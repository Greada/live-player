"""B 站 WBI 签名。

参考 B 站 web 端算法：用 nav 接口拿到的 img_key/sub_key 经过固定混淆表
生成 mixin_key，再对排序后的参数拼接后取 md5 得到 w_rid。
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]


def _mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _strip(value: str) -> str:
    return "".join(ch for ch in str(value) if ch not in "!'()*")


def sign(params: dict, img_key: str, sub_key: str) -> dict:
    """返回带 wts 与 w_rid 的参数字典。"""
    mixin_key = _mixin_key(img_key + sub_key)
    signed = dict(params)
    signed["wts"] = int(time.time())
    signed = {k: signed[k] for k in sorted(signed)}
    query = urllib.parse.urlencode({k: _strip(v) for k, v in signed.items()})
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


def keys_from_urls(img_url: str, sub_url: str) -> tuple[str, str]:
    img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
    return img_key, sub_key
