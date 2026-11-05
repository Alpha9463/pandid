"""Check obstacle geometry, path search, crossing pricing, and the default router."""

import heapq
import re
import warnings
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

from pandid import ControlValve, ShellAndTubeExchanger
from pandid.flowsheet import Flowsheet
from pandid.geometry import Route
from pandid.streams import Stream
from pandid.units import Feed, Fitting, HeatExchanger, Product, Pump, Valve, Vessel
from pandid.portgeom import outward_dir
from pandid.routing import DefaultRouter, _fallback_path
from pandid.routing import astar
from pandid.routing.astar import CrossingIndex, committed_segments, find_path
from pandid.routing.visibility import TAG_CLEAR, Rect, VisibilityGraph, clear_gaps


#: Blocker width, height, label side and corner; whether the router recovers
#: exits; whether the blocker hides the feed's nominal projection from the
#: graph; and whether the line is drawn as a fallback through the blocker.
_BLOCKED_NOZZLES = {
    "reachable-lane": ((44, 44, "bottom"), (83, 78), True, True, False),
    "no-recovery": ((44, 44, "bottom"), (83, 78), False, True, True),
    "sealed-nozzle": ((44, 44, "bottom"), (60, 78), True, True, True),
    "blocked-stub": ((12, 40, "center"), (68, 80), True, False, True),
}


@pytest.mark.parametrize("case", list(_BLOCKED_NOZZLES))
def test_a_blocked_nozzle_escapes_by_a_reachable_lane_or_reports_its_fallback(case: str) -> None:
    """Check that a blocked nozzle stub routes clear or draws a reported fallback."""
    (width, height, side), corner, recover, hidden, blocked = _BLOCKED_NOZZLES[case]
    fs = Flowsheet(case)
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=400, y=100)
    blocker = fs.add(Pump("Blocker", width=width, height=height, label_pos=side))
    blocker.pin(x=corner[0], y=corner[1])
    stream = fs.connect(feed.outlet, product.inlet)
    fs.layout()
    graph = VisibilityGraph(fs)
    assert (graph.port_projs[("F", "outlet")] not in graph.nodes) is hidden

    with pytest.warns(DeprecationWarning, match="recover_exits"):
        router = DefaultRouter(recover_exits=recover)
    fs.route(router)

    assert stream.route is not None and stream.route.used_fallback is blocked
    assert feed.frame is not None and product.frame is not None and blocker.frame is not None
    assert [(f.x, f.y) for f in (feed.frame, product.frame, blocker.frame)] == [
        (10.0, 75.0),
        (400.0, 75.0),
        corner,
    ]
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate()) is blocked


def test_passing_recover_exits_is_deprecated(same_file: Callable[[str], str]) -> None:
    """Check that ``recover_exits=`` warns at the caller's line and is still kept."""
    with pytest.warns(DeprecationWarning, match="recover_exits") as caught:
        router = DefaultRouter(recover_exits=False)
    assert [same_file(w.filename) for w in caught] == [same_file(__file__)]
    assert router.recover_exits is False
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert DefaultRouter().recover_exits is True


def test_the_router_protocol_is_deprecated(same_file: Callable[[str], str]) -> None:
    """Check that ``routing.Router`` warns at the caller's line and still gives the protocol."""
    import pandid.routing as routing

    with pytest.warns(DeprecationWarning, match=r"pandid\.routing\.Router") as imported:
        from pandid.routing import Router
    with pytest.warns(DeprecationWarning, match=r"pandid\.routing\.Router") as read:
        assert routing.Router is Router
    assert len(read) == 1
    assert {same_file(w.filename) for w in [*imported, *read]} == {same_file(__file__)}
    assert "route" in vars(Router)
    with pytest.raises(AttributeError, match="no attribute 'Rooter'"):
        getattr(routing, "Rooter")


def test_rect_intersection():
    """Count segment contact with the rectangle's edge."""
    r = Rect(10, 20, 10, 20)
    # Intersect a segment that passes through.
    assert r.intersects_segment(5, 15, 25, 15)
    # Intersect a segment that lies on the edge.
    assert r.intersects_segment(10, 5, 10, 25)
    # Miss a segment that lies outside.
    assert not r.intersects_segment(5, 5, 25, 5)


