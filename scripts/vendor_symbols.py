import os
import xml.etree.ElementTree as ET

SVG_DIR = "/tmp/equinor-symbols/package/src/svg"

# Map internal 'kind' to (SVG_Filename, {Equinor_Port_Number: Semantic_Port_Name})
MAPPING = {
    "pump": ("PP001A.svg", {"1": "discharge", "2": "suction"}),
    "compressor": ("PP003A.svg", {"1": "discharge", "2": "suction"}),
    # Separator is a vertical cylinder. Port 4 (top) -> vapor, Port 2 (bottom) -> liquid, Port 3 (left) -> feed
    "separator": ("PT002A.svg", {"4": "vapor", "2": "liquid", "3": "feed"}),
    # Reactor is a vertical cylinder too. Port 4 (top) -> feed, Port 2 (bottom) -> outlet, Port 1 (right) -> duty
    "reactor": ("PT002A.svg", {"4": "feed", "2": "outlet", "1": "duty"}),
    # Heat Exchanger (cylinder)
    "hex": ("PT002A.svg", {"3": "cold_in", "1": "cold_out", "4": "hot_in", "2": "hot_out"}),
    # Mixer is a circle. Port 3 (left), Port 4 (top) -> inlets, Port 1 (right) -> outlet
    "mixer": ("ND0023.svg", {"3": "in_1", "4": "in_2", "1": "outlet"}),
    
    # New Mappings for M6 / P&ID
    "valve": ("PV022A.svg", {"2": "inlet", "1": "outlet"}),
    "vessel": ("PT005A.svg", {"2": "inlet", "1": "outlet"}),
    "heater": ("PT002A.svg", {"3": "inlet", "1": "outlet", "2": "duty"}),
    "cooler": ("PT002A.svg", {"3": "inlet", "1": "outlet", "4": "duty"}),
    "column": ("PT002A.svg", {"3": "feed", "4": "distillate", "2": "bottoms", "1": "reboiler_duty"}),
    "splitter": ("ND0024.svg", {"3": "inlet", "1": "out_1", "4": "out_2", "2": "out_3"}),
}

OUTPUT_FILE = "pfd/render/symbols.py"

def generate_registry():
    out = [
        '"""SVG symbol registry for the topology primitives."""',
        '',
        'from dataclasses import dataclass, field',
        '',
        '@dataclass',
        'class Symbol:',
        '    """An SVG template for a unit, with named connection port anchors."""',
        '    svg: str',
        '    width: float',
        '    height: float',
        '    ports: dict[str, tuple[float, float]] = field(default_factory=dict)',
        '    label_pos: tuple[float, float] | None = None',
        '',
        'class SymbolRegistry:',
        '    def __init__(self):',
        '        self._symbols: dict[str, Symbol] = {}',
        '        self._register_defaults()',
        '',
        '    def register(self, kind: str, template: Symbol) -> None:',
        '        self._symbols[kind] = template',
        '',
        '    def get(self, kind: str) -> Symbol:',
        '        if kind not in self._symbols:',
        '            return self._generic_symbol()',
        '        return self._symbols[kind]',
        '',
        '    def _generic_symbol(self) -> Symbol:',
        '        svg = (',
        '            \'<g id="sym_generic">\'',
        '            \'<rect x="0" y="0" width="50" height="50" fill="white" stroke="black" />\'',
        '            \'</g>\'',
        '        )',
        '        return Symbol(svg=svg, width=50, height=50)',
        '',
        '    def _register_defaults(self):',
        '        # Generic Feed',
        '        self.register("feed", Symbol(',
        '            svg=\'<g id="sym_feed"><polygon points="0,25 30,25 50,0 50,50" fill="#e0f7fa" stroke="black"/></g>\',',
        '            width=50, height=50,',
        '            ports={"outlet": (50.0, 25.0)}',
        '        ))',
        '        # Generic Product',
        '        self.register("product", Symbol(',
        '            svg=\'<g id="sym_product"><polygon points="0,0 20,25 0,50 50,50 50,0" fill="#fbe9e7" stroke="black"/></g>\',',
        '            width=50, height=50,',
        '            ports={"inlet": (0.0, 25.0)}',
        '        ))',
    ]

    for kind, (filename, port_map) in MAPPING.items():
        svg_path = os.path.join(SVG_DIR, filename)
        if not os.path.exists(svg_path):
            print(f"Warning: {svg_path} not found.")
            continue
            
        tree = ET.parse(svg_path)
        root = tree.getroot()
        
        width = float(root.attrib.get('width', 50))
        height = float(root.attrib.get('height', 50))
        
        # Extract <path> tags from <g id="Symbol">
        paths = []
        symbol_group = root.find(".//{http://www.w3.org/2000/svg}g[@id='Symbol']")
        if symbol_group is None:
            # Fallback to any path in the root
            symbol_group = root
            
        for path in symbol_group.findall(".//{http://www.w3.org/2000/svg}path"):
            d = path.attrib.get('d', '')
            paths.append(f'<path d="{d}" stroke="black" fill="transparent"/>')
            
        svg_content = f'<g id="sym_{kind}">' + "".join(paths) + "</g>"
        
        # Extract ports from <g id="Annotations">
        ports = {}
        annotations_group = root.find(".//{http://www.w3.org/2000/svg}g[@id='Annotations']")
        if annotations_group is not None:
            for circle in annotations_group.findall(".//{http://www.w3.org/2000/svg}circle"):
                cid = circle.attrib.get('id', '')
                cx = float(circle.attrib.get('cx', 0))
                cy = float(circle.attrib.get('cy', 0))
                
                # cid is like "annotation-connector-2-270"
                parts = cid.split('-')
                if len(parts) >= 3:
                    port_num = parts[2]
                    if port_num in port_map:
                        semantic_name = port_map[port_num]
                        ports[semantic_name] = (cx, cy)
                        
        out.append(f'        # Equinor Symbol: {filename}')
        out.append(f'        self.register("{kind}", Symbol(')
        out.append(f'            svg=\'{svg_content}\',')
        out.append(f'            width={width}, height={height},')
        out.append(f'            ports={ports}')
        out.append(f'        ))')
        
    out.append('')
    out.append('default_registry = SymbolRegistry()')
    out.append('')
    
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(out))

if __name__ == "__main__":
    generate_registry()
    print("Successfully generated symbols.py")
