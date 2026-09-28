"""Stream-relative insertion and placement of simple inline devices."""

from __future__ import annotations

import pytest

from pandid import Feed, Flowsheet, Product, Reactor, Tee, Valve
from pandid.layout.backbone import infer_backbone
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point
from pandid.state import State


def test_place_on_keeps_the_logical_stream_and_places_the_valve() -> None:
    """Keep the caller's stream handle through insertion and a spec round-trip.

    Returns
    -------
    None
        The device lies on the straight run and the original host survives.
    """
    fs = Flowsheet("Inline valve")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet, size=6, service="P")
    run.state = State(T=300)
    instrument = fs.add_instrument("FT", 101, sensing=run, at=0.6)
    valve = Valve("HV-101")

    assert fs.place_on(run, valve, at=0.4) is valve
    assert fs.streams[0] is run
    assert run.dest is valve.inlet
    assert fs.streams[1].source is valve.outlet
    assert fs.streams[1].dest is product.inlet
    assert instrument.host is run
    assert run.state is not None and run.state.T == 300
    assert fs.streams[0].name == fs.streams[1].name
    before_waypoints = run.route.waypoints if run.route is not None else None
    with pytest.raises(ValueError, match="split run"):
        run.via([(200, 100)])
    assert (run.route.waypoints if run.route is not None else None) == before_waypoints

    fs.to_svg()
    assert valve.frame is not None
    assert feed.frame is not None and product.frame is not None
    assert feed.frame.x < valve.frame.x < product.frame.x
    start = port_point(feed, feed.frame, "outlet")
    end = port_point(product, product.frame, "inlet")
    assert abs(valve.frame.cx - (start[0] + 0.4 * (end[0] - start[0]))) < 1
    assert not any(issue.code == "unit-overlap" for issue in fs.validate())
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.to_dict() == spec
    assert rebuilt.units[-1].host is rebuilt.streams[0]


def test_place_on_orders_repeated_insertions_by_fraction() -> None:
    """Insert devices in run order even when calls arrive in reverse order.

    Returns
    -------
    None
        Fractions and physical segments follow the material direction.
    """
    fs = Flowsheet("Two valves")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    later = fs.place_on(run, Valve("HV-2"), at=0.75)
    earlier = fs.place_on(run, Valve("HV-1"), at=0.25)

    assert [s.dest.owner.name for s in fs.streams] == ["HV-1", "HV-2", "Product"]
    assert [s._inline_at for s in fs.streams] == [0.25, 0.75, None]
    assert infer_backbone(fs).runs[0].inline_at == (0.25, 0.75)
    fs.to_svg()
    assert earlier.frame is not None and later.frame is not None
    assert earlier.frame.x < later.frame.x
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert rebuilt.to_dict() == fs.to_dict()
    rebuilt.place_on(rebuilt.streams[0], Valve("HV-3"), at=0.5)
    assert [s._inline_at for s in rebuilt.streams] == [0.25, 0.5, 0.75, None]


def test_unpinned_inline_chain_uses_equipment_first_placement() -> None:
    """Place two attached valves after solving their external equipment.

    Returns
    -------
    None
        The routed train is compact, clear, and stable across layout runs.
    """
    fs = Flowsheet("Inline equipment train")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    first = fs.place_on(run, Valve("HV-1"), at=0.25)
    second = fs.place_on(run, Valve("HV-2"), at=0.75)

    fs.layout()
    assert fs._coarse_layout_candidate is True
    fs.route()
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0
    assert quality.length < 200
    assert first.frame is not None and second.frame is not None
    assert feed.frame is not None and product.frame is not None
    assert feed.frame.x < first.frame.x < second.frame.x < product.frame.x
    frames = [(unit.frame.x, unit.frame.y) for unit in fs.units]
    fs.layout()
    fs.route()
    assert [(unit.frame.x, unit.frame.y) for unit in fs.units] == frames


