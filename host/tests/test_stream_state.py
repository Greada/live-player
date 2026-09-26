"""StreamState 刷新策略的离线单测（不联网）。

验证核心修复：代理不再「每个新连接都重新解析上游」，而是
- 普通连接直接复用缓存地址；
- 仅在 ``force=True``（上一轮请求失败）时同步重新解析；
- TTL 到期时在后台刷新（stale-while-revalidate），不阻塞当前请求；
- 非「一次有效」平台（如 B 站）不做 TTL 后台刷新。

可独立运行： ``python tests/test_stream_state.py``
也可被 pytest 收集。
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import ExitStack
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from liveplayer import platform, proxy, resolver  # noqa: E402

_OLD_URL = "https://upstream/old.flv"
_NEW_URL = "https://upstream/new.flv"


class _Resolved:
    def __init__(self, url: str):
        self.url = url


def _patches(platform_name: str, calls: list, new_url: str, delay: float = 0.0):
    def fake_detect(text: str):
        return platform.Target(platform_name, text, room_id="1")

    def fake_resolve(target, quality="", cookies="", cfg=None):
        if delay:
            time.sleep(delay)
        calls.append(1)
        return _Resolved(new_url)

    return [
        mock.patch.object(platform, "detect", fake_detect),
        mock.patch.object(platform, "upstream_headers", lambda t, c="": {"Referer": "r"}),
        mock.patch.object(platform, "upstream_tls_legacy", lambda t: True),
        mock.patch.object(resolver, "resolve", fake_resolve),
    ]


def _state(
    stack: ExitStack, platform_name: str, calls: list, new_url: str, delay: float = 0.0
) -> proxy.StreamState:
    for patcher in _patches(platform_name, calls, new_url, delay):
        stack.enter_context(patcher)
    return proxy.StreamState(
        {
            "url": _OLD_URL,
            "headers": {"Referer": "r"},
            "tls_legacy": True,
            "refresh": {"page_url": "https://www.douyu.com/1", "cookies": "", "quality": "best"},
        }
    )


def test_no_resolve_on_normal_connections():
    """修复点：第二个及之后的连接不应再触发解析（原 bug 的核心）。"""
    calls: list = []
    with ExitStack() as stack:
        state = _state(stack, platform.DOUYU, calls, _NEW_URL)
        u1, _, _ = state.acquire()
        u2, _, _ = state.acquire()
        u3, _, _ = state.acquire()
    assert calls == [], f"普通连接不应触发重新解析，实际 {len(calls)} 次"
    assert (u1, u2, u3) == (_OLD_URL, _OLD_URL, _OLD_URL)
    print("PASS test_no_resolve_on_normal_connections")


def test_force_resolves_once():
    """失败重试时 force=True 应重新解析并换用新地址。"""
    calls: list = []
    with ExitStack() as stack:
        state = _state(stack, platform.DOUYU, calls, _NEW_URL)
        url, _, _ = state.acquire(force=True)
    assert len(calls) == 1, f"force 应触发一次解析，实际 {len(calls)} 次"
    assert url == _NEW_URL
    print("PASS test_force_resolves_once")


def test_ttl_refresh_is_background():
    """TTL 到期后应立即返回（不等待解析），随后在后台刷新。

    这里把解析模拟为耗时 0.5s，从而确定性地证明 acquire 不会同步等待解析；
    否则存在竞态：后台线程可能在 acquire 返回前就已完成刷新。
    """
    calls: list = []
    with ExitStack() as stack:
        state = _state(stack, platform.DOUYU, calls, _NEW_URL, delay=0.5)
        state._resolved_at = time.time() - proxy._REFRESH_SECONDS - 5
        state._next_refresh = time.time() - 1  # 视为 TTL 已到期

        began = time.time()
        url, _, _ = state.acquire()
        elapsed = time.time() - began
        assert elapsed < 0.3, f"acquire 不应被解析阻塞，实际 {elapsed:.2f}s"
        assert url == _OLD_URL, "后台刷新完成前应继续用旧地址服务"

        deadline = time.time() + 3.0
        while state._url != _NEW_URL and time.time() < deadline:
            time.sleep(0.05)
        assert calls, "TTL 到期后应触发后台刷新"
        assert state._url == _NEW_URL, "后台刷新完成后应换用新地址"
    print("PASS test_ttl_refresh_is_background")


def test_stable_platform_no_ttl_refresh():
    """非「一次有效」平台（B 站）不应做 TTL 后台刷新。"""
    calls: list = []
    with ExitStack() as stack:
        state = _state(stack, platform.BILIBILI_LIVE, calls, _NEW_URL)
        assert state.refresh_on_failure is False
        state._resolved_at = time.time() - proxy._REFRESH_SECONDS - 5
        state._next_refresh = time.time() - 1
        state.acquire()
        time.sleep(0.6)
    assert calls == [], f"B 站不应后台刷新，实际 {len(calls)} 次"
    print("PASS test_stable_platform_no_ttl_refresh")


def test_bg_refresh_failure_backs_off():
    """后台刷新失败后应进入冷却，避免每个连接都重试。"""
    calls: list = []
    with ExitStack() as stack:
        state = _state(stack, platform.DOUYU, calls, _NEW_URL)

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("boom")

        stack.enter_context(mock.patch.object(resolver, "resolve", boom))
        state._next_refresh = time.time() - 1
        state.acquire()

        deadline = time.time() + 3.0
        while not calls and time.time() < deadline:
            time.sleep(0.05)
        assert calls, "TTL 到期后应尝试后台刷新"

        deadline = time.time() + 1.0
        while state._resolving and time.time() < deadline:
            time.sleep(0.02)
        assert state._next_refresh > time.time() + proxy._REFRESH_RETRY_SECONDS - 5, \
            "失败后应设置冷却时间"
    print("PASS test_bg_refresh_failure_backs_off")


def main() -> int:
    test_no_resolve_on_normal_connections()
    test_force_resolves_once()
    test_ttl_refresh_is_background()
    test_stable_platform_no_ttl_refresh()
    test_bg_refresh_failure_backs_off()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
