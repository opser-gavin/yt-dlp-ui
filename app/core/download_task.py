"""A single download task: state machine + yt-dlp invocation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.core import extractor_args, progress_parser
from app.core.cookie_workaround import build_cookies_arg, cleanup_temp_profile
from app.core.format_parser import DownloadSelection
from app.core.ytdlp_runner import YtdlpRunner
from app.core.settings import AppSettings
from app.utils import paths


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


class CookieWorkaroundFailed(RuntimeError):
    """Raised in _build_args when cookie DB copy strategies all fail."""


# Path yt-dlp reports for the finished file, e.g.:
#   [download] Destination: D:\Videos\foo [abc].webm
#   [Merger] Merging formats into "D:\Videos\foo [abc].mkv"
_DEST_RE = re.compile(r"^\[download\] Destination: (.+)$")
_MERGE_RE = re.compile(r'Merging formats into "([^"]+)"')


@dataclass
class TaskState:
    task_id: str
    url: str
    title: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None
    eta: int | None = None
    output_path: str | None = None
    error: str = ""
    # Original params so pause/resume can restart with --continue.
    selection: DownloadSelection | None = None
    is_playlist: bool = False
    playlist_items: str = ""     # e.g. "1-10"

    @property
    def percent(self) -> float | None:
        if not self.total:
            return None
        return min(100.0, self.downloaded / self.total * 100.0)


class DownloadTask(QObject):
    """Owns a YtdlpRunner and translates its output into structured state."""

    updated = Signal(str)       # task_id
    finished = Signal(str)      # task_id (any terminal state)

    def __init__(
        self,
        url: str,
        selection: DownloadSelection,
        settings: AppSettings,
        title: str = "",
        is_playlist: bool = False,
        playlist_items: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = TaskState(
            task_id=uuid.uuid4().hex[:8],
            url=url,
            title=title or url,
            selection=selection,
            is_playlist=is_playlist,
            playlist_items=playlist_items,
        )
        self._settings = settings
        self._runner: YtdlpRunner | None = None
        self._temp_cookie_profile: Path | None = None

    # ---------------------------------------------------------- lifecycle

    def start(self) -> None:
        self.state.status = TaskStatus.RUNNING
        self.state.error = ""
        try:
            args = self._build_args()
        except CookieWorkaroundFailed as e:
            self.state.status = TaskStatus.FAILED
            self.state.error = str(e)
            self.updated.emit(self.state.task_id)
            self.finished.emit(self.state.task_id)
            return
        self._runner = YtdlpRunner(self)
        self._runner.line_received.connect(self._on_line)
        self._runner.stderr_received.connect(self._on_stderr)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed_to_start.connect(self._on_start_error)
        ok = self._runner.run(args)
        if not ok:
            self.state.status = TaskStatus.FAILED
            self.updated.emit(self.state.task_id)
            self.finished.emit(self.state.task_id)

    def pause(self) -> None:
        """Kill the process; --continue will resume from the .part file."""
        if self._runner and self._runner.is_running():
            self._runner.cancel()
        self.state.status = TaskStatus.PAUSED
        self.updated.emit(self.state.task_id)

    def cancel(self) -> None:
        if self._runner and self._runner.is_running():
            self._runner.cancel()
        self.state.status = TaskStatus.CANCELED
        self.updated.emit(self.state.task_id)
        self.finished.emit(self.state.task_id)

    def resume(self) -> None:
        """Restart the process; -c/--continue picks up the .part file."""
        self.start()

    # -------------------------------------------------------- args builder

    def _build_args(self) -> list[str]:
        s = self._settings
        args: list[str] = []

        # Format / subs (from user selection).
        if self.state.selection:
            args += self.state.selection.to_args()
        else:
            args += ["-f", "bv*+ba/best"]

        # Progress template.
        args += progress_parser.PROGRESS_TEMPLATE_ARGS

        # Output.
        out_dir = Path(s.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        args += ["-P", str(out_dir), "-o", s.output_template]

        # Continue (safe even on fresh runs).
        args += ["--continue", "--no-mtime", "--restrict-filenames"]

        # ffmpeg location.
        ff = paths.ffmpeg_exe()
        if ff:
            args += ["--ffmpeg-location", str(ff)]

        # Proxy.
        if s.proxy:
            args += ["--proxy", s.proxy]
        if s.socket_timeout:
            args += ["--socket-timeout", str(s.socket_timeout)]
        if s.rate_limit_kbps:
            args += ["--limit-rate", f"{s.rate_limit_kbps}K"]

        # Cookies. For Chromium browsers on Windows, stage a copy of the
        # Cookies DB to a temp dir first (Chrome holds an exclusive lock).
        if s.cookies_from_browser:
            cookie_args, tmp, wa_err = build_cookies_arg(s.cookies_from_browser)
            if wa_err:
                # Copy strategies exhausted. Surface the error via the task
                # state; the process is not started.
                self.state.error = wa_err
                raise CookieWorkaroundFailed(wa_err)
            args += cookie_args
            self._temp_cookie_profile = tmp
        elif s.cookies_file:
            args += ["--cookies", s.cookies_file]

        # Archive (dedup).
        if s.use_archive:
            args += ["--download-archive", str(out_dir / "archive.txt")]

        # Playlist handling.
        if self.state.is_playlist:
            args += ["--yes-playlist"]
            if self.state.playlist_items:
                args += ["--playlist-items", self.state.playlist_items]
            if s.sleep_interval:
                args += ["--sleep-interval", str(s.sleep_interval)]
            if s.max_sleep_interval:
                args += ["--max-sleep-interval", str(s.max_sleep_interval)]
        else:
            args += ["--no-playlist"]

        # Site-specific workarounds (e.g. YouTube player_client fallbacks).
        args += extractor_args.build(self.state.url, s)

        # Extra raw args.
        if s.extra_args:
            args += s.extra_args

        args.append(self.state.url)
        return args

    # -------------------------------------------------------------- events

    def _on_line(self, line: str) -> None:
        evt = progress_parser.parse(line)
        if evt:
            self.state.downloaded = evt.downloaded
            self.state.total = evt.total or self.state.total
            self.state.speed = evt.speed
            self.state.eta = evt.eta
            if evt.status == "finished":
                # yt-dlp emits 'finished' per format; keep running until proc exit.
                pass
            self.updated.emit(self.state.task_id)
            return

        m = _DEST_RE.match(line)
        if m:
            self.state.output_path = m.group(1).strip()
            self.updated.emit(self.state.task_id)
            return

        m = _MERGE_RE.search(line)
        if m:
            self.state.output_path = m.group(1).strip()
            self.updated.emit(self.state.task_id)

    def _on_stderr(self, line: str) -> None:
        if "ERROR" in line:
            self.state.error = line

    def _on_finished(self, code: int) -> None:
        self._cleanup_cookies()
        # If we were paused/canceled, don't overwrite that terminal state.
        if self.state.status in (TaskStatus.PAUSED, TaskStatus.CANCELED):
            return
        if code == 0:
            self.state.status = TaskStatus.DONE
            if self.state.total:
                self.state.downloaded = self.state.total
        else:
            self.state.status = TaskStatus.FAILED
            if not self.state.error:
                self.state.error = f"yt-dlp 退出码 {code}"
        self.updated.emit(self.state.task_id)
        self.finished.emit(self.state.task_id)

    def _on_start_error(self, msg: str) -> None:
        self._cleanup_cookies()
        self.state.status = TaskStatus.FAILED
        self.state.error = msg
        self.updated.emit(self.state.task_id)
        self.finished.emit(self.state.task_id)

    def _cleanup_cookies(self) -> None:
        cleanup_temp_profile(self._temp_cookie_profile)
        self._temp_cookie_profile = None
