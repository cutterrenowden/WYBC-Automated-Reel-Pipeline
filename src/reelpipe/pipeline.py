"""stage orchestration. each function reads what the last one wrote."""

from __future__ import annotations

import sys
from pathlib import Path

from . import anchor, energy, media, prompt, selection, subtitles
from . import cut as cut_mod
from . import handoff as handoff_mod
from . import transcribe as asr
from .paths import Job
from .transcript import Transcript, write_llm_view, write_srt, write_txt


_log_listener = None


def set_log_listener(fn):
    """the desktop app taps in here to mirror progress lines. pass none to detach."""
    global _log_listener
    _log_listener = fn


def log(message):
    print(message, flush=True)
    if _log_listener:
        try:
            _log_listener(str(message))
        except Exception:
            pass


def doctor(cfg):
    for name in ["ffmpeg", "ffprobe"]:
        try:
            log(f"{name:16} {media.find_tool(name, getattr(cfg.paths, name))}")
        except media.MediaError as err:
            log(f"{name:16} MISSING\n{err}")
    for label, value in asr.backend_report(cfg):
        log(f"{label:16} {value}")
    return 0


def ingest(cfg, source, slug=None):
    source = Path(source).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"no such file: {source}")
    info = media.probe(cfg, source)
    job = Job.create(cfg.paths.out_dir, source, slug, "video" if info.has_video else "audio")
    job.write_meta({"media": info.to_dict()})
    shape = f"{info.width}x{info.height} @ {info.fps:.3f} fps" if info.has_video else "audio only"
    log(f"job {job.slug}: {info.duration / 60:.1f} min, {shape}")
    return job


def transcribe(cfg, job, progress=None, should_cancel=None):
    info = job.read_meta()["media"]
    media.extract_audio(cfg, job.source, job.audio)
    backend = asr.pick_backend(cfg.asr.backend)
    log(f"transcribing with {backend} / {cfg.asr.model}, this is the slow part")
    result = asr.transcribe(cfg, job.audio, info["duration"], progress=progress, should_cancel=should_cancel)
    result.source = str(job.source)
    result.save(job.transcript_json)
    write_srt(result.segments, job.transcript_srt)
    write_txt(result, job.transcript_txt)
    job.write_meta({"asr": {"backend": backend, "model": cfg.asr.model, "language": result.language}, "words": len(result.words())})
    log(f"transcript: {len(result.segments)} segments, {len(result.words())} words")
    return result


def hot_windows(cfg, job):
    if not cfg.energy.enabled:
        return []
    log("measuring loudness")
    return energy.analyse(cfg, job.audio, job.energy_json)["hot_windows"]


def build_prompt(cfg, job):
    result = Transcript.load(job.transcript_json)
    hot = hot_windows(cfg, job)
    write_llm_view(result, job.llm_transcript, hot, cfg.energy.window)
    for stale in job.prompt_files():
        stale.unlink()
    prompts = prompt.build(cfg, result, hot)
    paths = []
    for index, text in enumerate(prompts):
        path = job.prompt_file(index, len(prompts))
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def select_api(cfg, job):
    paths = job.prompt_files() or build_prompt(cfg, job)
    written = []
    for index, path in enumerate(paths, start=1):
        log(f"asking {cfg.llm.provider} about part {index}/{len(paths)}")
        reply = selection.ask_api(cfg, path.read_text(encoding="utf-8"))
        dest = job.root / ("response.txt" if len(paths) == 1 else f"response_{index:02d}.txt")
        dest.write_text(reply, encoding="utf-8")
        written.append(dest)
    return written


def apply_selection(cfg, job):
    responses = job.response_files()
    if not responses:
        raise SystemExit(f"no reply found. save the llm output as {job.root / 'response.txt'} first")
    result = Transcript.load(job.transcript_json)
    picks = selection.parse_files(responses)
    clips = anchor.anchor(cfg, result, picks)
    anchor.save(clips, job.clips_json)
    log(f"{len(picks)} picks -> {len(clips)} clips after overlap pruning")
    for clip in clips:
        flag = f"  <- {'; '.join(clip.warnings)}" if clip.warnings else ""
        log(f"  {clip.index:02d} {clip.start:8.2f}s +{clip.duration:5.1f}s  match {clip.match:.2f}  {clip.title}{flag}")
    return clips


def cut(cfg, job):
    clips = anchor.load(job.clips_json)
    result = Transcript.load(job.transcript_json)
    info = job.read_meta()["media"]
    audio_only = not info.get("has_video", True)
    vertical = cfg.render.vertical and not audio_only
    burn = cfg.render.burn_subs and not audio_only
    frame = (info.get("width") or 1920, info.get("height") or 1080)
    ext = ".m4a" if audio_only else ".mp4"
    job.clips_dir.mkdir(exist_ok=True)
    rendered = []
    for clip in clips:
        words = anchor.words_between(result, clip.start, clip.end)
        srt_path = job.clips_dir / f"{clip.slug}.srt"
        subtitles.write_clip_srt(words, clip, srt_path)
        dest = job.clips_dir / f"{clip.slug}{ext}"
        log(f"cutting {dest.name} ({clip.duration:.1f}s)")
        cues = subtitles.group(words) if burn else None
        cut_mod.cut_clip(cfg, job.source, clip, dest, cues=cues, audio_only=audio_only, vertical=vertical, frame=frame)
        rendered.append(dest)
    return rendered


def handoff(cfg, job):
    clips = anchor.load(job.clips_json)
    info = job.read_meta()["media"]
    job.handoff_dir.mkdir(exist_ok=True)
    written, notes = handoff_mod.write_timeline(job.source, clips, info["fps"], info["duration"], job.handoff_dir)
    written.append(handoff_mod.write_csv(clips, info["fps"], job.handoff_dir / "clips.csv"))
    written.append(handoff_mod.write_report(job, clips, info["fps"], job.handoff_dir / "REPORT.md", notes))
    for note in notes:
        print(note, file=sys.stderr)
    log("handoff: " + ", ".join(path.name for path in written))
    return written
