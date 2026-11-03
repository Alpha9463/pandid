"""Place attached instrument balloons from their hosts.

A balloon hangs from a tap point on its host stream or unit face, at a
standoff distance and branch angle.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Instrument, Unit

Point = tuple[float, float]

#: Maximum placement and routing passes.
MAX_PLACEMENT_PASSES = 6

#: Outward step and step count for moving a colliding balloon.
STANDOFF_STEP = 22.0
STANDOFF_STEPS = 8

#: Largest swing either side of the branch angle, and its step, in
#: degrees.
SWEEP_LIMIT = 60.0
SWEEP_STEP = 15.0

#: Smallest angle, in degrees, between a swept branch and the host's
#: reference direction.
MIN_BRANCH = 20.0

#: Clearance a balloon keeps once a collision forces a new standoff.
RESOLVED_CLEARANCE = 6.0

#: Length of the strip a moved balloon keeps clear in front of a
#: connected nozzle.
ESCAPE_ROOM = 25.0

#: Overlap validation tolerates before it reports a collision.
TOUCHING = 1.0

Box = tuple[float, float, float, float]


def is_attached(unit: "Unit | None") -> bool:
    """Return whether a unit is positioned by a host."""
    return unit is not None and getattr(unit, "host", None) is not None


def _rotate_ccw(vx: float, vy: float, degrees: float) -> Point:
    """Rotate a direction anticlockwise on the y-down canvas."""
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c + vy * s, -vx * s + vy * c)


def stream_path(stream: "Stream") -> list[Point]:
    """Return the polyline a stream is drawn along, or ``[]``."""
    from pandid.portgeom import port_point

    src_u, dst_u = stream.source.owner, stream.dest.owner
    if src_u is None or dst_u is None or src_u.frame is None or dst_u.frame is None:
        return []
    mid = list(stream.route.waypoints) if (stream.route and stream.route.waypoints) else []
    return ([port_point(src_u, src_u.frame, stream.source.name)] + mid
            + [port_point(dst_u, dst_u.frame, stream.dest.name)])


def logical_stream_path(stream: "Stream") -> list[Point]:
    """Return the polyline of a logical run through its segments."""
    segments = stream._logical_segments or [stream]
    root = stream._logical_root or stream
    owner = root.source.owner
    fs = owner.flowsheet if owner is not None else None
    points: list[Point] = []
    for index, segment in enumerate(segments):
        physical = stream_path(segment)
        if not physical:
            return []
        points.extend(physical)
        if fs is None or index + 1 == len(segments):
            continue
        following = segments[index + 1]
        station = next((assembly.station for assembly in fs._station_assemblies
                        if assembly.run is root and assembly.station.inlet is segment.dest
                        and assembly.station.outlet is following.source), None)
        if station is None:
            continue
        unit = station.inlet.owner
        for _ in station.members:
            if unit is station.outlet.owner:
                break
            outgoing = unit.ports["outlet"].stream
            if outgoing is None or outgoing.dest.owner not in station.members:
                return []
            points.extend(stream_path(outgoing))
            unit = outgoing.dest.owner
    return points


def _along(points: list[Point], fraction: float) -> tuple[Point, Point]:
    """Return the point a fraction along a polyline, and its heading."""
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
    """Return a balloon's tap point and reference direction, or None."""
    from pandid.portgeom import face_point
    from pandid.streams import Stream

    host = inst.host
    assert host is not None
    if isinstance(host, Stream):
        points = logical_stream_path(host)
        if len(points) < 2:
            return None
        return _along(points, float(inst.at if inst.at is not None else 0.5))
    if host.frame is None:
        return None
    (px, py), (nx, ny) = face_point(host, host.frame, str(inst.at or "E"))
    return (px, py), (-ny, nx)


def _intrusion(a: Box, b: Box, gap: float) -> float:
    """Return the overlap area of two boxes grown by a gap."""
    wide = min(a[2], b[2]) - max(a[0], b[0]) + gap
    tall = min(a[3], b[3]) - max(a[1], b[1]) + gap
    return max(0.0, wide) * max(0.0, tall)


def _nozzle_keepouts(fs: "Flowsheet", *, margin: float = 0.0) -> list[Box]:
    """Return the escape strips outside connected process nozzles."""
    from pandid.portgeom import port_anchor

    out: list[Box] = []
    for u in fs.units:
        if u.frame is None or is_attached(u):
            continue
        for name, port in u.ports.items():
            if port.stream is None:
                continue
            ax, ay, facing = port_anchor(u, u.frame, name)
            bx = ax + ESCAPE_ROOM * (1.0 if facing == "E" else -1.0 if facing == "W" else 0.0)
            by = ay + ESCAPE_ROOM * (1.0 if facing == "S" else -1.0 if facing == "N" else 0.0)
            out.append((min(ax, bx) - margin, min(ay, by) - margin,
                        max(ax, bx) + margin, max(ay, by) + margin))
    return out


