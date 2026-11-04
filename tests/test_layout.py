"""Check the layered layout engine through the public API."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

import pytest

from pandid import Flowsheet, devices as D, units as U
from pandid.layout.attach import place_attached, stream_path
from pandid.layout.control import _grid as control_grid
from pandid.layout.halo import balloon_pads
from pandid.layout.layered import BAND_WIDTH, COL_GAP, MARGIN
from pandid.portgeom import pin_intent, port_faces, port_point, unit_box
from pandid.routing.metrics import real_bends

from _layout_cases import build, overlaps

Box = tuple[float, float, float, float]


def _drawn_boxes(fs: Flowsheet) -> dict[str, Box]:
    """Return every unit's drawn box, by name.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    dict[str, tuple[float, float, float, float]]
        Each unit's drawn box; a feed flag's is left of its frame.
    """
    boxes = {}
    for unit in fs.units:
        assert unit.frame is not None, unit.name
        boxes[unit.name] = unit_box(unit, unit.frame)
    return boxes


def _overlapping(fs: Flowsheet) -> list[tuple[str, str]]:
    """Return the pairs of units whose drawn boxes overlap.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[tuple[str, str]]
        Names of each overlapping pair.
    """
    boxes = _drawn_boxes(fs)
    return [(a, b) for a, b in combinations(boxes, 2) if overlaps(boxes[a], boxes[b])]


def _unit_overlaps(fs: Flowsheet) -> list[str]:
    """Return the messages of the sheet's unit-overlap findings.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[str]
        One message per overlap ``validate()`` reports.
    """
    return [issue.message for issue in fs.validate() if issue.code == "unit-overlap"]


def _long_train(n: int) -> Flowsheet:
    """Return *n* blocks in one straight line, each feeding the next.

    Parameters
    ----------
    n : int
        Number of blocks.

    Returns
    -------
    Flowsheet
        Unlaid sheet.
    """
    fs = Flowsheet("train")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W"], outputs=["E"]))
        fs.connect(port, block.in_1)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def _width_and_rows(fs: Flowsheet) -> tuple[float, int]:
    """Return a laid-out sheet's drawn width and how many unit heights it has.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    tuple[float, int]
        Drawn width, and the count of distinct unit centre heights.
    """
    boxes = _drawn_boxes(fs).values()
    width = max(box[2] for box in boxes) - min(box[0] for box in boxes)
    return width, len({round((box[1] + box[3]) / 2) for box in boxes})


# --- layers: flow runs west to east -------------------------------------------


def test_flow_runs_west_to_east() -> None:
    """Check that each step along the flow is the next column east."""
    fs = Flowsheet("Train")
    reactor = fs.add(U.Reactor("R1"))
    separator = fs.add(U.Separator("S1"))
    mixer = fs.add(U.Mixer("M1"))
    fs.connect(reactor.outlet, separator.feed)
    fs.connect(separator.vapor, mixer.in_1)
    fs.layout()

    frames = [unit.frame for unit in (reactor, separator, mixer)]
    assert all(frame is not None for frame in frames)
    assert [frame.col for frame in frames if frame is not None] == [0, 1, 2]
    xs = [frame.x for frame in frames if frame is not None]
    assert xs == sorted(xs) and len(set(xs)) == 3


def test_a_cycle_is_broken_at_its_return_line() -> None:
    """Check that a cycle is laid out with its closing pipe drawn as a return line."""
    fs = Flowsheet("Cycle")
    reactor = fs.add(U.Reactor("R1"))
    separator = fs.add(U.Separator("S1"))
    forward = fs.connect(reactor.outlet, separator.feed)
    back = fs.connect(separator.liquid, reactor.feed)
    fs.layout()
    fs.route()

    assert not forward.is_recycle
    assert back.is_recycle
    assert reactor.frame is not None and separator.frame is not None
    assert reactor.frame.x_max < separator.frame.x


def test_a_pipe_from_a_north_nozzle_to_a_south_nozzle_stacks_its_units() -> None:
    """Check that a top-to-bottom pipe puts both ends in one column, nozzles lined up."""
    fs = Flowsheet("Stack")
    lower = fs.add(U.Block("A", inputs=["W"], outputs=["E", "N"]))
    upper = fs.add(U.Block("B", inputs=["S"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, lower.in_1)
    fs.connect(lower.out_1, fs.add(U.Product("P1")).inlet)
    fs.connect(lower.out_2, upper.in_1)
    fs.connect(upper.out_1, fs.add(U.Product("P2")).inlet)
    fs.layout()

    assert lower.frame is not None and upper.frame is not None
    assert upper.frame.col == lower.frame.col
    assert upper.frame.y_max < lower.frame.y
    assert port_point(upper, upper.frame, "in_1")[0] == pytest.approx(
        port_point(lower, lower.frame, "out_2")[0]
    )


# --- north and south faces ---------------------------------------------------


def _syngas_block() -> tuple[Flowsheet, U.Feed, U.Feed, U.Feed, U.Block]:
    """Return a sheet with two north inlets on one block.

    Returns
    -------
    tuple
        The unlaid sheet, its natural gas, air and steam feeds, and the block.
    """
    fs = Flowsheet("north face")
    ng = fs.add(U.Feed("Natural Gas"))
    air = fs.add(U.Feed("Air"))
    steam = fs.add(U.Feed("Steam"))
    sec = fs.add(U.Block("Sec", inputs=["W", "N", "N"], outputs=["E"]))
    prod = fs.add(U.Product("Syngas"))
    fs.connect(ng.outlet, sec.in_1)
    fs.connect(air.outlet, sec.in_2)
    fs.connect(steam.outlet, sec.in_3)
    fs.connect(sec.out_1, prod.inlet)
    return fs, ng, air, steam, sec


def test_a_feed_on_a_north_nozzle_is_drawn_above_it() -> None:
    """Check that feeds onto a block's roof sit above it, one each, and a side feed stays level."""
    fs, ng, air, steam, sec = _syngas_block()
    fs.layout()

    assert sec.frame is not None and ng.frame is not None
    for feed in (air, steam):
        assert feed.frame is not None
        assert port_point(feed, feed.frame, "outlet")[1] < sec.frame.y
    # The two of them stack rather than fight over the one place.
    assert air.frame is not None and steam.frame is not None
    assert air.frame.row != steam.frame.row
    # The west inlet is unaffected: a column to the left, level with its nozzle.
    assert sec.frame.col is not None
    assert ng.frame.col == sec.frame.col - 1
    assert port_point(ng, ng.frame, "outlet")[1] == pytest.approx(
        port_point(sec, sec.frame, "in_1")[1]
    )


