"""Routing primitives for orthogonal flowsheet paths."""

import bisect
import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple
from pandid.routing.visibility import VisibilityGraph

BEND_PENALTY = 500.0


Axis = Literal["h", "v"]


CROSSING_PENALTY = 10.0


#: Crossing queries before a search binds the index's sorted tracks locally.
_INLINE_CROSSING_QUERY_THRESHOLD = 500


_AXIS: Dict[str, Axis] = {"E": "h", "W": "h", "N": "v", "S": "v"}


@dataclass
class CrossingIndex:
    """Index orthogonal route segments for crossing queries.

    Attributes
    ----------
    h : dict[float, list[tuple[float, float]]]
        Horizontal spans keyed by their y coordinate.
    v : dict[float, list[tuple[float, float]]]
        Vertical spans keyed by their x coordinate.
    """

    h: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)
    v: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)

    _h_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)
    _v_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)

    def record(self, path: List[Tuple[float, float]]) -> None:
        """Record the merged segments of a committed route.

        Parameters
        ----------
        path : list[tuple[float, float]]
            Orthogonal route waypoints.
        """
        for axis, fixed, lo, hi in committed_segments(path):
            (self.h if axis == "h" else self.v).setdefault(fixed, []).append((lo, hi))

    def _sorted_keys(self, axis: Axis) -> List[float]:
        """Return the sorted coordinates for one segment axis.

        Parameters
        ----------
        axis : {"h", "v"}
            Axis whose fixed coordinates are requested.

        Returns
        -------
        list[float]
            Sorted fixed coordinates for the selected axis.
        """
        d = self.h if axis == "h" else self.v
        cached = self._h_sorted if axis == "h" else self._v_sorted
        if cached is not None and cached[0] == len(d):
            return cached[1]
        keys = sorted(d)
        if axis == "h":
            self._h_sorted = (len(d), keys)
        else:
            self._v_sorted = (len(d), keys)
        return keys

    def crosses(self, node: Tuple[float, float], axis: Axis) -> int:
        """Count segments crossed by a route continuing through a node.

        Parameters
        ----------
        node : tuple[float, float]
            Node on the candidate route.
        axis : {"h", "v"}
            Axis on which the candidate route continues.

        Returns
        -------
        int
            Number of perpendicular segments that strictly contain the node.

        Raises
        ------
        ValueError
            If ``axis`` is not horizontal or vertical.
        """
        if axis not in ("h", "v"):
            raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")
        x, y = node
        if axis == "v":
            return sum(1 for lo, hi in self.h.get(y, ()) if lo < x < hi)
        return sum(1 for lo, hi in self.v.get(x, ()) if lo < y < hi)

    def crossings_along(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> int:
        """Count segments crossed by an entire orthogonal run.

        Parameters
        ----------
        p1, p2 : tuple[float, float]
            Endpoints of the candidate run.

        Returns
        -------
        int
            Number of perpendicular segments strictly inside the run. Diagonal and
            zero-length pairs return zero.
        """
        if p1[1] == p2[1] and p1[0] != p2[0]:
            y = p1[1]
            xlo, xhi = sorted((p1[0], p2[0]))
            keys = self._sorted_keys("v")
            i0, i1 = bisect.bisect_right(keys, xlo), bisect.bisect_left(keys, xhi)
            if i0 == i1:
                return 0
            return sum(1 for x in keys[i0:i1] for lo, hi in self.v[x] if lo < y < hi)
        if p1[0] == p2[0] and p1[1] != p2[1]:
            x = p1[0]
            ylo, yhi = sorted((p1[1], p2[1]))
            keys = self._sorted_keys("h")
            i0, i1 = bisect.bisect_right(keys, ylo), bisect.bisect_left(keys, yhi)
            if i0 == i1:
                return 0
            return sum(1 for y in keys[i0:i1] for lo, hi in self.h[y] if lo < x < hi)
        return 0


def committed_segments(path: List[Tuple[float, float]]) -> List[Tuple[Axis, float, float, float]]:
    """Return merged orthogonal segments for a route.

    Parameters
    ----------
    path : list[tuple[float, float]]
        Route waypoints, including any fixed nozzle stubs.

    Returns
    -------
    list[tuple[{"h", "v"}, float, float, float]]
        ``(axis, fixed_coordinate, lower_bound, upper_bound)`` tuples.

    Raises
    ------
    ValueError
        If consecutive waypoints form a diagonal segment.
    """

    def axis_of(p: Tuple[float, float], q: Tuple[float, float]) -> Optional[Axis]:
        """Return the axis of an orthogonal segment.

        Parameters
        ----------
        p, q : tuple[float, float]
            Segment endpoints.

        Returns
        -------
        {"h", "v"} or None
            Segment axis, or ``None`` for equal points.

        Raises
        ------
        ValueError
            If the endpoints form a diagonal segment.
        """
        dx, dy = p[0] != q[0], p[1] != q[1]
        if dx and dy:
            raise ValueError(f"committed_segments: {p!r} -> {q!r} is diagonal, not orthogonal")
        if dx:
            return "h"
        if dy:
            return "v"
        return None

    dedup = [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]

    segs = []
    n = len(dedup)
    i = 0
    while i < n - 1:
        ax = axis_of(dedup[i], dedup[i + 1])
        assert ax is not None
        j = i + 1
        while j < n - 1 and axis_of(dedup[j], dedup[j + 1]) == ax:
            j += 1
        p0, p1 = dedup[i], dedup[j]
        idx = 0 if ax == "h" else 1
        fixed = p0[1 - idx]
        lo, hi = (p0[idx], p1[idx]) if p0[idx] <= p1[idx] else (p1[idx], p0[idx])
        segs.append((ax, fixed, lo, hi))
        i = j
    return segs


MAX_EXPANSIONS_PER_NODE = 16
MIN_EXPANSION_BUDGET = 50_000

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def get_dir(p1: Tuple[float, float], p2: Tuple[float, float]) -> Optional[str]:
    """Return the cardinal direction from one point to another.

    Parameters
    ----------
    p1, p2 : tuple[float, float]
        Orthogonal segment endpoints.

    Returns
    -------
    str or None
        ``E``, ``W``, ``N``, or ``S``; ``None`` for equal points.
    """
    if p1[0] < p2[0]:
        return "E"
    if p1[0] > p2[0]:
        return "W"
    if p1[1] < p2[1]:
        return "S"
    if p1[1] > p2[1]:
        return "N"
    return None


def heuristic(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Estimate the remaining A* cost between two graph nodes.

    Parameters
    ----------
    a, b : tuple[float, float]
        Current and goal coordinates.

    Returns
    -------
    float
        Manhattan distance plus one potential bend penalty.
    """
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    h = dx + dy

    if dx > 0 and dy > 0:
        h += BEND_PENALTY
    return h


def find_path(
    graph: VisibilityGraph,
    start: Tuple[float, float],
    goal: Tuple[float, float],
    start_dir: Optional[str] = None,
    goal_dir: Optional[str] = None,
    edge_penalties: Optional[Dict[Tuple[Tuple[float, float], Tuple[float, float]], float]] = None,
    is_recycle: bool = False,
    crossing_index: Optional[CrossingIndex] = None,
) -> List[Tuple[float, float]]:
    """Find a lowest-cost orthogonal path through a visibility graph.

    Parameters
    ----------
    graph : VisibilityGraph
        Graph of clear routing lanes.
    start, goal : tuple[float, float]
        Escape-node coordinates for the route.
    start_dir, goal_dir : str or None, optional
        Outward directions at the source and destination ports.
    edge_penalties : dict[tuple[tuple[float, float], tuple[float, float]], float], optional
        Accumulated penalties for already-used directed graph edges.
    is_recycle : bool, default=False
        Whether recycle-lane preferences apply.
    crossing_index : CrossingIndex, optional
        Segments of routes committed before this route.

    Returns
    -------
    list[tuple[float, float]]
        Graph nodes from ``start`` to ``goal``, or an empty list when no path
        is available.

    Raises
    ------
    ValueError
        If either endpoint is non-finite.
    RuntimeError
        If the search exceeds its expansion budget.
    """
    for role, point in (("start", start), ("goal", goal)):
        if not (math.isfinite(point[0]) and math.isfinite(point[1])):
            raise ValueError(
                f"cannot route from a non-finite {role} {point!r}: every "
                f"comparison against it is false, so the search would settle "
                f"no state and never return."
            )

    if edge_penalties is None:
        edge_penalties = {}

    budget = max(MIN_EXPANSION_BUDGET, MAX_EXPANSIONS_PER_NODE * len(graph.nodes))
    expansions = 0
    crossing_queries = 0
    horizontal_tracks: Optional[List[float]] = None
    vertical_tracks: Optional[List[float]] = None

    queue: list[
        tuple[float, float, int, tuple[float, float], Optional[str], list[tuple[float, float]]]
    ] = []
    heapq.heappush(queue, (0, 0, 0, start, start_dir, [start]))

    visited: Dict[Tuple[Tuple[float, float], Optional[str]], float] = {}

    counter = 1

    while queue:
        expansions += 1
        if expansions > budget:
            raise RuntimeError(
                f"routing {start} -> {goal} expanded {expansions} states over "
                f"{len(graph.nodes)} graph nodes, past the {budget} this graph "
                f"is allowed, without settling. The search is not converging: "
                f"suspect a coordinate that does not compare, or a cost that "
                f"keeps falling."
            )
        f, g, _, current, cur_dir, path = heapq.heappop(queue)

        if current == goal:
            return path

        state_key = (current, cur_dir)
        if state_key in visited and visited[state_key] <= g:
            continue
        visited[state_key] = g

        for neighbor in graph.edges.get(current, []):
            ndir = get_dir(current, neighbor)

            if cur_dir and ndir == OPPOSITE[cur_dir]:
                continue

            if neighbor == goal and goal_dir:
                if ndir == goal_dir:
                    continue

            dist = abs(neighbor[0] - current[0]) + abs(neighbor[1] - current[1])
            cost = g + dist + edge_penalties.get((current, neighbor), 0.0)

            if crossing_index is not None:
                crossing_queries += 1
                if crossing_queries <= _INLINE_CROSSING_QUERY_THRESHOLD:
                    cost += CROSSING_PENALTY * crossing_index.crossings_along(current, neighbor)
                else:
                    if horizontal_tracks is None or vertical_tracks is None:
                        horizontal_tracks = crossing_index._sorted_keys("h")
                        vertical_tracks = crossing_index._sorted_keys("v")
                    if current[1] == neighbor[1] and current[0] != neighbor[0]:
                        y = current[1]
                        xlo, xhi = sorted((current[0], neighbor[0]))
                        i0 = bisect.bisect_right(vertical_tracks, xlo)
                        i1 = bisect.bisect_left(vertical_tracks, xhi)
                        if i0 != i1:
                            cost += CROSSING_PENALTY * sum(
                                1
                                for x in vertical_tracks[i0:i1]
                                for lo, hi in crossing_index.v[x]
                                if lo < y < hi
                            )
                    elif current[0] == neighbor[0] and current[1] != neighbor[1]:
                        x = current[0]
                        ylo, yhi = sorted((current[1], neighbor[1]))
                        i0 = bisect.bisect_right(horizontal_tracks, ylo)
                        i1 = bisect.bisect_left(horizontal_tracks, yhi)
                        if i0 != i1:
                            cost += CROSSING_PENALTY * sum(
                                1
                                for y in horizontal_tracks[i0:i1]
                                for lo, hi in crossing_index.h[y]
                                if lo < x < hi
                            )

            bend_cost = BEND_PENALTY
            if is_recycle:
                bend_cost = BEND_PENALTY / 2.0
                if (
                    current[1] == neighbor[1]
                    and current[1] not in graph.recycle_y
                    and current[1] not in (start[1], goal[1])
                ):
                    cost += dist * 10.0
            else:
                if current[1] == neighbor[1] and current[1] in graph.recycle_y:
                    cost += 100000.0

            if cur_dir and ndir != cur_dir:
                cost += bend_cost
            elif cur_dir and crossing_index is not None:
                cost += CROSSING_PENALTY * crossing_index.crosses(current, _AXIS[cur_dir])

            if (
                neighbor == goal
                and goal_dir
                and crossing_index is not None
                and CROSSING_PENALTY > 0
            ):
                if ndir is not None and ndir == OPPOSITE[goal_dir]:
                    cost += CROSSING_PENALTY * crossing_index.crosses(goal, _AXIS[ndir])
                elif crossing_index.crosses(goal, _AXIS[OPPOSITE[goal_dir]]):
                    cost += bend_cost

            h = heuristic(neighbor, goal)

            counter += 1
            heapq.heappush(queue, (cost + h, cost, counter, neighbor, ndir, path + [neighbor]))

    return []
