"""whisper backends. mlx on apple silicon, faster-whisper everywhere else."""

from __future__ import annotations

import importlib.util
import platform

from .transcript import Segment, Transcript, Word

# mlx wants an hf repo, faster-whisper wants a short name. the mlx-community repos
# use a -mlx suffix for every size except large-v3-turbo, which has no suffix
MLX_REPOS = {"tiny": "mlx-community/whisper-tiny-mlx", "base": "mlx-community/whisper-base-mlx", "small": "mlx-community/whisper-small-mlx", "medium": "mlx-community/whisper-medium-mlx", "large-v3": "mlx-community/whisper-large-v3-mlx", "large-v3-turbo": "mlx-community/whisper-large-v3-turbo"}


class AsrError(RuntimeError):
    pass


def installed(module):
    return importlib.util.find_spec(module) is not None


def is_apple_silicon():
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def pick_backend(name="auto"):
    if name == "auto":
        if is_apple_silicon() and installed("mlx_whisper"):
            return "mlx"
        if installed("faster_whisper"):
            return "faster-whisper"
        extra = "apple" if is_apple_silicon() else "generic"
        raise AsrError(f"no asr backend installed. try: pip install -e \".[{extra}]\"")
    if name == "mlx" and not installed("mlx_whisper"):
        raise AsrError("mlx-whisper isn't installed. apple silicon only: pip install -e \".[apple]\"")
    if name == "faster-whisper" and not installed("faster_whisper"):
        raise AsrError("faster-whisper isn't installed: pip install -e \".[generic]\"")
    return name


def transcribe(cfg, audio_path, duration=0.0, progress=None, should_cancel=None):
    backend = pick_backend(cfg.asr.backend)
    language = cfg.asr.language or None
    if backend == "mlx":
        segments, detected = _mlx(cfg.asr.model, audio_path, language, should_cancel)
    else:
        segments, detected = _faster_whisper(cfg, audio_path, language, duration, progress, should_cancel)
    total = duration or (segments[-1].end if segments else 0.0)
    return Transcript(str(audio_path), total, detected or (language or ""), segments)


def _mlx(model, audio_path, language, should_cancel=None):
    import mlx_whisper

    # mlx runs as one blocking call: honor a cancel on the way in, but there is no
    # in-flight progress or interrupt hook, so mid-transcription cancel isn't possible here
    if should_cancel and should_cancel():
        raise InterruptedError("cancelled")
    repo = model if "/" in model else MLX_REPOS.get(model, f"mlx-community/whisper-{model}-mlx")
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=repo, word_timestamps=True, language=language, verbose=None)
    if should_cancel and should_cancel():
        raise InterruptedError("cancelled")
    segments = [_segment(seg["start"], seg["end"], seg["text"], [(w["word"], w["start"], w["end"]) for w in seg.get("words", [])]) for seg in result.get("segments", [])]
    return segments, result.get("language", "")


def _faster_whisper(cfg, audio_path, language, duration=0.0, progress=None, should_cancel=None):
    from faster_whisper import WhisperModel

    model = WhisperModel(cfg.asr.model, device=cfg.asr.device, compute_type=cfg.asr.compute_type)
    raw, info = model.transcribe(str(audio_path), word_timestamps=True, language=language, vad_filter=True)
    total = duration or getattr(info, "duration", 0.0) or 0.0
    # faster-whisper yields segments lazily, so this loop is where real progress and a
    # responsive mid-transcription cancel live
    segments = []
    for seg in raw:
        if should_cancel and should_cancel():
            raise InterruptedError("cancelled")
        segments.append(_segment(seg.start, seg.end, seg.text, [(w.word, w.start, w.end) for w in (seg.words or [])]))
        if progress and total:
            progress(seg.end / total)
    if progress:
        progress(1.0)
    return segments, getattr(info, "language", "") or ""


def _segment(start, end, text, raw_words):
    words = [Word(str(text_).strip(), float(begin), float(finish)) for text_, begin, finish in raw_words if str(text_).strip()]
    # whisper sometimes drops word timings, fall back to the segment span
    if not words and str(text).strip():
        words = [Word(str(text).strip(), float(start), float(end))]
    return Segment(float(start), float(end), str(text).strip(), words)


def backend_report(cfg):
    """for `reelpipe doctor`."""
    rows = [("apple silicon", "yes" if is_apple_silicon() else "no"), ("mlx-whisper", "installed" if installed("mlx_whisper") else "missing"), ("faster-whisper", "installed" if installed("faster_whisper") else "missing")]
    try:
        rows.append(("chosen backend", pick_backend(cfg.asr.backend)))
    except AsrError as err:
        rows.append(("chosen backend", f"none ({err})"))
    return rows
