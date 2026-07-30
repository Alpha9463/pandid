"""PDF/PNG export: the flattening that stands between the SVG and the backend.

The backend does not implement `<use>` of a `<symbol>` or `marker-end`, and
drops both without saying so, which draws every unit at the wrong size and
loses every flow arrow. `pandid.render.export.flatten` resolves them into plain
geometry first. These tests hold that resolution to the SVG viewport rules, and
hold the renderer to emitting nothing else the backend would quietly discard.
"""

import base64
import importlib.util
import math
import re
import zlib
from pathlib import Path

import pytest

from pandid import Flowsheet, units as U
from pandid.render import export

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDENS = sorted(p.name for p in GOLDEN_DIR.glob("*.svg"))

# The whole extra, not one member of it: a PNG is rasterised from the PDF, so it
# needs everything the PDF needs and pypdfium2 besides. Skipping on pypdfium2
# alone would let a machine with the rasteriser and not the writer fail here.
_HAS_PDF_EXTRA = all(
    importlib.util.find_spec(m) is not None for m in ("svglib", "reportlab", "pypdfium2", "PIL")
)

_OP = re.compile(r"(translate|scale|rotate)\(([^)]*)\)")


def _matrix(transform: str) -> tuple[float, float, float, float, float, float]:
    """A transform list as a single (a, b, c, d, e, f) matrix.

    Composed left to right the way SVG does, so this test measures the order the
    operations were written in as well as the numbers in them.
    """
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, raw in _OP.findall(transform):
        v = [float(n) for n in raw.replace(",", " ").split()]
        if name == "translate":
            other = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            other = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        else:
            r = math.radians(v[0])
            cos, sin = math.cos(r), math.sin(r)
            other = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(v) == 3:  # rotate about a point
                cx, cy = v[1], v[2]
                other = (
                    cos,
                    sin,
                    -sin,
                    cos,
                    cx - cos * cx + sin * cy,
                    cy - sin * cx - cos * cy,
                )
        a, b, c, d, e, f = m
        oa, ob, oc, od, oe, of = other
        m = (
            a * oa + c * ob,
            b * oa + d * ob,
            a * oc + c * od,
            b * oc + d * od,
            a * oe + c * of + e,
            b * oe + d * of + f,
        )
    return m


def _apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _page_content(pdf: bytes) -> bytes:
    """The first page's content stream, decoded: the drawing itself."""
    m = re.search(rb"stream\r?\n", pdf)
    assert m, "the PDF has no stream to read"
    body = pdf[m.end() : pdf.find(b"endstream", m.end())].strip()
    return zlib.decompress(base64.a85decode(body, adobe=True))


def _fs():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    return fs


# --- the flattening itself ----------------------------------------------------


@pytest.mark.parametrize("name", GOLDENS)
def test_every_golden_sheet_flattens_to_something_the_backend_can_draw(name):
    # The watchdog on the coupling: the goldens are the whole rendered feature
    # range, and flatten() refuses anything it would otherwise hand over to be
    # silently dropped. A renderer that grows a clip path fails here, on every
    # machine, whether or not the pdf extra is installed.
    flat = export.flatten((GOLDEN_DIR / name).read_text(encoding="utf-8"))
    for gone in ("<use", "<symbol", "<marker", "marker-end", "<defs"):
        assert gone not in flat, f"{gone} survived flattening of {name}"


def test_a_stretched_symbol_lands_on_exactly_the_box_the_use_asked_for():
    # The bug this whole module exists for: the backend drew the symbol at its
    # viewBox size and ignored the box, so equipment came out undersized and its
    # process lines stopped short of the nozzles.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<defs><symbol id="s" viewBox="0 0 10 20" preserveAspectRatio="none">'
        '<rect x="0" y="0" width="10" height="20"/></symbol></defs>'
        '<use href="#s" x="30" y="40" width="50" height="60" />'
        "</svg>"
    )
    m = _matrix(re.search(r'<g transform="([^"]*)"', export.flatten(svg)).group(1))
    assert _apply(m, 0, 0) == pytest.approx((30, 40))
    assert _apply(m, 10, 20) == pytest.approx((80, 100))


