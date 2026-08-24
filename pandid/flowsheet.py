"""The top-level container, and the truth about connectivity.

Units are added with ``add()``; streams are created only through
``connect()``, which validates the connection and enforces the
one-stream-per-port rule.
"""

from __future__ import annotations
from pathlib import Path
from string import Formatter
from typing import Any, Callable, TYPE_CHECKING, TypeVar

# A runtime import and not a TYPE_CHECKING one: every flowsheet builds
# its own StreamTableOptions. pandid.document imports nothing from this
# package, so there is no cycle to route around.
from pandid.document import StreamTableOptions
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

#: Size, service, sequence and spec: the four parts almost every site's
#: line number opens with. ``{insulation}`` and ``{schedule}`` are there
#: for a scheme that names them.
DEFAULT_LINE_NUMBERING_SCHEME = "{size}-{service}-{sequence}-{spec}"

#: Line sequences conventionally start well clear of 1, so the drawing
#: reads 1001 rather than 1 out of the box.
DEFAULT_LINE_NUMBER_START = 1001

#: Where ``S{n}`` starts counting.
DEFAULT_STREAM_NUMBER_START = 1

#: Where :meth:`Flowsheet.add_loop` starts counting when it is left to
#: allocate. Three digits because a loop series belongs to a plant area,
#: so an author still has to say which area this sheet is, exactly as
#: they do for a line sequence; this only decides what the drawing reads
#: like until they do.
DEFAULT_LOOP_NUMBER_START = 101

#: The unit kinds that sit *in* a run rather than at the end of one:
#: piping components, not equipment. Two rules turn on the one fact that
#: these interrupt a line without ending it, and ask this set rather
#: than each keeping a copy -- :meth:`Flowsheet.renumber_streams`
#: carries one line number through a valve, and
#: :func:`~pandid.render.svg.flanged_joint` reads an end as something
#: other than an equipment nozzle.
#:
#: Which of these get *bolted* into the line is a different fact with a
#: set of its own: see :data:`~pandid.render.svg._INLINE_BODIES`, a
#: strict subset of this one.
INLINE_KINDS = frozenset({"valve", "reducer", "fitting", "tee"})


def _format_line_number(scheme: "str | Callable[[Stream], str]", stream: Stream) -> str:
    """Assemble a line number from the components the author set.

    A component left unset drops out, and so does the text introducing
    it, so a line with no spec reads ``6"-P-1001`` rather than
    ``6"-P-1001-``, and a line with no size reads ``P-1001-SS`` rather
    than ``-P-1001-SS``. A format spec still applies, which is how a
    site pads its sequence: ``"{size}-{service}-{sequence:0>4}"``.
    """
    if callable(scheme):
        return scheme(stream)
    parts = stream.line_components()
    out: list[str] = []
    pending = ""  # literal text held back until a component earns it
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
        # `pending` is the literal between this component and the last
        # surviving one -- unless nothing has survived yet, in which case
        # it only ever separated this component from one dropped ahead of
        # it (or from nothing at all), and there is nothing for it to join.
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
    return f"{port.owner.name}.{port.name}"


