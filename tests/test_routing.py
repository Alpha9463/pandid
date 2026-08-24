import heapq
from types import SimpleNamespace
from typing import cast

import pytest

from pandid.flowsheet import Flowsheet
from pandid.units import Feed, HeatExchanger, Product, Pump, Valve, Vessel
from pandid.routing import get_outward_dir, _fallback_path
from pandid.routing import astar
from pandid.routing.astar import CrossingIndex, committed_segments, find_path
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


def test_the_fallback_l_also_breaks_an_obstacle_tie_on_a_drawn_crossing():
    # Obstacles alone are not the only thing a fallback L can be checked
    # against: two candidates can tie on obstacles (none in the way of
    # either, as here) while one crosses a line an earlier stream already
    # drew and the other does not. Left unchecked, ties always fell to
    # across-first regardless.
    start, start_proj = (0.0, 0.0), (25.0, 0.0)
    goal_proj, goal = (100.0, 100.0), (100.0, 125.0)
    across = [start, start_proj, (100.0, 0.0), goal_proj, goal]
    down = [start, start_proj, (25.0, 100.0), goal_proj, goal]

    # No crossing_index: across-first, same tie-break as ever.
    assert _fallback_path(start, start_proj, goal_proj, goal, []) == across

    # An earlier stream's vertical line at x=50, which only the
    # across-first leg (y=0, x from 25 to 100) passes through.
    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]
    assert _fallback_path(start, start_proj, goal_proj, goal, [], index) == down

    # Obstacles still take priority over lines: a box on the clear (down)
    # leg sends it back to across even though across now crosses a line.
    on_down = Rect(10.0, 40.0, 90.0, 110.0)
    assert _fallback_path(start, start_proj, goal_proj, goal, [on_down], index) == across


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


# ---------------------------------------------------------------------------
# #425: charging a drawn crossing.
# ---------------------------------------------------------------------------


def test_committed_segments_merges_a_straight_run_into_one_span():
    # 602->615->640 is one drawn line, not two: a router-committed path keeps
    # a collinear waypoint the simplifier would later drop (a stub's own
    # projection point, kept verbatim -- see ``DefaultRouter.route()``'s
    # ``simplified`` comment), so the axis a later crossing check needs has
    # to be read off *segments*, not off the raw waypoint count.
    path = [(602.0, 450.0), (615.0, 450.0), (640.0, 450.0)]
    assert committed_segments(path) == [("h", 450.0, 602.0, 640.0)]


def test_committed_segments_merges_across_a_repeated_point_on_the_same_axis():
    # Two horizontal segments meeting at a duplicate waypoint (an escape
    # stub ``share_escape_room`` shrank to nothing, say) are one continuous
    # drawn line, not two that merely touch: a crossing exactly at the
    # touch point (10, 0) has to read as interior to the recorded span, not
    # as the shared endpoint of two separate ones.
    #
    # A different-axis pair either side of the repeat would pass this same
    # assertion even if the repeat were never special-cased at all (an axis
    # change already ends a run on its own), so it proves nothing about the
    # repeat specifically -- this needs same-axis segments on both sides.
    path = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert committed_segments(path) == [("h", 0.0, 0.0, 20.0)]


def test_crossing_index_is_strict_interior_only():
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])  # one horizontal span, y=0, x in [0, 100]

    # Strictly inside: a vertical run through (50, 0), continuing past it on
    # both sides, properly crosses the recorded line.
    assert index.crosses((50.0, 0.0), "v")
    # At the recorded span's own endpoint: a T-junction, not a crossing --
    # the same distinction ``route_quality.py``'s ``crossing_point`` draws
    # between a proper crossing and a branch tee.
    assert not index.crosses((100.0, 0.0), "v")
    assert not index.crosses((0.0, 0.0), "v")
    # Off the recorded lane entirely.
    assert not index.crosses((50.0, 5.0), "v")
    # Wrong axis: querying with "h" asks whether something crosses a
    # *horizontal* run through this node, which looks in ``.v``, not ``.h``.
    assert not index.crosses((50.0, 0.0), "h")


