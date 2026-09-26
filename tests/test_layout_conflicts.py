"""Observable conflicts used by route-constrained placement."""

from __future__ import annotations

from pandid import Block, Feed, Flowsheet, Product
from pandid.layout.conflicts import Conflict, analyze_conflicts
from pandid.layout.quality import admissible, measure_final
from pandid.portgeom import resolve_port
from pandid.routing.metrics import crossing_pairs


def test_exchanging_the_blocking_unit_is_not_an_improvement() -> None:
    """Reject a same-count defect transferred to another unit.

    Returns
    -------
    None
        Conflict identity blocks the candidate despite equal counts.
    """
    fs = Flowsheet("Swapped blocker")
    source = fs.add(Feed("Feed"))
    dest = fs.add(Product("Product"))
    first = fs.add(Block("First", inputs=0, outputs=1))
    second = fs.add(Block("Second", inputs=0, outputs=1))
    source.pin(x=0, y=50)
    dest.pin(x=300, y=50)
    stream = fs.connect(source.outlet, dest.inlet)
    fs.layout()
    fs.route()
    first.frame.x = second.frame.x = 140
    first.frame.y, second.frame.y = 20, 200
    stream.route.waypoints = [
        resolve_port(source, source.frame, "outlet").anchor,
        resolve_port(dest, dest.frame, "inlet").anchor,
    ]
    before = measure_final(fs)
    first.frame.y, second.frame.y = second.frame.y, first.frame.y
    after = measure_final(fs)

    assert before.hard == after.hard
    assert before.crossings == after.crossings
    assert before.hard_conflicts != after.hard_conflicts
    assert not admissible(before, after)


def test_fixed_blocker_names_the_sealed_source_exit() -> None:
    """Identify the unit that seals a pinned nozzle's escape.

    Returns
    -------
    None
        The route and conflict retain the exact pinned geometry.
    """
    fs = Flowsheet("Sealed exit")
    source = fs.add(Feed("Feed"))
    dest = fs.add(Product("Product"))
    blocker = fs.add(Block("Blocker", inputs=0, outputs=1))
    source.pin(x=0, y=50)
    dest.pin(x=300, y=50)
    blocker.pin(x=10, y=20)
    stream = fs.connect(source.outlet, dest.inlet)
    fs.layout()
    fs.route()

    assert stream.route.used_fallback
    assert Conflict("blocked-exit", (0,), (0, 2), "outlet") in analyze_conflicts(fs)
    assert resolve_port(source, source.frame, "outlet").anchor == (0, 50)
    assert (blocker.frame.x, blocker.frame.y) == (10, 20)


def test_detached_and_inward_stubs_are_named() -> None:
    """Catch route defects even when the remaining path is clear.

    Returns
    -------
    None
        Both endpoint and exit checks produce stable conflict identities.
    """
    fs = Flowsheet("Bad stubs")
    source = fs.add(Feed("Feed"))
    dest = fs.add(Product("Product"))
    stream = fs.connect(source.outlet, dest.inlet)
    fs.layout()
    fs.route()
    start, end = stream.route.waypoints[0], stream.route.waypoints[-1]

    stream.route.waypoints = [(start[0] + 5, start[1]), end]
    assert Conflict("detached-endpoint", (0,), (0,), "outlet") in analyze_conflicts(fs)

    stream.route.waypoints = [start, (start[0] - 5, start[1]), end]
    assert Conflict("inward-exit", (0,), (0,), "outlet") in analyze_conflicts(fs)


def test_crossing_pairs_keep_indices_of_undrawn_streams() -> None:
    """Do not renumber crossing pairs when an earlier route is missing.

    Returns
    -------
    None
        The pair refers to global stream indices.
    """
    paths = [None, [(0, 5), (10, 5)], [(5, 0), (5, 10)]]
    assert crossing_pairs(paths) == frozenset({(1, 2)})


def test_manual_waypoints_remain_authored_routes() -> None:
    """Keep a valid short manual path out of automatic conflicts.

    Returns
    -------
    None
        A manual line and its authored diagonal remain outside search rules.
    """
    fs = Flowsheet("Manual path")
    source = fs.add(Feed("Feed"))
    dest = fs.add(Product("Product"))
    source.pin(x=100, y=75)
    dest.pin(x=250, y=75)
    stream = fs.connect(source.outlet, dest.inlet)
    stream.via([(150, 75)])
    fs.layout()
    fs.route()
    assert not analyze_conflicts(fs)
    assert measure_final(fs).hard[-1] == 0

    stream.via([(150, 60), (200, 75)])
    assert any(issue.code == "route-diagonal" for issue in fs.validate())
    assert not any(
        conflict.kind in {"route-diagonal", "route-crosses-unit"}
        for conflict in analyze_conflicts(fs)
    )