@pytest.mark.parametrize("pinned_origin", [False, True])
def test_south_discharge_inline_chain_uses_receiver_leg(pinned_origin: bool) -> None:
    """Place inline valves on the clear leg after a south discharge.

    Parameters
    ----------
    pinned_origin : bool
        Fix the reactor's absolute frame position when true.

    Returns
    -------
    None
        The reactor train uses contracted placement with a clear elbow.
    """
    fs = Flowsheet("South outlet inline train")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101"))
    if pinned_origin:
        reactor.pin(x=350, y=250)
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, product.inlet)
    first = fs.place_on(run, Valve("HV-1"), at=0.25)
    second = fs.place_on(run, Valve("HV-2"), at=0.75)

    fs.layout()
    assert fs._coarse_layout_candidate is True
    fs.route()
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.bends <= 1
    assert reactor.frame is not None and product.frame is not None
    assert first.frame is not None and second.frame is not None
    if pinned_origin:
        assert (reactor.frame.x, reactor.frame.y) == (350, 250)
    receiver_y = port_point(product, product.frame, "inlet")[1]
    assert receiver_y > port_point(reactor, reactor.frame, "outlet")[1]
    assert port_point(first, first.frame, "inlet")[1] == pytest.approx(receiver_y)
    assert port_point(second, second.frame, "inlet")[1] == pytest.approx(receiver_y)


def test_south_discharge_does_not_put_inline_valves_above_its_outlet() -> None:
    """Reject a receiver leg that opposes the reactor's south nozzle.

    Returns
    -------
    None
        A pinned upstream receiver keeps the full placement path.
    """
    fs = Flowsheet("Pinned receiver")
    reactor = fs.add(Reactor("R-101"))
    product = fs.add(Product("Product")).pin(y=50)
    run = fs.connect(reactor.outlet, product.inlet)
    fs.place_on(run, Valve("HV-1"), at=0.5)

    fs.layout()
    assert fs._coarse_layout_candidate is False
    fs.route()
    assert product.frame is not None
    assert port_point(product, product.frame, "inlet")[1] == 50


def test_inline_chain_preserves_a_pinned_branch_origin() -> None:
    """Propagate a feed's absolute pin through a contracted branch run.

    Returns
    -------
    None
        The tee and valve follow the feed without a routing defect.
    """
    fs = Flowsheet("Pinned branch inline")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=450, y=300)
    tee = fs.add(Tee())
    product = fs.add(Product("Product"))
    branch = fs.add(Product("Branch"))
    run = fs.connect(feed.outlet, tee.inlet)
    valve = fs.place_on(run, Valve("HV-1"), at=0.5)
    fs.connect(tee.outlet, product.inlet)
    fs.connect(tee.branch, branch.inlet)

    fs.route()
    assert fs._coarse_layout_candidate is False
    assert feed.frame is not None and tee.frame is not None and valve.frame is not None
    assert port_point(feed, feed.frame, "outlet") == (450, 300)
    assert feed.frame.x < valve.frame.x < tee.frame.x
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0


def test_unrelated_inline_preference_cannot_mask_a_failed_attachment() -> None:
    """Require every contracted device to fit its own host corridor.

    Returns
    -------
    None
        A separate placed device cannot make a failed chain look complete.
    """
    fs = Flowsheet("Separate inline runs")
    feed_a = fs.add(Feed("Feed A"))
    product_a = fs.add(Product("Product A"))
    run = fs.connect(feed_a.outlet, product_a.inlet)
    fs.place_on(run, Valve("HV-A").pin(orientation=90), at=0.5)

    feed_b = fs.add(Feed("Feed B"))
    valve_b = fs.add(Valve("HV-B"))
    product_b = fs.add(Product("Product B"))
    preferred = fs.connect(feed_b.outlet, valve_b.inlet)
    fs.connect(valve_b.outlet, product_b.inlet)
    fs._set_inline_at(preferred, 0.5)

    fs.layout()
    assert fs._coarse_layout_candidate is False


def test_adjacent_logical_runs_use_their_own_fractions() -> None:
    """Keep each attachment's fraction tied to its own logical run.

    Returns
    -------
    None
        Both devices appear between the endpoints of their own root runs.
    """
    fs = Flowsheet("Adjacent logical runs")
    feed = fs.add(Feed("Feed"))
    middle = fs.add(Valve("HV-M"))
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, middle.inlet)
    downstream = fs.connect(middle.outlet, product.inlet)
    first = fs.place_on(upstream, Valve("HV-A"), at=0.25)
    second = fs.place_on(downstream, Valve("HV-B"), at=0.75)

    fs.layout()
    assert fs._coarse_layout_candidate is True
    fs.route()
    assert feed.frame is not None and middle.frame is not None and product.frame is not None
    assert first.frame is not None and second.frame is not None
    feed_exit = port_point(feed, feed.frame, "outlet")[0]
    middle_inlet = port_point(middle, middle.frame, "inlet")[0]
    middle_exit = port_point(middle, middle.frame, "outlet")[0]
    product_inlet = port_point(product, product.frame, "inlet")[0]
    assert feed_exit < first.frame.cx < middle_inlet
    assert middle_exit < second.frame.cx < product_inlet
    assert first.frame.cx == pytest.approx(feed_exit + 0.25 * (middle_inlet - feed_exit))
    assert second.frame.cx == pytest.approx(middle_exit + 0.75 * (product_inlet - middle_exit))
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0
    assert quality.length < 400


