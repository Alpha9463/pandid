"""SVG rendering backend."""

from typing import TYPE_CHECKING
import html

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
        from pfd.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", path: str, **opts) -> None:
        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append('<svg xmlns="http://www.w3.org/2000/svg" '
                     'xmlns:xlink="http://www.w3.org/1999/xlink" '
                     'width="2000" height="2000">')
        
        # 1. Embed definitions for used symbols
        lines.append('  <defs>')
        used_kinds = {u.kind for u in fs.units}
        for kind in used_kinds:
            sym = self.registry.get(kind)
            # Ensure the embedded SVG doesn't break XML structure
            # and override the ID if a generic symbol is returned for a missing kind
            svg_str = sym.svg
            if kind not in self.registry._symbols:
                svg_str = svg_str.replace('id="sym_generic"', f'id="sym_{kind}"')
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')

        # 2. Draw units using <use> tags
        lines.append('  <g id="units">')
        for u in fs.units:
            if u.placement is None:
                raise ValueError(
                    f"Unit '{u.name}' lacks a placement even after layout was run."
                )
            x, y = u.placement.x, u.placement.y
            lines.append(f'    <use href="#sym_{u.kind}" x="{x}" y="{y}" />')
            # Text label, safely escaping XML
            safe_name = html.escape(u.name)
            lines.append(f'    <text x="{x}" y="{y - 5}" font-family="sans-serif" '
                         f'font-size="12">{safe_name}</text>')
        lines.append('  </g>')

        # 3. Draw streams
        lines.append('  <g id="streams">')
        for s in fs.streams:
            src_u = s.source.owner
            dst_u = s.dest.owner
            
            src_sym = self.registry.get(src_u.kind)
            dst_sym = self.registry.get(dst_u.kind)
            
            # Resolve anchors
            src_px, src_py = src_sym.ports.get(
                s.source.name, (src_sym.width / 2, src_sym.height / 2)
            )
            dst_px, dst_py = dst_sym.ports.get(
                s.dest.name, (dst_sym.width / 2, dst_sym.height / 2)
            )
            
            sx = src_u.placement.x + src_px
            sy = src_u.placement.y + src_py
            dx = dst_u.placement.x + dst_px
            dy = dst_u.placement.y + dst_py
            
            if s.route and s.route.waypoints:
                points = [(sx, sy)] + s.route.waypoints + [(dx, dy)]
            else:
                points = [(sx, sy), (dx, dy)]
                
            pts_str = " ".join(f"{px},{py}" for px, py in points)
            color = "blue" if s.is_recycle else "black"
            dash = ' stroke-dasharray="5,5"' if s.is_recycle else ''
            
            lines.append(
                f'    <polyline points="{pts_str}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash}/>'
            )
        lines.append('  </g>')

        lines.append('</svg>')
        
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
