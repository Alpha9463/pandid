"""The ISO 10628-2 part artwork, held to the table it claims to be.

Groups 26-29, and item 20.6 the motor -- which is not a part at all, and is
drawn here because item 1.27 X8006 draws it above a stirred vessel and
registers the composition. ``symbols.COMPOSED_APPARATUS`` is the admission.

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
    # Not a part, and here on the standard's own authority rather than on the
    # rule the other thirty-six are here on: group 20 is DRIVES, and item 1.27
    # X8006 draws this one above a stirred vessel. See
    # ``symbols.COMPOSED_APPARATUS``.
    (20, "motor"): ("20.6", "C0082", "Electric motor (general)"),
    (29, "gravity"): ("29.1", "C2028", "Gravity type, settling type"),
    (29, "electrostatic"): ("29.2", "C2030", "Electrostatic type"),
    (29, "electromagnetic"): ("29.3", "C2031", "Electromagnetic type"),
    (29, "disc"): ("29.4", "C2033", "Disc type"),
    (29, "crushing"): ("29.5", "C0240", "Crushing"),
    # Three digits, not four. Table 2 prints it that way and this table
    # is quoted from Table 2, so "correcting" it here to C0240's shape
    # would be the failing test rather than the fix.
    (29, "gear"): ("29.6", "C024", "Gear type, gearwheels type"),
    (29, "hammer"): ("29.7", "C2034", "Hammer type"),
    (29, "impact"): ("29.8", "C2035", "Impact type"),
    (29, "jaw"): ("29.9", "C2036", "Jaw type"),
    (29, "liquid"): ("29.10", "321", "Liquid type, wet type"),
    (29, "roller"): ("29.11", "C2037", "Roller type"),
    (29, "cone"): ("29.12", "C2038", "Cone type"),
    (29, "jet"): ("29.13", "X8176", "Jet type"),
    (29, "vibration"): ("29.14", "3831", "Vibration type"),
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
    """26's four supports, 27's eight internals, 28's ten agitators, and all
    fourteen group-29 characteristics.

    Group 26's manhole and socket are deliberately absent, not overlooked: both
    are drawn *on the vessel wall*, and where a wall is depends on the body.

    Three of the fourteen are the ones ISO composes onto its own group-8
    separating vessel and gives a registration number to (8.3, 8.6, 8.8), and
    those three are still all that ``Separator(characteristic=)`` names -- see
    :func:`test_the_marks_beyond_the_composed_three_are_artwork_only`. Two
    group-29 *absences* still carry an argument: the group has no vortex, which
    is why ISO 8.10 X2618 is a symbol of its own, and no spray, which is why
    8.7 X8033 cannot be composed either.
    """
    counts = {g: len(default_registry.part_names(g)) for g in (20, 26, 27, 28, 29)}
    assert counts == {20: 1, 26: 4, 27: 8, 28: 10, 29: 14}
    # One of group 20's eight, and the only one ISO draws inside another
    # apparatus. The other seven -- turbine, gear, generator -- are machines
    # that carry a tag of their own, and pandid draws those as whole symbols.
    assert default_registry.part_names(20) == ["motor"]


def test_a_mark_is_a_separator_keyword_only_where_iso_composes_a_separator():
    """``Separator(characteristic=)`` names the three rows ISO itself composes
    and numbers in group 8, and artwork alone does not add a fourth: a mark is a
    keyword only once someone can point at the Table 1 row the composition *is*.

    Six of the eleven crushing marks now have such a row, and it is in **group
    11** -- ``crusher/jaw`` is item 11.5 X8047, ``mill/vibration`` is 11.12
    X8054, and so on. That is what put them in the registry, and it is a claim
    about a crusher body rather than about a separating vessel: a settling
    chamber with a pair of gearwheels in it is not a symbol ISO has.

    ``crushing``, ``jet``, ``liquid``, ``disc`` and ``gear`` are the five with
    no composed row anywhere yet -- 11.1 X8084 is not drawn (see
    ``SymbolRegistry._register_crushing_machines``) and 29.10, 29.13, 29.4 and
    29.6 are marks Table 2 uses only in rows pandid has no body for.
    """
    from pandid.units import Separator

    assert Separator._CHARACTERISTICS == ("gravity", "electrostatic", "electromagnetic")
    for name in ("crushing", "hammer", "jet"):
        assert default_registry.part(29, name)
        with pytest.raises(ValueError):
            Separator("V-901", characteristic=name)


def test_every_group_11_row_composes_the_mark_table_2_draws_in_it():
    """The nine composed group-11 drawings, each against the part it carries.

    Read off rows 11.3 to 11.12: the mark is the same glyph its own group-29 row
    draws, at the same size, centred on the body's box. So this checks the pair
    -- which characteristic, on which body -- rather than the geometry, which
    ``crushing_overlays`` derives and the row below pins.
    """
    carried = {}
    for (kind, variant), sym in default_registry._symbols.items():
        if kind in ("crusher", "mill") and sym.overlays:
            assert len(sym.overlays) == 1, f"{kind}/{variant} carries more than one mark"
            carried[f"{kind}/{variant}"] = (sym.overlays[0].group, sym.overlays[0].name)
    assert carried == {
        "crusher/hammer": (29, "hammer"),  # 11.3  X8045 + 29.7  C2034
        "crusher/impact": (29, "impact"),  # 11.4  X8046 + 29.8  C2035
        "crusher/jaw": (29, "jaw"),  # 11.5  X8047 + 29.9  C2036
        "crusher/roller": (29, "roller"),  # 11.6  X8048 + 29.11 C2037
        "crusher/cone": (29, "cone"),  # 11.7  X8049 + 29.12 C2038
        "mill/hammer": (29, "hammer"),  # 11.9  X8050 + 29.7  C2034
        "mill/impact": (29, "impact"),  # 11.10 X8051 + 29.8  C2035
        "mill/roller": (29, "roller"),  # 11.11 X8053 + 29.11 C2037
        "mill/vibration": (29, "vibration"),  # 11.12 X8054 + 29.14 3831
    }


@pytest.mark.parametrize(
    "name, modules",
    [
        ("crushing", (4, 4)),
        ("hammer", (3, 3)),
        ("impact", (4, 4)),
        ("jaw", (5, 2)),
        ("roller", (4, 2)),
        ("cone", (4, 3)),
    ],
)
def test_a_crushing_mark_lands_on_the_modules_table_2_draws_it_in(name, modules):
    """Measured off rows 11.1 and 11.3 to 11.11, against a body box of x 7..17
    and y 4..10 -- ten modules by six.

    Every one of them is **centred**, and its size is its own group-29 row's, so
    the rectangle ``crushing_overlays`` hands ``compose`` is fully determined by
    the part's declared box. This is that arithmetic held to the modules
    counted on the page: a mark that grew a module would still centre, and
    would be the wrong size for the row it claims to be.
    """
    from pandid.render.iso_parts import CRUSHER_MODULES_H, CRUSHER_MODULES_W, crushing_overlays

    w, h = modules
    (overlay,) = crushing_overlays(name)
    assert (overlay.w * CRUSHER_MODULES_W, overlay.h * CRUSHER_MODULES_H) == (w, h)
    assert overlay.x == pytest.approx((CRUSHER_MODULES_W - w) / 2 / CRUSHER_MODULES_W)
    assert overlay.y == pytest.approx((CRUSHER_MODULES_H - h) / 2 / CRUSHER_MODULES_H)


def test_the_vibration_mark_is_squeezed_the_way_the_mill_row_squeezes_it():
    """Item 29.14's own row draws the two arrows 3 M across; item 11.12 draws
    them 2 M across, inside the drum. Both are the same part, and the row being
    reproduced is 11.12's -- so ``mill/vibration`` is the one composition whose
    mark is not at its own row's width, and it is deliberate.
    """
    from pandid.render.iso_parts import M, CRUSHER_MODULES_W, crushing_overlays

    assert default_registry.part(29, "vibration").width == 3 * M
    (overlay,) = crushing_overlays("vibration")
    assert overlay.w * CRUSHER_MODULES_W == 2


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_asked_for_by_group_and_name(part):
    assert default_registry.part(part.iso.group, part.name) is part


def test_every_part_that_draw_io_has_a_shape_for_names_it():
    """Ten of the thirty-seven, and they are draw.io's whole agitator set.

    ``mxgraph.pid.agitators`` has exactly ten shapes and they are ISO group
    28's ten, item for item -- so a composed reactor exports with a real
    agitator on it rather than a stand-in. Nothing else in groups 26, 27 or 29
    has a shape of its own in the P&ID set, and inventing a key for one would
    fail silently: draw.io answers an unresolvable ``shape=`` with a plain
    rectangle. ``tests/test_drawio.py`` holds these ten keys against the
    stencil XML they are meant to name.
    """
    stencilled = {p.name for p in iso_parts.parts() if p.drawio_shape}
    assert stencilled == {p.name for p in iso_parts.parts() if p.iso.group == 28}
    for part in iso_parts.parts():
        if part.drawio_shape:
            assert part.drawio_shape.startswith("mxgraph.pid.agitators.")


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
def test_only_the_motor_brings_a_connection(part):
    """``drive`` is where the power arrives, and on ISO item 1.27 (X8006) that
    is the motor: the shaft under it is welded to it, not connected to it. A
    tray, a settling arrow and a stirrer are marks inside or under a body that
    no line ever reaches.

    The ten agitators anchored this until the motor was drawn, which was right
    while the top of the shaft was the top of the drawing. It is not any more --
    the crown is mid-shaft -- and a nozzle left there would be nearest a *side*
    of the grown box and would take its stream out through the shell.
    """
    if part.iso.group == 20:
        assert set(part.ports) == {"drive"}
        assert part.ports["drive"] == (part.width / 2, 0.0)
    else:
        assert part.ports == {}


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_every_part_fills_the_rectangle_it_is_given(part):
    """``stretchable=False`` is not "draw this part carefully".

    It letterboxes the part on its rectangle **and** makes the whole composed
    symbol unstretchable, and both of those are decisions about the body. The
    first lifted a stirred tank's ``drive`` eight units off the head it comes
    through, because a rectangle stated in fractions of the body's box has the
    body's aspect and the width was the binding scale; the second would have
    centred a reactor in the box its author asked for while every stencilled
    neighbour filled one.

    draw.io settles it from outside: its own ten agitator stencils, drawing
    these same ten items, are every one of them ``aspect="variable"``, and this
    module names those stencils -- so a part that refused to stretch would have
    the two backends sizing one drawing by two rules.
    """
    assert part.stretchable


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_no_part_holds_its_own_artwork_still_under_a_flip(part):
    """``directional`` is a rendering instruction, not a claim about the mark.

    It says *hold the artwork still and move only the nozzles*, which is sound
    only where the artwork under the moved nozzle is the same as the artwork
    under the original -- a circle with everything laid through its centre. A
    part cannot promise that on a body's behalf: a settling arrow's body is a
    hopper, and held still under a vertical flip its feed nozzle lands twenty
    units below the cone in mid-air, which is what
    ``tests/test_symbol_invariants`` measured.
    """
    assert not part.directional


def test_the_settling_arrow_fixes_the_body_it_is_drawn_in():
    """Item 29.1 is the statement that gravity does the work, which is the case
    ISO 14617-1 §4.5's prohibition on turning exists for -- and a prohibition
    is the right shape of thing for it, where ``directional`` is not."""
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


def test_a_motors_drive_lands_on_the_body_and_the_bodys_nozzles_survive():
    """A part *adds* a connection to the body's rather than replacing one, and
    the added one lands where the part's own coordinate says it does."""
    host = body()
    out = compose(
        host, [(Overlay(20, "motor", 0.3, -0.2, 0.4, 0.16), default_registry.part(20, "motor"))]
    )
    assert set(out.ports) == {"inlet", "outlet", "drive"}
    # The motor is drawn entirely above the body -- its rectangle runs from
    # -0,2 to -0,04 of a 200-tall box -- so the box grows by the 40 units its
    # top edge hangs off the top and everything shifts down into it.
    assert (out.width, out.height) == (80.0, 240.0)
    # The drive is at the top of the motor, so it lands on the composed
    # drawing's own top edge, on the centre line of the rectangle it was given.
    assert out.ports["drive"] == (pytest.approx(40.0), pytest.approx(0.0))
    assert out.ports["inlet"] == (0.0, host.ports["inlet"][1] + 40.0)


