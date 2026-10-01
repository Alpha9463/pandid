"""Check that the row index gives the same collision answers as a full scan."""

from __future__ import annotations

import math

import pytest

from pandid import Flowsheet, units as U
from pandid.geometry import _Slot
from pandid.layout import coordinates
from pandid.layout.coordinates import STACK_CLEAR, _overlaps_x, _RowIndex

# Each case: neighbours as (x, y, w, h), the mover as (x, y, w, h), its new
# x, and the full scan's answer. ``None`` stands for an unset coordinate;
# NaN fails every comparison, so the scan counts it as overlapping.
CASES = {
    "disjoint bands": ([(100, 400, 60, 40)], (0, 0, 60, 40), 100, False),
    "same row, within the clearance": ([(200, 0, 60, 40)], (0, 0, 60, 40), 120, True),
    "same row, clear of it": ([(200, 0, 60, 40)], (0, 0, 60, 40), 100, False),
    "touching top to bottom": ([(0, 40, 60, 40)], (0, 0, 60, 40), 0, False),
    "negative coordinates": ([(-90, -130, 60, 40)], (-300, -150, 60, 40), -150, True),
    "box taller than many bands": ([(80, -500, 60, 1200)], (0, 330, 60, 40), 10, True),
    "neighbour without y": ([(80, None, 60, 40)], (0, 0, 60, 40), 10, False),
    "neighbour without x": ([(None, 0, 60, 40)], (0, 0, 60, 40), 10, False),
    "mover without y": ([(80, 0, 60, 40)], (0, None, 60, 40), 300, True),
    "neighbour at nan": ([(80, math.nan, 60, 40)], (0, 0, 60, 40), 10, True),
    "mover at nan": ([(80, 0, 60, 40)], (0, math.nan, 60, 40), 10, True),
}


def _unit(name: str, box: tuple) -> U.Unit:
    """Return a unit carrying a layout slot at ``box``.

    Parameters
    ----------
    name : str
        Tag.
    box : tuple
        ``(x, y, w, h)``; ``x`` and ``y`` may be ``None``.

    Returns
    -------
    Unit
        Unit with ``_slot`` set.
    """
    x, y, w, h = box
    unit = U.Pump(name)
    unit._slot = _Slot(w=w, h=h, x=x, y=y)
    return unit


@pytest.mark.parametrize("case", CASES, ids=list(CASES))
def test_row_index_matches_the_full_scan(case):
    """Check each case against both the full scan and its stated answer."""
    neighbours, mover_box, new_x, expected = CASES[case]
    mover = _unit("M", mover_box)
    units = [mover] + [_unit(f"N{i}", box) for i, box in enumerate(neighbours)]
    indexed = _overlaps_x(mover, new_x, _RowIndex(units).near(mover))
    assert indexed == _overlaps_x(mover, new_x, units) == expected


def test_row_index_reads_x_moved_after_it_was_built():
    """Check that a neighbour moved during the pass is judged where it now is."""
    mover = _unit("M", (0, 0, 60, 40))
    other = _unit("N", (500, 0, 60, 40))
    index = _RowIndex([mover, other])
    assert not _overlaps_x(mover, 100, index.near(mover))
    other._slot.x = 100 + 60 + STACK_CLEAR - 1
    assert _overlaps_x(mover, 100, index.near(mover))


def _stacked(n: int) -> Flowsheet:
    """Return a row of ``n`` blocks, each fed over its roof as well.

    Parameters
    ----------
    n : int
        Number of blocks.

    Returns
    -------
    Flowsheet
        Unlaid sheet.
    """
    fs = Flowsheet("stacked")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W", "N"], outputs=["E"]))
        fs.connect(port, block.in_1)
        fs.connect(fs.add(U.Feed(f"A-{i}")).outlet, block.in_2)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def test_stacked_layout_matches_the_unindexed_layout(monkeypatch):
    """Check that indexing changes no frame on a sheet that uses the check."""
    indexed = _stacked(30)
    indexed.layout()
    monkeypatch.setattr(coordinates._RowIndex, "near", lambda self, u: self._units)
    scanned = _stacked(30)
    scanned.layout()
    assert [u.frame for u in indexed.units] == [u.frame for u in scanned.units]
