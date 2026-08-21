"""Main application window: URL bar, toolbar, queue table, status bar."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.core.download_manager import DownloadManager
from app.core.download_task import DownloadTask, TaskStatus
from app.core.format_parser import DownloadSelection, MediaInfo
from app.core.probe import UrlProbe
from app.core.settings import AppSettings
from app.ui.format_dialog import FormatDialog
from app.ui.queue_view import QueueView
from app.ui.settings_dialog import SettingsDialog
from app.utils import paths, updater


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("yt-dlp UI")
        self.resize(1080, 640)

        self.settings = AppSettings.load()
        self.manager = DownloadManager(self.settings, self)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self.manager.task_updated.connect(lambda _tid: self._refresh_status())
        self.manager.task_added.connect(lambda _tid: self._refresh_status())
        self.manager.task_finished.connect(lambda _tid: self._refresh_status())

        # Periodic refresh for speed/eta smoothing even without events.
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_status)
        self._tick.start()

        QTimer.singleShot(300, self._first_run_check)

    # ---------------------------------------------------------------- UI

    def _build_toolbar(self) -> None:
        tb = QToolBar("main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        self.act_settings = QAction("设置", self)
        self.act_settings.triggered.connect(self._open_settings)
        tb.addAction(self.act_settings)

        self.act_update = QAction("检查/下载 yt-dlp、ffmpeg", self)
        self.act_update.triggered.connect(self._download_binaries)
        tb.addAction(self.act_update)

        tb.addSeparator()

        self.act_clear = QAction("清除已完成", self)
        self.act_clear.triggered.connect(self._clear_finished)
        tb.addAction(self.act_clear)

    def _build_central(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)

        # URL row
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("粘贴视频 / 播放列表链接，回车 = 解析")
        self.url_edit.returnPressed.connect(self._on_parse)
        url_row.addWidget(self.url_edit, 1)

        btn_paste = QPushButton("从剪贴板")
        btn_paste.clicked.connect(self._paste_from_clipboard)
        url_row.addWidget(btn_paste)

        btn_parse = QPushButton("解析")
        btn_parse.clicked.connect(self._on_parse)
        url_row.addWidget(btn_parse)

        btn_quick = QPushButton("直接下载 (最佳)")
        btn_quick.clicked.connect(self._on_quick_download)
        url_row.addWidget(btn_quick)

        root.addLayout(url_row)

        # Queue view
        self.queue = QueueView(self.manager, self)
        self.queue.pause_requested.connect(self.manager.pause)
        self.queue.resume_requested.connect(self.manager.resume)
        self.queue.cancel_requested.connect(self.manager.cancel)
        self.queue.remove_requested.connect(self.manager.remove)
        self.queue.open_folder_requested.connect(self._open_folder)
        root.addWidget(self.queue, 1)

        self.setCentralWidget(central)

    def _build_statusbar(self) -> None:
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.status_label = QLabel("就绪")
        self.status.addPermanentWidget(self.status_label)

    # ------------------------------------------------------------- probe

    def _paste_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)

    def _on_parse(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        if paths.ytdlp_exe() is None:
            self._prompt_download_ytdlp()
            return

        # Disable button; show a modal progress dialog.
        self._probe_dlg = QProgressDialog("正在解析 URL…", "取消", 0, 0, self)
        self._probe_dlg.setWindowTitle("解析中")
        self._probe_dlg.setWindowModality(Qt.WindowModal)
        self._probe_dlg.setMinimumDuration(0)

        self._probe = UrlProbe(url, self.settings, self)
        self._probe.ready.connect(self._on_probe_ready)
        self._probe.failed.connect(self._on_probe_failed)
        self._probe_dlg.canceled.connect(self._probe._runner.cancel)  # noqa: SLF001
        self._probe.start()

    def _on_probe_ready(self, info: MediaInfo) -> None:
        self._probe_dlg.close()

        if info.is_playlist:
            self._enqueue_playlist(info)
            return

        dlg = FormatDialog(info, self)
        if dlg.exec() != FormatDialog.Accepted:
            return
        self._enqueue(info.url, info.title, dlg.selection(), is_playlist=False)

    def _on_probe_failed(self, msg: str) -> None:
        self._probe_dlg.close()

        low = msg.lower()
        is_cookie_lock = (
            "could not copy" in low and "cookie" in low
        ) or ("锁定" in msg and "cookie" in low)
        is_yt_reload = "page needs to be reloaded" in low or (
            "youtube" in low and "reload" in low
        )

        if is_cookie_lock:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Cookie 数据库被锁定")
            box.setText("无法从浏览器读取 Cookie。")
            box.setInformativeText(msg)
            open_settings_btn = box.addButton(
                "打开设置 → 使用 cookies.txt", QMessageBox.AcceptRole
            )
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_settings_btn:
                self._open_settings()
            return

        if is_yt_reload:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("YouTube 反爬拦截")
            box.setText("YouTube 返回 'The page needs to be reloaded'。")
            box.setInformativeText(
                "这是 YouTube 近期升级的反自动化机制。建议按顺序尝试：\n\n"
                "  1. 【立即】更新 yt-dlp 到最新版本 —— 官方通常几天内跟进修复\n"
                "  2. 打开 设置 → YouTube，确认 兼容模式 已开启，并把 "
                "player_client 改为 <tv,web_safari,mweb> 试试\n"
                "  3. 如果使用了已登录 YouTube 的 cookies，尝试改用未登录会话的 "
                "cookies（或暂时不用 cookie）\n"
                "  4. 换个 URL 或稍等几分钟再试（限流通常短时间恢复）\n\n"
                f"原始错误：\n{msg}"
            )
            update_btn = box.addButton("立即更新 yt-dlp", QMessageBox.AcceptRole)
            settings_btn = box.addButton("打开 YouTube 设置", QMessageBox.ActionRole)
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is update_btn:
                self._download_binaries()
            elif clicked is settings_btn:
                self._open_settings()
            return

        QMessageBox.warning(self, "解析失败", msg)

    def _on_quick_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        if paths.ytdlp_exe() is None:
            self._prompt_download_ytdlp()
            return
        sel = DownloadSelection()  # defaults: bv*+ba/best
        self._enqueue(url, url, sel, is_playlist=False)

    # ------------------------------------------------------------ enqueue

    def _enqueue(
        self,
        url: str,
        title: str,
        sel: DownloadSelection,
        is_playlist: bool,
        playlist_items: str = "",
        entry_titles: list[str] | None = None,
    ) -> None:
        task = DownloadTask(
            url=url,
            selection=sel,
            settings=self.settings,
            title=title,
            is_playlist=is_playlist,
            playlist_items=playlist_items,
            entry_titles=entry_titles,
            parent=self,
        )
        self.manager.add(task)
        self.url_edit.clear()

    def _enqueue_playlist(self, info: MediaInfo) -> None:
        n = len(info.entries)
        rng, ok = QInputDialog.getText(
            self,
            f"播放列表 ({n} 项)",
            f"该链接是播放列表，共 {n} 项。\n"
            f"输入要下载的条目范围（例如 1-{min(n,10)} 或留空 = 全部）:",
            text=f"1-{min(n, 10)}" if n > 10 else "",
        )
        if not ok:
            return
        sel = DownloadSelection()   # use best quality by default for batch
        # Full titles pre-fetched from the JSON dump — the authoritative
        # source for per-video titles at display time (progress events'
        # info.title is unreliable across streams).
        entry_titles = [t for t, _u in info.entries]
        self._enqueue(
            url=info.url,
            title=info.title,
            sel=sel,
            is_playlist=True,
            playlist_items=rng.strip(),
            entry_titles=entry_titles,
        )

    # ----------------------------------------------------------- toolbar

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        dlg.exec()

    def _clear_finished(self) -> None:
        self.manager.clear_finished()
        self.queue.refresh()

    def _open_folder(self, task_id: str) -> None:
        t = self.manager.get(task_id)
        if not t:
            return
        # Prefer the recorded output path, but it may point to an intermediate
        # file (e.g. .f30064.mp4) that yt-dlp deleted after merging. Walk up
        # until we find a directory that exists; fall back to the configured
        # download directory.
        candidate = Path(t.state.output_path) if t.state.output_path else None
        folder: Path | None = None
        if candidate and candidate.exists():
            folder = candidate if candidate.is_dir() else candidate.parent
        elif candidate:
            walk = candidate.parent
            while walk != walk.parent and not walk.exists():
                walk = walk.parent
            if walk.exists():
                folder = walk
        if folder is None:
            folder = Path(self.settings.output_dir)
            folder.mkdir(parents=True, exist_ok=True)

        if os.name == "nt":
            os.startfile(str(folder))   # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    # -------------------------------------------------------------- misc

    def _refresh_status(self) -> None:
        tasks = self.manager.tasks()
        running = [t for t in tasks if t.state.status == TaskStatus.RUNNING]
        speed = sum((t.state.speed or 0) for t in running)
        self.status_label.setText(
            f"任务: {len(tasks)}   活跃: {len(running)}/{self.settings.max_concurrent}"
            f"   总速: {self._fmt_speed(speed)}"
        )

    @staticmethod
    def _fmt_speed(bps: float) -> str:
        if bps <= 0:
            return "0 B/s"
        f = bps
        for u in ("B", "KB", "MB", "GB"):
            if f < 1024:
                return f"{f:.1f} {u}/s"
            f /= 1024
        return f"{f:.1f} TB/s"

    # ----------------------------------------------------------- first-run

    def _first_run_check(self) -> None:
        if paths.ytdlp_exe() is None:
            self._prompt_download_ytdlp()

    def _prompt_download_ytdlp(self) -> None:
        ret = QMessageBox.question(
            self,
            "未找到 yt-dlp.exe",
            "程序目录下的 bin/yt-dlp.exe 不存在。\n是否现在从官方 GitHub 下载？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._download_binaries()

    def _download_binaries(self) -> None:
        # Blocking download with a progress dialog; keeps things simple.
        dlg = QProgressDialog("正在下载 yt-dlp.exe…", None, 0, 100, self)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)

        def cb(done: int, total: int) -> None:
            if total > 0:
                dlg.setValue(int(done * 100 / total))
            QGuiApplication.processEvents()

        try:
            updater.download_ytdlp(cb)
        except Exception as e:                            # noqa: BLE001
            dlg.close()
            QMessageBox.critical(self, "下载失败", f"下载 yt-dlp.exe 失败：{e}")
            return

        dlg.setLabelText("正在下载 ffmpeg (essentials)…")
        dlg.setValue(0)
        try:
            updater.download_ffmpeg(cb)
        except Exception as e:                            # noqa: BLE001
            dlg.close()
            QMessageBox.warning(
                self,
                "ffmpeg 下载失败",
                f"ffmpeg 下载失败（不影响单格式下载）：{e}\n"
                "你可以自行放置 ffmpeg.exe 到 bin/ 目录。",
            )
            return

        dlg.close()
        QMessageBox.information(self, "完成", "yt-dlp.exe 与 ffmpeg.exe 已就绪。")
