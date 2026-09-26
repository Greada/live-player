"""原生消息协议端到端测试：以子进程方式启动 Host（Python 或打包 exe），
通过 stdin/stdout 发送长度前缀 JSON，验证握手与解析。"""

import json
import os
import struct
import subprocess
import sys

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
EXE = os.path.join(ROOT, "dist", "host.exe")
BAT = os.path.join(ROOT, "run_host.bat")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def live_room() -> str:
    r = httpx.get(
        "https://api.live.bilibili.com/room/v1/area/getRoomList",
        params={"parent_area_id": 1, "area_id": 0, "sort_type": "online", "page": 1, "page_size": 1},
        headers={"User-Agent": UA, "Referer": "https://live.bilibili.com/"},
        timeout=20,
    )
    return str(r.json()["data"][0]["roomid"])


def send(proc, obj):
    data = json.dumps(obj).encode("utf-8")
    proc.stdin.write(struct.pack("<I", len(data)) + data)
    proc.stdin.flush()


def recv(proc):
    header = proc.stdout.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    return json.loads(proc.stdout.read(length).decode("utf-8"))


def main():
    use_exe = "--exe" in sys.argv
    use_bat = "--bat" in sys.argv
    if use_exe:
        cmd = [EXE]
        env = os.environ.copy()
    elif use_bat:
        cmd = [BAT]
        env = os.environ.copy()
    else:
        cmd = [PY, "-m", "liveplayer"]
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONUTF8="1")

    room = live_room()
    # native messaging 会把调用方 origin 作为第一个参数
    cmd = cmd + ["chrome-extension://test-origin/"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )

    send(proc, {"action": "health"})
    print("health:", recv(proc))

    send(proc, {"action": "parse", "url": f"https://live.bilibili.com/{room}"})
    resp = recv(proc)
    if resp:
        resp = dict(resp)
        if resp.get("url"):
            resp["url"] = resp["url"][:70] + "..."
    print("parse:", json.dumps(resp, ensure_ascii=False))

    proc.stdin.close()
    proc.wait(timeout=30)
    err = proc.stderr.read().decode("utf-8", "replace")
    if err.strip():
        print("stderr:", err.strip()[-400:])


if __name__ == "__main__":
    main()
