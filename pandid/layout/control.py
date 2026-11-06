"""Place instrument balloons against the settled process geometry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pandid.layout.layered import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Iterator

    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: A drawn box, ``(x_min, y_min, x_max, y_max)``.
_Box = tuple[float, float, float, float]

#: Clearance the free-spot search tests around placed unit boxes.
CLEARANCE = 30.0

#: Distance a tap may lie from its host's line or face.
_TAP_TOL = 0.01

#: Lattice spacing of the free-spot search, in drawing units.
STEP = 25.0

#: Rings searched before a balloon is left at its preferred spot.
REACH = 40

#: Standoff of a balloon hung off the actuator it drives.
ACTUATOR_OFFSET = 100.0

#: Line crossings and runs along units, in all, a redraw may add where
#: it takes a line out of a unit.
UNIT_TRADE = 2


def place_control(fs: "Flowsheet") -> bool:
    """Place balloons and return whether any moved.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed process units.

    Returns
    -------
    bool
        True if any balloon is newly placed or moved by over 0.01.
    """
    from pandid.layout.attach import place_attached

    moved = place_attached(fs)
    return _place_free(fs) or moved


def _place_free(fs: "Flowsheet") -> bool:
    """Place free-standing balloons and return whether any moved.

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
    from pandid.layout.attach import _nozzle_keepouts
    from pandid.layout.faces import select_faces
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size, unit_box

    pending = [u for u in fs.units if is_control(u) and getattr(u, "host", None) is None]
    if not pending:
        return False

    # Use each unit's drawn box, which may reach outside its frame.
    taken = [unit_box(u, u.frame) for u in fs.units
             if u.frame is not None and u not in set(pending)]
    # Strips a balloon hung off an actuator must clear.
    clear = _nozzle_keepouts(fs, skip=set(pending))
    # Drawn lines it must clear too, each with the units it joins.
    segments = _segments(fs)
    # Tag halos a hung balloon must clear, as the router blocks them.
    halos = _halos(fs) if fs._may_hang else []
    moved = rehung = False
    # Place in flowsheet order, each against what is already placed.
    for inst in pending:
        w, h = resolve_size(inst)
        crossed = [box for ends, box in segments if inst not in ends]
        valve = _hangable(fs, inst) if fs._may_hang else None
        standoff = (None if valve is None
                    else next(_actuator_spots(valve, w, h, taken + clear + crossed + halos),
                              None))
        hung = (None if valve is None or standoff is None
                else _actuator_box(valve, standoff, w, h)[:2])
        if hung is not None:
            fs._hung.add(id(inst))
        x, y = hung or _spot(fs, inst, w, h, taken)
        old = inst.frame
        if old is None or abs(old.x - x) > 0.01 or abs(old.y - y) > 0.01:
            moved = True
            rehung = rehung or hung is not None
        pin = inst.pin_
        inst.frame = Frame(
            x=x, y=y, w=w, h=h, label_pos="center",
            # Record a grid rank only where the pin used one.
            col=pin.col if pin is not None and pin.x is None else None,
            row=pin.row if pin is not None and pin.y is None else None,
            orientation=pin.orientation if pin else 0.0,
            mirrored=pin.mirrored if pin else False,
            mirror_y=pin.mirror_y if pin else False,
            # Keep the faces already chosen.
            port_faces=dict(old.port_faces) if old is not None else {},
        )
        taken.append(unit_box(inst, inst.frame))
    # Faces were chosen for where a newly hung controller stood.
    if rehung:
        select_faces(fs)
    return moved


