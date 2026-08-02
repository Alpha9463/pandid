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
from decimal import Decimal
import xml.etree.ElementTree as ET

import pytest

from pandid import units
from pandid.flowsheet import Flowsheet
from pandid.portgeom import port_point, unit_box
from pandid.render.drawio import _APPROXIMATIONS, DrawioRenderer
from pandid.render.svg import (
    _page,
    boundary_flag,
    impulse_tap,
    pneumatic_marks,
    stream_polyline,
    tap_lines,
)
from pandid.render.symbols import Symbol, default_registry, expander

ROOT = pathlib.Path(__file__).resolve().parent.parent
STENCILS = ROOT / "scripts" / "vendor_data" / "drawio"

#: mxGraph's own shapes, registered by ``mxCellRenderer.registerShape`` in
#: mxGraph itself and so present in *any* mxGraph, draw.io included. ``None`` is
#: draw.io's default vertex, a plain rectangle.
_MXGRAPH_SHAPES = {None, "ellipse", "rhombus", "hexagon", "triangle", "line"}

#: draw.io's own shapes, registered the same way but in ``js/grapheditor/
#: Shapes.js``, which is one unconditional IIFE compiled into ``app.min.js``,
#: ``viewer.min.js`` and ``viewer-static.min.js`` alike.
#:
#: These count as built-ins here and the distinction that earns them the name is
#: *compiled in versus loaded from a file*, not *mxGraph versus draw.io*. What
#: this test guards is a reference that fails silently -- and a miss is silent:
#: ``mxCellRenderer.getShapeConstructor`` falls back to ``mxRectangleShape``
#: with no error, no warning and no log. A name in ``Shapes.js`` cannot miss for
#: a file opened in draw.io, which is what a ``.drawio`` file is for; a stencil
#: key can, since ``mxStencilRegistry.getStencil`` fetches
#: ``stencils/<set>.xml`` over the wire on first reference and a 404 registers
#: nothing (and is retried, uncached, for every cell that names it). So this set
#: is *safer* than the stencil references this file already checks, not looser.
_DRAWIO_SHAPES = {"offPageConnector", "table", "tableRow", "partialRectangle"}

