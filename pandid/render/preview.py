"""Put a rendered sheet on screen: a window if there is one to be had,
the browser if there is not.

:meth:`pandid.flowsheet.Flowsheet.show` is the call an author reaches
for while drafting, and what it wants is what ``matplotlib.pyplot.show``
gives -- the drawing in a window, sized to the window, that closes when
you close it. This module is that window, and the fallback for the
machines that cannot have one.

**Why tkinter, and nothing new in ``pyproject.toml``.** ``dependencies``
is empty and stays empty. tkinter is stdlib, and its ``PhotoImage``
reads PNG on its own from Tk 8.6 (which every CPython 3.10+ build ships
), so the window itself costs nothing to install. The one thing tkinter
cannot do is turn an SVG into pixels -- and a converter is already here,
in the optional ``pdf`` extra that :func:`pandid.render.export.to_png`
dispatches to for a ``.png`` render. So the window is drawn from the
same raster the author would have got by rendering to a file, and needs
no package that was not already an option.

matplotlib would supply both halves in one import, and was rejected: a
compiled numerical plotting stack is a large thing to make a preview
depend on, it would be a *new* dependency rather than one already listed
for another purpose, and what it would be asked to do is draw a bitmap
in a frame -- which is the whole of what the fifty lines below do.

**Three ways there is no window**, and each falls back rather than
raising, because the author asked to see a drawing and a browser shows
it perfectly well:

* no tkinter -- a Python built ``--without-tk``, which is what most slim
  container images ship;
* no display -- CI, a container, SSH without X11 forwarding. Detected by
  building the root window and catching :class:`tkinter.TclError`, plus
  an ``$DISPLAY`` check first on X11 so the common headless case never
  reaches Tk at all;
* no rasteriser -- ``pandid`` installed without the ``pdf`` extra.

Each says which way it went and why, on stdout. A call that silently did
something other than what it usually does would leave an author waiting
for a window that is never coming.
"""

from __future__ import annotations

import atexit
import base64
import io
import os
import shutil
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

#: Milliseconds a resize is left to settle before the image is scaled to
#: the new window. A drag fires ``<Configure>`` continuously and each
#: redraw resamples the whole sheet, so redrawing on every one of them
#: makes the drag stutter; redrawing once it stops does not.
_SETTLE_MS = 120

#: The window opens at this fraction of the screen at most, so a sheet
#: rasterised larger than the display does not open off the edge of it.
_SCREEN_FRACTION = 0.9

#: What a preview directory is called. Named rather than random-prefixed
#: so a later run can recognise one left behind by an earlier one; see
#: :func:`_preview_dir`.
_PREFIX = "pandid-preview-"

#: How long a preview directory is left alone before another run sweeps
#: it. Comfortably longer than any browser takes to read the file, and
#: short enough that a temp directory does not collect a week of them.
_STALE_S = 6 * 3600.0

#: How long after pointing a browser at the file this process refuses to
#: delete it on the way out. ``webbrowser.open`` returns as soon as the
#: browser has been *launched*, which on a cold start is well before it
#: has read anything, so a script whose last statement is ``show()``
#: would otherwise delete the file out from under the tab that is about
#: to open it. Nothing waits for this: the deletion is skipped, not
#: delayed, and the file is picked up by the sweep in the next run.
_GRACE_S = 5.0

_dir: str | None = None
_grace_until = 0.0


def _sweep(parent: Path) -> None:
    """Remove preview directories older than :data:`_STALE_S`.

    The other half of :data:`_GRACE_S`: what this process declined to
    delete because a browser might still be opening it, the next process
    to preview anything deletes. ``ignore_errors`` throughout -- a
    directory belonging to a *running* interpreter is exactly as
    deletable as one belonging to a finished one and the failure is of
    no interest either way.
    """
    cutoff = time.time() - _STALE_S
    for entry in parent.glob(f"{_PREFIX}*"):
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


