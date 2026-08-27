# builds dist\ReelPipe\ReelPipe.exe on Windows. run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
  py -3.13 -m venv .venv
}
& .venv\Scripts\Activate.ps1

pip install -e ".[generic,app,build]"
pyinstaller --noconfirm packaging\reelpipe-app.spec

Write-Host ""
Write-Host "built dist\ReelPipe\ReelPipe.exe"
Write-Host "the machine needs ffmpeg on PATH: winget install Gyan.FFmpeg"
Write-Host "and the WebView2 runtime, which windows 11 ships by default"
