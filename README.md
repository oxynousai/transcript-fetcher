# transcript-fetcher

Fetch the video transcripts of the Udemy courses you're enrolled in, in curriculum order
(Section 1 → Lecture 1, 2, 3 … → Section 2 …). Use the desktop app (paste a course link, get one
`.txt` per video named after the video) or the command line.

It uses the same internal API the udemy.com player uses to show its "Transcript" panel. That API
is undocumented, so Udemy can change it without notice.

## Install

### Ubuntu: app icon in the dock

```bash
git clone https://github.com/oxynousai/transcript-fetcher
cd transcript-fetcher
./install-ubuntu.sh
```

This installs the app for your user only (in `~/.local/share/transcript-fetcher`, with its own
Python environment), adds **Udemy Transcript Fetcher** to the app grid and pins it to the dock.
It asks for your password only if `python3-tk` or `python3-venv` must be installed with apt.
Afterwards the downloaded folder can be deleted. To update, run the script from a newer copy;
to remove everything (including the saved token), run `./install-ubuntu.sh --uninstall`.

### Other systems

Requires Python 3.9+.

```bash
git clone https://github.com/oxynousai/transcript-fetcher
cd transcript-fetcher
pip install ".[impersonate]"
```

On Linux distributions that block system-wide `pip install` ("externally-managed-environment"),
create a virtual environment first (`python3 -m venv .venv && . .venv/bin/activate`).

The desktop app uses Tkinter, which comes with Python from python.org on Windows and macOS.
Elsewhere: `brew install python-tk` (Homebrew Python) or `sudo apt install python3-tk` (Debian/Ubuntu).

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

## Desktop app

```bash
transcript-fetcher-gui
```

1. Paste the course link (any page of the course, e.g. `https://www.udemy.com/course/some-course/`).
2. Paste your access token (the **How do I get it?** button shows the steps below).
3. Choose where to save and press **Fetch transcripts**.

You get a folder named after the course with one file per video, named after the video and
numbered in course order so they sort correctly:

```
Udemy Transcripts/
  Some Course/
    001 - Welcome.txt
    002 - Setting up your tools.txt
    ...
    Some Course (full course).txt       # optional: everything in one file
```

Each file starts with the video title and its section, followed by the transcript. Untick
**Number files in course order** to name files with the video title only. Each file is saved as
soon as it's fetched, so **Cancel** keeps what's already done. Videos without a transcript are
listed in the window. Udemy Business links (`yourcompany.udemy.com`) work as is.

"Remember on this computer" stores the token in a settings file only your user can read
(`%APPDATA%\transcript-fetcher` on Windows, `~/Library/Application Support/transcript-fetcher` on
macOS, `~/.config/transcript-fetcher` on Linux). Untick it on a shared computer.

## Command line

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
