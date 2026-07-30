"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``), and each subclass annotates those attributes
(``suction: Port``) so an editor and a type checker can see them; see
:class:`Unit` for why the annotation is a declaration rather than a second copy.

This module is also the public ``units`` namespace: ``from pandid import units``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from pandid.geometry import Frame, Pin, _Slot
from pandid.ports import Port

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

__all__ = [
    "Unit",
    "Feed", "Product", "Pump", "Compressor", "Blower", "Valve", "Vessel", "Tank",
    "HeatExchanger", "Heater", "Cooler", "Reactor", "Separator", "Column",
    "Mixer", "Splitter", "Tee", "Reducer", "Fitting", "Ejector", "Vent", "Funnel",
    "Furnace", "Turbine", "Filter", "Dryer", "Conveyor", "Instrument",
]

# "signal" is the odd one out: every other role names something that flows in a
# pipe, so only a signal port may carry a signal line and only a process one may
# carry fluid. :meth:`pandid.flowsheet.Flowsheet.connect` enforces the pairing.
_VALID_ROLES = {"process", "feed", "product", "energy", "utility", "vapor",
                "liquid", "signal"}

# The same side vocabulary label_pos uses, so a sheet does not need two spellings
# for "the top of this unit".
_FACE_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}

# "not supplied", for pin() arguments whose falsy value is a real request.
# ``orientation=0`` and ``mirrored=False`` mean "put it back", so they cannot
# double as the default the way ``None`` does for the pinned axes.
_UNCHANGED: Any = object()

# What the chainable placement methods hand back: the very class they were
# called on, not the base. ``fs.add(units.HeatExchanger("E-1")).pin(x=210)`` is
# how a manually placed sheet is written, so a plain ``-> Unit`` would throw the
# subclass away mid-chain and with it the nozzle declarations below.
_UnitT = TypeVar("_UnitT", bound="Unit")


