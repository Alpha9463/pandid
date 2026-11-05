"""Check Draw.io document structure, shape keys, geometry, and styling against the SVG sheet."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from decimal import Decimal
import pathlib
import re
import xml.etree.ElementTree as ET

import pytest

from _render_cases import _script, copy_settled_case
from test_crossing_style import _ARC, MARKED, _paths
from _layout_cases import overlaps
import pandid
from pandid import units
from pandid.flowsheet import Flowsheet
from pandid.portgeom import port_point, unit_box
from pandid.render.drawio import (
    _APPROXIMATIONS,
    HOP_DROPPED,
    _hops,
    _PART_APPROXIMATIONS,
    DrawioRenderer,
)
from pandid.render.svg import (
    CROSSING_STYLES,
    HOP_R,
    _class_weight,
    _LEADER_HEAD,
    HATCH_ARM,
    _page,
    boundary_flag,
    drawing_bounds,
    impulse_tap,
    pneumatic_marks,
    stream_hops,
    stream_polyline,
    tap_lines,
    tap_route,
)
from pandid.render.symbols import _GROUP, Symbol, default_registry, expander
from pandid.render.weights import LineWeight

ROOT = pathlib.Path(__file__).resolve().parent.parent
STENCILS = ROOT / "scripts" / "vendor_data" / "drawio"

#: Shapes registered by mxGraph; ``None`` denotes its default rectangle.
_MXGRAPH_SHAPES = {None, "ellipse", "rhombus", "hexagon", "triangle", "line"}

#: Shapes registered by Draw.io itself rather than loaded from stencil files.
_DRAWIO_SHAPES = {"offPageConnector", "table", "tableRow", "partialRectangle"}

#: What an approximation, or anything else this exporter writes, may name.
_BUILTIN_SHAPES = _MXGRAPH_SHAPES | _DRAWIO_SHAPES


# Derive stencil keys independently from the vendored XML.


def _stencil_keys() -> set[str]:
    """Collect shape keys from the vendored Draw.io stencil XML."""
    keys = set()
    for path in sorted(STENCILS.glob("*.xml")):
        root = ET.parse(path).getroot()
        package = root.get("name")
        assert package, f"{path.name} names no package on its root element"
        for shape in root.findall("shape"):
            name = shape.get("name")
            assert name, f"{path.name} has a shape with no name"
            keys.add(f"{package}.{name}".replace(" ", "_").lower())
    return keys


STENCIL_KEYS = _stencil_keys()


def _every_drawing() -> list[tuple[str, str, Symbol]]:
    """Collect registered, closed, and reversed symbol drawings."""
    out = [
        (kind, variant, sym) for (kind, variant), sym in sorted(default_registry._symbols.items())
    ]
    out += [
        (kind, f"{variant} [closed]", sym)
        for (kind, variant), sym in sorted(default_registry._closed.items())
    ]
    out += [
        (kind, f"{variant} [expander]", expander(sym))
        for (kind, variant), sym in sorted(default_registry._symbols.items())
        if kind == "reducer"
    ]
    return out


DRAWINGS = _every_drawing()
DRAWING_IDS = [f"{kind}/{variant}" for kind, variant, _ in DRAWINGS]


@pytest.mark.parametrize("entry", DRAWINGS, ids=DRAWING_IDS)
def test_every_drawing_exports_as_a_stencil_or_a_written_down_approximation(entry):
    """Check each drawing names a stretchable vendored stencil or a documented built-in."""
    kind, variant, sym = entry
    assert ";" not in sym.drawio_shape and "=" not in sym.drawio_shape
    if sym.drawio_shape:
        assert sym.drawio_shape in STENCIL_KEYS, f"{kind}/{variant}: no {sym.drawio_shape!r}"
        assert sym.stretchable, f"{kind}/{variant} references a fixed-aspect stencil"
        return
    base = variant.split(" [")[0]
    assert (kind, base) in _APPROXIMATIONS, f"{kind}/{base} has no stencil and no approximation"
    assert _APPROXIMATIONS[(kind, base)].shape in _BUILTIN_SHAPES


def test_the_approximations_name_only_shapes_and_symbols_that_exist():
    """Check each approximation names a registered stencil-less symbol and built-in shapes."""
    for (kind, variant), approx in _APPROXIMATIONS.items():
        assert (kind, variant) in default_registry._symbols, (
            f"_APPROXIMATIONS names {kind}/{variant}, which the registry does not draw"
        )
        assert not default_registry._symbols[(kind, variant)].drawio_shape, (
            f"{kind}/{variant} has a draw.io stencil of its own"
        )
        for shape in (approx.shape, approx.inscribed):
            assert shape in _BUILTIN_SHAPES or shape is None, f"{kind}/{variant}: {shape!r}"


# Export warnings.


def test_a_stand_in_says_on_fs_warnings_what_it_lost():
    """Report the artwork lost by each approximate symbol."""
    fs = Flowsheet("lost")
    feed = fs.add(units.Feed("F"))
    belt = fs.add(units.Conveyor("CV-101"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, belt.feed)
    fs.connect(belt.discharge, prod.inlet)

    fs.to_drawio()
    said = [w for w in fs.warnings if w.code == "drawio-approximated"]
    assert len(said) == 1
    assert "CV-101" in said[0].message
    assert _APPROXIMATIONS[("conveyor", "default")].lost in said[0].message

    # The SVG reports nothing, and a second export replaces the first one's findings.
    fs.to_svg()
    assert "drawio-approximated" not in [w.code for w in fs.warnings]
    fs.to_drawio()
    fs.to_drawio()
    assert [w.code for w in fs.warnings].count("drawio-approximated") == 1


def test_a_stand_in_that_loses_nothing_says_nothing():
    """Omit loss warnings for faithful built-in shapes."""
    assert not _APPROXIMATIONS[("feed", "default")].lost, "the premise has moved"
    fs = Flowsheet("exact")
    feed = fs.add(units.Feed("F"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    fs.to_drawio()
    assert "drawio-approximated" not in [w.code for w in fs.warnings]


def _truncated_title_sheet() -> Flowsheet:
    """Build a sheet with title-block fields that exceed their cell widths."""
    from pandid.document import TitleBlock

    fs = Flowsheet("strip")
    feed = fs.add(units.Feed("F"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    fs.title_block = TitleBlock(
        title="T",
        drawing_number="PFD-A300-0001-REV-C-SHEET-1-OF-9-LONG",
        status="ISSUED FOR CONSTRUCTION AND PROCUREMENT",
    )
    return fs


def test_the_export_reports_a_title_block_cell_it_had_to_abbreviate():
    """Report title-block text shortened during export."""
    svg_sheet, drawio_sheet = _truncated_title_sheet(), _truncated_title_sheet()
    svg_sheet.to_svg(page_size="A3")
    drawio_sheet.to_drawio(page_size="A3")
    truncated = [w for w in drawio_sheet.warnings if w.code == "text-truncated"]
    assert {w.message for w in svg_sheet.warnings if w.code == "text-truncated"} == {
        w.message for w in truncated
    }
    assert any("drawing_number" in w.message for w in truncated)
    assert any("status" in w.message for w in truncated)


# A sheet carrying one of everything.


#: Registered ``(kind, variant)`` pairs selected by ``display=``.
_BY_DISPLAY = {("instrument", "panel"): "central", ("instrument", "aux"): "subsidiary"}


@pytest.fixture(scope="module")
def every_symbol_sheet() -> Flowsheet:
    """Place every registered symbol on a test sheet."""
    fs = Flowsheet("every symbol")
    n = 0
    for name in units.__all__:
        cls = getattr(units, name)
        for variant in default_registry.variants(cls.kind):
            tag = f"{cls.kind[:3].upper()}-{n}"
            # Location bars are selected by display rather than by symbol kind.
            if (cls.kind, variant) in _BY_DISPLAY:
                unit = cls(tag, display=_BY_DISPLAY[cls.kind, variant])
            else:
                # A Separator's characteristic drawings are asked for by characteristic=.
                how = (
                    "characteristic"
                    if variant in getattr(cls, "_CHARACTERISTICS", ())
                    else "variant"
                )
                unit = cls(tag, **{how: variant})
            fs.add(unit)
            unit.pin(x=(n % 12) * 300.0, y=(n // 12) * 300.0)
            n += 1
    fs.layout()
    return fs


def test_the_sheet_covers_every_registered_symbol(every_symbol_sheet):
    """Cover every symbol registered for export."""
    drawn = {(u.kind, getattr(u, "variant", "default")) for u in every_symbol_sheet.units}
    assert drawn == set(default_registry._symbols)


def test_an_exported_sheet_references_only_shapes_that_resolve(every_symbol_sheet):
    """Resolve every shape reference in a full-sheet export."""
    doc = ET.fromstring(every_symbol_sheet.to_drawio(check=False))
    shapes = set()
    for cell in doc.iter("mxCell"):
        for key in cell.get("style", "").split(";"):
            if key.startswith("shape="):
                shapes.add(key[len("shape=") :])
    assert shapes, "no shape references at all -- the sheet exported as blank boxes"
    unresolved = sorted(s for s in shapes if s not in STENCIL_KEYS and s not in _BUILTIN_SHAPES)
    assert not unresolved, f"unresolvable shape references: {unresolved}"


# The document draw.io expects.


def _model(fs: Flowsheet, **kwargs) -> ET.Element:
    """Parse an export and return its graph root."""
    doc = ET.fromstring(fs.to_drawio(**kwargs))
    assert doc.tag == "mxfile"
    diagrams = doc.findall("diagram")
    assert len(diagrams) == 1, "one flowsheet is one page"
    assert diagrams[0].get("id"), "a page with no id"
    models = diagrams[0].findall("mxGraphModel")
    assert len(models) == 1
    roots = models[0].findall("root")
    assert len(roots) == 1
    return roots[0]


@pytest.fixture(scope="module")
def sample() -> Flowsheet:
    """Build a small connected sheet for export checks."""
    fs = Flowsheet("sample")
    feed = fs.add(units.Feed("FEED", reference="P-01"))
    pump = fs.add(units.Pump("P-101"))
    valve = fs.add(units.Valve("FV-101", variant="control"))
    tank = fs.add(units.Tank("T-101"))
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, pump.suction)
    line = fs.connect(pump.discharge, valve.inlet)
    fs.connect(valve.outlet, tank.inlet)
    fs.connect(tank.outlet, product.inlet)
    ft = fs.add_instrument("FT", 101, sensing=line, at=0.5, offset=60)
    fs.connect(ft.sig_out, valve.actuator, kind="electric")
    fs.route()
    return fs


def test_the_model_carries_drawios_two_root_cells(sample):
    """Include the two root cells required by Draw.io."""
    root = _model(sample)
    cells = root.findall("mxCell")
    assert cells[0].get("id") == "0" and cells[0].get("parent") is None
    assert cells[1].get("id") == "1" and cells[1].get("parent") == "0"


def test_every_drawn_cell_is_parented_and_uniquely_identified(sample):
    """Give every drawn cell one identifier and a valid parent."""
    root = _model(sample)
    ids = [cell.get("id") for cell in root.findall("mxCell")]
    assert len(ids) == len(set(ids)), "two cells under one id"
    for cell in root.findall("mxCell")[2:]:
        assert cell.get("parent") == "1", f"cell {cell.get('id')} is parented nowhere"
        assert (cell.get("vertex") == "1") != (cell.get("edge") == "1"), (
            f"cell {cell.get('id')} is neither a vertex nor an edge, or is both"
        )
        assert len(cell.findall("mxGeometry")) == 1


def test_every_edge_joins_cells_that_exist(sample):
    """Connect every edge to existing cells."""
    root = _model(sample)
    ids = {cell.get("id") for cell in root.findall("mxCell")}
    edges = [c for c in root.findall("mxCell") if c.get("edge") == "1"]
    # Every stream and every instrument connection is an edge.
    assert len(edges) == len(sample.streams) + len(tap_lines(sample))
    for edge in edges:
        assert edge.get("target") in ids
        # A stream tap uses a fixed endpoint; other taps reference two cells.
        if edge.get("source") is None:
            assert edge.find('mxGeometry/mxPoint[@as="sourcePoint"]') is not None
        else:
            assert edge.get("source") in ids


def test_every_instrument_connection_is_exported_as_an_edge(sample):
    """Export each instrument tap as a connected edge."""
    root = _model(sample)
    drawn = tap_lines(sample)
    assert drawn, "the fixture stopped exercising tap lines"
    taps = {c.get("id"): c for c in root.findall("mxCell") if (c.get("id") or "").startswith("t")}
    assert len(taps) == len(drawn)
    at = {i: _style(c) for i, c in {c.get("id"): c for c in root.findall("mxCell")}.items()}
    for n, (inst, tap, centre) in enumerate(drawn):
        style = _style(taps[f"t{n}"])
        # Solid to the process, dashed to the control system (§5.1.1).
        assert ("dashed" in style) != impulse_tap(inst)
        # The balloon end lands on the balloon's centre.
        landed = _drawio_connection_point(inst, at[taps[f"t{n}"].get("target")], style, "entry")
        assert landed == pytest.approx(centre, abs=0.01)
        point = taps[f"t{n}"].find('mxGeometry/mxPoint[@as="sourcePoint"]')
        assert point is not None and taps[f"t{n}"].get("source") is None
        assert (float(point.attrib["x"]), float(point.attrib["y"])) == pytest.approx(tap, abs=0.01)


def test_an_off_page_flag_is_a_pennant_with_its_tag_inside_it():
    """Export an off-page flag as a pennant with an internal tag."""
    fs = Flowsheet("flags")
    east = fs.add(units.Feed("FEED", reference="P-01"))
    east.pin(x=100, y=100)
    west = fs.add(units.Product("PROD"))
    west.pin(x=400, y=100, mirrored=True)
    fs.layout()
    cells = _cells(fs, check=False)
    for i, unit, direction in ((0, east, "north"), (1, west, "south")):
        style = _style(cells[f"u{i}"])
        assert style["shape"] == "offPageConnector"
        assert style["direction"] == direction
        # The 15-unit point cut, as a fraction of the turned cell's width.
        (x0, _, x1, _), depth, _east = boundary_flag(unit, unit.frame)
        assert float(style["size"]) == pytest.approx(depth / (x1 - x0), abs=1e-6)
        # Keep the tag inside the flag.
        assert style["verticalLabelPosition"] == "middle"
        assert style["verticalAlign"] == "middle" and style["align"] == "center"
        assert "labelPosition" not in style
    assert cells["u0"].get("value") == "FEED<br>P-01"


def test_a_label_written_inside_its_shape_fits_inside_it(settled_gallery, rendered_gallery):
    """Fit text labels inside their exported shapes."""
    from pandid.render.drawio import _LINE_BOX

    for stem in DRAWIO_REPRESENTATIVES:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        cells = _gallery_cells(rendered_gallery, stem)
        for i, unit in enumerate(fs.units):
            cell = cells[f"u{i}"]
            value = cell.get("value") or ""
            style = _style(cell)
            # Only labels written inside the cell; a side tag has no box to overflow.
            if not value or style.get("verticalLabelPosition") != "middle":
                continue
            if style.get("labelPosition") in ("left", "right"):
                continue
            box = _LINE_BOX * float(style["fontSize"]) * (value.count("<br>") + 1)
            height = float(cell.find("mxGeometry").get("height"))
            assert box <= height + 0.01, f"{stem}: {unit.name} {value!r} {box:.2f} > {height:.2f}"


def _unit_label_sizes(fs, kwargs, **over) -> list[float]:
    """Read exported font sizes of units with labels."""
    cells = _drawio_cells(fs, {**kwargs, **over})
    return [
        float(_style(cells[f"u{i}"])["fontSize"])
        for i in range(len(fs.units))
        if cells[f"u{i}"].get("value")
    ]


def test_the_drawing_is_lettered_at_the_size_the_sheet_letters_it(settled_gallery):
    """Scale exported lettering with the drawing geometry."""
    from pandid.render.drawio import _TAG_TYPE

    fs, kwargs = copy_settled_case(settled_gallery, "10_ethanol_pid")
    fs.to_svg(**kwargs)

    # Without paper the export keeps the drawing's own coordinates and type.
    plain = _unit_label_sizes(fs, kwargs, page_size=None, border=None)
    assert plain and max(plain) == _TAG_TYPE

    # With paper every label scales by the geometry's ratio, or is capped smaller.
    fitted = _unit_label_sizes(fs, kwargs)
    assert len(fitted) == len(plain)
    assert max(fitted) < _TAG_TYPE, "the type was left at its unfitted size"
    ratio = max(fitted) / _TAG_TYPE
    assert all(size <= ratio * _TAG_TYPE + 0.01 for size in fitted)
    cells = _drawio_cells(fs, kwargs)
    for i, unit in enumerate(fs.units):
        if unit.kind not in ("feed", "product") or not fs.units[i].tag:
            continue
        box = boundary_flag(unit, unit.frame).box
        # A flag's cell is scaled by the same ratio.
        cell = cells[f"u{i}"].find("mxGeometry")
        assert float(cell.get("height")) == pytest.approx(ratio * (box[3] - box[1]), abs=0.01)


def test_a_flag_is_drawn_across_its_own_box():
    """Match boundary-flag width to its unit box."""
    for cls, mirrored in (
        (units.Feed, False),
        (units.Feed, True),
        (units.Product, False),
        (units.Product, True),
    ):
        for reference in ("", "PFD-302"):
            fs = Flowsheet("extent")
            flag = fs.add(cls("X", reference=reference))
            flag.pin(x=137.5, y=42.25, mirrored=mirrored)
            fs.layout()
            bx0, by0, bx1, by1 = boundary_flag(flag, flag.frame).box
            ux0, uy0, ux1, uy1 = unit_box(flag, flag.frame)
            assert (bx0, bx1) == pytest.approx((ux0, ux1), abs=1e-9)
            # Keep vertical insets within the flag box.
            assert uy0 < by0 < by1 < uy1


def test_a_tall_flag_fills_its_own_box_rather_than_a_fixed_50_units():
    """Scale a flag pennant to its configured height."""
    for cls, mirrored in (
        (units.Feed, False),
        (units.Feed, True),
        (units.Product, False),
        (units.Product, True),
    ):
        fs = Flowsheet("tall-flag")
        flag = fs.add(cls("X", height=120))
        flag.pin(x=100, y=50, mirrored=mirrored, port=None)
        fs.layout()

        ux0, uy0, ux1, uy1 = unit_box(flag, flag.frame)
        assert (uy1 - uy0) == pytest.approx(120.0)

        bx0, by0, bx1, by1 = boundary_flag(flag, flag.frame).box
        # The pennant is inset a fixed amount from the placed height.
        assert (by1 - by0) == pytest.approx(120.0 - 2 * 15)
        assert uy0 < by0 < by1 < uy1

        port_name = next(iter(flag.ports))
        _, py = port_point(flag, flag.frame, port_name)
        # Centred in the pennant, not a quarter of the way down it.
        assert py == pytest.approx((by0 + by1) / 2)

        # The SVG polygon's tip agrees with the port and with draw.io's cell.
        svg = fs.to_svg()
        points = re.findall(r'<polygon[^>]*points="([^"]+)"', svg)[0]
        tip_y = float(points.split()[2].split(",")[1])
        assert tip_y == pytest.approx(py)

        cells = _drawio_cells(fs, {})
        geom = cells["u0"].find("mxGeometry")
        dy0 = float(geom.get("y"))
        dy1 = dy0 + float(geom.get("height"))
        assert (dy0, dy1) == pytest.approx((by0, by1))


def test_a_default_sized_flag_is_unmoved_by_the_height_fix():
    """Keep default flag geometry at its standard size."""
    fs = Flowsheet("plain-flag")
    feed = fs.add(units.Feed("F"))
    feed.pin(x=100, y=50, port=None)
    fs.layout()
    box = boundary_flag(feed, feed.frame).box
    assert box == pytest.approx((70.0, 65.0, 150.0, 85.0))
    _, py = port_point(feed, feed.frame, "outlet")
    assert py == pytest.approx(75.0)


def test_a_tee_draws_no_ink_of_its_own():
    """Draw a tee junction with its streams rather than its cell."""
    fs = Flowsheet("tee")
    tee = fs.add(units.Tee("TEE"))
    tee.pin(x=100, y=100)
    fs.layout()
    cell = _cells(fs, check=False)["u0"]
    style = _style(cell)
    assert "shape" not in style
    assert style["strokeColor"] == "none"
    assert style["fillColor"] == "none"
    assert (cell.get("value") or "") == ""
    # Still a cell, so the pipes stay attached to it when it is dragged.
    assert cell.get("vertex") == "1"
    assert cell.find("mxGeometry") is not None


def _pneumatic_sheet() -> Flowsheet:
    """Return a routed sheet with one pneumatic signal line."""
    fs = Flowsheet("pneumatic")
    valve = fs.add(units.Valve("FV-101", variant="control"))
    valve.pin(x=400, y=300)
    pic = fs.add_instrument("PIC", 101, display="central")
    pic.pin(x=100, y=100)
    fs.connect(pic.sig_out, valve.actuator, kind="pneumatic")
    fs.route()
    return fs


def test_a_pneumatic_line_is_marked_where_the_sheet_marks_it():
    """Place pneumatic markers at the rendered positions."""
    fs = _pneumatic_sheet()
    root = _model(fs, check=False)
    cells = {c.get("id"): c for c in root.findall("mxCell")}
    marks = pneumatic_marks(stream_polyline(fs.streams[0]))
    assert marks, "the fixture stopped exercising the hatch"
    hatches = [c for c in cells.values() if c.get("parent") == "s0"]
    # Two strokes per mark, in the same places the sheet strokes them.
    assert len(hatches) == 2 * len(marks)
    for hatch in hatches:
        style = _style(hatch)
        assert style["shape"] == "line"
        geo = hatch.find("mxGeometry")
        assert geo.get("relative") == "1"
        assert -1.0 <= float(geo.get("x")) <= 1.0
        # mxGraph puts a relative child's top-left on its point; the offset adds the half-size.
        offset = geo.find('mxPoint[@as="offset"]')
        assert offset is not None
        half = float(geo.get("width")) / 2
        assert abs(float(offset.get("x")) + half) <= 3 or abs(float(offset.get("y")) + half) <= 3
    assert "dashed" not in _style(cells["s0"])


def _svg_hatch_strokes(fs: Flowsheet) -> list[tuple[float, float]]:
    """Return the angle and length of each SVG hatch stroke."""
    body = fs.to_svg(check=False).split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    strokes = []
    for found in re.finditer(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body
    ):
        x1, y1, x2, y2 = map(float, found.groups())
        strokes.append((math.degrees(math.atan2(y2 - y1, x2 - x1)), math.hypot(x2 - x1, y2 - y1)))
    return strokes


def test_the_svg_hatch_is_drawn_from_hatch_arm(monkeypatch):
    """Check that the SVG hatch strokes follow ``HATCH_ARM``."""
    fs = _pneumatic_sheet()
    along, across = HATCH_ARM
    assert {round(length, 1) for _, length in _svg_hatch_strokes(fs)} == {
        round(2 * math.hypot(along, across), 1)
    }
    monkeypatch.setattr("pandid.render.svg.HATCH_ARM", (along, 2 * across))
    assert {round(length, 1) for _, length in _svg_hatch_strokes(fs)} == {
        round(2 * math.hypot(along, 2 * across), 1)
    }


def test_the_hatch_stroke_is_the_same_in_both_backends():
    """Check that draw.io hatch strokes have the SVG strokes' angle and length."""
    fs = _pneumatic_sheet()
    svg_strokes = _svg_hatch_strokes(fs)
    assert svg_strokes, "the fixture stopped exercising the hatch"
    hatches = [c for c in _model(fs, check=False).findall("mxCell") if c.get("parent") == "s0"]
    assert len(hatches) == len(svg_strokes)
    for (angle, length), hatch in zip(svg_strokes, hatches):
        style = _style(hatch)
        scale = float(style["strokeWidth"]) / LineWeight.DETAIL.width
        assert float(style["rotation"]) == pytest.approx(angle, abs=0.5)
        geo = hatch.find("mxGeometry")
        assert geo is not None
        assert float(geo.get("width", "nan")) / scale == pytest.approx(length, abs=0.2)


