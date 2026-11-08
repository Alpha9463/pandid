"""Check the electric motor and the shaft that drives a machine."""

import xml.etree.ElementTree as ET

import pytest
from test_drawio import _inline_stencil, _model, _style

from pandid import Blower, Conveyor, Feed, Flowsheet, Mill, Motor, Product, Pump, Reactor
from pandid.layout.attach import _free_face
from pandid.layout.drives import SHAFT
from pandid.portgeom import resolve_port, unit_box
from pandid.render.symbols import default_registry
from pandid.route_geometry import stream_polyline
from pandid.routing.visibility import VisibilityGraph


def _driven(machine, inlet: str, outlet: str, variant: str = "general"):
    """Return a sheet piping a machine from a feed to a product, with a motor on it."""
    fs = Flowsheet("Drive")
    feed = fs.add(Feed("Feed"))
    fs.add(machine)
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, machine.ports[inlet])
    fs.connect(machine.ports[outlet], product.inlet)
    motor = fs.add(Motor("M-1", variant=variant))
    shaft = fs.connect(motor.shaft, machine.drive)
    return fs, motor, shaft


@pytest.fixture(scope="module")
def pump_sheet():
    """Draw a pumped line whose pump has a motor."""
    fs, motor, shaft = _driven(Pump("P-1"), "suction", "discharge", variant="ac")
    svg = fs.to_svg(diagram="p&id")
    return fs, motor, shaft, svg


def test_a_motor_stands_on_its_pump_a_short_straight_shaft_above_the_drive(pump_sheet):
    """Check that the motor is drawn over the pump's drive, joined by a short shaft."""
    fs, motor, shaft, _ = pump_sheet
    pump = shaft.dest.owner
    drive = resolve_port(pump, pump.frame, "drive")
    end = resolve_port(motor, motor.frame, "shaft")
    assert (drive.face, end.face) == ("N", "S")
    assert end.point == (drive.point[0], drive.point[1] - SHAFT)
    assert stream_polyline(shaft) == [end.point, drive.point]
    assert shaft.kind == "mechanical"
    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_a_shaft_has_no_number_arrowhead_or_line_list_row(pump_sheet):
    """Check that the shaft is drawn as a bare line and scheduled nowhere but the motor."""
    fs, motor, shaft, svg = pump_sheet
    (x0, y0), (x1, y1) = stream_polyline(shaft)
    assert (
        f'<path d="M {x0},{y0} L {x1},{y1}" fill="none" stroke="black" stroke-width="2" />' in svg
    )
    assert f">{shaft.name}</text>" not in svg
    assert [row["line"] for row in fs.line_list()] == ["S1", "S2"]
    assert [row["tag"] for row in fs.equipment_list()] == ["P-1", "M-1"]
    assert 'id="sym_motor_ac"' in svg


def test_a_mill_takes_its_motor_on_the_east():
    """Check that a machine whose drive faces east has its motor beside it, level."""
    fs, motor, shaft = _driven(Mill("ML-1"), "feed", "discharge")
    fs.to_svg()
    mill = shaft.dest.owner
    drive = resolve_port(mill, mill.frame, "drive")
    end = resolve_port(motor, motor.frame, "shaft")
    assert (drive.face, end.face) == ("E", "W")
    assert end.point == (drive.anchor[0] + SHAFT, drive.point[1])
    assert stream_polyline(shaft) == [end.point, drive.point]


def test_the_layout_keeps_room_for_the_motor_above_a_belt_conveyor():
    """Check that nothing else is drawn where the motor stands."""
    fs, motor, shaft = _driven(Conveyor("CV-1"), "feed", "discharge", variant="dc")
    fs.to_svg()
    box = unit_box(motor, motor.frame)
    others = [u for u in fs.units if u is not motor and u.frame is not None]
    assert all(
        b[2] <= box[0] or box[2] <= b[0] or b[3] <= box[1] or box[3] <= b[1]
        for b in (unit_box(u, u.frame) for u in others)
    )
    assert box[1] >= 0.0


