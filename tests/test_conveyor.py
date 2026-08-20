"""ISO 10628-2 group 18's solids handling: the conveyors and the elevators.

The two conveyors are the symbols drawn to a length the *drawing* gives them,
and the defect that guards against is the reason they are built rather than
scaled. An ordinary symbol is drawn once and placed with ``<use width= height=>``
against a fixed ``viewBox``, so a box of a different aspect ratio scales it
unevenly -- which would draw a belt's rollers as ellipses, wider the longer the
belt. So the assertions here are about the rollers being the *same circle* at
every length and about the scale factor being exactly 1, not about the box
getting wider, which would pass either way.

The screw conveyor is built for a related but different reason and the tests
below say which: it has no circle in it, and what a stretch ruins is the
*pitch* of its flight. The bucket elevators are not built to a size at all --
an elevator's lift is not a number a flowsheet states -- so what is checked
about them is their geometry against Table 2 and the end of the machine each
nozzle is on.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
from test_symbol_invariants import GEOM_TOL, _collect_segments, _nearest_distance

from pandid import Flowsheet, units as U
from pandid.portgeom import port_point, resolve_size, symbol_to_box
from pandid.render.symbols import (
    CONVEYOR_LENGTH,
    CONVEYOR_MIN_LENGTH,
    CONVEYOR_ROLLER,
    SCREW_HEIGHT,
    SCREW_MARGIN,
    SCREW_MIN_LENGTH,
    SCREW_MODULE,
    SCREW_PITCH,
    SCREW_REACH,
    SCREW_TURN,
    conveyor_symbol,
    default_registry,
    screw_conveyor_symbol,
)

SVG = "{http://www.w3.org/2000/svg}"
R = CONVEYOR_ROLLER


def _sheet(lengths, diameters=None, **pin):
    """A flowsheet with one piped conveyor per size, rendered and parsed.

    ``lengths`` may be plain runs or ``(length, diameter)`` pairs; ``diameters``
    pairs one diameter with every length instead, for the sweeps below.
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
# The hard requirement: the rollers are true circles at every length.
# ---------------------------------------------------------------------------

LENGTHS = [CONVEYOR_MIN_LENGTH, 80.0, 160.0, 300.0]


def test_the_rollers_are_the_same_circle_at_every_length():
    """Not "the box got wider": the roller *geometry* has to be identical, and
    the only thing free to differ is where the head roller sits."""
    _, root = _sheet(LENGTHS)
    defs = _defs(root)
    for length in LENGTHS:
        rollers = _ellipses(defs[f"sym_conveyor_L{length:g}"])
        assert rollers == [(R, R, R, R), (length - R, R, R, R)], f"length {length:g}"


def test_only_the_belt_run_grows():
    """The straight run between the rollers is the whole of what a longer
    conveyor adds, so belt + two roller radii accounts for the length exactly."""
    _, root = _sheet(LENGTHS)
    defs = _defs(root)
    for length in LENGTHS:
        runs = _belt_runs(defs[f"sym_conveyor_L{length:g}"])
        assert runs == [length - 2 * R, length - 2 * R], f"length {length:g}"


def test_the_placed_box_is_the_box_the_artwork_was_drawn_in():
    """The assertion the roundness actually rests on. ``<use>`` maps the
    definition's viewBox onto its own width/height, so equal width and height
    mean a scale of exactly 1 on both axes and a circle stays a circle on the
    page. A definition shared between two lengths would fail here."""
    _, root = _sheet(LENGTHS)
    defs, uses = _defs(root), _uses(root)
    for length in LENGTHS:
        sym_id = f"sym_conveyor_L{length:g}"
        _, _, vb_w, vb_h = (float(v) for v in defs[sym_id].get("viewBox").split())
        use = uses[f"#{sym_id}"]
        assert (float(use.get("width")), float(use.get("height"))) == (vb_w, vb_h)


def test_a_long_conveyor_and_a_short_one_draw_the_same_roller_ink():
    """Byte-for-byte, at the tail end: the two definitions differ only where the
    head roller and the far end of the belt are."""
    short, long = conveyor_symbol(CONVEYOR_MIN_LENGTH), conveyor_symbol(400.0)
    tail = f'<ellipse cx="{R:g}" cy="{R:g}" rx="{R:g}" ry="{R:g}"'
    assert tail in short.svg and tail in long.svg
    assert short.height == long.height == 2 * R


