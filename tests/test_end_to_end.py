import json

import pytest

from transcript_fetcher import cli
from transcript_fetcher.client import (
    NETWORK_RETRIES,
    AuthError,
    BlockedError,
    UdemyClient,
    UdemyError,
    parse_cookies,
    request_timeout,
    slug_from_url,
)
from transcript_fetcher.exporter import write_course
from transcript_fetcher.fetcher import fetch_course

from fakes import BASE, COURSES, CURRICULUM, FakeResponse, FakeSession, make_routes, vtt


@pytest.fixture
def client():
    return UdemyClient(token="secret", session=FakeSession(make_routes()), delay=0)


def test_courses_paginate_and_resolve(client):
    assert [c.title for c in client.courses()] == ["Alpha course", "Zeta course"]
    assert client.find_course("https://www.udemy.com/course/alpha/learn/lecture/100#overview").id == 42
    assert client.find_course("7").slug == "zeta"
    with pytest.raises(UdemyError, match="There is no Udemy course at 'other'"):
        client.find_course("other")


def test_courses_missing_from_the_enrolled_list_are_looked_up_directly(client):
    # Udemy leaves subscription (Personal Plan) and archived courses out of the enrolled list.
    client.session.routes["/api-2.0/courses/plan-course/"] = FakeResponse(
        200, {"id": 42, "title": "Plan course", "url": "/course/plan-course/", "published_title": "plan-course"}
    )
    course = client.find_course("https://www.udemy.com/course/plan-course/learn/lecture/100")
    assert (course.id, course.title, course.slug) == (42, "Plan course", "plan-course")
    assert [l.number for s in fetch_course(client, course) for l in s.lectures] == [1, 3, 4]


def test_no_access_to_course_is_explained(client):
    client.session.routes[CURRICULUM] = FakeResponse(403, {"detail": "You do not have permission to perform this action."})
    with pytest.raises(UdemyError, match="can't open this course's lectures") as info:
        fetch_course(client, client.find_course("alpha"))
    assert not isinstance(info.value, AuthError)  # not reported as a bad token


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


class CurlTimeout(OSError):
    """Stands in for curl_cffi's Timeout, which subclasses OSError like requests' errors."""


def test_network_errors_are_retried_then_reported(monkeypatch):
    monkeypatch.setattr("transcript_fetcher.client.time.sleep", lambda s: None)
    outcomes = iter([CurlTimeout("timed out"), FakeResponse(200, {"results": [], "next": None})])

    def flaky():
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert UdemyClient(token="t", session=FakeSession({COURSES: flaky}), delay=0).courses() == []

    attempts = []

    def always_slow():
        attempts.append(1)
        raise CurlTimeout(
            "Failed to perform, curl: (28) Operation timed out after 30001 milliseconds with 130507 bytes received. "
            "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

    client = UdemyClient(token="t", session=FakeSession({COURSES: always_slow}), delay=0)
    with pytest.raises(UdemyError, match="^Udemy took too long to respond"):
        client.courses()
    assert len(attempts) == NETWORK_RETRIES + 1


def test_request_timeout_allows_slow_but_steady_transfers():
    import requests

    assert request_timeout(requests.Session()) == (15, 60)
    curl = pytest.importorskip("curl_cffi.requests")
    connect, read = request_timeout(curl.Session(impersonate="chrome"))
    assert connect + read >= 300  # curl_cffi caps the whole transfer, not the silence between bytes
