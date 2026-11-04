"""Check ISO 10628-2 group 18's conveyors and elevators; the conveyors are built to size."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
from test_symbol_invariants import GEOM_TOL, _collect_segments, _nearest_distance

from pandid import Flowsheet, units as U
from pandid.portgeom import port_point, resolve_size, symbol_to_box
from pandid.render.symbols import (
    CONVEYOR_LENGTH,
    CONVEYOR_ROLLER,
    SCREW_HEIGHT,
    SCREW_MARGIN,
    SCREW_MIN_LENGTH,
    SCREW_MODULE,
    SCREW_PITCH,
    SCREW_REACH,
    SCREW_TURN,
    conveyor_min_length,
    conveyor_symbol,
    default_registry,
    screw_conveyor_symbol,
)

SVG = "{http://www.w3.org/2000/svg}"
R = CONVEYOR_ROLLER
CONVEYOR_MIN_LENGTH = conveyor_min_length()


def _sheet(lengths, diameters=None, **pin):
    """Return a flowsheet with one piped conveyor per size, and its parsed SVG.

    ``lengths`` may be runs or ``(length, diameter)`` pairs; ``diameters`` pairs
    each diameter with every length instead.
    """
    sizes = [s if isinstance(s, tuple) else (s, None) for s in lengths]
    if diameters is not None:
        sizes = [(length, d) for length, _ in sizes for d in diameters]
    fs = Flowsheet("conveyors")
    for i, (length, diameter) in enumerate(sizes):
        feed = fs.add(U.Feed(f"IN-{i}"))
        kwargs = {} if diameter is None else {"diameter": diameter}
        conv = fs.add(U.Conveyor(f"BC-{i}", length=length, **kwargs))
        product = fs.add(U.Product(f"OUT-{i}"))
        if pin:
            conv.pin(**pin)
        fs.connect(feed.outlet, conv.feed)
        fs.connect(conv.discharge, product.inlet)
    return fs, ET.fromstring(fs.to_svg())


def _defs(root):
    return {el.get("id"): el for el in root.iter(f"{SVG}symbol")}


def _uses(root):
    return {el.get("href"): el for el in root.iter(f"{SVG}use")}


def _ellipses(el):
    return [
        (float(e.get("cx")), float(e.get("cy")), float(e.get("rx")), float(e.get("ry")))
        for e in el.iter(f"{SVG}ellipse")
    ]


def _belt_runs(el):
    """Length of each straight belt line drawn in a conveyor definition."""
    runs = []
    for path in el.iter(f"{SVG}path"):
        parts = path.get("d").split()
        for i in range(0, len(parts), 6):  # "M x y L x y"
            runs.append(float(parts[i + 4]) - float(parts[i + 1]))
    return runs


# ---------------------------------------------------------------------------
# The second dimension: the roller, set independently of the run.
# ---------------------------------------------------------------------------

DIAMETERS = [8.0, 2 * R, 45.0, 120.0]
#: Every length with every diameter, and the default roller at every legal length.
COMBOS = [(length, d) for length in (240.0, 400.0) for d in DIAMETERS] + [
    (length, 2 * R) for length in (CONVEYOR_MIN_LENGTH, 41.0, 80.0, 160.0, 300.0, 1000.0)
]


def _sym_id(length, diameter=None):
    """The definition id a belt of this size is drawn under."""
    tail = "" if diameter in (None, 2 * R) else f"_D{diameter:g}"
    return f"sym_conveyor_L{length:g}{tail}"


@pytest.mark.parametrize("length,diameter", COMBOS)
def test_the_rollers_are_true_circles_at_every_run_and_roller(length, diameter):
    """Check that the rollers are true circles drawn at a scale of 1 at every size."""
    _, root = _sheet([(length, diameter)])
    definition = _defs(root)[_sym_id(length, diameter)]
    r = diameter / 2
    assert _ellipses(definition) == [(r, r, r, r), (length - r, r, r, r)]
    _, _, vb_w, vb_h = (float(v) for v in definition.get("viewBox").split())
    use = _uses(root)[f"#{_sym_id(length, diameter)}"]
    assert (float(use.get("width")), float(use.get("height"))) == (vb_w, vb_h)
    assert (vb_w, vb_h) == (length, diameter)
    assert _belt_runs(definition) == [length - diameter] * 2


@pytest.mark.parametrize("length,diameter", COMBOS)
def test_every_port_lands_on_drawn_ink_at_every_combination(length, diameter):
    sym = conveyor_symbol(length, diameter)
    segments = _collect_segments(sym.svg)
    for name, faces in sym.port_faces.items():
        for face, point in faces.items():
            assert _nearest_distance(point, segments) <= GEOM_TOL, (
                f"{name}/{face} at {length:g}x{diameter:g}"
            )


def test_neither_dimension_moves_the_other():
    """Check that the run and the roller size each other's drawing not at all."""
    _, root = _sheet([240.0, 400.0], diameters=DIAMETERS)
    defs = _defs(root)
    for length in (240.0, 400.0):
        for diameter in DIAMETERS:
            definition = defs[_sym_id(length, diameter)]
            assert {e[2] for e in _ellipses(definition)} == {diameter / 2}
            assert _belt_runs(definition) == [length - diameter] * 2


