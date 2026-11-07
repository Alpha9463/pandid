"""Check control loops: final control elements and balloons with several signals."""

import math
from collections.abc import Callable

import pytest

from pandid import Flowsheet, units as U

from _layout_cases import build_unpinned, frame_of
from test_instruments import _centre, _hatch_marks, _line, _overlaps


# --- final control element ---------------------------------------------------


def test_controller_output_routes_to_the_valve_actuator():
    from pandid.layout.attach import stream_path
    from pandid.portgeom import port_point

    fs, _, ft, fv = _line(at=0.4, offset=60)
    fic = fs.add_instrument("FIC", 101, near=ft, face="N", offset=120, angle=35, display="central")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    sig = fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
    fs.route()
    end = port_point(fv, fv.frame, "actuator")
    drawn = stream_path(sig)
    assert drawn[0] == pytest.approx(port_point(fic, fic.frame, "sig_out"))
    assert drawn[-1] == pytest.approx(end)
    assert drawn[-2][0] == pytest.approx(end[0])  # arrives square onto the top
    # the actuator is on top of the valve, not on either process nozzle
    assert end[1] < frame_of(fv).cy
    assert frame_of(fv).x < end[0] < frame_of(fv).x_max
    assert _hatch_marks(fs.to_svg()) >= 2  # pneumatic slash ticks drawn


