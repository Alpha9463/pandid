"""The top-level container and the single source of truth for connectivity.

Units are added with ``add()``; streams are created only through ``connect()``,
which validates the connection and enforces the one-stream-per-port rule.
"""

from __future__ import annotations
from pathlib import Path
from string import Formatter
from typing import Callable, TYPE_CHECKING

from pandid.stations import (
    DEFAULT_BYPASS_RISE,
    DEFAULT_DRAIN_DROP,
    DEFAULT_GAP,
    DEFAULT_VALVE_STATION_TAG_SCHEME,
)
from pandid.streams import PROCESS_KINDS, SIGNAL_KINDS, STREAM_KINDS, Stream

if TYPE_CHECKING:
    from pandid.components import Component
    from pandid.document import TitleBlock
    from pandid.loops import Loop
    from pandid.ports import Port
    from pandid.stations import ValveStation
    from pandid.units import Instrument, Unit

_ENERGY_ROLES = {"energy", "utility"}

#: Size, service, sequence and spec: the four parts almost every site's line
#: number opens with. Insulation and schedule are available to a scheme that
#: wants them, and are left out of the default because most sheets carry
#: neither: a site that quotes the schedule on the line rather than leaving it
#: to the piping class names ``{schedule}`` in a scheme of its own.
DEFAULT_LINE_NUMBERING_SCHEME = "{size}-{service}-{sequence}-{spec}"

#: Line sequences conventionally start well clear of 1, so the drawing reads
#: 1001 rather than 1 out of the box.
DEFAULT_LINE_NUMBER_START = 1001


def _format_line_number(scheme: "str | Callable[[Stream], str]", stream: Stream) -> str:
    """Assemble one stream's line number from the components the author set.

    A component left unset drops out, and so does the text introducing it, so a
    line with no spec reads ``6"-P-1001`` rather than ``6"-P-1001-``. A format
    spec still applies, which is how a site pads its sequence:
    ``"{size}-{service}-{sequence:0>4}"``.
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
        out.append(pending + (format(value, format_spec) if format_spec else value))
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


def _check_signal_pairing(src: "Port", dst: "Port", kind: str) -> None:
    """Raise unless the stream's kind matches what its two ports are.

    A signal port is a terminal for a measurement or a command: a valve's stem,
    an instrument's tap and its two signal connections. Nothing flows through
    one, so a signal line runs between two of them and process fluid runs
    between two nozzles. Unchecked, the sheet draws a process pipe into a valve
    top, or a control signal between two pumps, and claims both are real.
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


