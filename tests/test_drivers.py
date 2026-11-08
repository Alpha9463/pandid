"""Check the gearbox, the generator, the diesel engine and the turbine as drivers."""

import xml.etree.ElementTree as ET

import pytest
from test_drawio import _inline_stencil, _model, _style
from test_drives import _BAR, _TILDE, _stencil_steps, _steps

from pandid import (
    Compressor,
    DieselEngine,
    Feed,
    Flowsheet,
    Gearbox,
    Generator,
    Motor,
    Product,
    Pump,
    Turbine,
)
from pandid.portgeom import resolve_port
from pandid.render.symbols import default_registry
from pandid.route_geometry import stream_polyline

#: The G of items 20.2 to 20.5 on the 10-unit module.
_G = [
    ("M", [25, 10]),
    ("L", [17.5, 10]),
    ("A", [2.5, 2.5, 0, 0, 0, 15, 12.5]),
    ("L", [15, 27.5]),
    ("A", [2.5, 2.5, 0, 0, 0, 17.5, 30]),
    ("L", [25, 30]),
    ("L", [25, 20]),
    ("L", [20, 20]),
]

#: Each drawing's outline, as ``(element, attributes)``, and its strokes.
_DRAWN = {
    ("gearbox", "default"): (("rect", {"x": 0, "y": 0, "width": 40, "height": 40}), _G),
    ("generator", "general"): (("circle", {"cx": 20, "cy": 20, "r": 20}), _G),
    ("generator", "ac"): (("circle", {"cx": 20, "cy": 20, "r": 20}), _G + _TILDE),
    ("generator", "dc"): (("circle", {"cx": 20, "cy": 20, "r": 20}), _G + _BAR),
    ("diesel_engine", "default"): (
        ("rect", {"x": 0, "y": 0, "width": 60, "height": 40}),
        [
            ("M", [22.5, 10]),
            ("L", [27.5, 10]),
            ("A", [10, 10, 0, 0, 1, 27.5, 30]),
            ("L", [22.5, 30]),
            ("Z", []),
        ],
    ),
}

#: The stencil element and keys that stand for each SVG outline.
_STENCIL = {
    "rect": ("rect", ("x", "y", "w", "h"), ("x", "y", "width", "height")),
    "circle": ("ellipse", ("x", "y", "w", "h"), None),
}


def _sheet(*units):
    """Return a sheet holding the units."""
    fs = Flowsheet("Drivers")
    for unit in units:
        fs.add(unit)
    return fs


def _drawn(kind: str, variant: str):
    """Return a sheet driving or driven by a unit of this drawing, and the unit."""
    if kind == "diesel_engine":
        unit, other = DieselEngine("U-1"), Generator("G-1")
        fs = _sheet(unit, other)
        fs.connect(unit.shaft, other.drive)
    elif kind == "gearbox":
        unit, motor, pump = Gearbox("U-1"), Motor("M-1"), Pump("P-1")
        fs = _sheet(unit, motor, pump)
        fs.connect(motor.shaft, unit.drive)
        fs.connect(unit.shaft, pump.drive)
    else:
        unit, motor = Generator("U-1", variant=variant), Motor("M-1")
        fs = _sheet(unit, motor)
        fs.connect(motor.shaft, unit.drive)
    return fs, unit


@pytest.mark.parametrize(("kind", "variant"), list(_DRAWN), ids=lambda v: str(v))
def test_the_sheet_draws_each_driver_s_outline_and_marks(kind, variant):
    """Check the emitted drawing: its outline, and exactly the strokes stated."""
    fs, _ = _drawn(kind, variant)
    doc = ET.fromstring(fs.to_svg())
    name = f"sym_{kind}" + ("" if variant == "default" else f"_{variant}")
    sym = next(el for el in doc.iter() if el.get("id") == name)
    (tag, box), strokes = _DRAWN[kind, variant]
    (outline,) = [el for el in sym if el.tag.endswith(tag)]
    assert {k: float(outline.get(k, "nan")) for k in box} == box
    drawn = [step for el in sym if el.tag.endswith("path") for step in _steps(el.get("d", ""))]
    assert drawn == strokes


@pytest.mark.parametrize(("kind", "variant"), list(_DRAWN), ids=lambda v: str(v))
def test_draw_io_gets_each_driver_s_outline_and_marks(kind, variant):
    """Check that draw.io draws the outline and exactly the strokes stated."""
    fs, unit = _drawn(kind, variant)
    cell = next(c for c in _model(fs, check=False).iter("mxCell") if c.get("value") == unit.name)
    stencil = _inline_stencil(_style(cell).get("shape", ""))
    assert stencil is not None, f"{unit.name} exports as a box, not its outline"
    (tag, box), strokes = _DRAWN[kind, variant]
    element, keys, svg_keys = _STENCIL[tag]
    (outline,) = stencil.iter(element)
    want = (
        [box[k] for k in svg_keys]
        if svg_keys
        else [box["cx"] - box["r"], box["cy"] - box["r"], 2 * box["r"], 2 * box["r"]]
    )
    assert [float(outline.get(k, "nan")) for k in keys] == want
    assert [step for p in stencil.iter("path") for step in _stencil_steps(p)] == strokes


