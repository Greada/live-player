# 卸载 Edge 原生消息 Host 注册项。
$hostName = "com.liveplayer.host"
$regPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"

if (Test-Path $regPath) {
    Remove-Item -Path $regPath -Recurse -Force
    Write-Host "已删除注册表: $regPath"
} else {
    Write-Host "未找到注册项: $regPath"
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$manifestPath = Join-Path $root "install\$hostName.json"
if (Test-Path $manifestPath) {
    Remove-Item -LiteralPath $manifestPath -Force
    Write-Host "已删除清单: $manifestPath"
}