def test_crossing_index_crosses_counts_rather_than_answers_yes_or_no():
    # Two different earlier streams can each cross the same point (each
    # drew its own span, and both happen to cover it) -- a route through
    # there crosses both, not one, and ``crosses`` has to say so rather than
    # collapsing "how many" to "any at all".
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    assert index.crosses((50.0, 0.0), "v") == 1

    index.record([(0.0, 0.0), (100.0, 0.0)])  # a second stream, same line
    assert index.crosses((50.0, 0.0), "v") == 2

    # Still falsy at zero, so a caller that only wants to know whether
    # anything crosses at all keeps working unchanged.
    assert not index.crosses((50.0, 5.0), "v")


def test_a_route_that_crosses_two_streams_costs_twice():
    # The g-cost `find_path` actually settles the returned route at (see
    # ``_final_g``) has to reflect crossing two earlier streams as twice
    # the charge of crossing one -- not the same charge either way, which
    # is what a boolean-valued ``crosses`` gave: a route crossing a second
    # stream at an already-crossed point cost nothing more for it.
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
    two.v[40.0] = [(-10.0, 10.0), (-10.0, 10.0)]  # a second earlier stream, same span
    crossing_two = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W", crossing_index=two)

    assert crossing_one == pytest.approx(clear + astar.CROSSING_PENALTY)
    assert crossing_two == pytest.approx(clear + 2 * astar.CROSSING_PENALTY)


def test_crossing_index_protects_a_stubs_whole_span_not_just_its_ends():
    # The bug #425 shipped and then caught on its own corpus: a fixed
    # anchor->projection stub (or the shared mid-point ``share_escape_room``
    # gives two nozzles too close for both stand-offs) is recorded as *one*
    # long span from a two-point path, with no graph node anywhere in its
    # interior. A later stream sliding onto any lane inside that span --
    # 617 here, never itself a point on the recorded path -- still has to
    # see the crossing; an index keyed on the recorded path's own points
    # would have missed it, which is exactly what let
    # ``17_stirred_reactor_train`` gain a crossing instead of losing one the
    # first time this was tried.
    index = CrossingIndex()
    index.record([(602.0, 450.0), (640.0, 450.0)])
    assert index.crosses((617.0, 450.0), "v")


def _tie_graph() -> VisibilityGraph:
    """Two routes from (0, 0) to (40, 0), tied on both bends and length:
    north via (0, 10)->(20, 10)->(40, 10), south via (0, -10)->(20,
    -10)->(40, -10). No direct east edge at y=0 exists (an obstacle would
    put one there on a real sheet), so the search must pick one detour or
    the other. Built by hand, not through ``Flowsheet``/``VisibilityGraph``,
    so the tie is exact and nothing about placement can perturb it --
    ``find_path`` only ever reads ``graph.nodes``, ``graph.edges`` and
    ``graph.recycle_y``, so a bare stand-in carries everything it needs; the
    cast is only to tell the type checker that too.
    """
    nodes = {(0, 0), (40, 0), (0, 10), (20, 10), (40, 10), (0, -10), (20, -10), (40, -10)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
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
    graph = _tie_graph()

    # An earlier stream's vertical run at x=20, y in [0, 20]: the north
    # detour's horizontal leg passes straight through (20, 10), strictly
    # inside that span, so it crosses; the south leg, through (20, -10),
    # does not.
    crosses_north = CrossingIndex()
    crosses_north.v[20] = [(0.0, 20.0)]
    south = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=crosses_north)
    assert (20, 10) not in south, f"took the crossing route: {south}"
    assert (20, -10) in south, f"did not take the free alternative: {south}"

    # Symmetric the other way: nothing about this favours south by
    # construction, only whichever lane was actually marked crossed.
    crosses_south = CrossingIndex()
    crosses_south.v[20] = [(-20.0, 0.0)]
    north = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=crosses_south)
    assert (20, -10) not in north, f"took the crossing route: {north}"
    assert (20, 10) in north, f"did not take the free alternative: {north}"


