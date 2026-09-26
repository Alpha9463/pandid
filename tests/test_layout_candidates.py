"""Behavioral checks for conflict-derived placement moves."""

from __future__ import annotations

from pandid import Block, Feed, Flowsheet, Instrument, Product, units as U
from pandid.layout.candidates import (
    MAX_CANDIDATES,
    Move,
    Translation,
    _move_groups,
    _move_preflight,
    generate_moves,
)
from pandid.layout.conflicts import Conflict, analyze_conflicts
from pandid.layout.halo import balloon_pads
from pandid.layout.trials import evaluate_trial


def _closed_arms() -> Flowsheet:
    """Build two complete process arms with overlapping interiors.

    Returns
    -------
    Flowsheet
        Routed split/merge drawing requiring an arm-level move.
    """
    fs = Flowsheet("Closed arms")
    feed = fs.add(Feed("Feed"))
    split = fs.add(U.Splitter("Split"))
    upper_first = fs.add(U.Pump("Upper 1"))
    upper_second = fs.add(U.Pump("Upper 2"))
    lower_first = fs.add(U.Pump("Lower 1"))
    lower_second = fs.add(U.Pump("Lower 2"))
    merge = fs.add(U.Mixer("Merge", n_inlets=2))
    product = fs.add(Product("Product"))
    for source, dest in (
        (feed.outlet, split.inlet),
        (split.out_1, upper_first.suction),
        (upper_first.discharge, upper_second.suction),
        (upper_second.discharge, merge.in_1),
        (split.out_2, lower_first.suction),
        (lower_first.discharge, lower_second.suction),
        (lower_second.discharge, merge.in_2),
        (merge.outlet, product.inlet),
    ):
        fs.connect(source, dest)
    fs.layout()
    upper_first.frame.y += 100
    upper_second.frame.y += 100
    fs.route()
    return fs


def test_closed_arm_moves_keep_each_connected_interior_together() -> None:
    """Move complete arms, including when two groups move atomically.

    Returns
    -------
    None
        Every proposal preserves group membership and stays bounded.
    """
    fs = _closed_arms()
    moves = generate_moves(fs)
    assert 0 < len(moves) <= MAX_CANDIDATES
    assert moves == generate_moves(_closed_arms())
    assert any(len(move.translations) == 2 for move in moves)
    for move in moves:
        for part in move.translations:
            assert part.units in ((2, 3), (4, 5))
        assert all(index not in part.units for part in move.translations for index in (1, 6))


def test_fully_pinned_obstruction_has_no_legal_move() -> None:
    """Leave an impossible authored obstruction in place for reporting.

    Returns
    -------
    None
        Pins stay exact and no illegal move is offered.
    """
    fs = Flowsheet("Fixed obstruction")
    source = fs.add(Feed("Feed"))
    dest = fs.add(Product("Product"))
    blocker = fs.add(Block("Blocker", inputs=0, outputs=1))
    source.pin(x=0, y=50)
    dest.pin(x=300, y=50)
    blocker.pin(x=10, y=20)
    fs.connect(source.outlet, dest.inlet)
    fs.layout()
    fs.route()

    assert any(item.kind == "blocked-exit" for item in analyze_conflicts(fs))
    assert generate_moves(fs) == ()
    assert (blocker.frame.x, blocker.frame.y) == (10, 20)


def test_mixed_face_blocker_offers_a_clear_adjacent_lane() -> None:
    """Derive a movable blocker lane from an S-to-W connection.

    Returns
    -------
    None
        A detached trial clears the conflict without moving the live sheet.
    """
    fs = Flowsheet("Mixed-face blockage")
    source = fs.add(Block("Source", inputs=0, outputs=["S"]))
    dest = fs.add(Block("Dest", inputs=["W"], outputs=0))
    blocker = fs.add(Block("Blocker", inputs=0, outputs=1))
    source.pin(x=100, y=0)
    dest.pin(x=400, y=200)
    blocker.pin(x=130)
    fs.connect(source.out_1, dest.in_1)
    fs.layout()
    blocker.frame.y = 90
    fs.route()
    before = (blocker.frame.x, blocker.frame.y)
    findings = analyze_conflicts(fs)
    assert any(item.kind == "blocked-exit" for item in findings)

    moves = generate_moves(fs, findings)
    assert moves == generate_moves(fs, findings)
    assert any(part.units == (2,) for move in moves for part in move.translations)
    assert all(part.dx == 0 for move in moves for part in move.translations)
    assert any(evaluate_trial(fs, move).qualified for move in moves)
    assert (blocker.frame.x, blocker.frame.y) == before


def test_fixed_blocker_can_be_cleared_by_a_free_endpoint() -> None:
    """Shift a free stream end around a fully pinned obstacle.

    Returns
    -------
    None
        A short boundary-derived move qualifies without changing pins.
    """
    fs = Flowsheet("Pinned blocker")
    source = fs.add(Block("Source", inputs=0, outputs=["E"]))
    dest = fs.add(Block("Dest", inputs=["W"], outputs=0))
    blocker = fs.add(Block("Blocker", inputs=0, outputs=1))
    source.pin(x=100)
    dest.pin(x=500, y=400)
    blocker.pin(x=235, y=0)
    fs.connect(source.out_1, dest.in_1)
    fs.layout()
    source.frame.y = 0
    fs.route()

    moves = generate_moves(fs)
    assert any(part.units == (0,) and part.dy == 50 for move in moves for part in move.translations)
    assert any(evaluate_trial(fs, move).qualified for move in moves)
    assert (source.frame.x, source.frame.y) == (100, 0)
    assert (blocker.frame.x, blocker.frame.y) == (235, 0)


def test_attached_manual_endpoint_cannot_follow_a_moved_host() -> None:
    """Keep the drawn end of a hand-routed signal fixed.

    Returns
    -------
    None
        Preflight and final quality both reject movement of its host.
    """
    fs = Flowsheet("Attached manual signal")
    host = fs.add(Block("Host", inputs=0, outputs=1))
    transmitter = fs.add(Instrument("LT-101"))
    controller = fs.add(Instrument("LIC-101"))
    transmitter.attach(host, at="E", offset=60)
    controller.pin(x=500, y=200)
    signal = fs.connect(transmitter.sig_out, controller.sig_in, kind="electric")
    signal.via([(300, 200)])
    fs.layout()
    fs.route()

    move = Move((Translation((0,), dy=50),), Conflict("route-cost", streams=(0,)), 100)
    assert not _move_preflight(fs, move, _move_groups(fs), balloon_pads(fs))
    trial = evaluate_trial(fs, move)
    assert trial.before.manual_endpoint_geometry != trial.after.manual_endpoint_geometry
    assert not trial.qualified
