"""Geometry primitives for PFD elements.

The model keeps two distinct things apart:

- :class:`Pin` — the user's *intent*: "put this unit at column 2" or "pin it to
  exactly (x, y)". Set only through :meth:`pfd.units.Unit.pin`. Never written by
  the engine.
- :class:`Frame` — the *result*: the resolved pixel box (and grid rank) the
  layout engine computes. Written only by the layout engine, read by the router
  and renderer. Recomputed from the :class:`Pin` on every layout run, so layout
  is idempotent.

:class:`Route` is the resolved orthogonal path of a stream.
"""

from dataclasses import dataclass, field

# Quarter turns are the only rotations a P&ID sheet uses: anything else would
# tilt the text and break the orthogonal routing grid.
_QUARTER_TURNS = (0, 90, 180, 270)


def normalize_orientation(value) -> int:
    """Snap an orientation to a quarter turn, clockwise, in degrees."""
    try:
        deg = int(round(float(value))) % 360
    except (TypeError, ValueError):
        raise ValueError(f"orientation must be a number of degrees, got {value!r}") from None
    if deg not in _QUARTER_TURNS:
        raise ValueError(
            f"orientation must be one of {_QUARTER_TURNS} degrees, got {value!r}"
        )
    return deg


def normalize_mirror(value) -> tuple[bool, bool]:
    """Resolve a mirror spec to ``(mirror_x, mirror_y)``.

    ``mirror_x`` flips left↔right (swapping the E and W faces), ``mirror_y``
    flips top↔bottom (swapping N and S). Accepts ``True`` (shorthand for the
    left↔right flip), or one of ``"x"``/``"horizontal"``, ``"y"``/``"vertical"``,
    ``"xy"``/``"both"``.
    """
    if value is None or value is False:
        return (False, False)
    if value is True:
        return (True, False)
    key = str(value).strip().lower()
    table = {
        "x": (True, False), "h": (True, False), "horizontal": (True, False),
        "y": (False, True), "v": (False, True), "vertical": (False, True),
        "xy": (True, True), "both": (True, True),
        "": (False, False), "none": (False, False),
    }
    if key not in table:
        raise ValueError(
            f"mirrored must be a bool or one of {sorted(k for k in table if k)}, got {value!r}"
        )
    return table[key]


@dataclass
class Pin:
    """User-specified placement *intent* for a Unit.

    Any subset of fields may be given. Grid intent (``col``/``row``) and absolute
    intent (``x``/``y``) may be mixed; absolute wins for whichever axis it sets.

    ``orientation`` is a clockwise quarter turn in degrees; ``mirrored`` /
    ``mirror_y`` flip the symbol left↔right and top↔bottom respectively.
    """
    col: int | None = None
    row: int | None = None
    x: float | None = None
    y: float | None = None
    orientation: float = 0.0
    mirrored: bool = False
    mirror_y: bool = False

    @property
    def is_fixed_xy(self) -> bool:
        """True when both x and y are pinned to absolute coordinates."""
        return self.x is not None and self.y is not None

    @property
    def has_grid(self) -> bool:
        """True when a grid column or row was requested."""
        return self.col is not None or self.row is not None


@dataclass
class Frame:
    """Resolved geometry of a Unit, produced by the layout engine.

    Read-only by convention: callers (router, renderer) consume it but never
    mutate it. ``x``/``y`` are the top-left pixel corner; ``w``/``h`` the
    resolved size; ``col``/``row`` the grid rank the solver assigned.
    """
    x: float
    y: float
    w: float
    h: float
    col: int | None = None
    row: int | None = None
    orientation: float = 0.0
    mirrored: bool = False
    mirror_y: bool = False
    label_pos: str | None = None  # resolved label side: top/bottom/left/right
    # Faces the engine picked for movable ports (see pfd.layout.faces), keyed by
    # port name. A *result*, so it belongs here and not on the unit: the unit
    # carries only what the author asked for, and a layout run that started from
    # a previous run's pick would not be idempotent.
    port_faces: dict[str, str] = field(default_factory=dict)

    @property
    def x_max(self) -> float:
        return self.x + self.w

    @property
    def y_max(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class _Slot:
    """Internal, mutable solver scratch state for one unit.

    The layout engine seeds this from the unit's :class:`Pin` and fills in the
    missing ``col``/``row``/``x``/``y`` across its phases, then emits a concrete
    :class:`Frame`. Not part of the public API.
    """
    w: float
    h: float
    col: int | None = None
    row: int | None = None
    x: float | None = None
    y: float | None = None
    orientation: float = 0.0
    mirrored: bool = False
    mirror_y: bool = False


@dataclass
class Route:
    """Resolved orthogonal path of a Stream (absolute pixel waypoints)."""
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    lane: int | None = None
    manual: bool = False
