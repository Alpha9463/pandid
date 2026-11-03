"""Check that a draw.io child cell is placed and turned with the symbol it is part of."""

import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, SteamTrap
from pandid import units

from test_drawio import _style

#: The two quarter turns. A half turn leaves the axes alone, so it cannot
#: tell a turned child from an unturned one and is no use here; it is
#: covered for the trap in ``tests/test_steam_trap.py``.
QUARTERS = [90, 270]


def _export(
    unit_factory, orientation: int
) -> "dict[str, tuple[dict[str, str], tuple[float, float, float, float]]]":
    """One unit, pinned at *orientation*, as ``{cell id: (style, box)}``."""
    fs = Flowsheet("turned")
    unit = fs.add(unit_factory())
    unit.pin(x=400.0, y=400.0, orientation=orientation)
    fs.layout()
    document = fs.to_drawio()
    out = {}
    for cell in ET.fromstring(document).iter("mxCell"):
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        out[cell.get("id") or ""] = (
            _style(cell),
            tuple(float(geometry.get(key, 0)) for key in ("x", "y", "width", "height")),
        )
    return out


def _children(cells, marker: str):
    """The child cells of the one placed unit, in the order written."""
    ours = [cid for cid in cells if cid and marker in cid and "-" in cid]
    assert ours, (
        f"the export drew no {marker!r} child cells at all, so this unit is not "
        f"exercising the mechanism the test is about"
    )
    parent = ours[0]
    root = parent.split("-")[0]
    return cells[root], [cells[cid] for cid in sorted(cells) if cid.startswith(f"{root}-")]


#: The two ways a symbol gets child cells, and a unit that exercises each.
#:
#: ``SteamTrap`` is the ``pieces=`` case: a body between two leads, which
#: is the mechanism this repository added for it. ``Reactor`` is the
#: ``overlays`` case, and its agitator is the part that had been drawn
#: across a vessel lying the other way.
MECHANISMS = [
    pytest.param(lambda: SteamTrap("T-701"), "-s", id="pieces/steam_trap"),
    pytest.param(lambda: units.Reactor("R-1", agitator="disc"), "-p", id="overlays/reactor"),
    pytest.param(
        lambda: units.Column("T-1", internals="packing", trays=2), "-p", id="overlays/column"
    ),
    pytest.param(lambda: units.Vessel("D-1", supports="leg"), "-p", id="overlays/vessel"),
]


@pytest.mark.parametrize(
    "factory,marker",
    [(p.values[0], p.values[1]) for p in MECHANISMS],
    ids=[p.id for p in MECHANISMS],
)
@pytest.mark.parametrize("rot", QUARTERS)
def test_a_child_turns_with_the_symbol_it_is_part_of(factory, marker, rot):
    """Check that a quarter turn swaps a child's width and height as it swaps the parent's."""
    upright_parent, upright = _children(_export(factory, 0), marker)
    turned_parent, turned = _children(_export(factory, rot), marker)

    assert upright and len(turned) == len(upright), "a child went missing in the turn"
    # The parent swapped, which is what makes the question meaningful.
    assert turned_parent[1][2] == pytest.approx(upright_parent[1][3], abs=0.02)
    assert turned_parent[1][3] == pytest.approx(upright_parent[1][2], abs=0.02)

    for (_style_up, up), (_style_turned, over) in zip(upright, turned):
        assert over[2] == pytest.approx(up[3], abs=0.02), (
            "the child's width did not become its upright height, so it was "
            "laid out in a frame the symbol is no longer in"
        )
        assert over[3] == pytest.approx(up[2], abs=0.02)


@pytest.mark.parametrize(
    "factory,marker",
    [(p.values[0], p.values[1]) for p in MECHANISMS],
    ids=[p.id for p in MECHANISMS],
)
@pytest.mark.parametrize("rot", QUARTERS)
def test_a_turned_child_paints_the_way_its_parent_does(factory, marker, rot):
    """Check that a turned child carries its parent's painting ``direction``."""
    cells = _export(factory, rot)
    parent, children = _children(cells, marker)
    direction = parent[0].get("direction")
    assert direction, "the parent did not record the turn at all"
    for style, _box in children:
        assert style.get("direction") == direction, (
            "a child kept the upright painting direction while its parent turned"
        )


@pytest.mark.parametrize(
    "factory,marker",
    [(p.values[0], p.values[1]) for p in MECHANISMS],
    ids=[p.id for p in MECHANISMS],
)
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_a_symbol_at_its_own_size_is_never_reported_as_reproportioned(factory, marker, rot):
    """Check that turning a symbol is not reported as resizing it."""
    fs = Flowsheet("turned")
    unit = fs.add(factory())
    unit.pin(x=400.0, y=400.0, orientation=rot)
    fs.layout()
    fs.to_drawio()
    assert [
        issue.message
        for issue in fs.warnings
        if issue.code == "drawio-approximated" and "reproportioned" in issue.message
    ] == []
