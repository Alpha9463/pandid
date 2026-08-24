#!/usr/bin/env python3
"""Measure whether the routes ``route()`` draws are *good* drawings, not just fast ones.

``route_bench.py`` times ``layout()`` and ``route()``; this asks the question
speed says nothing about: given the sheet it was handed, did the router draw a
line a draughtsman would draw?

    python scripts/route_quality.py                   # every example
    python scripts/route_quality.py 11_ethanol_pid     # one of them
    python scripts/route_quality.py --synthetic        # the probe sheets only
    python scripts/route_quality.py --worst 15         # widen the offender lists

Five things are measured, each against a bound computed from the geometry
itself rather than a fixed threshold, so a sheet with tighter equipment reads
no worse than a roomy one for the same quality of routing:

- **bends**, against the fewest an orthogonal path leaving the source nozzle
  along its outward face and arriving at the destination against its can
  possibly have (:func:`min_bends`) -- zero for two nozzles facing each other
  down one lane, and never fewer than the geometry allows regardless of what
  is in the way;
- **length**, against the Manhattan distance between the two nozzles, which
  bounds *every* orthogonal path between them, direction and obstacles alike;
- **crossings** between two different streams' drawn segments, and, for each,
  whether the *later*-routed stream (the one whose search saw the earlier
  one's ``edge_penalties``) had a same-or-near-length alternative that misses
  it -- found by re-running its own search with that one lane barred, so an
  "avoidable" verdict is never asserted, only demonstrated;
- **the fallback path**: how many auto-routed streams got the L
  ``_fallback_path`` draws because ``find_path`` returned nothing, which is
  issue #355's territory -- see :class:`Recorder`;
- **the expansion budget** (``pandid/routing/astar.py``'s
  ``max(50_000, 16 * nodes)``), as a fraction actually spent per search, so a
  search that nearly ran out reads as different from one that walked away
  from most of its ceiling.

Every metric reads ``stream.route.waypoints`` after ``route()`` returns --
the drawn geometry, offsets from ``separate_streams`` included -- except the
avoidability re-route, which necessarily replays the pre-separation search
(see :class:`Recorder`'s docstring for why that is the more honest ground to
test on, and why it does not change the headline crossing count).

Nothing here changes a route. This is read-only over what ``route()`` already
decided; the only extra work it does is a handful of *additional* searches,
each with one lane barred, purely to answer "was there another way".
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
from pandid.units import Feed, Product, Pump, Valve  # noqa: E402
import pandid.routing.astar as astar_mod  # noqa: E402
from pandid.routing.astar import (  # noqa: E402
    MAX_EXPANSIONS_PER_NODE,
    MIN_EXPANSION_BUDGET,
    OPPOSITE,
    find_path,
)
from pandid.routing.visibility import TRAVEL, VisibilityGraph  # noqa: E402

Point = tuple[float, float]

# ---------------------------------------------------------------------------
# The geometric bend minimum
# ---------------------------------------------------------------------------


def min_bends(a: Point, dir_a: Optional[str], b: Point, dir_b: Optional[str]) -> Optional[int]:
    """The fewest direction changes any orthogonal path from *a* to *b* can
    have, leaving *a* along its outward face ``dir_a`` and entering *b*
    against its outward face ``dir_b`` -- with no obstacle in the world.
    ``None`` if either direction is unknown.

    A real path also carries the router's fixed escape stubs (anchor to
    projection, at each end, always drawn along the port's own outward
    normal), so the true final approach into *b* always travels
    ``OPPOSITE[dir_b]``. That, and the constraint on the very first
    segment leaving *a*, are the only two things fixed; between them the
    path is free, so this is the two-tangent minimum-bend problem for
    orthogonal routing, not a heuristic.

    Every orthogonal path alternates axis at each bend (two consecutive
    segments on the same axis are not a bend, they are one line), so a path
    of *k* bends ends on the x-axis if ``k`` is even and the y-axis if
    ``k`` is odd, when it starts on the x-axis (and the reverse starting on
    y). Matching that parity against whether *a* and *b* leave/arrive on
    the same axis or different ones fixes which counts are even reachable,
    which is most of this function; the rest is one feasibility check per
    case, proved achievable by construction (freely-chosen positive leg
    lengths always solve the resulting linear equation) rather than merely
    guessed at:

    - **same axis, facing** (``dir_b`` is ``dir_a``'s opposite -- two
      nozzles pointed at each other): 0 if they are already dead level and
      *b* is ahead of *a*; 2 if *b* is ahead but off level (a single jog
      closes the offset); 4 if *b* is behind *a* along that axis (nothing
      shorter turns a path fully around).
    - **same axis, same-facing** (both nozzles face the same compass
      direction -- a "same side" pair): 2 whenever they are off level (the
      single jog's two free leg lengths solve for *any* signed distance
      along the axis, so *b* being "behind" costs nothing extra here,
      unlike the facing case); 4 when they are dead level too (the jog has
      nothing to jog around, so the detour needs its own out-and-back).
    - **perpendicular** (one leaves horizontal, the other arrives
      vertical, or vice versa): 1 if the single L-corner -- *b*'s
      coordinate on *a*'s axis, *a*'s coordinate on *b*'s axis -- is ahead
      of *a* along *a*'s axis and ahead of *b* along *b*'s (the ordinary
      case); 3 otherwise, and never 2, since a 2-bend path would end on
      the wrong axis to arrive along ``dir_b`` at all.
    """
    if dir_a is None or dir_b is None:
        return None
    s_axis, s_sign = TRAVEL[dir_a]
    t_dir = OPPOSITE[dir_b]  # the direction the final stub actually travels, into b
    t_axis, t_sign = TRAVEL[t_dir]
    dx, dy = b[0] - a[0], b[1] - a[1]
    delta = (dx, dy)
    eps = 1e-6

    if s_axis == t_axis:
        perp = delta[1 - s_axis]
        along = s_sign * delta[s_axis]
        if s_sign == t_sign:  # facing: a straight line is on the table
            if abs(perp) < eps and along >= -eps:
                return 0
            return 2 if along > eps else 4
        else:  # same-facing: never straight, but the jog absorbs any along-axis distance
            return 2 if abs(perp) > eps else 4

    # Perpendicular axes: the one-corner L, or the three-segment detour around it.
    # Never 0: a single segment has one axis, and leaving along s while
    # arriving along the different axis t is two directions no one segment
    # can be, however the corner happens to fall -- including the boundary
    # where it lands exactly on a or on b, where the corner's two defining
    # deltas would let a careless check divide by that coincidence and call
    # it a straight line. Strict inequality is what keeps that boundary out
    # of the 1-bend case rather than folding it into a false 0.
    ahead_on_s = s_sign * (b[s_axis] - a[s_axis]) > eps
    ahead_on_t = t_sign * (b[t_axis] - a[t_axis]) > eps
    return 1 if (ahead_on_s and ahead_on_t) else 3


# ---------------------------------------------------------------------------
# Reading the drawn geometry
# ---------------------------------------------------------------------------


def waypoint_segments(waypoints: list[Point]) -> list[tuple[Point, Point, str]]:
    """(p1, p2, axis) for every non-degenerate consecutive pair; axis is 'h' or 'v'.

    ``route()`` never drops a projection point, even a collinear one (the
    comment by ``simplified.append`` in ``pandid/routing/__init__.py`` says
    why), so a waypoint list can hold points that do not actually bend.
    Segment axis is the honest read; bend counting below only trusts a
    change between two of *these*, not a change of waypoint index.
    """
    segs = []
    for p1, p2 in zip(waypoints, waypoints[1:]):
        if p1 == p2:
            continue
        if p1[1] == p2[1]:
            segs.append((p1, p2, "h"))
        elif p1[0] == p2[0]:
            segs.append((p1, p2, "v"))
        # else: off-axis -- shouldn't happen on a router-drawn route; skip rather than crash.
    return segs


def real_bends(waypoints: list[Point]) -> int:
    """Direction changes between real segments -- see ``waypoint_segments``."""
    segs = waypoint_segments(waypoints)
    dirs = []
    for p1, p2, axis in segs:
        dirs.append(("E" if p2[0] > p1[0] else "W") if axis == "h" else ("S" if p2[1] > p1[1] else "N"))
    return sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)


def path_length(points: list[Point]) -> float:
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:]))


def crossing_point(h: tuple[Point, Point], v: tuple[Point, Point]) -> Optional[Point]:
    """Where horizontal segment *h* and vertical segment *v* properly cross --
    an interior point of both, never a shared endpoint (a junction, not a
    crossing) and never a touch (one's endpoint on the other's interior,
    which a branch tee draws on purpose)."""
    y = h[0][1]
    x = v[0][0]
    xlo, xhi = sorted((h[0][0], h[1][0]))
    ylo, yhi = sorted((v[0][1], v[1][1]))
    eps = 1e-6
    if xlo + eps < x < xhi - eps and ylo + eps < y < yhi - eps:
        return (x, y)
    return None


def overlap_length(a: tuple[Point, Point], b: tuple[Point, Point], axis: str) -> float:
    """How much of two same-axis segments coincide -- 0 unless they share a track."""
    i = 1 if axis == "h" else 0
    if abs(a[0][i] - b[0][i]) > 1e-6:
        return 0.0
    j = 1 - i
    alo, ahi = sorted((a[0][j], a[1][j]))
    blo, bhi = sorted((b[0][j], b[1][j]))
    return max(0.0, min(ahi, bhi) - max(alo, blo))


@dataclass
class Crossing:
    h_stream: object
    h_seg: tuple[Point, Point]
    v_stream: object
    v_seg: tuple[Point, Point]
    point: Point


@dataclass
class Overlap:
    a: object
    b: object
    axis: str
    length: float


def find_crossings_and_overlaps(fs: Flowsheet) -> tuple[list[Crossing], list[Overlap], int]:
    """Every proper crossing and every residual overlap between two
    *different* streams' final, drawn segments, plus a count of self-crossings
    (a stream's own route crossing itself -- rare, and reported but not
    otherwise analysed).

    O(streams^2 x segments^2) per sheet; the largest example in the corpus
    (11_ethanol_pid, 93 streams) is comfortably small for that.
    """
    entries: list[tuple[object, tuple[Point, Point, str]]] = []
    for s in fs.streams:
        if not s.route or not s.route.waypoints:
            continue
        for seg in waypoint_segments(s.route.waypoints):
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
# Instrumented find_path: fallback, budget headroom, and the raw search state
# an avoidability re-route needs.
# ---------------------------------------------------------------------------


@dataclass
class Call:
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


class Recorder:
    """Capture every ``find_path`` call made during one ``fs.route()``,
    without changing a single decision it makes.

    Wraps ``pandid.routing.astar.find_path`` for the ``with`` block's
    duration. ``DefaultRouter.route()`` does ``from pandid.routing.astar
    import find_path`` fresh on every call, which is an attribute lookup on
    the module at that moment -- so patching the module's attribute here is
    enough, and nothing in ``pandid/`` has to change to be measured. Restored
    on exit regardless of how the block ends.

    Two things ride along for free because they are already in scope at the
    point ``find_path`` is called: the *exact* ``edge_penalties`` state
    earlier streams left behind (a shallow copy, since values are floats)
    and expansions spent, counted by wrapping ``heapq.heappop`` only for the
    duration of the one nested call -- it is what ``find_path``'s own budget
    check counts, so this reads the same number the router would raise on.

    The recorded ``result`` is the *pre-separation* path: graph nodes only,
    before ``[start] + result + [goal]`` and before ``separate_streams``
    offsets anything sideways by a few pixels to de-overlap parallel runs.
    That is deliberately what :func:`avoidable` re-routes against -- every
    coordinate in it is a member of ``graph.xs`` / ``graph.ys``, so a lane
    to ban can be read straight off it, where the drawn (separated) version
    can sit a few pixels off every lane the graph carries. A crossing
    between two perpendicular segments is not moved by a 6px parallel
    offset, so this changes nothing about which crossings are found --
    only how the alternate-route check for one is carried out.
    """

    def __init__(self) -> None:
        self.calls: list[Call] = []

    def __enter__(self) -> "Recorder":
        self._original = astar_mod.find_path
        recorder = self

        def wrapped(graph, start, goal, start_dir=None, goal_dir=None, edge_penalties=None,
                    is_recycle=False, crossing_index=None):
            count = [0]
            real_heappop = heapq.heappop

            def counting_heappop(heap):
                count[0] += 1
                return real_heappop(heap)

            heapq.heappop = counting_heappop
            try:
                result = recorder._original(graph, start, goal, start_dir, goal_dir, edge_penalties,
                                             is_recycle, crossing_index)
            finally:
                heapq.heappop = real_heappop
            budget = max(MIN_EXPANSION_BUDGET, MAX_EXPANSIONS_PER_NODE * len(graph.nodes))
            recorder.calls.append(
                Call(graph, start, goal, start_dir, goal_dir, dict(edge_penalties or {}), is_recycle,
                     list(result), count[0], budget)
            )
            return result

        astar_mod.find_path = wrapped
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        astar_mod.find_path = self._original


def eligible_streams(fs: Flowsheet, graph: VisibilityGraph) -> list:
    """Streams ``route()`` will call ``find_path`` for, in the same order.

    Replicates ``DefaultRouter.route()``'s filter (manual route, missing
    frame, missing anchor) so the result lines up 1:1 with ``Recorder``'s
    call log -- checked by the caller, not assumed, since a drift here would
    silently misattribute every call downstream of it.
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


