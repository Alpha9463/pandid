"""SVG rendering backend."""

from typing import TYPE_CHECKING
import html
import re
from datetime import datetime

from pfd.render import furniture as F

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

_SIGNAL_KINDS = {"electric", "pneumatic", "data", "capillary", "software"}

# Standard page sizes in landscape orientation (mm → px at 96 dpi).
_PAGE_SIZES = {
    "A4": (1122.0, 793.7),
    "A3": (1587.4, 1122.0),
    "A2": (2245.0, 1587.4),
    "A1": (3174.8, 2245.0),
    "A0": (4489.1, 3174.8),
}


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
        from pfd.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical",
               show_stream_table: bool = False, styling: str = "default",
               page_size: str = "A3", **opts) -> str:
        """Render the flowsheet to SVG.

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
        jump_direction : str
            Which crossing lines get a semicircle bump: ``"vertical"`` or ``"horizontal"``.
        show_stream_table : bool
            Whether to render a stream property table on the sheet.
        styling : str
            ``"default"`` for plain, ``"pid"`` for the engineering title strip,
            zone-ruled border, and any docked furniture boxes.
        page_size : str
            Standard paper size: ``"A4"``, ``"A3"`` (default), ``"A2"``, ``"A1"``, ``"A0"``.
        """
        from pfd.portgeom import unit_box
        pid = styling == "pid"

        # 1. Diagram bounding box — union of every unit's drawn box and every
        #    route waypoint. Furniture is placed *around* this fixed region.
        dx0 = dy0 = float("inf")
        dx1 = dy1 = float("-inf")
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            dx0, dy0 = min(dx0, bx0), min(dy0, by0)
            dx1, dy1 = max(dx1, bx1), max(dy1, by1)
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    dx0, dy0 = min(dx0, px), min(dy0, py)
                    dx1, dy1 = max(dx1, px), max(dy1, py)
        if not fs.units:  # empty flowsheet: fall back to the nominal page size
            page_w, page_h = _PAGE_SIZES.get(page_size.upper(), _PAGE_SIZES["A3"])
            dx0 = dy0 = 0.0
            dx1, dy1 = page_w, page_h

        # 2. Which streams get a table column (unique material streams only).
        table_streams = self._table_streams(fs) if show_stream_table else []
        st_layout = self._stream_table_layout(fs, table_streams) if table_streams else None

        # 3. Place furniture around the diagram and size the sheet.
        margin = 55.0
        furniture: list[str] = []
        # union of everything drawn (diagram + furniture), grown as boxes land
        U = [dx0, dy0, dx1, dy1]

        def grow(x0, y0, x1, y1):
            U[0], U[1] = min(U[0], x0), min(U[1], y0)
            U[2], U[3] = max(U[2], x1), max(U[3], y1)

        if pid:
            frame_x, frame_y, canvas_width, canvas_height = self._place_pid(
                fs, st_layout, dx0, dy0, dx1, dy1, furniture, U, grow)
        else:
            # Plain sheet: optional stream table docked below the diagram, left.
            if st_layout:
                top = dy1 + 24
                furniture.extend(self._draw_stream_table(st_layout, dx0, top))
                grow(dx0, top, dx0 + st_layout["w"], top + st_layout["h"])
            frame_x, frame_y = U[0] - margin, U[1] - margin
            canvas_width = (U[2] - U[0]) + 2 * margin
            canvas_height = (U[3] - U[1]) + 2 * margin

        # 4. SVG document.
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{canvas_width:.0f}" height="{canvas_height:.0f}" '
            f'viewBox="{frame_x:.1f} {frame_y:.1f} {canvas_width:.1f} {canvas_height:.1f}">'
        )
        lines.append('  <!-- Background -->')
        lines.append(f'  <rect x="{frame_x:.1f}" y="{frame_y:.1f}" width="{canvas_width:.1f}" height="{canvas_height:.1f}" fill="white" />')

        # Furniture (border + title strip + boxes) sits behind the diagram.
        for item in furniture:
            lines.append("    " + item)

        lines.extend(self._defs(fs))
        lines.extend(self._draw_units(fs))
        lines.extend(self._draw_streams(fs, jump_direction))
        lines.append('</svg>')
        return "\n".join(lines)

    # ------------------------------------------------------------------ furniture

    def _place_pid(self, fs, st_layout, dx0, dy0, dx1, dy1, furniture, U, grow):
        """Dock the title strip, stream table, and annotation boxes to the sheet
        corners; draw the zone border. Returns the final canvas rect."""
        from pfd.document import TitleBlock, TableBox

        GAP, PAD, OUT = 16.0, 14.0, 8.0

        anns = list(getattr(fs, "annotations", []) or [])
        by_anchor: dict[str, list] = {}
        for a in anns:
            size = F.measure_table(a) if isinstance(a, TableBox) else F.measure_annotation(a)
            by_anchor.setdefault(a.anchor, []).append((a, size[0], size[1]))

        def draw_box(a, x, y):
            if isinstance(a, TableBox):
                furniture.extend(F.draw_table(a, x, y))
            else:
                furniture.extend(F.draw_annotation(a, x, y))

        # --- top band: stacks grow upward from just above the diagram ---
        for anchor, right in (("top-right", dx1), ("top-left", None)):
            y = dy0 - GAP
            for a, w, h in by_anchor.get(anchor, []):
                x = (right - w) if right is not None else dx0
                draw_box(a, x, y - h)
                grow(x, y - h, x + w, y)
                y -= h + GAP

        # --- bottom band: annotations, then title strip (right) / table (left) ---
        tb = fs.title_block or TitleBlock()
        ts_w, ts_h = F.measure_title_strip(tb)
        date = tb.date or datetime.now().strftime("%Y-%m-%d")
        name = tb.title or fs.name

        # right column top→bottom: bottom-right boxes, then title strip
        y = dy1 + GAP
        for a, w, h in by_anchor.get("bottom-right", []):
            x = dx1 - w
            draw_box(a, x, y)
            grow(x, y, x + w, y + h)
            y += h + GAP
        furniture.extend(F.draw_title_strip(tb, name, date, dx1, y + ts_h))
        grow(dx1 - ts_w, y, dx1, y + ts_h)

        # left column top→bottom: bottom-left boxes, then stream table
        y = dy1 + GAP
        for a, w, h in by_anchor.get("bottom-left", []):
            draw_box(a, dx0, y)
            grow(dx0, y, dx0 + w, y + h)
            y += h + GAP
        if st_layout:
            furniture.extend(self._draw_stream_table(st_layout, dx0, y))
            grow(dx0, y, dx0 + st_layout["w"], y + st_layout["h"])

        # --- zone-ruled border around the grown union, then the sheet edge ---
        inner_x, inner_y = U[0] - PAD, U[1] - PAD
        inner_w, inner_h = (U[2] - U[0]) + 2 * PAD, (U[3] - U[1]) + 2 * PAD
        frame_lines, (ox, oy, ow, oh) = F.zone_frame(inner_x, inner_y, inner_w, inner_h)
        furniture[:0] = frame_lines  # border sits behind the boxes
        return ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT

    def _table_streams(self, fs):
        streams, seen = [], set()
        for s in fs.streams:
            if s.kind in _SIGNAL_KINDS or s.name in seen:
                continue
            seen.add(s.name)
            streams.append(s)
        return streams

    def _stream_table_layout(self, fs, streams):
        # property rows in first-seen order (dict preserves insertion order)
        order, seen = [], set()
        for s in streams:
            for k in s.properties:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
        sec_before: dict[str, str] = {}
        for key, label in (getattr(fs, "stream_table_sections", []) or []):
            sec_before.setdefault(key, label)

        n = len(streams)
        size = 10.5 if n <= 18 else max(8.0, 190.0 / n)
        row_h = 20.0 if n <= 18 else max(15.0, size + 5)
        label_w = 122.0
        name_w = max(52.0, max((F.text_width(s.name, size, bold=True)
                                for s in streams), default=52.0) + 14)
        disp = []  # ('section', label) | ('data', key)
        for k in order:
            if k in sec_before:
                disp.append(("section", sec_before[k]))
            disp.append(("data", k))
        return dict(streams=streams, disp=disp, size=size, row_h=row_h,
                    label_w=label_w, name_w=name_w,
                    w=label_w + name_w * n, h=row_h * (1 + len(disp)))

    def _draw_stream_table(self, L, left, top):
        streams = L["streams"]
        size, row_h, label_w, name_w = L["size"], L["row_h"], L["label_w"], L["name_w"]
        out = ['<g id="stream_table">']

        def cell(x, y, w, text, *, fill, bold=False, anchor="middle"):
            out.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{row_h:.1f}" '
                       f'fill="{fill}" stroke="black" stroke-width="0.75"/>')
            if anchor == "start":
                tx = x + 5
            elif anchor == "end":
                tx = x + w - 5
            else:
                tx = x + w / 2
            wt = ' font-weight="bold"' if bold else ''
            out.append(f'  <text x="{tx:.1f}" y="{y + row_h / 2 + size / 3:.1f}" '
                       f'font-family="{F.FONT}" font-size="{size:.1f}"{wt} '
                       f'text-anchor="{anchor}">{html.escape(str(text))}</text>')

        # header row: "Stream Number" + each stream name
        y = top
        cell(left, y, label_w, "Stream Number", fill="#eee", bold=True, anchor="start")
        cx = left + label_w
        for s in streams:
            cell(cx, y, name_w, s.name, fill="#eee", bold=True)
            cx += name_w
        y += row_h
        for kind, key in L["disp"]:
            if kind == "section":
                cell(left, y, label_w + name_w * len(streams), key,
                     fill="#f4f4f4", bold=True, anchor="start")
                y += row_h
                continue
            cell(left, y, label_w, key, fill="#f9f9f9", bold=True, anchor="start")
            cx = left + label_w
            for s in streams:
                val = s.properties.get(key, "-")
                cell(cx, y, name_w, "-" if val in (None, "") else val, fill="white")
                cx += name_w
            y += row_h
        out.append('</g>')
        return out

    # ------------------------------------------------------------------ defs

    def _defs(self, fs):
        lines = []
        used_colors = {s.color or "black" for s in fs.streams}
        lines.append('  <defs>')
        for c in used_colors:
            marker_id = f'arrow_{c.replace("#", "").replace(" ", "_")}'
            lines.append(
                f'    <marker id="{marker_id}" viewBox="0 0 10 10" refX="10" refY="5" '
                f'markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{c}" />')
            lines.append('    </marker>')

        used_symbols = {(u.kind, getattr(u, 'variant', 'default'))
                        for u in fs.units if u.kind not in ("feed", "product")}
        for kind, variant in used_symbols:
            sym = self.registry.get(kind, variant)
            svg_str = sym.svg
            sym_id = f"sym_{kind}" if variant == "default" else f"sym_{kind}_{variant}"
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                svg_str = f'<symbol id="{sym_id}" viewBox="0 0 {sym.width} {sym.height}">{inner}</symbol>'
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')
        return lines

    # ------------------------------------------------------------------ units

    def _draw_units(self, fs):
        lines = ['  <g id="units">']
        for u in fs.units:
            f = u.frame
            x, y = f.x, f.y
            safe_name = html.escape(u.name)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, x, y, safe_name))
                continue

            variant = getattr(u, 'variant', 'default')
            sym_id = f"sym_{u.kind}" if variant == "default" else f"sym_{u.kind}_{variant}"
            u_width, u_height = f.w, f.h
            transform = ""
            if f.mirrored:
                transform = f' transform="translate({2 * x + u_width}, 0) scale(-1, 1)"'
            lines.append(f'    <use href="#{sym_id}" x="{x}" y="{y}" width="{u_width}" height="{u_height}"{transform} />')

            if u.kind == "instrument":
                lines.extend(self._draw_instrument_tag(u, x, y, u_width, u_height))
            else:
                lines.append(self._draw_unit_label(u, f, x, y, u_width, u_height, safe_name))
        lines.append('  </g>')
        return lines

    def _draw_boundary(self, u, f, x, y, safe_name):
        """Feed / Product off-page connector flag, with an optional second line
        referencing the drawing the stream comes from / goes to."""
        label_w = f.w
        ref = getattr(u, "reference", "") or ""
        if u.kind == "feed":
            if f.mirrored:
                px0, px1, px2 = x + label_w, x + 15, x
                tx = x + 15 + (label_w - 15) / 2
            else:
                px0, px1, px2 = x + 50 - label_w, x + 50 - 15, x + 50
                tx = px0 + (label_w - 15) / 2
        else:  # product
            if f.mirrored:
                px0, px1, px2 = x + label_w, x + 15, x
                tx = x + 15 + (label_w - 15) / 2
            else:
                px0, px1, px2 = x, x + label_w - 15, x + label_w
                tx = px0 + (label_w - 15) / 2
        # slightly taller flag so two lines of text fit, centered on the port (y+25)
        top, bot = (y + 12, y + 38) if ref else (y + 15, y + 35)
        points = f"{px0},{top} {px1},{top} {px2},{y + 25} {px1},{bot} {px0},{bot}"
        out = [f'    <polygon points="{points}" fill="transparent" stroke="black" stroke-width="2" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{y + 21}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{y + 33}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{html.escape(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{y + 25}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        name = u.name
        if "-" in name:
            top, bot = name.split("-", 1)
        else:
            i = 0
            while i < len(name) and not name[i].isdigit():
                i += 1
            top, bot = name[:i], name[i:]
        cx, cy = x + u_width / 2, y + u_height / 2
        out = [f'    <text x="{cx}" y="{cy - 4}" font-family="sans-serif" '
               f'font-size="12" font-weight="bold" text-anchor="middle" '
               f'dominant-baseline="middle">{html.escape(top.upper())}</text>']
        if bot:
            out.append(f'    <text x="{cx}" y="{cy + 10}" font-family="sans-serif" '
                       f'font-size="11" text-anchor="middle" '
                       f'dominant-baseline="middle">{html.escape(bot)}</text>')
        return out

    def _draw_unit_label(self, u, f, x, y, u_width, u_height, safe_name):
        lpos = f.label_pos or "top"
        if lpos == "bottom":
            lx, ly, anchor, baseline = x + u_width / 2, y + u_height + 15, "middle", "middle"
        elif lpos == "left":
            lx, ly, anchor, baseline = x - 10, y + u_height / 2, "end", "middle"
        elif lpos == "right":
            lx, ly, anchor, baseline = x + u_width + 10, y + u_height / 2, "start", "middle"
        elif lpos == "center":
            lx, ly, anchor, baseline = x + u_width / 2, y + u_height / 2, "middle", "middle"
        else:  # top
            lx, ly, anchor, baseline = x + u_width / 2, y - 10, "middle", "baseline"
        return (f'    <text x="{lx}" y="{ly}" font-family="sans-serif" '
                f'font-size="12" text-anchor="{anchor}" dominant-baseline="{baseline}">{safe_name}</text>')

    # ------------------------------------------------------------------ streams

    def _draw_streams(self, fs, jump_direction):
        from pfd.portgeom import port_point

        stream_geoms, horizontals, verticals = [], [], []
        for s in fs.streams:
            src_u, dst_u = s.source.owner, s.dest.owner
            sx, sy = port_point(src_u, src_u.frame, s.source.name)
            dx, dy = port_point(dst_u, dst_u.frame, s.dest.name)
            points = [(sx, sy)] + (s.route.waypoints if s.route and s.route.waypoints else []) + [(dx, dy)]

            simplified = [points[0]]
            for i in range(1, len(points) - 1):
                p_prev, p_curr, p_next = simplified[-1], points[i], points[i + 1]
                if (p_prev[0] == p_curr[0] == p_next[0]) or (p_prev[1] == p_curr[1] == p_next[1]):
                    continue
                simplified.append(p_curr)
            simplified.append(points[-1])
            points = simplified
            stream_geoms.append((s, points))
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if y1 == y2:
                    horizontals.append((min(x1, x2), max(x1, x2), y1))
                elif x1 == x2:
                    verticals.append((x1, min(y1, y2), max(y1, y2)))

        lines = ['  <g id="streams">']
        labeled_names: set = set()
        label_items: list = []   # (tx, ty, name, color) — drawn last, over every line
        _SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                        "capillary": "3,3"}
        for s, points in stream_geoms:
            color = s.color or "black"
            marker_id = f'arrow_{color.replace("#", "").replace(" ", "_")}'
            is_signal = s.kind in _SIGNAL_KINDS
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            elif s.kind in _SIGNAL_DASH:
                dash = f' stroke-dasharray="{_SIGNAL_DASH[s.kind]}"'

            longest_seg, max_len = None, -1
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                seg = abs(x2 - x1) + abs(y2 - y1)
                if seg > max_len:
                    max_len, longest_seg = seg, ((x1, y1), (x2, y2))

            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if jump_direction == "vertical" and x1 == x2:
                    crossings = [hy for mnx, mxx, hy in horizontals if mnx < x1 < mxx and min(y1, y2) < hy < max(y1, y2)]
                    crossings.sort(reverse=(y1 > y2))
                    for hy in crossings:
                        if y1 < y2:
                            d_parts.extend([f"L {x1},{hy - 5}", f"A 5 5 0 0 1 {x1},{hy + 5}"])
                        else:
                            d_parts.extend([f"L {x1},{hy + 5}", f"A 5 5 0 0 1 {x1},{hy - 5}"])
                    d_parts.append(f"L {x2},{y2}")
                elif jump_direction == "horizontal" and y1 == y2:
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

            # A stream number is labelled once (on its longest segment); a
            # white halo drawn in a final pass knocks the line out beneath it.
            if bool(longest_seg) and not is_signal and s.name not in labeled_names:
                labeled_names.add(s.name)
                (lx1, ly1), (lx2, ly2) = longest_seg
                label_items.append(((lx1 + lx2) / 2, (ly1 + ly2) / 2, s.name, color))

            marker = "" if is_signal else f' marker-end="url(#{marker_id})"'
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash}{marker} />'
            )

            if s.kind == "pneumatic":
                for i in range(len(points) - 1):
                    (px1, py1), (px2, py2) = points[i], points[i + 1]
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

        # Final pass: stream-number labels, each on a white halo so it reads
        # cleanly over its own line and any line that crosses beneath it.
        for tx, ty, name, color in label_items:
            hw, hh = len(name) * 6.2 + 6, 13.0
            lines.append(f'    <rect x="{tx - hw / 2:.1f}" y="{ty - hh / 2:.1f}" '
                         f'width="{hw:.1f}" height="{hh:.1f}" fill="white" />')
            lines.append(
                f'    <text x="{tx}" y="{ty}" font-family="sans-serif" font-size="10" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{color}">{html.escape(name)}</text>'
            )
        lines.append('  </g>')
        return lines
