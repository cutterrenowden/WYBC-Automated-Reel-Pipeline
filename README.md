# reelpipe

Point it at a long broadcast, get back short clips cut on the announcer's words, with subtitles and
a timeline you can open in DaVinci Resolve.

The pipeline: transcribe locally with whisper, hand the transcript to an LLM to pick the best
moments, snap those picks to real word boundaries, then cut with ffmpeg. Clips come out 16:9 so you
can reframe to vertical in Resolve.

You can drive the LLM step with an API key, or skip the API entirely and paste the prompt into a
ChatGPT/Claude subscription you already pay for.

Worked example: [example/](example/) — Gilbert no-hitter call at [`example/clips/05_gilbert-throws-a-no-hitter.mp4`](example/clips/05_gilbert-throws-a-no-hitter.mp4).

## Download

The desktop app is on the [latest release](https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest):
`ReelPipe-macOS.zip` (Apple Silicon) or `ReelPipe-Windows.zip`. Install
[ffmpeg](https://ffmpeg.org/download.html), unzip, and run. macOS builds are unsigned, so the
first launch is right-click &rarr; Open. Everything below covers running the pipeline from
source instead.

## Requirements

- [Python](https://www.python.org/downloads/) 3.11, 3.12, or 3.13. Not 3.14 yet (OpenTimelineIO has no 3.14 wheels).
- [ffmpeg](https://ffmpeg.org/download.html) (includes ffprobe) on your PATH.
- [DaVinci Resolve](https://www.blackmagicdesign.com/products/davinciresolve) if you want the timeline handoff. Free version is enough.
- An LLM for the pick step: paste into [ChatGPT](https://chatgpt.com) or [Claude](https://claude.ai), or use an [OpenAI](https://platform.openai.com/api-keys) / [Anthropic](https://console.anthropic.com) API key.
- Whisper runs locally. First transcribe downloads a model (a few GB). CPU-only is slower.

## Setup

Install ffmpeg and Python:

- macOS: [Homebrew](https://brew.sh), then `brew install ffmpeg python@3.13`
- Windows: [ffmpeg builds](https://www.gyan.dev/ffmpeg/builds/) via `winget install Gyan.FFmpeg`, [Python](https://www.python.org/downloads/) via `winget install Python.Python.3.13`
- Linux: distro packages, or the [ffmpeg](https://ffmpeg.org/download.html) / [Python](https://www.python.org/downloads/) installers

```bash
# macOS
brew install ffmpeg python@3.13

# debian / ubuntu
sudo apt install ffmpeg python3.13 python3.13-venv

# fedora
sudo dnf install ffmpeg python3.13

# windows
winget install Gyan.FFmpeg
winget install Python.Python.3.13
```

Then make a venv and install. The extra you want depends on your hardware, because Apple Silicon
gets a much faster whisper via MLX:

```bash
# macos / linux
python3.13 -m venv .venv
source .venv/bin/activate

# windows powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

```bash
pip install -e ".[apple]"      # apple silicon
pip install -e ".[generic]"    # intel mac, linux, windows
pip install -e ".[api]"        # optional, only if you want the api path
```

Check that everything resolved:

```bash
reelpipe doctor
```

That prints where ffmpeg was found, which whisper backends are installed, and which one will be
used. If ffmpeg isn't on your PATH, set `paths.ffmpeg` and `paths.ffprobe` in `config.toml`, or set
the `FFMPEG` and `FFPROBE` environment variables.

## The desktop app

Everything below also comes as a windowed app: drop a video or an audio file (a podcast, a radio
show) on it, tune the knobs with sliders, and it walks the same pipeline stage by stage. In paste
mode it stops to hand you the prompt and take the reply. When the clips are done you can preview
each one in place, fix a bad splice in a trim editor that shows extra footage around the cut and
lets you drag the in/out points, delete misses, and jump straight to the export files. A settings
tab holds a dark mode and a full uninstall (models and settings go, outputs stay).

```bash
pip install -e ".[apple,app]"     # or [generic,app] off apple silicon
reelpipe-app
```

The window and the cli share `config.toml`, the `out/` folder, and every stage's files, so you can
mix them freely — start a job in the app, rerun a stage from the terminal, reopen the job in the
app.

To build the double-clickable app:

```bash
bash packaging/build-macos.sh                                      # dist/ReelPipe.app
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1   # dist\ReelPipe\ReelPipe.exe
```

Builds must be made on the platform they target — or let CI do it: creating a GitHub release
whose tag starts with `v` (or running the `release-builds` workflow against an existing tag)
builds both platforms on GitHub's runners and attaches the zips to the release.

The bundle is large (it carries the whisper backend), ffmpeg still has to be installed on the
machine, and whisper models still download to the user cache on first transcribe. A packaged app
keeps its `config.toml` and `out/` in `~/ReelPipe`. Unsigned macOS builds need the right-click
&rarr; Open dance the first time.

## Quick start, no API key

```bash
# 1. transcribe. slow the first time, since it downloads the model
reelpipe transcribe game.mov

# 2. put the prompt on your clipboard, paste it into chatgpt or claude
reelpipe prompt game --copy

# 3. save the reply as out/game/response.txt, fences and chit-chat are fine

# 4. turn the reply into real timestamps
reelpipe apply game

# 5. render clips, subtitles, and the resolve handoff
reelpipe cut game
```

Every stage writes files and reads what the last one wrote, so you can rerun any step without
redoing transcription.

## With an API key

```bash
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY
reelpipe run game.mov --mode api
```

## What you get

Video sources land in `out/video/`, audio-only sources (podcasts, radio) in `out/audio/`. An
audio job runs the same pipeline and produces the same files, except clips come out as `.m4a`
audio instead of `.mp4`.

```
out/video/game/
  job.json              media info, backend used, word count
  audio.wav             16k mono, what whisper ate
  transcript.json       segments and per-word timings
  transcript.srt        full transcript subtitles
  llm_transcript.txt    timestamped view, what the prompt embeds
  prompt.txt            paste this
  response.txt          you save this
  clips.json            anchored cuts, with a warning on anything shaky
  clips/01_the-shot.mp4 the clip
  clips/01_the-shot.srt subtitles rebased to start at zero
  handoff/reels.xml     fcp7 xml timeline, import this into resolve
  handoff/reels.edl     same cuts as an edl, in case the xml misbehaves
  handoff/clips.csv     titles, timecodes, scores, captions
  handoff/REPORT.md     why each clip got picked, and what to double check
```

In Resolve: import `handoff/reels.xml` as a timeline, set the timeline to vertical, reframe each
clip, and drop the matching `clips/NN_*.srt` on a subtitle track.

## How the cuts stay accurate

LLMs are good at quoting text and bad at reading clocks, so the prompt asks for the first and last
few words of each clip, copied verbatim. Those quotes get fuzzy-matched against whisper's word-level
timings to find the real in and out points. Edges then get padded, nudged into nearby pauses so cuts
don't land mid-breath, and clamped to your min and max length.

Anything that didn't match cleanly is flagged in `clips.json` and `REPORT.md` rather than quietly
cut in the wrong place, so skim the report before you trust a batch.

## Tuning

Copy `config.example.toml` to `config.toml` and edit. CLI flags override the file. The knobs that
matter most:

- `clips.lead_in` defaults to 2 seconds because announcers describe a play a beat after it happens.
  Raise it if clips start too late, lower it if they open on dead air.
- `clips.max_seconds` caps clip length and always wins over `min_seconds`.
- `prompt.profile` is `sports` (hunts for scoring plays, stops, and big calls) or `generic`.
- `energy.enabled` turns on a loudness pass that marks where the audio peaked, so the model can see
  where the announcer got loud. Off by default, costs one extra ffmpeg pass.
- `asr.model` defaults to `large-v3-turbo`. Use `tiny` or `base` for a fast sanity check.

Long games get split into overlapping prompt windows automatically, one `prompt_NN.txt` per window.
Save one `response_NN.txt` per window and `apply` will read them all.

## Notes

- Burning subtitles in (`--burn-subs`) needs an ffmpeg built with libass. Plenty of builds, including
  the current Homebrew one, ship without it. If yours can't, you'll get a clear error and the sidecar
  SRT files are still there. Since you're reframing to vertical anyway, burning captions into a 16:9
  master usually crops them off, so leaving this off is the better default.
- Clips are re-encoded rather than stream-copied, so the in point is exactly where it should be
  instead of snapping to the nearest keyframe.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The end-to-end test generates its own video with ffmpeg and stubs out whisper, so the suite stays
fast and offline.