@pytest.mark.parametrize("valve_at", [(440, 170), (446, 150)])
def test_a_lane_beside_a_tag_or_its_own_unit_stays_a_way_through(valve_at):
    """Route a cooler's outlet up the narrow lane between it and its valve."""
    fs = Flowsheet("product cooler")
    cooler = fs.add(ShellAndTubeExchanger("E-101")).pin(x=360, y=180)
    valve = fs.add(ControlValve("TV-101")).pin(x=valve_at[0], y=valve_at[1])
    feed, product = fs.add(Feed("Feed")), fs.add(Product("Product"))
    cws, cwr = fs.add(Feed("CWS")), fs.add(Product("CWR"))
    fs.connect(feed.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.connect(cws.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr.inlet)
    fs.add_control_loop("T", 101, measuring=cooler, acting_on=valve)
    fs.to_svg(diagram="p&id")
    assert fs.validate(diagram="p&id") == []


def test_a_lane_a_pixel_off_a_unit_carries_no_route_along_it():
    """Route round a vessel rather than along a lane a pixel under it."""
    fs = Flowsheet("lane beside an edge")
    feed = fs.add(Feed("F")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("P")).pin(port="inlet", x=700, y=100)
    fs.add(Vessel("V-1", width=60, height=100)).pin(x=380, y=50)
    # V-2's lower lane runs one pixel under V-1.
    fs.add(Vessel("V-2", width=60, height=86)).pin(x=1000, y=50)
    line = fs.connect(feed.outlet, product.inlet)
    fs.route()
    assert line.route is not None
    # V-1's bottom edge is at y=150.
    assert all(abs(y - 150.0) >= 2.0 for _, y in line.route.waypoints), line.route.waypoints
    assert "route-along-unit" not in {issue.code for issue in fs.validate()}


def test_clear_gaps_closes_the_run_a_span_reaches_into():
    """Close each lane gap that an obstacle span reaches into."""
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
    """Match the indexed graph to an exhaustive obstacle scan."""
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

    graph = VisibilityGraph(fs)
    assert len(graph.obstacles) >= 8 and len(graph.nodes) >= 500  # Require a non-trivial graph.

    scanned_nodes = {
        (x, y)
        for x in graph.xs
        for y in graph.ys
        if not any(o.x_min < x < o.x_max and o.y_min < y < o.y_max for o in graph.obstacles)
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
    """Name the box edge nearest a port coordinate."""
    assert outward_dir(0, 50, 100, 100) == "W"
    assert outward_dir(100, 50, 100, 100) == "E"
    assert outward_dir(50, 0, 100, 100) == "N"
    assert outward_dir(50, 100, 100, 100) == "S"


def test_router_integration():
    """Route around a vessel that blocks both fallback corners."""
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
    graph = VisibilityGraph(fs)
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
    """Route around a drum that blocks both fallback corners."""
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
    """Choose the fallback corner that crosses fewer obstacles."""
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
    """Break an obstacle tie by the number of recorded lines crossed."""
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
    """Omit a corner that coincides with an escape node."""
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (25.0, 100.0), (25.0, 125.0)
    path = _fallback_path(start, start_proj, goal_proj, goal, [])
    assert path == [start, start_proj, goal_proj, goal]
    assert len(set(path)) == len(path)


def _straight_run(bad=None):
    """Build a feed, heat exchanger, and product in one row."""
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
    """Reject a non-finite coordinate before the path search starts."""
    with pytest.raises(ValueError, match="E-101: pin x must be a finite number"):
        _straight_run(bad)
    fs = _straight_run()
    fs.layout()
    frame = fs.units[1].frame
    assert frame is not None
    frame.x = bad
    with pytest.raises(ValueError, match="E-101 has a non-finite x="):
        fs.route()


def test_the_router_keeps_lines_off_the_tag_the_renderer_draws():
    """Block the halo drawn behind a tag and a pen beside it, and nothing for no tag."""
    fs = Flowsheet("tag-obstacle")
    name = "V-101-FEED-SURGE-DRUM-FIRST-STAGE"
    fs.add(Vessel(name, label_pos="top")).pin(x=300, y=200)
    element = fs.add(Fitting("FE-303", variant="venturi")).pin(x=100, y=400)
    fs.add_balloon(element, face="S", offset=46)
    fs.layout()
    graph = VisibilityGraph(fs)
    bodies = {id(rect) for _, rect in graph.body_obstacles}
    labels = [rect for rect in graph.obstacles if id(rect) not in bodies]
    svg = fs.to_svg(check=False)
    halo = re.search(rf'<rect [^>]*width="([\d.]+)"[^>]*/>\s*<text [^>]*>{name}</text>', svg)
    assert halo is not None
    assert [round(rect.x_max - rect.x_min, 1) for rect in labels] == [
        round(float(halo.group(1)) + 2 * TAG_CLEAR, 1)
    ]


def test_the_search_is_bounded_by_the_size_of_the_graph():
    """Stop a search that exceeds its expansion budget."""
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
    """Reject a non-finite start or goal by name."""
    fs = _straight_run()
    fs.layout()
    graph = VisibilityGraph(fs)
    node = next(iter(graph.nodes))
    with pytest.raises(ValueError, match="non-finite start"):
        find_path(graph, (float("nan"), 0.0), node)
    with pytest.raises(ValueError, match="non-finite goal"):
        find_path(graph, node, (0.0, float("inf")))


# Pricing drawn crossings.


def test_committed_segments_merges_a_straight_run_into_one_span():
    """Merge collinear waypoints into one segment."""
    path = [(602.0, 450.0), (615.0, 450.0), (640.0, 450.0)]
    assert committed_segments(path) == [("h", 450.0, 602.0, 640.0)]


def test_committed_segments_merges_across_a_repeated_point_on_the_same_axis():
    """Merge two same-axis segments that meet at a repeated waypoint."""
    path = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert committed_segments(path) == [("h", 0.0, 0.0, 20.0)]


def test_crossing_index_is_strict_interior_only():
    """Count a crossing only strictly inside a recorded span."""
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
    """Return the number of recorded spans crossed at a point."""
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    assert index.crosses((50.0, 0.0), "v") == 1

    index.record([(0.0, 0.0), (100.0, 0.0)])  # Record a second stream on the line.
    assert index.crosses((50.0, 0.0), "v") == 2

    # Return a falsy zero when nothing is crossed.
    assert not index.crosses((50.0, 5.0), "v")


def _graph(*paths: list[tuple[float, float]]) -> VisibilityGraph:
    """Build a stand-in search graph that joins consecutive points of each path."""
    edges: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for path in paths:
        for a, b in zip(path, path[1:]):
            edges.setdefault(a, []).append(b)
            edges.setdefault(b, []).append(a)
    return cast(VisibilityGraph, SimpleNamespace(nodes=set(edges), edges=edges, recycle_y=[]))


def test_a_route_that_crosses_two_streams_costs_twice():
    """Charge one crossing penalty per stream crossed."""
    graph = _graph([(0.0, 0.0), (40.0, 0.0)])

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
    """Count a crossing anywhere inside a span recorded from two points."""
    index = CrossingIndex()
    index.record([(602.0, 450.0), (640.0, 450.0)])
    assert index.crosses((617.0, 450.0), "v")


def test_a_bend_and_length_tie_breaks_towards_the_route_that_does_not_cross():
    """Prefer the tied route that crosses no recorded line."""
    graph = _graph(
        [(0, 0), (0, 10), (20, 10), (40, 10), (40, 0)],
        [(0, 0), (0, -10), (20, -10), (40, -10), (40, 0)],
    )

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
    """Accept a crossing rather than add two bends to avoid it."""
    graph = _graph(
        [(0, 0), (0, 10), (20, 10), (40, 10), (40, 0)],
        [(0, 0), (0, -10), (20, -10), (20, -30), (40, -30), (40, 0)],
    )

    index = CrossingIndex()
    index.v[20] = [(0.0, 20.0)]  # Cross the north route at (20, 10).
    routed = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=index)
    assert (20, 10) in routed, f"detoured two extra bends to dodge a crossing: {routed}"


def test_a_route_goes_round_rather_than_cross_an_arrowhead():
    """Pay a longer route of the same bends to cross clear of a nozzle."""
    graph = _graph(
        [(0, 0), (0, 10), (20, 10), (40, 10), (40, 0)],
        [(0, 0), (0, -30), (20, -30), (40, -30), (40, 0)],
    )
    assert (20, 10) in find_path(graph, (0, 0), (40, 0), "E", None)

    heads = CrossingIndex()
    heads.record([(20, 4), (20, 16)])  # an arrowhead the north route crosses
    routed = find_path(graph, (0, 0), (40, 0), "E", None, nozzle_index=heads)
    assert (20, -30) in routed, f"crossed the arrowhead: {routed}"


def _final_g(graph, start, goal, start_dir, goal_dir, crossing_index=None):
    """Return the cost of the state ``find_path`` stops on."""
    original = heapq.heappop
    popped: list = []

    def logging_pop(heap):
        """Pop one search state and keep a copy."""
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


def test_a_crossing_at_the_terminal_is_never_worth_a_bend():
    """Cross a line at the goal rather than turn into the stub to dodge it."""
    graph = _graph(
        [(0.0, -20.0), (0.0, 0.0), (20.0, 0.0)],  # Arrive in line with the stub.
        [(0.0, -20.0), (20.0, -20.0), (20.0, 0.0)],  # Arrive from the side.
    )

    index = CrossingIndex()
    index.v[20.0] = [(-30.0, 30.0)]  # Place the goal strictly inside the span.

    routed = find_path(graph, (0.0, -20.0), (20.0, 0.0), None, "W", crossing_index=index)
    assert (0.0, 0.0) in routed, f"bought a bend to dodge a 10px crossing: {routed}"
    assert (20.0, -20.0) not in routed, f"bought a bend to dodge a 10px crossing: {routed}"


@pytest.mark.parametrize("index", [None, CrossingIndex()], ids=["no-index", "empty-index"])
def test_a_side_arrival_pays_the_bend_it_draws_into_the_goal_stub(
    index: CrossingIndex | None,
) -> None:
    """Prefer the arrival in line with the goal stub, one bend fewer."""
    inline = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0)]
    side = [(0.0, 0.0), (0.0, 20.0), (40.0, 20.0)]
    dearer = {((0.0, 0.0), (40.0, 0.0)): 5.0}  # Make the inline arrival 5 px dearer.
    routed = find_path(
        _graph(inline, side), (0.0, 0.0), (40.0, 20.0), None, "N", dearer, crossing_index=index
    )
    assert routed == inline, f"turned into the stub from the side: {routed}"


