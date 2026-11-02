"""Check the two-pass layout: equipment by layered drawing, furniture on its pipes."""

from __future__ import annotations

import pytest

from _layout_cases import build as build_biodiesel
from pandid import Flowsheet, GravitySeparator, Product, Reactor, units as U
from pandid.layout.quality import measure_final
from pandid.portgeom import port_point
from pandid.geometry import Frame, Route
from pandid.routing.metrics import real_bends
from scripts import layout_quality, route_quality
from scripts.layout_compare import _fingerprint


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
