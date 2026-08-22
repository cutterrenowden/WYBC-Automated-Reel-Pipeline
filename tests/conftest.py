import pytest

from reelpipe.config import Config
from reelpipe.transcript import Segment, Transcript, Word

# a stretch of fake play-by-play, one word per 0.4s with a pause between plays
SCRIPT = [
    "the point guard brings it up the floor here in the closing seconds",
    "he pulls up from thirty feet and oh my word it is good",
    "unbelievable shot and this building has completely lost its mind",
    "timeout on the floor as the visitors try to settle things down",
]


@pytest.fixture
def cfg():
    config = Config()
    config.clips.min_seconds = 4.0
    config.clips.max_seconds = 20.0
    config.clips.lead_in = 0.5
    config.clips.lead_out = 0.5
    return config


@pytest.fixture
def transcript():
    segments, clock = [], 0.0
    for line in SCRIPT:
        words = []
        for text in line.split():
            words.append(Word(text, clock, clock + 0.3))
            clock += 0.4
        segments.append(Segment(words[0].start, words[-1].end, line, words))
        clock += 1.5  # pause between plays
    return Transcript("fake.mov", clock, "en", segments)
