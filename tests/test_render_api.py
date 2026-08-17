"""render() contract: to_svg() returns a string; render(path) writes the file
whose format is inferred from the extension and returns None."""

import re
import string
import sys
import zlib

import pytest

from pandid import Flowsheet, units as U

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
# The same label with the point it is centred on, for reading the grid's direction.
_ZONE_LABEL = re.compile(
    r'<text x="([-\d.]+)" y="([-\d.]+)" font-family="[^"]*" font-size="9.0" '
    r'text-anchor="middle" font-weight="bold" fill="black">(\w+)<'
)


def _fs():
    fs = Flowsheet("t")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    return fs


def _spanning(width: float) -> Flowsheet:
    """A feed and a product pinned *width* apart: a drawing of a chosen size."""
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

    A writer is free to put the page object inside a compressed object stream,
    so the box is looked for in the inflated streams as well as in the file
    itself rather than only where the current backend happens to put it.
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
    from pandid.portgeom import unit_box

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
    # `pandid` on PyPI is an unrelated project; the distribution is `pandid`.
    monkeypatch.setitem(sys.modules, "svglib.svglib", None)  # makes the import fail
    with pytest.raises(ImportError) as excinfo:
        _fs().render(str(tmp_path / "d.pdf"))
    message = str(excinfo.value)
    assert "svglib" in message
    assert "pip install 'pandid[pdf]'" in message


def test_png_hint_names_the_rasteriser_that_is_missing(tmp_path, monkeypatch):
    # Four packages carry the extra, so the hint has to say which one is absent
    # rather than send the reader to reinstall all of them and guess.
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(ImportError) as excinfo:
        _fs().render(str(tmp_path / "d.png"))
    message = str(excinfo.value)
    assert "pypdfium2" in message
    assert "pip install 'pandid[pdf]'" in message


def test_jump_direction_reaches_the_public_api():
    from pandid.render.svg import SvgRenderer

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


# --- diagram: a P&ID draws its process lines without arrowheads ----------------

# An arrowhead on a drawn line, and the marker definition it points at.
_ARROWHEAD = re.compile(r'\s*marker-end="url\(#arrow_[^"]*\)"')
_MARKER_DEF = re.compile(r'<marker id="arrow_.*?</marker>', re.S)


def _loop() -> Flowsheet:
    """Two process lines and the pneumatic signal that strokes their valve."""
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    fic = fs.add_instrument("FIC", 1, near=fv, at="N", offset=80)
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
    return fs


@pytest.mark.parametrize(
    "kwargs",
    [
        {"diagram": "p&id"},
        {"diagram": "pid"},  # the ampersand-less spelling
        {"diagram": "P&ID"},  # ...and the drawing's own name, as it is written
        # A P&ID on the engineering frame: the two options are independent, and
        # asking for both is still one drawing without arrowheads.
        {"border": "zone", "diagram": "p&id"},
    ],
)
def test_a_pid_draws_its_process_lines_without_arrowheads(kwargs):
    svg = _loop().to_svg(**kwargs)
    assert '<g id="streams">' in svg  # the lines are still drawn
    assert not _ARROWHEAD.search(svg)  # ...with nothing on the end of them
    assert not _MARKER_DEF.search(svg)  # ...and nothing left defining one


@pytest.mark.parametrize("kwargs", [{}, {"diagram": "pfd"}, {"border": "zone"}])
def test_a_sheet_that_is_not_a_pid_keeps_its_arrowheads(kwargs):
    # Including a PFD ruled with the engineering frame: the border is furniture
    # and says nothing about which drawing is on the sheet.
    svg = _loop().to_svg(**kwargs)
    assert len(_ARROWHEAD.findall(svg)) == 2  # one per process line
    assert _MARKER_DEF.search(svg)


