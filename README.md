# AI Lyric Generation System

Generate professional song lyrics using AI with a modern GUI or CLI scripts.

## 📁 Project Structure

```
auto_generated_lyric/
├── lyric_studio/     # GUI app (RECOMMENDED)
├── code/             # Legacy CLI scripts
├── data/             # Sample datasets
├── prompt/           # AI prompt templates
└── song/             # Example outputs
```

## 🚀 Quick Start

```bash
cd lyric_studio
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.8+, Claude Pro/Max subscription

## 🎵 Lyric Studio (Main App)

Modern desktop GUI with real-time streaming and batch processing.

**Features:**
- Real-time lyric streaming
- Batch processing (2 songs per API call = 50% fewer calls)
- 10 genres, 2 AI models (Opus 4, Sonnet 4)
- Auto-scroll logs, song preview tabs
- Smart error handling, rate limit detection

**Usage:**
1. Enter theme (e.g., "first love")
2. Select genre and model
3. Set song count (1-20)
4. Click Generate
5. View songs in tabs

**First-Time Setup:**
- App auto-installs Claude Code if needed
- Login to Claude when prompted
- Start generating!

**Batch Processing:**
- 1 song → 1 call
- 5 songs → 3 calls (2+2+1)
- 10 songs → 5 calls (2+2+2+2+2)

## 💻 Legacy CLI (code/)

Original DeepSeek API scripts. Edit `lyric_generated.py` to set API key and parameters, then run.

## 📊 Other Folders

- **data/** - Sample lyric datasets and benchmarks
- **prompt/** - AI prompt template with songwriting guidelines
- **song/** - Example generated songs

## 🐛 Troubleshooting

**"Claude Code not installed"** → Click "Install" in setup wizard

**"Rate limit hit"** → Wait for reset (hourly) or upgrade to Claude Max

**Songs not saving** → Check Settings → Output Folder permissions

## 📦 Build Executable

**Recommended Method (Most Reliable):**

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. Build using the spec file from the deploy folder:
   ```bash
   cd deploy
   pyinstaller LyricStudio.spec
   ```

**Output:** `deploy/dist/LyricStudio.exe` (Windows) or `deploy/dist/LyricStudio.app` (macOS)

**Troubleshooting:** See `PACKAGING_GUIDE.md` for detailed instructions and solutions.

---

**Happy songwriting! 🎵**
