"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``), and each subclass annotates those attributes
(``suction: Port``) so an editor and a type checker can see them; see
:class:`Unit` for why the annotation is a declaration rather than a second copy.

A unit whose nozzle count the caller chooses has no finite set of names to
declare, so it declares the *family* instead: ``mixer.inlets``,
``splitter.outlets``, ``block.inlets``/``outlets`` and
``column``/``reactor.feeds`` are ``tuple[Port, ...]`` in declaration order, and
:class:`Mixer` is where that choice is argued. The numbered attributes
(``mixer.in_3``) and ``port("in_3")`` are unchanged.

This module is also the public ``units`` namespace: ``from pandid import units``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, TypeVar

from pandid.deprecation import Deprecation
from pandid.geometry import Frame, Pin, _Slot
from pandid.ports import Port

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.render.symbols import Symbol
    from pandid.streams import Stream

__all__ = [
    "Unit",
    "Feed", "Product", "Pump", "Compressor", "Blower", "Valve", "Vessel", "Tank",
    "HeatExchanger", "Heater", "Cooler", "Reactor", "Separator", "Column",
    "Mixer", "Splitter", "Tee", "Reducer", "Fitting", "Ejector", "Vent", "Funnel",
    "Furnace", "Turbine", "Filter", "Dryer", "Conveyor", "Instrument", "Block",
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

    #: The drawings this class owns, class-local name first. Empty on a base
    #: class that owns its whole kind, which is checked at render as it always
    #: has been: an empty tuple says "every variant the registry has for this
    #: kind is mine", and the registry is the only thing that knows the list.
    #:
    #: A class that names some of them is saying the opposite, that the rest
    #: belong to another device, and it refuses them at construction. That is
    #: the difference the check buys: a variant naming a device this class is
    #: not fails on the line that asks for it, rather than surviving as far as
    #: the first layout or render and being refused there by
    #: :meth:`pandid.render.symbols.SymbolRegistry.get`.
    #:
    #: ``variant`` defaults to ``"default"``, so a class that names its variants
    #: and leaves that one out refuses to be built by name alone. A class whose
    #: own drawing is what naming it should ask for therefore lists ``"default"``
    #: and aliases it (``VARIANT_ALIASES = {"default": "cyclone"}``), which needs
    #: no second mechanism and no ``__init__`` of its own.
    VARIANTS: tuple[str, ...] = ()
    #: class-local variant name -> the registry's, where a class renames one.
    #:
    #: ``self.variant`` stores the *result*, so what a unit carries is the
    #: **registry's** spelling.
    #: :meth:`pandid.render.symbols.SymbolRegistry.for_unit` and
    #: :mod:`pandid.portgeom` read that attribute to find the artwork, and a
    #: name only one class knows would find none. The rename is therefore a
    #: spelling the constructor accepts, not a second name the rest of the
    #: package has to learn.
    #:
    #: The visible consequence is that :meth:`pandid.flowsheet.Flowsheet.to_dict`
    #: writes the registry name and not the class-local one, so a sheet written
    #: out and read back has lost the rename. Where that round trip matters,
    #: list **both** spellings in :attr:`VARIANTS`, class-local first: the alias
    #: then makes them two names for one drawing, and the spec the class wrote
    #: is a spec it accepts.
    VARIANT_ALIASES: dict[str, str] = {}

    #: nozzle name -> the name the *symbol* anchors it under, where a class
    #: calls one of its drawing's nozzles something else.
    #:
    #: A symbol's ``ports`` dict is keyed by name, so a class that renames a
    #: nozzle would otherwise ask the artwork for an anchor it does not have and
    #: be given the fallback, the centre of the box: two renamed draws then land
    #: on one point and their streams stack. Naming the anchor here is what lets
    #: a class rename a nozzle without the drawing having to be redrawn or the
    #: name it already ships under having to change.
    #:
    #: Declaring both names on the *symbol* is not the alternative it looks
    #: like. Two names at one coordinate is exactly what
    #: :meth:`pandid.render.symbols.Symbol.coincident_ports` reports, and it
    #: reports it because a symbol cannot tell a rename from two nozzles drawn
    #: on top of each other. So the rename is a fact about the class, and it
    #: lives on the class.
    #:
    #: The cost is deliberate and permanent: one drawing then answers to two
    #: nozzle vocabularies depending on which class was constructed. See
    #: :mod:`pandid.devices`, which is where that happens and where it is
    #: argued.
    #:
    #: A dict on the class can only name nozzles the class knows about when it
    #: is written, which is every nozzle but the ones :class:`Instrument` mints
    #: per signal connection. :meth:`_symbol_anchor` is the reader, and it is
    #: what that one class overrides; this stays the declaration for everything
    #: whose list is fixed.
    PORT_ANCHORS: dict[str, str] = {}

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

    @classmethod
    def _generic_class(cls) -> type["Unit"] | None:
        """The ancestor that owns this class's whole kind, ``None`` if none does.

        An empty :attr:`VARIANTS` is what "owns the whole kind" means, so the
        search is for the nearest ancestor that declares none and is still the
        same equipment type. That class draws every variant the registry has, so
        it is the escape hatch a refused variant has to name.

        The kind has to match. A class of your own that subclasses :class:`Unit`
        directly and names its variants has no such ancestor: ``Unit`` itself
        draws a generic box under ``kind = "unit"``, and offering it as the
        low-level form would send an author somewhere their artwork is not.
        """
        for klass in cls.__mro__:
            if issubclass(klass, Unit) and not klass.VARIANTS and klass.kind == cls.kind:
                return klass
        return None

    @classmethod
    def _unknown_variant(cls, name: str, variant: str) -> ValueError:
        """The error a class raises for a drawing it does not own.

        Returned rather than raised, the way
        :func:`pandid.portgeom.unreachable_face` is, so the traceback starts at
        the constructor the author called.

        It ends by naming the low-level form because refusing a variant is only
        half an answer. The drawing exists and is in the catalogue; some other
        class owns it, and the base class that owns the whole kind draws every
        one of them. A message that stopped at "not one of mine" would leave an
        author holding a symbol they can see and no call that reaches it.
        """
        close = get_close_matches(variant, cls.VARIANTS, n=1, cutoff=0.6)
        suggestion = f" (did you mean {close[0]!r}?)" if close else ""
        generic = cls._generic_class()
        escape = "" if generic is None else (
            f" The generic form is {generic.__name__}(variant={variant!r}), which "
            f"takes any variant registered for a {cls.kind}."
        )
        return ValueError(
            f"{name}: {cls.__name__} draws "
            f"{', '.join(repr(v) for v in cls.VARIANTS)}, not {variant!r}{suggestion}. "
            f"A different device is a different class, so {variant!r} belongs to "
            f"whichever class draws it.{escape}"
        )

    def __init__(self, name: str, variant: str = "default", width: float | None = None, height: float | None = None, label_pos: str | None = None, description: str = "", reference: str = ""):
        if not name:
            raise ValueError("Unit name cannot be empty")
        self.name = name
        if self.VARIANTS and variant not in self.VARIANTS:
            raise self._unknown_variant(name, variant)
        # The registry's spelling, never the class-local one: see
        # :attr:`VARIANT_ALIASES` for what reads this and what it costs.
        self.variant = self.VARIANT_ALIASES.get(variant, variant)
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
        port_name = self._current_name(port_name)
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

        port_name = self._current_name(port_name)
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

    def has_another_port(self, port: "Port") -> bool:
        """Whether this unit has a second connection like ``port`` to give.

        False here, and so for every nozzle of every piece of equipment: a pump
        has one suction, and a second line to it is a mistake in the drawing
        rather than a request for another nozzle. The one class that answers
        otherwise is :class:`Instrument`, whose signal connections are a pool,
        and it is the whole of the exception.

        The question is asked separately from :meth:`another_port`, which does
        the taking, because :meth:`pandid.flowsheet.Flowsheet.connect` has two
        ends to settle and must not mint on one of them for a call it is about
        to refuse on the other: a balloon left carrying a nozzle no line reaches
        is a drawing changed by an error, and the debug overlay draws it.
        """
        return False

    def another_port(self, port: "Port") -> "Port":
        """A second connection like ``port``. Only called where :meth:`has_another_port`.

        ``port`` itself here, since nothing on this class has a second of
        anything; overriding :meth:`has_another_port` without this would be a
        unit that says it has more connections and then hands back the one that
        is already spoken for.
        """
        return port

    def _symbol_anchor(self, port_name: str) -> str:
        """The name this unit's *symbol* anchors ``port_name`` under.

        :attr:`PORT_ANCHORS` is the whole of the answer for every unit whose
        nozzle list is fixed when the class is written, which is all but one of
        them: the rename is a fact about the class and the class states it.
        :class:`Instrument` overrides this because its signal connections are
        minted per connection, so their names do not exist when the class is
        written and no dict on the class could hold them.

        :mod:`pandid.portgeom` asks through here and nowhere else, so a unit that
        answers for a name the artwork never heard of lands its nozzle on drawn
        ink rather than on the box-centre fallback.
        """
        return type(self).PORT_ANCHORS.get(port_name, port_name)

    def _retired_ports(self) -> dict[str, tuple[str, Deprecation]]:
        """Nozzle names this unit still answers to, and what each one is now.

        Empty for everything but a class that has renamed a draw, and empty
        there for every variant that did not have the old name. Asked of the
        *unit* rather than read off the class for that second reason:
        :class:`Separator`'s rename is true of three of its eleven drawings, and
        a dict on the class would have a flash drum answering to an
        ``overflow`` it never had.

        Each value pairs the current name with the
        :class:`~pandid.deprecation.Deprecation` that announces it, because a
        lookup that returned one nozzle while the sentence named another is
        exactly the drift the deprecation mechanism exists to make impossible.
        """
        return {}

    def _retired_port(self, name: str, stacklevel: int = 4) -> Port | None:
        """The nozzle a retired name still reaches, or ``None`` if it is not one.

        Every way to a nozzle *by name* goes through here -- ``sep.vapor``,
        ``sep.port("vapor")``, ``nozzle()``, ``pin(port=...)`` and the spec
        reader -- so a sheet or a spec file written against the old name still
        draws, and gets the same sentence whichever spelling it used.
        ``sep.ports["vapor"]`` does not, and cannot: it is the dict itself, and
        the rename is a fact about what is in it.

        *stacklevel* is 4 rather than :meth:`~pandid.deprecation.Deprecation.warn`'s
        default 3, because there is one frame more than it assumes: ``warn``,
        this method, the accessor that called it, and then the author's line. A
        caller with a frame of its own in between passes 5.
        """
        retired = self._retired_ports().get(name)
        if retired is None:
            return None
        current, notice = retired
        notice.warn(self, where=self.name, stacklevel=stacklevel)
        return self.ports[current]

    def _current_name(self, port_name: str) -> str:
        """``port_name``, or what it is called now if it is a retired spelling.

        For the entry points that carry a name rather than hand back a
        :class:`~pandid.ports.Port`: :meth:`nozzle`, :meth:`pin`'s ``port=`` and
        :func:`pandid.spec._find_port`. A name that is not retired comes back
        unchanged, typos included, so each of them still raises exactly where it
        did on one.
        """
        if port_name in self.ports:
            return port_name
        retired = self._retired_port(port_name, stacklevel=5)
        return port_name if retired is None else retired.name

    def port(self, name: str) -> Port:
        if name in self.ports:
            return self.ports[name]
        retired = self._retired_port(name)
        if retired is not None:
            return retired
        raise KeyError(
            f"{type(self).__name__!r} has no port named {name!r}; "
            f"available ports: {sorted(self.ports)}"
        )

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
    # raises the message below. The cost is the numbered members no annotation
    # can name one at a time (``mixer.in_3``; the family itself is declared, see
    # :class:`Mixer`) and the variant nozzles that are not on the base class
    # (see :class:`Separator`), which a checker refuses. The first is answered
    # by iterating the family or by ``port("in_3")``, the second by the
    # generated subclasses of the follow-up change.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            # Only invoked when normal lookup fails. Attribute access
            # (reactor.feed) is the primary way to reach ports, so give typos a
            # helpful message listing the real ports instead of a bare
            # AttributeError.
            ports = self.__dict__.get("ports")
            if ports is not None and not name.startswith("_"):
                # A nozzle this class used to call something else is still
                # reachable by the old name for one release. It is looked up
                # here rather than kept in ``ports``, so the sheet's own list of
                # nozzles is the new vocabulary and nothing but it.
                retired = self._retired_port(name)
                if retired is not None:
                    return retired
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


#: ``variant='pneumatic'`` retired in 0.1.2, and the only spelling this change
#: takes away.
#:
#: A module constant beside the branch that honours it, which is what
#: :func:`pandid.deprecation.declarations` enumerates and the only shape a
#: retirement can be held to a release by.
#:
#: The name went for two reasons at once. It names a **signal medium**, and a
#: medium is not a kind of valve: every actuated valve on this list is stroked by
#: something, and "the pneumatic one" picks out no body, no operator and no duty.
#: And as of 0.1.2 it names the **same drawing** ``control`` names, so it is the
#: second of two spellings for one symbol -- and it was the one an engineer had
#: to find, since the obvious one drew a valve with nothing on top of it.
#:
#: ``butterfly_pneumatic`` survives the same argument and is deliberately kept.
#: It names a *body* with an actuator on it, which is a valve you can point at on
#: a rack, and it is the only spelling for its drawing. Reach it either way:
#: ``variant='butterfly_pneumatic'``, or ``variant='butterfly',
#: actuator='diaphragm'``.
_RETIRED_PNEUMATIC = Deprecation(
    what="Valve(variant='pneumatic')",
    instead="Valve(variant='control')",
    removed_in="0.1.3",
)


class Valve(_NormallyPositioned):
    """Control or let-down valve.

    Two questions, asked separately. ``variant`` is the **body** -- what the
    valve is, ``"globe"``, ``"ball"``, ``"butterfly"``, ``"gate"`` and the rest.
    The ``actuator`` argument is **what strokes it**: ``"diaphragm"``,
    ``"motor"``, ``"solenoid"``, ``"hydraulic"`` or ``"handwheel"``, and unset
    for a bare body whose operator the drawing does not state.

    That is **ISO 15519-2:2015 Table A.3**'s own model, and it says so with its
    registration numbers. A.3.01 registers the bowtie as *"2-way on-off valve,
    straight type, general"* (2101A); A.3.41 registers a *"Diaphragm actuator,
    single acting"* (725A) on its own; and A.3.20, *"Control valve, general,
    continuously adjustability, shown with general actuator"*, carries three
    numbers at once because that symbol **is** the body symbol with an actuator
    symbol on it.

    ``variant="control"`` is the shorthand for the pairing every sheet draws six
    times: general body, diaphragm actuator. Type it and you get a complete
    control valve, dome and all::

        units.Valve("HV-101", variant="globe")                        # plain globe valve
        units.Valve("CV-303", variant="control")                      # control valve
        units.Valve("CV-303", variant="gate", actuator="diaphragm")   # the same drawing
        units.Valve("CV-303", variant="control", actuator="diaphragm")  # and the same again
        units.Valve("XV-201", variant="butterfly", actuator="diaphragm")
        units.Valve("SV-401", variant="solenoid")                     # = actuator="solenoid"

    The fourth of those spells out what the second is shorthand for, and it is
    **allowed**: a shorthand's own actuator, named alongside it, is one true
    thing said twice rather than two contradictory ones. What is refused is a
    *disagreement* -- ``variant="control", actuator="motor"`` is two operators
    and one drawing, and there is no telling which the author meant.

    **The stencil set draws pairings, not parts.** Every actuated valve draw.io
    ships is one fused shape -- "Pneumatic Operated" is a bowtie with a dome on
    it, "Motor Operated Valve" the same bowtie with a lettered box -- so there is
    no loose actuator glyph to lay over a globe or a ball, and a globe body with
    a diaphragm on it is a drawing that does not exist. The pairings that do are
    :data:`pandid.render.symbols.ACTUATED`, and asking for one that is not there
    raises and names them. What is stored is the *variant*, because the variant
    is the drawing and the pair is only a way of asking for it.

    Up to 0.1.1 ``variant="control"`` drew a Saunders body with no operator at
    all: a bowtie, a weir arc inside it, and nothing on top. That drawing is a
    real valve and keeps its place as ``variant="saunders"``; what it is not is
    a control valve. **ISO 15519-2:2015 Table 5** (p. 19) lists *"specific
    graphical symbols for process equipment incl. prime movers ..., valves incl.
    actuators, connections, etc."* as **basic information** for a P&ID, so the
    actuator is not decoration on the symbol -- it is part of what the symbol is
    for. Issue #136.

    ``actuator`` is also the name of the **signal connection** on top of the
    valve, the terminus of a control loop, so a controller's output lands on the
    final control element rather than in mid-air. One word for one thing: the
    keyword says which actuator is fitted and the port is the terminal on it.
    Being a signal port, it takes a signal ``kind`` and refuses process fluid: a
    pipe into a valve stem is not a connection.

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
    NC"*, is enforced: a ``control``, ``regulator``, ``relief`` or ``psv`` valve
    raises rather than drawing a mark the standard forbids.

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

    def __init__(self, name: str, variant: str = "default", *,
                 actuator: str = "",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", normal_position: str = "open",
                 fail: str = ""):
        variant = self._resolve(name, variant, actuator)
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference, normal_position=normal_position)
        self._fail = ""
        self.fail = fail

    def _resolve(self, name: str, variant: str, actuator: str) -> str:
        """The one variant that draws *variant* with *actuator* on it.

        Before ``super().__init__``, so what the rest of this package sees is a
        variant and nothing else: :data:`~pandid.render.symbols.NC_DARKENS`,
        :data:`~pandid.render.symbols.FAIL_ACTUATED`,
        :func:`pandid.spec.dump`, the SVG renderer and the draw.io exporter all
        go on reading ``self.variant`` and none of them learns a second axis.
        That is the same move :attr:`Unit.VARIANT_ALIASES` already makes for
        :class:`pandid.devices.ControlValve`, whose ``default`` has resolved to
        ``control`` since 0.1.0.

        It is also why the pair is not kept. Storing ``(body, actuator)``
        *beside* the resolved variant would be one fact in two places, which
        :attr:`Block._faces` argues is a fact that will one day disagree with
        itself; and the resolved variant is the one the sheet is issued with,
        so it is the one that survives a round trip through
        :mod:`pandid.spec`.
        """
        from pandid.render.symbols import ACTUATED, ACTUATORS, actuated_variant

        if variant == "pneumatic":
            _RETIRED_PNEUMATIC.warn(self, where=name)
            variant = "control"
        if not actuator:
            return variant
        if actuator not in ACTUATORS:
            raise ValueError(
                f"{name}: actuator is one of "
                f"{', '.join(repr(a) for a in ACTUATORS)}, got {actuator!r}. It is "
                f"what strokes the valve; what the valve *is* -- the body -- is "
                f"variant."
            )
        # ``control`` and the rest already name a body with an operator on it, so
        # the question ``actuator`` asks has an answer before it is asked. Read
        # that answer back out of the same table, and the two cases part:
        #
        # - **agreeing.** ``variant='control', actuator='diaphragm'`` is one true
        #   thing said twice, by an engineer being explicit about the valve they
        #   have. There is nothing to choose between and nothing to guess, so it
        #   resolves to the variant it already named;
        # - **disagreeing.** ``variant='control', actuator='motor'`` is two
        #   operators and one drawing. That is a real contradiction, and the two
        #   spellings are not merged silently: the author meant one of them and
        #   this package cannot tell which.
        #
        # Derived rather than tabulated, so :data:`~pandid.render.symbols.ACTUATED`
        # stays the one place a pairing is written down: a second table naming
        # what each variant is fitted with is that fact in two places, which is
        # what :attr:`Block._faces` argues will one day disagree with itself.
        fitted = {a for (_, a), drawn in ACTUATED.items() if drawn == variant}
        if fitted:
            if actuator in fitted:
                return variant
            raise ValueError(
                f"{name}: variant {variant!r} already draws a valve with a "
                f"{', '.join(repr(a) for a in sorted(fitted))} operator on it, so it "
                f"cannot also take actuator={actuator!r} -- one drawing, two "
                f"operators. Name the body and the actuator (variant='gate', "
                f"actuator={actuator!r}), or the pairing on its own "
                f"(variant={variant!r})."
            )
        return actuated_variant(variant, actuator)

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

    Besides the process pair a vessel has three connections that are not what
    enters and what leaves: ``vent``, the vapour connection off the top head;
    ``relief``, where the protective device sits; and ``drain``, the low-point
    liquid draw. :class:`Tank` carries the same five, which is the point --
    a tank and a vessel are one shell at two design pressures, and the
    difference between them is drawn rather than declared.

    **Named, and not counted**, and this is the canonical statement of that
    choice; :class:`Tank` refers here rather than restating it.

    A count was the consistent answer. Five classes already take one --
    ``Mixer(n_inlets=)``, ``Splitter(n_outlets=)``, ``Column``/
    ``Reactor(n_feeds=)``, ``Block(inputs=)`` -- and ``Vessel(outlets=3)`` would
    have been the sixth. It is the wrong answer here, and consistency does not
    rescue it, because **a vessel's connections are positioned by what they are
    for and a number carries no duty**. CHEE4001 p.7: "The PSV should be placed,
    whenever possible, directly on the system to be protected, vertically,
    upward, and at the top of the container." A relief is on the crown because
    that clause puts it there. Three interchangeable draws have nothing in them
    that says the third is a relief, so nothing stops it being placed on the
    floor -- and a relief on the floor is not a layout preference gone wrong, it
    is a drawing that asserts the protective device vents the liquid. A
    :class:`Block`'s connections carry no such meaning, which is exactly why
    counting is right there and wrong here.

    The same number decides **where the ink goes**, and that is where a count
    runs out of drawing. A stencil draws a fixed set of nozzles, and not many:
    ``tank/sphere`` draws three rectangles, ``vessel/legs`` draws none at all.
    A role has one position per drawing because it has one meaning, so each of
    the ten vessel stencils and seven tank stencils authors a coordinate for
    each of the five nozzles and :func:`pandid.portgeom.is_anchored` is true for
    every pair -- there is no placement rule to run and therefore nothing to
    outrun. Ask a count for one more and the only thing that can place it is
    :func:`pandid.render.symbols.spread`, walking a family along a face the
    artwork may have no ink on; a nozzle the symbol never anchored falls back to
    the centre of the box, where any two of them land on each other. Ports and
    drawn nozzles have already come apart once that way, which is issue #225.

    What a fixed set costs is that the drawing cannot be asked for a *second*
    relief, and that is the honest bound: it is a change to the artwork, made
    where the artwork is, rather than a number that promises what no stencil
    can draw. ``scripts/vendor_symbols.py`` is where the seventeen port maps
    live and what the measurement for each of them is written against.

    Nothing here is reported by ``nozzle-unconnected``. That finding reads a
    *numbered* nozzle -- a count the author wrote down and did not meet -- and
    none of these is numbered, so a tank with a bare ``relief`` is silent for
    the same reason a vessel with a bare ``vent`` has always been silent. It
    does make the case for drawing a spare nozzle blanked (issue #215) worth
    more, since there are now three unpiped connections on a typical tank rather
    than none; it does not make it more urgent, because an unpiped port draws
    nothing at all and no sheet changes until #215 lands.
    """

    inlet: Port
    outlet: Port
    vent: Port
    # The connection a protective device sits on: a PSV, a rupture disc, a pilot
    # valve. Not the device, which is a :class:`Valve` or a :class:`Fitting` of
    # its own with its own tag -- this is the nozzle it is mounted on, so that
    # the relief path is drawn *from the vessel* and can be seen not to run
    # through anything else. That is the whole reason it is a third connection
    # rather than a takeoff off the draw-off, and issue #222 puts it in one
    # line: a relief path must not depend on a valve someone can close.
    #
    # ``process`` and not ``vapor``, which ``vent`` next door takes. What a
    # relief passes is whatever the vessel is full of at the moment it lifts --
    # vapour on a gas case, liquid on a thermal-expansion or a fire case where
    # the vessel is liquid-full, two phases in between -- and the role
    # vocabulary has no word that covers those. Saying ``vapor`` of a
    # liquid-full relief is the kind of bend :class:`Separator`'s
    # ``overflow``/``underflow`` pair exists to keep out of the names.
    relief: Port
    # The low-point liquid draw: a water draw-off, a clean-out, the knocked-out
    # liquid a vapour drum collects. Distinct from ``outlet`` because on nine of
    # the ten vessel drawings ``outlet`` is on the *shell wall* -- a vessel is
    # piped side to side and the bottom head is left free -- so before this
    # there was no nozzle at the bottom of a vessel at all, which is
    # ``examples/14``'s V-604 knocking liquid out of a vapour stream with
    # nowhere to put it.
    drain: Port

    kind = "vessel"
    # Appended rather than woven in among the three that were here in 0.1.1.
    # ``ports`` is insertion-ordered and a family placed by a
    # :class:`~pandid.render.symbols.PortSeries` is spread in the unit's own
    # port order (see :func:`pandid.portgeom._series_point`), so the order is
    # observable; putting the new ones last is what makes this change purely
    # additive for every sheet already drawn.
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]


