import pytest

from reelpipe.selection import SelectionError, parse, parse_clock

CLEAN = """[{"title": "the shot", "start_quote": "he pulls up from thirty feet", "end_quote": "it is good", "approx_start": "0:12", "approx_end": "0:20", "score": 9, "why": "big shot", "caption": "cold blooded", "hashtags": ["#hoops"]}]"""

MESSY = """Sure! Here are the best moments:

```json
[
  {
    "title": "The Shot",
    "start_quote": \u201che pulls up from thirty feet\u201d,
    "end_quote": "it is good",
    "approx_start": "0:00:12",
    "score": 9,
  },
]
```

Let me know if you want more!"""


def test_parses_clean_json():
    picks = parse(CLEAN)
    assert len(picks) == 1
    assert picks[0].approx_start == 12.0
    assert picks[0].hashtags == ["#hoops"]


def test_parses_fences_prose_smart_quotes_and_trailing_commas():
    picks = parse(MESSY)
    assert picks[0].start_quote == "he pulls up from thirty feet"
    assert picks[0].approx_start == 12.0
    assert picks[0].approx_end == 0.0


def test_ignores_brackets_inside_strings():
    picks = parse('[{"title": "a [weird] one", "start_quote": "one two three", "end_quote": "four five six"}]')
    assert picks[0].title == "a [weird] one"


def test_rejects_a_reply_with_no_array():
    with pytest.raises(SelectionError):
        parse("i could not find any good clips, sorry")


def test_requires_quotes():
    with pytest.raises(SelectionError):
        parse('[{"title": "x", "start_quote": "", "end_quote": "y"}]')


@pytest.mark.parametrize("raw,seconds", [(90, 90.0), ("90", 90.0), ("1:30", 90.0), ("0:01:30", 90.0), ("1:02:03", 3723.0), ("1:30.5", 90.5), ("", 0.0), ("garbage", 0.0)])
def test_parse_clock(raw, seconds):
    assert parse_clock(raw) == seconds
