"""Define a port: a named nozzle on a unit where one stream attaches.

A port belongs to one unit and holds at most one stream. A process port
has a direction that :meth:`pandid.flowsheet.Flowsheet.connect` enforces:
a process stream runs from an outlet to an inlet. A signal port carries
signal lines only, and ``connect()`` will not join a signal port to a
process port. A signal connection is not held to the port's direction;
which end it took is read from the stream's ``source`` and ``dest``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.state import State
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
    state : State or None
        Stream conditions for a future balance engine.
    """

    name: str
    owner: Unit = field(repr=False)
    direction: str
    role: str
    stream: Stream | None = field(default=None, repr=False)
    state: State | None = field(default=None, repr=False)
