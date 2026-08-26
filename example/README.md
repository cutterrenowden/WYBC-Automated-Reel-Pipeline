# example: tyler gilbert no-hitter

sample: [youtube](https://www.youtube.com/watch?v=WFlYE8F-_xo) (~7 min, 640x360). save it as `gilbert_nohitter.mp4`

install: [python 3.13](https://www.python.org/downloads/), [ffmpeg](https://ffmpeg.org/download.html), [resolve](https://www.blackmagicdesign.com/products/davinciresolve) (optional). mac: [homebrew](https://brew.sh) then `brew install ffmpeg python@3.13`. see the [root README](../README.md).

## 0. setup

from the cloned repo, start the virtual environment (`source .venv/bin/activate`):

```bash
reelpipe doctor
```

before running, satisfy these requirements: ffmpeg on PATH, whisper is installed. this example uses mlx / `large-v3-turbo`.

## 1. transcribe : reelpipe transcribe {file name} {optional count argument} {optional min seconds argument} {optional max seconds argument}

```bash
reelpipe transcribe gilbert_nohitter.mp4 --count 5 --min-seconds 12 --max-seconds 45
```

```
job gilbert-nohitter: 7.3 min, 640x360 @ 29.970 fps
transcribing with mlx / large-v3-turbo
transcript: 145 segments, 837 words
prompt ready: out/gilbert-nohitter/prompt.txt
```

running may take a couple minutes.

local transcription model will output `llm_transcript.txt` with `[m:ss]` prefixes. here is an example of part of the transcription:

```
[6:06] center field Marte
[6:08] it's a no hitter
[6:14] Tyler Gilbert has thrown a no hitter
[6:18] in his first career major league
[6:20] start the first Diamondbacks...
```

## 2. we want to use a llm to determine how to splice the clips. to use a website, copy the prompt to give to ChatGPT/Claude/etc.

```bash
reelpipe prompt gilbert-nohitter --copy
```

paste into [chatgpt](https://chatgpt.com) or [claude](https://claude.ai). save the reply as `out/gilbert-nohitter/response.txt`.


## 3. apply

```bash
reelpipe apply gilbert-nohitter --min-seconds 12 --max-seconds 45
```

from the llm, the pipeline determines the start and endpoints of each clip, and writes `clips.json`.

```
5 picks -> 5 clips
  01     0.00s + 31.4s  match 1.00  first mlb start
  02    84.34s + 12.0s  match 1.00  eight straight retired  <- padded to 12s floor
  03   213.16s + 22.1s  match 1.00  no-hitter through six
  04   257.16s + 40.7s  match 1.00  peralta at the wall
  05   363.84s + 19.3s  match 1.00  gilbert throws a no-hitter
```

## 4. cut the clips according to `clips.json`. uses ffmpeg (make sure its installed)

```bash
reelpipe cut gilbert-nohitter
```

outputs the individual clips along with their transcription files (.srt)


xml/edl point at `gilbert_nohitter.mp4`. relink in resolve if the file isn't next to them.

## resolve

path A if you just want to post. path B if you want to reframe the original.

### A. cut mp4s

1. file → import → media. pick `example/clips/05_gilbert-throws-a-no-hitter.mp4`.
2. new timeline, custom 1080×1920, 29.97 fps.
3. drop the clip. inspector → transform: zoom to fill 9:16, pan if needed.
4. add a subtitle track. import `05_gilbert-throws-a-no-hitter.srt` (times already start at 0).
5. deliver: h.264, 1080×1920.

### B. xml on the original

1. new project, 29.97 fps.
2. file → import → timeline → `example/handoff/reels.xml`. if that fails, import `reels.edl` and point it at your `gilbert_nohitter.mp4`.
3. five clips back to back, still 16:9. timeline settings → 1080×1920. zoom/pan per clip (studio: smart reframe).
4. srts are per-file (each starts at 00:00), not timeline-wide. do not drop all five at 0. easier to caption via path A.

path A matches the srts with no offset math.
