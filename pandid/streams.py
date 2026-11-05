"""Streams: connections from one port to another.

An automatically named stream takes its stream number, or a line
number from the flowsheet's ``line_numbering_scheme`` once any of
``size``, ``schedule``, ``service``, ``spec`` or ``insulation`` is
set. A name given to ``connect()`` is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pandid._checks import check_real
from pandid.deprecation import Deprecation
from pandid.geometry import Route

if TYPE_CHECKING:
    from pandid.ports import Port
    from pandid.state import State

#: Line-number components, in conventional order.
LINE_NUMBER_FIELDS = ("size", "schedule", "service", "sequence", "spec", "insulation")

#: Deprecation of Stream.line_components().
_LINE_COMPONENTS = Deprecation(
    what="Stream.line_components()",
    instead="the stream's size, schedule, service, sequence, spec and insulation",
    removed_in="0.3.0",
)

#: Kinds that carry process fluid or duty.
PROCESS_KINDS = frozenset({"material", "energy"})

#: Kinds that carry a signal; they join signal-role ports only.
SIGNAL_KINDS = frozenset({"electric", "pneumatic", "data", "capillary", "software"})

#: Every kind ``connect()`` accepts.
STREAM_KINDS = PROCESS_KINDS | SIGNAL_KINDS

#: Accepted colour shapes: a keyword, a hex colour of 3, 4, 6 or 8
#: digits, or an ``rgb``/``rgba``/``hsl``/``hsla`` function.
_COLOR = re.compile(
    r"""\A(?:
        [A-Za-z][A-Za-z0-9-]*                        # a keyword
      | \#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})
      | (?:rgb|rgba|hsl|hsla)\( [0-9.,%/ +-]* \)     # a colour function
    )\Z""",
    re.VERBOSE,
)

#: One number in a dash pattern, in drawing units.
_DASH_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"

#: A dash pattern: ``none``, or lengths separated by commas or spaces.
_DASHARRAY = re.compile(rf"\A(?:none|{_DASH_NUMBER}(?:[, ]+{_DASH_NUMBER})*)\Z")


def _names(stream: "Stream | None") -> str:
    """Return ``"<name>: "`` for a named stream, else ``""``.

    Parameters
    ----------
    stream : Stream or None
        Stream being checked.

    Returns
    -------
    str
        Message prefix.
    """
    name = getattr(stream, "name", "") if stream is not None else ""
    return f"{name}: " if name else ""


def check_color(value: str, stream: "Stream | None" = None) -> None:
    """Raise ``ValueError`` unless ``value`` is shaped like a colour.

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
    """Raise ``ValueError`` unless ``value`` is a dash pattern.

    Parameters
    ----------
    value : str
        Proposed dash pattern.
    stream : Stream or None, optional
        Stream named in the error message.

    Raises
    ------
    ValueError
        If the value is not ``none`` or a list of lengths.
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

    Attributes
    ----------
    name : str
        Given name, stream number or line number.
    source, dest : Port
        Connected source and destination ports.
    kind : str
        Connection type, one of :data:`STREAM_KINDS`.
    draw_as_recycle : bool
        Prefer this stream as the return line of a cycle.
    route : Route or None
        Resolved or manually supplied route.
    color, dasharray : str or None
        Line colour and dash pattern, validated when set.
    ends : str, tuple[str, str], or None
        Joint style at both ends or ``(source, dest)``; ``None``
        inherits the sheet's ``connections``, unlike ``"none"``.
    auto_named : bool
        Whether the flowsheet assigns the name.
    size, schedule, service, sequence, spec, insulation : str or float
        Line-number components, or ``None`` when unset.
    properties : dict[str, str | float]
        Values shown in the stream table.
    tabulate : bool
        Report this segment in a split run's stream-table column.
    state : State or None
        Stream conditions.
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
    # Sequence last written by automatic numbering.
    _auto_sequence: str | None = field(default=None, init=False, repr=False)
    _inline_at: float | None = field(default=None, init=False, repr=False, compare=False)
    _logical_to: Port | None = field(default=None, init=False, repr=False, compare=False)
    _logical_segments: list[Stream] = field(default_factory=list, init=False, repr=False, compare=False)
    _logical_root: Stream | None = field(default=None, init=False, repr=False, compare=False)

    #: Fields validated on assignment, with their checks.
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
            If ``color`` or ``dasharray`` has the wrong shape.
        """
        check = self._CHECKED.get(name)
        if check is not None and value is not None:
            if not isinstance(value, str):
                raise TypeError(
                    f"{_names(self)}{name}={value!r} must be text, such as "
                    f"{'black' if name == 'color' else '4,2'!r}"
                )
            check(value, self)
        object.__setattr__(self, name, value)

    @property
    def is_recycle(self) -> bool:
        """Return whether layout made this a cycle's return line.

        Returns
        -------
        bool
            Result of cycle breaking.
        """
        return self._is_recycle

    @property
    def has_line_number(self) -> bool:
        """Return whether a line number, not a stream number, names it.

        Returns
        -------
        bool
            Whether ``size``, ``schedule``, ``service``, ``spec``,
            ``insulation`` or a ``sequence`` the author set is set.
        """
        return (any((self.size, self.schedule, self.service, self.spec, self.insulation))
                or bool(self.sequence) and self.sequence != self._auto_sequence)

    @property
    def at_boundary(self) -> bool:
        """Return whether this segment ends at a Feed or Product.

        Returns
        -------
        bool
            Whether either end's unit is a boundary flag.
        """
        from pandid.units import _Boundary

        return (isinstance(self.source.owner, _Boundary)
                or isinstance(self.dest.owner, _Boundary))

    def line_components(self) -> dict[str, str]:
        """Return the line-number fields as text, empty where unset.

        Returns
        -------
        dict[str, str]
            Value per field in :data:`LINE_NUMBER_FIELDS`.

        Warns
        -----
        DeprecationWarning
            Always.
        """
        _LINE_COMPONENTS.warn(self)
        return {f: "" if getattr(self, f) is None else str(getattr(self, f))
                for f in LINE_NUMBER_FIELDS}

    def via(self, waypoints: list[tuple[float, float]]) -> "Stream":
        """Route the stream through exact waypoints.

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
            If a coordinate is not finite, or this stream is the handle
            of a split run.
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
