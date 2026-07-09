"""SVG rendering backend."""

from typing import TYPE_CHECKING
import html
import datetime

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
        from pfd.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", path: str = "", jump_direction: str = "vertical", show_stream_table: bool = False, styling: str = "default", page_size: str = "A3", **opts) -> str:
        """Render the flowsheet to SVG.

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
        path : str
            File path to write the SVG to. If empty, only returns the string.
        jump_direction : str
            Which crossing lines get a semicircle bump: ``"vertical"`` or ``"horizontal"``.
        show_stream_table : bool
            Whether to render a stream table below the diagram.
        styling : str
            ``"default"`` for plain, ``"pid"`` for title block and border.
        page_size : str
            Standard paper size: ``"A4"``, ``"A3"`` (default), ``"A2"``, ``"A1"``, ``"A0"``.
        """
        # Standard page sizes in landscape orientation (width x height in mm → viewBox points)
        _PAGE_SIZES = {
            "A4": (1122.0, 793.7),   # 297 x 210 mm at 96 dpi ÷ 25.4
            "A3": (1587.4, 1122.0),  # 420 x 297 mm
            "A2": (2245.0, 1587.4),  # 594 x 420 mm
            "A1": (3174.8, 2245.0),  # 841 x 594 mm
            "A0": (4489.1, 3174.8),  # 1189 x 841 mm
        }

        # 1. Determine bounding box of units and routes
        max_x, max_y = 0.0, 0.0
        for u in fs.units:
            if u.placement is None:
                raise ValueError(f"Unit '{u.name}' lacks a placement even after layout was run.")
            sym = self.registry.get(u.kind, getattr(u, 'variant', 'default'))
            max_x = max(max_x, u.placement.x + sym.width)
            max_y = max(max_y, u.placement.y + sym.height)
            
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)
                    
        # Add padding — use page size as minimum canvas
        page_w, page_h = _PAGE_SIZES.get(page_size.upper(), _PAGE_SIZES["A3"])
        canvas_width = max(page_w, max_x + 100)
        canvas_height = max(page_h, max_y + 100)
        
        # 2. Collect Stream Table Properties
        table_lines = []
        if show_stream_table:
            table_y_start = canvas_height + 50
            
            # Find all unique keys
            keys = set()
            for s in fs.streams:
                keys.update(s.properties.keys())
            sorted_keys = sorted(list(keys))
            
            # Columns: Property, S1, S2, S3...
            headers = ["Stream"] + [s.name for s in fs.streams]
            
            # Auto-scale: if more than ~20 streams, shrink columns to fit
            n_streams = len(fs.streams)
            if n_streams > 20:
                stream_col_w = max(35, int(canvas_width / (n_streams + 2)))
                font_size = max(8, min(12, int(stream_col_w / 5)))
                row_height = max(20, font_size + 12)
            else:
                stream_col_w = max(60, max(len(s.name) * 8 for s in fs.streams) if fs.streams else 60)
                font_size = 12
                row_height = 30
                
            col_widths = [100] + [stream_col_w] * n_streams
            table_width = sum(col_widths)
            
            if table_width > canvas_width:
                import warnings
                warnings.warn(
                    f"Stream table width ({table_width}px) exceeds canvas width "
                    f"({canvas_width:.0f}px). Consider using a larger page_size or "
                    f"reducing the number of stream properties.",
                    stacklevel=3,
                )
            
            # Update canvas dimensions
            canvas_width = max(canvas_width, table_width + 100)
            
            table_lines.append('  <g id="stream_table">')
            
            # Draw header row (Stream names)
            cx = 50
            for i, h in enumerate(headers):
                table_lines.append(f'    <rect x="{cx}" y="{table_y_start}" width="{col_widths[i]}" height="{row_height}" fill="#eee" stroke="black" />')
                table_lines.append(f'    <text x="{cx + col_widths[i]/2}" y="{table_y_start + row_height/2}" font-family="sans-serif" font-size="{font_size}" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{html.escape(h)}</text>')
                cx += col_widths[i]
                
            # Draw property rows
            current_y = table_y_start + row_height
            for k in sorted_keys:
                cx = 50
                # Property name cell
                table_lines.append(f'    <rect x="{cx}" y="{current_y}" width="{col_widths[0]}" height="{row_height}" fill="#f9f9f9" stroke="black" />')
                table_lines.append(f'    <text x="{cx + col_widths[0]/2}" y="{current_y + row_height/2}" font-family="sans-serif" font-size="{font_size}" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{html.escape(k)}</text>')
                cx += col_widths[0]
                
                # Stream values
                for i, s in enumerate(fs.streams):
                    val = str(s.properties.get(k, "-"))
                    cw = col_widths[i + 1]
                    table_lines.append(f'    <rect x="{cx}" y="{current_y}" width="{cw}" height="{row_height}" fill="white" stroke="black" />')
                    table_lines.append(f'    <text x="{cx + cw/2}" y="{current_y + row_height/2}" font-family="sans-serif" font-size="{font_size}" text-anchor="middle" dominant-baseline="middle">{html.escape(val)}</text>')
                    cx += cw
                    
                current_y += row_height
                
            table_lines.append('  </g>')
            canvas_height = current_y + 50
            
        pid_lines = []
        if styling == "pid":
            # 50px border
            border_margin = 25
            border_w = canvas_width - 2 * border_margin
            border_h = canvas_height - 2 * border_margin
            
            pid_lines.append('  <g id="pid_styling">')
            pid_lines.append(f'    <rect x="{border_margin}" y="{border_margin}" width="{border_w}" height="{border_h}" fill="none" stroke="black" stroke-width="4" />')
            
            # Title block in bottom right
            tb_w = 300
            tb_h = 100
            tb_x = canvas_width - border_margin - tb_w
            tb_y = canvas_height - border_margin - tb_h
            
            pid_lines.append(f'    <rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="{tb_h}" fill="white" stroke="black" stroke-width="2" />')
            
            # Lines inside title block
            pid_lines.append(f'    <line x1="{tb_x}" y1="{tb_y + 33}" x2="{tb_x + tb_w}" y2="{tb_y + 33}" stroke="black" stroke-width="1" />')
            pid_lines.append(f'    <line x1="{tb_x}" y1="{tb_y + 66}" x2="{tb_x + tb_w}" y2="{tb_y + 66}" stroke="black" stroke-width="1" />')
            
            # Text
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            pid_lines.append(f'    <text x="{tb_x + 10}" y="{tb_y + 20}" font-family="sans-serif" font-size="14" font-weight="bold">Project: {html.escape(fs.name)}</text>')
            pid_lines.append(f'    <text x="{tb_x + 10}" y="{tb_y + 53}" font-family="sans-serif" font-size="12">Generated by: py-chemengg</text>')
            pid_lines.append(f'    <text x="{tb_x + 10}" y="{tb_y + 86}" font-family="sans-serif" font-size="12">Date: {date_str}</text>')
            
            pid_lines.append('  </g>')

        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        
        # Physical dimensions for the SVG element (landscape orientation)
        _PHYS_DIMS = {
            "A4": ("297mm", "210mm"),
            "A3": ("420mm", "297mm"),
            "A2": ("594mm", "420mm"),
            "A1": ("841mm", "594mm"),
            "A0": ("1189mm", "841mm"),
        }
        phys_w, phys_h = _PHYS_DIMS.get(page_size.upper(), ("420mm", "297mm"))
        
        lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                     f'xmlns:xlink="http://www.w3.org/1999/xlink" '
                     f'width="{phys_w}" height="{phys_h}" viewBox="0 0 {canvas_width} {canvas_height}">')
        
        lines.append('  <!-- Background -->')
        lines.append(f'  <rect x="0" y="0" width="{canvas_width}" height="{canvas_height}" fill="white" />')
        
        if pid_lines:
            lines.extend(pid_lines)

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

        used_symbols = {(u.kind, getattr(u, 'variant', 'default')) for u in fs.units if u.kind not in ("feed", "product")}
        import re
        for kind, variant in used_symbols:
            sym = self.registry.get(kind, variant)
            svg_str = sym.svg
            sym_id = f"sym_{kind}" if variant == "default" else f"sym_{kind}_{variant}"
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>')+1:svg_str.rfind('</g>')]
                svg_str = f'<symbol id="{sym_id}" viewBox="0 0 {sym.width} {sym.height}">{inner}</symbol>'
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')

        # 2. Draw units using <use> tags or dynamic shapes
        lines.append('  <g id="units">')
        for u in fs.units:
            x, y = u.placement.x, u.placement.y
            safe_name = html.escape(u.name)
            sym = self.registry.get(u.kind, getattr(u, 'variant', 'default'))
            
            if u.kind in ("feed", "product"):
                # Dynamic width based on text with more padding
                if u.width is not None:
                    label_w = u.width
                else:
                    label_w = max(80.0, len(u.name) * 8.0 + 30.0)
                
                if u.kind == "feed":
                    if getattr(u.placement, 'mirrored', False):
                        px0 = x + label_w
                        px1 = x + 15
                        px2 = x
                        points = f"{px0},{y+15} {px1},{y+15} {px2},{y+25} {px1},{y+35} {px0},{y+35}"
                        tx = x + 15 + (label_w - 15) / 2
                    else:
                        # Arrow pointing right, ending at x+50 (where the port is)
                        px0 = x + 50 - label_w
                        px1 = x + 50 - 15
                        px2 = x + 50
                        points = f"{px0},{y+15} {px1},{y+15} {px2},{y+25} {px1},{y+35} {px0},{y+35}"
                        tx = px0 + (label_w - 15) / 2
                    
                    lines.append(f'    <polygon points="{points}" fill="transparent" stroke="black" stroke-width="2" />')
                    lines.append(f'    <text x="{tx}" y="{y+25}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
                else: # product
                    if getattr(u.placement, 'mirrored', False):
                        # Arrow pointing left, starting at x + label_w (where the port is)
                        px0 = x + label_w
                        px1 = x + 15
                        px2 = x
                        # Flat right edge, pointed left edge
                        points = f"{px0},{y+15} {px1},{y+15} {px2},{y+25} {px1},{y+35} {px0},{y+35}"
                        tx = x + 15 + (label_w - 15) / 2
                    else:
                        # Arrow pointing right, starting at x (where the port is)
                        px0 = x
                        px1 = x + label_w - 15
                        px2 = x + label_w
                        # Flat left edge, pointed right edge
                        points = f"{px0},{y+15} {px1},{y+15} {px2},{y+25} {px1},{y+35} {px0},{y+35}"
                        tx = px0 + (label_w - 15) / 2
                        
                    lines.append(f'    <polygon points="{points}" fill="transparent" stroke="black" stroke-width="2" />')
                    # Inline text
                    lines.append(f'    <text x="{tx}" y="{y+25}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            else:
                variant = getattr(u, 'variant', 'default')
                sym_id = f"sym_{u.kind}" if variant == "default" else f"sym_{u.kind}_{variant}"
                u_width = u.width if u.width is not None else sym.width
                u_height = u.height if u.height is not None else sym.height
                
                transform = ""
                if getattr(u.placement, 'mirrored', False):
                    transform = f' transform="translate({2 * x + u_width}, 0) scale(-1, 1)"'
                    
                lines.append(f'    <use href="#{sym_id}" x="{x}" y="{y}" width="{u_width}" height="{u_height}"{transform} />')
                lpos = getattr(u, 'label_pos', None) or sym.label_pos or "top"
                if lpos == "bottom":
                    lx, ly = x + u_width / 2, y + u_height + 15
                    anchor, baseline = "middle", "middle"
                elif lpos == "left":
                    lx, ly = x - 10, y + u_height / 2
                    anchor, baseline = "end", "middle"
                elif lpos == "right":
                    lx, ly = x + u_width + 10, y + u_height / 2
                    anchor, baseline = "start", "middle"
                elif lpos == "center":
                    lx, ly = x + u_width / 2, y + u_height / 2
                    anchor, baseline = "middle", "middle"
                else: # top
                    lx, ly = x + u_width / 2, y - 10
                    anchor, baseline = "middle", "baseline"
                
                lines.append(f'    <text x="{lx}" y="{ly}" font-family="sans-serif" '
                             f'font-size="12" text-anchor="{anchor}" dominant-baseline="{baseline}">{safe_name}</text>')
        lines.append('  </g>')

        # Pre-compute stream point geometries for crossings and labels
        stream_geoms = []
        horizontals = []
        verticals = []

        for s in fs.streams:
            src_u = s.source.owner
            dst_u = s.dest.owner
            
            src_sym = self.registry.get(src_u.kind, getattr(src_u, 'variant', 'default'))
            dst_sym = self.registry.get(dst_u.kind, getattr(dst_u, 'variant', 'default'))
            
            src_px, src_py = src_sym.ports.get(s.source.name, (src_sym.width / 2, src_sym.height / 2))
            dst_px, dst_py = dst_sym.ports.get(s.dest.name, (dst_sym.width / 2, dst_sym.height / 2))
            
            sx = src_u.placement.x + src_px
            sy = src_u.placement.y + src_py
            dx = dst_u.placement.x + dst_px
            dy = dst_u.placement.y + dst_py
            
            points = [(sx, sy)] + (s.route.waypoints if s.route and s.route.waypoints else []) + [(dx, dy)]
            
            simplified = [points[0]]
            for i in range(1, len(points) - 1):
                p_prev = simplified[-1]
                p_curr = points[i]
                p_next = points[i+1]
                
                # If they are all collinear horizontally or vertically, skip the middle point
                if (p_prev[0] == p_curr[0] == p_next[0]) or (p_prev[1] == p_curr[1] == p_next[1]):
                    continue
                simplified.append(p_curr)
            simplified.append(points[-1])
            points = simplified
            
            stream_geoms.append((s, points))
            
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i+1]
                if y1 == y2: # horizontal
                    horizontals.append((min(x1, x2), max(x1, x2), y1))
                elif x1 == x2: # vertical
                    verticals.append((x1, min(y1, y2), max(y1, y2)))

        lines.append('  <g id="streams">')
        for s_idx, (s, points) in enumerate(stream_geoms):
            color = s.color or "black"
            marker_id = f'arrow_{color.replace("#", "").replace(" ", "_")}'
            
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            elif s.is_recycle:
                dash = ' stroke-dasharray="5,5"'
                
            longest_seg = None
            max_len = -1
            
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i+1]
                l = abs(x2 - x1) + abs(y2 - y1)
                if l > max_len:
                    max_len = l
                    longest_seg = ((x1, y1), (x2, y2))
                    
            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i+1]
                
                if jump_direction == "vertical" and x1 == x2: # Vertical segment
                    crossings = [hy for min_x, max_x, hy in horizontals if min_x < x1 < max_x and min(y1, y2) < hy < max(y1, y2)]
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
            
            mask_id = f"mask_stream_{s_idx}"
            if longest_seg:
                lx1, ly1 = longest_seg[0]
                lx2, ly2 = longest_seg[1]
                mid_x = (lx1 + lx2) / 2
                mid_y = (ly1 + ly2) / 2
                tx = mid_x
                ty = mid_y
                anchor = "middle"
                
                text_len = len(s.name) * 7.5
                rect_width = text_len + 8
                rect_height = 16
                rx = mid_x - rect_width / 2
                ry = mid_y - rect_height / 2
                
                lines.append(f'    <mask id="{mask_id}" maskUnits="userSpaceOnUse" x="0" y="0" width="{canvas_width}" height="{canvas_height}">')
                lines.append(f'      <rect x="0" y="0" width="{canvas_width}" height="{canvas_height}" fill="white" />')
                lines.append(f'      <rect x="{rx}" y="{ry}" width="{rect_width}" height="{rect_height}" fill="black" />')
                lines.append('    </mask>')
            else:
                lines.append(f'    <mask id="{mask_id}" maskUnits="userSpaceOnUse" x="0" y="0" width="{canvas_width}" height="{canvas_height}">')
                lines.append(f'      <rect x="0" y="0" width="{canvas_width}" height="{canvas_height}" fill="white" />')
                lines.append('    </mask>')
                
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash} marker-end="url(#{marker_id})" mask="url(#{mask_id})" />'
            )
            
            if longest_seg:
                lines.append(
                    f'    <text x="{tx}" y="{ty}" font-family="sans-serif" font-size="10" '
                    f'text-anchor="{anchor}" dominant-baseline="middle" '
                    f'fill="{color}">{html.escape(s.name)}</text>'
                )

        lines.append('  </g>')
        
        if table_lines:
            lines.extend(table_lines)
            
        lines.append('</svg>')
        svg_str = "\n".join(lines)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg_str)
        return svg_str
