"""render() contract: to_svg() returns a string; render(path) writes the file
whose format is inferred from the extension and returns None."""

import re
import sys
import zlib

import pytest

from pfd import Flowsheet, units as U

# ISO 216 landscape in millimetres, and the same sheets in the px the drawing is
# laid out in. Restated here rather than imported so a silent edit to the
# renderer's own table cannot make these assertions vacuous.
PX_PER_MM = 96.0 / 25.4
A4_MM = (297.0, 210.0)
A3_MM = (420.0, 297.0)
A0_MM = (1189.0, 841.0)
A4 = (A4_MM[0] * PX_PER_MM, A4_MM[1] * PX_PER_MM)
A3 = (A3_MM[0] * PX_PER_MM, A3_MM[1] * PX_PER_MM)
A0 = (A0_MM[0] * PX_PER_MM, A0_MM[1] * PX_PER_MM)

_CANVAS = re.compile(
    r'width="([\d.]+)(mm)?" height="([\d.]+)(mm)?" '
    r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"'
)
_FIT = re.compile(
    r'<g id="drawing" transform="translate\(([-\d.]+), ([-\d.]+)\) scale\(([\d.e+-]+)\)"'
)
# A zone letter/number ruled in the border band (furniture.zone_frame).
_ZONE = re.compile(r'font-size="9.0" text-anchor="middle" font-weight="bold" fill="black">(\w+)<')


def _fs():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    return fs


def _spanning(width: float) -> Flowsheet:
    """A feed and a product pinned *width* apart — a drawing of a chosen size."""
    fs = Flowsheet("span")
    feed = fs.add(U.Feed("F")).pin(x=0, y=0)
    prod = fs.add(U.Product("P")).pin(x=width, y=0)
    fs.connect(feed.outlet, prod.inlet)
    return fs


def _canvas(svg: str) -> tuple[float, float]:
    """The sheet's px canvas, cross-checked against the size ``<svg>`` declares."""
    m = _CANVAS.search(svg)
    assert m, "no canvas on the <svg> element"
    view = float(m.group(7)), float(m.group(8))
    declared = float(m.group(1)), float(m.group(3))
    if m.group(2):  # a physical size: it must describe the same sheet
        assert (declared[0] * PX_PER_MM, declared[1] * PX_PER_MM) == pytest.approx(view, abs=0.1)
    else:
        assert declared == (round(view[0]), round(view[1]))
    return view


def _sheet_mm(svg: str) -> "tuple[float, float] | None":
    """The physical size the sheet declares, in mm; ``None`` if it declares none."""
    m = _CANVAS.search(svg)
    assert m, "no canvas on the <svg> element"
    if not m.group(2):
        return None
    return float(m.group(1)), float(m.group(3))


def _pdf_page_pt(pdf: bytes) -> tuple[float, float]:
    """The page size a PDF declares, in points, from its first ``/MediaBox``.

    cairosvg writes the page object into a compressed object stream, so the box
    has to be inflated out of one rather than read from the file directly.
    """
    bodies = [pdf]
    for m in re.finditer(rb"/Type\s*/ObjStm.*?stream\r?\n", pdf, re.S):
        chunk = pdf[m.end() :]
        try:
            bodies.append(zlib.decompress(chunk[: chunk.find(b"\nendstream")]))
        except zlib.error:  # not the stream we are after
            continue
    for body in bodies:
        box = re.search(rb"/MediaBox\s*\[([^\]]*)\]", body)
        if box:
            _, _, width, height = (float(v) for v in box.group(1).split())
            return width, height
    raise AssertionError("no /MediaBox in the exported PDF")


def _fit(svg: str) -> tuple[float, float, float]:
    """The fitted drawing group's ``(tx, ty, scale)``."""
    m = _FIT.search(svg)
    assert m, "no fitted drawing group"
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def _drawing_bbox(fs: Flowsheet) -> tuple[float, float, float, float]:
    from pfd.portgeom import unit_box

    xs: list[float] = []
    ys: list[float] = []
    for u in fs.units:
        x0, y0, x1, y1 = unit_box(u, u.frame)
        xs += [x0, x1]
        ys += [y0, y1]
    for s in fs.streams:
        for px, py in s.route.waypoints if s.route else []:
            xs.append(px)
            ys.append(py)
    return min(xs), min(ys), max(xs), max(ys)


def test_to_svg_returns_a_string():
    svg = _fs().to_svg()
    assert isinstance(svg, str)
    assert "<svg" in svg


