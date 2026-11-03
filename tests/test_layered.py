"""Check the two-pass layout: equipment by layered drawing, furniture on its pipes."""

from __future__ import annotations

import hashlib
import json

import pytest

from _layout_cases import build as build_biodiesel
from pandid import Block, Feed, Flowsheet, GravitySeparator, Product, Reactor
from pandid import devices as D, units as U
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point, resolve_port
from pandid.geometry import Frame, Route
from pandid.streams import Stream
from pandid.routing.metrics import real_bends
from scripts import layout_quality, route_quality


def _fingerprint(fs: Flowsheet) -> str:
    """Hash the resolved frames, port faces, routes, and convergence state.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed flowsheet.

    Returns
    -------
    str
        SHA-256 digest of the drawing geometry, rounded to six decimal places.
    """
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
    """Draw the same sheet from author intent and from a fresh build.

    Parameters
    ----------
    stem : str
        Example laid out with its placement stripped.

    Returns
    -------
    None
        Routing again, laying out again, and constructing anew agree.
    """
    fs, _ = layout_quality.build(stem, True)
    fs.layout()
    fs.route()
    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint
    fs.layout()
    fs.route()
    assert _fingerprint(fs) == fingerprint

    fresh, _ = layout_quality.build(stem, True)
    fresh.layout()
    fresh.route()
    assert _fingerprint(fresh) == fingerprint


@pytest.mark.parametrize("stem", ["04_control_loop", "10_ethanol_pfd"])
def test_route_report_uses_the_published_graph(stem: str) -> None:
    """Report route quality from the drawn routes.

    Parameters
    ----------
    stem : str
        Corpus drawing with its placement stripped.

    Returns
    -------
    None
        Reported excess bends agree with the published route geometry.
    """
    fs, _ = layout_quality.build(stem, True)
    report = route_quality.measure_sheet(fs, stem)
    excess = sum(
        max(0, row.actual_bends - row.min_bends)
        for row in report.rows
        if row.min_bends is not None and not row.is_manual
    )
    assert excess == measure_final(fs).excess_bends


def test_route_report_accepts_manual_intermediate_waypoints() -> None:
    """Count a manual route with one waypoint as drawn.

    Returns
    -------
    None
        The final route report does not count manual waypoints as undrawn.
    """
    fs, _ = layout_quality.build("11_ethanol_pid", False)
    report = route_quality.measure_sheet(fs, "11_ethanol_pid")
    assert report.undrawn == []


def _sealed_by_alignment(pinned: bool = False) -> tuple[Flowsheet, Frame, Frame, Route]:
    """Lay out a sheet where lining up S-2's feed with R-1's outlet can seal S-1's exit.

    Pinned at the sealed pixel positions, S-2 sits 9 px below S-1, inside
    the stub of S-1's connected underflow.

    Parameters
    ----------
    pinned : bool, optional
        Pin every unit at the sealed pixel positions instead of grid ranks.

    Returns
    -------
    tuple[Flowsheet, Frame, Frame, Route]
        The routed sheet, S-1's and S-2's frames and the underflow's route.
    """
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
    """Keep a separator's connected exit clear on a sheet pinned by grid rank.

    Returns
    -------
    None
        The underflow is routed clear, grid ranks hold, and a second route
        and a fresh build draw the same sheet.
    """
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
    """Keep pinned units where the author put them when an exit is sealed.

    Returns
    -------
    None
        Both separators stay on their pins and the blocked route is reported.
    """
    fs, upper, lower, underflow = _sealed_by_alignment(pinned=True)
    assert (upper.x, upper.y, lower.x, lower.y) == (232, 56, 232, 185)
    assert underflow.used_fallback
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_default_route_clears_the_unpinned_biodiesel_sheet() -> None:
    """Route the unpinned biodiesel sheet without a line through equipment.

    Returns
    -------
    None
        No stream uses the fallback and no hard conflict remains.
    """
    fs, _ = build_biodiesel(pinned=False)
    fs.route()

    quality = measure_final(fs)
    assert all(stream.route is not None and not stream.route.used_fallback for stream in fs.streams)
    assert not quality.hard_conflicts and not any(quality.hard)
    assert not any(issue.code == "route-crosses-unit" for issue in fs.validate())


@pytest.mark.parametrize("mirror", [None, "y", True])
def test_a_valve_on_an_upright_leg_runs_along_it(mirror: str | bool | None) -> None:
    """Turn an in-line valve to run along an upright pipe, mirror or not.

    A mirror states no turn, so it does not hold the valve level.

    Parameters
    ----------
    mirror : str or bool or None
        The valve's stated mirror, if any.

    Returns
    -------
    None
        Both nozzles sit on the pipe and neither segment jogs.
    """
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
    """Put a valve on a pipe that runs straight down from one tank into another.

    Parameters
    ----------
    valve : Valve
        Valve to put on the pipe.

    Returns
    -------
    tuple[Flowsheet, Valve]
        The sheet and the valve on it.
    """
    fs = Flowsheet("Upright line")
    top = fs.add(U.Tank("T-1"))
    bottom = fs.add(U.Tank("T-2")).nozzle("in_1", "N")
    line = fs.connect(top.ports["out_1"], bottom.ports["in_1"])
    return fs, fs.add(valve, on=line)


