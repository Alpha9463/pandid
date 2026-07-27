"""Port — a named nozzle on a unit; the attachment point for a stream.

A port belongs to exactly one unit, has a direction ("inlet"/"outlet") and a
role (e.g. "feed", "vapor", "energy"), and holds at most one stream. Named port
anchors are what the (future) router targets; roles/sides are hints the (future)
renderer and layout engine consume.

The role "signal" is the one that also decides what may be connected: a signal
port carries a signal line and a process port carries fluid, and
`Flowsheet.connect()` will not mix them.
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
    name: str
    owner: Unit = field(repr=False)  # always set by Unit._add_port(owner=self)
    direction: str  # "inlet" | "outlet"
    role: str
    side: str | None = None
    stream: Stream | None = field(default=None, repr=False)
    state: State | None = field(default=None, repr=False)  # <- balance engine writes here later
