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


# Track the file yt-dlp is/was writing:
#   [download] Destination: D:\Videos\foo.f137.mp4
#   [Merger] Merging formats into "D:\Videos\foo.mkv"
#   [Merger] Merging formats into 'D:\Videos\foo.mkv'      (some builds)
#   [MoveFiles] Moving file "D:\Videos\foo.mkv" to "D:\Final\foo.mkv"
_DEST_RE = re.compile(r"^\[download\] Destination: (.+)$")
_MERGE_RE = re.compile(r'Merging formats into ["\']([^"\']+)["\']')
_MOVE_RE = re.compile(r'\[MoveFiles\] Moving file "[^"]+" to "([^"]+)"')
# Fallback playlist context — yt-dlp prints e.g.:
#   [download] Downloading item 3 of 10
#   [download] Downloading video 3 of 10
# when handling a playlist. Used when info.playlist_index isn't emitted
# via the progress-template (some extractors don't populate it).
_PL_ITEM_RE = re.compile(
    r"^\[download\] Downloading (?:item|video|playlist item) (\d+) of (\d+)"
)


@dataclass
class TaskState:
    task_id: str
    url: str
    title: str = ""
    status: TaskStatus = TaskStatus.QUEUED

    # ---- current file (single video, or current file within a playlist) ----
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None
    eta: int | None = None
    output_path: str | None = None
    error: str = ""

    # ---- original params so pause/resume can restart with --continue ------
    selection: DownloadSelection | None = None
    is_playlist: bool = False
    playlist_items: str = ""

    # ---- playlist context (populated as progress events arrive) -----------
    playlist_index: int | None = None    # 1-based; index of currently-downloading video
    playlist_count: int | None = None    # total count in the enqueued range
    completed_videos_bytes: int = 0      # sum of finished videos' bytes
    current_video_id: str = ""
    current_video_title: str = ""        # from progress events (may be flaky per stream)
    # Titles pre-fetched from --dump-single-json at probe time; index-aligned
    # with playlist_index-1. This is the authoritative source for per-video
    # titles — progress events' info.title can be overwritten mid-download by
    # yt-dlp when switching between video/audio streams, which was the cause
    # of "title garbled after a while".
    entry_titles: list[str] = field(default_factory=list)
    # A single video may involve multiple streams (video+audio). Each stream's
    # 'finished' event banks its bytes here so the running total keeps growing
    # instead of being replaced by the most recent stream's (usually smaller)
    # total. Reset when the info_id changes to a new video.
    current_video_bytes: int = 0

    # ---------------------------------------------------------- displays

    @property
    def percent(self) -> float | None:
        """Progress %.

        * Single video → byte progress on the current stream.
        * Playlist     → item progress: fully-completed videos plus the
          fraction of the current one — insulated from unknown future sizes.
        """
        if self.is_playlist and self.playlist_count:
            done = (self.playlist_index or 1) - 1
            frac = 0.0
            if self.total and self.total > 0:
                frac = min(1.0, self.downloaded / self.total)
            return min(100.0, (done + frac) / self.playlist_count * 100.0)
        if not self.total:
            return None
        return min(100.0, self.downloaded / self.total * 100.0)

    @property
    def size_display(self) -> int | None:
        """Actual bytes fetched so far (grows monotonically).

        Combines: prior videos' totals + this video's already-finished
        streams + this stream's downloaded so far.
        """
        cumulative = (
            self.completed_videos_bytes
            + self.current_video_bytes
            + self.downloaded
        )
        return cumulative or None

    @property
    def display_current_title(self) -> str:
        """Best-effort current-video title.

        Fallback chain (most trustworthy first):
          1. Pre-fetched entry_titles (from --dump-single-json, if the site
             gave full titles under --flat-playlist)
          2. Progress event's info.title (from the download-hook)
          3. Filename stem of output_path — with any '.fNNNN' format-id
             suffix stripped (e.g. 'MTV_p06.f30064' → 'MTV_p06')
          4. The task's own title
        """
        if self.entry_titles and self.playlist_index:
            i = self.playlist_index - 1
            if 0 <= i < len(self.entry_titles) and self.entry_titles[i]:
                return self.entry_titles[i]
        if self.current_video_title:
            return self.current_video_title
        if self.output_path:
            stem = Path(self.output_path).stem
            stem = re.sub(r"\.f\d+$", "", stem)
            if stem:
                return stem
        return self.title


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
        entry_titles: list[str] | None = None,
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
            entry_titles=list(entry_titles or []),
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

        # Output. For playlists, put each video under a subfolder named after
        # the playlist. Filenames use the site's original resource name only.
        #   Single:   D:\Videos\Some Video Title.mkv
        #   Playlist: D:\Videos\My Playlist\Some Video Title.mkv
        out_dir = Path(s.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.state.is_playlist:
            template = (
                "%(playlist_title,playlist_id|playlist)s/" + s.output_template
            )
        else:
            template = s.output_template
        args += ["-P", str(out_dir), "-o", template]

        # Continue (safe even on fresh runs).
        # NOTE: DO NOT use --restrict-filenames — it strips all non-ASCII
        # characters (Chinese, Japanese, emoji) from filenames, leaving only
        # ASCII fragments like "MTV_p04". --windows-filenames replaces only
        # the OS-reserved characters (\ / : * ? " < > |) and keeps Unicode.
        args += ["--continue", "--no-mtime", "--windows-filenames"]

        # Bilibili分P prefix stripping: yt-dlp's Bilibili extractor composes
        # each part's title as "<series>[ series] p<num> <part_title>", so
        # "%(title)s" comes out as
        #     经典老歌系列大合集（港台篇）MTV p01 张宇-月亮惹的祸
        # Since the series name is already the playlist subfolder, keeping
        # it in the filename is noise. Strip the "…p<num> " prefix from the
        # title metadata *before* the output template evaluates. The regex
        # is anchored + requires 'p<digits><whitespace>' so it only fires
        # on that specific pattern; regular titles pass through unchanged.
        args += ["--replace-in-metadata", "title", r"^.+\sp\d+\s+", ""]

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
            self._apply_progress(evt)
            self.updated.emit(self.state.task_id)
            return

        m = _PL_ITEM_RE.match(line)
        if m:
            new_idx, new_cnt = int(m.group(1)), int(m.group(2))
            # Playlist transition detected via stdout log — bank in-flight
            # bytes for the previous item before advancing the counters.
            if (
                self.state.is_playlist
                and self.state.playlist_index
                and new_idx != self.state.playlist_index
            ):
                self.state.completed_videos_bytes += (
                    self.state.current_video_bytes + self.state.downloaded
                )
                self.state.current_video_bytes = 0
                self.state.downloaded = 0
                self.state.total = None
            self.state.playlist_index = new_idx
            self.state.playlist_count = new_cnt
            self.updated.emit(self.state.task_id)
            return

        m = _DEST_RE.match(line)
        if m:
            self.state.output_path = m.group(1).strip()
            # Filename is our most reliable per-video title source when the
            # site's own title didn't come through the probe or progress hook.
            stem = Path(self.state.output_path).stem
            stem = re.sub(r"\.f\d+$", "", stem)
            if stem and not self.state.current_video_title:
                self.state.current_video_title = stem
            self.updated.emit(self.state.task_id)
            return

        m = _MERGE_RE.search(line)
        if m:
            self.state.output_path = m.group(1).strip()
            self.updated.emit(self.state.task_id)
            return

        m = _MOVE_RE.search(line)
        if m:
            self.state.output_path = m.group(1).strip()
            self.updated.emit(self.state.task_id)

    def _apply_progress(self, evt) -> None:
        """Fold a ProgressEvent into TaskState.

        Bytes accounting:
          * Each stream finish → its total banked into ``current_video_bytes``
            and ``downloaded`` reset to 0 (so the running sum doesn't
            double-count when the next stream starts).
          * ``info_id`` change → ``current_video_bytes`` promoted to
            ``completed_videos_bytes``.
        """
        prev_id = self.state.current_video_id
        new_id = evt.info_id

        # Playlist transition (new video begins)
        if self.state.is_playlist and prev_id and new_id and new_id != prev_id:
            # Fold anything not yet banked from the previous video.
            self.state.completed_videos_bytes += (
                self.state.current_video_bytes + self.state.downloaded
            )
            self.state.current_video_bytes = 0
            self.state.downloaded = 0
            self.state.total = None

        if new_id:
            self.state.current_video_id = new_id
        if evt.playlist_index is not None:
            self.state.playlist_index = evt.playlist_index
        if evt.playlist_count is not None:
            self.state.playlist_count = evt.playlist_count
        if evt.current_title:
            self.state.current_video_title = evt.current_title

        self.state.downloaded = evt.downloaded
        if evt.total:
            self.state.total = evt.total
        self.state.speed = evt.speed
        self.state.eta = evt.eta

        if evt.status == "finished":
            # This stream is done — bank its bytes and reset the running
            # 'downloaded' so the next stream (or postprocess) doesn't shrink
            # the displayed size.
            stream_bytes = self.state.total or self.state.downloaded
            self.state.current_video_bytes += stream_bytes
            self.state.downloaded = 0
            self.state.total = None

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
            # Fold whatever is still in-flight into the cumulative bucket so
            # the size column reflects the *entire* task on completion.
            self.state.completed_videos_bytes += (
                self.state.current_video_bytes + self.state.downloaded
            )
            self.state.current_video_bytes = 0
            self.state.downloaded = 0
            self.state.total = None
            # For playlists, snap displayed index to the final count.
            if self.state.is_playlist and self.state.playlist_count:
                self.state.playlist_index = self.state.playlist_count
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
