"""turn the llm's quotes into real timestamps.

the model is good at quoting and bad at clocks, so we trust the quotes and find them in the
word-level transcript ourselves.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .paths import slugify

TOKEN = re.compile(r"[a-z0-9']+")
# how far a candidate can sit from the model's guess before we start penalising it
PROXIMITY_TOKENS = 600.0
PROXIMITY_WEIGHT = 0.2
# windows sharing fewer than this share of tokens with the quote aren't worth scoring
PREFILTER_SHARE = 0.4


@dataclass
class Clip:
    index: int
    title: str
    start: float
    end: float
    score: float = 0.0
    why: str = ""
    caption: str = ""
    hashtags: list = field(default_factory=list)
    match: float = 0.0
    warnings: list = field(default_factory=list)

    @property
    def duration(self):
        return max(0.0, self.end - self.start)

    @property
    def slug(self):
        return f"{self.index:02d}_{slugify(self.title)[:48] or 'clip'}"

    def to_dict(self):
        return {"index": self.index, "title": self.title, "start": round(self.start, 3), "end": round(self.end, 3), "duration": round(self.duration, 3), "score": self.score, "why": self.why, "caption": self.caption, "hashtags": self.hashtags, "match": round(self.match, 3), "warnings": self.warnings, "slug": self.slug}

    @classmethod
    def from_dict(cls, data):
        return cls(int(data["index"]), data["title"], float(data["start"]), float(data["end"]), float(data.get("score", 0)), data.get("why", ""), data.get("caption", ""), list(data.get("hashtags", [])), float(data.get("match", 0)), list(data.get("warnings", [])))


@dataclass
class WordIndex:
    """flat token stream plus a map back to the word each token came from."""

    words: list
    tokens: list
    owners: list

    @classmethod
    def build(cls, words):
        tokens, owners = [], []
        for index, word in enumerate(words):
            for token in tokenize(word.text):
                tokens.append(token)
                owners.append(index)
        return cls(words, tokens, owners)

    def word_of(self, token_index):
        if not self.owners:
            return None
        return self.words[self.owners[min(max(token_index, 0), len(self.owners) - 1)]]

    def token_near(self, seconds):
        """first token at or after a wall-clock time, for proximity weighting."""
        target = word_at_time(self.words, seconds)
        return next((index for index, owner in enumerate(self.owners) if owner >= target), 0)


def tokenize(text):
    return TOKEN.findall(str(text).lower())


def best_match(tokens, needle, near=None):
    """sliding window over the transcript, best ratio wins, ties go to whoever is closer to `near`."""
    if not tokens or not needle:
        return 0, 0, 0.0
    size = min(len(needle), len(tokens))
    wanted = set(needle)
    floor = max(1, int(PREFILTER_SHARE * size))
    hits = sum(1 for token in tokens[:size] if token in wanted)
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(needle)
    best, best_at, scored = -1.0, -1, 0
    for start in range(0, len(tokens) - size + 1):
        if start:
            hits -= tokens[start - 1] in wanted
            hits += tokens[start + size - 1] in wanted
        if hits < floor:
            continue
        scored += 1
        matcher.set_seq1(tokens[start : start + size])
        ratio = matcher.ratio()
        if near is not None:
            ratio -= PROXIMITY_WEIGHT * min(1.0, abs(start - near) / PROXIMITY_TOKENS)
        if ratio > best:
            best, best_at = ratio, start
    if best_at < 0:
        # nothing shared enough tokens to bother scoring, so the quote isn't in here
        return 0, size - 1, 0.0
    matcher.set_seq1(tokens[best_at : best_at + size])
    return best_at, best_at + size - 1, matcher.ratio()


def word_at_time(words, seconds):
    for index, word in enumerate(words):
        if word.end >= seconds:
            return index
    return max(0, len(words) - 1)


def snap_start(words, when, pause):
    """don't start mid-word, and if there's a real pause just before, start inside it."""
    for index, word in enumerate(words):
        if word.start <= when < word.end:
            when = word.start
            if index:
                gap = word.start - words[index - 1].end
                if gap >= pause:
                    when = words[index - 1].end + gap / 2
            break
    return when


def snap_end(words, when, pause):
    for index, word in enumerate(words):
        if word.start < when <= word.end:
            when = word.end
            if index + 1 < len(words):
                gap = words[index + 1].start - word.end
                if gap >= pause:
                    when = word.end + gap / 2
            break
    return when


def anchor_one(cfg, transcript, pick, index, word_index=None):
    words = word_index.words if word_index else transcript.words()
    word_index = word_index or WordIndex.build(words)
    tokens, warnings = word_index.tokens, []
    if not tokens:
        return Clip(index, pick.title, pick.approx_start, pick.approx_end, pick.score, pick.why, pick.caption, list(pick.hashtags), 0.0, ["transcript had no words, using the model's times"])
    near = word_index.token_near(pick.approx_start) if pick.approx_start > 0 else None

    head, tail = tokenize(pick.start_quote), tokenize(pick.end_quote)
    head_at, head_end, head_ratio = best_match(tokens, head, near)
    offset = head_end + 1
    tail_at, tail_end, tail_ratio = best_match(tokens[offset:], tail, None)
    tail_at, tail_end = tail_at + offset, tail_end + offset
    if tail_ratio < cfg.clips.match_threshold:
        # maybe the model quoted out of order, so try the whole thing
        alt_at, alt_end, alt_ratio = best_match(tokens, tail, near)
        if alt_ratio > tail_ratio:
            tail_at, tail_end, tail_ratio = alt_at, alt_end, alt_ratio

    match = min(head_ratio, tail_ratio)
    if head_ratio < cfg.clips.match_threshold:
        warnings.append(f"start quote only matched {head_ratio:.2f}, timing may be off")
    if tail_ratio < cfg.clips.match_threshold:
        warnings.append(f"end quote only matched {tail_ratio:.2f}, timing may be off")

    if match < cfg.clips.match_threshold and pick.approx_end > pick.approx_start:
        start, end = pick.approx_start, pick.approx_end
        warnings.append("fell back to the model's approximate times")
    else:
        first, last = word_index.word_of(head_at), word_index.word_of(tail_end)
        if last.end <= first.start:
            last = word_index.word_of(head_end)
            warnings.append("end landed before the start, clipped short")
        start = snap_start(words, first.start - cfg.clips.lead_in, cfg.clips.pause_snap)
        end = snap_end(words, last.end + cfg.clips.lead_out, cfg.clips.pause_snap)

    limit = transcript.duration or (words[-1].end if words else end)
    # the cap always wins, so a config with min above max can't fight itself
    floor = min(cfg.clips.min_seconds, cfg.clips.max_seconds)
    start, end = max(0.0, start), min(end, limit)
    if end - start > cfg.clips.max_seconds:
        end = start + cfg.clips.max_seconds
        warnings.append(f"trimmed to the {cfg.clips.max_seconds:.0f}s cap")
    if end - start < floor:
        end = min(limit, start + floor)
        start = max(0.0, min(start, end - floor))
        warnings.append(f"padded up to the {floor:.0f}s floor")

    return Clip(index, pick.title, start, end, pick.score, pick.why, pick.caption, list(pick.hashtags), match, warnings)


def overlap(a, b):
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def drop_overlaps(clips, tolerance=0.5):
    """keep the higher scored clip when two picks cover the same play."""
    kept = []
    for clip in sorted(clips, key=lambda c: (-c.score, c.start)):
        if any(overlap(clip, other) > tolerance * min(clip.duration, other.duration) for other in kept):
            continue
        kept.append(clip)
    kept.sort(key=lambda c: c.start)
    for index, clip in enumerate(kept, start=1):
        clip.index = index
    return kept


def anchor(cfg, transcript, picks):
    word_index = WordIndex.build(transcript.words())
    clips = [anchor_one(cfg, transcript, pick, index, word_index) for index, pick in enumerate(picks, start=1)]
    return drop_overlaps([clip for clip in clips if clip.duration > 0.5])


def words_between(transcript, start, end):
    return [word for word in transcript.words() if word.end > start and word.start < end]


def save(clips, path):
    Path(path).write_text(json.dumps([clip.to_dict() for clip in clips], indent=2) + "\n", encoding="utf-8")
    return Path(path)


def load(path):
    return [Clip.from_dict(row) for row in json.loads(Path(path).read_text(encoding="utf-8"))]
