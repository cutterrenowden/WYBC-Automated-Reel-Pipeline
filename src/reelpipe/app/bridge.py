"""js <-> python bridge. the ui calls these methods, long work runs on one worker thread
and streams events back by evaluating js in the window. every return value is plain json.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from .. import anchor, media, pipeline, selection, subtitles
from .. import config as config_mod
from .. import cut as cut_mod
from ..cli import copy_to_clipboard
from ..paths import Job
from ..transcribe import backend_report
from ..transcript import Transcript, Word, write_srt, write_txt
from . import diagnostics


def _log_event(event):
    try:
        diagnostics.log_event(event)
    except Exception:
        pass

ASR_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
ENV_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
MIN_CLIP = 1.0
VIDEO_EXTS = ["mp4", "mov", "m4v", "mkv", "avi", "webm", "mpg", "mpeg", "ts", "m2ts", "mts", "wmv", "flv", "mxf"]
AUDIO_EXTS = ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aif", "aiff", "wma"]
CLIP_EXTS = (".mp4", ".m4a")


class Api:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.window = None
        self.event_log = []
        self._seq = 0
        self._emit_lock = threading.Lock()
        self._thread = None
        self._cancel = threading.Event()
        self._queue = []
        pipeline.set_log_listener(lambda line: self._emit("log", line=line))

    _public = None

    @classmethod
    def public_methods(cls):
        """the http fallback exposes exactly the non-underscore bridge methods, so a
        new method is reachable on windows by construction, never a two-place edit.
        built from the class (not the instance) so properties like out_dir aren't fired."""
        if cls._public is None:
            import inspect

            names = set()
            for name in dir(cls):
                if name.startswith("_") or name == "public_methods":
                    continue
                if inspect.isfunction(inspect.getattr_static(cls, name, None)):
                    names.add(name)
            cls._public = frozenset(names)
        return cls._public

    # ---- plumbing ----------------------------------------------------------

    def _config(self, options=None):
        """defaults < config.toml next to base_dir < ui options."""
        explicit = self.base_dir / "config.toml"
        cfg = config_mod.load(str(explicit) if explicit.is_file() else None)
        if not Path(cfg.paths.out_dir).expanduser().is_absolute():
            cfg.paths.out_dir = str(self.base_dir / cfg.paths.out_dir)
        known = {}
        for key, value in (options or {}).items():
            section, _, name = key.partition("_")
            if hasattr(getattr(cfg, section, None), name):
                known[key] = value
        return config_mod.override(cfg, **known)

    @property
    def out_dir(self):
        return Path(self._config().paths.out_dir)

    def _open(self, slug):
        job = Job.open(self.out_dir, slug)
        options = job.read_meta().get("app") or {}
        return self._config(options), job

    def _emit(self, kind, **payload):
        with self._emit_lock:
            self._seq += 1
            event = {"type": kind, "seq": self._seq, **payload}
            self.event_log.append(event)
            del self.event_log[:-400]
        _log_event(event)
        if self.window is not None:
            try:
                self.window.evaluate_js(f"reelApp.onEvent({json.dumps(event)})")
            except Exception:
                # when the webview is broken the poller still delivers events, so a
                # failed push here must not stop the worker thread mid-stage
                pass

    def _busy(self):
        return self._thread is not None and self._thread.is_alive()

    def _launch(self, work):
        if self._busy():
            return {"error": "a job is already running"}
        self._cancel.clear()
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return {"ok": True}

    def _stage(self, name, fn, *args):
        if self._cancel.is_set():
            raise InterruptedError("cancelled")
        self._emit("stage", stage=name, state="running")
        result = fn(*args)
        self._emit("stage", stage=name, state="done")
        return result

    def _fail(self, err, slug=None):
        if isinstance(err, InterruptedError):
            self._emit("cancelled", slug=slug)
        else:
            self._emit("error", message=str(err), slug=slug)

    # ---- first paint -------------------------------------------------------

    def boot(self):
        cfg = self._config()
        doctor = {}
        for name in ("ffmpeg", "ffprobe"):
            try:
                doctor[name] = media.find_tool(name, getattr(cfg.paths, name))
            except media.MediaError:
                doctor[name] = None
        doctor["backends"] = [list(row) for row in backend_report(cfg)]
        defaults = {
            "asr_model": cfg.asr.model if cfg.asr.model in ASR_MODELS else "large-v3-turbo",
            "asr_language": cfg.asr.language,
            "clips_count": cfg.clips.count,
            "clips_target_seconds": cfg.clips.target_seconds,
            "clips_min_seconds": cfg.clips.min_seconds,
            "clips_max_seconds": cfg.clips.max_seconds,
            "clips_lead_in": cfg.clips.lead_in,
            "clips_lead_out": cfg.clips.lead_out,
            "energy_enabled": cfg.energy.enabled,
            "prompt_profile": cfg.prompt.profile,
            "render_burn_subs": cfg.render.burn_subs,
            "render_vertical": cfg.render.vertical,
            "llm_mode": cfg.llm.mode,
            "llm_provider": cfg.llm.provider,
            "llm_model": cfg.llm.model,
        }
        # last-used choices win over config defaults, when they're still valid
        for key, value in (self._ui().get("prefs") or {}).items():
            if key in defaults or key == "length_mode":
                defaults[key] = value
        keys = {name: bool(os.environ.get(var)) for name, var in ENV_KEYS.items()}
        return {"doctor": doctor, "defaults": defaults, "models": ASR_MODELS, "env_keys": keys, "jobs": self.list_jobs(), "out_dir": str(self.out_dir), "busy": self._busy(), "platform": platform.system(), "video_exts": VIDEO_EXTS, "audio_exts": AUDIO_EXTS, "ui": self._ui(), "seq": self._seq}

    # ---- ui prefs (the app's port changes per launch, so browser storage won't do) --

    def _ui_file(self):
        return self.base_dir / ".reelpipe-ui.json"

    def _ui(self):
        try:
            return json.loads(self._ui_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    UI_KEYS = {"dark"}
    # the last-used setup choices, so the form opens where you left it
    PREF_KEYS = {"asr_model", "asr_language", "clips_count", "clips_target_seconds",
                 "clips_min_seconds", "clips_max_seconds", "prompt_profile",
                 "render_burn_subs", "render_vertical", "energy_enabled",
                 "llm_mode", "llm_provider", "length_mode"}

    def set_ui(self, prefs):
        ui = self._ui()
        ui.update({key: value for key, value in dict(prefs or {}).items() if key in self.UI_KEYS})
        self._ui_file().write_text(json.dumps(ui) + "\n", encoding="utf-8")
        return {"ok": True}

    def _save_prefs(self, options):
        ui = self._ui()
        ui["prefs"] = {key: options[key] for key in self.PREF_KEYS if key in options}
        try:
            self._ui_file().write_text(json.dumps(ui) + "\n", encoding="utf-8")
        except OSError:
            pass

    # ---- crash reporting ---------------------------------------------------

    def report_problem(self):
        webbrowser.open(diagnostics.report_url())
        return {"ok": True}

    def copy_diagnostics(self):
        tool = copy_to_clipboard(diagnostics.diagnostics())
        return {"ok": bool(tool)} if tool else {"error": "no clipboard tool found"}

    def open_log(self):
        log = diagnostics.path()
        if not log or not log.is_file():
            return {"error": "no log yet"}
        self._reveal(log, select=True)
        return {"ok": True}

    def list_jobs(self):
        jobs = []
        root = self.out_dir
        if not root.is_dir():
            return jobs
        found = set(root.glob("*/job.json")) | set(root.glob("video/*/job.json")) | set(root.glob("audio/*/job.json"))
        for meta_path in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                job = Job.open(root, meta_path.parent)
                kind = meta_path.parent.parent.name
                if kind not in ("video", "audio"):
                    kind = "video" if job.read_meta().get("media", {}).get("has_video", True) else "audio"
                jobs.append({"slug": job.slug, "ref": str(job.root), "kind": kind, "status": self._status(job)})
            except Exception:
                continue
        return jobs

    def _status(self, job):
        if job.clips_json.is_file():
            clips = anchor.load(job.clips_json)
            done = clips and all(any((job.clips_dir / f"{c.slug}{ext}").is_file() for ext in CLIP_EXTS) for c in clips)
            return "done" if done else "anchored"
        prompts, responses = job.prompt_files(), job.response_files()
        if prompts and len(responses) >= len(prompts):
            return "responded"
        if prompts:
            return "awaiting"
        if job.transcript_json.is_file():
            return "transcribed"
        return "new"

    # ---- picking a file ----------------------------------------------------

    def pick_source(self):
        if self.window is None:
            return None
        import webview

        video = ";".join(f"*.{ext}" for ext in VIDEO_EXTS)
        audio = ";".join(f"*.{ext}" for ext in AUDIO_EXTS)
        filters = (f"Media files ({video};{audio})", f"Video files ({video})", f"Audio files ({audio})")
        picked = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=filters)
        if not picked:
            return None
        return self.inspect(picked[0] if isinstance(picked, (list, tuple)) else picked)

    def inspect(self, path):
        path = Path(str(path)).expanduser()
        if not path.is_file():
            return {"error": f"not a file: {path}"}
        if path.suffix.lower().lstrip(".") not in VIDEO_EXTS + AUDIO_EXTS:
            return {"error": f"only video or audio files can be uploaded, not .{path.suffix.lstrip('.') or '?'}"}
        try:
            info = media.probe(self._config(), path)
        except media.MediaError as err:
            return {"error": str(err)}
        return {"path": str(path), "name": path.name, **info.to_dict()}

    # ---- the run -----------------------------------------------------------

    def _transcribe(self, cfg, job):
        def progress(frac):
            self._emit("progress", stage="transcribe", frac=max(0.0, min(1.0, frac)))

        pipeline.transcribe(cfg, job, progress=progress, should_cancel=self._cancel.is_set)

    def _prep_one(self, cfg, source, options, batch=False):
        """probe, transcribe, prompt. in api mode carry through to finished clips;
        in manual mode stop at the prompt (awaiting for a single job, ready for a batch)."""
        job = self._stage("probe", pipeline.ingest, cfg, source, options.get("slug") or None)
        job.write_meta({"app": options})
        self._emit("job", slug=job.slug, ref=str(job.root))
        self._stage("transcribe", self._transcribe, cfg, job)
        paths = self._stage("prompt", pipeline.build_prompt, cfg, job)
        if cfg.llm.mode == "api":
            self._stage("select", pipeline.select_api, cfg, job)
            self._finish(cfg, job)
        elif batch:
            self._emit("ready", slug=job.slug, ref=str(job.root))
        else:
            self._emit("awaiting", slug=job.slug, ref=str(job.root), prompts=[p.read_text(encoding="utf-8") for p in paths])
        return job

    def _check_api_key(self, options):
        if options.get("llm_mode") == "api":
            provider = options.get("llm_provider") or "anthropic"
            if not os.environ.get(ENV_KEYS.get(provider, "")):
                return f"no {ENV_KEYS[provider]} set. add a key or switch to paste mode"
        return None

    def start(self, source, options):
        options = dict(options or {})
        problem = self._check_api_key(options)
        if problem:
            return {"error": problem}
        cfg = self._config(options)
        try:
            media.find_tool("ffmpeg", cfg.paths.ffmpeg)
        except media.MediaError as err:
            return {"error": str(err)}
        self._save_prefs(options)

        def work():
            job = None
            try:
                job = self._prep_one(cfg, source, options)
            except (Exception, SystemExit) as err:
                self._fail(err, job.slug if job else None)

        return self._launch(work)

    def start_batch(self, sources, options):
        """queue several files, transcribe each back to back. api jobs finish; manual
        jobs land ready in the jobs list to paste at your leisure."""
        sources = [str(s) for s in (sources or [])]
        if len(sources) < 2:
            return self.start(sources[0], options) if sources else {"error": "no files"}
        options = dict(options or {})
        problem = self._check_api_key(options)
        if problem:
            return {"error": problem}
        cfg = self._config(options)
        try:
            media.find_tool("ffmpeg", cfg.paths.ffmpeg)
        except media.MediaError as err:
            return {"error": str(err)}
        self._save_prefs(options)

        def work():
            total = len(sources)
            self._emit("batch_start", total=total)
            done = 0
            for index, source in enumerate(sources, start=1):
                if self._cancel.is_set():
                    break
                name = Path(source).name
                self._emit("batch_item", index=index, total=total, name=name)
                try:
                    self._prep_one(cfg, source, dict(options), batch=True)
                    done += 1
                except InterruptedError:
                    break
                except (Exception, SystemExit) as err:
                    self._emit("log", line=f"{name} failed: {err}")
            self._emit("batch_done", done=done, total=total)

        return self._launch(work)

    def _finish(self, cfg, job):
        if not job.clips_json.is_file():
            self._stage("anchor", pipeline.apply_selection, cfg, job)
        self._stage("cut", pipeline.cut, cfg, job)
        try:
            self._stage("handoff", pipeline.handoff, cfg, job)
        except InterruptedError:
            raise
        except Exception as err:
            # the clips are what matters; a broken timeline writer should not stop the run
            self._emit("stage", stage="handoff", state="error")
            self._emit("log", line=f"handoff failed: {err}")
        self._emit("done", slug=job.slug, ref=str(job.root), results=self.get_results(str(job.root)))

    def check_response(self, text):
        """cheap validation so the paste screen can flag a bad reply before running."""
        try:
            return {"ok": True, "picks": len(selection.parse(text))}
        except selection.SelectionError as err:
            return {"error": str(err)}

    def submit_responses(self, slug, texts):
        cfg, job = self._open(slug)
        texts = [str(t) for t in (texts or [])]
        try:
            for text in texts:
                selection.parse(text)
        except selection.SelectionError as err:
            return {"error": str(err)}
        for stale in job.response_files():
            stale.unlink()
        for index, text in enumerate(texts, start=1):
            name = "response.txt" if len(texts) == 1 else f"response_{index:02d}.txt"
            (job.root / name).write_text(text, encoding="utf-8")
        job.clips_json.unlink(missing_ok=True)

        def work():
            try:
                self._finish(cfg, job)
            except (Exception, SystemExit) as err:
                self._fail(err, job.slug)

        return self._launch(work)

    def burn_captions(self, slug):
        """re-render every clip with captions drawn in, and keep them on for recuts."""
        cfg, job = self._open(slug)
        if not job.clips_json.is_file():
            return {"error": "no clips to burn yet"}
        options = job.read_meta().get("app") or {}
        options["render_burn_subs"] = True
        job.write_meta({"app": options})
        cfg.render.burn_subs = True

        def work():
            try:
                self._stage("cut", pipeline.cut, cfg, job)
                self._emit("done", slug=job.slug, ref=str(job.root), results=self.get_results(str(job.root)))
            except (Exception, SystemExit) as err:
                self._fail(err, job.slug)

        return self._launch(work)

    def finish_job(self, slug):
        """resume a job that already has responses or anchored clips."""
        cfg, job = self._open(slug)

        def work():
            try:
                self._finish(cfg, job)
            except (Exception, SystemExit) as err:
                self._fail(err, job.slug)

        return self._launch(work)

    def cancel(self):
        self._cancel.set()
        return {"ok": True}

    def resume(self, slug):
        _, job = self._open(slug)
        status = self._status(job)
        payload = {"slug": job.slug, "ref": str(job.root), "status": status}
        if status == "awaiting":
            payload["prompts"] = [p.read_text(encoding="utf-8") for p in job.prompt_files()]
            payload["responses"] = [p.read_text(encoding="utf-8") for p in job.response_files()]
        if status in ("done", "anchored"):
            payload["results"] = self.get_results(slug)
        return payload

    # ---- results and splice fixes ------------------------------------------

    def _job_url(self, job):
        rel = job.root.resolve().relative_to(self.out_dir.resolve()).as_posix()
        return f"/jobs/{rel}"

    def _thumbnail(self, cfg, job, clip):
        """first frame of the rendered clip, so cards aren't black boxes before play."""
        mp4 = job.clips_dir / f"{clip.slug}.mp4"
        if not mp4.is_file():
            return None
        thumb = job.clips_dir / f".thumb_{clip.slug}.jpg"
        if not thumb.is_file() or thumb.stat().st_mtime < mp4.stat().st_mtime:
            try:
                media.run([media.ffmpeg_bin(cfg), "-y", "-v", "error", "-i", str(mp4), "-frames:v", "1", "-vf", "scale=480:-2", str(thumb)])
            except media.MediaError:
                return None
        return f"{self._job_url(job)}/clips/{thumb.name}"

    def _clip_row(self, cfg, job, clip):
        row = clip.to_dict()
        ext = next((e for e in CLIP_EXTS if (job.clips_dir / f"{clip.slug}{e}").is_file()), None)
        row["ext"] = ext or ".mp4"
        row["kind"] = "audio" if ext == ".m4a" else "video"
        row["rendered"] = ext is not None
        row["vertical"] = bool(cfg.render.vertical) and row["kind"] == "video"
        row["video"] = f"{self._job_url(job)}/clips/{clip.slug}{ext or '.mp4'}"
        row["poster"] = self._thumbnail(cfg, job, clip) if ext == ".mp4" else None
        return row

    def get_results(self, slug):
        cfg, job = self._open(slug)
        info = job.read_meta().get("media", {})
        clips = []
        for clip in anchor.load(job.clips_json) if job.clips_json.is_file() else []:
            clips.append(self._clip_row(cfg, job, clip))
        report = job.handoff_dir / "REPORT.md"
        handoff_files = sorted(p.name for p in job.handoff_dir.iterdir() if p.is_file()) if job.handoff_dir.is_dir() else []
        return {
            "slug": job.slug,
            "ref": str(job.root),
            "root": str(job.root),
            "duration": info.get("duration", 0.0),
            "burned": bool(cfg.render.burn_subs),
            "clips": clips,
            "handoff": handoff_files,
            "report": report.read_text(encoding="utf-8") if report.is_file() else "",
        }

    def make_preview(self, slug, index, pad=8.0):
        """a quick low-res render of the clip plus context on both sides, so the user
        can see what they'd be splicing in before committing to new times."""
        cfg, job = self._open(slug)
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        pad = min(40.0, max(2.0, float(pad)))
        info = job.read_meta().get("media", {})
        duration = info.get("duration", 0.0)
        window_start = max(0.0, clip.start - pad)
        window_end = min(clip.end + pad, duration) if duration else clip.end + pad
        dest = job.clips_dir / f".preview_{clip.index:02d}.mp4"
        cmd = [media.ffmpeg_bin(cfg), "-y", "-v", "error", "-ss", f"{window_start:.3f}", "-i", str(job.source), "-t", f"{window_end - window_start:.3f}"]
        if info.get("has_video"):
            cmd += ["-vf", "scale=640:-2", "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast"]
        else:
            cmd += ["-vn"]
        cmd += ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest)]
        try:
            media.run(cmd)
        except media.MediaError as err:
            return {"error": str(err)}
        return {"ok": True, "url": f"{self._job_url(job)}/clips/{dest.name}", "window_start": round(window_start, 3), "window_end": round(window_end, 3), "start": clip.start, "end": clip.end}

    def reframe_frame(self, slug, index):
        """a still from the source at the clip midpoint, plus the 9:16 box size, so
        the ui can pan the vertical crop with a real preview."""
        cfg, job = self._open(slug)
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        info = job.read_meta().get("media", {})
        if not info.get("has_video", True):
            return {"error": "audio clips have no video to reframe"}
        iw, ih = info.get("width") or 1920, info.get("height") or 1080
        mid = clip.start + clip.duration / 2
        dest = job.clips_dir / f".reframe_{clip.index:02d}.jpg"
        try:
            media.run([media.ffmpeg_bin(cfg), "-y", "-v", "error", "-ss", f"{mid:.3f}", "-i", str(job.source), "-frames:v", "1", "-vf", "scale=720:-2", str(dest)])
        except media.MediaError as err:
            return {"error": str(err)}
        box_w = min(iw, ih * cut_mod.VERTICAL_W / cut_mod.VERTICAL_H) / iw
        box_h = min(ih, iw * cut_mod.VERTICAL_H / cut_mod.VERTICAL_W) / ih
        return {"ok": True, "url": f"{self._job_url(job)}/clips/{dest.name}?v={self._seq}", "box_w": round(box_w, 4), "box_h": round(box_h, 4), "crop_x": clip.crop_x}

    def reframe_clip(self, slug, index, crop_x):
        cfg, job = self._open(slug)
        if self._busy():
            return {"error": "wait for the current job to finish"}
        info = job.read_meta().get("media", {})
        if not info.get("has_video", True) or not cfg.render.vertical:
            return {"error": "reframing only applies to vertical video clips"}
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        clip.crop_x = min(1.0, max(0.0, float(crop_x)))
        transcript = Transcript.load(job.transcript_json)
        words = anchor.words_between(transcript, clip.start, clip.end)
        cues = subtitles.group(words) if cfg.render.burn_subs else None
        frame = (info.get("width") or 1920, info.get("height") or 1080)
        try:
            cut_mod.cut_clip(cfg, job.source, clip, job.clips_dir / f"{clip.slug}.mp4", cues=cues, vertical=True, frame=frame)
        except media.MediaError as err:
            return {"error": str(err)}
        anchor.save(clips, job.clips_json)
        return {"ok": True, "clip": self._clip_row(cfg, job, clip)}

    def update_clip(self, slug, index, start, end):
        """the splice fixer: new absolute in/out, re-render just that clip."""
        cfg, job = self._open(slug)
        if self._busy():
            return {"error": "wait for the current job to finish"}
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        info = job.read_meta().get("media", {})
        duration = info.get("duration", 0.0)
        audio_only = not info.get("has_video", True)
        start = max(0.0, float(start))
        end = min(float(end), duration) if duration else float(end)
        if end - start < MIN_CLIP:
            return {"error": f"clip must be at least {MIN_CLIP:.0f}s long"}
        clip.start, clip.end = start, end
        if "manually adjusted" not in clip.warnings:
            clip.warnings.append("manually adjusted")
        transcript = Transcript.load(job.transcript_json)
        words = anchor.words_between(transcript, start, end)
        srt = job.clips_dir / f"{clip.slug}.srt"
        subtitles.write_clip_srt(words, clip, srt)
        dest = job.clips_dir / f"{clip.slug}{'.m4a' if audio_only else '.mp4'}"
        cues = subtitles.group(words) if cfg.render.burn_subs and not audio_only else None
        frame = (info.get("width") or 1920, info.get("height") or 1080)
        try:
            cut_mod.cut_clip(cfg, job.source, clip, dest, cues=cues, audio_only=audio_only, vertical=cfg.render.vertical and not audio_only, frame=frame)
        except media.MediaError as err:
            return {"error": str(err)}
        anchor.save(clips, job.clips_json)
        pipeline.handoff(cfg, job)
        return {"ok": True, "clip": self._clip_row(cfg, job, clip)}

    def delete_clip(self, slug, index):
        cfg, job = self._open(slug)
        if self._busy():
            return {"error": "wait for the current job to finish"}
        clips = anchor.load(job.clips_json)
        keep = [c for c in clips if c.index != int(index)]
        if len(keep) == len(clips):
            return {"error": f"no clip {index}"}
        gone = next(c for c in clips if c.index == int(index))
        for name in (f"{gone.slug}.mp4", f"{gone.slug}.m4a", f"{gone.slug}.srt", f".thumb_{gone.slug}.jpg", f".reframe_{gone.index:02d}.jpg"):
            (job.clips_dir / name).unlink(missing_ok=True)
        anchor.save(keep, job.clips_json)
        if keep:
            pipeline.handoff(cfg, job)
        return {"ok": True, "results": self.get_results(slug)}

    # ---- desktop conveniences ----------------------------------------------

    # ---- subtitle text fixes -----------------------------------------------

    @staticmethod
    def _replace_cue_words(transcript, cue, text):
        """swap the words inside one cue's timespan. timing stays, words change."""
        eps = 1e-4
        affected = []
        for segment in transcript.segments:
            hits = [w for w in segment.words if w.start >= cue.start - eps and w.end <= cue.end + eps]
            if hits:
                affected.append((segment, hits))
        if not affected:
            return False
        start = min(w.start for _, hits in affected for w in hits)
        end = max(w.end for _, hits in affected for w in hits)
        for segment, hits in affected:
            gone = {id(w) for w in hits}
            segment.words = [w for w in segment.words if id(w) not in gone]
        pieces = text.split()
        width = (end - start) / len(pieces)
        home = affected[0][0]
        for i, piece in enumerate(pieces):
            home.words.append(Word(piece, start + i * width, start + (i + 1) * width))
        home.words.sort(key=lambda w: w.start)
        for segment, _ in affected:
            segment.text = " ".join(w.text for w in segment.words)
        return True

    def get_subtitles(self, slug, index):
        cfg, job = self._open(slug)
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        transcript = Transcript.load(job.transcript_json)
        cues = subtitles.group(anchor.words_between(transcript, clip.start, clip.end))
        return {"cues": [{"start": cue.start, "end": cue.end, "text": cue.text} for cue in cues]}

    def set_subtitles(self, slug, index, texts):
        cfg, job = self._open(slug)
        if self._busy():
            return {"error": "wait for the current job to finish"}
        clips = anchor.load(job.clips_json)
        clip = next((c for c in clips if c.index == int(index)), None)
        if clip is None:
            return {"error": f"no clip {index}"}
        transcript = Transcript.load(job.transcript_json)
        cues = subtitles.group(anchor.words_between(transcript, clip.start, clip.end))
        texts = [str(t) for t in (texts or [])]
        if len(texts) != len(cues):
            return {"error": "the subtitles changed underneath, reopen the editor"}
        changed = False
        for cue, new in zip(cues, texts):
            new = " ".join(new.split())
            if new and new != cue.text:
                changed = self._replace_cue_words(transcript, cue, new) or changed
        if not changed:
            return {"ok": True, "clip": self._clip_row(cfg, job, clip)}
        transcript.save(job.transcript_json)
        write_srt(transcript.segments, job.transcript_srt)
        write_txt(transcript, job.transcript_txt)
        words = anchor.words_between(transcript, clip.start, clip.end)
        subtitles.write_clip_srt(words, clip, job.clips_dir / f"{clip.slug}.srt")
        info = job.read_meta().get("media", {})
        audio_only = not info.get("has_video", True)
        if cfg.render.burn_subs and not audio_only:
            frame = (info.get("width") or 1920, info.get("height") or 1080)
            try:
                cut_mod.cut_clip(cfg, job.source, clip, job.clips_dir / f"{clip.slug}.mp4", cues=subtitles.group(words), vertical=cfg.render.vertical, frame=frame)
            except media.MediaError as err:
                return {"error": str(err)}
        return {"ok": True, "clip": self._clip_row(cfg, job, clip)}

    def open_folder(self, slug):
        _, job = self._open(slug)
        self._reveal(job.root, select=False)
        return {"ok": True}

    def reveal(self, slug, relative):
        _, job = self._open(slug)
        target = (job.root / str(relative)).resolve()
        if job.root.resolve() not in target.parents or not target.exists():
            return {"error": "no such file"}
        self._reveal(target, select=True)
        return {"ok": True}

    def _reveal(self, path, select):
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", "-R", str(path)] if select else ["open", str(path)])
        elif system == "Windows":
            subprocess.Popen(["explorer", f"/select,{path}"] if select else ["explorer", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent if select else path)])

    def copy_text(self, text):
        tool = copy_to_clipboard(str(text))
        return {"ok": bool(tool)} if tool else {"error": "no clipboard tool found"}

    def paste_text(self):
        """read the clipboard, for the paste-reply button when the webview blocks
        navigator.clipboard. platform read tool, no window on windows."""
        no_window = 0x08000000 if os.name == "nt" else 0
        tools = {
            "Darwin": ["pbpaste"],
            "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            "Linux": ["xclip", "-selection", "clipboard", "-o"],
        }
        cmd = tools.get(platform.system())
        if not cmd or not shutil.which(cmd[0]):
            return {"text": ""}
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=no_window)
            return {"text": out.stdout.rstrip("\n")}
        except (OSError, subprocess.SubprocessError):
            return {"text": ""}

    def open_external(self, url):
        if str(url).startswith(("https://", "http://")):
            webbrowser.open(str(url))
            return {"ok": True}
        return {"error": "refusing a non-http url"}

    # ---- updates -----------------------------------------------------------

    RELEASES_API = "https://api.github.com/repos/cutterrenowden/WYBC-Automated-Reel-Pipeline/releases/latest"

    @staticmethod
    def app_version():
        try:
            import importlib.metadata

            return importlib.metadata.version("reelpipe")
        except Exception:
            return "0.0.0"

    @staticmethod
    def _version_tuple(text):
        parts = []
        for piece in str(text).lstrip("v").split("."):
            digits = "".join(ch for ch in piece if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts)

    def check_update(self):
        """compare the installed version against the newest github release."""
        current = self.app_version()
        try:
            import ssl
            import urllib.request

            try:
                # frozen builds often can't find the system ca bundle, certifi always works
                import certifi

                context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                context = ssl.create_default_context()
            request = urllib.request.Request(self.RELEASES_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "reelpipe"})
            with urllib.request.urlopen(request, timeout=6, context=context) as reply:
                release = json.loads(reply.read().decode("utf-8"))
        except Exception as err:
            print(f"update check failed: {err}", file=sys.stderr)
            return {"current": current, "update": False, "offline": True, "detail": str(err)}
        latest = str(release.get("tag_name", "")).lstrip("v")
        wanted = ".dmg" if platform.system() == "Darwin" else "Setup.exe"
        asset = next((a.get("browser_download_url") for a in release.get("assets", []) if str(a.get("name", "")).endswith(wanted)), None)
        return {
            "current": current,
            "latest": latest,
            "update": bool(latest) and self._version_tuple(latest) > self._version_tuple(current),
            "url": asset or release.get("html_url", ""),
        }

    # ---- uninstall ---------------------------------------------------------

    def _app_bundle(self):
        """the installed program to remove: the .app on mac, the install folder on
        windows. none when running from source."""
        if not getattr(sys, "frozen", False):
            return None
        exe = Path(sys.executable)
        if sys.platform == "darwin":
            return next((p for p in exe.parents if p.suffix == ".app"), None)
        return exe.parent

    def _uninstall_targets(self):
        """everything the program wrote, minus the exported clips in out/. the app
        itself is handled separately, so it isn't in this list."""
        targets = []
        hub = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
        if hub.is_dir():
            for entry in sorted(hub.glob("models--*")):
                if "whisper" in entry.name.lower():
                    targets.append(entry)
        log_dir = diagnostics.path().parent if diagnostics.path() else None
        for extra in (self.base_dir / "config.toml", self._ui_file(), log_dir):
            if extra and Path(extra).exists():
                targets.append(Path(extra))
        return targets

    @staticmethod
    def _pretty_target(path):
        name = path.name
        return name[len("models--"):].replace("--", "/") if name.startswith("models--") else name

    def uninstall_info(self):
        targets = self._uninstall_targets()
        total = 0
        for target in targets:
            total += sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) if target.is_dir() else target.stat().st_size
        app = self._app_bundle()
        names = [self._pretty_target(t) for t in targets]
        if app and app.exists():
            total += sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
            names.insert(0, "the ReelPipe app")
        return {"targets": names, "bytes": total, "frozen": bool(getattr(sys, "frozen", False)), "removes_app": bool(app and app.exists())}

    def uninstall(self):
        removed = []
        for target in self._uninstall_targets():
            try:
                shutil.rmtree(target) if target.is_dir() else target.unlink()
                removed.append(self._pretty_target(target))
            except OSError:
                pass  # a partial removal beats stopping halfway
        quitting = False
        app = self._app_bundle()
        if app and app.exists():
            quitting = self._remove_app(app)
        return {"ok": True, "removed": removed, "frozen": bool(getattr(sys, "frozen", False)), "quitting": quitting}

    def _remove_app(self, app):
        """move the program to the trash (mac) or launch the windows uninstaller,
        then quit so the files aren't locked. returns whether a quit was scheduled."""
        if sys.platform == "darwin":
            try:
                subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{app}"'], timeout=20)
            except (OSError, subprocess.SubprocessError):
                return False
            self._quit_soon()
            return True
        if sys.platform.startswith("win"):
            uninstaller = app / "unins000.exe"
            if not uninstaller.is_file():
                return False
            try:
                subprocess.Popen([str(uninstaller)], creationflags=0x08000000)
            except OSError:
                return False
            self._quit_soon()
            return True
        return False

    def _quit_soon(self):
        def go():
            try:
                if self.window is not None:
                    self.window.destroy()
            except Exception:
                pass
            os._exit(0)

        timer = threading.Timer(1.5, go)
        timer.daemon = True
        timer.start()

    def set_api_key(self, provider, key):
        var = ENV_KEYS.get(str(provider))
        if not var:
            return {"error": f"unknown provider {provider}"}
        key = str(key).strip()
        if key:
            os.environ[var] = key
        return {"ok": True, "set": bool(key)}
