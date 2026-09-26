"""斗鱼直播解析。

斗鱼页面不再内嵌 ``$ROOM``（yt-dlp 因此失效），且 CDN 不兼容 OpenSSL 3 默认
安全等级。这里采用官方 H5 接口：
    getEncryption -> getH5PlayV1
纯 Python 计算鉴权，无需 Node。

斗鱼对短时间高频请求会返回 403，故对请求做有限重试与友好报错。

CDN 拉流需低安全等级 TLS（SECLEVEL=1）与关闭主机名校验，故播放时通过带
``tls_legacy`` 的本地代理转发。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from email.utils import parsedate_to_datetime

import httpx

from .config import Config
from .platform import Target
from .resolver import (
    Quality,
    Resolved,
    ResolveError,
    _dedupe_by_label,
    _sorted,
    pick_quality,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_URL_ENCRYPTION = "https://www.douyu.com/wgapi/livenc/liveweb/websec/getEncryption"
_URL_PLAY = "https://www.douyu.com/lapi/live/getH5PlayV1/{rid}"
_URL_BETARD = "https://www.douyu.com/betard/{rid}"

# streamlink 使用的固定设备 id
_DID = "10000000000000000000000000001501"

_RETRIES = 3


class DouyuError(ResolveError):
    """斗鱼解析失败。"""


def _log(message: str) -> None:
    """把斗鱼请求失败写入 %TEMP%\\liveplayer.log，便于排查。"""
    try:
        import os
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "liveplayer.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [douyu] {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _headers(rid: str, cookies: str = "") -> dict:
    headers = {"User-Agent": _UA, "Referer": f"https://www.douyu.com/{rid}"}
    if cookies:
        headers["Cookie"] = cookies
    return headers


def _retry_call(func):
    """对斗鱼请求做有限重试，主要应对间歇性 403 / 网络抖动。"""
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return func()
        except httpx.HTTPStatusError as exc:
            last = exc
            if exc.response.status_code not in (403, 408, 429) and exc.response.status_code < 500:
                break
        except httpx.HTTPError as exc:
            last = exc
        if attempt < _RETRIES - 1:
            time.sleep(0.6 * (attempt + 1))
    if isinstance(last, httpx.HTTPStatusError) and last.response.status_code == 403:
        _log(f"403 访问被拒 url={last.request.url}")
        raise DouyuError("斗鱼拒绝访问（403，可能触发风控），请稍后重试") from last
    _log(f"请求失败 {last!r}")
    raise DouyuError(f"斗鱼请求失败: {last}") from last


def _get_room(rid: str, cookies: str) -> dict:
    def call():
        resp = httpx.get(_URL_BETARD.format(rid=rid), headers=_headers(rid, cookies), timeout=20)
        resp.raise_for_status()
        return resp.json()

    room = ( _retry_call(call) or {}).get("room")
    if not room:
        raise DouyuError("斗鱼房间不存在或解析失败")
    return room


def _compute_auth(rid: str, ts: int, key: str, rand_str: str, enc_time: int, is_special: int) -> str:
    suffix = "" if is_special == 1 else f"{rid}{ts}"
    value = rand_str
    for _ in range(int(enc_time)):
        value = hashlib.md5((value + key).encode("utf-8")).hexdigest()
    return hashlib.md5((value + key + suffix).encode("utf-8")).hexdigest()


def _get_encryption(did: str) -> tuple[int, dict]:
    def call():
        resp = httpx.get(
            _URL_ENCRYPTION,
            params={"did": did},
            headers={"User-Agent": _UA, "Referer": "https://www.douyu.com/"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp

    resp = _retry_call(call)
    try:
        ts = int(parsedate_to_datetime(resp.headers.get("date", "")).timestamp())
    except (TypeError, ValueError, OverflowError):
        ts = int(time.time())
    payload = resp.json()
    data = payload.get("data")
    if payload.get("error") != 0 or not data:
        raise DouyuError("斗鱼获取加密参数失败")
    return ts, data


def _request_stream(rid: str, rate: int, did: str, cookies: str) -> dict:
    ts, enc = _get_encryption(did)
    auth = _compute_auth(rid, ts, enc["key"], enc["rand_str"], enc["enc_time"], enc["is_special"])

    def call():
        resp = httpx.post(
            _URL_PLAY.format(rid=rid),
            data={
                "enc_data": enc["enc_data"],
                "tt": str(ts),
                "did": did,
                "auth": auth,
                "cdn": "",
                "rate": str(rate),
                "hevc": "0",
                "fa": "0",
                "ive": "0",
            },
            headers={
                "User-Agent": _UA,
                "Referer": f"https://www.douyu.com/{rid}",
                "Content-Type": "application/x-www-form-urlencoded",
                **({"Cookie": cookies} if cookies else {}),
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    payload = _retry_call(call)
    data = payload.get("data")
    if payload.get("error") != 0 or not data:
        raise DouyuError(f"斗鱼取流失败: {payload.get('msg') or payload.get('error')}")
    return data


def _height_from_name(name: str) -> int:
    n = (name or "").upper()
    if "4K" in n:
        return 2160
    if "2K" in n:
        return 1440
    if "蓝光" in (name or "") or "超清" in (name or ""):
        return 1080
    if "高清" in (name or ""):
        return 720
    if "流畅" in (name or "") or "标清" in (name or ""):
        return 480
    return 0


def _stream_url(data: dict) -> str:
    return f"{data.get('rtmp_url')}/{data.get('rtmp_live')}"


def _rank_bit(bit: float) -> int:
    return 100000 if bit <= 0 else int(bit)


def _quality_from(data: dict, label: str, bit: float, quality_id: str) -> Quality:
    return Quality(
        id=quality_id,
        label=label,
        height=_height_from_name(label),
        rank=_rank_bit(bit),
        tbr=bit,
        ext="flv",
        url=_stream_url(data),
    )


def _first_stream(rid: str, cookies: str) -> dict:
    """取最高档（rate=0）。首个 did 被拒时换随机 did 再试一次。"""
    try:
        return _request_stream(rid, 0, _DID, cookies)
    except DouyuError:
        return _request_stream(rid, 0, uuid.uuid4().hex, cookies)


def _resolve(rid: str, cookies: str, quality: str, cfg: Config | None) -> Resolved:
    room = _get_room(rid, cookies)
    if int(room.get("show_status") or 0) != 1:
        raise DouyuError("该斗鱼直播间未开播")

    # 关键优化：只请求最高档 + 实际需要的档位，避免为列全部档位而发起大量请求触发风控。
    first = _first_stream(rid, cookies)
    first_rate = int(first.get("rate") or 0)
    multirates = first.get("multirates") or []

    entries: list[tuple[int, str, float]] = []
    if multirates:
        for item in multirates:
            rate = int(item.get("rate") or 0)
            label = str(item.get("name") or "") or ("原画" if rate == 0 else f"{rate}M")
            entries.append((rate, label, float(item.get("bit") or 0)))
    else:
        entries.append((first_rate, "原画", float(first_rate)))

    display = [
        Quality(id=str(rate), label=label, height=_height_from_name(label),
                rank=_rank_bit(bit), tbr=bit, ext="flv", url="")
        for rate, label, bit in entries
    ]
    display = _dedupe_by_label(display)
    if not display:
        raise DouyuError("斗鱼没有可用画质")

    want = quality or (cfg.default_quality if cfg else "best")
    chosen_display = pick_quality(display, want)
    target_rate = int(chosen_display.id)

    data = first if target_rate == first_rate else _request_stream(rid, target_rate, _DID, cookies)
    chosen = _quality_from(data, chosen_display.label, chosen_display.tbr, str(target_rate))
    display = [chosen if q.id == chosen_display.id else q for q in display]

    return Resolved(
        platform="douyu",
        title=str(room.get("room_name") or ""),
        is_live=True,
        qualities=_sorted(display),
        selected=chosen,
        url=chosen.url,
    )


def resolve(
    target: Target,
    quality: str = "",
    cookies: str = "",
    cfg: Config | None = None,
) -> Resolved:
    rid = target.room_id
    if not rid:
        raise DouyuError("缺少斗鱼房间号")
    try:
        return _resolve(rid, cookies, quality, cfg)
    except DouyuError as exc:
        # 浏览器 Cookie 可能导致风控 403；去掉 Cookie 再试一次
        if cookies and "403" in str(exc):
            return _resolve(rid, "", quality, cfg)
        raise
