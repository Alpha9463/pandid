"""Bounded, read-only placement and face proposals for completed drawings.

Proposals change resolved frames or selected automatic faces on an isolated
trial. They do not change the live model or accept a drawing;
:mod:`pandid.layout.trials` measures the fully routed result.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING

from pandid.layout.claims import stacks
from pandid.layout.coordinates import COL_GAP, ROW_GAP
from pandid.layout.faces import eligible_faces
from pandid.layout.halo import Pad, balloon_pads
from pandid.layout.pixel import grid_limits
from pandid.layout.stages import process_streams, process_units
from pandid.layout.structure import Structure, infer
from pandid.portgeom import resolve_port, unit_box
from pandid.routing.metrics import min_bends, path_length, real_bends, waypoint_segments
from pandid.routing.visibility import Rect, escape_distance, share_escape_room

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.layout.trials import TrialResult
    from pandid.streams import Stream
    from pandid.units import Unit


MAX_CANDIDATES = 24
MAX_PREFLIGHTS = 24
_MIN_SHIFT = 5.0
_MAX_SHIFT = 2.0 * ROW_GAP
_MAX_COLUMN_SHIFT = 2.0 * COL_GAP


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
    """A local placement or automatic-face proposal.

    Attributes
    ----------
    units : tuple[int, ...]
        Global ``Flowsheet.units`` indices in original order.
    dy : float
        Vertical displacement in drawing pixels.
    stream : int
        Global ``Flowsheet.streams`` index behind this proposal.
    estimated_gain : float
        Cheap reduction in affected stream costs; only a trial can
        establish final-drawing improvement.
    face_choices : tuple[tuple[int, str, str], ...]
        Optional global unit index, canonical port name, and face choices.
        These are passed to trial face selection, not author intent.
    dx : float
        Horizontal displacement in drawing pixels.
    """

    units: tuple[int, ...]
    dy: float
    stream: int
    estimated_gain: float
    face_choices: tuple[tuple[int, str, str], ...] = ()
    dx: float = 0.0

    def apply(self, frames: list[Frame | None]) -> None:
        """Translate detached frames for a dry-run trial.

        Parameters
        ----------
        frames : list[Frame or None]
            Index-aligned frames detached by ``evaluate_trial``.

        Returns
        -------
        None
            Only frames listed in this proposal change. Face choices are
            applied by ``evaluate`` during automatic face selection.
        """
        for index in self.units:
            frame = frames[index]
            if frame is None:
                raise ValueError("candidate unit has no frame")
            frame.x += self.dx
            frame.y += self.dy

    def evaluate(self, fs: Flowsheet) -> TrialResult:
        """Score this complete proposal on a routed clone.

        Parameters
        ----------
        fs : Flowsheet
            Settled drawing from which this proposal was generated.

        Returns
        -------
        TrialResult
            Final-drawing measurements and qualification. The live
            drawing is unchanged.
        """
        from pandid.layout.trials import evaluate_trial

        return evaluate_trial(fs, self.apply, face_choices=self.face_choices)


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


def _movable(group: tuple[Unit, ...], axis: str = "y") -> bool:
    """Reject a group with an author-owned axis or manual-route endpoint.

    Parameters
    ----------
    group : tuple[Unit, ...]
        Connected process group considered for translation.
    axis : str, optional
        Coordinate axis proposed for movement.

    Returns
    -------
    bool
        Whether all group members leave the requested coordinate free.
    """
    for unit in group:
        pin = unit.pin_
        rank = "col" if axis == "x" else "row"
        if pin is not None and (getattr(pin, axis) is not None
                                or getattr(pin, rank) is not None):
            return False
        if any(stream.route is not None and stream.route.manual
               for port in unit.ports.values()
               if (stream := port.stream) is not None):
            return False
    return True


def _legal(fs: Flowsheet, group: tuple[Unit, ...], delta: float, axis: str,
           boxes: dict[Unit, tuple[float, float, float, float]]) -> bool:
    """Reject pin, grid-order, manual-route, and occupied-box conflicts.

    Parameters
    ----------
    fs : Flowsheet
        Current settled drawing.
    group : tuple[Unit, ...]
        Connected process units that would move together.
    delta : float
        Proposed shift on the selected axis.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, tuple[float, float, float, float]]
        Current process reservations, including control clearance.

    Returns
    -------
    bool
        Whether inexpensive preflight checks permit an exact trial.
    """
    moving = set(group)
    maximum = _MAX_COLUMN_SHIFT if axis == "x" else _MAX_SHIFT
    if not group or not _movable(group, axis) or not _MIN_SHIFT <= abs(delta) <= maximum:
        return False
    for unit in group:
        lower, upper = grid_limits(unit, axis, boxes, moving=moving)
        if not lower <= getattr(_placed(unit), axis) + delta <= upper:
            return False
    offset = (delta, 0.0) if axis == "x" else (0.0, delta)
    shifted = {unit: (box[0] + offset[0], box[1] + offset[1],
                      box[2] + offset[0], box[3] + offset[1])
               for unit, box in boxes.items() if unit in moving}
    for unit, box in shifted.items():
        if any(_overlap(box, other_box) for other, other_box in boxes.items()
               if other not in moving):
            return False
    placed = {unit: replace(_placed(unit), **{axis: getattr(_placed(unit), axis) + delta})
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


def _estimate(moving: set[Unit], delta: float, axis: str,
              touching: dict[Unit, list[int]], streams: list[Stream]) -> float:
    """Estimate the affected route length and directed-bend reduction.

    Parameters
    ----------
    moving : set[Unit]
        Process group proposed for translation.
    delta : float
        Proposed shift on the selected axis.
    axis : str
        ``"x"`` or ``"y"``.
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
                frame = replace(frame, **{axis: getattr(frame, axis) + delta})
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


