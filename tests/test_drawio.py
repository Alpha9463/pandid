"""The draw.io export, and the one thing about it that cannot be tested here.

**draw.io is not run.** Nothing in this file opens the exported document in
draw.io or in anything else that speaks mxGraph, so nothing here is evidence
that a sheet *looks right* when a reader opens one. What is left is still worth
having, and it is the part that fails silently:

* the document parses, and is the ``mxfile > diagram > mxGraphModel > root``
  shape draw.io reads, with every cell parented and every edge joining two cells
  that exist;
* **every shape reference resolves.** This is the check the whole export turns
  on. draw.io answers a ``shape=`` it cannot resolve with a plain rectangle
  rather than an error, so a mistyped, stale or invented key produces a file
  that opens perfectly and has quietly stopped being a P&ID. Every symbol the
  library can draw is walked, and each reference is held against the shape keys
  built *here*, from the vendored stencil XML, by draw.io's own rule -- deriving
  them again rather than calling the generator's function, so that a bug in the
  rule has to be made twice to pass;
* the geometry is the SVG renderer's. Every box, every waypoint and every
  connection point is compared against what :mod:`pandid.render.svg` and
  :mod:`pandid.portgeom` compute for the same sheet, so the exported drawing and
  the rendered one cannot drift apart.

The connection-point check needs one caveat of its own. It applies *this file's
model* of how draw.io resolves a fixed connection point -- fraction of the box,
then the cell's flips -- and asserts the emitted fractions land back on the
nozzle. That catches an inverted flip or a fraction taken against the wrong box,
which is what it is for. It cannot catch a mistake in the model itself; only
opening the file can.
"""

from __future__ import annotations

import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

from pandid import units
from pandid.flowsheet import Flowsheet
from pandid.portgeom import port_point, unit_box
from pandid.render.drawio import _APPROXIMATIONS, DrawioRenderer
from pandid.render.svg import stream_polyline
from pandid.render.symbols import Symbol, default_registry, expander

ROOT = pathlib.Path(__file__).resolve().parent.parent
STENCILS = ROOT / "scripts" / "vendor_data" / "drawio"

#: mxGraph's own shapes, compiled into draw.io rather than loaded from a stencil
#: file. The approximations may name these and nothing else: the point of an
#: approximation is to be a shape that is certainly there, and a built-in is the
#: only kind of name that cannot go stale. ``None`` is draw.io's default vertex,
#: a plain rectangle.
_BUILTIN_SHAPES = {None, "ellipse", "rhombus", "hexagon", "triangle", "line"}


# ---------------------------------------------------------------------------
# The stencil keys draw.io actually answers to, derived here from the XML.
# ---------------------------------------------------------------------------


def _stencil_keys() -> set[str]:
    """Every shape key the vendored stencil files define.

    mxGraph's ``mxStencilRegistry.parseStencilSet`` files a shape under the
    package on the set's root element and the shape's own name, spaces
    underscored, the pair lowercased. That rule is implemented here rather than
    imported from ``scripts/vendor_symbols.py``, deliberately: importing it
    would compare the generator against itself, and every key in the library
    would agree with every key in the library whatever the rule said.
    """
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
    """Every symbol the library can put on a sheet, with the key it is filed by.

    Three sets, because ``SymbolRegistry.for_unit`` can hand back any of them
    and each is a different drawing: the registered symbol for a
    ``(kind, variant)``; the second drawing a device with two positions has (a
    spectacle blind's solid disc); and a fitting turned end for end, which is
    what a reducer becomes when its large face is its outlet. A reference that
    resolved for the first and not the third would draw two of the three
    correctly, which is the kind of gap an exhaustive walk exists to close.
    """
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
def test_every_shape_reference_resolves_to_a_vendored_stencil(entry):
    """The check the export turns on; see this module's docstring."""
    kind, variant, sym = entry
    if not sym.drawio_shape:
        pytest.skip("drawn here rather than vendored; the approximations cover it")
    assert sym.drawio_shape in STENCIL_KEYS, (
        f"{kind}/{variant} references {sym.drawio_shape!r}, which no vendored "
        f"stencil defines. draw.io answers an unresolvable shape with a plain "
        f"rectangle and no error, so this would export a sheet of boxes."
    )


