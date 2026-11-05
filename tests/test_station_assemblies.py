"""Station geometry should follow its material run as one assembly."""

from __future__ import annotations

import pytest

from pandid import Feed, Flowsheet, GravitySeparator, Product, Reactor, Valve
from pandid.layout.attach import logical_stream_path
from pandid.layout.layered import END_ROOM
from pandid.layout.mounted import _station_width
from _quality import measure_final
from pandid.portgeom import port_point
from pandid.spec import SpecError

from _layout_cases import on_the_run


def test_unpinned_station_keeps_its_run_and_branches_together() -> None:
    """Place an unpinned station as one horizontal assembly."""
    fs = Flowsheet("Station assembly")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    station = fs.add_valve_station("CV-101")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.layout()
    assert fs._mounted_layout is True
    main = on_the_run(station)
    assert [unit.frame.x for unit in main] == sorted(unit.frame.x for unit in main)
    for unit in main:
        assert unit.frame is not None
        assert port_point(unit, unit.frame, "inlet")[1] == pytest.approx(300)
        assert port_point(unit, unit.frame, "outlet")[1] == pytest.approx(300)
    assert station.bypass is not None and station.bypass.frame is not None
    assert port_point(station.bypass, station.bypass.frame, "inlet")[1] < 300
    for drain in (station.upstream_drain, station.downstream_drain):
        assert drain is not None and drain.frame is not None
        assert port_point(drain, drain.frame, "inlet")[1] > 300

    saved = fs.to_dict()
    rebuilt = Flowsheet.from_dict(saved)
    assert rebuilt.to_dict() == saved
    rebuilt.layout()
    assert [(unit.name, unit.frame.x, unit.frame.y) for unit in rebuilt.units] == [
        (unit.name, unit.frame.x, unit.frame.y) for unit in fs.units
    ]


def test_hand_wired_station_is_set_on_its_pipe() -> None:
    """Keep an unpinned hand-wired station out of the equipment grid."""
    fs = Flowsheet("Hand-wired station")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    station = fs.add_valve_station("CV-101")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.layout()
    assert fs._mounted_layout is True
    fs.route()
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0
    assert quality.length < 1000
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


@pytest.mark.parametrize("product_col", [1, 3])
def test_station_uses_receiver_axis_after_a_south_discharge(product_col: int) -> None:
    """Place a station on the horizontal leg after an elbow."""
    fs = Flowsheet("Reactor outlet station")
    reactor = fs.add(Reactor("R-101")).pin(col=0)
    product = fs.add(Product("Product")).pin(col=product_col)
    run = fs.connect(reactor.outlet, product.inlet)
    station = fs.add_valve_station("CV-101", on=run)

    fs.layout()
    first = [(unit.frame.x, unit.frame.y) for unit in fs.units]
    fs.layout()
    assert [(unit.frame.x, unit.frame.y) for unit in fs.units] == first
    assert reactor.frame is not None and product.frame is not None
    assert reactor.frame.y != product.frame.y
    nozzle_span = (
        port_point(product, product.frame, "inlet")[0]
        - port_point(reactor, reactor.frame, "outlet")[0]
    )
    assert nozzle_span == pytest.approx(_station_width(fs._station_assemblies) + END_ROOM)
    receiver_y = port_point(product, product.frame, "inlet")[1]
    main = on_the_run(station)
    assert all(
        unit.frame is not None
        and port_point(unit, unit.frame, "inlet")[1] == pytest.approx(receiver_y)
        for unit in main
    )
    fs.route()
    assert not any(issue.code in ("unit-overlap", "route-crosses-unit") for issue in fs.validate())


def test_station_does_not_force_an_outward_facing_elbow() -> None:
    """Set a station on the routed pipe after it leaves an east nozzle westward."""
    fs = Flowsheet("Reverse outlet station")
    feed = fs.add(Feed("Feed")).pin(x=1300, y=300)
    reactor = fs.add(Reactor("R-101")).pin(x=100, y=100, orientation=90)
    run = fs.connect(feed.outlet, reactor.feed)
    station = fs.add_valve_station("CV-101", on=run)

    fs.route()
    assert feed.frame is not None and reactor.frame is not None
    assert port_point(feed, feed.frame, "outlet") == (1300, 300)
    assert (reactor.frame.x, reactor.frame.y, reactor.frame.orientation) == (100, 100, 90)
    main = on_the_run(station)
    assert len({round(port_point(unit, unit.frame, "inlet")[1]) for unit in main}) == 1
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)


