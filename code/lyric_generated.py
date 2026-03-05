import json
import os
import re
import time
from pathlib import Path

import requests

# ── CONFIG ──────────────────────────────────────
DEEPSEEK_API_KEY = ""
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
PROMPT_PATH      = Path(__file__).parent.parent / "data" / "lyric_generation_prompt.md"
OUTPUT_DIR       = Path(__file__).parent / "output"
NUM_LYRICS       = 10    # total number of lyrics to generate
BATCH_SIZE       = 2     # how many lyrics per single API call
GENRE            = "country"
THEME            = "childhood nostalgia"
# ── API payload params ───────────────────────────
MODEL            = "deepseek-chat"
TEMPERATURE      = 1
# ────────────────────────────────────────────────

SONG_START = "===SONG_START==="
SONG_END   = "===SONG_END==="


def load_prompt_template(path: str) -> str:
    """Read the full prompt, excluding the How to Use — Examples section."""
    text = Path(path).read_text(encoding="utf-8")
    # Drop the examples section and everything after it
    cutoff = text.find("## How to Use")
    if cutoff != -1:
        text = text[:cutoff].strip()
    # Extract the content inside the fenced code block
    match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError(f"No fenced code block found in {path}")
    return match.group(1).strip()


def build_messages(prompt_template: str, genre: str, theme: str, n: int) -> list[dict]:
    """Return the messages list for the DeepSeek API call.

    The system message instructs the model to produce exactly n songs,
    each wrapped in the defined delimiters so the parser can reliably split them.
    """
    filled_prompt = prompt_template.replace("{GENRE}", genre).replace("{THEME}", theme)

    system_content = (
        f"You are a world-class songwriter. You will generate exactly {n} distinct, "
        f"original songs following the instructions given. "
        f"Wrap EACH complete song (lyrics + footer) with the delimiters "
        f"{SONG_START} on its own line before the song and {SONG_END} on its own line after. "
        f"Do NOT output anything outside the delimiters. "
        f"Every song must have a unique title and fully independent lyrics."
    )

    user_content = (
        f"Generate exactly {n} original {genre} songs about: {theme}\n\n"
        f"Follow these detailed songwriting instructions for EACH song:\n\n"
        f"{filled_prompt}\n\n"
        f"CRITICAL FORMATTING RULE:\n"
        f"Wrap each complete song with:\n"
        f"{SONG_START}\n"
        f"[full lyrics + Title/BPM/Central Metaphor footer]\n"
        f"{SONG_END}\n\n"
        f"Produce exactly {n} such blocks, one after another, with no text outside the delimiters."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]


def call_deepseek(messages: list[dict]) -> str:
    """POST to the DeepSeek chat completions endpoint and return the assistant's text."""
    api_key = DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "No API key found. Set DEEPSEEK_API_KEY in the config or as an environment variable."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
    }

    print(f"[API] Sending request to DeepSeek (model: {payload['model']}, temperature: {payload['temperature']})...")
    t_start = time.time()

    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)

    elapsed = time.time() - t_start
    print(f"[API] Response received in {elapsed:.1f}s — HTTP {response.status_code}")

    if response.status_code != 200:
        print(f"[ERROR] DeepSeek API returned {response.status_code}:\n{response.text}")
        response.raise_for_status()

    data = response.json()
    usage = data.get("usage", {})
    if usage:
        print(
            f"[API] Tokens — prompt: {usage.get('prompt_tokens', '?')}, "
            f"completion: {usage.get('completion_tokens', '?')}, "
            f"total: {usage.get('total_tokens', '?')}"
        )

    content = data["choices"][0]["message"]["content"]
    preview = content[:120].replace("\n", " ")
    print(f"[API] Response preview: {preview}...")

    return content


def parse_songs(raw_text: str) -> list[dict]:
    """Split on delimiters and parse each song block into a structured dict.

    Each song block is expected to contain:
      - Section-labeled lyrics ([Verse 1], [Chorus], etc.)
      - A footer with Title:, BPM:, Central Metaphor:
    """
    # Extract everything between SONG_START / SONG_END pairs
    pattern = re.compile(
        re.escape(SONG_START) + r"\s*(.*?)\s*" + re.escape(SONG_END),
        re.DOTALL,
    )
    blocks = pattern.findall(raw_text)

    songs = []
    for i, block in enumerate(blocks, start=1):
        song = _parse_block(block, block_index=i)
        if song:
            songs.append(song)

    return songs


