from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Optional, Set, Tuple, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

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


def clear_gaps(lane: List[float], spans: List[Tuple[float, float]]) -> List[bool]:
    """Which gaps between consecutive nodes on a lane no obstacle reaches into.

    ``lane`` is the ordered coordinates of the lane's valid nodes, and ``spans``
    the ``(min, max)`` of the obstacles already known to touch the lane, taken
    along the axis it runs. Gap *k*, between ``lane[k]`` and ``lane[k + 1]``, is
    closed when some span has ``lane[k + 1] > min and lane[k] < max``: the half
    of :meth:`Rect.intersects_segment` the caller has not already settled by
    selecting the spans.

    A span closes a *contiguous* run of gaps -- the ones bisection puts either
    side of it -- so marking that run costs one pass over the lane's own
    obstacles, where testing each gap costs a pass over every obstacle on the
    sheet for every gap on every lane.
    """
    clear = [True] * max(len(lane) - 1, 0)
    for lo, hi in spans:
        # ``lane[k + 1] > lo`` from the first coordinate past ``lo``, and
        # ``lane[k] < hi`` up to the last one before ``hi``.
        first = max(bisect_right(lane, lo) - 1, 0)
        last = min(bisect_left(lane, hi), len(clear))
        for k in range(first, last):
            clear[k] = False
    return clear


# Outward direction -> the axis it travels along, and its sign along that axis.
TRAVEL: Dict[str, Tuple[int, float]] = {
    "E": (0, 1.0),
    "W": (0, -1.0),
    "S": (1, 1.0),
    "N": (1, -1.0),
}


