"""Ports: named nozzles on a unit, each holding at most one stream.

A process stream runs from an outlet to an inlet. A signal port
carries signal lines only, in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.streams import Stream
    from pandid.units import Unit


@dataclass
class Port:
    """A named nozzle on a unit.

    Attributes
    ----------
    name : str
        Port name, unique on its unit.
    owner : Unit
        Unit the port belongs to, set by ``Unit._add_port``.
    direction : str
        ``"inlet"`` or ``"outlet"``.
    role : str
        Port role, such as ``"process"``, ``"feed"``, ``"vapor"``,
        ``"energy"`` or ``"signal"``.
    stream : Stream or None
        Connected stream, if any.
    """

    name: str
    owner: Unit = field(repr=False)
    direction: str
    role: str
    stream: Stream | None = field(default=None, repr=False)
