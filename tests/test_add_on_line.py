"""Stream-relative insertion and placement of simple inline devices."""

from __future__ import annotations

import pytest

from pandid import Feed, Flowsheet, Mixer, Product, Reactor, Splitter, Stream, Tee, Valve
from pandid.layout.mounted import mounted_runs
from _quality import measure_final
from pandid.portgeom import port_point
from pandid.state import State
from pandid.stations import ValveStation


def test_add_on_keeps_the_line_handle_and_places_the_valve() -> None:
    """Keep the caller's stream handle through insertion and a spec round-trip."""
    fs = Flowsheet("Inline valve")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet, size=6, service="P")
    run.state = State(T=300)
    instrument = fs.add_instrument("FT", 101, sensing=run, at=0.6)
    valve = Valve("HV-101")

    assert fs.add(valve, on=run, at=0.4) is valve
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


def test_add_on_orders_insertions_by_fraction() -> None:
    """Insert devices in run order even when calls arrive in reverse order."""
    fs = Flowsheet("Two valves")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    later = fs.add(Valve("HV-2"), on=run, at=0.75)
    earlier = fs.add(Valve("HV-1"), on=run, at=0.25)

    assert [s.dest.owner.name for s in fs.streams] == ["HV-1", "HV-2", "Product"]
    assert [s._inline_at for s in fs.streams] == [0.25, 0.75, None]
    assert tuple(place[2] for place in mounted_runs(fs)[0].places if place) == (0.25, 0.75)
    fs.to_svg()
    assert earlier.frame is not None and later.frame is not None
    assert earlier.frame.x < later.frame.x
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    assert rebuilt.to_dict() == fs.to_dict()
    rebuilt.add(Valve("HV-3"), on=rebuilt.streams[0], at=0.5)
    assert [s._inline_at for s in rebuilt.streams] == [0.25, 0.5, 0.75, None]


def test_unpinned_inline_chain_uses_equipment_first_placement() -> None:
    """Place two attached valves after solving their external equipment."""
    fs = Flowsheet("Inline equipment train")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    first = fs.add(Valve("HV-1"), on=run, at=0.25)
    second = fs.add(Valve("HV-2"), on=run, at=0.75)

    fs.layout()
    assert fs._mounted_layout is True
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
    """Place inline valves on the leg that reaches the receiver."""
    fs = Flowsheet("South outlet inline train")
    feed = fs.add(Feed("Feed"))
    reactor = fs.add(Reactor("R-101"))
    if pinned_origin:
        reactor.pin(x=350, y=250)
    product = fs.add(Product("Product"))
    fs.connect(feed.outlet, reactor.feed)
    run = fs.connect(reactor.outlet, product.inlet)
    first = fs.add(Valve("HV-1"), on=run, at=0.25)
    second = fs.add(Valve("HV-2"), on=run, at=0.75)

    fs.layout()
    assert fs._mounted_layout is True
    fs.route()
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.bends <= 1
    assert reactor.frame is not None and product.frame is not None
    assert first.frame is not None and second.frame is not None
    if pinned_origin:
        assert (reactor.frame.x, reactor.frame.y) == (350, 250)
    receiver_y = port_point(product, product.frame, "inlet")[1]
    assert port_point(first, first.frame, "inlet")[1] == pytest.approx(receiver_y)
    assert port_point(second, second.frame, "inlet")[1] == pytest.approx(receiver_y)


def test_south_discharge_does_not_put_inline_valves_above_its_outlet() -> None:
    """Reject a receiver leg that opposes the reactor's south nozzle."""
    fs = Flowsheet("Pinned receiver")
    reactor = fs.add(Reactor("R-101"))
    product = fs.add(Product("Product")).pin(y=50)
    run = fs.connect(reactor.outlet, product.inlet)
    fs.add(Valve("HV-1"), on=run, at=0.5)

    fs.layout()
    assert fs._mounted_layout is True
    fs.route()
    assert product.frame is not None
    assert port_point(product, product.frame, "inlet")[1] == 50


def test_inline_chain_preserves_a_pinned_branch_origin() -> None:
    """Propagate a feed's absolute pin through a contracted branch run."""
    fs = Flowsheet("Pinned branch inline")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=450, y=300)
    tee = fs.add(Tee())
    product = fs.add(Product("Product"))
    branch = fs.add(Product("Branch"))
    run = fs.connect(feed.outlet, tee.inlet)
    valve = fs.add(Valve("HV-1"), on=run, at=0.5)
    fs.connect(tee.outlet, product.inlet)
    fs.connect(tee.branch, branch.inlet)

    fs.route()
    assert fs._mounted_layout is True
    assert feed.frame is not None and tee.frame is not None and valve.frame is not None
    assert port_point(feed, feed.frame, "outlet") == (450, 300)
    assert feed.frame.x < valve.frame.x < tee.frame.x
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0


