# PyInstaller spec — build with:  pyinstaller build.spec
# Produces a single windowed exe that bundles bin/yt-dlp.exe & bin/ffmpeg.exe.

from pathlib import Path

block_cipher = None
proj = Path(SPECPATH)   # noqa: F821 (SPECPATH injected by PyInstaller)

binaries = []
for name in ("yt-dlp.exe", "ffmpeg.exe"):
    src = proj / "bin" / name
    if src.exists():
        binaries.append((str(src), "bin"))

a = Analysis(          # noqa: F821
    ["app/main.py"],
    pathex=[str(proj)],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821

exe = EXE(                                              # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="yt-dlp-ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
