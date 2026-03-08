#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build_mac.sh — macOS build script for LyricStudio
#
# Uses PyInstaller directly with --onedir + --windowed instead of `flet pack`.
# Why NOT `flet pack`:
#   - flet pack forces --onefile, which causes macOS 14/15 to silently block
#     the app on launch (the self-extraction to /tmp clashes with macOS security).
#
# This script:
#   1. Passes --additional-hooks-dir to fire flet_cli's hook-flet.py, which
#      collects flet Python modules + the embedded Flutter binary (flet-macos.tar.gz).
#   2. Uses --onedir so all files live inside the .app bundle — no temp extraction,
#      no macOS security block.
#   3. Uses --windowed to produce a proper .app bundle — zero terminal window.
#
# Usage (from any directory):
#   bash lyric_studio/deploy/build_mac.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LYRIC_STUDIO_DIR="$(dirname "$SCRIPT_DIR")"
PROMPT_FILE="$(dirname "$LYRIC_STUDIO_DIR")/prompt/lyric_generation_prompt.md"

cd "$LYRIC_STUDIO_DIR"

# ── Activate virtualenv ────────────────────────────────────────────────────
if [ ! -f ".venv/bin/activate" ]; then
    echo "ERROR: .venv not found. Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate

# ── Verify flet is installed ───────────────────────────────────────────────
if ! python -c "import flet" &>/dev/null; then
    echo "ERROR: flet not installed in .venv. Run: pip install -r requirements.txt"
    exit 1
fi

# ── Locate flet_cli's PyInstaller hooks directory ─────────────────────────
# hook-flet.py lives here — it collects flet Python package + flet-macos.tar.gz
FLET_HOOKS=$(python -c "import flet_cli.__pyinstaller as h, os; print(os.path.dirname(h.__file__))")
echo "flet hooks: $FLET_HOOKS"

# ── Find bundled claude CLI binary from claude_agent_sdk ──────────────────
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
    --windowed                          # .app bundle, zero terminal window
    --onedir                            # all files inside .app — no temp extraction
    --distpath "dist"
    --workpath "build"
    --noconfirm
    # --- flet hooks (collects flet package + Flutter binary) ---
    --additional-hooks-dir "${FLET_HOOKS}"
    # --- tell PyInstaller to look in lyric_studio/ for local packages (core/) ---
    --paths "."
    # --- data files (src:dest) ---
    --add-data "assets/system_prompt.txt:."
    --add-data "${PROMPT_FILE}:prompt"
    # --- hidden imports not reachable by static analysis ---
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
else
    echo "WARNING: claude_agent_sdk bundled binary not found — skipping."
fi

pyinstaller "${PYI_ARGS[@]}"

# ── Remove quarantine attribute (macOS Gatekeeper) ─────────────────────────
# Locally-built apps get quarantined, which causes "damaged/blocked" errors.
echo "Removing quarantine attribute..."
xattr -cr dist/LyricStudio.app 2>/dev/null || true

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo " Build complete!"
echo " App bundle: dist/LyricStudio.app"
echo " Double-click to open — no terminal window."
echo "=============================================="
