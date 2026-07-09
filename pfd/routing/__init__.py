from typing import Protocol, TYPE_CHECKING
from pfd.geometry import Route

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class Router(Protocol):
    def route(self, fs: "Flowsheet") -> None:
        """Route all streams in the flowsheet."""


def get_outward_dir(px: float, py: float, w: float, h: float, unit_kind: str = "", port_name: str = "", mirrored: bool = False) -> str:
    """Determine the outward normal direction for a port anchor relative to its unit bounding box."""
    if unit_kind == "product" and port_name == "inlet":
        return "E" if mirrored else "W"
    if unit_kind == "feed" and port_name == "outlet":
        return "W" if mirrored else "E"
        
    dist_N = py
    dist_S = h - py
    dist_W = px
    dist_E = w - px
    m = min(dist_N, dist_S, dist_W, dist_E)
    if m == dist_N:
        return "N"
    if m == dist_S:
        return "S"
    if m == dist_W:
        return "W"
    return "E"


class DefaultRouter:
    def route(self, fs: "Flowsheet") -> None:
        from pfd.routing.visibility import VisibilityGraph
        from pfd.routing.astar import find_path
        from pfd.render.symbols import default_registry
        
        graph = VisibilityGraph(fs, margin=15.0)
        edge_penalties: dict[tuple[tuple[float, float], tuple[float, float]], float] = {}
        
        for stream in fs.streams:
            if stream.route and stream.route.manual:
                continue
                
            src_u = stream.source.owner
            dst_u = stream.dest.owner
            assert src_u is not None and dst_u is not None
            
            if not src_u.placement or not dst_u.placement:
                continue
                
            start = graph.port_anchors.get((src_u.name, stream.source.name))
            goal = graph.port_anchors.get((dst_u.name, stream.dest.name))
            
            if not start or not goal:
                continue
                
            src_sym = default_registry.get(src_u.kind, getattr(src_u, 'variant', 'default'))
            dst_sym = default_registry.get(dst_u.kind, getattr(dst_u, 'variant', 'default'))
            
            s_width = src_u.width if src_u.width is not None else src_sym.width
            s_height = src_u.height if src_u.height is not None else src_sym.height
            if src_u.kind in ("feed", "product"):
                s_width = max(80.0, len(src_u.name) * 8.0 + 30.0)
                
            d_width = dst_u.width if dst_u.width is not None else dst_sym.width
            d_height = dst_u.height if dst_u.height is not None else dst_sym.height
            if dst_u.kind in ("feed", "product"):
                d_width = max(80.0, len(dst_u.name) * 8.0 + 30.0)
            
            spx, spy = src_sym.ports.get(stream.source.name, (src_sym.width / 2, src_sym.height / 2))
            dpx, dpy = dst_sym.ports.get(stream.dest.name, (dst_sym.width / 2, dst_sym.height / 2))
            
            s_mirrored = getattr(src_u.placement, 'mirrored', False)
            if s_mirrored:
                spx = src_sym.width - spx
            
            d_mirrored = getattr(dst_u.placement, 'mirrored', False)
            if d_mirrored:
                dpx = dst_sym.width - dpx
            
            if src_u.kind not in ("feed", "product"):
                spx *= s_width / src_sym.width
                spy *= s_height / src_sym.height
            if dst_u.kind not in ("feed", "product"):
                dpx *= d_width / dst_sym.width
                dpy *= d_height / dst_sym.height
            
            start_dir = get_outward_dir(spx, spy, s_width, s_height, src_u.kind, stream.source.name, s_mirrored)
            goal_dir = get_outward_dir(dpx, dpy, d_width, d_height, dst_u.kind, stream.dest.name, d_mirrored)
            
            s_lpos = getattr(src_u, 'label_pos', None) or src_sym.label_pos or "top"
            d_lpos = getattr(dst_u, 'label_pos', None) or dst_sym.label_pos or "top"
            
            # Increase projection distance if routing through the label's position
            # Feed/Product do not have unit labels outside their bounding box
            if src_u.kind in ("feed", "product") or s_lpos == "center":
                s_lpos = None
            if dst_u.kind in ("feed", "product") or d_lpos == "center":
                d_lpos = None

            start_proj = list(start)
            if start_dir == "N": start_proj[1] -= (45.0 if s_lpos == "top" else 25.0)
            elif start_dir == "S": start_proj[1] += (45.0 if s_lpos == "bottom" else 25.0)
            elif start_dir == "W": start_proj[0] -= (50.0 if s_lpos == "left" else 25.0)
            elif start_dir == "E": start_proj[0] += (50.0 if s_lpos == "right" else 25.0)
            start_proj = tuple(start_proj)
            
            goal_proj = list(goal)
            if goal_dir == "N": goal_proj[1] -= (45.0 if d_lpos == "top" else 25.0)
            elif goal_dir == "S": goal_proj[1] += (45.0 if d_lpos == "bottom" else 25.0)
            elif goal_dir == "W": goal_proj[0] -= (50.0 if d_lpos == "left" else 25.0)
            elif goal_dir == "E": goal_proj[0] += (50.0 if d_lpos == "right" else 25.0)
            goal_proj = tuple(goal_proj)
            
            is_recycle = getattr(stream, "is_recycle", False)
            path = find_path(graph, start_proj, goal_proj, start_dir, goal_dir, edge_penalties, is_recycle)
            
            if path:
                path = [start] + path + [goal]
                # Add heavy penalties to all segments used so subsequent streams avoid them
                for i in range(len(path) - 1):
                    u_node = path[i]
                    v_node = path[i+1]
                    edge_penalties[(u_node, v_node)] = edge_penalties.get((u_node, v_node), 0.0) + 2000.0
                    edge_penalties[(v_node, u_node)] = edge_penalties.get((v_node, u_node), 0.0) + 2000.0
            else:
                print(f"Fallback for {stream.name}: {start_proj} to {goal_proj}")
                # Fallback to an orthogonal L-shape ensuring we pass through projection points
                mid_point = (goal_proj[0], start_proj[1])
                path = [start, start_proj, mid_point, goal_proj, goal]
                
            # Simplify path (remove collinear intermediate points)
            simplified = [path[0]]
            for i in range(1, len(path)-1):
                prev = simplified[-1]
                curr = path[i]
                nxt = path[i+1]
                # Never simplify away start_proj or goal_proj to guarantee a minimum orthogonal segment
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
