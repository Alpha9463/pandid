"""Check the two-pass layout: equipment by layered drawing, furniture on its pipes."""

from __future__ import annotations

import hashlib
import json

import pytest

from _layout_cases import build as build_biodiesel, build_unpinned
from pandid import Block, Feed, Flowsheet, GravitySeparator, Product, Reactor
from pandid import devices as D, units as U
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point, resolve_port
from pandid.geometry import Frame, Route
from pandid.streams import Stream
from pandid.routing.metrics import real_bends


def _fingerprint(fs: Flowsheet) -> str:
    """Hash the resolved frames, port faces, routes, and convergence state."""
    geometry = {
        "units": [
            (
                u.name,
                None
                if u.frame is None
                else (
                    round(u.frame.x, 6),
                    round(u.frame.y, 6),
                    round(u.frame.w, 6),
                    round(u.frame.h, 6),
                    u.frame.col,
                    u.frame.row,
                    u.frame.orientation,
                    u.frame.mirrored,
                    u.frame.mirror_y,
                    u.frame.label_pos,
                    sorted(u.frame.port_faces.items()),
                ),
            )
            for u in fs.units
        ],
        "streams": [
            (
                s.name,
                None
                if s.route is None
                else (s.route.manual, [(round(x, 6), round(y, 6)) for x, y in s.route.waypoints]),
            )
            for s in fs.streams
        ],
        "converged": fs.route_converged,
    }
    encoded = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("stem", ["04_control_loop", "08_from_data", "16_demineralised_water"])
def test_layout_repeats_from_author_intent_and_fresh_builds(stem: str) -> None:
    """Draw the same sheet from author intent and from a fresh build."""
    fs, _ = build_unpinned(stem)
    fs.layout()
    fs.route()
    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint
    fs.layout()
    fs.route()
    assert _fingerprint(fs) == fingerprint

    fresh, _ = build_unpinned(stem)
    fresh.layout()
    fresh.route()
    assert _fingerprint(fresh) == fingerprint


def _sealed_by_alignment(pinned: bool = False) -> tuple[Flowsheet, Frame, Frame, Route]:
    """Lay out a sheet where lining up S-2's feed with R-1's outlet can seal S-1's exit."""
    fs = Flowsheet("Sealed exit")
    reactor = fs.add(Reactor("R-1"))
    upper = fs.add(GravitySeparator("S-1"))
    lower = fs.add(GravitySeparator("S-2"))
    drain = fs.add(Product("Drain"))
    if pinned:
        reactor.pin(x=50, y=50)
        upper.pin(x=232, y=56)
        lower.pin(x=232, y=185)
        drain.pin(x=432, y=91)
    else:
        reactor.pin(col=0, row=0)
        upper.pin(col=1, row=0)
        lower.pin(col=1, row=1)
        drain.pin(col=2, row=0)
    fs.connect(reactor.outlet, lower.feed)
    underflow = fs.connect(upper.underflow, drain.inlet)
    fs.route()
    assert upper.frame is not None and lower.frame is not None and underflow.route is not None
    return fs, upper.frame, lower.frame, underflow.route


def test_grid_pins_keep_a_connected_exit_clear() -> None:
    """Keep a separator's connected exit clear on a sheet pinned by grid rank."""
    fs, upper, lower, underflow = _sealed_by_alignment()
    assert not underflow.used_fallback
    assert not measure_final(fs).hard_conflicts
    assert lower.y - upper.y_max >= 25
    assert (upper.row, lower.row) == (0, 1)

    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint
    fresh = _sealed_by_alignment()[0]
    assert _fingerprint(fresh) == fingerprint


