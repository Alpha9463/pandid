"""The space a process unit has to leave for the balloons hung on it.

Stage 1 places the equipment and stage 2 places the instrumentation
against it. If stage 1 packs the boxes as though the sheet were empty,
stage 2 packs into space that is already gone -- which is a bubble drawn
over the vessel it reads (#428), and it gets worse exactly as a sheet
gets more instrumented.

So a unit's *effective* footprint is its own box plus whatever hangs off
it: the balloon on its crown, the transmitter beside that, the
controller beside that again. The demand is computable before anything
is drawn, because a balloon's position is its host, a face or a
fraction, an offset and an angle, and only the first of those is
unknown at this point.

A balloon on a **stream** is charged to both of the units that stream
joins. Where the tap lands along the run is not known yet, so the run
is treated as though the balloon could be anywhere on it; over-reserving
the two ends is the safe direction, and the alternative -- reserving
nothing and finding out afterwards -- is the defect this exists to stop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: How much clear paper a balloon wants around it. Not a hairline: what
#: has to fit in the gap between a bubble and whatever the grid packs
#: against it is **two lines of lettering and a pipe** -- the bubble's
#: own tag, the neighbour's (a control valve writes its fail position
#: under its body, outside the box the grid laid out for it, and the
#: layout has no way to ask where), and whatever run the router then
#: threads between the two.
#:
#: Reserved at 20, ``18_fixed_bed_recycle``'s flow controller came to
#: rest four units under ``XV-307``'s "FC"; at 50 the same lettering
#: landed on the loop-gas line running under it. Both were reported --
#: by ``tests/test_halo_invariants.py`` and ``tests/test_render.py`` --
#: rather than found by looking, which is what says this is a *width*
#: and not a taste.
CLEARANCE = 80.0


class Pad(NamedTuple):
    """Clear space one unit needs on each side of its own box."""

    north: float = 0.0
    south: float = 0.0
    east: float = 0.0
    west: float = 0.0

    def widened(self, face: str, reach: float, girth: float = 0.0) -> "Pad":
        """Room for something ``reach`` out on ``face``, ``girth`` across.

        The girth goes on the other two faces. A balloon standing north
        of an orifice plate is forty units wide and the plate is twelve,
        so reserving only the run up to it reserves a corridor the
        balloon does not fit down -- and what it overlaps is whatever
        the next column put beside it.
        """
        n, s, e, w = self
        if face in ("N", "S"):
            e, w = max(e, girth), max(w, girth)
            n = max(n, reach) if face == "N" else n
            s = max(s, reach) if face == "S" else s
        else:
            n, s = max(n, girth), max(s, girth)
            e = max(e, reach) if face == "E" else e
            w = max(w, reach) if face == "W" else w
        return Pad(n, s, e, w)


def balloon_pads(fs: "Flowsheet") -> dict["Unit", Pad]:
    """What each process unit must leave clear, by side.

    Read after the ranks are settled and before pixels are handed out,
    which is the one point at which a stream's direction is known (from
    the columns and rows its ends landed in) and nothing has yet been
    placed against it.
    """
    from pandid.layout.stages import is_control

    pads: dict["Unit", Pad] = {}
    for inst in fs.units:
        if not is_control(inst) or getattr(inst, "host", None) is None:
            continue
        charge = _charge(inst)
        if charge is None:
            continue
        reach, girth, face, hosts = charge
        for host in hosts:
            pads[host] = pads.get(host, Pad()).widened(face, reach, girth)
    return pads


def _charge(inst: "Unit") -> tuple[float, float, str, list["Unit"]] | None:
    """How far this balloon reaches, how wide it is, and who pays."""
    from pandid.layout.attach import _rotate_ccw
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size
    from pandid.streams import Stream

    reach, girth, node, root = 0.0, 0.0, inst, inst
    # Balloons chain -- an interlock under a controller beside a
    # transmitter -- and each link stands its own offset further out, so
    # what the sheet has to reserve is the whole chain and not the last
    # link of it. Which way the chain leaves is the *root* link's
    # question: it is the only one measured against the host that pays.
    #
    # ``seen`` is what stops a chain that closes on itself: two balloons
    # hung on each other is a model nothing can place (see
    # :func:`~pandid.layout.attach.place_attached`, which reports them
    # unplaced), and reserving paper for it must not be the thing that
    # hangs the run.
    seen: set[int] = set()
    while is_control(node) and getattr(node, "host", None) is not None:
        if id(node) in seen:
            return None
        seen.add(id(node))
        w, h = resolve_size(node)
        reach += float(getattr(node, "offset", 0.0)) + max(w, h) / 2.0
        girth = max(girth, max(w, h) / 2.0)
        # ``host`` lives on Instrument rather than on Unit, and what the
        # walk holds is whatever the last host was -- a balloon, a unit
        # or a stream -- so it is read off the object and not the class.
        root, node = node, getattr(node, "host")
    reach += CLEARANCE
    girth += CLEARANCE

    if isinstance(node, Stream):
        src, dst = node.source.owner, node.dest.owner
        if src is None or dst is None:
            return None
        flow = _run_direction(src, dst)
        hosts = [src] if src is dst else [src, dst]
    elif is_control(node):
        return None  # a chain that closes on itself: nothing to charge
    else:
        nx, ny = _face_normal(str(getattr(root, "at", None) or "E"))
        flow = (-ny, nx)  # the face's tangent, as attach() measures from
        hosts = [node]

    ux, uy = _rotate_ccw(flow[0], flow[1], float(getattr(root, "angle", 90.0)))
    face = "E" if ux >= abs(uy) else ("W" if -ux >= abs(uy) else ("N" if uy < 0 else "S"))
    return reach, girth, face, hosts


def _face_normal(face: str) -> tuple[float, float]:
    return {"N": (0.0, -1.0), "S": (0.0, 1.0),
            "W": (-1.0, 0.0), "E": (1.0, 0.0)}.get(face.upper(), (1.0, 0.0))


def _run_direction(src: "Unit", dst: "Unit") -> tuple[float, float]:
    """Which way a run travels, read off the ranks its ends landed in.

    The columns and rows are settled by the time this is asked, and the
    pixels are not, so this is the only description of the run that
    exists yet. A run that changes column is drawn along the sheet
    whatever else it does; one that does not is drawn down it.
    """
    across = (slot(dst).col or 0) - (slot(src).col or 0)
    if across:
        return (1.0 if across > 0 else -1.0, 0.0)
    down = (slot(dst).row or 0) - (slot(src).row or 0)
    return (0.0, 1.0 if down >= 0 else -1.0)