def test_the_default_roller_is_the_stencils_own_and_draws_what_it_always_drew():
    """Check that the default roller is ``2 * R`` and draws under the length-only id."""
    assert conveyor_symbol(300.0) == conveyor_symbol(300.0, 2 * R)
    assert conveyor_symbol(300.0).id_suffix == "_L300"
    assert U.Conveyor("BC-301").diameter == 2 * R


def test_a_belt_on_bigger_rollers_needs_a_longer_bed():
    """Check that the minimum length is two roller diameters."""
    assert U.Conveyor("BC-301", length=90, diameter=45).length == 90
    with pytest.raises(ValueError, match=r"Use length=90 or more"):
        U.Conveyor("BC-302", length=89, diameter=45)


def test_growing_the_roller_under_a_belt_too_short_for_it_is_refused():
    """Check that a roller too big for the belt is refused and the old one kept."""
    conveyor = U.Conveyor("BC-301", length=90)
    conveyor.diameter = 45
    with pytest.raises(ValueError, match=r"rollers.*would overlap"):
        conveyor.diameter = 50
    assert conveyor.diameter == 45


def test_changing_to_a_variant_the_length_is_too_short_for_is_refused() -> None:
    """Check that a variant the length cannot draw is refused and the old one kept."""
    screw = U.Conveyor("SC-301", variant="screw", length=40)
    with pytest.raises(ValueError, match=r"rollers.*would overlap"):
        screw.variant = "default"
    assert screw.variant == "screw"
    belt = U.Conveyor("BC-301", length=10, diameter=5)
    with pytest.raises(ValueError, match=r"screw conveyor can be drawn"):
        belt.variant = "screw"
    assert belt.variant == "default"


def test_changing_to_a_variant_the_length_fits_is_accepted() -> None:
    """Check that a variant the length can draw is accepted."""
    conveyor = U.Conveyor("CV-301", length=80)
    conveyor.variant = "screw"
    assert conveyor.variant == "screw"


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({}, r"the rollers are circles"),
        ({"variant": "screw"}, r"the casing is a tube"),
    ],
)
def test_a_diameter_with_no_circle_in_it_is_refused_in_the_machines_words(kwargs, message):
    with pytest.raises(ValueError, match=message):
        U.Conveyor("BC-301", length=140, diameter=0, **kwargs)


def test_belts_of_one_size_share_a_definition_and_others_do_not():
    """Check that belts share a definition exactly when run and roller match."""
    _, root = _sheet([(240.0, 45.0), (240.0, 45.0), 240.0, 240.0, (400.0, 45.0), 300.0])
    ids = sorted(i for i in _defs(root) if i.startswith("sym_conveyor"))
    assert ids == [
        "sym_conveyor_L240",
        "sym_conveyor_L240_D45",
        "sym_conveyor_L300",
        "sym_conveyor_L400_D45",
    ]


