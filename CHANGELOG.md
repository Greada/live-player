# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [Unreleased]

### Added
- 英文文档 `README.en.md`，中英双语互链。

### Fixed
- **斗鱼播放卡顿 / 速率仅数百 KB/s**：代理不再“每个新连接都重新解析上游”。
  此前 PotPlayer 每次重连都会触发一次斗鱼 `getH5PlayV1` 请求，斗鱼对高频请求返回
  403（风控），且解析持锁阻塞其它连接，导致卡顿。现在改为：
  - 普通连接直接复用缓存直链；
  - 直链过期在**后台线程**刷新（stale-while-revalidate），旧地址继续服务；
  - 仅上游请求失败时才同步重新解析，失败后有 30s 冷却。
- 代理关闭 Nagle（TCP_NODELAY）、复用上游连接池、转发分块提升至 256KB，改善吞吐。
- 客户端（PotPlayer）主动断开不再被误报为“上游错误”。

### Changed
- `platform.upstream_refresh_each` → `upstream_refresh_on_failure`（语义修正）。
- 移除未使用的 `curl_cffi` 运行时依赖。

## [0.1.0] - 2026-09-26

### Added
- Edge 扩展（MV3）：工具栏弹窗、右键菜单、画质选择、复制直链。
- Python 原生消息 Host：解析 B站直播 / 斗鱼 / 虎牙 / B站视频，启动 PotPlayer。
- 本地流代理：补 Referer/Cookie 绕过防盗链，支持直链过期刷新与断线重连。
- 按视频尺寸自动调整 PotPlayer 窗口。
- 安装/卸载 Edge 原生消息注册脚本。
