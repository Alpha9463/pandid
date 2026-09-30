#!/usr/bin/env python3
"""Measure the quality of the routes ``route()`` draws.

    python scripts/route_quality.py                   # every example
    python scripts/route_quality.py 11_ethanol_pid     # one example
    python scripts/route_quality.py --synthetic        # the probe sheets only
    python scripts/route_quality.py --worst 15         # longer offender lists

Each measure is compared with a bound computed from the sheet's own geometry:

- **bends**, against the fewest an orthogonal path between the two nozzle
  faces can have (:func:`min_bends`);
- **length**, against the Manhattan distance between the two nozzles;
- **crossings** between different streams, and whether the later-routed
  stream had an alternative of similar length, found by repeating its search
  with the crossed lane barred;
- **fallback routes**, drawn when no route was found: a search that returned
  nothing, or a nozzle exit sealed before any search (#355);
- **expansion budget**, as the fraction each search spent.

Metrics read the complete drawn paths after ``route()`` returns. The
alternative-route test replays the search before separation. The script
changes no route; its only extra work is those repeated searches.
"""

from __future__ import annotations

import argparse
import contextlib
import heapq
import io
import pathlib
import statistics
import sys
import warnings
from dataclasses import dataclass
from typing import Optional

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402

from pandid.flowsheet import Flowsheet  # noqa: E402
from pandid.portgeom import port_point  # noqa: E402
from pandid.route_geometry import stream_polyline  # noqa: E402
from pandid.units import Feed, Product, Pump, Valve  # noqa: E402
import pandid.routing.astar as astar_mod  # noqa: E402
from pandid.routing import DefaultRouter  # noqa: E402
from pandid.routing.astar import (  # noqa: E402
    MAX_EXPANSIONS_PER_NODE,
    MIN_EXPANSION_BUDGET,
    find_path,
)
from pandid.routing.visibility import TRAVEL, VisibilityGraph  # noqa: E402
from pandid.routing.metrics import (  # noqa: E402
    Point,
    crossing_point,
    min_bends,
    overlap_length,
    path_length,
    real_bends,
    waypoint_segments,
)


@dataclass
class Crossing:
    """One crossing between two different streams.

    Attributes
    ----------
    h_stream, v_stream : Stream
        Streams owning the horizontal and vertical segments.
    h_seg, v_seg : tuple[Point, Point]
        Endpoints of the two segments.
    point : Point
        Where the segments cross.
    """

    h_stream: object
    h_seg: tuple[Point, Point]
    v_stream: object
    v_seg: tuple[Point, Point]
    point: Point


@dataclass
class Overlap:
    """One stretch of track shared by two streams.

    Attributes
    ----------
    a, b : Stream
        Streams drawn on the same track.
    axis : str
        ``"h"`` or ``"v"``.
    length : float
        Shared length in drawing pixels.
    """

    a: object
    b: object
    axis: str
    length: float


def find_crossings_and_overlaps(fs: Flowsheet) -> tuple[list[Crossing], list[Overlap], int]:
    """Find crossings and overlapping tracks on complete drawn paths.

    Parameters
    ----------
    fs : Flowsheet
        Routed drawing whose stream paths are inspected.

    Returns
    -------
    tuple[list[Crossing], list[Overlap], int]
        Between-stream crossings, overlaps, and self-crossing count.
    """
    entries: list[tuple[object, tuple[Point, Point, str]]] = []
    for s in fs.streams:
        if (s.route is None or s.source.owner.frame is None
                or s.dest.owner.frame is None):
            continue
        for seg in waypoint_segments(stream_polyline(s)):
            entries.append((s, seg))

    crossings: list[Crossing] = []
    overlaps: list[Overlap] = []
    self_crossings = 0
    for i in range(len(entries)):
        s_a, (a1, a2, axis_a) = entries[i]
        for j in range(i + 1, len(entries)):
            s_b, (b1, b2, axis_b) = entries[j]
            if axis_a != axis_b:
                if axis_a == "h":
                    pt = crossing_point((a1, a2), (b1, b2))
                    h_stream, h_seg, v_stream, v_seg = s_a, (a1, a2), s_b, (b1, b2)
                else:
                    pt = crossing_point((b1, b2), (a1, a2))
                    h_stream, h_seg, v_stream, v_seg = s_b, (b1, b2), s_a, (a1, a2)
                if pt is not None:
                    if s_a is s_b:
                        self_crossings += 1
                    else:
                        crossings.append(Crossing(h_stream, h_seg, v_stream, v_seg, pt))
            elif s_a is not s_b:
                ov = overlap_length((a1, a2), (b1, b2), axis_a)
                if ov > 1e-6:
                    overlaps.append(Overlap(s_a, s_b, axis_a, ov))
    return crossings, overlaps, self_crossings


