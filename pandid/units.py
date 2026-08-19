"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute
``PORTS`` (a list of ``(name, direction, role)`` tuples), or, for
variable-port units, by adding ports in ``__init__``. Ports are exposed
both as a ``ports`` dict and as attributes (``pump.suction``), which
each subclass also annotates (``suction: Port``) so an editor and a type
checker can see them.

A unit whose nozzle count the caller chooses declares the *family*
instead: ``mixer.inlets``, ``splitter.outlets``,
``block.inlets``/``outlets`` and ``column``/``reactor.feeds`` are
``tuple[Port, ...]`` in declaration order. The numbered attributes
(``mixer.in_3``) and ``port("in_3")`` work as well.

This module is also the public ``units`` namespace:
``from pandid import units``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

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
    "HeatExchanger", "Heater", "Cooler", "CoolingTower", "Reactor", "Separator",
    "Absorber", "Stripper", "Column",
    "Mixer", "Splitter", "Tee", "Reducer", "Fitting", "Ejector", "Vent", "Funnel",
    "Furnace", "Boiler", "Stack", "Flare", "Turbine", "Filter", "Dryer",
    "CrushingMachine", "Crusher", "Mill", "Centrifuge", "Conveyor", "Elevator",
    "Feeder", "SprayNozzle", "ScreeningDevice", "Kneader",
    "Instrument", "Block",
]

# Only a signal port may carry a signal line and only a process one may
# carry fluid; Flowsheet.connect enforces the pairing.
_VALID_ROLES = {"process", "feed", "product", "energy", "utility", "vapor",
                "liquid", "signal"}

# The side vocabulary label_pos uses, mapped onto compass faces.
_FACE_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}

# "not supplied", for pin() arguments whose falsy value is a real
# request: ``orientation=0`` and ``mirrored=False`` mean "put it back".
_UNCHANGED: Any = object()

#: Not stated is not the same as stated empty. A ``Reactor`` left alone
#: is a stirred tank and gets its agitator; one told ``agitator=None`` is
#: a bare shell somebody asked for on purpose. Every composition keyword
#: with a non-empty default tells the two apart this way, and so does
#: :meth:`Unit.pin`'s ``port``, where a flag names its own nozzle when
#: the caller says nothing and ``None`` asks for the corner regardless.
_UNSTATED: Any = object()

# What the chainable placement methods hand back: the class they were
# called on, so a plain ``-> Unit`` does not throw the subclass away
# mid-chain in ``fs.add(units.HeatExchanger("E-1")).pin(x=210)``.
_UnitT = TypeVar("_UnitT", bound="Unit")

# The facts about a unit that the layout engine and the router read:
# write one and the box moves, changes size, or puts its nozzles
# somewhere else. ``Unit.__setattr__`` marks the sheet's geometry stale
# when one is assigned, which is the only way to catch a PLAIN
# assignment -- a method can call the hook itself, ``pump.width = 90``
# cannot -- and the sheet's cached frames and routes are only sound
# while none of these has moved under them. See
# ``Flowsheet.__init__``'s note on the two staleness flags.
#
# The private names are the backing fields of the properties that guard
# these facts (``Block.width``, ``Conveyor.length`` and
# ``Conveyor.diameter``, ``Reducer.large_end``,
# ``_NormallyPositioned.normal_position``),
# listed here rather than hooked one setter at a time so there is a
# single list to read and to add to. Each reaches the geometry through
# ``SymbolRegistry.for_unit``, which hands back a DIFFERENT symbol --
# its own box, its own nozzle coordinates -- for a conveyor of another
# length, an expansion rather than a reduction, or a blind drawn shut.
#
# ``name`` is here because it is the tag that gets drawn, and the router
# treats a label as an obstacle sized from it (see
# ``pandid.routing.visibility``); renaming a unit moves the lines around
# it.
#
# Deliberately absent: ``description``, ``reference`` and an
# instrument's ``quadrants``, which are lettering the renderer lays out
# afresh on every drawing and so can never be stale; and ``frame`` and
# ``_slot``, which are the engine's own output -- listing those would
# have every layout run end by declaring itself out of date.
_LAYOUT_INPUTS = frozenset({
    "name", "variant", "label_pos", "pin_",
    "width", "height", "_width", "_height",
    "_length", "_diameter", "_large_end", "_normal_position",
})


