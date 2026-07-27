"""Instrument attachment: balloons anchored to a line or to equipment.

A P&ID bubble is not a node in the process flow — it is furniture hung off a
tap point. So an attached instrument is kept out of the Sugiyama phases
entirely (it has no rank and no row) and its frame comes from its host instead:
a point on the host stream's routed path, or the midpoint of a face of the host
unit's drawn box, pushed out along a branch direction measured from the flow.

The tap point is resolved through :mod:`pandid.portgeom`, so a balloon can never
disagree with the nozzle geometry the router and renderer see.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

Point = tuple[float, float]


def is_attached(unit: "Unit | None") -> bool:
    """True when this unit is positioned from a host rather than by the ranker."""
    return unit is not None and getattr(unit, "host", None) is not None


def free_units(fs: "Flowsheet") -> list:
    """The units the layout ranker sees — everything that is not attached."""
    return [u for u in fs.units if not is_attached(u)]


def free_streams(fs: "Flowsheet") -> list:
    """Streams between two ranked units; a signal to an attached balloon is not
    a flow-order constraint and must not push its peer down a column."""
    return [s for s in fs.streams
            if not is_attached(s.source.owner) and not is_attached(s.dest.owner)]


def _rotate_ccw(vx: float, vy: float, degrees: float) -> Point:
    """Rotate a direction counter-clockwise *as drawn*, i.e. on a y-down canvas."""
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c + vy * s, -vx * s + vy * c)


def stream_path(stream: "Stream") -> list[Point]:
    """The stream's drawn polyline: exactly what :meth:`SvgRenderer._draw_streams`
    puts on the sheet, so ``at=`` measures along the line the reader sees."""
    from pandid.portgeom import port_point

    src_u, dst_u = stream.source.owner, stream.dest.owner
    if src_u is None or dst_u is None or src_u.frame is None or dst_u.frame is None:
        return []
    mid = list(stream.route.waypoints) if (stream.route and stream.route.waypoints) else []
    return ([port_point(src_u, src_u.frame, stream.source.name)] + mid
            + [port_point(dst_u, dst_u.frame, stream.dest.name)])


def _along(points: list[Point], fraction: float) -> tuple[Point, Point]:
    """Point at ``fraction`` of a polyline's length, and the unit direction there."""
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths)
    if total <= 0.0:
        return points[0], (1.0, 0.0)
    target = max(0.0, min(1.0, fraction)) * total
    walked = 0.0
    for i, length in enumerate(lengths):
        if length <= 0.0:
            continue
        if walked + length >= target or i == len(lengths) - 1:
            a, b = points[i], points[i + 1]
            t = min(1.0, (target - walked) / length)
            return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                    ((b[0] - a[0]) / length, (b[1] - a[1]) / length))
        walked += length
    return points[-1], (1.0, 0.0)


def _anchor(inst: "Unit") -> tuple[Point, Point] | None:
    """The tap point and the reference direction the branch angle is measured from.

    On a stream that reference is the flow direction; on a unit face it is the
    face's tangent, chosen so a 90 degree branch again points straight out of
    the host.
    """
    from pandid.portgeom import face_point
    from pandid.streams import Stream

    host = inst.host
    if isinstance(host, Stream):
        points = stream_path(host)
        if len(points) < 2:
            return None
        return _along(points, float(inst.at if inst.at is not None else 0.5))
    if host.frame is None:
        return None
    (px, py), (nx, ny) = face_point(host, host.frame, str(inst.at or "E"))
    return (px, py), (-ny, nx)


def place_attached(fs: "Flowsheet") -> bool:
    """Resolve every attached instrument's frame from its host.

    Returns True if any balloon moved, which is the signal that the lines
    running to it are stale and have to be routed again.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size

    moved = False
    # Balloons chain (an interlock hung under a controller hung off a
    # transmitter), so resolve a host before whatever hangs on it, sweeping
    # until nothing new can be placed.
    pending = [u for u in fs.units if is_attached(u)]
    while pending:
        progressed = False
        for inst in list(pending):
            if inst.host in pending:
                continue
            anchor = _anchor(inst)
            if anchor is None:
                continue
            (tx, ty), (rx, ry) = anchor
            ux, uy = _rotate_ccw(rx, ry, inst.angle)
            w, h = resolve_size(inst)
            cx, cy = tx + ux * inst.offset - w / 2, ty + uy * inst.offset - h / 2
            old = inst.frame
            if old is None or abs(old.x - cx) > 0.01 or abs(old.y - cy) > 0.01:
                moved = True
            # Carry the placement transform across: an attached balloon is
            # positioned by its host rather than by the coordinate pass, so
            # without this a pin(mirrored=...) on one is silently dropped —
            # and mirroring is how a balloon puts its signal port on the side
            # the run actually comes from.
            pin = inst.pin_
            inst.frame = Frame(
                x=cx, y=cy, w=w, h=h, label_pos="center",
                orientation=pin.orientation if pin else 0.0,
                mirrored=pin.mirrored if pin else False,
                mirror_y=pin.mirror_y if pin else False,
                # Faces chosen in layout ride across the re-place. Re-deciding
                # here would move a nozzle the router has already drawn to, and
                # would make the answer depend on the routed path — which is
                # itself downstream of the face.
                port_faces=dict(old.port_faces) if old is not None else {},
            )
            inst.tap = (tx, ty)
            pending.remove(inst)
            progressed = True
        if not progressed:
            break  # host frame never resolved (e.g. a cycle of attachments)
    return moved
