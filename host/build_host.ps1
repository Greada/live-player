# 将 Host 打包为单文件 host.exe（供 Edge 原生消息调用）。
# 用法: pwsh -File build_host.ps1 [-Python <python.exe>] [-OneDir]
param(
    [string]$Python = "",
    [switch]$OneDir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Python) { $Python = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "未找到 Python: $Python" }

Write-Host "使用 Python: $Python"
& $Python -c "import sys; print(sys.version)"

& $Python -m pip install -U pyinstaller

$mode = if ($OneDir) { "--onedir" } else { "--onefile" }
$entry = Join-Path $root "run_host.py"
$dist = Join-Path $root "dist"

# host.exe 可能正作为播放代理在运行并锁住文件，先停止匹配的进程
$targetExe = Join-Path $dist "host.exe"
Get-Process -Name host -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $targetExe } |
    ForEach-Object {
        Write-Host "停止占用中的 host.exe (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 300

& $Python -m PyInstaller `
    --noconfirm --clean --noconsole `
    $mode `
    --name host `
    --paths $root `
    --distpath $dist `
    --workpath (Join-Path $root "build") `
    --specpath (Join-Path $root "build") `
    $entry

$exe = Join-Path $dist "host.exe"
if (Test-Path $exe) {
    Write-Host "构建完成: $exe"
} else {
    throw "构建失败，未生成 $exe"
}
