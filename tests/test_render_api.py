"""render() contract: to_svg() returns a string; render(path) writes the file
whose format is inferred from the extension and returns None."""

import re
import string
import sys

import pytest

from pandid import Flowsheet, units as U

# ISO 216 landscape sheets in millimetres, and in the px the drawing is laid out in.
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
    """Build a feed and a product pinned *width* apart."""
    fs = Flowsheet("span")
    feed = fs.add(U.Feed("F")).pin(x=50, y=25)
    prod = fs.add(U.Product("P")).pin(x=width, y=25)
    fs.connect(feed.outlet, prod.inlet)
    return fs


def _canvas(svg: str) -> tuple[float, float]:
    """Return the sheet's px canvas, cross-checked against the size ``<svg>`` declares."""
    m = _CANVAS.search(svg)
    assert m, "no canvas on the <svg> element"
    view = float(m.group(7)), float(m.group(8))
    declared = float(m.group(1)), float(m.group(3))
    assert m.group(2) == m.group(4), "width and height in different units"
    if m.group(2):  # a physical size: it must describe the same sheet
        assert (declared[0] * PX_PER_MM, declared[1] * PX_PER_MM) == pytest.approx(view, abs=0.1)
    else:
        assert declared == (round(view[0]), round(view[1]))
    return view


def _sheet_mm(svg: str) -> "tuple[float, float] | None":
    """Return the physical size the sheet declares, in mm; ``None`` if it declares none."""
    m = _CANVAS.search(svg)
    assert m, "no canvas on the <svg> element"
    if not m.group(2):
        return None
    return float(m.group(1)), float(m.group(3))


def _pdf_page_pt(pdf: bytes) -> tuple[float, float]:
    """Return the page size a PDF declares, in points, from its first ``/MediaBox``."""
    box = re.search(rb"/MediaBox\s*\[([^\]]*)\]", pdf)
    assert box, "no /MediaBox in the exported PDF"
    _, _, width, height = (float(v) for v in box.group(1).split())
    return width, height


def _fit(svg: str) -> tuple[float, float, float]:
    """Return the fitted drawing group's ``(tx, ty, scale)``."""
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


def test_render_svg_writes_file_and_returns_none(tmp_path):
    out = tmp_path / "d.svg"
    result = _fs().render(str(out))
    assert result is None
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("module", "path", "missing"),
    [("svglib.svglib", "d.pdf", "svglib"), ("pypdfium2", "d.png", "pypdfium2")],
)
def test_the_hint_names_the_package_of_the_extra_that_is_missing(
    tmp_path, monkeypatch, module, path, missing
):
    monkeypatch.setitem(sys.modules, module, None)  # makes the import fail
    with pytest.raises(ImportError) as excinfo:
        _fs().render(str(tmp_path / path))
    message = str(excinfo.value)
    assert missing in message
    assert "pip install 'pandid[pdf]'" in message


def test_jump_direction_reaches_the_public_api():
    from pandid.render.svg import HOP_R, SvgRenderer

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

    # Arcs on purpose: this counts arcs, and the arc is no longer the default.
    default = build().to_svg(crossing_style="arc")
    assert build().to_svg(jump_direction="vertical", crossing_style="arc") == default
    horizontal = build().to_svg(jump_direction="horizontal", crossing_style="arc")
    assert horizontal != default
    arc = f"A {HOP_R:g} {HOP_R:g}"
    assert default.count(arc) == horizontal.count(arc) == 2

    # ... and it means the same thing it means on the renderer itself.
    fs = build()
    fs.layout()
    fs.route()
    fs.renumber_streams()
    assert SvgRenderer().render(fs, jump_direction="horizontal", crossing_style="arc") == horizontal


def test_canvas_fits_content_and_is_not_padded_to_page_size():
    # A two-box diagram frames tightly rather than filling an A3 sheet (1587x1122).
    svg = _fs().to_svg()
    w, h = _canvas(svg)  # width/height in px equal the viewBox → no letterbox
    assert w < 800 and h < 500


# --- diagram: a P&ID draws its process lines without arrowheads ----------------

# An arrowhead on a drawn line, and the marker definition it points at.
_ARROWHEAD = re.compile(r'\s*marker-end="url\(#arrow_[^"]*\)"')
_MARKER_DEF = re.compile(r'<marker id="arrow_.*?</marker>', re.S)