@pytest.mark.parametrize(
    ("dasharray", "pattern"),
    [
        ("8,4", "8 4"),
        ("7, 4", "7 4"),
        ("7 ,  4", "7 4"),
        ("9 3,2 3", "9 3 2 3"),
        ("none", None),
    ],
)
def test_a_dash_draws_in_drawio_as_the_svg_draws_it(dasharray, pattern):
    """Read a dash as SVG does: any comma and space separate, ``none`` is solid."""
    fs = Flowsheet("dashes")
    a = fs.add(units.Tank("T-1"))
    b = fs.add(units.Tank("T-2"))
    a.pin(x=100, y=100)
    b.pin(x=500, y=100)
    fs.connect(a.outlet, b.inlet).dasharray = dasharray
    fs.route()
    style = _style(_cells(fs, check=False)["s0"])
    assert style.get("dashPattern") == pattern
    assert ("dashed" in style) == (pattern is not None)
    assert style.get("fixDash") == ("1" if pattern else None)


def test_a_turned_cell_pins_which_anchor_algorithm_reads_its_fractions():
    """Use the anchor algorithm matching the placed cell bounds."""
    style = _one_unit(units.Pump("P-1"), x=100, y=100, orientation=90)
    assert style["direction"] == "south"
    assert style["anchorPointDirection"] == "0"
    assert style["legacyAnchorPoints"] == "1"


def test_the_backend_is_a_renderer_in_its_own_right(sample):
    """Expose the Draw.io backend through the renderer interface."""
    assert DrawioRenderer().render(sample) == sample.to_drawio(check=False)


def test_a_far_coordinate_is_written_in_full():
    """Write a coordinate past a million fixed-point, as the SVG does."""
    fs = Flowsheet("far")
    a = fs.add(units.Feed("F-1")).pin(x=1234567, y=100)
    b = fs.add(units.Product("P-1")).pin(x=1234867, y=100)
    fs.connect(a.outlet, b.inlet)
    fs.route()
    document = fs.to_drawio(check=False)
    assert not re.search(r'"-?[\d.]+e[+-]\d+"', document), "a number in exponent notation"
    xs = [float(g.get("x", "0")) for g in _drawio_root(document).iter("mxGeometry")]
    assert max(xs) > 1_234_000, "the pinned coordinates did not reach the file"


# The geometry, against the renderer's.


def _cells(fs: Flowsheet, **kwargs) -> dict[str, ET.Element]:
    """Index exported cells by identifier."""
    return {cell.get("id"): cell for cell in _model(fs, **kwargs).findall("mxCell")}


def _style(cell: ET.Element) -> dict[str, str]:
    """Parse the key-value pairs in a cell style."""
    out = {}
    for key in cell.get("style", "").split(";"):
        if key:
            name, _, value = key.partition("=")
            out[name] = value
    return out


def stream_end(port) -> tuple[float, float]:
    """Locate the endpoint drawn at a port."""
    unit = port.owner
    if unit.kind == "tee":
        x0, y0, x1, y1 = cell_box(unit)
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    return port_point(unit, unit.frame, port.name)


def cell_box(unit) -> tuple[float, float, float, float]:
    """Locate the exported rectangle for a unit."""
    if unit.kind in ("feed", "product"):
        return boundary_flag(unit, unit.frame).box
    return unit_box(unit, unit.frame)


def _drawio_connection_point(unit, vertex: dict, edge: dict, prefix: str) -> tuple[float, float]:
    """Resolve a fixed connection point from Draw.io styles."""
    assert edge[f"{prefix}Perimeter"] == "0"
    if "direction" in vertex:
        assert vertex["anchorPointDirection"] == "0", (
            "a turned shape turns its anchors with it unless told not to"
        )
    x0, y0, x1, y1 = cell_box(unit)
    fx, fy = float(edge[f"{prefix}X"]), float(edge[f"{prefix}Y"])
    if vertex.get("flipH") == "1":
        fx = 1.0 - fx
    if vertex.get("flipV") == "1":
        fy = 1.0 - fy
    return (x0 + fx * (x1 - x0), y0 + fy * (y1 - y0))


@pytest.mark.parametrize("orientation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirrored", [False, True, "y", "xy"])
def test_a_connection_point_resolves_back_onto_its_nozzle(orientation, mirrored):
    """Match fixed connection points to nozzles in every orientation."""
    fs = Flowsheet("placements")
    vessel = fs.add(units.Vessel("V-101", variant="dished"))
    feed = fs.add(units.Feed("F"))
    product = fs.add(units.Product("P"))
    vessel.pin(x=400, y=200, orientation=orientation, mirrored=mirrored)
    feed.pin(x=60, y=200)
    product.pin(x=900, y=200)
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, product.inlet)
    fs.route()

    cells = _cells(fs, check=False)
    at = {id(u): _style(cells[f"u{i}"]) for i, u in enumerate(fs.units)}
    for n, s in enumerate(fs.streams):
        style = _style(cells[f"s{n}"])
        for prefix, port in (("exit", s.source), ("entry", s.dest)):
            landed = _drawio_connection_point(port.owner, at[id(port.owner)], style, prefix)
            drawn = port_point(port.owner, port.owner.frame, port.name)
            assert landed == pytest.approx(drawn, abs=0.01), (
                f"{port.owner.name}.{port.name} {orientation=} {mirrored=} {prefix}"
            )


def test_a_feed_pinned_to_a_stage_resolves_to_the_same_point_in_both_backends():
    """Match a pinned stage feed connection across both renderers."""
    fs = Flowsheet("stage")
    col = fs.add(
        units.Column("T-101", internals="valve_tray", trays=30, n_feeds=2, feed_stages=[12, 22])
    )
    col.pin(x=400, y=200)
    solvent = fs.add(units.Feed("Solvent")).pin(x=60, y=180)
    feed = fs.add(units.Feed("Feed")).pin(x=60, y=240)
    fs.connect(solvent.outlet, col.feed_1)
    fs.connect(feed.outlet, col.feed_2)
    fs.route()

    cells = _cells(fs, check=False)
    style = _style(cells["u0"])
    for n, port_name in enumerate(("feed_1", "feed_2")):
        entry = _style(cells[f"s{n}"])
        landed = _drawio_connection_point(col, style, entry, "entry")
        drawn = port_point(col, col.frame, port_name)
        assert landed == pytest.approx(drawn, abs=0.01)


