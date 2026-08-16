import pytest

from pandid.flowsheet import Flowsheet
from pandid.units import Feed, HeatExchanger, Product, Pump, Valve, Vessel
from pandid.routing import get_outward_dir
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

    # Force placement to bypass layout engine
    f.pin(x=0, y=0)
    p.pin(x=200, y=200)

    s = fs.connect(f.outlet, p.inlet)
    fs.route()

    assert s.route is not None
    wp = s.route.waypoints
    # Asserting only that the list exists passes on a router that found nothing
    # at all, so say what the run has to be: it starts on one nozzle, ends on
    # the other, and every segment lies on an axis. Diagonally offset ports
    # cannot be joined by one straight line, so it also has to turn.
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


def test_no_obstacle_intersection():
    from pandid.units import Separator, Compressor

    fs = Flowsheet("intersect_test")
    v = fs.add(Separator("V1"))
    c = fs.add(Compressor("C1"))

    # Place them such that a straight line intersects
    v.pin(x=0, y=0)
    c.pin(x=200, y=0)

    s = fs.connect(v.vapor, c.suction)
    fs.route()

    graph = VisibilityGraph(fs)

    from pandid.render.symbols import default_registry

    src_sym = default_registry.get(v.kind)
    dst_sym = default_registry.get(c.kind)

    spx, spy = src_sym.ports.get("vapor", (src_sym.width / 2, src_sym.height / 2))
    dpx, dpy = dst_sym.ports.get("suction", (dst_sym.width / 2, dst_sym.height / 2))

    sx, sy = v.frame.x + spx, v.frame.y + spy
    dx, dy = c.frame.x + dpx, c.frame.y + dpy

    # A route with no waypoints used to fall through to a bare source-to-dest
    # straight line and be checked against the obstacles as though the router
    # had drawn it, so a router that found nothing passed this test.
    assert s.route is not None and s.route.waypoints, "V1 -> C1 was not routed"
    pts = [(sx, sy)] + s.route.waypoints + [(dx, dy)]

    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        for obs in graph.obstacles:
            # The first segment is allowed to intersect the source unit's bounding box and its external label
            if i in (0, 1):
                if obs.x_min == v.frame.x and obs.y_min == v.frame.y:
                    continue
                if obs.y_max == v.frame.y:
                    continue
            # The last segment is allowed to intersect the dest unit's bounding box and its external label
            if i in (len(pts) - 2, len(pts) - 3):
                if obs.x_min == c.frame.x and obs.y_min == c.frame.y:
                    continue
                if obs.y_max == c.frame.y:
                    continue

            assert not obs.intersects_segment(x1, y1, x2, y2), (
                f"Segment {pts[i]}->{pts[i + 1]} intersects obstacle {obs}"
            )


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
