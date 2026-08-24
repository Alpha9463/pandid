"""A draw.io child cell is placed and turned with the symbol it is part of.

Two mechanisms in :mod:`pandid.render.drawio` draw a symbol as a parent
cell with children inside it, and both state the child's rectangle in the
**symbol's** frame:

* ``_APPROXIMATIONS[...].pieces`` -- a stand-in that is several built-ins,
  such as the steam trap's body between its two leads;
* ``Symbol.overlays`` -- a composed drawing's ISO supplementary parts,
  such as a reactor's agitator on its shell.

mxGraph carries neither the parent's ``direction`` nor its flips into a
child's geometry: a child is positioned by its own numbers, relative to
the parent's origin and nothing else. A child that is a shape *beside*
its parent would not care. A child that is a piece **of the drawing**
does, and the failure is quiet in the worst way -- the sheet still opens,
every cell is present, and the symbol has come apart.

It came apart exactly once, on a trap laid on its side: a 40 x 60 cell
carrying three children still laid out along the *unturned* axis, so the
body and both leads were drawn as tall slivers side by side and the ink
met neither nozzle. The parts of a composed symbol had the same fault
and had had it longer.

So this file exports the same units upright and turned and asks what has
to be true of the pair. It never restates the mapping -- that would only
say the code computes what the code computes -- and instead asks for
properties a correct turn must have and a missing one cannot fake.
"""

import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, SteamTrap
from pandid import units

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
        style = dict(
            part.split("=", 1) for part in (cell.get("style") or "").split(";") if "=" in part
        )
        out[cell.get("id") or ""] = (
            style,
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
    """A quarter turn swaps a child's width and height, as it swaps the
    parent's.

    This is the property a missing turn cannot fake. Left unturned, a
    child's rectangle is still computed as fractions of the parent's box
    -- and the parent's box *has* swapped -- so the child comes out with
    a shape that is neither the upright one nor the turned one. Asserting
    the swap therefore catches the real failure without restating how the
    turn is worked out.
    """
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
    """Turning a child's *rectangle* is half the job; the other half is
    how the shape paints inside it.

    ``mxLine`` draws across its box horizontally and turns only for
    ``direction`` north or south, and a stencil like an agitator has a top
    and a bottom. So a child carries the parent's own direction -- not a
    decision of its own, because the whole drawing turns together.
    """
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
    """Laying a symbol on its side is not resizing it.

    ``drawio-approximated`` reports a drawing draw.io will stretch because
    no built-in can be told to keep its shape. A quarter turn swaps the
    cell's width and height, and comparing that against the symbol's
    *unturned* box made every upright drawing laid on its side report a
    resize it never had -- a false warning, which costs a reader exactly
    as much trust as a missing one.
    """
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
