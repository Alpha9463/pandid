"""The ISO 10628-2 groups 26-29 artwork, held to the table it claims to be.

``tests/test_composition.py`` holds the *mechanism* -- what ``compose`` does
with a body and a part. This file holds the *drawings*: that each one names a
real Table 2 row, that it is drawn on the module grid at the detail weight,
that it fits the box it declares, and that it composes onto a real body without
the caller having to know anything about it.

The one test here that is a claim rather than a check is
:func:`test_no_agitator_shaft_is_dashed`. Table 2 draws a short thin stroke a
module above each agitator, which reads at a glance as the top of a dashed
shaft and was reported as one. Clause 5 column 3 says what it actually is --
"Preferred locations of connections at graphical symbols are indicated by
'—'. This is not a part of the graphical symbol." -- and every group-28 shaft
under it is a single solid stroke. The test is what stops that correction being
undone by the next reader of the same page.
"""

import math
import re

import pytest

from pandid.render import iso_parts
from pandid.render.svg import _SYMBOL_STROKE
from pandid.render.symbols import Overlay, Symbol, compose, default_registry
from test_symbol_invariants import _collect_segments

# Every part, quoted from ISO 10628-2:2012 Table 2 by item number,
# registration number and the standard's own descriptor. A reader with the
# standard checks this table against four columns of one page; the drawing it
# guards is checked by eye against the fifth. Spelled out here rather than read
# off the parts, so a typo in a registration number is a failing test and not a
# quieter version of the same drawing.
TABLE_2 = {
    (26, "leg"): ("26.1", "C2005", "Support leg"),
    (26, "bracket"): ("26.2", "C2006", "Support bracket"),
    (26, "skirt"): ("26.3", "C2007", "Support skirt"),
    (26, "ring"): ("26.4", "C2008", "Support ring"),
    (27, "tray"): ("27.1", "C2044", "Tray (general)"),
    (27, "baffle_tray"): ("27.2", "X8166", "Tray with baffle"),
    (27, "bubble_cap_tray"): ("27.3", "C2010", "Tray, bubble-cap type"),
    (27, "valve_tray"): ("27.4", "C2011", "Tray, valve type"),
    (27, "sieve_tray"): ("27.5", "2602", "Sieve tray, screen or sieve element"),
    (27, "filter_insert"): ("27.6", "C2047", "Filter insert (general)"),
    (27, "fluidised_bed"): ("27.7", "2604", "Fluidized bed"),
    (27, "packing"): ("27.8", "X8141", "packing"),
    (28, "agitator"): ("28.1", "2672", "Agitator (general), stirrer (general)"),
    (28, "flat_blade"): ("28.2", "C2019", "Agitator, flat-blade paddle type"),
    (28, "gate_paddle"): ("28.3", "C2020", "Agitator, gate paddle type"),
    (28, "cross_beam"): ("28.4", "C2021", "Agitator, cross-beam type"),
    (28, "anchor"): ("28.5", "C2022", "Agitator, anchor type"),
    (28, "helical"): ("28.6", "C2023", "Agitator, helical type"),
    (28, "impeller"): ("28.7", "C2024", "Agitator, impeller type"),
    (28, "propeller"): ("28.8", "C2025", "Agitator, propeller type"),
    (28, "disc"): ("28.9", "C2026", "Agitator, disc type"),
    (28, "turbine"): ("28.10", "C2027", "Agitator, turbine type"),
    (29, "gravity"): ("29.1", "C2028", "Gravity type, settling type"),
    (29, "electrostatic"): ("29.2", "C2030", "Electrostatic type"),
    (29, "electromagnetic"): ("29.3", "C2031", "Electromagnetic type"),
}

PARTS = iso_parts.parts()
IDS = [f"{p.iso.group}/{p.name}" for p in PARTS]


def body(width=80.0, height=200.0) -> Symbol:
    """A plain body to hang a part on."""
    return Symbol(
        svg=f'<g id="sym_body"><rect x="0" y="0" width="{width:g}" height="{height:g}" '
        f'fill="none" stroke="black" stroke-width="2"/></g>',
        width=width,
        height=height,
        ports={"inlet": (0.0, height / 2), "outlet": (width / 2, height)},
    )


# --- identity -----------------------------------------------------------------


def test_every_registered_part_is_one_this_module_draws():
    assert default_registry.parts() == sorted(PARTS, key=lambda p: p.key())


def test_the_parts_are_exactly_the_table_2_rows_they_claim():
    assert {p.key(): (p.iso.item, p.iso.reg, p.iso.name) for p in PARTS} == TABLE_2


