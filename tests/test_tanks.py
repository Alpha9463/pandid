"""Check the rectangular tanks of ISO 10628-2 items 1.1 and 1.2, and stirred tanks and vessels."""

import math
import re
import xml.etree.ElementTree as ET

import pytest
from test_drawio import _inline_stencil
from test_symbol_invariants import Segment, _collect_segments, _nearest_distance

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


@pytest.mark.parametrize("unit", _STIRRED, ids=_STIRRED_IDS)
def test_the_stirrer_stops_at_the_foot_of_the_straight_wall(unit):
    """Check that the stirrer hangs in the straight shell, clear of a cone or bottom head."""
    sym = default_registry.for_unit(unit)
    body = _drawn_parts(unit, unit.__dict__["overlays"])[0]
    # The body's top, below the motor.
    shift = -min(0.0, *(o.y * body.height for o in sym.overlays))
    assert overlay_boxes(body, sym.overlays)[-2][3] == pytest.approx(body.bands["W"][1] + shift)


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


# The marks that tell each drawing apart, read back from what each backend emits.


def _emitted(unit: Unit) -> "tuple[list[Segment], float, float]":
    """Return the ink a unit is drawn with on a sheet of its own, in its box, and the box."""
    fs = Flowsheet("Emitted")
    fs.add(unit)
    svg = fs.to_svg()
    use = re.search(
        r'<use href="#([^"]+)" x="[^"]+" y="[^"]+" width="([^"]+)" height="([^"]+)"', svg
    )
    assert use is not None
    ref, w, h = use.group(1), float(use.group(2)), float(use.group(3))
    sym = re.search(
        rf'<symbol id="{re.escape(ref)}" viewBox="0 0 (\S+) (\S+)"[^>]*>(.*?)</symbol>', svg, re.S
    )
    assert sym is not None
    sx, sy = w / float(sym.group(1)), h / float(sym.group(2))
    ink = _collect_segments(f'<g xmlns="http://www.w3.org/2000/svg">{sym.group(3)}</g>')
    return [((a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy)) for a, b in ink], w, h


def _bare(ink: "list[Segment]", points: "list[tuple[float, float]]") -> list:
    """Return the points no ink passes within a unit of."""
    return [p for p in points if _nearest_distance(p, ink) > 1.0]


def _along(a: "tuple[float, float]", b: "tuple[float, float]", n: int = 9) -> list:
    """Return ``n`` points strictly between ``a`` and ``b``."""
    return [
        (a[0] + (b[0] - a[0]) * i / (n + 1), a[1] + (b[1] - a[1]) * i / (n + 1))
        for i in range(1, n + 1)
    ]


