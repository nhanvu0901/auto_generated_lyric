# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[('/Users/nhanvu/Documents/AI_project/auto_generated_lyric/lyric_studio/.venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude', 'claude_agent_sdk/_bundled')],
    datas=[('assets/system_prompt.txt', '.'), ('/Users/nhanvu/Documents/AI_project/auto_generated_lyric/prompt/lyric_generation_prompt.md', 'prompt')],
    hiddenimports=['flet', 'flet.core', 'flet.auth', 'flet.utils', 'flet_desktop', 'claude_agent_sdk', 'claude_agent_sdk.types', 'anyio', 'anyio._backends._asyncio', 'sniffio', 'exceptiongroup'],
    hookspath=['/Users/nhanvu/Documents/AI_project/auto_generated_lyric/lyric_studio/.venv/lib/python3.12/site-packages/flet_cli/__pyinstaller'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LyricStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LyricStudio',
)
app = BUNDLE(
    coll,
    name='LyricStudio.app',
    icon=None,
    bundle_identifier='com.lyricstudio.app',
)
