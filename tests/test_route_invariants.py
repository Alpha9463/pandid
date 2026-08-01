"""Invariants every routed sheet has to satisfy, over the whole shipped corpus.

Two properties, checked against the nine golden scenarios (which are examples
01-09 rebuilt), the two ethanol sheets (examples 10 and 11, the densest drawings
in the repo), and a synthetic sheet built here to be pathological:

**A stream's path begins and ends on its own nozzles.** The router writes the
port *anchors* as the first and last waypoint and the renderer draws
``port_point -> waypoints -> port_point``, so an endpoint that has drifted off
its anchor is a line whose stub no longer leaves the nozzle it belongs to.
(``via()`` states the intermediate points only, so a hand-routed line has no
endpoint of its own to check.)

**Nothing is drawn diagonally.** A P&ID line is orthogonal by convention, so a
sloping segment is never intentional. It is what stale geometry looks like on
the sheet: the line leaves one port, follows a path aimed at where the other end
used to be, and closes the gap with a diagonal.

The convention is not a house style. BS ISO 15519-1:2010 §12.1: "Connecting
lines shall be oriented horizontally or vertically, except in those cases where
oblique lines improve the clarity of the diagram", and §12.4: "Joining of
connecting lines shall be shown meeting or intersecting at right angles", with
no exception clause on the second. §12.1 names "conductors, functional
connections" alongside pipelines, BS ISO 15519-2:2015 §6.1 pulls Part 1's rules
into force on a P&ID, and its §5.1.1 calls an instrument's process tap a
"functional connection line" -- so the rule reaches the tap and not only the
pipe. The issued reference sheet ``professional_examples/P&ID_301.pdf`` draws 47
dashed signal segments, every one exactly horizontal or vertical, and no
diagonal connector of any kind.

So the second invariant sweeps the **impulse lines too**, and not just the
streams. A tap is drawn by :meth:`SvgRenderer._draw_taps` rather than by the
stream pass, and for as long as this file checked only ``fs.streams`` the line
that says *where* an instrument measures was the one line on the sheet exempt
from the rule the file is named for. Three shipped diagonals, and a fourth in
this file's own fixture, is what that exemption was worth (issue #155).

Both invariants are cheap. The defect they were written for (issue #71) was a
routing pass whose result nothing re-checked.
"""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from pandid import Flowsheet, units
from pandid.geometry import Route
from pandid.layout.attach import MAX_PLACEMENT_PASSES, place_attached, stream_path
from pandid.portgeom import port_anchor, port_point
from pandid.render.svg import tap_lines
from pandid.routing import DefaultRouter

from test_golden import SCENARIOS

TOL = 0.01
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# --- the corpus ---------------------------------------------------------------


