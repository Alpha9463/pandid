"""Port: a named nozzle on a unit, the attachment point for a stream.

A port belongs to exactly one unit, has a direction ("inlet"/"outlet") and a
role (e.g. "feed", "vapor", "energy"), and holds at most one stream. The router
targets a port by name, and the renderer and the layout engine read its role.
`side` is read by none of the three and passed by no call site of `_add_port`;
it is a field waiting on a decision rather than a hint anything consumes.

The role "signal" is the one that also decides what may be connected: a signal
port carries a signal line and a process port carries fluid, and
`Flowsheet.connect()` will not mix them.

`direction` is a rule about process nozzles only. Fluid enters a nozzle or
leaves it, so a pipe drawn the other way is wrong about the plant and
`Flowsheet.connect()` refuses it. A signal connection has no such fact to be
right about -- the same alarm terminal is fed on one sheet and trips from it on
another -- so it is not held to the field, and which end of its line it took is
read off `Stream.source`/`Stream.dest`, which is exact because a port holds at
most one stream. On a signal port the field records which pool the connection
came from and nothing more; see `pandid.units.Instrument`.
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
