"""Check pipe furniture: kept out of the grid and set on its routed pipe."""

from __future__ import annotations

import pytest

from pandid import ControlValve, Feed, Flowsheet, GravitySeparator, Product, Reactor, Valve
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point


def _drawing(fs: Flowsheet) -> str:
    """Return a snapshot of every frame and route on a routed sheet.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    str
        Each unit's frame and each stream's waypoints, as text.
    """
    units = [(unit.name, unit.frame) for unit in fs.units]
    routes = [(stream.name, stream.route) for stream in fs.streams]
    return repr((units, routes))


def _clean(fs: Flowsheet) -> bool:
    """Return whether a routed sheet has no hard finding.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    bool
        Whether every hard count is zero.
    """
    quality = measure_final(fs)
    return quality.hard == (0,) * len(quality.hard) and not quality.hard_conflicts


def test_a_pinned_hand_wired_valve_splits_two_mounted_runs() -> None:
    """Check that mounted valves sit either side of a pinned connect() valve."""
    fs = Flowsheet("Mixed run")
    feed = fs.add(Feed("Feed"))
    middle = fs.add(Valve("HV-M")).pin(x=400, y=192.5)
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, middle.inlet)
    downstream = fs.connect(middle.outlet, product.inlet)
    first = fs.add(Valve("HV-A"), on=upstream)
    second = fs.add(Valve("HV-B"), on=downstream)

    fs.route()
    assert fs._mounted_layout is True
    assert middle.frame is not None and (middle.frame.x, middle.frame.y) == (400, 192.5)
    assert feed.frame is not None and product.frame is not None
    assert first.frame is not None and second.frame is not None
    assert feed.frame.x < first.frame.x < middle.frame.x < second.frame.x < product.frame.x
    assert _clean(fs)


def test_a_chain_without_room_is_drawn_and_named() -> None:
    """Check that furniture too long for its pinned run is drawn and reported as overlap."""
    fs = Flowsheet("No room")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=160, y=100)
    run = fs.connect(feed.outlet, product.inlet)
    for index, at in enumerate((0.25, 0.5, 0.75)):
        fs.add(Valve(f"HV-{index}"), on=run, at=at)

    fs.route()
    assert all(unit.frame is not None for unit in fs.units)
    findings = [issue for issue in fs.validate() if issue.code == "unit-overlap"]
    assert findings and all(issue.severity == "error" for issue in findings)
    assert any("HV-" in issue.message for issue in findings)


def test_a_device_on_a_return_run_is_mounted() -> None:
    """Check that a valve on a return line is set on its pipe."""
    fs = Flowsheet("Return run")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101", n_feeds=2))
    separator = fs.add(GravitySeparator("S-101"))
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed_1)
    fs.connect(reactor.outlet, separator.feed)
    fs.connect(separator.overflow, product.inlet)
    back = fs.connect(separator.underflow, reactor.feed_2)
    valve = fs.add(Valve("HV-R"), on=back)

    fs.route()
    assert fs._mounted_layout is True
    assert any(segment.is_recycle for segment in back._logical_segments)
    assert valve.frame is not None
    assert _clean(fs)


def test_a_free_hand_wired_station_beside_mounted_devices() -> None:
    """Check that a hand-wired station beside a mounted valve is set as one assembly."""
    fs = Flowsheet("Mixed furniture")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    station = fs.add_valve_station("CV-101")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)
    other_feed = fs.add(Feed("Water"))
    other_product = fs.add(Product("Drain"))
    run = fs.connect(other_feed.outlet, other_product.inlet)
    fs.add(Valve("HV-1"), on=run)

    fs.route()
    assert fs._mounted_layout is True
    main = [
        unit
        for unit in station.members
        if unit not in (station.bypass, station.upstream_drain, station.downstream_drain)
    ]
    assert (
        len(
            {
                round(port_point(unit, unit.frame, "inlet")[1], 3)
                for unit in main
                if unit.frame is not None
            }
        )
        == 1
    )
    assert _clean(fs)


def test_a_device_pinned_on_a_line_stays_in_the_grid() -> None:
    """Check that a device pinned on a line is drawn at its pin and stays in the grid."""
    fs = Flowsheet("Pinned mounted device")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    valve = fs.add(Valve("HV-1").pin(x=300, y=200), on=run)

    fs.route()
    assert fs._mounted_layout is False
    assert valve.frame is not None and (valve.frame.x, valve.frame.y) == (300, 200)