def _level_loop() -> tuple[Flowsheet, U.Instrument, U.Valve]:
    """Return a drum's level loop: LT-101 wired to a free LIC-101, and LV-101 on the outlet."""
    fs = Flowsheet("level")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-1"))
    lv = fs.add(U.Valve("LV-101", variant="control"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    lt = fs.add_instrument("LT", 101, sensing=drum)
    lic = fs.add_instrument("LIC", 101)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    return fs, lic, lv


def test_an_unanchored_controller_hangs_beyond_the_actuator_it_drives():
    """Check that a free controller hangs 100 out past the actuator, on its axis."""
    from pandid.portgeom import port_anchor

    fs, lic, lv = _level_loop()
    fs.connect(lic.sig_out, lv.actuator, kind="electric")
    fs.route()

    valve = frame_of(lv)
    ax, ay, face = port_anchor(lv, valve, "actuator")
    cx, cy = _centre(lic)
    beyond = {"N": valve.y - cy, "S": cy - valve.y_max, "W": valve.x - cx, "E": cx - valve.x_max}
    assert beyond[face] > 0, f"LIC-101 is not on the {face} side of LV-101"
    assert (cx if face in "NS" else cy) == pytest.approx(ax if face in "NS" else ay, abs=0.5)
    assert math.dist((cx, cy), (ax, ay)) == pytest.approx(100.0, abs=1.0)
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


def test_hanging_a_controller_off_its_valve_writes_nothing_into_the_model():
    """Check that hanging a controller writes nothing to the spec and repeats on relayout."""
    from pandid.portgeom import port_anchor

    fs, lic, lv = _level_loop()
    fs.connect(lic.sig_out, lv.actuator, kind="electric")
    spec = fs.to_dict()
    fs.layout()
    fs.route()

    ax, ay, _ = port_anchor(lv, frame_of(lv), "actuator")
    first = _centre(lic)
    assert math.dist(first, (ax, ay)) == pytest.approx(100.0, abs=1.0)
    assert lic.host is None
    assert fs.to_dict() == spec
    fs.layout()
    fs.route()
    assert _centre(lic) == pytest.approx(first)
    assert fs.to_dict() == spec


def test_a_controller_driving_no_actuator_is_not_hung():
    """Check that a controller driving a relay rather than the actuator gets no spot."""
    from pandid.layout.control import _hangable

    fs, lic, lv = _level_loop()
    ly = fs.add_instrument("LY", 101, near=lv, face="N")
    fs.connect(lic.sig_out, ly.sig_in, kind="electric")
    fs.connect(ly.sig_out, lv.actuator, kind="pneumatic")
    fs.route()

    assert _hangable(fs, lic) is None


def test_a_controller_too_big_for_the_actuator_spot_is_placed_free():
    """Check that a controller too big for the actuator spot is placed clear of the valve."""
    fs = Flowsheet("big")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add(U.Instrument("LIC", 1, width=600, height=600))
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert not _overlaps(lic, valve)
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


def test_a_controller_is_not_hung_across_a_pipe():
    """Check that a controller is not hung across a pipe through the actuator's standoff."""
    fs = Flowsheet("pipe")
    feed = fs.add(U.Feed("Feed")).pin(port="outlet", x=100, y=100)
    fv = fs.add(U.Valve("FV-1", variant="control")).pin(port="inlet", x=300, y=212.4)
    prod = fs.add(U.Product("Product")).pin(port="inlet", x=600, y=212.4)
    fs.connect(feed.outlet, fv.inlet).via([(400, 100), (400, 160), (275, 160), (275, 212.4)])
    fs.connect(fv.outlet, prod.inlet)
    fic = fs.add(U.Instrument("FIC", 1))
    fs.connect(fic.sig_out, fv.actuator, kind="electric")
    fs.route()

    assert "route-crosses-unit" not in {i.code for i in fs.validate()}


def test_a_controller_driving_two_actuators_reads_back_in_place():
    """Check that a controller driving two actuators reads back from the spec in place."""
    fs = Flowsheet("split")
    first = fs.add(U.Valve("FV-1", variant="control")).pin(x=100, y=300)
    second = fs.add(U.Valve("FV-2", variant="control")).pin(x=500, y=300)
    fic = fs.add(U.Instrument("FIC", 1))
    third_out = fic.signal_port("sig_out_3")
    fs.connect(fic.signal_port("sig_out_2"), second.actuator, kind="electric")
    fs.connect(third_out, first.actuator, kind="electric")
    fs.route()
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    rebuilt.route()

    (twin,) = [u for u in rebuilt.units if u.name == "FIC-1"]
    assert _centre(twin) == pytest.approx(_centre(fic))


def test_a_controller_hangs_from_the_actuators_own_point():
    """Check that a controller hangs square to an off-centre actuator."""
    from pandid.portgeom import port_anchor

    fs = Flowsheet("angle")
    valve = fs.add(U.Valve("V", variant="angle", width=198, height=198)).pin(x=300, y=300)
    lic = fs.add(U.Instrument("LIC", 1))
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    ax, ay, face = port_anchor(valve, frame_of(valve), "actuator")
    assert face == "N"
    assert abs(ax - frame_of(valve).cx) > 1.0, "the actuator has to be off the face's middle"
    assert _centre(lic) == pytest.approx((ax, ay - 100.0))


def _hung_controller() -> tuple[Flowsheet, U.Instrument, U.Valve]:
    """Return a free LIC-1 driving the actuator of a pinned valve."""
    fs = Flowsheet("review")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    return fs, lic, valve


def test_a_hung_controller_clears_a_balloon_pinned_after_it():
    """Check that a hung controller stands clear of a balloon pinned on its spot."""
    fs, lic, _ = _hung_controller()
    pi = fs.add_instrument("PI", 1).pin(x=300, y=178)
    fs.route()

    assert not _overlaps(lic, pi)


def test_a_hung_controller_clears_a_signal_line():
    """Check that a hung controller stands clear of a signal line through its spot."""
    fs, _, _ = _hung_controller()
    first = fs.add_instrument("XI", 1).pin(x=100, y=178)
    second = fs.add_instrument("XI", 2).pin(x=600, y=178)
    fs.connect(first.sig_out, second.sig_in, kind="electric").via([(200, 200), (500, 200)])
    fs.route()

    assert "route-crosses-unit" not in {i.code for i in fs.validate()}


def test_a_hung_controller_clears_a_tap_line():
    """Check that a hung controller stays off a tap line rising past the actuator."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, valve = _hung_controller()
    fs.route()
    fs.add_instrument("PI", 1, sensing=valve, face="N", offset=100)
    fs.layout()
    fs.route()

    box = unit_box(lic, frame_of(lic))
    lines = [tap_route(u, tap, centre) for u, tap, centre in tap_lines(fs)]
    assert lines, "PI-1 draws a tap line"
    for route in lines:
        assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_hung_controller_keeps_its_own_tap_line() -> None:
    """Check that a balloon tapped on a hung controller keeps its tap on the north face."""
    from pandid.portgeom import face_point

    fs, lic, _ = _hung_controller()
    pi = fs.add_instrument("PI", 1, sensing=lic, face="N", offset=100)
    fs.route()

    assert fs.route_converged
    assert pi.tap == pytest.approx(face_point(lic, frame_of(lic), "N")[0])


def test_a_unit_laid_out_again_keeps_off_a_controller_held_at_its_frozen_line() -> None:
    """Lay V-101 clear of FIC-101, held where S4 was frozen, when a pin moves the feed."""
    fs, _ = build_unpinned("03_control_loop")
    fs.route()
    line = next(s for s in fs.streams if s.name == "S4")
    assert line.route is not None
    line.via(list(line.route.waypoints))
    feed = next(u for u in fs.units if u.name == "Feed")
    assert feed.frame is not None
    feed.pin(port=None, x=feed.frame.x - 60, y=feed.frame.y)
    fs.route()
    found = fs.validate()
    assert [i.message for i in found if i.code == "unit-overlap"] == []
    assert [
        i.message
        for i in found
        if i.code in ("route-diagonal", "route-crosses-unit") and i.message.startswith("stream S4 ")
    ] == []


def test_a_hung_controller_clears_a_balloon_pinned_on_the_grid() -> None:
    """Check that a hung controller stands clear of a balloon pinned by grid rank."""
    fs = Flowsheet("grid")
    valve = fs.add(U.Valve("V", variant="control")).pin(col=0, row=0)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.add_instrument("PI", 1).pin(col=0, row=-1)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "unit-overlap"] == []


def test_a_controller_carrying_a_balloon_is_not_hung() -> None:
    """Check that a controller carrying a balloon is not hung across the valve."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, valve = _hung_controller()
    fs.add_instrument("PI", 1, sensing=lic, face="S", offset=140)
    fs.route()

    box = unit_box(valve, frame_of(valve))
    ((inst, tap, centre),) = tap_lines(fs)
    route = tap_route(inst, tap, centre)
    assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_controller_with_a_hand_routed_line_is_not_hung() -> None:
    """Check that a controller whose line is routed by hand is not hung on that line."""
    fs, lic, valve = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    line.via([(280, 200), (500, 200)])
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_a_controller_is_not_hung_where_its_line_passes_through_it_twice() -> None:
    """Check that hanging is refused where it adds a leg through the controller."""
    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    line.via([(100, 200), (500, 200)])
    fs.route()

    box, path = unit_box(lic, frame_of(lic)), stream_path(line)
    assert sum(segment_crosses_box(a, b, box) for a, b in zip(path, path[1:])) == 1


def test_a_hung_controllers_line_clears_a_balloon_on_the_actuator() -> None:
    """Check that a hung controller's line misses a balloon hung on the actuator face."""
    fs, _, valve = _hung_controller()
    fs.add_instrument("PI", 1, sensing=valve, face="N", offset=46)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_a_controller_with_a_balloon_on_its_line_is_not_hung() -> None:
    """Check that a controller with a balloon on its line is not hung over it."""
    fs = Flowsheet("inline")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=270)
    lic = fs.add_instrument("LIC", 1)
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.add_instrument("ZI", 1, sensing=signal, at=0.9, offset=0)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "unit-overlap"] == []


