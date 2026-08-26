# example: tyler gilbert no-hitter

sample: [youtube](https://www.youtube.com/watch?v=WFlYE8F-_xo) (~7 min, 640x360). save it as `gilbert_nohitter.mp4` (not in this repo).

this folder is a checked-in run of that video: cuts, captions, and resolve files. your own jobs still go to `out/` (gitignored).

install: [python 3.13](https://www.python.org/downloads/), [ffmpeg](https://ffmpeg.org/download.html), [resolve](https://www.blackmagicdesign.com/products/davinciresolve) (optional). mac: [homebrew](https://brew.sh) then `brew install ffmpeg python@3.13`. see the [root README](../README.md).

## 0. setup

from the cloned repo, venv on (`source .venv/bin/activate`):

```bash
reelpipe doctor
```

preflight: ffmpeg on PATH, which whisper backend is installed. this example used mlx / `large-v3-turbo`.

## 1. transcribe

```bash
reelpipe transcribe gilbert_nohitter.mp4 --count 5 --min-seconds 12 --max-seconds 45
```

```
job gilbert-nohitter: 7.3 min, 640x360 @ 29.970 fps
transcribing with mlx / large-v3-turbo
transcript: 145 segments, 837 words
prompt ready: out/gilbert-nohitter/prompt.txt
```

~2 min including model download.

whisper writes word timings. `llm_transcript.txt` is that text with `[m:ss]` prefixes. the last clip comes from:

```
[6:06] center field Marte
[6:08] it's a no hitter
[6:14] Tyler Gilbert has thrown a no hitter
[6:18] in his first career major league
[6:20] start the first Diamondbacks
```

## 2. llm pick

```bash
reelpipe prompt gilbert-nohitter --copy
```

paste into [chatgpt](https://chatgpt.com) or [claude](https://claude.ai). save the reply as `out/gilbert-nohitter/response.txt`.

the prompt asks for 5 clips, 12–45s, with `start_quote` / `end_quote` copied verbatim. five titles this run:

1. first mlb start
2. eight straight retired
3. no-hitter through six
4. peralta at the wall
5. gilbert throws a no-hitter

## 3. apply

```bash
reelpipe apply gilbert-nohitter --min-seconds 12 --max-seconds 45
```

fuzzy-matches those quotes onto whisper word times. writes `clips.json`.

```
5 picks -> 5 clips
  01     0.00s + 31.4s  match 1.00  first mlb start
  02    84.34s + 12.0s  match 1.00  eight straight retired  <- padded to 12s floor
  03   213.16s + 22.1s  match 1.00  no-hitter through six
  04   257.16s + 40.7s  match 1.00  peralta at the wall
  05   363.84s + 19.3s  match 1.00  gilbert throws a no-hitter
```

## 4. cut

```bash
reelpipe cut gilbert-nohitter
```

ffmpeg slices the source. sidecar `.srt` per clip, times start at 0. then resolve handoff files.

the copies in this folder are that output.

## the clip: no-hitter call

[`clips/05_gilbert-throws-a-no-hitter.mp4`](clips/05_gilbert-throws-a-no-hitter.mp4) — 19.3s, source 00:06:03–00:06:23, match 1.00

announcer: *center field Marte / it's a no hitter / Tyler Gilbert has thrown a no hitter in his first career major league start*

sidecar captions: [`05_gilbert-throws-a-no-hitter.srt`](clips/05_gilbert-throws-a-no-hitter.srt)

other cuts from the same run (same `clips/` folder):

| file | source tc | dur |
|---|---|---|
| `01_first-mlb-start.mp4` | 00:00:00–00:00:31 | 31.4s |
| `02_eight-straight-retired.mp4` | 00:01:24–00:01:36 | 12.0s |
| `03_no-hitter-through-six.mp4` | 00:03:33–00:03:55 | 22.1s |
| `04_peralta-at-the-wall.mp4` | 00:04:17–00:04:57 | 40.7s |

## what's in here

```
example/
  clips/     mp4 + matching srt
  handoff/   resolve xml/edl, csv, report
  clips.json start/end seconds used to cut
```

- `clips/*.srt` — captions for that mp4. not burned in.
- `clips.json` — start/end seconds, match score, warnings.
- `handoff/reels.xml` — fcp7 timeline of the five cuts on the source file.
- `handoff/reels.edl` — same cuts, fallback if xml import fails.
- `handoff/clips.csv` — titles, timecodes, scores, captions. spreadsheet, not a timeline.
- `handoff/REPORT.md` — same info readable, plus why each clip was picked.

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
