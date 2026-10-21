"""A fake Udemy API: just enough HTTP session to exercise the client offline."""

import json

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
        if key not in self.routes:
            return FakeResponse(404, {"detail": "Not found."})
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