class Unit:
    #: The equipment type this unit is drawn as: the key the symbol registry is
    #: looked up by, and the tag a spec's ``kind:`` names. One per class.
    kind: str = "unit"
    #: The unit's nozzles, one ``(name, direction, role)`` tuple each: the name
    #: a stream is connected by, ``"inlet"`` or ``"outlet"``, and one of
    #: :data:`_VALID_ROLES`. Read once when the unit is constructed, so the
    #: nearest declaration in the class hierarchy is the whole list. A unit
    #: whose nozzle count the caller decides adds its ports in ``__init__``
    #: instead, as :class:`Mixer` does.
    PORTS: list[tuple[str, str, str]] = []

    #: The layout engine's solver scratch, seeded from :attr:`pin_` at the start
    #: of every run by ``pandid.layout._seed_slots`` and read by nothing outside
    #: that package. Declared rather than initialised in ``__init__`` because a
    #: unit that has never been laid out genuinely does not have one, which is
    #: what the engine's own ``assert u._slot is not None`` lines are checking.
    _slot: _Slot | None

    # Every subclass below writes its nozzle names out a second time, as bare
    # class annotations (``suction: Port``) beside the ``PORTS`` list that
    # builds them. The ports themselves are still built by ``_add_port``, whose
    # ``setattr`` no type checker can follow, so before the annotations existed
    # ``pump.suction`` was invisible to mypy and to editor completion even
    # though the package ships ``py.typed``, and a misspelled nozzle was found
    # only when the sheet was drawn.
    #
    # An annotation with no assignment binds nothing: it lands in the class's
    # ``__annotations__`` and nowhere else, so nothing about construction, the
    # ``ports`` dict or the drawn sheet changes. That is what makes this a
    # *declaration* of what ``PORTS`` produces rather than a second
    # implementation of it, and ``tests/test_port_annotations.py`` holds the two
    # halves to each other in both directions so they cannot drift apart.

    @classmethod
    def _declared_ports(cls) -> list[tuple[str, str, str]]:
        """The ports this class declares.

        The nearest class in the MRO to name :attr:`PORTS` answers for the whole
        list, empty or not, exactly as an attribute lookup would: overriding a
        declaration replaces it.
        """
        for klass in cls.__mro__:
            if "PORTS" in klass.__dict__:
                return list(klass.__dict__["PORTS"])
        return []

    def __init__(self, name: str, variant: str = "default", width: float | None = None, height: float | None = None, label_pos: str | None = None, description: str = "", reference: str = ""):
        if not name:
            raise ValueError("Unit name cannot be empty")
        self.name = name
        self.variant = variant
        self.width = width
        self.height = height
        self.label_pos = label_pos
        # Free-text equipment description (used by the auto equipment list).
        self.description = description
        # Off-page reference for boundary flags (Feed/Product): the drawing this
        # stream comes from / goes to, drawn as the connector's second line. It
        # is a statement about where the sheet ends, and equipment is not where
        # a sheet ends, so nothing else has anywhere to draw it.
        if reference and self.kind not in ("feed", "product"):
            raise ValueError(
                f"{name}: reference= names the drawing an off-page connector "
                f"continues onto, and a {type(self).__name__} is drawn as equipment. "
                f"Put it on the Feed or Product where the line crosses the sheet edge."
            )
        self.reference = reference
        self.flowsheet: Flowsheet | None = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        self._new_line_number = False
        self.pin_: Pin | None = None      # user intent (set only via pin())
        self.frame: Frame | None = None   # resolved geometry (set only by layout)
        self._port_faces: dict[str, str] = {}   # port name -> chosen face
        for spec in self._declared_ports():
            self._add_port(*spec)

    @property
    def tag(self) -> str:
        """The tag drawn against this unit.

        One piece of plant carries one tag and is drawn once, so for equipment
        the tag *is* the name the flowsheet knows it by. Only a symbol that
        stands for something drawn in several places has to tell the two apart;
        see :attr:`Instrument.tag` and :attr:`_Boundary.tag`.
        """
        return self.name

    def repeats(self, other: "Unit") -> bool:
        """Whether this unit is *another drawing of* ``other``.

        False here, and so for every piece of equipment: two units answering to
        ``P-101`` are two pumps sharing a tag, which is a mistake in the
        drawing rather than a convention of it. Overridden by the two symbols
        that stand for one thing shown in several places (the interlock square,
        :meth:`Instrument.repeats`, and the utility header flag,
        :meth:`_Boundary.repeats`), and by the one that stands for nothing at
        all, the pipe tee (:meth:`Tee.repeats`), which draws no tag to clash.
        """
        return False

    @property
    def new_line_number(self) -> bool:
        """Whether the line identifier breaks across this inline fitting.

        On a valve, reducer or fitting, True breaks the stream number (or the
        line number, where the line has one) across the unit instead of
        carrying it through, which is where a spec break goes.

        Setting it renumbers the flowsheet, so the names on the stream objects
        the caller already holds stay the names that get drawn.
        """
        return self._new_line_number

    @new_line_number.setter
    def new_line_number(self, value: bool) -> None:
        self._new_line_number = value
        if self.flowsheet is not None:
            self.flowsheet.renumber_streams()

    def pin(
        self: _UnitT,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = _UNCHANGED,
        mirrored: bool | str = _UNCHANGED,
        port: str | None = None,
    ) -> _UnitT:
        """Pin the unit to a specific layout grid cell or exact pixel coordinate.

        Records *intent* only. The layout engine reads it and resolves the final
        :class:`~pandid.geometry.Frame`; pinned axes are honored exactly.

        ``orientation`` is a clockwise quarter turn in degrees (0/90/180/270); a
        quarter turn swaps the unit's width and height. ``mirrored`` flips the
        symbol: ``True`` or ``"x"`` left↔right (swapping its E and W faces),
        ``"y"`` top↔bottom (swapping N and S), ``"xy"`` both.

        ``port`` names a nozzle, and the coordinates given then locate **that
        nozzle** rather than the unit's top-left corner. A run is a line at one
        elevation and the devices on it are whatever size their artwork is, so
        ``valve.pin(port="inlet", y=run_y)`` is how a valve is put *on* a run
        without writing down half its height. The offset comes from
        :func:`pandid.portgeom.port_offset`, which asks the symbol. Only the axes
        this call names are read that way, so ``pin(x=..., port="inlet",
        y=run_y)`` steps along a row by the corner and still lands the nozzle on
        the line. A grid cell has no nozzle in it, so ``port`` refuses
        ``col``/``row``.

        Every argument is optional and an omitted one leaves that part of the
        placement as it stands, so nudging a unit with a second ``pin(y=...)``
        keeps the turn and the flip the first call asked for. Pass
        ``orientation=0`` / ``mirrored=False`` to clear them.
        """
        from dataclasses import replace

        from pandid.geometry import normalize_mirror, normalize_orientation

        candidate = replace(self.pin_ if self.pin_ is not None else Pin())
        for axis, value in (("col", col), ("row", row), ("x", x), ("y", y)):
            if value is not None:
                setattr(candidate, axis, value)
        if orientation is not _UNCHANGED:
            candidate.orientation = normalize_orientation(orientation)
        if mirrored is not _UNCHANGED:
            candidate.mirrored, candidate.mirror_y = normalize_mirror(mirrored)
        if port is not None:
            if col is not None or row is not None:
                raise ValueError(
                    f"{self.name}: pin(port=...) reads x/y as the position of a "
                    f"nozzle, and col/row name a grid cell, which has no nozzle in "
                    f"it. Give x/y, or drop port="
                )
            # After the transform, never before: a mirror moves the nozzle
            # within the box, so an offset taken from the placement this call
            # replaces would put the device half a body off its run.
            self._offset_to_port(candidate, port, x, y)
        # A nozzle() choice names a face on the finished sheet, and this
        # transform is what decides which placement lands there. Check the
        # *candidate*: asking about the committed placement answers for the
        # sheet this call is replacing, and committing first would leave the
        # unit in exactly the state a raise here exists to prevent.
        if self._port_faces:
            from pandid.portgeom import port_faces

            for port_name, face in self._port_faces.items():
                self._check_face(port_name, face, port_faces(self, port_name, candidate))
        self.pin_ = candidate
        return self

    def _offset_to_port(self, candidate: Pin, port_name: str,
                        x: float | None, y: float | None) -> None:
        """Re-read a candidate's named axes as the position of one nozzle.

        Writes the corner the nozzle asked for back onto the pin, so what is
        stored stays the one thing a :class:`~pandid.geometry.Pin` has ever
        meant. Pinning the same nozzle to the same point twice is therefore the
        same placement twice, not a device walking off its run.
        """
        if port_name not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {port_name!r} to "
                f"pin by; available ports: {sorted(self.ports)}"
            )
        from pandid.portgeom import port_offset

        dx, dy = port_offset(self, port_name, candidate)
        if x is not None:
            candidate.x = x - dx
        if y is not None:
            candidate.y = y - dy

    def nozzle(self: _UnitT, port_name: str, face: str) -> _UnitT:
        """Pipe a port from a named face of the unit *as drawn*.

        Many vessels can be piped from more than one side, and the layout engine
        already picks between them from where the peer landed (see
        :mod:`pandid.layout.faces`); this overrides that pick, which is how a
        drawing convention gets stated. ``face`` is the compass point on the
        finished sheet (``"N"``/``"S"``/``"E"``/``"W"``, or the
        ``top``/``bottom``/``left``/``right`` spelling ``label_pos`` uses), so a
        mirrored unit takes the face the reader sees rather than the one the
        stencil happened to be drawn with.

        Raises :class:`KeyError` for an unknown port and :class:`ValueError` when
        the symbol offers no placement on that face (a column's bottoms nozzle,
        for instance, is fixed by physics and offers exactly one).

        Because the drawn face depends on the placement transform, a later
        :meth:`pin` that rotates or mirrors the unit re-checks the choice and
        raises if it no longer reaches that face.
        """
        from pandid.portgeom import port_faces

        if port_name not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        face = _FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
        self._check_face(port_name, face, port_faces(self, port_name))
        self._port_faces[port_name] = face
        return self

    def _check_face(self, port_name: str, face: str, options: list[str]) -> None:
        """Raise unless ``face`` is one this port can be piped from as drawn.

        The message comes from :mod:`pandid.portgeom`, which raises the same one at
        resolve time: this check only moves the complaint forward to the call
        that caused it.
        """
        if face not in options:
            from pandid.portgeom import unreachable_face

            raise unreachable_face(self, port_name, face, options)

    def _add_port(self, name: str, direction: str, role: str,
                  side: str | None = None) -> Port:
        if name in self.ports:
            raise ValueError(
                f"{type(self).__name__!r} already has a port named {name!r}"
            )
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r} for port {name!r}. Allowed roles are: {_VALID_ROLES}"
            )
        port = Port(name=name, owner=self, direction=direction, role=role, side=side)
        self.ports[name] = port
        setattr(self, name, port)
        return port

    def port(self, name: str) -> Port:
        try:
            return self.ports[name]
        except KeyError:
            raise KeyError(
                f"{type(self).__name__!r} has no port named {name!r}; "
                f"available ports: {sorted(self.ports)}"
            ) from None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    # Defined for the interpreter and hidden from type checkers, which is the
    # only thing ``TYPE_CHECKING`` is false for: mypy reads a class that has a
    # ``__getattr__`` as having whatever attribute it is asked for, so leaving
    # it visible would answer every ``sep.liqid`` with ``Any`` and the
    # annotations above would buy a better hover and nothing else. Under the
    # guard the static answer is the same one this method gives, moved earlier:
    # a nozzle no class declares is an error before the sheet is ever drawn.
    #
    # Nothing moves at runtime. ``TYPE_CHECKING`` is False when Python runs, so
    # the method is defined exactly where and as it always was, and a typo still
    # raises the message below. The cost is the families no annotation can spell
    # (see :class:`Mixer`) and the variant nozzles that are not on the base
    # class (see :class:`Separator`), which a checker now refuses; both are
    # answered by the generated subclasses of the follow-up change.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            # Only invoked when normal lookup fails. Attribute access
            # (reactor.feed) is the primary way to reach ports, so give typos a
            # helpful message listing the real ports instead of a bare
            # AttributeError.
            ports = self.__dict__.get("ports")
            if ports is not None and not name.startswith("_"):
                raise AttributeError(
                    f"{type(self).__name__} {self.__dict__.get('name', '?')!r} has no "
                    f"attribute or port {name!r}; available ports: {sorted(ports)}"
                )
            raise AttributeError(name)


# ---------------------------------------------------------------------------
# Fixed-port unit types
# ---------------------------------------------------------------------------


class _Boundary(Unit):
    """Where the sheet ends: the off-page connector flag Feed and Product draw.

    Not a piece of plant. The flag stands for a line crossing the sheet edge,
    and its label is the whole of what identifies the service to the reader,
    which is why ``reference``, the drawing the line continues onto, is drawn
    here and nowhere else.

    ``header`` says the flag stands for a *utility header* rather than for one
    line: cooling water supply, steam, flare, plant air. A header is a service
    available all over the plant and tapped wherever it is wanted, so it is
    drawn at each tap and labelled the same way every time. See :meth:`repeats`.
    """

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", header: bool = False):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        #: One service tapped at several points, rather than one line crossing
        #: the sheet edge once. Opt in, because two flags accidentally given one
        #: name are two services the reader cannot tell apart, which is a defect
        #: in the drawing and worth catching.
        self.header = bool(header)
        # The drawn label, kept apart from the name because a tapped header
        # needs a name of its own to be addressed by. See :attr:`tag`.
        self._tag = name

    @property
    def tag(self) -> str:
        """The service drawn on the flag (``"CWSH"``).

        Equal to :attr:`~Unit.name` for a flag drawn once. A header repeats:
        the same service appears wherever it is tapped, so the sheet shows one
        label several times while the flowsheet keeps a distinct name for each
        tap to address it by (``CWSH``, ``CWSH (2)``).
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Whether this flag is another tap of the same header.

        Both ends have to be headers carrying the same label: two flags called
        ``Reactor Effluent`` are one line drawn as if it left the sheet twice,
        which is a mistake worth catching, and the author says which case this
        is by passing ``header=True``.

        They also have to be *the same drawing* of it, since the reader has only
        the flag to go on: same class, so a supply and a return sharing a label
        still clash, and the same ``reference``, since two taps of one header
        continue onto one drawing.
        """
        return (self.header
                and isinstance(other, _Boundary)
                and type(other) is type(self)
                and other.header
                and other.tag == self.tag
                and other.variant == self.variant
                and other.reference == self.reference)


