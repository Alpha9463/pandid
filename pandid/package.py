"""Package units: bought-in equipment drawn inside one boundary frame.

:meth:`~pandid.flowsheet.Flowsheet.package` returns a :class:`Package`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.render.weights import M

if TYPE_CHECKING:
    from pandid.units import Unit

#: Clearance from a package's units and their tags to its frame.
MARGIN = 2 * M


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
