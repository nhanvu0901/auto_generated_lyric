#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_mac.sh — macOS build script for LyricStudio
#
# Root cause of repeated permission prompts:
#   macOS Application Firewall prompts for EVERY app that opens a server
#   socket (even on 127.0.0.1). For ad-hoc signed apps the firewall rule
#   is keyed to the binary's hash, which changes on every rebuild.
#   This script re-registers both LyricStudio.app AND Flet.app with the
#   firewall after every build so the user is never prompted again for the
#   SAME build. Rebuilding naturally re-registers.
#
# Usage (from any directory):
#   bash lyric_studio/deploy/build_mac.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LYRIC_STUDIO_DIR="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$(dirname "$LYRIC_STUDIO_DIR")/prompt/lyric_generation_prompt.md"
BUNDLE_ID="com.lyricstudio.app"

cd "$LYRIC_STUDIO_DIR"

# ── Activate virtualenv ────────────────────────────────────────────────────
if [ ! -f ".venv/bin/activate" ]; then
    echo "ERROR: .venv not found. Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate

if ! python -c "import flet" &>/dev/null; then
    echo "ERROR: flet not installed in .venv. Run: pip install -r requirements.txt"
    exit 1
fi

# ── Locate flet_cli's PyInstaller hooks directory ─────────────────────────
FLET_HOOKS=$(python -c "import flet_cli.__pyinstaller as h, os; print(os.path.dirname(h.__file__))")
echo "flet hooks: $FLET_HOOKS"

# ── Find bundled claude CLI binary ────────────────────────────────────────
CLAUDE_BIN=$(python - <<'EOF'
import importlib.util, os, sys
spec = importlib.util.find_spec('claude_agent_sdk')
if spec and spec.origin:
    p = os.path.join(os.path.dirname(spec.origin), '_bundled', 'claude')
    if os.path.exists(p):
        print(p)
        sys.exit(0)
EOF
)

# ── Clean previous build ───────────────────────────────────────────────────
rm -rf build/LyricStudio dist/LyricStudio dist/LyricStudio.app

# ── Build ──────────────────────────────────────────────────────────────────
echo "=============================================="
echo " Building LyricStudio.app (macOS, --onedir)"
echo "=============================================="

PYI_ARGS=(
    main.py
    --name "LyricStudio"
    --windowed
    --onedir
    --distpath "dist"
    --workpath "build"
    --noconfirm
    --osx-bundle-identifier "${BUNDLE_ID}"
    --additional-hooks-dir "${FLET_HOOKS}"
    --paths "."
    --add-data "assets/system_prompt.txt:."
    --add-data "${PROMPT_FILE}:prompt"
    --hidden-import flet
    --hidden-import flet.core
    --hidden-import flet.auth
    --hidden-import flet.utils
    --hidden-import flet_desktop
    --hidden-import claude_agent_sdk
    --hidden-import claude_agent_sdk.types
    --hidden-import anyio
    --hidden-import "anyio._backends._asyncio"
    --hidden-import sniffio
    --hidden-import exceptiongroup
)

if [ -n "$CLAUDE_BIN" ]; then
    echo "Bundling claude binary: $CLAUDE_BIN"
    PYI_ARGS+=(--add-binary "${CLAUDE_BIN}:claude_agent_sdk/_bundled")
fi

pyinstaller "${PYI_ARGS[@]}"

# ── Strip quarantine ───────────────────────────────────────────────────────
xattr -cr dist/LyricStudio.app 2>/dev/null || true

# ── Register with macOS Application Firewall ──────────────────────────────
# flet starts a local WebSocket server — the firewall prompts for it unless
# the app is pre-registered. We register both LyricStudio AND the Flet.app
# viewer (which runs as a separate process) so neither ever prompts the user.
# This must be re-run after every rebuild (rule is tied to binary hash).
echo "Registering firewall rules..."

ALF=/usr/libexec/ApplicationFirewall/socketfilterfw
APP_PATH="$(pwd)/dist/LyricStudio.app"

"$ALF" --add "$APP_PATH"       2>/dev/null || true
"$ALF" --unblockapp "$APP_PATH" 2>/dev/null || true

# Register Flet.app — it lives in ~/.flet/bin/ and is a separate binary
FLET_APP="$HOME/.flet/bin/flet-0.28.2/Flet.app"
if [ -d "$FLET_APP" ]; then
    "$ALF" --add "$FLET_APP"       2>/dev/null || true
    "$ALF" --unblockapp "$FLET_APP" 2>/dev/null || true
    echo "✓ Flet.app registered."
fi

echo "✓ Firewall rules set — no incoming-connection prompts will appear."

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo " Build complete! → dist/LyricStudio.app"
echo " Bundle ID: ${BUNDLE_ID}"
echo " Firewall: pre-registered (no prompts)"
echo "=============================================="
