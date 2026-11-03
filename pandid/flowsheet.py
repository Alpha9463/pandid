"""Define the flowsheet: the units, streams and loops of one drawing.

A flowsheet also lays out, routes, validates and renders its drawing.
"""

from __future__ import annotations
from contextlib import contextmanager
from math import isfinite
from numbers import Integral
from pathlib import Path
from string import Formatter
from typing import Any, Callable, Literal, TYPE_CHECKING, TypeVar

from pandid.document import StreamLabelOptions, StreamTableOptions
from pandid.stations import (
    DEFAULT_BYPASS_RISE,
    DEFAULT_DRAIN_DROP,
    DEFAULT_GAP,
    DEFAULT_VALVE_STATION_TAG_SCHEME,
)
from pandid.streams import PROCESS_KINDS, SIGNAL_KINDS, STREAM_KINDS, Stream

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pandid.components import Component
    from pandid.document import TitleBlock
    from pandid.loops import ControlLoop, Loop
    from pandid.ports import Port
    from pandid.stations import ValveStation
    from pandid.units import Instrument, Unit

_ENERGY_ROLES = {"energy", "utility"}

#: Default line-number format.
DEFAULT_LINE_NUMBERING_SCHEME = "{size}-{service}-{sequence}-{spec}"

#: First automatic line sequence number.
DEFAULT_LINE_NUMBER_START = 1001

#: First automatic stream number, ``n`` in ``S{n}``.
DEFAULT_STREAM_NUMBER_START = 1

#: First loop number :meth:`Flowsheet.add_loop` allocates.
DEFAULT_LOOP_NUMBER_START = 101

#: Unit kinds that sit within a line.
INLINE_KINDS = frozenset({"valve", "reducer", "fitting", "tee"})

#: Attribute types :func:`_restore` refills in place.
_CONTAINERS = (list, dict, set)


def _snapshot(obj) -> dict:
    """Save every attribute of an object for :func:`_restore`.

    Parameters
    ----------
    obj : object
        Object to save.

    Returns
    -------
    dict
        Attribute name to ``(value, container copy or None)``.
    """
    return {k: (v, v.copy() if isinstance(v, _CONTAINERS) else None)
            for k, v in vars(obj).items()}


def _restore(obj, saved: dict) -> None:
    """Restore an object's attributes saved by :func:`_snapshot`.

    Containers are emptied and refilled in place.

    Parameters
    ----------
    obj : object
        Object to restore.
    saved : dict
        Result of :func:`_snapshot`.
    """
    obj.__dict__.clear()
    for k, (value, contents) in saved.items():
        if contents is not None:
            if isinstance(value, list):
                value[:] = contents
            else:
                value.clear()
                value.update(contents)
        obj.__dict__[k] = value


#: Extensions :meth:`Flowsheet.render` writes; none means SVG.
_OUTPUT_FORMATS = frozenset({"", ".svg", ".pdf", ".png", ".drawio"})


def _inferred_kind(src: "Port", dst: "Port") -> str:
    """Return the stream kind two ports imply.

    Two energy or utility ports imply ``"energy"``.

    Parameters
    ----------
    src, dst : Port
        Source and destination ports.

    Returns
    -------
    str
        ``"energy"`` or ``"material"``.
    """
    return ("energy" if src.role in _ENERGY_ROLES and dst.role in _ENERGY_ROLES
            else "material")


def _format_line_number(scheme: "str | Callable[[Stream], str]", stream: Stream) -> str:
    """Build a stream's line number from its components.

    An unset component is dropped with the separator before it.

    Parameters
    ----------
    scheme : str or Callable[[Stream], str]
        Format string over the line-number components, or a callable.
    stream : Stream
        Stream to number.

    Returns
    -------
    str
        Line number.

    Raises
    ------
    ValueError
        If the scheme names an unknown component or yields nothing.
    """
    if callable(scheme):
        return scheme(stream)
    parts = stream.line_components()
    out: list[str] = []
    pending = ""  # separator held until the next component is present
    for literal, name, format_spec, _ in Formatter().parse(scheme):
        pending += literal
        if name is None:
            continue
        if name not in parts:
            raise ValueError(
                f"line_numbering_scheme {scheme!r} asks for {name!r}, which is not a "
                f"line-number component; available components: {sorted(parts)}"
            )
        value = parts[name]
        if not value:
            pending = ""
            continue
        # Drop a leading separator when no earlier component survived.
        piece = format(value, format_spec) if format_spec else value
        out.append((pending if out else "") + piece)
        pending = ""
    line_number = "".join(out) + pending
    if not line_number:
        raise ValueError(
            f"stream {stream.name!r} carries line-number components that "
            f"line_numbering_scheme {scheme!r} never uses, so its line number would be "
            f"empty; name the components you set, or set the ones the scheme names"
        )
    return line_number


def _format_stream_name(scheme: "str | Callable[[int], str]", number: int) -> str:
    """Return a generated stream name from the naming scheme.

    Parameters
    ----------
    scheme : str or Callable[[int], str]
        Format string over ``n``, or a callable of the number.
    number : int
        Stream number.

    Returns
    -------
    str
        Stream name.

    Raises
    ------
    ValueError
        If the format string cannot format the number.
    """
    if callable(scheme):
        return scheme(number)
    try:
        return scheme.format(n=number)
    except (KeyError, IndexError):
        # Find the first field whose root is not ``n``.
        roots = (name.partition(".")[0].partition("[")[0]
                 for _, name, _, _ in Formatter().parse(scheme) if name is not None)
        field = next((root for root in roots if root != "n"), "") or "{}"
        raise ValueError(
            f"stream_naming_scheme {scheme!r} asks for {field!r}, which is not "
            f"part of a stream name; the only field is 'n', the stream's number"
        ) from None
    except (AttributeError, TypeError, ValueError) as exc:
        # Such as {n.foo}, {n:q} or an unclosed brace.
        raise ValueError(
            f"stream_naming_scheme {scheme!r} cannot write a stream number: {exc}. "
            f"Write it as {{n}}, with a format spec if needed, such as 'S{{n:03d}}'"
        ) from None


def _spell(port: "Port") -> str:
    """Return ``"<unit>.<port>"`` for messages.

    Parameters
    ----------
    port : Port
        Port to name.

    Returns
    -------
    str
        Owner name and port name.
    """
    return f"{port.owner.name}.{port.name}"


def _signal_end(end: "Port | Unit", kind: str, which: str) -> "Port":
    """Return the port for one connection end, given as a port or unit.

    An instrument gives its signal pool; another unit its one signal
    port.

    Parameters
    ----------
    end : Port or Unit
        End as the caller gave it.
    kind : str
        Stream kind.
    which : str
        ``"source"`` or ``"destination"``.

    Returns
    -------
    Port
        Port to connect.

    Raises
    ------
    TypeError
        If ``end`` is neither a port nor a unit.
    ValueError
        If a unit ends a process line or has no single signal port.
    """
    from pandid.ports import Port
    from pandid.units import Instrument, Unit

    if isinstance(end, Port):
        return end
    if not isinstance(end, Unit):
        raise TypeError(
            f"connect() takes a Port or a Unit at each end, got "
            f"{type(end).__name__}"
        )
    if kind not in SIGNAL_KINDS:
        raise ValueError(
            f"the {which} is {end.name}, a unit rather than one of its nozzles, and "
            f"kind={kind!r} is process piping. Which nozzle a pipe runs to is the "
            f"whole question, so name it ({end.name}.<nozzle>); only a signal line "
            f"(kind one of {sorted(SIGNAL_KINDS)}) may be drawn to the unit"
        )
    if isinstance(end, Instrument):
        # Use the signal pool.
        return end.sig_out if which == "source" else end.sig_in
    signals = [port for port in end.ports.values() if port.role == "signal"]
    if len(signals) == 1:
        return signals[0]
    if not signals:
        raise ValueError(
            f"the {which} is {end.name}, which has no signal connection for a "
            f"{kind} line to reach; its nozzles are {sorted(end.ports)}"
        )
    raise ValueError(
        f"the {which} is {end.name}, which has {len(signals)} signal connections "
        f"({', '.join(port.name for port in signals)}); name the one this line "
        f"runs to"
    )


def _port_bearers(*ends: "Port | Unit") -> "tuple[Any, ...]":
    """Return the units at a connection's ends, then all their ports.

    Parameters
    ----------
    *ends : Port or Unit
        Connection ends.

    Returns
    -------
    tuple
        Distinct units, then each of their ports.
    """
    from pandid.ports import Port
    from pandid.units import Unit

    units: "list[Unit]" = []
    for end in ends:
        owner = end.owner if isinstance(end, Port) else end
        if isinstance(owner, Unit) and not any(owner is u for u in units):
            units.append(owner)
    return (*units, *(port for unit in units for port in unit.ports.values()))


def _stated(**kwargs: "float | str | None") -> dict[str, Any]:
    """Return the keyword arguments that are not ``None``.

    Parameters
    ----------
    **kwargs : float, str or None
        Candidate arguments.

    Returns
    -------
    dict[str, Any]
        Arguments with a value.
    """
    return {name: value for name, value in kwargs.items() if value is not None}


def _functional_code(loop: "Loop", stated: str | None, default: str, role: str) -> str:
    """Return and check one control-loop member's functional code.

    Parameters
    ----------
    loop : Loop
        Loop the member belongs to.
    stated : str or None
        Code the author gave, or ``None`` to use ``default``.
    default : str
        Code composed from the loop.
    role : str
        Argument name, for messages.

    Returns
    -------
    str
        Functional code.

    Raises
    ------
    ValueError
        If the code is blank or invalid for the loop.
    """
    if stated is None:
        return default
    letters = stated.strip()
    if not letters:
        raise ValueError(
            f"loop {loop.name}: {role} is the whole functional code that member "
            f"carries ({default!r} here), and an empty string is no tag at all. Leave "
            f"it out and this letters the member from the loop"
        )
    if letters.upper() == loop.variable:
        raise ValueError(
            f"loop {loop.name}: {role}={stated!r} is the measured variable with no "
            f"function letter after it, which leaves the balloon tagged "
            f"{loop.variable}-{loop.number} -- a tag no instrument carries. It is the "
            f"whole functional code that is wanted, e.g. {default!r}"
        )
    loop.check(letters)
    return letters