def test_render_svg_writes_file_and_returns_none(tmp_path):
    out = tmp_path / "d.svg"
    result = _fs().render(str(out))
    assert result is None
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_pdf_hint_names_the_distribution_on_pypi(tmp_path, monkeypatch):
    # `pfd` on PyPI is an unrelated project; the distribution is `pandid`.
    monkeypatch.setitem(sys.modules, "cairosvg", None)  # makes `import cairosvg` fail
    with pytest.raises(ImportError) as excinfo:
        _fs().render(str(tmp_path / "d.pdf"))
    message = str(excinfo.value)
    assert "cairosvg" in message
    assert "pip install 'pandid[pdf]'" in message


def test_jump_direction_reaches_the_public_api():
    from pfd.render.svg import SvgRenderer

    # Two lines that cross: which of them bulges is what the option chooses.
    def build():
        fs = Flowsheet("jump")
        f1 = fs.add(U.Feed("F1")).pin(x=60, y=175)
        p1 = fs.add(U.Product("P1")).pin(x=600, y=175)
        f2 = fs.add(U.Feed("F2")).pin(x=60, y=375)
        p2 = fs.add(U.Product("P2")).pin(x=600, y=375)
        fs.connect(f1.outlet, p1.inlet)
        fs.connect(f2.outlet, p2.inlet).via([(300, 400), (300, 100), (400, 100), (400, 400)])
        return fs

    default = build().to_svg()
    assert build().to_svg(jump_direction="vertical") == default
    horizontal = build().to_svg(jump_direction="horizontal")
    assert horizontal != default
    assert default.count("A 5 5") == horizontal.count("A 5 5") == 2

    # ... and it means the same thing it means on the renderer itself.
    fs = build()
    fs.layout()
    fs.route()
    fs.renumber_streams()
    assert SvgRenderer().render(fs, jump_direction="horizontal") == horizontal


def test_render_unknown_extension_raises_valueerror(tmp_path):
    with pytest.raises(ValueError):
        _fs().render(str(tmp_path / "d.bmp"))


def test_canvas_fits_content_and_is_not_padded_to_page_size():
    # A two-box diagram must frame tightly, not float in a full A3 sheet
    # (1587x1122).
    svg = _fs().to_svg()
    w, h = _canvas(svg)  # width/height in px equal the viewBox → no letterbox
    assert w < 800 and h < 500


# --- page_size: a named sheet is drawn at exactly that size --------------------


@pytest.mark.parametrize("name,mm", [("A4", A4_MM), ("A3", A3_MM), ("A0", A0_MM)])
@pytest.mark.parametrize("styling", ["default", "pid"])
def test_page_size_draws_a_sheet_of_exactly_that_size(name, mm, styling):
    svg = _fs().to_svg(page_size=name, styling=styling)
    assert _sheet_mm(svg) == mm


def test_a_furnished_page_is_that_size_with_or_without_a_border():
    # The border is ink, not layout: a title strip rules to the same place on a
    # fixed page whether or not the frame around it is drawn.
    from pfd.document import TitleBlock

    def build():
        fs = _spanning(600.0)
        fs.title_block = TitleBlock(drawing_number="PFD-1")
        return fs

    assert _sheet_mm(build().to_svg(page_size="A3", border="zone")) == A3_MM
    assert _sheet_mm(build().to_svg(page_size="A3", border="none")) == A3_MM
    assert _fit(build().to_svg(page_size="A3", border="none")) == _fit(
        build().to_svg(page_size="A3", border="zone")
    )


def test_page_sizes_differ_from_one_another():
    sheets = {n: _sheet_mm(_fs().to_svg(page_size=n)) for n in ("A4", "A3", "A2", "A1", "A0")}
    assert len(set(sheets.values())) == len(sheets)


def test_page_size_is_case_insensitive():
    assert _sheet_mm(_fs().to_svg(page_size="a3")) == A3_MM


def test_omitting_page_size_fits_the_sheet_to_the_drawing():
    fitted = _fs().to_svg()
    assert fitted == _fs().to_svg(page_size=None)
    assert _canvas(fitted) != A3
    # No paper was asked for, so the sheet claims no physical size either.
    assert _sheet_mm(fitted) is None
    assert '<g id="drawing"' not in fitted  # nothing to fit into, so nothing wraps it


def test_unknown_page_size_names_the_ones_that_work():
    with pytest.raises(ValueError) as excinfo:
        _fs().to_svg(page_size="A9")
    message = str(excinfo.value)
    assert "A9" in message
    assert "A3" in message and "A0" in message


