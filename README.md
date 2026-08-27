# reelpipe

Point it at a broadcast. Get back short clips cut on the announcer's words, with subtitles and a
DaVinci Resolve timeline.

The pipeline: whisper transcribes locally, an LLM picks the best moments, the picks snap to real
word boundaries, ffmpeg cuts. Drive the LLM with an API key, or paste the prompt into ChatGPT or
Claude for free.

Worked example: [example/](example/).

## Download

Desktop app on the [latest release](https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest).

- macOS: open `ReelPipe-macOS.dmg`, drag to Applications. Unsigned, so right-click and Open the first time.
- Windows: run `ReelPipe-Windows-Setup.exe`.
- Both need ffmpeg: `brew install ffmpeg` or `winget install Gyan.FFmpeg`.

Everything below is for running from source.

## Setup

Python 3.11 to 3.13, plus ffmpeg:

```bash
# macos
brew install ffmpeg python@3.13

# debian / ubuntu
sudo apt install ffmpeg python3.13 python3.13-venv

# windows
winget install Gyan.FFmpeg
winget install Python.Python.3.13
```

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # windows: .venv\Scripts\Activate.ps1

pip install -e ".[apple]"        # apple silicon
pip install -e ".[generic]"      # everything else
pip install -e ".[api]"          # optional, api mode
```

`reelpipe doctor` checks ffmpeg and the whisper backend.

## Desktop app from source

```bash
pip install -e ".[apple,app]"    # or [generic,app]
reelpipe-app
```

Drop a video or audio file, tune the sliders, paste the LLM reply when asked. Preview the clips,
drag the in and out points to fix a splice, delete misses. Settings has dark mode and uninstall.
The app and the CLI share `config.toml` and `out/`.

Builds: `bash packaging/build-macos.sh` or `packaging\build-windows.ps1`, each on its own platform.
Or tag a release and the `release-builds` workflow builds both on GitHub.

## CLI

```bash
# no api key
reelpipe transcribe game.mov
reelpipe prompt game --copy      # paste into chatgpt or claude
# save the reply as out/video/game/response.txt
reelpipe apply game
reelpipe cut game

# with a key
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY
reelpipe run game.mov --mode api
```

Every stage writes files and reads the last stage's files. Rerun any step without redoing
transcription.

## Output

Video jobs land in `out/video/`, audio jobs in `out/audio/` with `.m4a` clips.

```
out/video/game/
  transcript.json       per-word timings
  prompt.txt            paste this
  response.txt          save the reply here
  clips.json            anchored cuts, warnings on anything shaky
  clips/01_the-shot.mp4
  clips/01_the-shot.srt
  handoff/reels.xml     import into resolve
  handoff/reels.edl     fallback timeline
  handoff/clips.csv     titles, timecodes, captions
  handoff/REPORT.md     why each clip got picked
```

In Resolve: import `handoff/reels.xml`, set the timeline vertical, reframe, drop the SRTs on a
subtitle track.

## How the cuts stay accurate

LLMs quote well and read clocks badly. The prompt asks for the first and last words of each clip,
verbatim. Those quotes fuzzy-match against whisper's word timings. Edges then pad, snap into
pauses, and clamp to your length limits. Shaky matches get flagged in `clips.json` and `REPORT.md`
instead of silently miscut.

## Tuning

Copy `config.example.toml` to `config.toml`. CLI flags win.

- `clips.lead_in`: announcers call plays late, so the default backs up 2s.
- `clips.max_seconds` caps length and beats `min_seconds`.
- `prompt.profile`: `sports` or `generic`.
- `energy.enabled` marks loud moments for the model. One extra ffmpeg pass.
- `asr.model`: `large-v3-turbo` by default, `tiny` for a fast check.

Long games split into prompt windows, one `prompt_NN.txt` each. Save matching `response_NN.txt`
files and `apply` reads them all.

## Notes

- `--burn-subs` needs an ffmpeg built with libass. Sidecar SRTs are written either way.
- Clips re-encode, so in points are exact instead of keyframe-snapped.
- First transcribe downloads a whisper model, a few GB.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
