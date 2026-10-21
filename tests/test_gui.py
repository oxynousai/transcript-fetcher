import time

import pytest

tk = pytest.importorskip("tkinter")

from transcript_fetcher.gui import App  # noqa: E402

from fakes import FakeSession, make_routes  # noqa: E402


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    yield root
    root.destroy()


def pump(root, until, timeout=10):
    deadline = time.monotonic() + timeout
    while not until():
        assert time.monotonic() < deadline, "timed out"
        root.update()
        time.sleep(0.01)


def test_fetch_from_the_window(root, tmp_path):
    app = App(root, settings_path=tmp_path / "settings.json", session=FakeSession(make_routes()), delay=0)
    app.link.set("https://www.udemy.com/course/alpha/")
    app.token.set("secret")
    app.output_dir.set(str(tmp_path / "out"))
    app.start()
    assert str(app.fetch_button["state"]) == "disabled"

    pump(root, lambda: app.status.get().startswith("Done"))
    assert app.status.get().startswith("Done. Saved 2 of 3 video transcripts")
    assert (tmp_path / "out" / "Alpha course" / "001 - Welcome.txt").exists()
    assert str(app.open_button["state"]) == "normal"
    assert str(app.fetch_button["state"]) == "normal"
    assert "Saved    003 - Setup.txt" in app.log.get("1.0", "end")
    assert (tmp_path / "settings.json").exists()


def test_token_visibility_toggle(root, tmp_path):
    app = App(root, settings_path=tmp_path / "settings.json")
    assert app.token_entry["show"] == "•"
    app.show_token.set(True)
    app._toggle_token()
    assert app.token_entry["show"] == ""
