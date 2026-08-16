"""Stream: a connection from one outlet Port to one inlet Port.

`name` is the stream number. On an auto-named stream the flowsheet owns
it and keeps it equal to what gets drawn; a name passed to `connect()`
is never touched. Setting any of `size`, `schedule`, `service`, `spec`
or `insulation` turns that number into a full line number
(`6"-P-1001-A1A`), assembled by the flowsheet's `line_numbering_scheme`.
`kind` is one of `STREAM_KINDS`: a process kind ("material"/"energy") on
a pipe, a signal kind on an instrument line. `is_recycle` is COMPUTED
later by the layout engine's cycle-detection phase and must never be set
by API callers. `draw_as_recycle` lets a caller nudge which stream is
chosen as a tear/back-edge in ambiguous cycles; it is advisory only.
`color` and `dasharray` are checked as they are set -- see
`check_color` -- because they are instructions to the renderer rather
than lettering, and an instruction it cannot read is dropped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.state import State

#: The parts of a line number, in the order a conventional scheme spells
#: them. ``schedule`` sits next to ``size`` because it qualifies it: the
#: two together are the bore and the wall, and the issued reference
#: sheet writes them side by side (``FB-301-200-160-SS`` is service,
#: sequence, DN 200, schedule 160, 316L).
#:
#: The list is fixed rather than open: a component nothing else on the
#: sheet can spell is one the drawing cannot be checked against. An
#: author who wants a fact of their own writes a callable
#: ``line_numbering_scheme``. See issue #118 before adding a seventh.
LINE_NUMBER_FIELDS = ("size", "schedule", "service", "sequence", "spec", "insulation")

#: Kinds that carry process fluid or duty: what a pipe on the sheet
#: holds.
PROCESS_KINDS = frozenset({"material", "energy"})

#: Kinds that carry a measurement or a command instead of a fluid.
#: ISA-5.1 gives each its own line style, and `Flowsheet.connect()`
#: pairs them with the signal-role ports that are the only things they
#: may run between.
SIGNAL_KINDS = frozenset({"electric", "pneumatic", "data", "capillary", "software"})

#: Every kind `connect()` accepts.
STREAM_KINDS = PROCESS_KINDS | SIGNAL_KINDS

#: A colour, in the three shapes SVG writes one: a keyword (a named
#: colour, or ``none``/``currentColor``/``transparent``/``inherit``), a
#: hex triple in any of its four lengths, or a colour function over
#: numbers. Deliberately a *shape* check and not a list of the 148 CSS
#: names -- ``rebeccapurple`` is a colour and so is whatever CSS names
#: next, and a library that ships the list has to keep shipping it.
#:
#: What the shape rules out is the point: no quote, angle bracket or
#: ampersand can appear in a value that matches, so nothing that gets
#: past here can close an SVG attribute; and no ``;`` or ``=`` can,
#: which is what keeps it from opening a second key in the ``style=``
#: string the draw.io export writes it into.
#:
#: ``url(#...)`` is not admitted although SVG accepts it as a paint: the
#: library defines no gradient or pattern for one to name, so it could
#: only ever dangle.
_COLOR = re.compile(
    r"""\A(?:
        [A-Za-z][A-Za-z0-9-]*                        # a keyword
      | \#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})
      | (?:rgb|rgba|hsl|hsla)\( [0-9.,%/ +-]* \)     # a colour function
    )\Z""",
    re.VERBOSE,
)

#: One number in a dash pattern. Unitless: everything in this library is
#: in drawing units, and the draw.io export translates the pattern into
#: draw.io's own unitless list (see ``pandid.render.drawio._dash``), so a
#: length carrying ``px`` or ``%`` would come out right on one backend
#: and wrong on the other.
_DASH_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"

#: A dash pattern, as SVG spells one: ``none``, or lengths separated by
#: commas and/or spaces.
_DASHARRAY = re.compile(rf"\A(?:none|{_DASH_NUMBER}(?:[, ]+{_DASH_NUMBER})*)\Z")


def _names(stream: "Stream | None") -> str:
    """``"S-1: "`` for a stream that carries a number, else nothing.

    A stream is checked as it is built, before auto-numbering has given
    it one, so the line cannot always be named -- but the field always
    can, and that is what a message has to carry.
    """
    name = getattr(stream, "name", "") if stream is not None else ""
    return f"{name}: " if name else ""


def check_color(value: str, stream: "Stream | None" = None) -> None:
    """Refuse a ``color`` that is not a colour.

    Refused rather than escaped, which is the choice the rest of this
    library makes about a value that is wrong rather than merely
    awkward. Escaping ``black" onload="alert(1)`` yields a well-formed
    document whose ``stroke`` is a string no renderer recognises, and an
    unrecognised paint is *ignored*: the line is drawn with no stroke
    and vanishes off the sheet, silently, on a drawing whose whole job
    is to say what is connected to what. A refusal names the field and
    the line; a missing pipe names nothing.

    What is checked is the *shape*, which is the part that decides
    whether the value is safe to write. A misspelled keyword --
    ``"blck"`` -- still gets through and still draws nothing: catching
    that means shipping and maintaining the 148 CSS colour names, and it
    is a typo rather than an injection. It belongs with the rest of the
    sheet's spelling checks in :mod:`pandid.validate`, not here.
    """
    if _COLOR.match(value):
        return
    raise ValueError(
        f"{_names(stream)}color={value!r} is not a colour. Write one the way SVG "
        f"writes one: a name ('black'), a hex triple ('#0a7', '#00aa77') or a "
        f"colour function ('rgb(0, 170, 119)'). Anything else reaches the drawing "
        f"as a paint no renderer recognises, and an unrecognised paint is ignored "
        f"-- the line is drawn with no stroke at all and disappears."
    )


def check_dasharray(value: str, stream: "Stream | None" = None) -> None:
    """Refuse a ``dasharray`` that is not a dash pattern.

    For the reason :func:`check_color` refuses a colour, and with a
    sharper edge: an unrecognised ``stroke-dasharray`` is ignored too,
    and the line is then drawn **solid**. A signal line that comes out
    solid does not go missing, it reads as a pipe.
    """
    if _DASHARRAY.match(value):
        return
    raise ValueError(
        f"{_names(stream)}dasharray={value!r} is not a dash pattern. Write lengths "
        f"in drawing units, separated by commas or spaces ('7,4', '9 3 2 3'), or "
        f"'none' for a solid line. Anything else is ignored by the renderer and "
        f"the line comes out solid, which on a signal line reads as a pipe."
    )


@dataclass
class Stream:
    name: str
    source: Port
    dest: Port
    kind: str = "material"
    draw_as_recycle: bool = False
    route: Route | None = None
    color: str | None = None
    dasharray: str | None = None
    # How this line's two joints are made up, overriding the sheet's
    # `connections` for this run alone. One name for both ends, or a
    # (source, dest) pair in connection order. None inherits, which lets
    # one flanged line sit on an unmarked sheet. Resolved by
    # pandid.render.svg.resolve_connections(), which also holds the
    # P&ID-only rule that outranks all of this.
    ends: "str | tuple[str, str] | None" = None
    auto_named: bool = True  # False if the caller named it
    # Line-number components. The author supplies all but `sequence`,
    # which auto-numbering fills; see Flowsheet.renumber_streams().
    size: str | float | None = None
    # The wall the line is bought to, at the size above. A schedule
    # number (40, 80, 160) or one of the older STD/XS/XXS names, so it
    # is not numeric and takes the same union as the components either
    # side of it.
    schedule: str | float | None = None
    service: str | float | None = None
    sequence: str | float | None = None
    spec: str | float | None = None
    insulation: str | float | None = None
    properties: dict[str, str | float] = field(default_factory=dict)
    state: State | None = None  # <- balance engine writes here later
    _is_recycle: bool = field(default=False, init=False, repr=False)
    # The sequence auto-numbering last wrote, so a value the author put
    # there instead is recognised and left alone however often numbering
    # re-runs.
    _auto_sequence: str | None = field(default=None, init=False, repr=False)

    #: The two fields that are checked as they are written, and why they
    #: are the only two. Everything else on a stream is *lettering* --
    #: it reaches the sheet as words, and words are escaped on the way
    #: out (see :mod:`pandid.render.escape`), so a strange one draws
    #: strangely and no more. These two are *instructions to the
    #: renderer*, and an instruction the renderer cannot read is not
    #: drawn strangely, it is dropped: a bad colour takes the line with
    #: it, a bad dash makes a signal read as a pipe. Neither failure
    #: reaches the author, which is what makes checking here worth the
    #: refusal.
    _CHECKED = {"color": check_color, "dasharray": check_dasharray}

    def __setattr__(self, name: str, value) -> None:
        check = self._CHECKED.get(name)
        if check is not None and value is not None:
            check(str(value), self)
        object.__setattr__(self, name, value)

    @property
    def is_recycle(self) -> bool:
        """True when layout() marked this stream a recycle back-edge.

        Read-only: computed by the engine, never set by API callers.
        """
        return self._is_recycle

    @property
    def has_line_number(self) -> bool:
        """True when a line number rather than a stream number names it.

        Read-only. ``sequence`` alone does not count: auto-numbering
        fills it on every stream, and on its own it only renumbers,
        which ``stream_naming_scheme`` already does.
        """
        return any((self.size, self.schedule, self.service, self.spec, self.insulation))

    def line_components(self) -> dict[str, str]:
        """The line-number components as text, empty where unset.

        Unset components drop out of the formatted line number.
        """
        return {f: "" if getattr(self, f) is None else str(getattr(self, f))
                for f in LINE_NUMBER_FIELDS}

    def via(self, waypoints: list[tuple[float, float]]) -> "Stream":
        """Route the stream through these exact pixel waypoints."""
        if self.route is None:
            self.route = Route()
        self.route.waypoints = waypoints
        self.route.manual = True
        return self
