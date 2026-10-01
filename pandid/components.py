"""Define an entry in a flowsheet's chemical species list.

No property data is attached; a future balance backend can add it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Component:
    """A chemical species registered on a flowsheet.

    Attributes
    ----------
    name : str
        Species name.
    formula : str or None
        Chemical formula.
    """

    name: str
    formula: str | None = None