def test_a_controller_wired_from_behind_its_valve_is_not_hung() -> None:
    """Check that a controller wired from behind its valve is not hung across it."""
    fs = Flowsheet("behind")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=100, y=350, orientation=180)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=100, y=300)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def _close_transmitter() -> Flowsheet:
    """Return a free LIC-1 on a turned valve, with LT-1 pinned close by."""
    fs = Flowsheet("close")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=90)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=450, y=275)
    lt.nozzle("sig_out", face="N")
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    return fs


def _two_transmitters() -> Flowsheet:
    """Return a free LIC-1 that drives no actuator and reads two pinned transmitters."""
    fs = Flowsheet("no-actuator")
    fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lt1 = fs.add_instrument("LT", 1).pin(x=325, y=275)
    lt2 = fs.add_instrument("LT", 2).pin(x=325, y=325)
    fs.connect(lt1.sig_out, lic.sig_in, kind="electric")
    fs.connect(lt2.sig_out, lic.signal_port("sig_in_2"), kind="electric")
    return fs


def _cascade() -> Flowsheet:
    """Return LIC-1 and FIC-1 driving valves 50 apart and wired to each other."""
    fs = Flowsheet("cascade")
    va = fs.add(U.Valve("VA", variant="control")).pin(x=300, y=300)
    vb = fs.add(U.Valve("VB", variant="control")).pin(x=300, y=350)
    lic = fs.add_instrument("LIC", 1)
    fic = fs.add_instrument("FIC", 1)
    fs.connect(lic.sig_out, va.actuator, kind="electric")
    fs.connect(fic.sig_out, vb.actuator, kind="electric")
    fs.connect(lic, fic, kind="electric")
    return fs


def _crossed_cascade() -> Flowsheet:
    """Return two turned valves whose controllers are in cascade, with LT-1 and PI-1 nearby."""
    fs = Flowsheet("fallback")
    va = fs.add(U.Valve("VA", variant="control")).pin(x=300, y=500, orientation=270)
    vb = fs.add(U.Valve("VB", variant="control")).pin(x=350, y=550, orientation=90)
    lic = fs.add_instrument("LIC", 1)
    fic = fs.add_instrument("FIC", 1)
    fs.connect(lic.sig_out, va.actuator, kind="electric")
    fs.connect(fic.sig_out, vb.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=450, y=500)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.signal_port("sig_out_2"), fic.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=vb, face="S", offset=60)
    return fs


