"""
Standalone Suno music generation experiment.

Uses saved cookie (confirmed working) + nodriver browser to:
1. Open suno.com/create with cookies injected
2. Ensure Advanced mode is active
3. Fill lyrics (data-testid="lyrics-textarea"), title, style tags (textarea maxlength=1000)
4. Click Create (aria-label="Create song")
5. User solves captcha (if any) in the browser
6. Intercept the generate/v2 network request via CDP
7. Capture the response (clips with audio URLs)
8. Poll until clips are ready, download MP3s

Run: .venv/bin/python3 test_suno_gen.py
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# ── Load config + cookie ──────────────────────────────────────────────────────

sys.path.insert(0, ".")
from core.config import load_config

config = load_config()
COOKIE_STR = config.get("suno_cookie", "")
OUTPUT_DIR = config.get("output_folder", "./downloads")
if not COOKIE_STR:
    print("ERROR: No suno_cookie. Run the app and connect your account first.")
    sys.exit(1)

# ── The 3 test songs ──────────────────────────────────────────────────────────

SONG_FILES = [
    "/Users/nhanvu/Documents/AI_project/auto_generated_lyric/song/beside_the_door.txt",
    "/Users/nhanvu/Documents/AI_project/auto_generated_lyric/song/blueprint_for_two.txt",
    "/Users/nhanvu/Documents/AI_project/auto_generated_lyric/song/borrowed_line.txt",
]


def parse_song_file(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    footer = re.search(r"^Title:", text, re.MULTILINE)
    lyrics = text[:footer.start()].strip() if footer else text.strip()
    title_m = re.search(r"^Title:\s*(.+)$", text, re.MULTILINE)
    genre_m = re.search(r"^Genre:\s*(.+)$", text, re.MULTILINE)
    bpm_m   = re.search(r"^BPM:\s*(\d+)$", text, re.MULTILINE)
    theme_m = re.search(r"^Theme:\s*(.+)$", text, re.MULTILINE)

    title = title_m.group(1).strip() if title_m else Path(path).stem
    genre = genre_m.group(1).strip() if genre_m else "pop"
    bpm   = bpm_m.group(1) if bpm_m else ""
    theme = theme_m.group(1).strip() if theme_m else ""

    # Build tags from metadata
    tag_parts = [genre]
    if bpm:
        tag_parts.append(f"{bpm} bpm")
    if theme:
        tag_parts.append(theme)
    tags = ", ".join(tag_parts)

    return {"title": title, "lyrics": lyrics, "tags": tags, "file": path}


SONGS = [parse_song_file(f) for f in SONG_FILES]

print("Songs loaded:")
for s in SONGS:
    print(f"  • {s['title']} — tags: {s['tags']}")
print()

# ── Browser-based generation (one song at a time) ────────────────────────────

SUNO_CREATE = "https://suno.com/create"
SUNO_COOKIE_DOMAINS = {"suno.com", ".suno.com", "clerk.suno.com"}


def log(msg: str):
    print(f"  [{msg}]")


async def generate_one_song_via_browser(song: dict, cookie_str: str) -> list[dict]:
    """
    Open browser → inject cookies → fill form → click Create →
    user solves captcha → intercept generate/v2 → return clips.
    """
    import nodriver as uc
    from nodriver import cdp

    print(f"\n{'='*60}")
    print(f"GENERATING: {song['title']}")
    print(f"Tags: {song['tags']}")
    print(f"{'='*60}")

    # ── Launch browser ────────────────────────────────────────────────────────
    log("Launching browser…")
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--window-size=1280,900",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
        no_sandbox=True,
    )

    try:
        # ── Inject cookies ────────────────────────────────────────────────────
        log("Injecting cookies…")
        tab = await browser.get("about:blank")
        await asyncio.sleep(1)

        cookie_count = 0
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if not name or not value:
                continue
            try:
                await tab.send(cdp.network.set_cookie(
                    name=name, value=value,
                    domain=".suno.com", path="/", secure=True,
                ))
                cookie_count += 1
            except Exception:
                pass
        log(f"Injected {cookie_count} cookies")

        # ── Navigate to /create ───────────────────────────────────────────────
        log("Opening suno.com/create…")
        tab = await browser.get(SUNO_CREATE)
        await asyncio.sleep(6)

        # Stealth
        try:
            await tab.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false, configurable: true
                });
            """)
        except Exception:
            pass

        # Check URL
        current_url = await tab.evaluate("window.location.href")
        log(f"Current URL: {current_url}")
        if "/sign-in" in str(current_url):
            raise RuntimeError("Redirected to sign-in — cookies expired!")

        # ── Dump page elements ────────────────────────────────────────────────
        log("Scanning page elements…")
        dump = await tab.evaluate("""
            JSON.stringify({
                textareas: [...document.querySelectorAll('textarea')].map(t => ({
                    cls: t.className, ph: t.placeholder || '',
                    vis: t.offsetParent !== null, rows: t.rows
                })),
                inputs: [...document.querySelectorAll('input')]
                    .filter(i => i.offsetParent !== null)
                    .map(i => ({ type: i.type, ph: i.placeholder || '' })),
                buttons: [...document.querySelectorAll('button')]
                    .filter(b => b.offsetParent !== null)
                    .map(b => ({
                        text: b.textContent.trim().substring(0, 50),
                        aria: b.getAttribute('aria-label') || '',
                        disabled: b.disabled
                    }))
            })
        """)
        try:
            info = json.loads(dump)
        except Exception:
            info = {}
            log(f"Raw dump: {str(dump)[:300]}")

        log(f"Found: {len(info.get('textareas',[]))} textareas, "
            f"{len(info.get('inputs',[]))} inputs, "
            f"{len(info.get('buttons',[]))} buttons")
        for ta in info.get("textareas", []):
            log(f"  TEXTAREA cls='{ta.get('cls','')}' ph='{ta.get('ph','')}' vis={ta.get('vis')}")
        for inp in info.get("inputs", []):
            log(f"  INPUT type='{inp.get('type','')}' ph='{inp.get('ph','')}'")
        for btn in info.get("buttons", [])[:20]:
            log(f"  BUTTON text='{btn.get('text','')}' aria='{btn.get('aria','')}' disabled={btn.get('disabled')}")

        # ── Switch to Advanced mode ───────────────────────────────────────────
        # Suno checks event.isTrusted — both JS .click() and nodriver CDP clicks
        # get filtered. Solution: call React's onClick handler directly via
        # __reactProps$ on the DOM node, bypassing event dispatch entirely.
        log("Switching to Advanced mode…")
        mode_result = await tab.evaluate("""
            (() => {
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(b => b.textContent.trim() === 'Advanced');
                if (!btn) return 'not_found';

                // Strategy 1: Call React's internal onClick/onMouseDown directly
                const propsKey = Object.keys(btn).find(k => k.startsWith('__reactProps$'));
                if (propsKey) {
                    const props = btn[propsKey];
                    const handlers = Object.keys(props || {}).filter(k =>
                        k.startsWith('on') && typeof props[k] === 'function'
                    );
                    // Try onClick first, then onMouseDown, onPointerDown
                    const tryOrder = ['onClick', 'onMouseDown', 'onPointerDown',
                                      'onPointerUp', 'onMouseUp'];
                    for (const name of tryOrder) {
                        if (props[name]) {
                            props[name]({
                                bubbles: true,
                                cancelable: true,
                                preventDefault: () => {},
                                stopPropagation: () => {},
                                currentTarget: btn,
                                target: btn,
                                nativeEvent: { isTrusted: true },
                            });
                            return 'react_fiber:' + name + ' handlers=' + handlers.join(',');
                        }
                    }
                    return 'no_handler found=' + handlers.join(',');
                }

                // Strategy 2: Try broader React internal key prefix
                const reactKey = Object.keys(btn).find(k => k.startsWith('__react'));
                return 'no_reactProps key=' + (reactKey || 'none');
            })()
        """)
        log(f"Advanced mode: {mode_result}")
        await asyncio.sleep(2)

        # Verify toggle actually switched
        mode_check = await tab.evaluate("""
            (() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.textContent.trim() === 'Advanced') {
                        return b.classList.contains('active') ? 'active' : 'inactive';
                    }
                }
                return 'not_found';
            })()
        """)
        log(f"Advanced mode status: {mode_check}")

        if mode_check != 'active':
            # Fallback: try CDP dispatchMouseEvent with real coordinates
            log("React fiber didn't work, trying CDP mouse at coordinates…")
            try:
                coords_json = await tab.evaluate("""
                    (() => {
                        const btns = [...document.querySelectorAll('button')];
                        const btn = btns.find(b => b.textContent.trim() === 'Advanced');
                        if (!btn) return 'null';
                        const r = btn.getBoundingClientRect();
                        return JSON.stringify({x: r.left + r.width/2, y: r.top + r.height/2});
                    })()
                """)
                if coords_json and coords_json != 'null':
                    coords = json.loads(coords_json)
                    x, y = coords["x"], coords["y"]
                    from nodriver import cdp as _cdp
                    await tab.send(_cdp.input_.dispatch_mouse_event(
                        type_="mousePressed", x=x, y=y,
                        button=_cdp.input_.MouseButton.LEFT, click_count=1))
                    await asyncio.sleep(0.05)
                    await tab.send(_cdp.input_.dispatch_mouse_event(
                        type_="mouseReleased", x=x, y=y,
                        button=_cdp.input_.MouseButton.LEFT, click_count=1))
                    log(f"CDP click at ({x:.0f}, {y:.0f})")
                    await asyncio.sleep(2)
            except Exception as e:
                log(f"CDP click fallback failed: {e}")

        # ── Fill lyrics (using data-testid) ──────────────────────────────────
        log("Filling lyrics…")
        escaped_lyrics = json.dumps(song["lyrics"])
        lyrics_result = await tab.evaluate(f"""
            (() => {{
                let ta = document.querySelector('textarea[data-testid="lyrics-textarea"]');
                if (!ta) {{
                    // Fallback: find by placeholder
                    const all = document.querySelectorAll('textarea');
                    for (const t of all) {{
                        if (t.placeholder && t.placeholder.includes('lyrics')) {{
                            ta = t; break;
                        }}
                    }}
                }}
                if (!ta) return 'NO_LYRICS_TEXTAREA';

                // Focus first to trigger React's internal state
                ta.focus();

                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(ta, {escaped_lyrics});

                // Reset React's internal value tracker
                const tracker = ta._valueTracker;
                if (tracker) tracker.setValue('');

                // Dispatch events React listens to
                ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                ta.dispatchEvent(new Event('change', {{bubbles: true}}));

                return 'OK:' + ta.value.substring(0, 60);
            }})()
        """)
        log(f"Lyrics fill: {lyrics_result}")
        await asyncio.sleep(0.5)

        # ── Fill title ────────────────────────────────────────────────────────
        log("Filling title…")
        escaped_title = json.dumps(song["title"])
        title_result = await tab.evaluate(f"""
            (() => {{
                const inputs = [...document.querySelectorAll('input')]
                    .filter(i => i.offsetParent !== null);
                for (const inp of inputs) {{
                    const ph = (inp.placeholder || '').toLowerCase();
                    if (ph.includes('title') || ph.includes('name') || ph.includes('song')) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(inp, {escaped_title});
                        const tracker = inp._valueTracker;
                        if (tracker) tracker.setValue('');
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return 'OK:' + inp.placeholder;
                    }}
                }}
                return 'NO_TITLE_INPUT';
            }})()
        """)
        log(f"Title fill: {title_result}")
        await asyncio.sleep(0.5)

        # ── Fill style/tags (it's a TEXTAREA with maxlength="1000") ────────
        log("Filling style tags…")
        escaped_tags = json.dumps(song["tags"])
        tags_result = await tab.evaluate(f"""
            (() => {{
                // The styles textarea has maxlength="1000" — unique identifier
                let ta = document.querySelector('textarea[maxlength="1000"]');
                if (!ta) {{
                    // Fallback: find visible textarea that's NOT lyrics
                    const all = [...document.querySelectorAll('textarea')]
                        .filter(t => t.offsetParent !== null
                            && !t.hasAttribute('data-testid'));
                    ta = all[0] || null;
                }}
                if (!ta) return 'NO_STYLE_TEXTAREA';

                ta.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(ta, {escaped_tags});
                const tracker = ta._valueTracker;
                if (tracker) tracker.setValue('');
                ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                ta.dispatchEvent(new Event('change', {{bubbles: true}}));
                return 'OK:' + ta.value.substring(0, 60);
            }})()
        """)
        log(f"Tags fill: {tags_result}")
        await asyncio.sleep(0.5)

        # ── Set up CDP interception (Network-only, no Fetch) ─────────────────
        # Fetch and Network domains use DIFFERENT request ID namespaces,
        # so we use Network-only: requestWillBeSent → loadingFinished → getResponseBody
        log("Setting up Network interception…")
        captured = {
            "response_body": None,
            "post_request_id": None,
        }
        intercept_done = asyncio.Event()

        async def on_request_will_be_sent(event):
            """Detect the POST to generate/v2 and store its Network request ID."""
            req = event.request
            url = req.url if req else ""
            if "api/generate/v2" in url and req.method == "POST":
                captured["post_request_id"] = event.request_id
                log(f"POST generate/v2 detected (rid={event.request_id})")

        async def on_response(event):
            """Log generate/v2 responses for debugging."""
            url = event.response.url if event.response else ""
            if "api/generate/v2" in url:
                code = event.response.status if event.response else 0
                is_post = event.request_id == captured.get("post_request_id")
                log(f"generate/v2 response: HTTP {code} is_post={is_post}")

        async def on_loading_finished(event):
            """Read response body when the POST response is fully loaded."""
            post_id = captured.get("post_request_id")
            if not post_id or event.request_id != post_id:
                return
            log(f"POST response body ready")
            for attempt in range(5):
                try:
                    body_result = await tab.send(
                        cdp.network.get_response_body(event.request_id)
                    )
                    if body_result and body_result[0]:
                        captured["response_body"] = body_result[0]
                        log(f"Response body captured: {len(body_result[0])} chars")
                        break
                except Exception as e:
                    log(f"Body read attempt {attempt+1} failed: {e}")
                    await asyncio.sleep(1)
            intercept_done.set()

        # Network-only — consistent request IDs across all events
        await tab.send(cdp.network.enable())
        tab.add_handler(cdp.network.RequestWillBeSent, on_request_will_be_sent)
        tab.add_handler(cdp.network.ResponseReceived, on_response)
        tab.add_handler(cdp.network.LoadingFinished, on_loading_finished)
        log("Interception ready")

        # ── Snapshot existing clip IDs (for DOM fallback later) ────────────
        existing_ids_json = await tab.evaluate("""
            JSON.stringify(
                [...document.querySelectorAll('a[href^="/song/"]')]
                    .map(a => (a.href.match(/\\/song\\/([a-f0-9-]{36})/) || [])[1])
                    .filter(Boolean)
            )
        """)
        try:
            existing_clip_ids = set(json.loads(existing_ids_json))
        except Exception:
            existing_clip_ids = set()
        log(f"Existing clips in workspace: {len(existing_clip_ids)}")

        # ── Click Create button ───────────────────────────────────────────────
        log("Looking for Create button…")
        await asyncio.sleep(1)
        click_result = await tab.evaluate("""
            (() => {
                // Primary: aria-label="Create song"
                let btn = document.querySelector('button[aria-label="Create song"]');
                if (!btn) {
                    // Fallback: find by text content
                    const btns = [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null);
                    for (const b of btns) {
                        const txt = b.textContent.trim();
                        if (txt === 'Create' || txt.includes('Create')) {
                            if (b.closest('[class*="playbar"]') || b.closest('nav')) continue;
                            // Skip sidebar "Create New Workspace" etc
                            if (txt.includes('Workspace') || txt.includes('New')) continue;
                            btn = b;
                            break;
                        }
                    }
                }
                if (!btn) return 'NOT_FOUND';

                if (btn.disabled) {
                    // Force remove disabled and click
                    btn.disabled = false;
                    btn.click();
                    return 'FORCE_CLICKED (was disabled)';
                }
                btn.click();
                return 'clicked';
            })()
        """)
        log(f"Create button: {click_result}")

        if "NOT_FOUND" in str(click_result):
            log("Create button NOT FOUND — check browser window")

        # ── Wait for captcha + intercept ──────────────────────────────────────
        log("Waiting for generation… (solve captcha in browser if it appears)")
        log("  If no captcha appears, generation will proceed automatically.")
        deadline = asyncio.get_event_loop().time() + 300  # 5 min timeout

        poll_count = 0
        while asyncio.get_event_loop().time() < deadline:
            try:
                await asyncio.wait_for(intercept_done.wait(), timeout=10.0)
                break
            except asyncio.TimeoutError:
                poll_count += 1
                try:
                    _ = browser.tabs
                except Exception:
                    raise RuntimeError("Browser was closed!")

                if poll_count % 3 == 0:
                    try:
                        state = await tab.evaluate("""
                            JSON.stringify({
                                captcha: !!document.querySelector(
                                    'iframe[title*="hCaptcha"], iframe[src*="hcaptcha"]'
                                ),
                                modal: !!document.querySelector('[role="dialog"]'),
                                url: window.location.href.substring(0, 60)
                            })
                        """)
                        log(f"Browser state: {state}")
                    except Exception:
                        log("Could not read browser state")
                continue

        # ── Parse results ─────────────────────────────────────────────────────
        clips = []
        if captured["response_body"]:
            try:
                resp = json.loads(captured["response_body"])
                clips = resp.get("clips", [])
            except Exception:
                log(f"Could not parse response: {captured['response_body'][:200]}")

        # Fallback: if CDP didn't capture clips, scrape clip IDs from the DOM
        if not clips and not intercept_done.is_set():
            log("CDP capture timed out — scraping clip IDs from workspace DOM…")

        if not clips:
            log("Trying DOM fallback: extracting NEW clip IDs from page…")
            # Wait for new clips to appear in workspace (poll DOM every 3s)
            for wait_round in range(10):
                await asyncio.sleep(3)
                dom_clips_json = await tab.evaluate("""
                    JSON.stringify(
                        [...document.querySelectorAll('a[href^="/song/"]')]
                            .map(a => (a.href.match(/\\/song\\/([a-f0-9-]{36})/) || [])[1])
                            .filter(Boolean)
                    )
                """)
                try:
                    all_ids = set(json.loads(dom_clips_json))
                    new_ids = all_ids - existing_clip_ids
                    if new_ids:
                        log(f"Found {len(new_ids)} NEW clip IDs from DOM")
                        clips = [{"id": cid, "status": "submitted"} for cid in new_ids]
                        break
                except Exception:
                    pass
                if wait_round % 3 == 2:
                    log(f"Waiting for clips to appear… ({(wait_round+1)*3}s)")

        log(f"Got {len(clips)} clip(s)")
        for c in clips:
            log(f"  clip id={c.get('id')} status={c.get('status')}")

        return clips

    finally:
        log("Closing browser…")
        try:
            await browser.stop()
        except Exception:
            pass


