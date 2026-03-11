"""Suno Google SSO login — mirrors the LinkedIn automation pattern exactly.

Flow (same as LinkedIn orchestrator):
  1. Launch stealth browser
  2. Log into Google accounts.google.com first (establishes Google session)
     — email → password → 2FA (required) → skip passkey
  3. Navigate to suno.com/sign-in and click "Continue with Google"
     — existing Google session auto-completes the OAuth
  4. Wait for redirect back to suno.com
  5. Navigate to /create to initialize Clerk session
  6. Extract all cookies via CDP and return as serialized string
"""
import asyncio
from typing import Callable, Optional

from .browser import create_stealth_browser, inject_stealth, navigate, close_browser
from .google_auth import gmail_login
from .config import (
    WAIT_AFTER_SUNO_PAGE_LOAD, WAIT_AFTER_GOOGLE_BTN,
    WAIT_FOR_SUNO_REDIRECT, WAIT_SUNO_SESSION_INIT,
    jittered,
)

SUNO_SIGN_IN = "https://suno.com/sign-in"
SUNO_CREATE  = "https://suno.com/create"


async def _click_continue_with_google(page) -> None:
    """Click the Google SSO button on suno.com/sign-in.

    Uses the Google logo's unique SVG color #4285F4 as the selector —
    unambiguous regardless of how the button text is split in the DOM.
    """
    from .browser import wait_for_element

    for attempt in range(2):
        try:
            btn = await wait_for_element(page, 'button:has(path[fill="#4285F4"])', 15, 3, "Google SSO button")
            if not btn:
                raise RuntimeError("Google SSO button not found on Suno sign-in page")

            await btn.scroll_into_view()
            await asyncio.sleep(0.5)
            await btn.click()
            print("  ✔ Clicked Google SSO button")
            break

        except Exception as e:
            msg = str(e)
            if ("does not belong to the document" in msg or "No node with given id" in msg) and attempt == 0:
                print("  Button stale, retrying…")
                await asyncio.sleep(2)
                continue
            raise

    await asyncio.sleep(jittered(WAIT_AFTER_GOOGLE_BTN))


async def _wait_for_suno_home(browser, timeout: float = WAIT_FOR_SUNO_REDIRECT) -> object:
    """Poll all browser tabs until one lands on suno.com (not sign-in). Returns that tab."""
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        await asyncio.sleep(1.5)
        for tab in browser.tabs:
            url = getattr(tab, "url", "") or ""
            if "suno.com" in url and "sign-in" not in url:
                return tab
    return None


async def login_with_google(
    email: str,
    password: str,
    recovery_email: str = None,
    totp_secret: str = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Log into Suno via Google SSO using a stealth browser.

    Requires a TOTP secret if Google Authenticator 2FA is enabled on the account.
    Browser is VISIBLE so the user can handle any unexpected CAPTCHA prompts.

    Returns a serialized cookie string ready for SunoClient.
    Raises RuntimeError on failure.
    """
    try:
        import nodriver  # noqa: F401
    except ImportError:
        raise RuntimeError("nodriver is not installed. Run: pip install nodriver")

    def status(msg: str) -> None:
        print(f"  {msg}")
        if on_status:
            on_status(msg)

    browser = None
    try:
        status("Launching stealth browser…")
        browser = await create_stealth_browser()

        # ── Step 1: Log into Google first (LinkedIn pattern) ──────────────────
        status("Logging into Google account…")
        await gmail_login(
            browser,
            email,
            password,
            recovery_email=recovery_email,
            totp_secret=totp_secret,
        )
        status("Google login complete — navigating to Suno…")

        # ── Step 2: Open Suno sign-in page ────────────────────────────────────
        suno_page = await browser.get(SUNO_SIGN_IN)
        await asyncio.sleep(jittered(WAIT_AFTER_SUNO_PAGE_LOAD))
        await inject_stealth(suno_page)

        # ── Step 3: Click "Continue with Google" ──────────────────────────────
        status("Clicking 'Continue with Google' on Suno…")
        await _click_continue_with_google(suno_page)

        # ── Step 4: Wait for OAuth chain to fully complete ────────────────────
        # The redirect chain is: Suno → Google OAuth → Clerk callback → Suno
        # We must wait for ALL redirects to settle, not just the first suno.com hit.
        status("Waiting for Suno to authenticate… (solve any CAPTCHA if prompted)")
        suno_tab = await _wait_for_suno_home(browser)
        if not suno_tab:
            raise RuntimeError(
                "Timed out waiting for Suno redirect after Google OAuth. "
                "Check credentials or solve any CAPTCHA in the browser."
            )

        # ── Step 5: Let the Clerk session fully initialize ────────────────────
        # The page landed on suno.com but Clerk's OAuth callback may still be
        # processing server-side. Wait, then navigate to /create to force a
        # full Clerk session initialization.
        status("Waiting for Clerk session to initialize…")
        await asyncio.sleep(10)
        await inject_stealth(suno_tab)
        await navigate(suno_tab, SUNO_CREATE)
        await asyncio.sleep(jittered(WAIT_SUNO_SESSION_INIT))

        # ── Step 6: Extract cookies via CDP ───────────────────────────────────
        status("Extracting session cookies…")
        from nodriver import cdp
        raw_cookies = await suno_tab.send(cdp.network.get_all_cookies())
        cookie_str = "; ".join(
            f"{c.name}={c.value}"
            for c in raw_cookies
            if c.name and c.value
        )

        if "__client" not in cookie_str:
            raise RuntimeError(
                "No Clerk session cookie found after login — please try again."
            )

        status(f"Login successful — {len(raw_cookies)} cookies captured.")
        return cookie_str

    finally:
        await close_browser(browser)
