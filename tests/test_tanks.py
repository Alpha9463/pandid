"""Check the rectangular tanks of ISO 10628-2 items 1.1 and 1.2."""

import pytest

from pandid import Tank
from pandid.portgeom import port_faces
from pandid.render.symbols import default_registry

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
