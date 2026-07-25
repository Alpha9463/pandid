"""SVG symbol registry for the topology primitives.

Symbols follow ISO 10628-2 / ISA 5.1 conventions and come from two sources:

- **Vendored (draw.io / diagrams.net P&ID stencils, Apache-2.0)** — valves and
  their variants, pumps, compressors, blowers, heat exchangers, vessels,
  columns, reactors, separators, tanks, and reducers. Converted from mxGraph
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

from dataclasses import dataclass, field

@dataclass
class Symbol:
    """An SVG template for a unit, with named connection port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Alternate faces a port may be moved to, each with its own exact coordinate
    # so the moved port still lands on drawn ink:
    #   {"feed": {"N": (30.0, 0.0), "E": (91.5, 15.0)}}
    port_alts: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    label_pos: str | None = None

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
            ports={'outlet': (50.0, 25.0), 'in_1': (0.0, 15.0), 'in_2': (0.0, 35.0)}
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
            ports={'out_1': (50.0, 15.0), 'out_2': (50.0, 35.0), 'inlet': (0.0, 25.0)}
        ))

        # ====================================================================
        # ISA-5.1 instrument bubbles. The tag text is drawn dynamically from the
        # unit name by the renderer, so the symbol is just the balloon + its
        # location bar. Ports: pv (process connection, bottom), in/out (signals).
        # Variants: field (bare balloon), panel (single bar), aux (double bar),
        # shared (balloon-in-square = DCS/shared display), computer (hexagon).
        # ====================================================================
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, label_pos="center"))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_panel"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="22" x2="43" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, label_pos="center"), "panel")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_aux"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="19" x2="43" y2="19" stroke="black" stroke-width="1.5"/><line x1="1" y1="25" x2="43" y2="25" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, label_pos="center"), "aux")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, label_pos="center"), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # The hexagon's flat bottom is at y=41, not y=43 like the circular
            # variants, so pv needs its own coordinate to keep the same 1-unit
            # nozzle stub instead of floating 3 units clear of the outline.
            width=44.0, height=44.0, label_pos="center",
            ports={**_inst_ports, "pv": (22.0, 42.0)}), "computer")

        # Vendored draw.io symbols (Apache-2.0) — registered last so they
        # override the hand-drawn defaults for shared kinds and add variants.
        from pfd.render._vendored_symbols import register_vendored
        register_vendored(self)


default_registry = SymbolRegistry()