# ---------------------------------------------------------------------------
# Record path searches: budget use and the state a repeated search needs.
# ---------------------------------------------------------------------------


@dataclass
class Call:
    """One path search and the drawing that requested it.

    Attributes
    ----------
    sheet : Flowsheet
        Live or isolated drawing routed during this call.
    graph : VisibilityGraph
        Visibility graph used by the search.
    start, goal : Point
        Projected route endpoints.
    start_dir, goal_dir : str or None
        Required endpoint directions.
    edge_penalties : dict
        Costs from earlier streams in the same pass.
    is_recycle : bool
        Whether the stream is a recycle.
    result : list[Point]
        Search result before route separation.
    expansions, budget : int
        Search effort and its limit.
    route_pass : int
        Router pass that made the search, counted from one.
    """

    sheet: Flowsheet
    graph: VisibilityGraph
    start: Point
    goal: Point
    start_dir: Optional[str]
    goal_dir: Optional[str]
    edge_penalties: dict
    is_recycle: bool
    result: list[Point]
    expansions: int
    budget: int
    route_pass: int


class Recorder:
    """Record router searches and their owning drawing.

    Attributes
    ----------
    calls : list[Call]
        Search calls in execution order, including isolated trials.
    """

    def __init__(self) -> None:
        """Prepare an empty route-search log.

        Returns
        -------
        None
            Search calls are stored in ``calls``.
        """
        self.calls: list[Call] = []
        self._active_sheet: Flowsheet | None = None
        self._active_pass = 0
        self._passes = 0
        self._last_pass: dict[int, int] = {}
        self._count = 0

    def __enter__(self) -> "Recorder":
        """Install temporary route and path-search observers.

        Returns
        -------
        Recorder
            Active observer for the live drawing.
        """
        global _ACTIVE_RECORDER
        if _ACTIVE_RECORDER is not None:
            raise RuntimeError("route recorders cannot be nested")
        self._original = astar_mod.find_path
        self._original_route = DefaultRouter.route
        _ACTIVE_RECORDER = self
        DefaultRouter.route = _recorded_route
        astar_mod.find_path = self._record_path
        return self

    def _record_route(self, router: DefaultRouter, fs: Flowsheet) -> None:
        """Associate one router pass with its drawing.

        Parameters
        ----------
        router : DefaultRouter
            Router performing the pass.
        fs : Flowsheet
            Drawing being routed.

        Returns
        -------
        None
            Routes are stored on ``fs`` by the original router.
        """
        previous, previous_pass = self._active_sheet, self._active_pass
        self._passes += 1
        self._active_sheet, self._active_pass = fs, self._passes
        self._last_pass[id(fs)] = self._passes
        try:
            self._original_route(router, fs)
        finally:
            self._active_sheet, self._active_pass = previous, previous_pass

    def final_pass(self, sheet: Flowsheet) -> list[Call]:
        """Return the searches of the last router pass over one drawing.

        Parameters
        ----------
        sheet : Flowsheet
            Live or isolated drawing that was routed.

        Returns
        -------
        list[Call]
            Searches in router order; empty when the pass made none.
        """
        last = self._last_pass.get(id(sheet))
        return [call for call in self.calls if call.sheet is sheet and call.route_pass == last]

    def _record_path(self, graph, start, goal, start_dir=None, goal_dir=None,
                     edge_penalties=None, is_recycle=False, crossing_index=None):
        """Record one path search with its owning drawing.

        Parameters
        ----------
        graph : VisibilityGraph
            Search graph.
        start, goal : Point
            Projected route endpoints.
        start_dir, goal_dir : str or None, optional
            Required endpoint directions.
        edge_penalties : dict or None, optional
            Costs accumulated from earlier streams.
        is_recycle : bool, optional
            Whether this stream is a recycle.
        crossing_index : object or None, optional
            Router crossing state.

        Returns
        -------
        list[Point]
            Original path search result.
        """
        if self._active_sheet is None:
            return self._original(graph, start, goal, start_dir, goal_dir, edge_penalties,
                                  is_recycle, crossing_index)
        self._count = 0
        self._original_heappop = heapq.heappop
        heapq.heappop = self._count_heappop
        try:
            result = self._original(graph, start, goal, start_dir, goal_dir, edge_penalties,
                                    is_recycle, crossing_index)
        finally:
            heapq.heappop = self._original_heappop
        budget = max(MIN_EXPANSION_BUDGET, MAX_EXPANSIONS_PER_NODE * len(graph.nodes))
        self.calls.append(
            Call(self._active_sheet, graph, start, goal, start_dir, goal_dir,
                 dict(edge_penalties or {}), is_recycle, list(result), self._count, budget,
                 self._active_pass)
        )
        return result

    def _count_heappop(self, heap):
        """Count one heap removal without changing the search.

        Parameters
        ----------
        heap : list
            Search priority queue.

        Returns
        -------
        object
            Item removed by the original heap operation.
        """
        self._count += 1
        return self._original_heappop(heap)

    def __exit__(self, exc_type, exc, tb) -> None:
        """Restore the unobserved router and path search.

        Parameters
        ----------
        exc_type, exc, tb : object
            Exception context supplied by the context manager protocol.

        Returns
        -------
        None
            Both temporary wrappers are removed.
        """
        global _ACTIVE_RECORDER
        astar_mod.find_path = self._original
        DefaultRouter.route = self._original_route
        _ACTIVE_RECORDER = None


