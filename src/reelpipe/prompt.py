"""prompt building. same text whether you paste it or spend api money."""

from __future__ import annotations

from .transcript import llm_view

SCHEMA = """[
  {
    "title": "short punchy name for the clip",
    "start_quote": "the first 8-12 words of the clip, copied VERBATIM from the transcript",
    "end_quote": "the last 8-12 words of the clip, copied VERBATIM from the transcript",
    "approx_start": "h:mm:ss of the start, from the nearest timestamp marker",
    "approx_end": "h:mm:ss of the end",
    "score": 8,
    "why": "one sentence on why this works as a reel",
    "caption": "a social caption, no more than 150 chars",
    "hashtags": ["#tag", "#tag"]
  }
]"""

SPORTS = """You are cutting short vertical highlight reels out of a live sports broadcast.

All you get is the play-by-play audio transcript. There is no face on camera, so the announcer's
words are the only signal you have about what happened on the field.

Look for:
- scoring plays, and the call that lands right on them
- big defensive stops, turnovers, saves, and momentum swings
- lead changes, ties broken, and anything late and close
- calls where the announcer clearly gets loud or loses composure
- short bits of color commentary that land as a joke or a story on their own

Avoid:
- ad reads, station idents, and promos
- dead air, filler between plays, and pure stat recitation
- anything that only makes sense if you watched the previous ten minutes"""

GENERIC = """You are cutting short vertical clips out of a long recording.

Look for self-contained moments: a clear idea with a hook, a punchline, or a strong statement.

Avoid intros, housekeeping, ad reads, and anything that needs earlier context to land."""

PROFILES = {"sports": SPORTS, "generic": GENERIC}

RULES = """Rules:
- Pick the {count} best moments, ranked best first.
- Each clip must be between {min_seconds:.0f} and {max_seconds:.0f} seconds long.
- Start the clip on the buildup, not on the payoff. The announcer usually describes a play a beat
  after it happens, so back up to where the sequence starts.
- Start and end on a complete thought. Never start or end mid-sentence.
- start_quote and end_quote must be copied word for word from the transcript below, exactly as
  written, including any misspellings. Do not paraphrase, do not clean them up. They are how the
  tool finds your clip in the audio, so if you reword them the clip will be cut in the wrong place.
- Similar phrasing repeats throughout, so make each quote long enough to be unique, and always
  fill in approx_start so a duplicate phrase can be told apart.
- Do not let clips overlap each other.

Reply with nothing but a JSON array matching this shape:
{schema}"""

LOUD_NOTE = "\nLines marked [LOUD] are where the audio peaked, usually the announcer raising their voice.\n"


def build_windows(segments, max_words, overlap_words):
    """split a long game into overlapping chunks so each prompt fits in a chat window."""
    usable = [seg for seg in segments if seg.text.strip()]
    counts = [len(seg.text.split()) for seg in usable]
    if sum(counts) <= max_words:
        return [usable]
    windows, start = [], 0
    while start < len(usable):
        total, stop = 0, start
        while stop < len(usable) and total + counts[stop] <= max_words:
            total += counts[stop]
            stop += 1
        stop = max(stop, start + 1)
        windows.append(usable[start:stop])
        if stop >= len(usable):
            break
        back, trimmed = 0, stop
        while trimmed > start + 1 and back < overlap_words:
            trimmed -= 1
            back += counts[trimmed]
        start = trimmed
    return windows


def render(cfg, segments, hot_windows=(), part=1, total=1):
    profile = PROFILES.get(cfg.prompt.profile, SPORTS)
    header = profile
    if total > 1:
        share = max(2, -(-cfg.clips.count // total))
        header += f"\n\nThis is part {part} of {total} of one long recording. Pick the best {share} moments from this part only."
    rules = RULES.format(count=max(2, -(-cfg.clips.count // total)) if total > 1 else cfg.clips.count, min_seconds=cfg.clips.min_seconds, max_seconds=cfg.clips.max_seconds, schema=SCHEMA)
    loud = LOUD_NOTE if hot_windows else ""
    body = llm_view(segments, hot_windows, cfg.energy.window)
    return f"{header}\n\n{rules}\n{loud}\nTranscript (timestamps are h:mm:ss from the start of the recording):\n\n{body}"


def build(cfg, transcript, hot_windows=()):
    """returns a list of prompt strings, usually just one."""
    windows = build_windows(transcript.segments, cfg.prompt.max_words_per_window, cfg.prompt.window_overlap_words)
    return [render(cfg, window, hot_windows, index + 1, len(windows)) for index, window in enumerate(windows)]
