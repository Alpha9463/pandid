"""PDF/PNG export: the flattening that stands between the SVG and the backend.

The backend does not implement `<use>` of a `<symbol>`, `marker-end` or
`dominant-baseline`, and drops all three without saying so, which draws every
unit at the wrong size, loses every flow arrow, and sets every vertically
centred label a quarter of its type size clear of the halo it is centred on.
`pandid.render.export.flatten` resolves them into plain geometry and plain
coordinates first. These tests hold that resolution to the SVG viewport and
alignment rules, and hold the renderer to emitting nothing else the backend
would quietly discard.
"""

import base64
import importlib.util
import io
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


# --- how a string sets --------------------------------------------------------

# Half the ascent/descent box of Helvetica, the face svglib resolves pandid's
# font-family="sans-serif" onto: how far below a centred point that string's
# alphabetic baseline belongs, per unit of font size. Written out rather than
# imported from the module under test, so the arithmetic is stated twice.
_MIDDLE = (0.718 - 0.207) / 2


def _label(baseline: str, size: str = "12") -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<text x="50" y="50" font-family="sans-serif" font-size="{size}" '
        f'text-anchor="middle" dominant-baseline="{baseline}">S1</text></svg>'
    )


def _text_y(flat: str) -> float:
    return float(re.search(r'<text[^>]*\by="(-?[\d.]+)"', flat).group(1))


@pytest.mark.parametrize("size", ["12", "10"])
def test_a_vertically_centred_label_is_handed_the_baseline_it_meant(size):
    # The renderer centres a stream number, a balloon tag and most equipment
    # labels on the point it struck the white halo round. The backend maps
    # text-anchor and nothing else about alignment, so left alone it puts the
    # *baseline* on that point and the lettering ends up clear of its own halo.
    # The alphabetic baseline belongs half the ascent/descent box lower, and the
    # shift is a fraction of the size the string is set in, not a constant.
    flat = export.flatten(_label("middle", size))
    assert "dominant-baseline" not in flat
    assert _text_y(flat) == pytest.approx(50 + _MIDDLE * float(size))


@pytest.mark.parametrize("baseline", ["baseline", "auto", "alphabetic"])
def test_a_label_already_set_on_its_baseline_does_not_move(baseline):
    # What pandid writes above a unit, where the y it computed is a baseline
    # already. "baseline" is not one of the SVG keywords and a browser reads it
    # as "auto"; all three have to come out of here as the same drawing, and as
    # a drawing identical to the one with no attribute at all.
    flat = export.flatten(_label(baseline))
    assert "dominant-baseline" not in flat
    assert _text_y(flat) == pytest.approx(50)


def test_a_baseline_the_backend_cannot_place_is_refused_rather_than_drawn_wrong():
    # `hanging` is the value a renderer is next likeliest to reach for, and a
    # browser reads it out of the font's own baseline table, which ReportLab's
    # base-14 metrics do not carry. Guessing it would put the text somewhere
    # near right and say nothing, which is the failure this module exists to
    # turn into a loud one.
    with pytest.raises(RuntimeError) as excinfo:
        export.flatten(_label("hanging"))
    assert "hanging" in str(excinfo.value)


def test_a_baseline_inherited_from_an_ancestor_is_refused_too():
    # dominant-baseline inherits, so a <g> carrying one moves every string
    # below it. Nothing here resolves that, and the backend would not either.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g dominant-baseline="middle"><text x="50" y="50" font-size="12">S1</text></g></svg>'
    )
    with pytest.raises(RuntimeError) as excinfo:
        export.flatten(svg)
    assert "dominant-baseline" in str(excinfo.value)


def test_a_symbol_shifts_its_own_lettering_by_its_own_size():
    # The shift is applied after the <use> expansion and in the symbol's units,
    # so the placement scales it with everything else it scales. Applied in the
    # sheet's units instead, a symbol drawn at four times its definition would
    # have its lettering nudged a quarter as far as its own artwork moved.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><symbol id="s" viewBox="0 0 10 10" preserveAspectRatio="none">'
        '<text x="5" y="5" font-family="sans-serif" font-size="4" '
        'dominant-baseline="middle">M</text></symbol></defs>'
        '<use href="#s" x="0" y="0" width="40" height="40" />'
        "</svg>"
    )
    flat = export.flatten(svg)
    assert _text_y(flat) == pytest.approx(5 + _MIDDLE * 4)
    assert _matrix(re.search(r'<g transform="([^"]*)"', flat).group(1))[3] == pytest.approx(4)


# --- and how big it is set ----------------------------------------------------

