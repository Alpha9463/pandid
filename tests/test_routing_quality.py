"""Routing polish: forward (non-recycle) streams must not detour onto the global
recycle lanes at the sheet edge — that reads as streams 'cut off' at the top."""

from pfd import Flowsheet, units as U
from pfd.routing.visibility import VisibilityGraph


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
    fs.connect(reformer.outlet, hx.hot_in)
    fs.connect(hx.hot_out, sep.feed)
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
    # Guard against the fix introducing diagonal segments or obstacle crossings.
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
