"""SVG symbol registry for the topology primitives.

Symbols follow ISO 10628-2 / ISA 5.1 conventions and come from two sources:

- **Vendored (draw.io / diagrams.net P&ID stencils, Apache-2.0)** — valves and
  their variants, pumps, compressors, blowers, heat exchangers, vessels,
  columns, reactors, separators, tanks, reducers, in-line fittings, ejectors,
  vents and funnels. Converted from mxGraph
  stencil XML by ``scripts/vendor_symbols.py`` into ``_vendored_symbols.py`` and
  registered last (overriding the hand-drawn defaults of the same kind). See the
  repo ``NOTICE`` for attribution.
- **Hand-drawn primitives** — Feed/Product boundary markers and the
  variable-port Mixer and Splitter.

Authoring conventions (hand-drawn symbols)
------------------------------------------
- Local coordinates: (0, 0) top-left, spanning ``width`` × ``height``.
- Ports: named anchors on the boundary face a stream attaches to; names MUST
  match the owning :class:`~pfd.units.Unit`'s port names.
- Variants share a ``kind`` and register under a ``variant`` name.
"""

import math
import re
import warnings
from dataclasses import InitVar, dataclass, field

from pfd.portgeom import outward_dir

# Two placements closer together than this are the same point as far as a reader
# (and a stream endpoint) is concerned.
_COINCIDENT = 0.5


@dataclass(frozen=True)
class PortSeries:
    """A family of like ports spread evenly along one face of a symbol.

    A :class:`~pfd.units.Mixer` does not have a fixed set of inlets — the unit
    decides how many there are — so the symbol cannot author a coordinate per
    port the way a pump authors its suction. It declares the *rule* instead, and
    the coordinates are resolved once the unit is in hand and the count is known.

    Members are ``prefix`` followed by a 1-based index (``in_1``, ``in_2``, ...),
    matching the names :class:`~pfd.units.Mixer` and
    :class:`~pfd.units.Splitter` generate.

    Ports sit ``pitch`` apart, centred on the face; past the point where that
    would run them off the ends, the whole run is squeezed into the middle
    ``extent`` of the face instead. Two ports therefore land exactly where the
    hand-drawn symbols used to put them, and a third does not have to shove the
    first two aside to find room.
    """

    prefix: str
    face: str
    pitch: float = 20.0
    extent: float = 0.7

    def matches(self, port_name: str) -> bool:
        """True when ``port_name`` is a member of this series."""
        return (port_name.startswith(self.prefix)
                and port_name[len(self.prefix):].isdigit())

    def placement(self, index: int, count: int,
                  width: float, height: float) -> tuple[float, float]:
        """Symbol-space coordinate of member ``index`` of ``count`` (0-based)."""
        along = height if self.face in ("W", "E") else width
        span = min(self.pitch * (count - 1), self.extent * along)
        t = along / 2 if count < 2 else (along - span) / 2 + span * index / (count - 1)
        return {"W": (0.0, t), "E": (width, t),
                "N": (t, 0.0), "S": (t, height)}[self.face]


