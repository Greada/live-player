"""虎牙直播解析。

yt-dlp 的虎牙提取器对部分房间会算出占位流（拉几秒即断）。这里移植
streamlink 的做法：解析页面 ``hyPlayerConfig.stream``，按官方算法计算
``wsSecret`` 等防盗链参数，得到可持续的直播流。
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import time
import urllib.parse
from html import unescape as html_unescape

import httpx

from .config import Config
from .platform import Target
from .resolver import Quality, Resolved, ResolveError, _dedupe_by_label, _sorted, pick_quality

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_CONSTANTS = {"t": 100, "ver": 1, "sv": 2401090219, "codec": 264}


class HuyaError(ResolveError):
    """虎牙解析失败。"""


def _match_brace(text: str, start: int) -> int:
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
    raise HuyaError("虎牙 stream 配置解析失败")


def _extract_config(html: str) -> dict:
    m = re.search(r"stream\s*:\s*\{", html)
    if m:
        start = html.index("{", m.start())
        return json.loads(html[start:_match_brace(html, start)])
    m = re.search(r'stream\s*:\s*"([A-Za-z0-9+/=]{80,})"', html)
    if m:
        return json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
    raise HuyaError("未找到虎牙 stream 配置（可能未开播）")


def _label(bit: int) -> str:
    if bit <= 0:
        return "原画"
    if bit >= 10000:
        return "蓝光"
    if bit >= 4000:
        return "超清"
    if bit >= 2000:
        return "高清"
    return f"{bit}k"


def _rank(bit: int) -> int:
    return 100000 if bit <= 0 else bit


def _build_url(stream_info: dict, bit: int) -> str:
    flv_url = str(stream_info.get("sFlvUrl") or "")
    stream_name = str(stream_info.get("sStreamName") or "")
    suffix = str(stream_info.get("sFlvUrlSuffix") or "flv")
    anticode = html_unescape(str(stream_info.get("sFlvAntiCode") or ""))
    qs = dict(urllib.parse.parse_qsl(anticode))

    ws_time = qs.get("wsTime", "")
    ctype = qs.get("ctype", "huya_live")
    fs = qs.get("fs", "")
    fm = qs.get("fm", "")

    uid = random.randint(12340000, 12349999)
    convert_uid = ((uid << 8) | (uid >> (32 - 8))) & 0xFFFFFFFF
    timestamp = int(time.time() * 1000)
    seqid = uid + timestamp

    prefix = base64.b64decode(urllib.parse.unquote(fm)).decode().split("_")[0]
    secret_hash = hashlib.md5(f"{seqid}|{ctype}|{_CONSTANTS['t']}".encode()).hexdigest()
    ws_secret = hashlib.md5(
        f"{prefix}_{convert_uid}_{stream_name}_{secret_hash}_{ws_time}".encode()
    ).hexdigest()

    params = {
        "wsSecret": ws_secret,
        "wsTime": ws_time,
        "ctype": ctype,
        "fs": fs,
        "seqid": seqid,
        "u": convert_uid,
        "sdk_sid": timestamp,
        "ratio": bit,
        **_CONSTANTS,
    }
    return f"{flv_url}/{stream_name}.{suffix}?" + urllib.parse.urlencode(params)


def resolve(
    target: Target,
    quality: str = "",
    cookies: str = "",
    cfg: Config | None = None,
) -> Resolved:
    rid = target.room_id
    if not rid:
        raise HuyaError("缺少虎牙房间号")

    headers = {"User-Agent": _UA, "Referer": "https://www.huya.com/"}
    if cookies:
        headers["Cookie"] = cookies
    html = httpx.get(f"https://www.huya.com/{rid}", headers=headers, timeout=20).text

    config = _extract_config(html)
    blocks = config.get("data") or []
    if not blocks:
        raise HuyaError("虎牙未取到直播数据")
    block = blocks[0]
    info = block.get("gameLiveInfo") or {}
    streams = block.get("gameStreamInfoList") or []
    if not streams:
        raise HuyaError("该虎牙直播间未开播")

    title = str(info.get("roomName") or info.get("introduction") or "")

    multi = config.get("vMultiStreamInfo") or [{"iBitRate": 0}]
    qualities: list[Quality] = []
    for stream_info in streams:
        for item in multi:
            bit = int(item.get("iBitRate") or 0)
            qualities.append(
                Quality(
                    id=f"{stream_info.get('iLineIndex')}-{bit}",
                    label=_label(bit),
                    height=0,
                    rank=_rank(bit),
                    tbr=float(bit),
                    ext=str(stream_info.get("sFlvUrlSuffix") or "flv"),
                    url=_build_url(stream_info, bit),
                )
            )
    if not qualities:
        raise HuyaError("虎牙未取到可用流")

    qualities = _dedupe_by_label(qualities)
    want = quality or (cfg.default_quality if cfg else "best")
    selected = pick_quality(qualities, want)
    return Resolved(
        platform=target.platform,
        title=title,
        is_live=True,
        qualities=_sorted(qualities),
        selected=selected,
        url=selected.url,
    )
