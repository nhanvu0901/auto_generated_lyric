"""
Quick test: What does YOUR Suno account actually need?

Tests:
1. Can we get a session ID + JWT from your cookie?
2. What does /api/c/check return? (captcha required or not?)
3. What does /api/billing/info/ say? (credits?)
4. Try generate with token=null — does it work or 422?
"""

import json
import sys
sys.path.insert(0, ".")

from core.config import load_config

config = load_config()
cookie_str = config.get("suno_cookie", "")
if not cookie_str:
    print("ERROR: No suno_cookie in config. Connect your account first.")
    sys.exit(1)

print(f"Cookie length: {len(cookie_str)} chars")
print(f"Has __client: {'__client' in cookie_str}")
print()

# ── Step 1: Initialize client (session ID + JWT) ──────────────────────────────
print("=" * 60)
print("STEP 1: Initialize SunoClient (session ID + JWT)")
print("=" * 60)
try:
    from core.suno_client import SunoClient
    client = SunoClient(cookie_str, on_log=lambda m: print(f"  [{m}]"))
    print("✓ Client initialized successfully")
except Exception as e:
    print(f"✗ Client init FAILED: {e}")
    sys.exit(1)

# ── Step 2: Check credits ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 2: Check billing/credits")
print("=" * 60)
try:
    credits = client.get_credits()
    print(f"✓ Credits: {json.dumps(credits, indent=2)}")
except Exception as e:
    print(f"✗ Credits check FAILED: {e}")

# ── Step 3: Captcha check ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 3: /api/c/check — Is captcha required?")
print("=" * 60)
try:
    captcha_needed = client.check_captcha_required()
    print(f"✓ Captcha required: {captcha_needed}")
except Exception as e:
    print(f"✗ Captcha check FAILED: {e}")
    captcha_needed = "unknown"

# ── Step 4: Try generate with token=null ──────────────────────────────────────
print()
print("=" * 60)
print("STEP 4: Try generate with token=null (no captcha)")
print("=" * 60)

if captcha_needed == True:
    print("⚠ Captcha IS required — trying anyway to see exact error...")

import requests as req
from core.suno_client import STUDIO_BASE

# Refresh token first
client._do_refresh_token()
headers = client._api_headers()

# Test payload — minimal custom lyrics
test_payloads = [
    {
        "name": "token=null",
        "payload": {
            "prompt": "[Verse]\nThis is a test\n\n[Chorus]\nJust a test song",
            "tags": "pop, acoustic",
            "title": "Test Song",
            "mv": "chirp-auk",
            "make_instrumental": False,
            "generation_type": "TEXT",
            "token": None,
        }
    },
    {
        "name": "no token field at all",
        "payload": {
            "prompt": "[Verse]\nThis is a test\n\n[Chorus]\nJust a test song",
            "tags": "pop, acoustic",
            "title": "Test Song",
            "mv": "chirp-auk",
            "make_instrumental": False,
            "generation_type": "TEXT",
        }
    },
    {
        "name": "token=empty string",
        "payload": {
            "prompt": "[Verse]\nThis is a test\n\n[Chorus]\nJust a test song",
            "tags": "pop, acoustic",
            "title": "Test Song",
            "mv": "chirp-auk",
            "make_instrumental": False,
            "generation_type": "TEXT",
            "token": "",
        }
    },
]

for test in test_payloads:
    print(f"\n--- Testing: {test['name']} ---")
    client._do_refresh_token()
    headers = client._api_headers()
    try:
        r = req.post(
            f"{STUDIO_BASE}/api/generate/v2/",
            json=test["payload"],
            headers=headers,
            timeout=30,
        )
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        if r.status_code == 200:
            clips = r.json().get("clips", [])
            print(f"  ✓ SUCCESS! Got {len(clips)} clip(s)")
            for c in clips:
                print(f"    clip id={c.get('id')} status={c.get('status')}")
            # Don't try the remaining tests if one works
            print("\n🎉 GENERATION WORKS WITHOUT CAPTCHA!")
            break
    except Exception as e:
        print(f"  ✗ Request FAILED: {e}")

print()
print("=" * 60)
print("DONE")
print("=" * 60)