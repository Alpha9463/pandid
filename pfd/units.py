"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``_PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``).

This module is also the public ``units`` namespace: ``from pfd import units``.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from pfd.geometry import Frame, Pin
from pfd.ports import Port

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet
    from pfd.streams import Stream

__all__ = [
    "Unit",
    "Feed", "Product", "Pump", "Compressor", "Blower", "Valve", "Vessel", "Tank",
    "HeatExchanger", "Heater", "Cooler", "Reactor", "Separator", "Column",
    "Mixer", "Splitter", "Reducer", "Fitting", "Ejector", "Vent", "Funnel",
    "Furnace", "Turbine", "Filter", "Dryer", "Conveyor", "Instrument",
]

# "signal" is the odd one out: every other role names something that flows in a
# pipe, so only a signal port may carry a signal line and only a process one may
# carry fluid. :meth:`pfd.flowsheet.Flowsheet.connect` enforces the pairing.
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
    kind: str = "unit"
    _PORTS: list[tuple[str, str, str]] = []

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
        for spec in self._PORTS:
            self._add_port(*spec)

    @property
    def tag(self) -> str:
        """The tag drawn against this unit.

        One piece of plant carries one tag and is drawn once, so for equipment
        the tag *is* the name the flowsheet knows it by. Only a symbol that
        stands for something drawn in several places has to tell the two apart;
        see :attr:`Instrument.tag`.
        """
        return self.name

    def repeats(self, other: "Unit") -> bool:
        """Whether this unit is *another drawing of* ``other``.

        False here, and so for every piece of equipment: two units answering to
        ``P-101`` are two pumps sharing a tag, which is a mistake in the
        drawing rather than a convention of it.
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
        :class:`~pfd.geometry.Frame`; pinned axes are honored exactly.

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

        from pfd.geometry import normalize_mirror, normalize_orientation

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
            from pfd.portgeom import port_faces

            for port_name, face in self._port_faces.items():
                self._check_face(port_name, face, port_faces(self, port_name, candidate))
        self.pin_ = candidate
        return self

    def nozzle(self, port_name: str, face: str) -> "Unit":
        """Pipe a port from a named face of the unit *as drawn*.

        Many vessels can be piped from more than one side, and the layout engine
        already picks between them from where the peer landed (see
        :mod:`pfd.layout.faces`); this overrides that pick, which is how a
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
        from pfd.portgeom import port_faces

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

        The message comes from :mod:`pfd.portgeom`, which raises the same one at
        resolve time: this check only moves the complaint forward to the call
        that caused it.
        """
        if face not in options:
            from pfd.portgeom import unreachable_face

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


class Feed(Unit):
    """Boundary condition: a stream source entering the flowsheet."""

    kind = "feed"
    _PORTS = [("outlet", "outlet", "feed")]


class Product(Unit):
    """Boundary condition: a stream sink leaving the flowsheet."""

    kind = "product"
    _PORTS = [("inlet", "inlet", "product")]


class Pump(Unit):
    """Centrifugal or positive-displacement pump."""

    kind = "pump"
    _PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Compressor(Unit):
    """Gas compressor."""

    kind = "compressor"
    _PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Valve(Unit):
    """Control or let-down valve.

    ``actuator`` is the signal connection on top of the valve, the terminus of
    a control loop, so a controller's output lands on the final control element
    rather than in mid-air. Being a signal port, it takes a signal ``kind`` and
    refuses process fluid: a pipe into a valve stem is not a connection.
    """

    kind = "valve"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
              ("actuator", "inlet", "signal")]


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
    _PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
    ]


class Tank(Unit):
    """Storage tank. Variants: ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``."""

    kind = "tank"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Blower(Unit):
    """Fan or blower."""

    kind = "blower"
    _PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]


class Reducer(Unit):
    """Concentric pipe reducer/expander."""

    kind = "reducer"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Fitting(Unit):
    """In-line pipe device: whatever sits in the run and is not a valve.

    One class rather than a dozen, because to the flowsheet a strainer, a sight
    glass and a rupture disc are the same thing — a pair of faces on a line —
    and differ only in what is drawn between them. The variant picks the device:
    ``strainer``, ``strainer_cone``, ``orifice``, ``rotameter``,
    ``rupture_disc``, ``sight_glass``, ``sight_glass_lit``, ``silencer``,
    ``expansion_joint``, ``static_mixer``, ``hose``, ``coupling``,
    ``clamped_coupling``, ``flange`` (the default), and the flame arrestors
    (``flame_arrestor`` plus ``_explosion_proof`` / ``_detonation_proof`` /
    ``_fire_resistant``).

    Like a valve, a fitting is inline: a stream keeps its number through it
    unless ``significant`` is set.
    """

    kind = "fitting"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Ejector(Unit):
    """Steam/gas ejector or eductor.

    A motive stream entrains a second one, so this is three connections, not
    two: ``motive`` drives the nozzle, ``suction`` is what gets entrained, and
    ``discharge`` leaves the diffuser.
    """

    kind = "ejector"
    _PORTS = [("motive", "inlet", "utility"), ("suction", "inlet", "process"),
              ("discharge", "outlet", "process")]


class Vent(Unit):
    """Open end to atmosphere (vent stack with a weather cap).

    A boundary like :class:`Product`, but drawn as real piping rather than an
    off-page flag — which is what a PSV tailpipe or a tank breather wants.
    """

    kind = "vent"
    _PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel — a manual addition point feeding the line.

    The mirror of :class:`Vent`: the cone is open to the room and the stem is
    the process connection, so its single port is an *outlet*.
    """

    kind = "funnel"
    _PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater / furnace (process stream heated by burning fuel)."""

    kind = "furnace"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
              ("fuel", "inlet", "feed")]


class Turbine(Unit):
    """Steam/gas turbine or expander."""

    kind = "turbine"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Filter(Unit):
    """Filter (liquid or gas)."""

    kind = "filter"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Dryer(Unit):
    """Dryer (removes moisture from a feed solid/slurry)."""

    kind = "dryer"
    _PORTS = [("feed", "inlet", "feed"), ("product", "outlet", "process")]


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
    _PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]

    _length: float

    def __init__(self, name: str, length: float | None = None,
                 variant: str = "default", width: float | None = None,
                 height: float | None = None, label_pos: str | None = None,
                 description: str = "", reference: str = ""):
        from pfd.render.symbols import CONVEYOR_LENGTH

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
        from pfd.render.symbols import CONVEYOR_MIN_LENGTH, conveyor_too_short

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
    ``"default"`` (field balloon), ``"panel"``, ``"aux"``, ``"shared"`` (DCS),
    ``"computer"``, ``"logic"`` (interlock square).

    A balloon that measures something belongs *on* what it measures: see
    :meth:`attach` (and :meth:`pfd.flowsheet.Flowsheet.add_instrument`).
    """

    kind = "instrument"
    _PORTS = [("pv", "inlet", "signal"), ("sig_in", "inlet", "signal"),
              ("sig_out", "outlet", "signal")]

    #: The one variant that stands for a function rather than a device. A
    #: balloon is a thing — a transmitter in the field, a faceplate in the
    #: control room — and there is one of it. An interlock square is a *logic
    #: function*, which acts in several places at once and is therefore drawn in
    #: each of them, carrying the same tag every time.
    _REPEATABLE_VARIANT = "logic"

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

        Both ends have to be interlock squares carrying the same tag: an
        ``LT-101`` drawn twice is two transmitters on one loop number, and a
        square sharing its tag with a balloon is two different symbols claiming
        to be the same thing.
        """
        return (isinstance(other, Instrument)
                and other.tag == self.tag
                and self.variant == other.variant == self._REPEATABLE_VARIANT)

    def attach(self, on: "Stream | Unit", *, at: float | str | None = None,
               offset: float = 45.0, angle: float = 90.0) -> "Instrument":
        """Anchor this balloon to a process line or to a piece of equipment.

        ``on`` is the host: a :class:`~pfd.streams.Stream` (tap a line) or a
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
        from pfd.streams import Stream

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


