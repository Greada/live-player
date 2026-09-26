"""解析引擎：基于 yt-dlp 库获取画质列表与直链。

以库方式调用（而非子进程），这样打包成单文件 exe 后依然可用，也避免
依赖外部 yt-dlp 可执行文件。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

import yt_dlp

from .config import Config
from .platform import Target, canonical_url


class ResolveError(Exception):
    """解析失败。"""


_QUALITY_ALIASES = {"4k": "2160", "8k": "4320", "2k": "1440", "1080": "1080"}
_HEIGHT_RE = re.compile(r"^(\d{3,4})p?$")


@dataclass
class Quality:
    id: str
    label: str
    height: int = 0
    fps: float = 0.0
    tbr: float = 0.0
    ext: str = ""
    url: str = ""
    rank: int = 0


@dataclass
class Resolved:
    platform: str
    title: str
    is_live: bool
    qualities: list[Quality] = field(default_factory=list)
    selected: Quality | None = None
    url: str = ""


class _Logger:
    """把 yt-dlp 的输出导向 stderr，避免污染原生消息协议的 stdout。"""

    def debug(self, msg):  # noqa: D102
        pass

    def info(self, msg):  # noqa: D102
        pass

    def warning(self, msg):  # noqa: D102
        _stderr(msg)

    def error(self, msg):  # noqa: D102
        _stderr(msg)


def _stderr(msg: object) -> None:
    try:
        if sys.stderr is not None:
            print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _base_opts(cookies: str) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "logger": _Logger(),
    }
    if cookies:
        opts["http_headers"] = {"Cookie": cookies}
    return opts


def _extract(url: str, cookies: str, extra: dict | None = None) -> dict:
    opts = _base_opts(cookies)
    if extra:
        opts.update(extra)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ResolveError(str(exc).replace("ERROR: ", "").strip()) from exc
    except Exception as exc:  # noqa: BLE001
        raise ResolveError(f"yt-dlp 解析异常: {exc}") from exc

    if not info:
        raise ResolveError("yt-dlp 未返回信息")
    if info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise ResolveError("未找到可播放内容")
        info = entries[0]
    return info


def _label_rank(label: str) -> int:
    """按画质名称推断档位（用于 height 缺失的直播流排序）。"""
    text = (label or "").lower()
    table = [
        (("8k",), 8000),
        (("4k", "原画", "source", "蓝光", "blu-ray", "blueray"), 4000),
        (("2k",), 2000),
        (("超清", "ultra", "1080"), 1080),
        (("高清", "high", "720"), 720),
        (("流畅", "fluent", "480", "标清", "standard"), 480),
    ]
    for keywords, rank in table:
        if any(kw in text for kw in keywords):
            return rank
    return 0


def _build_qualities(info: dict) -> list[Quality]:
    qualities: list[Quality] = []
    seen: set[str] = set()
    for fmt in info.get("formats") or []:
        fmt_id = fmt.get("format_id")
        if not fmt_id or str(fmt_id) in seen:
            continue
        seen.add(str(fmt_id))
        label = (
            fmt.get("format_note")
            or fmt.get("resolution")
            or fmt.get("format")
            or str(fmt_id)
        )
        qualities.append(
            Quality(
                id=str(fmt_id),
                label=str(label),
                height=int(fmt.get("height") or 0),
                fps=float(fmt.get("fps") or 0),
                tbr=float(fmt.get("tbr") or 0),
                ext=str(fmt.get("ext") or ""),
                url=str(fmt.get("url") or ""),
                rank=_label_rank(str(label)),
            )
        )
    return _dedupe_by_label(qualities)


def _dedupe_by_label(qualities: list[Quality]) -> list[Quality]:
    """同一档位（标签相同）只保留最佳的一条，避免 CDN 变体刷屏。"""
    best: dict[str, Quality] = {}
    order: list[str] = []
    for q in qualities:
        key = q.label
        if key not in best:
            best[key] = q
            order.append(key)
        elif (q.height, q.rank, q.tbr, q.fps) > (best[key].height, best[key].rank, best[key].tbr, best[key].fps):
            best[key] = q
    return [best[k] for k in order]


def _sorted(qualities: list[Quality]) -> list[Quality]:
    return sorted(
        qualities, key=lambda q: (q.height, q.rank, q.tbr, q.fps), reverse=True
    )


def pick_quality(qualities: list[Quality], want: str) -> Quality:
    if not qualities:
        raise ResolveError("没有可用画质")
    ordered = _sorted(qualities)

    want = (want or "").strip().lower()
    if not want or want in ("best", "max", "最高", "最高画质"):
        return ordered[0]

    normalized = _QUALITY_ALIASES.get(want, want)
    m = _HEIGHT_RE.match(normalized)
    if m:
        target = int(m.group(1))
        not_above = [q for q in ordered if q.height and q.height <= target]
        if not_above:
            return not_above[0]
        return ordered[0]

    for q in ordered:
        if want == q.id.lower() or want in q.label.lower():
            return q
    raise ResolveError(f"未找到画质: {want}")


def _direct_url(url: str, quality: Quality, cookies: str) -> str:
    if quality.url:
        return quality.url
    info = _extract(url, cookies, {"format": quality.id})
    if info.get("url"):
        return str(info["url"])
    for fmt in info.get("requested_formats") or info.get("formats") or []:
        if fmt.get("url"):
            return str(fmt["url"])
    raise ResolveError("未能获取直播直链")


def resolve(
    target: Target,
    quality: str = "",
    cookies: str = "",
    cfg: Config | None = None,
) -> Resolved:
    if target.platform == "douyu":
        from . import douyu

        return douyu.resolve(target, quality=quality, cookies=cookies, cfg=cfg)

    if target.platform == "bilibili_video":
        from . import bilibili_video

        return bilibili_video.resolve(target, quality=quality, cookies=cookies, cfg=cfg)

    if target.platform == "huya":
        from . import huya

        return huya.resolve(target, quality=quality, cookies=cookies, cfg=cfg)

    url = canonical_url(target)
    info = _extract(url, cookies)
    qualities = _build_qualities(info)
    want = quality or (cfg.default_quality if cfg else "best")
    selected = pick_quality(qualities, want)
    direct = _direct_url(url, selected, cookies)
    return Resolved(
        platform=target.platform,
        title=str(info.get("title") or ""),
        is_live=bool(info.get("is_live")),
        qualities=_sorted(qualities),
        selected=selected,
        url=direct,
    )
