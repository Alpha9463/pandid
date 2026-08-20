"""The control valve station: the assembly, its tags, and where it is drawn.

The arrangement is the one the **CHEE4001/7103 P&ID guidelines** prescribe on
p.4 and draw on p.5 (``professional_examples/``, gitignored). Read off that
figure along the run:

    bypass takeoff, isolation valve, drain tee, reduction, control valve,
    expansion, drain tee, isolation valve, bypass rejoin

with the bypass carried below on one throttling valve, tapped **outside** both
isolation valves, and the drain and bypass valves drawn solid (normally closed)
while the two in-line isolation valves are left unfilled.

The issued sheet ``professional_examples/P&ID_301.pdf`` corroborates the
geometry and contradicts nothing here, but it tags **none** of a station's hand
valves or reducers -- it writes only ``CV-301-1``, ``CV-303``, ``CV-305``,
``CV-306``, ``CV-308``, ``CV-312``. So the tag derivation below is a convention
with a default, not a rule, which is why it is a scheme.
"""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.document import equipment_list
from pandid.portgeom import port_offset, port_point, resolve_size
from pandid.stations import ValveStation

RUN_Y = 400.0


def _sheet(**kwargs):
    """A station spliced into a feed-to-product run."""
    fs = Flowsheet("station")
    feed = fs.add(units.Feed("IN"))
    prod = fs.add(units.Product("OUT"))
    station = fs.add_valve_station("CV-303", x=300, y=RUN_Y, **kwargs)
    feed.pin(port="outlet", x=240, y=RUN_Y)
    prod.pin(port="inlet", x=900, y=RUN_Y)
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, prod.inlet)
    return fs, station


# --- what the assembly is ----------------------------------------------------


def test_a_full_station_is_eight_devices_and_four_tees():
    fs, st = _sheet()
    assert len(st.members) == 12
    assert [u.kind for u in st.members] == [
        "tee",  # bypass takeoff
        "valve",  # the throttling valve on the leg
        "valve",  # upstream isolation
        "tee",  # upstream drain
        "valve",
        "reducer",  # the reduction in
        "valve",  # the control valve
        "reducer",  # the expansion out
        "tee",  # downstream drain
        "valve",
        "valve",  # downstream isolation
        "tee",  # bypass rejoin
    ]


def test_the_run_passes_through_the_devices_the_figure_draws_it_through():
    """Isolation, drain, reduction, valve, expansion, drain, isolation."""
    _fs, st = _sheet()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    assert on_the_run[1:-1] == [
        st.upstream_isolation,
        on_the_run[2],  # the upstream drain tee
        st.reduction,
        st.control,
        st.expansion,
        on_the_run[6],  # the downstream drain tee
        st.downstream_isolation,
    ]


def test_the_bypass_is_tapped_outside_both_isolation_valves():
    _fs, st = _sheet()
    takeoff, rejoin = st.tees[0], st.tees[-1]
    assert takeoff.branch.stream.dest.owner is st.bypass
    assert st.bypass.outlet.stream.dest.owner is rejoin
    # The takeoff feeds the upstream isolation and the rejoin is fed by the
    # downstream one, so both valves are inside the leg.
    assert takeoff.outlet.stream.dest.owner is st.upstream_isolation
    assert rejoin.inlet.stream.source.owner is st.downstream_isolation


def test_the_size_change_is_a_reduction_in_and_an_expansion_out():
    _fs, st = _sheet()
    assert st.reduction.large_end == "inlet"
    assert st.expansion.large_end == "outlet"


def test_the_drain_and_bypass_valves_are_normally_closed_and_the_isolations_are_not():
    _fs, st = _sheet()
    for valve in (st.bypass, st.upstream_drain, st.downstream_drain):
        assert valve.normal_position == "closed"
    for valve in (st.upstream_isolation, st.downstream_isolation):
        assert valve.normal_position == "open"


def test_a_drain_leg_ends_at_its_valve():
    """A drain runs to a funnel on the floor, which is not on the sheet."""
    _fs, st = _sheet()
    assert st.upstream_drain.outlet.stream is None
    assert st.downstream_drain.outlet.stream is None


def test_the_control_valve_takes_the_tag_and_the_variant():
    _fs, st = _sheet(variant="butterfly_pneumatic")
    assert st.control.name == "CV-303"
    assert st.control.variant == "butterfly_pneumatic"


def test_members_can_be_left_out():
    fs = Flowsheet("bare")
    st = fs.add_valve_station("CV-1", isolation=False, bypass=False, reducers=False, drains=0)
    assert st.members == (st.control,)
    assert st.tees == ()
    assert st.inlet is st.control.inlet and st.outlet is st.control.outlet


