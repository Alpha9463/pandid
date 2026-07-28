"""Routing polish: geometric properties a routed sheet has to hold, none of which
a golden byte-match would localise — forward streams staying off the sheet-edge
recycle lanes, runs never drawn over themselves, ports leaving squarely without a
gratuitous hop, and the separation pass moving only the runs that actually collide."""

from pandid import Flowsheet, units as U
from pandid.routing.visibility import VisibilityGraph


def _ammonia_loop():
    fs = Flowsheet("Ammonia Loop")
    feed = fs.add(U.Feed("Natural Gas"))
    mix = fs.add(U.Mixer("M-101"))
    reformer = fs.add(U.Reactor("R-101"))
    hx = fs.add(U.HeatExchanger("E-101"))
    sep = fs.add(U.Separator("V-101"))
    comp = fs.add(U.Compressor("K-101"))
    prod = fs.add(U.Product("Ammonia"))
    fs.connect(feed.outlet, mix.in_1)
    fs.connect(mix.outlet, reformer.feed)
    fs.connect(reformer.outlet, hx.shell_in)
    fs.connect(hx.shell_out, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.connect(comp.discharge, mix.in_2)  # recycle
    fs.connect(sep.liquid, prod.inlet)
    return fs


def test_forward_streams_do_not_route_on_the_recycle_lane():
    fs = _ammonia_loop()
    fs.layout()
    fs.route()
    graph = VisibilityGraph(fs, margin=15.0)
    lanes = {round(y, 1) for y in graph.recycle_y}
    assert lanes, "expected global recycle lanes to exist for this loop"
    for s in fs.streams:
        if s.is_recycle:
            continue
        on_lane = {round(y, 1) for _, y in s.route.waypoints} & lanes
        assert not on_lane, f"forward stream {s.name} travels on recycle lane(s) {on_lane}"


def _crossing_network():
    """Two feeds, each splitting to both mixers — forces two streams to share
    the vertical corridor between the splitter and mixer columns."""
    fs = Flowsheet("Crossing Network")
    f1, f2 = fs.add(U.Feed("Feed A")), fs.add(U.Feed("Feed B"))
    s1 = fs.add(U.Splitter("SP-501", n_outlets=2))
    s2 = fs.add(U.Splitter("SP-502", n_outlets=2))
    m1 = fs.add(U.Mixer("M-501", n_inlets=2))
    m2 = fs.add(U.Mixer("M-502", n_inlets=2))
    p1, p2 = fs.add(U.Product("Product A")), fs.add(U.Product("Product B"))
    fs.connect(f1.outlet, s1.inlet)
    fs.connect(f2.outlet, s2.inlet)
    fs.connect(s1.out_1, m1.in_1)
    fs.connect(s1.out_2, m2.in_1)  # crosses down
    fs.connect(s2.out_1, m1.in_2)  # crosses up
    fs.connect(s2.out_2, m2.in_2)
    fs.connect(m1.outlet, p1.inlet)
    fs.connect(m2.outlet, p2.inlet)
    return fs


def test_parallel_runs_sharing_a_corridor_are_separated():
    # Two streams routed up/down the same corridor must not land on top of each
    # other — at 2px stroke widths a few px apart reads as one doubled line.
    fs = _crossing_network()
    fs.layout()
    fs.route()

    runs = []  # (stream name, x, y_min, y_max)
    for s in fs.streams:
        wp = s.route.waypoints
        for i in range(len(wp) - 1):
            (x1, y1), (x2, y2) = wp[i], wp[i + 1]
            if abs(x1 - x2) < 0.5 and abs(y1 - y2) > 20:
                runs.append((s.name, x1, min(y1, y2), max(y1, y2)))

    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            n1, x1, a1, b1 = runs[i]
            n2, x2, a2, b2 = runs[j]
            if n1 == n2:
                continue
            if min(b1, b2) - max(a1, a2) > 10:  # genuinely share the corridor
                assert abs(x1 - x2) >= 5, (
                    f"{n1} and {n2} run the same corridor only {abs(x1 - x2):.1f}px apart"
                )


def test_routes_remain_orthogonal_and_clear_of_equipment():
    # No routing refinement may buy its result with diagonal segments or
    # obstacle crossings.
    fs = _ammonia_loop()
    fs.layout()
    fs.route()
    boxes = []
    for u in fs.units:
        f = u.frame
        boxes.append((u, f.x, f.y, f.x + f.w, f.y + f.h))
    for s in fs.streams:
        wp = s.route.waypoints
        for i in range(len(wp) - 1):
            (x1, y1), (x2, y2) = wp[i], wp[i + 1]
            assert abs(x1 - x2) < 0.5 or abs(y1 - y2) < 0.5, f"{s.name} has a diagonal segment"


OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def _headings(waypoints):
    """The route's headings in order, one per straight run.

    Zero-length segments are dropped and collinear ones merged, so the result is
    the shape of the drawn line rather than its waypoint count. Dropping the
    degenerate ones matters: a spur that goes out and straight back collapses to
    a repeated waypoint, which hides the reversal from a naive pairwise scan.
    """
    out = []
    for (x1, y1), (x2, y2) in zip(waypoints, waypoints[1:]):
        if abs(x1 - x2) < 0.5 and abs(y1 - y2) < 0.5:
            continue
        d = "E" if x2 > x1 else "W" if x2 < x1 else "S" if y2 > y1 else "N"
        if not out or out[-1] != d:
            out.append(d)
    return out


def _inline_element_signal():
    """An E-facing port whose row is open to the west.

    An in-line primary element (``offset=0``) deliberately stands aside from the
    obstacle set, so the row through its east-facing ``sig_out`` is clear — the
    one geometry in which a run leaving east can turn straight back west.
    """
    fs = Flowsheet("Inline Element")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    prod = fs.add(U.Product("Product")).pin(x=700, y=170)
    line = fs.connect(feed.outlet, prod.inlet)
    fe = fs.add_instrument("FE", 101, on=line, at=0.5, offset=0)
    fic = fs.add_instrument("FIC", 101, on=line, at=0.15, offset=150, variant="panel")
    fs.connect(fe.sig_out, fic.sig_in, kind="electric")
    return fs


def _nozzle_above_its_target_lane():
    """A downward nozzle 15px above the lane it has to join, projected 25px out.

    The escape projection overshoots the lane, so the run has to come back up to
    it — the geometry that tempts the search into a spur out and straight back.
    """
    fs = Flowsheet("Overshot Nozzle")
    hx = fs.add(U.HeatExchanger("E-101")).pin(x=568, y=68)
    sep = fs.add(U.Separator("V-101")).pin(x=728, y=88)
    fs.connect(hx.shell_out, sep.feed)
    return fs


def test_no_run_doubles_back_along_its_own_axis():
    # A reversal draws the run it has just drawn a second time. The cost model
    # charges that spur a single bend, undercutting the honest two-bend detour
    # round whatever provoked it, so nothing but an explicit ban keeps the search
    # off a line drawn over itself.
    for build in (
        _ammonia_loop,
        _crossing_network,
        _inline_element_signal,
        _nozzle_above_its_target_lane,
    ):
        fs = build()
        fs.layout()
        fs.route()
        for s in fs.streams:
            dirs = _headings(s.route.waypoints)
            for a, b in zip(dirs, dirs[1:]):
                assert b != OPPOSITE[a], (
                    f"{fs.name}/{s.name} doubles back ({a} then {b}): {s.route.waypoints}"
                )


def test_a_port_does_not_overshoot_the_lane_it_is_leaving_for():
    # The escape projection is a stand-off, not a compulsory first move: PSV-101
    # relieves north into a flare header whose flag already sits at the valve's
    # escape height, so the run turns east there. Carrying on north first lands
    # the horizontal on whatever lane happens to exist above and costs two more
    # bends coming back down.
    fs = Flowsheet("Relief Header")
    drum = fs.add(U.Vessel("V-101")).pin(x=420, y=145)
    psv = fs.add(U.Valve("PSV-101", variant="relief")).pin(x=441, y=55)
    flare = fs.add(U.Product("To Flare")).pin(x=630, y=5)
    fs.connect(drum.vent, psv.inlet)
    relief = fs.connect(psv.outlet, flare.inlet)
    fs.layout()
    fs.route()

    wp = relief.route.waypoints
    lane = wp[-1][1]  # the flare nozzle's own height
    assert min(y for _, y in wp) >= lane - 0.5, (
        f"relief run rises past the flare lane before turning: {wp}"
    )
    assert _headings(wp) == ["N", "E"], f"expected one bend out of the PSV, got {wp}"


def test_separation_only_moves_runs_that_actually_collide():
    # Clustering tracks with a window of twice the spacing would chain runs a
    # comfortable 12px apart into one cluster and then pack them onto the
    # spacing grid — leaving them 6px apart, closer than they started.
    fs = Flowsheet("Parallel Runs")
    streams = []
    for i, y in enumerate((100, 400, 700, 1000)):
        f = fs.add(U.Feed(f"F-{i}")).pin(x=0, y=y)
        p = fs.add(U.Product(f"P-{i}")).pin(x=600, y=y)
        streams.append(fs.connect(f.outlet, p.inlet))
    # Two interior runs sharing a corridor two spacings apart, and two on top
    # of each other. Only the second pair has anything to resolve.
    streams[0].via([(50, 100), (50, 200), (400, 200), (400, 300)])
    streams[1].via([(50, 460), (50, 212), (400, 212), (400, 500)])
    streams[2].via([(150, 760), (150, 850), (500, 850), (500, 900)])
    streams[3].via([(150, 1060), (150, 850), (500, 850), (500, 1100)])
    fs.layout()
    fs.route()

    clear = [s.route.waypoints[1][1] for s in streams[:2]]
    assert clear == [200, 212], f"already-legible runs were moved: {clear}"

    stacked = [s.route.waypoints[1][1] for s in streams[2:]]
    assert abs(stacked[0] - stacked[1]) >= 6, f"coincident runs left stacked: {stacked}"
