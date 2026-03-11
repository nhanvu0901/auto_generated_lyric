"""Suno authentication via nodriver stealth browser.

Two login paths are supported:
  A) Email + password  — for accounts created directly on Suno
  B) Google SSO        — delegates to suno_automation.suno_login

The browser is VISIBLE so the user can solve any hCaptcha / 2FA challenges.
"""

import asyncio
from typing import Callable, Optional

# ── Google SSO path (preferred for Google-linked accounts) ────────────────────

async def login_with_google(
    email: str,
    password: str,
    recovery_email: str = None,
    totp_secret: str = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    """Log into Suno via Google SSO. Returns serialized cookie string."""
    import sys, os
    # Allow importing suno_automation from sibling folder
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path:
        sys.path.insert(0, parent)

    from suno_automation.suno_login import login_with_google as _login
    return await _login(email, password, recovery_email, totp_secret, on_status)


SUNO_SIGN_IN = "https://suno.com/sign-in"
SUNO_CREATE  = "https://suno.com/create"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _inject_stealth(page) -> None:
    """Remove webdriver fingerprint."""
    try:
        await page.evaluate("""
            try {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false, configurable: true
                });
            } catch(e) {}
        """)
    except Exception:
        pass


async def _wait_for(page, selector: str, timeout: float = 15.0):
    """Poll for a CSS selector up to `timeout` seconds. Returns element or None."""
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        try:
            el = await page.select(selector, timeout=2)
            if el:
                return el
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None


async def _wait_url_leaves(page, fragment: str, timeout: float = 90.0) -> bool:
    """Wait until page URL no longer contains `fragment`. Returns True if it left."""
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        await asyncio.sleep(1.5)
        url = getattr(page, "url", "") or ""
        if fragment not in url:
            return True
    return False


# ── Public API ─────────────────────────────────────────────────────────────────

async def login_and_get_cookies(
    email: str,
    password: str,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Log into Suno with email + password using a stealth browser.

    The browser window is VISIBLE so the user can handle CAPTCHA / 2-FA if needed.
    Returns a serialized cookie string for use with SunoClient.

    Raises RuntimeError on login failure.
    """
    try:
        import nodriver as uc
        from nodriver import cdp
    except ImportError:
        raise RuntimeError(
            "nodriver is not installed. Run: pip install nodriver"
        )

    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    status("Launching stealth browser…")
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
        await asyncio.sleep(3)
        await _inject_stealth(page)

        # ── Step 1: email ──────────────────────────────────────────────────────
        status("Looking for email field…")
        # Clerk sign-in widget uses name="identifier" or type="email"
        email_input = await _wait_for(page, 'input[name="identifier"]', 15)
        if not email_input:
            email_input = await _wait_for(page, 'input[type="email"]', 8)
        if not email_input:
            raise RuntimeError(
                "Email field not found on Suno sign-in page. "
                "Your account may use Google/Discord SSO — "
                "paste your browser cookie in Settings instead."
            )

        status("Entering email…")
        await email_input.send_keys(email)
        await asyncio.sleep(0.8)

        # Click Continue
        continue_btn = await _wait_for(page, 'button[type="submit"]', 6)
        if continue_btn:
            await continue_btn.click()
            await asyncio.sleep(2.5)

        # ── Step 2: password ───────────────────────────────────────────────────
        status("Looking for password field…")
        pwd_input = await _wait_for(page, 'input[type="password"]', 15)
        if not pwd_input:
            raise RuntimeError(
                "Password field not found. "
                "Your Suno account may use Google/Discord SSO only — "
                "paste your browser cookie in Settings instead."
            )

        status("Entering password…")
        await pwd_input.click()
        await asyncio.sleep(0.4)
        await pwd_input.send_keys(password)
        await asyncio.sleep(0.8)

        submit = await _wait_for(page, 'button[type="submit"]', 6)
        if submit:
            await submit.click()

        # ── Step 3: wait for redirect away from sign-in ────────────────────────
        status("Authenticating… (solve any CAPTCHA in the browser window)")
        left = await _wait_url_leaves(page, "sign-in", timeout=90)
        if not left:
            raise RuntimeError(
                "Login timed out — still on sign-in page after 90 s. "
                "Check your credentials or solve the CAPTCHA in the browser window."
            )

        # ── Step 4: navigate to /create to fully initialize Clerk session ──────
        status("Initializing Suno session…")
        await page.get(SUNO_CREATE)
        await asyncio.sleep(5)
        await _inject_stealth(page)

        # ── Step 5: extract cookies via CDP ────────────────────────────────────
        status("Extracting session cookies…")
        raw_cookies = await page.send(cdp.network.get_all_cookies())
        cookie_str = "; ".join(
            f"{c.name}={c.value}"
            for c in raw_cookies
            if c.name and c.value
        )

        if "__client" not in cookie_str:
            raise RuntimeError(
                "Login appeared to succeed but no Clerk session cookie found. "
                "Please try again."
            )

        status(f"Login successful — {len(raw_cookies)} cookies captured.")
        return cookie_str

    finally:
        try:
            await browser.stop()
        except Exception:
            pass