def test_one_drain_goes_upstream():
    fs = Flowsheet("one drain")
    st = fs.add_valve_station("CV-1", drains=1)
    assert st.upstream_drain is not None
    assert st.downstream_drain is None


# --- tags --------------------------------------------------------------------


def test_the_default_scheme_spells_the_common_convention():
    _fs, st = _sheet()
    assert st.upstream_isolation.name == "HV-303A"
    assert st.downstream_isolation.name == "HV-303B"
    assert st.bypass.name == "HV-303C"
    assert st.upstream_drain.name == "HV-303D"
    assert st.downstream_drain.name == "HV-303E"
    assert st.reduction.name == "RD-303A"
    assert st.expansion.name == "RD-303B"


def test_the_scheme_is_a_flowsheet_setting_like_the_other_two():
    fs = Flowsheet("site", valve_station_tag_scheme="{letters}{number}{suffix}")
    st = fs.add_valve_station("CV-303")
    assert st.upstream_isolation.name == "HV303A"
    assert st.reduction.name == "RD303A"


def test_one_station_may_override_the_sheet_scheme():
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-303", tag_scheme="{number}-{letters}{suffix}")
    assert st.bypass.name == "303-HVC"


def test_a_callable_scheme_is_given_the_role_and_the_control_valve_tag():
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-303", tag_scheme=lambda role, control: f"{control}/{role}")
    assert st.bypass.name == "CV-303/bypass"
    assert st.expansion.name == "CV-303/expansion"


def test_a_scheme_asking_for_something_that_is_not_part_of_a_tag_says_so():
    fs = Flowsheet("site")
    with pytest.raises(ValueError, match="not part of a station member's tag"):
        fs.add_valve_station("CV-303", tag_scheme="{service}-{number}")


def test_the_number_can_be_given_where_the_control_valve_carries_a_suffix():
    """``CV-301-1`` is one of two valves on loop 301; its hand valves are 301."""
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-301-1", number=301)
    assert st.control.name == "CV-301-1"
    assert st.upstream_isolation.name == "HV-301A"


def test_each_member_is_described_from_the_station_service():
    _fs, st = _sheet(description="Reflux")
    assert st.control.description == "Reflux Control Valve"
    assert st.upstream_isolation.description == "Reflux Isolation Valve"
    assert st.downstream_drain.description == "Reflux Downstream Drain Valve"
    assert st.expansion.description == "Reflux Outlet Expander"


# --- what it returns ---------------------------------------------------------


def test_a_station_is_not_a_unit_and_is_not_on_the_flowsheet():
    fs, st = _sheet()
    assert isinstance(st, ValveStation)
    assert not isinstance(st, units.Unit)
    assert st not in fs.units
    assert all(member in fs.units for member in st.members)


def test_a_station_reaches_no_equipment_list():
    """Its members are pipe and valves, and neither is scheduled equipment."""
    fs, _st = _sheet()
    assert equipment_list(fs).rows == []


def test_the_handle_does_not_let_a_member_be_rebound():
    _fs, st = _sheet()
    with pytest.raises(Exception):
        st.control = st.bypass


def test_a_member_is_an_ordinary_unit_that_can_still_be_moved_and_instrumented():
    fs, st = _sheet()
    st.bypass.pin(x=555)
    assert st.bypass.pin_.x == 555
    fic = fs.add_instrument("FIC", 303, near=st.control, at="N", variant="shared")
    fs.connect(fic.sig_out, st.control.actuator, kind="pneumatic")
    assert fs.validate() == []


# --- where it is drawn -------------------------------------------------------


def _nozzle(unit, port):
    return port_point(unit, unit.frame, port)


def test_every_device_on_the_run_lands_on_the_run():
    fs, st = _sheet()
    fs.layout()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    for unit in on_the_run:
        assert _nozzle(unit, "inlet")[1] == pytest.approx(RUN_Y)
        assert _nozzle(unit, "outlet")[1] == pytest.approx(RUN_Y)


