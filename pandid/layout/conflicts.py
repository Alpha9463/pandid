"""Find named geometric conflicts in a placed and routed flowsheet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.portgeom import resolve_port, unit_box
from pandid.route_geometry import stream_polyline
from pandid.routing.metrics import crossing_pairs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pandid.flowsheet import Flowsheet


# Tolerances in drawing units: body intrusion, off-axis drift and
# point coincidence.
_BODY_TOL = 1.0
_SQUARE_TOL = 0.5
_POINT_TOL = 0.05
# Outward unit step for each face, with y increasing down the sheet.
_DIRECTION = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


@dataclass(frozen=True, order=True)
class Conflict:
    """A geometric defect and the streams and units it involves.

    Attributes
    ----------
    kind : str
        Category of the defect.
    streams : tuple[int, ...]
        Stream indices in flowsheet order.
    units : tuple[int, ...]
        Unit indices in flowsheet order.
    port : str or None
        Port name when the defect is at a nozzle.
    """

    kind: str
    streams: tuple[int, ...] = ()
    units: tuple[int, ...] = ()
    port: str | None = None


def boxes_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """Return whether two boxes overlap beyond the edge tolerance.

    Parameters
    ----------
    a : tuple[float, float, float, float]
        First box as left, top, right, bottom.
    b : tuple[float, float, float, float]
        Second box as left, top, right, bottom.

    Returns
    -------
    bool
        True if they overlap by more than the tolerance.
    """
    return not (
        a[2] - _BODY_TOL <= b[0]
        or b[2] - _BODY_TOL <= a[0]
        or a[3] - _BODY_TOL <= b[1]
        or b[3] - _BODY_TOL <= a[1]
    )


def segment_crosses_box(
    a: tuple[float, float], b: tuple[float, float], box: tuple[float, float, float, float]
) -> bool:
    """Return whether an orthogonal segment enters a box interior.

    Parameters
    ----------
    a : tuple[float, float]
        Segment start.
    b : tuple[float, float]
        Segment end.
    box : tuple[float, float, float, float]
        Box as left, top, right, bottom.

    Returns
    -------
    bool
        True if the segment enters the box; False for a diagonal.
    """
    bx0, by0, bx1, by1 = box
    if abs(a[0] - b[0]) < _SQUARE_TOL:
        return (
            bx0 + _BODY_TOL < a[0] < bx1 - _BODY_TOL
            and min(a[1], b[1]) < by1 - _BODY_TOL
            and max(a[1], b[1]) > by0 + _BODY_TOL
        )
    if abs(a[1] - b[1]) < _SQUARE_TOL:
        return (
            by0 + _BODY_TOL < a[1] < by1 - _BODY_TOL
            and min(a[0], b[0]) < bx1 - _BODY_TOL
            and max(a[0], b[0]) > bx0 + _BODY_TOL
        )
    return False


def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Return whether two points match within tolerance.

    Parameters
    ----------
    a : tuple[float, float]
        First point.
    b : tuple[float, float]
        Second point.

    Returns
    -------
    bool
        True if the points coincide.
    """
    return abs(a[0] - b[0]) <= _POINT_TOL and abs(a[1] - b[1]) <= _POINT_TOL


def _outward(a: tuple[float, float], b: tuple[float, float], face: str) -> bool:
    """Return whether a leg runs orthogonally out of a face.

    Parameters
    ----------
    a : tuple[float, float]
        Leg start, on the face.
    b : tuple[float, float]
        Leg end.
    face : str
        Compass face, ``"N"``, ``"S"``, ``"E"`` or ``"W"``.

    Returns
    -------
    bool
        True if the leg leaves the face square to it.
    """
    direction = _DIRECTION.get(face)
    if direction is None:
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    if direction[0]:
        return abs(dy) < _SQUARE_TOL and dx * direction[0] > _POINT_TOL
    return abs(dx) < _SQUARE_TOL and dy * direction[1] > _POINT_TOL


