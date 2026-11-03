"""Route automatic streams orthogonally between placed nozzles."""

import math
import warnings
from collections import Counter
from typing import Protocol, TYPE_CHECKING

from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.routing.astar import CrossingIndex
    from pandid.streams import Stream

__all__ = ["Router", "DefaultRouter"]

#: Cost of one used graph edge for the streams routed after it.
LANE_PENALTY = 2000.0

#: Crossing charge for a stream rerouted against every other route.
RIPUP_CROSSING_PENALTY = 1000.0

#: Search expansions a reroute may spend.
RIPUP_BUDGET = 20_000

#: Bends a reroute may add per crossing it removes.
RIPUP_BENDS_PER_CROSSING = 1

#: Gap under which a rerouted line touches another line or a unit.
RIPUP_CLEARANCE = 12.0


class Router(Protocol):
    """Define the interface ``Flowsheet.route`` requires of a router."""

    def route(self, fs: "Flowsheet") -> None:
        """Route every stream and store the route on the stream.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames.
        """


def _clamp_projection(
    anchor: tuple[float, float],
    proj: tuple[float, float],
    d: str,
    target: tuple[float, float],
    nodes: set[tuple[float, float]],
) -> tuple[float, float]:
    """Clamp an escape node to the peer's lane if the stub crosses it.

    Parameters
    ----------
    anchor : tuple[float, float]
        Port anchor on the unit body.
    proj : tuple[float, float]
        Nominal escape node.
    d : str
        Outward port direction.
    target : tuple[float, float]
        Escape node at the other end of the stream.
    nodes : set[tuple[float, float]]
        Visibility graph nodes.

    Returns
    -------
    tuple[float, float]
        Clamped escape node, or ``proj``.
    """
    ax, ay = anchor
    px, py = proj
    tx, ty = target
    if d in ("N", "S"):
        lo, hi = (py, ay) if d == "N" else (ay, py)
        cand = (ax, ty) if lo < ty < hi else proj
    else:
        lo, hi = (px, ax) if d == "W" else (ax, px)
        cand = (tx, ay) if lo < tx < hi else proj
    # Keep the nominal node if the graph has no node on that lane.
    return cand if cand in nodes else proj


def _fallback_path(
    start: tuple[float, float],
    start_proj: tuple[float, float],
    goal_proj: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list,
    crossing_index: "CrossingIndex | None" = None,
) -> list[tuple[float, float]]:
    """Return the L-shaped route drawn when no path is found.

    Of the two corner orders, pick the one with fewer segments hitting
    an obstacle, then fewer recorded-line crossings, then across-first.

    Parameters
    ----------
    start : tuple[float, float]
        Source port anchor.
    start_proj : tuple[float, float]
        Source escape node.
    goal_proj : tuple[float, float]
        Destination escape node.
    goal : tuple[float, float]
        Destination port anchor.
    obstacles : list
        Obstacles whose hits are counted.
    crossing_index : CrossingIndex or None, optional
        Routes already drawn in this pass.

    Returns
    -------
    list[tuple[float, float]]
        Route waypoints from ``start`` to ``goal``.
    """
    def through(corner: tuple[float, float]) -> list[tuple[float, float]]:
        """Return the route that turns at ``corner``.

        Parameters
        ----------
        corner : tuple[float, float]
            Turning point between the two escape nodes.

        Returns
        -------
        list[tuple[float, float]]
            Route waypoints, consecutive repeats dropped.
        """
        pts = [start]
        for point in (start_proj, corner, goal_proj, goal):
            if point != pts[-1]:
                pts.append(point)
        return pts

    def score(pts: list[tuple[float, float]]) -> tuple[int, int]:
        """Return a route's obstacle hits and line crossings.

        Parameters
        ----------
        pts : list[tuple[float, float]]
            Route waypoints.

        Returns
        -------
        tuple[int, int]
            Segments hitting an obstacle, and recorded-line crossings.
        """
        obstacle_hits = sum(
            any(o.intersects_segment(a[0], a[1], b[0], b[1]) for o in obstacles)
            for a, b in zip(pts, pts[1:])
        )
        line_hits = (
            sum(crossing_index.crossings_along(a, b) for a, b in zip(pts, pts[1:]))
            if crossing_index is not None
            else 0
        )
        return obstacle_hits, line_hits

    across = through((goal_proj[0], start_proj[1]))
    down = through((start_proj[0], goal_proj[1]))
    return down if score(down) < score(across) else across