@pytest.mark.parametrize("entry", DRAWINGS, ids=DRAWING_IDS)
def test_a_symbol_with_no_stencil_is_an_approximation_that_was_written_down(entry):
    """Nothing degrades without a sentence saying what it lost.

    A symbol with neither a stencil reference nor an entry in the table exports
    as a bare rectangle by falling through, which is the same file a documented
    rectangle produces and a very different claim about it.
    """
    kind, variant, sym = entry
    if sym.drawio_shape:
        return
    base = variant.split(" [")[0]
    assert (kind, base) in _APPROXIMATIONS, (
        f"{kind}/{base} has no draw.io stencil behind it and no entry in "
        f"pandid.render.drawio._APPROXIMATIONS, so it would export as an "
        f"undocumented rectangle"
    )
    assert _APPROXIMATIONS[(kind, base)].shape in _BUILTIN_SHAPES


@pytest.mark.parametrize("entry", DRAWINGS, ids=DRAWING_IDS)
def test_a_shape_key_survives_being_written_into_a_style(entry):
    """A draw.io style is ``key=value`` pairs split on ``;``.

    Forty-eight of the vendored shape names carry punctuation upstream put
    there -- "Tank (Dished Roof)", "Rotary Drum Drier, Tumbling Drier",
    "Y-Type Strainer" -- and all of it travels into the key, because draw.io
    builds its own key by the same rule and looks the result up exactly. Commas,
    parentheses and hyphens are all safe in a style value. A ``;`` or an ``=``
    would not be: one would end the key early and the other would split it, and
    what draw.io would then fail to resolve is a name that never appears
    anywhere to be searched for.
    """
    _, _, sym = entry
    assert ";" not in sym.drawio_shape and "=" not in sym.drawio_shape


def test_the_approximations_name_only_shapes_and_symbols_that_exist():
    """The table is data, and stale data here is a silent wrong drawing."""
    for (kind, variant), approx in _APPROXIMATIONS.items():
        assert (kind, variant) in default_registry._symbols, (
            f"_APPROXIMATIONS names {kind}/{variant}, which the registry does not draw"
        )
        assert not default_registry._symbols[(kind, variant)].drawio_shape, (
            f"{kind}/{variant} has a draw.io stencil of its own, so approximating "
            f"it throws the real shape away"
        )
        assert approx.shape in _BUILTIN_SHAPES, (
            f"{kind}/{variant} is approximated with {approx.shape!r}, which is not "
            f"an mxGraph built-in; a stencil key here could go stale, and the "
            f"whole point of an approximation is a shape that is certainly there"
        )


def test_a_referenced_stencil_is_always_variable_aspect():
    """What makes the box the whole of the size mapping.

    draw.io stretches a ``variable`` stencil to fill the cell and centres a
    ``fixed`` one uniformly inside it, which is exactly what
    :func:`pandid.portgeom.ink_box` does with
    :attr:`~pandid.render.symbols.Symbol.stretchable` -- that flag *is* the
    stencil's aspect. So for a ``variable`` shape, handing draw.io the placed box
    reproduces the sheet whatever ``SCALE`` in ``scripts/vendor_symbols.py`` did
    to the symbol's proportions on the way in.

    A ``fixed`` one is where that stops being true, and only when its ``SCALE``
    is uneven: pandid would centre against the reproportioned box and draw.io
    against the stencil's own, and the two would land at different sizes. None
    is both today. Should one arrive, the exporter has to map the box rather
    than copy it, and this is the test that says so.
    """
    for kind, variant, sym in DRAWINGS:
        if sym.drawio_shape:
            assert sym.stretchable, (
                f"{kind}/{variant} references a fixed-aspect stencil. Check its "
                f"SCALE entry: if it is uneven, the exported box has to be mapped "
                f"onto the stencil's own aspect rather than copied."
            )


