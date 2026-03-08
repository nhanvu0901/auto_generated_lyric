# AI Lyric Generation System

Generate professional song lyrics using Claude AI with a modern desktop GUI.

## Project Structure

```
auto_generated_lyric/
├── lyric_studio/          # Desktop GUI app (main)
│   ├── main.py            # Entry point — Flet UI
│   ├── requirements.txt
│   ├── core/              # Business logic
│   │   ├── engine.py      # Claude Agent SDK, lyric generation, parsing
│   │   └── config.py      # Settings, model list, genre list
│   ├── assets/            # Static resources
│   │   └── system_prompt.txt
│   └── deploy/            # Build
│       └── LyricStudio.spec  # PyInstaller spec (Windows & macOS)
├── prompt/                # AI prompt templates
├── data/                  # Sample datasets
└── song/                  # Example generated outputs
```

## Quick Start

**Requirements:** Python 3.10+, Claude Pro or Max subscription

```bash
cd lyric_studio
pip install -r requirements.txt
python main.py
```

The app checks for Claude Code on launch and guides you through login if needed.

## Features

- Real-time lyric streaming from Claude
- 7 genres: Pop, Rock, Country, R&B, Folk, Indie, Hip-Hop
- 2 models: Opus 4.6 (quality) and Sonnet 4.6 (speed)
- Batch processing — 2 songs per API call (e.g. 5 songs = 3 calls)
- Song preview tabs with title, BPM, central metaphor
- Auto-saves lyrics as `.txt` files to a configurable output folder

## Usage

1. Enter a theme (e.g. "first love", "road trip")
2. Select genre and model
3. Set song count (1–20)
4. Click **Generate Lyrics**
5. Browse results in the song tabs

## Build a Standalone Executable

Run from the `lyric_studio/` directory (not from `deploy/`):

### Windows

```bash
cd lyric_studio
pip install pyinstaller
pyinstaller deploy/LyricStudio.spec
```

Output: `deploy/dist/LyricStudio.exe`

The build script automatically bundles the `claude` CLI binary that ships
with `claude-agent-sdk`, so the executable works without a separate Claude
Code installation.

### macOS

```bash
cd lyric_studio
pip install pyinstaller
pyinstaller deploy/LyricStudio.spec
```

Output: `deploy/dist/LyricStudio.app`

**First launch on macOS:** Right-click the `.app` and choose **Open** to bypass
Gatekeeper. Unsigned apps are blocked on double-click the first time.

The same spec file works on both platforms — it detects the OS automatically.

## Troubleshooting

**"Claude Code is not installed"**
The app needs the `claude` CLI. Click **Install Claude Code** in the setup
screen, or install manually: `npm install -g @anthropic-ai/claude-code`.

**App freezes / button stays disabled after clicking Generate**
This was a known bug fixed in the current version. Make sure you are running
the latest `engine.py` and `main.py`. The fix ensures errors during generation
are always shown in the log rather than silently killing the background thread.

**"Rate limit hit" or "Usage limit reached"**
Your Claude account has reached its hourly usage cap. Wait for the reset window
(shown in the log) or upgrade to Claude Max for higher limits.

**Songs not saving**
Open **Settings** (gear icon) and confirm the Output Folder path exists and is
writable.

**macOS: app quits immediately after opening**
Run from Terminal to see the error:
```bash
/path/to/LyricStudio.app/Contents/MacOS/LyricStudio
```
Common causes: missing Claude login (`~/.claude.json` absent) or a corrupted
build. Re-build with a fresh `pip install`.

**Windows: antivirus flags the executable**
PyInstaller executables are sometimes flagged as false positives. Add an
exclusion for the `deploy/dist/` folder, or run from source with
`python main.py` instead.
