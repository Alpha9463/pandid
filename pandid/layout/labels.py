"""Choose label sides for placed units."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_DIR_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}
#: Label sides in order of preference.
LABEL_SIDES = ("top", "bottom", "right", "left")


def free_label_sides(u) -> list[str]:
    """Return a placed unit's sides that no connected nozzle uses.

    Parameters
    ----------
    u : Unit
        Placed unit.

    Returns
    -------
    list[str]
        Free sides, in :data:`LABEL_SIDES` order.
    """
    from pandid.portgeom import port_anchor

    if u.frame is None:
        return []
    occupied = set()
    for name, port in u.ports.items():
        if port.stream is None:
            continue
        _, _, d = port_anchor(u, u.frame, name)
        occupied.add(d)
    return [side for side in LABEL_SIDES if _DIR_OF_SIDE[side] not in occupied]


def assign_labels(fs: "Flowsheet") -> None:
    """Set ``label_pos`` on every placed unit's frame but a flag's.

    An explicit ``label_pos`` wins, then the symbol's default, then the
    first side free of connected nozzles and of balloons moved off E
    (:func:`~pandid.layout.attach.free_face`), then ``"top"``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose units to label.
    """
    from pandid.layout.attach import free_face
    from pandid.render.symbols import default_registry
    from pandid.units import Instrument

    moved: dict[int, set[str]] = {}
    for inst in fs.units:
        face = free_face(inst) if isinstance(inst, Instrument) else None
        if face is not None:
            moved.setdefault(id(inst.host), set()).add(face)
    for u in fs.units:
        if u.kind in ("feed", "product") or u.frame is None:
            continue  # A boundary flag draws its own label.
        explicit = getattr(u, "label_pos", None)
        if explicit:
            u.frame.label_pos = explicit
            continue
        sym = default_registry.get(u.kind, getattr(u, "variant", "default"))
        if sym.label_pos:
            u.frame.label_pos = sym.label_pos
            continue
        free = [side for side in free_label_sides(u)
                if _DIR_OF_SIDE[side] not in moved.get(id(u), ())]
        u.frame.label_pos = free[0] if free else "top"
