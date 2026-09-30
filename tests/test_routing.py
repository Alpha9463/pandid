"""Check obstacle geometry, path search, crossing pricing, and the default router."""

import heapq
from types import SimpleNamespace
from typing import cast

import pytest

from pandid.flowsheet import Flowsheet
from pandid.units import Feed, HeatExchanger, Product, Pump, Valve, Vessel
from pandid.routing import DefaultRouter, get_outward_dir, _fallback_path
from pandid.routing import astar
from pandid.routing.astar import CrossingIndex, committed_segments, find_path
from pandid.routing.visibility import Rect, VisibilityGraph, clear_gaps


def test_router_uses_a_reachable_lane_before_a_blocked_projection() -> None:
    """Reach the graph before an obstacle blocks the nominal nozzle stub.

    Returns
    -------
    None
        The automatic route clears the unrelated body without moving pins.
    """
    fs = Flowsheet("reachable escape")
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=400, y=100)
    blocker = fs.add(Pump("Blocker", width=44, height=44, label_pos="bottom")).pin(x=83, y=78)
    stream = fs.connect(feed.outlet, product.inlet)
    fs.layout()
    graph = VisibilityGraph(fs)
    assert graph.port_projs[("F", "outlet")] not in graph.nodes

    fs.route(DefaultRouter())

    assert stream.route is not None and not stream.route.used_fallback
    assert feed.frame is not None and product.frame is not None and blocker.frame is not None
    assert [
        (feed.frame.x, feed.frame.y),
        (product.frame.x, product.frame.y),
        (blocker.frame.x, blocker.frame.y),
    ] == [(10.0, 75.0), (400.0, 75.0), (83, 78)]
    assert not any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_router_without_recovery_searches_only_the_nominal_projection() -> None:
    """Keep the nominal-projection search available as an opt-out.

    Returns
    -------
    None
        The blocked projection draws the fallback when recovery is disabled.
    """
    fs = Flowsheet("nominal escape")
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=400, y=100)
    fs.add(Pump("Blocker", width=44, height=44, label_pos="bottom")).pin(x=83, y=78)
    stream = fs.connect(feed.outlet, product.inlet)
    fs.layout()
    fs.route(DefaultRouter(recover_exits=False))

    assert stream.route is not None and stream.route.used_fallback


def test_router_reports_a_sealed_fixed_nozzle() -> None:
    """Keep a fully blocked outward nozzle unresolved.

    Returns
    -------
    None
        Fixed equipment stays put and the route records fallback.
    """
    fs = Flowsheet("sealed escape")
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=400, y=100)
    blocker = fs.add(Pump("Blocker", width=44, height=44, label_pos="bottom")).pin(x=60, y=78)
    stream = fs.connect(feed.outlet, product.inlet)
    fs.layout()
    fs.route(DefaultRouter())

    assert stream.route is not None and stream.route.used_fallback
    assert feed.frame is not None and product.frame is not None and blocker.frame is not None
    assert [
        (feed.frame.x, feed.frame.y),
        (product.frame.x, product.frame.y),
        (blocker.frame.x, blocker.frame.y),
    ] == [(10.0, 75.0), (400.0, 75.0), (60, 78)]
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_router_does_not_call_a_blocked_stub_successful() -> None:
    """Reject a graph path whose anchor lead crosses another body.

    Returns
    -------
    None
        The drawn fallback remains explicitly unresolved.
    """
    fs = Flowsheet("blocked stub")
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=400, y=100)
    fs.add(Pump("Blocker", width=12, height=40, label_pos="center")).pin(x=68, y=80)
    stream = fs.connect(feed.outlet, product.inlet)
    fs.layout()
    fs.route(DefaultRouter())

    assert stream.route is not None and stream.route.used_fallback
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_rect_intersection():
    """Distinguish strict containment from segment contact.

    Returns
    -------
    None
        An edge point is not contained; an edge segment intersects.
    """
    r = Rect(10, 20, 10, 20)
    # Contain a point strictly inside.
    assert r.contains(15, 15)
    # Exclude a point on the edge.
    assert not r.contains(10, 15)

    # Intersect a segment that passes through.
    assert r.intersects_segment(5, 15, 25, 15)
    # Intersect a segment that lies on the edge.
    assert r.intersects_segment(10, 5, 10, 25)
    # Miss a segment that lies outside.
    assert not r.intersects_segment(5, 5, 25, 5)


def test_clear_gaps_closes_the_run_a_span_reaches_into():
    """Close each lane gap that an obstacle span reaches into.

    Returns
    -------
    None
        Gap ``k`` lies between ``lane[k]`` and ``lane[k + 1]``.
    """
    lane = [0.0, 10.0, 20.0, 30.0, 40.0]
    # Close both middle gaps for a span that reaches into them.
    assert clear_gaps(lane, [(15.0, 25.0)]) == [True, False, False, True]
    # Leave a gap open when the span only touches its node.
    assert clear_gaps(lane, [(20.0, 30.0)]) == [True, True, False, True]
    assert clear_gaps(lane, [(0.0, 10.0)]) == [False, True, True, True]
    # Handle spans beyond the lane and spans covering all of it.
    assert clear_gaps(lane, [(50.0, 60.0)]) == [True] * 4
    assert clear_gaps(lane, [(-5.0, 45.0)]) == [False] * 4
    assert clear_gaps(lane, []) == [True] * 4
    # Report no gaps for a lane with fewer than two coordinates.
    assert clear_gaps([7.0], [(0.0, 10.0)]) == []
    assert clear_gaps([], [(0.0, 10.0)]) == []


