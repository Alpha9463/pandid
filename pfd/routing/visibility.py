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
        from pfd.layout.attach import is_attached
        from pfd.portgeom import port_anchor

        self.obstacles: List[Rect] = []
        x_set: Set[float] = set()
        y_set: Set[float] = set()

        # Port anchors and their outward directions — the single geometry
        # authority the router reads from.
        self.port_anchors: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.port_dirs: Dict[Tuple[str, str], str] = {}

        for u in fs.units:
            f = u.frame
            if f is None:
                continue
            u_width, u_height = f.w, f.h
            mirrored = f.mirrored

            # An in-line element straddles its own tap — that is the whole point
            # of ``offset=0`` — so treating it as an obstacle would push its host
            # line into a detour around it, and the balloon, being placed from
            # that line, would then chase the detour. It stands aside instead.
            tap = getattr(u, "tap", None)
            inline = (is_attached(u) and tap is not None
                      and f.x <= tap[0] <= f.x + u_width and f.y <= tap[1] <= f.y + u_height)

            # The exact boundary of the unit is an obstacle. Feed keeps its
            # port-at-(x+50) convention: the drawn box extends left from there.
            if not inline:
                if u.kind == "feed" and not mirrored:
                    self.obstacles.append(
                        Rect(f.x + 50.0 - u_width, f.x + 50.0, f.y, f.y + u_height))
                else:
                    self.obstacles.append(Rect(f.x, f.x + u_width, f.y, f.y + u_height))

            lpos = f.label_pos or "top"
            if u.kind not in ("feed", "product") and lpos != "center":
                label_w = min(150.0, max(40.0, len(u.name) * 7.5))
                if lpos == "top":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, f.y - 20, f.y))
                elif lpos == "bottom":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, f.y + u_height, f.y + u_height + 25))
                elif lpos == "left":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x - label_w - 15, f.x, cy - 10, cy + 10))
                elif lpos == "right":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x + u_width, f.x + u_width + label_w + 15, cy - 10, cy + 10))

            # Routing lanes around the unit
            x_set.add(f.x - margin)
            x_set.add(f.x + u_width + margin)
            y_set.add(f.y - margin)
            y_set.add(f.y + u_height + margin)

            if u.kind not in ("feed", "product") and lpos != "center":
                if lpos == "top":
                    y_set.add(f.y - 20.0 - margin)
                    y_set.add(f.y - 10.0)
                elif lpos == "bottom":
                    y_set.add(f.y + u_height + 25.0 + margin)
                    y_set.add(f.y + u_height + 10.0)
                elif lpos == "left":
                    x_set.add(f.x - label_w - 15.0 - margin)
                    x_set.add(f.x - 5.0)
                elif lpos == "right":
                    x_set.add(f.x + u_width + label_w + 15.0 + margin)
                    x_set.add(f.x + u_width + 5.0)

            # Port anchors (bbox-edge) and their projected escape nodes.
            for name in u.ports:
                ax, ay, o_dir = port_anchor(u, f, name)
                self.port_anchors[(u.name, name)] = (ax, ay)
                self.port_dirs[(u.name, name)] = o_dir

                px_proj, py_proj = ax, ay
                proj_dist = 25.0
                if u.kind not in ("feed", "product"):
                    if o_dir == "N" and lpos == "top":
                        proj_dist = 45.0
                    elif o_dir == "S" and lpos == "bottom":
                        proj_dist = 45.0
                    elif o_dir == "W" and lpos == "left":
                        proj_dist = 50.0
                    elif o_dir == "E" and lpos == "right":
                        proj_dist = 50.0
                if o_dir == "N":
                    py_proj -= proj_dist
                elif o_dir == "S":
                    py_proj += proj_dist
                elif o_dir == "W":
                    px_proj -= proj_dist
                elif o_dir == "E":
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