def test_unrelated_inline_preference_cannot_mask_a_failed_attachment() -> None:
    """Require every contracted device to fit its own host corridor."""
    fs = Flowsheet("Separate inline runs")
    feed_a = fs.add(Feed("Feed A"))
    product_a = fs.add(Product("Product A"))
    run = fs.connect(feed_a.outlet, product_a.inlet)
    fs.add(Valve("HV-A").pin(orientation=180), on=run, at=0.5)

    feed_b = fs.add(Feed("Feed B"))
    valve_b = fs.add(Valve("HV-B"))
    product_b = fs.add(Product("Product B"))
    preferred = fs.connect(feed_b.outlet, valve_b.inlet)
    fs.connect(valve_b.outlet, product_b.inlet)
    fs._set_inline_at(preferred, 0.5)

    fs.layout()
    assert fs._mounted_layout is True


def test_rotation_only_pin_places_inline_valve_on_its_host_run() -> None:
    """Keep a rotated valve at its requested fraction of the host run."""
    fs = Flowsheet("Rotated inline valve")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=900, y=100)
    run = fs.connect(feed.outlet, product.inlet)
    valve = fs.add(Valve("V").pin(orientation=90), on=run, at=0.5)

    fs.layout()
    assert fs._mounted_layout is True
    fs.route()

    assert valve.frame is not None
    assert valve.frame.orientation == 90
    assert valve.frame.cx == pytest.approx(500)
    assert valve.frame.cy == pytest.approx(100)
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)


def test_adjacent_logical_runs_use_their_own_fractions() -> None:
    """Keep each attachment's fraction tied to its own logical run."""
    fs = Flowsheet("Adjacent logical runs")
    feed = fs.add(Feed("Feed"))
    middle = fs.add(Valve("HV-M"))
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, middle.inlet)
    downstream = fs.connect(middle.outlet, product.inlet)
    first = fs.add(Valve("HV-A"), on=upstream, at=0.25)
    second = fs.add(Valve("HV-B"), on=downstream, at=0.75)

    fs.layout()
    assert fs._mounted_layout is True
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
    """Exclude a merged run containing a separately positioned valve."""
    fs = Flowsheet("Mixed inline preferences")
    feed = fs.add(Feed("Feed"))
    first_boundary = fs.add(Valve("HV-M"))
    handwired = fs.add(Valve("HV-H"))
    product = fs.add(Product("Product"))
    upstream = fs.connect(feed.outlet, first_boundary.inlet)
    middle = fs.connect(first_boundary.outlet, handwired.inlet)
    downstream = fs.connect(handwired.outlet, product.inlet)
    fs.add(Valve("HV-A"), on=upstream, at=0.1)
    fs.add(Valve("HV-B"), on=downstream, at=0.9)
    fs._set_inline_at(middle, 0.25)

    fs.layout()
    assert fs._mounted_layout is True
    fs.route()
    assert first_boundary.frame is not None and handwired.frame is not None
    assert first_boundary.frame.x < handwired.frame.x
    quality = measure_final(fs)
    assert quality.hard == (0,) * len(quality.hard)
    assert quality.crossings == 0
    assert quality.bends < 12


def test_add_on_refuses_invalid_calls_without_mutation() -> None:
    """Reject unsupported inputs before adding a unit or splitting a stream."""
    fs = Flowsheet("Invalid insertion")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet)
    before = fs.to_dict()
    for device, at in ((Valve("V-1"), 0), (Tee(), 0.5), (Valve("V-2"), 1)):
        with pytest.raises(ValueError):
            fs.add(device, on=run, at=at)
        assert fs.to_dict() == before
        assert run.dest is product.inlet
    run.via([(200, 100)])
    before = fs.to_dict()
    with pytest.raises(ValueError, match="manual"):
        fs.add(Valve("V-3"), on=run, at=0.5)
    assert fs.to_dict() == before


