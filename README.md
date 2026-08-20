# yt-dlp UI (Windows)

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 官方 Windows 二进制的图形化客户端。用 Python + PySide6 (Qt6) 编写，通过 `QProcess` 调用 `yt-dlp.exe`。

## 功能

- 代理设置（HTTP / SOCKS5）、限速、超时
- 从浏览器（Edge/Chrome/Firefox/…）导入 Cookie 或加载 `cookies.txt`
- 解析 URL 后弹窗展示所有可选**视频/音频轨、字幕语言**，勾选后下载
- **仅音频提取**（`--extract-audio` → MP3/M4A/Opus/…）
- 下载**队列**：进度条 / 速度 / 剩余时间 / 暂停 / 恢复 / 取消
  - "暂停"实现方式：kill 子进程 + 复用 `.part` 文件；"恢复"用 `--continue` 断点续传
- **播放列表批量下载**（`--yes-playlist` / `--playlist-items`，含站点限流保护的随机延迟）
- 去重档案（`--download-archive`）避免重复下载
- 首次运行自动从 GitHub Releases 下载 `yt-dlp.exe` 与 ffmpeg essentials

## 目录结构

```
yt-dlp-ui/
├── app/
│   ├── main.py
│   ├── core/     # ytdlp_runner / format_parser / progress_parser / download_task / download_manager / probe / settings
│   ├── ui/       # main_window / format_dialog / settings_dialog / queue_view
│   └── utils/    # paths / updater
├── bin/          # 运行时存放 yt-dlp.exe / ffmpeg.exe
├── build.spec    # PyInstaller 打包配置
└── requirements.txt
```

## 开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

首次启动会检测 `bin/yt-dlp.exe` 是否存在，若无则弹窗询问下载。

## 打包为单 exe

```powershell
pip install pyinstaller
# 手动或首次运行程序后，让 bin/ 目录下有 yt-dlp.exe 和 ffmpeg.exe
pyinstaller build.spec
# 产物: dist/yt-dlp-ui.exe
```

## 配置文件

保存在 `%APPDATA%\yt-dlp-ui\config.json`。删除该文件即可恢复默认。

## 常见场景

**下载 YouTube 1080p + 中文字幕**
1. 粘贴视频链接，点"解析"
2. 视频轨选一个 `1080p`；音频轨选码率最高的 `m4a/opus`
3. 字幕勾选 `zh` 与 `zh-Hans`，保留"内嵌字幕"
4. 确定后加入队列

**下载 B 站会员视频**
1. 在设置 → Cookie 中选择 `edge` (先在 Edge 浏览器登录 B 站)
2. 保存后即可像普通视频那样下载

**批量下载 YouTube 播放列表前 10 项**
1. 粘贴播放列表链接，点"解析"
2. 弹窗中输入范围 `1-10`

## 效果预览
直接下载最佳效果
<img width="1073" height="356" alt="image" src="https://github.com/user-attachments/assets/e8e549f3-18f0-45ec-8681-c81ead3cef5e" />
也可以先解析视频，选择想要的 画质、音轨、
<img width="1067" height="747" alt="image" src="https://github.com/user-attachments/assets/eb9745aa-cc6d-4fc3-a7b6-065063c478c7" />
cookie可以选择：
1 chrome等浏览器（这个要关闭浏览器要不会报错，因为chrome运行时会锁定cookie数据库）
2 用cookie保存插件（比如Get cookies.txt LOCALLY）
<img width="850" height="387" alt="image" src="https://github.com/user-attachments/assets/f8627bf5-9da0-436c-ad5d-99870a2d374c" />


## 授权提示

本项目仅是 yt-dlp 的图形前端。请遵守目标站点的服务条款与所在地法律法规，仅在被授权的范围内下载内容。
