import pytest
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
    assert not r.intersects_segment(10, 5, 10, 25)
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
