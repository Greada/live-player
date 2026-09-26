# LivePlayer

在 Edge 浏览器里一键把 **B站直播 / 斗鱼 / 虎牙 / B站视频** 用 **PotPlayer** 播放，
优先最高画质（4K / 原画 / 蓝光）。

浏览器扩展无法直接启动本地程序，因此采用 **Native Messaging**：扩展把当前页面
URL 与登录 Cookie 交给本地 Python Host，Host 解析出真实流地址后启动 PotPlayer。

## 结构

```
live-player/
  extension/                 Edge 扩展（MV3，纯 JS）
  host/                      Python 原生消息 Host
    liveplayer/
      __main__.py            入口：原生消息循环 / 命令行 / 代理子进程
      protocol.py            原生消息协议（4 字节长度帧 + 二进制模式）
      proxy.py               本地流代理（补 Referer/Cookie，绕过防盗链）
      resolver.py            yt-dlp 封装 + 画质选择（B站直播、虎牙）
      douyu.py               斗鱼解析（getEncryption + getH5PlayV1）
      bilibili_video.py      B站点播（WBI 签名 + 合并流 durl）
      wbi.py                 B站 WBI 签名
      platform.py            平台识别 / 请求头规则
      player.py              PotPlayer 定位与启动
      config.py              配置加载
    build_host.ps1           打包 host.exe
    host.config.example.toml
    requirements.txt         运行时依赖（已锁定版本）
    requirements-dev.txt     开发 / CI 依赖
    pyproject.toml           打包与工具配置（ruff / pytest）
    tests/                   离线单测 + 四平台联调脚本
  install/
    register-edge.ps1        注册 Edge 原生消息 Host
    unregister-edge.ps1
    extension-key.txt        扩展固定 ID 与公钥
  CONTRIBUTING.md  CHANGELOG.md  SECURITY.md  LICENSE(MIT)
```

## 环境要求

- Windows
- Python 3.11+ 与项目内 venv（**运行时需要**：Host 由 `run_host.bat` 用 `pythonw.exe` 启动）
- PotPlayer（Scoop 或默认安装路径均可，自动探测）
- Node.js **不需要**（斗鱼鉴权已改为纯 Python 实现）

## 安装

> 下文用 `<repo>` 指代本仓库根目录（例如 `C:\code\live-player`）。

### 1. 准备 Host 运行环境

```powershell
cd <repo>\host
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 默认使用 `run_host.bat`（通过 venv 的 `pythonw.exe` 运行），**无需自建 exe**。
> 若系统关闭了 Smart App Control，也可改为打包 exe：`pwsh -File .\build_host.ps1`。

### 2. 注册到 Edge

```powershell
pwsh -File <repo>\install\register-edge.ps1
```

脚本会：生成 `install\com.liveplayer.host.json`，并写入注册表
`HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.liveplayer.host`。

### 3. 加载扩展

1. 打开 `edge://extensions`，开启左下角「开发人员模式」。
2. 点「加载解压缩的扩展」，选择 `<repo>\extension`。
3. 确认扩展 ID 为 `cagnicepbgamjhjjbmfpkkfbchoalpfa`（由 manifest 的 `key` 固定）。

### 4. 使用

打开支持的页面，点浏览器工具栏的 LivePlayer 图标：
- **用 PotPlayer 播放**：解析并启动播放（默认最高画质）。
- **列出画质**：查看可选档位。
- **复制直链**：仅复制流地址。
- 也可以在页面上右键 → “用 PotPlayer 播放”。

播放时 Host 会**按视频尺寸自动调整 PotPlayer 窗口**（在屏幕工作区内等比缩放并
居中），适配 4K 显示器；可在配置中用 `fit_window` / `fit_window_cover` 调整。

## 支持的平台

| 平台 | 解析方式 | 画质上限 |
|------|----------|----------|
| B站直播 | yt-dlp | 原画/蓝光（登录后更全） |
| 斗鱼 | 官方 H5 接口 | 原画 2K60 |
| 虎牙 | 自研解析（wsSecret 防盗链算法） | 原画 蓝光 |
| B站视频 | playurl 合并流 | 未登录 ~720P，登录 1080P |

