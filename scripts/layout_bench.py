#!/usr/bin/env python3
"""Time layout as a sheet grows, and print what it costs.

A dev tool for watching the layout engine's runtime, not part of the test
suite:

    python scripts/layout_bench.py                  # 100 to 800 units, both shapes
    python scripts/layout_bench.py -s 200 -s 400    # just those two sizes
    python scripts/layout_bench.py -n 3             # best of three passes
    python scripts/layout_bench.py --shape stacked  # one shape

``x`` is the growth in ``layout`` over the size before it, against the ``2.0``
that would be linear. It is the column to watch, and it is why there are two
shapes rather than one.

**chain** is a straight run of blocks, each feeding the next west to east. Every
edge advances the rank, nothing shares a column, and the phases that cost the
most never run.

**stacked** is that same run with a ``Feed`` on each block's north face. A north
face is a same-column, adjacent-row constraint (see
:mod:`pandid.layout.claims`), so every one of them is a candidate union in the
column-sharing pass and a satellite in the row-ordering pass. That is the shape
the quadratic lives on, and a benchmark built on ``chain`` alone would report a
flat cost for a sheet that is anything but.

``layout()`` is timed whole: the layering, ordering, coordinate and label
phases together. The sheet is rebuilt for every pass because ``layout()``
writes its results onto it, so a second pass over the same object would time
re-running the phases over settled geometry.
"""

import argparse
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from pandid import Flowsheet  # noqa: E402
from pandid import units as U  # noqa: E402


def chain(n: int) -> Flowsheet:
    """*n* blocks in a row, each feeding the next along the flow axis."""
    fs = Flowsheet("chain")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W"], outputs=["E"]))
        fs.connect(port, block.in_1)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def stacked(n: int) -> Flowsheet:
    """The same row of blocks, each also taking a feed over its roof."""
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


def measure(shape: str, n: int, repeat: int) -> dict:
    """Lay a *shape* sheet of *n* blocks out *repeat* times, keeping the best."""
    build = SHAPES[shape]
    layout_s = float("inf")
    for _ in range(repeat):
        fs = build(n)
        t0 = time.perf_counter()
        fs.layout()
        layout_s = min(layout_s, time.perf_counter() - t0)
    return {"shape": shape, "blocks": n, "units": len(fs.units),
            "streams": len(fs.streams), "layout": layout_s}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-s", "--size", type=int, action="append",
                    help="blocks to build; repeatable, default 100/200/400/800")
    ap.add_argument("-n", "--repeat", type=int, default=1,
                    help="passes per size (best wins)")
    ap.add_argument("--shape", action="append", choices=sorted(SHAPES),
                    help="repeatable; default is both")
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")
    sizes = sorted(args.size or [100, 200, 400, 800])
    if any(n < 1 for n in sizes):
        raise SystemExit("--size takes at least one block")
    shapes = args.shape or sorted(SHAPES)

    header = (f"{'shape':<10}{'blocks':>8}{'units':>7}{'streams':>9}"
              f"{'layout':>10}{'per-unit':>12}{'x':>7}")
    print(header)
    print("-" * len(header))
    for shape in shapes:
        previous = None
        for n in sizes:
            r = measure(shape, n, args.repeat)
            grow = f"{r['layout'] / previous:.1f}" if previous else "-"
            previous = r["layout"]
            print(f"{r['shape']:<10}{r['blocks']:>8}{r['units']:>7}{r['streams']:>9}"
                  f"{r['layout']:>9.3f}s{r['layout'] / r['units'] * 1e6:>9.1f}us{grow:>7}")


if __name__ == "__main__":
    main()
