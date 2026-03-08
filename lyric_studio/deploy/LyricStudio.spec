# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
import platform
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

IS_MACOS   = platform.system() == 'Darwin'
IS_WINDOWS = platform.system() == 'Windows'

# The spec lives in deploy/; lyric_studio_dir is its parent.
lyric_studio_dir = os.path.dirname(os.path.abspath(SPECPATH))

# ── Locate the claude CLI binary bundled with claude_agent_sdk ────────────
_sdk_spec = importlib.util.find_spec('claude_agent_sdk')
_cli_name  = 'claude.exe' if IS_WINDOWS else 'claude'
if _sdk_spec and _sdk_spec.origin:
    _sdk_bundled = os.path.join(
        os.path.dirname(_sdk_spec.origin), '_bundled', _cli_name
    )
else:
    _sdk_bundled = ''
_bundled_binaries = (
    [(_sdk_bundled, 'claude_agent_sdk/_bundled')]
    if _sdk_bundled and os.path.exists(_sdk_bundled)
    else []
)

# ── flet_desktop data: includes the Flutter view engine tarball ───────────
# On macOS this is flet-macos.tar.gz; on Windows flet-windows.tar.gz.
# collect_data_files picks up whatever is present for the current platform.
_flet_desktop_datas = collect_data_files('flet_desktop')

a = Analysis(
    [os.path.join(lyric_studio_dir, 'main.py')],
    pathex=[lyric_studio_dir],
    binaries=_bundled_binaries,
    datas=[
        (os.path.join(lyric_studio_dir, 'assets', 'system_prompt.txt'), '.'),
        (os.path.join(lyric_studio_dir, '..', 'prompt', 'lyric_generation_prompt.md'), 'prompt'),
    ] + _flet_desktop_datas,
    hiddenimports=[
        'flet',
        'flet.core',
        'flet.auth',
        'flet.utils',
        'flet_desktop',
        'flet_desktop.version',
        'claude_agent_sdk',
        'claude_agent_sdk.types',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'anyio._core._asyncio_selector_thread',
        'anyio.streams.text',
        'anyio.streams.memory',
        'sniffio',
        'exceptiongroup',
        'repath',
        'msgpack',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_MACOS:
    # ── macOS: onedir mode — EXE + COLLECT + BUNDLE → produces LyricStudio.app
    # UPX is intentionally disabled: crashes on macOS Ventura+ and is
    # incompatible with macOS code signing.
    exe = EXE(
        pyz,
        a.scripts,
        [],                     # binaries/datas go to COLLECT, not here
        exclude_binaries=True,  # REQUIRED for onedir/BUNDLE mode
        name='LyricStudio',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,   # keep False — flet uses Flutter subprocess, not argv
        target_arch=None,       # None = current arch; 'universal2' for fat binary
        codesign_identity=None, # None = ad-hoc (local use); set Developer ID for distribution
        entitlements_file=None,
        icon=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='LyricStudio',
    )

    app = BUNDLE(
        coll,
        name='LyricStudio.app',
        icon=None,
        bundle_identifier='com.lyricstudio.app',
        version='1.0.0',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
            'NSAppleEventsUsageDescription': 'LyricStudio needs to launch its display engine.',
        },
    )

else:
    # ── Windows (and Linux): onefile mode — single self-contained EXE ────
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='LyricStudio',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=None,
    )