# What the style says about a placement.


def _one_unit(unit, **pin) -> dict[str, str]:
    """Export the style of a single placed unit."""
    fs = Flowsheet("one")
    fs.add(unit)
    if pin:
        unit.pin(**pin)
    fs.layout()
    return _style(_cells(fs, check=False)["u0"])


@pytest.mark.parametrize(
    "orientation,direction", [(0, None), (90, "south"), (180, "west"), (270, "north")]
)
def test_a_quarter_turn_exports_as_the_direction_it_turns_to(orientation, direction):
    """Export a clockwise quarter turn as the direction the shape's east ends up facing."""
    style = _one_unit(units.Pump("P-1"), x=100, y=100, orientation=orientation)
    assert style.get("direction") == direction


def test_a_mirror_exports_as_a_flip():
    """Export a mirrored unit with its flip style."""
    style = _one_unit(units.Pump("P-1"), x=100, y=100, mirrored="xy")
    assert style.get("flipH") == "1" and style.get("flipV") == "1"


def test_a_directional_symbol_is_never_flipped():
    """Keep directional artwork unflipped while moving its nozzles."""
    directional = [(k, v) for (k, v), s in default_registry._symbols.items() if s.directional]
    assert directional, "no directional symbol left to check this against"
    for kind, variant in directional:
        cls = next(getattr(units, n) for n in units.__all__ if getattr(units, n).kind == kind)
        style = _one_unit(cls("X-1", variant=variant), x=100, y=100, mirrored="xy")
        assert "flipH" not in style and "flipV" not in style, (
            f"{kind}/{variant} states a direction in its artwork and was exported flipped"
        )


def test_a_normally_closed_valve_exports_its_body_filled():
    """Fill the body of a normally closed valve."""
    style = _one_unit(units.Valve("HV-1", variant="gate", normal_position="closed"), x=100, y=100)
    assert style["shape"] == "mxgraph.pid.valves.gate_valve"
    assert style["fillColor"] == "#111"


def test_an_expander_exports_its_stencil_mirrored():
    """Mirror reducer artwork when exporting an expander."""
    reduction = _one_unit(units.Reducer("R-1", large_end="inlet"), x=100, y=100)
    expansion = _one_unit(units.Reducer("R-2", large_end="outlet"), x=100, y=100)
    assert reduction["shape"] == expansion["shape"]
    assert "flipH" not in reduction
    assert expansion["flipH"] == "1"


def test_a_balloon_carries_its_letters_over_its_number():
    """Place instrument letters above the balloon number."""
    fs = Flowsheet("balloon")
    ft = fs.add_instrument("FT", 101)
    ft.pin(x=100, y=100)
    fs.layout()
    cell = _cells(fs, check=False)["u0"]
    assert cell.get("value") == "FT<br>101"
    style = _style(cell)
    assert style["shape"] == "ellipse"
    # Opaque, so the line a balloon is drawn over does not run through its tag.
    assert style["fillColor"] == "#ffffff"


def test_only_the_balloons_are_drawn_opaque():
    """Use opaque fill only for built-in balloon shapes."""
    from pandid.render.drawio import _APPROXIMATIONS as table

    for (kind, variant), approx in table.items():
        expected = "#ffffff" if kind == "instrument" else "none"
        assert approx.fill == expected, f"{kind}/{variant} fills with {approx.fill!r}"


def test_a_vendored_stencil_exports_on_the_paper():
    """Fill vendored shapes with the page colour where required."""
    style = _one_unit(units.Tank("V-1", variant="sphere"), x=100, y=100)
    assert style["shape"] == "mxgraph.pid.vessels.storage_sphere"
    assert style["fillColor"] == "#ffffff"


def test_a_mirrored_expander_is_the_reducer_drawn_as_vendored():
    """Compose reducer direction and mirror without moving its nozzles."""
    style = _one_unit(units.Reducer("R-1", large_end="outlet"), x=100, y=100, mirrored=True)
    assert "flipH" not in style


@pytest.mark.parametrize("variant", ["sis", "logic"])
def test_a_trip_balloon_keeps_the_square_around_its_diamond(variant):
    """Retain the safety-system square around a trip balloon."""
    art = default_registry.get("instrument", variant).svg
    assert art.count("<rect") == 1 and art.count("<polygon") == 1, (
        "the sheet has stopped drawing this as a square with a diamond in it"
    )

    fs = Flowsheet("trip")
    fs.add(units.Instrument("Z", 301, variant=variant)).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, check=False)
    square, diamond = cells["u0"], cells["u0-in"]
    # The square is the cell: it carries the number and is draw.io's default vertex.
    assert "shape" not in _style(square)
    assert _style(square)["rounded"] == "0"
    assert square.get("value") == "301"
    assert _style(square)["fillColor"] == "#ffffff", "a balloon is opaque"

    # The diamond is inscribed in it, is scenery, and draws no second fill.
    assert diamond.get("parent") == "u0"
    assert _style(diamond)["shape"] == "rhombus"
    assert _style(diamond)["fillColor"] == "none"
    assert _style(diamond)["connectable"] == "0"
    assert _style(diamond)["movable"] == "0"
    box = square.find("mxGeometry")
    inner = diamond.find("mxGeometry")
    assert (inner.get("x"), inner.get("y")) == ("0", "0")
    assert inner.get("width") == box.get("width")
    assert inner.get("height") == box.get("height")

    # The plain interlock remains a bare diamond on the sheet.
    plain = Flowsheet("interlock")
    plain.add(units.Instrument("Z", 302, variant="interlock")).pin(x=100, y=100)
    plain.layout()
    bare = _cells(plain, check=False)
    assert _style(bare["u0"])["shape"] == "rhombus"
    assert bare["u0"].get("value") == "302"
    assert "u0-in" not in bare


def test_a_unit_from_outside_the_package_exports_as_the_box_it_draws(gapped_kind):
    """Export an unknown unit as the generic box drawn by the sheet."""
    fs = Flowsheet("foreign")
    unit = fs.add(gapped_kind("X-1"))
    unit.pin(x=100, y=100)
    fs.layout()
    style = _style(_cells(fs, check=False)["u0"])
    assert "shape" not in style
    assert style["rounded"] == "0"


def test_an_empty_flowsheet_still_exports_a_document():
    """Export a valid document for an empty flowsheet."""
    root = _model(Flowsheet("empty"), check=False)
    assert [c.get("id") for c in root.findall("mxCell")] == ["0", "1"]


def test_a_repeated_tag_gets_a_cell_of_its_own():
    """Give each occurrence of a repeated tag its own cell."""
    fs = Flowsheet("repeats")
    for n in range(3):
        square = fs.add(units.Instrument("Z", 1, variant="interlock"))
        square.pin(x=100 + 120 * n, y=100)
    fs.layout()
    root = _model(fs, check=False)
    ids = [c.get("id") for c in root.findall("mxCell")]
    assert len(ids) == len(set(ids))
    assert len(ids) == 2 + 3


# Streams: weight, dash and arrowhead.


def test_a_signal_line_is_dashed_and_drawn_half_the_weight_of_pipe(sample):
    """Draw signal lines dashed and half the material-line weight."""
    cells = _cells(sample)
    weights = {}
    for n, s in enumerate(sample.streams):
        weights[s.kind] = _style(cells[f"s{n}"])
    # Use the fixed 0.2 M and 0.1 M width ladder as an independent oracle.
    assert weights["material"]["strokeWidth"] == "2"
    assert weights["electric"]["strokeWidth"] == "1"
    assert weights["electric"]["dashed"] == "1"
    assert weights["electric"]["dashPattern"] == "7 4"
    assert "dashed" not in weights["material"]
    assert weights["material"]["strokeColor"] == "#000000"


def test_a_pfd_exports_arrowheads_and_a_p_and_id_does_not(sample):
    """Show stream arrowheads only on process flow diagrams."""
    pfd = _cells(sample, diagram="pfd")
    pid = _cells(sample, diagram="p&id")
    heads = [
        _style(pfd[f"s{n}"]).get("endArrow")
        for n, s in enumerate(sample.streams)
        if s.kind == "material"
    ]
    assert "block" in heads, "a PFD draws the flow direction with an arrowhead"
    for n, s in enumerate(sample.streams):
        assert _style(pid[f"s{n}"])["endArrow"] == "none"


def test_a_stream_number_is_written_once_however_many_segments_carry_it(sample):
    """Write each stream number once, however many segments carry it."""
    cells = _cells(sample)
    labels = [cells[f"s{n}"].get("value") for n in range(len(sample.streams))]
    written = [label for label in labels if label]
    assert len(written) == len(set(written)), f"a number written twice: {written}"
    assert set(written) == {s.name for s in sample.streams if s.kind == "material"}


