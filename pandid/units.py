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

import math
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
    from pandid.render.symbols import PortSeries, Symbol
    from pandid.streams import Stream

__all__ = [
    "Unit",
    "Feed",
    "Product",
    "Pump",
    "Compressor",
    "Blower",
    "Valve",
    "Vessel",
    "Tank",
    "HeatExchanger",
    "Heater",
    "Cooler",
    "CoolingTower",
    "Reactor",
    "Separator",
    "Absorber",
    "Stripper",
    "DistillationColumn",
    "Column",
    "Mixer",
    "Splitter",
    "Tee",
    "Reducer",
    "Fitting",
    "Ejector",
    "Vent",
    "Funnel",
    "Furnace",
    "Boiler",
    "Stack",
    "Flare",
    "Turbine",
    "Filter",
    "Dryer",
    "CrushingMachine",
    "Crusher",
    "Mill",
    "Centrifuge",
    "Conveyor",
    "Elevator",
    "Feeder",
    "SprayNozzle",
    "ScreeningDevice",
    "Kneader",
    "Instrument",
    "Block",
]

# Only a signal port may carry a signal line and only a process one may
# carry fluid; Flowsheet.connect enforces the pairing.
#
# "draw" is "feed" reversed: a side draw's phase is as unstated as a
# feed's is, for the same reason -- neither placement nor role commits a
# column to vapour or liquid, so drawing that distinction is a choice a
# future role value can make without this one lying about it meanwhile.
_VALID_ROLES = {
    "process",
    "feed",
    "product",
    "energy",
    "utility",
    "vapor",
    "liquid",
    "signal",
    "draw",
}

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
_LAYOUT_INPUTS = frozenset(
    {
        "name",
        "variant",
        "label_pos",
        "pin_",
        "width",
        "height",
        "_width",
        "_height",
        "_length",
        "_diameter",
        "_large_end",
        "_normal_position",
    }
)


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

    #: How hard this kind of equipment insists on the arrangement it
    #: states in :attr:`PLACES`, and on everything else it says about
    #: where its neighbours are drawn.
    #:
    #: It is **stiffness, not authority**. The layout fits every claim
    #: at once by weighted least squares
    #: (:mod:`pandid.layout.solver`), so a number here is how strongly a
    #: relationship resists being deformed -- at both of its ends. A
    #: column at 8 authoring six claims is stiff by 48 and barely moves;
    #: twenty neighbours at 2 muster 40 between them and can move it.
    #: Nothing is ever overruled and nothing is ever dropped.
    #:
    #: The ladder the library is written to:
    #:
    #: - **8** a tower or a reactor -- the equipment a sheet is drawn
    #:   around, and the only equipment whose arrangement is a
    #:   convention a reader expects rather than a consequence of what
    #:   it is connected to.
    #: - **4** a vessel, tank or separator: a fixed point on the sheet,
    #:   but one drawn where its train runs.
    #: - **2** an exchanger, pump, compressor or filter: in the train,
    #:   with an opinion about its own two sides and none about the
    #:   sheet.
    #: - **1** (the base) a plain :class:`Block` or anything unlisted:
    #:   it says only what its nozzles and the flow say.
    #: - **0** a valve, a fitting, a reducer, a tee -- these sit *in*
    #:   the line and have no opinion about where the line goes. Their
    #:   claims are dropped entirely rather than weighed at 1, so a
    #:   train with a dozen block valves on it does not stiffen the
    #:   vessel at the end of it by twelve.
    LAYOUT_CONFIDENCE: float = 1

    #: Nozzle name -> where a unit connected to *that nozzle* is drawn
    #: relative to this one: a compass point (``"N"``, ``"NE"``, ...) or
    #: ``(compass point, confidence)`` where one nozzle deserves a
    #: different weight from the rest of the class.
    #:
    #: This is the drafting convention the equipment is drawn to, and
    #: the equipment is the only thing that knows it: a condenser goes
    #: top right of its column because that reads clearly, not because
    #: it stands above it. Vertical position on a P&ID is not elevation,
    #: and no amount of looking at the pipe will say which way up the
    #: tower goes.
    #:
    #: Looked up by the nozzle's own name and then by the family name a
    #: numbered family shares, so ``{"feed": "W"}`` covers ``feed_1``
    #: through ``feed_8``. A nozzle with no entry falls back to the face
    #: the symbol fixed it to, and a unit with neither to flow order --
    #: both at this class's own :attr:`LAYOUT_CONFIDENCE`. See
    #: :mod:`pandid.layout.claims`.
    #:
    #: An entry of ``None`` is that fallback **declined**: this nozzle's
    #: face is where the pipe attaches and nothing more, and the class
    #: has no view on where its peer is drawn. Which is what a *service*
    #: connection is -- a heater's steam supply, a filter's regenerant,
    #: a furnace's fuel gas. The header on the other end of it is placed
    #: by where the sheet's utilities come in, not by the machine tapping
    #: it, and reading the nozzle's face instead had five heaters at
    #: confidence 2 asserting their supply lay south of them and sinking
    #: the header below every consumer it fed (#459). Not the same as
    #: leaving the nozzle out: a missing entry reads the face, an entry
    #: of ``None`` says not to.
    #:
    #: Inherited whole, like :attr:`PORT_ANCHORS`: a subclass that
    #: declares its own replaces its base's rather than adding to it, so
    #: a class with one nozzle to say something about restates the ones
    #: it still means.
    PLACES: dict[str, "str | tuple[str, float] | None"] = {}

    #: Do this unit's connections all land on one drawn point *on
    #: purpose*?
    #:
    #: False everywhere but :class:`_Boundary`. Two live connections
    #: resolving to one point is otherwise a hard finding
    #: (``coincident-ports``), because one stream then terminates on top
    #: of another and the sheet cannot be read; :mod:`pandid.layout.faces`
    #: is written so the face selector can never be the thing that makes
    #: one, and :class:`Instrument`'s pool spreads its members over four
    #: faces rather than sharing a point.
    #:
    #: A boundary flag is the case that rule was never about. It is not
    #: a body with nozzles on it -- it is a *pennant*, a mark saying the
    #: material crosses the sheet edge here, and the point is the edge
    #: rather than a nozzle. Two runs meeting it meet it at one place
    #: because there is only one place: the tip of the flag. Nothing is
    #: hidden by them arriving together, since the flag is drawn once
    #: whatever its count.
    #:
    #: A flag, and not "anything that opts in": there is no keyword for
    #: this and it is not meant to grow one. A manifold nozzle on real
    #: equipment is a different question with a different answer (an
    #: opt-in on the port, and a ``validate()`` finding when it happens
    #: implicitly), and this attribute is deliberately too blunt to be
    #: mistaken for it.
    ONE_NOZZLE_MANY_RUNS = False

    #: Nozzle name -> ``(direction, role, the Deprecation naming its
    #: replacement)``, for a nozzle this class stopped building but must
    #: still answer for one release: an author who called this class for
    #: what has moved to a narrower one still has a sheet connecting the
    #: old name. :meth:`__getattr__` is the only reader, and it mints the
    #: port -- once, on first access -- rather than building it at
    #: construction, so a unit that never uses the retired name never
    #: warns. A class that never carried the nozzle honestly overrides
    #: this back to ``{}`` rather than inheriting a promise it never
    #: made; see :class:`Absorber` and :class:`Stripper`.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

    #: Nozzle name -> ``(the name that replaces it, the Deprecation that
    #: says so)``, for a nozzle that was only ever renamed -- the same
    #: connection point under an old word. Unlike :attr:`_RETIRED_PORTS`,
    #: this mints nothing: the retired name resolves to *the same*
    #: :class:`~pandid.ports.Port` object the new one does, since two
    #: ports answering for one nozzle is exactly the fault
    #: :meth:`~pandid.render.symbols.Symbol.coincident_ports` exists to
    #: catch.
    _RETIRED_PORT_ALIASES: dict[str, tuple[str, Deprecation]] = {}

    #: Attribute names this class reads exactly once, in ``__init__``, to
    #: build the nozzles and overlays that describe what the equipment
    #: *is*: :class:`Column`'s ``internals``/``trays``/``feed_stages``/
    #: ``draw_stages``, :class:`Reactor`'s ``agitator``/``internals``,
    #: :class:`Vessel`'s ``supports``. :meth:`__setattr__` refuses a
    #: later assignment to one, naming the constructor keyword to use
    #: instead -- the same answer :attr:`Tee.branch_direction` gives a
    #: reassignment, for the same reason: the drawing is already built
    #: from the first answer, and a second one silently accepted would
    #: leave it disagreeing with what the object claims to be (#415).
    #:
    #: Declared per class exactly like :attr:`_RETIRED_PORTS`, so a
    #: subclass that adds no keyword of its own -- every :class:`Column`
    #: subclass -- inherits the set its base built, and the refusal, in
    #: one place, covers all of them uniformly rather than needing its
    #: own copy.
    _FIXED_AT_CONSTRUCTION: frozenset[str] = frozenset()

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
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
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
        escape = (
            ""
            if generic is None
            else (
                f" The generic form is {generic.__name__}(variant={variant!r}), which "
                f"takes any variant registered for a {cls.kind}."
            )
        )
        return ValueError(
            f"{name}: {cls.__name__} draws "
            f"{', '.join(repr(v) for v in cls.VARIANTS)}, not {variant!r}{suggestion}. "
            f"A different device is a different class, so {variant!r} belongs to "
            f"whichever class draws it.{escape}"
        )

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if not name:
            raise ValueError("Unit name cannot be empty")
        self.name = name
        if self.VARIANTS and variant not in self.VARIANTS:
            raise self._unknown_variant(name, variant)
        # The registry's spelling, never the class-local one; see
        # :attr:`VARIANT_ALIASES`.
        self.variant = self.VARIANT_ALIASES.get(variant, variant)
        # A box is drawn into ``<use width=... height=...>`` (and, on the
        # composed classes, a ``viewBox`` of the same two numbers): the SVG
        # spec calls a negative value on either an error and a conformant
        # reader draws nothing for it, silently -- the symbol vanishes while
        # the tag and the pipe routed to its nozzle are drawn as if it were
        # still there. Zero is the same fault by a different route: nothing
        # is left to draw a nozzle onto. Caught here, once, for every unit
        # rather than at each place downstream that assumes a box it was
        # given can be measured.
        for dim, value in (("width", width), ("height", height)):
            if value is not None and not (math.isfinite(value) and value > 0):
                raise ValueError(
                    f"{name}: {dim}={value!r} is not a usable size; a symbol is "
                    f"drawn into a box with a positive, finite {dim}, or "
                    f"{dim}=None to size itself"
                )
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
        self.pin_: Pin | None = None  # intent; set only via pin()
        self.frame: Frame | None = None  # resolved; set only by layout
        self._port_faces: dict[str, str] = {}  # port name -> face
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

        A name in :attr:`_FIXED_AT_CONSTRUCTION` is refused once it is
        already in ``self.__dict__`` -- which lets ``__init__`` set it
        the first time at full speed and catches only a later
        reassignment, the one :meth:`__init__` itself never makes.

        Everything else is set at full speed.
        """
        if name in self._FIXED_AT_CONSTRUCTION and name in self.__dict__:
            raise AttributeError(
                f"{self.name}: {name} is read-only. It is read once, in "
                f"__init__, to build the nozzles and artwork that describe "
                f"what this {type(self).__name__} is; reassigning it would "
                f"leave the drawing disagreeing with the object. Build a new "
                f"{type(self).__name__} with {name}={value!r} instead."
            )
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

    def _offset_to_port(
        self, candidate: Pin, port_name: str, x: float | None, y: float | None
    ) -> None:
        """Re-read a candidate's named axes as one nozzle's position.

        Writes the corner the nozzle asked for back onto the pin, so a
        :class:`~pandid.geometry.Pin` still stores a corner and pinning
        the same nozzle to the same point twice is the same placement
        twice rather than a device walking off its run.
        """
        port_name = self._canonical_port_name(port_name)
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

        port_name = self._canonical_port_name(port_name)
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

    def _add_port(self, name: str, direction: str, role: str, side: str | None = None) -> Port:
        if name in self.ports:
            raise ValueError(f"{type(self).__name__!r} already has a port named {name!r}")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r} for port {name!r}. Allowed roles are: {_VALID_ROLES}"
            )
        port = Port(name=name, owner=self, direction=direction, role=role, side=side)
        self.ports[name] = port
        setattr(self, name, port)
        # A new name can join a series :meth:`_series_members` already
        # answered for, so the cached membership goes with it.
        self.__dict__.pop("_series_members_cache", None)
        return port

    def has_another_port(self, port: "Port") -> bool:
        """Whether this unit has a second connection like ``port``.

        False for every nozzle of every piece of equipment: a pump has
        one suction, and a second pipe on it is a :class:`Tee` the
        drawing has to show. :class:`Instrument`, whose signal
        connections are a pool, and :class:`_Boundary`, whose flag is
        one point on the sheet edge rather than a nozzle, are the whole
        of the exception.

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

    def _next_member(self, base: str, direction: str, role: str) -> "Port":
        """A free port of the ``base``/``base_2``/``base_3`` family,
        minting one if every member is spoken for.

        The one piece of pool arithmetic in the library, shared by
        :class:`Instrument`'s signal pools and :class:`_Boundary`'s flag
        so the two cannot number their members differently. Members are
        found by asking the *unit* which of its ports are in the family
        (:meth:`_pool_members`) rather than by matching a name, since
        which names are pooled is a fact about the class.

        Numbered from the members present, so a sheet rebuilt from a
        spec that named ``sig_out_2`` and ``sig_out_4`` numbers its next
        one 5; the ``while`` covers the gap the named ones left.
        """
        members = self._pool_members(base)
        for member in members:
            if member.stream is None:
                return member
        n = len(members) + 1
        while f"{base}_{n}" in self.ports:
            n += 1
        return self._add_port(f"{base}_{n}", direction, role)

    def _pool_members(self, base: str) -> list["Port"]:
        """This unit's ports belonging to the ``base`` pool, in port
        order. Empty on a class with no pools, which is nearly all of
        them."""
        return []

    def _mint_port(self, name: str) -> "Port | None":
        """The port ``name``, built here and now if this class answers
        for names it did not declare -- ``None`` if it does not.

        Only a pooled connection does: a balloon's ``sig_out_3`` and a
        flag's ``outlet_3`` exist because a line was made, so a sheet
        rebuilt from a spec has to be able to ask for one by name before
        the line exists (:func:`pandid.spec._find_port`). ``None``
        everywhere else, which is what leaves "no such port" to be
        reported against the entry that named it.
        """
        return None

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
        this but :class:`Column`, whose ``feed_stages=``/``draw_stages=``
        put a feed or a draw on the stage it actually enters or leaves
        on, rather than spreading it with the rest.
        """
        return None

    def _series_members(self, series: "PortSeries") -> dict[str, int]:
        """This unit's ports that belong to *series*, each mapped to its
        place among them in port order.

        :func:`pandid.portgeom._series_point` asks this once per member
        to place it -- a column with a feed on every one of fifty trays
        asks fifty times -- and every ask scanned the same ports for the
        same answer and then scanned the answer itself to find one name
        in it, which made placing every port on a wide family cost the
        square of its count. A dict answers both by one key lookup
        instead. Cached per series here, and dropped by :meth:`_add_port`
        the one place ``self.ports`` can gain a member the cached answer
        would then be missing.
        """
        cache = self.__dict__.setdefault("_series_members_cache", {})
        members = cache.get(id(series))
        if members is None:
            members = {n: i for i, n in enumerate(n for n in self.ports if series.matches(n))}
            cache[id(series)] = members
        return members

    def _canonical_port_name(self, name: str) -> str:
        """``name``, or the real port an alias like ``feed`` names.

        Almost always ``name`` unchanged. ``Reactor.feed``/``Column.feed``
        at ``n_feeds == 1`` are the one live alias in the library -- a
        plain attribute set beside ``feed_1`` in ``__init__`` rather than
        a second entry in :attr:`ports`, so a ``PortSeries`` placing the
        family sees one member and not two (see :func:`_feed_names`).
        That means the alias is invisible to anything that resolves a
        port name by checking :attr:`ports` directly, so this is called
        wherever a caller-supplied name is about to become one -- a
        dict key, or an argument to :mod:`pandid.portgeom`, which knows
        nothing of the alias and would otherwise place it at the box
        centre, or a ``nozzle()`` face silently filed under a key
        nothing later looks up.

        Only a name that is genuinely a :class:`Port` counts: a plain
        attribute this unit happens to have under that name (``width``,
        say) is not a port under a new spelling, and is left alone so
        the caller's own "no such port" error fires on it unchanged.
        """
        if name in self.ports:
            return name
        aliased = getattr(self, name, None)
        return aliased.name if isinstance(aliased, Port) and aliased.name in self.ports else name

    def port(self, name: str) -> Port:
        name = self._canonical_port_name(name)
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
                where = self.__dict__.get("name", "?")
                alias = type(self)._RETIRED_PORT_ALIASES.get(name)
                if alias is not None:
                    target, dep = alias
                    dep.warn(self, where=where)
                    return getattr(self, target)
                retired = type(self)._RETIRED_PORTS.get(name)
                if retired is not None:
                    direction, role, dep = retired
                    dep.warn(self, where=where)
                    return self._add_port(name, direction, role)
                raise AttributeError(
                    f"{type(self).__name__} {where!r} has no "
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

    Several lines on one flag
    -------------------------
    **A flag's connection takes as many streams as the sheet gives it,
    and every other nozzle in the library still takes one.** One header
    entering a drawing and serving three users is ordinary, and three
    flags for one header misrepresents the plant; but two pipes on a
    real nozzle *is* a tee, and this package draws one (:class:`Tee`),
    so relaxing the rule there would let an author draw a branch with no
    tee on it -- losing, silently, the thing the drawing exists to
    carry.

    The mechanism is :class:`Instrument`'s signal pool, which is the
    same shape: :meth:`Unit.has_another_port` says the connection is
    plural and :meth:`another_port` hands out the next member, so
    ``fs.connect(feed.outlet, ...)`` twice makes two lines rather than
    raising. What differs is where the members go. A balloon's are
    spread over four faces of a circle and must never coincide; a
    flag's all draw on the flag's **one** nozzle, because that is what
    a flag is -- a single point where the material crosses the sheet
    edge, whatever leaves it on this side. So they are exempt from the
    coincident-nozzle rule, by name and only here; see
    :attr:`ONE_NOZZLE_MANY_RUNS`.

    Each stream stays a stream of its own throughout: its own number,
    its own line number, its own row in the stream table and the line
    list, its own route. Only the *flag* is one thing.
    """

    #: A flag states nothing about where anything is drawn. Its nozzle
    #: faces east on a feed and west on a product because that is how a
    #: pennant is drawn, not because the line comes from the west -- so
    #: reading that face as a claim would have every boundary on the
    #: sheet arguing, at full weight, from a fact about its own artwork.
    #: A flag goes where its line comes from, which is what a
    #: confidence of 0 says.
    LAYOUT_CONFIDENCE = 0

    #: The tip of the pennant is one point and every run on the flag
    #: leaves it. See :attr:`Unit.ONE_NOZZLE_MANY_RUNS`.
    ONE_NOZZLE_MANY_RUNS = True

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        header: bool = False,
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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

    @property
    def connection(self) -> Port:
        """The flag's one nozzle -- ``outlet`` on a feed, ``inlet`` on a
        product -- whatever the class calls it.

        The one name every flag has, since :attr:`PORTS` on each
        subclass is one entry and it is that one. Written as "the first
        port declared" rather than as a per-class constant so a flag
        subclass that renamed it would still be answered for.
        """
        return next(iter(self.ports.values()))

    def _pool_base(self, port_name: str) -> str | None:
        """The pool ``port_name`` is in -- the flag's own nozzle name --
        or ``None`` for a name this flag does not answer for.

        A flag has exactly one pool, so this is "is it the nozzle, or a
        numbered member of it".
        """
        base = self.connection.name
        if port_name == base:
            return base
        head, _, tail = port_name.rpartition("_")
        return base if head == base and tail.isdigit() else None

    def _pool_members(self, base: str) -> list[Port]:
        return [p for name, p in self.ports.items() if self._pool_base(name) == base]

    def has_another_port(self, port: Port) -> bool:
        """True for the flag's own connection, at any count.

        A flag is not a nozzle; see the class docstring. Guarded on the
        name rather than answered ``True`` outright so that a flag which
        one day grew a second, *different* connection would not have it
        quietly pooled with the first.
        """
        return self._pool_base(port.name) is not None

    def another_port(self, port: Port) -> Port:
        """A free member of the flag's connection, minting one if need be.

        Called by :meth:`pandid.flowsheet.Flowsheet.connect` on a
        connection already spoken for, which is what makes two lines off
        one ``feed.outlet`` two lines rather than an error. Every member
        keeps the first one's direction and role, since they are the
        same connection: a Feed's are all outlets carrying ``feed``.
        """
        base = self._pool_base(port.name)
        if base is None:
            return port
        return self._next_member(base, port.direction, port.role)

    def _mint_port(self, name: str) -> Port | None:
        """A member of the flag's connection, by name.

        What :func:`pandid.spec._find_port` needs to read back a sheet
        whose flag carried three lines: ``to_dict()`` writes them out as
        ``outlet``, ``outlet_2``, ``outlet_3``, and only the first of
        those exists on a flag that has just been built.
        """
        if self._pool_base(name) is None:
            return None
        first = self.connection
        return self._add_port(name, first.direction, first.role)

    def _symbol_anchor(self, port_name: str) -> str:
        """Every member draws on the flag's own nozzle.

        Which is the point of the class: the pennant is drawn once and
        every run on it leaves the same tip. Unlike
        :meth:`Instrument._symbol_anchor`, which sends its pool members
        to a shared *menu* of four faces for the face selector to spread
        them over, this really does resolve them all to one coordinate
        -- see :attr:`Unit.ONE_NOZZLE_MANY_RUNS` for why that is allowed
        here and nowhere else.
        """
        return self._pool_base(port_name) or super()._symbol_anchor(port_name)

    def repeats(self, other: "Unit") -> bool:
        """Whether this flag is another tap of the same header.

        Both ends have to be headers (``header=True``) carrying the same
        label, and to be the *same drawing* of it: same class, so a
        supply and a return sharing a label still clash, and the same
        ``reference``, since two taps of one header continue onto one
        drawing.

        Unchanged by a flag carrying several streams, and it is worth
        saying why, because this compares flags rather than lines. Two
        *taps* of one header are two flags drawn in two places, each
        with its own name; a header serving three users from **one**
        point on the sheet edge is one flag with three streams on it and
        never reaches this at all. The choice between them is a drawing
        decision an author makes by adding a second flag or not, which
        is what it was before.
        """
        return (
            self.header
            and isinstance(other, _Boundary)
            and type(other) is type(self)
            and other.header
            and other.tag == self.tag
            and other.variant == self.variant
            and other.reference == self.reference
        )


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
    LAYOUT_CONFIDENCE = 2
    #: A pump is in the train and knows only its own two sides.
    PLACES = {"suction": "W", "discharge": "E"}


