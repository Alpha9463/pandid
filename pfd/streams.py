"""Stream — a connection from one outlet Port to one inlet Port.

`name` is the stream number. On an auto-named stream the flowsheet owns it and
keeps it equal to what gets drawn; a name passed to `connect()` is never touched.
Setting any of `size`, `service`, `spec` or `insulation` turns that number into a
full line number (`6"-P-1001-A1A`), assembled by the flowsheet's
`line_numbering_scheme`. `kind` is "material" or "energy". `is_recycle` is
COMPUTED later by the layout engine's cycle-detection phase and must never be set
by API callers. `tear_hint` lets a caller nudge which stream is chosen as a
tear/back-edge in ambiguous cycles; it is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pfd.geometry import Route

if TYPE_CHECKING:
    from pfd.ports import Port
    from pfd.state import State

#: The parts of a line number, in the order a conventional scheme spells them.
LINE_NUMBER_FIELDS = ("size", "service", "sequence", "spec", "insulation")


@dataclass
class Stream:
    name: str
    source: Port
    dest: Port
    kind: str = "material"
    tear_hint: bool = False
    route: Route | None = None
    color: str | None = None
    dasharray: str | None = None
    auto_named: bool = True  # False if the caller passed an explicit name
    # Line-number components. The author supplies all but `sequence`, which
    # auto-numbering fills; see Flowsheet.renumber_streams().
    size: str | float | None = None
    service: str | float | None = None
    sequence: str | float | None = None
    spec: str | float | None = None
    insulation: str | float | None = None
    properties: dict[str, str | float] = field(default_factory=dict)
    state: State | None = None  # <- balance engine writes here later
    _is_recycle: bool = field(default=False, init=False, repr=False)
    # The sequence auto-numbering last wrote, so a value the author put there
    # instead is recognised and left alone however often numbering re-runs.
    _auto_sequence: str | None = field(default=None, init=False, repr=False)

    @property
    def is_recycle(self) -> bool:
        """True when layout()'s cycle-detection marked this stream a recycle
        (feedback / back-edge). Read-only: computed by the engine, never set by
        API callers.
        """
        return self._is_recycle

    @property
    def has_line_number(self) -> bool:
        """True when this line is identified by a line number rather than a
        stream number.

        Read-only. ``sequence`` alone does not count: auto-numbering fills it on
        every stream, and on its own it only renumbers, which
        ``stream_naming_scheme`` already does.
        """
        return any((self.size, self.service, self.spec, self.insulation))

    def line_components(self) -> dict[str, str]:
        """The line-number components as text, empty where the author left one
        unset. Unset components drop out of the formatted line number."""
        return {f: "" if getattr(self, f) is None else str(getattr(self, f))
                for f in LINE_NUMBER_FIELDS}

    def via(self, waypoints: list[tuple[float, float]]) -> "Stream":
        """Force the stream to route through these exact pixel waypoints."""
        if self.route is None:
            self.route = Route()
        self.route.waypoints = waypoints
        self.route.manual = True
        return self
