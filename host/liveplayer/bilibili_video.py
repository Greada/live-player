"""B 站点播视频解析。

B 站默认走 DASH（音视频分离），PotPlayer 不能直接播放；这里改用
``playurl`` 的合并流（fnval=1，FLV/durl），得到单一直链，音视频同源。

画质受账号权限限制：未登录约 480P，登录后最高 1080P，4K/8K 需大会员。
"""

from __future__ import annotations

import httpx

from . import wbi
from .config import Config
from .platform import Target
from .resolver import Quality, Resolved, ResolveError, _sorted, pick_quality

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_URL_VIEW = "https://api.bilibili.com/x/web-interface/view"
_URL_NAV = "https://api.bilibili.com/x/web-interface/nav"
_URL_PLAYURL = "https://api.bilibili.com/x/player/wbi/playurl"

_QN_HEIGHT = {
    127: 4320, 126: 2160, 125: 2160, 120: 2160, 116: 1080,
    112: 1080, 80: 1080, 74: 720, 64: 720, 32: 480, 16: 360,
}


class BiliVideoError(ResolveError):
    """B 站视频解析失败。"""


def _headers(cookies: str = "") -> dict:
    headers = {
        "User-Agent": _UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if cookies:
        headers["Cookie"] = cookies
    return headers


def _get_cid(bvid: str, cookies: str) -> tuple[str, str]:
    resp = httpx.get(_URL_VIEW, params={"bvid": bvid}, headers=_headers(cookies), timeout=20)
    payload = resp.json()
    data = payload.get("data")
    if payload.get("code") != 0 or not data:
        raise BiliVideoError(payload.get("message") or "获取视频信息失败")
    return str(data.get("cid") or ""), str(data.get("title") or "")


def _get_wbi_keys(cookies: str) -> tuple[str, str]:
    resp = httpx.get(_URL_NAV, headers=_headers(cookies), timeout=20)
    data = (resp.json() or {}).get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = wbi_img.get("img_url") or ""
    sub_url = wbi_img.get("sub_url") or ""
    if not img_url or not sub_url:
        raise BiliVideoError("获取 WBI 签名密钥失败")
    return wbi.keys_from_urls(img_url, sub_url)


def _playurl(bvid: str, cid: str, cookies: str) -> dict:
    img_key, sub_key = _get_wbi_keys(cookies)
    params = wbi.sign(
        {
            "bvid": bvid,
            "cid": cid,
            "fnval": 1,      # 合并流（FLV/durl），音视频同源
            "fnver": 0,
            "fourk": 1,
            "qn": 127,       # 请求最高画质，服务器按权限返回
            "platform": "pc",
        },
        img_key,
        sub_key,
    )
    resp = httpx.get(_URL_PLAYURL, params=params, headers=_headers(cookies), timeout=20)
    payload = resp.json()
    data = payload.get("data")
    if payload.get("code") != 0 or not data:
        raise BiliVideoError(payload.get("message") or "获取播放地址失败")
    return data


def _label_for(data: dict, qn: int) -> str:
    for item in data.get("support_formats") or []:
        if item.get("quality") == qn:
            return str(item.get("new_description") or item.get("display_desc") or qn)
    return f"{_QN_HEIGHT.get(qn, '')}P" if _QN_HEIGHT.get(qn) else str(qn)


def resolve(
    target: Target,
    quality: str = "",
    cookies: str = "",
    cfg: Config | None = None,
) -> Resolved:
    bvid = target.room_id
    if not bvid:
        raise BiliVideoError("缺少 BV 号")

    cid, title = _get_cid(bvid, cookies)
    if not cid:
        raise BiliVideoError("未获取到 cid")

    data = _playurl(bvid, cid, cookies)
    durls = data.get("durl") or []
    if not durls:
        raise BiliVideoError("未获取到合并流地址（可能仅提供 DASH）")

    qn = int(data.get("quality") or 0)
    url = str(durls[0].get("url") or "")
    if not url:
        raise BiliVideoError("播放地址为空")

    item = Quality(
        id=str(qn or 80),
        label=_label_for(data, qn),
        height=_QN_HEIGHT.get(qn, 0),
        ext="flv" if url.split("?")[0].endswith(".flv") else "mp4",
        url=url,
    )
    qualities = [item]

    want = quality or (cfg.default_quality if cfg else "best")
    selected = pick_quality(qualities, want)
    return Resolved(
        platform=target.platform,
        title=title,
        is_live=False,
        qualities=_sorted(qualities),
        selected=selected,
        url=selected.url,
    )
