"""One-shot 'probe URL' helper: run yt-dlp --dump-single-json and return MediaInfo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.core import extractor_args
from app.core.cookie_workaround import build_cookies_arg, cleanup_temp_profile
from app.core.format_parser import MediaInfo, parse
from app.core.settings import AppSettings
from app.core.ytdlp_runner import YtdlpRunner


class UrlProbe(QObject):
    ready = Signal(object)      # MediaInfo
    failed = Signal(str)

    def __init__(self, url: str, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._settings = settings
        self._buf: list[str] = []
        self._err: list[str] = []
        self._temp_cookie_profile: Path | None = None
        self._runner = YtdlpRunner(self)
        self._runner.line_received.connect(self._buf.append)
        self._runner.stderr_received.connect(self._err.append)
        self._runner.finished.connect(self._on_done)
        self._runner.failed_to_start.connect(self._on_start_error)

    def start(self) -> None:
        s = self._settings
        args = ["--dump-single-json", "--no-warnings", "--no-download",
                "--flat-playlist"]
        if s.proxy:
            args += ["--proxy", s.proxy]

        if s.cookies_from_browser:
            cookie_args, tmp, wa_err = build_cookies_arg(s.cookies_from_browser)
            if wa_err:
                # Every copy strategy failed; native yt-dlp would fail too.
                # Fire failed synchronously (via a zero-delay signal-safe path).
                self._temp_cookie_profile = None
                self.failed.emit(wa_err)
                return
            args += cookie_args
            self._temp_cookie_profile = tmp
        elif s.cookies_file:
            args += ["--cookies", s.cookies_file]

        args += extractor_args.build(self._url, s)

        args.append(self._url)
        self._runner.run(args)

    def _cleanup(self) -> None:
        cleanup_temp_profile(self._temp_cookie_profile)
        self._temp_cookie_profile = None

    def _on_start_error(self, msg: str) -> None:
        self._cleanup()
        self.failed.emit(msg)

    def _on_done(self, code: int) -> None:
        self._cleanup()
        if code != 0:
            msg = "\n".join(self._err[-10:]) or f"yt-dlp 退出码 {code}"
            self.failed.emit(msg)
            return
        try:
            info: MediaInfo = parse("\n".join(self._buf), self._url)
        except Exception as e:                    # noqa: BLE001
            self.failed.emit(f"无法解析 JSON: {e}")
            return
        self.ready.emit(info)
