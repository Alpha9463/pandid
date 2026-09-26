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
from pandid.layout.conflicts import Conflict, analyze_conflicts
from pandid.layout.coordinates import COL_GAP, ROW_GAP
from pandid.layout.faces import eligible_faces
from pandid.layout.halo import Pad, balloon_pads
from pandid.layout.pixel import grid_limits
from pandid.layout.stages import process_streams, process_units
from pandid.layout.structure import Structure, infer
from pandid.portgeom import pin_intent, resolve_port, unit_box
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
_TRIGGER_ORDER = {"unit-overlap": 0, "blocked-exit": 1,
                  "route-crosses-unit": 2, "fallback": 3, "crossing": 4}
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


@dataclass(frozen=True)
class Translation:
    """Move one safe unit group by a shared displacement.

    Attributes
    ----------
    units : tuple[int, ...]
        Global unit indices in flowsheet order.
    dx, dy : float
        Horizontal and vertical movement in drawing pixels.
    """

    units: tuple[int, ...]
    dx: float = 0.0
    dy: float = 0.0


@dataclass(frozen=True)
class Move:
    """A geometry-derived proposal for an isolated route trial.

    Attributes
    ----------
    translations : tuple[Translation, ...]
        One or two disjoint safe group movements.
    trigger : Conflict
        Final-drawing conflict or costly route that led to the proposal.
    estimate : float
        Cheap ranking estimate; final routing decides acceptance.
    """

    translations: tuple[Translation, ...]
    trigger: Conflict
    estimate: float

    def apply(self, frames: list[Frame | None]) -> None:
        """Apply the proposed translation to detached frames.

        Parameters
        ----------
        frames : list[Frame or None]
            Index-aligned frames owned by an isolated trial.

        Returns
        -------
        None
            Only the listed frame coordinates are changed.

        Raises
        ------
        ValueError
            If a listed unit has no frame.
        """
        for translation in self.translations:
            for index in translation.units:
                frame = frames[index]
                if frame is None:
                    raise ValueError("move unit has no frame")
                frame.x += translation.dx
                frame.y += translation.dy


def _move_groups(fs: Flowsheet) -> dict[int, tuple[int, ...]]:
    """Map each movable process unit to its safe connected group.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out process drawing.

    Returns
    -------
    dict[int, tuple[int, ...]]
        Global unit indices grouped by stacks and closed branch arms.
    """
    units = process_units(fs)
    global_index = {unit: index for index, unit in enumerate(fs.units)}
    return {
        global_index[unit]: tuple(global_index[member] for member in group)
        for unit, group in _groups(fs, infer(fs), units).items()
    }


def _move_boxes(fs: Flowsheet, move: Move,
                pads: dict[Unit, Pad]) -> dict[int, tuple[float, float, float, float]]:
    """Find process reservations after a proposed detached translation.

    Parameters
    ----------
    fs : Flowsheet
        Current completed drawing.
    move : Move
        Translation proposal.
    pads : dict[Unit, Pad]
        Existing control clearance by process unit.

    Returns
    -------
    dict[int, tuple[float, float, float, float]]
        Proposed padded boxes keyed by global unit index.
    """
    shifts = {index: (part.dx, part.dy) for part in move.translations for index in part.units}
    boxes = {}
    for index, unit in enumerate(fs.units):
        if unit.frame is None or (unit.kind == "instrument"
                                  and vars(unit).get("host") is not None):
            continue
        dx, dy = shifts.get(index, (0.0, 0.0))
        frame = replace(unit.frame, x=unit.frame.x + dx, y=unit.frame.y + dy)
        boxes[index] = _box(unit, frame, pads.get(unit, Pad()))
    return boxes