def _loop() -> Flowsheet:
    """Build two process lines and the pneumatic signal that strokes their valve."""
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    fic = fs.add_instrument("FIC", 1, near=fv, face="N", offset=80)
    fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
    return fs


@pytest.mark.parametrize(
    "kwargs",
    [
        {"diagram": "p&id"},
        # A P&ID on the engineering frame.
        {"border": "zone", "diagram": "p&id"},
    ],
)
def test_a_pid_draws_its_process_lines_without_arrowheads(kwargs):
    svg = _loop().to_svg(**kwargs)
    assert '<g id="streams">' in svg  # the lines are still drawn
    assert not _ARROWHEAD.search(svg)  # ...with nothing on the end of them
    assert not _MARKER_DEF.search(svg)  # ...and nothing left defining one


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"diagram": "pfd"},
        {"border": "zone"},
        # A block flow diagram heads its lines as a PFD does (ISO 10628-1:2014 4.2.2 c)).
        {"diagram": "bfd"},
        {"diagram": "BFD"},  # ...however an engineer capitalises it
    ],
)
def test_a_sheet_that_is_not_a_pid_keeps_its_arrowheads(kwargs):
    # A PFD on the engineering frame.
    svg = _loop().to_svg(**kwargs)
    assert len(_ARROWHEAD.findall(svg)) == 2  # one per process line
    assert _MARKER_DEF.search(svg)


def test_a_pid_takes_the_arrowheads_off_and_changes_nothing_else():
    # Signal lines, symbols, balloons and stream numbers do not move.
    pfd = _loop().to_svg(diagram="pfd")
    pid = _loop().to_svg(diagram="p&id")
    stripped = _ARROWHEAD.sub("", _MARKER_DEF.sub("", pfd))
    assert " ".join(stripped.split()) == " ".join(pid.split())


def test_both_spellings_of_a_pid_mean_the_same_drawing():
    assert _loop().to_svg(diagram="p&id") == _loop().to_svg(diagram="pid")
    # ...and the drawing's own name, however an engineer capitalises it.
    assert _loop().to_svg(diagram="P&ID") == _loop().to_svg(diagram="pid")


def test_the_frame_and_the_drawing_are_asked_for_separately():
    """Check that the frame and the drawing are asked for separately."""
    sheets = {
        _loop().to_svg(border=b, diagram=d) for b in ("none", "zone") for d in ("pfd", "p&id")
    }
    assert len(sheets) == 4


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"diagram": "isometric"}, ["'p&id'", "'pid'", "'pfd'", "'bfd'"]),
        ({"border": "isometric"}, ["none", "zone"]),
        ({"border": "p&id"}, ["none", "zone"]),
    ],
)
def test_a_drawing_the_renderer_cannot_draw_raises_naming_the_spellings(kwargs, expected):
    with pytest.raises(ValueError) as excinfo:
        _loop().to_svg(**kwargs)
    for token in expected:
        assert token in str(excinfo.value)


# --- page_size: a named sheet is drawn at exactly that size --------------------


@pytest.mark.parametrize(
    "name,mm",
    [
        ("A4", A4_MM),
        ("A3", A3_MM),
        ("A2", (594.0, 420.0)),
        ("A1", (841.0, 594.0)),
        ("A0", A0_MM),
        ("a3", A3_MM),
    ],
)
@pytest.mark.parametrize("sheet", [{}, {"border": "zone", "diagram": "p&id"}])
def test_page_size_draws_a_sheet_of_exactly_that_size(name, mm, sheet):
    svg = _fs().to_svg(page_size=name, **sheet)
    assert _sheet_mm(svg) == mm


def test_a_furnished_page_is_that_size_with_or_without_a_border():
    # A title strip rules to the same place on a fixed page with or without the frame.
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
    # A zone reference stays put on a fixed page as the drawing grows.
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
    """Check that the zone grid runs letters down and numerals right (ISO 5457 4.4)."""
    from pandid.render import furniture as F

    z = F.zone_layout(0.0, 0.0, 1200.0, 700.0)
    labels = [part[1:] for part in z.parts if part[0] == "label"]
    # Each numeral and letter is lettered twice; keep one per field.
    numerals = sorted({(x, text) for x, _y, text in labels if text.isdigit()})
    letters = sorted({(y, text) for _x, y, text in labels if text.isalpha()})

    assert [text for _x, text in numerals] == [str(n) for n in range(1, len(numerals) + 1)]
    assert [text for _y, text in letters] == list(string.ascii_uppercase[: len(letters)])