def test_station_compacts_an_equipment_train_from_a_pinned_origin() -> None:
    """Keep a station's members out of the equipment grid solve."""
    fs = Flowsheet("Pinned train")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101")).pin(x=500, y=350)
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, product.inlet)
    station = fs.add_valve_station("CV-101", on=run)

    fs.route()
    assert reactor.frame is not None and product.frame is not None
    assert (reactor.frame.x, reactor.frame.y) == (500, 350)
    assert 0 < product.frame.x - reactor.frame.x < 650
    assert station.control.frame is not None
    assert not any(stream.route is not None and stream.route.used_fallback for stream in fs.streams)
    first = [(unit.frame.x, unit.frame.y) for unit in fs.units]
    fs.layout()
    fs.route()
    assert [(unit.frame.x, unit.frame.y) for unit in fs.units] == first


def test_branch_station_keeps_a_clear_compact_default_route() -> None:
    """Avoid routing regressions after contracting a branched train."""
    fs = Flowsheet("Branched train")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101"))
    separator = fs.add(GravitySeparator("S-101"))
    product = fs.add(Product("Product"))
    waste = fs.add(Product("Waste"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, separator.feed)
    fs.add_valve_station("CV-101", on=run)
    fs.connect(separator.overflow, product.inlet)
    fs.connect(separator.underflow, waste.inlet)

    fs.route()
    quality = measure_final(fs)
    assert quality.hard[:4] == (0, 0, 0, 0)
    assert quality.crossings == 0
    assert quality.length < 1900


def test_station_on_a_line_retains_the_line_and_fraction() -> None:
    """Insert a station into one material run without replacing its handle."""
    fs = Flowsheet("Station insertion")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = fs.connect(feed.outlet, product.inlet, size=80, service="P")
    instrument = fs.add_instrument("FT", 101, sensing=run, at=0.75)

    station = fs.add_valve_station("CV-101", on=run, at=0.3)
    assert fs.streams[0] is run
    assert run.dest is station.inlet
    assert station.outlet.stream is not None
    assert station.outlet.stream.dest is product.inlet
    assert instrument.host is run
    assert station.control.inlet.stream is not None
    assert station.control.inlet.stream.name == run.name
    fs.to_svg(diagram="p&id")
    assert len(logical_stream_path(run)) > len(run.route.waypoints) + 2
    assert station.control.frame is not None
    assert station.control.frame.cx < 700
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec
    assert rebuilt.units[-1].host is rebuilt.streams[0]


def test_station_insertion_rejects_invalid_run_without_mutation() -> None:
    """Reject an out-of-range fraction before creating station members."""
    fs = Flowsheet("Rejected station")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    original = fs.to_dict()
    with pytest.raises(ValueError, match="fraction"):
        fs.add_valve_station("CV-101", on=run, at=1)
    assert fs.to_dict() == original
    assert run.dest is product.inlet


def test_station_reverse_flow_and_optional_members() -> None:
    """Keep a reduced station together when its host flows westward."""
    fs = Flowsheet("Reverse station")
    feed = fs.add(Feed("Feed")).pin(mirrored=True).pin(port="outlet", x=1300, y=300)
    product = fs.add(Product("Product")).pin(mirrored=True).pin(port="inlet", x=100, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    station = fs.add_valve_station(
        "CV-101", on=run, at=0.7, isolation=False, reducers=False, bypass=False, drains=0
    )

    fs.layout()
    assert len(station.members) == 1
    assert station.control.frame is not None
    assert station.control.frame.mirrored
    assert (
        port_point(station.control, station.control.frame, "inlet")[0]
        > port_point(station.control, station.control.frame, "outlet")[0]
    )
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_station_member_pin_remains_exact() -> None:
    """Keep an authored member coordinate when it conflicts with the corridor."""
    fs = Flowsheet("Pinned member")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    station = fs.add_valve_station("CV-101")
    station.control.pin(x=750, y=150)
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.layout()
    assert station.control.frame is not None
    assert (station.control.frame.x, station.control.frame.y) == (750, 150)
    main = on_the_run(station)
    assert max(unit.frame.x for unit in main) - min(unit.frame.x for unit in main) < 600


def test_feasible_member_pin_anchors_the_complete_station() -> None:
    """Keep a station compact around an exact control-valve position."""
    fs = Flowsheet("Pinned station assembly")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    station = fs.add_valve_station("CV-1")
    station.control.pin(x=700, y=287.75)
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.route()

    assert station.control.frame is not None
    assert (station.control.frame.x, station.control.frame.y) == (700, 287.75)
    main = on_the_run(station)
    assert max(unit.frame.x for unit in main) - min(unit.frame.x for unit in main) < 600
    run_y = port_point(station.control, station.control.frame, "inlet")[1]
    assert run_y == pytest.approx(300, abs=1)
    for unit in main:
        assert unit.frame is not None
        assert port_point(unit, unit.frame, "inlet")[1] == pytest.approx(run_y)
        assert port_point(unit, unit.frame, "outlet")[1] == pytest.approx(run_y)
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)


def test_station_member_nearby_pin_remains_exact_after_render() -> None:
    """Keep a member pin even when its proposed assembly frame is nearby."""
    fs = Flowsheet("Nearby pinned member")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=200)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=200)
    station = fs.add_valve_station("CV-1")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.layout()
    assert station.control.frame is not None
    requested_x = station.control.frame.x + 0.5
    station.control.pin(x=requested_x)
    fs.to_svg()

    assert station.control.frame is not None
    assert station.control.frame.x == requested_x
    assert not any(issue.code == "pin-not-honored" for issue in fs.validate())