def test_add_on_restores_ports_after_numbering_failure() -> None:
    """Restore every pre-existing object if renumbering rejects a split."""
    fs = Flowsheet("Numbering rollback")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    run = fs.connect(feed.outlet, product.inlet, size=6)
    device = Valve("HV-101")
    fs.line_numbering_scheme = "{unknown}"
    before = fs.to_dict()

    with pytest.raises(ValueError, match="unknown"):
        fs.add(device, on=run, at=0.5)

    assert fs.to_dict() == before
    assert fs.streams == [run]
    assert run.dest is product.inlet
    assert feed.outlet.stream is run and product.inlet.stream is run
    assert device.flowsheet is None
    assert device.inlet.stream is None and device.outlet.stream is None


def test_add_on_respects_branch_and_exact_device_pin() -> None:
    """Keep a branch junction and an exact pinned device as placed."""
    fs = Flowsheet("Pinned branch")
    feed = fs.add(Feed("Feed"))
    junction = fs.add(Tee())
    product = fs.add(Product("Product"))
    branch = fs.add(Product("Branch"))
    fs.connect(feed.outlet, junction.inlet)
    run = fs.connect(junction.outlet, product.inlet)
    fs.connect(junction.branch, branch.inlet)
    valve = Valve("HV-101").pin(x=400, y=180)
    fs.add(valve, on=run, at=0.2)

    fs.to_svg()
    assert valve.frame is not None and (valve.frame.x, valve.frame.y) == (400, 180)
    assert all(junction not in run.elements for run in mounted_runs(fs))
    assert not any(issue.code == "pin-not-honored" for issue in fs.validate())


def test_position_after_pinned_device_uses_full_run_fraction() -> None:
    """Measure later attachments from the original run endpoints."""
    fs = Flowsheet("Pinned inline origin")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=900, y=100)
    run = fs.connect(feed.outlet, product.inlet)
    first = Valve("HV-1").pin(x=300, y=92.5)
    fs.add(first, on=run, at=0.25)
    later = fs.add(Valve("HV-2"), on=run, at=0.75)

    fs.to_svg()
    assert first.frame is not None and first.frame.x == 300
    assert later.frame is not None and abs(later.frame.cx - 700) < 1


def test_devices_without_at_go_in_the_order_added() -> None:
    """Put several devices on a line without inventing fractions for them."""
    fs = Flowsheet("Three valves")
    feed = fs.add(Feed("Feed")).pin(port="outlet", x=100, y=100)
    product = fs.add(Product("Product")).pin(port="inlet", x=1300, y=100)
    line = fs.connect(feed.outlet, product.inlet)
    valves = [fs.add(Valve(f"HV-{n}"), on=line) for n in (1, 2, 3)]

    assert [s.dest.owner.name for s in fs.streams] == ["HV-1", "HV-2", "HV-3", "Product"]
    assert tuple(place[2] for place in mounted_runs(fs)[0].places if place) == (0.25, 0.5, 0.75)
    fs.layout()
    centres = [valve.frame.cx for valve in valves if valve.frame is not None]
    assert centres == pytest.approx([400, 700, 1000], abs=1)
    spec = fs.to_dict()
    assert not any("inline_at" in entry for entry in spec["streams"])
    assert Flowsheet.from_dict(spec).to_dict() == spec


def test_a_device_with_at_goes_before_any_with_a_larger_at() -> None:
    """Order a stated fraction among devices added without one."""
    fs = Flowsheet("Mixed positions")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet)
    fs.add(Valve("HV-1"), on=line)
    fs.add(Valve("HV-2"), on=line, at=0.6)
    fs.add(Valve("HV-3"), on=line)
    fs.add(Valve("HV-4"), on=line, at=0.3)

    assert [s.dest.owner.name for s in fs.streams] == ["HV-1", "HV-4", "HV-2", "HV-3", "Product"]
    assert tuple(place[2] for place in mounted_runs(fs)[0].places if place) == pytest.approx(
        (0.15, 0.3, 0.6, 0.8)
    )


def test_at_without_on_is_refused() -> None:
    """Refuse a position that names no line, for a device and a station."""
    fs = Flowsheet("No line")
    with pytest.raises(ValueError, match="on="):
        fs.add(Valve("HV-1"), at=0.5)
    with pytest.raises(ValueError, match="on="):
        fs.add_valve_station("CV-1", at=0.5)
    assert fs.units == []


