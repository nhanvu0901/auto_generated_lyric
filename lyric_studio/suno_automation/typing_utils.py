"""Reliable typing helpers for nodriver input fields.

nodriver's element.send_keys() does ONE focus() then dispatches all chars
rapidly — this is the safest approach for React/Clerk inputs that reset
state on repeated focus/blur cycles.
"""
import asyncio
import random
from .config import TYPING_MIN_DELAY, TYPING_MAX_DELAY


async def credential_type(element, text: str) -> None:
    """Type a credential string with a single focus+send to avoid React state resets."""
    if not text:
        return
    await asyncio.sleep(random.uniform(0.2, 0.6))
    await element.send_keys(text)
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def human_type(element, text: str) -> None:
    """Character-by-character typing with human delays — for non-critical fields."""
    if not text:
        return
    import nodriver.cdp.input_ as cdp_input

    tab = element._tab
    await element.apply("(el) => el.focus()")
    await asyncio.sleep(random.uniform(0.15, 0.35))

    for char in text:
        await tab.send(cdp_input.dispatch_key_event("char", text=char))
        await asyncio.sleep(random.uniform(TYPING_MIN_DELAY, TYPING_MAX_DELAY))
        if random.random() < 0.03:
            await asyncio.sleep(random.uniform(0.2, 0.5))

    await asyncio.sleep(random.uniform(0.1, 0.3))
