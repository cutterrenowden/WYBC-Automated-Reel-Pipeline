from reelpipe.anchor import Clip, words_between
from reelpipe.handoff import timecode
from reelpipe.subtitles import group, write_clip_srt
from reelpipe.transcript import srt_time, write_srt


def test_srt_time_format():
    assert srt_time(0) == "00:00:00,000"
    assert srt_time(3723.456) == "01:02:03,456"
    assert srt_time(-5) == "00:00:00,000"


def test_cues_break_on_pauses(transcript):
    cues = group(transcript.words(), max_chars=200, max_seconds=100)
    assert len(cues) == 4  # one per play, split by the 1.5s gaps


def test_cues_break_on_length(transcript):
    cues = group(transcript.words(), max_chars=20)
    assert all(len(cue.text) <= 20 for cue in cues)


def test_clip_srt_is_rebased_to_zero(tmp_path, transcript):
    clip = Clip(1, "shot", 12.0, 22.0)
    words = words_between(transcript, clip.start, clip.end)
    path = write_clip_srt(words, clip, tmp_path / "clip.srt")
    body = path.read_text(encoding="utf-8")
    stamps = [line.split(" --> ") for line in body.splitlines() if "-->" in line]
    assert body.startswith("1\n00:00:0")
    # first cue lines up with the first word, and nothing runs past the clip
    assert stamps[0][0] == srt_time(words[0].start - clip.start)
    assert all(end <= srt_time(clip.duration) for _, end in stamps)


def test_empty_words_writes_an_empty_srt(tmp_path):
    path = write_srt([], tmp_path / "none.srt")
    assert path.read_text(encoding="utf-8") == ""


def test_timecode_frames():
    assert timecode(0, 30) == "00:00:00:00"
    assert timecode(1.5, 30) == "00:00:01:15"
    assert timecode(3661.0, 25) == "01:01:01:00"
