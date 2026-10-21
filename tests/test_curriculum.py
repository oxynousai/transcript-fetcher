from transcript_fetcher.curriculum import Caption, build_sections, choose_caption, parse_captions


def cap(locale, auto=False, label=None):
    return Caption(locale=locale, label=label or locale, url=f"https://cdn/{locale}.vtt", auto=auto)


def test_build_sections_keeps_order_and_drops_quizzes():
    items = [
        {"_class": "lecture", "id": 1, "title": "Welcome", "object_index": 1, "asset": {"asset_type": "Video"}},
        {"_class": "chapter", "id": 10, "title": "Basics", "object_index": 1},
        {"_class": "lecture", "id": 2, "title": "Variables", "object_index": 2, "asset": {"asset_type": "Video", "captions": []}},
        {"_class": "quiz", "id": 3, "title": "Quiz", "object_index": 1},
        {"_class": "chapter", "id": 11, "title": "Advanced", "object_index": 2},
        {"_class": "lecture", "id": 4, "title": "Notes", "object_index": 3, "asset": {"asset_type": "Article"}},
    ]
    sections = build_sections(items)
    assert [(s.number, s.title) for s in sections] == [(0, ""), (1, "Basics"), (2, "Advanced")]
    assert [l.id for s in sections for l in s.lectures] == [1, 2, 4]
    assert sections[0].lectures[0].captions is None  # not in response: look up later
    assert sections[1].lectures[0].captions == []
    assert not sections[2].lectures[0].is_video


def test_parse_captions_detects_auto_and_skips_missing_urls():
    raw = [
        {"locale_id": "en_US", "video_label": "English [Auto]", "url": "https://x/a.vtt", "source": "auto"},
        {"locale_id": "es_ES", "video_label": "Spanish", "url": "https://x/b.srt?token=1"},
        {"locale_id": "fr_FR", "video_label": "French", "url": None},
    ]
    captions = parse_captions(raw)
    assert [(c.locale, c.auto) for c in captions] == [("en_US", True), ("es_ES", False)]
    assert captions[1].extension == "srt"


def test_choose_caption_prefers_language_then_manual_then_exact_locale():
    auto_us, manual_gb = cap("en_US", auto=True), cap("en_GB")
    assert choose_caption([auto_us, manual_gb], "en_US") is manual_gb
    assert choose_caption([cap("en_GB"), cap("en_US")], "en-us").locale == "en_US"
    spanish = cap("es_ES")
    assert choose_caption([spanish], "en") is None
    assert choose_caption([spanish], "en", any_lang=True) is spanish
    # A matching auto caption still beats a human caption in another language.
    assert choose_caption([spanish, auto_us], "en", any_lang=True) is auto_us
