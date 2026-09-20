"""Fit relative pixel positions to exact per-axis placement pins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.layout import claims, solver
from pandid.layout.stages import process_streams, slot
from pandid.portgeom import port_offset, resolve_port, unit_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def refine(fs: Flowsheet, units: list[Unit],
           reference: dict[Unit, tuple[float, float]]) -> dict[str, list[Unit]]:
    """Resolve free coordinates against pinned corners and nominal grid spacing."""
    at = {u: i for i, u in enumerate(units)}
    pulls: dict[str, list[solver.Pull]] = {"x": [], "y": []}
    for stream in process_streams(fs):
        src, dst = stream.source.owner, stream.dest.owner
        assert src is not None and dst is not None
        if src is dst:
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



def clear_pins(units: list[Unit], moved: dict[str, list[Unit]], gap: float) -> None:
    """Clear fixed pins without moving refined units into another body."""
    boxes = {u: unit_box(u, slot(u)) for u in units}
    for axis, index in (("x", 0), ("y", 1)):
        fixed = [u for u in units
                 if u.pin_ is not None and getattr(u.pin_, axis) is not None]
        for u in moved[axis]:
            s = slot(u)
            value = getattr(s, axis)
            box = boxes[u]
            low, high = box[index] - value, box[index + 2] - value

            def interval(other: Unit) -> tuple[float, float] | None:
                obstacle = boxes[other]
                cross = 1 - index
                if (box[cross + 2] <= obstacle[cross]
                        or box[cross] >= obstacle[cross + 2]):
                    return None
                return (obstacle[index] - high - gap,
                        obstacle[index + 2] - low + gap)

            if not any(bounds[0] < value < bounds[1] for other in fixed
                       if (bounds := interval(other)) is not None):
                continue
            # The move clears a pin; every other body bounds the available space.
            intervals = [bounds for other in units if other is not u
                         if (bounds := interval(other)) is not None]
            merged: list[tuple[float, float]] = []
            for start, end in sorted(intervals):
                if merged and start < merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            for start, end in merged:
                if start < value < end:
                    setattr(s, axis, min((start, end), key=lambda v: abs(v - value)))
                    boxes[u] = unit_box(u, s)
                    break
