from typing import Protocol, TYPE_CHECKING
from pfd.geometry import Route

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class Router(Protocol):
    def route(self, fs: "Flowsheet") -> None:
        """Route all streams in the flowsheet."""


def get_outward_dir(px: float, py: float, w: float, h: float, unit_kind: str = "", port_name: str = "") -> str:
    """Determine the outward normal direction for a port anchor relative to its unit bounding box."""
    if unit_kind == "product" and port_name == "inlet":
        return "W"
    if unit_kind == "feed" and port_name == "outlet":
        return "E"
        
    dist_N = py
    dist_S = h - py
    dist_W = px
    dist_E = w - px
    m = min(dist_N, dist_S, dist_W, dist_E)
    if m == dist_N: return "N"
    if m == dist_S: return "S"
    if m == dist_W: return "W"
    return "E"


class DefaultRouter:
    def route(self, fs: "Flowsheet") -> None:
        from pfd.routing.visibility import VisibilityGraph
        from pfd.routing.astar import find_path
        from pfd.render.symbols import default_registry
        
        graph = VisibilityGraph(fs, margin=15.0)
        edge_penalties = {}
        
        for stream in fs.streams:
            if stream.route and stream.route.manual:
                continue
                
            src_u = stream.source.owner
            dst_u = stream.dest.owner
            
            if not src_u.placement or not dst_u.placement:
                continue
                
            start = graph.port_anchors.get((src_u.name, stream.source.name))
            goal = graph.port_anchors.get((dst_u.name, stream.dest.name))
            
            if not start or not goal:
                continue
                
            src_sym = default_registry.get(src_u.kind)
            dst_sym = default_registry.get(dst_u.kind)
            
            spx, spy = src_sym.ports.get(stream.source.name, (src_sym.width / 2, src_sym.height / 2))
            dpx, dpy = dst_sym.ports.get(stream.dest.name, (dst_sym.width / 2, dst_sym.height / 2))
            
            start_dir = get_outward_dir(spx, spy, src_sym.width, src_sym.height, src_u.kind, stream.source.name)
            goal_dir = get_outward_dir(dpx, dpy, dst_sym.width, dst_sym.height, dst_u.kind, stream.dest.name)
            
            path = find_path(graph, start, goal, start_dir, goal_dir, edge_penalties)
            
            if path:
                # Add heavy penalties to all segments used so subsequent streams avoid them
                for i in range(len(path) - 1):
                    u_node = path[i]
                    v_node = path[i+1]
                    edge_penalties[(u_node, v_node)] = edge_penalties.get((u_node, v_node), 0.0) + 2000.0
                    edge_penalties[(v_node, u_node)] = edge_penalties.get((v_node, u_node), 0.0) + 2000.0
            else:
                # Fallback to straight line
                path = [start, goal]
                
            # Simplify path (remove collinear intermediate points)
            simplified = [path[0]]
            for i in range(1, len(path)-1):
                prev = simplified[-1]
                curr = path[i]
                nxt = path[i+1]
                if (prev[0] == curr[0] == nxt[0]) or (prev[1] == curr[1] == nxt[1]):
                    continue
                simplified.append(curr)
            if len(path) > 1:
                simplified.append(path[-1])
                
            stream.route = Route(waypoints=simplified)
