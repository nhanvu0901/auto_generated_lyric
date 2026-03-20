"""
Standalone Suno music generation via browser automation.

Flow per song:
  1. Launch browser with saved cookies → navigate to suno.com/create
  2. Switch to Advanced mode, fill lyrics/title/style tags
  3. Click Create → user solves captcha if prompted
  4. Intercept the generate/v2 response via CDP to get clip IDs
  5. Poll clips via SunoClient HTTP API until complete
  6. Download MP3s, skip clips under 90s

Run:  python test_suno_gen.py
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

# ── Load config + cookie ──────────────────────────────────────────────────────

sys.path.insert(0, ".")
from core.config import load_config

config = load_config()
COOKIE_STR = config.get("suno_cookie", "")
OUTPUT_DIR = config.get("output_folder", "./downloads")
if not COOKIE_STR:
    print("ERROR: No suno_cookie. Run the app and connect your account first.")
    sys.exit(1)

# ── Song files to generate ───────────────────────────────────────────────────

SONG_FILES = [
    "/Users/nhanvu/Documents/AI_project/auto_generated_lyric/song/you_dont_go.txt",
]


def parse_song_file(path: str) -> dict:
    """Parse a song .txt file into {title, lyrics, tags, file}."""
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

    tag_parts = [genre]
    if bpm:
        tag_parts.append(f"{bpm} bpm")
    if theme:
        tag_parts.append(theme)

    return {"title": title, "lyrics": lyrics, "tags": ", ".join(tag_parts), "file": path}


SONGS = [parse_song_file(f) for f in SONG_FILES]

print("Songs loaded:")
for s in SONGS:
    print(f"  • {s['title']} — tags: {s['tags']}")
print()

# ── Shared helpers ────────────────────────────────────────────────────────────

SUNO_CREATE = "https://suno.com/create"


def log(msg: str):
    print(f"  [{msg}]")


# ── Browser-based generation (one song at a time) ────────────────────────────


async def generate_one_song_via_browser(song: dict, cookie_str: str) -> list[dict]:
    """
    Open browser → inject cookies → fill form → click Create →
    intercept generate/v2 via CDP → return clip dicts.
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
        await asyncio.sleep(15)

        # Hide webdriver flag from bot detection
        try:
            await tab.evaluate("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false, configurable: true
                });
            """)
        except Exception:
            pass

        current_url = await tab.evaluate("window.location.href")
        log(f"Current URL: {current_url}")
        if "/sign-in" in str(current_url):
            raise RuntimeError("Redirected to sign-in — cookies expired!")

        # ── Scan page elements (debug) ─────────────────────────────────────────
        # Only log textareas — those are the fields we need to fill.
        # Buttons/inputs are too noisy and rarely useful for debugging.
        log("Scanning page elements…")
        dump = await tab.evaluate("""
            JSON.stringify({
                textareas: [...document.querySelectorAll('textarea')].map(t => ({
                    cls: t.className, ph: t.placeholder || '',
                    vis: t.offsetParent !== null
                }))
            })
        """)
        try:
            info = json.loads(dump)
        except Exception:
            info = {}
        log(f"Found: {len(info.get('textareas',[]))} textareas")
        for ta in info.get("textareas", []):
            log(f"  TEXTAREA ph='{ta.get('ph','')}' vis={ta.get('vis')}")

        # ── Switch to Advanced mode ───────────────────────────────────────────
        # Suno filters untrusted events (isTrusted check). We bypass this by
        # calling React's internal onMouseDown handler directly via __reactProps$.
        log("Switching to Advanced mode…")
        mode_result = await tab.evaluate("""
            (() => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim() === 'Advanced');
                if (!btn) return 'not_found';

                const propsKey = Object.keys(btn).find(k => k.startsWith('__reactProps$'));
                if (!propsKey) return 'no_reactProps';

                const props = btn[propsKey];
                // onMouseDown is the handler Suno uses for tab switching
                const tryOrder = ['onClick', 'onMouseDown', 'onPointerDown'];
                for (const name of tryOrder) {
                    if (typeof props[name] === 'function') {
                        props[name]({
                            bubbles: true, cancelable: true,
                            preventDefault: () => {}, stopPropagation: () => {},
                            currentTarget: btn, target: btn,
                            nativeEvent: { isTrusted: true },
                        });
                        return 'ok:' + name;
                    }
                }
                return 'no_handler';
            })()
        """)
        log(f"Advanced mode: {mode_result}")
        await asyncio.sleep(2)

        # ── Fill lyrics ───────────────────────────────────────────────────────
        # The lyrics textarea uses data-testid="lyrics-textarea".
        # Native setter + input event works here (unlike style tags).
        log("Filling lyrics…")
        escaped_lyrics = json.dumps(song["lyrics"])
        lyrics_result = await tab.evaluate(f"""
            (() => {{
                let ta = document.querySelector('textarea[data-testid="lyrics-textarea"]');
                if (!ta) {{
                    const all = document.querySelectorAll('textarea');
                    for (const t of all) {{
                        if (t.placeholder && t.placeholder.includes('lyrics')) {{
                            ta = t; break;
                        }}
                    }}
                }}
                if (!ta) return 'NO_LYRICS_TEXTAREA';

                ta.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(ta, {escaped_lyrics});
                const tracker = ta._valueTracker;
                if (tracker) tracker.setValue('');
                ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                ta.dispatchEvent(new Event('change', {{bubbles: true}}));
                return 'OK:' + ta.value.substring(0, 60);
            }})()
        """)
        log(f"Lyrics fill: {lyrics_result}")
        await asyncio.sleep(0.5)

        # ── Fill title ────────────────────────────────────────────────────────
        # Find the visible input whose placeholder mentions "title".
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

        # ── Fill style/tags ───────────────────────────────────────────────────
        # The Styles textarea is a React controlled component. Only the React
        # fiber onChange approach works — we walk __reactFiber$ up the tree,
        # call onChange at each level, and set ta.value via native setter before
        # each call so event.target.value reads correctly.
        #
        # Why other approaches fail:
        #   - Native setter + InputEvent: React ignores synthetic InputEvents
        #   - execCommand('insertText'): wipes the value S3 just set
        log("Filling style tags…")
        escaped_tags = json.dumps(song["tags"])
        tags_result = await tab.evaluate(f"""
            (() => {{
                // Expand the Styles section if collapsed
                for (const el of document.querySelectorAll('[role="button"][aria-expanded="false"]')) {{
                    if (el.textContent.includes('Styles')) {{
                        const pk = Object.keys(el).find(k => k.startsWith('__reactProps$'));
                        if (pk && el[pk] && typeof el[pk].onClick === 'function') {{
                            el[pk].onClick({{
                                bubbles: true, cancelable: true,
                                preventDefault: () => {{}}, stopPropagation: () => {{}},
                                currentTarget: el, target: el,
                                nativeEvent: {{ isTrusted: true }},
                            }});
                        }} else {{
                            el.click();
                        }}
                        break;
                    }}
                }}

                // Locate: textarea[maxlength="1000"] is the style field.
                // Fallback: second textarea with the fog-dense placeholder class.
                let ta = document.querySelector('textarea[maxlength="1000"]');
                if (!ta) {{
                    const fogDense = [...document.querySelectorAll('textarea')]
                        .filter(t => t.className.includes('fog-dense'));
                    ta = fogDense.length >= 2 ? fogDense[1] : null;
                }}
                if (!ta) return 'NO_STYLE_TEXTAREA';

                const targetValue = {escaped_tags};

                // Walk React fiber tree and call onChange at each level
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                const fiberKey = Object.keys(ta).find(k =>
                    k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
                );
                if (!fiberKey) return 'NO_FIBER_KEY';

                let fiber = ta[fiberKey];
                let walked = 0;
                while (fiber && walked < 40) {{
                    const props = fiber.memoizedProps || fiber.pendingProps;
                    if (props && typeof props.onChange === 'function') {{
                        nativeSetter.call(ta, targetValue);
                        props.onChange({{
                            target: ta, currentTarget: ta,
                            bubbles: true, cancelable: true,
                            preventDefault: () => {{}}, stopPropagation: () => {{}},
                            nativeEvent: {{ isTrusted: true, data: targetValue, inputType: 'insertText' }},
                        }});
                    }}
                    fiber = fiber.return;
                    walked++;
                }}

                const val = ta.value;
                return val ? 'OK:' + val.substring(0, 60) : 'EMPTY_AFTER_FIBER';
            }})()
        """)
        log(f"Tags fill: {tags_result}")

        # Verify after one React render cycle; re-fill via fiber if wiped
        await asyncio.sleep(0.8)
        tags_verify = await tab.evaluate(f"""
            (() => {{
                const ta = document.querySelector('textarea[maxlength="1000"]')
                    || [...document.querySelectorAll('textarea')]
                        .filter(t => t.className.includes('fog-dense'))[1];
                if (!ta) return 'TEXTAREA_GONE';
                if (ta.value) return 'VERIFIED:' + ta.value.substring(0, 60);

                // Value wiped by React — re-fill via fiber onChange
                const targetValue = {escaped_tags};
                const ns = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                const fk = Object.keys(ta).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (!fk) return 'EMPTY_NO_FIBER';
                let fiber = ta[fk], w = 0;
                while (fiber && w < 40) {{
                    const props = fiber.memoizedProps || fiber.pendingProps;
                    if (props && typeof props.onChange === 'function') {{
                        ns.call(ta, targetValue);
                        props.onChange({{
                            target: ta, currentTarget: ta, bubbles: true,
                            preventDefault: () => {{}}, stopPropagation: () => {{}},
                            nativeEvent: {{ isTrusted: true, data: targetValue, inputType: 'insertText' }},
                        }});
                    }}
                    fiber = fiber.return; w++;
                }}
                return 'REFILLED:' + ta.value.substring(0, 60);
            }})()
        """)
        log(f"Tags verify: {tags_verify}")
        await asyncio.sleep(0.2)

        # ── Set up CDP network interception ───────────────────────────────────
        # We listen for the POST to api/generate/v2 and read its response body
        # once the network request finishes loading. This gives us the clip IDs.
        #
        # Pipeline: RequestWillBeSent (spot POST) → ResponseReceived (log status)
        #         → LoadingFinished (read body via getResponseBody)
        log("Setting up Network interception…")
        captured = {
            "response_body": None,
            "post_request_id": None,
        }
        intercept_done = asyncio.Event()

        async def on_request_will_be_sent(event):
            req = event.request
            url = req.url if req else ""
            if "api/generate/v2" in url and req.method == "POST":
                captured["post_request_id"] = event.request_id
                log(f"POST generate/v2 detected (rid={event.request_id})")

        async def on_response(event):
            url = event.response.url if event.response else ""
            if "api/generate/v2" in url:
                code = event.response.status if event.response else 0
                is_post = event.request_id == captured.get("post_request_id")
                log(f"generate/v2 response: HTTP {code} is_post={is_post}")

        async def on_loading_finished(event):
            post_id = captured.get("post_request_id")
            if not post_id or event.request_id != post_id:
                return
            log("POST response body ready")
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

        await tab.send(cdp.network.enable())
        tab.add_handler(cdp.network.RequestWillBeSent, on_request_will_be_sent)
        tab.add_handler(cdp.network.ResponseReceived, on_response)
        tab.add_handler(cdp.network.LoadingFinished, on_loading_finished)
        log("Interception ready")

        # ── Snapshot existing clip IDs for DOM fallback ────────────────────────
        # If CDP interception fails, we compare before/after clip links to find
        # newly generated clips.
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
                let btn = document.querySelector('button[aria-label="Create song"]');
                if (!btn) {
                    const btns = [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null);
                    for (const b of btns) {
                        const txt = b.textContent.trim();
                        if (txt === 'Create' || txt.includes('Create')) {
                            if (b.closest('[class*="playbar"]') || b.closest('nav')) continue;
                            if (txt.includes('Workspace') || txt.includes('New')) continue;
                            btn = b;
                            break;
                        }
                    }
                }
                if (!btn) return 'NOT_FOUND';
                if (btn.disabled) {
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

        # ── Wait for generation (+ captcha if needed) ─────────────────────────
        # Poll every 10s for the CDP intercept. Every 30s check if a captcha
        # iframe appeared so we can log it for the user.
        log("Waiting for generation… (solve captcha in browser if it appears)")
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

        # DOM fallback: if CDP didn't capture, scrape new clip IDs from page
        if not clips:
            log("Trying DOM fallback: extracting NEW clip IDs from page…")
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
    """Poll clip statuses via SunoClient API, then download completed MP3s."""
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

    # Download completed clips, skip short ones (< 90s)
    out = Path(OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\s-]", "", song_title.lower())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")[:50] or "suno"

    for idx, clip in enumerate(final, 1):
        status = clip.get("status", "")
        audio_url = clip.get("audio_url", "")
        duration = clip.get("metadata", {}).get("duration", 0)
        if status == "error":
            err = clip.get("metadata", {}).get("error_message", "?")
            print(f"  ✗ Clip {idx} failed: {err}")
            continue
        if not audio_url:
            print(f"  ✗ Clip {idx} has no audio URL")
            continue
        if duration and duration < 90:
            print(f"  ✗ Clip {idx} skipped — too short ({duration:.1f}s)")
            continue
        dest = out / f"{slug}_{idx}.mp3"
        print(f"  Downloading clip {idx} ({duration:.1f}s) → {dest.name}")
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
    for song in SONGS:
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
