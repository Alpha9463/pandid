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
    """Where this balloon goes: the author's answer, or the nearest free."""
    pin = inst.pin_
    want = _wanted(fs, inst, w, h)
    x = pin.x if pin is not None and pin.x is not None else want[0]
    y = pin.y if pin is not None and pin.y is not None else want[1]
    if pin is not None and (pin.x is not None or pin.y is not None):
        return x, y  # an absolute pin is an answer, not a preference
    return _nearest_free(x, y, w, h, taken)


def _wanted(fs: "Flowsheet", inst: "Unit", w: float, h: float) -> tuple[float, float]:
    """The balloon's own idea of where it belongs, before collisions.

    The middle of what it is wired to, which is the only thing on the
    sheet that has anything to say about it -- a signal contributes no
    order along either axis, only this pull towards its peer. A pinned
    column or row is read against the grid stage 1 laid out, so
    ``pin(col=3)`` on a controller means the same column it means on a
    pump.
    """
    pin = inst.pin_
    if pin is not None and (pin.col is not None or pin.row is not None):
        grid = _grid(fs)
        if pin.col is not None and pin.col in grid[0]:
            gx = grid[0][pin.col]
        else:
            gx = None
        if pin.row is not None and pin.row in grid[1]:
            gy = grid[1][pin.row]
        else:
            gy = None
        if gx is not None or gy is not None:
            centre = _centroid(fs, inst)
            return (gx if gx is not None else centre[0] - w / 2.0,
                    gy if gy is not None else centre[1] - h / 2.0)
    cx, cy = _centroid(fs, inst)
    return cx - w / 2.0, cy - h / 2.0


def _grid(fs: "Flowsheet") -> tuple[dict[int, float], dict[int, float]]:
    """The columns and rows stage 1 drew, read back off its frames."""
    cols: dict[int, float] = {}
    rows: dict[int, float] = {}
    for u in fs.units:
        frame = u.frame
        if frame is None:
            continue
        col, row = frame.col, frame.row
        if col is not None:
            cols[col] = min(cols[col], frame.x) if col in cols else frame.x
        if row is not None:
            rows[row] = min(rows[row], frame.y) if row in rows else frame.y
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


def _nearest_free(x: float, y: float, w: float, h: float,
                  taken: list["Frame"]) -> tuple[float, float]:
    """The spot nearest ``(x, y)`` that no drawn box already holds.

    Walked as rings on a lattice so the answer is a function of the
    sheet and not of the order the rings happened to be generated in:
    within a ring the candidates are visited in a fixed order, and the
    first that clears everything wins.
    """
    for ring in range(REACH):
        for dx, dy in _ring(ring):
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