def _escape_blockers(fs: Flowsheet, frames: dict[int, Frame]) -> set[tuple[int, int, int, str]]:
    """Name obstacles inside the required outward nozzle leads.

    Parameters
    ----------
    fs : Flowsheet
        Drawing whose automatic streams need clear exits.
    frames : dict[int, Frame]
        Process placements keyed by global unit index.

    Returns
    -------
    set[tuple[int, int, int, str]]
        Stream, endpoint owner, blocker, and endpoint port identities.
    """
    index_by_id = {id(unit): index for index, unit in enumerate(fs.units)}
    boxes = {index: unit_box(fs.units[index], frame) for index, frame in frames.items()}
    hosts = {index: vars(fs.units[index]).get("host") for index in boxes}
    rects = [Rect(box[0], box[2], box[1], box[3]) for box in boxes.values()]
    normals = {"N": (0.0, -1.0), "S": (0.0, 1.0),
               "E": (1.0, 0.0), "W": (-1.0, 0.0)}
    blocked = set()
    for stream_index, stream in enumerate(fs.streams):
        route = stream.route
        if route is None or route.manual:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        source_index, dest_index = index_by_id[id(source)], index_by_id[id(dest)]
        if source_index not in frames or dest_index not in frames:
            continue
        ends = ((source_index, stream.source.name), (dest_index, stream.dest.name))
        resolved = [resolve_port(fs.units[index], frames[index], port) for index, port in ends]
        projections = []
        for (index, _), port in zip(ends, resolved):
            normal = normals[port.face]
            distance = escape_distance(fs.units[index].kind, frames[index].label_pos, port.face)
            projections.append((port.anchor[0] + distance * normal[0],
                                port.anchor[1] + distance * normal[1]))
        shared = share_escape_room(resolved[0].anchor, resolved[0].face, projections[0],
                                   resolved[1].anchor, resolved[1].face, projections[1],
                                   rects)
        for (owner_index, port_name), port, projection in zip(ends, resolved, shared):
            for blocker_index, box in boxes.items():
                if blocker_index in (source_index, dest_index):
                    continue
                if hosts[blocker_index] is stream:
                    continue
                if _segment_hits_box(port.anchor, projection, box):
                    blocked.add((stream_index, owner_index, blocker_index, port_name))
    return blocked


def _manual_endpoint_follows_move(fs: Flowsheet, moved: set[int]) -> bool:
    """Find a hand-routed endpoint attached to translated geometry.

    Parameters
    ----------
    fs : Flowsheet
        Drawing whose manual streams must retain their endpoints.
    moved : set[int]
        Global indices of units proposed for movement.

    Returns
    -------
    bool
        Whether an attached manual endpoint follows a moved unit or
        an affected host stream.
    """
    from pandid.streams import Stream

    moved_ids = {id(fs.units[index]) for index in moved}
    for stream in fs.streams:
        if stream.route is None or not stream.route.manual:
            continue
        for port in (stream.source, stream.dest):
            host = vars(port.owner).get("host")
            seen: set[int] = set()
            while host is not None and id(host) not in seen:
                seen.add(id(host))
                if id(host) in moved_ids:
                    return True
                if isinstance(host, Stream):
                    if (id(host.source.owner) in moved_ids
                            or id(host.dest.owner) in moved_ids):
                        return True
                    break
                host = vars(host).get("host")
    return False