# ---------------------------------------------------------------------------
# A sheet carrying one of everything.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def every_symbol_sheet() -> Flowsheet:
    """One unit of every registered ``(kind, variant)``, pinned on a grid.

    Unconnected and un-routed on purpose: what this sheet is for is the *shape*
    each unit exports as, and one of every symbol in the catalogue is a thing no
    real flowsheet is. The streams are exercised by the examples below, which are
    real sheets.
    """
    fs = Flowsheet("every symbol")
    n = 0
    for name in units.__all__:
        cls = getattr(units, name)
        for variant in default_registry.variants(cls.kind):
            unit = cls(f"{cls.kind[:3].upper()}-{n}", variant=variant)
            fs.add(unit)
            unit.pin(x=(n % 12) * 300.0, y=(n // 12) * 300.0)
            n += 1
    fs.layout()
    return fs


def test_the_sheet_covers_every_registered_symbol(every_symbol_sheet):
    """The fixture is only worth its runtime if it really is exhaustive."""
    drawn = {(u.kind, getattr(u, "variant", "default")) for u in every_symbol_sheet.units}
    assert drawn == set(default_registry._symbols)


def test_an_exported_sheet_references_only_shapes_that_resolve(every_symbol_sheet):
    """End to end: parse the document back and check every ``shape=`` in it."""
    doc = ET.fromstring(every_symbol_sheet.to_drawio(check=False))
    shapes = set()
    for cell in doc.iter("mxCell"):
        for key in cell.get("style", "").split(";"):
            if key.startswith("shape="):
                shapes.add(key[len("shape=") :])
    assert shapes, "no shape references at all -- the sheet exported as blank boxes"
    unresolved = sorted(s for s in shapes if s not in STENCIL_KEYS and s not in _BUILTIN_SHAPES)
    assert not unresolved, f"unresolvable shape references: {unresolved}"


# ---------------------------------------------------------------------------
# The document draw.io expects.
# ---------------------------------------------------------------------------


def _model(fs: Flowsheet, **kwargs) -> ET.Element:
    """The ``<root>`` of a fresh export, after checking the frame around it."""
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
    """A small sheet with a feed, a pump, a control valve, a tank and a balloon."""
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
    ft = fs.add_instrument("FT", 101, on=line, at=0.5, offset=60)
    fs.connect(ft.sig_out, valve.actuator, kind="electric")
    fs.route()
    return fs


def test_the_model_carries_drawios_two_root_cells(sample):
    root = _model(sample)
    cells = root.findall("mxCell")
    assert cells[0].get("id") == "0" and cells[0].get("parent") is None
    assert cells[1].get("id") == "1" and cells[1].get("parent") == "0"


def test_every_drawn_cell_is_parented_and_uniquely_identified(sample):
    root = _model(sample)
    ids = [cell.get("id") for cell in root.findall("mxCell")]
    assert len(ids) == len(set(ids)), "two cells under one id"
    for cell in root.findall("mxCell")[2:]:
        assert cell.get("parent") == "1", f"cell {cell.get('id')} is parented nowhere"
        assert (cell.get("vertex") == "1") != (cell.get("edge") == "1"), (
            f"cell {cell.get('id')} is neither a vertex nor an edge, or is both"
        )
        assert len(cell.findall("mxGeometry")) == 1


def test_every_edge_joins_two_cells_that_exist(sample):
    root = _model(sample)
    ids = {cell.get("id") for cell in root.findall("mxCell")}
    edges = [c for c in root.findall("mxCell") if c.get("edge") == "1"]
    assert len(edges) == len(sample.streams)
    for edge in edges:
        assert edge.get("source") in ids
        assert edge.get("target") in ids


def test_the_export_is_deterministic(sample):
    """A re-export that differs from itself is a diff nobody can read."""
    assert sample.to_drawio() == sample.to_drawio()


def test_the_backend_is_a_renderer_in_its_own_right(sample):
    """A backend beside SvgRenderer rather than a converter bolted onto one, so
    it answers :class:`pandid.render.Renderer` and can be called directly."""
    assert DrawioRenderer().render(sample) == sample.to_drawio(check=False)


# ---------------------------------------------------------------------------
# The geometry, against the renderer's.
# ---------------------------------------------------------------------------


def _cells(fs: Flowsheet, **kwargs) -> dict[str, ET.Element]:
    return {cell.get("id"): cell for cell in _model(fs, **kwargs).findall("mxCell")}


def _style(cell: ET.Element) -> dict[str, str]:
    out = {}
    for key in cell.get("style", "").split(";"):
        if key:
            name, _, value = key.partition("=")
            out[name] = value
    return out


def test_a_units_box_is_the_box_the_renderer_draws_it_in(sample):
    cells = _cells(sample)
    for i, u in enumerate(sample.units):
        geometry = cells[f"u{i}"].find("mxGeometry")
        x0, y0, x1, y1 = unit_box(u, u.frame)
        assert float(geometry.get("x")) == pytest.approx(x0, abs=0.01)
        assert float(geometry.get("y")) == pytest.approx(y0, abs=0.01)
        assert float(geometry.get("width")) == pytest.approx(x1 - x0, abs=0.01)
        assert float(geometry.get("height")) == pytest.approx(y1 - y0, abs=0.01)


def test_an_edges_waypoints_are_the_line_the_renderer_draws(sample):
    """The turns in the route, and only the turns: the ends are the nozzles."""
    cells = _cells(sample)
    for n, s in enumerate(sample.streams):
        drawn = stream_polyline(s)
        array = cells[f"s{n}"].find("mxGeometry/Array")
        emitted = (
            [(float(p.get("x")), float(p.get("y"))) for p in array.findall("mxPoint")]
            if array is not None
            else []
        )
        assert len(emitted) == len(drawn) - 2, (
            f"{s.name}: {len(emitted)} waypoints for a line drawn through {len(drawn)} points"
        )
        for (ex, ey), (dx, dy) in zip(emitted, drawn[1:-1]):
            assert (ex, ey) == pytest.approx((dx, dy), abs=0.01)


def _drawio_connection_point(unit, vertex: dict, edge: dict, prefix: str) -> tuple[float, float]:
    """Where draw.io lands one of these fixed connection points.

    This file's model of ``mxGraph.getConnectionPoint``. It reads the two style
    dicts apart because mxGraph does: the constraint and whether it is projected
    onto the perimeter come off the **edge**, and the shape's own direction,
    flips and ``anchorPointDirection`` come off the **vertex** being connected
    to. Writing an anchor key on the wrong one of the two is a mistake with no
    symptom until the file is opened, which is what this reproduction is for.

    With ``anchorPointDirection=0`` the cell's ``direction`` leaves the bounds
    alone, so the fraction is of the box as placed; with ``<prefix>Perimeter=0``
    the point is taken as given instead of being pushed out to the outline. What
    is left is the fraction, then the vertex's own flips about the box centre.

    A model, and only a model -- see this module's docstring.
    """
    assert edge[f"{prefix}Perimeter"] == "0"
    if "direction" in vertex:
        assert vertex["anchorPointDirection"] == "0", (
            "a turned shape turns its anchors with it unless told not to"
        )
    x0, y0, x1, y1 = unit_box(unit, unit.frame)
    fx, fy = float(edge[f"{prefix}X"]), float(edge[f"{prefix}Y"])
    if vertex.get("flipH") == "1":
        fx = 1.0 - fx
    if vertex.get("flipV") == "1":
        fy = 1.0 - fy
    return (x0 + fx * (x1 - x0), y0 + fy * (y1 - y0))


@pytest.mark.parametrize("orientation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirrored", [False, True, "y", "xy"])
def test_a_connection_point_resolves_back_onto_its_nozzle(orientation, mirrored):
    """Every placement a unit can take, checked against the drawn nozzle.

    A vessel rather than a valve, because a vessel has nozzles on four faces and
    an uneven box, so an inverted flip or a fraction taken against the wrong axis
    has somewhere to show.
    """
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
                f"{port.owner.name}.{port.name} at orientation={orientation} "
                f"mirrored={mirrored!r}: the {prefix} constraint lands at {landed}, "
                f"and the nozzle is drawn at {drawn}"
            )


# ---------------------------------------------------------------------------
# What the style says about a placement.
# ---------------------------------------------------------------------------


def _one_unit(unit, **pin) -> dict[str, str]:
    """One unit's exported style, on a sheet of its own."""
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
    """pandid turns clockwise; draw.io names where the shape's east ended up."""
    style = _one_unit(units.Pump("P-1"), x=100, y=100, orientation=orientation)
    assert style.get("direction") == direction


def test_a_mirror_exports_as_a_flip():
    style = _one_unit(units.Pump("P-1"), x=100, y=100, mirrored="xy")
    assert style.get("flipH") == "1" and style.get("flipV") == "1"


def test_a_directional_symbol_is_never_flipped():
    """A cooler flipped is not a cooler: it is the heater, drawn where a cooler
    was asked for. The renderer holds such a drawing still under a flip and
    moves only its nozzles, and the export has to say the same thing -- the
    nozzles are stated as coordinates, so nothing is lost by leaving the shape
    alone."""
    directional = [(k, v) for (k, v), s in default_registry._symbols.items() if s.directional]
    assert directional, "no directional symbol left to check this against"
    for kind, variant in directional:
        cls = next(getattr(units, n) for n in units.__all__ if getattr(units, n).kind == kind)
        style = _one_unit(cls("X-1", variant=variant), x=100, y=100, mirrored="xy")
        assert "flipH" not in style and "flipV" not in style, (
            f"{kind}/{variant} states a direction in its artwork and was exported flipped"
        )


def test_a_normally_closed_valve_exports_its_body_filled():
    """The darkening is what says the line is shut; a reference alone would name
    the open valve."""
    style = _one_unit(units.Valve("HV-1", variant="gate", normal_position="closed"), x=100, y=100)
    assert style["shape"] == "mxgraph.pid.valves.gate_valve"
    assert style["fillColor"] == "#111"


def test_an_expander_exports_its_stencil_mirrored():
    """A reducer and an expander are one casting piped either way round, and the
    cone has to point the way the run opens out."""
    reduction = _one_unit(units.Reducer("R-1", large_end="inlet"), x=100, y=100)
    expansion = _one_unit(units.Reducer("R-2", large_end="outlet"), x=100, y=100)
    assert reduction["shape"] == expansion["shape"]
    assert "flipH" not in reduction
    assert expansion["flipH"] == "1"


def test_a_balloon_carries_its_letters_over_its_number():
    fs = Flowsheet("balloon")
    ft = fs.add_instrument("FT", 101)
    ft.pin(x=100, y=100)
    fs.layout()
    cell = _cells(fs, check=False)["u0"]
    assert cell.get("value") == "FT<br>101"
    style = _style(cell)
    assert style["shape"] == "ellipse"
    # Opaque, as the symbol's own artwork is: a balloon is drawn over the line
    # it reads, and a transparent one has that line running through its tag.
    assert style["fillColor"] == "#ffffff"


def test_only_the_balloons_are_drawn_opaque():
    """Everything else on the sheet is an outline that lets the paper through,
    which is what ``scripts/mxgraph_to_svg.py`` converts every stencil under."""
    from pandid.render.drawio import _APPROXIMATIONS as table

    for (kind, variant), approx in table.items():
        expected = "#ffffff" if kind == "instrument" else "none"
        assert approx.fill == expected, f"{kind}/{variant} fills with {approx.fill!r}"


def test_a_mirrored_expander_is_the_reducer_drawn_as_vendored():
    """Two mirrors compose to none, and the nozzles still move.

    A reducer piped the other way round already draws its stencil mirrored, so a
    placement that mirrors it again asks for the artwork as vendored -- with the
    run entering from the other end, which the connection points say and the
    shape does not.
    """
    style = _one_unit(units.Reducer("R-1", large_end="outlet"), x=100, y=100, mirrored=True)
    assert "flipH" not in style


def test_a_diamond_balloon_carries_its_number_alone():
    """As the sheet draws it: an interlock square's letters are only the tag
    prefix, and a diamond has no room under them."""
    fs = Flowsheet("interlock")
    square = fs.add(units.Instrument("Z", 301, variant="interlock"))
    square.pin(x=100, y=100)
    fs.layout()
    cell = _cells(fs, check=False)["u0"]
    assert cell.get("value") == "301"
    assert _style(cell)["shape"] == "rhombus"


def test_a_unit_from_outside_the_package_exports_as_the_box_it_draws(gapped_kind):
    """No artwork, no stencil, no approximation -- and still a cell, because the
    sheet draws a generic box there and draw.io's default vertex is one."""
    fs = Flowsheet("foreign")
    unit = fs.add(gapped_kind("X-1"))
    unit.pin(x=100, y=100)
    fs.layout()
    style = _style(_cells(fs, check=False)["u0"])
    assert "shape" not in style
    assert style["rounded"] == "0"


def test_an_empty_flowsheet_still_exports_a_document():
    """Nothing to draw is a document with nothing in it, not a traceback."""
    root = _model(Flowsheet("empty"), check=False)
    assert [c.get("id") for c in root.findall("mxCell")] == ["0", "1"]


def test_a_repeated_tag_gets_a_cell_of_its_own():
    """An interlock square is one piece of logic drawn wherever it acts, so a
    tag repeats. Two cells under one id is a file draw.io reads as one cell."""
    fs = Flowsheet("repeats")
    for n in range(3):
        square = fs.add(units.Instrument("Z", 1, variant="interlock"))
        square.pin(x=100 + 120 * n, y=100)
    fs.layout()
    root = _model(fs, check=False)
    ids = [c.get("id") for c in root.findall("mxCell")]
    assert len(ids) == len(set(ids))
    assert len(ids) == 2 + 3


def test_an_off_page_flag_keeps_its_tag_and_its_reference():
    fs = Flowsheet("boundary")
    feed = fs.add(units.Feed("FEED", reference="P-01"))
    feed.pin(x=100, y=100)
    fs.layout()
    assert _cells(fs, check=False)["u0"].get("value") == "FEED<br>P-01"


# ---------------------------------------------------------------------------
# Streams: weight, dash and arrowhead.
# ---------------------------------------------------------------------------


def test_a_signal_line_is_dashed_and_drawn_at_half_the_weight_of_pipe(sample):
    cells = _cells(sample)
    weights = {}
    for n, s in enumerate(sample.streams):
        weights[s.kind] = _style(cells[f"s{n}"])
    assert weights["material"]["strokeWidth"] == "2"
    assert weights["electric"]["strokeWidth"] == "1"
    assert weights["electric"]["dashed"] == "1"
    assert weights["electric"]["dashPattern"] == "7 4"
    assert "dashed" not in weights["material"]
    assert weights["material"]["strokeColor"] == "#000000"


def test_a_pfd_exports_arrowheads_and_a_p_and_id_does_not(sample):
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
    """A number names a run, and a run survives the valves in it."""
    cells = _cells(sample)
    labels = [cells[f"s{n}"].get("value") for n in range(len(sample.streams))]
    written = [label for label in labels if label]
    assert len(written) == len(set(written)), f"a number written twice: {written}"
    assert set(written) == {s.name for s in sample.streams if s.kind == "material"}


# ---------------------------------------------------------------------------
# Sheet furniture, and the options a model has no room for.
# ---------------------------------------------------------------------------


def test_a_title_block_exports_as_a_box_carrying_its_fields():
    """Degraded, not dropped: a sheet that loses its drawing number on the way
    out is worse than one whose title block landed in the wrong place."""
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
    cells = _cells(fs, check=False)
    box = cells["f0"]
    value = box.get("value")
    assert "Ethanol Purification" in value
    assert "A-301" in value and "Acme" in value and "2026-01-02" in value
    assert box.get("vertex") == "1"


@pytest.mark.parametrize(
    "option,value",
    [
        ("show_stream_table", True),
        ("border", "zone"),
        ("page_size", "A3"),
        ("jump_direction", "horizontal"),
        ("debug", True),
    ],
)
def test_render_refuses_a_sheet_option_it_cannot_honour(tmp_path, sample, option, value):
    """Accepting and ignoring these would tell the caller something false about
    the file they now hold."""
    with pytest.raises(ValueError, match=option):
        sample.render(tmp_path / "sheet.drawio", **{option: value})


def test_render_writes_the_document_to_a_drawio_path(tmp_path, sample):
    out = tmp_path / "sheet.drawio"
    sample.render(out)
    text = out.read_text(encoding="utf-8")
    assert text == sample.to_drawio()
    ET.fromstring(text)


def test_an_unsupported_extension_still_names_drawio_among_the_options(tmp_path, sample):
    with pytest.raises(ValueError, match=r"\.drawio"):
        sample.render(tmp_path / "sheet.dwg")


# ---------------------------------------------------------------------------
# The shipped examples, which are the only real sheets in reach.
# ---------------------------------------------------------------------------


def _gallery():
    path = ROOT / "scripts" / "gallery.py"
    spec = importlib.util.spec_from_file_location("_pandid_script_gallery_drawio", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gallery = _gallery()
SHEETS = gallery.sheets()


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_every_example_exports_a_document_that_matches_its_sheet(stem):
    """Twelve real sheets: parsed back, with every box, waypoint and shape
    reference held against the drawing the same flowsheet renders."""
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)  # settle layout and routing exactly as the sheet does
    root = ET.fromstring(fs.to_drawio(diagram=kwargs.get("diagram")))
    cells = {cell.get("id"): cell for cell in root.iter("mxCell")}

    at = {}
    for i, u in enumerate(fs.units):
        geometry = cells[f"u{i}"].find("mxGeometry")
        x0, y0, x1, y1 = unit_box(u, u.frame)
        assert float(geometry.get("x")) == pytest.approx(x0, abs=0.01)
        assert float(geometry.get("y")) == pytest.approx(y0, abs=0.01)
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
            assert landed == pytest.approx(
                port_point(port.owner, port.owner.frame, port.name), abs=0.01
            )