def _branch_angles(requested: float) -> list[float]:
    """Return the branch angles to try, nearest the request first."""
    floor = math.sin(math.radians(MIN_BRANCH))
    angles = [requested]
    for k in range(1, int(SWEEP_LIMIT // SWEEP_STEP) + 1):
        for swing in (k * SWEEP_STEP, -k * SWEEP_STEP):
            angle = requested + swing
            if abs(math.sin(math.radians(angle))) >= floor:
                angles.append(angle)
    return angles


def _standoff_box(tap: Point, ref: Point, distance: float, angle: float,
                  w: float, h: float) -> Box:
    """Return the box of a balloon hung from a tap.

    Parameters
    ----------
    ref : Point
        Host's reference direction.
    distance : float
        Standoff from the tap to the balloon centre.
    angle : float
        Branch angle from ``ref``, anticlockwise.
    """
    ux, uy = _rotate_ccw(ref[0], ref[1], angle)
    cx, cy = tap[0] + ux * distance, tap[1] + uy * distance
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _clear_standoff(inst: "Instrument", tap: Point, ref: Point,
                    w: float, h: float,
                    obstacles: list[Box],
                    keepouts: list[Box]) -> tuple[float, float]:
    """Return the distance and angle to hang a balloon at.

    The requested standoff is kept if it overlaps nothing, or if it is
    an inline balloon straddling its tap on a stream. Otherwise the
    angle swings about the tap, then the distance grows. When nothing
    is clear, the candidate with the least overlap is returned.

    Parameters
    ----------
    ref : Point
        Host's reference direction.
    obstacles : list[Box]
        Placed process boxes and balloons placed earlier in this pass.
    keepouts : list[Box]
        Boxes a moved balloon must also clear.
    """
    from pandid.streams import Stream

    on_a_line = isinstance(inst.host, Stream)
    angles = _branch_angles(inst.angle)
    asked = (inst.offset, inst.angle)
    fallback, least = asked, None
    for ring in range(STANDOFF_STEPS + 1):
        distance = inst.offset + ring * STANDOFF_STEP
        for angle in angles:
            box = _standoff_box(tap, ref, distance, angle, w, h)
            if (distance, angle) == asked:
                if (on_a_line and box[0] <= tap[0] <= box[2]
                        and box[1] <= tap[1] <= box[3]):
                    return asked
                gap, against = -TOUCHING, obstacles
            else:
                gap, against = RESOLVED_CLEARANCE, obstacles + keepouts
            if not any(_intrusion(box, o, gap) > 0.0 for o in against):
                return distance, angle
            # Rank fallbacks by the overlap validation reports.
            crowding = sum(_intrusion(box, o, -TOUCHING) for o in obstacles)
            if least is None or crowding < least:
                fallback, least = (distance, angle), crowding
    return fallback


def place_attached(fs: "Flowsheet") -> bool:
    """Place attached balloons and return whether any moved.

    Balloons left unplaced are recorded in ``fs.unplaced_instruments``.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size, unit_box

    moved = False
    # Start from process boxes; each balloon joins once placed.
    obstacles = [unit_box(u, u.frame) for u in fs.units
                 if u.frame is not None and not is_attached(u)]
    mounted = fs._mounted_layout
    keepouts = _nozzle_keepouts(fs, margin=RESOLVED_CLEARANCE if mounted else 0.0)
    # Place a host before whatever hangs on it.
    pending = [u for u in fs.units if is_attached(u)]
    while pending:
        progressed = False
        for inst in list(pending):
            if inst.host in pending:
                continue
            anchor = _anchor(inst)
            if anchor is None:
                continue
            (tx, ty), ref = anchor
            w, h = resolve_size(inst)
            distance, angle = _clear_standoff(
                inst, (tx, ty), ref, w, h,
                obstacles + keepouts if mounted else obstacles,
                [] if mounted else keepouts)
            ux, uy = _rotate_ccw(ref[0], ref[1], angle)
            cx, cy = tx + ux * distance - w / 2, ty + uy * distance - h / 2
            # An absolute pin replaces the standoff on its axis.
            pin = inst.pin_
            if pin is not None:
                cx = cx if pin.x is None else float(pin.x)
                cy = cy if pin.y is None else float(pin.y)
            obstacles.append((cx, cy, cx + w, cy + h))
            old = inst.frame
            if old is None or abs(old.x - cx) > 0.01 or abs(old.y - cy) > 0.01:
                moved = True
            inst.frame = Frame(
                x=cx, y=cy, w=w, h=h, label_pos="center",
                orientation=pin.orientation if pin else 0.0,
                mirrored=pin.mirrored if pin else False,
                mirror_y=pin.mirror_y if pin else False,
                # Keep the faces already chosen.
                port_faces=dict(old.port_faces) if old is not None else {},
            )
            inst.tap = (tx, ty)
            pending.remove(inst)
            progressed = True
        if not progressed:
            # The rest hang on each other in a closed chain.
            break
    fs.unplaced_instruments = list(pending)
    return moved