_ACTIVE_RECORDER: Recorder | None = None


def _recorded_route(router: DefaultRouter, fs: Flowsheet) -> None:
    """Forward a patched router call to the active recorder.

    Parameters
    ----------
    router : DefaultRouter
        Router performing the pass.
    fs : Flowsheet
        Drawing being routed.

    Returns
    -------
    None
        Routes are stored on ``fs`` by the original router.
    """
    recorder = _ACTIVE_RECORDER
    if recorder is None:
        raise RuntimeError("no route recorder is active")
    recorder._record_route(router, fs)


def _same_drawing(first: Flowsheet, second: Flowsheet) -> bool:
    """Compare settled geometry across a live drawing and a trial.

    Parameters
    ----------
    first, second : Flowsheet
        Drawings with corresponding units and streams.

    Returns
    -------
    bool
        Whether frames, routes, control taps, and convergence agree.
    """
    return (
        len(first.units) == len(second.units)
        and len(first.streams) == len(second.streams)
        and all(a.frame == b.frame and getattr(a, "tap", None) == getattr(b, "tap", None)
                for a, b in zip(first.units, second.units))
        and all(a.route == b.route for a, b in zip(first.streams, second.streams))
        and first.route_converged == second.route_converged
    )


def eligible_streams(fs: Flowsheet, graph: VisibilityGraph) -> list:
    """Return the streams ``route()`` draws automatically, in router order.

    The filter copies ``DefaultRouter.route()``: manual routes, unplaced
    units, and ports without an anchor are excluded. Each stream makes at
    most one ``find_path`` call per pass.

    Parameters
    ----------
    fs : Flowsheet
        Routed drawing.
    graph : VisibilityGraph
        Graph of the pass being measured.

    Returns
    -------
    list[Stream]
        Streams in flowsheet order.
    """
    out = []
    for stream in fs.streams:
        if stream.route and stream.route.manual:
            continue
        src_u, dst_u = stream.source.owner, stream.dest.owner
        if src_u is None or dst_u is None:
            continue
        if src_u.frame is None or dst_u.frame is None:
            continue
        if (src_u.name, stream.source.name) not in graph.port_anchors:
            continue
        if (dst_u.name, stream.dest.name) not in graph.port_anchors:
            continue
        out.append(stream)
    return out


#: Longest stand-off ``escape_distance`` gives a nozzle, in drawing pixels.
MAX_ESCAPE = 50.0