def test_pixel_pins_hold_when_an_exit_is_sealed() -> None:
    """Keep pinned units where the author put them when an exit is sealed."""
    fs, upper, lower, underflow = _sealed_by_alignment(pinned=True)
    assert (upper.x, upper.y, lower.x, lower.y) == (232, 56, 232, 185)
    assert underflow.used_fallback
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_default_route_clears_the_unpinned_biodiesel_sheet() -> None:
    """Route the unpinned biodiesel sheet without a line through equipment."""
    fs, _ = build_biodiesel(pinned=False)
    fs.route()

    quality = measure_final(fs)
    assert all(stream.route is not None and not stream.route.used_fallback for stream in fs.streams)
    assert not quality.hard_conflicts and not any(quality.hard)
    assert not any(issue.code == "route-crosses-unit" for issue in fs.validate())


@pytest.mark.parametrize("mirror", [None, "y", True])
def test_a_valve_on_an_upright_leg_runs_along_it(mirror: str | bool | None) -> None:
    """Turn an in-line valve to run along an upright pipe, mirror or not."""
    fs = Flowsheet("Upright valve")
    top = fs.add(U.Tank("T-1"))
    bottom = fs.add(U.Tank("T-2")).nozzle("in_1", "N")
    line = fs.connect(top.ports["out_1"], bottom.ports["in_1"])
    valve = U.Valve("HV-1")
    if mirror is not None:
        valve.pin(mirrored=mirror)
    fs.add(valve, on=line)
    fs.route()

    assert top.frame is not None and valve.frame is not None
    pipe_x = port_point(top, top.frame, "out_1")[0]
    assert valve.frame.orientation in (90, 270)
    for name in ("inlet", "outlet"):
        assert port_point(valve, valve.frame, name)[0] == pytest.approx(pipe_x)
    for stream in fs.streams:
        assert stream.route is not None
        assert real_bends(stream.route.waypoints) == 0


def _upright_line(valve: U.Valve) -> tuple[Flowsheet, U.Valve]:
    """Put a valve on a pipe that runs straight down from one tank into another."""
    fs = Flowsheet("Upright line")
    top = fs.add(U.Tank("T-1"))
    bottom = fs.add(U.Tank("T-2")).nozzle("in_1", "N")
    line = fs.connect(top.ports["out_1"], bottom.ports["in_1"])
    return fs, fs.add(valve, on=line)


def test_a_stated_level_turn_holds_and_round_trips() -> None:
    """Keep a valve level on an upright pipe when its author stated a 0 turn."""
    fs, valve = _upright_line(U.Valve("HV-1").pin(orientation=0))
    fs.route()
    assert valve.frame is not None and valve.frame.orientation == 0

    (entry,) = [u for u in fs.to_dict()["units"] if u["name"] == "HV-1"]
    assert entry["pin"]["orientation"] == 0
    again = Flowsheet.from_dict(fs.to_dict())
    again.route()
    (copy,) = [u for u in again.units if u.name == "HV-1"]
    assert copy.frame is not None and copy.frame.orientation == 0

    loose, free = _upright_line(U.Valve("HV-2").pin(mirrored="y"))
    (entry,) = [u for u in loose.to_dict()["units"] if u["name"] == "HV-2"]
    assert "orientation" not in entry["pin"]
    loose.route()
    assert free.frame is not None and free.frame.orientation in (90, 270)


@pytest.mark.parametrize("pins", [((0, None), (1, None)), ((0, 1), (0, 0))])
def test_grid_pins_win_over_a_stack(pins: tuple[tuple[int, int | None], ...]) -> None:
    """Keep two blocks where their grid pins put them, though their pipe would stack them."""
    fs = Flowsheet("Pinned stack")
    a = fs.add(Block("A", outputs=["S"]))
    b = fs.add(Block("B", inputs=["N"]))
    fs.connect(a.ports["out_1"], b.ports["in_1"])
    for unit, (col, row) in zip((a, b), pins):
        unit.pin(col=col, row=row)
    fs.route()

    assert a.frame is not None and b.frame is not None
    if pins[0][0] != pins[1][0]:
        assert b.frame.x >= a.frame.x_max
    else:
        assert b.frame.y_max <= a.frame.y
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_a_grid_pin_drawn_out_of_order_is_reported() -> None:
    """Report two units drawn in the other order from their column pins."""
    fs = Flowsheet("Swapped")
    a = fs.add(Block("A")).pin(col=0)
    b = fs.add(Block("B")).pin(col=1)
    fs.connect(a.ports["out_1"], b.ports["in_1"])
    fs.layout()
    assert a.frame is not None and b.frame is not None
    a.frame.x, b.frame.x = b.frame.x, a.frame.x

    found = [i for i in fs.validate() if i.code == "pin-not-honored"]
    assert found and "col" in found[0].message


