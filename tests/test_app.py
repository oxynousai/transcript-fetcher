import os
import threading

import pytest

from transcript_fetcher.app import Settings, check_link, make_client, run_job
from transcript_fetcher.curriculum import Lecture, Section
from transcript_fetcher.exporter import lecture_filenames, safe_name

from fakes import COURSES, CURRICULUM, FakeResponse, FakeSession, make_routes

LINK = "https://www.udemy.com/course/alpha/learn/lecture/100#overview"


def run(tmp_path, link=LINK, cancel_after=None, routes=None, **settings):
    events = []
    cancel = threading.Event()

    def emit(event):
        events.append(event)
        if cancel_after and event[0] == "log" and event[1].startswith("Saved") and len(
            [e for e in events if e[0] == "log" and e[1].startswith("Saved")]
        ) == cancel_after:
            cancel.set()

    settings = Settings(token="secret", output_dir=str(tmp_path), **settings)
    run_job(link, settings, emit, cancel, session=FakeSession(routes or make_routes()), delay=0)
    return events


def test_saves_one_txt_per_video_named_after_it(tmp_path):
    events = run(tmp_path)
    folder = tmp_path / "Alpha course"
    assert sorted(p.name for p in folder.iterdir()) == ["001 - Welcome.txt", "003 - Setup.txt", "Alpha course (full course).txt"]
    assert (folder / "003 - Setup.txt").read_text() == "Setup\nSection 2: Deep dive\n\nInstall Python.\n"
    full = (folder / "Alpha course (full course).txt").read_text()
    assert full.index("Welcome to the course.") < full.index("Install Python.")
    assert events[-1] == ("done", folder, 2, 3)
    assert any(e[0] == "log" and "Skipped  4. Spanish only" in e[1] for e in events)
    progress = [e[1:] for e in events if e[0] == "progress"]
    assert progress == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_unnumbered_names_and_no_combined_file(tmp_path):
    run(tmp_path, numbered=False, combined=False)
    assert sorted(p.name for p in (tmp_path / "Alpha course").iterdir()) == ["Setup.txt", "Welcome.txt"]


def test_cancel_keeps_files_already_saved(tmp_path):
    events = run(tmp_path, cancel_after=1)
    assert events[-1] == ("cancelled", tmp_path / "Alpha course", 1, 3)
    assert [p.name for p in (tmp_path / "Alpha course").iterdir()] == ["001 - Welcome.txt"]


def test_errors_become_events(tmp_path):
    events = run(tmp_path, routes={COURSES: FakeResponse(401, {"detail": "no"})})
    assert events[-1][0] == "error" and "rejected" in events[-1][1]
    events = run(tmp_path, link="https://www.udemy.com/course/not-mine/")
    assert events[-1][0] == "error" and "not one of your enrolled courses" in events[-1][1]


def test_network_failure_is_reported_as_network_not_file_error(tmp_path, monkeypatch):
    monkeypatch.setattr("transcript_fetcher.client.time.sleep", lambda s: None)
    routes = make_routes()

    def slow():
        raise OSError("Operation timed out after 30001 milliseconds")

    routes[CURRICULUM] = slow
    events = run(tmp_path, routes=routes)
    assert ("log", "Found 'Alpha course' in your courses.") in events
    assert events[-1] == ("error", "Udemy took too long to respond. Check your internet connection and try again.")


def test_make_client_accepts_token_or_cookie_string():
    client = make_client("https://acme.udemy.com/course/x/", "access_token=abc; client_id=1", session=FakeSession({}))
    assert client.domain == "acme.udemy.com"
    assert client.session.cookies["access_token"] == ("abc", "acme.udemy.com")
    client = make_client(LINK, "  plain-token  ", session=FakeSession({}))
    assert client.domain == "www.udemy.com"
    assert client.session.cookies["access_token"][0] == "plain-token"


def test_check_link():
    assert check_link(LINK) is None
    assert check_link("https://acme.udemy.com/course/py-101/") is None
    assert check_link("https://www.udemy.com/home/my-courses/") is not None
    assert check_link("alpha") is not None
    assert check_link("https://example.com/course/alpha/") is not None


def test_settings_roundtrip_and_token_privacy(tmp_path):
    path = tmp_path / "cfg" / "settings.json"
    Settings(token="t", output_dir="/x", lang="es", numbered=False).save(path)
    loaded = Settings.load(path)
    assert (loaded.token, loaded.output_dir, loaded.lang, loaded.numbered) == ("t", "/x", "es", False)
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    Settings(token="t", remember_token=False).save(path)
    assert Settings.load(path).token == ""
    path.write_text("not json")
    assert Settings.load(path) == Settings()


def lecture(id, number, title):
    return Lecture(id=id, number=number, title=title, asset_type="Video", captions=[])


def test_lecture_filenames_are_unique_and_ordered():
    sections = [Section(1, "A", [lecture(1, 1, "Intro"), lecture(2, 2, "intro")]), Section(2, "B", [lecture(3, 1000, "Q&A?")])]
    assert lecture_filenames(sections) == {1: "0001 - Intro.txt", 2: "0002 - intro.txt", 3: "1000 - Q&A.txt"}
    assert lecture_filenames(sections, numbered=False) == {1: "Intro.txt", 2: "intro (2).txt", 3: "Q&A.txt"}


@pytest.mark.parametrize(
    "title, expected",
    [("What is: a/b?", "What is ab"), ("CON", "CON_"), ("nul.txt", "nul.txt_"), ("  ...  ", "untitled"), ("Ends with dot.", "Ends with dot")],
)
def test_safe_name(title, expected):
    assert safe_name(title) == expected
