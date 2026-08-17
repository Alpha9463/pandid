import pytest

from pandid.flowsheet import Flowsheet
from pandid.units import Feed, HeatExchanger, Product, Pump, Valve, Vessel
from pandid.routing import get_outward_dir, _fallback_path
from pandid.routing import astar
from pandid.routing.astar import find_path
from pandid.routing.visibility import Rect, VisibilityGraph, clear_gaps


def test_rect_intersection():
    r = Rect(10, 20, 10, 20)
    # Strictly inside
    assert r.contains(15, 15)
    # Edge is not strict containment
    assert not r.contains(10, 15)

    # Segment crossing through
    assert r.intersects_segment(5, 15, 25, 15)
    # Segment on the edge
    assert r.intersects_segment(10, 5, 10, 25)
    # Segment completely outside
    assert not r.intersects_segment(5, 5, 25, 5)


def test_clear_gaps_closes_the_run_a_span_reaches_into():
    lane = [0.0, 10.0, 20.0, 30.0, 40.0]
    # Gap k lies between lane[k] and lane[k + 1]. A span reaching into the two
    # middle gaps closes both and leaves the ones either side open.
    assert clear_gaps(lane, [(15.0, 25.0)]) == [True, False, False, True]
    # Touching a node is not reaching past it: the test is strict on both ends.
    assert clear_gaps(lane, [(20.0, 30.0)]) == [True, True, False, True]
    assert clear_gaps(lane, [(0.0, 10.0)]) == [False, True, True, True]
    # Spans clear of the lane's ends, and spans over the whole of it.
    assert clear_gaps(lane, [(50.0, 60.0)]) == [True] * 4
    assert clear_gaps(lane, [(-5.0, 45.0)]) == [False] * 4
    assert clear_gaps(lane, []) == [True] * 4
    # A lane with nothing to travel between has no gaps to report on.
    assert clear_gaps([7.0], [(0.0, 10.0)]) == []
    assert clear_gaps([], [(0.0, 10.0)]) == []


def test_the_obstacle_index_sees_what_an_exhaustive_scan_sees():
    """The graph narrows each test to the obstacles that can be in the way.

    It indexes them against the lane grid instead of scanning the whole list
    for every point and every candidate edge, which is what routing spent
    nearly all of its time on. The narrowing has to be exactly that: the same
    nodes, and the same adjacency in the same order, as ``Rect.contains`` and
    ``Rect.intersects_segment`` give when asked about every obstacle. Order is
    part of it -- A* breaks equal-cost ties by the order neighbours were
    inserted -- so a re-ordered adjacency list re-routes the sheet.

    The units are pinned rather than laid out, with labels on all four sides
    and positions chosen so lanes land on obstacle edges: containment is strict
    and the segment test is not, so an index that confused the two would pass
    on a sheet whose lanes all fall clear.
    """
    fs = Flowsheet("obstacle index")
    feed = fs.add(Feed("Raw Feed")).pin(x=40, y=200)
    pump = fs.add(Pump("P-101", label_pos="bottom")).pin(x=180, y=180)
    hx = fs.add(HeatExchanger("E-101", width=120, height=60, label_pos="left")).pin(x=320, y=170)
    # x=440 is E-101's right edge (320 + 120) and y=290 its label band's, so the
    # lanes those obstacles put on the grid fall on this vessel's own.
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
    assert len(graph.obstacles) >= 8 and len(graph.nodes) >= 500  # not a vacuous corpus

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
    assert get_outward_dir(0, 50, 100, 100) == "W"
    assert get_outward_dir(100, 50, 100, 100) == "E"
    assert get_outward_dir(50, 0, 100, 100) == "N"
    assert get_outward_dir(50, 100, 100, 100) == "S"


def test_router_integration():
    fs = Flowsheet("test")
    f = fs.add(Feed("F"))
    p = fs.add(Product("P"))
    # A column standing between the two, tall enough to reach both escape
    # lanes. Without it the run the search finds and the L the router falls
    # back to are the same five points, so nothing asserted about the drawn
    # route could tell a working search from one that returned nothing: the
    # sheet has to make the two differ before the assertions below mean
    # anything. It spans both nozzle elevations, so *both* L's cross it and
    # only a searched route gets past.
    wall = fs.add(Vessel("V-101", width=50, height=250))

    # Force placement to bypass layout engine
    f.pin(x=0, y=0)
    p.pin(x=200, y=200)
    wall.pin(x=100, y=0)

    s = fs.connect(f.outlet, p.inlet)
    fs.route()

    assert s.route is not None
    wp = s.route.waypoints
    # Asserting only that the list exists passes on a router that found nothing
    # at all, so say what the run has to be: it starts on one nozzle, ends on
    # the other, every segment lies on an axis, and nothing but the two boxes
    # it is tied to is in its way. Diagonally offset ports cannot be joined by
    # one straight line, so it also has to turn.
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

    # No exemption for the end segments: a nozzle sits on its own box's edge
    # and the stub off it leaves along the outward normal, which the segment
    # test reads as touching rather than crossing. Every segment of this run,
    # first and last included, is clear of every box on the sheet.
    for a, b in zip(wp, wp[1:]):
        hit = [o for o in graph.obstacles if o.intersects_segment(a[0], a[1], b[0], b[1])]
        assert not hit, f"segment {a}->{b} of {wp} runs through {hit}"


