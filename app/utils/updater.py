"""Download yt-dlp.exe / ffmpeg.exe from official sources."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Callable

import requests

from app.utils.paths import bin_dir

YTDLP_LATEST = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
# Gyan.dev provides "essentials" ffmpeg builds for Windows.
FFMPEG_ESSENTIALS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

ProgressCb = Callable[[int, int], None]  # (downloaded, total)


def _download(url: str, dest: Path, cb: ProgressCb | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if cb:
                    cb(downloaded, total)


def download_ytdlp(cb: ProgressCb | None = None) -> Path:
    target = bin_dir() / "yt-dlp.exe"
    _download(YTDLP_LATEST, target, cb)
    return target


def download_ffmpeg(cb: ProgressCb | None = None) -> Path:
    """Fetch ffmpeg-release-essentials.zip and extract ffmpeg.exe only."""
    buf = io.BytesIO()
    with requests.get(FFMPEG_ESSENTIALS, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        for chunk in r.iter_content(chunk_size=256 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            downloaded += len(chunk)
            if cb:
                cb(downloaded, total)

    buf.seek(0)
    target = bin_dir() / "ffmpeg.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buf) as zf:
        member = next(
            (n for n in zf.namelist() if n.endswith("bin/ffmpeg.exe")),
            None,
        )
        if member is None:
            raise RuntimeError("ffmpeg.exe not found in downloaded archive")
        with zf.open(member) as src, target.open("wb") as dst:
            dst.write(src.read())
    return target
