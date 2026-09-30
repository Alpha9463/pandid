"""Preview rendered SVG in a Tk window or a browser.

``Flowsheet.show`` calls :func:`preview`. A window requires a graphical
session, tkinter, and the optional PDF export backend to rasterise SVG. When
any requirement is unavailable, the module writes an SVG file and opens it in
a browser. Preview files share a directory per process and stale directories
are removed on later runs.
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

#: Resize debounce delay in milliseconds.
_SETTLE_MS = 120

#: Maximum fraction of the screen used for the initial window.
_SCREEN_FRACTION = 0.9

#: Prefix for temporary preview directories.
_PREFIX = "pandid-preview-"

#: Maximum age of a preview directory before cleanup, in seconds.
_STALE_S = 6 * 3600.0

#: Browser grace period before cleanup, in seconds.
_GRACE_S = 5.0

_dir: str | None = None
_grace_until = 0.0


def _sweep(parent: Path) -> None:
    """Remove stale preview directories.

    Parameters
    ----------
    parent : Path
        Temporary-directory parent to scan.
    """
    cutoff = time.time() - _STALE_S
    for entry in parent.glob(f"{_PREFIX}*"):
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


def _preview_dir() -> Path:
    """Return this process's preview directory.

    Returns
    -------
    Path
        Directory created on first use and removed at interpreter exit when
        the browser grace period has elapsed.
    """
    global _dir
    if _dir is None:
        parent = Path(tempfile.gettempdir())
        _sweep(parent)
        _dir = tempfile.mkdtemp(prefix=_PREFIX, dir=parent)
        atexit.register(_discard)
    return Path(_dir)


def _discard() -> None:
    """Remove the process preview directory after the browser grace period."""
    if _dir is not None and time.monotonic() >= _grace_until:
        shutil.rmtree(_dir, ignore_errors=True)


def _macos_gui_session() -> bool:
    """Return whether Quartz exposes a GUI session to this process.

    Returns
    -------
    bool
        Whether Core Graphics returned a window server session dictionary.
    """
    import ctypes

    try:
        graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        foundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        session_info = graphics.CGSessionCopyCurrentDictionary
        session_info.argtypes = []
        session_info.restype = ctypes.c_void_p
        release = foundation.CFRelease
        release.argtypes = [ctypes.c_void_p]
        release.restype = None
    except (OSError, AttributeError):
        return False

    session = session_info()
    if not session:
        return False
    release(session)
    return True


def _no_display() -> str:
    """Return a display-unavailability reason, if any.

    Returns
    -------
    str
        A reason for browser fallback, or ``""`` when Tk can open a window.
    """
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        return "no display ($DISPLAY is unset)"
    if sys.platform == "darwin" and not _macos_gui_session():
        return "no Quartz GUI session"
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
    """Convert SVG markup to PNG bytes.

    Parameters
    ----------
    svg : str
        Rendered SVG markup.

    Returns
    -------
    bytes
        PNG image bytes at the renderer's native size.
    """
    from pandid.render import export
    return export.to_png(svg)


def _fit(image: tuple[int, int], into: tuple[int, int]) -> tuple[int, int]:
    """Scale an image to fit bounds while preserving its aspect ratio.

    Parameters
    ----------
    image : tuple[int, int]
        Source image width and height.
    into : tuple[int, int]
        Available width and height.

    Returns
    -------
    tuple[int, int]
        Scaled width and height, each at least one pixel.
    """
    scale = min(into[0] / image[0], into[1] / image[1])
    return max(1, round(image[0] * scale)), max(1, round(image[1] * scale))


def _window(root, png: bytes, title: str) -> None:
    """Configure a Tk window to display a resizable PNG preview.

    Parameters
    ----------
    root : tkinter.Tk
        Window that owns the preview canvas.
    png : bytes
        Source PNG image bytes.
    title : str
        Flowsheet title shown in the window title bar.
    """
    import tkinter

    from PIL import Image

    sheet = Image.open(io.BytesIO(png))
    # Check PNG support before registering resize callbacks.
    probe = io.BytesIO()
    Image.new("RGB", (1, 1)).save(probe, format="PNG")
    tkinter.PhotoImage(data=base64.b64encode(probe.getvalue()))
    root.title(f"pandid - {title}" if title else "pandid")
    root.geometry("{}x{}".format(
        max(320, min(sheet.width, int(root.winfo_screenwidth() * _SCREEN_FRACTION))),
        max(240, min(sheet.height, int(root.winfo_screenheight() * _SCREEN_FRACTION))),
    ))
    # Use a dark canvas background around the sheet.
    canvas = tkinter.Canvas(root, background="#3c3c3c", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # Retain the live image and its dimensions for Tk.
    held: dict = {"photo": None, "size": None, "job": None}

    def redraw() -> None:
        """Scale and draw the image for the current canvas dimensions."""
        held["job"] = None
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 2 or ch < 2:  # Wait until the canvas is mapped.
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
        """Schedule a redraw after a resize event settles.

        Parameters
        ----------
        _event : tkinter.Event
            Configure event emitted by the preview canvas.
        """
        if held["job"] is not None:
            canvas.after_cancel(held["job"])
        held["job"] = canvas.after(_SETTLE_MS, redraw)

    canvas.bind("<Configure>", on_configure)
    # Bind common keyboard shortcuts for closing the preview.
    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("q", lambda _e: root.destroy())


def _browser(svg: str, title: str, why: str) -> None:
    """Write SVG markup to a preview file and open it in a browser.

    Parameters
    ----------
    svg : str
        Rendered SVG markup.
    title : str
        Flowsheet title used in the temporary filename.
    why : str
        Reason a Tk window was unavailable.
    """
    global _grace_until
    path = _preview_dir() / f"{_slug(title)}.svg"
    path.parent.mkdir(parents=True, exist_ok=True)  # a sweep may have taken it
    path.write_text(svg, encoding="utf-8")
    print(f"pandid: no window available ({why}); opened {path} in your browser instead")
    _grace_until = time.monotonic() + _GRACE_S
    # Use a platform-correct file URI.
    webbrowser.open(path.as_uri())


def _slug(title: str) -> str:
    """Return a portable filename stem for a flowsheet title.

    Parameters
    ----------
    title : str
        Flowsheet title.

    Returns
    -------
    str
        Sanitised filename stem with a maximum length of 60 characters.
    """
    kept = "".join(c if c.isalnum() or c in "-_" else "-" for c in title).strip("-")
    return kept[:60] or "sheet"


def preview(svg: str, *, title: str = "") -> str:
    """Display rendered SVG in a Tk window or a browser fallback.

    Parameters
    ----------
    svg : str
        Rendered SVG markup.
    title : str, default=""
        Flowsheet title shown by the selected preview backend.

    Returns
    -------
    str
        ``"window"`` when the Tk preview closes, otherwise ``"browser"``.
    """
    why = _no_display()
    if not why:
        try:
            png = _raster(svg)
        except ImportError:
            why = "the PNG backend is not installed (pip install 'pandid[pdf]')"
        except Exception as e:
            # Report rasterisation failures through the browser fallback.
            why = f"the sheet could not be rasterised for a window ({type(e).__name__}: {e})"
        else:
            import tkinter
            root = tkinter.Tk()
            try:
                _window(root, png, title)
            except tkinter.TclError as e:
                # Fall back when Tk cannot read PNG data.
                root.destroy()
                why = f"this Tk cannot display a PNG ({e})"
            else:
                root.mainloop()
                return "window"
    _browser(svg, title, why)
    return "browser"
