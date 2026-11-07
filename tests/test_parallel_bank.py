"""Check that a parallel bank between a splitter and a mixer draws planar."""

import pytest

from pandid import Flowsheet, ShellAndTubeExchanger, units as U
from pandid.devices import ControlValve
from pandid.streams import Stream
from pandid.layout.attach import stream_path
from pandid.layout.conflicts import boxes_overlap
from pandid.layout.control import _flaws, _shared, _taps_off
from pandid.layout import layered, mounted
from pandid.layout.layered import COL_GAP, LANE_PITCH
from pandid.layout.mounted import ALONG, GAP
from _quality import measure_final
from pandid.portgeom import resolve_size, unit_box
from pandid.render import symbols
from pandid.route_geometry import stream_polyline
from pandid.routing import lanes
from pandid.routing.metrics import real_bends
from pandid.routing.visibility import MIN_ESCAPE


def _bank(n: int, exchangers: bool) -> Flowsheet:
    """Return n pumps, each with an exchanger if asked, between SP and MX."""
    fs = Flowsheet(f"Bank of {n}")
    feed, product = fs.add(U.Feed("F")), fs.add(U.Product("P"))
    sp = fs.add(U.Splitter("SP", n_outlets=n))
    mx = fs.add(U.Mixer("MX", n_inlets=n))
    fs.connect(feed.outlet, sp.inlet)
    fs.connect(mx.outlet, product.inlet)
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        fs.connect(outlet, pump.suction)
        if exchangers:
            exchanger = fs.add(ShellAndTubeExchanger(f"E-{i}"))
            fs.connect(pump.discharge, exchanger.tube_in)
            fs.connect(exchanger.tube_out, inlet)
        else:
            fs.connect(pump.discharge, inlet)
    return fs


@pytest.mark.parametrize(("n", "exchangers"), [(6, False), (12, False), (4, True), (8, True)])
def test_a_parallel_bank_draws_without_crossings_or_crowding(n, exchangers):
    fs = _bank(n, exchangers)
    fs.route()
    assert measure_final(fs).crossings == 0
    codes = {issue.code for issue in fs.validate()}
    assert not codes & {"nozzles-crowded", "lines-crowded"}
    assert _flaws(fs)["line-on-line"] == 0
    # A lateral turns twice at most, so none loops round its header.
    for s in fs.streams:
        if {s.source.owner.name, s.dest.owner.name} & {"SP", "MX"}:
            assert real_bends(stream_polyline(s)) <= 2, s.name


def test_a_header_face_grows_with_its_nozzles_and_keeps_a_stated_height():
    fs = Flowsheet("Headers")
    two, six = fs.add(U.Mixer("M-1")), fs.add(U.Mixer("M-2", n_inlets=6))
    stated = fs.add(U.Splitter("SP-1", n_outlets=6, height=80))
    fs.layout()
    assert two.frame is not None and six.frame is not None and stated.frame is not None
    assert (two.frame.w, two.frame.h) == (50, 50)
    assert (six.frame.w, six.frame.h) == (50, 130)
    assert stated.frame.h == 80


def test_a_layer_gap_widens_to_give_each_lateral_a_lane():
    fs = _bank(16, exchangers=False)
    fs.layout()
    sp, pump = fs.units[2], fs.units[4]
    assert sp.frame is not None and pump.frame is not None
    # Seven laterals overlap on the way up, needing eight pitches.
    assert pump.frame.x - (sp.frame.x + sp.frame.w) == 2 * MIN_ESCAPE + 8 * LANE_PITCH
    assert 2 * MIN_ESCAPE + 8 * LANE_PITCH > COL_GAP