class Unit:
    #: The equipment type this unit is drawn as: the key the symbol
    #: registry is looked up by, and the tag a spec's ``kind:`` names.
    kind: str = "unit"
    #: The unit's nozzles, one ``(name, direction, role)`` tuple each:
    #: the name a stream is connected by, ``"inlet"`` or ``"outlet"``,
    #: and one of :data:`_VALID_ROLES`. Read once at construction, so
    #: the nearest declaration in the class hierarchy is the whole list.
    #: A unit whose nozzle count the caller decides adds its ports in
    #: ``__init__``.
    PORTS: list[tuple[str, str, str]] = []

    #: The drawings this class owns, class-local name first. Empty means
    #: "every variant the registry has for this kind", checked at
    #: render; a class that names some refuses the rest at construction.
    #:
    #: ``variant`` defaults to ``"default"``, so a class that names its
    #: variants and leaves that one out refuses to be built by name
    #: alone. List ``"default"`` and alias it where naming the class
    #: should ask for the class's own drawing.
    VARIANTS: tuple[str, ...] = ()
    #: class-local variant name -> the registry's, where a class renames
    #: one. ``self.variant`` stores the *result*, so what a unit carries
    #: is the registry's spelling -- which is what the symbol registry
    #: and :mod:`pandid.portgeom` look the artwork up by.
    #:
    #: :meth:`pandid.flowsheet.Flowsheet.to_dict` therefore writes the
    #: registry name, so a sheet written out and read back has lost the
    #: rename. Where that round trip matters, list **both** spellings in
    #: :attr:`VARIANTS`, class-local first.
    VARIANT_ALIASES: dict[str, str] = {}

    #: nozzle name -> the name the *symbol* anchors it under, where a
    #: class calls one of its drawing's nozzles something else. A
    #: symbol's ``ports`` dict is keyed by name, so without this the
    #: artwork answers with its fallback, the centre of the box, and two
    #: renamed draws land on one point.
    #:
    #: Declaring both names on the symbol instead is what
    #: :meth:`pandid.render.symbols.Symbol.coincident_ports` reports as
    #: a fault, since a symbol cannot tell a rename from two nozzles
    #: drawn on top of each other.
    #:
    #: Only names known when the class is written fit here.
    #: :meth:`_symbol_anchor` is the reader, and :class:`Instrument`
    #: overrides it because it mints nozzles per signal connection.
    PORT_ANCHORS: dict[str, str] = {}

    #: The composition keywords this class takes, each mapped to what it
    #: means when the author states none. ``variant=`` chooses the
    #: **body**; these choose the ISO 10628-2 supplementary parts drawn
    #: in it, so a class that composes lists one entry per keyword and a
    #: class that does not leaves this empty.
    #:
    #: **One declaration, read by everything that has to enumerate
    #: them**: the constructor below, and both directions of
    #: :mod:`pandid.spec`. That is the whole point of it. The keywords
    #: shipped with the spec format knowing nothing about them, so
    #: ``to_dict`` wrote none of them and ``from_dict`` put the class's
    #: own part back in their place -- a different drawing, drawn without
    #: complaint, with both directions agreeing that nothing had been
    #: lost. A list restated in the serializer is what let that happen,
    #: so there is no list to restate.
    #:
    #: A default of :data:`_UNSTATED` means the class works the answer
    #: out from the body and from the parts the author *did* name;
    #: :meth:`composition_defaults` is where it does, and is what a
    #: serializer asks rather than this.
    COMPOSITION: dict[str, Any] = {}

    #: The composition keyword this class folds into :attr:`variant`,
    #: where it has one. ``Separator(characteristic="gravity")`` carries
    #: ``variant == "gravity"`` afterwards, because the mark inside a
    #: separating vessel *is* which drawing it is.
    #:
    #: Named here so a serializer can write the keyword the author typed
    #: rather than the variant it folded to. The two are not
    #: interchangeable on the way back in: the variant spelling is
    #: deprecated, so a sheet written through it warns today and is
    #: refused at 0.2.0. See :func:`pandid.spec._write_composition`.
    COMPOSITION_VARIANT: str = ""

    #: The layout engine's solver scratch, seeded from :attr:`pin_` at
    #: the start of every run by ``pandid.layout._seed_slots`` and read
    #: by nothing outside that package. Declared rather than initialised
    #: because a unit that has never been laid out has no slot, which
    #: the engine's ``assert u._slot is not None`` lines rely on.
    _slot: _Slot | None

    # The bare ``suction: Port`` annotations on the subclasses below
    # declare what ``PORTS`` produces. The ports themselves are built by
    # ``_add_port``, whose ``setattr`` no type checker can follow, so
    # without them ``pump.suction`` is invisible to mypy and to editor
    # completion. An annotation with no assignment binds nothing, so
    # nothing about construction or the drawn sheet changes;
    # ``tests/test_port_annotations.py`` holds the two halves together.

    @classmethod
    def _declared_ports(cls) -> list[tuple[str, str, str]]:
        """The ports this class declares.

        The nearest class in the MRO to name :attr:`PORTS` answers for
        the whole list, empty or not: overriding a declaration replaces
        it.
        """
        for klass in cls.__mro__:
            if "PORTS" in klass.__dict__:
                return list(klass.__dict__["PORTS"])
        return []

    @classmethod
    def composition_defaults(cls, variant: str,
                             stated: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """What each composition keyword means on *variant*, unstated.

        :attr:`COMPOSITION` as it stands, for a class whose defaults are
        the same whichever body is drawn. A class whose defaults depend
        on the body overrides this and **its constructor asks here**
        rather than working the answer out for itself, so the rule is
        written once and a serializer reading it back gets the same
        answer the constructor did.

        *stated* is every composition keyword's value as it stands --
        what the author named, where the constructor is asking, and what
        the unit ended up carrying, where a serializer is. The two are
        the same value for any keyword whose own default does not depend
        on a sibling, which is every keyword read through here. It
        exists because one part can rule another out: a reactor the
        author has put internals in is not a stirred tank, so its
        agitator default is *no agitator*, and that is a fact about the
        keywords together rather than about the body.

        Never returns :data:`_UNSTATED`: a class that declares one owes
        an override that resolves it.
        """
        return dict(cls.COMPOSITION)

    @classmethod
    def _generic_class(cls) -> type["Unit"] | None:
        """The ancestor owning this class's whole kind, else ``None``.

        The nearest ancestor declaring an empty :attr:`VARIANTS` and the
        same :attr:`kind`. That class draws every variant the registry
        has, so it is the escape hatch a refused variant names. The kind
        must match: ``Unit`` itself draws a generic box under
        ``kind = "unit"`` and is not an escape hatch for anything.
        """
        for klass in cls.__mro__:
            if issubclass(klass, Unit) and not klass.VARIANTS and klass.kind == cls.kind:
                return klass
        return None

    @classmethod
    def _unknown_variant(cls, name: str, variant: str) -> ValueError:
        """The error a class raises for a drawing it does not own.

        Returned rather than raised, as
        :func:`pandid.portgeom.unreachable_face` is, so the traceback
        starts at the constructor the author called. It names the
        low-level form, since the drawing does exist and the author
        needs a call that reaches it.
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
        # The registry's spelling, never the class-local one; see
        # :attr:`VARIANT_ALIASES`.
        self.variant = self.VARIANT_ALIASES.get(variant, variant)
        self.width = width
        self.height = height
        self.label_pos = label_pos
        # Free-text equipment description (used by the auto equipment
        # list).
        self.description = description
        # Off-page reference for boundary flags (Feed/Product): the
        # drawing this stream comes from or goes to, drawn as the
        # connector's second line. Nothing else has anywhere to draw it.
        if reference and self.kind not in ("feed", "product"):
            raise ValueError(
                f"{name}: reference= names the drawing an off-page connector "
                f"continues onto, and a {type(self).__name__} is drawn as equipment. "
                f"Put it on the Feed or Product where the line crosses the sheet edge."
            )
        self.reference = reference
        #: The balloon this item's tag is drawn in, if it has one; set
        #: only by :meth:`pandid.flowsheet.Flowsheet.add_balloon`. A
        #: primary element with a balloon draws no lettering of its own,
        #: because the two marks share one tag: see :attr:`tag`.
        self.balloon: "Instrument | None" = None
        self.flowsheet: Flowsheet | None = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        self._new_line_number = False
        self.pin_: Pin | None = None      # intent; set only via pin()
        self.frame: Frame | None = None   # resolved; set only by layout
        self._port_faces: dict[str, str] = {}   # port name -> face
        for spec in self._declared_ports():
            self._add_port(*spec)

    def _invalidate_layout(self) -> None:
        """Tell the sheet this unit is on that its geometry is stale.

        The unit-side half of
        :meth:`pandid.flowsheet.Flowsheet._invalidate_layout`, where the
        invariant is written down: a resolved frame or route is kept and
        reused, so every change that could move one has to say so.

        A unit on no flowsheet has nobody to tell, and needs nobody:
        :meth:`~pandid.flowsheet.Flowsheet.add` marks the sheet stale as
        it takes the unit, which accounts for everything set on the way
        to that call.

        ``getattr`` with a default rather than ``self.flowsheet``:
        :meth:`__setattr__` fires on the first line of ``__init__``,
        well before there is a ``flowsheet`` attribute to read.
        """
        fs = getattr(self, "flowsheet", None)
        if fs is not None:
            fs._invalidate_layout()

    def __setattr__(self, name: str, value: Any) -> None:
        """Assign, and mark the sheet stale for a fact layout reads.

        Which facts those are, and why an assignment rather than a
        method has to be watched for at all, is :data:`_LAYOUT_INPUTS`.
        Everything else is set at full speed.
        """
        super().__setattr__(name, value)
        if name in _LAYOUT_INPUTS:
            self._invalidate_layout()

    @property
    def tag(self) -> str:
        """The tag drawn against this unit.

        For equipment the tag *is* the name the flowsheet knows it by.
        Only a symbol drawn in several places tells the two apart; see
        :attr:`Instrument.tag` and :attr:`_Boundary.tag`.

        Empty once :attr:`balloon` holds it. One tag is drawn once, and
        every backend already writes nothing against a symbol whose tag
        is empty, so moving it is the whole of what a primary element's
        balloon does to the element.
        """
        return "" if self.balloon is not None else self.name

    def repeats(self, other: "Unit") -> bool:
        """Whether this unit is *another drawing of* ``other``.

        False for every piece of equipment: two units answering to
        ``P-101`` are two pumps sharing a tag. Overridden by the symbols
        that stand for one thing shown in several places
        (:meth:`Instrument.repeats`, :meth:`_Boundary.repeats`) and by
        the one that draws no tag at all (:meth:`Tee.repeats`).
        """
        return False

    @property
    def new_line_number(self) -> bool:
        """Whether the line identifier breaks across this fitting.

        On a valve, reducer or fitting, True breaks the stream number
        (or the line number, where the line has one) across the unit
        instead of carrying it through, which is where a spec break
        goes.

        Setting it renumbers the flowsheet, so the names on the stream
        objects the caller already holds stay the names that get drawn.
        """
        return self._new_line_number

    @new_line_number.setter
    def new_line_number(self, value: bool) -> None:
        self._new_line_number = value
        if self.flowsheet is not None:
            # Renumbering rewrites the names of every run that passed
            # through this fitting, and a name is drawn -- so the sheet
            # that comes out next has to be laid out and routed for the
            # labels it now carries, not the ones it had.
            self.flowsheet._invalidate_layout()
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
        port: str | None = _UNSTATED,
    ) -> _UnitT:
        """Pin the unit to a grid cell or an exact pixel coordinate.

        Records *intent* only. The layout engine reads it and resolves
        the final :class:`~pandid.geometry.Frame`; pinned axes are
        honored exactly.

        ``orientation`` is a clockwise quarter turn in degrees
        (0/90/180/270); a quarter turn swaps the unit's width and
        height. ``mirrored`` flips the symbol: ``True`` or ``"x"``
        left/right (swapping its E and W faces), ``"y"`` top/bottom
        (swapping N and S), ``"xy"`` both.

        ``port`` names a nozzle, and the coordinates then locate **that
        nozzle** rather than the unit's top-left corner, so
        ``valve.pin(port="inlet", y=run_y)`` puts a valve on a run
        without writing down half its height. Only the axes this call
        names are read that way, so
        ``pin(x=..., port="inlet", y=run_y)`` steps along a row by the
        corner and still lands the nozzle on the line. A grid cell has
        no nozzle in it, so a ``port`` you *name* refuses ``col``/
        ``row``.

        **On a** :class:`Feed` **or a** :class:`Product` **the nozzle is
        the default**, so ``x``/``y`` place the tip of the flag and
        ``pin(port=...)`` is only ever a way of writing that down. This
        is the one place in the library where ``pin`` means two things:
        every other unit is a box whose corner is somewhere on it, while
        a flag's corner is a coordinate with nothing drawn at it that
        moves as its label grows (see
        :func:`pandid.portgeom.unit_box`). Pass ``port=None`` to place
        that corner anyway -- which is what a placement read back off a
        resolved :class:`~pandid.geometry.Pin` wants.

        Every argument is optional and an omitted one leaves that part
        of the placement as it stands, so a second ``pin(y=...)`` keeps
        the turn and the flip the first call asked for. Pass
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
        if port is _UNSTATED:
            # A flag stands for the line, not for a piece of plant, and
            # it has exactly one nozzle -- so the point worth naming is
            # where the line leaves, and naming it costs a caller the
            # ceremony of spelling out the only port there is. Nothing
            # else defaults: a box's corner is on the box.
            port = next(iter(self.ports)) if isinstance(self, _Boundary) else None
        elif port is not None and (col is not None or row is not None):
            # Only for a port this call *named*: the default above must
            # leave a flag pinned to a grid cell alone rather than
            # refusing a placement the caller wrote nothing wrong in.
            raise ValueError(
                f"{self.name}: pin(port=...) reads x/y as the position of a "
                f"nozzle, and col/row name a grid cell, which has no nozzle in "
                f"it. Give x/y, or drop port="
            )
        if port is not None:
            # After the transform, never before: a mirror moves the
            # nozzle within the box, so an offset taken from the
            # placement this call replaces puts the device half a body
            # off its run.
            self._offset_to_port(candidate, port, x, y)
        # Check the *candidate*: the committed placement answers for the
        # sheet this call is replacing, and committing first would leave
        # the unit in the state a raise here exists to prevent.
        if self._port_faces:
            from pandid.portgeom import port_faces

            for port_name, face in self._port_faces.items():
                self._check_face(port_name, face, port_faces(self, port_name, candidate))
        self.pin_ = candidate
        return self

    def _offset_to_port(self, candidate: Pin, port_name: str,
                        x: float | None, y: float | None) -> None:
        """Re-read a candidate's named axes as one nozzle's position.

        Writes the corner the nozzle asked for back onto the pin, so a
        :class:`~pandid.geometry.Pin` still stores a corner and pinning
        the same nozzle to the same point twice is the same placement
        twice rather than a device walking off its run.
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

        The layout engine otherwise picks between the faces a symbol
        offers, from where the peer landed (:mod:`pandid.layout.faces`);
        this overrides that pick. ``face`` is the compass point on the
        finished sheet (``"N"``/``"S"``/``"E"``/``"W"``, or the
        ``top``/``bottom``/``left``/``right`` spelling ``label_pos``
        uses), so a mirrored unit takes the face the reader sees.

        Raises :class:`KeyError` for an unknown port and
        :class:`ValueError` when the symbol offers no placement on that
        face (a column's bottoms nozzle offers exactly one).

        Because the drawn face depends on the placement transform, a
        later :meth:`pin` that rotates or mirrors the unit re-checks the
        choice and raises if it no longer reaches that face.
        """
        from pandid.portgeom import port_faces

        if port_name not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        face = _FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
        self._check_face(port_name, face, port_faces(self, port_name))
        # Marked by hand: this writes *into* ``_port_faces`` rather than
        # rebinding it, and the assignment ``__setattr__`` watches for
        # is the rebinding kind.
        self._port_faces[port_name] = face
        self._invalidate_layout()
        return self

    def _check_face(self, port_name: str, face: str, options: list[str]) -> None:
        """Raise unless ``face`` is one this port is drawn piped from.

        The message comes from :mod:`pandid.portgeom`, which raises the
        same one at resolve time; this only moves the complaint forward
        to the call that caused it.
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
        """Whether this unit has a second connection like ``port``.

        False for every nozzle of every piece of equipment: a pump has
        one suction. :class:`Instrument`, whose signal connections are a
        pool, is the whole of the exception.

        Asked separately from :meth:`another_port`, which does the
        taking, because :meth:`pandid.flowsheet.Flowsheet.connect` has
        two ends to settle and must not mint on one of them for a call
        it is about to refuse on the other -- a balloon left carrying a
        nozzle no line reaches is a drawing changed by an error, and the
        debug overlay draws it.
        """
        return False

    def another_port(self, port: "Port") -> "Port":
        """A second connection like ``port``.

        Only called where :meth:`has_another_port` is true. ``port``
        itself here, since nothing on this class has a second of
        anything.
        """
        return port

    def _symbol_anchor(self, port_name: str) -> str:
        """The name this unit's *symbol* anchors ``port_name`` under.

        :attr:`PORT_ANCHORS` for every unit whose nozzle list is fixed
        when the class is written. :class:`Instrument` overrides this
        because its signal connections are minted per connection.

        :mod:`pandid.portgeom` asks through here and nowhere else; a
        name the artwork never heard of lands the nozzle on the
        box-centre fallback.
        """
        return type(self).PORT_ANCHORS.get(port_name, port_name)

    def _series_pin(self, port_name: str) -> float | None:
        """Where this unit pins ``port_name`` along its
        :class:`~pandid.render.symbols.PortSeries`' face, as a fraction of
        that face -- or ``None`` to let the series spread it evenly with
        its siblings, which is what every unit does by default.

        :mod:`pandid.portgeom` asks through here before falling back to
        :meth:`~pandid.render.symbols.PortSeries.placement`'s even spread,
        so a unit that knows a *specific* reason one member of its family
        belongs somewhere else on the face can say so without a second
        placement mechanism standing next to the series. Nothing overrides
        this but :class:`Column`, whose ``feed_stages=`` puts a feed on
        the stage it actually enters rather than spreading it with the
        rest.
        """
        return None

    def port(self, name: str) -> Port:
        if name in self.ports:
            return self.ports[name]
        raise KeyError(
            f"{type(self).__name__!r} has no port named {name!r}; "
            f"available ports: {sorted(self.ports)}"
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    # Hidden from type checkers: mypy reads a class that has a
    # ``__getattr__`` as having whatever attribute it is asked for, so
    # leaving it visible answers every ``sep.liqid`` with ``Any`` and
    # the annotations above buy nothing. ``TYPE_CHECKING`` is False at
    # run time, so the method is defined exactly as it always was.
    #
    # The cost is that a checker refuses the variant nozzles that are not
    # on the base class (see :class:`Separator`), and would refuse the
    # numbered members of a family too. The families buy that back
    # without giving anything up: :class:`Mixer`, :class:`Splitter`,
    # :class:`Column` and :class:`Reactor` overload ``__new__`` on a
    # **literal** count and hand back a subclass declaring exactly the
    # nozzles that count builds, so ``mixer.in_3`` resolves and
    # ``mixer.in_4`` does not.
    # :class:`Block` is the one class that cannot be written that way and
    # does take the blanket ``__getattr__``; it says why, and
    # ``tests/test_port_annotations.py`` pins that it is alone.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            # Only invoked when normal lookup fails. Attribute access
            # (reactor.feed) is the primary way to reach ports, so give
            # typos a message listing the real ports.
            ports = self.__dict__.get("ports")
            if ports is not None and not name.startswith("_"):
                raise AttributeError(
                    f"{type(self).__name__} {self.__dict__.get('name', '?')!r} has no "
                    f"attribute or port {name!r}; available ports: {sorted(ports)}"
                )
            raise AttributeError(name)


# ----------------------------------------------------------------
# Fixed-port unit types
# ----------------------------------------------------------------


class _Boundary(Unit):
    """Where the sheet ends: Feed and Product's off-page flag.

    Not a piece of plant. The flag stands for a line crossing the sheet
    edge, and its label identifies the service to the reader.
    ``reference`` is the drawing the line continues onto.

    Being a line and not a box, it is placed by the line: ``pin(x=...,
    y=...)`` puts the flag's *nozzle* there, where the same call puts
    every other unit's top-left corner. See :meth:`Unit.pin`.

    ``header`` says the flag stands for a *utility header* rather than
    for one line: cooling water supply, steam, flare, plant air. A
    header is tapped wherever it is wanted, so it is drawn at each tap
    and labelled the same way every time. See :meth:`repeats`.
    """

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = "", header: bool = False):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        #: One service tapped at several points, rather than one line
        #: crossing the sheet edge once. Opt in, so two flags
        #: accidentally given one name are still caught.
        self.header = bool(header)
        # The drawn label, kept apart from the name because a tapped
        # header needs a name of its own to be addressed by. See
        # :attr:`tag`.
        self._tag = name

    @property
    def tag(self) -> str:
        """The service drawn on the flag (``"CWSH"``).

        Equal to :attr:`~Unit.name` for a flag drawn once. A header
        repeats, so the sheet shows one label several times while the
        flowsheet keeps a distinct name for each tap to address it by
        (``CWSH``, ``CWSH (2)``).
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Whether this flag is another tap of the same header.

        Both ends have to be headers (``header=True``) carrying the same
        label, and to be the *same drawing* of it: same class, so a
        supply and a return sharing a label still clash, and the same
        ``reference``, since two taps of one header continue onto one
        drawing.
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

    ``header=True`` marks the flag as a utility supply header (cooling
    water, steam, plant air), which a sheet taps wherever it needs it
    and labels the same way at every tap. Such a flag may be added more
    than once; see :meth:`_Boundary.repeats`.
    """

    outlet: Port

    kind = "feed"
    PORTS = [("outlet", "outlet", "feed")]


class Product(_Boundary):
    """Boundary condition: a stream sink leaving the flowsheet.

    ``header=True`` marks the flag as a return or collection header
    (cooling water return, condensate, flare), which takes from wherever
    it is tapped and is labelled the same way each time. See
    :meth:`_Boundary.repeats`.
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
    """A unit that carries a ``normal_position``: Valve and Fitting.

    Where the device sits with the plant running. Only a device a line
    can be stopped at has one.

    What a sheet *draws* for it is not shared: a closed valve is the
    open valve with its body darkened (PIP PIC001 4.2.2.7), while a
    closed blind is the other of the two shapes the stencil already had.
    So each subclass says separately which of its variants may be shown
    closed, by overriding :meth:`_refuse_closed`, and
    :func:`pandid.render.symbols.closed_marking` says how each is drawn.
    """

    #: The positions such a unit may be declared in. A tuple rather than
    #: a bool: the designations a P&ID draws are an enumeration (NC
    #: today, the locked and car-sealed ones later).
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
        """``"open"``/``"closed"``: where it sits when running.

        See the owning class's docstring for what each one draws, and
        for the variants that refuse to be shown closed at all.
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

        Refused here rather than at render time, so a position nothing
        on the sheet can state never reaches a drawing.
        """


class Valve(_NormallyPositioned):
    """Control or let-down valve.

    Two questions, asked separately. ``variant`` is the **body** --
    ``"globe"``, ``"ball"``, ``"butterfly"``, ``"gate"`` and the rest.
    The ``actuator`` argument is **what strokes it**: ``"diaphragm"``,
    ``"motor"``, ``"solenoid"``, ``"hydraulic"`` or ``"handwheel"``, and
    unset for a bare body whose operator the drawing does not state.

    ``variant="control"`` is the shorthand for the common pairing:
    general body, diaphragm actuator::

        units.Valve("HV-101", variant="globe")       # plain globe valve
        units.Valve("CV-303", variant="control")     # control valve
        units.Valve("CV-303", variant="gate", actuator="diaphragm")
        units.Valve("CV-303", variant="control", actuator="diaphragm")
        units.Valve("XV-201", variant="butterfly", actuator="diaphragm")
        units.Valve("SV-401", variant="solenoid")   # = its actuator

    Naming a shorthand's own actuator alongside it is allowed. What is
    refused is a disagreement: ``variant="control", actuator="motor"``
    is two operators and one drawing.

    **The stencil set draws pairings, not parts.** Every actuated valve
    draw.io ships is one fused shape, so there is no loose actuator
    glyph to lay over a globe or a ball and a globe body with a
    diaphragm on it is a drawing that does not exist. The pairings that
    do are :data:`pandid.render.symbols.ACTUATED`, and asking for one
    that is not there raises and names them. What is stored is the
    *variant*.

    ``actuator`` is also the name of the **signal connection** on top of
    the valve, the terminus of a control loop. Being a signal port, it
    takes a signal ``kind`` and refuses process fluid.

    ``normal_position`` is where the valve sits with the plant running:
    ``"open"`` (the default) or ``"closed"``. A closed one is drawn with
    its body **darkened solid** (PIP PIC001 clause 4.2.2.7). The rule is
    one-sided: an open valve is not marked at all, so ``"open"`` draws
    what a valve without the argument draws.

    Where the body cannot carry the fill legibly -- a butterfly's disc,
    a check valve's arrow, a knife gate's blade, all of which the fill
    swallows -- clause 4.2.2.8 writes the abbreviation **NC** instead,
    below the valve on a horizontal run and to the right of it on a
    vertical one. Those variants draw the letters.
    :data:`pandid.render.symbols.NC_DARKENS` lists the ones that darken.

    Clause 4.2.2.10, which bars a control valve and a relief valve
    from being shown NC at all, is enforced: a ``control``,
    ``regulator``, ``relief`` or ``psv`` valve raises rather than
    drawing a mark the standard forbids.

    ISA-5.1 has no valve-fill convention, and its clauses 2.8.1(b)(1),
    2.8.2 and 5.2.5 make it mandatory to declare any symbol extending
    the standard on a legend or cover sheet.
    :func:`pandid.document.legend` builds the box; nothing adds the
    entry for you.

    ``variant="three_way"`` carries a third process nozzle, ``branch``,
    where the symbol's own third leg lands. A three-way body both
    diverts (one inlet, two outlets) and mixes (two inlets, one
    outlet), so no direction is right for both jobs; ``branch`` is
    declared ``"outlet"``, the switching/diverting service the drawing
    is already described as -- the one a run is *switched between*, not
    blended into. Reached by name through
    :class:`~pandid.devices.ThreeWayValve`, or as
    ``Valve(variant="three_way").port("branch")`` on the low-level
    form, since it is not annotated here; see :class:`HeatExchanger`
    for why.

    ``fail`` is a **different question**; see :attr:`fail`.
    """

    inlet: Port
    outlet: Port
    actuator: Port

    kind = "valve"
    # Empty because which nozzles a valve has depends on its variant, and
    # Unit.__init__ reads PORTS before a variant is in hand. _VARIANT_PORTS
    # below is the declaration; __init__ lays it down.
    PORTS: list[tuple[str, str, str]] = []
    #: Every variant but ``three_way``: the inlet, the outlet and the
    #: actuator's signal terminal.
    _BASE = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("actuator", "inlet", "signal")]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_BASE`. Only ``three_way`` carries a fourth, ``branch``,
    #: and it is not annotated as a bare ``branch: Port`` on the class
    #: body the way ``inlet``/``outlet``/``actuator`` are: that would say
    #: every valve has one and make a real mistake type-check clean,
    #: which is why :class:`HeatExchanger` keeps ``bottoms`` off its own
    #: base the same way.
    _VARIANT_PORTS = {"three_way": [*_BASE, ("branch", "outlet", "process")]}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._BASE)

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
        # ``self.variant`` rather than the argument; see HeatExchanger.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        self._fail = ""
        self.fail = fail

    def _resolve(self, name: str, variant: str, actuator: str) -> str:
        """The one variant that draws *variant* with *actuator* on it.

        Called before ``super().__init__``, so what the rest of the
        package sees is a variant and nothing else: the renderers, the
        exporter and :mod:`pandid.spec` all read ``self.variant`` and
        none of them learns a second axis. The pair is not stored beside
        it.
        """
        from pandid.render.symbols import ACTUATED, ACTUATORS, actuated_variant

        if not actuator:
            return variant
        if actuator not in ACTUATORS:
            raise ValueError(
                f"{name}: actuator is one of "
                f"{', '.join(repr(a) for a in ACTUATORS)}, got {actuator!r}. It is "
                f"what strokes the valve; what the valve *is* -- the body -- is "
                f"variant."
            )
        # ``control`` and the rest already name a body with an operator
        # on it. Read what that is back out of ACTUATED, so the table
        # stays the one place a pairing is written down: an agreeing
        # actuator resolves to the variant already named, a disagreeing
        # one raises.
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
        """Where the valve goes on loss of energy, ``""`` if unset.

        **This is not** :attr:`~_NormallyPositioned.normal_position`:

        ===================  ===================================
        ``normal_position``  where the valve sits **with the plant
                             running**. Marked by darkening the
                             body, or by ``NC`` beside it.
        ``fail``             where the valve goes **when the air,
                             the hydraulic supply or the power is
                             lost**. Marked by letters beside it.
        ===================  ===================================

        They are independent, and a valve may state either, both or
        neither; nothing infers one from the other. Six positions, given
        as the plant's words and drawn as ISA's letters
        (:data:`pandid.render.symbols.FAIL_POSITIONS`):

        ===================  =========  =============================
        ``fail``             drawn      ANSI/ISA-5.1-2009 Table 5.4.4
        ===================  =========  =============================
        ``"open"``           ``FO``     fail open
        ``"closed"``         ``FC``     fail closed
        ``"last"``           ``FL``     fail last, holding position
        ``"drift_open"``     ``FL/DO``  fail last, then drifting open
        ``"drift_closed"``   ``FL/DC``  fail last, then drifting shut
        ``"indeterminate"``  ``FI``     fail indeterminate
        ===================  =========  =============================

        **Only an actuated valve may declare one.** A hand-operated
        valve has no actuating energy to lose, and a relief valve or
        regulator is worked by the process itself. Those raise; the
        variants that may are
        :data:`pandid.render.symbols.FAIL_ACTUATED`.

        Drawn as letters rather than as stem arrows, which is PIP PIC001
        clause 4.5.3.2's choice between the two ISA-5.1 Table 5.4.4
        methods. See the README's *Standards* section.

        **One position, not two.** PIP PIC001 4.5.3.2(3) wants an
        explanatory note on a valve that fails one way on loss of signal
        and another on loss of motive power. Declare the motive-power
        position here and add the note; nothing writes it for you.
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
                f"{self.name}: PIP PIC001 clause 4.2.2.10 bars a control valve and "
                f"a relief valve from being shown NC, and variant "
                f"{self.variant!r} draws one. A darkened control valve on an issued "
                f"sheet reads as a block valve someone has closed. Say where the "
                f"valve fails instead (fail='closed'), or put the normally closed "
                f"mark on the hand valve that actually isolates the line."
            )


def _compose_onto(unit, *groups) -> None:
    """Set ``unit.overlays`` from the parts its keywords asked for.

    One place, because the four kinds that compose need the same two
    things: the overlays flattened in the order they were asked for, and
    **nothing set at all where nothing was asked for**. The second is
    what keeps a unit that composes nothing indistinguishable from one
    that cannot -- ``SymbolRegistry.for_unit`` reads
    ``getattr(unit, "overlays", ())`` and short-circuits on the empty
    tuple -- and so keeps every drawing nobody asked to change exactly
    where it was.
    """
    overlays = tuple(overlay for group in groups for overlay in group)
    if overlays:
        unit.overlays = overlays


#: The two vessel variants that are a vessel plus an ISO group-26
#: support, and so the two the keyword replaces. ISO group 1 items
#: 1.16-1.19 are this composition drawn out -- one vessel outline and one
#: support each -- and pandid vendored whichever two of the four the
#: stencil set happened to ship, which is why a bracket and a ring were
#: unreachable and now are not.
#:
#: The other eight vessel variants are **not** supports and are not
#: deprecated: a jacket, an insulation band, an electrical heater and a
#: swaged shell are none of them a group-26 element.
#:
#: One module constant each, because that is what
#: :func:`pandid.deprecation.declarations` can enumerate: a declaration
#: built inline, or hidden inside a container, outlives its release
#: quietly. The dict below is only the lookup that finds them.
#:
#: **Both carry a note, because neither is a drop-in.** The support is
#: the same construction either way, but the shell it stands on is not:
#: measured, ``variant='legs'`` and ``variant='skirted'`` are 40 x 122,7
#: on draw.io's "Vessel (Dished Ends)" with the support in the artwork,
#: while ``supports=`` puts the ISO group-26 element under the 62 x 125
#: shell every other vessel keyword draws. A sheet moves at the next
#: render, and an author told only "use X" was not told that.
VESSEL_VARIANT_LEGS = Deprecation(
    what="Vessel(variant='legs')", instead="Vessel(supports='leg')",
    removed_in="0.2.0",
    note="the drawing changes -- a pair of ISO item 26.1 C2005 legs under the "
         "standard vessel shell, where this one has its own drawn in")
VESSEL_VARIANT_SKIRTED = Deprecation(
    what="Vessel(variant='skirted')", instead="Vessel(supports='skirt')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 26.3 C2007's skirt under the standard "
         "vessel shell, where this one has its own drawn in")

_VESSEL_SUPPORT_VARIANTS = {
    "legs": VESSEL_VARIANT_LEGS,
    "skirted": VESSEL_VARIANT_SKIRTED,
}


class Vessel(Unit):
    """Generic pressure vessel: holdup, not phase separation.

    Variants: ``"default"`` and ``"dished"`` stand upright;
    ``"horizontal"`` is a lying cylinder with dished ends, which is how
    a reflux drum, accumulator or knock-out pot is drawn. Use the
    variant rather than rotating an upright vessel: skirts, saddles and
    shell bands do not survive a quarter turn. ISO 15519-1 §11.4.2 says
    the same, and turning one is reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate`.

    Reach for :class:`Separator` instead when the point of the vessel is
    splitting phases and you want to name the vapour and liquid
    products.

    Besides the process pair a vessel has three connections that are not
    what enters and what leaves: ``vent``, the vapour connection off the
    top head; ``relief``, where the protective device sits; and
    ``drain``, the low-point liquid draw. :class:`Tank` carries the same
    five: a tank and a vessel are one shell at two design pressures, and
    the difference between them is drawn rather than declared.

    **Named, and not counted.** Each of the five is positioned by what
    it is for, and a number carries no duty -- CHEE4001 p.7 puts the PSV
    on the protected system itself, upright, discharging upward, at the
    top of the container -- and three interchangeable draws have nothing
    in them that says which is the relief.

    Every one of the ten vessel and seven tank stencils therefore
    anchors a coordinate for each of the five, and
    :func:`pandid.portgeom.is_anchored` is true for every pair. A nozzle
    the symbol never anchored falls back to the centre of the box, where
    any two of them land on each other -- issue #225 is that failure.
    ``scripts/vendor_symbols.py`` holds the seventeen port maps.

    The cost is that a *second* relief is a change to the artwork rather
    than a number. Nothing here is reported by ``nozzle-unconnected``,
    which reads only numbered nozzles; see issue #215 for drawing a
    spare nozzle blanked.

    What it stands on
    -----------------
    ``supports=`` names one of the four ISO 10628-2 group-26 apparatus
    elements and draws it under or against the shell::

        Vessel("D-301", supports="skirt")     # 26.3 C2007
        Vessel("D-302", supports="leg")       # 26.1 C2005, a pair
        Vessel("D-303", supports="bracket")   # 26.2 C2006, a pair
        Vessel("D-304", supports="ring")      # 26.4 C2008, a pair

    That is what ISO group 1 items 1.16 to 1.19 are: one vessel outline
    and one group-26 element each, composed. It works on **every** vessel
    variant, which the two variants it replaces did not -- a jacketed
    vessel could not stand on legs, because ``variant=`` had already been
    spent on the jacket.
    """

    inlet: Port
    outlet: Port
    vent: Port
    # The nozzle a protective device sits on, not the device itself,
    # which is a Valve or Fitting with a tag of its own. A third
    # connection rather than a takeoff off the draw-off, so the relief
    # path is drawn from the vessel and can be seen not to run through
    # anything else; issue #222.
    #
    # ``process`` and not ``vapor``: a relief passes whatever the vessel
    # is full of when it lifts, and the role vocabulary has no word for
    # that.
    relief: Port
    # The low-point liquid draw: a water draw-off, a clean-out, the
    # knocked-out liquid a vapour drum collects. Distinct from
    # ``outlet`` because on nine of the ten vessel drawings ``outlet``
    # is on the shell wall, so without it there is no nozzle at the
    # bottom of a vessel at all.
    drain: Port

    kind = "vessel"
    # Order is observable: ``ports`` is insertion-ordered and a family
    # placed by a :class:`~pandid.render.symbols.PortSeries` is spread
    # in the unit's own port order
    # (:func:`pandid.portgeom._series_point`).
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    #: A vessel stands on nothing unless it is told what it stands on,
    #: whichever shell is drawn: the four group-26 elements go under or
    #: against every one of the ten variants.
    COMPOSITION = {"supports": None}

    def __init__(self, name: str, variant: str = "default",
                 supports: str | None = None,
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # **The argument, not ``self.variant``** -- the opposite of what
        # ``_variant_ports`` a few lines down in HeatExchanger wants, and
        # for the opposite reason. A ports table is keyed the way the
        # *registry* spells a variant, so it has to be read with the
        # spelling :attr:`~Unit.VARIANT_ALIASES` settled on. A
        # deprecation table is keyed by the spelling being **retired**,
        # and the only question it answers is what the author typed.
        #
        # Reading ``self.variant`` here asks the second question with the
        # first one's answer, and a convenience class is where the two
        # come apart: ``GravitySeparator("V-1")`` aliases ``default`` to
        # ``gravity`` and so was told off for a word it did not write and
        # a rewrite it cannot make. Nothing aliases into a retired
        # *support* today, so this line is a correction rather than a
        # behaviour change -- but it is the same line, and leaving it
        # right side up is what stops the next alias reintroducing it.
        if variant in _VESSEL_SUPPORT_VARIANTS:
            _VESSEL_SUPPORT_VARIANTS[variant].warn(self, where=name)
        self.supports = supports
        from pandid.render.iso_parts import support_overlays
        _compose_onto(self, () if supports is None else support_overlays(supports))


class Tank(Unit):
    """Storage tank.

    Variants: ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``, and three named for a cone at the
    bottom: ``"conical_bottom"``, ``"conical_ends"``,
    ``"dished_roof_conical_bottom"``.

    A tank's five nozzles are :class:`Vessel`'s five, for the reason
    given there. Two of them are what a storage tank exists to have:

    - **``vent``, the conservation vent.** A fixed-roof tank fills,
      empties and warms through the day, and it breathes through a roof
      nozzle that is neither the fill nor the draw. Ordinary practice;
      no document on disk covers tank venting, arrestors or floating
      roofs.
    - **``relief``, the fire-case relief on the sphere.** CHEE4001 p.8
      has it protect a pressure vessel against fire or another outside
      source of heat, on a vessel carrying no permanent supply
      connection. A separate nozzle from the vent because one passes
      something on every fill and the other nothing until the design
      case.

    Whether a given tank really has all five is the sheet's business: a
    declared nozzle is *offered*, and choosing not to pipe one is a
    drawing decision.

    **Where a tank fills** is a menu and not a fixture (issue #226). The
    four flat-floored variants -- ``default``, ``conical``,
    ``floating_roof`` and the sphere -- anchor the fill low on the
    shell, since splash-filling a flammable liquid into a vapour space
    generates static; the three hopper-bottomed ones keep the crown,
    because a silo is filled over the top. Every variant offers both,
    through the same :meth:`~Unit.nozzle` call every other unit takes::

        tk = Tank("TK-602")          # fills low on the shell
        tk.nozzle("inlet", "N")      # ...through a crown downcomer

    ``floating_roof`` offers no crown placement at all: the roof rides
    on the liquid, so ``nozzle("inlet", "N")`` raises. The sphere's
    crown carries two drawn nozzles and both are spoken for; see #225
    and ``scripts/vendor_symbols.py``.

    A tank with no ``nozzle()`` call gets its face chosen by layout from
    where the peer landed (:mod:`pandid.layout.faces`), as a drum's
    inlet does.
    """

    inlet: Port
    outlet: Port
    # The same three :class:`Vessel` declares, and each carries the
    # comment there.
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
    """The fitting that changes a line's size: reducer or expander.

    Variants are the body style. ``"concentric"`` is the trapezoid a
    piping drawing draws, symmetric about the run's centreline, and
    ``"default"`` draws it. ``"eccentric"`` is flat along one side, so
    the small end sits on a different centreline from the large one; see
    ``mirrored`` below for which side.

    ``large_end`` says which of the two nozzles is on the wide face, and
    so which way the cone points:

    =====================  ========================================
    ``large_end``          what the fitting does
    =====================  ========================================
    ``"inlet"`` (default)  a **reduction**: the run enters wide
                           and leaves narrow, going into a valve
    ``"outlet"``           an **expansion**: the run enters narrow
                           and leaves wide, coming back out of one
    =====================  ========================================

    One fitting either way, the same casting piped round the other way.
    What changes is the artwork and which end each nozzle is on; the run
    still goes ``inlet`` to ``outlet``, so a station reads

    .. code-block:: python

        fs.connect(hv.outlet, rd.inlet)   # Reducer("RD-306A")
        fs.connect(rd.outlet, cv.inlet)   # the control valve
        fs.connect(cv.outlet, ex.inlet)   # ...large_end="outlet"

    ``pin(mirrored="x")`` is not the same thing: it turns the drawing
    *and* its nozzles over together, so the run enters the east face and
    leaves the west one, drawing the line backwards through the fitting.

    **Eccentric bodies.** The stencil draws the eccentric reducer **flat
    on top**, which is the pump suction arrangement: a concentric body
    there leaves a pocket against the roof of the line for vapour to
    break the pump's suction. Flat on the bottom, for a line that has to
    drain, is ``pin(mirrored="y")`` -- the body turns while both nozzles
    stay on the faces the run enters and leaves by.
    """

    inlet: Port
    outlet: Port

    kind = "reducer"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The nozzles the wide face may be on. Not a bool: the answer names
    #: a port, and "the large end is the outlet" is what an expansion
    #: is.
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
        """``"inlet"`` for a reduction, ``"outlet"`` for expansion."""
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

    A bypass leg around a control valve, a drain off the underside of a
    run, a vent off the top, a sample point, a PSV takeoff: every one of
    them is a line splitting in two, and this is the fitting that splits
    it. Not a unit operation -- a :class:`Mixer` or :class:`Splitter` is
    a piece of plant, drawn as a triangle and scheduled as one.

    A tee is drawn as **nothing at all**: three lines meeting, the run
    passing straight through unbroken and the branch leaving it at a
    right angle, so ``inlet`` and ``outlet`` sit on one centreline. That
    includes the **arrowhead** a PFD draws at the end of a process line:
    a line ending at a tee is drawn without a head, so no filled
    triangle lands in the middle of an unbroken run. A line *leaving* a
    tee takes its head at its own destination.

    **It carries no tag.** A tee is a bulk piping item specified by the
    piping class, and an issued sheet writes nothing against it. The
    flowsheet still needs a name, so ``name`` defaults to
    :data:`DEFAULT_NAME` and any two tees may share it
    (:meth:`repeats`); :meth:`~pandid.flowsheet.Flowsheet.add` hands out
    ``TEE (2)``, ``TEE (3)``. Nothing reaches the equipment list either:
    ``"tee"`` is not in ``pandid.document._MAJOR_EQUIPMENT``.

    ``branch`` says which way the third connection runs: ``"outlet"``
    (the default) takes flow off the run, which is the takeoff end of a
    bypass and every drain, vent and sample point; ``"inlet"`` returns
    flow to it. The run is always ``inlet`` to ``outlet``.

    The branch leaves the **south** face as drawn, so the side it comes
    off is the tee's placement, stated with :meth:`~Unit.pin`:

    ===================  ================
    ``pin(...)``         run, branch
    ===================  ================
    (nothing)            W to E, branch S
    ``mirrored="y"``     W to E, branch N
    ``orientation=90``   N to S, branch W
    ``orientation=270``  S to N, branch E
    ===================  ================

    The run keeps its stream or line number straight through a tee, as
    it does through a valve or a reducer, and the branch starts a number
    of its own. Set ``new_line_number`` to break the run's number where
    the piping class changes at the junction.
    """

    inlet: Port
    outlet: Port
    # Added in ``__init__`` rather than declared in ``PORTS``, because
    # which way it runs is the ``branch=`` argument.
    branch: Port

    kind = "tee"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The name a tee answers to when the author gives it none. Every
    #: tee may take it and be renamed apart by the flowsheet; see
    #: :meth:`repeats`.
    DEFAULT_NAME = "TEE"

    #: What the third connection may be. A tee joins three lengths of
    #: the same pipe, so the branch carries process fluid like the run
    #: and differs only in which way it runs.
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
        self._add_port("branch", branch, "process")

    @property
    def branch_direction(self) -> str:
        """``"outlet"`` for a takeoff, ``"inlet"`` for a return.

        Read off the port rather than kept beside it. It was a plain
        attribute until #292, set once in ``__init__`` and free to be
        assigned afterwards -- which moved the word and not the nozzle,
        so a tee could report a return while its branch went on taking
        flow off the run, and :mod:`pandid.spec` wrote the word into the
        file. A sheet read back then had the branch running the other
        way from the sheet that was written.

        Derived, that cannot happen: there is one fact and the
        serialiser and the router read the same one.
        """
        return self.ports["branch"].direction

    @branch_direction.setter
    def branch_direction(self, value: str) -> None:
        raise AttributeError(
            f"{self.name}: branch_direction is read-only. The branch nozzle is "
            f"already built and may already have a line on it, so turning one "
            f"direction into the other would leave that line running the wrong "
            f"way with nothing said about it. Build the tee you want: "
            f"Tee({self.name!r}, branch={value!r})"
        )

    @property
    def tag(self) -> str:
        """Nothing. A tee is drawn as bare pipe and labelled nowhere."""
        return ""

    def repeats(self, other: "Unit") -> bool:
        """Whether ``other`` is another tee, and so no clash here.

        A tee has no tag, so two tees answering to one name are nothing
        the reader could confuse. The name is only how the flowsheet
        addresses the junction, and
        :meth:`~pandid.flowsheet.Flowsheet.add` keeps it unique.
        """
        return isinstance(other, Tee)


class Fitting(_NormallyPositioned):
    """In-line pipe device: whatever sits in the run and is not a valve.

    One class rather than a dozen: to the flowsheet a strainer, a sight
    glass and a rupture disc are a pair of faces on a line and differ
    only in what is drawn between them. The variant picks the device:
    ``strainer``, ``strainer_cone``, ``strainer_y``,
    ``strainer_basket``, ``strainer_duplex``, ``orifice``,
    ``rotameter``, ``rupture_disc``, ``sight_glass``,
    ``sight_glass_lit``, ``silencer``, ``expansion_joint``, ``bellows``,
    ``blind``, ``damper``, ``spool``, ``static_mixer`` (ISO 10628-2 item
    12.2 X2673), ``rotary_mixer`` (item 12.1 X2672), ``mixing_path``
    (item 12.3 X8184), ``hose``, ``coupling``, ``clamped_coupling``,
    ``flange`` (the default), and the flame arrestors
    (``flame_arrestor`` plus ``_explosion_proof`` / ``_detonation_proof``
    / ``_fire_resistant``).

    A primary flow element is in the run like anything else here, so it
    is a variant too: ``venturi``, ``flow_nozzle``, ``coriolis``,
    ``vortex``, ``ultrasonic``, ``turbine_meter``,
    ``positive_displacement``, ``v_cone``, ``wedge``, ``target``,
    ``pitot`` and ``averaging_pitot``. Hang the FE balloon on one with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`.

    Like a valve, a fitting is inline: a stream keeps its number through
    it unless ``new_line_number`` is set.

    ``blind`` is the **spectacle blind** (figure-8 blind), and it is the
    one fitting with a ``normal_position``: a pair of discs on a common
    tie, one bored through and one solid, of which the line passes
    through the lower one.

    - ``normal_position="open"`` (the default) draws that disc as a
      **ring**, with the solid one parked above it: the line is through.
    - ``normal_position="closed"`` draws it **solid**, with the ring
      parked above: the line is blanked.

    The stencil set draws both shapes, so this is not a mark added to
    one drawing. Any other fitting variant refuses ``"closed"``.
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

    A motive stream entrains a second one, so this is three connections,
    not two: ``motive`` drives the nozzle, ``suction`` is what gets
    entrained, and ``discharge`` leaves the diffuser.
    """

    motive: Port
    suction: Port
    discharge: Port

    kind = "ejector"
    PORTS = [("motive", "inlet", "utility"), ("suction", "inlet", "process"),
             ("discharge", "outlet", "process")]


class Vent(Unit):
    """Open end to atmosphere (vent stack with a weather cap).

    A boundary like :class:`Product`, but drawn as real piping rather
    than an off-page flag, which is what a PSV tailpipe or a tank
    breather wants.

    Variants: ``"default"`` (a stack with a weather cap),
    ``"exhaust_head"`` (the silencing hood on a steam or relief vent)
    and ``"breather"`` (the tank conservation vent). All three carry the
    one connection, piped from below.
    """

    inlet: Port

    kind = "vent"
    PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel: a manual addition point feeding the line.

    The mirror of :class:`Vent`: the cone is open to the room and the
    stem is the process connection, so its single port is an *outlet*.
    """

    outlet: Port

    kind = "funnel"
    PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater or furnace: a stream heated by burning fuel."""

    inlet: Port
    outlet: Port
    fuel: Port

    kind = "furnace"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
             ("fuel", "inlet", "feed")]


