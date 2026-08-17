"""Composing a symbol from a body and ISO 10628-2 group 26-29 parts.

ISO 10628-2 clause 5 makes composition a ``shall`` for any symbol the standard
does not tabulate, and clause 5's own Table 2 demonstrates it: item 8.6
(X8125, the electrostatic precipitator) is the group-8 body carrying item 29.2
(C2030), and item 8.7 (X8033) is that same body carrying two parts at once.
:mod:`pandid.render.symbols` gained the mechanism for it; this is the suite that
holds the mechanism to what the standard actually licenses.

Two things this file is careful about.

**The mechanism is tested on parts built here, not on the shipped artwork.**
That is deliberate rather than a gap: a suite that leaned on shipped parts
would go quiet the day one was renamed, and this file's subject is the rule and
the arithmetic. ``tests/test_iso_parts.py`` is where the thirty-six drawings
are held to Table 2 row by row, and ``tests/test_drawio.py`` is where the two
backends are held to each other.

**What the registry itself composes is spelled out, not counted.** A
composition the registry ships is a composition *ISO tabulates with a
registration number of its own* -- three of them, all in group 8 -- while the
ones an author configures with ``agitator=`` or ``trays=`` are built per unit
and cannot be enumerated, because the combinations are the point.
:func:`test_the_registry_composes_exactly_the_three_ISO_gives_a_number_to` lists
the three by name so that a fourth has to be argued for here.
"""

import re
import subprocess
import sys

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import SvgRenderer
from pandid.render.symbols import (
    COMPOSED_APPARATUS,
    PART_GROUPS,
    IsoPart,
    Overlay,
    OverlayPart,
    Symbol,
    SymbolRegistry,
    compose,
    default_registry,
)

# The four Table 2 rows the parts below claim to be, quoted by number so a
# reader with the standard can check each one against its row. All four are
# genuine group 26-29 entries; the point of naming real ones in a test that
# draws nothing real is that :class:`IsoPart` refuses an invented number, and a
# suite exercising the refusal with invented numbers everywhere else would never
# notice it had stopped accepting the real ones.
TRAY = IsoPart(27, "27.1", "C2044", "Tray (general)")
PACKING = IsoPart(27, "27.8", "X8141", "Packing")
TURBINE = IsoPart(28, "28.10", "C2027", "Agitator, turbine type")
SETTLING = IsoPart(29, "29.1", "C2028", "Gravity type, settling type")

#: pandid's spelling for each, which is what an author types and half the
#: registry key. Short where the standard's descriptor is a sentence.
NAMES = {TRAY: "tray", PACKING: "packing", TURBINE: "turbine", SETTLING: "gravity"}


def part(iso, **kwargs):
    """A part with placeholder artwork, for exercising the mechanism.

    A horizontal rule in a 40 x 10 box unless a test says otherwise: the
    simplest thing with a length, a weight and a position, so a test can read
    all three back out of the composed SVG.
    """
    kwargs.setdefault("name", NAMES[iso])
    kwargs.setdefault(
        "svg",
        '<g id="part"><line x1="0" y1="5" x2="40" y2="5" stroke="black" stroke-width="1.5"/></g>',
    )
    kwargs.setdefault("width", 40.0)
    kwargs.setdefault("height", 10.0)
    return OverlayPart(iso=iso, **kwargs)


def body(**kwargs):
    """A plain 100 x 200 body with one nozzle per face."""
    kwargs.setdefault(
        "svg",
        '<g id="sym_test_body"><rect x="0" y="0" width="100" height="200" '
        'fill="none" stroke="black" stroke-width="2"/></g>',
    )
    kwargs.setdefault("width", 100.0)
    kwargs.setdefault("height", 200.0)
    kwargs.setdefault(
        "ports", {"feed": (0.0, 40.0), "bottoms": (50.0, 200.0), "vapour": (50.0, 0.0)}
    )
    return Symbol(**kwargs)


def transforms(svg):
    """Every ``transform`` in a composed drawing, outermost first."""
    return re.findall(r'transform="([^"]+)"', svg)


# ---------------------------------------------------------------- the rule


def test_a_part_must_name_a_group_that_composes():
    """Groups 1-25 are whole apparatus, and one is not overlaid on another.

    The rule the whole mechanism turns on, made refusable: a body carrying a
    body is two pieces of equipment on one tag, not a composition.
    """
    with pytest.raises(ValueError, match="not one of the part groups"):
        IsoPart(8, "8.10", "X2618", "Separator, cyclone type")


def test_the_part_groups_are_the_four_iso_names_them():
    assert sorted(PART_GROUPS) == [26, 27, 28, 29]