#: What an approximation, or anything else this exporter writes, may name.
_BUILTIN_SHAPES = _MXGRAPH_SHAPES | _DRAWIO_SHAPES


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
        for shape in (approx.shape, approx.inscribed):
            assert shape in _BUILTIN_SHAPES or shape is None, (
                f"{kind}/{variant} is approximated with {shape!r}, which is not "
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


def test_every_edge_joins_cells_that_exist(sample):
    root = _model(sample)
    ids = {cell.get("id") for cell in root.findall("mxCell")}
    edges = [c for c in root.findall("mxCell") if c.get("edge") == "1"]
    # Every stream, and every instrument connection: the latter is not a stream
    # and would be dropped by anything that walked fs.streams alone.
    assert len(edges) == len(sample.streams) + len(tap_lines(sample))
    for edge in edges:
        assert edge.get("target") in ids
        # A tap on a *stream* has no cell to hang its far end on -- an edge is
        # not a place -- and states a fixed point instead. Everything else names
        # a cell at both ends.
        if edge.get("source") is None:
            assert edge.find('mxGeometry/mxPoint[@as="sourcePoint"]') is not None
        else:
            assert edge.get("source") in ids


def test_every_instrument_connection_is_exported_as_an_edge(sample):
    """ISO 15519-2 §5.1.1 says the PCI symbol *shall* be connected to the
    process system and to the control system. A balloon floating free of its tap
    is not a conforming P&ID, and the tap line is not a stream, so nothing that
    walks ``fs.streams`` will find it."""
    root = _model(sample)
    drawn = tap_lines(sample)
    assert drawn, "the fixture stopped exercising tap lines"
    taps = {c.get("id"): c for c in root.findall("mxCell") if (c.get("id") or "").startswith("t")}
    assert len(taps) == len(drawn)
    at = {i: _style(c) for i, c in {c.get("id"): c for c in root.findall("mxCell")}.items()}
    for n, (inst, tap, centre) in enumerate(drawn):
        style = _style(taps[f"t{n}"])
        # Solid to the process, dashed to the control system: §5.1.1's two
        # bullets, answered by impulse_tap() and not decided again here.
        assert ("dashed" in style) != impulse_tap(inst)
        # The balloon end lands on the balloon's centre, which is where the
        # sheet runs the line to.
        landed = _drawio_connection_point(inst, at[taps[f"t{n}"].get("target")], style, "entry")
        assert landed == pytest.approx(centre, abs=0.01)
        source = taps[f"t{n}"].get("source")
        if source is None:
            point = taps[f"t{n}"].find('mxGeometry/mxPoint[@as="sourcePoint"]')
            assert (float(point.get("x")), float(point.get("y"))) == pytest.approx(tap, abs=0.01)
        else:
            host = inst.host
            assert _drawio_connection_point(host, at[source], style, "exit") == pytest.approx(
                tap, abs=0.01
            )


def test_an_off_page_flag_is_a_pennant_with_its_tag_inside_it():
    """Two defects at once: the flag drew as a bare rectangle, and its label was
    explicitly placed *above* the shape rather than in it."""
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
        # The point is cut back fifteen units, stated as the fraction of the
        # shape's own height that the quarter turn makes of the cell's width.
        (x0, _, x1, _), depth, _east = boundary_flag(unit, unit.frame)
        assert float(style["size"]) == pytest.approx(depth / (x1 - x0), abs=1e-6)
        # ...and the tag is *in* the flag.
        assert style["verticalLabelPosition"] == "middle"
        assert style["verticalAlign"] == "middle" and style["align"] == "center"
        assert "labelPosition" not in style
    assert cells["u0"].get("value") == "FEED<br>P-01"


def test_a_label_written_inside_its_shape_fits_inside_it():
    """`Fermentation Broth / P&ID-201` was drawn across the top and bottom edges
    of its own pennant: two lines of draw.io's default 12 want 28,8 of line box
    and the flag is 26 deep before the sheet's fitting scales it. Nothing in
    mxGraph shrinks type to fit, so the size has to be chosen against the box."""
    from pandid.render.drawio import _LINE_BOX

    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        cells = _drawio_cells(fs, kwargs)
        for i, unit in enumerate(fs.units):
            cell = cells[f"u{i}"]
            value = cell.get("value") or ""
            style = _style(cell)
            # Only the labels written *in* the cell: a tag on a side of a symbol
            # is on the paper beside it and has no box to overflow.
            if not value or style.get("verticalLabelPosition") != "middle":
                continue
            if style.get("labelPosition") in ("left", "right"):
                continue
            box = _LINE_BOX * float(style["fontSize"]) * (value.count("<br>") + 1)
            height = float(cell.find("mxGeometry").get("height"))
            assert box <= height + 0.01, (
                f"{stem}: {unit.name} writes {value!r} as {box:.2f} units of "
                f"line box inside a {height:.2f}-unit shape"
            )


def test_the_drawing_is_lettered_at_the_size_the_sheet_letters_it():
    """The export stated no size anywhere in the drawing, so every tag, balloon
    and flag came out at draw.io's default 12 -- unscaled, in a drawing the
    sheet had fitted to three-quarters. A rendered sheet puts its type inside
    the same `scale()` as its geometry; this backend has to multiply it in."""
    from pandid.render.drawio import _TAG_TYPE

    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.to_svg(**kwargs)

    def sizes(**over):
        cells = _drawio_cells(fs, {**kwargs, **over})
        return [
            float(_style(cells[f"u{i}"])["fontSize"])
            for i in range(len(fs.units))
            if cells[f"u{i}"].get("value")
        ]

    # Without paper there is no fitting to do, so the drawing keeps its own
    # coordinates and its own type: _Fit.identity() end to end.
    plain = sizes(page_size=None, border=None)
    assert plain and max(plain) == _TAG_TYPE

    # With it, every label rides the same ratio the geometry does -- or is
    # smaller still, where it had to be capped to the shape it is written in.
    fitted = sizes()
    assert len(fitted) == len(plain)
    assert max(fitted) < _TAG_TYPE, "the type was left at its unfitted size"
    ratio = max(fitted) / _TAG_TYPE
    assert all(size <= ratio * _TAG_TYPE + 0.01 for size in fitted)
    for i, unit in enumerate(fs.units):
        if unit.kind not in ("feed", "product") or not fs.units[i].tag:
            continue
        box = boundary_flag(unit, unit.frame).box
        # A flag's cell is scaled by that same ratio, which is what makes the
        # cap a statement about the drawing rather than about the model.
        cell = _drawio_cells(fs, kwargs)[f"u{i}"].find("mxGeometry")
        assert float(cell.get("height")) == pytest.approx(ratio * (box[3] - box[1]), abs=0.01)


def test_a_flag_is_drawn_across_its_own_box():
    """``boundary_flag`` writes the horizontal extent out again rather than
    reading ``unit_box``, so that whole-number coordinates keep the spelling the
    sheet has always given them. The two must still agree on the number."""
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
            # ...and is inset inside it, top and bottom, rather than filling it.
            assert uy0 < by0 < by1 < uy1


def test_a_tee_draws_no_ink_of_its_own():
    """The pipes draw the junction. A `line` drew a mark the width of the whole
    box, which the branch met at the box *edge* -- a stub jutting out of the
    pipe -- and hiding the cell without moving the pipes left a twelve-unit gap
    between the two nozzles instead. The cell stays, so the three edges have
    something to hold on to, and draws nothing."""
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


def test_three_runs_meeting_at_a_tee_close_on_one_point():
    """Flush by construction rather than by measurement: every leg ends on the
    box centre, so there is no gap to leave and no overshoot to trim. And each
    leg stays straight, because a tee's nozzles are the midpoints of three faces
    and the centre is on the axis of all three."""
    fs = Flowsheet("junction")
    header = fs.add(units.Feed("HDR"))
    tee = fs.add(units.Tee("TEE"))
    sink = fs.add(units.Product("OUT"))
    drop = fs.add(units.Tank("T-1"))
    header.pin(x=0, y=200)
    tee.pin(x=400, y=200)
    sink.pin(x=800, y=200)
    drop.pin(x=350, y=500)
    fs.connect(header.outlet, tee.inlet)
    fs.connect(tee.outlet, sink.inlet)
    fs.connect(tee.branch, drop.inlet)
    fs.route()

    cells = _cells(fs, check=False)
    at = {i: _style(c) for i, c in cells.items()}
    x0, y0, x1, y1 = cell_box(tee)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    legs = 0
    for n, s in enumerate(fs.streams):
        style = _style(cells[f"s{n}"])
        for prefix, port in (("exit", s.source), ("entry", s.dest)):
            if port.owner is not tee:
                continue
            legs += 1
            landed = _drawio_connection_point(tee, at[f"u{fs.units.index(tee)}"], style, prefix)
            assert landed == pytest.approx(centre, abs=0.01)
    assert legs == 3, "the fixture stopped exercising a three-way junction"


def test_a_pneumatic_line_is_marked_where_the_sheet_marks_it():
    """ISO 15519-2 §6.2 sanctions the signal-medium symbol where most of the
    diagram's signal lines are electric, which is this case. Weight alone does
    not tell a pneumatic line from a process one."""
    fs = Flowsheet("pneumatic")
    valve = fs.add(units.Valve("FV-101", variant="control"))
    valve.pin(x=400, y=300)
    pic = fs.add_instrument("PIC", 101, variant="panel")
    pic.pin(x=100, y=100)
    fs.connect(pic.sig_out, valve.actuator, kind="pneumatic")
    fs.route()
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
        # mxGraphView puts a relative child's TOP-LEFT on the point it computes,
        # so the offset has to carry the half-size or the mark sits off the line.
        offset = geo.find('mxPoint[@as="offset"]')
        assert offset is not None
        half = float(geo.get("width")) / 2
        assert abs(float(offset.get("x")) + half) <= 3 or abs(float(offset.get("y")) + half) <= 3
    # ...and the line itself stays solid, which is what a pneumatic line is.
    assert "dashed" not in _style(cells["s0"])


def test_a_dash_is_stated_in_drawing_units():
    """draw.io multiplies a dash pattern by the stroke width unless told not to,
    so a pattern written for a 1-unit signal line comes out twice as long on a
    2-unit process line. ``fixDash=1`` is what makes the numbers mean what the
    SVG's ``stroke-dasharray`` means."""
    fs = Flowsheet("dashes")
    a = fs.add(units.Tank("T-1"))
    b = fs.add(units.Tank("T-2"))
    a.pin(x=100, y=100)
    b.pin(x=500, y=100)
    fs.connect(a.outlet, b.inlet).dasharray = "8,4"
    fs.route()
    style = _style(_cells(fs, check=False)["s0"])
    assert style["dashPattern"] == "8 4", "a comma breaks mxGraph's pattern parser"
    assert style["fixDash"] == "1"


def test_a_turned_cell_pins_which_anchor_algorithm_reads_its_fractions():
    """draw.io ships two, and they disagree for a north or south direction: the
    newer one swaps the bounds' width and height whatever ``anchorPointDirection``
    says. Every fraction this exporter writes is a fraction of the box as placed,
    so only the legacy one is right, and relying on it being the default is a
    nozzle that moves when draw.io changes its mind."""
    style = _one_unit(units.Pump("P-1"), x=100, y=100, orientation=90)
    assert style["direction"] == "south"
    assert style["anchorPointDirection"] == "0"
    assert style["legacyAnchorPoints"] == "1"


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
        x0, y0, x1, y1 = cell_box(u)
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


def stream_end(port) -> tuple[float, float]:
    """Where a stream's line is expected to stop at this port.

    The drawn nozzle everywhere except a tee, which has no body: the pipes are
    carried on to the junction's centre so the three of them draw the meeting
    themselves. See ``_APPROXIMATIONS[("tee", "default")]``.
    """
    unit = port.owner
    if unit.kind == "tee":
        x0, y0, x1, y1 = cell_box(unit)
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    return port_point(unit, unit.frame, port.name)


def cell_box(unit) -> tuple[float, float, float, float]:
    """The rectangle the exporter hands draw.io for a unit.

    ``unit_box`` for everything whose artwork fills its box, and the pennant for
    an off-page flag, which is drawn inset inside a box half again as tall. Built
    here from :func:`~pandid.render.svg.boundary_flag` -- the function the SVG
    renderer strokes its polygon from -- so a cell that has drifted off the drawn
    flag fails rather than being compared against the exporter's own opinion.
    """
    if unit.kind in ("feed", "product"):
        return boundary_flag(unit, unit.frame).box
    return unit_box(unit, unit.frame)


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


@pytest.mark.parametrize("variant", ["sis", "logic"])
def test_a_trip_balloon_keeps_the_square_around_its_diamond(variant):
    """#242. ANSI/ISA-5.1-2009 Table 5.1.1 column B draws the
    safety-instrumented-system symbol as a square with an inscribed diamond;
    the export wrote ``shape=rhombus``, which is Table 5.1.2's *generic
    interlock* -- the variant next door, and a different claim about the
    system. Two symbols came out as one.

    So it is two cells: the square is the cell, the diamond is a child filling
    the same box. Held against the artwork the sheet draws rather than against
    a remembered pair of shapes -- ``sym_instrument_sis`` really is a ``<rect>``
    and a four-point ``<polygon>``, and the plain interlock really is the
    polygon on its own.
    """
    art = default_registry.get("instrument", variant).svg
    assert art.count("<rect") == 1 and art.count("<polygon") == 1, (
        "the sheet has stopped drawing this as a square with a diamond in it"
    )

    fs = Flowsheet("trip")
    fs.add(units.Instrument("Z", 301, variant=variant)).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, check=False)
    square, diamond = cells["u0"], cells["u0-in"]
    # The square is the cell: it carries the number, it is what a pipe lands on,
    # and it is draw.io's default vertex with the corners left square.
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

    # ...and the plain interlock is still the bare diamond it is on the sheet,
    # which is the distinction that was being thrown away.
    plain = Flowsheet("interlock")
    plain.add(units.Instrument("Z", 302, variant="interlock")).pin(x=100, y=100)
    plain.layout()
    bare = _cells(plain, check=False)
    assert _style(bare["u0"])["shape"] == "rhombus"
    assert "u0-in" not in bare


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


