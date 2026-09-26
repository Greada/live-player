# 注册 Edge 原生消息 Host（写入当前用户注册表，无需管理员）。
# 用法: pwsh -File register-edge.ps1 [-Exe <host.exe 路径>] [-ExtensionId <扩展ID>]

param(
    [string]$Exe = "",
    [string]$ExtensionId = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)  # live-player\
$hostName = "com.liveplayer.host"
$installDir = Join-Path $root "install"
$manifestPath = Join-Path $installDir "$hostName.json"

if (-not $Exe) {
    # 优先使用 .bat 启动器（用受信任的 pythonw.exe，规避 Smart App Control 对未签名 exe 的拦截）
    $bat = Join-Path $root "host\run_host.bat"
    if (Test-Path $bat) {
        $Exe = (Resolve-Path $bat).Path
    } else {
        $Exe = Join-Path $root "host\dist\host.exe"
    }
}
if (-not (Test-Path $Exe)) { throw "未找到 Host 启动器: $Exe" }
$Exe = (Resolve-Path $Exe).Path

# 扩展 ID：优先参数 -> extension-key.txt -> 由 manifest 的 key 计算
if (-not $ExtensionId) {
    $keyFile = Join-Path $installDir "extension-key.txt"
    if (Test-Path $keyFile) {
        $line = Select-String -Path $keyFile -Pattern '^id=' | Select-Object -First 1
        if ($line) { $ExtensionId = $line.Line.Substring(3).Trim() }
    }
}
if (-not $ExtensionId) {
    $manifest = Get-Content (Join-Path $root "extension\manifest.json") -Raw | ConvertFrom-Json
    $spki = [Convert]::FromBase64String($manifest.key)
    $sha = [System.Security.Cryptography.SHA256]::Create().ComputeHash($spki)
    $hex = ($sha[0..15] | ForEach-Object { $_.ToString('x2') }) -join ''
    $ExtensionId = -join ($hex.ToCharArray() | ForEach-Object { [char](97 + [Convert]::ToInt32($_, 16)) })
}

$origin = "chrome-extension://$ExtensionId/"

$hostManifest = [ordered]@{
    name            = $hostName
    description     = "LivePlayer native host (解析直播/视频并用 PotPlayer 播放)"
    path            = $Exe
    type            = "stdio"
    allowed_origins = @($origin)
}
$hostManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "已生成 Host 清单: $manifestPath"

$regPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
New-Item -Path $regPath -Force | Out-Null
Set-ItemProperty -Path $regPath -Name "(default)" -Value $manifestPath
Write-Host "已写入注册表: $regPath"
Write-Host "扩展 ID: $ExtensionId"
Write-Host ""
Write-Host "下一步：在 Edge 打开 edge://extensions，开启“开发人员模式”，加载"
Write-Host "未打包扩展 -> 选择目录: $root\extension"