def test_a_turbine_s_shaft_leaves_under_its_wide_end():
    """Check the turbine's shaft is on the casing's underside near its wide end."""
    sym = default_registry.get("turbine")
    assert sym.ports == {"inlet": (0.0, 30.0), "outlet": (98.0, 30.0), "shaft": (69.0, 56.25)}


def _piped_pump():
    """Return a sheet piping a pump, and the pump."""
    fs = Flowsheet("Train")
    pump = fs.add(Pump("P-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(Product("Out")).inlet)
    return fs, pump


def test_a_motor_turns_a_pump_through_a_gearbox_in_line():
    """Check the train stands on the pump, each shaft 20 long and straight."""
    fs, pump = _piped_pump()
    motor, gearbox = fs.add(Motor("M-1")), fs.add(Gearbox("GB-1"))
    upper = fs.connect(motor.shaft, gearbox.drive)
    lower = fs.connect(gearbox.shaft, pump.drive)
    fs.to_svg()
    drive = resolve_port(pump, pump.frame, "drive").point
    out = resolve_port(gearbox, gearbox.frame, "shaft")
    into = resolve_port(gearbox, gearbox.frame, "drive")
    end = resolve_port(motor, motor.frame, "shaft")
    assert (out.face, into.face, end.face) == ("S", "N", "S")
    assert out.point == (drive[0], drive[1] - 20.0)
    assert end.point == (into.point[0], into.point[1] - 20.0)
    assert stream_polyline(lower) == [out.point, drive]
    assert stream_polyline(upper) == [end.point, into.point]


def test_a_turbine_drives_a_generator_hung_under_it():
    """Check a generator, piped to nothing, is drawn 20 under its turbine's box."""
    fs = Flowsheet("Turbine generator")
    turbine = fs.add(Turbine("ST-1"))
    fs.connect(fs.add(Feed("HP")).outlet, turbine.inlet)
    fs.connect(turbine.outlet, fs.add(Product("LP")).inlet)
    generator = fs.add(Generator("G-1", variant="ac"))
    shaft = fs.connect(turbine.shaft, generator.drive)
    fs.to_svg()
    start, edge, _ = resolve_port(turbine, turbine.frame, "shaft")
    end = resolve_port(generator, generator.frame, "drive")
    assert edge[1] - start[1] == 3.75
    assert end.face == "N" and end.point == (start[0], edge[1] + 20.0)
    assert stream_polyline(shaft) == [start, end.point]


def test_a_turbine_stands_on_the_compressor_it_drives():
    """Check two piped machines on one shaft are stacked and the shaft drawn straight."""
    fs = Flowsheet("Turbine compressor")
    compressor = fs.add(Compressor("K-1"))
    fs.connect(fs.add(Feed("Gas")).outlet, compressor.suction)
    fs.connect(compressor.discharge, fs.add(Product("HP gas")).inlet)
    turbine = fs.add(Turbine("KT-1"))
    fs.connect(fs.add(Feed("Steam")).outlet, turbine.inlet)
    fs.connect(turbine.outlet, fs.add(Product("Exhaust")).inlet)
    shaft = fs.connect(turbine.shaft, compressor.drive)
    fs.to_svg()
    (x0, y0), (x1, y1) = stream_polyline(shaft)
    assert x0 == x1 and y0 < y1
    assert [i for i in fs.validate() if i.severity == "error"] == []


@pytest.mark.parametrize(
    ("turbine_at", "compressor_at"),
    [((400, 60), (100, 300)), ((61, 300), (100, 100))],
    ids=["off one line", "on one line, back to back"],
)
def test_a_shaft_whose_ends_do_not_face_is_routed_square(turbine_at, compressor_at):
    """Check a shaft between two pinned machines whose ends do not face has no slant."""
    fs = Flowsheet("Pinned")
    turbine = fs.add(Turbine("KT-1")).pin(x=turbine_at[0], y=turbine_at[1])
    compressor = fs.add(Compressor("K-1")).pin(x=compressor_at[0], y=compressor_at[1])
    shaft = fs.connect(turbine.shaft, compressor.drive)
    fs.to_svg()
    path = stream_polyline(shaft)
    assert len(path) > 2
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(path, path[1:]))


def test_a_diesel_engine_and_its_generator_hang_together():
    """Check two units piped to nothing are drawn a straight shaft apart."""
    fs = Flowsheet("Diesel set")
    engine, generator = fs.add(DieselEngine("DE-1")), fs.add(Generator("G-1", variant="dc"))
    shaft = fs.connect(engine.shaft, generator.drive)
    fs.to_svg()
    (x0, y0), (x1, y1) = stream_polyline(shaft)
    assert abs(x1 - x0) + abs(y1 - y0) == 20.0 and (x0 == x1 or y0 == y1)


def test_a_spec_keeps_a_train(tmp_path):
    """Check a gearbox train reads back from its spec as drawn."""
    fs, pump = _piped_pump()
    motor, gearbox = fs.add(Motor("M-1")), fs.add(Gearbox("GB-1"))
    fs.connect(motor.shaft, gearbox.drive)
    fs.connect(gearbox.shaft, pump.drive)
    svg = fs.to_svg()
    assert Flowsheet.from_dict(fs.to_dict()).to_svg() == svg