def _exit_conflicts(
    fs: Flowsheet,
    stream_index: int,
    boxes: list[tuple[int, tuple[float, float, float, float]]],
    index_by_id: dict[int, int],
    at_source: bool,
    points: list[tuple[float, float]],
    hosts: Sequence[object],
) -> set[Conflict]:
    """Return a stream end's detached, inward or blocked nozzle exit.

    Parameters
    ----------
    fs : Flowsheet
        Placed and routed sheet.
    stream_index : int
        Index of the stream in ``fs.streams``.
    boxes : list[tuple[int, tuple[float, float, float, float]]]
        Placed unit boxes with their unit indices.
    index_by_id : dict[int, int]
        Unit indices keyed by object id.
    at_source : bool
        Whether to inspect the source end.
    points : list[tuple[float, float]]
        Route waypoints.
    hosts : Sequence[object]
        Each unit's ``host``, by unit index.

    Returns
    -------
    set[Conflict]
        Conflicts found at that end.
    """
    stream = fs.streams[stream_index]
    port = stream.source if at_source else stream.dest
    owner = port.owner
    owner_index = index_by_id[id(owner)]
    resolved = resolve_port(owner, owner.frame, port.name)
    ordered = points if at_source else list(reversed(points))
    name = port.name
    result: set[Conflict] = set()
    if not _same_point(ordered[0], resolved.anchor):
        result.add(Conflict("detached-endpoint", (stream_index,), (owner_index,), name))
        return result
    next_point = next((point for point in ordered[1:] if not _same_point(point, ordered[0])), None)
    if next_point is None or not _outward(ordered[0], next_point, resolved.face):
        result.add(Conflict("inward-exit", (stream_index,), (owner_index,), name))
        return result
    other = stream.dest.owner if at_source else stream.source.owner
    for blocker_index, box in boxes:
        if blocker_index == owner_index or fs.units[blocker_index] is other:
            continue
        if hosts[blocker_index] is stream:
            continue
        if segment_crosses_box(ordered[0], next_point, box):
            result.add(
                Conflict("blocked-exit", (stream_index,), (owner_index, blocker_index), name)
            )
    return result


def analyze_conflicts(fs: Flowsheet) -> tuple[Conflict, ...]:
    """Return a flowsheet's geometric conflicts, sorted.

    Parameters
    ----------
    fs : Flowsheet
        Placed and routed sheet.

    Returns
    -------
    tuple[Conflict, ...]
        Every conflict, in sorted order.
    """
    index_by_id = {id(unit): index for index, unit in enumerate(fs.units)}
    hosts = [getattr(unit, "host", None) for unit in fs.units]
    boxes = [
        (index, unit_box(unit, unit.frame))
        for index, unit in enumerate(fs.units)
        if unit.frame is not None
    ]
    conflicts: set[Conflict] = set()
    for position, (first, first_box) in enumerate(boxes):
        for second, second_box in boxes[position + 1 :]:
            if boxes_overlap(first_box, second_box):
                conflicts.add(Conflict("unit-overlap", units=(first, second)))

    for stream_index, stream in enumerate(fs.streams):
        source, dest = stream.source.owner, stream.dest.owner
        route = stream.route
        if route is None or (not route.manual and len(route.waypoints) < 2):
            conflicts.add(Conflict("missing-route", streams=(stream_index,)))
            continue
        if source.frame is None or dest.frame is None:
            conflicts.add(Conflict("missing-route", streams=(stream_index,)))
            continue
        source_index, dest_index = index_by_id[id(source)], index_by_id[id(dest)]
        if not route.manual:
            if route.used_fallback:
                conflicts.add(Conflict("fallback", streams=(stream_index,)))
            conflicts.update(
                _exit_conflicts(
                    fs, stream_index, boxes, index_by_id, True, route.waypoints, hosts
                )
            )
            conflicts.update(
                _exit_conflicts(
                    fs, stream_index, boxes, index_by_id, False, route.waypoints, hosts
                )
            )
        start = resolve_port(source, source.frame, stream.source.name).point
        end = resolve_port(dest, dest.frame, stream.dest.name).point
        points = [start, *route.waypoints, end]
        for a, b in zip(points, points[1:]):
            if (
                not route.manual
                and abs(a[0] - b[0]) >= _SQUARE_TOL
                and abs(a[1] - b[1]) >= _SQUARE_TOL
            ):
                conflicts.add(Conflict("route-diagonal", streams=(stream_index,)))
            if route.manual:
                continue
            for unit_index, box in boxes:
                if unit_index in (source_index, dest_index):
                    continue
                if hosts[unit_index] is stream:
                    continue
                if segment_crosses_box(a, b, box):
                    conflicts.add(Conflict("route-crosses-unit", (stream_index,), (unit_index,)))
    paths: list[list[tuple[float, float]] | None] = []
    for stream in fs.streams:
        route = stream.route
        if route is None or stream.source.owner.frame is None or stream.dest.owner.frame is None:
            paths.append(None)
        else:
            paths.append(stream_polyline(stream))
    conflicts.update(Conflict("crossing", streams=pair) for pair in crossing_pairs(paths))
    return tuple(sorted(conflicts))
