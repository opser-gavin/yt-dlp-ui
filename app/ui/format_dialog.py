"""Dialog showing available formats and subtitles for a parsed URL."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.format_parser import DownloadSelection, MediaInfo


def _fmt_size(n: int | None) -> str:
    if not n:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


class FormatDialog(QDialog):
    """Let user pick a video format, audio format, subtitle langs."""

    def __init__(self, info: MediaInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"选择下载内容 — {info.title}")
        self.resize(820, 560)

        root = QVBoxLayout(self)

        # Header
        header = QLabel(
            f"<b>{info.title}</b><br>"
            f"<span style='color:#888'>{info.uploader or ''}"
            f"{' · ' + self._fmt_duration(info.duration) if info.duration else ''}"
            f"</span>"
        )
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        # Audio-only toggle
        self.audio_only_cb = QCheckBox("仅下载音频（提取为 MP3/M4A）")
        self.audio_only_cb.toggled.connect(self._on_audio_only_toggled)
        root.addWidget(self.audio_only_cb)

        self.audio_format_row = QHBoxLayout()
        self.audio_format_row.addWidget(QLabel("音频格式:"))
        self.audio_format_combo = QComboBox()
        self.audio_format_combo.addItems(["mp3", "m4a", "opus", "flac", "wav"])
        self.audio_format_row.addWidget(self.audio_format_combo)
        self.audio_format_row.addStretch(1)
        self._audio_row_widget = QWidget()
        self._audio_row_widget.setLayout(self.audio_format_row)
        self._audio_row_widget.setEnabled(False)
        root.addWidget(self._audio_row_widget)

        # Video formats table
        root.addWidget(QLabel("视频轨（可选一个）:"))
        self.video_table = self._build_format_table()
        self._populate_formats(self.video_table, kind="video")
        root.addWidget(self.video_table, 3)

        # Audio formats table
        root.addWidget(QLabel("音频轨（可选一个；与视频合并 或 仅音频提取）:"))
        self.audio_table = self._build_format_table()
        self._populate_formats(self.audio_table, kind="audio")
        root.addWidget(self.audio_table, 2)

        # Subtitles
        if info.subtitles:
            root.addWidget(QLabel("字幕语言:"))
            sub_row = QHBoxLayout()
            self.sub_checks: list[tuple[QCheckBox, str]] = []
            for s in info.subtitles[:20]:
                label = s.lang + ("(自动)" if s.is_auto else "")
                cb = QCheckBox(label)
                sub_row.addWidget(cb)
                self.sub_checks.append((cb, s.lang))
            sub_row.addStretch(1)
            wrap = QWidget()
            wrap.setLayout(sub_row)
            root.addWidget(wrap)
            self.embed_sub_cb = QCheckBox("将字幕内嵌到视频")
            self.embed_sub_cb.setChecked(True)
            root.addWidget(self.embed_sub_cb)
        else:
            self.sub_checks = []
            self.embed_sub_cb = None

        self.thumb_cb = QCheckBox("同时保存封面图")
        root.addWidget(self.thumb_cb)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _fmt_duration(secs: float | None) -> str:
        if not secs:
            return ""
        s = int(secs)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _build_format_table(self) -> QTableWidget:
        cols = ["ID", "扩展", "分辨率/码率", "编码", "大小", "备注"]
        t = QTableWidget(0, len(cols), self)
        t.setHorizontalHeaderLabels(cols)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setSelectionMode(QTableWidget.SingleSelection)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        h = t.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        return t

    def _populate_formats(self, table: QTableWidget, kind: str) -> None:
        best_row = -1
        best_metric = -1
        for f in self.info.formats:
            if kind == "video" and not (f.is_video_only or f.is_muxed):
                continue
            if kind == "audio" and not (f.is_audio_only or f.is_muxed):
                continue

            row = table.rowCount()
            table.insertRow(row)

            if kind == "video":
                res = f"{f.height}p" if f.height else "-"
                if f.fps:
                    res += f"@{int(f.fps)}"
                if f.tbr:
                    res += f"  {int(f.tbr)}k"
                codec = f.vcodec
                metric = (f.height or 0) * 1000 + int(f.fps or 0)
            else:
                res = f"{int(f.tbr)}k" if f.tbr else "-"
                codec = f.acodec
                metric = int(f.tbr or 0)

            cells = [
                f.format_id,
                f.ext,
                res,
                codec,
                _fmt_size(f.filesize),
                f.note,
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.UserRole, f.format_id)
                table.setItem(row, col, item)

            if metric > best_metric:
                best_metric = metric
                best_row = row

        if best_row >= 0:
            table.selectRow(best_row)

    def _on_audio_only_toggled(self, checked: bool) -> None:
        self._audio_row_widget.setEnabled(checked)
        self.video_table.setEnabled(not checked)

    # ------------------------------------------------------- selection

    def _selected_id(self, table: QTableWidget) -> str | None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        item = table.item(rows[0].row(), 0)
        return item.text() if item else None

    def selection(self) -> DownloadSelection:
        audio_only = self.audio_only_cb.isChecked()
        vid = None if audio_only else self._selected_id(self.video_table)
        aud = self._selected_id(self.audio_table)
        langs = [lang for cb, lang in self.sub_checks if cb.isChecked()]
        return DownloadSelection(
            video_format_id=vid,
            audio_format_id=aud,
            audio_only=audio_only,
            audio_format=self.audio_format_combo.currentText(),
            subtitle_langs=langs,
            embed_subs=bool(self.embed_sub_cb and self.embed_sub_cb.isChecked()),
            write_thumbnail=self.thumb_cb.isChecked(),
        )
