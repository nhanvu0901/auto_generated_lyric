"""
Standalone test: Direct HTTP generation with Suno API.

No browser during generation — pure HTTP requests.
Implements: Clerk 4.74.0 pin, consistent macOS headers, rate limiting.

Usage:
    cd lyric_studio
    .venv/bin/python3 test_suno_direct.py
"""

import sys
import time
import uuid
import requests
from pathlib import Path

sys.path.insert(0, ".")
from core.config import load_config

# ── Constants ────────────────────────────────────────────────────────────────

CLERK_BASE    = "https://auth.suno.com"
CLERK_JS_VER  = "4.74.0"                        # pinned: pre-fraud-detection
CLERK_API_VER = "2024-10-04"                     # match the older Clerk era
STUDIO_BASE   = "https://studio-api.prod.suno.com"

# Consistent macOS Chrome fingerprint — no Android/mobile mismatch
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

CLERK_HEADERS_BASE = {
    "User-Agent": UA,
    "Origin":     "https://suno.com",
    "Referer":    "https://suno.com/",
    "sec-ch-ua":          '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest":     "empty",
    "sec-fetch-mode":     "cors",
    "sec-fetch-site":     "same-site",
    "Accept":             "application/json",
}

API_HEADERS_BASE = {
    **CLERK_HEADERS_BASE,
    "Content-Type": "application/json",
}

TERMINAL_STATUSES = {"streaming", "complete", "error"}

# ── Cookie helpers ───────────────────────────────────────────────────────────

def parse_cookies(cookie_str: str) -> dict[str, str]:
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, value = part.split("=", 1)
            name = name.strip()
            if name and value:
                result[name] = value
    return result