def test_routing_a_mounted_sheet_again_draws_the_same_sheet() -> None:
    """Check that layout and routing a mounted sheet twice give one drawing."""
    fs = Flowsheet("Repeatable")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101"))
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, product.inlet)
    fs.add(Valve("HV-1"), on=run, at=0.3)
    fs.add_valve_station("CV-101", on=run, at=0.7)

    fs.route()
    first = _drawing(fs)
    fs.route()
    assert _drawing(fs) == first
    fs.layout()
    fs.route()
    assert _drawing(fs) == first
    assert fs.to_svg() == fs.to_svg()


@pytest.mark.parametrize(("orientation", "mirrored"), [(None, None), (0, None), (None, "y")])
def test_a_control_valve_sits_on_its_pipe_without_a_jog(
    orientation: int | None, mirrored: str | None
) -> None:
    """Check that a turned or mirrored valve keeps both nozzles on the pipe.

    Parameters
    ----------
    orientation : int or None
        Turn the author pinned, if any.
    mirrored : str or None
        Mirroring the author pinned, if any.
    """
    fs = Flowsheet("No jog")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet)
    valve = ControlValve("FV-101")
    if orientation is not None:
        valve.pin(orientation=orientation)
    if mirrored is not None:
        valve.pin(mirrored=mirrored)
    fs.add(valve, on=line)

    fs.route()
    assert feed.frame is not None and valve.frame is not None
    pipe_y = port_point(feed, feed.frame, "outlet")[1]
    assert port_point(valve, valve.frame, "inlet")[1] == pytest.approx(pipe_y)
    assert port_point(valve, valve.frame, "outlet")[1] == pytest.approx(pipe_y)
    assert measure_final(fs).bends == 0


@pytest.mark.parametrize("mirrored", [None, True])
def test_valves_on_an_upright_pipe_turn_and_get_room(mirrored: bool | None) -> None:
    """Check that valves between stacked units are turned onto the pipe and fit.

    Parameters
    ----------
    mirrored : bool or None
        Mirroring the author pinned, which states no turn.
    """
    from pandid import Cyclone, HeatExchanger
    from pandid.layout.mounted import ALONG

    fs = Flowsheet("Upright pipe")
    feed = fs.add(Feed("Feed"))
    cyclone = fs.add(Cyclone("CY-101"))
    cooler = fs.add(HeatExchanger("E-101"))
    gas = fs.add(Product("Gas"))
    solids = fs.add(Product("Solids"))
    fs.connect(feed.outlet, cyclone.feed)
    fs.connect(cyclone.overflow, gas.inlet)
    drop = fs.connect(cyclone.underflow, cooler.shell_in)
    fs.connect(cooler.shell_out, solids.inlet)
    valves = []
    for index in range(3):
        valve = Valve(f"HV-{index}")
        if mirrored is not None:
            valve.pin(mirrored=mirrored)
        valves.append(fs.add(valve, on=drop))

    fs.route()
    assert cyclone.frame is not None and cooler.frame is not None
    top = port_point(cyclone, cyclone.frame, "underflow")
    bottom = port_point(cooler, cooler.frame, "shell_in")
    assert top[0] == pytest.approx(bottom[0])
    spans = []
    for valve in valves:
        assert valve.frame is not None
        inlet = port_point(valve, valve.frame, "inlet")
        outlet = port_point(valve, valve.frame, "outlet")
        assert inlet[0] == outlet[0] == pytest.approx(top[0])
        spans.append((inlet[1], outlet[1]))
    assert top[1] < spans[0][0] and spans[-1][1] < bottom[1]
    assert all(above[1] + ALONG <= below[0] + 1e-6 for above, below in zip(spans, spans[1:]))
    assert all(inlet < outlet for inlet, outlet in spans)
    assert _clean(fs)


