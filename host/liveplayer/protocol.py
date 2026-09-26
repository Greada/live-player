"""Chromium/Edge 原生消息（Native Messaging）协议编解码。

协议格式：
    [4 字节小端无符号整数长度][UTF-8 编码的 JSON]

注意：在 Windows 上必须使用二进制读写，否则 ``\\n`` 会被转换成 ``\\r\\n``，
破坏消息格式。这里直接对文件描述符 0/1 读写，绕开 Python 文本层。
"""

from __future__ import annotations

import json
import os
import struct

_STDIN_FD = 0
_STDOUT_FD = 1
_OUT_FD = _STDOUT_FD


def protect_stdout() -> None:
    """把协议输出通道独立出来，并把标准输出重定向到 NUL。

    这样即使 yt-dlp 等第三方库误写 stdout，也不会破坏原生消息协议。
    仅在原生消息模式下调用（命令行模式不需要）。
    """
    global _OUT_FD
    try:
        _OUT_FD = os.dup(_STDOUT_FD)
    except OSError:
        _OUT_FD = _STDOUT_FD
        return
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, _STDOUT_FD)
        os.close(devnull)
    except OSError:
        pass


def _read_exact(fd: int, size: int) -> bytes | None:
    """从文件描述符读取恰好 size 个字节；若中途 EOF 返回 None。"""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = os.read(fd, remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message() -> dict | None:
    """读取一条消息。输入结束（EOF）时返回 None。"""
    header = _read_exact(_STDIN_FD, 4)
    if header is None:
        return None
    (length,) = struct.unpack("<I", header)
    if length == 0:
        return {}
    payload = _read_exact(_STDIN_FD, length)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


def write_message(message: dict) -> None:
    """写出单条消息（4 字节小端长度 + UTF-8 JSON）。"""
    data = json.dumps(message, ensure_ascii=False).encode("utf-8")
    frame = struct.pack("<I", len(data)) + data
    view = memoryview(frame)
    fd = _OUT_FD
    while view:
        written = os.write(fd, view)
        view = view[written:]
