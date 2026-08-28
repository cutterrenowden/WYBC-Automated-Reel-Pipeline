from reelpipe.prompt import build, build_windows
from reelpipe.transcript import Segment, Word, llm_view


def many_segments(count=40, words_per=5):
    """fine grained segments, like a real transcript, so overlap has room to work."""
    segments, clock = [], 0.0
    for index in range(count):
        words = []
        for slot in range(words_per):
            words.append(Word(f"w{index}x{slot}", clock, clock + 0.3))
            clock += 0.4
        segments.append(Segment(words[0].start, words[-1].end, " ".join(w.text for w in words), words))
    return segments


def test_single_window_for_a_short_transcript(cfg, transcript):
    prompts = build(cfg, transcript)
    assert len(prompts) == 1
    assert "start_quote" in prompts[0]
    assert "VERBATIM" in prompts[0]


def test_sports_profile_talks_about_plays(cfg, transcript):
    assert "play-by-play" in build(cfg, transcript)[0]


def test_generic_profile_does_not(cfg, transcript):
    cfg.prompt.profile = "generic"
    assert "play-by-play" not in build(cfg, transcript)[0]


def test_long_transcripts_get_split_with_overlap(cfg, transcript):
    segments = many_segments()
    windows = build_windows(segments, 50, 15)
    assert len(windows) > 1
    assert set(map(id, windows[0])) & set(map(id, windows[1]))  # the overlap is real
    transcript.segments = segments
    cfg.prompt.max_words_per_window = 50
    cfg.prompt.window_overlap_words = 15
    prompts = build(cfg, transcript)
    assert len(prompts) == len(windows)
    assert "part 1 of" in prompts[0]


def test_windows_cover_everything(cfg, transcript):
    segments = many_segments()
    windows = build_windows(segments, 37, 11)
    seen = {id(seg) for window in windows for seg in window}
    assert seen == {id(seg) for seg in segments}


def test_a_single_huge_segment_still_makes_progress():
    segments = many_segments(count=3, words_per=80)
    windows = build_windows(segments, 10, 5)
    assert len(windows) == 3  # each window has to take at least one segment


def test_loud_markers_only_show_when_asked(transcript):
    plain = llm_view(transcript.segments)
    marked = llm_view(transcript.segments, hot_windows=[0], window=1.0)
    assert "[LOUD]" not in plain
    assert "[LOUD]" in marked


def test_llm_view_has_timestamps(transcript):
    assert llm_view(transcript.segments).startswith("[0:00]")


def test_target_length_softens_the_rules(cfg, transcript):
    from reelpipe import prompt
    from reelpipe.config import clip_bounds

    cfg.clips.target_seconds = 30.0
    text = prompt.build(cfg, transcript)[0]
    assert "roughly 30 seconds" in text
    assert "Stay between 12 and 60 seconds" in text
    assert clip_bounds(cfg.clips) == (12.0, 60.0)

    cfg.clips.target_seconds = 0.0
    text = prompt.build(cfg, transcript)[0]
    assert "must be between" in text