def test_the_run_is_drawn_left_to_right_in_piping_order():
    fs, st = _sheet()
    fs.layout()
    xs = [
        u.frame.x
        for u in st.members
        if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    assert xs == sorted(xs)


def test_a_mirrored_station_is_the_same_run_drawn_the_other_way_round():
    fs, st = _sheet(mirrored=True)
    fs.layout()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    xs = [u.frame.x for u in on_the_run]
    assert xs == sorted(xs, reverse=True)
    # Flow still enters the station's inlet, which is now its east end.
    assert _nozzle(st.upstream_isolation, "inlet")[0] > _nozzle(st.upstream_isolation, "outlet")[0]


def test_the_bypass_stands_over_the_run_and_the_drains_hang_under_it():
    fs, st = _sheet(bypass_rise=45, drain_drop=36)
    fs.layout()
    assert _nozzle(st.bypass, "inlet")[1] == pytest.approx(RUN_Y - 45)
    for drain in (st.upstream_drain, st.downstream_drain):
        assert _nozzle(drain, "inlet")[1] == pytest.approx(RUN_Y + 36)
        assert _nozzle(drain, "inlet")[0] == pytest.approx(_nozzle(drain, "outlet")[0])


def test_a_drain_hangs_off_its_own_tee():
    fs, st = _sheet()
    fs.layout()
    for tee, drain in ((st.tees[1], st.upstream_drain), (st.tees[2], st.downstream_drain)):
        assert _nozzle(drain, "inlet")[0] == pytest.approx(_nozzle(tee, "branch")[0])


def test_the_bypass_valve_sits_in_the_middle_of_its_leg_by_default():
    fs, st = _sheet()
    fs.layout()
    legs = [_nozzle(st.tees[0], "branch")[0], _nozzle(st.tees[-1], "branch")[0]]
    centre = st.bypass.frame.x + resolve_size(st.bypass)[0] / 2
    assert centre == pytest.approx(sum(legs) / 2)


def test_the_bypass_valve_can_be_stood_over_a_named_member():
    fs, st = _sheet(bypass_over="reduction")
    fs.layout()
    centre = st.bypass.frame.x + resolve_size(st.bypass)[0] / 2
    assert centre == pytest.approx(st.reduction.frame.x + resolve_size(st.reduction)[0] / 2)


def test_an_unplaced_station_is_declared_and_connected_but_not_pinned():
    fs = Flowsheet("unplaced")
    st = fs.add_valve_station("CV-1")
    assert all(u.pin_ is None for u in st.members)
    assert st.control.inlet.stream is not None


def test_a_placed_station_draws_without_a_finding():
    fs, _st = _sheet()
    assert fs.validate() == []
    assert "<svg" in fs.to_svg(diagram="p&id")


# --- line numbers ------------------------------------------------------------


def test_the_run_takes_the_number_of_the_line_connected_to_it():
    fs = Flowsheet("numbered", line_numbering_scheme="{service}-{sequence}-{size}")
    feed = fs.add(units.Feed("IN"))
    st = fs.add_valve_station("CV-303", x=300, y=RUN_Y)
    fs.connect(feed.outlet, st.inlet, service="AE", sequence=303, size=80)
    assert st.control.inlet.stream.name == "AE-303-80"
    assert st.expansion.outlet.stream.name == "AE-303-80"


def test_a_branch_takes_the_number_the_station_was_given():
    """A bypass is the same service, size and spec as the run it goes round."""
    fs = Flowsheet("numbered", line_numbering_scheme="{service}-{sequence}-{size}")
    st = fs.add_valve_station("CV-303", x=300, y=RUN_Y, service="AE", sequence=303, size=80)
    assert st.bypass.inlet.stream.name == "AE-303-80"
    assert st.upstream_drain.inlet.stream.name == "AE-303-80"
    # ...and it carries through the bypass valve to the rejoin.
    assert st.bypass.outlet.stream.name == "AE-303-80"


# --- refusals ----------------------------------------------------------------


def test_a_bypass_with_no_isolation_valves_to_go_round_is_refused():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="no isolation valves to tap outside of"):
        fs.add_valve_station("CV-1", isolation=False, bypass=True)


def test_a_drain_count_that_is_not_zero_one_or_two_is_refused():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="drains= is how many drain valves"):
        fs.add_valve_station("CV-1", drains=3)


def test_one_of_x_and_y_without_the_other_is_refused():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="placed by"):
        fs.add_valve_station("CV-1", x=300)


def test_a_bypass_over_a_member_that_is_not_there_is_refused():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="told to leave out"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="reduction")


def test_a_bypass_over_something_that_is_not_a_member_is_refused():
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="bypass_over names the member"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, bypass_over="drain")


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(isolation=False, bypass=True),
        dict(drains=3),
        dict(x=300),
        dict(x=300, y=RUN_Y, reducers=False, bypass_over="reduction"),
    ],
    ids=[
        "bypass_without_isolation",
        "bad_drain_count",
        "x_without_y",
        "bypass_over_a_role_left_out",
    ],
)
def test_a_refused_call_leaves_the_sheet_exactly_as_it_was(kwargs):
    """Every refusal is checked before a member joins the sheet, so a call
    that raises has built nothing -- not just fewer things than it would
    have, but nothing at all. A retry with the mistake fixed can then reuse
    the tag."""
    fs = Flowsheet("bad")
    before_units, before_streams = list(fs.units), list(fs.streams)
    with pytest.raises(ValueError):
        fs.add_valve_station("CV-1", **kwargs)
    assert fs.units == before_units
    assert fs.streams == before_streams