> **关于 4K**：B站视频/直播的 4K、8K、HDR 需要 **大会员** 账号。工具会把浏览器
> 登录 Cookie（含 `SESSDATA`）自动传给 Host；无大会员时只能拿到未登录/普通账号
> 允许的档位，并如实显示，不会伪装成功。斗鱼/虎牙的原画/2K/1080P 通常免会员可得。

## 防盗链与本地代理

B站等 CDN 校验 `Referer`，缺少会返回 403，而 PotPlayer 无法自定义请求头。
Host 会启动一个**仅监听 127.0.0.1** 的临时代理进程（随机端口 + 随机 token），
转发时补上 Referer/Cookie/UA，PotPlayer 播放本地地址。代理空闲自动退出，不常驻、
不自启。斗鱼 CDN 还需降低 OpenSSL 安全等级（SECLEVEL=1）拉流，已内置处理。

另外，斗鱼等平台的流地址基本「一次有效」且会过期（约 5 分钟），PotPlayer 探测/
重连时若沿用旧地址会卡住。代理会**按时间在后台刷新**地址（旧地址继续服务，
不影响正在播放的流），并在上游请求失败时同步重新解析一次。为避免斗鱼对高频
请求返回 403、以及解析阻塞连接导致的卡顿，代理**不再在每个新连接都重新解析**，
同时关闭 Nagle、复用上游连接以提升吞吐。失败信息会写入 `%TEMP%\liveplayer.log`。

## 配置

复制 `host\host.config.example.toml` 为 `host\host.config.toml`（与 `host.exe` 同目录）：

```toml
potplayer_path = ""        # 留空自动探测
default_quality = "best"   # best / 4k / 1080p / 720p / <format_id>
fit_window = true          # 启动后按视频尺寸调整 PotPlayer 窗口
fit_window_cover = 0.95    # 窗口最多占屏幕工作区的比例
proxy_idle_timeout = 300   # 代理空闲多少秒后退出
```

## 命令行调试（可选）

```powershell
cd <repo>\host
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m liveplayer health
.\.venv\Scripts\python.exe -m liveplayer list  "https://www.douyu.com/9999"
.\.venv\Scripts\python.exe -m liveplayer print-url "https://live.bilibili.com/1"
.\.venv\Scripts\python.exe -m liveplayer play   "https://www.bilibili.com/video/BVxxxx"
```

## 排错

- **提示“无法连接本地助手”**：确认已运行 `register-edge.ps1`，且 `host\run_host.bat`
  （或你自行打包的 `host\dist\host.exe`）存在；在 `edge://extensions` 查看扩展是否有错误。
- **“指定的本机消息传递主机未找到”**：注册表默认值需指向
  `install\com.liveplayer.host.json` 的**绝对路径**，且清单内 `path` 指向真实 exe。
- **“无法播放”**：多为防盗链（已由代理解决）。若手动改过配置，确认代理进程未被杀。
- **画质偏低**：检查浏览器是否已登录对应平台；B站 4K 需大会员。
- **`host.exe` 被“应用程序控制策略”拦截 / 无法删除**：这是 Windows **Smart App
  Control** 在拦截未签名 exe。默认方案已改为 `run_host.bat`（用受信任的 Python 运行），
  不受此限制。若你改用 `host.exe`，需在「Windows 安全中心 → 应用和浏览器控制 →
  智能应用控制」中关闭（关闭不可逆）。
- **重新打包时提示拒绝访问**：`host.exe` 正作为播放代理在运行。`build_host.ps1`
  会自动停止它；也可手动结束 `host.exe` 进程。
- **查看 Edge 日志**：以 `--enable-logging` 启动 Edge，原生消息错误会写入日志。

## 许可证与免责声明

本项目以 [MIT License](LICENSE) 开源，你可自由使用、修改、分发。

- 本工具仅供**个人学习与观看**：解析公开接口并使用**你自己的**账号凭证，**不绕过**
  平台的付费 / 会员权限。
- 请遵守各平台服务条款；因使用本工具产生的一切后果由使用者自行承担。
- 软件按“原样”提供，不附带任何明示或暗示的担保。
