#!/usr/bin/env python3
"""Convert draw.io / mxGraph stencil shapes to plain SVG.

mxGraph stencils (jgraph/drawio, Apache-2.0) describe each shape in a small
drawing language: <path> made of <move>/<line>/<quad>/<curve>/<arc>/<close>,
plus <rect>/<roundrect>/<ellipse>/<line>, painted by <fillstroke>/<stroke>/
<fill>. Coordinates are already in the shape's ``w`` × ``h`` space, so they map
straight onto an SVG ``viewBox="0 0 w h"``.

`convert_shape(shape_el)` returns (inner_svg, width, height, constraints) where
constraints is ``{name: (x_abs, y_abs)}`` from the stencil's <connections>.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET


def _endpoint_to_center(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    """SVG endpoint arc parameterization -> (cx, cy, rx, ry, theta1, dtheta).

    Implements the conversion in the SVG 1.1 spec (Appendix F.6.5), used to
    subdivide an arc at a known angle.
    """
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (x1 + x2) / 2.0
    cy = sinp * cxp + cosp * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / n))) if n else 0.0
        return -a if (ux * vy - uy * vx) < 0 else a

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = ang(1.0, 0.0, ux, uy)
    dtheta = ang(ux, uy, vx, vy)
    if not fs and dtheta > 0:
        dtheta -= 2 * math.pi
    if fs and dtheta < 0:
        dtheta += 2 * math.pi
    return cx, cy, rx, ry, theta1, dtheta


def _arc_to_path(x0, y0, rx, ry, phi_deg, fa, fs, x, y):
    """Emit one SVG ``A`` command, subdividing near-degenerate arcs.

    When an arc's chord is ~= its diameter, cairosvg (and some other renderers)
    stroke it noticeably thick. Splitting such an arc into ~<=90 deg segments
    preserves the shape exactly while rendering at a uniform line weight.
    """
    r = min(abs(rx), abs(ry))
    chord = math.hypot(x - x0, y - y0)
    if r <= 0 or chord <= 1.95 * r:  # well-conditioned -> emit verbatim
        return f"A {rx} {ry} {phi_deg} {fa} {fs} {x} {y}"

    phi = math.radians(phi_deg)
    cx, cy, rxx, ryy, th1, dth = _endpoint_to_center(x0, y0, rx, ry, phi, fa, fs, x, y)
    n = max(2, math.ceil(abs(dth) / (math.pi / 2)))
    cosp, sinp = math.cos(phi), math.sin(phi)

    def pt(t):
        return (cx + rxx * math.cos(t) * cosp - ryy * math.sin(t) * sinp,
                cy + rxx * math.cos(t) * sinp + ryy * math.sin(t) * cosp)

    seg = dth / n
    large = 1 if abs(seg) > math.pi else 0
    parts = []
    for i in range(1, n + 1):
        ex, ey = (x, y) if i == n else pt(th1 + seg * i)
        parts.append(f"A {round(rx, 4)} {round(ry, 4)} {phi_deg} {large} {fs} "
                     f"{round(ex, 4)} {round(ey, 4)}")
    return " ".join(parts)

# Paint style for each paint op: (fill, stroke). Monochrome PFD convention —
# outlines are transparent, only explicit <fill> makes a solid black shape.
_PAINT = {
    "fillstroke": ("none", "#111"),
    "stroke": ("none", "#111"),
    "fill": ("#111", "none"),
}


def _num(el, attr, default=0.0):
    return float(el.get(attr, default))


def _path_d(path_el) -> str:
    parts = []
    cx = cy = sx = sy = 0.0  # current point + subpath start (for arc subdivision)
    for c in path_el:
        t = c.tag
        if t == "move":
            cx, cy = _num(c, "x"), _num(c, "y")
            sx, sy = cx, cy
            parts.append(f"M {cx} {cy}")
        elif t == "line":
            cx, cy = _num(c, "x"), _num(c, "y")
            parts.append(f"L {cx} {cy}")
        elif t == "quad":
            parts.append(f"Q {_num(c,'x1')} {_num(c,'y1')} {_num(c,'x2')} {_num(c,'y2')}")
            cx, cy = _num(c, "x2"), _num(c, "y2")
        elif t == "curve":
            parts.append(f"C {_num(c,'x1')} {_num(c,'y1')} {_num(c,'x2')} {_num(c,'y2')} "
                         f"{_num(c,'x3')} {_num(c,'y3')}")
            cx, cy = _num(c, "x3"), _num(c, "y3")
        elif t == "arc":
            large = int(c.get("large-arc-flag", "0"))
            sweep = int(c.get("sweep-flag", "0"))
            x, y = _num(c, "x"), _num(c, "y")
            parts.append(_arc_to_path(cx, cy, _num(c, "rx"), _num(c, "ry"),
                                      _num(c, "x-axis-rotation"), large, sweep, x, y))
            cx, cy = x, y
        elif t == "close":
            parts.append("Z")
            cx, cy = sx, sy
    return " ".join(parts)


def convert_shape(shape_el, stroke_width=2.0):
    """Convert one <shape> element to (inner_svg, w, h, constraints).

    ``stroke_width`` is emitted verbatim on every stroked element (in the
    shape's own units). At a symbol's native scale this equals the sheet's line
    weight; for a symbol later scaled by ``s``, pass ``stroke_width = 2 / s`` so
    the rendered line still lands at 2px.
    """
    w = _num(shape_el, "w", 100)
    h = _num(shape_el, "h", 100)

    constraints = {}
    conns = shape_el.find("connections")
    if conns is not None:
        for c in conns.findall("constraint"):
            name = c.get("name") or f"c{len(constraints)}"
            constraints[name] = (round(_num(c, "x") * w, 2), round(_num(c, "y") * h, 2))

    out = []
    pending = []   # geometry accumulated since the last paint op

    def flush(op):
        nonlocal pending
        if not pending:
            return
        fill, stroke = _PAINT.get(op, ("none", "#111"))
        sw = f' stroke-width="{stroke_width}"' if stroke != "none" else ""
        for kind, data in pending:
            if kind == "path":
                out.append(f'<path d="{data}" fill="{fill}" stroke="{stroke}"{sw}/>')
            elif kind == "rect":
                x, y, rw, rh = data
                out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" '
                           f'fill="{fill}" stroke="{stroke}"{sw}/>')
            elif kind == "rrect":
                x, y, rw, rh, r = data
                out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" rx="{r}" '
                           f'fill="{fill}" stroke="{stroke}"{sw}/>')
            elif kind == "ellipse":
                x, y, rw, rh = data
                out.append(f'<ellipse cx="{x+rw/2}" cy="{y+rh/2}" rx="{rw/2}" ry="{rh/2}" '
                           f'fill="{fill}" stroke="{stroke}"{sw}/>')
            elif kind == "line":
                x1, y1, x2, y2 = data
                out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                           f'stroke="{stroke}"{sw}/>')
        pending = []

    for section in ("background", "foreground"):
        sec = shape_el.find(section)
        if sec is None:
            continue
        for el in sec:
            t = el.tag
            if t == "path":
                pending.append(("path", _path_d(el)))
            elif t == "rect":
                pending.append(("rect", (_num(el, "x"), _num(el, "y"),
                                         _num(el, "w"), _num(el, "h"))))
            elif t == "roundrect":
                pending.append(("rrect", (_num(el, "x"), _num(el, "y"), _num(el, "w"),
                                          _num(el, "h"), _num(el, "arcsize", 5))))
            elif t == "ellipse":
                pending.append(("ellipse", (_num(el, "x"), _num(el, "y"),
                                            _num(el, "w"), _num(el, "h"))))
            elif t == "line":
                pending.append(("line", (_num(el, "x1"), _num(el, "y1"),
                                         _num(el, "x2"), _num(el, "y2"))))
            elif t in _PAINT:
                flush(t)
    flush("stroke")  # paint anything left

    return "".join(out), w, h, constraints


def shapes_in(xml_path):
    """Yield (name, shape_el) for each shape in a stencil file."""
    root = ET.fromstring(open(xml_path, encoding="utf-8").read())
    for sh in root.findall("shape"):
        yield sh.get("name", "?"), sh
