"""Lyric Studio — GUI wrapper around Claude Code for generating song lyrics.

Requires: flet==0.28.2
"""

import platform
import re
import subprocess
import threading
from pathlib import Path

import flet as ft

from core.config import GENRES, MODELS, SUNO_MODELS, load_config, save_config
from core.engine import (
    generate_lyrics,
    install_claude_code,
    is_claude_installed,
    is_claude_logged_in,
    save_songs,
)

# ── Design tokens ─────────────────────────────────────────────────────
BG       = "#0F1117"
SURFACE  = "#1A1D27"
SURFACE2 = "#22263A"
ACCENT   = "#7C6FCD"
ACCENT2  = "#5B8DEF"
SUCCESS  = "#3DDC84"
TEXT     = "#E8EAF6"
DIM      = "#6B7280"
BORDER   = "#2E3347"


def card(content, padding=20, radius=14, color=SURFACE):
    return ft.Container(
        content=content,
        bgcolor=color,
        border_radius=radius,
        padding=padding,
        border=ft.border.all(1, BORDER),
    )


def main(page: ft.Page):
    page.title = "Lyric Studio"
    page.window_width = 860
    page.window_height = 740
    page.window_min_width = 700
    page.window_min_height = 600
    page.bgcolor = BG
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK

    config = load_config()
    generated_songs: list[dict] = []
    _stop_event: threading.Event | None = None
    _selected_song_idx: int = 0  # track which pill/song is active

    model_names = list(MODELS.keys())
    default_model_name = next(
        (n for n, mid in MODELS.items() if mid == config.get("model", "claude-opus-4-6")),
        model_names[0],
    )

    # ══════════════════════════════════════════════════════════════════
    # SETUP WIZARD
    # ══════════════════════════════════════════════════════════════════

    setup_status   = ft.Text("", size=14, color=DIM, text_align=ft.TextAlign.CENTER)
    setup_progress = ft.ProgressBar(visible=False, color=ACCENT, bgcolor=SURFACE2, height=4, width=360)
    action_col     = ft.Column([], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)

    def check_setup(e=None):
        setup_status.value = "Checking Claude Code..."
        action_col.controls = []
        page.update()

        if not is_claude_installed():
            setup_status.value = "Claude Code is not installed on this machine."
            action_col.controls = [
                ft.ElevatedButton(
                    "Install Claude Code",
                    icon=ft.Icons.DOWNLOAD,
                    bgcolor=ACCENT, color=TEXT,
                    on_click=do_install,
                ),
                ft.TextButton("Check again", on_click=check_setup),
            ]
            page.update()
            return

        setup_status.value = "Checking login..."
        page.update()

        if not is_claude_logged_in():
            setup_status.value = "Installed but not logged in."
            action_col.controls = [
                ft.ElevatedButton(
                    "Login to Claude",
                    icon=ft.Icons.LOGIN,
                    bgcolor=ACCENT2, color=TEXT,
                    on_click=do_login,
                ),
                ft.TextButton("Check again", on_click=check_setup),
            ]
            page.update()
            return

        setup_status.value = "All set!"
        action_col.controls = [
            ft.ElevatedButton(
                "Start Making Lyrics",
                icon=ft.Icons.MUSIC_NOTE,
                bgcolor=SUCCESS, color=ft.Colors.BLACK,
                on_click=go_to_main,
            ),
        ]
        page.update()

    def do_install(e):
        action_col.controls = []
        setup_progress.visible = True
        setup_status.value = "Installing Claude Code..."
        page.update()

        def _run():
            success, msg = install_claude_code()
            setup_progress.visible = False
            if success:
                check_setup()
            else:
                setup_status.value = f"Install failed: {msg}"
                action_col.controls = [
                    ft.ElevatedButton("Retry", icon=ft.Icons.REFRESH,
                                      bgcolor=ACCENT, color=TEXT, on_click=do_install),
                ]
                page.update()

        threading.Thread(target=_run, daemon=True).start()

    setup_log = ft.Column(
        [],
        spacing=4,
        visible=False,
        scroll=ft.ScrollMode.AUTO,
        height=120,
    )
    setup_log_card = ft.Container(
        content=setup_log,
        bgcolor="#0A0D14",
        border_radius=8,
        border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        visible=False,
        width=360,
    )

    def log_setup(msg: str, color: str = DIM):
        setup_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
        setup_log.visible = True
        setup_log_card.visible = True
        page.update()

    def do_login(e):
        action_col.controls = []
        setup_log.controls = []
        setup_log.visible = False
        setup_log_card.visible = False
        setup_status.value = "Opening browser for Claude login..."
        page.update()

        def _run():
            log_setup("Launching claude login…")
            try:
                result = subprocess.run(
                    ["claude", "login"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    log_setup("Login command completed.", SUCCESS)
                    if result.stdout.strip():
                        log_setup(result.stdout.strip()[:200])
                else:
                    log_setup(f"Exit code {result.returncode}", "#FF6B6B")
                    if result.stderr.strip():
                        log_setup(result.stderr.strip()[:200], "#FF6B6B")
            except subprocess.TimeoutExpired:
                log_setup("Timed out waiting for login.", "#FF6B6B")
            except Exception as ex:
                log_setup(f"Error: {ex}", "#FF6B6B")
            log_setup("Checking authentication status…")
            check_setup()

        threading.Thread(target=_run, daemon=True).start()

    def go_to_main(e):
        config["setup_complete"] = True
        save_config(config)
        show_main_view()

    setup_view = ft.Column(
        [
            ft.Container(height=40),
            ft.Text("♪", size=56, color=ACCENT, text_align=ft.TextAlign.CENTER),
            ft.Container(height=6),
            ft.Text("Lyric Studio", size=32, weight=ft.FontWeight.BOLD,
                    color=TEXT, text_align=ft.TextAlign.CENTER),
            ft.Text("AI-powered song lyrics in seconds", size=15, color=DIM,
                    text_align=ft.TextAlign.CENTER),
            ft.Container(height=28),
            card(
                ft.Column(
                    [setup_status, setup_progress, ft.Container(height=4),
                     action_col, setup_log_card],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                padding=32,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
    )

    # ══════════════════════════════════════════════════════════════════
    # MAIN VIEW
    # ══════════════════════════════════════════════════════════════════

    theme_input = ft.TextField(
        hint_text="What is the song about?  e.g. first love, road trip, losing a friend",
        border_color=BORDER,
        focused_border_color=ACCENT,
        bgcolor=SURFACE2,
        color=TEXT,
        hint_style=ft.TextStyle(color=DIM),
        border_radius=10,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        text_size=14,
        expand=True,
    )

    genre_dd = ft.Dropdown(
        label="Genre",
        label_style=ft.TextStyle(color=DIM, size=12),
        border_color=BORDER, focused_border_color=ACCENT,
        bgcolor=SURFACE2, color=TEXT, border_radius=10,
        options=[ft.dropdown.Option(g) for g in GENRES],
        value=config.get("default_genre", "Pop"),
        width=150, text_size=14,
    )

    model_dd = ft.Dropdown(
        label="Model",
        label_style=ft.TextStyle(color=DIM, size=12),
        border_color=BORDER, focused_border_color=ACCENT,
        bgcolor=SURFACE2, color=TEXT, border_radius=10,
        options=[ft.dropdown.Option(m) for m in model_names],
        value=default_model_name,
        width=150, text_size=14,
    )

    count_tf = ft.TextField(
        label="Songs",
        label_style=ft.TextStyle(color=DIM, size=12),
        value="1",
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=BORDER, focused_border_color=ACCENT,
        bgcolor=SURFACE2, color=TEXT, border_radius=10,
        width=75, text_size=14,
        text_align=ft.TextAlign.CENTER,
        content_padding=ft.padding.symmetric(horizontal=10, vertical=14),
    )

    progress_text = ft.Text("", size=13, color=DIM)
    progress_bar  = ft.ProgressBar(visible=False, color=ACCENT, bgcolor=SURFACE2, height=3)

    gen_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, height=110)
    gen_log_card = ft.Container(
        content=gen_log,
        bgcolor="#0A0D14",
        border_radius=8,
        border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        visible=False,
    )

    def log_gen(msg: str, color: str = DIM):
        gen_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
        gen_log_card.visible = True
        page.update()

    generate_btn = ft.ElevatedButton(
        "Generate Lyrics",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor=ACCENT, color=TEXT,
        height=46,
        on_click=lambda e: do_generate(e),
    )

    stop_btn = ft.ElevatedButton(
        "Stop",
        icon=ft.Icons.STOP_CIRCLE_OUTLINED,
        bgcolor="#C62828", color=TEXT,
        height=46,
        visible=False,
        on_click=lambda e: do_stop(e),
    )

    reset_btn = ft.OutlinedButton(
        "Reset",
        icon=ft.Icons.REFRESH,
        icon_color=DIM,
        visible=False,
        height=46,
        on_click=lambda e: do_reset(e),
    )

    pills_row       = ft.Row(
        visible=False, 
        spacing=8, 
        scroll=ft.ScrollMode.AUTO,
        auto_scroll=False,
    )
    # Container for tabs with scroll indicator
    pills_container = ft.Container(
        content=pills_row,
        visible=False,
        padding=ft.padding.symmetric(vertical=8, horizontal=4),
    )
    preview_col     = ft.Column(visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)
    open_folder_btn = ft.TextButton(
        "Open Output Folder",
        icon=ft.Icons.FOLDER_OPEN,
        visible=False,
        on_click=lambda e: do_open_folder(e),
    )

    # ── Suno integration UI ────────────────────────────────────────────────────
    _folder_songs: list[dict] = []
    _suno_checked: dict[int, bool] = {}

    suno_tags_input = ft.TextField(
        hint_text="Style tags  e.g. indie rock, guitar, emotional, female vocals",
        border_color=BORDER, focused_border_color="#7B68EE",
        bgcolor=SURFACE2, color=TEXT,
        hint_style=ft.TextStyle(color=DIM),
        border_radius=10,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=12),
        text_size=13, expand=True,
    )
    suno_model_dd = ft.Dropdown(
        label="Suno Model",
        label_style=ft.TextStyle(color=DIM, size=12),
        border_color=BORDER, focused_border_color="#7B68EE",
        bgcolor=SURFACE2, color=TEXT, border_radius=10,
        options=[ft.dropdown.Option(m) for m in SUNO_MODELS],
        value=next(
            (n for n, v in SUNO_MODELS.items() if v == config.get("suno_model", "chirp-v4")),
            list(SUNO_MODELS.keys())[0],
        ),
        width=170, text_size=13,
    )
    suno_send_btn = ft.ElevatedButton(
        "Generate Selected (0)",
        icon=ft.Icons.MUSIC_NOTE,
        bgcolor="#6A1B9A", color=TEXT,
        height=42, disabled=True,
        on_click=lambda e: do_generate_suno(e),
    )
    suno_status_text = ft.Text("", size=12, color=DIM)
    suno_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, height=90)
    suno_log_card = ft.Container(
        content=suno_log,
        bgcolor="#0A0D14", border_radius=8,
        border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        visible=False,
    )
    suno_song_list = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO, height=180)

    suno_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.HEADPHONES, color="#7B68EE", size=16),
                        ft.Text("Suno Music Generation", size=13, color=DIM,
                                weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        suno_status_text,
                        ft.IconButton(
                            ft.Icons.REFRESH, icon_color=DIM, icon_size=16,
                            tooltip="Reload songs from output folder",
                            on_click=lambda e: _reload_song_list(),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(height=4),
                suno_song_list,
                ft.Container(height=6),
                ft.Row(
                    [suno_tags_input, suno_model_dd, suno_send_btn],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                suno_log_card,
            ],
            spacing=6,
        ),
        visible=False,
        bgcolor=SURFACE, border_radius=14,
        padding=16,
        border=ft.border.all(1, BORDER),
    )

    def log_suno(msg: str, color: str = DIM):
        suno_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
        suno_log_card.visible = True
        page.update()

    def _parse_song_file(path: Path) -> dict | None:
        try:
            text = path.read_text(encoding="utf-8")
            footer = re.search(r"^Title:", text, re.MULTILINE)
            lyrics = text[:footer.start()].strip() if footer else text.strip()
            title_m  = re.search(r"^Title:\s*(.+)$",  text, re.MULTILINE)
            genre_m  = re.search(r"^Genre:\s*(.+)$",  text, re.MULTILINE)
            bpm_m    = re.search(r"^BPM:\s*(\d+)$",   text, re.MULTILINE)
            theme_m  = re.search(r"^Theme:\s*(.+)$",  text, re.MULTILINE)
            return {
                "title":  title_m.group(1).strip() if title_m else path.stem,
                "genre":  genre_m.group(1).strip() if genre_m else "",
                "bpm":    int(bpm_m.group(1)) if bpm_m else 0,
                "theme":  theme_m.group(1).strip() if theme_m else "",
                "lyrics": lyrics,
                "_file":  str(path),
            }
        except Exception:
            return None

    def _update_send_btn():
        count = sum(1 for v in _suno_checked.values() if v)
        suno_send_btn.text = f"Generate Selected ({count})"
        suno_send_btn.disabled = count == 0
        page.update()

    def _on_checkbox_change(idx: int, val: bool):
        _suno_checked[idx] = val
        _update_send_btn()

    def _reload_song_list():
        nonlocal _folder_songs
        folder = config.get("output_folder", "")
        _folder_songs = []
        _suno_checked.clear()
        if folder:
            for p in sorted(Path(folder).glob("*.txt")):
                song = _parse_song_file(p)
                if song:
                    _folder_songs.append(song)

        suno_song_list.controls = []
        if not _folder_songs:
            suno_song_list.controls.append(
                ft.Text("No .txt songs found in output folder.", size=12, color=DIM)
            )
        else:
            for i, song in enumerate(_folder_songs):
                _suno_checked[i] = False
                idx = i
                row = ft.Row(
                    [
                        ft.Checkbox(
                            value=False,
                            active_color="#7B68EE",
                            on_change=lambda e, i=idx: _on_checkbox_change(i, e.control.value),
                        ),
                        ft.Column(
                            [
                                ft.Text(song["title"], size=13, color=TEXT,
                                        weight=ft.FontWeight.W_500, no_wrap=True),
                                ft.Text(song["genre"] or Path(song["_file"]).name,
                                        size=11, color=DIM),
                            ],
                            spacing=1, expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                suno_song_list.controls.append(
                    ft.Container(
                        content=row,
                        bgcolor=SURFACE2, border_radius=8,
                        padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    )
                )
        _update_send_btn()

    def _refresh_suno_section():
        has_cookie = bool(config.get("suno_cookie", ""))
        suno_section.visible = has_cookie
        if has_cookie:
            _reload_song_list()
        page.update()

    def show_song(index: int):
        nonlocal _selected_song_idx
        if index >= len(generated_songs):
            return
        _selected_song_idx = index
        song = generated_songs[index]
        saved = preview_col.data or []
        saved_name = saved[index].name if index < len(saved) else ""

        for i, pill in enumerate(pills_row.controls):
            pill.bgcolor = ACCENT if i == index else SURFACE2
            pill.style = ft.ButtonStyle(color=TEXT if i == index else DIM)

        meta = []
        if song["bpm"]:
            meta.append(f"♩ {song['bpm']} BPM")
        meta.append(song["genre"])

        preview_col.controls = [
            card(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(song["title"], size=19,
                                                weight=ft.FontWeight.BOLD, color=TEXT),
                                        ft.Text("  ·  ".join(meta), size=12, color=DIM),
                                    ],
                                    spacing=2, expand=True,
                                ),
                                ft.Text(f"✓  {saved_name}", size=11, color=SUCCESS)
                                if saved_name else ft.Container(),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(color=BORDER, height=20),
                        ft.Text(song["lyrics"], size=13, color=TEXT, selectable=True),
                        *(
                            [
                                ft.Divider(color=BORDER, height=20),
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, color=ACCENT, size=14),
                                        ft.Text(song["central_metaphor"], size=12,
                                                color=DIM, italic=True, expand=True),
                                    ],
                                    spacing=8,
                                ),
                            ]
                            if song.get("central_metaphor") else []
                        ),
                    ],
                    spacing=0,
                ),
                padding=24,
            )
        ]
        page.update()

    def do_stop(e):
        nonlocal _stop_event
        if _stop_event:
            _stop_event.set()
        stop_btn.disabled = True
        stop_btn.text = "Stopping…"
        page.update()

    def do_generate(e):
        nonlocal generated_songs, _stop_event

        theme = theme_input.value.strip()
        if not theme:
            theme_input.error_text = "Please enter a theme"
            page.update()
            return
        theme_input.error_text = None

        try:
            count = int(count_tf.value)
            if not 1 <= count <= 20:
                raise ValueError
        except ValueError:
            count_tf.error_text = "1–20"
            page.update()
            return
        count_tf.error_text = None

        _stop_event = threading.Event()
        generate_btn.visible    = False
        stop_btn.visible        = True
        stop_btn.disabled       = False
        stop_btn.text           = "Stop"
        reset_btn.visible       = False
        progress_bar.visible    = True
        pills_container.visible = False
        preview_col.visible     = False
        open_folder_btn.visible = False
        gen_log.controls        = []
        gen_log_card.visible    = False
        progress_text.value     = "Starting…"
        page.update()

        def _run():
            nonlocal generated_songs

            model_label = model_dd.value
            genre_label = genre_dd.value

            log_gen(f"Model: {model_label}  |  Genre: {genre_label}  |  Songs: {count}")
            log_gen(f"Theme: \"{theme}\"")

            def truncate_title(title: str, max_len: int = 25) -> str:
                """Truncate song title if too long."""
                return title if len(title) <= max_len else title[:max_len-1] + "…"

            def on_progress(cur, total, status):
                progress_text.value = status
                progress_bar.value  = cur / total if total else None
                is_limit = "LIMIT HIT" in status or "Wait for your usage" in status
                is_error = status.startswith("[") and "Error" in status
                color = "#FF4444" if is_limit else ("#FF9944" if is_error else DIM)
                log_gen(status, color=color)
                page.update()

            log_gen("Calling Claude Code CLI…")
            try:
                songs = generate_lyrics(
                    genre=genre_label,
                    theme=theme,
                    model=MODELS[model_label],
                    num_songs=count,
                    on_progress=on_progress,
                    stop_event=_stop_event,
                )
            except Exception as exc:
                log_gen(f"Fatal error: {exc}", "#FF6B6B")
                progress_text.value = "Generation failed — see log above."
                progress_bar.visible  = False
                stop_btn.visible      = False
                generate_btn.visible  = True
                page.update()
                return
            generated_songs = songs

            if songs:
                log_gen(f"Parsing complete — {len(songs)} song(s) received.", SUCCESS)
                output_dir = config.get("output_folder", "")
                saved = save_songs(songs, output_dir)
                preview_col.data = saved
                for i, (song, path) in enumerate(zip(songs, saved)):
                    log_gen(f"Saved: {path.name}  [{song['title']}]", SUCCESS)

                pills_row.controls = [
                    ft.ElevatedButton(
                        truncate_title(song["title"]),
                        bgcolor=ACCENT if i == 0 else SURFACE2,
                        color=TEXT,
                        tooltip=song["title"],  # Show full title on hover
                        on_click=lambda e, idx=i: show_song(idx),
                    )
                    for i, song in enumerate(songs)
                ]
                pills_row.visible       = True
                pills_container.visible = True
                preview_col.visible     = True
                open_folder_btn.visible = True
                reset_btn.visible       = True
                show_song(0)
                progress_text.value = f"{len(songs)} song{'s' if len(songs) > 1 else ''} generated"
                _refresh_suno_section()
            else:
                log_gen("No songs returned — check Claude Code login and connection.", "#FF6B6B")
                progress_text.value = "No songs generated — check Claude Code connection."

            progress_bar.visible  = False
            stop_btn.visible      = False
            generate_btn.visible  = True
            page.update()

        threading.Thread(target=_run, daemon=True).start()

    def do_generate_suno(e):
        selected = [_folder_songs[i] for i, v in _suno_checked.items() if v]
        if not selected:
            return
        tags     = suno_tags_input.value.strip()
        model_id = SUNO_MODELS.get(suno_model_dd.value, "chirp-v4")
        cookie   = config.get("suno_cookie", "")
        if not cookie:
            log_suno("No Suno account connected — go to Settings.", "#FF6B6B")
            return

        suno_send_btn.disabled = True
        suno_send_btn.text = "Generating…"
        suno_log.controls = []
        suno_log_card.visible = False
        suno_status_text.value = f"Starting — {len(selected)} song(s)…"
        page.update()

        def _run():
            try:
                from core.suno_client import SunoClient
                client = SunoClient(cookie)

                for song in selected:
                    song_tags = tags or song.get("genre", "pop")
                    log_suno(f"Submitting \"{song['title']}\" | {song_tags}")
                    clips = client.generate(
                        lyrics=song["lyrics"],
                        tags=song_tags,
                        title=song["title"],
                        model=model_id,
                    )
                    log_suno(f"{len(clips)} clip(s) rendering…")

                    def on_poll(m):
                        suno_status_text.value = m
                        log_suno(m)

                    paths = client.wait_and_download(
                        clips,
                        output_dir=config.get("output_folder", ""),
                        song_title=song["title"],
                        on_status=on_poll,
                    )
                    if paths:
                        for p in paths:
                            log_suno(f"Saved: {Path(p).name}", SUCCESS)
                    else:
                        log_suno(f"No audio for \"{song['title']}\"", "#FF6B6B")

                suno_status_text.value = "Done!"
                log_suno("All done — check your output folder.", SUCCESS)

            except Exception as exc:
                log_suno(f"Error: {exc}", "#FF6B6B")
                suno_status_text.value = "Suno error — see log."
            finally:
                _update_send_btn()
                page.update()

        threading.Thread(target=_run, daemon=True).start()

    def do_reset(e):
        nonlocal generated_songs
        generated_songs = []
        pills_row.controls = []
        pills_row.visible = False
        pills_container.visible = False
        preview_col.controls = []
        preview_col.visible = False
        preview_col.data = None
        open_folder_btn.visible = False
        reset_btn.visible = False
        gen_log.controls = []
        gen_log_card.visible = False
        progress_text.value = ""
        progress_bar.visible = False
        theme_input.value = ""
        suno_section.visible = False
        suno_log.controls = []
        suno_log_card.visible = False
        suno_status_text.value = ""
        suno_tags_input.value = ""
        suno_send_btn.disabled = True
        page.update()

    def do_open_folder(e):
        folder = config.get("output_folder", "")
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", folder])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    input_card = card(
        ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.EDIT_NOTE, color=ACCENT, size=18),
                     ft.Text("New Song", size=13, color=DIM, weight=ft.FontWeight.W_600)],
                    spacing=8,
                ),
                ft.Container(height=10),
                ft.Row([theme_input]),
                ft.Container(height=10),
                ft.Row(
                    [genre_dd, model_dd, count_tf, ft.Container(expand=True), reset_btn, stop_btn, generate_btn],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
            ],
            spacing=0,
        ),
        padding=20,
    )

    main_view = ft.Column(
        [
            # Top bar
            ft.Container(
                content=ft.Row(
                    [
                        ft.Row(
                            [ft.Text("♪", size=22, color=ACCENT),
                             ft.Text("Lyric Studio", size=20,
                                     weight=ft.FontWeight.BOLD, color=TEXT)],
                            spacing=8,
                        ),
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.SETTINGS_OUTLINED,
                            icon_color=DIM,
                            tooltip="Settings",
                            on_click=lambda e: show_settings_view(),
                        ),
                    ],
                ),
                bgcolor=SURFACE,
                padding=ft.padding.symmetric(horizontal=24, vertical=14),
                border=ft.border.only(bottom=ft.border.BorderSide(1, BORDER)),
            ),
            # Body
            ft.Container(
                content=ft.Column(
                    [
                        input_card,
                        ft.Column(
                            [
                                progress_bar,
                                ft.Row([progress_text],
                                       alignment=ft.MainAxisAlignment.CENTER),
                                gen_log_card,
                            ],
                            spacing=6,
                        ),
                        pills_container,
                        ft.Container(content=preview_col, expand=True),
                        ft.Row([open_folder_btn], alignment=ft.MainAxisAlignment.END),
                        suno_section,
                        ft.Container(height=16),
                    ],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=14,
                ),
                expand=True,
                padding=ft.padding.symmetric(horizontal=24, vertical=20),
            ),
        ],
        expand=True,
        spacing=0,
    )

    # ══════════════════════════════════════════════════════════════════
    # SETTINGS VIEW  (rebuilt fresh every time to avoid control-reuse)
    # ══════════════════════════════════════════════════════════════════

    def build_settings_view():
        s_model = ft.Dropdown(
            label="Default Model",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            options=[ft.dropdown.Option(m) for m in model_names],
            value=default_model_name, width=280, text_size=14,
        )
        s_genre = ft.Dropdown(
            label="Default Genre",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            options=[ft.dropdown.Option(g) for g in GENRES],
            value=config.get("default_genre", "Pop"), width=280, text_size=14,
        )
        s_output = ft.TextField(
            label="Output Folder",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            value=config.get("output_folder", ""),
            expand=True, text_size=13,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        )

        folder_picker = ft.FilePicker(
            on_result=lambda e: (
                setattr(s_output, "value", e.path or s_output.value),
                page.update(),
            )
        )
        page.overlay.append(folder_picker)
        page.update()

        # ── Suno settings ──────────────────────────────────────────────────────
        _tf = dict(
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color="#7B68EE",
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            expand=True, text_size=13,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        )

        s_suno_google_email = ft.TextField(
            label="Google Email",
            value=config.get("suno_email", ""),
            **_tf,
        )
        s_suno_google_password = ft.TextField(
            label="Google Password",
            value=config.get("suno_password", ""),
            password=True, can_reveal_password=True,
            **_tf,
        )
        s_suno_totp = ft.TextField(
            label="Google Authenticator 2FA Secret",
            value=config.get("suno_totp_secret", ""),
            password=True, can_reveal_password=True,
            **_tf,
        )
        s_suno_status = ft.Text(
            "● Connected" if config.get("suno_cookie") else "○ Not connected",
            size=12,
            color=SUCCESS if config.get("suno_cookie") else DIM,
        )
        s_suno_connect_btn = ft.ElevatedButton(
            "Connect via Google",
            icon=ft.Icons.LINK,
            bgcolor="#6A1B9A", color=TEXT,
            height=42,
        )
        s_suno_disconnect_btn = ft.TextButton(
            "Disconnect",
            icon=ft.Icons.LOGOUT,
            style=ft.ButtonStyle(color="#FF6B6B"),
            visible=bool(config.get("suno_cookie")),
        )
        s_suno_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, height=80)
        s_suno_log_card = ft.Container(
            content=s_suno_log,
            bgcolor="#0A0D14",
            border_radius=8,
            border=ft.border.all(1, BORDER),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            visible=False,
        )
        s_suno_model = ft.Dropdown(
            label="Suno Default Model",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color="#7B68EE",
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            options=[ft.dropdown.Option(m) for m in SUNO_MODELS],
            value=next(
                (n for n, v in SUNO_MODELS.items() if v == config.get("suno_model", "chirp-v4")),
                list(SUNO_MODELS.keys())[0],
            ),
            width=220, text_size=13,
        )

        def log_suno_connect(msg: str, color: str = DIM):
            s_suno_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
            s_suno_log_card.visible = True
            page.update()

        def do_connect_suno(e):
            email    = s_suno_google_email.value.strip()
            password = s_suno_google_password.value.strip()
            totp     = s_suno_totp.value.strip()
            if not email or not password or not totp:
                log_suno_connect("Email, password and 2FA secret are all required.", "#FF9944")
                return

            # Save credentials immediately so they persist across app restarts
            config["suno_email"]       = email
            config["suno_password"]    = password
            config["suno_totp_secret"] = totp
            save_config(config)

            s_suno_connect_btn.disabled = True
            s_suno_connect_btn.text = "Connecting…"
            s_suno_log.controls = []
            s_suno_log_card.visible = False
            s_suno_status.value = "Connecting…"
            s_suno_status.color = DIM
            page.update()

            def _run():
                import asyncio
                from core.suno_auth import login_with_google
                from core.suno_client import validate_cookie

                loop = asyncio.new_event_loop()
                try:
                    cookie = loop.run_until_complete(
                        login_with_google(
                            email, password,
                            totp_secret=totp or None,
                            on_status=lambda m: log_suno_connect(m),
                        )
                    )
                    ok, msg = validate_cookie(cookie)
                    if ok:
                        config["suno_email"]       = email
                        config["suno_password"]    = password
                        config["suno_totp_secret"] = totp
                        config["suno_cookie"]      = cookie
                        save_config(config)
                        s_suno_status.value = f"● Connected — {msg}"
                        s_suno_status.color = SUCCESS
                        s_suno_disconnect_btn.visible = True
                        log_suno_connect(f"Connected! {msg}", SUCCESS)
                        _refresh_suno_section()
                    else:
                        s_suno_status.value = "Connection failed"
                        s_suno_status.color = "#FF6B6B"
                        log_suno_connect(f"Validation failed: {msg}", "#FF6B6B")
                except Exception as exc:
                    s_suno_status.value = "○ Not connected"
                    s_suno_status.color = DIM
                    log_suno_connect(f"Error: {exc}", "#FF6B6B")
                finally:
                    loop.close()
                    s_suno_connect_btn.disabled = False
                    s_suno_connect_btn.text = "Connect via Google"
                    page.update()

            threading.Thread(target=_run, daemon=True).start()

        def do_disconnect(e):
            config["suno_email"]    = ""
            config["suno_password"] = ""
            config["suno_cookie"]   = ""
            save_config(config)
            s_suno_status.value = "○ Not connected"
            s_suno_status.color = DIM
            s_suno_disconnect_btn.visible = False
            s_suno_google_email.value = ""
            s_suno_google_password.value = ""
            s_suno_totp.value = ""
            s_suno_log.controls = []
            s_suno_log_card.visible = False
            _refresh_suno_section()
            page.update()

        s_suno_connect_btn.on_click    = do_connect_suno
        s_suno_disconnect_btn.on_click = do_disconnect

        # ── Save handler ───────────────────────────────────────────────────────
        def on_save(e):
            config["model"]         = MODELS[s_model.value]
            config["default_genre"] = s_genre.value
            config["output_folder"] = s_output.value
            config["suno_model"]    = SUNO_MODELS[s_suno_model.value]
            save_config(config)
            model_dd.value  = s_model.value
            genre_dd.value  = s_genre.value
            page.overlay.remove(folder_picker)
            show_main_view()

        def on_pick(e):
            folder_picker.get_directory_path(dialog_title="Choose output folder")

        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.IconButton(
                                ft.Icons.ARROW_BACK_IOS_NEW,
                                icon_color=DIM,
                                on_click=lambda e: (
                                    page.overlay.remove(folder_picker),
                                    show_main_view(),
                                ),
                            ),
                            ft.Text("Settings", size=20,
                                    weight=ft.FontWeight.BOLD, color=TEXT),
                        ],
                        spacing=4,
                    ),
                    bgcolor=SURFACE,
                    padding=ft.padding.symmetric(horizontal=24, vertical=14),
                    border=ft.border.only(bottom=ft.border.BorderSide(1, BORDER)),
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            # Claude preferences
                            card(
                                ft.Column(
                                    [
                                        ft.Text("Preferences", size=13, color=DIM,
                                                weight=ft.FontWeight.W_600),
                                        ft.Container(height=14),
                                        s_model,
                                        s_genre,
                                        ft.Row(
                                            [
                                                s_output,
                                                ft.IconButton(
                                                    ft.Icons.FOLDER_OPEN,
                                                    icon_color=ACCENT,
                                                    tooltip="Choose folder",
                                                    on_click=on_pick,
                                                ),
                                            ],
                                            spacing=8,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                    ],
                                    spacing=14,
                                ),
                                padding=24,
                            ),
                            ft.Container(height=12),
                            # Suno integration
                            card(
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                ft.Icon(ft.Icons.HEADPHONES,
                                                        color="#7B68EE", size=16),
                                                ft.Text("Suno Integration", size=13,
                                                        color=DIM, weight=ft.FontWeight.W_600),
                                                ft.Container(expand=True),
                                                s_suno_status,
                                                s_suno_disconnect_btn,
                                            ],
                                            spacing=8,
                                        ),
                                        ft.Container(height=8),
                                        ft.Text(
                                            "Sign in with your Google account linked to Suno. "
                                            "Enter your Google email, password, and the secret key "
                                            "from your Google Authenticator app. All three fields are required.",
                                            size=11, color=DIM,
                                        ),
                                        ft.Container(height=6),
                                        s_suno_google_email,
                                        s_suno_google_password,
                                        s_suno_totp,
                                        ft.Row(
                                            [s_suno_connect_btn],
                                            alignment=ft.MainAxisAlignment.START,
                                        ),
                                        ft.Container(height=4),
                                        s_suno_model,
                                        s_suno_log_card,
                                    ],
                                    spacing=8,
                                ),
                                padding=24,
                            ),
                            ft.Container(height=12),
                            ft.ElevatedButton(
                                "Save Settings",
                                icon=ft.Icons.CHECK,
                                bgcolor=SUCCESS, color=ft.Colors.BLACK,
                                on_click=on_save,
                            ),
                        ],
                        spacing=0,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=24, vertical=20),
                ),
            ],
            expand=True,
            spacing=0,
        )

    # ══════════════════════════════════════════════════════════════════
    # NAVIGATION
    # ══════════════════════════════════════════════════════════════════

    def show_setup_view():
        page.controls.clear()
        page.add(
            ft.Container(
                content=setup_view,
                expand=True,
                alignment=ft.alignment.center,
                padding=ft.padding.symmetric(horizontal=60),
            )
        )
        page.update()
        threading.Thread(target=check_setup, daemon=True).start()

    def show_main_view():
        page.controls.clear()
        page.add(main_view)
        page.update()

    def show_settings_view():
        page.controls.clear()
        page.add(build_settings_view())
        page.update()

    # ── Start ──────────────────────────────────────────────────────────
    if config.get("setup_complete") and is_claude_installed():
        show_main_view()
    else:
        show_setup_view()


if __name__ == "__main__":
    ft.app(target=main)
