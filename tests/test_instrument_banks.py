"""Check controllers hung on a bank of pumps and balloons turned off blocked nozzles."""

import copy
import functools

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.conflicts import boxes_overlap
from pandid.loops import ControlLoop
from pandid.portgeom import unit_box
from pandid.streams import Stream

from _layout_cases import frame_of


def _valved_bank(
    first_tag: int,
    controller_face: str | None = None,
    controller_on_line: bool = False,
    route: bool = True,
    pumps: int = 3,
) -> tuple[Flowsheet, list[ControlLoop]]:
    """Build pumps in parallel, each with a flow loop on its valved suction line.

    Route the bank unless ``route`` is False.
    """
    from pandid.devices import ControlValve

    fs = Flowsheet("valved loops")
    sp = fs.add(U.Splitter("SP", n_outlets=pumps))
    mx = fs.add(U.Mixer("MX", n_inlets=pumps))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    fs.connect(mx.outlet, fs.add(U.Product("P")).inlet)
    pairs = []
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        line = fs.connect(outlet, pump.suction)
        fs.connect(pump.discharge, inlet)
        pairs.append((line, fs.add(ControlValve(f"FV-{first_tag + i}"), on=line, at=0.5)))
    loops = [
        fs.add_control_loop(
            "F", 200 + i, measuring=line, acting_on=valve, controller_face=controller_face
        )
        for i, (line, valve) in enumerate(pairs)
    ]
    for loop in loops if controller_on_line else ():
        host = loop.transmitter.host
        assert host is not None
        loop.controller.attach(host, at=0.5, offset=45, relation="near")
    if route:
        fs.route()
    return fs, loops


@functools.cache
def _routed_bank(first_tag: int) -> tuple[Flowsheet, list[ControlLoop]]:
    """Return a routed bank shared by the tests that only read it."""
    return _valved_bank(first_tag)


def _drawn_wrong(fs: Flowsheet, line: Stream) -> list[str]:
    """Return the findings that draw a line through a unit or on the slant."""
    codes = ("route-crosses-unit", "route-diagonal")
    return [
        i.message
        for i in fs.validate()
        if i.code in codes and i.message.startswith(f"stream {line.name} ")
    ]


@pytest.mark.parametrize(
    ("first_tag", "loop", "signal"),
    [
        (10, 2, "output"),
        (999, 0, "measurement"),
    ],
)
def test_a_balloon_nozzle_facing_a_unit_turns_clear(first_tag: int, loop: int, signal: str):
    """Draw a bank's signal line clear of units where its balloon's nozzle faced one.

    The line takes no fallback path and crosses no unit.
    """
    fs, loops = _routed_bank(first_tag)
    line = getattr(loops[loop], signal)

    assert line.route is not None and not line.route.used_fallback
    assert _drawn_wrong(fs, line) == []


def _blocked_controller(
    via: list[tuple[float, float]] | None = None,
) -> tuple[Flowsheet, Stream]:
    """Route FT-101 below V-101 to FIC-101, pinned just above it, through ``via`` if given."""
    fs = Flowsheet("blocked controller")
    fs.add(U.Vessel("V-101", width=80, height=60)).pin(x=145, y=155)
    ft = fs.add(U.Instrument("FT-101")).pin(x=163, y=320)
    fic = fs.add(U.Instrument("FIC-101")).pin(x=163, y=100)
    line = fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    if via is not None:
        line.via(via)
    fs.route()
    return fs, line


def test_a_signal_line_frozen_on_a_turned_nozzle_keeps_its_points():
    """Route again after freezing the line into a nozzle turned off V-101.

    The frozen line keeps its points, is square and crosses no unit.
    """
    fs, line = _blocked_controller()
    assert line.route is not None
    points = list(line.route.waypoints)
    line.via(points)
    fs.route()

    assert line.route.waypoints == points
    assert _drawn_wrong(fs, line) == []


def test_a_hand_drawn_line_into_a_blocked_nozzle_keeps_its_face():
    """Route a line drawn by hand into FIC-101's S face, which V-101 blocks.

    The line keeps its points and is square after each of two route() calls.
    """
    points = [(185.0, 295.0), (185.0, 169.0)]
    fs, line = _blocked_controller(points)
    for again in (False, True):
        if again:
            fs.route()

        assert line.route is not None
        assert line.route.waypoints == points
        assert [m for m in _drawn_wrong(fs, line) if "slant" in m] == []