def test_the_one_apparatus_iso_composes_itself_is_admitted_by_item():
    """ "Compose only where ISO itself composes" and "compose only groups 26-29"
    are not the same test, and they part company exactly once.

    Item 1.27 X8006 draws the general electric motor -- item 20.6, and group 20
    is DRIVES, whole machines -- above a stirred vessel on the stirrer's own
    shaft, and registers the composition. So the motor is composed on the
    standard's own authority, the way the three group-29 separators are.

    The admission is a list of **items**, which is what keeps it from becoming a
    licence for the group it comes from: 20.1's turbine and 20.7's generator are
    machines that carry a tag of their own, and they are refused here beside the
    cyclone.
    """
    assert IsoPart(20, "20.6", "C0082", "Electric motor (general)").group == 20
    assert set(COMPOSED_APPARATUS) == {"20.6"}
    for group, item, reg, name in (
        (20, "20.1", "C0080", "Turbine (general)"),
        (20, "20.7", "C0083", "Generator (general)"),
        (8, "8.10", "X2618", "Separator, cyclone type"),
    ):
        with pytest.raises(ValueError, match="not one of the part groups"):
            IsoPart(group, item, reg, name)


@pytest.mark.parametrize("reg", ["2062", "301", "C2044", "X2618", "X8141"])
def test_every_namespace_clause_5_declares_is_accepted(reg):
    """``nnn``, ``nnnn``, ``Cnnnn``, ``X2nnn`` and ``X8nnn``."""
    assert IsoPart(27, "27.1", reg, "a part").reg == reg


@pytest.mark.parametrize("reg", ["", "vortex", "27.1", "X1234", "CC2044", "X20000"])
def test_a_mark_with_no_registration_number_cannot_become_a_part(reg):
    """The check that keeps a composition from being invented.

    A cyclone's vortex is the case this exists for. It is a mark inside the
    separator body, it looks composable, and there is no group-29 item that
    draws one -- so there is no number to write here, and X2618 stays a
    distinct symbol instead of becoming "body plus cyclone characteristic".
    """
    with pytest.raises(ValueError, match="not a registration number"):
        IsoPart(29, "29.1", reg, "a mark")


def test_an_item_number_has_to_be_in_the_group_it_claims():
    with pytest.raises(ValueError, match="not in group 27"):
        IsoPart(27, "29.1", "C2028", "Gravity type, settling type")


def test_a_part_has_to_say_what_the_standard_calls_it():
    with pytest.raises(ValueError, match="the standard's own descriptor"):
        IsoPart(27, "27.1", "C2044", "   ")


# ---------------------------------------------------------------- placement


def test_a_part_lands_on_the_fraction_of_the_body_it_names():
    """Placement is stated in fractions, so it is resolved against the box."""
    sym = compose(body(), [(Overlay(27, "tray", 0.15, 0.30, 0.70, 0.05), part(TRAY))])
    # 0.15 x 100 across, 0.30 x 200 down, and 70 units over the part's own 40
    # wide by 10 units over its own 10 tall.
    assert transforms(sym.svg) == ["translate(15,60) scale(1.75,1)"]


def test_the_placement_is_proportional_so_a_stretched_body_carries_its_parts():
    """The point of fractions rather than drawing units.

    A tray three-tenths down the shell is three-tenths down it at every size,
    because the composed artwork is written in the body's own coordinates and
    whatever scales the body scales the part with it. Read back off two bodies
    of different heights: the same fractions give the same *relative* position.
    """
    tall = compose(
        body(height=400.0, ports={"feed": (0.0, 80.0)}),
        [(Overlay(27, "tray", 0.15, 0.30, 0.70, 0.05), part(TRAY))],
    )
    short = compose(body(), [(Overlay(27, "tray", 0.15, 0.30, 0.70, 0.05), part(TRAY))])
    assert re.search(r"translate\(15,(\d+)\)", tall.svg).group(1) == "120"
    assert re.search(r"translate\(15,(\d+)\)", short.svg).group(1) == "60"


def test_a_scaled_part_keeps_the_line_weight_its_author_drew_it_at():
    """ISO 14617-1 §4.3, a ``shall``: the line width does not scale.

    The part is drawn at 1.5 in a 40 x 10 box and placed on a rectangle a
    quarter that size, so the transform would otherwise draw it at 0.375 -- a
    tray deck rendered as a hairline while the shell around it stays at 2.
    """
    sym = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.1, 0.0125), part(TRAY))])
    placed = sym.svg[sym.svg.index('<g transform="translate(10,100)') :]
    scale = re.search(r"scale\(([\d.]+),([\d.]+)\)", placed)
    factor = (float(scale.group(1)) * float(scale.group(2))) ** 0.5
    drawn = float(re.search(r'stroke-width="([\d.]+)"', placed).group(1))
    assert drawn * factor == pytest.approx(1.5, rel=1e-4)