def _tap_past_a_transmitter() -> Flowsheet:
    """Return PI-1 hung off a turned valve near the LT-1 that LIC-1 reads."""
    fs = Flowsheet("tap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=180)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=250, y=350)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=valve, face="S", offset=100, angle=45)
    return fs


def _drawn_by_hand() -> Flowsheet:
    """Return a free LIC-1 whose line to the actuator is drawn by hand."""
    fs = Flowsheet("manual")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="E")
    fs.connect(lic.sig_out, valve.actuator, kind="electric").via(
        [(284.25, 234.9), (312.2, 234.9), (312.2, 275)]
    )
    return fs


def _balloon_on_a_signal_line() -> Flowsheet:
    """Return PI-1 on a signal line between two indicators near LIC-1's valve."""
    fs = Flowsheet("signal balloon")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=300, y=350)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    x1 = fs.add_instrument("XI", 1).pin(x=200, y=300)
    x2 = fs.add_instrument("XI", 2).pin(x=550, y=500)
    line = fs.connect(x1.sig_out, x2.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=line, at=0.5, offset=60)
    return fs


@pytest.mark.parametrize(
    "build",
    [
        _balloon_on_a_signal_line,
        _close_transmitter,
        _two_transmitters,
        _cascade,
        _crossed_cascade,
        _tap_past_a_transmitter,
        _drawn_by_hand,
    ],
)
def test_a_hung_controller_that_leaves_a_clash_is_placed_from_its_wiring(
    build: Callable[[], Flowsheet],
) -> None:
    """Check that a clash from hanging gives way to placing the controller from its wiring."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs = build()
    fs.route()

    codes = ("route-crosses-unit", "route-diagonal")
    assert [i.code for i in fs.validate() if i.severity == "error" or i.code in codes] == []
    for inst, tap, centre in tap_lines(fs):
        route = tap_route(inst, tap, centre)
        for u in fs.units:
            if u is inst or u is inst.host or u.frame is None:
                continue
            box = unit_box(u, u.frame)
            assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_router_that_freezes_its_routes_still_gets_the_fallback() -> None:
    """Check that a router freezing every route still gets a sheet with no slanted line."""
    from pandid.routing import DefaultRouter

    class FreezeRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for stream in fs.streams:
                assert stream.route is not None
                stream.route.manual = True

    fs, _, _ = _hung_controller()
    fs.route(FreezeRouter())

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_custom_router_routes_the_sheet_without_hanging() -> None:
    """Check that a router freezing only its straight routes leaves no slanted line."""
    from pandid.routing import DefaultRouter

    class FreezeStraightRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for stream in fs.streams:
                assert stream.route is not None
                if len({x for x, _ in stream.route.waypoints}) == 1:
                    stream.route.manual = True

    fs, _, _ = _hung_controller()
    fs.route(FreezeStraightRouter())

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_the_fallback_lays_out_with_an_engine_that_wraps_the_default() -> None:
    """Check that the fallback reruns an engine that wraps ``fs.layout()`` and moves a unit."""

    class WrappedEngine:
        def layout(self, fs: Flowsheet) -> None:
            fs.layout()
            assert marker.frame is not None
            marker.frame.x = marker.frame.y = 1200

    fs = _close_transmitter()
    marker = fs.add(U.Vessel("marker"))
    fs.layout(WrappedEngine())
    fs.route()

    assert marker.frame is not None
    assert (marker.frame.x, marker.frame.y) == (1200, 1200)


def test_a_router_that_refuses_the_hung_sheet_gets_the_fallback() -> None:
    """Check that a router raising on the hung sheet routes the unhung sheet instead."""
    from pandid.routing import DefaultRouter

    class CheckingRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for issue in fs.validate():
                if issue.code == "route-crosses-unit":
                    raise ValueError(issue.message)

    fs = _close_transmitter()
    fs.route(CheckingRouter())

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_the_fallback_keeps_an_engine_that_refines_the_layout() -> None:
    """Check that a refining engine is not rerun and the sheet routes without errors."""

    class SnapToGrid:
        def layout(self, fs: Flowsheet) -> None:
            for u in fs.units:
                assert u.frame is not None
                u.frame.x = round(u.frame.x)

    fs = _close_transmitter()
    fs.layout()
    fs.layout(SnapToGrid())
    fs.route()

    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_a_hung_controller_keeps_out_of_a_tag_halo() -> None:
    """Check that a hung controller stays out of a nearby tag's halo."""
    from pandid.layout.control import _halos
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    fs.add(U.Pump("P-101", width=44, height=44, label_pos="left")).pin(x=350, y=178)
    fs.route()

    box = unit_box(lic, frame_of(lic))
    for left, top, right, bottom in _halos(fs):
        assert not (box[0] < right and left < box[2] and box[1] < bottom and top < box[3])