@pytest.mark.parametrize("on_line", [True, False])
def test_a_refused_valve_station_leaves_the_sheet_unchanged(on_line: bool) -> None:
    """A member tag that clashes refuses the station after others are built."""
    fs = Flowsheet("Clash")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet)
    fs.add(Valve("HV-101A"))
    units, streams = [u.name for u in fs.units], [s.name for s in fs.streams]

    with pytest.raises(ValueError):
        fs.add_valve_station("CV-101", on=line if on_line else None)

    assert [u.name for u in fs.units] == units
    assert [s.name for s in fs.streams] == streams


def test_a_valve_station_on_a_line_takes_its_colour_and_dashes() -> None:
    """Draw a station's run, bypass and drains as the line it sits on."""
    fs = Flowsheet("Coloured")
    line = fs.connect(fs.add(Feed("F")).outlet, fs.add(Product("P")).inlet)
    line.color, line.dasharray = "blue", "4,2"
    other = fs.connect(fs.add(Feed("G")).outlet, fs.add(Product("Q")).inlet)
    coloured = fs.add_valve_station("CV-1", on=line)
    plain = fs.add_valve_station("CV-2", on=other)

    def drawn(station: ValveStation) -> set[tuple[str | None, str | None]]:
        """Return the colour and dashes of each line leaving a member."""
        return {(s.color, s.dasharray) for s in fs.streams if s.source.owner in station.members}

    assert drawn(coloured) == {("blue", "4,2")}
    assert drawn(plain) == {(None, None)}


@pytest.mark.parametrize("order", ["style-then-on", "on-then-style", "on-then-reload-then-style"])
def test_a_style_set_on_a_split_line_reaches_its_whole_run(order: str) -> None:
    """Draw every segment and station pipe of a line in the style set on it."""
    fs = Flowsheet("Styled")
    line = fs.connect(fs.add(Feed("F")).outlet, fs.add(Product("P")).inlet)
    other = fs.connect(fs.add(Feed("G")).outlet, fs.add(Product("Q")).inlet)
    if order == "style-then-on":
        line.color, line.dasharray = "blue", "4,2"
    fs.add(Valve("HV-1"), on=line)
    fs.add_valve_station("CV-1", on=line)
    station = fs.add_valve_station("CV-2", on=other)
    plain = [
        i
        for i, s in enumerate(fs.streams)
        if other is s or other is s._logical_root or s.source.owner in station.members
    ]
    if order == "on-then-reload-then-style":
        fs = Flowsheet.from_dict(fs.to_dict())
        line = fs.streams[0]
    if order != "style-then-on":
        line.color, line.dasharray = "blue", "4,2"

    drawn = [(s.color, s.dasharray) for s in fs.streams]
    assert {style for i, style in enumerate(drawn) if i not in plain} == {("blue", "4,2")}
    assert {style for i, style in enumerate(drawn) if i in plain} == {(None, None)}


def _recycle_loop(marked: bool) -> tuple[Flowsheet, Stream]:
    """Build a mixer, reactor and splitter loop and return its return line."""
    fs = Flowsheet("Recycle")
    feed, mixer = fs.add(Feed("F")), fs.add(Mixer("M", n_inlets=2))
    reactor, split = fs.add(Reactor("R")), fs.add(Splitter("S", n_outlets=2))
    fs.connect(feed.outlet, mixer.in_1)
    fs.connect(mixer.outlet, reactor.feed_1)
    fs.connect(reactor.outlet, split.inlet)
    fs.connect(split.out_1, fs.add(Product("P")).inlet)
    return fs, fs.connect(split.out_2, mixer.in_2, draw_as_recycle=marked)


@pytest.mark.parametrize("marked", [False, True], ids=["chosen by layout", "draw_as_recycle"])
def test_on_a_recycle_line_is_the_same_before_and_after_a_render(marked: bool) -> None:
    """Split a recycle line whether or not a render drew it as the recycle."""
    sheets = []
    for rendered in (False, True):
        fs, line = _recycle_loop(marked)
        if rendered:
            fs.to_svg()
        fs.add(Valve("HV-1"), on=line, at=0.6)
        fs.add_valve_station("FV-1", on=line, at=0.3)
        sheets.append(fs.to_dict())
        fs.to_svg(diagram="p&id")
        assert fs.validate(diagram="p&id") == []
        segments = [s for s in fs.streams if s is line or s._logical_root is line]
        assert [s.draw_as_recycle for s in segments] == [marked] * 3
        assert [s.is_recycle for s in segments] == [False, False, True]
        assert Flowsheet.from_dict(sheets[-1]).to_dict() == sheets[-1]
    assert sheets[0] == sheets[1]