class Feed(_Boundary):
    """Boundary condition: a stream source entering the flowsheet.

    ``header=True`` marks the flag as a utility supply header (cooling water,
    steam, plant air), which a sheet taps wherever it needs it and labels the
    same way at every tap. Such a flag may be added more than once; see
    :meth:`_Boundary.repeats`.
    """

    outlet: Port

    kind = "feed"
    PORTS = [("outlet", "outlet", "feed")]


class Product(_Boundary):
    """Boundary condition: a stream sink leaving the flowsheet.

    ``header=True`` marks the flag as a return or collection header (cooling
    water return, condensate, flare), which takes from wherever it is tapped
    and is labelled the same way each time. See :meth:`_Boundary.repeats`.
    """

    inlet: Port

    kind = "product"
    PORTS = [("inlet", "inlet", "product")]


class Pump(Unit):
    """Centrifugal or positive-displacement pump."""

    suction: Port
    discharge: Port

    kind = "pump"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Compressor(Unit):
    """Gas compressor."""

    suction: Port
    discharge: Port

    kind = "compressor"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class _NormallyPositioned(Unit):
    """A unit that carries a ``normal_position``, the base of Valve and Fitting.

    One attribute with one meaning (where the device sits with the plant
    running) and one validated vocabulary, held in one place rather than
    written out twice. A pump has no such position, and neither does a vessel;
    only a device a line can be stopped at does.

    What a *sheet* draws for the position is not shared, because the two
    devices do not share a convention. A closed valve is the open valve with
    its body darkened (PIP PIC001 4.2.2.7). A closed blind is not the open
    blind with anything added: it is the other of the two shapes the drawing
    already had, with the solid disc in the line instead of the bored one. The
    common part is therefore the attribute and its two names; each subclass
    says separately which of its variants may be *shown* closed, by overriding
    :meth:`_refuse_closed`, and :func:`pandid.render.symbols.closed_marking`
    says how each is drawn.
    """

    #: The positions such a unit may be declared in. A drawing convention exists
    #: for exactly one of them; the other is the unmarked default. Held as a
    #: tuple rather than a bool because the position is what the *plant* is in,
    #: and the designations a P&ID draws are an enumeration (NC today, the locked
    #: and car-sealed ones later) rather than a switch with two settings.
    NORMAL_POSITIONS = ("open", "closed")

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", normal_position: str = "open"):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        self._normal_position = "open"
        self.normal_position = normal_position

    @property
    def normal_position(self) -> str:
        """``"open"`` or ``"closed"``: where the device sits when running.

        See the owning class's docstring for what each one draws, and for the
        variants that refuse to be shown closed at all.
        """
        return self._normal_position

    @normal_position.setter
    def normal_position(self, value: str) -> None:
        if value not in self.NORMAL_POSITIONS:
            raise ValueError(
                f"{self.name}: normal_position is "
                f"{' or '.join(repr(p) for p in self.NORMAL_POSITIONS)}, got {value!r}"
            )
        if value == "closed":
            self._refuse_closed()
        self._normal_position = value

    def _refuse_closed(self) -> None:
        """Raise if this unit may not be *shown* normally closed.

        The position is a fact about the plant and every subclass takes it; the
        drawing is where the two differ, and a position nothing on the sheet
        can state is worse than no position at all. Refusing here rather than
        at render time means the sheet is never built.
        """


class Valve(_NormallyPositioned):
    """Control or let-down valve.

    ``actuator`` is the signal connection on top of the valve, the terminus of
    a control loop, so a controller's output lands on the final control element
    rather than in mid-air. Being a signal port, it takes a signal ``kind`` and
    refuses process fluid: a pipe into a valve stem is not a connection.

    ``normal_position`` is where the valve sits with the plant running:
    ``"open"`` (the default) or ``"closed"``. A closed one is drawn with its
    body **darkened solid**, which is the convention of **PIP PIC001 clause
    4.2.2.7**: *"normally closed manual valves shall be shown using a darkened
    solid symbol"*. The rule is one-sided. An open valve is not marked at all,
    so ``"open"`` draws exactly what a valve without the argument draws, and
    the fill is the whole of what ``"closed"`` adds.

    Where the body cannot carry the fill legibly, clause 4.2.2.8 writes the
    abbreviation **NC** instead, directly below the valve on a horizontal run
    and to the right of it on a vertical one. That is the case for a
    butterfly's disc, a check valve's arrow and a knife gate's blade, which all
    live inside the outline and are swallowed by the fill. Those variants draw
    the letters, so the position is always stated somehow.
    :data:`pandid.render.symbols.NC_DARKENS` is the list of variants that
    darken.

    Clause 4.2.2.10, *"control valves or relief valves shall not be shown as
    NC"*, is enforced: a ``control``, ``pneumatic``, ``regulator``, ``relief``
    or ``psv`` valve raises rather than drawing a mark the standard forbids.

    **This is not an ISA-5.1 or ISO 10628 convention.** ISA-5.1 says nothing
    about valve fill and hands manual block valve depiction to the piping
    group. Clauses 2.8.1(b)(1), 2.8.2 and 5.2.5 of ISA-5.1 make it *mandatory*
    to declare on a legend or cover sheet any symbol extending the standard, so
    a sheet that draws a darkened valve owes its reader a legend entry saying
    what the fill means. :func:`pandid.document.legend` builds the box; nothing
    adds the entry for you.

    ``fail`` is a **different question** and is described on :attr:`fail`.
    """

    inlet: Port
    outlet: Port
    actuator: Port

    kind = "valve"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("actuator", "inlet", "signal")]

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", normal_position: str = "open",
                 fail: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference, normal_position=normal_position)
        self._fail = ""
        self.fail = fail

    @property
    def fail(self) -> str:
        """Where the valve goes when its actuating energy is lost, ``""`` unset.

        **This is not** :attr:`~_NormallyPositioned.normal_position`, and the
        two are the easiest pair on a P&ID to run together:

        ===================  ===================================================
        ``normal_position``  where the valve sits **with the plant running**.
                             A fact about the operating case. Marked by
                             darkening the body, or by ``NC`` beside it.
        ``fail``             where the valve goes **when the air, the hydraulic
                             supply or the power is lost**. A fact about the
                             actuator. Marked by letters beside the body.
        ===================  ===================================================

        They are independent, and a valve may state either, both or neither. A
        block valve held open in service and driven shut on a trip is
        ``normal_position="open", fail="closed"``, and both marks are drawn.
        Nothing infers one from the other, because nothing can: the two answer
        different questions and a plant answers them separately.

        Six positions, given as the plant's words and drawn as ISA's letters
        (:data:`pandid.render.symbols.FAIL_POSITIONS`):

        =====================  =========  ==========================================
        ``fail``               drawn      ANSI/ISA-5.1-2009 Table 5.4.4
        =====================  =========  ==========================================
        ``"open"``             ``FO``     fail open
        ``"closed"``           ``FC``     fail closed
        ``"last"``             ``FL``     fail last, holding its position
        ``"drift_open"``       ``FL/DO``  fail last, then drifting open
        ``"drift_closed"``     ``FL/DC``  fail last, then drifting closed
        ``"indeterminate"``    ``FI``     fail indeterminate (ISA-5.1-1984 §6.7)
        =====================  =========  ==========================================

        **Only an actuated valve may declare one.** A hand-operated valve has no
        actuating energy to lose, and a relief valve and a regulator are worked
        by the process itself, so there is no supply whose failure is the
        question. Those raise rather than carrying a statement about equipment
        they do not have; the variants that may are listed in
        :data:`pandid.render.symbols.FAIL_ACTUATED`.

        **Letters, not geometry.** ISA-5.1 Table 5.4.4 offers arrows on the
        actuator stem as well, and ISO encodes the same fact a third way, as the
        apex direction of ISO 15519-2 symbol 654 (A.3.50 fail close ``654V1A``,
        A.3.52 fail open ``654V3A``) drawn on the stem between actuator and
        body. **PIP PIC001 clause 4.5.3.2** is the source that chooses between
        the two ISA methods and it chooses the letters, so this does too. See
        the README's *Standards* section for the whole argument, which a sheet
        cannot be silent about because ISO and ISA draw this one fact
        differently.

        **One position, not two.** A valve can behave one way on loss of signal
        and another on loss of air, and this attribute holds a single answer.
        PIP PIC001 4.5.3.2(3) is the rule for that case: *"valves with different
        fail actions for loss of signal and for loss of motive power require an
        explanatory note."* Declare the motive-power position here and add the
        note; nothing writes it for you.
        """
        return self._fail

    @fail.setter
    def fail(self, value: str) -> None:
        from pandid.render.symbols import FAIL_ACTUATED, FAIL_POSITIONS

        if not value:
            self._fail = ""
            return
        if value not in FAIL_POSITIONS:
            raise ValueError(
                f"{self.name}: fail is one of "
                f"{', '.join(repr(p) for p in FAIL_POSITIONS)}, got {value!r}. "
                f"It is where the valve goes when its actuating energy is lost. "
                f"Where it sits in normal operation is normal_position."
            )
        if self.variant not in FAIL_ACTUATED:
            raise ValueError(
                f"{self.name}: variant {self.variant!r} has no actuator, so it has "
                f"no fail position. ANSI/ISA-5.1 note 5.3.4(10) scopes the failure "
                f"symbols to control valves and actuators: a handwheel loses no air, "
                f"and a regulator or a relief valve is worked by the process itself. "
                f"The variants that take one are: "
                f"{', '.join(sorted(FAIL_ACTUATED))}. If you meant where the valve "
                f"sits with the plant running, that is normal_position."
            )
        self._fail = value

    def _refuse_closed(self) -> None:
        from pandid.render.symbols import NC_FORBIDDEN

        if self.variant in NC_FORBIDDEN:
            raise ValueError(
                f"{self.name}: PIP PIC001 clause 4.2.2.10 says control valves and "
                f"relief valves shall not be shown as NC, and variant "
                f"{self.variant!r} draws one. A darkened control valve on an issued "
                f"sheet reads as a block valve someone has closed. Say where the "
                f"valve fails instead (fail='closed'), or put the normally closed "
                f"mark on the hand valve that actually isolates the line."
            )


