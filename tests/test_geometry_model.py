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
