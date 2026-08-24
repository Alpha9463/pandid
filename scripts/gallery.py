#!/usr/bin/env python3
"""Generate docs/gallery/: every example rendered to SVG and rasterised to PNG.

The gallery is the first thing a reader sees and the last generated artefact
that had nothing holding it to its source. It drifted: `04_control_loop.svg` sat
on `main` for a dozen rendering PRs showing a drawing the package had stopped
producing. This script is the one command that rebuilds it, and
`tests/test_gallery.py` is what fails when the committed copy is not what it
emits -- the same pairing `scripts/vendor_symbols.py` and `scripts/gen_devices.py`
already have with their own generated files.

Run:  python scripts/gallery.py

Three things it does that copying the examples' own output by hand did not.

**It renders against this checkout.** ``examples/_bootstrap.py`` prepends the
repo root only when ``find_spec("pandid") is None``, so on a machine with a
released ``pandid`` installed -- which is most machines, and every one that has
run ``pip install pandid`` once -- running an example plainly renders against
*that* and not against the working tree. A gallery built that way shows the last
release, and a check built that way passes against the wrong code. This puts the
checkout first on ``sys.path`` and then refuses to run unless that is where
``pandid`` came from.

**It never has to rename anything.** Each example writes a name of its own into
``examples/`` (``01_ammonia_loop.py`` writes ``ammonia_auto.svg``), so copying
the output in was a rename, done by hand, once per example. Instead of running
the scripts and copying files, this imports each one with ``Flowsheet.render``
stubbed, catching the flowsheet and the keyword arguments it was about to be
drawn with, and renders it here under the example's own stem. Nothing is written
into ``examples/`` and there is no mapping to get wrong.

**It stamps a date that does not churn.** ``03`` and ``08`` leave
``TitleBlock.date`` blank, which the renderer fills in with today's, so
regenerating them moved the date and nothing else -- a daily diff on a
committed artefact and a freshness check that could never compare exactly.
:func:`_stamp` fills that field, before the render, with the newest revision's
date: the date the sheet was in fact issued at, taken from the sheet's own
revision history rather than from a constant kept in step by hand.
``tests/test_golden.py`` pins the same field, to the same value, so the golden
and the gallery sheet made from one example are the same drawing rather than two
that differ in one cell;
``test_no_fixture_dates_a_sheet_differently_from_the_generator`` holds them to
it. Only a *blank* field is filled: a date the author stated is theirs, and
replacing it would ship a drawing dated a day nobody typed
(``test_the_generator_leaves_a_date_the_sheet_states_alone``).
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

# Raster width, in device pixels, chosen by measuring the smallest type any
# sheet carries: the 7.5-unit lettering of the title block's revision rows.
#
# Crop one revision row's description cell -- glyphs only, no rule -- and read
# the darkest pixel in it. Across the five sheets that carried a title block
# when the width was chosen (13 and 14 have since added two more, and are the
# same 7,5-unit lettering at the same widths):
#
#     width     03    08    09    10    11
#     1600      65    50    50    57    57
#     2000      49    27    28    28    28
#     2400      29    13     0    14    16
#     3000       9     0     0     1     1
#
# At 1600 the darkest ink in that lettering is mid-grey; the strings are legible
# as shapes and not as letters. 2400 puts every sheet at or near black, and the
# inked fraction of the cell stops climbing there -- at 3000 it is flat or a
# shade lower, which is more anti-aliasing rather than more letter. Sixteen
# PNGs weigh 1.56 MiB at 1600, 2.56 at 2400 and 3.35 at 3000, so the 1.00 MiB
# from 1600 to 2400 buys a readable title block and the next 0.79 buys very
# little. (The darkest-pixel table above is per sheet and does not move with the
# size of the corpus; the weights do, and are re-measured with it.)
#
# Supersampling and downsampling does not substitute: rendering at 2x and
# resampling averages a one-pixel stroke back into its background, which is the
# same grey by another route. Device pixels are what a 7.5-unit glyph needs.
WIDTH = 2400


def _pandid_is_this_checkout() -> None:
    """Refuse to render against some other copy of the library.

    ``sys.path.insert`` above puts this checkout first, so this only fires when
    something else has already imported ``pandid`` -- but that is exactly the
    case that has to be loud, because everything downstream of it looks right.
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
    """Every example's stem, in sheet order. The gallery is named after these."""
    return sorted(p.stem for p in EXAMPLES.glob("[0-9]*.py"))


