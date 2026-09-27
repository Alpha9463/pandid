"""Station geometry should follow its material run as one assembly."""

from __future__ import annotations

import pytest

from pandid import Feed, Flowsheet, Product, Reactor, Valve
from pandid.layout.attach import logical_stream_path
from pandid.portgeom import port_point
from pandid.spec import SpecError


def test_unpinned_station_keeps_its_run_and_branches_together() -> None:
    """Place an unpinned station as one horizontal assembly.

    Returns
    -------
    None
        Main members share the host corridor; bypass and drains remain local.
    """
    fs = Flowsheet("Station assembly")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    station = fs.add_valve_station("CV-101")
    fs.connect(feed.outlet, station.inlet)
    fs.connect(station.outlet, product.inlet)

    fs.layout()
    main = [
        unit
        for unit in station.members
        if unit not in (station.bypass, station.upstream_drain, station.downstream_drain)
    ]
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


def test_station_uses_receiver_axis_after_a_south_discharge() -> None:
    """Place a station on the horizontal leg after an elbow.

    Returns
    -------
    None
        The assembly aligns with the receiver and retains clear routing.
    """
    fs = Flowsheet("Reactor outlet station")
    reactor = fs.add(Reactor("R-101"))
    product = fs.add(Product("Product"))
    run = fs.connect(reactor.outlet, product.inlet)
    station = fs.place_valve_station_on(run, "CV-101")

    fs.layout()
    first = [(unit.frame.x, unit.frame.y) for unit in fs.units]
    fs.layout()
    assert [(unit.frame.x, unit.frame.y) for unit in fs.units] == first
    assert reactor.frame is not None and product.frame is not None
    assert reactor.frame.y != product.frame.y
    receiver_y = port_point(product, product.frame, "inlet")[1]
    main = [
        unit
        for unit in station.members
        if unit not in (station.bypass, station.upstream_drain, station.downstream_drain)
    ]
    assert all(
        unit.frame is not None
        and port_point(unit, unit.frame, "inlet")[1] == pytest.approx(receiver_y)
        for unit in main
    )
    fs.route()
    assert not any(issue.code in ("unit-overlap", "route-crosses-unit") for issue in fs.validate())


def test_station_does_not_force_an_outward_facing_elbow() -> None:
    """Keep a station off a leg that reverses its source nozzle.

    Returns
    -------
    None
        A westbound host does not form a westbound leg from an east nozzle.
    """
    fs = Flowsheet("Reverse outlet station")
    feed = fs.add(Feed("Feed")).pin(x=1300, y=300)
    reactor = fs.add(Reactor("R-101")).pin(x=100, y=100, orientation=90)
    run = fs.connect(feed.outlet, reactor.feed)
    station = fs.place_valve_station_on(run, "CV-101")

    fs.layout()
    assert feed.frame is not None and reactor.frame is not None
    assert port_point(feed, feed.frame, "outlet") == (1300, 300)
    assert (reactor.frame.x, reactor.frame.y, reactor.frame.orientation) == (100, 100, 90)
    main = [
        unit
        for unit in station.members
        if unit not in (station.bypass, station.upstream_drain, station.downstream_drain)
    ]
    assert len({round(port_point(unit, unit.frame, "inlet")[1]) for unit in main}) > 1


def test_place_valve_station_on_retains_run_and_fraction() -> None:
    """Insert a station into one material run without replacing its handle.

    Returns
    -------
    None
        Topology, instrument host, geometry, and spec preserve insertion.
    """
    fs = Flowsheet("Station insertion")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = fs.connect(feed.outlet, product.inlet, size=80, service="P")
    instrument = fs.add_instrument("FT", 101, sensing=run, at=0.75)

    station = fs.place_valve_station_on(run, "CV-101", at=0.3)
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
    """Reject an out-of-range fraction before creating station members.

    Returns
    -------
    None
        The original sheet and ports remain unchanged.
    """
    fs = Flowsheet("Rejected station")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    original = fs.to_dict()
    with pytest.raises(ValueError, match="fraction"):
        fs.place_valve_station_on(run, "CV-101", at=1)
    assert fs.to_dict() == original
    assert run.dest is product.inlet