@pytest.mark.parametrize("side_first", [False, True], ids=["inline-first", "side-first"])
def test_a_side_arrival_wins_a_tie_with_an_inline_arrival(side_first: bool) -> None:
    """Keep the side arrival when both draw two bends over the same length."""
    inline = [(0.0, 0.0), (0.0, 10.0), (40.0, 10.0), (40.0, 20.0)]
    side = [(0.0, 0.0), (0.0, 20.0), (40.0, 20.0)]
    inline_cost = _final_g(_graph(inline), (0.0, 0.0), (40.0, 20.0), None, "N")
    side_cost = _final_g(_graph(side), (0.0, 0.0), (40.0, 20.0), None, "N")
    assert side_cost < inline_cost
    assert side_cost == pytest.approx(inline_cost)

    graph = _graph(side, inline) if side_first else _graph(inline, side)
    routed = find_path(graph, (0.0, 0.0), (40.0, 20.0), None, "N")
    assert routed == side, f"broke the tie towards the inline arrival: {routed}"


def test_a_recycle_search_returns_the_cheapest_path():
    """Estimate a recycle's remaining bend at the recycle's own bend cost."""
    west = [(0.0, 0.0), (0.0, 50.0), (0.0, 100.0), (100.0, 100.0)]
    east = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    graph = _graph(west, east)
    penalties = {((0.0, 0.0), (100.0, 0.0)): 100.0}
    routed = find_path(graph, (0.0, 0.0), (100.0, 100.0), edge_penalties=penalties, is_recycle=True)
    assert routed == west, f"returned the dearer route: {routed}"


