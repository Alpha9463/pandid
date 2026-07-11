"""Geometry primitives for PFD elements.

The model separates two distinct things that used to be conflated:

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


@dataclass
class Pin:
    """User-specified placement *intent* for a Unit.

    Any subset of fields may be given. Grid intent (``col``/``row``) and absolute
    intent (``x``/``y``) may be mixed; absolute wins for whichever axis it sets.
    """
    col: int | None = None
    row: int | None = None
    x: float | None = None
    y: float | None = None
    orientation: float = 0.0
    mirrored: bool = False

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


@dataclass
class Route:
    """Resolved orthogonal path of a Stream (absolute pixel waypoints)."""
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    lane: int | None = None
    manual: bool = False