def _drawio_edge_label(points, geometry) -> tuple[float, float]:
    """Resolve an edge label along its routed polyline."""
    lengths = [((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 for p, q in zip(points, points[1:])]
    total = sum(lengths)
    gx = float(geometry.get("x") or 0.0) / 2
    dist = round((gx + 0.5) * total)
    walked, index, segment = 0.0, 1, lengths[0]
    while dist >= round(walked + segment) and index < len(points) - 1:
        walked += segment
        segment = lengths[index]
        index += 1
    factor = (dist - walked) / segment if segment else 0.0
    p0, pe = points[index - 1], points[index]
    offset = geometry.find("mxPoint[@as='offset']")
    dx = float(offset.get("x")) if offset is not None else 0.0
    dy = float(offset.get("y")) if offset is not None else 0.0
    return (p0[0] + (pe[0] - p0[0]) * factor + dx, p0[1] + (pe[1] - p0[1]) * factor + dy)


def test_a_line_number_is_written_where_the_sheet_writes_it(settled_gallery, rendered_gallery):
    """Match exported line-number positions to the sheet."""
    from pandid.render.drawio import _tag_pass
    from pandid.render.svg import sheet_connections, stream_numbers

    for stem in LINE_NUMBER_SHEETS:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        cells = _gallery_cells(rendered_gallery, stem)
        _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
        plates = _tag_pass(fs, None, "vertical").plates
        # The sheet's own joints: a flange mark is ink the number search dodges.
        joints = sheet_connections(kwargs.get("diagram"), kwargs.get("connections"))
        wanted = {number.name: number for number in stream_numbers(fs, plates, joints, "vertical")}
        checked = 0
        for n, s in enumerate(fs.streams):
            cell = cells[f"s{n}"]
            name = cell.get("value") or ""
            if not name:
                continue
            landed = _drawio_edge_label(
                [fit.at(*p) for p in stream_polyline(s)], cell.find("mxGeometry")
            )
            number = wanted[name]
            # Half a unit, which is `Math.round(dist)` and nothing else.
            assert landed == pytest.approx(fit.at(number.x, number.y), abs=0.6), (
                f"{stem}: {name} lands at {landed}, not where the sheet writes it"
            )
            # Written on an opaque halo, as the sheet writes it.
            assert _style(cell)["labelBackgroundColor"] == "#ffffff"
            checked += 1
        assert checked or not [s for s in fs.streams if s.kind == "material"]


def test_every_letter_code_the_sheet_writes_outside_a_balloon_is_exported(
    settled_gallery, rendered_gallery
):
    """Export each function code beside its instrument balloon."""
    from pandid.render.drawio import _TEXT_INSET
    from pandid.render.svg import quadrant_labels

    written, counted = {}, {}
    for stem in INSTRUMENT_CODE_SHEETS:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        svg = rendered_gallery[stem].svg
        cells = _gallery_cells(rendered_gallery, stem)
        _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
        codes = quadrant_labels(fs, "vertical")
        written[stem] = {item[5] for item in codes}
        counted[stem] = len(codes)
        for n, (lx, ly, anchor, _baseline, _lpos, text) in enumerate(codes):
            assert f">{text}</text>" in svg, f"{stem}: the sheet letters no {text}"
            cell = cells.get(f"q{n}")
            assert cell is not None, f"{stem}: {text} reached no cell in the export"
            assert cell.get("value") == html.unescape(text)
            style = _style(cell)
            geometry = cell.find("mxGeometry")
            x, y = float(geometry.get("x")), float(geometry.get("y"))
            w, h = float(geometry.get("width")), float(geometry.get("height"))
            # Remove Draw.io's two-unit inset before comparing label anchors.
            edge = x + w - _TEXT_INSET if style["align"] == "right" else x + _TEXT_INSET
            assert (edge, y + h / 2) == pytest.approx(fit.at(lx, ly), abs=0.01), (
                f"{stem}: {text} is exported out of its quadrant"
            )
            # A code beside a balloon is haloed, as the sheet haloes it.
            assert style["labelBackgroundColor"] == "#ffffff"

    # Assert the code population as well as parity between both renderers.
    assert counted == {
        "03_control_loop": 2,
        "10_ethanol_pid": 6,
        "13_tank_farm": 5,
    }, counted
    # Check identities as well as counts on the affected sheets.
    assert written["10_ethanol_pid"] == {"PAH", "PAL", "TAH", "TAL", "LAH", "LAL"}
    assert written["03_control_loop"] == {"LAH", "LAL"}
    assert written["13_tank_farm"] == {"LAH", "LAL", "PAH"}


def _exported_codes(fs, kwargs) -> tuple:
    """Return each exported letter code with the page box its halo paints, and the fit."""
    from pandid.render.drawio import _TEXT_INSET

    cells = _drawio_cells_from_document(fs.to_drawio(**kwargs))
    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    codes = []
    for cid, cell in cells.items():
        if not re.fullmatch(r"q\d+", cid or ""):
            continue
        geometry = cell.find("mxGeometry")
        assert geometry is not None
        x, y = float(geometry.get("x", 0)), float(geometry.get("y", 0))
        w, h = float(geometry.get("width", 0)), float(geometry.get("height", 0))
        # The halo fills the cell inside draw.io's text inset.
        inset = _TEXT_INSET
        codes.append((cell.get("value"), (x + inset, y + inset, x + w - inset, y + h - inset)))
    assert codes, "the sheet exports no letter code"
    return codes, fit


def test_a_letter_code_is_exported_clear_of_a_flange_mark():
    """Export each letter code clear of the flange marks on its sheet."""
    from test_halo_invariants import _flange_bars
    from test_label_invariants import CORPUS

    fs, kwargs = CORPUS["codes_beside_a_flange"]()
    codes, fit = _exported_codes(fs, kwargs)
    faces = [fit.box(face.box) for face in _flange_bars(fs, kwargs)]
    hit = [text for text, box in codes for face in faces if overlaps(box, face)]
    assert not hit, f"letter codes exported over a flange mark: {hit}"


@pytest.mark.parametrize(
    "sheet",
    [
        "a_flange_and_a_line",
        "a_fixed_tag",
        "another_balloon",
        "a_closed_valve",
        "a_pneumatic_line",
        "a_stacked_tag",
    ],
)
def test_a_letter_code_by_a_flange_mark_is_exported_clear_of_every_line_and_tag(sheet):
    """Export a letter code by a flange mark clear of every line, hatch and tag label."""
    from pandid.render.svg import _ink
    from test_halo_invariants import CROWDED_CODES, _hatch_bars

    fs, kwargs = CROWDED_CODES[sheet]()
    codes, fit = _exported_codes(fs, kwargs)
    _symbols, tags, _numbers = _drawn_boxes(
        fs, kwargs, _drawio_cells_from_document(fs.to_drawio(**kwargs))
    )
    marks = [fit.box(line.box) for line in _ink(fs, "vertical")]
    marks += [fit.box(bar) for bar in _hatch_bars(fs)] + list(tags.values())
    hit = [text for text, box in codes for mark in marks if overlaps(box, mark)]
    assert not hit, f"letter codes exported over a line or tag: {hit}"


def _titled() -> Flowsheet:
    """Build a sheet with a populated title block."""
    from pandid.document import Revision, TitleBlock

    fs = Flowsheet("titled")
    pump = fs.add(units.Pump("P-101"))
    pump.pin(x=100, y=100)
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        drawing_number="A-301",
        client="Acme",
        revisions=[Revision(rev="A", date="2026-01-02", description="Issued")],
    )
    fs.layout()
    return fs


def test_a_title_block_carries_every_field_in_a_cell_of_its_own():
    """Give every title-block field an editable cell."""
    cells = _cells(_titled(), check=False)
    values = {c.get("value") for c in cells.values()}
    assert {"REV", "DATE", "DESCRIPTION"} <= values, "the revision grid lost its headings"
    assert {"A", "2026-01-02", "Issued"} <= values, "a revision row was flattened"
    assert {"A-301", "Acme", "Ethanol Purification"} <= values, "a field was dropped"
    for cell in cells.values():
        assert "<br>" not in (cell.get("value") or ""), (
            f"{cell.get('id')} is a text blob: {cell.get('value')!r}"
        )


def test_the_title_strip_carries_the_same_ink_the_sheet_rules():
    """Match title-strip text and rules to the rendered sheet."""
    import html
    import re

    from pandid.render import furniture as F
    from pandid.render.drawio import _BASELINE, _TEXT_INSET

    block = _titled().title_block
    x, y, w, h = 400.0, 300.0, *F.measure_title_strip(block)
    sheet = "\n".join(F.draw_title_strip(block, "titled", "2026-01-02", x + w, y + h, "1:1"))
    root = ET.fromstring(
        "<root>"
        + "\n".join(
            DrawioRenderer()._title_strip("t", block, x, y, w, h, "titled", "2026-01-02", "1:1")
        )
        + "</root>"
    )
    cells = list(root.iter("mxCell"))

    # --- every rule the sheet strokes -------------------------------------
    emitted = set()
    for cell in cells:
        src = cell.find("mxGeometry/mxPoint[@as='sourcePoint']")
        dst = cell.find("mxGeometry/mxPoint[@as='targetPoint']")
        if src is None or dst is None:
            continue
        emitted.add(
            (
                round(float(src.get("x")), 1),
                round(float(src.get("y")), 1),
                round(float(dst.get("x")), 1),
                round(float(dst.get("y")), 1),
            )
        )
    # The revision table draws column rules from its cell geometry.
    table = next(c for c in cells if "shape=table;" in (c.get("style") or ""))
    geo = table.find("mxGeometry")
    stops, at = set(), float(geo.get("x"))
    for cell in cells:
        if _style(cell).get("shape") != "partialRectangle":
            continue
        stops.add(round(at + float(cell.find("mxGeometry").get("x")), 1))
    stops.add(round(at + float(geo.get("width")), 1))
    for line in re.finditer(
        r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', sheet
    ):
        rule = tuple(round(float(v), 1) for v in line.groups())
        if rule in emitted or (rule[0] == rule[2] and rule[0] in stops):
            continue
        raise AssertionError(f"the export does not rule {rule}")

    # Compare SVG baselines with Draw.io boxes using their text offsets.
    written = []
    for cell in cells:
        value, style = cell.get("value") or "", _style(cell)
        if not value or "fontSize" not in style:
            continue
        box = cell.find("mxGeometry")
        cw = float(box.get("width"))
        size = float(style["fontSize"])
        if style.get("shape") == "partialRectangle":  # a revision cell
            row = next(c for c in cells if c.get("id") == cell.get("id").rsplit("-", 1)[0])
            top = float(geo.get("y")) + float(row.find("mxGeometry").get("y"))
            depth = float(row.find("mxGeometry").get("height"))
            left = at + float(box.get("x"))
            written.append(
                (value, size, left + F._REV_PAD, top + depth / 2 + size * (_BASELINE - 0.6))
            )
            continue
        top, left = float(box.get("y")), float(box.get("x"))
        align = style.get("align", "center")
        anchored = (
            left + _TEXT_INSET
            if align == "left"
            else left + cw - _TEXT_INSET
            if align == "right"
            else left + cw / 2
        )
        written.append((value, size, anchored, top + _TEXT_INSET + _BASELINE * size))

    for text in re.finditer(
        r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*font-size="([\d.]+)"[^>]*>([^<]*)</text>', sheet
    ):
        # Compare decoded text because SVG and XML escape apostrophes differently.
        tx, ty, size, value = (
            float(text.group(1)),
            float(text.group(2)),
            float(text.group(3)),
            html.unescape(text.group(4)),
        )
        if not value:  # a blank revision cell inks nothing at either end
            continue
        near = [
            c
            for c in written
            if c[0] == value
            and abs(c[1] - size) < 0.01
            and abs(c[2] - tx) <= 2.5
            and abs(c[3] - ty) <= 1.5
        ]
        assert near, f"{value!r} at {tx},{ty} size {size} is not written by the export"


def test_a_table_rules_rows_and_cells_that_add_up_to_it():
    """Make table rows and cells span their parent bounds."""
    cells = _cells(_titled(), check=False)
    tables = [c for c in cells.values() if "shape=table;" in (c.get("style") or "")]
    assert tables, "the title block exported no table at all"
    for table in tables:
        tid = table.get("id")
        geo = table.find("mxGeometry")
        width, height = float(geo.get("width")), float(geo.get("height"))
        start = float(_style(table).get("startSize", 0))
        rows = [c for c in cells.values() if c.get("parent") == tid]
        assert rows, f"{tid} has no rows"
        top = start
        for row in rows:
            rgeo = row.find("mxGeometry")
            assert _style(row)["shape"] == "tableRow"
            # A row's y is measured from the table's top-left; a row spans the table.
            assert float(rgeo.get("y")) == pytest.approx(top, abs=0.01)
            assert float(rgeo.get("width")) == pytest.approx(width, abs=0.01)
            rh = float(rgeo.get("height"))
            cs = [c for c in cells.values() if c.get("parent") == row.get("id")]
            assert cs, f"{row.get('id')} has no cells"
            x = 0.0
            for cell in cs:
                cgeo = cell.find("mxGeometry")
                assert _style(cell)["shape"] == "partialRectangle"
                assert float(cgeo.get("x")) == pytest.approx(x, abs=0.01)
                assert float(cgeo.get("height")) == pytest.approx(rh, abs=0.01)
                x += float(cgeo.get("width"))
                # TableLayout uses alternateBounds to retain authored column widths.
                alt = cgeo.find("mxRectangle")
                assert alt is not None and alt.get("as") == "alternateBounds"
                assert float(alt.get("width")) == pytest.approx(float(cgeo.get("width")), abs=0.01)
            assert x == pytest.approx(width, abs=0.01), (
                f"{row.get('id')}'s cells span {x} of a {width} row"
            )
            top += rh
        assert top == pytest.approx(height, abs=0.01), (
            f"{tid}'s rows span {top} of a {height} table"
        )


@pytest.mark.parametrize("nrows", range(1, 13))
def test_a_tables_parts_add_up_at_the_precision_they_are_written_at(nrows):
    """Make serialized row dimensions sum to the table dimensions."""
    from pandid.document import Annotation

    fs = Flowsheet(f"rows{nrows}")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.annotations.append(
        Annotation(
            title="SCHEDULE", align="top-right", rows=[(f"T-{i}", "Tank") for i in range(nrows)]
        )
    )
    fs.layout()
    cells = _cells(fs, check=False)
    table = next(c for c in cells.values() if "shape=table;" in (c.get("style") or ""))
    geo = table.find("mxGeometry")
    # Sum serialized dimensions as decimals to preserve their precision.
    height = Decimal(geo.get("height"))
    start = Decimal(_style(table).get("startSize", "0"))
    rows = [c for c in cells.values() if c.get("parent") == table.get("id")]
    assert len(rows) == nrows
    spanned = start + sum((Decimal(r.find("mxGeometry").get("height")) for r in rows), Decimal(0))
    assert spanned == height, f"{nrows} rows span {spanned} of a {height} table"
    for row in rows:
        width = Decimal(row.find("mxGeometry").get("width"))
        cs = [c for c in cells.values() if c.get("parent") == row.get("id")]
        assert sum((Decimal(c.find("mxGeometry").get("width")) for c in cs), Decimal(0)) == width


#: Gallery render options that ``to_drawio`` accepts.
_DRAWIO_KWARGS = (
    "diagram",
    "page_size",
    "border",
    "show_stream_table",
    "connections",
    "crossing_style",
)


def _drawio_cells(fs, kwargs) -> dict:
    """Export a sheet with its gallery options and index its cells."""
    return _drawio_cells_from_document(fs.to_drawio(**_drawio_options(kwargs)))


def _drawio_options(kwargs: dict) -> dict:
    """Select gallery options implemented by the Draw.io renderer."""
    return {key: value for key, value in kwargs.items() if key in _DRAWIO_KWARGS}


def _drawio_root(document: str) -> ET.Element:
    """Read the graph root from an exported Draw.io document."""
    root = ET.fromstring(document).find("diagram/mxGraphModel/root")
    assert root is not None, "the Draw.io document has no graph root"
    return root


def _drawio_furniture(fs, kwargs):
    """Build furniture with the export options used by the gallery."""
    return DrawioRenderer()._furniture(
        fs, _page(kwargs.get("page_size")), bool(kwargs.get("show_stream_table", False))
    )


def _cell_font(cell) -> float:
    """Read the font size declared on a table cell."""
    size = _style(cell).get("fontSize")
    assert size is not None, f"{cell.get('id')} states no fontSize of its own"
    return float(size)


def _table_cells(cells):
    """Yield text cells with their containing rows and tables."""
    for cell in cells.values():
        if _style(cell).get("shape") != "partialRectangle":
            continue
        if not (cell.get("value") or ""):
            continue
        row = cells[cell.get("parent")]
        yield cell, row, cells[row.get("parent")]


def _clipped(cells) -> list[str]:
    """Find table cells whose text exceeds their column width."""
    from pandid.render.furniture import text_width

    out = []
    for cell, _row, _table in _table_cells(cells):
        value = cell.get("value")
        need = text_width(value, _cell_font(cell), _style(cell).get("fontStyle") == "1")
        width = float(cell.find("mxGeometry").get("width"))
        if need > width:
            out.append(f"{cell.get('id')} {value!r} needs {need:.1f} of {width:.1f}")
    return out


def test_no_table_cell_is_narrower_than_the_text_in_it(rendered_gallery):
    """Size table columns to contain their rendered text."""
    for stem in TABLE_REPRESENTATIVES:
        cells = _gallery_cells(rendered_gallery, stem)
        assert list(_table_cells(cells)), f"{stem} carries no table"
        clipped = _clipped(cells)
        assert not clipped, f"{stem}: " + "; ".join(clipped)


def test_no_table_row_is_shorter_than_the_line_box_of_its_own_text(rendered_gallery):
    """Size table rows to contain their text line boxes."""
    from pandid.render.drawio import _line_box

    for stem in TABLE_REPRESENTATIVES:
        for cell, row, _table in _table_cells(_gallery_cells(rendered_gallery, stem)):
            box = _line_box(_cell_font(cell))
            height = float(row.find("mxGeometry").get("height"))
            assert box <= height + 0.01, f"{stem}: {cell.get('id')} {box:.2f} > {height:.2f}"


def test_no_furniture_text_is_drawn_under_the_frames_own_rule(rendered_gallery):
    """Keep furniture text clear of the page frame."""
    from pandid.render.drawio import _line_box

    for stem in TABLE_REPRESENTATIVES:
        cells = _gallery_cells(rendered_gallery, stem)
        frame = cells.get("z-frame")
        if frame is None:  # an unruled sheet has no frame to be drawn under
            continue
        geometry = frame.find("mxGeometry")
        paper = (
            float(geometry.get("y"))
            + float(geometry.get("height"))
            - float(_style(frame)["strokeWidth"]) / 2
        )
        for cell, row, table in _table_cells(cells):
            top = float(table.find("mxGeometry").get("y")) + float(row.find("mxGeometry").get("y"))
            height = float(row.find("mxGeometry").get("height"))
            # Centred in its row, which is what verticalAlign=middle does.
            ink = top + height - (height - _line_box(_cell_font(cell))) / 2
            assert ink <= paper + 0.01, f"{stem}: {cell.get('id')} {ink:.2f} > {paper:.2f}"


def _legend_sheet() -> Flowsheet:
    """Build a sheet whose box has a long first column, a plain row and a wide title."""
    from pandid.document import Annotation

    fs = Flowsheet("legend")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.annotations.append(
        Annotation(
            title="A TITLE WIDER THAN EVERY ROW BENEATH IT, BY SOME WAY",
            align="top-left",
            rows=[("Cooling water supply header and return", "CWS"), "A plain note"],
        )
    )
    fs.layout()
    return fs


def test_annotation_text_starts_in_drawio_where_the_sheet_writes_it():
    """Start each annotation cell's text at the sheet's column stop."""
    from pandid.render.drawio import _TEXT_INSET

    fs = _legend_sheet()
    svg = fs.to_svg(check=False)
    cells = _cells(fs, check=False)
    seen = 0
    for cell, row, table in _table_cells(cells):
        geo, row_geo, table_geo = (e.find("mxGeometry") for e in (cell, row, table))
        assert geo is not None and row_geo is not None and table_geo is not None
        start = (
            float(table_geo.get("x", "0"))
            + float(row_geo.get("x", "0"))
            + float(geo.get("x", "0"))
            + float(_style(cell).get("spacingLeft", "0"))
            + _TEXT_INSET
        )
        value = cell.get("value", "")
        drawn = re.search(r'<text x="([-\d.]+)"[^>]*>' + re.escape(value) + "</text>", svg)
        assert drawn is not None, value
        assert start == pytest.approx(float(drawn.group(1)), abs=0.1), value
        bold = re.search(r'font-weight="bold"[^>]*>' + re.escape(value) + "<", svg) is not None
        assert (_style(cell).get("fontStyle") == "1") == bold, value
        seen += 1
    assert seen == 3


def test_tablebox_text_sits_in_drawio_where_the_sheet_writes_it():
    """Inset left- and right-aligned TableBox text as the sheet does."""
    from pandid.document import TableBox
    from pandid.render.drawio import _TEXT_INSET

    fs = Flowsheet("schedule")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.add_annotation(
        TableBox(
            title="SCHEDULE",
            headers=["Tag", "Duty"],
            rows=[["P-101A", "Feed pump"]],
            col_align=["l", "r"],
        )
    )
    fs.layout()
    svg = fs.to_svg(check=False)
    seen = 0
    for cell, row, table in _table_cells(_cells(fs, check=False)):
        geo, row_geo, table_geo = (e.find("mxGeometry") for e in (cell, row, table))
        assert geo is not None and row_geo is not None and table_geo is not None
        left = sum(float(g.get("x", "0")) for g in (table_geo, row_geo, geo))
        style = _style(cell)
        if style.get("align") == "right":
            right = left + float(geo.get("width", "0"))
            edge = right - float(style.get("spacingRight", "0")) - _TEXT_INSET
        else:
            edge = left + float(style.get("spacingLeft", "0")) + _TEXT_INSET
        value = cell.get("value", "")
        drawn = re.search(r'<text x="([-\d.]+)"[^>]*>' + re.escape(value) + "</text>", svg)
        assert drawn is not None, value
        assert edge == pytest.approx(float(drawn.group(1)), abs=0.1), value
        seen += 1
    assert seen == 4


def test_revision_text_sits_in_drawio_where_the_sheet_writes_it():
    """Inset each revision cell's text as the sheet does."""
    from pandid.render import furniture as F
    from pandid.render.drawio import _TEXT_INSET

    block = _titled().title_block
    assert block is not None
    x, y, w, h = 400.0, 300.0, *F.measure_title_strip(block)
    sheet = "\n".join(F.draw_title_strip(block, "titled", "2026-01-02", x + w, y + h, "1:1"))
    root = ET.fromstring(
        "<root>"
        + "\n".join(
            DrawioRenderer()._title_strip("t", block, x, y, w, h, "titled", "2026-01-02", "1:1")
        )
        + "</root>"
    )
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    # Compare decoded text because SVG and XML escape apostrophes differently.
    lettered = rf'<text x="([-\d.]+)"[^>]*font-size="{F._REV_TYPE:.1f}"[^>]*>([^<]*)</text>'
    drawn = {html.unescape(m.group(2)): float(m.group(1)) for m in re.finditer(lettered, sheet)}
    seen = set()
    for cell, row, table in _table_cells(cells):
        geo, row_geo, table_geo = (e.find("mxGeometry") for e in (cell, row, table))
        assert geo is not None and row_geo is not None and table_geo is not None
        left = sum(float(g.get("x", "0")) for g in (table_geo, row_geo, geo))
        start = left + float(_style(cell).get("spacingLeft", "0")) + _TEXT_INSET
        value = html.unescape(cell.get("value", ""))
        assert start == pytest.approx(drawn[value], abs=0.1), value
        seen.add(value)
    assert {"REV", "DATE", "DESCRIPTION", "A", "2026-01-02", "Issued"} <= seen


def test_a_bold_first_column_is_measured_bold():
    """Keep a long bold first cell clear of the column after it."""
    from pandid.render.furniture import text_width

    svg = _legend_sheet().to_svg(check=False)
    first = "Cooling water supply header and return"
    x0 = re.search(r'<text x="([-\d.]+)"[^>]*font-weight="bold"[^>]*>' + first, svg)
    x1 = re.search(r'<text x="([-\d.]+)"[^>]*>CWS</text>', svg)
    assert x0 is not None and x1 is not None
    assert float(x0.group(1)) + text_width(first, 11.0, bold=True) < float(x1.group(1))


def test_a_table_states_the_size_its_columns_were_measured_at():
    """Export table text at the font size used to measure columns."""
    from pandid.document import Annotation

    fs = Flowsheet("sized")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.annotations.append(
        Annotation(title="LEGEND", align="top-left", font_size=9.0, rows=[("SS", "316L")])
    )
    fs.layout()
    cells = _cells(fs, check=False)
    table = next(c for c in cells.values() if "shape=table;" in (c.get("style") or ""))
    assert _style(table)["fontSize"] == "10", "the title band is not the sheet's size"
    for cell, _row, _table in _table_cells(cells):
        assert _cell_font(cell) == 9.0, f"{cell.get('id')} is drawn at another size"


def test_the_title_block_rules_rows_deep_enough_to_draw_text_in():
    """Give title-block rows enough height for their text."""
    fs = _titled()
    cells = _cells(fs, check=False)
    rows = [c for c in cells.values() if _style(c).get("shape") == "tableRow"]
    assert rows
    for row in rows:
        height = float(row.find("mxGeometry").get("height"))
        assert height >= 11.0, f"{row.get('id')} is {height} units tall"


def test_the_title_strip_is_one_rectangle_flush_to_the_frame():
    """Align the title strip with the bottom-right frame corner."""
    from pandid.render import furniture as F

    fs = _titled()
    cells = _cells(fs, page_size="A3", border="zone", check=False)
    frame = cells["z-frame"].find("mxGeometry")
    fx, fy = float(frame.get("x")), float(frame.get("y"))
    fw, fh = float(frame.get("width")), float(frame.get("height"))
    strip = next(
        c
        for c in cells.values()
        if f"strokeWidth={F._STRIP_RULE:g};" in (c.get("style") or "")
        and c.get("id", "").startswith("f")
    )
    geo = strip.find("mxGeometry")
    sw, sh = F.measure_title_strip(fs.title_block)
    assert (float(geo.get("width")), float(geo.get("height"))) == pytest.approx((sw, sh))
    assert float(geo.get("x")) + sw == pytest.approx(fx + fw, abs=0.01)
    assert float(geo.get("y")) + sh == pytest.approx(fy + fh, abs=0.01)
    # The frame is ruled at the strip's weight.
    assert _style(cells["z-frame"])["strokeWidth"] == f"{F.FRAME_RULE:g}"


def test_the_revision_history_is_still_a_grid_a_reader_can_edit():
    """Keep revision history as editable table cells."""
    from pandid.render import furniture as F

    fs = _titled()
    cells = _cells(fs, check=False)
    table = next(
        c
        for c in cells.values()
        if "shape=table;" in (c.get("style") or "") and c.get("id", "").endswith("-rev")
    )
    style = _style(table)
    assert style["rowLines"] == "0", "the export rules between revisions; the sheet does not"
    assert style.get("columnLines", "1") != "0", "the revision columns lost their rules"

    rows = [
        c
        for c in cells.values()
        if _style(c).get("shape") == "tableRow" and c.get("parent") == table.get("id")
    ]
    rows.sort(key=lambda c: float(c.find("mxGeometry").get("y")))
    assert [c.get("value") for c in _row_cells(cells, rows[-1])] == [
        heading for heading, _w in _rev_cols()
    ], "the heading row is not at the foot"
    assert [c.get("value") for c in _row_cells(cells, rows[-2])] == [
        "A",
        "2026-01-02",
        "Issued",
        "",
        "",
        "",
    ], "the newest revision is not against the heading"
    # Keep empty revision rows and the heading within the ruled strip.
    for row in rows[-(len(fs.title_block.revisions) + 1) :]:
        assert float(row.find("mxGeometry").get("height")) == pytest.approx(F._REV_ROW, abs=0.01), (
            "a revision row is not the sheet's own depth"
        )
    # Every column at the width the sheet rules it.
    widths = [float(c.find("mxGeometry").get("width")) for c in _row_cells(cells, rows[-1])]
    assert widths == pytest.approx([w for _heading, w in _rev_cols()], abs=0.01)


def _rev_cols():
    """Return revision-table headings and widths."""
    from pandid.render import furniture as F

    return [(heading, width) for heading, width, _attr in F._REV_COLS]


def _row_cells(cells, row):
    """Sort a table row's children by horizontal position."""
    kids = [c for c in cells.values() if c.get("parent") == row.get("id")]
    return sorted(kids, key=lambda c: float(c.find("mxGeometry").get("x")))


def test_a_columnar_box_is_a_table_and_a_prose_box_is_not():
    """Export columnar annotations as tables and prose as text."""
    from pandid.document import Annotation

    fs = Flowsheet("boxes")
    pump = fs.add(units.Pump("P-101"))
    pump.pin(x=100, y=100)
    fs.annotations.append(
        Annotation(title="LEGEND", align="top-left", rows=[("SS", "316L"), ("CS", "A106")])
    )
    fs.annotations.append(
        Annotation(title="NOTES", align="top-right", rows=["All lines slope to drain."])
    )
    fs.layout()
    cells = _cells(fs, check=False)
    styles = {c.get("id"): _style(c) for c in cells.values()}
    legend = next(i for i, c in cells.items() if c.get("value") == "LEGEND")
    notes = next(i for i, c in cells.items() if (c.get("value") or "").startswith("NOTES"))
    assert styles[legend].get("shape") == "table"
    assert "shape" not in styles[notes]
    assert {"SS", "316L", "CS", "A106"} <= {c.get("value") for c in cells.values()}


def test_the_furniture_docks_where_the_sheet_docks_it():
    """Place exported furniture at the SVG docking positions."""
    from pandid.document import Annotation
    from pandid.render import furniture as F

    fs = Flowsheet("docked")
    pump = fs.add(units.Pump("P-101"))
    pump.pin(x=400, y=300)
    left = Annotation(title="LEGEND", align="top-left", rows=[("SS", "316L")])
    right = Annotation(title="EQUIPMENT LIST", align="top-right", rows=[("P-101", "Pump")])
    fs.annotations.extend([left, right])
    fs.layout()

    box = drawing_bounds(fs)
    placed, _frame, _free = F.dock(
        [(a, a.align, *F.measure_annotation(a)) for a in fs.annotations], box
    )
    at = {id(obj): (x, y) for obj, x, y, _w, _h in placed}
    cells = _cells(fs, check=False)
    for annotation in (left, right):
        cell = next(c for c in cells.values() if c.get("value") == annotation.title)
        geo = cell.find("mxGeometry")
        want = at[id(annotation)]
        assert (float(geo.get("x")), float(geo.get("y"))) == pytest.approx(want, abs=0.01)
    # Confirm the two annotations occupy different corners.
    assert at[id(left)][0] < at[id(right)][0]


def _svg_stream_table(svg: str) -> list[tuple]:
    """Read stream-table cells from rendered SVG."""
    body = re.search(r'<g id="stream_table">(.*?)</g>', svg, re.S)
    assert body is not None, "the sheet drew no stream table"
    cell = re.compile(
        r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" '
        r'fill="(\S+)" stroke="black" stroke-width="([\d.]+)"/>\s*'
        r'<text x="[-\d.]+" y="[-\d.]+" font-family="\S+" font-size="[\d.]+"'
        r'( font-weight="bold")? text-anchor="(\w+)">(.*?)</text>'
    )
    out = []
    for m in cell.finditer(body.group(1)):
        x, y, w, h, fill, rule, bold, anchor, text = m.groups()
        out.append(
            (
                float(x),
                float(y),
                float(w),
                float(h),
                fill,
                float(rule),
                bold is not None,
                anchor,
                text,
            )
        )
    assert out, "the stream table drew no cells"
    return out


def _drawio_stream_table(cells):
    """Read stream-table cells from a Draw.io export."""
    tables = [
        c
        for c in cells.values()
        if "shape=table;" in (c.get("style") or "")
        and not (c.get("value") or "")
        and not c.get("id").endswith("-rev")
    ]
    assert len(tables) == 1, f"expected one stream table, found {len(tables)}"
    table = tables[0]
    geo = table.find("mxGeometry")
    x0, y0 = float(geo.get("x")), float(geo.get("y"))
    out = []
    for row in [c for c in cells.values() if c.get("parent") == table.get("id")]:
        rgeo = row.find("mxGeometry")
        ry, rh = float(rgeo.get("y")), float(rgeo.get("height"))
        for cell in [c for c in cells.values() if c.get("parent") == row.get("id")]:
            cgeo = cell.find("mxGeometry")
            style = _style(cell)
            out.append(
                (
                    x0 + float(cgeo.get("x")),
                    y0 + ry,
                    float(cgeo.get("width")),
                    rh,
                    style.get("fillColor"),
                    style.get("fontStyle") == "1",
                    style.get("align"),
                    cell.get("value") or "",
                )
            )
    return table, out


#: SVG rounding (0.05), two XML coordinates (0.005 each), and float slack.
_GRID_SLACK = 0.05 + 0.005 + 0.005 + 1e-9


def test_the_stream_table_is_the_grid_the_sheet_draws(settled_gallery, rendered_gallery):
    """Match stream-table cells to SVG geometry, style, and text."""
    from pandid.render.drawio import _fill

    checked = []
    for stem in TABLE_REPRESENTATIVES:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        drawn = _svg_stream_table(rendered_gallery[stem].svg)
        table, exported = _drawio_stream_table(_gallery_cells(rendered_gallery, stem))
        assert len(exported) == len(drawn), (
            f"{stem}: the sheet rules {len(drawn)} cells and the export writes {len(exported)}"
        )
        for want, got in zip(drawn, exported):
            x, y, w, h, fill, _rule, bold, anchor, text = want
            gx, gy, gw, gh, gfill, gbold, galign, gtext = got
            # Allow only serialization rounding between SVG and Draw.io.
            assert (gx, gy, gw, gh) == pytest.approx((x, y, w, h), abs=_GRID_SLACK), (
                f"{stem}: {text!r} is ruled at {(x, y, w, h)} and exported at {(gx, gy, gw, gh)}"
            )
            # Compare decoded SVG text with ElementTree's decoded XML value.
            want_text = html.unescape(text)
            assert gtext == want_text, f"{stem}: {want_text!r} exported as {gtext!r}"
            assert gfill == _fill(fill), f"{stem}: {text!r} is filled {fill} and exported {gfill}"
            assert gbold is bold, f"{stem}: {text!r} exported at the wrong weight"
            assert galign == ("left" if anchor == "start" else "center"), (
                f"{stem}: {text!r} is set {anchor} and exported {galign}"
            )
        # The whole table sits inside the exported frame.
        geo = table.find("mxGeometry")
        tx, ty = float(geo.get("x")), float(geo.get("y"))
        tw, th = float(geo.get("width")), float(geo.get("height"))
        fx, fy, fw, fh = _drawio_furniture(fs, kwargs)[1]
        assert fx - 0.01 <= tx and tx + tw <= fx + fw + 0.01, f"{stem}: out of frame"
        assert fy - 0.01 <= ty and ty + th <= fy + fh + 0.01, f"{stem}: out of frame"
        checked.append(stem)
    assert checked, "no example in the gallery draws a stream table"


def test_the_stream_table_is_ruled_across_and_down_as_the_sheet_rules_it(
    settled_gallery, rendered_gallery
):
    """Match stream-table rules to the rendered grid."""
    from pandid.render import furniture as F

    checked = []
    for stem in TABLE_REPRESENTATIVES:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        cells = _gallery_cells(rendered_gallery, stem)
        table, _drawn = _drawio_stream_table(cells)
        style = _style(table)
        assert style.get("rowLines", "1") != "0"
        assert style.get("columnLines", "1") != "0"
        assert float(style["strokeWidth"]) == pytest.approx(F._CELL_RULE)

        rows = [c for c in cells.values() if c.get("parent") == table.get("id")]
        widths = [
            [
                float(c.find("mxGeometry").get("width"))
                for c in cells.values()
                if c.get("parent") == r.get("id")
            ]
            for r in rows
        ]
        ncol = max(len(w) for w in widths)
        total = float(table.find("mxGeometry").get("width"))
        for w in widths:
            assert len(w) in (1, ncol), f"{stem}: a row of {len(w)} of {ncol} cells"
            assert sum(w) == pytest.approx(total, abs=0.01)
        assert len([w for w in widths if len(w) == 1]) == len(fs.stream_table_sections), stem
        checked.append(stem)
    assert checked, "no example in the gallery draws a stream table"


@pytest.mark.parametrize(
    "option,value",
    [
        ("debug", True),
    ],
)
def test_render_refuses_a_sheet_option_it_cannot_honour(tmp_path, sample, option, value):
    """Reject unsupported Draw.io rendering options."""
    with pytest.raises(ValueError, match=option):
        sample.render(tmp_path / "sheet.drawio", **{option: value})


@pytest.mark.parametrize(
    "option,value",
    [
        ("page_size", "A3"),
        ("border", "zone"),
        ("jump_direction", "horizontal"),
        ("show_stream_table", True),
    ],
)
def test_render_honours_the_sheet_options_it_can(tmp_path, sample, option, value):
    """Apply supported sheet options when rendering Draw.io."""
    out = tmp_path / "sheet.drawio"
    sample.render(out, **{option: value})
    assert out.read_text(encoding="utf-8") == sample.to_drawio(**{option: value})


def _page_states(fs: Flowsheet, **kwargs) -> "tuple[str, float, float]":
    """Read the exported page setting and dimensions."""
    model = ET.fromstring(fs.to_drawio(**kwargs)).find("diagram/mxGraphModel")
    assert model.get("pageWidth") is not None and model.get("pageHeight") is not None, (
        "the model states no page size"
    )
    return (model.get("page"), float(model.get("pageWidth")), float(model.get("pageHeight")))


@pytest.mark.parametrize("border", ["none", "zone"])
@pytest.mark.parametrize("page_size", [None, "A3"])
def test_every_export_states_a_page_that_holds_the_whole_drawing(page_size, border):
    """Declare a page large enough to contain the drawing."""
    from pandid.render import furniture as F
    from pandid.render.svg import _page

    fs = Flowsheet("held")
    a = fs.add(units.Tank("T-1"))
    b = fs.add(units.Tank("T-2"))
    a.pin(x=0, y=0)
    b.pin(x=900, y=260)
    fs.connect(a.outlet, b.inlet)
    fs.route()

    kwargs = {"border": border, "check": False}
    if page_size is not None:
        kwargs["page_size"] = page_size
    page, pw, ph = _page_states(fs, **kwargs)

    sheet = _page(page_size)
    _furniture, frame, _fit = DrawioRenderer()._furniture(fs, sheet, border=border)
    if sheet is not None:
        # Paged: the page is the paper, anchored at the model origin.
        assert page == "1"
        assert (pw, ph) == pytest.approx((sheet.width, sheet.height), abs=0.01)
        return

    # Unpaged exports use the drawing's top-left corner as their origin.
    assert page == "0"
    ox, oy, ow, oh = F.sheet_rect(*frame)
    ox, oy = ox - F.OUTER_MARGIN, oy - F.OUTER_MARGIN
    assert (pw, ph) == pytest.approx((ow + 2 * F.OUTER_MARGIN, oh + 2 * F.OUTER_MARGIN), abs=0.01)

    # The page holds the drawing and its frame.
    dx0, dy0, dx1, dy1 = drawing_bounds(fs)
    fx, fy, fw, fh = frame
    for x0, y0, x1, y1 in ((dx0, dy0, dx1, dy1), (fx, fy, fx + fw, fy + fh)):
        assert ox <= x0 and oy <= y0
        assert x1 <= ox + pw and y1 <= oy + ph


@pytest.mark.parametrize("border", ["none", "zone"])
def test_no_cell_hangs_over_the_edge_of_the_page_the_file_states(sample, border):
    """Keep every visible cell inside the declared page."""
    from pandid.render import furniture as F

    _page_attr, pw, ph = _page_states(sample, border=border, check=False)
    _furniture, frame, _fit = DrawioRenderer()._furniture(sample, None, border=border)
    ox, oy, _ow, _oh = F.sheet_rect(*frame)
    ox, oy = ox - F.OUTER_MARGIN, oy - F.OUTER_MARGIN

    seen = 0
    for cell in _cells(sample, border=border, check=False).values():
        geo = cell.find("mxGeometry")
        # A child cell (a table row or cell) is placed relative to its parent.
        if geo is None or cell.get("edge") == "1" or cell.get("parent") != "1":
            continue
        x, y = float(geo.get("x")), float(geo.get("y"))
        w, h = float(geo.get("width") or 0), float(geo.get("height") or 0)
        seen += 1
        assert ox <= x and x + w <= ox + pw, f"{cell.get('id')} runs off the page"
        assert oy <= y and y + h <= oy + ph, f"{cell.get('id')} runs off the page"
    assert seen > 1, "the sheet stopped writing vertices"


def _two_tanks(name: str) -> Flowsheet:
    """Build two connected tanks with nothing else on the sheet."""
    fs = Flowsheet(name)
    a = fs.add(units.Tank("T-1")).pin(x=0, y=0)
    b = fs.add(units.Tank("T-2")).pin(x=400, y=0)
    fs.connect(a.outlet, b.inlet)
    fs.route()
    return fs


@pytest.mark.parametrize("case", ["zone border", "box in the strip's corner"])
def test_the_title_strip_is_docked_where_the_sheet_docks_it(case):
    """Dock draw.io's title strip on the rectangle the SVG sheet gives it."""
    from pandid.document import Annotation, TitleBlock

    fs = _two_tanks("docked")
    border = "zone" if case == "zone border" else "none"
    if case != "zone border":
        fs.title_block = TitleBlock(drawing_number="PFD-1")
        fs.annotations.append(Annotation(title="NOTES", align="bottom-right", rows=[("1", "One.")]))
    svg = fs.to_svg(border=border, check=False)
    drawn = re.findall(
        r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" '
        r'fill="white" stroke="black" stroke-width="2"/>',
        svg,
    )
    assert len(drawn) == 1, "the sheet draws one title strip"
    cells = _cells(fs, border=border, check=False)
    strips = [
        c
        for cid, c in cells.items()
        if re.fullmatch(r"f\d+", cid) and _style(c).get("strokeWidth") == "2"
    ]
    assert len(strips) == 1, "draw.io exports one title strip"
    geo = strips[0].find("mxGeometry")
    assert geo is not None
    got = [float(geo.get(k, "nan")) for k in ("x", "y", "width", "height")]
    assert got == pytest.approx([float(v) for v in drawn[0]], abs=0.1)


def test_a_sheet_without_furniture_states_the_page_the_sheet_draws():
    """State the page the SVG sheet draws, margin and all."""
    fs = _two_tanks("bare")
    view = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', fs.to_svg(check=False))
    assert view is not None
    _page_attr, pw, ph = _page_states(fs, check=False)
    assert (pw, ph) == pytest.approx((float(view.group(1)), float(view.group(2))), abs=0.1)


def test_a_paged_drawing_is_fitted_onto_its_paper():
    """Fit paged drawing geometry into the region the SVG sheet fits it to."""
    from pandid.render.svg import _page

    fs = Flowsheet("fitted")
    a = fs.add(units.Tank("T-1"))
    b = fs.add(units.Tank("T-2"))
    a.pin(x=0, y=0)
    b.pin(x=3000, y=1600)
    fs.connect(a.outlet, b.inlet)
    fs.route()

    sheet = _page("A3")
    assert sheet is not None
    fitted = re.search(
        r'<g id="drawing" transform="[^"]*scale\(([\d.]+)\)"', fs.to_svg(page_size="A3")
    )
    assert fitted is not None
    scale = float(fitted.group(1))
    assert scale < 1.0, "the fixture stopped needing to be shrunk"

    cells = _cells(fs, page_size="A3", check=False)
    for i, u in enumerate(fs.units):
        x0, y0, x1, y1 = cell_box(u)
        geo = cells[f"u{i}"].find("mxGeometry")
        assert float(geo.get("width")) == pytest.approx(scale * (x1 - x0), abs=0.01)
    # Every cell lands inside the paper.
    for cell in cells.values():
        geo = cell.find("mxGeometry")
        if geo is None or geo.get("x") is None or cell.get("edge") == "1":
            continue
        assert -1 <= float(geo.get("x")) <= sheet.width
        assert -1 <= float(geo.get("y")) <= sheet.height


def test_dock_names_the_missing_callback_rather_than_crashing_blind():
    """Report a missing overflow callback when docking needs it."""
    from pandid.render import furniture as F
    from pandid.render.svg import _page

    sheet = _page("A4")
    huge = object()
    with pytest.raises(TypeError, match="too_small"):
        F.dock([(huge, "top-left", 10_000.0, 10_000.0)], (0.0, 0.0, 100.0, 100.0), sheet=sheet)


def test_a_zone_border_rules_the_same_frame_the_sheet_rules():
    """Match zone-border divisions to the SVG frame."""
    from pandid.render import furniture as F

    fs = Flowsheet("ruled")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, page_size="A3", border="zone", check=False)
    values = {c.get("value") for c in cells.values()}

    _placed, frame, _free = F.dock(
        [],
        drawing_bounds(fs),
        sheet=__import__("pandid.render.svg", fromlist=["x"])._page("A3"),
    )
    z = F.zone_layout(*frame)
    assert {t for _k, *_r, t in [p for p in z.parts if p[0] == "label"]} <= values, (
        "a zone lost its letter"
    )
    rules = [p for p in z.parts if p[0] == "rule"]
    ruled = [
        c for c in cells.values() if (c.get("id") or "").startswith("z") and c.get("edge") == "1"
    ]
    assert len(ruled) == len(rules)
    # The two rectangles the frame is: the sheet edge and the drawing frame.
    ix, iy, iw, ih = z.inner
    geo = cells["z-frame"].find("mxGeometry")
    assert (float(geo.get("x")), float(geo.get("y"))) == pytest.approx((ix, iy), abs=0.01)
    assert (float(geo.get("width")), float(geo.get("height"))) == pytest.approx((iw, ih), abs=0.01)
    ox, oy, ow, oh = z.outer
    geo = cells["z-sheet"].find("mxGeometry")
    assert (float(geo.get("x")), float(geo.get("y"))) == pytest.approx((ox, oy), abs=0.01)