def test_a_crossing_is_kept_rather_than_bought_off_with_two_more_bends():
    # North (3 bends, length 60) is charged for a crossing; south is clear
    # but costs two more bends to reach (5 bends, length 100) by way of an
    # extra jog. CROSSING_PENALTY (20) sits two orders of magnitude under
    # BEND_PENALTY (500), so paying it must always be cheaper than buying a
    # bend to avoid it -- the corpus's own "costly" crossings, which needed
    # 8px to 1589px to clear, are the real-world version of this same
    # inequality holding.
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
    index.v[20] = [(0.0, 20.0)]  # crosses north's (20, 10) pass-through
    routed = find_path(graph, (0, 0), (40, 0), "E", None, crossing_index=index)
    assert (20, 10) in routed, f"detoured two extra bends to dodge a crossing: {routed}"


def test_a_forced_crossing_still_routes():
    # No alternative at all -- the north lane above, alone. Charging a
    # crossing must never turn a route the search would otherwise have
    # found into no route.
    nodes = {(0, 0), (40, 0), (0, 10), (20, 10), (40, 10)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
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
    """The g-cost of the state ``find_path`` actually returns on -- the last
    thing popped, since a search returns the instant it pops a state at
    ``goal`` rather than pushing anything further. Reading cost this way,
    from the search's own internals, is what a *forced* graph (exactly one
    route through it) needs: with no alternative to switch to, the returned
    path is identical whether or not something is charged along it, so the
    only way to see a charge landing at all is to read the number it landed
    on, not which route won.
    """
    original = heapq.heappop
    popped: list = []

    def logging_pop(heap):
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
    # A path this search returns on reaches ``goal`` and stops -- the ``if
    # current == goal: return path`` at the top of the loop -- without ever
    # *expanding* it, which is the only place the ordinary per-node check
    # (on ``current``, above) ever fires. So a route that arrives at ``goal``
    # already travelling the direction the caller's fixed goal_proj->port
    # stub continues in (``OPPOSITE[goal_dir]``) is a strict-interior point
    # of the drawn line exactly like any other, and used to cross for free.
    #
    # A single-route graph -- (0, 0) to goal (40, 0), goal_dir "W", one hop
    # -- so there is no alternative arrival for the search to switch to; the
    # only way to see the charge is in the cost the returned route settles
    # at, read via ``_final_g`` rather than by which of two routes won (see
    # ``test_a_crossing_at_the_terminal_is_never_worth_a_bend`` below for
    # why a decision-flip test at the terminal specifically cannot be built
    # fairly).
    nodes = {(0.0, 0.0), (40.0, 0.0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0.0, 0.0)].append((40.0, 0.0))
    edges[(40.0, 0.0)].append((0.0, 0.0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    g_clear = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W")

    index = CrossingIndex()
    index.v[40.0] = [(-10.0, 10.0)]  # goal (40, 0) sits strictly inside it
    g_crossed = _final_g(graph, (0.0, 0.0), (40.0, 0.0), None, "W", crossing_index=index)

    assert g_crossed == pytest.approx(g_clear + astar.CROSSING_PENALTY)


def test_a_crossing_at_the_terminal_is_never_worth_a_bend():
    # The one place a bend at the terminal can hide: an arrival that does
    # not match the fixed goal_proj->port stub's own direction
    # (``OPPOSITE[goal_dir]``) draws a real bend there -- the join between
    # this search's last segment and that stub -- which this search never
    # itself expands or prices, because the stub is added by the caller
    # after this function returns. Charging the straight arrival for a
    # crossing while leaving that side approach's bend unpriced would make
    # a bend look free next to a 10px charge, which is exactly backwards.
    #
    # Perfectly symmetric square, (0, -20) to goal_proj (20, 0), goal_dir
    # "W": one route arrives via (0, 0) heading east -- straight, matching
    # the stub, chargeable if it crosses something; the other via (20, -20)
    # heading north -- a side approach whose own hidden bend must now cost
    # as much as any other. Both cost the same length (40) and the same one
    # counted bend before this fix; the difference the fix adds is entirely
    # in the north route's own uncounted turn.
    nodes = {(0.0, -20.0), (0.0, 0.0), (20.0, 0.0), (20.0, -20.0)}
    edges: dict = {n: [] for n in nodes}

    def link(a, b):
        edges[a].append(b)
        edges[b].append(a)

    link((0.0, -20.0), (0.0, 0.0))
    link((0.0, 0.0), (20.0, 0.0))  # arrives at goal_proj heading east (straight)
    link((0.0, -20.0), (20.0, -20.0))
    link((20.0, -20.0), (20.0, 0.0))  # arrives at goal_proj heading north (side)
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    index = CrossingIndex()
    index.v[20.0] = [(-30.0, 30.0)]  # goal_proj (20, 0) sits strictly inside it

    routed = find_path(graph, (0.0, -20.0), (20.0, 0.0), None, "W", crossing_index=index)
    assert (0.0, 0.0) in routed, f"bought a bend to dodge a 10px crossing: {routed}"
    assert (20.0, -20.0) not in routed, f"bought a bend to dodge a 10px crossing: {routed}"

    # Without the index the two arrivals are a genuine tie (confirms the
    # graph above is not secretly biased towards the straight arrival
    # already) -- which one wins is arbitrary and not asserted on.
    tied = find_path(graph, (0.0, -20.0), (20.0, 0.0), None, "W")
    assert tied in (
        [(0.0, -20.0), (0.0, 0.0), (20.0, 0.0)],
        [(0.0, -20.0), (20.0, -20.0), (20.0, 0.0)],
    )


def test_a_forced_terminal_crossing_still_routes():
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
    # A router-drawn path is orthogonal by construction; a diagonal pair
    # reaching here is a caller bug, and guessing an axis for it (whichever
    # of x or y the check happens to test first) would silently misreport
    # geometry rather than say so.
    with pytest.raises(ValueError, match="diagonal"):
        committed_segments([(0.0, 0.0), (10.0, 10.0)])


def test_crossing_index_crosses_refuses_an_invalid_axis():
    index = CrossingIndex()
    index.record([(0.0, 0.0), (100.0, 0.0)])
    with pytest.raises(ValueError, match="axis"):
        index.crosses((50.0, 0.0), "garbage")  # type: ignore[arg-type]


def _obstacle_bypass_tie(fs):
    """F -> P around a centered obstacle, added to *fs* last, with the
    north and south bypass an exact tie: nothing yet gives the search a
    reason to prefer one over the other, so which one it draws is the free
    choice a stream connected earlier can load one side of.

    ``label_pos="center"`` matters: the vessel's tag block is otherwise
    drawn above it, which makes the obstacle taller on that one side and
    breaks the symmetry the tie depends on.
    """
    f = fs.add(Feed("F")).pin(x=0, y=200)
    p = fs.add(Product("P")).pin(x=400, y=200)
    fs.add(Vessel("V-101", width=100, height=100, label_pos="center")).pin(x=150, y=150)
    return fs.connect(f.outlet, p.inlet)


def test_a_manual_routes_geometry_is_recorded_for_later_streams():
    # A hand-drawn (``.via()``) route is a line on the sheet too, and one an
    # auto-routed stream later in this order can genuinely cross. It used
    # to be invisible: ``DefaultRouter.route()`` skipped a manual stream
    # without ever telling ``crossing_index`` it existed.
    #
    # A spy on ``CrossingIndex.record`` that merely asserts it was *called*
    # passes just as well against a ``record`` that silently does nothing
    # once called (a real regression this project's own review caught) --
    # the call happening proves nothing about whether it had any effect. So
    # this checks the effect instead: F -> P (connected second, so it
    # routes second) has a free, bend- and length-tied choice between an
    # obstacle bypass to the north or the south (see
    # ``_obstacle_bypass_tie``); the manual stream (connected first) draws
    # its line squarely across the north one's path -- x=175 is a lane the
    # bypass's own row already carries, so the search's raw path is
    # guaranteed to pass through the exact node the crossing is checked at.
    # If recording manual geometry ever regresses to a no-op, F -> P goes
    # back to breaking this tie arbitrarily, and on this construction that
    # arbitrary choice is north -- straight across the line just drawn.
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
    # Unlike a router-drawn path, a manual (``.via()``) one is not
    # guaranteed orthogonal -- ``validate()``'s own ``route-diagonal``
    # finding exists because an author's waypoints can legitimately be
    # drawn on the slant. Recording that geometry must not crash ``route()``
    # over a leg ``committed_segments`` (rightly) refuses to call an axis;
    # the diagonal leg is left out, the orthogonal ones either side of it
    # are not.
    #
    # "Does not crash, and validate() still reports route-diagonal" proves
    # only that routing survives the diagonal leg -- a regression that
    # skipped recording *every* manual route containing one (diagonal or
    # not) would pass both checks just as well. Same fix as the other two
    # recording tests: check the orthogonal legs' actual effect. The manual
    # route here is an orthogonal leg across the north bypass (as in
    # ``test_a_manual_routes_geometry_is_recorded_for_later_streams``)
    # followed by a diagonal one that goes nowhere near it, so recording
    # the orthogonal leg despite the diagonal one sitting right after it in
    # the same waypoint list is exactly what's under test.
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
    # The L drawn when a search comes back empty is still a line on the
    # sheet. It used to be invisible too: only the ``if path:`` branch
    # called ``crossing_index.record``, never the ``_fallback_path`` one,
    # so a later stream's search could not see it -- #425's corpus already
    # had two live crossings this let through (``AE-303-80-80-SS`` on
    # ``11_ethanol_pid+auto``, a fallback-drawn stream).
    #
    # Same shape as the manual-route test above and for the same reason: a
    # spy that only checks ``crossing_index.record`` was *called* cannot
    # tell a working recording from a silent no-op, so this checks that a
    # later stream's route actually changes. The fixture units sitting
    # near the bypass (rather than far off-sheet, as the manual version
    # can afford) perturb the tie by a small, fixed amount of their own --
    # empirically about 10px -- so ``CROSSING_PENALTY`` is raised for the
    # duration of this test alone, comfortably clear of that perturbation
    # without depending on its exact size.
    #
    # ``find_path`` is forced empty on its first call only, which is the
    # first stream's -- the same seam ``route_quality.py``'s own ``Recorder``
    # patches, since ``DefaultRouter.route()`` re-imports it fresh every
    # call.
    fs = Flowsheet("fallback-recorded")
    f1 = fs.add(Feed("F1")).pin(x=175, y=100)
    p1 = fs.add(Product("P1")).pin(x=175, y=170)
    fs.connect(f1.outlet, p1.inlet)
    stream = _obstacle_bypass_tie(fs)

    original_find_path = astar.find_path
    original_penalty = astar.CROSSING_PENALTY
    calls = [0]

    def forced_empty_once(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return []
        return original_find_path(*args, **kwargs)

    astar.find_path = forced_empty_once
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
    # ``crosses`` answers "does a crossing land here" for one node a search
    # actually stops at; ``crossings_along`` is the whole-edge version the
    # new interior-edge check in ``find_path`` and ``_fallback_path`` both
    # lean on, since neither a graph edge's own skipped-lane stretch nor a
    # fallback L's corner is built from nodes at all. Two earlier spans
    # crossing the same edge count as two, the same counting ``crosses``
    # already does; a span sitting exactly at the edge's own endpoint --
    # 100.0 here, not strictly inside (0.0, 100.0) -- is not a crossing of
    # *this* edge and must not count (the endpoint is what the node-based
    # checks price, when it is one of this path's own nodes).
    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]
    index.v[100.0] = [(-10.0, 10.0)]  # at the edge's own endpoint, not inside it
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 1
    index.v[50.0].append((-10.0, 10.0))  # a second earlier stream, same span
    assert index.crossings_along((0.0, 0.0), (100.0, 0.0)) == 2
    # Neither a diagonal nor a zero-length pair is a segment this index's
    # straight-line spans can properly cross.
    assert index.crossings_along((0.0, 0.0), (10.0, 10.0)) == 0
    assert index.crossings_along((5.0, 5.0), (5.0, 5.0)) == 0


def test_find_path_prices_a_crossing_strictly_inside_a_long_edge_not_just_at_a_node():
    # #483's round-5 review, point 1: a graph edge is one hop, but not
    # necessarily a short one -- the visibility grid skips lane coordinates
    # an obstacle blocks, not the ones past it, so an edge can run well past
    # several skipped coordinates with no node of its own anywhere inside.
    # A hand-drawn (``.via()``) route is under no obligation to land on a
    # lane at all, so an earlier crossing can sit at exactly such a
    # coordinate -- x=50 here, strictly inside the graph's only edge from
    # (0, 0) to (100, 0) and never itself a node -- where the old per-node
    # checks alone never looked. Neither ``current`` (0, 0) nor ``goal``
    # (100, 0) is itself strictly interior to the recorded span (its fixed
    # coordinate, 50, matches neither), so this isolates the new
    # whole-edge check from the pre-existing node-based ones: they would
    # find nothing here on their own.
    nodes = {(0.0, 0.0), (100.0, 0.0)}
    edges: dict = {n: [] for n in nodes}
    edges[(0.0, 0.0)].append((100.0, 0.0))
    edges[(100.0, 0.0)].append((0.0, 0.0))
    graph = cast(VisibilityGraph, SimpleNamespace(nodes=nodes, edges=edges, recycle_y=[]))

    clear = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W")

    index = CrossingIndex()
    index.v[50.0] = [(-10.0, 10.0)]  # off-node: 50.0 is nowhere in ``nodes``
    crossed = _final_g(graph, (0.0, 0.0), (100.0, 0.0), None, "W", crossing_index=index)

    assert crossed == pytest.approx(clear + astar.CROSSING_PENALTY)


def test_a_manual_route_off_lane_still_breaks_the_tie():
    # #483's round-5 review, point 1, at the ``Flowsheet`` level: x=175 in
    # ``test_a_manual_routes_geometry_is_recorded_for_later_streams`` above
    # happens to be a lane the bypass's own row already carries, so that
    # test was already passing on the pre-existing per-node check alone.
    # x=176 is not a lane coordinate anywhere on this sheet's grid -- before
    # the interior-edge check existed, F -> P's search edge sailed straight
    # over it (confirmed directly against the pre-fix code) and drew the
    # crossing unpriced. Same fixture, same assertions, one digit changed.
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
    # ``DefaultRouter.route()`` needs to know where ``separate_streams``
    # will actually put a stream's waypoints *before* that pass has run
    # (see the ``settle`` test below for why), without that preview
    # becoming the drawn sheet itself -- ``_compute_offsets``'s own
    # docstring covers why running the real, writing pass more than once
    # is not an option. So the preview has to promise two things: it
    # changes nothing on its own, and it agrees with the real pass once
    # that does run.
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
    assert s1.route is not None and s2.route is not None  # ``.via()`` sets both directly

    raw_s1, raw_s2 = list(s1.route.waypoints), list(s2.route.waypoints)
    preview = preview_separated_waypoints(fs.streams)

    # Not applied to the real waypoints -- the whole point of a preview.
    assert s1.route.waypoints == raw_s1
    assert s2.route.waypoints == raw_s2

    separate_streams(fs)

    # But it has to match what the real, writing pass settles on, or a
    # decision made from the preview would not match the sheet that gets
    # drawn either.
    assert preview[id(s1)] == s1.route.waypoints
    assert preview[id(s2)] == s2.route.waypoints
    # And separation actually moved something here, or none of the above
    # proves anything: s1/s2's overlapping middle runs (both at y=100,
    # neither "fixed" -- see ``_compute_offsets`` -- since neither is the
    # first or last segment of its route) are exactly what triggers it.
    assert s1.route.waypoints != raw_s1 or s2.route.waypoints != raw_s2


def test_a_later_streams_recording_uses_separated_not_raw_geometry():
    # #483's round-5 review, point 2: the router recorded every route's
    # *raw*, pre-separation geometry into ``crossing_index``, then only
    # afterwards ran ``separate_streams`` -- once, on the whole sheet -- to
    # nudge overlapping parallel runs apart. So a later stream's search was
    # always pricing crossings against a drawing that was never actually
    # made: the true, on-sheet position of an earlier run could be a few
    # pixels off whatever the index had recorded for it.
    #
    # Two manual routes share an unfixed middle run at y=100, overlapping
    # in x (see the preview test above), so ``separate_streams`` moves the
    # second one to y=106 once both are on the sheet -- confirmed against
    # s2's own final waypoints below, not assumed. What gets *recorded* for
    # s2 has to show that same y=106, not the raw y=100 that s2 never
    # actually draws by the time the sheet is finished; a spy on
    # ``CrossingIndex.record`` reads that off directly rather than needing
    # a downstream routing decision to flip.
    recorded: list[list[tuple[float, float]]] = []
    original_record = CrossingIndex.record

    def spy(self, path):
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
        fs.route()
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