def _preview_dir() -> Path:
    """This process's preview directory, made on first use.

    One directory per interpreter, holding one file that every
    ``show()`` overwrites, rather than a fresh ``mkstemp`` per call: a
    loop that previews twenty drafts leaves one file behind, not twenty.
    """
    global _dir
    if _dir is None:
        parent = Path(tempfile.gettempdir())
        _sweep(parent)
        _dir = tempfile.mkdtemp(prefix=_PREFIX, dir=parent)
        atexit.register(_discard)
    return Path(_dir)


def _discard() -> None:
    """Drop the preview file on the way out, unless a browser was sent
    to it too recently to have read it. See :data:`_GRACE_S`."""
    if _dir is not None and time.monotonic() >= _grace_until:
        shutil.rmtree(_dir, ignore_errors=True)


def _no_display() -> str:
    """Why a window cannot be opened here, or ``""`` if one can.

    The X11 check comes first and without importing tkinter, because an
    unset ``$DISPLAY`` is the headless case that matters -- CI, a
    container, SSH without forwarding -- and answering it from an
    environment variable is both instant and incapable of blocking on a
    socket to a display that is not listening. Windows and macOS have no
    such variable and are asked the only way they can be asked, by
    building a root window; :class:`tkinter.TclError` is what a session
    with no window station of its own answers with.
    """
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        return "no display ($DISPLAY is unset)"
    try:
        import tkinter
    except ImportError:
        return "this Python was built without tkinter"
    try:
        root = tkinter.Tk()
    except tkinter.TclError as e:
        return f"no display ({e})"
    root.destroy()
    return ""


def _raster(svg: str) -> bytes:
    """*svg* as PNG bytes, at the size ``render("sheet.png")`` gives.

    One pixel per drawing unit, which is where the renderer's own type
    sizes were chosen to be legible, so a sheet reads on screen at the
    size it reads on paper. Rasterising larger would be sharper under a
    zoom and costs memory as the square of the factor -- a 4000-unit
    sheet at 3x is a 140-megapixel image -- for a preview.
    """
    from pandid.render import export
    return export.to_png(svg)


def _fit(image: tuple[int, int], into: tuple[int, int]) -> tuple[int, int]:
    """*image* scaled to sit wholly inside *into*, keeping its shape.

    The whole of the window's geometry, kept out of the widget code so
    that it can be checked on a machine with no display -- which is most
    of the machines this suite runs on.

    Upscaling is allowed. The raster is one pixel per drawing unit (see
    :func:`_raster`), so a small sheet in a large window would otherwise
    sit as a stamp in the middle of it, and an image viewer that will not
    fill its own window is not what was asked for.
    """
    scale = min(into[0] / image[0], into[1] / image[1])
    return max(1, round(image[0] * scale)), max(1, round(image[1] * scale))