class Flowsheet:
    """A process flow diagram's topology: units, streams, and components."""

    def __init__(
        self, name: str, *,
        stream_naming_scheme: str | Callable[[int], str] = "S{n}",
        line_numbering_scheme: str | Callable[[Stream], str] = DEFAULT_LINE_NUMBERING_SCHEME,
        line_number_start: int = DEFAULT_LINE_NUMBER_START,
        valve_station_tag_scheme: "str | Callable[[str, str], str]" = (
            DEFAULT_VALVE_STATION_TAG_SCHEME),
        auto_faces: bool = True,
    ):
        self.name = name
        self.stream_naming_scheme = stream_naming_scheme
        self.line_numbering_scheme = line_numbering_scheme
        self.line_number_start = line_number_start
        # How a valve station spells its members' tags out of its control
        # valve's. A drawing office convention, like the two schemes above, so
        # it is set here for a whole sheet and overridable per station.
        self.valve_station_tag_scheme = valve_station_tag_scheme
        # Let the layout engine pick which face a movable port is piped from,
        # given where its peer landed (see :mod:`pandid.layout.faces`). Turn it off
        # to pin every port to its symbol's own nozzle plus whatever
        # :meth:`~pandid.units.Unit.nozzle` named, which is what a sheet already
        # tuned by hand wants.
        self.auto_faces = auto_faces
        self.units: list = []
        self.streams: list[Stream] = []
        self.components: list = []
        # Declared control loops, in declaration order. A loop is a namespace
        # and not a drawn thing, so it is kept apart from `units`: layout,
        # routing, validation, the renderer and the equipment list all iterate
        # `units` unconditionally and none of them has anything to do with it.
        self.loops: list["Loop"] = []
        self.warnings: list = []  # soft validation findings from the last render
        # Did the last route() settle its attached instruments, or run out of
        # passes still moving them? Read by validate(), which is what carries
        # the answer onto `warnings` and in front of the author.
        self.route_converged: bool = True
        # The sheet's own metadata; a block set here is a title strip drawn.
        self.title_block: "TitleBlock | None" = None
        # Generic titled boxes (equipment list, notes, legend, tables) docked to
        # the sheet corners, drawn wherever they are added. See pandid.document.
        self.annotations: list = []
        # Section headers to inject into the stream table: (before_key, label).
        self.stream_table_sections: list[tuple[str, str]] = []

    def add_annotation(self, annotation):
        """Register a sheet-furniture box (Annotation / TableBox). Chainable."""
        self.annotations.append(annotation)
        return annotation

    def add(self, unit: "Unit") -> "Unit":
        """Register a unit on this flowsheet. Returns the unit for chaining.

        A tag names one item, so a tag already on the sheet is refused. The
        exceptions are the symbols that stand for one thing shown in several
        places: an interlock square is one piece of logic drawn at every place
        it acts, and a utility header flag
        (``Feed``/``Product`` with ``header=True``) is one service drawn at
        every place it is tapped. A sheet that cannot draw the square four
        times cannot draw the interlock, and one that cannot draw ``CWSH``
        twice cannot show cooling water reaching two coolers. A
        :class:`~pandid.units.Tee` repeats for the opposite reason: it draws no
        tag at all, so there is nothing on the sheet for two of them to confuse.

        Such a repeat is accepted and given a name of its own (``I-1``,
        ``I-1 (2)``), so the unit that a stream, a spec entry or an equipment
        list means is never in doubt, while the tag drawn stays ``I-1``.
        """
        if unit in self.units:
            raise ValueError(
                f"{unit!r} is already on this flowsheet"
            )
        clash = next((u for u in self.units if u.name == unit.name), None)
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
                f"A Tee repeats against another Tee, having no tag to clash with, "
                f"but the name is still what a stream and a spec entry reach it by, "
                f"so it may not take one that already means something else."
            )
        if unit.flowsheet is not None:
            raise ValueError(
                f"{unit!r} is already on flowsheet {unit.flowsheet.name!r}"
            )
        if clash is not None:
            # The tag is what repeats and so what the fresh name is derived
            # from. A tee draws none, so its name stands in: it is already the
            # only handle anything has on that junction.
            unit.name = self._repeat_name(unit.tag or unit.name)
        unit.flowsheet = self
        self.units.append(unit)
        return unit

    def _repeat_name(self, tag: str) -> str:
        """A free name for one more drawing of a repeated tag.

        The tag is what the sheet draws and what repeats; the name is what the
        flowsheet is addressed by, so it stays unique and stays derived from the
        tag: second, third and fourth square of ``I-1`` become ``I-1 (2)``,
        ``I-1 (3)``, ``I-1 (4)``, in the order they are added.
        """
        taken = {u.name for u in self.units}
        n = 2
        while f"{tag} ({n})" in taken:
            n += 1
        return f"{tag} ({n})"

    def add_loop(self, variable: str, number: str | int) -> "Loop":
        """Declare a control loop and return the handle its members are tagged from.

        ``variable`` is the ISA measured-variable letter (``"F"``, ``"L"``,
        ``"T"``) and ``number`` the loop number. A loop is identified by the
        **pair**: ``add_loop("F", 101)`` and ``add_loop("L", 101)`` are two
        loops on one sheet, which is what most sheets draw.

        The loop replaces the number, not the letters. Each member still types
        its own functional letters and the loop checks the first of them, so a
        ``TT`` put on a flow loop raises at that line::

            loop = fs.add_loop("F", 303)
            fs.add_instrument("FE", loop, on=line, at=0.5, offset=0)
            ft = fs.add_instrument("FT", loop, on=line, at=0.5, offset=95)
            cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

        A loop draws nothing, is never in :attr:`units`, and reaches no
        equipment list; see :mod:`pandid.loops`. Instruments that are in no loop
        keep taking a literal number. An indicator standing on its own and a
        repeated interlock square with no measured variable at all are both
        correct as they stand.

        Unlike a stream number, a loop number allocates once and is never
        rewritten: it leaves the drawing for the DCS.
        """
        from pandid.loops import Loop

        loop = Loop(variable, number)
        clash = next((existing for existing in self.loops
                      if (existing.variable, existing.number) == (loop.variable, loop.number)),
                     None)
        if clash is not None:
            raise ValueError(
                f"loop {loop.name} is already declared on this flowsheet. A loop is "
                f"identified by its measured variable and its number together, so two "
                f"handles on {loop.name} are two names for one loop; hold on to the one "
                f"add_loop() returned. Two loops may share a number if they measure "
                f"different variables (F-101 and L-101)"
            )
        self.loops.append(loop)
        return loop

    def add_instrument(self, type: str, number: "str | int | Loop" = "", *,
                       on: "Stream | Unit | None" = None, at: float | str | None = None,
                       offset: float = 45.0, angle: float = 90.0,
                       variant: str = "default", **kwargs) -> "Instrument":
        """Add an ISA-5.1 instrument balloon, optionally anchored to its host.

        ``type`` is the functional letter string and ``number`` the loop number;
        together they make the tag (``add_instrument("FT", 101)`` -> ``FT-101``).
        ``number`` also takes a :class:`~pandid.loops.Loop` from :meth:`add_loop`,
        which supplies the number and checks ``type`` against the loop's measured
        variable, raising here rather than warning at render time.
        ``on``/``at``/``offset``/``angle`` are passed straight to
        :meth:`~pandid.units.Instrument.attach`; without ``on`` the balloon is laid
        out like any other unit.

        >>> s = fs.connect(feed.outlet, fv.inlet)
        >>> fs.add_instrument("FE", 101, on=s, at=0.4, offset=0)     # in-line element
        >>> fs.add_instrument("FT", 101, on=s, at=0.4, offset=60)    # transmitter above
        """
        from pandid.loops import Loop
        from pandid.units import Instrument

        if isinstance(number, Loop):
            number.check(type)
            number = number.number
        inst = Instrument(type, number, variant=variant, **kwargs)
        self.add(inst)
        if on is not None:
            inst.attach(on, at=at, offset=offset, angle=angle)
        return inst

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

        Two isolation valves, two drain valves, one bypass valve on a leg tapped
        outside the isolations, and a size change at each end: the arrangement
        the CHEE4001/7103 guidelines draw and :mod:`pandid.stations` quotes. The
        units are added, tagged, described, pinned along a run at ``y`` and
        wired to each other; what is left for the author is the piping either
        side of it, which is what :attr:`~pandid.stations.ValveStation.inlet` and
        :attr:`~pandid.stations.ValveStation.outlet` are for::

            station = fs.add_valve_station("CV-303", x=670, y=440, mirrored=True,
                                           description="Reflux", service="AE",
                                           sequence=303, size=80, schedule=80,
                                           spec="SS")
            fs.connect(t_draw.branch, station.inlet, service="AE", sequence=303,
                       size=80, schedule=80, spec="SS")
            fs.connect(station.outlet, fe303.inlet)

        The returned :class:`~pandid.stations.ValveStation` is a handle, not a
        unit: it draws nothing, reaches no equipment list, and its members are
        ordinary units that can be re-pinned, re-tagged or instrumented.

        Args:
            tag: The control valve's tag, and what the other members' tags are
                derived from.
            x: Left edge of the drawn station; ``y`` is the run's **centreline**,
                so each device lands on the line whatever its artwork measures.
                Give both or neither; without them the members lay out like any
                other units, which is a legal sheet but not a station-shaped one.
            mirrored: Pipe the run east to west. The station still occupies
                ``x`` rightwards; what reverses is which end the flow enters.
            variant: The control valve's variant.
            number: The number the members are tagged from, defaulting to the
                one in ``tag``. The escape hatch for a control valve whose own
                number is not what its station is numbered by: ``CV-301-1`` with
                ``number=301`` gives ``HV-301A``, not ``HV-301-1A``.
            isolation: Draw the two isolation valves.
            reducers: Draw the reduction in and the expansion out.
            bypass: Draw the bypass leg and its normally closed throttling valve.
            drains: How many drain valves, 0, 1 or 2. One goes upstream.
            description: The service in words. Each member's description is this
                plus what it does: ``"Reflux Isolation Valve"``.
            bypass_over: The member the bypass valve stands over, one of
                :data:`~pandid.stations.BYPASS_ANCHORS`; by default it sits in
                the middle of its own leg, which is where the reference figure
                draws it. Move it when something else already crosses there: a
                controller's output dropping onto the actuator, most often.
            tag_scheme: Overrides :attr:`valve_station_tag_scheme` for this
                station only.
            gap: Edge to edge between devices along the run.
            bypass_rise: How far the bypass leg stands off the run.
            drain_drop: How far a drain leg hangs below it.
            size, schedule, service, sequence, spec, insulation: The line
                number's components, put on the bypass and drain branches. A
                branch off a tee starts a number of its own, and a bypass is the
                same service, size and spec as the run it goes round, so the
                station's own number is what they take. The run through the
                station carries the number of whatever is connected to
                :attr:`inlet`.

        Raises:
            ValueError: for a station that cannot mean what it says: a bypass
                with nothing to bypass around, a drain count that is not 0, 1 or
                2, one of ``x``/``y`` without the other, or a ``bypass_over``
                naming a member this station was told to leave out.
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

        # The order the fluid meets them, which is the order the figure draws
        # them and the order the streams below are made in. A mirrored station
        # is this run drawn the other way round, not a different one.
        run = [u for u in (t_bya, iso_a, t_dra, red, control, exp, t_drb, iso_b, t_byb)
               if u is not None]
        anchors = {"upstream_isolation": iso_a, "downstream_isolation": iso_b,
                   "reduction": red, "expansion": exp, "control": control}

        if bypass_over is not None and anchors[bypass_over] is None:
            raise ValueError(
                f"{tag}: bypass_over={bypass_over!r} names a member this station was "
                f"told to leave out"
            )

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
                # A drain runs down to a funnel on the floor, which is not on
                # this sheet, so the leg ends at the valve.
                drain.pin(orientation=90)
                drain.pin(port="inlet",
                          x=left[id(junction)] + port_offset(junction, "branch")[0],
                          y=y + drain_drop)
            if byp is not None and t_bya is not None and t_byb is not None:
                target = anchors[bypass_over] if bypass_over is not None else None
                if target is not None:
                    centre = left[id(target)] + resolve_size(target)[0] / 2
                else:
                    # Nothing named, so the middle of its own leg, which is
                    # where the reference figure draws it.
                    centre = sum(left[id(t)] + port_offset(t, "branch")[0]
                                 for t in (t_bya, t_byb)) / 2
                byp.pin(mirrored="x" if mirrored else False)
                byp.pin(x=centre - resolve_size(byp)[0] / 2)
                byp.pin(port="inlet", y=y - bypass_rise)

        def branch_line(src: "Port", dst: "Port") -> Stream:
            """A leg off the run, carrying the station's own line number."""
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
        """Register a chemical component. Returns the component for chaining."""
        self.components.append(component)
        return component

    def connect(self, src: "Port", dst: "Port", *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False,
                size: str | float | None = None, schedule: str | float | None = None,
                service: str | float | None = None,
                sequence: str | float | None = None, spec: str | float | None = None,
                insulation: str | float | None = None) -> Stream:
        """Create a stream connecting *src* (outlet port) to *dst* (inlet port).

        The returned stream already carries the number it will be drawn with;
        see :meth:`renumber_streams`.

        ``kind`` has to match what the two ports are: a signal kind runs between
        two signal connections (a valve's ``actuator``, an instrument's ``pv``
        and ``sig_in``/``sig_out``) and a process kind between two process
        nozzles. Mixing them draws a pipe into a valve stem or a control signal
        between two pumps.

        ``size``/``schedule``/``service``/``spec``/``insulation`` are the
        line-number components; supplying any of them draws this line with its
        line number instead of a stream number. ``sequence`` is filled by
        auto-numbering unless it is given here. ``size`` is the line's nominal
        bore, ``schedule`` the wall it is bought to at that bore, and ``spec``
        the piping class or material the line is built to.

        Raises :class:`ValueError` if any validation rule is violated.
        """
        if kind not in STREAM_KINDS:
            raise ValueError(
                f"Stream kind must be one of {sorted(STREAM_KINDS)}, got {kind!r}"
            )

        if src.direction != "outlet":
            raise ValueError(
                f"source port {src.owner.name}.{src.name} must be an outlet, "
                f"got {src.direction!r}"
            )
        if dst.direction != "inlet":
            raise ValueError(
                f"destination port {dst.owner.name}.{dst.name} must be an inlet, "
                f"got {dst.direction!r}"
            )
        if src.owner.flowsheet is not self or dst.owner.flowsheet is not self:
            raise ValueError(
                "both units must be added to this flowsheet before connecting"
            )
        if src.stream is not None:
            raise ValueError(
                f"port {src.owner.name}.{src.name} is already connected"
            )
        if dst.stream is not None:
            raise ValueError(
                f"port {dst.owner.name}.{dst.name} is already connected"
            )
        _check_signal_pairing(src, dst, kind)
        if kind == "material" and src.role in _ENERGY_ROLES and dst.role in _ENERGY_ROLES:
            kind = "energy"

        stream = Stream(
            name=name or "",  # an auto-named stream is numbered by renumber_streams()
            source=src,
            dest=dst,
            kind=kind,
            tear_hint=tear_hint,
            auto_named=not name,
            size=size,
            schedule=schedule,
            service=service,
            sequence=sequence,
            spec=spec,
            insulation=insulation,
        )
        src.stream = stream
        dst.stream = stream
        self.streams.append(stream)
        # The number a caller reads off the returned stream, into a report, a
        # stream table or a label of their own, has to be the number that gets
        # drawn, so numbering is settled here rather than at render time.
        self.renumber_streams()
        return stream

    @classmethod
    def from_dict(cls, spec: dict) -> "Flowsheet":
        """Build a flowsheet from a declarative spec ``dict``.

        See :mod:`pandid.spec` for the format. Raises :class:`pandid.spec.SpecError`
        (a :class:`ValueError`) naming the offending entry.
        """
        from pandid.spec import from_dict as _from_dict
        return _from_dict(spec)

    @classmethod
    def from_json(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a JSON spec file. See :mod:`pandid.spec`."""
        from pandid.spec import from_json as _from_json
        return _from_json(path)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a YAML spec file (needs the ``yaml`` extra).

        See :mod:`pandid.spec`.
        """
        from pandid.spec import from_yaml as _from_yaml
        return _from_yaml(path)

    def to_dict(self) -> dict:
        """Serialize the flowsheet to a JSON-safe declarative spec ``dict``.

        Round-trips: ``Flowsheet.from_dict(fs.to_dict())`` rebuilds an
        equivalent flowsheet. See :mod:`pandid.spec` for the format.
        """
        from pandid.spec import to_dict as _to_dict
        return _to_dict(self)

    def layout(self, engine=None) -> None:
        """Run the automatic layout engine to generate unit coordinates."""
        if engine is None:
            from pandid.layout import default_layout_engine
            engine = default_layout_engine
        engine.layout(self)

    def route(self, router=None) -> None:
        """Run the automatic routing engine to generate orthogonal stream paths.

        Runs :meth:`layout` first if any unit still lacks a resolved frame, since
        routing needs geometry to work against.

        Attached instruments are placed and the sheet re-routed until the two
        agree, up to :data:`~pandid.layout.attach.MAX_PLACEMENT_PASSES`. A sheet
        that never settles leaves ``route_converged`` false, which
        :meth:`validate` reports as a warning.
        """
        if any(u.frame is None for u in self.units):
            self.layout()
        if router is None:
            from pandid.routing import DefaultRouter
            router = DefaultRouter()
        from pandid.layout.attach import MAX_PLACEMENT_PASSES, place_attached
        router.route(self)
        # An attached balloon hangs off its host's *routed* path, so where it
        # finally lands is only known once that path exists. Layout placed it on
        # the straight port-to-port line, which is already right for a straight
        # run; when the router bent the line, re-place it and re-route the
        # signal lines that now leave from somewhere else.
        #
        # That re-route can move a balloon again, because the box it now
        # occupies is an obstacle in a place the last pass had clear, so the two
        # chase each other to a fixed point rather than trading a fixed two
        # turns. The loop always ends on a route, whether it converged or ran
        # out of passes, so the waypoints describe the balloons where they now
        # are and no signal line is left pointing at where one used to be.
        self.route_converged = False
        for _ in range(MAX_PLACEMENT_PASSES):
            if not place_attached(self):
                self.route_converged = True
                break
            router.route(self)

    def renumber_streams(self) -> None:
        """Assign stream numbers, carrying one number through inline fittings.

        Runs on every :meth:`connect` and again before rendering, so the name on
        the stream object a caller holds is the name that gets drawn.

        Valves, reducers, fittings and tees are inline: a stream keeps its
        number as it passes through them (set ``unit.significant = True`` to
        break the number at an important valve). Explicitly-named streams keep
        their name and lend it to their whole inline group. What carries the
        number through is the ``inlet`` to ``outlet`` run, so a tee's *branch*
        takes a number of its own: the bypass leg or drain off a station is its
        own line, and the run it leaves carries straight on.

        A line carrying line-number components is named by its line number
        rather than its stream number, on the same terms: the first segment of a
        group that carries components supplies them for the whole group, so a
        line number survives an inline valve and breaks where a significant one
        does, which is exactly where the spec breaks.

        Process streams take the low numbers because they are the ones drawn on
        the sheet and quoted in the stream table; energy streams, which are also
        drawn, follow, and unlabelled signal lines come last. One sequence
        covers all three so no two streams answer to the same name.
        """
        _INLINE = {"valve", "reducer", "fitting", "tee"}
        material = [s for s in self.streams if s.kind == "material"]
        pos = {id(s): i for i, s in enumerate(material)}  # Stream is unhashable
        parent = list(range(len(material)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # The run through an inline device is its ``inlet`` to its ``outlet``,
        # named rather than counted: a tee has a third process connection and
        # counting cannot say which two of the three are the run. The two names
        # are the whole of what every inline kind has in common, and on a valve,
        # a reducer or a fitting they are its only process nozzles, so this is
        # the same joining those kinds already had.
        for u in self.units:
            if u.kind in _INLINE and not getattr(u, "significant", False):
                run = [u.ports.get("inlet"), u.ports.get("outlet")]
                ends = [pos[id(p.stream)] for p in run
                        if p is not None and p.stream is not None and id(p.stream) in pos]
                if len(ends) == 2:
                    parent[find(ends[0])] = find(ends[1])

        # An explicit name on any segment names its whole group.
        explicit: dict = {}
        for i, s in enumerate(material):
            if not s.auto_named:
                explicit.setdefault(find(i), s.name)

        n = 0

        def next_name(group: list[Stream]) -> str:
            """Take the next number for one group of segments sharing a name."""
            nonlocal n
            n += 1
            sequence = str(self.line_number_start + n - 1)
            for s in group:
                # A sequence the author put there outranks the one numbering
                # would assign, however often numbering re-runs.
                if s.sequence is None or s.sequence == s._auto_sequence:
                    s.sequence = s._auto_sequence = sequence
            carrier = next((s for s in group if s.has_line_number), None)
            if carrier is not None:
                return _format_line_number(self.line_numbering_scheme, carrier)
            return (self.stream_naming_scheme(n)
                    if callable(self.stream_naming_scheme)
                    else self.stream_naming_scheme.format(n=n))

        segments: dict = {}
        for i, s in enumerate(material):
            segments.setdefault(find(i), []).append(s)

        group_name: dict = {}
        for i in range(len(material)):  # first-appearance order
            r = find(i)
            if r in group_name:
                continue
            group_name[r] = explicit[r] if r in explicit else next_name(segments[r])

        for i, s in enumerate(material):
            if s.auto_named:
                s.name = group_name[find(i)]

        # Energy before signals: `sorted` is stable, so each kind keeps its
        # creation order within the tail of the sequence.
        for s in sorted((s for s in self.streams if s.kind != "material"),
                        key=lambda s: s.kind != "energy"):
            if s.auto_named:
                s.name = next_name([s])

    def validate(self) -> list:
        """Return validation issues for the flowsheet (errors first, then warnings).

        See :mod:`pandid.validate`. Errors are contradictions the engine cannot
        honor (overlapping pins, off-sheet coords); warnings are imperfections
        (a route crossing a unit body, a large detour).
        """
        from pandid.validate import validate as _validate
        return _validate(self)

    def to_svg(self, *, show_stream_table: bool = False,
               styling: str = "default", border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               jump_direction: str = "vertical", check: bool = True) -> str:
        """Render the flowsheet to an SVG string, running ``layout()`` and
        ``route()`` first if they have not been run yet.

        ``border`` rules the sheet: ``"zone"`` for the ASME-style zone-ruled
        drawing frame, ``"none"`` (the default) for a plain edge. The title
        block and annotation boxes attached to this flowsheet are drawn either
        way.

        ``diagram`` says which drawing this is: ``"pfd"`` (the default) or
        ``"p&id"``, also spelled ``"pid"``. A P&ID draws its process lines
        without arrowheads, since flow direction is read off the equipment and
        the line list rather than off an arrow on every run.
        ``styling="p&id"`` asks for both at once (``border="zone"`` with
        ``diagram="p&id"``) and is the older spelling of the option.

        ``page_size`` draws a sheet of exactly that standard size (``"A4"``
        through ``"A0"``), fitting the drawing into what the sheet furniture
        leaves; omit it to size the sheet to the drawing instead.
        ``jump_direction`` selects which of two crossing lines gets the
        semicircle hop: ``"vertical"`` or ``"horizontal"``.

        When ``check`` is true, validation runs first: any *error* raises
        :class:`ValueError`, and *warnings* are collected on ``self.warnings``.
        """
        if any(u.frame is None for u in self.units):
            self.layout()
        if any(s.route is None for s in self.streams):
            self.route()
        self.renumber_streams()
        if check:
            issues = self.validate()
            self.warnings = [i for i in issues if i.severity == "warning"]
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                raise ValueError(
                    "Flowsheet validation failed:\n"
                    + "\n".join(f"  {e}" for e in errors)
                )
        from pandid.render.svg import SvgRenderer
        return SvgRenderer().render(
            self, show_stream_table=show_stream_table, styling=styling,
            border=border, diagram=diagram, page_size=page_size,
            jump_direction=jump_direction
        )

    def render(self, path: str | Path, *, show_stream_table: bool = False,
               styling: str = "default", border: str | None = None,
               diagram: str | None = None, page_size: str | None = None,
               jump_direction: str = "vertical", check: bool = True) -> None:
        """Render the flowsheet and write it to *path*.

        The output format is inferred from the file extension:

        - ``.svg``: pure-Python, always available.
        - ``.pdf`` / ``.png``: require the optional ``cairosvg`` backend
          (``pip install 'pandid[pdf]'``).

        Args:
            path: Output file path; its extension selects the format.
            show_stream_table: Draw a property table of all streams at the bottom.
            border: ``"none"`` or ``"zone"`` (the zone-ruled drawing frame).
            diagram: ``"pfd"`` (the default) or ``"p&id"``, also spelled
                ``"pid"``. A P&ID draws its process lines without arrowheads.
            styling: Both at once, and the older spelling: ``"p&id"`` means
                ``border="zone"`` with ``diagram="p&id"``.
            page_size: Draw on a sheet of exactly this standard size, e.g.
                ``"A3"``; omit to size the sheet to the drawing.
            jump_direction: Which crossing lines hop, ``"vertical"`` or ``"horizontal"``.
            check: Validate first; errors raise, warnings collect on ``warnings``.
        """
        svg = self.to_svg(
            show_stream_table=show_stream_table, styling=styling, border=border,
            diagram=diagram, page_size=page_size, jump_direction=jump_direction,
            check=check,
        )
        ext = Path(path).suffix.lower()
        if ext in ("", ".svg"):
            Path(path).write_text(svg, encoding="utf-8")
        elif ext in (".pdf", ".png"):
            try:
                import cairosvg
            except ImportError as e:
                raise ImportError(
                    f"Exporting {ext} requires the optional cairosvg backend. "
                    "Install it with: pip install 'pandid[pdf]'"
                ) from e
            data = svg.encode("utf-8")
            if ext == ".pdf":
                cairosvg.svg2pdf(bytestring=data, write_to=str(path))
            else:
                cairosvg.svg2png(bytestring=data, write_to=str(path))
        else:
            raise ValueError(
                f"Unsupported output format {ext!r}; use .svg, .pdf, or .png"
            )

    def _repr_svg_(self) -> str:
        """IPython/Jupyter integration: display the diagram inline in notebooks."""
        return self.to_svg()

    def show(self) -> None:
        """Render the flowsheet and open it in the default web browser."""
        import tempfile
        import webbrowser
        import os
        
        fd, temp_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        
        self.render(temp_path)
        webbrowser.open(f"file://{temp_path}")

    def __repr__(self) -> str:
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