def _parse_block(block: str, block_index: int) -> dict | None:
    """Parse a single song block. Returns None and logs a warning on failure."""
    # ── Extract footer fields ────────────────────────────────────────────────
    title_match   = re.search(r"^Title\s*:\s*(.+)$",           block, re.MULTILINE | re.IGNORECASE)
    bpm_match     = re.search(r"^BPM\s*:\s*(\d+)",             block, re.MULTILINE | re.IGNORECASE)
    metaphor_match= re.search(r"^Central Metaphor\s*:\s*(.+)$",block, re.MULTILINE | re.IGNORECASE)

    if not title_match or not bpm_match:
        print(f"[WARNING] Song block {block_index}: missing Title or BPM — skipping.")
        return None

    title   = title_match.group(1).strip().strip('"').strip("'")
    bpm     = int(bpm_match.group(1))
    central_metaphor = metaphor_match.group(1).strip() if metaphor_match else ""

    # ── Extract lyrics: everything with section labels up to the footer ──────
    # Split at the first footer line to isolate the lyrics portion
    footer_start = re.search(
        r"^(Title|BPM|Central Metaphor)\s*:",
        block,
        re.MULTILINE | re.IGNORECASE,
    )
    lyrics_text = block[: footer_start.start()].strip() if footer_start else block.strip()

    # Keep only lines that are section labels or lyric content
    lyrics_lines = []
    for line in lyrics_text.splitlines():
        stripped = line.strip()
        if stripped:
            lyrics_lines.append(stripped)
    lyrics = "\n".join(lyrics_lines)

    if not lyrics:
        print(f"[WARNING] Song block {block_index} ('{title}'): no lyrics content — skipping.")
        return None

    return {
        "title":           title,
        "genre":           GENRE,
        "theme":           THEME,
        "bpm":             bpm,
        "central_metaphor": central_metaphor,
        "lyrics":          lyrics,
    }


def _title_slug(title: str) -> str:
    """Convert a title to a filename-safe slug (lowercase, underscores, no special chars)."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)   # strip punctuation
    slug = re.sub(r"[\s-]+", "_", slug)    # spaces/hyphens → underscores
    slug = slug.strip("_")
    return slug[:60]  # cap length to keep filenames sane


def save_song(song: dict, index: int, output_dir: str) -> Path:
    """Write a song dict as a JSON file. Returns the path written."""
    filename = f"{index:03d}_{_title_slug(song['title'])}.json"
    filepath = Path(output_dir) / filename
    filepath.write_text(json.dumps(song, ensure_ascii=False, indent=2), encoding="utf-8")
    return filepath


def get_existing_titles(output_dir: str) -> set[str]:
    """Return a set of already-saved song titles (lowercase) from OUTPUT_DIR."""
    out = Path(output_dir)
    if not out.exists():
        return set()

    titles: set[str] = set()
    for json_file in out.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if "title" in data:
                titles.add(data["title"].lower())
        except (json.JSONDecodeError, OSError):
            pass  # corrupt file — ignore
    return titles


def main() -> None:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    prompt_template = load_prompt_template(PROMPT_PATH)

    collected: list[dict] = []          # unique songs gathered this run
    seen_titles: set[str] = get_existing_titles(OUTPUT_DIR)  # titles already on disk
    # Track titles added this run to catch intra-run duplicates
    run_titles: set[str] = set()

    # Starting index for filenames: continue after existing files
    existing_files = list(Path(OUTPUT_DIR).glob("*.json"))
    next_index = len(existing_files) + 1

    print(f"Starting generation: need {NUM_LYRICS} unique songs, batch size {BATCH_SIZE}.")
    print(f"Already saved: {len(seen_titles)} songs.")

    remaining = NUM_LYRICS
    while remaining > 0:
        batch_n = min(BATCH_SIZE, remaining)
        print(f"\nRequesting {batch_n} song(s) from DeepSeek API...")

        messages = build_messages(prompt_template, GENRE, THEME, batch_n)
        raw_text = call_deepseek(messages)

        songs = parse_songs(raw_text)
        print(f"Parsed {len(songs)} song(s) from response.")

        for song in songs:
            if remaining <= 0:
                break

            title_key = song["title"].lower()

            if title_key in seen_titles or title_key in run_titles:
                print(f"[WARNING] Duplicate title '{song['title']}' — skipping.")
                continue

            filepath = save_song(song, next_index, OUTPUT_DIR)
            print(f"Saved: {filepath.name}")

            seen_titles.add(title_key)
            run_titles.add(title_key)
            collected.append(song)
            next_index += 1
            remaining -= 1

    print(f"\nDone. Generated {len(collected)} new song(s) in '{OUTPUT_DIR}'.")


if __name__ == "__main__":
    main()
