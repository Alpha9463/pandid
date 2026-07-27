"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``).

This module is also the public ``units`` namespace: ``from pandid import units``.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from pandid.geometry import Frame, Pin
from pandid.ports import Port

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

__all__ = [
    "Unit",
    "Feed", "Product", "Pump", "Compressor", "Blower", "Valve", "Vessel", "Tank",
    "HeatExchanger", "Heater", "Cooler", "Reactor", "Separator", "Column",
    "Mixer", "Splitter", "Reducer", "Fitting", "Ejector", "Vent", "Funnel",
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

class Unit:
    #: The equipment type this unit is drawn as: the key the symbol registry is
    #: looked up by, and the tag a spec's ``kind:`` names. One per class.
    kind: str = "unit"
    #: The unit's nozzles, one ``(name, direction, role)`` tuple each — the name
    #: a stream is connected by, ``"inlet"`` or ``"outlet"``, and one of
    #: :data:`_VALID_ROLES`. Read once when the unit is constructed, so the
    #: nearest declaration in the class hierarchy is the whole list. A unit
    #: whose nozzle count the caller decides adds its ports in ``__init__``
    #: instead, as :class:`Mixer` does.
    PORTS: list[tuple[str, str, str]] = []
    #: The name :attr:`PORTS` had while it was private. Still read, so a unit
    #: written against it keeps its nozzles, and deprecated: the one attribute a
    #: subclass has to set cannot be the one its name says not to touch.
    _PORTS: list[tuple[str, str, str]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "_PORTS" in cls.__dict__:
            warnings.warn(
                f"{cls.__name__} declares its ports as _PORTS, the private name the "
                f"attribute used to have; it is now PORTS. _PORTS is still read, so "
                f"the class keeps its nozzles either way.",
                DeprecationWarning, stacklevel=2,
            )

    @classmethod
    def _declared_ports(cls) -> list[tuple[str, str, str]]:
        """The ports this class declares, under whichever spelling it uses.

        The nearest class in the MRO to name either one answers for the whole
        list, empty or not, exactly as an attribute lookup would: overriding a
        declaration replaces it. A class naming both is taken at its public word.
        """
        for klass in cls.__mro__:
            for attr in ("PORTS", "_PORTS"):
                if attr in klass.__dict__:
                    return list(klass.__dict__[attr])
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
        self._significant = False
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
        that stand for one thing shown in several places: the interlock square
        (:meth:`Instrument.repeats`) and the utility header flag
        (:meth:`_Boundary.repeats`).
        """
        return False

    @property
    def significant(self) -> bool:
        """For inline fittings (valve/reducer/fitting): if True, the stream
        number — or the line number, where the line has one — breaks across this
        unit instead of carrying through it, which is where a spec break goes.

        Setting it renumbers the flowsheet, so the names on the stream objects
        the caller already holds stay the names that get drawn.
        """
        return self._significant

    @significant.setter
    def significant(self, value: bool) -> None:
        self._significant = value
        if self.flowsheet is not None:
            self.flowsheet.renumber_streams()

    def pin(
        self,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = _UNCHANGED,
        mirrored: bool | str = _UNCHANGED,
    ) -> "Unit":
        """Pin the unit to a specific layout grid cell or exact pixel coordinate.

        Records *intent* only. The layout engine reads it and resolves the final
        :class:`~pandid.geometry.Frame`; pinned axes are honored exactly.

        ``orientation`` is a clockwise quarter turn in degrees (0/90/180/270); a
        quarter turn swaps the unit's width and height. ``mirrored`` flips the
        symbol: ``True`` or ``"x"`` left↔right (swapping its E and W faces),
        ``"y"`` top↔bottom (swapping N and S), ``"xy"`` both.

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

    def nozzle(self, port_name: str, face: str) -> "Unit":
        """Pipe a port from a named face of the unit *as drawn*.

        Many vessels can be piped from more than one side, and the layout engine
        already picks between them from where the peer landed (see
        :mod:`pandid.layout.faces`); this overrides that pick, which is how a
        drawing convention gets stated. ``face`` is the compass point on the
        finished sheet — ``"N"``/``"S"``/``"E"``/``"W"``, or the
        ``top``/``bottom``/``left``/``right`` spelling ``label_pos`` uses — so a
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

    def port_face(self, port_name: str, face: str) -> "Unit":
        """Deprecated alias for :meth:`nozzle`.

        Its ``face`` was documented as the symbol's own frame; :meth:`nozzle`
        reads it as the drawn one, which is the same thing on an untransformed
        unit and the right thing on a mirrored one.
        """
        warnings.warn(
            "Unit.port_face() is deprecated; use Unit.nozzle(port, face), whose "
            "face is the compass point as drawn.",
            DeprecationWarning, stacklevel=2,
        )
        return self.nozzle(port_name, face)

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

    def __getattr__(self, name: str):
        # Only invoked when normal lookup fails. Attribute access (reactor.feed)
        # is the primary way to reach ports, so give typos a helpful message
        # listing the real ports instead of a bare AttributeError.
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
    which is why ``reference`` — the drawing the line continues onto — is drawn
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

        Equal to :attr:`~Unit.name` for a flag drawn once. A header repeats —
        the same service appears wherever it is tapped — so the sheet shows one
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
        the flag to go on — same class, so a supply and a return sharing a label
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

    ``header=True`` marks the flag as a utility supply header — cooling water,
    steam, plant air — which a sheet taps wherever it needs it and labels the
    same way at every tap. Such a flag may be added more than once; see
    :meth:`_Boundary.repeats`.
    """

    kind = "feed"
    PORTS = [("outlet", "outlet", "feed")]


class Product(_Boundary):
    """Boundary condition: a stream sink leaving the flowsheet.

    ``header=True`` marks the flag as a return or collection header — cooling
    water return, condensate, flare — which takes from wherever it is tapped
    and is labelled the same way each time. See :meth:`_Boundary.repeats`.
    """

    kind = "product"
    PORTS = [("inlet", "inlet", "product")]


class Pump(Unit):
    """Centrifugal or positive-displacement pump."""

    kind = "pump"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Compressor(Unit):
    """Gas compressor."""

    kind = "compressor"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class _NormallyPositioned(Unit):
    """A unit that carries a ``normal_position``, the base of Valve and Fitting.

    One attribute with one meaning — where the device sits with the plant
    running — and one validated vocabulary, held in one place rather than
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
    """

    kind = "valve"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("actuator", "inlet", "signal")]

    def _refuse_closed(self) -> None:
        from pandid.render.symbols import NC_FORBIDDEN

        if self.variant in NC_FORBIDDEN:
            raise ValueError(
                f"{self.name}: PIP PIC001 clause 4.2.2.10 says control valves and "
                f"relief valves shall not be shown as NC, and variant "
                f"{self.variant!r} draws one. A darkened control valve on an issued "
                f"sheet reads as a block valve someone has closed. Say where the "
                f"valve fails instead (the actuator's fail action), or put the "
                f"normally closed mark on the hand valve that actually isolates "
                f"the line."
            )


class Vessel(Unit):
    """Generic pressure vessel — holdup, not phase separation.

    Variants: ``"default"`` and ``"dished"`` stand upright; ``"horizontal"`` is
    a lying cylinder with dished ends, which is how a reflux drum, accumulator
    or knock-out pot is drawn. Use the variant rather than rotating an upright
    vessel: skirts, saddles and shell bands do not survive a quarter turn, and
    the outlet still has to drain from the bottom whichever way the artwork is
    spun.

    Reach for :class:`Separator` instead when the point of the vessel is
    splitting phases and you want to name the vapour and liquid products.
    """

    kind = "vessel"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
    ]


