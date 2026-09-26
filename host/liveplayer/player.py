"""PotPlayer 定位、启动与视频尺寸估算。"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

# Scoop 会按版本号建目录，因此用通配符 + 排序取最新，避免写死版本号。
_CANDIDATE_GLOBS = [
    r"E:\software\Scoop\apps\potplayer\*\PotPlayerMini64.exe",
    r"E:\software\Scoop\apps\potplayer\*\PotPlayer64.exe",
    r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
    r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini.exe",
    r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
]
_CANDIDATE_NAMES = [
    "PotPlayerMini64.exe",
    "PotPlayer64.exe",
    "PotPlayerMini.exe",
    "PotPlayer.exe",
]


def find_potplayer(explicit: str = "") -> str:
    """返回 PotPlayer 可执行文件路径，找不到返回空串。

    查找顺序：显式配置 -> PATH -> 常见安装路径。
    """
    if explicit and os.path.isfile(explicit):
        return explicit

    for name in _CANDIDATE_NAMES:
        found = shutil.which(name)
        if found:
            return found

    matches: list[str] = []
    for pattern in _CANDIDATE_GLOBS:
        matches.extend(glob.glob(pattern))
    if matches:
        matches.sort()
        return matches[-1]
    return ""


def launch(url: str, explicit: str = "") -> tuple[str, int]:
    """用 PotPlayer 打开 url，返回 (播放器路径, 进程 id)。"""
    if not url:
        raise ValueError("播放地址为空")
    path = find_potplayer(explicit)
    if not path:
        raise FileNotFoundError(
            "未找到 PotPlayer，请在 host.config.toml 中设置 potplayer_path"
        )
    proc = subprocess.Popen([path, url], close_fds=True)
    return path, proc.pid


def estimate_video_size(height: int, label: str = "") -> tuple[int, int]:
    """估算视频像素尺寸（按 16:9），用于调整窗口大小。"""
    text = (label or "").lower()
    h = int(height or 0)
    if not h:
        if "8k" in text:
            h = 4320
        elif "4k" in text:
            h = 2160
        elif "2k" in text:
            h = 1440
        elif "1080" in text or any(k in (label or "") for k in ("蓝光", "超清", "原画")):
            h = 1080
        elif "720" in text or "高清" in (label or ""):
            h = 720
        elif "480" in text or any(k in (label or "") for k in ("标清", "流畅")):
            h = 480
        else:
            h = 1080
    w = round(h * 16 / 9)
    return (w - w % 2, h - h % 2)


def open_stream(
    upstream_url: str,
    headers: dict,
    explicit: str = "",
    idle_timeout: int = 300,
    tls_legacy: bool = False,
    refresh: dict | None = None,
    video_size: tuple[int, int] | None = None,
    fit_window: bool = True,
    cover: float = 0.95,
) -> dict:
    """经由本地代理把流交给 PotPlayer 播放，并按视频尺寸调整窗口。

    refresh: {"page_url", "cookies", "quality"}，用于代理按连接重新解析上游。
    返回 {"player", "localUrl", "upstream"}。
    """
    from . import proxy

    local_url = proxy.start(
        upstream_url,
        headers,
        idle_timeout=idle_timeout,
        tls_legacy=tls_legacy,
        refresh=refresh,
    )
    player_path, pid = launch(local_url, explicit)

    if fit_window and video_size and video_size[0] > 0 and video_size[1] > 0:
        from . import window

        window.spawn_fit(pid, video_size[0], video_size[1])

    return {"player": player_path, "localUrl": local_url, "upstream": upstream_url}
