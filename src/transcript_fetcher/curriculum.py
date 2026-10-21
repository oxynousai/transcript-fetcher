"""Turn Udemy curriculum items into ordered sections and lectures, and pick captions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .captions import Cue

VIDEO_ASSET_TYPES = {"video", "videomashup"}


@dataclass
class Course:
    id: int
    title: str
    slug: str
    url: str


@dataclass
class Caption:
    locale: str  # e.g. "en_US"
    label: str  # e.g. "English [Auto]"
    url: str
    auto: bool

    @property
    def extension(self) -> str:
        path = self.url.split("?", 1)[0].lower()
        return "srt" if path.endswith(".srt") else "vtt"


@dataclass
class Lecture:
    id: int
    number: int
    title: str
    asset_type: str
    # None means the curriculum response did not include captions and they
    # must be looked up per lecture; [] means the lecture has none.
    captions: Optional[list[Caption]]
    caption: Optional[Caption] = None
    raw: Optional[str] = None
    cues: list[Cue] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def is_video(self) -> bool:
        return self.asset_type.lower() in VIDEO_ASSET_TYPES


@dataclass
class Section:
    number: int
    title: str
    lectures: list[Lecture] = field(default_factory=list)


def parse_captions(raw: Optional[Iterable[dict[str, Any]]]) -> list[Caption]:
    captions = []
    for item in raw or []:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        locale = item.get("locale_id") or item.get("language") or ""
        label = item.get("video_label") or item.get("title") or locale
        auto = str(item.get("source", "")).lower() == "auto" or "[auto]" in label.lower()
        captions.append(Caption(locale=locale, label=label, url=url, auto=auto))
    return captions


def build_sections(items: Iterable[dict[str, Any]]) -> list[Section]:
    """Group curriculum items (already in course order) into sections of lectures.

    Quizzes, practice tests and coding exercises are dropped. Lectures that appear
    before the first chapter go into a section numbered 0.
    """
    sections: list[Section] = []
    current: Optional[Section] = None
    lecture_count = 0
    for item in items:
        kind = item.get("_class")
        if kind == "chapter":
            current = Section(number=item.get("object_index") or len(sections) + 1, title=item.get("title") or "")
            sections.append(current)
        elif kind == "lecture":
            lecture_count += 1
            if current is None:
                current = Section(number=0, title="")
                sections.append(current)
            asset = item.get("asset") or {}
            current.lectures.append(
                Lecture(
                    id=item["id"],
                    number=item.get("object_index") or lecture_count,
                    title=item.get("title") or "",
                    asset_type=asset.get("asset_type") or "",
                    captions=parse_captions(asset["captions"]) if "captions" in asset else None,
                )
            )
    return sections


def _normalize_locale(value: str) -> str:
    return value.replace("-", "_").lower()


def choose_caption(captions: list[Caption], lang: str = "en", any_lang: bool = False) -> Optional[Caption]:
    """Pick the best caption track for ``lang`` ("en" or "en_US").

    Order of preference: requested language over others, human-made over
    auto-generated, exact locale over same language. Other languages are only
    considered when ``any_lang`` is set.
    """
    wanted = _normalize_locale(lang)
    best: Optional[tuple[tuple[int, bool, int], Caption]] = None
    for caption in captions:
        locale = _normalize_locale(caption.locale)
        if locale == wanted:
            rank = 0
        elif locale.split("_")[0] == wanted.split("_")[0]:
            rank = 1
        elif any_lang:
            rank = 2
        else:
            continue
        key = (int(rank == 2), caption.auto, rank)
        if best is None or key < best[0]:
            best = (key, caption)
    return best[1] if best else None