class Boiler(Unit):
    """Steam boiler: feedwater in, steam out. ISO 10628-2 item 4.1, 2532.

    Two nozzles, in the two connections Table 2 draws and no others:
    ``feedwater`` on the shell's west wall, a quarter of the way down
    from the crown, and ``steam`` off the dome's own apex. There is no
    fuel or flue connection in the row -- unlike :class:`Furnace`, which
    draws one -- so none is declared here; a boiler fired by its own
    burner is a :class:`Furnace` upstream of this on the sheet, tagged
    and drawn separately.
    """

    feedwater: Port
    steam: Port

    kind = "boiler"
    PORTS = [("feedwater", "inlet", "process"), ("steam", "outlet", "process")]


class Stack(Unit):
    """Exhaust stack or chimney. ISO 10628-2 item 4.7, 2041.

    Not :class:`Vent`. A vent is bulk piping -- a pipe stack with a
    weather cap, bought by the line -- and this is Table 2's own
    equipment: the structure a furnace or boiler's flue gas is ducted up
    and out through, tagged and scheduled the way the plant it exhausts
    is. Table 2 draws one connection, low on the shaft, and nothing
    downstream of it -- a stack takes a line and gives the sheet nothing
    back, the same boundary a :class:`Vent` or a :class:`Product` draws,
    but piped as real equipment rather than an off-page flag.
    """

    inlet: Port

    kind = "stack"
    PORTS = [("inlet", "inlet", "vapor")]


class Flare(Unit):
    """Flare stack: waste gas burned off at the tip. ISO 10628-2 item 4.8, 2591.

    The same terminal shape as :class:`Stack` -- one connection, low on
    the shaft, nothing routed onward -- topped with the flame Table 2
    draws in place of an open end. A sheet that instead wants to *name*
    the flare header a stream leaves to, without drawing the stack
    itself, still reaches for ``Product(header=True)``; see that
    class's docstring. This is for drawing the equipment.
    """

    inlet: Port

    kind = "flare"
    PORTS = [("inlet", "inlet", "vapor")]