def test_a_symbol_that_keeps_its_aspect_is_centred_in_its_box():
    # xMidYMid meet, which is what a symbol without preserveAspectRatio="none"
    # asks for: an instrument balloon is a circle because ISA-5.1 says so, and
    # it is centred in a box of another shape rather than squashed to fill it.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<defs><symbol id="s" viewBox="0 0 10 10">'
        '<rect x="0" y="0" width="10" height="10"/></symbol></defs>'
        '<use href="#s" x="0" y="0" width="40" height="20" />'
        "</svg>"
    )
    m = _matrix(re.search(r'<g transform="([^"]*)"', export.flatten(svg)).group(1))
    # Scale 2 (the smaller of 4 and 2), so 20 wide inside a 40-wide box, with
    # the 20 left over split evenly down the two sides.
    assert _apply(m, 0, 0) == pytest.approx((10, 0))
    assert _apply(m, 10, 10) == pytest.approx((30, 20))


def test_the_reference_transform_is_applied_outside_the_placement():
    # rotate() on the <use> turns the placed box; applying it inside the
    # placement instead would turn the artwork within a box that stayed put.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<defs><symbol id="s" viewBox="0 0 10 10" preserveAspectRatio="none">'
        '<rect x="0" y="0" width="10" height="10"/></symbol></defs>'
        '<use href="#s" x="0" y="0" width="10" height="10" '
        'transform="rotate(90, 0, 0)" />'
        "</svg>"
    )
    m = _matrix(re.search(r'<g transform="([^"]*)"', export.flatten(svg)).group(1))
    assert _apply(m, 10, 0) == pytest.approx((0, 10))


def test_an_end_marker_is_drawn_at_the_end_of_its_own_line():
    # A PFD's arrowheads are marker-end, and the backend ignores the attribute.
    # Losing them loses the flow direction, which is most of what a PFD says.
    flat = export.flatten(_fs().to_svg())
    heads = re.findall(r'<g transform="translate\(([-\d.]+), ([-\d.]+)\) rotate', flat)
    ends = {
        (round(float(m.group(1))), round(float(m.group(2))))
        for m in re.finditer(r'<path d="[^"]*L ([-\d.]+),([-\d.]+)" fill="none"', flat)
    }
    assert heads, "no arrowhead was drawn"
    for hx, hy in heads:
        assert (round(float(hx)), round(float(hy))) in ends


def test_a_construct_the_backend_cannot_draw_is_refused_rather_than_dropped():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect x="0" y="0" width="10" height="10" clip-path="url(#c)"/></svg>'
    )
    with pytest.raises(RuntimeError) as excinfo:
        export.flatten(svg)
    assert "clip-path" in str(excinfo.value)


# --- the files that come out --------------------------------------------------


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_render_writes_a_pdf(tmp_path):
    out = tmp_path / "d.pdf"
    _fs().render(str(out))
    assert out.read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_render_writes_a_png(tmp_path):
    out = tmp_path / "d.png"
    _fs().render(str(out))
    assert out.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_the_exported_pdf_draws_the_sheet_rather_than_a_picture_of_it(tmp_path):
    # A raster page would have been the easy way out of the cairo problem, and
    # would have cost every reader a drawing that stops resolving when zoomed.
    # One image XObject and no path operators is what that mistake looks like.
    out = tmp_path / "d.pdf"
    _fs().render(str(out), page_size="A4", border="zone")
    body = out.read_bytes()
    assert b"/Subtype /Image" not in body  # no page-sized picture of the drawing
    assert b"/BaseFont /Helvetica" in body  # and its lettering is still lettering
    assert b" l\n" in _page_content(body) or b" re\n" in _page_content(body)


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
@pytest.mark.parametrize("name", GOLDENS)
def test_every_label_on_the_sheet_reaches_the_page(name):
    # The failure mode this whole module guards against is the silent drop, and
    # a tag that does not print is the most expensive one: on a P&ID the
    # lettering is the content. Counted rather than eyeballed, per sheet.
    svg = (GOLDEN_DIR / name).read_text(encoding="utf-8")
    written = len([t for t in re.findall(r"<text\b[^>]*>(.*?)</text>", svg, re.S) if t.strip()])
    drawn = len(re.findall(rb"\) Tj", _page_content(export.to_pdf(svg))))
    assert drawn == written
