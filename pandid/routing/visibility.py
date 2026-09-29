"""Visibility-graph construction for orthogonal flowsheet routing."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


@dataclass
class Rect:
    """Represent an axis-aligned routing obstacle.

    Parameters
    ----------
    x_min, x_max, y_min, y_max : float
        Rectangle boundaries in drawing coordinates.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        """Return whether a point lies strictly inside the rectangle.

        Parameters
        ----------
        x, y : float
            Point coordinates.

        Returns
        -------
        bool
            Whether the point is inside both pairs of boundaries.
        """
        return self.x_min < x < self.x_max and self.y_min < y < self.y_max

    def intersects_segment(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """Return whether an orthogonal segment crosses the rectangle interior.

        Parameters
        ----------
        x1, y1, x2, y2 : float
            Segment endpoint coordinates.

        Returns
        -------
        bool
            Whether the segment intersects or lies on a rectangle boundary.
        """
        if x1 == x2:
            return (
                self.x_min <= x1 <= self.x_max
                and max(y1, y2) > self.y_min
                and min(y1, y2) < self.y_max
            )
        if y1 == y2:
            return (
                self.y_min <= y1 <= self.y_max
                and max(x1, x2) > self.x_min
                and min(x1, x2) < self.x_max
            )
        return False


def clear_gaps(lane: List[float], spans: List[Tuple[float, float]]) -> List[bool]:
    """Return the clear gaps between consecutive lane coordinates.

    Parameters
    ----------
    lane : list[float]
        Ordered coordinates on one routing lane.
    spans : list[tuple[float, float]]
        Obstacle spans that touch the lane.

    Returns
    -------
    list[bool]
        One value per gap; ``False`` marks a gap blocked by an obstacle span.
    """
    clear = [True] * max(len(lane) - 1, 0)
    for lo, hi in spans:
        first = max(bisect_right(lane, lo) - 1, 0)
        last = min(bisect_left(lane, hi), len(clear))
        for k in range(first, last):
            clear[k] = False
    return clear


TRAVEL: Dict[str, Tuple[int, float]] = {
    "E": (0, 1.0),
    "W": (0, -1.0),
    "S": (1, 1.0),
    "N": (1, -1.0),
}


def escape_distance(kind: str, label_pos: str | None, face: str) -> float:
    """Return the maximum outward distance for a port escape node.

    Parameters
    ----------
    kind : str
        Owner unit kind.
    label_pos : str or None
        Resolved label side.
    face : str
        Outward port face.

    Returns
    -------
    float
        Escape distance in drawing pixels.
    """
    if kind in ("feed", "product"):
        return 25.0
    if (face, label_pos) in (("N", "top"), ("S", "bottom")):
        return 45.0
    if (face, label_pos) in (("W", "left"), ("E", "right")):
        return 50.0
    return 25.0


def share_escape_room(
    start: Tuple[float, float],
    start_dir: Optional[str],
    start_proj: Tuple[float, float],
    goal: Tuple[float, float],
    goal_dir: Optional[str],
    goal_proj: Tuple[float, float],
    obstacles: List[Rect],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Return shared escape points for nearby facing ports.

    Parameters
    ----------
    start, goal : tuple[float, float]
        Port-anchor coordinates.
    start_dir, goal_dir : str or None
        Outward port directions.
    start_proj, goal_proj : tuple[float, float]
        Nominal escape-node coordinates.
    obstacles : list[Rect]
        Obstacles that can block a shared escape lane.

    Returns
    -------
    tuple[tuple[float, float], tuple[float, float]]
        Adjusted escape coordinates, or the original projections when a shared
        lane is unsuitable.
    """
    if start_dir is None or goal_dir is None:
        return start_proj, goal_proj
    axis, sign = TRAVEL[start_dir]
    goal_axis, goal_sign = TRAVEL[goal_dir]
    if goal_axis != axis or goal_sign == sign:
        return start_proj, goal_proj

    room = sign * (goal[axis] - start[axis])
    claimed = sign * (start_proj[axis] - start[axis]) + goal_sign * (goal_proj[axis] - goal[axis])
    if not 0.0 <= room < claimed:
        return start_proj, goal_proj

    mid = start[axis] + sign * room / 2.0
    if axis == 0:
        shared = ((mid, start_proj[1]), (mid, goal_proj[1]))
    else:
        shared = ((start_proj[0], mid), (goal_proj[0], mid))
    (sx, sy), (gx, gy) = shared
    if any(o.intersects_segment(sx, sy, gx, gy) for o in obstacles):
        return start_proj, goal_proj
    return shared


class VisibilityGraph:
    """Represent clear orthogonal lanes around resolved flowsheet geometry.

    Attributes
    ----------
    obstacles : list[Rect]
        Unit and label rectangles excluded from graph edges.
    body_obstacles : list[tuple[Unit, Rect]]
        Unit bodies used to validate outward port stubs.
    nodes : set[tuple[float, float]]
        Clear lane intersections.
    edges : dict[tuple[float, float], list[tuple[float, float]]]
        Connections between adjacent clear nodes.
    """

    def __init__(self, fs: "Flowsheet", margin: float = 15.0):
        """Build routing lanes from resolved flowsheet geometry.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet with placed frames and resolved port faces.
        margin : float, default=15.0
            Clearance around unit and label obstacles.
        """
        from pandid.layout.attach import is_attached
        from pandid.portgeom import port_anchor

        self.obstacles: List[Rect] = []
        self.body_obstacles: List[Tuple["Unit", Rect]] = []
        x_set: Set[float] = set()
        y_set: Set[float] = set()

        self.port_anchors: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.port_dirs: Dict[Tuple[str, str], str] = {}
        self.port_projs: Dict[Tuple[str, str], Tuple[float, float]] = {}

        for u in fs.units:
            f = u.frame
            if f is None:
                continue
            u_width, u_height = f.w, f.h
            mirrored = f.mirrored

            tap = getattr(u, "tap", None)
            inline = (
                is_attached(u)
                and tap is not None
                and f.x <= tap[0] <= f.x + u_width
                and f.y <= tap[1] <= f.y + u_height
            )

            if not inline:
                if u.kind == "feed" and not mirrored:
                    body = Rect(f.x + 50.0 - u_width, f.x + 50.0, f.y, f.y + u_height)
                else:
                    body = Rect(f.x, f.x + u_width, f.y, f.y + u_height)
                self.obstacles.append(body)
                self.body_obstacles.append((u, body))

            lpos = f.label_pos or "top"
            if u.kind not in ("feed", "product") and lpos != "center":
                label_w = min(150.0, max(40.0, len(u.name) * 7.5))
                if lpos == "top":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w / 2, cx + label_w / 2, f.y - 20, f.y))
                    y_set.add(f.y - 20.0 - margin)
                    y_set.add(f.y - 10.0)
                elif lpos == "bottom":
                    cx = f.x + u_width / 2
                    self.obstacles.append(
                        Rect(
                            cx - label_w / 2, cx + label_w / 2, f.y + u_height, f.y + u_height + 25
                        )
                    )
                    y_set.add(f.y + u_height + 25.0 + margin)
                    y_set.add(f.y + u_height + 10.0)
                elif lpos == "left":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x - label_w - 15, f.x, cy - 10, cy + 10))
                    x_set.add(f.x - label_w - 15.0 - margin)
                    x_set.add(f.x - 5.0)
                elif lpos == "right":
                    cy = f.y + u_height / 2
                    self.obstacles.append(
                        Rect(f.x + u_width, f.x + u_width + label_w + 15, cy - 10, cy + 10)
                    )
                    x_set.add(f.x + u_width + label_w + 15.0 + margin)
                    x_set.add(f.x + u_width + 5.0)

            x_set.add(f.x - margin)
            x_set.add(f.x + u_width + margin)
            y_set.add(f.y - margin)
            y_set.add(f.y + u_height + margin)

            for name in u.ports:
                ax, ay, o_dir = port_anchor(u, f, name)
                self.port_anchors[(u.name, name)] = (ax, ay)
                self.port_dirs[(u.name, name)] = o_dir

                px_proj, py_proj = ax, ay
                proj_dist = escape_distance(u.kind, lpos, o_dir)
                if o_dir == "N":
                    py_proj -= proj_dist
                elif o_dir == "S":
                    py_proj += proj_dist
                elif o_dir == "W":
                    px_proj -= proj_dist
                elif o_dir == "E":
                    px_proj += proj_dist
                self.port_projs[(u.name, name)] = (px_proj, py_proj)
                x_set.add(px_proj)
                y_set.add(py_proj)

        for stream in fs.streams:
            src, dst = stream.source, stream.dest
            if src.owner is None or dst.owner is None:
                continue
            s_key, d_key = (src.owner.name, src.name), (dst.owner.name, dst.name)
            if s_key not in self.port_projs or d_key not in self.port_projs:
                continue
            s_esc, d_esc = share_escape_room(
                self.port_anchors[s_key],
                self.port_dirs[s_key],
                self.port_projs[s_key],
                self.port_anchors[d_key],
                self.port_dirs[d_key],
                self.port_projs[d_key],
                self.obstacles,
            )
            for x, y in (s_esc, d_esc):
                x_set.add(x)
                y_set.add(y)

        self.recycle_y: List[float] = []

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
        xs, ys = self.xs, self.ys

        blocked_on_row: List[Set[float]] = [set() for _ in ys]
        blocked_on_col: List[Set[float]] = [set() for _ in xs]
        for o in self.obstacles:
            i0, i1 = bisect_right(xs, o.x_min), bisect_left(xs, o.x_max)
            j0, j1 = bisect_right(ys, o.y_min), bisect_left(ys, o.y_max)
            inside_x, inside_y = xs[i0:i1], ys[j0:j1]
            for j in range(j0, j1):
                blocked_on_row[j].update(inside_x)
            for i in range(i0, i1):
                blocked_on_col[i].update(inside_y)

        valid_x_on_row = [[x for x in xs if x not in blocked] for blocked in blocked_on_row]
        self.nodes: Set[Tuple[float, float]] = {
            (x, y) for y, valid_x in zip(ys, valid_x_on_row) for x in valid_x
        }

        self.edges: Dict[Tuple[float, float], List[Tuple[float, float]]] = {
            n: [] for n in self.nodes
        }

        row_spans: List[List[Tuple[float, float]]] = [[] for _ in ys]
        col_spans: List[List[Tuple[float, float]]] = [[] for _ in xs]
        for o in self.obstacles:
            for j in range(bisect_left(ys, o.y_min), bisect_right(ys, o.y_max)):
                row_spans[j].append((o.x_min, o.x_max))
            for i in range(bisect_left(xs, o.x_min), bisect_right(xs, o.x_max)):
                col_spans[i].append((o.y_min, o.y_max))

        for j, (y, valid_x) in enumerate(zip(ys, valid_x_on_row)):
            for k, clear in enumerate(clear_gaps(valid_x, row_spans[j])):
                if clear:
                    x1, x2 = valid_x[k], valid_x[k + 1]
                    self.edges[(x1, y)].append((x2, y))
                    self.edges[(x2, y)].append((x1, y))

        for i, x in enumerate(xs):
            valid_y = [y for y in ys if y not in blocked_on_col[i]]
            for k, clear in enumerate(clear_gaps(valid_y, col_spans[i])):
                if clear:
                    y1, y2 = valid_y[k], valid_y[k + 1]
                    self.edges[(x, y1)].append((x, y2))
                    self.edges[(x, y2)].append((x, y1))

    def reachable_projection(
        self,
        anchor: Tuple[float, float],
        projection: Tuple[float, float],
        direction: str | None,
        owner: "Unit",
    ) -> Tuple[float, float] | None:
        """Return the furthest clear lane on a port's outward stub.

        Parameters
        ----------
        anchor : tuple[float, float]
            Port-anchor coordinate on the unit body.
        projection : tuple[float, float]
            Maximum escape-node coordinate.
        direction : str or None
            Outward port direction.
        owner : Unit
            Unit that owns the port.

        Returns
        -------
        tuple[float, float] or None
            Reachable graph node, or ``None`` when the stub is blocked.
        """
        travel = TRAVEL.get(direction) if direction is not None else None
        if travel is None:
            return projection
        axis, sign = travel
        distance = sign * (projection[axis] - anchor[axis])
        if distance <= 0:
            return projection
        lanes = self.xs if axis == 0 else self.ys
        ordered = reversed(lanes) if sign > 0 else iter(lanes)
        for coordinate in ordered:
            reach = sign * (coordinate - anchor[axis])
            if reach <= 0:
                break
            if reach > distance:
                continue
            candidate = (coordinate, anchor[1]) if axis == 0 else (anchor[0], coordinate)
            if not self.edges.get(candidate):
                continue
            if any(
                other is not owner and body.intersects_segment(*anchor, *candidate)
                for other, body in self.body_obstacles
            ):
                continue
            return candidate
        return None
