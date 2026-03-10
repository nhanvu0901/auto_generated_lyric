"""Suno direct HTTP API client.

Architecture:
  - Uses the cookie captured by suno_auth.login_and_get_cookies()
  - Exchanges session ID for a short-lived JWT via Clerk FAPI
  - Refreshes that JWT every 30 s in a background daemon thread
  - Calls studio-api.prod.suno.com for generation, polling, billing
  - Downloads finished MP3s directly from the CDN (no auth needed)

Suno always returns TWO clips per generation request.
"""

import re
import time
import uuid
import threading
import requests
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable, Optional


# ── Constants ──────────────────────────────────────────────────────────────────

CLERK_BASE      = "https://clerk.suno.com"
CLERK_JS_VER    = "4.73.2"
STUDIO_BASE     = "https://studio-api.prod.suno.com"
DEFAULT_MODEL   = "chirp-v4"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "Affiliate-Id": "undefined",
    "x-suno-client": "Android prerelease-4nt180t 1.0.42",
    "X-Requested-With": "com.suno.android",
    "sec-ch-ua": '"Chromium";v="130", "Android WebView";v="130", "Not?A_Brand";v="99"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "User-Agent": _UA,
}

# Generation status values returned by Suno
TERMINAL_STATUSES = {"streaming", "complete", "error"}

# Available Suno model versions
SUNO_MODELS = {
    "V4 (Recommended)": "chirp-v4",
    "V4.5 (8-min max)": "chirp-v4-5",
    "V3.5 (Fast)":      "chirp-v3-5",
}


# ── Cookie helpers ─────────────────────────────────────────────────────────────

def _parse_cookie_str(cookie_str: str) -> dict[str, str]:
    sc = SimpleCookie()
    sc.load(cookie_str)
    return {k: m.value for k, m in sc.items() if m.value}