# Every distinct font-size the renderer puts on a sheet, read off the goldens
# rather than listed here: the sizes are spread over svg.py and furniture.py and
# a new one arrives whenever a new sheet element does, so a list would be a list
# that goes stale. Today it is ten of them, 6.5 through 18.
_SIZES = sorted(
    {
        float(s)
        for name in GOLDENS
        for s in re.findall(
            r'font-size="([\d.]+)"', (GOLDEN_DIR / name).read_text(encoding="utf-8")
        )
    }
)

# Helvetica's cap height, the fraction of the font size a capital with no
# descender measures from its baseline. Written out rather than imported, so the
# number the drawing is held to is stated independently of the drawing.
_CAP_HEIGHT = 0.718


def _rule_and_capitals(size: float) -> str:
    """A capital at *size*, twice, beside a rule declared exactly *size* long."""
    s = size
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{4.5 * s:g}" height="{2.5 * s:g}" '
        f'viewBox="0 0 {4.5 * s:g} {2.5 * s:g}">'
        f'<rect x="0" y="0" width="{4.5 * s:g}" height="{2.5 * s:g}" fill="white" />'
        f'<rect x="{0.25 * s:g}" y="{s:g}" width="{0.5 * s:g}" height="{s:g}" />'
        f'<text x="{1.5 * s:g}" y="{2 * s:g}" font-family="sans-serif" font-size="{s:g}">H</text>'
        f'<text x="{3 * s:g}" y="{2 * s:g}" font-family="sans-serif" font-size="{s:g}" '
        f'font-weight="bold">H</text>'
        "</svg>"
    )


def _ink_height(im, px: float, x0: float, x1: float) -> float:
    """The height of the ink between *x0* and *x1*, back in user units."""
    band = im.crop((round(x0 * px), 0, round(x1 * px), im.height))
    box = band.point(lambda v: 255 if v < 128 else 0).getbbox()
    assert box, "nothing was drawn in this band"
    return (box[3] - box[1]) / px


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
@pytest.mark.parametrize("size", _SIZES)
def test_lettering_is_drawn_at_the_size_the_file_asks_for(size):
    # The backend converts font-size from px to pt and then scales the drawing
    # the string sits in from px to pt as well, so the size took the 0.75 twice
    # and the geometry beside it took it once: every label on every exported
    # sheet came out at three quarters, measurably and only in the PDF and PNG.
    # A cap height is what makes that checkable without a golden image. The face
    # declares one as a fraction of the font size, so a capital and a rule of the
    # same declared length in the same document must draw in that ratio, whatever
    # the page size, the raster scale or the units in between -- and the rule is
    # measured too, because a fix that moved both would satisfy neither.
    from PIL import Image

    # Rasterised so a capital is about 170 device px tall whatever size it is set
    # at, which reads its ink box to well inside a percent even for the 6.5 the
    # title block's rows are set in.
    im = Image.open(io.BytesIO(export.to_png(_rule_and_capitals(size), scale=320 / size)))
    im = im.convert("L")
    px = im.width / (4.5 * size)

    rule = _ink_height(im, px, 0, 1.25 * size)
    assert rule == pytest.approx(size, rel=0.01), f"the {size:g} rule drew {rule:.3f}"
    for x0, x1, weight in ((1.25, 2.75, "regular"), (2.75, 4.5, "bold")):
        cap = _ink_height(im, px, x0 * size, x1 * size)
        assert cap / size == pytest.approx(_CAP_HEIGHT, abs=0.02), (
            f"a {weight} capital set in {size:g} drew a cap height of {cap:.3f}, "
            f"{cap / size:.3f} of its size against the {_CAP_HEIGHT} the face declares"
        )


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_the_written_out_metrics_are_the_ones_the_backend_will_draw_with():
    # export.py carries Helvetica's numbers so that flatten() answers the same
    # on a machine with no pdf extra to ask. This is what keeps the two agreeing.
    from reportlab.pdfbase import pdfmetrics

    for bold, face in export._FACES.items():
        assert pdfmetrics.getAscentDescent(face, 1.0) == pytest.approx(export._HELVETICA_EM), bold


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