def test_a_mixer_drawing_registered_again_is_drawn():
    from pandid.render.symbols import Symbol, default_registry

    stock = default_registry.get("mixer")
    mine = Symbol(
        svg='<g id="sym_mixer"><rect width="40" height="40"/></g>',
        width=40.0,
        height=40.0,
        ports={"outlet": (40.0, 20.0), "in_1": (0.0, 10.0), "in_2": (0.0, 30.0)},
    )
    default_registry.register("mixer", mine)
    try:
        assert default_registry.for_unit(U.Mixer("M-1")) is mine
    finally:
        default_registry.register("mixer", stock)
    assert default_registry.for_unit(U.Mixer("M-1", n_inlets=4)).height == 90


@pytest.mark.parametrize("at", [0.25, 0.5, 0.75])
def test_a_lateral_keeps_the_instrument_that_taps_it(at):
    fs = Flowsheet("Tapped bank")
    sp = fs.add(U.Splitter("SP", n_outlets=4))
    mx = fs.add(U.Mixer("MX", n_inlets=4))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    fs.connect(mx.outlet, fs.add(U.Product("P")).inlet)
    suctions = []
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        suctions.append(fs.connect(outlet, pump.suction))
        fs.connect(pump.discharge, inlet)
    fs.add_instrument("PI", 100, sensing=suctions[3], at=at)
    fs.to_svg(diagram="p&id")
    assert _taps_off(fs) == set()
    assert fs.route_converged
    assert measure_final(fs).crossings == 0
    assert _flaws(fs)["line-on-line"] == 0


def _coolers(n: int) -> tuple[Flowsheet, list[Stream], list[Stream]]:
    """Return n exchangers between headers, each with its own cooling water."""
    fs = Flowsheet("Cooler bank")
    sp = fs.add(U.Splitter("SP-101", n_outlets=n))
    mx = fs.add(U.Mixer("MX-101", n_inlets=n))
    fs.connect(fs.add(U.Feed("Feed")).outlet, sp.inlet)
    fs.connect(mx.outlet, fs.add(U.Product("Product")).inlet)
    outlets, returns = [], []
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        exchanger = fs.add(ShellAndTubeExchanger(f"E-{100 + i}"))
        fs.connect(outlet, exchanger.tube_in)
        outlets.append(fs.connect(exchanger.tube_out, inlet))
        fs.connect(fs.add(U.Feed(f"CWS-{i}")).outlet, exchanger.shell_in)
        returns.append(fs.connect(exchanger.shell_out, fs.add(U.Product(f"CWR-{i}")).inlet))
    return fs, outlets, returns


def _drawing(fs: Flowsheet) -> tuple[list, list]:
    """Return every unit's frame and every stream's waypoints."""
    frames = [(u.name, u.frame) for u in fs.units]
    routes = [s.route.waypoints if s.route is not None else None for s in fs.streams]
    return frames, routes


def test_a_three_way_header_keeps_its_stock_face():
    fs, outlets, returns = _coolers(3)
    fs.to_svg(diagram="p&id")
    assert [u.frame.h for u in fs.units[:2] if u.frame is not None] == [50, 50]
    # No exchanger's tube outlet runs along its own shell return.
    for tube, shell in zip(outlets, returns):
        a, b = stream_path(tube), stream_path(shell)
        assert not any(_shared(p, q, r, t) for p, q in zip(a, a[1:]) for r, t in zip(b, b[1:]))


def _as_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Draw from here on with stock headers, no lane gaps and no lanes."""
    monkeypatch.setattr(symbols, "header_grows", lambda unit: False)
    monkeypatch.setattr(layered, "_lanes", lambda segs: {})
    monkeypatch.setattr(lanes, "relane", lambda *args: False)


def _tapped_coolers(n: int, at: float) -> Flowsheet:
    """Return n coolers with a temperature balloon on each outlet at ``at``."""
    fs, outlets, _ = _coolers(n)
    for i, stream in enumerate(outlets):
        fs.add_instrument("TI", 201 + i, sensing=stream, at=at)
    return fs


def test_a_header_kept_stock_draws_as_the_stock_header_without_lanes(monkeypatch):
    fs = _coolers(9)[0]
    fs.to_svg(diagram="p&id")
    assert [u.frame.h for u in fs.units[:2] if u.frame is not None] == [50, 50]
    _as_main(monkeypatch)
    plain = _coolers(9)[0]
    plain.to_svg(diagram="p&id")
    assert _drawing(fs) == _drawing(plain)


def _retyped(fs: Flowsheet) -> None:
    """Type the feed line's drawn route back in with via()."""
    line = fs.streams[0]
    assert line.route is not None
    line.via(list(line.route.waypoints))