# ── Poll + Download ───────────────────────────────────────────────────────────

def poll_and_download(clips: list[dict], song_title: str):
    """Use the confirmed-working SunoClient for polling + download."""
    if not clips:
        print("  No clips to download.")
        return

    from core.suno_client import SunoClient

    client = SunoClient(COOKIE_STR, on_log=lambda m: print(f"  [{m}]"))
    clip_ids = [c["id"] for c in clips]

    print(f"  Polling {len(clip_ids)} clips…")
    final = client.poll_until_done(
        clip_ids,
        on_status=lambda m: print(f"  [{m}]"),
        timeout=300,
    )

    # If clips are still "streaming", wait a bit more for them to finish encoding
    still_streaming = [c for c in final if c.get("status") == "streaming"]
    if still_streaming:
        print(f"  {len(still_streaming)} clip(s) still streaming, waiting 15s for encoding…")
        time.sleep(15)
        # Re-poll to get "complete" status + final audio URLs
        final = client.poll_until_done(
            clip_ids,
            on_status=lambda m: print(f"  [{m}]"),
            timeout=120,
        )

    # Download
    out = Path(OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\s-]", "", song_title.lower())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")[:50] or "suno"

    for idx, clip in enumerate(final, 1):
        status = clip.get("status", "")
        audio_url = clip.get("audio_url", "")
        if status == "error":
            err = clip.get("metadata", {}).get("error_message", "?")
            print(f"  ✗ Clip {idx} failed: {err}")
            continue
        if not audio_url:
            print(f"  ✗ Clip {idx} has no audio URL")
            continue
        dest = out / f"{slug}_{idx}.mp3"
        print(f"  Downloading clip {idx} → {dest.name}")
        # Retry download up to 3 times (CDN may not be ready yet)
        for attempt in range(3):
            try:
                client.download_mp3(audio_url, str(dest))
                print(f"  ✓ Saved: {dest}")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  ⚠ Download attempt {attempt+1} failed: {e}, retrying in 10s…")
                    time.sleep(10)
                else:
                    print(f"  ✗ Download failed after 3 attempts: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    # Only process the FIRST song for initial testing
    # Change to SONGS[:3] once confirmed working
    for song in SONGS[:1]:
        try:
            clips = await generate_one_song_via_browser(song, COOKIE_STR)
            if clips:
                poll_and_download(clips, song["title"])
            else:
                print(f"  No clips returned for {song['title']}")
        except Exception as e:
            print(f"  ERROR: {e}")

        print()

    print("DONE!")


if __name__ == "__main__":
    asyncio.run(main())