def test_zone_b3_is_where_a_reader_told_b3_would_look():
    """Check that zone B3 is where a reader told B3 would look."""
    svg = _spanning(900.0).to_svg(page_size="A3", border="zone", diagram="p&id")
    labels = _ZONE_LABEL.findall(svg)
    assert labels, "no zone labels on a border='zone' sheet"

    numerals = sorted({(float(x), text) for x, _y, text in labels if text.isdigit()})
    letters = sorted({(float(y), text) for _x, y, text in labels if text.isalpha()})
    assert [text for _x, text in numerals] == [str(n) for n in range(1, len(numerals) + 1)]
    assert [text for _y, text in letters] == list(string.ascii_uppercase[: len(letters)])

    # B3 (ISO 15519-1 5.1.2) is the second band down and the third column across.
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
    # A small drawing keeps its size on a large page.
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


@pytest.mark.parametrize("name,mm", [("A4", A4_MM), ("A3", A3_MM), ("A0", A0_MM)])
def test_exported_pdf_lands_on_a_page_of_exactly_that_size(tmp_path, name, mm):
    # The PDF page a printer is handed is the named size.
    pytest.importorskip("svglib")
    out = tmp_path / "sheet.pdf"
    _fs().render(str(out), page_size=name, border="zone", diagram="p&id")
    width_pt, height_pt = _pdf_page_pt(out.read_bytes())
    assert (width_pt / 72 * 25.4, height_pt / 72 * 25.4) == pytest.approx(mm, abs=0.01)


# --- connections: how the sheet says its joints are made up -------------------

#: One flange face: a FLANGE_TICK bar across the run at the accessory rung (ISO 10628-1).
_FLANGE_BAR = re.compile(
    r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)" '
    r'stroke="[^"]+" stroke-width="1" />'
)


def _marks(svg: str) -> int:
    """Return how many flange *pairs* the sheet drew."""
    import math

    bars = [
        m
        for m in _FLANGE_BAR.findall(svg)
        if abs(math.dist((float(m[0]), float(m[1])), (float(m[2]), float(m[3]))) - 12.5) < 0.2
    ]
    assert len(bars) % 2 == 0, "a flange is a pair of faces and they are drawn together"
    return len(bars) // 2


def _joints() -> Flowsheet:
    """Build a vessel, pump and product flag with a hand valve in the run."""
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
    """Check that a sheet marks no joints unless it is asked to."""
    assert _marks(_joints().to_svg(diagram="p&id")) == 0
    assert _marks(_joints().to_svg(diagram="p&id", connections="none")) == 0


def test_a_flanged_sheet_flanges_the_bodies_in_the_run_as_well():
    """Check that a flanged sheet flanges the bodies in the run as well."""
    svg = _joints().to_svg(diagram="p&id", connections="flanged")
    # V-1's nozzle, the pump's two and HV-1's two faces; the product flag is no joint.
    assert _marks(svg) == 5


def test_flanged_at_nozzles_draws_what_the_reference_sheet_draws():
    """Check that ``flanged-at-nozzles`` draws what the reference sheet draws."""
    svg = _joints().to_svg(diagram="p&id", connections="flanged-at-nozzles")
    assert _marks(svg) == 3


def _in_a_run(make) -> Flowsheet:
    """Return a sheet with the unit ``make`` builds between two vessels."""
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
    """Check that a welded fitting is pipe and takes no mark either way."""
    fs = _in_a_run(make)
    # The two vessel nozzles and nothing in between, on either setting.
    assert _marks(fs.to_svg(diagram="p&id", connections="flanged")) == 2
    assert _marks(fs.to_svg(diagram="p&id", connections="flanged-at-nozzles")) == 2


def test_a_body_that_is_already_a_flange_is_not_flanged_again():
    """Check that a body that is already a flange is not flanged again."""
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
    """Check that the bodies flanged are a subset of the things that sit in a run."""
    from pandid.flowsheet import INLINE_KINDS
    from pandid.render.svg import _INLINE_BODIES

    assert _INLINE_BODIES < INLINE_KINDS