def test_a_pid_takes_the_arrowheads_off_and_changes_nothing_else():
    # The signal lines never carried one and must not move, and neither must a
    # symbol, a balloon or a stream number.
    pfd = _loop().to_svg(diagram="pfd")
    pid = _loop().to_svg(diagram="p&id")
    stripped = _ARROWHEAD.sub("", _MARKER_DEF.sub("", pfd))
    assert " ".join(stripped.split()) == " ".join(pid.split())


def test_both_spellings_of_a_pid_mean_the_same_drawing():
    assert _loop().to_svg(diagram="p&id") == _loop().to_svg(diagram="pid")
    # ...and the drawing's own name, however an engineer capitalises it.
    assert _loop().to_svg(diagram="P&ID") == _loop().to_svg(diagram="pid")


def test_the_frame_and_the_drawing_are_asked_for_separately():
    """``border`` is sheet furniture and ``diagram`` is which drawing is on it.
    Neither implies the other, so the four combinations are four sheets."""
    sheets = {
        _loop().to_svg(border=b, diagram=d) for b in ("none", "zone") for d in ("pfd", "p&id")
    }
    assert len(sheets) == 4


def test_a_pid_reaches_render_as_well_as_to_svg(tmp_path):
    out = tmp_path / "sheet.svg"
    _loop().render(str(out), diagram="p&id")
    assert not _ARROWHEAD.search(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"diagram": "isometric"}, ["'p&id'", "'pid'", "'pfd'"]),
        ({"border": "isometric"}, ["none", "zone"]),
    ],
)
def test_a_drawing_the_renderer_cannot_draw_raises_naming_the_spellings(kwargs, expected):
    with pytest.raises(ValueError) as excinfo:
        _loop().to_svg(**kwargs)
    for token in expected:
        assert token in str(excinfo.value)


# --- page_size: a named sheet is drawn at exactly that size --------------------


@pytest.mark.parametrize("name,mm", [("A4", A4_MM), ("A3", A3_MM), ("A0", A0_MM)])
@pytest.mark.parametrize("sheet", [{}, {"border": "zone", "diagram": "p&id"}])
def test_page_size_draws_a_sheet_of_exactly_that_size(name, mm, sheet):
    svg = _fs().to_svg(page_size=name, **sheet)
    assert _sheet_mm(svg) == mm


def test_a_furnished_page_is_that_size_with_or_without_a_border():
    # The border is ink, not layout: a title strip rules to the same place on a
    # fixed page whether or not the frame around it is drawn.
    from pandid.document import TitleBlock

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
        sorted(
            set(_ZONE.findall(_spanning(w).to_svg(page_size="A3", border="zone", diagram="p&id")))
        )
        for w in (300.0, 900.0, 1500.0)
    ]
    assert on_page[0] == on_page[1] == on_page[2]
    fitted = [
        sorted(set(_ZONE.findall(_spanning(w).to_svg(border="zone", diagram="p&id"))))
        for w in (300.0, 900.0, 1500.0)
    ]
    assert len(set(map(tuple, fitted))) == 3


def test_zone_grid_runs_letters_down_and_numerals_right():
    """ISO 5457 4.4: the grid's origin is the top-left corner.

    The direction is the whole of a zone reference's meaning. ISO 15519-1
    Clause 9 composes an address out of it (``location_reference``), so a grid
    that runs the other way sends a reader who is told "B3" to the far corner
    of the sheet from the one the drawing meant.
    """
    from pandid.render import furniture as F

    z = F.zone_layout(0.0, 0.0, 1200.0, 700.0)
    labels = [part[1:] for part in z.parts if part[0] == "label"]
    # Each numeral is lettered twice, on the top band and the bottom, at one x;
    # each letter twice, left band and right, at one y. Dedupe to one per field.
    numerals = sorted({(x, text) for x, _y, text in labels if text.isdigit()})
    letters = sorted({(y, text) for _x, y, text in labels if text.isalpha()})

    assert [text for _x, text in numerals] == [str(n) for n in range(1, len(numerals) + 1)]
    assert [text for _y, text in letters] == list(string.ascii_uppercase[: len(letters)])


