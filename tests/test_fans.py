"""Check the fans: ISO 10628-2 item 17.1, the centrifugal fan and the axial fan."""

import math
import re

import pytest

from pandid import AxialFan, Blower, CentrifugalFan, Feed, Flowsheet, Product
from pandid.portgeom import port_faces
from pandid.render.symbols import default_registry

#: Table 2's grid module, in drawing units.
M = 10.0


def test_the_general_fan_is_row_17_1():
    """Check the circle, the two chords and the impeller of item 17.1."""
    fan = default_registry.get("blower", "general")
    assert (fan.width, fan.height) == (6 * M, 6 * M)
    assert '<circle cx="30" cy="30" r="30"' in fan.svg
    assert fan.ports == {"suction": (0.0, 30.0), "discharge": (60.0, 30.0), "drive": (30.0, 0.0)}
    assert fan.iso_reg == "X8164"

    chords = re.findall(r"M (\S+) (\S+) L (\S+) (\S+) ", fan.svg)
    assert len(chords) == 2
    for chord in chords:
        (ax, ay), (bx, by) = (
            (float(chord[0]), float(chord[1])),
            (float(chord[2]), float(chord[3])),
        )
        # Both ends on the circle, and the line through the grid points
        # 1.5 M left and 2.5 M off the axis, and 2.5 M right and 1.5 M off.
        assert math.dist((ax, ay), (30, 30)) == pytest.approx(30, abs=1e-3)
        assert math.dist((bx, by), (30, 30)) == pytest.approx(30, abs=1e-3)
        assert (by - ay) / (bx - ax) == pytest.approx(math.copysign(0.25, 30 - ay), abs=1e-4)
        assert ay + (15 - ax) * (by - ay) / (bx - ax) == pytest.approx(
            30 + math.copysign(25, ay - 30), abs=1e-3
        )
    # The impeller's three tips: 2 M ahead, and 1 M back 1.5 M off the axis.
    for tip in ("50 30", "20 15", "20 45"):
        assert tip in fan.svg


def test_a_bare_blower_draws_the_iso_fan():
    """Check that ``Blower()`` and ``variant="default"`` draw item 17.1."""
    for blower in (Blower("B-101"), Blower("B-102", variant="default")):
        assert blower.variant == "general"
        assert default_registry.for_unit(blower) is default_registry.get("blower", "general")


@pytest.mark.parametrize(("cls", "variant"), [(CentrifugalFan, "centrifugal"), (AxialFan, "axial")])
def test_each_fan_class_draws_its_variant_from_west_to_east(cls, variant):
    """Check that each fan class draws its own variant, suction west and discharge east."""
    fan = cls("K-101")
    assert isinstance(fan, Blower)
    assert (fan.kind, fan.variant) == ("blower", variant)
    assert port_faces(fan, "suction")[0] == "W"
    assert port_faces(fan, "discharge")[0] == "E"


def test_the_centrifugal_fan_discharges_through_its_outlet():
    """Check that the discharge is the middle of the scroll's outlet mouth."""
    fan = default_registry.get("blower", "centrifugal")
    x, y = fan.ports["discharge"]
    assert x == fan.width
    assert y == pytest.approx(10.0), "off the middle of the 2 M outlet"
    assert fan.ports["suction"] == (0.0, fan.height / 2)


def test_a_fan_draws_on_a_sheet():
    """Check that a centrifugal fan between two flags renders clean."""
    fs = Flowsheet("Exhaust")
    gas = fs.add(Feed("Dryer Off-Gas"))
    fan = fs.add(CentrifugalFan("K-101", description="Exhaust Fan"))
    stack = fs.add(Product("To Stack"))
    fs.connect(gas.outlet, fan.suction)
    fs.connect(fan.discharge, stack.inlet)

    assert 'id="sym_blower_centrifugal"' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
