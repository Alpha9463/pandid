"""Check ``Flowsheet.show()``: its keywords, its window, and its fallback.

No test calls ``mainloop()``. A window is built, inspected, and closed, and
the browser fallback is tested through the decision function.
"""

import inspect
import os
import sys
import time
from types import SimpleNamespace

import pytest

from pandid import Flowsheet, units as U
from pandid.render import preview as P

#: A 1x1 PNG for tests that need an image but not a drawing.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fs() -> Flowsheet:
    """Build a three-unit sheet with one tabulated stream.

    Returns
    -------
    Flowsheet
        Feed, pump, and product connected in series.
    """
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
    """Capture the SVG and title ``show()`` passes to the preview.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces ``preview`` with a recorder.

    Returns
    -------
    dict
        The ``svg`` and ``title`` of the last call.
    """
    seen: dict = {}

    def fake(svg, *, title=""):
        """Record one preview call without opening anything.

        Parameters
        ----------
        svg : str
            Rendered SVG markup.
        title : str, optional
            Flowsheet title.

        Returns
        -------
        str
            ``"window"``, as a successful preview returns.
        """
        seen["svg"], seen["title"] = svg, title
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


# --- The signature ------------------------------------------------------------


def test_show_takes_exactly_the_keywords_render_takes():
    """Hold ``show()`` to the keywords, kinds, and defaults of ``render()``.

    Returns
    -------
    None
        Every ``render()`` keyword except ``path`` matches on ``show()``.
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
        # These three do not change this sheet: a PFD marks no joints, no
        # lines cross, and ``check`` affects warnings rather than the drawing.
        ("connections", "flanged", False),
        ("jump_direction", "horizontal", False),
        ("check", False, False),
    ],
)
def test_every_keyword_reaches_the_drawing(caught, keyword, value, visible):
    """Forward each keyword to the renderer.

    Parameters
    ----------
    caught : dict
        Captured preview call.
    keyword : str
        ``show()`` keyword under test.
    value : object
        Value passed for the keyword.
    visible : bool
        Whether the value changes this sheet's drawing.

    Returns
    -------
    None
        The previewed SVG equals ``to_svg()`` for the same keyword.
    """
    _fs().show(**{keyword: value})
    assert caught["svg"] == _fs().to_svg(**{keyword: value})
    assert (caught["svg"] != _fs().to_svg()) is visible


def test_the_sheet_is_named_to_whatever_shows_it(caught):
    """Pass the flowsheet title to the preview.

    Parameters
    ----------
    caught : dict
        Captured preview call.

    Returns
    -------
    None
        The preview receives the sheet's title.
    """
    _fs().show()
    assert caught["title"] == "Sheet 1"


# --- Choosing a window or the browser -----------------------------------------


@pytest.fixture
def browsed(monkeypatch, tmp_path):
    """Redirect preview files to a temporary directory and stub the browser.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the preview directory and ``webbrowser.open``.
    tmp_path : pathlib.Path
        Parent of the preview directory.

    Returns
    -------
    list[str]
        URLs the module asked the browser to open.
    """
    opened: list[str] = []
    monkeypatch.setattr(P, "_dir", str(tmp_path / "preview"))
    (tmp_path / "preview").mkdir()
    monkeypatch.setattr(P.webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


def test_a_machine_with_no_display_falls_back_and_says_so(monkeypatch, browsed, capsys):
    """Open the browser and print the reason when no display exists.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Reports a missing display.
    browsed : list[str]
        URLs sent to the browser.
    capsys : pytest.CaptureFixture
        Captured standard output.

    Returns
    -------
    None
        One URL is opened and the reason is printed.
    """
    monkeypatch.setattr(P, "_no_display", lambda: "no display ($DISPLAY is unset)")
    assert P.preview("<svg/>", title="Sheet 1") == "browser"
    out = capsys.readouterr().out
    assert "no display ($DISPLAY is unset)" in out and "browser" in out
    assert len(browsed) == 1


def test_a_machine_with_no_rasteriser_falls_back_and_names_the_extra(monkeypatch, browsed, capsys):
    """Open the browser and name the ``pdf`` extra when it is missing.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Makes rasterisation raise ``ImportError``.
    browsed : list[str]
        URLs sent to the browser.
    capsys : pytest.CaptureFixture
        Captured standard output.

    Returns
    -------
    None
        One URL is opened and the message names ``pandid[pdf]``.
    """
    monkeypatch.setattr(P, "_no_display", lambda: "")
    monkeypatch.setattr(P, "_raster", lambda svg: (_ for _ in ()).throw(ImportError("no")))
    assert P.preview("<svg/>") == "browser"
    assert "pandid[pdf]" in capsys.readouterr().out
    assert len(browsed) == 1


def test_a_rasteriser_that_fails_falls_back_rather_than_raising(monkeypatch, browsed, capsys):
    """Open the browser when rasterisation raises.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Makes rasterisation raise ``RuntimeError``.
    browsed : list[str]
        URLs sent to the browser.
    capsys : pytest.CaptureFixture
        Captured standard output.

    Returns
    -------
    None
        The preview falls back and prints the error.
    """
    monkeypatch.setattr(P, "_no_display", lambda: "")

    def boom(svg):
        """Fail as a broken PNG backend would.

        Parameters
        ----------
        svg : str
            Rendered SVG markup.

        Raises
        ------
        RuntimeError
            Always.
        """
        raise RuntimeError("the PDF backend could not read the rendered SVG")

    monkeypatch.setattr(P, "_raster", boom)
    assert P.preview("<svg/>") == "browser"
    assert "could not read the rendered SVG" in capsys.readouterr().out


def test_the_display_check_answers_an_unset_display_without_importing_tkinter(monkeypatch):
    """Report an unset ``DISPLAY`` without importing tkinter.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Sets a Linux platform, unsets ``DISPLAY``, and blocks the import.

    Returns
    -------
    None
        The reason names ``DISPLAY``.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setitem(sys.modules, "tkinter", None)  # Make an import raise.
    assert "DISPLAY" in P._no_display()


