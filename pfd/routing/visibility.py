import itertools
from dataclasses import dataclass
from typing import Set, Tuple, List, Dict

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
        # A segment along the edge is allowed.
        if x1 == x2:
            return self.x_min < x1 < self.x_max and max(y1, y2) > self.y_min and min(y1, y2) < self.y_max
        if y1 == y2:
            return self.y_min < y1 < self.y_max and max(x1, x2) > self.x_min and min(x1, x2) < self.x_max
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
            sym = default_registry.get(u.kind)
            
            # The exact boundary of the unit is an obstacle
            self.obstacles.append(Rect(p.x, p.x + p.width, p.y, p.y + p.height))
            
            # Routing lanes around the unit
            x_set.add(p.x - margin)
            x_set.add(p.x + p.width + margin)
            y_set.add(p.y - margin)
            y_set.add(p.y + p.height + margin)
            
            # Port locations themselves form grid lines
            for name, port in u.ports.items():
                px, py = sym.ports.get(name, (p.width / 2, p.height / 2))
                ax, ay = p.x + px, p.y + py
                self.port_anchors[(u.name, name)] = (ax, ay)
                x_set.add(ax)
                y_set.add(ay)
                
        # Global recycle lanes above and below all equipment
        if self.obstacles:
            min_y = min(o.y_min for o in self.obstacles)
            max_y = max(o.y_max for o in self.obstacles)
            y_set.add(min_y - 40.0)
            y_set.add(max_y + 40.0)
            
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
