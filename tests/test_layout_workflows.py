"""Hold automatic drawing quality on a small behavioural corpus."""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

import pytest

from _layout_cases import build as build_biodiesel, build_unpinned
from pandid import Flowsheet, units as U
from pandid.layout.quality import _HARD_CODES, measure_final
from pandid.portgeom import pin_intent, port_point

#: Allowance on a budgeted extent, as a fraction of it.
EXTENT_SLACK = 0.01

#: Labels for ``Quality.hard``, in its order.
HARD_LABELS = ("validation errors", "fallback routes", *_HARD_CODES, "undrawn streams")


class Budget(NamedTuple):
    """Upper limits for one scenario's drawing."""

    crossings: int
    width: float
    height: float


def _simple_chain() -> tuple[Flowsheet, dict]:
    """Build a feed, pump, exchanger and product in one line."""
    fs = Flowsheet("Simple chain")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-101"))
    exchanger = fs.add(U.HeatExchanger("E-101"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, exchanger.tube_in)
    fs.connect(exchanger.tube_out, product.inlet)
    return fs, {}


def _pixel_anchors() -> tuple[Flowsheet, dict]:
    """Build a free pump between two flags pinned in pixels."""
    fs = Flowsheet("Pixel anchors")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-101"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    feed.pin(x=100, y=400)
    product.pin(x=700, y=400)
    return fs, {}


def _biodiesel(**options) -> Callable[[], tuple[Flowsheet, dict]]:
    """Return a builder for one variant of the biodiesel sheet."""
    return lambda: (build_biodiesel(**options)[0], {})


def _long_chain() -> tuple[Flowsheet, dict]:
    """Build twelve pump and exchanger pairs in one line, too wide for one band."""
    fs = Flowsheet("Long chain")
    port = fs.add(U.Feed("Feed")).outlet
    for i in range(101, 113):
        pump = fs.add(U.Pump(f"P-{i}"))
        exchanger = fs.add(U.HeatExchanger(f"E-{i}"))
        fs.connect(port, pump.suction)
        fs.connect(pump.discharge, exchanger.tube_in)
        port = exchanger.tube_out
    fs.connect(port, fs.add(U.Product("Product")).inlet)
    return fs, {}


def _stripped(stem: str) -> Callable[[], tuple[Flowsheet, dict]]:
    """Return a builder for a shipped example with its placement pins removed."""
    return lambda: build_unpinned(stem)


SCENARIOS: dict[str, tuple[Callable[[], tuple[Flowsheet, dict]], Budget]] = {
    "simple chain": (_simple_chain, Budget(0, 656, 87)),
    "pixel anchors": (_pixel_anchors, Budget(0, 736, 67)),
    "biodiesel as authored": (_biodiesel(), Budget(9, 1981, 1254)),
    "biodiesel with one pin removed": (_biodiesel(skip="s103"), Budget(7, 1981, 1254)),
    "biodiesel automatic": (_biodiesel(pinned=False), Budget(20, 1998, 942)),
    # Four of the 13 crossings are a station bypass under its own controller's signal.
    "ethanol P&ID automatic": (_stripped("10_ethanol_pid"), Budget(13, 2588, 1992)),
    # The layered engine keeps one band up to 3200 px wide.
    "molecular sieve automatic": (_stripped("19_molecular_sieve_dryer"), Budget(32, 2903, 1822)),
    # Measured on the three sheets the alumina refinery is drawn on.
    "alumina digestion automatic": (_stripped("20_alumina_refinery_1"), Budget(4, 2901, 418)),
    "alumina clarification automatic": (_stripped("20_alumina_refinery_2"), Budget(4, 1487, 422)),
    "alumina precipitation automatic": (_stripped("20_alumina_refinery_3"), Budget(10, 2329, 910)),
    # 4690 px drawn in one band, so it meets the width budget only folded into two.
    "long chain folded": (_long_chain, Budget(0, 3040, 534)),
}


def _extent(fs: Flowsheet) -> tuple[float, float]:
    """Measure the width and height spanned by every unit frame."""
    frames = [unit.frame for unit in fs.units if unit.frame is not None]
    return (
        max(frame.x_max for frame in frames) - min(frame.x for frame in frames),
        max(frame.y_max for frame in frames) - min(frame.y for frame in frames),
    )


def _drawing(fs: Flowsheet) -> tuple[object, ...]:
    """Snapshot the resolved frames, port faces, routes and convergence."""
    units = tuple(
        (
            unit.name,
            None
            if unit.frame is None
            else (
                unit.frame.x,
                unit.frame.y,
                unit.frame.w,
                unit.frame.h,
                unit.frame.col,
                unit.frame.row,
                unit.frame.orientation,
                unit.frame.mirrored,
                unit.frame.mirror_y,
                unit.frame.label_pos,
                tuple(sorted(unit.frame.port_faces.items())),
            ),
        )
        for unit in fs.units
    )
    routes = tuple(
        (
            stream.name,
            None
            if stream.route is None
            else (stream.route.manual, tuple(map(tuple, stream.route.waypoints))),
        )
        for stream in fs.streams
    )
    return units, routes, fs.route_converged


def _unhonoured_pins(fs: Flowsheet) -> list[str]:
    """List the pixel pins that the drawing does not keep."""
    missed = []
    for unit in fs.units:
        for axis, (port, value) in pin_intent(unit).items():
            assert unit.frame is not None
            point = (
                port_point(unit, unit.frame, port)
                if port is not None
                else (unit.frame.x, unit.frame.y)
            )
            drawn = point[0 if axis == "x" else 1]
            if abs(drawn - value) > 0.5:
                missed.append(f"{unit.name} {axis}={value} drawn at {drawn:.1f}")
    return missed


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_meets_invariants_and_budget(name: str) -> None:
    """Draw a scenario cleanly, repeatably and within its budget."""
    build, budget = SCENARIOS[name]
    fs, options = build()
    fs.route()
    quality = measure_final(fs)

    found = {label: count for label, count in zip(HARD_LABELS, quality.hard) if count}
    assert not found, f"{name}: hard findings {found}"
    kinds = sorted({conflict.kind for conflict in quality.hard_conflicts})
    assert not kinds, f"{name}: hard conflicts {kinds}"
    assert not _unhonoured_pins(fs), f"{name}: {_unhonoured_pins(fs)}"

    drawing = _drawing(fs)
    fs.route()
    assert _drawing(fs) == drawing, f"{name}: routing again changed the drawing"
    assert fs.to_svg(**options) == fs.to_svg(**options), f"{name}: rendering is not repeatable"

    assert quality.crossings <= budget.crossings, (
        f"{name}: {quality.crossings} crossings, budget {budget.crossings}"
    )
    width, height = _extent(fs)
    assert width <= budget.width * (1 + EXTENT_SLACK), (
        f"{name}: width {width:.0f} px, budget {budget.width:.0f} px"
    )
    assert height <= budget.height * (1 + EXTENT_SLACK), (
        f"{name}: height {height:.0f} px, budget {budget.height:.0f} px"
    )