def test_each_paged_representative_lands_on_its_configured_paper(settled_gallery):
    """Fit each paged representative within its configured paper and border."""
    for stem in PAGED_REPRESENTATIVES:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        fs.to_svg(**kwargs)
        sheet = _page(kwargs.get("page_size"))
        doc = fs.to_drawio(
            diagram=kwargs.get("diagram"),
            page_size=kwargs.get("page_size"),
            border=kwargs.get("border"),
        )
        root = ET.fromstring(doc)
        assert sheet is not None
        for cell in root.iter("mxCell"):
            geo = cell.find("mxGeometry")
            if geo is None or cell.get("edge") == "1" or geo.get("x") is None:
                continue
            if cell.get("parent") not in (None, "1"):
                continue  # a table row or cell, measured inside its own container
            x, y = float(geo.get("x")), float(geo.get("y"))
            w, h = float(geo.get("width") or 0), float(geo.get("height") or 0)
            assert -1 <= x and x + w <= sheet.width + 1, f"{cell.get('id')} runs off the page"
            assert -1 <= y and y + h <= sheet.height + 1, f"{cell.get('id')} runs off the page"


def test_an_unruled_sheet_draws_no_frame():
    """Omit frame cells when the sheet requests no border."""
    fs = Flowsheet("plain")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, page_size="A3", check=False)
    assert not [i for i in cells if i.startswith("z")]


