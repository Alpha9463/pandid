"""Visibility-graph construction for orthogonal flowsheet routing."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import TYPE_CHECKING, Collection, Dict, List, Set, Tuple

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: Clearance a line keeps beside a tag's halo.
TAG_CLEAR = 3.0

#: Least distance a route runs straight out of a nozzle.
MIN_ESCAPE = 25.0


@dataclass
class Rect:
    """An axis-aligned routing obstacle.

    Attributes
    ----------
    x_min, x_max : float
        Left and right edges.
    y_min, y_max : float
        Top and bottom edges.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def intersects_segment(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """Return whether an orthogonal segment enters the rectangle.

        Parameters
        ----------
        x1, y1 : float
            First end of the segment.
        x2, y2 : float
            Second end of the segment.

        Returns
        -------
        bool
            Whether it enters or runs along a side; False if diagonal.
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
    """Return whether each gap between lane coordinates is clear.

    Parameters
    ----------
    lane : list[float]
        Sorted node coordinates along one lane.
    spans : list[tuple[float, float]]
        Obstacle spans ``(lo, hi)`` on that lane.

    Returns
    -------
    list[bool]
        One flag per gap between neighbouring coordinates.
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
    """Return a port's nominal escape distance from its anchor.

    Parameters
    ----------
    kind : str
        Kind of the port's unit.
    label_pos : str or None
        Side of the unit its tag is drawn on.
    face : str
        Compass face of the port.

    Returns
    -------
    float
        Escape distance.
    """
    if kind in ("feed", "product"):
        return MIN_ESCAPE
    if (face, label_pos) in (("N", "top"), ("S", "bottom")):
        return 45.0
    if (face, label_pos) in (("W", "left"), ("E", "right")):
        return 50.0
    return MIN_ESCAPE


def share_escape_room(
    start: Tuple[float, float],
    start_dir: str,
    start_proj: Tuple[float, float],
    goal: Tuple[float, float],
    goal_dir: str,
    goal_proj: Tuple[float, float],
    obstacles: List[Rect],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Move two close facing ports' escape nodes onto their midline.

    The nodes move only when the ports face each other, lack room for
    both stubs and have a clear midline.

    Parameters
    ----------
    start : tuple[float, float]
        Source port anchor.
    start_dir : str
        Outward direction of the source port.
    start_proj : tuple[float, float]
        Nominal source escape node.
    goal : tuple[float, float]
        Destination port anchor.
    goal_dir : str
        Outward direction of the destination port.
    goal_proj : tuple[float, float]
        Nominal destination escape node.
    obstacles : list[Rect]
        Obstacles the midline must clear.

    Returns
    -------
    tuple[tuple[float, float], tuple[float, float]]
        Source and destination escape nodes.
    """
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
    """Graph of clear orthogonal lanes around units and tags.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with unit frames and port faces.
    skip : Collection[Unit], optional
        Units to leave out.

    Attributes
    ----------
    obstacles : list[Rect]
        Unit bodies, except inline balloons, and tag halos.
    body_obstacles : list[tuple[Unit, Rect]]
        Unit bodies with their units.
    port_anchors : dict[tuple[str, str], tuple[float, float]]
        Port anchor by ``(unit name, port name)``.
    port_dirs : dict[tuple[str, str], str]
        Port outward direction by ``(unit name, port name)``.
    port_projs : dict[tuple[str, str], tuple[float, float]]
        Port escape node by ``(unit name, port name)``.
    recycle_y : list[float]
        Recycle lanes above and below the drawing.
    xs, ys : list[float]
        Sorted lane coordinates.
    nodes : set[tuple[float, float]]
        Lane intersections outside every obstacle's interior.
    edges : dict[tuple[float, float], list[tuple[float, float]]]
        Clear neighbours of each node.

    Raises
    ------
    ValueError
        If a port's face cannot be reached under its placement.
    """

    def __init__(self, fs: "Flowsheet", skip: "Collection[Unit]" = ()):  # numpydoc ignore=GL08
        from pandid.layout.attach import is_attached
        from pandid.portgeom import COMPASS, port_anchor, tag_width, unit_box

        margin = 15.0  # clearance around unit and label obstacles

        self.obstacles: List[Rect] = []
        self.body_obstacles: List[Tuple["Unit", Rect]] = []
        x_set: Set[float] = set()
        y_set: Set[float] = set()

        self.port_anchors: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.port_dirs: Dict[Tuple[str, str], str] = {}
        self.port_projs: Dict[Tuple[str, str], Tuple[float, float]] = {}

        for u in fs.units:
            f = u.frame
            if f is None or u in skip:
                continue
            u_width, u_height = f.w, f.h

            tap = getattr(u, "tap", None)
            inline = (
                is_attached(u)
                and tap is not None
                and f.x <= tap[0] <= f.x + u_width
                and f.y <= tap[1] <= f.y + u_height
            )

            if not inline:
                x0, y0, x1, y1 = unit_box(u, f)
                body = Rect(x0, x1, y0, y1)
                self.obstacles.append(body)
                self.body_obstacles.append((u, body))

            lpos = f.label_pos or "top"
            # Block the halo drawn behind the tag.
            if u.kind not in ("feed", "product") and lpos != "center" and u.tag:
                label_w = tag_width(u.tag) + 2 * TAG_CLEAR
                # Room for a valve's fail letters past its tag.
                fail = 25.0 if getattr(u, "fail", "") else 0.0
                if lpos == "top":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w / 2, cx + label_w / 2, f.y - 20, f.y))
                    y_set.add(f.y - 20.0 - margin)
                    y_set.add(f.y - 10.0)
                elif lpos == "bottom":
                    cx = f.x + u_width / 2
                    self.obstacles.append(
                        Rect(
                            cx - label_w / 2, cx + label_w / 2,
                            f.y + u_height, f.y + u_height + 25 + fail,
                        )
                    )
                    y_set.add(f.y + u_height + 25.0 + fail + margin)
                    y_set.add(f.y + u_height + 10.0)
                elif lpos == "left":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x - label_w - 15, f.x, cy - 10, cy + 10))
                    x_set.add(f.x - label_w - 15.0 - margin)
                    x_set.add(f.x - 5.0)
                elif lpos == "right":
                    cy = f.y + u_height / 2
                    self.obstacles.append(
                        Rect(f.x + u_width, f.x + u_width + label_w + 15 + fail, cy - 10, cy + 10)
                    )
                    x_set.add(f.x + u_width + label_w + 15.0 + fail + margin)
                    x_set.add(f.x + u_width + 5.0)

            x_set.add(f.x - margin)
            x_set.add(f.x + u_width + margin)
            y_set.add(f.y - margin)
            y_set.add(f.y + u_height + margin)

            for name in u.ports:
                ax, ay, o_dir = port_anchor(u, f, name)
                self.port_anchors[(u.name, name)] = (ax, ay)
                self.port_dirs[(u.name, name)] = o_dir

                proj_dist = escape_distance(u.kind, lpos, o_dir)
                dx, dy = COMPASS[o_dir]
                px_proj, py_proj = ax + proj_dist * dx, ay + proj_dist * dy
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
        direction: str,
        owner: "Unit",
    ) -> Tuple[float, float] | None:
        """Return the furthest stub node clear of other units' bodies.

        Parameters
        ----------
        anchor : tuple[float, float]
            Port anchor.
        projection : tuple[float, float]
            Furthest escape node.
        direction : str
            Outward port direction.
        owner : Unit
            Unit the port belongs to.

        Returns
        -------
        tuple[float, float] or None
            Furthest such node, ``projection`` if not outward, or None.
        """
        axis, sign = TRAVEL[direction]
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
