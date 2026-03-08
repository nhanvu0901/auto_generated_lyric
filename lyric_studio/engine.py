"""Core lyric generation engine — uses Claude Agent SDK for real-time streaming."""

import asyncio
import json
import os
import re
import platform
import shutil
from pathlib import Path

SONG_START = "===SONG_START==="
SONG_END = "===SONG_END==="

SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
LYRIC_PROMPT_PATH = (
    Path(__file__).parent.parent / "prompt" / "lyric_generation_prompt.md"
)


def is_claude_installed() -> bool:
    """Check if Claude Code CLI is available (bundled with SDK or system-wide)."""
    try:
        import claude_agent_sdk
        return True
    except ImportError:
        return shutil.which("claude") is not None


LIMIT_PHRASES = [
    "usage limit",
    "rate limit",
    "quota",
    "too many requests",
    "limit reached",
    "please slow down",
    "overloaded",
    "capacity",
    "try again later",
    "upgrade your plan",
]

def check_for_limit_error(text: str) -> str | None:
    """Return a human-readable limit message if the output signals a usage/rate limit, else None."""
    lower = text.lower()
    if any(phrase in lower for phrase in LIMIT_PHRASES):
        # Try to extract the raw message from claude's output
        for line in text.splitlines():
            if any(phrase in line.lower() for phrase in LIMIT_PHRASES):
                return line.strip()
        return "Usage or rate limit reached on your Claude account."
    return None


def is_claude_logged_in() -> bool:
    """Check login by reading ~/.claude.json — instant, no subprocess needed."""
    try:
        import json
        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return False
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        return bool(data.get("oauthAccount"))
    except Exception:
        return False


