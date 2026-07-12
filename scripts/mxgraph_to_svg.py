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

import xml.etree.ElementTree as ET

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
    for c in path_el:
        t = c.tag
        if t == "move":
            parts.append(f"M {_num(c,'x')} {_num(c,'y')}")
        elif t == "line":
            parts.append(f"L {_num(c,'x')} {_num(c,'y')}")
        elif t == "quad":
            parts.append(f"Q {_num(c,'x1')} {_num(c,'y1')} {_num(c,'x2')} {_num(c,'y2')}")
        elif t == "curve":
            parts.append(f"C {_num(c,'x1')} {_num(c,'y1')} {_num(c,'x2')} {_num(c,'y2')} "
                         f"{_num(c,'x3')} {_num(c,'y3')}")
        elif t == "arc":
            large = c.get("large-arc-flag", "0")
            sweep = c.get("sweep-flag", "0")
            parts.append(f"A {_num(c,'rx')} {_num(c,'ry')} {_num(c,'x-axis-rotation')} "
                         f"{large} {sweep} {_num(c,'x')} {_num(c,'y')}")
        elif t == "close":
            parts.append("Z")
    return " ".join(parts)


def convert_shape(shape_el):
    """Convert one <shape> element to (inner_svg, w, h, constraints)."""
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
    stroke_w = 1.0

    def flush(op):
        nonlocal pending
        if not pending:
            return
        fill, stroke = _PAINT.get(op, ("none", "#111"))
        sw = f' stroke-width="{stroke_w}"' if stroke != "none" else ""
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
            elif t == "strokewidth":
                stroke_w = _num(el, "width", 1)
    flush("stroke")  # paint anything left

    return "".join(out), w, h, constraints


def shapes_in(xml_path):
    """Yield (name, shape_el) for each shape in a stencil file."""
    root = ET.fromstring(open(xml_path, encoding="utf-8").read())
    for sh in root.findall("shape"):
        yield sh.get("name", "?"), sh