def _segments(fs: "Flowsheet") -> list[tuple[tuple[object, ...], _Box]]:
    """Return the segments of every drawn line and tap line.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    list[tuple[tuple[object, ...], _Box]]
        Each segment as a box, with the units its line joins.
    """
    from pandid.layout.attach import stream_path
    from pandid.render.svg import tap_lines, tap_route

    lines: list[tuple[tuple[object, ...], list[tuple[float, float]]]] = [
        ((u.host,), tap_route(u, tap, centre)) for u, tap, centre in tap_lines(fs)]
    lines += [((s.source.owner, s.dest.owner), stream_path(s))
              for s in fs.streams if s.route is not None]
    return [(ends, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
            for ends, points in lines for a, b in zip(points, points[1:])]


def _beside_valve(fs: "Flowsheet", inst: "Unit"
                  ) -> "Iterator[tuple[float, float, tuple[float, float]]]":
    """Yield the places of a controller hung off the valve it drives.

    A balloon :func:`_hangs_beside` accepts may stand where
    :func:`_actuator_spots` puts it, clear of every other unit, nozzle
    strip, drawn line and tag.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    inst : Unit
        Balloon to place.

    Yields
    ------
    tuple[float, float, tuple[float, float]]
        Top-left corner and the standoff and angle off the actuator,
        nearest first; none if the balloon does not qualify.
    """
    from pandid.layout.attach import _nozzle_keepouts
    from pandid.portgeom import unit_box

    valve = _hangs_beside(fs, inst)
    frame = inst.frame
    if valve is None or frame is None:
        return
    blocked = [unit_box(u, u.frame) for u in fs.units if u is not inst and u.frame is not None]
    blocked += _nozzle_keepouts(fs) + _halos(fs)
    blocked += [box for ends, box in _segments(fs) if inst not in ends]
    for standoff in _actuator_spots(valve, frame.w, frame.h, blocked):
        x0, y0, _, _ = _actuator_box(valve, standoff, frame.w, frame.h)
        yield x0, y0, standoff


def _hangs_beside(fs: "Flowsheet", inst: "Unit") -> "Unit | None":
    """Return the valve a controller may hang beside, if any.

    Parameters
    ----------
    fs : Flowsheet
        Sheet the balloon is on.
    inst : Unit
        Balloon to test.

    Returns
    -------
    Unit or None
        The valve :func:`_driven` finds for a balloon placed near the
        balloon it hangs from, with no face stated and no pin; None for
        any other balloon, such as one placed near a line or a process
        unit.
    """
    from pandid.units import Instrument

    if (not isinstance(inst, Instrument) or inst.relation != "near"
            or not isinstance(inst.host, Instrument) or inst._face_stated
            or inst.pin_ is not None):
        return None
    return _driven(fs, inst)


def _actuator_box(valve: "Unit", standoff: tuple[float, float], w: float,
                  h: float) -> _Box:
    """Return the box of a balloon hung off a valve's actuator.

    Parameters
    ----------
    valve : Unit
        Placed valve.
    standoff : tuple[float, float]
        Distance from the actuator to the balloon centre, and branch
        angle from square to the actuator's face, anticlockwise.
    w : float
        Balloon width.
    h : float
        Balloon height.

    Returns
    -------
    _Box
        Balloon box.
    """
    from pandid.layout.attach import _standoff_box
    from pandid.portgeom import face_point, port_anchor

    ax, ay, face = port_anchor(valve, valve.frame, "actuator")
    _, (nx, ny) = face_point(valve, valve.frame, face)
    return _standoff_box((ax, ay), (-ny, nx), standoff[0], standoff[1], w, h)


def _actuator_spots(valve: "Unit", w: float, h: float,
                    blocked: list[_Box]) -> "Iterator[tuple[float, float]]":
    """Yield the standoffs of a balloon hung off a valve's actuator.

    The balloon stands :data:`ACTUATOR_OFFSET` out from the actuator,
    square to its face, and steps out and swings as an attached balloon
    does, at each place clear of every blocked box.

    Parameters
    ----------
    valve : Unit
        Placed valve.
    w : float
        Balloon width.
    h : float
        Balloon height.
    blocked : list[_Box]
        Boxes the balloon must clear.

    Yields
    ------
    tuple[float, float]
        Distance and angle for :func:`_actuator_box`, nearest first.
    """
    from pandid.layout.attach import (
        RESOLVED_CLEARANCE, STANDOFF_STEP, STANDOFF_STEPS, _branch_angles, _intrusion)

    for ring in range(STANDOFF_STEPS + 1):
        for angle in _branch_angles(90.0):
            standoff = (ACTUATOR_OFFSET + ring * STANDOFF_STEP, angle)
            box = _actuator_box(valve, standoff, w, h)
            if not any(_intrusion(box, b, RESOLVED_CLEARANCE) > 0.0 for b in blocked):
                yield standoff


def _hangable(fs: "Flowsheet", inst: "Unit") -> "Unit | None":
    """Return the valve a free balloon may hang off, if any.

    Parameters
    ----------
    fs : Flowsheet
        Sheet the balloon is on.
    inst : Unit
        Unit to test.

    Returns
    -------
    Unit or None
        The valve :func:`_driven` finds, or None if the balloon is not a
        free, unpinned control balloon.
    """
    from pandid.layout.stages import is_control

    if not is_control(inst) or getattr(inst, "host", None) is not None or inst.pin_ is not None:
        return None
    return _driven(fs, inst)


def _driven(fs: "Flowsheet", inst: "Unit") -> "Unit | None":
    """Return the one valve a balloon's signal lines drive, if any.

    Parameters
    ----------
    fs : Flowsheet
        Sheet the balloon is on.
    inst : Unit
        Balloon to test.

    Returns
    -------
    Unit or None
        The one placed valve whose actuator the balloon's lines drive,
        or None if they drive another number or a balloon hangs from the
        balloon or its lines.
    """
    wired = [(p, s) for p in inst.ports.values() if (s := p.stream) is not None]
    hosts = {id(inst), *(id(s) for _, s in wired)}
    if any(id(getattr(u, "host", None)) in hosts for u in fs.units):
        return None
    driven = [s.dest.owner for p, s in wired if s.source is p and s.dest.name == "actuator"]
    if len(driven) != 1 or driven[0].frame is None:
        return None
    return driven[0]


def _halos(fs: "Flowsheet") -> list[_Box]:
    """Return the tag halos the router blocks, as boxes.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.

    Returns
    -------
    list[_Box]
        Each halo as ``(left, top, right, bottom)``.
    """
    from pandid.routing.visibility import _tag_halo

    halos = (_tag_halo(u, u.frame) for u in fs.units if u.frame is not None)
    return [(r.x_min, r.y_min, r.x_max, r.y_max) for r in halos if r is not None]


def _flaws(fs: "Flowsheet", full: bool = False) -> "Counter[str]":
    """Count the routed sheet's findings and drawn clashes.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    full : bool, default=False
        Count shared runs per straight run rather than per segment.

    Returns
    -------
    Counter[str]
        Each validate() finding by code, plus units on tag halos, lines
        through tag halos, line segments through units other than
        balloons on that line and the end of a line leaving its own
        nozzle straight out of the face, tap lines through units or tag
        halos, and runs two lines or tap lines share.
    """
    from collections import Counter

    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import _BODY_TOL, boxes_overlap, segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    def crosses(points: list, box: _Box) -> bool:
        """Return whether a polyline crosses a box.

        Parameters
        ----------
        points : list
            Polyline points.
        box : _Box
            Box to test.

        Returns
        -------
        bool
            True if any segment crosses the box.
        """
        return any(segment_crosses_box(a, b, box) for a, b in zip(points, points[1:]))

    flaws = Counter(i.code for i in fs.validate())
    halos = _halos(fs)
    boxes = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    flaws["unit-on-tag"] = sum(boxes_overlap(box, h, -_BODY_TOL)
                               for _, box in boxes for h in halos)
    drawn = [s for s in fs.streams if s.route is not None]
    lines = [stream_path(s) for s in drawn]
    flaws["line-through-tag"] = sum(crosses(points, h) for points in lines for h in halos)
    flaws["line-through-unit"] = sum(_through_units(s, points, boxes)
                                     for s, points in zip(drawn, lines))
    taps = [(inst, tap_route(inst, tap, centre)) for inst, tap, centre in tap_lines(fs)]
    for inst, route in taps:
        flaws["tap-through-unit"] += sum(crosses(route, box) for u, box in boxes
                                         if u is not inst and u is not inst.host)
        flaws["tap-through-tag"] += sum(crosses(route, h) for h in halos)
    runs = [(k, a, b) for k, points in enumerate(lines + [route for _, route in taps])
            for a, b in (_straight_runs(points) if full else zip(points, points[1:]))]
    flaws["line-on-line"] = sum(
        _shared(a, b, c, d) for i, (k, a, b) in enumerate(runs)
        for m, c, d in runs[i + 1:] if m != k)
    return flaws


def _through_units(stream: "Stream", points: list, boxes: list) -> int:
    """Count the segments of a drawn line that cross a unit.

    A line meets its own unit at a nozzle that may sit inside the box,
    and leaves it straight out of the nozzle's face; a balloon on the
    line is not crossed.

    Parameters
    ----------
    stream : Stream
        Drawn stream.
    points : list
        Its polyline.
    boxes : list
        ``(unit, box)`` for every placed unit.

    Returns
    -------
    int
        Segments crossing a unit, once per unit.
    """
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import COMPASS, resolve_port

    def outward(port, nozzle: tuple[float, float], other: tuple[float, float]) -> bool:
        """Return whether a segment leaves a nozzle straight out of its face.

        Parameters
        ----------
        port : Port
            Port the segment ends at.
        nozzle : tuple[float, float]
            The segment's end at the nozzle.
        other : tuple[float, float]
            Its other end.

        Returns
        -------
        bool
            True if the segment runs along the face's outward normal.
        """
        nx, ny = COMPASS[resolve_port(port.owner, port.owner.frame, port.name).face]
        dx, dy = other[0] - nozzle[0], other[1] - nozzle[1]
        return abs(dx * ny - dy * nx) < 1e-6 and dx * nx + dy * ny >= 0.0

    last = len(points) - 2
    return sum(
        segment_crosses_box(a, b, box) for k, (a, b) in enumerate(zip(points, points[1:]))
        for u, box in boxes if getattr(u, "host", None) is not stream
        and not (k == 0 and u is stream.source.owner and outward(stream.source, a, b))
        and not (k == last and u is stream.dest.owner and outward(stream.dest, b, a)))


def _clean(fs: "Flowsheet", stream: "Stream") -> bool:
    """Return whether a line is drawn square and through no unit.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    stream : Stream
        Line to test.

    Returns
    -------
    bool
        True if every segment is level or upright and none crosses a
        unit as :func:`_through_units` counts it.
    """
    from pandid.layout.attach import stream_path
    from pandid.portgeom import unit_box

    points = stream_path(stream)
    boxes = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    return (all(abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5
                for a, b in zip(points, points[1:]))
            and not _through_units(stream, points, boxes))


def _out_of_unit(before: "Counter[str]", after: "Counter[str]") -> bool:
    """Return whether a redraw takes a line out of a unit at a price kept.

    Parameters
    ----------
    before : Counter[str]
        Counts of the drawing before, as ``Flowsheet._counted_flaws``
        returns them.
    after : Counter[str]
        The same counts after.

    Returns
    -------
    bool
        True if fewer lines cross units, crossings and runs along units
        grow by at most :data:`UNIT_TRADE` in all, and no other count
        grows.
    """
    traded = ("crossing", "route-along-unit")
    added = sum(max(0, after[k] - before[k]) for k in traded)
    return (after["route-crosses-unit"] < before["route-crosses-unit"] and added <= UNIT_TRADE
            and not any(n > before[k] for k, n in after.items() if k not in traded))


def _taps_off(fs: "Flowsheet") -> set[int]:
    """Return the balloons whose tap is off their host's drawn line or face.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    set[int]
        ``id()`` of each such balloon.
    """
    from pandid.layout.attach import _anchor, is_attached, logical_stream_path
    from pandid.streams import Stream

    off = set()
    for u in fs.units:
        tap = getattr(u, "tap", None)
        if tap is None or not is_attached(u):
            continue
        if isinstance(u.host, Stream):
            points = logical_stream_path(u.host)
            on = any(min(a[0], b[0]) - _TAP_TOL <= tap[0] <= max(a[0], b[0]) + _TAP_TOL
                     and min(a[1], b[1]) - _TAP_TOL <= tap[1] <= max(a[1], b[1]) + _TAP_TOL
                     for a, b in zip(points, points[1:]))
        else:
            anchor = _anchor(u)
            on = anchor is not None and math.dist(anchor[0], tap) <= _TAP_TOL
        if not on:
            off.add(id(u))
    return off


def _straight_runs(points: list) -> list:
    """Return the ends of each straight run of a polyline.

    Parameters
    ----------
    points : list
        Polyline points.

    Returns
    -------
    list[tuple[tuple[float, float], tuple[float, float]]]
        Each run of segments on one track, to within 1, that keeps one
        direction, as its two ends.
    """
    out: list = []
    for a, b in zip(points, points[1:]):
        if out:
            p, q = out[-1]
            if any(abs(p[i] - q[i]) < 1 and abs(q[i] - b[i]) < 1
                   and (q[1 - i] - p[1 - i]) * (b[1 - i] - q[1 - i]) >= 0 for i in (0, 1)):
                out[-1] = (p, b)
                continue
        out.append((a, b))
    return out


def _shared(a: tuple[float, float], b: tuple[float, float],
            c: tuple[float, float], d: tuple[float, float]) -> bool:
    """Return whether two square runs lie on one track and overlap.

    Parameters
    ----------
    a, b : tuple[float, float]
        Ends of the first run.
    c, d : tuple[float, float]
        Ends of the second run.

    Returns
    -------
    bool
        True if both runs are level, or both upright, to within 1, lie
        within 1 of the same track, and overlap by more than 1 along it.
    """
    for along, across in ((0, 1), (1, 0)):
        if (abs(a[across] - b[across]) < 1 and abs(c[across] - d[across]) < 1
                and abs(a[across] - c[across]) < 1):
            lo = max(min(a[along], b[along]), min(c[along], d[along]))
            hi = min(max(a[along], b[along]), max(c[along], d[along]))
            return hi - lo > 1
    return False


def _spot(fs: "Flowsheet", inst: "Unit", w: float, h: float,
          taken: list[_Box]) -> tuple[float, float]:
    """Return a free-standing balloon's top-left corner.

    An x or y pin, or a grid pin on a non-empty grid, fixes its axis;
    a free axis is searched outward from :func:`_centroid`.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being laid out.
    inst : Unit
        Balloon to place.
    w : float
        Balloon width.
    h : float
        Balloon height.
    taken : list[_Box]
        Boxes already drawn.

    Returns
    -------
    tuple[float, float]
        Top-left corner of the balloon.
    """
    pin = inst.pin_
    centre = _centroid(fs, inst)
    want = (centre[0] - w / 2.0, centre[1] - h / 2.0)
    if pin is None:
        return _nearest_free(want[0], want[1], w, h, taken, True, True)

    cols, rows = _grid(fs)
    x = pin.x if pin.x is not None else _lane(cols, pin.col, COL_GAP)
    y = pin.y if pin.y is not None else _lane(rows, pin.row, ROW_GAP)
    return _nearest_free(want[0] if x is None else x, want[1] if y is None else y,
                         w, h, taken, x is None, y is None)


def _lane(grid: dict[int, tuple[float, float]], index: int | None,
          gap: float) -> float | None:
    """Return the start of a grid line, or None.

    An unused index is interpolated or extrapolated from the used lines.

    Parameters
    ----------
    grid : dict[int, tuple[float, float]]
        Start and size of each used grid line.
    index : int or None
        Grid line to find.
    gap : float
        Gap between lines, used when a one-line grid gives no pitch.

    Returns
    -------
    float or None
        Line start, or None if ``index`` is None or ``grid`` empty.
    """
    if index is None or not grid:
        return None
    if index in grid:
        return grid[index][0]
    known = sorted(grid)
    if len(known) > 1:
        pitch = (grid[known[-1]][0] - grid[known[0]][0]) / (known[-1] - known[0])
    else:
        pitch = grid[known[0]][1] + gap
    if index < known[0]:
        return grid[known[0]][0] - (known[0] - index) * pitch
    if index > known[-1]:
        return grid[known[-1]][0] + (index - known[-1]) * pitch
    below = max(k for k in known if k < index)
    above = min(k for k in known if k > index)
    span = (grid[above][0] - grid[below][0]) / (above - below)
    return grid[below][0] + (index - below) * span


def _grid(fs: "Flowsheet") -> tuple[dict[int, tuple[float, float]],
                                    dict[int, tuple[float, float]]]:
    """Return the start and largest size of each column and row.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed process units.

    Returns
    -------
    tuple[dict[int, tuple], dict[int, tuple]]
        Columns and rows, each keyed by index.
    """
    from pandid.layout.stages import process_units

    cols: dict[int, tuple[float, float]] = {}
    rows: dict[int, tuple[float, float]] = {}
    for u in process_units(fs):
        frame = u.frame
        if frame is None:
            continue
        for index, start, size, grid in ((frame.col, frame.x, frame.w, cols),
                                         (frame.row, frame.y, frame.h, rows)):
            if index is None:
                continue
            held = grid.get(index)
            grid[index] = ((start if held is None else min(held[0], start)),
                           (size if held is None else max(held[1], size)))
    return cols, rows


def _centroid(fs: "Flowsheet", inst: "Unit") -> tuple[float, float]:
    """Return the centre of the placed units a balloon is wired to.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being laid out.
    inst : Unit
        Balloon to place.

    Returns
    -------
    tuple[float, float]
        Their centre, else a spot below the drawing, else ``(0, 0)``.
    """
    points = []
    for port in inst.ports.values():
        stream = port.stream
        if stream is None:
            continue
        peer = stream.dest.owner if stream.source.owner is inst else stream.source.owner
        if peer is not inst and peer.frame is not None:
            points.append((peer.frame.cx, peer.frame.cy))
    if points:
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))
    # Wired to nothing placed: go below the sheet's bottom-left corner.
    frames = [u.frame for u in fs.units if u.frame is not None and u is not inst]
    if not frames:
        return 0.0, 0.0
    return (min(f.x for f in frames), max(f.y_max for f in frames) + CLEARANCE * 2)


