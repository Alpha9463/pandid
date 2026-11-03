"""Invariants for the intent (Pin) / result (Frame) geometry model."""

import itertools
from dataclasses import replace

import pytest

from pandid import Flowsheet, units as U
from pandid.portgeom import pinned_x, pinned_y, port_offset

from _layout_cases import nozzle_of


def _small_auto():
    fs = Flowsheet("auto")
    feed = fs.add(U.Feed("F"))
    rx = fs.add(U.Reactor("R"))
    sep = fs.add(U.Separator("V"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, rx.feed)
    fs.connect(rx.outlet, sep.feed)
    fs.connect(sep.liquid, prod.inlet)
    return fs


def test_layout_idempotent():
    """Check that laying a sheet out twice gives identical frames."""
    fs = _small_auto()
    fs.layout()
    first = {
        u.name: (u.frame.x, u.frame.y, u.frame.w, u.frame.h, u.frame.col, u.frame.row)
        for u in fs.units
    }
    fs.layout()
    second = {
        u.name: (u.frame.x, u.frame.y, u.frame.w, u.frame.h, u.frame.col, u.frame.row)
        for u in fs.units
    }
    assert first == second


def test_pin_honored_exactly():
    """A pinned (x, y) must survive layout untouched in the resolved frame."""
    fs = Flowsheet("pinned")
    a = fs.add(U.Reactor("R")).pin(x=333, y=222)
    b = fs.add(U.Separator("V"))
    fs.connect(a.outlet, b.feed)
    fs.layout()
    assert a.frame.x == 333
    assert a.frame.y == 222


def test_mirror_consistent_and_rendered():
    """Check that renderer and router put a mirrored valve's ports on the same side."""
    from pandid.portgeom import port_point, port_anchor

    fs = Flowsheet("mirror")
    feed = fs.add(U.Feed("F")).pin(x=50, y=25)
    valve = fs.add(U.Valve("V")).pin(x=200, y=0, mirrored=True)
    prod = fs.add(U.Product("P")).pin(x=400, y=25)
    fs.connect(feed.outlet, valve.inlet)
    s2 = fs.connect(valve.outlet, prod.inlet)
    fs.layout()

    f = valve.frame
    # Valve symbol has inlet at local x=0; mirrored, it must sit on the RIGHT.
    pp_in = port_point(valve, f, "inlet")
    pa_in = port_anchor(valve, f, "inlet")
    assert pp_in[0] > f.cx, "mirrored inlet should flip to the right half"
    # Renderer (port_point) and router (port_anchor) agree on the side.
    assert (pp_in[0] - f.cx) * (pa_in[0] - f.cx) >= 0

    # The rendered path for valve.outlet must begin exactly at its port_point.
    svg = fs.to_svg()
    op = port_point(valve, valve.frame, "outlet")
    assert f"M {op[0]},{op[1]}" in svg
    assert s2.route is not None


# ---------------------------------------------------------------------------
# Reading an intent back: pinned_x / pinned_y
# ---------------------------------------------------------------------------


def _pinned_mixer(**pin):
    fs = Flowsheet("pinned")
    m = fs.add(U.Mixer("M-1", n_inlets=2))
    m.pin(**pin)
    return m


def test_a_pinned_coordinate_is_the_sum_the_examples_used_to_write():
    """Check that ``pinned_x`` and ``pinned_y`` are the pin plus the port offset."""
    m = _pinned_mixer(x=100, y=200)
    for axis, fn, index in (("x", pinned_x, 0), ("y", pinned_y, 1)):
        assert fn(m, "in_1") == getattr(m.pin_, axis) + port_offset(m, "in_1")[index]
        assert fn(m) == getattr(m.pin_, axis)


def test_a_quarter_turn_moves_the_nozzle_it_is_read_from():
    """Check that a quarter turn moves the coordinate read from a nozzle."""
    upright = _pinned_mixer(x=100, y=200)
    turned = _pinned_mixer(x=100, y=200, orientation=90)
    assert (pinned_x(upright, "in_1"), pinned_y(upright, "in_1")) != (
        pinned_x(turned, "in_1"),
        pinned_y(turned, "in_1"),
    )


def test_an_unpinned_unit_says_so_rather_than_raising_from_inside_an_expression():
    """Check that reading an unpinned unit's pin raises a ``ValueError`` naming it."""
    fs = Flowsheet("bare")
    m = fs.add(U.Mixer("M-9", n_inlets=2))
    for fn in (pinned_x, pinned_y):
        with pytest.raises(ValueError, match="M-9 has not been pinned"):
            fn(m)


def test_a_grid_pinned_unit_says_the_solver_has_not_decided_yet():
    """Check that reading a coordinate from a col/row pin is refused."""
    m = _pinned_mixer(col=2, row=1)
    with pytest.raises(ValueError, match="pinned by col/row"):
        pinned_x(m)


def test_one_axis_pinned_answers_for_that_axis_and_refuses_the_other():
    """A pin may set either axis, so the two functions answer independently."""
    m = _pinned_mixer(x=100)
    assert pinned_x(m) == 100
    with pytest.raises(ValueError, match="not by an absolute y"):
        pinned_y(m)


# ---------------------------------------------------------------------------
# A port-pinned axis is a relation, not a coordinate
# ---------------------------------------------------------------------------

RUN_Y = 440.0


def _valve_on_a_run():
    """Return a run of one valve between two flags."""
    fs = Flowsheet("run")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    prod = fs.add(U.Product("Q"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    return fs, valve


def test_a_later_turn_leaves_a_port_pinned_nozzle_on_its_run():
    """Check that a later turn keeps a port-pinned nozzle on its run."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    fs.layout()
    assert nozzle_of(valve, "inlet")[1] == RUN_Y

    valve.pin(orientation=90)
    fs.layout()
    assert nozzle_of(valve, "inlet")[1] == RUN_Y


def test_a_later_mirror_leaves_a_port_pinned_nozzle_on_its_run():
    """Check that a later mirror keeps a port-pinned nozzle where it was drawn."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", x=300.0, y=RUN_Y)
    fs.layout()
    was = nozzle_of(valve, "inlet")

    valve.pin(mirrored=True)
    fs.layout()
    assert nozzle_of(valve, "inlet") == was


def test_piping_the_nozzle_from_another_face_leaves_it_where_it_was_pinned():
    """Check that moving a port-pinned nozzle to another face keeps its pinned elevation."""
    fs = Flowsheet("faces")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    tank.pin(port="in_1", y=RUN_Y)
    fs.layout()
    assert nozzle_of(tank, "in_1")[1] == RUN_Y

    tank.nozzle("in_1", "N")
    fs.layout()
    assert nozzle_of(tank, "in_1")[1] == RUN_Y


def test_resizing_the_box_leaves_a_port_pinned_nozzle_where_it_was_pinned():
    """Check that resizing a unit keeps a port-pinned nozzle at its pinned elevation."""
    fs = Flowsheet("resized")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    tank.pin(port="in_1", y=RUN_Y)
    fs.layout()

    tank.height = 200.0
    fs.layout()
    assert nozzle_of(tank, "in_1")[1] == RUN_Y


def _tank_the_selector_wants_to_move(port_pin: bool):
    """Return a laid-out tank fed from above, pinned at its ``in_1`` nozzle or its corner."""
    fs = Flowsheet("face")
    feed = fs.add(U.Feed("F")).pin(x=300.0, y=50.0)
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P")).pin(x=800.0, y=RUN_Y)
    fs.connect(feed.outlet, tank.in_1)
    fs.connect(tank.outlet, prod.inlet)
    if port_pin:
        tank.pin(port="in_1", x=300.0, y=RUN_Y)
    else:
        tank.pin(x=300.0, y=RUN_Y)
    fs.layout()
    return fs, tank


def test_the_engine_does_not_pick_a_face_out_from_under_a_pinned_nozzle():
    """Check that face selection moves a corner-pinned nozzle but not a port-pinned one."""
    from pandid.portgeom import port_faces

    fs, loose = _tank_the_selector_wants_to_move(port_pin=False)
    assert loose.frame is not None
    assert len(port_faces(loose, "in_1", loose.frame)) > 1
    assert loose.frame.port_faces.get("in_1") == "N"
    assert nozzle_of(loose, "in_1") != (300.0, RUN_Y)

    fs, tank = _tank_the_selector_wants_to_move(port_pin=True)
    assert nozzle_of(tank, "in_1") == (300.0, RUN_Y)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_a_pinned_nozzle_may_still_be_sent_to_a_face_by_name():
    """Check that a port pin and a face named by ``nozzle()`` are honoured together."""
    from pandid.portgeom import resolve_port

    fs, tank = _tank_the_selector_wants_to_move(port_pin=True)
    tank.nozzle("in_1", "N")
    fs.layout()
    assert tank.frame is not None
    assert resolve_port(tank, tank.frame, "in_1").face == "N"
    assert nozzle_of(tank, "in_1") == (300.0, RUN_Y)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_only_the_pinned_nozzle_is_taken_out_of_the_engine_s_hands():
    """Check that face selection still chooses for a nozzle the port pin does not name."""
    fs = Flowsheet("conveyor")
    src = fs.add(U.Feed("S")).pin(x=400.0, y=60.0)
    belt = fs.add(U.Conveyor("CV-1"))
    dst = fs.add(U.Product("D")).pin(x=900.0, y=600.0)
    fs.connect(src.outlet, belt.feed)
    fs.connect(belt.discharge, dst.inlet)
    belt.pin(port="feed", x=400.0, y=RUN_Y)
    fs.layout()

    assert belt.frame is not None
    assert belt.frame.port_faces == {"discharge": "E"}
    assert nozzle_of(belt, "feed") == (400.0, RUN_Y)


def test_a_pin_reads_back_as_the_corner_it_always_did():
    """Check that ``pin_`` reads a port pin back as the corner it implies."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    assert valve.pin_ is not None
    assert valve.pin_.y is not None
    assert valve.pin_.y + port_offset(valve, "inlet")[1] == RUN_Y
    assert pinned_y(valve, "inlet") == RUN_Y

    valve.pin(orientation=90)
    assert pinned_y(valve, "inlet") == RUN_Y


def test_the_nozzle_a_coordinate_was_measured_to_is_remembered_per_axis():
    """Check that each axis keeps the nozzle its coordinate was measured to."""
    fs = Flowsheet("axes")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    tank.pin(port="in_1", x=300.0)
    tank.pin(y=100.0)
    assert pinned_x(tank, "in_1") == 300.0
    assert pinned_y(tank) == 100.0

    # A turn moves the nozzle within the box, so the corner follows on the
    # axis that was pinned by the nozzle and holds still on the other.
    tank.pin(orientation=90)
    assert pinned_x(tank, "in_1") == 300.0
    assert pinned_y(tank) == 100.0


def test_pinning_the_corner_afterwards_drops_the_relation():
    """Check that ``port=None`` turns a port pin into a corner pin a turn leaves alone."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    valve.pin(port=None, y=RUN_Y)
    assert pinned_y(valve) == RUN_Y

    valve.pin(orientation=90)
    assert pinned_y(valve) == RUN_Y


def test_a_written_sheet_carries_the_relation_and_not_its_consequence():
    """Check that ``to_dict`` writes a port pin as its port and coordinate."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    written = fs.to_dict()
    pin = next(u["pin"] for u in written["units"] if u["name"] == "HV-1")
    assert pin == {"y": RUN_Y, "port": "inlet"}

    back = Flowsheet.from_dict(written)
    read = next(u for u in back.units if u.name == "HV-1")
    assert pinned_y(read, "inlet") == RUN_Y
    read.pin(orientation=90)
    assert pinned_y(read, "inlet") == RUN_Y


@pytest.mark.parametrize(
    "place, written_pin",
    [
        # One nozzle for every stated axis, which is how ``pin()`` takes it.
        (lambda u: u.pin(port="in_1", x=300.0, y=100.0), {"x": 300.0, "y": 100.0, "port": "in_1"}),
        # The axis-by-axis mapping, for a pin built out of two calls: only
        # one of the two coordinates was measured to a nozzle...
        (
            lambda u: (u.pin(port="in_1", x=300.0), u.pin(y=100.0)),
            {"x": 300.0, "y": 100.0, "port": {"x": "in_1"}},
        ),
        # ...or the two were measured to different ones, which no shorthand
        # can say and which is not a contradiction: two calls, two nozzles.
        # Named by the alias ``outlet`` and written under the name the unit
        # holds it by, so the file says something the reader can resolve.
        (
            lambda u: (u.pin(port="in_1", x=300.0), u.pin(port="outlet", y=100.0)),
            {"x": 300.0, "y": 100.0, "port": {"x": "in_1", "y": "out_1"}},
        ),
    ],
    ids=["one-nozzle", "one-axis", "two-nozzles"],
)
def test_a_written_pin_reads_back_as_the_pin_that_was_written(place, written_pin):
    """Check that a written port pin reads back as the same pin, before and after a turn."""
    # Local, so this module still collects against a tree without it and
    # the tests that need it are the only ones that fail there.
    from pandid.portgeom import pin_intent

    fs = Flowsheet("written")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    place(tank)

    written = fs.to_dict()
    assert written["units"][0]["pin"] == written_pin
    assert Flowsheet.from_dict(written).to_dict() == written

    read = Flowsheet.from_dict(written).units[0]
    assert pin_intent(read) == pin_intent(tank)
    assert read.pin_ == tank.pin_

    # And it is still a relation on the far side, not a number that was
    # right once: the coordinate the author gave is where the nozzle they
    # named sits, before the turn and after it.
    def where(unit) -> dict[str, float]:
        return {
            axis: (pinned_x if axis == "x" else pinned_y)(unit, port)
            for axis, (port, _) in pin_intent(unit).items()
        }

    asked = {axis: want for axis, (_, want) in pin_intent(tank).items()}
    assert where(read) == asked
    read.pin(orientation=90)
    assert where(read) == asked


def test_a_pin_read_back_refuses_to_be_edited_in_place():
    """Check that ``pin_`` refuses assignment however the unit is pinned."""
    fs, valve = _valve_on_a_run()
    for place in (lambda: valve.pin(x=300.0), lambda: valve.pin(port="inlet", y=RUN_Y)):
        place()
        assert valve.pin_ is not None
        with pytest.raises(AttributeError):
            valve.pin_.x = 999.0  # type: ignore[misc]


def _codes(fs):
    fs.layout()
    fs.route()
    return [i.code for i in fs.validate()]


def _drum_run(name: str) -> tuple[Flowsheet, U.Vessel]:
    """Build a feed, a drum ``V-1`` and a product in one line.

    Parameters
    ----------
    name : str
        Sheet name.

    Returns
    -------
    tuple[Flowsheet, Vessel]
        The unlaid sheet and its drum.
    """
    fs = Flowsheet(name)
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    return fs, vessel


def test_a_placement_the_sheet_did_not_honour_is_reported():
    """Check that a unit moved after layout is reported as ``pin-not-honored``."""
    fs, vessel = _drum_run("moved-after-the-solve")
    vessel.pin(x=300.0, y=300.0)
    fs.layout()
    fs.route()
    assert vessel.frame is not None
    assert (vessel.frame.x, vessel.frame.y) == (300.0, 300.0)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]

    vessel.frame = replace(vessel.frame, x=900.0)

    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert len(said) == 1, said
    assert "V-1 was pinned x=300 and is drawn at 900, 600 away" in said[0]
    assert "something moved this unit after the solver read the pin" in said[0]


def test_a_grid_pin_the_sheet_did_not_honour_is_reported():
    """Check that an attached balloon's unread col/row pin is reported."""
    fs, vessel = _drum_run("ranked")
    fs.add_instrument("LI", 1, sensing=vessel).pin(col=3, row=1)

    assert "pin-not-honored" in _codes(fs)
    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert len(said) == 2, said
    assert any("col=3" in m for m in said) and any("row=1" in m for m in said)


def test_a_grid_pin_the_sheet_honoured_is_not_reported():
    """Check that a free balloon placed by its col/row pin is not reported."""
    fs, _ = _drum_run("ranked-ok")
    fs.add_instrument("XI", 9).pin(col=3, row=1)

    assert "pin-not-honored" not in _codes(fs)


def test_a_rank_an_absolute_coordinate_supersedes_is_not_reported():
    """Check that a rank overridden by a coordinate on its axis is not reported."""
    fs, _ = _drum_run("superseded")
    balloon = fs.add_instrument("XI", 9)
    balloon.pin(col=7, x=222.0, row=0, y=333.0)

    assert "pin-not-honored" not in _codes(fs)
    # And the sheet really is right: the superseded rank is not on the frame
    # either, so this is silence about a correct drawing and not silence
    # about a rank that was quietly dropped.
    assert balloon.frame is not None
    assert (balloon.frame.x, balloon.frame.y) == (222.0, 333.0)
    assert (balloon.frame.col, balloon.frame.row) == (None, None)


def test_only_the_rank_of_an_attached_balloons_pin_goes_unread():
    """Check that only the unread rank of an attached balloon's mixed pin is reported."""
    fs, vessel = _drum_run("superseded-attached")
    balloon = fs.add_instrument("LI", 1, sensing=vessel).pin(col=7, x=222.0, row=2)

    assert "pin-not-honored" in _codes(fs)
    assert balloon.frame is not None
    assert balloon.frame.x == 222.0
    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert len(said) == 1, said
    assert "row=2" in said[0] and "pin(x=..., y=...)" in said[0]


_MEASURES_NOTHING = "port 'inlet' is the nozzle x or y are measured to, and this pin states neither"
_GRID_CELL = ": {ranks} a grid cell, which has no nozzle in it"
_REMEDY = ". Give x or y, or drop port"


def _split(call):
    """Every ordered way of writing one ``pin()`` call as two."""
    keys = sorted(call)
    for size in range(1, len(keys)):
        for first in itertools.combinations(keys, size):
            rest = [k for k in keys if k not in first]
            yield [{k: call[k] for k in first}, {k: call[k] for k in rest}]


@pytest.mark.parametrize(
    "call, message",
    [
        # A nozzle and a grid cell: the author gave a placement and no
        # coordinate for the nozzle to sit on, so the sentence points at the
        # ranks rather than saying they stated nothing.
        (
            dict(col=1, port="inlet"),
            _MEASURES_NOTHING + _GRID_CELL.format(ranks="col names") + _REMEDY,
        ),
        (
            dict(row=2, port="inlet"),
            _MEASURES_NOTHING + _GRID_CELL.format(ranks="row names") + _REMEDY,
        ),
        (
            dict(col=1, row=2, port="inlet"),
            _MEASURES_NOTHING + _GRID_CELL.format(ranks="col and row name") + _REMEDY,
        ),
        # A nozzle measuring nothing, with nothing else wrong.
        (dict(port="inlet"), _MEASURES_NOTHING + _REMEDY),
        # A transform is not a coordinate, so it does not locate a nozzle.
        (dict(orientation=90, port="inlet"), _MEASURES_NOTHING + _REMEDY),
    ],
    ids=["col", "row", "col+row", "bare", "transform"],
)
def test_the_call_and_the_file_refuse_a_port_in_the_same_words(call, message):
    """Check that ``pin()`` and the spec reader refuse a port locating nothing alike."""
    from pandid.spec import SpecError

    written = {k: (5 if k == "x" else 440 if k == "y" else v) for k, v in call.items()}
    fs, valve = _valve_on_a_run()
    with pytest.raises(ValueError) as from_call:
        valve.pin(**call)
    assert str(from_call.value) == f"HV-1: {message}"

    with pytest.raises(SpecError) as from_file:
        Flowsheet.from_dict(_written_valve(written))
    assert str(from_file.value) == f"units[0] 'HV-1'.pin.port: {message}"


@pytest.mark.parametrize(
    "call",
    [
        dict(col=1, port="inlet"),
        dict(row=2, port="inlet"),
        dict(col=1, row=2, port="inlet"),
        dict(orientation=90, port="inlet"),
    ],
    ids=["col", "row", "col+row", "transform"],
)
def test_no_way_of_splitting_a_refused_call_lets_the_port_through(call):
    """Check that every two-call split of a refused pin is refused too."""
    from pandid.portgeom import pin_intent

    for calls in _split(call):
        fs, valve = _valve_on_a_run()
        with pytest.raises(ValueError, match="is the nozzle x or y are measured to"):
            for kw in calls:
                valve.pin(**kw)
        assert pin_intent(valve) == {}, calls


@pytest.mark.parametrize(
    "call",
    [
        # A rank and a nozzle sit together perfectly well: x locates the
        # inlet and the column is superseded there, which is what a pin
        # mixing grid and absolute has always meant. Refusing this was a
        # second rule, and it was the rule that made a placement the call
        # accepted and the file rejected.
        dict(col=1, x=5.0, port="inlet"),
        dict(row=2, y=440.0, port="inlet"),
        dict(col=1, row=2, x=5.0, y=440.0, port="inlet"),
    ],
    ids=["col+x", "row+y", "both"],
)
def test_a_rank_beside_a_nozzle_that_does_locate_something_is_accepted(call):
    """However the author spread it across calls, and it round-trips."""
    from pandid.portgeom import pin_intent

    for calls in [[call], *_split(call)]:
        fs, valve = _valve_on_a_run()
        try:
            for kw in calls:
                valve.pin(**kw)
        except ValueError:
            # A split that leaves the nozzle in a call with no coordinate is
            # refused on its own account; what must never happen is a split
            # that *lands* and then cannot be written down.
            continue
        written = fs.to_dict()
        read = Flowsheet.from_dict(written).units[1]
        assert pin_intent(read) == pin_intent(valve), calls
        assert read.pin_ == valve.pin_, calls


def _ranked_valve():
    """A valve on a three-unit run, with room for the grid to mean something."""
    fs = Flowsheet("ranked")
    feed = fs.add(U.Feed("A"))
    vessel = fs.add(U.Vessel("V-1"))
    valve = fs.add(U.Valve("HV-1"))
    prod = fs.add(U.Product("C"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    return fs, valve


def test_a_rank_and_a_located_nozzle_are_both_honoured():
    """Check that a column rank and a located nozzle are both honoured."""
    fs, reference = _ranked_valve()
    reference.pin(col=1)
    fs.layout()
    assert reference.frame is not None
    column_one = reference.frame.x

    fs, valve = _ranked_valve()
    valve.pin(col=1, y=RUN_Y, port="inlet")
    fs.layout()
    fs.route()
    assert valve.frame is not None
    assert valve.frame.x == column_one, "the column the pin named was not honoured"
    assert nozzle_of(valve, "inlet")[1] == RUN_Y, "the elevation the pin named was not honoured"
    assert valve.frame.col == 1
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_an_absolute_coordinate_still_supersedes_the_rank_beside_a_nozzle():
    """Check that an absolute coordinate beside a nozzle still wins over the rank."""
    fs, valve = _ranked_valve()
    valve.pin(col=1, x=5.0, port="inlet")
    fs.layout()
    fs.route()
    assert nozzle_of(valve, "inlet")[0] == 5.0
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_the_refusal_reads_the_pin_the_unit_has_not_the_call_in_front_of_it():
    """Check that a bare ``port=`` is judged against the pin the unit already has."""
    from pandid.portgeom import pin_intent

    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", x=300.0)
    was = pin_intent(valve)
    valve.pin(port="inlet")  # already what x is measured to; nothing discarded
    assert pin_intent(valve) == was

    fs, other = _valve_on_a_run()
    other.pin(col=1)
    with pytest.raises(ValueError) as raised:
        other.pin(port="inlet")
    assert "col names a grid cell, which has no nozzle in it" in str(raised.value)


def test_a_nozzle_and_a_grid_rank_accumulate_into_a_sheet_that_reads_back():
    """Check that a nozzle pin and a grid rank given in two calls write and read back."""
    from pandid.portgeom import pin_intent

    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    valve.pin(col=1)
    assert pin_intent(valve) == {"y": ("inlet", RUN_Y)}
    assert valve.pin_ is not None and valve.pin_.col == 1
    written = fs.to_dict()
    assert next(u["pin"] for u in written["units"] if u["name"] == "HV-1") == {
        "y": RUN_Y,
        "col": 1,
        "port": "inlet",
    }
    assert Flowsheet.from_dict(written).to_dict() == written

    flag = next(u for u in fs.units if u.name == "F")
    flag.pin(x=10.0, y=20.0, col=2)
    written = fs.to_dict()
    assert next(u["pin"] for u in written["units"] if u["name"] == "F") == {
        "x": 10.0,
        "y": 20.0,
        "col": 2,
        "port": "outlet",
    }
    assert Flowsheet.from_dict(written).to_dict() == written


_PIN_ARGS = [("col", 1), ("row", 2), ("x", 5.0), ("y", 440.0), ("port", None), ("orientation", 90)]


@pytest.mark.parametrize(
    "kind, port",
    [(U.Valve, "inlet"), (U.Feed, "outlet"), (U.Product, "inlet")],
    ids=["valve", "feed", "product"],
)
def test_every_placement_the_api_accepts_can_be_written_and_read_back(kind, port):
    """Check that every pin ``pin()`` accepts round-trips through ``to_dict``."""
    from pandid.portgeom import pin_intent

    landed = 0
    for size in range(1, len(_PIN_ARGS) + 1):
        for combo in itertools.combinations(_PIN_ARGS, size):
            call = {k: (port if k == "port" else v) for k, v in combo}
            for calls in [[call], *_split(call)]:
                fs = Flowsheet("sweep")
                feed = fs.add(U.Feed("F"))
                valve = fs.add(U.Valve("HV-1"))
                prod = fs.add(U.Product("Q"))
                fs.connect(feed.outlet, valve.inlet)
                fs.connect(valve.outlet, prod.inlet)
                unit = {U.Valve: valve, U.Feed: feed, U.Product: prod}[kind]
                try:
                    for kw in calls:
                        unit.pin(**kw)
                except (ValueError, KeyError):
                    continue  # refused, so there is no state to write down
                landed += 1
                written = fs.to_dict()
                back = Flowsheet.from_dict(written)  # must not raise
                read = next(u for u in back.units if u.name == unit.name)
                assert pin_intent(read) == pin_intent(unit), calls
                assert read.pin_ == unit.pin_, calls
    # A guard on the sweep itself: a bug that refused everything would
    # otherwise leave this asserting nothing at all.
    assert landed > 300, landed


def test_a_refused_port_leaves_no_half_applied_placement():
    """A refusal that half landed would be this defect wearing an exception."""
    from pandid.portgeom import pin_intent

    fs, valve = _valve_on_a_run()
    with pytest.raises(ValueError):
        valve.pin(port="inlet")
    assert pin_intent(valve) == {}
    assert valve.pin_ is None


def test_both_doors_name_the_misspelling_before_anything_it_measures():
    """Check that ``pin()`` and the spec reader both name a misspelt port first."""
    from pandid.spec import SpecError

    fs, valve = _valve_on_a_run()
    for call in (dict(port="inlets"), dict(col=1, port="inlets"), dict(y=RUN_Y, port="inlets")):
        with pytest.raises(KeyError, match="no port 'inlets'"):
            valve.pin(**call)
    for written in ({"port": "inlets"}, {"col": 1, "port": "inlets"}, {"y": 440, "port": "inlets"}):
        with pytest.raises(SpecError, match="has no port 'inlets'"):
            Flowsheet.from_dict(_written_valve(written))


def test_a_flag_that_named_no_port_is_not_refused():
    """Check that a flag pinned without a port takes a transform and a grid cell."""
    fs, valve = _valve_on_a_run()
    feed = next(u for u in fs.units if u.name == "F")
    feed.pin(mirrored=True)
    feed.pin(orientation=90)
    assert feed.pin_ is not None and feed.pin_.mirrored
    feed.pin(col=2, row=1)
    assert feed.pin_ is not None and (feed.pin_.col, feed.pin_.row) == (2, 1)


def _written_valve(pin):
    """One valve on a run, as a sheet, with ``pin`` written on the valve."""
    return {
        "name": "s",
        "units": [
            {"kind": "valve", "name": "HV-1", "pin": pin},
            {"kind": "feed", "name": "F"},
            {"kind": "product", "name": "Q"},
        ],
        "streams": [
            {"from": ["F", "outlet"], "to": ["HV-1", "inlet"]},
            {"from": ["HV-1", "outlet"], "to": ["Q", "inlet"]},
        ],
    }


@pytest.mark.parametrize(
    "port, said",
    [
        (
            {"orientation": 90, "port": "inlet"},
            "units[0] 'HV-1'.pin.port: " + _MEASURES_NOTHING + _REMEDY,
        ),
        # The axis-by-axis mapping, which has no ``pin()`` counterpart: only a
        # key can say which axis it went wrong on, and the path and the ``drop``
        # both name that key.
        (
            {"y": 440, "port": {"x": "inlet"}},
            "units[0] 'HV-1'.pin.port.x: port 'inlet' is the nozzle x is measured "
            "to, and this pin states no x. Give x, or drop port.x",
        ),
        # ...and the grid hint reaches the axis-by-axis form too, against the
        # key that names the nozzle rather than the pin as a whole.
        (
            {"col": 1, "port": {"x": "inlet"}},
            "units[0] 'HV-1'.pin.port.x: port 'inlet' is the nozzle x is measured "
            "to, and this pin states no x: col names a grid cell, which has no "
            "nozzle in it. Give x, or drop port.x",
        ),
        (
            {"y": 440, "port": {}},
            "units[0] 'HV-1'.pin.port names no axis; give port: {x: ...} or drop port",
        ),
        (
            {"y": 440, "port": 5},
            "units[0] 'HV-1'.pin.port names the nozzle a coordinate was measured to: "
            "either one name for every coordinate this pin states (port: inlet) or "
            "one per axis (port: {y: inlet}), got int: 5",
        ),
    ],
    ids=["no-coordinate", "axis-not-stated", "axis-on-a-grid", "empty", "not-a-name"],
)
def test_a_written_port_that_measures_nothing_is_refused(port, said):
    """Check that the spec reader refuses a written port that locates nothing."""
    from pandid.spec import SpecError

    with pytest.raises(SpecError) as raised:
        Flowsheet.from_dict(_written_valve(port))
    assert str(raised.value) == said


def test_a_placement_the_sheet_honoured_is_not_reported():
    """Check that an honoured port pin is not reported after a turn."""
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", x=300.0, y=RUN_Y)
    valve.pin(orientation=90)
    assert "pin-not-honored" not in _codes(fs)


def test_a_port_that_does_not_exist_is_refused_by_the_call_that_named_it():
    """Check that ``pin()`` refuses a port the unit lacks, with or without a coordinate."""
    fs, valve = _valve_on_a_run()
    with pytest.raises(KeyError, match="no port 'inlets' to pin by"):
        valve.pin(port="inlets")
    with pytest.raises(KeyError, match="no port 'inlets' to pin by"):
        valve.pin(port="inlets", y=RUN_Y)
