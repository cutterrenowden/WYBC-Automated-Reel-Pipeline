"""per-job folder layout. every stage reads and writes files in here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "job"


@dataclass
class Job:
    slug: str
    root: Path

    @classmethod
    def create(cls, out_dir, source, slug=None):
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"no such file: {source}")
        job = cls(slug or slugify(source.stem), Path(out_dir).expanduser() / slugify(slug or source.stem))
        job.root.mkdir(parents=True, exist_ok=True)
        job.clips_dir.mkdir(exist_ok=True)
        job.handoff_dir.mkdir(exist_ok=True)
        job.write_meta({"slug": job.slug, "source": str(source)})
        return job

    @classmethod
    def open(cls, out_dir, ref):
        """ref is either a slug or a path to a job folder."""
        candidate = Path(ref).expanduser()
        root = candidate if candidate.is_dir() else Path(out_dir).expanduser() / slugify(ref)
        if not (root / "job.json").is_file():
            raise FileNotFoundError(f"no job at {root}, run transcribe first")
        return cls(slugify(root.name), root)

    @property
    def meta_json(self):
        return self.root / "job.json"

    @property
    def audio(self):
        return self.root / "audio.wav"

    @property
    def transcript_json(self):
        return self.root / "transcript.json"

    @property
    def transcript_srt(self):
        return self.root / "transcript.srt"

    @property
    def transcript_txt(self):
        return self.root / "transcript.txt"

    @property
    def llm_transcript(self):
        return self.root / "llm_transcript.txt"

    @property
    def energy_json(self):
        return self.root / "energy.json"

    @property
    def clips_json(self):
        return self.root / "clips.json"

    @property
    def clips_dir(self):
        return self.root / "clips"

    @property
    def handoff_dir(self):
        return self.root / "handoff"

    def prompt_file(self, index=0, total=1):
        return self.root / ("prompt.txt" if total == 1 else f"prompt_{index + 1:02d}.txt")

    def prompt_files(self):
        return sorted(self.root.glob("prompt*.txt"))

    def response_files(self):
        return sorted(self.root.glob("response*.txt"))

    def read_meta(self):
        return json.loads(self.meta_json.read_text(encoding="utf-8"))

    def write_meta(self, patch):
        meta = self.read_meta() if self.meta_json.is_file() else {}
        meta.update(patch)
        self.meta_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    @property
    def source(self):
        return Path(self.read_meta()["source"])