def test_macos_without_a_gui_session_does_not_start_tkinter(monkeypatch):
    """Skip native Tk before it aborts in a headless macOS process.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Overrides the platform, session result, and tkinter import.

    Returns
    -------
    None
        The display check reports the missing session without importing Tk.
    """
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(P, "_macos_gui_session", lambda: False)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert "Quartz GUI session" in P._no_display()


def test_macos_with_a_gui_session_can_open_tkinter(monkeypatch):
    """Allow the window path when Quartz reports a GUI session.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies a GUI session and a small Tk root.

    Returns
    -------
    None
        The display check opens the root and closes it with no idle task left.
    """
    calls = []

    class Root:
        """Stand in for a Tk root.

        Notes
        -----
        Each call is recorded in ``calls``.
        """

        def withdraw(self) -> None:
            """Record that the temporary window was hidden.

            Returns
            -------
            None
                The call is appended to ``calls``.
            """
            calls.append("withdraw")

        def update_idletasks(self) -> None:
            """Record that pending idle tasks were run.

            Returns
            -------
            None
                The call is appended to ``calls``.
            """
            calls.append("update_idletasks")

        def destroy(self) -> None:
            """Record that the temporary window was closed.

            Returns
            -------
            None
                The call is appended to ``calls``.
            """
            calls.append("destroy")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(P, "_macos_gui_session", lambda: True)
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=Root, TclError=Exception))
    assert P._no_display() == ""
    # Tk 9 on macOS aborts when a later root services an idle task left by a
    # destroyed root, so idle tasks run before the root is destroyed.
    assert calls == ["withdraw", "update_idletasks", "destroy"]


# --- The temporary file -------------------------------------------------------


def test_the_browser_gets_a_url_a_browser_can_open(browsed):
    """Give the browser a ``file:///`` URL without backslashes.

    Parameters
    ----------
    browsed : list[str]
        URLs sent to the browser.

    Returns
    -------
    None
        The URL is a valid file URI on every platform.
    """
    P._browser("<svg/>", "Sheet 1", "testing")
    assert browsed[0].startswith("file:///")
    assert "\\" not in browsed[0]


def test_previewing_twenty_drafts_leaves_one_file(browsed, tmp_path):
    """Reuse one preview file for repeated previews of a sheet.

    Parameters
    ----------
    browsed : list[str]
        URLs sent to the browser.
    tmp_path : pathlib.Path
        Parent of the preview directory.

    Returns
    -------
    None
        Twenty previews leave a single file.
    """
    for _ in range(20):
        P._browser("<svg/>", "Sheet 1", "testing")
    assert len(list((tmp_path / "preview").iterdir())) == 1


def test_the_file_is_dropped_on_the_way_out(monkeypatch, browsed, tmp_path):
    """Remove the preview directory once the grace period has passed.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Expires the grace period.
    browsed : list[str]
        URLs sent to the browser.
    tmp_path : pathlib.Path
        Parent of the preview directory.

    Returns
    -------
    None
        The directory no longer exists.
    """
    P._browser("<svg/>", "Sheet 1", "testing")
    monkeypatch.setattr(P, "_grace_until", time.monotonic() - 1)
    P._discard()
    assert not (tmp_path / "preview").exists()


