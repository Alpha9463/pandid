"""Instrument attachment: balloons anchored to a line or to equipment.

A P&ID bubble is not a node in the process flow; it is furniture hung
off a tap point. So an attached instrument takes no part in stage 1 (it
has no column and no row) and its frame comes from its host instead: a
point on the host stream's routed path, or the midpoint of a face of the
host unit's drawn box, pushed out along a branch direction measured from
the flow. The space it will need is reserved before stage 1 places
anything -- see :mod:`pandid.layout.halo` -- so what it lands in is
paper nothing else was allowed to take.

The tap point is resolved through :mod:`pandid.portgeom`, so a balloon
can never disagree with the nozzle geometry the router and renderer see.

The tap is the anchor and never moves; the *standoff* -- how far out and
in which direction -- is the only thing this module may choose, and it
chooses it against everything already on the sheet. See
:func:`_clear_standoff`.

**Unless the author placed it.** A balloon carries a
:class:`~pandid.geometry.Pin` like any other unit, and an absolute
``x``/``y`` on one is honoured here, per axis, in place of the standoff
this module would have chosen (#467). It is not a rank -- there is no
grid for a bubble to stand in -- and ``col``/``row`` on one is still
nothing this sweep can read, which
:func:`pandid.validate.geometry_issues` reports as ``pin-not-honored``.
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

#: How far out :func:`_clear_standoff` walks a balloon that collides,
#: per step, and how many steps it may take.
#:
#: A step is the balloon's own radius. Shorter, and a box only just
#: clear of one obstacle needs several steps to clear the next; longer,
#: and the first free ring is further out than the drawing needed.
#: Eight of them is enough to walk a bubble clear of the tallest vessel
#: in the corpus, and a search that runs out returns the least-bad
#: standoff rather than growing without bound.
STANDOFF_STEP = 22.0
STANDOFF_STEPS = 8

#: How far either side of the branch angle asked for the search may
#: swing the balloon, and in what increments. The sweep runs at a fixed
#: distance from the tap, so it is a rotation about the anchor and not a
#: move of it.
SWEEP_LIMIT = 60.0
SWEEP_STEP = 15.0

#: How near the host's own reference direction a swept angle may come.
#: That reference is the flow at a stream tap and the face tangent on a
#: unit host, so a branch along it lays the balloon *on* the line it
#: reads or flat against the face it is mounted on. Both are clear of
#: every box on the sheet and neither can be read, which is exactly the
#: kind of answer a box-overlap search would otherwise be delighted with.
MIN_BRANCH = 20.0

#: What a balloon the search *had* to move clears its neighbours by.
#:
#: Nothing is ever moved in order to reach it: the standoff the author
#: asked for is kept whenever it merely does not overlap, which is what
#: leaves a bubble deliberately set a pixel off a primary element (11's
#: FT-303 on FE-303) exactly where it was put. The clearance applies
#: only once a collision has already forced a different standoff, and
#: then it is the difference between a balloon that reads as separate
#: and one that is separate by a hair.
RESOLVED_CLEARANCE = 6.0

#: How much room in front of a nozzle a *moved* balloon leaves the
#: router. ``VisibilityGraph`` stands every run off its nozzle before it
#: may turn, by this much or more -- more where a label has to be
#: cleared, but the label pass has not run the first time a balloon is
#: placed, so the bare stand-off is the one figure true at every call.
#: Under-stating it leaves a nozzle the router can still escape from;
#: over-stating it would walk bubbles out past corridors nothing needs.
ESCAPE_ROOM = 25.0

#: The overlap :func:`pandid.validate.validate` tolerates before it
#: calls two boxes collided -- its ``_TOL``, restated rather than
#: imported so that a layout phase does not reach into the checker's
#: privates. ``tests/test_instruments.py`` pins the two together, because
#: a search that resolved to a tighter rule than the check would report
#: overlaps it had just declared itself finished with.
TOUCHING = 1.0

Box = tuple[float, float, float, float]


def is_attached(unit: "Unit | None") -> bool:
    """True when a host positions this unit, not the coordinate pass.

    Which balloons stage 2 resolves *from something else* rather than
    from their wiring; :func:`pandid.layout.stages.is_control` is the
    question of which units stage 2 places at all, and is the one the
    process/control boundary is drawn on.
    """
    return unit is not None and getattr(unit, "host", None) is not None


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


def _intrusion(a: Box, b: Box, gap: float) -> float:
    """How much of *a* lies within *gap* of *b*, as an area.

    ``gap = -TOUCHING`` is exactly the overlap
    :func:`pandid.validate.validate` reports, so "the search found a free
    standoff" and "the checker finds no overlap" are the same statement
    rather than two rules that have to be kept in step. A positive
    *gap* asks for daylight as well.
    """
    wide = min(a[2], b[2]) - max(a[0], b[0]) + gap
    tall = min(a[3], b[3]) - max(a[1], b[1]) + gap
    return max(0.0, wide) * max(0.0, tall)


def _nozzle_keepouts(fs: "Flowsheet") -> list[Box]:
    """The stand-off in front of every connected nozzle on the sheet.

    A run leaves its nozzle along the outward face and may not turn until
    it has cleared :data:`ESCAPE_ROOM`; park a bubble across that and the
    router finds no path out at all and falls back to an unchecked L. So
    a balloon the search *had* to move keeps off them -- not the balloon
    the author placed, which is judged on drawn boxes alone, so a sheet
    already drawing well is not rearranged around a rule it never had to
    meet.

    Read off the nozzles rather than off the routed paths, and only the
    ranked units' nozzles: both are settled before this sweep begins and
    stay settled through it, so this cannot be the thing that makes a
    placement chase a line the router has not drawn yet.
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
            out.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
    return out