def _face_candidates(fs: Flowsheet, limit: int) -> tuple[Candidate, ...]:
    """Propose alternative declared faces for costly automatic routes.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing with final routes and selected faces.
    limit : int
        Maximum face proposals to return.

    Returns
    -------
    tuple[Candidate, ...]
        Face choices ordered by optimistic routed-cost reduction. No
        proposed face changes author intent or a manual-route endpoint.
    """
    if limit <= 0:
        return ()
    global_index = {unit: index for index, unit in enumerate(fs.units)}
    proposals: dict[tuple[int, str, str], Candidate] = {}
    for stream_index, stream in enumerate(fs.streams):
        route = stream.route
        if route is None or route.manual or len(route.waypoints) < 2:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None or source.frame is None or dest.frame is None:
            continue
        current = (resolve_port(source, _placed(source), stream.source.name),
                   resolve_port(dest, _placed(dest), stream.dest.name))
        actual = path_length(route.waypoints) + 25.0 * real_bends(route.waypoints)
        for side, (owner, port) in enumerate(((source, stream.source), (dest, stream.dest))):
            if any(connected.route is not None and connected.route.manual
                   for item in owner.ports.values()
                   if (connected := item.stream) is not None):
                continue
            frame = _placed(owner)
            live = [name for name, item in owner.ports.items()
                    if item.stream is not None]
            earlier = set(live[:live.index(port.name)])
            reserved = [name for name in live
                        if name in earlier or not eligible_faces(fs, owner, name)]
            reserved_points = {
                tuple(round(value, 3) for value in resolve_port(owner, frame, name).point)
                for name in reserved
            }
            for face in eligible_faces(fs, owner, port.name):
                if face == current[side].face:
                    continue
                chosen = replace(frame, port_faces={**frame.port_faces, port.name: face})
                alternative = resolve_port(owner, chosen, port.name)
                point = tuple(round(value, 3) for value in alternative.point)
                if point in reserved_points:
                    continue
                endpoints = (alternative, current[1]) if side == 0 else (current[0], alternative)
                first, second = endpoints
                bends = min_bends(first.anchor, first.face, second.anchor, second.face)
                lower = (abs(first.anchor[0] - second.anchor[0])
                         + abs(first.anchor[1] - second.anchor[1])
                         + 25.0 * (bends or 0))
                gain = actual - lower
                if gain <= 0:
                    continue
                key = global_index[owner], port.name, face
                candidate = Candidate((), 0.0, stream_index, round(gain, 6), (key,))
                if key not in proposals or candidate.estimated_gain > proposals[key].estimated_gain:
                    proposals[key] = candidate
    return tuple(sorted(proposals.values(),
                        key=lambda item: (-item.estimated_gain, item.stream,
                                          item.face_choices))[:limit])


