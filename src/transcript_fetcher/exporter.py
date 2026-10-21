"""Write fetched transcripts to disk in course order."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .captions import transcript_text
from .curriculum import Course, Lecture, Section

FORMATS = ("md", "txt", "json")
_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(value: str, max_length: int = 100) -> str:
    """A file name that is valid on Windows, macOS and Linux."""
    name = _UNSAFE_RE.sub("", value)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:max_length].rstrip(" .") or "untitled"
    return f"{name}_" if name.split(".")[0].upper() in _WINDOWS_RESERVED else name


def section_heading(section: Section) -> str:
    if section.number == 0:
        return section.title or "Course content"
    return f"Section {section.number}: {section.title}".rstrip(": ")


def _missing_text(lecture: Lecture) -> str:
    return f"(No transcript: {lecture.note or 'unavailable'})"


def render_markdown(course: Course, sections: list[Section], lang: str, timestamps: bool) -> str:
    out = [f"# {course.title}", "", f"Source: {course.url}  ", f"Transcript language: {lang} · Fetched {date.today()}", ""]
    for section in sections:
        out += [f"## {section_heading(section)}", ""]
        for lecture in section.lectures:
            out += [f"### {lecture.number}. {lecture.title}", ""]
            if lecture.cues:
                if lecture.caption and lecture.caption.auto:
                    out += [f"*Captions: {lecture.caption.label}*", ""]
                out += [transcript_text(lecture.cues, timestamps), ""]
            else:
                out += [f"*{_missing_text(lecture)}*", ""]
    return "\n".join(out)


def render_text(course: Course, sections: list[Section], timestamps: bool) -> str:
    out = [course.title, "=" * len(course.title), course.url, ""]
    for section in sections:
        heading = section_heading(section)
        out += ["", heading, "-" * len(heading), ""]
        for lecture in section.lectures:
            out += [f"[{lecture.number}] {lecture.title}", ""]
            out += [transcript_text(lecture.cues, timestamps) if lecture.cues else _missing_text(lecture), ""]
    return "\n".join(out)


def render_json(course: Course, sections: list[Section], lang: str) -> str:
    def lecture_data(lecture: Lecture) -> dict[str, Any]:
        caption = lecture.caption
        return {
            "id": lecture.id,
            "number": lecture.number,
            "title": lecture.title,
            "caption": {"locale": caption.locale, "label": caption.label, "auto": caption.auto} if caption else None,
            "note": lecture.note,
            "transcript": transcript_text(lecture.cues) if lecture.cues else None,
            "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in lecture.cues],
        }

    data = {
        "course": {"id": course.id, "title": course.title, "url": course.url},
        "language": lang,
        "fetched": str(date.today()),
        "sections": [
            {"number": s.number, "title": s.title, "lectures": [lecture_data(l) for l in s.lectures]} for s in sections
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def lecture_filenames(sections: list[Section], numbered: bool = True) -> dict[int, str]:
    """Map lecture id to ``"001 - Video title.txt"`` (or ``"Video title.txt"``), unique per folder."""
    lectures = [l for s in sections for l in s.lectures]
    width = max(3, len(str(max((l.number for l in lectures), default=0))))
    names: dict[int, str] = {}
    used: set[str] = set()
    for lecture in lectures:
        stem = safe_name(lecture.title)
        if numbered:
            stem = f"{lecture.number:0{width}d} - {stem}"
        candidate, n = stem, 2
        while candidate.lower() in used:  # Windows and macOS file names ignore case
            candidate, n = f"{stem} ({n})", n + 1
        used.add(candidate.lower())
        names[lecture.id] = f"{candidate}.txt"
    return names


def lecture_file_text(section: Section, lecture: Lecture, timestamps: bool = False) -> str:
    return f"{lecture.title}\n{section_heading(section)}\n\n{transcript_text(lecture.cues, timestamps)}\n"


def write_course(
    course: Course,
    sections: list[Section],
    out_dir: Path,
    fmt: str = "md",
    lang: str = "en",
    timestamps: bool = False,
    split: bool = False,
    raw: bool = False,
) -> Path:
    """Write the combined transcript (plus optional per-lecture and raw caption files).

    Returns the path of the combined file.
    """
    course_dir = out_dir / safe_name(course.slug)
    course_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "md":
        content = render_markdown(course, sections, lang, timestamps)
    elif fmt == "txt":
        content = render_text(course, sections, timestamps)
    elif fmt == "json":
        content = render_json(course, sections, lang)
    else:
        raise ValueError(f"unknown format {fmt!r}")
    combined = course_dir / f"{safe_name(course.slug)}.{fmt}"
    combined.write_text(content + "\n", encoding="utf-8")

    if split or raw:
        lectures = [l for s in sections for l in s.lectures]
        sec_width = max(2, len(str(max((s.number for s in sections), default=0))))
        lec_width = max(3, len(str(max((l.number for l in lectures), default=0))))
        for section in sections:
            folder = f"{section.number:0{sec_width}d} - {safe_name(section.title or 'Course content')}"
            for lecture in section.lectures:
                stem = f"{lecture.number:0{lec_width}d} - {safe_name(lecture.title)}"
                if split and lecture.cues:
                    path = course_dir / "lectures" / folder / f"{stem}.txt"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"{lecture.title}\n\n{transcript_text(lecture.cues, timestamps)}\n", encoding="utf-8")
                if raw and lecture.raw is not None and lecture.caption:
                    path = course_dir / "captions" / folder / f"{stem}.{lecture.caption.locale}.{lecture.caption.extension}"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(lecture.raw, encoding="utf-8")
    return combined
