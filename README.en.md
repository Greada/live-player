# LivePlayer

> 🌐 [简体中文](README.md) | English

Play **Bilibili Live / Douyu / Huya / Bilibili Video** in **PotPlayer** with one click
from Microsoft Edge, preferring the highest quality (4K / Original / Blu-ray).

A browser extension cannot launch a local program directly, so this project uses
**Native Messaging**: the extension hands the current page URL and login cookies to a
local Python Host, which resolves the real stream URL and launches PotPlayer.

## Layout

```
live-player/
  extension/                 Edge extension (MV3, plain JS)
  host/                      Python native-messaging Host
    liveplayer/
      __main__.py            Entry: native-messaging loop / CLI / proxy subprocess
      protocol.py            Native-messaging protocol (4-byte length frame, binary mode)
      proxy.py               Local stream proxy (adds Referer/Cookie, bypasses hotlink protection)
      resolver.py            yt-dlp wrapper + quality selection (Bilibili Live, Huya)
      douyu.py               Douyu resolver (getEncryption + getH5PlayV1)
      bilibili_video.py      Bilibili VOD (WBI signature + merged-stream durl)
      wbi.py                 Bilibili WBI signature
      platform.py            Platform detection / request-header rules
      player.py              PotPlayer discovery and launch
      config.py              Config loading
    build_host.ps1           Build host.exe
    host.config.example.toml
    requirements.txt         Runtime deps (pinned)
    requirements-dev.txt     Dev / CI deps
    pyproject.toml           Packaging & tooling config (ruff / pytest)
    tests/                   Offline unit tests + 4-platform integration scripts
  install/
    register-edge.ps1        Register the Edge native-messaging host
    unregister-edge.ps1
    extension-key.txt        Fixed extension ID and public key
  CONTRIBUTING.md  CHANGELOG.md  SECURITY.md  LICENSE(MIT)
```

## Requirements

- Windows
- Python 3.11+ with an in-project venv (**needed at runtime**: the Host is started by
  `run_host.bat` via `pythonw.exe`)
- PotPlayer (Scoop or default install path; auto-detected)
- Node.js is **not** required (Douyu auth is implemented in pure Python)

## Install

> Below, `<repo>` denotes the repository root (e.g. `C:\code\live-player`).

### 1. Prepare the Host runtime

```powershell
cd <repo>\host
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> By default `run_host.bat` is used (runs via the venv's `pythonw.exe`); **no custom exe
> is needed**. If Smart App Control is disabled on your system, you may instead build an
> exe: `pwsh -File .\build_host.ps1`.

### 2. Register with Edge

```powershell
pwsh -File <repo>\install\register-edge.ps1
```

The script generates `install\com.liveplayer.host.json` and writes the registry key
`HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.liveplayer.host`.

### 3. Load the extension

1. Open `edge://extensions` and enable **Developer mode** (bottom-left).
2. Click **Load unpacked** and select `<repo>\extension`.
3. Make sure the extension ID is `cagnicepbgamjhjjbmfpkkfbchoalpfa` (fixed by the
   manifest `key`).

### 4. Usage

Open a supported page and click the LivePlayer icon in the toolbar:
- **Play with PotPlayer**: resolve and start playback (highest quality by default).
- **List qualities**: show the available tiers.
- **Copy direct URL**: copy only the stream URL.
- You can also right-click on the page → “Play with PotPlayer”.

During playback the Host **auto-fits the PotPlayer window to the video size** (scaled
proportionally and centered within the monitor work area), which helps on 4K displays;
tune it with `fit_window` / `fit_window_cover` in the config.

## Supported platforms

| Platform | Resolver | Max quality |
|----------|----------|-------------|
| Bilibili Live | yt-dlp | Original / Blu-ray (more when logged in) |
| Douyu | Official H5 API | Original 2K60 |
| Huya | Custom resolver (wsSecret hotlink algorithm) | Original / Blu-ray |
| Bilibili Video | playurl merged stream | ~720P logged-out, 1080P logged-in |

