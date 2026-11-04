"""Check PDF/PNG export and the SVG flattening it draws from."""

import base64
import importlib.util
import io
import re
import zlib
from pathlib import Path

import pytest

from pandid import Flowsheet, units as U
from pandid.render import export
from test_symbol_invariants import _apply, _parse_transform as _matrix

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDENS = sorted(p.name for p in GOLDEN_DIR.glob("*.svg"))

# The whole pdf extra: a PNG is rasterised from the PDF.
_HAS_PDF_EXTRA = all(
    importlib.util.find_spec(m) is not None for m in ("svglib", "reportlab", "pypdfium2", "PIL")
)


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
    """Flatten each golden sheet to no ``<use>``, ``<symbol>``, marker or ``<defs>``."""
    flat = export.flatten((GOLDEN_DIR / name).read_text(encoding="utf-8"))
    for gone in ("<use", "<symbol", "<marker", "marker-end", "<defs"):
        assert gone not in flat, f"{gone} survived flattening of {name}"


@pytest.mark.parametrize(
    ("symbol", "use", "mapped"),
    [
        # preserveAspectRatio="none" stretches onto exactly the box.
        (
            'viewBox="0 0 10 20" preserveAspectRatio="none"',
            'x="30" y="40" width="50" height="60"',
            [((0, 0), (30, 40)), ((10, 20), (80, 100))],
        ),
        # xMidYMid meet: scale 2 (the smaller of 4 and 2), 20 wide, centred in the 40-wide box.
        (
            'viewBox="0 0 10 10"',
            'x="0" y="0" width="40" height="20"',
            [((0, 0), (10, 0)), ((10, 10), (30, 20))],
        ),
        # The use's own transform applies to the placed box, not inside it.
        (
            'viewBox="0 0 10 10" preserveAspectRatio="none"',
            'x="0" y="0" width="10" height="10" transform="rotate(90, 0, 0)"',
            [((10, 0), (0, 10))],
        ),
    ],
)
def test_a_use_places_its_symbol_on_the_box_it_asks_for(symbol, use, mapped):
    """Map a ``<use>``'s symbol onto its box as SVG places it."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        f'<defs><symbol id="s" {symbol}><rect x="0" y="0" width="10" height="10"/></symbol>'
        f'</defs><use href="#s" {use} /></svg>'
    )
    m = _matrix(re.search(r'<g transform="([^"]*)"', export.flatten(svg)).group(1))
    for (x, y), placed in mapped:
        assert _apply(m, x, y) == pytest.approx(placed)


def test_an_end_marker_is_drawn_at_the_end_of_its_own_line():
    """Draw each ``marker-end`` arrowhead at the end of its line."""
    flat = export.flatten(_fs().to_svg())
    heads = re.findall(r'<g transform="translate\(([-\d.]+), ([-\d.]+)\) rotate', flat)
    ends = {
        (round(float(m.group(1))), round(float(m.group(2))))
        for m in re.finditer(r'<path d="[^"]*L ([-\d.]+),([-\d.]+)" fill="none"', flat)
    }
    assert heads, "no arrowhead was drawn"
    for hx, hy in heads:
        assert (round(float(hx)), round(float(hy))) in ends


# --- how a string sets --------------------------------------------------------

# Half Helvetica's ascent/descent box: the baseline's drop below a centred point per unit size.
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
    """Move a ``dominant-baseline="middle"`` label to its alphabetic baseline."""
    flat = export.flatten(_label("middle", size))
    assert "dominant-baseline" not in flat
    assert _text_y(flat) == pytest.approx(50 + _MIDDLE * float(size))


@pytest.mark.parametrize("baseline", ["baseline", "auto", "alphabetic"])
def test_a_label_already_set_on_its_baseline_does_not_move(baseline):
    """Leave a label already set on its alphabetic baseline where it is."""
    flat = export.flatten(_label(baseline))
    assert "dominant-baseline" not in flat
    assert _text_y(flat) == pytest.approx(50)


@pytest.mark.parametrize(
    ("svg", "named"),
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect x="0" y="0" width="10" height="10" clip-path="url(#c)"/></svg>',
            "clip-path",
        ),
        # The backend's metrics cannot place a hanging baseline.
        (_label("hanging"), "hanging"),
        # Nor one set on an ancestor group.
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<g dominant-baseline="middle"><text x="50" y="50" font-size="12">S1</text></g></svg>',
            "dominant-baseline",
        ),
    ],
)
def test_what_the_backend_cannot_draw_is_refused_rather_than_drawn_wrong(svg, named):
    """Refuse a clip path or an unplaceable baseline, naming it."""
    with pytest.raises(RuntimeError) as excinfo:
        export.flatten(svg)
    assert named in str(excinfo.value)


def test_a_symbol_shifts_its_own_lettering_by_its_own_size():
    """Shift a symbol's centred lettering in the symbol's own units."""
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

# Every font size the golden sheets use.
_SIZES = sorted(
    {
        float(s)
        for name in GOLDENS
        for s in re.findall(
            r'font-size="([\d.]+)"', (GOLDEN_DIR / name).read_text(encoding="utf-8")
        )
    }
)

# Helvetica's cap height as a fraction of the font size.
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
    """Rasterise a rule and two capitals and check both draw at the declared size."""
    from PIL import Image

    # Scale so a capital is about 170 device px tall at any size.
    im = Image.open(io.BytesIO(export.to_png(_rule_and_capitals(size), scale=320 / size)))
    im = im.convert("L")
    px = im.width / (4.5 * size)

    rule = _ink_height(im, px, 0, 1.25 * size)
    assert rule == pytest.approx(size, rel=0.01), f"the {size:g} rule drew {rule:.3f}"
    for x0, x1, weight in ((1.25, 2.75, "regular"), (2.75, 4.5, "bold")):
        cap = _ink_height(im, px, x0 * size, x1 * size)
        assert cap / size == pytest.approx(_CAP_HEIGHT, abs=0.02), (
            f"a {weight} capital set in {size:g} drew a cap height of {cap:.3f}"
        )


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_the_written_out_metrics_are_the_ones_the_backend_will_draw_with():
    """Match export.py's Helvetica metrics to ReportLab's."""
    from reportlab.pdfbase import pdfmetrics

    for face in ("Helvetica", "Helvetica-Bold"):
        assert pdfmetrics.getAscentDescent(face, 1.0) == pytest.approx(export._HELVETICA_EM), face


# --- the files that come out --------------------------------------------------


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_render_writes_a_png(tmp_path):
    """Write a PNG for a ``.png`` path."""
    out = tmp_path / "d.png"
    _fs().render(str(out))
    assert out.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.skipif(not _HAS_PDF_EXTRA, reason="the pdf extra is not installed")
def test_the_exported_pdf_draws_the_sheet_rather_than_a_picture_of_it(tmp_path):
    """Export the PDF as vector paths and text, not an embedded image."""
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
    """Rasterise each haloed label with its ink offset from the halo's middle as stated."""
    from PIL import Image

    # Many stream numbers, all capitals and figures, so no descender moves the ink box.
    svg = (GOLDEN_DIR / "03_distillation_train.svg").read_text(encoding="utf-8")
    vx, vy, vw, _ = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
    # Two device pixels per user unit.
    im = Image.open(io.BytesIO(export.to_png(svg, scale=2 * export._PX_PER_PT))).convert("L")
    px = im.width / vw

    measured = 0
    for rx, ry, rw, rh, size, text in _HALOED.findall(svg):
        rx, ry, rw, rh, size = (float(v) for v in (rx, ry, rw, rh, size))
        top, bottom = (ry - vy) * px, (ry + rh - vy) * px
        # Crop inside the halo and threshold, so only this label's ink counts.
        box = (int((rx - vx) * px) + 1, int(top) + 1, int((rx + rw - vx) * px), int(bottom))
        ink = im.crop(box).point(lambda v: 255 if v < 128 else 0).getbbox()
        assert ink, f"{text!r} drew no ink inside its own halo"
        off = (box[1] + (ink[1] + ink[3]) / 2 - (top + bottom) / 2) / px
        want = (_MIDDLE - _CAP_HEIGHT / 2) * size
        assert abs(off - want) < 0.5, f"{text!r} sits {off:+.2f} px off, expected {want:+.2f}"
        measured += 1
    assert measured >= 4, "no haloed label was measured, so this checked nothing"


def _strings_on_the_paper(svg: str) -> int:
    """Count the strings a sheet draws, a symbol's lettering once per ``<use>`` of it."""
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
    """Draw one PDF ``Tj`` per string the golden sheet draws."""
    svg = (GOLDEN_DIR / name).read_text(encoding="utf-8")
    drawn = len(re.findall(rb"\) Tj", _page_content(export.to_pdf(svg))))
    assert drawn == _strings_on_the_paper(svg)