class Tank(Unit):
    """Storage tank. Variants: ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``, and three named for a cone at the bottom:
    ``"conical_bottom"``, ``"conical_ends"``, ``"dished_roof_conical_bottom"``.

    A tank's five nozzles are :class:`Vessel`'s five, for the reason argued
    there. Two of them are what a storage tank exists to have and could not be
    drawn before:

    - **``vent``, the conservation vent.** A fixed-roof tank fills, empties and
      warms through the day, and it breathes through a roof nozzle that is
      neither the fill nor the draw. ``examples/14``'s ethanol tank wants a
      breather with a flame arrestor under it and could only imply the
      arrangement. No document on disk says anything about tank venting,
      arrestors or floating roofs -- ``examples/14`` went looking and reported
      the absence rather than stretching a clause -- so this one is ordinary
      practice and is claimed as nothing more.
    - **``relief``, the fire-case relief on the sphere.** This one *is* cited.
      CHEE4001 p.8 names the duty exactly: "Protection against exposure of a
      pressure vessel to fire or other sources of heat provided that the vessel
      has no permanent supply connection. This is usually the case with storage
      vessels for non-refrigerated liquefied compressible gases at ambient
      temperatures." And p.7 says where it goes, which is why the two are
      separate nozzles rather than one: "The PSV should be placed, whenever
      possible, directly on the system to be protected, vertically, upward, and
      at the top of the container."

    A vent and a relief are both on the crown and are still two connections,
    because one of them passes something on every fill and every cold night and
    the other passes nothing until the design case. A sheet that draws one line
    off the roof has said which of those two it is.

    Whether a given tank really has all five is the sheet's business and not
    this class's. A floating roof has no vapour space to conserve, an
    atmospheric tank is protected by its vents rather than by a PSV, and neither
    is a reason to withhold a nozzle: a declared nozzle is *offered*, and
    choosing not to pipe one is a drawing decision -- which is the rule
    :func:`pandid.validate.validate` already measures the whole corpus against.
    Withholding one per variant is what :class:`Separator` does, and it is worth
    saying why this is not that case: a mechanical separator has ``overflow``
    and ``underflow`` **instead of** ``vapor`` and ``liquid``, never as well, so
    declaring all four would tell a checker a flash drum has an overflow. Here
    every variant has all five and the question is only whether a particular
    plant piped them.

    **Where a tank fills** is a menu and not a fixture, which is issue #226.
    Until 0.1.2 every variant's ``inlet`` was fixed on the crown, so no sheet
    could draw a bottom-filled tank at all: ``examples/14`` top-filled both its
    atmospheric tanks because the symbol left no choice, and one of them is a
    *floating roof*, where the plate the fill landed on rides on the liquid.

    Splash-filling a flammable liquid into a vapour space generates static, so
    bottom entry -- or a fill pipe carried down to the floor -- is the ordinary
    arrangement for motor spirit or ethanol, and a fill drawn onto the crown
    with nothing said about a downcomer reads as the splash fill. **None of the
    three documents on disk covers tank filling, static or downcomers**, so that
    is ordinary practice and is claimed as nothing more; contrast the relief
    above, which CHEE4001 p.7 places outright.

    So the four flat-floored variants -- ``default``, ``conical``,
    ``floating_roof`` and the sphere -- anchor the fill low on the shell, and
    the three hopper-bottomed ones keep the crown, because a hopper is the
    drawing for solids or a slurry and a silo is filled over the top. Every
    variant offers both, and moving between them is the same
    :meth:`~Unit.nozzle` call every other unit takes::

        tk = Tank("TK-602")                 # fills low on the shell
        tk.nozzle("inlet", "N")             # ...through a crown downcomer

    No new keyword, deliberately. "This tank is bottom-filled" and "pipe this
    nozzle from the west" are the same sentence, and ``nozzle()`` is the one an
    engineer already types for a drum, a column and a pump. A ``fill=`` argument
    would be a second spelling of it on one class, and would then owe the draw,
    the drain and the vent one each.

    ``floating_roof`` is the one variant offering no crown placement at all, and
    that is a fact about the drawing rather than a default: a floating roof
    rides on the liquid, so there is no fixed roof to weld a nozzle to and
    ``nozzle("inlet", "N")`` raises rather than drawing a pipe joined to a
    moving deck. The sphere is the other end of the same argument -- its crown
    carries two drawn nozzles and both are spoken for; see #225 and the block in
    ``scripts/vendor_symbols.py``.

    A tank with no ``nozzle()`` call still gets its face chosen by layout, from
    where the peer landed (:mod:`pandid.layout.faces`), exactly as a drum's
    inlet has always been. The anchor above is what an unconstrained tank falls
    back to and what the menu is ordered by; a sheet that has *decided* how a
    tank fills says so, which is what naming a face is for.
    """

    inlet: Port
    outlet: Port
    # The same three :class:`Vessel` declares, and each carries the comment
    # there. The pair of classes is deliberately identical: 0.1.1 gave a vessel
    # a ``vent`` and a tank nothing, which said that a tank does not breathe.
    vent: Port
    relief: Port
    drain: Port

    kind = "tank"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]


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


