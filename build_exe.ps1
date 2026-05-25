$ErrorActionPreference = "Stop"

$env:HTTP_PROXY = "http://127.0.0.1:7891"
$env:HTTPS_PROXY = "http://127.0.0.1:7891"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot "ms-playwright"

conda run -n boss_sender python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
conda run -n boss_sender python -m playwright install chromium
conda run -n boss_sender python -m PyInstaller --noconfirm --clean BossResumeSender.spec

Write-Host ""
Write-Host "Build complete: dist\BossResumeSender\BossResumeSender.exe"
Write-Host "Copy the whole dist\BossResumeSender directory when moving the app to another machine."