def _line() -> tuple[Flowsheet, Stream]:
    """Return a sheet with one level line from a feed to a product."""
    fs = Flowsheet("Line")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    return fs, fs.connect(feed.outlet, product.inlet)


def test_a_stated_mirror_holds_on_a_line() -> None:
    """Keep the mirror its author stated on a control valve set on a line."""
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(mirrored=True), on=line)
    fs.route()

    assert valve.frame is not None and valve.frame.mirrored is True
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_a_station_member_keeps_its_stated_turn() -> None:
    """Keep the turn its author stated on a station's control valve."""
    fs, line = _line()
    station = fs.add_valve_station("CV-101", on=line)
    assert station.control is not None
    station.control.pin(orientation=90)
    fs.route()

    assert station.control.frame is not None and station.control.frame.orientation == 90
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


@pytest.mark.parametrize(
    "kind, port, face",
    [(U.Valve, "inlet", "W"), (D.ControlValve, "outlet", "E"), (D.ControlValve, "inlet", "W")],
)
def test_a_stated_nozzle_face_is_kept_in_every_pose(
    kind: type[U.Valve], port: str, face: str
) -> None:
    """Set a valve with a stated nozzle face on a line, skipping poses that lose it."""
    fs, line = _line()
    valve = fs.add(kind("V-1").nozzle(port, face), on=line)
    fs.route()

    assert valve.frame is not None
    assert resolve_port(valve, valve.frame, port).face == face
    assert not any(measure_final(fs).hard)


def test_row_pins_order_a_whole_stack() -> None:
    """Keep row pins in order down a stack of three, not only between neighbours."""
    fs = Flowsheet("Three")
    a = fs.add(Block("A", outputs=["S"])).pin(col=0, row=2)
    b = fs.add(Block("B", inputs=["N"], outputs=["S"]))
    c = fs.add(Block("C", inputs=["N"])).pin(col=0, row=0)
    fs.connect(a.ports["out_1"], b.ports["in_1"])
    fs.connect(b.ports["out_1"], c.ports["in_1"])
    fs.route()

    assert a.frame is not None and c.frame is not None
    assert c.frame.y_max <= a.frame.y
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


@pytest.mark.parametrize(
    "upper, out, lower, inlet",
    [
        (U.HeatExchanger("A"), "shell_out", U.HeatExchanger("B"), "shell_in"),
        (U.Feeder("A"), "discharge", U.Crusher("B"), "feed"),
        (U.Tank("A"), "out_1", U.Tank("B").nozzle("in_1", "N"), "in_1"),
        (U.Column("A"), "bottoms", U.Tank("B").nozzle("in_1", "N"), "in_1"),
        (U.Separator("A"), "liquid", U.Tank("B").nozzle("in_1", "N"), "in_1"),
    ],
)
def test_a_row_pin_between_two_stacking_units_holds(
    upper: U.Unit, out: str, lower: U.Unit, inlet: str
) -> None:
    """Draw a unit pinned between two units whose pipe would stack them."""
    fs = Flowsheet("Interleaved")
    a = fs.add(upper).pin(col=0, row=0)
    b = fs.add(lower).pin(col=0, row=2)
    c = fs.add(Block("C")).pin(col=0, row=1)
    fs.connect(a.ports[out], b.ports[inlet])
    fs.route()

    assert a.frame is not None and b.frame is not None and c.frame is not None
    assert a.frame.cy < c.frame.cy < b.frame.cy
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


