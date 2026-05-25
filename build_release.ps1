$ErrorActionPreference = "Stop"

$env:HTTP_PROXY = "http://127.0.0.1:7891"
$env:HTTPS_PROXY = "http://127.0.0.1:7891"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot "ms-playwright"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$workPath = Join-Path $PSScriptRoot "build_release_$stamp"
$distPath = Join-Path $PSScriptRoot "release_$stamp"
$zipPath = Join-Path $PSScriptRoot "BossResumeSender-windows-$stamp.zip"

conda run -n boss_sender python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
conda run -n boss_sender python -m playwright install chromium
conda run -n boss_sender python -m PyInstaller --noconfirm --clean --workpath $workPath --distpath $distPath BossResumeSender.spec

$exePath = Join-Path $distPath "BossResumeSender\BossResumeSender.exe"

Compress-Archive -Path (Join-Path $distPath "BossResumeSender") -DestinationPath $zipPath -CompressionLevel Optimal -Force

& $exePath --smoke-login-fallback
if ($LASTEXITCODE -ne 0) { throw "smoke-login-fallback failed" }
& $exePath --smoke-flow
if ($LASTEXITCODE -ne 0) { throw "smoke-flow failed" }
& $exePath --smoke-diagnose
if ($LASTEXITCODE -ne 0) { throw "smoke-diagnose failed" }

Write-Host ""
Write-Host "Release directory: $distPath\BossResumeSender"
Write-Host "Release exe: $exePath"
Write-Host "Release zip: $zipPath"
Write-Host "Copy the whole BossResumeSender directory when moving the app to another machine."
