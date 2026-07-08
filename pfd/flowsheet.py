"""Flowsheet — the top-level container and the single source of truth for
connectivity. Units are added with ``add()``; streams are created only through
``connect()``, which validates the connection and enforces the one-stream-per-port
rule.
"""

from __future__ import annotations

from pfd.streams import Stream

_ENERGY_ROLES = {"energy", "utility"}


class Flowsheet:
    """A process flow diagram's topology: units, streams, and components."""

    def __init__(self, name: str, direction: str = "LR"):
        self.name = name
        self.direction = direction
        self.units: list = []
        self.streams: list[Stream] = []
        self.components: list = []

    def add(self, unit):
        """Register a unit on this flowsheet. Returns the unit for chaining."""
        if unit in self.units:
            raise ValueError(
                f"{unit!r} is already on this flowsheet"
            )
        if unit.flowsheet is not None:
            raise ValueError(
                f"{unit!r} is already on flowsheet {unit.flowsheet.name!r}"
            )
        unit.flowsheet = self
        self.units.append(unit)
        return unit

    def add_component(self, component):
        """Register a chemical component. Returns the component for chaining."""
        self.components.append(component)
        return component

    def connect(self, src, dst, *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False) -> Stream:
        """Create a stream connecting *src* (outlet port) to *dst* (inlet port).

        Raises :class:`ValueError` if any validation rule is violated.
        """
        if src.direction != "outlet":
            raise ValueError(
                f"source port {src.owner.name}.{src.name} must be an outlet, "
                f"got {src.direction!r}"
            )
        if dst.direction != "inlet":
            raise ValueError(
                f"destination port {dst.owner.name}.{dst.name} must be an inlet, "
                f"got {dst.direction!r}"
            )
        if src.owner.flowsheet is not self or dst.owner.flowsheet is not self:
            raise ValueError(
                "both units must be added to this flowsheet before connecting"
            )
        if src.stream is not None:
            raise ValueError(
                f"port {src.owner.name}.{src.name} is already connected"
            )
        if dst.stream is not None:
            raise ValueError(
                f"port {dst.owner.name}.{dst.name} is already connected"
            )
        if kind == "material" and src.role in _ENERGY_ROLES and dst.role in _ENERGY_ROLES:
            kind = "energy"

        stream = Stream(
            name=name or f"S{len(self.streams) + 1}",
            source=src,
            dest=dst,
            kind=kind,
            tear_hint=tear_hint,
        )
        src.stream = stream
        dst.stream = stream
        self.streams.append(stream)
        return stream

    def to_dict(self) -> dict:
        """Serialize the flowsheet topology to a plain ``dict``.

        The returned structure is JSON-safe and suitable for passing to the
        (future) geometry and render layers, or for displaying a pre-calculated
        stream table in a PFD viewer.
        """
        return {
            "name": self.name,
            "direction": self.direction,
            "components": [c.name for c in self.components],
            "units": [
                {
                    "name": u.name,
                    "kind": u.kind,
                    "ports": [
                        {"name": p.name, "direction": p.direction, "role": p.role}
                        for p in u.ports.values()
                    ],
                }
                for u in self.units
            ],
            "streams": [
                {
                    "name": s.name,
                    "source": [s.source.owner.name, s.source.name],
                    "dest": [s.dest.owner.name, s.dest.name],
                    "kind": s.kind,
                    "is_recycle": s.is_recycle,
                }
                for s in self.streams
            ],
        }

    def render(self, path: str, *, backend: str = "svg", **opts) -> None:
        """Render the flowsheet geometry to a file.
        
        Currently, only the 'svg' backend is supported.
        """
        if backend == "svg":
            from pfd.render.svg import SvgRenderer
            renderer = SvgRenderer()
        else:
            raise NotImplementedError(f"Backend '{backend}' not supported.")
        renderer.render(self, path, **opts)

    def __repr__(self) -> str:
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
