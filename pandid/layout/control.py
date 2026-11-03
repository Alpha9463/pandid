"""Place instrument balloons against the settled process geometry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.layout.layered import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: A drawn box, ``(x_min, y_min, x_max, y_max)``.
_Box = tuple[float, float, float, float]

#: Clearance between a free-standing balloon and anything drawn.
CLEARANCE = 30.0

#: Lattice spacing of the free-spot search, in drawing units.
STEP = 25.0

#: Rings searched before a balloon is left at its preferred spot.
REACH = 40


def place_control(fs: "Flowsheet") -> bool:
    """Place every balloon and return whether any moved.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed process units.

    Returns
    -------
    bool
        True if any balloon is newly placed or moved.
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
        True if any balloon is newly placed or moved.
    """
    from pandid.geometry import Frame
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size, unit_box

    pending = [u for u in fs.units if is_control(u) and getattr(u, "host", None) is None]
    if not pending:
        return False

    # Use each unit's drawn box, which may reach outside its frame.
    taken = [unit_box(u, u.frame) for u in fs.units
             if u.frame is not None and u not in set(pending)]
    moved = False
    # Place in flowsheet order, each against what is already placed.
    for inst in pending:
        w, h = resolve_size(inst)
        x, y = _spot(fs, inst, w, h, taken)
        old = inst.frame
        if old is None or abs(old.x - x) > 0.01 or abs(old.y - y) > 0.01:
            moved = True
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
    return moved


def _spot(fs: "Flowsheet", inst: "Unit", w: float, h: float,
          taken: list[_Box]) -> tuple[float, float]:
    """Return a free-standing balloon's top-left corner.

    A pinned axis is fixed; an unpinned axis is searched outward from
    the centre of the units the balloon is wired to.

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
        if peer is not None and peer is not inst and peer.frame is not None:
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
    """Return the clear corner nearest ``(x, y)``, else ``(x, y)``.

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
        Top-left corner.
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
