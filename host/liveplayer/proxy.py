"""本地流代理：为 PotPlayer 转发需要 Referer / Cookie 的平台直播流。

背景：
- B 站等 CDN 做了防盗链，缺少 Referer 会返回 403，而 PotPlayer 无法通过命令行
  传递请求头，故由本地代理补头转发。
- 斗鱼等平台的流地址基本「一次有效」且会过期。PotPlayer 会先探测、或在到期后
  重连，第二次连接若仍用旧地址会拿到死流而卡住。故代理会按时间在**后台**刷新
  地址（旧地址继续服务），并在上游请求失败时同步重新解析。
  注意：**不应**在每个新连接都同步重新解析——斗鱼会因高频请求返回 403，且解析
  会阻塞其它连接，导致播放卡顿与速率骤降。

代理仅监听 127.0.0.1，按需启动、空闲自动退出，不常驻。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

DEFAULT_IDLE_SECONDS = 300
_REFRESH_SECONDS = 240
_REFRESH_RETRY_SECONDS = 30  # 后台刷新失败后的冷却时间，避免反复打平台 API
_CHUNK_SIZE = 262144  # 转发分块大小（越大 CPU 开销越低、吞吐越高）
_FORWARD_HEADERS = (
    "Content-Type",
    "Content-Length",
    "Content-Range",
    "Accept-Ranges",
    "Cache-Control",
)


def _log(message: str) -> None:
    try:
        path = os.path.join(tempfile.gettempdir(), "liveplayer.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [proxy] {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _make_client(tls_legacy: bool, timeout) -> httpx.Client:
    """创建上游 HTTP 客户端。

    部分平台 CDN（如斗鱼）不兼容 OpenSSL 3 默认安全等级，需要降低到
    SECLEVEL=1 并关闭主机名校验。
    """
    if not tls_legacy:
        return httpx.Client(follow_redirects=True, timeout=timeout)

    import ssl

    context = ssl.create_default_context()
    try:
        context.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return httpx.Client(verify=context, follow_redirects=True, timeout=timeout)


class StreamState:
    """维护当前上游地址，并在需要时（后台）重新解析。

    历史问题：斗鱼等平台被标记为「每个新连接都重新解析」，而 PotPlayer 会因
    探测/重连/缓冲频繁开新连接，于是每次连接都去打一次斗鱼 API。斗鱼对高频
    请求返回 403（风控），且解析在 ``self._lock`` 内同步进行，会阻塞所有其它
    连接——表现为播放卡顿、平均速率骤降到几百 KB/s。

    现在的策略：
    - 正常连接**直接返回缓存地址**，连接建立不再触发解析；
    - 地址超过 TTL 时在**后台线程**刷新，旧地址继续服务
      （stale-while-revalidate），刷新失败也不影响正在播放的流；
    - 仅当上一轮请求失败需要换地址时，才同步 ``force`` 解析一次。
    """

    def __init__(self, job: dict):
        self._url = str(job.get("url") or "")
        self._headers = dict(job.get("headers") or {})
        self._tls = bool(job.get("tls_legacy"))
        refresh = job.get("refresh") or {}
        self._page_url = str(refresh.get("page_url") or "")
        self._cookies = str(refresh.get("cookies") or "")
        self._quality = str(refresh.get("quality") or "")
        self._resolved_at = time.time()
        self._next_refresh = self._resolved_at + _REFRESH_SECONDS
        self._lock = threading.Lock()
        self._resolving = False
        self._clients: dict[bool, httpx.Client] = {}
        self._client_lock = threading.Lock()
        self.refresh_on_failure = False
        if self._page_url:
            try:
                from . import platform as plat

                self.refresh_on_failure = plat.upstream_refresh_on_failure(
                    plat.detect(self._page_url)
                )
            except Exception:  # noqa: BLE001
                self.refresh_on_failure = False

    def client(self, tls_legacy: bool, timeout) -> httpx.Client:
        """按 TLS 模式复用长连接客户端，避免每次请求都重新握手。"""
        key = bool(tls_legacy)
        with self._client_lock:
            client = self._clients.get(key)
            if client is None:
                client = _make_client(key, timeout)
                self._clients[key] = client
            return client

    def _do_resolve(self) -> None:
        from . import platform as plat
        from .config import load as load_config
        from .resolver import resolve as do_resolve

        target = plat.detect(self._page_url)
        result = do_resolve(target, quality=self._quality, cookies=self._cookies, cfg=load_config())
        now = time.time()
        with self._lock:
            self._url = result.url
            self._headers = plat.upstream_headers(target, self._cookies)
            self._tls = plat.upstream_tls_legacy(target)
            self._resolved_at = now
            self._next_refresh = now + _REFRESH_SECONDS
        _log(f"refresh ok {self._page_url} -> {self._url[:70]}")

    def _refresh_bg(self) -> None:
        try:
            self._do_resolve()
        except Exception as exc:  # noqa: BLE001
            _log(f"background refresh failed: {exc!r}")
            with self._lock:
                # 失败后冷却一段时间再试，避免每个连接都触发一次平台请求
                self._next_refresh = time.time() + _REFRESH_RETRY_SECONDS
        finally:
            with self._lock:
                self._resolving = False

    def _maybe_refresh_bg(self) -> None:
        """TTL 到期时后台刷新，不阻塞当前请求。"""
        if not self.refresh_on_failure:
            return
        with self._lock:
            if self._resolving or time.time() < self._next_refresh:
                return
            self._resolving = True
        threading.Thread(target=self._refresh_bg, daemon=True).start()

    def acquire(self, force: bool = False) -> tuple[str, dict, bool]:
        if not self._page_url:
            with self._lock:
                return self._url, self._headers, self._tls
        if force:
            try:
                self._do_resolve()
            except Exception as exc:  # noqa: BLE001
                _log(f"refresh failed: {exc!r}")
        else:
            self._maybe_refresh_bg()
        with self._lock:
            return self._url, self._headers, self._tls


def _handler_factory(state: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # 关闭 Nagle：避免小包 + 延迟 ACK 造成吞吐塌陷
        disable_nagle_algorithm = True

        def log_message(self, *args):  # noqa: D102 - 静默
            return

        def do_GET(self):  # noqa: N802
            self._serve(with_body=True)

        def do_HEAD(self):  # noqa: N802
            self._serve(with_body=False)

        def _serve(self, with_body: bool) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/stream/"):
                self.send_error(404, "not found")
                return
            token = parsed.path[len("/stream/"):]
            if state["token"] and token != state["token"]:
                self.send_error(403, "forbidden")
                return

            self.close_connection = True
            with state["lock"]:
                state["active"] += 1
            state["last"] = time.time()
            stream: StreamState = state["stream"]
            timeout = httpx.Timeout(20.0, read=60.0)
            started = False
            sent = 0
            began = time.time()
            try:
                for attempt in (0, 1):
                    # 仅在“需要换地址”的平台（如斗鱼）且首轮失败时才重新解析，
                    # 避免每次重连都打平台 API（会触发 403 且阻塞其它连接）。
                    force = attempt == 1 and stream.refresh_on_failure
                    url, headers, tls = stream.acquire(force=force)
                    request_headers = dict(headers)
                    range_header = self.headers.get("Range")
                    if range_header:
                        request_headers["Range"] = range_header
                    client = stream.client(tls, timeout)
                    with client.stream("GET", url, headers=request_headers) as upstream:
                        if upstream.status_code >= 400 and attempt == 0:
                            continue
                        self.send_response(upstream.status_code)
                        for name in _FORWARD_HEADERS:
                            value = upstream.headers.get(name)
                            if value is not None:
                                self.send_header(name, value)
                        self.send_header("Connection", "close")
                        self.end_headers()
                        started = True
                        if with_body:
                            for chunk in upstream.iter_bytes(_CHUNK_SIZE):
                                self.wfile.write(chunk)
                                sent += len(chunk)
                                state["last"] = time.time()
                        return
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # 客户端（PotPlayer）主动断开，属正常情况，不再当上游错误处理
                pass
            except Exception as exc:  # noqa: BLE001
                _log(f"upstream error: {exc!r}")
                if not started:
                    try:
                        self.send_error(502, "upstream error")
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                with state["lock"]:
                    state["active"] -= 1
                state["last"] = time.time()
                _log(f"conn done sent={sent}B in {time.time() - began:.1f}s")

    return Handler


class _ProxyServer(ThreadingHTTPServer):
    """线程化的本地代理服务器；每个连接独立线程，连接间互不阻塞。"""

    daemon_threads = True
    allow_reuse_address = True


def _watchdog(state: dict) -> None:
    idle = float(state.get("idle_timeout") or DEFAULT_IDLE_SECONDS)
    while True:
        time.sleep(10)
        with state["lock"]:
            active = state["active"]
        if active == 0 and (time.time() - state["last"]) > idle:
            os._exit(0)


def serve(job_file: str) -> None:
    """代理进程入口：从 job 文件读取配置并开始服务。"""
    with open(job_file, encoding="utf-8") as fh:
        job = json.load(fh)

    state = {
        "stream": StreamState(job),
        "token": job.get("token") or "",
        "idle_timeout": job.get("idle_timeout") or DEFAULT_IDLE_SECONDS,
        "last": time.time(),
        "active": 0,
        "lock": threading.Lock(),
    }
    server = _ProxyServer(("127.0.0.1", int(job["port"])), _handler_factory(state))
    threading.Thread(target=_watchdog, args=(state,), daemon=True).start()
    server.serve_forever()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _proxy_command(job_file: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "__proxy", job_file]
    return [sys.executable, "-m", "liveplayer", "__proxy", job_file]


def start(
    upstream_url: str,
    headers: dict,
    idle_timeout: int = DEFAULT_IDLE_SECONDS,
    wait_seconds: float = 8.0,
    tls_legacy: bool = False,
    refresh: dict | None = None,
) -> str:
    """启动本地代理并返回给 PotPlayer 播放的本地地址。

    refresh: {"page_url", "cookies", "quality"}，提供后代理可在每次新连接时
    重新解析上游地址（应对斗鱼等「一次有效」的流）。
    """
    import secrets

    port = _free_port()
    token = secrets.token_urlsafe(16)
    job = {
        "port": port,
        "url": upstream_url,
        "headers": headers,
        "token": token,
        "idle_timeout": idle_timeout,
        "tls_legacy": tls_legacy,
        "refresh": refresh or {},
    }
    job_file = os.path.join(tempfile.gettempdir(), f"liveplayer-proxy-{port}.json")
    with open(job_file, "w", encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)

    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen(
        _proxy_command(job_file),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return f"http://127.0.0.1:{port}/stream/{token}"
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("本地流代理启动超时")