def share_escape_room(
    start: Tuple[float, float],
    start_dir: Optional[str],
    start_proj: Tuple[float, float],
    goal: Tuple[float, float],
    goal_dir: Optional[str],
    goal_proj: Tuple[float, float],
    obstacles: List[Rect],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Split the gap between two facing nozzles too close to both stand off fully.

    Each end claims its own escape distance before the run is allowed to turn,
    and the two claims are made independently. Nozzles pointing at each other
    across less room than the claims add up to therefore overshoot each other:
    the source's escape node lands beyond the destination's nozzle and the
    destination's lands back behind the source's, so the leg between them is
    drawn backwards over both stubs. A 13px span came out as 87px of path, most
    of it on top of itself and through the source symbol.

    There is no room for two stand-offs, so the pair takes one between them and
    both escape nodes move to the middle of the gap. The run across is then the
    straight line, and neither stub is drawn twice. A control valve station
    packs an isolation valve, a reducer, the valve, another reducer and a second
    isolation valve into spans narrower than one stand-off, so this is what lets
    a sheet be drawn at the density a real one is drawn at.

    Both ends have to turn on the *same* lane for neither to overshoot, which is
    a real constraint and not only a relaxation: it is the one column (or row)
    the run may cross on. Nozzles that also sit on different lanes have to
    travel along it, so if anything is in the way the pair keeps its full
    stand-offs and the search picks its own way round instead. Ports facing each
    other on one lane meet on it and travel nowhere, so nothing can be in the
    way and that case always takes the relaxation.

    Pure, and called from two places: the router, to place the escape nodes, and
    the graph, to carry the lane they land on.
    """
    if start_dir is None or goal_dir is None:
        return start_proj, goal_proj
    axis, sign = TRAVEL[start_dir]
    goal_axis, goal_sign = TRAVEL[goal_dir]
    if goal_axis != axis or goal_sign == sign:
        return start_proj, goal_proj  # not pointed at each other along one axis

    room = sign * (goal[axis] - start[axis])
    claimed = sign * (start_proj[axis] - start[axis]) + goal_sign * (goal_proj[axis] - goal[axis])
    if not 0.0 <= room < claimed:
        return start_proj, goal_proj  # back to back, or room enough for both

    mid = start[axis] + sign * room / 2.0
    if axis == 0:
        shared = ((mid, start_proj[1]), (mid, goal_proj[1]))
    else:
        shared = ((start_proj[0], mid), (goal_proj[0], mid))
    (sx, sy), (gx, gy) = shared
    if any(o.intersects_segment(sx, sy, gx, gy) for o in obstacles):
        return start_proj, goal_proj  # the shared lane is not one the run can use
    return shared


class VisibilityGraph:
    def __init__(self, fs: "Flowsheet", margin: float = 15.0):
        from pandid.layout.attach import is_attached
        from pandid.portgeom import port_anchor

        self.obstacles: List[Rect] = []
        x_set: Set[float] = set()
        y_set: Set[float] = set()

        # Port anchors, their outward directions, and the escape node each one
        # stands off to: the single geometry authority the router reads from.
        # The router used to project its own, from a copy of the distances
        # below; the copies agreeing was load-bearing and unenforced.
        self.port_anchors: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self.port_dirs: Dict[Tuple[str, str], str] = {}
        self.port_projs: Dict[Tuple[str, str], Tuple[float, float]] = {}

        for u in fs.units:
            f = u.frame
            if f is None:
                continue
            u_width, u_height = f.w, f.h
            mirrored = f.mirrored

            # An in-line element straddles its own tap (that is the whole point
            # of ``offset=0``), so treating it as an obstacle would push its host
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

            # The label's own obstacle rect and the lanes that clear it were
            # two separately-guarded blocks that happened to test the same
            # ``lpos`` under the same condition, `label_w` computed in the
            # first and only read in the second -- true today because the
            # two conditions are copies of each other, and one unbound
            # `label_w` away from not being. One guard, computing it once,
            # is the same result without relying on that staying true.
            lpos = f.label_pos or "top"
            if u.kind not in ("feed", "product") and lpos != "center":
                label_w = min(150.0, max(40.0, len(u.name) * 7.5))
                if lpos == "top":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, f.y - 20, f.y))
                    y_set.add(f.y - 20.0 - margin)
                    y_set.add(f.y - 10.0)
                elif lpos == "bottom":
                    cx = f.x + u_width / 2
                    self.obstacles.append(Rect(cx - label_w/2, cx + label_w/2, f.y + u_height, f.y + u_height + 25))
                    y_set.add(f.y + u_height + 25.0 + margin)
                    y_set.add(f.y + u_height + 10.0)
                elif lpos == "left":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x - label_w - 15, f.x, cy - 10, cy + 10))
                    x_set.add(f.x - label_w - 15.0 - margin)
                    x_set.add(f.x - 5.0)
                elif lpos == "right":
                    cy = f.y + u_height / 2
                    self.obstacles.append(Rect(f.x + u_width, f.x + u_width + label_w + 15, cy - 10, cy + 10))
                    x_set.add(f.x + u_width + label_w + 15.0 + margin)
                    x_set.add(f.x + u_width + 5.0)

            # Routing lanes around the unit
            x_set.add(f.x - margin)
            x_set.add(f.x + u_width + margin)
            y_set.add(f.y - margin)
            y_set.add(f.y + u_height + margin)

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
                self.port_projs[(u.name, name)] = (px_proj, py_proj)
                x_set.add(px_proj)
                y_set.add(py_proj)

        # Two nozzles closer together than their stand-offs add up to turn on a
        # lane midway between them instead (see ``share_escape_room``), and no
        # unit puts that lane here. Carry it, or the search has nothing to run
        # along and the router falls back to an L nothing has checked.
        for stream in fs.streams:
            src, dst = stream.source, stream.dest
            if src.owner is None or dst.owner is None:
                continue
            s_key, d_key = (src.owner.name, src.name), (dst.owner.name, dst.name)
            if s_key not in self.port_projs or d_key not in self.port_projs:
                continue
            s_esc, d_esc = share_escape_room(
                self.port_anchors[s_key], self.port_dirs[s_key], self.port_projs[s_key],
                self.port_anchors[d_key], self.port_dirs[d_key], self.port_projs[d_key],
                self.obstacles,
            )
            for x, y in (s_esc, d_esc):
                x_set.add(x)
                y_set.add(y)

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
        xs, ys = self.xs, self.ys

        # The lanes and the obstacles are both settled here, so the obstacles
        # are indexed against the lanes once and every test below is asked of
        # only the few that can reach the point or the segment in hand. What
        # decides is still Rect's own two predicates -- each step below names
        # the half of one it stands in for -- so this is the same graph, built
        # without the scan that dominated it. Example 11 lays a 394x283 grid
        # over 146 obstacles: the node pass alone was 16 million rectangle
        # tests, and under a profiler 99% of route() was graph construction.

        # A node is invalid when an obstacle strictly contains it. Strict on
        # both axes means one obstacle rules out one contiguous block of the
        # grid, which bisection finds outright, and nothing outside those
        # blocks is looked at at all. The blocked coordinates are kept per
        # lane because that is the form the two edge passes want them in.
        blocked_on_row: List[Set[float]] = [set() for _ in ys]   # x's, per y
        blocked_on_col: List[Set[float]] = [set() for _ in xs]   # y's, per x
        for o in self.obstacles:
            i0, i1 = bisect_right(xs, o.x_min), bisect_left(xs, o.x_max)
            j0, j1 = bisect_right(ys, o.y_min), bisect_left(ys, o.y_max)
            inside_x, inside_y = xs[i0:i1], ys[j0:j1]
            for j in range(j0, j1):
                blocked_on_row[j].update(inside_x)
            for i in range(i0, i1):
                blocked_on_col[i].update(inside_y)

        self.nodes: Set[Tuple[float, float]] = {
            (x, y) for j, y in enumerate(ys) for x in xs if x not in blocked_on_row[j]
        }

        # Build adjacency list
        self.edges: Dict[Tuple[float, float], List[Tuple[float, float]]] = {n: [] for n in self.nodes}

        # A run along a lane is blocked by an obstacle whose span *touches*
        # that lane: intersects_segment is inclusive there, a segment along an
        # obstacle's edge being no lane to route on, so these bands are closed
        # where the node test above is open. One pass over the obstacles
        # leaves every lane holding the spans that reach it.
        row_spans: List[List[Tuple[float, float]]] = [[] for _ in ys]  # (x_min, x_max), per y
        col_spans: List[List[Tuple[float, float]]] = [[] for _ in xs]  # (y_min, y_max), per x
        for o in self.obstacles:
            for j in range(bisect_left(ys, o.y_min), bisect_right(ys, o.y_max)):
                row_spans[j].append((o.x_min, o.x_max))
            for i in range(bisect_left(xs, o.x_min), bisect_right(xs, o.x_max)):
                col_spans[i].append((o.y_min, o.y_max))

        # Horizontal edges
        for j, y in enumerate(ys):
            valid_x = [x for x in xs if x not in blocked_on_row[j]]
            for k, clear in enumerate(clear_gaps(valid_x, row_spans[j])):
                if clear:
                    x1, x2 = valid_x[k], valid_x[k+1]
                    self.edges[(x1, y)].append((x2, y))
                    self.edges[(x2, y)].append((x1, y))

        # Vertical edges
        for i, x in enumerate(xs):
            valid_y = [y for y in ys if y not in blocked_on_col[i]]
            for k, clear in enumerate(clear_gaps(valid_y, col_spans[i])):
                if clear:
                    y1, y2 = valid_y[k], valid_y[k+1]
                    self.edges[(x, y1)].append((x, y2))
                    self.edges[(x, y2)].append((x, y1))
