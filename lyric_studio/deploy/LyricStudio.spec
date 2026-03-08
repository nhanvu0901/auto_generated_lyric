# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import os
import platform

block_cipher = None

# The spec lives in deploy/; lyric_studio_dir is its parent.
lyric_studio_dir = os.path.dirname(os.path.abspath(SPECPATH))

# ── Locate the claude CLI binary bundled with claude_agent_sdk ────────────
# importlib.util.find_spec works regardless of OS or venv layout.
_sdk_spec = importlib.util.find_spec('claude_agent_sdk')
_cli_name  = 'claude.exe' if platform.system() == 'Windows' else 'claude'
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

a = Analysis(
    [os.path.join(lyric_studio_dir, 'main.py')],
    pathex=[lyric_studio_dir],
    binaries=_bundled_binaries,
    datas=[
        (os.path.join(lyric_studio_dir, 'assets', 'system_prompt.txt'), '.'),
        (os.path.join(lyric_studio_dir, '..', 'prompt', 'lyric_generation_prompt.md'), 'prompt'),
    ],
    hiddenimports=[
        'flet',
        'flet.core',
        'flet.auth',
        'flet.utils',
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