def test_an_unsupported_extension_still_names_drawio_among_the_options(tmp_path, sample):
    """List Draw.io among supported render formats."""
    with pytest.raises(ValueError, match=r"\.drawio"):
        sample.render(tmp_path / "sheet.dwg")


# Shipped gallery examples.


def _drawio_cells_from_document(document: str) -> dict:
    """Index cells from an already-rendered Draw.io document."""
    return {cell.get("id"): cell for cell in _drawio_root(document).iter("mxCell")}


#: Representative sheets for cross-backend Draw.io export checks.
DRAWIO_REPRESENTATIVES = (
    "02_distillation_train",
    "03_control_loop",
    "08_line_numbers",
    "09_ethanol_pfd",
    "10_ethanol_pid",
    "11_block_flow_diagram",
    "13_tank_farm",
    "20_alumina_refinery_3",
)

#: Sheets whose material-line labels exercise collision avoidance.
LINE_NUMBER_SHEETS = ("08_line_numbers", "10_ethanol_pid", "13_tank_farm")

#: Sheets that place at least one line-number leader.
LEADER_SHEETS = ("10_ethanol_pid", "13_tank_farm")

#: Representatives that write an equipment tag beside its symbol.
TAGGED_SHEETS = tuple(stem for stem in DRAWIO_REPRESENTATIVES if stem != "11_block_flow_diagram")


#: Instrumented P&ID representatives with all exported function-code forms.
INSTRUMENT_CODE_SHEETS = ("03_control_loop", "10_ethanol_pid", "13_tank_farm")

#: Zoned, paged, and large tables for Draw.io furniture checks.
TABLE_REPRESENTATIVES = ("02_distillation_train", "09_ethanol_pfd", "20_alumina_refinery_3")

#: Paged representatives for checking actual gallery fit on A3 paper.
PAGED_REPRESENTATIVES = ("09_ethanol_pfd", "10_ethanol_pid")


@dataclass(frozen=True)
class _GalleryArtifacts:
    """Rendered outputs shared by read-only gallery export checks."""

    svg: str
    drawio: str


@pytest.fixture(scope="module")
def rendered_gallery(settled_gallery) -> dict[str, _GalleryArtifacts]:
    """Render the default export pair once for each representative sheet."""
    artifacts = {}
    for stem in DRAWIO_REPRESENTATIVES:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        artifacts[stem] = _GalleryArtifacts(
            svg=fs.to_svg(**kwargs),
            drawio=fs.to_drawio(**_drawio_options(kwargs)),
        )
    return artifacts


def _gallery_cells(rendered_gallery: dict[str, _GalleryArtifacts], stem: str) -> dict:
    """Parse a fresh Draw.io cell map from a shared gallery artifact."""
    return _drawio_cells_from_document(rendered_gallery[stem].drawio)