def serial(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_session_id(cookies: dict[str, str]) -> str:
    """Exchange __client cookie for a Clerk session ID."""
    url = (
        f"{CLERK_BASE}/v1/client"
        f"?__clerk_api_version={CLERK_API_VER}"
        f"&_clerk_js_version={CLERK_JS_VER}"
    )
    headers = {**CLERK_HEADERS_BASE, "Cookie": serial(cookies)}

    for attempt in range(3):
        if attempt:
            time.sleep(3)
        r = requests.get(url, headers=headers, timeout=15)
        print(f"  Clerk /v1/client → {r.status_code}")
        if r.status_code != 200:
            print(f"  Response: {r.text[:300]}")
            continue
        resp = r.json().get("response", {})

        sid = resp.get("last_active_session_id")
        if not sid:
            sessions = resp.get("sessions", [])
            active = [s for s in sessions if s.get("status") == "active"]
            sid = (active or sessions or [{}])[0].get("id")
        if sid:
            return sid

    raise RuntimeError("Could not get session ID from Clerk")


def get_jwt(cookies: dict[str, str], session_id: str) -> str:
    """Mint a short-lived JWT (~60s) from Clerk."""
    url = (
        f"{CLERK_BASE}/v1/client/sessions/{session_id}/tokens"
        f"?__clerk_api_version={CLERK_API_VER}"
        f"&_clerk_js_version={CLERK_JS_VER}"
    )
    headers = {**CLERK_HEADERS_BASE, "Cookie": serial(cookies)}
    r = requests.post(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()["jwt"]


# ── Generation ───────────────────────────────────────────────────────────────

def generate(cookies: dict[str, str], jwt: str, device_id: str,
             lyrics: str, tags: str, title: str, model: str = "chirp-auk") -> list[dict]:
    """POST to /api/generate/v2/ — returns list of clip dicts."""
    headers = {
        **API_HEADERS_BASE,
        "Authorization": f"Bearer {jwt}",
        "Cookie":        serial(cookies),
        "Device-Id":     f'"{device_id}"',
    }
    payload = {
        "prompt":             lyrics,
        "tags":               tags,
        "title":              title,
        "mv":                 model,
        "make_instrumental":  False,
    }
    print(f"  POST /api/generate/v2/  model={model}")
    r = requests.post(
        f"{STUDIO_BASE}/api/generate/v2/",
        json=payload,
        headers=headers,
        timeout=30,
    )
    print(f"  → {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:500]}")
    r.raise_for_status()
    clips = r.json().get("clips", [])
    if not clips:
        raise RuntimeError("No clips returned")
    return clips


def poll(cookies: dict[str, str], session_id: str, clip_ids: list[str],
         timeout: int = 300) -> list[dict]:
    """Poll /api/feed/v2 until all clips reach a terminal status."""
    ids_str = ",".join(clip_ids)
    url = f"{STUDIO_BASE}/api/feed/v2?ids={ids_str}"
    deadline = time.time() + timeout

    time.sleep(5)  # initial back-off

    while time.time() < deadline:
        jwt = get_jwt(cookies, session_id)
        headers = {
            **API_HEADERS_BASE,
            "Authorization": f"Bearer {jwt}",
            "Cookie":        serial(cookies),
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        clips = r.json().get("clips", [])

        statuses = [c.get("status", "unknown") for c in clips]
        print(f"  Poll: {', '.join(statuses)}")

        if all(s in TERMINAL_STATUSES for s in statuses):
            return clips

        time.sleep(5)

    print("  ⚠ Timed out waiting for clips")
    return []


def download(audio_url: str, dest: str) -> None:
    r = requests.get(audio_url, stream=True, timeout=90)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Load saved cookie
    config = load_config()
    cookie_str = config.get("suno_cookie", "")
    output_dir = config.get("output_folder", str(Path.home() / "LyricStudio" / "output"))

    if not cookie_str or "__client" not in cookie_str:
        print("ERROR: No suno_cookie in config. Connect your account first.")
        sys.exit(1)

    cookies = parse_cookies(cookie_str)
    device_id = str(uuid.uuid4())
    print(f"Cookies: {len(cookies)} keys, has __client: {'__client' in cookies}")

    # 2. Auth — session ID + JWT
    print("\n── Auth ──")
    session_id = get_session_id(cookies)
    print(f"  Session ID: {session_id}")
    jwt = get_jwt(cookies, session_id)
    print(f"  JWT: {len(jwt)} chars")

    # 3. Credits check
    print("\n── Credits ──")
    credits_headers = {
        **API_HEADERS_BASE,
        "Authorization": f"Bearer {jwt}",
        "Cookie":        serial(cookies),
    }
    r = requests.get(f"{STUDIO_BASE}/api/billing/info/", headers=credits_headers, timeout=15)
    if r.status_code == 200:
        info = r.json()
        print(f"  Credits left: {info.get('total_credits_left', '?')}")
    else:
        print(f"  Credits check failed: {r.status_code} {r.text[:200]}")

    # 4. Generate — simple test song
    print("\n── Generate ──")
    test_lyrics = """[Verse]
Walking down the empty street at dawn
City lights are fading one by one
Coffee cup in hand and thoughts run free
This morning belongs to only me

[Chorus]
Brand new day, brand new start
Sun is painting colors on my heart
Every step I take feels like a song
Brand new day, I'm moving on"""

    test_tags = "pop, acoustic, upbeat, morning vibes"
    test_title = "Brand New Day"

    # Refresh JWT right before generation
    jwt = get_jwt(cookies, session_id)

    try:
        clips = generate(cookies, jwt, device_id,
                         test_lyrics, test_tags, test_title)
    except requests.HTTPError as e:
        print(f"\n  FAILED: {e}")
        print(f"  This likely means captcha was triggered.")
        print(f"  → Layer 2/3 fallback would activate here.")
        sys.exit(1)

    print(f"  Got {len(clips)} clip(s):")
    for c in clips:
        print(f"    id={c.get('id')}  status={c.get('status')}")

    # 5. Poll until done
    print("\n── Polling ──")
    clip_ids = [c["id"] for c in clips]
    final_clips = poll(cookies, session_id, clip_ids)

    # 6. Download
    print("\n── Download ──")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for idx, clip in enumerate(final_clips, 1):
        status = clip.get("status", "")
        audio_url = clip.get("audio_url", "")

        if status == "error":
            err = clip.get("metadata", {}).get("error_message", "unknown")
            print(f"  Clip {idx} FAILED: {err}")
            continue
        if not audio_url:
            print(f"  Clip {idx} has no audio URL — skipping")
            continue

        dest = out / f"test_brand_new_day_{idx}.mp3"
        print(f"  Downloading clip {idx} → {dest.name}")
        download(audio_url, str(dest))
        print(f"  ✓ Saved: {dest}")

    print("\n── Done ──")


if __name__ == "__main__":
    main()