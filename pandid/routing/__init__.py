"""Route automatic streams orthogonally between placed nozzles."""

import math
import warnings
from typing import Protocol, TYPE_CHECKING

from pandid.geometry import Route
from pandid.portgeom import outward_dir as get_outward_dir  # Re-exported for callers.

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.routing.astar import CrossingIndex
    from pandid.streams import Stream

__all__ = ["Router", "DefaultRouter", "get_outward_dir"]


class Router(Protocol):
    """Define the interface ``Flowsheet.route`` requires of a router."""

    def route(self, fs: "Flowsheet") -> None:
        """Route all streams in the flowsheet.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames.

        Returns
        -------
        None
            Routes are stored on the streams.
        """


def _clamp_projection(
    anchor: tuple[float, float],
    proj: tuple[float, float],
    d: str | None,
    target: tuple[float, float],
    nodes: set[tuple[float, float]],
) -> tuple[float, float]:
    """Shorten an escape projection onto the lane its peer occupies.

    The stand-off is a maximum. Turning onto the peer's lane on the way out
    avoids an overshoot and return.

    Parameters
    ----------
    anchor : tuple[float, float]
        Port anchor on the unit body.
    proj : tuple[float, float]
        Nominal escape node.
    d : str or None
        Outward port direction.
    target : tuple[float, float]
        Escape node at the other end of the stream.
    nodes : set[tuple[float, float]]
        Visibility-graph nodes.

    Returns
    -------
    tuple[float, float]
        The shortened escape node, or ``proj`` when the peer's lane is not
        strictly inside the stub or is not a graph node.
    """
    ax, ay = anchor
    px, py = proj
    tx, ty = target
    if d in ("N", "S"):
        lo, hi = (py, ay) if d == "N" else (ay, py)
        cand = (ax, ty) if lo < ty < hi else proj
    elif d in ("E", "W"):
        lo, hi = (px, ax) if d == "W" else (ax, px)
        cand = (tx, ay) if lo < tx < hi else proj
    else:
        return proj
    # Keep the nominal projection when the graph has no node on that lane.
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

    Both corner orders are candidates. The one crossing fewer obstacles
    wins, then the one crossing fewer recorded lines, then the across-first
    order. A route through equipment is a defect; a line crossing is a drawn
    convention. ``validate()`` reports a blocked result as
    ``route-crosses-unit``.

    Parameters
    ----------
    start, goal : tuple[float, float]
        Port anchors.
    start_proj, goal_proj : tuple[float, float]
        Escape nodes of the two ports.
    obstacles : list
        Rectangles the route should avoid.
    crossing_index : CrossingIndex or None, optional
        Routes already drawn in this pass.

    Returns
    -------
    list[tuple[float, float]]
        Waypoints from ``start`` to ``goal`` without repeated points.
    """
    def through(corner: tuple[float, float]) -> list[tuple[float, float]]:
        """Build the route that turns at one corner.

        Parameters
        ----------
        corner : tuple[float, float]
            Point where the route changes direction.

        Returns
        -------
        list[tuple[float, float]]
            Waypoints with consecutive duplicates removed.
        """
        pts = [start]
        for point in (start_proj, corner, goal_proj, goal):
            if point != pts[-1]:
                pts.append(point)
        return pts

    def score(pts: list[tuple[float, float]]) -> tuple[int, int]:
        """Count the obstacles and recorded lines a route crosses.

        Parameters
        ----------
        pts : list[tuple[float, float]]
            Candidate route waypoints.

        Returns
        -------
        tuple[int, int]
            Segments that hit an obstacle, then crossings of recorded lines.
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
    """Record one committed route in the crossing index.

    A manual route is recorded one orthogonal run at a time. Its diagonal
    legs are left out, so later searches do not price crossing them.

    Parameters
    ----------
    crossing_index : CrossingIndex
        Index of routes drawn so far in this pass.
    waypoints : list[tuple[float, float]]
        Route waypoints.
    manual : bool
        Whether the author supplied the waypoints with ``via()``.

    Returns
    -------
    None
        The index is updated in place.
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
    """Reject a sheet whose frames hold a NaN or an infinity.

    A non-finite coordinate stops the path search from terminating.

    Parameters
    ----------
    fs : Flowsheet
        Sheet about to be routed.

    Returns
    -------
    None
        Every placed frame is finite.

    Raises
    ------
    ValueError
        If a frame has a non-finite position or size.
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
        Try connected lanes before a blocked nominal nozzle projection.
        ``False`` searches from the nominal projection only.
    """

    def __init__(self, *, recover_exits: bool = True) -> None:
        """Set the outward-stub recovery policy.

        Parameters
        ----------
        recover_exits : bool, optional
            Enable clearance checks and shorter reachable escape nodes.
        """
        self.recover_exits = recover_exits

    def route(self, fs: "Flowsheet") -> None:
        """Compute and separate all automatic stream paths.

        Parameters
        ----------
        fs : Flowsheet
            Sheet with resolved unit frames and selected nozzle faces.

        Returns
        -------
        None
            Final route waypoints and fallback status are stored on streams.

        Raises
        ------
        ValueError
            If a frame is non-finite or a stream's port has no owner.
        """
        from pandid.routing.visibility import VisibilityGraph, share_escape_room
        from pandid.routing.astar import CrossingIndex, find_path
        from pandid.routing.separation import preview_separated_waypoints

        _refuse_non_finite_geometry(fs)
        graph = VisibilityGraph(fs, margin=15.0)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
        # Index the streams drawn earlier in this pass. Rebuild it on every
        # call because each pass routes against new geometry.
        crossing_index = CrossingIndex()
        routed: list["Stream"] = []

        def settle(stream: "Stream") -> None:
            """Add a routed stream to the crossing index.

            The index is rebuilt from a preview of the separated waypoints,
            so later searches price crossings against the drawn geometry.
            A stream routed later can still move an earlier track (#509).

            Parameters
            ----------
            stream : Stream
                Stream carrying its waypoints for this pass.

            Returns
            -------
            None
                ``crossing_index`` is replaced.
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
                # Record a manual route so later streams price crossing it.
                settle(stream)
                continue

            src_u = stream.source.owner
            dst_u = stream.dest.owner
            # Raise explicitly because ``python -O`` removes assertions.
            if src_u is None or dst_u is None:
                orphan = stream.source if src_u is None else stream.dest
                raise ValueError(
                    f"stream {stream.name!r} cannot be routed: port "
                    f"{orphan.name!r} belongs to no unit."
                )

            # Warn when a stream is left unrouted; its route stays ``None``.
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

            start_dir = graph.port_dirs.get((src_u.name, stream.source.name))
            goal_dir = graph.port_dirs.get((dst_u.name, stream.dest.name))

            # Read the escape nodes the graph placed at the stand-off distance.
            start_proj = graph.port_projs[(src_u.name, stream.source.name)]
            goal_proj = graph.port_projs[(dst_u.name, stream.dest.name)]

            # Shorten each stand-off onto the peer's lane, then share the room
            # between two facing ports.
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
                # Penalise used segments so later streams avoid overlapping them.
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

            # Record every drawn route, including a fallback, for later streams.
            settle(stream)

        # Separate parallel segments that share a lane.
        from pandid.routing.separation import separate_streams
        separate_streams(fs)
