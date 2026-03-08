# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Get the parent directory (lyric_studio) since spec is in deploy/
lyric_studio_dir = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    [os.path.join(lyric_studio_dir, 'main.py')],  # Path to main.py in parent dir
    pathex=[lyric_studio_dir],  # Add lyric_studio directory to Python path
    binaries=[],
    datas=[
        (os.path.join(lyric_studio_dir, 'system_prompt.txt'), '.'),
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