def test_no_obstacle_intersection():
    """The searched run goes round what is in its way; the fallback L does not.

    The sheet needs something in the way for that to be a distinction. With
    only the two ends on it, the route is four points, every one of the
    exemptions below applies to every segment, and the fallback L is the
    route the search finds anyway -- so the assertion was never reached and
    could not have failed if it had been. The drum between them is what makes
    the two differ: it stands across both nozzle elevations, so *both* L's
    cross it and only a route that has been searched for gets past.
    """
    from pandid.units import Separator, Compressor

    fs = Flowsheet("intersect_test")
    v = fs.add(Separator("V1"))
    c = fs.add(Compressor("C1"))
    drum = fs.add(Vessel("V-102", width=60, height=120))

    # Place them such that a straight line intersects
    v.pin(x=0, y=100)
    c.pin(x=200, y=100)
    drum.pin(x=90, y=40)

    s = fs.connect(v.vapor, c.suction)
    fs.route()

    graph = VisibilityGraph(fs)

    # A route with no waypoints used to fall through to a bare source-to-dest
    # straight line and be checked against the obstacles as though the router
    # had drawn it, so a router that found nothing passed this test.
    assert s.route is not None and s.route.waypoints, "V1 -> C1 was not routed"
    pts = s.route.waypoints
    assert pts[0] == pytest.approx(graph.port_anchors[("V1", "vapor")])
    assert pts[-1] == pytest.approx(graph.port_anchors[("C1", "suction")])

    # The stub off a nozzle is the one segment that may touch something: the
    # label band sits between the nozzle and the sheet, so a run leaving a
    # top nozzle on a top-labelled unit crosses its own label whatever it
    # does next. That is the *first* segment and the *last*, not the first
    # two and the last two -- which on a four-point route is all of them.
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
    """The L drawn when the search finds nothing is a choice, so make it one.

    Both corner orders reach the same two projections. Only one of them may
    be clear, and the router used to take the across-first order whatever was
    standing on it -- through a vessel as readily as through open sheet.
    """
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (100.0, 100.0), (100.0, 125.0)
    across = [start, start_proj, (100.0, 0.0), goal_proj, goal]
    down = [start, start_proj, (25.0, 100.0), goal_proj, goal]

    # Nothing in the way: the across-first order, exactly as before.
    assert _fallback_path(start, start_proj, goal_proj, goal, []) == across

    # A box on the across-first leg, and the other order goes round it.
    on_across = Rect(40.0, 60.0, -10.0, 10.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_across]) == down

    # A box on each: the search has already said the grid has no way through,
    # so the least bad L is still drawn -- and ``validate()`` reports it under
    # ``route-crosses-unit`` rather than the sheet coming out with a gap in it.
    on_down = Rect(40.0, 60.0, 90.0, 110.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_across, on_down]) == across


def test_the_fallback_drops_a_corner_that_repeats_the_projection():
    """Two projections in one column leave no corner to turn on.

    Kept from #282: a repeated point survives the caller's simplifier, which
    never drops a projection, and reaches the separation pass as a zero-length
    run on a track the stream does not occupy.
    """
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (25.0, 100.0), (25.0, 125.0)
    path = _fallback_path(start, start_proj, goal_proj, goal, [])
    assert path == [start, start_proj, goal_proj, goal]
    assert len(set(path)) == len(path)


def _straight_run(bad=None):
    """Feed to product through a heat exchanger, optionally misplaced."""
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
    """A coordinate that does not compare used to hang the render outright.

    A* terminates because ``visited[state] <= g`` settles each state at most
    once, and that comparison is false for every NaN: nothing was settled,
    every state re-expanded, and the queue's paths grew until the process
    died. ``route()`` never came back, so neither did ``to_svg()``.

    This test cannot itself hang: the sheet is refused before the graph is
    built, which is also the last point that can name the unit at fault.
    """
    with pytest.raises(ValueError, match="E-101 has a non-finite x="):
        _straight_run(bad).route()


def test_the_search_is_bounded_by_the_size_of_the_graph():
    """Termination may not rest on the coordinates being well behaved.

    The endpoint check catches what we know how to name; the expansion ceiling
    is what makes termination unconditional, so a graph poisoned somewhere
    nobody thought to look raises instead of spinning. Driven by taking the
    budget away rather than by finding a pathological sheet, so the test costs
    what any other does.
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

    # The same sheet routes with the budget it is actually given.
    fs = _straight_run()
    fs.route()
    assert all(s.route and s.route.waypoints for s in fs.streams)


def test_find_path_names_the_endpoint_it_cannot_search_from():
    fs = _straight_run()
    fs.layout()
    graph = VisibilityGraph(fs, margin=15.0)
    node = next(iter(graph.nodes))
    with pytest.raises(ValueError, match="non-finite start"):
        find_path(graph, (float("nan"), 0.0), node)
    with pytest.raises(ValueError, match="non-finite goal"):
        find_path(graph, node, (0.0, float("inf")))
