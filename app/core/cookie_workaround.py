"""Workaround for the 'could not copy chrome cookie database' error on Windows.

Chromium-based browsers hold a file lock on ``Cookies`` (SQLite) while
running. yt-dlp tries the SQLite hot-backup API to snapshot it, which some
Chrome builds now block, producing::

    ERROR: could not copy chrome cookie database.
    (see https://github.com/yt-dlp/yt-dlp/issues/7271)

We stage a mini profile in a temp directory that mirrors the layout yt-dlp
expects, then point yt-dlp at *that* path via
``--cookies-from-browser <browser>:<staged_path>``.

Copying the locked file goes through several fallbacks:

1. ``shutil.copy2`` (works when the OS share mode allows read)
2. ``esentutl.exe /y … /d … /o`` — Windows built-in that opens files with
   backup semantics, bypassing many share-mode restrictions
3. ``sqlite3.connect(uri, immutable=1)`` + ``Connection.backup()`` — SQLite
   URI ``immutable=1`` disables ALL locking on the source, and the online
   backup API produces a clean copy at the destination

For ``Local State`` (a JSON file), only strategies 1 & 2 apply.

Staged layout::

    <workdir>/
    ├── Local State                # copy — holds the DPAPI-encrypted key
    └── <profile>/
        └── Network/
            └── Cookies            # copy of the SQLite DB
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

_CHROMIUM_LAYOUT: dict[str, tuple[str, str]] = {
    "chrome":   ("LOCALAPPDATA", r"Google\Chrome\User Data"),
    "edge":     ("LOCALAPPDATA", r"Microsoft\Edge\User Data"),
    "brave":    ("LOCALAPPDATA", r"BraveSoftware\Brave-Browser\User Data"),
    "chromium": ("LOCALAPPDATA", r"Chromium\User Data"),
    "vivaldi":  ("LOCALAPPDATA", r"Vivaldi\User Data"),
    "opera":    ("APPDATA",      r"Opera Software\Opera Stable"),
}


class CookieWorkaroundError(Exception):
    pass


def is_chromium(browser: str) -> bool:
    return browser.split("+", 1)[0].split(":", 1)[0].lower() in _CHROMIUM_LAYOUT


def _user_data_dir(browser: str) -> Path | None:
    env_var, sub = _CHROMIUM_LAYOUT[browser]
    root = os.environ.get(env_var)
    if not root:
        return None
    p = Path(root) / sub
    return p if p.exists() else None


def _cookie_source(user_data: Path, profile: str) -> Path | None:
    """Cookies file for a profile — try the new (Network/) then legacy path."""
    for c in (user_data / profile / "Network" / "Cookies",
              user_data / profile / "Cookies"):
        if c.exists():
            return c
    return None


# ------------------------------------------------------------ copy strategies

def _copy_plain(src: Path, dst: Path) -> bool:
    for attempt in range(3):
        try:
            shutil.copy2(src, dst)
            return True
        except PermissionError:
            time.sleep(0.15)
        except OSError:
            return False
    return False


def _copy_esentutl(src: Path, dst: Path) -> bool:
    """Use Windows ``esentutl.exe /y`` — copies with backup semantics.

    Works on many files that ``shutil`` cannot read due to Chrome's share
    mode; no admin required (does not need SeBackupPrivilege for read).
    """
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["esentutl.exe", "/y", str(src), "/d", str(dst), "/o"],
            capture_output=True,
            timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def _copy_sqlite_immutable(src: Path, dst: Path) -> bool:
    """Open source in SQLite ``immutable=1`` mode (no locks) and clone."""
    try:
        src_uri = f"{src.absolute().as_uri()}?immutable=1"
        # ``uri=True`` enables URI parsing; the immutable flag tells SQLite the
        # file cannot change, so no locks are taken.
        with sqlite3.connect(src_uri, uri=True) as sc:
            with sqlite3.connect(str(dst)) as dc:
                sc.backup(dc)
    except sqlite3.Error:
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return dst.exists() and dst.stat().st_size > 0


def _copy_locked(src: Path, dst: Path, is_sqlite: bool) -> None:
    """Try every strategy; raise :class:`PermissionError` if all fail."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    strategies = [_copy_plain, _copy_esentutl]
    if is_sqlite:
        strategies.append(_copy_sqlite_immutable)
    for strat in strategies:
        if strat(src, dst):
            return
    raise PermissionError(f"cannot copy locked file: {src}")


