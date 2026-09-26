"""Host 配置加载（TOML）。"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass

CONFIG_FILENAME = "host.config.toml"


@dataclass
class Config:
    potplayer_path: str = ""
    default_quality: str = "best"
    yt_dlp_path: str = ""
    streamlink_path: str = ""
    proxy_idle_timeout: int = 300
    fit_window: bool = True
    fit_window_cover: float = 0.95


def config_path() -> str:
    env = os.environ.get("LIVEPLAYER_CONFIG")
    if env:
        return env
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        # 本文件位于 host/liveplayer/config.py，向上两级到 host/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, CONFIG_FILENAME)


def load() -> Config:
    cfg = Config()
    path = config_path()
    if not os.path.isfile(path):
        return cfg
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    for key in ("potplayer_path", "default_quality", "yt_dlp_path", "streamlink_path"):
        value = data.get(key)
        if value:
            setattr(cfg, key, str(value))
    if data.get("proxy_idle_timeout"):
        cfg.proxy_idle_timeout = int(data["proxy_idle_timeout"])
    if "fit_window" in data:
        cfg.fit_window = bool(data["fit_window"])
    if data.get("fit_window_cover"):
        cfg.fit_window_cover = float(data["fit_window_cover"])
    return cfg
