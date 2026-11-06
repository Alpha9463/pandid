"""Check pipe furniture: kept out of the grid and set on its routed pipe."""

from __future__ import annotations

import pytest

from pandid import (
    ControlValve,
    Feed,
    Flowsheet,
    GravitySeparator,
    Product,
    Reactor,
    Valve,
    ValveStation,
)
from _quality import measure_final
from pandid.portgeom import port_point


def _drawing(fs: Flowsheet) -> str:
    """Return a snapshot of every frame and route on a routed sheet."""
    units = [(unit.name, unit.frame) for unit in fs.units]
    routes = [(stream.name, stream.route) for stream in fs.streams]
    return repr((units, routes))


def _clean(fs: Flowsheet) -> bool:
    """Return whether a routed sheet has no hard finding."""
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
    """Check that a turned or mirrored valve keeps both nozzles on the pipe."""
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


@pytest.mark.parametrize(
    ("upright", "at"),
    [(False, 100.0), (False, 125.7), (False, 126.3), (False, 127.8), (True, -128.0)],
)
def test_a_valve_set_on_a_shifted_line_adds_no_bends(upright: bool, at: float) -> None:
    """Check that a valve set on a line shifted across the sheet adds no bends."""
    fs = Flowsheet("Shifted")
    if upright:
        start = fs.add(Valve("A")).pin(orientation=90).pin(port="outlet", x=at, y=100)
        end = fs.add(Valve("B")).pin(orientation=90).pin(port="inlet", x=at, y=500)
        valve = ControlValve("CV", width=27.3, height=31.7).pin(orientation=90)
    else:
        start = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=at)
        end = fs.add(Product("Product")).pin(port="inlet", x=500, y=at)
        valve = ControlValve("FV-101")
    fs.add(valve, on=fs.connect(start.outlet, end.inlet))

    fs.route()
    assert measure_final(fs).bends == 0


@pytest.mark.parametrize("at", [-128.0, 211.3])
@pytest.mark.parametrize("sized", [False, True])
@pytest.mark.parametrize("mirrored", [False, True, "x", "y", "xy"])
@pytest.mark.parametrize("turn", [90, 270, 0, 180])
@pytest.mark.parametrize("flow", [1, -1])
def test_a_turned_and_mirrored_valve_sits_on_its_pipe(
    flow: int, turn: int, mirrored: bool | str, sized: bool, at: float
) -> None:
    """Check that a valve with a stated turn and mirror sits in its line with the flow."""
    from pandid.portgeom import port_offset

    upright = turn in (90, 270)
    first, last = (100.0, 500.0)[::flow]
    end_turn = (90 if upright else 0) + (0 if flow > 0 else 180)
    fs = Flowsheet("Turned and mirrored")
    start = fs.add(Valve("A")).pin(orientation=end_turn)
    end = fs.add(Valve("B")).pin(orientation=end_turn)
    if upright:
        start.pin(port="outlet", x=at, y=first)
        end.pin(port="inlet", x=at, y=last)
    else:
        start.pin(port="outlet", x=first, y=at)
        end.pin(port="inlet", x=last, y=at)
    valve = ControlValve("CV", width=27.3, height=31.7) if sized else ControlValve("CV")
    valve.pin(orientation=turn, mirrored=mirrored)
    stated = valve.pin_
    assert stated is not None
    across = 0 if upright else 1
    inlet, outlet = (port_offset(valve, name)[1 - across] for name in ("inlet", "outlet"))
    backwards = (outlet - inlet) * flow < 0
    fs.add(valve, on=fs.connect(start.outlet, end.inlet))

    fs.route()
    assert valve.frame is not None
    for name in ("inlet", "outlet"):
        assert port_point(valve, valve.frame, name)[across] == pytest.approx(at, abs=1e-6)
    assert measure_final(fs).bends == 0
    drawn = valve.frame
    assert (drawn.orientation, drawn.mirror_y) == (turn, stated.mirror_y)
    assert drawn.mirrored == (stated.mirrored != backwards)
    warned = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert bool(warned) == backwards
    assert all("end for end" in said for said in warned)


