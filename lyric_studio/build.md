# Building Lyric Studio

## Development

```bash
cd lyric_studio
pip install -r requirements.txt
python main.py
```

## Package for Windows (.exe)

Run ON a Windows machine:

```bash
pip install flet
flet pack main.py --name "LyricStudio" --add-data "system_prompt.txt:." --add-data "../prompt/lyric_generation_prompt.md:prompt"
```

Output: `dist/LyricStudio.exe`

## Package for Mac (.app)

Run ON a Mac:

```bash
pip install flet
flet pack main.py --name "LyricStudio" --add-data "system_prompt.txt:." --add-data "../prompt/lyric_generation_prompt.md:prompt"
```

Output: `dist/LyricStudio.app`

## Prerequisites for end users

1. Claude Code must be installed (the app auto-installs it if missing)
2. User must have a Claude Pro or Max subscription
3. User must login once (the app guides them through this)
