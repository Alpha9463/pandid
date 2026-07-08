from pfd import Flowsheet, units as U


def test_unit_pin_sets_placement():
    fs = Flowsheet("Test")
    feed = fs.add(U.Feed("F1"))
    
    assert feed.placement is None
    # Fluent API check
    returned = feed.pin(x=100.5, y=200.0, orientation=90)
    assert returned is feed
    
    assert feed.placement is not None
    assert feed.placement.x == 100.5
    assert feed.placement.y == 200.0
    assert feed.placement.orientation == 90
    assert feed.placement.col is None


def test_stream_via_sets_route_waypoints():
    fs = Flowsheet("Test")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    
    s = fs.connect(feed.outlet, prod.inlet)
    assert s.route is None
    
    # Fluent API check
    returned = s.via([(100, 100), (200, 100)])
    assert returned is s
    
    assert s.route is not None
    assert s.route.manual is True
    assert s.route.waypoints == [(100, 100), (200, 100)]
