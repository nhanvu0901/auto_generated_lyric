"""Suno browser automation — login + music generation.

login_and_get_cookies():
  Opens browser to suno.com, user logs in manually (any method),
  extracts cookies via independent WebSocket (bypasses nodriver's
  broken Cookie.from_json parser).

generate_via_browser():
  Opens browser with saved cookies, switches to Advanced mode,
  fills lyrics/title/style tags using React fiber internals,
  clicks Create, intercepts generate/v2 response via CDP Network
  to get clip IDs. Falls back to DOM scraping if CDP capture fails.
"""

import asyncio
import json
from typing import Callable, Optional
from urllib.parse import urlparse

SUNO_SIGN_IN = "https://suno.com/sign-in"
SUNO_CREATE  = "https://suno.com/create"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _inject_stealth(tab) -> None:
    """Remove webdriver fingerprint on a tab."""
    try:
        await tab.evaluate("""
            try {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false, configurable: true
                });
            } catch(e) {}
        """)
    except Exception:
        pass


def _is_suno_domain(domain: str) -> bool:
    """Check if a cookie domain belongs to Suno (suno.com or subdomains)."""
    d = domain.lstrip(".")
    return d == "suno.com" or d.endswith(".suno.com")


def _get_tab_host(tab) -> str:
    """Extract the hostname from a tab's URL."""
    try:
        url = tab.target.url or ""
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _get_tab_path(tab) -> str:
    """Extract the path from a tab's URL."""
    try:
        url = tab.target.url or ""
        return urlparse(url).path or ""
    except Exception:
        return ""


def _find_suno_tab(browser):
    """Return the first tab whose hostname is suno.com, or None."""
    for t in browser.tabs:
        host = _get_tab_host(t)
        if host in ("suno.com", "www.suno.com"):
            return t
    return None


def _describe_location(browser) -> str:
    """Return a human-readable description of where the browser is."""
    for t in browser.tabs:
        host = _get_tab_host(t)
        if host and "google.com" in host:
            return "Waiting for Google sign-in…"
        if host and "discord.com" in host:
            return "Waiting for Discord sign-in…"
        if host in ("suno.com", "www.suno.com"):
            path = _get_tab_path(t)
            if "/sign-in" in path or "/sign-up" in path:
                return "Please log in to Suno in the browser window…"
            return "Checking for session…"
    return "Waiting for login to complete…"


