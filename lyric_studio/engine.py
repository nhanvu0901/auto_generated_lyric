"""Core lyric generation engine — wraps Claude Code CLI."""

import json
import os
import re
import subprocess
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
    """Auto-install Claude Code. Returns (success, message)."""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["powershell", "-Command", "irm https://claude.ai/install.ps1 | iex"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        elif system == "Darwin":
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            return False, "Unsupported OS. Please install Claude Code manually."

        if result.returncode == 0:
            return True, "Claude Code installed successfully!"
        return False, f"Installation failed:\n{result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return False, "Installation timed out. Please try again."
    except Exception as e:
        return False, f"Installation error: {e}"


def open_claude_login() -> tuple[bool, str]:
    """Run claude login to authenticate."""
    try:
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
    """Generate lyrics using Claude Code CLI.

    Args:
        genre: Music genre
        theme: Song theme/topic
        model: Model ID (claude-opus-4-6 or claude-sonnet-4-6)
        num_songs: Number of songs to generate
        on_progress: Optional callback(song_index, total, status_text)

    Returns:
        List of song dicts with keys: title, genre, theme, bpm, central_metaphor, lyrics
    """
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    all_songs = []

    def prog(status: str):
        if on_progress:
            on_progress(len(all_songs), num_songs, status)

    # Generate one at a time for better quality and progress tracking
    for i in range(num_songs):
        prog(f"[{i+1}/{num_songs}] Building prompt…")

        user_prompt = build_user_prompt(genre, theme, 1)

        cmd = [
            "claude",
            "-p",
            "--model", model,
            "--tools", "",
            "--max-turns", "1",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--system-prompt", system_prompt,
            user_prompt,
        ]

        prog(f"[{i+1}/{num_songs}] Connecting to Claude ({model})…")

        proc = None
        try:
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,          # line-buffered for real-time output
                env=env,
            )

            raw = ""           # final complete text
            token_buf = ""     # accumulate partial tokens for log lines
            hit_limit = False

            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                # Non-JSON lines (raw errors/messages)
                if not line.startswith("{"):
                    limit_msg = check_for_limit_error(line)
                    if limit_msg:
                        prog(f"⚠ LIMIT HIT: {limit_msg}")
                        prog("Wait for your usage window to reset, then try again.")
                        hit_limit = True
                        proc.kill()
                        break
                    prog(f"  {line[:200]}")
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                # ── stream_event: contains token deltas ──
                if etype == "stream_event":
                    inner = event.get("event", {})
                    inner_type = inner.get("type", "")

                    if inner_type == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            token_buf += chunk
                            # Flush complete lines to log
                            while "\n" in token_buf:
                                log_line, token_buf = token_buf.split("\n", 1)
                                if log_line.strip():
                                    prog(f"  {log_line}")

                    elif inner_type == "message_start":
                        prog(f"  Claude is writing…")

                # ── system init ──
                elif etype == "system" and event.get("subtype") == "init":
                    prog(f"  Session started")

                # ── rate_limit_event ──
                elif etype == "rate_limit_event":
                    info = event.get("rate_limit_info", {})
                    status = info.get("status", "")
                    if status != "allowed":
                        prog(f"⚠ LIMIT HIT: rate limit status = {status}")
                        prog("Wait for your usage window to reset, then try again.")
                        hit_limit = True
                        proc.kill()
                        break

                # ── final result ──
                elif etype == "result":
                    subtype = event.get("subtype", "")
                    raw = event.get("result", "").strip()
                    cost = event.get("total_cost_usd")
                    duration = event.get("duration_ms")
                    if duration:
                        prog(f"  Done in {duration/1000:.1f}s" +
                             (f" · ${cost:.4f}" if cost else ""))
                    if subtype != "success":
                        error = event.get("error", subtype)
                        limit_msg = check_for_limit_error(str(error))
                        if limit_msg:
                            prog(f"⚠ LIMIT HIT: {limit_msg}")
                            hit_limit = True
                        else:
                            prog(f"[{i+1}/{num_songs}] Error: {error}")

                # ── assistant message (full or partial) ──
                elif etype == "assistant":
                    pass  # tokens already streamed via stream_event

                # ── error event ──
                elif etype == "error":
                    msg = str(event.get("error", event))[:300]
                    limit_msg = check_for_limit_error(msg)
                    if limit_msg:
                        prog(f"⚠ LIMIT HIT: {limit_msg}")
                        hit_limit = True
                        proc.kill()
                        break
                    prog(f"  Error: {msg}")

            # Flush any remaining token buffer
            if token_buf.strip():
                prog(f"  {token_buf.strip()}")

            if hit_limit:
                break

            proc.wait(timeout=30)
            stderr_out = proc.stderr.read().strip()

            if stderr_out:
                limit_msg = check_for_limit_error(stderr_out)
                if limit_msg:
                    prog(f"⚠ LIMIT HIT: {limit_msg}")
                    prog("Wait for your usage window to reset, then try again.")
                    continue
                prog(f"  stderr: {stderr_out[:300]}")

            if not raw:
                prog(f"[{i+1}/{num_songs}] No output received — skipping.")
                continue

            prog(f"[{i+1}/{num_songs}] Parsing lyrics…")
            songs = parse_songs(raw, genre, theme)
            if not songs:
                song = parse_single_song(raw, genre, theme)
                if song:
                    songs = [song]

            if songs:
                prog(f"[{i+1}/{num_songs}] ✓ \"{songs[0]['title']}\"")
                all_songs.extend(songs)
            else:
                prog(f"[{i+1}/{num_songs}] Could not parse output — skipping.")

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            prog(f"[{i+1}/{num_songs}] Timed out — process killed.")
        except Exception as e:
            prog(f"[{i+1}/{num_songs}] Exception: {e}")

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
