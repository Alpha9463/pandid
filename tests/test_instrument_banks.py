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
from _quality import measure_final


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


def test_a_controller_a_turn_clears_stays_by_its_transmitter():
    """Route a bank at k = 10: FIC-200's nozzle is turned clear, so only FIC-201 hangs beside its valve."""
    fs, loops = _routed_bank(10)

    assert id(loops[0].controller) not in fs._beside
    assert id(loops[1].controller) in fs._beside


def test_a_controller_with_no_clear_side_hangs_beside_its_valve():
    """Draw FT-201's line to FIC-201 clear of units where no side of FIC-201 is clear by FT-201.

    The line takes no fallback path and crosses no unit.
    """
    fs, loops = _routed_bank(10)
    line = loops[1].measurement

    assert line.route is not None and not line.route.used_fallback
    assert _drawn_wrong(fs, line) == []


def test_a_bank_laid_out_again_keeps_its_drawn_layout_where_a_fresh_one_crosses_more():
    """Keep the layout from the drawn routes where a fresh one draws more crossings."""
    fs, _ = _valved_bank(10, pumps=2)
    first = measure_final(fs).crossings
    fs.layout()
    fs.route()
    assert measure_final(fs).crossings < first


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
    """Let go of FT-201, held where S11 was frozen, once a fresh layout lays SP over it."""
    fs, loops = copy.deepcopy(_routed_bank(999))
    line = loops[1].measurement
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs._lay_out(None, afresh=True)
    boxes = [(u.name, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    assert [
        (a, b)
        for i, (a, p) in enumerate(boxes)
        for b, q in boxes[i + 1 :]
        if boxes_overlap(p, q, -1.0)
    ] == []


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


@pytest.mark.parametrize(
    ("after", "taps_off", "trade", "kept"),
    [
        ({"route-crosses-unit": 1, "crossing": 4}, set(), True, True),
        ({"route-crosses-unit": 1, "crossing": 5}, set(), True, False),
        ({"route-crosses-unit": 1, "crossing": 4}, {7}, True, False),
        ({"crossing": 6}, set(), True, True),
        ({"crossing": 6}, set(), False, False),
    ],
)
def test_a_redraw_is_kept_where_no_tap_leaves_its_line_and_nothing_grows_untraded(
    after: dict[str, int], taps_off: set[int], trade: bool, kept: bool
):
    """Keep a redraw only where no tap leaves its line and no count grows.

    With the trade allowed, a redraw that takes a line out of a unit at the
    price allowed is kept too.
    """
    from collections import Counter

    from pandid.layout.control import _kept

    before = Counter({"route-crosses-unit": 1, "crossing": 4})

    assert _kept(before, set(), Counter(after), taps_off, trade) is kept


def test_lines_frozen_on_a_bank_keep_their_points_and_balloons():
    """Freeze FIC-201's output and route a bank; then FT-201's line and P-1's outlet, and route.

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
        ([loops[1].output], [loops[1].controller], 1),
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


def _pinned_off(fs: Flowsheet, name: str, dx: float) -> None:
    """Pin a valve ``dx`` to the right of where the sheet draws it."""
    valve = next(u for u in fs.units if u.name == name)
    valve.pin(x=frame_of(valve).x + dx, y=frame_of(valve).y)


def test_a_pin_after_a_controller_hangs_beside_its_valve_draws_no_line_through_a_unit():
    """Pin FV-10 40 px left of where a two-pump bank with a hung controller draws it.

    The hang no longer passes its terms, so route() draws without it: the P&ID
    exports to SVG and draw.io, nothing overlaps, no line is drawn through a
    unit, and no lines crowd or cross by a nozzle.
    """
    fs, _ = _valved_bank(10, pumps=2)
    assert fs._beside
    _pinned_off(fs, "FV-10", -40)
    fs.route()
    fs.to_svg(diagram="p&id")
    fs.to_drawio(diagram="p&id")
    codes = ("route-crosses-unit", "unit-overlap", "lines-crowded", "route-crosses-near-nozzle")

    assert [i.message for i in fs.validate() if i.code in codes] == []


def test_a_hang_that_still_passes_its_terms_after_an_edit_is_kept():
    """Pin FV-10 1 px left of where a two-pump bank draws it; FIC-200 stays hung beside it."""
    fs, loops = _valved_bank(10, pumps=2)
    assert id(loops[0].controller) in fs._beside
    _pinned_off(fs, "FV-10", -1)
    fs.route()

    assert id(loops[0].controller) in fs._beside


def test_a_hang_whose_redraw_fails_is_drawn_afresh(monkeypatch: pytest.MonkeyPatch):
    """Route a two-pump bank again after an edit where redrawing its hang raises.

    route() draws the sheet without the hang instead, and the P&ID exports.
    """
    fs, _ = _valved_bank(10, pumps=2)
    assert fs._beside
    _pinned_off(fs, "FV-10", -1)
    stepped = Flowsheet._route_stepped
    calls: list[int] = []

    def fails_first(self: Flowsheet, router: object = None) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("the hung redraw fails")
        stepped(self, router)

    monkeypatch.setattr(Flowsheet, "_route_stepped", fails_first)
    fs.route()
    fs.to_svg(diagram="p&id")

    assert len(calls) > 1


def _steps_per_drawing(fs: Flowsheet, monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """Route a sheet; return how often it ran the hang steps and drew the sheet."""
    counts = {"steps": 0, "drawings": 0}
    stepped, drawing = Flowsheet._route_stepped, Flowsheet._route_drawing

    def counted_steps(self: Flowsheet, router: object = None) -> None:
        counts["steps"] += 1
        stepped(self, router)

    def counted_drawing(self: Flowsheet, router: object = None) -> None:
        counts["drawings"] += 1
        drawing(self, router)

    monkeypatch.setattr(Flowsheet, "_route_stepped", counted_steps)
    monkeypatch.setattr(Flowsheet, "_route_drawing", counted_drawing)
    fs.route()
    return counts["steps"], counts["drawings"]


def test_a_sheet_with_no_hung_controller_runs_the_hang_steps_once(monkeypatch):
    """Route a single loop whose controller hangs nowhere: no hang is judged again."""
    from pandid.devices import ControlValve

    fs = Flowsheet("one loop")
    pump = fs.add(U.Pump("P-1"))
    line = fs.connect(fs.add(U.Feed("F")).outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(U.Product("P")).inlet)
    valve = fs.add(ControlValve("FV-1"), on=line, at=0.5)
    fs.add_control_loop("F", 1, measuring=line, acting_on=valve)
    steps, drawings = _steps_per_drawing(fs, monkeypatch)

    assert steps == drawings


def test_a_hung_controller_its_frozen_lines_meet_is_not_judged_again(monkeypatch):
    """Freeze FIC-200's lines on a two-pump bank and route again: the hang is not re-judged."""
    fs, loops = _valved_bank(10, pumps=2)
    assert id(loops[0].controller) in fs._beside
    for line in (loops[0].output, loops[0].measurement):
        assert line.route is not None
        line.via(list(line.route.waypoints))
    steps, drawings = _steps_per_drawing(fs, monkeypatch)

    assert steps == drawings


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


def test_a_bank_at_k99_hangs_a_controller_where_its_lines_draw_clear():
    """Route a bank at k = 99; route() hangs a controller beside its valve.

    FT-201's line to FIC-201 and FIC-202's output take no fallback path and
    cross no unit.
    """
    fs, loops = _routed_bank(99)
    assert fs._beside
    for line in (loops[1].measurement, loops[2].output):
        assert line.route is not None and not line.route.used_fallback
        assert _drawn_wrong(fs, line) == []
