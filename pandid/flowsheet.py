"""Define the flowsheet: the units, streams and loops of one drawing.

Units are added with :meth:`Flowsheet.add`; streams are created only by
:meth:`Flowsheet.connect`, which validates each connection and allows one
stream per port. The flowsheet also lays out, routes, validates and
renders the drawing.
"""

from __future__ import annotations
from contextlib import contextmanager
from math import isfinite
from numbers import Integral
from pathlib import Path
from string import Formatter
from typing import Any, Callable, Literal, TYPE_CHECKING, TypeVar

# Imported at runtime: every flowsheet builds its own table options.
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
    from pandid.geometry import Frame
    from pandid.loops import ControlLoop, Loop
    from pandid.layout.search import SearchResult
    from pandid.ports import Port
    from pandid.stations import ValveStation
    from pandid.units import Instrument, Unit

_ENERGY_ROLES = {"energy", "utility"}

#: Default line-number format: size, service, sequence and spec. A scheme may
#: also use ``{schedule}`` and ``{insulation}``.
DEFAULT_LINE_NUMBERING_SCHEME = "{size}-{service}-{sequence}-{spec}"

#: First automatic line sequence number.
DEFAULT_LINE_NUMBER_START = 1001

#: First automatic stream number, ``n`` in ``S{n}``.
DEFAULT_STREAM_NUMBER_START = 1

#: First loop number :meth:`Flowsheet.add_loop` allocates when none is given.
DEFAULT_LOOP_NUMBER_START = 101

#: Unit kinds that sit within a line rather than at its end. A line number
#: carries through them (:meth:`Flowsheet.renumber_streams`), and
#: :func:`~pandid.render.svg.flanged_joint` treats their ends as fittings,
#: not equipment nozzles. :data:`~pandid.render.svg._INLINE_BODIES` is the
#: subset bolted into the line.
INLINE_KINDS = frozenset({"valve", "reducer", "fitting", "tee"})

#: Containers a render may mutate in place. :func:`_restore` refills them
#: rather than replacing them, so references callers hold stay valid.
_CONTAINERS = (list, dict, set)


def _snapshot(obj) -> dict:
    """Save every attribute of an object for :func:`_restore`.

    Every attribute is saved, rather than a list of ones a render is known
    to write, so a new attribute cannot escape the restore.

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

    Containers are emptied and refilled in place, and each attribute points
    back at the original object, so references held elsewhere (such as a
    unit returned by ``fs.add()``) stay valid.

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


#: Output extensions :meth:`Flowsheet.render` writes. An empty extension
#: writes SVG. Checked before layout and again when writing.
_OUTPUT_FORMATS = frozenset({"", ".svg", ".pdf", ".png", ".drawio"})


def _inferred_kind(src: "Port", dst: "Port") -> str:
    """Return the stream kind implied by two ports when none is given.

    A stream between two energy or utility ports (such as a reactor's
    ``duty``) is an energy line; anything else is material.
    :meth:`Flowsheet._resolve_connection` applies this and
    :func:`pandid.spec.to_dict` uses it to decide when to write ``kind``.

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

    An unset component is dropped with the separator before it, so a line
    with no spec reads ``6"-P-1001`` and one with no size reads
    ``P-1001-SS``. Format specs apply, for example ``{sequence:0>4}``.

    Parameters
    ----------
    scheme : str or Callable[[Stream], str]
        Format string over :data:`~pandid.streams.LINE_NUMBER_FIELDS`, or a
        callable returning the line number.
    stream : Stream
        Stream to number.

    Returns
    -------
    str
        Line number.

    Raises
    ------
    ValueError
        If the scheme names an unknown component, or the result is empty.
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
    """Resolve one end of a signal connection given as a unit.

    ``fs.connect(ft305, fic305, kind="electric")`` connects to an
    instrument's signal pool. Any other unit must have exactly one signal
    port; a process stream must always name its port.

    Parameters
    ----------
    end : Port or Unit
        End as the caller gave it.
    kind : str
        Stream kind.
    which : str
        ``"source"`` or ``"destination"``, for messages and pool choice.

    Returns
    -------
    Port
        The port to connect.

    Raises
    ------
    TypeError
        If ``end`` is neither a port nor a unit.
    ValueError
        If a unit is given for a process stream, or has no signal port or
        several.
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
        # Use the signal pool, never ``pv`` (the process tap).
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
    """Return the units at a connection's ends and all their ports.

    Collected before either end is resolved, so
    :meth:`Flowsheet._unchanged_if_it_raises` guards them before any write.
    Every port is included because connecting may add a member to a port
    pool.

    Parameters
    ----------
    *ends : Port or Unit
        Ends as the caller gave them; anything else is ignored.

    Returns
    -------
    tuple
        The distinct units, then each of their ports.
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
    """Return only the keyword arguments that are not ``None``.

    :meth:`Flowsheet.add_control_loop` forwards placement through this so
    :meth:`Flowsheet.add_instrument` applies its own defaults.

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
    """Return the full functional code for one member of a control loop.

    The whole code is given (``"FIC"``, not ``"IC"``), as everywhere else
    in the API, so it can be checked against the loop's measured variable.

    Parameters
    ----------
    loop : Loop
        Loop the member belongs to.
    stated : str or None
        Code the author gave, or ``None`` to use ``default``.
    default : str
        Code composed from the loop.
    role : str
        Parameter name, for messages.

    Returns
    -------
    str
        Functional code.

    Raises
    ------
    ValueError
        If the code is empty, is only the measured variable, or opens with
        another variable.
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
    # Use the loop's own check, so the message matches add_instrument's.
    loop.check(letters)
    return letters