def test_the_fallback_starts_from_the_settled_state_it_saved() -> None:
    """Check that a router reading ``route_converged`` sees the pre-hanging value."""
    from pandid.routing import DefaultRouter

    class CheckingRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            if any(i.code == "route-not-settled" for i in fs.validate()):
                raise ValueError("unsettled")

    fs, _, _ = _hung_controller()
    fs.route(CheckingRouter())

    assert fs.route_converged


def test_a_line_drawn_by_hand_before_routing_keeps_its_controller_unhung() -> None:
    """Check that a line drawn by hand to the free controller stays square over two routes."""
    fs, lic, valve = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    line.via([(284.25, 234.9), (312.2, 234.9), (312.2, 275)])
    for _ in range(2):
        fs.route()

        assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_hung_controllers_line_keeps_out_of_a_tag_halo() -> None:
    """Check that a controller's line routes round a tag lying across it."""
    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.layout.control import _halos

    fs, lic, _ = _hung_controller()
    fs.add(U.Vessel("P-101", width=80, height=20, label_pos="left")).pin(x=330, y=235)
    fs.route()

    line = lic.sig_out.stream
    assert line is not None
    points = stream_path(line)
    for halo in _halos(fs):
        assert not any(segment_crosses_box(a, b, halo) for a, b in zip(points, points[1:]))


def test_a_hung_line_frozen_with_via_is_drawn_as_frozen() -> None:
    """Check that a hung line frozen with ``via()`` stays square on the next route."""
    fs, lic, _ = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    fs.route()
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_balloon_moved_by_hanging_keeps_out_of_a_tag_halo() -> None:
    """Check that a hung controller and the balloon it moves stay out of a tag halo."""
    from pandid.layout.control import _halos
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    xi = fs.add_instrument("XI", 1)
    fs.connect(lic.signal_port("sig_out_2"), xi.sig_in, kind="electric")
    fs.add(U.Pump("P-101-ABCDEF", width=44, height=44, label_pos="left")).pin(x=350, y=103)
    fs.route()

    for unit in (lic, xi):
        box = unit_box(unit, frame_of(unit))
        for left, top, right, bottom in _halos(fs):
            assert not (box[0] < right and left < box[2] and box[1] < bottom and top < box[3])


def test_a_route_drawn_by_hand_and_then_cleared_stays_cleared() -> None:
    """Check that a hand-drawn route cleared after a hung route stays cleared."""
    fs, _, _ = _hung_controller()
    feed = fs.add(U.Feed("Feed")).pin(x=100, y=700)
    prod = fs.add(U.Product("Product")).pin(x=600, y=700)
    pipe = fs.connect(feed.outlet, prod.inlet).via([(200, 700), (200, 600), (500, 600), (500, 700)])
    fs.route()
    pipe.route = None
    fs.route()

    assert "via" not in fs.to_dict()["streams"][-1]


def test_a_copied_sheet_routes_from_its_own_unhung_state() -> None:
    """Check that a deep copy of a hung sheet keeps a line frozen on it square."""
    import copy

    fs, _, _ = _hung_controller()
    fs.route()
    fs = copy.deepcopy(fs)
    line = fs.streams[0]
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_balloon_added_after_hanging_is_laid_out_from_the_unhung_sheet() -> None:
    """Check that a balloon added after hanging settles with its tap on the line."""
    from pandid.layout.attach import stream_path

    fs, lic, _ = _hung_controller()
    signal = lic.sig_out.stream
    assert signal is not None
    fs.route()
    pi = fs.add_instrument("PI", 1, sensing=signal, at=0.1, offset=30)
    fs.route()

    assert fs.route_converged
    assert pi.tap is not None
    x, y = pi.tap

    def gap(a: tuple[float, float], b: tuple[float, float]) -> float:
        near_x = min(max(x, min(a[0], b[0])), max(a[0], b[0]))
        near_y = min(max(y, min(a[1], b[1])), max(a[1], b[1]))
        return math.hypot(x - near_x, y - near_y)

    points = stream_path(signal)
    assert min(gap(a, b) for a, b in zip(points, points[1:])) < 0.5