def test_two_stations_use_fractions_of_the_original_run() -> None:
    """Measure every inserted station from the same original endpoints."""
    fs = Flowsheet("Two stations")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=2000, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    later = fs.add_valve_station("CV-2", on=run, at=0.7)
    earlier = fs.add_valve_station("CV-1", on=run, at=0.3)

    fs.layout()
    assert earlier.control.frame is not None and later.control.frame is not None
    assert abs(earlier.control.frame.cx - 670) < 40
    assert abs(later.control.frame.cx - 1430) < 40
    assert earlier.control.frame.cx < later.control.frame.cx
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_inline_pass_does_not_scatter_a_tee_free_station() -> None:
    """Keep a station assembled when every member is inline eligible."""
    fs = Flowsheet("Tee-free station")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1800, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    station = fs.add_valve_station("CV-101", on=run, at=0.5, bypass=False, drains=0)

    fs.layout()
    xs = [unit.frame.x for unit in station.members]
    assert xs == sorted(xs)
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_spec_rejects_missing_station_tees_before_layout() -> None:
    """Refuse a station record that omits its wired junctions."""
    fs = Flowsheet("Bad station record")
    fs.add_valve_station("CV-101")
    spec = fs.to_dict()
    spec["stations"][0]["tees"] = []
    with pytest.raises(SpecError, match="stations\\[0\\]"):
        Flowsheet.from_dict(spec)


def test_a_device_or_station_without_at_sits_mid_line() -> None:
    """Draw a lone item at the line's midpoint without storing a fraction."""
    valve_sheet = Flowsheet("Default valve")
    feed = valve_sheet.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = valve_sheet.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = valve_sheet.connect(feed.outlet, product.inlet)
    valve = valve_sheet.add(Valve("HV-1"), on=run)
    assert run._inline_at is None
    assert "inline_at" not in valve_sheet.to_dict()["streams"][0]
    valve_sheet.layout()
    assert valve.frame is not None and abs(valve.frame.cx - 700) < 1

    station_sheet = Flowsheet("Default station")
    feed = station_sheet.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = station_sheet.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = station_sheet.connect(feed.outlet, product.inlet)
    station = station_sheet.add_valve_station("CV-1", on=run)
    assert run._inline_at is None
    spec = station_sheet.to_dict()
    assert "at" not in spec["stations"][0]
    assert Flowsheet.from_dict(spec).to_dict() == spec
    station_sheet.layout()
    assert station.control.frame is not None
    assert abs(station.control.frame.cx - 700) < 1


def test_spec_rejects_station_attached_to_an_unrelated_run() -> None:
    """Reject a station record that claims another stream as its host."""
    fs = Flowsheet("Unrelated run")
    source = fs.add(Feed("A"))
    sink = fs.add(Product("Z"))
    station = fs.add_valve_station("CV-101")
    fs.connect(source.outlet, station.inlet)
    fs.connect(station.outlet, sink.inlet)
    other_source = fs.add(Feed("B"))
    other_sink = fs.add(Product("Q"))
    fs.connect(other_source.outlet, other_sink.inlet)
    spec = fs.to_dict()
    spec["stations"][0]["run"] = len(spec["streams"]) - 1
    spec["stations"][0]["at"] = 0.5

    with pytest.raises(SpecError, match="stations\\[0\\]"):
        Flowsheet.from_dict(spec)
