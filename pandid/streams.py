"""Stream: a connection from one outlet Port to one inlet Port.

`name` is the stream number. On an auto-named stream the flowsheet owns it and
keeps it equal to what gets drawn; a name passed to `connect()` is never touched.
Setting any of `size`, `schedule`, `service`, `spec` or `insulation` turns that
number into a full line number (`6"-P-1001-A1A`), assembled by the flowsheet's
`line_numbering_scheme`. `kind` is one of `STREAM_KINDS`: a process kind
("material"/"energy") on a pipe, a signal kind on an instrument line. `is_recycle` is
COMPUTED later by the layout engine's cycle-detection phase and must never be set
by API callers. `tear_hint` lets a caller nudge which stream is chosen as a
tear/back-edge in ambiguous cycles; it is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.state import State

#: The parts of a line number, in the order a conventional scheme spells them.
#: ``schedule`` sits next to ``size`` because it qualifies it: the two together
#: are the bore and the wall, and the issued reference sheet writes them side by
#: side (``FB-301-200-160-SS`` is service, sequence, DN 200, schedule 160, 316L).
#:
#: The list is deliberately fixed rather than open. A line number identifies a
#: line to the line list, and a component nothing else on the sheet can spell is
#: a component the drawing cannot be checked against; an author who wants a fact
#: of their own writes a callable ``line_numbering_scheme``. The trigger to add
#: a seventh here is a *second* real sheet needing a component this list lacks,
#: which is what issue #118 records the reasoning for.
LINE_NUMBER_FIELDS = ("size", "schedule", "service", "sequence", "spec", "insulation")

#: Kinds that carry process fluid or duty: what a pipe on the sheet holds.
PROCESS_KINDS = frozenset({"material", "energy"})

#: Kinds that carry a measurement or a command instead of a fluid. ISA-5.1 gives
#: each its own line style, and `Flowsheet.connect()` pairs them with the
#: signal-role ports that are the only things they may run between.
SIGNAL_KINDS = frozenset({"electric", "pneumatic", "data", "capillary", "software"})

#: Every kind `connect()` accepts.
STREAM_KINDS = PROCESS_KINDS | SIGNAL_KINDS


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
    # The wall the line is bought to, at the size above. A schedule number
    # (40, 80, 160) or one of the older STD/XS/XXS names, so it is not numeric
    # and takes the same union as the components either side of it.
    schedule: str | float | None = None
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
        return any((self.size, self.schedule, self.service, self.spec, self.insulation))

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