def test_both_backends_place_every_label_side_the_vocabulary_names():
    """Check that both backends place every label side the vocabulary names."""
    from pandid.render.drawio import _LABEL_SIDE
    from pandid.render.svg import LABEL_POSITIONS, SvgRenderer

    assert set(_LABEL_SIDE) == set(LABEL_POSITIONS)
    placed = {side: SvgRenderer()._label_place(side, 0, 0, 100, 40) for side in LABEL_POSITIONS}
    assert len(set(placed.values())) == len(LABEL_POSITIONS)


def test_a_pfd_marks_no_joints_however_it_is_asked():
    """Check that a PFD marks no joints however it is asked (ISO 15519-2 Table 5)."""
    for value in ("flanged", "flanged-at-nozzles"):
        assert _marks(_joints().to_svg(connections=value)) == 0
        assert _marks(_joints().to_svg(diagram="pfd", connections=value)) == 0


def test_a_stream_may_say_the_opposite_of_its_sheet_either_way_round():
    """Check that a stream may say the opposite of its sheet either way round."""
    welded = _joints()
    welded.streams[0].ends = "flanged"
    # V-1's nozzle and HV-1's inlet face: this run is flanged at both its ends.
    assert _marks(welded.to_svg(diagram="p&id")) == 2

    flanged = _joints()
    flanged.streams[0].ends = "none"
    assert _marks(flanged.to_svg(diagram="p&id", connections="flanged")) == 3


def test_one_run_may_take_the_narrower_convention_on_a_sheet_that_takes_the_wider():
    """Check that one run may take the narrower convention on a sheet that takes the wider."""
    fs = _joints()
    fs.streams[0].ends = "flanged-at-nozzles"
    # V-1's nozzle keeps its mark and HV-1's inlet face loses its own.
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
    """Check that a signal line has no joint to describe."""
    from pandid.render.svg import flange_marks, stream_polyline

    fs = _loop()
    svg = fs.to_svg(diagram="p&id", connections="flanged")
    signals = [s for s in fs.streams if s.kind == "pneumatic"]
    assert signals, "the fixture stopped carrying a signal"
    for s in signals:
        assert flange_marks(s, stream_polyline(s), ("flanged", "flanged")) == []
    # FV-1's two faces; the signal and the boundary flags take none.
    assert _marks(svg) == 2


def test_the_mark_stands_off_the_nozzle_the_way_the_head_does():
    """Check that the mark stands off the nozzle the way the head does."""
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
    # ...and a stream raises the same message when it is given the value.
    fs = Flowsheet("t")
    a, b = fs.add(U.Vessel("V-1")), fs.add(U.Vessel("V-2"))
    with pytest.raises(ValueError) as excinfo:
        fs.connect(a.outlet, b.inlet, ends=value)
    assert "none" in str(excinfo.value) and "flanged" in str(excinfo.value)


def test_connections_reaches_render_and_the_drawio_export_too(tmp_path):
    out = tmp_path / "sheet.svg"
    _joints().render(str(out), diagram="p&id", connections="flanged")
    assert _marks(out.read_text(encoding="utf-8")) == 5
    # The export draws the same five marks as cells of its own.
    model = _joints().to_drawio(diagram="p&id", connections="flanged")
    assert model.count("shape=line;rotation=") == 10  # two faces per mark
    # ...and honours the narrower setting too.
    narrow = _joints().to_drawio(diagram="p&id", connections="flanged-at-nozzles")
    assert narrow.count("shape=line;rotation=") == 6


# --- stale geometry: an edit made after a render reaches the next one ---------


def _unit(fs: Flowsheet, name: str):
    return next(u for u in fs.units if u.name == name)