def test_a_sheet_routed_again_draws_as_it_would_without_lanes(monkeypatch):
    fs = _tapped_coolers(4, 0.5)
    fs.to_svg(diagram="p&id")
    _retyped(fs)
    fs.route()
    fs.to_svg(diagram="p&id")
    _as_main(monkeypatch)
    plain = _tapped_coolers(4, 0.5)
    plain.to_svg(diagram="p&id")
    _retyped(plain)
    plain.route()
    plain.to_svg(diagram="p&id")
    assert _drawing(fs) == _drawing(plain)


def _tapped_bank(n: int) -> Flowsheet:
    """Return n pumps with a temperature balloon halfway along each line off the splitter."""
    fs = _bank(n, exchangers=False)
    laterals = [s for s in fs.streams if s.source.owner.name == "SP"]
    for i, stream in enumerate(laterals):
        fs.add_instrument("TI", 301 + i, sensing=stream, at=0.5)
    return fs


def test_a_sheet_laid_out_again_draws_as_it_would_without_lanes(monkeypatch):
    fs = _tapped_bank(6)
    fs.route()
    fs.layout()
    fs.route()
    _as_main(monkeypatch)
    plain = _tapped_bank(6)
    plain.route()
    plain.layout()
    plain.route()
    assert _drawing(fs) == _drawing(plain)


def test_lanes_are_kept_only_where_they_draw_no_worse_than_without():
    fs = _tapped_coolers(3, 0.75)
    fs.to_svg(diagram="p&id")
    assert _flaws(fs)["line-on-line"] == 0
    assert measure_final(fs).bends == 20


def test_a_restored_drawing_shares_no_frame_with_the_one_it_was_saved_from():
    fs = _tapped_coolers(3, 0.75)
    fs.to_svg(diagram="p&id")
    state = fs._state()
    fs._put_state(state)
    fs._put_state(state)
    saved = {id(frame) for _, frame, _ in state[0][0]}
    assert not saved & {id(u.frame) for u in fs.units}


def test_a_restored_drawing_puts_back_whether_a_lateral_can_fan():
    fs = _valved(3)[0]
    fs.route()
    assert fs._fannable
    state = fs._state()
    # Stand in for the flag a refused layout trial leaves.
    fs._fannable = False
    fs._put_state(state)
    assert fs._fannable


def _valved(
    n: int, at: float | None = None, kind: type[U.Valve] = U.Valve, discharge: bool = False
) -> tuple[Flowsheet, list[U.Valve], list[U.Pump]]:
    """Return n pumps between SP and MX, each with a ``kind`` valve on its suction.

    With ``at`` given, put each valve on its pump's discharge instead if ``discharge``.
    """
    fs = Flowsheet(f"Valved bank of {n}")
    sp = fs.add(U.Splitter("SP", n_outlets=n))
    mx = fs.add(U.Mixer("MX", n_inlets=n))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    fs.connect(mx.outlet, fs.add(U.Product("P")).inlet)
    valves, pumps = [], []
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        if at is None:
            valve = fs.add(kind(f"HV-{i}"))
            fs.connect(outlet, valve.inlet)
            fs.connect(valve.outlet, pump.suction)
            fs.connect(pump.discharge, inlet)
        else:
            lines = [fs.connect(outlet, pump.suction), fs.connect(pump.discharge, inlet)]
            valve = fs.add(kind(f"HV-{i}"), on=lines[discharge], at=at)
        valves.append(valve)
        pumps.append(pump)
    return fs, valves, pumps


