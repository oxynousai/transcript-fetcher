from transcript_fetcher.captions import format_timestamp, parse_cues, parse_timestamp, to_paragraphs, transcript_text

VTT = """﻿WEBVTT
Kind: captions

NOTE this is a comment

STYLE
::cue { color: white }

1
00:00:00.000 --> 00:00:02.500 align:start position:0%
Hello <c.yellow>and</c> welcome

00:00:02.500 --> 00:00:04.000
to the course &amp; enjoy.

00:00:04.000 --> 00:00:05.000
to the course &amp; enjoy.

01:02.000 --> 01:03.500
<v Instructor>Short form timestamp.</v>
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
First line
second line

2
00:00:03,500 --> 00:00:05,000
Next cue.
"""


def test_parse_timestamp_variants():
    assert parse_timestamp("00:00:01.500") == 1.5
    assert parse_timestamp("01:02.250") == 62.25
    assert parse_timestamp("01:00:00,000") == 3600


def test_parse_vtt_strips_tags_entities_and_duplicates():
    cues = parse_cues(VTT)
    assert [c.text for c in cues] == ["Hello and welcome", "to the course & enjoy.", "Short form timestamp."]
    assert cues[1].end == 5.0  # merged duplicate extends the cue
    assert cues[2].start == 62.0


def test_parse_srt_joins_multiline_cues():
    cues = parse_cues(SRT.replace("\n", "\r\n"))
    assert [c.text for c in cues] == ["First line second line", "Next cue."]
    assert cues[0].start == 1.0


def test_paragraphs_break_on_sentence_end_after_target():
    cues = parse_cues(SRT)
    assert to_paragraphs(cues, target=10) == [(1.0, "First line second line Next cue.")]
    sentences = [type(cues[0])(float(i), float(i + 1), "Word word word.") for i in range(6)]
    paragraphs = to_paragraphs(sentences, target=30)
    assert [start for start, _ in paragraphs] == [0.0, 2.0, 4.0]


def test_paragraphs_hard_max_without_punctuation():
    cue = parse_cues(SRT)[0]
    cues = [type(cue)(float(i), float(i + 1), "no punctuation here") for i in range(10)]
    assert len(to_paragraphs(cues, target=20, hard_max=60)) == 4


def test_transcript_text_with_timestamps():
    text = transcript_text(parse_cues(VTT), timestamps=True)
    assert text.startswith("[00:00] Hello and welcome")
    assert format_timestamp(3725) == "1:02:05"