def _branch_angles(requested: float) -> list[float]:
    """Branch angles to try, the one asked for first.

    Ordered by how far each is from the request, so the search gives up
    as little of the author's intent as the sheet allows. The near-axial
    ones are dropped (see :data:`MIN_BRANCH`) *except* for the request
    itself, which is honoured however it is spelled: an author who puts
    a bubble along the line has said something, and this is not the
    place to overrule it.
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
    """The drawn box of a balloon hung *distance* out from *tap* at
    *angle* off the host's reference direction."""
    ux, uy = _rotate_ccw(ref[0], ref[1], angle)
    cx, cy = tap[0] + ux * distance, tap[1] + uy * distance
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _clear_standoff(inst: "Instrument", tap: Point, ref: Point,
                    w: float, h: float,
                    obstacles: list[Box],
                    keepouts: list[Box]) -> tuple[float, float]:
    """``(distance, angle)`` to hang *inst* at: what it asked for, or the
    nearest standoff out from it that nothing else is standing in.

    The anchor does not move. Only the standoff does, and only outward:
    the balloon is swung about the tap at one distance, and *then* the
    distance grows -- never the reverse. That is what makes a pass
    monotone, which is what makes the placement/routing fixed point in
    :meth:`pandid.flowsheet.Flowsheet.route` terminate rather than
    trading two arrangements back and forth until
    :data:`MAX_PLACEMENT_PASSES` trips.

    *obstacles* is every drawn box already on the sheet -- the ranked
    units, and the balloons this sweep has placed before this one. Not
    the routed paths: a standoff chosen against a line the router has
    yet to redraw is a standoff that moves every time the line does, and
    that loop has no bottom. *keepouts* holds the nozzle stand-offs of
    :func:`_nozzle_keepouts`, which only a *replacement* standoff has to
    respect.

    Deliberately no search at all for a balloon that straddles its own
    tap **on a stream**: that is an in-line primary element (``offset=0``
    is how an orifice plate is drawn), and it is the same test
    :class:`pandid.routing.visibility.VisibilityGraph` uses to leave one
    out of its obstacles -- so a symbol the router draws *through* is one
    this refuses to push aside. A balloon straddling a *unit* face is not
    that: there is no line for it to be in, and what it is actually doing
    is standing half inside the wall it is mounted on, which is the
    collision rather than the exception to it.
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
            # Ranked on one rule for every candidate, and the checker's
            # rather than the search's: where the sheet has no free
            # standoff at all, the balloon should land on the one that
            # overlaps least of what a reader would be shown, not on the
            # one that came closest to a clearance nothing could meet.
            crowding = sum(_intrusion(box, o, -TOUCHING) for o in obstacles)
            if least is None or crowding < least:
                fallback, least = (distance, angle), crowding
    return fallback


def place_attached(fs: "Flowsheet") -> bool:
    """Resolve every attached instrument's frame from its host, or its pin.

    Returns True if any balloon moved, which is the signal that the
    lines running to it are stale and have to be routed again.

    An absolute pin wins over the host on the axis it names; see the
    module docstring. Everything below is about the axes nobody stated.

    Balloons are resolved in the order they were added to the sheet, and
    each sees only the boxes resolved before it -- never the previous
    sweep's, which would make a second ``layout()`` of the same model
    draw a different sheet from the first. So placement is first come,
    first served in declaration order: deterministic, and stated in the
    one thing the author controls.

    The balloons no host could position are left on
    ``fs.unplaced_instruments``, since this sweep is the only thing that
    knows which they are. :func:`pandid.validate.validate` reads them
    back as ``instrument-unplaced``.
    """
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_size, unit_box

    moved = False
    # What a balloon has to keep out of. The ranked units are all of it
    # to begin with -- an attached one carries a frame from the last
    # sweep, and reading that back is what would make this pass depend
    # on the one before it -- and each balloon joins as it is placed.
    obstacles = [unit_box(u, u.frame) for u in fs.units
                 if u.frame is not None and not is_attached(u)]
    keepouts = _nozzle_keepouts(fs)
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
            (tx, ty), ref = anchor
            w, h = resolve_size(inst)
            distance, angle = _clear_standoff(
                inst, (tx, ty), ref, w, h, obstacles, keepouts)
            ux, uy = _rotate_ccw(ref[0], ref[1], angle)
            cx, cy = tx + ux * distance - w / 2, ty + uy * distance - h / 2
            # An absolute pin supersedes the standoff on the axis it
            # names, exactly as it supersedes a grid rank on every other
            # unit -- and per axis for the same reason, so
            # ``pin(x=...)`` fixes the column the bubble stands in and
            # leaves the search to find it clear air down the page.
            #
            # Read off ``pin_`` rather than off the raw coordinates, so
            # ``pin(port="signal", y=...)`` puts the *nozzle* on that
            # elevation: the property derives the corner from the
            # nozzle relation the author stated (#294), and a balloon's
            # signal terminal is the point on it worth lining up.
            #
            # Not swept, not cleared, not walked out of a collision: the
            # author said where. What the search may still choose is the
            # standoff on the axes they left alone, and the tap is the
            # host's either way, so the leader line still lands on the
            # line or the face the balloon reads.
            pin = inst.pin_
            if pin is not None:
                cx = cx if pin.x is None else float(pin.x)
                cy = cy if pin.y is None else float(pin.y)
            obstacles.append((cx, cy, cx + w, cy + h))
            old = inst.frame
            if old is None or abs(old.x - cx) > 0.01 or abs(old.y - cy) > 0.01:
                moved = True
            # Carry the placement transform across: an attached balloon
            # is positioned by its host rather than by the coordinate
            # pass, so without this a pin(mirrored=...) on one is
            # silently dropped, and mirroring is how a balloon puts its
            # signal port on the side the run actually comes from.
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
