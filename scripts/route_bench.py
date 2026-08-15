#!/usr/bin/env python3
"""Time layout and routing over the example sheets, and print what they cost.

A dev tool for watching the geometry's runtime, not part of the test suite:

    python scripts/route_bench.py                   # every example
    python scripts/route_bench.py 11_ethanol_pid    # one of them
    python scripts/route_bench.py -n 5              # best of five passes

Each sheet is built by importing its example with ``Flowsheet.render``
stubbed out -- ``scripts/gallery.py``'s capture, so nothing is written
anywhere -- and is then laid out and routed here, timed. Rendering is left
out on purpose: this measures the geometry, which is where the time goes.

``route()`` is timed whole, so the number covers the visibility graph, the
A* search over it, the parallel-segment separation pass, and the re-route
per attached-instrument placement pass. ``nodes`` is the size of the graph
that work runs against, and is what the routing cost tracks: it is the
lane grid, one node per crossing not sealed inside a piece of equipment.
"""

import argparse
import contextlib
import io
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402


def measure(stem: str, repeat: int) -> dict:
    """Lay out and route *stem*'s sheet *repeat* times, keeping the best pass.

    The flowsheet is rebuilt for every pass: ``layout()`` and ``route()``
    both write their results onto it, so timing a second pass over the same
    object would time re-running them over settled geometry. Building it runs
    the example's own ``main()``, which reports what it drew; that goes to a
    sink, so the table below is the only thing on stdout.
    """
    layout_s = route_s = float("inf")
    for _ in range(repeat):
        with contextlib.redirect_stdout(io.StringIO()):
            fs, _kwargs = gallery.flowsheet(stem)
        t0 = time.perf_counter()
        fs.layout()
        t1 = time.perf_counter()
        fs.route()
        t2 = time.perf_counter()
        layout_s = min(layout_s, t1 - t0)
        route_s = min(route_s, t2 - t1)

    from pandid.routing.visibility import VisibilityGraph

    graph = VisibilityGraph(fs, margin=15.0)
    return {
        "sheet": stem,
        "units": len(fs.units),
        "streams": len(fs.streams),
        "nodes": len(graph.nodes),
        "layout": layout_s,
        "route": route_s,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", nargs="*", help="example stems; default is all of them")
    ap.add_argument("-n", "--repeat", type=int, default=1, help="passes per sheet (best wins)")
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")

    known = gallery.sheets()
    stems = args.sheet or known
    for stem in stems:
        if stem not in known:
            raise SystemExit(f"no such example: {stem}\nknown sheets: {', '.join(known)}")

    header = f"{'sheet':<24}{'units':>7}{'streams':>9}{'nodes':>9}{'layout':>10}{'route':>10}"
    print(header)
    print("-" * len(header))
    total_layout = total_route = 0.0
    for stem in stems:
        r = measure(stem, args.repeat)
        total_layout += r["layout"]
        total_route += r["route"]
        print(
            f"{r['sheet']:<24}{r['units']:>7}{r['streams']:>9}{r['nodes']:>9}"
            f"{r['layout']:>9.3f}s{r['route']:>9.3f}s"
        )
    print("-" * len(header))
    print(f"{'total':<24}{'':>7}{'':>9}{'':>9}{total_layout:>9.3f}s{total_route:>9.3f}s")


if __name__ == "__main__":
    main()