def test_zone_grid_is_fixed_by_the_page_not_by_the_drawing():
    # A note reading "valve in D-4" must still point at D-4 after the next
    # revision adds an exchanger; a fitted sheet renumbers its zones instead.
    on_page = [
        sorted(set(_ZONE.findall(_spanning(w).to_svg(page_size="A3", styling="pid"))))
        for w in (300.0, 900.0, 1500.0)
    ]
    assert on_page[0] == on_page[1] == on_page[2]
    fitted = [
        sorted(set(_ZONE.findall(_spanning(w).to_svg(styling="pid"))))
        for w in (300.0, 900.0, 1500.0)
    ]
    assert len(set(map(tuple, fitted))) == 3


def test_pid_furniture_rules_to_the_sheet_edges():
    from pfd.document import TitleBlock
    from pfd.render.furniture import ZONE_BAND, measure_title_strip

    fs = _spanning(600.0)
    fs.title_block = TitleBlock(drawing_number="PFD-1")
    svg = fs.to_svg(page_size="A3", styling="pid")
    # the sheet border sits a hair inside the page, the drawing frame a band in
    frame = re.search(
        r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" '
        r'fill="none" stroke="black" stroke-width="2"/>',
        svg,
    )
    fx, fy, fw, fh = (float(g) for g in frame.groups())
    assert fx == fy and fx < ZONE_BAND + 12
    # Coordinates are written to one decimal, so allow half of that last place.
    assert (fx + fw, fy + fh) == pytest.approx((A3[0] - fx, A3[1] - fy), abs=0.05)
    # the title strip is docked into the frame's bottom-right corner
    sw, sh = measure_title_strip(fs.title_block)
    strip = re.search(
        rf'<rect x="([-\d.]+)" y="([-\d.]+)" width="{sw:.1f}" height="{sh:.1f}" '
        r'fill="white" stroke="black" stroke-width="2"/>',
        svg,
    )
    assert strip, "title strip not found"
    assert (float(strip.group(1)) + sw, float(strip.group(2)) + sh) == pytest.approx(
        (fx + fw, fy + fh)
    )


def test_an_oversized_drawing_is_scaled_onto_the_sheet_not_clipped():
    fs = _spanning(4000.0)
    svg = fs.to_svg(page_size="A4", styling="pid")
    tx, ty, scale = _fit(svg)
    assert scale < 1
    x0, y0, x1, y1 = _drawing_bbox(fs)
    assert 0 <= x0 * scale + tx and x1 * scale + tx <= A4[0]
    assert 0 <= y0 * scale + ty and y1 * scale + ty <= A4[1]


def test_a_drawing_that_already_fits_is_never_blown_up():
    # Line weights and lettering are sheet-fixed; a small drawing keeps its size
    # and leaves the rest of the page white.
    _, _, scale = _fit(_spanning(300.0).to_svg(page_size="A0", styling="pid"))
    assert scale == 1


def test_page_too_small_for_its_own_furniture_raises():
    from pfd.document import TableBox

    fs = _spanning(300.0)
    fs.add_annotation(TableBox(title="SCHEDULE", headers=["Tag"] * 40, rows=[["x"] * 40]))
    with pytest.raises(ValueError) as excinfo:
        fs.to_svg(page_size="A4", styling="pid")
    message = str(excinfo.value)
    assert "A4" in message
    assert "page_size" in message  # and how to get out of it


def test_page_size_reaches_render_as_well_as_to_svg(tmp_path):
    out = tmp_path / "sheet.svg"
    _fs().render(str(out), page_size="A4")
    assert _sheet_mm(out.read_text(encoding="utf-8")) == A4_MM


@pytest.mark.parametrize("name,mm", [("A4", A4_MM), ("A3", A3_MM), ("A0", A0_MM)])
def test_exported_pdf_lands_on_a_page_of_exactly_that_size(tmp_path, name, mm):
    # The end of the line for page_size: what a printer is handed. A sheet that
    # is A3 only if the reader happens to call a user unit 1/96 inch is not A3.
    pytest.importorskip("cairosvg")
    out = tmp_path / "sheet.pdf"
    _fs().render(str(out), page_size=name, styling="pid")
    width_pt, height_pt = _pdf_page_pt(out.read_bytes())
    assert (width_pt / 72 * 25.4, height_pt / 72 * 25.4) == pytest.approx(mm, abs=0.01)
