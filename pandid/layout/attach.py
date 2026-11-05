"""Place attached instrument balloons from their hosts.

A balloon hangs from a tap point on its host stream or unit face, at a
standoff distance and branch angle.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pandid.routing.visibility import MIN_ESCAPE

if TYPE_CHECKING:
    from collections.abc import Collection

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
#: reference line.
MIN_BRANCH = 20.0

#: Clearance tested around a standoff other than the asked one.
RESOLVED_CLEARANCE = 6.0

#: Overlap two boxes may share before they count as colliding.
TOUCHING = 1.0

Box = tuple[float, float, float, float]


def is_attached(unit: "Unit | None") -> bool:
    """Return whether a unit is positioned by a host.

    Parameters
    ----------
    unit : Unit or None
        Unit to test.

    Returns
    -------
    bool
        True if the unit has a host.
    """
    return unit is not None and getattr(unit, "host", None) is not None


def _rotate_ccw(vx: float, vy: float, degrees: float) -> Point:
    """Rotate a direction anticlockwise on the y-down canvas.

    Parameters
    ----------
    vx : float
        Direction x component.
    vy : float
        Direction y component.
    degrees : float
        Rotation angle.

    Returns
    -------
    Point
        Rotated direction.
    """
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c + vy * s, -vx * s + vy * c)


def stream_path(stream: "Stream") -> list[Point]:
    """Return a stream's nozzles and waypoints as a polyline, or ``[]``.

    Parameters
    ----------
    stream : Stream
        Stream to trace.

    Returns
    -------
    list[Point]
        Source nozzle, waypoints and destination nozzle.
    """
    from pandid.portgeom import port_point

    src_u, dst_u = stream.source.owner, stream.dest.owner
    if src_u.frame is None or dst_u.frame is None:
        return []
    mid = list(stream.route.waypoints) if (stream.route and stream.route.waypoints) else []
    return ([port_point(src_u, src_u.frame, stream.source.name)] + mid
            + [port_point(dst_u, dst_u.frame, stream.dest.name)])


def logical_stream_path(stream: "Stream") -> list[Point]:
    """Return the polyline of a logical run through its segments.

    Parameters
    ----------
    stream : Stream
        Run handle, or a segment, which gives only its own path.

    Returns
    -------
    list[Point]
        Points along the segments and each station's main line only.
        ``[]`` if a run segment has no drawn path or a station's
        member chain breaks; an unplaced member adds no points.
    """
    segments = stream._logical_segments or [stream]
    root = stream._logical_root or stream
    fs = root.source.owner.flowsheet
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
    """Return the point a fraction along a polyline, and its heading.

    Parameters
    ----------
    points : list[Point]
        Polyline of at least two points.
    fraction : float
        Position along the polyline, clamped to 0 to 1.

    Returns
    -------
    tuple[Point, Point]
        The point and its segment's unit heading, else ``(1, 0)``.
    """
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
    """Return a balloon's tap point and reference direction, or None.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.

    Returns
    -------
    tuple[Point, Point] or None
        Tap point and direction, or None if the host is unplaced.
    """
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
    face = free_face(inst) or inst.face
    (px, py), (nx, ny) = face_point(host, host.frame, face or "E")
    return (px, py), (-ny, nx)


def free_face(inst: "Instrument") -> str | None:
    """Return the face a balloon takes off E, if any.

    It takes one only while its sheet's ``_free_faces`` is set, with no
    face stated, on equipment that is not itself a balloon.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.

    Returns
    -------
    str or None
        That face, or ``None`` if the balloon keeps its own.
    """
    from pandid.streams import Stream

    host, fs = inst.host, inst.flowsheet
    if (fs is None or not fs._free_faces or inst._face_stated or host is None
            or isinstance(host, Stream) or is_attached(host) or host.frame is None):
        return None
    face = _free_face(host)
    return None if face == "E" else face


def _free_face(host: "Unit") -> str:
    """Return the face an unfaced balloon hangs from.

    This is E, unless a line leaves E; then it is the first of N, S
    and W that no line leaves and that has a process nozzle at its
    middle.

    Parameters
    ----------
    host : Unit
        Placed unit a balloon hangs from.

    Returns
    -------
    str
        That face, or ``"E"`` if none qualifies.
    """
    from pandid.portgeom import face_point, resolve_port

    at = {name: resolve_port(host, host.frame, name) for name in host.ports}
    used = {at[name].face for name, port in host.ports.items() if port.stream is not None}
    process = [at[name].point for name, port in host.ports.items() if port.role != "signal"]
    for face in "NSW" if "E" in used else "":
        middle = face_point(host, host.frame, face)[0]
        if face not in used and any(math.dist(point, middle) < 0.5 for point in process):
            return face
    return "E"


def _intrusion(a: Box, b: Box, gap: float) -> float:
    """Return the overlap area of two boxes grown by a gap.

    Parameters
    ----------
    a : Box
        First box.
    b : Box
        Second box.
    gap : float
        Growth added to each overlap extent.

    Returns
    -------
    float
        Overlap area, or 0.
    """
    wide = min(a[2], b[2]) - max(a[0], b[0]) + gap
    tall = min(a[3], b[3]) - max(a[1], b[1]) + gap
    return max(0.0, wide) * max(0.0, tall)


def _nozzle_keepouts(fs: "Flowsheet", *, margin: float = 0.0,
                     skip: "Collection[Unit]" = ()) -> list[Box]:
    """Return the escape strips at unattached units' connected nozzles.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.
    margin : float, optional
        Growth on every side of each strip.
    skip : collection of Unit, optional
        Units whose nozzles get no strip.

    Returns
    -------
    list[Box]
        One strip per connected nozzle.
    """
    from pandid.portgeom import COMPASS, port_anchor

    out: list[Box] = []
    for u in fs.units:
        if u.frame is None or is_attached(u) or u in skip:
            continue
        for name, port in u.ports.items():
            if port.stream is None:
                continue
            ax, ay, facing = port_anchor(u, u.frame, name)
            dx, dy = COMPASS[facing]
            bx, by = ax + MIN_ESCAPE * dx, ay + MIN_ESCAPE * dy
            out.append((min(ax, bx) - margin, min(ay, by) - margin,
                        max(ax, bx) + margin, max(ay, by) + margin))
    return out


def _branch_angles(requested: float) -> list[float]:
    """Return the branch angles to try, nearest the request first.

    Parameters
    ----------
    requested : float
        Requested branch angle, in degrees.

    Returns
    -------
    list[float]
        Angles in the order to try.
    """
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
    tap : Point
        Tap point on the host.
    ref : Point
        Host's reference direction.
    distance : float
        Standoff from the tap to the balloon centre.
    angle : float
        Branch angle from ``ref``, anticlockwise.
    w : float
        Balloon width.
    h : float
        Balloon height.

    Returns
    -------
    Box
        Balloon box as ``(x0, y0, x1, y1)``.
    """
    ux, uy = _rotate_ccw(ref[0], ref[1], angle)
    cx, cy = tap[0] + ux * distance, tap[1] + uy * distance
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _clear_standoff(inst: "Instrument", tap: Point, ref: Point,
                    w: float, h: float,
                    obstacles: list[Box],
                    keepouts: list[Box],
                    runs: tuple[Box, ...] = ()) -> tuple[float, float]:
    """Return the distance and angle to hang a balloon at.

    A balloon whose requested box straddles its stream tap keeps it. No
    candidate's box, moved to the balloon's pin, may come within an
    arrowhead length of ``runs``.

    Parameters
    ----------
    inst : Instrument
        Balloon to place.
    tap : Point
        Tap point on the host.
    ref : Point
        Host's reference direction.
    w : float
        Balloon width.
    h : float
        Balloon height.
    obstacles : list[Box]
        Boxes each candidate is tested against.
    keepouts : list[Box]
        Boxes a moved candidate is also tested against.
    runs : tuple[Box, ...], optional
        Runs to keep off, each as a flat box.

    Returns
    -------
    tuple[float, float]
        First clear standoff and angle, else the least crowded.
    """
    from pandid.render.symbols import ARROWHEAD
    from pandid.streams import Stream

    on_a_line = isinstance(inst.host, Stream)
    pin = inst.pin_
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
            x0 = box[0] if pin is None or pin.x is None else float(pin.x)
            y0 = box[1] if pin is None or pin.y is None else float(pin.y)
            drawn = (x0, y0, x0 + w, y0 + h)
            if not (any(_intrusion(box, o, gap) > 0.0 for o in against)
                    or any(_intrusion(drawn, r, ARROWHEAD) > 0.0 for r in runs)):
                return distance, angle
            # Rank fallbacks by the overlap validation reports.
            crowding = sum(_intrusion(box, o, -TOUCHING) for o in obstacles)
            if least is None or crowding < least:
                fallback, least = (distance, angle), crowding
    return fallback