def _drawio_edge_label(points, geometry) -> tuple[float, float]:
    """Where draw.io draws an edge's label, by draw.io's own arithmetic.

    ``mxGraphView.getPoint``, transcribed: ``geometry.x`` runs -1 to +1 over the
    routed polyline's Euclidean arc length, the walk finds the segment that
    ``dist`` falls in, and ``geometry.offset`` displaces the result in plain
    drawing units. The view scale is 1 here, so it drops out.

    ``Math.round`` is reproduced because it is the whole of the residual: the
    rounding of ``dist`` to a whole pixel is worth up to half a unit of
    along-run slop and there is no way to write a fraction that avoids it.
    """
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


def test_a_line_number_is_written_where_the_sheet_writes_it():
    """`CWS-311-150-40-CS` was centred on its own run, across HV-311's body and
    the CWSH flag; `FB-301-200-160-SS` and `FB-310-300-160-SS` were centred over
    the lettering of the flags they run to. The sheet does not centre a number,
    it searches for paper -- and the export had no way to ask, so it centred.

    Now it asks. This replays draw.io's own `getPoint` over the emitted geometry
    and holds the answer against `stream_numbers`, which is the one derivation
    both backends read -- seeded, as the sheet seeds it, with the plates the
    equipment tags lay down.
    """
    from pandid.render.drawio import DrawioRenderer, _tag_pass
    from pandid.render.svg import _page, stream_numbers

    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        cells = _drawio_cells(fs, kwargs)
        _boxes, _frame, fit = DrawioRenderer()._furniture(fs, _page(kwargs.get("page_size")))
        plates = _tag_pass(fs, default_registry).plates
        wanted = {number.name: number for number in stream_numbers(fs, plates)}
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
            # ...and it is written on the sheet's own opaque halo, so a number
            # that has to cross a passing run still reads.
            assert _style(cell)["labelBackgroundColor"] == "#ffffff"
            checked += 1
        assert checked or not [s for s in fs.streams if s.kind == "material"]