class Turbine(Unit):
    """Steam/gas turbine or expander."""

    inlet: Port
    outlet: Port

    kind = "turbine"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Filter(Unit):
    """Filter (liquid or gas), in three shapes of nozzle set.

    **Clarifying** is the default and the plain reading of the word: one
    in, one out. The solids are held in the medium and taken out offline
    when it is changed, backwashed or blown down, so nothing leaves the
    symbol but the filtrate. ``default`` (bag, candle or cartridge
    elements), ``fixed_bed`` and the three gas casings ``gas``,
    ``gas_fixed_bed`` and ``gas_belt`` are all of them.

    **Cake-forming** is the other half of the family, and it is two
    streams more::

        Filter("F-101", variant="press")
          .inlet      slurry in
          .wash_in    wash water in
          .outlet     filtrate out
          .cake       cake out

    A press separates a slurry into **two products**, and the cake is
    the one it is bought for. Drawing it as the filtrate is the sheet
    saying the solids leave in the liquid line, which is the opposite of
    what the machine does. ``wash_in`` is the **displacement wash** that
    pushes mother liquor out of the cake before it is discharged --
    standard on a plate-and-frame press, on a rotary drum vacuum filter
    (sprays over the drum) and on a belt filter (discrete wash zones),
    which is exactly the four variants that carry it: ``press``,
    ``belt``, ``rotary`` and ``rotary_scraper``.

    **``ion_exchange`` is neither**, because what it takes is not wash
    water. A resin bed is restored by running acid, caustic or brine
    through it, and what comes back out is that reagent loaded with the
    ions it has stripped: ``regenerant_in`` and ``spent_regenerant``.
    Calling either of those a wash would put the wrong fluid on the
    line list and the wrong material on the pipe spec.

    Both extra nozzles are **offered, not required**. A sheet that pipes
    the cake and leaves the wash open draws three lines and no fourth,
    and :meth:`~pandid.flowsheet.Flowsheet.validate` says nothing about
    it: an unconnected nozzle a class declares is a drawing decision,
    and only a *numbered* one is a count that has to be met.
    """

    # The clarifying pair only, since ``_VARIANT_PORTS`` defaults to
    # ``_CLARIFYING``. ``wash_in`` and ``cake`` are absent for the reason
    # :class:`HeatExchanger` leaves out ``bottoms``: declaring them here
    # would say every filter has a cake draw and make a bag filter's
    # ``f.cake`` type-check clean. The generated per-variant classes --
    # :class:`~pandid.devices.FilterPress`,
    # :class:`~pandid.devices.RotaryDrumFilter`,
    # :class:`~pandid.devices.IonExchanger` -- declare their own and are
    # where a checker can see them; off one, reach a nozzle by
    # ``f.port("cake")``.
    inlet: Port
    outlet: Port

    kind = "filter"
    # Empty because which nozzles a filter has depends on its variant,
    # and Unit.__init__ reads PORTS before a variant is in hand.
    # _VARIANT_PORTS below is the declaration and __init__ lays it down,
    # exactly as :class:`HeatExchanger` and :class:`Separator` do.
    PORTS: list[tuple[str, str, str]] = []
    #: One in, one out: the medium keeps the solids and is cleaned
    #: offline. The default, and what five of the ten variants are.
    _CLARIFYING = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]
    #: Slurry in, filtrate and cake out, with the wash that displaces
    #: mother liquor from the cake before it is discharged.
    #:
    #: ``utility`` for the wash and ``process`` for the cake. The wash is
    #: a service fluid supplied to the machine, which is the role
    #: :class:`Ejector`'s motive steam already carries; a line only
    #: becomes an energy stream when *both* its ends are energy or
    #: utility, so wash water off a header flag stays material and stays
    #: in the stream table, where a flow that big belongs. The cake has
    #: no word of its own in the role vocabulary -- it is wet solids --
    #: so it takes ``process``, on
    #: :data:`Separator._OVER_AND_UNDER`'s reasoning.
    _CAKE_FORMING = [
        ("inlet", "inlet", "process"),
        ("wash_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("cake", "outlet", "process"),
    ]
    #: The ion exchanger's own pair. Same two positions on the drawing as
    #: the wash and the cake, and deliberately not the same two words: a
    #: regenerant is acid, caustic or brine, and the outlet is named for
    #: what it carries away rather than for the side it leaves by.
    _REGENERATED = [
        ("inlet", "inlet", "process"),
        ("regenerant_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("spent_regenerant", "outlet", "process"),
    ]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_CLARIFYING`. The five absent ones are the five that really
    #: do clarify: the two bag/candle/cartridge casings, the two granular
    #: beds and the gas belt, whose catch is dust in a hopper rather than
    #: a cake taken off a medium.
    _VARIANT_PORTS = {
        "press": _CAKE_FORMING,
        "belt": _CAKE_FORMING,
        "rotary": _CAKE_FORMING,
        "rotary_scraper": _CAKE_FORMING,
        "ion_exchange": _REGENERATED,
    }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._CLARIFYING)

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # ``self.variant`` rather than the argument; see HeatExchanger.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Centrifuge(Unit):
    """Centrifuge: separates a feed by spinning it, ISO 10628-2 group 9.

    A feed and two streams, named for **where** Table 2 draws them
    rather than for which one is the product -- :class:`Separator`'s own
    reasoning, and for the same reason. ``overflow`` is drawn high on
    the shell and ``underflow`` low, at the end a basket or a screw
    discharges its solids from; a decanter clarifying a brine wants its
    ``overflow`` and one dewatering a mineral slurry wants its
    ``underflow``, and neither name should presuppose which is the
    product::

        Centrifuge("CF-101")                             # 9.6  X8082  decanter
        Centrifuge("CF-102", variant="disc")              # 9.4  X8036
        Centrifuge("CF-103", variant="high_speed")        # 9.1  X2619
        Centrifuge("CF-104", variant="perforated_shell")  # 9.2  X2614
        Centrifuge("CF-105", variant="solid_shell")       # 9.3  X8035
        Centrifuge("CF-106", variant="screw_perforated")  # 9.5  X8037
        Centrifuge("CF-107", variant="pusher")            # 9.7  X8038
        Centrifuge("CF-108", variant="skimmer")           # 9.8  X8039

    **Bare ``Centrifuge(...)`` draws the decanter**, item 9.6 X8082, and
    that is a choice rather than an arbitrary default. Group 9 tabulates
    no "centrifuge, general": every one of its eight rows already commits
    to a mechanism, unlike group 11's 11.1 X8084, which is why
    :class:`CrushingMachine` has an unspecified drawing to reach and this
    class does not. Of the eight, the continuous screw-type decanter is
    the one a solid-liquid separation duty on a slurry, sludge or cake
    reaches for most often, so it is the drawing an author gets free and
    every other row is named explicitly.

    **The same three nozzles on every row.** All eight draw the same
    shape of connection -- a feed and a pair of draws -- so unlike
    :class:`Filter`'s cake-forming variants, no variant here adds or
    removes a nozzle; only where each lands on the drawing changes
    between them. See
    ``pandid.render.symbols.SymbolRegistry._register_centrifuges``.

    **Not gravity-fixed.** A centrifuge's floor is drawn low and its feed
    high, the way a hopper's or a settling vessel's is, but what does the
    separating is rotation and not a free surface or a settling body, so
    it may be turned or mirrored to fit a layout exactly as ISO 15519-1
    §11.4.2 permits for equipment whose function is not gravity.
    """

    feed: Port
    overflow: Port
    underflow: Port

    kind = "centrifuge"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]


class Dryer(Unit):
    """Dryer (removes moisture from a feed solid/slurry)."""

    feed: Port
    product: Port

    kind = "dryer"
    PORTS = [("feed", "inlet", "feed"), ("product", "outlet", "process")]


class Feeder(Unit):
    """Proportional or metering feeder, ISO 10628-2 group 19.

    A feeder takes solids in and metres them out, so every variant
    keeps the two names :class:`CrushingMachine` does::

        Feeder("FD-101")                          # 19.1  C2056  general
        Feeder("FD-102", variant="rotary_valve")  # 19.2  X8067
        Feeder("FD-103", variant="rotary_table")  # 19.3  C0074
        Feeder("FD-104", variant="metering")      # 19.4  C0035

    **``"general"`` is the default**, item 19.1's plain circle with no
    mechanism marked -- the same reasoning :class:`CrushingMachine`
    gives item 11.1: a process design that has sized a feed duty
    without yet picking a rotary valve over a table feeder wants this
    row rather than a placeholder with no ISO number.

    ``"rotary_valve"`` (19.2) is the standard way solids enter a
    pressurised system: a rotor turning in a close-fitting housing
    passes material through a module at a time while keeping the two
    sides from communicating.

    ``"rotary_table"`` (19.3) meters off a turntable's edge and
    ``"metering"`` (19.4) is drawn as a balance, weighing what it lets
    through -- both still fed from above and discharging below, the
    hopper valve's own claim about which way is down.

    Every variant is drawn one way up and reported as ``gravity-turned``
    by :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: solids
    drop in at the top and are metered out at the bottom, ISO
    15519-1 §11.4.2's exception for a hopper valve.
    """

    feed: Port
    discharge: Port

    kind = "feeder"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


class SprayNozzle(Unit):
    """Spray nozzle, ISO 10628-2 item 19.5 2037.

    A terminal fitting on a line, drawn as a fan opening downward off
    the point a header tees into it -- not a piece of equipment with a
    duty of its own, so it carries the one connection a nozzle has:
    ``inlet``, the header feeding it. What it sprays into is whatever
    line or vessel it is drawn against, and is not a nozzle of this
    symbol's.

    Table 2 ticks the connection level with the fan's own apex on
    *both* sides -- the nozzle taps a header running through it rather
    than dead-ending a single supply -- so ``inlet`` is offered on the
    west face and the east alike; an author routes from whichever side
    the header approaches from.
    """

    inlet: Port

    kind = "spray_nozzle"
    PORTS = [("inlet", "inlet", "process")]


class ScreeningDevice(Unit):
    """Screening device: sieve, strainer or rake, ISO 10628-2 group 7.

    **Not named ``Screen``.** ``Separator(variant="sifter")`` has drawn
    a screening deck since before this class existed and
    :mod:`pandid.devices` already generates that variant's own class
    under the word an engineer searches for -- see
    :class:`~pandid.devices.Screen`. Measured against Table 2's group 7
    it is not one of these seven rows (a different outline, at group 8's
    own 8 M box rather than this group's 6 M one, and a mesh mark near
    the vessel's shoulder rather than the corner-to-corner diagonal
    every row here draws), so it is left exactly as it ships and this
    class takes the ISO name instead of the plainer one.

    A screen makes an oversize and an undersize, named for what Table 2
    draws rather than for which one is wanted -- :class:`Separator`'s
    own reasoning, and for the same reason: a scalping screen ahead of
    a crusher wants its ``oversize`` and a dewatering screen under a
    centrifuge wants its ``undersize``, and neither name should presume
    which is the product::

        ScreeningDevice("SC-101")                             # 7.1  X8123  general
        ScreeningDevice("SC-102", variant="coarse_rake")      # 7.2  X8026
        ScreeningDevice("SC-103", variant="fine_rake")        # 7.3  X8027
        ScreeningDevice("SC-104", variant="coarse_and_fine")  # 7.4  X8028
        ScreeningDevice("SC-105", variant="vibrating")        # 7.5  X2605
        ScreeningDevice("SC-106", variant="rotating_drum")    # 7.6  X8029
        ScreeningDevice("SC-107", variant="basket_reel")      # 7.7  X8030

    **The same three nozzles on every row.** All seven draw the same
    shape of connection -- fed from above, oversize retained out of a
    side wall, undersize passed through the deck and out of the apex
    below -- so no variant adds or removes a nozzle; only 7.7's own
    larger outline moves where each one lands on it. See
    ``pandid.render.symbols.SymbolRegistry._register_screens``.

    Every variant is drawn one way up and reported as ``gravity-turned``
    by :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: a screen
    retains its oversize on a deck and drops its undersize through it,
    ISO 15519-1 §11.4.2's exception again.
    """

    feed: Port
    oversize: Port
    undersize: Port

    # Not ``"screen"``: that string is also ``Screen``'s own class name
    # lower-cased (:class:`~pandid.devices.Screen`, the group-8
    # ``separator/sifter`` device), and :mod:`pandid.spec` builds one
    # alias table from both a class's name and every class's ``kind``.
    # The two would collide there -- whichever loop ran last would win,
    # and a spec naming ``kind: Screen`` would silently resolve to the
    # wrong class on the way back in. See ``pandid.spec._ALIASES``.
    kind = "screening_device"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("oversize", "outlet", "process"),
        ("undersize", "outlet", "process"),
    ]


class Kneader(Unit):
    """Kneader: a trough mixer working a stiff paste, dough or rubber
    compound, ISO 10628-2 item 12.4 X8134.

    A folding wave crossing the casing on its own centre line is
    Table 2's mark for the blades' action; unlike ``fitting/
    rotary_mixer`` and ``fitting/mixing_path`` beside it in group 12,
    a kneader is substantial process equipment and carries a tag of
    its own rather than sitting in the run as pipe furniture.

    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: twin shafts
    driven from above work a trough that holds its charge below them,
    ISO 15519-1 §11.4.2's exception.
    """

    inlet: Port
    outlet: Port

    kind = "kneader"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class CrushingMachine(Unit):
    """ISO 10628-2 item 11.1 X8084: a size-reduction machine, unspecified.

    The bare trapezoid, no mark inside it -- neither :class:`Crusher`'s
    two verticals nor :class:`Mill`'s two chords, both of which are
    built on this class rather than beside it. ISO's own item means "a
    crusher or a mill, not yet said which", which is not something a
    *finished* P&ID says. It is exactly what an early PFD says: process
    design has sized a duty for coarse crushing or fine grinding before
    it has picked jaw over cone or even settled which of the two
    families the flowsheet needs, and this is the row Table 2 gives that
    stage rather than a placeholder box with no ISO number behind it::

        CrushingMachine("SZ-101")            # 11.1  X8084  general

    Once the machine is chosen, :class:`Crusher` or :class:`Mill` draws
    it and ``variant=`` says which characteristic -- both take every
    keyword this class does, since both are it with a mark added.

    Two nozzles, and the same two on every row of the group, because
    Table 2 draws the same two connection ticks on all thirteen: one on
    the centre line above the top edge and one below the bottom edge.
    Ore goes in the top and falls out of the bottom.

    ``feed`` and ``discharge`` are :class:`Conveyor`'s names, which is
    deliberate -- a crusher is fed by a belt and discharges onto one, and
    the two units either side of that chute should not call the same
    thing by two words.

    **There is no ``drive``**, and it is worth saying why rather than
    leaving it to be noticed. Every one of these is motor-driven, and
    ISO draws exactly one motor in the whole of Table 2: item 1.27 X8006,
    the stirred vessel, where the motor sits on the agitator's own shaft
    and the standard registers the composition. Group 11 draws no motor
    and no third tick, so a ``drive`` here would be a nozzle pandid
    invented, on a body ISO has already said how to connect. An author
    who wants the drive on the sheet draws the motor as its own tagged
    unit, which is what the other seven group-20 machines are for.

    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: the feed
    comes in the top and the product falls out of the bottom, which is
    ISO 15519-1 §11.4.2's exception.
    """

    feed: Port
    discharge: Port

    kind = "crushing_machine"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


class Crusher(CrushingMachine):
    """Crusher: coarse size reduction, ISO 10628-2 item 11.2 X8085.

    The trapezoid every group-11 row is drawn on, with the crusher's own
    two full-depth verticals inside it. ``variant=`` names the ISO
    group-29 characteristic that says how it breaks the feed, and each
    one is the body carrying that mark::

        Crusher("CR-101")                    # 11.2  X8085  general
        Crusher("CR-102", variant="jaw")     # 11.5  X8047
        Crusher("CR-103", variant="cone")    # 11.7  X8049
        Crusher("CR-104", variant="hammer")  # 11.3  X8045
        Crusher("CR-105", variant="impact")  # 11.4  X8046
        Crusher("CR-106", variant="roller")  # 11.6  X8048

    Five characteristics, and they are the five ISO gives a crusher.
    ``vibration`` is a mill's (11.12) and is refused here, because Table 2
    has no vibrating crusher -- the registry says so, by name, with the
    list of the ones there are.

    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned: the feed
    comes in the top and the product falls out of the bottom, which is
    ISO 15519-1 §11.4.2's exception.
    """

    kind = "crusher"


class Mill(CrushingMachine):
    """Mill or pulveriser: fine grinding, ISO 10628-2 item 11.8 X8086.

    The same trapezoid as :class:`Crusher`, with the mill's own two
    chords across the top corners instead of the crusher's verticals.
    That pair of marks is the whole of what tells the two machines apart
    on an ISO sheet, and it is why they are two classes: an engineer
    orders a crusher or a mill, never "a group-11 machine"::

        Mill("ML-101")                       # 11.8   X8086  general
        Mill("ML-102", variant="hammer")     # 11.9   X8050
        Mill("ML-103", variant="impact")     # 11.10  X8051
        Mill("ML-104", variant="roller")     # 11.11  X8053
        Mill("ML-105", variant="vibration")  # 11.12  X8054

    A **ball or rod mill** is drawn as the general mill: ISO 10628-2 has
    no item for either, and the four characteristics above are the four
    it does give, so the tumbling mill of a grinding circuit takes the
    plain body and says what it is in its description.

    ``jaw`` and ``cone`` are a crusher's (11.5, 11.7) and are refused
    here for the reason ``vibration`` is refused there.
    """

    kind = "mill"


class Conveyor(Unit):
    """Conveyor: bulk solids carried tail end to head end.

    ``variant="default"`` is the belt (ISO 10628-2 item 18.2, 3821) and
    ``variant="screw"`` the enclosed screw (item 18.5 X8063)::

        Conveyor("CV-101")                                # belt
        Conveyor("CV-102", variant="screw", length=140)   # screw
        Conveyor("CV-103", length=300, diameter=40)       # big rollers

    **Two dimensions, and each is a dimension of the machine.**
    ``length`` is the run, tail end to head end. ``diameter`` is the
    machine across that run: the roller on a belt, the casing bore on a
    screw -- both circles seen in elevation, and both the depth of the
    drawing. Neither is worked out from the other, so a long belt on
    small rollers and a short one on big rollers are both drawings.

    The symbol is *built* to the pair rather than scaled to a box, so a
    longer belt grows the straight run and its rollers stay round, a
    bigger roller grows a circle, and a longer screw gets more turns of
    the flight at the same pitch rather than one stretched turn.

    ``width`` and ``height`` size the drawn *box* and are refused, for
    the reason the second dimension is not spelled ``height=``: a
    quarter turn stands the machine on end, where the length is the box
    height and the diameter is its width. The rollers are the rollers
    either way up, so they are stated as the rollers.

    **Where the nozzles are differs between the two, because the
    machines differ.** A belt is open: material is dropped onto it and
    thrown off the end, so ``feed`` is the tail roller and ``discharge``
    the head, each also offered on the face the chute would come from. A
    screw runs enclosed in a trough and is loaded and discharged through
    spouts, so its ``feed`` is on the **top** near the tail and its
    ``discharge`` on the **underside** near the head, with the two ends
    offered instead. Both follow the connection ticks Table 2 draws on
    the two rows.
    """

    feed: Port
    discharge: Port

    kind = "conveyor"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]

    _length: float
    _diameter: float

    def __init__(self, name: str, length: float | None = None,
                 diameter: float | None = None, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        from pandid.render.symbols import CONVEYOR_LENGTH

        if width is not None or height is not None:
            # Name the keyword the given number belongs on. width= is
            # always the run; height= is the machine across it, and the
            # box axis it sizes is only the run's when the conveyor is
            # left lying down.
            given = width if width is not None else height
            instead = "length" if width is not None else "diameter"
            raise ValueError(
                f"{name}: a Conveyor is sized by length=, the run between its "
                f"two ends, and diameter=, the roller a belt runs on or the "
                f"bore a screw turns in. Those are the machine; width= and "
                f"height= size the drawn box instead, which a quarter turn "
                f"swaps and which would stretch a belt's rollers out of round "
                f"and a screw's flight off its pitch. Pass {instead}={given!r}."
            )
        super().__init__(name, variant=variant, label_pos=label_pos,
                         description=description, reference=reference)
        # Diameter first: it is what the run is measured against, so a
        # belt on 40 rollers is refused at 60 rather than accepted at
        # the default roller's 40 and then quietly widened.
        self.diameter = self.default_diameter() if diameter is None else diameter
        self.length = CONVEYOR_LENGTH if length is None else length

    def default_diameter(self) -> float:
        """The roller or bore this variant is drawn with unstated.

        The stencil's own 20 for the belt and row 18.5's 6 M casing for
        the screw: two drawings from two sources, so two numbers.
        """
        from pandid.render.symbols import CONVEYOR_DIAMETER, SCREW_HEIGHT

        return SCREW_HEIGHT if self.variant == "screw" else CONVEYOR_DIAMETER

    @property
    def length(self) -> float:
        """The run, tail end to head end, in drawn units.

        The symbol is built to it rather than scaled to it, so a belt's
        rollers are the same circles and a screw's turns the same turns
        however long the machine is.
        """
        return self._length

    @length.setter
    def length(self, value: float) -> None:
        """The shortest run each variant can be drawn in is its own.

        A belt is bounded by its two rollers overlapping -- so by the
        roller, and a belt on bigger rollers needs a longer bed to stand
        them on -- and a screw by one whole turn of the flight not
        fitting, which is measured along the axis and so is the same
        number at every bore. The two *sentences* differ too, so the
        error comes from whichever drawing is being asked for. A reader
        told about rollers goes looking for rollers.
        """
        from pandid.render.symbols import (
            SCREW_MIN_LENGTH, conveyor_min_length, conveyor_too_short,
            screw_too_short,
        )

        if self.variant == "screw":
            if value < SCREW_MIN_LENGTH:
                raise screw_too_short(value, self.name)
        elif value < conveyor_min_length(self.diameter):
            raise conveyor_too_short(value, self.name, self.diameter)
        self._length = float(value)

    @property
    def diameter(self) -> float:
        """The machine across the run: the roller a belt runs on, or the
        bore a screw turns in.

        Its own dimension, set independently of :attr:`length` and never
        derived from it. It *is* the drawn depth of the artwork, because
        a belt runs tangent to both rollers and a screw fills its
        casing -- so the box the symbol is placed in is the box it was
        drawn in, and the circles in it are circles on the page.
        """
        return self._diameter

    @diameter.setter
    def diameter(self, value: float) -> None:
        """A circle with no diameter is not a machine, and shrinking the
        rollers under a belt already too short for them is not either.

        The second check is the one that makes the pair a pair: the
        minimum run is two roller diameters, so growing the roller on an
        existing belt can invalidate a length that was legal, and it is
        refused in the same sentence a short length is.
        """
        from pandid.render.symbols import (
            conveyor_bad_diameter, conveyor_min_length, conveyor_too_short,
            screw_bad_diameter,
        )

        if value <= 0:
            raise (screw_bad_diameter if self.variant == "screw"
                   else conveyor_bad_diameter)(value, self.name)
        value = float(value)
        length = getattr(self, "_length", None)
        if (self.variant != "screw" and length is not None
                and length < conveyor_min_length(value)):
            raise conveyor_too_short(length, self.name, value)
        self._diameter = value


class Elevator(Unit):
    """Bucket elevator: solids lifted in buckets on a belt.

    ISO 10628-2 item 18.7 X8065, and ``variant="z_form"`` its item 18.8
    X8066 -- the same machine with a horizontal run at each end, which
    is what carries material along as well as up::

        Elevator("BE-301")
        Elevator("BE-302", variant="z_form")

    ``feed`` is the boot, low, and ``discharge`` the head, high: a
    machine that takes material in at the bottom and delivers it at the
    top is the whole of what an elevator is for, and the nozzles say so.
    On the straight elevator the row's own vertical chute directions are
    offered as the north and south faces beside them; see
    ``symbols._BUCKET_ELEVATOR`` for why they are not the home nozzles.

    There is no ``length``. A conveyor's run is a number an author
    states and an elevator's lift is not -- it follows from the two
    elevations it connects, which the sheet already shows -- so both
    drawings are fixed and a taller machine is the same symbol.

    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned. Upside down
    it is a machine that lowers material, which is not this one.
    """

    feed: Port
    discharge: Port

    kind = "elevator"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


def split_tag(type: str, number: str | int = "") -> tuple[str, str]:
    """Split an instrument tag into its letters and its loop number.

    ``("FT", 101)``, ``"FT-101"`` and ``"FT101"`` all give
    ``("FT", "101")``.
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


#: A minted member of one of :class:`Instrument`'s signal pools. Member
#: one of each keeps the name it shipped under (``sig_out``) and the
#: rest count on from two (``sig_out_2``).
_POOL_MEMBER = re.compile(r"(sig_in|sig_out)_\d+")

#: Where the information a balloon shows is available. ISO 15519-2:2015
#: Table 1, p. 7, tabulates one additional graphic per row: no bar
#: means the reading is at a field-mounted instrument or display, one
#: full horizontal bar puts it in the central control system, and two
#: put it in a subsidiary one.
DISPLAYS = ("field", "central", "subsidiary")

#: What a balloon relates to its host by. ``"sensing"`` and
#: ``"acting_on"`` are connections and draw a line; ``"near"`` is a
#: placement and draws nothing.
RELATIONS = ("sensing", "acting_on", "near")

#: The registered drawing each (symbol type, display) pair resolves to.
#: The two axes are the standard's; the registry spells one enum over
#: both, so this table is where they meet. A pair asking for no bar is
#: not in it and falls through to the registry unchanged, which is what
#: lets a balloon shape registered later need no edit here.
_BALLOON_SYMBOLS = {
    ("default", "field"): "default",
    ("default", "central"): "panel",
    ("default", "subsidiary"): "aux",
    ("shared", "central"): "shared",
}

#: The same table read back: the symbol type a registered variant
#: draws, for anything that has to state the two axes apart again
#: (:meth:`pandid.flowsheet.Flowsheet.to_dict`, chiefly).
_BALLOON_SHAPES = {drawn: shape for (shape, _display), drawn in _BALLOON_SYMBOLS.items()}

#: The display a symbol type states on its own, so its bar is not a
#: second decision to make. CHEE4001 p.13 reads a circle inside a
#: square as an instrument with a controlling function, the circle
#: standing for continuous control such as a DCS.
_IMPLIED_DISPLAY = {"shared": "central"}

#: The two spellings that were a location wearing a symbol type's
#: clothes, and the display each of them meant. Removed in 0.1.3 and
#: refused by name, because each is also the registered *artwork* the
#: pair above resolves to: a ``variant`` left to the registry would draw
#: the bar while the balloon went on saying it was in the field.
_DISPLAY_VARIANTS = {"panel": "central", "aux": "subsidiary"}


class Instrument(Unit):
    """ISA-5.1 instrument balloon.

    ``type`` is the functional letter string (``"FT"``, ``"PAH"``,
    ``"LIC"``) and ``number`` the loop number; the balloon draws the
    letters over the number, and the number is drawn **bare**. ``name``
    is the full tag (``"FT-101"``), which is what equipment lists and
    cross-references want. A single combined argument
    (``Instrument("FT-101")``) is accepted and split.

    ``pv`` taps the process; ``sig_in``/``sig_out`` carry signals. All
    three are signal connections and take a signal ``kind``: an impulse
    line to a transmitter is an instrument connection, not a process
    pipe.

    ``sig_in`` and ``sig_out`` are **pools**, not single connections.
    Each hands back a free one and mints another when they are all
    taken, so a balloon takes as many signal lines as the loop needs::

        fs.connect(pic301.sig_out, cv1.actuator, kind="pneumatic")
        fs.connect(pic301.sig_out, cv2.actuator, kind="pneumatic")

    Naming the units instead lets the engine pick both ends:
    ``fs.connect(ft305, fic305, kind="electric")``.

    Two axes, asked separately. ``variant`` is the **symbol type**, what
    the instrument does: ``"default"`` (a circle), ``"shared"`` (a
    circle in a square, shared display and shared control),
    ``"computer"`` (a hexagon), ``"sis"`` (a diamond in a square,
    ANSI/ISA-5.1-2009 Table 5.1.1 column B, also spelled ``"logic"``)
    and ``"interlock"`` (a plain diamond, Table 5.1.2 items 3-5).
    ``display`` is **where the information is available**, ISO 15519-2
    Table 1's additional graphic: ``"field"`` (no bar), ``"central"``
    (one) or ``"subsidiary"`` (two). See :data:`DISPLAYS`.

    Not every pair has a drawing registered. ``variant="shared"`` is the
    only shape carrying a bar today, and it carries ``"central"``
    without being asked; a shape and a display with no artwork between
    them raises rather than drawing the shape and dropping the bar.

    A balloon that measures something belongs *on* what it measures: see
    :meth:`attach` and
    :meth:`pandid.flowsheet.Flowsheet.add_instrument`.
    """

    pv: Port
    sig_in: Port
    sig_out: Port

    kind = "instrument"
    # The three a balloon is born with; ``sig_in`` and ``sig_out`` are
    # the first member of their pool. Declared rather than minted lazily
    # because ``ports`` is an ordered dict that
    # :mod:`pandid.layout.faces` serves in order, so a balloon whose
    # connections appeared as the author reached for them would draw
    # differently depending on which line was written first.
    PORTS = [("pv", "inlet", "signal"), ("sig_in", "inlet", "signal"),
             ("sig_out", "outlet", "signal")]

    #: The two pools, and the name the first member of each ships under.
    _SIGNAL_POOLS = ("sig_in", "sig_out")

    #: The variants that stand for a function rather than a device. A
    #: trip square is a logic function, which acts in several places at
    #: once and is drawn in each of them under the same tag. ``"sis"``
    #: and ``"logic"`` are two names for one symbol.
    _REPEATABLE_VARIANTS = frozenset({"sis", "logic", "interlock"})

    def __init__(self, type: str, number: str | int = "", variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "", reference: str = "",
                 display: str | None = None):
        letters, num = split_tag(type, number)
        # Built from the SPLIT, not from the arguments. ``split_tag``
        # promises that ("FT", 101), "FT-101" and "FT101" are one
        # request, and until #292 the name was worked out beside it
        # rather than from it: the un-hyphenated spelling came out
        # ``name == tag == "FT101"`` while the balloon drew ``FT`` over
        # ``101``, so the equipment list, every cross-reference and the
        # spec round trip carried a tag no other spelling of the same
        # request produced -- and reading that file back re-derived
        # "FT-101" from the type and number, renaming the instrument.
        # Joined the same way ``split_tag`` takes it apart, so all three
        # spellings converge; ``letters + num`` is what a tag that is
        # all letters or all digits comes out as.
        name = f"{letters}-{num}" if letters and num else letters + num
        #: Which of :data:`DISPLAYS` this balloon states. Set by the
        #: resolver below, which is also what turns the pair into the
        #: one variant the registry, the exporter and :mod:`pandid.spec`
        #: all read.
        self.display = "field"
        variant = self._resolved_variant(name, variant, display)
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description, reference=reference)
        self.type = letters
        self.number = num
        #: The symbol type the author asked for, kept apart from
        #: :attr:`~Unit.variant` because the registry's spelling folds
        #: the display into it. This is the half ``to_dict`` writes, so
        #: a sheet read back never names a variant that is refused.
        self.symbol_type = _BALLOON_SHAPES.get(variant, variant)
        # The drawn tag, kept apart from the name because a repeated
        # square needs a name of its own to be addressed by. See
        # :attr:`tag`.
        self._tag = name
        # Attachment intent (set only via attach()); the layout engine
        # resolves it into a frame, as Pin -> Frame for equipment.
        self.host: "Stream | Unit | None" = None
        self.at: float | str | None = None
        self.offset: float = 45.0
        self.angle: float = 90.0
        #: One of :data:`RELATIONS`; set only by :meth:`attach`. What
        #: the sheet draws between this balloon and its host follows
        #: from it -- see :func:`pandid.render.svg.tap_lines`.
        self.relation: str = "sensing"
        #: The item whose tag this balloon carries, for a primary
        #: element's balloon; set only by
        #: :meth:`pandid.flowsheet.Flowsheet.add_balloon`. What makes
        #: the shared tag legal rather than a clash: see :meth:`repeats`.
        self._marks: "Unit | None" = None
        # Letter codes written outside the symbol, keyed by quadrant;
        # see :meth:`annotate`.
        self.quadrants: dict[str, tuple[str, ...]] = {}
        # Resolved tap point; set only by layout.
        self.tap: tuple[float, float] | None = None

    def _resolved_variant(self, name: str, variant: str, display: str | None) -> str:
        """The one registered spelling for a symbol type and a display.

        Two questions, answered by one variant name. *Where* the
        information is available is ISO 15519-2 Table 1's additional
        graphic. *What the instrument does* is the outline -- and that
        half is ANSI/ISA-5.1's, not ISO's: §5.1.1 gives a circle and an
        extended circle, and neither of the two encodes function. This
        is where they meet, so that the rest of
        the package sees a variant and nothing else, exactly as
        :meth:`Valve._resolve` folds a body and an actuator into one.
        """
        meant = _DISPLAY_VARIANTS.get(variant)
        if meant is not None:
            raise ValueError(
                f"{name}: variant={variant!r} says where the information is "
                f"available, which is the display= axis: write "
                f"display={meant!r}. What the instrument *does* is variant="
            )
        if display is None:
            display = _IMPLIED_DISPLAY.get(variant, "field")
        if display not in DISPLAYS:
            raise ValueError(
                f"{name}: display= is where the information this balloon shows is "
                f"available, one of {', '.join(repr(d) for d in DISPLAYS)}, got "
                f"{display!r}. It is ISO 15519-2 Table 1's additional graphic: no bar "
                f"in the field, one for the central control system, two for a "
                f"subsidiary one. What the instrument *does* is variant="
            )
        self.display = display
        pair = _BALLOON_SYMBOLS.get((variant, display))
        if pair is not None:
            return pair
        if display == "field":
            return variant  # an unregistered shape is the registry's to refuse
        drawn = ", ".join(f"variant={v!r} display={d!r}"
                          for (v, d) in _BALLOON_SYMBOLS if d != "field")
        raise ValueError(
            f"{name}: no balloon is drawn for variant={variant!r} with "
            f"display={display!r}. A location bar is registered artwork rather than "
            f"a stripe laid over any outline, and the pairs drawn today are {drawn}. "
            f"Ask for display='field', or for one of those"
        )

    # ------------------------------------------------------------------
    # The signal pools.
    #
    # ``sig_in`` and ``sig_out`` mint a fresh member per connection, so
    # a balloon takes as many signal lines as the loop needs: one
    # controller on split range, a measurement feeding a high and a low
    # alarm, an alarm that both trips and is tripped from.
    #
    # **They must stay attributes and not become properties over the
    # pool.** A property handing back a free member destroys the
    # read-back: ``inst.sig_out.stream`` is how a caller asks what a
    # balloon drives, and once the first line is made a property answers
    # with a freshly minted port whose stream is None, having grown a
    # nozzle nothing reaches as a side effect of being looked at. The
    # pool is entered where a *connection* is made --
    # :meth:`pandid.flowsheet.Flowsheet.connect` asks for another member
    # when the one it was handed is already wired -- which leaves
    # ``pic.sig_out`` meaning the first line for good.
    #
    # Direction on a signal port is derived from
    # ``Stream.source``/``Stream.dest``, which is exact because a port
    # holds at most one stream; the ``Port.direction`` guard is a rule
    # about process nozzles only.
    #
    # ``pv`` is not a pool: an instrument taps one process point, and
    # that is what :meth:`attach` places the balloon against. A
    # differential instrument tapping two wants a second *named* tap,
    # high and low, rather than an anonymous pool member.
    # ------------------------------------------------------------------

    def has_another_port(self, port: Port) -> bool:
        """True for a member of a signal pool, false for ``pv``.

        A balloon taps one process point, so a second line to ``pv`` is
        refused as :meth:`Unit.has_another_port` describes.
        """
        return self._pool_of(port.name) is not None

    def another_port(self, port: Port) -> Port:
        """A free member of ``port``'s pool, minting one if need be.

        Called by :meth:`pandid.flowsheet.Flowsheet.connect` on a
        connection that is already spoken for, which is what makes two
        lines off one ``sig_out`` two lines rather than an error.
        """
        base = self._pool_of(port.name)
        if base is None:
            return port
        members = [p for name, p in self.ports.items() if self._pool_of(name) == base]
        for member in members:
            if member.stream is None:
                return member
        # Numbered from the members present, so a sheet rebuilt from a
        # spec that named ``sig_out_2`` and ``sig_out_4`` numbers its
        # next one 5. The loop covers the gap the named ones left.
        n = len(members) + 1
        while f"{base}_{n}" in self.ports:
            n += 1
        return self._add_port(f"{base}_{n}", members[0].direction, "signal")

    def signal_port(self, name: str) -> Port:
        """The signal connection ``name``, minting it if absent.

        The way to reach a pool member the balloon has not grown yet
        (``pic.signal_port("sig_out_2")``), which is what
        :func:`pandid.spec.from_dict` needs to rebuild a sheet a pool
        was used on. An existing port of any name comes back unchanged.
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
        """The pool ``port_name`` is in, ``None`` for a unique nozzle.

        The one rule that tells ``sig_out`` and ``sig_out_2`` apart from
        ``pv``; everything about the pools reads it.
        """
        if port_name in cls._SIGNAL_POOLS:
            return port_name
        member = _POOL_MEMBER.fullmatch(port_name)
        return member.group(1) if member else None

    def _symbol_anchor(self, port_name: str) -> str:
        """Every pool member draws on its pool's first nozzle.

        A balloon's signal connections are declared ``faceless``
        (:attr:`pandid.render.symbols.Symbol.faceless_ports`): they
        share one menu of four faces and none owns one, so a minted
        member wants the menu ``sig_out`` already has and the registry
        never has to anchor a name it cannot know.

        Which face a member lands on is :mod:`pandid.layout.faces`'
        answer, port by port, and it refuses to put two live connections
        on one point.
        """
        return self._pool_of(port_name) or super()._symbol_anchor(port_name)

    @property
    def tag(self) -> str:
        """The ISA tag drawn in the balloon or square (``"I-1"``).

        Equal to :attr:`~Unit.name` for everything drawn once. An
        interlock square repeats, so the sheet shows one tag several
        times while the flowsheet keeps a distinct name for each square
        to address it by (``I-1``, ``I-1 (2)``).
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Whether this balloon is *another mark of* ``other``.

        Two ways it can be. It is **the same logic function drawn
        again**: both ends trip squares carrying the same tag, and the
        *same* square, since a plain interlock diamond and a
        diamond-in-square are two different ISA-5.1 symbols and one of
        each on a tag is still a clash (``"sis"`` and ``"logic"`` name
        one symbol and count as the same). Or it is **a primary
        element's balloon**, holding the tag of the thing in the pipe
        that :meth:`pandid.flowsheet.Flowsheet.add_balloon` built it
        for -- one instrument, two marks, issue #249.
        """
        def symbol(variant: object) -> object:
            return "sis" if variant == "logic" else variant

        if other is self._marks:
            return True
        return (isinstance(other, Instrument)
                and other.tag == self.tag
                and self.variant in self._REPEATABLE_VARIANTS
                and symbol(self.variant) == symbol(other.variant))

    def annotate(self, *, high: "str | Sequence[str] | None" = None,
                 low: "str | Sequence[str] | None" = None,
                 safety: "str | Sequence[str] | None" = None,
                 variable: "str | Sequence[str] | None" = None) -> "Instrument":
        """Write letter codes in the quadrants around this symbol.

        ISO 15519-2 §5.2.5, p. 22, puts any letter code carrying the
        modifiers H or L outside the PCI symbol, and **shall** order the
        codes A, then S, then Z, with the value each stands for rising
        as they go away from the symbol's centre line. So a high
        alarm on a controller is lettering beside that controller, not a
        balloon of its own, and no line is drawn: an annotation is not a
        signal.

        §5.1.3, p. 19, names the four quadrants Figure 8 puts them in,
        and this method's four arguments are that list in its order:

        - ``safety`` -- (a) a reference to a typical diagram, or safety
          information such as a SIL or SIF identifier;
        - ``variable`` -- (b) which variable is meant where the tag uses
          letter code U for multivariable: pH, µS, MJ/s;
        - ``high`` -- (c) a high output or input function, an alarm or a
          switching action say;
        - ``low`` -- (d) the same for a low one.

        The quadrants are the corners, which is the clause's own reason
        for them: keeping the four faces clear is what lets the symbol
        be connected horizontally and vertically. So annotating a
        balloon spends no face.

        Each takes one code or several. Several are ordered A, S then Z
        outward whatever order they are given in, since the standard
        fixes the sequence and the author has no choice to express::

            lic304.annotate(high="LAH", low="LAL")
            lsh611.annotate(high=("LAHH", "LSHH"))
            ai301.annotate(variable="pH", safety="SIL 2")

        Chainable. An argument left out is a quadrant left alone, so a
        second call replaces only what it names; ``high=()`` is how a
        quadrant is emptied, which is a different request from not
        mentioning it.
        """
        for name, codes in (("a", safety), ("b", variable),
                            ("c", high), ("d", low)):
            if codes is None:
                continue
            written = _quadrant_codes(self.name, name, codes)
            if written:
                self.quadrants[name] = written
            else:
                self.quadrants.pop(name, None)
        return self

    def attach(self, on: "Stream | Unit", *, at: float | str | None = None,
               offset: float = 45.0, angle: float = 90.0,
               relation: str = "sensing") -> "Instrument":
        """Anchor this balloon to a process line or to equipment.

        ``on`` is the host: a :class:`~pandid.streams.Stream` (tap a
        line) or a :class:`Unit` (mount on equipment). ``at`` locates
        the tap: a fraction ``0..1`` along the host stream's routed
        path, or a face (``"N"``, ``"S"``, ``"E"``, ``"W"``) of a host
        unit's drawn box.

        ``relation`` is what the balloon has to do with the host, one of
        :data:`RELATIONS`, and it decides whether a line is drawn
        between them: ``"sensing"`` and ``"acting_on"`` are connections,
        ``"near"`` is a placement and draws nothing.
        :meth:`pandid.flowsheet.Flowsheet.add_instrument` is where an
        author states it.

        ``offset`` is the distance from the tap to the balloon centre;
        ``offset=0`` leaves the element sitting *on* the line, which is
        how an in-line primary element (an orifice plate FE) is drawn.

        ``angle`` is the direction the balloon branches off, in degrees
        from the flow direction at the tap, counter-clockwise positive,
        so the default ``90`` is "perpendicular, upstream side up" and a
        tap keeps its orientation if the line is later re-routed. On a
        unit host the reference direction is the face's tangent.

        An attached balloon takes no part in the layout ranking: it is
        placed from its host, not from the process flow order.
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
        if relation not in RELATIONS:
            raise ValueError(
                f"{self.name}: relation= is what this balloon has to do with "
                f"{getattr(on, 'name', on)!r}, one of "
                f"{', '.join(repr(r) for r in RELATIONS)}, got {relation!r}"
            )
        self.host = on
        self.at = at
        self.offset = float(offset)
        self.angle = float(angle)
        self.relation = relation
        # Where this balloon lands is these five together, and it is
        # resolved inside route(); re-anchoring an already-placed one
        # therefore has to send the sheet round again.
        self._invalidate_layout()
        return self


def _quadrant_codes(where: str, quadrant: str, codes: "str | Sequence[str]") -> tuple[str, ...]:
    """One quadrant's letter codes, in the sequence the standard fixes.

    ISO 15519-2 §5.2.5 fixes the sequence: A, then S, then Z, with the
    value each stands for rising away from the symbol's centre line. The
    author has no choice to express, so the order they wrote is not
    preserved; an alarm, a switch and a trip in one quadrant come out A
    then S then Z outward however they were listed. A code with none of
    the three letters in it keeps its place after those that have one.
    """
    if isinstance(codes, str):
        codes = (codes,) if codes else ()
    out = [str(code).strip() for code in codes]
    for code in out:
        if not code:
            raise ValueError(
                f"{where}: quadrant {quadrant!r} was given an empty letter code. A "
                f"quadrant holds the codes written outside the symbol, e.g. "
                f"high='LAH'; leave the argument out to write nothing there"
            )

    def rank(code: str) -> int:
        # The function letter, which is the one after the measured
        # variable: 'LAH' alarms, 'LSHH' switches, 'LZHH' trips.
        return next((" ASZ".index(c) for c in code[1:] if c in "ASZ"), 4)

    return tuple(sorted(out, key=rank))


def _side_ports(*sides: str) -> list[tuple[str, str, str]]:
    """One inlet and one outlet on each of an exchanger's two sides."""
    return [
        (f"{side}_{end}", direction, "process")
        for side in sides
        for end, direction in (("in", "inlet"), ("out", "outlet"))
    ]


class HeatExchanger(Unit):
    """Heat exchanger, with a nozzle pair on each of its two sides.

    Nozzles are named for the **side of the equipment** they sit on,
    never for the duty the stream carries. Which fluid runs in the shell
    and which in the tubes is a design decision -- fouling service goes
    tube side because tubes can be cleaned, condensing vapour goes shell
    side -- so the drawing records it. Which side is the hot one inverts
    between operating cases while the nozzle stays where it is.

    Most variants are a shell and a tube side. The ones that are neither
    say so: ``air_cooled`` is a tube bundle with air across it,
    ``plate`` and ``spiral`` have two interchangeable channel sets and
    letter them, and ``thin_film`` is an evaporator with a jacket and a
    product side.

    The ``kettle`` variant carries one nozzle more: ``bottoms``, the
    liquid draw at the weir end of the shell, where a tower's bottoms
    product physically leaves.
    """

    # The shell-and-tube nozzles only, since ``_VARIANT_PORTS`` defaults
    # to ``_SHELL_AND_TUBE``. Declaring the other variants' nozzles here
    # (``bottoms``, ``side_a_in``, ``air_in``) would say every
    # HeatExchanger has a ``bottoms`` and make a real mistake type-check
    # clean. They belong on a per-variant subclass; until then reach one
    # by ``hx.port("bottoms")``.
    shell_in: Port
    shell_out: Port
    tube_in: Port
    tube_out: Port

    kind = "hex"
    # Empty because which nozzles an exchanger has depends on its
    # variant, and Unit.__init__ reads PORTS before a variant is in
    # hand. _VARIANT_PORTS below is the declaration, and __init__ lays
    # it down.
    PORTS: list[tuple[str, str, str]] = []
    # The shell-and-tube family, which is what most of the variants are.
    _SHELL_AND_TUBE = _side_ports("shell", "tube")
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_SHELL_AND_TUBE`. A variant that is not a shell and tubes
    #: names its own two sides; only the kettle has a weir to draw off,
    #: and a port the symbol cannot place lands on the box centre.
    _VARIANT_PORTS = {
        "kettle": [*_SHELL_AND_TUBE, ("bottoms", "outlet", "liquid")],
        "air_cooled": _side_ports("tube", "air"),
        "plate": _side_ports("side_a", "side_b"),
        "spiral": _side_ports("side_a", "side_b"),
        "thin_film": _side_ports("jacket", "product"),
    }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        ``__init__`` lays these down *after* ``super().__init__()`` has
        laid down :attr:`~Unit.PORTS`, so a subclass that declares its
        whole nozzle list and inherits this constructor would add
        ``shell_in`` a second time and be refused by
        :meth:`~Unit._add_port`. Asking here lets a per-variant subclass
        be a class body and nothing else.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._SHELL_AND_TUBE)

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # ``self.variant``, not the argument: _VARIANT_PORTS is keyed
        # the way the registry spells a variant, which is what the
        # constructor stored once :attr:`~Unit.VARIANT_ALIASES` had its
        # say.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Heater(Unit):
    """Single-stream heater (utility heating).

    ``utility_in`` is the heating medium's connection: named for what
    lands on it, on the same principle as :class:`HeatExchanger`'s
    nozzles.
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

    ``utility_out`` is the cooling medium's connection, the counterpart
    of :class:`Heater`'s ``utility_in``.
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


class CoolingTower(Unit):
    """Evaporative cooling tower: a water side, and air through it.

    Variants: ``"default"`` and ``"induced_draft"`` are one drawing,
    with the fan on a stack over the fill; ``"forced_draft"`` puts it in
    a housing at the foot of each side instead. That is the whole
    difference between the two machines, and both carry the same six
    nozzles in the same roles, so swapping one for the other moves no
    run.

    Nozzles are named for the **side of the equipment**, as
    :class:`HeatExchanger`'s are: ``water`` for the circulating loop,
    ``air`` for what is drawn or blown through it. Which of the two is
    the hot one is the operating case rather than a fact about the
    tower, so neither is a nozzle name -- the return from the plant is
    ``water_in`` whatever it comes back at.

    Two more are what makes this a tower and not an exchanger. It cools
    by evaporating part of its own inventory, so ``makeup`` replaces
    what leaves as vapour and drift, and ``blowdown`` bleeds off the
    dissolved solids that evaporation leaves behind. Both are drawn on
    the cold-water basin, which is where a plant taps them.

    A declared nozzle is *offered* rather than asserted, which is the
    argument in :class:`Tank`. The air pair is drawn where the machine
    takes its draught and discharges it, and a sheet that pipes neither
    is the ordinary case: the air is ambient at both ends.
    """

    water_in: Port
    water_out: Port
    air_in: Port
    air_out: Port
    # ``utility`` and ``liquid``: the makeup is a service brought to the
    # tower from somewhere else on the plant, and the blowdown is water
    # leaving it. Neither is the circulating loop, which is the pair
    # above.
    makeup: Port
    blowdown: Port

    kind = "cooling_tower"
    PORTS = [
        *_side_ports("water", "air"),
        ("makeup", "inlet", "utility"),
        ("blowdown", "outlet", "liquid"),
    ]


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Names for a unit's feeds: ``feed``, or ``feed_1`` .. ``feed_n``.

    One feed is the common case and keeps the singular name. The symbol
    declares the same rule as a
    :class:`~pandid.render.symbols.PortSeries`, which spreads the family
    down the shell.

    Spelling is the only thing the count changes: ``unit.feeds`` is the
    family either way, a one-tuple where this returns ``["feed"]``.
    """
    if n_feeds < 1:
        raise ValueError(f"{owner} requires at least 1 feed, got {n_feeds}")
    return ["feed"] if n_feeds == 1 else [f"feed_{i}" for i in range(1, n_feeds + 1)]


def _feed_stage_fractions(name: str, internals: str | None, trays: int,
                          feed_stages: list[int | None] | None,
                          feed_names: list[str]) -> dict[str, float]:
    """Validate ``feed_stages`` against ``feed_names`` and turn it into a
    fraction of the shell, per feed that named one.

    ``None`` -- the default -- asks nothing of the shell: every feed keeps
    :class:`~pandid.render.symbols.PortSeries`'s even spread, and a column
    that names no stage is unchanged from the one 0.1.3 drew.

    Given a list, its length has to match the feeds: one entry per feed,
    in declaration order, so ``feed_stages[i]`` is never read against the
    wrong nozzle. An entry may be ``None``: that one feed keeps the even
    spread while its siblings pin to the stage they name, which is what
    lets an author place the solvent and leave the main feed where it
    always was.
    """
    if feed_stages is None:
        return {}
    if len(feed_stages) != len(feed_names):
        raise ValueError(
            f"{name} has {len(feed_names)} feed{'s' if len(feed_names) != 1 else ''} "
            f"({', '.join(feed_names)}) but feed_stages names {len(feed_stages)}; "
            f"give one entry per feed, in the same order, and null for a feed that "
            f"keeps the even spread"
        )
    if internals is None:
        if any(stage is not None for stage in feed_stages):
            raise ValueError(
                f"{name}: feed_stages names a stage, and this column draws no "
                f"stages to put one on -- internals is None, so there is nothing on "
                f"the shell for a reader to count against. Give internals= a deck or "
                f"a bed, or drop feed_stages and let n_feeds spread the feeds evenly"
            )
        return {}
    from pandid.render.iso_parts import stage_fraction
    fractions = {}
    for feed_name, stage in zip(feed_names, feed_stages):
        if stage is None:
            continue
        try:
            fractions[feed_name] = stage_fraction(internals, stage, trays)
        except ValueError as e:
            raise ValueError(f"{name}.{feed_name}: {e}") from None
    return fractions


#: ``plain`` draws a bed ISO does not draw. Its band is filled with
#: **one-way 45-degree hatching** between two solid rules; ISO 10628-2
#: item 27.8 X8141 -- the only packed bed in group 27, and group 27 has
#: exactly eight items -- is a **crossed X between two long-dashed**
#: rules. No item in the group is a hatch. So the variant is a bed drawn
#: with a mark that has no registration number, next to a keyword that
#: draws the one that has.
#:
#: **Not a drop-in, and the message says so.** Measured: ``plain`` is
#: 40 x 95,4 on draw.io's "Vessel (Dished Ends)"; the composed form is
#: 62 x 100 on the vessel ``variant="default"`` draws. Different shell,
#: different mark. ``Vessel(variant='legs')`` is the warning here -- it
#: is deprecated in favour of ``supports='leg'`` and the two are 40 x
#: 122,7 with no parts against 62 x 125 with two, which the sentence an
#: author reads does not mention.
#:
#: Retired rather than kept, because a body is what ``variant=`` chooses
#: and ``plain``'s body is the plain dished-end shell three other
#: spellings already draw. What it adds is its contents, which is the
#: word being spent twice: a ``plain`` reactor cannot also be jacketed,
#: and cannot hold trays or a fluidised bed.
REACTOR_VARIANT_PLAIN = Deprecation(
    what="Reactor(variant='plain')", instead="Reactor(internals='packing')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 27.8 X8141's crossed bed on the "
         "standard vessel shell, in place of this one's diagonal hatch")


#: ``mixing`` is draw.io's "Mixing Reactor": a cone-bottomed rectangle with a
#: capsule perched on top of it for the motor, two flat plates for the
#: impeller, and the whole assembly drawn into the body artwork. It is the
#: drawing ``default`` used to be, and it was kept under a name that says so.
#:
#: **Not equivalent to the composed form, and not pretending to be.** The
#: replacement is ISO item 1.27 X8006: a dished-end cylinder, a group-28
#: stirrer, and item 20.6 C0082's circle marked M above the head. Body,
#: driver mark and stirrer all differ, and so does the box -- 50 x 96,4
#: against 62 x 131,8. Retired anyway, because it is **redundant**:
#:
#: 1. **ISO draws an agitated vessel exactly once**, at item 1.27, and it is
#:    the dished-end one. Group 1 has 29 rows; 1.8 to 1.11 are cone-bottomed
#:    and carry no agitator, and 1.27 carries the agitator and is dished.
#:    There is no cone-bottomed agitated vessel in the standard, so this
#:    variant reproduces no tabulated item.
#: 2. **It spends ``variant=`` on the contents, on the one row where that word
#:    is already contested.** :data:`Reactor._STIRRED` has to exclude it
#:    precisely because the stirrer is in the artwork and a composed one would
#:    make two -- so a ``mixing`` reactor cannot take a stirrer of its own,
#:    cannot be jacketed, and cannot hold a bed or trays. That is the failure
#:    the four keywords were added to end.
#: 3. **Its drawn motor connects to nothing.** The agitator resolves to
#:    ``None`` here, so no ``drive`` is ever added, and the sheet shows a
#:    driver an author cannot route power to. ``Reactor(agitator='disc')``
#:    draws the motor *and* the nozzle.
#:
#: ``disc`` rather than the bare default because ``mixing``'s two flat plates
#: are nearest item 28.9, C2026, "Agitator, disc type".
REACTOR_VARIANT_MIXING = Deprecation(
    what="Reactor(variant='mixing')", instead="Reactor(agitator='disc')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 1.27 X8006's dished-end shell with a "
         "group-28 stirrer and the motor that turns it, in place of this one's "
         "cone-bottomed box and the capsule on top of it; the cone goes, and "
         "the stirrer becomes one you can choose and route a drive to")


class Reactor(Unit):
    """Generic reactor: CSTR, PFR, packed bed, fluidised bed.

    ``vent`` is the off-gas connection at the top of the vessel.
    ``n_feeds`` gives the vessel more than one charge nozzle: ``feed_1``
    ... ``feed_n``, spread down the shell top to bottom, in place of the
    single ``feed``.

    What kind of reactor it is
    --------------------------
    ISO 10628-2 has no reactor group and no reactor symbol. What it has
    is a vessel and the parts you put in one, so that is what pandid
    takes: **the body is ``variant=``, and what is inside it is
    ``agitator=`` and ``internals=``**::

        Reactor("R-101")                              # a CSTR
        Reactor("R-102", agitator="turbine")
        Reactor("R-103", variant="jacketed")          # jacketed CSTR
        Reactor("R-201", internals="packing")         # a PBR
        Reactor("R-202", internals="fluidised_bed")   # a FBR
        Reactor("R-301", variant="tubular")           # a PFR

    - ``agitator=`` names one of the ten ISO group-28 stirrers:
      ``"agitator"`` (the general one, and the default on a stirred
      body), ``"turbine"``, ``"propeller"``, ``"anchor"``, ``"helical"``,
      ``"flat_blade"``, ``"gate_paddle"``, ``"cross_beam"``,
      ``"impeller"``, ``"disc"``. It hangs from the top head on a shaft
      through it, and the shaft runs up to the **drive motor** -- ISO
      item 20.6 C0082, drawn above the vessel, which is what carries the
      ``drive`` connection. Stirrer and motor come together because ISO
      item 1.27 X8006 draws them together: there is no tabulated stirred
      vessel with nothing turning it, so there is no keyword to ask for
      one.
    - ``internals=`` names one of the eight ISO group-27 internals. Two
      of them make a reactor a different reactor: ``"packing"`` is a
      packed bed and ``"fluidised_bed"`` is a fluidised bed.

    Either may be ``None``, which draws that much of the shell bare.

    **Naming internals leaves out the agitator**, because a packed bed,
    a fluidised bed and a set of trays are all ways of not being a
    stirred tank. Name one anyway where the vessel really has both --
    ``Reactor("R-203", agitator="turbine", internals="packing")`` is a
    stirred slurry reactor and is drawn with the stirrer in the bed.

    ``variant=`` chooses the **body**: ``"default"`` the dished-end
    stirred tank, ``"jacketed"`` the same inside a heating jacket,
    ``"tubular"`` the horizontal shell of a plug-flow reactor, and
    ``"mixing"`` the rectangle-with-a-V-bottom that ``"default"`` used to
    draw.
    """

    outlet: Port
    vent: Port
    duty: Port
    # The agitator's shaft where it leaves the top head, present only on
    # a reactor that has one. Declared here for the same reason ``feeds``
    # is: ``__init__`` adds it, and without the annotation it is
    # invisible to mypy and to editor completion.
    drive: Port
    # Every charge nozzle, in declaration order and so top to bottom
    # down the shell, whether the count spelled them ``feed`` or
    # ``feed_1`` ... ``feed_n`` (see :func:`_feed_names`).
    feeds: tuple[Port, ...]
    # The single-feed vessel's charge nozzle. ``n_feeds > 1`` replaces
    # it with a family no annotation can name a member at a time; see
    # :class:`Mixer`.
    feed: Port

    # ``feed_1`` ... ``feed_n`` are the same shape as :class:`Column`'s
    # feeds and :class:`Mixer`'s numbered inlets, and are answered the
    # same way: a literal ``n_feeds`` gets a subclass declaring exactly
    # those nozzles, a computed one gets this class and
    # ``reactor.feeds[i]``.
    #
    # A one-feed vessel keeps the singular ``feed`` -- see
    # :func:`_feed_names` -- so ``Reactor1`` declares nothing of its own
    # and the annotation above answers for it.
    #
    # ``StirredTankReactor`` adds ``duty``, ``outlet`` and ``vent``, but
    # all three are already declared here too -- narrowing this
    # ``__new__`` to ``Reactor2`` loses nothing a stirred tank has. What
    # it *would* break is ``StirredTankReactor``'s own assignability
    # (``t: StirredTankReactor = StirredTankReactor("R")`` wants
    # ``StirredTankReactor``, not ``Reactor2``), so
    # ``scripts/gen_devices.py`` gives every generated subclass of a
    # family base its own overloads and its own ``ClassNameN`` classes
    # rather than reusing the base's. See that file's ``_arity_family``.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, n_feeds: Literal[1] = 1,
                    *args: Any, **kwargs: Any) -> "Reactor1": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[2],
                    *args: Any, **kwargs: Any) -> "Reactor2": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[3],
                    *args: Any, **kwargs: Any) -> "Reactor3": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[4],
                    *args: Any, **kwargs: Any) -> "Reactor4": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[5],
                    *args: Any, **kwargs: Any) -> "Reactor5": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[6],
                    *args: Any, **kwargs: Any) -> "Reactor6": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[7],
                    *args: Any, **kwargs: Any) -> "Reactor7": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[8],
                    *args: Any, **kwargs: Any) -> "Reactor8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int,
                    *args: Any, **kwargs: Any) -> "Reactor": ...
        def __new__(cls, name: str, n_feeds: int = 1,
                    *args: Any, **kwargs: Any) -> "Reactor": ...

    kind = "reactor"
    # Empty because which nozzles a reactor has depends on its variant,
    # and Unit.__init__ reads PORTS before a variant is in hand.
    # _VARIANT_PORTS below is the declaration and __init__ lays it down,
    # exactly as :class:`HeatExchanger` and :class:`Separator` do.
    PORTS: list[tuple[str, str, str]] = []
    # The stirred vessel, and the default: a charge nozzle down the
    # shell, the product out of the bottom, the off-gas off the top and
    # a duty connection for the jacket or coil.
    _VESSEL = [
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("duty", "inlet", "energy"),
    ]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_VESSEL`. Empty today, because both registered drawings are
    #: vertical vessels -- but the reactors that are not are exactly the
    #: ones this table exists for. A tubular reactor is a pipe with a
    #: bed in it: it has no vapour space, so it has no ``vent`` to
    #: connect, and a nozzle nothing is ever routed to is a nozzle an
    #: author has to be told to ignore. Its natural pair is an inlet and
    #: an outlet at opposite ends rather than a charge nozzle in the
    #: shell and a draw in the floor.
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {
        # ...and that is what ``tubular`` is. No vapour space, so no
        # off-gas to take: the ``vent`` the other three carry would be a
        # nozzle nothing is ever routed to, which is a nozzle an author
        # has to be told to ignore.
        "tubular": [
            ("outlet", "outlet", "process"),
            ("duty", "inlet", "energy"),
        ],
    }

    #: The bodies an agitator is fitted to when the author names none. A
    #: stirred tank is what a reactor is unless it says otherwise, so the
    #: two dished-end vessels get one -- but ``mixing`` draws a stirrer in
    #: its own artwork and would come out with two, and neither the
    #: tubular shell nor ``plain``'s hatched bed is stirred at all.
    _STIRRED = ("default", "jacketed")

    #: The agitator depends on the body and on the internals; the
    #: internals depend on neither. So one of the two is
    #: :data:`_UNSTATED` and resolved below.
    COMPOSITION = {"agitator": _UNSTATED, "internals": None}

    @classmethod
    def composition_defaults(cls, variant: str,
                             stated: Mapping[str, Any] | None = None
                             ) -> dict[str, Any]:
        """A stirred body gets item 28.1; the rest get nothing, and so
        does a body the author has put internals in.

        The only place :attr:`_STIRRED` is read. ``__init__`` asks here,
        so "a reactor is a stirred tank unless it says otherwise" is one
        sentence rather than one in the constructor and another wherever
        a reactor has to be written down.

        **Naming internals is saying otherwise.** A packed bed is not
        stirred, a fluidised bed is mixed by its own fluidisation, and a
        trayed vessel is not a tank with a paddle in it -- so an
        unstated agitator on any of them is a stirrer nobody asked for,
        drawn through the bed it would have to turn in. An agitator the
        author *does* name still wins, because a stirred slurry reactor
        is a real vessel and ``agitator="turbine", internals="packing"``
        is how it is asked for. The whole distinction is stated once, by
        whether the constructor was handed :data:`_UNSTATED`.
        """
        return {**super().composition_defaults(variant, stated),
                "agitator": "agitator"
                if variant in cls._STIRRED and (stated or {}).get("internals") is None
                else None}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._VESSEL)

    def __init__(self, name: str, n_feeds: int = 1, variant: str = "default",
                 agitator: str | None = _UNSTATED, internals: str | None = None,
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        names = _feed_names(n_feeds, "Reactor")
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # The argument, not ``self.variant``: a deprecation is about the
        # word the author typed. See :meth:`Vessel.__init__`.
        if variant == "plain":
            REACTOR_VARIANT_PLAIN.warn(self, where=name)
        elif variant == "mixing":
            REACTOR_VARIANT_MIXING.warn(self, where=name)
        if agitator is _UNSTATED:
            agitator = self.composition_defaults(
                self.variant, {"internals": internals})["agitator"]
        self.agitator = agitator
        self.internals = internals
        # Before the feeds, so the declaration order the drawing is read
        # in -- product, off-gas, duty, then the charge nozzles down the
        # shell -- is the order it was in when PORTS held the first
        # three. ``self.variant``, not the argument; see HeatExchanger.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        # The bed first, then the stirrer over it, so the shaft is drawn
        # on top of whatever it turns in rather than under it.
        from pandid.render.iso_parts import agitator_overlays, internals_overlays
        _compose_onto(
            self,
            () if internals is None else internals_overlays(internals),
            () if agitator is None
            else agitator_overlays(agitator, self.kind, self.variant),
        )
        # The drive is the *motor's*, and the motor comes with the
        # agitator, so it exists exactly when the agitator does.
        # Declared here rather than in ``_VARIANT_PORTS`` because the
        # part brings it and the part is chosen per unit, where a
        # variant's nozzles are the same for every unit that names it.
        if agitator is not None:
            self.drive = self._add_port("drive", "inlet", "energy")
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)


if TYPE_CHECKING:
    # A reactor of each feed count, for the overloads above. ``Reactor1``
    # is the one-feed vessel, whose nozzle is the singular ``feed`` the
    # base already declares, so it adds nothing of its own -- exactly as
    # ``Column1`` does.

    class Reactor1(Reactor):
        pass

    class Reactor2(Reactor):
        feed_1: Port
        feed_2: Port

    class Reactor3(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Reactor4(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Reactor5(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Reactor6(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Reactor7(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Reactor8(Reactor):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


#: One per composable characteristic, so the sentence an author reads
#: names the spelling they should type rather than a family -- and one
#: module constant each, so :func:`pandid.deprecation.declarations` can
#: find them. Spelled out rather than built in a comprehension for the
#: same reason: a name a walker cannot see is a retirement nobody is told
#: about.
#:
#: **The cyclone is not here and is not deprecated.** ISO 14617-1 §4.5
#: names X2618 by registration number as a symbol in its own right and
#: group 29 has no vortex to compose one from, so ``variant="cyclone"``
#: is the only way to ask for a hydrocyclone and stays the right way.
#: The same goes for the sifter, the impact separator, the permanent
#: magnet and the scrubber.
SEPARATOR_VARIANT_GRAVITY = Deprecation(
    what="Separator(variant='gravity')",
    instead="Separator(characteristic='gravity')", removed_in="0.2.0")
SEPARATOR_VARIANT_ELECTROSTATIC = Deprecation(
    what="Separator(variant='electrostatic')",
    instead="Separator(characteristic='electrostatic')", removed_in="0.2.0")
SEPARATOR_VARIANT_ELECTROMAGNETIC = Deprecation(
    what="Separator(variant='electromagnetic')",
    instead="Separator(characteristic='electromagnetic')", removed_in="0.2.0")

_SEPARATOR_CHARACTERISTIC_VARIANTS = {
    "gravity": SEPARATOR_VARIANT_GRAVITY,
    "electrostatic": SEPARATOR_VARIANT_ELECTROSTATIC,
    "electromagnetic": SEPARATOR_VARIANT_ELECTROMAGNETIC,
}


class Separator(Unit):
    """Flash drum or phase separator.

    Variants: ``"default"`` is the plain dished-head vertical cylinder,
    the same shell :class:`Vessel` and :class:`Column` are drawn from.
    ``"horizontal"`` is a lying cylinder with dished ends, sharing its
    stencil with ``Vessel(variant="horizontal")``. Use it rather than
    turning the upright one, as a vessel does.

    ``"knockout"`` adds two internals to the upright drum: a demister
    pad and a level gauge, both drawn into the equipment artwork. The
    gauge is *drawn*, not declared, so a level instrument added with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument` puts its own
    balloon beside it rather than replacing it, and the sheet says the
    level is measured twice.

    ``"cyclone"``, ``"gravity"``, ``"scrubber"`` and ``"electrostatic"``
    are the separating bodies that are not drums at all.

    **The draws are named for what leaves, not for the shape of the
    body.** Four variants keep ``vapor`` and ``liquid``, and they are
    the ones where the two really are phases disengaging: the drum in
    its three drawings, and the wet scrubber.

    The other seven draw ``overflow``, high on the body, and
    ``underflow``, out of the apex: the four **mechanical** separators
    (``"sifter"``, ``"impact"``, ``"permanent_magnet"``,
    ``"electromagnetic"``), which sort by size, inertia or magnetism,
    and the three **dust collectors** (``"cyclone"``, ``"gravity"``,
    ``"electrostatic"``), whose catch is a hopper full of solids. The
    pair names the two *positions* the artwork draws. Neither name says
    which of the two is the product: a cyclone on a spray dryer recovers
    its product from the underflow, and the identical cyclone on a vent
    line throws that same catch away.

    The three collectors called their catch ``vapor`` and ``liquid`` up
    to 0.1.1, ``overflow`` and ``underflow`` since 0.1.2. The old pair
    is gone as of 0.1.3: a sheet written against it raises.

    Every variant is drawn one way up and reported as ``gravity-turned``
    by :meth:`~pandid.flowsheet.Flowsheet.validate` if turned, which is
    ISO 15519-1 §11.4.2's exception for symbols where gravity is a
    functionality.

    How it separates
    ----------------
    ``characteristic=`` names one of the three ISO 10628-2 group-29
    internal characteristics the standard composes a separating vessel
    from -- the mark inside the body that says what does the work::

        Separator("V-201", characteristic="gravity")          # 8.3 X8031
        Separator("V-202", characteristic="electrostatic")    # 8.6 X8125
        Separator("V-203", characteristic="electromagnetic")  # 8.8 X8126

    Three, and only three, because those are the three group-8 rows whose
    every mark is a numbered part. **A cyclone is not one of them**: it
    is X2618, a registered symbol in its own right whose helical vortex
    appears nowhere in group 29, so it stays ``variant="cyclone"``. So do
    the sifter, the impact separator, the permanent magnet and the
    scrubber.
    """

    # The phase draws only, since ``_VARIANT_PORTS`` defaults to
    # ``_PHASES``. ``overflow`` and ``underflow`` are absent: seven of
    # the eleven variants have them *instead of* ``vapor`` and
    # ``liquid``, never as well, so declaring all four would tell a
    # checker a plain flash drum has an ``overflow``. They belong on a
    # per-variant subclass, which ``pandid.devices`` is; off it, reach
    # one by ``sep.port("overflow")``.
    feed: Port
    vapor: Port
    liquid: Port

    kind = "separator"
    # Empty because which nozzles a separator has depends on its
    # variant, and Unit.__init__ reads PORTS before a variant is in
    # hand. _VARIANT_PORTS below is the declaration and __init__ lays it
    # down, as HeatExchanger does.
    PORTS: list[tuple[str, str, str]] = []
    # The flash drum, and the default.
    _PHASES = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]
    # A high draw and a low draw: the most the drawing supports, and the
    # vocabulary classification and solid-liquid separation already use.
    # The four mechanical stencils are one body, anchor for anchor -- a
    # box with a hopper under it, the feed high on one wall (0, 12), one
    # draw high on the opposite wall (80, 12) and one out of the apex
    # (40, 120) -- while the three collectors put the high draw at the
    # top of the vortex or chamber, so the pair names positions and not
    # coordinates.
    #
    # ``process`` rather than ``vapor``/``liquid``: what leaves is dry
    # dust, tramp metal or a screened size fraction, and the role
    # vocabulary has no word for those. Nothing drawn depends on the
    # difference -- outside ``signal``, and ``energy``/``utility`` on
    # both ends of one stream, ``connect()`` and the renderer never read
    # a role.
    _OVER_AND_UNDER = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    #: The nozzles each variant has, keyed by variant, defaulting to
    #: :data:`_PHASES`. ``default``, ``horizontal``, ``knockout`` and
    #: ``scrubber`` are absent: they are the four whose draws really are
    #: phases.
    _VARIANT_PORTS = {
        "cyclone": _OVER_AND_UNDER,
        "gravity": _OVER_AND_UNDER,
        "electrostatic": _OVER_AND_UNDER,
        "sifter": _OVER_AND_UNDER,
        "impact": _OVER_AND_UNDER,
        "permanent_magnet": _OVER_AND_UNDER,
        "electromagnetic": _OVER_AND_UNDER,
    }
    #: The name each renamed draw is anchored under in the *artwork*,
    #: keyed by variant. The three collectors' stencils still anchor
    #: ``vapor`` and ``liquid``: this is a rename of the nozzle, not a
    #: redrawing of the symbol.
    #:
    #: Keyed by variant rather than declared in
    #: :attr:`Unit.PORT_ANCHORS` because eight of the eleven drawings
    #: anchor what they are asked for, and a class-wide dict would send
    #: a sifter's ``overflow`` to a ``vapor`` anchor its stencil does
    #: not have -- which is a nozzle on the centre of the box.
    _VARIANT_ANCHORS = {
        "cyclone": {"overflow": "vapor", "underflow": "liquid"},
        "gravity": {"overflow": "vapor", "underflow": "liquid"},
        "electrostatic": {"overflow": "vapor", "underflow": "liquid"},
        # ``electromagnetic`` joins the three above now that it is drawn
        # by composition rather than from its own stencil. Its stencil
        # anchored ``overflow`` and ``underflow`` directly; the
        # separating vessel the composition is built on anchors what the
        # other two composed drawings anchor, since it is one body
        # carrying three different marks and a body has one set of
        # nozzles.
        "electromagnetic": {"overflow": "vapor", "underflow": "liquid"},
    }

    #: The three drawings that are the shared separating vessel carrying
    #: one ISO group-29 characteristic, and so the three the keyword
    #: names. The registry builds each by composition and records the
    #: registration number ISO gives the result; see
    #: :meth:`pandid.render.symbols.SymbolRegistry._register_composed`.
    _CHARACTERISTICS = ("gravity", "electrostatic", "electromagnetic")

    #: A separating vessel carries no mark unless one is named. The
    #: constructor then folds the name into :attr:`variant`, which is
    #: what :attr:`COMPOSITION_VARIANT` below says out loud.
    COMPOSITION = {"characteristic": None}
    COMPOSITION_VARIANT = "characteristic"

    def _symbol_anchor(self, port_name: str) -> str:
        """The name this separator's art anchors ``port_name`` under.

        :attr:`_VARIANT_ANCHORS` first, then the base's, so a subclass
        that states a rename of its own in :attr:`Unit.PORT_ANCHORS`
        still gets it.
        """
        renamed = self._VARIANT_ANCHORS.get(self.variant, {})
        return renamed.get(port_name) or super()._symbol_anchor(port_name)

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._PHASES)

    def __init__(self, name: str, variant: str = "default",
                 characteristic: str | None = None,
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        if characteristic is not None:
            if variant != "default":
                raise ValueError(
                    f"{name}: characteristic={characteristic!r} and variant={variant!r} "
                    f"both choose the drawing, and they disagree. The characteristic is "
                    f"the mark inside the separating vessel, so it *is* the variant: "
                    f"drop one of the two"
                )
            if characteristic not in self._CHARACTERISTICS:
                raise ValueError(
                    f"{name}: {characteristic!r} is not an ISO 10628-2 group-29 "
                    f"characteristic pandid composes a separator from; it draws "
                    f"{', '.join(repr(c) for c in self._CHARACTERISTICS)}. A cyclone, a "
                    f"sifter, an impact separator, a permanent magnet and a scrubber "
                    f"are distinct registered symbols rather than a body plus a mark, "
                    f"so each is a variant= of its own"
                )
            variant = characteristic
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        # The argument, not ``self.variant``: a deprecation is about the
        # word the author typed, and this is the class where the two came
        # apart. :class:`~pandid.devices.GravitySeparator` and
        # :class:`~pandid.devices.ElectrostaticPrecipitator` alias
        # ``default`` to the retired spelling, so reading the resolved
        # one told a ``GravitySeparator("V-1")`` author to write
        # ``Separator(characteristic='gravity')`` instead of the class
        # they had already picked -- for a variant they never named. See
        # :meth:`Vessel.__init__` for why a deprecation table and a ports
        # table want opposite spellings.
        if characteristic is None and variant in self._CHARACTERISTICS:
            _SEPARATOR_CHARACTERISTIC_VARIANTS[variant].warn(self, where=name)
        self.characteristic = (
            self.variant if self.variant in self._CHARACTERISTICS else None)
        # ``self.variant`` rather than the argument; see HeatExchanger.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


#: How many decks a tower is drawn with when the author does not say.
#: A number, because a drawing has to pick one and no number is the real
#: tray count anyway -- a forty-tray column is not drawn with forty lines
#: on any sheet. **Eight**, which is what ISO 10628-2 item 2.6 X8011
#: draws: eight decks at a 2 M pitch down a 16 M straight side.
DEFAULT_TRAYS = 8


class Column(Unit):
    """Distillation or absorption column.

    Besides the feed and the two products, a column has two *return*
    nozzles that close its internal loops: ``reflux_in`` (liquid back to
    the top from the reflux drum) and ``boilup_in`` (vapour back to the
    bottom from the reboiler).

    ``n_feeds`` gives the tower more than one feed nozzle: an extractive
    distillation takes its solvent above the feed tray, an azeotropic
    tower its entrainer. They are ``feed_1`` ... ``feed_n``, spread down
    the shell in declaration order, so ``feed_1`` is the highest; the
    single-feed column keeps the plain ``feed``.

    What is inside it
    -----------------
    **A column is drawn bare; ``internals=`` furnishes it.** ISO
    10628-2's group 2 is not a separate vocabulary of towers; it is one
    dished-end shell carrying one group-27 internal, drawn N times. The
    standard's own general column is item 2.1 X8100 and it carries
    nothing; the tray tower is the *separate* item 2.2 X8101. So a
    column nobody has furnished draws the first of those, not the
    second::

        Column("T-101")                                    # a bare shell
        Column("T-102", internals="tray")                  # a tray tower
        Column("T-103", internals="bubble_cap_tray", trays=12)
        Column("T-104", internals="valve_tray", trays=30)
        Column("T-105", internals="packing", trays=2)      # two beds

    The eight names are ISO's: ``"tray"`` (27.1), ``"baffle_tray"``,
    ``"bubble_cap_tray"``, ``"valve_tray"``, ``"sieve_tray"``,
    ``"filter_insert"``, ``"fluidised_bed"`` and ``"packing"``.

    ``trays=`` counts whatever ``internals=`` names: decks for a deck,
    beds for a bed, and nothing at all where ``internals`` is ``None``.
    The default is :data:`DEFAULT_TRAYS`, the eight of ISO item 2.6
    X8011.

    An absorber, a stripper, a scrubbing tower, an adsorber and a
    molecular sieve are **not distinct drawings** and ISO gives them no
    symbols. Each is this shell carrying whichever internal it really
    contains, told apart by its tag.

    Where a feed enters
    -------------------
    Left alone, ``n_feeds`` nozzles spread evenly down the shell -- a
    placement with no process meaning. ``feed_stages=`` says which stage
    each feed actually enters on, in the same count ``trays=`` gives::

        Column("T-101", internals="valve_tray", trays=30,
               n_feeds=2, feed_stages=[12, 22])

    One entry per feed, in declaration order, top of the shell to bottom.
    ``None`` in place of a stage leaves that one feed on the even spread,
    so ``feed_stages=[12, None]`` pins the solvent and leaves the main
    feed exactly where it always was. A stage is 1 at the top of the
    shell to ``trays`` at the bottom -- the same numbering the tray count
    itself is given in -- and a stage the column does not have is
    refused, naming the count it does. Naming a stage on a column with
    no ``internals=`` is refused too: there is nothing on the shell for a
    reader to count against.
    """

    distillate: Port
    bottoms: Port
    reflux_in: Port
    boilup_in: Port
    reboiler_duty: Port
    condenser_duty: Port
    # Every feed nozzle, in declaration order and so highest first,
    # whatever the count spelled them. See :class:`Reactor`.
    feeds: tuple[Port, ...]
    # The single-feed tower's nozzle; ``n_feeds > 1`` replaces it with a
    # family that cannot be declared a member at a time. See
    # :class:`Mixer`.
    feed: Port


    # ``feed_1`` ... ``feed_n`` are the same shape as :class:`Mixer`'s
    # numbered inlets and are answered the same way: a literal
    # ``n_feeds`` gets a subclass declaring exactly those nozzles, a
    # computed one gets this class and ``col.feeds[i]``.
    #
    # A one-feed tower keeps the singular ``feed`` -- see
    # :func:`_feed_names` -- so ``Column1`` declares nothing of its own
    # and the annotation above answers for it.
    #
    # :class:`Reactor` spells the same family and takes the same
    # treatment; see its own comment for the subclass wrinkle that has
    # nothing to do with feeds and does not touch a column, which has no
    # subclass to protect.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, n_feeds: Literal[1] = 1,
                    *args: Any, **kwargs: Any) -> "Column1": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[2],
                    *args: Any, **kwargs: Any) -> "Column2": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[3],
                    *args: Any, **kwargs: Any) -> "Column3": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[4],
                    *args: Any, **kwargs: Any) -> "Column4": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[5],
                    *args: Any, **kwargs: Any) -> "Column5": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[6],
                    *args: Any, **kwargs: Any) -> "Column6": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[7],
                    *args: Any, **kwargs: Any) -> "Column7": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[8],
                    *args: Any, **kwargs: Any) -> "Column8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int,
                    *args: Any, **kwargs: Any) -> "Column": ...
        def __new__(cls, name: str, n_feeds: int = 1,
                    *args: Any, **kwargs: Any) -> "Column": ...

    kind = "column"
    PORTS = [
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reflux_in", "inlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]

    #: Nothing is drawn inside a column nobody has furnished. ISO's own
    #: general column, item 2.1 X8100, carries no internal, and the tray
    #: tower is the separate item 2.2 X8101 -- so defaulting to a deck
    #: would assert a tray count the author never gave, and would say it
    #: of every absorber, stripper and adsorber drawn through this class
    #: too. The count does not depend on the body: eight is eight of
    #: whatever is drawn, and of nothing where nothing is.
    #:
    #: No :meth:`composition_defaults` override, deliberately. The
    #: answer no longer turns on which body is drawn, and the override
    #: existed only to keep the general shell's default deck out of
    #: ``packed``, which draws two beds on their support grids in its
    #: own artwork and would have come out with a third.
    COMPOSITION = {"internals": None, "trays": DEFAULT_TRAYS}

    def __init__(self, name: str, n_feeds: int = 1, variant: str = "default",
                 internals: str | None = _UNSTATED, trays: int = DEFAULT_TRAYS,
                 feed_stages: list[int | None] | None = None,
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        names = _feed_names(n_feeds, "Column")
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        if internals is _UNSTATED:
            internals = self.composition_defaults(self.variant)["internals"]
        self.internals = internals
        self.trays = trays
        from pandid.render.iso_parts import internals_overlays
        _compose_onto(self, () if internals is None
                      else internals_overlays(internals, trays))
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        self.feed_stages = feed_stages
        self._feed_stage_fractions = _feed_stage_fractions(
            name, internals, trays, feed_stages, names)

    def _series_pin(self, port_name: str) -> float | None:
        return self._feed_stage_fractions.get(port_name)



if TYPE_CHECKING:
    # A column of each feed count, for the overloads above. ``Column1``
    # is the one-feed tower, whose nozzle is the singular ``feed`` the
    # base already declares, so it adds nothing and exists only so the
    # overload for ``Literal[1]`` has something to name.

    class Column1(Column):
        pass

    class Column2(Column):
        feed_1: Port
        feed_2: Port

    class Column3(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Column4(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Column5(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Column6(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Column7(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Column8(Column):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


class Absorber(Column):
    """Absorption or scrubbing tower: a solute moves from a gas into a liquid.

    :class:`Column` again -- ISO gives an absorber, a scrubber and a
    molecular sieve no symbol of its own, so the drawing is the same
    dished-end shell carrying whichever group-27 internal it really
    holds, exactly as the module docstring already says. What earns this
    class is not the picture but the **ports**: an absorber has no
    reboiler, no condenser and no internal reflux loop, because nothing
    in the tower boils. Gas enters at the bottom and lean liquid at the
    top; treated gas leaves over ``distillate`` and rich liquid over
    ``bottoms``, and the two counter-current inlets are ``n_feeds=2``,
    placed on the trays they actually enter::

        Absorber("V-501", internals="packing",
                 n_feeds=2, feed_stages=[1, 8])

    ``reflux_in``, ``boilup_in``, ``reboiler_duty`` and ``condenser_duty``
    are **not on this class**. A plain :class:`Column` pressed into
    service as an absorber carries all four, unconnected, and nothing
    then stops an author wiring one of them to a stream the vessel does
    not have -- the false statement this class exists to rule out. See
    :class:`Stripper` for the shell with a reboiler and no condenser, and
    ``scripts/gen_devices.py``'s module docstring for the rule both
    classes are the first to be justified under: a **reduced port set**,
    with no distinct drawing behind it at all.

    Defaults to ``internals="packing"``, because absorbers are packed,
    trayed or -- for a coarse duty -- run as a bare spray tower more
    often than a distillation column is drawn bare. ``trays=`` and every
    other knob :class:`Column` offers are still here: a trayed absorber
    is a normal absorber, not a different class of tower.
    """

    kind = "column"
    PORTS = [
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    distillate: Port
    bottoms: Port

    #: The one default this class narrows: an unfurnished absorber is
    #: rarer than an unfurnished column, so ``internals=`` defaults to a
    #: bed rather than to bare shell. ``trays=`` keeps :class:`Column`'s
    #: own default -- the count means the same thing on both classes and
    #: neither has a reason to disagree with the other about it.
    COMPOSITION = {"internals": "packing", "trays": DEFAULT_TRAYS}

    # Copied from :class:`Column`'s own overloads rather than inherited:
    # a literal ``n_feeds`` has to resolve to ``Absorber2``, not
    # ``Column2``, or ``t: Absorber = Absorber("V-1")`` is an error the
    # moment a checker sees it -- see ``StirredTankReactor``'s comment in
    # ``scripts/gen_devices.py`` for the general argument.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, n_feeds: Literal[1] = 1,
                    *args: Any, **kwargs: Any) -> "Absorber1": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[2],
                    *args: Any, **kwargs: Any) -> "Absorber2": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[3],
                    *args: Any, **kwargs: Any) -> "Absorber3": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[4],
                    *args: Any, **kwargs: Any) -> "Absorber4": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[5],
                    *args: Any, **kwargs: Any) -> "Absorber5": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[6],
                    *args: Any, **kwargs: Any) -> "Absorber6": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[7],
                    *args: Any, **kwargs: Any) -> "Absorber7": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[8],
                    *args: Any, **kwargs: Any) -> "Absorber8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int,
                    *args: Any, **kwargs: Any) -> "Absorber": ...
        def __new__(cls, name: str, n_feeds: int = 1,
                    *args: Any, **kwargs: Any) -> "Absorber": ...


if TYPE_CHECKING:

    class Absorber1(Absorber):
        pass

    class Absorber2(Absorber):
        feed_1: Port
        feed_2: Port

    class Absorber3(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Absorber4(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Absorber5(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Absorber6(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Absorber7(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Absorber8(Absorber):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


class Stripper(Column):
    """Stripping column: a light component is driven out of a liquid by heat.

    :class:`Column` again, for :class:`Absorber`'s reason -- the drawing
    is one dished-end shell, and what a stripper draws is picked by
    ``internals=`` the same way an absorber's or a plain distillation
    column's is. What earns this class is again the **ports**: a
    stripper carries a reboiler and the vapour it returns, but nothing
    condenses and nothing refluxes, because what leaves the top is the
    stripped-out product itself, not something the tower recovers and
    sends back down. ``distillate``, ``bottoms``, ``reboiler_duty`` and
    ``boilup_in`` are here; ``reflux_in`` and ``condenser_duty`` are not
    -- two of :class:`Column`'s four return nozzles rather than
    :class:`Absorber`'s none, because a stripper still reboils even
    though it never refluxes.

    ``internals=`` and ``trays=`` are unchanged from :class:`Column`: a
    stripper is at least as often trayed as packed, so unlike
    :class:`Absorber` this class states no default of its own.
    """

    kind = "column"
    PORTS = [
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
    ]

    distillate: Port
    bottoms: Port
    boilup_in: Port
    reboiler_duty: Port

    # See :class:`Absorber`'s comment on the same block: a literal
    # ``n_feeds`` has to resolve to ``Stripper2``, not ``Column2``.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, n_feeds: Literal[1] = 1,
                    *args: Any, **kwargs: Any) -> "Stripper1": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[2],
                    *args: Any, **kwargs: Any) -> "Stripper2": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[3],
                    *args: Any, **kwargs: Any) -> "Stripper3": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[4],
                    *args: Any, **kwargs: Any) -> "Stripper4": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[5],
                    *args: Any, **kwargs: Any) -> "Stripper5": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[6],
                    *args: Any, **kwargs: Any) -> "Stripper6": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[7],
                    *args: Any, **kwargs: Any) -> "Stripper7": ...

        @overload
        def __new__(cls, name: str, n_feeds: Literal[8],
                    *args: Any, **kwargs: Any) -> "Stripper8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int,
                    *args: Any, **kwargs: Any) -> "Stripper": ...
        def __new__(cls, name: str, n_feeds: int = 1,
                    *args: Any, **kwargs: Any) -> "Stripper": ...


if TYPE_CHECKING:

    class Stripper1(Stripper):
        pass

    class Stripper2(Stripper):
        feed_1: Port
        feed_2: Port

    class Stripper3(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Stripper4(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Stripper5(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Stripper6(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Stripper7(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Stripper8(Stripper):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


# ----------------------------------------------------------------
# Variable-port unit types
# ----------------------------------------------------------------


class Mixer(Unit):
    """Combines multiple inlet streams into one outlet.

    A piece of plant, drawn as a triangle and scheduled as one. Where
    two lines simply meet in the piping, the fitting is a :class:`Tee`.
    """

    # Every inlet, in declaration order, and the canonical statement of
    # why a variable-port family is declared as a *sequence*. The four
    # other families refer here.
    #
    # ``n`` is the caller's, chosen per instance, so the set of
    # attribute names is a property of the object and not of the class
    # and no class annotation can name ``in_1`` ... ``in_n`` a member at
    # a time. A generated class per arity would not help either, since
    # ``Mixer("M-1", n_inlets=len(feeds))`` is not a literal.
    #
    # ``inlets`` holds the same ``Port`` objects, so ``m.inlets[0]`` is
    # a ``Port`` and ``len(m.inlets)`` is honest. **It is indexed from
    # zero while the nozzles are numbered from one**: ``m.inlets[0]`` is
    # ``in_1``.
    #
    # Where the number is wanted, ``m.in_3`` is the plain spelling and
    # resolves to ``Port`` in a checker -- see the ``__getattr__`` below,
    # which exists for it. ``m.port("in_3")`` is the same nozzle where
    # the name is computed, and ``enumerate(m.inlets, start=1)`` gives
    # the number and the port together.
    inlets: tuple[Port, ...]
    # The one nozzle every mixer has, declared like any other fixed one.
    outlet: Port


    # ``in_1`` ... ``in_n`` are real attributes at run time and no
    # annotation can name them: ``n`` is the caller's. But a checker
    # *can* be told what a **literal** count builds, and that is every
    # call this library has ever been written with -- there is not one
    # ``n_inlets=len(...)`` in the examples or the suite.
    #
    # So the overloads below hand a literal count back a subclass that
    # declares exactly those nozzles, and a computed one back this
    # class, which declares none of them. ``Mixer("M", n_inlets=3).in_3``
    # is a ``Port``; ``.in_4`` and ``.outlt`` are both errors, which a
    # blanket ``__getattr__`` could not have said. The subclasses exist
    # only under ``TYPE_CHECKING``: nothing is built at run time, the
    # object really is a ``Mixer``, and every one of them is assignable
    # to ``Mixer`` for anything that annotates the base.
    #
    # Where the count *is* computed, ``m.inlets[i]`` is the typed route
    # and the honest one -- a checker cannot know how many nozzles
    # ``n_inlets=len(feeds)`` made, and saying it did would be a lie
    # rather than a limitation.
    #
    # ``*args``/``**kwargs`` on the overloads rather than the real
    # signature repeated nine times: ``__new__`` takes what
    # ``__init__`` takes, and ``__init__`` right below is the one
    # declaration of it.
    if TYPE_CHECKING:
        @overload
        def __new__(cls, name: str, n_inlets: Literal[1],
                    *args: Any, **kwargs: Any) -> "Mixer1": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[2] = 2,
                    *args: Any, **kwargs: Any) -> "Mixer2": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[3],
                    *args: Any, **kwargs: Any) -> "Mixer3": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[4],
                    *args: Any, **kwargs: Any) -> "Mixer4": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[5],
                    *args: Any, **kwargs: Any) -> "Mixer5": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[6],
                    *args: Any, **kwargs: Any) -> "Mixer6": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[7],
                    *args: Any, **kwargs: Any) -> "Mixer7": ...

        @overload
        def __new__(cls, name: str, n_inlets: Literal[8],
                    *args: Any, **kwargs: Any) -> "Mixer8": ...

        @overload
        def __new__(cls, name: str, n_inlets: int,
                    *args: Any, **kwargs: Any) -> "Mixer": ...
        def __new__(cls, name: str, n_inlets: int = 2,
                    *args: Any, **kwargs: Any) -> "Mixer": ...

    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        # Built from what the loop that creates the family hands back,
        # rather than by matching ``in_`` against the ``ports`` dict
        # afterwards, which would be the naming rule written twice.
        self.inlets = tuple(
            self._add_port(f"in_{i}", "inlet", "process") for i in range(1, n_inlets + 1)
        )
        self._add_port("outlet", "outlet", "process")



if TYPE_CHECKING:
    # A mixer of each arity, for the overloads above to hand back.
    #
    # Declared here and not generated in a loop, because a checker reads
    # the source and not the objects: a class built by ``type()`` at
    # import time is invisible to Pyright and to mypy alike, which is
    # the whole point of these. Nothing is built at run time either --
    # ``TYPE_CHECKING`` is False there and this block does not execute.

    class Mixer1(Mixer):
        in_1: Port

    class Mixer2(Mixer):
        in_1: Port
        in_2: Port

    class Mixer3(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port

    class Mixer4(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Mixer5(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Mixer6(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Mixer7(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Mixer8(Mixer):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Splitter(Unit):
    """Divides one inlet stream into multiple outlets.

    A piece of plant, drawn as a triangle and scheduled as one. A bypass
    leg, a drain, a vent or a sample point is a line branching, and the
    fitting that branches it is a :class:`Tee`.
    """

    # The one nozzle every splitter has.
    inlet: Port
    # Every outlet, in declaration order. ``out_1`` ... ``out_n`` are
    # the caller's count and the family is what is declared; see
    # :class:`Mixer`.
    outlets: tuple[Port, ...]

    # The mirror of :class:`Mixer`'s: a literal ``n_outlets`` gets a
    # subclass declaring exactly ``out_1`` ... ``out_n``, a computed one
    # gets this class and ``outlets[i]``. See :class:`Mixer` for why.
    if TYPE_CHECKING:
        @overload
        def __new__(cls, name: str, n_outlets: Literal[1],
                    *args: Any, **kwargs: Any) -> "Splitter1": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[2] = 2,
                    *args: Any, **kwargs: Any) -> "Splitter2": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[3],
                    *args: Any, **kwargs: Any) -> "Splitter3": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[4],
                    *args: Any, **kwargs: Any) -> "Splitter4": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[5],
                    *args: Any, **kwargs: Any) -> "Splitter5": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[6],
                    *args: Any, **kwargs: Any) -> "Splitter6": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[7],
                    *args: Any, **kwargs: Any) -> "Splitter7": ...

        @overload
        def __new__(cls, name: str, n_outlets: Literal[8],
                    *args: Any, **kwargs: Any) -> "Splitter8": ...

        @overload
        def __new__(cls, name: str, n_outlets: int,
                    *args: Any, **kwargs: Any) -> "Splitter": ...
        def __new__(cls, name: str, n_outlets: int = 2,
                    *args: Any, **kwargs: Any) -> "Splitter": ...

    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None, description: str = "", reference: str = ""):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, width=width, height=height, description=description, reference=reference)
        self._add_port("inlet", "inlet", "process")
        self.outlets = tuple(
            self._add_port(f"out_{i}", "outlet", "process") for i in range(1, n_outlets + 1)
        )



if TYPE_CHECKING:
    # A splitter of each arity; see the mixers above.
    #
    # Declared here and not generated in a loop, because a checker reads
    # the source and not the objects: a class built by ``type()`` at
    # import time is invisible to Pyright and to mypy alike, which is
    # the whole point of these. Nothing is built at run time either --
    # ``TYPE_CHECKING`` is False there and this block does not execute.

    class Splitter1(Splitter):
        out_1: Port

    class Splitter2(Splitter):
        out_1: Port
        out_2: Port

    class Splitter3(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port

    class Splitter4(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port

    class Splitter5(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port

    class Splitter6(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port

    class Splitter7(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port
        out_7: Port

    class Splitter8(Splitter):
        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port
        out_7: Port
        out_8: Port


def _block_faces(spec: "int | Sequence[str]", default: str, owner: str,
                 argument: str) -> list[str]:
    """Read a :class:`Block`'s ``inputs=``/``outputs=``, a face each.

    A plain count is the common case spelled short: ``inputs=3`` is
    three connections on the default face, west for a feed and east for
    a product. A sequence names the face of each one in order, which is
    what a block flow diagram needs -- a section takes its charge from
    the left and its recycle from above, and both are inputs.
    """
    if isinstance(spec, bool) or not isinstance(spec, (int, Sequence)) or isinstance(spec, str):
        # A bare string is the trap: ``inputs="W"`` is a sequence of one
        # character, so it would read as one connection on the west and
        # work quietly until somebody writes ``inputs="WN"``.
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
    """One face name, in the vocabulary :meth:`Unit.nozzle` takes.

    The compass point, or the ``top``/``bottom``/``left``/``right``
    spelling ``label_pos`` uses. The constructor and
    :meth:`Block.nozzle` both come through here, so both raise the same
    sentence.
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
    """A block flow diagram's box: a section as a labelled rectangle.

    The BFD is the drawing a level above the PFD, and this is the only
    symbol on it. One box is a whole plant section -- *Reaction*,
    *Compression*, *Product Recovery* -- with the streams between them
    named and nothing inside them drawn. It carries no equipment
    vocabulary: no suction, no bottoms, no vent. It has connections, and
    the only thing the drawing says about one is which side it is on.

    .. code-block:: python

        rx = fs.add(units.Block("Reaction",
                                inputs=["W", "W", "N"],
                                outputs=["E", "S"]))
        fs.connect(feed.outlet, rx.in_1)      # west
        fs.connect(recycle.out_1, rx.in_3)    # north
        fs.connect(rx.out_2, drain.inlet)     # south

    ``inputs`` and ``outputs`` are **one face per connection**, in
    order, and a plain count is the shorthand for the common case:
    ``inputs=3`` is three on the west, ``outputs=2`` two on the east.
    The nozzles are ``in_1`` ... ``in_n`` and ``out_1`` ... ``out_m``,
    numbered across the whole family rather than per face.

    Those two arguments are named for what they *declare*; the accessors
    are named for what they *return*: :attr:`inlets` and :attr:`outlets`
    are the connections, :attr:`input_faces` and :attr:`output_faces`
    the sides they are on.

    **A face is a placement, and the engine reads it.** A connection on
    the north puts its peer in the row above and in the same column, one
    on the south puts it below, so a block flow diagram lays itself out
    without a coordinate anywhere. See :mod:`pandid.layout.stacking`.
    ``examples/12_block_flow_diagram.py`` is pinned all the same: a
    hand-placed BFD says which sections the reader takes in a row, which
    is not something the ranking can know.

    **A face names the box's own side, not the reader's.** ``"N"`` is
    the top of the block as declared; a :meth:`pin` that turns or
    mirrors it moves the box and every connection with it, so that
    connection is drawn on the east of a block turned a quarter. This is
    where :meth:`nozzle` differs from :meth:`Unit.nozzle`.
    :func:`pandid.portgeom.port_faces` answers about the finished sheet.

    **The box sizes itself to what it carries.** A family squeezed to
    fit a fixed box draws arrowheads that touch and read as one blob, so
    the height follows the west and east counts and the width follows
    the north and south ones, at a pitch derived from the arrowhead the
    renderer draws (:data:`~pandid.render.symbols.BLOCK_PITCH`). The
    width also clears the name, which a BFD letters inside the box.

    ``width``/``height`` still win where they are given, and a box too
    small to draw the connections at that pitch is **refused** wherever
    it is asked for: the constructor, a later assignment, :meth:`nozzle`
    and :meth:`pin`, the last of which is where a quarter turn can put a
    run on the shorter axis.

    A width the author gave also wins over the name, which then hangs
    out of both ends of the box. The name is written on an opaque halo,
    so an overhanging one **erases whatever is drawn beside it**. Leave
    ``width`` off and it cannot happen.

    **Variants**: none.
    """

    # No individual nozzle annotation, not even one: every connection a
    # block has is one of the two families, whose size is the caller's,
    # so ``in_1: Port`` would be wrong for
    # ``Block("B", inputs=0, outputs=2)``. See :class:`Mixer` for the
    # general argument. Either family may be the empty tuple.
    #
    # ``tests/test_port_annotations.py`` pins the five classes that
    # declare a family in ``_DECLARED_FAMILIES``.
    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]

    # ``in_1`` ... ``in_n`` are real attributes at run time, and a checker
    # cannot be told their names because ``n`` is the caller's -- so a
    # reader writing the spelling this class exists for was told
    # "Cannot access attribute" by Pyright and ``attr-defined`` by mypy.
    # This answers with the family's own type instead.
    #
    # **The cost is paid on this class and nowhere else.**
    # :meth:`Unit.__getattr__` stays hidden, so ``reactor.fed`` and
    # ``sep.liqid`` are still refused; what gives typo detection up is a
    # class whose attribute set is genuinely open, where the numbered
    # nozzles outnumber the fixed ones. A typo still raises at run time
    # on the first access, listing every real nozzle, and the declared
    # annotations above still win over this -- ``outlet`` resolves to
    # the nozzle, not to the fallback.
    #
    # Not done for :class:`Column` and :class:`Reactor`, whose
    # ``feed_1`` ... ``feed_n`` are the same shape: they carry six and
    # seven fixed nozzles apiece, so the trade runs the other way and
    # ``col.feeds`` or ``col.port("feed_2")`` is the typed route there.
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Port: ...

    kind = "block"

    #: The face a connection is put on when the author gives a count
    #: rather than a list: west in, east out, the direction the rest of
    #: the library draws a sheet in.
    DEFAULT_INPUT_FACE = "W"
    DEFAULT_OUTPUT_FACE = "E"

    # Class-level backing for the two properties below, so
    # ``Unit.__init__``'s ``self.width = width`` has somewhere to land
    # before this class has built anything of its own.
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
        #: connection name -> the face it leaves from, in port order.
        #: The single authority: the symbol is built from it.
        self._faces: dict[str, str] = {}
        self.inlets = tuple(self._add_connection(f"in_{i}", "inlet", face)
                            for i, face in enumerate(in_faces, start=1))
        self.outlets = tuple(self._add_connection(f"out_{i}", "outlet", face)
                             for i, face in enumerate(out_faces, start=1))
        # Check now, so a box that cannot hold the connections is
        # refused on the line that asked for it rather than at the first
        # render.
        self._check_box()

    def _add_connection(self, name: str, direction: str, face: str) -> Port:
        """One connection: the nozzle, and the side it leaves from.

        Laid down together, so there is no window in which
        :attr:`_faces` and ``ports`` disagree. The nozzle first, so a
        name :meth:`~Unit._add_port` refuses cannot leave a face
        recorded for a connection that does not exist.
        """
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    @property
    def width(self) -> float | None:
        """The box's width, or ``None`` to size it to the connections.

        A property rather than a plain attribute: assigning a width that
        crushes a run of connections raises and leaves the block at the
        size it had.
        """
        return self._width

    @width.setter
    def width(self, value: float | None) -> None:
        self._resize("_width", value)

    @property
    def height(self) -> float | None:
        """The box's height, ``None`` to size it to the connections."""
        return self._height

    @height.setter
    def height(self, value: float | None) -> None:
        self._resize("_height", value)

    def _resize(self, attr: str, value: float | None) -> None:
        """Take a new box dimension, or refuse it and keep the old."""
        was = getattr(self, attr)
        setattr(self, attr, value)
        # ``Unit.__init__`` sets both of these before this class has
        # declared a connection; the constructor checks once at the end,
        # when there is something to check.
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
        port: str | None = _UNSTATED,
    ) -> "Block":
        """Place the block, re-checking the placement can draw it.

        A quarter turn draws the box's upright faces across the sheet,
        so a placement decides whether a run of connections still has
        room; the other half is the size, which :attr:`width` guards.

        Raises :class:`ValueError` and leaves the previous placement in
        place rather than turning the block into something undrawable.
        """
        was = self.pin_
        super().pin(col=col, row=row, x=x, y=y, orientation=orientation,
                    mirrored=mirrored, port=port)
        try:
            self._check_box()
        except ValueError:
            # The sheet is left marked stale by the two writes above,
            # though this one placed nothing. That costs a layout run
            # that resolves the same frames; the alternative is a flag
            # that lies, and layout is reseeded from ``pin_`` every run
            # precisely so a needless one is free of consequence.
            self.pin_ = was
            raise
        return self

    @property
    def input_faces(self) -> tuple[str, ...]:
        """The face each input leaves, in ``in_1`` .. ``in_n`` order.

        Compass letters and not connections: ``('W', 'W', 'N')``.
        :attr:`inlets` is the ports.

        A tuple, like :attr:`inlets` beside it: all four of these are
        *derived views* of :attr:`_faces` and ``ports``, and appending
        to one would not move a connection. :meth:`nozzle` does that.
        """
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """Each output's face, in ``out_1`` .. ``out_m`` order."""
        return tuple(self._faces[port.name] for port in self.outlets)

    def face(self, port_name: str) -> str:
        """Which side of the **box** ``port_name`` is on.

        Not necessarily the side of the *sheet*: a :meth:`pin` that
        turns or mirrors the block moves the box and everything on it,
        so a connection declared ``"N"`` on a block turned a quarter is
        drawn on the east. :func:`pandid.portgeom.port_faces` answers
        about the finished sheet.
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

        It differs from :meth:`Unit.nozzle` in two ways.

        **``face`` names the box's own side, not the reader's.**
        :meth:`Unit.nozzle` takes the compass point on the finished
        sheet, because it picks between placements a symbol authored in
        advance. Here the face *is* the declaration the drawing is built
        from, and :meth:`pin` may come after this call and may come
        twice, so a turn or a mirror moves the box and everything on it:
        ``"N"`` on a block turned a quarter is drawn on the east. Ask
        :func:`pandid.portgeom.port_faces` about the finished sheet.

        **It always succeeds.** A block is a rectangle built from its
        own declaration, so moving a connection is changing that
        declaration and redrawing, and every side is a side the box has.

        It therefore writes :attr:`_faces` and not ``Unit._port_faces``,
        which is an override of a placement the symbol authored -- here
        the declaration *is* the placement, and one record is what lets
        ``to_dict`` write the block back out as the constructor call
        that rebuilds it.

        Raises :class:`ValueError` if the move would squeeze the
        connections on the destination side closer than the pitch the
        placed box leaves room for, and leaves the block untouched.
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
        # A move that stuck: the box is built from this declaration, so
        # its artwork and its nozzles are both somewhere else now.
        # Marked by hand for the reason :meth:`Unit.nozzle` gives.
        self._invalidate_layout()
        return self

    def ports_on(self, face: str) -> tuple[Port, ...]:
        """The connections on one side of the box, in drawn order.

        Along the face, first to last, in the direction :meth:`order_on`
        describes: the west end of a north or south face, the north end
        of a west or east one. Until :meth:`order_on` is called that is
        declaration order, inputs before outputs.

        The **ports**, and a tuple, so this is a third way of asking for
        a family rather than a different kind of answer.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    # The writer beside ``ports_on``'s reader. A face carrying both an
    # input and an output draws every input before every output, because
    # ``_faces`` is filled inputs-first and ``block_symbol`` groups it
    # in insertion order; this is the only way to say otherwise. Issue
    # #192, and ``examples/12`` is the sheet.
    #
    # It takes the ports and not their names, so reversing a face is
    # one expression -- ``b.order_on("S", b.ports_on("S")[::-1])`` --
    # and so a typo is caught where it is written rather than becoming
    # a quietly wrong drawing.
    #
    # It takes the *whole* face every time, which makes the call
    # idempotent and independent of the calls around it. An index into
    # the destination face (``nozzle("in_2", "S", at=1)``) would mean
    # something else as soon as a connection was added.
    def order_on(self, face: str, ports: "Sequence[Port]") -> "Block":
        """Set the order the connections on one side are drawn in.

        ``ports`` is **every** connection on ``face``, first to last
        along it.

        .. code-block:: python

            loop = fs.add(units.Block("Synthesis Loop",
                                      inputs=["W", "S"],
                                      outputs=["E", "S"]))
            # purge west, recycle east
            loop.order_on("S", [loop.out_2, loop.in_2])

        A block otherwise draws the connections on a face in declaration
        order, inputs before outputs. This is the only thing that says
        otherwise: :meth:`nozzle` chooses the *side*, and re-declaring a
        connection onto the side it is already on leaves it where it
        was.

        **First is the low end of the face, on the box's own axes.**
        West on a north or south face, north on a west or east one --
        the direction :attr:`inlets` is numbered in and
        :func:`~pandid.render.symbols.spread` lays a family out in. Like
        the face itself it is the box's own order, so a :meth:`pin` that
        mirrors the block draws the same first member on the right of
        the sheet.

        A connection :meth:`nozzle` moves onto the face *afterwards*
        takes its place in declaration order rather than joining the
        end. Order the face once it has the members it is going to have.

        Raises :class:`ValueError` for a connection that is not on
        ``face``, one named twice, one belonging to another unit, or a
        list that leaves any of the face's connections unplaced, and
        leaves the block untouched when it does.
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
                    f"b.port('out_2') where the name is computed. "
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
        # Rewritten in place: the dict's order *is* the drawn order,
        # since ``block_symbol`` groups its argument by face and spreads
        # each group by index. Swapping in the new sequence as each
        # member of this face comes round leaves every other face's
        # members where they were, so reordering the south does not
        # perturb the north.
        #
        # No ``_check_box()``: this changes no face's count, so the box
        # that held the connections a moment ago still does.
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on
            for name, on in self._faces.items()
        }
        # Same face, different connections along it, so every nozzle on
        # it has moved and the runs into them have to be routed again.
        self._invalidate_layout()
        return self

    def symbol(self) -> "Symbol":
        """This block's drawing, built to its connections.

        The one place a block's artwork comes from, called by
        :meth:`~pandid.render.symbols.SymbolRegistry.for_unit` on every
        port resolution. It only *builds*: :meth:`_check_box` asks
        :func:`~pandid.portgeom.resolve_size` for the placed box, and
        ``resolve_size`` asks the registry for this symbol, so checking
        here would close that loop.
        """
        from pandid.render.symbols import block_symbol

        # The name widens the box only where the author left the width
        # open; see block_symbol(). Passing it with a width already
        # given would cost every block its own <defs> entry.
        return block_symbol(tuple(self._faces.items()),
                            "" if self.width is not None else self.tag)

    def _check_box(self, placed=None) -> None:
        """Raise unless the placed box draws the connections at pitch.

        Measured against the box the drawing really lands in
        (:func:`~pandid.portgeom.resolve_size`), *including the quarter
        turn*: a turn swaps which axis of the box a face's run is drawn
        along, while ``resolve_size`` takes an explicit ``width``/
        ``height`` as the final box and does not swap it. Five inlets in
        a 60 x 150 box turned a quarter came out 12 apart, one
        arrowhead, five heads touching -- which is why this is not a
        pair of comparisons against ``width`` and ``height``.

        The comparison is against the box the block sized itself to and
        not the bare run, because the artwork is stretched into whatever
        box it is given: halving the box halves the drawn pitch with it.

        ``placed`` is the placement to answer for, defaulting to the
        unit's own; :meth:`pin` passes its candidate, since the
        committed placement answers for the sheet that call is
        replacing.
        """
        from pandid.portgeom import resolve_size
        from pandid.render.symbols import block_box_too_small

        sym = self.symbol()
        if placed is None:
            placed = self.pin_
        w, h = resolve_size(self, placed)
        turned = int(getattr(placed, "orientation", 0) or 0) in (90, 270)
        for face, count in Counter(self._faces.values()).items():
            # One connection on a face has no spacing to crush.
            if count < 2:
                continue
            upright = face in ("W", "E")
            along = sym.height if upright else sym.width
            # A quarter turn lays the symbol's upright faces across the
            # box and stands its horizontal ones up, so which box axis a
            # run is drawn along is the two questions XOR'd.
            drawn, axis = (w, "width") if upright == turned else (h, "height")
            if drawn < along - 1e-9:
                raise block_box_too_small(self.name, face, count, axis, drawn,
                                          along, turned=turned)