def _stamp(fs: Flowsheet) -> None:
    """Fill a blank title-block date with the newest revision's.

    A drawing's date cell is the date of the issue it is at, which is the date
    of the revision at the top of its history. Left blank, ``SvgRenderer`` puts
    today's there instead -- right for a sheet drawn today, wrong for one
    committed to a repository, where it makes the file differ from itself
    tomorrow.
    """
    tb = getattr(fs, "title_block", None)
    if tb is not None and not tb.date and tb.revisions:
        tb.date = tb.revisions[-1].date


def flowsheet(stem: str) -> "tuple[Flowsheet, dict]":
    """The flowsheet *stem*'s example builds, and the options it draws it with.

    The example is imported rather than executed as a subprocess, with
    ``Flowsheet.render`` replaced for the duration so the call at the end of it
    hands over the flowsheet and its keyword arguments instead of writing a
    file. ``01`` renders at import and the rest behind ``main()``; both shapes
    end in that same call, so both are caught the same way.

    Separate from :func:`render` so a caller that wants the *model* the example
    builds -- and not the sheet it draws -- has one, without a second copy of
    the capture. ``tests/test_drawio.py`` is that caller: a draw.io export is
    made from a flowsheet and has no SVG anywhere in it.

    A ``.drawio`` write is passed over rather than caught. ``03`` and ``11``
    write one beside their SVG, because the export is a one-liner and an example
    is where a reader looks for one; what those calls write is the *same drawing
    in a second format*, not a second sheet. Caught, they would trip the count
    below on files that draw exactly one.
    """
    caught: list[tuple[Flowsheet, dict]] = []
    original = Flowsheet.render

    def capture(self, path, **kwargs):
        if pathlib.Path(path).suffix.lower() != ".drawio":
            caught.append((self, kwargs))

    sys.path.insert(0, str(EXAMPLES))  # the examples' own _bootstrap
    Flowsheet.render = capture  # type: ignore[method-assign]
    try:
        spec = importlib.util.spec_from_file_location(f"_gallery_{stem}", EXAMPLES / f"{stem}.py")
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
    """The SVG *stem*'s example draws, canonicalised, without running its output."""
    fs, kwargs = flowsheet(stem)
    return normalize(fs.to_svg(**kwargs))


def normalize(svg: str) -> str:
    """Canonicalise the ``<defs>`` ordering, which is not the diagram's.

    ``SvgRenderer._defs()`` builds its markers and symbols from ``set``s, so
    their order depends on the process's string-hash seed and on nothing about
    the drawing. Sorting them here is what lets a committed sheet be compared
    against a fresh render byte for byte. This is the rule
    ``tests/test_golden.py`` applies to the golden fixtures, for the same
    reason and with the same effect on everything else: none.
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
    """*svg* as a PNG *width* device pixels across.

    ``export.to_png`` takes a scale in pixels per PDF point, and the page is as
    many points across as the sheet's own physical size -- which is 420 mm for
    the two A3 examples and the drawing's own extent for the rest. The backend
    is asked what it made rather than told, so a sheet's declared size and the
    conversion to points stay the export module's business.
    """
    import pypdfium2

    page_pt = pypdfium2.PdfDocument(export.to_pdf(svg))[0].get_width()
    return export.to_png(svg, scale=width / page_pt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
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
