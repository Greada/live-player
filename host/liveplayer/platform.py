"""平台识别：把用户输入的 URL / 房间号 / BV 号解析成统一的 Target。"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 支持的平台标识
BILIBILI_LIVE = "bilibili_live"
BILIBILI_VIDEO = "bilibili_video"
DOUYU = "douyu"
HUYA = "huya"

_ALIASES = {
    "b站": "bilibili",
    "bilibili": "bilibili",
    "哔哩哔哩": "bilibili",
    "斗鱼": "douyu",
    "douyu": "douyu",
    "虎牙": "huya",
    "huya": "huya",
}

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{8,}|av\d+)", re.I)
_EXPLICIT_RE = re.compile(r"^([A-Za-z\u4e00-\u9fff]+)\s+(\S+)$")
_LIVE_BILI_RE = re.compile(r"bilibili\.com/(?:blanc/)?(\d+)", re.I)


@dataclass
class Target:
    platform: str
    url: str
    room_id: str = ""
    kind: str = "live"  # live | video


def _last_number(text: str) -> str:
    nums = re.findall(r"\d+", text)
    return nums[-1] if nums else ""


def _normalize_platform(name: str) -> str:
    return _ALIASES.get(name.strip().lower(), name.strip().lower())


def detect(text: str) -> Target:
    """从任意文本识别目标平台。

    支持形式：
        https://live.bilibili.com/21452505
        https://www.douyu.com/9999
        https://www.huya.com/660000
        https://www.bilibili.com/video/BV1xx411c7mD
        斗鱼 9999 / douyu 9999
        BV1xx411c7mD
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("输入为空")

    # 显式 "平台 房间号" 形式
    m = _EXPLICIT_RE.match(raw)
    if m and not raw.lower().startswith("http"):
        plat = _normalize_platform(m.group(1))
        if plat in ("bilibili", "douyu", "huya"):
            return _from_platform(plat, m.group(2))

    low = raw.lower()
    clean = raw.split("?")[0].split("#")[0]

    # B 站点播视频
    m = _BV_RE.search(clean)
    if m and "bilibili.com" in low:
        return Target(BILIBILI_VIDEO, raw, room_id=m.group(1), kind="video")

    # 纯 BV/av 号
    m = _BV_RE.fullmatch(raw)
    if m:
        return Target(BILIBILI_VIDEO, raw, room_id=m.group(1), kind="video")

    if "live.bilibili.com" in low:
        room = _last_number(clean)
        if not room:
            raise ValueError("无法从 B 站直播链接解析房间号")
        return Target(BILIBILI_LIVE, raw, room_id=room, kind="live")

    if "bilibili.com" in low:
        room = _last_number(clean)
        if room:
            return Target(BILIBILI_LIVE, raw, room_id=room, kind="live")
        raise ValueError("无法解析 B 站链接")

    if "douyu.com" in low:
        room = _last_number(clean)
        if not room:
            raise ValueError("无法从斗鱼链接解析房间号")
        return Target(DOUYU, raw, room_id=room, kind="live")

    if "huya.com" in low:
        room = _last_number(clean)
        if not room:
            raise ValueError("无法从虎牙链接解析房间号")
        return Target(HUYA, raw, room_id=room, kind="live")

    # 纯数字无法判断平台
    raise ValueError(
        "无法识别平台。请给完整链接，或使用 '平台 房间号'（如：douyu 9999）"
    )


def _from_platform(plat: str, arg: str) -> Target:
    if plat == "bilibili":
        m = _BV_RE.fullmatch(arg)
        if m:
            return Target(BILIBILI_VIDEO, arg, room_id=m.group(1), kind="video")
        room = _last_number(arg)
        if not room:
            raise ValueError("B 站房间号无效")
        return Target(BILIBILI_LIVE, arg, room_id=room, kind="live")
    room = _last_number(arg)
    if not room:
        raise ValueError(f"{plat} 房间号无效")
    return Target(plat, arg, room_id=room, kind="live")


def canonical_url(target: Target) -> str:
    """生成可交给 yt-dlp 处理的标准 URL。"""
    if target.url.lower().startswith("http"):
        return target.url
    if target.platform == BILIBILI_LIVE:
        return f"https://live.bilibili.com/{target.room_id}"
    if target.platform == BILIBILI_VIDEO:
        return f"https://www.bilibili.com/video/{target.room_id}"
    if target.platform == DOUYU:
        return f"https://www.douyu.com/{target.room_id}"
    if target.platform == HUYA:
        return f"https://www.huya.com/{target.room_id}"
    return target.url


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_REFERERS = {
    BILIBILI_LIVE: "https://live.bilibili.com/",
    BILIBILI_VIDEO: "https://www.bilibili.com/",
    DOUYU: "https://www.douyu.com/",
    HUYA: "https://www.huya.com/",
}

_ORIGINS = {
    HUYA: "https://www.huya.com",
    BILIBILI_VIDEO: "https://www.bilibili.com",
}


def upstream_headers(target: Target, cookies: str = "") -> dict:
    """返回访问上游流地址时必须携带的请求头（防盗链所需）。"""
    headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
    referer = _REFERERS.get(target.platform)
    if referer:
        headers["Referer"] = referer
    origin = _ORIGINS.get(target.platform)
    if origin:
        headers["Origin"] = origin
    if cookies:
        headers["Cookie"] = cookies
    return headers


# 这些平台的 CDN 不兼容 OpenSSL 3 默认安全等级，需降低 TLS 安全等级拉流
_LEGACY_TLS_PLATFORMS = {DOUYU}

# 这些平台的流地址基本「一次有效」且会过期：代理需定期在后台刷新，
# 并在上一轮请求失败时同步重新解析以换用新地址。
# 注意：**不要**在“每个新连接”都同步解析——斗鱼会因高频请求返回 403，
# 且解析期间会持锁阻塞其它连接，直接导致播放卡顿、速率骤降。
_REFRESH_ON_FAILURE_PLATFORMS = {DOUYU}


def upstream_tls_legacy(target: Target) -> bool:
    return target.platform in _LEGACY_TLS_PLATFORMS


def upstream_refresh_on_failure(target: Target) -> bool:
    """该平台的流地址是否为「一次有效」，失败/过期时需重新解析。"""
    return target.platform in _REFRESH_ON_FAILURE_PLATFORMS
