#!/usr/bin/env python3
"""Time layout and routing over example and dense sheets, and print what they cost.

A development tool, not part of the test suite::

    python scripts/route_bench.py                   # every example
    python scripts/route_bench.py 11_ethanol_pid    # one of them
    python scripts/route_bench.py -n 5              # best of five passes
    python scripts/route_bench.py --manifold 8 --manifold 16   # dense sheets only

Each example is built with ``Flowsheet.render`` stubbed out
(``scripts/gallery.py``), then laid out and routed here. Rendering is left
out: this measures geometry.

``route()`` is timed whole: the visibility graph, the A* searches, separation,
attached-instrument passes and the layout refinements that re-route the
sheet. The graph columns describe one :class:`~pandid.routing.visibility.
VisibilityGraph` built over the final layout: ``nodes`` and ``edges`` (directed
adjacency entries), and ``graph MB``, the peak memory of building it.

``--manifold N`` adds a synthetic dense sheet: a feed split ``N`` ways through
a pump and an exchanger on each branch, then mixed into one product. It shows
how routing grows with the number of parallel branches.
"""

import argparse
import contextlib
import io
import pathlib
import sys
import time
import tracemalloc

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402


def manifold(n: int):
    """Return a sheet with ``n`` parallel pump-and-exchanger branches.

    Parameters
    ----------
    n : int
        Number of branches.

    Returns
    -------
    Flowsheet
        Unlaid sheet.
    """
    from pandid import Flowsheet
    from pandid import units as U

    fs = Flowsheet(f"manifold_{n}")
    feed = fs.add(U.Feed("F"))
    split = fs.add(U.Splitter("S-1", n_outlets=n))
    mix = fs.add(U.Mixer("M-1", n_inlets=n))
    fs.connect(feed.outlet, split.inlet)
    for i in range(n):
        pump = fs.add(U.Pump(f"P-{i}"))
        hx = fs.add(U.HeatExchanger(f"E-{i}"))
        fs.connect(split.outlets[i], pump.suction)
        fs.connect(pump.discharge, hx.tube_in)
        fs.connect(hx.tube_out, mix.inlets[i])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    return fs


def _example(stem: str):
    """Return an example's flowsheet, with its console output discarded."""
    with contextlib.redirect_stdout(io.StringIO()):
        fs, _kwargs = gallery.flowsheet(stem)
    return fs


def measure(name: str, build, repeat: int) -> dict:
    """Return the best layout and route times, and the graph size, for one sheet.

    The sheet is rebuilt for every pass, since ``layout()`` and ``route()``
    write their results onto it.

    Parameters
    ----------
    name : str
        Row label.
    build : callable
        Returns a fresh, unlaid flowsheet.
    repeat : int
        Timed passes; the fastest of each phase is kept.

    Returns
    -------
    dict
        ``sheet``, ``units``, ``streams``, ``nodes``, ``edges``, ``graph_mb``,
        ``layout`` and ``route`` (seconds).
    """
    layout_s = route_s = float("inf")
    for _ in range(repeat):
        fs = build()
        t0 = time.perf_counter()
        fs.layout()
        t1 = time.perf_counter()
        fs.route()
        t2 = time.perf_counter()
        layout_s = min(layout_s, t1 - t0)
        route_s = min(route_s, t2 - t1)

    from pandid.routing.visibility import VisibilityGraph

    tracemalloc.start()
    graph = VisibilityGraph(fs, margin=15.0)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {
        "sheet": name,
        "units": len(fs.units),
        "streams": len(fs.streams),
        "nodes": len(graph.nodes),
        "edges": sum(len(v) for v in graph.edges.values()),
        "graph_mb": peak / 1e6,
        "layout": layout_s,
        "route": route_s,
    }


def main() -> None:
    """Parse arguments and print the table."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "sheet", nargs="*", help="example stems; default is all of them unless --manifold is given"
    )
    ap.add_argument("-n", "--repeat", type=int, default=1, help="passes per sheet (best wins)")
    ap.add_argument(
        "--manifold",
        type=int,
        action="append",
        default=[],
        metavar="N",
        help="also route a synthetic sheet of N parallel branches; repeatable",
    )
    args = ap.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat takes at least one pass")
    if any(n < 1 for n in args.manifold):
        raise SystemExit("--manifold takes at least one branch")

    known = gallery.sheets()
    stems = args.sheet or ([] if args.manifold else known)
    for stem in stems:
        if stem not in known:
            raise SystemExit(f"no such example: {stem}\nknown sheets: {', '.join(known)}")
    jobs = [(stem, lambda stem=stem: _example(stem)) for stem in stems]
    jobs += [(f"manifold_{n}", lambda n=n: manifold(n)) for n in sorted(args.manifold)]

    header = (
        f"{'sheet':<26}{'units':>7}{'streams':>9}{'nodes':>9}{'edges':>9}"
        f"{'graph MB':>10}{'layout':>10}{'route':>10}"
    )
    print(header)
    print("-" * len(header))
    total_layout = total_route = 0.0
    for name, build in jobs:
        r = measure(name, build, args.repeat)
        total_layout += r["layout"]
        total_route += r["route"]
        print(
            f"{r['sheet']:<26}{r['units']:>7}{r['streams']:>9}{r['nodes']:>9}{r['edges']:>9}"
            f"{r['graph_mb']:>10.1f}{r['layout']:>9.3f}s{r['route']:>9.3f}s"
        )
    print("-" * len(header))
    print(
        f"{'total':<26}{'':>7}{'':>9}{'':>9}{'':>9}{'':>10}"
        f"{total_layout:>9.3f}s{total_route:>9.3f}s"
    )


if __name__ == "__main__":
    main()