def test_station_reverse_flow_and_optional_members() -> None:
    """Keep a reduced station together when its host flows westward.

    Returns
    -------
    None
        Main member order reverses without adding omitted branches.
    """
    fs = Flowsheet("Reverse station")
    feed = fs.add(Feed("Feed")).pin(mirrored=True).pin(port="outlet", x=1300, y=300)
    product = fs.add(Product("Product")).pin(mirrored=True).pin(port="inlet", x=100, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    station = fs.place_valve_station_on(
        run,
        "CV-101",
        at=0.7,
        isolation=False,
        reducers=False,
        bypass=False,
        drains=0,
        mirrored=True,
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
    """Keep an authored member coordinate when it conflicts with the corridor.

    Returns
    -------
    None
        The pinned control valve stays at its stated position.
    """
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


def test_two_stations_use_fractions_of_the_original_run() -> None:
    """Measure every inserted station from the same original endpoints.

    Returns
    -------
    None
        Stations inserted out of order settle near their global fractions.
    """
    fs = Flowsheet("Two stations")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=2000, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    later = fs.place_valve_station_on(run, "CV-2", at=0.7)
    earlier = fs.place_valve_station_on(run, "CV-1", at=0.3)

    fs.layout()
    assert earlier.control.frame is not None and later.control.frame is not None
    assert abs(earlier.control.frame.cx - 670) < 40
    assert abs(later.control.frame.cx - 1430) < 40
    assert earlier.control.frame.cx < later.control.frame.cx
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_inline_pass_does_not_scatter_a_tee_free_station() -> None:
    """Keep a station assembled when every member is inline eligible.

    Returns
    -------
    None
        Main members keep their material order after both placement passes.
    """
    fs = Flowsheet("Tee-free station")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = fs.add(Product("Product")).pin(port="inlet", x=1800, y=300)
    run = fs.connect(feed.outlet, product.inlet)
    station = fs.place_valve_station_on(
        run,
        "CV-101",
        at=0.5,
        gap=80,
        bypass=False,
        drains=0,
    )

    fs.layout()
    xs = [unit.frame.x for unit in station.members]
    assert xs == sorted(xs)
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()


def test_spec_rejects_missing_station_tees_before_layout() -> None:
    """Refuse a station record that omits its wired junctions.

    Returns
    -------
    None
        Deserialization reports the invalid station section.
    """
    fs = Flowsheet("Bad station record")
    fs.add_valve_station("CV-101")
    spec = fs.to_dict()
    spec["stations"][0]["tees"] = []
    with pytest.raises(SpecError, match="stations\\[0\\]"):
        Flowsheet.from_dict(spec)


def test_inline_api_defaults_to_the_midpoint() -> None:
    """Use the run midpoint when the caller omits a fraction.

    Returns
    -------
    None
        A valve and a station each store a preferred half-run position.
    """
    valve_sheet = Flowsheet("Default valve")
    feed = valve_sheet.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = valve_sheet.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = valve_sheet.connect(feed.outlet, product.inlet)
    valve = valve_sheet.place_on(run, Valve("HV-1"))
    assert run._inline_at == 0.5
    valve_sheet.layout()
    assert valve.frame is not None and abs(valve.frame.cx - 700) < 1

    station_sheet = Flowsheet("Default station")
    feed = station_sheet.add(Feed("Feed")).pin(port="outlet", x=100, y=300)
    product = station_sheet.add(Product("Product")).pin(port="inlet", x=1300, y=300)
    run = station_sheet.connect(feed.outlet, product.inlet)
    station = station_sheet.place_valve_station_on(run, "CV-1")
    assert run._inline_at == 0.5
    station_sheet.layout()
    assert station.control.frame is not None
    assert abs(station.control.frame.cx - 700) < 1


def test_spec_rejects_station_attached_to_an_unrelated_run() -> None:
    """Reject a station record that claims another stream as its host.

    Returns
    -------
    None
        An unrelated root cannot silently replace the station attachment.
    """
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
