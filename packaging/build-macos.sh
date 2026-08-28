#!/usr/bin/env bash
# builds dist/ReelPipe.app on macOS (apple silicon). run from the repo root:
#   bash packaging/build-macos.sh
set -euo pipefail

if [ ! -d .venv ]; then
  python3.13 -m venv .venv
fi
source .venv/bin/activate

pip install -e ".[apple,app,build]"
python packaging/fetch_ffmpeg.py
pyinstaller --noconfirm packaging/reelpipe-app.spec

rm -rf dist/dmg-root
mkdir -p dist/dmg-root
cp -R dist/ReelPipe.app dist/dmg-root/
ln -s /Applications dist/dmg-root/Applications
hdiutil create -volname ReelPipe -srcfolder dist/dmg-root -ov -format UDZO dist/ReelPipe-macOS.dmg

echo
echo "built dist/ReelPipe.app and dist/ReelPipe-macOS.dmg"
echo "first launch on another mac: right-click the app and pick Open (it isn't notarized)"