def _window(root, png: bytes, title: str) -> None:
    """Fill *root* with the sheet, scaled to whatever size it is given.

    A canvas rather than a label, because the image is re-made at every
    settled size and a canvas item is replaced without the widget
    relaying out around it. The scaled PNG is handed to Tk as base64
    rather than through ``PIL.ImageTk``: ``ImageTk`` needs a Pillow built
    against Tk, and ``PhotoImage(data=...)`` needs only Tk 8.6, so the
    window has one fewer way to be unavailable on a machine that has
    everything the ``pdf`` extra asks for.
    """
    import tkinter

    from PIL import Image

    sheet = Image.open(io.BytesIO(png))
    # Ask, here, whether this Tk reads PNG at all -- 8.5 does not. The
    # image the window shows is built inside a <Configure> callback, and
    # an exception raised in one of those is printed by Tk and stepped
    # over, leaving an empty window and no way back to the browser. A
    # one-pixel image asks the same question where the answer can still
    # be acted on, and decodes nothing of the sheet to ask it.
    probe = io.BytesIO()
    Image.new("RGB", (1, 1)).save(probe, format="PNG")
    tkinter.PhotoImage(data=base64.b64encode(probe.getvalue()))
    root.title(f"pandid - {title}" if title else "pandid")
    root.geometry("{}x{}".format(
        max(320, min(sheet.width, int(root.winfo_screenwidth() * _SCREEN_FRACTION))),
        max(240, min(sheet.height, int(root.winfo_screenheight() * _SCREEN_FRACTION))),
    ))
    # Dark surround, so the white sheet reads as a sheet with an edge
    # rather than as the window's own background.
    canvas = tkinter.Canvas(root, background="#3c3c3c", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # Tk does not own the image it is drawing -- a PhotoImage with no
    # Python reference is collected and the canvas draws nothing -- so
    # the live one is held here, and the size it was made for with it, so
    # a <Configure> that reports the size already drawn does no work.
    held: dict = {"photo": None, "size": None, "job": None}

    def redraw() -> None:
        held["job"] = None
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 2 or ch < 2:  # not mapped yet; the next <Configure> has real numbers
            return
        size = _fit((sheet.width, sheet.height), (cw, ch))
        if size == held["size"]:
            return
        buffer = io.BytesIO()
        sheet.resize(size, Image.Resampling.LANCZOS).save(buffer, format="PNG")
        photo = tkinter.PhotoImage(data=base64.b64encode(buffer.getvalue()))
        held["photo"], held["size"] = photo, size
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")

    def on_configure(_event) -> None:
        if held["job"] is not None:
            canvas.after_cancel(held["job"])
        held["job"] = canvas.after(_SETTLE_MS, redraw)

    canvas.bind("<Configure>", on_configure)
    # Escape and q close it, as every image viewer does; the window
    # manager's own close button already works.
    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("q", lambda _e: root.destroy())


def _browser(svg: str, title: str, why: str) -> None:
    """Write *svg* where a browser can read it and open it there."""
    global _grace_until
    path = _preview_dir() / f"{_slug(title)}.svg"
    path.parent.mkdir(parents=True, exist_ok=True)  # a sweep may have taken it
    path.write_text(svg, encoding="utf-8")
    print(f"pandid: no window available ({why}); opened {path} in your browser instead")
    _grace_until = time.monotonic() + _GRACE_S
    # `as_uri()` rather than "file://" + the path: on Windows the latter
    # produces file://C:\... , which is a hostname of "C:" and a browser
    # opens nothing at all.
    webbrowser.open(path.as_uri())


def _slug(title: str) -> str:
    """*title* as a filename stem. The sheet's name is on the browser tab
    and in the window title, so it is worth carrying; it is also author
    text and reaches a path, so only the characters every filesystem
    takes survive it."""
    kept = "".join(c if c.isalnum() or c in "-_" else "-" for c in title).strip("-")
    return kept[:60] or "sheet"


def preview(svg: str, *, title: str = "") -> str:
    """Show *svg*, and say which way it was shown: ``"window"`` or
    ``"browser"``.

    Blocks until the window is closed, the way ``matplotlib.pyplot.show``
    blocks. The browser fallback cannot block -- ``webbrowser.open``
    returns once the browser is launched -- and does not pretend to.
    """
    why = _no_display()
    if not why:
        try:
            png = _raster(svg)
        except ImportError:
            why = "the PNG backend is not installed (pip install 'pandid[pdf]')"
        except Exception as e:
            # Broad, and reported rather than swallowed.
            # Any failure to rasterise is a failure of the window and not
            # of the drawing: the SVG itself is what the browser is about
            # to be handed, and it is the renderer's native output.
            why = f"the sheet could not be rasterised for a window ({type(e).__name__}: {e})"
        else:
            import tkinter
            root = tkinter.Tk()
            try:
                _window(root, png, title)
            except tkinter.TclError as e:
                # Tk 8.5 has no PNG reader, so PhotoImage(data=) refuses
                # the image. Nothing else here is version-dependent.
                root.destroy()
                why = f"this Tk cannot display a PNG ({e})"
            else:
                root.mainloop()
                return "window"
    _browser(svg, title, why)
    return "browser"