def test_every_port_lands_on_drawn_ink_at_every_legal_length():
    """Including on the roller circles, which is where three of the four sit."""
    for length in [*LENGTHS, 41.0, 1000.0]:
        sym = conveyor_symbol(length)
        segments = _collect_segments(sym.svg)
        for name, faces in sym.port_faces.items():
            for face, point in faces.items():
                distance = _nearest_distance(point, segments)
                assert distance <= GEOM_TOL, f"{name}/{face} at length {length:g}"


# ---------------------------------------------------------------------------
# The second dimension: the roller, set independently of the run.
#
# The run and the roller are two dimensions of the machine and neither is
# worked out from the other, so the assertions below sweep the *combinations*
# rather than one axis at a time. What has to hold at every one of them is what
# held at every length before: a true circle drawn at a scale of exactly 1.
# ---------------------------------------------------------------------------

DIAMETERS = [8.0, 2 * R, 45.0, 120.0]
#: Long enough for the widest roller above, so the sweep is a rectangle rather
#: than a triangle: every length pairs with every diameter.
COMBOS = [(length, d) for length in (240.0, 400.0) for d in DIAMETERS]


def _sym_id(length, diameter=None):
    """The definition id a belt of this size is drawn under."""
    tail = "" if diameter in (None, 2 * R) else f"_D{diameter:g}"
    return f"sym_conveyor_L{length:g}{tail}"


@pytest.mark.parametrize("length,diameter", COMBOS)
def test_the_rollers_are_true_circles_at_every_run_and_roller(length, diameter):
    """The hard requirement, now over both dimensions.

    Two things together make a circle on the page, and both are checked here.
    The drawn ellipse has to have rx == ry -- and it has to be *placed* at the
    same scale on both axes, which is what ``<use width= height=>`` matching the
    definition's viewBox says. Either alone would pass on a drawing the other
    ruins.
    """
    _, root = _sheet([(length, diameter)])
    definition = _defs(root)[_sym_id(length, diameter)]
    r = diameter / 2
    assert _ellipses(definition) == [(r, r, r, r), (length - r, r, r, r)]
    _, _, vb_w, vb_h = (float(v) for v in definition.get("viewBox").split())
    use = _uses(root)[f"#{_sym_id(length, diameter)}"]
    assert (float(use.get("width")), float(use.get("height"))) == (vb_w, vb_h)
    assert (vb_w, vb_h) == (length, diameter)


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
    """The whole of "built to size" in one assertion: change the run and the
    rollers are the same circles; change the roller and the run is the same
    run. A drawing scaled into a box could hold neither."""
    _, root = _sheet([240.0, 400.0], diameters=DIAMETERS)
    defs = _defs(root)
    for length in (240.0, 400.0):
        for diameter in DIAMETERS:
            definition = defs[_sym_id(length, diameter)]
            # The roller is the one asked for, at either run...
            assert {e[2] for e in _ellipses(definition)} == {diameter / 2}
            # ...and the straight run is the whole of what is left over, at
            # either roller.
            assert _belt_runs(definition) == [length - diameter] * 2


def test_the_default_roller_is_the_stencils_own_and_draws_what_it_always_drew():
    """The default has to reproduce the old drawing exactly, or every sheet
    already issued moves. Byte for byte, including the definition's id."""
    assert conveyor_symbol(300.0) == conveyor_symbol(300.0, 2 * R)
    assert conveyor_symbol(300.0).id_suffix == "_L300"
    assert U.Conveyor("BC-301").diameter == 2 * R


def test_a_belt_on_bigger_rollers_needs_a_longer_bed():
    """The minimum is two roller diameters and always was; what changed is that
    the roller is now a number the author picks, so the bound moves with it."""
    assert U.Conveyor("BC-301", length=90, diameter=45).length == 90
    with pytest.raises(ValueError, match=r"Use length=90 or more"):
        U.Conveyor("BC-302", length=89, diameter=45)