def _check_signal_pairing(src: "Port", dst: "Port", kind: str) -> None:
    """Check that a stream's kind matches the roles of its two ports.

    A signal line joins two signal ports; process piping joins two process
    ports.

    Parameters
    ----------
    src, dst : Port
        Source and destination ports.
    kind : str
        Stream kind.

    Raises
    ------
    ValueError
        If the ports mix signal and process roles, or the kind does not
        match them.
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


# Lets add() return the subclass it was given, keeping its typed ports.
_UnitT = TypeVar("_UnitT", bound="Unit")


def _whole_number(value: Any, name: str) -> int:
    """Return a number start as an ``int``, refusing anything else.

    Stream, line and loop numbers are integers, so a float (even ``1.0``),
    a ``Decimal``, a string or a ``bool`` is refused rather than drawn as
    ``S1.0``. Any integral type, such as ``numpy.int64``, is accepted.

    Parameters
    ----------
    value : Any
        Value to check.
    name : str
        Attribute name, for the error message.

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
        Declared control loops, in declaration order. Loops draw nothing
        and are kept out of ``units``.
    warnings : list[Issue]
        Warnings from the last render only; emptied before each render.
    route_converged : bool
        Whether the last ``route()`` settled its attached instruments
        within the pass limit.
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
    stream_naming_scheme, stream_number_start, line_numbering_scheme,
    line_number_start, loop_number_start, valve_station_tag_scheme
        Numbering settings; see :meth:`__init__`.
    auto_faces : bool
        Whether movable port faces are chosen automatically.
    """

    def __init__(
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
        """Create an empty flowsheet with its author-facing defaults.

        Parameters
        ----------
        name : str
            Drawing title.
        stream_naming_scheme : str or callable, default="S{n}"
            Format, or callable of the number, for generated stream names.
        stream_number_start : int, default=1
            First ``n`` in ``stream_naming_scheme``. Separate from
            ``line_number_start``.
        line_numbering_scheme : str or callable, default="{size}-{service}-{sequence}-{spec}"
            Format, or callable of the stream, for line numbers.
        line_number_start : int, default=1001
            First generated ``sequence`` component of a line number.
        loop_number_start : int, default=101
            First number :meth:`add_loop` allocates.
        valve_station_tag_scheme : str or callable, default="{letters}-{number}{suffix}"
            Format for valve station member tags; see
            :data:`~pandid.stations.DEFAULT_VALVE_STATION_TAG_SCHEME`.
        auto_faces : bool, default=True
            Whether movable port faces are chosen automatically.

        Raises
        ------
        TypeError
            If a number start is not an integer.
        """
        self.name = name
        self.stream_naming_scheme = stream_naming_scheme
        self.stream_number_start = stream_number_start
        self.line_numbering_scheme = line_numbering_scheme
        self.line_number_start = line_number_start
        self.loop_number_start = loop_number_start
        # Numbers add_loop() has allocated; kept apart from the start so a
        # later change to loop_number_start still applies.
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
        self._layout_search_result: SearchResult | None = None
        self._search_seed_frames: tuple[Frame, ...] | None = None
        self._coarse_layout_candidate = False
        self.unplaced_instruments: list = []
        # Frames and routes are cached between renders. Every mutation that
        # can move a box or a route calls _invalidate_layout(), which marks
        # both stale; layout() clears the first and leaves routes stale.
        # Both start false: an empty sheet has nothing stale.
        self._layout_stale = False
        self._route_stale = False
        # Cache of the last full numbering pass, written by
        # renumber_streams() and read by _number_appended().
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
        """Mark the cached layout and routes stale.

        Every mutation that can move a drawn box or route calls this,
        directly or through :meth:`pandid.units.Unit._invalidate_layout`.
        It is cheap and safe to call when unsure: layout restarts from the
        pins, so an unneeded re-layout draws the same sheet.
        """
        self._layout_stale = True
        self._route_stale = True
        self._layout_search_result = None
        self._search_seed_frames = None

    @property
    def auto_faces(self) -> bool:
        """Return whether movable port faces are chosen automatically.

        See :mod:`pandid.layout.faces`. When ``False``, every port uses its
        symbol's face or the face set with
        :meth:`~pandid.units.Unit.nozzle`. Setting it invalidates layout.

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
        """Return the first generated ``sequence`` component of a line number.

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
        """Set the first loop number :meth:`add_loop` allocates.

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

    def add(self, unit: _UnitT) -> _UnitT:
        """Add a unit to the sheet.

        Tags must be unique, except for symbols that show one thing in
        several places: an interlock or logic square, and a utility header
        flag (``Feed`` or ``Product`` with ``header=True``). A
        :class:`~pandid.units.Tee` may also repeat, as it draws no tag. A
        repeat keeps its drawn tag but is given a unique name such as
        ``I-1 (2)``. A refused unit leaves the sheet unchanged.

        Parameters
        ----------
        unit : Unit
            Unit to add.

        Returns
        -------
        Unit
            The same unit, with its own type.

        Raises
        ------
        ValueError
            If the unit is already on this or another sheet, or its name is
            taken by a unit it may not repeat.
        """
        clash = self._refuse_unaddable(unit)
        if clash is not None:
            # Derive the new name from the tag; a tee has none, so use its name.
            unit.name = self._repeat_name(unit.tag or unit.name)
        unit.flowsheet = self
        self.units.append(unit)
        self._invalidate_layout()
        return unit

    def _refuse_unaddable(self, unit: "Unit",
                          alongside: "Sequence[Unit]" = ()) -> "Unit | None":
        """Check that a unit may join the sheet, before anything is written.

        Composite calls such as :meth:`add_control_loop` ask this of every
        unit they will add before adding any, so a refusal leaves the sheet
        unchanged.

        Parameters
        ----------
        unit : Unit
            Unit to check.
        alongside : Sequence[Unit], optional
            Units the same call is about to add; their names count as taken.

        Returns
        -------
        Unit or None
            The unit this one repeats, or ``None``.

        Raises
        ------
        ValueError
            If the unit is already on a sheet, or its name clashes with a
            unit it may not repeat.
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
            ``"<tag> (n)"`` with the smallest free ``n`` from 2.
        """
        taken = {u.name for u in self.units}
        n = 2
        while f"{tag} ({n})" in taken:
            n += 1
        return f"{tag} ({n})"

    def add_loop(self, variable: str, number: str | int | None = None) -> "Loop":
        """Declare a control loop and return its handle.

        A loop is identified by its variable and number together, so
        ``add_loop("F", 101)`` and ``add_loop("L", 101)`` are two loops.
        Without a number, the sheet allocates the next one from a single
        series starting at ``loop_number_start``::

            fs = Flowsheet("A300", loop_number_start=301)
            press = fs.add_loop("P")   # P-301
            temp = fs.add_loop("T")    # T-302

        Members still type their own letters, and the loop checks the first
        one::

            loop = fs.add_loop("F", 303)
            fe = fs.add(units.Fitting(loop.element("FE"),
                                      variant="venturi"))
            ft = fs.add_instrument("FT", loop, sensing=fe, at="N",
                                   offset=70)
            cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

        A loop draws nothing and is not in :attr:`units`; see
        :mod:`pandid.loops`. Loop numbers are never renumbered, and
        :meth:`to_dict` writes allocated numbers explicitly.

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
        """Build and check the loop :meth:`add_loop` would declare.

        Nothing is written, so :meth:`add_control_loop` can check every
        change before making any.

        Parameters
        ----------
        variable : str
            ISA measured-variable letter.
        number : str, int or None, optional
            Loop number, or ``None`` to take the next allocated number.

        Returns
        -------
        tuple[Loop, bool]
            The loop and whether its number was allocated.

        Raises
        ------
        ValueError
            If the loop is already declared, including when the allocated
            number collides with a typed one.
        """
        from pandid.loops import Loop

        # One series per sheet across all variables, as on the reference
        # sheet (P-301, T-302, F-303). The counter does not skip numbers
        # typed by hand; a collision raises instead.
        allocated = number is None
        if number is None:  # the same test twice, so the narrowing survives to Loop()
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

        The only writer of :attr:`loops` and the allocation counter, so a
        refused declaration uses up no number.

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
        """Move the loop counter past every declared numeric loop number.

        The spec reader calls this after loading loops, so a reloaded sheet
        continues its series rather than reusing numbers. It only moves the
        counter forward, so a gap in the series is not filled. Non-numeric
        numbers such as ``"301A"`` are ignored.
        """
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

        The tag is ``type`` and ``number`` (``add_instrument("FT", 101)``
        gives ``FT-101``). ``number`` may be a :class:`~pandid.loops.Loop`
        or :class:`~pandid.loops.ControlLoop`, which supplies the number
        and checks ``type`` against the measured variable.

        At most one anchor may be given:

        - ``sensing=``: the balloon reads from this host. An impulse line is
          drawn to a field device on a process host, otherwise a dashed
          instrument connection.
        - ``acting_on=``: the balloon commands this host, such as a trip
          square under its valve. Drawn dashed.
        - ``near=``: the balloon is only placed here; nothing is drawn. Use
          :meth:`connect` for its signals.

        With no anchor the balloon is laid out like any other unit. A
        refused call leaves the sheet unchanged.

        Parameters
        ----------
        type : str
            Functional letters, such as ``"FT"``.
        number : str, int, Loop or ControlLoop, default=""
            Loop number or loop.
        sensing, acting_on, near : Stream or Unit or None, optional
            Anchor, as above.
        at : float, str or None, optional
            Fraction along a stream host, or face of a unit host.
        offset : float, default=45.0
            Distance from the tap to the balloon centre.
        angle : float, default=90.0
            Branch angle from the host's reference direction.
        variant : str, default="default"
            Balloon symbol.
        **kwargs
            Passed to :class:`~pandid.units.Instrument`, such as
            ``display``.

        Returns
        -------
        Instrument
            The added balloon.

        Raises
        ------
        ValueError
            If the letters, variant, anchors, placement or tag are invalid,
            or a host is on another sheet.

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
        """Build and anchor the balloon :meth:`add_instrument` would add.

        The balloon is not added. Every refusal except the tag clash
        (:meth:`add`) and host ownership is made here, and nothing outside
        the new balloon is written. Host ownership is left to the caller,
        because :meth:`add_control_loop` hangs a controller on a
        transmitter it has not added yet.

        Parameters
        ----------
        type, number, sensing, acting_on, near, at, offset, angle, variant, **kwargs
            As for :meth:`add_instrument`.

        Returns
        -------
        Instrument
            The anchored balloon.
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.units import Instrument

        # Accept a ControlLoop handle as well as a Loop.
        if isinstance(number, (Loop, ControlLoop)):
            number.check(type)
            number = number.number
        inst = Instrument(type, number, variant=variant, **kwargs)
        host, relation = self._anchor(inst, sensing, acting_on, near)
        if host is not None:
            inst.attach(host, at=at, offset=offset, angle=angle, relation=relation)
        return inst

    def _refuse_foreign(self, role: str, thing: "Stream | Port | Unit") -> None:
        """Check that a unit, port or stream belongs to this sheet.

        An object from another sheet would draw names this sheet's spec
        never declares, so the sheet could not be read back. Streams are
        compared by identity, because equal streams on two sheets compare
        equal.

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
        """Record a wired inline device's preferred position on its run.

        Parameters
        ----------
        stream : Stream
            Material segment entering the inline device.
        at : float
            Preferred fraction of the complete run from source to destination.

        Raises
        ------
        ValueError
            If the segment or its destination is ineligible.
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

    def place_on(self, run: Stream, device: _UnitT, *, at: float = 0.5) -> _UnitT:
        """Insert a simple inline device on a material run.

        The original stream remains the run's stable handle. Its physical
        segments and the device are added to this flowsheet in flow order.

        Parameters
        ----------
        run : Stream
            Existing material run or handle returned by an earlier insertion.
        device : Unit
            Fresh two-port valve, reducer, or fitting.
        at : float, default=0.5
            Preferred fraction of the complete run.

        Returns
        -------
        Unit
            The inserted device.

        Raises
        ------
        ValueError
            If the run, device, or fraction cannot be inserted safely.
        """
        from pandid.inline import insert_device

        return insert_device(self, run, device, at=at)

    def place_valve_station_on(self, run: Stream, tag: str, *, at: float = 0.5,
                               **station_options) -> "ValveStation":
        """Build and place a valve station on a material run.

        Parameters
        ----------
        run : Stream
            Original material run handle.
        tag : str
            Control valve tag used to name the station members.
        at : float, default=0.5
            Preferred fraction of the complete run.
        **station_options : Any
            Options accepted by ``add_valve_station`` other than coordinates.

        Returns
        -------
        ValveStation
            The station handle with its members wired into the run.

        Raises
        ------
        ValueError
            If the run, fraction, or station options are invalid.
        """
        from dataclasses import replace

        from pandid.inline import insert_station

        if (isinstance(at, bool) or not isinstance(at, (int, float))
                or not isfinite(at) or not 0 < at < 1):
            raise ValueError("station fraction must be a finite number between 0 and 1")
        if "x" in station_options or "y" in station_options:
            raise ValueError("stream-relative stations do not accept x or y")
        local = {}
        for key, default in (("gap", DEFAULT_GAP),
                             ("bypass_rise", DEFAULT_BYPASS_RISE),
                             ("drain_drop", DEFAULT_DRAIN_DROP)):
            value = station_options.pop(key, default)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value <= 0):
                raise ValueError(f"{key} must be a positive finite number")
            local[key] = float(value)
        mirrored = station_options.pop("mirrored", False)
        if not isinstance(mirrored, bool):
            raise ValueError("mirrored must be a boolean")
        with self._unchanged_if_it_raises():
            station = self.add_valve_station(tag, **station_options)
            index = next(i for i, assembly in enumerate(self._station_assemblies)
                         if assembly.station is station)
            self._station_assemblies[index] = replace(
                self._station_assemblies[index], mirrored=mirrored, **local,
            )
            insert_station(self, run, station, at=at)
        return station

    def _anchor(self, inst: "Instrument", sensing, acting_on, near):
        """Return the one anchor an :meth:`add_instrument` call named.

        Parameters
        ----------
        inst : Instrument
            Balloon being built, for messages.
        sensing, acting_on, near : Stream, Unit or None
            Anchor arguments.

        Returns
        -------
        tuple
            ``(host, relation)``, or ``(None, "sensing")`` when none was
            named.

        Raises
        ------
        ValueError
            If more than one anchor was named.
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

        A primary element (such as an orifice plate or venturi) and its
        balloon are one instrument shown twice. The element stops drawing
        its tag and the balloon carries it, hung on a solid impulse line,
        as on the reference sheet::

            fe303 = fs.add(units.Fitting(flow303.element("FE"),
                                         variant="venturi"))
            fs.add_balloon(fe303, at="S", offset=46)
            ft303 = fs.add_instrument("FT", flow303, near=fe303.balloon,
                                      at="S", offset=45)

        The element keeps its name for the equipment list; the balloon is
        named like a repeat, such as ``FE-303 (2)``.

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
            If the element is not on this sheet, already has a balloon, or
            has no tag.
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
        # Set before add(), which allows the shared tag; see Instrument.repeats.
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
        """Add a transmitter, controller and signal lines around a final element.

        One call replaces :meth:`add_loop`, two :meth:`add_instrument` calls
        and two :meth:`connect` calls::

            loop = fs.add_control_loop("F", 101, measuring=feed,
                                       acting_on=fv)
            loop.transmitter     # FT-101
            loop.controller      # FIC-101
            loop.final_element   # the ControlValve passed in

        The final control element must already be on the sheet; this does
        not create one. Letters follow from the measured variable (``"F"``
        gives ``FT`` and ``FIC``) unless a whole functional code is given.
        Placement arguments left out use :meth:`add_instrument`'s defaults,
        and the standoff resolver in :mod:`pandid.layout.attach` keeps
        balloons clear. Members are ordinary units and can be pinned. Every
        check runs before the first write, so a refused call leaves the
        sheet and the loop counter unchanged. Cascade, ratio, split-range
        and override loops are built by hand.

        Parameters
        ----------
        variable : str or Loop
            ISA measured-variable letter, or a loop declared on this sheet.
        number : str, int or None, optional
            Loop number when ``variable`` is a letter; ``None`` allocates
            one.
        measuring : Stream or Unit
            What the transmitter reads, anchored as ``sensing=``.
        acting_on : Port or Unit
            Final control element, or its signal port.
        at : float, str or None, optional
            Transmitter tap: a fraction along a stream, or a face of a unit.
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
            If a declared loop is also given a number or belongs to another
            sheet, a functional code is invalid, ``measuring`` or
            ``acting_on`` is on another sheet, or any composed call would
            refuse.
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.ports import Port

        # Check everything first; nothing is written until the commit below.
        # The checks are the ones add() and connect() make, called from the
        # methods that own them.
        if isinstance(variable, Loop):
            if number is not None:
                raise ValueError(
                    f"loop {variable.name} is already declared and carries its "
                    f"number, so number={number!r} here is a second answer to a "
                    f"settled question. Pass the loop on its own, or pass "
                    f"{variable.variable!r} and {number!r} and let this declare it"
                )
            # Compare by identity: an equal loop from another sheet is not ours.
            if not any(declared is variable for declared in self.loops):
                raise ValueError(
                    f"loop {variable.name} was not declared on flowsheet "
                    f"{self.name!r}. A loop is a namespace belonging to one sheet, so "
                    f"pass the handle this sheet's add_loop() returned -- or pass "
                    f"{variable.variable!r} and {variable.number!r} and let this "
                    f"declare it here"
                )
            # None: the loop is already declared, so nothing is registered.
            loop, allocates = variable, None
        else:
            loop, allocates = self._new_loop(variable, number)
        transmitter_code = _functional_code(
            loop, transmitter_letters, f"{loop.variable}T", "transmitter_letters")
        controller_code = _functional_code(
            loop, controller_letters, f"{loop.variable}IC", "controller_letters")
        self._refuse_foreign("measuring", measuring)
        self._refuse_foreign("acting_on", acting_on)
        # Build but do not add. The transmitter comes first because the
        # controller hangs on it and balloons resolve in the order added.
        transmitter = self._build_instrument(
            transmitter_code, loop, sensing=measuring,
            **_stated(at=at, offset=offset, angle=angle))
        # near=, not sensing=: the measurement signal below is the only line.
        controller = self._build_instrument(
            controller_code, loop, near=transmitter,
            variant=controller_variant,
            **_stated(at=controller_at, offset=controller_offset))
        self._refuse_unaddable(transmitter)
        # Check the controller's tag against the pending transmitter too.
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
    ) -> "ValveStation":
        """Build a wired control valve station.

        See :mod:`pandid.stations` for the arrangement. With ``x`` and
        ``y`` every member is pinned; without them the layout engine places
        the station as one assembly when its run has a clear straight
        corridor. ``mirrored``, ``gap``, ``bypass_rise`` and ``drain_drop``
        describe a drawn run, so they are refused without ``x`` and ``y``.

        Parameters
        ----------
        tag : str
            Control valve tag, from which member tags are derived.
        x, y : float or None, optional
            Station left edge and run centreline; give both or neither.
        mirrored : bool or None, optional
            Pipe the pinned run east to west. Left unstated, the run is
            piped west to east.
        variant : str, default="control"
            Control valve symbol.
        number : str, int or None, optional
            Number for member tags; defaults to the control tag's number.
        isolation, reducers, bypass : bool, default=True
            Include isolation valves, reducers and a bypass. A bypass needs
            isolation valves.
        drains : int, default=2
            Number of drain valves: 0, 1 or 2.
        description : str, default=""
            Service word prefixed to member descriptions.
        bypass_over : str or None, optional
            Main member to centre the bypass valve over; one of
            :data:`~pandid.stations.BYPASS_ANCHORS`.
        tag_scheme : str, callable or None, optional
            Member tag format; defaults to the sheet's
            ``valve_station_tag_scheme``.
        gap, bypass_rise, drain_drop : float or None, optional
            Spacing for a pinned station; defaults from
            :mod:`pandid.stations`.
        size, schedule, service, sequence, spec, insulation : str, float or None, optional
            Line-number components for the bypass and drain legs.

        Returns
        -------
        ValveStation
            Handle to the members and the station's inlet and outlet.

        Raises
        ------
        ValueError
            If ``drains`` is out of range, a bypass lacks isolation, only one
            of ``x`` and ``y`` is given, run options are given without them,
            or ``bypass_over`` names an unknown or omitted member.
        """
        from pandid.portgeom import port_offset, resolve_size
        from pandid.stations import (
            BYPASS_ANCHORS, ROLE_WORDS, ValveStation, member_tag, member_mirror,
            station_number,
        )
        from pandid.units import Reducer, Tee, Valve

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
        # These describe a drawn run, which an unpinned station does not have;
        # the engine lays out its members. Each defaults to None, so any value
        # given, mirrored=False included, is named in the refusal.
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
        # Check bypass_over against the flags before any member is added.
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
                Station description followed by the role words.
            """
            return f"{description} {ROLE_WORDS[role]}".strip()

        def valve(role: str, closed: bool = False) -> "Valve":
            """Add a member valve.

            Parameters
            ----------
            role : str
                Member role.
            closed : bool, default=False
                Whether it is normally closed.

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
            """Add the reducer into or the expander out of the control valve.

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
                Whether the branch returns flow to the run.

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

        # Members in flow order; a mirrored station draws this order reversed.
        run = [u for u in (t_bya, iso_a, t_dra, red, control, exp, t_drb, iso_b, t_byb)
               if u is not None]
        anchors = {"upstream_isolation": iso_a, "downstream_isolation": iso_b,
                   "reduction": red, "expansion": exp, "control": control}

        if x is not None and y is not None:
            # Apply the run defaults now that the run is drawn.
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

        def branch_line(src: "Port", dst: "Port") -> Stream:
            """Connect a bypass or drain leg with the station's line number.

            Parameters
            ----------
            src, dst : Port
                Ends of the leg.

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

        A process stream runs from an outlet to an inlet. A signal stream
        joins two signal ports (a valve's ``actuator``, an instrument's
        ``pv``, ``sig_in`` or ``sig_out``); either end of a signal stream
        may be given as a unit (``fs.connect(ft305, fic305,
        kind="electric")``), and an instrument provides a free signal port
        from its pool. The returned stream already carries the number it is
        drawn with (see :meth:`renumber_streams`). A refused call leaves
        the sheet unchanged, including other streams' numbers.

        Parameters
        ----------
        src : Port or Unit
            Source port, or a unit for a signal line.
        dst : Port or Unit
            Destination port, or a unit for a signal line.
        kind : str or None, optional
            One of :data:`~pandid.streams.STREAM_KINDS`. ``None`` infers
            ``"energy"`` between two energy or utility ports and
            ``"material"`` otherwise; a stated kind is never changed.
            Energy streams are numbered after material ones.
        name : str or None, optional
            Fixed stream name; ``None`` numbers it automatically.
        draw_as_recycle : bool, default=False
            Prefer this stream as a cycle's return line.
        size, schedule, service, sequence, spec, insulation : str, float or None, optional
            Line-number components: nominal bore, wall schedule, service,
            sequence (automatic unless given), piping class and insulation.
            Any of them except ``sequence`` makes the stream show a line
            number.
        ends : str, tuple[str, str] or None, optional
            Joint style for both ends, or for ``(source, dest)``, from
            :data:`~pandid.render.svg.CONNECTIONS`; overrides the sheet's
            ``connections``. Joints are drawn only on a P&ID, and never at a
            boundary flag, an instrument or on a signal line.

        Returns
        -------
        Stream
            The new stream.

        Raises
        ------
        ValueError
            If the kind, ports, directions or line-number scheme are
            invalid, or a port is already connected.
        """
        # Guard the sheet and both end units: numbering renames other streams
        # and another_port() may add a port to a unit.
        with self._unchanged_if_it_raises((self, *_port_bearers(src, dst))):
            return self._connect(
                src, dst, kind=kind, name=name,
                draw_as_recycle=draw_as_recycle, size=size, schedule=schedule,
                service=service, sequence=sequence, spec=spec,
                insulation=insulation, ends=ends)

    def _connect(self, src: "Port | Unit", dst: "Port | Unit", *,
                 kind: str | None, name: str | None, draw_as_recycle: bool,
                 size: "str | float | None", schedule: "str | float | None",
                 service: "str | float | None", sequence: "str | float | None",
                 spec: "str | float | None", insulation: "str | float | None",
                 ends: "str | tuple[str, str] | None") -> Stream:
        """Create the stream for :meth:`connect`, inside its rollback guard.

        Parameters
        ----------
        src, dst, kind, name, draw_as_recycle, size, schedule, service, sequence, spec, insulation, ends
            As for :meth:`connect`.

        Returns
        -------
        Stream
            The new, numbered stream.
        """
        src, dst, kind = self._resolve_connection(src, dst, kind=kind, ends=ends)
        # Writes start here; another_port() adds a member to a port pool.
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
        # Number now so the returned stream shows its drawn number. Number
        # only this stream when possible; a full pass per connect() would
        # make building a sheet quadratic.
        if not self._number_appended(stream):
            self.renumber_streams()
        return stream

    def _resolve_connection(
        self, src: "Port | Unit", dst: "Port | Unit", *, kind: str | None,
        ends: "str | tuple[str, str] | None" = None,
        pending: "Sequence[Unit]" = (),
    ) -> "tuple[Port, Port, str]":
        """Resolve and check a connection's ports and kind without writing.

        Ports are returned as named, not as the pool members they may be
        swapped for, because taking a pool member would add a port.

        Parameters
        ----------
        src, dst : Port or Unit
            Ends as given to :meth:`connect`.
        kind : str or None
            Kind as given; ``None`` is inferred from the ports.
        ends : str, tuple[str, str] or None, optional
            Joint styles to check.
        pending : Sequence[Unit], optional
            Units the calling operation is about to add; they pass the
            same-sheet check.

        Returns
        -------
        tuple[Port, Port, str]
            Source port, destination port and kind.

        Raises
        ------
        ValueError
            If the connection is invalid.
        """
        if ends is not None:
            from pandid.render.svg import check_connections
            check_connections(ends)
        stated = kind is not None
        if kind is None:
            # Check as material; the inferred kind is applied at the end.
            kind = "material"
        elif kind not in STREAM_KINDS:
            raise ValueError(
                f"Stream kind must be one of {sorted(STREAM_KINDS)}, got {kind!r}"
            )
        src = _signal_end(src, kind, "source")
        dst = _signal_end(dst, kind, "destination")

        # A signal port has no direction, so check self-connection explicitly.
        if src is dst:
            raise ValueError(
                f"{src.owner.name}.{src.name} is both the source and the "
                f"destination; a stream needs two different nozzles to mean "
                f"anything"
            )
        # Only process ports have a direction; a signal stream's direction is
        # its source and dest.
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
        # A connected port is refused unless it belongs to a pool (an
        # instrument's signal ports). Both are checked before either is taken.
        for port in (src, dst):
            if port.stream is not None and not port.owner.has_another_port(port):
                raise ValueError(
                    f"port {port.owner.name}.{port.name} is already connected"
                )
        # Infer the kind only when none was stated.
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
            If an entry is invalid; it is a :class:`ValueError`.
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
        """
        from pandid.spec import from_json as _from_json
        return _from_json(path)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a YAML spec file.

        Requires the ``yaml`` extra.

        Parameters
        ----------
        path : str or Path
            YAML file.

        Returns
        -------
        Flowsheet
            New flowsheet.
        """
        from pandid.spec import from_yaml as _from_yaml
        return _from_yaml(path)

    def to_dict(self) -> dict:
        """Return the flowsheet's author intent as a JSON-safe spec.

        ``Flowsheet.from_dict(fs.to_dict())`` rebuilds an equivalent
        flowsheet. Computed coordinates and routes are not written.

        Returns
        -------
        dict
            Spec in the format :mod:`pandid.spec` describes.
        """
        from pandid.spec import to_dict as _to_dict
        return _to_dict(self)

    def layout(self, engine=None) -> None:
        """Lay out every unit, replacing any previous frames.

        Always runs, even when nothing changed. Routes become stale, so the
        next :meth:`route` or render routes again.

        Parameters
        ----------
        engine : object or None, optional
            Layout engine with a ``layout(fs)`` method. ``None`` selects the
            default engine, which also enables the refinement and search in
            :meth:`route`.
        """
        from pandid.layout import default_layout_engine

        self._default_layout = engine is None or engine is default_layout_engine
        self._coarse_layout_candidate = False
        self._refinement_attempted = False
        self._layout_search_result = None
        self._search_seed_frames = None
        if engine is None:
            engine = default_layout_engine
        engine.layout(self)
        self._layout_stale = False
        self._route_stale = True

    def route(self, router=None) -> None:
        """Route every stream, laying out first if needed.

        Attached instruments are placed and the sheet re-routed until
        neither moves, up to
        :data:`~pandid.layout.attach.MAX_PLACEMENT_PASSES`; a sheet that
        does not settle sets ``route_converged`` to ``False``, reported by
        :meth:`validate`. With the default router and engine, bounded
        refinement and layout search then run, keeping a change only when
        the routed drawing improves without new defects.

        Parameters
        ----------
        router : object or None, optional
            Router with a ``route(fs)`` method. ``None`` selects the default
            router and enables refinement.
        """
        if self._layout_stale or any(u.frame is None for u in self.units):
            self.layout()
        if router is not None and self._coarse_layout_candidate:
            from pandid.layout import default_layout_engine

            default_layout_engine.layout(self, use_coarse=False)
            self._layout_stale = False
            self._route_stale = True
        self._layout_search_result = None
        self._search_seed_frames = None
        default_router = router is None
        from pandid.layout.stages import process_units

        canonical_frames = all(
            unit.frame is not None and unit._slot is not None
            and unit.frame.x == unit._slot.x and unit.frame.y == unit._slot.y
            for unit in process_units(self)
        )
        if router is None:
            from pandid.routing import DefaultRouter
            router = DefaultRouter()
        from pandid.layout.attach import MAX_PLACEMENT_PASSES
        from pandid.layout.control import place_control
        router.route(self)
        # A balloon sits on its host's routed path and then obstructs other
        # routes, so repeat to a fixed point. Always end on a route.
        self.route_converged = False
        for _ in range(MAX_PLACEMENT_PASSES):
            if not place_control(self):
                self.route_converged = True
                break
            router.route(self)
        # Cleared last, so a router that raises leaves routes stale.
        self._route_stale = False
        if (default_router and getattr(self, "_default_layout", False)
                and not self._refinement_attempted):
            from pandid.layout.trials import refine_default
            self._refinement_attempted = True
            refine_default(self)
        if default_router and self._coarse_layout_candidate:
            from pandid.layout.coarse import keep_if_better
            keep_if_better(self)
        if default_router and getattr(self, "_default_layout", False):
            row_baseline = None
            if canonical_frames:
                import copy

                from pandid.layout.coarse import has_free_station
                from pandid.layout.trials import refine_rows

                if (not has_free_station(self)
                        and not any(stream._logical_to is not None for stream in self.streams)):
                    row_baseline = copy.deepcopy(self)
                    if not refine_rows(self):
                        row_baseline = None
            from pandid.layout.search import SearchBudget, search_layout

            budget = SearchBudget(4, 4, 16)
            search_layout(self, budget)
            if row_baseline is not None:
                from pandid.layout.trials import _publish_candidate, row_final_better

                search_layout(row_baseline, budget)
                if not row_final_better(row_baseline, self):
                    _publish_candidate(self, row_baseline)
            # Only explicit searches report budget status during validation.
            self._layout_search_result = None

    def _resolve_geometry(self) -> None:
        """Lay out and route only if the cached geometry is missing or stale.

        A sheet rendered twice without changes is laid out and routed once.
        :meth:`layout` marks routes stale, so a re-layout always re-routes.
        """
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

        A render numbers streams, replaces ``warnings``, lays out and
        routes. If it then fails, for example on a bad page size or a
        full disk, the sheet must be left as the caller had it. Every
        attribute of every guarded object is saved (:func:`_snapshot`),
        not a list of known writes, so new writes are covered too. A
        successful block keeps all its changes, including cached geometry.

        :meth:`render` and :meth:`show` wrap their whole bodies, including
        the file write; :meth:`to_svg` and :meth:`to_drawio` wrap theirs.
        Guards nest safely.

        Parameters
        ----------
        objects : Sequence or None, optional
            Objects the operation may write. ``None`` guards the flowsheet,
            every unit and every stream. Per-stream operations pass a small
            set, because guarding everything per call makes building a sheet
            quadratic: :meth:`connect` passes the sheet and its end units.
            An empty sequence guards nothing.

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

        Steps, in order:

        0. Reject an unknown stream-label enclosure.
        1. Number the streams, so findings quote drawn names.
        2. Check the render arguments
           (:func:`pandid.render.svg.check_render_arguments`).
        3. Check the model (:func:`pandid.validate.model_issues`).
        4. Lay out and route (:meth:`_resolve_geometry`).
        5. Check the geometry (:func:`pandid.validate.geometry_issues`).

        Arguments and the model are checked before layout because a model
        the validator rejects (such as ``pin(x=nan)``) cannot be laid out,
        and because layout writes to the sheet. Steps 0 and 2 always run;
        ``check=False`` skips steps 3 and 5. ``warnings`` is replaced after
        the argument check, so a refused render keeps the previous render's
        warnings; with ``check=False`` it is left empty.

        Parameters
        ----------
        diagram : str or None
            Diagram type being drawn.
        check : bool
            Whether to validate the model and geometry.
        **arguments
            Other render arguments, passed to
            :func:`~pandid.render.svg.check_render_arguments`.

        Raises
        ------
        ValueError
            If an argument is invalid or validation finds an error.
        """
        from pandid.document import _resolve_enclosure
        from pandid.render.svg import (check_render_arguments, draws_arrowheads,
                                       tabulates_boundary_flows)
        from pandid.validate import geometry_issues, model_issues

        # Check the sheet's own label setting before writing anything.
        _resolve_enclosure(self.stream_labels.enclosure)
        # Number before the model check, which reads stream names.
        self.renumber_streams()
        # After numbering, because the stream table is measured from drawn
        # names; before layout, so a refusal costs no layout.
        check_render_arguments(self, diagram=diagram, **arguments)
        # Replace warnings only after the arguments pass, so a refused render
        # keeps the last successful render's warnings.
        self.warnings = []
        # Record the diagram type for validate(), even with check=False.
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

        A run passes from an inline device's ``inlet`` to its ``outlet``
        unless the device sets ``new_line_number``; a tee's branch starts
        its own run. :meth:`renumber_streams` gives each group one number,
        and validation uses the groups to tell a run drawn in segments from
        two runs that share a name. Segments with one name but separate
        groups are allowed.

        Returns
        -------
        list[list[Stream]]
            Groups in order of their first segment, each in connection
            order.
        """
        material = [s for s in self.streams if s.kind == "material"]
        pos = {id(s): i for i, s in enumerate(material)}  # Stream: unhashable
        parent = list(range(len(material)))

        def find(i):
            """Return the representative of a stream's group.

            Parameters
            ----------
            i : int
                Index into the material streams.

            Returns
            -------
            int
                Representative index, with the path compressed.
            """
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # Join inlet to outlet by name; a tee's branch is not part of the run.
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

        Unlike :meth:`_stream_groups`, every segment carrying one name is
        one entry however it was named. The stream table and validation
        both use this, so they agree on what one column is.

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

        Runs on every :meth:`connect` and before each render, so a stream's
        name is the drawn name. A number carries through inline valves,
        reducers, fittings and the run of a tee (see
        :meth:`_stream_groups`); set ``unit.new_line_number = True`` to
        break it. A group with an explicitly named segment takes that name
        but still uses its place in the sequence. A group whose first
        segment carrying line-number components has them is named by its
        line number.

        Material runs are numbered first, then energy lines, then signal
        lines, in one sequence. A number may still equal a name the author
        typed; validation reports ``stream-name-reused``. If a naming
        scheme raises, every stream keeps its previous name.

        Raises
        ------
        ValueError
            If a naming scheme cannot name a group.
        """
        with self._unchanged_if_it_raises():
            self._renumber_streams()

    def _renumber_streams(self) -> None:
        """Number every stream and cache the groups for :meth:`connect`."""
        groups = self._stream_groups()
        names = []
        for place, group in enumerate(groups, 1):
            # Named groups still use their place, so counted numbers cannot
            # repeat a name the counter has passed.
            names.append(self._name_group(group, place))
        self._tail = [s for s in self.streams if s.kind != "material"]
        self._number_tail(len(groups))
        # Cache for _number_appended().
        self._groups, self._group_names = groups, names
        self._group_of = {id(s): i for i, g in enumerate(groups) for s in g}

    def _number_appended(self, stream: "Stream") -> bool:
        """Number the stream :meth:`connect` just added without a full pass.

        A full pass per connect made building a sheet quadratic. Three
        cases:

        - The stream starts a new run: it becomes the last group, and the
          non-material lines after it shift by one.
        - It extends one existing run: only that run is renamed.
        - It joins two runs: later groups move, so a full pass is needed.

        Names always come from :meth:`_name_group`, as in the full pass.

        Parameters
        ----------
        stream : Stream
            Stream just added.

        Returns
        -------
        bool
            Whether it was numbered; ``False`` means the caller must run
            :meth:`renumber_streams`.
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
            # Replace the list rather than append, so the rollback guard can
            # restore it.
            groups[where] = group = [*groups[where], stream]
            index[id(stream)] = where
            # Rename from the segments: the new one may add a line number.
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

        Uses the same inlet-to-outlet rule as :meth:`_stream_groups`.

        Parameters
        ----------
        stream : Stream
            New material stream.
        index : dict
            Group index by ``id(stream)``.

        Returns
        -------
        list[int] or None
            Indices of joined groups, or ``None`` when a neighbour has no
            cached group and a full pass is needed.
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

        The only place a group's name is decided. Segments are restored if
        naming raises.

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
        """
        with self._unchanged_if_it_raises(group):
            return self._name_group_now(group, place)

    def _name_group_now(self, group: "list[Stream]", place: int) -> str:
        """Name one group's segments, without the rollback guard.

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
        """
        # The line sequence and stream number share the place but not the start.
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
                    # A callable gets the same number a format string does.
                    self.stream_naming_scheme(number)
                    if callable(self.stream_naming_scheme)
                    else self.stream_naming_scheme.format(n=number))
        for s in group:
            if s.auto_named:
                s.name = name
        return name

    def _number_tail(self, used: int) -> int:
        """Number non-material lines after the places material runs used.

        Energy lines come before signal lines, each in creation order. Only
        automatically named lines take a place. Lines are restored if
        naming raises.

        Parameters
        ----------
        used : int
            Places already used.

        Returns
        -------
        int
            Places used after numbering the tail.
        """
        with self._unchanged_if_it_raises(self._tail):
            for s in sorted(self._tail, key=lambda s: s.kind != "energy"):
                if s.auto_named:
                    used += 1
                    self._name_group([s], used)
        return used

    def validate(self, *, diagram: str | None = None) -> list:
        """Return validation findings, errors first, then warnings.

        Errors are contradictions the engine cannot honour, such as
        overlapping pins; warnings are imperfections, such as a route
        through a unit or a large detour. Geometric findings need frames and
        routes, so call this after :meth:`route` or a render; before layout
        only model findings are reported. See :mod:`pandid.validate`.

        Parameters
        ----------
        diagram : str or None, optional
            ``"pfd"``, ``"p&id"`` or ``"bfd"``. ``None`` uses the diagram
            type of the last render, or ``"pfd"`` before any render. On a
            P&ID nozzles crowding arrowheads are not reported, and
            ``stream-table-missing`` (ISO 10628-1 4.3.2 d) applies only to
            a PFD.

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

        Lays out and routes first if the geometry is missing or stale. The
        title block and annotations are drawn whatever the border. A call
        that raises leaves the sheet unchanged.

        Parameters
        ----------
        show_stream_table : bool or {"sheet"}, default=False
            ``True`` docks the stream property table at the foot of the
            drawing. ``"sheet"`` draws the table as its own sheet, with a
            border, title strip and drawing number, instead of the diagram;
            render the two to separate files. ``fs.stream_table`` sets its
            sizing and title.
        border : str or None, optional
            ``"none"`` (the default) or ``"zone"`` for the zone-ruled frame
            of ISO 5457 4.4 (letters top to bottom, numerals left to right,
            A1 at top left).
        diagram : str or None, optional
            ``"pfd"`` (the default), ``"p&id"`` (also ``"pid"``) or
            ``"bfd"``. A P&ID draws process lines without arrowheads.
        page_size : str or None, optional
            ``"A4"`` to ``"A0"`` for a sheet of exactly that size, with the
            drawing fitted to it; ``None`` sizes the sheet to the drawing.
        connections : str or None, optional
            Joint marks: ``"none"`` (the default), ``"flanged"`` (every
            equipment nozzle and both sides of every valve and inline
            fitting) or ``"flanged-at-nozzles"`` (nozzles only). Reducers
            and tees are welded and never marked. Drawn on a P&ID only (ISO
            15519-2 Table 5); ``connect(..., ends=...)`` overrides one line.
            See :func:`~pandid.render.svg.flanged_joint`.
        jump_direction : str, default="vertical"
            Which of two crossing lines carries the mark: ``"vertical"`` or
            ``"horizontal"``.
        crossing_style : str, default="gap"
            Crossing mark for the whole sheet. ``"gap"`` interrupts the
            marking line (ISO 10628-1 5.3.4), which removes a short length
            of run either side. ``"arc"`` bridges it with a semicircle.
            ``"plain"`` draws both lines straight through (ISO 15519-1
            12.5). A crossing too near a corner for its mark is drawn
            unmarked and reported as ``crossing-unmarked``.
        debug : bool or float, default=False
            Draw the coordinate overlay under the diagram: a ruled grid, a
            marker at every pinned point and a marker on every port.
            ``True`` uses 50-unit spacing; a number sets it.
        check : bool, default=True
            Validate: model checks before layout and routing, geometric
            checks after. Errors raise; warnings are stored on
            ``warnings``. See :meth:`_prepare_to_draw`.

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
        """Render the flowsheet to a draw.io document string.

        The result is an editable model: each unit is a draw.io shape and
        each stream an edge between its connection points, so it can be
        edited in draw.io (diagrams.net) and exported to Visio. Equipment
        uses draw.io's own P&ID stencils (see ``NOTICE``); symbols pandid
        draws itself, such as balloons, junctions, off-page flags and
        built-to-size shapes, are approximated with built-in shapes (see
        :mod:`pandid.render.drawio`). Columnar furniture and the stream
        table become draw.io tables. Lays out and routes first if needed.
        There is no debug overlay.

        Parameters
        ----------
        diagram : str or None, optional
            As for :meth:`to_svg`.
        page_size : str or None, optional
            Sheet size; the furniture docks to the page and the drawing is
            fitted to it. ``None`` keeps drawing coordinates on an unbounded
            canvas.
        border : str or None, optional
            ``"zone"`` draws the frame and zone band. The zone grid is a
            snapshot: moving shapes in draw.io does not update references to
            zones.
        connections : str or None, optional
            As for :meth:`to_svg`.
        jump_direction : str, default="vertical"
            As for :meth:`to_svg`; draw.io line-jump styles are written on
            both crossing edges.
        crossing_style : str, default="gap"
            As for :meth:`to_svg`. ``"arc"`` and ``"gap"`` map to draw.io
            line-jump styles; ``"plain"`` writes none.
        show_stream_table : bool or {"sheet"}, default=False
            As for :meth:`to_svg`.
        check : bool, default=True
            Validate: model checks before layout and routing, geometric
            checks after. Errors raise; warnings are stored on
            ``warnings``. See :meth:`_prepare_to_draw`.

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

        The extension selects the format: ``.svg`` (or none), ``.pdf`` and
        ``.png`` (need ``pandid[pdf]``; see :mod:`pandid.render.export`), or
        ``.drawio`` (see :meth:`to_drawio`). A call that writes no file,
        whether refused or failing to write, leaves the flowsheet unchanged
        (see :meth:`_unchanged_if_it_raises`). To write a drawing and its
        stream-table sheet::

            fs.render("pfd.svg", page_size="A1")
            fs.render("stream_table.svg", page_size="A1",
                      show_stream_table="sheet")

        Parameters
        ----------
        path : str or Path
            Output file.
        show_stream_table : bool or {"sheet"}, default=False
            ``True`` docks the stream property table at the foot of the
            drawing. ``"sheet"`` draws the table as its own sheet, with a
            border, title strip and drawing number, instead of the diagram;
            render the two to separate files. ``fs.stream_table`` sets its
            sizing and title.
        border : str or None, optional
            ``"none"`` (the default) or ``"zone"`` for the zone-ruled frame
            of ISO 5457 4.4 (letters top to bottom, numerals left to right,
            A1 at top left).
        diagram : str or None, optional
            ``"pfd"`` (the default), ``"p&id"`` (also ``"pid"``) or
            ``"bfd"``. A P&ID draws process lines without arrowheads.
        page_size : str or None, optional
            ``"A4"`` to ``"A0"`` for a sheet of exactly that size, with the
            drawing fitted to it; ``None`` sizes the sheet to the drawing.
        connections : str or None, optional
            Joint marks: ``"none"`` (the default), ``"flanged"`` (every
            equipment nozzle and both sides of every valve and inline
            fitting) or ``"flanged-at-nozzles"`` (nozzles only). Reducers
            and tees are welded and never marked. Drawn on a P&ID only (ISO
            15519-2 Table 5); ``connect(..., ends=...)`` overrides one line.
            See :func:`~pandid.render.svg.flanged_joint`.
        jump_direction : str, default="vertical"
            Which of two crossing lines carries the mark: ``"vertical"`` or
            ``"horizontal"``.
        crossing_style : str, default="gap"
            Crossing mark for the whole sheet. ``"gap"`` interrupts the
            marking line (ISO 10628-1 5.3.4), which removes a short length
            of run either side. ``"arc"`` bridges it with a semicircle.
            ``"plain"`` draws both lines straight through (ISO 15519-1
            12.5). A crossing too near a corner for its mark is drawn
            unmarked and reported as ``crossing-unmarked``.
        debug : bool or float, default=False
            Draw the coordinate overlay (not for ``.drawio``) under the diagram: a ruled grid, a
            marker at every pinned point and a marker on every port.
            ``True`` uses 50-unit spacing; a number sets it.
        check : bool, default=True
            Validate: model checks before layout and routing, geometric
            checks after. Errors raise; warnings are stored on
            ``warnings``. See :meth:`_prepare_to_draw`.

        Raises
        ------
        ValueError
            If the extension or an argument is invalid, ``debug`` is given
            for ``.drawio``, or validation finds an error.
        ImportError
            If PDF or PNG output is requested without ``pandid[pdf]``.
        OSError
            If the file cannot be written.
        """
        # Guard the whole call: to_svg() and to_drawio() return strings, and
        # the conversion and write here can still fail.
        with self._unchanged_if_it_raises():
            ext = Path(path).suffix.lower()
            # Check the extension before any layout.
            if ext not in _OUTPUT_FORMATS:
                raise ValueError(
                    f"Unsupported output format {ext!r}; use "
                    f"{', '.join(sorted(f for f in _OUTPUT_FORMATS if f))}"
                )
            if ext == ".drawio":
                # The debug overlay has no draw.io counterpart, so refuse it.
                # Compare with the default: debug=0 is not a request.
                sheet_only = [
                    name for name, given, default in (
                        ("debug", debug, False),
                    ) if given != default
                ]
                if sheet_only:
                    raise ValueError(
                        f"{', '.join(sheet_only)} describe(s) a drawing sheet that "
                        f"a .drawio file has no counterpart for: the coordinate "
                        f"overlay is scaffolding rather than drawing. Render the "
                        f"sheet to .svg/.pdf/.png, or drop these arguments"
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
            else:  # .pdf / .png; anything else was refused before the render
                from pandid.render import export
                data = export.to_pdf(svg) if ext == ".pdf" else export.to_png(svg)
                Path(path).write_bytes(data)

    def _repr_svg_(self) -> str:
        """Return SVG for inline display in IPython and Jupyter.

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

        Takes the same keywords as :meth:`render` (``tests/test_show.py``
        keeps the signatures equal). Opens a resizable window and blocks
        until it closes when a display and ``pandid[pdf]`` are available;
        otherwise opens the SVG in a browser and prints why. A headless
        machine takes the browser path without hanging. See
        :mod:`pandid.render.preview`. A preview that fails leaves the sheet
        unchanged.

        Parameters
        ----------
        show_stream_table : bool or {"sheet"}, default=False
            ``True`` docks the stream property table at the foot of the
            drawing. ``"sheet"`` draws the table as its own sheet, with a
            border, title strip and drawing number, instead of the diagram;
            render the two to separate files. ``fs.stream_table`` sets its
            sizing and title.
        border : str or None, optional
            ``"none"`` (the default) or ``"zone"`` for the zone-ruled frame
            of ISO 5457 4.4 (letters top to bottom, numerals left to right,
            A1 at top left).
        diagram : str or None, optional
            ``"pfd"`` (the default), ``"p&id"`` (also ``"pid"``) or
            ``"bfd"``. A P&ID draws process lines without arrowheads.
        page_size : str or None, optional
            ``"A4"`` to ``"A0"`` for a sheet of exactly that size, with the
            drawing fitted to it; ``None`` sizes the sheet to the drawing.
        connections : str or None, optional
            Joint marks: ``"none"`` (the default), ``"flanged"`` (every
            equipment nozzle and both sides of every valve and inline
            fitting) or ``"flanged-at-nozzles"`` (nozzles only). Reducers
            and tees are welded and never marked. Drawn on a P&ID only (ISO
            15519-2 Table 5); ``connect(..., ends=...)`` overrides one line.
            See :func:`~pandid.render.svg.flanged_joint`.
        jump_direction : str, default="vertical"
            Which of two crossing lines carries the mark: ``"vertical"`` or
            ``"horizontal"``.
        crossing_style : str, default="gap"
            Crossing mark for the whole sheet. ``"gap"`` interrupts the
            marking line (ISO 10628-1 5.3.4), which removes a short length
            of run either side. ``"arc"`` bridges it with a semicircle.
            ``"plain"`` draws both lines straight through (ISO 15519-1
            12.5). A crossing too near a corner for its mark is drawn
            unmarked and reported as ``crossing-unmarked``.
        debug : bool or float, default=False
            Draw the coordinate overlay under the diagram: a ruled grid, a
            marker at every pinned point and a marker on every port.
            ``True`` uses 50-unit spacing; a number sets it.
        check : bool, default=True
            Validate: model checks before layout and routing, geometric
            checks after. Errors raise; warnings are stored on
            ``warnings``. See :meth:`_prepare_to_draw`.
        """
        # Guard the whole call: the preview can fail after to_svg() returns.
        with self._unchanged_if_it_raises():
            from pandid.render.preview import preview
            preview(self.to_svg(
                show_stream_table=show_stream_table, border=border,
                diagram=diagram, page_size=page_size, connections=connections,
                jump_direction=jump_direction, crossing_style=crossing_style,
                debug=debug, check=check,
            ), title=self.name)

    def __repr__(self) -> str:
        """Return a summary with the name and unit and stream counts."""
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