def test_a_conveyor_round_trips_through_a_spec_with_its_roller():
    fs = Flowsheet("cake handling")
    fs.add(U.Conveyor("BC-301", length=300, diameter=45))
    fs.add(U.Conveyor("BC-302", length=300))
    spec = fs.to_dict()
    assert spec["units"][0]["diameter"] == 45.0
    assert "diameter" not in spec["units"][1]
    rebuilt = Flowsheet.from_dict(spec)
    assert [u.diameter for u in rebuilt.units] == [45.0, 2 * R]
    assert rebuilt.to_dict() == spec


# ---------------------------------------------------------------------------
# Two numbers, and the box is neither of them.
# ---------------------------------------------------------------------------


def test_the_length_is_the_symbols_width_so_nothing_else_states_it():
    conveyor = U.Conveyor("BC-301", length=300)
    assert conveyor.width is None and conveyor.height is None
    assert default_registry.for_unit(conveyor).width == 300.0
    assert resolve_size(conveyor) == (300.0, 2 * R)


def test_a_quarter_turn_makes_the_length_the_height():
    conveyor = U.Conveyor("BC-301", length=300).pin(orientation=90)
    assert resolve_size(conveyor) == (2 * R, 300.0)


@pytest.mark.parametrize(
    "kwargs,names",
    [
        ({"width": 200}, "length=200"),
        ({"height": 60}, "diameter=60"),
    ],
)
def test_a_size_given_as_width_or_height_names_the_dimension_it_belongs_on(kwargs, names):
    """Check that ``width=`` or ``height=`` is refused, naming ``length=`` or ``diameter=``."""
    with pytest.raises(ValueError, match=r"sized by length=") as excinfo:
        U.Conveyor("BC-301", **kwargs)
    assert names in str(excinfo.value)


def test_the_roller_is_not_the_box_height_when_the_belt_is_stood_on_end():
    """Check that a turned belt keeps its length and diameter and swaps its box."""
    conveyor = U.Conveyor("BC-301", length=300, diameter=45).pin(orientation=90)
    assert (conveyor.length, conveyor.diameter) == (300.0, 45.0)
    assert resolve_size(conveyor) == (45.0, 300.0)


def test_a_belt_shorter_than_two_roller_diameters_is_refused():
    with pytest.raises(ValueError) as excinfo:
        U.Conveyor("BC-301", length=CONVEYOR_MIN_LENGTH - 1)
    message = str(excinfo.value)
    assert "BC-301" in message
    assert f"length={CONVEYOR_MIN_LENGTH:g} or more" in message


def test_the_minimum_itself_is_accepted():
    """Check that the minimum length is accepted."""
    assert conveyor_symbol(CONVEYOR_MIN_LENGTH).width == CONVEYOR_MIN_LENGTH


def test_shortening_an_existing_conveyor_is_refused_too():
    conveyor = U.Conveyor("BC-301")
    with pytest.raises(ValueError, match=r"shorter than a conveyor can be drawn"):
        conveyor.length = 5


# ---------------------------------------------------------------------------
# Placement: a conveyor turned and flipped still meets its streams.
# ---------------------------------------------------------------------------


def _world_segments(unit):
    """The symbol's strokes placed exactly the way the renderer places them."""
    frame = unit.frame
    sym = default_registry.for_unit(unit)
    rot = int(getattr(frame, "orientation", 0) or 0)
    placed = []
    for a, b in _collect_segments(sym.svg):
        points = []
        for px, py in (a, b):
            bx, by, bw, bh = symbol_to_box(
                px, py, sym.width, sym.height, rot, frame.mirrored, frame.mirror_y
            )
            points.append((frame.x + bx * frame.w / bw, frame.y + by * frame.h / bh))
        placed.append(tuple(points))
    return placed


