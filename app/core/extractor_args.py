"""Assemble ``--extractor-args`` for yt-dlp based on URL heuristics + settings.

Motivating case: YouTube's anti-bot changes (2024–2025) cause frequent

    ERROR: [youtube] <id>: The page needs to be reloaded.

when the default web player is used. Passing multiple ``player_client``
fallbacks (e.g. ``default,tv,mweb``) lets yt-dlp retry with a mobile /
TV client that is usually still working.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.settings import AppSettings


_YT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}


def _is_youtube(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host.lower() in _YT_HOSTS


def build(url: str, settings: AppSettings) -> list[str]:
    """Return the ``--extractor-args`` flags to append for ``url``."""
    args: list[str] = []
    if settings.youtube_compat and _is_youtube(url):
        clients = settings.youtube_player_clients.strip() or "default,tv,mweb"
        args += ["--extractor-args", f"youtube:player_client={clients}"]
    return args
