"""Place attached instrument balloons from their hosts.

An attached balloon is not a process node: it has no grid rank, and its
frame comes from its host. The tap point is a point on the host stream's
drawn path, or the midpoint of a face of the host unit, resolved through
:mod:`pandid.portgeom`. The balloon hangs from the tap at a standoff
distance and branch angle; :func:`_clear_standoff` may change the
standoff to avoid other boxes, but never the tap. Room is reserved before
stage 1 by :mod:`pandid.layout.halo`.

An absolute ``x`` or ``y`` pin on a balloon replaces the standoff on that
axis. A ``col`` or ``row`` pin has no meaning here and is reported as
``pin-not-honored`` by :func:`pandid.validate.geometry_issues`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Instrument, Unit

Point = tuple[float, float]

#: Maximum placement and routing passes in
#: :meth:`pandid.flowsheet.Flowsheet.route`. A balloon is placed on its
#: host's routed path and then becomes an obstacle that can bend that path,
#: so some sheets cycle; the cap ends the loop with a warning. Every pass
#: ends on a route, so every line still reaches its balloon.
MAX_PLACEMENT_PASSES = 6

#: Distance step, about one balloon radius, and number of steps
#: :func:`_clear_standoff` may move a colliding balloon outward.
STANDOFF_STEP = 22.0
STANDOFF_STEPS = 8

#: Largest swing either side of the requested branch angle, and its
#: increment, in degrees. The swing rotates the balloon about its tap.
SWEEP_LIMIT = 60.0
SWEEP_STEP = 15.0

#: Smallest angle, in degrees, between a swept branch and the host's
#: reference direction (the flow at a stream tap, the face tangent on a
#: unit). A smaller angle lays the balloon along the line or the face.
MIN_BRANCH = 20.0

#: Clearance a balloon keeps once a collision has forced a new standoff.
#: The requested standoff is kept whenever it merely does not overlap.
RESOLVED_CLEARANCE = 6.0

#: Length of the strip in front of a connected nozzle that a moved balloon
#: keeps clear, matching the router's minimum stand-off.
ESCAPE_ROOM = 25.0

#: Overlap :func:`pandid.validate.validate` tolerates before it reports a
#: collision. Restated here; ``tests/test_instruments.py`` keeps the two
#: equal.
TOUCHING = 1.0

Box = tuple[float, float, float, float]


def is_attached(unit: "Unit | None") -> bool:
    """Return whether a unit is positioned by a host.

    :func:`pandid.layout.stages.is_control` decides which units stage 2
    places; this decides which of those resolve from a host.

    Parameters
    ----------
    unit : Unit or None
        Unit to test.

    Returns
    -------
    bool
        Whether the unit has a host.
    """
    return unit is not None and getattr(unit, "host", None) is not None


def _rotate_ccw(vx: float, vy: float, degrees: float) -> Point:
    """Rotate a direction anticlockwise as drawn on the y-down canvas.

    Parameters
    ----------
    vx, vy : float
        Direction to rotate.
    degrees : float
        Anticlockwise angle.

    Returns
    -------
    Point
        Rotated direction.
    """
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c + vy * s, -vx * s + vy * c)


def stream_path(stream: "Stream") -> list[Point]:
    """Return the polyline a stream is drawn along.

    It matches the renderer's line, so ``at=`` measures along what the
    reader sees.

    Parameters
    ----------
    stream : Stream
        Stream to trace.

    Returns
    -------
    list[Point]
        Port points and route waypoints, or an empty list before either end
        has a frame.
    """
    from pandid.portgeom import port_point

    src_u, dst_u = stream.source.owner, stream.dest.owner
    if src_u is None or dst_u is None or src_u.frame is None or dst_u.frame is None:
        return []
    mid = list(stream.route.waypoints) if (stream.route and stream.route.waypoints) else []
    return ([port_point(src_u, src_u.frame, stream.source.name)] + mid
            + [port_point(dst_u, dst_u.frame, stream.dest.name)])


def logical_stream_path(stream: "Stream") -> list[Point]:
    """Trace a logical run through its inserted physical segments.

    Parameters
    ----------
    stream : Stream
        Original run handle or an ordinary physical segment.

    Returns
    -------
    list[Point]
        Routed points with each inline device's inlet and outlet joined.
    """
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
    """Return the point a fraction along a polyline, and its direction.

    Parameters
    ----------
    points : list[Point]
        Polyline with at least one point.
    fraction : float
        Fraction of the total length, clamped to ``[0, 1]``.

    Returns
    -------
    tuple[Point, Point]
        Point and unit direction of the segment it lies on.
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
    """Find an attached instrument's tap point and flow direction.

    Parameters
    ----------
    inst : Instrument
        Instrument with a unit or stream host.

    Returns
    -------
    tuple[Point, Point] or None
        Tap point and reference direction, or None before placement.
    """
    from pandid.portgeom import face_point
    from pandid.streams import Stream

    host = inst.host
    # place_attached only offers attached balloons.
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
    """Return the area of overlap between two boxes grown by a gap.

    With ``gap = -TOUCHING`` this is the overlap
    :func:`pandid.validate.validate` reports; a positive gap also demands
    clearance.

    Parameters
    ----------
    a, b : Box
        Boxes as ``(left, top, right, bottom)``.
    gap : float
        Clearance added to the overlap test.

    Returns
    -------
    float
        Overlap area, zero when clear.
    """
    wide = min(a[2], b[2]) - max(a[0], b[0]) + gap
    tall = min(a[3], b[3]) - max(a[1], b[1]) + gap
    return max(0.0, wide) * max(0.0, tall)