def test_growing_the_roller_under_a_belt_too_short_for_it_is_refused():
    """The pair is checked from both sides. Setting the roller is as able to
    break the rule as setting the run, and it is refused in the same sentence
    rather than drawing two overlapping circles."""
    conveyor = U.Conveyor("BC-301", length=90)
    conveyor.diameter = 45
    with pytest.raises(ValueError, match=r"rollers.*would overlap"):
        conveyor.diameter = 50
    assert conveyor.diameter == 45


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
    """Two conveyors of the same run but different rollers are two drawings, so
    a definition keyed on the run alone would hand one of them the other's."""
    _, root = _sheet([(240.0, 45.0), (240.0, 45.0), (240.0, None), (400.0, 45.0)])
    ids = sorted(i for i in _defs(root) if i.startswith("sym_conveyor"))
    assert ids == ["sym_conveyor_L240", "sym_conveyor_L240_D45", "sym_conveyor_L400_D45"]


def test_a_conveyor_round_trips_through_a_spec_with_its_roller():
    fs = Flowsheet("cake handling")
    fs.add(U.Conveyor("BC-301", length=300, diameter=45))
    fs.add(U.Conveyor("BC-302", length=300))
    spec = fs.to_dict()
    assert spec["units"][0]["diameter"] == 45.0
    # The default is left out: writing it down would rewrite every conveyor
    # entry ever exported to say what its absence already says.
    assert "diameter" not in spec["units"][1]
    rebuilt = Flowsheet.from_dict(spec)
    assert [u.diameter for u in rebuilt.units] == [45.0, 2 * R]
    assert rebuilt.to_dict() == spec


def test_a_diameter_on_something_that_is_not_a_conveyor_is_refused():
    from pandid.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Pump", "name": "P-101", "diameter": 40}]}
    with pytest.raises(SpecError, match=r"only a Conveyor takes 'diameter'"):
        Flowsheet.from_dict(spec)


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
    """Both set the drawn box, which a quarter turn swaps and the machine's own
    two dimensions do not, so both are refused -- and the refusal says which
    keyword the number the author typed actually belongs on."""
    with pytest.raises(ValueError, match=r"sized by length=") as excinfo:
        U.Conveyor("BC-301", **kwargs)
    assert names in str(excinfo.value)


def test_the_roller_is_not_the_box_height_when_the_belt_is_stood_on_end():
    """Why the second dimension is ``diameter=`` and not ``height=``. A quarter
    turn puts the *run* on the box's height and the rollers on its width; the
    machine's own numbers are the same either way up."""
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
    """The rollers touch there and the belt still has a run, so it is a drawing
    rather than the degenerate case the rule is about."""
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
    """The stream is drawn to the port point, so a port off the ink is a line
    ending in whitespace. Checked against the artwork put through the same
    transform the ``<use>`` applies."""
    fs, _ = _sheet([220.0], **pin)
    conveyor = next(u for u in fs.units if u.kind == "conveyor")
    segments = _world_segments(conveyor)
    for name in ("feed", "discharge"):
        point = port_point(conveyor, conveyor.frame, name)
        assert _nearest_distance(point, segments) <= GEOM_TOL, name


def test_conveyors_of_one_length_share_a_definition_and_others_do_not():
    _, root = _sheet([160.0, 160.0, 300.0])
    ids = sorted(i for i in _defs(root) if i.startswith("sym_conveyor"))
    assert ids == ["sym_conveyor_L160", "sym_conveyor_L300"]


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


def test_a_length_on_something_that_is_not_a_conveyor_is_refused():
    from pandid.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Pump", "name": "P-101", "length": 200}]}
    with pytest.raises(SpecError, match=r"only a Conveyor takes 'length'"):
        Flowsheet.from_dict(spec)


def test_a_spec_length_below_the_minimum_names_the_entry():
    from pandid.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Conveyor", "name": "BC-301", "length": 10}]}
    with pytest.raises(SpecError, match=r"units\[0\] 'BC-301'"):
        Flowsheet.from_dict(spec)


def test_the_default_length_is_the_stencils_own_proportion():
    """The symbol is adapted from draw.io's "Drier (Roller Conveyor Belt)",
    whose rollers are r=10 centred 60 apart -- so 80 overall."""
    assert (CONVEYOR_ROLLER, CONVEYOR_LENGTH) == (10.0, 80.0)
    assert U.Conveyor("BC-301").length == CONVEYOR_LENGTH


