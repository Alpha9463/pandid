"""Reserve room around process units for the balloons attached to them.

Stage 1 places equipment before stage 2 places instruments, so each
unit's footprint is widened by the balloon chains that hang on it: the
balloon, the transmitter beside it, the controller beside that. A chain's
reach is known before drawing because it depends only on its host, face
or fraction, offsets and angle.

A balloon on a stream is charged to both units the stream joins, because
where it lands along the run is not known yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: Clear space added around a balloon chain, in drawing units. It must
#: hold two lines of lettering and a run between them: the balloon's tag
#: and a neighbour's, such as a control valve's fail position. Smaller
#: values put lettering on neighbouring tags or lines in
#: ``tests/test_halo_invariants.py`` and ``tests/test_render.py``.
CLEARANCE = 80.0


class Pad(NamedTuple):
    """Clear space a unit needs on each side of its box.

    Attributes
    ----------
    north, south, east, west : float
        Clearance beyond the box on each side, in drawing units.
    """

    north: float = 0.0
    south: float = 0.0
    east: float = 0.0
    west: float = 0.0

    def widened(self, face: str, reach: float, girth: float = 0.0) -> "Pad":
        """Return a pad widened for something on one face.

        The reach extends the named face; the girth extends the two faces
        beside it, so a balloon wider than its host fits beside it.

        Parameters
        ----------
        face : str
            ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
        reach : float
            Distance out from the face.
        girth : float, default=0.0
            Half-width across the face.

        Returns
        -------
        Pad
            Pad no smaller than this one on any side.
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
    """Return the clearance each process unit must leave for its balloons.

    Called after grid ranks are settled and before pixel coordinates,
    because a stream's direction is read from its ends' ranks.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with settled grid ranks.

    Returns
    -------
    dict[Unit, Pad]
        Pad for each unit that hosts at least one balloon chain.
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
    """Measure one attached balloon chain and the units that host it.

    Parameters
    ----------
    inst : Unit
        Attached instrument at the outer end of a chain.

    Returns
    -------
    tuple[float, float, str, list[Unit]] or None
        Reach, girth and face of the chain, and the units that reserve the
        room; ``None`` for a chain that closes on itself or hangs on a
        stream with an unowned end.
    """
    from pandid.layout.attach import _rotate_ccw
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size
    from pandid.streams import Stream

    reach, girth, node, root = 0.0, 0.0, inst, inst
    # Sum the whole chain's reach. Its direction is the root link's, the
    # only one measured from the host. ``seen`` stops a chain that closes
    # on itself; place_attached reports such balloons unplaced.
    seen: set[int] = set()
    while is_control(node) and getattr(node, "host", None) is not None:
        if id(node) in seen:
            return None
        seen.add(id(node))
        w, h = resolve_size(node)
        reach += float(getattr(node, "offset", 0.0)) + max(w, h) / 2.0
        girth = max(girth, max(w, h) / 2.0)
        # The host may be a balloon, a unit or a stream, so read it with getattr.
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
    """Return the outward unit normal of a face.

    Parameters
    ----------
    face : str
        Compass face; anything else is treated as ``"E"``.

    Returns
    -------
    tuple[float, float]
        Normal on the y-down canvas.
    """
    return {"N": (0.0, -1.0), "S": (0.0, 1.0),
            "W": (-1.0, 0.0), "E": (1.0, 0.0)}.get(face.upper(), (1.0, 0.0))


def _run_direction(src: "Unit", dst: "Unit") -> tuple[float, float]:
    """Return the direction a stream runs, from its ends' grid ranks.

    A stream that changes column runs along the sheet; one that does not
    runs down or up it.

    Parameters
    ----------
    src, dst : Unit
        Source and destination units with settled ranks.

    Returns
    -------
    tuple[float, float]
        Unit direction on the y-down canvas.
    """
    across = (slot(dst).col or 0) - (slot(src).col or 0)
    if across:
        return (1.0 if across > 0 else -1.0, 0.0)
    down = (slot(dst).row or 0) - (slot(src).row or 0)
    return (0.0, 1.0 if down >= 0 else -1.0)