@pytest.mark.parametrize("stem", DRAWIO_REPRESENTATIVES, ids=DRAWIO_REPRESENTATIVES)
def test_each_representative_export_matches_its_rendered_sheet(settled_gallery, stem):
    """Match each representative Draw.io export to its rendered sheet."""
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    fs.to_svg(**kwargs)  # draw the same settled geometry as the example
    root = ET.fromstring(fs.to_drawio(diagram=kwargs.get("diagram")))
    cells = {cell.get("id"): cell for cell in root.iter("mxCell")}

    at = {}
    for i, u in enumerate(fs.units):
        geometry = cells[f"u{i}"].find("mxGeometry")
        x0, y0, x1, y1 = cell_box(u)
        assert float(geometry.get("x")) == pytest.approx(x0, abs=0.01)
        assert float(geometry.get("y")) == pytest.approx(y0, abs=0.01)
        assert float(geometry.get("width")) == pytest.approx(x1 - x0, abs=0.01)
        assert float(geometry.get("height")) == pytest.approx(y1 - y0, abs=0.01)
        at[id(u)] = _style(cells[f"u{i}"])
        shape = at[id(u)].get("shape")
        assert shape is None or shape in STENCIL_KEYS or shape in _BUILTIN_SHAPES, (
            f"{stem}: {u.name} references {shape!r}, which resolves to nothing"
        )

    for n, s in enumerate(fs.streams):
        drawn = stream_polyline(s)
        array = cells[f"s{n}"].find("mxGeometry/Array")
        emitted = (
            [(float(p.get("x")), float(p.get("y"))) for p in array.findall("mxPoint")]
            if array is not None
            else []
        )
        assert len(emitted) == len(drawn) - 2, f"{stem}: {s.name} lost a turn"
        for point, expected in zip(emitted, drawn[1:-1]):
            assert point == pytest.approx(expected, abs=0.01), f"{stem}: {s.name}"
        style = _style(cells[f"s{n}"])
        for prefix, port in (("exit", s.source), ("entry", s.dest)):
            landed = _drawio_connection_point(port.owner, at[id(port.owner)], style, prefix)
            assert landed == pytest.approx(stream_end(port), abs=0.01)


def _drawn_boxes(fs, kwargs, cells: dict) -> tuple[dict, dict, list]:
    """Read drawn symbol and label boxes from exported XML."""
    from pandid.render.drawio import _LINE_BOX, _Fit
    from pandid.render.furniture import text_width

    symbols, tags, numbers = {}, {}, []
    for i, u in enumerate(fs.units):
        cell = cells[f"u{i}"]
        geometry = cell.find("mxGeometry")
        x, y = float(geometry.get("x")), float(geometry.get("y"))
        w, h = float(geometry.get("width")), float(geometry.get("height"))
        symbols[f"u{i}"] = (x, y, x + w, y + h)
        text = cell.get("value") or ""
        style = _style(cell)
        side = style.get("labelPosition", style.get("verticalLabelPosition", "middle"))
        # Internal labels are part of their shape, not separate obstacles.
        if not text or side in ("middle", "center"):
            continue
        size = float(style.get("fontSize", 12))
        lines = text.split("<br>")
        lw = max(text_width(line, size) for line in lines)
        lh = _LINE_BOX * size * len(lines)
        offset = geometry.find("mxPoint[@as='offset']")
        dx = float(offset.get("x")) if offset is not None else 0.0
        dy = float(offset.get("y")) if offset is not None else 0.0
        # draw.io holds a side label 2 off the cell, and 1 more under and 5 over its text.
        nx, ny, gap = {
            "top": (0, -1, 3.0),
            "bottom": (0, 1, 7.0),
            "left": (-1, 0, 2.0),
            "right": (1, 0, 2.0),
        }[side]
        cx = x + w / 2 + dx + nx * (w / 2 + gap + lw / 2)
        cy = y + h / 2 + dy + ny * (h / 2 + gap + lh / 2)
        tags[f"u{i}"] = (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)

    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    assert isinstance(fit, _Fit)
    for n, s in enumerate(fs.streams):
        cell = cells[f"s{n}"]
        name = cell.get("value") or ""
        if not name:
            continue
        style = _style(cell)
        size = float(style["fontSize"])
        cx, cy = _drawio_edge_label(
            [fit.at(*p) for p in stream_polyline(s)], cell.find("mxGeometry")
        )
        lw, lh = text_width(name, size), _LINE_BOX * size
        # `horizontal=0` turns the label a quarter, so its box is transposed.
        if style.get("horizontal") == "0":
            lw, lh = lh, lw
        numbers.append((name, (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)))
    return symbols, tags, numbers


@pytest.mark.parametrize("stem", LINE_NUMBER_SHEETS, ids=LINE_NUMBER_SHEETS)
def test_no_line_number_is_written_over_a_symbol_or_an_equipment_tag(
    settled_gallery, rendered_gallery, stem
):
    """Keep line-number labels clear of symbols and equipment tags."""
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    symbols, tags, numbers = _drawn_boxes(fs, kwargs, _gallery_cells(rendered_gallery, stem))
    drawn = {**symbols, **{f"{k} tag": v for k, v in tags.items()}}

    struck = [
        (name, other)
        for name, box in numbers
        for other, obstacle in drawn.items()
        if overlaps(box, obstacle)
    ]
    assert not struck, f"{stem}: line numbers written over {struck}"


_HALO = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" />\n'
    r"\s*<text [^>]*>([^<]*)</text>"
)


@pytest.mark.parametrize("stem", TAGGED_SHEETS, ids=TAGGED_SHEETS)
def test_an_equipment_tag_is_written_inside_its_halo_on_the_sheet(
    settled_gallery, rendered_gallery, stem
):
    """Write each one-line equipment tag inside the halo the sheet draws for it."""
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    group = rendered_gallery[stem].svg.split('<g id="unit_labels">', 1)[1].split("</g>", 1)[0]
    halos: dict[str, list] = {}
    for x, y, w, h, text in _HALO.findall(group):
        x0, y0 = float(x), float(y)
        halos.setdefault(html.unescape(text), []).append(
            fit.box((x0, y0, x0 + float(w), y0 + float(h)))
        )
    cells = _gallery_cells(rendered_gallery, stem)
    _symbols, tags, _numbers = _drawn_boxes(fs, kwargs, cells)

    def inside(box, halo) -> bool:
        # The sheet writes a halo to a tenth of a unit.
        x0, y0, x1, y1 = halo
        return box[0] > x0 - 0.1 and box[1] > y0 - 0.1 and box[2] < x1 + 0.1 and box[3] < y1 + 0.1

    adrift = [
        (tag, [round(v, 1) for v in box])
        for cid, box in tags.items()
        if "<br>" not in (tag := html.unescape(cells[cid].get("value") or ""))
        and not any(inside(box, halo) for halo in halos.get(tag, ()))
    ]
    assert tags, f"{stem}: no equipment tag is written beside its symbol"
    assert not adrift, f"{stem}: tags off their halos {adrift}"


def test_a_tag_draw_io_wraps_keeps_off_the_unit_above():
    """Keep a tag that wraps to two lines in its cell clear of the unit above it."""
    fs = Flowsheet("wrapped tag")
    fs.add(pandid.Block("U-1", width=60, height=40)).pin(x=100, y=100)
    fs.add(pandid.Mixer("M-101 A/B", label_pos="top")).pin(x=115, y=172)
    cells = _drawio_cells_from_document(fs.to_drawio())
    assert "whiteSpace=wrap" in (cells["u1"].get("style") or "")
    geometry = cells["u1"].find("mxGeometry")
    assert geometry is not None
    offset = geometry.find("mxPoint[@as='offset']")
    # Two wrapped lines rise from draw.io's own spot, three above the cell.
    top = float(geometry.get("y", 0)) - 3.0 - 2 * 1.2 * 12.0
    top += float(offset.get("y", 0)) if offset is not None else 0.0
    assert top >= 140.0, f"the wrapped tag reaches up to {top:.1f}, into U-1"


def test_a_tag_stacked_with_fail_letters_keeps_off_the_unit_above():
    """Keep a two-line tag label clear of the unit above its symbol."""
    fs = Flowsheet("stacked equipment")
    fs.add(pandid.Pump("P-1", width=60, height=40, label_pos="center")).pin(x=100, y=100)
    fs.add(pandid.ControlValve("CV-1", fail="closed")).pin(x=115, y=172)
    cells = _drawio_cells_from_document(fs.to_drawio())
    symbols, tags, _numbers = _drawn_boxes(fs, {}, cells)
    assert cells["u1"].get("value") == "CV-1<br>FC"
    assert not overlaps(tags["u1"], symbols["u0"]), (tags["u1"], symbols["u0"])


@pytest.mark.parametrize("stem", LEADER_SHEETS, ids=LEADER_SHEETS)
def test_a_displaced_line_number_is_tied_back_to_its_run(settled_gallery, rendered_gallery, stem):
    """Connect a displaced line number to its stream with a leader."""
    from test_label_invariants import _labels

    fs, kwargs = copy_settled_case(settled_gallery, stem)
    svg = rendered_gallery[stem].svg
    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    cells = _gallery_cells(rendered_gallery, stem)

    drawn = {label.name: label for label in _labels(svg) if label.leader is not None}
    emitted = {cid: cell for cid, cell in cells.items() if cid.endswith("-lead")}
    assert drawn, f"{stem}: this representative has no displaced line number"
    assert sorted(cells[cid[: -len("-lead")]].get("value") for cid in emitted) == sorted(drawn), (
        f"{stem}: the sheet draws {sorted(drawn)} leaders and the export {len(emitted)}"
    )

    for cid, cell in emitted.items():
        label = drawn[cells[cid[: -len("-lead")]].get("value")]
        assert label.head, "the sheet drew this leader without a head"
        geometry = cell.find("mxGeometry")
        got, want = [], []
        for point, end in zip(("sourcePoint", "targetPoint"), label.leader, strict=True):
            at = geometry.find(f'mxPoint[@as="{point}"]')
            got += [float(at.get("x")), float(at.get("y"))]
            want += list(fit.at(*end))
        # The sheet writes these coordinates to one decimal, the export to two.
        assert got == pytest.approx(want, abs=0.06)
        style = _style(cell)
        # The head goes on the end that lands on the run, and nowhere else.
        assert style["endArrow"] == "block" and style["endFill"] == "1"
        assert style["startArrow"] == "none"
        assert float(style["endSize"]) == pytest.approx(fit.length(_LEADER_HEAD), abs=0.01)
        # A reference line is ISO 10628-1 5.3.1 c), in the label's own ink.
        assert float(style["strokeWidth"]) == pytest.approx(
            fit.length(LineWeight.DETAIL.width), abs=0.01
        )


# Line weight


@pytest.mark.parametrize("stem", DRAWIO_REPRESENTATIVES, ids=DRAWIO_REPRESENTATIVES)
def test_every_drawn_symbol_states_the_weight_the_sheet_rules_it_at(
    settled_gallery, rendered_gallery, stem
):
    """Export each symbol at its rendered stroke width."""

    fs, kwargs = copy_settled_case(settled_gallery, stem)
    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    cells = _gallery_cells(rendered_gallery, stem)
    seen = 0
    for i, u in enumerate(fs.units):
        sym = default_registry.for_unit(u)
        want = fit.length(_class_weight(sym).width)
        for cid in (f"u{i}", f"u{i}-in"):
            cell = cells.get(cid)
            if cell is None:
                continue
            style = _style(cell)
            # A pipe tee draws no ink, so it has no pen to state.
            if style.get("strokeColor") == "none":
                continue
            assert "strokeWidth" in style, f"{stem}: {u.kind}/{getattr(u, 'variant', 'default')}"
            assert float(style["strokeWidth"]) == pytest.approx(want, abs=0.01)
            seen += 1
    assert seen, f"{stem}: no unit cell was checked"


@pytest.mark.parametrize("stem", DRAWIO_REPRESENTATIVES, ids=DRAWIO_REPRESENTATIVES)
def test_no_cell_that_inks_anything_leaves_its_weight_to_drawio(rendered_gallery, stem):
    """State a stroke width on each visible exported cell."""
    root = _drawio_root(rendered_gallery[stem].drawio)
    silent = []
    for cell in root.findall("mxCell"):
        style = _style(cell)
        ink = style.get("strokeColor")
        if ink in (None, "none", "inherit") or "strokeWidth" in style:
            continue
        silent.append(cell.get("id"))
    assert not silent, f"{stem}: cells drawn at draw.io's default weight: {silent}"


# Line jumps, resolved from exported edge order and styles.


