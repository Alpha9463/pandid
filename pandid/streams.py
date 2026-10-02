"""Define a stream: a connection from one port to another.

A stream's ``name`` is its stream number; the flowsheet keeps an
automatically named stream's number current and never changes a name
given to ``connect()``. Setting any of ``size``, ``schedule``,
``service``, ``spec`` or ``insulation`` turns the number into a line
number built by the flowsheet's ``line_numbering_scheme``.

``kind`` is one of :data:`STREAM_KINDS`. ``is_recycle`` is computed by
layout and read-only; ``draw_as_recycle`` only advises which stream of a
cycle to treat as the return. ``color`` and ``dasharray`` are validated
when set, because the renderer silently ignores a value it cannot read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pandid._checks import check_real
from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.state import State

#: Line-number components, in conventional order. ``schedule`` follows
#: ``size`` because together they give the bore and the wall. The set is
#: fixed; a different format needs a callable ``line_numbering_scheme``.
LINE_NUMBER_FIELDS = ("size", "schedule", "service", "sequence", "spec", "insulation")

#: Kinds that carry process fluid or duty.
PROCESS_KINDS = frozenset({"material", "energy"})

#: Kinds that carry a measurement or command, each with its own ISA-5.1
#: line style. They may only join signal-role ports.
SIGNAL_KINDS = frozenset({"electric", "pneumatic", "data", "capillary", "software"})

#: Every kind ``connect()`` accepts.
STREAM_KINDS = PROCESS_KINDS | SIGNAL_KINDS

#: Accepted colour shapes: a keyword, a hex colour of 3, 4, 6 or 8 digits,
#: or an ``rgb``/``rgba``/``hsl``/``hsla`` function over numbers. The shape
#: excludes quotes, angle brackets, ampersands, ``;`` and ``=``, so a value
#: cannot break out of an SVG attribute or a draw.io style string.
#: ``url(#...)`` is excluded because no gradient or pattern is defined.
_COLOR = re.compile(
    r"""\A(?:
        [A-Za-z][A-Za-z0-9-]*                        # a keyword
      | \#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})
      | (?:rgb|rgba|hsl|hsla)\( [0-9.,%/ +-]* \)     # a colour function
    )\Z""",
    re.VERBOSE,
)

#: One unitless number in a dash pattern, in drawing units, which the
#: draw.io export can translate.
_DASH_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"

#: A dash pattern: ``none``, or lengths separated by commas or spaces.
_DASHARRAY = re.compile(rf"\A(?:none|{_DASH_NUMBER}(?:[, ]+{_DASH_NUMBER})*)\Z")


def _names(stream: "Stream | None") -> str:
    """Return a message prefix naming a stream, if it has a name yet.

    Parameters
    ----------
    stream : Stream or None
        Stream being checked; it may not be numbered yet.

    Returns
    -------
    str
        ``"<name>: "``, or an empty string.
    """
    name = getattr(stream, "name", "") if stream is not None else ""
    return f"{name}: " if name else ""


def check_color(value: str, stream: "Stream | None" = None) -> None:
    """Reject a ``color`` value that is not a colour.

    An unreadable paint is ignored by renderers, so the line would vanish.
    Only the shape is checked; a misspelled keyword such as ``"blck"``
    passes.

    Parameters
    ----------
    value : str
        Proposed colour.
    stream : Stream or None, optional
        Stream named in the error message.

    Raises
    ------
    ValueError
        If the value is not a keyword, hex colour or colour function.
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
    """Reject a ``dasharray`` value that is not a dash pattern.

    An unreadable pattern is ignored and the line is drawn solid, so a
    signal line would read as a pipe.

    Parameters
    ----------
    value : str
        Proposed dash pattern.
    stream : Stream or None, optional
        Stream named in the error message.

    Raises
    ------
    ValueError
        If the value is not ``none`` or a list of numbers.
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
    """One physical connection between two ports.

    Parameters
    ----------
    name : str
        Stream number or line number.
    source, dest : Port
        Connected source and destination ports.
    kind : str, default="material"
        Connection type, one of :data:`STREAM_KINDS`.
    draw_as_recycle : bool, default=False
        Prefer this stream as the return line of a cycle.
    route : Route or None, default=None
        Resolved or manually supplied route.
    color, dasharray : str or None, default=None
        Line colour and dash pattern, validated when set.
    ends : str, tuple[str, str], or None, default=None
        Joint style at both ends, or at ``(source, dest)``, overriding the
        sheet's ``connections``. ``None`` inherits. Resolved by
        :func:`pandid.render.svg.resolve_connections`.
    auto_named : bool, default=True
        Whether the flowsheet assigns the name.
    size, schedule, service, sequence, spec, insulation : str, float, or None, default=None
        Line-number components. ``sequence`` is filled by automatic
        numbering unless set; ``schedule`` is a schedule number or
        ``STD``/``XS``/``XXS``.
    properties : dict[str, str | float], optional
        Values shown in the stream table.
    tabulate : bool, default=False
        Report this segment's values in the stream-table column of a run
        drawn through inline devices. It does not add the run to the table.
    state : State or None, default=None
        Stream conditions for a future balance engine.
    """

    name: str
    source: Port
    dest: Port
    kind: str = "material"
    draw_as_recycle: bool = False
    route: Route | None = None
    color: str | None = None
    dasharray: str | None = None
    ends: "str | tuple[str, str] | None" = None
    auto_named: bool = True
    size: str | float | None = None
    schedule: str | float | None = None
    service: str | float | None = None
    sequence: str | float | None = None
    spec: str | float | None = None
    insulation: str | float | None = None
    properties: dict[str, str | float] = field(default_factory=dict)
    tabulate: bool = False
    state: State | None = None
    _is_recycle: bool = field(default=False, init=False, repr=False)
    # Sequence last written by automatic numbering, so an author's value is
    # recognised and kept.
    _auto_sequence: str | None = field(default=None, init=False, repr=False)
    _inline_at: float | None = field(default=None, init=False, repr=False, compare=False)
    _logical_to: Port | None = field(default=None, init=False, repr=False, compare=False)
    _logical_segments: list[Stream] = field(default_factory=list, init=False, repr=False, compare=False)
    _logical_root: Stream | None = field(default=None, init=False, repr=False, compare=False)

    #: Fields validated on assignment: renderer instructions that are
    #: silently dropped when unreadable. Other text is escaped on output.
    _CHECKED = {"color": check_color, "dasharray": check_dasharray}

    def __setattr__(self, name: str, value) -> None:
        """Set an attribute, validating ``color`` and ``dasharray``.

        Parameters
        ----------
        name : str
            Attribute name.
        value : object
            New value.

        Raises
        ------
        TypeError
            If ``color`` or ``dasharray`` is not text or ``None``.
        ValueError
            If a checked field receives an invalid value.
        """
        check = self._CHECKED.get(name)
        if check is not None and value is not None:
            # Both are written into SVG and draw.io styles as text; a bool or
            # number passes the shape check as str() but breaks the renderers.
            if not isinstance(value, str):
                raise TypeError(
                    f"{_names(self)}{name}={value!r} must be text, such as "
                    f"{'black' if name == 'color' else '4,2'!r}"
                )
            check(value, self)
        object.__setattr__(self, name, value)

    @property
    def is_recycle(self) -> bool:
        """Return whether layout marked this stream as a return line.

        Returns
        -------
        bool
            Read-only result of cycle breaking.
        """
        return self._is_recycle

    @property
    def has_line_number(self) -> bool:
        """Return whether a line number, not a stream number, names the stream.

        ``sequence`` alone does not count, because automatic numbering fills
        it on every stream.

        Returns
        -------
        bool
            Whether ``size``, ``schedule``, ``service``, ``spec`` or
            ``insulation`` is set.
        """
        return any((self.size, self.schedule, self.service, self.spec, self.insulation))

    @property
    def at_boundary(self) -> bool:
        """Return whether this segment crosses the sheet boundary.

        A segment is a boundary segment when one end is a
        :class:`~pandid.units.Feed` or :class:`~pandid.units.Product` flag.
        ISO 10628-1:2014 4.3.2 d) requires a PFD to name every ingoing and
        outgoing material with its flow, so the stream table keeps such
        columns and :mod:`pandid.validate` reports empty ones. A
        :class:`~pandid.units.Vent` or :class:`~pandid.units.Funnel` is
        drawn as piping, not as a reference to another drawing, and is not
        a boundary here.

        The answer is per segment: on a run drawn through inline devices,
        only the segment at the flag returns ``True``.

        Returns
        -------
        bool
            Whether either end is a boundary flag.
        """
        from pandid.units import _Boundary

        return (isinstance(self.source.owner, _Boundary)
                or isinstance(self.dest.owner, _Boundary))

    def line_components(self) -> dict[str, str]:
        """Return the line-number components as text.

        Returns
        -------
        dict[str, str]
            Value per field in :data:`LINE_NUMBER_FIELDS`, empty where unset.
        """
        return {f: "" if getattr(self, f) is None else str(getattr(self, f))
                for f in LINE_NUMBER_FIELDS}

    def via(self, waypoints: list[tuple[float, float]]) -> "Stream":
        """Route the stream through exact author-supplied waypoints.

        Parameters
        ----------
        waypoints : list[tuple[float, float]]
            Ordered drawing coordinates in pixels.

        Returns
        -------
        Stream
            This stream, with its route marked manual.

        Raises
        ------
        TypeError
            If a coordinate is not a number.
        ValueError
            If this stream is the handle of a split logical run.
        """
        for i, point in enumerate(waypoints):
            for axis, value in zip("xy", point):
                check_real(value, f"{_names(self)}via waypoint {i} {axis}")
        if self._logical_segments:
            raise ValueError("via() on a split run is ambiguous; route a physical segment instead")
        if self.route is None:
            self.route = Route()
        self.route.waypoints = waypoints
        self.route.manual = True
        self.route.used_fallback = False
        return self
