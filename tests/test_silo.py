"""Check the silo and the bunker, ISO 10628-2 items 1.9 and 1.8."""

import re
import xml.etree.ElementTree as ET

import pytest
from test_drawio import _inline_stencil

from pandid import Bunker, Conveyor, Feed, Flowsheet, Product, Silo
from pandid.portgeom import port_faces
from pandid.render.symbols import default_registry

#: Table 2's grid module, in drawing units.
M = 10.0

#: The walls and cone both rows share: 6 M apart, 6 M deep, a 3 M cone.
WALLS = "M 0 0 L 0 60 L 30 90 L 60 60 L 60 0"


def test_the_silo_is_row_1_9_closed_over_its_cone():
    """Check that the default silo is item 1.9's walls and cone with the roof drawn."""
    silo = default_registry.get("silo")
    assert (silo.width, silo.height) == (6 * M, 9 * M)
    assert f'd="{WALLS} Z"' in silo.svg
    assert silo.iso_reg == "X2062"
    assert silo.ports == {"feed": (0.0, M), "discharge": (3 * M, 9 * M), "vent": (3 * M, 0.0)}


def test_the_bunker_is_row_1_8_open_at_the_top():
    """Check that the bunker is item 1.8's walls and cone with no roof."""
    bunker = default_registry.get("silo", "bunker")
    assert (bunker.width, bunker.height) == (6 * M, 9 * M)
    assert f'd="{WALLS}"' in bunker.svg
    assert 'fill="none"' in bunker.svg, "an open bunker is drawn as if it had a roof"
    assert bunker.iso_reg == "2064"
    assert bunker.ports == {"feed": (0.0, M), "discharge": (3 * M, 9 * M)}


@pytest.mark.parametrize(
    ("unit", "faces"),
    [
        (Silo("SI-101"), {"feed": "W", "vent": "N", "discharge": "S"}),
        (Bunker("BN-101"), {"feed": "W", "discharge": "S"}),
    ],
    ids=["silo", "bunker"],
)
def test_each_nozzle_leaves_by_its_own_face(unit, faces):
    """Check that solids enter the west wall and leave the cone, and the silo vents up."""
    assert {name: port_faces(unit, name)[0] for name in unit.ports} == faces


def test_a_bunker_is_the_silo_kind_without_a_roof_vent():
    """Check that ``Bunker`` draws the silo kind's open row and builds no vent."""
    bunker = Bunker("BN-101")
    assert isinstance(bunker, Silo)
    assert (bunker.kind, bunker.variant) == ("silo", "bunker")
    assert "vent" not in bunker.ports


def test_a_silo_between_two_conveyors_draws_and_is_scheduled():
    """Check a silo fed and drawn off by conveyors renders clean and is listed."""
    fs = Flowsheet("Storage")
    feed = fs.add(Feed("Concentrate"))
    belt_in = fs.add(Conveyor("CV-101"))
    silo = fs.add(Silo("SI-101", description="Concentrate Silo"))
    belt_out = fs.add(Conveyor("CV-102"))
    out = fs.add(Product("To Loadout"))
    fs.connect(feed.outlet, belt_in.feed)
    fs.connect(belt_in.discharge, silo.feed)
    fs.connect(silo.discharge, belt_out.feed)
    fs.connect(belt_out.discharge, out.inlet)

    assert 'id="sym_silo"' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert "SI-101" in [row["tag"] for row in fs.equipment_list()]


def _exported_outline(unit) -> "tuple[list[tuple[str, float, float]], bool]":
    """Return the draw.io stencil path a unit exports as, and whether it is filled."""
    fs = Flowsheet("Export")
    feed = fs.add(Feed("F"))
    fs.add(unit)
    out = fs.add(Product("P"))
    fs.connect(feed.outlet, unit.feed)
    fs.connect(unit.discharge, out.inlet)
    cell = next(
        c for c in ET.fromstring(fs.to_drawio()).iter("mxCell") if c.get("value") == unit.name
    )
    shape = re.search(r"shape=(stencil\([^)]*\))", cell.get("style", ""))
    assert shape, f"{unit.name} exports as a {cell.get('style')!r} box, not its outline"
    stencil = _inline_stencil(shape.group(1))
    assert stencil is not None
    path = stencil.find("foreground/path")
    assert path is not None
    steps = [
        (step.tag, float(step.get("x", "nan")), float(step.get("y", "nan")))
        for step in path
        if step.tag != "close"
    ]
    return steps, stencil.find("foreground/fillstroke") is not None


@pytest.mark.parametrize(
    ("unit", "variant", "closed"),
    [(Silo("SI-101"), "default", True), (Bunker("BN-101"), "bunker", False)],
    ids=["silo", "bunker"],
)
def test_draw_io_gets_the_outline_the_sheet_draws(unit, variant, closed):
    """Check that the draw.io export traces the SVG outline, open or closed as drawn."""
    d = re.search(r' d="([^"]*)"', default_registry.get("silo", variant).svg)
    assert d
    tokens = d.group(1).split()
    drawn = [
        ("move" if tokens[i] == "M" else "line", float(tokens[i + 1]), float(tokens[i + 2]))
        for i in range(0, len(tokens), 3)
        if tokens[i] in "ML"
    ]
    steps, filled = _exported_outline(unit)
    assert steps == drawn
    assert filled == closed