class Vessel(Unit):
    """Generic pressure vessel: holdup, not phase separation.

    Variants: ``"default"`` and ``"dished"`` stand upright; ``"horizontal"`` is
    a lying cylinder with dished ends, which is how a reflux drum, accumulator
    or knock-out pot is drawn. Use the variant rather than rotating an upright
    vessel: skirts, saddles and shell bands do not survive a quarter turn, and
    the outlet still has to drain from the bottom whichever way the artwork is
    spun. That is ISO 15519-1 §11.4.2's rule as well, and turning one is
    reported as ``gravity-turned`` by :meth:`~pandid.flowsheet.Flowsheet.validate`.

    Reach for :class:`Separator` instead when the point of the vessel is
    splitting phases and you want to name the vapour and liquid products.
    """

    inlet: Port
    outlet: Port
    vent: Port

    kind = "vessel"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
    ]


class Tank(Unit):
    """Storage tank. Variants: ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``."""

    inlet: Port
    outlet: Port

    kind = "tank"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Blower(Unit):
    """Fan or blower."""

    suction: Port
    discharge: Port

    kind = "blower"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Reducer(Unit):
    """The fitting that changes a line's size: a reducer, or an expander.

    Variants are the body style. ``"concentric"`` is the trapezoid a piping
    drawing draws, symmetric about the run's centreline, and ``"default"`` draws
    it. ``"eccentric"`` is flat along one side, so the small end sits on a
    different centreline from the large one; see ``mirrored`` below for which
    side.

    ``large_end`` says which of the two nozzles is on the wide face, and so
    which way the cone points:

    ======================  ==================================================
    ``large_end``           what the fitting does
    ======================  ==================================================
    ``"inlet"`` (default)   a **reduction**: the run enters wide and leaves
                            narrow, as it does going into a control valve
    ``"outlet"``            an **expansion**: the run enters narrow and leaves
                            wide, as it does coming back out of one
    ======================  ==================================================

    It is one fitting either way: the same casting, piped round the other way,
    which is why this is a property of the unit and not a second variant or a
    second class. What changes is the artwork and which end each nozzle is on;
    the run still goes ``inlet`` to ``outlet``, so a station reads

    .. code-block:: python

        fs.connect(hv.outlet, rd.inlet)      # Reducer("RD-306A")
        fs.connect(rd.outlet, cv.inlet)      # the control valve
        fs.connect(cv.outlet, ex.inlet)      # Reducer("RD-306B", large_end="outlet")

    :meth:`~Unit.pin` cannot say this instead. ``mirrored="x"`` turns the
    drawing *and* its nozzles over together, so the run would enter the east
    face and leave the west one, drawing the line backwards through the fitting,
    which is the thing this argument exists to avoid.

    **Eccentric bodies.** The stencil draws the eccentric reducer **flat on
    top**, which is the pump suction arrangement: a concentric body there leaves
    a pocket against the roof of the line for vapour to collect in and break the
    pump's suction. Flat on the bottom is the same fitting rolled over, for a
    line that has to drain, and it is a placement rather than another symbol:
    ``pin(mirrored="y")`` turns the body top-to-bottom while both nozzles stay
    on the faces the run enters and leaves by.
    """

    inlet: Port
    outlet: Port

    kind = "reducer"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The nozzles the wide face may be on. Not a bool, because the answer names
    #: a port: "the large end is the outlet" is what an expansion is, and a flag
    #: called ``expanding`` would have to be read against the flow to be
    #: understood.
    LARGE_ENDS = ("inlet", "outlet")

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", large_end: str = "inlet"):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        self._large_end = "inlet"
        self.large_end = large_end

    @property
    def large_end(self) -> str:
        """``"inlet"`` for a reduction, ``"outlet"`` for an expansion."""
        return self._large_end

    @large_end.setter
    def large_end(self, value: str) -> None:
        if value not in self.LARGE_ENDS:
            raise ValueError(
                f"{self.name}: large_end names the nozzle on the wide face and is "
                f"{' or '.join(repr(end) for end in self.LARGE_ENDS)}, got {value!r}"
            )
        self._large_end = value