def _signal_end(end: "Port | Unit", kind: str, which: str) -> "Port":
    """The connection at one end, where the caller named a unit.

    ``fs.connect(ft305, fic305, kind="electric")`` is the spelling this
    exists for: a signal may meet a balloon anywhere, and the balloon
    mints a connection per line, so there is one sensible answer.
    Process piping always names its nozzle, since which nozzle is the
    whole question.

    Where a unit has several signal connections, this refuses rather
    than picking. Two that are not a pool are two different things (a
    valve station's control valve and its own instruments), and guessing
    between them draws a line to the wrong device.
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
        # The pool, and never ``pv``: an instrument's tap on the process
        # is a different kind of edge from a line between two
        # instruments, and it is named where it is meant. See
        # :class:`pandid.units.Instrument`.
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


def _stated(**kwargs: "float | str | None") -> dict[str, Any]:
    """Only the arguments the caller actually gave.

    :meth:`Flowsheet.add_control_loop` forwards placement to
    :meth:`Flowsheet.add_instrument`, and it must forward *nothing* for
    a keyword left out: repeating ``add_instrument``'s defaults in the
    helper's own signature would put a second copy of every standoff in
    the package, and the two would drift the first time one moved.
    Issue #439 asks for exactly this: the helper states no distance of
    its own, and #428's standoff resolver keeps the balloons apart.
    """
    return {name: value for name, value in kwargs.items() if value is not None}


def _functional_code(loop: "Loop", stated: str | None, default: str, role: str) -> str:
    """The functional letters one member of a control loop carries.

    The **whole** code, ``FIC`` and not the ``IC`` that follows the
    ``F``. Two reasons, and the second is the one that settles it.

    It is the spelling everything else in the package takes -- ``type``
    on :meth:`Flowsheet.add_instrument`, :meth:`~pandid.loops.Loop.tag`,
    :meth:`~pandid.loops.Loop.element`, ``Instrument("FIC", 101)`` -- so
    a suffix here would be the one place an author spells instrument
    letters without their variable.

    And it is the only spelling that can be *checked*. Every string is a
    valid suffix, so ``controller_letters="FIC"`` -- what the engineer
    calls the instrument and would therefore type -- composed ``FFIC``
    and nothing on the sheet could tell (issue #448): a misleading
    parameter fails silently where an absent one fails loudly. A whole
    code is held to the loop's measured variable by
    :meth:`~pandid.loops.Loop.check`, so the same typo now raises at the
    line that wrote it.

    Left out, the code is composed from the loop, which is what keeps
    the measured variable typed once on the ordinary loop.
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
    # The measured-variable check is the loop's own, not a second copy:
    # it quotes the offending string, spells the corrected code, and is
    # the identical message the long-hand `add_instrument(letters, loop)`
    # gives for the identical mistake.
    loop.check(letters)
    return letters


def _check_signal_pairing(src: "Port", dst: "Port", kind: str) -> None:
    """Raise unless the stream's kind matches what its two ports are.

    A signal port is a terminal for a measurement or a command: a
    valve's stem, an instrument's tap and its two signal connections.
    Nothing flows through one, so a signal line runs between two of them
    and process fluid between two nozzles.
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


# What :meth:`Flowsheet.add` hands back: the very class it was given,
# not the base. A plain ``-> Unit`` would throw the subclass away at
# the one call each unit passes through, and with it every nozzle
# :mod:`pandid.units` declares (``fs.add(Pump(...)).suction``).
_UnitT = TypeVar("_UnitT", bound="Unit")


class Flowsheet:
    """A diagram's topology: units, streams and components."""

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
        self.name = name
        self.stream_naming_scheme = stream_naming_scheme
        # The ``{n}`` in ``stream_naming_scheme``, offset. Not its
        # neighbour below, which moves a different number on a different
        # label: `line_number_start` moves the ``sequence`` *component*
        # of a LINE number, the ``1001`` inside ``6"-P-1001-A1A``, where
        # this moves the whole of a STREAM number, the ``S1`` a PFD
        # draws in a flag and a stream table keys its columns on. A PFD
        # numbering S100 upward carries no line numbers at all.
        self.stream_number_start = stream_number_start
        self.line_numbering_scheme = line_numbering_scheme
        self.line_number_start = line_number_start
        # Where `add_loop()` starts counting when the author leaves the
        # number to it. See that method for why the counter is naive.
        self.loop_number_start = loop_number_start
        # How many numbers `add_loop()` has handed out. Two fields
        # rather than one running total so the start stays
        # authoritative: it is what `to_dict()` writes and what an
        # author moves, and a total seeded from it at construction would
        # ignore a later move.
        self._loops_allocated = 0
        # How a valve station spells its members' tags out of its
        # control valve's. Set here for a whole sheet, overridable per
        # station.
        self.valve_station_tag_scheme = valve_station_tag_scheme
        self.auto_faces = auto_faces
        self.units: list = []
        self.streams: list[Stream] = []
        self.components: list = []
        # Declared control loops, in declaration order. Kept apart from
        # `units`: layout, routing, validation, the renderer and the
        # equipment list all iterate `units` unconditionally, and a loop
        # draws nothing.
        self.loops: list["Loop"] = []
        # Soft findings from the last render, and only from it:
        # `_prepare_to_draw` empties this before each one. A caller who
        # wants two renders' findings copies the list after each --
        # accumulating them here would leave no way to tell a finding
        # about the drawing in hand from one about a drawing that has
        # since been fixed, and `check=False` would report an older
        # render's list as though it were this one's.
        self.warnings: list = []
        # Did the last route() settle its attached instruments, or run
        # out of passes still moving them? Read by validate(), which
        # carries the answer onto `warnings`.
        self.route_converged: bool = True
        # The attached instruments the last placement sweep could put
        # nowhere, because nothing in their host chain ever resolved.
        # Set by `pandid.layout.attach.place_attached`, which is the
        # only thing that knows; read by validate(), which reports each
        # as `instrument-unplaced`. Empty until layout has run, so a
        # balloon that is merely waiting for layout is not a finding.
        self.unplaced_instruments: list = []
        # Does the resolved geometry still answer for this model? A
        # Frame and a Route are CACHED -- laying a sheet out and routing
        # it costs far more than drawing it, and a script that renders
        # the same sheet to .svg and .drawio should pay once -- so the
        # render entry points reuse what is already there. That is only
        # sound while nothing the engine reads has changed since, which
        # is the invariant these two hold: EVERY mutation that can move
        # a drawn box or a routed run says so through
        # `_invalidate_layout()`, and a stage that is stale re-runs
        # before the next drawing comes out. Miss one and the author's
        # edit is silently absent from the file they get: the guard used
        # to be `frame is None`, which is true only before the very
        # first layout, so a second render redrew the first render's
        # placement however much had changed in between.
        #
        # Two flags because the two stages do not go stale together. A
        # route is computed against the frames, so re-laying out
        # invalidates every route; re-routing moves no box and leaves
        # the frames alone. `layout()` therefore clears the first and
        # sets the second.
        #
        # `frame is None` / `route is None` is a different question --
        # *never run* rather than *run and overtaken* -- and the render
        # entry points still ask it separately. These start false for
        # that reason: a sheet with nothing on it has no stale geometry,
        # and the first `add()` is what makes it stale.
        self._layout_stale = False
        self._route_stale = False
        # What the last full numbering pass worked out, kept so that
        # `connect()` can name the one stream it just added instead of
        # re-deriving every name on the sheet. See `_number_appended`,
        # which is the only reader, and `renumber_streams`, which is the
        # only writer. `None` until a pass has run.
        self._groups: "list[list[Stream]] | None" = None
        self._group_names: list[str] = []
        self._group_of: dict[int, int] = {}  # id(Stream) -> its group
        self._tail: list[Stream] = []  # the lines numbered after the runs
        # The sheet's own metadata; a block set here is a title strip
        # drawn.
        self.title_block: "TitleBlock | None" = None
        # Generic titled boxes (equipment list, notes, legend, tables)
        # docked to the sheet corners. See pandid.document.
        self.annotations: list = []
        # Section headers to inject into the stream table: (before_key,
        # label). Content rather than a setting -- the heading text the
        # table draws -- which is why it is here beside `title_block`
        # and `annotations` and not on `stream_table` below.
        self.stream_table_sections: list[tuple[str, str]] = []
        # How that table is drawn: its type size today, and whatever is
        # asked of it next. An object rather than an attribute apiece,
        # so the second option is a field on it and not another name on
        # this class; see pandid.document.StreamTableOptions.
        self.stream_table = StreamTableOptions()

    def _invalidate_layout(self) -> None:
        """Say that the resolved geometry no longer answers for this
        sheet.

        The hook every mutation that can move a drawn box or a routed
        run calls -- here, or through
        :meth:`pandid.units.Unit._invalidate_layout` for a mutation made
        on a unit. It is the one place the staleness flags described in
        ``__init__`` are set, so a new mutator has an obvious thing to
        call and one comment to read.

        Cheap and idempotent, which settles the doubtful cases: a
        mutator that cannot say for certain whether it moves anything
        should call it anyway. Re-laying out costs time and comes out
        the same drawing, because the solver is reseeded from ``pin_``
        on every run; not re-laying out draws the previous sheet.
        """
        self._layout_stale = True
        self._route_stale = True

    @property
    def auto_faces(self) -> bool:
        """Let the layout engine pick which face a movable port is piped
        from, given where its peer landed.

        See :mod:`pandid.layout.faces`. Turn it off to pin every port to
        its symbol's own nozzle plus whatever
        :meth:`~pandid.units.Unit.nozzle` named.
        """
        return self._auto_faces

    @auto_faces.setter
    def auto_faces(self, value: bool) -> None:
        self._auto_faces = value
        self._invalidate_layout()

    def add_annotation(self, annotation):
        """Register a furniture box (Annotation/TableBox). Chainable."""
        self.annotations.append(annotation)
        return annotation

    def add(self, unit: _UnitT) -> _UnitT:
        """Register a unit. Returns the unit, for chaining.

        A tag names one item, so a tag already on the sheet is refused.
        The exceptions are the symbols that stand for one thing shown in
        several places: an interlock square, one piece of logic drawn at
        every place it acts, and a utility header flag (``Feed`` or
        ``Product`` with ``header=True``), one service drawn at every
        place it is tapped. A :class:`~pandid.units.Tee` repeats for the
        opposite reason: it draws no tag at all.

        Such a repeat is accepted and given a name of its own (``I-1``,
        ``I-1 (2)``), so the unit that a stream, a spec entry or an
        equipment list means is never in doubt, while the tag drawn
        stays ``I-1``.

        Every refusal is made before the first write, so a rejected
        ``add()`` leaves the sheet exactly as it found it. See
        :meth:`_refuse_unaddable`, which is where the refusals live so
        that a composite call can ask them of a unit it has not added
        yet.
        """
        clash = self._refuse_unaddable(unit)
        if clash is not None:
            # The tag is what repeats and so what the fresh name is
            # derived from. A tee draws none, so its name stands in.
            unit.name = self._repeat_name(unit.tag or unit.name)
        unit.flowsheet = self
        self.units.append(unit)
        self._invalidate_layout()
        return unit

    def _refuse_unaddable(self, unit: "Unit",
                          alongside: "Sequence[Unit]" = ()) -> "Unit | None":
        """Raise unless *unit* may join this sheet; answer what it repeats.

        :meth:`add`'s three refusals, lifted out whole so that a call
        building several units at once can ask them **before** it writes
        any of them: ``add_control_loop`` puts two balloons and two
        signal lines on the sheet, and a clash found on the second used
        to leave the first drawn (issue #433).

        ``alongside`` is the units the same call is about to add. They
        are not on :attr:`units` yet and a name they have already taken
        is as unavailable as one the sheet is holding, so the tag check
        runs over both.

        The answer is the unit *unit* repeats, or ``None``: the caller
        needs it to name the repeat, and finding it twice would be the
        same scan run again.
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
        """A free name for one more drawing of a repeated tag.

        The tag is what the sheet draws and what repeats; the name is
        what the flowsheet is addressed by, so it stays unique and stays
        derived from the tag: second, third and fourth square of ``I-1``
        become ``I-1 (2)``, ``I-1 (3)``, ``I-1 (4)``, in the order they
        are added.
        """
        taken = {u.name for u in self.units}
        n = 2
        while f"{tag} ({n})" in taken:
            n += 1
        return f"{tag} ({n})"

    def add_loop(self, variable: str, number: str | int | None = None) -> "Loop":
        """Declare a control loop and return its handle.

        ``variable`` is the ISA measured-variable letter (``"F"``,
        ``"L"``, ``"T"``) and ``number`` the loop number. A loop is
        identified by the **pair**: ``add_loop("F", 101)`` and
        ``add_loop("L", 101)`` are two loops on one sheet.

        Leave ``number`` out and the sheet allocates the next one,
        counting from ``loop_number_start``::

            fs = Flowsheet("A300", loop_number_start=301)
            press = fs.add_loop("P")   # P-301
            temp = fs.add_loop("T")    # T-302
            flow = fs.add_loop("F")    # F-303

        One series for the sheet, climbing through whichever measured
        variable was declared next, and allocated here at the
        declaration, so the order the numbers come out in is the order
        the file reads in. Allocated and typed numbers mix freely;
        :meth:`to_dict` writes both as literals, which is what freezes a
        draft.

        The loop replaces the number, not the letters. Each member still
        types its own functional letters and the loop checks the first
        of them, so a ``TT`` put on a flow loop raises at that line::

            loop = fs.add_loop("F", 303)
            fe = fs.add(units.Fitting(loop.element("FE"),
                                      variant="venturi"))
            ft = fs.add_instrument("FT", loop, sensing=fe, at="N",
                                   offset=70)
            cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

        A member that is not a balloon joins through one of two methods,
        chosen by which piece of equipment it is:
        :meth:`~pandid.loops.Loop.element` for a primary element, which
        is lettered from the measured variable and so is held to it, and
        :meth:`~pandid.loops.Loop.tag` for a final control element,
        which is not lettered that way and so cannot be.

        A loop draws nothing, is never in :attr:`units`, and reaches no
        equipment list; see :mod:`pandid.loops`. Instruments that are in
        no loop keep taking a literal number.

        Unlike a stream number, a loop number allocates once and is
        never rewritten afterwards, however it was arrived at: it leaves
        the drawing for the DCS.
        """
        loop, allocated = self._new_loop(variable, number)
        self._register_loop(loop, allocated=allocated)
        return loop

    def _new_loop(self, variable: str,
                  number: str | int | None = None) -> "tuple[Loop, bool]":
        """The loop :meth:`add_loop` would declare, checked but *not*
        declared. Answers it and whether its number was allocated.

        Split from the declaration so that
        :meth:`add_control_loop`, which cannot write anything until all
        five of its mutations are known to be safe, can find out what
        number it is about to spend without spending it (issue #433).
        Nothing here touches the sheet.
        """
        from pandid.loops import Loop

        # ONE series for the sheet, not one counter per measured
        # variable: ``professional_examples/P&ID_301.pdf`` runs P-301,
        # T-302, F-303, L-304 and on, a single series climbing through
        # whichever variable came next, and its notes block says the
        # instrument numbers are unique to that drawing.
        #
        # And a NAIVE counter: no reservation list, no skipping past
        # numbers already typed, no collision search. That holds only
        # while nothing outside `loops` spends a number for it to dodge,
        # which is CHEE4001 p.13: one number goes to the whole group of
        # components that between them do the monitoring or control the
        # scheme is for. The group consumes the
        # number, so p.11 letters a flow loop's element, transmitter,
        # controller and valve all 504, and a lone indicator is a group
        # of one.
        allocated = number is None
        if number is None:  # the same test twice, so the narrowing survives to Loop()
            number = self.loop_number_start + self._loops_allocated
        loop = Loop(variable, number)
        clash = next((existing for existing in self.loops
                      if (existing.variable, existing.number) == (loop.variable, loop.number)),
                     None)
        if clash is not None:
            # The one thing a naive counter can walk into: a number
            # typed by hand, on this variable, in the stretch the
            # counter is climbing through.
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
        """Declare a loop :meth:`_new_loop` has already checked.

        The only writer of :attr:`loops` and of the allocation counter,
        so "a rejected declaration burns nothing" is one fact in one
        place: every raise is behind us by the time this runs, and a bad
        letter or a clash leaves the next :meth:`add_loop` the number
        this one was reaching for.
        """
        if allocated:
            self._loops_allocated += 1
        self.loops.append(loop)

    def _resume_loop_numbering(self) -> None:
        """Move the counter past every loop number already declared.

        The hook a *reader* calls once :attr:`loops` is populated, and
        the reason a frozen sheet can be picked up and carried on.
        :func:`~pandid.spec.to_dict` writes every number out as a
        literal and records nothing about the counter, so a rebuilt
        sheet would otherwise start the series over and hand out numbers
        the drawing has already spent -- quietly, because ``F-301``
        beside ``P-301`` is two legal loops and only a repeated *pair*
        raises.

        Derived on read rather than serialised: the counter is engine
        state and the spec is a description of the drawing, and every
        number needed to derive it is in the file already. The cost is a
        series with a deliberate hole in it -- 301-304, 306, 307 --
        which resumes at 308 rather than filling 305. Allocating past a
        gap is the mild failure; allocating into one the author left for
        a loop not yet drawn is not.

        Only ever forwards, so it is safe to call twice and safe on a
        sheet whose loops sit below :attr:`loop_number_start`. A number
        that is not a number at all -- ``"301A"`` -- moves nothing,
        having no place in the series to be past.
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
        """Add an ISA-5.1 instrument balloon, anchored to the sheet.

        ``type`` is the functional letter string and ``number`` the loop
        number; together they make the tag (``add_instrument("FT",
        101)`` -> ``FT-101``). ``number`` also takes a
        :class:`~pandid.loops.Loop` from :meth:`add_loop` -- or the
        :class:`~pandid.loops.ControlLoop` from
        :meth:`add_control_loop`, which names the same loop -- which
        supplies the number and checks ``type`` against the loop's
        measured variable, raising here rather than warning at render
        time.

        **Three ways to name the anchor, and they say different
        things.** Each takes a :class:`~pandid.streams.Stream` or a
        :class:`~pandid.units.Unit` and places the balloon against it;
        what they differ on is whether the sheet then draws a line
        between the two.

        - ``sensing=`` -- the balloon takes its reading from here.
          Drawn: an impulse line where the host holds the fluid being
          measured and the balloon is a field device, a fine dashed
          instrument connection otherwise.
        - ``acting_on=`` -- the balloon commands this. A trip square
          under the valve it strokes. Drawn dashed: nothing is piped
          from a logic solver.
        - ``near=`` -- neither. The balloon is only *placed* here, and
          nothing is drawn between them. A control-room faceplate hung
          over the valve it drives is near it; what reaches the actuator
          is a signal, stated with :meth:`connect` and routed like one.

        ``at``/``offset``/``angle`` locate the balloon against whichever
        was named; see :meth:`~pandid.units.Instrument.attach`. With no
        anchor at all the balloon is laid out like any other unit.

        >>> s = fs.connect(feed.outlet, fv.inlet)
        >>> ft = fs.add_instrument("FT", 101, sensing=s, at=0.4,
        ...                        offset=60)
        >>> fic = fs.add_instrument("FIC", 101, near=ft, at="N",
        ...                         offset=70, display="central")
        >>> fs.connect(ft.sig_out, fic.sig_in, kind="electric")

        Whatever it is refused for -- the letters, the variant, two
        anchors, a placement, a host on another sheet, a tag already
        taken -- the balloon does not reach the sheet, so correcting the
        argument and calling again is all a retry has to be.
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
        """The balloon :meth:`add_instrument` would add, built and
        anchored but **not** on the sheet.

        Every refusal an ``add_instrument`` call can make except the tag
        clash, which is :meth:`add`'s, and the host ownership check,
        which is the caller's -- see below. The tag, the variant, the
        display, the one-anchor rule and the placement are all settled
        here, and all of them write to the new balloon and to nothing
        else, so a call refused for any of them leaves the sheet as it
        was. Until #433 the balloon joined ``units`` before ``attach``
        ran, so correcting a bad ``at=`` and retrying reported a
        duplicate tag.

        Host ownership is left to the caller because the one host this
        cannot judge is a balloon the same call is about to add:
        ``add_control_loop`` hangs its controller off a transmitter that
        is not on the sheet yet, and that is not a foreign object but a
        sibling.
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.units import Instrument

        # Both, because an author holding what add_control_loop() returned
        # is holding the loop by the only name they were given. Asking
        # them for ``handle.loop`` here would make the shorter spelling
        # the one that fails.
        if isinstance(number, (Loop, ControlLoop)):
            number.check(type)
            number = number.number
        inst = Instrument(type, number, variant=variant, **kwargs)
        host, relation = self._anchor(inst, sensing, acting_on, near)
        if host is not None:
            inst.attach(host, at=at, offset=offset, angle=angle, relation=relation)
        return inst

    def _refuse_foreign(self, role: str, thing: "Stream | Port | Unit") -> None:
        """Raise unless *thing* is on this sheet.

        A balloon anchored to a unit of another sheet, or a signal line
        landing on one, draws a sheet that cannot be read back: the
        member has no entry in this sheet's spec, so
        ``Flowsheet.from_dict(fs.to_dict())`` raises with nothing of
        that name to attach to (issue #433). :meth:`connect` has made
        this check since it existed; this is the same question asked
        wherever else an author hands in an object.

        Identity, not equality, for a stream: :class:`Stream` is a
        dataclass, so two lines with the same ends and the same
        components on two sheets compare equal, and ``in`` would call
        the foreign one ours.
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

    def _anchor(self, inst: "Instrument", sensing, acting_on, near):
        """The one anchor an ``add_instrument`` call named, and its use.

        Returns ``(host, relation)``, or ``(None, "sensing")`` for a
        balloon that named none.
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
        """Draw *element*'s tag in a balloon beside it, not against it.

        A primary element is **one instrument shown as two marks**: the
        thing in the pipe, and the balloon that carries its tag.
        CHEE4001 p.10 settles that it is one instrument -- it defines the
        primary element, letter ``E``, as the instrument that measures
        the process variable, an orifice plate or a thermocouple say --
        and ``professional_examples/P&ID_301.pdf`` settles the drawing: its
        venturi carries **no lettering at all**, an ``FE 303`` balloon
        hangs under it on a short impulse line, and ``FT 303`` sits
        immediately below that::

            fe303 = fs.add(units.Fitting(flow303.element("FE"),
                                         variant="venturi"))
            fs.add_balloon(fe303, at="S", offset=46)
            ft303 = fs.add_instrument("FT", flow303, near=fe303.balloon,
                                      at="S", offset=45)

        The tag is typed once, on the element, and moves to the balloon:
        the element stops drawing lettering of its own, so the sheet
        shows ``FE-303`` exactly once. Both objects answer to it, which
        is why the pair joins the sheet's "one thing, several marks"
        exemption (issue #249). The element keeps the plain name, since
        it is the item an equipment list schedules; the balloon is named
        ``FE-303 (2)``, as a repeated trip square is.

        ``at``/``offset``/``angle`` place the balloon exactly as
        :meth:`add_instrument` does, and the relation is ``sensing``, so
        a solid impulse line is drawn between them. The default
        ``offset`` is the reference sheet's, whose FE balloon centre
        stands 1,05 balloon diameters off the process line.

        Raises:
            ValueError: if *element* already has a balloon, or is not on
                this flowsheet, or carries no tag to move.
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
        # Set before add(), which is where the shared tag is either
        # allowed or refused; see Instrument.repeats.
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
        """Draw a single-variable feedback loop, in the one sentence it is.

        A transmitter on what is being measured, a controller beside it,
        and the two signal lines that close the loop onto a final
        control element the author has already put in the pipe::

            loop = fs.add_control_loop("F", 101, measuring=feed,
                                       acting_on=fv)
            loop.transmitter     # FT-101
            loop.controller      # FIC-101
            loop.final_element   # the ControlValve passed in

        which is the loop, the two balloons and the two signal lines of
        the long-hand -- :meth:`add_loop`, two :meth:`add_instrument`
        calls and two :meth:`connect` calls -- said once. It composes
        exactly those calls and nothing else, so anything true of a
        hand-built loop is true of this one.

        **It takes the final element; it does not make one.** A control
        valve is process equipment standing in a line, between two
        pieces of piping the author drew. Minting one here would be
        guessing where that piping goes, so ``acting_on`` is required
        and takes the unit -- or one of its nozzles, where the unit has
        more than one signal terminal to choose between.

        **The letters follow from the measured variable.** ``"F"`` gives
        ``FT-101`` and ``FIC-101``, ``"L"`` gives ``LT-101`` and
        ``LIC-101``, so the variable is typed once for the ordinary
        loop. A house style that letters them otherwise states the
        member's **whole** functional code -- a recording controller is
        ``controller_letters="FRC"`` on a flow loop, spelled as it is
        said and as :meth:`add_instrument` takes it -- and a code that
        does not open with the loop's measured variable is refused
        rather than composed (issue #448).

        **It states no distance of its own.** ``at``/``offset``/``angle``
        place the transmitter against what it measures, and
        ``controller_at``/``controller_offset`` place the controller
        against the transmitter, both exactly as :meth:`add_instrument`
        means them. Leave any of them out and ``add_instrument``'s own
        default applies, with the standoff resolver of
        :mod:`pandid.layout.attach` walking a balloon clear of whatever
        it would have landed on. Repeating those defaults here would put
        a second copy of every standoff in the package, and a number an
        author has to guess is what issue #439 was raised about.

        ``variable`` takes the :class:`~pandid.loops.Loop`
        :meth:`add_loop` returned as well as the measured-variable
        letter, and usually has to: the valve is tagged from the loop
        and is placed in the run long before the balloons go on, so on
        most sheets the loop is already declared by the time this is
        called. Given a letter instead -- with a number, or without one
        for the sheet to allocate -- this declares the loop itself,
        which is the spelling for a valve whose tag was typed literally.

        ``measurement_kind`` and ``output_kind`` are the two signal
        lines' :meth:`connect` kinds: a 4-20 mA measurement into the
        controller and an air signal down onto the diaphragm, which is
        what the defaults say. An electrically actuated valve is
        ``output_kind="electric"``.

        Cascade, ratio, split-range and override loops are **not** built
        here; each is more than one measured variable or more than one
        final element. Every part stays reachable, so building one of
        those on top of this is the long-hand it always was.

        Args:
            variable: The ISA measured-variable letter, or a declared
                :class:`~pandid.loops.Loop`.
            number: The loop number, when ``variable`` is a letter.
                Left out, the sheet allocates one; see :meth:`add_loop`.
            measuring: What the transmitter reads -- a stream for a
                flow, a unit for a level, a pressure or a temperature.
                Anchored as ``sensing=`` anchors a balloon on
                :meth:`add_instrument`, so the tap is drawn.
            acting_on: The final control element, or its signal nozzle.
            transmitter_letters: The transmitter's whole functional code
                (``"FT"``, ``"FIT"``). Left out, the loop letters it.
            controller_letters: The controller's whole functional code
                (``"FIC"``, ``"FRC"``). Left out, the loop letters it.

        Returns:
            The :class:`~pandid.loops.ControlLoop` handle. It draws
            nothing itself; its members are ordinary units and streams.

        Raises:
            ValueError: if a declared loop is given a number as well or
                was declared on another sheet; if either functional code
                is empty, is the measured variable alone, or opens with
                a different variable; if ``measuring`` or ``acting_on``
                is not on this sheet; or for anything the four calls it
                composes would refuse. **Every one of those is checked
                before the first write**, so a rejected call leaves no
                loop declared, no balloon drawn, no signal line and the
                allocation counter where it was -- correct the argument
                and call again with the same number (issue #433).
        """
        from pandid.loops import ControlLoop, Loop
        from pandid.ports import Port

        # ------------------------------------------------------------------
        # Preflight. NOTHING below writes to the sheet until the commit
        # block at the foot of the method, and that is the whole point:
        # this call makes five mutations -- the loop, two balloons, two
        # signal lines -- and until #433 each ran as it was reached, so a
        # tag clash on the controller left the loop declared and the
        # transmitter drawn. A typo did not merely fail; it consumed a
        # loop number and left half a control loop on the drawing.
        #
        # Preflight rather than rollback. Rollback would have to unwind
        # a minted pool nozzle and a stream-numbering pass that renames
        # lines all over the sheet, and it would only run on the paths
        # someone remembered to wrap. The checks below are the same ones
        # the four calls make, asked of the same objects, from the
        # methods that own them -- so a rule added to `add()` or
        # `connect()` is preflighted here whether or not anyone
        # remembers this method exists.
        if isinstance(variable, Loop):
            if number is not None:
                raise ValueError(
                    f"loop {variable.name} is already declared and carries its "
                    f"number, so number={number!r} here is a second answer to a "
                    f"settled question. Pass the loop on its own, or pass "
                    f"{variable.variable!r} and {number!r} and let this declare it"
                )
            # Identity, not equality: a Loop built by another sheet's
            # `add_loop` has the same variable and number as ours would,
            # and taking it would number two balloons from a loop this
            # sheet never declares -- `fs.loops` would stay empty and
            # `to_dict()` would write no entry for it.
            if not any(declared is variable for declared in self.loops):
                raise ValueError(
                    f"loop {variable.name} was not declared on flowsheet "
                    f"{self.name!r}. A loop is a namespace belonging to one sheet, so "
                    f"pass the handle this sheet's add_loop() returned -- or pass "
                    f"{variable.variable!r} and {variable.number!r} and let this "
                    f"declare it here"
                )
            # ``None``, not ``False``: the loop is on `fs.loops` already
            # and this call declares nothing, where ``False`` would say
            # it declares one whose number was typed rather than counted.
            loop, allocates = variable, None
        else:
            loop, allocates = self._new_loop(variable, number)
        transmitter_code = _functional_code(
            loop, transmitter_letters, f"{loop.variable}T", "transmitter_letters")
        controller_code = _functional_code(
            loop, controller_letters, f"{loop.variable}IC", "controller_letters")
        self._refuse_foreign("measuring", measuring)
        self._refuse_foreign("acting_on", acting_on)
        # Built and anchored but not added, which is what settles the
        # tags, the variants and both placements without spending them.
        # The transmitter first, because ``place_attached`` resolves
        # balloons in the order they joined ``units`` and the controller
        # hangs off the transmitter.
        transmitter = self._build_instrument(
            transmitter_code, loop, sensing=measuring,
            **_stated(at=at, offset=offset, angle=angle))
        # ``near=``, not ``sensing=``: the controller does not read the
        # transmitter, it is only stacked on it, and what passes between
        # them is the measurement below -- a signal line, routed like
        # one. Saying both would draw two lines between one pair.
        controller = self._build_instrument(
            controller_code, loop, near=transmitter,
            variant=controller_variant,
            **_stated(at=controller_at, offset=controller_offset))
        self._refuse_unaddable(transmitter)
        # Against the transmitter as well: it is not on `units` yet, and
        # a controller lettered onto the same tag is still a clash.
        self._refuse_unaddable(controller, alongside=(transmitter,))
        pending = (transmitter, controller)
        self._resolve_connection(transmitter.sig_out, controller.sig_in,
                                 kind=measurement_kind, pending=pending)
        self._resolve_connection(controller.sig_out, acting_on,
                                 kind=output_kind, pending=pending)

        # ------------------------------------------------------------------
        # Commit. Every one of these was asked above and answered yes.
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
        x: float | None = None, y: float | None = None, mirrored: bool = False,
        variant: str = "control", number: str | int | None = None,
        isolation: bool = True, reducers: bool = True, bypass: bool = True,
        drains: int = 2, description: str = "", bypass_over: str | None = None,
        tag_scheme: "str | Callable[[str, str], str] | None" = None,
        gap: float = DEFAULT_GAP, bypass_rise: float = DEFAULT_BYPASS_RISE,
        drain_drop: float = DEFAULT_DRAIN_DROP,
        size: str | float | None = None, schedule: str | float | None = None,
        service: str | float | None = None,
        sequence: str | float | None = None, spec: str | float | None = None,
        insulation: str | float | None = None,
    ) -> "ValveStation":
        """Build the standard assembly a control valve is installed in.

        Two isolation valves, two drain valves, one bypass valve on a
        leg tapped outside the isolations, and a size change at each
        end: the arrangement the CHEE4001/7103 guidelines draw and
        :mod:`pandid.stations` quotes. The units are added, tagged,
        described, pinned along a run at ``y`` and wired to each other;
        what is left for the author is the piping either side of it,
        which is what :attr:`~pandid.stations.ValveStation.inlet` and
        :attr:`~pandid.stations.ValveStation.outlet` are for::

            station = fs.add_valve_station(
                "CV-303", x=670, y=440, mirrored=True,
                description="Reflux", service="AE", sequence=303,
                size=80, schedule=80, spec="SS")
            fs.connect(t_draw.branch, station.inlet, service="AE",
                       sequence=303, size=80, schedule=80, spec="SS")
            fs.connect(station.outlet, fe303.inlet)

        The returned :class:`~pandid.stations.ValveStation` is a handle,
        not a unit: it draws nothing, reaches no equipment list, and its
        members are ordinary units that can be re-pinned, re-tagged or
        instrumented.

        Args:
            tag: The control valve's tag, and what the other members'
                tags are derived from.
            x: Left edge of the drawn station; ``y`` is the run's
                **centreline**, so each device lands on the line
                whatever its artwork measures. Give both or neither;
                without them the members lay out like any other units.
            mirrored: Pipe the run east to west. The station still
                occupies ``x`` rightwards; what reverses is which end
                the flow enters.
            variant: The control valve's variant.
            number: The number the members are tagged from, defaulting
                to the one in ``tag``. The escape hatch for a control
                valve whose own number is not what its station is
                numbered by: ``CV-301-1`` with ``number=301`` gives
                ``HV-301A``, not ``HV-301-1A``.
            isolation: Draw the two isolation valves.
            reducers: Draw the reduction in and the expansion out.
            bypass: Draw the bypass leg and its normally closed
                throttling valve.
            drains: How many drain valves, 0, 1 or 2. One goes upstream.
            description: The service in words. Each member's description
                is this plus what it does: ``"Reflux Isolation Valve"``.
            bypass_over: The member the bypass valve stands over, one of
                :data:`~pandid.stations.BYPASS_ANCHORS`; by default it
                sits in the middle of its own leg, where the reference
                figure draws it. Move it when something else already
                crosses there, most often a controller's output dropping
                onto the actuator.
            tag_scheme: Overrides :attr:`valve_station_tag_scheme` for
                this station only.
            gap: Edge to edge between devices along the run.
            bypass_rise: How far the bypass leg stands off the run.
            drain_drop: How far a drain leg hangs below it.
            size, schedule, service, sequence, spec, insulation: The
                line number's components, put on the bypass and drain
                branches. A branch off a tee starts a number of its own,
                and a bypass is the same service, size and spec as the
                run it goes round. The run through the station carries
                the number of whatever is connected to :attr:`inlet`.

        Raises:
            ValueError: for a station that cannot mean what it says: a
                bypass with nothing to bypass around, a drain count that
                is not 0, 1 or 2, one of ``x``/``y`` without the other,
                or a ``bypass_over`` naming a member this station was
                told to leave out.
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
        if bypass_over is not None and bypass_over not in BYPASS_ANCHORS:
            raise ValueError(
                f"{tag}: bypass_over names the member the bypass valve stands over, "
                f"one of {', '.join(BYPASS_ANCHORS)}, got {bypass_over!r}"
            )
        # Which roles this station will carry is decided by isolation= and
        # reducers= alone -- control is always built -- so this is checked
        # from the two flags, before any member joins the sheet, rather than
        # from the constructed units afterwards. A call refused here must
        # leave nothing behind to be drawn.
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
            return f"{description} {ROLE_WORDS[role]}".strip()

        def valve(role: str, closed: bool = False) -> "Valve":
            unit = Valve(member_tag(scheme, role, tag, num),
                         description=described(role),
                         normal_position="closed" if closed else "open")
            self.add(unit)
            return unit

        def size_change(role: str) -> "Reducer":
            unit = Reducer(member_tag(scheme, role, tag, num),
                           description=described(role),
                           large_end="inlet" if role == "reduction" else "outlet")
            self.add(unit)
            return unit

        def tee(returns: bool = False) -> "Tee":
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

        # The order the fluid meets them, which is the order the figure
        # draws them and the order the streams below are made in. A
        # mirrored station is this run drawn the other way round.
        run = [u for u in (t_bya, iso_a, t_dra, red, control, exp, t_drb, iso_b, t_byb)
               if u is not None]
        anchors = {"upstream_isolation": iso_a, "downstream_isolation": iso_b,
                   "reduction": red, "expansion": exp, "control": control}

        if x is not None and y is not None:
            left: dict[int, float] = {}   # the corner each member was pinned at
            cursor = x
            for unit in (reversed(run) if mirrored else run):
                unit.pin(x=cursor, mirrored=member_mirror(mirrored, unit in (t_bya, t_byb)))
                unit.pin(port="inlet", y=y)
                left[id(unit)] = cursor
                cursor += resolve_size(unit)[0] + gap
            for junction, drain in ((t_dra, dr_a), (t_drb, dr_b)):
                if junction is None or drain is None:
                    continue
                # A drain runs down to a funnel on the floor, which is
                # not on this sheet, so the leg ends at the valve.
                drain.pin(orientation=90)
                drain.pin(port="inlet",
                          x=left[id(junction)] + port_offset(junction, "branch")[0],
                          y=y + drain_drop)
            if byp is not None and t_bya is not None and t_byb is not None:
                target = anchors[bypass_over] if bypass_over is not None else None
                if target is not None:
                    centre = left[id(target)] + resolve_size(target)[0] / 2
                else:
                    # Nothing named, so the middle of its own leg, which
                    # is where the reference figure draws it.
                    centre = sum(left[id(t)] + port_offset(t, "branch")[0]
                                 for t in (t_bya, t_byb)) / 2
                byp.pin(mirrored="x" if mirrored else False)
                byp.pin(x=centre - resolve_size(byp)[0] / 2)
                byp.pin(port="inlet", y=y - bypass_rise)

        def branch_line(src: "Port", dst: "Port") -> Stream:
            """A leg off the run, on the station's own line number."""
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
        return ValveStation(
            control=control, upstream_isolation=iso_a, downstream_isolation=iso_b,
            reduction=red, expansion=exp, bypass=byp,
            upstream_drain=dr_a, downstream_drain=dr_b,
            tees=tuple(t for t in (t_bya, t_dra, t_drb, t_byb) if t is not None),
            members=tuple(members), inlet=run[0].inlet, outlet=run[-1].outlet,
        )

    def add_component(self, component: "Component") -> "Component":
        """Register a chemical component. Returns it, for chaining."""
        self.components.append(component)
        return component

    def connect(self, src: "Port | Unit", dst: "Port | Unit", *, kind: str = "material",
                name: str | None = None, draw_as_recycle: bool = False,
                size: str | float | None = None, schedule: str | float | None = None,
                service: str | float | None = None,
                sequence: str | float | None = None, spec: str | float | None = None,
                insulation: str | float | None = None,
                ends: "str | tuple[str, str] | None" = None) -> Stream:
        """Create a stream from *src* (an outlet) to *dst* (an inlet).

        The returned stream already carries the number it will be drawn
        with; see :meth:`renumber_streams`.

        ``kind`` has to match what the two ports are: a signal kind runs
        between two signal connections (a valve's ``actuator``, an
        instrument's ``pv`` and ``sig_in``/``sig_out``) and a process
        kind between two process nozzles.

        For a signal line either end may be the **unit** instead of one
        of its connections, and this picks the connection: an instrument
        mints a free one and anything else with a single signal
        connection offers that one (``fs.connect(ft305, fic305,
        kind="electric")``). Process piping always names its nozzles,
        since which nozzle is the whole question.

        ``size``/``schedule``/``service``/``spec``/``insulation`` are
        the line-number components; supplying any of them draws this
        line with its line number instead of a stream number.
        ``sequence`` is filled by auto-numbering unless it is given
        here. ``size`` is the line's nominal bore, ``schedule`` the wall
        it is bought to at that bore, and ``spec`` the piping class or
        material it is built to.

        ``ends`` says how this line's joints are made up and overrides
        the sheet's ``connections`` for this run alone: ``"flanged"``
        marks both, ``"none"`` marks neither, and a ``(source, dest)``
        pair -- in the order the two were just named -- states them
        apart. Left unset the line follows the sheet. It takes any
        member of :data:`~pandid.render.svg.CONNECTIONS`, so a single
        run can be marked at its nozzles alone on a sheet that flanges
        its valves, and the other way round. Never marked either way: a
        boundary flag, an instrument or a signal line, there being no
        joint to describe. Nothing is marked at all except on a
        ``diagram="p&id"`` sheet; see :meth:`render`.

        Raises :class:`ValueError` if any validation rule is violated.
        Every rule is checked before the first write, so a rejected
        ``connect()`` leaves both nozzles free and the sheet's streams
        untouched; see :meth:`_resolve_connection`.
        """
        src, dst, kind = self._resolve_connection(src, dst, kind=kind, ends=ends)
        # Everything from here writes. `another_port` MINTS on a pool,
        # which is why the refusals above run first and why they run on
        # the ports as named rather than on the members they are about
        # to be swapped for.
        if src.stream is not None:
            src = src.owner.another_port(src)
        if dst.stream is not None:
            dst = dst.owner.another_port(dst)

        stream = Stream(
            name=name or "",  # auto-named: renumber_streams() numbers it
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
        # The number a caller reads off the returned stream has to be
        # the number that gets drawn, so numbering is settled here
        # rather than at render time. One stream's worth of it where
        # that is all the append moved, since a full pass per connect()
        # is what made building a sheet quadratic in its own size.
        if not self._number_appended(stream):
            self.renumber_streams()
        return stream

    def _resolve_connection(
        self, src: "Port | Unit", dst: "Port | Unit", *, kind: str,
        ends: "str | tuple[str, str] | None" = None,
        pending: "Sequence[Unit]" = (),
    ) -> "tuple[Port, Port, str]":
        """The two nozzles a :meth:`connect` call means, and its kind,
        with every refusal made and nothing written.

        Answers the ports **as named**, not the pool members they may be
        swapped for: taking a fresh member mints one, and a preflight
        that minted would leave a balloon carrying a spare nozzle no
        line reaches, which is the very thing this exists to prevent.

        ``pending`` is the units the calling operation is about to add.
        A composite has to know its lines are drawable before it writes
        the balloons they run between, and those balloons are on no
        flowsheet yet -- not foreign, just not committed. It is the one
        concession preflighting a composite needs, and it is
        deliberately narrow: only the ownership check reads it.
        """
        if ends is not None:
            from pandid.render.svg import check_connections
            check_connections(ends)
        if kind not in STREAM_KINDS:
            raise ValueError(
                f"Stream kind must be one of {sorted(STREAM_KINDS)}, got {kind!r}"
            )
        src = _signal_end(src, kind, "source")
        dst = _signal_end(dst, kind, "destination")

        # A signal port carries no direction (see the two checks below),
        # so nothing else here catches a line asked to run from a nozzle
        # back to that same nozzle. Undetected, it draws as a zero-length
        # spike that ``stream_polyline()``'s collinear-run collapse then
        # erases outright -- a stream that connects, routes and renders
        # clean while meaning nothing, the same nozzle at both ends of a
        # line that answers no question about which way anything flows.
        if src is dst:
            raise ValueError(
                f"{src.owner.name}.{src.name} is both the source and the "
                f"destination; a stream needs two different nozzles to mean "
                f"anything"
            )
        # Process nozzles only. Fluid enters a nozzle or it leaves one,
        # and a sheet that says otherwise is wrong about the plant. A
        # signal connection has no such fact to be right or wrong about
        # -- the same alarm terminal is fed on one sheet and trips from
        # it on another -- so its direction is read off
        # ``Stream.source``/``Stream.dest``, which is exact because a
        # port holds at most one stream. See
        # :class:`pandid.units.Instrument`.
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
        # A connection already spoken for is a mistake on every nozzle
        # but one: an instrument balloon's signal connections are a
        # *pool*, so a second line off ``sig_out`` is the split-range
        # case and gets a member of its own. The unit answers, because
        # which of its connections are plural is a fact about the
        # equipment.
        #
        # Both refusals are made before either port is taken, so a call
        # that raises leaves the sheet as it found it: a balloon left
        # carrying a spare nozzle no line reaches is a drawing changed
        # by an error.
        for port in (src, dst):
            if port.stream is not None and not port.owner.has_another_port(port):
                raise ValueError(
                    f"port {port.owner.name}.{port.name} is already connected"
                )
        # Read off the ports as named, which is exact: a pool member has
        # its siblings' role, so the swap below cannot change the answer.
        if kind == "material" and src.role in _ENERGY_ROLES and dst.role in _ENERGY_ROLES:
            kind = "energy"
        return src, dst, kind

    @classmethod
    def from_dict(cls, spec: dict) -> "Flowsheet":
        """Build a flowsheet from a declarative spec ``dict``.

        See :mod:`pandid.spec` for the format. Raises
        :class:`pandid.spec.SpecError` (a :class:`ValueError`) naming
        the offending entry.
        """
        from pandid.spec import from_dict as _from_dict
        return _from_dict(spec)

    @classmethod
    def from_json(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from JSON. See :mod:`pandid.spec`."""
        from pandid.spec import from_json as _from_json
        return _from_json(path)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from YAML (needs the ``yaml`` extra).

        See :mod:`pandid.spec`.
        """
        from pandid.spec import from_yaml as _from_yaml
        return _from_yaml(path)

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe declarative spec ``dict``.

        Round-trips: ``Flowsheet.from_dict(fs.to_dict())`` rebuilds an
        equivalent flowsheet. See :mod:`pandid.spec` for the format.
        """
        from pandid.spec import to_dict as _to_dict
        return _to_dict(self)

    def layout(self, engine=None) -> None:
        """Run the layout engine to generate unit coordinates.

        Always runs: an explicit call is a request, not a cache lookup.
        The frames it resolves are fresh geometry, so every route
        computed against the old ones is now stale and the next
        :meth:`route` -- or the next render, which calls it -- runs
        again. Without that a ``pin()`` and a hand-called ``layout()``
        moved the equipment and left the pipe where it was, drawn from
        the new nozzle to the old run and so no longer orthogonal.
        """
        if engine is None:
            from pandid.layout import default_layout_engine
            engine = default_layout_engine
        engine.layout(self)
        self._layout_stale = False
        self._route_stale = True

    def route(self, router=None) -> None:
        """Run the router to generate orthogonal stream paths.

        Runs :meth:`layout` first if the frames are stale or if any unit
        still lacks one, since routing needs geometry to work against.

        Attached instruments are placed and the sheet re-routed until
        the two agree, up to
        :data:`~pandid.layout.attach.MAX_PLACEMENT_PASSES`. A sheet that
        never settles leaves ``route_converged`` false, which
        :meth:`validate` reports as a warning.
        """
        if self._layout_stale or any(u.frame is None for u in self.units):
            self.layout()
        if router is None:
            from pandid.routing import DefaultRouter
            router = DefaultRouter()
        from pandid.layout.attach import MAX_PLACEMENT_PASSES
        from pandid.layout.control import place_control
        router.route(self)
        # An attached balloon hangs off its host's *routed* path, so
        # where it lands is only known once that path exists; and
        # re-placing it can move the next one, because the box it now
        # occupies is an obstacle in a place the last pass had clear.
        # Hence a fixed point rather than a fixed two passes. The loop
        # always ends on a route, converged or not, so no signal line is
        # left pointing at where a balloon used to be.
        self.route_converged = False
        for _ in range(MAX_PLACEMENT_PASSES):
            if not place_control(self):
                self.route_converged = True
                break
            router.route(self)
        # Last, so a router that raises leaves the sheet saying its
        # routes are stale -- which they are: half of them are this
        # run's and half the previous one's.
        self._route_stale = False

    def _resolve_geometry(self) -> None:
        """Bring the frames and routes up to date with the model.

        Step 3 of :meth:`_prepare_to_draw`, and the one place the
        staleness rule is stated. Each stage runs when it has never run
        at all, or when a mutation since has overtaken it; a sheet
        rendered twice with nothing changed in between pays for neither,
        which is the whole reason the geometry is kept rather than
        recomputed.

        :meth:`layout` sets ``_route_stale``, so a re-layout here always
        drags the routes with it and the two cannot be left describing
        different sheets.
        """
        if self._layout_stale or any(u.frame is None for u in self.units):
            self.layout()
        if self._route_stale or any(s.route is None for s in self.streams):
            self.route()

    @staticmethod
    def _raise_on_errors(issues: list) -> None:
        """Raise on the errors in *issues*, naming every one of them.

        One exception for the lot, rather than one per finding: an
        author who fixes the first of four and renders again should not
        have to meet the other three one at a time.
        """
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise ValueError(
                "Flowsheet validation failed:\n"
                + "\n".join(f"  {e}" for e in errors)
            )

    def _prepare_to_draw(self, *, diagram: str | None, check: bool) -> None:
        """Bring the sheet to the state a renderer can draw it from.

        The order is the contract :meth:`to_svg`, :meth:`to_drawio` and
        :meth:`render` all state, and this is the one place it is
        carried out:

        1. number the streams, so any finding quotes the name that will
           actually be drawn;
        2. **check the model** -- :func:`pandid.validate.model_issues`,
           the findings that need no geometry: a pin that is not a
           number, a symbol gravity fixes given a quarter turn, a tag
           out of sequence, a counted nozzle with nothing piped to it, a
           counted name already taken;
        3. resolve the geometry, laying out and routing;
        4. **check the geometry** --
           :func:`pandid.validate.geometry_issues`: overlaps, coincident
           nozzles, crossings, detours, elevations.

        Step 2 precedes step 3 because a model the validator rejects is
        a model the engine cannot lay out or route either, and the
        engine has no way to say so. ``pin(x=nan)`` is the case that
        named this method: ``pin-not-finite`` describes it exactly, and
        every render reached the router first, which was handed that
        coordinate and did not come back. The finding was made for a
        drawing nobody could obtain.

        Errors raise from whichever half found them, so a model error
        raises before any geometry exists. Warnings from both halves
        land on ``warnings`` together, model findings first, so that
        list is one sheet's findings rather than one phase's.

        ``check=False`` skips both halves and resolves the geometry
        alone, which is what it has always meant. It does **not** leave
        the previous render's findings standing: ``warnings`` is emptied
        here either way, so an empty list after a ``check=False`` render
        means nothing was found rather than nothing was looked for.
        """
        from pandid.render.svg import draws_arrowheads
        from pandid.validate import geometry_issues, model_issues

        # ``warnings`` describes *this* render. Emptied at the top rather
        # than assigned at the bottom, because only the `check` branch
        # assigns it and the renderers append to it afterwards, so a
        # `check=False` render used to answer with the last checked
        # render's findings and a caller could not tell that list from an
        # honestly empty one.
        self.warnings = []
        # Before the model check, not after: `stream-name-reused` reads
        # the names, and `new_line_number` set after the last connect()
        # regroups the runs and so changes them.
        self.renumber_streams()
        found: list = []
        if check:
            found = model_issues(self, arrows=draws_arrowheads(diagram))
            self._raise_on_errors(found)
        self._resolve_geometry()
        if check:
            found += geometry_issues(self, arrows=draws_arrowheads(diagram))
            self.warnings = [i for i in found if i.severity == "warning"]
            self._raise_on_errors(found)

    def _stream_groups(self) -> "list[list[Stream]]":
        """The material streams, gathered into the runs that share a name.

        One list per group, each in the order its segments were
        connected, and the groups themselves in the order their first
        segment was. A group is a run through inline devices -- the
        thing :meth:`renumber_streams` hands a single number to -- so a
        sheet with no valve in it answers one single-element list per
        stream.

        Split out because two callers have to agree on what "one
        stream" means and there must not be two answers.
        :meth:`renumber_streams` numbers a group; :func:`pandid.validate
        <pandid.validate.validate>` asks whether two streams that answer
        to one name are one run drawn in segments or two runs that
        collided, and the grouping is the only thing that can tell them
        apart.

        Note what a group is **not**: it is not every segment an author
        gave one name to. ``examples/10_ethanol_pfd.py`` draws ``S-305``
        over five ``connect`` calls round a reflux circuit whose
        intervening equipment is a condenser and a drum, neither of them
        inline, so those five sit in four groups. Sharing a name across
        groups is ordinary and is not on its own a finding.
        """
        material = [s for s in self.streams if s.kind == "material"]
        pos = {id(s): i for i, s in enumerate(material)}  # Stream: unhashable
        parent = list(range(len(material)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # The run through an inline device is its ``inlet`` to its
        # ``outlet``, named rather than counted: a tee has a third
        # process connection and counting cannot say which two of the
        # three are the run.
        for u in self.units:
            if u.kind in INLINE_KINDS and not getattr(u, "new_line_number", False):
                run = [u.ports.get("inlet"), u.ports.get("outlet")]
                ends = [pos[id(p.stream)] for p in run
                        if p is not None and p.stream is not None and id(p.stream) in pos]
                if len(ends) == 2:
                    parent[find(ends[0])] = find(ends[1])

        groups: dict = {}  # insertion-ordered, so first-appearance order
        for i, s in enumerate(material):
            groups.setdefault(find(i), []).append(s)
        return list(groups.values())

    def _named_runs(self) -> "dict[str, list[Stream]]":
        """The lines that get a stream-table column, by the name on them.

        One entry per name, in the order the name was first drawn, each
        holding every segment that answers to it. Signal lines are left
        out: a signal is not a stream of anything and has no properties
        to tabulate.

        The sibling of :meth:`_stream_groups` and not the same grouping.
        A *group* is a run through inline devices, which is what a single
        number is handed to; a *named run* is every segment carrying one
        name however it got there, which is what a single column is
        handed to. ``examples/10_ethanol_pfd.py``'s ``S-305`` is one
        named run and four groups. Split out for the reason that one is:
        :func:`pandid.render.furniture._table_streams` decides which runs
        get a column and :func:`pandid.validate.model_issues` reports the
        boundary run that is empty, and the two must not disagree about
        what one column is.
        """
        from pandid.streams import SIGNAL_KINDS

        runs: dict[str, list[Stream]] = {}
        for s in self.streams:
            if s.kind not in SIGNAL_KINDS:
                runs.setdefault(s.name, []).append(s)
        return runs

    def renumber_streams(self) -> None:
        """Assign stream numbers, carrying one through inline fittings.

        Runs on every :meth:`connect` and again before rendering, so the
        name on the stream object a caller holds is the name that gets
        drawn.

        Valves, reducers, fittings and tees are inline: a stream keeps
        its number as it passes through them (set ``unit.new_line_number
        = True`` to break the number at an important valve).
        Explicitly-named streams keep their name and lend it to their
        whole inline group, but still take a place in the sequence --
        see :meth:`_stream_groups`, which decides what one group is.
        What carries the number through is the ``inlet`` to ``outlet``
        run, so a tee's *branch* takes a number of its own: the bypass
        leg or drain off a station is its own line, and the run it
        leaves carries straight on.

        A line carrying line-number components is named by its line
        number rather than its stream number, on the same terms: the
        first segment of a group that carries components supplies them
        for the whole group, so a line number survives an inline valve
        and breaks at one that sets ``new_line_number``, which is
        exactly where the spec breaks.

        Process streams take the low numbers, being the ones drawn on
        the sheet and quoted in the stream table; energy streams, also
        drawn, follow, and unlabelled signal lines come last. One
        sequence covers all three, so a name this counts out is never
        counted out twice.

        It can still *land* on one an author already used, since a name
        is free text; :func:`pandid.validate.validate` reports that as
        ``stream-name-reused``, which is the only place the two readings
        of a shared name can be told apart.
        """
        groups = self._stream_groups()
        names = []
        for place, group in enumerate(groups, 1):
            # Every group takes the next place in the sequence, named
            # groups included, and an explicit name says what that place
            # is *called* rather than taking the group out of the count.
            # A named group that consumed nothing let the counter walk
            # over the names it holds: on a `stream_number_start=100`
            # sheet, `connect(..., name="S100")` followed by three plain
            # connects drew S100 twice and dropped a stream-table
            # column, because the counter was still on its first number
            # when the second group asked for one.
            #
            # Counting them lines the series up with the sheet as well:
            # the fourth run drawn takes the fourth number, whether or
            # not the three before it were named by hand.
            #
            # It does not make a collision impossible -- a name is free
            # text, and `name="S102"` on that same sheet still meets the
            # third number the counter reaches -- so `validate()`
            # reports one as `stream-name-reused`. This removes the case
            # the engine creates by itself.
            names.append(self._name_group(group, place))
        self._tail = [s for s in self.streams if s.kind != "material"]
        self._number_tail(len(groups))
        # What the next `connect()` names one new stream against, in
        # place of running all of this again. See `_number_appended`.
        self._groups, self._group_names = groups, names
        self._group_of = {id(s): i for i, g in enumerate(groups) for s in g}

    def _number_appended(self, stream: "Stream") -> bool:
        """Name the stream :meth:`connect` just added, on its own.

        Answers whether it managed it. ``False`` means the append moves
        names that were already handed out, and the caller owes the
        sheet a full :meth:`renumber_streams`.

        **Why this exists.** Numbering runs on every ``connect()``, so
        that the name on the object a caller is handed back is the name
        that gets drawn. A full pass is linear in the sheet -- every
        unit, to find the inline runs, and every stream -- so running
        one per ``connect()`` made building a sheet quadratic in its own
        size: 200 streams cost 0.05s and 1600 cost 3.3s, and 4.6s of a
        4.7s build was inside numbering. Appending one stream leaves
        almost every name exactly as it was, and this works out which.

        Three shapes, and only the first two are cheap:

        - **A run of its own.** Nothing joins it, so it becomes the last
          group and takes the next place. No earlier group moves.
        - **The next segment of a run already drawn.** It joins one
          group through an inline device and that group keeps its place,
          so at most that group's own segments are renamed -- which
          happens when the new segment brings a name or a line number
          the run did not have.
        - **A join between two runs.** Two groups become one, so every
          group after the second one moves down a place and the whole
          sheet is renumbered. Reported as ``False``.

        The non-material tail is numbered after the process runs, so it
        moves whenever the count of those does -- which is the first
        shape and no other.

        Every name still comes out of :meth:`_name_group`, the same call
        the full pass makes, so the two cannot drift. What this decides
        is *which* groups need naming again, never what they are called.
        """
        groups, index = self._groups, self._group_of
        if groups is None:  # no pass has run, so there is nothing to add to
            return False

        if stream.kind != "material":
            # Not part of any process run: it lands in the tail, and the
            # tail is short and cheap to lay out again from the front.
            self._tail.append(stream)
            self._number_tail(len(groups))
            return True

        joined = self._joined_groups(stream, index)
        if joined is None or len(joined) > 1:
            return False

        if joined:
            where = joined[0]
            group = groups[where]
            group.append(stream)
            index[id(stream)] = where
            # Named from the group's own segments rather than from the
            # cached name, so a run whose new segment carries a line
            # number the rest of it lacked is renamed here and not left
            # for the next render to notice.
            self._group_names[where] = self._name_group(group, where + 1)
            return True

        groups.append([stream])
        index[id(stream)] = len(groups) - 1
        self._group_names.append(self._name_group([stream], len(groups)))
        # One more process run means one more place used, so everything
        # numbered behind them shifts.
        self._number_tail(len(groups))
        return True

    def _joined_groups(self, stream: "Stream", index: dict) -> "list[int] | None":
        """The groups a newly connected material stream runs into.

        ``None`` where the answer cannot be trusted -- a neighbour the
        cache has no group for -- which sends the caller to a full pass.

        The run through an inline device is its ``inlet`` to its
        ``outlet``, the same rule :meth:`_stream_groups` applies, so a
        tee's *branch* joins nothing and starts a line of its own.
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
                continue  # a branch, not the run
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
        """Name the segments of one group, holding *place* in the series.

        Where a group's name is decided, and the only place: the full
        pass calls it for every group and :meth:`_number_appended` for
        the one group a new stream lands in, so the fast path cannot
        drift from the slow one. Answers the name it settled on, which
        is what the caller caches.

        *place* is 1-based and is the group's position in the sequence,
        not an index into anything.
        """
        # One count, two starts. `place` is the group's position and
        # both numbers are read off it, each from its own offset,
        # because a line sequence and a stream number are different
        # labels on different lists (see `stream_number_start` in
        # `__init__`).
        sequence = str(self.line_number_start + place - 1)
        number = self.stream_number_start + place - 1
        for s in group:
            # A sequence the author put there outranks the one numbering
            # would assign, however often it re-runs.
            if s.sequence is None or s.sequence == s._auto_sequence:
                s.sequence = s._auto_sequence = sequence
        # An explicit name on any segment names its whole group.
        name = next((s.name for s in group if not s.auto_named), None)
        if name is None:
            carrier = next((s for s in group if s.has_line_number), None)
            name = (_format_line_number(self.line_numbering_scheme, carrier)
                    if carrier is not None else
                    # The offset is applied to the number, not inside the
                    # format string, so a callable scheme is handed the
                    # same count a format string interpolates.
                    self.stream_naming_scheme(number)
                    if callable(self.stream_naming_scheme)
                    else self.stream_naming_scheme.format(n=number))
        for s in group:
            if s.auto_named:
                s.name = name
        return name

    def _number_tail(self, used: int) -> int:
        """Number the lines that are not material, after the *used*
        places the process runs took. Answers the new total.

        Energy before signals: ``sorted`` is stable, so each kind keeps
        its creation order within the tail of the sequence. Only a line
        the counter names takes a place, which is why an explicitly
        named duty consumes none.

        Read off ``_tail`` rather than filtered out of ``streams``, so a
        sheet with no duty or signal line on it does no work here at
        all. Every ``connect()`` that starts a new run calls this --
        one more run means one more place used, and everything behind
        them moves -- and a filter would have made that a scan of the
        whole sheet, which is the cost this is here to avoid.
        """
        for s in sorted(self._tail, key=lambda s: s.kind != "energy"):
            if s.auto_named:
                used += 1
                self._name_group([s], used)
        return used

    def validate(self, *, diagram: str | None = None) -> list:
        """Validation issues, errors first, then warnings.

        See :mod:`pandid.validate`. Errors are contradictions the engine
        cannot honor (overlapping pins, off-sheet coords); warnings are
        imperfections (a route crossing a unit body, a large detour).

        ``diagram`` names the drawing the findings are about, in the
        spelling :meth:`to_svg` takes it: ``"pfd"`` (the default) or
        ``"p&id"``. Two findings depend on it. A P&ID draws no
        arrowheads, so nozzles pitched inside the head they would carry
        on a PFD are not a defect there. And ``stream-table-missing``
        answers ISO 10628-1 4.3.2, a *process flow diagram*'s clause, so
        it is silent on a sheet declared a P&ID, which answers to 4.4.2
        instead. ``render()`` passes the drawing it is making, so the
        warnings left on ``fs.warnings`` are about the sheet that came
        out.

        Both halves of the check, over the sheet as it stands: the
        geometric findings need frames and routes, so call this after
        :meth:`layout` and :meth:`route` -- or after a render, which
        runs them -- to hear them. On a sheet nothing has placed yet the
        geometric half is simply silent, and the model findings are the
        answer. A render asks the two separately, and in the order
        :meth:`_prepare_to_draw` sets out.
        """
        from pandid.render.svg import draws_arrowheads
        from pandid.validate import validate as _validate
        return _validate(self, arrows=draws_arrowheads(diagram))

    def to_svg(self, *, show_stream_table: bool = False,
               border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               connections: str | None = None,
               jump_direction: str = "vertical", debug: bool | float = False,
               check: bool = True) -> str:
        """Render to an SVG string, running ``layout()`` and ``route()``
        first if they have not been run yet, or if anything changed
        since they were.

        ``border`` rules the sheet: ``"zone"`` for the zone-ruled
        drawing frame, ``"none"`` (the default) for a plain edge. The
        grid runs ISO 5457 §4.4's way -- letters A.. top down, numerals
        1.. left to right, so zone A1 is the top-left corner. The title
        block and annotation boxes attached to this flowsheet are drawn
        either way.

        ``diagram`` says which drawing this is: ``"pfd"`` (the default)
        or ``"p&id"``, also spelled ``"pid"``. A P&ID draws its process
        lines without arrowheads, since flow direction is read off the
        equipment and the line list rather than off an arrow on every
        run. The two are independent: the frame is sheet furniture and a
        PFD carries the zone-ruled one as readily as a P&ID does.

        ``page_size`` draws a sheet of exactly that standard size
        (``"A4"`` through ``"A0"``), fitting the drawing into what the
        sheet furniture leaves; omit it to size the sheet to the drawing
        instead. ``jump_direction`` selects which of two crossing lines
        gets the semicircle hop: ``"vertical"`` or ``"horizontal"``.

        ``connections`` says how the sheet's joints are made up, as the
        double tick across the run:

        * ``"none"`` (the default) marks nothing;
        * ``"flanged"`` marks every equipment nozzle **and both sides of
          every valve and in-line fitting**, which is how a body is got
          out of a line;
        * ``"flanged-at-nozzles"`` marks the nozzles only and leaves the
          bodies in the run unmarked, which is what ``P&ID_301.pdf``
          draws.

        Reducers and tees are welded fittings and take no mark under
        either. Boundary flags, instruments and signal lines are never
        marked: there is no joint to describe. Only a P&ID marks joints
        at all, per ISO 15519-2 Table 5, so this draws nothing on a PFD.
        Which bodies are flanged is a drafting choice and no standard on
        disk settles it; see :func:`~pandid.render.svg.flanged_joint`.
        One line may say otherwise with ``connect(..., ends=...)``.

        ``debug`` draws the coordinate overlay under the diagram: a
        ruled grid carrying its own coordinates, a marker on the point
        every ``pin(x=, y=)`` sets, and a marker on every port. ``True``
        rules the grid at its default 50-unit spacing and a number sets
        that spacing. It is scaffolding for whoever is writing the
        placement rather than part of the drawing, and is off by
        default.

        When ``check`` is true, validation runs around the geometry
        rather than after it: the checks that read the model alone run
        **before** ``layout()`` and ``route()``, and the ones that need
        frames and routes run once those exist. Either half raises
        :class:`ValueError` on an *error*; *warnings* from both are
        collected on ``self.warnings``. See :meth:`_prepare_to_draw`.
        """
        self._prepare_to_draw(diagram=diagram, check=check)
        from pandid.render.svg import SvgRenderer
        return SvgRenderer().render(
            self, show_stream_table=show_stream_table,
            border=border, diagram=diagram, page_size=page_size,
            connections=connections, jump_direction=jump_direction, debug=debug
        )

    def to_drawio(self, *, diagram: str | None = None,
                  page_size: str | None = None, border: str | None = None,
                  connections: str | None = None,
                  jump_direction: str = "vertical",
                  show_stream_table: bool = False, check: bool = True) -> str:
        """Render to a draw.io (``.drawio``) document string, running
        ``layout()`` and ``route()`` first if they have not been run
        yet, or if anything changed since they were.

        The drawing comes out as a *model* rather than a picture: every
        unit is a draw.io shape and every stream an edge between two of
        its connection points, so an author can open it in draw.io /
        diagrams.net and move blocks and lines by hand. It is also the
        route to Visio, which draw.io exports natively.

        The equipment symbols are draw.io's own P&ID stencils (see
        ``NOTICE``), so the file *references* them rather than carrying
        a tracing: what opens is a native, editable shape. The fifteen
        symbols this library draws itself -- the instrument balloons,
        the junctions, the off-page flags, the conveyor -- have no
        draw.io stencil behind them and are approximated with draw.io's
        built-in shapes; :mod:`pandid.render.drawio` names each one and
        what the approximation loses.

        ``diagram`` says which drawing this is, exactly as
        :meth:`to_svg` takes it: a P&ID exports its process lines
        without arrowheads. ``check`` validates on the same terms and in
        the same order -- the model before the geometry is built, the
        geometry once it is. ``connections`` marks the joints, also
        exactly as :meth:`to_svg` takes it, and in the same places --
        the two backends ask one function where a flange goes.

        Sheet furniture (the title block and any annotation boxes) is
        docked by the same arithmetic the sheet docks it with, and
        anything columnar -- an equipment list, a legend, a numbered
        note list, a :class:`~pandid.document.TableBox` -- comes out as
        a real draw.io table with rows and cells rather than one block
        of text.

        ``page_size`` puts the model on paper, exactly as it does for
        :meth:`to_svg`: the file carries the page for draw.io to rule,
        the furniture docks to that page rather than to the drawing's
        own bounds, and the drawing is fitted into what the furniture
        leaves. Omit it and the drawing keeps its own coordinates on an
        unbounded canvas, which is what a model is.

        ``border`` rules that page. ``"zone"`` draws the frame, the
        sheet edge and the lettered band between them, with one caveat:
        a zone grid is an *address space* (ISO 15519-1 Clause 9) and
        :attr:`pandid.units._Boundary.reference` writes addresses into
        it. In an editable model those do not hold -- move a column and
        it is in a different zone from the one every reference names --
        so what is exported is a **snapshot of the grid**, true of the
        drawing as it left pandid.

        ``jump_direction`` selects which of two crossing lines gets the
        semicircle hop, exactly as it does on the sheet: ``"vertical"``,
        the default, hops the vertical runs. draw.io draws the hop
        itself from a style key on the edge that carries it, and settles
        ties between two crossing lines by z-order, so the export states
        both.

        ``show_stream_table`` docks the stream property table at the
        foot of the sheet, as :meth:`to_svg` does: one column per unique
        material stream, one row per property, and the section headings
        ``stream_table_sections`` asks for. It comes out as a real
        draw.io table too, ruled across and down the way the sheet rules
        it.

        The debug overlay has no counterpart here and :meth:`render`
        refuses it for a ``.drawio`` path rather than ignoring it.
        """
        self._prepare_to_draw(diagram=diagram, check=check)
        from pandid.render.drawio import DrawioRenderer
        return DrawioRenderer().render(self, diagram=diagram,
                                       page_size=page_size, border=border,
                                       connections=connections,
                                       jump_direction=jump_direction,
                                       show_stream_table=show_stream_table)

    def render(self, path: str | Path, *, show_stream_table: bool = False,
               border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               connections: str | None = None,
               jump_direction: str = "vertical", debug: bool | float = False,
               check: bool = True) -> None:
        """Render the flowsheet and write it to *path*.

        The output format is inferred from the file extension:

        - ``.svg``: pure-Python, always available.
        - ``.pdf`` / ``.png``: require the optional export backend
          (``pip install 'pandid[pdf]'``), which ships as wheels and
          needs no system libraries. See :mod:`pandid.render.export`.
        - ``.drawio``: the editable draw.io / diagrams.net model, and
          through draw.io's own exporter the way to Visio. See
          :meth:`to_drawio`.

        Args:
            path: Output file path; its extension selects the format.
            show_stream_table: Draw a property table of all streams at
                the bottom. How that table is drawn -- its type size --
                is ``fs.stream_table``; see
                :class:`~pandid.document.StreamTableOptions`.
            border: ``"none"`` or ``"zone"`` (the zone-ruled frame).
            diagram: ``"pfd"`` (the default) or ``"p&id"``, also spelled
                ``"pid"``. A P&ID draws no arrowheads on process lines.
            page_size: Draw on a sheet of exactly this standard size,
                e.g. ``"A3"``; omit to size the sheet to the drawing.
            connections: ``"none"`` (the default), ``"flanged"`` -- the
                double tick at every equipment nozzle and both sides of
                every valve and in-line fitting -- or
                ``"flanged-at-nozzles"`` for the nozzles alone. A P&ID
                only; one line may say otherwise with
                ``connect(ends=...)``.
            jump_direction: Which crossing lines hop, ``"vertical"`` or
                ``"horizontal"``.
            debug: Draw the coordinate overlay under the diagram: the
                grid, every ``pin()`` anchor and every port. ``True``
                for the default spacing, a number to set it. Off by
                default.
            check: Validate. The model-only checks run before the
                sheet is laid out and routed, the geometric ones
                after; errors raise from either, warnings collect on
                ``warnings``. See :meth:`_prepare_to_draw`.
        """
        ext = Path(path).suffix.lower()
        if ext == ".drawio":
            # Refused rather than ignored: a caller who asked for
            # something and got a file without it has been told
            # something false about the file they now hold. The overlay
            # is scaffolding for whoever is writing a placement and
            # deliberately not part of the drawing, so exporting it
            # would put it into an editable model as ordinary cells a
            # reader would have to delete by hand.
            #
            # ``given != default`` and not ``is not False``: ``debug``
            # takes a number as well as a flag, and ``debug=0`` is not a
            # request for an overlay.
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
                               show_stream_table=show_stream_table,
                               check=check), encoding="utf-8")
            return

        svg = self.to_svg(
            show_stream_table=show_stream_table, border=border,
            diagram=diagram, page_size=page_size, connections=connections,
            jump_direction=jump_direction, debug=debug, check=check,
        )
        if ext in ("", ".svg"):
            Path(path).write_text(svg, encoding="utf-8")
        elif ext in (".pdf", ".png"):
            from pandid.render import export
            data = export.to_pdf(svg) if ext == ".pdf" else export.to_png(svg)
            Path(path).write_bytes(data)
        else:
            raise ValueError(
                f"Unsupported output format {ext!r}; use .svg, .pdf, .png, or .drawio"
            )

    def _repr_svg_(self) -> str:
        """IPython/Jupyter: display the diagram inline in a notebook."""
        return self.to_svg()

    def show(self, *, show_stream_table: bool = False,
             border: str | None = None,
             diagram: str | None = None, page_size: str | None = None,
             connections: str | None = None,
             jump_direction: str = "vertical", debug: bool | float = False,
             check: bool = True) -> None:
        """Render the flowsheet and put it on screen.

        Every keyword :meth:`render` takes, this takes and means the
        same thing by -- it is ``render()`` without the path, so a sheet
        can be previewed with its stream table, on a given page size, as
        a P&ID rather than a PFD, or with the coordinate overlay on.
        ``tests/test_show.py`` holds the two signatures equal, so
        a keyword added to ``render()`` and not to this raises there
        rather than quietly leaving the drafting call behind again.

        A **window** where there is one to be had, the way
        ``matplotlib.pyplot.show`` gives one: the sheet drawn in a
        resizable window, rescaled as the window is, and this call
        blocks until it is closed. It needs a display and the optional
        rasteriser (``pip install 'pandid[pdf]'``), since a window shows
        pixels and the renderer's own output is SVG.

        Without either, the sheet goes to the **browser** instead, which
        is what this always did, and the reason it went there is printed
        rather than left to be guessed at. A headless machine -- CI, a
        container, SSH without X11 -- takes that path without hanging or
        raising. See :mod:`pandid.render.preview`.
        """
        from pandid.render.preview import preview
        preview(self.to_svg(
            show_stream_table=show_stream_table, border=border,
            diagram=diagram, page_size=page_size, connections=connections,
            jump_direction=jump_direction, debug=debug, check=check,
        ), title=self.name)

    def __repr__(self) -> str:
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
