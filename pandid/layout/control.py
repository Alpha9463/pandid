"""Stage 2: the instrumentation, against frozen process geometry.

Every balloon on the sheet lands here, and the process boxes are read
and never written. A balloon with a host resolves against it, exactly as
it always has (:func:`~pandid.layout.attach.place_attached`); a
free-standing one -- a controller in a panel, a logic square between two
loops -- has no host to resolve against, so it is put near the things it
is wired to, in the nearest space nothing else has claimed.

The old engine ranked a free-standing balloon with the equipment, and
the signal into it was read as a step along the process: a controller
was pushed a full column east of its transmitter, and the loop it closed
became a cycle the flow graph then had to be torn to break. Placing it
here instead is what leaves no control loop in the flow graph at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# The gaps the coordinate pass left between one grid line and the next,
# which is what a grid line the sheet never used is worth (see
# :func:`_lane`). Imported rather than restated so the two cannot drift.
from pandid.layout.coordinates import COL_GAP, ROW_GAP

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.units import Unit

#: How far apart a free-standing balloon and anything already drawn are
#: kept, so a signal line has a lane to reach it by.
CLEARANCE = 30.0

#: The lattice a free spot is looked for on. Coarse enough that the
#: search over a crowded sheet is short, fine enough that a balloon does
#: not jump a whole column to dodge a line.
STEP = 25.0

#: How far the search may walk before it gives up and stacks the balloon
#: where it wanted to be. A sheet that full has a different problem, and
#: ``validate()`` reports the overlap.
REACH = 40


def place_control(fs: "Flowsheet") -> bool:
    """Place every balloon. True when one of them moved."""
    from pandid.layout.attach import place_attached

    moved = place_attached(fs)
    return _place_free(fs) or moved


def _place_free(fs: "Flowsheet") -> bool:
    """Put each hostless balloon beside what it is wired to."""
    from pandid.geometry import Frame
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size

    pending = [u for u in fs.units if is_control(u) and getattr(u, "host", None) is None]
    if not pending:
        return False

    taken = [u.frame for u in fs.units
             if u.frame is not None and u not in set(pending)]
    moved = False
    # Resolved in the order the sheet holds them, and a balloon wired
    # only to balloons still waiting is placed against whatever *is*
    # settled rather than deferred: a panel of controllers wired to each
    # other has no root to start from, and a sheet drawn late is better
    # than a sheet not drawn.
    for inst in pending:
        w, h = resolve_size(inst)
        x, y = _spot(fs, inst, w, h, taken)
        old = inst.frame
        if old is None or abs(old.x - x) > 0.01 or abs(old.y - y) > 0.01:
            moved = True
        pin = inst.pin_
        inst.frame = Frame(
            x=x, y=y, w=w, h=h, label_pos="center",
            # The rank :func:`_spot` actually stood the balloon in, and
            # only where it used one: an absolute coordinate on an axis
            # wins over the grid there, so recording the superseded
            # ``col`` would claim a lane the balloon may not be in.
            # Carried because the frame is the record of what was drawn
            # -- a balloon put in column 3 *is* in column 3 -- and
            # ``pin-not-honored`` reads it to tell a grid pin that was
            # honoured from one that was dropped on the floor.
            col=pin.col if pin is not None and pin.x is None else None,
            row=pin.row if pin is not None and pin.y is None else None,
            orientation=pin.orientation if pin else 0.0,
            mirrored=pin.mirrored if pin else False,
            mirror_y=pin.mirror_y if pin else False,
            # Faces chosen in layout ride across the re-place, for the
            # reason an attached balloon's do: re-deciding here would
            # move a nozzle the router has already drawn to.
            port_faces=dict(old.port_faces) if old is not None else {},
        )
        taken.append(inst.frame)
    return moved


def _spot(fs: "Flowsheet", inst: "Unit", w: float, h: float,
          taken: list["Frame"]) -> tuple[float, float]:
    """Where this balloon goes: the author's answer, or the nearest free.

    **A pin is an answer on the axis it names, and nothing at all on the
    axis it does not.** So ``pin(col=3)`` alone fixes the column and
    leaves the balloon free to step up or down to clear what is already
    drawn, and ``pin(col=3, row=1)`` is the whole answer and no search
    is made. That distinction is what the short-circuit here used to
    get wrong: it fired for ``pin.x``/``pin.y`` only, so a grid pin was
    computed exactly and then handed to :func:`_nearest_free`, which
    walked the balloon straight off the column it had been put in
    (#444).
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
    """Where the grid line the author named is, in pixels.

    ``None`` where no line was named, but **never** because the sheet
    did not happen to use that one: ``pin(col=7)`` on a three-column
    sheet is a column four past the last, and the old answer -- drop the
    pin and put the balloon by its wires instead -- silently drew
    something the author did not ask for. Beyond either end the grid is
    continued at its own average pitch, and a gap inside it is
    interpolated across, so a named line always resolves somewhere.

    A sheet with a single column has no pitch of its own to continue at,
    so that column's own box and the gap after it stand in.
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
    """The columns and rows stage 1 drew: where each starts, and how deep.

    The size is carried because :func:`_lane` needs a pitch to continue
    the grid past its last line, and a one-column sheet has none to
    measure.
    """
    cols: dict[int, tuple[float, float]] = {}
    rows: dict[int, tuple[float, float]] = {}
    for u in fs.units:
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
    """The middle of everything this balloon is wired to."""
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
    # Wired to nothing placed: stand it off the sheet's own bottom left,
    # where it is visible and in nothing's way.
    frames = [u.frame for u in fs.units if u.frame is not None and u is not inst]
    if not frames:
        return 0.0, 0.0
    return (min(f.x for f in frames), max(f.y_max for f in frames) + CLEARANCE * 2)


def _nearest_free(x: float, y: float, w: float, h: float, taken: list["Frame"],
                  free_x: bool, free_y: bool) -> tuple[float, float]:
    """The spot nearest ``(x, y)`` that no drawn box already holds.

    Walked as rings on a lattice so the answer is a function of the
    sheet and not of the order the rings happened to be generated in:
    within a ring the candidates are visited in a fixed order, and the
    first that clears everything wins.

    An axis the author pinned is not searched. A balloon pinned to a
    column steps *up and down* that column to find its room and never
    leaves it, which is what a column pin means; one pinned on both
    axes is placed where it was put, overlap and all, since the author
    has already answered and ``validate()`` reports what results.
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
    """The lattice points at Chebyshev distance ``radius``, clockwise."""
    if radius == 0:
        return [(0, 0)]
    out = [(dx, -radius) for dx in range(-radius, radius + 1)]
    out += [(radius, dy) for dy in range(-radius + 1, radius + 1)]
    out += [(dx, radius) for dx in range(radius - 1, -radius - 1, -1)]
    out += [(-radius, dy) for dy in range(radius - 1, -radius, -1)]
    return out


def _hits(x: float, y: float, w: float, h: float, taken: list["Frame"]) -> bool:
    """Would a box here touch anything already drawn?"""
    for frame in taken:
        if (x < frame.x_max + CLEARANCE and x + w + CLEARANCE > frame.x
                and y < frame.y_max + CLEARANCE and y + h + CLEARANCE > frame.y):
            return True
    return False