def test_adjacent_roots_with_handwired_preference_keep_full_placement() -> None:
    """Exclude a merged run containing a separately positioned valve.

    Returns
    -------
    None
        The mixed run remains on the established full placement path.
    """
    fs = Flowsheet("Mixed inline preferences")
    feed = fs.add(Feed("Feed"))
    first_boundary = fs.add(Valve("HV-M"))
    handwired = fs.add(Valve("HV-H"))
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, first_boundary.inlet)
    middle = fs.connect(first_boundary.outlet, handwired.inlet)
    downstream = fs.connect(handwired.outlet, product.inlet)
    fs.place_on(upstream, Valve("HV-A"), at=0.1)
    fs.place_on(downstream, Valve("HV-B"), at=0.9)
    fs._set_inline_at(middle, 0.25)

    fs.layout()
    assert fs._coarse_layout_candidate is False
    fs.route()
    assert first_boundary.frame is not None and handwired.frame is not None
    assert first_boundary.frame.x < handwired.frame.x
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0
    assert quality.bends < 12


def test_place_on_refuses_invalid_calls_without_mutation() -> None:
    """Reject unsupported inputs before adding a unit or splitting a stream.

    Returns
    -------
    None
        The topology and original stream remain unchanged.
    """
    fs = Flowsheet("Invalid insertion")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    before = fs.to_dict()
    for device, at in ((Valve("V-1"), 0), (Tee(), 0.5), (Valve("V-2"), 1)):
        with pytest.raises(ValueError):
            fs.place_on(run, device, at=at)
        assert fs.to_dict() == before
        assert run.dest is product.inlet
    run.via([(200, 100)])
    before = fs.to_dict()
    with pytest.raises(ValueError, match="manual"):
        fs.place_on(run, Valve("V-3"), at=0.5)
    assert fs.to_dict() == before


def test_place_on_restores_ports_after_numbering_failure() -> None:
    """Restore every pre-existing object if renumbering rejects a split.

    Returns
    -------
    None
        The original run and unused device keep their identities and ports.
    """
    fs = Flowsheet("Numbering rollback")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet, size=6)
    device = Valve("HV-101")
    fs.line_numbering_scheme = "{unknown}"
    before = fs.to_dict()

    with pytest.raises(ValueError, match="unknown"):
        fs.place_on(run, device, at=0.5)

    assert fs.to_dict() == before
    assert fs.streams == [run]
    assert run.dest is product.inlet
    assert feed.outlet.stream is run and product.inlet.stream is run
    assert device.flowsheet is None
    assert device.inlet.stream is None and device.outlet.stream is None


def test_place_on_respects_branch_and_exact_device_pin() -> None:
    """Keep a branch junction and an exact pinned device as placed.

    Returns
    -------
    None
        The branch remains a node and the valve stays at its pin.
    """
    fs = Flowsheet("Pinned branch")
    feed = fs.add(Feed("Feed"))
    junction = fs.add(Tee())
    product = fs.add(Product("Product"))
    branch = fs.add(Product("Branch"))
    fs.connect(feed.outlet, junction.inlet)
    run = fs.connect(junction.outlet, product.inlet)
    fs.connect(junction.branch, branch.inlet)
    valve = Valve("HV-101").pin(x=400, y=180)
    fs.place_on(run, valve, at=0.2)

    fs.to_svg()
    assert valve.frame is not None and (valve.frame.x, valve.frame.y) == (400, 180)
    assert junction in [fs.units[index] for index in infer_backbone(fs).nodes]
    assert not any(issue.code == "pin-not-honored" for issue in fs.validate())


def test_position_after_pinned_device_uses_full_run_fraction() -> None:
    """Measure later attachments from the original run endpoints.

    Returns
    -------
    None
        A pinned inline node does not reset the fraction's origin.
    """
    fs = Flowsheet("Pinned inline origin")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=900, y=100)
    run = fs.connect(feed.outlet, product.inlet)
    first = Valve("HV-1").pin(x=300, y=92.5)
    fs.place_on(run, first, at=0.25)
    later = fs.place_on(run, Valve("HV-2"), at=0.75)

    fs.to_svg()
    assert first.frame is not None and first.frame.x == 300
    assert later.frame is not None and abs(later.frame.cx - 700) < 1
