"""Desktop app: paste a Udemy course link, get one .txt transcript per video."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Optional

from . import __version__
from .app import Settings, check_link, run_job

TOKEN_HELP = """Your access token lets the app read your purchased courses, the same way your browser does.

1. Open udemy.com in Chrome, Edge or Firefox and log in.
2. Press F12 to open the developer tools.
3. Chrome/Edge: open the "Application" tab. Firefox: open the "Storage" tab.
4. In the left panel, expand "Cookies" and click the Udemy site.
5. Find the row named access_token and copy its Value.
6. Paste it into the "Access token" box.

Treat it like a password. If fetching later says the token was rejected, it has expired: copy a fresh one the same way.

Udemy Business: do the same on your company's Udemy site (for example yourcompany.udemy.com)."""


class App:
    def __init__(self, root: tk.Tk, settings_path: Optional[Path] = None, session: Any = None, delay: float = 0.3) -> None:
        self.root = root
        self.settings_path = settings_path
        self.session = session
        self.delay = delay
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.folder: Optional[Path] = None

        settings = Settings.load(settings_path)
        self.link = tk.StringVar()
        self.token = tk.StringVar(value=settings.token or os.environ.get("UDEMY_ACCESS_TOKEN", ""))
        self.remember = tk.BooleanVar(value=settings.remember_token)
        self.show_token = tk.BooleanVar(value=False)
        self.output_dir = tk.StringVar(value=settings.output_dir)
        self.lang = tk.StringVar(value=settings.lang)
        self.numbered = tk.BooleanVar(value=settings.numbered)
        self.combined = tk.BooleanVar(value=settings.combined)
        self.status = tk.StringVar(value="Paste a course link and press Fetch transcripts.")

        root.title("Udemy Transcript Fetcher")
        root.minsize(640, 480)
        if sys.platform.startswith("linux"):
            style = ttk.Style(root)
            style.theme_use("clam")
            # clam draws the filled part lighter than the trough, so a full bar looks empty
            accent = "#3b7ddd"
            style.configure("Horizontal.TProgressbar", background=accent, lightcolor=accent, darkcolor=accent, troughcolor="#e4e4e4")
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._poll)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=14)
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)
        pad = {"padx": 4, "pady": 4}

        ttk.Label(frame, text="Course link").grid(row=0, column=0, sticky="w", **pad)
        self.link_entry = ttk.Entry(frame, textvariable=self.link)
        self.link_entry.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        self.link_entry.bind("<Return>", lambda _e: self.start())
        ttk.Label(frame, text="e.g. https://www.udemy.com/course/your-course-name/", foreground="gray").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=4
        )

        ttk.Label(frame, text="Access token").grid(row=2, column=0, sticky="w", **pad)
        self.token_entry = ttk.Entry(frame, textvariable=self.token, show="•")
        self.token_entry.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="How do I get it?", command=self.token_help).grid(row=2, column=2, sticky="ew", **pad)
        token_opts = ttk.Frame(frame)
        token_opts.grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Checkbutton(token_opts, text="Show", variable=self.show_token, command=self._toggle_token).pack(side="left", padx=4)
        ttk.Checkbutton(token_opts, text="Remember on this computer", variable=self.remember).pack(side="left", padx=12)

        ttk.Label(frame, text="Save to").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.output_dir).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse...", command=self.browse).grid(row=4, column=2, sticky="ew", **pad)

        ttk.Label(frame, text="Language").grid(row=5, column=0, sticky="w", **pad)
        opts = ttk.Frame(frame)
        opts.grid(row=5, column=1, columnspan=2, sticky="w")
        ttk.Entry(opts, textvariable=self.lang, width=8).pack(side="left", padx=4)
        ttk.Checkbutton(opts, text="Number files in course order", variable=self.numbered).pack(side="left", padx=12)
        ttk.Checkbutton(opts, text="Also save the whole course in one file", variable=self.combined).pack(side="left")

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.fetch_button = ttk.Button(buttons, text="Fetch transcripts", command=self.start)
        self.fetch_button.pack(side="left", padx=4)
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.stop, state="disabled")
        self.cancel_button.pack(side="left", padx=4)
        self.open_button = ttk.Button(buttons, text="Open folder", command=self.open_folder, state="disabled")
        self.open_button.pack(side="left", padx=4)

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=7, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.status, wraplength=600).grid(row=8, column=0, columnspan=3, sticky="w", **pad)
        self.log = ScrolledText(frame, height=12, state="disabled", wrap="none", font=("TkFixedFont", 9))
        self.log.grid(row=9, column=0, columnspan=3, sticky="nsew", **pad)
        self.link_entry.focus_set()

    def _toggle_token(self) -> None:
        self.token_entry.configure(show="" if self.show_token.get() else "•")

    def token_help(self) -> None:
        messagebox.showinfo("Getting your access token", TOKEN_HELP, parent=self.root)

    def browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(Path.home()), parent=self.root)
        if folder:
            self.output_dir.set(folder)

    def _settings(self) -> Settings:
        return Settings(
            token=self.token.get().strip(),
            output_dir=self.output_dir.get().strip(),
            lang=self.lang.get().strip() or "en",
            numbered=self.numbered.get(),
            combined=self.combined.get(),
            remember_token=self.remember.get(),
        )

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        link = self.link.get().strip()
        problem = check_link(link)
        if not problem and not self.token.get().strip():
            problem = "Paste your Udemy access token first (see 'How do I get it?')."
        if not problem and not self.output_dir.get().strip():
            problem = "Choose a folder to save the transcripts in."
        if problem:
            messagebox.showwarning("Missing information", problem, parent=self.root)
            return

        settings = self._settings()
        try:
            settings.save(self.settings_path)
        except OSError:
            pass  # remembering settings is a convenience, not a requirement
        self.cancel.clear()
        self.folder = None
        self.progress.configure(value=0, maximum=1)
        self._set_running(True)
        self.worker = threading.Thread(
            target=run_job,
            args=(link, settings, self.events.put, self.cancel, self.session, self.delay),
            daemon=True,
        )
        self.worker.start()

    def stop(self) -> None:
        self.cancel.set()
        self.status.set("Cancelling after the current video...")

    def _set_running(self, running: bool) -> None:
        self.fetch_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.open_button.configure(state="normal" if self.folder and not running else "disabled")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "status":
            self.status.set(event[1])
        elif kind == "log":
            self._append_log(event[1])
        elif kind == "progress":
            self.progress.configure(value=event[1], maximum=max(event[2], 1))
        elif kind in ("done", "cancelled"):
            folder, saved, total = event[1:]
            self.folder = folder
            if kind == "cancelled":
                message = f"Cancelled. Saved {saved} transcript(s) to {folder}"
            else:
                message = f"Done. Saved {saved} of {total} video transcripts to {folder}"
                if saved < total:
                    message += f" ({total - saved} had no transcript, see the list below)"
            self.status.set(message)
            self._append_log(message)
            self._set_running(False)
        elif kind == "error":
            self.status.set("Failed: " + event[1])
            self._append_log("Error: " + event[1])
            self._set_running(False)
            messagebox.showerror("Could not fetch transcripts", event[1], parent=self.root)

    def open_folder(self) -> None:
        if not self.folder:
            return
        if sys.platform == "win32":
            os.startfile(self.folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.folder)])

    def close(self) -> None:
        self.cancel.set()
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root)
    root.title(f"Udemy Transcript Fetcher {__version__}")
    root.mainloop()


if __name__ == "__main__":
    main()