def test_a_part_whose_shape_carries_meaning_is_not_distorted():
    """``stretchable=False``, and the letterbox that answers it.

    An impeller is a shape. Placed on a rectangle of another aspect it takes
    the smaller scale on both axes and is centred on what it was given, which
    is exactly what :func:`pandid.portgeom.ink_box` does for a whole symbol.
    """
    sym = compose(
        body(),
        [(Overlay(28, "turbine", 0.0, 0.0, 1.0, 0.1), part(TURBINE, stretchable=False))],
    )
    # 100 x 20 offered to a 40 x 10 part: 2.5 across but only 2.0 down, so the
    # even scale is 2.0 and the 80 the part then occupies is centred in the 100.
    assert transforms(sym.svg) == ["translate(10,0) scale(2,2)"]

    tighter = compose(
        body(),
        [(Overlay(28, "turbine", 0.0, 0.0, 1.0, 0.05), part(TURBINE, stretchable=False))],
    )
    # 100 x 10: the height binds at 1.0, so the part stays 40 wide and is
    # centred in the 100 it was offered.
    assert transforms(tighter.svg) == ["translate(30,0) scale(1,1)"]


def test_a_part_that_may_not_be_reshaped_holds_the_whole_symbol_to_its_aspect():
    """There is no way to hold one group still inside a group being stretched.

    So a composition is stretchable only if the body and every part is, and the
    renderer letterboxes the lot. ISO 14617-1 §4.4 bounds reshaping at the point
    where the symbol stops being recognisable, which an impeller drawn as a
    smear plainly is.
    """
    assert body().stretchable
    loose = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert loose.stretchable
    fixed = compose(
        body(),
        [(Overlay(28, "turbine", 0.1, 0.5, 0.8, 0.2), part(TURBINE, stretchable=False))],
    )
    assert not fixed.stretchable


def test_a_part_can_make_the_body_gravity_fixed_and_directional():
    """Item 29.1's settling arrow says the heavy phase goes *down*.

    Turning the body it is drawn in is ISO 14617-1 §4.5's prohibition, and
    flipping it draws the opposite claim -- both true of the composition even
    where the bare body was free of either.
    """
    plain = body()
    assert not plain.gravity_fixed and not plain.directional
    sym = compose(
        plain,
        [
            (
                Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.3),
                part(SETTLING, gravity_fixed=True, directional=True),
            )
        ],
    )
    assert sym.gravity_fixed and sym.directional


def test_two_parts_land_on_one_body_in_the_order_they_are_given():
    """ISO item 8.7 (X8033) is one body carrying two parts, so this is not a
    theoretical case: the wet electrostatic precipitator is the group-8 body
    with item 8.5's spray mark and item 29.2's electrostatic mark together."""
    sym = compose(
        body(),
        [
            (Overlay(27, "tray", 0.1, 0.2, 0.8, 0.05), part(TRAY)),
            (Overlay(27, "packing", 0.1, 0.6, 0.8, 0.05), part(PACKING)),
        ],
    )
    assert [t.split(")")[0] for t in transforms(sym.svg)] == [
        "translate(10,40",
        "translate(10,120",
    ]
    assert [o.name for o in sym.overlays] == ["tray", "packing"]


# ---------------------------------------------------------------- the box


