"""Flowsheet — the top-level container and the single source of truth for
connectivity. Units are added with ``add()``; streams are created only through
``connect()``, which validates the connection and enforces the one-stream-per-port
rule.
"""

from __future__ import annotations
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from pfd.streams import Stream

if TYPE_CHECKING:
    from pfd.components import Component
    from pfd.ports import Port
    from pfd.units import Unit

_ENERGY_ROLES = {"energy", "utility"}


class Flowsheet:
    """A process flow diagram's topology: units, streams, and components."""

    def __init__(self, name: str, direction: str = "LR", stream_naming_scheme: str | Callable[[int], str] = "S{n}"):
        self.name = name
        self.direction = direction
        self.stream_naming_scheme = stream_naming_scheme
        self.units: list = []
        self.streams: list[Stream] = []
        self.components: list = []

    def add(self, unit: "Unit") -> "Unit":
        """Register a unit on this flowsheet. Returns the unit for chaining."""
        if unit in self.units:
            raise ValueError(
                f"{unit!r} is already on this flowsheet"
            )
        if any(u.name == unit.name for u in self.units):
            raise ValueError(
                f"A unit with the name {unit.name!r} already exists on this flowsheet."
            )
        if unit.flowsheet is not None:
            raise ValueError(
                f"{unit!r} is already on flowsheet {unit.flowsheet.name!r}"
            )
        unit.flowsheet = self
        self.units.append(unit)
        return unit

    def add_component(self, component: "Component") -> "Component":
        """Register a chemical component. Returns the component for chaining."""
        self.components.append(component)
        return component

    def connect(self, src: "Port", dst: "Port", *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False) -> Stream:
        """Create a stream connecting *src* (outlet port) to *dst* (inlet port).

        Raises :class:`ValueError` if any validation rule is violated.
        """
        if kind not in {"material", "energy"}:
            raise ValueError(f"Stream kind must be 'material' or 'energy', got {kind!r}")
            
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

        if not name:
            if callable(self.stream_naming_scheme):
                name = self.stream_naming_scheme(len(self.streams) + 1)
            else:
                name = self.stream_naming_scheme.format(n=len(self.streams) + 1)

        stream = Stream(
            name=name,
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
                    "source": [s.source.owner.name if s.source.owner else "", s.source.name],
                    "dest": [s.dest.owner.name if s.dest.owner else "", s.dest.name],
                    "kind": s.kind,
                    "is_recycle": s.is_recycle,
                }
                for s in self.streams
            ],
        }

    def layout(self, engine=None) -> None:
        """Run the automatic layout engine to generate unit coordinates."""
        if engine is None:
            from pfd.layout import default_layout_engine
            engine = default_layout_engine
        engine.layout(self)

    def route(self, router=None) -> None:
        """Run the automatic routing engine to generate orthogonal stream paths.

        Runs :meth:`layout` first if any unit still lacks a resolved frame, since
        routing needs geometry to work against.
        """
        if any(u.frame is None for u in self.units):
            self.layout()
        if router is None:
            from pfd.routing import DefaultRouter
            router = DefaultRouter()
        router.route(self)

    def to_svg(self, *, show_stream_table: bool = False,
               styling: str = "default", page_size: str = "A3") -> str:
        """Render the flowsheet to an SVG string, running ``layout()`` and
        ``route()`` first if they have not been run yet.
        """
        if any(u.frame is None for u in self.units):
            self.layout()
        if any(s.route is None for s in self.streams):
            self.route()
        from pfd.render.svg import SvgRenderer
        return SvgRenderer().render(
            self, show_stream_table=show_stream_table, styling=styling, page_size=page_size
        )

    def render(self, path: str | Path, *, show_stream_table: bool = False,
               styling: str = "default", page_size: str = "A3") -> None:
        """Render the flowsheet and write it to *path*.

        The output format is inferred from the file extension:

        - ``.svg`` — pure-Python, always available.
        - ``.pdf`` / ``.png`` — require the optional ``cairosvg`` backend
          (``pip install 'pfd[pdf]'``).

        Args:
            path: Output file path; its extension selects the format.
            show_stream_table: Draw a property table of all streams at the bottom.
            styling: ``"default"`` or ``"pid"`` (adds a title block and border).
            page_size: Sheet size, e.g. ``"A3"`` (default) or ``"A4"``.
        """
        svg = self.to_svg(
            show_stream_table=show_stream_table, styling=styling, page_size=page_size
        )
        ext = Path(path).suffix.lower()
        if ext in ("", ".svg"):
            Path(path).write_text(svg, encoding="utf-8")
        elif ext in (".pdf", ".png"):
            try:
                import cairosvg
            except ImportError as e:
                raise ImportError(
                    f"Exporting {ext} requires the optional cairosvg backend. "
                    "Install it with: pip install 'pfd[pdf]'"
                ) from e
            data = svg.encode("utf-8")
            if ext == ".pdf":
                cairosvg.svg2pdf(bytestring=data, write_to=str(path))
            else:
                cairosvg.svg2png(bytestring=data, write_to=str(path))
        else:
            raise ValueError(
                f"Unsupported output format {ext!r}; use .svg, .pdf, or .png"
            )

    def _repr_svg_(self) -> str:
        """IPython/Jupyter integration: display the diagram inline in notebooks."""
        return self.to_svg()

    def show(self) -> None:
        """Render the flowsheet and open it in the default web browser."""
        import tempfile
        import webbrowser
        import os
        
        fd, temp_path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        
        self.render(temp_path)
        webbrowser.open(f"file://{temp_path}")

    def __repr__(self) -> str:
        return (
            f"Flowsheet({self.name!r}, "
            f"units={len(self.units)}, streams={len(self.streams)})"
        )
