"""Queue table view with a progress-bar delegate."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QMenu,
    QStyle,
    QStyleOptionProgressBar,
    QStyledItemDelegate,
    QTableView,
)

from app.core.download_manager import DownloadManager
from app.core.download_task import TaskStatus


# ------------------------------------------------------------------ helpers

_STATUS_LABEL = {
    TaskStatus.QUEUED: "排队中",
    TaskStatus.RUNNING: "下载中",
    TaskStatus.PAUSED: "已暂停",
    TaskStatus.DONE: "已完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.CANCELED: "已取消",
}


def _fmt_size(n: int | None) -> str:
    if not n:
        return "-"
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _fmt_speed(bps: float | None) -> str:
    if not bps:
        return "-"
    return _fmt_size(int(bps)) + "/s"


def _fmt_eta(sec: int | None) -> str:
    if sec is None:
        return "-"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


# ------------------------------------------------------------------- model

COL_TITLE, COL_SIZE, COL_PROGRESS, COL_SPEED, COL_ETA, COL_STATUS = range(6)
_HEADERS = ("标题", "大小", "进度", "速度", "剩余", "状态")


class QueueModel(QAbstractTableModel):
    def __init__(self, mgr: DownloadManager) -> None:
        super().__init__()
        self._mgr = mgr
        mgr.task_added.connect(self._on_added)
        mgr.task_updated.connect(self._on_updated)
        mgr.task_finished.connect(self._on_updated)

    # ------ Qt boilerplate ------

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self._mgr.tasks())

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(_HEADERS)

    def headerData(self, section: int, orient: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orient == Qt.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        tasks = self._mgr.tasks()
        if index.row() >= len(tasks):
            return None
        st = tasks[index.row()].state
        col = index.column()

        if role == Qt.UserRole:
            # Progress delegate reads (percent, index_label, pct_label).
            if col == COL_PROGRESS:
                pct = st.percent if st.percent is not None else -1.0
                if st.status == TaskStatus.DONE:
                    pct = 100.0
                pct_txt = f"{pct:.1f}%" if pct >= 0 else "--"
                if st.is_playlist:
                    if st.status == TaskStatus.DONE and st.playlist_count:
                        idx_txt = str(st.playlist_count)
                    else:
                        idx_txt = str(st.playlist_index) if st.playlist_index else "?"
                    cnt_txt = str(st.playlist_count) if st.playlist_count else "?"
                    index_label = f"[{idx_txt}/{cnt_txt}]"
                else:
                    index_label = ""
                return (pct, index_label, pct_txt)
            return None

        if role == Qt.DisplayRole:
            if col == COL_TITLE:
                return self._title_display(st)
            if col == COL_SIZE:
                return _fmt_size(st.size_display)
            if col == COL_SPEED:
                return _fmt_speed(st.speed) if st.status == TaskStatus.RUNNING else "-"
            if col == COL_ETA:
                return _fmt_eta(st.eta) if st.status == TaskStatus.RUNNING else "-"
            if col == COL_STATUS:
                return self._status_display(st)

        if role == Qt.ToolTipRole and col == COL_TITLE:
            parts = []
            if st.is_playlist:
                parts.append(f"合集: {st.title}")
            parts.append(st.output_path or st.url)
            if st.error:
                parts.append("错误: " + st.error)
            return "\n".join(parts)

        return None

    # -------- display helpers --------

    @staticmethod
    def _title_display(st) -> str:
        # For playlists, always show the (stable) playlist name — per-video
        # titles from progress events / filenames can flap during multi-stream
        # downloads and were causing garbled text mid-run.
        if not st.is_playlist:
            return st.title
        if st.playlist_index and st.playlist_count:
            return f"[合集 {st.playlist_index}/{st.playlist_count}] {st.title}"
        return f"[合集] {st.title}"

    @staticmethod
    def _status_display(st) -> str:
        return _STATUS_LABEL.get(st.status, st.status.value)

    # ------ helpers ------

    def task_at(self, row: int):
        tasks = self._mgr.tasks()
        return tasks[row] if 0 <= row < len(tasks) else None

    def _on_added(self, _tid: str) -> None:
        self.beginResetModel()
        self.endResetModel()

    def _on_updated(self, tid: str) -> None:
        for row, t in enumerate(self._mgr.tasks()):
            if t.state.task_id == tid:
                self.dataChanged.emit(
                    self.index(row, 0),
                    self.index(row, self.columnCount() - 1),
                )
                return

    def reset_all(self) -> None:
        self.beginResetModel()
        self.endResetModel()


# ---------------------------------------------------------------- delegate

class ProgressDelegate(QStyledItemDelegate):
    """Renders `[i/n]` as a left-aligned label and the progress bar to its
    right. Single-video rows have no index label; the bar takes the full cell.
    """

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        payload = index.data(Qt.UserRole)
        if not payload:
            super().paint(painter, option, index)
            return

        pct, index_label, pct_label = payload
        painter.save()
        cell = option.rect.adjusted(4, 3, -4, -3)

        # Left label (playlist index only)
        if index_label:
            fm = painter.fontMetrics()
            label_w = fm.horizontalAdvance(index_label) + 8
            label_rect = QRect(cell.left(), cell.top(), label_w, cell.height())
            painter.drawText(
                label_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                index_label,
            )
            bar_rect = QRect(
                cell.left() + label_w + 4,
                cell.top(),
                max(0, cell.width() - label_w - 4),
                cell.height(),
            )
        else:
            bar_rect = cell

        opt = QStyleOptionProgressBar()
        opt.rect = bar_rect
        opt.minimum = 0
        opt.maximum = 100
        opt.progress = max(0, int(pct))
        opt.text = pct_label
        opt.textVisible = True
        QApplication.style().drawControl(QStyle.CE_ProgressBar, opt, painter)
        painter.restore()


# ------------------------------------------------------------------ view

class QueueView(QTableView):
    pause_requested = Signal(str)
    resume_requested = Signal(str)
    cancel_requested = Signal(str)
    remove_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, mgr: DownloadManager, parent=None) -> None:
        super().__init__(parent)
        self._mgr = mgr
        self._model = QueueModel(mgr)
        self.setModel(self._model)
        self.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self))
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)

        h = self.horizontalHeader()
        # All columns user-resizable; title stretches to fill remainder.
        for c in range(len(_HEADERS)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.setStretchLastSection(False)
        h.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        h.setMinimumSectionSize(60)

        # Reasonable defaults so nothing gets truncated on first show.
        default_widths = {
            COL_TITLE: 340,
            COL_SIZE: 90,
            COL_PROGRESS: 220,
            COL_SPEED: 100,
            COL_ETA: 80,
            COL_STATUS: 90,
        }
        for c, w in default_widths.items():
            self.setColumnWidth(c, w)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

    def _selected_task_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[int] = set()
        for idx in self.selectionModel().selectedIndexes():
            if idx.row() in seen:
                continue
            seen.add(idx.row())
            t = self._model.task_at(idx.row())
            if t:
                ids.append(t.state.task_id)
        return ids

    def _on_menu(self, pos: QPoint) -> None:
        ids = self._selected_task_ids()
        if not ids:
            return
        menu = QMenu(self)
        act_pause = QAction("暂停", menu)
        act_resume = QAction("继续 / 重试", menu)
        act_cancel = QAction("取消", menu)
        act_remove = QAction("从列表移除", menu)
        act_open = QAction("打开所在文件夹", menu)

        act_pause.triggered.connect(lambda: [self.pause_requested.emit(i) for i in ids])
        act_resume.triggered.connect(lambda: [self.resume_requested.emit(i) for i in ids])
        act_cancel.triggered.connect(lambda: [self.cancel_requested.emit(i) for i in ids])
        act_remove.triggered.connect(lambda: [self.remove_requested.emit(i) for i in ids])
        act_open.triggered.connect(lambda: [self.open_folder_requested.emit(i) for i in ids])

        menu.addAction(act_pause)
        menu.addAction(act_resume)
        menu.addAction(act_cancel)
        menu.addSeparator()
        menu.addAction(act_open)
        menu.addAction(act_remove)
        menu.exec(self.viewport().mapToGlobal(pos))

    def refresh(self) -> None:
        self._model.reset_all()