def _check_signal_pairing(src: "Port", dst: "Port", kind: str) -> None:
    """Check that a stream's kind matches the roles of its two ports.

    Parameters
    ----------
    src, dst : Port
        Source and destination ports.
    kind : str
        Stream kind.

    Raises
    ------
    ValueError
        If the ports mix signal and process roles, or the kind differs.
    """
    signal_ends = [p for p in (src, dst) if p.role == "signal"]
    if len(signal_ends) == 1:
        signal = signal_ends[0]
        process = dst if signal is src else src
        raise ValueError(
            f"{_spell(signal)} is a signal connection and {_spell(process)} is a "
            f"process connection; a stream joins two signal connections or two "
            f"process ones"
        )
    if signal_ends and kind not in SIGNAL_KINDS:
        raise ValueError(
            f"{_spell(src)} to {_spell(dst)} is a signal line; kind must be one "
            f"of {sorted(SIGNAL_KINDS)}, got {kind!r}"
        )
    if not signal_ends and kind in SIGNAL_KINDS:
        raise ValueError(
            f"{_spell(src)} to {_spell(dst)} is process piping; kind must be one "
            f"of {sorted(PROCESS_KINDS)}, got {kind!r}"
        )


# Lets add() return the subclass it was given.
_UnitT = TypeVar("_UnitT", bound="Unit")