def test_zone_b3_is_where_a_reader_told_b3_would_look():
    """The rendered sheet, not the geometry: the issue's own reading of it."""
    svg = _spanning(900.0).to_svg(page_size="A3", border="zone", diagram="p&id")
    labels = _ZONE_LABEL.findall(svg)
    assert labels, "no zone labels on a border='zone' sheet"

    numerals = sorted({(float(x), text) for x, _y, text in labels if text.isdigit()})
    letters = sorted({(float(y), text) for _x, y, text in labels if text.isalpha()})
    assert [text for _x, text in numerals] == [str(n) for n in range(1, len(numerals) + 1)]
    assert [text for _y, text in letters] == list(string.ascii_uppercase[: len(letters)])

    # ...so B3 -- ISO 15519-1 5.1.2's spelling, row letter then column number --
    # is the second band down and the third column across, in the upper left.
    row_b = dict((text, y) for y, text in letters)["B"]
    column_3 = dict((text, x) for x, text in numerals)["3"]
    assert row_b < A3[1] / 2 and column_3 < A3[0] / 2


def test_pid_furniture_rules_to_the_sheet_edges():
    from pandid.document import TitleBlock
    from pandid.render.furniture import ZONE_BAND, measure_title_strip

    fs = _spanning(600.0)
    fs.title_block = TitleBlock(drawing_number="PFD-1")
    svg = fs.to_svg(page_size="A3", border="zone", diagram="p&id")
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
    svg = fs.to_svg(page_size="A4", border="zone", diagram="p&id")
    tx, ty, scale = _fit(svg)
    assert scale < 1
    x0, y0, x1, y1 = _drawing_bbox(fs)
    assert 0 <= x0 * scale + tx and x1 * scale + tx <= A4[0]
    assert 0 <= y0 * scale + ty and y1 * scale + ty <= A4[1]


def test_a_drawing_that_already_fits_is_never_blown_up():
    # Line weights and lettering are sheet-fixed; a small drawing keeps its size
    # and leaves the rest of the page white.
    _, _, scale = _fit(_spanning(300.0).to_svg(page_size="A0", border="zone", diagram="p&id"))
    assert scale == 1


def test_page_too_small_for_its_own_furniture_raises():
    from pandid.document import TableBox

    fs = _spanning(300.0)
    fs.add_annotation(TableBox(title="SCHEDULE", headers=["Tag"] * 40, rows=[["x"] * 40]))
    with pytest.raises(ValueError) as excinfo:
        fs.to_svg(page_size="A4", border="zone", diagram="p&id")
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
    pytest.importorskip("svglib")
    out = tmp_path / "sheet.pdf"
    _fs().render(str(out), page_size=name, border="zone", diagram="p&id")
    width_pt, height_pt = _pdf_page_pt(out.read_bytes())
    assert (width_pt / 72 * 25.4, height_pt / 72 * 25.4) == pytest.approx(mm, abs=0.01)


# --- connections: how the sheet says its joints are made up -------------------

#: One flange face: a bar of exactly FLANGE_TICK across the run, at the pipe's
#: own pen. Restated rather than imported for the reason the sheet sizes above
#: are: an edit to the constant must show up here as a failure, not be absorbed.
_FLANGE_BAR = re.compile(
    r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)" '
    r'stroke="[^"]+" stroke-width="2" />'
)


def _marks(svg: str) -> int:
    """How many flange *pairs* the sheet drew."""
    import math

    bars = [
        m
        for m in _FLANGE_BAR.findall(svg)
        if abs(math.dist((float(m[0]), float(m[1])), (float(m[2]), float(m[3]))) - 12.5) < 0.2
    ]
    assert len(bars) % 2 == 0, "a flange is a pair of faces and they are drawn together"
    return len(bars) // 2