def test_a_line_number_beside_its_run_carries_a_perpendicular_offset():
    """The defect stated plainly: with no offset at all, every number sat on the
    midpoint of its own polyline. `geometry.offset` is what moves it off, and it
    is the offset rather than `geometry.y` because `getPoint` applies the latter
    as `(nx*gy, -ny*gy)` -- a sign taken from the direction the segment happens
    to be routed in, which would put half a sheet's numbers on the wrong side of
    their lines."""
    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.to_svg(**kwargs)
    cells = _drawio_cells(fs, kwargs)
    offsets = []
    for n, s in enumerate(fs.streams):
        cell = cells[f"s{n}"]
        if not (cell.get("value") or ""):
            continue
        point = cell.find("mxGeometry/mxPoint[@as='offset']")
        if point is None:
            offsets.append(0.0)
            continue
        offsets.append(abs(float(point.get("x"))) + abs(float(point.get("y"))))
    assert offsets, "the sample sheet writes line numbers"
    # Most of them stand off their run; the rest sit in it on the sheet's own
    # halo, which is the convention and not an omission.
    assert sum(1 for d in offsets if d > 1.0) >= len(offsets) // 2


# ---------------------------------------------------------------------------


def _titled() -> Flowsheet:
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
    """Nothing is run together into a blob of ``<br>``-separated text: every
    field, heading and revision value is a cell a reader can double-click."""
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
    """The user's second report: `the blocks don't look anything like our SVG or
    PNG outputs`. They did not. The strip went out as two draw.io tables -- a
    revision grid and a twelve-row list reading COMPANY, TITLE, SUBTITLE,
    STATUS, DRAWING No, SCALE, SHEET, DATE, REV, DRAWN, CHECKED, APPROVED --
    which holds every value and is not a title block.

    Held against the SVG the sheet draws, part for part, rather than against the
    layout both are now built from: every rule the sheet strokes has an edge in
    the export between the same two points, and every string the sheet letters
    has a cell carrying it. That is what makes this a parity check rather than a
    restatement of the code.
    """
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
    # ...bar the revision grid's column rules, which the table draws itself
    # from its own cells' geometry (`TableShape.paintTableForeground`) rather
    # than needing a segment apiece.
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

    # --- every string the sheet letters -----------------------------------
    #
    # An SVG string sits on a baseline at an anchor; a draw.io one is laid out
    # in a box. `_BASELINE` and `_TEXT_INSET` are the conversion. A whole unit
    # and a half of slack, because a table cell is centred in its own row where
    # the sheet sets it four units off the row's foot, and a table cell's
    # gutter is its `spacingLeft` where the sheet's is `_REV_PAD`.
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
            written.append((value, size, left + 5, top + depth / 2 + size * (_BASELINE - 0.6)))
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
        # The two backends escape differently -- `html.escape` writes `&#x27;`
        # for an apostrophe and an XML attribute writes `&apos;` -- and neither
        # is what the reader sees, so both are compared unescaped.
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
    """``childLayout=tableLayout`` lays a table out from its children, so rows
    that do not span the table, or cells that do not span their row, are a grid
    whose rules do not meet its own frame.

    Nothing repairs that on load: draw.io's layout manager short-circuits on the
    root change every file load produces, so what is written is what is drawn
    until the reader's first edit.
    """
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
            # A row's y is measured from the table's top-left, title band and
            # all, and a row spans the whole table.
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
                # alternateBounds is the authored size TableLayout re-derives the
                # column proportions from; a cell without one loses its width the
                # first time the reader touches the table.
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
    """The arithmetic has to be done in the numbers that reach the file.

    Three equal rows of an eighty-unit strip are 26.666...; written at the two
    decimals a ``.drawio`` file carries they are 26.67 three times, which is a
    table one hundredth of a unit taller than the container it is inside. Nothing
    repairs it on load, and a reader who drags a column rule then finds the whole
    grid shift. Every row count from one to twelve, because whether it divides is
    the whole question.
    """
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
    # Summed as decimals, over the strings that reach the file, because that is
    # what draw.io adds up. Summing them as binary floats would fail the test on
    # its own rounding rather than on the exporter's.
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


#: The keyword arguments a ``.drawio`` export takes, out of the wider set the
#: gallery renders a sheet with. Every furniture defect below is a defect of a
#: *paged* export -- the strip docks to the frame, the frame is ruled, the
#: drawing is fitted into what is left -- so a check that drops ``page_size``
#: and ``border`` is a check run on a different picture from the one the reader
#: opened.
_DRAWIO_KWARGS = ("diagram", "page_size", "border")


def _drawio_cells(fs, kwargs) -> dict:
    return {
        c.get("id"): c
        for c in ET.fromstring(
            fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
        ).iter("mxCell")
    }


def _cell_font(cell) -> float:
    """The size a table cell's own style says it is drawn at.

    **No fallback to the row or to the table**, and that is the point of the
    function. mxGraph does not inherit a style from a parent cell:
    ``mxGraph.getCellStyle`` resolves the cell's own string against the
    stylesheet default and stops, and the only key that reaches down a draw.io
    table is the literal value ``inherit``, which ``Graph.getCellStyle``
    special-cases for ``strokeColor``, ``fillColor`` and ``gradientColor``
    alone. This helper used to read the row's size and then the table's, and
    that is why the export passed a clipping check while every cell in it was
    being drawn at draw.io's default 12: the size the *container* stated was
    never the size the cell was set in.
    """
    size = _style(cell).get("fontSize")
    assert size is not None, f"{cell.get('id')} states no fontSize of its own"
    return float(size)


def _table_cells(cells):
    """Every drawn table cell, with the row and the table it belongs to."""
    for cell in cells.values():
        if _style(cell).get("shape") != "partialRectangle":
            continue
        if not (cell.get("value") or ""):
            continue
        row = cells[cell.get("parent")]
        yield cell, row, cells[row.get("parent")]


def _clipped(cells) -> list[str]:
    """Every table cell whose text is wider than the column it is drawn in.

    Measured with ``furniture.text_width`` -- the estimate the SVG rules its own
    columns by -- at the size and in the face the cell states it will be *drawn*
    at, which is the pair that has to agree. A column measured at one size and
    drawn at another is the whole of this defect.
    """
    from pandid.render.furniture import text_width

    out = []
    for cell, _row, _table in _table_cells(cells):
        value = cell.get("value")
        need = text_width(value, _cell_font(cell), _style(cell).get("fontStyle") == "1")
        width = float(cell.find("mxGeometry").get("width"))
        if need > width:
            out.append(f"{cell.get('id')} {value!r} needs {need:.1f} of {width:.1f}")
    return out


def test_no_table_cell_is_narrower_than_the_text_in_it():
    """`HPSSH` came out `HPSSI`, `APP'D` came out `APP'`, and
    `Issued for internal review` lost its last word. The columns were measured
    at the size the sheet sets them and drawn at draw.io's default 12, because
    the size was stated on the table and mxGraph does not inherit a style from a
    parent cell."""
    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        clipped = _clipped(_drawio_cells(fs, kwargs))
        assert not clipped, f"{stem}: " + "; ".join(clipped)


