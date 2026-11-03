"""Measurements of orthogonal route geometry."""

from __future__ import annotations

from typing import Optional, Sequence

from pandid.routing.astar import OPPOSITE
from pandid.routing.visibility import TRAVEL

Point = tuple[float, float]


def min_bends(a: Point, dir_a: Optional[str], b: Point, dir_b: Optional[str]) -> Optional[int]:
    """Return the fewest bends between two ports, aligned within 1e-6.

    Parameters
    ----------
    a : Point
        Source port anchor.
    dir_a : str or None
        Source port's outward direction: N, S, E, W or None.
    b : Point
        Destination port anchor.
    dir_b : str or None
        Destination port's outward direction: N, S, E, W or None.

    Returns
    -------
    int or None
        Fewest bends, or None if either direction is unknown.
    """
    if dir_a is None or dir_b is None:
        return None
    s_axis, s_sign = TRAVEL[dir_a]
    t_dir = OPPOSITE[dir_b]
    t_axis, t_sign = TRAVEL[t_dir]
    dx, dy = b[0] - a[0], b[1] - a[1]
    delta = (dx, dy)
    eps = 1e-6

    if s_axis == t_axis:
        perp = delta[1 - s_axis]
        along = s_sign * delta[s_axis]
        if s_sign == t_sign:
            if abs(perp) < eps and along >= -eps:
                return 0
            return 2 if along > eps else 4
        else:
            return 2 if abs(perp) > eps else 4

    # Perpendicular ports need one bend if both legs can advance.
    ahead_on_s = s_sign * (b[s_axis] - a[s_axis]) > eps
    ahead_on_t = t_sign * (b[t_axis] - a[t_axis]) > eps
    return 1 if (ahead_on_s and ahead_on_t) else 3


def waypoint_segments(waypoints: list[Point]) -> list[tuple[Point, Point, str]]:
    """Return each nonzero orthogonal segment of a route.

    Parameters
    ----------
    waypoints : list[Point]
        Route waypoints.

    Returns
    -------
    list[tuple[Point, Point, str]]
        One ``(p1, p2, axis)`` per segment; diagonals are skipped.
    """
    segs = []
    for p1, p2 in zip(waypoints, waypoints[1:]):
        if p1 == p2:
            continue
        if p1[1] == p2[1]:
            segs.append((p1, p2, "h"))
        elif p1[0] == p2[0]:
            segs.append((p1, p2, "v"))
    return segs


def real_bends(waypoints: list[Point]) -> int:
    """Count direction changes between a route's orthogonal segments.

    Parameters
    ----------
    waypoints : list[Point]
        Route waypoints.

    Returns
    -------
    int
        Number of bends.
    """
    segs = waypoint_segments(waypoints)
    dirs = []
    for p1, p2, axis in segs:
        dirs.append(
            ("E" if p2[0] > p1[0] else "W") if axis == "h" else ("S" if p2[1] > p1[1] else "N")
        )
    return sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)


def path_length(points: Sequence[Point]) -> float:
    """Return the Manhattan length of a waypoint path.

    Parameters
    ----------
    points : Sequence[Point]
        Path waypoints.

    Returns
    -------
    float
        Sum of the segment lengths.
    """
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:]))


def crossing_point(h: tuple[Point, Point], v: tuple[Point, Point]) -> Optional[Point]:
    """Return where two segments cross more than 1e-6 inside both.

    Parameters
    ----------
    h : tuple[Point, Point]
        Horizontal segment.
    v : tuple[Point, Point]
        Vertical segment.

    Returns
    -------
    Point or None
        Crossing point, or None if there is none.
    """
    y = h[0][1]
    x = v[0][0]
    xlo, xhi = sorted((h[0][0], h[1][0]))
    ylo, yhi = sorted((v[0][1], v[1][1]))
    eps = 1e-6
    if xlo + eps < x < xhi - eps and ylo + eps < y < yhi - eps:
        return (x, y)
    return None


def crossing_count(paths: list[list[Point]]) -> int:
    """Count :func:`crossing_point` crossings between different paths.

    Parameters
    ----------
    paths : list[list[Point]]
        Route waypoints, one list per path.

    Returns
    -------
    int
        Number of crossings.
    """
    segments = [
        (index, *segment)
        for index, points in enumerate(paths)
        for segment in waypoint_segments(points)
    ]
    horizontal = [(index, (a, b)) for index, a, b, axis in segments if axis == "h"]
    vertical = [(index, (a, b)) for index, a, b, axis in segments if axis == "v"]
    count = 0
    for stream_h, h in horizontal:
        for stream_v, v in vertical:
            if stream_h != stream_v:
                count += crossing_point(h, v) is not None
    return count


def crossing_pairs(paths: list[list[Point] | None]) -> frozenset[tuple[int, int]]:
    """Return the path pairs that :func:`crossing_point` finds crossing.

    Parameters
    ----------
    paths : list[list[Point] or None]
        Route waypoints per path; None entries are skipped.

    Returns
    -------
    frozenset[tuple[int, int]]
        Crossing pairs as ``(lower, higher)`` indices.
    """
    horizontal: list[tuple[int, tuple[Point, Point]]] = []
    vertical: list[tuple[int, tuple[Point, Point]]] = []
    for index, points in enumerate(paths):
        if points is None:
            continue
        for a, b, axis in waypoint_segments(points):
            (horizontal if axis == "h" else vertical).append((index, (a, b)))
    pairs: set[tuple[int, int]] = set()
    for stream_h, h in horizontal:
        for stream_v, v in vertical:
            if stream_h != stream_v and crossing_point(h, v) is not None:
                pairs.add((min(stream_h, stream_v), max(stream_h, stream_v)))
    return frozenset(pairs)
