# -*- mode: python ; coding: utf-8 -*-
# build with: pyinstaller --noconfirm packaging/reelpipe-app.spec  (run from the repo root)
# the whisper backends drag in torch/numba (mac) or ctranslate2/onnx (windows),
# so expect a fat bundle. whisper models still download to ~/.cache on first run.

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent

# read the version so the .app info.plist shows it in finder's get info
with open(ROOT / "pyproject.toml", "rb") as fh:
    APP_VERSION = tomllib.load(fh)["project"]["version"]

datas = [(str(ROOT / "src/reelpipe/app/web"), "reelpipe/app/web")]
binaries = []
hiddenimports = ["reelpipe", "reelpipe.app.main"]

# otio discovers its adapters through entry points, which need the dist metadata around.
# reelpipe's own metadata carries the version the update checker reports.
for dist in ["opentimelineio", "otio-fcp-adapter", "otio-cmx3600-adapter", "reelpipe"]:
    datas += copy_metadata(dist)
hiddenimports += ["otio_fcp_adapter", "otio_cmx3600_adapter"]

# the otio adapters ship plugin manifests as package data, so collect them fully
collect = ["opentimelineio", "otio_fcp_adapter", "otio_cmx3600_adapter"]
if sys.platform == "darwin":
    # mlx ships metal kernels as data, tiktoken loads its encodings via a plugin package
    collect += ["mlx", "mlx_whisper"]
    hiddenimports += ["tiktoken_ext", "tiktoken_ext.openai_public"]
else:
    # faster-whisper carries the silero vad model in its assets
    collect += ["faster_whisper", "ctranslate2"]

for package in collect:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# static ffmpeg/ffprobe fetched by packaging/fetch_ffmpeg.py, so installs are one-click
ffmpeg_bin = ROOT / "packaging" / "ffmpeg-bin"
if ffmpeg_bin.is_dir():
    binaries += [(str(p), "ffmpeg-bin") for p in ffmpeg_bin.iterdir() if p.is_file()]

a = Analysis(
    [str(ROOT / "packaging/launch.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

icon_file = ROOT / "packaging" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ReelPipe",
    console=False,
    upx=False,
    icon=str(icon_file) if icon_file.is_file() else None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="ReelPipe", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ReelPipe.app",
        icon=str(icon_file) if icon_file.is_file() else None,
        bundle_identifier="org.wybc.reelpipe",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            # the ui and clip previews come off a loopback http server
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
