"""Geometry primitives for PFD elements.

These structures represent the purely visual/spatial data of a flowsheet:
coordinates, bounding boxes, and routing lines. They are derived from the topology
or manually specified as overrides, but never form the core semantic model itself.
"""

from dataclasses import dataclass, field


@dataclass
class Placement:
    """Represents the position and orientation of a Unit."""
    x: float | None = None
    y: float | None = None
    width: float = 50.0
    height: float = 50.0
    orientation: float = 0.0
    col: int | None = None
    row: int | None = None


@dataclass
class Route:
    """Represents the orthogonal path of a Stream."""
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    lane: int | None = None
    manual: bool = False
