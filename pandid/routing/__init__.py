import math
import warnings
from typing import Protocol, TYPE_CHECKING

from pandid.geometry import Route
from pandid.portgeom import outward_dir as get_outward_dir  # re-exported for callers

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

__all__ = ["Router", "DefaultRouter", "get_outward_dir"]


class Router(Protocol):
    def route(self, fs: "Flowsheet") -> None:
        """Route all streams in the flowsheet."""


def _clamp_projection(
    anchor: tuple[float, float],
    proj: tuple[float, float],
    d: str | None,
    target: tuple[float, float],
    nodes: set[tuple[float, float]],
) -> tuple[float, float]:
    """Pull an escape projection back onto a lane the stub would otherwise overshoot.

    The escape distance is a *maximum* stand-off, not a fixed one. When the far
    end of the run already sits on the outward ray (a nozzle 15px above the lane
    its stream has to join, say, projected 25px out), insisting on the full
    projection makes the path overshoot and come back, which is two bends and
    part of the stub drawn twice. Turning onto that lane on the way out is one.

    Going further out stays available: the continuation is the same direction,
    so it costs no bend, which makes this purely a relaxation of where the path
    is *allowed* to turn.
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
    # A lane the visibility grid does not carry is no lane at all.
    return cand if cand in nodes else proj


def _fallback_path(
    start: tuple[float, float],
    start_proj: tuple[float, float],
    goal_proj: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list,
) -> list[tuple[float, float]]:
    """The L to draw when the search comes back with nothing.

    A* returns nothing when the two escape nodes are not connected on the
    lane grid -- most often because one of them has been sealed inside a
    neighbouring unit, which leaves it out of the graph entirely and so
    with no edges to search along. Something still has to be drawn, and an
    L through the two projections is it.

    Which L, though, is a choice, and it was not being made: the corner
    always went across first and then down, wherever that landed. Both
    orders are candidates here and the one crossing fewer obstacles wins,
    with the across-first order keeping the tie so a sheet nothing is in
    the way of draws exactly what it drew before.

    Where every candidate is blocked there is no better line to draw --
    the search has already established that the grid has none -- so the
    least bad one goes down and ``validate()`` names it, under
    ``route-crosses-unit``. Silently preferring a clear L when one exists
    is the half that belongs here; saying so when none does is the half
    that belongs there.

    Any corner repeating the point before it is dropped. Two projections
    already in one column put the corner on top of ``start_proj``, and the
    caller's simplifier keeps both verbatim (it never drops a projection
    point), leaving a zero-length segment that the separation pass then
    reads as a horizontal run on a track the stream does not occupy.
    """
    def through(corner: tuple[float, float]) -> list[tuple[float, float]]:
        pts = [start]
        for point in (start_proj, corner, goal_proj, goal):
            if point != pts[-1]:
                pts.append(point)
        return pts

    def crossings(pts: list[tuple[float, float]]) -> int:
        return sum(
            any(o.intersects_segment(a[0], a[1], b[0], b[1]) for o in obstacles)
            for a, b in zip(pts, pts[1:])
        )

    across = through((goal_proj[0], start_proj[1]))
    down = through((start_proj[0], goal_proj[1]))
    return down if crossings(down) < crossings(across) else across


def _refuse_non_finite_geometry(fs: "Flowsheet") -> None:
    """Refuse a sheet carrying a NaN or an infinity in its geometry.

    Such a coordinate does not stay where it was put. It reaches the
    visibility graph as a lane and as an obstacle edge, and from there the
    search, where it is fatal: every comparison against NaN is false, so A*'s
    ``visited`` prune settles nothing, every state re-expands and the render
    never returns. Caught here, before the graph is built, because this is the
    last place that can name the unit carrying it.
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
    def route(self, fs: "Flowsheet") -> None:
        from pandid.routing.visibility import VisibilityGraph, share_escape_room
        from pandid.routing.astar import find_path

        _refuse_non_finite_geometry(fs)
        graph = VisibilityGraph(fs, margin=15.0)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}

        for stream in fs.streams:
            if stream.route and stream.route.manual:
                continue

            src_u = stream.source.owner
            dst_u = stream.dest.owner
            # Not an ``assert``: ``python -O`` strips those, and the line below
            # would then fail with an AttributeError naming none of this.
            if src_u is None or dst_u is None:
                orphan = stream.source if src_u is None else stream.dest
                raise ValueError(
                    f"stream {stream.name!r} cannot be routed: port "
                    f"{orphan.name!r} belongs to no unit."
                )

            # The three ways a stream drops out below all leave ``stream.route``
            # None, which draws no line and sends every later render back
            # through routing again. Say so rather than skip in silence.
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

            # The graph stood every port off to its escape node already, at the
            # label-aware distance, and carries the lanes those land on.
            start_proj = graph.port_projs[(src_u.name, stream.source.name)]
            goal_proj = graph.port_projs[(dst_u.name, stream.dest.name)]

            # The stand-off is a ceiling, and it applies at both ends. Prefer to
            # give way onto a lane the grid already carries; only when neither
            # end can is the room between them split down the middle.
            start_proj = _clamp_projection(start, start_proj, start_dir, goal_proj, graph.nodes)
            goal_proj = _clamp_projection(goal, goal_proj, goal_dir, start_proj, graph.nodes)
            start_proj, goal_proj = share_escape_room(
                start, start_dir, start_proj, goal, goal_dir, goal_proj, graph.obstacles
            )

            is_recycle = getattr(stream, "is_recycle", False)
            path = find_path(graph, start_proj, goal_proj, start_dir, goal_dir, edge_penalties, is_recycle)

            if path:
                path = [start] + path + [goal]
                # Penalize used segments so later streams avoid overlapping them.
                for i in range(len(path) - 1):
                    u_node, v_node = path[i], path[i+1]
                    edge_penalties[(u_node, v_node)] = edge_penalties.get((u_node, v_node), 0.0) + 2000.0
                    edge_penalties[(v_node, u_node)] = edge_penalties.get((v_node, u_node), 0.0) + 2000.0
            else:
                path = _fallback_path(
                    start, start_proj, goal_proj, goal, graph.obstacles
                )

            # Simplify (remove collinear intermediate points), but never drop the
            # projection points that guarantee a clean port exit/entry.
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

            stream.route = Route(waypoints=simplified)

        # Apply parallel segment separation pass
        from pandid.routing.separation import separate_streams
        separate_streams(fs)