def _reversed_valve(turn: int, mirrored: bool | str, face: bool) -> tuple[Flowsheet, ControlValve]:
    """Return a sheet with a valve whose stated pose runs it against its line."""
    from pandid.portgeom import port_faces

    upright = turn in (90, 270)
    fs = Flowsheet("Reversed")
    start = fs.add(Valve("A")).pin(orientation=90 if upright else 0)
    end = fs.add(Valve("B")).pin(orientation=90 if upright else 0)
    if upright:
        start.pin(port="outlet", x=300, y=100)
        end.pin(port="inlet", x=300, y=500)
    else:
        start.pin(port="outlet", x=100, y=300)
        end.pin(port="inlet", x=500, y=300)
    valve = ControlValve("CV").pin(orientation=turn, mirrored=mirrored)
    if face:
        valve.nozzle("actuator", port_faces(valve, "actuator")[0])
    fs.add(valve, on=fs.connect(start.outlet, end.inlet))
    return fs, valve


@pytest.mark.parametrize("face", [False, True])
@pytest.mark.parametrize(
    ("turn", "mirrored"), [(0, True), (0, "xy"), (180, False), (180, "y"), (90, True), (270, False)]
)
def test_each_pin_offered_for_a_reversed_valve_clears_the_warning(
    turn: int, mirrored: bool | str, face: bool
) -> None:
    """Check that every pin the end-for-end advice offers is taken and draws as pinned."""
    import ast
    import re

    fs, _ = _reversed_valve(turn, mirrored, face)
    fs.route()
    warned = [i.message for i in fs.validate() if i.code == "pin-not-honored"]
    assert len(warned) == 1 and "end for end" in warned[0]
    offered = re.findall(r"(mirrored|orientation)=(\S+) to (?:draw|keep)", warned[0])
    assert offered[0][0] == "mirrored"
    assert face or [name for name, _ in offered] == ["mirrored", "orientation"]
    for name, value in offered:
        fs, valve = _reversed_valve(turn, mirrored, face)
        valve.pin(**{name: ast.literal_eval(value)})
        fs.route()
        assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_a_line_between_two_devices_set_on_it_adds_no_bends() -> None:
    """Check that the lines either side of a reducer set after a valve on one pipe draw straight."""
    from pandid import Reducer
    from pandid.route_geometry import stream_polyline
    from pandid.routing.metrics import real_bends

    fs = Flowsheet("Rounding")
    start = fs.add(Valve("A")).pin(orientation=90).pin(port="outlet", x=100, y=100)
    end = fs.add(Product("B")).pin(port="inlet", x=700, y=127.8)
    line = fs.connect(start.outlet, end.inlet)
    valve = fs.add(ControlValve("CV"), on=line, at=0.4)
    reducer = fs.add(Reducer("R", height=27.8), on=line, at=0.7)

    fs.route()
    for stream in (valve.outlet.stream, reducer.outlet.stream):
        assert stream is not None
        assert real_bends(stream_polyline(stream)) == 0


def test_a_valve_whose_nozzles_sit_apart_keeps_the_frame_that_fits_its_line() -> None:
    """Check that a frame whose outlet misses the line is not chosen over one that fits.

    The two nozzles of this drawing sit 1.0 apart across the line, so the frame
    that lands the inlet exactly puts the outlet a full unit off.
    """
    from pandid.render.symbols import Symbol, default_registry

    default_registry.register(
        "valve",
        Symbol(
            svg='<g id="skew"><path d="M0 80.1 L50 81.1"/></g>',
            width=50,
            height=100,
            ports={"inlet": (0, 80.1), "outlet": (50, 81.1)},
        ),
        variant="skew",
    )
    try:
        fs = Flowsheet("Offset ports")
        feed = fs.add(Feed("A")).pin(port="outlet", x=100, y=125.7)
        prod = fs.add(Product("B")).pin(port="inlet", x=500, y=125.7)
        valve = fs.add(
            Valve("V", variant="skew").pin(orientation=0), on=fs.connect(feed.outlet, prod.inlet)
        )
        fs.route()
        assert valve.frame is not None
        assert port_point(valve, valve.frame, "inlet")[1] == pytest.approx(125.7)
    finally:
        default_registry._symbols.pop(("valve", "skew"), None)