def _move_preflight(fs: Flowsheet, move: Move, groups: dict[int, tuple[int, ...]],
                    pads: dict[Unit, Pad]) -> bool:
    """Reject translations that violate pins, bodies, or authored lines.

    Parameters
    ----------
    fs : Flowsheet
        Current completed drawing.
    move : Move
        Proposed one- or two-group translation.
    groups : dict[int, tuple[int, ...]]
        Safe groups keyed by global process-unit index.
    pads : dict[Unit, Pad]
        Control clearance by process unit.

    Returns
    -------
    bool
        Whether the proposal may proceed to an exact detached route.
    """
    moved: set[int] = set()
    if not move.translations or len(move.translations) > 2:
        return False
    for part in move.translations:
        if not part.units or not (_MIN_SHIFT <= max(abs(part.dx), abs(part.dy))):
            return False
        if abs(part.dx) > _MAX_COLUMN_SHIFT or abs(part.dy) > _MAX_SHIFT:
            return False
        if part.units != groups.get(part.units[0]) or moved.intersection(part.units):
            return False
        moved.update(part.units)
        for index in part.units:
            unit = fs.units[index]
            pinned = pin_intent(unit)
            pin = unit.pin_
            if part.dx and ("x" in pinned or (pin is not None and pin.col is not None)):
                return False
            if part.dy and ("y" in pinned or (pin is not None and pin.row is not None)):
                return False
            if any(port.stream is not None and port.stream.route is not None
                   and port.stream.route.manual for port in unit.ports.values()):
                return False
    if _manual_endpoint_follows_move(fs, moved):
        return False
    boxes = _move_boxes(fs, move, pads)
    for index in moved:
        if any(_overlap(boxes[index], box) for peer, box in boxes.items() if peer != index
               and peer not in moved):
            return False
    members = sorted(moved)
    for position, index in enumerate(members):
        if any(_overlap(boxes[index], boxes[peer]) for peer in members[position + 1:]):
            return False
    shifts = {index: (part.dx, part.dy)
              for part in move.translations for index in part.units}
    proposed_frames = {}
    current_frames = {}
    for index, unit in enumerate(fs.units):
        if unit.frame is None:
            continue
        current_frames[index] = unit.frame
        dx, dy = shifts.get(index, (0.0, 0.0))
        proposed_frames[index] = replace(unit.frame, x=unit.frame.x + dx,
                                         y=unit.frame.y + dy)
    if not _escape_blockers(fs, proposed_frames) <= _escape_blockers(fs, current_frames):
        return False
    current_boxes = {unit: _box(unit, _placed(unit), pads.get(unit, Pad()))
                     for unit in process_units(fs)}
    moved_units = {fs.units[index] for index in moved}
    for part in move.translations:
        for index in part.units:
            unit = fs.units[index]
            for axis, delta in (("x", part.dx), ("y", part.dy)):
                if not delta:
                    continue
                lower, upper = grid_limits(unit, axis, current_boxes, moving=moved_units)
                if not lower <= getattr(_placed(unit), axis) + delta <= upper:
                    return False
    for stream in fs.streams:
        route = stream.route
        if route is None or not route.manual:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source.frame is None or dest.frame is None:
            continue
        points = [resolve_port(source, source.frame, stream.source.name).point,
                  *route.waypoints,
                  resolve_port(dest, dest.frame, stream.dest.name).point]
        for a, b in zip(points, points[1:]):
            if any(_segment_hits_box(a, b, unit_box(fs.units[index], proposed_frames[index]))
                   for index in moved):
                return False
    return True


def _move_key(move: Move) -> tuple:
    """Provide a stable value key for proposal deduplication.

    Parameters
    ----------
    move : Move
        Proposal to identify.

    Returns
    -------
    tuple
        Translation values independent of object identities.
    """
    return tuple((part.units, round(part.dx, 6), round(part.dy, 6))
                 for part in move.translations)


def _offer_move(fs: Flowsheet, proposals: dict[tuple, Move], groups: dict[int, tuple[int, ...]],
                pads: dict[Unit, Pad], target: int, dx: float, dy: float,
                trigger: Conflict, estimate: float) -> None:
    """Add one legal group translation to the bounded proposal pool.

    Parameters
    ----------
    fs : Flowsheet
        Current completed drawing.
    proposals : dict[tuple, Move]
        Deduplicated proposals collected so far.
    groups : dict[int, tuple[int, ...]]
        Safe groups keyed by global process-unit index.
    pads : dict[Unit, Pad]
        Control clearance by process unit.
    target : int
        Global index of one desired member.
    dx, dy : float
        Proposed displacement.
    trigger : Conflict
        Conflict or costly route behind the move.
    estimate : float
        Cheap priority estimate.

    Returns
    -------
    None
        Accepted preflight proposals are stored in ``proposals``.
    """
    group = groups.get(target)
    if group is None:
        return
    part = Translation(group, round(dx, 6), round(dy, 6))
    move = Move((part,), trigger, round(estimate, 6))
    if not _move_preflight(fs, move, groups, pads):
        return
    key = _move_key(move)
    if key not in proposals or move.estimate > proposals[key].estimate:
        proposals[key] = move


def _offer_alignment(fs: Flowsheet, stream_index: int, trigger: Conflict,
                     proposals: dict[tuple, Move], groups: dict[int, tuple[int, ...]],
                     pads: dict[Unit, Pad], priority: float) -> None:
    """Offer endpoint group moves derived from two drawn nozzles.

    Parameters
    ----------
    fs : Flowsheet
        Current completed drawing.
    stream_index : int
        Global stream whose endpoints suggest the translation.
    trigger : Conflict
        Conflict or route cost behind the proposal.
    proposals : dict[tuple, Move]
        Deduplicated proposal pool.
    groups : dict[int, tuple[int, ...]]
        Safe groups keyed by global process-unit index.
    pads : dict[Unit, Pad]
        Control clearance by process unit.
    priority : float
        Cheap ranking value before exact routing.

    Returns
    -------
    None
        Legal endpoint moves are added to ``proposals``.
    """
    stream = fs.streams[stream_index]
    if stream.route is None or stream.route.manual:
        return
    source, dest = stream.source.owner, stream.dest.owner
    if source.frame is None or dest.frame is None:
        return
    first = resolve_port(source, source.frame, stream.source.name).anchor
    second = resolve_port(dest, dest.frame, stream.dest.name).anchor
    indices = {unit: index for index, unit in enumerate(fs.units)}
    for unit, peer, sign in ((source, dest, 1), (dest, source, -1)):
        index = indices[unit]
        group = groups.get(index)
        if group is not None and any(fs.units[item] is peer for item in group):
            continue
        for axis, delta in (("x", (second[0] - first[0]) * sign),
                            ("y", (second[1] - first[1]) * sign)):
            _offer_move(fs, proposals, groups, pads, index,
                        delta if axis == "x" else 0.0,
                        delta if axis == "y" else 0.0,
                        trigger, priority - abs(delta) * 0.01)