> **About 4K**: 4K/8K/HDR on Bilibili video & live require a **Premium (大会员)** account.
> The tool automatically forwards the browser login cookies (including `SESSDATA`) to the
> Host; without Premium you only get the tiers allowed for a logged-out/normal account,
> and they are reported honestly — no fake “success”. Douyu/Huya Original/2K/1080P are
> usually available without membership.

## Hotlink protection & the local proxy

CDNs such as Bilibili validate the `Referer` and return 403 when it is missing, and
PotPlayer cannot set custom request headers. The Host therefore starts a temporary
proxy that **listens only on 127.0.0.1** (random port + random token) and adds the
Referer/Cookie/UA while forwarding, so PotPlayer plays a local address. The proxy exits
automatically when idle — it does not stay resident or auto-start. The Douyu CDN also
requires a lower OpenSSL security level (SECLEVEL=1) to pull the stream, which is handled
internally.

In addition, stream URLs on platforms like Douyu are basically **single-use** and expire
(~5 minutes); if PotPlayer reuses an old URL when probing/reconnecting, it stalls. The
proxy **refreshes the URL in the background on a timer** (the old URL keeps serving so the
current stream is uninterrupted) and re-resolves synchronously once when an upstream
request fails. To avoid Douyu returning 403 on high-frequency requests and to avoid
stalls from blocking connections during resolution, the proxy **no longer re-resolves on
every new connection**; it also disables Nagle and reuses upstream connections to improve
throughput. Failures are written to `%TEMP%\liveplayer.log`.

## Configuration

Copy `host\host.config.example.toml` to `host\host.config.toml` (same directory as
`host.exe`):

```toml
potplayer_path = ""        # empty = auto-detect
default_quality = "best"   # best / 4k / 1080p / 720p / <format_id>
fit_window = true          # fit the PotPlayer window to the video size on launch
fit_window_cover = 0.95    # max fraction of the monitor work area the window may use
proxy_idle_timeout = 300   # seconds of inactivity before the proxy exits
```

## CLI debugging (optional)

```powershell
cd <repo>\host
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m liveplayer health
.\.venv\Scripts\python.exe -m liveplayer list  "https://www.douyu.com/9999"
.\.venv\Scripts\python.exe -m liveplayer print-url "https://live.bilibili.com/1"
.\.venv\Scripts\python.exe -m liveplayer play   "https://www.bilibili.com/video/BVxxxx"
```

## Troubleshooting

- **“Cannot connect to the local helper”**: make sure `register-edge.ps1` has been run and
  that `host\run_host.bat` (or your own `host\dist\host.exe`) exists; check
  `edge://extensions` for extension errors.
- **“Specified native messaging host not found”**: the registry default value must point
  to the **absolute path** of `install\com.liveplayer.host.json`, and the manifest `path`
  must point to the real exe.
- **“Cannot play”**: usually hotlink protection (already handled by the proxy). If you
  edited the config manually, make sure the proxy process was not killed.
- **Quality is low**: check that the browser is logged in to that platform; Bilibili 4K
  requires Premium.
- **`host.exe` blocked by “Application Control Policy” / cannot be deleted**: this is
  Windows **Smart App Control** blocking an unsigned exe. The default approach is now
  `run_host.bat` (running with trusted Python), which is not affected. If you switch to
  `host.exe`, disable it in Windows Security → App & browser control → Smart App Control
  (this is irreversible).
- **“Access denied” when re-building**: `host.exe` is running as the playback proxy.
  `build_host.ps1` stops it automatically; you can also end the `host.exe` process
  manually.
- **Viewing Edge logs**: start Edge with `--enable-logging`; native-messaging errors are
  written to the log.

## License & disclaimer

This project is open-sourced under the [MIT License](LICENSE); you may freely use, modify
and distribute it.

- This tool is intended for **personal study and viewing only**: it resolves public APIs
  and uses **your own** account credentials, and does **not** bypass paid/membership
  restrictions.
- Please comply with each platform's terms of service; you are solely responsible for any
  consequences of using this tool.
- The software is provided “as is”, without warranty of any kind.