def test_the_obstacle_index_sees_what_an_exhaustive_scan_sees():
    """Match the indexed graph to an exhaustive obstacle scan.

    Nodes, edges, and neighbour order must all agree, because the search
    breaks cost ties by neighbour order. Units are pinned with labels on all
    four sides so lanes fall on obstacle edges, where strict containment and
    segment contact differ.

    Returns
    -------
    None
        ``graph.nodes`` and ``graph.edges`` equal the scanned results.
    """
    fs = Flowsheet("obstacle index")
    feed = fs.add(Feed("Raw Feed")).pin(x=40, y=200)
    pump = fs.add(Pump("P-101", label_pos="bottom")).pin(x=180, y=180)
    hx = fs.add(HeatExchanger("E-101", width=120, height=60, label_pos="left")).pin(x=320, y=170)
    # Align the vessel with E-101's right edge (x=440) and label band (y=290).
    drum = fs.add(Vessel("V-101", width=90, height=140, label_pos="right")).pin(x=440, y=290)
    valve = fs.add(Valve("FV-101", label_pos="top")).pin(x=620, y=200)
    prod = fs.add(Product("To Unit 200")).pin(x=760, y=200)

    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, hx.tube_in)
    fs.connect(hx.tube_out, drum.inlet)
    fs.connect(drum.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fs.layout()

    graph = VisibilityGraph(fs, margin=15.0)
    assert len(graph.obstacles) >= 8 and len(graph.nodes) >= 500  # Require a non-trivial graph.

    scanned_nodes = {
        (x, y)
        for x in graph.xs
        for y in graph.ys
        if not any(o.contains(x, y) for o in graph.obstacles)
    }
    assert graph.nodes == scanned_nodes

    scanned_edges = {n: [] for n in scanned_nodes}
    for y in graph.ys:
        valid_x = [x for x in graph.xs if (x, y) in scanned_nodes]
        for i in range(len(valid_x) - 1):
            x1, x2 = valid_x[i], valid_x[i + 1]
            if not any(o.intersects_segment(x1, y, x2, y) for o in graph.obstacles):
                scanned_edges[(x1, y)].append((x2, y))
                scanned_edges[(x2, y)].append((x1, y))
    for x in graph.xs:
        valid_y = [y for y in graph.ys if (x, y) in scanned_nodes]
        for i in range(len(valid_y) - 1):
            y1, y2 = valid_y[i], valid_y[i + 1]
            if not any(o.intersects_segment(x, y1, x, y2) for o in graph.obstacles):
                scanned_edges[(x, y1)].append((x, y2))
                scanned_edges[(x, y2)].append((x, y1))
    assert graph.edges == scanned_edges


def test_outward_dir():
    """Name the box edge nearest a port coordinate.

    Returns
    -------
    None
        Each edge midpoint maps to its own face.
    """
    assert get_outward_dir(0, 50, 100, 100) == "W"
    assert get_outward_dir(100, 50, 100, 100) == "E"
    assert get_outward_dir(50, 0, 100, 100) == "N"
    assert get_outward_dir(50, 100, 100, 100) == "S"


def test_router_integration():
    """Route around a vessel that blocks both fallback corners.

    Returns
    -------
    None
        The route joins both nozzles, is orthogonal, turns, and clears
        every obstacle.
    """
    fs = Flowsheet("test")
    f = fs.add(Feed("F"))
    p = fs.add(Product("P"))
    # Block both L-shaped fallbacks so only a searched route can pass.
    wall = fs.add(Vessel("V-101", width=50, height=250))

    # Pin every unit to fix the geometry.
    f.pin(x=0, y=0)
    p.pin(x=200, y=200)
    wall.pin(x=100, y=0)

    s = fs.connect(f.outlet, p.inlet)
    fs.route()

    assert s.route is not None
    wp = s.route.waypoints
    # Check the endpoints, orthogonality, and that the route turns.
    graph = VisibilityGraph(fs, margin=15.0)
    assert wp[0] == pytest.approx(graph.port_anchors[("F", "outlet")])
    assert wp[-1] == pytest.approx(graph.port_anchors[("P", "inlet")])
    for (x1, y1), (x2, y2) in zip(wp, wp[1:]):
        assert abs(x1 - x2) < 0.5 or abs(y1 - y2) < 0.5, f"diagonal segment in {wp}"
    turns = {
        ("E" if x2 > x1 else "W") if abs(x1 - x2) >= 0.5 else ("S" if y2 > y1 else "N")
        for (x1, y1), (x2, y2) in zip(wp, wp[1:])
        if abs(x1 - x2) >= 0.5 or abs(y1 - y2) >= 0.5
    }
    assert len(turns) >= 2, f"expected an orthogonal step, got {wp}"

    # Check every segment, including both nozzle stubs, against every box.
    for a, b in zip(wp, wp[1:]):
        hit = [o for o in graph.obstacles if o.intersects_segment(a[0], a[1], b[0], b[1])]
        assert not hit, f"segment {a}->{b} of {wp} runs through {hit}"


def test_no_obstacle_intersection():
    """Route around a drum that blocks both fallback corners.

    Returns
    -------
    None
        No segment crosses an obstacle other than the end units' own
        boxes and labels on the two nozzle stubs.
    """
    from pandid.units import Separator, Compressor

    fs = Flowsheet("intersect_test")
    v = fs.add(Separator("V1"))
    c = fs.add(Compressor("C1"))
    drum = fs.add(Vessel("V-102", width=60, height=120))

    # Place the drum across the straight line between the two nozzles.
    v.pin(x=0, y=100)
    c.pin(x=200, y=100)
    drum.pin(x=90, y=40)

    s = fs.connect(v.vapor, c.suction)
    fs.route()

    graph = VisibilityGraph(fs)

    # Require a drawn route before checking it against obstacles.
    assert s.route is not None and s.route.waypoints, "V1 -> C1 was not routed"
    pts = s.route.waypoints
    assert pts[0] == pytest.approx(graph.port_anchors[("V1", "vapor")])
    assert pts[-1] == pytest.approx(graph.port_anchors[("C1", "suction")])

    # Exempt only the first and last segments from their own unit and label.
    stubs = {0, len(pts) - 2}
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(pts, pts[1:])):
        for obs in graph.obstacles:
            if i in stubs:
                own = v.frame if i == 0 else c.frame
                if obs.x_min == own.x and obs.y_min == own.y:
                    continue
                if obs.y_max == own.y:
                    continue

            assert not obs.intersects_segment(x1, y1, x2, y2), (
                f"Segment {pts[i]}->{pts[i + 1]} intersects obstacle {obs}"
            )