def _on_exit_ray(anchor: Point, direction: Optional[str], node: Point) -> bool:
    """Check that a search endpoint lies on a nozzle's outward stub.

    Parameters
    ----------
    anchor : Point
        Nozzle anchor on the unit body.
    direction : str or None
        Outward face of the nozzle.
    node : Point
        Search start or goal.

    Returns
    -------
    bool
        Whether the node is the anchor's escape node at any permitted reach.
    """
    travel = TRAVEL.get(direction) if direction is not None else None
    if travel is None:
        return node == anchor
    axis, sign = travel
    reach = sign * (node[axis] - anchor[axis])
    return node[1 - axis] == anchor[1 - axis] and 0.0 <= reach <= MAX_ESCAPE


def pair_calls(eligible: list, calls: list[Call], name: str) -> dict[int, Call]:
    """Match one pass's searches to the streams that made them.

    The router draws a stream whose nozzle exit is sealed without searching,
    so a pass can log fewer calls than it has streams.

    Parameters
    ----------
    eligible : list[Stream]
        Automatically routed streams in router order.
    calls : list[Call]
        Searches logged by one router pass, in order.
    name : str
        Sheet name used in the failure message.

    Returns
    -------
    dict[int, Call]
        Search keyed by ``id()`` of its stream; streams drawn without a
        search have no entry.
    """
    paired: dict[int, Call] = {}
    used = 0
    for stream in eligible:
        if used == len(calls):
            break
        call = calls[used]
        source = (stream.source.owner.name, stream.source.name)
        dest = (stream.dest.owner.name, stream.dest.name)
        anchors, faces = call.graph.port_anchors, call.graph.port_dirs
        if (_on_exit_ray(anchors[source], faces.get(source), call.start)
                and _on_exit_ray(anchors[dest], faces.get(dest), call.goal)):
            paired[id(stream)] = call
            used += 1
    assert used == len(calls), (
        f"{name}: {len(calls) - used} of {len(calls)} searches match no "
        f"stream of the {len(eligible)} eligible -- eligibility filter "
        f"drifted from DefaultRouter.route(); re-check eligible_streams() "
        f"against pandid/routing/__init__.py."
    )
    return paired


# ---------------------------------------------------------------------------
# Test whether the later stream could have avoided a crossed lane.
# ---------------------------------------------------------------------------


def lane_edges(graph: VisibilityGraph, axis: str, track: float) -> list[tuple[Point, Point]]:
    """Return the graph edges that lie on one lane.

    Parameters
    ----------
    graph : VisibilityGraph
        Search graph.
    axis : str
        ``"h"`` for a horizontal lane, ``"v"`` for a vertical one.
    track : float
        Fixed coordinate of the lane.

    Returns
    -------
    list[tuple[Point, Point]]
        Directed edges whose two nodes are on the lane.
    """
    idx = 1 if axis == "h" else 0
    edges = []
    for u, neighbors in graph.edges.items():
        if u[idx] != track:
            continue
        for v in neighbors:
            if v[idx] == track:
                edges.append((u, v))
    return edges


def track_covering(raw_points: list[Point], axis: str, coord: float) -> Optional[float]:
    """Return the lane of the raw search path that covers a coordinate.

    Parameters
    ----------
    raw_points : list[Point]
        Search path before separation, including both endpoints.
    axis : str
        ``"h"`` or ``"v"``.
    coord : float
        Position along the lane.

    Returns
    -------
    float or None
        Fixed coordinate of the covering segment, or ``None`` if none covers it.
    """
    for p1, p2 in zip(raw_points, raw_points[1:]):
        if axis == "h" and p1[1] == p2[1]:
            lo, hi = sorted((p1[0], p2[0]))
            if lo - 1e-6 <= coord <= hi + 1e-6:
                return p1[1]
        if axis == "v" and p1[0] == p2[0]:
            lo, hi = sorted((p1[1], p2[1]))
            if lo - 1e-6 <= coord <= hi + 1e-6:
                return p1[0]
    return None