class HeatExchanger(Unit):
    """Shell-and-tube or plate heat exchanger (two process sides).

    The ``kettle`` variant carries one nozzle more: ``bottoms``, the liquid draw
    at the weir end of the shell. A kettle reboiler is where a tower's bottoms
    product physically leaves — what does not boil overflows the weir — so the
    draw belongs on the exchanger and not on an invented splitter in the sump
    line.
    """

    kind = "hex"
    _PORTS = [
        ("hot_in", "inlet", "process"),
        ("hot_out", "outlet", "process"),
        ("cold_in", "inlet", "process"),
        ("cold_out", "outlet", "process"),
    ]
    # Nozzles only some variants draw, keyed by the variant that has them: a
    # plate exchanger has no weir to draw off, so giving every hex a `bottoms`
    # would hand most of them a port the symbol cannot place.
    _VARIANT_PORTS = {"kettle": [("bottoms", "outlet", "liquid")]}

    def __init__(self, name: str, variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "",
                 reference: str = ""):
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description,
                         reference=reference)
        for spec in self._VARIANT_PORTS.get(variant, []):
            self._add_port(*spec)


class Heater(Unit):
    """Single-stream heater (utility heating)."""

    kind = "heater"
    _PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("duty", "inlet", "energy"),
    ]


class Cooler(Unit):
    """Single-stream cooler (utility cooling)."""

    kind = "cooler"
    _PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("duty", "outlet", "energy"),
    ]


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Names for a unit's feed nozzles: ``feed`` alone, else ``feed_1`` ... ``feed_n``.

    One feed is the overwhelmingly common case and keeps the singular name, so a
    second one is what changes the spelling rather than every sheet ever drawn.
    The symbol declares the same rule as a
    :class:`~pfd.render.symbols.PortSeries`, which is what spreads the family
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
    _PORTS = [
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
    _PORTS = [
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
    _PORTS = [
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
