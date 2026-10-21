"""Minimal client for the Udemy web API (the endpoints the udemy.com player itself uses).

These endpoints are undocumented and may change without notice.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from .curriculum import Course

log = logging.getLogger(__name__)

COURSE_FIELDS = "id,title,url,published_title"
CURRICULUM_PARAMS = {
    "page_size": "100",
    "fields[chapter]": "title,object_index",
    "fields[lecture]": "title,object_index,asset",
    "fields[quiz]": "title,object_index",
    "fields[practice]": "title,object_index",
    "fields[asset]": "asset_type,title,captions",
    "caching_intent": "True",
}
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 4
NETWORK_RETRIES = 2
# (connect, read) seconds. requests treats "read" as the longest silence between bytes,
# but curl_cffi caps the whole transfer at connect + read, so it needs room for slow but
# steady responses such as a big course's lecture list.
REQUESTS_TIMEOUT = (15, 60)
CURL_TIMEOUT = (15, 285)


class UdemyError(Exception):
    """An error with a message meant for the user."""


class AuthError(UdemyError):
    pass


class BlockedError(UdemyError):
    pass


def parse_cookies(value: str) -> dict[str, str]:
    """Read cookies from a ``Cookie:`` header string or a Netscape cookies.txt file."""
    path = Path(value).expanduser()
    if "=" not in value and path.is_file():
        cookies = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif not line.strip() or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7 and "udemy.com" in fields[0]:
                cookies[fields[5]] = fields[6].strip()
        return cookies
    cookies = {}
    for part in value.split(";"):
        name, sep, val = part.strip().partition("=")
        if sep and name:
            cookies[name.strip()] = val.strip().strip('"')
    return cookies


def request_timeout(session: Any) -> tuple[float, float]:
    return CURL_TIMEOUT if type(session).__module__.startswith("curl_cffi") else REQUESTS_TIMEOUT


def describe_network_error(exc: OSError) -> str:
    text = str(exc).split(" See https://curl.se")[0].strip()
    if "timed out" in text.lower() or "timeout" in type(exc).__name__.lower():
        return "Udemy took too long to respond. Check your internet connection and try again."
    return f"Could not reach Udemy: {text[:200]}"


def make_session(impersonate: bool = True) -> Any:
    """Return a curl_cffi session impersonating Chrome when available, else requests.

    Do not send a browser User-Agent from plain requests: Cloudflare challenges
    a browser UA arriving with a non-browser TLS fingerprint.
    """
    if impersonate:
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            log.debug("curl_cffi not installed, using requests")
        else:
            return cffi_requests.Session(impersonate="chrome")
    import requests

    return requests.Session()


class UdemyClient:
    def __init__(
        self,
        token: Optional[str] = None,
        cookies: Optional[dict[str, str]] = None,
        domain: str = "www.udemy.com",
        delay: float = 0.3,
        session: Any = None,
        impersonate: bool = True,
    ) -> None:
        cookies = dict(cookies or {})
        token = token or cookies.get("access_token")
        if not token:
            raise AuthError("No Udemy access token. Pass --token, set UDEMY_ACCESS_TOKEN, or pass --cookies.")
        cookies["access_token"] = token
        self.domain = domain
        self.base_url = f"https://{domain}"
        self.delay = delay
        self.session = session if session is not None else make_session(impersonate)
        self._timeout = request_timeout(self.session)
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain=domain)
        # Sent only to the API, never to the caption CDN.
        self._api_headers = {
            "Authorization": f"Bearer {token}",
            "X-Udemy-Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
        }
        self._last_request = 0.0
        self._courses: Optional[list[Course]] = None

    def _throttle(self) -> None:
        wait = self._last_request + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, url: str, params: Optional[dict[str, str]] = None, headers: Optional[dict[str, str]] = None) -> Any:
        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self._timeout)
            except OSError as exc:  # network errors of both requests and curl_cffi subclass OSError
                if attempt >= NETWORK_RETRIES:
                    raise UdemyError(describe_network_error(exc)) from exc
                wait = 2.0 * 2**attempt
                log.info("%s for %s, retrying in %.0fs", type(exc).__name__, urlparse(url).path, wait)
                time.sleep(wait)
                continue
            if response.status_code not in RETRY_STATUSES or attempt == MAX_RETRIES:
                return response
            retry_after = response.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.isdigit() else 2.0 * 2**attempt
            log.info("HTTP %s from %s, retrying in %.0fs", response.status_code, urlparse(url).path, wait)
            time.sleep(wait)
        raise AssertionError("unreachable")

    def get_json(self, path_or_url: str, params: Optional[dict[str, str]] = None) -> Any:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        response = self._get(url, params=params, headers=self._api_headers)
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and "json" in content_type:
            return response.json()
        if "json" not in content_type and response.status_code in (403, 503):
            raise BlockedError(
                "Udemy's Cloudflare protection blocked the request. Install curl_cffi "
                "(pip install 'transcript-fetcher[impersonate]'), or wait and try again."
            )
        if response.status_code in (401, 403):
            raise AuthError(
                f"Udemy rejected the request (HTTP {response.status_code}). The access token is "
                "missing, expired or for a different domain (Udemy Business needs --domain)."
            )
        if response.status_code == 404:
            raise UdemyError(f"Not found: {urlparse(url).path}")
        raise UdemyError(f"Udemy API error HTTP {response.status_code} for {urlparse(url).path}")

    def paginate(self, path: str, params: dict[str, str]) -> Iterator[dict[str, Any]]:
        data = self.get_json(path, params)
        while True:
            yield from data.get("results", [])
            next_url = data.get("next")
            if not next_url:
                return
            data = self.get_json(next_url)

    def courses(self) -> list[Course]:
        """All courses the account is enrolled in, sorted by title."""
        if self._courses is None:
            items = self.paginate(
                "/api-2.0/users/me/subscribed-courses/",
                {"fields[course]": COURSE_FIELDS, "page_size": "100"},
            )
            self._courses = sorted(
                (
                    Course(
                        id=item["id"],
                        title=item.get("title") or "",
                        slug=item.get("published_title") or slug_from_url(item.get("url") or "") or str(item["id"]),
                        url=self.base_url + (item.get("url") or ""),
                    )
                    for item in items
                ),
                key=lambda c: c.title.lower(),
            )
        return self._courses

    def find_course(self, ref: str) -> Course:
        """Resolve a course id, slug or URL against the enrolled courses."""
        ref = ref.strip()
        slug = slug_from_url(ref) or ref.strip("/")
        for course in self.courses():
            if str(course.id) == slug or course.slug == slug:
                return course
        raise UdemyError(f"'{ref}' is not one of your enrolled courses on {self.domain}. Run 'transcript-fetcher list'.")

    def curriculum(self, course_id: int) -> Iterator[dict[str, Any]]:
        """Curriculum items (chapters, lectures, quizzes...) in course order."""
        return self.paginate(f"/api-2.0/courses/{course_id}/subscriber-curriculum-items/", CURRICULUM_PARAMS)

    def lecture_captions(self, course_id: int, lecture_id: int) -> list[dict[str, Any]]:
        data = self.get_json(
            f"/api-2.0/users/me/subscribed-courses/{course_id}/lectures/{lecture_id}/",
            {"fields[lecture]": "asset", "fields[asset]": "asset_type,captions"},
        )
        return (data.get("asset") or {}).get("captions") or []

    def download_text(self, url: str) -> str:
        """Download a caption file from its signed CDN URL (no Udemy credentials sent)."""
        response = self._get(url)
        if response.status_code != 200:
            raise UdemyError(f"caption download failed (HTTP {response.status_code})")
        return response.content.decode("utf-8-sig", errors="replace")


def slug_from_url(value: str) -> Optional[str]:
    """``https://www.udemy.com/course/python-bootcamp/learn/lecture/1#x`` -> ``python-bootcamp``."""
    path = urlparse(value).path if "://" in value else value
    parts = [p for p in path.split("/") if p]
    if "course" in parts:
        i = parts.index("course")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def domain_from_url(value: str) -> Optional[str]:
    """The Udemy host of a course URL (``acme.udemy.com`` for Udemy Business), if any."""
    host = urlparse(value.strip()).hostname if "://" in value else None
    return host if host and (host == "udemy.com" or host.endswith(".udemy.com")) else None
