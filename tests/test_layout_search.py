"""Observable outcomes of opt-in layout and route search."""

from __future__ import annotations

from pandid import Block, Flowsheet
from pandid.layout.candidates import Move, Translation, generate_moves
from pandid.layout.conflicts import Conflict
from pandid.layout.quality import measure_final
from pandid.layout.search import SearchBudget, search_layout


def _two_obstructions() -> Flowsheet:
    """Build two separated chains with movable exit blockers.

    Returns
    -------
    Flowsheet
        Routed drawing requiring two independent placement repairs.
    """
    fs = Flowsheet("Two obstructions")
    for branch in range(2):
        source = fs.add(Block(f"Source {branch}", inputs=0, outputs=["S"]))
        dest = fs.add(Block(f"Dest {branch}", inputs=["W"], outputs=0))
        blocker = fs.add(Block(f"Blocker {branch}", inputs=0, outputs=1))
        source.pin(x=100, y=800 * branch)
        dest.pin(x=400, y=200 + 800 * branch)
        blocker.pin(x=130)
        fs.connect(source.out_1, dest.in_1)
    fs.layout()
    for branch in range(2):
        fs.units[3 * branch + 2].frame.y = 90 + 800 * branch
    fs.route()
    return fs


def _geometry(fs: Flowsheet) -> tuple:
    """Capture the visible geometry of a settled test sheet.

    Parameters
    ----------
    fs : Flowsheet
        Drawing to inspect.

    Returns
    -------
    tuple
        Unit frames and routed paths in declaration order.
    """
    return (
        tuple(
            (unit.frame.x, unit.frame.y, tuple(sorted(unit.frame.port_faces.items())))
            for unit in fs.units
        ),
        tuple(tuple(stream.route.waypoints) for stream in fs.streams),
    )


def test_search_accepts_two_repairs_and_rebuilds_identically() -> None:
    """Repair both chains without changing pins or model identities.

    Returns
    -------
    None
        The final route is clear and independent fresh builds agree.
    """
    fs = _two_obstructions()
    units = tuple(fs.units)
    streams = tuple(fs.streams)
    pins = tuple(unit.pin_ for unit in fs.units)
    before = measure_final(fs)
    assert before.hard_conflicts

    budget = SearchBudget(4, 12, 36)
    result = search_layout(fs, budget)
    fresh = _two_obstructions()
    fresh_result = search_layout(fresh, budget)

    assert result.status == "converged"
    assert result.accepted_moves == 2
    assert not result.conflicts
    assert _geometry(fs) == _geometry(fresh)
    assert result == fresh_result
    assert not measure_final(fs).hard_conflicts
    assert all(actual is original for actual, original in zip(fs.units, units))
    assert all(actual is original for actual, original in zip(fs.streams, streams))
    assert tuple(unit.pin_ for unit in fs.units) == pins


def test_search_reports_budget_with_remaining_conflicts() -> None:
    """Report an incomplete repair after one allowed pass.

    Returns
    -------
    None
        One conflict region remains and validation names the limit.
    """
    fs = _two_obstructions()
    result = search_layout(fs, SearchBudget(1, 1, 1))

    assert result.status == "budget_exhausted"
    assert result.accepted_moves == 1
    assert result.exact_trials == 1
    assert result.conflicts
    assert any(issue.code == "layout-search-budget-exhausted" for issue in fs.validate())
    assert fs.units[0].frame.x == 100
    assert fs.units[3].frame.x == 100


def test_search_keeps_incumbent_when_trial_breaks_a_pin(monkeypatch) -> None:
    """Reject an illegal proposal even if its generator offered it.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Temporary proposal source for the final-gate check.

    Returns
    -------
    None
        The original geometry and pinned positions remain unchanged.
    """
    fs = _two_obstructions()
    before = _geometry(fs)
    illegal = Move(
        (Translation((0,), dx=50),),
        Conflict("blocked-exit", streams=(0,), units=(0, 2)),
        1000.0,
    )
    monkeypatch.setattr("pandid.layout.search.generate_moves", lambda *args, **kwargs: (illegal,))

    result = search_layout(fs, SearchBudget(1, 1, 1))

    assert result.status == "unresolved"
    assert result.accepted_moves == 0
    assert result.exact_trials == 1
    assert _geometry(fs) == before
    assert any(issue.code == "layout-search-unresolved" for issue in fs.validate())


def test_search_reports_unexamined_proposals_after_rejection(monkeypatch) -> None:
    """Distinguish a proposal cap from an exhausted local neighbourhood.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Temporary ordered proposal source.

    Returns
    -------
    None
        A failed first trial with another available move reports budget use.
    """
    fs = _two_obstructions()
    before = _geometry(fs)
    legal = generate_moves(fs)[0]
    illegal = Move(
        (Translation((0,), dx=50),),
        Conflict("blocked-exit", streams=(0,), units=(0, 2)),
        1000.0,
    )
    monkeypatch.setattr(
        "pandid.layout.search.generate_moves",
        lambda *args, limit=24: (illegal, legal)[:limit],
    )

    result = search_layout(fs, SearchBudget(2, 1, 2))

    assert result.status == "budget_exhausted"
    assert result.accepted_moves == 0
    assert result.exact_trials == 1
    assert _geometry(fs) == before


def test_canonical_settlement_can_repair_without_a_placement_move() -> None:
    """Publish a clear reroute when no unit translation is needed.

    Returns
    -------
    None
        The opt-in settlement clears a stale fallback with zero moves.
    """
    fs = Flowsheet("Route-only repair")
    source = fs.add(Block("Source", inputs=0, outputs=["E"]))
    dest = fs.add(Block("Dest", inputs=["W"], outputs=0))
    source.pin(x=100, y=100)
    dest.pin(x=400, y=100)
    stream = fs.connect(source.out_1, dest.in_1)
    fs.layout()
    fs.route()
    stream.route.used_fallback = True
    assert measure_final(fs).hard_conflicts

    result = search_layout(fs, SearchBudget(0, 0, 0))

    assert result.status == "converged"
    assert result.accepted_moves == 0
    assert result.exact_trials == 0
    assert not stream.route.used_fallback
    assert not measure_final(fs).hard_conflicts