def test_the_fallback_l_is_checked_against_the_obstacles():
    """Choose the fallback corner that crosses fewer obstacles.

    Returns
    -------
    None
        A clear corner wins, and across-first wins when both are equal.
    """
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (100.0, 100.0), (100.0, 125.0)
    across = [start, start_proj, (100.0, 0.0), goal_proj, goal]
    down = [start, start_proj, (25.0, 100.0), goal_proj, goal]

    # Take the across-first order when nothing is in the way.
    assert _fallback_path(start, start_proj, goal_proj, goal, []) == across

    # Take the other order when a box sits on the across-first leg.
    on_across = Rect(40.0, 60.0, -10.0, 10.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_across]) == down

    # Draw the across-first order when both legs are blocked.
    on_down = Rect(40.0, 60.0, 90.0, 110.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_across, on_down]) == across


def test_the_fallback_l_also_breaks_an_obstacle_tie_on_a_drawn_crossing():
    """Break an obstacle tie by the number of recorded lines crossed.

    Returns
    -------
    None
        The corner avoiding a recorded line wins unless an obstacle blocks it.
    """
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (100.0, 100.0), (100.0, 125.0)
    across = [start, start_proj, (100.0, 0.0), goal_proj, goal]
    down = [start, start_proj, (25.0, 100.0), goal_proj, goal]

    # Take the across-first order without a crossing index.
    assert _fallback_path(start, start_proj, goal_proj, goal, []) == across

    # Record a vertical line at x=50 that only the across-first leg crosses.
    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]
    assert _fallback_path(start, start_proj, goal_proj, goal, [], index) == down

    # Rank an obstacle on the down leg above the recorded crossing.
    on_down = Rect(10.0, 40.0, 90.0, 110.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_down], index) == across


def test_the_fallback_drops_a_corner_that_repeats_the_projection():
    """Omit a corner that coincides with an escape node (#282).

    Returns
    -------
    None
        Two projections in one column give a path without repeated points.
    """
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (25.0, 100.0), (25.0, 125.0)
    path = _fallback_path(start, start_proj, goal_proj, goal, [])
    assert path == [start, start_proj, goal_proj, goal]
    assert len(set(path)) == len(path)


def _straight_run(bad=None):
    """Build a feed, heat exchanger, and product in one row.

    Parameters
    ----------
    bad : float or None, optional
        Replacement x coordinate for the heat exchanger.

    Returns
    -------
    Flowsheet
        Sheet with all three units pinned.
    """
    fs = Flowsheet("Non-finite")
    feed = fs.add(Feed("Raw Feed")).pin(x=0, y=100)
    hx = fs.add(HeatExchanger("E-101"))
    prod = fs.add(Product("To Unit 200")).pin(x=400, y=100)
    fs.connect(feed.outlet, hx.shell_in)
    fs.connect(hx.shell_out, prod.inlet)
    hx.pin(x=200.0 if bad is None else bad, y=100.0)
    return fs


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_placement_is_refused_rather_than_routed_for_ever(bad):
    """Reject a non-finite coordinate before the path search starts.

    Parameters
    ----------
    bad : float
        Non-finite x coordinate given to the heat exchanger.

    Returns
    -------
    None
        ``route()`` raises and names the unit.
    """
    with pytest.raises(ValueError, match="E-101 has a non-finite x="):
        _straight_run(bad).route()


