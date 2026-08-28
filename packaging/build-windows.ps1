# builds dist\ReelPipe\ReelPipe.exe on Windows. run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
  py -3.13 -m venv .venv
}
& .venv\Scripts\Activate.ps1

pip install -e ".[generic,app,build]"
python packaging\fetch_ffmpeg.py
pyinstaller --noconfirm packaging\reelpipe-app.spec

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
  $ver = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
  & $iscc /DAppVer=$ver packaging\reelpipe.iss
  Write-Host "built ReelPipe-Windows-Setup.exe"
} else {
  Write-Host "inno setup not found - skipping the installer (choco install innosetup)"
}

Write-Host ""
Write-Host "built dist\ReelPipe\ReelPipe.exe"
Write-Host "machines need the WebView2 runtime, which windows 11 ships by default"