def test_each_group_ships_the_items_it_was_drawn_for():
    """26's four supports, 27's eight internals, 28's ten agitators, and the
    three group-29 characteristics whose composition onto ISO group 8's
    separating vessel is verified glyph for glyph (8.3, 8.6, 8.8).

    The other eleven group-29 items and group 26's manhole and socket are
    deliberately absent, not overlooked: a part is drawn when something
    composes from it. Two of the absences carry an argument -- group 29 has no
    vortex, which is why ISO 8.10 X2618 is a symbol of its own, and no spray,
    which is why 8.7 X8033 cannot be composed either.
    """
    counts = {g: len(default_registry.part_names(g)) for g in (26, 27, 28, 29)}
    assert counts == {26: 4, 27: 8, 28: 10, 29: 3}


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_asked_for_by_group_and_name(part):
    assert default_registry.part(part.iso.group, part.name) is part


def test_the_registry_composes_only_where_iso_gives_the_result_a_number():
    """Three registered drawings are compositions, and all three are ISO group-8
    rows the standard tabulates with a registration number of its own: 8.3
    X8031, 8.6 X8125 and 8.8 X8126, each the shared separating vessel carrying
    one group-29 characteristic.

    Everything else a unit composes -- an agitator in a reactor, decks in a
    column, supports under a vessel -- is built per unit from that unit's
    keywords and never reaches the registry, because the combinations are the
    point of it. ``tests/test_composition.py`` holds the same line from the
    other side.
    """
    composed = {f"{kind}/{variant}": sym.iso_reg
                for (kind, variant), sym in default_registry._symbols.items()
                if sym.overlays}
    assert composed == {"separator/gravity": "X8031",
                        "separator/electrostatic": "X8125",
                        "separator/electromagnetic": "X8126"}


# --- how they are drawn -------------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_drawn_at_the_detail_weight(part):
    """ISO 10628-1:2014 §5.3.1 splits the line weights by what is being drawn:
    b) equipment and machinery symbols at 0,5 mm, c) the in-line detail band at
    0,25 mm. A tray deck and an impeller are detail *inside* an outline, so
    they belong in the finer band and at half the outline's weight.

    27.7's fluidised bed is the one part with no stroked ink at all -- Table 2
    draws it as a field of filled dots -- so the set of weights it uses is
    allowed to be empty, and is not allowed to be anything else.
    """
    widths = {float(w) for w in re.findall(r'stroke-width="([\d.]+)"', part.svg)}
    assert widths in ({iso_parts.PART_STROKE}, set())
    assert iso_parts.PART_STROKE * 2 == _SYMBOL_STROKE


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_parts_ink_stays_inside_the_box_it_declares(part):
    """A part is mapped from its own box onto a rectangle of the body's, so ink
    outside the box lands outside the rectangle the caller asked for."""
    segments = _collect_segments(part.svg)
    assert segments, "a part that draws nothing is not a drawing"
    xs = [x for seg in segments for x, _ in seg]
    ys = [y for seg in segments for _, y in seg]
    slack = iso_parts.PART_STROKE  # half a stroke each side of an edge line
    assert -slack <= min(xs) and max(xs) <= part.width + slack
    assert -slack <= min(ys) and max(ys) <= part.height + slack


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_parts_box_is_a_whole_number_of_grid_modules(part):
    """ISO 14617-1 §4.3 and ISO 10628-2 clause 5 both lay the artwork out on a
    2,5 mm grid, and Table 2's symbols land on it."""
    assert part.width % iso_parts.M == 0
    assert part.height % iso_parts.M == 0


def test_no_agitator_shaft_is_dashed():
    """Table 2's agitator shafts are solid. See the module docstring."""
    for part in PARTS:
        if part.iso.group == 28:
            assert "dasharray" not in part.svg, f"{part.iso.reg} {part.name}"


def test_only_the_two_iso_dash_pitches_are_used():
    """The sieve tray's deck (27.5) and the filter insert's (27.6) are told
    apart by nothing but their pitch, so the two are stated once and shared
    rather than typed out per part."""
    used = set(re.findall(r'stroke-dasharray="([\d.,]+)"', "".join(p.svg for p in PARTS)))
    assert used == {"20,10", "20,10,10,10"}


# --- what a part contributes --------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_only_an_agitator_brings_a_connection(part):
    """ISO item 1.27 (X8006) runs the stirrer's shaft up through the top head
    to a motor drawn above the vessel, so an agitator's drive is a real
    connection at a real place. A tray and a settling arrow are marks inside a
    body that no line ever reaches."""
    if part.iso.group == 28:
        assert set(part.ports) == {"drive"}
        assert part.ports["drive"] == (part.width / 2, 0.0)
    else:
        assert part.ports == {}


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_every_part_stretches_with_the_body_it_is_drawn_in(part):
    """``stretchable=False`` does not mean "draw this carefully".

    It means letterbox the *whole composed symbol* and centre it in the box the
    author asked for, since there is no way to hold one group still inside a
    group that is being stretched -- and a body centred in its box has its own
    nozzles floating in the whitespace beside it, which is issue #225. Holding
    a vessel rigid to protect a four-module impeller trades a nozzle that lands
    on ink for a blade that keeps its proportions, and that is the wrong way
    round. What keeps a part legible is the rectangle it is handed, which
    ``iso_parts``'s placement helpers make about the part's own aspect.
    """
    assert part.stretchable


