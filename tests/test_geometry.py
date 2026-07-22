from pfd import Flowsheet, units as U


def test_unit_pin_sets_pin():
    fs = Flowsheet("Test")
    feed = fs.add(U.Feed("F1"))

    assert feed.pin_ is None
    # Fluent API check
    returned = feed.pin(x=100.5, y=200.0, orientation=90)
    assert returned is feed

    # pin() records intent only; the frame stays unset until layout runs.
    assert feed.frame is None
    assert feed.pin_ is not None
    assert feed.pin_.x == 100.5
    assert feed.pin_.y == 200.0
    assert feed.pin_.orientation == 90
    assert feed.pin_.col is None


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