# ---------------------------------------------------------------------------
# The screw conveyor, ISO 10628-2 item 18.5 X8063
# ---------------------------------------------------------------------------


def _screw_turns(length, diameter=SCREW_HEIGHT):
    """Each turn of the flight, as the list of points it is drawn through.

    The axis is the path's first run and is skipped: what these tests are
    about is the turns on it.
    """
    svg = screw_conveyor_symbol(length, diameter).svg
    body = re.search(r'<path d="(M 0 .*?)"', svg).group(1)
    runs = [r.strip() for r in body.split("M ") if r.strip()]
    return [
        [tuple(float(v) for v in p.split()) for p in run.split("L ") if p.strip()]
        for run in runs[1:]
    ]


def test_the_screw_is_the_construction_row_18_5_draws():
    """Measured off row 18.5 in grid modules: a casing 15 M x 6 M, the screw's
    axis along it, and turns 4 M wide reaching 2 M either side of that axis,
    starting 2 M inside the tail and repeating every 7 M.

    Written here in the module the drawing is built at, so a reader with the
    standard can count dots. The casing's *length* is not among them: it is
    whatever the author asks for, and 15 M is only what the row happens to draw.
    """
    assert SCREW_HEIGHT == 6 * SCREW_MODULE
    assert (SCREW_TURN, SCREW_REACH) == (4 * SCREW_MODULE, 2 * SCREW_MODULE)
    assert (SCREW_PITCH, SCREW_MARGIN) == (7 * SCREW_MODULE, 2 * SCREW_MODULE)
    # Row 18.5's own casing carries exactly the two turns it draws.
    assert len(_screw_turns(15 * SCREW_MODULE)) == 2


@pytest.mark.parametrize("length", [SCREW_MIN_LENGTH, 80, 120, 200, 400])
def test_a_turn_of_the_flight_is_the_same_turn_at_every_length(length):
    """The screw's answer to the belt's rollers.

    A screw has no circle in it, so nothing here would come out an ellipse --
    what a stretched drawing would get wrong is the *pitch*, and a 400-unit
    screw showing the same two turns as an 80-unit one reads as a flight every
    four metres. So the turns keep their size and the casing gets more of them.
    """
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
    # The last one leaves the head's clear casing rather than running out
    # through the end wall.
    assert max(p[0] for p in turns[-1]) <= length - SCREW_MARGIN + GEOM_TOL


def test_a_longer_screw_gets_more_turns_rather_than_longer_ones():
    counts = [len(_screw_turns(n)) for n in (40, 80, 200, 400)]
    assert counts == sorted(counts) and counts[0] < counts[-1]


BORES = [12.0, SCREW_HEIGHT, 45.0, 90.0]


@pytest.mark.parametrize("diameter", BORES)
def test_a_wider_screw_keeps_its_pitch_and_its_flight_fills_the_casing(diameter):
    """The screw's answer to the belt's second dimension, and it cuts the
    drawing in half. *Along the axis* nothing moves -- the turn is the same
    4 M, the pitch the same 7 M, the count the same count -- because a wider
    machine does not turn its flight more often. *Across it* the flight follows
    the bore, because the flight is the screw and a screw fills its trough.
    """
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
    """Unlike the belt, whose minimum is two roller diameters and moves with
    the roller. Everything bounding a screw's length -- the turn and the clear
    casing at each end -- is measured along the axis, which the bore does not
    touch."""
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
    """``_BUILT_TO_SIZE`` was keyed ``("conveyor", None)`` while a conveyor was
    a belt and nothing else, and a kind-wide key would have handed the screw the
    belt's builder -- a belt drawn at the screw's length, under the screw's tag.

    Checked through ``for_unit``, which is what a sheet actually calls.
    """
    screw = default_registry.for_unit(U.Conveyor("SC-301", variant="screw", length=140))
    belt = default_registry.for_unit(U.Conveyor("BC-301", length=140))
    assert screw.width == belt.width == 140
    assert screw.height == SCREW_HEIGHT and belt.height == 2 * CONVEYOR_ROLLER
    assert "sym_conveyor_screw" in screw.svg
    assert screw.svg != belt.svg


