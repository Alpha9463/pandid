"""Route automatic streams orthogonally between placed nozzles."""

import math
import warnings
from collections import defaultdict
from typing import Protocol, TYPE_CHECKING

from pandid.deprecation import Deprecation
from pandid.geometry import Route

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pandid.flowsheet import Flowsheet
    from pandid.routing.astar import CrossingIndex
    from pandid.streams import Stream

__all__ = ["DefaultRouter"]


#: Deprecation of the Router protocol.
_ROUTER = Deprecation(
    what="pandid.routing.Router",
    instead="any object with a route(fs) method",
    removed_in="0.3.0",
)

#: Deprecation of DefaultRouter(recover_exits=).
_RECOVER_EXITS = Deprecation(
    what="DefaultRouter(recover_exits=...)",
    instead="DefaultRouter()",
    removed_in="0.3.0",
    note="the router will always recover a blocked stub's exit",
)


class _Router(Protocol):
    """Define the interface ``Flowsheet.route`` requires of a router."""

    def route(self, fs: "Flowsheet") -> None:
        """Route every stream and store the route on the stream.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames.
        """


def __getattr__(name: str) -> object:
    """Return the deprecated ``Router`` protocol, with a warning.

    Parameters
    ----------
    name : str
        Attribute looked up on the module.

    Returns
    -------
    object
        The ``Router`` protocol.

    Raises
    ------
    AttributeError
        If ``name`` is not ``"Router"``.

    Warns
    -----
    DeprecationWarning
        Always.
    """
    if name != "Router":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(_ROUTER.message(), DeprecationWarning, stacklevel=2)
    return _Router


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
    lanes: "tuple[Sequence[float], Sequence[float]] | None" = None,
) -> list[tuple[float, float]]:
    """Return the route drawn when no path is found.

    Of the two L-shaped corner orders, pick the one with fewer segments
    hitting an obstacle, then fewer recorded-line crossings, then
    across-first. Given ``lanes``, where that L hits an obstacle, draw
    instead the route that hits none and keeps :data:`EDGE_TOL` off
    every obstacle but the ends' own, with the fewest crossings, then
    bends, then length: an L, or a Z along a lane, from either end's
    escape node or, where its stub runs into an obstacle, from a lane
    short of it or halfway to it.

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
    lanes : tuple[Sequence[float], Sequence[float]] or None, optional
        x coordinates of the vertical lanes and y coordinates of the
        horizontal lanes a route may run along; ``None`` draws the L.

    Returns
    -------
    list[tuple[float, float]]
        Route waypoints from ``start`` to ``goal``.
    """
    def through(s: tuple[float, float], g: tuple[float, float],
                *corners: tuple[float, float]) -> list[tuple[float, float]]:
        """Return the route between two escape nodes that turns at ``corners``.

        Parameters
        ----------
        s, g : tuple[float, float]
            Source and destination escape nodes.
        *corners : tuple[float, float]
            Turning points between them.

        Returns
        -------
        list[tuple[float, float]]
            Route waypoints, consecutive repeats dropped.
        """
        pts = [start]
        for point in (s, *corners, g, goal):
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

    def ends(anchor: tuple[float, float],
             proj: tuple[float, float]) -> list[tuple[float, float]]:
        """Return the escape nodes a stub may end at.

        Parameters
        ----------
        anchor : tuple[float, float]
            Port anchor.
        proj : tuple[float, float]
            Escape node.

        Returns
        -------
        list[tuple[float, float]]
            ``proj``, and where the stub runs into an obstacle, each lane
            short of it and the point halfway to it.
        """
        axis = 0 if anchor[1] == proj[1] else 1
        sign = 1.0 if proj[axis] > anchor[axis] else -1.0
        across = anchor[1 - axis]
        faces = [sign * ((o.x_min, o.x_max) if axis == 0 else (o.y_min, o.y_max))[sign < 0]
                 - sign * anchor[axis]
                 for o in obstacles
                 if ((o.y_min <= across <= o.y_max) if axis == 0
                     else (o.x_min <= across <= o.x_max))]
        reach = min((f for f in faces if 0.0 < f <= sign * (proj[axis] - anchor[axis])),
                    default=None)
        if reach is None:
            return [proj]
        steps = [sign * (c - anchor[axis]) for c in (xs, ys)[axis]] + [reach / 2.0]
        return [proj] + [(anchor[0] + sign * d, anchor[1]) if axis == 0
                         else (anchor[0], anchor[1] + sign * d)
                         for d in steps if 0.0 < d < reach]

    across = through(start_proj, goal_proj, (goal_proj[0], start_proj[1]))
    down = through(start_proj, goal_proj, (start_proj[0], goal_proj[1]))
    drawn = down if score(down) < score(across) else across
    if lanes is None or score(drawn)[0] == 0:
        return drawn
    from pandid.routing.metrics import path_length
    from pandid.routing.visibility import EDGE_TOL, Rect

    xs, ys = lanes
    routes = []
    for (sx, sy) in ends(start, start_proj):
        for (gx, gy) in ends(goal, goal_proj):
            s, g = (sx, sy), (gx, gy)
            routes += [through(s, g, (gx, sy)), through(s, g, (sx, gy))]
            routes += [through(s, g, (x, sy), (x, gy)) for x in xs]
            routes += [through(s, g, (sx, y), (gx, y)) for y in ys]
    # Keep an edge tolerance off every obstacle but the ends' own.
    kept_off = [*obstacles, *(
        Rect(o.x_min - EDGE_TOL, o.x_max + EDGE_TOL, o.y_min - EDGE_TOL, o.y_max + EDGE_TOL)
        for o in obstacles
        if not any(o.x_min <= x <= o.x_max and o.y_min <= y <= o.y_max for x, y in (start, goal)))]
    clear = [r for r in routes if not any(o.intersects_segment(a[0], a[1], b[0], b[1])
                                          for a, b in zip(r, r[1:]) for o in kept_off)]
    return min(clear, key=lambda r: (score(r)[1], len(r), path_length(r))) if clear else drawn


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
    recover_exits : bool, optional
        Use the furthest reachable node on each stub, else an L route;
        ``True`` when omitted.

    Attributes
    ----------
    recover_exits : bool
        Escape-node recovery option.

    Warns
    -----
    DeprecationWarning
        If ``recover_exits`` is passed.
    """

    def __init__(self, *, recover_exits: bool | None = None) -> None:  # numpydoc ignore=GL08
        if recover_exits is not None:
            warnings.warn(_RECOVER_EXITS.message(), DeprecationWarning, stacklevel=2)
        self.recover_exits = True if recover_exits is None else recover_exits

    def route(self, fs: "Flowsheet") -> None:
        """Route and separate the sheet's automatic streams.

        Where the sheet asks for a re-check, each stream whose separated
        route crosses more of the lines routed before it than its search
        priced is routed again against those lines as separated, each run
        charged its unpriced crossings, and the sheet separated again.
        Outside layout, and unless the sheet asks for none, laterals that
        cross, share a run or wind are then laid on ordered lanes
        (:func:`pandid.routing.lanes.relane`). Outside layout, a line's
        search is charged for each run inside the frame of a package it
        has no end in.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames and nozzle faces.

        Raises
        ------
        ValueError
            If a frame is non-finite or a face is unreachable.
        RuntimeError
            If a path search exceeds its expansion budget.

        Warns
        -----
        UserWarning
            If an end has no frame or anchor; the stream is skipped.
        """
        from pandid.portgeom import COMPASS, resolve_port
        from pandid.package import frame as package_frame
        from pandid.render.svg import tap_lines, tap_route
        from pandid.render.symbols import ARROWHEAD
        from pandid.routing.visibility import VisibilityGraph, hugging_edges, share_escape_room
        from pandid.routing.astar import (CROSSING_PENALTY, FENCE_PENALTY, TOUCH_PENALTY,
                                          CrossingIndex, find_path)
        from pandid.routing.separation import preview_separated_waypoints

        _refuse_non_finite_geometry(fs)
        graph = VisibilityGraph(fs)
        # Price arrowheads and lanes beside units where route() asks,
        # but not on the routes layout sets pipe furniture on.
        priced = fs._priced and not fs._laying_out
        hugging = (hugging_edges(graph.edges, graph.xs, graph.ys, graph.body_obstacles)
                   if priced else {})
        # The first arrowhead length of each line out of each nozzle,
        # but a balloon's, which moves with the routes.
        heads = CrossingIndex()
        for s in fs.streams if priced else ():
            for port in (s.source, s.dest):
                if port.owner.frame is not None and port.owner.kind != "instrument":
                    (px, py), _, face = resolve_port(port.owner, port.owner.frame, port.name)
                    dx, dy = COMPASS[face]
                    heads.record([(px, py), (px + ARROWHEAD * dx, py + ARROWHEAD * dy)])
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float]
        edge_penalties = defaultdict(float)
        for run in hugging:
            edge_penalties[run] += TOUCH_PENALTY
        taps = [(u.host, tap_route(u, tap, centre)) for u, tap, centre in tap_lines(fs)]
        # Each package's units and the lane edges inside its frame.
        fences = [(set(p.units), [(a, b) for a, ends in graph.edges.items() for b in ends
                                  if box[0] < (a[0] + b[0]) / 2 < box[2]
                                  and box[1] < (a[1] + b[1]) / 2 < box[3]])
                  for p in ([] if fs._laying_out else fs.packages)
                  if (box := package_frame(p)) is not None]
        routed: list["Stream"] = []
        # Ends of each found route's stand-offs.
        escapes: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}

        # Each searched stream's crossing index and graph path.
        searched: dict[int, tuple["CrossingIndex", list[tuple[float, float]]]] = {}

        def crossable(stream: "Stream", lines: "dict[int, list[tuple[float, float]]] | None") -> "CrossingIndex":
            """Return the drawn lines a route for a stream would cross.

            The index holds every tap line but those on the stream
            itself, and every stream routed before it.

            Parameters
            ----------
            stream : Stream
                Stream to route.
            lines : dict or None
                Waypoints of the routed streams by ``id(stream)``, or
                ``None`` for a preview of them separated.

            Returns
            -------
            CrossingIndex
                Lines already on the sheet.
            """
            index = CrossingIndex()
            for host, points in taps:
                if host is not stream:
                    _record_route(index, points, True)
            if lines is None:
                lines = preview_separated_waypoints(routed, fs.units)
            for s in routed:
                if s is stream:
                    break
                assert s.route is not None
                _record_route(index, lines.get(id(s), s.route.waypoints), s.route.manual)
            return index

        def route_one(stream: "Stream", lines: "dict[int, list[tuple[float, float]]] | None") -> bool:
            """Route one automatic stream.

            Parameters
            ----------
            stream : Stream
                Stream to route.
            lines : dict or None
                What :func:`crossable` draws the routed streams from.

            Returns
            -------
            bool
                Whether the stream was routed.

            Warns
            -----
            UserWarning
                If an end has no frame or anchor; the stream is skipped.
            """
            src_u = stream.source.owner
            dst_u = stream.dest.owner
            if src_u.frame is None or dst_u.frame is None:
                unplaced = src_u if src_u.frame is None else dst_u
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: {unplaced.name!r} "
                    f"has no frame, so there is no geometry to route between. "
                    f"Call layout() before route().",
                    stacklevel=3,
                )
                return False

            s_key, d_key = (src_u.name, stream.source.name), (dst_u.name, stream.dest.name)
            start, goal = graph.port_anchors.get(s_key), graph.port_anchors.get(d_key)
            if start is None or goal is None:
                missing = (f"{src_u.name}.{stream.source.name}" if start is None
                           else f"{dst_u.name}.{stream.dest.name}")
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: the visibility "
                    f"graph carries no anchor for port {missing}.",
                    stacklevel=3,
                )
                return False

            start_dir, goal_dir = graph.port_dirs[s_key], graph.port_dirs[d_key]
            start_proj, goal_proj = graph.port_projs[s_key], graph.port_projs[d_key]

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
            crossing_index = crossable(stream, lines)
            # A run beside only the stream's own ends goes uncharged.
            own = [run for run, units in hugging.items()
                   if units <= {id(src_u), id(dst_u)}]
            for run in own:
                edge_penalties[run] -= TOUCH_PENALTY
            walls = [edge for held, edges in fences
                     if src_u not in held and dst_u not in held for edge in edges]
            for edge in walls:
                edge_penalties[edge] += FENCE_PENALTY
            path = []
            if clear_stubs:
                path = find_path(
                    graph, start_proj, goal_proj, start_dir, goal_dir,
                    edge_penalties, is_recycle, crossing_index, heads if priced else None,
                )
            for run in own:
                edge_penalties[run] += TOUCH_PENALTY
            for edge in walls:
                edge_penalties[edge] -= FENCE_PENALTY
            path_found = bool(path)

            if path:
                escapes[id(stream)] = (start_proj, goal_proj)
                path = [start] + path + [goal]
                searched[id(stream)] = (crossing_index, path)
                # Penalise used segments for later streams.
                for u_node, v_node in zip(path, path[1:]):
                    edge_penalties[(u_node, v_node)] += 2000.0
                    edge_penalties[(v_node, u_node)] += 2000.0
            else:
                searched[id(stream)] = (crossing_index, [])
                path = _fallback_path(
                    start, start_proj, goal_proj, goal, graph.obstacles, crossing_index,
                    (graph.xs, graph.ys) if fs._clear_fallback else None,
                )

            # Remove collinear points but keep both escape nodes.
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

            stream.route = Route(waypoints=simplified, used_fallback=not path_found)
            return True

        for stream in fs.streams:
            if (stream.route and stream.route.manual) or route_one(stream, None):
                routed.append(stream)

        from pandid.routing.lanes import relane
        from pandid.routing.separation import separate_streams
        found = {id(s): s.route.waypoints for s in routed if id(s) in searched and s.route}
        separate_streams(fs)
        drawn = {id(s): s.route.waypoints for s in routed if s.route}
        # Crossings each separated run draws beyond those its search priced.
        unpriced = []
        if not fs._laying_out:
            for s in routed:
                if id(s) in found:
                    index, real = searched[id(s)][0], crossable(s, drawn)
                    runs = zip(drawn[id(s)], drawn[id(s)][1:], found[id(s)], found[id(s)][1:])
                    extra = [real.crossings_along(a, b) - index.crossings_along(c, d)
                             for a, b, c, d in runs]
                    if sum(extra) > 0:
                        unpriced.append((s, extra))
        fs._undercharged = bool(unpriced)
        if unpriced and fs._recheck:
            for s in routed:
                if id(s) in found:
                    assert s.route is not None
                    s.route.waypoints = found[id(s)]
            for s, extra in unpriced:
                nodes = searched[id(s)][1]
                after = {a: b for a, b in zip(nodes, nodes[1:]) if a != b}
                # Charge each run's unpriced crossings on its first edge, and
                # lift the charge on the runs the stream used.
                charges = {(c, after[c]): CROSSING_PENALTY * n
                           for c, n in zip(found[id(s)], extra) if n > 0 and c in after}
                for a, b in after.items():
                    for edge in ((a, b), (b, a)):
                        edge_penalties[edge] += charges.get((a, b), 0.0) - 2000.0
                route_one(s, drawn)
                for (a, b), cost in charges.items():
                    edge_penalties[(a, b)] -= cost
                    edge_penalties[(b, a)] -= cost
            separate_streams(fs)
        # Keep the routes layout sets pipe furniture on.
        if fs._lanes and not fs._laying_out and relane(fs, escapes, graph):
            fs._relaned = True
