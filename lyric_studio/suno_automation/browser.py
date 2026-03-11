"""Browser lifecycle and element utilities for Suno automation."""
import asyncio
import random
from .config import VIEWPORT_SIZES, LANGUAGES, HEADLESS_MODE, WAIT_RETRY_ELEMENT, jittered


# ── Page Load ────────────────────────────────────────────────────

async def wait_page_loaded(page, timeout: float = 15) -> None:
    """Poll document.readyState until 'complete'."""
    elapsed = 0.0
    interval = 0.25
    while elapsed < timeout:
        try:
            state = await page.evaluate("document.readyState")
            if state == "complete":
                return
        except Exception:
            pass
        await asyncio.sleep(interval)
        elapsed += interval


# ── Element Helpers ──────────────────────────────────────────────

async def wait_for_element(page, selector: str, timeout: float = 15, retries: int = 3, name: str = "element"):
    """Retry finding a CSS selector element before giving up."""
    for attempt in range(retries):
        try:
            el = await page.select(selector, timeout=timeout)
            if el:
                return el
        except Exception:
            pass
        if attempt < retries - 1:
            print(f"  '{name}' not found, retry {attempt + 1}/{retries - 1}")
            await asyncio.sleep(jittered(WAIT_RETRY_ELEMENT))
    return None


async def click_and_wait(element, page, timeout: float = 15) -> None:
    """Click an element then wait for page to finish loading."""
    await element.click()
    await wait_page_loaded(page, timeout=timeout)


async def navigate(page, url: str, timeout: float = 15) -> None:
    """Navigate to URL and wait for load."""
    await page.get(url)
    await wait_page_loaded(page, timeout=timeout)


async def open_page(browser, url: str, timeout: float = 15):
    """Open a new browser page and wait for load."""
    page = await browser.get(url)
    await wait_page_loaded(page, timeout=timeout)
    return page


# ── Browser Lifecycle ────────────────────────────────────────────

async def create_stealth_browser():
    """Launch nodriver with randomised fingerprint."""
    import nodriver as uc

    vw, vh = random.choice(VIEWPORT_SIZES)
    lang = random.choice(LANGUAGES)

    browser = await uc.start(
        headless=HEADLESS_MODE,
        browser_args=[
            f"--window-size={vw},{vh}",
            f"--lang={lang.split(',')[0]}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
        no_sandbox=True,
    )
    return browser


async def inject_stealth(page) -> None:
    """Patch navigator.webdriver and permissions to avoid detection."""
    stealth_js = """
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false, configurable: true
        });
    } catch(e) {}
    try {
        const orig = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) =>
            p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : orig(p);
    } catch(e) {}
    """
    try:
        await page.evaluate(stealth_js)
    except Exception:
        pass


async def close_browser(browser) -> None:
    """Safely stop the browser instance."""
    try:
        if browser and not getattr(browser, "stopped", False):
            await browser.stop()
    except Exception:
        pass
