"""SVG symbol registry for the topology primitives.

Symbols follow ISO 10628-2 and ISA 5.1 conventions where applicable.
All custom geometric SVG primitives — no proprietary icons.
"""

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Symbol:
    """An SVG template for a unit, with named connection port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    label_pos: Optional[str] = None

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
        # NEW VARIANTS
        # ====================================================================
        self.register("column", Symbol(
            svg=(
                '<g id="sym_column_tray">'
                '<rect x="15" y="25" width="50" height="160" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="25" ry="15" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="185" rx="25" ry="15" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="15" y1="70" x2="65" y2="60" stroke="black" stroke-width="1.5"/>'
                '<line x1="15" y1="110" x2="65" y2="100" stroke="black" stroke-width="1.5"/>'
                '<line x1="15" y1="150" x2="65" y2="140" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=80.0, height=205.0,
            ports={
                'reboiler_duty': (65.0, 105.0),
                'bottoms': (40.0, 200.0),
                'feed': (15.0, 105.0),
                'distillate': (40.0, 10.0),
                'vapor_in': (40.0, 200.0),
                'liquid_in': (40.0, 10.0),
                'vapor_out': (40.0, 10.0),
                'liquid_out': (40.0, 200.0),
            }
        ), variant="tray")

        self.register("column", Symbol(
            svg=(
                '<g id="sym_column_packed">'
                '<rect x="15" y="25" width="50" height="160" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="25" ry="15" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="185" rx="25" ry="15" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M 15 60 L 65 100 M 15 100 L 65 60" stroke="black" stroke-width="1.5"/>'
                '<path d="M 15 120 L 65 160 M 15 160 L 65 120" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=80.0, height=205.0,
            ports={
                'reboiler_duty': (65.0, 105.0),
                'bottoms': (40.0, 200.0),
                'feed': (15.0, 105.0),
                'distillate': (40.0, 10.0),
                'vapor_in': (40.0, 200.0),
                'liquid_in': (40.0, 10.0),
                'vapor_out': (40.0, 10.0),
                'liquid_out': (40.0, 200.0),
            }
        ), variant="packed")

        self.register("vessel", Symbol(
            svg=(
                '<g id="sym_vessel_tank">'
                '<rect x="10" y="20" width="60" height="80" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M10,20 Q40,0 70,20" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="10" y1="100" x2="70" y2="100" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=115.0,
            ports={'inlet': (10.0, 55.0), 'outlet': (70.0, 100.0)}
        ), variant="tank")

        self.register("pump", Symbol(
            svg=(
                '<g id="sym_pump_centrifugal">'
                '<circle cx="30" cy="30" r="22" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="8" y1="52" x2="52" y2="52" stroke="black" stroke-width="2"/>'
                '<line x1="30" y1="8" x2="30" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="0" y1="30" x2="8" y2="30" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=55.0,
            ports={'suction': (0.0, 30.0), 'discharge': (30.0, 0.0)},
            label_pos="bottom"
        ), variant="centrifugal")

        self.register("pump", Symbol(
            svg=(
                '<g id="sym_pump_vacuum">'
                '<circle cx="30" cy="30" r="22" fill="none" stroke="black" stroke-width="2"/>'
                '<circle cx="30" cy="30" r="10" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="8" y1="52" x2="52" y2="52" stroke="black" stroke-width="2"/>'
                '<line x1="30" y1="8" x2="30" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="0" y1="30" x2="8" y2="30" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=55.0,
            ports={'suction': (0.0, 30.0), 'discharge': (30.0, 0.0)}
        ), variant="vacuum")

        self.register("pump", Symbol(
            svg=(
                '<g id="sym_pump_pd">'
                '<circle cx="30" cy="20" r="15" fill="none" stroke="black" stroke-width="2"/>'
                '<circle cx="30" cy="40" r="15" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="8" y1="52" x2="52" y2="52" stroke="black" stroke-width="2"/>'
                '<line x1="30" y1="5" x2="30" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="0" y1="30" x2="15" y2="30" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=55.0,
            ports={'suction': (0.0, 30.0), 'discharge': (30.0, 0.0)}
        ), variant="pd")

        self.register("hex", Symbol(
            svg=(
                '<g id="sym_hex_shell_tube">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M5,30 Q15,5 30,30 T55,30" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={
                'cold_in': (5.0, 30.0),
                'cold_out': (55.0, 30.0),
                'hot_in': (30.0, 5.0),
                'hot_out': (30.0, 55.0),
            }
        ), variant="shell_tube")

        self.register("hex", Symbol(
            svg=(
                '<g id="sym_hex_air_cooler">'
                '<rect x="10" y="20" width="40" height="20" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="30,40 25,50 35,50" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={
                'cold_in': (10.0, 30.0),
                'cold_out': (50.0, 30.0),
                'hot_in': (30.0, 20.0),
                'hot_out': (30.0, 40.0),
            }
        ), variant="air_cooler")

        self.register("valve", Symbol(
            svg=(
                '<g id="sym_valve_control">'
                '<polygon points="0,15 20,25 0,35" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="40,15 20,25 40,35" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="20" y1="25" x2="20" y2="5" stroke="black" stroke-width="2"/>'
                '<path d="M10,5 Q20,0 30,5" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=40.0, height=40.0,
            ports={'inlet': (0.0, 25.0), 'outlet': (40.0, 25.0)}
        ), variant="control")

        self.register("valve", Symbol(
            svg=(
                '<g id="sym_valve_relief">'
                '<polygon points="5,5 20,20 35,5" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="5,35 20,20 35,35" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="20" y1="5" x2="20" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="20" y1="35" x2="20" y2="40" stroke="black" stroke-width="2"/>'
                '<rect x="15" y="15" width="10" height="10" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=40.0, height=40.0,
            ports={'inlet': (20.0, 40.0), 'outlet': (35.0, 20.0)}
        ), variant="relief")

default_registry = SymbolRegistry()