def test_an_angle_relief_valve_is_placed_like_equipment() -> None:
    """Check that a valve that turns the pipe stays in the grid, clear of its flag."""
    from pandid import ReliefValve, Vessel
    from pandid.layout.mounted import mounted_runs

    fs = Flowsheet("Angle relief")
    feed = fs.add(Feed("Feed"))
    drum = fs.add(Vessel("V-101"))
    product = fs.add(Product("Product"))
    psv = fs.add(ReliefValve("PSV-101", variant="psv"))
    flare = fs.add(Product("To Flare"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, product.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)

    fs.route()
    assert psv not in {u for run in mounted_runs(fs) for u in run.elements}
    assert _clean(fs)


def test_a_station_and_a_neighbouring_valve_each_get_room() -> None:
    """Check that a station and a valve on the next line into one exchanger stay apart."""
    from pandid import ShellAndTubeExchanger

    fs = Flowsheet("Two lines into one exchanger")
    vapour = fs.add(Feed("Vapour"))
    water = fs.add(Feed("CWSH", header=True))
    condenser = fs.add(
        ShellAndTubeExchanger("C-301", variant="straight_tubes", width=130, height=40)
    )
    condensate = fs.add(Product("Condensate"))
    water_return = fs.add(Product("CWRH", header=True))
    line = fs.connect(vapour.outlet, condenser.shell_in)
    cooling = fs.connect(water.outlet, condenser.tube_in)
    fs.connect(condenser.shell_out, condensate.inlet)
    fs.connect(condenser.tube_out, water_return.inlet)
    station = fs.add_valve_station("CV-301", on=line)
    valve = fs.add(Valve("HV-311"), on=cooling)

    fs.route()
    assert _clean(fs)
    assert valve.frame is not None
    boxes = [unit.frame for unit in station.members if unit.frame is not None]
    left, right = min(b.x for b in boxes), max(b.x_max for b in boxes)
    top, bottom = min(b.y for b in boxes), max(b.y_max for b in boxes)
    frame = valve.frame
    assert frame.x_max < left or frame.x > right or frame.y_max < top or frame.y > bottom


def test_a_pinned_valve_on_a_westward_line_follows_the_flow() -> None:
    """Check that a turn-pinned valve is mirrored along the pipe, not drawn backwards."""
    fs = Flowsheet("Westward")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=600, y=100).pin(mirrored=True)
    product = fs.add(Product("Product")).pin(port="inlet", x=100, y=100).pin(mirrored=True)
    line = fs.connect(feed.outlet, product.inlet)
    valve = fs.add(ControlValve("FV-101").pin(orientation=0), on=line)

    fs.route()
    assert valve.frame is not None
    inlet = port_point(valve, valve.frame, "inlet")
    outlet = port_point(valve, valve.frame, "outlet")
    actuator = port_point(valve, valve.frame, "actuator")
    assert outlet[0] < inlet[0]
    assert inlet[1] == outlet[1] == pytest.approx(100)
    assert actuator[1] < 100
    assert measure_final(fs).bends == 0


def test_an_actuator_needs_a_clear_exit() -> None:
    """Check that a spot is refused when a unit sits in a connected actuator's exit."""
    from pandid import Instrument
    from pandid.geometry import Frame
    from pandid.layout.mounted import _clear

    fs = Flowsheet("Actuator exit")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    valve = fs.add(ControlValve("FV-101"), on=fs.connect(feed.outlet, product.inlet))
    controller = fs.add(Instrument("FIC-101"))
    fs.connect(controller.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()
    assert valve.frame is not None
    actuator = port_point(valve, valve.frame, "actuator")
    blocker = fs.add(Product("Blocker"))
    blocker.frame = Frame(x=actuator[0] - 5, y=actuator[1] - 15, w=10, h=5)

    assert _clear({valve: valve.frame}, [], True, [], [])
    assert not _clear({valve: valve.frame}, [blocker], True, [], [])


def test_an_eccentric_reducer_is_set_on_its_pipe() -> None:
    """Check that a reducer with offset centrelines still runs straight through."""
    from pandid import Reducer
    from pandid.layout.mounted import mounted_runs

    fs = Flowsheet("Eccentric reducer")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    reducer = fs.add(
        Reducer("RD-401", variant="eccentric"), on=fs.connect(feed.outlet, product.inlet)
    )

    fs.layout()
    assert [run.elements for run in mounted_runs(fs)] == [(reducer,)]


def test_a_vent_control_valve_keeps_its_loop_clear() -> None:
    """Check that a control loop on a vent valve draws no line through the valve."""
    from pandid import Vessel

    fs = Flowsheet("Vent control")
    feed = fs.add(Feed("Feed"))
    drum = fs.add(Vessel("V-101"))
    product = fs.add(Product("Product"))
    scrubber = fs.add(Product("To Vent Scrubber"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, product.inlet)
    vent = fs.connect(drum.vent, scrubber.inlet)
    valve = fs.add(ControlValve("PV-101"), on=vent)
    fs.add_control_loop("P", 101, measuring=vent, acting_on=valve)

    fs.route()
    quality = measure_final(fs)
    assert not quality.hard_conflicts
    assert not any(issue.code in ("route-crosses-unit", "unit-overlap") for issue in fs.validate())
