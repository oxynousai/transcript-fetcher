"""Command line interface: ``transcript-fetcher list`` and ``transcript-fetcher fetch``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from . import __version__
from .client import AuthError, BlockedError, UdemyClient, UdemyError, parse_cookies
from .curriculum import Course, Lecture
from .exporter import FORMATS, write_course
from .fetcher import fetch_course

TOKEN_HELP = (
    "Udemy access token (default: $UDEMY_ACCESS_TOKEN). Find it while logged in to Udemy: "
    "browser DevTools > Application/Storage > Cookies > access_token."
)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    auth = common.add_argument_group("authentication")
    auth.add_argument("--token", help=TOKEN_HELP)
    auth.add_argument(
        "--cookies",
        help="Browser cookies as a 'name=value; ...' string or a Netscape cookies.txt path (default: $UDEMY_COOKIES).",
    )
    auth.add_argument(
        "--domain",
        help="Udemy host, e.g. yourcompany.udemy.com for Udemy Business (default: $UDEMY_DOMAIN or www.udemy.com).",
    )
    common.add_argument("--delay", type=float, default=0.3, help="Seconds between requests (default: 0.3).")
    common.add_argument("--no-impersonate", action="store_true", help="Use plain requests even if curl_cffi is installed.")
    common.add_argument("-v", "--verbose", action="store_true", help="Show each lecture as it is fetched.")

    parser = argparse.ArgumentParser(
        prog="transcript-fetcher",
        description="Fetch the video transcripts of your enrolled Udemy courses, in curriculum order.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", parents=[common], help="List your enrolled courses.")
    p_list.add_argument("--json", action="store_true", help="Print as JSON.")

    p_fetch = sub.add_parser(
        "fetch",
        parents=[common],
        help="Fetch transcripts (prompts for courses when none are given).",
    )
    p_fetch.add_argument("courses", nargs="*", metavar="COURSE", help="Course URL, slug or numeric id.")
    p_fetch.add_argument("--all", action="store_true", help="Fetch every enrolled course.")
    p_fetch.add_argument("-o", "--out", type=Path, default=Path("transcripts"), help="Output directory (default: ./transcripts).")
    p_fetch.add_argument("-f", "--format", choices=FORMATS, default="md", help="Combined file format (default: md).")
    p_fetch.add_argument("--lang", default="en", help="Caption language, e.g. en, en_US, es (default: en).")
    p_fetch.add_argument("--any-lang", action="store_true", help="Fall back to another language when --lang is missing.")
    p_fetch.add_argument("--timestamps", action="store_true", help="Prefix paragraphs with [mm:ss].")
    p_fetch.add_argument("--split", action="store_true", help="Also write one .txt file per lecture.")
    p_fetch.add_argument("--raw", action="store_true", help="Also save the original .vtt/.srt caption files.")
    return parser


def parse_selection(text: str, count: int) -> list[int]:
    """Parse '1,3-5' or 'all' into sorted zero-based indexes."""
    text = text.strip().lower()
    if text in ("all", "*"):
        return list(range(count))
    picked: set[int] = set()
    for part in text.replace(" ", ",").split(","):
        if not part:
            continue
        start, sep, end = part.partition("-")
        try:
            lo = int(start)
            hi = int(end) if sep else lo
        except ValueError:
            raise ValueError(f"not a number or range: {part!r}") from None
        if not (1 <= lo <= hi <= count):
            raise ValueError(f"out of range: {part!r} (1-{count})")
        picked.update(range(lo - 1, hi))
    return sorted(picked)


def make_client(args: argparse.Namespace) -> UdemyClient:
    cookie_source = args.cookies or os.environ.get("UDEMY_COOKIES")
    cookies = parse_cookies(cookie_source) if cookie_source else {}
    domain = args.domain or os.environ.get("UDEMY_DOMAIN")
    if not domain:
        # A Udemy Business course URL tells us the portal host.
        hosts = {urlparse(c).hostname for c in getattr(args, "courses", []) if "://" in c}
        hosts = {h for h in hosts if h and h.endswith("udemy.com")}
        domain = hosts.pop() if len(hosts) == 1 else "www.udemy.com"
    return UdemyClient(
        token=args.token or os.environ.get("UDEMY_ACCESS_TOKEN"),
        cookies=cookies,
        domain=domain,
        delay=args.delay,
        impersonate=not args.no_impersonate,
    )


def cmd_list(client: UdemyClient, args: argparse.Namespace) -> int:
    courses = client.courses()
    if args.json:
        print(json.dumps([vars(c) for c in courses], ensure_ascii=False, indent=2))
        return 0
    for i, course in enumerate(courses, 1):
        print(f"{i:>4}. {course.title}  [{course.slug}]")
    print(f"\n{len(courses)} enrolled course(s) on {client.domain}", file=sys.stderr)
    return 0


def pick_courses(client: UdemyClient) -> list[Course]:
    if not sys.stdin.isatty():
        raise UdemyError("No course given. Pass COURSE arguments or --all.")
    courses = client.courses()
    if not courses:
        raise UdemyError(f"No enrolled courses found on {client.domain}.")
    for i, course in enumerate(courses, 1):
        print(f"{i:>4}. {course.title}")
    while True:
        answer = input("\nCourses to fetch (e.g. 1,3-5 or all): ")
        try:
            indexes = parse_selection(answer, len(courses))
        except ValueError as exc:
            print(exc)
            continue
        if indexes:
            return [courses[i] for i in indexes]


def _progress(verbose: bool):
    tty = sys.stderr.isatty()

    def report(i: int, total: int, lecture: Lecture) -> None:
        if verbose:
            print(f"  [{i}/{total}] {lecture.number}. {lecture.title}", file=sys.stderr)
        elif tty:
            end = "\n" if i == total else ""
            print(f"\r  lecture {i}/{total}", end=end, file=sys.stderr, flush=True)

    return report


def cmd_fetch(client: UdemyClient, args: argparse.Namespace) -> int:
    if args.all:
        courses = client.courses()
    elif args.courses:
        courses = [client.find_course(ref) for ref in args.courses]
    else:
        courses = pick_courses(client)

    failures = 0
    for course in courses:
        print(f"\n{course.title}", file=sys.stderr)
        try:
            sections = fetch_course(client, course, args.lang, args.any_lang, _progress(args.verbose))
        except (AuthError, BlockedError):
            raise
        except UdemyError as exc:
            if len(courses) == 1:
                raise
            print(f"  skipped: {exc}", file=sys.stderr)
            failures += 1
            continue
        path = write_course(course, sections, args.out, args.format, args.lang, args.timestamps, args.split, args.raw)
        lectures = [l for s in sections for l in s.lectures]
        missing = [l for l in lectures if not l.cues]
        print(f"  {len(lectures) - len(missing)}/{len(lectures)} video lectures transcribed -> {path}", file=sys.stderr)
        for lecture in missing:
            print(f"    missing {lecture.number}. {lecture.title}: {lecture.note}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("list", "fetch", "-h", "--help", "--version"):
        argv.insert(0, "fetch")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(levelname)s: %(message)s")
    try:
        client = make_client(args)
        return cmd_list(client, args) if args.command == "list" else cmd_fetch(client, args)
    except UdemyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