def install_claude_code() -> tuple[bool, str]:
    """Install Claude Agent SDK (includes bundled CLI). Returns (success, message)."""
    try:
        import subprocess
        result = subprocess.run(
            ["pip", "install", "claude-agent-sdk"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, "Claude Agent SDK installed successfully!"
        return False, f"Installation failed:\n{result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return False, "Installation timed out. Please try again."
    except Exception as e:
        return False, f"Installation error: {e}"


def open_claude_login() -> tuple[bool, str]:
    """Run claude login to authenticate."""
    try:
        import subprocess
        result = subprocess.run(
            ["claude", "login"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True, "Login successful!"
        return False, f"Login issue: {result.stderr or result.stdout}"
    except Exception as e:
        return False, f"Login error: {e}"


def load_lyric_prompt_template() -> str:
    """Load the lyric generation prompt, extracting content from the code block."""
    text = LYRIC_PROMPT_PATH.read_text(encoding="utf-8")
    cutoff = text.find("## How to Use")
    if cutoff != -1:
        text = text[:cutoff].strip()
    match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def build_user_prompt(genre: str, theme: str, num_songs: int) -> str:
    """Build the full prompt for Claude."""
    template = load_lyric_prompt_template()
    filled = template.replace("{GENRE}", genre).replace("{THEME}", theme)

    if num_songs == 1:
        return (
            f"Generate exactly 1 original {genre} song about: {theme}\n\n"
            f"Follow these songwriting instructions:\n\n"
            f"{filled}"
        )

    return (
        f"Generate exactly {num_songs} distinct original {genre} songs about: {theme}\n\n"
        f"Follow these songwriting instructions for EACH song:\n\n"
        f"{filled}\n\n"
        f"FORMATTING RULE:\n"
        f"Wrap each complete song with:\n"
        f"{SONG_START}\n"
        f"[full lyrics + Title/BPM/Central Metaphor footer]\n"
        f"{SONG_END}\n\n"
        f"Produce exactly {num_songs} such blocks. No text outside the delimiters."
    )


def generate_lyrics(
    genre: str,
    theme: str,
    model: str,
    num_songs: int = 1,
    on_progress=None,
) -> list[dict]:
    """Generate lyrics using Claude Agent SDK with real-time streaming.

    Args:
        genre: Music genre
        theme: Song theme/topic
        model: Model ID (claude-opus-4-6 or claude-sonnet-4-6)
        num_songs: Number of songs to generate
        on_progress: Optional callback(song_index, total, status_text)

    Returns:
        List of song dicts with keys: title, genre, theme, bpm, central_metaphor, lyrics
    """
    try:
        import anyio
        from claude_agent_sdk import query, ClaudeAgentOptions
        from claude_agent_sdk.types import AssistantMessage, TextBlock, StreamEvent
    except ImportError:
        if on_progress:
            on_progress(0, num_songs, "ERROR: claude-agent-sdk not installed. Run: pip install claude-agent-sdk")
        return []

    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    all_songs = []

    def prog(status: str):
        if on_progress:
            on_progress(len(all_songs), num_songs, status)

    async def generate_song(index: int):
        prog(f"[{index+1}/{num_songs}] Building prompt…")
        
        user_prompt = build_user_prompt(genre, theme, 1)
        
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            max_turns=1,
            allowed_tools=[],
            include_partial_messages=True,
        )

        prog(f"[{index+1}/{num_songs}] Connecting to Claude ({model})…")

        raw_text = ""
        current_line = ""
        hit_limit = False

        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, StreamEvent):
                    event = message.event
                    event_type = event.get("type", "")
                    
                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            raw_text += chunk
                            current_line += chunk
                            
                            while "\n" in current_line:
                                line, current_line = current_line.split("\n", 1)
                                if line.strip():
                                    prog(f"  {line[:100]}")
                    
                    elif event_type == "message_start":
                        prog(f"  Claude is writing…")
                    
                    elif event_type == "message_stop":
                        if current_line.strip():
                            prog(f"  {current_line[:100]}")
                        prog(f"  Generation complete")

                elif isinstance(message, AssistantMessage):
                    if not raw_text:
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                raw_text += block.text
                
                if "usage limit" in raw_text.lower() or "rate limit" in raw_text.lower():
                    limit_msg = check_for_limit_error(raw_text)
                    if limit_msg:
                        prog(f"⚠ LIMIT HIT: {limit_msg}")
                        prog("Wait for your usage window to reset, then try again.")
                        hit_limit = True
                        break

            if hit_limit:
                return None

            if not raw_text:
                prog(f"[{index+1}/{num_songs}] No output received — skipping.")
                return None

            prog(f"[{index+1}/{num_songs}] Parsing lyrics…")
            songs = parse_songs(raw_text, genre, theme)
            if not songs:
                song = parse_single_song(raw_text, genre, theme)
                if song:
                    songs = [song]

            if songs:
                prog(f"[{index+1}/{num_songs}] ✓ \"{songs[0]['title']}\"")
                return songs[0]
            else:
                prog(f"[{index+1}/{num_songs}] Could not parse output — skipping.")
                return None

        except Exception as e:
            prog(f"[{index+1}/{num_songs}] Exception: {e}")
            return None

    async def generate_all():
        for i in range(num_songs):
            song = await generate_song(i)
            if song:
                all_songs.append(song)
            if "LIMIT HIT" in (on_progress.__self__ if hasattr(on_progress, '__self__') else ''):
                break

    anyio.run(generate_all)
    
    prog(f"Finished. {len(all_songs)}/{num_songs} song(s) generated.")
    return all_songs


def parse_songs(raw_text: str, genre: str, theme: str) -> list[dict]:
    """Parse multiple songs from delimited output."""
    pattern = re.compile(
        re.escape(SONG_START) + r"\s*(.*?)\s*" + re.escape(SONG_END),
        re.DOTALL,
    )
    blocks = pattern.findall(raw_text)
    songs = []
    for block in blocks:
        song = _parse_block(block, genre, theme)
        if song:
            songs.append(song)
    return songs


def parse_single_song(raw_text: str, genre: str, theme: str) -> dict | None:
    """Parse a single song without delimiters."""
    if "[Verse 1]" in raw_text or "[Verse]" in raw_text:
        return _parse_block(raw_text, genre, theme)
    return None


def _parse_block(block: str, genre: str, theme: str) -> dict | None:
    """Parse a single song block into a structured dict."""
    title_match = re.search(
        r"^Title\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE
    )
    bpm_match = re.search(r"^BPM\s*:\s*(\d+)", block, re.MULTILINE | re.IGNORECASE)
    metaphor_match = re.search(
        r"^Central Metaphor\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE
    )

    title = title_match.group(1).strip().strip("\"'") if title_match else "Untitled"
    bpm = int(bpm_match.group(1)) if bpm_match else 0
    central_metaphor = metaphor_match.group(1).strip() if metaphor_match else ""

    # Extract lyrics (everything before the footer)
    footer_start = re.search(
        r"^(Title|BPM|Central Metaphor)\s*:", block, re.MULTILINE | re.IGNORECASE
    )
    lyrics_text = block[: footer_start.start()].strip() if footer_start else block.strip()

    lines = [line.strip() for line in lyrics_text.splitlines() if line.strip()]
    lyrics = "\n".join(lines)

    if not lyrics:
        return None

    return {
        "title": title,
        "genre": genre,
        "theme": theme,
        "bpm": bpm,
        "central_metaphor": central_metaphor,
        "lyrics": lyrics,
    }


def save_songs(songs: list[dict], output_dir: str) -> list[Path]:
    """Save songs as .txt files. Returns list of file paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = []
    for i, song in enumerate(songs):
        slug = re.sub(r"[^\w\s-]", "", song["title"].lower())
        slug = re.sub(r"[\s-]+", "_", slug).strip("_")[:60]
        # Avoid overwriting existing files by appending a number if needed
        base = out / f"{slug}.txt"
        filepath = base
        counter = 2
        while filepath.exists():
            filepath = out / f"{slug}_{counter}.txt"
            counter += 1
        filename = filepath.name
        filepath = out / filename
        content = song["lyrics"]
        content += f"\n\nTitle: {song['title']}"
        content += f"\nBPM: {song['bpm']}"
        if song["central_metaphor"]:
            content += f"\nCentral Metaphor: {song['central_metaphor']}"
        content += f"\nGenre: {song['genre']}"
        content += f"\nTheme: {song['theme']}"
        filepath.write_text(content, encoding="utf-8")
        paths.append(filepath)

    return paths