def test_the_search_is_bounded_by_the_size_of_the_graph():
    """Stop a search that exceeds its expansion budget.

    Returns
    -------
    None
        A zero budget raises, and the default budget routes the same sheet.
    """
    fs = _straight_run()
    fs.layout()
    original = (astar.MAX_EXPANSIONS_PER_NODE, astar.MIN_EXPANSION_BUDGET)
    astar.MAX_EXPANSIONS_PER_NODE, astar.MIN_EXPANSION_BUDGET = 0, 0
    try:
        with pytest.raises(RuntimeError, match="not converging"):
            fs.route()
    finally:
        astar.MAX_EXPANSIONS_PER_NODE, astar.MIN_EXPANSION_BUDGET = original

    # Route the same sheet with the default budget.
    fs = _straight_run()
    fs.route()
    assert all(s.route and s.route.waypoints for s in fs.streams)


def test_find_path_names_the_endpoint_it_cannot_search_from():
    """Reject a non-finite start or goal by name.

    Returns
    -------
    None
        Each endpoint raises its own ``ValueError``.
    """
    fs = _straight_run()
    fs.layout()
    graph = VisibilityGraph(fs, margin=15.0)
    node = next(iter(graph.nodes))
    with pytest.raises(ValueError, match="non-finite start"):
        find_path(graph, (float("nan"), 0.0), node)
    with pytest.raises(ValueError, match="non-finite goal"):
        find_path(graph, node, (0.0, float("inf")))


# ---------------------------------------------------------------------------
# Pricing drawn crossings (#425).
# ---------------------------------------------------------------------------


def test_committed_segments_merges_a_straight_run_into_one_span():
    """Merge collinear waypoints into one segment.

    Returns
    -------
    None
        Three points on one row give a single horizontal span.
    """
    path = [(602.0, 450.0), (615.0, 450.0), (640.0, 450.0)]
    assert committed_segments(path) == [("h", 450.0, 602.0, 640.0)]


def test_committed_segments_merges_across_a_repeated_point_on_the_same_axis():
    """Merge two same-axis segments that meet at a repeated waypoint.

    Returns
    -------
    None
        The repeated point is interior to a single span.
    """
    path = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert committed_segments(path) == [("h", 0.0, 0.0, 20.0)]


def test_crossing_index_is_strict_interior_only():
    """Count a crossing only strictly inside a recorded span.

    Returns
    -------
    None
        Endpoints, other lanes, and the wrong axis do not count.
    """
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])  # Record y=0 for x in [0, 100].

    # Count a vertical run through the span's interior.
    assert index.crosses((50.0, 0.0), "v")
    # Treat a span endpoint as a tee, not a crossing.
    assert not index.crosses((100.0, 0.0), "v")
    assert not index.crosses((0.0, 0.0), "v")
    # Ignore a point off the recorded lane.
    assert not index.crosses((50.0, 5.0), "v")
    # Ignore the other axis, which reads vertical spans.
    assert not index.crosses((50.0, 0.0), "h")


def test_crossing_index_crosses_counts_rather_than_answers_yes_or_no():
    """Return the number of recorded spans crossed at a point.

    Returns
    -------
    None
        Two streams on one line count as two crossings; none counts as zero.
    """
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    assert index.crosses((50.0, 0.0), "v") == 1

    index.record([(0.0, 0.0), (100.0, 0.0)])  # Record a second stream on the line.
    assert index.crosses((50.0, 0.0), "v") == 2

    # Return a falsy zero when nothing is crossed.
    assert not index.crosses((50.0, 5.0), "v")


