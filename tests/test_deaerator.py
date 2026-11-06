"""Check the deaerator."""

import xml.etree.ElementTree as ET

from test_drawio import _inline_stencil, _model, _style

from pandid import Deaerator, Feed, Flowsheet, Product
from pandid.portgeom import port_faces
from pandid.render import symbols
from pandid.render.symbols import MIN_NOZZLE_PITCH, default_registry

#: The registered drawing.
BODY = default_registry.get("deaerator")


def test_each_nozzle_leaves_by_its_own_face():
    """Check that water and vent use the column's crown, steam and outlet the drum."""
    unit = Deaerator("DA-101")
    faces = {name: port_faces(unit, name)[0] for name in unit.ports}
    assert faces == {"feed": "N", "vent": "N", "steam": "W", "outlet": "S"}


def test_the_water_and_vent_share_the_column_crown_a_pitch_apart():
    """Check that feed and vent are on the column's crown, a nozzle pitch apart."""
    left = symbols._DA_COLUMN_X
    right = left + symbols._DA_COLUMN_W
    for name in ("feed", "vent"):
        x, y = BODY.ports[name]
        assert left < x < right, f"{name} is off the column"
        assert y < symbols._DA_CROWN, f"{name} is below the crown"
    assert abs(BODY.ports["feed"][0] - BODY.ports["vent"][0]) >= MIN_NOZZLE_PITCH
    # The drum's ports are on the drum, below the column.
    assert BODY.ports["steam"][1] > symbols._DA_COLUMN_H
    assert BODY.ports["outlet"][1] == BODY.height


def test_a_deaerator_draws_on_a_sheet_and_is_scheduled():
    """Check a deaerator piped on all four nozzles renders clean and is listed."""
    fs = Flowsheet("Feedwater")
    water = fs.add(Feed("Condensate and Make-up"))
    steam = fs.add(Feed("LP Steam"))
    da = fs.add(Deaerator("DA-101", description="Deaerator"))
    vent = fs.add(Product("Vent"))
    bfw = fs.add(Product("To BFW Pumps"))
    fs.connect(water.outlet, da.feed)
    fs.connect(steam.outlet, da.steam)
    fs.connect(da.vent, vent.inlet)
    fs.connect(da.outlet, bfw.inlet)

    assert 'id="sym_deaerator"' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert [row["tag"] for row in fs.equipment_list()] == ["DA-101"]


def _steps(d: str) -> list:
    """Return a path's commands as ``(command, numbers)`` pairs."""
    out, tokens = [], d.replace(",", " ").split()
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        n = {"M": 2, "L": 2, "A": 7, "Z": 0}[cmd]
        out.append((cmd, [round(float(t), 4) for t in tokens[i + 1 : i + 1 + n]]))
        i += 1 + n
    return out


def _stencil_steps(path: ET.Element) -> list:
    """Return a stencil path's steps in the same form as :func:`_steps`."""
    names = {"move": "M", "line": "L", "arc": "A", "close": "Z"}
    keys = {
        "move": ("x", "y"),
        "line": ("x", "y"),
        "arc": ("rx", "ry", "x-axis-rotation", "large-arc-flag", "sweep-flag", "x", "y"),
        "close": (),
    }
    return [
        (names[step.tag], [round(float(step.get(k, "nan")), 4) for k in keys[step.tag]])
        for step in path
    ]


def test_draw_io_gets_the_outline_the_sheet_draws():
    """Check that the draw.io export traces the drawing's own paths and rectangles."""
    unit = Deaerator("DA-1")
    fs = Flowsheet("Export")
    fs.add(unit)
    cell = next(c for c in _model(fs, check=False).iter("mxCell") if c.get("value") == unit.name)
    stencil = _inline_stencil(_style(cell).get("shape", ""))
    assert stencil is not None, f"{unit.name} exports as a box, not its outline"
    drawn = ET.fromstring(default_registry.get(unit.kind, unit.variant).svg)
    paths = [_steps(el.get("d", "")) for el in drawn.iter() if el.tag == "path"]
    rects = [
        tuple(float(el.get(k, "nan")) for k in ("x", "y", "width", "height"))
        for el in drawn.iter()
        if el.tag == "rect"
    ]
    assert [_stencil_steps(p) for p in stencil.iter("path")] == paths
    assert [
        tuple(float(r.get(k, "nan")) for k in ("x", "y", "w", "h")) for r in stencil.iter("rect")
    ] == rects