@pytest.mark.parametrize(
    "pin",
    [
        {},
        {"orientation": 90},
        {"orientation": 270},
        {"mirrored": True},
        {"orientation": 90, "mirrored": "xy"},
    ],
)
def test_a_turned_or_flipped_conveyor_still_meets_its_streams(pin):
    """Check that a turned or flipped conveyor's ports lie on its placed ink."""
    fs, _ = _sheet([220.0], **pin)
    conveyor = next(u for u in fs.units if u.kind == "conveyor")
    segments = _world_segments(conveyor)
    for name in ("feed", "discharge"):
        point = port_point(conveyor, conveyor.frame, name)
        assert _nearest_distance(point, segments) <= GEOM_TOL, name


# ---------------------------------------------------------------------------
# Scheduled equipment, and the spec round trip.
# ---------------------------------------------------------------------------


def test_a_conveyor_is_scheduled_on_the_equipment_list():
    from pandid.document import equipment_list

    fs = Flowsheet("cake handling")
    fs.add(U.Conveyor("BC-301"))
    fs.add(U.Conveyor("BC-302", description="Filter Cake Conveyor Belt"))
    assert equipment_list(fs).rows == [
        ("BC-301", "Conveyor"),
        ("BC-302", "Filter Cake Conveyor Belt"),
    ]


def test_a_conveyor_round_trips_through_a_spec_with_its_length():
    fs = Flowsheet("cake handling")
    feed = fs.add(U.Feed("Cake"))
    conveyor = fs.add(U.Conveyor("BC-301", length=300, description="Cake Belt"))
    conveyor.pin(x=200, y=100, orientation=90)
    fs.connect(feed.outlet, conveyor.feed)

    spec = fs.to_dict()
    assert spec["units"][1] == {
        "kind": "Conveyor",
        "name": "BC-301",
        "description": "Cake Belt",
        "length": 300.0,
        "pin": {"x": 200, "y": 100, "orientation": 90},
    }
    rebuilt = Flowsheet.from_dict(spec)
    again = next(u for u in rebuilt.units if u.kind == "conveyor")
    assert again.length == 300.0
    assert rebuilt.to_dict() == spec


def test_a_spec_length_below_the_minimum_names_the_entry():
    from pandid.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Conveyor", "name": "BC-301", "length": 10}]}
    with pytest.raises(SpecError, match=r"units\[0\] 'BC-301'"):
        Flowsheet.from_dict(spec)


def test_the_default_length_is_the_stencils_own_proportion():
    """Check the default roller and length."""
    assert (CONVEYOR_ROLLER, CONVEYOR_LENGTH) == (10.0, 80.0)
    assert U.Conveyor("BC-301").length == CONVEYOR_LENGTH


# ---------------------------------------------------------------------------
# The screw conveyor, ISO 10628-2 item 18.5 X8063
# ---------------------------------------------------------------------------


def _screw_turns(length, diameter=SCREW_HEIGHT):
    """Return each flight turn of a screw conveyor as the points it is drawn through."""
    svg = screw_conveyor_symbol(length, diameter).svg
    body = re.search(r'<path d="(M 0 .*?)"', svg).group(1)
    runs = [r.strip() for r in body.split("M ") if r.strip()]
    return [
        [tuple(float(v) for v in p.split()) for p in run.split("L ") if p.strip()]
        for run in runs[1:]
    ]


def test_the_screw_is_the_construction_row_18_5_draws():
    """Check the screw's module sizes and the two turns row 18.5's casing carries."""
    assert SCREW_HEIGHT == 6 * SCREW_MODULE
    assert (SCREW_TURN, SCREW_REACH) == (4 * SCREW_MODULE, 2 * SCREW_MODULE)
    assert (SCREW_PITCH, SCREW_MARGIN) == (7 * SCREW_MODULE, 2 * SCREW_MODULE)
    # Row 18.5's own casing carries exactly the two turns it draws.
    assert len(_screw_turns(15 * SCREW_MODULE)) == 2


