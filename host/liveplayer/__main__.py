"""入口：无参数时作为原生消息 Host，有参数时作为命令行工具。"""

from __future__ import annotations

import sys

from . import HOST_NAME, __version__, platform as plat, player as player_mod, protocol
from .config import load as load_config
from .resolver import ResolveError, resolve


def handle(message: dict) -> dict:
    """处理一条原生消息，返回响应字典。"""
    cfg = load_config()
    action = str(message.get("action") or "").lower()

    if action == "health":
        return {
            "ok": True,
            "host": HOST_NAME,
            "version": __version__,
            "potplayer": player_mod.find_potplayer(cfg.potplayer_path),
        }

    if action in ("parse", "play"):
        raw = str(message.get("url") or "")
        cookies = str(message.get("cookies") or "")
        quality = str(message.get("quality") or "")
        try:
            target = plat.detect(raw)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            result = resolve(target, quality=quality, cookies=cookies, cfg=cfg)
        except ResolveError as exc:
            return {"ok": False, "error": str(exc), "platform": target.platform}

        response = {
            "ok": True,
            "platform": result.platform,
            "title": result.title,
            "isLive": result.is_live,
            "qualities": [
                {"id": q.id, "label": q.label, "height": q.height, "fps": q.fps}
                for q in result.qualities
            ],
            "selected": {
                "id": result.selected.id,
                "label": result.selected.label,
                "height": result.selected.height,
            },
        }
        if action == "play":
            headers = plat.upstream_headers(target, cookies)
            refresh = {
                "page_url": plat.canonical_url(target),
                "cookies": cookies,
                "quality": result.selected.label,
            }
            video_size = player_mod.estimate_video_size(
                result.selected.height, result.selected.label
            )
            try:
                info = player_mod.open_stream(
                    result.url,
                    headers,
                    explicit=cfg.potplayer_path,
                    idle_timeout=cfg.proxy_idle_timeout,
                    tls_legacy=plat.upstream_tls_legacy(target),
                    refresh=refresh,
                    video_size=video_size,
                    fit_window=cfg.fit_window,
                    cover=cfg.fit_window_cover,
                )
                response["played"] = True
                response["player"] = info["player"]
                response["localUrl"] = info["localUrl"]
            except Exception as exc:  # noqa: BLE001 - 需要把错误回传前端
                response["ok"] = False
                response["error"] = f"启动播放器失败: {exc}"
        else:
            response["url"] = result.url
        return response

    return {"ok": False, "error": f"未知 action: {action}"}


def native_loop() -> None:
    protocol.protect_stdout()
    while True:
        message = protocol.read_message()
        if message is None:
            break
        try:
            response = handle(message)
        except Exception as exc:  # noqa: BLE001 - Host 必须总能响应
            response = {"ok": False, "error": f"内部错误: {exc}"}
        protocol.write_message(response)


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def cli(argv: list[str]) -> int:
    import argparse

    _force_utf8_console()
    parser = argparse.ArgumentParser(
        prog="liveplayer",
        description="解析国内直播 / B 站视频，并用 PotPlayer 播放",
    )
    parser.add_argument("command", choices=["health", "list", "print-url", "play"])
    parser.add_argument("url", nargs="?", default="", help="链接或 '平台 房间号'")
    parser.add_argument("-q", "--quality", default="", help="画质: best/4k/1080p/...")
    parser.add_argument("--cookies", default="", help="Cookie 字符串")
    parser.add_argument("--player", default="", help="PotPlayer 可执行文件路径")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.player:
        cfg.potplayer_path = args.player

    if args.command == "health":
        found = player_mod.find_potplayer(cfg.potplayer_path)
        print(f"host: {HOST_NAME}  version: {__version__}")
        print(f"potplayer: {found or '(未找到)'}")
        print(f"config: {__import__('liveplayer.config', fromlist=['config_path']).config_path()}")
        return 0

    try:
        target = plat.detect(args.url)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    try:
        result = resolve(
            target,
            quality=args.quality or cfg.default_quality,
            cookies=args.cookies,
            cfg=cfg,
        )
    except ResolveError as exc:
        print(f"解析失败: {exc}", file=sys.stderr)
        return 1

    print(f"平台: {result.platform}  标题: {result.title}  直播: {result.is_live}")
    print("可用画质:")
    for q in result.qualities:
        mark = "*" if result.selected and q.id == result.selected.id else " "
        print(f"  [{mark}] {q.id:>10}  {q.label}  height={q.height} fps={q.fps}")
    print(f"选中: {result.selected.label}  ({result.selected.height}p)")

    if args.command == "list":
        return 0
    if args.command == "print-url":
        print(f"直链: {result.url}")
        return 0

    headers = plat.upstream_headers(target, args.cookies)
    refresh = {
        "page_url": plat.canonical_url(target),
        "cookies": args.cookies,
        "quality": result.selected.label,
    }
    video_size = player_mod.estimate_video_size(result.selected.height, result.selected.label)
    try:
        info = player_mod.open_stream(
            result.url,
            headers,
            explicit=cfg.potplayer_path,
            idle_timeout=cfg.proxy_idle_timeout,
            tls_legacy=plat.upstream_tls_legacy(target),
            refresh=refresh,
            video_size=video_size,
            fit_window=cfg.fit_window,
            cover=cfg.fit_window_cover,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"启动播放器失败: {exc}", file=sys.stderr)
        return 1
    print(f"已用 PotPlayer 播放: {info['player']}")
    print(f"本地代理地址: {info['localUrl']}")
    print(f"目标窗口尺寸: {video_size[0]}x{video_size[1]}")
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "__proxy":
        from . import proxy

        proxy.serve(argv[1])
        return
    if argv and argv[0] == "__fit":
        from . import window

        window.fit_main(argv[1:])
        return
    # 原生消息模式下，浏览器会把调用方 origin 作为第一个参数传入
    if argv and argv[0].startswith("chrome-extension://"):
        native_loop()
        return
    if argv:
        args = [a for a in argv if not a.startswith("--parent-window")]
        raise SystemExit(cli(args))
    native_loop()


if __name__ == "__main__":
    main()
