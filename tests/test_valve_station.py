"""Check the control valve station: its assembly, tags, placement and refusals.

The arrangement follows the CHEE4001/7103 P&ID guidelines (p.4, drawn on
p.5 of ``professional_examples/``, which is gitignored). Along the run it is:

    bypass takeoff, isolation valve, drain tee, reduction, control valve,
    expansion, drain tee, isolation valve, bypass rejoin

The bypass is carried on one throttling valve and tapped outside both
isolation valves. The drain and bypass valves are drawn solid (normally
closed); the two in-line isolation valves are left open.

The issued sheet ``professional_examples/P&ID_301.pdf`` agrees with this
geometry but tags none of a station's hand valves or reducers, so member tags
come from a configurable scheme rather than a fixed rule.
"""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.document import equipment_list
from pandid.geometry import Frame
from pandid.portgeom import port_offset, port_point, resolve_size
from pandid.stations import DEFAULT_GAP, ValveStation

RUN_Y = 400.0


def _sheet(**kwargs):
    """Return a sheet with a pinned station spliced into a feed-to-product run.

    Parameters
    ----------
    **kwargs : Any
        Options passed to :meth:`~pandid.flowsheet.Flowsheet.add_valve_station`.

    Returns
    -------
    tuple of (Flowsheet, ValveStation)
        The sheet and the station.
    """
    fs = Flowsheet("station")
    feed = fs.add(units.Feed("IN"))
    prod = fs.add(units.Product("OUT"))
    station = fs.add_valve_station("CV-303", x=300, y=RUN_Y, **kwargs)
    feed.pin(port="outlet", x=240, y=RUN_Y)
    prod.pin(port="inlet", x=900, y=RUN_Y)
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, prod.inlet)
    return fs, station


# --- Assembly ----------------------------------------------------------------


def test_a_full_station_is_eight_devices_and_four_tees():
    """Check that a full station has eight devices and four tees in flow order."""
    fs, st = _sheet()
    assert len(st.members) == 12
    assert [u.kind for u in st.members] == [
        "tee",  # bypass takeoff
        "valve",  # bypass throttling valve
        "valve",  # upstream isolation
        "tee",  # upstream drain
        "valve",
        "reducer",  # reduction
        "valve",  # control valve
        "reducer",  # expansion
        "tee",  # downstream drain
        "valve",
        "valve",  # downstream isolation
        "tee",  # bypass rejoin
    ]


def test_the_run_passes_through_the_devices_the_figure_draws_it_through():
    """Check the run order: isolation, drain, reduction, valve, expansion, drain, isolation."""
    _fs, st = _sheet()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    assert on_the_run[1:-1] == [
        st.upstream_isolation,
        on_the_run[2],  # upstream drain tee
        st.reduction,
        st.control,
        st.expansion,
        on_the_run[6],  # downstream drain tee
        st.downstream_isolation,
    ]


def test_the_bypass_is_tapped_outside_both_isolation_valves():
    """Check that the bypass leg leaves before and rejoins after both isolations."""
    _fs, st = _sheet()
    takeoff, rejoin = st.tees[0], st.tees[-1]
    assert takeoff.branch.stream.dest.owner is st.bypass
    assert st.bypass.outlet.stream.dest.owner is rejoin
    # Both isolation valves sit inside the bypass leg.
    assert takeoff.outlet.stream.dest.owner is st.upstream_isolation
    assert rejoin.inlet.stream.source.owner is st.downstream_isolation


def test_the_size_change_is_a_reduction_in_and_an_expansion_out():
    """Check that the reducers face the control valve from both sides."""
    _fs, st = _sheet()
    assert st.reduction.large_end == "inlet"
    assert st.expansion.large_end == "outlet"


def test_the_drain_and_bypass_valves_are_normally_closed_and_the_isolations_are_not():
    """Check the normal position of each hand valve."""
    _fs, st = _sheet()
    for valve in (st.bypass, st.upstream_drain, st.downstream_drain):
        assert valve.normal_position == "closed"
    for valve in (st.upstream_isolation, st.downstream_isolation):
        assert valve.normal_position == "open"


def test_a_drain_leg_ends_at_its_valve():
    """Check that a drain valve has no outlet stream, as its funnel is off-sheet."""
    _fs, st = _sheet()
    assert st.upstream_drain.outlet.stream is None
    assert st.downstream_drain.outlet.stream is None