@pytest.mark.parametrize("length", [SCREW_MIN_LENGTH, 80, 120, 200, 400])
def test_a_turn_of_the_flight_is_the_same_turn_at_every_length(length):
    """Check that every flight turn has the same width, reach and pitch at every length."""
    turns = _screw_turns(length)
    assert turns, "a screw at a legal length drew no flight at all"
    axis = SCREW_HEIGHT / 2
    for pts in turns:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        assert max(xs) - min(xs) == pytest.approx(SCREW_TURN)
        assert (min(ys), max(ys)) == pytest.approx((axis - SCREW_REACH, axis + SCREW_REACH))
    starts = [min(p[0] for p in pts) for pts in turns]
    assert starts[0] == pytest.approx(SCREW_MARGIN)
    for a, b in zip(starts, starts[1:]):
        assert b - a == pytest.approx(SCREW_PITCH)
    # The last turn ends inside the head's clear casing.
    assert max(p[0] for p in turns[-1]) <= length - SCREW_MARGIN + GEOM_TOL


def test_a_longer_screw_gets_more_turns_rather_than_longer_ones():
    counts = [len(_screw_turns(n)) for n in (40, 80, 200, 400)]
    assert counts == sorted(counts) and counts[0] < counts[-1]


BORES = [12.0, SCREW_HEIGHT, 45.0, 90.0]


@pytest.mark.parametrize("diameter", BORES)
def test_a_wider_screw_keeps_its_pitch_and_its_flight_fills_the_casing(diameter):
    """Check that a wider bore keeps the turns along the axis and spans the bore across it."""
    turns = _screw_turns(200.0, diameter)
    assert len(turns) == len(_screw_turns(200.0))
    axis, reach = diameter / 2, diameter * SCREW_REACH / SCREW_HEIGHT
    starts = [min(p[0] for p in pts) for pts in turns]
    assert starts == [min(p[0] for p in pts) for pts in _screw_turns(200.0)]
    for pts in turns:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        assert max(xs) - min(xs) == pytest.approx(SCREW_TURN)
        assert (min(ys), max(ys)) == pytest.approx((axis - reach, axis + reach))
    assert screw_conveyor_symbol(200.0, diameter).height == diameter


def test_the_shortest_screw_is_the_same_screw_at_every_bore():
    """Check that the shortest screw does not depend on the bore."""
    for diameter in BORES:
        assert screw_conveyor_symbol(SCREW_MIN_LENGTH, diameter)
    with pytest.raises(ValueError, match=r"screw conveyor can be drawn"):
        U.Conveyor("SC-301", variant="screw", length=SCREW_MIN_LENGTH - 1, diameter=90)


def test_the_screws_bore_defaults_to_row_18_5s_own_casing():
    assert U.Conveyor("SC-301", variant="screw").diameter == SCREW_HEIGHT
    assert screw_conveyor_symbol(140.0) == screw_conveyor_symbol(140.0, SCREW_HEIGHT)
    assert screw_conveyor_symbol(140.0).id_suffix == "_L140"


def test_a_wider_screw_meets_its_streams():
    fs = Flowsheet("screw")
    feed, out = fs.add(U.Feed("IN")), fs.add(U.Product("OUT"))
    sc = fs.add(U.Conveyor("SC-301", variant="screw", length=200, diameter=60))
    fs.connect(feed.outlet, sc.feed).properties = {"Flow (kg/h)": "4200"}
    fs.connect(sc.discharge, out.inlet).properties = {"Flow (kg/h)": "4200"}
    assert fs.validate() == []
    sym = default_registry.for_unit(sc)
    segments = _collect_segments(sym.svg)
    for name, faces in sym.port_faces.items():
        for face, point in faces.items():
            assert _nearest_distance(point, segments) <= GEOM_TOL, f"{name}/{face}"


def test_the_screw_is_drawn_from_its_own_drawing_and_not_the_belts():
    """Check that a screw conveyor is drawn with the screw's drawing."""
    screw = default_registry.for_unit(U.Conveyor("SC-301", variant="screw", length=140))
    belt = default_registry.for_unit(U.Conveyor("BC-301", length=140))
    assert screw.width == belt.width == 140
    assert screw.height == SCREW_HEIGHT and belt.height == 2 * CONVEYOR_ROLLER
    assert "sym_conveyor_screw" in screw.svg
    assert screw.svg != belt.svg


