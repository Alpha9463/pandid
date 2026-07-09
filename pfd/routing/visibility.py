from dataclasses import dataclass
from typing import Set, Tuple, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

@dataclass
class Rect:
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        # strict containment
        return self.x_min < x < self.x_max and self.y_min < y < self.y_max

    def intersects_segment(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        # Check if the segment strictly passes through the interior of the rect.
        # A segment along the edge is NOT allowed.
        if x1 == x2:
            return self.x_min <= x1 <= self.x_max and max(y1, y2) > self.y_min and min(y1, y2) < self.y_max
        if y1 == y2:
            return self.y_min <= y1 <= self.y_max and max(x1, x2) > self.x_min and min(x1, x2) < self.x_max
        return False

class VisibilityGraph:
    def __init__(self, fs: "Flowsheet", margin: float = 15.0):
        self.obstacles: List[Rect] = []
        x_set: Set[float] = set()
        y_set: Set[float] = set()
        
        from pfd.render.symbols import default_registry
        
        self.port_anchors: Dict[Tuple[str, str], Tuple[float, float]] = {}
        
        for u in fs.units:
            if not u.placement:
                continue
            p = u.placement
            sym = default_registry.get(u.kind, getattr(u, 'variant', 'default'))
            
            u_width = u.width if u.width is not None else sym.width
            u_height = u.height if u.height is not None else sym.height
            if u.width is not None:
                u_width = u.width
            elif u.kind in ("feed", "product"):
                u_width = max(80.0, len(u.name) * 8.0 + 30.0)
                
            sx = u_width / sym.width
            sy = u_height / sym.height
            
            mirrored = getattr(p, 'mirrored', False)
            
            # The exact boundary of the unit is an obstacle
            if u.kind == "feed":
                if mirrored:
                    self.obstacles.append(Rect(p.x, p.x + u_width, p.y, p.y + u_height))
                else:
                    self.obstacles.append(Rect(p.x + 50.0 - u_width, p.x + 50.0, p.y, p.y + u_height))
            else:
                self.obstacles.append(Rect(p.x, p.x + u_width, p.y, p.y + u_height))
            
            lpos = getattr(u, 'label_pos', None) or sym.label_pos or "top"
            if u.kind not in ("feed", "product") and lpos != "center":
                label_w = min(150.0, max(40.0, len(u.name) * 7.5))
                if lpos == "top":
                    cx = p.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, p.y - 20, p.y))
                elif lpos == "bottom":
                    cx = p.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, p.y + u_height, p.y + u_height + 25))
                elif lpos == "left":
                    cy = p.y + u_height / 2
                    self.obstacles.append(Rect(p.x - label_w - 15, p.x, cy - 10, cy + 10))
                elif lpos == "right":
                    cy = p.y + u_height / 2
                    self.obstacles.append(Rect(p.x + u_width, p.x + u_width + label_w + 15, cy - 10, cy + 10))
            
            # Routing lanes around the unit
            x_set.add(p.x - margin)
            x_set.add(p.x + u_width + margin)
            y_set.add(p.y - margin)
            y_set.add(p.y + u_height + margin)
            
            if u.kind not in ("feed", "product") and lpos != "center":
                if lpos == "top":
                    y_set.add(p.y - 20.0 - margin)
                    y_set.add(p.y - 10.0)
                elif lpos == "bottom":
                    y_set.add(p.y + u_height + 25.0 + margin)
                    y_set.add(p.y + u_height + 10.0)
                elif lpos == "left":
                    x_set.add(p.x - label_w - 15.0 - margin)
                    x_set.add(p.x - 5.0)
                elif lpos == "right":
                    x_set.add(p.x + u_width + label_w + 15.0 + margin)
                    x_set.add(p.x + u_width + 5.0)
            
            # Port locations themselves form grid lines
            for name, port in u.ports.items():
                px, py = sym.ports.get(name, (sym.width / 2, sym.height / 2))
                
                if mirrored:
                    px = sym.width - px
                    
                if u.kind not in ("feed", "product"):
                    px *= sx
                    py *= sy
                
                from pfd.routing import get_outward_dir
                outward_dir = get_outward_dir(px, py, u_width, u_height, u.kind, name, mirrored)
                
                if u.kind == "feed":
                    ax = p.x if mirrored else p.x + 50.0
                    ay = p.y + py
                elif u.kind == "product":
                    ax = p.x + u_width if mirrored else p.x
                    ay = p.y + py
                else:
                    ax, ay = p.x + px, p.y + py
                
                # Project the port to the bounding box if it's strictly inside
                if u.kind not in ("feed", "product"):
                    if outward_dir == "N":
                        ay = p.y
                    elif outward_dir == "S":
                        ay = p.y + u_height
                    elif outward_dir == "W":
                        ax = p.x
                    elif outward_dir == "E":
                        ax = p.x + u_width
                    
                self.port_anchors[(u.name, name)] = (ax, ay)
                
                # Also add the projected routing point
                px_proj, py_proj = ax, ay
                
                proj_dist = 25.0
                if u.kind not in ("feed", "product"):
                    if outward_dir == "N" and lpos == "top": proj_dist = 45.0
                    elif outward_dir == "S" and lpos == "bottom": proj_dist = 45.0
                    elif outward_dir == "W" and lpos == "left": proj_dist = 50.0
                    elif outward_dir == "E" and lpos == "right": proj_dist = 50.0
                if outward_dir == "N":
                    py_proj -= proj_dist
                elif outward_dir == "S":
                    py_proj += proj_dist
                elif outward_dir == "W":
                    px_proj -= proj_dist
                elif outward_dir == "E":
                    px_proj += proj_dist
                x_set.add(px_proj)
                y_set.add(py_proj)
                
        self.recycle_y: List[float] = []
        # Global recycle lanes above, below, left, and right of all equipment
        if self.obstacles:
            min_y = min(o.y_min for o in self.obstacles)
            max_y = max(o.y_max for o in self.obstacles)
            self.recycle_y = [min_y - 40.0, max_y + 40.0]
            for y in self.recycle_y:
                y_set.add(y)
                
            min_x = min(o.x_min for o in self.obstacles)
            max_x = max(o.x_max for o in self.obstacles)
            for x in [min_x - 40.0, max_x + 40.0]:
                x_set.add(x)
            
        self.xs = sorted(list(x_set))
        self.ys = sorted(list(y_set))
        
        # Valid nodes are those that are not strictly inside any obstacle
        self.nodes: Set[Tuple[float, float]] = set()
        for x in self.xs:
            for y in self.ys:
                if not any(o.contains(x, y) for o in self.obstacles):
                    self.nodes.add((x, y))
                    
        # Build adjacency list
        self.edges: Dict[Tuple[float, float], List[Tuple[float, float]]] = {n: [] for n in self.nodes}
        
        # Horizontal edges
        for y in self.ys:
            valid_x = [x for x in self.xs if (x, y) in self.nodes]
            for i in range(len(valid_x) - 1):
                x1, x2 = valid_x[i], valid_x[i+1]
                if not any(o.intersects_segment(x1, y, x2, y) for o in self.obstacles):
                    self.edges[(x1, y)].append((x2, y))
                    self.edges[(x2, y)].append((x1, y))
                    
        # Vertical edges
        for x in self.xs:
            valid_y = [y for y in self.ys if (x, y) in self.nodes]
            for i in range(len(valid_y) - 1):
                y1, y2 = valid_y[i], valid_y[i+1]
                if not any(o.intersects_segment(x, y1, x, y2) for o in self.obstacles):
                    self.edges[(x, y1)].append((x, y2))
                    self.edges[(x, y2)].append((x, y1))
