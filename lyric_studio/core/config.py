"""Settings management for Lyric Studio."""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "model": "claude-opus-4-6",
    "output_folder": "",
    "default_genre": "Pop",
    "file_naming": "numbered",
    "setup_complete": False,
    # Suno integration
    "suno_email": "",
    "suno_password": "",
    "suno_totp_secret": "",     # Google Authenticator TOTP secret (optional)
    "suno_cookie": "",          # serialized cookie string from nodriver login
    "suno_model": "chirp-v4",  # default Suno model
}

MODELS = {
    "Opus 4.6": "claude-opus-4-6",
    "Sonnet 4.6": "claude-sonnet-4-6",
}

GENRES = ["Pop", "Rock", "Country", "R&B", "Folk", "Indie", "Hip-Hop"]

SUNO_MODELS = {
    "V4 (Recommended)": "chirp-v4",
    "V4.5 (8-min max)": "chirp-v4-5",
    "V3.5 (Fast)":      "chirp-v3-5",
}

CONFIG_DIR = Path.home() / ".lyric_studio"
CONFIG_FILE = CONFIG_DIR / "settings.json"


def get_default_output_folder() -> str:
    return str(Path.home() / "LyricStudio" / "output")


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for key, val in DEFAULT_CONFIG.items():
                config.setdefault(key, val)
            if not config["output_folder"]:
                config["output_folder"] = get_default_output_folder()
            return config
        except (json.JSONDecodeError, OSError):
            pass

    config = DEFAULT_CONFIG.copy()
    config["output_folder"] = get_default_output_folder()
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
