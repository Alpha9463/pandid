"""Route automatic streams orthogonally between placed nozzles."""

import math
import warnings
from typing import Protocol, TYPE_CHECKING

from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.routing.astar import CrossingIndex
    from pandid.streams import Stream

__all__ = ["Router", "DefaultRouter"]


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

    Of the two corner orders, pick the one crossing fewer obstacles,
    then fewer recorded lines, then the across-first one.

    Parameters
    ----------
    start, goal : tuple[float, float]
        Port anchors.
    start_proj, goal_proj : tuple[float, float]
        Escape nodes of the two ports.
    crossing_index : CrossingIndex or None, optional
        Routes already drawn in this pass.
    """
    def through(corner: tuple[float, float]) -> list[tuple[float, float]]:
        """Return the route that turns at ``corner``."""
        pts = [start]
        for point in (start_proj, corner, goal_proj, goal):
            if point != pts[-1]:
                pts.append(point)
        return pts

    def score(pts: list[tuple[float, float]]) -> tuple[int, int]:
        """Count obstacle hits, then recorded-line crossings."""
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
    """Raise ValueError if a placed frame holds a NaN or an infinity."""
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
        Replace a blocked escape node with a reachable one on the stub.
    """

    def __init__(self, *, recover_exits: bool = True) -> None:
        """Set the escape-node recovery option."""
        self.recover_exits = recover_exits

    def route(self, fs: "Flowsheet") -> None:
        """Route and separate every automatic stream on the sheet.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames and nozzle faces.

        Raises
        ------
        ValueError
            If a frame is non-finite or a stream's port has no owner.
        """
        from pandid.routing.visibility import VisibilityGraph, share_escape_room
        from pandid.routing.astar import CrossingIndex, find_path
        from pandid.routing.separation import preview_separated_waypoints

        _refuse_non_finite_geometry(fs)
        graph = VisibilityGraph(fs)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
        crossing_index = CrossingIndex()
        routed: list["Stream"] = []

        def settle(stream: "Stream") -> None:
            """Add a routed stream and rebuild the crossing index.

            The index holds a preview of every routed stream's separated
            waypoints.
            """
            nonlocal crossing_index
            routed.append(stream)
            preview = preview_separated_waypoints(routed)
            crossing_index = CrossingIndex()
            for s in routed:
                assert s.route is not None  # Every routed stream has a route.
                wp = preview.get(id(s), s.route.waypoints)
                _record_route(crossing_index, wp, s.route.manual)

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
                path = find_path(
                    graph, start_proj, goal_proj, start_dir, goal_dir,
                    edge_penalties, is_recycle, crossing_index,
                )
            path_found = bool(path)

            if path:
                path = [start] + path + [goal]
                # Penalise used segments for later streams.
                for i in range(len(path) - 1):
                    u_node, v_node = path[i], path[i+1]
                    edge_penalties[(u_node, v_node)] = edge_penalties.get((u_node, v_node), 0.0) + 2000.0
                    edge_penalties[(v_node, u_node)] = edge_penalties.get((v_node, u_node), 0.0) + 2000.0
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

            settle(stream)

        # Separate parallel segments that share a lane.
        from pandid.routing.separation import separate_streams
        separate_streams(fs)
