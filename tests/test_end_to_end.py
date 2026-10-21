import json

import pytest

from transcript_fetcher import cli
from transcript_fetcher.client import AuthError, BlockedError, UdemyClient, parse_cookies, slug_from_url
from transcript_fetcher.exporter import write_course
from transcript_fetcher.fetcher import fetch_course

BASE = "https://www.udemy.com"
COURSES = "/api-2.0/users/me/subscribed-courses/"
CURRICULUM = "/api-2.0/courses/42/subscriber-curriculum-items/"


class FakeResponse:
    def __init__(self, status, body, content_type="application/json"):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": content_type}

    def json(self):
        return self._body

    @property
    def content(self):
        return self._body.encode() if isinstance(self._body, str) else json.dumps(self._body).encode()


class FakeCookies(dict):
    def set(self, name, value, domain=""):
        self[name] = (value, domain)


class FakeSession:
    """Routes GETs by path (API) or full URL (CDN) and records what was sent."""

    def __init__(self, routes):
        self.routes = routes
        self.cookies = FakeCookies()
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, headers))
        key = url.replace(BASE, "")
        return self.routes[key]() if callable(self.routes[key]) else self.routes[key]


def vtt(text):
    return f"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n{text}\n"


def make_routes():
    caption = lambda locale, label, url, source="manual": {
        "locale_id": locale, "video_label": label, "url": url, "source": source,
    }
    return {
        COURSES: FakeResponse(200, {
            "next": BASE + COURSES + "?page=2",
            "results": [{"id": 7, "title": "Zeta course", "url": "/course/zeta/", "published_title": "zeta"}],
        }),
        COURSES + "?page=2": FakeResponse(200, {
            "next": None,
            "results": [{"id": 42, "title": "Alpha course", "url": "/course/alpha/", "published_title": "alpha"}],
        }),
        CURRICULUM: FakeResponse(200, {
            "next": BASE + CURRICULUM + "?page=2",
            "results": [
                {"_class": "chapter", "id": 1, "title": "Intro", "object_index": 1},
                {"_class": "lecture", "id": 100, "title": "Welcome", "object_index": 1,
                 "asset": {"asset_type": "Video", "captions": [
                     caption("en_US", "English [Auto]", "https://cdn/100-auto.vtt", "auto"),
                     caption("en_US", "English", "https://cdn/100.vtt"),
                 ]}},
                {"_class": "lecture", "id": 101, "title": "Reading", "object_index": 2,
                 "asset": {"asset_type": "Article"}},
            ],
        }),
        CURRICULUM + "?page=2": FakeResponse(200, {
            "next": None,
            "results": [
                {"_class": "chapter", "id": 2, "title": "Deep dive", "object_index": 2},
                {"_class": "lecture", "id": 102, "title": "Setup", "object_index": 3,
                 "asset": {"asset_type": "Video"}},
                {"_class": "quiz", "id": 5, "title": "Check", "object_index": 1},
                {"_class": "lecture", "id": 103, "title": "Spanish only", "object_index": 4,
                 "asset": {"asset_type": "Video", "captions": [caption("es_ES", "Español", "https://cdn/103.vtt")]}},
            ],
        }),
        "/api-2.0/users/me/subscribed-courses/42/lectures/102/": FakeResponse(200, {
            "asset": {"captions": [caption("en_GB", "English", "https://cdn/102.srt")]},
        }),
        "https://cdn/100.vtt": FakeResponse(200, vtt("Welcome to the course."), "text/vtt"),
        "https://cdn/102.srt": FakeResponse(200, "1\n00:00:01,000 --> 00:00:02,000\nInstall Python.\n", "text/plain"),
    }


@pytest.fixture
def client():
    return UdemyClient(token="secret", session=FakeSession(make_routes()), delay=0)


def test_courses_paginate_and_resolve(client):
    assert [c.title for c in client.courses()] == ["Alpha course", "Zeta course"]
    assert client.find_course("https://www.udemy.com/course/alpha/learn/lecture/100#overview").id == 42
    assert client.find_course("7").slug == "zeta"
    with pytest.raises(Exception, match="not one of your enrolled courses"):
        client.find_course("other")


