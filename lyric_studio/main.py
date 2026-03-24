"""Lyric Studio — GUI wrapper around Claude Code for generating song lyrics.

Requires: flet==0.28.2
"""

import platform
import re
import subprocess
import threading
import time
from pathlib import Path

import flet as ft

from core.config import MODELS, SUNO_MODELS, load_config, save_config
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
SUNO_CLR = "#7B68EE"


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
    _selected_song_idx: int = 0

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
        auto_scroll=True,
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
    # SHARED: Parse song file from disk
    # ══════════════════════════════════════════════════════════════════

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

    def _truncate(title: str, max_len: int = 25) -> str:
        return title if len(title) <= max_len else title[:max_len-1] + "…"

    # ══════════════════════════════════════════════════════════════════
    # LYRICS TAB
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

    genre_dd = ft.TextField(
        label="Genre",
        label_style=ft.TextStyle(color=DIM, size=12),
        border_color=BORDER, focused_border_color=ACCENT,
        bgcolor=SURFACE2, color=TEXT, border_radius=10,
        value=config.get("default_genre", "Pop"),
        width=150, text_size=14,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
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

    gen_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, auto_scroll=True, height=110)
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

    pills_row       = ft.Row(visible=False, spacing=8, scroll=ft.ScrollMode.AUTO, auto_scroll=False)
    pills_container = ft.Container(
        content=pills_row, visible=False,
        padding=ft.padding.symmetric(vertical=8, horizontal=4),
    )
    preview_col     = ft.Column(visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)
    open_folder_btn = ft.TextButton(
        "Open Lyrics Folder",
        icon=ft.Icons.FOLDER_OPEN,
        visible=False,
        on_click=lambda e: _open_folder(config.get("output_folder", "")),
    )

    # ── Saved lyrics list (in Lyrics tab) ─────────────────────────────
    _saved_lyrics: list[dict] = []
    _saved_lyrics_checked: dict[int, bool] = {}
    _saved_lyrics_cbs: list[ft.Checkbox] = []

    saved_lyrics_list = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO, height=200)

    def _update_lyrics_delete_btn():
        count = sum(1 for v in _saved_lyrics_checked.values() if v)
        lyrics_delete_btn.text = f"Delete Selected ({count})"
        lyrics_delete_btn.disabled = count == 0
        page.update()

    def _on_lyrics_select_all(e):
        checked = e.control.value
        for i, cb in enumerate(_saved_lyrics_cbs):
            cb.value = checked
            _saved_lyrics_checked[i] = checked
        _update_lyrics_delete_btn()

    def _on_lyrics_cb_change(idx: int, val: bool):
        _saved_lyrics_checked[idx] = val
        if not val and _lyrics_select_all_cb.value:
            _lyrics_select_all_cb.value = False
        elif val and all(_saved_lyrics_checked.get(i, False) for i in range(len(_saved_lyrics_cbs))):
            _lyrics_select_all_cb.value = True
        _update_lyrics_delete_btn()

    _lyrics_select_all_cb = ft.Checkbox(
        label="Select All",
        label_style=ft.TextStyle(size=12, color=DIM),
        value=False, active_color=ACCENT,
        on_change=_on_lyrics_select_all,
    )

    lyrics_delete_btn = ft.ElevatedButton(
        "Delete Selected (0)",
        icon=ft.Icons.DELETE_OUTLINE,
        bgcolor="#C62828", color=TEXT,
        height=36, disabled=True,
        on_click=lambda e: _do_delete_selected_lyrics(),
    )

    def _do_delete_selected_lyrics():
        to_delete = [_saved_lyrics[i] for i, v in _saved_lyrics_checked.items() if v]
        for song in to_delete:
            try:
                Path(song["_file"]).unlink()
            except Exception:
                pass
        _reload_saved_lyrics()

    def _reload_saved_lyrics():
        nonlocal _saved_lyrics
        _saved_lyrics = []
        _saved_lyrics_checked.clear()
        _saved_lyrics_cbs.clear()
        _lyrics_select_all_cb.value = False

        folder = config.get("output_folder", "")
        if folder:
            for p in sorted(Path(folder).rglob("*.txt")):
                song = _parse_song_file(p)
                if song:
                    _saved_lyrics.append(song)

        saved_lyrics_list.controls = []
        if not _saved_lyrics:
            saved_lyrics_list.controls.append(
                ft.Text("No saved lyrics yet.", size=12, color=DIM)
            )
            saved_lyrics_section.visible = False
        else:
            saved_lyrics_section.visible = True
            saved_lyrics_list.controls.append(_lyrics_select_all_cb)
            for i, song in enumerate(_saved_lyrics):
                _saved_lyrics_checked[i] = False
                idx = i
                cb = ft.Checkbox(
                    value=False, active_color=ACCENT,
                    on_change=lambda e, i=idx: _on_lyrics_cb_change(i, e.control.value),
                )
                _saved_lyrics_cbs.append(cb)

                def _delete_one_lyric(e, file_path=song["_file"]):
                    try:
                        Path(file_path).unlink()
                    except Exception:
                        pass
                    _reload_saved_lyrics()

                subtitle = song["genre"]
                if song["theme"]:
                    subtitle += f" · {song['theme']}" if subtitle else song["theme"]

                row = ft.Row(
                    [
                        cb,
                        ft.Column(
                            [
                                ft.Text(song["title"], size=13, color=TEXT,
                                        weight=ft.FontWeight.W_500, no_wrap=True),
                                ft.Text(subtitle or Path(song["_file"]).name,
                                        size=11, color=DIM, no_wrap=True),
                            ],
                            spacing=1, expand=True,
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_color="#FF6B6B", icon_size=16,
                            tooltip="Delete", on_click=_delete_one_lyric,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                saved_lyrics_list.controls.append(
                    ft.Container(
                        content=row,
                        bgcolor=SURFACE2, border_radius=8,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    )
                )
        _update_lyrics_delete_btn()
        page.update()

    saved_lyrics_section = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LIBRARY_MUSIC, color=ACCENT, size=16),
                        ft.Text("Saved Lyrics", size=13, color=DIM, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.REFRESH, icon_color=DIM, icon_size=16,
                            tooltip="Reload", on_click=lambda e: _reload_saved_lyrics(),
                        ),
                    ],
                    spacing=8,
                ),
                saved_lyrics_list,
                ft.Row([lyrics_delete_btn], spacing=10),
            ],
            spacing=6,
        ),
        visible=False,
        bgcolor=SURFACE, border_radius=14,
        padding=16,
        border=ft.border.all(1, BORDER),
    )

    # ── Generation preview delete ─────────────────────────────────────
    def do_delete_song(index: int):
        nonlocal generated_songs, _selected_song_idx
        if index >= len(generated_songs):
            return
        saved = preview_col.data or []
        if index < len(saved):
            try:
                if saved[index].exists():
                    saved[index].unlink()
                    log_gen(f"Deleted: {saved[index].name}", DIM)
            except Exception:
                pass
            saved.pop(index)
            preview_col.data = saved
        generated_songs.pop(index)
        if not generated_songs:
            pills_row.controls = []
            pills_row.visible = False
            pills_container.visible = False
            preview_col.controls = []
            preview_col.visible = False
            open_folder_btn.visible = False
            reset_btn.visible = False
            progress_text.value = "All songs deleted"
            _reload_saved_lyrics()
            page.update()
            return
        new_idx = min(index, len(generated_songs) - 1)
        pills_row.controls = [
            ft.ElevatedButton(
                _truncate(song["title"]),
                bgcolor=ACCENT if i == new_idx else SURFACE2,
                color=TEXT, tooltip=song["title"],
                on_click=lambda e, idx=i: show_song(idx),
            )
            for i, song in enumerate(generated_songs)
        ]
        progress_text.value = f"{len(generated_songs)} song{'s' if len(generated_songs) > 1 else ''} remaining"
        show_song(new_idx)
        _reload_saved_lyrics()

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
                                ft.Row(
                                    [
                                        ft.Text(f"✓  {saved_name}", size=11, color=SUCCESS)
                                        if saved_name else ft.Container(),
                                        ft.IconButton(
                                            ft.Icons.DELETE_OUTLINE,
                                            icon_color="#FF6B6B", icon_size=18,
                                            tooltip="Delete this song",
                                            on_click=lambda e, idx=index: do_delete_song(idx),
                                        ),
                                    ],
                                    spacing=4,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
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
                    genre=genre_label, theme=theme,
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
                        _truncate(song["title"]),
                        bgcolor=ACCENT if i == 0 else SURFACE2,
                        color=TEXT, tooltip=song["title"],
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
                _reload_saved_lyrics()
            else:
                log_gen("No songs returned — check Claude Code login and connection.", "#FF6B6B")
                progress_text.value = "No songs generated — check Claude Code connection."
            progress_bar.visible  = False
            stop_btn.visible      = False
            generate_btn.visible  = True
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
        page.update()

    def _open_folder(folder: str):
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

    lyrics_tab_content = ft.Column(
        [
            input_card,
            ft.Column(
                [
                    progress_bar,
                    ft.Row([progress_text], alignment=ft.MainAxisAlignment.CENTER),
                    gen_log_card,
                ],
                spacing=6,
            ),
            pills_container,
            ft.Container(content=preview_col, expand=True),
            ft.Row([open_folder_btn], alignment=ft.MainAxisAlignment.END),
            saved_lyrics_section,
            ft.Container(height=16),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )

    # ══════════════════════════════════════════════════════════════════
    # SONGS TAB
    # ══════════════════════════════════════════════════════════════════

    # ── MP3 song list ─────────────────────────────────────────────────
    _mp3_songs: list[dict] = []
    _mp3_checked: dict[int, bool] = {}
    _mp3_cbs: list[ft.Checkbox] = []

    mp3_song_list = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO, height=200)

    def _update_mp3_delete_btn():
        count = sum(1 for v in _mp3_checked.values() if v)
        mp3_delete_btn.text = f"Delete Selected ({count})"
        mp3_delete_btn.disabled = count == 0
        page.update()

    def _on_mp3_select_all(e):
        checked = e.control.value
        for i, cb in enumerate(_mp3_cbs):
            cb.value = checked
            _mp3_checked[i] = checked
        _update_mp3_delete_btn()

    def _on_mp3_cb_change(idx: int, val: bool):
        _mp3_checked[idx] = val
        if not val and _mp3_select_all_cb.value:
            _mp3_select_all_cb.value = False
        elif val and all(_mp3_checked.get(i, False) for i in range(len(_mp3_cbs))):
            _mp3_select_all_cb.value = True
        _update_mp3_delete_btn()

    _mp3_select_all_cb = ft.Checkbox(
        label="Select All",
        label_style=ft.TextStyle(size=12, color=DIM),
        value=False, active_color=SUNO_CLR,
        on_change=_on_mp3_select_all,
    )

    mp3_delete_btn = ft.ElevatedButton(
        "Delete Selected (0)",
        icon=ft.Icons.DELETE_OUTLINE,
        bgcolor="#C62828", color=TEXT,
        height=36, disabled=True,
        on_click=lambda e: _do_delete_selected_mp3s(),
    )

    def _do_delete_selected_mp3s():
        to_delete = [_mp3_songs[i] for i, v in _mp3_checked.items() if v]
        for song in to_delete:
            try:
                Path(song["_file"]).unlink()
            except Exception:
                pass
        _reload_mp3_songs()

    def _reload_mp3_songs():
        nonlocal _mp3_songs
        _mp3_songs = []
        _mp3_checked.clear()
        _mp3_cbs.clear()
        _mp3_select_all_cb.value = False

        folder = config.get("song_output_folder", "")
        if folder and Path(folder).exists():
            for p in sorted(Path(folder).rglob("*.mp3")):
                _mp3_songs.append({
                    "title": p.stem.replace("_", " ").title(),
                    "_file": str(p),
                    "_name": p.name,
                })

        mp3_song_list.controls = []
        if not _mp3_songs:
            mp3_song_list.controls.append(
                ft.Text("No songs (.mp3) found.", size=12, color=DIM)
            )
        else:
            mp3_song_list.controls.append(_mp3_select_all_cb)
            for i, song in enumerate(_mp3_songs):
                _mp3_checked[i] = False
                idx = i
                cb = ft.Checkbox(
                    value=False, active_color=SUNO_CLR,
                    on_change=lambda e, i=idx: _on_mp3_cb_change(i, e.control.value),
                )
                _mp3_cbs.append(cb)

                def _delete_one_mp3(e, file_path=song["_file"]):
                    try:
                        Path(file_path).unlink()
                    except Exception:
                        pass
                    _reload_mp3_songs()

                row = ft.Row(
                    [
                        cb,
                        ft.Column(
                            [
                                ft.Text(song["title"], size=13, color=TEXT,
                                        weight=ft.FontWeight.W_500, no_wrap=True),
                                ft.Text(song["_name"], size=11, color=DIM, no_wrap=True),
                            ],
                            spacing=1, expand=True,
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_color="#FF6B6B", icon_size=16,
                            tooltip="Delete", on_click=_delete_one_mp3,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                mp3_song_list.controls.append(
                    ft.Container(
                        content=row,
                        bgcolor=SURFACE2, border_radius=8,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    )
                )
        _update_mp3_delete_btn()
        page.update()

    mp3_section = card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.AUDIOTRACK, color=SUNO_CLR, size=16),
                        ft.Text("Songs", size=13, color=DIM, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.FOLDER_OPEN, icon_color=DIM, icon_size=16,
                            tooltip="Open songs folder",
                            on_click=lambda e: _open_folder(config.get("song_output_folder", "")),
                        ),
                        ft.IconButton(
                            ft.Icons.REFRESH, icon_color=DIM, icon_size=16,
                            tooltip="Reload",
                            on_click=lambda e: _reload_mp3_songs(),
                        ),
                    ],
                    spacing=8,
                ),
                mp3_song_list,
                ft.Row([mp3_delete_btn], spacing=10),
            ],
            spacing=6,
        ),
        padding=16,
    )

    # ── Suno lyrics selector (read-only, no delete) ───────────────────
    _suno_lyrics: list[dict] = []
    _suno_checked: dict[int, bool] = {}
    _suno_cbs: list[ft.Checkbox] = []

    suno_lyrics_list = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO, height=180)

    def _update_suno_send_btn():
        count = sum(1 for v in _suno_checked.values() if v)
        suno_send_btn.text = f"Generate Selected ({count})"
        suno_send_btn.disabled = count == 0
        page.update()

    def _on_suno_select_all(e):
        checked = e.control.value
        for i, cb in enumerate(_suno_cbs):
            cb.value = checked
            _suno_checked[i] = checked
        _update_suno_send_btn()

    def _on_suno_cb_change(idx: int, val: bool):
        _suno_checked[idx] = val
        if not val and _suno_select_all_cb.value:
            _suno_select_all_cb.value = False
        elif val and all(_suno_checked.get(i, False) for i in range(len(_suno_cbs))):
            _suno_select_all_cb.value = True
        _update_suno_send_btn()

    _suno_select_all_cb = ft.Checkbox(
        label="Select All",
        label_style=ft.TextStyle(size=12, color=DIM),
        value=False, active_color=SUNO_CLR,
        on_change=_on_suno_select_all,
    )

    def _reload_suno_lyrics():
        nonlocal _suno_lyrics
        _suno_lyrics = []
        _suno_checked.clear()
        _suno_cbs.clear()
        _suno_select_all_cb.value = False

        folder = config.get("output_folder", "")
        if folder:
            for p in sorted(Path(folder).rglob("*.txt")):
                song = _parse_song_file(p)
                if song:
                    _suno_lyrics.append(song)

        suno_lyrics_list.controls = []
        if not _suno_lyrics:
            suno_lyrics_list.controls.append(
                ft.Text("No lyrics found. Generate some in the Lyrics tab.", size=12, color=DIM)
            )
        else:
            suno_lyrics_list.controls.append(_suno_select_all_cb)
            for i, song in enumerate(_suno_lyrics):
                _suno_checked[i] = False
                idx = i
                cb = ft.Checkbox(
                    value=False, active_color=SUNO_CLR,
                    on_change=lambda e, i=idx: _on_suno_cb_change(i, e.control.value),
                )
                _suno_cbs.append(cb)

                subtitle = song["genre"]
                if song["bpm"]:
                    subtitle += f" · {song['bpm']} BPM" if subtitle else f"{song['bpm']} BPM"
                if song["theme"]:
                    subtitle += f" · {song['theme']}" if subtitle else song["theme"]

                row = ft.Row(
                    [
                        cb,
                        ft.Column(
                            [
                                ft.Text(song["title"], size=13, color=TEXT,
                                        weight=ft.FontWeight.W_500, no_wrap=True),
                                ft.Text(subtitle or Path(song["_file"]).name,
                                        size=11, color=DIM, no_wrap=True),
                            ],
                            spacing=1, expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                suno_lyrics_list.controls.append(
                    ft.Container(
                        content=row,
                        bgcolor=SURFACE2, border_radius=8,
                        padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    )
                )
        _update_suno_send_btn()
        page.update()

    # ── Suno generation controls ──────────────────────────────────────
    _current_suno_model_id = config.get("suno_model", "chirp-auk")
    _suno_model_label = next(
        (k for k, v in SUNO_MODELS.items() if v == _current_suno_model_id),
        list(SUNO_MODELS.keys())[0],
    )
    suno_model_dd = ft.Dropdown(
        label="Model",
        value=_suno_model_label,
        options=[ft.dropdown.Option(k) for k in SUNO_MODELS],
        width=200,
        text_size=12, label_style=ft.TextStyle(size=11, color=DIM),
        border_color=BORDER, focused_border_color=SUNO_CLR,
        bgcolor=SURFACE2, color=TEXT,
        on_change=lambda e: _on_suno_model_change(),
    )

    def _on_suno_model_change():
        config["suno_model"] = SUNO_MODELS[suno_model_dd.value]
        save_config(config)

    suno_send_btn = ft.ElevatedButton(
        "Generate Selected (0)",
        icon=ft.Icons.MUSIC_NOTE,
        bgcolor="#6A1B9A", color=TEXT,
        height=42, disabled=True,
        on_click=lambda e: do_generate_suno(e),
    )
    suno_status_text = ft.Text("", size=12, color=DIM)
    suno_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, auto_scroll=True, height=90)

    def _copy_suno_log(e):
        lines = []
        for ctrl in suno_log.controls:
            if isinstance(ctrl, ft.Text):
                lines.append(ctrl.value or "")
        page.set_clipboard("\n".join(lines))
        _suno_copy_btn.icon = ft.Icons.CHECK
        _suno_copy_btn.tooltip = "Copied!"
        page.update()

    _suno_copy_btn = ft.IconButton(
        ft.Icons.COPY, icon_color=DIM, icon_size=14,
        tooltip="Copy log", on_click=_copy_suno_log,
    )
    suno_log_card = ft.Container(
        content=ft.Column([
            ft.Row([ft.Container(expand=True), _suno_copy_btn], spacing=0, height=20),
            suno_log,
        ], spacing=2),
        bgcolor="#0A0D14", border_radius=8,
        border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        visible=False,
    )

    def log_suno(msg: str, color: str = DIM):
        suno_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
        suno_log_card.visible = True
        page.update()

    suno_not_connected_text = ft.Text(
        "Connect to Suno in Settings to generate songs.",
        size=12, color=DIM,
    )

    suno_section = card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.HEADPHONES, color=SUNO_CLR, size=16),
                        ft.Text("Generate Songs from Lyrics", size=13, color=DIM,
                                weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        suno_status_text,
                        ft.IconButton(
                            ft.Icons.REFRESH, icon_color=DIM, icon_size=16,
                            tooltip="Reload lyrics",
                            on_click=lambda e: _reload_suno_lyrics(),
                        ),
                    ],
                    spacing=8,
                ),
                suno_not_connected_text,
                ft.Container(height=4),
                suno_lyrics_list,
                ft.Container(height=6),
                ft.Row(
                    [suno_model_dd, suno_send_btn],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                suno_log_card,
            ],
            spacing=6,
        ),
        padding=16,
    )

    def do_generate_suno(e):
        selected = [_suno_lyrics[i] for i, v in _suno_checked.items() if v]
        if not selected:
            return
        model_id = config.get("suno_model", "chirp-auk")
        cookie   = config.get("suno_cookie", "")
        if not cookie:
            log_suno("No Suno account connected — go to Settings.", "#FF6B6B")
            return
        suno_send_btn.disabled = True
        suno_send_btn.text = "Generating…"
        suno_log.controls = []
        suno_log_card.visible = False
        _suno_copy_btn.icon = ft.Icons.COPY
        _suno_copy_btn.tooltip = "Copy log"
        suno_status_text.value = f"Starting — {len(selected)} song(s)…"
        page.update()

        def _run():
            import asyncio as _aio
            try:
                from core.suno_client import SunoClient
                from core.suno_auth import generate_via_browser

                client = SunoClient(cookie, on_log=lambda m: log_suno(m))

                for song_idx, song in enumerate(selected):
                    tag_parts = [song.get("genre", "")]
                    if song.get("bpm"):
                        tag_parts.append(f"{song['bpm']} bpm")
                    if song.get("theme"):
                        tag_parts.append(song["theme"])
                    song_tags = ", ".join(p for p in tag_parts if p) or "pop"

                    clips = None
                    log_suno(f"Submitting \"{song['title']}\" | {song_tags}")
                    suno_status_text.value = f"Generating \"{song['title']}\"…"
                    page.update()

                    try:
                        clips = client.generate(
                            lyrics=song["lyrics"],
                            tags=song_tags,
                            title=song["title"],
                            model=model_id,
                        )
                        log_suno(f"{len(clips)} clip(s) rendering…")
                    except Exception as gen_err:
                        log_suno(f"Direct API blocked: {gen_err}")
                        log_suno("Opening browser for generation…")
                        suno_status_text.value = f"Browser gen: \"{song['title']}\"…"
                        page.update()
                        loop = _aio.new_event_loop()
                        try:
                            clips = loop.run_until_complete(
                                generate_via_browser(
                                    cookie_str=cookie,
                                    lyrics=song["lyrics"],
                                    tags=song_tags,
                                    title=song["title"],
                                    on_status=lambda m: log_suno(m),
                                    timeout=300.0,
                                )
                            )
                            if clips:
                                log_suno(f"{len(clips)} clip(s) from browser")
                        except Exception as browser_err:
                            log_suno(f"Browser generation failed: {browser_err}", "#FF6B6B")
                        finally:
                            loop.close()

                    if not clips:
                        log_suno(f"No clips returned for \"{song['title']}\"", "#FF6B6B")
                        continue

                    def on_poll(m):
                        suno_status_text.value = m
                        log_suno(m)

                    paths = client.wait_and_download(
                        clips,
                        output_dir=config.get("song_output_folder", ""),
                        song_title=song["title"],
                        on_status=on_poll,
                    )
                    if paths:
                        for p in paths:
                            log_suno(f"Saved: {Path(p).name}", SUCCESS)
                    else:
                        log_suno(f"No audio for \"{song['title']}\"", "#FF6B6B")

                    if song_idx < len(selected) - 1:
                        log_suno("Waiting 15s before next song…")
                        time.sleep(15)

                suno_status_text.value = "Done!"
                log_suno("All done — check your Songs tab.", SUCCESS)
                _reload_mp3_songs()

            except Exception as exc:
                log_suno(f"Error: {exc}", "#FF6B6B")
                suno_status_text.value = "Suno error — see log."
            finally:
                _update_suno_send_btn()
                page.update()

        threading.Thread(target=_run, daemon=True).start()

    def _refresh_suno_visibility():
        has_cookie = bool(config.get("suno_cookie", ""))
        suno_not_connected_text.visible = not has_cookie
        suno_lyrics_list.visible = has_cookie
        suno_model_dd.visible = has_cookie
        suno_send_btn.visible = has_cookie
        if has_cookie:
            _reload_suno_lyrics()
        page.update()

    songs_tab_content = ft.Column(
        [
            mp3_section,
            suno_section,
            ft.Container(height=16),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )

    # ══════════════════════════════════════════════════════════════════
    # MAIN VIEW with TABS
    # ══════════════════════════════════════════════════════════════════

    _active_tab = "lyrics"

    def _tab_style(active: bool):
        return ft.ButtonStyle(
            color=TEXT if active else DIM,
            bgcolor=ACCENT if active else "transparent",
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.padding.symmetric(horizontal=20, vertical=10),
        )

    tab_lyrics_btn = ft.ElevatedButton(
        "Lyrics", icon=ft.Icons.EDIT_NOTE,
        bgcolor=ACCENT, color=TEXT, height=38,
        on_click=lambda e: switch_tab("lyrics"),
    )
    tab_songs_btn = ft.ElevatedButton(
        "Songs", icon=ft.Icons.AUDIOTRACK,
        bgcolor="transparent", color=DIM, height=38,
        on_click=lambda e: switch_tab("songs"),
    )

    def switch_tab(tab: str):
        nonlocal _active_tab
        _active_tab = tab
        if tab == "lyrics":
            tab_lyrics_btn.bgcolor = ACCENT
            tab_lyrics_btn.color = TEXT
            tab_songs_btn.bgcolor = "transparent"
            tab_songs_btn.color = DIM
            lyrics_tab_content.visible = True
            songs_tab_content.visible = False
            _reload_saved_lyrics()
        else:
            tab_lyrics_btn.bgcolor = "transparent"
            tab_lyrics_btn.color = DIM
            tab_songs_btn.bgcolor = ACCENT
            tab_songs_btn.color = TEXT
            lyrics_tab_content.visible = True  # keep in DOM but hide
            lyrics_tab_content.visible = False
            songs_tab_content.visible = True
            _reload_mp3_songs()
            _refresh_suno_visibility()
        page.update()

    # Initial state: songs tab hidden
    songs_tab_content.visible = False

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
                        ft.Container(width=24),
                        ft.Row([tab_lyrics_btn, tab_songs_btn], spacing=8),
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
                padding=ft.padding.symmetric(horizontal=24, vertical=10),
                border=ft.border.only(bottom=ft.border.BorderSide(1, BORDER)),
            ),
            # Body
            ft.Container(
                content=ft.Stack(
                    [lyrics_tab_content, songs_tab_content],
                    expand=True,
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
        s_genre = ft.TextField(
            label="Default Genre",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            value=config.get("default_genre", "Pop"), width=280, text_size=14,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        )
        s_output = ft.TextField(
            label="Lyrics Folder",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            value=config.get("output_folder", ""),
            expand=True, text_size=13,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        )
        s_song_output = ft.TextField(
            label="Songs Folder (mp3)",
            label_style=ft.TextStyle(color=DIM, size=12),
            border_color=BORDER, focused_border_color=ACCENT,
            bgcolor=SURFACE2, color=TEXT, border_radius=10,
            value=config.get("song_output_folder", ""),
            expand=True, text_size=13,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=14),
        )

        _active_folder_target = {"ref": s_output}

        def _on_folder_picked(e):
            if e.path:
                _active_folder_target["ref"].value = e.path
                page.update()

        folder_picker = ft.FilePicker(on_result=_on_folder_picked)
        page.overlay.append(folder_picker)
        page.update()

        # ── Suno settings ──────────────────────────────────────────────
        s_suno_status = ft.Text(
            "● Connected" if config.get("suno_cookie") else "○ Not connected",
            size=12,
            color=SUCCESS if config.get("suno_cookie") else DIM,
        )
        s_suno_connect_btn = ft.ElevatedButton(
            "Connect to Suno",
            icon=ft.Icons.OPEN_IN_BROWSER,
            bgcolor="#6A1B9A", color=TEXT,
            height=42,
        )
        s_suno_disconnect_btn = ft.TextButton(
            "Disconnect",
            icon=ft.Icons.LOGOUT,
            style=ft.ButtonStyle(color="#FF6B6B"),
            visible=bool(config.get("suno_cookie")),
        )
        s_suno_log = ft.Column([], spacing=3, scroll=ft.ScrollMode.AUTO, auto_scroll=True, height=80)

        def _copy_s_suno_log(e):
            lines = []
            for ctrl in s_suno_log.controls:
                if isinstance(ctrl, ft.Text):
                    lines.append(ctrl.value or "")
            page.set_clipboard("\n".join(lines))
            _s_suno_copy_btn.icon = ft.Icons.CHECK
            _s_suno_copy_btn.tooltip = "Copied!"
            page.update()

        _s_suno_copy_btn = ft.IconButton(
            ft.Icons.COPY, icon_color=DIM, icon_size=14,
            tooltip="Copy log", on_click=_copy_s_suno_log,
        )
        s_suno_log_card = ft.Container(
            content=ft.Column([
                ft.Row([ft.Container(expand=True), _s_suno_copy_btn], spacing=0, height=20),
                s_suno_log,
            ], spacing=2),
            bgcolor="#0A0D14", border_radius=8,
            border=ft.border.all(1, BORDER),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            visible=False,
        )

        def log_suno_connect(msg: str, color: str = DIM):
            s_suno_log.controls.append(ft.Text(f"› {msg}", size=12, color=color, selectable=True))
            s_suno_log_card.visible = True
            page.update()

        def do_connect_suno(e):
            s_suno_connect_btn.disabled = True
            s_suno_connect_btn.text = "Waiting for login…"
            s_suno_log.controls = []
            s_suno_log_card.visible = False
            s_suno_status.value = "Connecting…"
            s_suno_status.color = DIM
            page.update()

            def _run():
                import asyncio
                from core.suno_auth import login_and_get_cookies
                from core.suno_client import validate_cookie

                loop = asyncio.new_event_loop()
                try:
                    cookie = loop.run_until_complete(
                        login_and_get_cookies(
                            on_status=lambda m: log_suno_connect(m),
                        )
                    )
                    ok, msg = validate_cookie(cookie)
                    if ok:
                        config["suno_cookie"] = cookie
                        save_config(config)
                        s_suno_status.value = f"● Connected — {msg}"
                        s_suno_status.color = SUCCESS
                        s_suno_disconnect_btn.visible = True
                        log_suno_connect(f"Connected! {msg}", SUCCESS)
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
                    s_suno_connect_btn.text = "Connect to Suno"
                    page.update()

            threading.Thread(target=_run, daemon=True).start()

        def do_disconnect(e):
            config["suno_cookie"] = ""
            save_config(config)
            s_suno_status.value = "○ Not connected"
            s_suno_status.color = DIM
            s_suno_disconnect_btn.visible = False
            s_suno_log.controls = []
            s_suno_log_card.visible = False
            page.update()

        s_suno_connect_btn.on_click    = do_connect_suno
        s_suno_disconnect_btn.on_click = do_disconnect

        # ── Save handler ──────────────────────────────────────────────
        def on_save(e):
            config["model"]              = MODELS[s_model.value]
            config["default_genre"]      = s_genre.value
            config["output_folder"]      = s_output.value
            config["song_output_folder"] = s_song_output.value
            save_config(config)
            model_dd.value  = s_model.value
            genre_dd.value  = s_genre.value
            page.overlay.remove(folder_picker)
            show_main_view()

        def on_pick_lyrics(e):
            _active_folder_target["ref"] = s_output
            folder_picker.get_directory_path(dialog_title="Choose lyrics folder")

        def on_pick_songs(e):
            _active_folder_target["ref"] = s_song_output
            folder_picker.get_directory_path(dialog_title="Choose songs folder")

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
                                                    tooltip="Choose lyrics folder",
                                                    on_click=on_pick_lyrics,
                                                ),
                                            ],
                                            spacing=8,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        ft.Row(
                                            [
                                                s_song_output,
                                                ft.IconButton(
                                                    ft.Icons.FOLDER_OPEN,
                                                    icon_color=ACCENT,
                                                    tooltip="Choose songs folder",
                                                    on_click=on_pick_songs,
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
                            card(
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                ft.Icon(ft.Icons.HEADPHONES,
                                                        color=SUNO_CLR, size=16),
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
                                            "Click Connect to open a browser window. "
                                            "Log in to Suno using any method (Google, Discord, email, etc.). "
                                            "Cookies will be captured automatically once you're signed in.",
                                            size=11, color=DIM,
                                        ),
                                        ft.Container(height=6),
                                        ft.Row(
                                            [s_suno_connect_btn],
                                            alignment=ft.MainAxisAlignment.START,
                                        ),
                                        ft.Container(height=4),
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
        _reload_saved_lyrics()
        page.update()

    def show_settings_view():
        page.controls.clear()
        page.add(build_settings_view())
        page.update()

    # ── Start ──────────────────────────────────────────────────────
    if config.get("setup_complete") and is_claude_installed():
        show_main_view()
    else:
        show_setup_view()


if __name__ == "__main__":
    ft.app(target=main)