class Tank(Unit):
    """Storage tank. Variants: ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``."""

    kind = "tank"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Blower(Unit):
    """Fan or blower."""

    kind = "blower"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Reducer(Unit):
    """Pipe reducer/expander.

    Variants: ``"default"`` (a cone tapering to a point), ``"concentric"`` (the
    trapezoid a piping drawing draws) and ``"eccentric"``, flat on top so its
    small end sits on a lower centreline than its large end. The eccentric body
    is what goes on a pump suction, where a concentric one would trap vapour
    against the roof of the line; its ``outlet`` is on that lowered centreline
    rather than at mid-height.
    """

    kind = "reducer"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Fitting(_NormallyPositioned):
    """In-line pipe device: whatever sits in the run and is not a valve.

    One class rather than a dozen, because to the flowsheet a strainer, a sight
    glass and a rupture disc are the same thing — a pair of faces on a line —
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
    unless ``significant`` is set.

    ``blind`` is the **spectacle blind** (figure-8 blind), and it is the one
    fitting with a ``normal_position``. It is a pair of discs on a common tie —
    one bored through, one solid — bolted between a pair of flanges, and which
    of them is in the line is the whole of what the symbol says. So the line
    passes through the lower disc, and:

    - ``normal_position="open"`` (the default) draws that disc as a **ring**,
      with the solid one parked above it: the line is through.
    - ``normal_position="closed"`` draws it **solid**, with the ring parked
      above: the line is blanked.

    That is a change of *shape*, not a mark added to one — the stencil set
    draws both — so a blind is never shown in a position by inference and the
    two are never one drawing. Any other fitting variant refuses ``"closed"``:
    a strainer has no position, and a position nothing draws is worse than none.
    """

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

    kind = "ejector"
    PORTS = [("motive", "inlet", "utility"), ("suction", "inlet", "process"),
             ("discharge", "outlet", "process")]


