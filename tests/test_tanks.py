"""Check the rectangular tanks of ISO 10628-2 items 1.1 and 1.2, and stirred tanks and vessels."""

import xml.etree.ElementTree as ET

import pytest

from pandid import Feed, Flowsheet, Product, Tank, Vessel
from pandid.portgeom import port_faces, resolve_size
from pandid.render.iso_parts import MOTOR_D, MOTOR_GAP
from pandid.render.symbols import default_registry, overlay_boxes
from pandid.units import Unit, _drawn_parts

#: Table 2's grid module, in drawing units.
M = 10.0


def test_the_flat_roof_tank_is_row_1_1():
    """Check that the flat-roof tank is item 1.1's 8 M by 12 M rectangle."""
    sym = default_registry.get("tank", "flat_roof")
    assert (sym.width, sym.height) == (8 * M, 12 * M)
    assert '<rect x="0" y="0" width="80" height="120"' in sym.svg
    assert sym.iso_reg == "301"
    assert sym.ports == {
        "inlet": (0.0, 11 * M),
        "outlet": (4 * M, 12 * M),
        "vent": (2 * M, 0.0),
        "relief": (6 * M, 0.0),
        "drain": (2 * M, 12 * M),
    }


def test_the_open_top_tank_is_row_1_2_with_no_roof_or_roof_nozzles():
    """Check that the open-top tank is item 1.2's 8 M by 6 M open walls, and vents nowhere."""
    sym = default_registry.get("tank", "open_top")
    assert (sym.width, sym.height) == (8 * M, 6 * M)
    assert 'd="M 0 0 L 0 60 L 80 60 L 80 0"' in sym.svg
    assert 'fill="none"' in sym.svg, "an open tank is drawn as if it had a roof"
    assert sym.iso_reg == "2061"
    assert set(Tank("TK-101", variant="open_top").ports) == {"in_1", "out_1", "drain"}


@pytest.mark.parametrize(
    ("variant", "faces"),
    [
        ("flat_roof", {"in_1": "W", "out_1": "S", "vent": "N", "relief": "N", "drain": "S"}),
        ("open_top", {"in_1": "W", "out_1": "S", "drain": "S"}),
    ],
)
def test_each_rectangular_tank_nozzle_leaves_by_its_own_face(variant, faces):
    """Check that each rectangular tank fills low on its west wall and draws off its floor."""
    tank = Tank("TK-101", variant=variant)
    assert {name: port_faces(tank, name)[0] for name in tank.ports} == faces


_STIRRED = [
    *(Tank(f"TK-{variant}", variant=variant, agitator="turbine") for variant in Tank._STIRRABLE),
    *(Vessel(f"V-{variant}", variant=variant, agitator="anchor") for variant in Vessel._STIRRABLE),
]
_STIRRED_IDS = [f"{unit.kind}/{unit.variant}" for unit in _STIRRED]


@pytest.mark.parametrize("unit", _STIRRED, ids=_STIRRED_IDS)
def test_a_stirred_body_takes_its_motor_and_drive_and_leaves_the_roof_to_it(unit):
    """Check that an agitator brings its motor and drive, and moves the vent and relief off the roof."""
    parts = default_registry.for_unit(unit).overlays
    assert [(o.group, o.name) for o in parts][-2:] == [(28, unit.agitator), (20, "motor")]
    assert port_faces(unit, "drive") == ["N"]
    if "vent" in unit.ports:
        assert port_faces(unit, "vent") == ["E"]
        assert port_faces(unit, "relief") == ["W"]
    assert "N" not in port_faces(unit, "in_1")


def test_a_body_without_an_agitator_has_no_drive():
    """Check that only a stirred tank or vessel has a drive."""
    assert "drive" not in Tank("TK-101").ports
    assert "drive" not in Vessel("V-101").ports


def _motor(unit: Unit) -> tuple[float, float]:
    """Return the drawn width and height of a unit's motor."""
    sym = default_registry.for_unit(unit)
    body = _drawn_parts(unit, unit.__dict__["overlays"])[0]
    left, top, right, bottom = overlay_boxes(body, sym.overlays)[-1]
    w, h = resolve_size(unit)
    return (right - left) * w / sym.width, (bottom - top) * h / sym.height


@pytest.mark.parametrize(
    "unit",
    [
        Tank("TK-1", agitator="turbine"),
        Tank("TK-2", agitator="turbine", width=70, height=90),
        Tank("TK-3", variant="open_top", agitator="propeller", width=200, height=100),
        Vessel("V-1", agitator="anchor"),
        Vessel("V-2", variant="jacketed", agitator="anchor", width=120, height=150),
    ],
    ids=["tank", "narrow-tank", "wide-open-tank", "vessel", "wide-vessel"],
)
def test_the_motor_is_drawn_at_its_own_size_whatever_the_box(unit):
    """Check that the motor keeps its item 1.27 diameter, a circle, at any box."""
    assert _motor(unit) == pytest.approx((MOTOR_D, MOTOR_D))
    fs = Flowsheet("Sized")
    fs.add(unit)
    fs.to_svg()
    assert "symbol-out-of-aspect" not in [issue.code for issue in fs.validate()]


def test_a_stated_height_holds_the_motor_over_the_tank():
    """Check that a height is the drawn box, motor included, and a too-short one is refused."""
    tank = Tank("TK-101", agitator="turbine", width=90, height=150)
    assert resolve_size(tank) == (90, 150)
    with pytest.raises(ValueError, match="TK-102: a height of 25 leaves no room for the body"):
        Tank("TK-102", agitator="turbine", height=MOTOR_D + MOTOR_GAP - 5).symbol()


def test_a_stirred_tank_with_its_vent_and_relief_piped_draws_clean():
    """Check that a stirred tank fed and drawn off, venting and relieving, has no error."""
    fs = Flowsheet("Mix tank")
    feed = fs.add(Feed("Feed"))
    tank = fs.add(Tank("TK-101", variant="flat_roof", agitator="turbine"))
    out = fs.add(Product("Product"))
    vent = fs.add(Product("Vent"))
    flare = fs.add(Product("Flare"))
    fs.connect(feed.outlet, tank.inlet)
    fs.connect(tank.outlet, out.inlet)
    fs.connect(tank.vent, vent.inlet)
    fs.connect(tank.relief, flare.inlet)
    fs.to_svg(diagram="p&id")
    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_draw_io_draws_a_stirred_tank_under_a_round_motor():
    """Check that the export draws the tank body in place and the motor as a circle."""
    fs = Flowsheet("Export")
    feed = fs.add(Feed("F"))
    tank = fs.add(Tank("TK-101", agitator="turbine", width=70, height=120))
    fs.connect(feed.outlet, tank.inlet)
    cells = {c.get("id"): c for c in ET.fromstring(fs.to_drawio()).iter("mxCell")}
    cid = next(k for k, c in cells.items() if c.get("value") == "TK-101")
    assert "shape=stencil(" in (cells[cid].get("style") or "")
    motor = cells[f"{cid}-p1"].find("mxGeometry")
    assert motor is not None
    assert (float(motor.get("width", "nan")), float(motor.get("height", "nan"))) == (
        MOTOR_D,
        MOTOR_D,
    )
