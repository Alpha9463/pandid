"""Fit free pixel coordinates around units pinned in pixels.

When a sheet mixes pixel pins with free units, :func:`refine` solves each
pixel axis by least squares with the pinned coordinates fixed, keeping the
grid's spacing between connected units. :func:`clear_pins` then moves
free units off any box they overlap, respecting pinned grid order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.layout import claims, solver
from pandid.layout.halo import Pad
from pandid.layout.stages import process_streams, slot
from pandid.portgeom import port_offset, resolve_port, unit_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def refine(fs: Flowsheet, units: list[Unit],
           reference: dict[Unit, tuple[float, float]],
           links: list[tuple[Unit, Unit, float]] | None = None) -> dict[str, list[Unit]]:
    """Resolve free coordinates against pixel pins and nominal grid spacing.

    Each process stream pulls its ends toward their spacing on the nominal
    grid, weighted by the stream's claims. Facing north/south or east/west
    nozzles in one grid column or row are pulled into line instead. A
    component with no pin on an axis keeps its grid coordinates there.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with authored coordinate pins.
    units : list[Unit]
        Units included in the pixel solve.
    reference : dict[Unit, tuple[float, float]]
        Nominal grid coordinates for each unit.
    links : list[tuple[Unit, Unit, float]] or None
        Contracted host connections absent from physical streams.

    Returns
    -------
    dict[str, list[Unit]]
        Free units moved on each pixel axis.
    """
    at = {u: i for i, u in enumerate(units)}
    pulls: dict[str, list[solver.Pull]] = {"x": [], "y": []}
    for stream in process_streams(fs):
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src is dst or src not in at or dst not in at:
            continue
        weight = sum(c.confidence for c in claims.read([stream]))
        source, dest = slot(src), slot(dst)
        offsets = (port_offset(src, stream.source.name, source),
                   port_offset(dst, stream.dest.name, dest))
        faces = (resolve_port(src, source, stream.source.name).face,
                 resolve_port(dst, dest, stream.dest.name).face)
        for axis, rank, directions, index in (("x", "col", ("N", "S"), 0),
                                              ("y", "row", ("E", "W"), 1)):
            step = reference[dst][index] - reference[src][index]
            if (not stream.is_recycle
                    and getattr(source, rank) == getattr(dest, rank)
                    and all(face in directions for face in faces)):
                step = offsets[0][index] - offsets[1][index]
            pulls[axis].append((at[src], at[dst], weight, step))

    for host_source, host_dest, weight in links or []:
        for axis, index in (("x", 0), ("y", 1)):
            step = reference[host_dest][index] - reference[host_source][index]
            pulls[axis].append((at[host_source], at[host_dest], weight, step))

    groups = solver.components(len(units), pulls["x"])
    moved: dict[str, list[Unit]] = {"x": [], "y": []}
    for axis in ("x", "y"):
        fixed = {at[u]: value for u in units
                 if u.pin_ is not None and (value := getattr(u.pin_, axis)) is not None}
        if not fixed:
            continue
        moving: list[int] = []
        for group in groups:
            if any(node in fixed for node in group):
                moving.extend(node for node in group if node not in fixed)
            else:
                # A component with no anchor on this axis retains its grid coordinates.
                fixed.update((node, getattr(slot(units[node]), axis)) for node in group)
        if not moving:
            continue
        fitted = solver.relax(len(units), pulls[axis], fixed)
        for node in moving:
            setattr(slot(units[node]), axis, round(fitted[node], solver.PLACES))
        moved[axis] = [units[node] for node in moving]
    return moved


Box = tuple[float, float, float, float]


def occupied_box(unit: Unit, pads: dict[Unit, Pad]) -> Box:
    """Return a unit's drawn box widened by its balloon reservation.

    Parameters
    ----------
    unit : Unit
        Unit with a resolved slot.
    pads : dict[Unit, Pad]
        Balloon reservations from :func:`pandid.layout.halo.balloon_pads`.

    Returns
    -------
    Box
        ``(left, top, right, bottom)``.
    """
    left, top, right, bottom = unit_box(unit, slot(unit))
    pad = pads.get(unit, Pad())
    return left - pad.west, top - pad.north, right + pad.east, bottom + pad.south


def grid_limits(unit: Unit, axis: str, boxes: dict[Unit, Box], gap: float = 0.0,
                moving: set[Unit] | None = None,
                origin: float | None = None) -> tuple[float, float]:
    """Return the range a coordinate may take without breaking pinned grid order.

    Applies only to a unit pinned by grid rank on this axis and not by
    pixel: it must stay after every unit with a lower pinned rank and
    before every unit with a higher one.

    Parameters
    ----------
    unit : Unit
        Unit to bound.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, Box]
        Occupied boxes.
    gap : float, default=0.0
        Required clearance.
    moving : set[Unit] or None, optional
        Units being moved together, ignored as bounds.
    origin : float or None, optional
        Coordinate ``boxes[unit]`` was measured at, if not the slot's.

    Returns
    -------
    tuple[float, float]
        Lower and upper bound, infinite where unconstrained.
    """
    lower, upper = float("-inf"), float("inf")
    rank = "col" if axis == "x" else "row"
    grid = getattr(unit.pin_, rank, None)
    if grid is None or getattr(unit.pin_, axis) is not None:
        return lower, upper
    index = 0 if axis == "x" else 1
    value = getattr(slot(unit), axis) if origin is None else origin
    low, high = boxes[unit][index] - value, boxes[unit][index + 2] - value
    for other, obstacle in boxes.items():
        other_grid = getattr(other.pin_, rank, None)
        if (other is unit or (moving is not None and other in moving)
                or other_grid is None or getattr(other.pin_, axis) is not None):
            continue
        if grid < other_grid:
            upper = min(upper, obstacle[index] - high - gap)
        elif grid > other_grid:
            lower = max(lower, obstacle[index + 2] - low + gap)
    return lower, upper


def _target(unit: Unit, axis: str, boxes: dict[Unit, Box], gap: float,
            limits: tuple[float, float] | None = None,
            preferred: float | None = None) -> float | None:
    """Return the nearest clear coordinate within pinned grid order.

    Parameters
    ----------
    unit : Unit
        Unit to move along ``axis``.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, Box]
        Occupied boxes.
    gap : float
        Required clearance.
    limits : tuple[float, float] or None, optional
        Bounds to use instead of :func:`grid_limits`.
    preferred : float or None, optional
        Coordinate to aim for instead of the current one.

    Returns
    -------
    float or None
        Clear coordinate nearest the aim, or ``None`` when the bounds leave
        no room.
    """
    index = 0 if axis == "x" else 1
    cross = 1 - index
    value = getattr(slot(unit), axis)
    aim: float = value if preferred is None else preferred
    box = boxes[unit]
    low, high = box[index] - value, box[index + 2] - value
    lower, upper = grid_limits(unit, axis, boxes, gap) if limits is None else limits
    intervals: list[tuple[float, float]] = []
    for other, obstacle in boxes.items():
        if other is unit:
            continue
        if box[cross + 2] > obstacle[cross] and box[cross] < obstacle[cross + 2]:
            intervals.append((obstacle[index] - high - gap,
                              obstacle[index + 2] - low + gap))
    if lower > upper:
        return None
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    nearest = min(max(aim, lower), upper)
    for start, end in merged:
        if start < nearest < end:
            choices = [point for point in (start, end) if lower <= point <= upper]
            return min(choices, key=lambda point: (abs(point - aim), point), default=None)
    return nearest


def _shifted(box: Box, axis: str, delta: float) -> Box:
    """Return a box moved along one axis.

    Parameters
    ----------
    box : Box
        Box to move.
    axis : str
        ``"x"`` or ``"y"``.
    delta : float
        Distance to move.

    Returns
    -------
    Box
        Moved box.
    """
    left, top, right, bottom = box
    return ((left + delta, top, right + delta, bottom) if axis == "x"
            else (left, top + delta, right, bottom + delta))


def _ordered(positions: dict[Unit, float], axis: str, boxes: dict[Unit, Box],
             gap: float) -> bool:
    """Return whether proposed coordinates keep pinned grid order.

    Parameters
    ----------
    positions : dict[Unit, float]
        Proposed coordinate per unit.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, Box]
        Occupied boxes at the proposed coordinates.
    gap : float
        Required clearance.

    Returns
    -------
    bool
        Whether every proposed coordinate is within its grid limits.
    """
    for unit, value in positions.items():
        lower, upper = grid_limits(unit, axis, boxes, gap, origin=value)
        if not lower <= value <= upper:
            return False
    return True


def _separate_pair(a: Unit, b: Unit, axis: str, boxes: dict[Unit, Box],
                   gap: float) -> dict[Unit, float]:
    """Try moving two overlapping units together to clear each other.

    Each unit in turn is tried at the boundaries of the free intervals on
    the axis, and the other is then moved to its nearest clear coordinate.

    Parameters
    ----------
    a, b : Unit
        Overlapping units.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, Box]
        Occupied boxes.
    gap : float
        Required clearance.

    Returns
    -------
    dict[Unit, float]
        Cheapest valid coordinates for both units, or an empty dict when
        none keeps grid order or either unit is pinned on ``axis``.
    """
    if any(u.pin_ is not None and getattr(u.pin_, axis) is not None for u in (a, b)):
        return {}
    index = 0 if axis == "x" else 1
    cross = 1 - index
    choices: list[tuple[float, float, float, dict[Unit, float]]] = []
    for first, second in ((a, b), (b, a)):
        value = getattr(slot(first), axis)
        box = boxes[first]
        low, high = box[index] - value, box[index + 2] - value
        space = {u: bounds for u, bounds in boxes.items() if u is not second}
        limits = grid_limits(first, axis, boxes, gap)
        hints = {value, *limits}
        for other, obstacle in space.items():
            if (other is not first and box[cross + 2] > obstacle[cross]
                    and box[cross] < obstacle[cross + 2]):
                hints.update((obstacle[index] - high - gap, obstacle[index + 2] - low + gap))
        targets = {_target(first, axis, space, gap, limits, hint)
                   for hint in hints if float("-inf") < hint < float("inf")}
        for target in sorted(point for point in targets if point is not None):
            trial = boxes.copy()
            trial[first] = _shifted(box, axis, target - value)
            other_target = _target(second, axis, trial, gap)
            if other_target is None:
                continue
            other_value = getattr(slot(second), axis)
            trial[second] = _shifted(boxes[second], axis, other_target - other_value)
            positions = {first: target, second: other_target}
            if _ordered(positions, axis, trial, gap):
                cost = abs(target - value) + abs(other_target - other_value)
                choices.append((cost, positions[a], positions[b], positions))
    return min(choices, key=lambda item: item[:3])[3] if choices else {}


def _cascade(unit: Unit, axis: str, boxes: dict[Unit, Box], gap: float,
             direction: int) -> dict[Unit, float]:
    """Make room by moving a unit and its later grid ranks in one direction.

    Parameters
    ----------
    unit : Unit
        Unit pinned by grid rank on this axis.
    axis : str
        ``"x"`` or ``"y"``.
    boxes : dict[Unit, Box]
        Occupied boxes.
    gap : float
        Required clearance.
    direction : int
        ``1`` to push toward higher ranks, ``-1`` toward lower.

    Returns
    -------
    dict[Unit, float]
        New coordinates for the units that moved, or an empty dict when no
        valid cascade exists.
    """
    rank = "col" if axis == "x" else "row"
    grid = getattr(unit.pin_, rank, None)
    if grid is None:
        return {}
    peers = [other for other in boxes if other.pin_ is not None
             and getattr(other.pin_, axis) is None
             and (value := getattr(other.pin_, rank)) is not None
             and (value - grid) * direction > 0]
    peers.sort(key=lambda other: direction * getattr(other.pin_, rank))
    trial = boxes.copy()
    positions: dict[Unit, float] = {}
    for other in [unit, *peers]:
        value = getattr(slot(other), axis)
        lower, upper = grid_limits(other, axis, trial, gap)
        limits = ((max(value, lower), float("inf")) if direction > 0
                  else (float("-inf"), min(value, upper)))
        if other is not unit and limits[0] <= value <= limits[1]:
            continue
        target = _target(other, axis, trial, gap, limits)
        if target is None:
            return {}
        trial[other] = _shifted(trial[other], axis, target - value)
        positions[other] = target
    return positions if _ordered(positions, axis, trial, gap) else {}


def clear_pins(units: list[Unit], moved: dict[str, list[Unit]], gap: float,
               pads: dict[Unit, Pad]) -> None:
    """Move free units off overlaps without creating new ones.

    First, units :func:`refine` moved are taken off pixel-pinned boxes.
    Then any remaining overlapping pair is cleared by the smallest move on
    a free axis, a joint move (:func:`_separate_pair`) or a cascade along
    pinned grid ranks (:func:`_cascade`). Each accepted move leaves the
    moved unit clear of every box, so the loop ends.

    Parameters
    ----------
    units : list[Unit]
        Units in the pixel solve.
    moved : dict[str, list[Unit]]
        Units :func:`refine` moved on each axis.
    gap : float
        Required clearance.
    pads : dict[Unit, Pad]
        Balloon reservations.
    """
    boxes = {u: occupied_box(u, pads) for u in units}
    for axis, index in (("x", 0), ("y", 1)):
        fixed = [u for u in units
                 if u.pin_ is not None and getattr(u.pin_, axis) is not None]
        cross = 1 - index
        for u in moved[axis]:
            box = boxes[u]
            if not any(box[cross + 2] > boxes[v][cross]
                       and box[cross] < boxes[v][cross + 2]
                       and box[index + 2] + gap > boxes[v][index]
                       and box[index] - gap < boxes[v][index + 2] for v in fixed):
                continue
            target = _target(u, axis, boxes, gap)
            if target is not None:
                setattr(slot(u), axis, target)
                boxes[u] = occupied_box(u, pads)

    # Each accepted move clears every other box, so a cleared unit stays clear.
    for _ in units:
        changed = False
        for i, unit in enumerate(units):
            box = boxes[unit]
            for other in units[i + 1:]:
                obstacle = boxes[other]
                if not (box[2] > obstacle[0] and box[0] < obstacle[2]
                        and box[3] > obstacle[1] and box[1] < obstacle[3]):
                    continue
                choices: list[tuple[float, int, int, float]] = []
                for order, candidate in enumerate((unit, other)):
                    for index, axis in enumerate(("x", "y")):
                        if candidate.pin_ is not None and getattr(candidate.pin_, axis) is not None:
                            continue
                        target = _target(candidate, axis, boxes, gap)
                        if target is not None:
                            distance = abs(target - getattr(slot(candidate), axis))
                            choices.append((distance, order, index, target))
                if choices:
                    _, order, index, target = min(choices)
                    positions = {(unit, other)[order]: target}
                else:
                    cascades: list[tuple[float, int, int, int, dict[Unit, float]]] = []
                    for order, candidate in enumerate((unit, other)):
                        for index, axis in enumerate(("x", "y")):
                            if candidate.pin_ is not None and getattr(candidate.pin_, axis) is not None:
                                continue
                            if order == 0:
                                trial = _separate_pair(unit, other, axis, boxes, gap)
                                if trial:
                                    cost = sum(abs(value - getattr(slot(u), axis))
                                               for u, value in trial.items())
                                    cascades.append((cost, order, index, 0, trial))
                            for direction in (-1, 1):
                                trial = _cascade(candidate, axis, boxes, gap, direction)
                                if trial:
                                    cost = sum(abs(value - getattr(slot(u), axis))
                                               for u, value in trial.items())
                                    cascades.append((cost, order, index, direction, trial))
                    if not cascades:
                        continue
                    _, _, index, _, positions = min(cascades, key=lambda item: item[:4])
                for candidate, target in positions.items():
                    setattr(slot(candidate), ("x", "y")[index], target)
                    boxes[candidate] = occupied_box(candidate, pads)
                changed = True
                break
            if changed:
                break
        if not changed:
            break