@dataclass
class Symbol:
    """An SVG template for a unit, with named connection port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Every placement a port may take, keyed by the face it lands on, each with
    # its own exact coordinate so a moved port still lands on drawn ink:
    #   {"feed": {"W": (0.0, 15.0), "N": (30.0, 0.0), "E": (91.5, 15.0)}}
    # ``__post_init__`` folds the symbol's own nozzle in as the first entry, so
    # this is the *whole* menu — nothing downstream has to merge a privileged
    # default back in, and a nozzle fixed by physics (a drum's liquid draw is on
    # the bottom because gravity put it there) is simply one with a single entry.
    port_faces: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    # Connections with no face of their own. An instrument balloon is a circle,
    # so a signal may meet it anywhere and "in on the west, out on the east" is
    # an artefact of having to pick a default rather than physics. Only these
    # may offer each other the same face: the overlap is a menu, not a
    # collision, since one placement per port is ever live. Authoring
    # *alternates* for an equipment nozzle does not make it faceless — a drum's
    # inlet may be moved to the right head, but that is still the inlet's
    # nozzle and nothing else may sit on it.
    faceless_ports: frozenset[str] = frozenset()
    # Port families whose membership the *unit* decides — a Mixer's inlets. The
    # symbol cannot list them in ``ports`` because it does not know how many
    # there are, so it declares the rule and :mod:`pfd.portgeom` resolves the
    # coordinates against the unit. A series is the sole authority for its own
    # members; naming one in ``ports`` as well would be two answers to one
    # question, and is rejected below.
    port_series: tuple[PortSeries, ...] = ()
    label_pos: str | None = None
    # Deprecated spelling, accepted so a symbol authored against the old
    # interface still registers. ``port_alts`` listed only the *extra* faces.
    port_alts: InitVar[dict[str, dict[str, tuple[float, float]]] | None] = None
    free_ports: InitVar[frozenset[str] | None] = None

    def __post_init__(self, port_alts, free_ports) -> None:
        if free_ports is not None:
            warnings.warn(
                "Symbol.free_ports is now Symbol.faceless_ports.",
                DeprecationWarning, stacklevel=2,
            )
            self.faceless_ports = frozenset(self.faceless_ports) | frozenset(free_ports)
        declared = {name: dict(faces) for name, faces in self.port_faces.items()}
        if port_alts is not None:
            warnings.warn(
                "Symbol.port_alts is deprecated; declare the whole menu in "
                "Symbol.port_faces (the symbol's own nozzle is folded in for you).",
                DeprecationWarning, stacklevel=2,
            )
            for name, faces in port_alts.items():
                declared.setdefault(name, {}).update(faces)
        # Everything below rejects rather than repairs. A declaration the engine
        # cannot honour used to be dropped where it was read -- the menu is
        # re-keyed by coordinate at resolve time, so a placement filed under the
        # wrong face simply ceased to exist -- and a placement that vanishes is
        # indistinguishable from one that was never authored. The invariant
        # suite catches these for the shipped registry; a third-party symbol
        # only ever meets this constructor.
        stray = sorted(set(declared) - set(self.ports))
        if stray:
            raise ValueError(
                f"{self.symbol_id()}: port_faces declares a menu for {stray}, which "
                f"ports does not anchor; nothing reads a menu for a port that has "
                f"no nozzle"
            )
        stray = sorted(frozenset(self.faceless_ports) - set(self.ports))
        if stray:
            raise ValueError(
                f"{self.symbol_id()}: faceless_ports names {stray}, which ports does "
                f"not anchor"
            )
        for series in self.port_series:
            clash = sorted(n for n in self.ports if series.matches(n))
            if clash:
                raise ValueError(
                    f"{self.symbol_id()}: ports anchors {clash}, which the "
                    f"{series.prefix!r} series also places; a series is the only "
                    f"authority on where its members go"
                )
            if series.face not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.symbol_id()}: the {series.prefix!r} series names face "
                    f"{series.face!r}; expected one of N, S, E, W"
                )
        menu: dict[str, dict[str, tuple[float, float]]] = {}
        for name, xy in self.ports.items():
            home = outward_dir(xy[0], xy[1], self.width, self.height)
            faces = {home: xy}
            for face, coord in declared.get(name, {}).items():
                lands = outward_dir(coord[0], coord[1], self.width, self.height)
                if lands != face:
                    raise ValueError(
                        f"{self.symbol_id()}: port_faces[{name!r}][{face!r}] at "
                        f"{coord} is nearest the {lands} edge of the "
                        f"{self.width}x{self.height} box, so that is the face it "
                        f"would come out of"
                    )
                if face == home and coord != xy:
                    # ``ports`` is the authority on the home nozzle, so this
                    # placement could only ever be discarded.
                    raise ValueError(
                        f"{self.symbol_id()}: port_faces[{name!r}][{face!r}] is "
                        f"{coord} but ports[{name!r}] puts the same face at {xy}"
                    )
                faces[face] = coord
            menu[name] = faces
        self.port_faces = menu
        for a, b, xy in self.coincident_ports():
            warnings.warn(
                f"{self.symbol_id()}: ports {a!r} and {b!r} both have a placement "
                f"at {xy}, so a stream routed to one lands on top of a stream "
                f"routed to the other. Only ports named in faceless_ports may "
                f"share a placement.",
                stacklevel=2,
            )

    def series_for(self, port_name: str) -> PortSeries | None:
        """The series that places ``port_name``, or None if it is a fixed nozzle."""
        for series in self.port_series:
            if series.matches(port_name):
                return series
        return None

    def symbol_id(self) -> str:
        """The svg id, for messages — a Symbol carries no name of its own."""
        match = re.search(r'\bid="([^"]+)"', self.svg)
        return match.group(1) if match else "<symbol>"

    def coincident_ports(self) -> list[tuple[str, str, tuple[float, float]]]:
        """Pairs of *different* ports sharing a placement, with the point.

        Two ports at one coordinate means a stream routed to one lands exactly
        on top of a stream routed to the other. Two placements of a *single*
        port may of course coincide — only one of them is ever live.

        :attr:`faceless_ports` are exempt from *each other*, not from the rule:
        they are still checked against the nozzles that do own their face. The
        exemption is a declaration, deliberately, rather than something read off
        the shape of the menu — "this connection is faceless" and "this nozzle
        has authored alternatives" both produce a multi-entry menu, and only the
        first of them justifies two ports sitting on one point.
        """
        placements = [(name, xy) for name, faces in self.port_faces.items()
                      for xy in faces.values()]
        hits: list[tuple[str, str, tuple[float, float]]] = []
        seen: set[tuple[str, str]] = set()
        for i, (n1, p1) in enumerate(placements):
            for n2, p2 in placements[i + 1:]:
                if n1 == n2 or (n1 in self.faceless_ports and n2 in self.faceless_ports):
                    continue
                pair = (n1, n2) if n1 < n2 else (n2, n1)
                if pair in seen or math.hypot(p1[0] - p2[0], p1[1] - p2[1]) >= _COINCIDENT:
                    continue
                seen.add(pair)
                hits.append((pair[0], pair[1], p1))
        return hits

class SymbolRegistry:
    def __init__(self):
        self._symbols: dict[tuple[str, str], Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol, variant: str = "default") -> None:
        self._symbols[(kind, variant)] = template

    def get(self, kind: str, variant: str = "default") -> Symbol:
        if (kind, variant) in self._symbols:
            return self._symbols[(kind, variant)]
        if (kind, "default") in self._symbols:
            return self._symbols[(kind, "default")]
        return self._generic_symbol()

    def _generic_symbol(self) -> Symbol:
        svg = (
            '<g id="sym_generic">'
            '<rect x="0" y="0" width="60" height="60" fill="none" stroke="black" stroke-width="2" />'
            '</g>'
        )
        return Symbol(svg=svg, width=60, height=60)

    def _register_defaults(self):
        # ====================================================================
        # Feed / Product — rendered dynamically in svg.py, these are fallbacks
        # ====================================================================
        self.register("feed", Symbol(
            svg='<g id="sym_feed"><polygon points="0,10 35,10 50,25 35,40 0,40" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={"outlet": (50.0, 25.0)}
        ))
        self.register("product", Symbol(
            svg='<g id="sym_product"><polygon points="0,10 35,10 50,25 35,40 0,40 10,25" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50, height=50,
            ports={"inlet": (0.0, 25.0)}
        ))

        # ====================================================================
        # Centrifugal Pump — ISO 10628-2 standard symbol
        # Circle with discharge nozzle at top, suction on left, baseplate line
        # ====================================================================
        self.register("pump", Symbol(
            svg=(
                '<g id="sym_pump">'
                '<circle cx="30" cy="30" r="22" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="8" y1="52" x2="52" y2="52" stroke="black" stroke-width="2"/>'
                '<line x1="30" y1="8" x2="30" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="0" y1="30" x2="8" y2="30" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=55.0,
            ports={'suction': (0.0, 30.0), 'discharge': (30.0, 0.0)}
        ))

        # ====================================================================
        # Compressor — circle with triangle indicator
        # ====================================================================
        self.register("compressor", Symbol(
            svg=(
                '<g id="sym_compressor">'
                '<circle cx="40" cy="40" r="30" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="25,55 55,55 40,25" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=80.0,
            ports={'suction': (10.0, 40.0), 'discharge': (40.0, 10.0)}
        ))

        # ====================================================================
        # Separator — vertical vessel with elliptical heads (ISO 10628-2)
        # ====================================================================
        self.register("separator", Symbol(
            svg=(
                '<g id="sym_separator">'
                '<rect x="10" y="25" width="60" height="130" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="155" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=170.0,
            ports={'liquid': (40.0, 167.0), 'feed': (10.0, 90.0), 'vapor': (40.0, 13.0)}
        ))

        # ====================================================================
        # Reactor — vertical vessel with internal coil indicator
        # ====================================================================
        self.register("reactor", Symbol(
            svg=(
                '<g id="sym_reactor">'
                '<rect x="10" y="25" width="60" height="130" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="155" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M25,70 Q40,55 55,70 Q40,85 25,70" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=80.0, height=170.0,
            ports={'duty': (70.0, 90.0), 'outlet': (40.0, 167.0), 'feed': (40.0, 13.0)}
        ))

        # ====================================================================
        # Shell & Tube Heat Exchanger — ISO 10628-2 standard
        # Horizontal cylinder with two tube-side nozzles on ends
        # and two shell-side nozzles on top/bottom
        # ====================================================================
        self.register("hex", Symbol(
            svg=(
                '<g id="sym_hex">'
                '<rect x="15" y="10" width="70" height="40" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="15" cy="30" rx="8" ry="20" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="85" cy="30" rx="8" ry="20" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="15" y1="30" x2="85" y2="30" stroke="black" stroke-width="1" stroke-dasharray="4,3"/>'
                '</g>'
            ),
            width=100.0, height=60.0,
            ports={
                'cold_in': (0.0, 30.0),
                'cold_out': (100.0, 30.0),
                'hot_in': (50.0, 10.0),
                'hot_out': (50.0, 50.0),
            }
        ))
        

        # ====================================================================
        # Mixer — Standard triangle pointing right
        # All inputs on the left flat face, output at right vertex
        # ====================================================================
        self.register("mixer", Symbol(
            svg='<g id="sym_mixer"><polygon points="0,0 50,25 0,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'outlet': (50.0, 25.0)},
            port_series=(PortSeries("in_", "W"),),
        ))

        # ====================================================================
        # Valve — ISO 10628-2 butterfly / gate valve (bowtie)
        # Two opposing triangles forming a bowtie shape
        # ====================================================================
        self.register("valve", Symbol(
            svg=(
                '<g id="sym_valve">'
                '<polygon points="0,0 20,15 0,30" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="40,0 20,15 40,30" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="20" y1="0" x2="20" y2="15" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=40.0, height=30.0,
            ports={'inlet': (0.0, 15.0), 'outlet': (40.0, 15.0)}
        ))

        # ====================================================================
        # Vessel — vertical drum with dished heads
        # ====================================================================
        self.register("vessel", Symbol(
            svg=(
                '<g id="sym_vessel">'
                '<rect x="10" y="20" width="60" height="80" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="20" rx="30" ry="10" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="100" rx="30" ry="10" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=115.0,
            ports={'inlet': (10.0, 55.0), 'outlet': (70.0, 55.0)}
        ))

        # ====================================================================
        # Heater — circle with an internal zigzag (electric heater symbol)
        # ====================================================================
        self.register("heater", Symbol(
            svg=(
                '<g id="sym_heater">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M15,30 L20,20 L25,40 L30,20 L35,40 L40,20 L45,30" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={'outlet': (55.0, 30.0), 'duty': (30.0, 55.0), 'inlet': (5.0, 30.0)}
        ))

        # ====================================================================
        # Cooler — circle with internal zigzag plus cooling arrow
        # ====================================================================
        self.register("cooler", Symbol(
            svg=(
                '<g id="sym_cooler">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M15,30 L20,20 L25,40 L30,20 L35,40 L40,20 L45,30" fill="none" stroke="black" stroke-width="1.5"/>'
                '<path d="M48,12 L55,5" stroke="black" stroke-width="1.5"/>'
                '<path d="M52,8 L55,5 L51,5" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={'outlet': (55.0, 30.0), 'inlet': (5.0, 30.0), 'duty': (30.0, 5.0)}
        ))

        # ====================================================================
        # Distillation Column — tall vertical vessel with internal trays
        # ====================================================================
        self.register("column", Symbol(
            svg=(
                '<g id="sym_column">'
                '<rect x="10" y="20" width="60" height="170" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="20" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="190" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                # Internal tray lines
                '<line x1="15" y1="65" x2="65" y2="65" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="100" x2="65" y2="100" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="135" x2="65" y2="135" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="170" x2="65" y2="170" stroke="black" stroke-width="1"/>'
                '</g>'
            ),
            width=80.0, height=205.0,
            ports={
                'reboiler_duty': (70.0, 105.0),
                'bottoms': (40.0, 202.0),
                'feed': (10.0, 105.0),
                'distillate': (40.0, 8.0),
            }
        ))
        

        # ====================================================================
        # Splitter — Standard triangle with point on left, flat on right
        # All outputs on the right flat face, input at left vertex
        # ====================================================================
        self.register("splitter", Symbol(
            svg='<g id="sym_splitter"><polygon points="0,25 50,0 50,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'inlet': (0.0, 25.0)},
            port_series=(PortSeries("out_", "E"),),
        ))

        # ====================================================================
        # ISA-5.1 instrument bubbles. The tag text is drawn dynamically from the
        # unit name by the renderer, so the symbol is just the balloon + its
        # location bar. Ports: pv (process connection, bottom), in/out (signals).
        # Variants: field (bare balloon), panel (single bar), aux (double bar),
        # shared (balloon-in-square = DCS/shared display), computer (hexagon).
        # ====================================================================
        # A balloon is a circle: a signal can meet it anywhere, so every
        # connection offers all four faces and none of them owns one. The
        # coordinates are one unit clear of the r=21 circle, matching the
        # nozzle stub used everywhere else.
        _inst_faces = {"N": (22.0, 0.0), "S": (22.0, 44.0),
                       "W": (0.0, 22.0), "E": (44.0, 22.0)}
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        # Every connection offers every face, so none of them owns one: the
        # menus overlap on purpose, which is what faceless_ports declares.
        _inst_menu = {name: dict(_inst_faces) for name in _inst_ports}
        _inst_faceless = frozenset(_inst_ports)
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center"))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_panel"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="22" x2="43" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center"), "panel")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_aux"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="19" x2="43" y2="19" stroke="black" stroke-width="1.5"/><line x1="1" y1="25" x2="43" y2="25" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center"), "aux")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center"), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # The hexagon's flat bottom is at y=41, not y=43 like the circular
            # variants, so pv needs its own coordinate to keep the same 1-unit
            # nozzle stub instead of floating 3 units clear of the outline.
            width=44.0, height=44.0, label_pos="center",
            faceless_ports=_inst_faceless,
            ports={**_inst_ports, "pv": (22.0, 42.0)},
            # the hexagon is flat-topped at y=3 and flat-bottomed at y=41, so N and S
            # need their own stubs; the side vertices sit where the circles do.
            port_faces={n: {**_inst_faces, "N": (22.0, 2.0), "S": (22.0, 42.0)}
                        for n in _inst_ports}), "computer")
        # Interlock / shared logic: a small bare square carrying only the
        # interlock number, hung under the instrument it trips (ISA-5.1).
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_logic"><rect x="1" y="1" width="26" height="26" fill="white" stroke="black" stroke-width="2"/></g>',
            width=28.0, height=28.0, label_pos="center",
            ports={'pv': (14.0, 27.0), 'sig_in': (1.0, 14.0), 'sig_out': (27.0, 14.0)}),
            "logic")

        # Vendored draw.io symbols (Apache-2.0) — registered last so they
        # override the hand-drawn defaults for shared kinds and add variants.
        from pfd.render._vendored_symbols import register_vendored
        register_vendored(self)


default_registry = SymbolRegistry()
