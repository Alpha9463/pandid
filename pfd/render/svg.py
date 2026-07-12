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

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical", show_stream_table: bool = False, styling: str = "default", page_size: str = "A3", **opts) -> str:
        """Render the flowsheet to SVG.

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
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

        # 1. Content bounding box — union of every unit's (dynamic) symbol box
        #    and every route waypoint. The canvas is framed to exactly this, so
        #    there is no wasted margin and the output aspect always matches the
        #    drawing (no letterboxing).
        from pfd.portgeom import unit_box
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            min_x = min(min_x, bx0)
            min_y = min(min_y, by0)
            max_x = max(max_x, bx1)
            max_y = max(max_y, by1)
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    min_x = min(min_x, px)
                    min_y = min(min_y, py)
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)

        if not fs.units:  # empty flowsheet: fall back to the nominal page size
            page_w, page_h = _PAGE_SIZES.get(page_size.upper(), _PAGE_SIZES["A3"])
            min_x = min_y = 0.0
            max_x, max_y = page_w, page_h

        # Margin absorbs unit labels (drawn just outside the symbol box) and arrowheads.
        margin = 55.0
        frame_x = min_x - margin
        frame_y = min_y - margin
        canvas_width = (max_x - min_x) + 2 * margin
        canvas_height = (max_y - min_y) + 2 * margin

        # 2. Optional stream-property table, placed directly below the diagram.
        table_lines = []
        if show_stream_table and fs.streams:
            table_left = frame_x + 25
            table_y_start = frame_y + canvas_height + 10

            keys = set()
            for s in fs.streams:
                keys.update(s.properties.keys())
            sorted_keys = sorted(keys)

            headers = ["Stream"] + [s.name for s in fs.streams]
            n_streams = len(fs.streams)
            if n_streams > 20:
                stream_col_w = max(35, int(canvas_width / (n_streams + 2)))
                font_size = max(8, min(12, int(stream_col_w / 5)))
                row_height = max(20, font_size + 12)
            else:
                stream_col_w = max(60, max((len(s.name) * 8 for s in fs.streams), default=60))
                font_size = 12
                row_height = 30

            col_widths = [100] + [stream_col_w] * n_streams
            table_width = sum(col_widths)

            table_lines.append('  <g id="stream_table">')
            cx = table_left
            for i, h in enumerate(headers):
                table_lines.append(f'    <rect x="{cx}" y="{table_y_start}" width="{col_widths[i]}" height="{row_height}" fill="#eee" stroke="black" />')
                table_lines.append(f'    <text x="{cx + col_widths[i]/2}" y="{table_y_start + row_height/2}" font-family="sans-serif" font-size="{font_size}" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{html.escape(h)}</text>')
                cx += col_widths[i]

            current_y = table_y_start + row_height
            for k in sorted_keys:
                cx = table_left
                table_lines.append(f'    <rect x="{cx}" y="{current_y}" width="{col_widths[0]}" height="{row_height}" fill="#f9f9f9" stroke="black" />')
                table_lines.append(f'    <text x="{cx + col_widths[0]/2}" y="{current_y + row_height/2}" font-family="sans-serif" font-size="{font_size}" font-weight="bold" text-anchor="middle" dominant-baseline="middle">{html.escape(k)}</text>')
                cx += col_widths[0]
                for i, s in enumerate(fs.streams):
                    val = str(s.properties.get(k, "-"))
                    cw = col_widths[i + 1]
                    table_lines.append(f'    <rect x="{cx}" y="{current_y}" width="{cw}" height="{row_height}" fill="white" stroke="black" />')
                    table_lines.append(f'    <text x="{cx + cw/2}" y="{current_y + row_height/2}" font-family="sans-serif" font-size="{font_size}" text-anchor="middle" dominant-baseline="middle">{html.escape(val)}</text>')
                    cx += cw
                current_y += row_height

            table_lines.append('  </g>')
            # Grow the canvas to include the table. The bottom inset matches the
            # P&ID border inset (25) so the table sits flush in the sheet corner
            # instead of floating a few px above the border.
            canvas_width = max(canvas_width, (table_left - frame_x) + table_width + 25)
            canvas_height = (current_y - frame_y) + 25

        # 3. Optional P&ID sheet border + title block + revision history.
        pid_lines = []
        if styling == "pid":
            border_margin = 25
            pid_lines.append('  <g id="pid_styling">')
            pid_lines.append(f'    <rect x="{frame_x + border_margin}" y="{frame_y + border_margin}" width="{canvas_width - 2 * border_margin}" height="{canvas_height - 2 * border_margin}" fill="none" stroke="black" stroke-width="4" />')
            pid_lines.extend(self._title_block(fs, frame_x, frame_y, canvas_width,
                                               canvas_height, border_margin))
            pid_lines.append('  </g>')

        # 4. SVG document. width/height in px equal the viewBox, so it never
        #    letterboxes regardless of the diagram's aspect ratio.
        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{canvas_width:.0f}" height="{canvas_height:.0f}" '
            f'viewBox="{frame_x:.1f} {frame_y:.1f} {canvas_width:.1f} {canvas_height:.1f}">'
        )
        lines.append('  <!-- Background -->')
        lines.append(f'  <rect x="{frame_x:.1f}" y="{frame_y:.1f}" width="{canvas_width:.1f}" height="{canvas_height:.1f}" fill="white" />')
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
            f = u.frame
            x, y = f.x, f.y
            safe_name = html.escape(u.name)
            sym = self.registry.get(u.kind, getattr(u, 'variant', 'default'))

            if u.kind in ("feed", "product"):
                label_w = f.w

                if u.kind == "feed":
                    if f.mirrored:
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
                    if f.mirrored:
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
                u_width = f.w
                u_height = f.h

                transform = ""
                if f.mirrored:
                    transform = f' transform="translate({2 * x + u_width}, 0) scale(-1, 1)"'
                    
                lines.append(f'    <use href="#{sym_id}" x="{x}" y="{y}" width="{u_width}" height="{u_height}"{transform} />')
                if u.kind == "instrument":
                    # ISA tag inside the balloon: functional letters over loop no.
                    name = u.name
                    if "-" in name:
                        top, bot = name.split("-", 1)
                    else:
                        i = len(name)
                        while i > 0 and name[i-1].isdigit():
                            i -= 1
                        top, bot = name[:i], name[i:]
                    cx, cy = x + u_width / 2, y + u_height / 2
                    lines.append(f'    <text x="{cx}" y="{cy - 4}" font-family="sans-serif" '
                                 f'font-size="12" font-weight="bold" text-anchor="middle" '
                                 f'dominant-baseline="middle">{html.escape(top.upper())}</text>')
                    if bot:
                        lines.append(f'    <text x="{cx}" y="{cy + 10}" font-family="sans-serif" '
                                     f'font-size="11" text-anchor="middle" '
                                     f'dominant-baseline="middle">{html.escape(bot)}</text>')
                else:
                    lpos = f.label_pos or "top"
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

        from pfd.portgeom import port_point
        for s in fs.streams:
            src_u = s.source.owner
            dst_u = s.dest.owner

            # Endpoints via the shared resolver so the drawn line lands on the
            # same port face the router used (mirror flip applied consistently).
            sx, sy = port_point(src_u, src_u.frame, s.source.name)
            dx, dy = port_point(dst_u, dst_u.frame, s.dest.name)

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
            
            # ISA-5.1 signal line styles: electrical dashed, software/data long
            # dash-dot, capillary evenly dashed. Pneumatic (double-slash ticks)
            # is drawn separately below.
            _SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                            "capillary": "3,3"}
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            elif s.kind in _SIGNAL_DASH:
                dash = f' stroke-dasharray="{_SIGNAL_DASH[s.kind]}"'

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
                
                lines.append(f'    <mask id="{mask_id}" maskUnits="userSpaceOnUse" x="{frame_x}" y="{frame_y}" width="{canvas_width}" height="{canvas_height}">')
                lines.append(f'      <rect x="{frame_x}" y="{frame_y}" width="{canvas_width}" height="{canvas_height}" fill="white" />')
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

            # Pneumatic signal: double-slash ticks along each segment (ISA-5.1).
            if s.kind == "pneumatic":
                for i in range(len(points) - 1):
                    (px1, py1), (px2, py2) = points[i], points[i+1]
                    seglen = abs(px2 - px1) + abs(py2 - py1)
                    n = int(seglen // 45)
                    horiz = abs(py1 - py2) < 0.1
                    for k in range(1, n + 1):
                        t = k / (n + 1)
                        mx, my = px1 + (px2 - px1) * t, py1 + (py2 - py1) * t
                        for off in (-2.5, 1.5):
                            if horiz:
                                lines.append(f'    <line x1="{mx+off-3:.1f}" y1="{my+5:.1f}" '
                                             f'x2="{mx+off+3:.1f}" y2="{my-5:.1f}" stroke="{color}" stroke-width="1.5" />')
                            else:
                                lines.append(f'    <line x1="{mx-5:.1f}" y1="{my+off-3:.1f}" '
                                             f'x2="{mx+5:.1f}" y2="{my+off+3:.1f}" stroke="{color}" stroke-width="1.5" />')

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
        return "\n".join(lines)

    def _title_block(self, fs, frame_x, frame_y, canvas_width, canvas_height, border_margin):
        """Draw a standard P&ID title block (+ revision history) bottom-right."""
        from pfd.document import TitleBlock
        tb = fs.title_block or TitleBlock()
        title = tb.title or fs.name
        date = tb.date or datetime.datetime.now().strftime("%Y-%m-%d")

        L = []
        tb_w = 380.0
        row = 26.0
        tb_h = row * 4  # title / dwg-rev-sheet / drawn-chk-app / project-scale-date
        tb_x = frame_x + canvas_width - border_margin - tb_w
        tb_y = frame_y + canvas_height - border_margin - tb_h
        c2, c3 = tb_x + tb_w * 0.5, tb_x + tb_w * 0.75

        L.append(f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="{tb_h}" fill="white" stroke="black" stroke-width="2"/>')
        for k in (1, 2, 3):
            L.append(f'<line x1="{tb_x}" y1="{tb_y + row*k}" x2="{tb_x + tb_w}" y2="{tb_y + row*k}" stroke="black" stroke-width="1"/>')
        for cx in (c2, c3):
            L.append(f'<line x1="{cx}" y1="{tb_y + row}" x2="{cx}" y2="{tb_y + tb_h}" stroke="black" stroke-width="1"/>')

        def cell(x, ytop, label, value, big=False):
            e = html.escape
            size = 13 if big else 11
            wt = ' font-weight="bold"' if big else ''
            return (f'<text x="{x + 8}" y="{ytop + 10}" font-family="sans-serif" font-size="7" '
                    f'fill="#666">{e(label)}</text>'
                    f'<text x="{x + 8}" y="{ytop + 21}" font-family="sans-serif" font-size="{size}"{wt}>{e(str(value))}</text>')

        rev = tb.revisions[-1].rev if tb.revisions else "0"
        L.append(f'<text x="{tb_x + 10}" y="{tb_y + 18}" font-family="sans-serif" font-size="14" font-weight="bold">{html.escape(title)}</text>')
        L.append(cell(tb_x, tb_y + row, "DWG No.", tb.drawing_number or "—", big=True))
        L.append(cell(c2, tb_y + row, "REV", rev, big=True))
        L.append(cell(c3, tb_y + row, "SHEET", f"{tb.sheet} of {tb.of_sheets}"))
        L.append(cell(tb_x, tb_y + 2 * row, "DRAWN", tb.drawn_by or "—"))
        L.append(cell(c2, tb_y + 2 * row, "CHK'D", tb.checked_by or "—"))
        L.append(cell(c3, tb_y + 2 * row, "APP'D", tb.approved_by or "—"))
        L.append(cell(tb_x, tb_y + 3 * row, "PROJECT", tb.project or fs.name))
        L.append(cell(c2, tb_y + 3 * row, "SCALE", tb.scale))
        L.append(cell(c3, tb_y + 3 * row, "DATE", date))

        # Revision history table, stacked directly above the title block.
        if tb.revisions:
            rh = 16.0
            rt_h = (len(tb.revisions) + 1) * rh
            rt_y = tb_y - rt_h
            cols = [tb_x, tb_x + 36, tb_x + 102, tb_x + tb_w - 46, tb_x + tb_w]
            L.append(f'<rect x="{tb_x}" y="{rt_y}" width="{tb_w}" height="{rt_h}" fill="white" stroke="black" stroke-width="1"/>')
            for cx in cols[1:-1]:
                L.append(f'<line x1="{cx}" y1="{rt_y}" x2="{cx}" y2="{rt_y + rt_h}" stroke="black" stroke-width="0.5"/>')

            def rowcells(y, vals, bold=False):
                wt = ' font-weight="bold"' if bold else ''
                for ci, v in enumerate(vals):
                    L.append(f'<text x="{cols[ci] + 4}" y="{y + 11}" font-family="sans-serif" '
                             f'font-size="8"{wt}>{html.escape(str(v))}</text>')

            rowcells(rt_y, ["REV", "DATE", "DESCRIPTION", "BY"], bold=True)
            yy = rt_y + rh
            for rv in tb.revisions:
                L.append(f'<line x1="{tb_x}" y1="{yy}" x2="{tb_x + tb_w}" y2="{yy}" stroke="black" stroke-width="0.5"/>')
                rowcells(yy, [rv.rev, rv.date, rv.description, rv.by])
                yy += rh

        return ["    " + item for item in L]
