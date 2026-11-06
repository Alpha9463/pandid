"""Package units: bought-in equipment drawn inside one boundary frame.

:meth:`~pandid.flowsheet.Flowsheet.package` returns a :class:`Package`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.render.weights import M

if TYPE_CHECKING:
    from pandid.units import Unit

Box = tuple[float, float, float, float]

#: Clearance from a package's units to the sides of its frame.
MARGIN = 2 * M

#: Clearance from a package's units to the top and foot of its frame,
#: room for a tag above or below a unit included.
DEPTH = MARGIN + 2.5 * M

#: Further depth at the foot of a frame that holds a reference.
REFERENCE_ROOM = 1.5 * M

#: Inset of the reference from the frame's lower-left corner.
INSET = 0.5 * M


class Package:
    """A package unit, such as a vendor skid.

    It is drawn as a boundary frame round its units (ISO 15519-1 7.3)
    and has no ports or place of its own.

    Parameters
    ----------
    name : str
        Package tag, such as ``"PK-301"``.
    units : tuple[Unit, ...]
        Units inside the frame.
    description : str, default=""
        Equipment-list description.
    reference : str, default=""
        Document the frame refers to, drawn inside it.

    Attributes
    ----------
    name : str
        Package tag.
    units : tuple[Unit, ...]
        Units inside the frame, in the order given.
    description : str
        Equipment-list description.
    reference : str
        Document the frame refers to.
    """

    def __init__(self, name: str, units: tuple[Unit, ...], description: str = "",
                 reference: str = ""):  # numpydoc ignore=GL08
        self.name = name
        self.units = units
        self.description = description
        self.reference = reference

    def __repr__(self) -> str:
        """Return the package's tag and unit names.

        Returns
        -------
        str
            Representation.
        """
        return f"Package({self.name!r}, {[u.name for u in self.units]!r})"


def text_width(pkg: Package) -> float:
    """Return the width a package's tag and reference take along its frame.

    Parameters
    ----------
    pkg : Package
        Package being framed.

    Returns
    -------
    float
        The wider of the tag above the frame and the reference inside
        it, with its insets.
    """
    from pandid.portgeom import tag_width

    inside = tag_width(str(pkg.reference)) + 2 * INSET if pkg.reference else 0.0
    return max(tag_width(pkg.name), inside)


def boundary(pkg: Package, boxes: list[Box]) -> Box:
    """Return the boundary frame round some of a package's unit boxes.

    The frame keeps :data:`MARGIN` from the boxes at its sides and
    :data:`DEPTH` at its top and foot (ISO 15519-1 7.3.1), and is deep
    and wide enough to hold the reference at its foot.

    Parameters
    ----------
    pkg : Package
        Package being framed.
    boxes : list[Box]
        Boxes of its units, as left, top, right, bottom; not empty.

    Returns
    -------
    Box
        The frame as left, top, right, bottom.
    """
    from pandid.portgeom import tag_width

    x0 = min(b[0] for b in boxes) - MARGIN
    x1 = max(b[2] for b in boxes) + MARGIN
    y1 = max(b[3] for b in boxes) + DEPTH
    if pkg.reference:
        x1 = max(x1, x0 + tag_width(str(pkg.reference)) + 2 * INSET)
        y1 += REFERENCE_ROOM
    return (x0, min(b[1] for b in boxes) - DEPTH, x1, y1)


def tag_reach(unit: Unit) -> float:
    """Return how far a tag laid out beside a unit reaches from it.

    Parameters
    ----------
    unit : Unit
        Unit whose tag is drawn outside it.

    Returns
    -------
    float
        Reach from the unit's side, or 0 for a unit whose tag is drawn
        inside it.
    """
    from pandid.render.svg import SvgRenderer, _unit_label_box

    if not unit.tag or unit.kind in ("feed", "product", "instrument"):
        return 0.0
    spot = SvgRenderer()._label_place("right", 0.0, 0.0, 0.0, 0.0)
    box = _unit_label_box((*spot, "right", unit.tag))
    return 0.0 if box is None else box[2]


def frame(pkg: Package) -> Box | None:
    """Return a package's boundary frame as drawn.

    It is the :func:`boundary` round its units' boxes and the tags laid
    out beside them.

    Parameters
    ----------
    pkg : Package
        Package to frame.

    Returns
    -------
    Box or None
        The frame as left, top, right, bottom, or ``None`` if a unit
        has no frame.
    """
    from pandid.portgeom import unit_box

    boxes = []
    for u in pkg.units:
        f = u.frame
        if f is None:
            return None
        x0, y0, x1, y1 = unit_box(u, f)
        if f.label_pos == "left":
            x0 = min(x0, f.x - tag_reach(u))
        elif f.label_pos == "right":
            x1 = max(x1, f.x + f.w + tag_reach(u))
        boxes.append((x0, y0, x1, y1))
    return boundary(pkg, boxes)
