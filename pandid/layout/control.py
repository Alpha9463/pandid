"""Place instrument balloons against the settled process geometry.

Process frames are read and never written. An attached balloon resolves
against its host (:func:`~pandid.layout.attach.place_attached`). A
free-standing balloon, such as a panel controller or a logic symbol, is
placed near the units it is wired to, in the nearest free space.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Grid gaps, used to place a pinned column or row the sheet does not use.
from pandid.layout.coordinates import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.units import Unit

#: Clearance between a free-standing balloon and anything already drawn,
#: leaving a lane for its signal lines.
CLEARANCE = 30.0

#: Lattice spacing of the free-spot search, in drawing units.
STEP = 25.0

#: Rings searched before a balloon is left at its preferred spot, where
#: ``validate()`` reports any overlap.
REACH = 40


def place_control(fs: "Flowsheet") -> bool:
    """Place every attached and free-standing balloon.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with settled process frames.

    Returns
    -------
    bool
        Whether any balloon moved.
    """
    from pandid.layout.attach import place_attached

    moved = place_attached(fs)
    return _place_free(fs) or moved


def _place_free(fs: "Flowsheet") -> bool:
    """Place each free-standing balloon near the units it is wired to.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with settled process frames.

    Returns
    -------
    bool
        Whether any free-standing balloon moved.
    """
    from pandid.geometry import Frame
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size

    pending = [u for u in fs.units if is_control(u) and getattr(u, "host", None) is None]
    if not pending:
        return False

    taken = [u.frame for u in fs.units
             if u.frame is not None and u not in set(pending)]
    moved = False
    # Place in flowsheet order. A balloon wired only to unplaced balloons
    # is placed against what is settled, so wired panels terminate.
    for inst in pending:
        w, h = resolve_size(inst)
        x, y = _spot(fs, inst, w, h, taken)
        old = inst.frame
        if old is None or abs(old.x - x) > 0.01 or abs(old.y - y) > 0.01:
            moved = True
        pin = inst.pin_
        inst.frame = Frame(
            x=x, y=y, w=w, h=h, label_pos="center",
            # Record a grid rank only where the pin used one; an absolute
            # coordinate on that axis supersedes it. ``pin-not-honored``
            # reads these to check grid pins.
            col=pin.col if pin is not None and pin.x is None else None,
            row=pin.row if pin is not None and pin.y is None else None,
            orientation=pin.orientation if pin else 0.0,
            mirrored=pin.mirrored if pin else False,
            mirror_y=pin.mirror_y if pin else False,
            # Keep chosen faces; changing them would move a nozzle the
            # router has already reached.
            port_faces=dict(old.port_faces) if old is not None else {},
        )
        taken.append(inst.frame)
    return moved


def _spot(fs: "Flowsheet", inst: "Unit", w: float, h: float,
          taken: list["Frame"]) -> tuple[float, float]:
    """Return a free-standing balloon's top-left corner.

    A pin fixes only the axes it names. ``pin(col=3)`` fixes the column and
    lets the balloon search up and down it; ``pin(col=3, row=1)`` is final.
    Unpinned axes search outward from the centroid of the units it is
    wired to.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with settled process frames.
    inst : Unit
        Free-standing balloon.
    w, h : float
        Balloon size.
    taken : list[Frame]
        Frames already drawn.

    Returns
    -------
    tuple[float, float]
        Top-left corner.
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
    """Return the pixel start of a named grid line.

    An index outside the sheet's grid is extrapolated at the grid's average
    pitch, and a gap inside it is interpolated, so a pinned line always
    resolves. A one-line grid uses its own size plus ``gap`` as the pitch.

    Parameters
    ----------
    grid : dict[int, tuple[float, float]]
        Start and size of each used grid line.
    index : int or None
        Line the author named.
    gap : float
        Gap between lines, used when the pitch cannot be measured.

    Returns
    -------
    float or None
        Start of the line, or ``None`` when no line was named or the grid
        is empty.
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
    """Return the start and size of each grid column and row stage 1 used.

    Only process units count, so a balloon placed earlier in stage 2 cannot
    add a grid line that later balloons are measured against.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with settled process frames.

    Returns
    -------
    tuple[dict[int, tuple[float, float]], dict[int, tuple[float, float]]]
        Columns and rows, each mapping index to ``(start, largest size)``.
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
        Sheet with settled frames.
    inst : Unit
        Free-standing balloon.

    Returns
    -------
    tuple[float, float]
        Mean centre of its placed peers, or a point below the sheet's
        bottom-left corner when none is placed.
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
    # Wired to nothing placed: put it below the sheet's bottom-left corner.
    frames = [u.frame for u in fs.units if u.frame is not None and u is not inst]
    if not frames:
        return 0.0, 0.0
    return (min(f.x for f in frames), max(f.y_max for f in frames) + CLEARANCE * 2)


def _nearest_free(x: float, y: float, w: float, h: float, taken: list["Frame"],
                  free_x: bool, free_y: bool) -> tuple[float, float]:
    """Return the free spot nearest a preferred corner.

    Candidates are lattice rings of growing Chebyshev radius, each walked
    in a fixed order, so the result does not depend on generation order.
    A pinned axis is not searched; with both axes pinned the preferred
    corner is returned even if it overlaps.

    Parameters
    ----------
    x, y : float
        Preferred top-left corner.
    w, h : float
        Box size.
    taken : list[Frame]
        Frames already drawn.
    free_x, free_y : bool
        Whether the search may move along each axis.

    Returns
    -------
    tuple[float, float]
        First clear corner within :data:`REACH` rings, else ``(x, y)``.
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
        Offsets starting at the top-left corner of the ring.
    """
    if radius == 0:
        return [(0, 0)]
    out = [(dx, -radius) for dx in range(-radius, radius + 1)]
    out += [(radius, dy) for dy in range(-radius + 1, radius + 1)]
    out += [(dx, radius) for dx in range(radius - 1, -radius - 1, -1)]
    out += [(-radius, dy) for dy in range(radius - 1, -radius, -1)]
    return out


def _hits(x: float, y: float, w: float, h: float, taken: list["Frame"]) -> bool:
    """Return whether a box comes within :data:`CLEARANCE` of a drawn frame.

    Parameters
    ----------
    x, y, w, h : float
        Candidate box.
    taken : list[Frame]
        Frames already drawn.

    Returns
    -------
    bool
        Whether the padded box overlaps any frame.
    """
    for frame in taken:
        if (x < frame.x_max + CLEARANCE and x + w + CLEARANCE > frame.x
                and y < frame.y_max + CLEARANCE and y + h + CLEARANCE > frame.y):
            return True
    return False