def _heated() -> Flowsheet:
    """Build a feed, a heater and a product, placed by the engine."""
    fs = Flowsheet("stale")
    feed = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("H-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, heater.inlet)
    fs.connect(heater.outlet, prod.inlet)
    return fs


def _mutable() -> Flowsheet:
    """Build one sheet carrying everything ``MUTATIONS`` below reaches for."""
    fs = Flowsheet("mutable")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    tank = fs.add(U.Tank("T-1"))
    block = fs.add(U.Block("B-1", inputs=["W", "S"], outputs=["E", "S"]))
    steam = fs.add(U.Feed("Steam"))
    prod = fs.add(U.Product("P-1"))
    drain = fs.add(U.Product("P-2"))
    fs.add(U.Product("P-3"))
    fs.connect(feed.outlet, valve.inlet).properties = {"Flow (kg/h)": "1000"}
    fs.connect(valve.outlet, tank.inlet)
    fs.connect(tank.outlet, block.in_1)
    fs.connect(steam.outlet, block.in_2).properties = {"Flow (kg/h)": "50"}
    fs.connect(block.out_1, prod.inlet).properties = {"Flow (kg/h)": "900"}
    fs.connect(block.out_2, drain.inlet).properties = {"Flow (kg/h)": "150"}
    fs.add_instrument("PI", 101, sensing=fs.streams[0])
    return fs


def _stages(monkeypatch) -> dict:
    """Count the ``layout()`` and ``route()`` runs from here on."""
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
    """Check that the draw.io export and render() see that pin too."""
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
    """Check that rendering an unchanged sheet again lays it out no further."""
    fs = _heated()
    first = fs.to_svg()
    runs = _stages(monkeypatch)
    assert fs.to_svg() == first
    fs.to_drawio()
    fs.render(str(tmp_path / "sheet.svg"))
    assert runs == {"layout": 0, "route": 0}


def test_a_hand_called_layout_takes_the_routes_with_it():
    """Check that a hand-called layout() takes the routes with it."""
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


def _retype(fs: Flowsheet) -> None:
    """Reassign HV-1's variant, expecting the deprecation."""
    with pytest.warns(DeprecationWarning, match="variant"):
        _unit(fs, "HV-1").variant = "ball"


#: Every way to change a rendered sheet that can move a drawn box or a routed run.
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
    "variant": _retype,
    "label_pos": lambda fs: setattr(_unit(fs, "HV-1"), "label_pos", "bottom"),
    "name": lambda fs: setattr(_unit(fs, "HV-1"), "name", "HV-1-A-VERY-LONG-TAG"),
    "normal_position": lambda fs: setattr(_unit(fs, "HV-1"), "normal_position", "closed"),
    "new_line_number": lambda fs: setattr(_unit(fs, "HV-1"), "new_line_number", True),
    "auto_faces": lambda fs: setattr(fs, "auto_faces", False),
}


@pytest.mark.parametrize("mutation", list(MUTATIONS), ids=list(MUTATIONS))
def test_every_mutation_that_can_move_something_marks_the_sheet_stale(mutation):
    fs = _mutable()
    fs.to_svg(show_stream_table=True)
    assert not fs.warnings, "the fixture stopped being a clean sheet"
    assert (fs._layout_stale, fs._route_stale) == (False, False)
    MUTATIONS[mutation](fs)
    assert fs._layout_stale, f"{mutation} left the frames looking current"
    assert fs._route_stale, f"{mutation} left the routes looking current"


@pytest.mark.parametrize("mutation", ["add", "connect", "nozzle", "width", "variant", "name"])
def test_a_change_that_is_not_a_pin_reaches_the_drawing(mutation):
    """Check that a change that is not a pin reaches the drawing."""
    fs = _mutable()
    before = fs.to_svg()
    MUTATIONS[mutation](fs)
    assert fs.to_svg() != before


def test_every_render_keyword_is_named_in_its_own_docstring():
    """Check that every render keyword is named in its own docstring."""
    import inspect
    import re

    from pandid.render.drawio import DrawioRenderer
    from pandid.render.svg import SvgRenderer

    for renderer in (SvgRenderer, DrawioRenderer):
        sig = inspect.signature(renderer.render)
        doc = " ".join((inspect.getdoc(renderer.render) or "").split())
        keywords = [
            name for name, p in sig.parameters.items() if p.kind == inspect.Parameter.KEYWORD_ONLY
        ]
        # The signature is not empty, so the docstring check below cannot pass vacuously.
        assert keywords, f"{renderer.__name__}.render grew no keyword-only parameters"
        missing = [kw for kw in keywords if not re.search(rf"\b{re.escape(kw)}\b", doc)]
        assert not missing, (
            f"{renderer.__name__}.render takes {missing} and its docstring never says so"
        )