def test_every_table_cell_states_the_size_it_is_drawn_at():
    """The container's ``fontSize`` styles the container's own label -- the
    table's title band -- and nothing below it, so a cell that says nothing is a
    cell drawn at 12 however carefully its column was measured."""
    sized = []
    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        # _cell_font is the assertion: it refuses to fall back to the container.
        sized += [_cell_font(c) for c, _r, _t in _table_cells(_drawio_cells(fs, kwargs))]
    assert sized, "no sheet in the gallery carries a table"


def test_no_table_row_is_shorter_than_the_line_box_of_its_own_text():
    """draw.io lays an HTML label out at ``line-height: 1.2`` and has no pass
    that shrinks type to fit -- ``TableLayout`` never measures a string at all --
    so a row shorter than its text loses the difference off the top and the
    bottom of every letter in it. Twelve-point values in fourteen-unit rows is
    what cut the title strip's last field in half."""
    from pandid.render.drawio import _line_box

    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        for cell, row, _table in _table_cells(_drawio_cells(fs, kwargs)):
            box = _line_box(_cell_font(cell))
            height = float(row.find("mxGeometry").get("height"))
            assert box <= height + 0.01, (
                f"{stem}: {cell.get('id')} {cell.get('value')!r} sets a "
                f"{box:.2f}-unit line in a {height:.2f}-unit row"
            )


def test_no_furniture_text_is_drawn_under_the_frames_own_rule():
    """The title strip docks flush to the frame, which is where the sheet rules
    its own last band -- but mxGraph strokes a rectangle *on* its path, so the
    frame lays half its weight inside that edge, and the strip's bottom row was
    drawn under it. `APPROVED / HVL` read as cut in half."""
    from pandid.render.drawio import _line_box

    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        cells = _drawio_cells(fs, kwargs)
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
            assert ink <= paper + 0.01, (
                f"{stem}: {cell.get('id')} {cell.get('value')!r} is drawn to "
                f"{ink:.2f}, past the frame's own ink at {paper:.2f}"
            )


def test_a_column_is_measured_in_the_face_its_text_is_drawn_in():
    """A legend's key column is set bold and its description column is not; a
    title strip is the other way round, captions light and values bold. Bold is
    eleven per cent the wider face, so a column measured in the wrong one either
    clips its own text or steals the room the column beside it needed."""
    from pandid.render.furniture import text_width

    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        for cell, _row, _table in _table_cells(_drawio_cells(fs, kwargs)):
            if _style(cell).get("fontStyle") != "1":
                continue
            width = float(cell.find("mxGeometry").get("width"))
            # The bold measurement, not the light one it used to be taken at.
            assert text_width(cell.get("value"), _cell_font(cell), True) <= width, (
                f"{stem}: {cell.get('id')} {cell.get('value')!r} is drawn bold "
                f"in a column only {width:.1f} wide"
            )


def test_a_table_states_the_size_its_columns_were_measured_at():
    """draw.io's default is 12 and every box on the sheet measures its own text
    at its ``font_size``. Leaving the size unsaid is what made the measurement
    and the drawing disagree.

    The container's own size is the *title band's*, since a style does not
    inherit down a draw.io table and the container's label is the title: the
    sheet sets that one point larger than the rows (``draw_annotation``), so
    the two sizes are checked apart rather than assumed equal.
    """
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
    """Eleven fields shared between an eighty-unit strip are rows 5.6 units
    tall, and 11-point type in a 5.6-unit row draws nothing: the reader saw a
    stack of empty rules. Nothing in mxGraph shrinks type to fit, so a row is
    exactly as tall as the file writes it and its text exactly as tall as the
    font says."""
    fs = _titled()
    cells = _cells(fs, check=False)
    rows = [c for c in cells.values() if _style(c).get("shape") == "tableRow"]
    assert rows
    for row in rows:
        height = float(row.find("mxGeometry").get("height"))
        assert height >= 11.0, f"{row.get('id')} is {height} units tall"


def test_the_title_strip_asks_the_dock_for_the_rectangle_the_sheet_rules():
    """The strip used to need measuring: two draw.io tables holding eleven
    fields at a row each are 154 units where the sheet rules 80, so the height
    had to be worked out here or the strip grew up over the foot of the drawing.
    The bands are bands again, so the answer is the sheet's own -- and it has to
    be, or the exported strip lands on different paper from the rendered one.
    """
    from pandid.render import furniture as F
    from pandid.render.drawio import _strip_size

    block = _titled().title_block
    assert _strip_size(block) == F.measure_title_strip(block)


def test_the_title_strip_is_one_rectangle_flush_to_the_frame():
    """It is drawn from a bottom-right corner because that is its natural
    anchor: the strip's own rule and the drawing frame's are coincident on the
    sheet, and every band inside it is ruled off that corner."""
    from pandid.render import furniture as F
    from pandid.render.drawio import _FRAME_STROKE

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
    # ...and the frame it is flush to is ruled at the weight the strip is, so
    # the corner of the sheet reads as one heavy line rather than two.
    assert _style(cells["z-frame"])["strokeWidth"] == f"{_FRAME_STROKE:g}"


def test_the_revision_history_is_still_a_grid_a_reader_can_edit():
    """The one part of a title block that is a grid, and the one part a reader
    edits -- the next thing that happens to an issued drawing is a revision.

    Ruled to the sheet's rules and no others: `rowLines=0`, because the sheet
    draws no line *between* revisions, and the column rules the sheet does draw
    left to the table. The heading sits at the foot with the newest revision
    against it, and the blank paper above the oldest is blank rows of the same
    depth rather than a stretched grid.
    """
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
    # The revisions and the heading, at the sheet's own depth. The rows above
    # them are the blank paper the sheet leaves for the next revision, and the
    # remainder that is not a whole row goes into the topmost of those.
    for row in rows[-(len(fs.title_block.revisions) + 1) :]:
        assert float(row.find("mxGeometry").get("height")) == pytest.approx(F._REV_ROW, abs=0.01), (
            "a revision row is not the sheet's own depth"
        )
    # Every column at the width the sheet rules it.
    widths = [float(c.find("mxGeometry").get("width")) for c in _row_cells(cells, rows[-1])]
    assert widths == pytest.approx([w for _heading, w in _rev_cols()], abs=0.01)


