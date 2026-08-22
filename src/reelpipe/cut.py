"""render the clips with ffmpeg. re-encodes, so the in point is frame accurate."""

from __future__ import annotations

from pathlib import Path

from .media import MediaError, ffmpeg_bin, has_filter, run

BURN_STYLE = "FontName=Arial,FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=0,MarginV=48"
NO_LIBASS = "this ffmpeg has no subtitles filter, so it was built without libass. either use the sidecar srt files (drop --burn-subs) or install an ffmpeg built with libass"


def subtitle_filter(srt_path):
    """named options only, ffmpeg 8 dropped the positional shorthand."""
    return f"subtitles=filename={Path(srt_path).name}:force_style='{BURN_STYLE}'"


def cut_clip(cfg, source, clip, dest, subtitles=None):
    """subtitles is an optional srt to burn in, it must sit next to dest."""
    dest = Path(dest)
    if subtitles and not has_filter(cfg, "subtitles"):
        raise MediaError(NO_LIBASS)
    cmd = [ffmpeg_bin(cfg), "-y", "-v", "error", "-ss", f"{clip.start:.3f}", "-i", str(Path(source).resolve()), "-t", f"{clip.duration:.3f}"]
    if subtitles:
        # run from the clip folder so the filter never sees a windows drive colon
        cmd += ["-vf", subtitle_filter(subtitles)]
    cmd += ["-c:v", "libx264", "-crf", str(cfg.render.crf), "-preset", cfg.render.preset, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", cfg.render.audio_bitrate, "-movflags", "+faststart", dest.name]
    run(cmd, cwd=str(dest.parent))
    return dest
