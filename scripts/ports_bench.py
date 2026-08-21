#!/usr/bin/env python3
"""Time layout as one unit's port count grows, and print what it costs.

A dev tool for watching a wide port family's runtime, not part of the test
suite:

    python scripts/ports_bench.py                 # 25 to 400 ports, both shapes
    python scripts/ports_bench.py -s 200 -s 400    # just those two sizes
    python scripts/ports_bench.py -n 3             # best of three passes
    python scripts/ports_bench.py --shape manifold  # one shape

``x`` is the growth in ``layout`` over the size before it, against the ``2.0``
that would be linear.

Every port on a unit is resolved by :func:`pandid.portgeom.resolve_port`,
which places a member of a :class:`~pandid.render.symbols.PortSeries` --
a splitter's numbered outlets, a mixer's numbered inlets, a column's
``feed_1`` ... ``feed_n`` -- by finding where among its same-family
siblings it falls. Doing that by rescanning every port on the unit, once
per port asked, costs the square of the family's size on the one unit
that carries it; the fix in `pandid/units.py`'s ``_series_members`` (read
once per family, not once per member) is what this benchmark is for.

**fanout** is one :class:`~pandid.units.Splitter` with *n* outlets, each
feeding its own single-unit branch -- a header supplying *n* parallel
users. **manifold** is the fan-in the task that named this file described:
one :class:`~pandid.units.Column` with a feed on every one of *n* stages,
each from its own :class:`~pandid.units.Feed`.

``layout()`` is timed whole, the same way :mod:`layout_bench` times it, and
for the same reason: it is what a caller pays, not one phase of it.
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


def fanout(n: int) -> Flowsheet:
    """One splitter with *n* outlets, each feeding its own branch."""
    fs = Flowsheet("fanout")
    splitter = fs.add(U.Splitter("SPL", n_outlets=n))
    fs.connect(fs.add(U.Feed("F")).outlet, splitter.inlet)
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W"], outputs=["E"]))
        fs.connect(splitter.outlets[i], block.in_1)
        fs.connect(block.out_1, fs.add(U.Product(f"P-{i}")).inlet)
    return fs


def manifold(n: int) -> Flowsheet:
    """One column with a feed on every one of its *n* stages."""
    fs = Flowsheet("manifold")
    col = fs.add(
        U.Column(
            "T-101", internals="valve_tray", trays=n, n_feeds=n, feed_stages=list(range(1, n + 1))
        )
    )
    for i in range(n):
        fs.connect(fs.add(U.Feed(f"F-{i}")).outlet, getattr(col, f"feed_{i + 1}"))
    fs.connect(col.overhead, fs.add(U.Product("OVHD")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("BTMS")).inlet)
    return fs


SHAPES = {"fanout": fanout, "manifold": manifold}


def measure(shape: str, n: int, repeat: int) -> dict:
    """Lay a *shape* sheet of *n* ports out *repeat* times, keeping the best."""
    build = SHAPES[shape]
    layout_s = float("inf")
    for _ in range(repeat):
        fs = build(n)
        t0 = time.perf_counter()
        fs.layout()
        layout_s = min(layout_s, time.perf_counter() - t0)
    return {
        "shape": shape,
        "n": n,
        "units": len(fs.units),
        "streams": len(fs.streams),
        "layout": layout_s,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "-s",
        "--size",
        type=int,
        action="append",
        help="ports to build; repeatable, default 25/50/100/200/400",
    )
    ap.add_argument("-n", "--repeat", type=int, default=1, help="passes per size (best wins)")
    ap.add_argument(
        "--shape", action="append", choices=sorted(SHAPES), help="repeatable; default is both"
    )
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")
    sizes = sorted(args.size or [25, 50, 100, 200, 400])
    if any(n < 1 for n in sizes):
        raise SystemExit("--size takes at least one port")
    shapes = args.shape or sorted(SHAPES)

    header = (
        f"{'shape':<10}{'ports':>7}{'units':>7}{'streams':>9}{'layout':>10}{'per-port':>12}{'x':>7}"
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
                f"{r['shape']:<10}{r['n']:>7}{r['units']:>7}{r['streams']:>9}"
                f"{r['layout']:>9.3f}s{r['layout'] / r['n'] * 1e6:>9.1f}us{grow:>7}"
            )


if __name__ == "__main__":
    main()
