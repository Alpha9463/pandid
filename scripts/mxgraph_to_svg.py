#!/usr/bin/env python3
"""Convert draw.io / mxGraph stencil shapes to plain SVG.

mxGraph stencils (jgraph/drawio, Apache-2.0) describe each shape in a small
drawing language: <path> made of <move>/<line>/<quad>/<curve>/<arc>/<close>,
plus <rect>/<roundrect>/<ellipse>/<line>/<text>, painted by <fillstroke>/
<stroke>/<fill>. Coordinates are already in the shape's ``w`` × ``h`` space, so
they map straight onto an SVG ``viewBox="0 0 w h"``.

A paint op names the operation, not the colour: what a fill comes out as is the
canvas's current fill colour, which <fillcolor> sets and <save>/<restore>
bracket. The pen is state in exactly the same way -- <dashed>, <dashpattern>,
<strokewidth> and <linecap> set it, and <save>/<restore> bracket it too. That is
how a stencil says a part of itself is solid (a damper's pivot, a flow arrow's
head) or open (a filter's screen, a strainer's mesh) and, being state rather
than a property of the op, it is also why a plain <fill> is a *background wash*
in the shape's own fill colour rather than a request for black.

**Every directive is answered.** A directive this converter does not act on is
named in :data:`DECLINED` with the reason; anything else stops the conversion.
There is no falling off the end: a dropped directive is a drawing that says
something other than the stencil said, and the drop is silent at every later
stage (issue #291).

`convert_shape(shape_el)` returns (inner_svg, width, height, constraints, aspect)
where constraints is ``{name: (x_abs, y_abs)}`` from the stencil's <connections>
and aspect is the stencil's own ``aspect`` attribute.
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
    # _endpoint_to_center applies the spec's own radius correction (F.6.6):
    # radii too small to span the chord are scaled up until they exactly span
    # it, which is the case this branch is reached in. ``rxx, ryy`` are that
    # true ellipse, the one the points below are computed from, so they are also
    # the radii each sub-arc has to be *emitted* with. Restating the originals
    # instead hands every sub-arc radii too small for its own, shorter chord,
    # and the renderer corrects them again -- independently, and by a different
    # factor per segment, so the halves bulge differently. The endpoints stay
    # exact either way, which is why the ports and the bounding box are right
    # and only the curve between them is wrong: on the 40-wide vessel shells the
    # two halves of a dished head met in a cusp instead of a crown.
    cx, cy, rxx, ryy, th1, dth = _endpoint_to_center(x0, y0, rx, ry, phi, fa, fs, x, y)
    n = max(2, math.ceil(abs(dth) / (math.pi / 2)))
    cosp, sinp = math.cos(phi), math.sin(phi)

    def pt(t):
        return (cx + rxx * math.cos(t) * cosp - ryy * math.sin(t) * sinp,
                cy + rxx * math.cos(t) * sinp + ryy * math.sin(t) * cosp)

    seg = dth / n
    # The other three parameters carry over unchanged, and are right to: every
    # sub-arc rides the same ellipse (so the same ``phi_deg``) in the same
    # direction (so the same sweep flag). The large-arc flag is the one that is
    # genuinely per-segment, and ``n`` holds every segment to a quarter turn or
    # less, so it is 0 for all of them -- stated as the general rule rather than
    # the constant, so it stays true if ``n`` ever changes.
    large = 1 if abs(seg) > math.pi else 0
    parts = []
    for i in range(1, n + 1):
        ex, ey = (x, y) if i == n else pt(th1 + seg * i)
        parts.append(f"A {round(rxx, 4)} {round(ryy, 4)} {phi_deg} {large} {fs} "
                     f"{round(ex, 4)} {round(ey, 4)}")
    return " ".join(parts)

#: The one ink the sheet is drawn in. A P&ID is monochrome, so every stroke and
#: every solid shape is this colour and nothing else is.
INK = "#111"

#: What the fill colour starts at: the paper. No P&ID palette in
#: draw.io's Sidebar-PID.js names a ``fillColor``, so each of these
#: shapes takes ``fillColor=default`` from styles/default.xml, which
#: ``Graph.replaceDefaultColors`` resolves to the page's own colour.
#: The stencils are drawn expecting it: a body is the last
#: <fillstroke> in the shape and covers the nozzles, legs and vanes
#: behind it. A *state*, not a constant: <fillcolor> is how a stencil
#: asks for something else.
DEFAULT_FILL = "white"

# Which of the two the mxGraph paint ops apply, as (fills, strokes). What each
# one is painted *with* is the current fill colour and the ink: a paint op
# names the operation, not the colour.
_PAINT = {
    "fillstroke": (True, True),
    "stroke": (False, True),
    "fill": (True, False),
}

#: What mxGraph dashes with when a stencil turns dashes on and names no pattern.
#: The numbers are multiples of the pen width, not lengths; see :func:`_pen`.
DEFAULT_DASH_PATTERN = "3 3"

#: Directives this converter reads and deliberately does not act on, with the
#: reason it does not. A directive named here changes nothing about what the
#: drawing says; one that is neither named here nor handled in
#: :func:`convert_shape` stops the conversion.
#:
#: That is the whole point of the table. Until #291 the dispatch was an
#: if/elif chain with no else, so seven directives fell off the end without a
#: word: twelve shipped symbols lost the dashed screen that is the only thing
#: telling a filter from a plain drum and a strainer from a plate, while the
#: draw.io backend went on referencing the original stencil and drawing it
#: dashed. One flowsheet, two drawings, disagreeing about the equipment.
DECLINED = {
    "linejoin": (
        "how a corner is finished, not what the drawing says. The library holds "
        "every symbol to SVG's own join, so a stencil-derived shape does not "
        "finish its corners differently from the hand-drawn one beside it."
    ),
    "miterlimit": (
        "the length a mitre may run out to before it is bevelled, which is the "
        "same corner-finishing decision as <linejoin> above."
    ),
    "fontcolor": (
        "a P&ID is drawn in one ink (see INK), so lettering is that ink and "
        "nothing else -- the same reduction _fill_colour makes for fills."
    ),
}


def _fill_colour(named):
    """The fill a stencil's ``<fillcolor color=...>`` asks for.

    mxGraph takes a real colour here, plus the keywords ``"none"`` and
    ``"stroke"``. The sheet has one ink, so the only distinction that survives
    is transparent versus solid: every colour a stencil names for a fill is
    naming the thing it wants drawn solid. ``"none"`` is a stencil turning
    the fill off, which is not the same as never having set one, so it
    comes out transparent rather than :data:`DEFAULT_FILL`.
    """
    return "none" if (named or "none").strip().lower() == "none" else INK


def _num(el, attr, default=0.0):
    return float(el.get(attr, default))


def _fmt(v):
    """A number written as short as it can be without changing it."""
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _pen(state):
    """The SVG stroke properties the canvas state currently asks for.

    ``stroke-width`` always, because every stroke in the library declares one;
    the rest only where the stencil moved the pen off SVG's own default, so a
    shape that never touches it comes out exactly as it did before any of this
    existed.

    A dash pattern is in **pen widths**, not in units: mxGraph multiplies each
    number by the current stroke width, which is why one ``pattern="2 2"``
    serves stencils drawn on a 40-unit module and on a 200-unit one alike. The
    multiplication is done here for the same reason -- pandid draws these
    symbols far smaller than draw.io does, and a dash measured in units would
    come out as a grey smear on a strainer 10 units wide.
    """
    sw = state["stroke_width"]
    out = f' stroke-width="{sw}"'
    if state["dashed"]:
        pattern = " ".join(_fmt(float(n) * sw) for n in state["dash_pattern"].split())
        out += f' stroke-dasharray="{pattern}"'
    # A zero-length dash is a DOT, and only under a round cap: butt caps draw
    # nothing at all for it. That is how "Strainer (Cone)" asks for its
    # dash-dot screen ("6 3 0 3"), so the cap is load-bearing here rather than
    # a nicety, which is why it is acted on where <linejoin> is declined.
    if state["linecap"] != "butt":
        out += f' stroke-linecap="{state["linecap"]}"'
    return out


# mxGraph anchors a <text> by its own box, SVG by the baseline, so each valign
# needs the distance from that edge down to the baseline (as a fraction of the
# em). Only the operator letters on actuated valves ("M"/"H"/"S") use text.
_TEXT_ANCHOR = {"left": "start", "center": "middle", "right": "end"}
_TEXT_BASELINE = {"top": 0.8, "middle": 0.35, "bottom": -0.2}


def _text_svg(el, size):
    s = (el.get("str") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    align = _TEXT_ANCHOR.get(el.get("align", "left"), "start")
    y = _num(el, "y") + _TEXT_BASELINE.get(el.get("valign", "top"), 0.8) * size
    common = (f'x="{_num(el, "x")}" y="{round(y, 3)}" font-family="sans-serif" '
              f'font-size="{size}" text-anchor="{align}"')
    # The operator boxes run a yoke line straight through where the letter goes,
    # so knock it out behind the glyph rather than let the line strike it.
    return (f'<text {common} fill="white" stroke="white" stroke-width="{round(size / 4, 3)}" '
            f'stroke-linejoin="round">{s}</text>'
            f'<text {common} fill="{INK}">{s}</text>')


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


#: What mxGraph assumes when a <shape> names no ``aspect``: the shape may be
#: resized along each axis independently. Only a shape that says otherwise is
#: held to its proportions. (See mxStencil in the mxGraph source.)
DEFAULT_ASPECT = "variable"


def convert_shape(shape_el, stroke_width=2.0):
    """Convert one <shape> element to (inner_svg, w, h, constraints, aspect).

    ``stroke_width`` is emitted on every stroked element (in the shape's own
    units). At a symbol's native scale this equals the sheet's line weight; for
    a symbol later scaled by ``s``, pass ``stroke_width = 2 / s`` so the
    rendered line still lands at 2px. It is also the ceiling a stencil's own
    <strokewidth> is held to, and the unit a dash pattern is measured in.

    ``aspect`` is the stencil author's own statement about resizing:
    ``"variable"`` for a shape that may be stretched to fill whatever box it is
    given, ``"fixed"`` for one whose proportions carry meaning. It is reported
    rather than acted on here: this converts a shape at its native size, and
    what a box of another shape does to it is the caller's business.
    """
    w = _num(shape_el, "w", 100)
    h = _num(shape_el, "h", 100)
    aspect = shape_el.get("aspect", DEFAULT_ASPECT)

    constraints = {}
    conns = shape_el.find("connections")
    if conns is not None:
        for c in conns.findall("constraint"):
            name = c.get("name") or f"c{len(constraints)}"
            constraints[name] = (round(_num(c, "x") * w, 2), round(_num(c, "y") * h, 2))

    out = []
    pending = []   # geometry accumulated since the last paint op
    # The canvas state, as mxGraph keeps it: the fill, the pen and the font,
    # all read at paint time and all bracketed by <save>/<restore>.
    fresh = {
        "fill": DEFAULT_FILL,
        "font_size": 12.0,
        "stroke_width": stroke_width,
        "dashed": False,
        "dash_pattern": DEFAULT_DASH_PATTERN,
        "linecap": "butt",
    }
    state = dict(fresh)
    saved = []            # <save>/<restore> stack for that state

    def flush(op):
        nonlocal pending
        if not pending:
            return
        fills, strokes = _PAINT.get(op, (False, True))
        paint = state["fill"] if fills else "none"
        stroke = INK if strokes else "none"
        if paint == "none" and stroke == "none":
            # Neither filled nor stroked: mxGraph draws nothing, so nor does
            # this. Emitting an invisible element would leave the geometry in
            # the SVG for every later reader of it to mistake for ink.
            pending = []
            return
        sw = _pen(state) if stroke != "none" else ""
        for kind, data in pending:
            if kind == "path":
                out.append(f'<path d="{data}" fill="{paint}" stroke="{stroke}"{sw}/>')
            elif kind == "rect":
                x, y, rw, rh = data
                out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" '
                           f'fill="{paint}" stroke="{stroke}"{sw}/>')
            elif kind == "rrect":
                x, y, rw, rh, r = data
                out.append(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}" rx="{r}" '
                           f'fill="{paint}" stroke="{stroke}"{sw}/>')
            elif kind == "ellipse":
                x, y, rw, rh = data
                out.append(f'<ellipse cx="{x+rw/2}" cy="{y+rh/2}" rx="{rw/2}" ry="{rh/2}" '
                           f'fill="{paint}" stroke="{stroke}"{sw}/>')
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
            elif t == "fontsize":
                state["font_size"] = _num(el, "size", 12)
            elif t == "fillcolor":
                # Canvas state, read at paint time: the stencils set it after
                # the geometry it applies to and before the op that paints it.
                state["fill"] = _fill_colour(el.get("color"))
            elif t == "dashed":
                state["dashed"] = el.get("dashed", "1") == "1"
            elif t == "dashpattern":
                state["dash_pattern"] = el.get("pattern") or DEFAULT_DASH_PATTERN
            elif t == "strokewidth":
                # The stencil's number is in its own units, as every coordinate
                # here is, so it lands in this SVG's user space unchanged.
                #
                # Capped at the sheet's own weight, which is what
                # ``stroke_width`` is. A P&ID is drawn at one line weight and a
                # symbol's own detail may be FINER than it (that is what these
                # numbers are usually for, and the library holds every symbol to
                # exactly that: the heaviest pen in a drawing is the sheet's).
                # A stencil asking for a heavier line is asking for a second
                # weight on a monochrome single-weight sheet, and ISO 15519-1
                # 6.2 has no name for one -- draw.io's own base is 1px and
                # pandid's is 2, so a stencil written to stand out against the
                # thinner pen would come out heavier still against this one.
                state["stroke_width"] = min(_num(el, "width", stroke_width), stroke_width)
            elif t == "linecap":
                state["linecap"] = el.get("cap", "butt")
            elif t == "save":
                saved.append(dict(state))
            elif t == "restore":
                state = saved.pop() if saved else dict(fresh)
            elif t == "text":
                # <text> paints itself, so it never joins the pending geometry.
                out.append(_text_svg(el, state["font_size"]))
            elif t in _PAINT:
                flush(t)
            elif t not in DECLINED:
                raise ValueError(
                    f"{shape_el.get('name', '?')!r}: <{t}> is a stencil directive "
                    f"this converter neither draws nor declines, so the shape it "
                    f"describes would come out saying something the stencil did "
                    f"not say. Handle it in convert_shape, or name it in DECLINED "
                    f"with the reason it changes no ink."
                )
    flush("stroke")  # paint anything left

    return "".join(out), w, h, constraints, aspect


def shapes_in(xml_path):
    """Yield (name, shape_el) for each shape in a stencil file."""
    root = ET.fromstring(open(xml_path, encoding="utf-8").read())
    for sh in root.findall("shape"):
        yield sh.get("name", "?"), sh


def stencil_namespace(xml_path):
    """The package draw.io files this stencil set's shapes under.

    The set names itself on its own root element -- ``valves.xml`` opens
    ``<shapes name="mxGraph.pid.valves">`` -- and that name is half of the key
    draw.io's stencil registry answers to, the shape's own name being the other
    half. Read here rather than written down anywhere, because a stencil file
    that were re-vendored under a different package would then rename its shapes
    with it, and a hard-coded package would go on naming shapes that no longer
    exist. The failure that would cause is silent at the far end: draw.io falls
    back to a plain rectangle for a name it cannot resolve, so the export would
    still open and would simply have stopped being a P&ID.

    The case is not normalised here. draw.io lowercases the whole key when it
    registers a shape, and this library's own copies are inconsistent about it
    (thirteen files say ``mxGraph.pid.*`` and ``agitators.xml`` says
    ``mxgraph.pid.*``), so the fold belongs with the key that is built out of
    this, not with the reading of it.
    """
    root = ET.fromstring(open(xml_path, encoding="utf-8").read())
    name = root.get("name")
    if not name:
        raise ValueError(
            f"{xml_path}: the stencil set names no package on its root element, "
            f"so there is nothing to file its shapes under. draw.io reads that "
            f"name off <shapes name=...> and keys every shape in the file by it."
        )
    return name
