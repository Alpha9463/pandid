#!/usr/bin/env python3
"""Time layout as a sheet grows, and count the collision checks it makes.

A development tool, not part of the test suite::

    python scripts/layout_bench.py                  # 100 to 800 blocks, both shapes
    python scripts/layout_bench.py -s 800 -s 1600   # just those two sizes
    python scripts/layout_bench.py -n 3             # best of three passes
    python scripts/layout_bench.py --shape stacked  # one shape

Columns:

``layout``
    Best ``layout()`` time over the passes. The sheet is rebuilt for every
    pass, since ``layout()`` writes its results onto it.
``x``
    Growth in ``layout`` over the previous size; 2.0 is linear when
    sizes double.
``checks``
    Rectangle comparisons made by the stack-alignment collision check
    (``pandid.layout.coordinates._overlaps_x``), counted in one extra untimed
    pass. Unlike time, it does not depend on the machine.

**chain** is a row of blocks, each feeding the next west to east; it never
reaches the collision check. **stacked** adds a ``Feed`` on each block's north
face, which makes every block a same-column stack, so it exercises the column
and row passes and the collision check.
"""

import argparse
import contextlib
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from pandid import Flowsheet  # noqa: E402
from pandid import units as U  # noqa: E402
from pandid.layout import coordinates  # noqa: E402


def chain(n: int) -> Flowsheet:
    """Return ``n`` blocks in a row, each feeding the next.

    Parameters
    ----------
    n : int
        Number of blocks.

    Returns
    -------
    Flowsheet
        Unlaid sheet.
    """
    fs = Flowsheet("chain")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W"], outputs=["E"]))
        fs.connect(port, block.in_1)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def stacked(n: int) -> Flowsheet:
    """Return the :func:`chain` row with a feed over each block's roof.

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


SHAPES = {"chain": chain, "stacked": stacked}


@contextlib.contextmanager
def counting_checks():
    """Count the candidates each collision check compares against.

    Wraps ``coordinates._overlaps_x`` for the duration of the block and
    restores it afterwards.

    Yields
    ------
    dict[str, int]
        Running totals: ``"calls"`` and ``"checks"`` (candidates compared).
    """
    original = coordinates._overlaps_x
    totals = {"calls": 0, "checks": 0}

    def counted(u, new_x, candidates):
        """Count the candidates, then run the real check."""
        candidates = list(candidates)
        totals["calls"] += 1
        totals["checks"] += len(candidates)
        return original(u, new_x, candidates)

    coordinates._overlaps_x = counted
    try:
        yield totals
    finally:
        coordinates._overlaps_x = original


def measure(shape: str, n: int, repeat: int) -> dict:
    """Return the best layout time and the check count for one sheet size.

    Parameters
    ----------
    shape : str
        Key of :data:`SHAPES`.
    n : int
        Number of blocks.
    repeat : int
        Timed passes; the fastest is kept.

    Returns
    -------
    dict
        ``shape``, ``blocks``, ``units``, ``streams``, ``layout`` (seconds)
        and ``checks``.
    """
    build = SHAPES[shape]
    layout_s = float("inf")
    for _ in range(repeat):
        fs = build(n)
        t0 = time.perf_counter()
        fs.layout()
        layout_s = min(layout_s, time.perf_counter() - t0)
    with counting_checks() as totals:
        build(n).layout()
    return {
        "shape": shape,
        "blocks": n,
        "units": len(fs.units),
        "streams": len(fs.streams),
        "layout": layout_s,
        "checks": totals["checks"],
    }


def main() -> None:
    """Parse arguments and print the table."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "-s",
        "--size",
        type=int,
        action="append",
        help="blocks to build; repeatable, default 100/200/400/800",
    )
    ap.add_argument("-n", "--repeat", type=int, default=1, help="passes per size (best wins)")
    ap.add_argument(
        "--shape", action="append", choices=sorted(SHAPES), help="repeatable; default is both"
    )
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")
    sizes = sorted(args.size or [100, 200, 400, 800])
    if any(n < 1 for n in sizes):
        raise SystemExit("--size takes at least one block")
    shapes = args.shape or sorted(SHAPES)

    header = (
        f"{'shape':<10}{'blocks':>8}{'units':>7}{'streams':>9}"
        f"{'layout':>10}{'per-unit':>12}{'x':>7}{'checks':>12}"
    )
    print(header)
    print("-" * len(header))
    for shape in shapes:
        previous = None
        for n in sizes:
            r = measure(shape, n, args.repeat)
            grow = f"{r['layout'] / previous:.1f}" if previous else "-"
            previous = r["layout"]
            print(
                f"{r['shape']:<10}{r['blocks']:>8}{r['units']:>7}{r['streams']:>9}"
                f"{r['layout']:>9.3f}s{r['layout'] / r['units'] * 1e6:>9.1f}us{grow:>7}"
                f"{r['checks']:>12,}"
            )


if __name__ == "__main__":
    main()