def test_fetch_course_orders_and_selects_captions(client, tmp_path):
    course = client.find_course("alpha")
    sections = fetch_course(client, course, lang="en")

    assert [(s.number, s.title) for s in sections] == [(1, "Intro"), (2, "Deep dive")]
    lectures = [l for s in sections for l in s.lectures]
    assert [l.number for l in lectures] == [1, 3, 4]  # article and quiz dropped
    assert lectures[0].caption.url == "https://cdn/100.vtt"  # manual beats auto
    assert lectures[1].cues[0].text == "Install Python."  # captions looked up per lecture
    assert lectures[2].cues == [] and "available: Español" in lectures[2].note

    # The token goes to the API only, never to the caption CDN.
    for url, headers in client.session.calls:
        sent = (headers or {}).get("Authorization")
        assert (sent == "Bearer secret") == url.startswith(BASE)

    path = write_course(course, sections, tmp_path, "md", split=True, raw=True)
    text = path.read_text()
    assert path == tmp_path / "alpha" / "alpha.md"
    assert text.index("## Section 1: Intro") < text.index("### 1. Welcome") < text.index("## Section 2: Deep dive")
    assert text.index("Welcome to the course.") < text.index("Install Python.")
    assert "*(No transcript: no 'en' captions (available: Español))*" in text
    assert (tmp_path / "alpha/lectures/02 - Deep dive/003 - Setup.txt").read_text() == "Setup\n\nInstall Python.\n"
    assert (tmp_path / "alpha/captions/02 - Deep dive/003 - Setup.en_GB.srt").exists()

    data = json.loads(write_course(course, sections, tmp_path, "json").read_text())
    assert [l["title"] for s in data["sections"] for l in s["lectures"]] == ["Welcome", "Setup", "Spanish only"]


def test_any_lang_fallback(client):
    sections = fetch_course(client, client.find_course("alpha"), lang="en", any_lang=False)
    assert sections[-1].lectures[-1].caption is None
    client.session.routes["https://cdn/103.vtt"] = FakeResponse(200, vtt("Hola."), "text/vtt")
    sections = fetch_course(client, client.find_course("alpha"), lang="en", any_lang=True)
    assert sections[-1].lectures[-1].cues[0].text == "Hola."


def test_per_lecture_errors_are_recorded(client):
    client.session.routes["https://cdn/100.vtt"] = FakeResponse(403, "denied", "text/plain")
    lectures = [l for s in fetch_course(client, client.find_course("alpha")) for l in s.lectures]
    assert "HTTP 403" in lectures[0].note
    assert lectures[1].cues  # later lectures still fetched


def test_auth_and_cloudflare_errors():
    session = FakeSession({COURSES: FakeResponse(401, {"detail": "nope"})})
    with pytest.raises(AuthError):
        UdemyClient(token="t", session=session, delay=0).courses()
    session = FakeSession({COURSES: FakeResponse(403, "<title>Just a moment...</title>", "text/html")})
    with pytest.raises(BlockedError):
        UdemyClient(token="t", session=session, delay=0).courses()
    with pytest.raises(AuthError):
        UdemyClient(token=None, session=session)


def test_retries_on_rate_limit(monkeypatch):
    responses = iter([FakeResponse(429, {}), FakeResponse(200, {"results": [], "next": None})])
    monkeypatch.setattr("transcript_fetcher.client.time.sleep", lambda s: None)
    client = UdemyClient(token="t", session=FakeSession({COURSES: lambda: next(responses)}), delay=0)
    assert client.courses() == []


def test_parse_cookies(tmp_path):
    assert parse_cookies('access_token=abc; client_id="x"') == {"access_token": "abc", "client_id": "x"}
    jar = tmp_path / "cookies.txt"
    jar.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.udemy.com\tTRUE\t/\tTRUE\t0\taccess_token\tabc\n"
        ".example.com\tTRUE\t/\tTRUE\t0\tother\tx\n"
    )
    assert parse_cookies(str(jar)) == {"access_token": "abc"}
    client = UdemyClient(cookies=parse_cookies(str(jar)), session=FakeSession({}))
    assert client.session.cookies["access_token"] == ("abc", "www.udemy.com")


def test_slug_from_url():
    assert slug_from_url("https://acme.udemy.com/course/py-101/learn/lecture/5") == "py-101"
    assert slug_from_url("py-101") is None


def test_parse_selection():
    assert cli.parse_selection("1, 3-4", 5) == [0, 2, 3]
    assert cli.parse_selection("all", 3) == [0, 1, 2]
    with pytest.raises(ValueError):
        cli.parse_selection("6", 5)


def test_cli_fetch_infers_business_domain(monkeypatch, tmp_path):
    seen = {}

    def fake_fetch(client, args):
        seen["domain"] = client.domain
        return 0

    monkeypatch.setattr(cli, "cmd_fetch", fake_fetch)
    monkeypatch.setenv("UDEMY_ACCESS_TOKEN", "t")
    monkeypatch.delenv("UDEMY_DOMAIN", raising=False)
    assert cli.main(["https://acme.udemy.com/course/py-101/", "-o", str(tmp_path)]) == 0
    assert seen["domain"] == "acme.udemy.com"
