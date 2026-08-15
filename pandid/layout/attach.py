"""Instrument attachment: balloons anchored to a line or to equipment.

A P&ID bubble is not a node in the process flow; it is furniture hung
off a tap point. So an attached instrument is kept out of the Sugiyama
phases entirely (it has no rank and no row) and its frame comes from its
host instead: a point on the host stream's routed path, or the midpoint
of a face of the host unit's drawn box, pushed out along a branch
direction measured from the flow.

The tap point is resolved through :mod:`pandid.portgeom`, so a balloon
can never disagree with the nozzle geometry the router and renderer see.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Instrument, Unit

Point = tuple[float, float]

#: How many times :func:`place_attached` may move a balloon before
#: :meth:`pandid.flowsheet.Flowsheet.route` gives up and warns.
#:
#: Placing and routing chase each other: a balloon is placed on its
#: host's routed path, and the box it lands in is an obstacle the router
#: then avoids, which can bend that very path. Every sheet shipped here
#: settles in one or two passes and the worst converging sheet found by
#: search took four, but there is no quantity the recursion descends,
#: and sheets do exist that cycle between two or three arrangements
#: forever. The cap is what stops such a drawing from hanging, and the
#: warning it raises is what stops it from being silently whichever
#: arrangement the last pass happened to leave. Every pass ends on a
#: *route*, so running out of them still leaves each line drawn to the
#: balloon it belongs to.
MAX_PLACEMENT_PASSES = 6


def is_attached(unit: "Unit | None") -> bool:
    """True when a host positions this unit, not the ranker."""
    return unit is not None and getattr(unit, "host", None) is not None


def free_units(fs: "Flowsheet") -> list:
    """The units the ranker sees: everything not attached."""
    return [u for u in fs.units if not is_attached(u)]


def free_streams(fs: "Flowsheet") -> list:
    """Streams between two ranked units. A signal to an attached
    a flow-order constraint and must not push its peer down a column."""
    return [s for s in fs.streams
            if not is_attached(s.source.owner) and not is_attached(s.dest.owner)]


def _rotate_ccw(vx: float, vy: float, degrees: float) -> Point:
    """Rotate a direction anticlockwise as drawn, on a y-down canvas."""
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c + vy * s, -vx * s + vy * c)


def stream_path(stream: "Stream") -> list[Point]:
    """The stream's drawn polyline.

    Exactly what :meth:`SvgRenderer._draw_streams` puts on the sheet, so
    ``at=`` measures along the line the reader sees.
    """
    from pandid.portgeom import port_point

    src_u, dst_u = stream.source.owner, stream.dest.owner
    if src_u is None or dst_u is None or src_u.frame is None or dst_u.frame is None:
        return []
    mid = list(stream.route.waypoints) if (stream.route and stream.route.waypoints) else []
    return ([port_point(src_u, src_u.frame, stream.source.name)] + mid
            + [port_point(dst_u, dst_u.frame, stream.dest.name)])


def _along(points: list[Point], fraction: float) -> tuple[Point, Point]:
    """Point at ``fraction`` along a polyline, and the direction."""
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


def _anchor(inst: "Instrument") -> tuple[Point, Point] | None:
    """The tap point, and the direction the branch angle is off.

    On a stream that reference is the flow direction; on a unit face it
    is the face's tangent, chosen so a 90 degree branch again points
    straight out of the host.
    """
    from pandid.portgeom import face_point
    from pandid.streams import Stream

    host = inst.host
    # Not one of the guard clauses below: those answer "not placeable
    # yet", and a balloon with no host at all is one place_attached
    # never offers, since it only sweeps what is_attached() has already
    # said yes to.
    assert host is not None
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

    Returns True if any balloon moved, which is the signal that the
    lines running to it are stale and have to be routed again.

    The balloons no host could position are left on
    ``fs.unplaced_instruments``, since this sweep is the only thing that
    knows which they are. :func:`pandid.validate.validate` reads them
    back as ``instrument-unplaced``.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size

    moved = False
    # Balloons chain (an interlock hung under a controller hung off a
    # transmitter), so resolve a host before whatever hangs on it,
    # sweeping until nothing new can be placed.
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
            # Carry the placement transform across: an attached balloon
            # is positioned by its host rather than by the coordinate
            # pass, so without this a pin(mirrored=...) on one is
            # silently dropped, and mirroring is how a balloon puts its
            # signal port on the side the run actually comes from.
            pin = inst.pin_
            inst.frame = Frame(
                x=cx, y=cy, w=w, h=h, label_pos="center",
                orientation=pin.orientation if pin else 0.0,
                mirrored=pin.mirrored if pin else False,
                mirror_y=pin.mirror_y if pin else False,
                # Faces chosen in layout ride across the re-place.
                # Re-deciding here would move a nozzle the router has
                # already drawn to, and would make the answer depend on
                # the routed path, which is itself downstream of the
                # face.
                port_faces=dict(old.port_faces) if old is not None else {},
            )
            inst.tap = (tx, ty)
            pending.remove(inst)
            progressed = True
        if not progressed:
            # A sweep that placed nothing will place nothing next time
            # either: what is left hangs off a host that is itself
            # waiting, so the chain closes on itself. Stopping is right;
            # stopping *quietly* was the defect. Each survivor keeps
            # ``frame = None``, which no later phase fills in and the
            # renderer refuses outright, so the sheet has an instrument
            # on it that cannot be drawn.
            break
    # Set on every call, placed or not, so this is the last sweep's
    # answer rather than an accumulation across the route() fixed point.
    fs.unplaced_instruments = list(pending)
    return moved