def _serial(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# ── Main client ────────────────────────────────────────────────────────────────

class SunoClient:
    """
    Thread-safe Suno API client.

    Usage:
        client = SunoClient(cookie_str)          # starts JWT keepalive thread
        clips  = client.generate(lyrics, tags, title)
        paths  = client.wait_and_download(clips, output_dir, on_status=...)
        credits = client.get_credits()
    """

    def __init__(self, cookie_str: str) -> None:
        self._cookies: dict[str, str] = _parse_cookie_str(cookie_str)
        self._device_id: str = str(uuid.uuid4())
        self._session_id: Optional[str] = None
        self._token: Optional[str] = None
        self._lock = threading.Lock()

        self._session_id = self._fetch_session_id()
        self._do_refresh_token()
        self._start_keepalive()

    # ── Auth internals ─────────────────────────────────────────────────────────

    def _clerk_headers(self) -> dict:
        return {
            **_BASE_HEADERS,
            "Authorization": self._cookies.get("__client", ""),
            "Cookie": _serial(self._cookies),
        }

    def _api_headers(self) -> dict:
        with self._lock:
            token = self._token or ""
        return {
            **_BASE_HEADERS,
            "Authorization": f"Bearer {token}",
            "Cookie": _serial(self._cookies),
            "Content-Type": "application/json",
            "Device-Id": f'"{self._device_id}"',
        }

    def _fetch_session_id(self) -> str:
        url = (
            f"{CLERK_BASE}/v1/client"
            f"?__clerk_api_version=2025-11-10"
            f"&_clerk_js_version={CLERK_JS_VER}"
        )
        r = requests.get(url, headers=self._clerk_headers(), timeout=15)
        r.raise_for_status()
        sid = r.json()["response"]["last_active_session_id"]
        if not sid:
            raise RuntimeError(
                "No active Suno session found — cookie may have expired. "
                "Please reconnect your Suno account in Settings."
            )
        return sid

    def _do_refresh_token(self) -> None:
        url = (
            f"{CLERK_BASE}/v1/client/sessions/{self._session_id}/tokens"
            f"?__clerk_api_version=2025-11-10"
            f"&_clerk_js_version={CLERK_JS_VER}"
        )
        r = requests.post(url, headers=self._clerk_headers(), timeout=15)
        r.raise_for_status()
        with self._lock:
            self._token = r.json()["jwt"]

    def _start_keepalive(self) -> None:
        """Refresh JWT every 30 s in background so it never expires (60 s TTL)."""
        def _loop() -> None:
            while True:
                time.sleep(30)
                try:
                    self._do_refresh_token()
                except Exception:
                    pass
        threading.Thread(target=_loop, daemon=True, name="suno-keepalive").start()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_credits(self) -> dict:
        """Return billing info: credits_left, monthly_limit, monthly_usage."""
        self._do_refresh_token()
        r = requests.get(
            f"{STUDIO_BASE}/api/billing/info/",
            headers=self._api_headers(),
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        return {
            "credits_left":  d.get("total_credits_left"),
            "monthly_limit": d.get("monthly_limit"),
            "monthly_usage": d.get("monthly_usage"),
        }

    def generate(
        self,
        lyrics: str,
        tags: str,
        title: str,
        model: str = DEFAULT_MODEL,
        make_instrumental: bool = False,
        negative_tags: str = "",
    ) -> list[dict]:
        """
        Submit a custom-lyrics generation request.

        Returns a list of clip dicts (Suno always returns 2 clips).
        Each dict has at minimum: id, status, title.
        """
        self._do_refresh_token()
        payload = {
            "prompt": lyrics,
            "tags": tags,
            "title": title,
            "negative_tags": negative_tags,
            "mv": model,
            "make_instrumental": make_instrumental,
            "generation_type": "TEXT",
            "continue_clip_id": None,
            "continue_at": None,
            "infill_start_s": None,
            "infill_end_s": None,
            "task": None,
            "token": "",  # empty = rely on session trust; fill with hCaptcha if 403
        }
        r = requests.post(
            f"{STUDIO_BASE}/api/generate/v2/",
            json=payload,
            headers=self._api_headers(),
            timeout=30,
        )
        if r.status_code == 402:
            raise RuntimeError("Insufficient Suno credits.")
        if r.status_code == 403:
            raise RuntimeError(
                "Suno returned 403 — session may have expired. "
                "Please reconnect your account in Settings."
            )
        r.raise_for_status()
        clips = r.json().get("clips", [])
        if not clips:
            raise RuntimeError("Suno returned no clips — unexpected API response.")
        return clips

    def poll_until_done(
        self,
        clip_ids: list[str],
        on_status: Optional[Callable[[str], None]] = None,
        timeout: int = 300,
        poll_interval: float = 5.0,
    ) -> list[dict]:
        """
        Poll /api/feed/v2 until all clips reach a terminal status.

        Terminal statuses: 'streaming', 'complete', 'error'.
        Returns the final list of clip dicts.
        """
        ids_str = ",".join(clip_ids)
        url = f"{STUDIO_BASE}/api/feed/v2?ids={ids_str}"
        deadline = time.time() + timeout

        time.sleep(5)  # initial back-off before first poll

        while time.time() < deadline:
            self._do_refresh_token()
            r = requests.get(url, headers=self._api_headers(), timeout=15)
            r.raise_for_status()
            clips = r.json().get("clips", [])

            statuses = [c.get("status", "unknown") for c in clips]
            if on_status:
                on_status(f"Rendering… ({', '.join(statuses)})")

            if all(s in TERMINAL_STATUSES for s in statuses):
                return clips

            time.sleep(poll_interval)

        if on_status:
            on_status("Timed out waiting for Suno to finish.")
        return []

    def download_mp3(self, audio_url: str, dest_path: str) -> str:
        """
        Download an MP3 from Suno's CDN. No auth needed for CDN URLs.
        Returns dest_path.
        """
        r = requests.get(audio_url, stream=True, timeout=90)
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
        return dest_path

    def wait_and_download(
        self,
        clips: list[dict],
        output_dir: str,
        song_title: str = "suno",
        on_status: Optional[Callable[[str], None]] = None,
    ) -> list[str]:
        """
        Full pipeline: poll → download all ready clips.

        Returns list of local MP3 file paths.
        """
        clip_ids = [c["id"] for c in clips]
        if on_status:
            on_status(f"Waiting for Suno to render {len(clip_ids)} clip(s)…")

        final_clips = self.poll_until_done(clip_ids, on_status=on_status)

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Clean title for filename
        slug = re.sub(r"[^\w\s-]", "", song_title.lower())
        slug = re.sub(r"[\s-]+", "_", slug).strip("_")[:50] or "suno"

        paths = []
        for idx, clip in enumerate(final_clips, start=1):
            status = clip.get("status", "")
            audio_url = clip.get("audio_url", "")
            clip_id = clip.get("id", f"clip{idx}")

            if status == "error":
                err = clip.get("metadata", {}).get("error_message", "unknown error")
                if on_status:
                    on_status(f"Clip {idx} failed: {err}")
                continue

            if not audio_url:
                if on_status:
                    on_status(f"Clip {idx} has no audio URL yet — skipping.")
                continue

            dest = out / f"{slug}_{idx}.mp3"
            # Avoid overwriting
            counter = 2
            while dest.exists():
                dest = out / f"{slug}_{idx}_{counter}.mp3"
                counter += 1

            if on_status:
                on_status(f"Downloading clip {idx} → {dest.name}…")
            self.download_mp3(audio_url, str(dest))
            paths.append(str(dest))

        return paths


# ── Convenience: validate a saved cookie ──────────────────────────────────────

def validate_cookie(cookie_str: str) -> tuple[bool, str]:
    """
    Quick check: try to fetch session ID with the stored cookie.
    Returns (ok: bool, message: str).
    """
    try:
        client = SunoClient(cookie_str)
        info = client.get_credits()
        left = info.get("credits_left", "?")
        return True, f"{left} credits remaining"
    except Exception as exc:
        return False, str(exc)
