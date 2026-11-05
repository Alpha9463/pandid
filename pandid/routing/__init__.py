"""Route automatic streams orthogonally between placed nozzles."""

import math
import warnings
from collections import defaultdict
from typing import Protocol, TYPE_CHECKING

from pandid.deprecation import Deprecation
from pandid.geometry import Route

if TYPE_CHECKING:
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

        Outside layout, and unless the sheet asks for none, laterals that
        cross, share a run or wind are then laid on ordered lanes
        (:func:`pandid.routing.lanes.relane`).

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
        from pandid.render.svg import tap_lines, tap_route
        from pandid.render.symbols import ARROWHEAD
        from pandid.routing.visibility import VisibilityGraph, hugging_edges, share_escape_room
        from pandid.routing.astar import TOUCH_PENALTY, CrossingIndex, find_path
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
        routed: list["Stream"] = []
        # Ends of each found route's stand-offs.
        escapes: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}

        def crossable(stream: "Stream") -> "CrossingIndex":
            """Return the drawn lines a route for a stream would cross.

            The index holds every tap line but those on the stream
            itself, and a preview of every routed stream's separated
            waypoints.

            Parameters
            ----------
            stream : Stream
                Stream about to be routed.

            Returns
            -------
            CrossingIndex
                Lines already on the sheet.
            """
            index = CrossingIndex()
            for host, points in taps:
                if host is not stream:
                    _record_route(index, points, True)
            preview = preview_separated_waypoints(routed, fs.units)
            for s in routed:
                assert s.route is not None
                wp = preview.get(id(s), s.route.waypoints)
                _record_route(index, wp, s.route.manual)
            return index

        for stream in fs.streams:
            if stream.route and stream.route.manual:
                routed.append(stream)
                continue

            src_u = stream.source.owner
            dst_u = stream.dest.owner
            if src_u.frame is None or dst_u.frame is None:
                unplaced = src_u if src_u.frame is None else dst_u
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: {unplaced.name!r} "
                    f"has no frame, so there is no geometry to route between. "
                    f"Call layout() before route().",
                    stacklevel=2,
                )
                continue

            s_key, d_key = (src_u.name, stream.source.name), (dst_u.name, stream.dest.name)
            start, goal = graph.port_anchors.get(s_key), graph.port_anchors.get(d_key)
            if start is None or goal is None:
                missing = (f"{src_u.name}.{stream.source.name}" if start is None
                           else f"{dst_u.name}.{stream.dest.name}")
                warnings.warn(
                    f"stream {stream.name!r} is left unrouted: the visibility "
                    f"graph carries no anchor for port {missing}.",
                    stacklevel=2,
                )
                continue

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
            crossing_index = crossable(stream)
            # A run beside only the stream's own ends goes uncharged.
            own = [run for run, units in hugging.items()
                   if units <= {id(src_u), id(dst_u)}]
            for run in own:
                edge_penalties[run] -= TOUCH_PENALTY
            path = []
            if clear_stubs:
                path = find_path(
                    graph, start_proj, goal_proj, start_dir, goal_dir,
                    edge_penalties, is_recycle, crossing_index, heads if priced else None,
                )
            for run in own:
                edge_penalties[run] += TOUCH_PENALTY
            path_found = bool(path)

            if path:
                escapes[id(stream)] = (start_proj, goal_proj)
                path = [start] + path + [goal]
                # Penalise used segments for later streams.
                for u_node, v_node in zip(path, path[1:]):
                    edge_penalties[(u_node, v_node)] += 2000.0
                    edge_penalties[(v_node, u_node)] += 2000.0
            else:
                path = _fallback_path(
                    start, start_proj, goal_proj, goal, graph.obstacles, crossing_index
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
            routed.append(stream)

        from pandid.routing.lanes import relane
        from pandid.routing.separation import separate_streams
        separate_streams(fs)
        # Keep the routes layout sets pipe furniture on.
        if fs._lanes and not fs._laying_out and relane(fs, escapes, graph):
            fs._relaned = True



def route_tap(inst, tap: tuple[float, float], faces: list[str],
              centre: tuple[float, float]) -> list[tuple[float, float]]:
    """Return a tap line's path round unit bodies and tags.

    The line leaves the tap square along the first of ``faces`` that
    has a path, and reaches the balloon centre on the visibility graph
    at the fewest bends. It may cross its own host's tag. It is priced
    as a stream routed after every drawn line: by the lines it crosses
    and the runs it shares.

    Parameters
    ----------
    inst : Instrument
        Placed attached balloon.
    tap : tuple[float, float]
        Tap point.
    faces : list[str]
        Compass directions the line may leave the tap in, in order.
    centre : tuple[float, float]
        Balloon centre.

    Returns
    -------
    list[tuple[float, float]]
        Points from ``tap`` to ``centre``, or ``[]`` if no path is clear.
    """
    from bisect import bisect_left, bisect_right

    from pandid.layout.attach import stream_path
    from pandid.portgeom import COMPASS, unit_box
    from pandid.routing.astar import CrossingIndex, find_path
    from pandid.routing.visibility import MIN_ESCAPE, Rect, VisibilityGraph, _tag_halo
    from pandid.units import Unit

    host, fs = inst.host, inst.flowsheet
    if fs is None or inst.frame is None:
        return []
    x0, y0, x1, y1 = unit_box(inst, inst.frame)
    omit = [Rect(x0, x1, y0, y1)]
    owner = host if isinstance(host, Unit) else inst
    if owner.frame is not None and (halo := _tag_halo(owner, owner.frame)) is not None:
        omit.append(halo)
    stubs = {face: (tap[0] + MIN_ESCAPE * COMPASS[face][0], tap[1] + MIN_ESCAPE * COMPASS[face][1])
             for face in faces}
    graph = VisibilityGraph(fs, lanes=(*stubs.values(), centre), omit=omit)
    index = CrossingIndex()
    used: dict[tuple[tuple[float, float], tuple[float, float]], float] = defaultdict(float)
    for line in (stream_path(s) for s in fs.streams if s.route is not None):
        _record_route(index, line, True)
        # Charge each graph edge on the line's square runs.
        for (ax, ay), (bx, by) in zip(line, line[1:]):
            if (ax == bx) == (ay == by):
                continue
            lanes, fixed = (graph.xs, ay) if ay == by else (graph.ys, ax)
            lo, hi = sorted((ax, bx) if ay == by else (ay, by))
            run = [(c, fixed) if ay == by else (fixed, c)
                   for c in lanes[bisect_left(lanes, lo):bisect_right(lanes, hi)]]
            for p, q in zip(run, run[1:]):
                if q in graph.edges.get(p, ()):
                    used[(p, q)] += 2000.0
                    used[(q, p)] += 2000.0
    for face, stub in stubs.items():
        start = graph.reachable_projection(tap, stub, face, owner)
        path = find_path(graph, start, centre, face, None, used, False, index) if start else []
        if path:
            break
    else:
        return []
    points = [tap, *path]
    return [points[0], *(b for a, b, c in zip(points, points[1:], points[2:])
                         if not (a[0] == b[0] == c[0] or a[1] == b[1] == c[1])), points[-1]]