@pytest.mark.parametrize("mirrored", [None, True])
def test_valves_on_an_upright_pipe_turn_and_get_room(mirrored: bool | None) -> None:
    """Check that valves between stacked units are turned onto the pipe and fit."""
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


def test_an_actuator_exit_keeps_off_a_units_side() -> None:
    """Check that an exit kept a lane clear refuses a spot beside a unit's side."""
    from pandid import Instrument, Vessel
    from pandid.geometry import Frame
    from pandid.layout.mounted import _clear
    from pandid.routing.visibility import MARGIN

    fs = Flowsheet("Actuator beside a vessel")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    valve = fs.add(ControlValve("FV-101"), on=fs.connect(feed.outlet, product.inlet))
    controller = fs.add(Instrument("FIC-101"))
    fs.connect(controller.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()
    assert valve.frame is not None
    x, y = port_point(valve, valve.frame, "actuator")
    vessel = fs.add(Vessel("V-101"))
    # The vessel's west side runs half a pixel east of the exit.
    vessel.frame = Frame(x=x + 0.5, y=y - 100, w=60, h=80)

    assert _clear({valve: valve.frame}, [vessel], True, [], [])
    assert not _clear({valve: valve.frame}, [vessel], True, [], [], (), MARGIN)
    vessel.frame = Frame(x=x + 20, y=y - 100, w=60, h=80)
    assert _clear({valve: valve.frame}, [vessel], True, [], [], (), MARGIN)


def _cooling(
    drum_height: float, cooler_at: tuple[float, float], face: str | None
) -> tuple[Flowsheet, ControlValve]:
    """Build a drum drained through a level valve and a pump to a cooler."""
    from pandid import Pump, ShellAndTubeExchanger, Vessel

    fs = Flowsheet("Cooling")
    feed, drum = fs.add(Feed("Feed")), fs.add(Vessel("V-101", width=60, height=drum_height))
    valve, pump = fs.add(ControlValve("LV-101")), fs.add(Pump("P-101"))
    cooler, out = fs.add(ShellAndTubeExchanger("E-101")), fs.add(Product("Product"))
    cws, cwr = fs.add(Feed("CWS")), fs.add(Product("CWR"))
    drum.pin(x=280, y=180)
    cooler.pin(x=cooler_at[0], y=cooler_at[1])
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, valve.inlet)
    fs.connect(valve.outlet, pump.suction)
    fs.connect(pump.discharge, cooler.tube_in)
    fs.connect(cooler.tube_out, out.inlet)
    fs.connect(cws.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr.inlet)
    fs.add_control_loop("L", 101, measuring=drum, acting_on=valve, face=face)
    return fs, valve


@pytest.mark.parametrize(
    ("drum_height", "cooler_at", "near_nozzle", "face"),
    [
        (140, (500, 160), 1, "E"),
        (100, (420, 240), 2, "E"),
        (80, (420, 140), 1, "E"),
        (140, (400, 120), 3, None),
    ],
)
def test_a_valve_moved_clear_of_a_unit_is_kept_only_if_no_finding_grows(
    drum_height: float, cooler_at: tuple[float, float], near_nozzle: int, face: str | None
) -> None:
    """Check that no line crosses a unit, nor more arrowheads than main draws."""
    fs, _ = _cooling(drum_height, cooler_at, face)
    fs.to_svg(diagram="p&id")
    codes = [i.code for i in fs.validate(diagram="p&id")]
    assert "route-crosses-unit" not in codes
    assert codes.count("route-crosses-near-nozzle") <= near_nozzle


