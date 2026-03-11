"""Google login steps: email → password → optional 2FA / recovery email."""
import asyncio
from .config import (
    WAIT_AFTER_EMAIL_INPUT, WAIT_FOR_PASSWORD_PAGE, WAIT_BEFORE_PASSWORD_INPUT,
    WAIT_AFTER_PASSWORD_CLICK, WAIT_AFTER_PASSWORD_INPUT, WAIT_FOR_LOGIN_COMPLETE,
    WAIT_FOR_2FA_PAGE, WAIT_AFTER_2FA_INPUT,
    WAIT_BEFORE_RECOVERY_OPTION, WAIT_AFTER_RECOVERY_CLICK, WAIT_AFTER_RECOVERY_SUBMIT,
    jittered,
)
from .browser import wait_for_element, click_and_wait, open_page, inject_stealth
from .typing_utils import credential_type

GOOGLE_ACCOUNTS_URL = "https://accounts.google.com/"


async def enter_email(page, email: str) -> None:
    email_input = await wait_for_element(page, 'input[type="email"]', 15, 3, "email input")
    if not email_input:
        raise RuntimeError("Google email input not found")
    print("  ✔ Google login page loaded")

    await credential_type(email_input, email)
    await asyncio.sleep(jittered(WAIT_AFTER_EMAIL_INPUT))

    await page.bring_to_front()
    next_btn = await wait_for_element(page, '#identifierNext', 10, 3, "email next button")
    if not next_btn:
        raise RuntimeError("Email next button not found")
    await click_and_wait(next_btn, page)
    print("  Waiting for password page…")
    await asyncio.sleep(jittered(WAIT_FOR_PASSWORD_PAGE))


async def enter_password(page, password: str) -> None:
    password_input = await wait_for_element(page, 'input[type="password"]', 15, 3, "password input")
    if not password_input:
        raise RuntimeError("Google password input not found")
    print("  ✔ Password page loaded")

    await asyncio.sleep(jittered(WAIT_BEFORE_PASSWORD_INPUT))
    await password_input.click()
    await asyncio.sleep(jittered(WAIT_AFTER_PASSWORD_CLICK))
    await credential_type(password_input, password)
    await asyncio.sleep(jittered(WAIT_AFTER_PASSWORD_INPUT))

    await page.bring_to_front()
    await asyncio.sleep(2)

    pwd_next = await wait_for_element(page, '#passwordNext', 10, 3, "password next button")
    if not pwd_next:
        raise RuntimeError("Password next button not found")
    await click_and_wait(pwd_next, page)
    print("  Waiting for login to complete…")
    await asyncio.sleep(jittered(WAIT_FOR_LOGIN_COMPLETE))


async def skip_passkey_prompt(page) -> None:
    """Dismiss Google's passkey setup prompt if it appears."""
    try:
        await page.bring_to_front()
        not_now = await page.find("Not now", best_match=True, timeout=5)
        if not_now:
            await not_now.click()
            print("  ✔ Skipped passkey prompt")
            await asyncio.sleep(2)
    except Exception:
        pass


async def handle_2fa(page, totp_secret: str) -> bool:
    """Handle Google Authenticator TOTP 2FA if the page appears."""
    try:
        await page.bring_to_front()
        await asyncio.sleep(jittered(WAIT_FOR_2FA_PAGE))

        totp_input = await wait_for_element(page, 'input[name="totpPin"]', 8, 2, "2FA input")
        if not totp_input:
            return False

        print("  ✔ 2FA page detected")
        if not totp_secret:
            print("  ⚠ 2FA required but no secret provided")
            return False

        import pyotp
        secret = totp_secret.replace(" ", "").replace("-", "").upper()
        code = pyotp.TOTP(secret).now()
        print(f"  Generated 2FA code: {code}")

        await credential_type(totp_input, code)
        await asyncio.sleep(jittered(WAIT_AFTER_2FA_INPUT))

        next_btn = await wait_for_element(page, '#totpNext', 5, 2, "2FA next")
        if not next_btn:
            next_btn = await page.find("Next", best_match=True, timeout=5)
        if next_btn:
            await click_and_wait(next_btn, page)
            print("  ✔ 2FA submitted")
            await asyncio.sleep(3)
            return True
        return False
    except Exception as e:
        print(f"  2FA error: {e}")
        return False


async def handle_recovery_email(page, recovery_email: str) -> None:
    """Handle Google verification via recovery email if prompted."""
    if not recovery_email:
        return
    try:
        await page.bring_to_front()
        verify = await page.find("Verify", best_match=True)
        if not verify:
            return
        print("  Verification prompt detected — using recovery email")
        await asyncio.sleep(jittered(WAIT_BEFORE_RECOVERY_OPTION))

        option = await page.find("recovery email", best_match=True)
        if option:
            await option.click()
        else:
            alt = await wait_for_element(page, 'div[role="link"][tabindex="0"]', 10, 3, "challenge option")
            if alt:
                await alt.click()

        await asyncio.sleep(jittered(WAIT_AFTER_RECOVERY_CLICK))
        await page.bring_to_front()

        email_input = await wait_for_element(page, 'input[type="email"]', 10, 3, "recovery email input")
        if not email_input:
            email_input = await wait_for_element(
                page, 'input[name="knowledgePreregisteredEmailResponse"]', 10, 3, "recovery alt input"
            )
        if email_input:
            await credential_type(email_input, recovery_email)
            next_btn = await page.find("Next", best_match=True)
            if next_btn:
                await next_btn.click()
            await asyncio.sleep(jittered(WAIT_AFTER_RECOVERY_SUBMIT))
    except Exception as e:
        print(f"  Recovery email error: {e}")


async def gmail_login(browser, email: str, password: str, recovery_email: str = None, totp_secret: str = None):
    """Full Google login flow — mirrors LinkedIn orchestrator's gmail_login signature.

    Opens accounts.google.com in a new browser tab, completes the full login:
    email → password → 2FA (if totp_secret provided) → recovery email (if provided) → skip passkey.

    Returns the page after successful login.
    """
    page = await open_page(browser, GOOGLE_ACCOUNTS_URL)
    await inject_stealth(page)
    print("  Waiting for Google login page…")

    await enter_email(page, email)
    await enter_password(page, password)
    await asyncio.sleep(5)  # let post-login challenges settle

    if totp_secret:
        await handle_2fa(page, totp_secret)
    if recovery_email:
        await handle_recovery_email(page, recovery_email)

    await skip_passkey_prompt(page)
    return page
