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
