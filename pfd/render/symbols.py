"""SVG symbol registry for the topology primitives."""

from dataclasses import dataclass, field


@dataclass
class Symbol:
    """An SVG template for a unit, with named connection port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)


class SymbolRegistry:
    """Registry mapping unit kinds to SVG Symbols."""
    def __init__(self):
        self._symbols: dict[str, Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol) -> None:
        self._symbols[kind] = template

    def get(self, kind: str) -> Symbol:
        if kind not in self._symbols:
            return self._generic_symbol()
        return self._symbols[kind]

    def _generic_symbol(self) -> Symbol:
        svg = (
            '<g id="sym_generic">'
            '<rect x="0" y="0" width="50" height="50" fill="white" stroke="black" />'
            '</g>'
        )
        return Symbol(svg=svg, width=50, height=50)

    def _register_defaults(self):
        # A basic feed
        self.register("feed", Symbol(
            svg='<g id="sym_feed"><polygon points="0,25 30,25 50,0 50,50" fill="#e0f7fa" stroke="black"/></g>',
            width=50, height=50,
            ports={"outlet": (50.0, 25.0)}
        ))
        # A basic product
        self.register("product", Symbol(
            svg='<g id="sym_product"><polygon points="0,0 20,25 0,50 50,50 50,0" fill="#fbe9e7" stroke="black"/></g>',
            width=50, height=50,
            ports={"inlet": (0.0, 25.0)}
        ))
        # A generic vessel/reactor
        self.register("reactor", Symbol(
            svg='<g id="sym_reactor"><rect x="0" y="0" width="50" height="80" rx="10" fill="#f3e5f5" stroke="black"/></g>',
            width=50, height=80,
            ports={"feed": (0.0, 40.0), "outlet": (50.0, 40.0), "duty": (25.0, 80.0)}
        ))
        # Heat exchanger
        self.register("hex", Symbol(
            svg='<g id="sym_hex"><circle cx="25" cy="25" r="25" fill="#fff3e0" stroke="black"/>'
                '<path d="M 0,25 L 50,25" stroke="black"/></g>',
            width=50, height=50,
            ports={
                "hot_in": (0.0, 15.0), "hot_out": (50.0, 15.0),
                "cold_in": (0.0, 35.0), "cold_out": (50.0, 35.0)
            }
        ))


default_registry = SymbolRegistry()
