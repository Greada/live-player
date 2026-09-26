"""通用播放验证：解析给定 URL -> 起本地代理 -> 抓取首块数据，验证可播。

用法: python tests/test_play.py "<url>" [quality]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from liveplayer import platform as p, proxy  # noqa: E402
from liveplayer.config import load as load_config  # noqa: E402
from liveplayer.resolver import resolve  # noqa: E402


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    quality = sys.argv[2] if len(sys.argv) > 2 else "best"
    cookies = sys.argv[3] if len(sys.argv) > 3 else ""

    cfg = load_config()
    target = p.detect(url)
    res = resolve(target, quality=quality, cookies=cookies, cfg=cfg)
    print(f"平台 {res.platform} | 标题 {res.title} | 直播 {res.is_live}")
    for q in res.qualities:
        mark = "*" if res.selected and q.id == res.selected.id else " "
        print(f"  [{mark}] {q.id:>8} {q.label} h={q.height} tbr={q.tbr}")
    print("选中:", res.selected.label)
    print("直链:", res.url[:90])

    headers = p.upstream_headers(target, cookies)
    local = proxy.start(
        res.url,
        headers,
        idle_timeout=20,
        tls_legacy=p.upstream_tls_legacy(target),
        refresh={"page_url": p.canonical_url(target), "cookies": cookies, "quality": res.selected.label},
    )
    print("本地:", local)
    with httpx.stream("GET", local, timeout=40) as r:
        first = next(r.iter_bytes(), b"")
        print("状态:", r.status_code, "类型:", r.headers.get("content-type"), "首块:", first[:16])


if __name__ == "__main__":
    main()