def test_hanging_adds_no_tap_line_through_a_tag_halo() -> None:
    """Check that hanging puts no tap line through a tag halo."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.layout.control import _halos
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, _ = _hung_controller()
    xi = fs.add_instrument("XI", 1)
    fs.connect(lic.signal_port("sig_out_2"), xi.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=xi, face="N", offset=100)
    fs.add(U.Pump("P-101", width=44, height=44, label_pos="left")).pin(x=275, y=28)
    fs.route()

    for inst, tap, centre in tap_lines(fs):
        route = tap_route(inst, tap, centre)
        for halo in _halos(fs):
            assert not any(segment_crosses_box(a, b, halo) for a, b in zip(route, route[1:]))


def test_hanging_lays_no_line_along_another() -> None:
    """Check that a hung controller's line does not run along a hand-drawn pipe."""
    from pandid.layout.attach import stream_path
    from pandid.layout.control import _shared

    fs = Flowsheet("coincident")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=265)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=265)
    pipe = fs.connect(feed.outlet, prod.inlet).via(
        [(312.2, 265), (312.2, 275), (500, 275), (500, 265)]
    )
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp, pp = stream_path(signal), stream_path(pipe)
    assert not any(_shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(pp, pp[1:]))


def test_hanging_lays_no_line_along_a_tap_line() -> None:
    """Check that a hung controller's line does not run along a tap line."""
    from pandid.layout.attach import stream_path
    from pandid.layout.control import _shared
    from pandid.render.svg import tap_lines, tap_route

    fs = Flowsheet("tap overlap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=270)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=270)
    pipe = fs.connect(feed.outlet, prod.inlet)
    fs.add_instrument("PI", 1, sensing=pipe, at=0.4244, offset=140, angle=10)
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp = stream_path(signal)
    for inst, tap, centre in tap_lines(fs):
        tp = tap_route(inst, tap, centre)
        assert not any(_shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(tp, tp[1:]))


def test_hanging_lays_no_line_along_a_pipe_with_rounding_in_its_track() -> None:
    """Check that a pipe track with rounding still counts as shared with the line."""
    from pandid.layout.attach import stream_path

    def shared(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
        d: tuple[float, float],
    ) -> bool:
        if max(abs(a[0] - b[0]), abs(c[0] - d[0]), abs(a[0] - c[0])) >= 1:
            return False
        low = max(min(a[1], b[1]), min(c[1], d[1]))
        return min(max(a[1], b[1]), max(c[1], d[1])) - low > 1

    fs = Flowsheet("overlap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(x=100, y=265)
    prod = fs.add(U.Product("P")).pin(x=600, y=265)
    pipe = fs.connect(feed.outlet, prod.inlet).via(
        [(312.2, 265), (312.1 + 0.1, 275), (500, 275), (500, 265)]
    )
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp, pp = stream_path(signal), stream_path(pipe)
    assert not any(shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(pp, pp[1:]))


def test_an_engine_that_routes_and_then_adjusts_keeps_its_adjustment() -> None:
    """Check that an engine routing inside ``layout()`` keeps its later move."""
    fs, _, _ = _hung_controller()
    marker = fs.add(U.Vessel("marker"))

    class Engine:
        def layout(self, fs: Flowsheet) -> None:
            fs.layout()
            fs.route()
            assert marker.frame is not None
            marker.frame.x = marker.frame.y = 1200

    fs.layout(Engine())
    fs.route()

    assert marker.frame is not None
    assert (marker.frame.x, marker.frame.y) == (1200, 1200)


def _valve_variants() -> list[str]:
    """Return every registered valve variant."""
    from pandid.render.symbols import default_registry

    return sorted(v for kind, v in default_registry._symbols if kind == "valve")


def test_no_valve_variant_draws_its_actuator_inside_the_body():
    """Check that every valve variant draws its actuator at its routing anchor."""
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_port, resolve_size

    inside = []
    for variant in _valve_variants():
        valve = U.Valve("V-1", variant=variant)
        w, h = resolve_size(valve)
        drawn = resolve_port(valve, Frame(x=0.0, y=0.0, w=w, h=h), "actuator")
        if drawn.point != drawn.anchor:
            inside.append(variant)
    assert inside == []


def test_flipping_a_valve_turns_its_actuator_over_with_it():
    """Check that mirroring a valve top to bottom moves its actuator to the far face."""
    from pandid.portgeom import port_faces

    for variant in _valve_variants():
        valve = U.Valve("V-1", variant=variant).pin(mirrored="y")
        # The PSV's pilot connection is on the side of its bonnet, and a
        # top-to-bottom flip leaves an east face where it was.
        want = "E" if variant == "relief" else "S"
        assert port_faces(valve, "actuator") == [want], variant


def test_relief_valve_is_tagged_as_plain_text_beside_the_symbol():
    fs = Flowsheet("psv")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    psv = fs.add(U.Valve("PSV-308", variant="relief")).pin(x=221, y=20)
    flare = fs.add(U.Product("Flare")).pin(x=400, y=25)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)
    svg = fs.to_svg()
    assert ">PSV-308<" in svg  # the whole tag, not letters over a number
    assert frame_of(psv).label_pos in ("left", "right")  # beside the symbol


def test_hanger_is_not_drawn_where_a_signal_already_joins_the_pair():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    # sensing= and not near=, deliberately: what this asserts is that the
    # *signal* is what suppresses the hanger, so the balloon has to be one
    # that would otherwise be joined to its host by a line.
    fic = fs.add_instrument(
        "FIC", 101, sensing=ft, face="N", offset=110, angle=35, display="central"
    )
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    # Count only lines that start a text line; a balloon's own bar is nested in its symbol.
    taps = [
        ln
        for ln in fs.to_svg().split("\n")
        if ln.strip().startswith("<line") and 'stroke-width="1"' in ln
    ]
    assert len(taps) == 1  # the transmitter's impulse line, not a second FT-FIC line


def test_interlock_hangs_off_its_controller_on_a_dashed_line():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    fs.add_instrument("I", 1, sensing=ft, face="S", offset=44, variant="logic")
    taps = [ln for ln in fs.to_svg().split("\n") if "<line" in ln and 'stroke-width="1"' in ln]
    assert any("stroke-dasharray" in ln for ln in taps)  # instrument host -> dashed
    assert any("stroke-dasharray" not in ln for ln in taps)  # process tap -> solid


# --- the signal pool: several connections on one balloon ----------------------


def _split_range():
    """Return loop 301: one controller on two control valves, pinned."""
    fs = Flowsheet("split range")
    loop = fs.add_loop("P", 301)
    pt = fs.add(U.Instrument("PT", 301)).pin(x=120, y=300)
    pic = fs.add(U.Instrument("PIC", 301, variant="shared")).pin(x=340, y=300)
    cv1 = fs.add(U.Valve("CV-301-1", variant="control")).pin(x=320, y=520)
    cv2 = fs.add(U.Valve("CV-301-2", variant="control")).pin(x=600, y=280)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    lo = fs.connect(pic.sig_out, cv1.actuator, kind="pneumatic")
    hi = fs.connect(pic.sig_out, cv2.actuator, kind="pneumatic")
    return fs, loop, pt, pic, (cv1, lo), (cv2, hi)


def test_split_range_draws_one_controller_onto_two_valves():
    """Check that one controller draws two outputs onto two valve stems."""
    from pandid.portgeom import port_point

    fs, _, _, pic, (cv1, lo), (cv2, hi) = _split_range()
    assert lo.source.owner is pic and lo.dest is cv1.actuator
    assert hi.source.owner is pic and hi.dest is cv2.actuator
    assert lo.source is not hi.source
    fs.route()
    # Two lines off one balloon leave from two different points on it, which is
    # the whole of what "several connections, on any face" has to mean.
    assert port_point(pic, pic.frame, lo.source.name) != port_point(pic, pic.frame, hi.source.name)
    svg = fs.to_svg()
    assert ">PIC<" in svg and ">301<" in svg
    assert svg.count("<path") >= 3  # the measurement and both outputs


def test_a_second_line_off_one_output_is_another_connection():
    """Check that a second line off ``sig_out`` mints ``sig_out_2`` and leaves the first."""
    _, _, _, pic, (_, lo), (_, hi) = _split_range()
    assert lo.source is pic.sig_out
    assert pic.sig_out.stream is lo
    assert hi.source.name == "sig_out_2"
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]