def avoidable(call: Call, axis: str, coord: float) -> tuple[Optional[str], Optional[float]]:
    """Classify the cost of avoiding one crossed lane.

    The search is repeated with every edge on that lane barred, on top of
    the penalties the original search saw.

    Parameters
    ----------
    call : Call
        Search made by the later-routed stream.
    axis : str
        Axis of that stream's crossing segment.
    coord : float
        Position of the crossing along the segment.

    Returns
    -------
    tuple[str or None, float or None]
        ``"avoidable"`` when an alternative within 2 % of the original
        length exists, ``"costly"`` when a longer one exists, or
        ``"forced"`` when none exists, with the added length in pixels.
        ``(None, None)`` when the call found no path or the crossing
        matches none of its segments.
    """
    if not call.result:
        return None, None
    raw = [call.start] + call.result + [call.goal]
    track = track_covering(raw, axis, coord)
    if track is None:
        return None, None
    orig_len = path_length(raw)
    banned = dict(call.edge_penalties)
    for edge in lane_edges(call.graph, axis, track):
        banned[edge] = banned.get(edge, 0.0) + 1e7
    alt = find_path(call.graph, call.start, call.goal, call.start_dir, call.goal_dir, banned, call.is_recycle)
    if not alt:
        return "forced", None
    alt_len = path_length([call.start] + alt + [call.goal])
    extra = alt_len - orig_len
    if extra <= max(orig_len * 0.02, 1.0):
        return "avoidable", extra
    return "costly", extra


# ---------------------------------------------------------------------------
# Measure one sheet.
# ---------------------------------------------------------------------------


@dataclass
class StreamRow:
    """Route measurements for one drawn stream.

    Attributes
    ----------
    sheet, name : str
        Sheet and stream names.
    actual_bends : int
        Direction changes on the drawn path.
    min_bends : int or None
        Fewest bends the two nozzle faces allow.
    length : float
        Drawn path length in pixels.
    manhattan : float or None
        Manhattan distance between the two nozzles.
    is_fallback : bool
        Whether the router drew the fallback route.
    is_manual : bool
        Whether the author supplied the waypoints.
    """

    sheet: str
    name: str
    actual_bends: int
    min_bends: Optional[int]
    length: float
    manhattan: Optional[float]
    is_fallback: bool
    is_manual: bool


@dataclass
class SheetReport:
    """Route measurements for one sheet.

    Attributes
    ----------
    sheet : str
        Sheet name.
    units, streams, nodes : int
        Counts of units, streams, and visibility-graph nodes.
    routed : int
        Streams with a drawn path.
    undrawn : list[str]
        One message per stream left without a route.
    fallback : int
        Automatically routed streams drawn by the fallback.
    auto_routed : int
        Streams the router draws automatically.
    budget_ratios : list[float]
        Fraction of the expansion budget each final-pass search spent.
    rows : list[StreamRow]
        Per-stream measurements.
    crossings : list[Crossing]
        Crossings between different streams.
    overlaps : list[Overlap]
        Shared tracks between different streams.
    self_crossings : int
        Crossings of a stream with itself.
    verdicts : list[tuple[str, float or None]]
        Verdict and added length for each crossing tested for an alternative.
    """

    sheet: str
    units: int
    streams: int
    nodes: int
    routed: int
    undrawn: list[str]
    fallback: int
    auto_routed: int
    budget_ratios: list[float]
    rows: list[StreamRow]
    crossings: list[Crossing]
    overlaps: list[Overlap]
    self_crossings: int
    verdicts: list[tuple[str, Optional[float]]]