def test_the_two_conveyors_put_their_nozzles_where_their_rows_do():
    """A belt is open and is loaded and unloaded at its two ends; a screw runs
    enclosed and is loaded and discharged through spouts. Table 2 ticks them
    that way round, and so does this.
    """
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
    """And not in the belt's. The two minima are equal by arithmetic, so only
    the sentence tells an author which machine ran out of room.
    """
    with pytest.raises(ValueError, match=r"screw conveyor can be drawn"):
        U.Conveyor("SC-301", variant="screw", length=SCREW_MIN_LENGTH - 1)
    with pytest.raises(ValueError, match=r"rollers.*would overlap"):
        U.Conveyor("BC-301", length=CONVEYOR_MIN_LENGTH - 1)
    assert U.Conveyor("SC-302", variant="screw", length=SCREW_MIN_LENGTH)


def test_a_screw_conveyor_renders_and_meets_its_streams():
    fs = Flowsheet("screw")
    feed, out = fs.add(U.Feed("IN")), fs.add(U.Product("OUT"))
    sc = fs.add(U.Conveyor("SC-301", variant="screw", length=140))
    fs.connect(feed.outlet, sc.feed).properties = {"Flow (kg/h)": "4200"}
    fs.connect(sc.discharge, out.inlet).properties = {"Flow (kg/h)": "4200"}
    assert fs.validate() == []
    assert "<svg" in fs.to_svg()


# ---------------------------------------------------------------------------
# The bucket elevators, ISO 10628-2 items 18.7 X8065 and 18.8 X8066
# ---------------------------------------------------------------------------


def test_the_elevators_are_the_boxes_their_rows_draw():
    """Row 18.7's casing is 8 M x 12 M and row 18.8's Z is 20 M x 12 M, both on
    the 10-unit module ``iso_parts`` states. Same height, because they are the
    same machine.
    """
    straight = default_registry.get("elevator")
    z = default_registry.get("elevator", "z_form")
    assert (straight.width, straight.height) == (80.0, 120.0)
    assert (z.width, z.height) == (200.0, 120.0)
    assert (straight.iso_reg, z.iso_reg) == ("X8065", "X8066")
    # Four pulleys on the Z-form against the straight lift's two: one at each
    # end of the belt loop, and one at each corner it turns through.
    assert straight.svg.count("<circle") == 2
    assert z.svg.count("<circle") == 4


def test_an_elevator_takes_material_in_low_and_delivers_it_high():
    """The whole of what the machine is for, and the one thing a reader must be
    able to see. Both variants: in at the boot, out at the head, so the feed
    sits below the discharge on the drawn box.
    """
    for variant in ("default", "z_form"):
        sym = default_registry.get("elevator", variant)
        assert sym.ports["feed"][1] > sym.ports["discharge"][1], (
            f"elevator/{variant} draws its feed above its discharge"
        )
        assert sym.gravity_fixed, f"elevator/{variant} may be turned upside down"


def test_the_straight_lift_still_offers_the_vertical_chutes_row_18_7_ticks():
    """The home nozzles depart from the row -- see ``symbols._BUCKET_ELEVATOR``
    for why -- and the departure is only about which face is *default*. Table
    2's own two directions are still reachable.
    """
    sym = default_registry.get("elevator")
    assert set(sym.port_faces["feed"]) == {"W", "N"}
    assert set(sym.port_faces["discharge"]) == {"E", "S"}
    assert sym.port_faces["feed"]["N"][1] == 0.0
    assert sym.port_faces["discharge"]["S"][1] == sym.height


def test_an_elevator_is_not_sized_by_a_length():
    """A conveyor's run is a number an author states; a lift is not, so there
    is nothing to pass and both drawings are fixed.
    """
    with pytest.raises(TypeError):
        U.Elevator("BE-301", length=140)  # type: ignore[call-arg]


@pytest.mark.parametrize("variant", ["default", "z_form"])
def test_an_elevator_renders_and_meets_its_streams(variant):
    fs = Flowsheet("lift")
    feed, out = fs.add(U.Feed("IN")), fs.add(U.Product("OUT"))
    be = fs.add(U.Elevator("BE-301", variant=variant))
    fs.connect(feed.outlet, be.feed).properties = {"Flow (kg/h)": "4200"}
    fs.connect(be.discharge, out.inlet).properties = {"Flow (kg/h)": "4200"}
    assert fs.validate() == []
    assert "<svg" in fs.to_svg()
