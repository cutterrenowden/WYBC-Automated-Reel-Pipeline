"""end to end on a generated clip. skips whisper, exercises everything around it."""

import json
import shutil
import subprocess

import pytest

from reelpipe import media, pipeline
from reelpipe.config import Config

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")

RESPONSE = """here you go!

```json
[
  {"title": "The Shot", "start_quote": "he pulls up from thirty feet", "end_quote": "it is good", "approx_start": "0:07", "score": 9, "caption": "cold blooded", "hashtags": ["#hoops"]},
  {"title": "Timeout", "start_quote": "timeout on the floor", "end_quote": "settle things down", "approx_start": "0:18", "score": 6}
]
```
"""


def make_video(path, seconds=26):
    """16:9 bars plus a tone, close enough to a broadcast for plumbing tests."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@pytest.fixture
def job(tmp_path, transcript):
    cfg = Config()
    cfg.paths.out_dir = str(tmp_path / "out")
    cfg.clips.min_seconds, cfg.clips.max_seconds = 4.0, 20.0
    cfg.clips.lead_in, cfg.clips.lead_out = 0.5, 0.5
    source = make_video(tmp_path / "game.mp4")
    job = pipeline.ingest(cfg, source)
    # stand in for whisper so tests stay fast and offline
    transcript.source = str(source)
    transcript.save(job.transcript_json)
    (job.root / "response.txt").write_text(RESPONSE, encoding="utf-8")
    return cfg, job


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def test_ingest_reads_the_media(job):
    _, handle = job
    info = handle.read_meta()["media"]
    assert info["width"] == 640 and info["height"] == 360
    assert info["fps"] == pytest.approx(30.0)
    assert info["duration"] == pytest.approx(26.0, abs=0.5)


def test_prompt_gets_written(job):
    cfg, handle = job
    paths = pipeline.build_prompt(cfg, handle)
    assert len(paths) == 1
    assert "start_quote" in paths[0].read_text(encoding="utf-8")
    assert handle.llm_transcript.is_file()


def test_apply_then_cut_then_handoff(job):
    cfg, handle = job
    clips = pipeline.apply_selection(cfg, handle)
    assert [clip.title for clip in clips] == ["The Shot", "Timeout"]
    assert all(clip.match > 0.9 for clip in clips)
    assert all(4.0 <= clip.duration <= 20.0 for clip in clips)

    rendered = pipeline.cut(cfg, handle)
    assert len(rendered) == 2
    for path, clip in zip(rendered, clips):
        assert path.is_file()
        assert probe_duration(path) == pytest.approx(clip.duration, abs=0.35)
        assert path.with_suffix(".srt").read_text(encoding="utf-8").strip()

    written = pipeline.handoff(cfg, handle)
    names = {path.name for path in written}
    assert {"reels.xml", "clips.csv", "REPORT.md"} <= names
    xml = (handle.handoff_dir / "reels.xml").read_text(encoding="utf-8")
    assert "game.mp4" in xml
    assert "The Shot".lower().replace(" ", "-") in (handle.handoff_dir / "clips.csv").read_text(encoding="utf-8")


def test_clips_json_round_trips(job):
    cfg, handle = job
    pipeline.apply_selection(cfg, handle)
    rows = json.loads(handle.clips_json.read_text(encoding="utf-8"))
    assert rows[0]["slug"] == "01_the-shot"
    assert rows[0]["duration"] > 0


def test_burn_subs_renders_when_the_build_can(job):
    cfg, handle = job
    cfg.render.burn_subs = True
    pipeline.apply_selection(cfg, handle)
    if not media.has_filter(cfg, "subtitles"):
        with pytest.raises(media.MediaError, match="libass"):
            pipeline.cut(cfg, handle)
        return
    assert all(path.stat().st_size > 1000 for path in pipeline.cut(cfg, handle))