class Tee(Unit):
    """Pipe tee: the junction where a line branches.

    A bypass leg around a control valve, a drain off the underside of a run, a
    vent off the top, a sample point, a PSV takeoff: every one of them is a
    line splitting in two, and this is the fitting that splits it. It is not a
    unit operation: a :class:`Mixer` or a :class:`Splitter` is a piece of plant
    drawn as a triangle and scheduled as one, and using either for a branch puts
    equipment on the sheet that the plant does not contain.

    A tee is drawn as **nothing at all**: three lines meeting, the run passing
    straight through unbroken and the branch leaving it at a right angle. That
    is what the reference sheets draw. P&ID-301's control valve stations put a
    bypass over the top and two drains below every station, and not one of the
    four junctions carries a dot, a circle or a symbol of any kind. So the
    symbol here is the pipe itself and no more, and the run does not kink
    through it: ``inlet`` and ``outlet`` sit on one centreline.

    Nothing at all includes the **arrowhead** a PFD draws at the end of every
    process line. A head says the material arrives somewhere; a tee is a point
    on a line where the line divides, and the run carries straight on past it,
    so a line ending at one is drawn without a head and no filled triangle ever
    lands in the middle of an unbroken run. A line *leaving* a tee is untouched:
    it takes its head at its own destination.

    **It carries no tag.** A tee is a bulk piping item bought by the line and
    specified by the piping class, like the valves and reducers around it, and
    an issued sheet writes nothing against it. The flowsheet still needs a name
    to address one by, so ``name`` defaults to :data:`DEFAULT_NAME` and any two
    tees may share it: :meth:`repeats` says so, and
    :meth:`~pandid.flowsheet.Flowsheet.add` hands out ``TEE (2)``, ``TEE (3)``
    exactly as it does for a repeated interlock square or a tapped utility
    header. Nothing is drawn either way, and nothing reaches the equipment
    list: ``"tee"`` is not in ``pandid.document._MAJOR_EQUIPMENT``.

    ``branch`` says which way the third connection runs: ``"outlet"`` (the
    default) takes flow off the run, which is the takeoff end of a bypass and
    every drain, vent and sample point; ``"inlet"`` returns flow to it, which is
    where a bypass rejoins. The run is always ``inlet`` to ``outlet``.

    The branch leaves the **south** face as drawn, so the side it comes off is
    the tee's placement, stated with :meth:`~Unit.pin`:

    ==================================  =====================================
    ``pin(...)``                        run, branch
    ==================================  =====================================
    (nothing)                           W to E, branch S
    ``mirrored="y"``                    W to E, branch N
    ``orientation=90``                  N to S, branch W
    ``orientation=270``                 S to N, branch E
    ==================================  =====================================

    The run keeps its stream or line number straight through a tee, the way it
    does through a valve or a reducer, and the branch starts a number of its
    own. Set ``new_line_number`` to break the run's number at the junction where the
    piping class changes there.
    """

    inlet: Port
    outlet: Port
    # Added in ``__init__`` rather than declared in ``PORTS``, because which way
    # it runs is the ``branch=`` argument. Every tee has one either way, so the
    # attribute is as fixed as the run's two, and only its direction is not.
    branch: Port

    kind = "tee"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The name a tee answers to when the author gives it none. A tee has no tag
    #: to be told apart by, so every one of them may take this and be renamed
    #: apart by the flowsheet; see :meth:`repeats`.
    DEFAULT_NAME = "TEE"

    #: What the third connection may be. Not a free choice of role: a tee joins
    #: three lengths of the same pipe, so the branch carries process fluid like
    #: the run and differs only in which way it runs.
    BRANCH_DIRECTIONS = ("outlet", "inlet")

    def __init__(self, name: str = "", branch: str = "outlet",
                 variant: str = "default", width: float | None = None,
                 height: float | None = None, description: str = "",
                 reference: str = ""):
        if branch not in self.BRANCH_DIRECTIONS:
            raise ValueError(
                f"{name or self.DEFAULT_NAME}: branch= is "
                f"{' or '.join(repr(d) for d in self.BRANCH_DIRECTIONS)}, whether "
                f"the third connection takes flow off the run or returns it; got "
                f"{branch!r}"
            )
        super().__init__(name or self.DEFAULT_NAME, variant=variant, width=width,
                         height=height, description=description, reference=reference)
        #: ``"outlet"`` for a takeoff, ``"inlet"`` for a return. Read-only after
        #: construction: the port is already built, and turning one direction
        #: into the other would silently disconnect whatever is on it.
        self.branch_direction = branch
        self._add_port("branch", branch, "process")

    @property
    def tag(self) -> str:
        """Nothing. A tee is drawn as bare pipe and labelled nowhere."""
        return ""

    def repeats(self, other: "Unit") -> bool:
        """Whether ``other`` is another tee, and so no clash with this one.

        A tag names one item and two units may not share one, which is why every
        piece of equipment refuses a repeat. A tee has no tag: the sheet writes
        nothing against it, so two tees answering to one name are not two things
        the reader could confuse, because there is nothing drawn to confuse. The name is
        purely how the flowsheet addresses the junction, and
        :meth:`~pandid.flowsheet.Flowsheet.add` keeps it unique.
        """
        return isinstance(other, Tee)


class Fitting(_NormallyPositioned):
    """In-line pipe device: whatever sits in the run and is not a valve.

    One class rather than a dozen, because to the flowsheet a strainer, a sight
    glass and a rupture disc are the same thing, a pair of faces on a line,
    and differ only in what is drawn between them. The variant picks the device:
    ``strainer``, ``strainer_cone``, ``strainer_y``, ``strainer_basket``,
    ``strainer_duplex``, ``orifice``, ``rotameter``,
    ``rupture_disc``, ``sight_glass``, ``sight_glass_lit``, ``silencer``,
    ``expansion_joint``, ``bellows``, ``blind``, ``damper``, ``spool``,
    ``static_mixer``, ``hose``, ``coupling``,
    ``clamped_coupling``, ``flange`` (the default), and the flame arrestors
    (``flame_arrestor`` plus ``_explosion_proof`` / ``_detonation_proof`` /
    ``_fire_resistant``).

    A primary flow element is in the run like anything else here, so it is a
    variant too: ``venturi``, ``flow_nozzle``, ``coriolis``, ``vortex``,
    ``ultrasonic``, ``turbine_meter``, ``positive_displacement``, ``v_cone``,
    ``wedge``, ``target``, ``pitot`` and ``averaging_pitot``. Hang the FE
    balloon on one with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`.

    Like a valve, a fitting is inline: a stream keeps its number through it
    unless ``new_line_number`` is set.

    ``blind`` is the **spectacle blind** (figure-8 blind), and it is the one
    fitting with a ``normal_position``. It is a pair of discs on a common tie,
    one bored through and one solid, bolted between a pair of flanges, and which
    of them is in the line is the whole of what the symbol says. So the line
    passes through the lower disc, and:

    - ``normal_position="open"`` (the default) draws that disc as a **ring**,
      with the solid one parked above it: the line is through.
    - ``normal_position="closed"`` draws it **solid**, with the ring parked
      above: the line is blanked.

    That is a change of *shape*, not a mark added to one: the stencil set draws
    both. A blind is therefore never shown in a position by inference, and the
    two are never one drawing. Any other fitting variant refuses ``"closed"``:
    a strainer has no position, and a position nothing draws is worse than none.
    """

    inlet: Port
    outlet: Port

    kind = "fitting"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    def _refuse_closed(self) -> None:
        from pandid.render.symbols import default_registry

        if default_registry.closed_symbol(self.kind, self.variant) is None:
            drawn = default_registry.closed_variants(self.kind)
            raise ValueError(
                f"{self.name}: variant {self.variant!r} is drawn one way, so it has "
                f"no normally closed position to state; the fittings drawn in two "
                f"positions are: {', '.join(drawn)}. Use a valve if what closes the "
                f"line is a valve."
            )


class Ejector(Unit):
    """Steam/gas ejector or eductor.

    A motive stream entrains a second one, so this is three connections, not
    two: ``motive`` drives the nozzle, ``suction`` is what gets entrained, and
    ``discharge`` leaves the diffuser.
    """

    motive: Port
    suction: Port
    discharge: Port

    kind = "ejector"
    PORTS = [("motive", "inlet", "utility"), ("suction", "inlet", "process"),
             ("discharge", "outlet", "process")]


class Vent(Unit):
    """Open end to atmosphere (vent stack with a weather cap).

    A boundary like :class:`Product`, but drawn as real piping rather than an
    off-page flag, which is what a PSV tailpipe or a tank breather wants.

    Variants: ``"default"`` (a stack with a weather cap), ``"exhaust_head"``
    (the silencing hood on a steam or relief vent) and ``"breather"`` (the tank
    conservation vent). All three carry the one connection, piped from below.
    """

    inlet: Port

    kind = "vent"
    PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel: a manual addition point feeding the line.

    The mirror of :class:`Vent`: the cone is open to the room and the stem is
    the process connection, so its single port is an *outlet*.
    """

    outlet: Port

    kind = "funnel"
    PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater / furnace (process stream heated by burning fuel)."""

    inlet: Port
    outlet: Port
    fuel: Port

    kind = "furnace"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("fuel", "inlet", "feed")]


