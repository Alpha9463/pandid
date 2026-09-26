"""Named conflicts in completed unit and stream geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.portgeom import resolve_port, unit_box
from pandid.routing.metrics import crossing_pairs

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


_BODY_TOL = 1.0
_SQUARE_TOL = 0.5
_POINT_TOL = 0.05
_DIRECTION = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


@dataclass(frozen=True, order=True)
class Conflict:
    """Identify one geometric defect across copies of a flowsheet.

    Attributes
    ----------
    kind : str
        Stable category of the defect.
    streams : tuple[int, ...]
        Stream indices in global flowsheet order.
    units : tuple[int, ...]
        Unit indices in global flowsheet order.
    port : str or None
        Endpoint port name when the defect belongs to a nozzle.
    """

    kind: str
    streams: tuple[int, ...] = ()
    units: tuple[int, ...] = ()
    port: str | None = None


def boxes_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """Test whether two unit boxes overlap beyond edge tolerance.

    Parameters
    ----------
    a, b : tuple[float, float, float, float]
        Left, top, right, and bottom coordinates.

    Returns
    -------
    bool
        Whether the box interiors overlap.
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
    """Test whether an orthogonal segment crosses a unit interior.

    Parameters
    ----------
    a, b : tuple[float, float]
        Segment endpoints.
    box : tuple[float, float, float, float]
        Left, top, right, and bottom unit coordinates.

    Returns
    -------
    bool
        Whether the segment enters the box interior.
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
    """Compare two route endpoints at pin-coordinate precision.

    Parameters
    ----------
    a, b : tuple[float, float]
        Points to compare.

    Returns
    -------
    bool
        Whether both coordinates match within tolerance.
    """
    return abs(a[0] - b[0]) <= _POINT_TOL and abs(a[1] - b[1]) <= _POINT_TOL


def _outward(a: tuple[float, float], b: tuple[float, float], face: str) -> bool:
    """Check that the first nonzero leg follows a port's outward face.

    Parameters
    ----------
    a, b : tuple[float, float]
        Leg endpoints in outward travel order.
    face : str
        Port's outward compass direction.

    Returns
    -------
    bool
        Whether the leg is orthogonal and outward.
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
) -> set[Conflict]:
    """Name a detached, inward, or obstructed automatic nozzle exit.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing under inspection.
    stream_index : int
        Global index of the stream.
    boxes : list[tuple[int, tuple[float, float, float, float]]]
        Placed unit boxes indexed by global unit order.
    index_by_id : dict[int, int]
        Global unit indices keyed by object identity.
    at_source : bool
        Whether to inspect the source rather than the destination.
    points : list[tuple[float, float]]
        Final route waypoints.

    Returns
    -------
    set[Conflict]
        Defects found at the selected endpoint.
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
        if getattr(fs.units[blocker_index], "host", None) is stream:
            continue
        if segment_crosses_box(ordered[0], next_point, box):
            result.add(
                Conflict("blocked-exit", (stream_index,), (owner_index, blocker_index), name)
            )
    return result


def analyze_conflicts(fs: Flowsheet) -> tuple[Conflict, ...]:
    """Name geometric defects on final placed and routed objects.

    Parameters
    ----------
    fs : Flowsheet
        Drawing with final frames and routes.

    Returns
    -------
    tuple[Conflict, ...]
        Deterministically ordered conflicts with global object indices.
    """
    index_by_id = {id(unit): index for index, unit in enumerate(fs.units)}
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
                _exit_conflicts(fs, stream_index, boxes, index_by_id, True, route.waypoints)
            )
            conflicts.update(
                _exit_conflicts(fs, stream_index, boxes, index_by_id, False, route.waypoints)
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
                if getattr(fs.units[unit_index], "host", None) is stream:
                    continue
                if segment_crosses_box(a, b, box):
                    conflicts.add(Conflict("route-crosses-unit", (stream_index,), (unit_index,)))
    paths: list[list[tuple[float, float]] | None] = []
    for stream in fs.streams:
        route = stream.route
        if route is None or stream.source.owner.frame is None or stream.dest.owner.frame is None:
            paths.append(None)
        elif route.manual and stream.source.owner.frame and stream.dest.owner.frame:
            start = resolve_port(
                stream.source.owner, stream.source.owner.frame, stream.source.name
            ).point
            end = resolve_port(stream.dest.owner, stream.dest.owner.frame, stream.dest.name).point
            paths.append([start, *route.waypoints, end])
        else:
            paths.append(route.waypoints)
    conflicts.update(Conflict("crossing", streams=pair) for pair in crossing_pairs(paths))
    return tuple(sorted(conflicts))
