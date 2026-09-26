"""Bounded, read-only placement proposals for completed process drawings.

Proposals move resolved frames only. They do not change the model, choose
faces, or accept a drawing; :mod:`pandid.layout.trials` evaluates those effects
on an isolated, fully routed copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING

from pandid.layout.claims import stacks
from pandid.layout.coordinates import ROW_GAP
from pandid.layout.halo import Pad, balloon_pads
from pandid.layout.pixel import grid_limits
from pandid.layout.stages import process_streams, process_units
from pandid.layout.structure import Structure, infer
from pandid.portgeom import resolve_port, unit_box
from pandid.routing.metrics import min_bends, waypoint_segments
from pandid.routing.visibility import Rect, escape_distance, share_escape_room

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.streams import Stream
    from pandid.units import Unit


MAX_CANDIDATES = 24
MAX_PREFLIGHTS = 24
_MIN_SHIFT = 5.0
_MAX_SHIFT = 2.0 * ROW_GAP


def _placed(unit: Unit) -> Frame:
    """Return a process unit's required resolved frame.

    Parameters
    ----------
    unit : Unit
        Unit in a completed drawing.

    Returns
    -------
    Frame
        Its resolved geometry.

    Raises
    ------
    ValueError
        If the drawing has no placement for this unit.
    """
    frame = unit.frame
    if frame is None:
        raise ValueError("candidate unit has no frame")
    return frame


@dataclass(frozen=True)
class Candidate:
    """A legal local translation of one connected process group.

    Attributes
    ----------
    units : tuple[int, ...]
        Global ``Flowsheet.units`` indices in original order.
    dy : float
        Vertical displacement in drawing pixels.
    stream : int
        Process-stream index that proposed the alignment.
    estimated_gain : float
        Cheap reduction in affected stream costs; only a trial can
        establish final-drawing improvement.
    """

    units: tuple[int, ...]
    dy: float
    stream: int
    estimated_gain: float

    def apply(self, frames: list[Frame | None]) -> None:
        """Translate detached frames for a dry-run trial.

        Parameters
        ----------
        frames : list[Frame or None]
            Index-aligned frames detached by ``evaluate_trial``.

        Returns
        -------
        None
            Only frames listed in this proposal change.
        """
        for index in self.units:
            frame = frames[index]
            if frame is None:
                raise ValueError("candidate unit has no frame")
            frame.y += self.dy


def _box(unit: Unit, frame: Frame, pad: Pad) -> tuple[float, float, float, float]:
    """Include a process unit's reserved control clearance.

    Parameters
    ----------
    unit : Unit
        Process unit whose drawn bounds are needed.
    frame : Frame
        Current or proposed placement.
    pad : Pad
        Instrument clearance reserved by the layout engine.

    Returns
    -------
    tuple[float, float, float, float]
        Padded left, top, right, and bottom bounds.
    """
    left, top, right, bottom = unit_box(unit, frame)
    return left - pad.west, top - pad.north, right + pad.east, bottom + pad.south


def _overlap(a: tuple[float, float, float, float],
             b: tuple[float, float, float, float]) -> bool:
    """Check whether two axis-aligned reservations share interior.

    Parameters
    ----------
    a, b : tuple[float, float, float, float]
        Left, top, right, and bottom bounds.

    Returns
    -------
    bool
        Whether the interiors intersect.
    """
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _segment_hits_box(a: tuple[float, float], b: tuple[float, float],
                      box: tuple[float, float, float, float]) -> bool:
    """Check an orthogonal segment against a box's open interior.

    Parameters
    ----------
    a, b : tuple[float, float]
        Segment endpoints.
    box : tuple[float, float, float, float]
        Left, top, right, and bottom bounds.

    Returns
    -------
    bool
        Whether the segment enters the box.
    """
    if a[1] == b[1]:
        return box[1] < a[1] < box[3] and max(a[0], b[0]) > box[0] and min(a[0], b[0]) < box[2]
    if a[0] == b[0]:
        return box[0] < a[0] < box[2] and max(a[1], b[1]) > box[1] and min(a[1], b[1]) < box[3]
    return False


def _movable(group: tuple[Unit, ...]) -> bool:
    """Reject a group that owns its row or a hand-routed endpoint.

    Parameters
    ----------
    group : tuple[Unit, ...]
        Connected process group considered for vertical translation.

    Returns
    -------
    bool
        Whether all group members leave their vertical position free.
    """
    for unit in group:
        pin = unit.pin_
        if pin is not None and (pin.y is not None or pin.row is not None):
            return False
        if any(stream.route is not None and stream.route.manual
               for port in unit.ports.values()
               if (stream := port.stream) is not None):
            return False
    return True


def _legal(fs: Flowsheet, group: tuple[Unit, ...], dy: float,
           boxes: dict[Unit, tuple[float, float, float, float]]) -> bool:
    """Reject pin, grid-order, manual-route, and occupied-box conflicts.

    Parameters
    ----------
    fs : Flowsheet
        Current settled drawing.
    group : tuple[Unit, ...]
        Connected process units that would move together.
    dy : float
        Proposed vertical shift.
    boxes : dict[Unit, tuple[float, float, float, float]]
        Current process reservations, including control clearance.

    Returns
    -------
    bool
        Whether inexpensive preflight checks permit an exact trial.
    """
    moving = set(group)
    if not group or not _movable(group) or abs(dy) < _MIN_SHIFT or abs(dy) > _MAX_SHIFT:
        return False
    for unit in group:
        lower, upper = grid_limits(unit, "y", boxes, moving=moving)
        if not lower <= _placed(unit).y + dy <= upper:
            return False
    shifted = {unit: (box[0], box[1] + dy, box[2], box[3] + dy)
               for unit, box in boxes.items() if unit in moving}
    for unit, box in shifted.items():
        if any(_overlap(box, other_box) for other, other_box in boxes.items()
               if other not in moving):
            return False
    placed = {unit: replace(_placed(unit), y=_placed(unit).y + dy)
              if unit in moving else _placed(unit) for unit in boxes}
    drawn = {unit: unit_box(unit, frame) for unit, frame in placed.items()}
    rects = [Rect(box[0], box[2], box[1], box[3]) for box in drawn.values()]
    normals = {"N": (0.0, -1.0), "S": (0.0, 1.0),
               "E": (1.0, 0.0), "W": (-1.0, 0.0)}
    for stream in fs.streams:
        source, dest = stream.source.owner, stream.dest.owner
        if source not in moving and dest not in moving:
            continue
        if source not in placed or dest not in placed:
            continue
        endpoints = (source, dest)
        resolved = (resolve_port(source, placed[source], stream.source.name),
                    resolve_port(dest, placed[dest], stream.dest.name))
        projections = []
        for unit, port in zip(endpoints, resolved):
            normal = normals[port.face]
            distance = escape_distance(unit.kind, placed[unit].label_pos, port.face)
            projections.append((port.anchor[0] + distance * normal[0],
                                port.anchor[1] + distance * normal[1]))
        shared = share_escape_room(resolved[0].anchor, resolved[0].face, projections[0],
                                   resolved[1].anchor, resolved[1].face, projections[1],
                                   rects)
        for unit, port, projection in zip(endpoints, resolved, shared):
            if unit in moving and any(_segment_hits_box(port.anchor, projection, box)
                                      for other, box in drawn.items() if other is not unit):
                return False
    for stream in fs.streams:
        route = stream.route
        if route is None or not route.manual:
            continue
        for start, end, _ in waypoint_segments(route.waypoints):
            if any(_segment_hits_box(start, end, drawn[unit]) for unit in moving):
                return False
    # Free-standing instruments stay fixed when process geometry is retried.
    # Attached controls are already represented by the process reservations.
    for control in fs.units:
        if control.kind != "instrument" or getattr(control, "host", None) is not None:
            continue
        if control.frame is not None:
            obstacle = unit_box(control, control.frame)
            if any(_overlap(box, obstacle) for box in shifted.values()):
                return False
    return True


def _groups(fs: Flowsheet, structure: Structure,
            units: list[Unit]) -> dict[Unit, tuple[Unit, ...]]:
    """Keep column stacks and closed branch arms together.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out drawing with seeded process slots.
    structure : Structure
        Immutable split/merge facts for the same drawing.
    units : list[Unit]
        Process units in structure index order.

    Returns
    -------
    dict[Unit, tuple[Unit, ...]]
        Smallest safe move group for each process unit. Interiors of
        partial branch regions are withheld from local translation.
    """
    roots = stacks(fs, units)
    order = {unit: index for index, unit in enumerate(units)}
    members: dict[Unit, set[Unit]] = {}
    for unit, root in roots.items():
        members.setdefault(root, set()).add(unit)
    groups = {unit: set(members[roots[unit]]) for unit in units}
    blocked: set[Unit] = set()
    for region in structure.branch_regions:
        blocked.update((units[region.split], units[region.merge]))
        for arm in region.arms:
            interior = {units[index] for index in arm.units
                        if index not in (region.split, region.merge)}
            if not region.closed:
                blocked.update(interior)
                continue
            for unit in interior:
                groups[unit].update(interior)
    result = {}
    for unit in units:
        if unit in blocked or groups[unit] & blocked:
            continue
        group = groups[unit]
        # A stack may bridge a branch endpoint or two arms. Such a group
        # is not a standalone arm, so leave it to a structural pass.
        if any(groups[member] != group for member in group):
            continue
        result[unit] = tuple(sorted(group, key=order.__getitem__))
    return result


def _estimate(moving: set[Unit], dy: float,
              touching: dict[Unit, list[int]], streams: list[Stream]) -> float:
    """Estimate the affected route length and directed-bend reduction.

    Parameters
    ----------
    moving : set[Unit]
        Process group proposed for translation.
    dy : float
        Proposed vertical shift.
    touching : dict[Unit, list[int]]
        Process-stream indices indexed by either endpoint unit.
    streams : list[Stream]
        Process streams in deterministic drawing order.

    Returns
    -------
    float
        Positive values favor an exact trial; no value accepts a move.
    """
    gain = 0.0
    affected = sorted({index for unit in moving for index in touching.get(unit, ())})
    for index in affected:
        stream = streams[index]
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None or (source not in moving and dest not in moving):
            continue
        current = [resolve_port(source, _placed(source), stream.source.name),
                   resolve_port(dest, _placed(dest), stream.dest.name)]
        proposed = []
        for unit, port in ((source, stream.source), (dest, stream.dest)):
            if unit in moving:
                frame = _placed(unit)
                frame = replace(frame, y=frame.y + dy)
            else:
                frame = _placed(unit)
            proposed.append(resolve_port(unit, frame, port.name))
        for sign, endpoints in ((1.0, current), (-1.0, proposed)):
            first, second = endpoints
            length = abs(first.anchor[0] - second.anchor[0]) + abs(
                first.anchor[1] - second.anchor[1])
            bends = min_bends(first.anchor, first.face, second.anchor, second.face)
            gain += sign * (length + 25.0 * (bends or 0))
    return gain


def generate(fs: Flowsheet, structure: Structure | None = None,
             limit: int = MAX_CANDIDATES) -> tuple[Candidate, ...]:
    """Propose a stable, bounded list of legal stream-alignment moves.

    Parameters
    ----------
    fs : Flowsheet
        Completed layout and routes. This function does not alter it.
    structure : Structure or None, optional
        Facts inferred for this drawing; inferred here when omitted.
    limit : int, optional
        Maximum proposals returned, capped by ``MAX_CANDIDATES``.

    Returns
    -------
    tuple[Candidate, ...]
        Proposals ranked by a cheap cost reduction, then stable indices.
        Each can be passed as ``candidate.apply`` to ``evaluate_trial``.

    Raises
    ------
    ValueError
        If placement or routing is stale.
    """
    if fs._layout_stale or fs._route_stale:
        raise ValueError("candidate generation requires completed layout and routing")
    if limit <= 0:
        return ()
    units = process_units(fs)
    structure = infer(fs) if structure is None else structure
    if structure.unit_count != len(units):
        raise ValueError("structure does not match process unit count")
    pads = balloon_pads(fs)
    boxes = {unit: _box(unit, _placed(unit), pads.get(unit, Pad())) for unit in units}
    groups = _groups(fs, structure, units)
    global_index = {unit: index for index, unit in enumerate(fs.units)}
    proposals: dict[tuple[tuple[int, ...], float], Candidate] = {}
    opportunities: dict[tuple[tuple[int, ...], float],
                        tuple[float, int, int, float, tuple[Unit, ...]]] = {}
    streams = process_streams(fs)
    touching: dict[Unit, list[int]] = {}
    for index, stream in enumerate(streams):
        for port in (stream.source, stream.dest):
            if port.owner is not None:
                touching.setdefault(port.owner, []).append(index)
    for stream_index, stream in enumerate(streams):
        if stream.is_recycle:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None or _placed(source).col == _placed(dest).col:
            continue
        first = resolve_port(source, _placed(source), stream.source.name)
        second = resolve_port(dest, _placed(dest), stream.dest.name)
        if first.face not in ("E", "W") or second.face not in ("E", "W"):
            continue
        for target, dy in ((dest, first.anchor[1] - second.anchor[1]),
                           (source, second.anchor[1] - first.anchor[1])):
            group = groups.get(target)
            if group is None or source in group and dest in group:
                continue
            if not _MIN_SHIFT <= abs(dy) <= _MAX_SHIFT or not _movable(group):
                continue
            indices = tuple(sorted(global_index[unit] for unit in group))
            key = indices, round(dy, 6)
            choice = (-abs(dy), stream_index, global_index[target], dy, group)
            if key not in opportunities or choice[:3] < opportunities[key][:3]:
                opportunities[key] = choice
    for _, stream_index, _, dy, group in sorted(opportunities.values())[:MAX_PREFLIGHTS]:
        if not _legal(fs, group, dy, boxes):
            continue
        gain = _estimate(set(group), dy, touching, streams)
        if gain <= 0:
            continue
        indices = tuple(sorted(global_index[unit] for unit in group))
        key = indices, round(dy, 6)
        candidate = Candidate(indices, round(dy, 6), stream_index, round(gain, 6))
        if key not in proposals or candidate.estimated_gain > proposals[key].estimated_gain:
            proposals[key] = candidate
    return tuple(sorted(proposals.values(),
                        key=lambda item: (-item.estimated_gain, item.stream,
                                          item.units, item.dy))[:min(limit, MAX_CANDIDATES)])
