"""Define placement intent, resolved geometry and routes.

- :class:`Pin` is the author's placement intent, set only through
  :meth:`pandid.units.Unit.pin` and never written by the engine.
- :class:`Frame` is the resolved box the layout engine writes and the
  router and renderer read. It is recomputed from the pin on every
  layout, so layout is idempotent.
- :class:`Route` is a stream's resolved path.
"""

from dataclasses import dataclass, field

# Other angles would tilt text and break orthogonal routing.
_QUARTER_TURNS = (0, 90, 180, 270)


def normalize_orientation(value) -> int:
    """Validate an orientation as a clockwise quarter turn.

    Parameters
    ----------
    value : object
        Angle in degrees.

    Returns
    -------
    int
        ``0``, ``90``, ``180`` or ``270``.

    Raises
    ------
    ValueError
        If the value is not a number or not a multiple of 90 degrees.
    """
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
    """Resolve a mirror setting to ``(mirror_x, mirror_y)``.

    ``mirror_x`` flips left to right (swapping the E and W faces);
    ``mirror_y`` flips top to bottom (swapping N and S).

    Parameters
    ----------
    value : bool, str or None
        ``True`` for a left-right flip, or ``"x"``/``"h"``/``"horizontal"``,
        ``"y"``/``"v"``/``"vertical"``, ``"xy"``/``"both"``; ``None``,
        ``False``, ``""`` and ``"none"`` mean no flip.

    Returns
    -------
    tuple[bool, bool]
        Left-right and top-bottom flips.

    Raises
    ------
    ValueError
        If the string is not recognised.
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


@dataclass(frozen=True)
class Pin:
    """Placement intent for a unit.

    Any subset of fields may be set. Grid and pixel intent may be mixed; a
    pixel coordinate wins on its axis. The object is frozen because
    :attr:`pandid.units.Unit.pin_` returns a derived value; change a
    placement with :meth:`pandid.units.Unit.pin`.

    Attributes
    ----------
    col, row : int or None
        Grid column and row.
    x, y : float or None
        Top-left corner in pixels.
    orientation : float
        Clockwise quarter turn in degrees.
    mirrored : bool
        Left-right flip.
    mirror_y : bool
        Top-bottom flip.
    """
    col: int | None = None
    row: int | None = None
    x: float | None = None
    y: float | None = None
    orientation: float = 0.0
    mirrored: bool = False
    mirror_y: bool = False


@dataclass
class Frame:
    """Resolved geometry of a unit, written by the layout engine.

    Callers read it and do not mutate it.

    Attributes
    ----------
    x, y : float
        Top-left corner in pixels.
    w, h : float
        Resolved size.
    col, row : int or None
        Grid rank the solver assigned, if any.
    orientation : float
        Clockwise quarter turn in degrees.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.
    label_pos : str or None
        Tag position: ``"top"``, ``"bottom"``, ``"left"``, ``"right"`` or
        ``"center"``.
    port_faces : dict[str, str]
        Faces automatic selection chose for movable ports. Kept on the
        frame, not the unit, so each layout starts from author intent.
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
    label_pos: str | None = None
    port_faces: dict[str, str] = field(default_factory=dict)

    @property
    def x_max(self) -> float:
        """Return the right edge in pixels."""
        return self.x + self.w

    @property
    def y_max(self) -> float:
        """Return the bottom edge in pixels."""
        return self.y + self.h

    @property
    def cx(self) -> float:
        """Return the horizontal centre in pixels."""
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        """Return the vertical centre in pixels."""
        return self.y + self.h / 2


@dataclass
class _Slot:
    """Mutable solver state for one unit during layout.

    Seeded from the unit's :class:`Pin`; layout passes fill in the missing
    fields, then write a :class:`Frame`. Not public API.

    Attributes
    ----------
    w, h : float
        Resolved size.
    col, row : int or None
        Grid rank.
    x, y : float or None
        Top-left corner in pixels.
    orientation : float
        Clockwise quarter turn in degrees.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.
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
    """A stream's resolved path in absolute drawing coordinates.

    Attributes
    ----------
    waypoints : list[tuple[float, float]]
        Ordered path points in pixels.
    manual : bool
        Whether the author supplied the path through ``via()``.
    used_fallback : bool
        Whether automatic search failed and the router used its fallback.
    """
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    manual: bool = False
    used_fallback: bool = False
