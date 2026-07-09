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

    def render(self, fs: "Flowsheet", path: str, jump_direction: str = "vertical", **opts) -> None:
        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append('<svg xmlns="http://www.w3.org/2000/svg" '
                     'xmlns:xlink="http://www.w3.org/1999/xlink" '
                     'width="2000" height="2000">')
        
        # Determine used stream colors to generate arrow markers
        used_colors = set()
        for s in fs.streams:
            used_colors.add(s.color or "black")

        # 1. Embed definitions for used symbols and markers
        lines.append('  <defs>')
        for c in used_colors:
            marker_id = f'arrow_{c.replace("#", "").replace(" ", "_")}'
            lines.append(
                f'    <marker id="{marker_id}" viewBox="0 0 10 10" refX="10" refY="5" '
                f'markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{c}" />')
            lines.append('    </marker>')

        used_kinds = {u.kind for u in fs.units}
        for kind in used_kinds:
            sym = self.registry.get(kind)
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
            safe_name = html.escape(u.name)
            sym = self.registry.get(u.kind)
            if sym.label_pos:
                lx = x + sym.label_pos[0]
                ly = y + sym.label_pos[1]
                # Center vertically and horizontally if label_pos is provided (usually inside shapes)
                lines.append(f'    <text x="{lx}" y="{ly}" font-family="sans-serif" '
                             f'font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            else:
                lines.append(f'    <text x="{x}" y="{y - 5}" font-family="sans-serif" '
                             f'font-size="12">{safe_name}</text>')
        lines.append('  </g>')

        # Pre-compute stream point geometries for crossings and labels
        stream_geoms = []
        horizontals = []
        verticals = []

        for s in fs.streams:
            src_u = s.source.owner
            dst_u = s.dest.owner
            src_sym = self.registry.get(src_u.kind)
            dst_sym = self.registry.get(dst_u.kind)
            
            src_px, src_py = src_sym.ports.get(s.source.name, (src_sym.width / 2, src_sym.height / 2))
            dst_px, dst_py = dst_sym.ports.get(s.dest.name, (dst_sym.width / 2, dst_sym.height / 2))
            
            sx = src_u.placement.x + src_px
            sy = src_u.placement.y + src_py
            dx = dst_u.placement.x + dst_px
            dy = dst_u.placement.y + dst_py
            
            points = [(sx, sy)] + (s.route.waypoints if s.route and s.route.waypoints else []) + [(dx, dy)]
            
            # Simplify collinear points to prevent "hanging" arrowheads on tiny final segments
            simplified = [points[0]]
            for i in range(1, len(points) - 1):
                p_prev = simplified[-1]
                p_curr = points[i]
                p_next = points[i+1]
                # If they form a continuous horizontal or vertical line, skip the middle point
                if (p_prev[0] == p_curr[0] == p_next[0]) or (p_prev[1] == p_curr[1] == p_next[1]):
                    pass
                else:
                    simplified.append(p_curr)
            if len(points) > 1:
                simplified.append(points[-1])
            points = simplified
            
            stream_geoms.append((s, points))
            
            for i in range(len(points)-1):
                p1, p2 = points[i], points[i+1]
                if p1[1] == p2[1]: # horizontal
                    horizontals.append((p1[1], min(p1[0], p2[0]), max(p1[0], p2[0])))
                elif p1[0] == p2[0]: # vertical
                    verticals.append((p1[0], min(p1[1], p2[1]), max(p1[1], p2[1])))

        # 3. Draw streams
        lines.append('  <g id="streams">')
        for s, points in stream_geoms:
            color = s.color or "black"
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            else:
                dash = ' stroke-dasharray="3,3"' if s.kind == "energy" else ''
            
            marker_id = f'arrow_{color.replace("#", "").replace(" ", "_")}'
            
            # Construct SVG Path with crossing jumps
            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            max_len = 0
            longest_seg = None
            
            for i in range(len(points)-1):
                x1, y1 = points[i]
                x2, y2 = points[i+1]
                
                # For label placement
                dist = abs(x1 - x2) + abs(y1 - y2)
                if dist > max_len:
                    max_len = dist
                    longest_seg = (points[i], points[i+1])

                # Crossings
                if jump_direction == "vertical" and x1 == x2: # Vertical segment
                    crossings = [hy for hy, mx, Mx in horizontals if mx < x1 < Mx and min(y1, y2) < hy < max(y1, y2)]
                    crossings.sort(reverse=(y1 > y2))
                    
                    for hy in crossings:
                        if y1 < y2:
                            d_parts.extend([f"L {x1},{hy - 5}", f"A 5 5 0 0 1 {x1},{hy + 5}"])
                        else:
                            d_parts.extend([f"L {x1},{hy + 5}", f"A 5 5 0 0 1 {x1},{hy - 5}"])
                    d_parts.append(f"L {x2},{y2}")
                    
                elif jump_direction == "horizontal" and y1 == y2: # Horizontal segment
                    crossings = [vx for vx, my, My in verticals if my < y1 < My and min(x1, x2) < vx < max(x1, x2)]
                    crossings.sort(reverse=(x1 > x2))
                    
                    for vx in crossings:
                        if x1 < x2:
                            d_parts.extend([f"L {vx - 5},{y1}", f"A 5 5 0 0 1 {vx + 5},{y1}"])
                        else:
                            d_parts.extend([f"L {vx + 5},{y1}", f"A 5 5 0 0 1 {vx - 5},{y1}"])
                    d_parts.append(f"L {x2},{y2}")
                else:
                    d_parts.append(f"L {x2},{y2}")
                    
            d_str = " ".join(d_parts)
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash} marker-end="url(#{marker_id})" />'
            )
            
            # Stream Label
            if longest_seg:
                lx1, ly1 = longest_seg[0]
                lx2, ly2 = longest_seg[1]
                mid_x = (lx1 + lx2) / 2
                mid_y = (ly1 + ly2) / 2
                tx = mid_x
                ty = mid_y
                anchor = "middle"
                
                # Draw a solid white rectangle to cleanly wipe the line underneath (CAD style)
                text_len = len(s.name) * 7.5
                rect_width = text_len + 8
                rect_height = 14
                rx = mid_x - rect_width / 2
                ry = mid_y - rect_height / 2
                
                lines.append(
                    f'    <rect x="{rx}" y="{ry}" width="{rect_width}" height="{rect_height}" fill="white" />'
                )
                
                # Draw the actual text label
                lines.append(
                    f'    <text x="{tx}" y="{ty}" font-family="sans-serif" font-size="10" '
                    f'text-anchor="{anchor}" dominant-baseline="middle" '
                    f'fill="{color}">{html.escape(s.name)}</text>'
                )

        lines.append('  </g>')
        lines.append('</svg>')
        
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