def _record_route(crossing_index: "CrossingIndex", waypoints: list[tuple[float, float]], manual: bool) -> None:
    """Record one route in the crossing index.

    A manual route is recorded one orthogonal run at a time, skipping
    its diagonal legs.

    Parameters
    ----------
    crossing_index : CrossingIndex
        Index to record into.
    waypoints : list[tuple[float, float]]
        Route waypoints.
    manual : bool
        Whether the route was set by hand.

    Raises
    ------
    ValueError
        If ``manual`` is false and a segment is diagonal.
    """
    if not manual:
        crossing_index.record(waypoints)
        return
    run_start = 0
    for i in range(1, len(waypoints)):
        (x1, y1), (x2, y2) = waypoints[i - 1], waypoints[i]
        if x1 != x2 and y1 != y2:
            if i - run_start >= 2:
                crossing_index.record(waypoints[run_start:i])
            run_start = i
    if len(waypoints) - run_start >= 2:
        crossing_index.record(waypoints[run_start:])


def _simplify(
    path: list[tuple[float, float]],
    start_proj: tuple[float, float],
    goal_proj: tuple[float, float],
) -> list[tuple[float, float]]:
    """Drop collinear waypoints but keep both escape nodes.

    Parameters
    ----------
    path : list[tuple[float, float]]
        Route waypoints.
    start_proj, goal_proj : tuple[float, float]
        Escape nodes to keep.

    Returns
    -------
    list[tuple[float, float]]
        Simplified waypoints.
    """
    simplified = [path[0]]
    for i in range(1, len(path)-1):
        prev = simplified[-1]
        curr = path[i]
        nxt = path[i+1]
        if curr == start_proj or curr == goal_proj:
            simplified.append(curr)
            continue
        if (prev[0] == curr[0] == nxt[0]) or (prev[1] == curr[1] == nxt[1]):
            continue
        simplified.append(curr)
    if len(path) > 1:
        simplified.append(path[-1])
    return simplified


def _apart(
    a: tuple[float, float], b: tuple[float, float], x0: float, x1: float, y0: float, y1: float
) -> float:
    """Return the distance from segment a-b to a box.

    Parameters
    ----------
    a, b : tuple[float, float]
        Segment ends.
    x0, x1, y0, y1 : float
        Box left, right, top and bottom.

    Returns
    -------
    float
        Euclidean gap, 0 where they touch or overlap.
    """
    gx = max(0.0, x0 - max(a[0], b[0]), min(a[0], b[0]) - x1)
    gy = max(0.0, y0 - max(a[1], b[1]), min(a[1], b[1]) - y1)
    return math.hypot(gx, gy)


def _meets(
    paths: dict[int, list[tuple[float, float]]], keys: set[int]
) -> tuple[int, Counter[tuple[int, int]]]:
    """Count crossings and contacts between paths, each pair touching ``keys``.

    A contact is two runs that come within :data:`RIPUP_CLEARANCE` of
    each other without crossing, or cross within it of either run's end.

    Parameters
    ----------
    paths : dict[int, list[tuple[float, float]]]
        Waypoints by stream id.
    keys : set[int]
        Stream ids whose pairs are counted.

    Returns
    -------
    tuple[int, Counter[tuple[int, int]]]
        Crossings, then contacts by stream id pair.
    """
    from pandid.routing.metrics import crossing_point
    segs = [(k, a, b) for k, pts in paths.items() for a, b in zip(pts, pts[1:])
            if a != b and (a[0] == b[0] or a[1] == b[1])]
    crossings = 0
    contacts: Counter[tuple[int, int]] = Counter()
    for k1, a1, b1 in segs:
        if k1 not in keys:
            continue
        for k2, a2, b2 in segs:
            if k2 == k1 or (k2 in keys and k2 < k1):
                continue
            pair = (min(k1, k2), max(k1, k2))
            if (a1[1] == b1[1]) != (a2[1] == b2[1]):
                h, v = ((a1, b1), (a2, b2)) if a1[1] == b1[1] else ((a2, b2), (a1, b1))
                p = crossing_point(h, v)
                if p is not None:
                    crossings += 1
                    if min(abs(p[0] - h[0][0]), abs(p[0] - h[1][0]),
                           abs(p[1] - v[0][1]), abs(p[1] - v[1][1])) <= RIPUP_CLEARANCE + 1e-6:
                        contacts[pair] += 1
                    continue
            box = (min(a2[0], b2[0]), max(a2[0], b2[0]), min(a2[1], b2[1]), max(a2[1], b2[1]))
            if _apart(a1, b1, *box) <= RIPUP_CLEARANCE + 1e-6:
                contacts[pair] += 1
    return crossings, contacts


