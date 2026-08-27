# ReelPipe

Point it at a broadcast. Get back short clips cut on the announcer's words, with subtitles and a
DaVinci Resolve timeline. Works on video and audio (podcasts, radio).

How it works: whisper transcribes locally, an LLM picks the best moments, ffmpeg cuts them. Paste
the prompt into ChatGPT or Claude for free, or use an API key.

## Install

1. Download the app from the [latest release](https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest): `ReelPipe-macOS.dmg` or `ReelPipe-Windows-Setup.exe`.
2. Install ffmpeg: `brew install ffmpeg` on macOS, `winget install Gyan.FFmpeg` on Windows.
3. macOS only: the app is unsigned, so right-click and Open the first time.

## Use

Drop a file on the app. Pick clip count and length. Copy the prompt into ChatGPT or Claude and
paste the reply back. Preview the clips, drag the in and out points to fix any splice, delete
misses. Clips, subtitles, and the Resolve timeline land in the job folder.

In Resolve: import `handoff/reels.xml`, set the timeline vertical, reframe, drop the SRTs on a
subtitle track.

Worked example: [example/](example/).

## Developers

From-source setup, the CLI, builds, and tuning: [DEVELOPING.md](DEVELOPING.md).