def measure_sheet(fs: Flowsheet, name: str) -> SheetReport:
    """Measure the final routed drawing and its matching search pass.

    Parameters
    ----------
    fs : Flowsheet
        Drawing to lay out and route.
    name : str
        Name used in the report.

    Returns
    -------
    SheetReport
        Final route costs, findings, and search effort.
    """
    fs.layout()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with Recorder() as rec:
            fs.route()

    # Use the last routed drawing whose geometry matches the published one.
    # Rejected isolated trials leave no trace in the measured route graph.
    owner = next((call.sheet for call in reversed(rec.calls)
                  if _same_drawing(call.sheet, fs)), fs)
    final_pass = rec.final_pass(owner)
    graph = final_pass[-1].graph if final_pass else VisibilityGraph(fs, margin=15.0)
    eligible = eligible_streams(fs, graph)
    stream_call = pair_calls(eligible, final_pass, name)

    undrawn = [f"stream {stream.name!r} is left unrouted"
               for stream in fs.streams
               if stream.route is None or (not stream.route.manual
                   and len(stream.route.waypoints) < 2)]

    rows: list[StreamRow] = []
    for s in fs.streams:
        if (s.route is None or s.source.owner.frame is None
                or s.dest.owner.frame is None
                or not s.route.manual and len(s.route.waypoints) < 2):
            continue
        wp = stream_polyline(s)
        src_u, dst_u = s.source.owner, s.dest.owner
        a = port_point(src_u, src_u.frame, s.source.name)
        b = port_point(dst_u, dst_u.frame, s.dest.name)
        dir_a = graph.port_dirs.get((src_u.name, s.source.name))
        dir_b = graph.port_dirs.get((dst_u.name, s.dest.name))
        rows.append(StreamRow(
            sheet=name,
            name=s.name,
            actual_bends=real_bends(wp),
            min_bends=min_bends(a, dir_a, b, dir_b) if a and b else None,
            length=path_length(wp),
            manhattan=(abs(b[0] - a[0]) + abs(b[1] - a[1])) if a and b else None,
            is_fallback=bool(not s.route.manual and s.route.used_fallback),
            is_manual=bool(s.route.manual),
        ))

    crossings, overlaps, self_crossings = find_crossings_and_overlaps(fs)
    stream_index = {id(s): i for i, s in enumerate(fs.streams)}
    verdicts: list[tuple[str, Optional[float]]] = []
    for c in crossings:
        h_idx = stream_index.get(id(c.h_stream), -1)
        v_idx = stream_index.get(id(c.v_stream), -1)
        later_is_h = h_idx > v_idx
        later, axis, coord = (
            (c.h_stream, "h", c.point[0]) if later_is_h else (c.v_stream, "v", c.point[1])
        )
        call = stream_call.get(id(later))
        if call is None:
            continue
        verdict, extra = avoidable(call, axis, coord)
        if verdict is not None:
            verdicts.append((verdict, extra))

    # Read budget use from the final pass only; earlier passes and trials are
    # not drawn. Count fallbacks from the published routes, which include a
    # stream drawn without a search.
    fallback = sum(1 for s in eligible if s.route is not None and s.route.used_fallback)
    return SheetReport(
        sheet=name,
        units=len(fs.units),
        streams=len(fs.streams),
        nodes=len(graph.nodes),
        routed=len(rows),
        undrawn=undrawn,
        fallback=fallback,
        auto_routed=len(eligible),
        budget_ratios=[c.expansions / c.budget for c in final_pass],
        rows=rows,
        crossings=crossings,
        overlaps=overlaps,
        self_crossings=self_crossings,
        verdicts=verdicts,
    )


