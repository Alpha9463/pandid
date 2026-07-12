from typing import Protocol, TYPE_CHECKING

from pfd.geometry import Route
from pfd.portgeom import outward_dir as get_outward_dir  # re-exported for callers

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet
    from pfd.units import Unit

__all__ = ["Router", "DefaultRouter", "get_outward_dir"]


class Router(Protocol):
    def route(self, fs: "Flowsheet") -> None:
        """Route all streams in the flowsheet."""


def _label_pos(u: "Unit") -> str:
    return (u.frame.label_pos if u.frame else None) or "top"


def _project(anchor: tuple[float, float], d: str | None, lpos: str | None) -> tuple[float, float]:
    """Push a port anchor outward to its escape node (label-aware distance)."""
    x, y = anchor
    if d == "N":
        y -= 45.0 if lpos == "top" else 25.0
    elif d == "S":
        y += 45.0 if lpos == "bottom" else 25.0
    elif d == "W":
        x -= 50.0 if lpos == "left" else 25.0
    elif d == "E":
        x += 50.0 if lpos == "right" else 25.0
    return (x, y)


class DefaultRouter:
    def route(self, fs: "Flowsheet") -> None:
        from pfd.routing.visibility import VisibilityGraph
        from pfd.routing.astar import find_path

        graph = VisibilityGraph(fs, margin=15.0)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}

        for stream in fs.streams:
            if stream.route and stream.route.manual:
                continue

            src_u = stream.source.owner
            dst_u = stream.dest.owner
            assert src_u is not None and dst_u is not None

            if src_u.frame is None or dst_u.frame is None:
                continue

            start = graph.port_anchors.get((src_u.name, stream.source.name))
            goal = graph.port_anchors.get((dst_u.name, stream.dest.name))
            if not start or not goal:
                continue

            start_dir = graph.port_dirs.get((src_u.name, stream.source.name))
            goal_dir = graph.port_dirs.get((dst_u.name, stream.dest.name))

            # Label-aware projection out of each port (feed/product have no
            # external unit label, so they never widen the escape distance).
            s_lpos = _label_pos(src_u)
            d_lpos = _label_pos(dst_u)
            if src_u.kind in ("feed", "product") or s_lpos == "center":
                s_lpos = None
            if dst_u.kind in ("feed", "product") or d_lpos == "center":
                d_lpos = None

            start_proj = _project(start, start_dir, s_lpos)
            goal_proj = _project(goal, goal_dir, d_lpos)

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
                # Fallback to an orthogonal L-shape through the projection points.
                mid_point = (goal_proj[0], start_proj[1])
                path = [start, start_proj, mid_point, goal_proj, goal]

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
        from pfd.routing.separation import separate_streams
        separate_streams(fs)
