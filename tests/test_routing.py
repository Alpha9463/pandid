from pfd.flowsheet import Flowsheet
from pfd.units import Feed, Product
from pfd.routing import get_outward_dir
from pfd.routing.visibility import Rect, VisibilityGraph

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
    assert isinstance(s.route.waypoints, list)
    # Ensure it's not a straight line (i.e. length > 0)
    # It has to step orthogonally around things!
    assert len(s.route.waypoints) >= 1

def test_no_obstacle_intersection():
    from pfd.units import Separator, Compressor
    fs = Flowsheet("intersect_test")
    v = fs.add(Separator("V1"))
    c = fs.add(Compressor("C1"))
    
    # Place them such that a straight line intersects
    v.pin(x=0, y=0)
    c.pin(x=200, y=0)
    
    s = fs.connect(v.vapor, c.suction)
    fs.route()
    
    graph = VisibilityGraph(fs)
    
    from pfd.render.symbols import default_registry
    src_sym = default_registry.get(v.kind)
    dst_sym = default_registry.get(c.kind)
    
    spx, spy = src_sym.ports.get("vapor", (src_sym.width/2, src_sym.height/2))
    dpx, dpy = dst_sym.ports.get("suction", (dst_sym.width/2, dst_sym.height/2))
    
    sx, sy = v.frame.x + spx, v.frame.y + spy
    dx, dy = c.frame.x + dpx, c.frame.y + dpy
    
    if s.route.waypoints:
        pts = [(sx, sy)] + s.route.waypoints + [(dx, dy)]
    else:
        pts = [(sx, sy), (dx, dy)]
        
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i+1]
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
                
            assert not obs.intersects_segment(x1, y1, x2, y2), f"Segment {pts[i]}->{pts[i+1]} intersects obstacle {obs}"