@pytest.mark.parametrize("col", [None, 0])
def test_row_pins_hold_whether_or_not_a_stack_forms(col: int | None) -> None:
    """Keep row pins in order when the lower of two stacking units has a column pin or not."""
    fs = Flowsheet("Row pins")
    a = fs.add(Block("A", inputs=[], outputs=["S"])).pin(col=0, row=0)
    b = fs.add(Block("B", inputs=["N"], outputs=["E"])).pin(col=col, row=2)
    c = fs.add(Block("C", inputs=["W"], outputs=[])).pin(col=0, row=1)
    d = fs.add(Block("D", inputs=["W"], outputs=["E"])).pin(row=3)
    fs.connect(a.ports["out_1"], b.ports["in_1"])
    fs.connect(b.ports["out_1"], d.ports["in_1"])
    fs.connect(d.ports["out_1"], c.ports["in_1"])
    fs.route()

    assert a.frame is not None and b.frame is not None
    assert c.frame is not None and d.frame is not None
    if col is None:
        assert b.frame.cy < d.frame.cy
    else:
        assert a.frame.cy < c.frame.cy < b.frame.cy
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_row_only_pins_hold_beside_a_column_split_by_a_row_pin() -> None:
    """Keep two units pinned by row alone in order beside a column whose stack splits."""
    fs = Flowsheet("Mixed pins")
    a = fs.add(Block("A", inputs=[], outputs=["S"])).pin(col=0, row=0)
    b = fs.add(Block("B", inputs=["N"], outputs=["E"])).pin(col=0, row=2)
    c = fs.add(Block("C", inputs=[], outputs=["E"])).pin(col=0, row=1)
    d = fs.add(Block("D", inputs=["W"], outputs=[])).pin(row=3)
    e = fs.add(Block("E", inputs=["W"], outputs=[])).pin(row=4)
    fs.connect(a.ports["out_1"], b.ports["in_1"])
    fs.connect(b.ports["out_1"], d.ports["in_1"])
    fs.connect(c.ports["out_1"], e.ports["in_1"])
    fs.route()

    assert a.frame is not None and b.frame is not None and c.frame is not None
    assert d.frame is not None and e.frame is not None
    assert a.frame.cy < c.frame.cy < b.frame.cy
    assert d.frame.cy < e.frame.cy
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_a_stated_turn_drawn_otherwise_is_reported() -> None:
    """Report a unit drawn in another turn or mirror than its author stated."""
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(orientation=0, mirrored=True), on=line)
    fs.layout()
    assert valve.frame is not None
    valve.frame.orientation, valve.frame.mirrored = 90, False

    said = " ".join(i.message for i in fs.validate() if i.code == "pin-not-honored")
    assert "orientation" in said and "mirror" in said


def test_a_turned_device_with_a_stated_face_is_set_on_its_line() -> None:
    """Set a turned control valve whose inlet face is stated for that turn."""
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(orientation=90).nozzle("inlet", "N"), on=line)
    fs.route()

    assert valve.frame is not None and valve.frame.orientation == 90
    assert resolve_port(valve, valve.frame, "inlet").face == "N"


@pytest.mark.parametrize("reverse", [False, True])
def test_side_draw_peers_follow_their_nozzle_heights(reverse: bool) -> None:
    """Draw the stripper on the higher side draw above the other."""
    fs = Flowsheet("Crude")
    tower = fs.add(
        U.Column("T-101", internals="valve_tray", trays=30, n_draws=2, draw_stages=[10, 20])
    )
    upper, lower = U.Stripper("T-102"), U.Stripper("T-103")
    for stripper in (lower, upper) if reverse else (upper, lower):
        fs.add(stripper)
    fs.connect(tower.draw_1, upper.feed)
    fs.connect(tower.draw_2, lower.feed)
    fs.route()

    assert upper.frame is not None and lower.frame is not None
    assert upper.frame.y < lower.frame.y
