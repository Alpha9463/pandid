"""Choose each unit's label side, after faces are selected.

A label avoids the faces nozzles use, so this runs after
:mod:`pandid.layout.faces`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

_DIR_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}
#: Label sides in order of preference.
LABEL_SIDES = ("top", "bottom", "right", "left")


def free_label_sides(u) -> list[str]:
    """Return the sides of a unit that no connected nozzle uses.

    Parameters
    ----------
    u : Unit
        Placed unit.

    Returns
    -------
    list[str]
        Free sides in order of preference; empty for an unplaced unit.
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
    """Choose a label side for every placed unit.

    An explicit ``label_pos`` wins, then the symbol's default, then the
    first side free of connected nozzles.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed frames and selected port faces.

    Returns
    -------
    None
        ``label_pos`` is stored on each frame.
    """
    from pandid.render.symbols import default_registry

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
        free = free_label_sides(u)
        u.frame.label_pos = free[0] if free else "top"