def test_the_control_valve_takes_the_tag_and_the_variant():
    """Check that the control valve carries the station tag and variant."""
    _fs, st = _sheet(variant="butterfly_pneumatic")
    assert st.control.name == "CV-303"
    assert st.control.variant == "butterfly_pneumatic"


def test_members_can_be_left_out():
    """Check that a station with every option off is the control valve alone."""
    fs = Flowsheet("bare")
    st = fs.add_valve_station("CV-1", isolation=False, bypass=False, reducers=False, drains=0)
    assert st.members == (st.control,)
    assert st.tees == ()
    assert st.inlet is st.control.inlet and st.outlet is st.control.outlet


def test_one_drain_goes_upstream():
    """Check that a single drain is placed upstream of the control valve."""
    fs = Flowsheet("one drain")
    st = fs.add_valve_station("CV-1", drains=1)
    assert st.upstream_drain is not None
    assert st.downstream_drain is None


# --- Tags --------------------------------------------------------------------


def test_the_default_scheme_spells_the_common_convention():
    """Check the default member tags derived from ``CV-303``."""
    _fs, st = _sheet()
    assert st.upstream_isolation.name == "HV-303A"
    assert st.downstream_isolation.name == "HV-303B"
    assert st.bypass.name == "HV-303C"
    assert st.upstream_drain.name == "HV-303D"
    assert st.downstream_drain.name == "HV-303E"
    assert st.reduction.name == "RD-303A"
    assert st.expansion.name == "RD-303B"


def test_the_scheme_is_a_flowsheet_setting_like_the_other_two():
    """Check that the sheet's ``valve_station_tag_scheme`` sets member tags."""
    fs = Flowsheet("site", valve_station_tag_scheme="{letters}{number}{suffix}")
    st = fs.add_valve_station("CV-303")
    assert st.upstream_isolation.name == "HV303A"
    assert st.reduction.name == "RD303A"


def test_one_station_may_override_the_sheet_scheme():
    """Check that a station's ``tag_scheme`` overrides the sheet's."""
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-303", tag_scheme="{number}-{letters}{suffix}")
    assert st.bypass.name == "303-HVC"


def test_a_callable_scheme_is_given_the_role_and_the_control_valve_tag():
    """Check that a callable scheme receives the role and the control tag."""
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-303", tag_scheme=lambda role, control: f"{control}/{role}")
    assert st.bypass.name == "CV-303/bypass"
    assert st.expansion.name == "CV-303/expansion"


def test_a_scheme_asking_for_something_that_is_not_part_of_a_tag_says_so():
    """Check that a scheme field outside the tag parts is refused."""
    fs = Flowsheet("site")
    with pytest.raises(ValueError, match="not part of a station member's tag"):
        fs.add_valve_station("CV-303", tag_scheme="{service}-{number}")


def test_the_number_can_be_given_where_the_control_valve_carries_a_suffix():
    """Check that ``number`` sets member tags for a suffixed control tag such as ``CV-301-1``."""
    fs = Flowsheet("site")
    st = fs.add_valve_station("CV-301-1", number=301)
    assert st.control.name == "CV-301-1"
    assert st.upstream_isolation.name == "HV-301A"


def test_each_member_is_described_from_the_station_service():
    """Check that member descriptions are prefixed with the station description."""
    _fs, st = _sheet(description="Reflux")
    assert st.control.description == "Reflux Control Valve"
    assert st.upstream_isolation.description == "Reflux Isolation Valve"
    assert st.downstream_drain.description == "Reflux Downstream Drain Valve"
    assert st.expansion.description == "Reflux Outlet Expander"


# --- Handle ------------------------------------------------------------------


def test_a_station_is_not_a_unit_and_is_not_on_the_flowsheet():
    """Check that the handle is not a unit, while every member is on the sheet."""
    fs, st = _sheet()
    assert isinstance(st, ValveStation)
    assert not isinstance(st, units.Unit)
    assert st not in fs.units
    assert all(member in fs.units for member in st.members)


def test_a_station_reaches_no_equipment_list():
    """Check that station members, being pipe and valves, are not scheduled equipment."""
    fs, _st = _sheet()
    assert equipment_list(fs).rows == []


def test_the_handle_does_not_let_a_member_be_rebound():
    """Check that the handle's members cannot be reassigned."""
    _fs, st = _sheet()
    with pytest.raises(Exception):
        st.control = st.bypass


