"""Hold automatic drawing quality on a small behavioural corpus.

Each scenario lays out and routes one sheet with the default engine. It must
meet the hard invariants, draw the same sheet when routed and rendered again,
and stay within its budgets. A budget is the figure measured at ``3e88e38``
(1 October 2026); #564 tightens them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

import pytest

from _layout_cases import build as build_biodiesel
from pandid import Flowsheet, units as U
from pandid.layout.quality import _HARD_CODES, measure_final
from pandid.portgeom import pin_intent, port_point
from scripts import layout_quality
from scripts.layout_compare import _fingerprint

#: Allowance on a budgeted extent, as a fraction of it.
EXTENT_SLACK = 0.01

#: Labels for ``Quality.hard``, in its order.
HARD_LABELS = ("validation errors", "fallback routes", *_HARD_CODES, "undrawn streams")


class Budget(NamedTuple):
    """Upper limits for one scenario's drawing.

    Attributes
    ----------
    crossings : int
        Line crossings in the finished drawing.
    width, height : float
        Extent of the unit frames, in pixels.
    """

    crossings: int
    width: float
    height: float


def _simple_chain() -> tuple[Flowsheet, dict]:
    """Build a feed, pump, exchanger and product in one line.

    Returns
    -------
    tuple[Flowsheet, dict]
        Unpinned flowsheet and its render options.
    """
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
    """Build a free pump between two flags pinned in pixels.

    Returns
    -------
    tuple[Flowsheet, dict]
        Flowsheet with two absolute pins and its render options.
    """
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
    """Return a builder for one variant of the biodiesel sheet.

    Parameters
    ----------
    **options
        Keyword arguments for ``tests._layout_cases.build``.

    Returns
    -------
    Callable[[], tuple[Flowsheet, dict]]
        Builder of a fresh flowsheet and empty render options.
    """
    return lambda: (build_biodiesel(**options)[0], {})


def _stripped(stem: str) -> Callable[[], tuple[Flowsheet, dict]]:
    """Return a builder for a shipped example with its placement pins removed.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    Callable[[], tuple[Flowsheet, dict]]
        Builder of a fresh flowsheet and its render options.
    """
    return lambda: layout_quality.build(stem, True)


SCENARIOS: dict[str, tuple[Callable[[], tuple[Flowsheet, dict]], Budget]] = {
    "simple chain": (_simple_chain, Budget(0, 656, 87)),
    "pixel anchors": (_pixel_anchors, Budget(0, 736, 67)),
    "biodiesel as authored": (_biodiesel(), Budget(7, 1981, 1254)),
    "biodiesel with one pin removed": (_biodiesel(skip="s103"), Budget(7, 1981, 1254)),
    "biodiesel automatic": (_biodiesel(pinned=False), Budget(20, 1998, 942)),
    "ethanol P&ID automatic": (_stripped("11_ethanol_pid"), Budget(8, 2588, 1992)),
    "molecular sieve automatic": (_stripped("20_molecular_sieve_dryer"), Budget(32, 1828, 1822)),
    "alumina refinery automatic": (_stripped("21_alumina_refinery"), Budget(69, 3044, 2147)),
}


def _extent(fs: Flowsheet) -> tuple[float, float]:
    """Measure the width and height spanned by every unit frame.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.

    Returns
    -------
    tuple[float, float]
        Width and height in pixels.
    """
    frames = [unit.frame for unit in fs.units if unit.frame is not None]
    return (
        max(frame.x_max for frame in frames) - min(frame.x for frame in frames),
        max(frame.y_max for frame in frames) - min(frame.y for frame in frames),
    )


def _unhonoured_pins(fs: Flowsheet) -> list[str]:
    """List the pixel pins that the drawing does not keep.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.

    Returns
    -------
    list[str]
        One description per pinned axis more than half a pixel off.
    """
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
    """Draw a scenario cleanly, repeatably and within its budget.

    Parameters
    ----------
    name : str
        Scenario key in ``SCENARIOS``.

    Returns
    -------
    None
        Invariants, repeat runs and each budget are checked separately.
    """
    build, budget = SCENARIOS[name]
    fs, options = build()
    fs.route()
    quality = measure_final(fs)

    found = {label: count for label, count in zip(HARD_LABELS, quality.hard) if count}
    assert not found, f"{name}: hard findings {found}"
    kinds = sorted({conflict.kind for conflict in quality.hard_conflicts})
    assert not kinds, f"{name}: hard conflicts {kinds}"
    assert not _unhonoured_pins(fs), f"{name}: {_unhonoured_pins(fs)}"

    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint, f"{name}: routing again changed the drawing"
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


@pytest.mark.xfail(strict=True, reason="#564: the column push leaves its partners west")
def test_columns_keep_condensers_and_reboilers_east_or_above() -> None:
    """Place each overhead condenser and reboiler east of its column or over it.

    Returns
    -------
    None
        No condenser or reboiler centre lies west of its column's centre.
    """
    fs, _ = layout_quality.build("03_distillation_train", True)
    fs.route()
    units = {unit.name: unit for unit in fs.units}
    west = [
        f"{peer} west of {column}"
        for column, peers in (("T-100", ("E-101", "E-102")), ("T-200", ("E-201", "E-202")))
        for peer in peers
        if units[peer].frame.cx < units[column].frame.cx - 1
    ]
    assert not west, west


@pytest.mark.xfail(strict=True, reason="#564: row passes separate R-103 from C-102")
def test_automatic_biodiesel_keeps_r103_beside_c102() -> None:
    """Keep R-103 within one grid row of C-102, which feeds it.

    Returns
    -------
    None
        The two units' grid rows differ by at most one.
    """
    fs, _ = build_biodiesel(pinned=False)
    fs.route()
    units = {unit.name: unit for unit in fs.units}
    rows = units["R-103"].frame.row, units["C-102"].frame.row
    assert rows[0] is not None and rows[1] is not None
    assert abs(rows[0] - rows[1]) <= 1, rows
