"""resolve handoff: a timeline you can import, a csv you can skim, a report you can read."""

from __future__ import annotations

import csv
from pathlib import Path


def timecode(seconds, fps):
    """hh:mm:ss:ff, non drop frame."""
    fps = fps or 30.0
    frames = int(round(max(0.0, seconds) * fps))
    per_hour, per_minute = int(round(fps * 3600)), int(round(fps * 60))
    hours, frames = divmod(frames, per_hour)
    minutes, frames = divmod(frames, per_minute)
    secs, frames = divmod(frames, int(round(fps)))
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def build_timeline(source, clips, fps, duration, name="reels"):
    import opentimelineio as otio

    def frames(seconds):
        return otio.opentime.RationalTime(round(seconds * fps), fps)

    timeline = otio.schema.Timeline(name=name)
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(track)
    span = otio.opentime.TimeRange(frames(0), frames(duration or 0.0))
    for clip in clips:
        reference = otio.schema.ExternalReference(target_url=Path(source).resolve().as_uri(), available_range=span)
        track.append(otio.schema.Clip(name=clip.slug, media_reference=reference, source_range=otio.opentime.TimeRange(frames(clip.start), frames(clip.duration))))
    return timeline


def write_timeline(source, clips, fps, duration, out_dir, name="reels"):
    """fcp7 xml is the one resolve likes best, edl is the fallback."""
    import opentimelineio as otio

    out_dir = Path(out_dir)
    timeline = build_timeline(source, clips, fps, duration, name)
    written, notes = [], []
    xml_path = out_dir / f"{name}.xml"
    otio.adapters.write_to_file(timeline, str(xml_path), adapter_name="fcp_xml")
    written.append(xml_path)
    try:
        edl_path = out_dir / f"{name}.edl"
        otio.adapters.write_to_file(timeline, str(edl_path), adapter_name="cmx_3600")
        written.append(edl_path)
    except Exception as err:
        notes.append(f"edl skipped: {err}")
    return written, notes


def write_csv(clips, fps, path):
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "slug", "title", "start_tc", "end_tc", "start_s", "end_s", "duration_s", "score", "match", "caption", "hashtags", "warnings"])
        for clip in clips:
            writer.writerow([clip.index, clip.slug, clip.title, timecode(clip.start, fps), timecode(clip.end, fps), f"{clip.start:.3f}", f"{clip.end:.3f}", f"{clip.duration:.3f}", clip.score, f"{clip.match:.2f}", clip.caption, " ".join(clip.hashtags), "; ".join(clip.warnings)])
    return path


def write_report(job, clips, fps, path, notes=()):
    lines = [f"# {job.slug}", "", f"source: `{job.source}`", f"clips: {len(clips)}", ""]
    for clip in clips:
        lines += [f"## {clip.index:02d}. {clip.title}", "", f"- timecode: `{timecode(clip.start, fps)}` to `{timecode(clip.end, fps)}` ({clip.duration:.1f}s)", f"- seconds: {clip.start:.2f} to {clip.end:.2f}", f"- score: {clip.score} | quote match: {clip.match:.2f}"]
        if clip.why:
            lines.append(f"- why: {clip.why}")
        if clip.caption:
            lines.append(f"- caption: {clip.caption}")
        if clip.hashtags:
            lines.append(f"- hashtags: {' '.join(clip.hashtags)}")
        if clip.warnings:
            lines.append(f"- check this one: {'; '.join(clip.warnings)}")
        lines.append("")
    if notes:
        lines += ["## notes", ""] + [f"- {note}" for note in notes] + [""]
    lines += ["## resolve", "", "1. import `reels.xml` (or `reels.edl` if the xml misbehaves) as a timeline.", "2. set the timeline to vertical, then reframe each clip with transform or smart reframe.", "3. drop the matching `clips/NN_*.srt` onto a subtitle track per clip.", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return Path(path)