def test_committed_segments_refuses_a_diagonal_pair():
    """Reject a diagonal segment instead of guessing its axis."""
    with pytest.raises(ValueError, match="diagonal"):
        committed_segments([(0.0, 0.0), (10.0, 10.0)])


def test_crossing_index_crosses_refuses_an_invalid_axis():
    """Reject an axis other than ``"h"`` or ``"v"``."""
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    with pytest.raises(ValueError, match="axis"):
        index.crosses((50.0, 0.0), "garbage")  # type: ignore[arg-type]


def _obstacle_bypass_tie(fs):
    """Add a stream whose north and south bypasses are exactly tied."""
    f = fs.add(Feed("F")).pin(x=0, y=200)
    p = fs.add(Product("P")).pin(x=400, y=200)
    fs.add(Vessel("V-101", width=100, height=100, label_pos="center")).pin(x=150, y=150)
    return fs.connect(f.outlet, p.inlet)


def test_via_waypoints_on_a_shared_track_stay_where_they_were_put():
    """Never move a ``via()`` route to separate it from another line."""
    fs = Flowsheet("via-shared-track")
    f1 = fs.add(Feed("F1")).pin(x=40, y=90)
    p1 = fs.add(Product("P1")).pin(x=560, y=90)
    f2 = fs.add(Feed("F2")).pin(x=40, y=290)
    p2 = fs.add(Product("P2")).pin(x=560, y=290)
    upper = [(100.0, 100.0), (150.0, 100.0), (150.0, 200.0), (450.0, 200.0), (450.0, 100.0)]
    lower = [(100.0, 300.0), (200.0, 300.0), (200.0, 200.0), (400.0, 200.0), (400.0, 300.0)]
    s1 = fs.connect(f1.outlet, p1.inlet).via(list(upper))
    s2 = fs.connect(f2.outlet, p2.inlet).via(list(lower))
    for _ in range(3):
        fs.route()
        assert s1.route is not None and s1.route.waypoints == upper
        assert s2.route is not None and s2.route.waypoints == lower


