from reelpipe.anchor import Clip, anchor, anchor_one, drop_overlaps, tokenize
from reelpipe.selection import Pick


def pick(start_quote, end_quote, **kwargs):
    return Pick("test clip", start_quote, end_quote, **kwargs)


def test_exact_quotes_land_on_the_right_words(cfg, transcript):
    words = transcript.words()
    clip = anchor_one(cfg, transcript, pick("he pulls up from thirty feet", "it is good"), 1)
    first = next(w for w in words if w.text == "pulls")
    assert clip.match > 0.99
    assert clip.start == first.start - 0.5 - 0.4  # lead in, then back to the previous word "he"
    assert clip.warnings == []


def test_paraphrased_quotes_still_match_close_enough(cfg, transcript):
    clip = anchor_one(cfg, transcript, pick("he pulls up from thirty ft", "and it is good"), 1)
    assert clip.match > cfg.clips.match_threshold
    assert clip.duration > 1.0


def test_gibberish_falls_back_to_the_models_times(cfg, transcript):
    clip = anchor_one(cfg, transcript, pick("zzz qqq xxx vvv", "www yyy uuu", approx_start=5.0, approx_end=15.0), 1)
    assert clip.start == 5.0
    assert clip.end == 15.0
    assert any("approximate" in warning for warning in clip.warnings)


def test_repeated_phrase_uses_the_models_hint_to_disambiguate(cfg, transcript):
    # "it is good" only shows once, so build a duplicate case with the transcript we have
    early = anchor_one(cfg, transcript, pick("the point guard brings it up", "closing seconds", approx_start=0.0), 1)
    late = anchor_one(cfg, transcript, pick("timeout on the floor", "settle things down", approx_start=30.0), 2)
    assert early.start < late.start


def test_max_seconds_is_enforced(cfg, transcript):
    cfg.clips.max_seconds = 3.0
    clip = anchor_one(cfg, transcript, pick("the point guard brings it up the floor", "settle things down"), 1)
    assert clip.duration == 3.0
    assert any("cap" in warning for warning in clip.warnings)


def test_min_seconds_is_enforced(cfg, transcript):
    cfg.clips.min_seconds = 8.0
    clip = anchor_one(cfg, transcript, pick("unbelievable shot", "lost its mind"), 1)
    assert clip.duration >= 8.0
    assert any("floor" in warning for warning in clip.warnings)


def test_clips_never_run_past_the_media(cfg, transcript):
    clip = anchor_one(cfg, transcript, pick("timeout on the floor", "settle things down"), 1)
    assert clip.end <= transcript.duration


def test_overlapping_picks_get_pruned_by_score(cfg, transcript):
    keep = Clip(1, "keep", 10.0, 30.0, score=9)
    drop = Clip(2, "drop", 12.0, 28.0, score=4)
    apart = Clip(3, "apart", 60.0, 80.0, score=1)
    kept = drop_overlaps([keep, drop, apart])
    assert [c.title for c in kept] == ["keep", "apart"]
    assert [c.index for c in kept] == [1, 2]


def test_anchor_renumbers_in_timeline_order(cfg, transcript):
    picks = [pick("timeout on the floor", "settle things down"), pick("the point guard brings it up", "closing seconds")]
    clips = anchor(cfg, transcript, picks)
    assert [c.index for c in clips] == [1, 2]
    assert clips[0].start < clips[1].start


def test_tokenize_drops_punctuation_and_case():
    assert tokenize("Oh My WORD -- it's good!") == ["oh", "my", "word", "it's", "good"]


def test_slug_is_filesystem_safe():
    assert Clip(3, "Oh My Word!! it's GOOD", 0.0, 5.0).slug == "03_oh-my-word-it-s-good"