def test_a_stirred_vessel_is_drawn_with_the_motor_that_turns_it():
    """ISO item 1.27 X8006 is one row and three marks: the vessel, a group-28
    stirrer, and item 20.6's motor above the top head on the stirrer's own
    shaft. So ``agitator=`` places two parts, and there is no keyword for the
    second -- group 1 has 29 rows, exactly one carries an agitator, and it
    carries the motor too.

    The numbers are 1.27's, read against its 6 M x 9 M body box: the motor is
    2 M across a 6 M shell and sits 1 M clear of a 9 M body's crown, with the
    shaft one continuous stroke from its underside down to the blade.
    """
    stirrer, motor = iso_parts.agitator_overlays("turbine", "reactor", "default")
    assert (stirrer.group, stirrer.name) == (28, "turbine")
    assert (motor.group, motor.name) == (20, "motor")
    reactor = default_registry.get("reactor", "default")
    # A third of the shell's width, centred on it...
    assert motor.w == pytest.approx(1 / 3)
    assert motor.x + motor.w / 2 == pytest.approx(0.5)
    # ...and round, which is the one thing a fraction of a box cannot say by
    # itself: the height is derived from the body it is being placed on.
    assert motor.h * reactor.height == pytest.approx(motor.w * reactor.width)
    # A ninth of the body's height of clear air between the two, with the
    # stirrer's rectangle reaching up to meet the circle exactly.
    assert motor.y + motor.h == pytest.approx(-1 / 9)
    assert stirrer.y == pytest.approx(-1 / 9)
    # The blade did not move: only the top edge went negative.
    assert stirrer.y + stirrer.h == pytest.approx(0.76)


def test_a_composed_body_stretches_exactly_as_the_bare_one_does():
    """The other half of :func:`test_every_part_fills_the_rectangle_it_is_given`.

    A stirred tank given a width and a height fills that box, as its neighbours
    drawn from whole stencils do. It used not to: one unstretchable part made
    the whole composition unstretchable, since there is no way to hold one
    group still inside a group that is being stretched.
    """
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