class Compressor(Unit):
    """Gas compressor."""

    suction: Port
    discharge: Port

    kind = "compressor"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]
    LAYOUT_CONFIDENCE = 2
    PLACES = {"suction": "W", "discharge": "E"}


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

    #: A valve or a fitting is *in* the line: it goes where the line
    #: goes and states nothing about where the line goes. Weighed at 0
    #: rather than 1 so that a train with a dozen block valves on it
    #: does not stiffen the vessel at the end of it twelve times over.
    LAYOUT_CONFIDENCE = 0

    #: The positions such a unit may be declared in. A tuple rather than
    #: a bool: the designations a P&ID draws are an enumeration (NC
    #: today, the locked and car-sealed ones later).
    NORMAL_POSITIONS = ("open", "closed")

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        normal_position: str = "open",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
    _BASE = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("actuator", "inlet", "signal"),
    ]
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

    def __init__(
        self,
        name: str,
        variant: str = "default",
        *,
        actuator: str = "",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        normal_position: str = "open",
        fail: str = "",
    ):
        variant = self._resolve(name, variant, actuator)
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
            normal_position=normal_position,
        )
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
    what="Vessel(variant='legs')",
    instead="Vessel(supports='leg')",
    removed_in="0.2.0",
    note="the drawing changes -- a pair of ISO item 26.1 C2005 legs under the "
    "standard vessel shell, where this one has its own drawn in",
)
VESSEL_VARIANT_SKIRTED = Deprecation(
    what="Vessel(variant='skirted')",
    instead="Vessel(supports='skirt')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 26.3 C2007's skirt under the standard "
    "vessel shell, where this one has its own drawn in",
)

_VESSEL_SUPPORT_VARIANTS = {
    "legs": VESSEL_VARIANT_LEGS,
    "skirted": VESSEL_VARIANT_SKIRTED,
}


#: Bound to :class:`_MultiPortVessel` rather than reusing :data:`_UnitT`:
#: a method typed ``self: _UnitT`` sees ``self`` *as* ``Unit`` inside its
#: own body, which is right for :meth:`Unit.nozzle` but would hide
#: ``_faces`` from :class:`Tank`'s and :class:`Vessel`'s own override of
#: it. Bound narrower, ``self`` is seen as this class inside the method
#: and as the caller's own subclass (``Tank3``, say) at the call site --
#: both at once, which is the whole point of a self-type.
_MultiPortVesselT = TypeVar("_MultiPortVesselT", bound="_MultiPortVessel")


