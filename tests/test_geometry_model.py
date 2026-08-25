"""Invariants for the intent (Pin) / result (Frame) geometry model."""

import itertools
from dataclasses import replace

import pytest

from pandid import Flowsheet, units as U
from pandid.portgeom import pinned_x, pinned_y, port_offset


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
    """Running layout twice must yield identical frames (seeded from pin_, not
    from the previous run's coordinates)."""
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
    """The renderer and the router must resolve a mirrored unit's ports to the
    same side, and the drawn stream must start at the mirror-correct port."""
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
    """The equivalence the sweep to these functions rested on.

    Every example used to read a nozzle's elevation as
    ``unit.pin_.y + port_offset(unit, port)[1]``. If these return anything else
    the twenty-two committed sheets would have moved, so this is the property
    that says the rewrite was a rewrite and not a redesign.
    """
    m = _pinned_mixer(x=100, y=200)
    for axis, fn, index in (("x", pinned_x, 0), ("y", pinned_y, 1)):
        assert fn(m, "in_1") == getattr(m.pin_, axis) + port_offset(m, "in_1")[index]
        assert fn(m) == getattr(m.pin_, axis)


def test_a_quarter_turn_moves_the_nozzle_it_is_read_from():
    """Not a constant added to a corner: the offset is measured in the placed box.

    A mixer turned a quarter draws its inlets down a different wall, so the
    coordinate has to follow. This is what stops the functions being a tidier
    spelling of ``pin_.x`` plus a number somebody wrote down once.
    """
    upright = _pinned_mixer(x=100, y=200)
    turned = _pinned_mixer(x=100, y=200, orientation=90)
    assert (pinned_x(upright, "in_1"), pinned_y(upright, "in_1")) != (
        pinned_x(turned, "in_1"),
        pinned_y(turned, "in_1"),
    )


def test_an_unpinned_unit_says_so_rather_than_raising_from_inside_an_expression():
    """``pin_`` is ``None`` until ``pin()`` is called.

    The old spelling reached ``None.y`` and raised ``AttributeError`` from the
    middle of an arithmetic expression, naming neither the unit nor the reason.
    """
    fs = Flowsheet("bare")
    m = fs.add(U.Mixer("M-9", n_inlets=2))
    for fn in (pinned_x, pinned_y):
        with pytest.raises(ValueError, match="M-9 has not been pinned"):
            fn(m)


def test_a_grid_pinned_unit_says_the_solver_has_not_decided_yet():
    """``col``/``row`` is a rank and not a coordinate, so there is nothing to read.

    The distinction the old spelling could not make: ``pin_`` exists, and
    ``pin_.x`` is still ``None``. That produced ``TypeError: unsupported operand
    type(s) for +: 'NoneType' and 'float'``, which says nothing about which unit
    or why.
    """
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
# A port-pinned axis is a relation, not a coordinate (#294)
# ---------------------------------------------------------------------------

RUN_Y = 440.0