def test_a_bypass_over_a_role_left_out_can_be_retried_with_the_same_tag():
    """The failed call above never claimed 'CV-1', so fixing the mistake and
    calling again does not collide with a half-built station."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="told to leave out"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="reduction")
    station = fs.add_valve_station(
        "CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="upstream_isolation"
    )
    assert station.control.name == "CV-1"


# --- the station is a constructor, so nothing of it has to be serialized ------


def test_a_sheet_with_a_station_round_trips_through_the_spec():
    fs, st = _sheet(description="Reflux", service="AE", sequence=303, size=80)
    fs.layout()
    again = Flowsheet.from_dict(spec.to_dict(fs))
    again.layout()
    assert [u.name for u in again.units] == [u.name for u in fs.units]
    assert [(u.frame.x, u.frame.y) for u in again.units] == [
        (u.frame.x, u.frame.y) for u in fs.units
    ]
    assert [s.name for s in again.streams] == [s.name for s in fs.streams]


# --- the two placement helpers the station is built on ------------------------


def test_port_offset_answers_where_a_nozzle_sits_in_its_own_box():
    valve = units.Valve("HV-1")
    width, height = resolve_size(valve)
    assert port_offset(valve, "inlet") == pytest.approx((0.0, height / 2))
    assert port_offset(valve, "outlet") == pytest.approx((width, height / 2))


def test_port_offset_follows_the_placement_the_unit_carries():
    valve = units.Valve("HV-1").pin(mirrored=True)
    width, height = resolve_size(valve)
    assert port_offset(valve, "inlet") == pytest.approx((width, height / 2))


def test_pin_by_port_puts_that_nozzle_on_the_coordinate_given():
    fs = Flowsheet("pinned")
    valve = fs.add(units.Valve("HV-1")).pin(port="inlet", x=200, y=RUN_Y)
    fs.layout()
    assert port_point(valve, valve.frame, "inlet") == pytest.approx((200, RUN_Y))


def test_pin_by_port_is_idempotent():
    valve = units.Valve("HV-1")
    valve.pin(port="inlet", x=200, y=RUN_Y)
    first = (valve.pin_.x, valve.pin_.y)
    valve.pin(port="inlet", x=200, y=RUN_Y)
    assert (valve.pin_.x, valve.pin_.y) == first


def test_pin_by_port_reads_only_the_axes_it_is_given():
    """Step along a row by the corner and still land the nozzle on the line."""
    valve = units.Valve("HV-1").pin(mirrored=True)
    valve.pin(x=200)
    valve.pin(port="inlet", y=RUN_Y)
    assert valve.pin_.x == 200
    assert valve.pin_.y == RUN_Y - resolve_size(valve)[1] / 2


def test_pin_by_port_applies_the_transform_from_the_same_call():
    turned = units.Valve("HV-1").pin(orientation=90, port="inlet", y=RUN_Y)
    assert turned.pin_.y == pytest.approx(RUN_Y)  # the turned inlet is on the top edge


def test_pin_by_a_port_the_unit_does_not_have_says_which_it_has():
    with pytest.raises(KeyError, match="no port 'suction' to pin by"):
        units.Valve("HV-1").pin(port="suction", x=10, y=10)


def test_pin_by_port_refuses_a_grid_cell():
    with pytest.raises(ValueError, match="has no nozzle in it"):
        units.Valve("HV-1").pin(port="inlet", col=2)


@pytest.mark.parametrize("kind, port", [(units.Feed, "outlet"), (units.Product, "inlet")])
def test_a_flag_is_pinned_by_its_nozzle_without_being_asked(kind, port):
    """A flag has one nozzle and no drawn corner, so naming the port is ceremony."""
    fs = Flowsheet("flag")
    flag = fs.add(kind("F")).pin(x=200, y=RUN_Y)
    fs.layout()
    assert port_point(flag, flag.frame, port) == pytest.approx((200, RUN_Y))


def test_a_flag_can_still_be_pinned_by_its_corner():
    """``port=None`` is the caller asking for the corner, which is not the same as
    saying nothing -- and it is what reading a written pin back in needs."""
    assert units.Feed("F").pin(port=None, x=200, y=100).pin_.x == 200


def test_a_flag_still_takes_a_grid_cell():
    """The nozzle default must not turn a cell into the col/row refusal, which is
    for a caller who named a port and a cell in one breath."""
    flag = units.Feed("F").pin(col=2, row=1)
    assert (flag.pin_.col, flag.pin_.row) == (2, 1)