class _MultiPortVessel(Unit):
    """Shared machinery for :class:`Tank` and :class:`Vessel`: an inlet
    and an outlet, each a family spread across up to four faces --
    :class:`Block`'s mechanism (a ``{port: face}`` dictionary and one
    call to :func:`~pandid.render.symbols.spread` per face), called
    directly rather than wrapped in a
    :class:`~pandid.render.symbols.PortSeries`. A series has one face
    for the whole family, and a tank's inlet has a menu of three;
    :class:`~pandid.render.symbols.Symbol.__post_init__` refuses a port
    claimed by both a series and ``ports``, which is exactly the wall
    this mechanism is built to not hit.

    **The one adaptation.** ``Block`` grows its box to fit a family,
    because a block's size means nothing. A tank or vessel's artwork is
    vendored and its size means something, so this takes
    :func:`~pandid.render.symbols.spread`'s **squeeze** instead -- the
    same fallback a mixer's inlets already reach for when a face runs
    out of room, taken here on purpose rather than as a last resort.

    **Legal faces come from the artwork, not from every compass
    point.** A block's rectangle has no physical constraint, so
    :meth:`Block.nozzle` always succeeds; a tank or vessel's shell only
    has a nozzle where the stencil drew one, so :meth:`nozzle` refuses a
    face the vendored symbol never anchored -- a floating roof's crown,
    say -- exactly as :meth:`Unit.nozzle` always has.

    ``vent``, ``relief`` and ``drain`` are not part of either family:
    each is a single, fixed nozzle, positioned by the artwork's own
    anchor and moved, where the artwork offers an alternative, through
    :meth:`Unit.nozzle`'s ordinary menu -- untouched by any of this.

    Three defaults, each more specific than the last, decide the face a
    connection is drawn on when the caller does not name one:

    1. **The symbol's own anchor** (:meth:`_home_face`) -- the face the
       vendored artwork already puts the nozzle on. The default when
       nothing else speaks, and what keeps every existing sheet exactly
       where it was: the differences between variants (a flat-floored
       tank fills low on the shell, a hopper-bottomed one at the crown)
       are per *drawing*, not per class, and this honours them without
       restating them anywhere.
    2. **A class attribute**, :attr:`DEFAULT_INPUT_FACE` /
       :attr:`DEFAULT_OUTPUT_FACE` -- :class:`Block`'s own mechanism,
       read through ``self.`` so a subclass overrides it. ``None`` on
       :class:`Tank` and :class:`Vessel` themselves, since neither has a
       class-wide opinion; this is where a device class with a
       contextual one -- a reflux drum that always fills at the crown --
       would state it.
    3. **The constructor argument**, ``inputs=``/``outputs=``, which
       always wins.
    """

    #: See level 2 of the class docstring. ``None`` on the base classes;
    #: a subclass with a contextual opinion overrides it.
    DEFAULT_INPUT_FACE: str | None = None
    DEFAULT_OUTPUT_FACE: str | None = None

    #: A fixed point on the sheet, but one drawn where its train runs
    #: rather than one the train is drawn around.
    LAYOUT_CONFIDENCE = 4
    #: What feeds a drum is upstream of it and what leaves it is
    #: downstream, whichever face the stencil put the nozzle on. That
    #: distinction is the whole of ``nozzle("inlet", "N")``:
    #: ``examples/08`` feeds its deaerator over the top tray, which moves
    #: the pipe to another part of the same drum and does not move the
    #: pump on the other end of it onto the roof.
    #:
    #: ``vent``, ``relief`` and ``drain`` restate the face they are
    #: already on, because at a vessel's weight rather than a nozzle's
    #: they hold: a relief line back to the vessel it protects is the
    #: clearest statement on a sheet of where that valve goes.
    PLACES = {"in": "W", "out": "E", "vent": "N", "relief": "N", "drain": "S"}

    #: connection name -> the face it leaves from, in port order. Built
    #: by :meth:`_init_connections`; the single authority the symbol is
    #: built from, exactly as :attr:`Block._faces` is.
    _faces: dict[str, str]

    def _symbol_anchor(self, port_name: str) -> str:
        """As :meth:`Unit._symbol_anchor`, read through the live alias
        too.

        ``inlet``/``outlet`` are plain attributes aliasing ``in_1``/
        ``out_1`` (see :meth:`_init_connections`), never a second entry
        in ``ports`` -- so the symbol only ever anchors the numbered
        spelling, and :mod:`pandid.portgeom` asked for ``"inlet"``
        directly (``port_offset(tk, "inlet")``, a bare
        ``pin(port="inlet")``, both ordinary) would otherwise find no
        such key and fall back to the box centre. A
        :class:`~pandid.render.symbols.PortSeries` sidesteps this with
        its own ``singular=``; this class has no series to carry one.
        """
        return super()._symbol_anchor(self._canonical_port_name(port_name))

    def _registry_symbol(self):
        """This unit's own vendored artwork, or ``None`` for a variant
        no symbol answers to.

        ``None`` rather than the registry's own :class:`ValueError`: a
        bad ``variant=`` is a render-time defect everywhere else in this
        library, caught by :meth:`~pandid.render.symbols.SymbolRegistry.
        for_unit` when the sheet is drawn, and never by any other
        class's ``__init__``. This is asked from inside the
        constructor -- to size the connections against the artwork --
        so it has to fail the same quiet way and let the real error
        surface where every other typo's does.
        """
        from pandid.render.symbols import default_registry

        try:
            return default_registry.get(self.kind, self.variant)
        except ValueError:
            return None

    def _home_face(self, role: str) -> str:
        """The face the vendored artwork draws ``role``'s nozzle on.

        Level 1 of the three defaults above. West for an inlet, east for
        an outlet, on a variant :meth:`_registry_symbol` cannot resolve
        -- an arbitrary placeholder that is never drawn, since the
        render this unit reaches will already have raised on the
        variant itself.
        """
        sym = self._registry_symbol()
        if sym is None:
            return "W" if role == "inlet" else "E"
        from pandid.portgeom import outward_dir

        x, y = sym.ports[role]
        return outward_dir(x, y, sym.width, sym.height)

    def _legal_faces(self, role: str) -> "dict[str, tuple[float, float]] | None":
        """``role``'s menu on the vendored artwork: ``{face: (x, y)}``.

        Always carries at least the home face --
        :class:`~pandid.render.symbols.Symbol.__post_init__` folds it in
        for every port it anchors -- so this is never empty for a
        variant that resolves. ``None`` for one that does not, which
        :meth:`_validate_face` reads as "nothing to check yet".
        """
        sym = self._registry_symbol()
        if sym is None:
            return None
        return dict(sym.port_faces.get(role, {}))

    def _validate_face(self, role: str, port_name: str, face: str) -> None:
        options = self._legal_faces(role)
        if options is None:
            # An unresolvable variant: refusing here would be this
            # constructor catching the typo, not the render every other
            # class leaves it to.
            return
        if face not in options:
            from pandid.portgeom import unreachable_face

            raise unreachable_face(self, port_name, face, list(options))

    def default_input_face(self) -> str:
        """The face an inlet is drawn on when the caller names none.

        Level 2 winning over level 1: :attr:`DEFAULT_INPUT_FACE` where a
        subclass states one, else the vendored artwork's own anchor.
        :meth:`~pandid.spec.to_dict`'s reader for what a bare ``inputs=``
        count means, so a sheet that never asked for a face writes none
        back out either.
        """
        return self.DEFAULT_INPUT_FACE or self._home_face("inlet")

    def default_output_face(self) -> str:
        """:meth:`default_input_face`, for the outlet family."""
        return self.DEFAULT_OUTPUT_FACE or self._home_face("outlet")

    def _init_connections(
        self, inputs: "int | Sequence[str]", outputs: "int | Sequence[str]"
    ) -> None:
        """Build ``in_1`` ... ``in_n`` and ``out_1`` ... ``out_m``.

        Called once, from ``__init__``, after :meth:`Unit.__init__` --
        the order :class:`Block` builds its own two families in.
        """
        in_faces = _block_faces(inputs, self.default_input_face(), self.name, "inputs")
        out_faces = _block_faces(outputs, self.default_output_face(), self.name, "outputs")
        self._faces = {}
        self.inlets = tuple(
            self._connect(f"in_{i}", "inlet", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._connect(f"out_{i}", "outlet", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
        if len(self.inlets) == 1:
            # An alias, not a second port; see :class:`Reactor`'s
            # ``feed``. ``n`` above one drops it, since there is no bare
            # name for a member of a family of more than one.
            self.inlet = self.inlets[0]
        if len(self.outlets) == 1:
            self.outlet = self.outlets[0]

    def _connect(self, name: str, direction: str, role: str, face: str) -> Port:
        """One connection: validate its face, then lay it down.

        The face is checked before the port exists, so a face the
        artwork refuses never leaves a connection half made.
        """
        self._validate_face(role, name, face)
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    def nozzle(self: _MultiPortVesselT, port_name: str, face: str) -> _MultiPortVesselT:
        """Pipe a connection from a named face.

        For ``in_1`` ... ``in_n`` / ``out_1`` ... ``out_m`` (and their
        singular aliases ``inlet``/``outlet``) this is :class:`Block`'s
        mechanism: ``face`` names the box's own side, the move always
        succeeds against a face the vendored artwork offers for that
        role and always refuses one it does not, and the drawing is
        rebuilt from the new declaration. For ``vent``, ``relief`` and
        ``drain`` -- not part of either family -- this is
        :meth:`Unit.nozzle` unchanged, choosing among the alternatives
        the artwork itself anchors.

        A single, un-nozzled inlet or outlet still offers its whole menu
        to the layout engine's own auto-pick (:mod:`pandid.layout.faces`,
        see :func:`~pandid.render.symbols.vessel_symbol`) -- which is
        what a call here has to *outrank*, or ``examples/03``'s crown
        entry would be overridden right back to the shell the moment the
        sheet is laid out. So this also records the choice in
        :attr:`Unit._port_faces`, the same store :meth:`Unit.nozzle`
        writes, since :func:`~pandid.portgeom.chosen_face` reads that
        before it ever asks the engine.
        """
        canonical = self._canonical_port_name(port_name)
        if canonical not in self._faces:
            return super().nozzle(port_name, face)
        role = "inlet" if canonical.startswith("in_") else "outlet"
        resolved = _block_face(face, self.name)
        self._validate_face(role, canonical, resolved)
        self._faces[canonical] = resolved
        self._port_faces[canonical] = resolved
        self._invalidate_layout()
        return self

    def face(self, port_name: str) -> str:
        """Which face ``port_name`` (an inlet or an outlet) leaves from.

        Only the two families: ``vent``, ``relief`` and ``drain`` are
        answered by :func:`pandid.portgeom.port_faces`, like any other
        unit's fixed nozzle.
        """
        canonical = self._canonical_port_name(port_name)
        try:
            return self._faces[canonical]
        except KeyError:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no inlet or outlet "
                f"named {port_name!r}; available: {sorted(self._faces)}"
            ) from None

    def ports_on(self, face: str) -> tuple[Port, ...]:
        """The inlets and outlets on one side, in drawn order.

        :class:`Block.ports_on`'s reader, restricted to the two
        families: ``vent``, ``relief`` and ``drain`` are never on this
        list, since :meth:`order_on` has no business reordering a fixed
        nozzle against a family member.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    def order_on(self: _MultiPortVesselT, face: str, ports: "Sequence[Port]") -> _MultiPortVesselT:
        """Set the order the inlets and outlets on one side are drawn in.

        :class:`Block.order_on`, unchanged: ``ports`` is every
        connection :meth:`ports_on` reports for ``face``, first to last
        along it.
        """
        wanted = _block_face(face, self.name)
        on_face = [name for name, on in self._faces.items() if on == wanted]
        named: list[str] = []
        for port in ports:
            if not isinstance(port, Port):
                raise TypeError(
                    f"{self.name}: order_on() takes the connections themselves and "
                    f"not their names, so a checker can see a typo -- "
                    f"order_on({wanted!r}, [v.out_2, v.in_2]), or v.outlets[1] / "
                    f"v.port('out_2') where the name is computed. "
                    f"Got {port!r}."
                )
            if self.ports.get(port.name) is not port:
                raise ValueError(
                    f"{self.name}: {port.name!r} is a connection of "
                    f"{port.owner.name!r}, not of this unit, so it is not on any "
                    f"face of it. order_on() orders one unit's own wall; "
                    f"the {wanted} face carries "
                    f"{', '.join(on_face) if on_face else 'nothing'}."
                )
            if self._faces.get(port.name) != wanted:
                raise ValueError(
                    f"{self.name}: {port.name!r} is on the "
                    f"{self._faces.get(port.name)} face, not the {wanted}. "
                    f"order_on() orders what is already on a side; move it first "
                    f"with nozzle({port.name!r}, {wanted!r})."
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
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on for name, on in self._faces.items()
        }
        self._invalidate_layout()
        return self

    @property
    def input_faces(self) -> tuple[str, ...]:
        """Each inlet's face, in ``in_1`` .. ``in_n`` order."""
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """Each outlet's face, in ``out_1`` .. ``out_m`` order."""
        return tuple(self._faces[port.name] for port in self.outlets)

    def symbol(self) -> "Symbol":
        """This unit's drawing: the vendored stencil (with a
        :class:`Vessel`'s ``supports=`` overlay already on it), and
        ``in_*``/``out_*`` recomputed to the current declaration.

        The one place a tank's or a vessel's artwork comes from, called
        by :meth:`~pandid.render.symbols.SymbolRegistry.for_unit` on
        every port resolution -- :class:`Block`'s own contract. It only
        *builds*: the artwork is vendored, so unlike ``Block`` there is
        no box to check.
        """
        from pandid.render.symbols import vessel_symbol

        overlays = tuple(getattr(self, "overlays", ()) or ())
        return vessel_symbol(self.kind, self.variant, tuple(self._faces.items()), overlays)


class Vessel(_MultiPortVessel):
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

    **``vent``, ``relief`` and ``drain`` are named, and not counted.**
    Each is positioned by what it is for, and a number carries no duty --
    CHEE4001 p.7 puts the PSV on the protected system itself, upright,
    discharging upward, at the top of the container -- and three
    interchangeable draws have nothing in them that says which is the
    relief.

    Every one of the ten vessel and seven tank stencils anchors a
    coordinate for each of the five, and
    :func:`pandid.portgeom.is_anchored` is true for every one. A nozzle
    the symbol never anchored falls back to the centre of the box, where
    any two of them land on each other -- issue #225 is that failure.
    ``scripts/vendor_symbols.py`` holds the seventeen port maps.

    The cost is that a *second* relief is a change to the artwork rather
    than a number. Nothing here is reported by ``nozzle-unconnected``,
    which reads only numbered nozzles; see issue #215 for drawing a
    spare nozzle blanked.

    **The process pair is a family, and may be.** ``inputs=``/
    ``outputs=`` give a vessel more than one connection, exactly as
    :class:`Block`'s do -- a count (every one on the same face) or one
    face per connection, e.g. ``inputs=["W", "W", "N"]`` for a knock-out
    pot taking a high-level fill against a recycle return. Left alone,
    ``inputs=1, outputs=1`` is what every vessel has always had: a
    single ``inlet``, a single ``outlet``, on the face the artwork
    anchors -- see :class:`_MultiPortVessel` for the three levels that
    decide it and :meth:`~_MultiPortVessel.nozzle` for how a face is
    moved. Above one, the numbered spelling takes over: ``in_1``,
    ``in_2`` ... in declaration order, reachable through
    :attr:`inlets`.

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

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    # The one-inlet, one-outlet vessel's own nozzles: aliases for
    # ``in_1``/``out_1``, set beside them in ``__init__`` rather than
    # registered a second time -- see :class:`Reactor`'s ``feed``.
    # ``inputs``/``outputs`` above one drops the alias; there is no bare
    # name for a member of a family of more than one.
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

    # ``in_1`` ... ``in_n`` are real attributes at run time and no class
    # annotation can name them, since ``n`` is the caller's -- the same
    # shape :class:`Mixer`'s inlets are, and answered the same way: a
    # **literal** ``inputs=`` count hands back a subclass declaring
    # exactly those nozzles, so ``Vessel("V-1", inputs=3).in_3`` resolves
    # and ``.in_4`` does not. A computed count, or one given as
    # ``inputs=["W", "W", "N"]`` (whose length is not in its type), gets
    # this class instead and ``vessel.inlets[i]`` / ``vessel.port(...)``.
    #
    # ``outputs=`` takes no matching family of its own: a vessel that
    # varies its outlet count is not a shape this library has a use for
    # yet, so ``outputs=2`` falls straight to the untyped case below --
    # the same trade ``Absorber``/``Stripper`` take for ``Column``'s
    # ``n_draws``. ``vessel.outlets[i]`` is the typed route there.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, inputs: Literal[1] = 1, *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel1": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel1": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[2], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel2": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel2": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[3], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel3": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel3": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[4], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel4": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel4": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[5], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel5": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel5": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[6], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel6": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel6": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[7], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel7": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel7": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[8], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel8": ...

        @overload
        def __new__(
            cls, name: str, inputs: tuple[str, str, str, str, str, str, str, str], *args: Any,
            outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any
        ) -> "Vessel8": ...

        @overload
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Vessel": ...
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Vessel": ...

    kind = "vessel"
    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    #: A vessel stands on nothing unless it is told what it stands on,
    #: whichever shell is drawn: the four group-26 elements go under or
    #: against every one of the ten variants.
    COMPOSITION = {"supports": None}
    #: See :attr:`Unit._FIXED_AT_CONSTRUCTION`: the overlay ``supports``
    #: composed is already drawn.
    _FIXED_AT_CONSTRUCTION = frozenset({"supports"})

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        supports: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._init_connections(inputs, outputs)
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


if TYPE_CHECKING:
    # A vessel of each inlet count, for the overloads above. Declared
    # here and not generated in a loop, for the reason :class:`Mixer`'s
    # own are: a checker reads the source, and nothing is built at
    # run time either, since ``TYPE_CHECKING`` is False there.

    class Vessel1(Vessel):
        in_1: Port

    class Vessel2(Vessel):
        in_1: Port
        in_2: Port

    class Vessel3(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port

    class Vessel4(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Vessel5(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Vessel6(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Vessel7(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Vessel8(Vessel):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Tank(_MultiPortVessel):
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
    through the same :meth:`~_MultiPortVessel.nozzle` call every other
    unit takes::

        tk = Tank("TK-602")          # fills low on the shell
        tk.nozzle("inlet", "N")      # ...through a crown downcomer

    ``floating_roof`` offers no crown placement at all: the roof rides
    on the liquid, so ``nozzle("inlet", "N")`` raises. The sphere's
    crown carries two drawn nozzles and both are spoken for; see #225
    and ``scripts/vendor_symbols.py``.

    A tank with no ``nozzle()`` call gets its face chosen by layout from
    where the peer landed (:mod:`pandid.layout.faces`), as a drum's
    inlet does.

    **A tank fed by several streams** takes ``inputs=``, exactly as
    :class:`Vessel` does -- a high-level fill against a recycle return,
    say::

        Tank("TK-901", inputs=["W", "W", "N"])
        tk.in_1, tk.in_2, tk.in_3   # west, west, crown; in declared order

    Left at ``inputs=1`` (the default), ``in_1`` keeps the bare alias
    ``inlet`` and every existing sheet is unchanged. ``outputs=`` is
    offered for the same reason :class:`Vessel`'s is, and defaults to
    one outlet the same way.
    """

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    inlet: Port
    outlet: Port
    # The same three :class:`Vessel` declares, and each carries the
    # comment there.
    vent: Port
    relief: Port
    drain: Port

    # See :class:`Vessel`'s own comment: a literal ``inputs=`` count
    # hands back a subclass declaring exactly ``in_1`` ... ``in_n``, and
    # ``outputs=`` carries no family of its own for the same reason.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, inputs: Literal[1] = 1, *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank1": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank1": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[2], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank2": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank2": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[3], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank3": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank3": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[4], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank4": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank4": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[5], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank5": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank5": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[6], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank6": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank6": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[7], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank7": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank7": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[8], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank8": ...

        @overload
        def __new__(
            cls, name: str, inputs: tuple[str, str, str, str, str, str, str, str], *args: Any,
            outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any
        ) -> "Tank8": ...

        @overload
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Tank": ...
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Tank": ...

    kind = "tank"
    # No PLACES of its own: :class:`_MultiPortVessel`'s ``out: "E"`` is
    # kept even though the artwork anchors ``out_1`` on this body's
    # **south** wall where a drum's is on its east one. #459 reads that
    # as a disagreement to reconcile and it is not one -- a tank empties
    # through its floor and what it empties into is drawn along, so the
    # pipe turns, which is what a drawing does. See :class:`Reactor`,
    # whose ``outlet`` is the identical pair of facts and which measures
    # what reconciling it costs. Measured here too: ``S`` moves the
    # corpus by +2 net (``14_tank_farm`` -2, ``13_mineral_dewatering``
    # +4) and ``SE`` by +21, so the drawing is not asking for either.

    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._init_connections(inputs, outputs)


if TYPE_CHECKING:
    # A tank of each inlet count; see :class:`Vessel`'s own.

    class Tank1(Tank):
        in_1: Port

    class Tank2(Tank):
        in_1: Port
        in_2: Port

    class Tank3(Tank):
        in_1: Port
        in_2: Port
        in_3: Port

    class Tank4(Tank):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Tank5(Tank):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Tank6(Tank):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Tank7(Tank):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Tank8(Tank):
        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Blower(Unit):
    """Fan or blower."""

    suction: Port
    discharge: Port

    kind = "blower"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]
    LAYOUT_CONFIDENCE = 2
    PLACES = {"suction": "W", "discharge": "E"}


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
    LAYOUT_CONFIDENCE = 0
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The nozzles the wide face may be on. Not a bool: the answer names
    #: a port, and "the large end is the outlet" is what an expansion
    #: is.
    LARGE_ENDS = ("inlet", "outlet")

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        large_end: str = "inlet",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
    LAYOUT_CONFIDENCE = 0
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    #: The name a tee answers to when the author gives it none. Every
    #: tee may take it and be renamed apart by the flowsheet; see
    #: :meth:`repeats`.
    DEFAULT_NAME = "TEE"

    #: What the third connection may be. A tee joins three lengths of
    #: the same pipe, so the branch carries process fluid like the run
    #: and differs only in which way it runs.
    BRANCH_DIRECTIONS = ("outlet", "inlet")

    def __init__(
        self,
        name: str = "",
        branch: str = "outlet",
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        description: str = "",
        reference: str = "",
    ):
        if branch not in self.BRANCH_DIRECTIONS:
            raise ValueError(
                f"{name or self.DEFAULT_NAME}: branch= is "
                f"{' or '.join(repr(d) for d in self.BRANCH_DIRECTIONS)}, whether "
                f"the third connection takes flow off the run or returns it; got "
                f"{branch!r}"
            )
        super().__init__(
            name or self.DEFAULT_NAME,
            variant=variant,
            width=width,
            height=height,
            description=description,
            reference=reference,
        )
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
    PORTS = [
        ("motive", "inlet", "utility"),
        ("suction", "inlet", "process"),
        ("discharge", "outlet", "process"),
    ]


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
    #: A fixed point on the sheet, drawn where its train runs -- the
    #: rung a vessel, a tank and a separator sit on. A fired heater is
    #: the thing a crude or reformer sheet is built around, and at the
    #: base 1 it was placed by whatever exchanger it happened to be
    #: piped to. Not an 8: what makes a tower an 8 is that its
    #: *arrangement* is a convention a reader expects, and a furnace's
    #: is in-one-side-out-the-other, which is a consequence of what it
    #: is connected to.
    LAYOUT_CONFIDENCE = 4
    #: ``fuel`` is declared empty: the burners are at the floor, so the
    #: symbol anchors the connection south, and read as a claim that
    #: hangs the fuel gas header off the bottom of the furnace. Where
    #: the fuel header runs is a fact about the sheet's utilities. See
    #: :class:`Heater`, which is the same nozzle on a smaller machine --
    #: and which is also why the process pair is not restated here, this
    #: being the class whose one mirrored instance measured the cost.
    PLACES = {"fuel": None}
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("fuel", "inlet", "feed"),
    ]


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
    #: A fixed point on the sheet, drawn where its train runs;
    #: :class:`Furnace`'s rung and its reasoning.
    LAYOUT_CONFIDENCE = 4
    #: ``steam`` is drawn off the dome's apex, so the symbol anchors it
    #: north and read as a claim the boiler asserts that whatever takes
    #: its steam is drawn above it. Nothing about a steam main says
    #: that: it leaves the boiler and goes on across the sheet like any
    #: other product, which is east. ``feedwater`` is already fixed west
    #: and stays with the artwork; see :class:`Heater`.
    PLACES = {"steam": "E"}
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
    #: A machine in the train, with an opinion about its own two sides
    #: and none about the sheet: the rung :class:`Compressor`,
    #: :class:`Blower` and :class:`Pump` are on, and a turbine is the
    #: machine on the other end of their shaft.
    LAYOUT_CONFIDENCE = 2
    # No PLACES: the symbol already fixes the motive fluid west and the
    # exhaust east, and restating a face loses the mirror it carries --
    # see :class:`Heater`. What was wrong here was the weight.

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
    LAYOUT_CONFIDENCE = 2
    #: ``regenerant_in`` is declared empty. It is anchored on the roof,
    #: and read as a claim that puts the acid or caustic day tank
    #: directly above the machine at the same weight as the process
    #: line -- an argument the process line should not be having (#459).
    #: ``spent_regenerant`` goes the same way: it leaves for a
    #: neutralisation pit or an effluent header, drawn wherever the
    #: sheet puts those.
    #:
    #: ``wash_in`` is the same case on the same drawing and is **not**
    #: declared here. It costs ``21_alumina_refinery`` 13 crossings, on
    #: two presses whose wash comes off a flag with nothing else to
    #: place it: silenced, the flag falls back to what the pipe says --
    #: "west of the machine" -- and lands in the column the process feed
    #: already occupies. That is a gap in what a silent nozzle falls
    #: back *to*, not a reason the wash header is placed by the press,
    #: and it wants fixing where the fallback lives rather than by
    #: leaving one of these two nozzles reading its artwork.
    PLACES = {"regenerant_in": None, "spent_regenerant": None}
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

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
    """Dryer (removes moisture from a feed solid/slurry).

    A drier takes a heating medium in and sends the moisture it picked
    up back out, so every variant carries four nozzles and not two:
    ``feed``/``product`` for the solid, and ``heating_in``/``vent`` for
    the gas that dries it and leaves laden with what it dried.

    Real plant forces the point. A gas-suspension calciner tees its
    combustion chamber's hot gas into the solids feed line rather than
    a windbox nozzle of its own, and lets the dried solid and the
    off-gas leave together on one nozzle to be parted in a downstream
    cyclone, when what it draws is one machine with four connections.
    ISO 10628-2's own group 10 row ticks only the solid pair -- no row
    in the group draws a third connection -- so ``heating_in``/``vent``
    are this library's own addition to it, on the casing wall (the
    solid's own) rather than the roof or the floor: a drier's air
    enters where the ISO row draws nothing and leaves where it draws
    nothing either, and there is no tabulated point to defer to.
    """

    feed: Port
    product: Port
    heating_in: Port
    vent: Port

    kind = "dryer"
    #: ``heating_in`` is :class:`Heater`'s ``utility_in`` under another
    #: name -- the hot gas or the steam brought to the machine from a
    #: header -- and it is anchored on whichever wall the drying medium
    #: enters by, which on most of these bodies is the floor. Declared
    #: empty for the same reason and with the same effect: a bank of
    #: driers on one hot-air main should not be able to drag the main
    #: below the bank (#459).
    PLACES = {"heating_in": None}
    # Empty because which nozzles a drier has depends on its variant --
    # today every one of them the same four, but the mechanism is
    # :attr:`_VARIANT_PORTS`, the one :class:`HeatExchanger`, ``Filter``
    # and :class:`Reactor` already use, so a future variant needing a
    # different set (a jacketed, indirect drier with a utility loop
    # rather than a direct gas sweep) is a dict entry rather than a
    # second mechanism.
    PORTS: list[tuple[str, str, str]] = []
    _GAS_SWEPT = [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._GAS_SWEPT)

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


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
    #: Six of the seven rows anchor the feed on the **roof**, because
    #: that is how a screen is loaded -- material is dropped onto the
    #: deck. Vertical position on a P&ID is not elevation, though, so
    #: read as a claim that nozzle puts whatever feeds a headworks screen
    #: directly above it and the raw influent comes in through the ceiling
    #: (#459). What feeds a screen is drawn where anything upstream is
    #: drawn: to the west.
    #:
    #: ``undersize`` is the other half: it leaves through the deck, so
    #: the symbol anchors it on the apex below, and it goes on east like
    #: any other product once it is out. South *east*, which is
    #: :class:`Separator`'s ``underflow`` on the same shape of machine
    #: and for the same reason -- the two products get a lane each
    #: instead of leaving by the same corner. ``oversize`` is already
    #: fixed east by the artwork and is left there; see :class:`Heater`
    #: on why restating a face costs more than it says.
    PLACES = {"feed": "W", "undersize": "SE"}
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

    def __init__(
        self,
        name: str,
        length: float | None = None,
        diameter: float | None = None,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
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
        super().__init__(
            name, variant=variant, label_pos=label_pos, description=description, reference=reference
        )
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
            SCREW_MIN_LENGTH,
            conveyor_min_length,
            conveyor_too_short,
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
            conveyor_bad_diameter,
            conveyor_min_length,
            conveyor_too_short,
            screw_bad_diameter,
        )

        if value <= 0:
            raise (screw_bad_diameter if self.variant == "screw" else conveyor_bad_diameter)(
                value, self.name
            )
        value = float(value)
        length = getattr(self, "_length", None)
        if self.variant != "screw" and length is not None and length < conveyor_min_length(value):
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
    #: Stage 2 places every balloon against frozen process geometry
    #: (:mod:`pandid.layout.control`), so an instrument is never an
    #: author of a stage 1 claim in the first place. Stated anyway, so
    #: that a reader of the ladder does not have to know that to know
    #: the answer.
    LAYOUT_CONFIDENCE = 0
    # The three a balloon is born with; ``sig_in`` and ``sig_out`` are
    # the first member of their pool. Declared rather than minted lazily
    # because ``ports`` is an ordered dict that
    # :mod:`pandid.layout.faces` serves in order, so a balloon whose
    # connections appeared as the author reached for them would draw
    # differently depending on which line was written first.
    PORTS = [
        ("pv", "inlet", "signal"),
        ("sig_in", "inlet", "signal"),
        ("sig_out", "outlet", "signal"),
    ]

    #: The two pools, and the name the first member of each ships under.
    _SIGNAL_POOLS = ("sig_in", "sig_out")

    #: The variants that stand for a function rather than a device. A
    #: trip square is a logic function, which acts in several places at
    #: once and is drawn in each of them under the same tag. ``"sis"``
    #: and ``"logic"`` are two names for one symbol.
    _REPEATABLE_VARIANTS = frozenset({"sis", "logic", "interlock"})

    def __init__(
        self,
        type: str,
        number: str | int = "",
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        display: str | None = None,
    ):
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
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
        drawn = ", ".join(
            f"variant={v!r} display={d!r}" for (v, d) in _BALLOON_SYMBOLS if d != "field"
        )
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
        # The numbering is :meth:`Unit._next_member`'s, shared with
        # :class:`_Boundary`'s flag so the two pools cannot come to
        # number their members differently. The direction is the pool's
        # first member's, as it always was: a minted ``sig_out_3`` is an
        # outlet because ``sig_out`` is.
        return self._next_member(base, self._pool_members(base)[0].direction, "signal")

    def _pool_members(self, base: str) -> list[Port]:
        return [p for name, p in self.ports.items() if self._pool_of(name) == base]

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

    def _mint_port(self, name: str) -> Port | None:
        """:meth:`signal_port`, as the hook a reader asks through.

        The public spelling stays: an author reaching a pool member the
        balloon has not grown yet writes ``pic.signal_port("sig_out_2")``
        and gets its message when the name is not one this class mints.
        This is the same question asked where a ``None`` is wanted rather
        than a raise, which is what :func:`pandid.spec._find_port` needs
        to fall through to its own report against the entry.
        """
        try:
            return self.signal_port(name)
        except KeyError:
            return None

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
        return (
            isinstance(other, Instrument)
            and other.tag == self.tag
            and self.variant in self._REPEATABLE_VARIANTS
            and symbol(self.variant) == symbol(other.variant)
        )

    def annotate(
        self,
        *,
        high: "str | Sequence[str] | None" = None,
        low: "str | Sequence[str] | None" = None,
        safety: "str | Sequence[str] | None" = None,
        variable: "str | Sequence[str] | None" = None,
    ) -> "Instrument":
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
        for name, codes in (("a", safety), ("b", variable), ("c", high), ("d", low)):
            if codes is None:
                continue
            written = _quadrant_codes(self.name, name, codes)
            if written:
                self.quadrants[name] = written
            else:
                self.quadrants.pop(name, None)
        return self

    def attach(
        self,
        on: "Stream | Unit",
        *,
        at: float | str | None = None,
        offset: float = 45.0,
        angle: float = 90.0,
        relation: str = "sensing",
    ) -> "Instrument":
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
    #: In the train, with an opinion about its own two sides and none
    #: about the sheet. No :attr:`~Unit.PLACES`: every exchanger nozzle
    #: is fixed to one face already, and which of them is the process
    #: side depends on the service rather than on the class -- the same
    #: shell-and-tube is a condenser over a column on one sheet and an
    #: interchanger in the middle of a train on the next. Stating
    #: "condensate falls south" here would drop every exchanger's
    #: downstream unit a row.
    LAYOUT_CONFIDENCE = 2
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

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
    LAYOUT_CONFIDENCE = 2
    #: ``utility_in`` is declared **empty**, and the process pair is left
    #: out. The nozzle is fixed to the symbol's south face because that
    #: is where the drawing puts it, and read as a claim that is the
    #: heater saying its steam supply is drawn below it. Five heaters on
    #: one header then muster 10 against a flag with no opinion of its
    #: own, and the header sinks below every consumer it feeds (#459).
    #: Where a steam header enters a sheet is a fact about the sheet's
    #: utilities, and the heater tapping it knows nothing about it.
    #:
    #: ``inlet`` and ``outlet`` are already fixed west and east by the
    #: artwork, so an entry restating them would only *lose* the
    #: placement transform: ``fixed_face`` mirrors with the unit and
    #: ``PLACES`` does not, so a heater drawn ``mirrored=True`` would go
    #: on claiming its feed lay west when the nozzle points east. That
    #: is measurable -- the same restatement on :class:`Furnace`, whose
    #: one mirrored instance in the corpus is ``20_molecular_sieve_dryer``,
    #: costs that sheet 14 crossings. So this states what the drawing
    #: does not, and nothing else.
    PLACES = {"utility_in": None}
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
    LAYOUT_CONFIDENCE = 2
    #: :class:`Heater`'s entry, mirrored: the cooling medium leaves by
    #: the symbol's north face, which read as a claim lifts a
    #: cooling-water return header above every consumer draining into
    #: it. Same nozzle, same drawing detail, same #459.
    PLACES = {"utility_out": None}
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
    #: A fixed point on the sheet, drawn where its train runs; a tower
    #: is the end of the cooling-water loop and the thing every cooler
    #: on the sheet is piped back to. :class:`Furnace`'s rung.
    LAYOUT_CONFIDENCE = 4
    #: ``water_out`` is drawn on the **basin**, at the foot of the
    #: tower, which is where a pump takes suction and not where the cold
    #: water supply belongs; read as a claim it drops the whole
    #: cold-water side of the sheet below the tower. The circulating
    #: loop runs through the tower like any other train, so it leaves
    #: east. ``water_in`` is already fixed west and stays with the
    #: artwork (see :class:`Heater`).
    #:
    #: The other three are declared empty. ``makeup`` and ``blowdown``
    #: are a service brought in and an effluent taken away, both to
    #: headers placed by where the sheet's utilities are, and ``air_in``
    #: is ambient or a fan intake with no drawn peer at all in the
    #: ordinary case. ``air_out`` is left to its own north face, which
    #: is not merely artwork: an exhaust is drawn leaving upward, the
    #: way a :class:`Vent` and a :class:`Stack` are.
    PLACES = {"water_out": "E", "air_in": None, "makeup": None, "blowdown": None}
    PORTS = [
        *_side_ports("water", "air"),
        ("makeup", "inlet", "utility"),
        ("blowdown", "outlet", "liquid"),
    ]


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Names for a unit's feeds: ``feed_1`` .. ``feed_n``.

    Numbered from one whatever the count, the way :class:`Mixer`'s
    ``in_1`` .. ``in_n`` and :class:`Splitter`'s ``out_1`` .. ``out_n``
    already are: ``feed_1`` is a real nozzle at ``n_feeds=1`` and stays
    one if the count is later raised, rather than existing only above
    one the way it used to. The caller adds the bare ``feed`` as an
    alias for ``feed_1`` when there is only one -- see
    :class:`Reactor`/:class:`Column`'s ``__init__`` -- since that
    spelling is the common case and reads better on the page than a
    ``_1`` nothing else on the vessel needs; it is not restated here
    because at every other count there is no bare name to give.

    Spelling is the only thing the count changes: ``unit.feeds`` is the
    family whatever it is, indexed from zero (``unit.feeds[0]`` is
    ``feed_1``) while the nozzles are numbered from one.
    """
    if n_feeds < 1:
        raise ValueError(f"{owner} requires at least 1 feed, got {n_feeds}")
    return [f"feed_{i}" for i in range(1, n_feeds + 1)]


def _draw_names(n_draws: int, owner: str) -> list[str]:
    """Names for a :class:`Column`'s side draws: none, ``draw``, or
    ``draw_1`` .. ``draw_n``.

    :func:`_feed_names` the other way round. A draw is the feed's flow
    reversed and most columns have none, so unlike a feed the count may
    be zero -- the empty list, and no nozzle at all -- rather than
    refusing anything short of one.
    """
    if n_draws < 0:
        raise ValueError(f"{owner} cannot take a negative number of draws, got {n_draws}")
    if n_draws == 0:
        return []
    return ["draw"] if n_draws == 1 else [f"draw_{i}" for i in range(1, n_draws + 1)]


def _stage_fractions(
    name: str,
    internals: str | None,
    trays: int,
    stages: list[int | None] | None,
    names: list[str],
    keyword: str,
    noun: str,
) -> dict[str, float]:
    """Validate ``keyword=`` (``feed_stages`` or ``draw_stages``) against
    ``names`` and turn it into a fraction of the shell, per nozzle that
    named one.

    ``None`` -- the default -- asks nothing of the shell: every nozzle
    keeps :class:`~pandid.render.symbols.PortSeries`'s even spread, and a
    column that names no stage is unchanged from the one 0.1.3 drew.

    Given a list, its length has to match ``names``: one entry per
    nozzle, in declaration order, so ``stages[i]`` is never read against
    the wrong one. An entry may be ``None``: that one nozzle keeps the
    even spread while its siblings pin to the stage they name, which is
    what lets an author place the solvent feed, or the semi-lean draw,
    and leave the rest where they always were.

    Shared by :class:`Column`'s feeds and its draws -- one function, so
    the two keywords cannot drift into checking the count, the bare
    shell or a stage out of range differently.
    """
    if stages is None:
        return {}
    if len(stages) != len(names):
        raise ValueError(
            f"{name} has {len(names)} {noun}{'s' if len(names) != 1 else ''} "
            f"({', '.join(names)}) but {keyword} names {len(stages)}; "
            f"give one entry per {noun}, in the same order, and null for a {noun} "
            f"that keeps the even spread"
        )
    if internals is None:
        if any(stage is not None for stage in stages):
            raise ValueError(
                f"{name}: {keyword} names a stage, and this column draws no "
                f"stages to put one on -- internals is None, so there is nothing on "
                f"the shell for a reader to count against. Give internals= a deck or "
                f"a bed, or drop {keyword} and let n_{noun}s spread the {noun}s evenly"
            )
        return {}
    from pandid.render.iso_parts import stage_fraction

    fractions = {}
    for one_name, stage in zip(names, stages):
        if stage is None:
            continue
        try:
            fractions[one_name] = stage_fraction(internals, stage, trays)
        except ValueError as e:
            raise ValueError(f"{name}.{one_name}: {e}") from None
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
    what="Reactor(variant='plain')",
    instead="Reactor(internals='packing')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 27.8 X8141's crossed bed on the "
    "standard vessel shell, in place of this one's diagonal hatch",
)


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
    what="Reactor(variant='mixing')",
    instead="Reactor(agitator='disc')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 1.27 X8006's dished-end shell with a "
    "group-28 stirrer and the motor that turns it, in place of this one's "
    "cone-bottomed box and the capsule on top of it; the cone goes, and "
    "the stirrer becomes one you can choose and route a drive to",
)


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
    # down the shell -- ``feed_1`` ... ``feed_n`` whatever the count
    # (see :func:`_feed_names`).
    feeds: tuple[Port, ...]
    # The one-feed vessel's charge nozzle: an alias for ``feed_1``, set
    # in ``__init__`` alongside it rather than a second registered port
    # -- ``feed`` and ``feed_1`` are the same ``Port`` object, so a
    # series placing the family sees one member, not two. ``n_feeds >
    # 1`` drops the alias; there is no bare name for a member of a
    # family of more than one, and ``.feed_1`` is what reaches the first
    # of them either way. See :class:`Mixer`.
    feed: Port

    # ``feed_1`` ... ``feed_n`` are the same shape as :class:`Column`'s
    # feeds and :class:`Mixer`'s numbered inlets, and are answered the
    # same way: a literal ``n_feeds`` gets a subclass declaring exactly
    # those nozzles, a computed one gets this class and
    # ``reactor.feeds[i]``.
    #
    # A one-feed vessel keeps the alias ``feed`` for ``feed_1`` -- see
    # :func:`_feed_names` -- and ``Reactor1`` declares ``feed_1`` itself
    # so a checker resolves it there too; the ``feed`` annotation above
    # already answers for the alias.
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
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Reactor1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Reactor2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Reactor3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Reactor4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Reactor5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Reactor6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Reactor7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Reactor8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Reactor": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Reactor": ...

    kind = "reactor"
    #: A reactor is what the sheet around it is drawn to serve, so it is
    #: as insistent as a tower.
    LAYOUT_CONFIDENCE = 8
    #: The two nozzles whose face is a fact about the *vessel* rather
    #: than about the drawing: the product leaves the floor because it
    #: drains and the off-gas leaves the side because that is where the
    #: nozzle is, but what either of them feeds is the next unit
    #: **along**. ``feed`` restates its own face, because a charge line
    #: coming from the left is a statement worth making at a reactor's
    #: weight rather than at a nozzle's.
    #:
    #: The ink and the claim therefore disagree about ``outlet``, which
    #: is not a defect to be reconciled away (#459 asks): the nozzle is
    #: on the floor and the pipe turns to reach a peer drawn level, and
    #: that is what a drawing does. Saying ``SE`` instead -- the claim
    #: the ink would make -- steps every downstream unit a row down at a
    #: reactor's confidence of 8, which is a staircase on a train of
    #: them: 23 crossings across the corpus, 17 of them on
    #: ``17_stirred_reactor_train``. A tower's ``bottoms`` is ``SE`` for
    #: a reason this does not share, that a column is drawn tall enough
    #: for its own bottom to be a row of its own.
    PLACES = {"feed": "W", "outlet": "E", "vent": "N"}
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
    #: See :attr:`Unit._FIXED_AT_CONSTRUCTION`: both choose the overlays
    #: -- and, for ``agitator``, the ``drive`` nozzle -- already built.
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator", "internals"})

    @classmethod
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
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
        return {
            **super().composition_defaults(variant, stated),
            "agitator": "agitator"
            if variant in cls._STIRRED and (stated or {}).get("internals") is None
            else None,
        }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """The nozzles a *variant* adds; none if the class declares any.

        The same one line :meth:`HeatExchanger._variant_ports` is.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._VESSEL)

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        agitator: str | None = _UNSTATED,
        internals: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Reactor")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # The argument, not ``self.variant``: a deprecation is about the
        # word the author typed. See :meth:`Vessel.__init__`.
        if variant == "plain":
            REACTOR_VARIANT_PLAIN.warn(self, where=name)
        elif variant == "mixing":
            REACTOR_VARIANT_MIXING.warn(self, where=name)
        if agitator is _UNSTATED:
            agitator = self.composition_defaults(self.variant, {"internals": internals})["agitator"]
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
            () if agitator is None else agitator_overlays(agitator, self.kind, self.variant),
        )
        # The drive is the *motor's*, and the motor comes with the
        # agitator, so it exists exactly when the agitator does.
        # Declared here rather than in ``_VARIANT_PORTS`` because the
        # part brings it and the part is chosen per unit, where a
        # variant's nozzles are the same for every unit that names it.
        if agitator is not None:
            self.drive = self._add_port("drive", "inlet", "energy")
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            # An alias, not a second port: registering ``feed`` too would
            # give the shell's ``PortSeries`` two names matching one
            # nozzle and it would spread a family of two down the shell
            # for a vessel that only has one. See :func:`_feed_names`.
            self.feed = self.feeds[0]


if TYPE_CHECKING:
    # A reactor of each feed count, for the overloads above. ``Reactor1``
    # is the one-feed vessel: its nozzle is really named ``feed_1``, so
    # that is declared here, and the alias ``feed`` the base class
    # already declares answers for the other spelling -- exactly as
    # ``Column1`` does.

    class Reactor1(Reactor):
        feed_1: Port

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
    instead="Separator(characteristic='gravity')",
    removed_in="0.2.0",
)
SEPARATOR_VARIANT_ELECTROSTATIC = Deprecation(
    what="Separator(variant='electrostatic')",
    instead="Separator(characteristic='electrostatic')",
    removed_in="0.2.0",
)
SEPARATOR_VARIANT_ELECTROMAGNETIC = Deprecation(
    what="Separator(variant='electromagnetic')",
    instead="Separator(characteristic='electromagnetic')",
    removed_in="0.2.0",
)

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

    More than one feed
    ------------------
    ``n_feeds`` gives the body more than one charge nozzle, the way it
    does on :class:`Column` and :class:`Reactor`. A wash-water gravity
    separator takes its wash beside the feed it is washing; a flare
    knock-out drum takes a header per relief system; a scrubber takes
    its make-up separately from the gas it cleans::

        Separator("V-401", n_feeds=2, characteristic="gravity")

    They are ``feed_1`` ... ``feed_n``, spread down the wall in
    declaration order so ``feed_1`` is the highest, and the single-feed
    separator keeps the plain ``feed`` as an alias for ``feed_1``. On
    the hopper-bottomed bodies the family grows **downwards** from the
    coordinate the one feed was always drawn at, rather than straddling
    it, so adding a second feed to an existing sheet does not move the
    first; see :data:`pandid.render.symbols.FROM_START`.

    ``variant="horizontal"`` is the one drawing that refuses a second
    feed, and it refuses it for a reason about the artwork rather than
    about the plant -- see :attr:`_ONE_FEED_VARIANTS`.
    """

    # The phase draws only, since ``_VARIANT_PORTS`` defaults to
    # ``_PHASES``. ``overflow`` and ``underflow`` are absent: seven of
    # the eleven variants have them *instead of* ``vapor`` and
    # ``liquid``, never as well, so declaring all four would tell a
    # checker a plain flash drum has an ``overflow``. They belong on a
    # per-variant subclass, which ``pandid.devices`` is; off it, reach
    # one by ``sep.port("overflow")``.
    vapor: Port
    liquid: Port
    # Every feed nozzle, in declaration order and so top to bottom down
    # the wall -- ``feed_1`` ... ``feed_n`` whatever the count (see
    # :func:`_feed_names`). :class:`Reactor`'s and :class:`Column`'s
    # exactly.
    feeds: tuple[Port, ...]
    # The one-feed separator's nozzle: an alias for ``feed_1``, not a
    # second registered port. ``n_feeds > 1`` drops the alias. See
    # :class:`Reactor`.
    feed: Port

    # ``feed_1`` ... ``feed_n`` are :class:`Column`'s and
    # :class:`Reactor`'s feeds, answered the same way: a literal
    # ``n_feeds`` gets a subclass declaring exactly those nozzles, a
    # computed one gets this class and ``sep.feeds[i]``. One family and
    # not two, unlike ``Column``: the draws a separator has are fixed by
    # its variant, so there is no count on that side to cross.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Separator1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Separator2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Separator3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Separator4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Separator5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Separator6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Separator7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Separator8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Separator": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Separator": ...

    kind = "separator"
    LAYOUT_CONFIDENCE = 4
    #: Down and to the right for what leaves the bottom, so the two
    #: draws never land in one cell and the feed side of the drum stays
    #: clear. Read straight off the faces instead, both draws share the
    #: drum's own column and whichever of them continues the train has
    #: to come back out of it.
    #:
    #: ``vapor`` is the exception, and is east rather than north east: a
    #: flash drum's vapour leaves the top because vapour does, and what
    #: it feeds is still the next unit **along**. Lifted a row instead,
    #: a knockout drum drags the compressor after it off the spine and
    #: the whole train behind it climbs -- ``05_reactor_recycle`` went
    #: from one straight row of equipment to a staircase three rows
    #: deep. ``overflow`` is not the same nozzle: a cyclone's clean gas
    #: really does leave the train, going up and away while the solids
    #: go down and on.
    PLACES = {
        "feed": "W",
        "vapor": "E", "liquid": "SE",
        "overflow": "NE", "underflow": "SE",
    }
    # Empty because which nozzles a separator has depends on its
    # variant, and Unit.__init__ reads PORTS before a variant is in
    # hand. _VARIANT_PORTS below is the declaration and __init__ lays it
    # down, as HeatExchanger does.
    PORTS: list[tuple[str, str, str]] = []
    # The flash drum, and the default.
    #
    # No ``feed``: the charge nozzles are a family sized by ``n_feeds``
    # and ``__init__`` lays them down after these, exactly as
    # :class:`Reactor` does with ``_VESSEL``. Both tables here are the
    # *draws* and nothing else.
    _PHASES = [
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
        # The horizontal drum's charge nozzle is still called ``feed`` in
        # its artwork, because it is the one separator whose feed is not
        # a family: see :attr:`_ONE_FEED_VARIANTS`. The nozzle is
        # ``feed_1`` here like every other separator's, so this is what
        # sends it to the three-placement menu the stencil really draws
        # -- without it the name the stencil never heard of falls back to
        # the centre of the box.
        "horizontal": {"feed_1": "feed"},
    }

    #: The three drawings that are the shared separating vessel carrying
    #: one ISO group-29 characteristic, and so the three the keyword
    #: names. The registry builds each by composition and records the
    #: registration number ISO gives the result; see
    #: :meth:`pandid.render.symbols.SymbolRegistry._register_composed`.
    _CHARACTERISTICS = ("gravity", "electrostatic", "electromagnetic")

    #: The variants that take one feed and refuse a second, keyed to what
    #: an author is told to do instead.
    #:
    #: ``horizontal`` alone, and it is the *drawing* that says so rather
    #: than the plant. That stencil authors three placements for its
    #: charge nozzle -- the west head, the north shell, the east head --
    #: and :class:`~pandid.render.symbols.Symbol` refuses to carry both a
    #: menu and a family for one nozzle, since a
    #: :class:`~pandid.render.symbols.PortSeries` is one band on one
    #: face and would have to overwrite the other two. The menu is worth
    #: more: it is what lets the face selector put the inlet on the head
    #: the feed actually arrives from, which is a choice this drum is
    #: made to offer and the upright ones are not.
    #:
    #: The body could not hold a family in any case. It is 30 units
    #: deep, so its west face has room for two
    #: :data:`~pandid.render.symbols.ARROWHEAD`\ s and no paper between
    #: them; every other separator has a wall of 80 or more.
    _ONE_FEED_VARIANTS = {
        "horizontal": "Separator(variant='default'), the upright drum, takes as many as "
                      "you like, and a Mixer ahead of the drum draws the junction where "
                      "two feeds really do combine before they enter",
    }

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

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        characteristic: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Separator")
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
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
        self.characteristic = self.variant if self.variant in self._CHARACTERISTICS else None
        # ``self.variant``, and after the base has resolved it: a device
        # subclass reaches ``horizontal`` through ``VARIANT_ALIASES``
        # rather than by naming it, so reading the argument would let one
        # of those through with a count its stencil cannot draw.
        instead = self._ONE_FEED_VARIANTS.get(self.variant)
        if instead is not None and n_feeds != 1:
            raise ValueError(
                f"{name}: Separator(variant={self.variant!r}) is drawn with one feed "
                f"nozzle and you asked for {n_feeds}. Its charge nozzle is drawn on "
                f"whichever of three heads the line comes from, and a family is spread "
                f"down one face, so the drawing can offer one or the other and this one "
                f"offers the choice of head. {instead}"
            )
        # Before the draws, which is where ``feed`` was when ``_PHASES``
        # and ``_OVER_AND_UNDER`` still held it: a unit's declaration
        # order is the order its nozzles are read in, and a family
        # replacing a fixed nozzle should not also move it down the list.
        # (:class:`Reactor` adds its feeds last for the same reason read
        # the other way -- ``feed`` was never first in its table.)
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            # An alias, not a second port: registering ``feed`` too would
            # give the wall's ``PortSeries`` two names matching one
            # nozzle and it would spread a family of two for a vessel
            # that only has one. See :func:`_feed_names`.
            self.feed = self.feeds[0]
        # ``self.variant`` rather than the argument; see HeatExchanger.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


if TYPE_CHECKING:
    # A separator of each feed count, for the overloads above.
    # ``Separator1`` is the one-feed vessel: its nozzle is really named
    # ``feed_1``, so that is declared here, and the alias ``feed`` the
    # base class already declares answers for the other spelling --
    # exactly as ``Column1`` and ``Reactor1`` do.

    class Separator1(Separator):
        feed_1: Port

    class Separator2(Separator):
        feed_1: Port
        feed_2: Port

    class Separator3(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Separator4(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Separator5(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Separator6(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Separator7(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Separator8(Separator):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


#: How many decks a tower is drawn with when the author does not say.
#: A number, because a drawing has to pick one and no number is the real
#: tray count anyway -- a forty-tray column is not drawn with forty lines
#: on any sheet. **Eight**, which is what ISO 10628-2 item 2.6 X8011
#: draws: eight decks at a 2 M pitch down a 16 M straight side.
DEFAULT_TRAYS = 8

# ``Column`` used to carry every nozzle a distillation column has, and
# ``Absorber``/``Stripper`` inherited four of them dishonestly (#400):
# Python cannot un-declare an inherited annotation, so a checker saw a
# reflux nozzle on a tower that raised the moment one was connected.  The
# fix is structural -- ``Column`` becomes the general tower and
# :class:`DistillationColumn` the specific one, matching
# :class:`Separator`, the one other class with a family of narrower
# subclasses -- and these five declarations are what keeps every sheet
# already writing the old spellings on its feet for one release.
#
# All five draw the same ``kind="column"`` symbol as before: nothing here
# moves a nozzle's position on the shell, only which class answers for
# it, so every ``note`` below is empty.
COLUMN_REFLUX_IN = Deprecation(
    what="Column(...).reflux_in", instead="DistillationColumn(...).reflux_in", removed_in="0.2.0"
)
COLUMN_BOILUP_IN = Deprecation(
    what="Column(...).boilup_in", instead="DistillationColumn(...).boilup_in", removed_in="0.2.0"
)
COLUMN_REBOILER_DUTY = Deprecation(
    what="Column(...).reboiler_duty",
    instead="DistillationColumn(...).reboiler_duty",
    removed_in="0.2.0",
)
COLUMN_CONDENSER_DUTY = Deprecation(
    what="Column(...).condenser_duty",
    instead="DistillationColumn(...).condenser_duty",
    removed_in="0.2.0",
)
#: Not a class move: ``distillate`` is retired on every tower it ever
#: named, ``Column`` included, in favour of ``overhead`` -- the position
#: name :class:`Separator` already chose ``overflow``/``underflow`` for,
#: and for the same reason. ``distillate`` is a distillation word and an
#: absorber's overhead product is stripped gas, not distillate; #398
#: fixed that category error four times over and left this the fifth.
COLUMN_DISTILLATE = Deprecation(
    what="Column(...).distillate", instead="Column(...).overhead", removed_in="0.2.0"
)


class Column(Unit):
    """A general tower: one dished-end shell, fed at one end and drawn from
    both.

    Every column has a feed, an ``overhead`` product off the top and
    ``bottoms`` off the bottom -- and nothing else, because nothing about
    those three assumes the tower boils. :class:`DistillationColumn` adds
    the reflux loop and the reboiler a *distillation* column has;
    :class:`Stripper` adds the reboiler alone; :class:`Absorber` adds
    neither, because an absorber is a general tower with an honest name.
    This class is their common base for exactly that reason -- the
    :class:`Separator` shape, one base carrying what every subclass has
    and nothing narrower -- so ``t: Column`` accepts any of the four and
    a checker never sees a nozzle a plain ``Column`` does not build.

    A plain ``Column(...)`` is still what an author writes for equipment
    that never had a reflux loop -- a scrubber, an adsorber, a molecular
    sieve -- and ``col.reflux_in``/``.boilup_in``/``.reboiler_duty``/
    ``.condenser_duty`` still work for one release where an existing sheet
    reaches for them on a tower that should have been built as a
    :class:`DistillationColumn`, with a warning naming the class to move
    to. ``col.distillate`` still works the same way, everywhere it used
    to, warning towards ``.overhead``.

    ``n_feeds`` gives the tower more than one feed nozzle: an extractive
    distillation takes its solvent above the feed tray, an azeotropic
    tower its entrainer. They are ``feed_1`` ... ``feed_n``, spread down
    the shell in declaration order, so ``feed_1`` is the highest; the
    single-feed column keeps the plain ``feed``.

    ``n_draws`` gives it a side draw: a sidestream tower -- a crude
    atmospheric column, a solvent recovery train, any three-product
    fractionation -- pulls a third product off the shell between the two
    ends. Unlike a feed, none is the ordinary case, so it defaults to
    zero and the family is ``draw`` / ``draw_1`` ... ``draw_n`` on the
    shell's **east** face, opposite the feeds -- a draw is a feed's flow
    reversed. It places a nozzle only: a real draw is vapour or liquid
    and the two leave different nozzles on a real sheet, but a feed does
    not distinguish that either, so doing it for a draw alone would be
    inconsistent. The phase belongs on the port's ``role``, not on its
    placement, and nothing here draws above-or-below-the-tray geometry
    for it. A pumparound is a draw at one stage and an ordinary feed
    carrying the return at another -- two nozzles, wired with a plain
    ``connect()`` and no paired abstraction for it, the same way reflux
    is not one either.

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

    Where a draw leaves
    --------------------
    ``draw_stages=`` puts a draw on the stage it actually leaves from --
    the identical mechanism, read in the other direction::

        Column("T-301", internals="valve_tray", trays=30,
               n_draws=1, draw_stages=[15])

    One entry per draw, in the same declaration order, and every rule
    ``feed_stages=`` follows above applies unchanged: ``None`` keeps the
    even spread, a stage out of range names the count the column really
    has, and a stage named on a bare shell is refused for the reason a
    feed's is.
    """

    overhead: Port
    bottoms: Port
    # Every feed nozzle, in declaration order and so highest first,
    # whatever the count spelled them. See :class:`Reactor`.
    feeds: tuple[Port, ...]
    # The single-feed tower's nozzle: an alias for ``feed_1``, not a
    # second registered port. ``n_feeds > 1`` drops the alias. See
    # :class:`Reactor`.
    feed: Port
    # Every side draw, in declaration order and so highest first,
    # whatever the count spelled them -- ``feeds`` above, read the other
    # way. Unlike ``feed``, there is no bare ``draw: Port`` beside this
    # one: ``n_draws`` defaults to zero, so a lone draw is not a nozzle
    # every column has the way a lone feed is, and declaring one here
    # would be a phantom on every column that draws nothing. See
    # :func:`_draw_names` and ``ColumnDraw1`` below, which is where a
    # one-draw tower's singular ``draw`` really gets declared.
    draws: tuple[Port, ...]

    # Two independent arity families on one class -- ``n_feeds`` and
    # ``n_draws`` -- and fully cross-typing them would be 8 x 8 = 64
    # ``TYPE_CHECKING`` classes for a combination almost nothing draws:
    # a column with more than one of *both* a feed and a draw is rare,
    # and a checker that cannot resolve ``feed_2`` on it has lost nothing
    # ``t: Column`` did not already accept.
    #
    # So this is two independent overload families instead, each
    # covering the case that is actually common:
    #
    # - **any n_feeds, n_draws=0** (the ordinary column, drawing no
    #   side stream at all) -- ``Column1`` .. ``Column8``, exactly as
    #   before this class had a second count;
    # - **n_feeds=1, any n_draws** (a plain tower with one side draw)
    #   -- ``ColumnDraw1`` .. ``ColumnDraw8``.
    #
    # A call naming *both* counts above one matches neither family and
    # falls through to the last, untyped overload, which hands back the
    # plain ``Column``: every nozzle it really has is still reachable
    # through ``col.feeds``/``col.draws`` or ``col.port(...)``, just not
    # by the numbered attribute spelling. That is the same trade
    # :class:`Reactor` and :class:`Mixer` already take for a *computed*
    # count -- honest rather than restrictive, since nothing about
    # ``n_feeds=2, n_draws=2`` is a literal a checker could not in
    # principle have resolved, only one this class declines to spend 64
    # classes resolving.
    #
    # This still catches every typo the single-family version did:
    # neither family reaches for a blanket ``__getattr__`` the way
    # :class:`Block` does, because a column carries fixed nozzles worth
    # catching a misspelling on and a block carries almost none -- see
    # :class:`Block`'s own comment on that trade, and
    # ``tests/test_port_annotations.py``'s ``_CHECKER_VISIBLE_GETATTR``,
    # which pins that ``Block`` is still the only class paying it.
    # :attr:`_RETIRED_PORTS`/:attr:`_RETIRED_PORT_ALIASES` are a
    # different mechanism from both: they answer through
    # :meth:`Unit.__getattr__`, which stays hidden from a checker, so
    # ``col.reflux_in`` still raises at edit time on a plain ``Column``
    # even though it still works at run time.
    if TYPE_CHECKING:
        # Family A: any n_feeds, n_draws pinned at its own default (0).
        # ``n_draws`` sits after ``*args`` -- keyword-only, exactly like
        # every other keyword this constructor takes beyond ``n_feeds``
        # -- so naming it changes nothing about how any positional call
        # this library has ever been written with resolves.
        @overload
        def __new__(
            cls,
            name: str,
            n_feeds: Literal[1] = 1,
            *args: Any,
            n_draws: Literal[0] = 0,
            **kwargs: Any,
        ) -> "Column1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column8": ...

        # Family B: n_feeds pinned at its own default (1), any n_draws.
        # ``n_draws`` takes no default here -- unlike Family A's, this
        # literal is what a call has to *name* for one of these eight to
        # match at all, so a bare ``Column("T-1")`` keeps resolving to
        # ``Column1`` above rather than to ``ColumnDraw1``.
        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[1], **kwargs: Any
        ) -> "ColumnDraw1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[2], **kwargs: Any
        ) -> "ColumnDraw2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[3], **kwargs: Any
        ) -> "ColumnDraw3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[4], **kwargs: Any
        ) -> "ColumnDraw4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[5], **kwargs: Any
        ) -> "ColumnDraw5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[6], **kwargs: Any
        ) -> "ColumnDraw6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[7], **kwargs: Any
        ) -> "ColumnDraw7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[8], **kwargs: Any
        ) -> "ColumnDraw8": ...

        # The intersection -- both counts above one -- and every
        # computed count: neither family above matches, so this is what
        # both an ``n_feeds=2, n_draws=2`` and an
        # ``n_feeds=len(...)`` call resolve to.
        @overload
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, n_draws: int = 0, **kwargs: Any
        ) -> "Column": ...
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, n_draws: int = 0, **kwargs: Any
        ) -> "Column": ...

    kind = "column"
    #: A tower is the thing a sheet is drawn around, and the arrangement
    #: below is a convention a reader expects rather than a consequence
    #: of what the tower happens to be connected to. Nothing else on a
    #: fractionation sheet has that standing, which is what the number
    #: says.
    LAYOUT_CONFIDENCE = 8
    #: Which is the whole of #446. Every one of these nozzles is fixed
    #: to a face already -- ``overhead`` north, ``bottoms`` south,
    #: ``reflux_in`` and ``boilup_in`` east -- and not one of those faces
    #: is where the peer is drawn. A condenser's own inlet is fixed
    #: north too, so read off the faces the pair states that each is
    #: above the other, which is no statement at all and left the tower
    #: to be drawn upside down by whatever had an opinion next.
    #:
    #: North *east* rather than north, and south *east* rather than
    #: south, so the overhead system and the reboiler loop each get a
    #: column of their own and the tower's west side stays clear for the
    #: feed.
    #:
    #: The two **returns** are north east and south east for the same
    #: reason the two draws are, and it has to be the same answer: the
    #: reflux comes back from the drum the overhead went to and the
    #: boilup from the reboiler the bottoms went to, so ``reflux_in: N``
    #: beside ``overhead: NE`` is the tower asserting that one cluster
    #: is in two places.
    #:
    #: **These two entries do very little, and the reason is worth
    #: knowing before anyone tunes them.** 13 of the 17 ``reflux_in`` and
    #: ``boilup_in`` connections in the shipped corpus are the run the
    #: cycle breaker tore, and a return line is read for the pipe alone
    #: (:mod:`pandid.layout.claims`) -- ``PLACES`` never sees it. What is
    #: left is four connections, and switching both entries to the
    #: ``N``/``S`` of the approved design moves the corpus by **one**
    #: crossing, 240 to 241, measured with ``scripts/layout_quality.py``.
    #: The consistency argument above is the whole of the case for them;
    #: an earlier version of this comment claimed 50 crossings, which was
    #: measured against an engine that read a return's nozzles and is no
    #: longer true of anything.
    #:
    #: A side draw is the one entry that is merely a preference: a
    #: sidestream goes east because everything downstream does, and a
    #: tower with four of them should not be as sure of that as it is of
    #: where its own condenser goes.
    PLACES = {
        "feed": "W",
        "overhead": "NE",
        "reflux_in": "NE",
        "bottoms": "SE",
        "boilup_in": "SE",
        "draw": ("E", 4),
    }
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    #: The vendored artwork still anchors this nozzle under its pre-0.1.4
    #: name -- a rename of the *nozzle*, not a redrawing of the symbol,
    #: so the artwork itself did not move. Without this, ``overhead``
    #: finds no anchor the symbol answers to and falls back to the
    #: box centre; inherited by every subclass, since none renames its
    #: own artwork either.
    PORT_ANCHORS = {"overhead": "distillate"}

    # The four nozzles a distillation column has and a general tower does
    # not (see :class:`DistillationColumn`), reachable here -- once, with
    # a warning -- for one release. Same ``(direction, role)`` a
    # :class:`DistillationColumn` builds them with, so a stream connected
    # through the old spelling draws exactly where the new one would.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {
        "reflux_in": ("inlet", "liquid", COLUMN_REFLUX_IN),
        "boilup_in": ("inlet", "vapor", COLUMN_BOILUP_IN),
        "reboiler_duty": ("inlet", "energy", COLUMN_REBOILER_DUTY),
        "condenser_duty": ("outlet", "energy", COLUMN_CONDENSER_DUTY),
    }
    #: ``distillate`` was this nozzle's name through 0.1.3; every
    #: subclass inherits this unchanged, since the rename is not about
    #: which class the nozzle lives on.
    _RETIRED_PORT_ALIASES: dict[str, tuple[str, Deprecation]] = {
        "distillate": ("overhead", COLUMN_DISTILLATE),
    }

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
    #: See :attr:`Unit._FIXED_AT_CONSTRUCTION`. ``internals``/``trays``
    #: choose the overlay; ``feed_stages``/``draw_stages`` choose where
    #: the nozzles they place sit on the shell -- placement rather than
    #: artwork, but read once and built into ``_stage_fractions`` the
    #: same way. Declared once here rather than on
    #: :class:`DistillationColumn`, :class:`Absorber` and
    #: :class:`Stripper` too: none of them overrides how any of the four
    #: is read, so all four inherit this set unchanged, which is what
    #: keeps the refusal uniform across every column rather than a
    #: per-subclass copy that could quietly drift from it.
    _FIXED_AT_CONSTRUCTION = frozenset(
        {"internals", "trays", "feed_stages", "draw_stages"}
    )

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        internals: str | None = _UNSTATED,
        trays: int = DEFAULT_TRAYS,
        feed_stages: list[int | None] | None = None,
        n_draws: int = 0,
        draw_stages: list[int | None] | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Column")
        draw_names = _draw_names(n_draws, "Column")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        if internals is _UNSTATED:
            internals = self.composition_defaults(self.variant)["internals"]
        self.internals = internals
        self.trays = trays
        from pandid.render.iso_parts import internals_overlays

        _compose_onto(self, () if internals is None else internals_overlays(internals, trays))
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        self.draws = tuple(self._add_port(draw, "outlet", "draw") for draw in draw_names)
        if n_feeds == 1:
            # An alias, not a second port; see :class:`Reactor`.
            self.feed = self.feeds[0]
        self.feed_stages = feed_stages
        self.draw_stages = draw_stages
        self._stage_fractions = {
            **_stage_fractions(name, internals, trays, feed_stages, names, "feed_stages", "feed"),
            **_stage_fractions(
                name, internals, trays, draw_stages, draw_names, "draw_stages", "draw"
            ),
        }

    def _series_pin(self, port_name: str) -> float | None:
        return self._stage_fractions.get(port_name)