def generate(fs: Flowsheet, structure: Structure | None = None,
             limit: int = MAX_CANDIDATES) -> tuple[Candidate, ...]:
    """Propose a stable, bounded list of local and automatic-face trials.

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
        Existing vertical and face proposals retain priority; horizontal
        proposals fill remaining slots by cheap cost reduction and stable
        indices.
        Call ``candidate.evaluate(fs)`` for an isolated completed trial.

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
    proposals: dict[tuple[tuple[int, ...], str, float], Candidate] = {}
    opportunities: dict[tuple[tuple[int, ...], str, float],
                        tuple[float, int, int, str, float, tuple[Unit, ...]]] = {}
    streams = process_streams(fs)
    global_stream_index = {id(stream): index for index, stream in enumerate(fs.streams)}
    touching: dict[Unit, list[int]] = {}
    for index, stream in enumerate(streams):
        for port in (stream.source, stream.dest):
            if port.owner is not None:
                touching.setdefault(port.owner, []).append(index)
    for stream in streams:
        if stream.is_recycle:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None:
            continue
        first = resolve_port(source, _placed(source), stream.source.name)
        second = resolve_port(dest, _placed(dest), stream.dest.name)
        if first.face in ("E", "W") and second.face in ("E", "W"):
            if _placed(source).col == _placed(dest).col:
                continue
            axis = "y"
            coordinate = 1
        elif first.face in ("N", "S") and second.face in ("N", "S"):
            if _placed(source).row == _placed(dest).row:
                continue
            axis = "x"
            coordinate = 0
        else:
            continue
        for target, delta in ((dest, first.anchor[coordinate] - second.anchor[coordinate]),
                              (source, second.anchor[coordinate] - first.anchor[coordinate])):
            group = groups.get(target)
            if group is None or source in group and dest in group:
                continue
            maximum = _MAX_COLUMN_SHIFT if axis == "x" else _MAX_SHIFT
            if not _MIN_SHIFT <= abs(delta) <= maximum or not _movable(group, axis):
                continue
            indices = tuple(sorted(global_index[unit] for unit in group))
            key = indices, axis, round(delta, 6)
            choice = (-abs(delta) / maximum, global_stream_index[id(stream)],
                      global_index[target], axis, delta, group)
            if key not in opportunities or choice[:3] < opportunities[key][:3]:
                opportunities[key] = choice
    vertical = sorted(value for value in opportunities.values() if value[3] == "y")
    horizontal = sorted(value for value in opportunities.values() if value[3] == "x")
    preflights = vertical[:MAX_PREFLIGHTS]
    preflights += horizontal[:MAX_PREFLIGHTS - len(preflights)]
    for _, stream_index, _, axis, delta, group in preflights:
        if not _legal(fs, group, delta, axis, boxes):
            continue
        gain = _estimate(set(group), delta, axis, touching, streams)
        if gain <= 0:
            continue
        indices = tuple(sorted(global_index[unit] for unit in group))
        key = indices, axis, round(delta, 6)
        candidate = Candidate(indices, round(delta, 6) if axis == "y" else 0.0,
                              stream_index, round(gain, 6),
                              dx=round(delta, 6) if axis == "x" else 0.0)
        if key not in proposals or candidate.estimated_gain > proposals[key].estimated_gain:
            proposals[key] = candidate
    vertical_moves = sorted((item for item in proposals.values() if item.dy),
                            key=lambda item: (-item.estimated_gain, item.stream,
                                              item.units, item.dy))[:MAX_CANDIDATES]
    horizontal_moves = sorted((item for item in proposals.values() if item.dx),
                              key=lambda item: (-item.estimated_gain, item.stream,
                                                item.units, item.dx))
    faces = _face_candidates(fs, MAX_CANDIDATES)
    established = sorted((*vertical_moves, *faces),
                         key=lambda item: (-item.estimated_gain, item.stream,
                                           item.units, item.dy, item.face_choices))
    return tuple((*established, *horizontal_moves)[:min(limit, MAX_CANDIDATES)])