def test_a_member_is_an_ordinary_unit_that_can_still_be_moved_and_instrumented():
    """Check that a member can be re-pinned and instrumented without findings."""
    fs, st = _sheet()
    # Tabulate a stream so stream-table-missing is not reported.
    fs.streams[0].properties = {"Flow (kg/h)": "4200"}
    st.bypass.pin(x=555)
    assert st.bypass.pin_.x == 555
    fic = fs.add_instrument("FIC", 303, near=st.control, at="N", variant="shared")
    fs.connect(fic.sig_out, st.control.actuator, kind="pneumatic")
    assert fs.validate() == []


# --- Placement ---------------------------------------------------------------


def _nozzle(unit, port):
    """Return the drawn position of a port on a laid-out unit.

    Parameters
    ----------
    unit : Unit
        Laid-out unit.
    port : str
        Port name.

    Returns
    -------
    tuple of (float, float)
        Port position on the sheet.
    """
    return port_point(unit, unit.frame, port)


def _box(unit: units.Unit) -> Frame:
    """Return the frame layout resolved for a unit.

    Parameters
    ----------
    unit : Unit
        Unit on a laid-out sheet.

    Returns
    -------
    Frame
        The unit's frame; asserted to exist.
    """
    assert unit.frame is not None
    return unit.frame


def _drawn(station: ValveStation) -> list[tuple[float, float, bool, bool]]:
    """Return where each member is drawn and which way round.

    Parameters
    ----------
    station : ValveStation
        Station on a laid-out sheet.

    Returns
    -------
    list of tuple of (float, float, bool, bool)
        Each member's ``x``, ``y``, ``mirrored`` and ``mirror_y``.
    """
    return [(_box(u).x, _box(u).y, _box(u).mirrored, _box(u).mirror_y) for u in station.members]


def test_every_device_on_the_run_lands_on_the_run():
    """Check that every in-line member's nozzles lie on the run centreline."""
    fs, st = _sheet()
    fs.layout()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    for unit in on_the_run:
        assert _nozzle(unit, "inlet")[1] == pytest.approx(RUN_Y)
        assert _nozzle(unit, "outlet")[1] == pytest.approx(RUN_Y)