# ------------------------------------------------------------------- stage

def stage_profile(browser: str, profile: str = "Default") -> Path:
    """Copy the browser's cookie DB + Local State into a temp dir.

    Returns the *profile* directory path (the ``PROFILE`` part of
    ``--cookies-from-browser``). Raises :class:`CookieWorkaroundError` with
    a user-friendly message on failure.
    """
    if not is_chromium(browser):
        raise CookieWorkaroundError(
            f"未支持自动 Cookie 复制的浏览器: {browser}"
        )

    user_data = _user_data_dir(browser)
    if user_data is None:
        raise CookieWorkaroundError(
            f"未找到 {browser} 的用户数据目录，请确认已安装并至少启动过一次。"
        )

    src_cookies = _cookie_source(user_data, profile)
    if src_cookies is None:
        raise CookieWorkaroundError(
            f"未找到 {browser} 的 '{profile}' 配置文件下的 Cookies 数据库。"
        )

    src_local_state = user_data / "Local State"
    if not src_local_state.exists():
        raise CookieWorkaroundError(
            f"未找到 {browser} 的 'Local State'（DPAPI 密钥）。"
        )

    workdir = Path(tempfile.mkdtemp(prefix="ytdlpui_cookies_"))
    staged_profile = workdir / profile
    staged_cookies = staged_profile / "Network" / "Cookies"

    try:
        _copy_locked(src_cookies, staged_cookies, is_sqlite=True)
    except PermissionError as e:
        _cleanup(workdir)
        raise CookieWorkaroundError(
            "浏览器锁定了 Cookies 数据库，所有绕过策略均失败。\n"
            "请尝试以下解决方式：\n"
            "  1. 完全关闭浏览器（含托盘图标与后台进程）后再解析\n"
            "  2. 使用扩展导出 cookies.txt（推荐 'Get cookies.txt LOCALLY'），\n"
            "     然后在 设置 → Cookie → 加载 cookies.txt 文件"
        ) from e

    # Sidecar files improve consistency; failures are non-fatal.
    for suffix in ("-wal", "-shm"):
        side = src_cookies.with_name(src_cookies.name + suffix)
        if side.exists():
            try:
                _copy_locked(
                    side, staged_cookies.with_name(staged_cookies.name + suffix),
                    is_sqlite=False,
                )
            except PermissionError:
                pass  # backup DB is self-consistent enough without WAL

    try:
        _copy_locked(src_local_state, workdir / "Local State", is_sqlite=False)
    except PermissionError as e:
        _cleanup(workdir)
        raise CookieWorkaroundError(
            "无法读取 'Local State'（存有 Cookie 加密密钥），无法继续。\n"
            "请完全关闭浏览器后重试，或改用 cookies.txt 方式。"
        ) from e

    return staged_profile


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_temp_profile(profile_dir: Path | str | None) -> None:
    """Remove a temp profile dir created by :func:`stage_profile`."""
    if not profile_dir:
        return
    p = Path(profile_dir)
    root = p.parent
    if root.name.startswith("ytdlpui_cookies_"):
        _cleanup(root)


# ----------------------------------------------------------------- top API

def build_cookies_arg(
    cookies_from_browser: str,
) -> tuple[list[str], Path | None, str]:
    """Assemble the ``--cookies-from-browser`` args for yt-dlp.

    Returns ``(args, temp_profile_or_None, workaround_error)``.

    * ``args`` — pass to yt-dlp.
    * ``temp_profile_or_None`` — pass to :func:`cleanup_temp_profile` after
      the yt-dlp process finishes.
    * ``workaround_error`` — empty string on success. Non-empty means every
      copy strategy failed; ``args`` is left empty and callers should
      surface this message to the user (native yt-dlp mode would fail with
      the same underlying error).
    """
    if not cookies_from_browser:
        return [], None, ""

    raw = cookies_from_browser
    browser_and_kr, _, profile = raw.partition(":")
    browser = browser_and_kr.split("+", 1)[0].lower()

    if not is_chromium(browser):
        # Firefox / Safari — hand off to yt-dlp verbatim.
        return ["--cookies-from-browser", raw], None, ""

    try:
        staged = stage_profile(browser, profile or "Default")
    except CookieWorkaroundError as e:
        return [], None, str(e)

    return ["--cookies-from-browser", f"{browser_and_kr}:{staged}"], staged, ""
