"""Parse WebVTT / SRT caption files into cues and readable paragraphs."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TIME = r"(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}"
_TIMING_RE = re.compile(rf"({_TIME})\s*-->\s*({_TIME})")
_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"[.?!][\"')\]]*$")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def parse_timestamp(value: str) -> float:
    """Convert ``01:02:03.456``, ``02:03.456`` or ``00:02:03,456`` to seconds."""
    parts = value.replace(",", ".").split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def _clean(line: str) -> str:
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub("", line))).strip()


def parse_cues(content: str) -> list[Cue]:
    """Parse a WebVTT or SRT document into cues, dropping exact consecutive repeats."""
    content = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n[ \t]*\n", content):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            match = _TIMING_RE.search(line)
            if match:
                break
        else:
            continue  # WEBVTT header, NOTE, STYLE or REGION block
        text = " ".join(t for t in (_clean(l) for l in lines[i + 1 :]) if t)
        if not text:
            continue
        start, end = parse_timestamp(match.group(1)), parse_timestamp(match.group(2))
        if cues and cues[-1].text == text:
            cues[-1].end = max(cues[-1].end, end)
            continue
        cues.append(Cue(start, end, text))
    return cues


def to_paragraphs(cues: list[Cue], target: int = 500, hard_max: int = 1200) -> list[tuple[float, str]]:
    """Group cues into paragraphs of roughly ``target`` characters.

    A paragraph closes at the first sentence end past ``target`` characters, or
    unconditionally at ``hard_max`` (auto-generated captions can lack punctuation).
    Returns ``(start_seconds, text)`` pairs.
    """
    paragraphs: list[tuple[float, str]] = []
    buf: list[str] = []
    start = 0.0
    length = 0
    for cue in cues:
        if not buf:
            start = cue.start
        buf.append(cue.text)
        length += len(cue.text) + 1
        if length >= hard_max or (length >= target and _SENTENCE_END_RE.search(cue.text)):
            paragraphs.append((start, " ".join(buf)))
            buf, length = [], 0
    if buf:
        paragraphs.append((start, " ".join(buf)))
    return paragraphs


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def transcript_text(cues: list[Cue], timestamps: bool = False) -> str:
    """Render cues as blank-line separated paragraphs, optionally prefixed with ``[mm:ss]``."""
    paragraphs = to_paragraphs(cues)
    if timestamps:
        return "\n\n".join(f"[{format_timestamp(start)}] {text}" for start, text in paragraphs)
    return "\n\n".join(text for _, text in paragraphs)