# ---------------------------------------------------------------------------
# Avoidability: could the later stream have missed this lane for free?
# ---------------------------------------------------------------------------


def lane_edges(graph: VisibilityGraph, axis: str, track: float) -> list[tuple[Point, Point]]:
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
    """The pre-separation graph lane whose span covers *coord*, read off the
    raw search path -- an exact ``graph.xs``/``graph.ys`` value, not the
    (possibly separation-offset) drawn one."""
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
    """Could *call*'s search have missed the lane its crossing segment is
    on, for the same length or close to it?

    Bars every graph edge on that lane (on top of the exact
    ``edge_penalties`` the real search saw) and re-runs the search. That is
    a strictly harder problem than the real one, so a path found this way is
    never better than the real one for a reason unrelated to the ban --
    only worse or equal, which is what "cost of avoiding it" means.

    Returns ``(None, None)`` when there is nothing to compare (the call
    itself found no path, or the crossing point cannot be matched back to
    one of its own segments -- both defensive, neither expected to fire on
    the corpus); otherwise one of ``"avoidable"`` (an alternative within 2%
    of the original length exists), ``"costly"`` (one exists but is
    longer), or ``"forced"`` (no alternative at all), with the length
    difference in px.
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
# One sheet, fully measured
# ---------------------------------------------------------------------------


@dataclass
class StreamRow:
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
    verdicts: list[tuple[str, Optional[float]]]  # (verdict, extra px) per testable crossing


def measure_sheet(fs: Flowsheet, name: str) -> SheetReport:
    fs.layout()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Recorder() as rec:
            fs.route()

    # ``Flowsheet.route()`` is not one pass over the streams: it places
    # attached instruments and re-runs ``DefaultRouter.route()`` -- a fresh
    # ``VisibilityGraph`` and a fresh ``find_path`` call per eligible stream,
    # since a newly-placed balloon is a new obstacle for every stream, not
    # only the one it hangs off -- until a pass moves nothing, up to
    # ``MAX_PLACEMENT_PASSES``. So the call log holds a whole number of
    # equal-length passes, and only the *last* one produced the routes on
    # the sheet in hand; matching against an earlier pass would credit or
    # blame the router for a graph nothing was finally drawn against.
    graph = rec.calls[-1].graph if rec.calls else VisibilityGraph(fs, margin=15.0)
    eligible = eligible_streams(fs, graph)
    n = len(eligible)
    if n == 0:
        assert not rec.calls, f"{name}: no eligible streams but {len(rec.calls)} calls logged"
        final_pass: list[Call] = []
    else:
        assert len(rec.calls) % n == 0, (
            f"{name}: {len(rec.calls)} calls is not a whole number of "
            f"{n}-stream passes -- eligibility filter drifted from "
            f"DefaultRouter.route(); re-check eligible_streams() against "
            f"pandid/routing/__init__.py."
        )
        final_pass = rec.calls[-n:]
    stream_call = dict(zip((id(s) for s in eligible), final_pass))

    undrawn = [str(w.message) for w in caught if "is left unrouted" in str(w.message)]

    rows: list[StreamRow] = []
    for s in fs.streams:
        if s.route is None or len(s.route.waypoints) < 2:
            continue
        wp = s.route.waypoints
        src_u, dst_u = s.source.owner, s.dest.owner
        a = graph.port_anchors.get((src_u.name, s.source.name))
        b = graph.port_anchors.get((dst_u.name, s.dest.name))
        dir_a = graph.port_dirs.get((src_u.name, s.source.name))
        dir_b = graph.port_dirs.get((dst_u.name, s.dest.name))
        call = stream_call.get(id(s))
        rows.append(StreamRow(
            sheet=name,
            name=s.name,
            actual_bends=real_bends(wp),
            min_bends=min_bends(a, dir_a, b, dir_b) if a and b else None,
            length=path_length(wp),
            manhattan=(abs(b[0] - a[0]) + abs(b[1] - a[1])) if a and b else None,
            is_fallback=bool(call and not call.result),
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

    # Fallback and budget both read the final pass only, for the same reason
    # the call-to-stream matching above does: an earlier pass's search is not
    # what is on the sheet. ``len(rec.calls)`` (every pass) is available to a
    # caller who wants total search effort instead.
    fallback = sum(1 for c in final_pass if not c.result)
    return SheetReport(
        sheet=name,
        units=len(fs.units),
        streams=len(fs.streams),
        nodes=len(graph.nodes),
        routed=len(rows),
        undrawn=undrawn,
        fallback=fallback,
        auto_routed=len(final_pass),
        budget_ratios=[c.expansions / c.budget for c in final_pass],
        rows=rows,
        crossings=crossings,
        overlaps=overlaps,
        self_crossings=self_crossings,
        verdicts=verdicts,
    )


def measure_stem(stem: str) -> SheetReport:
    with contextlib.redirect_stdout(io.StringIO()):
        fs, _kwargs = gallery.flowsheet(stem)
    return measure_sheet(fs, stem)


# ---------------------------------------------------------------------------
# Synthetic probes: controlled two-unit geometries, both to sanity-check
# min_bends against a hand-verifiable answer and to demonstrate #355's
# sealed-projection failure mode in isolation.
# ---------------------------------------------------------------------------


def _facing_pair(bx: float, perp_offset: float, mirror_b: bool = False) -> Flowsheet:
    """A's discharge to B's suction, B's suction placed *perp_offset* px off
    A's discharge on the perpendicular axis (0 keeps the two nozzles level).

    B's suction is placed *by the nozzle*, via ``pin(port="suction", ...)``,
    rather than by guessing the box corner that would put it there: the
    two ports sit at different offsets within a pump's own artwork (10px
    and 30px down from the top, at this writing, and this helper does not
    hardcode either), so pinning the boxes level does not put the *ports*
    level. Reading A's actual discharge anchor and asking B for the same y
    on its suction is what a caller who wants that would do, and it stays
    correct however the artwork is redrawn.
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
    sheets = []

    # Facing, level: A's discharge (E) meets B's suction (W) on the same row.
    # min_bends must read 0, and a good router should draw a straight line.
    sheets.append(("facing_level", _facing_pair(300, 0)))

    # Facing, offset: same directions, B's suction dropped 150px -- min_bends reads 2.
    sheets.append(("facing_offset", _facing_pair(300, 150)))

    # Facing, but B is *behind* A along the direction A leaves in (B's box
    # sits west of A, though the two still face each other) -- min_bends
    # reads 4, the one case that needs a full turn-around.
    sheets.append(("facing_behind", _facing_pair(-300, 150)))

    # Same-side: mirroring B puts its suction on the east face too, so both
    # nozzles face the same compass direction. min_bends reads 2.
    sheets.append(("same_side", _facing_pair(300, 150, mirror_b=True)))

    # Perpendicular: rotate B a quarter turn so its suction faces north
    # instead of west. min_bends reads 1 when B sits ahead on both axes.
    fs = Flowsheet("probe")
    a = fs.add(Pump("A")).pin(x=0, y=0)
    b = fs.add(Pump("B")).pin(x=300, y=200, orientation=90)
    fs.connect(a.discharge, b.suction)
    sheets.append(("perpendicular", fs))

    # https://github.com/Alpha9463/pandid/issues/355: an instrument balloon
    # placed close enough to a feed's own outlet that the feed's escape node
    # lands strictly inside the balloon's own obstacle box. find_path is
    # handed a start node the graph does not carry and returns nothing; the
    # stream is drawn by _fallback_path instead, which validate() then
    # reports as route-crosses-unit. Still open, measured here rather than
    # fixed: this reproduction crosses zero units from the shipped corpus,
    # and the one real consequence (S1 crosses FCI-1) is already a warning a
    # caller sees, not a silent miss.
    fs = Flowsheet("probe-355")
    f = fs.add(Feed("F")).pin(x=60, y=100)
    p = fs.add(Product("P")).pin(x=400, y=100)
    fs.connect(f.outlet, p.inlet)
    fs.add_instrument("FCI", 1, near=f)
    sheets.append(("sealed_projection_355", fs))

    # Crossing stress: three parallel forward streams and one that must jog
    # across all of them to reach a valve tapped off the far side, to give
    # the crossing/avoidability analysis something to measure.
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
# Aggregation and reporting
# ---------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "n/a"


def _fmt(x: Optional[float], nd: int = 2) -> str:
    return f"{x:.{nd}f}" if x is not None else "n/a"


def print_sheet_table(reports: list[SheetReport]) -> None:
    header = (
        f"{'sheet':<24}{'units':>6}{'strm':>6}{'routed':>7}{'undrwn':>7}{'fbck':>6}"
        f"{'bnd~0':>7}{'bnd+avg':>8}{'bnd+max':>8}{'len avg':>9}{'len max':>9}"
        f"{'cross':>7}{'ovrlap':>7}{'budget%':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        # Manual (.via()) routes are excluded: they are the author's own
        # choice, not the router's, and the stub-direction contract
        # min_bends and the Manhattan bound both rest on -- first segment
        # along the source's outward face, last along the destination's --
        # is the router's, not one a hand-written waypoint list has to keep.
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
    undrawn = [(r.sheet, msg) for r in reports for msg in r.undrawn]
    if not undrawn:
        return
    print(f"\n{len(undrawn)} stream(s) left fully undrawn (route() warned why):")
    for sheet, msg in undrawn:
        print(f"  {sheet}: {msg}")


def main() -> None:
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
