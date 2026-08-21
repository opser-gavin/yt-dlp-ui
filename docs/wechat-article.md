# 告别命令行：给 yt-dlp 套一个人人能用的 Windows 客户端

> 视频下载工具 yt-dlp 早已封神——1800 多个站点全通吃，YouTube、Bilibili、Twitter、TikTok、抖音、快手、Twitch、SoundCloud、爱奇艺、腾讯视频……只要能在浏览器打开的视频，它多半就能扒下来。
>
> 但它是**命令行工具**，几十个参数、几百页文档。对不会写代码的朋友，光看它的 `--help` 就头大。
>
> 于是我用一个周末给它做了个图形化外壳：**yt-dlp UI**——把最常用的能力全部可视化，粘贴链接、勾几个选项、点下载，就这么简单。

---

## 一、它长这样

**主界面**：URL 栏 + 下载队列 + 设置入口，一眼看全。

![主界面](https://github.com/user-attachments/assets/e8e549f3-18f0-45ec-8681-c81ead3cef5e)

**解析后弹窗**：所有可选的画质、音质、字幕都摊开给你勾。

![格式选择](https://github.com/user-attachments/assets/eb9745aa-cc6d-4fc3-a7b6-065063c478c7)

**Cookie 设置**：从浏览器直接读，或者用 cookies.txt 文件。

![Cookie 设置](https://github.com/user-attachments/assets/f8627bf5-9da0-436c-ad5d-99870a2d374c)

---

## 二、都能干什么

### 🌐 代理设置一键搞定

支持 HTTP / SOCKS5 / SOCKS5H：

```
socks5://127.0.0.1:1080
http://user:pass@proxy.example.com:8080
```

翻墙站点（YouTube、Twitter）和限流站点（B 站会员视频）都好用。

### 🎬 智能格式选择

粘贴链接点"解析"，弹窗里能看到：

- **视频轨**：所有分辨率 × 码率 × 编码组合（1080p AV1、720p H.264 各分辨清楚）
- **音频轨**：不同码率的 M4A / Opus / MP3
- **字幕**：所有可用语言 + 平台自动生成的字幕

勾选你要的，一次搞定。如果只要音频（比如把演唱会视频扒成 MP3），勾"仅音频"就行。

### 📋 多任务队列

- 实时进度条、速度、剩余时间
- 支持**暂停/继续**——用 yt-dlp 的 `--continue` 断点续传
- 最大并发数可配置（默认 3）
- 完成后右键"打开所在文件夹"

### 📚 合集批量下载

粘贴 B 站分 P 视频、YouTube 播放列表、Bilibili 系列合集的链接：

```
下载目录\
└── 经典老歌系列大合集（港台篇）\   ← 自动按合集名建目录
    ├── 张宇-月亮惹的祸.mp4
    ├── 王杰-一场游戏一场梦.mp4
    ├── 李宗盛-爱的代价.mp4
    └── ...
```

进度列显示 `[3/10] 32%`，一目了然。

### 🍪 Cookie 支持

需要登录的资源（B 站会员视频、YouTube 私享、抖音仅关注可见……）：

- **方式 1**：从浏览器直接读（Chrome / Edge / Firefox / Brave）
- **方式 2**：用扩展导出 cookies.txt 再加载（推荐 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)）

### 🛡️ YouTube 反爬兼容模式（默认开启）

YouTube 近期升级了反机器人策略，`web` 客户端经常报 `The page needs to be reloaded`。UI 里默认帮你加了：

```
--extractor-args "youtube:player_client=default,tv,mweb"
```

一次不行就自动换客户端重试，成功率高很多。

### 🔄 自动更新 yt-dlp 与 ffmpeg

工具栏里"检查/下载 yt-dlp、ffmpeg"一键：

- yt-dlp.exe 从官方 GitHub Releases 拉最新
- ffmpeg 从 gyan.dev 拉 essentials 构建
- 首次启动自动检测，没有就弹窗询问下载

YouTube 反爬变了、B 站接口改了？点一下更新，通常几天内官方就跟进修复。

---

## 三、支持哪些站点

**理论上 yt-dlp 支持的站点它都支持**，超过 1800 个。常见的国内外站点：

| 类型 | 站点 |
|---|---|
| 视频 | YouTube · Bilibili · Twitch · Vimeo · DailyMotion · TikTok · 抖音 · 快手 · 微博 |
| 直播回放 | Twitch · YouTube Live · Bilibili Live |
| 音频 | SoundCloud · Bandcamp · Mixcloud |
| 影视 | 爱奇艺 · 腾讯视频 · 优酷（部分需 cookie） |
| 教育 | Coursera · Khan Academy · edX · B 站课堂 |
| 成人 | Pornhub · XVideos · 各类 tube 站点（需登录时靠 cookie） |

完整列表看 yt-dlp 官方：<https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md>

---

## 四、怎么用

### 下载安装

**方式 1：直接跑源码**（推荐给会 Python 的朋友，方便更新）

```powershell
git clone https://github.com/opser-gavin/yt-dlp-ui.git
cd yt-dlp-ui
pip install -r requirements.txt
python -m app.main
```

**方式 2：打包成单 exe**

```powershell
pip install pyinstaller
pyinstaller build.spec
# 产物在 dist/yt-dlp-ui.exe
```

首次启动会检测 `yt-dlp.exe` / `ffmpeg.exe`，没有就弹窗一键下载。

### 基本流程

1. 粘贴视频/合集 URL
2. 点"解析" → 弹窗勾选画质字幕 → 确定
3. 队列开始下载，看着进度条走就完事
4. 完成后右键"打开所在文件夹"

想更快就点"直接下载 (最佳)"，跳过弹窗、按最高画质 + 最高音质合并。

---

## 五、技术实现（对代码感兴趣的朋友）

**技术栈**：
- **Python 3.11+** + **PySide6 (Qt6)**——原生 Windows 观感，跨平台，Python 生态成熟
- **QProcess** 调用捆绑的 `yt-dlp.exe`——非阻塞进度回调，Qt 事件循环无缝集成
- **自定义 progress-template** 实时解析下载事件，字段级更新表格

**几个有意思的坑**：

1. **Chrome cookie 数据库被锁**——Chrome 用了 `FILE_SHARE_NONE` 独占锁，`shutil` 拷不出来。三重回退：`shutil.copy2` → `esentutl.exe /y`（Windows 系统自带的 backup semantics 拷贝）→ `sqlite3.connect("...?immutable=1")` + `Connection.backup()` API。绝大部分场景能自动绕开。

2. **中文标题乱码**——`QProcess` 每次给的 stdout 字节块边界随意，如果我拿到就 `.decode('utf-8')`，一个中文字符 3 字节被切在中间就变 `�`。改成**字节级缓冲，只在换行符处切开再解码**，中文 100% 完整。

3. **文件名 ASCII 化的坑**——`--restrict-filenames` 会删掉所有非 ASCII，`【MTV精选】张宇-月亮惹的祸` 变成 `MTV_`。改用 `--windows-filenames` 只处理 Windows 保留字符，Unicode 原样保留。

4. **合集大小累积**——单个视频常有 video 轨 + audio 轨两个下载流，如果用 `total` 字段累加会被后一个流覆盖导致数字缩水。改成**每个流 finished 时银行入 per-video 桶，视频切换时晋升到 completed 桶**，`size = completed + current_video + downloading` 就永远单调增长。

代码全开源，欢迎 PR：<https://github.com/opser-gavin/yt-dlp-ui>

---

## 六、常见问题

**Q：Chrome 用户 Cookie 老失败？**
A：先试关闭 Chrome 所有进程（含托盘图标）后重试；不行就用 `Get cookies.txt LOCALLY` 扩展导出 `.txt` 用文件方式。

**Q：YouTube 报 "page needs to be reloaded"？**
A：先点工具栏更新一下 yt-dlp。还不行就到 设置 → YouTube 换个 `player_client` 组合（比如 `tv,web_safari,mweb`）。

**Q：B 站分 P 合集，文件名一大串合集名？**
A：默认已经加了 `--replace-in-metadata` 剥离 `<合集名> p<数字> ` 前缀，如果你的版本还没生效，git pull 拉最新代码。

**Q：能下 4K 吗？8K 呢？**
A：能。只要平台提供了对应格式，解析弹窗里就会列出来，勾就是。

**Q：会员视频能下吗？**
A：能，前提是你的账号有权限：先在浏览器登录、把 Cookie 导入 UI，就跟普通视频一样下。

---

## 七、声明

本项目仅是 yt-dlp 的图形前端，**核心下载能力来自 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 开源项目**。请遵守目标站点的服务条款与所在地法律法规，仅在被授权的范围内下载内容。

---

## 结尾

如果这个小工具帮到了你，欢迎去 GitHub 点个 Star：

**👉 https://github.com/opser-gavin/yt-dlp-ui**

有想法、有 bug、有需求，直接开 Issue 或 PR。也欢迎转发给身边被"电脑上下载视频"折磨过的朋友。

下一步的计划：
- [ ] 深色主题
- [ ] 系统托盘常驻 + 剪贴板自动识别
- [ ] 更多站点的一键场景预设（B 站番剧、YouTube Music、播客等）

有想加的功能，评论区告诉我。