@pytest.mark.parametrize("n", [3, 6])
def test_each_suction_valve_sits_on_the_level_run_into_its_pump(n):
    fs, valves, _ = _valved(n)
    fs.route()
    for valve in valves:
        line = valve.outlet.stream
        assert line is not None
        points = stream_polyline(line)
        assert len(points) == 2, valve.name
        (x0, y0), (x1, y1) = points
        assert y0 == y1 and x1 - x0 == pytest.approx(ALONG), valve.name
    assert measure_final(fs).crossings == 0
    flaws = _flaws(fs)
    assert flaws["unit-on-tag"] == flaws["line-through-tag"] == 0


def _makeup() -> Flowsheet:
    """Return a makeup line through a valve into a mixer."""
    fs = Flowsheet("Makeup")
    mx = fs.add(U.Mixer("MX"))
    valve = fs.add(U.Valve("HV-1"))
    fs.connect(fs.add(U.Feed("Makeup")).outlet, valve.inlet)
    fs.connect(valve.outlet, mx.inlets[0])
    fs.connect(fs.add(U.Feed("Return")).outlet, mx.inlets[1])
    fs.connect(mx.outlet, fs.add(U.Pump("P-1")).suction)
    return fs


def test_control_valves_set_on_a_banks_laterals_keep_clear_of_each_other():
    fs, valves, _ = _valved(3, at=0.5, kind=ControlValve)
    fs.route()
    assert not [i for i in fs.validate() if i.code == "unit-overlap"]
    boxes = [unit_box(valve, valve.frame) for valve in valves]
    for k, box in enumerate(boxes):
        for other in boxes[k + 1 :]:
            assert not boxes_overlap(box, other, GAP)


def test_valves_moved_apart_on_a_banks_discharge_cross_no_line_at_a_nozzle():
    fs = _valved(5, at=0.5, kind=ControlValve, discharge=True)[0]
    fs.route()
    assert not [i for i in fs.validate() if i.code == "route-crosses-near-nozzle"]


def test_a_valve_moved_off_its_neighbour_keeps_other_lines_out_of_it():
    fs, valves, _ = _valved(4, at=0.5, kind=ControlValve, discharge=True)
    fs.route()
    boxes = [unit_box(valve, valve.frame) for valve in valves]
    for valve, box in zip(valves, boxes):
        if any(other is not box and boxes_overlap(box, other, -1.0) for other in boxes):
            continue
        for stream in fs.streams:
            if valve in (stream.source.owner, stream.dest.owner):
                continue
            points = stream_polyline(stream)
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                segment = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
                assert not boxes_overlap(box, segment), (valve.name, stream.name)


def test_a_header_spaces_its_lines_to_fit_their_control_valves():
    fs, valves, _ = _valved(4, at=0.5, kind=ControlValve, discharge=True)
    fs.route()
    assert not [i for i in fs.validate() if i.code == "unit-overlap"]
    mixer = next(u for u in fs.units if u.kind == "mixer")
    across = resolve_size(valves[0])[1] + GAP
    assert resolve_size(mixer)[1] == pytest.approx(3 * across + 2 * symbols.JUNCTION_END)


@pytest.mark.parametrize("build", [lambda: _valved(4, at=0.3)[0], _makeup])
def test_a_valve_placed_or_off_a_flag_keeps_its_place(monkeypatch, build):
    fs = build()
    fs.route()
    monkeypatch.setattr(mounted, "_fanned", lambda run, legs: None)
    plain = build()
    plain.route()
    assert _drawing(fs) == _drawing(plain)


def test_routing_a_valved_bank_again_draws_the_same_sheet():
    fs = _valved(6)[0]
    fs.route()
    first = _drawing(fs)
    fs.route()
    assert _drawing(fs) == first
    fs.layout()
    fs.route()
    assert _drawing(fs) == first
