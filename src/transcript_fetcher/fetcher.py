"""Fetch every video transcript of a course, in curriculum order."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .captions import parse_cues
from .client import AuthError, BlockedError, UdemyClient, UdemyError
from .curriculum import Course, Lecture, Section, build_sections, choose_caption, parse_captions

log = logging.getLogger(__name__)

Progress = Callable[[int, int, Lecture], None]


def fetch_course(
    client: UdemyClient,
    course: Course,
    lang: str = "en",
    any_lang: bool = False,
    progress: Optional[Progress] = None,
) -> list[Section]:
    """Return the course's sections with video lectures only, transcripts filled in.

    Lectures without a usable caption keep empty ``cues`` and get a ``note``.
    Auth and Cloudflare errors abort; other per-lecture errors are recorded and skipped.
    """
    sections = build_sections(client.curriculum(course.id))
    for section in sections:
        section.lectures = [l for l in section.lectures if l.is_video or l.captions]
    sections = [s for s in sections if s.lectures]

    lectures = [l for s in sections for l in s.lectures]
    for i, lecture in enumerate(lectures, 1):
        if progress:
            progress(i, len(lectures), lecture)
        try:
            _fill_transcript(client, course, lecture, lang, any_lang)
        except (AuthError, BlockedError):
            raise
        except (UdemyError, OSError, ValueError) as exc:
            lecture.note = str(exc)
            log.warning("Lecture %s (%s): %s", lecture.number, lecture.title, exc)
    return sections


def _fill_transcript(client: UdemyClient, course: Course, lecture: Lecture, lang: str, any_lang: bool) -> None:
    if lecture.captions is None:
        lecture.captions = parse_captions(client.lecture_captions(course.id, lecture.id))
    if not lecture.captions:
        lecture.note = "this lecture has no captions"
        return
    caption = choose_caption(lecture.captions, lang, any_lang)
    if caption is None:
        available = ", ".join(sorted({c.label for c in lecture.captions}))
        lecture.note = f"no '{lang}' captions (available: {available})"
        return
    lecture.caption = caption
    lecture.raw = client.download_text(caption.url)
    lecture.cues = parse_cues(lecture.raw)
    if not lecture.cues:
        lecture.note = "caption file was empty"
