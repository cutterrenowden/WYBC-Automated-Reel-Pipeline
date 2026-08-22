"""getting picks out of an llm. tolerant paste parser + optional api call."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

SMART_QUOTES = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2013": "-", "\u2014": "-"}
DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o"}


class SelectionError(RuntimeError):
    pass


@dataclass
class Pick:
    title: str
    start_quote: str
    end_quote: str
    approx_start: float = 0.0
    approx_end: float = 0.0
    score: float = 0.0
    why: str = ""
    caption: str = ""
    hashtags: list = field(default_factory=list)

    def to_dict(self):
        return {"title": self.title, "start_quote": self.start_quote, "end_quote": self.end_quote, "approx_start": self.approx_start, "approx_end": self.approx_end, "score": self.score, "why": self.why, "caption": self.caption, "hashtags": self.hashtags}


def parse_clock(value):
    """accepts 90, "90", "1:30", "0:01:30", "1:30.5". returns seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    parts = text.replace(",", ".").split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return 0.0
    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return total


def strip_noise(text):
    for bad, good in SMART_QUOTES.items():
        text = text.replace(bad, good)
    # drop ```json fences, keep whatever is inside
    return re.sub(r"```[a-zA-Z]*\n?", "", text).replace("```", "")


def extract_array(text):
    """first balanced [...] in the blob, ignoring brackets inside strings."""
    start = text.find("[")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("[", start + 1)
    return ""


def loads_loose(blob):
    """json, but forgive trailing commas."""
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", blob))


def parse(text):
    """llm reply (fences, prose, whatever) -> list of picks."""
    blob = extract_array(strip_noise(text or ""))
    if not blob:
        raise SelectionError("couldn't find a json array in the reply. paste the whole thing including the brackets")
    data = loads_loose(blob)
    if not isinstance(data, list):
        raise SelectionError("expected a json array of clips")
    picks = []
    for index, raw in enumerate(data, start=1):
        if not isinstance(raw, dict):
            continue
        start_quote, end_quote = str(raw.get("start_quote", "")).strip(), str(raw.get("end_quote", "")).strip()
        if not start_quote or not end_quote:
            raise SelectionError(f"clip {index} is missing start_quote or end_quote")
        hashtags = raw.get("hashtags") or []
        picks.append(Pick(str(raw.get("title") or f"clip {index}").strip(), start_quote, end_quote, parse_clock(raw.get("approx_start")), parse_clock(raw.get("approx_end")), float(raw.get("score") or 0), str(raw.get("why") or "").strip(), str(raw.get("caption") or "").strip(), [str(tag) for tag in hashtags]))
    if not picks:
        raise SelectionError("the reply parsed but held no clips")
    return picks


def parse_files(paths):
    picks = []
    for path in paths:
        picks.extend(parse(path.read_text(encoding="utf-8")))
    return picks


def ask_api(cfg, prompt_text):
    provider = cfg.llm.provider
    model = cfg.llm.model or DEFAULT_MODELS.get(provider, "")
    if provider == "anthropic":
        return _anthropic(model, prompt_text)
    if provider == "openai":
        return _openai(model, prompt_text)
    raise SelectionError(f"unknown provider {provider}")


def _anthropic(model, prompt_text):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SelectionError("set ANTHROPIC_API_KEY, or use manual mode and paste the prompt yourself")
    import anthropic

    client = anthropic.Anthropic()
    reply = client.messages.create(model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt_text}])
    return "".join(block.text for block in reply.content if getattr(block, "type", "") == "text")


def _openai(model, prompt_text):
    if not os.environ.get("OPENAI_API_KEY"):
        raise SelectionError("set OPENAI_API_KEY, or use manual mode and paste the prompt yourself")
    from openai import OpenAI

    client = OpenAI()
    reply = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt_text}])
    return reply.choices[0].message.content or ""
