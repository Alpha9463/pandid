"""Invariants for the intent (Pin) / result (Frame) geometry model."""

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

    An attached balloon is positioned from its host and its pin is never
    read (#467), so it is drawn hundreds of pixels from where it was put and
    says nothing. That is the same defect as a nozzle walked off its run --
    a value accepted, quietly altered, and the drawing shipped -- and it is
    the same finding, because holding the drawing to what was asked for
    catches the shape rather than the instances.
    """
    fs = Flowsheet("discarded")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    balloon = fs.add_instrument("LI", 1, sensing=vessel)
    balloon.pin(x=900.0, y=900.0)

    assert "pin-not-honored" in _codes(fs)
    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert any("900" in m and "attach(" in m for m in said), said


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


def test_an_absolute_coordinate_the_sheet_dropped_is_still_reported():
    """The other side of the exemption: only the *rank* is excused.

    An attached balloon is positioned from its host, so ``pin(col=7, x=222)``
    on one is dropped whole. The coordinate that superseded the rank is what
    the check holds the drawing to, so nothing goes unheld -- exempting the
    rank must not exempt the pin.
    """
    fs = Flowsheet("superseded-attached")
    feed = fs.add(U.Feed("F"))
    vessel = fs.add(U.Vessel("V-1"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, prod.inlet)
    fs.add_instrument("LI", 1, sensing=vessel).pin(col=7, x=222.0)

    assert "pin-not-honored" in _codes(fs)
    said = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert [m for m in said if "x=222" in m], said
    assert not [m for m in said if "col=7" in m], said


def test_the_call_and_the_file_refuse_the_same_port_that_measures_nothing():
    """``pin(port=...)`` naming a nozzle no coordinate reaches is refused.

    It used to be accepted and thrown away: the nozzle was resolved, no
    relation was recorded, and the pin serialised as ``{}``. The file API
    refused the same sentence, so the two doors into a placement disagreed
    about the very rule this change exists to enforce -- a value accepted,
    quietly altered and shipped, one layer up from the bug being fixed.

    Both doors are asked here, together, because what matters is that they
    give the same answer; :func:`pandid.portgeom.unmeasured_port` is the one
    sentence they both raise it with.
    """
    from pandid.spec import SpecError

    fs, valve = _valve_on_a_run()
    with pytest.raises(ValueError, match="states neither"):
        valve.pin(port="inlet")
    # Nothing was recorded on the way out, either: a refusal that half
    # applied would be the same defect wearing an exception.
    from pandid.portgeom import pin_intent

    assert pin_intent(valve) == {}

    with pytest.raises(SpecError, match="states neither"):
        Flowsheet.from_dict(_written_valve({"port": "inlet"}))


def test_a_port_stated_with_a_transform_is_refused_and_a_flag_is_not():
    """The refusal is for a nozzle the *caller* named and measured nothing to.

    ``pin(port="inlet", orientation=90)`` states a transform and no
    coordinate, so the nozzle it names locates nothing and goes the same way.
    A boundary flag is the exception that has to keep working: its single
    nozzle is filled in for the caller, so ``feed.pin(mirrored=True)`` names
    no port at all and there is nothing in it to discard.
    """
    fs, valve = _valve_on_a_run()
    with pytest.raises(ValueError, match="states neither"):
        valve.pin(port="inlet", orientation=90)

    feed = next(u for u in fs.units if u.name == "F")
    feed.pin(mirrored=True)
    feed.pin(orientation=90)
    assert feed.pin_ is not None and feed.pin_.mirrored


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
    "port, why, path",
    [
        ({"orientation": 90, "port": "inlet"}, "states neither", ".pin.port"),
        ({"y": 440, "port": {"x": "inlet"}}, "states no x", ".pin.port.x"),
        ({"y": 440, "port": {}}, "names no axis", ".pin.port"),
        ({"y": 440, "port": 5}, "names the nozzle", ".pin.port"),
    ],
)
def test_a_written_port_that_measures_nothing_is_refused(port, why, path):
    """The parser this change added must not drop input either.

    A nozzle named for an axis the pin does not state is the author saying
    where something goes and the reader silently not putting it there -- the
    same defect one layer down, so it raises against the key that says it
    rather than being quietly reinterpreted.

    The path is asserted with the sentence because the path is the whole of
    what the file adds: a key can say which axis went wrong and a keyword
    argument cannot, which is why these two refusals are worded in one place
    and located in two.
    """
    from pandid.spec import SpecError

    with pytest.raises(SpecError, match=why) as raised:
        Flowsheet.from_dict(_written_valve(port))
    assert str(raised.value).startswith(f"units[0] 'HV-1'{path}"), raised.value


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