@pytest.mark.parametrize("x", [175.0, 176.0], ids=["on-a-lane", "off-every-lane"])
def test_a_manual_routes_geometry_is_recorded_for_later_streams(x: float):
    """Record a manual route so a later stream avoids crossing it."""
    fs = Flowsheet("manual-recorded")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    fs.connect(f1.outlet, p1.inlet).via([(x, 100.0), (x, 170.0)])
    stream = _obstacle_bypass_tie(fs)

    fs.layout()
    fs.route()

    assert stream.route is not None
    wp = stream.route.waypoints
    assert 135.0 not in {y for _, y in wp}, f"F -> P crossed the manual route's line: {wp}"
    assert 265.0 in {y for _, y in wp}, f"F -> P did not take the clear (south) bypass: {wp}"


def test_a_diagonal_manual_route_is_recorded_around_its_own_slant():
    """Record the orthogonal legs of a manual route that has a diagonal leg."""
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
    """Record a fallback route so a later stream avoids crossing it."""
    fs = Flowsheet("fallback-recorded")
    f1 = fs.add(Feed("F1")).pin(x=175, y=100)
    p1 = fs.add(Product("P1")).pin(x=175, y=170)
    fs.connect(f1.outlet, p1.inlet)
    stream = _obstacle_bypass_tie(fs)

    original_find_path = astar.find_path
    original_penalty = astar.CROSSING_PENALTY

    def forced_empty_for_first(graph, start, *args, **kwargs):
        """Return no path for a search that starts on F1's outlet row."""
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


def test_a_balloons_tap_line_is_counted_as_a_crossing():
    """Route a line clear of a balloon's tap line where an equal route crosses it."""
    from pandid.route_geometry import stream_polyline
    from pandid.render.svg import tap_lines, tap_route
    from pandid.routing.metrics import crossing_count

    fs = Flowsheet("tap-recorded")
    feed = fs.add(Feed("F")).pin(x=60, y=100)
    product = fs.add(Product("P")).pin(x=600, y=300)
    vessel = fs.add(Vessel("V-1")).pin(x=200, y=120)
    stream = fs.connect(feed.outlet, product.inlet)
    fs.add_instrument("LT", 1, sensing=vessel, face="W", offset=60)
    fs.route()

    taps = [tap_route(u, tap, centre) for u, tap, centre in tap_lines(fs)]
    assert len(taps) == 1
    assert crossing_count([stream_polyline(stream), *taps]) == 0


def test_crossings_along_counts_a_crossing_strictly_inside_the_span_open_on_both_ends():
    """Count recorded spans crossed strictly inside one edge."""
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
    """Refresh the sorted track cache when a new track is recorded."""
    index = CrossingIndex()
    index.v[10.0] = [(-10.0, 10.0)]
    assert index.crossings_along((0.0, 0.0), (20.0, 0.0)) == 1  # Build the cache.

    index.record([(50.0, -10.0), (50.0, 10.0)])  # Add a track after the build.
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 2


def test_find_path_prices_a_crossing_strictly_inside_a_long_edge_not_just_at_a_node():
    """Charge a crossing that lies inside an edge and on no graph node."""
    graph = _graph([(0.0, 0.0), (100.0, 0.0)])

    clear = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W")

    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]  # Use x=50, which is not a graph node.
    crossed = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W", crossing_index=index)

    assert crossed == pytest.approx(clear + astar.CROSSING_PENALTY)