class Turbine(Unit):
    """Steam/gas turbine or expander."""

    inlet: Port
    outlet: Port

    kind = "turbine"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Filter(Unit):
    """Filter (liquid or gas)."""

    inlet: Port
    outlet: Port

    kind = "filter"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Dryer(Unit):
    """Dryer (removes moisture from a feed solid/slurry)."""

    feed: Port
    product: Port

    kind = "dryer"
    PORTS = [("feed", "inlet", "feed"), ("product", "outlet", "process")]


class Conveyor(Unit):
    """Belt conveyor: bulk solids carried from the tail end to the head end.

    ``length`` is the belt run: the symbol is a straight bar between two rollers
    of fixed size, so a longer conveyor grows the bar and the rollers stay
    round. It is the unit's whole size, and its only one. ``width`` and
    ``height`` set the drawn box, which would stretch the rollers with it, so
    they are refused rather than left as a second answer to the same question.
    A quarter turn stands the belt on end, where the length is its height.

    ``feed`` is the tail end. Material is dropped onto a belt rather than piped
    into it, so the nozzle can be taken from the top face as well as the end.
    ``discharge`` is the head end, where the belt throws off; it can be taken
    from the underside too, for the chute that catches what comes over.
    """

    feed: Port
    discharge: Port

    kind = "conveyor"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]

    _length: float

    def __init__(self, name: str, length: float | None = None,
                 variant: str = "default", width: float | None = None,
                 height: float | None = None, label_pos: str | None = None,
                 description: str = "", reference: str = ""):
        from pandid.render.symbols import CONVEYOR_LENGTH

        if width is not None or height is not None:
            given = width if width is not None else height
            raise ValueError(
                f"{name}: a Conveyor is sized by length=, the belt run between "
                f"its two rollers, and that one number is the only authority on "
                f"how long the belt is. width= and height= size the drawn box "
                f"instead, which would stretch the rollers out of round. Pass "
                f"length={given!r}."
            )
        super().__init__(name, variant=variant, label_pos=label_pos,
                         description=description, reference=reference)
        self.length = CONVEYOR_LENGTH if length is None else length

    @property
    def length(self) -> float:
        """The belt run, tail roller to head roller, in drawn units.

        The symbol is built to it rather than scaled to it, so the box the
        conveyor is placed in is exactly the box its artwork was drawn in and
        the rollers are the same circles however long the belt is.
        """
        return self._length

    @length.setter
    def length(self, value: float) -> None:
        from pandid.render.symbols import CONVEYOR_MIN_LENGTH, conveyor_too_short

        if value < CONVEYOR_MIN_LENGTH:
            raise conveyor_too_short(value, self.name)
        self._length = float(value)


def split_tag(type: str, number: str | int = "") -> tuple[str, str]:
    """Split an instrument tag into its functional letters and its loop number.

    ``("FT", 101)`` and ``"FT-101"`` and ``"FT101"`` all give ``("FT", "101")``.
    """
    if number != "" and number is not None:
        return type.strip(), str(number).strip()
    tag = type.strip()
    if "-" in tag:
        letters, num = tag.split("-", 1)
        return letters, num
    i = 0
    while i < len(tag) and not tag[i].isdigit():
        i += 1
    return tag[:i], tag[i:]


class Instrument(Unit):
    """ISA-5.1 instrument balloon.

    ``type`` is the functional letter string (``"FT"``, ``"PAH"``, ``"LIC"``)
    and ``number`` the loop number; the balloon draws the letters over the
    number, and the number is drawn **bare**, because a real sheet does not
    repeat the letters inside the bubble. ``name`` is the full tag (``"FT-101"``), which is
    what equipment lists and cross-references want. A single combined argument
    (``Instrument("FT-101")``) is still accepted and split.

    ``pv`` taps the process; ``sig_in``/``sig_out`` carry signals. All three are
    signal connections and take a signal ``kind``: an impulse line to a
    transmitter is an instrument connection, not a process pipe. Variants:
    ``"default"`` (field balloon), ``"panel"``, ``"aux"``, ``"shared"``
    (a circle in a square: shared display and shared control, which ISA-5.1 no
    longer reads as "DCS"),
    ``"computer"``, ``"sis"`` (a diamond in a square: ANSI/ISA-5.1-2009
    Table 5.1.1 column B, the safety-instrumented-system symbol an issued sheet
    draws a trip with, also spelled ``"logic"``) and ``"interlock"`` (a plain
    diamond: Table 5.1.2 items 3-5, the generic interlock logic function).

    A balloon that measures something belongs *on* what it measures: see
    :meth:`attach` (and :meth:`pandid.flowsheet.Flowsheet.add_instrument`).
    """

    pv: Port
    sig_in: Port
    sig_out: Port

    kind = "instrument"
    PORTS = [("pv", "inlet", "signal"), ("sig_in", "inlet", "signal"),
             ("sig_out", "outlet", "signal")]

    #: The variants that stand for a function rather than a device. A balloon is
    #: a thing (a transmitter in the field, a faceplate in the control room)
    #: and there is one of it. A trip square is a *logic function*, which acts in
    #: several places at once and is therefore drawn in each of them, carrying
    #: the same tag every time. ``"sis"`` and ``"logic"`` are two names for one
    #: symbol, so a repeat spelled either way is the same function.
    _REPEATABLE_VARIANTS = frozenset({"sis", "logic", "interlock"})

    def __init__(self, type: str, number: str | int = "", variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "", reference: str = ""):
        letters, num = split_tag(type, number)
        name = f"{type}-{number}" if number != "" and number is not None else type
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description, reference=reference)
        self.type = letters
        self.number = num
        # The drawn tag, kept apart from the name because a repeated square
        # needs a name of its own to be addressed by. See :attr:`tag`.
        self._tag = name
        # Attachment intent (set only via attach()); the layout engine resolves
        # it into a frame, exactly as Pin -> Frame for ordinary equipment.
        self.host: "Stream | Unit | None" = None
        self.at: float | str | None = None
        self.offset: float = 45.0
        self.angle: float = 90.0
        self.tap: tuple[float, float] | None = None   # resolved (set only by layout)

    @property
    def tag(self) -> str:
        """The ISA tag drawn in the balloon or square (``"I-1"``).

        Equal to :attr:`~Unit.name` for everything drawn once. An interlock
        square repeats: the same logic function appears wherever it acts, so
        the sheet shows one tag several times while the flowsheet keeps a
        distinct name for each square to address it by (``I-1``, ``I-1 (2)``).
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Whether this square is another drawing of the same logic function.

        Both ends have to be trip squares carrying the same tag: an ``LT-101``
        drawn twice is two transmitters on one loop number, and a square sharing
        its tag with a balloon is two different symbols claiming to be the same
        thing. They also have to be the *same* square: a plain interlock
        diamond and a diamond-in-square are two different ISA-5.1 symbols, so
        one of each on a tag is still a clash. The exception is that ``"sis"``
        and ``"logic"`` name one symbol and so count as the same.
        """
        def symbol(variant: object) -> object:
            return "sis" if variant == "logic" else variant

        return (isinstance(other, Instrument)
                and other.tag == self.tag
                and self.variant in self._REPEATABLE_VARIANTS
                and symbol(self.variant) == symbol(other.variant))

    def attach(self, on: "Stream | Unit", *, at: float | str | None = None,
               offset: float = 45.0, angle: float = 90.0) -> "Instrument":
        """Anchor this balloon to a process line or to a piece of equipment.

        ``on`` is the host: a :class:`~pandid.streams.Stream` (tap a line) or a
        :class:`Unit` (mount on equipment). ``at`` locates the tap: a fraction
        ``0..1`` along the host stream's routed path, or a face (``"N"``,
        ``"S"``, ``"E"``, ``"W"``) of a host unit's drawn box.

        ``offset`` is the distance from the tap to the balloon centre;
        ``offset=0`` leaves the element sitting *on* the line, which is how an
        in-line primary element (an orifice plate FE) is drawn.

        ``angle`` is the direction the balloon branches off, in degrees from the
        flow direction at the tap, counter-clockwise positive, so the default
        ``90`` is "perpendicular, upstream side up" and a tap keeps its
        orientation if the line is later re-routed. On a unit host the reference
        direction is the face's tangent, so ``90`` again points straight out.

        An attached balloon takes no part in the layout ranking: it is placed
        from its host, not from the process flow order.
        """
        from pandid.streams import Stream

        if not isinstance(on, (Stream, Unit)):
            raise TypeError(
                f"{self.name}: attach(on=...) takes a Stream or a Unit, got {type(on).__name__}"
            )
        if isinstance(on, Unit) and on is self:
            raise ValueError(f"{self.name} cannot be attached to itself")
        if isinstance(on, Stream):
            if at is None:
                at = 0.5
            if isinstance(at, str):
                raise ValueError(
                    f"{self.name}: at= on a stream is a fraction 0..1 along its "
                    f"routed path, got {at!r}"
                )
            if not 0.0 <= float(at) <= 1.0:
                raise ValueError(f"{self.name}: at= must be within 0..1, got {at!r}")
            at = float(at)
        else:
            if at is None:
                at = "E"
            if not isinstance(at, str) or at.upper() not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.name}: at= on a unit host is a face 'N'/'S'/'E'/'W', got {at!r}"
                )
            at = at.upper()
        if offset < 0:
            raise ValueError(f"{self.name}: offset= must not be negative, got {offset!r}")
        self.host = on
        self.at = at
        self.offset = float(offset)
        self.angle = float(angle)
        return self