def _intersection(p0, p1, p2, p3):
    """Find the intersection of two line segments."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p0, p1, p2, p3
    denom = ((y3 - y2) * (x1 - x0)) - ((x3 - x2) * (y1 - y0))
    if denom == 0:
        return None
    ua = (((x3 - x2) * (y0 - y2)) - ((y3 - y2) * (x0 - x2))) / denom
    ub = (((x1 - x0) * (y0 - y2)) - ((y1 - y0) * (x0 - x2))) / denom
    if 0.0 <= ua <= 1.0 and 0.0 <= ub <= 1.0:
        return (x0 + ua * (x1 - x0), y0 + ua * (y1 - y0))
    return None


def _edge_lines(fs, kwargs, root):
    """Pair exported edges with their drawn polylines."""
    from pandid.render.drawio import _Fit

    _boxes, _frame, fit = _drawio_furniture(fs, kwargs)
    assert isinstance(fit, _Fit)
    known = {f"s{n}": [fit.at(*p) for p in stream_polyline(s)] for n, s in enumerate(fs.streams)}
    for n, (inst, tap, centre) in enumerate(tap_lines(fs)):
        known[f"t{n}"] = [fit.at(*p) for p in tap_route(inst, tap, centre)]
    out = []
    for cell in root.findall("mxCell"):
        if cell.get("edge") != "1":
            continue
        geometry = cell.find("mxGeometry")
        start = geometry.find('mxPoint[@as="sourcePoint"]')
        end = geometry.find('mxPoint[@as="targetPoint"]')
        if start is not None and end is not None:
            line = [(float(p.get("x")), float(p.get("y"))) for p in (start, end)]
        else:
            line = known[cell.get("id")]
        out.append((cell.get("id"), _style(cell), line))
    return out, fit


def _drawio_hops(edges):
    """Calculate hops implied by Draw.io edge order and styles."""
    thresh = 0.5
    seen: list = []
    out: set = set()
    for cid, style, line in edges:
        if style.get("jumpStyle", "none") != "none":
            for p0, p1 in zip(line, line[1:]):
                for other, other_style, other_line in seen:
                    if other_style.get("noJump") == "1":
                        continue
                    for p2, p3 in zip(other_line, other_line[1:]):
                        at = _intersection(p0, p1, p2, p3)
                        if at is None:
                            continue
                        if (abs(at[0] - p0[0]) <= thresh and abs(at[1] - p0[1]) <= thresh) or (
                            abs(at[0] - p1[0]) <= thresh and abs(at[1] - p1[1]) <= thresh
                        ):
                            continue
                        out.add((cid, other, round(at[0], 2), round(at[1], 2)))
        seen.append((cid, style, line))
    return out


def _sheet_hops(fs, fit, direction="vertical", style="arc"):
    """Calculate hops drawn by the SVG renderer."""
    if style == "plain":
        return set()
    hor, ver = [], []
    for n, s in enumerate(fs.streams):
        points = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                hor.append((n, min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                ver.append((n, min(y1, y2), max(y1, y2), x1))
    hopping, crossed = (ver, hor) if direction == "vertical" else (hor, ver)
    out = set()
    for hop, lo, hi, at in hopping:
        for cross, c_lo, c_hi, c_at in crossed:
            if not (c_lo < at < c_hi and lo + HOP_R < c_at < hi - HOP_R):
                continue
            point = (at, c_at) if direction == "vertical" else (c_at, at)
            x, y = fit.at(*point)
            out.add((f"s{hop}", f"s{cross}", round(x, 2), round(y, 2)))
    return out


@pytest.mark.parametrize("style", CROSSING_STYLES, ids=CROSSING_STYLES)
@pytest.mark.parametrize("stem", MARKED, ids=MARKED)
def test_each_marked_representative_accounts_for_every_drawio_hop(settled_gallery, stem, style):
    """Match exported jumps, hops and dropped-hop findings to the runs the sheet marks."""
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    paths = _paths(fs.to_svg(**kwargs, crossing_style=style))
    assert len(paths) == len(fs.streams)
    marked = {f"s{n}" for n, d in enumerate(paths) if _ARC in d or d.count("M ") > 1}
    root = _drawio_root(fs.to_drawio(**_drawio_options(kwargs), crossing_style=style))
    edges, fit = _edge_lines(fs, kwargs, root)
    jumps = {cid: s["jumpStyle"] for cid, s, _ in edges if s.get("jumpStyle", "none") != "none"}
    assert set(jumps) <= marked, (
        f"{stem}: the export marks {sorted(jumps)}, the sheet marks {sorted(marked)}"
    )
    if style == "plain":
        assert not marked, f"{stem}: plain crossings, and the sheet marked one"
        order = [cid for cid, _s, _line in edges if re.fullmatch(r"s\d+", cid)]
        assert order == sorted(order, key=lambda i: int(i[1:])), (
            f"{stem}: nothing hops, so the edges must come out in stream order"
        )
    else:
        assert marked, f"{stem}: no run marked, so this case proves nothing"
        assert set(jumps.values()) == {style}, (
            f"{stem}: exported as {sorted(set(jumps.values()))}, drawn as {style}"
        )
    drawn = _drawio_hops(edges)
    sheet = _sheet_hops(fs, fit, style=style)
    assert drawn <= sheet, f"{stem}: draw.io alone hops {sorted(drawn - sheet)} at {style!r}"
    assert len(sheet - drawn) == len([w for w in fs.warnings if w.code == HOP_DROPPED]), (
        f"{stem}: {len(sheet - drawn)} crossing(s) exported flat"
    )


@pytest.mark.parametrize("direction", ["vertical", "horizontal"])
def test_jump_direction_picks_which_of_two_crossing_lines_hops(direction):
    """Apply the configured jump direction to the crossing stream."""
    fs = Flowsheet("jump")
    a = fs.add(units.Feed("F1")).pin(x=60, y=175)
    b = fs.add(units.Product("P1")).pin(x=600, y=175)
    c = fs.add(units.Feed("F2")).pin(x=60, y=375)
    d = fs.add(units.Product("P2")).pin(x=600, y=375)
    fs.connect(a.outlet, b.inlet)
    fs.connect(c.outlet, d.inlet).via([(300, 400), (300, 100), (400, 100), (400, 400)])
    fs.layout()
    fs.route()
    fs.renumber_streams()
    root = ET.fromstring(fs.to_drawio(jump_direction=direction, check=False)).find(
        "diagram/mxGraphModel/root"
    )
    edges, fit = _edge_lines(fs, {}, root)
    hops = _drawio_hops(edges)
    assert hops, f"{direction}: nothing hops a sheet with two lines crossing on it"
    assert hops == _sheet_hops(fs, fit, direction)
    # Each direction selects a different hopping stream.
    assert {hop for hop, _crossed, _x, _y in hops} == (
        {"s1"} if direction == "vertical" else {"s0"}
    )


def test_a_run_that_crosses_itself_is_marked_on_the_sheet_and_reported_by_drawio():
    """Report the self-crossing draw.io cannot hop, which the sheet marks."""
    fs = Flowsheet("loop")
    a = fs.add(units.Feed("F1")).pin(x=60, y=175)
    b = fs.add(units.Product("P1")).pin(x=600, y=175)
    fs.connect(a.outlet, b.inlet).via(
        [(300, 175), (300, 100), (200, 100), (200, 300), (400, 300), (400, 175)]
    )
    fs.layout()
    fs.route()
    assert [(h.x, h.y) for h in stream_hops(fs, "vertical")] == [(200, 175)]
    root = ET.fromstring(fs.to_drawio(check=False)).find("diagram/mxGraphModel/root")
    edges, _fit = _edge_lines(fs, {}, root)
    assert not _drawio_hops(edges), "draw.io never hops an edge over itself"
    dropped = [w for w in fs.warnings if w.code == HOP_DROPPED]
    assert len(dropped) == 1 and "crosses itself" in dropped[0].message


def test_the_hop_is_the_radius_the_sheet_draws_it_at(settled_gallery):
    """Match exported jump size to the rendered hop radius."""
    from pandid.render.svg import HOP_R

    fs, kwargs = copy_settled_case(settled_gallery, "10_ethanol_pid")
    # Select arcs explicitly to check their exported radius.
    fs.to_svg(**kwargs, crossing_style="arc")
    _boxes, _frame, fit = _drawio_furniture(fs, dict(kwargs, crossing_style="arc"))
    cells = _drawio_cells(fs, dict(kwargs, crossing_style="arc"))
    hopping = [c for c in cells.values() if _style(c).get("jumpStyle", "none") != "none"]
    assert len(hopping) == 6, "10_ethanol_pid has six runs that hop another"
    for cell in hopping:
        style = _style(cell)
        assert style["jumpStyle"] == "arc", "the sheet hops with a semicircle"
        size = float(style["jumpSize"])
        assert size == int(size), "parseInt truncates a fractional jumpSize"
        weight = float(style["strokeWidth"])
        radius = (size - 2) / 2 + weight
        # Within the half unit rounding jumpSize to an integer can cost.
        assert radius == pytest.approx(fit.length(HOP_R), abs=0.5)


def test_only_a_stream_hops_or_is_hopped(rendered_gallery):
    """Restrict line jumps to stream crossings."""
    cells = _gallery_cells(rendered_gallery, "10_ethanol_pid")
    edges = {cid: c for cid, c in cells.items() if c.get("edge") == "1"}
    assert edges, "no edges at all"
    for cid, cell in edges.items():
        stream = cid.startswith("s") and cid[1:].isdigit()
        assert (_style(cell).get("noJump") == "1") != stream, cid


def test_a_run_is_written_before_the_run_that_hops_it():
    """Write a hopped run before the stream that jumps it."""
    order, hops, _lost = _hops(
        {"h": [(0.0, 10.0), (30.0, 10.0)], "v": [(15.0, 0.0), (15.0, 20.0)]},
        "vertical",
    )
    assert hops == {"v"}, "the vertical run hops the horizontal one"
    assert order.index("h") < order.index("v"), "the hopper is written first"


def _drawn(polylines, order, hops):
    """Calculate hops visible after applying edge order."""
    rank = {key: n for n, key in enumerate(order)}
    seg = {
        key: (
            [
                (min(a[0], b[0]), max(a[0], b[0]), a[1])
                for a, b in zip(pts, pts[1:])
                if a[1] == b[1] and a[0] != b[0]
            ],
            [
                (min(a[1], b[1]), max(a[1], b[1]), a[0])
                for a, b in zip(pts, pts[1:])
                if a[0] == b[0] and a[1] != b[1]
            ],
        )
        for key, pts in polylines.items()
    }
    out = set()
    for hopper in hops:
        for other in polylines:
            if other == hopper or rank[other] >= rank[hopper]:
                continue
            for lo, hi, at in seg[hopper][1]:  # hopper's verticals
                for c_lo, c_hi, c_at in seg[other][0]:  # other's horizontals
                    if c_lo < at < c_hi and lo < c_at < hi:
                        out.add((hopper, other))
    return out


def test_two_runs_that_each_hop_the_other_draw_no_hop_at_all():
    """Suppress jumps when two runs require conflicting draw order."""
    polylines = {
        "a": [(0.0, 10.0), (20.0, 10.0), (20.0, 30.0)],
        "b": [(10.0, 0.0), (10.0, 20.0), (30.0, 20.0)],
    }
    order, hops, lost = _hops(polylines, "vertical")
    assert sorted(order) == ["a", "b"], "every edge is still written once"
    assert _drawn(polylines, order, hops) == set(), (
        "a cycle drew a hop, and one of the two can only be the wrong way round"
    )
    # Count both crossing points in the ordering cycle.
    assert len(lost) == 2, f"a cycle lost 2 crossings and named {len(lost)}"
    assert {(hop, crossed) for hop, crossed, _x, _y in lost} == {("a", "b"), ("b", "a")}
    assert len({(x, y) for _h, _c, x, y in lost}) == 2, "at two different points"


def test_a_cycle_costs_only_the_runs_inside_it():
    """Retain jumps outside a conflicting draw-order cycle."""
    polylines = {
        "a": [(0.0, 10.0), (20.0, 10.0), (20.0, 30.0)],
        "b": [(10.0, 0.0), (10.0, 20.0), (30.0, 20.0)],
        "h": [(100.0, 10.0), (130.0, 10.0)],
        "c": [(115.0, 0.0), (115.0, 20.0)],
    }
    order, hops, _lost = _hops(polylines, "vertical")
    assert _drawn(polylines, order, hops) == {("c", "h")}


# The committed samples, and the script that makes them.


def test_a_version_bump_changes_only_sample_provenance(monkeypatch):
    """Keep generated sample structure independent of generator provenance."""
    samples = _script("drawio_samples")
    current, _dropped = samples.sample("03_control_loop")
    monkeypatch.setattr(pandid, "__version__", "99.99.99")
    bumped, _dropped = samples.sample("03_control_loop")

    assert current != bumped, "the generator version is absent from the sample"
    agent = re.compile(r'(<mxfile\b[^>]*\bagent=)"[^"]*"')
    assert agent.sub(r"\1", current) == agent.sub(r"\1", bumped)


# Compositions: the two backends drawing the same thing.


_COMPOSED = [
    units.Reactor("R-101"),
    units.Reactor("R-102", agitator="turbine"),
    units.Reactor("R-103", variant="jacketed", agitator="propeller"),
    units.Reactor("R-201", internals="packing", agitator=None),
    units.Reactor("R-202", internals="fluidised_bed", agitator="anchor"),
    units.Column("T-101", internals="tray"),
    units.Column("T-102", internals="bubble_cap_tray", trays=6),
    units.Column("T-103", internals="packing", trays=2),
    units.Vessel("D-301", supports="leg"),
    units.Vessel("D-302", supports="skirt"),
    units.Vessel("D-303", supports="bracket"),
    units.Vessel("D-304", supports="ring"),
    units.Separator("V-201", characteristic="gravity"),
    units.Separator("V-202", characteristic="electrostatic"),
    units.Separator("V-203", characteristic="electromagnetic"),
]


COMPOSED_IDS = [f"{u.kind}/{u.name}" for u in _COMPOSED]


@pytest.fixture(scope="module")
def composed_sheet() -> Flowsheet:
    """Place every composed symbol on a test sheet."""
    fs = Flowsheet("compositions")
    for i, unit in enumerate(_COMPOSED):
        fs.add(unit).pin(x=(i % 5) * 400.0, y=(i // 5) * 400.0)
    fs.layout()
    return fs


def test_a_composed_symbol_names_no_stencil_of_its_own(composed_sheet):
    """Render composed symbols from their constituent parts."""
    for unit in composed_sheet.units:
        sym = default_registry.for_unit(unit)
        assert sym.overlays, f"{unit.name} is not composed; the fixture is wrong"
        assert sym.drawio_shape == "", (
            f"{unit.name} carries a stencil reference for the whole composition"
        )


@pytest.mark.parametrize("index", range(len(COMPOSED_IDS)), ids=COMPOSED_IDS)
def test_both_backends_draw_the_same_parts_in_the_same_places(composed_sheet, index):
    """Match composed part geometry across both renderers."""
    unit = composed_sheet.units[index]
    sym = default_registry.for_unit(unit)
    cells = _cells(composed_sheet, check=False)
    cid = next(
        k
        for k, cell in cells.items()
        if cell.get("value") == unit.name and cell.get("vertex") == "1"
    )
    parent = cells[cid].find("mxGeometry")
    w, h = float(parent.get("width")), float(parent.get("height"))

    children = [cell for key, cell in cells.items() if key.startswith(f"{cid}-p")]
    assert len(children) == len(sym.overlays), (
        f"{unit.name}: the sheet draws {len(sym.overlays)} parts, the export {len(children)}"
    )
    # The SVG draws at least as many parts.
    inner = _GROUP.match(sym.svg).group(2)
    assert inner.count("<g transform=") >= len(sym.overlays)

    for overlay, cell in zip(sym.overlays, children):
        box = cell.find("mxGeometry")
        got = tuple(float(box.get(k)) for k in ("x", "y", "width", "height"))
        want = (overlay.x * w, overlay.y * h, overlay.w * w, overlay.h * h)
        assert got == pytest.approx(want, abs=0.02), f"{unit.name}: {overlay.group}/{overlay.name}"
        assert _style(cell)["movable"] == "0" and _style(cell)["connectable"] == "0"


def test_a_composed_symbol_still_draws_its_body(composed_sheet):
    """Keep the base symbol visible beneath its composed parts."""
    cells = _cells(composed_sheet, check=False)
    for unit in composed_sheet.units:
        sym = default_registry.for_unit(unit)
        cell = next(
            c for k, c in cells.items() if c.get("value") == unit.name and c.get("vertex") == "1"
        )
        style = _style(cell)
        if sym.drawio_body_shape:
            assert style.get("shape") == sym.drawio_body_shape
        else:
            key = (unit.kind, getattr(unit, "variant", "default"))
            assert key in _APPROXIMATIONS, f"{key} exports as an undocumented box"


@pytest.mark.parametrize(
    "part",
    sorted(default_registry.parts(), key=lambda p: p.key()),
    ids=lambda p: f"{p.iso.group}/{p.name}",
)
def test_every_part_resolves_to_a_stencil_or_a_documented_built_in(part):
    """Resolve each composed part to a known shape."""
    if part.drawio_shape:
        assert part.drawio_shape in STENCIL_KEYS, f"{part.iso.group}/{part.name}"
        assert part.key() not in _PART_APPROXIMATIONS, (
            "approximating a part that has a stencil throws the real shape away"
        )
        return
    assert part.key() in _PART_APPROXIMATIONS, (
        f"{part.iso.group}/{part.name} has no stencil and no approximation"
    )
    assert _PART_APPROXIMATIONS[part.key()].shape in _BUILTIN_SHAPES


def test_the_part_table_names_only_parts_that_exist():
    """Check each part approximation names a registered part."""
    registered = {p.key() for p in default_registry.parts()}
    assert set(_PART_APPROXIMATIONS) <= registered, sorted(set(_PART_APPROXIMATIONS) - registered)


def test_an_annotation_of_empty_rows_exports() -> None:
    """Export an annotation whose rows have no cells."""
    from pandid.document import Annotation

    fs = Flowsheet("Empty notes")
    fs.annotations.append(Annotation(title="NOTES", rows=[(), ()]))

    ET.fromstring(fs.to_drawio(check=False))