def test_the_sheet_draws_the_flat_roof_tank_closed_by_its_roof():
    """Check that item 1.1 is drawn as four walls, its roof inked from wall to wall."""
    ink, w, h = _emitted(Tank("TK-101", variant="flat_roof"))
    assert (w, h) == (80, 120)
    corners = [(0, 0), (80, 0), (80, 120), (0, 120)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        assert _bare(ink, _along(a, b)) == [], f"no ink from {a} to {b}"


def test_the_sheet_draws_the_open_top_tank_open():
    """Check that item 1.2 is drawn as two walls and a floor, and nothing across its top."""
    ink, w, h = _emitted(Tank("TK-101", variant="open_top"))
    assert (w, h) == (80, 60)
    for a, b in [((0, 0), (0, 60)), ((0, 60), (80, 60)), ((80, 60), (80, 0))]:
        assert _bare(ink, _along(a, b)) == [], f"no ink from {a} to {b}"
    top = _along((10, 0), (70, 0))
    assert _bare(ink, top) == top, "the open tank is drawn with a roof"


@pytest.mark.parametrize(
    ("unit", "roof"),
    [
        (Tank("TK-1", variant="flat_roof", agitator="turbine"), True),
        (Tank("TK-2", variant="flat_roof", agitator="turbine", width=70, height=200), True),
        (Tank("TK-3", variant="open_top", agitator="propeller", width=200, height=100), False),
        (Vessel("V-1", agitator="anchor", width=120, height=150), False),
    ],
    ids=["flat-roof", "tall-flat-roof", "wide-open-top", "wide-vessel"],
)
def test_the_sheet_draws_a_round_motor_over_the_roof_on_a_shaft_into_the_body(unit, roof):
    """Check the item 1.27 marks: a 2 M motor 1 M above the body, its shaft running into it."""
    ink, w, h = _emitted(unit)
    r, top = MOTOR_D / 2, MOTOR_D + MOTOR_GAP
    rim = [
        (w / 2 + r * math.cos(k * math.pi / 6), r + r * math.sin(k * math.pi / 6))
        for k in range(12)
    ]
    assert _bare(ink, rim) == [], "the motor is not a circle 2 M across at the top of the box"
    assert _bare(ink, _along((w / 2, MOTOR_D), (w / 2, top + 2 * M))) == [], "no shaft"
    if roof:
        assert _bare(ink, _along((0, top), (w, top))) == [], "the roof is not under the motor"
    beside = [(x, r) for x in (w / 2 - 2 * MOTOR_D, w / 2 + 2 * MOTOR_D)]
    assert _bare(ink, beside) == beside, "the body reaches up beside the motor"


def _exported(unit: Unit) -> "tuple[dict[str, ET.Element], str]":
    """Return the draw.io cells a unit exports as on a sheet of its own, and its cell id."""
    fs = Flowsheet("Export")
    fs.add(unit)
    cells = {c.get("id", ""): c for c in ET.fromstring(fs.to_drawio()).iter("mxCell")}
    return cells, next(k for k, c in cells.items() if c.get("value") == unit.name)


def _geometry(cell: ET.Element) -> "tuple[float, ...]":
    """Return a cell's ``x``, ``y``, ``width`` and ``height``."""
    box = cell.find("mxGeometry")
    assert box is not None
    return tuple(float(box.get(k, "nan")) for k in ("x", "y", "width", "height"))


def _outline(cells: "dict[str, ET.Element]", cid: str) -> ET.Element:
    """Return the inline stencil a cell is drawn with."""
    shape = re.search(r"shape=(stencil\([^)]*\))", cells[cid].get("style") or "")
    assert shape, f"{cid} is not drawn with its own outline"
    stencil = _inline_stencil(shape.group(1))
    assert stencil is not None
    return stencil


def test_draw_io_draws_the_flat_roof_tank_closed_and_the_open_top_open():
    """Check that the export draws item 1.1 as a filled box and item 1.2 as an open stroke."""
    cells, cid = _exported(Tank("TK-101", variant="flat_roof"))
    rects = [
        tuple(float(r.get(k, "nan")) for k in ("x", "y", "w", "h"))
        for r in _outline(cells, cid).iter("rect")
    ]
    assert rects == [(0, 0, 80, 120)]
    cells, cid = _exported(Tank("TK-102", variant="open_top"))
    outline = _outline(cells, cid)
    path = outline.find("foreground/path")
    assert path is not None
    steps = [(step.tag, float(step.get("x", "nan")), float(step.get("y", "nan"))) for step in path]
    assert steps == [("move", 0, 0), ("line", 0, 60), ("line", 80, 60), ("line", 80, 0)]
    assert outline.find("foreground/rect") is None
    assert outline.find("foreground/fillstroke") is None


def test_draw_io_draws_a_stirred_tank_under_a_round_motor_on_its_shaft():
    """Check that the export puts a 2 M motor on top, the stirrer under it, and the body below."""
    tank = Tank("TK-101", variant="flat_roof", agitator="turbine", width=70, height=200)
    cells, cid = _exported(tank)
    stencil = _outline(cells, cid)
    roof = next(stencil.iter("rect"))
    # The body's roof, in the cell's own units.
    drawn = float(roof.get("y", "nan")) / float(stencil.get("h", "nan")) * _geometry(cells[cid])[3]
    assert drawn == pytest.approx(MOTOR_D + MOTOR_GAP, abs=0.01)
    stirrer, motor = cells[f"{cid}-p0"], cells[f"{cid}-p1"]
    assert "shape=ellipse" in (motor.get("style") or "")
    assert _geometry(motor) == pytest.approx((25, 0, MOTOR_D, MOTOR_D))
    assert "agitators.agitator_(turbine)" in (stirrer.get("style") or "")
    x, y, w, _ = _geometry(stirrer)
    assert (x + w / 2, y) == pytest.approx((35, MOTOR_D))


@pytest.mark.parametrize(
    ("make", "variant"),
    [
        (lambda: Tank("TK-101", agitator="turbine"), "floating_roof"),
        (lambda: Vessel("V-101", agitator="anchor"), "horizontal"),
    ],
    ids=["tank-to-floating-roof", "vessel-to-drum"],
)
def test_a_stirred_body_reassigned_to_a_variant_that_cannot_carry_it_is_refused(make, variant):
    """Check that reassigning the variant refuses as the constructor does, and keeps the old one."""
    unit = make()
    with pytest.raises(ValueError, match=f"variant {variant!r} cannot carry agitator="):
        unit.variant = variant
    assert unit.variant == "default"
    fs = Flowsheet("Kept")
    fs.add(unit)
    fs.to_svg()
