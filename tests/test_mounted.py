"""Check stream-mounted furniture: kept out of placement and set on its pipe."""

from __future__ import annotations

from pandid import Feed, Flowsheet, GravitySeparator, Product, Reactor, Valve
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point
from scripts.layout_compare import _fingerprint


def _clean(fs: Flowsheet) -> bool:
    """Return whether a routed sheet has no hard finding.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    bool
        Whether every hard count is zero.
    """
    quality = measure_final(fs)
    return quality.hard == (0,) * len(quality.hard) and not quality.hard_conflicts


def test_a_pinned_hand_wired_valve_splits_two_mounted_runs() -> None:
    """Check that mounted valves sit either side of a pinned connect() valve."""
    fs = Flowsheet("Mixed run")
    feed = fs.add(Feed("Feed"))
    middle = fs.add(Valve("HV-M")).pin(x=400, y=192.5)
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, middle.inlet)
    downstream = fs.connect(middle.outlet, product.inlet)
    first = fs.place_on(upstream, Valve("HV-A"))
    second = fs.place_on(downstream, Valve("HV-B"))

    fs.route()
    assert fs._mounted_layout is True
    assert middle.frame is not None and (middle.frame.x, middle.frame.y) == (400, 192.5)
    assert feed.frame is not None and product.frame is not None
    assert first.frame is not None and second.frame is not None
    assert feed.frame.x < first.frame.x < middle.frame.x < second.frame.x < product.frame.x
    assert _clean(fs)


def test_a_chain_without_room_is_drawn_and_named() -> None:
    """Check that furniture too long for its pinned run is set and reported."""
    fs = Flowsheet("No room")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=160, y=100)
    run = fs.connect(feed.outlet, product.inlet)
    for index, at in enumerate((0.25, 0.5, 0.75)):
        fs.place_on(run, Valve(f"HV-{index}"), at=at)

    fs.route()
    assert all(unit.frame is not None for unit in fs.units)
    findings = [issue for issue in fs.validate() if issue.code == "inline-no-room"]
    assert findings and all(issue.severity == "warning" for issue in findings)
    assert any("HV-" in issue.message for issue in findings)


def test_a_device_on_a_return_run_is_mounted() -> None:
    """Check that a valve on a return line is set on its pipe."""
    fs = Flowsheet("Return run")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101", n_feeds=2))
    separator = fs.add(GravitySeparator("S-101"))
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed_1)
    fs.connect(reactor.outlet, separator.feed)
    fs.connect(separator.overflow, product.inlet)
    back = fs.connect(separator.underflow, reactor.feed_2)
    valve = fs.place_on(back, Valve("HV-R"))

    fs.route()
    assert fs._mounted_layout is True
    assert any(segment.is_recycle for segment in back._logical_segments)
    assert valve.frame is not None
    assert _clean(fs)


def test_a_free_hand_wired_station_beside_mounted_devices() -> None:
    """Check that an unplaced add_valve_station() station stays a placed group."""
    fs = Flowsheet("Mixed furniture")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    station = fs.add_valve_station("CV-101")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)
    other_feed = fs.add(Feed("Water"))
    other_product = fs.add(Product("Drain"))
    run = fs.connect(other_feed.outlet, other_product.inlet)
    fs.place_on(run, Valve("HV-1"))

    fs.route()
    assert fs._mounted_layout is True
    main = [
        unit
        for unit in station.members
        if unit not in (station.bypass, station.upstream_drain, station.downstream_drain)
    ]
    assert (
        len(
            {
                round(port_point(unit, unit.frame, "inlet")[1], 3)
                for unit in main
                if unit.frame is not None
            }
        )
        == 1
    )
    assert _clean(fs)


def test_a_position_pinned_mounted_device_keeps_the_full_placement() -> None:
    """Check that a pinned place_on() device keeps today's placement and its pin."""
    fs = Flowsheet("Pinned mounted device")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    valve = fs.place_on(run, Valve("HV-1").pin(x=300, y=200))

    fs.route()
    assert fs._mounted_layout is False
    assert valve.frame is not None and (valve.frame.x, valve.frame.y) == (300, 200)


def test_routing_a_mounted_sheet_again_draws_the_same_sheet() -> None:
    """Check that layout and routing a mounted sheet twice give one drawing."""
    fs = Flowsheet("Repeatable")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101"))
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, product.inlet)
    fs.place_on(run, Valve("HV-1"), at=0.3)
    fs.place_valve_station_on(run, "CV-101", at=0.7)

    fs.route()
    first = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == first
    fs.layout()
    fs.route()
    assert _fingerprint(fs) == first
    assert fs.to_svg() == fs.to_svg()