def measure_stem(stem: str) -> SheetReport:
    """Measure one shipped example.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    SheetReport
        Measurements of the routed example.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        fs, _kwargs = gallery.flowsheet(stem)
    return measure_sheet(fs, stem)


# ---------------------------------------------------------------------------
# Build probe sheets with known bend counts, a sealed projection (#355), and
# forced crossings.
# ---------------------------------------------------------------------------


def _facing_pair(bx: float, perp_offset: float, mirror_b: bool = False) -> Flowsheet:
    """Build two pumps joined discharge to suction.

    B is pinned by its suction nozzle, because the two ports sit at
    different heights within the pump symbol.

    Parameters
    ----------
    bx : float
        X coordinate of B's suction.
    perp_offset : float
        Vertical offset of B's suction from A's discharge; 0 keeps them level.
    mirror_b : bool, optional
        Mirror B so its suction faces east.

    Returns
    -------
    Flowsheet
        Unrouted two-pump sheet.
    """
    from pandid.portgeom import port_anchor

    fs = Flowsheet("probe")
    a = fs.add(Pump("A")).pin(x=0, y=0)
    fs.layout()
    ay = port_anchor(a, a.frame, "discharge")[1]
    b = fs.add(Pump("B")).pin(x=bx, port="suction", y=ay + perp_offset,
                               mirrored=("x" if mirror_b else False))
    fs.connect(a.discharge, b.suction)
    return fs


def synthetic_sheets() -> list[tuple[str, Flowsheet]]:
    """Build the probe sheets.

    Returns
    -------
    list[tuple[str, Flowsheet]]
        Name and unrouted sheet for each probe.
    """
    sheets = []

    # Face the nozzles on one row: minimum 0 bends.
    sheets.append(("facing_level", _facing_pair(300, 0)))

    # Face the nozzles with B 150 px lower: minimum 2 bends.
    sheets.append(("facing_offset", _facing_pair(300, 150)))

    # Put B behind A's outward direction: minimum 4 bends.
    sheets.append(("facing_behind", _facing_pair(-300, 150)))

    # Mirror B so both nozzles face east: minimum 2 bends.
    sheets.append(("same_side", _facing_pair(300, 150, mirror_b=True)))

    # Rotate B so its suction faces north: minimum 1 bend.
    fs = Flowsheet("probe")
    a = fs.add(Pump("A")).pin(x=0, y=0)
    b = fs.add(Pump("B")).pin(x=300, y=200, orientation=90)
    fs.connect(a.discharge, b.suction)
    sheets.append(("perpendicular", fs))

    # Place a balloon over the feed's nominal escape node (#355). The router
    # shortens the stub and routes around the balloon.
    fs = Flowsheet("probe-355")
    f = fs.add(Feed("F")).pin(x=60, y=100)
    p = fs.add(Product("P")).pin(x=400, y=100)
    fs.connect(f.outlet, p.inlet)
    fs.add_instrument("FCI", 1, near=f)
    sheets.append(("sealed_projection_355", fs))

    # Run one stream across three parallel streams to force crossings.
    fs = Flowsheet("probe-cross")
    for i in range(3):
        src = fs.add(Feed(f"F{i}")).pin(x=0, y=i * 60)
        dst = fs.add(Product(f"P{i}")).pin(x=400, y=i * 60)
        fs.connect(src.outlet, dst.inlet)
    v = fs.add(Valve("V-X")).pin(x=200, y=400)
    side = fs.add(Feed("Side")).pin(x=200, y=-120)
    out = fs.add(Product("Out")).pin(x=200, y=550)
    fs.connect(side.outlet, v.inlet)
    fs.connect(v.outlet, out.inlet)
    sheets.append(("crossing_stress", fs))

    return sheets


# ---------------------------------------------------------------------------
# Aggregate and report.
# ---------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    """Format a ratio as a whole percentage.

    Parameters
    ----------
    n, d : int
        Numerator and denominator.

    Returns
    -------
    str
        Percentage, or ``"n/a"`` for a zero denominator.
    """
    return f"{100 * n / d:.0f}%" if d else "n/a"


def _fmt(x: Optional[float], nd: int = 2) -> str:
    """Format an optional number to fixed decimals.

    Parameters
    ----------
    x : float or None
        Value to format.
    nd : int, optional
        Decimal places.

    Returns
    -------
    str
        Formatted value, or ``"n/a"`` for ``None``.
    """
    return f"{x:.{nd}f}" if x is not None else "n/a"


def print_sheet_table(reports: list[SheetReport]) -> None:
    """Print one row of route measurements per sheet.

    Parameters
    ----------
    reports : list[SheetReport]
        Measured sheets.
    """
    header = (
        f"{'sheet':<24}{'units':>6}{'strm':>6}{'routed':>7}{'undrwn':>7}{'fbck':>6}"
        f"{'bnd~0':>7}{'bnd+avg':>8}{'bnd+max':>8}{'len avg':>9}{'len max':>9}"
        f"{'cross':>7}{'ovrlap':>7}{'budget%':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        # Exclude manual routes: the bend and length bounds assume the
        # router's outward nozzle stubs.
        with_min = [(row, row.min_bends) for row in r.rows if row.min_bends is not None and not row.is_manual]
        excess = [row.actual_bends - mb for row, mb in with_min]
        optimal = sum(1 for e in excess if e == 0)
        len_ratios = [row.length / row.manhattan for row in r.rows
                      if row.manhattan and row.manhattan > 0 and not row.is_manual]
        budget_max = max(r.budget_ratios) * 100 if r.budget_ratios else 0.0
        print(
            f"{r.sheet:<24}{r.units:>6}{r.streams:>6}{r.routed:>7}{len(r.undrawn):>7}{r.fallback:>6}"
            f"{_pct(optimal, len(with_min)):>7}"
            f"{_fmt(statistics.mean(excess) if excess else None):>8}"
            f"{(max(excess) if excess else 0):>8}"
            f"{_fmt(statistics.mean(len_ratios) if len_ratios else None, 3):>9}"
            f"{_fmt(max(len_ratios) if len_ratios else None, 3):>9}"
            f"{len(r.crossings):>7}{len(r.overlaps):>7}{budget_max:>7.1f}%"
        )
    print("-" * len(header))


def print_crossing_summary(reports: list[SheetReport]) -> None:
    """Print crossing totals and alternative-route verdicts.

    Parameters
    ----------
    reports : list[SheetReport]
        Measured sheets.
    """
    total = sum(len(r.crossings) for r in reports)
    verdicts: dict[str, int] = {}
    extra_costly = []
    for r in reports:
        for v, extra in r.verdicts:
            verdicts[v] = verdicts.get(v, 0) + 1
            if v == "costly" and extra is not None:
                extra_costly.append(extra)
    tested = sum(verdicts.values())
    print(f"\ncrossings: {total} total, {tested} tested for an alternative route")
    for v in ("avoidable", "costly", "forced"):
        print(f"  {v:<10} {verdicts.get(v, 0)}")
    if extra_costly:
        print(f"  costly ones needed a median +{statistics.median(extra_costly):.0f}px to clear")
    self_x = sum(r.self_crossings for r in reports)
    overlaps = sum(len(r.overlaps) for r in reports)
    print(f"self-crossings: {self_x}   residual overlaps: {overlaps}")


def print_worst(reports: list[SheetReport], n: int) -> None:
    """Print the worst streams by excess bends and length, then fallbacks.

    Parameters
    ----------
    reports : list[SheetReport]
        Measured sheets.
    n : int
        Streams listed per category.
    """
    all_rows = [row for r in reports for row in r.rows]
    with_min = [(row, row.min_bends) for row in all_rows if row.min_bends is not None and not row.is_manual]
    print(f"\nworst {n} by excess bends (actual - geometric minimum):")
    for row, mb in sorted(with_min, key=lambda pair: pair[0].actual_bends - pair[1], reverse=True)[:n]:
        print(f"  {row.sheet:<24}{row.name:<12} actual={row.actual_bends} min={mb}")

    with_len = [(row, row.manhattan) for row in all_rows
                if row.manhattan and row.manhattan > 0 and not row.is_manual]
    print(f"\nworst {n} by length ratio (drawn / Manhattan):")
    for row, man in sorted(with_len, key=lambda pair: pair[0].length / pair[1], reverse=True)[:n]:
        print(f"  {row.sheet:<24}{row.name:<12} ratio={row.length / man:.2f} "
              f"({row.length:.0f}px vs {man:.0f}px)")

    fallbacks = [row for row in all_rows if row.is_fallback]
    if fallbacks:
        print(f"\n{len(fallbacks)} stream(s) drawn by the fallback L, not a found route:")
        for row in fallbacks:
            print(f"  {row.sheet:<24}{row.name}")


def print_undrawn(reports: list[SheetReport]) -> None:
    """Print the streams left without a route.

    Parameters
    ----------
    reports : list[SheetReport]
        Measured sheets.
    """
    undrawn = [(r.sheet, msg) for r in reports for msg in r.undrawn]
    if not undrawn:
        return
    print(f"\n{len(undrawn)} stream(s) left fully undrawn (route() warned why):")
    for sheet, msg in undrawn:
        print(f"  {sheet}: {msg}")


def main() -> None:
    """Parse the command line, measure the sheets, and print the report.

    Raises
    ------
    SystemExit
        If a named example does not exist.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", nargs="*", help="example stems; default is all of them")
    ap.add_argument("--synthetic", action="store_true", help="run only the synthetic probe sheets")
    ap.add_argument("--worst", type=int, default=10, help="offenders listed per category (default 10)")
    args = ap.parse_args()

    if args.synthetic:
        reports = []
        for name, fs in synthetic_sheets():
            reports.append(measure_sheet(fs, name))
        print(f"synthetic probes ({len(reports)} sheets)")
    else:
        known = gallery.sheets()
        stems = args.sheet or known
        for stem in stems:
            if stem not in known:
                raise SystemExit(f"no such example: {stem}\nknown sheets: {', '.join(known)}")
        reports = [measure_stem(stem) for stem in stems]

    print_sheet_table(reports)
    print_crossing_summary(reports)
    print_undrawn(reports)
    print_worst(reports, args.worst)


if __name__ == "__main__":
    main()
