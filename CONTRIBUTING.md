# 贡献指南

感谢参与 LivePlayer！本项目由 **Edge 扩展（MV3，纯 JS）+ Python 原生消息 Host** 组成。

## 开发环境

- Windows
- Python 3.11+（CI 覆盖 3.11 / 3.12 / 3.13）
- PotPlayer（播放验证用）

```powershell
cd host
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 目录约定

- `extension/` —— Edge 扩展，改动后需在 `edge://extensions` 重新加载。
- `host/liveplayer/` —— Host 逻辑：
  - `platform.py` 平台识别与请求头规则
  - `resolver.py` / `douyu.py` / `huya.py` / `bilibili_video.py` 各平台解析
  - `proxy.py` 本地流代理（补 Referer/Cookie、刷新直链）
  - `player.py` / `window.py` PotPlayer 启动与窗口适配
- `install/` —— 原生消息注册脚本。

## 测试

**离线单测**（CI 运行，不联网）：

```powershell
cd host
.\.venv\Scripts\python.exe -m pytest -q
```

**联调回归**（需真实网络，手动运行）：

```powershell
cd host
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe tests\verify_all.py            # 四平台解析 -> 代理 -> 抓首块
.\.venv\Scripts\python.exe tests\test_play.py "<url>"     # 指定链接播放验证
```

> 注意：`tests/verify_all.py`、`test_proxy.py`、`test_play.py`、`test_native.py`
> 依赖真实平台接口，已被 `tests/conftest.py` 排除出 pytest 收集。

## 提交前

1. `ruff check .` 通过；
2. `pytest` 通过；
3. 涉及某平台解析逻辑时，用 `tests/test_play.py` 实机验证一次。

## 代码风格

- 提交信息用祈使句、简明说明「做了什么/为什么」。
- 保持与现有代码一致的注释语言（中文为主）。

## 免责声明

本项目仅用于**个人学习与观看**，解析公开接口并使用你自己的账号凭据，不绕过平台
付费/会员权限。请遵守各平台服务条款，勿用于盗链、二次分发或商业用途。