def _tapped_stream(unit: "Unit") -> "Stream | None":
    """Return the stream at the end of a balloon's chain of hosts.

    Parameters
    ----------
    unit : Unit
        Unit to follow.

    Returns
    -------
    Stream or None
        Stream the chain taps, or None if it ends on a unit or loops.
    """
    from pandid.streams import Stream

    host, seen = getattr(unit, "host", None), set()
    while host is not None and not isinstance(host, Stream) and id(host) not in seen:
        seen.add(id(host))
        host = getattr(host, "host", None)
    return host if isinstance(host, Stream) else None


def _chained(unit: "Unit") -> bool:
    """Return whether a unit hangs from a balloon whose chain taps a line.

    Parameters
    ----------
    unit : Unit
        Unit to test.

    Returns
    -------
    bool
        True for a balloon hung from another balloon on a line.
    """
    from pandid.streams import Stream

    host = getattr(unit, "host", None)
    return host is not None and not isinstance(host, Stream) and _tapped_stream(unit) is not None


def _tapped_runs(inst: "Instrument") -> tuple[Box, ...]:
    """Return the runs of the line a balloon hung from a unit taps.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.

    Returns
    -------
    tuple[Box, ...]
        Each straight run as a flat box; ``()`` for a balloon hung from
        the line itself, a chain that taps no line, or a slanted line.
    """
    from pandid.routing.astar import committed_segments

    stream = _tapped_stream(inst)
    if stream is None or inst.host is stream:
        return ()
    try:
        segments = committed_segments(logical_stream_path(stream))
    except ValueError:  # an undrawn or slanted line has no runs to keep off
        return ()
    return tuple((lo, fixed, hi, fixed) if axis == "h" else (fixed, lo, fixed, hi)
                 for axis, fixed, lo, hi in segments)


def place_attached(fs: "Flowsheet") -> bool:
    """Place attached balloons and return whether any moved.

    Balloons left unplaced are recorded in ``fs.unplaced_instruments``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed process units.

    Returns
    -------
    bool
        True if any balloon is newly placed or moved by over 0.01.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size, unit_box

    moved = False
    # Start from placed unattached units; add each balloon once placed.
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
            runs = _tapped_runs(inst) if fs._keep_clear else ()
            fs._kept_clear = fs._kept_clear or bool(runs)
            distance, angle = _clear_standoff(
                inst, (tx, ty), ref, w, h,
                obstacles + keepouts if mounted else obstacles,
                [] if mounted else keepouts, runs)
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
            # The rest have no tap point or hang on each other.
            break
    fs.unplaced_instruments = list(pending)
    return moved
