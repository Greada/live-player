"""按视频尺寸调整 PotPlayer 窗口大小。

PotPlayer 没有可用的命令行尺寸参数，且其主程序为压缩格式。这里在启动后
用 Win32 API 找到播放器窗口，把窗口客户区调整为视频尺寸（在屏幕上等比缩放
以适配工作区），并居中显示。

作为独立子进程运行（``__fit``），以便 Host 立即返回、不阻塞。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

_USER32 = ctypes.WinDLL("user32", use_last_error=True)

_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_MONITOR_DEFAULTTONEAREST = 2

if hasattr(_USER32, "GetWindowLongPtrW"):
    _USER32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _USER32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_style = _USER32.GetWindowLongPtrW
else:  # pragma: no cover - 32 位系统
    _USER32.GetWindowLongW.restype = ctypes.c_long
    _USER32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_style = _USER32.GetWindowLongW

_USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_USER32.IsWindowVisible.argtypes = [wintypes.HWND]
_USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_USER32.AdjustWindowRectEx.argtypes = [
    ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
]
_USER32.MoveWindow.argtypes = [
    wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL
]
_USER32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_USER32.MonitorFromWindow.restype = wintypes.HANDLE


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _log(message: str) -> None:
    try:
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "liveplayer.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [fit] {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _USER32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _find_window(pid: int, timeout: float) -> int:
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def collect():
        by_pid: list[int] = []
        by_class: list[int] = []

        def callback(hwnd, _lparam):
            if not _USER32.IsWindowVisible(hwnd):
                return True
            cls = _class_name(hwnd).lower()
            if "potplayer" not in cls and "potmini" not in cls:
                return True
            if _window_pid(hwnd) == pid:
                by_pid.append(hwnd)
            else:
                by_class.append(hwnd)
            return True

        _USER32.EnumWindows(enum_proc(callback), 0)
        return by_pid, by_class

    deadline = time.time() + timeout
    while time.time() < deadline:
        by_pid, by_class = collect()
        if by_pid:
            return by_pid[0]
        if by_class:
            # 单实例模式下窗口可能属于已存在的进程
            return by_class[0]
        time.sleep(0.25)
    return 0


def fit_to_video(
    pid: int,
    width: int,
    height: int,
    timeout: float = 10.0,
    cover: float = 0.95,
) -> bool:
    """把 pid（或已存在的 PotPlayer）窗口调整为视频尺寸。"""
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

    if width <= 0 or height <= 0:
        return False

    hwnd = _find_window(pid, timeout)
    if not hwnd:
        _log("未找到 PotPlayer 窗口")
        return False

    # 等待播放器完成初始化，避免被其自身的窗口逻辑覆盖
    time.sleep(1.2)

    monitor = _USER32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    _USER32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
    work = info.rcWork
    work_w = work.right - work.left
    work_h = work.bottom - work.top

    scale = min(1.0, work_w * cover / width, work_h * cover / height)
    client_w = max(320, int(width * scale))
    client_h = max(240, int(height * scale))

    style = _get_style(hwnd, _GWL_STYLE) & 0xFFFFFFFF
    exstyle = _get_style(hwnd, _GWL_EXSTYLE) & 0xFFFFFFFF
    rect = wintypes.RECT(0, 0, client_w, client_h)
    _USER32.AdjustWindowRectEx(ctypes.byref(rect), style, False, exstyle)
    outer_w = rect.right - rect.left
    outer_h = rect.bottom - rect.top

    x = work.left + max(0, (work_w - outer_w) // 2)
    y = work.top + max(0, (work_h - outer_h) // 2)
    _USER32.MoveWindow(hwnd, x, y, outer_w, outer_h, True)
    _log(f"窗口调整为 {client_w}x{client_h} (视频 {width}x{height})")
    return True


def _command(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "__fit", *args]
    return [sys.executable, "-m", "liveplayer", "__fit", *args]


def spawn_fit(pid: int, width: int, height: int) -> None:
    """以独立进程执行窗口适配，不阻塞 Host。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            _command([str(pid), str(width), str(height)]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"启动窗口适配失败: {exc!r}")


def fit_main(argv: list[str]) -> None:
    """__fit 子进程入口：argv = [pid, width, height]。"""
    try:
        pid = int(argv[0])
        width = int(argv[1])
        height = int(argv[2])
    except (IndexError, ValueError):
        return
    fit_to_video(pid, width, height)