def _rev_cols():
    from pandid.render import furniture as F

    return [(heading, width) for heading, width, _attr in F._REV_COLS]


def _row_cells(cells, row):
    kids = [c for c in cells.values() if c.get("parent") == row.get("id")]
    return sorted(kids, key=lambda c: float(c.find("mxGeometry").get("x")))


def test_a_columnar_box_is_a_table_and_a_prose_box_is_not():
    """A box whose rows have columns in them is a grid and goes out as one.
    Ruling a column of sentences into a table would invent structure the author
    never wrote."""
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
    """The defect this replaced: four boxes stacked in a column down the left of
    a drawing that ran out to x=1540, while the sheet rules them into four
    different corners. Held against ``furniture.dock`` -- the function the SVG
    renderer places from -- rather than against a remembered coordinate."""
    from pandid.document import Annotation
    from pandid.render import furniture as F

    fs = Flowsheet("docked")
    pump = fs.add(units.Pump("P-101"))
    pump.pin(x=400, y=300)
    left = Annotation(title="LEGEND", align="top-left", rows=[("SS", "316L")])
    right = Annotation(title="EQUIPMENT LIST", align="top-right", rows=[("P-101", "Pump")])
    fs.annotations.extend([left, right])
    fs.layout()

    box = DrawioRenderer()._drawing_box(fs)
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
    # ...and the two really are in different corners, which is the whole point.
    assert at[id(left)][0] < at[id(right)][0]


@pytest.mark.parametrize(
    "option,value",
    [
        ("show_stream_table", True),
        ("debug", True),
    ],
)
def test_render_refuses_a_sheet_option_it_cannot_honour(tmp_path, sample, option, value):
    """Accepting and ignoring these would tell the caller something false about
    the file they now hold. ``page_size``, ``border`` and ``jump_direction`` are
    no longer among them; see the tests below."""
    with pytest.raises(ValueError, match=option):
        sample.render(tmp_path / "sheet.drawio", **{option: value})


@pytest.mark.parametrize(
    "option,value",
    [("page_size", "A3"), ("border", "zone"), ("jump_direction", "horizontal")],
)
def test_render_honours_the_sheet_options_it_can(tmp_path, sample, option, value):
    out = tmp_path / "sheet.drawio"
    sample.render(out, **{option: value})
    assert out.read_text(encoding="utf-8") == sample.to_drawio(**{option: value})


def test_a_page_size_is_the_paper_the_file_opens_on():
    """The defect: a sheet drawn A3 opened on draw.io's default page. The page
    is stated in the drawing units everything else here is stated in, which is
    what makes A3 1587 by 1123 rather than 420 by 297."""
    from pandid.render.svg import _page

    fs = Flowsheet("paper")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.layout()
    model = ET.fromstring(fs.to_drawio(page_size="A3", check=False)).find("diagram/mxGraphModel")
    sheet = _page("A3")
    assert model.get("page") == "1"
    assert float(model.get("pageWidth")) == pytest.approx(sheet.width, abs=0.01)
    assert float(model.get("pageHeight")) == pytest.approx(sheet.height, abs=0.01)
    # ...and without one there is no paper to rule, so none is claimed.
    plain = ET.fromstring(fs.to_drawio(check=False)).find("diagram/mxGraphModel")
    assert plain.get("page") == "0"
    assert plain.get("pageWidth") is None


def test_a_paged_drawing_is_fitted_onto_its_paper():
    """A page that the drawing spills off is not the paper it was drawn for.
    Held against ``svg._fit_scale`` and the region the dock leaves, which is
    what the SVG places the drawing at, rather than against a remembered
    number."""
    from pandid.render import furniture as F
    from pandid.render.svg import _fit_scale, _page

    fs = Flowsheet("fitted")
    a = fs.add(units.Tank("T-1"))
    b = fs.add(units.Tank("T-2"))
    a.pin(x=0, y=0)
    b.pin(x=3000, y=1600)
    fs.connect(a.outlet, b.inlet)
    fs.route()

    sheet = _page("A3")
    inner = DrawioRenderer()._drawing_box(fs)
    _placed, _frame, free = F.dock([], inner, sheet=sheet)
    scale = _fit_scale(inner[2] - inner[0], inner[3] - inner[1], free)
    assert scale < 1.0, "the fixture stopped needing to be shrunk"

    cells = _cells(fs, page_size="A3", check=False)
    for i, u in enumerate(fs.units):
        x0, y0, x1, y1 = cell_box(u)
        geo = cells[f"u{i}"].find("mxGeometry")
        assert float(geo.get("width")) == pytest.approx(scale * (x1 - x0), abs=0.01)
    # ...and every cell lands inside the paper it was fitted to.
    for cell in cells.values():
        geo = cell.find("mxGeometry")
        if geo is None or geo.get("x") is None or cell.get("edge") == "1":
            continue
        assert -1 <= float(geo.get("x")) <= sheet.width
        assert -1 <= float(geo.get("y")) <= sheet.height


def test_a_zone_border_rules_the_same_frame_the_sheet_rules():
    """Held against ``furniture.zone_layout`` -- the geometry the SVG strokes --
    so the exported band is divided into the same fields, lettered the same way
    round."""
    from pandid.render import furniture as F

    fs = Flowsheet("ruled")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, page_size="A3", border="zone", check=False)
    values = {c.get("value") for c in cells.values()}

    _placed, frame, _free = F.dock(
        [],
        DrawioRenderer()._drawing_box(fs),
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


def test_every_example_exported_on_its_own_paper_lands_on_it():
    """Each sheet exported with the page size and border it is *drawn* with,
    which is what ``drawio-samples/`` carries and what the reader opens. A page
    the drawing hangs off is not the paper it was drawn for."""
    from pandid.render.svg import _page

    for stem in SHEETS:
        _lands_on_its_paper(stem, _page)


def _lands_on_its_paper(stem, _page):
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)
    sheet = _page(kwargs.get("page_size"))
    doc = fs.to_drawio(
        diagram=kwargs.get("diagram"),
        page_size=kwargs.get("page_size"),
        border=kwargs.get("border"),
    )
    root = ET.fromstring(doc)
    if sheet is None:
        assert root.find("diagram/mxGraphModel").get("page") == "0"
        return
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
    """The sheet draws no rectangle for ``border="none"`` -- it takes the region
    for the canvas and strokes nothing -- so neither does the export. What the
    reader sees as the paper's edge is the page draw.io is now told to rule."""
    fs = Flowsheet("plain")
    fs.add(units.Pump("P-101")).pin(x=100, y=100)
    fs.layout()
    cells = _cells(fs, page_size="A3", check=False)
    assert not [i for i in cells if i.startswith("z")]


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
        x0, y0, x1, y1 = cell_box(u)
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
            assert landed == pytest.approx(stream_end(port), abs=0.01)