def _improves(
    before: dict[int, list[tuple[float, float]]],
    after: dict[int, list[tuple[float, float]]],
) -> bool:
    """Return whether ``after`` crosses less and is no worse otherwise.

    Fewer crossings, no new contact between two streams, and at most
    :data:`RIPUP_BENDS_PER_CROSSING` added bends per crossing removed.

    Parameters
    ----------
    before, after : dict[int, list[tuple[float, float]]]
        Separated waypoints by stream id.

    Returns
    -------
    bool
        Whether to keep ``after``.
    """
    from pandid.routing.metrics import real_bends

    changed = {k for k in after if after[k] != before.get(k)}
    x0, c0 = _meets(before, changed)
    x1, c1 = _meets(after, changed)
    added = sum(real_bends(after[k]) - real_bends(before[k]) for k in changed)
    return x1 < x0 and not c1 - c0 and added <= RIPUP_BENDS_PER_CROSSING * (x0 - x1)


def _refuse_non_finite_geometry(fs: "Flowsheet") -> None:
    """Check that every placed frame is finite.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to check.

    Raises
    ------
    ValueError
        If a placed frame holds a NaN or an infinity.
    """
    for unit in fs.units:
        frame = unit.frame
        if frame is None:
            continue
        for field in ("x", "y", "w", "h"):
            value = getattr(frame, field, 0.0)
            if not math.isfinite(value):
                raise ValueError(
                    f"{unit.name} has a non-finite {field}={value!r}, which "
                    f"nothing on the sheet can be measured against. Check the "
                    f"pin() that placed it and the width and height it was "
                    f"given."
                )


