"""``Flowsheet.show()``: the same keywords ``render()`` takes, a window
where there is one, and the browser where there is not.

Nothing here calls ``mainloop()``. A window that blocks until it is closed
is the point of the feature and the one thing a test suite must never
open, so the window is built and inspected and then destroyed, and every
test of the fallback drives the decision function rather than the display.
"""

import inspect
import os
import sys
import time

import pytest

from pandid import Flowsheet, units as U
from pandid.render import preview as P

#: A 1x1 PNG, for the tests that need *an* image and not a drawing.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fs() -> Flowsheet:
    fs = Flowsheet("Sheet 1")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-101"))
    prod = fs.add(U.Product("PR"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    fs.streams[0].properties = {"Flow (kg/h)": "1000"}
    return fs


@pytest.fixture
def caught(monkeypatch):
    """``show()`` stopped at the display: the SVG it produced, unshown."""
    seen: dict = {}

    def fake(svg, *, title=""):
        seen["svg"], seen["title"] = svg, title
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


# --- the signature ------------------------------------------------------------


def test_show_takes_exactly_the_keywords_render_takes():
    """The guard the docstring names.

    ``show()`` had none of ``render()``'s nine keywords, so the one call an
    author makes while drafting could not preview a stream table or a P&ID.
    Restating the list is what let them drift apart in the first place, so
    the list is restated *once* and held equal here: a keyword added to
    ``render()`` and not to ``show()`` fails on the day it lands.
    """
    render = inspect.signature(Flowsheet.render).parameters
    show = inspect.signature(Flowsheet.show).parameters
    assert [n for n in render if n != "path"] == list(show)
    for name, parameter in show.items():
        if name == "self":
            continue
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default == render[name].default
        assert parameter.annotation == render[name].annotation


@pytest.mark.parametrize(
    "keyword,value,visible",
    [
        ("show_stream_table", True, True),
        ("border", "zone", True),
        ("diagram", "p&id", True),
        ("page_size", "A3", True),
        ("debug", True, True),
        # The three that this sheet cannot show a difference for, and it is the
        # sheet rather than the forwarding: a PFD marks no joints whatever
        # ``connections`` says, nothing on it crosses for ``jump_direction`` to
        # hop, and ``check`` decides what lands on ``fs.warnings`` rather than
        # what is drawn. Equality with ``to_svg()`` is still the contract.
        ("connections", "flanged", False),
        ("jump_direction", "horizontal", False),
        ("check", False, False),
    ],
)
def test_every_keyword_reaches_the_drawing(caught, keyword, value, visible):
    """Taking the keyword is half of it; the sheet shown has to be the sheet
    ``to_svg()`` would have returned for the same words."""
    _fs().show(**{keyword: value})
    assert caught["svg"] == _fs().to_svg(**{keyword: value})
    assert (caught["svg"] != _fs().to_svg()) is visible


def test_the_sheet_is_named_to_whatever_shows_it(caught):
    _fs().show()
    assert caught["title"] == "Sheet 1"


# --- choosing a window or the browser -----------------------------------------


@pytest.fixture
def browsed(monkeypatch, tmp_path):
    """A preview directory under *tmp_path* and the browser stubbed out."""
    opened: list[str] = []
    monkeypatch.setattr(P, "_dir", str(tmp_path / "preview"))
    (tmp_path / "preview").mkdir()
    monkeypatch.setattr(P.webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


def test_a_machine_with_no_display_falls_back_and_says_so(monkeypatch, browsed, capsys):
    monkeypatch.setattr(P, "_no_display", lambda: "no display ($DISPLAY is unset)")
    assert P.preview("<svg/>", title="Sheet 1") == "browser"
    out = capsys.readouterr().out
    assert "no display ($DISPLAY is unset)" in out and "browser" in out
    assert len(browsed) == 1


def test_a_machine_with_no_rasteriser_falls_back_and_names_the_extra(monkeypatch, browsed, capsys):
    """The window needs the ``pdf`` extra to turn the SVG into pixels. Without
    it there is still a drawing to look at, so the browser gets it and the
    message says what would buy a window."""
    monkeypatch.setattr(P, "_no_display", lambda: "")
    monkeypatch.setattr(P, "_raster", lambda svg: (_ for _ in ()).throw(ImportError("no")))
    assert P.preview("<svg/>") == "browser"
    assert "pandid[pdf]" in capsys.readouterr().out
    assert len(browsed) == 1


def test_a_rasteriser_that_fails_falls_back_rather_than_raising(monkeypatch, browsed, capsys):
    """A window that cannot be drawn is not a render that failed: the SVG the
    browser is handed is the renderer's own output and is unaffected."""
    monkeypatch.setattr(P, "_no_display", lambda: "")

    def boom(svg):
        raise RuntimeError("the PDF backend could not read the rendered SVG")

    monkeypatch.setattr(P, "_raster", boom)
    assert P.preview("<svg/>") == "browser"
    assert "could not read the rendered SVG" in capsys.readouterr().out


def test_the_display_check_answers_an_unset_display_without_importing_tkinter(monkeypatch):
    """The headless case is answered from the environment, so nothing can
    block on a socket to a display that is not listening."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setitem(sys.modules, "tkinter", None)  # an import would raise
    assert "DISPLAY" in P._no_display()


# --- the temporary file -------------------------------------------------------


def test_the_browser_gets_a_url_a_browser_can_open(browsed):
    """``"file://" + r"C:\\Users\\..."`` is a URL whose *hostname* is ``C:``,
    and a browser opens nothing at all from it."""
    P._browser("<svg/>", "Sheet 1", "testing")
    assert browsed[0].startswith("file:///")
    assert "\\" not in browsed[0]


def test_previewing_twenty_drafts_leaves_one_file(browsed, tmp_path):
    for _ in range(20):
        P._browser("<svg/>", "Sheet 1", "testing")
    assert len(list((tmp_path / "preview").iterdir())) == 1


def test_the_file_is_dropped_on_the_way_out(monkeypatch, browsed, tmp_path):
    P._browser("<svg/>", "Sheet 1", "testing")
    monkeypatch.setattr(P, "_grace_until", time.monotonic() - 1)
    P._discard()
    assert not (tmp_path / "preview").exists()


def test_a_browser_just_launched_keeps_its_file(browsed, tmp_path):
    """``webbrowser.open`` returns when the browser is *launched*, which on a
    cold start is before it has read anything. Deleting then would blank the
    tab that is opening, so the file is left for the next run's sweep."""
    P._browser("<svg/>", "Sheet 1", "testing")
    P._discard()
    assert (tmp_path / "preview" / "Sheet-1.svg").exists()


def test_the_sweep_takes_what_an_earlier_run_left(tmp_path):
    stale = tmp_path / f"{P._PREFIX}old"
    fresh = tmp_path / f"{P._PREFIX}new"
    other = tmp_path / "not-ours"
    for d in (stale, fresh, other):
        d.mkdir()
        (d / "sheet.svg").write_text("<svg/>", encoding="utf-8")
    old = time.time() - P._STALE_S - 60
    os.utime(stale, (old, old))
    P._sweep(tmp_path)
    assert not stale.exists()
    assert fresh.exists() and other.exists()


@pytest.mark.parametrize(
    "title,stem",
    [
        ("Sheet 1", "Sheet-1"),
        ("../../etc/passwd", "etc-passwd"),
        ("", "sheet"),
        ("///", "sheet"),
    ],
)
def test_a_sheet_name_reaching_a_path_keeps_only_what_a_path_takes(title, stem):
    assert P._slug(title) == stem


# --- the window itself --------------------------------------------------------


@pytest.mark.parametrize(
    "image,into,fitted",
    [
        ((1000, 500), (400, 400), (400, 200)),  # wide: width binds
        ((500, 1000), (400, 400), (200, 400)),  # tall: height binds
        ((400, 300), (800, 600), (800, 600)),  # smaller than the window: filled
        ((1000, 500), (1000, 500), (1000, 500)),  # exact
        ((1000, 500), (3, 1), (2, 1)),  # never rounded away to nothing
    ],
)
def test_the_sheet_is_fitted_to_the_window_and_never_stretched(image, into, fitted):
    """The window's whole geometry, checked where no display is needed. The
    shape is the drawing's; only the size is the window's."""
    assert P._fit(image, into) == fitted


def _tk_or_skip():
    tkinter = pytest.importorskip("tkinter")
    pytest.importorskip("PIL")
    try:
        root = tkinter.Tk()
    except tkinter.TclError as e:  # pragma: no cover - headless CI
        pytest.skip(f"no display: {e}")
    return root


def _drawn(root, canvas, width: int, height: int) -> tuple[int, int]:
    """Resize the window and return the size of the image it settles on.

    The redraw is scheduled rather than immediate (see ``_SETTLE_MS``), so
    the pending timer is let run -- ``update()`` services one that is due --
    instead of the event loop being entered, which would not return.
    """
    root.geometry(f"{width}x{height}")
    root.update()
    time.sleep(P._SETTLE_MS / 1000 + 0.1)
    root.update()
    items = canvas.find_all()
    assert len(items) == 1, "the sheet is one canvas image, replaced in place"
    name = canvas.itemcget(items[0], "image")
    return root.tk.call("image", "width", name), root.tk.call("image", "height", name)


def test_the_window_draws_the_sheet_scaled_to_the_window():
    """A window and not a fixed-size picture: the image is remade for the
    size the canvas has, so resizing the window resizes the drawing rather
    than cropping it or leaving it alone.

    The one test here that opens a real window (briefly, and closed in a
    ``finally``); everything it needs a display for is the wiring, since
    the arithmetic is :func:`_fit`'s and is checked above without one.
    """
    from pandid.render import export

    root = _tk_or_skip()
    try:
        P._window(root, export.to_png(_fs().to_svg()), "Sheet 1")
        canvas = root.winfo_children()[0]
        small = _drawn(root, canvas, 400, 300)
        large = _drawn(root, canvas, 700, 550)
        assert small[0] <= 400 and small[1] <= 300
        assert large[0] > small[0] and large[1] > small[1]
        # The same drawing, so the same shape: fitted, never stretched.
        assert abs(small[0] / small[1] - large[0] / large[1]) < 0.05
        assert "pandid" in root.title() and "Sheet 1" in root.title()
    finally:
        root.destroy()


def test_the_window_closes_the_ways_an_image_viewer_does():
    root = _tk_or_skip()
    try:
        P._window(root, _PNG, "t")
        assert root.bind("<Escape>") and root.bind("q")
    finally:
        root.destroy()


def test_the_module_never_writes_a_file_for_a_window(monkeypatch, tmp_path):
    """A window is handed bytes. Only the browser needs somewhere on disk to
    point at, so the window path leaves nothing behind at all."""
    monkeypatch.setattr(P, "_dir", None)
    monkeypatch.setattr(P, "_no_display", lambda: "")
    monkeypatch.setattr(P, "_raster", lambda svg: _PNG)
    monkeypatch.setattr(P, "_window", lambda root, png, title: None)

    class Root:
        def mainloop(self):
            pass

        def destroy(self):
            pass

    monkeypatch.setattr("tkinter.Tk", Root)
    assert P.preview("<svg/>") == "window"
    assert P._dir is None