def test_a_route_that_crosses_two_streams_costs_twice():
    """Charge one crossing penalty per stream crossed.

    Returns
    -------
    None
        The route cost rises by one penalty, then two.
    """
    nodes = {(0.0, 0.0), (40.0, 0.0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0.0, 0.0)].append((40.0, 0.0))
    edges[(40.0, 0.0)].append((0.0, 0.0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    clear = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W")

    one = CrossingIndex()
    one.v[40.0] = [(-10.0, 10.0)]
    crossing_one = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W", crossing_index=one)

    two = CrossingIndex()
    two.v[40.0] = [(-10.0, 10.0), (-10.0, 10.0)]  # Add a second stream on the span.
    crossing_two = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W", crossing_index=two)

    assert crossing_one == pytest.approx(clear + astar.CROSSING_PENALTY)
    assert crossing_two == pytest.approx(clear + 2 * astar.CROSSING_PENALTY)


def test_crossing_index_protects_a_stubs_whole_span_not_just_its_ends():
    """Count a crossing anywhere inside a span recorded from two points.

    Returns
    -------
    None
        A lane inside the span crosses although it is not a recorded point.
    """
    index = CrossingIndex()
    index.record([(602.0, 450.0), (640.0, 450.0)])
    assert index.crosses((617.0, 450.0), "v")


def _tie_graph() -> VisibilityGraph:
    """Build two routes from (0, 0) to (40, 0) tied on bends and length.

    One route runs north through (20, 10) and one south through (20, -10).
    No direct edge exists. The graph is built by hand so the tie is exact.

    Returns
    -------
    VisibilityGraph
        Stand-in carrying the ``nodes``, ``edges``, and ``recycle_y`` that
        ``find_path`` reads.
    """
    nodes = {(0, 0), (40, 0), (0, 10), (20, 10), (40, 10), (0, -10), (20, -10), (40, -10)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
        """Join two nodes in both directions.

        Parameters
        ----------
        a, b : tuple[float, float]
            Graph nodes.
        """
        edges[a].append(b)
        edges[b].append(a)

    link((0, 0), (0, 10))
    link((0, 10), (20, 10))
    link((20, 10), (40, 10))
    link((40, 10), (40, 0))
    link((0, 0), (0, -10))
    link((0, -10), (20, -10))
    link((20, -10), (40, -10))
    link((40, -10), (40, 0))
    return cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))


def test_a_bend_and_length_tie_breaks_towards_the_route_that_does_not_cross():
    """Prefer the tied route that crosses no recorded line.

    Returns
    -------
    None
        The search avoids whichever side carries the recorded span.
    """
    graph = _tie_graph()

    # Record a vertical run that only the north route crosses.
    crosses_north = CrossingIndex()
    crosses_north.v[20] = [(0.0, 20.0)]
    south = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=crosses_north)
    assert (20, 10) not in south, f"took the crossing route: {south}"
    assert (20, -10) in south, f"did not take the free alternative: {south}"

    # Record the mirrored run to confirm the graph favours neither side.
    crosses_south = CrossingIndex()
    crosses_south.v[20] = [(-20.0, 0.0)]
    north = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=crosses_south)
    assert (20, -10) not in north, f"took the crossing route: {north}"
    assert (20, 10) in north, f"did not take the free alternative: {north}"