def test_the_settling_arrow_fixes_the_body_it_is_drawn_in():
    """Item 29.1 is the statement that gravity does the work, which is the case
    ISO 14617-1 §4.5's prohibition on *turning* exists for.

    It is deliberately not ``directional``, which in this renderer means "hold
    the artwork still under a flip and move only the nozzles" and is sound only
    where the rest of the drawing is symmetric. The arrow's body is a hopper:
    held still under a vertical flip, its feed nozzle lands in the air beside
    the cone.
    """
    arrow = default_registry.part(29, "gravity")
    assert arrow.gravity_fixed and not arrow.directional


# --- composed onto a body -----------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_inside_the_body_leaves_the_body_its_own_box(part):
    """The common case, and the one that costs nothing: a part drawn within the
    body's outline adds no wrapper and moves no nozzle."""
    host = body()
    overlay = Overlay(part.iso.group, part.name, 0.2, 0.2, 0.5, 0.4)
    out = compose(host, [(overlay, part)])
    assert (out.width, out.height) == (host.width, host.height)
    assert out.ports["inlet"] == host.ports["inlet"]
    assert out.overlays == (overlay,)


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_drawn_at_its_declared_weight_however_it_is_scaled(part):
    """ISO 14617-1 §4.3, a ``shall``: when the size of a symbol is changed the
    line width shall be unchanged. A deck squeezed into a twentieth of a
    column's height must not come out at a twentieth of the weight.

    Checked as *drawn* rather than as declared: ``compose`` divides the width
    it writes into the attribute by the scale it is about to apply, so the
    attribute is deliberately not the answer -- the attribute times the scale
    is, and 0,354 under a 2,83x scale is the same 1 unit on the paper.
    """
    if part.iso.group == 27 and part is not default_registry.part(27, "packing"):
        rect = (0.1, 0.1, 0.8, 0.05)  # a deck: wide and shallow
    else:
        rect = (0.3, 0.1, 0.3, 0.6)
    host = body(width=400.0, height=1000.0)
    out = compose(host, [(Overlay(part.iso.group, part.name, *rect), part)])
    scales = [
        tuple(float(n) for n in pair.split(","))
        for pair in re.findall(r"scale\(([-\d.,]+)\)", out.svg)
    ]
    assert len(scales) == 1, "one wrapper for the one part placed"
    sx, sy = scales[0]
    drawn = {
        float(w) * math.sqrt(sx * sy)
        for w in re.findall(r'stroke-width="([\d.]+)"', out.svg[out.svg.index("scale(") :])
    }
    assert all(w == pytest.approx(iso_parts.PART_STROKE, rel=1e-4) for w in drawn)
    # ...and the body's own outline is untouched by any of it.
    assert f'stroke-width="{_SYMBOL_STROKE:g}"' in out.svg


def test_an_agitators_drive_lands_on_the_body_and_the_bodys_nozzles_survive():
    """The rectangle is the agitator's own 1:2 aspect, which is what a caller
    has to give an unstretchable part: ``compose`` letterboxes one that is not
    stretchable, so a taller rectangle would centre the shaft in it and leave
    the drive floating below the head it is meant to come through."""
    host = body()
    # 0,4 x 80 = 32 wide and 0,32 x 200 = 64 tall, which is the part's own
    # 4 M x 8 M at 0,8 and so has nothing left over to centre.
    out = compose(
        host, [(Overlay(28, "turbine", 0.3, 0.05, 0.4, 0.32), default_registry.part(28, "turbine"))]
    )
    assert set(out.ports) == {"inlet", "outlet", "drive"}
    # 0.3 of 80 wide, plus half of the 0.4-wide rectangle: the shaft's top,
    # on the centre line the caller placed it on, at the rectangle's own top.
    assert out.ports["drive"] == (pytest.approx(40.0), pytest.approx(10.0))


def test_a_composed_body_stretches_exactly_as_the_bare_one_does():
    """Which is what lets a unit be given a ``width``/``height`` and still have
    its nozzles land on ink. Composing changes what is drawn inside the box and
    nothing about the box."""
    host = body()
    out = compose(
        host,
        [(Overlay(28, "propeller", 0.3, 0.05, 0.4, 0.8), default_registry.part(28, "propeller"))],
    )
    assert host.stretchable and out.stretchable


def test_a_column_of_trays_is_n_overlays_and_not_a_count():
    """Repetition is placement: thirty decks are thirty overlays with thirty
    values of ``y``, which is what lets item 2.5's staggered baffle trays
    alternate which wall each deck touches by varying ``x`` as well."""
    deck = default_registry.part(27, "baffle_tray")
    overlays = [
        Overlay(27, "baffle_tray", 0.1 if i % 2 else 0.2, 0.1 + 0.05 * i, 0.7, 0.04)
        for i in range(12)
    ]
    out = compose(body(), [(o, deck) for o in overlays])
    assert len(out.overlays) == 12
    assert out.svg.count('id="part_27_baffle_tray"') == 0  # the wrapper is dropped
