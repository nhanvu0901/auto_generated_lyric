"""Timing constants and browser config for Suno automation."""
import random

# ── Browser ──────────────────────────────────────────────────────
HEADLESS_MODE = False

VIEWPORT_SIZES = [
    (1366, 768), (1440, 900), (1536, 864),
    (1600, 900), (1920, 1080), (1280, 800),
]

LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,vi;q=0.8",
]

# ── Jitter ───────────────────────────────────────────────────────
JITTER_MIN = 0.8
JITTER_MAX = 1.4

def jittered(base: float) -> float:
    return base * random.uniform(JITTER_MIN, JITTER_MAX)

# ── Typing ───────────────────────────────────────────────────────
TYPING_MIN_DELAY = 0.04
TYPING_MAX_DELAY = 0.12

# ── Wait Timings (seconds) ───────────────────────────────────────
WAIT_AFTER_EMAIL_INPUT    = 3
WAIT_FOR_PASSWORD_PAGE    = 4
WAIT_BEFORE_PASSWORD_INPUT = 1
WAIT_AFTER_PASSWORD_CLICK = 0.5
WAIT_AFTER_PASSWORD_INPUT = 4
WAIT_FOR_LOGIN_COMPLETE   = 5
WAIT_FOR_2FA_PAGE         = 3
WAIT_AFTER_2FA_INPUT      = 2
WAIT_BEFORE_RECOVERY_OPTION = 1
WAIT_AFTER_RECOVERY_CLICK = 2
WAIT_AFTER_RECOVERY_SUBMIT = 3
WAIT_RETRY_ELEMENT        = 1

# Suno-specific
WAIT_AFTER_SUNO_PAGE_LOAD = 3
WAIT_AFTER_GOOGLE_BTN     = 3
WAIT_FOR_SUNO_REDIRECT    = 90   # max seconds to wait for post-login redirect
WAIT_SUNO_SESSION_INIT    = 5    # wait after navigating to /create