def test_a_relayout_inside_the_exit_clear_trial_keeps_the_exit_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that a sheet laid out again inside the exit-clear trial keeps the exit clear."""
    from pandid.layout import layered
    from pandid.layout.conflicts import boxes_overlap
    from pandid.layout.mounted import _signal_exits
    from pandid.layout.stages import process_units
    from pandid.portgeom import unit_box
    from pandid.routing.visibility import MARGIN

    # Every layout finds a flag's line to level, so each settle lays out again.
    monkeypatch.setattr(layered, "_level", lambda layers, segs, held, move, rises: not move)
    fs, valve = _cooling(140, (520, 160), "E")
    fs.route()

    assert valve.frame is not None
    exits = _signal_exits({valve: valve.frame})
    assert exits
    for unit in process_units(fs):
        if unit is not valve and unit.frame is not None:
            assert not any(boxes_overlap(box, unit_box(unit, unit.frame), MARGIN) for box in exits)


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


def test_a_valve_keeps_clear_of_a_balloon_pinned_on_both_axes() -> None:
    """Check that a valve steps along its pipe off a balloon pinned on top of it."""
    from pandid import Vessel

    fs = Flowsheet("Pinned balloon")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=200)
    drum = fs.add(Vessel("V-101")).pin(x=700, y=150)
    valve = fs.add(Valve("HV-1"), on=fs.connect(feed.outlet, drum.inlet))
    lt = fs.add_instrument("LT", 101, sensing=drum, face="N")
    fs.layout()
    assert valve.frame is not None
    lt.pin(x=valve.frame.cx - 22, y=valve.frame.cy - 44)

    fs.route()
    assert not any(issue.code == "unit-overlap" for issue in fs.validate())


def test_a_valve_is_not_set_on_a_pinned_balloon_main_draws_clear_of() -> None:
    """Check that a level loop with its transmitter pinned clear of everything stays clear."""
    from pandid import Pump, Vessel

    fs = Flowsheet("Level control")
    drum = fs.add(Vessel("V-101"))
    pump = fs.add(Pump("P-101"))
    fs.connect(drum.outlet, pump.suction)
    fs.add(ControlValve("LV-101"), on=fs.connect(pump.discharge, fs.add(Vessel("V-102")).inlet))
    lt = fs.add_instrument("LT", 101, sensing=drum, face="E").pin(x=350, y=50)
    fs.add_instrument("LIC", 101, near=lt, face="E")

    fs.route()
    assert not any(issue.code == "unit-overlap" for issue in fs.validate())


def _upright_at(station: ValveStation) -> float:
    """Return the x of a station whose run is drawn down one line."""
    branch = (station.bypass, station.upstream_drain, station.downstream_drain)
    points = []
    for unit in station.members:
        if unit not in branch:
            assert unit.frame is not None
            points += [port_point(unit, unit.frame, name) for name in ("inlet", "outlet")]
    assert all(x == pytest.approx(points[0][0]) for x, _ in points)
    assert [y for _, y in points] == sorted(y for _, y in points)
    return points[0][0]


def test_a_station_between_row_pinned_vessels_stands_on_its_upright_leg() -> None:
    """Check that a station between stacked vessels is turned onto an upright leg with room."""
    from pandid import Vessel

    fs = Flowsheet("Station between rows")
    upper = fs.add(Vessel("V-1")).pin(row=1, col=1)
    lower = fs.add(Vessel("V-2")).pin(row=2, col=1)
    station = fs.add_valve_station("FV-101", on=fs.connect(upper.outlet, lower.inlet))

    fs.route()
    _upright_at(station)
    assert not fs.validate()
    assert _clean(fs)


def test_a_station_on_a_stacked_drop_stands_on_it() -> None:
    """Check that a station on a pipe joining stacked nozzles is drawn upright with room."""
    from pandid import HeatExchanger

    fs = Flowsheet("Station on a drop")
    upper = fs.add(HeatExchanger("E-1"))
    lower = fs.add(HeatExchanger("E-2"))
    station = fs.add_valve_station("FV-101", on=fs.connect(upper.shell_out, lower.shell_in))

    fs.route()
    assert upper.frame is not None and lower.frame is not None
    top = port_point(upper, upper.frame, "shell_out")
    assert top[0] == pytest.approx(port_point(lower, lower.frame, "shell_in")[0])
    assert _upright_at(station) == pytest.approx(top[0])
    assert not fs.validate()
    assert _clean(fs)
    bypass, valve = station.bypass, station.control
    assert bypass is not None and bypass.frame is not None and valve.frame is not None
    assert valve.frame.label_pos == ("left" if bypass.frame.cx > top[0] else "right")


def test_a_station_set_part_way_down_a_drop_gets_room_where_it_is_wanted() -> None:
    """Check that a station set at=0.25 on a drop, with a tap below it, is drawn with room."""
    from pandid import HeatExchanger

    fs = Flowsheet("Station part way down a drop")
    upper = fs.add(HeatExchanger("E-1"))
    lower = fs.add(HeatExchanger("E-2"))
    line = fs.connect(upper.shell_out, lower.shell_in)
    station = fs.add_valve_station("FV-101", on=line, at=0.25)
    fs.add_instrument("PI", 201, sensing=line, at=0.5)

    fs.route()
    assert upper.frame is not None
    assert _upright_at(station) == pytest.approx(port_point(upper, upper.frame, "shell_out")[0])
    assert not fs.validate()


def test_an_angle_valve_is_set_at_its_lines_corner() -> None:
    """Check that the line turns through an angle valve with no bend of its own."""
    from pandid import Vessel
    from pandid.route_geometry import stream_polyline
    from pandid.routing.metrics import real_bends

    fs = Flowsheet("Angle valve")
    feed = fs.add(Feed("F")).pin(row=1, col=1)
    drum = fs.add(Vessel("V-2")).pin(row=2, col=2)
    valve = fs.add(Valve("HV-1", variant="angle"), on=fs.connect(feed.outlet, drum.inlet))

    fs.route()
    inlet, outlet = valve.inlet.stream, valve.outlet.stream
    assert inlet is not None and outlet is not None
    assert real_bends(stream_polyline(inlet)) + real_bends(stream_polyline(outlet)) <= 1
    assert _clean(fs)


def test_valves_either_side_of_an_angle_valve_keep_their_order() -> None:
    """Check that valves before and after a cornered angle valve stay on their own legs."""
    from pandid import Vessel
    from pandid.route_geometry import stream_polyline
    from pandid.routing.metrics import real_bends

    fs = Flowsheet("Angle valve between valves")
    feed = fs.add(Feed("F")).pin(row=1, col=1)
    drum = fs.add(Vessel("V-2")).pin(row=2, col=2)
    line = fs.connect(feed.outlet, drum.inlet)
    first = fs.add(Valve("HV-0"), on=line, at=0.2)
    angle = fs.add(Valve("HV-1", variant="angle"), on=line, at=0.5)
    last = fs.add(Valve("HV-2"), on=line, at=0.8)

    fs.route()
    assert first.frame is not None and angle.frame is not None and last.frame is not None
    inlet = port_point(angle, angle.frame, "inlet")
    outlet = port_point(angle, angle.frame, "outlet")
    assert port_point(first, first.frame, "outlet")[1] == pytest.approx(inlet[1])
    assert port_point(last, last.frame, "inlet")[0] == pytest.approx(outlet[0])
    paths = [stream_polyline(s) for s in fs.streams]
    assert sum(map(real_bends, paths)) <= 1
    assert _clean(fs)


def test_an_angle_valve_off_a_package_turns_its_corner_outside_the_frame() -> None:
    """Check that an angle valve on a line leaving a package is set at a corner off its frame."""
    from pandid import Pump, Vessel
    from pandid.route_geometry import stream_polyline
    from pandid.routing.metrics import real_bends

    fs = Flowsheet("Angle valve off a package")
    feed = fs.add(Feed("F")).pin(row=1, col=1)
    pump = fs.add(Pump("P-1")).pin(row=1, col=2)
    drum = fs.add(Vessel("V-2")).pin(row=2, col=3)
    fs.connect(feed.outlet, pump.suction)
    valve = fs.add(Valve("HV-1", variant="angle"), on=fs.connect(pump.discharge, drum.inlet))
    fs.package("PK-1", [pump])

    fs.route()
    inlet, outlet = valve.inlet.stream, valve.outlet.stream
    assert inlet is not None and outlet is not None
    assert real_bends(stream_polyline(inlet)) + real_bends(stream_polyline(outlet)) <= 1
    assert not [issue for issue in fs.validate() if issue.code == "package-encloses"]
    assert _clean(fs)