if TYPE_CHECKING:
    # A column of each feed count, for the overloads above. ``Column1``
    # is the one-feed tower: its nozzle is really named ``feed_1``, so
    # that is declared here, and the alias ``feed`` the base class
    # already declares answers for the other spelling.

    class Column1(Column):
        feed_1: Port

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

    # A column of each draw count, for Family B above -- the same
    # pattern read the other way, but asymmetric with the feeds above
    # it: the alias ``feed`` is on the base class because ``n_feeds``
    # defaults to 1, so a one-feed tower always has it, while ``draw``
    # is on no base class at all, because ``n_draws`` defaults to 0, so
    # nothing here can say a plain ``Column`` has one. Unlike a feed, a
    # lone draw stays the bare singular name rather than also getting a
    # numbered ``draw_1``: :func:`_draw_names`, unlike :func:`_feed_names`,
    # is not a real port for every count, so there is no ``feed_1``-style
    # member to alias it to. ``ColumnDraw1`` is where that singular
    # nozzle really gets declared.

    class ColumnDraw1(Column):
        draw: Port

    class ColumnDraw2(Column):
        draw_1: Port
        draw_2: Port

    class ColumnDraw3(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port

    class ColumnDraw4(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port

    class ColumnDraw5(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port

    class ColumnDraw6(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port

    class ColumnDraw7(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port
        draw_7: Port

    class ColumnDraw8(Column):
        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port
        draw_7: Port
        draw_8: Port


class DistillationColumn(Column):
    """Distillation column: reflux at the top, a reboiler at the bottom.

    Besides the feed and the two products :class:`Column` already gives
    every tower, a distillation column carries two *return* nozzles that
    close its internal loops: ``reflux_in`` (liquid back to the top from
    the reflux drum) and ``boilup_in`` (vapour back to the bottom from
    the reboiler), plus the ``reboiler_duty`` and ``condenser_duty``
    energy streams the two exchangers carry. See :class:`Stripper` for
    the reboiler alone, and :class:`Absorber` for neither.

    Everything else is :class:`Column`'s own and works exactly the same
    way here: ``internals=``, ``trays=``, ``n_feeds=``, ``feed_stages=``,
    ``n_draws=`` and ``draw_stages=`` are that class's keywords, not
    this one's::

        DistillationColumn("T-101", internals="valve_tray", trays=30)

    This class carries the four nozzles :class:`Column` carried outright
    through 0.1.3. They moved here in 0.1.4 (#400) because a checker
    could not otherwise see that :class:`Absorber` and :class:`Stripper`
    do not have them: Python has no way to un-declare an inherited
    annotation, so putting them on the base told a checker every tower
    reboils. ``Column(...).reflux_in`` and the other three still work,
    with a warning naming this class, for one release.
    """

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reflux_in", "inlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]

    overhead: Port
    bottoms: Port
    reflux_in: Port
    boilup_in: Port
    reboiler_duty: Port
    condenser_duty: Port

    # Copied from :class:`Column`'s own overloads rather than inherited,
    # for :class:`Absorber`'s reason: a literal ``n_feeds`` has to
    # resolve to ``DistillationColumn2``, not ``Column2``. ``n_draws=``
    # is untyped here for the same reason it is on :class:`Absorber` and
    # :class:`Stripper` -- a second overload family for every
    # narrower-or-wider subclass would spend the class-explosion problem
    # a third time.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "DistillationColumn1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "DistillationColumn2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "DistillationColumn3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "DistillationColumn4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "DistillationColumn5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "DistillationColumn6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "DistillationColumn7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "DistillationColumn8": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: int, *args: Any, **kwargs: Any
        ) -> "DistillationColumn": ...
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any
        ) -> "DistillationColumn": ...


if TYPE_CHECKING:

    class DistillationColumn1(DistillationColumn):
        feed_1: Port

    class DistillationColumn2(DistillationColumn):
        feed_1: Port
        feed_2: Port

    class DistillationColumn3(DistillationColumn):
        feed_1: Port
        feed_2: Port
        feed_3: Port

    class DistillationColumn4(DistillationColumn):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class DistillationColumn5(DistillationColumn):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class DistillationColumn6(DistillationColumn):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class DistillationColumn7(DistillationColumn):
        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class DistillationColumn8(DistillationColumn):
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

    :class:`Column` itself, and honestly -- an absorber *is* a general
    tower, so this class adds nothing to its base. ISO gives an absorber,
    a scrubber and a molecular sieve no symbol of its own, so the drawing
    is the same dished-end shell carrying whichever group-27 internal it
    really holds, exactly as the module docstring already says. Gas
    enters at the bottom and lean liquid at the top; treated gas leaves
    over ``overhead`` and rich liquid over ``bottoms``, and the two
    counter-current inlets are ``n_feeds=2``, placed on the trays they
    actually enter::

        Absorber("V-501", internals="packing",
                 n_feeds=2, feed_stages=[1, 8])

    ``reflux_in``, ``boilup_in``, ``reboiler_duty`` and ``condenser_duty``
    stay refused here, even during :class:`Column`'s own deprecation
    window for them: nothing in an absorber boils, and this class exists
    so that wiring one of those four to a stream the vessel does not have
    is refused rather than silently drawn on an unconnected nozzle. See
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
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    overhead: Port
    bottoms: Port

    #: None of :class:`Column`'s four distillation-only nozzles: an
    #: absorber never carried them honestly, so it does not inherit the
    #: one-release grace period either -- ``absorber.reflux_in`` still
    #: raises outright. ``_RETIRED_PORT_ALIASES`` is *not* overridden:
    #: ``.distillate`` still warns towards ``.overhead`` here too, since
    #: that rename is not about which class the nozzle lives on.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

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
    #
    # ``n_draws=``/``draw_stages=`` are still :class:`Column`'s own
    # keywords and work exactly the same way at run time here -- an
    # absorber can carry a semi-lean draw the same way any column
    # carries a side draw. What is *not* copied is Column's second
    # overload family: giving every reduced-port-set subclass its own
    # copy of the draw family too would spend the 64-class problem
    # Column's own comment argues against a second time. So ``n_draws=``
    # lands in ``**kwargs`` below, untyped, and ``absorber.draw_2`` does
    # not resolve even though the nozzle is really there once
    # ``n_draws=2`` is given -- the same honest gap ``m.inlets[i]``
    # covers for a *computed* count elsewhere in this module.
    # ``absorber.draws[i]`` or ``absorber.port("draw_2")`` is the typed
    # route.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Absorber1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Absorber2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Absorber3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Absorber4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Absorber5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Absorber6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Absorber7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Absorber8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Absorber": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Absorber": ...


if TYPE_CHECKING:

    class Absorber1(Absorber):
        feed_1: Port

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
    ``internals=`` the same way an absorber's or a distillation column's
    is. Sitting *beside* :class:`DistillationColumn` rather than under
    it: a stripper carries a reboiler and the vapour it returns, but
    nothing condenses and nothing refluxes, because what leaves the top
    is the stripped-out product itself, not something the tower recovers
    and sends back down. ``overhead``, ``bottoms``, ``reboiler_duty`` and
    ``boilup_in`` are here; ``reflux_in`` and ``condenser_duty`` are not,
    and stay refused even during :class:`Column`'s own deprecation window
    for them -- nothing here condenses, and this class exists so that
    wiring either to a stream the vessel does not have is refused rather
    than silently drawn on an unconnected nozzle.

    ``internals=`` and ``trays=`` are unchanged from :class:`Column`: a
    stripper is at least as often trayed as packed, so unlike
    :class:`Absorber` this class states no default of its own.
    """

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
    ]

    overhead: Port
    bottoms: Port
    boilup_in: Port
    reboiler_duty: Port

    #: Neither of the two nozzles left -- ``reflux_in``/``condenser_duty``
    #: -- for :class:`Absorber`'s reason: a stripper never carried them
    #: honestly either, so it does not inherit :class:`Column`'s grace
    #: period for them. ``boilup_in``/``reboiler_duty`` need no entry
    #: here at all: this class already builds them for real, so they
    #: resolve through the ordinary instance dict and never reach
    #: :meth:`Unit.__getattr__`. ``_RETIRED_PORT_ALIASES`` is not
    #: overridden, for :class:`Absorber`'s reason.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

    # See :class:`Absorber`'s comment on the same block: a literal
    # ``n_feeds`` has to resolve to ``Stripper2``, not ``Column2``, and
    # ``n_draws=`` is untyped here for the same reason it is there.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Stripper1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Stripper2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Stripper3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Stripper4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Stripper5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Stripper6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Stripper7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Stripper8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Stripper": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Stripper": ...


if TYPE_CHECKING:

    class Stripper1(Stripper):
        feed_1: Port

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
        def __new__(
            cls, name: str, n_inlets: Literal[1], *args: Any, **kwargs: Any
        ) -> "Mixer1": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[2] = 2, *args: Any, **kwargs: Any
        ) -> "Mixer2": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[3], *args: Any, **kwargs: Any
        ) -> "Mixer3": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[4], *args: Any, **kwargs: Any
        ) -> "Mixer4": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[5], *args: Any, **kwargs: Any
        ) -> "Mixer5": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[6], *args: Any, **kwargs: Any
        ) -> "Mixer6": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[7], *args: Any, **kwargs: Any
        ) -> "Mixer7": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[8], *args: Any, **kwargs: Any
        ) -> "Mixer8": ...

        @overload
        def __new__(cls, name: str, n_inlets: int, *args: Any, **kwargs: Any) -> "Mixer": ...
        def __new__(cls, name: str, n_inlets: int = 2, *args: Any, **kwargs: Any) -> "Mixer": ...

    kind = "mixer"
    #: In the train, with an opinion about its own two sides and none
    #: about the sheet -- the rung a pump and an exchanger sit on, and
    #: the right one for a machine every line on it passes *through*.
    #: At the base 1 a mixer was the weakest non-zero class in the
    #: library and the bank it collects from dragged it off its own
    #: header line; a mixer and a splitter are the only manifold
    #: primitives here, so that is a sheet's whole junction geometry
    #: coming loose (#459).
    LAYOUT_CONFIDENCE = 2
    # No PLACES. The symbol already fixes every ``in_n`` west and the
    # outlet east at any arity, so ``{"in": "W", "outlet": "E"}`` would
    # restate the drawing and, restating it, lose the mirror the drawing
    # carries and this attribute does not -- see :class:`Heater`. What
    # was wrong here was the weight, not the directions.

    def __init__(
        self,
        name: str,
        n_inlets: int = 2,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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
        def __new__(
            cls, name: str, n_outlets: Literal[1], *args: Any, **kwargs: Any
        ) -> "Splitter1": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[2] = 2, *args: Any, **kwargs: Any
        ) -> "Splitter2": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[3], *args: Any, **kwargs: Any
        ) -> "Splitter3": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[4], *args: Any, **kwargs: Any
        ) -> "Splitter4": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[5], *args: Any, **kwargs: Any
        ) -> "Splitter5": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[6], *args: Any, **kwargs: Any
        ) -> "Splitter6": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[7], *args: Any, **kwargs: Any
        ) -> "Splitter7": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[8], *args: Any, **kwargs: Any
        ) -> "Splitter8": ...

        @overload
        def __new__(cls, name: str, n_outlets: int, *args: Any, **kwargs: Any) -> "Splitter": ...
        def __new__(
            cls, name: str, n_outlets: int = 2, *args: Any, **kwargs: Any
        ) -> "Splitter": ...

    kind = "splitter"
    #: :class:`Mixer`'s, for the same reason and on the same rung, and
    #: no ``PLACES`` for the same reason either.
    LAYOUT_CONFIDENCE = 2

    def __init__(
        self,
        name: str,
        n_outlets: int = 2,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
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


def _block_faces(spec: "int | Sequence[str]", default: str, owner: str, argument: str) -> list[str]:
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
    resolved = (
        _FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
        if isinstance(face, str)
        else None
    )
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

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        in_faces = _block_faces(inputs, self.DEFAULT_INPUT_FACE, name, "inputs")
        out_faces = _block_faces(outputs, self.DEFAULT_OUTPUT_FACE, name, "outputs")
        if not in_faces and not out_faces:
            raise ValueError(
                f"{name}: a block with no connections is a rectangle with a word "
                f"in it, which nothing can be routed to. Give it at least one "
                f"inputs= or outputs=."
            )
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        #: connection name -> the face it leaves from, in port order.
        #: The single authority: the symbol is built from it.
        self._faces: dict[str, str] = {}
        self.inlets = tuple(
            self._add_connection(f"in_{i}", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._add_connection(f"out_{i}", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
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
        super().pin(
            col=col, row=row, x=x, y=y, orientation=orientation, mirrored=mirrored, port=port
        )
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
            (next(replacement) if on == wanted else name): on for name, on in self._faces.items()
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
        return block_symbol(tuple(self._faces.items()), "" if self.width is not None else self.tag)

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
                raise block_box_too_small(self.name, face, count, axis, drawn, along, turned=turned)