def _nozzle_keepouts(fs: "Flowsheet", *, margin: float = 0.0) -> list[Box]:
    """Describe the outward escape strips of connected process nozzles.

    Parameters
    ----------
    fs : Flowsheet
        Drawing with ranked process frames.
    margin : float, optional
        Clearance around each exit strip.

    Returns
    -------
    list[Box]
        Rectangles immediately outside connected nozzles.
    """
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
    """Return the branch angles to try, nearest the request first.

    Angles within :data:`MIN_BRANCH` of the reference direction are left
    out, except the requested angle itself.

    Parameters
    ----------
    requested : float
        Branch angle the author asked for.

    Returns
    -------
    list[float]
        Requested angle, then swings of :data:`SWEEP_STEP` up to
        :data:`SWEEP_LIMIT` either side.
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
        Tap point.
    ref : Point
        Host's reference direction.
    distance : float
        Standoff from the tap to the balloon centre.
    angle : float
        Branch angle from ``ref``, anticlockwise.
    w, h : float
        Balloon size.

    Returns
    -------
    Box
        ``(left, top, right, bottom)``.
    """
    ux, uy = _rotate_ccw(ref[0], ref[1], angle)
    cx, cy = tap[0] + ux * distance, tap[1] + uy * distance
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _clear_standoff(inst: "Instrument", tap: Point, ref: Point,
                    w: float, h: float,
                    obstacles: list[Box],
                    keepouts: list[Box]) -> tuple[float, float]:
    """Return the standoff to hang a balloon at.

    The requested standoff is used if it overlaps nothing. Otherwise the
    branch angle is swung about the tap at that distance, then the
    distance grows by :data:`STANDOFF_STEP`. Standoffs only move outward,
    which lets the placement and routing loop in
    :meth:`pandid.flowsheet.Flowsheet.route` settle. A replacement standoff
    must also clear the nozzle keepouts by :data:`RESOLVED_CLEARANCE`.

    A balloon on a stream whose requested box straddles its tap is an
    inline primary element (``offset=0``) and is kept where requested, as
    the router also routes through it.

    Parameters
    ----------
    inst : Instrument
        Balloon to place.
    tap : Point
        Its tap point.
    ref : Point
        Host's reference direction.
    w, h : float
        Balloon size.
    obstacles : list[Box]
        Placed process boxes and balloons placed earlier in this pass.
        Routes are excluded, because they are redrawn after placement.
    keepouts : list[Box]
        Nozzle exit strips that a replacement standoff must clear.

    Returns
    -------
    tuple[float, float]
        Distance and angle. When nothing is clear, the candidate with the
        least overlap with ``obstacles``.
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
    """Place attached instruments from their hosts and explicit pins.

    Balloons resolve in declaration order against process boxes and earlier
    balloons. Unresolved hosts are recorded in ``fs.unplaced_instruments``.

    Parameters
    ----------
    fs : Flowsheet
        Drawing whose process frames and routed hosts are available.

    Returns
    -------
    bool
        Whether any attached instrument moved.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size, unit_box

    moved = False
    # Start from process boxes only; an attached balloon's old frame would
    # make this pass depend on the last. Each balloon joins once placed.
    obstacles = [unit_box(u, u.frame) for u in fs.units
                 if u.frame is not None and not is_attached(u)]
    coarse = fs._coarse_layout_candidate
    keepouts = _nozzle_keepouts(fs, margin=RESOLVED_CLEARANCE if coarse else 0.0)
    # Balloons chain, so place a host before whatever hangs on it.
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
                obstacles + keepouts if coarse else obstacles,
                [] if coarse else keepouts)
            ux, uy = _rotate_ccw(ref[0], ref[1], angle)
            cx, cy = tx + ux * distance - w / 2, ty + uy * distance - h / 2
            # An absolute pin replaces the standoff on its axis. ``pin_``
            # gives the corner implied by a pinned nozzle, so
            # ``pin(port="signal", y=...)`` aligns the signal terminal.
            pin = inst.pin_
            if pin is not None:
                cx = cx if pin.x is None else float(pin.x)
                cy = cy if pin.y is None else float(pin.y)
            obstacles.append((cx, cy, cx + w, cy + h))
            old = inst.frame
            if old is None or abs(old.x - cx) > 0.01 or abs(old.y - cy) > 0.01:
                moved = True
            # Carry the pinned transform, so mirroring can put the signal
            # port on the side its run comes from.
            inst.frame = Frame(
                x=cx, y=cy, w=w, h=h, label_pos="center",
                orientation=pin.orientation if pin else 0.0,
                mirrored=pin.mirrored if pin else False,
                mirror_y=pin.mirror_y if pin else False,
                # Keep chosen faces; changing them would move a nozzle
                # the router has already reached.
                port_faces=dict(old.port_faces) if old is not None else {},
            )
            inst.tap = (tx, ty)
            pending.remove(inst)
            progressed = True
        if not progressed:
            # The rest hang on each other in a closed chain. They keep
            # ``frame = None`` and are reported as unplaced.
            break
    # Replace, not accumulate, across the route() passes.
    fs.unplaced_instruments = list(pending)
    return moved