def test_the_run_is_drawn_left_to_right_in_piping_order():
    """Check that in-line members are drawn west to east in flow order."""
    fs, st = _sheet()
    fs.layout()
    xs = [
        u.frame.x
        for u in st.members
        if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    assert xs == sorted(xs)


def test_gap_is_edge_to_edge_between_one_device_and_the_next():
    """Check that ``gap`` is the clear distance between neighbouring in-line members."""
    fs, st = _sheet(gap=50)
    fs.layout()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    for before, after in zip(on_the_run, on_the_run[1:]):
        assert _box(after).x - _box(before).x_max == pytest.approx(50)


def test_a_mirrored_station_is_the_same_run_drawn_the_other_way_round():
    """Check that ``mirrored=True`` draws the run east to west."""
    fs, st = _sheet(mirrored=True)
    fs.layout()
    on_the_run = [
        u for u in st.members if u not in (st.bypass, st.upstream_drain, st.downstream_drain)
    ]
    xs = [u.frame.x for u in on_the_run]
    assert xs == sorted(xs, reverse=True)
    # Flow still enters at the station inlet, now at its east end.
    assert _nozzle(st.upstream_isolation, "inlet")[0] > _nozzle(st.upstream_isolation, "outlet")[0]


def test_the_bypass_stands_over_the_run_and_the_drains_hang_under_it():
    """Check that ``bypass_rise`` and ``drain_drop`` set the leg offsets."""
    fs, st = _sheet(bypass_rise=45, drain_drop=36)
    fs.layout()
    assert _nozzle(st.bypass, "inlet")[1] == pytest.approx(RUN_Y - 45)
    for drain in (st.upstream_drain, st.downstream_drain):
        assert _nozzle(drain, "inlet")[1] == pytest.approx(RUN_Y + 36)
        assert _nozzle(drain, "inlet")[0] == pytest.approx(_nozzle(drain, "outlet")[0])


def test_a_drain_hangs_off_its_own_tee():
    """Check that each drain valve is directly below its tee's branch."""
    fs, st = _sheet()
    fs.layout()
    for tee, drain in ((st.tees[1], st.upstream_drain), (st.tees[2], st.downstream_drain)):
        assert _nozzle(drain, "inlet")[0] == pytest.approx(_nozzle(tee, "branch")[0])


def test_the_bypass_valve_sits_in_the_middle_of_its_leg_by_default():
    """Check that the bypass valve is centred between the takeoff and rejoin."""
    fs, st = _sheet()
    fs.layout()
    legs = [_nozzle(st.tees[0], "branch")[0], _nozzle(st.tees[-1], "branch")[0]]
    centre = st.bypass.frame.x + resolve_size(st.bypass)[0] / 2
    assert centre == pytest.approx(sum(legs) / 2)


def test_the_bypass_valve_can_be_stood_over_a_named_member():
    """Check that ``bypass_over`` centres the bypass valve over that member."""
    fs, st = _sheet(bypass_over="reduction")
    fs.layout()
    centre = st.bypass.frame.x + resolve_size(st.bypass)[0] / 2
    assert centre == pytest.approx(st.reduction.frame.x + resolve_size(st.reduction)[0] / 2)


def test_an_unplaced_station_is_declared_and_connected_but_not_pinned():
    """Check that a station without ``x``/``y`` is wired but leaves members unpinned."""
    fs = Flowsheet("unplaced")
    st = fs.add_valve_station("CV-1")
    assert all(u.pin_ is None for u in st.members)
    assert st.control.inlet.stream is not None


def test_a_placed_station_draws_without_a_finding():
    """Check that a pinned station validates cleanly and renders."""
    fs, _st = _sheet()
    # Tabulate a stream so stream-table-missing is not reported.
    fs.streams[0].properties = {"Flow (kg/h)": "4200"}
    assert fs.validate() == []
    assert "<svg" in fs.to_svg(diagram="p&id")


# --- Line numbers ------------------------------------------------------------


def test_the_run_takes_the_number_of_the_line_connected_to_it():
    """Check that the run inherits the number of the line feeding it."""
    fs = Flowsheet("numbered", line_numbering_scheme="{service}-{sequence}-{size}")
    feed = fs.add(units.Feed("IN"))
    st = fs.add_valve_station("CV-303", x=300, y=RUN_Y)
    fs.connect(feed.outlet, st.inlet, service="AE", sequence=303, size=80)
    assert st.control.inlet.stream.name == "AE-303-80"
    assert st.expansion.outlet.stream.name == "AE-303-80"


def test_a_branch_takes_the_number_the_station_was_given():
    """Check that bypass and drain legs carry the station's line number."""
    fs = Flowsheet("numbered", line_numbering_scheme="{service}-{sequence}-{size}")
    st = fs.add_valve_station("CV-303", x=300, y=RUN_Y, service="AE", sequence=303, size=80)
    assert st.bypass.inlet.stream.name == "AE-303-80"
    assert st.upstream_drain.inlet.stream.name == "AE-303-80"
    # The number continues through the bypass valve to the rejoin.
    assert st.bypass.outlet.stream.name == "AE-303-80"


# --- Refusals ----------------------------------------------------------------


def test_a_bypass_with_no_isolation_valves_to_go_round_is_refused():
    """Check that a bypass without isolation valves is refused."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="no isolation valves to tap outside of"):
        fs.add_valve_station("CV-1", isolation=False, bypass=True)


def test_a_drain_count_that_is_not_zero_one_or_two_is_refused():
    """Check that a drain count other than 0, 1 or 2 is refused."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="drains= is how many drain valves"):
        fs.add_valve_station("CV-1", drains=3)


def test_one_of_x_and_y_without_the_other_is_refused():
    """Check that ``x`` without ``y`` is refused."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="placed by"):
        fs.add_valve_station("CV-1", x=300)


def test_a_bypass_over_a_member_that_is_not_there_is_refused():
    """Check that ``bypass_over`` naming an omitted member is refused."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="told to leave out"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="reduction")


def test_a_bypass_over_something_that_is_not_a_member_is_refused():
    """Check that ``bypass_over`` naming an unknown role is refused."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="bypass_over names the member"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, bypass_over="drain")


# --- Run options without a drawn run -----------------------------------------


#: Each run option with a value that moves a pinned station. All four describe
#: a drawn run, which a station without ``x`` and ``y`` does not have.
RUN_WORDS = {
    "mirrored": True,
    "gap": 50.0,
    "bypass_rise": 80.0,
    "drain_drop": 60.0,
}


@pytest.mark.parametrize("word", list(RUN_WORDS))
def test_a_word_about_the_drawn_run_is_refused_where_there_is_no_run(word):
    """Check that a run option on an unplaced station is refused by name."""
    fs = Flowsheet("unplaced")
    with pytest.raises(ValueError) as raised:
        fs.add_valve_station("CV-1", **{word: RUN_WORDS[word]})
    assert f"{word}=" in str(raised.value)
    assert "Give x= and y=" in str(raised.value)


def test_all_four_together_are_named_in_the_one_refusal():
    """Check that one refusal names every run option given."""
    fs = Flowsheet("unplaced")
    with pytest.raises(ValueError) as raised:
        fs.add_valve_station("CV-1", **RUN_WORDS)
    assert "mirrored=, gap=, bypass_rise=, drain_drop=" in str(raised.value)


def test_mirrored_false_is_named_like_any_other_stated_run_option():
    """Check that ``mirrored=False`` is refused by name, though it matches the default."""
    fs = Flowsheet("unplaced")
    with pytest.raises(ValueError) as raised:
        fs.add_valve_station("CV-1", mirrored=False)
    assert "mirrored=" in str(raised.value)
    with pytest.raises(ValueError) as raised:
        fs.add_valve_station("CV-1", mirrored=False, gap=DEFAULT_GAP)
    assert "mirrored=, gap=" in str(raised.value)


@pytest.mark.parametrize("word", list(RUN_WORDS))
def test_the_same_word_is_taken_the_moment_the_station_has_a_run(word):
    """Check that each run option moves a pinned station.

    Both stations are pinned at the same point, so only the option can
    make them differ.
    """
    fs = Flowsheet("placed")
    plain = fs.add_valve_station("CV-1", x=300, y=RUN_Y)
    stated = fs.add_valve_station("CV-2", x=300, y=RUN_Y, **{word: RUN_WORDS[word]})
    fs.layout()
    assert _drawn(stated) != _drawn(plain)


def test_a_word_left_unsaid_is_the_default_it_always_was():
    """Check that unstated run options take their defaults once the run is drawn.

    An unplaced station given none of them is accepted, and a pinned station
    draws ``mirrored=False`` exactly as it draws the option left out.
    """
    fs = Flowsheet("mixed")
    unplaced = fs.add_valve_station("CV-1")
    assert all(u.pin_ is None for u in unplaced.members)
    placed = fs.add_valve_station("CV-2", x=300, y=RUN_Y)
    unmirrored = fs.add_valve_station("CV-3", x=300, y=RUN_Y, mirrored=False)
    fs.layout()
    assert _drawn(unmirrored) == _drawn(placed)
    on_the_run = [
        u
        for u in placed.members
        if u not in (placed.bypass, placed.upstream_drain, placed.downstream_drain)
    ]
    for before, after in zip(on_the_run, on_the_run[1:]):
        assert _box(after).x - _box(before).x_max == pytest.approx(DEFAULT_GAP)


def test_a_station_placed_on_a_stream_still_takes_mirrored_false():
    """Check that ``place_valve_station_on`` accepts ``mirrored=False``.

    A stream-relative station has a drawn run, so the option is kept.
    """
    fs = Flowsheet("on a stream")
    feed = fs.add(units.Feed("IN"))
    product = fs.add(units.Product("OUT"))
    run = fs.connect(feed.outlet, product.inlet)
    station = fs.place_valve_station_on(run, "CV-1", mirrored=False)
    assert station.control in fs.units


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(isolation=False, bypass=True),
        dict(drains=3),
        dict(x=300),
        dict(x=300, y=RUN_Y, reducers=False, bypass_over="reduction"),
        dict(mirrored=True, gap=50),
        dict(mirrored=False),
    ],
    ids=[
        "bypass_without_isolation",
        "bad_drain_count",
        "x_without_y",
        "bypass_over_a_role_left_out",
        "a_word_about_a_run_that_is_not_drawn",
        "mirrored_false_without_a_run",
    ],
)
def test_a_refused_call_leaves_the_sheet_exactly_as_it_was(kwargs):
    """Check that a refused call adds no unit or stream to the sheet."""
    fs = Flowsheet("bad")
    before_units, before_streams = list(fs.units), list(fs.streams)
    with pytest.raises(ValueError):
        fs.add_valve_station("CV-1", **kwargs)
    assert fs.units == before_units
    assert fs.streams == before_streams


def test_a_bypass_over_a_role_left_out_can_be_retried_with_the_same_tag():
    """Check that a refused call does not claim its tag, so a corrected retry succeeds."""
    fs = Flowsheet("bad")
    with pytest.raises(ValueError, match="told to leave out"):
        fs.add_valve_station("CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="reduction")
    station = fs.add_valve_station(
        "CV-1", x=300, y=RUN_Y, reducers=False, bypass_over="upstream_isolation"
    )
    assert station.control.name == "CV-1"


# --- Spec round trip ---------------------------------------------------------


def test_a_sheet_with_a_station_round_trips_through_the_spec():
    """Check that a sheet with a station reads back with the same units, frames and streams."""
    fs, st = _sheet(description="Reflux", service="AE", sequence=303, size=80)
    fs.layout()
    again = Flowsheet.from_dict(spec.to_dict(fs))
    again.layout()
    assert [u.name for u in again.units] == [u.name for u in fs.units]
    assert [(u.frame.x, u.frame.y) for u in again.units] == [
        (u.frame.x, u.frame.y) for u in fs.units
    ]
    assert [s.name for s in again.streams] == [s.name for s in fs.streams]


# --- Placement helpers -------------------------------------------------------


def test_port_offset_answers_where_a_nozzle_sits_in_its_own_box():
    """Check ``port_offset`` for an unpinned valve."""
    valve = units.Valve("HV-1")
    width, height = resolve_size(valve)
    assert port_offset(valve, "inlet") == pytest.approx((0.0, height / 2))
    assert port_offset(valve, "outlet") == pytest.approx((width, height / 2))


def test_port_offset_follows_the_placement_the_unit_carries():
    """Check that ``port_offset`` applies the unit's pinned mirroring."""
    valve = units.Valve("HV-1").pin(mirrored=True)
    width, height = resolve_size(valve)
    assert port_offset(valve, "inlet") == pytest.approx((width, height / 2))


def test_pin_by_port_puts_that_nozzle_on_the_coordinate_given():
    """Check that pinning by port places that nozzle on the given point."""
    fs = Flowsheet("pinned")
    valve = fs.add(units.Valve("HV-1")).pin(port="inlet", x=200, y=RUN_Y)
    fs.layout()
    assert port_point(valve, valve.frame, "inlet") == pytest.approx((200, RUN_Y))


def test_pin_by_port_is_idempotent():
    """Check that pinning by the same port twice gives the same pin."""
    valve = units.Valve("HV-1")
    valve.pin(port="inlet", x=200, y=RUN_Y)
    first = (valve.pin_.x, valve.pin_.y)
    valve.pin(port="inlet", x=200, y=RUN_Y)
    assert (valve.pin_.x, valve.pin_.y) == first


def test_pin_by_port_reads_only_the_axes_it_is_given():
    """Check that pinning by port on one axis keeps the other axis's pin."""
    valve = units.Valve("HV-1").pin(mirrored=True)
    valve.pin(x=200)
    valve.pin(port="inlet", y=RUN_Y)
    assert valve.pin_.x == 200
    assert valve.pin_.y == RUN_Y - resolve_size(valve)[1] / 2


def test_pin_by_port_applies_the_transform_from_the_same_call():
    """Check that pinning by port uses the orientation given in the same call."""
    turned = units.Valve("HV-1").pin(orientation=90, port="inlet", y=RUN_Y)
    assert turned.pin_.y == pytest.approx(RUN_Y)  # the turned inlet is on the top edge


def test_pin_by_a_port_the_unit_does_not_have_says_which_it_has():
    """Check that pinning by an unknown port is refused."""
    with pytest.raises(KeyError, match="no port 'suction' to pin by"):
        units.Valve("HV-1").pin(port="suction", x=10, y=10)


def test_pin_by_port_refuses_a_grid_cell():
    """Check that pinning by port with a grid cell is refused."""
    with pytest.raises(ValueError, match="has no nozzle in it"):
        units.Valve("HV-1").pin(port="inlet", col=2)


@pytest.mark.parametrize("kind, port", [(units.Feed, "outlet"), (units.Product, "inlet")])
def test_a_flag_is_pinned_by_its_nozzle_without_being_asked(kind, port):
    """Check that a flag is pinned by its only nozzle by default."""
    fs = Flowsheet("flag")
    flag = fs.add(kind("F")).pin(x=200, y=RUN_Y)
    fs.layout()
    assert port_point(flag, flag.frame, port) == pytest.approx((200, RUN_Y))


def test_a_flag_can_still_be_pinned_by_its_corner():
    """Check that ``port=None`` pins a flag by its corner, as the spec reader needs."""
    assert units.Feed("F").pin(port=None, x=200, y=100).pin_.x == 200


def test_a_flag_still_takes_a_grid_cell():
    """Check that a flag pinned to a grid cell is not treated as pinned by port."""
    flag = units.Feed("F").pin(col=2, row=1)
    assert (flag.pin_.col, flag.pin_.row) == (2, 1)