def _offer_obstruction_lanes(fs: Flowsheet, trigger: Conflict,
                             proposals: dict[tuple, Move], groups: dict[int, tuple[int, ...]],
                             pads: dict[Unit, Pad]) -> None:
    """Offer obstacle-boundary lanes to the blocker and stream ends.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing.
    trigger : Conflict
        Stream and blocker identity from final geometry.
    proposals : dict[tuple, Move]
        Deduplicated proposal pool.
    groups : dict[int, tuple[int, ...]]
        Safe groups keyed by global process-unit index.
    pads : dict[Unit, Pad]
        Control clearance by process unit.

    Returns
    -------
    None
        Legal blocker and endpoint moves are added to ``proposals``.
    """
    if not trigger.streams or not trigger.units:
        return
    blocker_index = trigger.units[-1]
    blocker = fs.units[blocker_index]
    stream = fs.streams[trigger.streams[0]]
    if blocker.frame is None or stream.route is None:
        return
    box = _box(blocker, blocker.frame, pads.get(blocker, Pad()))
    path = stream.route.waypoints
    index_by_id = {id(unit): index for index, unit in enumerate(fs.units)}
    endpoints = ((stream.source.owner, stream.source.name),
                 (stream.dest.owner, stream.dest.name))
    seen_axes: set[str] = set()
    for a, b, axis in waypoint_segments(path):
        if axis in seen_axes or not _segment_hits_box(a, b, box):
            continue
        seen_axes.add(axis)
        if axis == "h":
            for target in (a[1] - 10.0, a[1] + 10.0):
                shifted_top = target - (box[3] - box[1]) if target < a[1] else target
                _offer_move(fs, proposals, groups, pads, blocker_index, 0.0,
                            shifted_top - box[1], trigger, 1000.0)
            for owner, name in endpoints:
                if owner.frame is None:
                    continue
                anchor = resolve_port(owner, owner.frame, name).anchor
                for target in (box[1] - 10.0, box[3] + 10.0):
                    _offer_move(fs, proposals, groups, pads, index_by_id[id(owner)], 0.0,
                                target - anchor[1], trigger, 980.0)
        else:
            for target in (a[0] - 10.0, a[0] + 10.0):
                shifted_left = target - (box[2] - box[0]) if target < a[0] else target
                _offer_move(fs, proposals, groups, pads, blocker_index,
                            shifted_left - box[0], 0.0, trigger, 1000.0)
            for owner, name in endpoints:
                if owner.frame is None:
                    continue
                anchor = resolve_port(owner, owner.frame, name).anchor
                for target in (box[0] - 10.0, box[2] + 10.0):
                    _offer_move(fs, proposals, groups, pads, index_by_id[id(owner)],
                                target - anchor[0], 0.0, trigger, 980.0)
        if len(seen_axes) == 2:
            break