def test_an_unconnected_drive_takes_no_routing_track():
    """Check that a pump's free drive adds nothing to the router's grid."""
    fs = Flowsheet("Free drive")
    pump = fs.add(Pump("P-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(Product("Product")).inlet)
    fs.to_svg()
    graph = VisibilityGraph(fs)
    assert ("P-1", "drive") not in graph.port_anchors
    assert ("P-1", "suction") in graph.port_anchors


def test_a_free_drive_is_no_nozzle_a_balloon_moves_to():
    """Check that a balloon put off a fan's used east face ignores its free drive."""
    fs = Flowsheet("Fan")
    fan = fs.add(Blower("F-1", variant="axial"))
    fs.connect(fs.add(Feed("Air")).outlet, fan.suction)
    fs.connect(fan.discharge, fs.add(Product("Duct")).inlet)
    fs.to_svg()
    assert _free_face(fan) == "E"


@pytest.mark.parametrize(
    ("join", "says"),
    [
        (lambda m, p: (m.shaft, p.suction), "fs.connect(M-1.shaft, P-1.drive)"),
        (lambda m, p: (p.discharge, p.drive), "fs.connect(<driver>.shaft, P-1.drive)"),
        (lambda m, p: (p.discharge, p.suction, "mechanical"), "kind='mechanical'"),
        (lambda m, p: (m.shaft, p.drive, "material"), "leave kind unset"),
    ],
    ids=["shaft to a nozzle", "pipe to a drive", "mechanical pipe", "material shaft"],
)
def test_a_shaft_joins_a_driver_s_shaft_to_a_machine_s_drive(join, says):
    """Check that a shaft joined to anything else is refused, naming the fix."""
    fs = Flowsheet("Wrong")
    pump, motor = fs.add(Pump("P-1")), fs.add(Motor("M-1"))
    src, dst, *kind = join(motor, pump)
    with pytest.raises(ValueError, match=says.replace("(", r"\(").replace(")", r"\)")):
        fs.connect(src, dst, kind=kind[0] if kind else None)
    assert fs.streams == []


def test_a_stirred_reactor_refuses_a_second_motor():
    """Check that a reactor drawn with its own motor takes no Motor on its drive."""
    fs = Flowsheet("Reactor")
    reactor, motor = fs.add(Reactor("R-1")), fs.add(Motor("M-1"))
    with pytest.raises(ValueError, match="drawn with its own motor"):
        fs.connect(motor.shaft, reactor.drive)
    assert fs.streams == []


def test_a_spec_keeps_the_motor_and_where_it_is_drawn(pump_sheet):
    """Check that a spec writes the motor, its shaft and its place, and reads them back."""
    fs, motor, shaft, svg = pump_sheet
    spec = fs.to_dict()
    assert {"kind": "Motor", "name": "M-1", "variant": "ac"} in spec["units"]
    assert {"from": ["M-1", "shaft"], "to": ["P-1", "drive"]} in spec["streams"]
    placed = spec["layout"]["units"]["M-1"]
    assert (placed["x"], placed["y"]) == (motor.frame.x, motor.frame.y)
    assert placed["port_faces"] == {"shaft": "S"}
    assert Flowsheet.from_dict(spec).to_svg(diagram="p&id") == svg


def test_a_spec_draws_the_motor_where_its_layout_puts_it(pump_sheet):
    """Check that the read-back sheet draws the motor at the layout's place."""
    fs, motor, _, _ = pump_sheet
    spec = fs.to_dict()
    spec["layout"]["units"]["M-1"]["x"] += 40.0
    back = Flowsheet.from_dict(spec)
    back.to_svg(diagram="p&id")
    moved = next(u for u in back.units if u.name == "M-1")
    assert moved.frame is not None and moved.frame.x == motor.frame.x + 40.0


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


@pytest.mark.parametrize("variant", ["general", "ac", "dc"])
def test_draw_io_gets_the_motor_and_a_bare_shaft(variant):
    """Check that draw.io traces the motor's own strokes and draws the shaft bare."""
    fs, motor, shaft = _driven(Pump("P-1"), "suction", "discharge", variant=variant)
    cells = list(_model(fs, check=False).iter("mxCell"))
    cell = next(c for c in cells if c.get("value") == motor.name)
    stencil = _inline_stencil(_style(cell).get("shape", ""))
    assert stencil is not None, f"{motor.name} exports as a box, not its outline"
    drawn = ET.fromstring(default_registry.get("motor", variant).svg)
    assert [_stencil_steps(p) for p in stencil.iter("path")] == [
        _steps(el.get("d", "")) for el in drawn.iter() if el.tag == "path"
    ]
    assert len(list(stencil.iter("ellipse"))) == 1
    edge = next(c for c in cells if c.get("id") == f"s{fs.streams.index(shaft)}")
    style = _style(edge)
    assert (edge.get("value"), style["endArrow"], style["startArrow"]) == ("", "none", "none")