def _whole_number(value: Any, name: str) -> int:
    """Return an integral value as an ``int``.

    Parameters
    ----------
    value : Any
        Value to check.
    name : str
        Attribute name, for the message.

    Returns
    -------
    int
        The value as a built-in ``int``.

    Raises
    ------
    TypeError
        If ``value`` is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(
            f"{name} must be a whole number (an int), got {value!r}; stream, line "
            f"and loop numbers are integers"
        )
    return int(value)


class Flowsheet:
    """A drawing's units, streams, loops and sheet furniture.

    Parameters
    ----------
    name : str
        Drawing title.
    stream_naming_scheme : str or callable, default="S{n}"
        Stream name format over ``n``, or a callable of ``n``.
    stream_number_start : int, default=1
        First ``n`` in ``stream_naming_scheme``.
    line_numbering_scheme : str or callable, optional
        Line number format, or a callable of the stream.
    line_number_start : int, default=1001
        First generated ``sequence`` component of a line number.
    loop_number_start : int, default=101
        First number :meth:`add_loop` allocates.
    valve_station_tag_scheme : str or callable, optional
        Valve station member tag format, or a callable.
    auto_faces : bool, default=True
        Whether movable port faces are chosen automatically.

    Attributes
    ----------
    name : str
        Drawing title.
    units : list[Unit]
        Units in the order added.
    streams : list[Stream]
        Streams in the order connected.
    components : list[Component]
        Registered chemical species.
    loops : list[Loop]
        Declared control loops, in declaration order.
    warnings : list[Issue]
        Warnings from the last render.
    route_converged : bool
        Whether the last ``route()`` settled its attached instruments.
    unplaced_instruments : list[Instrument]
        Attached instruments the last placement could not place.
    title_block : TitleBlock or None
        Title block to draw.
    annotations : list
        Annotation and table boxes docked to the sheet corners.
    stream_table_sections : list[tuple[str, str]]
        Stream-table section headers as ``(before_key, label)``.
    stream_table : StreamTableOptions
        Stream-table sizing and title.
    stream_labels : StreamLabelOptions
        How numbers on lines are enclosed.
    stream_naming_scheme, line_numbering_scheme : str or callable
        Stream and line numbering schemes.
    valve_station_tag_scheme : str or callable
        Valve station member tag format.
    stream_number_start, line_number_start, loop_number_start : int
        First generated stream, line and loop numbers.
    auto_faces : bool
        Whether movable port faces are chosen automatically.

    Raises
    ------
    TypeError
        If a number start is not an integer.
    ValueError
        If ``stream_naming_scheme`` cannot format a stream number.
    """

    def __init__(  # numpydoc ignore=GL08
        self, name: str, *,
        stream_naming_scheme: str | Callable[[int], str] = "S{n}",
        stream_number_start: int = DEFAULT_STREAM_NUMBER_START,
        line_numbering_scheme: str | Callable[[Stream], str] = DEFAULT_LINE_NUMBERING_SCHEME,
        line_number_start: int = DEFAULT_LINE_NUMBER_START,
        loop_number_start: int = DEFAULT_LOOP_NUMBER_START,
        valve_station_tag_scheme: "str | Callable[[str, str], str]" = (
            DEFAULT_VALVE_STATION_TAG_SCHEME),
        auto_faces: bool = True,
    ):
        self.name = name
        self.stream_naming_scheme = stream_naming_scheme
        self.stream_number_start = stream_number_start
        self.line_numbering_scheme = line_numbering_scheme
        self.line_number_start = line_number_start
        self.loop_number_start = loop_number_start
        # Count of loop numbers add_loop() has allocated.
        self._loops_allocated = 0
        self.valve_station_tag_scheme = valve_station_tag_scheme
        self.auto_faces = auto_faces
        self.units: list = []
        self._station_assemblies: list = []
        self.streams: list[Stream] = []
        self.components: list = []
        self.loops: list["Loop"] = []
        self.warnings: list = []
        # Diagram type of the last render; validate() defaults to it.
        self._drawn_as: str | None = None
        self.route_converged: bool = True
        # Whether the last layout set pipe furniture on routed pipe.
        self._mounted_layout = False
        self.unplaced_instruments: list = []
        # Whether cached frames and routes are stale.
        self._layout_stale = False
        self._route_stale = False
        # Last full numbering pass, for _number_appended().
        self._groups: "list[list[Stream]] | None" = None
        self._group_names: list[str] = []
        self._group_of: dict[int, int] = {}  # id(Stream) -> group index
        self._tail: list[Stream] = []  # lines numbered after the runs
        self.title_block: "TitleBlock | None" = None
        self.annotations: list = []
        self.stream_table_sections: list[tuple[str, str]] = []
        self.stream_table = StreamTableOptions()
        self.stream_labels = StreamLabelOptions()

    def _invalidate_layout(self) -> None:
        """Mark the cached layout and routes stale."""
        self._layout_stale = True
        self._route_stale = True

    @property
    def auto_faces(self) -> bool:
        """Return whether movable port faces are chosen automatically.

        When ``False``, each port keeps its symbol's face or the one set
        with :meth:`~pandid.units.Unit.nozzle`.

        Returns
        -------
        bool
            Current setting.
        """
        return self._auto_faces

    @auto_faces.setter
    def auto_faces(self, value: bool) -> None:
        """Set automatic face selection and invalidate layout.

        Parameters
        ----------
        value : bool
            New setting.
        """
        self._auto_faces = value
        self._invalidate_layout()

    @property
    def stream_naming_scheme(self) -> "str | Callable[[int], str]":
        """Return the stream naming scheme.

        Returns
        -------
        str or Callable[[int], str]
            Current scheme.
        """
        return self._stream_naming_scheme

    @stream_naming_scheme.setter
    def stream_naming_scheme(self, value: "str | Callable[[int], str]") -> None:
        """Set the stream naming scheme, checking its fields.

        Parameters
        ----------
        value : str or Callable[[int], str]
            Format string over ``n``, or a callable of the number.

        Raises
        ------
        ValueError
            If the format string cannot format a stream number.
        """
        if not callable(value):
            _format_stream_name(value, DEFAULT_STREAM_NUMBER_START)
        self._stream_naming_scheme = value

    @property
    def stream_number_start(self) -> int:
        """Return the first ``n`` in ``stream_naming_scheme``.

        Returns
        -------
        int
            First generated stream number.
        """
        return self._stream_number_start

    @stream_number_start.setter
    def stream_number_start(self, value: int) -> None:
        """Set the first generated stream number.

        Parameters
        ----------
        value : int
            Whole number.

        Raises
        ------
        TypeError
            If ``value`` is not an integer.
        """
        self._stream_number_start = _whole_number(value, "stream_number_start")

    @property
    def line_number_start(self) -> int:
        """Return the first generated line sequence number.

        Returns
        -------
        int
            First generated line sequence number.
        """
        return self._line_number_start

    @line_number_start.setter
    def line_number_start(self, value: int) -> None:
        """Set the first generated line sequence number.

        Parameters
        ----------
        value : int
            Whole number.

        Raises
        ------
        TypeError
            If ``value`` is not an integer.
        """
        self._line_number_start = _whole_number(value, "line_number_start")

    @property
    def loop_number_start(self) -> int:
        """Return the first number :meth:`add_loop` allocates.

        Returns
        -------
        int
            First loop number.
        """
        return self._loop_number_start

    @loop_number_start.setter
    def loop_number_start(self, value: int) -> None:
        """Set the first number :meth:`add_loop` allocates.

        Parameters
        ----------
        value : int
            Whole number.

        Raises
        ------
        TypeError
            If ``value`` is not an integer.
        """
        self._loop_number_start = _whole_number(value, "loop_number_start")

    def add_annotation(self, annotation):
        """Add an annotation or table box to the sheet.

        Parameters
        ----------
        annotation : Annotation or TableBox
            Box to dock to a sheet corner.

        Returns
        -------
        Annotation or TableBox
            The same box.
        """
        self.annotations.append(annotation)
        return annotation

    def add(self, unit: _UnitT, *, on: Stream | None = None,
            at: float | None = None) -> _UnitT:
        """Add a unit to the sheet, optionally in a line.

        Tags must be unique, except for interlock or logic squares,
        utility header flags and tees, which may repeat under a unique
        name such as ``I-1 (2)``. With ``on``, a valve, reducer or
        fitting goes in that line in flow order.

        Parameters
        ----------
        unit : Unit
            Unit to add.
        on : Stream or None, optional
            Material line from :meth:`connect` to put the unit in.
        at : float or None, optional
            Position on that line, a fraction strictly between 0 and 1.

        Returns
        -------
        Unit
            The same unit.

        Raises
        ------
        ValueError
            If the unit is already on a sheet, its name is taken, ``at``
            is given without ``on``, or the unit cannot go in that line.
        """
        if on is not None:
            from pandid.inline import insert_device

            return insert_device(self, on, unit, at=at)
        if at is not None:
            raise ValueError(f"{unit.name}: at= is a position on the line given by on=")
        clash = self._refuse_unaddable(unit)
        if clash is not None:
            # Name a repeat from its tag, or a tee from its name.
            unit.name = self._repeat_name(unit.tag or unit.name)
        unit.flowsheet = self
        self.units.append(unit)
        self._invalidate_layout()
        return unit

    def _refuse_unaddable(self, unit: "Unit",
                          alongside: "Sequence[Unit]" = ()) -> "Unit | None":
        """Check that a unit may join the sheet.

        Parameters
        ----------
        unit : Unit
            Unit to check.
        alongside : Sequence[Unit], optional
            Units the same call is about to add.

        Returns
        -------
        Unit or None
            The unit this one repeats, or ``None``.

        Raises
        ------
        ValueError
            If the unit is already on a sheet, or its name clashes.
        """
        if unit in self.units:
            raise ValueError(
                f"{unit!r} is already on this flowsheet"
            )
        clash = next((u for u in [*self.units, *alongside] if u.name == unit.name), None)
        if clash is not None and not unit.repeats(clash):
            raise ValueError(
                f"A unit with the name {unit.name!r} already exists on this "
                f"flowsheet. A tag names one item, so two units cannot share one. "
                f"Two symbols stand for one thing shown in several places and may "
                f"repeat: a trip square (an Instrument with variant='sis'/'logic' "
                f"or 'interlock'), a single logic function drawn at each place it "
                f"acts, and a utility header flag (a Feed or Product with "
                f"header=True), one service drawn at each place it is tapped. Both "
                f"drawings have to be of the same thing, so they must agree on the "
                f"class and the variant, and two flags on the off-page reference. "
                f"A primary element and its balloon are one instrument shown twice "
                f"and share a tag for that reason, but the balloon has to be asked "
                f"for from the element: fs.add_balloon(fe303), not a second "
                f"Instrument carrying the same letters. "
                f"A Tee repeats against another Tee, having no tag to clash with, "
                f"but the name is still what a stream and a spec entry reach it by, "
                f"so it may not take one that already means something else."
            )
        if unit.flowsheet is not None:
            raise ValueError(
                f"{unit!r} is already on flowsheet {unit.flowsheet.name!r}"
            )
        return clash

    def _repeat_name(self, tag: str) -> str:
        """Return a unique name for another drawing of a repeated tag.

        Parameters
        ----------
        tag : str
            Repeated tag.

        Returns
        -------
        str
            ``"<tag> (n)"`` with the least free ``n`` from 2.
        """
        taken = {u.name for u in self.units}
        n = 2
        while f"{tag} ({n})" in taken:
            n += 1
        return f"{tag} ({n})"

    def add_loop(self, variable: str, number: str | int | None = None) -> "Loop":
        """Declare a control loop and return its handle.

        A loop is its variable and number together, so
        ``add_loop("F", 101)`` and ``add_loop("L", 101)`` are two loops.
        Without a number, the next one in the sheet's series from
        ``loop_number_start`` is allocated::

            fs = Flowsheet("A300", loop_number_start=301)
            press = fs.add_loop("P")   # P-301
            temp = fs.add_loop("T")    # T-302

        Parameters
        ----------
        variable : str
            ISA measured-variable letter, such as ``"F"``.
        number : str, int or None, optional
            Loop number, or ``None`` to allocate the next one.

        Returns
        -------
        Loop
            The declared loop.

        Raises
        ------
        ValueError
            If the variable is invalid, or the loop is already declared.
        """
        loop, allocated = self._new_loop(variable, number)
        self._register_loop(loop, allocated=allocated)
        return loop

    def _new_loop(self, variable: str,
                  number: str | int | None = None) -> "tuple[Loop, bool]":
        """Build and check a loop.

        Parameters
        ----------
        variable : str
            ISA measured-variable letter.
        number : str, int or None, optional
            Loop number, or ``None`` to allocate the next one.

        Returns
        -------
        tuple[Loop, bool]
            The loop and whether its number was allocated.

        Raises
        ------
        ValueError
            If the variable is invalid, or the loop is already declared.
        """
        from pandid.loops import Loop

        # One allocation series per sheet across all variables.
        allocated = number is None
        if number is None:
            number = self.loop_number_start + self._loops_allocated
        loop = Loop(variable, number)
        clash = next((existing for existing in self.loops
                      if (existing.variable, existing.number) == (loop.variable, loop.number)),
                     None)
        if clash is not None:
            if allocated:
                raise ValueError(
                    f"loop {loop.name} took {number}, the next number in this sheet's "
                    f"series, and {loop.name} is already declared. The counter counts; it "
                    f"does not read the numbers you typed and step over them, because "
                    f"only you know where those sit. Either type this loop's number too, "
                    f"or start the series clear of them with "
                    f"Flowsheet(loop_number_start=...)"
                )
            raise ValueError(
                f"loop {loop.name} is already declared on this flowsheet. A loop is "
                f"identified by its measured variable and its number together, so two "
                f"handles on {loop.name} are two names for one loop; hold on to the one "
                f"add_loop() returned. Two loops may share a number if they measure "
                f"different variables (F-101 and L-101)"
            )
        return loop, allocated

    def _register_loop(self, loop: "Loop", *, allocated: bool) -> None:
        """Declare a loop that :meth:`_new_loop` has checked.

        Parameters
        ----------
        loop : Loop
            Checked loop.
        allocated : bool
            Whether its number came from the counter.
        """
        if allocated:
            self._loops_allocated += 1
        self.loops.append(loop)

    def _resume_loop_numbering(self) -> None:
        """Move the loop counter past every numeric loop number."""
        for loop in self.loops:
            if not loop.number.isdigit():
                continue
            self._loops_allocated = max(
                self._loops_allocated, int(loop.number) + 1 - self.loop_number_start)

    def add_instrument(self, type: str, number: "str | int | Loop | ControlLoop" = "", *,
                       sensing: "Stream | Unit | None" = None,
                       acting_on: "Stream | Unit | None" = None,
                       near: "Stream | Unit | None" = None,
                       at: float | str | None = None,
                       offset: float = 45.0, angle: float = 90.0,
                       variant: str = "default", **kwargs) -> "Instrument":
        """Add an ISA-5.1 instrument balloon.

        The tag is ``type`` and ``number``, such as ``FT-101``. Give at
        most one of ``sensing``, ``acting_on`` and ``near``.

        Parameters
        ----------
        type : str
            Functional letters, such as ``"FT"``.
        number : str, int, Loop or ControlLoop, default=""
            Loop number, or a loop whose variable ``type`` must match.
        sensing : Stream or Unit or None, optional
            Host the balloon reads from.
        acting_on : Stream or Unit or None, optional
            Host the balloon commands.
        near : Stream or Unit or None, optional
            Host the balloon is placed by, with no line drawn.
        at : float, str or None, optional
            Fraction along a stream host, or face of a unit host.
        offset : float, default=45.0
            Distance from the tap to the balloon centre.
        angle : float, default=90.0
            Branch angle from the host's reference direction.
        variant : str, default="default"
            Balloon symbol.
        **kwargs
            Passed to :class:`~pandid.units.Instrument`.

        Returns
        -------
        Instrument
            The added balloon.

        Raises
        ------
        ValueError
            If an argument is invalid or a host is on another sheet.

        Examples
        --------
        >>> s = fs.connect(feed.outlet, fv.inlet)
        >>> ft = fs.add_instrument("FT", 101, sensing=s, at=0.4,
        ...                        offset=60)
        >>> fic = fs.add_instrument("FIC", 101, near=ft, at="N",
        ...                         offset=70, display="central")
        >>> fs.connect(ft.sig_out, fic.sig_in, kind="electric")
        """
        for role, host in (("sensing", sensing), ("acting_on", acting_on),
                           ("near", near)):
            if host is not None:
                self._refuse_foreign(role, host)
        inst = self._build_instrument(
            type, number, sensing=sensing, acting_on=acting_on, near=near,
            at=at, offset=offset, angle=angle, variant=variant, **kwargs)
        self.add(inst)
        return inst

    def _build_instrument(self, type: str,
                          number: "str | int | Loop | ControlLoop" = "", *,
                          sensing: "Stream | Unit | None" = None,
                          acting_on: "Stream | Unit | None" = None,
                          near: "Stream | Unit | None" = None,
                          at: float | str | None = None,
                          offset: float = 45.0, angle: float = 90.0,
                          variant: str = "default", **kwargs) -> "Instrument":
        """Build and anchor a balloon.

        Parameters
        ----------
        type : str
            Functional letters.
        number : str, int, Loop or ControlLoop, default=""
            Loop number, or a loop to take it from.
        sensing, acting_on, near : Stream or Unit or None, optional
            Anchor; at most one.
        at : float, str or None, optional
            Fraction along a stream host, or face of a unit host.
        offset : float, default=45.0
            Distance from the tap to the balloon centre.
        angle : float, default=90.0
            Branch angle from the host's reference direction.
        variant : str, default="default"
            Balloon symbol.
        **kwargs
            Passed to :class:`~pandid.units.Instrument`.

        Returns
        -------
        Instrument
            The anchored balloon.

        Raises
        ------
        ValueError
            If the letters, variant, anchors or placement are invalid.
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.units import Instrument

        if isinstance(number, ControlLoop):
            number = number.loop
        if isinstance(number, Loop):
            number.check(type)
            number = number.number
        inst = Instrument(type, number, variant=variant, **kwargs)
        host, relation = self._anchor(inst, sensing, acting_on, near)
        if host is not None:
            inst.attach(host, at=at, offset=offset, angle=angle, relation=relation)
        return inst

    def _refuse_foreign(self, role: str, thing: "Stream | Port | Unit") -> None:
        """Check that a unit, port or stream belongs to this sheet.

        Parameters
        ----------
        role : str
            Argument name, for messages.
        thing : Stream, Port or Unit
            Object to check.

        Raises
        ------
        ValueError
            If it belongs to another sheet or to none.
        """
        from pandid.ports import Port
        from pandid.units import Unit

        owner = thing.owner if isinstance(thing, Port) else thing
        if isinstance(owner, Unit):
            if owner.flowsheet is self:
                return
            where = ("no flowsheet" if owner.flowsheet is None
                     else f"flowsheet {owner.flowsheet.name!r}")
            raise ValueError(
                f"{role}={owner.name!r} is on {where}, not on {self.name!r}. A member "
                f"of this sheet's drawing has to be on this sheet: one built from "
                f"another sheet's units draws lines to names its own spec never "
                f"declares, so it cannot be read back. fs.add() it here first"
            )
        if any(stream is owner for stream in self.streams):
            return
        raise ValueError(
            f"{role}={getattr(owner, 'name', owner)!r} is a stream on another "
            f"flowsheet. A balloon taps a line this sheet draws; a line drawn "
            f"elsewhere has no entry in this sheet's spec to tap"
        )

    def _set_inline_at(self, stream: Stream, at: float) -> None:
        """Record an inline device's preferred position on its run.

        Parameters
        ----------
        stream : Stream
            Material segment entering the device.
        at : float
            Fraction of the whole run, strictly between 0 and 1.

        Raises
        ------
        ValueError
            If ``at`` is out of range, or the segment is ineligible.
        """
        self._refuse_foreign("stream", stream)
        if (isinstance(at, bool) or not isinstance(at, (int, float))
                or not isfinite(at) or not 0 < at < 1):
            raise ValueError("inline position must be a finite number between 0 and 1")
        unit = stream.dest.owner
        station = next((assembly for assembly in self._station_assemblies
                        if assembly.station.inlet is stream.dest and assembly.run is not None), None)
        if station is not None:
            if (stream.kind != "material" or stream.dest.stream is not stream
                    or station.at != float(at) or station.station.outlet.stream is None):
                raise ValueError("inline position differs from its station attachment")
            stream._inline_at = float(at)
            self._invalidate_layout()
            return
        if (stream.kind != "material" or stream.draw_as_recycle
                or stream.is_recycle or unit is None
                or unit.kind not in {"valve", "reducer", "fitting"}):
            raise ValueError("inline position requires a material stream entering an inline device")
        if stream.dest.name != "inlet" or stream.dest.stream is not stream:
            raise ValueError("inline position requires the device inlet stream")
        process_ports = {port.name for port in unit.ports.values() if port.role == "process"}
        outgoing = unit.ports.get("outlet")
        if (process_ports != {"inlet", "outlet"} or outgoing is None or outgoing.stream is None
                or outgoing.stream.source is not outgoing or outgoing.stream.kind != "material"
                or outgoing.stream.draw_as_recycle or outgoing.stream.is_recycle):
            raise ValueError("inline position requires one material inlet and outlet")
        stream._inline_at = float(at)
        self._invalidate_layout()

    def _anchor(self, inst: "Instrument", sensing, acting_on, near):
        """Return the one anchor named.

        Parameters
        ----------
        inst : Instrument
            Balloon being built, for messages.
        sensing, acting_on, near : Stream, Unit or None
            Anchor arguments.

        Returns
        -------
        tuple
            ``(host, relation)``, or ``(None, "sensing")`` if none.

        Raises
        ------
        ValueError
            If more than one anchor is named.
        """
        given = [("sensing", sensing), ("acting_on", acting_on), ("near", near)]
        named = [(relation, host) for relation, host in given if host is not None]
        if len(named) > 1:
            spellings = ", ".join(f"{relation}=" for relation, _ in named)
            raise ValueError(
                f"{inst.name}: a balloon is anchored to one thing, and this call "
                f"named {len(named)} ({spellings}). Which one it is decides what is "
                f"drawn between them: sensing= and acting_on= draw a connection, "
                f"near= draws nothing. A second relationship is a second line, so "
                f"state it with connect()"
            )
        if not named:
            return None, "sensing"
        relation, host = named[0]
        return host, relation

    def add_balloon(self, element: "Unit", *, at: float | str | None = None,
                    offset: float = 46.0, angle: float = 90.0,
                    variant: str = "default", **kwargs) -> "Instrument":
        """Move a primary element's tag into a balloon drawn beside it.

        The balloon hangs on a solid impulse line and is named like a
        repeat, such as ``FE-303 (2)``.

        Parameters
        ----------
        element : Unit
            Tagged element already on this sheet.
        at : float, str or None, optional
            Face or fraction to hang the balloon from.
        offset : float, default=46.0
            Distance from the tap to the balloon centre.
        angle : float, default=90.0
            Branch angle.
        variant : str, default="default"
            Balloon symbol.
        **kwargs
            Passed to :class:`~pandid.units.Instrument`.

        Returns
        -------
        Instrument
            The balloon.

        Raises
        ------
        ValueError
            If the element is off this sheet, has a balloon, or no tag.
        """
        from pandid.units import Instrument

        if element.flowsheet is not self:
            raise ValueError(
                f"add_balloon() draws the tag of something already on this sheet, and "
                f"{element.name!r} is on "
                f"{'no flowsheet' if element.flowsheet is None else 'another one'}. "
                f"fs.add() it first"
            )
        if element.balloon is not None:
            raise ValueError(
                f"{element.name}: one tag is drawn once, and this element's is already "
                f"in the balloon {element.balloon.name!r}. A second reading of the same "
                f"point is a second instrument with a tag of its own -- a transmitter "
                f"over a primary element is fs.add_instrument('FT', loop, ...)"
            )
        if not element.tag:
            raise ValueError(
                f"{element.name!r} draws no tag, so there is none to move into a "
                f"balloon. add_balloon() takes a tagged item: a primary element "
                f"lettered from its loop, e.g. Fitting(loop.element('FE'))"
            )
        inst = Instrument(element.tag, variant=variant, **kwargs)
        # Mark the element first; add() then allows the shared tag.
        inst._marks = element
        self.add(inst)
        element.balloon = inst
        inst.attach(element, at=at, offset=offset, angle=angle, relation="sensing")
        return inst

    def add_control_loop(
        self, variable: "str | Loop", number: str | int | None = None, *,
        measuring: "Stream | Unit", acting_on: "Port | Unit",
        at: float | str | None = None, offset: float | None = None,
        angle: float | None = None,
        controller_at: str | None = None, controller_offset: float | None = None,
        transmitter_letters: str | None = None, controller_letters: str | None = None,
        controller_variant: str = "shared",
        measurement_kind: str = "electric", output_kind: str = "pneumatic",
    ) -> "ControlLoop":
        """Add a control loop around a final control element.

        Adds a transmitter and a controller, and connects the
        measurement and output signals to the final element, which must
        be on this sheet. Letters follow from the variable (``"F"``
        gives ``FT`` and ``FIC``) unless whole codes are given.

        Parameters
        ----------
        variable : str or Loop
            Measured-variable letter, or a loop declared on this sheet.
        number : str, int or None, optional
            Loop number for a letter ``variable``; ``None`` allocates.
        measuring : Stream or Unit
            What the transmitter reads.
        acting_on : Port or Unit
            Final control element, or its signal port.
        at : float, str or None, optional
            Transmitter tap: a stream fraction or a unit face.
        offset, angle : float or None, optional
            Transmitter standoff and branch angle.
        controller_at : str or None, optional
            Face of the transmitter the controller hangs from.
        controller_offset : float or None, optional
            Controller standoff.
        transmitter_letters, controller_letters : str or None, optional
            Whole functional codes, such as ``"FIT"`` or ``"FRC"``.
        controller_variant : str, default="shared"
            Controller balloon symbol.
        measurement_kind : str, default="electric"
            Kind of the transmitter-to-controller signal.
        output_kind : str, default="pneumatic"
            Kind of the controller-to-element signal.

        Returns
        -------
        ControlLoop
            Handle to the loop and its members.

        Raises
        ------
        ValueError
            If an argument is invalid or belongs to another sheet.
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.ports import Port

        # Check everything; nothing is written until the commit.
        if isinstance(variable, Loop):
            if number is not None:
                raise ValueError(
                    f"loop {variable.name} is already declared and carries its "
                    f"number, so number={number!r} here is a second answer to a "
                    f"settled question. Pass the loop on its own, or pass "
                    f"{variable.variable!r} and {number!r} and let this declare it"
                )
            if not any(declared is variable for declared in self.loops):
                raise ValueError(
                    f"loop {variable.name} was not declared on flowsheet "
                    f"{self.name!r}. A loop is a namespace belonging to one sheet, so "
                    f"pass the handle this sheet's add_loop() returned -- or pass "
                    f"{variable.variable!r} and {variable.number!r} and let this "
                    f"declare it here"
                )
            # None: the loop is already declared.
            loop, allocates = variable, None
        else:
            loop, allocates = self._new_loop(variable, number)
        transmitter_code = _functional_code(
            loop, transmitter_letters, f"{loop.variable}T", "transmitter_letters")
        controller_code = _functional_code(
            loop, controller_letters, f"{loop.variable}IC", "controller_letters")
        self._refuse_foreign("measuring", measuring)
        self._refuse_foreign("acting_on", acting_on)
        # Build the balloons without adding them.
        transmitter = self._build_instrument(
            transmitter_code, loop, sensing=measuring,
            **_stated(at=at, offset=offset, angle=angle))
        # near=: the measurement signal is the only line drawn.
        controller = self._build_instrument(
            controller_code, loop, near=transmitter,
            variant=controller_variant,
            **_stated(at=controller_at, offset=controller_offset))
        self._refuse_unaddable(transmitter)
        # Check the controller's tag against the pending transmitter.
        self._refuse_unaddable(controller, alongside=(transmitter,))
        pending = (transmitter, controller)
        self._resolve_connection(transmitter.sig_out, controller.sig_in,
                                 kind=measurement_kind, pending=pending)
        self._resolve_connection(controller.sig_out, acting_on,
                                 kind=output_kind, pending=pending)

        # Commit.
        if allocates is not None:
            self._register_loop(loop, allocated=allocates)
        self.add(transmitter)
        self.add(controller)
        measurement = self.connect(
            transmitter.sig_out, controller.sig_in, kind=measurement_kind)
        output = self.connect(controller.sig_out, acting_on, kind=output_kind)
        return ControlLoop(
            loop, transmitter, controller,
            acting_on.owner if isinstance(acting_on, Port) else acting_on,
            measurement, output)

    def add_valve_station(
        self, tag: str, *,
        x: float | None = None, y: float | None = None, mirrored: bool | None = None,
        variant: str = "control", number: str | int | None = None,
        isolation: bool = True, reducers: bool = True, bypass: bool = True,
        drains: int = 2, description: str = "", bypass_over: str | None = None,
        tag_scheme: "str | Callable[[str, str], str] | None" = None,
        gap: float | None = None, bypass_rise: float | None = None,
        drain_drop: float | None = None,
        size: str | float | None = None, schedule: str | float | None = None,
        service: str | float | None = None,
        sequence: str | float | None = None, spec: str | float | None = None,
        insulation: str | float | None = None,
        on: Stream | None = None, at: float | None = None,
    ) -> "ValveStation":
        """Build a wired control valve station.

        Members are pinned at ``x`` and ``y`` when given, else placed by
        the layout engine; see :mod:`pandid.stations`.

        Parameters
        ----------
        tag : str
            Control valve tag; member tags derive from it.
        x, y : float or None, optional
            Station left edge and run centreline; give both or neither.
        mirrored : bool or None, optional
            Pipe a pinned run east to west.
        variant : str, default="control"
            Control valve symbol.
        number : str, int or None, optional
            Member tag number; defaults to the control tag's.
        isolation, reducers, bypass : bool, default=True
            Include isolation valves, reducers and a bypass.
        drains : int, default=2
            Number of drain valves: 0, 1 or 2.
        description : str, default=""
            Service word prefixed to member descriptions.
        bypass_over : str or None, optional
            Member to centre the bypass valve over; one of
            :data:`~pandid.stations.BYPASS_ANCHORS`.
        tag_scheme : str, callable or None, optional
            Member tag format; defaults to ``valve_station_tag_scheme``.
        gap, bypass_rise, drain_drop : float or None, optional
            Spacing for a pinned station.
        size, schedule, service : str or float, optional
            Bypass and drain line bore, wall schedule and service.
        sequence, spec, insulation : str or float, optional
            Bypass and drain line sequence, piping class and insulation.
        on : Stream or None, optional
            Material line from :meth:`connect` to put the station in.
        at : float or None, optional
            Position on that line, as for :meth:`add`.

        Returns
        -------
        ValveStation
            Handle to the members and the station's inlet and outlet.

        Raises
        ------
        ValueError
            If ``drains`` or ``bypass_over`` is invalid, options
            conflict, or the station cannot go in the ``on`` line.
        """
        # Undo every member if any step raises.
        with self._unchanged_if_it_raises():
            from pandid.inline import insert_station, split_point
            from pandid.portgeom import port_offset, resolve_size
            from pandid.stations import (
                BYPASS_ANCHORS, ROLE_WORDS, ValveStation, member_tag, member_mirror,
                station_number,
            )
            from pandid.units import Reducer, Tee, Valve

            if on is not None:
                split_point(self, on, at)  # refuse before any member is added
            elif at is not None:
                raise ValueError(f"{tag}: at= is a position on the line given by on=")
            if drains not in (0, 1, 2):
                raise ValueError(
                    f"{tag}: drains= is how many drain valves the station carries, 0, 1 "
                    f"or 2, one either side of the control valve, got {drains!r}"
                )
            if bypass and not isolation:
                raise ValueError(
                    f"{tag}: a bypass is tapped outside the isolation valves so the unit "
                    f"keeps running while the control valve is isolated, and this station "
                    f"has no isolation valves to tap outside of. Ask for isolation=True, "
                    f"or drop the bypass"
                )
            if (x is None) != (y is None):
                raise ValueError(
                    f"{tag}: a station is a run of devices on one line, so it is placed by "
                    f"an x and the run's centreline y together; got "
                    f"x={x!r}, y={y!r}"
                )
            # Run options given without x and y.
            stated = [
                f"{name}=" for name, given in (("mirrored", mirrored is not None),
                                               ("gap", gap is not None),
                                               ("bypass_rise", bypass_rise is not None),
                                               ("drain_drop", drain_drop is not None))
                if given
            ]
            if x is None and stated:
                named = ", ".join(stated)
                raise ValueError(
                    f"{tag}: {named} {'is' if len(stated) == 1 else 'are'} about the run a "
                    f"station is drawn along, and this station has no x/y to draw one: "
                    f"without them its members are laid out with every other unit on the "
                    f"sheet, ranked and faced by the layout engine. Give x= and y=, or "
                    f"drop {named}"
                )
            if bypass_over is not None and bypass_over not in BYPASS_ANCHORS:
                raise ValueError(
                    f"{tag}: bypass_over names the member the bypass valve stands over, "
                    f"one of {', '.join(BYPASS_ANCHORS)}, got {bypass_over!r}"
                )
            # Check that bypass_over names a kept member.
            _bypass_anchor_kept = {
                "upstream_isolation": isolation, "downstream_isolation": isolation,
                "reduction": reducers, "expansion": reducers, "control": True,
            }
            if bypass_over is not None and not _bypass_anchor_kept[bypass_over]:
                raise ValueError(
                    f"{tag}: bypass_over={bypass_over!r} names a member this station was "
                    f"told to leave out"
                )

            scheme = tag_scheme if tag_scheme is not None else self.valve_station_tag_scheme
            num = str(number) if number is not None else station_number(tag)

            def described(role: str) -> str:
                """Return a member's description.

                Parameters
                ----------
                role : str
                    Member role.

                Returns
                -------
                str
                    Description.
                """
                return f"{description} {ROLE_WORDS[role]}".strip()

            def valve(role: str, closed: bool = False) -> "Valve":
                """Add a member valve.

                Parameters
                ----------
                role : str
                    Member role.
                closed : bool, default=False
                    Whether the valve is normally closed.

                Returns
                -------
                Valve
                    The added valve.
                """
                unit = Valve(member_tag(scheme, role, tag, num),
                             description=described(role),
                             normal_position="closed" if closed else "open")
                self.add(unit)
                return unit

            def size_change(role: str) -> "Reducer":
                """Add the station's reducer or expander.

                Parameters
                ----------
                role : str
                    ``"reduction"`` or ``"expansion"``.

                Returns
                -------
                Reducer
                    The added reducer.
                """
                unit = Reducer(member_tag(scheme, role, tag, num),
                               description=described(role),
                               large_end="inlet" if role == "reduction" else "outlet")
                self.add(unit)
                return unit

            def tee(returns: bool = False) -> "Tee":
                """Add a station tee.

                Parameters
                ----------
                returns : bool, default=False
                    Whether the branch flows into the run.

                Returns
                -------
                Tee
                    The added tee.
                """
                unit = Tee(branch="inlet" if returns else "outlet")
                self.add(unit)
                return unit

            control = Valve(tag, variant=variant,
                            description=f"{description} Control Valve".strip())
            self.add(control)
            iso_a = valve("upstream_isolation") if isolation else None
            iso_b = valve("downstream_isolation") if isolation else None
            byp = valve("bypass", closed=True) if bypass else None
            dr_a = valve("upstream_drain", closed=True) if drains >= 1 else None
            dr_b = valve("downstream_drain", closed=True) if drains >= 2 else None
            red = size_change("reduction") if reducers else None
            exp = size_change("expansion") if reducers else None
            t_bya = tee() if bypass else None
            t_byb = tee(returns=True) if bypass else None
            t_dra = tee() if dr_a is not None else None
            t_drb = tee() if dr_b is not None else None

            # Members in flow order; a mirrored station reverses them.
            run = [u for u in (t_bya, iso_a, t_dra, red, control, exp, t_drb, iso_b, t_byb)
                   if u is not None]
            anchors = {"upstream_isolation": iso_a, "downstream_isolation": iso_b,
                       "reduction": red, "expansion": exp, "control": control}

            if x is not None and y is not None:
                # Apply the run defaults.
                mirrored = bool(mirrored)
                gap = DEFAULT_GAP if gap is None else gap
                bypass_rise = DEFAULT_BYPASS_RISE if bypass_rise is None else bypass_rise
                drain_drop = DEFAULT_DRAIN_DROP if drain_drop is None else drain_drop
                left: dict[int, float] = {}   # pinned left edge per member
                cursor = x
                for unit in (reversed(run) if mirrored else run):
                    unit.pin(x=cursor, mirrored=member_mirror(mirrored, unit in (t_bya, t_byb)))
                    unit.pin(port="inlet", y=y)
                    left[id(unit)] = cursor
                    cursor += resolve_size(unit)[0] + gap
                for junction, drain in ((t_dra, dr_a), (t_drb, dr_b)):
                    if junction is None or drain is None:
                        continue
                    # The drain leg ends at the valve.
                    drain.pin(orientation=90)
                    drain.pin(port="inlet",
                              x=left[id(junction)] + port_offset(junction, "branch")[0],
                              y=y + drain_drop)
                if byp is not None and t_bya is not None and t_byb is not None:
                    target = anchors[bypass_over] if bypass_over is not None else None
                    if target is not None:
                        centre = left[id(target)] + resolve_size(target)[0] / 2
                    else:
                        # Centre it on its own leg.
                        centre = sum(left[id(t)] + port_offset(t, "branch")[0]
                                     for t in (t_bya, t_byb)) / 2
                    byp.pin(mirrored="x" if mirrored else False)
                    byp.pin(x=centre - resolve_size(byp)[0] / 2)
                    byp.pin(port="inlet", y=y - bypass_rise)
                # Mark the station's own turns and mirrors as unstated.
                for drawn in (*run, byp, dr_a, dr_b):
                    if drawn is not None:
                        drawn._turn_stated = drawn._mirror_stated = False

            def branch_line(src: "Port", dst: "Port") -> Stream:
                """Connect a leg with the station's line number.

                Parameters
                ----------
                src, dst : Port
                    Leg ends.

                Returns
                -------
                Stream
                    The new stream.
                """
                return self.connect(src, dst, size=size, schedule=schedule, service=service,
                                    sequence=sequence, spec=spec, insulation=insulation)

            for upstream, downstream in zip(run, run[1:]):
                self.connect(upstream.outlet, downstream.inlet)
            if byp is not None and t_bya is not None and t_byb is not None:
                branch_line(t_bya.branch, byp.inlet)
                self.connect(byp.outlet, t_byb.branch)
            for junction, drain in ((t_dra, dr_a), (t_drb, dr_b)):
                if junction is not None and drain is not None:
                    branch_line(junction.branch, drain.inlet)

            hanging = {id(t_bya): byp, id(t_dra): dr_a, id(t_drb): dr_b}
            members: list["Unit"] = []
            for unit in run:
                members.append(unit)
                branch = hanging.get(id(unit))
                if branch is not None:
                    members.append(branch)
            station = ValveStation(
                control=control, upstream_isolation=iso_a, downstream_isolation=iso_b,
                reduction=red, expansion=exp, bypass=byp,
                upstream_drain=dr_a, downstream_drain=dr_b,
                tees=tuple(t for t in (t_bya, t_dra, t_drb, t_byb) if t is not None),
                members=tuple(members), inlet=run[0].inlet, outlet=run[-1].outlet,
            )
            from pandid.stations import StationAssembly

            self._station_assemblies.append(StationAssembly(
                station=station, mirrored=bool(mirrored),
                gap=DEFAULT_GAP if gap is None else gap,
                bypass_rise=DEFAULT_BYPASS_RISE if bypass_rise is None else bypass_rise,
                drain_drop=DEFAULT_DRAIN_DROP if drain_drop is None else drain_drop,
                bypass_over=bypass_over,
            ))
            if on is not None:
                insert_station(self, on, station, at=at)
            return station

    def add_component(self, component: "Component") -> "Component":
        """Register a chemical component.

        Parameters
        ----------
        component : Component
            Species to register.

        Returns
        -------
        Component
            The same component.
        """
        self.components.append(component)
        return component

    def connect(self, src: "Port | Unit", dst: "Port | Unit", *,
                kind: str | None = None,
                name: str | None = None, draw_as_recycle: bool = False,
                size: str | float | None = None, schedule: str | float | None = None,
                service: str | float | None = None,
                sequence: str | float | None = None, spec: str | float | None = None,
                insulation: str | float | None = None,
                ends: "str | tuple[str, str] | None" = None) -> Stream:
        """Connect two ports with a new stream.

        A process stream runs from an outlet to an inlet; a signal
        stream joins two signal ports, and either end may be a unit. Any
        line-number component but ``sequence`` shows a line number.

        Parameters
        ----------
        src : Port or Unit
            Source port, or a unit for a signal line.
        dst : Port or Unit
            Destination port, or a unit for a signal line.
        kind : str or None, optional
            One of :data:`~pandid.streams.STREAM_KINDS`; ``None`` infers
            it from the ports.
        name : str or None, optional
            Fixed stream name; ``None`` numbers it automatically.
        draw_as_recycle : bool, default=False
            Prefer this stream as a cycle's return line.
        size, schedule, service : str or float, optional
            Nominal bore, wall schedule and service.
        sequence, spec, insulation : str or float, optional
            Sequence (automatic if unset), piping class and insulation.
        ends : str, tuple[str, str] or None, optional
            ``connections`` style for both ends or ``(source, dest)``.

        Returns
        -------
        Stream
            The new stream.

        Raises
        ------
        TypeError
            If an end is neither a port nor a unit.
        ValueError
            If an argument is invalid or a port is already connected.
        """
        # Restore the sheet and both end units if anything raises.
        with self._unchanged_if_it_raises((self, *_port_bearers(src, dst))):
            src, dst, kind = self._resolve_connection(src, dst, kind=kind, ends=ends)
            # Writes start here.
            if src.stream is not None:
                src = src.owner.another_port(src)
            if dst.stream is not None:
                dst = dst.owner.another_port(dst)

            stream = Stream(
                name=name or "",  # numbered below when auto-named
                source=src,
                dest=dst,
                kind=kind,
                draw_as_recycle=draw_as_recycle,
                auto_named=not name,
                size=size,
                schedule=schedule,
                service=service,
                sequence=sequence,
                spec=spec,
                insulation=insulation,
                ends=ends,
            )
            src.stream = stream
            dst.stream = stream
            self.streams.append(stream)
            self._invalidate_layout()
            # Number this stream alone when possible, else every stream.
            if not self._number_appended(stream):
                self.renumber_streams()
            return stream

    def _resolve_connection(
        self, src: "Port | Unit", dst: "Port | Unit", *, kind: str | None,
        ends: "str | tuple[str, str] | None" = None,
        pending: "Sequence[Unit]" = (),
    ) -> "tuple[Port, Port, str]":
        """Resolve and check a connection.

        Parameters
        ----------
        src, dst : Port or Unit
            Ends as given to :meth:`connect`.
        kind : str or None
            Stream kind; ``None`` infers it from the ports.
        ends : str, tuple[str, str] or None, optional
            Joint styles to check.
        pending : Sequence[Unit], optional
            Units about to be added; they pass the same-sheet check.

        Returns
        -------
        tuple[Port, Port, str]
            Source port, destination port and kind.

        Raises
        ------
        TypeError
            If an end is neither a port nor a unit.
        ValueError
            If the connection is invalid.
        """
        if ends is not None:
            from pandid.render.svg import check_connections
            check_connections(ends)
        stated = kind is not None
        if kind is None:
            # Check as material; the inferred kind is applied last.
            kind = "material"
        elif kind not in STREAM_KINDS:
            raise ValueError(
                f"Stream kind must be one of {sorted(STREAM_KINDS)}, got {kind!r}"
            )
        src = _signal_end(src, kind, "source")
        dst = _signal_end(dst, kind, "destination")

        # Refuse a port joined to itself.
        if src is dst:
            raise ValueError(
                f"{src.owner.name}.{src.name} is both the source and the "
                f"destination; a stream needs two different nozzles to mean "
                f"anything"
            )
        # Only process ports have a direction.
        if src.role != "signal" and src.direction != "outlet":
            raise ValueError(
                f"source port {src.owner.name}.{src.name} must be an outlet, "
                f"got {src.direction!r}"
            )
        if dst.role != "signal" and dst.direction != "inlet":
            raise ValueError(
                f"destination port {dst.owner.name}.{dst.name} must be an inlet, "
                f"got {dst.direction!r}"
            )
        for port in (src, dst):
            if port.owner.flowsheet is not self and port.owner not in pending:
                raise ValueError(
                    "both units must be added to this flowsheet before connecting"
                )
        _check_signal_pairing(src, dst, kind)
        # Refuse a connected port unless its pool has another.
        for port in (src, dst):
            if port.stream is not None and not port.owner.has_another_port(port):
                raise ValueError(
                    f"port {port.owner.name}.{port.name} is already connected"
                )
        return src, dst, _inferred_kind(src, dst) if not stated else kind

    @classmethod
    def from_dict(cls, spec: dict) -> "Flowsheet":
        """Build a flowsheet from a spec dictionary.

        Parameters
        ----------
        spec : dict
            Spec in the format :mod:`pandid.spec` describes.

        Returns
        -------
        Flowsheet
            New flowsheet.

        Raises
        ------
        SpecError
            If an entry is invalid.
        """
        from pandid.spec import from_dict as _from_dict
        return _from_dict(spec)

    @classmethod
    def from_json(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a JSON spec file.

        Parameters
        ----------
        path : str or Path
            JSON file.

        Returns
        -------
        Flowsheet
            New flowsheet.

        Raises
        ------
        SpecError
            If the file is not valid JSON or the spec is invalid.
        """
        from pandid.spec import from_json as _from_json
        return _from_json(path)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a YAML spec file.

        Parameters
        ----------
        path : str or Path
            YAML file.

        Returns
        -------
        Flowsheet
            New flowsheet.

        Raises
        ------
        ImportError
            If PyYAML is not installed.
        SpecError
            If the file is not valid YAML or the spec is invalid.
        """
        from pandid.spec import from_yaml as _from_yaml
        return _from_yaml(path)

    def to_dict(self) -> dict:
        """Return the flowsheet's author intent as a JSON-safe spec.

        ``Flowsheet.from_dict(fs.to_dict())`` rebuilds an equivalent
        flowsheet.

        Returns
        -------
        dict
            Spec in the format :mod:`pandid.spec` describes.
        """
        from pandid.spec import to_dict as _to_dict
        return _to_dict(self)

    def layout(self, engine=None) -> None:
        """Lay out every unit, replacing any previous frames.

        Parameters
        ----------
        engine : object or None, optional
            Engine with ``layout(fs)``; ``None`` uses the default.
        """
        from pandid.layout import default_layout_engine

        self._mounted_layout = False
        if engine is None:
            engine = default_layout_engine
        engine.layout(self)
        self._layout_stale = False
        self._route_stale = True

    def route(self, router=None) -> None:
        """Route every stream, laying out first if needed.

        Attached instruments are placed and the sheet re-routed until
        neither moves, up to
        :data:`~pandid.layout.attach.MAX_PLACEMENT_PASSES` passes;
        ``route_converged`` records whether it settled.

        Parameters
        ----------
        router : object or None, optional
            Router with ``route(fs)``; ``None`` uses the default.
        """
        if self._layout_stale or any(u.frame is None for u in self.units):
            self.layout()
        if router is None:
            from pandid.routing import DefaultRouter
            router = DefaultRouter()
        from pandid.layout.attach import MAX_PLACEMENT_PASSES
        from pandid.layout.control import place_control
        router.route(self)
        # Place balloons and re-route until nothing moves; end on a
        # route.
        self.route_converged = False
        for _ in range(MAX_PLACEMENT_PASSES):
            if not place_control(self):
                self.route_converged = True
                break
            router.route(self)
        # Cleared last; a router that raises leaves routes stale.
        self._route_stale = False

    def _resolve_geometry(self) -> None:
        """Lay out and route where the geometry is missing or stale."""
        if self._layout_stale or any(u.frame is None for u in self.units):
            self.layout()
        if self._route_stale or any(s.route is None for s in self.streams):
            self.route()

    @staticmethod
    def _raise_on_errors(issues: list) -> None:
        """Raise one error listing every error-severity finding.

        Parameters
        ----------
        issues : list[Issue]
            Findings to check.

        Raises
        ------
        ValueError
            If any finding is an error.
        """
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise ValueError(
                "Flowsheet validation failed:\n"
                + "\n".join(f"  {e}" for e in errors)
            )

    @contextmanager
    def _unchanged_if_it_raises(self, objects: "Sequence[Any] | None" = None):
        """Restore objects to their entry state if the block raises.

        Parameters
        ----------
        objects : Sequence or None, optional
            Objects to guard; ``None`` means the sheet and its contents.

        Yields
        ------
        None
            Control to the guarded block.
        """
        saved = [(obj, _snapshot(obj))
                 for obj in ((self, *self.units, *self.streams)
                             if objects is None else objects)]
        try:
            yield
        except BaseException:
            for obj, state in saved:
                _restore(obj, state)
            raise

    def _prepare_to_draw(self, *, diagram: str | None, check: bool,
                         **arguments) -> None:
        """Number, check, lay out and route the sheet before drawing.

        Parameters
        ----------
        diagram : str or None
            Diagram type being drawn.
        check : bool
            Whether to validate the model and geometry.
        **arguments
            Other render arguments to check.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        """
        from pandid.document import _resolve_enclosure
        from pandid.render.svg import (check_render_arguments, draws_arrowheads,
                                       tabulates_boundary_flows)
        from pandid.validate import geometry_issues, model_issues

        # Check the stream-label enclosure.
        _resolve_enclosure(self.stream_labels.enclosure)
        self.renumber_streams()
        check_render_arguments(self, diagram=diagram, **arguments)
        self.warnings = []
        # Diagram type validate() defaults to, even with check=False.
        self._drawn_as = diagram
        found: list = []
        if check:
            found = model_issues(self, tabulates=tabulates_boundary_flows(diagram))
            self._raise_on_errors(found)
        self._resolve_geometry()
        if check:
            found += geometry_issues(self, arrows=draws_arrowheads(diagram))
            self.warnings = [i for i in found if i.severity == "warning"]
            self._raise_on_errors(found)

    def _stream_groups(self) -> "list[list[Stream]]":
        """Group material streams into runs through inline devices.

        A run passes from an inline device's inlet to its outlet unless
        the device sets ``new_line_number``.

        Returns
        -------
        list[list[Stream]]
            Runs in order of their first segment.
        """
        material = [s for s in self.streams if s.kind == "material"]
        pos = {id(s): i for i, s in enumerate(material)}  # Stream: unhashable
        parent = list(range(len(material)))

        def find(i):
            """Return the representative of a stream's group.

            Parameters
            ----------
            i : int
                Stream index.

            Returns
            -------
            int
                Index of the group's representative.
            """
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # Join each inline device's inlet run to its outlet run.
        for u in self.units:
            if u.kind in INLINE_KINDS and not getattr(u, "new_line_number", False):
                run = [u.ports.get("inlet"), u.ports.get("outlet")]
                ends = [pos[id(p.stream)] for p in run
                        if p is not None and p.stream is not None and id(p.stream) in pos]
                if len(ends) == 2:
                    parent[find(ends[0])] = find(ends[1])

        groups: dict = {}  # insertion order gives first-appearance order
        for i, s in enumerate(material):
            groups.setdefault(find(i), []).append(s)
        return list(groups.values())

    def _named_runs(self) -> "dict[str, list[Stream]]":
        """Group non-signal streams by name for the stream table.

        Returns
        -------
        dict[str, list[Stream]]
            Segments per name, in order of first appearance.
        """
        from pandid.streams import SIGNAL_KINDS

        runs: dict[str, list[Stream]] = {}
        for s in self.streams:
            if s.kind not in SIGNAL_KINDS:
                runs.setdefault(s.name, []).append(s)
        return runs

    def renumber_streams(self) -> None:
        """Assign stream and line numbers to every stream.

        A number carries through inline devices and a tee's run unless
        the unit sets ``new_line_number``. Material runs come first,
        then energy lines, then signal lines.

        Raises
        ------
        ValueError
            If a naming scheme cannot name a group.
        """
        with self._unchanged_if_it_raises():
            groups = self._stream_groups()
            names = []
            for place, group in enumerate(groups, 1):
                # Named groups still use up their place.
                names.append(self._name_group(group, place))
            self._tail = [s for s in self.streams if s.kind != "material"]
            self._number_tail(len(groups))
            # Cache for _number_appended().
            self._groups, self._group_names = groups, names
            self._group_of = {id(s): i for i, g in enumerate(groups) for s in g}

    def _number_appended(self, stream: "Stream") -> bool:
        """Number a just-connected stream incrementally.

        Parameters
        ----------
        stream : Stream
            Stream just added.

        Returns
        -------
        bool
            Whether it was numbered; ``False`` asks for a full pass.

        Raises
        ------
        ValueError
            If a naming scheme cannot name the stream's group.
        """
        groups, index = self._groups, self._group_of
        if groups is None:  # no full pass yet
            return False

        if stream.kind != "material":
            # Non-material lines are renumbered as a short tail.
            self._tail.append(stream)
            self._number_tail(len(groups))
            return True

        joined = self._joined_groups(stream, index)
        if joined is None or len(joined) > 1:
            return False

        if joined:
            where = joined[0]
            # Replace the list; the rollback guard restores the old one.
            groups[where] = group = [*groups[where], stream]
            index[id(stream)] = where
            # Rename the run; the new segment may add a line number.
            self._group_names[where] = self._name_group(group, where + 1)
            return True

        groups.append([stream])
        index[id(stream)] = len(groups) - 1
        self._group_names.append(self._name_group([stream], len(groups)))
        # One more run shifts the non-material lines after it.
        self._number_tail(len(groups))
        return True

    def _joined_groups(self, stream: "Stream", index: dict) -> "list[int] | None":
        """Return the cached groups a new material stream joins.

        Parameters
        ----------
        stream : Stream
            New material stream.
        index : dict
            Group index by ``id(stream)``.

        Returns
        -------
        list[int] or None
            Joined group indices, or ``None`` for an uncached peer.
        """
        found: list[int] = []
        for port in (stream.source, stream.dest):
            unit = port.owner
            if unit.kind not in INLINE_KINDS or getattr(unit, "new_line_number", False):
                continue
            inlet, outlet = unit.ports.get("inlet"), unit.ports.get("outlet")
            if port is inlet:
                peer = outlet
            elif port is outlet:
                peer = inlet
            else:
                continue  # a tee branch is not part of the run
            if peer is None or peer.stream is None or peer.stream is stream:
                continue
            if peer.stream.kind != "material":
                continue
            where = index.get(id(peer.stream))
            if where is None:
                return None
            if where not in found:
                found.append(where)
        return found

    def _name_group(self, group: "list[Stream]", place: int) -> str:
        """Name one group's segments for its place in the sequence.

        Parameters
        ----------
        group : list[Stream]
            Segments of one run.
        place : int
            1-based position in the sequence.

        Returns
        -------
        str
            The name given.

        Raises
        ------
        ValueError
            If a naming scheme cannot name the group.
        """
        with self._unchanged_if_it_raises(group):
            # Sequence and stream number share the place, not the start.
            sequence = str(self.line_number_start + place - 1)
            number = self.stream_number_start + place - 1
            for s in group:
                # Keep a sequence the author set.
                if s.sequence is None or s.sequence == s._auto_sequence:
                    s.sequence = s._auto_sequence = sequence
            # An explicit name on any segment names its whole group.
            name = next((s.name for s in group if not s.auto_named), None)
            if name is None:
                carrier = next((s for s in group if s.has_line_number), None)
                name = (_format_line_number(self.line_numbering_scheme, carrier)
                        if carrier is not None else
                        _format_stream_name(self.stream_naming_scheme, number))
            for s in group:
                if s.auto_named:
                    s.name = name
            return name

    def _number_tail(self, used: int) -> None:
        """Number non-material lines after the material runs.

        Energy lines come before signal lines.

        Parameters
        ----------
        used : int
            Places already taken.

        Raises
        ------
        ValueError
            If the stream naming scheme cannot name a line.
        """
        with self._unchanged_if_it_raises(self._tail):
            for s in sorted(self._tail, key=lambda s: s.kind != "energy"):
                if s.auto_named:
                    used += 1
                    self._name_group([s], used)

    def validate(self, *, diagram: str | None = None) -> list:
        """Return validation findings, errors first, then warnings.

        Geometric findings need frames and routes; before layout only
        model findings are reported. See :mod:`pandid.validate`.

        Parameters
        ----------
        diagram : str or None, optional
            ``"pfd"``, ``"p&id"`` or ``"bfd"``; ``None`` uses the last
            render's type, or ``"pfd"``.

        Returns
        -------
        list[Issue]
            Findings.
        """
        from pandid.render.svg import draws_arrowheads, tabulates_boundary_flows
        from pandid.validate import validate as _validate
        if diagram is None:
            diagram = self._drawn_as
        return _validate(self, arrows=draws_arrowheads(diagram),
                         tabulates=tabulates_boundary_flows(diagram))

    def to_svg(self, *, show_stream_table: bool | Literal["sheet"] = False,
               border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               connections: str | None = None,
               jump_direction: str = "vertical",
               crossing_style: str = "gap", debug: bool | float = False,
               check: bool = True) -> str:
        """Render the flowsheet to an SVG string.

        Lays out and routes first if needed. A call that raises leaves
        the sheet unchanged.

        Parameters
        ----------
        show_stream_table : bool or {"sheet"}, default=False
            ``True`` docks the stream table under the drawing;
            ``"sheet"`` draws the table as its own sheet.
        border : str or None, optional
            ``"none"`` or ``"zone"`` (ISO 5457 zone-ruled frame).
        diagram : str or None, optional
            ``"pfd"`` (default), ``"p&id"`` (or ``"pid"``) or ``"bfd"``.
        page_size : str or None, optional
            Sheet ``"A4"`` to ``"A0"``, or ``None`` to fit the drawing.
        connections : str or None, optional
            Joint marks on a P&ID: ``"none"`` (default), ``"flanged"``
            (nozzles, valves and inline fittings) or
            ``"flanged-at-nozzles"``. Reducers and tees stay unmarked.
        jump_direction : str, default="vertical"
            ``"vertical"`` or ``"horizontal"`` line carries the mark.
        crossing_style : str, default="gap"
            Crossing mark: ``"gap"``, ``"arc"`` or ``"plain"``.
        debug : bool or float, default=False
            Draw a debug grid and markers; a number sets the spacing.
        check : bool, default=True
            Validate; errors raise and warnings go to ``warnings``.

        Returns
        -------
        str
            SVG document.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        """
        with self._unchanged_if_it_raises():
            self._prepare_to_draw(
                diagram=diagram, check=check, show_stream_table=show_stream_table,
                border=border, page_size=page_size, connections=connections,
                jump_direction=jump_direction, crossing_style=crossing_style,
                debug=debug)
            from pandid.render.svg import SvgRenderer
            return SvgRenderer().render(
                self, show_stream_table=show_stream_table,
                border=border, diagram=diagram, page_size=page_size,
                connections=connections, jump_direction=jump_direction,
                crossing_style=crossing_style, debug=debug
            )

    def to_drawio(self, *, diagram: str | None = None,
                  page_size: str | None = None, border: str | None = None,
                  connections: str | None = None,
                  jump_direction: str = "vertical",
                  crossing_style: str = "gap",
                  show_stream_table: bool | Literal["sheet"] = False, check: bool = True) -> str:
        """Render the flowsheet to an editable draw.io document string.

        Each unit is a shape and each stream an edge. Lays out and
        routes first if needed.

        Parameters
        ----------
        diagram : str or None, optional
            As for :meth:`to_svg`.
        page_size : str or None, optional
            As for :meth:`to_svg`; ``None`` leaves the canvas unbounded.
        border : str or None, optional
            ``"zone"`` draws the frame and zone band.
        connections : str or None, optional
            As for :meth:`to_svg`.
        jump_direction : str, default="vertical"
            As for :meth:`to_svg`.
        crossing_style : str, default="gap"
            As for :meth:`to_svg`; ``"plain"`` writes no line jumps.
        show_stream_table : bool or {"sheet"}, default=False
            As for :meth:`to_svg`.
        check : bool, default=True
            As for :meth:`to_svg`.

        Returns
        -------
        str
            ``.drawio`` document.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        """
        with self._unchanged_if_it_raises():
            self._prepare_to_draw(
                diagram=diagram, check=check, show_stream_table=show_stream_table,
                border=border, page_size=page_size, connections=connections,
                jump_direction=jump_direction, crossing_style=crossing_style)
            from pandid.render.drawio import DrawioRenderer
            return DrawioRenderer().render(self, diagram=diagram,
                                           page_size=page_size, border=border,
                                           connections=connections,
                                           jump_direction=jump_direction,
                                           crossing_style=crossing_style,
                                           show_stream_table=show_stream_table)

    def render(self, path: str | Path, *, show_stream_table: bool | Literal["sheet"] = False,
               border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               connections: str | None = None,
               jump_direction: str = "vertical",
               crossing_style: str = "gap", debug: bool | float = False,
               check: bool = True) -> None:
        """Render the flowsheet and write it to a file.

        The extension selects the format: ``.svg`` (or none), ``.pdf``
        and ``.png`` (need ``pandid[pdf]``), or ``.drawio``. A call that
        writes no file leaves the flowsheet unchanged.

        Parameters
        ----------
        path : str or Path
            Output file.
        show_stream_table : bool or {"sheet"}, default=False
            As for :meth:`to_svg`.
        border : str or None, optional
            As for :meth:`to_svg`.
        diagram : str or None, optional
            As for :meth:`to_svg`.
        page_size : str or None, optional
            As for :meth:`to_svg`.
        connections : str or None, optional
            As for :meth:`to_svg`.
        jump_direction : str, default="vertical"
            As for :meth:`to_svg`.
        crossing_style : str, default="gap"
            As for :meth:`to_svg`.
        debug : bool or float, default=False
            As for :meth:`to_svg`; not for ``.drawio``.
        check : bool, default=True
            As for :meth:`to_svg`.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        ImportError
            If PDF or PNG output is requested without ``pandid[pdf]``.
        OSError
            If the file cannot be written.
        """
        # Guard the whole call, including the file write.
        with self._unchanged_if_it_raises():
            ext = Path(path).suffix.lower()
            # Check the extension before any layout.
            if ext not in _OUTPUT_FORMATS:
                raise ValueError(
                    f"Unsupported output format {ext!r}; use "
                    f"{', '.join(sorted(f for f in _OUTPUT_FORMATS if f))}"
                )
            if ext == ".drawio":
                # Refuse a debug overlay; debug=0 counts as off.
                if debug != 0:
                    raise ValueError(
                        "debug describe(s) a drawing sheet that "
                        "a .drawio file has no counterpart for: the coordinate "
                        "overlay is scaffolding rather than drawing. Render the "
                        "sheet to .svg/.pdf/.png, or drop these arguments"
                    )
                Path(path).write_text(
                    self.to_drawio(diagram=diagram, page_size=page_size,
                                   border=border, connections=connections,
                                   jump_direction=jump_direction,
                                   crossing_style=crossing_style,
                                   show_stream_table=show_stream_table,
                                   check=check), encoding="utf-8")
                return

            svg = self.to_svg(
                show_stream_table=show_stream_table, border=border,
                diagram=diagram, page_size=page_size, connections=connections,
                jump_direction=jump_direction, crossing_style=crossing_style,
                debug=debug, check=check,
            )
            if ext in ("", ".svg"):
                Path(path).write_text(svg, encoding="utf-8")
            else:  # .pdf or .png
                from pandid.render import export
                data = export.to_pdf(svg) if ext == ".pdf" else export.to_png(svg)
                Path(path).write_bytes(data)

    def _repr_svg_(self) -> str:
        """Return SVG for notebook display.

        Returns
        -------
        str
            SVG document.
        """
        return self.to_svg()

    def show(self, *, show_stream_table: bool | Literal["sheet"] = False,
             border: str | None = None,
             diagram: str | None = None, page_size: str | None = None,
             connections: str | None = None,
             jump_direction: str = "vertical",
             crossing_style: str = "gap", debug: bool | float = False,
             check: bool = True) -> None:
        """Render the flowsheet and show it.

        Opens a window that blocks until closed when a display and
        ``pandid[pdf]`` are available; otherwise opens the SVG in a
        browser. A preview that fails leaves the sheet unchanged.

        Parameters
        ----------
        show_stream_table : bool or {"sheet"}, default=False
            As for :meth:`to_svg`.
        border : str or None, optional
            As for :meth:`to_svg`.
        diagram : str or None, optional
            As for :meth:`to_svg`.
        page_size : str or None, optional
            As for :meth:`to_svg`.
        connections : str or None, optional
            As for :meth:`to_svg`.
        jump_direction : str, default="vertical"
            As for :meth:`to_svg`.
        crossing_style : str, default="gap"
            As for :meth:`to_svg`.
        debug : bool or float, default=False
            As for :meth:`to_svg`.
        check : bool, default=True
            As for :meth:`to_svg`.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        """
        # Guard the whole call, including the preview.
        with self._unchanged_if_it_raises():
            from pandid.render.preview import preview
            preview(self.to_svg(
                show_stream_table=show_stream_table, border=border,
                diagram=diagram, page_size=page_size, connections=connections,
                jump_direction=jump_direction, crossing_style=crossing_style,
                debug=debug, check=check,
            ), title=self.name)

    def __repr__(self) -> str:
        """Return a summary with the name and unit and stream counts.

        Returns
        -------
        str
            ``Flowsheet(name, units=n, streams=m)``.
        """
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
