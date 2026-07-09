"""Stream — a connection from one outlet Port to one inlet Port.

`kind` is "material" or "energy". `is_recycle` is COMPUTED later by the layout
engine's cycle-detection phase and must never be set by API callers. `tear_hint`
lets a caller nudge which stream is chosen as a tear/back-edge in ambiguous
cycles; it is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pfd.geometry import Route

if TYPE_CHECKING:
    from pfd.ports import Port
    from pfd.state import State


@dataclass
class Stream:
    name: str
    source: Port
    dest: Port
    kind: str = "material"
    is_recycle: bool = False
    tear_hint: bool = False
    route: Route | None = None
    color: str | None = None
    dasharray: str | None = None
    properties: dict[str, str | float] = field(default_factory=dict)
    state: State | None = None  # <- balance engine writes here later

    def via(self, waypoints: list[tuple[float, float]]) -> "Stream":
        """Force the stream to route through these exact pixel waypoints."""
        if self.route is None:
            self.route = Route()
        self.route.waypoints = waypoints
        self.route.manual = True
        return self
