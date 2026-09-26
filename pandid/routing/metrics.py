"""Pure measurements of orthogonal route geometry."""

from __future__ import annotations

from typing import Optional

from pandid.routing.astar import OPPOSITE
from pandid.routing.visibility import TRAVEL

Point = tuple[float, float]


def min_bends(a: Point, dir_a: Optional[str], b: Point, dir_b: Optional[str]) -> Optional[int]:
    """Return the unobstructed bend minimum between directed ports.

    Parameters
    ----------
    a, b : Point
        Source and destination port anchors in drawing coordinates.
    dir_a, dir_b : str or None
        Outward compass faces of the source and destination ports.

    Returns
    -------
    int or None
        Minimum orthogonal direction changes, or ``None`` if a face is unknown.
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

    # Perpendicular ports need one bend when both directed legs can advance.
    ahead_on_s = s_sign * (b[s_axis] - a[s_axis]) > eps
    ahead_on_t = t_sign * (b[t_axis] - a[t_axis]) > eps
    return 1 if (ahead_on_s and ahead_on_t) else 3


def waypoint_segments(waypoints: list[Point]) -> list[tuple[Point, Point, str]]:
    """Return the nonzero orthogonal segments in a waypoint path.

    Parameters
    ----------
    waypoints : list[Point]
        Ordered route coordinates.

    Returns
    -------
    list[tuple[Point, Point, str]]
        Segment endpoints and ``"h"`` or ``"v"`` axis. Diagonal legs are omitted.
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
    """Count direction changes between drawn route segments.

    Parameters
    ----------
    waypoints : list[Point]
        Ordered route coordinates, including any collinear waypoints.

    Returns
    -------
    int
        Number of changes between consecutive orthogonal travel directions.
    """
    segs = waypoint_segments(waypoints)
    dirs = []
    for p1, p2, axis in segs:
        dirs.append(
            ("E" if p2[0] > p1[0] else "W") if axis == "h" else ("S" if p2[1] > p1[1] else "N")
        )
    return sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)


def path_length(points: list[Point]) -> float:
    """Measure the Manhattan length of a waypoint path.

    Parameters
    ----------
    points : list[Point]
        Ordered route coordinates.

    Returns
    -------
    float
        Sum of the absolute coordinate changes between consecutive points.
    """
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:]))


def crossing_point(h: tuple[Point, Point], v: tuple[Point, Point]) -> Optional[Point]:
    """Find a proper crossing between horizontal and vertical segments.

    Parameters
    ----------
    h : tuple[Point, Point]
        Endpoints of a horizontal segment.
    v : tuple[Point, Point]
        Endpoints of a vertical segment.

    Returns
    -------
    Point or None
        Interior crossing coordinate, or ``None`` for a touch or no crossing.
    """
    y = h[0][1]
    x = v[0][0]
    xlo, xhi = sorted((h[0][0], h[1][0]))
    ylo, yhi = sorted((v[0][1], v[1][1]))
    eps = 1e-6
    if xlo + eps < x < xhi - eps and ylo + eps < y < yhi - eps:
        return (x, y)
    return None


def overlap_length(a: tuple[Point, Point], b: tuple[Point, Point], axis: str) -> float:
    """Measure the shared length of two segments on one axis.

    Parameters
    ----------
    a, b : tuple[Point, Point]
        Segment endpoint pairs.
    axis : str
        ``"h"`` for horizontal segments or ``"v"`` for vertical segments.

    Returns
    -------
    float
        Length of their shared track, or zero when they do not overlap.
    """
    i = 1 if axis == "h" else 0
    if abs(a[0][i] - b[0][i]) > 1e-6:
        return 0.0
    j = 1 - i
    alo, ahi = sorted((a[0][j], a[1][j]))
    blo, bhi = sorted((b[0][j], b[1][j]))
    return max(0.0, min(ahi, bhi) - max(alo, blo))