def test_a_controller_with_no_clear_side_hangs_beside_its_valve():
    """Draw FT-201's line to FIC-201 clear of units where no side of FIC-201 is clear by FT-201.

    The line takes no fallback path and crosses no unit.
    """
    fs, loops = _routed_bank(10)
    line = loops[1].measurement

    assert line.route is not None and not line.route.used_fallback
    assert _drawn_wrong(fs, line) == []


def test_a_bank_with_a_controller_hung_beside_its_valve_laid_out_again_draws_as_a_fresh_build():
    """Draw a routed bank laid out again as one route() of a fresh build."""
    fresh, _ = _valved_bank(10, pumps=2)
    fs, _ = _valved_bank(10, pumps=2)
    assert fs._beside
    fs.layout()
    fs.route()
    assert [(u.name, u.frame) for u in fs.units] == [(u.name, u.frame) for u in fresh.units]
    assert [s.route for s in fs.streams] == [s.route for s in fresh.streams]


def test_a_line_frozen_on_a_bank_then_laid_out_again_still_meets_its_controller():
    """Draw FIC-201's frozen output square and clear of units after layout()."""
    fs, loops = _valved_bank(10, pumps=2)
    line = loops[1].output
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.layout()
    fs.route()
    assert _drawn_wrong(fs, line) == []