class DefaultRouter:
    """Route automatic streams on a visibility graph.

    Parameters
    ----------
    recover_exits : bool, default=True
        Use the furthest reachable node on each stub, else an L route.

    Attributes
    ----------
    recover_exits : bool
        Escape-node recovery option.
    """

    def __init__(self, *, recover_exits: bool = True) -> None:  # numpydoc ignore=GL08
        self.recover_exits = recover_exits

    def route(self, fs: "Flowsheet") -> None:
        """Route and separate the sheet's automatic streams.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames and nozzle faces.

        Raises
        ------
        ValueError
            If a frame is non-finite, a port has no owner, or a face is
            unreachable.
        RuntimeError
            If a path search exceeds its expansion budget.

        Warns
        -----
        UserWarning
            If an end has no frame or anchor; the stream is skipped.
        """
        from pandid.routing.visibility import VisibilityGraph, share_escape_room
        from pandid.routing.astar import CrossingIndex, find_path
        from pandid.routing.separation import preview_separated_waypoints

        _refuse_non_finite_geometry(fs)
        graph = VisibilityGraph(fs)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
        crossing_index = CrossingIndex()
        routed: list["Stream"] = []
        # Search ends and found path of each automatic stream, by id.
        searches: dict[int, tuple] = {}
        found: dict[int, list[tuple[float, float]]] = {}

        def index_of(streams: list["Stream"]) -> CrossingIndex:
            """Return a crossing index of the streams' separated waypoints.

            Parameters
            ----------
            streams : list[Stream]
                Streams with a route.

            Returns
            -------
            CrossingIndex
                Index of every stream's previewed separated waypoints.
            """
            preview = preview_separated_waypoints(streams)
            index = CrossingIndex()
            for s in streams:
                # Every routed stream has a route.
                assert s.route is not None
                wp = preview.get(id(s), s.route.waypoints)
                _record_route(index, wp, s.route.manual)
            return index

        def settle(stream: "Stream") -> None:
            """Add a routed stream and rebuild the crossing index.

            Parameters
            ----------
            stream : Stream
                Stream with a route.
            """
            nonlocal crossing_index
            routed.append(stream)
            crossing_index = index_of(routed)

        def hugs(stream: "Stream", pts: list[tuple[float, float]]) -> set[int]:
            """Return the units other than its ends that ``pts`` passes close to.

            Parameters
            ----------
            stream : Stream
                Stream the waypoints belong to.
            pts : list[tuple[float, float]]
                Waypoints.

            Returns
            -------
            set[int]
                Ids of the units passed.
            """
            ends = (stream.source.owner, stream.dest.owner)
            return {id(u) for u, r in graph.body_obstacles if u not in ends
                    for a, b in zip(pts, pts[1:])
                    if _apart(a, b, r.x_min, r.x_max, r.y_min, r.y_max) <= RIPUP_CLEARANCE + 1e-6}

        def charge(path: list[tuple[float, float]], amount: float) -> None:
            """Add ``amount`` to the penalty of each edge on ``path``, both ways.

            Parameters
            ----------
            path : list[tuple[float, float]]
                Path through graph nodes.
            amount : float
                Penalty to add.
            """
            for u_node, v_node in zip(path, path[1:]):
                edge_penalties[(u_node, v_node)] = edge_penalties.get((u_node, v_node), 0.0) + amount
                edge_penalties[(v_node, u_node)] = edge_penalties.get((v_node, u_node), 0.0) + amount

        for stream in fs.streams:
            if stream.route and stream.route.manual:
                settle(stream)
                continue

            src_u = stream.source.owner
            dst_u = stream.dest.owner
            if src_u is None or dst_u is None:
                orphan = stream.source if src_u is None else stream.dest
                raise ValueError(
                    f"stream {stream.name!r} cannot be routed: port "
                    f"{orphan.name!r} belongs to no unit."
                )

            if src_u.frame is None or dst_u.frame is None:
                unplaced = src_u if src_u.frame is None else dst_u
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: {unplaced.name!r} "
                    f"has no frame, so there is no geometry to route between. "
                    f"Call layout() before route().",
                    stacklevel=2,
                )
                continue

            start = graph.port_anchors.get((src_u.name, stream.source.name))
            goal = graph.port_anchors.get((dst_u.name, stream.dest.name))
            if start is None or goal is None:
                missing = (f"{src_u.name}.{stream.source.name}" if start is None
                           else f"{dst_u.name}.{stream.dest.name}")
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: the visibility "
                    f"graph carries no anchor for port {missing}.",
                    stacklevel=2,
                )
                continue

            start_dir = graph.port_dirs[(src_u.name, stream.source.name)]
            goal_dir = graph.port_dirs[(dst_u.name, stream.dest.name)]

            start_proj = graph.port_projs[(src_u.name, stream.source.name)]
            goal_proj = graph.port_projs[(dst_u.name, stream.dest.name)]

            # Clamp each stand-off to the peer's lane, then share the
            # room between two facing ports.
            start_proj = _clamp_projection(start, start_proj, start_dir, goal_proj, graph.nodes)
            goal_proj = _clamp_projection(goal, goal_proj, goal_dir, start_proj, graph.nodes)
            start_proj, goal_proj = share_escape_room(
                start, start_dir, start_proj, goal, goal_dir, goal_proj, graph.obstacles
            )

            clear_stubs = True
            if self.recover_exits:
                clear_start = graph.reachable_projection(start, start_proj, start_dir, src_u)
                clear_goal = graph.reachable_projection(goal, goal_proj, goal_dir, dst_u)
                if clear_start is not None and clear_goal is not None:
                    start_proj, goal_proj = clear_start, clear_goal
                else:
                    clear_stubs = False

            is_recycle = getattr(stream, "is_recycle", False)
            path = []
            if clear_stubs:
                searches[id(stream)] = (start, goal, start_proj, goal_proj, start_dir, goal_dir, is_recycle)
                path = find_path(
                    graph, start_proj, goal_proj, start_dir, goal_dir,
                    edge_penalties, is_recycle, crossing_index,
                )
            path_found = bool(path)

            if path:
                path = [start] + path + [goal]
                found[id(stream)] = path
                charge(path, LANE_PENALTY)
            else:
                path = _fallback_path(
                    start, start_proj, goal_proj, goal, graph.obstacles, crossing_index
                )

            stream.route = Route(
                waypoints=_simplify(path, start_proj, goal_proj), used_fallback=not path_found
            )

            settle(stream)

        # Reroute each crossing stream against every other route, and
        # keep the new route where the sheet improves.
        preview = preview_separated_waypoints(routed)
        for stream in routed:
            if id(stream) not in searches:
                continue
            index = index_of([s for s in routed if s is not stream])
            own = preview[id(stream)]
            if not any(index.crossings_along(a, b) for a, b in zip(own, own[1:])):
                continue
            old_route, old_path = stream.route, found.get(id(stream), [])
            charge(old_path, -LANE_PENALTY)
            start, goal, start_proj, goal_proj, start_dir, goal_dir, is_recycle = searches[id(stream)]
            try:
                path = find_path(
                    graph, start_proj, goal_proj, start_dir, goal_dir,
                    edge_penalties, is_recycle, index, RIPUP_CROSSING_PENALTY, RIPUP_BUDGET,
                )
            except RuntimeError:  # Keep the old route past the budget.
                path = []
            if path:
                path = [start, *path, goal]
                stream.route = Route(waypoints=_simplify(path, start_proj, goal_proj))
                after = preview_separated_waypoints(routed)
                if (_improves(preview, after)
                        and hugs(stream, after[id(stream)]) <= hugs(stream, preview[id(stream)])):
                    preview, found[id(stream)] = after, path
                    charge(path, LANE_PENALTY)
                    continue
            stream.route = old_route
            charge(old_path, LANE_PENALTY)

        # Separate parallel segments that share a lane.
        from pandid.routing.separation import separate_streams
        separate_streams(fs)
