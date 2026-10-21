"""The fetch-and-save job behind the desktop app, kept free of Tkinter so it can be tested."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Optional

from .client import UdemyClient, UdemyError, domain_from_url, parse_cookies, slug_from_url
from .exporter import lecture_file_text, lecture_filenames, render_text, safe_name
from .fetcher import fetch_lecture, load_sections

log = logging.getLogger(__name__)

# ("status", text) | ("progress", done, total) | ("log", text)
# | ("done", folder, saved, total) | ("cancelled", folder, saved, total) | ("error", text)
Emit = Callable[[tuple], None]


def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "transcript-fetcher" / "settings.json"


def default_output_dir() -> str:
    documents = Path.home() / "Documents"
    return str((documents if documents.is_dir() else Path.home()) / "Udemy Transcripts")


@dataclass
class Settings:
    token: str = ""
    output_dir: str = field(default_factory=default_output_dir)
    lang: str = "en"
    numbered: bool = True
    combined: bool = True
    remember_token: bool = True

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = path or config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Optional[Path] = None) -> None:
        path = path or config_path()
        data: dict[str, Any] = asdict(self)
        if not self.remember_token:
            data["token"] = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)  # the token unlocks the Udemy account


def make_client(link: str, token_text: str, session: Any = None, delay: float = 0.3) -> UdemyClient:
    """Build a client from a course link and either an access token or a pasted cookie string."""
    text = token_text.strip()
    cookies = parse_cookies(text) if ";" in text or text.startswith("access_token=") else {}
    return UdemyClient(
        token=None if cookies else text or None,
        cookies=cookies,
        domain=domain_from_url(link) or "www.udemy.com",
        session=session,
        delay=delay,
    )


def check_link(link: str) -> Optional[str]:
    """An error message if ``link`` doesn't look like a Udemy course link."""
    if not domain_from_url(link) or not slug_from_url(link):
        return "Paste the course link, for example https://www.udemy.com/course/your-course-name/"
    return None


def run_job(
    link: str,
    settings: Settings,
    emit: Emit,
    cancel: threading.Event,
    session: Any = None,
    delay: float = 0.3,
) -> None:
    """Fetch every video transcript of the course and save one .txt per video, in course order.

    Each file is written as soon as its transcript arrives, so cancelling keeps what's done.
    Never raises: failures are reported as an ("error", message) event.
    """
    try:
        client = make_client(link, settings.token, session, delay)
        emit(("status", "Looking for the course in your purchased courses..."))
        course = client.find_course(link)
        emit(("status", f"Loading the lecture list of '{course.title}'..."))
        sections = load_sections(client, course)
        lectures = [(s, l) for s in sections for l in s.lectures]
        if not lectures:
            raise UdemyError("This course has no video lectures.")

        names = lecture_filenames(sections, settings.numbered)
        folder = Path(settings.output_dir).expanduser() / safe_name(course.title)
        folder.mkdir(parents=True, exist_ok=True)
        emit(("log", f"{course.title}: {len(lectures)} videos -> {folder}"))

        saved = 0
        for i, (section, lecture) in enumerate(lectures):
            if cancel.is_set():
                emit(("cancelled", folder, saved, len(lectures)))
                return
            emit(("progress", i, len(lectures)))
            emit(("status", f"Video {i + 1} of {len(lectures)}: {lecture.title}"))
            fetch_lecture(client, course, lecture, settings.lang)
            if lecture.cues:
                (folder / names[lecture.id]).write_text(lecture_file_text(section, lecture), encoding="utf-8")
                saved += 1
                emit(("log", f"Saved    {names[lecture.id]}"))
            else:
                emit(("log", f"Skipped  {lecture.number}. {lecture.title} ({lecture.note})"))

        if settings.combined and saved:
            combined = folder / f"{safe_name(course.title)} (full course).txt"
            combined.write_text(render_text(course, sections, timestamps=False) + "\n", encoding="utf-8")
            emit(("log", f"Saved    {combined.name}"))
        emit(("progress", len(lectures), len(lectures)))
        emit(("done", folder, saved, len(lectures)))
    except UdemyError as exc:
        emit(("error", str(exc)))
    except OSError as exc:
        emit(("error", f"Could not save the files: {exc}"))
    except Exception as exc:  # keep the window alive and tell the user
        log.exception("unexpected error")
        emit(("error", f"Unexpected error: {exc!r}"))