def test_separation_keeps_a_run_out_of_the_unit_its_stream_joins() -> None:
    """Move a run off a shared track without passing it through its own end unit."""
    from pandid.geometry import Frame
    from pandid.routing.visibility import Rect
    from pandid.routing.separation import separate_streams
    from pandid.units import Tee

    fs = Flowsheet("own unit")
    feed = fs.add(Feed("F1"))
    tee = fs.add(Tee())
    other_feed = fs.add(Feed("F2"))
    other_product = fs.add(Product("P2"))
    for unit in (feed, other_feed, other_product):
        unit.frame = Frame(x=2000.0, y=2000.0, w=10.0, h=10.0)
    tee.frame = Frame(x=480.0, y=1039.0, w=12.0, h=12.0)
    run = fs.connect(feed.outlet, tee.inlet)
    run.route = Route(
        [
            (712.0, 828.0),
            (712.0, 853.0),
            (712.0, 1037.0),
            (454.0, 1037.0),
            (454.0, 1045.0),
            (480.0, 1045.0),
        ]
    )
    nearby = fs.connect(other_feed.outlet, other_product.inlet)
    nearby.route = Route([(500.0, 1033.0), (700.0, 1033.0), (700.0, 900.0)])

    separate_streams(fs)
    assert run.route is not None
    box = Rect(480.0, 492.0, 1039.0, 1051.0)
    points = run.route.waypoints
    assert not any(box.intersects_segment(*a, *b) for a, b in zip(points, points[1:]))
    assert points != [
        (712.0, 828.0),
        (712.0, 853.0),
        (712.0, 1037.0),
        (454.0, 1037.0),
        (454.0, 1045.0),
        (480.0, 1045.0),
    ]


def test_preview_separated_waypoints_does_not_mutate_and_matches_the_real_pass():
    """Preview separation without changing routes, and match the real pass."""
    from pandid.routing.separation import preview_separated_waypoints, separate_streams

    fs = Flowsheet("preview-vs-real")
    f1 = fs.add(Feed("F1")).pin(x=1000, y=1000)
    p1 = fs.add(Product("P1")).pin(x=1000, y=1000)
    s1 = fs.connect(f1.outlet, p1.inlet)
    s1.route = Route([(0.0, 50.0), (0.0, 100.0), (300.0, 100.0), (300.0, 150.0)])
    f2 = fs.add(Feed("F2")).pin(x=2000, y=1000)
    p2 = fs.add(Product("P2")).pin(x=2000, y=1000)
    s2 = fs.connect(f2.outlet, p2.inlet)
    s2.route = Route([(100.0, 50.0), (100.0, 100.0), (400.0, 100.0), (400.0, 150.0)])

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


def test_a_later_streams_recording_uses_separated_not_raw_geometry(monkeypatch):
    """Record the separated route so later streams price its drawn path."""
    from pandid.routing import separation

    def lowered(streams: list[Stream]) -> dict[int, list[tuple[float, float]]]:
        """Return every route 6 px lower, as a separation preview."""
        return {
            id(s): [(x, y + 6.0) for x, y in s.route.waypoints]
            for s in streams
            if s.route is not None
        }

    monkeypatch.setattr(separation, "preview_separated_waypoints", lowered)
    recorded: list[list[tuple[float, float]]] = []
    original_record = CrossingIndex.record

    def spy(self, path):
        """Record one path and keep a copy of it."""
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
    later = fs.add(Product("P3")).pin(x=3400, y=1000)
    fs.connect(fs.add(Feed("F3")).pin(x=3000, y=1000).outlet, later.inlet)

    fs.layout()
    CrossingIndex.record = spy
    try:
        # Keep layout-search trials out of the router's recording spy.
        fs.route(router=DefaultRouter())
    finally:
        CrossingIndex.record = original_record

    assert s2.route is not None
    assert s2.route.waypoints[1][1] == 100.0, f"the via() route moved: {s2.route.waypoints}"
    s2_recordings = [p for p in recorded if p and p[0][0] == 100.0]
    assert s2_recordings, f"s2's geometry was never recorded: {recorded}"
    assert s2_recordings[-1][1][1] == 106.0, s2_recordings[-1]