#: A minted member of one of :class:`Instrument`'s signal pools. Member one of
#: each keeps the name it shipped under (``sig_out``) and the rest count on from
#: two (``sig_out_2``), so the pattern is what tells a grown connection from a
#: born one -- and from ``pv``, which is neither.
_POOL_MEMBER = re.compile(r"(sig_in|sig_out)_\d+")


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
    transmitter is an instrument connection, not a process pipe.

    ``sig_in`` and ``sig_out`` are **pools**, not single connections. Each hands
    back a free one and mints another when they are all taken, so a balloon
    takes as many signal lines as the loop needs and each is placed on whichever
    face suits::

        fs.connect(pic301.sig_out, cv1.actuator, kind="pneumatic")
        fs.connect(pic301.sig_out, cv2.actuator, kind="pneumatic")   # split range

    Naming the units instead lets the engine pick both ends:
    ``fs.connect(ft305, fic305, kind="electric")``. Variants:
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
    # The three a balloon is born with, in the order everything downstream reads
    # them in. ``sig_in`` and ``sig_out`` are the first member of their pool
    # rather than the whole of it. They are declared here, and not minted lazily
    # on first use, because ``ports`` is an ordered dict that
    # :mod:`pandid.layout.faces` serves in order -- a balloon whose connections
    # appeared in the order the author happened to reach for them would draw
    # differently depending on which line was written first.
    PORTS = [("pv", "inlet", "signal"), ("sig_in", "inlet", "signal"),
             ("sig_out", "outlet", "signal")]

    #: The two pools, and the name the first member of each ships under.
    _SIGNAL_POOLS = ("sig_in", "sig_out")

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

    # ------------------------------------------------------------------
    # The signal pools.
    #
    # A balloon used to have exactly one input and exactly one output, and that
    # is not what a loop is. One controller drives two final elements on split
    # range; a measurement feeds a high alarm and a low alarm, which ISO
    # 15519-2 requires be drawn as separate lines rather than chained; an alarm
    # that participates in a trip needs an input *and* an output of its own. All
    # three are ordinary practice and none of them could be drawn.
    #
    # **Why a pool and not a declared count.** A count (``outputs=2``) has to be
    # given before the connections are made, so it is a second statement of
    # something the ``connect()`` calls already say, and the two can disagree:
    # an author who declares two and wires three gets an error about a number
    # rather than about the drawing, and one who declares three and wires two
    # gets a balloon carrying a nozzle nothing reaches. Minting per connection
    # cannot disagree with the connections, because it *is* them. It also means
    # nothing already written has to be revisited: a balloon with one line each
    # way has exactly the ports it always had, on exactly the anchors it always
    # had, which is what keeps every issued sheet in this repository
    # byte-identical across this change.
    #
    # **Why the members keep their shipped names.** ``sig_in`` and ``sig_out``
    # are public and are all over the examples, so member one of each pool is
    # spelled the way it always was and the rest count on from two.
    #
    # **Why they stay attributes and are not properties over the pool.** A
    # property handing back a free member reads well at the call site and
    # destroys the read-back. ``inst.sig_out.stream`` is how a caller asks what a
    # balloon drives; once the first line is made, a property would answer with a
    # *freshly minted* port whose stream is None, having grown a nozzle nothing
    # reaches as a side effect of being looked at. Reading an object must not
    # change it. So the pool is entered where a *connection* is made and not
    # where an attribute is read: :meth:`pandid.flowsheet.Flowsheet.connect` asks
    # for another member when the one it was handed is already wired, which is
    # the split-range case stated the way an author states it --
    #
    #     fs.connect(pic.sig_out, cv1.actuator, kind="pneumatic")
    #     fs.connect(pic.sig_out, cv2.actuator, kind="pneumatic")
    #
    # -- and leaves ``pic.sig_out`` meaning the first line for good.
    #
    # **Why signal ports carry no direction requirement.** ``Port.direction``
    # was checked by ``Flowsheet.connect`` and read nowhere else in the package,
    # and on a signal connection there was never anything for it to be true of:
    # an alarm's one connection is an input on the sheet that feeds it and an
    # output on the sheet that trips from it, and which it is on this sheet is
    # simply which end of the line it took. So the guard is now a rule about
    # process nozzles, where it does mean something -- fluid enters a nozzle or
    # leaves it -- and direction on a signal port is *derived*, from
    # ``Stream.source``/``Stream.dest``, which is exact because a port holds at
    # most one stream.
    #
    # It is deliberately **not** a bidirectional "both" state that latches to
    # the first use. There would be nothing for such a latch to refuse: every
    # connection gets a port of its own, minted free, so no port is ever asked
    # to be an input after it has been an output. The check would have been dead
    # code on the day it was written, and a state nothing can reach is a
    # statement about the design that the design does not make.
    #
    # **Why ``pv`` is not a pool.** An instrument taps one process point, and
    # that edge is a different kind of thing from a line between two
    # instruments: it is the impulse or capillary connection to the medium, and
    # it is what :meth:`attach` places the balloon against. A differential
    # instrument tapping two points is a real case and a known future one; it
    # wants a *second named tap*, high and low, not an anonymous pool member, so
    # nothing here is designed for it.
    # ------------------------------------------------------------------

    def has_another_port(self, port: Port) -> bool:
        """True for a member of one of the signal pools, false for ``pv``.

        A balloon taps one process point, so a second line to ``pv`` is the
        mistake :meth:`Unit.has_another_port` describes and is refused as one.
        """
        return self._pool_of(port.name) is not None

    def another_port(self, port: Port) -> Port:
        """A free member of ``port``'s signal pool, minting one if all are taken.

        Called by :meth:`pandid.flowsheet.Flowsheet.connect` on a connection that
        is already spoken for, which is what makes two lines off one ``sig_out``
        two lines rather than an error.
        """
        base = self._pool_of(port.name)
        if base is None:
            return port
        members = [p for name, p in self.ports.items() if self._pool_of(name) == base]
        for member in members:
            if member.stream is None:
                return member
        # Numbered from the members present rather than from a running count, so
        # a sheet rebuilt from a spec that named ``sig_out_2`` and ``sig_out_4``
        # numbers its next one 5 and does not collide with 4. The loop is what
        # makes that true when the named ones left a gap.
        n = len(members) + 1
        while f"{base}_{n}" in self.ports:
            n += 1
        return self._add_port(f"{base}_{n}", members[0].direction, "signal")

    def signal_port(self, name: str) -> Port:
        """The signal connection called ``name``, minting it if it is not there.

        The way to reach a pool member the balloon has not grown yet
        (``pic.signal_port("sig_out_2")``), which is what
        :func:`pandid.spec.from_dict` needs to rebuild a sheet a pool was used
        on. An existing port of any name comes back unchanged, so this is
        :meth:`~Unit.port` for everything but a pool member that is missing.
        """
        if name in self.ports:
            return self.ports[name]
        member = _POOL_MEMBER.fullmatch(name)
        if member is None:
            raise KeyError(
                f"{type(self).__name__!r} has no port named {name!r} and mints none "
                f"under that name; its signal pools are "
                f"{', '.join(f'{base}, {base}_2, {base}_3' for base in self._SIGNAL_POOLS)}"
            )
        return self._add_port(name, self.ports[member.group(1)].direction, "signal")

    @classmethod
    def _pool_of(cls, port_name: str) -> str | None:
        """The pool ``port_name`` belongs to, or None for a nozzle that is unique.

        Member one keeps the name it shipped under and the rest count on from
        two, so this is the one rule that tells ``sig_out`` and ``sig_out_2``
        apart from ``pv``, and everything about the pools reads it.
        """
        if port_name in cls._SIGNAL_POOLS:
            return port_name
        member = _POOL_MEMBER.fullmatch(port_name)
        return member.group(1) if member else None

    def _symbol_anchor(self, port_name: str) -> str:
        """Every pool member is drawn on the nozzle its pool's first one is.

        A balloon is a circle and its signal connections are declared
        ``faceless`` (:attr:`pandid.render.symbols.Symbol.faceless_ports`), which
        is exactly the statement that they all share one menu of four faces and
        none of them owns one. So a minted member wants the menu ``sig_out``
        already has, and asking the artwork for it by rule is what saves the
        registry from having to anchor a name it cannot know.

        Which of those four faces a member actually lands on is
        :mod:`pandid.layout.faces`' answer, port by port, against where each
        peer ended up, and it already refuses to put two live connections on one
        point.
        """
        return self._pool_of(port_name) or super()._symbol_anchor(port_name)

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

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds. Empty on a class that declares its own.

        ``__init__`` lays these down *after* ``super().__init__()`` has laid down
        :attr:`~Unit.PORTS`, so a subclass that declares its whole nozzle list
        and inherits this constructor would add ``shell_in`` a second time and
        be refused by :meth:`~Unit._add_port`. Asking here, once, is what lets a
        per-variant subclass be a class body and nothing else: no ``__init__``
        of its own, and no copy of the loop below per generated class.

        The base is unaffected, and that is the whole compatibility argument:
        :attr:`PORTS` is ``[]`` here, so :meth:`~Unit._declared_ports` answers
        empty and every ``HeatExchanger(variant=...)`` gets exactly the nozzles
        it always did.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._SHELL_AND_TUBE)

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # ``self.variant``, not the argument: _VARIANT_PORTS is keyed the way
        # the registry spells a variant, and that is what the constructor stored
        # once :attr:`~Unit.VARIANT_ALIASES` had its say.
        for spec in self._variant_ports(self.variant):
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

    The spelling is the only thing the count changes: ``unit.feeds`` is the
    family either way, a one-tuple where this returns ``["feed"]``, so a caller
    that iterates never has to ask which it got.
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
    # Every charge nozzle, in declaration order and so top to bottom down the
    # shell. Whether they are spelled ``feed`` or ``feed_1`` ... ``feed_n`` is
    # the count's business (see :func:`_feed_names`), and this is the one
    # accessor that reads the same either way: a single-feed vessel's ``feeds``
    # is the one-tuple holding its ``feed``. The sequence is the general form,
    # and the singular name stays.
    feeds: tuple[Port, ...]
    # The single-feed vessel's charge nozzle. ``n_feeds > 1`` spells it
    # ``feed_1`` ... ``feed_n`` instead, a family whose size is the caller's, so
    # there is no finite set of names to declare and no annotation that could
    # stand for them one at a time; see :class:`Mixer`. ``feed`` itself is not
    # one of that family, it is what a reactor asked for by name has, so it is
    # declared like any other fixed nozzle as well as being in ``feeds``.
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
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)


