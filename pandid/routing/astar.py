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


#: Crossing queries before a search caches the sorted tracks locally.
_INLINE_CROSSING_QUERY_THRESHOLD = 500


_AXIS: Dict[str, Axis] = {"E": "h", "W": "h", "N": "v", "S": "v"}


@dataclass
class CrossingIndex:
    """Index of orthogonal route segments for crossing queries.

    Attributes
    ----------
    h : dict[float, list[tuple[float, float]]]
        Horizontal spans ``(lo, hi)`` keyed by their y.
    v : dict[float, list[tuple[float, float]]]
        Vertical spans ``(lo, hi)`` keyed by their x.
    """

    h: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)
    v: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)

    _h_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)
    _v_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)

    def record(self, path: List[Tuple[float, float]]) -> None:
        """Record the merged segments of an orthogonal route.

        Parameters
        ----------
        path : list[tuple[float, float]]
            Route waypoints.

        Raises
        ------
        ValueError
            If two consecutive waypoints form a diagonal segment.
        """
        for axis, fixed, lo, hi in committed_segments(path):
            (self.h if axis == "h" else self.v).setdefault(fixed, []).append((lo, hi))

    def _sorted_keys(self, axis: Axis) -> List[float]:
        """Return the sorted fixed coordinates of one axis, cached.

        Parameters
        ----------
        axis : {"h", "v"}
            Axis whose segments to read.

        Returns
        -------
        list[float]
            Sorted y of horizontal or x of vertical segments.
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
        """Count perpendicular segments strictly containing ``node``.

        Parameters
        ----------
        node : tuple[float, float]
            Point the route passes through.
        axis : {"h", "v"}
            Axis on which the route continues through ``node``.

        Returns
        -------
        int
            Number of segments crossed at ``node``.

        Raises
        ------
        ValueError
            If ``axis`` is not ``"h"`` or ``"v"``.
        """
        if axis not in ("h", "v"):
            raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")
        x, y = node
        if axis == "v":
            return sum(1 for lo, hi in self.h.get(y, ()) if lo < x < hi)
        return sum(1 for lo, hi in self.v.get(x, ()) if lo < y < hi)

    def crossings_along(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> int:
        """Count perpendicular segments crossing inside run p1-p2.

        Parameters
        ----------
        p1, p2 : tuple[float, float]
            Ends of the run.

        Returns
        -------
        int
            Number of crossings, 0 for a diagonal or empty run.
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
    """Return a route's merged segments.

    Parameters
    ----------
    path : list[tuple[float, float]]
        Route waypoints.

    Returns
    -------
    list[tuple[str, float, float, float]]
        One ``(axis, fixed, lo, hi)`` per straight run.

    Raises
    ------
    ValueError
        If two consecutive waypoints form a diagonal segment.
    """

    def axis_of(p: Tuple[float, float], q: Tuple[float, float]) -> Optional[Axis]:
        """Return the axis of segment p-q.

        Parameters
        ----------
        p, q : tuple[float, float]
            Segment ends.

        Returns
        -------
        {"h", "v"} or None
            Segment axis, or None for equal points.

        Raises
        ------
        ValueError
            If the segment is diagonal.
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
    """Return the compass direction from p1 to p2, x first.

    Parameters
    ----------
    p1, p2 : tuple[float, float]
        Start and end points.

    Returns
    -------
    str or None
        ``"E"`` or ``"W"``, else ``"S"`` or ``"N"``; None if equal.
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


def heuristic(a: Tuple[float, float], b: Tuple[float, float],
              bend_cost: float = BEND_PENALTY) -> float:
    """Return the Manhattan distance plus one bend if not aligned.

    Parameters
    ----------
    a, b : tuple[float, float]
        Points to measure between.
    bend_cost : float, default=BEND_PENALTY
        Cost of one bend.

    Returns
    -------
    float
        Estimated path cost.
    """
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    h = dx + dy

    if dx > 0 and dy > 0:
        h += bend_cost
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
    """Return the cheapest orthogonal path on the graph.

    Parameters
    ----------
    graph : VisibilityGraph
        Graph to search.
    start, goal : tuple[float, float]
        Escape nodes of the source and destination ports.
    start_dir, goal_dir : str or None, optional
        Outward directions at the source and destination ports.
    edge_penalties : dict, optional
        Penalties on directed edges used by earlier routes.
    is_recycle : bool, default=False
        Favour recycle lanes and halve the bend cost.
    crossing_index : CrossingIndex or None, optional
        Routes drawn before this one.

    Returns
    -------
    list[tuple[float, float]]
        Path from ``start`` to ``goal``, or ``[]`` if none.

    Raises
    ------
    ValueError
        If ``start`` or ``goal`` is non-finite.
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

            if neighbor == goal and goal_dir and crossing_index is not None:
                if ndir is not None and ndir == OPPOSITE[goal_dir]:
                    cost += CROSSING_PENALTY * crossing_index.crosses(goal, _AXIS[ndir])
                elif crossing_index.crosses(goal, _AXIS[OPPOSITE[goal_dir]]):
                    cost += bend_cost

            h = heuristic(neighbor, goal, bend_cost)

            counter += 1
            heapq.heappush(queue, (cost + h, cost, counter, neighbor, ndir, path + [neighbor]))

    return []