def _offer_overlap(fs: Flowsheet, trigger: Conflict,
                   proposals: dict[tuple, Move], groups: dict[int, tuple[int, ...]],
                   pads: dict[Unit, Pad]) -> None:
    """Offer four directions that separate two overlapping bodies.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing.
    trigger : Conflict
        Pair of overlapping global unit indices.
    proposals : dict[tuple, Move]
        Deduplicated proposal pool.
    groups : dict[int, tuple[int, ...]]
        Safe groups keyed by global process-unit index.
    pads : dict[Unit, Pad]
        Control clearance by process unit.

    Returns
    -------
    None
        Legal separation moves are added to ``proposals``.
    """
    if len(trigger.units) != 2:
        return
    first, second = trigger.units
    first_group, second_group = groups.get(first), groups.get(second)
    first_box = second_box = None
    for target, obstacle in ((first, second), (second, first)):
        unit, peer = fs.units[target], fs.units[obstacle]
        if unit.frame is None or peer.frame is None:
            continue
        box = _box(unit, unit.frame, pads.get(unit, Pad()))
        other = _box(peer, peer.frame, pads.get(peer, Pad()))
        if target == first:
            first_box, second_box = box, other
        for dx, dy in ((other[0] - box[2] - 10, 0.0),
                       (other[2] - box[0] + 10, 0.0),
                       (0.0, other[1] - box[3] - 10),
                       (0.0, other[3] - box[1] + 10)):
            _offer_move(fs, proposals, groups, pads, target, dx, dy, trigger, 1100.0)
    if (first_group is None or second_group is None or first_box is None
            or second_box is None or set(first_group) & set(second_group)):
        return
    separations = ((second_box[0] - first_box[2] - 10, 0.0),
                   (second_box[2] - first_box[0] + 10, 0.0),
                   (0.0, second_box[1] - first_box[3] - 10),
                   (0.0, second_box[3] - first_box[1] + 10))
    dx, dy = min(separations, key=lambda shift: (abs(shift[0]) + abs(shift[1]), shift))
    move = Move((Translation(first_group, dx / 2, dy / 2),
                 Translation(second_group, -dx / 2, -dy / 2)), trigger, 1050.0)
    if _move_preflight(fs, move, groups, pads):
        proposals[_move_key(move)] = move


def generate_moves(fs: Flowsheet, conflicts: tuple[Conflict, ...] | None = None,
                   limit: int = MAX_CANDIDATES) -> tuple[Move, ...]:
    """Generate bounded translations from final conflicts and route cost.

    Parameters
    ----------
    fs : Flowsheet
        Drawing with completed placement and routing.
    conflicts : tuple[Conflict, ...] or None, optional
        Final-geometry conflicts; measured here when omitted.
    limit : int, optional
        Maximum moves to return, capped by ``MAX_CANDIDATES``.

    Returns
    -------
    tuple[Move, ...]
        Stable, legal translations for detached exact-route trials.

    Raises
    ------
    ValueError
        If the drawing geometry is stale.
    """
    if fs._layout_stale or fs._route_stale:
        raise ValueError("move generation requires completed layout and routing")
    if limit <= 0:
        return ()
    findings = analyze_conflicts(fs) if conflicts is None else conflicts
    groups = _move_groups(fs)
    pads = balloon_pads(fs)
    proposals: dict[tuple, Move] = {}
    ordered_findings = sorted(findings,
                              key=lambda item: (_TRIGGER_ORDER.get(item.kind, 5), item))
    for trigger in ordered_findings[:MAX_PREFLIGHTS]:
        if trigger.kind == "unit-overlap":
            _offer_overlap(fs, trigger, proposals, groups, pads)
        elif trigger.kind in {"route-crosses-unit", "blocked-exit"}:
            _offer_obstruction_lanes(fs, trigger, proposals, groups, pads)
        for stream_index in trigger.streams:
            _offer_alignment(fs, stream_index, trigger, proposals, groups, pads, 900.0)
    costly: list[tuple[float, int]] = []
    for index, stream in enumerate(fs.streams):
        route = stream.route
        if route is None or route.manual or len(route.waypoints) < 2:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source.frame is None or dest.frame is None:
            continue
        first = resolve_port(source, source.frame, stream.source.name).anchor
        second = resolve_port(dest, dest.frame, stream.dest.name).anchor
        detour = path_length(route.waypoints) - (abs(first[0] - second[0])
                 + abs(first[1] - second[1]))
        if detour > 20 or real_bends(route.waypoints) > 2:
            costly.append((detour, index))
    for detour, index in sorted(costly, key=lambda item: (-item[0], item[1]))[:MAX_PREFLIGHTS]:
        trigger = Conflict("route-cost", streams=(index,))
        _offer_alignment(fs, index, trigger, proposals, groups, pads, detour + 100.0)
    ordered = sorted(proposals.values(),
                     key=lambda move: (-move.estimate, move.trigger,
                                       _move_key(move)))
    return tuple(ordered[:min(limit, MAX_CANDIDATES)])
