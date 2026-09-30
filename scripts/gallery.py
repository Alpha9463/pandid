#!/usr/bin/env python3
"""Generate SVG and PNG gallery assets from example flowsheets.

Run ``python scripts/gallery.py`` after an example or renderer change, then
review the generated assets. A version-only package update needs no redraw.
"""

import argparse
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from pandid import Flowsheet  # noqa: E402
from pandid.render import export  # noqa: E402

EXAMPLES = ROOT / "examples"
GALLERY = ROOT / "docs" / "gallery"

# Keep the smallest title-block lettering readable in gallery previews.
WIDTH = 2400


def _pandid_is_this_checkout() -> None:
    """Confirm that gallery rendering imports this checkout's package.

    Returns
    -------
    None
        The imported package belongs to this repository.

    Raises
    ------
    SystemExit
        If a previously imported package does not belong to this repository.
    """
    import pandid

    where = pathlib.Path(pandid.__file__).resolve()
    if not where.is_relative_to(ROOT):
        raise SystemExit(
            f"refusing to generate the gallery: pandid was imported from\n"
            f"    {where}\n"
            f"which is not this checkout at\n    {ROOT}\n"
            f"The drawings would be the installed release's, not this tree's."
        )


def sheets() -> list[str]:
    """Return gallery example stems in filename order.

    Returns
    -------
    list[str]
        Example filename stems used for gallery asset names.
    """
    return sorted(p.stem for p in EXAMPLES.glob("[0-9]*.py"))


def _stamp(fs: Flowsheet) -> None:
    """Populate a blank title-block date from the latest revision.

    Parameters
    ----------
    fs : pandid.Flowsheet
        Flowsheet whose title block may need a stable date.

    Returns
    -------
    None
        The title block is updated in place when a revision date is available.
    """
    tb = getattr(fs, "title_block", None)
    if tb is not None and not tb.date and tb.revisions:
        tb.date = tb.revisions[-1].date


def flowsheet(stem: str) -> "tuple[Flowsheet, dict]":
    """Capture one example flowsheet and its SVG render options.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    tuple[pandid.Flowsheet, dict]
        Captured flowsheet and the options supplied to its SVG render call.

    Raises
    ------
    SystemExit
        If the example does not request exactly one SVG render.
    """
    caught: list[tuple[Flowsheet, dict]] = []
    original = Flowsheet.render

    def capture(self, path, **kwargs):
        """Capture one SVG render request without writing its output.

        Parameters
        ----------
        self : pandid.Flowsheet
            Flowsheet passed to :meth:`pandid.Flowsheet.render`.
        path : str or pathlib.Path
            Requested output path.
        **kwargs : object
            Render options passed by the example.

        Returns
        -------
        None
            The SVG render request is appended to the local capture list.
        """
        if pathlib.Path(path).suffix.lower() != ".drawio":
            caught.append((self, kwargs))

    sys.path.insert(0, str(EXAMPLES))  # the examples' own _bootstrap
    Flowsheet.render = capture  # type: ignore[method-assign]
    try:
        spec = importlib.util.spec_from_file_location(f"_gallery_{stem}", EXAMPLES / f"{stem}.py")
        if spec is None or spec.loader is None:
            raise SystemExit(f"could not import examples/{stem}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not caught and hasattr(module, "main"):
            module.main()
    finally:
        Flowsheet.render = original  # type: ignore[method-assign]
        sys.path.remove(str(EXAMPLES))

    if len(caught) != 1:
        raise SystemExit(
            f"examples/{stem}.py drew {len(caught)} sheets, not one. The gallery is "
            f"one file per example; teach this script what the second one is called."
        )
    fs, kwargs = caught[0]
    _stamp(fs)
    return fs, kwargs


def render(stem: str) -> str:
    """Render one example as canonical SVG without writing output files.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    str
        Canonical SVG document.
    """
    fs, kwargs = flowsheet(stem)
    return normalize(fs.to_svg(**kwargs))


def normalize(svg: str) -> str:
    """Canonicalize unordered SVG definitions for reproducible assets.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    str
        SVG document with sorted marker and definition entries.
    """
    lines = svg.split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<defs>")
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</defs>")
    except StopIteration:
        return svg
    body = lines[start + 1 : end]
    markers = []
    j = 0
    while j < len(body) and body[j].strip().startswith("<marker "):
        markers.append(tuple(body[j : j + 3]))
        j += 3
    markers.sort()
    new_body = [line for group in markers for line in group] + sorted(body[j:])
    return "\n".join(lines[: start + 1] + new_body + lines[end:])


def rasterize(svg: str, width: int = WIDTH) -> bytes:
    """Rasterize an SVG document to a PNG of the requested width.

    Parameters
    ----------
    svg : str
        SVG document to convert.
    width : int, optional
        Output width in device pixels.

    Returns
    -------
    bytes
        PNG image data.
    """
    import pypdfium2

    page_pt = pypdfium2.PdfDocument(export.to_pdf(svg))[0].get_width()
    return export.to_png(svg, scale=width / page_pt)


def main() -> None:
    """Generate SVG assets and, unless disabled, PNG gallery previews.

    Returns
    -------
    None
        Assets are written to :data:`GALLERY`.
    """
    description = __doc__.split("\n", 1)[0] if __doc__ is not None else "Generate gallery assets"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--svg-only",
        action="store_true",
        help="rewrite the .svg sheets and leave the .png rasters alone "
        "(they need the optional [pdf] backend)",
    )
    args = parser.parse_args()

    _pandid_is_this_checkout()
    GALLERY.mkdir(parents=True, exist_ok=True)
    for stem in sheets():
        svg = render(stem)
        (GALLERY / f"{stem}.svg").write_text(svg, encoding="utf-8")
        if args.svg_only:
            print(f"wrote {stem}.svg")
            continue
        # Rasterise the sheet just written, not the one in hand, so a PNG can
        # never show a drawing its own SVG does not.
        png = rasterize((GALLERY / f"{stem}.svg").read_text(encoding="utf-8"))
        (GALLERY / f"{stem}.png").write_bytes(png)
        print(f"wrote {stem}.svg and {stem}.png ({len(png) / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
