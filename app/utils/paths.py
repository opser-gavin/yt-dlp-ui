"""Locate bundled binaries (yt-dlp.exe, ffmpeg.exe) and app data dirs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    """Root directory of the running app.

    When frozen by PyInstaller (--onefile), binaries are extracted to
    ``sys._MEIPASS``. Otherwise use the project root (two levels above this
    file: app/utils/paths.py -> project root).
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def bin_dir() -> Path:
    return app_root() / "bin"


def _find(name: str) -> Path | None:
    candidate = bin_dir() / name
    if candidate.exists():
        return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def ytdlp_exe() -> Path | None:
    """Return path to yt-dlp.exe or None if not found."""
    return _find("yt-dlp.exe")


def ffmpeg_exe() -> Path | None:
    return _find("ffmpeg.exe")


def app_data_dir() -> Path:
    """Per-user config dir. Uses %APPDATA% on Windows."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "yt-dlp-ui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return app_data_dir() / "config.json"


def default_download_dir() -> Path:
    """Default download destination (~/Videos/yt-dlp-ui or ~/Downloads)."""
    home = Path.home()
    for cand in (home / "Videos", home / "Downloads"):
        if cand.exists():
            return cand / "yt-dlp-ui"
    return home / "yt-dlp-ui"
