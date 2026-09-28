"""Place opted-in inline devices on clear straight material corridors."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.backbone import infer_backbone
from pandid.layout.stages import process_streams, process_units, slot
from pandid.portgeom import port_point, resolve_size, unit_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def _clear(candidate: Frame, unit: Unit, obstacles: list[Unit]) -> bool:
    """Check that a candidate body leaves room around other units.

    Parameters
    ----------
    candidate : Frame
        Proposed device placement.
    unit : Unit
        Device being moved.
    obstacles : list[Unit]
        Units already assigned to the drawing.

    Returns
    -------
    bool
        Whether the proposed body is free of nearby unit bodies.
    """
    left, top, right, bottom = unit_box(unit, candidate)
    for other in obstacles:
        if other.frame is None:
            continue
        o_left, o_top, o_right, o_bottom = unit_box(other, other.frame)
        if right + 8 > o_left and o_right + 8 > left and bottom + 8 > o_top and o_bottom + 8 > top:
            return False
    return True


def _candidate(unit: Unit, point: tuple[float, float], orientation: int) -> Frame:
    """Center a device at a point using its resolved orientation.

    Parameters
    ----------
    unit : Unit
        Inline device to position.
    point : tuple[float, float]
        Preferred center of the device.
    orientation : int
        Clockwise quarter-turn angle.

    Returns
    -------
    Frame
        Candidate frame with existing grid rank and mirror state.
    """
    original = unit.frame
    assert original is not None
    probe = replace(original, orientation=orientation)
    width, height = resolve_size(unit, probe)
    return replace(
        probe, x=point[0] - width / 2, y=point[1] - height / 2,
        w=width, h=height, label_pos=None, port_faces={},
    )


def _on_corridor(
    unit: Unit, candidate: Frame, direction: tuple[int, int], ordinate: float,
) -> bool:
    """Require both nozzles to follow the straight host corridor.

    Parameters
    ----------
    unit : Unit
        Device being placed.
    candidate : Frame
        Proposed geometry.
    direction : tuple[int, int]
        Unit step of the material flow on the drawing.
    ordinate : float
        Fixed coordinate perpendicular to that flow.

    Returns
    -------
    bool
        Whether both ports align and face in material order.
    """
    inlet = port_point(unit, candidate, "inlet")
    outlet = port_point(unit, candidate, "outlet")
    axis = 0 if direction[0] else 1
    other = 1 - axis
    forward = direction[axis]
    return (abs(inlet[other] - ordinate) < 1.0
            and abs(outlet[other] - ordinate) < 1.0
            and (outlet[axis] - inlet[axis]) * forward > 0)


def place_inline(fs: Flowsheet) -> set[Unit]:
    """Resolve preferred inline positions within straight equipment runs.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose ordinary process frames have already been assigned.

    Returns
    -------
    set[Unit]
        Devices placed on their host runs.
    """
    if not any(stream._inline_at is not None for stream in fs.streams):
        return set()
    units = process_units(fs)
    streams = process_streams(fs)
    backbone = infer_backbone(fs)
    station_members = {unit for assembly in fs._station_assemblies
                       for unit in assembly.station.members}
    placed_units: set[Unit] = set()
    for run in backbone.runs:
        movable = [
            units[index] for index, at in zip(run.inline_units, run.inline_at)
            if at is not None and units[index] not in station_members and (
                units[index].pin_ is None
                or all(getattr(units[index].pin_, key) is None
                       for key in ("col", "row", "x", "y"))
            )
        ]
        if not movable:
            continue
        source = streams[run.streams[0]]
        final = streams[run.streams[-1]]
        source_unit, dest_unit = source.source.owner, final.dest.owner
        assert source_unit is not None and dest_unit is not None
        if source_unit.frame is None or dest_unit.frame is None:
            continue
        start = port_point(source_unit, source_unit.frame, source.source.name)
        end = port_point(dest_unit, dest_unit.frame, final.dest.name)
        horizontal = abs(start[1] - end[1]) < 1.0
        vertical = abs(start[0] - end[0]) < 1.0
        if not horizontal and not vertical:
            continue
        axis = 0 if horizontal else 1
        other = 1 - axis
        forward = 1 if end[axis] > start[axis] else -1
        if end[axis] == start[axis]:
            continue
        direction = (forward, 0) if horizontal else (0, forward)
        default_orientation = (0 if forward > 0 else 180) if horizontal else (
            90 if forward > 0 else 270
        )
        obstacles = [u for u in units if u not in movable]
        last_outlet = start[axis]
        for unit_index, stream_index, preferred in zip(
            run.inline_units, run.streams[:-1], run.inline_at
        ):
            unit = units[unit_index]
            if preferred is None or unit not in movable:
                if unit.frame is not None and _on_corridor(
                    unit, unit.frame, direction, start[other]
                ):
                    held_outlet = port_point(unit, unit.frame, "outlet")[axis]
                    if (held_outlet - last_outlet) * forward > 0:
                        last_outlet = held_outlet
                continue
            if unit.frame is None:
                continue
            pin = unit.pin_
            orientation = int(unit.frame.orientation) if pin is not None else default_orientation
            incoming = streams[stream_index]
            logical_root = incoming._logical_root or incoming
            logical_end = logical_root._logical_to
            scope_start, scope_end = start, end
            if logical_end is not None:
                root_owner, end_owner = logical_root.source.owner, logical_end.owner
                assert root_owner is not None and end_owner is not None
                if root_owner.frame is None or end_owner.frame is None:
                    obstacles.append(unit)
                    continue
                scope_start = port_point(root_owner, root_owner.frame,
                                         logical_root.source.name)
                scope_end = port_point(end_owner, end_owner.frame, logical_end.name)
            if (scope_end[axis] - scope_start[axis]) * forward <= 0:
                obstacles.append(unit)
                continue
            target = scope_start[axis] + float(preferred) * (
                scope_end[axis] - scope_start[axis]
            )
            local = (target - start[axis]) / (end[axis] - start[axis])
            choices = sorted({max(0.0, min(1.0, local)),
                              *(step / 100 for step in range(1, 100))},
                             key=lambda value: (abs(
                                 start[axis] + value * (end[axis] - start[axis]) - target
                             ), value))
            for fraction in choices:
                point = (start[0] + fraction * (end[0] - start[0]),
                         start[1] + fraction * (end[1] - start[1]))
                candidate = _candidate(unit, point, orientation)
                if not _on_corridor(unit, candidate, direction, start[other]):
                    continue
                inlet = port_point(unit, candidate, "inlet")
                outlet = port_point(unit, candidate, "outlet")
                if ((inlet[axis] - last_outlet) * forward < 8
                        or (inlet[axis] - scope_start[axis]) * forward < 8
                        or (scope_end[axis] - outlet[axis]) * forward < 8
                        or (end[axis] - outlet[axis]) * forward < 8
                        or not _clear(candidate, unit, obstacles)):
                    continue
                unit.frame = candidate
                placed = slot(unit)
                placed.x, placed.y = candidate.x, candidate.y
                placed.w, placed.h = candidate.w, candidate.h
                placed.orientation = candidate.orientation
                last_outlet = outlet[axis]
                placed_units.add(unit)
                break
            obstacles.append(unit)
    return placed_units