def _drawn_boxes(fs, kwargs) -> tuple[dict, dict, list]:
    """Every rectangle the emitted file actually inks, read back out of it.

    Read out of the **XML** and not out of the renderer, which is the whole
    point of the check below: the renderer already believes it stepped the
    number aside, and what a reader opens is the file. A vertex's box is its
    geometry; a label's box is its measured text at the `fontSize` the cell
    states, laid out the way draw.io lays a label out.

    Returns the symbol boxes by cell id, the equipment-tag label boxes by cell
    id, and the line-number label boxes as `(name, box)`.
    """
    from pandid.render.drawio import _LINE_BOX, _Fit
    from pandid.render.furniture import text_width

    cells = _drawio_cells(fs, kwargs)
    symbols, tags, numbers = {}, {}, []
    for i, u in enumerate(fs.units):
        cell = cells[f"u{i}"]
        geometry = cell.find("mxGeometry")
        x, y = float(geometry.get("x")), float(geometry.get("y"))
        w, h = float(geometry.get("width")), float(geometry.get("height"))
        symbols[f"u{i}"] = (x, y, x + w, y + h)
        text = cell.get("value") or ""
        style = _style(cell)
        # A label written *inside* the shape is not on the paper beside it and
        # is not an obstacle: an instrument's tag and a boundary flag's service
        # name are the shape's own contents.
        if not text or style.get("verticalLabelPosition", "middle") == "middle":
            continue
        size = float(style.get("fontSize", 12))
        lines = text.split("<br>")
        lw = max(text_width(line, size) for line in lines)
        lh = _LINE_BOX * size * len(lines)
        offset = geometry.find("mxPoint[@as='offset']")
        dx = float(offset.get("x")) if offset is not None else 0.0
        dy = float(offset.get("y")) if offset is not None else 0.0
        # `verticalLabelPosition` puts the label's box outside the cell and the
        # `verticalAlign` beside it pulls the text back against the cell.
        cx = x + w / 2 + dx
        top = (y - lh if style["verticalLabelPosition"] == "top" else y + h) + dy
        tags[f"u{i}"] = (cx - lw / 2, top, cx + lw / 2, top + lh)

    _boxes, _frame, fit = DrawioRenderer()._furniture(fs, _page(kwargs.get("page_size")))
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
        # `horizontal=0` turns the label a quarter, so the paper it takes is the
        # transpose; it is centred on the same point either way round.
        if style.get("horizontal") == "0":
            lw, lh = lh, lw
        numbers.append((name, (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)))
    return symbols, tags, numbers


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_no_line_number_is_written_over_a_symbol_or_an_equipment_tag(stem):
    """The user's report, measured rather than looked at.

    `some of the valves are covered by the stream labels`. They were: the
    exporter seeded `stream_numbers` with an empty list of plates where the
    sheet seeds it with every equipment tag it has already laid down, so the
    search was offered paper the sheet had already spent and took it --
    `AE-302-300-80-SS` over `HV-301A`, `FB-301-200-160-SS` over `XV-301`,
    seventeen numbers over four sheets. And a number on a vertical run was
    written flat where the sheet turns it, so its lettering ran across the
    corridor it was reserved a slot *along*.

    Parsed back out of the emitted XML and measured, because a renderer that
    believes it stepped a label aside is not evidence of anything: draw.io's own
    `getPoint` places the number, `text_width` and the cell's stated `fontSize`
    measure it, and the boxes either meet or they do not.
    """
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)
    symbols, tags, numbers = _drawn_boxes(fs, kwargs)
    drawn = {**symbols, **{f"{k} tag": v for k, v in tags.items()}}

    def meets(a, b):
        return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]

    struck = [
        (name, other)
        for name, box in numbers
        for other, obstacle in drawn.items()
        if meets(box, obstacle)
    ]
    assert not struck, f"{stem}: line numbers written over {struck}"


# ---------------------------------------------------------------------------
# Line jumps
#
# draw.io is still not run, so what is done here is what the header of this file
# says is done everywhere else: draw.io's *algorithm* is written out from its
# own source and applied to the emitted XML. `mxGraphView.updateLineJumps` is
# forty lines long and every branch of it is reproduced below, including the two
# that decide a crossing is not one. That catches a hop on the wrong line, a hop
# on both lines, a hop draw.io would refuse to draw, and a hop drawn where the
# sheet draws none; it cannot catch a mistake in the transcription itself.
# ---------------------------------------------------------------------------


def _intersection(p0, p1, p2, p3):
    """``mxUtils.intersection``: where two *segments* meet, or None.

    Inclusive at all four ends, which matters: draw.io excludes an intersection
    at the jumping segment's own ends further down, and at the *other*
    segment's ends not at all.
    """
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
    """Every edge in the document, in ``<root>`` order, with the line it draws.

    An edge with both terminals stated as points carries its own geometry -- a
    ruled line of furniture, a tap whose host is a stream. Everything else is
    pinned to cells at one or both ends, and the line it draws is the sheet's
    own: the routed polyline for a stream, `tap_lines`' pair for a tap, each put
    through the fit a page size applies. Taken from the sheet rather than
    re-derived from the connection fractions because
    `test_an_edges_waypoints_are_the_line_the_renderer_draws` already holds the
    emitted waypoints against exactly that.
    """
    from pandid.render.drawio import _Fit

    _boxes, _frame, fit = DrawioRenderer()._furniture(fs, _page(kwargs.get("page_size")))
    assert isinstance(fit, _Fit)
    known = {f"s{n}": [fit.at(*p) for p in stream_polyline(s)] for n, s in enumerate(fs.streams)}
    for n, (_inst, tap, centre) in enumerate(tap_lines(fs)):
        known[f"t{n}"] = [fit.at(*tap), fit.at(*centre)]
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
    """Every hop draw.io draws on this document, by its own rule.

    ``mxGraphView.updateLineJumps``, transcribed: an edge is intersected only
    against ``this.validEdges``, which ``validateCellState`` appends to as it
    walks the model in child order -- so it holds exactly the edges written
    before this one. ``state2.style['noJump'] != '1'`` skips a candidate that
    has opted out, and the two ``thresh`` guards drop an intersection sitting on
    either end of the *jumping* segment, which is what keeps three runs meeting
    at a tee from being read as three crossings.

    Returns ``{(hopping id, hopped id, x, y)}``, the point rounded to the
    hundredth this file writes coordinates at.
    """
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