def test_a_browser_just_launched_keeps_its_file(browsed, tmp_path):
    """Keep the preview file while the browser may still be reading it.

    Parameters
    ----------
    browsed : list[str]
        URLs sent to the browser.
    tmp_path : pathlib.Path
        Parent of the preview directory.

    Returns
    -------
    None
        The file survives a discard inside the grace period.
    """
    P._browser("<svg/>", "Sheet 1", "testing")
    P._discard()
    assert (tmp_path / "preview" / "Sheet-1.svg").exists()


def test_the_sweep_takes_what_an_earlier_run_left(tmp_path):
    """Remove only stale preview directories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Directory holding a stale, a fresh, and an unrelated directory.

    Returns
    -------
    None
        The stale directory is removed and the other two remain.
    """
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
    """Reduce a sheet title to a safe filename stem.

    Parameters
    ----------
    title : str
        Flowsheet title.
    stem : str
        Expected filename stem.

    Returns
    -------
    None
        Path separators are removed and an empty result becomes ``sheet``.
    """
    assert P._slug(title) == stem


# --- The window itself --------------------------------------------------------


@pytest.mark.parametrize(
    "image,into,fitted",
    [
        ((1000, 500), (400, 400), (400, 200)),  # Width limits a wide image.
        ((500, 1000), (400, 400), (200, 400)),  # Height limits a tall image.
        ((400, 300), (800, 600), (800, 600)),  # A small image is enlarged.
        ((1000, 500), (1000, 500), (1000, 500)),  # An exact fit is unchanged.
        ((1000, 500), (3, 1), (2, 1)),  # Each side stays at least one pixel.
    ],
)
def test_the_sheet_is_fitted_to_the_window_and_never_stretched(image, into, fitted):
    """Scale an image into a window while keeping its aspect ratio.

    Parameters
    ----------
    image : tuple[int, int]
        Source width and height.
    into : tuple[int, int]
        Available width and height.
    fitted : tuple[int, int]
        Expected scaled width and height.

    Returns
    -------
    None
        ``_fit`` returns the expected size.
    """
    assert P._fit(image, into) == fitted


def _tk_or_skip():
    """Create a Tk root only when this process has a display.

    Returns
    -------
    tkinter.Tk
        Root window for the GUI test, if one can be opened.
    """
    why = P._no_display()
    if why:
        pytest.skip(why)
    tkinter = pytest.importorskip("tkinter")
    pytest.importorskip("PIL")
    try:
        root = tkinter.Tk()
    except tkinter.TclError as e:  # pragma: no cover - headless CI
        pytest.skip(f"no display: {e}")
    return root


def _drawn(root, canvas, width: int, height: int) -> tuple[int, int]:
    """Resize the window and return the size of the image it settles on.

    The redraw is delayed by ``_SETTLE_MS``, so ``update()`` is called again
    after that delay instead of entering the event loop.

    Parameters
    ----------
    root : tkinter.Tk
        Preview window.
    canvas : tkinter.Canvas
        Canvas holding the sheet image.
    width, height : int
        Requested window size in pixels.

    Returns
    -------
    tuple[int, int]
        Width and height of the drawn image.
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
    """Redraw the sheet at the canvas size when the window is resized.

    This test opens a real window and closes it in ``finally``.

    Returns
    -------
    None
        The image fits each window size, keeps its shape, and the title
        names the sheet.
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
        # Compare aspect ratios to confirm the image is not stretched.
        assert abs(small[0] / small[1] - large[0] / large[1]) < 0.05
        assert "pandid" in root.title() and "Sheet 1" in root.title()
    finally:
        P._close(root)


def test_the_window_closes_the_ways_an_image_viewer_does():
    """Bind Escape and ``q`` to close the window.

    Returns
    -------
    None
        Both key bindings exist on the root.
    """
    root = _tk_or_skip()
    try:
        P._window(root, _PNG, "t")
        assert root.bind("<Escape>") and root.bind("q")
    finally:
        P._close(root)


def test_the_module_never_writes_a_file_for_a_window(monkeypatch, tmp_path):
    """Create no preview directory when a window is shown.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies a display, a raster, and a stand-in Tk root.
    tmp_path : pathlib.Path
        Unused temporary directory.

    Returns
    -------
    None
        The preview reports a window and ``_dir`` stays unset.
    """
    monkeypatch.setattr(P, "_dir", None)
    monkeypatch.setattr(P, "_no_display", lambda: "")
    monkeypatch.setattr(P, "_raster", lambda svg: _PNG)
    monkeypatch.setattr(P, "_window", lambda root, png, title: None)

    class Root:
        """Stand in for a Tk root that returns from ``mainloop`` at once."""

        def mainloop(self):
            """Return immediately instead of running the event loop."""

        def destroy(self):
            """Accept the close request and do nothing."""

    monkeypatch.setattr("tkinter.Tk", Root)
    assert P.preview("<svg/>") == "window"
    assert P._dir is None