def test_a_balloon_with_one_line_each_way_grows_nothing():
    """Check that a balloon with one line each way keeps its three ports."""
    fs = Flowsheet("plain")
    a = fs.add(U.Instrument("FT-101"))
    b = fs.add(U.Instrument("FIC-101", display="central"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    assert list(a.ports) == ["pv", "sig_in", "sig_out"]
    assert list(b.ports) == ["pv", "sig_in", "sig_out"]


def test_a_minted_connection_is_drawn_on_the_balloons_own_nozzle():
    """Check that a minted port is anchored and offers the pool's four faces."""
    from pandid.portgeom import is_anchored, port_faces

    _, _, _, pic, _, _ = _split_range()
    assert is_anchored(pic, "sig_out_2")
    assert set(port_faces(pic, "sig_out_2")) == set(port_faces(pic, "sig_out"))
    assert set(port_faces(pic, "sig_out_2")) == {"N", "S", "E", "W"}


def test_each_output_takes_a_face_of_its_own():
    """Check that a balloon's three connections resolve to three faces."""
    from pandid.portgeom import resolve_port
    from pandid.validate import validate

    fs, _, _, pic, _, _ = _split_range()
    fs.route()
    faces = {
        name: resolve_port(pic, pic.frame, name).face for name in ("sig_in", "sig_out", "sig_out_2")
    }
    assert len(set(faces.values())) == 3, faces
    assert not [i for i in validate(fs) if i.code == "coincident-ports"]


def test_a_measurement_feeds_two_alarms_on_separate_lines():
    """Check that a measurement feeding two alarms takes two outputs."""
    fs = Flowsheet("alarms")
    li = fs.add(U.Instrument("LI", 322, variant="shared")).pin(x=200, y=300)
    lah = fs.add(U.Instrument("LAH", 322, variant="shared")).pin(x=420, y=200)
    lal = fs.add(U.Instrument("LAL", 322, variant="shared")).pin(x=420, y=400)
    high = fs.connect(li.sig_out, lah.sig_in, kind="electric")
    low = fs.connect(li.sig_out, lal.sig_in, kind="electric")
    assert high.source is not low.source
    assert {high.source.name, low.source.name} == {"sig_out", "sig_out_2"}
    fs.route()
    assert fs.to_svg()


def test_an_alarm_takes_an_input_and_an_output():
    """Check that an alarm takes a line in and a line out."""
    fs = Flowsheet("trip")
    lt = fs.add(U.Instrument("LT", 322)).pin(x=120, y=300)
    lal = fs.add(U.Instrument("LAL", 322, variant="shared")).pin(x=360, y=300)
    trip = fs.add(U.Instrument("I", 1, variant="sis")).pin(x=600, y=300)
    into = fs.connect(lt.sig_out, lal.sig_in, kind="electric")
    out = fs.connect(lal.sig_out, trip.sig_in, kind="electric")
    assert lal.sig_in.stream is into and into.source.owner is lt
    assert lal.sig_out.stream is out and out.dest.owner is trip


def test_a_signal_connection_takes_either_end_of_its_line():
    """Check that a signal port may be either end of a signal line."""
    fs = Flowsheet("either end")
    a = fs.add(U.Instrument("LAL-322", variant="shared"))
    b = fs.add(U.Instrument("I-1", variant="sis"))
    # ``sig_in`` as the source: named for the author's reading, not enforced.
    s = fs.connect(a.sig_in, b.sig_in, kind="electric")
    assert s.source is a.sig_in and s.dest is b.sig_in
    assert s.source.direction == "inlet"  # the field is a label, not a rule


def test_a_process_nozzle_still_has_a_direction():
    """Check that a pipe drawn against a nozzle's direction is still refused."""
    fs = Flowsheet("piping")
    p1 = fs.add(U.Pump("P-101"))
    p2 = fs.add(U.Pump("P-102"))
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(p1.suction, p2.discharge)
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(p1.discharge, p2.discharge)


def test_the_process_tap_is_one_tap():
    """Check that a second line onto an instrument's ``pv`` is refused."""
    fs = Flowsheet("tap")
    fic = fs.add(U.Instrument("FIC-301", variant="shared"))
    a = fs.add(U.Instrument("FT-301"))
    b = fs.add(U.Instrument("FT-302"))
    fs.connect(a.sig_out, fic.pv, kind="electric")
    with pytest.raises(ValueError, match=r"FIC-301\.pv is already connected"):
        fs.connect(b.sig_out, fic.pv, kind="electric")


def test_a_valve_has_one_actuator():
    """Check that a second line onto a valve's actuator is refused."""
    fs = Flowsheet("stem")
    cv = fs.add(U.Valve("CV-301-1", variant="control"))
    a = fs.add(U.Instrument("PIC-301", variant="shared"))
    b = fs.add(U.Instrument("HIC-301", variant="shared"))
    fs.connect(a.sig_out, cv.actuator, kind="pneumatic")
    with pytest.raises(ValueError, match=r"CV-301-1\.actuator is already connected"):
        fs.connect(b.sig_out, cv.actuator, kind="pneumatic")


def test_split_range_survives_a_round_trip_through_a_spec():
    """Check that a minted port round-trips through the spec."""
    fs, *_ = _split_range()
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    pic = next(u for u in rebuilt.units if u.name == "PIC-301")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]
    assert rebuilt.to_dict() == spec