def _sheet_hops(fs, fit, direction="vertical"):
    """Every hop the *sheet* draws, by ``SvgRenderer._draw_streams``' own rule.

    A vertical segment strictly inside a horizontal one hops it, or the reverse
    under ``"horizontal"``. Put through the same fit as the export, so the two
    sets are comparable point for point.
    """
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
            if hop == cross or not (c_lo < at < c_hi and lo < c_at < hi):
                continue
            point = (at, c_at) if direction == "vertical" else (c_at, at)
            x, y = fit.at(*point)
            out.add((f"s{hop}", f"s{cross}", round(x, 2), round(y, 2)))
    return out


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_a_crossing_is_hopped_by_the_line_the_sheet_hops(stem):
    """#241, measured rather than looked at.

    The export drew no jump anywhere -- `grep -c jumpStyle` on a committed
    sample returned 0 -- so every crossing on an exported sheet was a flat
    four-way and a reader could not tell one from a junction. The premise was
    that draw.io decides its own jumps; it decides nothing, and does not draw
    one at all unless the edge asks.

    So the two sets are built independently and compared: what
    `_draw_streams` hops, and what draw.io would hop given this document. Equal
    means every crossing carries exactly one hop, on the line the direction
    selects, and that the hopping edge really is the later of the two in
    ``<root>`` -- because an edge written first cannot hop at all.
    """
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)
    root = ET.fromstring(
        fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
    ).find("diagram/mxGraphModel/root")
    edges, fit = _edge_lines(fs, kwargs, root)
    assert _drawio_hops(edges) == _sheet_hops(fs, fit)


@pytest.mark.parametrize("direction", ["vertical", "horizontal"])
def test_jump_direction_picks_which_of_two_crossing_lines_hops(direction):
    """The option the exporter used to refuse, doing what it says.

    One horizontal run and one vertical, crossing once. Whichever the direction
    names is the one that carries the style, and it is the one written second.
    """
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
    # ...and the two directions really do put the hop on different lines.
    assert {hop for hop, _crossed, _x, _y in hops} == (
        {"s1"} if direction == "vertical" else {"s0"}
    )


def test_the_hop_is_the_radius_the_sheet_draws_it_at():
    """``jumpSize`` is not the radius, and reading it as one draws a hop a
    third too small on a process line.

    ``mxConnector.paintLine`` takes the hop's half-extent along the run as
    ``(parseInt(jumpSize) - 2) / 2 + this.strokewidth``, so the number in the
    style is net of the pen -- and the pen is the edge's own, which is why a
    signal line and the pipe it crosses are hopped by the same radius under
    different sizes. Solved back here and held against the sheet's own
    ``HOP_R``.
    """
    from pandid.render.svg import HOP_R

    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.to_svg(**kwargs)
    _boxes, _frame, fit = DrawioRenderer()._furniture(fs, _page(kwargs.get("page_size")))
    cells = _drawio_cells(fs, kwargs)
    hopping = [c for c in cells.values() if _style(c).get("jumpStyle", "none") != "none"]
    assert len(hopping) == 6, "11_ethanol_pid has six runs that hop another"
    for cell in hopping:
        style = _style(cell)
        assert style["jumpStyle"] == "arc", "the sheet hops with a semicircle"
        size = float(style["jumpSize"])
        assert size == int(size), "parseInt truncates a fractional jumpSize"
        weight = float(style["strokeWidth"])
        radius = (size - 2) / 2 + weight
        # Within the half unit rounding jumpSize to an integer can cost.
        assert radius == pytest.approx(fit.length(HOP_R), abs=0.5)


def test_only_a_stream_hops_or_is_hopped():
    """Only a *stream* hops or is hopped, because that is the only thing
    ``_draw_streams`` builds its two lists of segments from.

    draw.io has no such distinction and would hop a zone tick or an instrument
    connection as readily as a pipe, so the rule is stated on the cell rather
    than left to the order the edges happen to come out in -- which
    :func:`~pandid.render.drawio._hops` reorders.
    """
    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.to_svg(**kwargs)
    cells = _drawio_cells(fs, kwargs)
    edges = {cid: c for cid, c in cells.items() if c.get("edge") == "1"}
    assert edges, "no edges at all"
    for cid, cell in edges.items():
        stream = cid.startswith("s") and cid[1:].isdigit()
        assert (_style(cell).get("noJump") == "1") != stream, (
            f"{cid}: a {'stream' if stream else 'rule or tap'} says "
            f"noJump={_style(cell).get('noJump')}"
        )


# ---------------------------------------------------------------------------
# The committed samples, and the script that makes them.
# ---------------------------------------------------------------------------


def _samples():
    path = ROOT / "scripts" / "drawio_samples.py"
    spec = importlib.util.spec_from_file_location("_pandid_script_drawio_samples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("stem", sorted(_samples().SAMPLES))
def test_the_committed_sample_is_what_the_exporter_emits(stem):
    """`drawio-samples/` is the file a reader opens to see what this backend
    actually produces, and it had nothing holding it to the code: the command
    that made it was written into a commit message and nowhere else, three of
    the four committed files were pre-#236 exports carrying defects the branch
    had fixed, and the file the author opened to review the exporter was one of
    them. That is exactly the drift `scripts/gallery.py` exists to prevent for
    the SVGs, and its docstring warns against generating an artefact without a
    check beside it.

    Regenerate with `python scripts/drawio_samples.py`.
    """
    samples = _samples()
    committed = samples.OUT / f"{stem}.drawio"
    assert committed.exists(), f"{committed.name} is not committed"
    document, _dropped = samples.sample(stem)
    assert committed.read_text(encoding="utf-8") == document, (
        f"{committed.name} is stale; run python scripts/drawio_samples.py"
    )
