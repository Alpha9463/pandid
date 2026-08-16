#!/usr/bin/env python3
"""Time stream numbering as a sheet grows, and print what it costs.

A dev tool for watching numbering's runtime, not part of the test suite:

    python scripts/renumber_bench.py                # 200 to 1600 streams
    python scripts/renumber_bench.py -s 400 -s 800  # just those two sizes
    python scripts/renumber_bench.py -n 3           # best of three passes

Numbering runs on every ``connect()``, because the name on the stream a
caller is handed back has to be the name that gets drawn. That makes the
*build* the thing to measure and not a single call: one pass over a settled
sheet is cheap however the sheet was assembled, and what used to hurt was
paying for a whole pass per connection.

``connect`` is the wall time of the connect loop alone -- the units are put
on the sheet first, untimed, so the number is numbering's and not
``add()``'s -- and ``per-connect`` is that divided by the streams made,
which is the number to watch: flat means the cost of drawing one more line
does not depend on how many are already there. ``x`` is the growth in
``connect`` over the size before it, against a ``2.0`` that would be linear;
``4.0`` is the quadratic this was.

``renumber`` times one full pass over the finished sheet, which is what a
render pays and is linear by construction.

The sheet is a chain of tanks with a valve between every other pair, so
half the streams join their neighbour's group through an inline device and
half start a run of their own: both shapes numbering has to work on.
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


def wire(streams: int) -> "tuple[Flowsheet, list]":
    """A sheet of *streams* + 1 units, and the port pairs to connect them by.

    Every unit is added here so the timed loop is nothing but ``connect()``.
    ``add()`` carries a duplicate-tag scan of its own, which would otherwise
    be measured as numbering's cost.
    """
    fs = Flowsheet("bench")
    port = fs.add(U.Feed("F")).outlet
    pairs = []
    for i in range(streams):
        unit = fs.add(U.Valve(f"FV-{i}") if i % 2 == 0 else U.Tank(f"T-{i}"))
        pairs.append((port, unit.inlet))
        port = unit.outlet
    return fs, pairs


def measure(streams: int, repeat: int) -> dict:
    """Wire a *streams*-stream sheet *repeat* times, keeping the best pass.

    The sheet is rebuilt for every pass because connecting it is what is
    being timed; a second loop over the same object would time re-running
    numbering over names that are already settled, which is the other column.
    """
    connect_s = renumber_s = float("inf")
    for _ in range(repeat):
        fs, pairs = wire(streams)
        t0 = time.perf_counter()
        for src, dst in pairs:
            fs.connect(src, dst)
        t1 = time.perf_counter()
        fs.renumber_streams()
        t2 = time.perf_counter()
        connect_s = min(connect_s, t1 - t0)
        renumber_s = min(renumber_s, t2 - t1)
    return {"streams": streams, "units": len(fs.units),
            "connect": connect_s, "renumber": renumber_s}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-s", "--size", type=int, action="append",
                    help="streams to build; repeatable, default 200/400/800/1600")
    ap.add_argument("-n", "--repeat", type=int, default=1,
                    help="passes per size (best wins)")
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")
    sizes = sorted(args.size or [200, 400, 800, 1600])
    if any(n < 1 for n in sizes):
        raise SystemExit("--size takes at least one stream")

    header = (f"{'streams':>8}{'units':>7}{'connect':>10}"
              f"{'per-connect':>13}{'renumber':>10}{'x':>7}")
    print(header)
    print("-" * len(header))
    previous = None
    for n in sizes:
        r = measure(n, args.repeat)
        grow = f"{r['connect'] / previous:.1f}" if previous else "-"
        previous = r["connect"]
        print(f"{r['streams']:>8}{r['units']:>7}{r['connect']:>9.3f}s"
              f"{r['connect'] / n * 1e6:>10.1f}us{r['renumber']:>9.4f}s{grow:>7}")


if __name__ == "__main__":
    main()
