"""Unit operations and the built-in unit-type library.

Each Unit subclass declares its named ports via the class attribute ``_PORTS``
(a list of ``(name, direction, role)`` tuples), or, for variable-port units,
by adding ports in ``__init__``. Ports are exposed both as a ``ports`` dict and as
attributes (e.g. ``pump.suction``).

This module is also the public ``units`` namespace: ``from pfd import units``.
"""

from __future__ import annotations

from pfd.geometry import Frame, Pin
from pfd.ports import Port

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

    def __init__(self, name: str, variant: str = "default", width: float | None = None, height: float | None = None, label_pos: str | None = None):
        if not name:
            raise ValueError("Unit name cannot be empty")
        self.name = name
        self.variant = variant
        self.width = width
        self.height = height
        self.label_pos = label_pos
        self.flowsheet = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        # For inline fittings (valve/reducer): if True, the stream number breaks
        # across this unit instead of carrying through it. See Flowsheet naming.
        self.significant = False
        self.pin_: Pin | None = None      # user intent (set only via pin())
        self.frame: Frame | None = None   # resolved geometry (set only by layout)
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
        mirrored: bool = False,
    ) -> "Unit":
        """Pin the unit to a specific layout grid cell or exact pixel coordinate.

        Records *intent* only. The layout engine reads it and resolves the final
        :class:`~pfd.geometry.Frame`; pinned axes are honored exactly.
        """
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
        self.pin_.orientation = orientation
        self.pin_.mirrored = mirrored
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
    """Control or let-down valve."""

    kind = "valve"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Vessel(Unit):
    """Generic pressure vessel or storage tank."""

    kind = "vessel"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


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


class Instrument(Unit):
    """ISA-5.1 instrument balloon. The ``name`` is the tag (e.g. ``"FIC-101"``),
    drawn inside the balloon. ``pv`` taps the process; ``in``/``out`` carry
    signals. Variants: ``"field"`` (default), ``"panel"``, ``"aux"``,
    ``"shared"`` (DCS), ``"computer"``.
    """

    kind = "instrument"
    _PORTS = [("pv", "inlet", "process"), ("sig_in", "inlet", "process"),
              ("sig_out", "outlet", "process")]


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
    """Generic reactor (CSTR, PFR, etc.)."""

    kind = "reactor"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("outlet", "outlet", "process"),
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
    """Distillation or absorption column."""

    kind = "column"
    _PORTS = [
        ("feed", "inlet", "feed"),
        ("distillate", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]


# ---------------------------------------------------------------------------
# Variable-port unit types
# ---------------------------------------------------------------------------


class Mixer(Unit):
    """Combines multiple inlet streams into one outlet."""

    kind = "mixer"

    def __init__(self, name: str, n_inlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, width=width, height=height)
        for i in range(1, n_inlets + 1):
            self._add_port(f"in_{i}", "inlet", "process")
        self._add_port("outlet", "outlet", "process")


class Splitter(Unit):
    """Divides one inlet stream into multiple outlets."""

    kind = "splitter"

    def __init__(self, name: str, n_outlets: int = 2, variant: str = "default", width: float | None = None, height: float | None = None):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, width=width, height=height)
        self._add_port("inlet", "inlet", "process")
        for i in range(1, n_outlets + 1):
            self._add_port(f"out_{i}", "outlet", "process")
