"""Settings dialog: proxy, cookies, paths, concurrency, playlist, expert."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置")
        self.resize(640, 520)

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._build_network_tab(), "网络")
        tabs.addTab(self._build_cookies_tab(), "Cookie")
        tabs.addTab(self._build_download_tab(), "下载")
        tabs.addTab(self._build_playlist_tab(), "播放列表")
        tabs.addTab(self._build_youtube_tab(), "YouTube")
        tabs.addTab(self._build_expert_tab(), "高级")
        root.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ---------------------------------------------------- tabs

    def _build_network_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("代理（留空 = 不使用）"))
        self.proxy_edit = QLineEdit(self.settings.proxy)
        self.proxy_edit.setPlaceholderText(
            "例如: socks5://127.0.0.1:1080  或  http://user:pass@host:port"
        )
        lay.addWidget(self.proxy_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("Socket 超时（秒）:"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setValue(self.settings.socket_timeout)
        row.addWidget(self.timeout_spin)
        row.addStretch(1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("限速（KB/s, 0=不限）:"))
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(0, 200_000)
        self.rate_spin.setValue(self.settings.rate_limit_kbps)
        row.addWidget(self.rate_spin)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addStretch(1)
        return w

    def _build_cookies_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("从浏览器导入 Cookie（推荐）"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(
            ["", "chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi", "safari"]
        )
        self.browser_combo.setCurrentText(self.settings.cookies_from_browser)
        lay.addWidget(self.browser_combo)

        lay.addSpacing(12)
        lay.addWidget(QLabel("或加载 cookies.txt 文件"))
        row = QHBoxLayout()
        self.cookies_edit = QLineEdit(self.settings.cookies_file)
        pick = QPushButton("选择…")
        pick.clicked.connect(self._pick_cookies_file)
        row.addWidget(self.cookies_edit)
        row.addWidget(pick)
        lay.addLayout(row)

        lay.addWidget(QLabel(
            "<span style='color:#888'>注：如两处都填，将优先使用浏览器 Cookie。</span>"
        ))

        lay.addStretch(1)
        return w

    def _build_download_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("下载目录"))
        row = QHBoxLayout()
        self.outdir_edit = QLineEdit(self.settings.output_dir)
        pick = QPushButton("选择…")
        pick.clicked.connect(self._pick_outdir)
        row.addWidget(self.outdir_edit)
        row.addWidget(pick)
        lay.addLayout(row)

        lay.addWidget(QLabel("文件名模板 (yt-dlp -o)"))
        self.tpl_edit = QLineEdit(self.settings.output_template)
        lay.addWidget(self.tpl_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("最大并发下载数:"))
        self.conc_spin = QSpinBox()
        self.conc_spin.setRange(1, 10)
        self.conc_spin.setValue(self.settings.max_concurrent)
        row.addWidget(self.conc_spin)
        row.addStretch(1)
        lay.addLayout(row)

        self.archive_cb = QCheckBox("启用去重档案 (archive.txt) — 跳过已下载资源")
        self.archive_cb.setChecked(self.settings.use_archive)
        lay.addWidget(self.archive_cb)

        lay.addStretch(1)
        return w

    def _build_playlist_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("下载播放列表条目之间的随机延迟（秒）"))
        row = QHBoxLayout()
        row.addWidget(QLabel("最小:"))
        self.sleep_min_spin = QSpinBox()
        self.sleep_min_spin.setRange(0, 600)
        self.sleep_min_spin.setValue(self.settings.sleep_interval)
        row.addWidget(self.sleep_min_spin)
        row.addWidget(QLabel("最大:"))
        self.sleep_max_spin = QSpinBox()
        self.sleep_max_spin.setRange(0, 600)
        self.sleep_max_spin.setValue(self.settings.max_sleep_interval)
        row.addWidget(self.sleep_max_spin)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(QLabel(
            "<span style='color:#888'>提示：某些站点会限流，加个 2-8 秒的随机延迟能显著降低被封风险。</span>"
        ))

        lay.addStretch(1)
        return w

    def _build_youtube_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.yt_compat_cb = QCheckBox(
            "启用 YouTube 兼容模式（推荐，绕开 'The page needs to be reloaded' 错误）"
        )
        self.yt_compat_cb.setChecked(self.settings.youtube_compat)
        lay.addWidget(self.yt_compat_cb)

        lay.addWidget(QLabel("player_client 回退顺序（逗号分隔）:"))
        self.yt_clients_edit = QLineEdit(self.settings.youtube_player_clients)
        self.yt_clients_edit.setPlaceholderText("default,tv,mweb")
        lay.addWidget(self.yt_clients_edit)

        lay.addWidget(QLabel(
            "<span style='color:#888'>"
            "常见组合：<br>"
            "&nbsp;&nbsp;• <code>default,tv,mweb</code>（推荐，覆盖大部分场景）<br>"
            "&nbsp;&nbsp;• <code>tv,web_safari,mweb</code>（web 客户端被限流时的备选）<br>"
            "&nbsp;&nbsp;• <code>tv_embedded</code>（年龄限制视频）<br><br>"
            "如果多次尝试都失败，请通过工具栏的 <b>“检查/下载 yt-dlp、ffmpeg”</b> 更新到最新版本 "
            "—— YouTube 反爬变化频繁，yt-dlp 通常几天内就会跟进修复。"
            "</span>"
        ))

        lay.addStretch(1)
        return w

    def _build_expert_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(
            "附加原始 yt-dlp 参数（每行一个），会追加到命令行末尾（URL 之前）"
        ))
        self.extra_edit = QPlainTextEdit()
        self.extra_edit.setPlainText("\n".join(self.settings.extra_args))
        self.extra_edit.setPlaceholderText("--geo-bypass\n--force-ipv4\n...")
        lay.addWidget(self.extra_edit)
        return w

    # ---------------------------------------------------- pickers

    def _pick_cookies_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "选择 cookies.txt", "", "Cookies (*.txt);;All (*)"
        )
        if f:
            self.cookies_edit.setText(f)

    def _pick_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择下载目录", self.outdir_edit.text())
        if d:
            self.outdir_edit.setText(d)

    # ---------------------------------------------------- accept

    def _accept(self) -> None:
        s = self.settings
        s.proxy = self.proxy_edit.text().strip()
        s.socket_timeout = self.timeout_spin.value()
        s.rate_limit_kbps = self.rate_spin.value()
        s.cookies_from_browser = self.browser_combo.currentText().strip()
        s.cookies_file = self.cookies_edit.text().strip()
        s.output_dir = self.outdir_edit.text().strip() or s.output_dir
        s.output_template = self.tpl_edit.text().strip() or s.output_template
        s.max_concurrent = self.conc_spin.value()
        s.use_archive = self.archive_cb.isChecked()
        s.sleep_interval = self.sleep_min_spin.value()
        s.max_sleep_interval = self.sleep_max_spin.value()
        s.youtube_compat = self.yt_compat_cb.isChecked()
        s.youtube_player_clients = self.yt_clients_edit.text().strip() or "default,tv,mweb"
        s.extra_args = [
            ln.strip() for ln in self.extra_edit.toPlainText().splitlines() if ln.strip()
        ]
        s.save()
        self.accept()
