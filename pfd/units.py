"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``_PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``).

This module is also the public ``units`` namespace: ``from pfd import units``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pfd.geometry import Frame, Pin
from pfd.ports import Port

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet
    from pfd.streams import Stream

__all__ = [
    "Unit",
    "Feed", "Product", "Pump", "Compressor", "Blower", "Valve", "Vessel", "Tank",
    "HeatExchanger", "Heater", "Cooler", "Reactor", "Separator", "Column",
    "Mixer", "Splitter", "Reducer", "Furnace", "Turbine", "Filter", "Dryer",
    "Instrument",
]

_VALID_ROLES = {"process", "feed", "product", "energy", "utility", "vapor", "liquid"}

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
        # stream comes from / goes to, drawn as the connector's second line.
        self.reference = reference
        self.flowsheet: Flowsheet | None = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        # For inline fittings (valve/reducer): if True, the stream number breaks
        # across this unit instead of carrying through it. See Flowsheet naming.
        self.significant = False
        self.pin_: Pin | None = None      # user intent (set only via pin())
        self.frame: Frame | None = None   # resolved geometry (set only by layout)
        self._port_faces: dict[str, str] = {}   # port name -> chosen face
        for spec in self._PORTS:
            self._add_port(*spec)

    def pin(
        self,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = 0.0,
        mirrored: bool | str = False,
    ) -> "Unit":
        """Pin the unit to a specific layout grid cell or exact pixel coordinate.

        Records *intent* only. The layout engine reads it and resolves the final
        :class:`~pfd.geometry.Frame`; pinned axes are honored exactly.

        ``orientation`` is a clockwise quarter turn in degrees (0/90/180/270); a
        quarter turn swaps the unit's width and height. ``mirrored`` flips the
        symbol: ``True`` or ``"x"`` left↔right (swapping its E and W faces),
        ``"y"`` top↔bottom (swapping N and S), ``"xy"`` both.
        """
        from pfd.geometry import normalize_mirror, normalize_orientation

        if self.pin_ is None:
            self.pin_ = Pin()
        if col is not None:
            self.pin_.col = col
        if row is not None:
            self.pin_.row = row
        if x is not None:
            self.pin_.x = x
        if y is not None:
            self.pin_.y = y
        self.pin_.orientation = normalize_orientation(orientation)
        self.pin_.mirrored, self.pin_.mirror_y = normalize_mirror(mirrored)
        return self

    def port_face(self, port_name: str, face: str) -> "Unit":
        """Move a port to a different face of the symbol.

        Many vessels can be piped from more than one side; where a symbol
        declares alternates for a port, this picks one. ``face`` is ``"N"``,
        ``"S"``, ``"E"`` or ``"W"`` *in the symbol's own frame* — mirroring and
        rotation are applied on top, so the drawn face follows the placement.

        Raises :class:`KeyError` for an unknown port and :class:`ValueError` when
        the symbol offers no alternate on that face (a column's bottoms nozzle,
        for instance, is fixed by physics and has none).
        """
        from pfd.portgeom import _sym

        if port_name not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        face = face.upper()
        alts = (getattr(_sym(self), "port_alts", None) or {}).get(port_name) or {}
        if face not in alts:
            raise ValueError(
                f"port {self.name}.{port_name} cannot move to face {face!r}; "
                f"available: {sorted(alts) or 'none — this nozzle is fixed'}"
            )
        self._port_faces[port_name] = face
        return self

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

    ``actuator`` is the signal connection on top of the valve — the terminus of
    a control loop, so a controller's output lands on the final control element
    rather than in mid-air.
    """

    kind = "valve"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process"),
              ("actuator", "inlet", "process")]


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
    """Storage tank (cone/dished bottom). Variants: ``"default"``, ``"dished"``."""

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

    ``pv`` taps the process; ``sig_in``/``sig_out`` carry signals. Variants:
    ``"field"`` (default), ``"panel"``, ``"aux"``, ``"shared"`` (DCS),
    ``"computer"``, ``"logic"`` (interlock square).

    A balloon that measures something belongs *on* what it measures: see
    :meth:`attach` (and :meth:`pfd.flowsheet.Flowsheet.add_instrument`).
    """

    kind = "instrument"
    _PORTS = [("pv", "inlet", "process"), ("sig_in", "inlet", "process"),
              ("sig_out", "outlet", "process")]

    def __init__(self, type: str, number: str | int = "", variant: str = "default",
                 width: float | None = None, height: float | None = None,
                 label_pos: str | None = None, description: str = "", reference: str = ""):
        letters, num = split_tag(type, number)
        name = f"{type}-{number}" if number != "" and number is not None else type
        super().__init__(name, variant=variant, width=width, height=height,
                         label_pos=label_pos, description=description, reference=reference)
        self.type = letters
        self.number = num
        # Attachment intent (set only via attach()); the layout engine resolves
        # it into a frame, exactly as Pin -> Frame for ordinary equipment.
        self.host: "Stream | Unit | None" = None
        self.at: float | str | None = None
        self.offset: float = 45.0
        self.angle: float = 90.0
        self.tap: tuple[float, float] | None = None   # resolved (set only by layout)

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
    """Shell-and-tube or plate heat exchanger (two process sides)."""

    kind = "hex"
    _PORTS = [
        ("hot_in", "inlet", "process"),
        ("hot_out", "outlet", "process"),
        ("cold_in", "inlet", "process"),
        ("cold_out", "outlet", "process"),
    ]


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


class Reactor(Unit):
    """Generic reactor (CSTR, PFR, etc.).

    ``vent`` is the off-gas connection at the top of the vessel.
    """

    kind = "reactor"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("duty", "inlet", "energy"),
    ]


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
    """

    kind = "column"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reflux_in", "inlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]


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
