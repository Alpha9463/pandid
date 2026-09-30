"""Check endpoint and orthogonality invariants for routed flowsheets.

The corpus contains the gallery examples, author-built ethanol examples, and a
synthetic control-layout case. Stream paths and impulse lines must begin and
end at their intended ports and use orthogonal segments.
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

from _render_cases import copy_settled_case
from test_golden import SCENARIOS

TOL = 0.01
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# --- the corpus ---------------------------------------------------------------


def _crowded_taps() -> Flowsheet:
    """Build a control layout that needs more than two placement passes.

    Returns
    -------
    Flowsheet
        Routed-control fixture with two attached instruments.
    """
    fs = Flowsheet("Crowded Taps")
    feed = fs.add(units.Feed("F"))
    drum = fs.add(units.Vessel("V-1"))
    sep = fs.add(units.Separator("V-2"))
    prod = fs.add(units.Product("P"))
    # Tabulate boundary streams to isolate routing findings.
    fs.connect(feed.outlet, drum.inlet).properties = {"Flow (kg/h)": "4200"}
    transfer = fs.connect(drum.outlet, sep.feed)
    overhead = fs.connect(sep.vapor, prod.inlet)
    overhead.properties = {"Flow (kg/h)": "4200"}
    pt = fs.add_instrument("PT", 104, sensing=transfer, at=0.5, offset=60, angle=90)
    pic = fs.add_instrument("PIC", 101, sensing=overhead, at=0.3, offset=30, angle=90)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    return fs


def _example(stem: str) -> Flowsheet:
    """Build an author-written example without writing output files.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    Flowsheet
        Flowsheet captured from the example's ``main`` function.
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
AUTHOR_EXAMPLE_STEMS = ("10_ethanol_pfd", "11_ethanol_pid")
CORPUS["10_ethanol_pfd"] = lambda: _example("10_ethanol_pfd")
CORPUS["11_ethanol_pid"] = lambda: _example("11_ethanol_pid")
CORPUS["crowded_taps"] = _crowded_taps


@pytest.fixture(scope="module")
def routed(settled_gallery):
    """Return isolated routed sheets for the invariant corpus.

    The shared cache supplies ordinary gallery examples. The two ethanol
    examples and synthetic control-layout fixture remain fresh.

    Returns
    -------
    dict[str, Flowsheet]
        Routed flowsheets keyed by corpus name.
    """
    sheets = {}
    for name, build in CORPUS.items():
        if name in settled_gallery and name not in AUTHOR_EXAMPLE_STEMS:
            fs, _kwargs = copy_settled_case(settled_gallery, name)
        else:
            fs = build()
            fs.layout()
            fs.route()
        sheets[name] = fs
    return sheets


# --- the invariants -----------------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_route_endpoints_sit_on_their_ports(routed, name):
    """Place each automatically routed stream endpoint on its port anchor."""
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
    """Keep stream and impulse-line segments orthogonal."""
    fs = routed[name]
    sloping = []
    for s in fs.streams:
        points = stream_path(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if abs(x1 - x2) > TOL and abs(y1 - y2) > TOL:
                sloping.append(f"{s.name} runs ({x1:.0f}, {y1:.0f}) -> ({x2:.0f}, {y2:.0f})")
    # Check the impulse lines emitted by the renderer.
    for inst, (x1, y1), (x2, y2) in tap_lines(fs):
        if abs(x1 - x2) > TOL and abs(y1 - y2) > TOL:
            sloping.append(f"{inst.name}'s tap runs ({x1:.0f}, {y1:.0f}) -> ({x2:.0f}, {y2:.0f})")
    assert not sloping, f"{name}: " + "; ".join(sloping)


# Fixed-point routing


def test_two_placements_are_not_enough_for_a_crowded_sheet():
    """Keep the crowded control layout as a multi-pass regression case."""
    fs = _crowded_taps()
    fs.layout()
    router = DefaultRouter()
    router.route(fs)
    assert place_attached(fs) is True
    router.route(fs)
    assert place_attached(fs) is True, "a third placement is what the old two passes skipped"


def test_a_settled_sheet_says_so():
    """Mark a converged control layout as settled and validation-clean."""
    fs = _crowded_taps()
    fs.layout()
    fs.route()
    assert fs.route_converged is True
    assert fs.validate() == []


# Bounded non-convergence


class _WanderingRouter:
    """Router that alternates paths to force bounded non-convergence.

    Attributes
    ----------
    passes : int
        Number of route calls.
    """

    def __init__(self) -> None:
        """Initialize the route-call counter."""
        self.passes = 0

    def route(self, fs) -> None:
        """Assign alternating paths to every stream.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose streams receive routes.
        """
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
    """Cap non-convergent routing and report its validation warning."""
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
    """Expose a non-convergence warning through rendered-sheet warnings."""
    fs = _crowded_taps()
    fs.layout()
    fs.route(router=_WanderingRouter())
    fs.to_svg()
    assert "route-not-settled" in [w.code for w in fs.warnings]


def test_a_sheet_with_no_instruments_costs_one_routing_pass():
    """Route a sheet without attached instruments in one pass."""
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