def test_a_crossing_is_kept_rather_than_bought_off_with_two_more_bends():
    """Accept a crossing rather than add two bends to avoid it.

    The north route has 3 bends and one crossing. The south route is clear
    but has 5 bends. ``CROSSING_PENALTY`` is far below ``BEND_PENALTY``.

    Returns
    -------
    None
        The search takes the north route.
    """
    nodes = {
        (0, 0),
        (40, 0),
        (0, 10),
        (20, 10),
        (40, 10),
        (0, -10),
        (20, -10),
        (20, -30),
        (40, -30),
    }
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
        """Join two nodes in both directions.

        Parameters
        ----------
        a, b : tuple[float, float]
            Graph nodes.
        """
        edges[a].append(b)
        edges[b].append(a)

    link((0, 0), (0, 10))
    link((0, 10), (20, 10))
    link((20, 10), (40, 10))
    link((40, 10), (40, 0))
    link((0, 0), (0, -10))
    link((0, -10), (20, -10))
    link((20, -10), (20, -30))
    link((20, -30), (40, -30))
    link((40, -30), (40, 0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    index = CrossingIndex()
    index.v[20] = [(0.0, 20.0)]  # Cross the north route at (20, 10).
    routed = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=index)
    assert (20, 10) in routed, f"detoured two extra bends to dodge a crossing: {routed}"


def test_a_forced_crossing_still_routes():
    """Find the only route although it crosses a recorded line.

    Returns
    -------
    None
        The crossing charge never removes the single available route.
    """
    nodes = {(0, 0), (40, 0), (0, 10), (20, 10), (40, 10)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
        """Join two nodes in both directions.

        Parameters
        ----------
        a, b : tuple[float, float]
            Graph nodes.
        """
        edges[a].append(b)
        edges[b].append(a)

    link((0, 0), (0, 10))
    link((0, 10), (20, 10))
    link((20, 10), (40, 10))
    link((40, 10), (40, 0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    index = CrossingIndex()
    index.v[20] = [(0.0, 20.0)]
    routed = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=index)
    assert routed == [(0, 0), (0, 10), (20, 10), (40, 10), (40, 0)]


def _final_g(graph, start, goal, start_dir, goal_dir, crossing_index=None):
    """Return the cost of the state ``find_path`` stops on.

    A graph with one route returns the same path whether or not a crossing
    is charged, so the charge is read from the cost of the last popped
    state.

    Parameters
    ----------
    graph : VisibilityGraph
        Search graph.
    start, goal : tuple[float, float]
        Search endpoints.
    start_dir, goal_dir : str or None
        Required endpoint directions.
    crossing_index : CrossingIndex or None, optional
        Routes already drawn.

    Returns
    -------
    float
        Accumulated cost of the returned route.
    """
    original = heapq.heappop
    popped: list = []

    def logging_pop(heap):
        """Pop one search state and keep a copy.

        Parameters
        ----------
        heap : list
            Search priority queue.

        Returns
        -------
        object
            Item removed by the original heap operation.
        """
        item = original(heap)
        popped.append(item)
        return item

    heapq.heappop = logging_pop
    try:
        result = find_path(graph, start, goal, start_dir, goal_dir, crossing_index=crossing_index)
    finally:
        heapq.heappop = original
    assert result, f"no route found in a graph built to have exactly one: {popped}"
    return popped[-1][1]


def test_a_terminal_crossing_at_the_goal_itself_is_priced():
    """Charge a crossing that lies on the goal node.

    The search returns on reaching the goal without expanding it. An
    arrival that continues into the fixed goal stub makes the goal an
    interior point of the drawn line.

    Returns
    -------
    None
        The one-route graph costs one penalty more with the crossing.
    """
    nodes = {(0.0, 0.0), (40.0, 0.0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0.0, 0.0)].append((40.0, 0.0))
    edges[(40.0, 0.0)].append((0.0, 0.0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    g_clear = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W")

    index = CrossingIndex()
    index.v[40.0] = [(-10.0, 10.0)]  # Place the goal strictly inside the span.
    g_crossed = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W", crossing_index=index)

    assert g_crossed == pytest.approx(g_clear + astar.CROSSING_PENALTY)


def test_a_crossing_at_the_terminal_is_never_worth_a_bend():
    """Price the bend a side arrival makes with the goal stub.

    Two routes reach the goal with equal length and counted bends. One
    arrives in line with the stub and crosses a recorded line; the other
    arrives from the side, which adds a bend at the stub.

    Returns
    -------
    None
        The in-line arrival wins, and without the index both remain tied.
    """
    nodes = {(0.0, -20.0), (0.0, 0.0), (20.0, 0.0), (20.0, -20.0)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
        """Join two nodes in both directions.

        Parameters
        ----------
        a, b : tuple[float, float]
            Graph nodes.
        """
        edges[a].append(b)
        edges[b].append(a)

    link((0.0, -20.0), (0.0, 0.0))
    link((0.0, 0.0), (20.0, 0.0))  # Arrive heading east, in line with the stub.
    link((0.0, -20.0), (20.0, -20.0))
    link((20.0, -20.0), (20.0, 0.0))  # Arrive heading north, from the side.
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    index = CrossingIndex()
    index.v[20.0] = [(-30.0, 30.0)]  # Place the goal strictly inside the span.

    routed = find_path(graph, (0.0, -20.0), (20.0, 0.0), None, "W", crossing_index=index)
    assert (0.0, 0.0) in routed, f"bought a bend to dodge a 10px crossing: {routed}"
    assert (20.0, -20.0) not in routed, f"bought a bend to dodge a 10px crossing: {routed}"

    # Confirm the graph is unbiased: either route may win without the index.
    tied = find_path(graph, (0.0, -20.0), (20.0, 0.0), None, "W")
    assert tied in (
        [(0.0, -20.0), (0.0, 0.0), (20.0, 0.0)],
        [(0.0, -20.0), (20.0, -20.0), (20.0, 0.0)],
    )


def test_a_forced_terminal_crossing_still_routes():
    """Find the only route although its goal lies on a recorded line.

    Returns
    -------
    None
        The direct route is returned.
    """
    nodes = {(0, 0), (40, 0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0, 0)].append((40, 0))
    edges[(40, 0)].append((0, 0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    index = CrossingIndex()
    index.v[40] = [(-10.0, 10.0)]
    routed = find_path(graph, (0, 0), (40, 0), None, "W", crossing_index=index)
    assert routed == [(0, 0), (40, 0)]


def test_committed_segments_refuses_a_diagonal_pair():
    """Reject a diagonal segment instead of guessing its axis.

    Returns
    -------
    None
        ``committed_segments`` raises ``ValueError``.
    """
    with pytest.raises(ValueError, match="diagonal"):
        committed_segments([(0.0, 0.0), (10.0, 10.0)])


def test_crossing_index_crosses_refuses_an_invalid_axis():
    """Reject an axis other than ``"h"`` or ``"v"``.

    Returns
    -------
    None
        ``crosses`` raises ``ValueError``.
    """
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    with pytest.raises(ValueError, match="axis"):
        index.crosses((50.0, 0.0), "garbage")  # type: ignore[arg-type]


def _obstacle_bypass_tie(fs):
    """Add a stream whose north and south bypasses are exactly tied.

    ``label_pos="center"`` keeps the vessel symmetric; a label above it
    would make the north bypass longer.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that receives the feed, product, and central vessel.

    Returns
    -------
    Stream
        The F -> P stream, connected last.
    """
    f = fs.add(Feed("F")).pin(x=0, y=200)
    p = fs.add(Product("P")).pin(x=400, y=200)
    fs.add(Vessel("V-101", width=100, height=100, label_pos="center")).pin(x=150, y=150)
    return fs.connect(f.outlet, p.inlet)


def test_a_manual_routes_geometry_is_recorded_for_later_streams():
    """Record a manual route so a later stream avoids crossing it.

    The manual stream is drawn across the north bypass at x=175, a lane the
    graph carries. The test checks the later route, because a call to
    ``record`` does not prove that it had an effect.

    Returns
    -------
    None
        F -> P takes the south bypass.
    """
    fs = Flowsheet("manual-recorded")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    fs.connect(f1.outlet, p1.inlet).via([(175.0, 100.0), (175.0, 170.0)])
    stream = _obstacle_bypass_tie(fs)

    fs.layout()
    fs.route()

    assert stream.route is not None
    wp = stream.route.waypoints
    assert 135.0 not in {y for _, y in wp}, f"F -> P crossed the manual route's line: {wp}"
    assert 265.0 in {y for _, y in wp}, f"F -> P did not take the clear (south) bypass: {wp}"


def test_a_diagonal_manual_route_is_recorded_around_its_own_slant():
    """Record the orthogonal legs of a manual route that has a diagonal leg.

    The manual route crosses the north bypass with an orthogonal leg and
    then runs diagonally away from it.

    Returns
    -------
    None
        ``route-diagonal`` is reported and F -> P takes the south bypass.
    """
    fs = Flowsheet("diagonal-manual")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    fs.connect(f1.outlet, p1.inlet).via([(175.0, 100.0), (175.0, 170.0), (225.0, 220.0)])
    stream = _obstacle_bypass_tie(fs)

    fs.layout()
    fs.route()

    issues = fs.validate()
    assert any(i.code == "route-diagonal" for i in issues), (
        "the diagonal leg should still be reported by validate()"
    )

    assert stream.route is not None
    wp = stream.route.waypoints
    assert 135.0 not in {y for _, y in wp}, (
        f"F -> P crossed the manual route's orthogonal leg: {wp}"
    )
    assert 265.0 in {y for _, y in wp}, f"F -> P did not take the clear (south) bypass: {wp}"


def test_a_fallback_routes_geometry_is_recorded_for_later_streams():
    """Record a fallback route so a later stream avoids crossing it.

    F1 -> P1 is forced onto the fallback across the north bypass. The
    fixture units near the bypass shift the tie by about 10 px, so
    ``CROSSING_PENALTY`` is raised for this test.

    Returns
    -------
    None
        F1 -> P1 draws a fallback and F -> P takes the south bypass.
    """
    fs = Flowsheet("fallback-recorded")
    f1 = fs.add(Feed("F1")).pin(x=175, y=100)
    p1 = fs.add(Product("P1")).pin(x=175, y=170)
    fs.connect(f1.outlet, p1.inlet)
    stream = _obstacle_bypass_tie(fs)

    original_find_path = astar.find_path
    original_penalty = astar.CROSSING_PENALTY

    def forced_empty_for_first(graph, start, *args, **kwargs):
        """Return no path for a search that starts on F1's outlet row.

        Parameters
        ----------
        graph : VisibilityGraph
            Graph whose port anchors identify the first stream.
        start : tuple[float, float]
            Search start node.
        *args, **kwargs
            Remaining ``find_path`` arguments.

        Returns
        -------
        list[tuple[float, float]]
            An empty path for F1 -> P1, otherwise the real search result.
        """
        if start[1] == graph.port_anchors[("F1", "outlet")][1]:
            return []
        return original_find_path(graph, start, *args, **kwargs)

    astar.find_path = forced_empty_for_first
    astar.CROSSING_PENALTY = 100.0
    try:
        fs.layout()
        fs.route()
    finally:
        astar.find_path = original_find_path
        astar.CROSSING_PENALTY = original_penalty

    fallback_route = fs.streams[0].route
    assert fallback_route is not None and len(fallback_route.waypoints) > 2, (
        f"F1 -> P1 was not actually forced into the fallback path: {fallback_route}"
    )
    assert stream.route is not None
    wp = stream.route.waypoints
    assert 140.0 not in {y for _, y in wp}, f"F -> P crossed the fallback route's line: {wp}"
    assert 265.0 in {y for _, y in wp}, f"F -> P did not take the clear (south) bypass: {wp}"


def test_crossings_along_counts_a_crossing_strictly_inside_the_span_open_on_both_ends():
    """Count recorded spans crossed strictly inside one edge.

    Returns
    -------
    None
        Interior spans count once each; a span at the edge's endpoint, a
        diagonal, and a zero-length edge count as zero.
    """
    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]
    index.v[100.0] = [(-10.0, 10.0)]  # Lie on the edge's endpoint, not inside it.
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 1
    index.v[50.0].append((-10.0, 10.0))  # Add a second stream on the span.
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 2
    # Count nothing for a diagonal or a zero-length edge.
    assert index.crossings_along((0.0, 0.0), (10.0, 10.0)) == 0
    assert index.crossings_along((5.0, 5.0), (5.0, 5.0)) == 0


def test_crossings_along_sees_a_track_added_after_its_own_sorted_cache_was_built():
    """Refresh the sorted track cache when a new track is recorded.

    Returns
    -------
    None
        A track recorded after the first query is counted by the second.
    """
    index = CrossingIndex()
    index.v[10.0] = [(-10.0, 10.0)]
    assert index.crossings_along((0.0, 0.0), (20.0, 0.0)) == 1  # Build the cache.

    index.record([(50.0, -10.0), (50.0, 10.0)])  # Add a track after the build.
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 2


def test_find_path_prices_a_crossing_strictly_inside_a_long_edge_not_just_at_a_node():
    """Charge a crossing that lies inside an edge and on no graph node.

    Returns
    -------
    None
        The one-route graph costs one penalty more with the crossing.
    """
    nodes = {(0.0, 0.0), (100.0, 0.0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0.0, 0.0)].append((100.0, 0.0))
    edges[(100.0, 0.0)].append((0.0, 0.0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    clear = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W")

    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]  # Use x=50, which is not a graph node.
    crossed = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W", crossing_index=index)

    assert crossed == pytest.approx(clear + astar.CROSSING_PENALTY)


def test_a_manual_route_off_lane_still_breaks_the_tie():
    """Avoid a manual route drawn off every graph lane.

    The manual stream runs at x=176, which is not a lane coordinate, so
    only the whole-edge crossing check can price it.

    Returns
    -------
    None
        F -> P takes the south bypass.
    """
    fs = Flowsheet("manual-recorded-off-lane")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    fs.connect(f1.outlet, p1.inlet).via([(176.0, 100.0), (176.0, 170.0)])
    stream = _obstacle_bypass_tie(fs)

    fs.layout()
    fs.route()

    assert stream.route is not None
    wp = stream.route.waypoints
    assert 135.0 not in {y for _, y in wp}, f"F -> P crossed the manual route's line: {wp}"
    assert 265.0 in {y for _, y in wp}, f"F -> P did not take the clear (south) bypass: {wp}"


def test_preview_separated_waypoints_does_not_mutate_and_matches_the_real_pass():
    """Preview separation without changing routes, and match the real pass.

    Returns
    -------
    None
        Routes are unchanged by the preview, equal it after separation,
        and separation moves at least one of them.
    """
    from pandid.routing.separation import preview_separated_waypoints, separate_streams

    fs = Flowsheet("preview-vs-real")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    s1 = fs.connect(f1.outlet, p1.inlet).via(
        [(0.0, 50.0), (0.0, 100.0), (300.0, 100.0), (300.0, 150.0)]
    )
    f2 = fs.add(Feed("F2")).pin(x=2000, y=1000)
    p2 = fs.add(Product("P2")).pin(x=2000, y=1000)
    s2 = fs.connect(f2.outlet, p2.inlet).via(
        [(100.0, 50.0), (100.0, 100.0), (400.0, 100.0), (400.0, 150.0)]
    )
    assert s1.route is not None and s2.route is not None  # ``via()`` sets both routes.

    raw_s1, raw_s2 = list(s1.route.waypoints), list(s2.route.waypoints)
    preview = preview_separated_waypoints(fs.streams)

    # Leave the stored waypoints unchanged.
    assert s1.route.waypoints == raw_s1
    assert s2.route.waypoints == raw_s2

    separate_streams(fs)

    # Match the waypoints the real pass writes.
    assert preview[id(s1)] == s1.route.waypoints
    assert preview[id(s2)] == s2.route.waypoints
    # Confirm that the overlapping runs at y=100 were separated.
    assert s1.route.waypoints != raw_s1 or s2.route.waypoints != raw_s2


def test_a_later_streams_recording_uses_separated_not_raw_geometry():
    """Record the separated route so later streams price its drawn path.

    Returns
    -------
    None
        The second manual route is recorded at its separated y coordinate.
    """
    recorded: list[list[tuple[float, float]]] = []
    original_record = CrossingIndex.record

    def spy(self, path):
        """Record one path and keep a copy of it.

        Parameters
        ----------
        self : CrossingIndex
            Index receiving the path.
        path : list[tuple[float, float]]
            Route waypoints.

        Returns
        -------
        None
            Result of the original ``record``.
        """
        recorded.append(list(path))
        return original_record(self, path)

    fs = Flowsheet("preview-separation-recorded")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    fs.connect(f1.outlet, p1.inlet).via([(0.0, 50.0), (0.0, 100.0), (300.0, 100.0), (300.0, 150.0)])
    f2 = fs.add(Feed("F2")).pin(x=2000, y=1000)
    p2 = fs.add(Product("P2")).pin(x=2000, y=1000)
    s2 = fs.connect(f2.outlet, p2.inlet).via(
        [(100.0, 50.0), (100.0, 100.0), (400.0, 100.0), (400.0, 150.0)]
    )

    fs.layout()
    CrossingIndex.record = spy
    try:
        # Keep layout-search trials out of the router's recording spy.
        fs.route(router=DefaultRouter())
    finally:
        CrossingIndex.record = original_record

    assert s2.route is not None
    assert s2.route.waypoints[1][1] == 106.0, (
        f"expected separate_streams to move s2's shared run to y=106: {s2.route.waypoints}"
    )
    s2_recordings = [p for p in recorded if p and p[0][0] == 100.0]
    assert s2_recordings, f"s2's geometry was never recorded: {recorded}"
    assert s2_recordings[-1][1][1] == 106.0, (
        f"s2 was recorded at its raw, pre-separation position rather than "
        f"the one actually drawn: {s2_recordings[-1]}"
    )