def test_layout_after_a_line_is_frozen_draws_no_unit_over_a_balloon_it_held():
    """Let go of FT-201, held where S11 was frozen, once layout() lays SP over it."""
    fs, loops = copy.deepcopy(_routed_bank(999))
    line = loops[1].measurement
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.layout()
    boxes = [(u.name, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    assert [(a, b) for i, (a, p) in enumerate(boxes) for b, q in boxes[i + 1:]
            if boxes_overlap(p, q, -1.0)] == []


@pytest.mark.parametrize("face", [None, "E"])
def test_a_controller_on_a_stated_face_is_not_hung_beside_its_valve(face: str | None):
    """Offer spots beside its valve to a loop's controller only where no face is stated."""
    from pandid.devices import ControlValve
    from pandid.layout.control import _beside_valve

    fs = Flowsheet("one loop")
    pump = fs.add(U.Pump("P-1"))
    line = fs.connect(fs.add(U.Feed("F")).outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(U.Product("P")).inlet)
    valve = fs.add(ControlValve("FV-1"), on=line, at=0.5)
    loop = fs.add_control_loop("F", 1, measuring=line, acting_on=valve, controller_face=face)
    fs.route()

    assert bool(list(_beside_valve(fs, loop.controller))) is (face is None)


def test_a_bank_with_controllers_near_the_measured_line_routes():
    """Route a bank whose controllers hang near the line their transmitters measure.

    route() completes and leaves each controller on its line.
    """
    fs, loops = _valved_bank(10, controller_on_line=True)

    assert [loop.controller.host for loop in loops] == [loop.transmitter.host for loop in loops]
    assert all(loop.controller.frame is not None for loop in loops)


def test_a_controller_above_a_pump_draws_its_output_clear():
    """Draw FIC-202's output to FV-1001, past P-1, clear of every unit.

    The line takes no fallback path and crosses no unit.
    """
    fs, loops = _routed_bank(999)
    line = loops[2].output

    assert line.route is not None and not line.route.used_fallback
    assert _drawn_wrong(fs, line) == []


@pytest.mark.parametrize(
    ("after", "kept"),
    [
        ({"route-crosses-unit": 1, "crossing": 6}, True),
        ({"route-crosses-unit": 1, "crossing": 5, "route-along-unit": 2}, True),
        ({"route-crosses-unit": 1, "crossing": 6, "route-along-unit": 2}, False),
        ({"route-crosses-unit": 1, "crossing": 4, "route-crosses-near-nozzle": 1}, False),
        ({"route-crosses-unit": 3, "crossing": 4}, False),
    ],
)
def test_a_line_leaves_a_unit_for_at_most_two_crossings_or_runs_along_units(
    after: dict[str, int], kept: bool
):
    """Keep a redraw that takes a line out of a unit only at the price allowed.

    Two more crossings or runs along units in all are allowed; any other growth is not.
    """
    from collections import Counter

    from pandid.layout.control import _out_of_unit

    before = Counter({"route-crosses-unit": 3, "crossing": 4, "route-along-unit": 1})

    assert _out_of_unit(before, Counter(after)) is kept


def test_lines_frozen_on_a_bank_keep_their_points_and_balloons():
    """Freeze FIC-201's output and route a bank twice; then FT-201's line and P-1's outlet, once.

    The first route() both hangs FIC-201 beside FV-11 and closes the bank's empty
    bands. After each later route() the frozen lines keep their points, the
    balloons at their ends stay where the lines were drawn to them, the P&ID
    exports to SVG and draw.io, nothing overlaps, no line crosses a unit and no
    frozen line is drawn on the slant.
    """
    fs, loops = _valved_bank(10)
    assert fs._beside and fs._main is not None and not fs._offers_family_faces()
    pump = next(u for u in fs.units if u.name == "P-1")
    process = next(s for s in fs.streams if s.source.owner is pump)
    codes = ("route-crosses-unit", "unit-overlap")
    frozen: list[tuple[Stream, list[tuple[float, float]]]] = []
    held: list[tuple[U.Instrument, float, float]] = []
    steps = [
        ([loops[1].output], [loops[1].controller], 2),
        ([loops[1].measurement, process], [loops[1].transmitter], 1),
    ]
    for lines, balloons, routes in steps:
        for line in lines:
            assert line.route is not None
            frozen.append((line, list(line.route.waypoints)))
            line.via(list(frozen[-1][1]))
        held += [(b, frame_of(b).x, frame_of(b).y) for b in balloons]
        for _ in range(routes):
            fs.route()
            fs.to_svg(diagram="p&id")
            fs.to_drawio(diagram="p&id")

            assert [s.route.waypoints if s.route is not None else [] for s, _ in frozen] == [
                points for _, points in frozen
            ]
            assert [v for b, _, _ in held for v in (frame_of(b).x, frame_of(b).y)] == (
                pytest.approx([v for _, x, y in held for v in (x, y)])
            )
            assert [i.message for i in fs.validate() if i.code in codes] == []
            assert [m for s, _ in frozen for m in _drawn_wrong(fs, s)] == []


def test_a_pin_after_a_controller_hangs_beside_its_valve_draws_no_line_through_a_unit():
    """Pin FV-11 off where a bank with a hung controller draws it, and route again.

    The P&ID exports to SVG and draw.io, nothing overlaps, and no line is drawn
    through a unit.
    """
    fs, _ = _valved_bank(10)
    assert fs._beside
    next(u for u in fs.units if u.name == "FV-11").pin(x=430, y=230)
    fs.route()
    fs.to_svg(diagram="p&id")
    fs.to_drawio(diagram="p&id")
    codes = ("route-crosses-unit", "unit-overlap")

    assert [i.message for i in fs.validate() if i.code in codes] == []


def test_a_nozzle_face_or_attachment_is_not_read_against_the_drawing():
    """State a nozzle face and an attachment on a bank.

    Neither changes what route() reads as coordinates typed against the drawing.
    """
    fs, loops = _valved_bank(10, route=False)
    stated = fs._stated()
    next(u for u in fs.units if u.name == "FV-11").nozzle("actuator", "N")
    transmitter = loops[1].transmitter
    assert transmitter.host is not None
    transmitter.attach(transmitter.host, at=0.3)

    assert fs._stated() == stated


def test_a_valve_pinned_by_where_drawn_after_a_hang_routes():
    """Route a bank at k = 99, then pin FV-100 1 px left of where it is drawn and route again.

    The first route() hangs a controller and draws FT-201's line to FIC-201 and
    FIC-202's output with no fallback path and through no unit. The second
    completes and the P&ID exports.
    """
    fs, loops = _valved_bank(99)
    assert fs._beside
    for line in (loops[1].measurement, loops[2].output):
        assert line.route is not None and not line.route.used_fallback
        assert _drawn_wrong(fs, line) == []
    valve = next(u for u in fs.units if u.name == "FV-100")
    valve.pin(x=frame_of(valve).x - 1, y=frame_of(valve).y)
    fs.route()
    fs.to_svg(diagram="p&id")
    fs.to_drawio(diagram="p&id")
