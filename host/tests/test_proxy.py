import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from liveplayer import platform as p, proxy, resolver  # noqa: E402
from liveplayer.config import load as load_config  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

r = httpx.get(
    "https://api.live.bilibili.com/room/v1/area/getRoomList",
    params={"parent_area_id": 1, "area_id": 0, "sort_type": "online", "page": 1, "page_size": 5},
    headers={"User-Agent": UA, "Referer": "https://live.bilibili.com/"},
    timeout=20,
)
room = str(r.json()["data"][0]["roomid"])
print("live room:", room)

target = p.detect(f"https://live.bilibili.com/{room}")
cfg = load_config()
res = resolver.resolve(target, quality="best", cfg=cfg)
print("upstream:", res.url[:90])

headers = p.upstream_headers(target)
local = proxy.start(res.url, headers, idle_timeout=30)
print("local:", local)

with httpx.stream("GET", local, timeout=40) as rr:
    first = next(rr.iter_bytes(), b"")
    print("status:", rr.status_code, "ctype:", rr.headers.get("content-type"), "first:", first[:16])