def _legs(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return the straight runs of a routed path, in order, as unit steps.

    Parameters
    ----------
    path : list[tuple[float, float]]
        Routed waypoints.

    Returns
    -------
    list[tuple[float, float]]
        One direction per leg; zero-length repeats and a stand-off waypoint
        that continues a leg are folded in, so this counts turns.
    """
    out: list[tuple[float, float]] = []
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if (dx, dy) == (0.0, 0.0):
            continue
        step = (0 if dx == 0 else dx / abs(dx), 0 if dy == 0 else dy / abs(dy))
        if not out or out[-1] != step:
            out.append(step)
    return out


def test_a_north_face_peer_reaches_its_nozzle_in_one_turn() -> None:
    """Check that a feed onto a roof nozzle leaves east and drops onto it."""
    fs, _, air, steam, _ = _syngas_block()
    fs.layout()
    fs.route()

    for feed in (air, steam):
        stream = feed.outlet.stream
        assert stream is not None
        legs = _legs(stream_path(stream))
        assert len(legs) <= 2, f"{feed.name} turns {len(legs) - 1} times: {legs}"


def test_a_south_nozzles_peer_is_drawn_below_it() -> None:
    """Check that a product off a bottom nozzle sits below it, and the east one stays level."""
    fs = Flowsheet("south face")
    feed = fs.add(U.Feed("Feed"))
    sec = fs.add(U.Block("Sec", inputs=["W"], outputs=["E", "S"]))
    prod = fs.add(U.Product("Product"))
    waste = fs.add(U.Product("Waste"))
    fs.connect(feed.outlet, sec.in_1)
    fs.connect(sec.out_1, prod.inlet)
    fs.connect(sec.out_2, waste.inlet)
    fs.layout()

    assert sec.frame is not None and prod.frame is not None and waste.frame is not None
    assert port_point(waste, waste.frame, "inlet")[1] > port_point(sec, sec.frame, "out_2")[1]
    assert sec.frame.col is not None
    assert prod.frame.col == sec.frame.col + 1
    assert port_point(prod, prod.frame, "inlet")[1] == pytest.approx(
        port_point(sec, sec.frame, "out_1")[1]
    )


def test_an_equipment_nozzle_on_the_north_is_not_a_stacking_constraint() -> None:
    """Check that a compressor fed off a drum's top nozzle is still the next unit along."""
    fs = Flowsheet("equipment")
    feed = fs.add(U.Feed("Feed"))
    sep = fs.add(U.Separator("V-1"))
    comp = fs.add(U.Compressor("K-1"))
    fs.connect(feed.outlet, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.layout()

    assert sep.frame is not None and comp.frame is not None
    assert sep.frame.col is not None
    assert comp.frame.col == sep.frame.col + 1
    assert comp.frame.row == sep.frame.row


def test_a_named_north_nozzle_is_not_a_stacking_constraint_either() -> None:
    """Check that moving a drum's inlet to its top leaves the pump beside it."""
    fs = Flowsheet("named")
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    drum.nozzle("inlet", "N")
    fs.connect(pump.discharge, drum.inlet)
    fs.layout()

    assert pump.frame is not None and drum.frame is not None
    assert pump.frame.col is not None
    assert drum.frame.col == pump.frame.col + 1


def test_a_top_nozzle_piped_to_a_side_nozzle_does_not_stack() -> None:
    """Check that two blocks joined by a roof pipe and a side pipe sit side by side."""
    fs = Flowsheet("vertical cycle")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["E", "N"]))
    b = fs.add(U.Block("B", inputs=["N", "W"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(a.out_2, b.in_2)
    fs.connect(b.out_1, fs.add(U.Product("P")).inlet)
    fs.layout()

    assert a.frame is not None and b.frame is not None
    assert a.frame.col is not None
    assert b.frame.col == a.frame.col + 1
    assert a.frame.row == b.frame.row


def test_a_recycle_into_a_south_face_does_not_drag_its_source_back() -> None:
    """Check that a return line into a bottom nozzle keeps its source downstream."""
    fs = Flowsheet("recycle")
    feed = fs.add(U.Feed("Feed"))
    a = fs.add(U.Block("A", inputs=["W", "S"], outputs=["E"]))
    b = fs.add(U.Block("B", inputs=["W"], outputs=["E", "E"]))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(b.out_1, prod.inlet)
    fs.connect(b.out_2, a.in_2, draw_as_recycle=True)
    fs.layout()

    assert a.frame is not None and b.frame is not None
    assert a.frame.col is not None
    assert b.frame.col == a.frame.col + 1


def test_a_branch_ranks_beside_the_spine_it_joins() -> None:
    """Check that a blower feeding a tower far along the train sits one column from it."""
    fs = Flowsheet("slack")
    water = fs.add(U.Feed("Water"))
    a = fs.add(U.Filter("F-1"))
    b = fs.add(U.Filter("F-2"))
    tower = fs.add(U.Stripper("D-1"))
    air = fs.add(U.Feed("Air"))
    blower = fs.add(U.Blower("B-1"))
    fs.connect(water.outlet, a.inlet)
    fs.connect(a.outlet, b.inlet)
    fs.connect(b.outlet, tower.feed)
    fs.connect(air.outlet, blower.suction)
    fs.connect(blower.discharge, tower.boilup_in)
    fs.layout()

    assert air.frame is not None and blower.frame is not None
    assert tower.frame is not None and b.frame is not None
    assert air.frame.col is not None and blower.frame.col is not None
    assert tower.frame.col is not None and b.frame.col is not None
    assert abs(blower.frame.col - tower.frame.col) == 1
    assert abs(air.frame.col - blower.frame.col) == 1
    assert blower.frame.col > b.frame.col


def test_a_relief_valve_is_drawn_over_the_vessel_it_protects() -> None:
    """Check that a relief valve on a vessel's top nozzle sits up at that vessel."""
    fs = Flowsheet("relief")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-101"))
    prod = fs.add(U.Product("Product"))
    psv = fs.add(D.ReliefValve("PSV-101"))
    flare = fs.add(U.Product("To Flare"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)
    fs.layout()

    assert psv.frame is not None and drum.frame is not None
    # On the relief line's first level leg, beside the vessel's top.
    assert drum.frame.x <= psv.frame.cx <= drum.frame.x_max + COL_GAP
    assert psv.frame.y_max <= drum.frame.y


def test_one_fixed_nozzle_places_an_edge_whose_far_end_can_move() -> None:
    """Check that a pump's one-face discharge puts the drum it feeds east of it."""
    fs = Flowsheet("one fixed end")
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    fs.connect(pump.discharge, drum.in_1)
    fs.layout()

    assert drum.frame is not None and pump.frame is not None
    assert len(port_faces(drum, "in_1", drum.frame)) > 1, "in_1 is not movable"
    assert pump.frame.col is not None
    assert drum.frame.col == pump.frame.col + 1


def test_a_signal_run_states_no_order_along_the_sheet() -> None:
    """Check that a control loop neither tears the process nor puts balloons on the grid."""
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    ft = fs.add(U.Instrument("FT-101"))
    fic = fs.add(U.Instrument("FIC-101"))
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    signal = fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()

    assert [s.name for s in fs.streams if s.is_recycle] == []
    assert not signal.is_recycle
    assert feed.frame is not None and prod.frame is not None and valve.frame is not None
    assert feed.frame.x < valve.frame.x < prod.frame.x
    for balloon in (ft, fic):
        assert balloon.frame is not None
        assert balloon.frame.col is None


def test_a_condenser_is_not_drawn_below_the_column_it_serves() -> None:
    """Check that a column's condenser is drawn above its reboiler and both to its east."""
    fs = Flowsheet("reflux")
    feed = fs.add(U.Feed("Feed"))
    tower = fs.add(U.DistillationColumn("T-701", internals="baffle_tray", trays=10))
    condenser = fs.add(D.ShellAndTubeExchanger("E-701", variant="straight_tubes"))
    drum = fs.add(U.Vessel("V-701", variant="horizontal"))
    vent = fs.add(U.Product("Vent Gas"))
    split = fs.add(U.Splitter("SP-701", n_outlets=2))
    dist = fs.add(U.Product("Distillate"))
    reboiler = fs.add(D.KettleReboiler("E-702"))
    bottoms = fs.add(U.Product("Bottoms"))

    fs.connect(feed.outlet, tower.feed_1)
    fs.connect(tower.overhead, condenser.shell_in)
    fs.connect(condenser.shell_out, drum.ports["in_1"])
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.ports["out_1"], split.inlet)
    fs.connect(split.ports["out_1"], dist.inlet)
    fs.connect(split.ports["out_2"], tower.reflux_in)
    fs.connect(tower.bottoms, reboiler.shell_in)
    fs.connect(reboiler.shell_out, tower.boilup_in)
    fs.connect(reboiler.bottoms, bottoms.inlet)
    fs.layout()

    assert tower.frame is not None
    assert condenser.frame is not None
    assert reboiler.frame is not None
    assert reboiler.frame.cy > tower.frame.cy, (
        f"the reboiler is drawn at y={reboiler.frame.cy}, above the column "
        f"it boils at y={tower.frame.cy}"
    )
    assert condenser.frame.cy < reboiler.frame.cy, (
        f"the overhead condenser (y={condenser.frame.cy}) is drawn below "
        f"the reboiler (y={reboiler.frame.cy}); the sheet is upside down"
    )
    assert condenser.frame.cx > tower.frame.cx
    assert reboiler.frame.cx > tower.frame.cx


# --- order within a layer ------------------------------------------------------


def test_two_units_fed_by_one_take_two_rows_of_the_next_column() -> None:
    """Check that two units sharing a feeder share its next column on separate rows."""
    fs = Flowsheet("Branch")
    separator = fs.add(U.Separator("S1"))
    reactor = fs.add(U.Reactor("R1"))
    mixer = fs.add(U.Mixer("M1"))
    fs.connect(separator.vapor, reactor.feed)
    fs.connect(separator.liquid, mixer.in_1)
    fs.layout()

    assert separator.frame is not None and reactor.frame is not None and mixer.frame is not None
    assert separator.frame.row == 0
    assert separator.frame.col is not None
    assert reactor.frame.col == mixer.frame.col == separator.frame.col + 1
    assert {reactor.frame.row, mixer.frame.row} == {0, 1}


def test_crossing_reduction_runs_left_of_column_zero() -> None:
    """Check that a layer pinned left of column 0 still orders the next one."""
    fs = Flowsheet("negative column")
    a, b, c = (fs.add(U.Block(n, inputs=1, outputs=1)) for n in "ABC")
    x, y, z = (fs.add(U.Block(n, inputs=1, outputs=1)) for n in "XYZ")
    for src, dest in ((a, z), (b, y), (c, x)):
        fs.connect(src.out_1, dest.in_1)
        src.pin(col=-1)
    fs.layout()

    assert x.frame is not None and y.frame is not None and z.frame is not None
    # Each sink follows the source feeding it, so no run crosses another.
    assert [z.frame.row, y.frame.row, x.frame.row] == [0, 1, 2]


# --- straightening ---------------------------------------------------------------


def test_a_pipe_runs_level_onto_a_resized_unit() -> None:
    """Check that a feed lines up with a resized drum's inlet, not its symbol's."""
    fs = Flowsheet("straighten")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal", height=42))
    fs.connect(feed.outlet, drum.inlet)
    fs.layout()

    assert feed.frame is not None and drum.frame is not None
    assert port_point(feed, feed.frame, "outlet")[1] == port_point(drum, drum.frame, "inlet")[1]


def test_a_train_lines_up_with_a_unit_pinned_in_y() -> None:
    """Check that every pipe of a straight train runs level when one block is pinned in y."""
    fs = _long_train(6)
    fs.units[3].pin(y=300)
    fs.layout()

    assert _width_and_rows(fs)[1] == 1


def test_vertical_vent_terminal_aligns_without_overriding_exact_pins() -> None:
    """Check that a free vent rises straight off its nozzle, and pinned x values hold."""
    free = Flowsheet("Free vent")
    vessel = free.add(U.Vessel("V-1", variant="horizontal", width=150, height=48))
    vent = free.add(U.Vent("VT-1"))
    stream = free.connect(vessel.vent, vent.inlet)
    free.layout()
    free.route()

    assert vessel.frame is not None and vent.frame is not None and stream.route is not None
    assert port_point(vessel, vessel.frame, "vent")[0] == pytest.approx(
        port_point(vent, vent.frame, "inlet")[0]
    )
    assert real_bends(stream.route.waypoints) == 0

    pinned = Flowsheet("Pinned vent")
    vessel = pinned.add(U.Vessel("V-2", variant="horizontal", width=150, height=48))
    vent = pinned.add(U.Vent("VT-2"))
    vessel.pin(x=100)
    vent.pin(x=50)
    pinned.connect(vessel.vent, vent.inlet)
    pinned.layout()
    pinned.route()

    assert vessel.frame is not None and vent.frame is not None
    assert vessel.frame.x == 100
    assert vent.frame.x == 50


# --- grid pins --------------------------------------------------------------------


def test_a_col_pin_sets_the_layer() -> None:
    """Check that a pinned column holds and the next unit along takes the one after."""
    fs = Flowsheet("Pinned col")
    reactor = fs.add(U.Reactor("R1"))
    separator = fs.add(U.Separator("S1"))
    fs.connect(reactor.outlet, separator.feed)
    reactor.pin(col=2, row=0)
    fs.layout()

    assert reactor.frame is not None and separator.frame is not None
    assert reactor.frame.col == 2
    assert separator.frame.col == 3


def test_a_unit_between_two_pins_is_drawn_between_them() -> None:
    """Check that a pump between a feed in column 0 and a drum in column 6 lands between."""
    fs = Flowsheet("pinned slack")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, drum.inlet)
    feed.pin(col=0)
    drum.pin(col=6)
    fs.layout()

    assert feed.frame is not None and pump.frame is not None and drum.frame is not None
    assert feed.frame.col == 0
    assert drum.frame.col == 6
    assert pump.frame.col is not None and 0 < pump.frame.col < 6


def test_two_pins_that_contradict_hold_and_the_derived_one_gives() -> None:
    """Check that ``P-1`` east of ``P-3`` holds with the flow running the other way."""
    fs = Flowsheet("conflicting pins")
    a = fs.add(U.Pump("P-1"))
    b = fs.add(U.Pump("P-2"))
    c = fs.add(U.Pump("P-3"))
    fs.connect(a.discharge, b.suction)
    fs.connect(b.discharge, c.suction)
    a.pin(col=3)
    c.pin(col=0)
    fs.layout()

    assert a.frame is not None and b.frame is not None and c.frame is not None
    assert a.frame.col == 3
    assert c.frame.col == 0
    assert b.frame.col is not None


def test_grid_pins_are_recorded_and_a_lone_unit_starts_at_the_margin() -> None:
    """Check that a col and row pin are the frame's, and the unit is not moved off the margin."""
    fs = Flowsheet("Lone")
    reactor = fs.add(U.Reactor("R1"))
    reactor.pin(col=1, row=2)
    fs.layout()

    assert reactor.frame is not None
    assert (reactor.frame.col, reactor.frame.row) == (1, 2)
    assert (reactor.frame.x, reactor.frame.y) == (MARGIN, MARGIN)


def test_a_row_pinned_above_row_zero_draws() -> None:
    """Check that ``pin(row=-1)`` is recorded and drawn on the page."""
    fs = Flowsheet("negative row")
    top = fs.add(U.Feed("Top"))
    bottom = fs.add(U.Feed("Bottom"))
    mixer = fs.add(U.Mixer("M-1"))
    fs.connect(top.outlet, mixer.in_1)
    fs.connect(bottom.outlet, mixer.in_2)
    top.pin(row=-1)
    bottom.pin(row=2)
    fs.layout()

    assert top.frame is not None and bottom.frame is not None
    assert top.frame.row == -1
    assert bottom.frame.row == 2
    assert min(top.frame.y, bottom.frame.y) >= MARGIN


@pytest.mark.parametrize("pin_row", [None, 0, 1, 2, -1])
def test_pinning_a_row_does_not_flip_a_north_feed(pin_row: int | None) -> None:
    """Check that a block's row pin leaves its roof feed above it.

    Parameters
    ----------
    pin_row : int or None
        Row pinned on the block, or ``None`` for no pin.
    """
    fs = Flowsheet("stack")
    block = fs.add(U.Block("Reaction", inputs=["W", "N"], outputs=1))
    feed = fs.add(U.Feed("Main"))
    air = fs.add(U.Feed("Air"))
    prod = fs.add(U.Product("Out"))
    fs.connect(feed.outlet, block.in_1)
    fs.connect(air.outlet, block.in_2)
    fs.connect(block.out_1, prod.inlet)
    if pin_row is not None:
        block.pin(row=pin_row)
    fs.layout()

    assert air.frame is not None and block.frame is not None
    assert air.frame.y_max <= block.frame.y
    if pin_row is not None:
        assert block.frame.row == pin_row


# --- pixel pins -------------------------------------------------------------------


def test_x_and_y_pins_are_exact_even_when_they_conflict() -> None:
    """Check that two pumps pinned to one point stay there and the overlap is reported."""
    fs = Flowsheet("Conflicting pixel pins")
    a = fs.add(U.Pump("P-1")).pin(x=400, y=300)
    b = fs.add(U.Pump("P-2")).pin(x=400, y=300)
    fs.connect(a.discharge, b.suction)
    fs.layout()

    assert a.frame is not None and b.frame is not None
    assert (a.frame.x, a.frame.y) == (400, 300)
    assert (b.frame.x, b.frame.y) == (400, 300)
    with pytest.raises(ValueError, match="overlap"):
        fs.to_svg()


def _pixel_anchored_pump(
    dx: float = 0, dy: float = 0, vertical: bool = False
) -> tuple[Flowsheet, U.Pump]:
    """Return a laid-out free pump between a pinned feed and product.

    Parameters
    ----------
    dx, dy : float
        Offset added to both flags' pins.
    vertical : bool
        Whether the three are turned to run down the sheet.

    Returns
    -------
    tuple[Flowsheet, Pump]
        The laid-out sheet and its pump.
    """
    fs = Flowsheet("Pixel anchors")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-1"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    if vertical:
        pump.pin(orientation=90)
        feed.pin(x=400 + dx, y=100 + dy, orientation=90)
        product.pin(x=400 + dx, y=700 + dy, orientation=90)
    else:
        feed.pin(x=100 + dx, y=400 + dy)
        product.pin(x=700 + dx, y=400 + dy)
    fs.layout()
    return fs, pump


def test_free_pump_follows_translated_pixel_anchors() -> None:
    """Check that moving both flags' x pins moves the free pump between them by as much."""
    before_fs, before = _pixel_anchored_pump()
    after_fs, after = _pixel_anchored_pump(dx=1000)
    feed, product = after_fs.units[0], after_fs.units[-1]

    assert before.frame is not None and after.frame is not None
    assert feed.frame is not None and product.frame is not None
    assert after.frame.x - before.frame.x == pytest.approx(1000)
    assert after.frame.y == pytest.approx(before.frame.y)
    assert 1100 < after.frame.x < after.frame.x_max < 1700
    assert port_point(feed, feed.frame, "outlet") == (1100, 400)
    assert port_point(product, product.frame, "inlet") == (1700, 400)
    before_fs.to_svg()
    after_fs.to_svg()


def test_vertical_pump_follows_translated_pixel_anchors() -> None:
    """Check that moving both turned flags' y pins moves the free pump between them by as much."""
    _, before = _pixel_anchored_pump(vertical=True)
    fs, after = _pixel_anchored_pump(dy=1000, vertical=True)

    assert before.frame is not None and after.frame is not None
    assert after.frame.y - before.frame.y == pytest.approx(1000)
    assert after.frame.x == pytest.approx(before.frame.x)
    assert 1100 < after.frame.y < after.frame.y_max < 1700
    fs.to_svg()


def test_partial_pixel_pins_follow_transformed_nozzles_and_preserve_grid_intent() -> None:
    """Check that pins on a turned nozzle hold and the sheet lays out the same every time."""

    def build_partial(dx: float, dy: float) -> tuple[Flowsheet, U.Pump, D.Valve, U.Product]:
        fs = Flowsheet("Partial transformed anchors")
        pump = fs.add(U.Pump("P-1", width=140, height=100))
        valve = fs.add(D.Valve("V-1"))
        product = fs.add(U.Product("Product"))
        pump.pin(col=1, port="discharge", x=1000 + dx, y=400 + dy, orientation=90, mirrored="x")
        product.pin(row=2, x=1800 + dx)
        fs.connect(pump.discharge, valve.inlet)
        fs.connect(valve.outlet, product.inlet)
        fs.layout()
        return fs, pump, valve, product

    _, _, valve_before, _ = build_partial(0, 0)
    after, pump, valve, product = build_partial(1000, 500)

    assert valve_before.frame is not None and valve.frame is not None
    assert pump.frame is not None and product.frame is not None and product.pin_ is not None
    assert valve.frame.x - valve_before.frame.x == pytest.approx(1000)
    assert valve.frame.y - valve_before.frame.y == pytest.approx(500)
    assert port_point(pump, pump.frame, "discharge") == pytest.approx((2000, 900))
    assert port_point(product, product.frame, "inlet")[0] == 2800
    assert pump.frame.col == 1
    assert product.frame.row == 2
    assert product.pin_.y is None
    assert (pump.frame.w, pump.frame.h) == (140, 100)
    restored = Flowsheet.from_dict(after.to_dict())
    restored.layout()
    assert restored.to_dict() == after.to_dict()
    expected = [unit.frame for unit in after.units]
    after.layout()
    assert [unit.frame for unit in after.units] == expected
    assert [unit.frame for unit in restored.units] == expected


def test_translating_every_pin_translates_the_drawing() -> None:
    """Check that moving every biodiesel pin 1000 down and right moves every unit as far."""
    fs, _ = build()
    fs.layout()
    fs.route()
    before = {}
    for unit in fs.units:
        assert unit.frame is not None
        before[unit.name] = (unit.frame.x, unit.frame.y)
    for unit in fs.units:
        for axis, (port, value) in pin_intent(unit).items():
            unit.pin(**{axis: value + 1000}, port=port)
    fs.layout()
    fs.route()

    for unit in fs.units:
        assert unit.frame is not None
        x, y = before[unit.name]
        assert (unit.frame.x, unit.frame.y) == pytest.approx((x + 1000, y + 1000)), unit.name


def test_a_branched_sheet_with_partial_pins_draws() -> None:
    """Check that a branched sheet pinned on one axis here and two there renders."""
    fs = Flowsheet("Branched pixel anchors")
    feed = fs.add(U.Feed("F"))
    separator = fs.add(U.Separator("S"))
    first = fs.add(U.Pump("P1"))
    second = fs.add(U.Pump("P2"))
    a = fs.add(U.Product("A"))
    b = fs.add(U.Product("B"))
    fs.connect(feed.outlet, separator.feed)
    fs.connect(separator.vapor, first.suction)
    fs.connect(separator.liquid, second.suction)
    fs.connect(first.discharge, a.inlet)
    fs.connect(second.discharge, b.inlet)
    b.pin(x=450)
    feed.pin(y=200)
    a.pin(x=1400, y=375)
    fs.to_svg()


def test_units_sharing_a_layer_with_a_pinned_unit_keep_clear_of_it() -> None:
    """Check that free heights in a layer stack clear of a tall pinned unit, x pins exact."""
    fs = Flowsheet("Clearance within a layer")
    obstacle = fs.add(U.Pump("Fixed", height=540)).pin(x=50, y=0)
    top = fs.add(U.Pump("Top")).pin(x=50, row=3)
    bottom = fs.add(U.Pump("Bottom")).pin(x=50, row=4)
    fs.to_svg()

    assert obstacle.frame is not None and top.frame is not None and bottom.frame is not None
    assert (obstacle.frame.x, obstacle.frame.y) == (50, 0)
    assert (top.frame.x, bottom.frame.x) == (50, 50)
    assert (top.frame.row, bottom.frame.row) == (3, 4)
    assert _overlapping(fs) == []


def test_a_free_axis_keeps_clear_of_a_pinned_unit() -> None:
    """Check that a pump pinned only in y is placed clear of one pinned in both."""
    fs = Flowsheet("Partial pin clearance")
    fixed = fs.add(U.Pump("Fixed")).pin(x=50, y=50)
    free = fs.add(U.Pump("Free")).pin(y=50)
    fs.layout()

    assert fixed.frame is not None and free.frame is not None
    assert (fixed.frame.x, fixed.frame.y) == (50, 50)
    assert free.frame.y == 50
    assert _overlapping(fs) == []


def test_a_pinned_feed_flag_is_kept_clear_where_it_is_drawn() -> None:
    """Check that a pump pinned in y keeps clear of the flag a long feed tag draws."""
    fs = Flowsheet("Drawn extent clearance")
    feed = fs.add(U.Feed("Long feed label that extends far to the left")).pin(x=300, y=100)
    pump = fs.add(U.Pump("Rotated", width=140, height=90)).pin(y=75, orientation=90, mirrored="x")
    fs.layout()

    assert feed.frame is not None and pump.frame is not None
    assert port_point(feed, feed.frame, "outlet") == (300, 100)
    assert (pump.frame.y, pump.frame.w, pump.frame.h) == (75, 140, 90)
    assert unit_box(feed, feed.frame)[0] < feed.frame.x
    assert _overlapping(fs) == []


def test_an_x_pinned_unit_and_its_balloon_keep_clear_of_a_pinned_body() -> None:
    """Check that a pump pinned in x over a wide pinned body is placed clear of it."""
    fs = Flowsheet("Instrument clearance")
    fixed = fs.add(U.Pump("Fixed", width=1500, height=400)).pin(x=0, y=50)
    host = fs.add(U.Pump("Host", width=100, height=100)).pin(x=550)
    fs.connect(fixed.discharge, host.suction)
    fs.add_instrument("LT", 1, sensing=host, face="S", offset=40)
    fs.layout()

    assert fixed.frame is not None and host.frame is not None
    assert (fixed.frame.x, fixed.frame.y) == (0, 50)
    assert host.frame.x == 550
    assert _unit_overlaps(fs) == []


def test_two_units_pinned_to_one_column_and_height_sit_side_by_side() -> None:
    """Check that two pumps pinned to one column at one height do not overlap."""
    fs = Flowsheet("Room within a column")
    left = fs.add(U.Pump("Left", width=100)).pin(col=0, y=150)
    right = fs.add(U.Pump("Right")).pin(col=2, row=0)
    fixed = fs.add(U.Pump("Fixed", width=50)).pin(x=100, y=50)
    a = fs.add(U.Pump("A", width=50)).pin(col=1, y=50)
    b = fs.add(U.Pump("B", width=70, height=50)).pin(col=1, y=50)
    fs.layout()

    for unit in (left, right, fixed, a, b):
        assert unit.frame is not None
    assert fixed.frame is not None and left.frame is not None
    assert a.frame is not None and b.frame is not None
    assert (fixed.frame.x, fixed.frame.y) == (100, 50)
    assert (left.frame.y, a.frame.y, b.frame.y) == (150, 50, 50)
    assert _overlapping(fs) == []


def test_the_pinned_biodiesel_sheet_draws_without_an_overlap() -> None:
    """Check that a sheet pinned mostly by height lays out with no two units overlapping."""
    fs, _ = build()
    fs.layout()
    fs.route()

    assert _unit_overlaps(fs) == []


# --- bands -------------------------------------------------------------------------


def test_a_ribbon_wider_than_the_paper_is_folded_into_bands() -> None:
    """Check that a train too wide for the paper is folded, not squashed."""
    fs = _long_train(30)
    fs.layout()

    width, rows = _width_and_rows(fs)
    assert width <= BAND_WIDTH
    assert rows > 1


def test_a_ribbon_that_fits_the_paper_is_left_alone() -> None:
    """Check that a train that fits is drawn as one row."""
    fs = _long_train(6)
    fs.layout()

    assert _width_and_rows(fs)[1] == 1


@pytest.mark.parametrize("axis", ["x", "y"])
def test_a_pixel_pinned_ribbon_is_not_folded(axis: str) -> None:
    """Check that a wide train with one unit pinned in x or y is not folded onto the pin.

    Parameters
    ----------
    axis : str
        Axis pinned on the first block.
    """
    fs = _long_train(30)
    fs.units[1].pin(**{axis: 200})
    fs.layout()

    assert _width_and_rows(fs)[0] > BAND_WIDTH


# --- margins, overlaps and determinism ------------------------------------------------


def test_the_drawing_and_its_balloon_halos_start_at_the_margin() -> None:
    """Check that the top-left of an unpinned sheet, balloon room included, is at the margin."""
    fs = Flowsheet("Margin")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-1"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, fs.add(U.Product("P")).inlet)
    fs.add_instrument("PT", 1, sensing=drum, face="N", offset=60)
    fs.add_instrument("TT", 1, sensing=feed, face="W", offset=60)
    fs.layout()

    pads = balloon_pads(fs)
    assert pads, "no unit reserves room for its balloons"
    lefts, tops = [], []
    for unit in fs.units:
        assert unit.frame is not None
        x0, y0, _, _ = unit_box(unit, unit.frame)
        pad = pads.get(unit)
        lefts.append(x0 - (pad.west if pad else 0.0))
        tops.append(y0 - (pad.north if pad else 0.0))
    assert (min(lefts), min(tops)) == (MARGIN, MARGIN)


def test_a_balloon_on_a_unit_face_takes_no_room_beside_the_unit() -> None:
    """Check that a balloon on a drum's top leaves its neighbours one column gap away."""
    fs = Flowsheet("Side room")
    feed, drum, product = fs.add(U.Feed("Feed")), fs.add(U.Vessel("V-1")), fs.add(U.Product("P"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, product.inlet)
    fs.add_instrument("PT", 1, sensing=drum, face="N", offset=60)
    fs.route()

    boxes = _drawn_boxes(fs)
    assert boxes["V-1"][0] - boxes["Feed"][2] == pytest.approx(COL_GAP)
    assert boxes["P"][0] - boxes["V-1"][2] == pytest.approx(COL_GAP)


def test_no_two_units_overlap_judged_by_the_boxes_they_draw() -> None:
    """Check a folded sheet of roof-fed blocks with long feed tags for overlaps."""
    fs = Flowsheet("Stacked")
    port = fs.add(U.Feed("F")).outlet
    for i in range(30):
        block = fs.add(U.Block(f"B-{i}", inputs=["W", "N"], outputs=["E"]))
        fs.connect(port, block.in_1)
        fs.connect(fs.add(U.Feed(f"AIR AND STEAM SUPPLY {i}")).outlet, block.in_2)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    fs.layout()

    flag = fs.units[2]
    assert flag.frame is not None and unit_box(flag, flag.frame)[0] < flag.frame.x
    assert _overlapping(fs) == []


def _chain() -> tuple[Flowsheet, list[U.Block]]:
    fs = Flowsheet("chain")
    blocks = [fs.add(U.Block(name, inputs=["W"], outputs=["E"])) for name in "ABC"]
    fs.connect(blocks[0].out_1, blocks[1].in_1)
    fs.connect(blocks[1].out_1, blocks[2].in_1)
    return fs, blocks


def _arrangement(units: "Sequence[U.Unit]") -> list[tuple[int, int]]:
    """Return each unit's column and row relative to the first unit."""
    frames = [u.frame for u in units]
    assert all(f is not None and f.col is not None and f.row is not None for f in frames)
    origin = frames[0]
    assert origin is not None and origin.col is not None and origin.row is not None
    out: list[tuple[int, int]] = []
    for frame in frames:
        assert frame is not None and frame.col is not None and frame.row is not None
        out.append((frame.col - origin.col, frame.row - origin.row))
    return out


def test_an_unrelated_group_cannot_move_this_one() -> None:
    fs, (a, b, c) = _chain()
    fs.layout()
    alone = _arrangement([a, b, c])

    fs, (a, b, c) = _chain()
    x = fs.add(U.Vessel("X"))
    y = fs.add(U.Vessel("Y"))
    fs.connect(x.outlet, y.inlet)  # a stiffer pair, joined to nothing
    fs.layout()

    assert _arrangement([a, b, c]) == alone, (
        "adding a vessel pair with no connection to A, B or C rearranged them"
    )
    # And the newcomers are on the sheet rather than on top of it.
    assert x.frame is not None and y.frame is not None
    assert (x.frame.col, x.frame.row) != (y.frame.col, y.frame.row)
    assert {(u.frame.col, u.frame.row) for u in (a, b, c) if u.frame is not None}.isdisjoint(
        {(x.frame.col, x.frame.row), (y.frame.col, y.frame.row)}
    )


def test_laying_out_twice_gives_identical_frames() -> None:
    """Check that a sheet with roof feeds lays out the same way twice."""
    fs, *_ = _syngas_block()
    fs.layout()
    first = [unit.frame for unit in fs.units]
    fs.layout()

    assert [unit.frame for unit in fs.units] == first


def _interlock_on_a_signal() -> tuple[Flowsheet, U.Unit]:
    """Return ``examples/04_control_loop.py``'s shape: a balloon on a balloon's line.

    Returns
    -------
    tuple[Flowsheet, Unit]
        The unlaid sheet and its interlock.
    """
    fs = Flowsheet("interlock")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    lt = fs.add_instrument("LT", 101, sensing=drum, face="S", offset=70)
    lic = fs.add_instrument("LIC", 101, near=lt, face="S", offset=95, variant="shared")
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    interlock = fs.add_instrument(
        "I", 1, sensing=measurement, at=0.5, offset=44, angle=90, variant="logic"
    )
    return fs, interlock


def test_laying_a_sheet_out_twice_puts_every_box_in_the_same_place() -> None:
    """Check that a balloon hung on a signal is placed the same on every layout."""
    fs, interlock = _interlock_on_a_signal()
    fs.layout()
    first = {unit.name: unit.frame for unit in fs.units}
    assert first[interlock.name] is not None
    fs.layout()
    assert {unit.name: unit.frame for unit in fs.units} == first
    fs.layout()
    assert {unit.name: unit.frame for unit in fs.units} == first


def test_the_face_a_signal_leaves_on_is_settled_before_the_labels_are_placed() -> None:
    """Check that layout ends on a face selection no further balloon pass changes."""
    fs, _ = _interlock_on_a_signal()
    fs.layout()

    lt = next(unit for unit in fs.units if unit.name == "LT-101")
    assert lt.frame is not None
    before = dict(lt.frame.port_faces)
    assert not place_attached(fs), "a further pass still moves a balloon"
    assert dict(lt.frame.port_faces) == before


@pytest.mark.parametrize("skip", ["s103", "dirty_water"])
def test_an_unpinned_sheet_matches_a_fresh_build_and_keeps_remaining_pins(skip: str) -> None:
    """Check that removing a pin draws what a build without it draws.

    Parameters
    ----------
    skip : str
        Key of the unit whose pin is removed.
    """
    live, units = build()
    live.layout()
    live.route()
    units[skip].pin_ = None
    fresh, _ = build(skip=skip)

    assert live.to_svg(check=False) == fresh.to_svg(check=False)
    for unit in live.units:
        assert unit.frame is not None
        for axis, (port, value) in pin_intent(unit).items():
            point = port_point(unit, unit.frame, port) if port else (unit.frame.x, unit.frame.y)
            assert point[0 if axis == "x" else 1] == pytest.approx(value)
    frames = [unit.frame for unit in live.units]
    live.layout()
    live.route()
    assert [unit.frame for unit in live.units] == frames


def test_full_layout_via_render(tmp_path: Path) -> None:
    """Check that rendering an unlaid sheet lays it out first.

    Parameters
    ----------
    tmp_path : Path
        Output directory.
    """
    fs = Flowsheet("Test")
    reactor = fs.add(U.Reactor("R1"))
    separator = fs.add(U.Separator("S1"))
    fs.connect(reactor.outlet, separator.feed)
    svg_path = tmp_path / "test.svg"
    fs.render(str(svg_path))

    assert reactor.frame is not None and separator.frame is not None
    assert separator.frame.col == 1
    assert "<use" in svg_path.read_text()


# --- balloons -----------------------------------------------------------------------


def _panel() -> tuple[Flowsheet, U.Instrument, D.ControlValve]:
    """Return a feed, control valve and product with a free-standing controller on the valve.

    Returns
    -------
    tuple[Flowsheet, Instrument, ControlValve]
        The unlaid sheet, its controller and its valve.
    """
    fs = Flowsheet("panel")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fic = fs.add(U.Instrument("FIC-101"))
    fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    return fs, fic, valve


def test_a_free_standing_balloon_is_placed_near_what_it_is_wired_to() -> None:
    """Check that a controller wired to a valve is drawn near it but not on it."""
    fs, fic, valve = _panel()
    fs.layout()

    assert fic.frame is not None and valve.frame is not None
    reach = abs(fic.frame.cx - valve.frame.cx) + abs(fic.frame.cy - valve.frame.cy)
    assert reach < 400, "the controller is nowhere near the valve it commands"
    assert not overlaps(unit_box(fic, fic.frame), unit_box(valve, valve.frame))


def test_a_free_standing_balloon_stays_off_a_feed_flag_where_it_is_drawn() -> None:
    """Check that a balloon keeps clear of the flag drawn, not of the flag's frame."""
    fs = Flowsheet("panel")
    valve = fs.add(D.ControlValve("FV-101")).pin(x=500, y=300)
    feed = fs.add(U.Feed("FEED FROM UNIT 100 STORAGE AREA")).pin(x=880, y=290)
    fs.connect(feed.outlet, fs.add(U.Product("P")).pin(x=1200, y=600).inlet)
    fic = fs.add(U.Instrument("FIC-101")).pin(y=300)
    fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()

    assert fic.frame is not None and feed.frame is not None
    flag = unit_box(feed, feed.frame)
    assert flag[0] < feed.frame.x, "the flag is meant to be drawn left of its frame"
    assert not overlaps(unit_box(fic, fic.frame), flag), "the balloon is on the flag"


def test_a_chain_of_balloons_is_reserved_paper_before_anything_is_placed() -> None:
    """Check that a balloon chain on an orifice plate lands on nothing else."""
    fs = Flowsheet("halo")
    feed = fs.add(U.Feed("Feed"))
    plate = fs.add(D.Fitting("FE-101", variant="orifice"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, plate.inlet)
    fs.connect(plate.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    top = fs.add_balloon(plate, face="N", offset=38)
    ft = fs.add_instrument("FT", 101, near=top, face="N", offset=23)
    fs.add_instrument("FIC", 101, near=ft, face="N", offset=60, variant="shared")
    fs.route()

    assert _unit_overlaps(fs) == [], "a balloon was drawn over something"


def _lanes(fs: Flowsheet) -> tuple[dict[int, float], dict[int, float]]:
    """Return where each grid column and row the balloons are measured against starts."""
    cols, rows = control_grid(fs)
    return ({k: v[0] for k, v in cols.items()}, {k: v[0] for k, v in rows.items()})


def test_a_pinned_column_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic, _ = _panel()
    fic.pin(col=0)
    fs.layout()

    cols, _ = _lanes(fs)
    assert fic.frame is not None
    assert fic.frame.x == cols[0], (
        f"pin(col=0) put FIC-101 at x={fic.frame.x}, but column 0 is at x={cols[0]}"
    )


def test_a_pinned_row_on_a_free_standing_balloon_is_honoured() -> None:
    fs, fic, _ = _panel()
    fic.pin(row=0)
    fs.layout()

    _, rows = _lanes(fs)
    assert fic.frame is not None
    assert fic.frame.y == rows[0], (
        f"pin(row=0) put FIC-101 at y={fic.frame.y}, but row 0 is at y={rows[0]}"
    )


def test_a_column_past_the_last_one_the_sheet_used_is_still_honoured() -> None:
    """Check that a column past the sheet's last is placed by continuing the grid's pitch."""
    fs, fic, _ = _panel()
    fic.pin(col=7)
    fs.layout()

    cols, _ = _lanes(fs)
    assert fic.frame is not None
    assert 7 not in cols, (
        f"column 7 is the balloon's own rank, not a line stage 1 drew: {sorted(cols)}"
    )
    assert max(cols) < 7, "this sheet is supposed to be narrower than the pin"
    pitch = (cols[max(cols)] - cols[min(cols)]) / (max(cols) - min(cols))
    assert fic.frame.x == cols[max(cols)] + (7 - max(cols)) * pitch


def test_a_balloon_does_not_move_the_lane_the_next_balloon_is_measured_against() -> None:
    """Check that a balloon in column 0 does not widen the column the next is measured from."""
    fs = Flowsheet("one-column")
    valve = fs.add(D.ControlValve("FV-101"))
    first = fs.add(U.Instrument("FIC-101"))
    fs.connect(first.sig_out, valve.actuator, kind="pneumatic")
    second = fs.add(U.Instrument("XI-1"))
    fs.connect(second.sig_out, first.sig_in, kind="electric")
    first.pin(col=0)
    second.pin(col=1)
    fs.layout()

    assert valve.frame is not None and first.frame is not None
    assert second.frame is not None
    assert first.frame.w > valve.frame.w, (
        "this test needs a balloon wider than the column it stands in"
    )
    assert first.frame.x == valve.frame.x
    assert second.frame.x == valve.frame.x + valve.frame.w + COL_GAP, (
        f"XI-1 is at x={second.frame.x}; column 1 of a sheet whose only column "
        f"is the valve's is at x={valve.frame.x + valve.frame.w + COL_GAP}"
    )