def test_a_part_inside_the_body_leaves_the_box_exactly_as_it_was():
    """The common case, and it costs nothing: no wrapper, no shift."""
    sym = compose(body(), [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert (sym.width, sym.height) == (100.0, 200.0)
    assert sym.ports["feed"] == (0.0, 40.0)
    assert transforms(sym.svg) == ["translate(10,100) scale(2,1)"]


def test_a_part_drawn_outside_the_body_grows_the_box_and_moves_the_body_into_it():
    """ISO item 1.27 (X8006) hangs the drive motor above the top head.

    The vessel is then no longer the whole drawing, so the box has to hold both
    and the body's nozzles move down with the body.
    """
    sym = compose(
        body(ports={"bottoms": (50.0, 200.0)}),
        [(Overlay(28, "turbine", 0.3, -0.1, 0.4, 0.1), part(TURBINE))],
    )
    assert (sym.width, sym.height) == (100.0, 220.0)
    assert sym.ports["bottoms"] == (50.0, 220.0)
    # The body wrapped in the shift, then the part at the top of the new box.
    assert transforms(sym.svg) == ["translate(0,20)", "translate(30,0) scale(1,2)"]


def test_growing_the_box_may_not_move_a_nozzle_onto_another_face():
    """A nozzle leaves by whichever face of its box it is nearest.

    A relief on the crown of a vessel, a quarter of the way across it, is
    nearest the top of the vessel's own box and nearest the *side* of a box
    grown to hold a motor above it -- at which point the stream drawn to it
    leaves through the shell wall. Refused, naming the part that moved it.
    """
    with pytest.raises(ValueError, match="grows the box"):
        compose(
            body(ports={"relief": (10.0, 0.0), "bottoms": (50.0, 200.0)}),
            [(Overlay(28, "turbine", 0.3, -0.5, 0.4, 0.5), part(TURBINE))],
        )


# ---------------------------------------------------------------- ports


def test_an_internal_and_a_characteristic_bring_no_connection():
    """Nothing is ever routed to a tray or to a settling arrow."""
    sym = compose(
        body(),
        [
            (Overlay(27, "tray", 0.1, 0.2, 0.8, 0.05), part(TRAY)),
            (Overlay(29, "gravity", 0.3, 0.5, 0.4, 0.2), part(SETTLING)),
        ],
    )
    assert sorted(sym.ports) == ["bottoms", "feed", "vapour"]


def test_an_agitator_brings_its_drive_connection():
    """ISO item 1.27 draws the shaft running up to a circle marked ``M``,
    itself item 20.6 (C0082, electric motor). The drive is a real connection at
    a real place on the drawing, so the part that draws it anchors one."""
    sym = compose(
        body(),
        [
            (
                Overlay(28, "turbine", 0.3, 0.1, 0.4, 0.1),
                part(TURBINE, ports={"drive": (20.0, 0.0)}),
            )
        ],
    )
    assert sorted(sym.ports) == ["bottoms", "drive", "feed", "vapour"]
    # 0.3 x 100 across plus 20 of the part's own scaled by 40 over 40.
    assert sym.ports["drive"] == (50.0, 20.0)


def test_a_part_may_not_take_over_a_nozzle_the_body_already_has():
    """Two nozzles under one name is a stream drawn to whichever survived."""
    with pytest.raises(ValueError, match="the body already has one"):
        compose(
            body(),
            [
                (
                    Overlay(28, "turbine", 0.3, 0.1, 0.4, 0.1),
                    part(TURBINE, ports={"feed": (20.0, 0.0)}),
                )
            ],
        )


def test_a_parts_nozzle_has_to_be_on_the_part():
    with pytest.raises(ValueError, match="outside the"):
        part(TURBINE, ports={"drive": (200.0, 0.0)})


def test_the_body_keeps_its_faceless_and_series_declarations():
    """A part adds artwork and connections; it does not restate the body."""
    from pandid.render.symbols import PortSeries

    plain = body(
        ports={"bottoms": (50.0, 200.0)},
        port_series=(PortSeries("feed_", "W", singular="feed"),),
        label_pos="center",
    )
    sym = compose(plain, [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert sym.port_series == plain.port_series
    assert sym.label_pos == "center"


# ---------------------------------------------------------------- registry


@pytest.fixture
def registry():
    """A registry of its own, with the four parts above in it and nothing else.

    The shipped ISO artwork is cleared out first, deliberately. These tests are
    about the *mechanism* -- what a key is, what a miss reports -- and the four
    placeholders above are the smallest thing that exercises it. Leaving the
    real thirty-six in would make "the registered group 27 parts" a list this
    file has to be kept in step with, for no gain: ``tests/test_iso_parts.py``
    is where the shipped set is held to Table 2.
    """
    reg = SymbolRegistry()
    reg._parts.clear()
    reg.register("composition_test", body())
    for iso in (TRAY, PACKING, TURBINE, SETTLING):
        reg.register_part(part(iso))
    return reg


def test_a_part_is_keyed_by_its_iso_group_and_its_name(registry):
    """A name is only unique inside its group."""
    assert registry.part(27, "tray").iso is TRAY
    assert registry.part_names(27) == ["packing", "tray"]
    assert registry.part_names(28) == ["turbine"]
    # Sorted by key: group, then name.
    assert [p.iso.reg for p in registry.parts()] == ["X8141", "C2044", "C2027", "C2028"]


def test_a_part_nobody_registered_is_refused_with_the_ones_that_are(registry):
    with pytest.raises(ValueError, match="did you mean 'tray'"):
        registry.part(27, "trey")
    with pytest.raises(ValueError, match=r"group 26 parts: \(none\)"):
        registry.part(26, "skirt")


def test_no_overlays_gives_the_body_back_unchanged(registry):
    """The zero case, and the one every shipped symbol is in."""
    assert registry.composed("composition_test") is registry.get("composition_test")


def test_a_composition_is_built_once_and_shared(registry):
    """Port resolution asks for a unit's symbol on every call."""
    overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    first = registry.composed("composition_test", "default", overlays)
    assert registry.composed("composition_test", "default", overlays) is first


def test_re_registering_a_body_or_a_part_drops_the_compositions_using_it(registry):
    overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    first = registry.composed("composition_test", "default", overlays)
    registry.register_part(part(TRAY))
    assert registry.composed("composition_test", "default", overlays) is not first
    second = registry.composed("composition_test", "default", overlays)
    registry.register("composition_test", body())
    assert registry.composed("composition_test", "default", overlays) is not second


def test_a_unit_that_names_no_parts_draws_what_it_always_drew(registry):
    """The wiring, and the reason no golden moved: ``for_unit`` reads the
    overlays off the unit, and no unit sets any."""

    class Body(units.Unit):
        kind = "composition_test"

    assert registry.for_unit(Body("X-1")) is registry.get("composition_test")


def test_a_unit_that_names_parts_is_drawn_with_them(registry):
    class Body(units.Unit):
        kind = "composition_test"

    unit = Body("X-1")
    unit.overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    assert registry.for_unit(unit).overlays == unit.overlays


# ---------------------------------------------------------------- identity


def test_a_composition_needs_a_definition_of_its_own(registry):
    """The ``<defs>`` entry a ``<use>`` points at is keyed by the artwork, so
    the bare body and the body with parts on are two drawings. The same reason
    :func:`~pandid.render.symbols.darkened` carries an ``_nc`` suffix."""
    bare = registry.get("composition_test")
    one = registry.composed(
        "composition_test", "default", (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
    )
    two = registry.composed(
        "composition_test", "default", (Overlay(27, "tray", 0.1, 0.6, 0.8, 0.05),)
    )
    assert one.id_suffix != bare.id_suffix
    assert one.id_suffix != two.id_suffix
    assert re.fullmatch(r"_c[0-9a-f]{8}", one.id_suffix)


def test_the_definition_id_does_not_depend_on_the_process_hash_seed():
    """It lands in the emitted SVG, and ``tests/golden`` compares byte for byte.

    Python's own ``hash()`` is seeded per process, so an id built from one would
    make a sheet render differently from run to run. Two interpreters, two
    seeds, one answer.
    """
    script = (
        "from pandid.render.symbols import *\n"
        "p = OverlayPart(name='tray', iso=IsoPart(27, '27.1', 'C2044', 'Tray'),"
        ' svg=\'<g id="p"><line x1="0" y1="5" x2="40" y2="5"'
        ' stroke="black" stroke-width="1.5"/></g>\', width=40.0, height=10.0)\n'
        'b = Symbol(svg=\'<g id="b"><rect x="0" y="0" width="100"'
        ' height="200" fill="none" stroke="black" stroke-width="2"/></g>\','
        " width=100.0, height=200.0)\n"
        "print(compose(b, [(Overlay(27, 'tray', 0.1, 0.5, 0.8, 0.05), p)]).id_suffix)\n"
    )
    seen = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        ).stdout.strip()
        for seed in ("0", "12345")
    }
    assert len(seen) == 1


def test_a_composition_is_not_the_symbol_it_was_composed_onto(registry):
    """Carrying the body's registration number forward would claim a stirred
    tank is a plain vessel, which is the false identity the rule exists to
    stop. A composition that reproduces a tabulated example -- a body carrying
    item 29.2 is X8125 -- says so itself."""
    overlays = (Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.2),)
    assert registry.composed("composition_test", "default", overlays).iso_reg == ""
    stated = compose(
        body(iso_reg="301"),
        [(Overlay(29, "gravity", 0.3, 0.3, 0.4, 0.2), part(SETTLING))],
        iso_reg="X8125",
    )
    assert stated.iso_reg == "X8125"


# ---------------------------------------------------------------- backends


def test_a_composed_symbol_names_no_drawio_stencil():
    """The guard against the two backends drawing different things.

    A stencil reference names one shape, and draw.io draws whatever that name
    resolves to. A composed reactor exported under its body's reference would
    come out as a bare vessel: the right outline, silently missing the thing
    that made it a reactor. Naming nothing is what keeps the divergence loud.
    """
    stencilled = body(drawio_shape="mxgraph.pid.vessels.tower")
    sym = compose(stencilled, [(Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05), part(TRAY))])
    assert stencilled.drawio_shape
    assert sym.drawio_shape == ""
    assert sym.overlays  # ...and this is what the exporter draws instead


def test_a_composed_symbol_renders_through_the_svg_backend():
    """The composition is one ``Symbol``, so nothing downstream learns a second
    kind of drawing. Rendered here end to end to say so.

    Into ``default_registry``, because layout resolves ports against that one
    and a sheet drawn from a registry the engine never sees is only half a
    test.
    """

    class Body(units.Unit):
        kind = "composition_test"
        PORTS = [("feed", "inlet", "feed"), ("bottoms", "outlet", "liquid")]

    default_registry.register(Body.kind, body())
    try:
        fs = Flowsheet("composition")
        unit = Body("X-1")
        # The shipped item 27.1 C2044, not a placeholder: the artwork exists
        # now, and a registry-level test that swapped it for a stand-in would
        # have to put the real one back afterwards or take it out of the
        # library for every test that ran after this one.
        unit.overlays = (Overlay(27, "tray", 0.1, 0.5, 0.8, 0.05),)
        fs.add(unit)
        fs.layout()
        svg = SvgRenderer().render(fs)
        assert 'id="sym_composition_test_c' in svg
        # The part's own rule, drawn inside the body's definition.
        assert "<line" in svg
    finally:
        default_registry._symbols.pop((Body.kind, "default"), None)
        default_registry._composed.clear()


# ------------------------------------------------- what the registry composes


def test_the_registry_composes_exactly_the_rows_ISO_gives_a_number_to():
    """A composition the *registry* ships is a composition **ISO tabulates**.

    Two kinds of composition exist and only one of them belongs here. The one
    an author configures -- which agitator, how many trays -- is built per unit
    from a keyword and cannot be enumerated, because the combinations are the
    point. The one the standard itself tabulates as a symbol example with a
    registration number has a fixed answer, and a fixed answer belongs in the
    registry beside every other fixed drawing.

    Twelve, in two families. Three are ISO 10628-2 group 8: one separating
    vessel carrying one group-29 characteristic. The other nine are group 11,
    the crushing and grinding machines: one crusher or mill body carrying one
    group-29 characteristic, which is the same shape of row and the reason
    closing that group cost two drawings instead of eleven.

    The list is spelled out rather than counted so that a thirteenth arriving
    has to be argued for here.
    """
    composed = {
        f"{kind}/{variant}": sym.iso_reg
        for (kind, variant), sym in default_registry._symbols.items()
        if sym.overlays
    }
    assert composed == {
        "separator/gravity": "X8031",
        "separator/electrostatic": "X8125",
        "separator/electromagnetic": "X8126",
        "crusher/hammer": "X8045",
        "crusher/impact": "X8046",
        "crusher/jaw": "X8047",
        "crusher/roller": "X8048",
        "crusher/cone": "X8049",
        "mill/hammer": "X8050",
        "mill/impact": "X8051",
        "mill/roller": "X8053",
        "mill/vibration": "X8054",
    }


def test_the_two_group_11_bodies_are_the_outline_table_2_draws():
    """The trapezoid, and the one mark each that tells a crusher from a mill.

    Measured off rows 11.2 and 11.8 in grid modules and written here in drawing
    units at ten to the module, which is the scale
    ``symbols._CRUSHER_W`` x ``_CRUSHER_H`` is built at:

    * the shared trapezoid, 10 M across the top and 6 M across the bottom over a
      6 M depth -- (0,0) (100,0) (80,60) (20,60);
    * the **crusher's** two verticals at x 20 and x 80, which are ISO's x 9 and
      x 15, running the full depth;
    * the **mill's** two chords, each striking the top edge 2,5 M in from a
      corner and falling 4 down for 3 across to the wall at (10/13, 30/13) M.

    Neither mark is in group 29, which is why both are body rather than part and
    why this is a geometry check rather than a composition one. The numbers are
    spelled out so that a redraw has to be argued against the page.
    """
    trapezoid = "M 0 0 L 100 0 L 80 60 L 20 60 Z"
    crusher = default_registry.get("crusher")
    mill = default_registry.get("mill")
    for sym in (crusher, mill):
        assert (sym.width, sym.height) == (100.0, 60.0)
        assert trapezoid in sym.svg
        # Fed at the mouth, discharging at the throat, and nothing else. See
        # ``units._CrushingMachine`` on why there is no drive.
        assert sym.ports == {"feed": (50.0, 0.0), "discharge": (50.0, 60.0)}
    assert "M 20 0 L 20 60 M 80 0 L 80 60" in crusher.svg
    assert "M 25 0 L 7.6923 23.0769 M 75 0 L 92.3077 23.0769" in mill.svg
    # The vibration mill is the same body with X8054's drum on it, which is the
    # only reason ``mill/vibration`` can claim that number; see
    # ``symbols._VIBRATION_DRUM``.
    drum = default_registry.get("mill", "vibration")
    assert '<circle cx="50" cy="30" r="20"' in drum.svg


def test_the_cyclone_is_not_composed():
    """ISO 14617-1 §4.5 names X2618 by registration number as a symbol in its
    own right, and group 29 has no vortex to compose one from. So a
    hydrocyclone is a whole drawing, keeps its stencil, and ``variant=`` stays
    the way to ask for one -- which is why it is not deprecated.

    The four beside it are here for the same reason, one absence each: no
    baffle (8.2), no spray (8.5), no permanent magnet (8.9) and no double arc
    (8.4) anywhere in group 29.
    """
    for variant in ("cyclone", "sifter", "impact", "permanent_magnet", "scrubber"):
        sym = default_registry.get("separator", variant)
        assert not sym.overlays, f"separator/{variant} is composed"
        assert sym.drawio_shape, f"separator/{variant} lost its stencil"


def test_the_parts_that_ship_are_available_and_unused():
    """The artwork for groups 26-29 has since landed in
    ``pandid/render/iso_parts.py``, and ``tests/test_iso_parts.py`` is where it
    is held to Table 2 row by row.

    What this file still asserts is the half that has not changed: registering
    a part makes it *available* to be overlaid, in a namespace of its own that
    the symbol lookup never reads. So no lookup, no sheet and no golden can
    have moved -- which is what the test above says from the other side.

    One name proves the namespaces are separate rather than merely disjoint by
    luck: ``turbine`` is both a group-28 agitator and a kind of machine, and
    the two are different drawings that neither shadow nor collide with each
    other.
    """
    assert default_registry.parts()
    agitator = default_registry.part(28, "turbine")
    machine = default_registry.get("turbine")
    assert agitator.iso.reg == "C2027"
    assert agitator.svg != machine.svg and not machine.overlays


#: The whole drawings that claim a registration number, and the only ones.
#:
#: Every other one of the library's vendored drawings claims nothing, and that
#: is the point of the field: filling one in is a conformance claim about that
#: symbol's geometry, and one made by assumption is worse than none. The
#: backfill over the vendored set is still its own change, against Table 2, one
#: drawing at a time.
#:
#: These are not backfill. None existed before the Table 2 row was measured --
#: ``crusher/default`` *is* item 11.2 and ``mill/default`` *is* item 11.8,
#: drawn from the rows and from nothing else -- so the claim is the same kind
#: of claim a composition makes, and is checkable the same way. The three
#: group-18 drawings joined them the same way: a screw conveyor and the two
#: bucket elevators, none of which draw.io has a stencil for either.
_NUMBERED_WHOLE_DRAWINGS = {
    "crusher/default": "X8085",
    "mill/default": "X8086",
    "conveyor/screw": "X8063",
    "elevator/default": "X8065",
    "elevator/z_form": "X8066",
}


def test_a_registration_number_is_claimed_by_a_composition_or_by_a_measured_body():
    """A composition is why the field exists. It is only ever built because the
    standard composes at that point, so the row it reproduces is known at the
    moment it is built: a separating vessel carrying item 29.2 *is* X8125, and
    saying so is what makes the composition checkable rather than plausible.

    :data:`_NUMBERED_WHOLE_DRAWINGS` is the other way in, and it is deliberately
    a list rather than a rule: a whole drawing may say which row it is only
    where somebody drew it *from* that row. Vendoring a stencil and guessing at
    its number is what this still refuses.
    """
    numbered = {
        f"{kind}/{variant}": sym
        for (kind, variant), sym in default_registry._symbols.items()
        if sym.iso_reg
    }
    whole = {name: sym.iso_reg for name, sym in numbered.items() if not sym.overlays}
    assert whole == _NUMBERED_WHOLE_DRAWINGS, (
        "a whole drawing claimed a registration number without being drawn from "
        "the row; that is the backfill, and it wants its own change"
    )


def test_a_built_to_size_drawing_does_not_capture_its_kinds_other_variants():
    """``_BUILT_TO_SIZE`` used to be keyed by kind alone.

    Both entries in it are kind-wide and both kinds have one variant, so the
    two spellings said the same thing about the symbols on hand -- and only one
    of them stays true when a second variant arrives. A tray column drawn to
    its tray count is a ``("column", "tray")`` entry, and under a kind-wide key
    it would have captured ``column/default`` and ``column/packed`` too.
    """
    from pandid.render import symbols

    marker = body(width=7.0)
    symbols._BUILT_TO_SIZE[("composition_test", "sized")] = lambda unit: marker
    try:
        reg = SymbolRegistry()
        reg.register("composition_test", body())
        reg.register("composition_test", body(), "sized")

        class Body(units.Unit):
            kind = "composition_test"

        assert reg.for_unit(Body("X-1", variant="sized")) is marker
        assert reg.for_unit(Body("X-2")) is reg.get("composition_test")
    finally:
        del symbols._BUILT_TO_SIZE[("composition_test", "sized")]


def test_a_tubular_reactor_drops_the_vent_it_has_no_use_for():
    """What ``_VARIANT_PORTS`` was added for.

    A tubular reactor is a pipe with a bed in it: no vapour space, so no
    off-gas to take, and a nozzle nothing is ever routed to is a nozzle an
    author has to be told to ignore. Every vertical reactor keeps all three.
    """
    assert [name for name, _, _ in units.Reactor._variant_ports("default")] == [
        "outlet",
        "vent",
        "duty",
    ]
    assert [name for name, _, _ in units.Reactor._variant_ports("tubular")] == [
        "outlet",
        "duty",
    ]
    assert "vent" not in units.Reactor("R-301", variant="tubular", agitator=None).ports


def test_only_the_agitator_brings_the_drive():
    """The nozzle a *part* anchors exists exactly when the part does.

    ISO item 1.27 X8006 runs the stirrer's shaft up through the top head to the
    motor above the vessel, and the motor is where the power arrives -- so the
    drive is a real connection at a real place, and a reactor with no stirrer
    has neither the motor nor anything for it to turn.
    """
    assert "drive" in units.Reactor("R-101").ports
    assert "drive" in units.Reactor("R-102", agitator="turbine").ports
    assert "drive" not in units.Reactor("R-201", agitator=None).ports
    # The body's own nozzles are unchanged either way, and in order.
    assert list(units.Reactor("R-101").ports) == ["outlet", "vent", "duty", "drive", "feed"]


def drawn(unit):
    """The parts on a unit's drawing, by identity rather than by number.

    ``(group, name)`` and not a count: a test that counted would pass on a
    reactor drawn with the wrong stirrer, and the whole subject here is
    *which* part ends up on the body.

    Read off the composed :class:`~pandid.render.symbols.Symbol` rather than
    off ``unit.overlays``, because those are two different routes to a
    composition and only the symbol is both. A separator's characteristic is
    composed in the registry, under the ISO registration number of the row it
    reproduces; everything else is composed per unit.
    """
    return [(overlay.group, overlay.name) for overlay in default_registry.for_unit(unit).overlays]


@pytest.mark.parametrize(
    "internals", ["packing", "fluidised_bed", "sieve_tray", "tray", "filter_insert"]
)
@pytest.mark.parametrize("variant", ["default", "jacketed"])
def test_naming_internals_leaves_out_the_agitator_nobody_asked_for(variant, internals):
    """A reactor with a bed in it is not a stirred tank.

    ``agitator=`` defaults to item 28.1 on the two stirred bodies, which is
    right for a reactor described only by its body -- and wrong the moment the
    author says what is inside it. A packed bed is not stirred, a fluidised bed
    is mixed by its own fluidisation, and a trayed vessel is not a tank with a
    paddle in it; drawing one anyway put a stirrer through the bed it would
    have had to turn in.
    """
    unit = units.Reactor("R-201", variant=variant, internals=internals)
    assert drawn(unit) == [(27, internals)]
    assert unit.agitator is None
    # The drive is the agitator's, so it goes with it.
    assert "drive" not in unit.ports


def test_an_agitator_the_author_named_survives_its_internals():
    """A stirred slurry reactor is a real vessel, and this is how it is asked
    for.

    The suppression is of the *default*, not of the keyword: what is being read
    is whether the author said anything, which is the one thing the
    :data:`~pandid.units._UNSTATED` sentinel exists to record. Order is drawing
    order -- the bed first, the stirrer over it -- so the shaft is drawn on top
    of what it turns in.
    """
    unit = units.Reactor("R-203", agitator="turbine", internals="packing")
    assert drawn(unit) == [(27, "packing"), (28, "turbine"), (20, "motor")]
    assert (unit.agitator, unit.internals) == ("turbine", "packing")
    assert "drive" in unit.ports


def test_the_reactor_forms_that_did_not_change():
    """The three spellings the suppression must leave exactly where they were.

    A rule about one keyword that moves another keyword's drawing is a rule
    that has escaped its subject, so the neighbours are asserted rather than
    assumed.
    """
    # Nothing said at all: still the stirred tank a reactor is by default,
    # and a stirrer comes with the motor that turns it (ISO item 1.27 X8006).
    assert drawn(units.Reactor("R-101")) == [(28, "agitator"), (20, "motor")]
    # Said, and said empty: still the bare shell somebody asked for.
    assert drawn(units.Reactor("R-102", agitator=None)) == []
    # Said, and said something: still that stirrer.
    assert drawn(units.Reactor("R-103", agitator="anchor")) == [(28, "anchor"), (20, "motor")]


def test_the_agitator_default_is_the_same_answer_wherever_it_is_asked_for():
    """The constructor and a serializer read one rule, not two.

    :meth:`~pandid.units.Unit.composition_defaults` is that rule, and
    ``pandid.spec._write_composition`` asks it the same question the
    constructor did -- so a keyword left off a spec reads back as the drawing
    it was written from. A default worked out in the constructor alone would
    have written ``agitator: null`` onto every packed-bed reactor instead.
    """
    for internals, expected in (("packing", None), (None, "agitator")):
        stated = {"agitator": units._UNSTATED, "internals": internals}
        assert units.Reactor.composition_defaults("default", stated)["agitator"] == expected
        assert units.Reactor("R-1", internals=internals).agitator == expected


def test_a_class_with_one_composition_keyword_has_nothing_to_suppress():
    """Only a reactor composes from two parts at once.

    A column's ``trays`` is a count rather than a part, and a vessel and a
    separator take one keyword each, so there is no second part for a first to
    rule out. Asserted rather than left implied: the suppression is a rule
    about keywords *together*, and the classes it does not apply to are as much
    a part of it as the one it does.
    """
    two_parts = {
        cls.__name__
        for cls in (units.Reactor, units.Column, units.Vessel, units.Separator)
        if len([key for key in cls.COMPOSITION if key != "trays"]) > 1
    }
    assert two_parts == {"Reactor"}
    assert drawn(units.Column("T-104", internals="packing", trays=2)) == [(27, "packing")] * 2
    assert drawn(units.Vessel("D-301", supports="skirt")) == [(26, "skirt")]
    assert drawn(units.Separator("V-201", characteristic="gravity")) == [(29, "gravity")]