_HALOED = re.compile(
    r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" />\s*'
    r'<text x="[\d.]+" y="[\d.]+"[^>]*font-size="([\d.]+)"[^>]*'
    r'dominant-baseline="middle"[^>]*>([^<]+)</text>'
)


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_a_centred_label_is_rasterised_where_its_alignment_puts_it_in_its_halo():
    # Measured rather than eyeballed, and measured on the pixels, so it covers
    # the whole path down to the raster instead of one rewrite in the middle of
    # it. The renderer strikes the halo and sets the text from a single centre,
    # and dropping the alignment put this lettering 2.7 px high in a 13 px halo,
    # half the height of the ink itself.
    #
    # Where it belongs is a stated distance from the middle rather than the middle:
    # `middle` puts the alphabetic baseline half the ascent/descent box below the
    # centre, and an all-capitals string's ink reaches a cap height above that
    # baseline, so the ink box sits about 0.10 em high of centre and is meant to.
    # That is what a browser draws as well. While the backend set every string at
    # three quarters of its size those 0.10 em were 0.10 em of nine-tenths of
    # nothing, and asking only for ink within 1.5 px of the halo's middle passed
    # on the accident; the same labels at true size are 1.0 to 1.2 px high of it.
    # So this states the offset instead of hoping it is zero, which holds the
    # alignment and the type size at once and to half a pixel rather than three.
    from PIL import Image

    # The sheet with the most stream numbers on it, and they are capitals and
    # figures throughout: no descender to pull the ink box down off the letters.
    svg = (GOLDEN_DIR / "03_distillation_train.svg").read_text(encoding="utf-8")
    vx, vy, vw, _ = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
    # Two device pixels per user unit, so an ink box reads to a quarter of one and
    # the tolerance below is a statement about the drawing, not about the raster.
    im = Image.open(io.BytesIO(export.to_png(svg, scale=2 * export._PX_PER_PT))).convert("L")
    px = im.width / vw

    measured = 0
    for rx, ry, rw, rh, size, text in _HALOED.findall(svg):
        rx, ry, rw, rh, size = (float(v) for v in (rx, ry, rw, rh, size))
        if rh > rw:  # a number turned to run up a vertical line
            continue
        top, bottom = (ry - vy) * px, (ry + rh - vy) * px
        # Inside the halo, so the strokes it was struck over cannot be read as
        # this label's ink, and thresholded so antialiasing is not either.
        box = (int((rx - vx) * px) + 1, int(top) + 1, int((rx + rw - vx) * px), int(bottom))
        ink = im.crop(box).point(lambda v: 255 if v < 128 else 0).getbbox()
        assert ink, f"{text!r} drew no ink inside its own halo"
        off = (box[1] + (ink[1] + ink[3]) / 2 - (top + bottom) / 2) / px
        want = (_MIDDLE - _CAP_HEIGHT / 2) * size
        assert abs(off - want) < 0.5, (
            f"{text!r} sits {off:+.2f} px off the middle of its halo, where its "
            f"{size:g} type and the alignment it was given put it {want:+.2f}"
        )
        measured += 1
    assert measured >= 4, "no haloed label was measured, so this checked nothing"


def _strings_on_the_paper(svg: str) -> int:
    """How many strings the sheet asks a renderer to draw.

    Not the number of ``<text>`` elements, which is what this counted until a
    sheet drew a *lettered symbol* twice. The S inside a solenoid valve's box is
    part of the artwork: ``SvgRenderer`` defines that artwork once under
    ``<defs>`` and instantiates it with a ``<use>`` per valve, so one element in
    the file is two strings on the paper. ``14_tank_farm`` has two solenoid
    valves -- a receipt trip valve on each of its two atmospheric tanks -- and
    is the first sheet in the corpus where the two numbers part company.

    So a symbol's lettering counts once per reference to it and everything
    outside a symbol counts once, which is what a PDF's ``Tj`` operators are a
    count of. Counting elements instead would have let a symbol's letter go
    missing on its second and every later instance without failing anything.
    """
    text = r"<text\b[^>]*>(.*?)</text>"
    total = 0
    for match in re.finditer(r'<symbol id="([^"]+)".*?</symbol>', svg, re.S):
        lettering = len([t for t in re.findall(text, match.group(0), re.S) if t.strip()])
        if lettering:
            total += lettering * len(re.findall(rf'href="#{re.escape(match.group(1))}"', svg))
    body = re.sub(r"<symbol\b.*?</symbol>", "", svg, flags=re.S)
    return total + len([t for t in re.findall(text, body, re.S) if t.strip()])


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
@pytest.mark.parametrize("name", GOLDENS)
def test_every_label_on_the_sheet_reaches_the_page(name):
    # The failure mode this whole module guards against is the silent drop, and
    # a tag that does not print is the most expensive one: on a P&ID the
    # lettering is the content. Counted rather than eyeballed, per sheet.
    svg = (GOLDEN_DIR / name).read_text(encoding="utf-8")
    drawn = len(re.findall(rb"\) Tj", _page_content(export.to_pdf(svg))))
    assert drawn == _strings_on_the_paper(svg)
