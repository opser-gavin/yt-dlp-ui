"""Thin wrapper around QProcess to invoke yt-dlp.exe."""

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from app.utils import paths


class YtdlpRunner(QObject):
    """Run a single yt-dlp.exe invocation, emitting stdout lines in real time.

    Bytes handling: we buffer raw bytes and only decode ``utf-8`` at line
    boundaries. QProcess delivers whatever chunks the OS gives us, which can
    slice through the middle of a multi-byte UTF-8 sequence — decoding each
    chunk directly with ``errors='replace'`` turns those partial chunks into
    U+FFFD characters and mangles Chinese/Japanese/emoji titles. Newline
    bytes are always single-byte ASCII, so splitting on them first is safe.
    """

    line_received = Signal(str)      # each stdout line (no trailing \r/\n)
    stderr_received = Signal(str)    # each stderr line
    finished = Signal(int)           # exit code
    failed_to_start = Signal(str)    # error string

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._stdout_buf = bytearray()
        self._stderr_buf = bytearray()

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

        # Force yt-dlp (Python) to emit UTF-8 to stdout/stderr instead of the
        # Windows console code page. Belt & braces — the byte-buffered
        # decoder above already tolerates the default cp936, but forcing
        # UTF-8 here avoids yt-dlp's own translation errors on emoji etc.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONLEGACYWINDOWSSTDIO", "0")
        self._proc.setProcessEnvironment(env)

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

    def _emit_line(self, line_bytes: bytes, sig: Signal) -> None:
        if line_bytes:
            sig.emit(line_bytes.decode("utf-8", errors="replace"))

    def _drain_bytes(self, buf: bytearray, sig: Signal) -> None:
        """Emit each complete line in ``buf``; keep unterminated tail bytes."""
        while buf:
            nl = buf.find(b"\n")
            cr = buf.find(b"\r")
            if nl == -1 and cr == -1:
                return  # no complete line yet; keep bytes for next chunk

            if nl == -1:
                idx = cr
                consume = 1
            elif cr == -1:
                idx = nl
                consume = 1
            else:
                idx = min(nl, cr)
                # Merge a \r\n pair into a single line terminator.
                if idx == cr and idx + 1 < len(buf) and buf[idx + 1] == 0x0A:
                    consume = 2
                else:
                    consume = 1

            self._emit_line(bytes(buf[:idx]), sig)
            del buf[: idx + consume]

    def _on_stdout(self) -> None:
        assert self._proc is not None
        self._stdout_buf.extend(bytes(self._proc.readAllStandardOutput()))
        self._drain_bytes(self._stdout_buf, self.line_received)

    def _on_stderr(self) -> None:
        assert self._proc is not None
        self._stderr_buf.extend(bytes(self._proc.readAllStandardError()))
        self._drain_bytes(self._stderr_buf, self.stderr_received)

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        # Flush any buffered tail bytes as a final line before completing.
        if self._stdout_buf:
            self._emit_line(bytes(self._stdout_buf), self.line_received)
            self._stdout_buf.clear()
        if self._stderr_buf:
            self._emit_line(bytes(self._stderr_buf), self.stderr_received)
            self._stderr_buf.clear()
        self.finished.emit(code)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart:
            self.failed_to_start.emit("无法启动 yt-dlp.exe（文件缺失或权限不足）")