def _valve_on_a_run():
    """The issue's own reproduction: one valve between two flags."""
    fs = Flowsheet("run")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    prod = fs.add(U.Product("Q"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    return fs, valve


def _drawn(unit, port_name):
    """Where a laid-out unit's nozzle ended up on the sheet."""
    from pandid.portgeom import port_point

    assert unit.frame is not None, f"{unit.name} was never placed"
    return port_point(unit, unit.frame, port_name)


def test_a_later_turn_leaves_a_port_pinned_nozzle_on_its_run():
    """``pin(port=...)`` says where a *nozzle* goes, and it keeps saying it.

    The defect this pins: the offset from the corner to the nozzle was
    taken once, at the call that named the port, and written into the pin as
    a corner. A later ``pin()`` that turned the unit changed the offset and
    left the corner where it was, so the same intent silently meant a
    different nozzle position and the valve came off its run by half a body
    -- 7.5px, with nothing said.
    """
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    fs.layout()
    assert _drawn(valve, "inlet")[1] == RUN_Y

    valve.pin(orientation=90)
    fs.layout()
    assert _drawn(valve, "inlet")[1] == RUN_Y


def test_a_later_mirror_leaves_a_port_pinned_nozzle_on_its_run():
    """The other half of the transform, and the one the offset is ordered for.

    ``pin()`` already took the offset after the turn and the flip *this* call
    asks for. A flip asked for by the next call is the same arithmetic one
    call too late.
    """
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", x=300.0, y=RUN_Y)
    fs.layout()
    was = _drawn(valve, "inlet")

    valve.pin(mirrored=True)
    fs.layout()
    assert _drawn(valve, "inlet") == was


def test_piping_the_nozzle_from_another_face_leaves_it_where_it_was_pinned():
    """A second site the same defect reaches, and one no re-pin covers.

    :meth:`~pandid.units.Unit.nozzle` moves a port to another face of the
    same box -- a tank's inlet from the west wall to the roof -- which moves
    it within the box exactly as a mirror does. Both statements are about the
    one nozzle, so the elevation the author wrote is the one that survives.
    """
    fs = Flowsheet("faces")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    tank.pin(port="in_1", y=RUN_Y)
    fs.layout()
    assert _drawn(tank, "in_1")[1] == RUN_Y

    tank.nozzle("in_1", "N")
    fs.layout()
    assert _drawn(tank, "in_1")[1] == RUN_Y


def test_resizing_the_box_leaves_a_port_pinned_nozzle_where_it_was_pinned():
    """The third site: the offset is measured in the *placed* box.

    A nozzle four fifths of the way down a tank is four fifths of whatever
    height the tank is given, so a later ``height =`` moves it too. Listed in
    ``_LAYOUT_INPUTS`` and so already known to move geometry.
    """
    fs = Flowsheet("resized")
    tank = fs.add(U.Tank("T-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(tank.outlet, prod.inlet)
    tank.pin(port="in_1", y=RUN_Y)
    fs.layout()

    tank.height = 200.0
    fs.layout()
    assert _drawn(tank, "in_1")[1] == RUN_Y


def _tank_the_selector_wants_to_move(port_pin: bool):
    """A sheet whose feed comes from above, so the engine prefers the roof.

    The tank's ``in_1`` is offered on three faces and the run arrives from
    the north, so face selection picks ``N`` and puts the nozzle on the roof
    -- half a box away from the west wall its offset was measured on. Built
    twice from one place so the two placements differ in nothing but how the
    author spelt the same point.
    """
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
    """The fourth site, and the one no ``pin()`` call can be reordered around.

    A port pin is honoured by deriving a corner from where the nozzle sits on
    the box, and *which* face it sits on is chosen later, by ``select_faces``
    -- after the boxes are placed, because a face can only be judged against
    where its peer landed. So the engine was choosing a face the corner had
    not been derived under, and the tank was drawn taking its feed into the
    roof instead of the pinned point on its wall: asked for (300, 440), drawn
    at (350, 361.4). Nothing downstream re-derives the corner, and the cut
    that puts selection after placement is the one thing here that cannot
    move -- so a pin, being a boundary condition rather than a preference, is
    what constrains the selection.

    The corner-pinned half is the control: the same sheet, the same nozzle,
    the same three candidate faces, and the engine *does* move it. Without
    that this could pass on a sheet that never tempted the selector at all.
    """
    from pandid.portgeom import port_faces

    fs, loose = _tank_the_selector_wants_to_move(port_pin=False)
    assert loose.frame is not None
    assert len(port_faces(loose, "in_1", loose.frame)) > 1
    assert loose.frame.port_faces.get("in_1") == "N"
    assert _drawn(loose, "in_1") != (300.0, RUN_Y)

    fs, tank = _tank_the_selector_wants_to_move(port_pin=True)
    assert _drawn(tank, "in_1") == (300.0, RUN_Y)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_a_pinned_nozzle_may_still_be_sent_to_a_face_by_name():
    """The pin fixes the point; :meth:`~pandid.units.Unit.nozzle` fixes which.

    Constraining the selection must not take the choice away from the author
    -- only from the engine. Both statements are honoured together: the run
    enters the roof because ``nozzle`` said so, and the roof is at 440 because
    the pin said so. Which face the nozzle is on is asserted as well as where
    it lands, since a fix that answered the pin by ignoring the named face
    would put it in the right place off the wrong wall.
    """
    from pandid.portgeom import resolve_port

    fs, tank = _tank_the_selector_wants_to_move(port_pin=True)
    tank.nozzle("in_1", "N")
    fs.layout()
    assert tank.frame is not None
    assert resolve_port(tank, tank.frame, "in_1").face == "N"
    assert _drawn(tank, "in_1") == (300.0, RUN_Y)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_only_the_pinned_nozzle_is_taken_out_of_the_engine_s_hands():
    """The constraint is the nozzle's, not the whole unit's.

    A conveyor takes its feed on the west wall or the roof and discharges east
    or south, and only one of the two was pinned. The other says nothing about
    where it goes, so the engine still chooses for it -- exempting the unit
    rather than the port would answer a pin nobody wrote by drawing the
    discharge off the symbol's default wall.
    """
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
    assert _drawn(belt, "feed") == (400.0, RUN_Y)


def test_a_pin_reads_back_as_the_corner_it_always_did():
    """The relation is stored; the corner is what every reader still sees.

    ``pin_`` is the layout engine's seed and the examples' arithmetic, and
    both want a top-left corner. Keeping that meaning is what lets the
    intent be recorded without moving a single drawn sheet.
    """
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    assert valve.pin_ is not None
    assert valve.pin_.y is not None
    assert valve.pin_.y + port_offset(valve, "inlet")[1] == RUN_Y
    assert pinned_y(valve, "inlet") == RUN_Y

    valve.pin(orientation=90)
    assert pinned_y(valve, "inlet") == RUN_Y


def test_the_nozzle_a_coordinate_was_measured_to_is_remembered_per_axis():
    """``pin(x=..., port=...)`` then ``pin(y=...)`` is two different statements.

    Each call speaks for the axes it names and leaves the rest as they
    stand, so the port has to be remembered per axis rather than per unit:
    x stays on the nozzle, y is the corner the second call gave.
    """
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
    """``port=None`` places the corner, which is how a resolved pin is written.

    :func:`pandid.spec._read_placement` reads a written sheet back that way,
    so a later turn must leave those coordinates exactly where the file put
    them.
    """
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", y=RUN_Y)
    valve.pin(port=None, y=RUN_Y)
    assert pinned_y(valve) == RUN_Y

    valve.pin(orientation=90)
    assert pinned_y(valve) == RUN_Y


def test_a_written_sheet_carries_the_relation_and_not_its_consequence():
    """The file boundary is a place the intent can be thrown away too.

    ``to_dict`` used to write the derived corner and drop the nozzle it was
    measured to, so a sheet written and read back was the defect again: the
    relation survived in memory and died in the file. What is stored is what
    has to be written.
    """
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
    """``from_dict(to_dict(fs))`` carries the relation, not its consequence.

    What is asserted is the relation this test **wrote**, against the record
    the unit that was read back holds (:func:`~pandid.portgeom.pin_intent`).
    Asking the unit that came back what it thinks it has and holding it to
    its own answer is a tautology, and it is how this test passed while
    losing everything it exists to protect: a round trip that deleted
    ``port`` and wrote the derived corner reports ``port=None`` on both
    sides of every question put in those terms, is a perfect fixed point,
    and survives a turn -- because a bare corner has nothing left in it to
    go stale.

    So the fixed point is only the first of three. The nozzle each
    coordinate was measured to is compared to the one that was written, the
    file is held to the spelling it must have for another reader to make
    sense of it, and the unit is then **turned**, which is the thing the
    relation exists to survive.
    """
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
    """``pin_`` is a read, and the same read whichever way the unit is pinned.

    A port-pinned axis is derived on the way out, so an assignment to the
    object handed back was silently dropped -- while the very same
    assignment on a corner-pinned unit moved it. The same input honoured or
    discarded depending on how the unit happened to be pinned is the defect
    this whole change is about, so both are refused and ``pin()`` is the way
    to place a unit.
    """
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


def test_a_placement_the_sheet_did_not_honour_is_reported():
    """The loud half: one check for the whole shape of the defect.

    A pinned axis is honoured exactly, so a drawn coordinate that is not
    the one the author wrote means something moved the unit after the
    solver read its pin -- and every way that happens happens silently.
    The check is written to that shape rather than to a cause, which is
    why it outlived the two causes it was raised for: the balloon whose
    absolute pin was discarded (#467) and the nozzle walked off its run by
    a later transform (#294) are both honoured now, and this still holds
    the drawing to the pin.

    So the mover here is explicit, and it is the finding's own sentence:
    the sheet is laid out, routed, and *then* the unit is shoved. Nothing
    re-runs the solve, because a frame is an output and assigning one is
    not a layout input -- which is exactly the hole a future phase could
    fall into.
    """
    fs = Flowsheet("moved-after-the-solve")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
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
    """``col``/``row`` is the natural spelling for a balloon, and was exempt.

    The absolute half of this was already caught; a rank was not, so an
    attached balloon pinned the way an author would actually pin one was
    still silently ignored. A rank is compared as a rank: the frame carries
    the one the sheet stood the unit in, and a pin naming one the frame does
    not is a pin nothing read.
    """
    fs = Flowsheet("ranked")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    fs.add_instrument("LI", 1, sensing=vessel).pin(col=3, row=1)

    assert "pin-not-honored" in _codes(fs)
    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert len(said) == 2, said
    assert any("col=3" in m for m in said) and any("row=1" in m for m in said)


def test_a_grid_pin_the_sheet_honoured_is_not_reported():
    """The balloon that *is* placed by its rank must stay quiet.

    A free-standing balloon is stood in the lane its pin names, and the
    check has to tell that apart from a rank dropped on the floor -- which
    is why the lane it was put in is recorded on the frame rather than
    inferred from the fact that a balloon was placed at all.
    """
    fs = Flowsheet("ranked-ok")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    fs.add_instrument("XI", 9).pin(col=3, row=1)

    assert "pin-not-honored" not in _codes(fs)


def test_a_rank_an_absolute_coordinate_supersedes_is_not_reported():
    """The check must not cry wolf on a sheet that is exactly right.

    ``pin(col=7, x=222)`` means 222: an absolute coordinate on an axis wins
    over the grid there, which is the placement rule
    ``layout.control._place_free`` states and honours -- it records the rank
    it *used*, and it used none. Holding the drawing to the overridden half
    reported a correct sheet twice, and an author who is warned about
    correct work stops reading the warnings.
    """
    fs = Flowsheet("superseded")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
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
    """The other side of the exemption, on the unit that has both halves.

    ``pin(col=7, x=222, row=2)`` on an attached balloon: the coordinate is
    honoured (#467), the rank on *that* axis is superseded rather than
    dropped, and the rank on the axis with no coordinate is the one half a
    balloon genuinely cannot stand in -- so it is the one thing reported.
    A grid is what a balloon does not have; an absolute position is not.
    """
    fs = Flowsheet("superseded-attached")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
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
    """Both doors into a placement, asked the same question, to the byte.

    The whole message is asserted and not a substring of it, because a
    substring is what hid the last defect here: both doors said "states
    neither" while one of them should have been talking about the grid.
    """
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
    """The refusal is against the pin the unit ends up with, not the statement.

    A rule read off one call's arguments is one you defeat by writing two,
    which is how an accumulated placement got past the previous version of
    this check. Every ordered way of writing the same arguments as two calls
    is refused, and the unit is left unplaced either way.

    The *sentence* may differ between splits and that is not a divergence:
    a pin refused before its ``col`` was ever stated cannot be told that a
    cell has no nozzle in it, because at that moment it names no cell. What
    has to hold is the verdict, and it does.
    """
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
    """The claim the relaxed rule rests on, in drawn pixels.

    Accepting a placement is worth nothing if the sheet then draws something
    else -- that is this issue's own defect. So the case for letting a rank
    stand beside a nozzle is not that it serialises, it is that the engine
    honours *both halves at once*: the valve is in the column its pin names,
    and its inlet is on the elevation its pin names, and neither is
    approximate.

    ``col=1`` is checked against the column a plain ``pin(col=1)`` puts the
    same valve in on the same sheet, rather than against a number written
    down here -- a rank is only meaningful relative to the grid stage 1 drew.

    Refusing this was the second rule, and it refused something correct.
    """
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
    assert _drawn(valve, "inlet")[1] == RUN_Y, "the elevation the pin named was not honoured"
    assert valve.frame.col == 1
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_an_absolute_coordinate_still_supersedes_the_rank_beside_a_nozzle():
    """The other half of the mixed pin, unchanged by any of this.

    ``absolute wins for whichever axis it sets`` is what a mixed pin has
    always promised, and a nozzle on that axis does not change it: the inlet
    goes to the x that was given, not to the column that was also named.
    """
    fs, valve = _ranked_valve()
    valve.pin(col=1, x=5.0, port="inlet")
    fs.layout()
    fs.route()
    assert _drawn(valve, "inlet")[0] == 5.0
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_the_refusal_reads_the_pin_the_unit_has_not_the_call_in_front_of_it():
    """Two consequences of asking the resulting placement, both observable.

    A nozzle already in force for an axis has not been discarded, so naming
    it again is not a refusal even though that call states no coordinate of
    its own -- the question is whether the pin measures anything to it, and
    it does. And a rank the unit was given by an *earlier* call is still the
    reason a later bare ``port=`` cannot land, so the sentence says so.

    Reading the arguments in front of us instead would answer both the other
    way round, which is the formulation a caller defeats by writing two
    calls.
    """
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
    """The two placements that were written and then refused.

    Both are a nozzle relation standing beside a grid rank, which is not a
    contradiction: the absolute coordinate locates the nozzle and supersedes
    the rank on its own axis, exactly as a pin mixing grid and absolute has
    always meant. Refusing that combination outright was a second rule, and
    it was reachable in two ways the rule could not see -- by splitting one
    ``pin()`` into two, and, on a boundary flag, without splitting anything,
    because a flag's nozzle is filled in rather than named.
    """
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
    """``to_dict`` must never write a sheet ``from_dict`` refuses.

    The check on a ``port=`` used to be read off the arguments of the call in
    front of it, so two calls could accumulate a placement neither call
    objected to and the file then rejected -- ``pin(port="inlet", y=440)``
    followed by ``pin(col=1)``, and a boundary flag's ``pin(x=…, y=…, col=…)``
    in a single call. Both wrote a document that would not read back, which
    is a broken public round trip and the same defect shape as a pin the
    reader silently reinterprets.

    So the property is asserted rather than the instances: sweep every
    combination of pin arguments, as one call and as every ordered way of
    writing it as two, and require of every placement that *lands* that it
    survives the file unchanged -- the relation and the resolved corner both.
    """
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
    """A name that is not a port at all is wrong before what it locates.

    Ordering again, and the half no shared sentence covers: a nozzle that
    does not exist is refused by both doors even when the pin is also wrong
    about the grid, so neither door answers a spelling mistake by complaining
    about a coordinate. The wording differs -- the file's carries the key
    path and a suggestion, as every ``_find_port`` failure does -- but the
    verdict does not.
    """
    from pandid.spec import SpecError

    fs, valve = _valve_on_a_run()
    for call in (dict(port="inlets"), dict(col=1, port="inlets"), dict(y=RUN_Y, port="inlets")):
        with pytest.raises(KeyError, match="no port 'inlets'"):
            valve.pin(**call)
    for written in ({"port": "inlets"}, {"col": 1, "port": "inlets"}, {"y": 440, "port": "inlets"}):
        with pytest.raises(SpecError, match="has no port 'inlets'"):
            Flowsheet.from_dict(_written_valve(written))


def test_a_flag_that_named_no_port_is_not_refused():
    """The exception the refusal must leave alone.

    A boundary flag's single nozzle is filled in for the caller, so
    ``feed.pin(mirrored=True)`` names no port at all and there is nothing in
    it to discard -- and a flag pinned to a grid cell is likewise not the
    author writing a nozzle onto one.
    """
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
    """The parser this change added must not drop input either.

    A nozzle named for an axis the pin does not state is the author saying
    where something goes and the reader silently not putting it there -- the
    same defect one layer down, so it raises against the key that says it
    rather than being quietly reinterpreted.

    Whole messages, path included: the path is what the file adds over the
    call, and asserting a substring of the sentence is how a wrong verdict
    went unnoticed the last time these were checked.
    """
    from pandid.spec import SpecError

    with pytest.raises(SpecError) as raised:
        Flowsheet.from_dict(_written_valve(port))
    assert str(raised.value) == said


def test_a_placement_the_sheet_honoured_is_not_reported():
    """Including a port-pinned one, which is the case with two numbers.

    The check reads the nozzle where the author named one and the corner
    where they did not, so a device pinned by its inlet and then turned is
    quiet -- which it is only because the intent survived the turn.
    """
    fs, valve = _valve_on_a_run()
    valve.pin(port="inlet", x=300.0, y=RUN_Y)
    valve.pin(orientation=90)
    assert "pin-not-honored" not in _codes(fs)


def test_a_port_that_does_not_exist_is_refused_by_the_call_that_named_it():
    """Even with no coordinate to apply it to.

    The port is resolved when ``pin()`` is called and not when the offset is
    taken, so a misspelling is the complaint of the call that wrote it.
    """
    fs, valve = _valve_on_a_run()
    with pytest.raises(KeyError, match="no port 'inlets' to pin by"):
        valve.pin(port="inlets")
    with pytest.raises(KeyError, match="no port 'inlets' to pin by"):
        valve.pin(port="inlets", y=RUN_Y)
