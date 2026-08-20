"""Persist user settings to JSON at %APPDATA%/yt-dlp-ui/config.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from app.utils import paths


@dataclass
class AppSettings:
    # --- network ---
    proxy: str = ""                          # e.g. "socks5://127.0.0.1:1080"
    socket_timeout: int = 30
    rate_limit_kbps: int = 0                 # 0 == unlimited

    # --- cookies ---
    cookies_from_browser: str = ""           # "" or one of chrome/edge/firefox/...
    cookies_file: str = ""                   # path to cookies.txt

    # --- download ---
    output_dir: str = ""                     # filled in __post_init__ if empty
    output_template: str = "%(title).100B [%(id)s].%(ext)s"
    max_concurrent: int = 3
    use_archive: bool = True

    # --- playlist ---
    sleep_interval: int = 0
    max_sleep_interval: int = 0

    # --- subtitles (defaults; per-download overridable) ---
    default_sub_langs: str = "zh,zh-Hans,en"
    embed_subs: bool = True

    # --- youtube compat (workarounds for anti-bot / "page needs reload") ---
    youtube_compat: bool = True
    youtube_player_clients: str = "default,tv,mweb"

    # --- expert ---
    extra_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.output_dir:
            self.output_dir = str(paths.default_download_dir())

    # ---------------------------------------------------------- persist

    @classmethod
    def load(cls) -> "AppSettings":
        f = paths.config_file()
        if not f.exists():
            s = cls()
            s.save()
            return s
        try:
            data = json.loads(f.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        known = {fld.name for fld in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def save(self) -> None:
        f = paths.config_file()
        f.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), "utf-8")
