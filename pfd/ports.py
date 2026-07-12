"""Port — a named nozzle on a unit; the attachment point for a stream.

A port belongs to exactly one unit, has a direction ("inlet"/"outlet") and a
role (e.g. "feed", "vapor", "energy"), and holds at most one stream. Named
port anchors are what the (future) router targets; roles/sides are hints the
(future) renderer and layout engine consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.state import State
    from pfd.streams import Stream
    from pfd.units import Unit


@dataclass
class Port:
    name: str
    owner: Unit | None = field(repr=False)
    direction: str  # "inlet" | "outlet"
    role: str
    side: str | None = None
    stream: Stream | None = field(default=None, repr=False)
    state: State | None = field(default=None, repr=False)  # <- balance engine writes here later
