"""Reserve room around process units for the balloons attached to them.

A balloon on a stream reserves room on both units the stream joins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.layout.stages import slot
from pandid.portgeom import COMPASS

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: Clear space added around a balloon chain, in drawing units.
CLEARANCE = 80.0


class Pad(NamedTuple):
    """Clear space a unit needs on each side of its box.

    Attributes
    ----------
    north : float
        Space above the box.
    south : float
        Space below the box.
    east : float
        Space right of the box.
    west : float
        Space left of the box.
    """

    north: float = 0.0
    south: float = 0.0
    east: float = 0.0
    west: float = 0.0

    def widened(self, face: str, reach: float, girth: float = 0.0) -> "Pad":
        """Return a pad widened for something on one face.

        Parameters
        ----------
        face : str
            Compass face, ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
        reach : float
            Distance out from the face.
        girth : float, default=0.0
            Half-width across the face, reserved on the faces beside it.

        Returns
        -------
        Pad
            The widened pad.
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
    """Return the pad each unit needs for the balloons it hosts.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with seeded slots, whose ranks give a stream's direction.

    Returns
    -------
    dict[Unit, Pad]
        Pads keyed by host unit.
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
    """Return a chain's reach, girth, face and hosts, or None.

    Parameters
    ----------
    inst : Unit
        Balloon at the end of the chain.

    Returns
    -------
    tuple[float, float, str, list[Unit]] or None
        None for a closed chain, a free root balloon or ownerless end.
    """
    from pandid.layout.attach import _rotate_ccw
    from pandid.layout.stages import is_control
    from pandid.portgeom import resolve_size
    from pandid.streams import Stream

    reach, girth, node, root = 0.0, 0.0, inst, inst
    # Sum the chain's reach; its direction is the root link's. ``seen``
    # stops a chain that closes on itself.
    seen: set[int] = set()
    while is_control(node) and getattr(node, "host", None) is not None:
        if id(node) in seen:
            return None
        seen.add(id(node))
        w, h = resolve_size(node)
        reach += float(getattr(node, "offset", 0.0)) + max(w, h) / 2.0
        girth = max(girth, max(w, h) / 2.0)
        root, node = node, getattr(node, "host")
    reach += CLEARANCE
    girth += CLEARANCE

    if isinstance(node, Stream):
        src, dst = node.source.owner, node.dest.owner
        if src is None or dst is None:
            return None
        across = (slot(dst).col or 0) - (slot(src).col or 0)
        down = (slot(dst).row or 0) - (slot(src).row or 0)
        flow = ((1.0 if across > 0 else -1.0, 0.0) if across
                else (0.0, 1.0 if down >= 0 else -1.0))
        hosts = [src] if src is dst else [src, dst]
    elif is_control(node):
        return None
    else:
        nx, ny = COMPASS[getattr(root, "face", None) or "E"]
        flow = (-ny, nx)  # the face's tangent
        hosts = [node]

    ux, uy = _rotate_ccw(flow[0], flow[1], float(getattr(root, "angle", 90.0)))
    face = "E" if ux >= abs(uy) else ("W" if -ux >= abs(uy) else ("N" if uy < 0 else "S"))
    return reach, girth, face, hosts
