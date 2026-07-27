"""The belt conveyor: the one symbol drawn to a length the drawing gives it.

The defect these guard against is the reason it is built rather than scaled. An
ordinary symbol is drawn once and placed with ``<use width= height=>`` against a
fixed ``viewBox``, so a box of a different aspect ratio scales it unevenly --
which would draw a conveyor's rollers as ellipses, wider the longer the belt. So
the assertions here are about the rollers being the *same circle* at every
length and about the scale factor being exactly 1, not about the box getting
wider, which would pass either way.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from test_symbol_invariants import GEOM_TOL, _collect_segments, _nearest_distance

from pfd import Flowsheet, units as U
from pfd.portgeom import port_point, resolve_size, symbol_to_box
from pfd.render.symbols import (
    CONVEYOR_LENGTH,
    CONVEYOR_MIN_LENGTH,
    CONVEYOR_ROLLER,
    conveyor_symbol,
    default_registry,
)

SVG = "{http://www.w3.org/2000/svg}"
R = CONVEYOR_ROLLER


def _sheet(lengths, **pin):
    """A flowsheet with one piped conveyor per length, rendered and parsed."""
    fs = Flowsheet("conveyors")
    for i, length in enumerate(lengths):
        feed = fs.add(U.Feed(f"IN-{i}"))
        conv = fs.add(U.Conveyor(f"BC-{i}", length=length))
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
# One number, not two.
# ---------------------------------------------------------------------------


def test_the_length_is_the_symbols_width_so_nothing_else_states_it():
    conveyor = U.Conveyor("BC-301", length=300)
    assert conveyor.width is None and conveyor.height is None
    assert default_registry.for_unit(conveyor).width == 300.0
    assert resolve_size(conveyor) == (300.0, 2 * R)


def test_a_quarter_turn_makes_the_length_the_height():
    conveyor = U.Conveyor("BC-301", length=300).pin(orientation=90)
    assert resolve_size(conveyor) == (2 * R, 300.0)


def test_a_size_given_as_width_or_height_is_refused():
    """Both would set the drawn box independently of the length and stretch the
    rollers with it, so both are a second answer to a settled question."""
    for kwargs in ({"width": 200}, {"height": 60}):
        with pytest.raises(ValueError, match=r"sized by length="):
            U.Conveyor("BC-301", **kwargs)


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
    from pfd.document import equipment_list

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
    from pfd.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Pump", "name": "P-101", "length": 200}]}
    with pytest.raises(SpecError, match=r"only a Conveyor takes 'length'"):
        Flowsheet.from_dict(spec)


def test_a_spec_length_below_the_minimum_names_the_entry():
    from pfd.spec import SpecError

    spec = {"name": "s", "units": [{"kind": "Conveyor", "name": "BC-301", "length": 10}]}
    with pytest.raises(SpecError, match=r"units\[0\] 'BC-301'"):
        Flowsheet.from_dict(spec)


def test_the_default_length_is_the_stencils_own_proportion():
    """The symbol is adapted from draw.io's "Drier (Roller Conveyor Belt)",
    whose rollers are r=10 centred 60 apart -- so 80 overall."""
    assert (CONVEYOR_ROLLER, CONVEYOR_LENGTH) == (10.0, 80.0)
    assert U.Conveyor("BC-301").length == CONVEYOR_LENGTH
