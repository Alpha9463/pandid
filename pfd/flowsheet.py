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
    from pfd.document import TitleBlock
    from pfd.ports import Port
    from pfd.units import Instrument, Unit

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
        self.warnings: list = []  # soft validation findings from the last render
        self.title_block: "TitleBlock | None" = None  # for pid styling
        # Generic titled boxes (equipment list, notes, legend, tables) docked to
        # the sheet corners; drawn under pid styling. See pfd.document.
        self.annotations: list = []
        # Section headers to inject into the stream table: (before_key, label).
        self.stream_table_sections: list[tuple[str, str]] = []

    def add_annotation(self, annotation):
        """Register a sheet-furniture box (Annotation / TableBox). Chainable."""
        self.annotations.append(annotation)
        return annotation

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

    def add_instrument(self, type: str, number: str | int = "", *,
                       on: "Stream | Unit | None" = None, at: float | str | None = None,
                       offset: float = 45.0, angle: float = 90.0,
                       variant: str = "default", **kwargs) -> "Instrument":
        """Add an ISA-5.1 instrument balloon, optionally anchored to its host.

        ``type`` is the functional letter string and ``number`` the loop number;
        together they make the tag (``add_instrument("FT", 101)`` -> ``FT-101``).
        ``on``/``at``/``offset``/``angle`` are passed straight to
        :meth:`~pfd.units.Instrument.attach`; without ``on`` the balloon is laid
        out like any other unit.

        >>> s = fs.connect(feed.outlet, fv.inlet)
        >>> fs.add_instrument("FE", 101, on=s, at=0.4, offset=0)     # in-line element
        >>> fs.add_instrument("FT", 101, on=s, at=0.4, offset=60)    # transmitter above
        """
        from pfd.units import Instrument

        inst = Instrument(type, number, variant=variant, **kwargs)
        self.add(inst)
        if on is not None:
            inst.attach(on, at=at, offset=offset, angle=angle)
        return inst

    def add_component(self, component: "Component") -> "Component":
        """Register a chemical component. Returns the component for chaining."""
        self.components.append(component)
        return component

    def connect(self, src: "Port", dst: "Port", *, kind: str = "material",
                name: str | None = None, tear_hint: bool = False) -> Stream:
        """Create a stream connecting *src* (outlet port) to *dst* (inlet port).

        Raises :class:`ValueError` if any validation rule is violated.
        """
        _KINDS = {"material", "energy", "electric", "pneumatic", "data", "capillary", "software"}
        if kind not in _KINDS:
            raise ValueError(f"Stream kind must be one of {sorted(_KINDS)}, got {kind!r}")
            
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

        explicit = bool(name)
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
            auto_named=not explicit,
        )
        src.stream = stream
        dst.stream = stream
        self.streams.append(stream)
        return stream

    @classmethod
    def from_dict(cls, spec: dict) -> "Flowsheet":
        """Build a flowsheet from a declarative spec ``dict``.

        See :mod:`pfd.spec` for the format. Raises :class:`pfd.spec.SpecError`
        (a :class:`ValueError`) naming the offending entry.
        """
        from pfd.spec import from_dict as _from_dict
        return _from_dict(spec)

    @classmethod
    def from_json(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a JSON spec file. See :mod:`pfd.spec`."""
        from pfd.spec import from_json as _from_json
        return _from_json(path)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Flowsheet":
        """Build a flowsheet from a YAML spec file (needs the ``yaml`` extra).

        See :mod:`pfd.spec`.
        """
        from pfd.spec import from_yaml as _from_yaml
        return _from_yaml(path)

    def to_dict(self) -> dict:
        """Serialize the flowsheet to a JSON-safe declarative spec ``dict``.

        Round-trips: ``Flowsheet.from_dict(fs.to_dict())`` rebuilds an
        equivalent flowsheet. See :mod:`pfd.spec` for the format.
        """
        from pfd.spec import to_dict as _to_dict
        return _to_dict(self)

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
        # An attached balloon hangs off its host's *routed* path, so where it
        # finally lands is only known once that path exists. Layout placed it on
        # the straight port-to-port line, which is already right for a straight
        # run; when the router bent the line, re-place it and re-route the
        # signal lines that now leave from somewhere else.
        from pfd.layout.attach import place_attached
        if place_attached(self):
            router.route(self)
            place_attached(self)

    def renumber_streams(self) -> None:
        """Assign stream numbers, carrying one number through inline fittings.

        Valves, reducers and fittings are inline: a stream keeps its number as
        it passes through them (set ``unit.significant = True`` to break the
        number at an important valve). Only auto-named material streams are
        renumbered; explicitly-named streams and signal lines are left untouched.
        """
        _INLINE = {"valve", "reducer", "fitting"}
        material = [s for s in self.streams if s.kind == "material"]
        pos = {id(s): i for i, s in enumerate(material)}  # Stream is unhashable
        parent = list(range(len(material)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for u in self.units:
            if u.kind in _INLINE and not getattr(u, "significant", False):
                ins = [pos[id(p.stream)] for p in u.ports.values()
                       if p.direction == "inlet" and p.stream is not None and id(p.stream) in pos]
                outs = [pos[id(p.stream)] for p in u.ports.values()
                        if p.direction == "outlet" and p.stream is not None and id(p.stream) in pos]
                if len(ins) == 1 and len(outs) == 1:
                    parent[find(ins[0])] = find(outs[0])

        # An explicit name on any segment names its whole group.
        explicit: dict = {}
        for i, s in enumerate(material):
            if not s.auto_named:
                explicit.setdefault(find(i), s.name)

        group_name: dict = {}
        n = 0
        for i in range(len(material)):  # first-appearance order
            r = find(i)
            if r in group_name:
                continue
            if r in explicit:
                group_name[r] = explicit[r]
            else:
                n += 1
                group_name[r] = (self.stream_naming_scheme(n)
                                 if callable(self.stream_naming_scheme)
                                 else self.stream_naming_scheme.format(n=n))

        for i, s in enumerate(material):
            if s.auto_named:
                s.name = group_name[find(i)]

    def validate(self) -> list:
        """Return validation issues for the flowsheet (errors first, then warnings).

        See :mod:`pfd.validate`. Errors are contradictions the engine cannot
        honor (overlapping pins, off-sheet coords); warnings are imperfections
        (a route crossing a unit body, a large detour).
        """
        from pfd.validate import validate as _validate
        return _validate(self)

    def to_svg(self, *, show_stream_table: bool = False,
               styling: str = "default", page_size: str = "A3",
               check: bool = True) -> str:
        """Render the flowsheet to an SVG string, running ``layout()`` and
        ``route()`` first if they have not been run yet.

        When ``check`` is true, validation runs first: any *error* raises
        :class:`ValueError`, and *warnings* are collected on ``self.warnings``.
        """
        if any(u.frame is None for u in self.units):
            self.layout()
        if any(s.route is None for s in self.streams):
            self.route()
        self.renumber_streams()
        if check:
            issues = self.validate()
            self.warnings = [i for i in issues if i.severity == "warning"]
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                raise ValueError(
                    "Flowsheet validation failed:\n"
                    + "\n".join(f"  {e}" for e in errors)
                )
        from pfd.render.svg import SvgRenderer
        return SvgRenderer().render(
            self, show_stream_table=show_stream_table, styling=styling, page_size=page_size
        )

    def render(self, path: str | Path, *, show_stream_table: bool = False,
               styling: str = "default", page_size: str = "A3",
               check: bool = True) -> None:
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
            check: Validate first; errors raise, warnings collect on ``warnings``.
        """
        svg = self.to_svg(
            show_stream_table=show_stream_table, styling=styling, page_size=page_size,
            check=check,
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