class Vent(Unit):
    """Open end to atmosphere (vent stack with a weather cap).

    A boundary like :class:`Product`, but drawn as real piping rather than an
    off-page flag — which is what a PSV tailpipe or a tank breather wants.

    Variants: ``"default"`` (a stack with a weather cap), ``"exhaust_head"``
    (the silencing hood on a steam or relief vent) and ``"breather"`` (the tank
    conservation vent). All three carry the one connection, piped from below.
    """

    kind = "vent"
    PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel — a manual addition point feeding the line.

    The mirror of :class:`Vent`: the cone is open to the room and the stem is
    the process connection, so its single port is an *outlet*.
    """

    kind = "funnel"
    PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater / furnace (process stream heated by burning fuel)."""

    kind = "furnace"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("fuel", "inlet", "feed")]


class Turbine(Unit):
    """Steam/gas turbine or expander."""

    kind = "turbine"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Filter(Unit):
    """Filter (liquid or gas)."""

    kind = "filter"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Dryer(Unit):
    """Dryer (removes moisture from a feed solid/slurry)."""

    kind = "dryer"
    PORTS = [("feed", "inlet", "feed"), ("product", "outlet", "process")]


class Conveyor(Unit):
    """Belt conveyor — bulk solids carried from the tail end to the head end.

    ``length`` is the belt run: the symbol is a straight bar between two rollers
    of fixed size, so a longer conveyor grows the bar and the rollers stay
    round. It is the unit's whole size, and its only one — ``width`` and
    ``height`` set the drawn box, which would stretch the rollers with it, so
    they are refused rather than left as a second answer to the same question.
    A quarter turn stands the belt on end, where the length is its height.

    ``feed`` is the tail end. Material is dropped onto a belt rather than piped
    into it, so the nozzle can be taken from the top face as well as the end.
    ``discharge`` is the head end, where the belt throws off; it can be taken
    from the underside too, for the chute that catches what comes over.
    """

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
    number, and the number is drawn **bare** — a real sheet does not repeat the
    letters inside the bubble. ``name`` is the full tag (``"FT-101"``), which is
    what equipment lists and cross-references want. A single combined argument
    (``Instrument("FT-101")``) is still accepted and split.

    ``pv`` taps the process; ``sig_in``/``sig_out`` carry signals. All three are
    signal connections and take a signal ``kind``: an impulse line to a
    transmitter is an instrument connection, not a process pipe. Variants:
    ``"default"`` (field balloon), ``"panel"``, ``"aux"``, ``"shared"``
    (a circle in a square: shared display and shared control, which ISA-5.1 no
    longer reads as "DCS"),
    ``"computer"``, ``"sis"`` (a diamond in a square — ANSI/ISA-5.1-2009
    Table 5.1.1 column B, the safety-instrumented-system symbol an issued sheet
    draws a trip with, also spelled ``"logic"``) and ``"interlock"`` (a plain
    diamond — Table 5.1.2 items 3-5, the generic interlock logic function).

    A balloon that measures something belongs *on* what it measures: see
    :meth:`attach` (and :meth:`pandid.flowsheet.Flowsheet.add_instrument`).
    """

    kind = "instrument"
    PORTS = [("pv", "inlet", "signal"), ("sig_in", "inlet", "signal"),
             ("sig_out", "outlet", "signal")]

    #: The variants that stand for a function rather than a device. A balloon is
    #: a thing — a transmitter in the field, a faceplate in the control room —
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
        square repeats — the same logic function appears wherever it acts — so
        the sheet shows one tag several times while the flowsheet keeps a
        distinct name for each square to address it by (``I-1``, ``I-1 (2)``).
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Whether this square is another drawing of the same logic function.

        Both ends have to be trip squares carrying the same tag: an ``LT-101``
        drawn twice is two transmitters on one loop number, and a square sharing
        its tag with a balloon is two different symbols claiming to be the same
        thing. They also have to be the *same* square — a plain interlock
        diamond and a diamond-in-square are two different ISA-5.1 symbols, so
        one of each on a tag is still a clash — except that ``"sis"`` and
        ``"logic"`` name one symbol and so count as the same.
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
        :class:`Unit` (mount on equipment). ``at`` locates the tap — a fraction
        ``0..1`` along the host stream's routed path, or a face (``"N"``,
        ``"S"``, ``"E"``, ``"W"``) of a host unit's drawn box.

        ``offset`` is the distance from the tap to the balloon centre;
        ``offset=0`` leaves the element sitting *on* the line, which is how an
        in-line primary element (an orifice plate FE) is drawn.

        ``angle`` is the direction the balloon branches off, in degrees from the
        flow direction at the tap, counter-clockwise positive — so the default
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
    tubes is a design decision an engineer makes deliberately — fouling service
    goes tube side because tubes can be cleaned, condensing vapour goes shell
    side — and that is a fact about the exchanger, so the drawing records it.
    Which side is the hot one inverts between operating cases while the nozzle
    stays where it is.

    Most variants are a shell and a tube side. The ones that are neither say so:
    ``air_cooled`` is a tube bundle with air across it, ``plate`` and ``spiral``
    have two interchangeable channel sets and letter them, and ``thin_film`` is
    an evaporator with a jacket and a product side.

    The ``kettle`` variant carries one nozzle more: ``bottoms``, the liquid draw
    at the weir end of the shell. A kettle reboiler is where a tower's bottoms
    product physically leaves — what does not boil overflows the weir — so the
    draw belongs on the exchanger and not on an invented splitter in the sump
    line.
    """

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
    gives the vessel more than one charge nozzle — ``feed_1`` ... ``feed_n``,
    spread down the shell top to bottom, in place of the single ``feed``.
    """

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
    """Flash drum or phase separator."""

    kind = "separator"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]


class Column(Unit):
    """Distillation or absorption column.

    Besides the feed and the two products, a real column has two *return*
    nozzles that close its internal loops: ``reflux_in`` (liquid back to the top
    from the reflux drum) and ``boilup_in`` (vapour back to the bottom from the
    reboiler). Without them a reflux loop has to be modelled as a recycle to
    some upstream unit, which drags the overhead system across the sheet.

    ``n_feeds`` gives the tower more than one feed nozzle — an extractive
    distillation takes its solvent above the feed tray, an azeotropic tower its
    entrainer. They are ``feed_1`` ... ``feed_n``, spread down the shell in
    declaration order, so ``feed_1`` is the highest and ``feed_n`` the lowest;
    the single-feed column keeps the plain ``feed``.
    """

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
    """Combines multiple inlet streams into one outlet."""

    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        for i in range(1, n_inlets + 1):
            self._add_port(f"in_{i}", "inlet", "process")
        self._add_port("outlet", "outlet", "process")


class Splitter(Unit):
    """Divides one inlet stream into multiple outlets."""

    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        self._add_port("inlet", "inlet", "process")
        for i in range(1, n_outlets + 1):
            self._add_port(f"out_{i}", "outlet", "process")
