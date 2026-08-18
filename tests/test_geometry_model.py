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
