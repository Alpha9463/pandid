"""Test the ISO 10628-2 Table 2 part artwork and its composition onto a body."""

import math
import re

import pytest

from pandid.render import iso_parts
from pandid.render.weights import M, LineWeight
from pandid.render.symbols import Overlay, Symbol, compose, default_registry
from test_symbol_invariants import _collect_segments

# Every part as (item, registration number, descriptor) from ISO 10628-2:2012 Table 2.
TABLE_2 = {
    (26, "leg"): ("26.1", "C2005", "Support leg"),
    (26, "bracket"): ("26.2", "C2006", "Support bracket"),
    (26, "skirt"): ("26.3", "C2007", "Support skirt"),
    (26, "ring"): ("26.4", "C2008", "Support ring"),
    # Each drawn on a west wall, and turned to point up and down.
    (26, "manhole"): ("26.5", "X8159", "Manhole"),
    (26, "manhole_up"): ("26.5", "X8159", "Manhole"),
    (26, "manhole_down"): ("26.5", "X8159", "Manhole"),
    (26, "socket"): ("26.6", "X8160", "Socket, connection nozzle"),
    (26, "socket_up"): ("26.6", "X8160", "Socket, connection nozzle"),
    (26, "socket_down"): ("26.6", "X8160", "Socket, connection nozzle"),
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
    # The group-20 drive that item 1.27 X8006 draws above a stirred vessel.
    (20, "motor"): ("20.6", "C0082", "Electric motor (general)"),
    (29, "gravity"): ("29.1", "C2028", "Gravity type, settling type"),
    (29, "electrostatic"): ("29.2", "C2030", "Electrostatic type"),
    (29, "electromagnetic"): ("29.3", "C2031", "Electromagnetic type"),
    (29, "disc"): ("29.4", "C2033", "Disc type"),
    (29, "crushing"): ("29.5", "C0240", "Crushing"),
    # Three digits, as Table 2 prints it.
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
    """Build a plain rectangular body to hang a part on."""
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
    """Check that groups 20 and 26-29 register 1, 10, 8, 10 and 14 parts."""
    counts = {g: len(default_registry.part_names(g)) for g in (20, 26, 27, 28, 29)}
    assert counts == {20: 1, 26: 10, 27: 8, 28: 10, 29: 14}
    assert default_registry.part_names(20) == ["motor"]


def test_a_mark_is_a_separator_keyword_only_where_iso_composes_a_separator():
    """Check that Separator accepts only the three ISO group-8 characteristics."""
    from pandid.units import Separator

    assert Separator._CHARACTERISTICS == ("gravity", "electrostatic", "electromagnetic")
    for name in ("crushing", "hammer", "jet"):
        assert default_registry.part(29, name)
        with pytest.raises(ValueError):
            Separator("V-901", characteristic=name)


def test_every_group_11_row_composes_the_mark_table_2_draws_in_it():
    """Check that each composed crusher and mill carries its row's group-29 mark."""
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
    """Check that a crushing mark is centred on the body at its Table 2 size in modules."""
    from pandid.render.iso_parts import CRUSHER_MODULES_H, CRUSHER_MODULES_W, crushing_overlays

    w, h = modules
    (overlay,) = crushing_overlays(name)
    assert (overlay.w * CRUSHER_MODULES_W, overlay.h * CRUSHER_MODULES_H) == (w, h)
    assert overlay.x == pytest.approx((CRUSHER_MODULES_W - w) / 2 / CRUSHER_MODULES_W)
    assert overlay.y == pytest.approx((CRUSHER_MODULES_H - h) / 2 / CRUSHER_MODULES_H)


def test_the_vibration_mark_is_squeezed_the_way_the_mill_row_squeezes_it():
    """Check that the vibration part is 3 M wide and its mill overlay 2 M wide."""
    from pandid.render.iso_parts import M, CRUSHER_MODULES_W, crushing_overlays

    assert default_registry.part(29, "vibration").width == 3 * M
    (overlay,) = crushing_overlays("vibration")
    assert overlay.w * CRUSHER_MODULES_W == 2


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_asked_for_by_group_and_name(part):
    assert default_registry.part(part.iso.group, part.name) is part


def test_every_part_that_draw_io_has_a_shape_for_names_it():
    """Check that exactly the group-28 agitators name a draw.io agitator shape."""
    stencilled = {p.name for p in iso_parts.parts() if p.drawio_shape}
    assert stencilled == {p.name for p in iso_parts.parts() if p.iso.group == 28}
    for part in iso_parts.parts():
        if part.drawio_shape:
            assert part.drawio_shape.startswith("mxgraph.pid.agitators.")


# --- how they are drawn -------------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_drawn_at_the_detail_weight(part):
    """Check that a part strokes only at the detail weight, half the equipment weight."""
    widths = {float(w) for w in re.findall(r'stroke-width="([\d.]+)"', part.svg)}
    assert widths in ({iso_parts.PART_STROKE}, set())
    assert iso_parts.PART_STROKE * 2 == LineWeight.EQUIPMENT.width


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_parts_ink_stays_inside_the_box_it_declares(part):
    """Check that a part's ink stays within the box it declares."""
    segments = _collect_segments(part.svg)
    assert segments, "a part that draws nothing is not a drawing"
    xs = [x for seg in segments for x, _ in seg]
    ys = [y for seg in segments for _, y in seg]
    slack = iso_parts.PART_STROKE  # half a stroke each side of an edge line
    assert -slack <= min(xs) and max(xs) <= part.width + slack
    assert -slack <= min(ys) and max(ys) <= part.height + slack


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_parts_box_is_a_whole_number_of_grid_modules(part):
    """Check that a part's width and height are whole grid modules."""
    assert part.width % iso_parts.M == 0
    assert part.height % iso_parts.M == 0


def test_no_agitator_shaft_is_dashed():
    """Check that no group-28 agitator draws a dashed stroke."""
    for part in PARTS:
        if part.iso.group == 28:
            assert "dasharray" not in part.svg, f"{part.iso.reg} {part.name}"


def test_only_the_two_iso_dash_pitches_are_used():
    """Check that the parts use only the two ISO dash pitches."""
    used = set(re.findall(r'stroke-dasharray="([\d.,]+)"', "".join(p.svg for p in PARTS)))
    assert used == {"20,10", "20,10,10,10"}


# --- what a part contributes --------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_only_the_motor_brings_a_connection(part):
    """Check that only the motor declares a port, ``drive`` at its top centre."""
    if part.iso.group == 20:
        assert set(part.ports) == {"drive"}
        assert part.ports["drive"] == (part.width / 2, 0.0)
    else:
        assert part.ports == {}


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_every_part_fills_the_rectangle_it_is_given(part):
    """Check that every part is stretchable."""
    assert part.stretchable


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_no_part_holds_its_own_artwork_still_under_a_flip(part):
    """Check that no part is directional."""
    assert not part.directional


def test_the_settling_arrow_fixes_the_body_it_is_drawn_in():
    """Check that the gravity arrow is gravity-fixed and not directional."""
    arrow = default_registry.part(29, "gravity")
    assert arrow.gravity_fixed and not arrow.directional


# --- composed onto a body -----------------------------------------------------


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_inside_the_body_leaves_the_body_its_own_box(part):
    """Check that a part inside the body keeps the body's box and nozzles."""
    host = body()
    overlay = Overlay(part.iso.group, part.name, 0.2, 0.2, 0.5, 0.4)
    out = compose(host, [(overlay, part)])
    assert (out.width, out.height) == (host.width, host.height)
    assert out.ports["inlet"] == host.ports["inlet"]
    assert out.overlays == (overlay,)


@pytest.mark.parametrize("part", PARTS, ids=IDS)
def test_a_part_is_drawn_at_its_declared_weight_however_it_is_scaled(part):
    """Check that a composed part's stroke, times its scale, stays at the part weight."""
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
    assert f'stroke-width="{LineWeight.EQUIPMENT.width:g}"' in out.svg


def test_a_motors_drive_lands_on_the_body_and_the_bodys_nozzles_survive():
    """Check that a motor adds a drive port where it is drawn and keeps the body's nozzles."""
    host = body()
    out = compose(
        host, [(Overlay(20, "motor", 0.3, -0.2, 0.4, 0.16), default_registry.part(20, "motor"))]
    )
    assert set(out.ports) == {"inlet", "outlet", "drive"}
    # The motor's top edge sits 40 units above the 200-tall body.
    assert (out.width, out.height) == (80.0, 240.0)
    # The drive lands on the top edge, on the motor rectangle's centre line.
    assert out.ports["drive"] == (pytest.approx(40.0), pytest.approx(0.0))
    assert out.ports["inlet"] == (0.0, host.ports["inlet"][1] + 40.0)


def test_a_stirred_vessel_is_drawn_with_the_motor_that_turns_it():
    """Check that a stirred reactor places the stirrer and the motor on its shaft."""
    stirrer, motor = iso_parts.agitator_overlays("turbine", "reactor", "default")
    assert (stirrer.group, stirrer.name) == (28, "turbine")
    assert (motor.group, motor.name) == (20, "motor")
    reactor = default_registry.get("reactor", "default")
    # 2 M across, centred, and round on the body it is placed on.
    assert motor.w * reactor.width == pytest.approx(2 * M)
    assert motor.x + motor.w / 2 == pytest.approx(0.5)
    assert motor.h * reactor.height == pytest.approx(2 * M)
    # 1 M above the crown, met by the stirrer's rectangle.
    assert (motor.y + motor.h) * reactor.height == pytest.approx(-M)
    assert stirrer.y * reactor.height == pytest.approx(-M)
    # The blade stays put; only the top edge goes negative.
    assert stirrer.y + stirrer.h == pytest.approx(0.76)


def test_a_composed_body_stretches_exactly_as_the_bare_one_does():
    """Check that composing a part keeps the body stretchable."""
    host = body()
    out = compose(
        host,
        [(Overlay(28, "propeller", 0.3, 0.05, 0.4, 0.8), default_registry.part(28, "propeller"))],
    )
    assert host.stretchable and out.stretchable


def test_a_column_of_trays_is_n_overlays_and_not_a_count():
    """Check that twelve tray overlays compose as twelve overlays without the part wrapper."""
    deck = default_registry.part(27, "baffle_tray")
    overlays = [
        Overlay(27, "baffle_tray", 0.1 if i % 2 else 0.2, 0.1 + 0.05 * i, 0.7, 0.04)
        for i in range(12)
    ]
    out = compose(body(), [(o, deck) for o in overlays])
    assert len(out.overlays) == 12
    assert out.svg.count('id="part_27_baffle_tray"') == 0  # the wrapper is dropped


# --- stage_fraction: where a feed asked for a stage actually lands ----------


@pytest.mark.parametrize("count", [1, 8, 30])
def test_a_decks_stage_lands_where_internals_overlays_centres_the_deck(count):
    """Check that a tray stage lands on the centre of its ``internals_overlays`` deck."""
    overlays = iso_parts.internals_overlays("tray", count)
    for k in range(1, count + 1):
        deck = overlays[k - 1]
        assert iso_parts.stage_fraction("tray", k, count) == pytest.approx(deck.y + deck.h / 2)


@pytest.mark.parametrize("count", [1, 2, 5])
def test_a_beds_stage_lands_on_the_bed_internals_overlays_draws_above_it(count):
    """Check that a packing stage lands on the top edge of its ``internals_overlays`` bed."""
    overlays = iso_parts.internals_overlays("packing", count)
    for k in range(1, count + 1):
        bed = overlays[k - 1]
        assert iso_parts.stage_fraction("packing", k, count) == pytest.approx(bed.y)


def test_a_stage_out_of_range_is_refused_naming_the_count():
    with pytest.raises(ValueError, match=r"stage 0 is not on a column of 30"):
        iso_parts.stage_fraction("tray", 0, 30)
    with pytest.raises(ValueError, match=r"stage 31 is not on a column of 30"):
        iso_parts.stage_fraction("tray", 31, 30)
