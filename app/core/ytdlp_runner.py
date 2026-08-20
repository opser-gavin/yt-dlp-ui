"""Thin wrapper around QProcess to invoke yt-dlp.exe."""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

from app.utils import paths


class YtdlpRunner(QObject):
    """Run a single yt-dlp.exe invocation, emitting stdout lines in real time."""

    line_received = Signal(str)      # each stdout line (already stripped of \r\n)
    stderr_received = Signal(str)    # each stderr line
    finished = Signal(int)           # exit code
    failed_to_start = Signal(str)    # error string

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._stdout_buf = ""
        self._stderr_buf = ""

    # ------------------------------------------------------------------ run

    def run(self, args: list[str], workdir: str | None = None) -> bool:
        """Start yt-dlp with the given args. Returns False if binary missing."""
        exe = paths.ytdlp_exe()
        if exe is None:
            self.failed_to_start.emit(
                "yt-dlp.exe 未找到，请先在设置或首次向导中下载。"
            )
            return False

        self._proc = QProcess(self)
        self._proc.setProgram(str(exe))
        self._proc.setArguments(args)
        if workdir:
            self._proc.setWorkingDirectory(workdir)

        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)

        self._proc.start()
        return True

    def cancel(self) -> None:
        """Kill the running process (Windows has no SIGSTOP for pause)."""
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(3000)

    def is_running(self) -> bool:
        return bool(self._proc and self._proc.state() != QProcess.NotRunning)

    # -------------------------------------------------------------- signals

    def _drain(self, buf: str, sig: Signal) -> str:
        """Split ``buf`` on line breaks; emit each line; return leftover."""
        # yt-dlp uses \r for progress updates in default mode. With --newline
        # it emits \n between progress updates, but the tail of the last line
        # may still lack a terminator.
        buf = buf.replace("\r\n", "\n").replace("\r", "\n")
        *lines, tail = buf.split("\n")
        for line in lines:
            if line:
                sig.emit(line)
        return tail

    def _on_stdout(self) -> None:
        assert self._proc is not None
        data = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._stdout_buf = self._drain(self._stdout_buf + data, self.line_received)

    def _on_stderr(self) -> None:
        assert self._proc is not None
        data = bytes(self._proc.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        self._stderr_buf = self._drain(
            self._stderr_buf + data, self.stderr_received
        )

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        # Flush any buffered tail lines before signalling completion.
        for buf_attr, sig in (
            ("_stdout_buf", self.line_received),
            ("_stderr_buf", self.stderr_received),
        ):
            tail = getattr(self, buf_attr)
            if tail:
                sig.emit(tail)
                setattr(self, buf_attr, "")
        self.finished.emit(code)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart:
            self.failed_to_start.emit("无法启动 yt-dlp.exe（文件缺失或权限不足）")
