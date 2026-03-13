"""Suno authentication via nodriver stealth browser.

Opens a visible browser to suno.com and lets the user log in manually
(any method: Google, Discord, email, etc.). Polls browser-level cookies
and tabs to detect successful login, then extracts cookies and closes.

Also provides solve_captcha_via_browser() for the hybrid captcha flow:
opens browser to /create, fills lyrics, clicks Create, user solves
hCaptcha manually, then we intercept the generate/v2 request via CDP
to extract the captcha token + JWT.

Key design: we never call page.send() during the wait loop — the page
object can go stale during cross-origin OAuth redirects (e.g. Google).
Instead we use browser.cookies.get_all() and browser.tabs which survive
any navigation.
"""

import asyncio
import json
from typing import Callable, Optional
from urllib.parse import urlparse

SUNO_SIGN_IN = "https://suno.com/sign-in"
SUNO_CREATE  = "https://suno.com/create"

# Only keep cookies from these domains — everything else (Google, Discord,
# tracking pixels, etc.) is noise and makes the Cookie header too large
# (431 Request Header Fields Too Large from Clerk).
SUNO_COOKIE_DOMAINS = {"suno.com", ".suno.com", "clerk.suno.com"}


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
    """Extract the hostname from a tab's URL (e.g. 'suno.com')."""
    try:
        url = tab.target.url or ""
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _get_tab_path(tab) -> str:
    """Extract the path from a tab's URL (e.g. '/sign-in')."""
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

        # ── Poll browser-level cookies + tabs ────────────────────────────────
        # We do NOT use `page.send()` here because the page object can go
        # stale when the browser navigates cross-origin (Google OAuth, etc.).
        # browser.cookies.get_all() finds any alive tab internally.
        deadline = asyncio.get_event_loop().time() + timeout
        logged_in = False
        last_status = ""

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)

            # Context-aware status
            new_status = _describe_location(browser)
            if new_status != last_status:
                status(new_status)
                last_status = new_status

            # Check 1: is any tab back on suno.com (not sign-in)?
            suno_tab = _find_suno_tab(browser)
            if not suno_tab:
                continue
            path = _get_tab_path(suno_tab)
            if "/sign-in" in path or "/sign-up" in path:
                continue

            # Check 2: does __client cookie exist? (browser-level)
            try:
                all_cookies = await browser.cookies.get_all()
                has_client = any(
                    c.name == "__client" and c.value
                    for c in all_cookies
                )
                if has_client:
                    logged_in = True
                    break
            except Exception:
                # browser.cookies.get_all() needs at least one alive tab;
                # if all tabs are mid-navigation, just retry next loop
                pass

        if not logged_in:
            raise RuntimeError(
                "Login timed out — no session detected after "
                f"{int(timeout)} seconds. Please try again."
            )

        # ── Navigate to /create to fully initialize Clerk session ────────────
        status("Login detected! Initializing session…")
        suno_tab = _find_suno_tab(browser)
        if suno_tab:
            await suno_tab.get(SUNO_CREATE)
        else:
            await browser.get(SUNO_CREATE)
        await asyncio.sleep(4)

        # Inject stealth on the suno tab
        suno_tab = _find_suno_tab(browser)
        if suno_tab:
            await _inject_stealth(suno_tab)

        # ── Extract final cookies (Suno domains only) ────────────────────────
        status("Extracting session cookies…")
        all_cookies = await browser.cookies.get_all()

        # Filter to Suno-related domains only. Google OAuth, Discord, etc.
        # cookies bloat the header and cause 431 from Clerk.
        suno_cookies = [
            c for c in all_cookies
            if c.name and c.value and _is_suno_domain(getattr(c, "domain", ""))
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


# ── Captcha solving via browser ───────────────────────────────────────────────

async def solve_captcha_via_browser(
    cookie_str: str,
    lyrics: str,
    tags: str,
    title: str,
    on_status: Optional[Callable[[str], None]] = None,
    timeout: float = 300.0,
) -> dict:
    """
    Open a stealth browser to suno.com/create with saved cookies,
    fill in the song details, click Create, and let the user solve
    the hCaptcha manually. Intercept the generate/v2 request via CDP
    to extract the captcha token and JWT.

    Returns dict with keys: token, authorization, clips.
    - token: hCaptcha token from the intercepted request body
    - authorization: Bearer JWT from the intercepted request headers
    - clips: list of clip dicts from the Suno response (the generation
             already happened in the browser, so we just return the result)
    """
    try:
        import nodriver as uc
    except ImportError:
        raise RuntimeError("nodriver is not installed. Run: pip install nodriver")

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    status("Launching browser for captcha…")
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
        # Navigate to about:blank first, set cookies, then go to /create
        status("Setting session cookies…")
        tab = await browser.get("about:blank")
        await asyncio.sleep(1)

        # Parse and set cookies via CDP — set on multiple domains
        cookie_count = 0
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if not name or not value:
                continue
            # Set on both .suno.com and suno.com to cover all cases
            for domain in [".suno.com"]:
                try:
                    result = await tab.send(uc.cdp.network.set_cookie(
                        name=name,
                        value=value,
                        domain=domain,
                        path="/",
                        secure=True,
                    ))
                    cookie_count += 1
                except Exception as exc:
                    status(f"Cookie set failed: {name} -> {exc}")

        status(f"Set {cookie_count} cookies")

        # Navigate to /create
        status("Opening Suno create page…")
        tab = await browser.get(SUNO_CREATE)
        await asyncio.sleep(5)
        await _inject_stealth(tab)

        # Check current URL — did we get redirected to sign-in?
        current_url = await tab.evaluate("window.location.href")
        status(f"Current URL: {current_url}")
        if current_url and "/sign-in" in str(current_url):
            raise RuntimeError(
                "Redirected to sign-in page — cookies may have expired. "
                "Please reconnect your account in Settings."
            )

        # Check if user appears logged in
        login_info = await tab.evaluate("""
            JSON.stringify({
                hasAvatar: !!document.querySelector('[class*="avatar"], [class*="Avatar"]'),
                bodySnippet: document.body ? document.body.innerText.substring(0, 200) : ''
            })
        """)
        status(f"Login check: {login_info}")

        # Dump all visible form elements to understand the page structure
        page_dump = await tab.evaluate("""
            JSON.stringify({
                textareas: [...document.querySelectorAll('textarea')].map(t => ({
                    cls: t.className,
                    ph: t.placeholder || '',
                    vis: t.offsetParent !== null
                })),
                inputs: [...document.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
                    type: i.type,
                    ph: i.placeholder || ''
                })),
                buttons: [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => ({
                    text: b.textContent.trim().substring(0, 40),
                    aria: b.getAttribute('aria-label') || '',
                    disabled: b.disabled
                }))
            })
        """)
        try:
            page_info = json.loads(page_dump)
        except Exception:
            page_info = {"textareas": [], "inputs": [], "buttons": []}
            status(f"Raw page dump: {str(page_dump)[:300]}")

        status(f"Page: {len(page_info.get('textareas', []))} textareas, "
               f"{len(page_info.get('inputs', []))} inputs, "
               f"{len(page_info.get('buttons', []))} buttons")

        for ta in page_info.get("textareas", []):
            status(f"  textarea: cls='{ta.get('cls','')}' ph='{ta.get('ph','')}' vis={ta.get('vis')}")
        for inp in page_info.get("inputs", []):
            status(f"  input: type='{inp.get('type','')}' ph='{inp.get('ph','')}'")
        for btn in page_info.get("buttons", [])[:15]:
            status(f"  btn: text='{btn.get('text','')}' aria='{btn.get('aria','')}' disabled={btn.get('disabled')}")

        # Switch to custom mode if needed
        status("Switching to Custom mode…")
        custom_clicked = await tab.evaluate("""
            (() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const txt = b.textContent.trim().toLowerCase();
                    if (txt === 'custom') {
                        b.click();
                        return 'clicked';
                    }
                }
                return 'not_found';
            })()
        """)
        status(f"Custom mode toggle: {custom_clicked}")
        await asyncio.sleep(2)

        # Re-check page elements after switching to Custom
        if custom_clicked == "clicked":
            dump2 = await tab.evaluate("""
                JSON.stringify({
                    textareas: [...document.querySelectorAll('textarea')].map(t => ({
                        cls: t.className, ph: t.placeholder || '', vis: t.offsetParent !== null
                    })),
                    inputs: [...document.querySelectorAll('input')].filter(i =>
                        i.offsetParent !== null
                    ).map(i => ({ type: i.type, ph: i.placeholder || '' })),
                    buttons: [...document.querySelectorAll('button')].filter(b =>
                        b.offsetParent !== null
                    ).map(b => ({
                        text: b.textContent.trim().substring(0, 40),
                        aria: b.getAttribute('aria-label') || '',
                        disabled: b.disabled
                    }))
                })
            """)
            try:
                pi2 = json.loads(dump2)
            except Exception:
                pi2 = {"textareas": [], "inputs": [], "buttons": []}
                status(f"Raw dump2: {str(dump2)[:300]}")
            status(f"After Custom: {len(pi2.get('textareas',[]))} textareas, "
                   f"{len(pi2.get('inputs',[]))} inputs, "
                   f"{len(pi2.get('buttons',[]))} buttons")
            for ta in pi2.get("textareas", []):
                status(f"  textarea: cls='{ta.get('cls','')}' ph='{ta.get('ph','')}'")
            for inp in pi2.get("inputs", []):
                status(f"  input: type='{inp.get('type','')}' ph='{inp.get('ph','')}'")
            for btn in pi2.get("buttons", [])[:15]:
                status(f"  btn: text='{btn.get('text','')}' aria='{btn.get('aria','')}' disabled={btn.get('disabled')}")

        # Fill in lyrics — try multiple selectors
        status("Filling in lyrics…")
        escaped_lyrics = json.dumps(lyrics)
        lyrics_filled = await tab.evaluate(f"""
            (() => {{
                // Try .custom-textarea first, then any visible textarea
                let ta = document.querySelector('.custom-textarea');
                if (!ta) {{
                    const all = document.querySelectorAll('textarea');
                    for (const t of all) {{
                        if (t.offsetParent !== null) {{ ta = t; break; }}
                    }}
                }}
                if (!ta) return 'no_textarea';

                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(ta, {escaped_lyrics});
                ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
                ta.dispatchEvent(new Event('change', {{ bubbles: true }}));

                // Also try React fiber dispatch
                const tracker = ta._valueTracker;
                if (tracker) {{ tracker.setValue(''); }}
                ta.dispatchEvent(new Event('input', {{ bubbles: true }}));

                return 'filled:' + ta.value.substring(0, 50);
            }})()
        """)
        status(f"Lyrics: {lyrics_filled}")
        await asyncio.sleep(0.5)

        # Fill in title — try placeholder matching + positional fallback
        escaped_title = json.dumps(title)
        title_filled = await tab.evaluate(f"""
            (() => {{
                const inputs = document.querySelectorAll('input');
                const visible = [...inputs].filter(i => i.offsetParent !== null);

                // First try placeholder matching
                for (const inp of visible) {{
                    const ph = (inp.placeholder || '').toLowerCase();
                    if (ph.includes('title') || ph.includes('name') || ph.includes('song')) {{
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        nativeSetter.call(inp, {escaped_title});
                        const tracker = inp._valueTracker;
                        if (tracker) {{ tracker.setValue(''); }}
                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'filled_by_placeholder:' + inp.placeholder;
                    }}
                }}
                return 'no_title_input';
            }})()
        """)
        status(f"Title: {title_filled}")
        await asyncio.sleep(0.5)

        # Fill in tags/style
        escaped_tags = json.dumps(tags)
        tags_filled = await tab.evaluate(f"""
            (() => {{
                const inputs = document.querySelectorAll('input');
                const visible = [...inputs].filter(i => i.offsetParent !== null);

                for (const inp of visible) {{
                    const ph = (inp.placeholder || '').toLowerCase();
                    if (ph.includes('style') || ph.includes('genre') || ph.includes('tag') || ph.includes('describe')) {{
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        nativeSetter.call(inp, {escaped_tags});
                        const tracker = inp._valueTracker;
                        if (tracker) {{ tracker.setValue(''); }}
                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'filled_by_placeholder:' + inp.placeholder;
                    }}
                }}
                return 'no_style_input';
            }})()
        """)
        status(f"Tags: {tags_filled}")
        await asyncio.sleep(0.5)

        # Set up network interception BEFORE clicking Create
        status("Setting up request interception…")
        captured = {"token": None, "authorization": None, "response_body": None}
        intercept_done = asyncio.Event()

        async def _handle_request_paused(event):
            """Handle intercepted requests via CDP Fetch domain."""
            request = event.request
            url = request.url if request else ""
            request_id = event.request_id

            if "api/generate/v2" in url and request.method == "POST":
                status(f"Intercepted generate/v2 request!")
                # Capture the authorization header (Headers is a dict subclass)
                hdrs = request.headers or {}
                for k, v in hdrs.items():
                    if k.lower() == "authorization":
                        captured["authorization"] = v
                        break

                # Capture the request body to extract captcha token
                body = getattr(request, "post_data", None)
                if body:
                    try:
                        data = json.loads(body)
                        captured["token"] = data.get("token", "")
                        status(f"Captured token: {len(captured['token'] or '')} chars")
                    except Exception as exc:
                        status(f"Failed to parse request body: {exc}")
                else:
                    status("No post_data on intercepted request")

                # Let the request continue
                try:
                    await tab.send(uc.cdp.fetch.continue_request(request_id=request_id))
                except Exception:
                    pass
                return

            # Let all other requests through
            try:
                await tab.send(uc.cdp.fetch.continue_request(request_id=request_id))
            except Exception:
                pass

        async def _handle_response(event):
            """Monitor network responses for generate/v2 — store request ID."""
            url = event.response.url if event.response else ""
            if "api/generate/v2" in url:
                status_code = event.response.status if event.response else 0
                status(f"generate/v2 response: {status_code}")
                captured["generate_request_id"] = event.request_id

        async def _handle_loading_finished(event):
            """Fires when response body is fully received — safe to read body."""
            gen_req_id = captured.get("generate_request_id")
            if gen_req_id and event.request_id == gen_req_id:
                for _ in range(3):
                    try:
                        body_result = await tab.send(
                            uc.cdp.network.get_response_body(event.request_id)
                        )
                        if body_result and body_result[0]:
                            captured["response_body"] = body_result[0]
                            break
                    except Exception:
                        await asyncio.sleep(0.5)
                intercept_done.set()

        # Enable Fetch domain to intercept requests
        await tab.send(uc.cdp.fetch.enable(
            patterns=[
                uc.cdp.fetch.RequestPattern(
                    url_pattern="*api/generate/v2*",
                    request_stage=uc.cdp.fetch.RequestStage.REQUEST,
                )
            ]
        ))

        # Enable Network domain for response monitoring
        await tab.send(uc.cdp.network.enable())

        # Register event handlers
        tab.add_handler(uc.cdp.fetch.RequestPaused, _handle_request_paused)
        tab.add_handler(uc.cdp.network.ResponseReceived, _handle_response)
        tab.add_handler(uc.cdp.network.LoadingFinished, _handle_loading_finished)

        # Click the Create button — try multiple strategies
        status("Looking for Create button…")
        click_result = await tab.evaluate("""
            (() => {
                // Strategy 1: aria-label
                let btn = document.querySelector('button[aria-label="Create"]');
                if (btn && !btn.disabled) { btn.click(); return 'clicked_aria'; }
                if (btn && btn.disabled) return 'disabled_aria';

                // Strategy 2: exact text match
                const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
                for (const b of btns) {
                    const txt = b.textContent.trim();
                    if (txt === 'Create') {
                        if (b.disabled) return 'disabled_text:' + txt;
                        b.click();
                        return 'clicked_text:' + txt;
                    }
                }

                // Strategy 3: button containing "Create" but NOT nav links
                for (const b of btns) {
                    const txt = b.textContent.trim();
                    // Skip nav items (they tend to have single words or icons)
                    if (txt.length > 30) continue;
                    if (txt.includes('Create') && !b.closest('nav') && !b.closest('[class*="sidebar"]') && !b.closest('[class*="nav"]')) {
                        if (b.disabled) return 'disabled_partial:' + txt;
                        b.click();
                        return 'clicked_partial:' + txt;
                    }
                }

                // Strategy 4: submit button
                btn = document.querySelector('button[type="submit"]');
                if (btn && !btn.disabled) { btn.click(); return 'clicked_submit'; }
                if (btn && btn.disabled) return 'disabled_submit';

                return 'not_found';
            })()
        """)
        status(f"Create click: {click_result}")

        if "not_found" in str(click_result) or "disabled" in str(click_result):
            status("Create button not clickable — will wait for you to click it manually")

        # Wait for the user to solve captcha and the request to be intercepted
        status("Waiting for captcha to be solved…")
        deadline = asyncio.get_event_loop().time() + timeout

        # Also periodically check for captcha iframe and hCaptcha state
        check_count = 0
        while asyncio.get_event_loop().time() < deadline:
            try:
                await asyncio.wait_for(intercept_done.wait(), timeout=10.0)
                break
            except asyncio.TimeoutError:
                check_count += 1
                # Check if browser is still open
                try:
                    _ = browser.tabs
                except Exception:
                    raise RuntimeError("Browser was closed before captcha was solved.")

                # Periodically check captcha state
                if check_count % 3 == 0:
                    try:
                        captcha_state = await tab.evaluate("""
                            JSON.stringify({
                                hasCaptcha: !!document.querySelector('iframe[title*="hCaptcha"], iframe[src*="hcaptcha"], iframe[title*="captcha"]'),
                                hasModal: !!document.querySelector('[class*="modal"], [role="dialog"]'),
                                url: window.location.href
                            })
                        """)
                        status(f"State: {captcha_state}")
                    except Exception:
                        pass
                continue

        if not intercept_done.is_set():
            raise RuntimeError(
                f"Timed out waiting for captcha after {int(timeout)}s. Please try again."
            )

        # Parse response
        clips = []
        if captured["response_body"]:
            try:
                resp_data = json.loads(captured["response_body"])
                clips = resp_data.get("clips", [])
            except Exception:
                pass

        status(f"Captcha solved! Got {len(clips)} clip(s) from browser generation.")
        await asyncio.sleep(2)

        result = {
            "token": captured.get("token", ""),
            "authorization": captured.get("authorization", ""),
            "clips": clips,
        }

        return result

    finally:
        try:
            await browser.stop()
        except Exception:
            pass