def _nearest_free(x: float, y: float, w: float, h: float, taken: list[_Box],
                  free_x: bool, free_y: bool) -> tuple[float, float]:
    """Return the first clear corner on rings out from ``(x, y)``.

    Parameters
    ----------
    x : float
        Preferred left edge.
    y : float
        Preferred top edge.
    w : float
        Box width.
    h : float
        Box height.
    taken : list[_Box]
        Boxes already drawn.
    free_x : bool
        Whether the search may move along x.
    free_y : bool
        Whether the search may move along y.

    Returns
    -------
    tuple[float, float]
        Top-left corner, else ``(x, y)``.
    """
    if not (free_x or free_y):
        return x, y
    for ring in range(REACH):
        for dx, dy in _ring(ring):
            if (dx and not free_x) or (dy and not free_y):
                continue
            cx, cy = x + dx * STEP, y + dy * STEP
            if not _hits(cx, cy, w, h, taken):
                return cx, cy
    return x, y


def _ring(radius: int) -> list[tuple[int, int]]:
    """Return the lattice offsets at one Chebyshev radius, clockwise.

    Parameters
    ----------
    radius : int
        Ring radius in lattice steps.

    Returns
    -------
    list[tuple[int, int]]
        Offsets on the ring.
    """
    if radius == 0:
        return [(0, 0)]
    out = [(dx, -radius) for dx in range(-radius, radius + 1)]
    out += [(radius, dy) for dy in range(-radius + 1, radius + 1)]
    out += [(dx, radius) for dx in range(radius - 1, -radius - 1, -1)]
    out += [(-radius, dy) for dy in range(radius - 1, -radius, -1)]
    return out


def _hits(x: float, y: float, w: float, h: float, taken: list[_Box]) -> bool:
    """Return whether a box is within the clearance of a drawn box.

    Parameters
    ----------
    x : float
        Box left edge.
    y : float
        Box top edge.
    w : float
        Box width.
    h : float
        Box height.
    taken : list[_Box]
        Boxes already drawn.

    Returns
    -------
    bool
        True if the box is too close to any drawn box.
    """
    for x0, y0, x1, y1 in taken:
        if (x < x1 + CLEARANCE and x + w + CLEARANCE > x0
                and y < y1 + CLEARANCE and y + h + CLEARANCE > y0):
            return True
    return False
