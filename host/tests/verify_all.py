"""四平台统一回归：解析 -> 本地代理 -> 抓首块，输出简短结论。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from liveplayer import platform as p, proxy  # noqa: E402
from liveplayer.config import load as load_config  # noqa: E402
from liveplayer.resolver import resolve  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
cfg = load_config()


def live_bili():
    r = httpx.get(
        "https://api.live.bilibili.com/room/v1/area/getRoomList",
        params={"parent_area_id": 1, "area_id": 0, "sort_type": "online", "page": 1, "page_size": 1},
        headers={"User-Agent": UA, "Referer": "https://live.bilibili.com/"}, timeout=20,
    )
    return f"https://live.bilibili.com/{r.json()['data'][0]['roomid']}"


def live_douyu():
    r = httpx.get("https://www.douyu.com/gapi/rkc/directory/2_1/1", headers={"User-Agent": UA}, timeout=20)
    return f"https://www.douyu.com/{r.json()['data']['rl'][0]['rid']}"


def live_huya():
    lst = httpx.get(
        "https://www.huya.com/cache.php",
        params={"m": "LiveList", "do": "getLiveListByPage", "tagAll": 0, "page": 1},
        headers={"User-Agent": UA, "Referer": "https://www.huya.com/"}, timeout=20,
    ).json()["data"]["datas"]
    for x in lst[:15]:
        rid = x.get("profileRoom")
        d = httpx.get("https://mp.huya.com/cache.php", params={"m": "Live", "do": "profileRoom", "roomid": rid},
                      headers={"User-Agent": UA}, timeout=15).json().get("data") or {}
        if d.get("liveStatus") == "ON":
            return f"https://www.huya.com/{rid}"
    return f"https://www.huya.com/{lst[0]['profileRoom']}"


def bili_video():
    r = httpx.get("https://api.bilibili.com/x/web-interface/popular", params={"ps": 1, "pn": 1},
                  headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"}, timeout=20)
    return f"https://www.bilibili.com/video/{r.json()['data']['list'][0]['bvid']}"


cases = [
    ("B站直播", live_bili()),
    ("斗鱼", live_douyu()),
    ("虎牙", live_huya()),
    ("B站视频", bili_video()),
]

print("=" * 60)
for name, url in cases:
    try:
        target = p.detect(url)
        res = resolve(target, quality="best", cookies="", cfg=cfg)
        headers = p.upstream_headers(target)
        local = proxy.start(
            res.url, headers, idle_timeout=15,
            tls_legacy=p.upstream_tls_legacy(target),
            refresh={"page_url": p.canonical_url(target), "cookies": "", "quality": res.selected.label},
        )
        with httpx.stream("GET", local, timeout=30) as r:
            first = next(r.iter_bytes(), b"")
            ok = r.status_code == 200 and len(first) > 0
        print(f"[{'OK ' if ok else 'FAIL'}] {name:6} | {res.selected.label:8} | {r.headers.get('content-type')} | {url}")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {name:6} | {type(e).__name__}: {str(e)[:80]} | {url}")
print("=" * 60)