def test_a_stated_level_turn_holds_and_round_trips() -> None:
    """Keep a valve level on an upright pipe when its author stated a 0 turn.

    Returns
    -------
    None
        The stated 0 is drawn and written to a spec; an unstated turn is not
        written.
    """
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


def test_a_valve_with_a_stated_inlet_face_is_set_on_its_line() -> None:
    """Set a valve whose inlet face its author stated, skipping poses that lose it.

    Returns
    -------
    None
        The line routes and the valve's inlet is on the stated face.
    """
    fs = Flowsheet("Stated face")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet)
    valve = fs.add(U.Valve("HV-1").nozzle("inlet", "W"), on=line)
    fs.route()

    assert valve.frame is not None
    assert resolve_port(valve, valve.frame, "inlet").face == "W"
    assert not any(measure_final(fs).hard)


@pytest.mark.parametrize("pins", [((0, None), (1, None)), ((0, 1), (0, 0))])
def test_grid_pins_win_over_a_stack(pins: tuple[tuple[int, int | None], ...]) -> None:
    """Keep two blocks where their grid pins put them, though their pipe would stack them.

    A pipe from A's bottom to B's top stacks B under A, unless the author
    pinned them to different columns or B to a row above A's.

    Parameters
    ----------
    pins : tuple[tuple[int, int or None], ...]
        ``(col, row)`` pinned on A, then on B.

    Returns
    -------
    None
        B is drawn east of A, or above it, as pinned, and nothing is reported.
    """
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
    """Report two units drawn in the other order from their column pins.

    Returns
    -------
    None
        ``pin-not-honored`` names the pin the drawing does not keep.
    """
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
    """Return a sheet with one level line from a feed to a product.

    Returns
    -------
    tuple[Flowsheet, Stream]
        The sheet and its line.
    """
    fs = Flowsheet("Line")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    return fs, fs.connect(feed.outlet, product.inlet)


def test_a_stated_mirror_holds_on_a_line() -> None:
    """Keep the mirror its author stated on a control valve set on a line.

    Returns
    -------
    None
        The frame keeps the mirror and nothing is reported.
    """
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(orientation=0, mirrored=True), on=line)
    fs.route()

    assert valve.frame is not None and valve.frame.mirrored is True
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


def test_a_station_member_keeps_its_stated_turn() -> None:
    """Keep the turn its author stated on a station's control valve.

    Returns
    -------
    None
        The control valve is drawn at its stated turn and nothing is reported.
    """
    fs, line = _line()
    station = fs.add_valve_station("CV-101", on=line)
    assert station.control is not None
    station.control.pin(orientation=90)
    fs.route()

    assert station.control.frame is not None and station.control.frame.orientation == 90
    assert not [i for i in fs.validate() if i.code == "pin-not-honored"]


@pytest.mark.parametrize("port, face", [("outlet", "E"), ("inlet", "W")])
def test_a_stated_nozzle_face_is_kept_in_every_pose(port: str, face: str) -> None:
    """Set a control valve with a stated nozzle face on a line without raising.

    Parameters
    ----------
    port, face : str
        The nozzle and the face its author stated.

    Returns
    -------
    None
        The line routes and the nozzle is on its stated face.
    """
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").nozzle(port, face), on=line)
    fs.route()

    assert valve.frame is not None
    assert resolve_port(valve, valve.frame, port).face == face


def test_row_pins_order_a_whole_stack() -> None:
    """Keep row pins in order down a stack of three, not only between neighbours.

    Returns
    -------
    None
        C, pinned to row 0, is drawn above A, pinned to row 2, and nothing is
        reported.
    """
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


def test_a_stated_turn_drawn_otherwise_is_reported() -> None:
    """Report a unit drawn in another turn or mirror than its author stated.

    Returns
    -------
    None
        ``pin-not-honored`` names the turn and the mirror.
    """
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(orientation=0, mirrored=True), on=line)
    fs.layout()
    assert valve.frame is not None
    valve.frame.orientation, valve.frame.mirrored = 90, False

    said = " ".join(i.message for i in fs.validate() if i.code == "pin-not-honored")
    assert "orientation" in said and "mirror" in said


def test_a_turned_device_with_a_stated_face_is_set_on_its_line() -> None:
    """Set a turned control valve whose inlet face is stated for that turn.

    Returns
    -------
    None
        The line routes, the valve keeps its turn and its inlet is on N.
    """
    fs, line = _line()
    valve = fs.add(D.ControlValve("CV-1").pin(orientation=90).nozzle("inlet", "N"), on=line)
    fs.route()

    assert valve.frame is not None and valve.frame.orientation == 90
    assert resolve_port(valve, valve.frame, "inlet").face == "N"


@pytest.mark.parametrize("reverse", [False, True])
def test_side_draw_peers_follow_their_nozzle_heights(reverse: bool) -> None:
    """Draw the stripper on the higher side draw above the other (#460).

    Parameters
    ----------
    reverse : bool
        Add the lower draw's stripper first.

    Returns
    -------
    None
        The stripper on ``draw_1`` is drawn above the one on ``draw_2``.
    """
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