def _joints() -> Flowsheet:
    """A vessel to a pump to a product flag, with a hand valve in the run.

    Five joints a mark could go on and three kinds of answer, which is the whole
    vocabulary in one sheet: the vessel and the pump are equipment and are
    marked by both settings, the valve is a body in the run and is marked only
    by the broader one, and the boundary flag is a reference to another drawing
    and is marked by neither.
    """
    fs = Flowsheet("joints")
    v = fs.add(U.Vessel("V-1"))
    hv = fs.add(U.Valve("HV-1"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(v.outlet, hv.inlet)
    fs.connect(hv.outlet, p.suction)
    fs.connect(p.discharge, prod.inlet)
    return fs


def test_a_sheet_marks_no_joints_unless_it_is_asked_to():
    """The honest default. Drawing every joint flanged is a claim about the
    piping, and nobody made it."""
    assert _marks(_joints().to_svg(diagram="p&id")) == 0
    assert _marks(_joints().to_svg(diagram="p&id", connections="none")) == 0


def test_a_flanged_sheet_flanges_the_bodies_in_the_run_as_well():
    """The defect: a sheet that said its connections were flanged drew its valves
    welded in, which is two statements. A valve in flanged service is flanged
    both sides -- that is how it is got out of the line -- and no clause in
    either ISO 15519 part says otherwise, because neither part contains the word
    at all. See ``svg.flanged_joint``."""
    svg = _joints().to_svg(diagram="p&id", connections="flanged")
    # V-1's nozzle, the pump's two, and HV-1's two faces. The product flag is a
    # sheet reference, so it is not a joint under any setting.
    assert _marks(svg) == 5


def test_flanged_at_nozzles_draws_what_the_reference_sheet_draws():
    """P&ID_301 flanges every piped branch off a shell and nothing else: not the
    gate valves either side of CV-305, not the drains, not the boundary flags.
    That convention stays reachable, under a name that says what it restricts."""
    svg = _joints().to_svg(diagram="p&id", connections="flanged-at-nozzles")
    assert _marks(svg) == 3


def _in_a_run(make) -> Flowsheet:
    """One in-line unit between two vessels, so the sheet's only question is what
    the thing in the middle takes."""
    fs = Flowsheet("run")
    a = fs.add(U.Vessel("V-1"))
    mid = fs.add(make())
    b = fs.add(U.Vessel("V-2"))
    fs.connect(a.outlet, mid.inlet)
    fs.connect(mid.outlet, b.inlet)
    return fs


@pytest.mark.parametrize(
    "make", [lambda: U.Reducer("RD-1"), lambda: U.Tee()], ids=["reducer", "tee"]
)
def test_a_welded_fitting_is_pipe_and_takes_no_mark_either_way(make):
    """A reducer and a tee are butt-welded into the run: they are as much pipe as
    the pipe either side, so neither setting marks them. Only what has to come
    out of the line is bolted into it."""
    fs = _in_a_run(make)
    # The two vessel nozzles and nothing in between, on either setting.
    assert _marks(fs.to_svg(diagram="p&id", connections="flanged")) == 2
    assert _marks(fs.to_svg(diagram="p&id", connections="flanged-at-nozzles")) == 2


def test_a_body_that_is_already_a_flange_is_not_flanged_again():
    """``Fitting``'s default variant *is* the flanged connection. An author who
    pinned one has drawn the joint; marking it would put three flange pairs where
    one was asked for. A strainer is a body like any other and takes both."""
    assert (
        _marks(_in_a_run(lambda: U.Fitting("F-1")).to_svg(diagram="p&id", connections="flanged"))
        == 2
    )
    assert (
        _marks(
            _in_a_run(lambda: U.Fitting("ST-1", variant="strainer")).to_svg(
                diagram="p&id", connections="flanged"
            )
        )
        == 4
    )


def test_the_bodies_flanged_are_a_subset_of_the_things_that_sit_in_a_run():
    """Two questions that look like one. ``INLINE_KINDS`` is what carries a line
    number through itself; ``_INLINE_BODIES`` is what gets bolted in. Every body
    is inline, and letting the two become the same set would flange every reducer
    on the sheet."""
    from pandid.flowsheet import INLINE_KINDS
    from pandid.render.svg import _INLINE_BODIES

    assert _INLINE_BODIES < INLINE_KINDS


def test_both_backends_place_every_label_side_the_vocabulary_names():
    """``LABEL_POSITIONS`` is the vocabulary; ``_label_place`` and draw.io's
    ``_LABEL_SIDE`` are two implementations of it and ``validate`` refuses
    anything outside it, so all three have to agree. A side named in the tuple
    that a backend does not place falls through to ``top`` -- which is the
    silent default the tuple exists to stop."""
    from pandid.render.drawio import _LABEL_SIDE
    from pandid.render.svg import LABEL_POSITIONS, SvgRenderer

    assert set(_LABEL_SIDE) == set(LABEL_POSITIONS)
    placed = {side: SvgRenderer()._label_place(side, 0, 0, 100, 40) for side in LABEL_POSITIONS}
    assert len(set(placed.values())) == len(LABEL_POSITIONS)


def test_a_pfd_marks_no_joints_however_it_is_asked():
    """ISO 15519-2:2015 Table 5 (p. 19) counts connections among the *specific*
    graphical symbols a P&ID carries as basic information; Table 4 (p. 17)
    allows the PFD only *general* symbols for its connections. A flange face is
    as specific as a connection gets, so a PFD does not draw one."""
    for value in ("flanged", "flanged-at-nozzles"):
        assert _marks(_joints().to_svg(connections=value)) == 0
        assert _marks(_joints().to_svg(diagram="pfd", connections=value)) == 0


def test_a_stream_may_say_the_opposite_of_its_sheet_either_way_round():
    """The default matters, so the override has to work in both directions: a
    mostly-welded sheet with one flanged joint and a mostly-flanged sheet with
    one welded joint are both drawings somebody makes."""
    welded = _joints()
    welded.streams[0].ends = "flanged"
    # V-1's nozzle and HV-1's inlet face: this run is flanged at both its ends.
    assert _marks(welded.to_svg(diagram="p&id")) == 2

    flanged = _joints()
    flanged.streams[0].ends = "none"
    assert _marks(flanged.to_svg(diagram="p&id", connections="flanged")) == 3


def test_one_run_may_take_the_narrower_convention_on_a_sheet_that_takes_the_wider():
    """``ends`` takes any member of ``CONNECTIONS``, not just the two ends of a
    switch, so the override is as expressive as the sheet setting it overrides."""
    fs = _joints()
    fs.streams[0].ends = "flanged-at-nozzles"
    # V-1's nozzle keeps its mark; HV-1's inlet face loses the one the sheet
    # would have given it. The other two runs are untouched.
    assert _marks(fs.to_svg(diagram="p&id", connections="flanged")) == 4


def test_a_stream_states_its_two_ends_apart_in_the_order_it_was_connected():
    fs = Flowsheet("pair")
    a = fs.add(U.Vessel("V-1"))
    b = fs.add(U.Vessel("V-2"))
    s = fs.connect(a.outlet, b.inlet, ends=("flanged", "none"))
    assert _marks(fs.to_svg(diagram="p&id")) == 1
    s.ends = ("none", "flanged")
    assert _marks(fs.to_svg(diagram="p&id")) == 1
    s.ends = ("flanged", "flanged")
    assert _marks(fs.to_svg(diagram="p&id")) == 2
    s.ends = None  # back to inheriting, and the sheet says nothing
    assert _marks(fs.to_svg(diagram="p&id")) == 0


def test_a_signal_line_has_no_joint_to_describe():
    """ISA-5.1 draws a signal as a line to a balloon. There is no pipe, so there
    is nothing for a flange to be a fact about -- and that has to hold even now
    that both of this signal's ends are things the sheet marks elsewhere: a
    control valve at one end, a balloon at the other."""
    from pandid.render.svg import flange_marks, stream_polyline

    fs = _loop()
    svg = fs.to_svg(diagram="p&id", connections="flanged")
    signals = [s for s in fs.streams if s.kind == "pneumatic"]
    assert signals, "the fixture stopped carrying a signal"
    for s in signals:
        assert flange_marks(s, stream_polyline(s), ("flanged", "flanged")) == []
    # FV-1's two faces, off the two process lines, and nothing off the signal:
    # the feed and the product are boundary flags and take no mark either.
    assert _marks(svg) == 2


def test_the_mark_stands_off_the_nozzle_the_way_the_head_does():
    """Just outside the outline, on the stream, and clear of the artwork: the
    near face sits FLANGE_STANDOFF - FLANGE_GAP/2 out and no bar touches the
    box it is drawn against."""
    from pandid.portgeom import unit_box
    from pandid.render.svg import FLANGE_GAP, FLANGE_STANDOFF, FLANGE_TICK

    fs = _joints()
    svg = fs.to_svg(diagram="p&id", connections="flanged")
    assert FLANGE_STANDOFF - FLANGE_GAP / 2 > 0, "the near face is outside the nozzle"
    boxes = [unit_box(u, u.frame) for u in fs.units if u.frame is not None]
    for x1, y1, x2, y2 in _FLANGE_BAR.findall(svg):
        bar = (
            min(float(x1), float(x2)),
            min(float(y1), float(y2)),
            max(float(x1), float(x2)),
            float(max(float(y1), float(y2))),
        )
        assert abs((bar[2] - bar[0]) + (bar[3] - bar[1]) - FLANGE_TICK) < 0.2
        for bx0, by0, bx1, by1 in boxes:
            assert bar[2] <= bx0 or bar[0] >= bx1 or bar[3] <= by0 or bar[1] >= by1, (
                "a flange bar is drawn across a symbol it should be standing off"
            )


@pytest.mark.parametrize("value", ["welded", "bolted", "socket"])
def test_a_joint_this_package_cannot_draw_raises_naming_the_ones_it_can(value):
    with pytest.raises(ValueError) as excinfo:
        _joints().to_svg(diagram="p&id", connections=value)
    assert "none" in str(excinfo.value) and "flanged" in str(excinfo.value)
    # ...and the same message for a stream that says it, raised when it is said
    # rather than when the sheet is drawn.
    fs = Flowsheet("t")
    a, b = fs.add(U.Vessel("V-1")), fs.add(U.Vessel("V-2"))
    with pytest.raises(ValueError) as excinfo:
        fs.connect(a.outlet, b.inlet, ends=value)
    assert "none" in str(excinfo.value) and "flanged" in str(excinfo.value)


def test_connections_reaches_render_and_the_drawio_export_too(tmp_path):
    out = tmp_path / "sheet.svg"
    _joints().render(str(out), diagram="p&id", connections="flanged")
    assert _marks(out.read_text(encoding="utf-8")) == 5
    # The export draws the same five, as its own cells: draw.io has no flange
    # in its arrow vocabulary, so they cannot ride the arrowhead's style keys.
    model = _joints().to_drawio(diagram="p&id", connections="flanged")
    assert model.count("shape=line;rotation=") == 10  # two faces per mark
    # ...and it honours the narrower setting too, rather than treating anything
    # that is not "none" as the sheet's own default.
    narrow = _joints().to_drawio(diagram="p&id", connections="flanged-at-nozzles")
    assert narrow.count("shape=line;rotation=") == 6


# --- stale geometry: an edit made after a render reaches the next one ---------
#
# A Frame and a Route are computed once and kept, because laying a sheet out and
# routing it costs far more than drawing it. The guard deciding whether to
# recompute used to be ``frame is None``, which is true only before the very
# first layout -- so from the second render on, every edit was silently absent
# from the file that came out, and a notebook baked the placement it happened to
# display first. The flowsheet now records that its geometry is stale and the
# entry points ask that instead.
#
# Both halves are tested here: that a change gets through, and that a sheet
# nobody changed still pays nothing, which is what the old guard was protecting.


def _unit(fs: Flowsheet, name: str):
    return next(u for u in fs.units if u.name == name)


def _heated() -> Flowsheet:
    """A feed, a heater and a product, placed by the engine."""
    fs = Flowsheet("stale")
    feed = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("H-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, heater.inlet)
    fs.connect(heater.outlet, prod.inlet)
    return fs


def _mutable() -> Flowsheet:
    """One sheet carrying everything ``MUTATIONS`` below reaches for.

    Every numbered nozzle is piped and ``P-3`` is the one spare: an
    unconnected nozzle is a warning of its own, and a fixture that always
    warns hides the warning a change breaks.
    """
    fs = Flowsheet("mutable")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    tank = fs.add(U.Tank("T-1"))
    block = fs.add(U.Block("B-1", inputs=["W", "S"], outputs=["E", "S"]))
    steam = fs.add(U.Feed("Steam"))
    prod = fs.add(U.Product("P-1"))
    drain = fs.add(U.Product("P-2"))
    fs.add(U.Product("P-3"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, tank.inlet)
    fs.connect(tank.outlet, block.in_1)
    fs.connect(steam.outlet, block.in_2)
    fs.connect(block.out_1, prod.inlet)
    fs.connect(block.out_2, drain.inlet)
    fs.add_instrument("PI", 101, sensing=fs.streams[0])
    return fs


def _stages(monkeypatch) -> dict:
    """Count the ``layout()`` and ``route()`` runs from here on.

    Counted on the class rather than timed, because what is being held is
    an exact property -- an unchanged sheet re-runs *neither* stage --
    and a stopwatch could only say it got faster.
    """
    runs = {"layout": 0, "route": 0}
    for stage in list(runs):
        original = getattr(Flowsheet, stage)

        def counted(self, *args, _stage=stage, _original=original, **kwargs):
            runs[_stage] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Flowsheet, stage, counted)
    return runs


def test_a_pin_made_after_a_render_reaches_the_next_one():
    fs = _heated()
    heater = _unit(fs, "H-1")
    before = fs.to_svg()
    heater.pin(x=600, y=400)
    after = fs.to_svg()
    assert (heater.frame.x, heater.frame.y) == (600, 400)
    assert after != before


def test_the_drawio_export_and_render_see_that_pin_too(tmp_path):
    """The three entry points share one rule, so they answer alike."""
    fs = _heated()
    before = fs.to_drawio()
    _unit(fs, "H-1").pin(x=600, y=400)
    assert fs.to_drawio() != before

    fs, out = _heated(), tmp_path / "sheet.svg"
    fs.render(str(out))
    was = out.read_text(encoding="utf-8")
    _unit(fs, "H-1").pin(x=600, y=400)
    fs.render(str(out))
    assert out.read_text(encoding="utf-8") != was


def test_rendering_an_unchanged_sheet_again_lays_it_out_no_further(monkeypatch, tmp_path):
    """The property the old guard was buying, and the reason the fix is a
    dirty flag rather than an unconditional re-layout."""
    fs = _heated()
    first = fs.to_svg()
    runs = _stages(monkeypatch)
    assert fs.to_svg() == first
    fs.to_drawio()
    fs.render(str(tmp_path / "sheet.svg"))
    assert runs == {"layout": 0, "route": 0}


def test_a_hand_called_layout_takes_the_routes_with_it():
    """A route is computed against the frames, so replacing the frames
    strands every route on the sheet they were measured from.

    ``render -> pin -> layout -> render`` is the sequence: the boxes move
    and the runs do not, and what gets drawn is the current nozzle joined
    to the old path -- a diagonal, which no P&ID line may be. See
    ``tests/test_route_invariants.py`` for the invariant itself.
    """
    from pandid.layout.attach import stream_path

    fs = _heated()
    fs.to_svg()
    _unit(fs, "H-1").pin(x=600, y=400)
    fs.layout()
    fs.to_svg()

    sloping = []
    for s in fs.streams:
        points = stream_path(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if abs(x1 - x2) > 0.01 and abs(y1 - y2) > 0.01:
                sloping.append(f"{s.name} runs ({x1:.0f}, {y1:.0f}) -> ({x2:.0f}, {y2:.0f})")
    assert not sloping, "; ".join(sloping)


#: Every way to change a sheet that can move a drawn box or a routed run.
#: Each is applied to a sheet already rendered once, and each has to leave
#: it saying so. ``add_loop()`` is deliberately absent: a loop draws
#: nothing and is never in ``units``.
MUTATIONS = {
    "pin": lambda fs: _unit(fs, "HV-1").pin(x=300, y=300),
    "add": lambda fs: fs.add(U.Vessel("V-9")),
    "connect": lambda fs: fs.connect(_unit(fs, "T-1").vent, _unit(fs, "P-3").inlet),
    "add_instrument": lambda fs: fs.add_instrument("TI", 102, near=_unit(fs, "HV-1")),
    "add_balloon": lambda fs: fs.add_balloon(_unit(fs, "HV-1")),
    "add_valve_station": lambda fs: fs.add_valve_station("CV-9", x=900, y=900),
    "nozzle": lambda fs: _unit(fs, "T-1").nozzle("inlet", "N"),
    "block_nozzle": lambda fs: _unit(fs, "B-1").nozzle("in_2", "N"),
    "block_order_on": lambda fs: _unit(fs, "B-1").order_on(
        "S", list(_unit(fs, "B-1").ports_on("S"))[::-1]
    ),
    "attach": lambda fs: _unit(fs, "PI-101").attach(fs.streams[0], at=0.8, offset=70),
    "width": lambda fs: setattr(_unit(fs, "T-1"), "width", 90),
    "height": lambda fs: setattr(_unit(fs, "T-1"), "height", 90),
    "variant": lambda fs: setattr(_unit(fs, "HV-1"), "variant", "ball"),
    "label_pos": lambda fs: setattr(_unit(fs, "HV-1"), "label_pos", "bottom"),
    "name": lambda fs: setattr(_unit(fs, "HV-1"), "name", "HV-1-A-VERY-LONG-TAG"),
    "normal_position": lambda fs: setattr(_unit(fs, "HV-1"), "normal_position", "closed"),
    "new_line_number": lambda fs: setattr(_unit(fs, "HV-1"), "new_line_number", True),
    "auto_faces": lambda fs: setattr(fs, "auto_faces", False),
}


@pytest.mark.parametrize("mutation", list(MUTATIONS), ids=list(MUTATIONS))
def test_every_mutation_that_can_move_something_marks_the_sheet_stale(mutation):
    fs = _mutable()
    fs.to_svg()
    assert not fs.warnings, "the fixture stopped being a clean sheet"
    assert (fs._layout_stale, fs._route_stale) == (False, False)
    MUTATIONS[mutation](fs)
    assert fs._layout_stale, f"{mutation} left the frames looking current"
    assert fs._route_stale, f"{mutation} left the routes looking current"


@pytest.mark.parametrize("mutation", ["add", "connect", "nozzle", "width", "variant", "name"])
def test_a_change_that_is_not_a_pin_reaches_the_drawing(mutation):
    """The flag above is the mechanism; this is what it is for."""
    fs = _mutable()
    before = fs.to_svg()
    MUTATIONS[mutation](fs)
    assert fs.to_svg() != before
