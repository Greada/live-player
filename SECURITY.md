# 安全说明

## 报告漏洞

请**不要**公开提交安全问题的 Issue。请通过 GitHub 的私密漏洞报告（Security →
Report a vulnerability）或私下联系维护者。

## 安全模型

LivePlayer 涉及三个组件，理解其边界有助于评估风险：

### 1. Edge 扩展（MV3）
- 权限：`nativeMessaging`、`cookies`、`contextMenus`、`storage`、`tabs`。
- 仅在 `*.bilibili.com` / `*.douyu.com` / `*.huya.com` 上有主机权限。
- 会把当前页面 URL 与**该平台的登录 Cookie** 交给本地 Host。

### 2. 原生消息 Host（Python）
- 由 Edge 通过注册表 `HKCU\...\NativeMessagingHosts` 启动，`allowed_origins`
  限定为固定扩展 ID。
- **Cookie 仅在内存中使用**，用于解析直链与补请求头，不写入磁盘（日志不记录 Cookie）。

### 3. 本地流代理
- 仅监听 `127.0.0.1`，使用**随机端口 + 随机 token**（`/stream/<token>`），
  空闲自动退出，不常驻、不自启。
- 通过命令行参数把 PotPlayer 指向本地地址，token 防止本机其它进程误用。

## 已知注意事项

- 扩展 `manifest.json` 中的固定 `key` 仅用于**开发加载**以稳定扩展 ID；他人 fork
  后请自行生成 key，不要沿用该 ID 发布。
- 本工具不绕过平台付费/会员权限，仅使用公开接口与用户自己的账号凭据。