async def _extract_cookies_raw(browser, status_fn) -> list:
    """Extract all browser cookies via an independent WebSocket.

    nodriver's Cookie.from_json() crashes on Chrome's removed 'sameParty'
    field (KeyError), and its _listener loop owns the WebSocket recv(),
    blocking direct use. We open a SECOND WebSocket to Chrome's browser
    debug endpoint, send Storage.getCookies, parse the raw JSON ourselves.
    """
    import websockets

    try:
        ws_url = browser.connection.websocket_url
        async with websockets.connect(ws_url, max_size=2**24) as ws:
            await ws.send(json.dumps({
                "id": 1, "method": "Storage.getCookies", "params": {},
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            msg = json.loads(raw)
            cookies_data = msg.get("result", {}).get("cookies", [])

            class _Cookie:
                def __init__(self, d):
                    self.name = d.get("name", "")
                    self.value = d.get("value", "")
                    self.domain = d.get("domain", "")

            cookies = [_Cookie(c) for c in cookies_data]
            status_fn(f"Got {len(cookies)} cookies")
            return cookies
    except Exception as exc:
        status_fn(f"Cookie extraction failed: {type(exc).__name__}: {exc}")
        return []


# ── Public API ─────────────────────────────────────────────────────────────────

async def login_and_get_cookies(
    on_status: Optional[Callable[[str], None]] = None,
    timeout: float = 300.0,
) -> str:
    """
    Open a stealth browser to Suno sign-in and wait for the user to log in
    manually (any method). Once logged in, extract cookies and close browser.

    Returns a serialized cookie string for use with SunoClient.
    Raises RuntimeError on timeout or missing session cookie.
    """
    try:
        import nodriver as uc
    except ImportError:
        raise RuntimeError(
            "nodriver is not installed. Run: pip install nodriver"
        )

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    status("Launching browser…")
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--window-size=1280,820",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
        no_sandbox=True,
    )

    try:
        status("Opening Suno sign-in page…")
        page = await browser.get(SUNO_SIGN_IN)
        await asyncio.sleep(2)
        await _inject_stealth(page)

        status("Please log in to Suno in the browser window (any method)…")

        # ── Detect login by polling tab URLs ──────────────────────────────
        # We do NOT use CDP cookie queries here — after OAuth redirects,
        # all tab CDP connections are dead.
        deadline = asyncio.get_event_loop().time() + timeout
        logged_in = False
        last_status = ""
        suno_home_checks = 0

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)

            new_status = _describe_location(browser)
            if new_status != last_status:
                status(new_status)
                last_status = new_status

            suno_tab = _find_suno_tab(browser)
            if not suno_tab:
                suno_home_checks = 0
                continue
            path = _get_tab_path(suno_tab)
            if "/sign-in" in path or "/sign-up" in path:
                suno_home_checks = 0
                continue

            # User on suno.com (not sign-in) for 2 consecutive checks = logged in
            suno_home_checks += 1
            if suno_home_checks >= 2:
                logged_in = True
                break

        if not logged_in:
            raise RuntimeError(
                "Login timed out — no session detected after "
                f"{int(timeout)} seconds. Please try again."
            )

        # ── Extract cookies via independent WebSocket ─────────────────────
        status("Login detected! Extracting session cookies…")
        all_cookies = await _extract_cookies_raw(browser, status)

        # Filter to Suno-related domains only
        suno_cookies = [
            c for c in all_cookies
            if c.name and c.value and _is_suno_domain(c.domain)
        ]

        cookie_str = "; ".join(
            f"{c.name}={c.value}" for c in suno_cookies
        )

        if "__client" not in cookie_str:
            raise RuntimeError(
                "Login appeared to succeed but no Clerk session cookie found. "
                "Please try again."
            )

        status(f"Login successful — {len(suno_cookies)} cookies captured.")
        return cookie_str

    finally:
        try:
            await browser.stop()
        except Exception:
            pass


# ── Browser-based music generation ────────────────────────────────────────────

async def generate_via_browser(
    cookie_str: str,
    lyrics: str,
    tags: str,
    title: str,
    on_status: Optional[Callable[[str], None]] = None,
    timeout: float = 300.0,
) -> list[dict]:
    """
    Open browser → inject cookies → fill form → click Create →
    intercept generate/v2 via CDP Network → return clip dicts.

    This is the primary generation method for free accounts (captcha
    is handled automatically by the browser).
    """
    try:
        import nodriver as uc
        from nodriver import cdp
    except ImportError:
        raise RuntimeError("nodriver is not installed. Run: pip install nodriver")

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    status("Launching browser…")
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
        # ── Inject cookies ────────────────────────────────────────────────
        status("Injecting cookies…")
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
        status(f"Injected {cookie_count} cookies")

        # ── Navigate to /create ───────────────────────────────────────────
        status("Opening suno.com/create…")
        tab = await browser.get(SUNO_CREATE)
        await asyncio.sleep(15)

        await _inject_stealth(tab)

        current_url = await tab.evaluate("window.location.href")
        if "/sign-in" in str(current_url):
            raise RuntimeError("Redirected to sign-in — cookies expired!")

        # ── Wait for create form to render ────────────────────────────────
        status("Waiting for create form…")
        for _ in range(20):
            ready = await tab.evaluate("""
                !!document.querySelector('textarea[data-testid="lyrics-textarea"]')
                || document.querySelectorAll('textarea').length > 0
            """)
            if ready:
                break
            await asyncio.sleep(1.5)

        # ── Switch to Advanced mode ───────────────────────────────────────
        # Suno filters isTrusted — call React's onMouseDown via __reactProps$
        status("Switching to Advanced mode…")
        mode_result = await tab.evaluate("""
            (() => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim() === 'Advanced');
                if (!btn) return 'not_found';

                const propsKey = Object.keys(btn).find(k => k.startsWith('__reactProps$'));
                if (!propsKey) return 'no_reactProps';

                const props = btn[propsKey];
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
        status(f"Advanced mode: {mode_result}")
        await asyncio.sleep(2)

        # ── Fill lyrics ───────────────────────────────────────────────────
        status("Filling lyrics…")
        escaped_lyrics = json.dumps(lyrics)
        await tab.evaluate(f"""
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
                return 'OK';
            }})()
        """)
        await asyncio.sleep(0.5)

        # ── Fill title ────────────────────────────────────────────────────
        escaped_title = json.dumps(title)
        await tab.evaluate(f"""
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
                        return 'OK';
                    }}
                }}
                return 'NO_TITLE_INPUT';
            }})()
        """)
        await asyncio.sleep(0.5)

        # ── Fill style/tags (React fiber onChange walk) ────────────────────
        status("Filling style tags…")
        escaped_tags = json.dumps(tags)
        await tab.evaluate(f"""
            (() => {{
                // Expand Styles section if collapsed
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
                        }}
                        break;
                    }}
                }}

                let ta = document.querySelector('textarea[maxlength="1000"]');
                if (!ta) return 'NO_STYLE_TEXTAREA';

                const targetValue = {escaped_tags};
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
                return ta.value ? 'OK' : 'EMPTY_AFTER_FIBER';
            }})()
        """)

        # Verify + re-fill if React wiped the value
        await asyncio.sleep(0.8)
        await tab.evaluate(f"""
            (() => {{
                const ta = document.querySelector('textarea[maxlength="1000"]');
                if (!ta || ta.value) return;
                const targetValue = {escaped_tags};
                const ns = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                const fk = Object.keys(ta).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (!fk) return;
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
            }})()
        """)
        await asyncio.sleep(0.2)

        # ── Set up CDP Network interception ───────────────────────────────
        status("Setting up interception…")
        captured = {"response_body": None, "post_request_id": None}
        intercept_done = asyncio.Event()

        async def on_request_will_be_sent(event):
            req = event.request
            url = req.url if req else ""
            if "api/generate/v2" in url and req.method == "POST":
                captured["post_request_id"] = event.request_id

        async def on_loading_finished(event):
            post_id = captured.get("post_request_id")
            if not post_id or event.request_id != post_id:
                return
            for _ in range(5):
                try:
                    body_result = await tab.send(
                        cdp.network.get_response_body(event.request_id)
                    )
                    if body_result and body_result[0]:
                        captured["response_body"] = body_result[0]
                        break
                except Exception:
                    await asyncio.sleep(1)
            intercept_done.set()

        await tab.send(cdp.network.enable())
        tab.add_handler(cdp.network.RequestWillBeSent, on_request_will_be_sent)
        tab.add_handler(cdp.network.LoadingFinished, on_loading_finished)

        # ── Snapshot existing clip IDs (for DOM fallback) ─────────────────
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

        # ── Click Create button ───────────────────────────────────────────
        status("Clicking Create…")
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
                    return 'FORCE_CLICKED';
                }
                btn.click();
                return 'clicked';
            })()
        """)
        status(f"Create: {click_result}")

        # ── Wait for generation ───────────────────────────────────────────
        status("Waiting for generation… (solve captcha if prompted)")
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                await asyncio.wait_for(intercept_done.wait(), timeout=10.0)
                break
            except asyncio.TimeoutError:
                try:
                    _ = browser.tabs
                except Exception:
                    raise RuntimeError("Browser was closed!")
                continue

        # ── Parse results ─────────────────────────────────────────────────
        clips = []
        if captured["response_body"]:
            try:
                resp = json.loads(captured["response_body"])
                clips = resp.get("clips", [])
            except Exception:
                pass

        # DOM fallback if CDP didn't capture
        if not clips:
            status("Extracting clip IDs from page…")
            for wait_round in range(10):
                await asyncio.sleep(3)
                dom_json = await tab.evaluate("""
                    JSON.stringify(
                        [...document.querySelectorAll('a[href^="/song/"]')]
                            .map(a => (a.href.match(/\\/song\\/([a-f0-9-]{36})/) || [])[1])
                            .filter(Boolean)
                    )
                """)
                try:
                    all_ids = set(json.loads(dom_json))
                    new_ids = all_ids - existing_clip_ids
                    if new_ids:
                        clips = [{"id": cid, "status": "submitted"} for cid in new_ids]
                        break
                except Exception:
                    pass

        status(f"Got {len(clips)} clip(s)")
        return clips

    finally:
        try:
            await browser.stop()
        except Exception:
            pass
