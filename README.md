# transcript-fetcher

Fetch the video transcripts of the Udemy courses you're enrolled in, in curriculum order
(Section 1 → Lecture 1, 2, 3 … → Section 2 …), as one Markdown, text or JSON file per course.

It uses the same internal API the udemy.com player uses to show its "Transcript" panel. That API
is undocumented, so Udemy can change it without notice.

## Install

Requires Python 3.9+.

```bash
git clone https://github.com/oxynousai/transcript-fetcher
cd transcript-fetcher
pip install ".[impersonate]"
```

`[impersonate]` adds `curl_cffi`, which makes requests look like Chrome at the TLS level and is
less likely to be stopped by Udemy's Cloudflare protection. Without it the tool falls back to
plain `requests`, which also works today.

## Get your access token

1. Log in at https://www.udemy.com (or your Udemy Business site) in your browser.
2. Open DevTools (F12) → **Application** (Chrome/Edge) or **Storage** (Firefox) → **Cookies** → the Udemy site.
3. Copy the value of the `access_token` cookie.

```bash
export UDEMY_ACCESS_TOKEN='paste-token-here'
```

Treat the token like a password: it gives full access to your Udemy account. Prefer the
environment variable over `--token` so it doesn't end up in your shell history. If you get an
"Udemy rejected the request" error later, the token has expired; copy a fresh one.

## Use

```bash
transcript-fetcher                     # list your courses and pick interactively (e.g. "1,3-5")
transcript-fetcher list                # list enrolled courses with their slugs
transcript-fetcher fetch https://www.udemy.com/course/some-course/learn/lecture/123
transcript-fetcher fetch some-course other-course --format txt --timestamps
transcript-fetcher fetch --all --split --raw -o ~/udemy-notes
```

A course can be given as its URL (any page inside it), its slug, or its numeric id.

| Option | Effect |
| --- | --- |
| `-f md\|txt\|json` | Combined file format (default `md`). JSON includes per-cue timings. |
| `--lang en` | Caption language: `en`, `en_US`, `es`, … (default `en`). |
| `--any-lang` | If a lecture has no captions in `--lang`, use another language. |
| `--timestamps` | Prefix each paragraph with `[mm:ss]`. |
| `--split` | Also write one `.txt` per lecture. |
| `--raw` | Also save the original `.vtt`/`.srt` caption files. |
| `--domain acme.udemy.com` | Udemy Business. Inferred automatically when you pass a course URL from that site. |
| `-v` | Print each lecture as it's fetched. |

Caption choice per lecture: the requested language first, human-made captions over
auto-generated ones, exact locale (`en_US`) over the same language (`en_GB`).

## Output

```
transcripts/
  some-course/
    some-course.md                      # whole course, in order
    lectures/                           # with --split
      01 - Getting Started/
        001 - Welcome.txt
    captions/                           # with --raw
      01 - Getting Started/
        001 - Welcome.en_US.vtt
```

The combined file has a heading per section and per lecture (numbered as on Udemy). Lectures
without a usable transcript stay in place with a note explaining why, and are also listed at the
end of the run. Articles, quizzes and exercises are skipped since they have no video.

## Troubleshooting

- **"Udemy rejected the request (HTTP 401/403)"**: token missing or expired, or you're on Udemy
  Business without `--domain`.
- **"Cloudflare protection blocked the request"**: install the `[impersonate]` extra, or wait a
  while. Passing your full browser cookies with `--cookies` can also help.
- **A lecture says "this lecture has no captions"**: the instructor's video has no captions on
  Udemy either; there is nothing to fetch.

## Scope and terms

Only courses your account is enrolled in can be fetched; the tool uses your own login and adds a
delay between requests (`--delay`, default 0.3 s). Check Udemy's Terms of Use before using it, keep
the transcripts for your own study, and don't redistribute them: course content belongs to its
instructors.

## Development

```bash
pip install -e ".[dev,impersonate]"
pytest
```