def _crowded_taps() -> Flowsheet:
    """A sheet whose balloons and routes do not agree on the first try.

    Both balloons hang off automatically routed lines, so each one lands at a
    fraction along a path the router chose; the box it lands in is then an
    obstacle the *next* routing pass has to avoid, which moves the path, which
    moves the balloon. Settling it takes three placements, and the signal line
    between the two balloons is where a placement that is never re-routed shows
    up, since both of its endpoints are balloon nozzles.

    Minimised from a randomised search: four units and two instruments is the
    smallest sheet found that needs more than the two fixed passes
    :meth:`Flowsheet.route` used to run.

    Both branches are perpendicular, because this sheet is in the corpus the
    diagonal invariant runs over and a fixture that cannot satisfy an invariant
    it is checked against covers nothing. The controller was drawn at 45 degrees
    and its ``offset`` is what paid for squaring it: 40 at 90 degrees settles in
    two placements, and 30 is the nearest value searched that keeps the third
    that :func:`test_two_placements_are_not_enough_for_a_crowded_sheet` pins.
    """
    fs = Flowsheet("Crowded Taps")
    feed = fs.add(units.Feed("F"))
    drum = fs.add(units.Vessel("V-1"))
    sep = fs.add(units.Separator("V-2"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, drum.inlet)
    transfer = fs.connect(drum.outlet, sep.feed)
    overhead = fs.connect(sep.vapor, prod.inlet)
    pt = fs.add_instrument("PT", 104, on=transfer, at=0.5, offset=60, angle=90)
    pic = fs.add_instrument("PIC", 101, on=overhead, at=0.3, offset=30, angle=90)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    return fs


def _example(stem: str) -> Flowsheet:
    """Build an example's flowsheet without letting it write its drawing out.

    Examples 10 and 11 are not in the golden corpus and are the two densest
    sheets shipped, which is where a routing defect shows first. Their ``main()``
    ends in a ``render()``; that one call is stubbed so the flowsheet can be
    inspected without a test suite dropping files into ``examples/``.
    """
    sys.path.insert(0, str(EXAMPLES))  # the examples' own _bootstrap
    try:
        spec = importlib.util.spec_from_file_location(
            f"_invariants_{stem}", EXAMPLES / f"{stem}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(EXAMPLES))

    built: list[Flowsheet] = []
    original = Flowsheet.render
    Flowsheet.render = lambda self, *a, **k: built.append(self)  # type: ignore[method-assign]
    try:
        module.main()
    finally:
        Flowsheet.render = original  # type: ignore[method-assign]
    return built[0]


CORPUS: dict = {name: build for name, (build, _kwargs) in SCENARIOS.items()}
CORPUS["10_ethanol_pfd"] = lambda: _example("10_ethanol_pfd")
CORPUS["11_ethanol_pid"] = lambda: _example("11_ethanol_pid")
CORPUS["crowded_taps"] = _crowded_taps


@pytest.fixture(scope="module")
def routed():
    """Every shipped sheet, laid out and routed once, keyed by name."""
    sheets = {}
    for name, build in CORPUS.items():
        fs = build()
        fs.layout()
        fs.route()
        sheets[name] = fs
    return sheets


# --- the invariants -----------------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_route_endpoints_sit_on_their_ports(routed, name):
    fs = routed[name]
    off = []
    for s in fs.streams:
        if s.route is not None and s.route.manual:
            continue  # via() states the middle of the path, not its ends
        waypoints = list(s.route.waypoints) if s.route else []
        assert waypoints, f"{name}: stream {s.name} was not routed"
        src_u, dst_u = s.source.owner, s.dest.owner
        head = port_anchor(src_u, src_u.frame, s.source.name)[:2]
        tail = port_anchor(dst_u, dst_u.frame, s.dest.name)[:2]
        for end, waypoint, anchor, port in (
            ("leaves", waypoints[0], head, f"{src_u.name}.{s.source.name}"),
            ("reaches", waypoints[-1], tail, f"{dst_u.name}.{s.dest.name}"),
        ):
            gap = math.dist(waypoint, anchor)
            if gap > TOL:
                off.append(f"{s.name} {end} {port} {gap:.1f}px away from its anchor")
    assert not off, f"{name}: " + "; ".join(off)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_nothing_is_drawn_diagonally(routed, name):
    fs = routed[name]
    sloping = []
    for s in fs.streams:
        points = stream_path(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if abs(x1 - x2) > TOL and abs(y1 - y2) > TOL:
                sloping.append(f"{s.name} runs ({x1:.0f}, {y1:.0f}) -> ({x2:.0f}, {y2:.0f})")
    # The impulse line from a tap to the balloon reading it is drawn by a pass of
    # its own, so it has to be swept by name or it is exempt. ``tap_lines`` is
    # the renderer's own answer to which taps are drawn at all -- it drops the
    # ones a stream already joins and the ones sitting on the line at
    # ``offset=0`` -- so what is checked here is exactly what lands on the sheet.
    for inst, (x1, y1), (x2, y2) in tap_lines(fs):
        if abs(x1 - x2) > TOL and abs(y1 - y2) > TOL:
            sloping.append(f"{inst.name}'s tap runs ({x1:.0f}, {y1:.0f}) -> ({x2:.0f}, {y2:.0f})")
    assert not sloping, f"{name}: " + "; ".join(sloping)


# --- the specific defect the synthetic sheet was built for ---------------------


def test_two_placements_are_not_enough_for_a_crowded_sheet():
    """Guards the guard: ``crowded_taps`` only earns its place in the corpus
    while it still outruns the two fixed passes ``route()`` used to run. Should
    a routing change make it settle sooner, the invariant tests above would
    still pass on it while no longer covering anything, so say so here."""
    fs = _crowded_taps()
    fs.layout()
    router = DefaultRouter()
    router.route(fs)
    assert place_attached(fs) is True
    router.route(fs)
    assert place_attached(fs) is True, "a third placement is what the old two passes skipped"


def test_a_settled_sheet_says_so():
    fs = _crowded_taps()
    fs.layout()
    fs.route()
    assert fs.route_converged is True
    assert fs.validate() == []


# --- what happens when the passes run out -------------------------------------


class _WanderingRouter:
    """A router that answers differently every pass, so nothing can ever settle.

    Placement and routing feed each other, since a balloon is placed on a routed
    path and the box it lands in is an obstacle that bends paths, so a sheet can
    trade between two arrangements indefinitely. Real ones that do are
    fragile specimens that a routing improvement would quietly turn into
    converging ones, leaving the test passing and covering nothing. Driving the
    loop from a router that is *defined* not to settle pins the contract
    instead: bounded work, and the author told.
    """

    def __init__(self) -> None:
        self.passes = 0

    def route(self, fs) -> None:
        self.passes += 1
        jog = 40.0 if self.passes % 2 else 90.0
        for s in fs.streams:
            src_u, dst_u = s.source.owner, s.dest.owner
            if src_u.frame is None or dst_u.frame is None:
                continue
            a = port_point(src_u, src_u.frame, s.source.name)
            b = port_point(dst_u, dst_u.frame, s.dest.name)
            s.route = Route(waypoints=[a, (a[0], a[1] - jog), (b[0], a[1] - jog), b])


def test_a_sheet_that_never_settles_is_capped_and_reported():
    fs = _crowded_taps()
    fs.layout()
    router = _WanderingRouter()
    fs.route(router=router)

    assert router.passes == MAX_PLACEMENT_PASSES + 1  # the first, then one per pass
    assert fs.route_converged is False

    codes = [i.code for i in fs.validate()]
    assert "route-not-settled" in codes
    assert all(i.severity == "warning" for i in fs.validate() if i.code == "route-not-settled")


def test_the_unsettled_warning_reaches_the_caller_after_a_render():
    fs = _crowded_taps()
    fs.layout()
    fs.route(router=_WanderingRouter())
    fs.to_svg()
    assert "route-not-settled" in [w.code for w in fs.warnings]


def test_a_sheet_with_no_instruments_costs_one_routing_pass():
    """The loop must not make the common sheet pay for the pathological one."""
    fs = Flowsheet("plain")
    feed = fs.add(units.Feed("F"))
    drum = fs.add(units.Vessel("V-1"))
    prod = fs.add(units.Product("P"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    fs.layout()
    router = _WanderingRouter()
    fs.route(router=router)
    assert router.passes == 1
    assert fs.route_converged is True