#: The two draws the dust collectors renamed in 0.1.2, one declaration each.
#:
#: Module constants because :func:`pandid.deprecation.declarations` finds them
#: that way and no other: one built inside :attr:`Separator._RETIRED_DRAWS`
#: would be a retirement no release could be held to, which is the failure that
#: convention exists to prevent.
#:
#: One per nozzle rather than one for the pair, because a finding names the call
#: the author has to go and find in their own file, and an author who piped only
#: the catch away should not be sent looking for a ``vapor`` they never typed.
_RETIRED_VAPOR_DRAW = Deprecation(
    what="Separator(variant='cyclone'|'gravity'|'electrostatic').vapor",
    instead=".overflow",
    removed_in="0.1.3",
)
_RETIRED_LIQUID_DRAW = Deprecation(
    what="Separator(variant='cyclone'|'gravity'|'electrostatic').liquid",
    instead=".underflow",
    removed_in="0.1.3",
)


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

    **The draws are named for what leaves, not for the shape of the body.** Four
    variants keep ``vapor`` and ``liquid``, and those four are the ones where the
    two really are phases disengaging: the drum in its three drawings, and the
    wet scrubber, whose products are a cleaned gas and a dirty scrubbing liquid.

    The other seven draw ``overflow``, high on the body, and ``underflow``, out
    of the apex. They are the four **mechanical** separators -- ``"sifter"``,
    ``"impact"``, ``"permanent_magnet"``, ``"electromagnetic"`` -- which sort by
    size, inertia or magnetism rather than into phases, and the three **dust
    collectors**, ``"cyclone"``, ``"gravity"`` and ``"electrostatic"``, whose
    catch is a hopper full of solids. The pair names the two *positions* the
    artwork draws, on the same principle as :class:`HeatExchanger`'s nozzles, and
    it is the ordinary vocabulary of classification and solid-liquid separation.
    Neither name says which of the two is the product, because that is a fact
    about the service and not about the machine: a cyclone on a spray dryer
    recovers its product from the underflow, and the identical cyclone on a vent
    line throws that same catch away.

    The three collectors called their catch ``liquid`` up to 0.1.1, while
    :class:`~pandid.devices.Cyclone`, :class:`~pandid.devices.GravitySeparator`
    and :class:`~pandid.devices.ElectrostaticPrecipitator` -- the same three
    drawings, reached by name -- have always called it ``underflow``. One
    drawing answering to two vocabularies depending on which class built it was
    a cost recorded as permanent and is not one any more. The old pair still
    resolves for 0.1.2 with a :class:`DeprecationWarning` and a ``deprecated``
    finding on :meth:`~pandid.flowsheet.Flowsheet.validate`, and goes in 0.1.3;
    see :meth:`_retired_ports`.

    Every variant is drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: vapour disengages
    off the top and liquid draws off the bottom, which is ISO 15519-1 §11.4.2's
    exception for symbols where gravity is a functionality.
    """

    # The phase draws, and only those: ``_VARIANT_PORTS`` below defaults to
    # ``_PHASES``, so they are what a separator asked for by name has.
    # ``overflow`` and ``underflow`` are deliberately absent. Seven of the
    # eleven variants have them *instead of* ``vapor`` and ``liquid``, never as
    # well as, so declaring all four here would tell a checker that a plain
    # flash drum has an ``overflow``, which is exactly the mistake the over/under
    # pair exists to keep out of the vocabulary. They belong on a per-variant
    # subclass, which ``pandid.devices`` is: ``devices.Cyclone`` declares the
    # collectors' three and a checker resolves them. Off it, the draws of a
    # variant this class does not annotate are reached by
    # ``sep.port("overflow")``.
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
    # A high draw and a low draw. That is the whole of what is true of every
    # body that takes this set, so naming the two positions is the most the
    # drawing supports -- and it is what classification and solid-liquid
    # separation call them anyway, on a hydrocyclone, a thickener or a
    # classifier. The four mechanical stencils are one body, anchor for anchor:
    # a box with a hopper under it, the feed high on one wall (0, 12), one draw
    # high on the opposite wall (80, 12) and one out of the apex (40, 120). The
    # three collectors put the high draw at the top of the vortex or the chamber
    # instead, which is why the pair names positions and not coordinates.
    #
    # ``process`` rather than ``vapor``/``liquid`` on both draws, because what
    # leaves is dry dust from a precipitator or a settling chamber, tramp metal
    # from a magnet, a screened size fraction, or a cyclone's recovered product,
    # and the role vocabulary has no word that covers those. Saying ``liquid``
    # of a hopper full of dust is the bend this set exists to stop. No drawing
    # depends on the difference: outside ``signal``, and ``energy``/``utility``
    # on both ends of one stream, ``connect()`` and the renderer never read a
    # role.
    _OVER_AND_UNDER = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_PHASES`.
    #:
    #: ``default``, ``horizontal``, ``knockout`` and ``scrubber`` are absent, and
    #: they are the four whose draws really are phases. A drum's two are the
    #: vapour disengaging and the liquid settling out; a wet scrubber's are a
    #: cleaned gas and a dirty scrubbing liquid. :data:`_PHASES` already says so.
    #:
    #: ``cyclone``, ``gravity`` and ``electrostatic`` are in it as of 0.1.2. A
    #: settling chamber and a precipitator collect *dust*, and so does a cyclone
    #: in the gas-solid service ISO 15519-1 draws it for; all three called that
    #: catch ``liquid`` up to 0.1.1 while the three device classes over the same
    #: drawings called it ``underflow``. That divergence was written down as a
    #: permanent cost of correcting the names without a break, and this is the
    #: announced break instead: the old pair resolves through
    #: :meth:`_retired_ports` for one release and is gone in 0.1.3.
    _VARIANT_PORTS = {
        "cyclone": _OVER_AND_UNDER,
        "gravity": _OVER_AND_UNDER,
        "electrostatic": _OVER_AND_UNDER,
        "sifter": _OVER_AND_UNDER,
        "impact": _OVER_AND_UNDER,
        "permanent_magnet": _OVER_AND_UNDER,
        "electromagnetic": _OVER_AND_UNDER,
    }
    #: The name each renamed draw is anchored under in the *artwork*, keyed by
    #: variant. The three collectors' stencils have anchored ``vapor`` and
    #: ``liquid`` since 0.1.0 and still do: the ink did not move, and this is a
    #: rename of the nozzle rather than a redrawing of the symbol.
    #:
    #: Keyed by variant rather than declared in :attr:`Unit.PORT_ANCHORS`, which
    #: is the class-wide form of the same statement, because eight of this
    #: class's eleven drawings anchor exactly what they are asked for. A dict on
    #: the class would send a sifter's ``overflow`` to a ``vapor`` anchor its
    #: stencil does not have, and an unfound anchor is a nozzle on the centre of
    #: the box. :class:`~pandid.devices.Cyclone` and its two siblings carried a
    #: copy of this each and now inherit it: a class that owns one drawing has
    #: the drawing's rename, and stating it twice was two places for one fact.
    #:
    #: It doubles as the list of variants that renamed anything, which is what
    #: :meth:`_retired_ports` reads it for. The two are the same three by
    #: construction -- a drawing's anchors differ from its nozzle names exactly
    #: when the nozzle was renamed -- so they are one list.
    _VARIANT_ANCHORS = {
        "cyclone": {"overflow": "vapor", "underflow": "liquid"},
        "gravity": {"overflow": "vapor", "underflow": "liquid"},
        "electrostatic": {"overflow": "vapor", "underflow": "liquid"},
    }
    #: The old draw names, what each reaches now, and the notice it carries.
    _RETIRED_DRAWS = {
        "vapor": ("overflow", _RETIRED_VAPOR_DRAW),
        "liquid": ("underflow", _RETIRED_LIQUID_DRAW),
    }

    def _symbol_anchor(self, port_name: str) -> str:
        """The name this separator's *drawing* anchors ``port_name`` under.

        :attr:`_VARIANT_ANCHORS` first, then the base's, so a subclass that
        states a rename of its own in :attr:`Unit.PORT_ANCHORS` still gets it.
        """
        renamed = self._VARIANT_ANCHORS.get(self.variant, {})
        return renamed.get(port_name) or super()._symbol_anchor(port_name)

    def _retired_ports(self) -> dict[str, tuple[str, Deprecation]]:
        """``vapor`` and ``liquid``, on the three variants that renamed them.

        Answered from ``self.variant``, because a flash drum, a knockout drum
        and a wet scrubber still *have* a ``vapor`` and a ``liquid`` and there is
        nothing deprecated about either: they are the phases leaving. A class-
        wide answer would retire the correct vocabulary along with the wrong one.
        """
        return self._RETIRED_DRAWS if self.variant in self._VARIANT_ANCHORS else {}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds. Empty on a class that declares its own.

        The same one line :meth:`HeatExchanger._variant_ports` is, for the same
        reason and with the same compatibility argument: :attr:`PORTS` is ``[]``
        here, so the base still lays down :data:`_PHASES` or the mechanical
        separators' pair exactly as it did.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._PHASES)

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # ``self.variant`` rather than the argument, as HeatExchanger explains.
        for spec in self._variant_ports(self.variant):
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
    # Every feed nozzle, in declaration order and so highest first, whatever the
    # count spelled them. See :class:`Reactor`, which carries the same pair for
    # the same reason.
    feeds: tuple[Port, ...]
    # The single-feed tower's nozzle; ``n_feeds > 1`` replaces it with the
    # ``feed_1`` ... ``feed_n`` family, which cannot be declared a member at a
    # time. See :class:`Reactor`, which spells the same rule, and :class:`Mixer`.
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
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)


# ---------------------------------------------------------------------------
# Variable-port unit types
# ---------------------------------------------------------------------------


class Mixer(Unit):
    """Combines multiple inlet streams into one outlet.

    A piece of plant, drawn as a triangle and scheduled as one. Where two lines
    simply meet in the piping, the fitting is a :class:`Tee`.
    """

    # Every inlet, in declaration order, and the canonical statement of why a
    # variable-port family is declared as a *sequence* rather than a member at a
    # time. The four other families refer here rather than restate it.
    #
    # The nozzles are ``in_1`` ... ``in_n`` and ``n`` is the caller's, chosen per
    # instance at construction, so the set of attribute names is a property of
    # the *object* and not of the class. A class annotation is a statement about
    # every instance, and there is no finite list here to make one from:
    # declaring ``in_1: Port`` and ``in_2: Port`` would be right for the default
    # and wrong for ``Mixer("M", n_inlets=5)`` in one direction and for
    # ``n_inlets=1`` in the other. Python has no integer generic, so no
    # ``Literal`` spells the set either, and a generated class per arity -- a
    # ``Mixer3`` declaring ``in_1`` ... ``in_3``, which this package could emit,
    # since it already generates classes -- misses the case that matters:
    # ``Mixer("M-1", n_inlets=len(feeds))`` is not a literal, so every overload
    # misses it. It would type the easy call and abandon the real one.
    #
    # The *family* is declarable, and is the whole of what a checker can be told
    # here. ``inlets`` holds the same ``Port`` objects ``in_1`` ... ``in_n`` are
    # bound to, so ``m.inlets[0]`` is a ``Port``, ``for p in m.inlets`` checks,
    # and ``len(m.inlets)`` is honest. The arity is still not in the type and
    # cannot be; a computed count works, which is what the per-arity classes
    # could not deliver.
    #
    # **Indexed from zero while the nozzles are numbered from one**:
    # ``m.inlets[0]`` is ``in_1``, and ``m.inlets[3]`` is ``in_4``. Nothing here
    # re-bases it. A sequence that indexed from one would be the only one in the
    # language, and buying the arithmetic back would cost ``[-1]``, slicing and
    # every ``zip`` and ``enumerate`` a reader already knows how to use.
    #
    # Where the number is what is wanted, ``m.port("in_3")`` is the way to ask
    # for it: it is the *only* 1-based route a checker can follow. ``m.in_3``
    # answers at run time and always has, but the ``__getattr__`` above is
    # hidden from type checkers, so mypy reads it as an error and an ``Any`` --
    # which makes it the wrong thing to point checked code at, whatever it does
    # when Python runs. ``enumerate(m.inlets, start=1)`` gives the number and
    # the port together, and ``Port.name`` carries the number too, so nothing
    # has to count. A fourth spelling (an ``m.inlet(3)``) was not added: it
    # would be a new name for what ``port()`` already does, and ``port()``
    # raises a message naming the nozzles that do exist.
    inlets: tuple[Port, ...]
    # The one nozzle every mixer has, declared like any other fixed one.
    outlet: Port

    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        # Built from what the loop that creates the family hands back, rather
        # than by matching ``in_`` against the ``ports`` dict afterwards: a
        # second reader would be the naming rule written down twice, and the
        # two spellings of one fact are what this file keeps saying not to do.
        self.inlets = tuple(
            self._add_port(f"in_{i}", "inlet", "process") for i in range(1, n_inlets + 1)
        )
        self._add_port("outlet", "outlet", "process")


class Splitter(Unit):
    """Divides one inlet stream into multiple outlets.

    A piece of plant, drawn as a triangle and scheduled as one. A bypass leg, a
    drain, a vent or a sample point is not that: it is a line branching, and
    the fitting that branches it is a :class:`Tee`.
    """

    # The one nozzle every splitter has.
    inlet: Port
    # Every outlet, in declaration order. ``out_1`` ... ``out_n`` are the
    # caller's count and no annotation can name them one at a time; the family
    # is what is declared, for the reason :class:`Mixer` gives at length, and it
    # is zero-based there for the reason given there too.
    outlets: tuple[Port, ...]

    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        self._add_port("inlet", "inlet", "process")
        self.outlets = tuple(
            self._add_port(f"out_{i}", "outlet", "process") for i in range(1, n_outlets + 1)
        )


def _block_faces(spec: "int | Sequence[str]", default: str, owner: str,
                 argument: str) -> list[str]:
    """Read a :class:`Block`'s ``inputs=``/``outputs=`` into one face per port.

    A plain count is the common case spelled short: ``inputs=3`` is three
    connections on the face a reader expects them on, which is the west for a
    feed and the east for a product, exactly as the rest of the library defaults.
    A sequence names the face of each one in order, which is what a block flow
    diagram actually needs -- a section takes its charge from the left and its
    recycle from above, and both are inputs.
    """
    if isinstance(spec, bool) or not isinstance(spec, (int, Sequence)) or isinstance(spec, str):
        # A bare string is the trap worth naming: ``inputs="W"`` looks like one
        # connection on the west and is a sequence of one character, so it would
        # otherwise be read as exactly that and quietly work until the day
        # somebody writes ``inputs="WN"``.
        raise ValueError(
            f"{owner}: {argument}= is a count ({argument}=3) or one face per "
            f"connection ({argument}=['W', 'W', 'N']), got {spec!r}"
        )
    if isinstance(spec, int):
        if spec < 0:
            raise ValueError(f"{owner}: {argument}= cannot be negative, got {spec}")
        return [default] * spec
    return [_block_face(face, owner) for face in spec]


def _block_face(face: object, owner: str) -> str:
    """One face name, in the vocabulary :meth:`Unit.nozzle` already takes.

    The compass point on the finished sheet, or the ``top``/``bottom``/``left``/
    ``right`` spelling ``label_pos`` uses, so a sheet needs one word for "the
    top of this block" whether it is declaring a connection or moving one.

    One sentence for both ways of getting it wrong, because they are the same
    mistake: the constructor and :meth:`Block.nozzle` both come through here.
    """
    resolved = (_FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
                if isinstance(face, str) else None)
    if resolved not in ("N", "S", "E", "W"):
        raise ValueError(
            f"{owner}: {face!r} is not a face; a connection is on the 'N', 'S', "
            f"'E' or 'W' of the box (or the 'top'/'bottom'/'left'/'right' spelling)"
        )
    return resolved


class Block(Unit):
    """A block flow diagram's box: a labelled rectangle standing for a section.

    The BFD is the drawing a level above the PFD, and this is the only symbol on
    it. One box is a whole plant section -- *Reaction*, *Compression*, *Product
    Recovery* -- with the streams between them named and nothing inside them
    drawn. That is why it carries no equipment vocabulary: it has no suction, no
    bottoms and no vent, because it is not a machine. It has connections, and
    the only thing the drawing says about one is which side of the box it is on.

    .. code-block:: python

        rx = fs.add(units.Block("Reaction", inputs=["W", "W", "N"], outputs=["E", "S"]))
        fs.connect(feed.outlet, rx.in_1)      # west
        fs.connect(recycle.out_1, rx.in_3)    # north
        fs.connect(rx.out_2, drain.inlet)     # south

    ``inputs`` and ``outputs`` are **one face per connection**, in order, and a
    plain count is the shorthand for the common case: ``inputs=3`` is three on
    the west, ``outputs=2`` two on the east. The nozzles are ``in_1`` ...
    ``in_n`` and ``out_1`` ... ``out_m`` in that order, numbered across the whole
    family rather than per face.

    Those two arguments are named for what they *declare*, and the accessors are
    named for what they *return*: :attr:`inlets` and :attr:`outlets` are the
    connections, :attr:`input_faces` and :attr:`output_faces` the sides they are
    on. The constructor keeps ``inputs=``/``outputs=`` because "the inputs are
    on these faces" is what the argument says.

    **Pin a block flow diagram.** The layout engine ranks units by flow order
    and has no notion that a connection on the north wants its source *above*,
    so a BFD left to lay itself out routes those streams up and over the sheet:
    long climbs, runs closer together than the pitch this class is careful to
    keep at the nozzle, and line jumps where there should be none. That is a gap
    in :mod:`pandid.layout` rather than in this class -- issue #168 -- but a
    block is what makes north and south connections ordinary, so it is what
    meets the gap first. ``examples/12_block_flow_diagram.py`` is a worked,
    pinned sheet to start from.

    **A face names the box's own side, not the reader's.** ``"N"`` is the top of
    the block as declared; a :meth:`pin` that turns or mirrors it moves the box
    and every connection with it, so that same connection is drawn on the east
    of a block turned a quarter. This is where :meth:`nozzle` differs from
    :meth:`Unit.nozzle`, which takes the compass point on the finished sheet,
    and :meth:`nozzle` says why. :func:`pandid.portgeom.port_faces` is what
    answers about the finished sheet.

    **Why the face is declared and not named into the port.** The alternative
    was ``in_w_1`` / ``in_n_1``, one numbered family per face, which is what a
    :class:`~pandid.render.symbols.PortSeries` could have placed without any new
    machinery. It was rejected because it puts a *placement* inside an
    *identity*: nowhere else in this library does the name of a thing record
    where it was drawn -- :meth:`~Unit.pin` and :meth:`~Unit.nozzle` are both
    separate from the name for exactly that reason -- and a connection moved to
    another face would have had to be renamed, breaking every line that referred
    to it. The cost of the choice is real and is paid in
    :func:`~pandid.render.symbols.block_symbol`: one series cannot produce
    ``in_3`` on a face its ``in_1`` is not on, so the symbol authors an anchor
    per connection instead, and only the *spreading rule*
    (:func:`~pandid.render.symbols.spread`) is shared with the series.

    **The box sizes itself to what it carries.** A block flow diagram's box is
    precisely the thing that gathers many streams, and a family squeezed to fit
    a fixed box draws arrowheads that touch and read as one blob. So the height
    follows the west and east counts and the width follows the north and south
    ones, at a pitch derived from the arrowhead the renderer actually draws
    (:data:`~pandid.render.symbols.BLOCK_PITCH`): eight inputs on one wall make a
    *taller block*, not eight crushed nozzles. The width also clears the name,
    which a BFD letters inside the box.

    ``width``/``height`` still win where they are given, as everywhere else, and
    a box too small to draw the connections at that pitch is **refused** rather
    than drawn crushed -- the same answer :class:`Conveyor` gives a belt run its
    rollers do not fit in, and refused wherever it is asked for: the
    constructor, a later assignment, :meth:`nozzle` and :meth:`pin`, the last of
    which is where a quarter turn can put a run on the shorter axis.

    A width the author gave also wins over the name, which then hangs out of
    both ends of the box. The name is written on an opaque halo, as every label
    here is, so an overhanging one **erases whatever is drawn beside it** rather
    than merely looking untidy. Leave ``width`` off and it cannot happen.

    **Variants**: none. A block is a block, and there is nothing about a section
    of plant for a second drawing to say.
    """

    # No *individual* nozzle annotation, and unlike :class:`Mixer` not even one.
    # Every connection a block has is one of the two families, whose size is the
    # caller's and chosen per instance, so the set of attribute names is a
    # property of the *object*: ``in_1: Port`` would be right for a block with
    # an input and wrong for ``Block("B", inputs=0, outputs=2)``, which is a
    # legitimate thing to draw at the edge of a sheet. Mixer's comment argues
    # the general case at length; the difference here is only that a block has
    # no fixed nozzle left over to declare, since a section of plant has no
    # connection every section has.
    #
    # So both of these are families and neither is empty of meaning: a block is
    # the one class whose *whole* connection list is declared as sequences, and
    # ``for inlet in rx.inlets`` is how a BFD is read. Either may be the
    # empty tuple, which is what ``inputs=0`` draws at the edge of a sheet.
    #
    # ``tests/test_port_annotations.py`` pins the five classes that declare a
    # family in ``_DECLARED_FAMILIES``, so adding a sixth is a decision somebody
    # makes rather than one that happens.
    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]

    kind = "block"

    #: The face a connection is put on when the author gives a count rather than
    #: a list. West in and east on out, which is the direction the rest of the
    #: library draws a sheet in and the direction a reader scans one.
    DEFAULT_INPUT_FACE = "W"
    DEFAULT_OUTPUT_FACE = "E"

    # Class-level backing for the two properties below, so ``Unit.__init__``'s
    # ``self.width = width`` has somewhere to land before this class has built
    # anything of its own.
    _width: float | None = None
    _height: float | None = None

    def __init__(self, name: str, inputs: "int | Sequence[str]" = 1,
                 outputs: "int | Sequence[str]" = 1, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        in_faces = _block_faces(inputs, self.DEFAULT_INPUT_FACE, name, "inputs")
        out_faces = _block_faces(outputs, self.DEFAULT_OUTPUT_FACE, name, "outputs")
        if not in_faces and not out_faces:
            raise ValueError(
                f"{name}: a block with no connections is a rectangle with a word "
                f"in it, which nothing can be routed to. Give it at least one "
                f"inputs= or outputs=."
            )
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        #: connection name -> the face it leaves from, in port order. The single
        #: authority: the symbol is built from it, so there is no second place a
        #: face could be recorded and disagree.
        self._faces: dict[str, str] = {}
        self.inlets = tuple(self._add_connection(f"in_{i}", "inlet", face)
                            for i, face in enumerate(in_faces, start=1))
        self.outlets = tuple(self._add_connection(f"out_{i}", "outlet", face)
                             for i, face in enumerate(out_faces, start=1))
        # Check the drawing now, so a box that cannot hold the connections is
        # refused on the line that asked for it rather than at the first render.
        self._check_box()

    def _add_connection(self, name: str, direction: str, face: str) -> Port:
        """One connection: the nozzle, and the side of the box it leaves from.

        The two are laid down together because they are one declaration -- a
        block's connection *is* a name and a face, and nothing else -- so there
        is no window in which :attr:`_faces` and ``ports`` disagree, and the
        family tuples above are what this hands back rather than a second scan
        of the dict looking for names shaped like ``in_1``.

        The nozzle first, so a name :meth:`~Unit._add_port` refuses cannot leave
        a face recorded for a connection that does not exist.
        """
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    @property
    def width(self) -> float | None:
        """The drawn box's width, or ``None`` to size it to the connections.

        A property, unlike every other unit's plain attribute, for the reason
        :attr:`Conveyor.length` is one: the size and the drawing are the same
        question here, so a size the drawing cannot be made at has to be refused
        where it is set. Assigning one that crushes a run of connections raises
        and leaves the block at the size it had.
        """
        return self._width

    @width.setter
    def width(self, value: float | None) -> None:
        self._resize("_width", value)

    @property
    def height(self) -> float | None:
        """The drawn box's height, or ``None`` to size it to the connections."""
        return self._height

    @height.setter
    def height(self, value: float | None) -> None:
        self._resize("_height", value)

    def _resize(self, attr: str, value: float | None) -> None:
        """Take a new box dimension, or refuse it and leave the old one."""
        was = getattr(self, attr)
        setattr(self, attr, value)
        # ``Unit.__init__`` sets both of these before this class has declared a
        # connection, and a block with no connections has nothing to crush. The
        # constructor checks once at the end, when there is something to check.
        if "_faces" not in self.__dict__:
            return
        try:
            self._check_box()
        except ValueError:
            setattr(self, attr, was)
            raise

    def pin(
        self,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = _UNCHANGED,
        mirrored: bool | str = _UNCHANGED,
        port: str | None = None,
    ) -> "Block":
        """Place the block, re-checking that the placement can still draw it.

        A quarter turn draws the box's upright faces across the sheet, so a
        placement is one of the two things that decide whether a run of
        connections still has room; the other is the size, which
        :attr:`width` guards. :meth:`Unit.pin` already re-checks a ``nozzle()``
        choice for the same reason -- a transform can outrun a guard that only
        ran at construction.

        Raises :class:`ValueError` and leaves the previous placement in place,
        rather than turning the block into something that cannot be drawn.
        """
        was = self.pin_
        super().pin(col=col, row=row, x=x, y=y, orientation=orientation,
                    mirrored=mirrored, port=port)
        try:
            self._check_box()
        except ValueError:
            self.pin_ = was
            raise
        return self

    @property
    def input_faces(self) -> tuple[str, ...]:
        """The face each input leaves from, in ``in_1`` ... ``in_n`` order.

        Compass letters and not connections: ``('W', 'W', 'N')``.
        :attr:`inlets` is the ports, which is what the pair was called before
        0.1.1 -- ``b.inputs`` returned the sides, and any reader of that name
        expects the things themselves. ``Block`` had not been released, so the
        rename is free here and would have been a break a version later. The
        constructor argument keeps its name: ``inputs=['W', 'W', 'N']`` reads
        as "the inputs are on these faces", which is what it means.

        A tuple, like :attr:`inlets` beside it. Every one of these four is a
        *derived view* of :attr:`_faces` and ``ports``, and handing back a list
        invites a caller to append to something that is not the record --
        :meth:`nozzle` is what moves a connection. Immutable is the right
        default for all four, and one type across the set is what stops a reader
        having to remember which two are which.
        """
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """The face each output leaves from, in ``out_1`` ... ``out_m`` order."""
        return tuple(self._faces[port.name] for port in self.outlets)

    def face(self, port_name: str) -> str:
        """Which side of the **box** ``port_name`` is on.

        Not necessarily the side of the *sheet*: a :meth:`pin` that turns or
        mirrors the block moves the box and everything on it, so a connection
        declared ``"N"`` on a block turned a quarter is drawn on the east.
        :func:`pandid.portgeom.port_faces` is the one that answers about the
        finished sheet, and it is what a caller asking "which way does this
        stream leave" wants.
        """
        try:
            return self._faces[port_name]
        except KeyError:
            raise KeyError(
                f"Block {self.name!r} has no connection named {port_name!r}; "
                f"available: {sorted(self.ports)}"
            ) from None

    def nozzle(self, port_name: str, face: str) -> "Block":
        """Move a connection to another side of the box.

        It differs from :meth:`Unit.nozzle` in two ways, and both are worth
        stating because the base method's contract is the opposite of this one
        on the first of them.

        **``face`` names the box's own side, not the reader's.**
        :meth:`Unit.nozzle` takes the compass point on the finished sheet, so a
        mirrored pump's ``"W"`` is the west the reader sees. It can afford to,
        because it picks between placements a symbol authored in advance and can
        map the reader's face back onto one of them. Here the face *is* the
        declaration the drawing is built from, and a declaration cannot be about
        a transform that has not been applied yet -- :meth:`pin` may come after
        this call, and may come twice. So a block's connections are declared on
        the box, and a turn or a mirror moves the box and everything on it:
        ``"N"`` on a block turned a quarter is drawn on the east. Ask
        :func:`pandid.portgeom.port_faces` what a connection comes out of on the
        finished sheet; it reports correctly for a block, as it does for
        everything else.

        **It always succeeds.** Every other symbol is artwork drawn in advance,
        so a nozzle may only be moved to a face the drawing anchored one on, and
        a column's bottoms draw offers exactly one because gravity does. A block
        is a rectangle built from its own declaration, so moving a connection is
        *changing that declaration* and redrawing, and every side is a side the
        box has.

        It therefore writes :attr:`_faces` and not ``Unit._port_faces``: the
        latter is an override of a placement the symbol authored, and here there
        is nothing to override -- the declaration is the placement. Keeping one
        record is what stops a block from carrying two answers about one nozzle,
        and it is what makes ``to_dict`` able to write the block back out as the
        constructor call that would rebuild it.

        Raises :class:`ValueError` if the move would squeeze the connections on
        the destination side closer than the pitch the placed box leaves room
        for, and leaves the block untouched when it does.
        """
        if port_name not in self.ports:
            raise KeyError(
                f"Block {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        was = self._faces[port_name]
        self._faces[port_name] = _block_face(face, self.name)
        try:
            self._check_box()
        except ValueError:
            self._faces[port_name] = was
            raise
        return self

    def ports_on(self, face: str) -> tuple[Port, ...]:
        """The connections on one side of the box, in the order they are drawn.

        Along the face, first to last, in the direction :meth:`order_on`
        describes: the west end of a north or south face, the north end of a
        west or east one. Until :meth:`order_on` is called that is the order the
        connections were declared in, inputs before outputs, so the two readings
        coincide on a block nobody has reordered.

        The lookup :meth:`face` does not do. A block is the one unit whose
        nozzles are grouped by side rather than named for what they are, so
        "what comes in on the north" is a question a caller has, and answering it
        by filtering :attr:`_faces` in three places is how the three answers come
        to disagree.

        The **ports**, and a tuple, so this is a third way of asking for a family
        and not a different kind of answer. It returned names before 0.1.1,
        which put a caller through ``[b.port(n) for n in b.ports_on("N")]`` --
        a round trip out to a string and back through the very dict
        :attr:`inlets` and :attr:`outlets` exist to spare them, under a name
        that says "ports". Renamed here rather than deferred because
        :attr:`input_faces` is renamed for exactly that reason and ``Block`` is
        one unreleased class: the free window closes on both at the same moment.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    # The writer beside ``ports_on``'s reader, and the four decisions in it.
    #
    # **Why there is one at all.** A face carrying both an input and an output
    # draws every input before every output, because ``_faces`` is filled
    # inputs-first in ``__init__`` and ``block_symbol`` groups it in insertion
    # order. That is a defensible *default* -- something has to be first, and
    # "as declared" is the only answer that does not invent a rule -- but it was
    # the only order obtainable, which made a common BFD drawing inexpressible:
    # a recycle returning from the right into a face whose other member is a
    # purge has to enter on the right, or it reaches across the purge's drop to
    # get to its own nozzle. Issue #192, and ``examples/12`` is the sheet.
    #
    # **Why a method and not a constructor argument.** The obvious alternative
    # was to say it where the faces are said, ``inputs=["W", ("S", 1)]``, and it
    # fails on three counts. The declaration's whole vocabulary is *which side*,
    # and an index along the side is a fact about the drawing, so the tuple form
    # puts two unrelated kinds of thing in one list and gives ``inputs=`` the
    # type ``Sequence[str | tuple[str, int]]`` -- which a reader must now
    # destructure to answer "which face is in_2 on". The index also counts from
    # a base that does not exist yet: at the moment ``inputs=`` is read the
    # outputs have not been declared, so ``("S", 1)`` is an index into a face
    # whose membership is still being decided, and adding an output later
    # silently re-seats it. And at construction time there are no
    # :class:`~pandid.ports.Port` objects yet -- the constructor is what makes
    # them -- so a constructor-side ordering can only name connections as
    # strings. That last one is decisive: see below.
    #
    # **Why it takes the ports and not their names.** ``ports_on`` returned
    # names until 0.1.1 and was changed to return ports precisely so a caller
    # would stop round-tripping out to a string and back through ``port()``; a
    # writer put beside it that took the strings back would undo that decision
    # from the other side. Taking ports also makes the reversal of a face one
    # expression -- ``b.order_on("S", b.ports_on("S")[::-1])`` -- because the
    # writer accepts exactly what the reader hands back, which is the property
    # that makes a reader/writer pair worth having. And this package ships
    # ``py.typed``: ``Sequence[Port]`` is checked where the author writes it,
    # while a ``Sequence[str]`` is a runtime error at best and, for a typo that
    # happens to name another connection, a quietly wrong drawing. Naming the
    # attribute (``b.out_2``) is the spelling on a sheet; ``b.port("out_2")``
    # and ``b.outlets[1]`` are the two that a type checker can also follow, for
    # the reason :class:`Unit`'s hidden ``__getattr__`` gives.
    #
    # **Why the whole face, every time.** Two cheaper shapes were considered.
    # ``nozzle("in_2", "S", at=1)`` reuses a call the author already knows, but
    # ``at`` is an index into the destination face's membership *at the moment
    # of the call*, so two ``nozzle`` calls onto one face give different
    # drawings in different orders, and an author who adds a connection a year
    # later finds the old ``at=1`` now means something else. It is also a
    # block-only argument hung on the one method whose contract this class
    # already spends a docstring separating from ``Unit.nozzle``'s. A partial
    # list (``order_on("S", [out_2])``, "put this one first") needs a stated
    # rule for the members it does not name, which is a second rule to remember
    # for the sake of a shorter call. Naming every connection on the face is a
    # total statement: it is idempotent, it is order-independent with respect to
    # the calls around it, it reads as the drawing it produces, and the error
    # for an incomplete one can print the current order for the author to copy
    # and edit. One obvious way.
    def order_on(self, face: str, ports: "Sequence[Port]") -> "Block":
        """Set the order the connections on one side of the box are drawn in.

        ``ports`` is **every** connection on ``face``, first to last along it.

        .. code-block:: python

            loop = fs.add(units.Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"]))
            loop.order_on("S", [loop.out_2, loop.in_2])   # purge west, recycle east

        Both ``in_2`` and ``out_2`` are on the south wall, and a block draws
        the connections on a face in the order they were declared -- so inputs
        before outputs, which is not always the order the sheet wants. This is
        what says otherwise, and it is the only thing that does: :meth:`nozzle`
        chooses the *side* and re-declaring a connection onto the side it is
        already on leaves it exactly where it was.

        **First is the low end of the face, on the box's own axes.** West on a
        north or south face, north on a west or east one -- the direction
        :attr:`inlets` is numbered in and the direction
        :func:`~pandid.render.symbols.spread` lays a family out in. It is the
        box's own order and not the reader's, exactly as the face itself is
        (:meth:`nozzle` says why at length): a :meth:`pin` that mirrors the
        block draws the same first member on the *right* of the sheet, because
        a mirror moves the box and everything on it.

        Takes the ports themselves, so the reversal of a face is
        ``b.order_on("S", b.ports_on("S")[::-1])`` -- this is
        :meth:`ports_on`'s writer, and it accepts what that hands back.

        A connection :meth:`nozzle` moves onto the face *afterwards* takes its
        place in declaration order rather than joining the end, because
        ``nozzle`` changes which side a connection is on and says nothing about
        where along it. Order the face once it has the members it is going to
        have, and the call names all of them, which is the point of it.

        Raises :class:`ValueError` for a connection that is not on ``face``, one
        named twice, one belonging to another unit, or a list that leaves any of
        the face's connections unplaced, and leaves the block untouched when it
        does. Naming every one is what keeps the call a statement of the drawing
        rather than a nudge whose result depends on what it was nudging.
        """
        wanted = _block_face(face, self.name)
        on_face = [name for name, on in self._faces.items() if on == wanted]
        named: list[str] = []
        for port in ports:
            if not isinstance(port, Port):
                raise TypeError(
                    f"{self.name}: order_on() takes the connections themselves and "
                    f"not their names, so a checker can see a typo -- "
                    f"order_on({wanted!r}, [b.out_2, b.in_2]), or b.outlets[1] / "
                    f"b.port('out_2') where the attribute cannot be named. "
                    f"Got {port!r}."
                )
            if self.ports.get(port.name) is not port:
                raise ValueError(
                    f"{self.name}: {port.name!r} is a connection of "
                    f"{port.owner.name!r}, not of this block, so it is not on any "
                    f"face of it. order_on() orders one block's own wall; "
                    f"the {wanted} face carries "
                    f"{', '.join(on_face) if on_face else 'nothing'}."
                )
            if self._faces[port.name] != wanted:
                raise ValueError(
                    f"{self.name}: {port.name!r} is on the "
                    f"{self._faces[port.name]} face, not the {wanted}. order_on() "
                    f"orders what is already on a side; move it first with "
                    f"nozzle({port.name!r}, {wanted!r})."
                )
            if port.name in named:
                raise ValueError(
                    f"{self.name}: order_on({wanted!r}, ...) names {port.name!r} "
                    f"twice, so it asks for one connection in two places. Name "
                    f"each of the {wanted} face's connections once: "
                    f"{', '.join(on_face)}."
                )
            named.append(port.name)
        missing = [name for name in on_face if name not in named]
        if missing:
            raise ValueError(
                f"{self.name}: order_on({wanted!r}, ...) names {len(named)} of the "
                f"{len(on_face)} connections on the {wanted} face and leaves "
                f"{', '.join(missing)} unplaced. Name every one, first to last "
                f"along the face; it currently carries {', '.join(on_face)}."
            )
        # Rewritten in place rather than recorded beside ``_faces``, because the
        # dict's order *is* the drawn order -- ``block_symbol`` groups its
        # argument by face and spreads each group by index -- and a second
        # record of where a connection sits is the thing this class keeps saying
        # it will not have. Walking the old dict and swapping in the new
        # sequence as each member of this face comes round leaves every other
        # face's members exactly where they were, so reordering the south does
        # not perturb the north.
        #
        # No ``_check_box()``: this moves connections within a face and changes
        # no face's count, so the box that held them a moment ago still does.
        # It is the one mutator here that cannot make the block undrawable.
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on
            for name, on in self._faces.items()
        }
        return self

    def symbol(self) -> "Symbol":
        """This block's drawing, built to its connections.

        The one place a block's artwork comes from, called by
        :meth:`~pandid.render.symbols.SymbolRegistry.for_unit` on every port
        resolution. It only *builds*: the check that the box can hold what was
        built is :meth:`_check_box`, which has to ask
        :func:`~pandid.portgeom.resolve_size` what the placed box is, and
        ``resolve_size`` asks the registry for this symbol. Checking here would
        close that loop.
        """
        from pandid.render.symbols import block_symbol

        # The name widens the box only where the author left the width open;
        # see block_symbol(). Asking for it with a width already given would
        # make the drawing depend on the tag for no visible reason, and would
        # cost every block its own <defs> entry.
        return block_symbol(tuple(self._faces.items()),
                            "" if self.width is not None else self.tag)

    def _check_box(self, placed=None) -> None:
        """Raise unless the placed box can draw the connections at the pitch.

        Measured against the box the drawing really lands in
        (:func:`~pandid.portgeom.resolve_size`), *including the quarter turn*,
        which is the whole reason this is not a pair of comparisons against
        ``width`` and ``height``. A turn swaps which axis of the box a face's run
        is drawn along while ``resolve_size`` takes an explicit ``width``/
        ``height`` as the final box and does not swap it, so a run that fits the
        height standing up is squeezed into the width lying down. Five inlets in
        a 60 x 150 box turned a quarter came out 12 apart -- exactly one
        arrowhead, five heads touching -- which is the defect this exists to
        prevent, stated about the wrong axis.

        The comparison is against the box the block *sized itself to* rather
        than against the bare run, because the artwork is stretched into
        whatever box it is given: halving the box halves the drawn pitch with
        it, whatever the run alone would have fitted in. An auto-sized block is
        safe at every placement by construction, since ``resolve_size`` swaps
        the symbol's own axes with the turn and the two are then equal.

        ``placed`` is the placement to answer for, defaulting to the unit's own;
        :meth:`pin` passes its candidate, for the reason :meth:`Unit.pin` checks
        a ``nozzle()`` choice against one -- answering about the committed
        placement answers for the sheet this call is replacing.
        """
        from pandid.portgeom import resolve_size
        from pandid.render.symbols import block_box_too_small

        sym = self.symbol()
        if placed is None:
            placed = self.pin_
        w, h = resolve_size(self, placed)
        turned = int(getattr(placed, "orientation", 0) or 0) in (90, 270)
        for face, count in Counter(self._faces.values()).items():
            # One connection on a face has no spacing to crush, so only a run of
            # them is measured.
            if count < 2:
                continue
            upright = face in ("W", "E")
            along = sym.height if upright else sym.width
            # A quarter turn lays the symbol's upright faces across the box and
            # stands its horizontal ones up, so which box axis a run is drawn
            # along is the two questions XOR'd.
            drawn, axis = (w, "width") if upright == turned else (h, "height")
            if drawn < along - 1e-9:
                raise block_box_too_small(self.name, face, count, axis, drawn,
                                          along, turned=turned)