def test_the_two_conveyors_put_their_nozzles_where_their_rows_do():
    """Check that a belt is fed and discharged at its ends and a screw top and bottom."""
    belt = default_registry.get("conveyor")
    screw = default_registry.get("conveyor", "screw")
    assert belt.ports["feed"][0] == 0.0
    assert set(belt.port_faces["feed"]) == {"W", "N"}
    assert set(belt.port_faces["discharge"]) == {"E", "S"}
    # The screw's home faces are the other pair: in on top, out underneath.
    assert screw.ports["feed"][1] == 0.0
    assert screw.ports["discharge"][1] == SCREW_HEIGHT
    assert set(screw.port_faces["feed"]) == {"N", "W"}
    assert set(screw.port_faces["discharge"]) == {"S", "E"}


def test_a_screw_too_short_for_one_turn_is_refused_in_its_own_words():
    """Check that a screw and a belt below their minimum are refused in their own words."""
    with pytest.raises(ValueError, match=r"screw conveyor can be drawn"):
        U.Conveyor("SC-301", variant="screw", length=SCREW_MIN_LENGTH - 1)
    with pytest.raises(ValueError, match=r"rollers.*would overlap"):
        U.Conveyor("BC-301", length=CONVEYOR_MIN_LENGTH - 1)
    assert U.Conveyor("SC-302", variant="screw", length=SCREW_MIN_LENGTH)


# ---------------------------------------------------------------------------
# The bucket elevators, ISO 10628-2 items 18.7 X8065 and 18.8 X8066
# ---------------------------------------------------------------------------


def test_the_elevators_are_the_boxes_their_rows_draw():
    """Check the two elevators' boxes, numbers and pulleys."""
    straight = default_registry.get("elevator")
    z = default_registry.get("elevator", "z_form")
    assert (straight.width, straight.height) == (80.0, 120.0)
    assert (z.width, z.height) == (200.0, 120.0)
    assert (straight.iso_reg, z.iso_reg) == ("X8065", "X8066")
    # Two pulleys on the straight lift, four on the Z-form.
    assert straight.svg.count("<circle") == 2
    assert z.svg.count("<circle") == 4


def test_an_elevator_takes_material_in_low_and_delivers_it_high():
    """Check that each elevator's feed is below its discharge and it is gravity-fixed."""
    for variant in ("default", "z_form"):
        sym = default_registry.get("elevator", variant)
        assert sym.ports["feed"][1] > sym.ports["discharge"][1], (
            f"elevator/{variant} draws its feed above its discharge"
        )
        assert sym.gravity_fixed, f"elevator/{variant} may be turned upside down"


def test_the_straight_lift_still_offers_the_vertical_chutes_row_18_7_ticks():
    """Check that the straight elevator also offers the top feed and bottom discharge."""
    sym = default_registry.get("elevator")
    assert set(sym.port_faces["feed"]) == {"W", "N"}
    assert set(sym.port_faces["discharge"]) == {"E", "S"}
    assert sym.port_faces["feed"]["N"][1] == 0.0
    assert sym.port_faces["discharge"]["S"][1] == sym.height


def test_an_elevator_is_not_sized_by_a_length():
    """Check that an elevator takes no ``length=``."""
    with pytest.raises(TypeError):
        U.Elevator("BE-301", length=140)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "build",
    [
        lambda: U.Conveyor("SC-301", variant="screw", length=140),
        lambda: U.Elevator("BE-301", variant="default"),
        lambda: U.Elevator("BE-301", variant="z_form"),
    ],
    ids=["screw conveyor", "elevator", "z-form elevator"],
)
def test_a_screw_conveyor_or_an_elevator_renders_and_meets_its_streams(build):
    fs = Flowsheet("solids")
    feed, out = fs.add(U.Feed("IN")), fs.add(U.Product("OUT"))
    unit = fs.add(build())
    fs.connect(feed.outlet, unit.feed).properties = {"Flow (kg/h)": "4200"}
    fs.connect(unit.discharge, out.inlet).properties = {"Flow (kg/h)": "4200"}
    assert fs.validate() == []
    assert "<svg" in fs.to_svg()