def _side_ports(*sides: str) -> list[tuple[str, str, str]]:
    """One inlet and one outlet on each of an exchanger's two sides."""
    return [
        (f"{side}_{end}", direction, "process")
        for side in sides
        for end, direction in (("in", "inlet"), ("out", "outlet"))
    ]


class HeatExchanger(Unit):
    """Heat exchanger, with a nozzle pair on each of its two sides.

    Nozzles are named for the **side of the equipment** they sit on, never for
    the duty the stream carries. Which fluid runs in the shell and which in the
    tubes is a design decision an engineer makes deliberately: fouling service
    goes tube side because tubes can be cleaned, condensing vapour goes shell
    side. That is a fact about the exchanger, so the drawing records it.
    Which side is the hot one inverts between operating cases while the nozzle
    stays where it is.

    Most variants are a shell and a tube side. The ones that are neither say so:
    ``air_cooled`` is a tube bundle with air across it, ``plate`` and ``spiral``
    have two interchangeable channel sets and letter them, and ``thin_film`` is
    an evaporator with a jacket and a product side.

    The ``kettle`` variant carries one nozzle more: ``bottoms``, the liquid draw
    at the weir end of the shell. A kettle reboiler is where a tower's bottoms
    product physically leaves: what does not boil overflows the weir. The draw
    therefore belongs on the exchanger and not on an invented splitter in the
    sump line.
    """

    # The shell-and-tube nozzles, and only those: they are what an exchanger
    # asked for by name has, since ``_VARIANT_PORTS`` below defaults to
    # ``_SHELL_AND_TUBE``. The other variants' nozzles (``bottoms`` on a kettle,
    # ``side_a_in`` on a plate, ``air_in`` on an air cooler) are deliberately
    # absent. Declaring them here would say that *every* HeatExchanger has a
    # ``bottoms``, which is false for all but one variant and would make a real
    # mistake type-check clean. They belong on a per-variant subclass, which is
    # the follow-up change this annotation layer is the foundation for; until
    # then a variant nozzle is reached by ``hx.port("bottoms")``.
    shell_in: Port
    shell_out: Port
    tube_in: Port
    tube_out: Port

    kind = "hex"
    # Empty because which nozzles an exchanger has depends on its variant, and
    # Unit.__init__ reads PORTS before a variant is in hand. _VARIANT_PORTS
    # below is the declaration, and __init__ lays it down.
    PORTS: list[tuple[str, str, str]] = []
    # The shell-and-tube family, which is what most of the variants are.
    _SHELL_AND_TUBE = _side_ports("shell", "tube")
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_SHELL_AND_TUBE`. A variant that is not a shell and tubes names
    #: its own two sides rather than borrowing a vocabulary it has no parts for,
    #: and only the kettle has a weir to draw off, so giving every exchanger a
    #: ``bottoms`` would hand most of them a port the symbol cannot place.
    _VARIANT_PORTS = {
        "kettle": [*_SHELL_AND_TUBE, ("bottoms", "outlet", "liquid")],
        "air_cooled": _side_ports("tube", "air"),
        "plate": _side_ports("side_a", "side_b"),
        "spiral": _side_ports("side_a", "side_b"),
        "thin_film": _side_ports("jacket", "product"),
    }

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        for spec in self._VARIANT_PORTS.get(variant, self._SHELL_AND_TUBE):
            self._add_port(*spec)


class Heater(Unit):
    """Single-stream heater (utility heating).

    ``utility_in`` is the heating medium's connection: named for what lands on
    it, on the same principle as :class:`HeatExchanger`'s nozzles.
    """

    inlet: Port
    outlet: Port
    utility_in: Port

    kind = "heater"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_in", "inlet", "energy"),
    ]


class Cooler(Unit):
    """Single-stream cooler (utility cooling).

    ``utility_out`` is the cooling medium's connection, the counterpart of
    :class:`Heater`'s ``utility_in``.
    """

    inlet: Port
    outlet: Port
    utility_out: Port

    kind = "cooler"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_out", "outlet", "energy"),
    ]


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Names for a unit's feed nozzles: ``feed`` alone, else ``feed_1`` ... ``feed_n``.

    One feed is the overwhelmingly common case and keeps the singular name, so a
    second one is what changes the spelling rather than every sheet ever drawn.
    The symbol declares the same rule as a
    :class:`~pandid.render.symbols.PortSeries`, which is what spreads the family
    down the shell.
    """
    if n_feeds < 1:
        raise ValueError(f"{owner} requires at least 1 feed, got {n_feeds}")
    return ["feed"] if n_feeds == 1 else [f"feed_{i}" for i in range(1, n_feeds + 1)]


class Reactor(Unit):
    """Generic reactor (CSTR, PFR, etc.).

    ``vent`` is the off-gas connection at the top of the vessel. ``n_feeds``
    gives the vessel more than one charge nozzle: ``feed_1`` ... ``feed_n``,
    spread down the shell top to bottom, in place of the single ``feed``.
    """

    outlet: Port
    vent: Port
    duty: Port
    # The single-feed vessel's charge nozzle. ``n_feeds > 1`` spells it
    # ``feed_1`` ... ``feed_n`` instead, a family whose size is the caller's, so
    # there is no finite set of names to declare and no annotation that could
    # stand for them; see :class:`Mixer`. ``feed`` itself is not one of that
    # family, it is what a reactor asked for by name has, so it is declared like
    # any other fixed nozzle.
    feed: Port

    kind = "reactor"
    PORTS = [
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("duty", "inlet", "energy"),
    ]

    def __init__(self, name: str, n_feeds: int = 1, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        names = _feed_names(n_feeds, "Reactor")
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        for feed in names:
            self._add_port(feed, "inlet", "feed")


class Separator(Unit):
    """Flash drum or phase separator.

    Variants: ``"default"`` is the plain dished-head vertical cylinder, the same
    shell :class:`Vessel` and :class:`Column` are drawn from, because a
    separator *is* a vessel whose vapour and liquid products are worth naming.
    ``"horizontal"`` is a lying cylinder with dished ends, and shares its
    stencil with ``Vessel(variant="horizontal")`` for the same reason. Use it
    rather than turning the upright one, exactly as a vessel does.

    ``"knockout"`` adds two internals to the upright drum: a demister pad and a
    level gauge, both drawn into the equipment artwork. Ask for it when the mesh
    pad is a fact about the equipment worth putting on the sheet, and note that
    the gauge is *drawn*, not declared, so a level instrument added with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument` puts its own ISA-5.1
    balloon beside it rather than replacing it, and the sheet says the level is
    measured twice.

    ``"cyclone"``, ``"gravity"``, ``"scrubber"`` and ``"electrostatic"`` are the
    separating bodies that are not drums at all, each with its own hopper or
    vortex.

    ``"sifter"``, ``"impact"``, ``"permanent_magnet"`` and ``"electromagnetic"``
    are the **mechanical** separators, which sort by size, inertia or magnetism
    rather than into phases. Their products are neither a vapour nor a liquid, so
    they do not borrow those names: the draws are ``overflow``, high on the body,
    and ``underflow``, out of the apex. The pair names the two *positions* the
    artwork draws, on the same principle as :class:`HeatExchanger`'s nozzles, and
    it is the ordinary vocabulary of classification and solid-liquid separation.
    Neither name says which of the two is the product, because that is a fact
    about the service and not about the machine: a cyclone on a spray dryer
    recovers its product from the underflow, and the identical cyclone on a vent
    line throws that same catch away.

    Every variant is drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: vapour disengages
    off the top and liquid draws off the bottom, which is ISO 15519-1 §11.4.2's
    exception for symbols where gravity is a functionality.
    """

    # The phase draws, and only those: ``_VARIANT_PORTS`` below defaults to
    # ``_PHASES``, so they are what a separator asked for by name has.
    # ``overflow`` and ``underflow`` are deliberately absent. Four of the
    # variants have them *instead of* ``vapor`` and ``liquid``, never as well
    # as, so declaring all four here would tell a checker that a plain flash
    # drum has an ``overflow``, which is exactly the mistake the mechanical
    # separators exist to keep out of the vocabulary. They belong on a
    # per-variant subclass, which is the follow-up change this annotation layer
    # is the foundation for; until then a mechanical separator's draws are
    # reached by ``sep.port("overflow")``.
    feed: Port
    vapor: Port
    liquid: Port

    kind = "separator"
    # Empty because which nozzles a separator has depends on its variant, and
    # Unit.__init__ reads PORTS before a variant is in hand. _VARIANT_PORTS
    # below is the declaration and __init__ lays it down, exactly as
    # HeatExchanger does and for the same reason.
    PORTS: list[tuple[str, str, str]] = []
    # The flash drum, and the default: a vessel whose vapour and liquid
    # products are worth naming. Every variant 0.1.0 could draw takes this set,
    # unchanged in name, order, direction and role.
    _PHASES = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]
    # The mechanical separators. All four stencils are one body, anchor for
    # anchor: a box with a hopper under it, the feed high on one wall (0, 12),
    # one draw high on the opposite wall (80, 12) and one out of the apex
    # (40, 120). A high draw and a low draw is the whole of what is true of all
    # of them, so naming the two positions is the most the drawing supports --
    # and it is what classification and solid-liquid separation call them
    # anyway, on a hydrocyclone, a thickener or a classifier.
    #
    # ``process`` rather than ``vapor``/``liquid`` on both draws, because what
    # leaves is dry dust from a precipitator, tramp metal from a magnet, or a
    # screened size fraction, and the role vocabulary has no word that covers
    # those. Saying ``liquid`` of a hopper full of dust is the bend this set
    # exists to stop.
    _OVER_AND_UNDER = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_PHASES`.
    #:
    #: ``scrubber`` and ``venturi_scrubber`` are absent deliberately. A wet
    #: scrubber's draws really are a cleaned gas and a dirty scrubbing liquid,
    #: which is what :data:`_PHASES` already says; a scrubber cleans a gas
    #: rather than classifying a solid, so it is not one of these.
    #:
    #: ``cyclone``, ``gravity`` and ``electrostatic`` are absent for a worse
    #: reason. A settling chamber and a precipitator collect *dust*, and so does
    #: a cyclone in the gas-solid service ISO 15519-1 draws it for; all three
    #: call that catch ``liquid``, which is the bend this mechanism exists to
    #: stop. They are left alone because 0.1.0 shipped those names and every
    #: sheet drawn against them would break. Correcting them is a deliberate,
    #: announced break and belongs in its own change, not smuggled in under a
    #: new mechanism.
    _VARIANT_PORTS = {
        "sifter": _OVER_AND_UNDER,
        "impact": _OVER_AND_UNDER,
        "permanent_magnet": _OVER_AND_UNDER,
        "electromagnetic": _OVER_AND_UNDER,
    }

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        for spec in self._VARIANT_PORTS.get(variant, self._PHASES):
            self._add_port(*spec)


class Column(Unit):
    """Distillation or absorption column.

    Besides the feed and the two products, a real column has two *return*
    nozzles that close its internal loops: ``reflux_in`` (liquid back to the top
    from the reflux drum) and ``boilup_in`` (vapour back to the bottom from the
    reboiler). Without them a reflux loop has to be modelled as a recycle to
    some upstream unit, which drags the overhead system across the sheet.

    ``n_feeds`` gives the tower more than one feed nozzle: an extractive
    distillation takes its solvent above the feed tray, an azeotropic tower its
    entrainer. They are ``feed_1`` ... ``feed_n``, spread down the shell in
    declaration order, so ``feed_1`` is the highest and ``feed_n`` the lowest;
    the single-feed column keeps the plain ``feed``.
    """

    distillate: Port
    bottoms: Port
    reflux_in: Port
    boilup_in: Port
    reboiler_duty: Port
    condenser_duty: Port
    # The single-feed tower's nozzle; ``n_feeds > 1`` replaces it with the
    # ``feed_1`` ... ``feed_n`` family, which cannot be declared. See
    # :class:`Reactor`, which spells the same rule, and :class:`Mixer`.
    feed: Port

    kind = "column"
    PORTS = [
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reflux_in", "inlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]

    def __init__(self, name: str, n_feeds: int = 1, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        names = _feed_names(n_feeds, "Column")
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        for feed in names:
            self._add_port(feed, "inlet", "feed")


# ---------------------------------------------------------------------------
# Variable-port unit types
# ---------------------------------------------------------------------------


class Mixer(Unit):
    """Combines multiple inlet streams into one outlet.

    A piece of plant, drawn as a triangle and scheduled as one. Where two lines
    simply meet in the piping, the fitting is a :class:`Tee`.
    """

    # The one nozzle every mixer has. The inlets are ``in_1`` ... ``in_n`` and
    # ``n`` is the caller's, chosen per instance at construction, so the set of
    # attribute names is a property of the *object* and not of the class. A
    # class annotation is a statement about every instance, and there is no
    # finite list here to make one from: declaring ``in_1: Port`` and
    # ``in_2: Port`` would be right for the default and wrong for
    # ``Mixer("M", n_inlets=5)`` in one direction and for ``n_inlets=1`` in the
    # other. Not even a generated subclass fixes it, because the count is not
    # in the type; the numbered nozzles stay reachable by ``mixer.port("in_3")``
    # and through the ``ports`` dict. ``tests/test_port_annotations.py`` exempts
    # exactly this family, and names it.
    outlet: Port

    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        for i in range(1, n_inlets + 1):
            self._add_port(f"in_{i}", "inlet", "process")
        self._add_port("outlet", "outlet", "process")


class Splitter(Unit):
    """Divides one inlet stream into multiple outlets.

    A piece of plant, drawn as a triangle and scheduled as one. A bypass leg, a
    drain, a vent or a sample point is not that: it is a line branching, and
    the fitting that branches it is a :class:`Tee`.
    """

    # The one nozzle every splitter has; ``out_1`` ... ``out_n`` are the
    # caller's count and cannot be declared, for the reason :class:`Mixer`
    # gives at length.
    inlet: Port

    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        self._add_port("inlet", "inlet", "process")
        for i in range(1, n_outlets + 1):
            self._add_port(f"out_{i}", "outlet", "process")
