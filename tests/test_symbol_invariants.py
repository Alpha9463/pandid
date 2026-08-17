"""Symbol-invariant tests over EVERY (kind, variant) in the registry.

These are the defects the other render tests cannot reach -- a port placed in
empty space, a stroke half-clipped by an SVG viewport, a label struck through
by a line -- because those tests only ever exercise the handful of symbols the
example flowsheets happen to use. Every registered symbol is checked here, so a
newly added one gets the same scrutiny for free.

Geometry is approximated, not hit-tested exactly: SVG path/rect/ellipse/
circle/line/polygon primitives are flattened into straight-line segments
(elliptical arcs are properly sampled since several vessel-head ports sit on
one; Bezier curves are chorded between their anchor points, since ports are
never authored to sit mid-curve), and a port only has to land within
``GEOM_TOL`` of the nearest segment -- coarse by design, enough to catch a
port floating several units off a vessel wall without attempting exact path
hit-testing.
"""

from __future__ import annotations

import functools
import math
import pathlib
import re
import xml.etree.ElementTree as ET
from typing import NamedTuple

import pytest

from pandid import units
from pandid.portgeom import outward_dir, port_point
from pandid.render.symbols import Symbol, default_registry

BOX_EPS = 1.0  # bounding-box slack, in symbol-space units
GEOM_TOL = 2.0  # max distance from a port to the nearest drawn segment

Point = tuple[float, float]
Segment = tuple[Point, Point]
Matrix = tuple[float, float, float, float, float, float]  # a b c d e f, SVG order

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _compose(parent: Matrix, child: Matrix) -> Matrix:
    """parent ∘ child -- child is applied first, inside the parent's space."""
    pa, pb, pc, pd, pe, pf = parent
    ca, cb, cc, cd, ce, cf = child
    return (
        pa * ca + pc * cb,
        pb * ca + pd * cb,
        pa * cc + pc * cd,
        pb * cc + pd * cd,
        pa * ce + pc * cf + pe,
        pb * ce + pd * cf + pf,
    )


def _apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_NUM = r"-?\d*\.?\d+(?:[eE][-+]?\d+)?"


def _nums(s: str) -> list[float]:
    return [float(x) for x in re.findall(_NUM, s)]


def _parse_transform(s: str) -> Matrix:
    """Only the handful of transform functions any symbol here actually uses
    (mostly the valves' ``scale(0.5)``), but translate/rotate/matrix are cheap
    to support too so a hand-authored new symbol isn't silently mis-checked."""
    m = _IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        vals = _nums(args)
        if not vals:
            continue
        f: Matrix
        if name == "translate":
            f = (1.0, 0.0, 0.0, 1.0, vals[0], vals[1] if len(vals) > 1 else 0.0)
        elif name == "scale":
            sx = vals[0]
            sy = vals[1] if len(vals) > 1 else sx
            f = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            rad = math.radians(vals[0])
            co, si = math.cos(rad), math.sin(rad)
            rot: Matrix = (co, si, -si, co, 0.0, 0.0)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                f = _compose(
                    _compose((1.0, 0.0, 0.0, 1.0, cx, cy), rot), (1.0, 0.0, 0.0, 1.0, -cx, -cy)
                )
            else:
                f = rot
        elif name == "matrix" and len(vals) >= 6:
            f = (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
        else:
            continue
        m = _compose(m, f)
    return m


def _arc_points(x1, y1, rx, ry, phi_deg, large_arc, sweep, x2, y2, n=12):
    """Sample an SVG elliptical arc (endpoint parameterization, SVG 1.1 F.6.5)
    so a port on a curved vessel head is checked against the true curve, not
    the chord between its two path anchors."""
    if rx == 0 or ry == 0:
        return [(x1, y1), (x2, y2)]
    phi = math.radians(phi_deg)
    cphi, sphi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cphi * dx2 + sphi * dy2
    y1p = -sphi * dx2 + cphi * dy2
    rx, ry = abs(rx), abs(ry)
    lam = (x1p**2) / (rx**2) + (y1p**2) / (ry**2)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        co = -co
    cxp = co * (rx * y1p / ry)
    cyp = co * (-ry * x1p / rx)
    cx = cphi * cxp - sphi * cyp + (x1 + x2) / 2.0
    cy = sphi * cxp + cphi * cyp + (y1 + y2) / 2.0

    def _ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        c = max(-1.0, min(1.0, dot / (lu * lv))) if lu and lv else 1.0
        a = math.acos(c)
        return -a if (ux * vy - uy * vx) < 0 else a

    theta1 = _ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if sweep == 0 and dtheta > 0:
        dtheta -= 2 * math.pi
    if sweep == 1 and dtheta < 0:
        dtheta += 2 * math.pi
    pts = []
    for k in range(n + 1):
        t = theta1 + dtheta * k / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + ex * cphi - ey * sphi, cy + ex * sphi + ey * cphi))
    return pts


_PATH_CMD_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_PATH_TOKEN = re.compile(r"[MLHVCSQTAZ]|" + _NUM, re.I)


def _path_segments(d: str) -> list[Segment]:
    tokens = _PATH_TOKEN.findall(d)
    segs: list[Segment] = []
    i, n = 0, len(tokens)
    cur = start = (0.0, 0.0)
    cmd = None
    while i < n:
        if tokens[i].upper() in _PATH_CMD_ARGS:
            cmd = tokens[i]
            i += 1
        if cmd is None:
            break
        upper = cmd.upper()
        relative = cmd.islower()
        nargs = _PATH_CMD_ARGS[upper]
        if upper == "Z":
            segs.append((cur, start))
            cur = start
            cmd = None
            continue
        if i + nargs > n:
            break
        args = [float(tokens[i + k]) for k in range(nargs)]
        i += nargs
        if upper == "A":
            rx, ry, rot, laf, sf = args[0], args[1], args[2], args[3], args[4]
            x, y = args[5], args[6]
            if relative:
                x, y = x + cur[0], y + cur[1]
            pts = _arc_points(cur[0], cur[1], rx, ry, rot, int(laf), int(sf), x, y)
            segs.extend(zip(pts, pts[1:]))
            cur = (x, y)
            continue
        if upper == "H":
            x, y = args[0] + (cur[0] if relative else 0.0), cur[1]
        elif upper == "V":
            x, y = cur[0], args[0] + (cur[1] if relative else 0.0)
        else:
            x, y = args[-2], args[-1]
            if relative:
                x, y = x + cur[0], y + cur[1]
        newp = (x, y)
        if upper == "M":
            # A moveto lifts the pen. Counting the jump as a segment draws a
            # phantom stroke across the symbol -- from the origin to the first
            # subpath, and between every subpath after it -- and a port measured
            # against one of those is measured against a line nobody drew.
            start, cmd = newp, ("l" if relative else "L")
        else:
            segs.append((cur, newp))
        cur = newp
    return segs


def _ellipse_segments(cx, cy, rx, ry, n=48) -> list[Segment]:
    pts = [
        (cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ]
    return list(zip(pts, pts[1:] + pts[:1]))


def _poly_segments(points_attr: str, *, closed: bool) -> list[Segment]:
    nums = _nums(points_attr)
    pts = list(zip(nums[0::2], nums[1::2]))
    segs = list(zip(pts, pts[1:]))
    if closed and len(pts) > 2:
        segs.append((pts[-1], pts[0]))
    return segs


def _collect_segments(svg: str) -> list[Segment]:
    """Flatten every drawn primitive in a symbol's SVG into world-space
    (post-transform) line segments, for a coarse port-proximity check."""
    root = ET.fromstring(svg)
    segs: list[Segment] = []

    def walk(el, m: Matrix) -> None:
        tag = el.tag.split("}")[-1]
        m2 = _compose(m, _parse_transform(el.get("transform", "")))
        local: list[Segment] = []
        if tag == "path" and el.get("d"):
            local = _path_segments(el.get("d"))
        elif tag == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width", 0)), float(el.get("height", 0))
            corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            local = list(zip(corners, corners[1:] + corners[:1]))
        elif tag == "ellipse":
            local = _ellipse_segments(
                float(el.get("cx", 0)),
                float(el.get("cy", 0)),
                float(el.get("rx", 0)),
                float(el.get("ry", 0)),
            )
        elif tag == "circle":
            r = float(el.get("r", 0))
            local = _ellipse_segments(float(el.get("cx", 0)), float(el.get("cy", 0)), r, r)
        elif tag == "line":
            local = [
                (
                    (float(el.get("x1", 0)), float(el.get("y1", 0))),
                    (float(el.get("x2", 0)), float(el.get("y2", 0))),
                )
            ]
        elif tag == "polygon":
            local = _poly_segments(el.get("points", ""), closed=True)
        elif tag == "polyline":
            local = _poly_segments(el.get("points", ""), closed=False)
        segs.extend((_apply(m2, *a), _apply(m2, *b)) for a, b in local)
        for child in el:
            walk(child, m2)

    walk(root, _IDENTITY)
    return segs


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _nearest_distance(p: Point, segments: list[Segment]) -> float:
    return min((_point_segment_distance(p, a, b) for a, b in segments), default=math.inf)


# ---------------------------------------------------------------------------
# Exemptions.
#
# Each names a specific (kind, variant[, port]), so every invariant stays
# strict for every other symbol -- including any added later.
# ---------------------------------------------------------------------------

# feed/product are drawn dynamically by SvgRenderer._draw_boundary and never
# from their own Symbol.svg (see the "fallbacks" comment in symbols.py), so
# their registered geometry is intentionally unrelated to their ports.
_DYNAMIC_KINDS = {"feed", "product"}

# Ports sitting several units off the nearest drawn stroke.
# Intentional, not defects: on these symbols the casing is drawn *open* where
# the suction nozzle attaches, and the port sits in the mouth of that opening,
# which is where the pipe should meet it. The nearest stroke is therefore half
# the opening away. Do not "fix" these by moving the port onto the casing.
_KNOWN_GEOMETRY_GAPS = {
    ("pump", "default", "suction"),
    ("compressor", "default", "suction"),
    ("pump", "screw", "suction"),
}

# A signal connection is not a nozzle: nothing flows through a valve stem or an
# instrument tap, so the line stops at the symbol's outline instead of reaching
# in to meet ink, and most stencils draw no operator there to meet. They answer
# to the outline rule below instead; every port a pipe attaches to keeps this one.
_SIGNAL_PORTS = {
    (cls.kind, name)
    for cls in (getattr(units, n) for n in units.__all__)
    for name, _, role in cls.PORTS
    if role == "signal"
}

# No public "list everything" API on SymbolRegistry (by design: callers look
# up one (kind, variant) at a time), so reach into the private dict to
# enumerate the full registry for exhaustive testing.
_SYMBOLS = sorted(default_registry._symbols.items())
_IDS = [f"{kind}/{variant}" for (kind, variant), _ in _SYMBOLS]


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_svg_is_well_formed_and_declares_stroke_width(entry):
    (kind, variant), sym = entry
    ET.fromstring(sym.svg)  # raises ET.ParseError on malformed XML
    assert "stroke-width" in sym.svg, f"{kind}/{variant} declares no stroke-width"


#: Sizes to redraw a symbol at, as factors on its own box. The wide and tall
#: pairs are what a layout actually asks for; the last two are past anything a
#: drawing would want, because a check is only worth having under strain.
_REDRAWS = ((1.0, 1.0), (2.0, 1.0), (1.0, 2.5), (3.0, 0.5), (0.4, 1.7))


@pytest.mark.parametrize("factors", _REDRAWS, ids=[f"{a}x{b}" for a, b in _REDRAWS])
@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_a_symbol_redrawn_at_a_new_size_draws_the_ink_it_was_drawn_from(entry, factors):
    """``pandid.render.svg._baked`` moves the pen and nothing else.

    A placement that would scale the two axes differently is emitted redrawn at
    the placed size rather than stretched by its viewport (#235), which rewrites
    every number in the drawing. That is only allowed to be a change of
    *notation*: the ink has to land where the scale would have put it. Every
    check in this file says a port lands on drawn ink, and every one of them is
    worth nothing if the ink itself has quietly moved.

    Measured against the scale applied by this file's own flattener rather than
    against the renderer's arithmetic restated, so the two sides are independent
    -- and over every registered symbol, since it is the arcs (which have to be
    recomputed rather than scaled) and the mirrored derivations that are the
    parts with somewhere to go wrong.
    """
    from pandid.render.svg import _baked

    (kind, variant), sym = entry
    fx, fy = factors
    want = [
        ((ax * fx, ay * fy), (bx * fx, by * fy))
        for (ax, ay), (bx, by) in _collect_segments(sym.svg)
    ]
    got = _collect_segments(_baked(sym.svg, fx, fy))
    assert len(got) == len(want), (
        f"{kind}/{variant} redrawn at {fx} x {fy} flattens to {len(got)} segments, "
        f"against the {len(want)} it was drawn from"
    )
    worst = max(
        (max(math.dist(p, q) for p, q in zip(g, w)) for g, w in zip(got, want)),
        default=0.0,
    )
    # The redraw writes six decimals, so a point may land half a millionth of a
    # unit from where the scale would have put it. A drawing unit is 0,26 mm.
    assert worst <= 1e-5, (
        f"{kind}/{variant} redrawn at {fx} x {fy} moved its ink by {worst:.3g} units"
    )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_ports_within_bounding_box(entry):
    (kind, variant), sym = entry
    for name, (x, y) in sym.ports.items():
        assert -BOX_EPS <= x <= sym.width + BOX_EPS, (
            f"{kind}/{variant} port {name!r} x={x} outside [0, {sym.width}]"
        )
        assert -BOX_EPS <= y <= sym.height + BOX_EPS, (
            f"{kind}/{variant} port {name!r} y={y} outside [0, {sym.height}]"
        )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_port_faces_within_bounding_box(entry):
    (kind, variant), sym = entry
    for name, faces in sym.port_faces.items():
        for face, (x, y) in faces.items():
            assert -BOX_EPS <= x <= sym.width + BOX_EPS, (
                f"{kind}/{variant} port_faces[{name!r}][{face!r}] x={x} outside [0, {sym.width}]"
            )
            assert -BOX_EPS <= y <= sym.height + BOX_EPS, (
                f"{kind}/{variant} port_faces[{name!r}][{face!r}] y={y} outside [0, {sym.height}]"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_every_menu_entry_resolves_to_the_face_it_claims(entry):
    """A placement filed under "N" whose coordinate is nearest the west edge is
    a lie: ``port_anchor`` derives the face from the coordinate, so the nozzle
    silently comes out somewhere else.

    ``Symbol.__post_init__`` rejects such a declaration outright, so this is a
    postcondition over the shipped registry rather than the primary guard.
    It would only fire if that check were weakened *and* a symbol were authored
    wrongly. The constructor's own rejection is tested separately."""
    (kind, variant), sym = entry
    for name, faces in sym.port_faces.items():
        for face, (x, y) in faces.items():
            got = outward_dir(x, y, sym.width, sym.height)
            assert got == face, (
                f"{kind}/{variant} port_faces[{name!r}][{face!r}] at ({x}, {y}) is "
                f"nearest the {got} edge of the {sym.width}x{sym.height} box"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_the_menu_carries_the_symbols_own_nozzle(entry):
    """The home placement is folded into the menu, so nothing downstream has a
    privileged default to merge back in.

    Like the check above, this is a postcondition of ``Symbol.__post_init__``
    over the shipped registry, not the guard that enforces it."""
    (kind, variant), sym = entry
    assert set(sym.port_faces) == set(sym.ports), f"{kind}/{variant} menu misses a port"
    for name, xy in sym.ports.items():
        assert xy in sym.port_faces[name].values(), (
            f"{kind}/{variant} port {name!r} home {xy} is not in its own menu"
        )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_ports_lie_on_drawn_geometry(entry):
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    segments = _collect_segments(sym.svg)
    for name, (x, y) in sym.ports.items():
        if (kind, variant, name) in _KNOWN_GEOMETRY_GAPS or (kind, name) in _SIGNAL_PORTS:
            continue
        d = _nearest_distance((x, y), segments)
        assert d <= GEOM_TOL, (
            f"{kind}/{variant} port {name!r} at ({x}, {y}) is {d:.1f}u "
            f"from the nearest drawn stroke (tolerance {GEOM_TOL})"
        )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_port_faces_lie_on_drawn_geometry(entry):
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    segments = _collect_segments(sym.svg)
    for name, faces in sym.port_faces.items():
        if (kind, variant, name) in _KNOWN_GEOMETRY_GAPS or (kind, name) in _SIGNAL_PORTS:
            continue
        for face, (x, y) in faces.items():
            d = _nearest_distance((x, y), segments)
            assert d <= GEOM_TOL, (
                f"{kind}/{variant} port_faces[{name!r}][{face!r}] at ({x}, {y}) is "
                f"{d:.1f}u from the nearest drawn stroke (tolerance {GEOM_TOL})"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_signal_ports_sit_on_the_symbols_outline(entry):
    """A signal connection terminates where the line meets the symbol, so its
    coordinate belongs on the edge of the box and not inside it.

    The renderer draws to the port's own point while the router steers to that
    point projected onto the box edge, so a coordinate parked on interior ink
    (a gate valve's seat, a butterfly's shaft boss) draws the signal running
    into the body and stopping in the middle of it. The allowance is the same
    nozzle stub the balloons use, which is what lets a hexagon or a square
    drawn inboard of its box put the terminal on its own outline."""
    (kind, variant), sym = entry
    placements = {(name, "port"): xy for name, xy in sym.ports.items()}
    placements.update(
        {(name, face): xy for name, faces in sym.port_faces.items() for face, xy in faces.items()}
    )
    for (name, where), (x, y) in placements.items():
        if (kind, name) not in _SIGNAL_PORTS:
            continue
        inboard = min(x, y, sym.width - x, sym.height - y)
        assert inboard <= GEOM_TOL, (
            f"{kind}/{variant} signal port {name!r} ({where}) at ({x}, {y}) is "
            f"{inboard:.1f}u inside the {sym.width}x{sym.height} box "
            f"(tolerance {GEOM_TOL})"
        )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_no_two_ports_coincide(entry):
    (kind, variant), sym = entry
    # The rule itself lives on Symbol, so a third-party symbol this suite never
    # sees is held to it too; this assertion covers the shipped registry.
    assert sym.coincident_ports() == [], f"{kind}/{variant}: " + "; ".join(
        f"ports {a!r} and {b!r} both resolve to {xy}" for a, b, xy in sym.coincident_ports()
    )


# ---------------------------------------------------------------------------
# Ports, and the nozzles the artwork draws for them (#225).
#
# ``test_ports_lie_on_drawn_geometry`` above holds every port to the ink, and
# that is not the same question. A stencil that draws an explicit nozzle has
# said something stronger than "there is a wall here": a nozzle drawn on a
# vessel is a statement that a connection exists *at that point*, and a port
# somewhere else on the same drawing is the drawing disagreeing with itself.
# Both halves of #225 passed the ink check and were wrong -- ``tank/sphere``'s
# inlet sat on the crown midway between the two nozzles drawn either side of
# it, and its outlet sat on the base rail of the support skirt, ten units below
# the nozzle the stencil drew for it and on the structure rather than on the
# vessel.
#
# This is the companion of ``nozzle-unconnected`` (#209). That finding reads a
# *numbered* nozzle a sheet did not pipe; this reads a *drawn* one the class
# cannot pipe at all, which is a defect one layer further down and is caught
# without a flowsheet.
#
# WHAT COUNTS AS A DRAWN NOZZLE. In the draw.io P&ID stencils a nozzle is a
# short rectangular stub standing off the shell with a flange line ruled across
# its free end. All three parts are required here, because each of them is what
# tells a nozzle from something else the artwork draws:
#
#   - a *rectangle*, small against the box on both axes (``_NOZZLE_STUB``),
#     which is what ``vessel/jacketed``'s full-height jacket panels, a
#     submersible pump's mounting plate and a damper's body are not;
#   - a *flange*, a straight line on the same axis as one of the rectangle's
#     four faces, centred on it and longer than it, which is what makes that
#     face the free end and gives the connection its point;
#   - and an overhang short enough to read as a flange (``_NOZZLE_FLANGE``),
#     which is what a submersible pump's 90-unit casing line across a 14-unit
#     rectangle is not.
#
# The sweep that settled these numbers found exactly one symbol in the 157 that
# draws a nozzle this way, plus the one gauge stub named below. If a later
# vendoring adds a second, it gets both invariants for free -- which is the
# whole point, since the port map is authored by hand in
# ``scripts/vendor_symbols.py`` and the artwork is not.
# ---------------------------------------------------------------------------

#: How much of the box a nozzle stub may be, on each axis.
_NOZZLE_STUB = 0.25
#: How much longer than the face it caps a flange line may be. A flange
#: overhangs a nozzle by a little; a line seven times its width is some other
#: part of the drawing that happens to pass through.
_NOZZLE_FLANGE = 2.0

#: (kind, variant) whose flanged stub is not a process nozzle. One entry, named
#: rather than tolerated silently, exactly as ``_KNOWN_GEOMETRY_GAPS`` is:
#: ``separator/knockout`` draws a level gauge on the east wall -- an 8 x 12 stub
#: carrying the two vertical lines of the glass -- and the outer of those two
#: reads as a flange across the stub's end. It is a gauge and not a connection:
#: nothing flows through it, ``Separator`` has no port for one, and the giveaway
#: in the artwork is that there is a second line drawn *outboard* of the
#: "flange", which no real nozzle has.
_NOT_NOZZLES = {("separator", "knockout")}


def _rects(svg: str) -> list[tuple[float, float, float, float]]:
    """Every ``<rect>`` in the artwork, as world-space (x0, y0, x1, y1).

    ``_collect_segments`` flattens a rect into four unattributed segments, which
    is right for a proximity test and useless here: the whole question is which
    four segments belong to one rectangle.
    """
    out: list[tuple[float, float, float, float]] = []

    def walk(el, m: Matrix) -> None:
        m2 = _compose(m, _parse_transform(el.get("transform", "")))
        if el.tag.split("}")[-1] == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width", 0)), float(el.get("height", 0))
            (ax, ay), (bx, by) = _apply(m2, x, y), _apply(m2, x + w, y + h)
            out.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
        for child in el:
            walk(child, m2)

    walk(ET.fromstring(svg), _IDENTITY)
    return out


class _Nozzle(NamedTuple):
    """One nozzle the artwork draws: the face it points out of, the point a
    pipe meets it at, and the stretch of that face the stub covers."""

    face: str
    point: Point
    lo: float
    hi: float


def _drawn_nozzles(sym: Symbol) -> list[_Nozzle]:
    """Every flanged rectangular stub in a symbol's artwork."""
    segments = _collect_segments(sym.svg)
    found: list[_Nozzle] = []
    for x0, y0, x1, y1 in _rects(sym.svg):
        if x1 - x0 > _NOZZLE_STUB * sym.width or y1 - y0 > _NOZZLE_STUB * sym.height:
            continue
        for face, (a, b) in (
            ("N", ((x0, y0), (x1, y0))),
            ("S", ((x0, y1), (x1, y1))),
            ("W", ((x0, y0), (x0, y1))),
            ("E", ((x1, y0), (x1, y1))),
        ):
            across = face in ("N", "S")
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            width = abs(b[0] - a[0]) if across else abs(b[1] - a[1])
            for sa, sb in segments:
                span = abs(sb[0] - sa[0]) if across else abs(sb[1] - sa[1])
                # Same straight line as the face, centred on it, longer than it
                # but not by more than a flange plate is.
                if not width < span <= _NOZZLE_FLANGE * width:
                    continue
                if abs(sa[int(across)] - sb[int(across)]) > GEOM_TOL / 4:
                    continue  # not on the face's own axis
                if abs(sa[int(across)] - mid[int(across)]) > GEOM_TOL / 4:
                    continue  # parallel to the face, but not on it
                if (
                    abs((sa[1 - int(across)] + sb[1 - int(across)]) / 2 - mid[1 - int(across)])
                    > GEOM_TOL / 4
                ):
                    continue  # on the face's line, but not centred on the stub
                lo, hi = (x0, x1) if across else (y0, y1)
                found.append(_Nozzle(face, mid, lo, hi))
                break
    return found


def _port_placements(sym: Symbol) -> list[tuple[str, str, Point]]:
    """Every (port, face, point) the symbol offers, home placements and menu."""
    return [
        (name, face, xy) for name, faces in sym.port_faces.items() for face, xy in faces.items()
    ]


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_every_drawn_nozzle_carries_a_port(entry):
    """A nozzle nobody can connect to is a connection the class cannot make.

    ``tank/sphere`` drew a flanged nozzle under its belly and put ``outlet`` on
    the base rail of the support skirt instead, so ``examples/14``'s butane left
    the structure rather than the vessel and the one nozzle the stencil drew for
    it was never used.
    """
    (kind, variant), sym = entry
    if (kind, variant) in _NOT_NOZZLES:
        pytest.skip("draws a gauge stub, not a process nozzle")
    points = [xy for _n, _f, xy in _port_placements(sym)]
    for nozzle in _drawn_nozzles(sym):
        near = min(math.dist(nozzle.point, p) for p in points) if points else math.inf
        assert near <= GEOM_TOL, (
            f"{kind}/{variant} draws a nozzle on its {nozzle.face} face at "
            f"{nozzle.point} and anchors no port on it, so the drawing offers a "
            f"connection the class cannot make"
        )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_no_port_lands_between_two_drawn_nozzles(entry):
    """Where a face carries a row of nozzles, its connections are those nozzles.

    ``tank/sphere``'s inlet sat at (40, 5) with nozzles drawn at x 18..30 and
    50..62 either side of it: on ink, on the crown, and on nothing that says a
    pipe may be joined there. The reported symptom of #225 is a line arriving at
    bare shell in the gap, which is this.
    """
    (kind, variant), sym = entry
    if (kind, variant) in _NOT_NOZZLES:
        pytest.skip("draws a gauge stub, not a process nozzle")
    nozzles = _drawn_nozzles(sym)
    for name, face, (x, y) in _port_placements(sym):
        on_face = [n for n in nozzles if n.face == face]
        if len(on_face) < 2:
            continue
        along = x if face in ("N", "S") else y
        if any(n.lo - GEOM_TOL <= along <= n.hi + GEOM_TOL for n in on_face):
            continue
        assert not (min(n.lo for n in on_face) < along < max(n.hi for n in on_face)), (
            f"{kind}/{variant} port {name!r} at ({x}, {y}) sits on the {face} "
            f"face between the nozzles drawn at "
            + " and ".join(f"{n.lo:g}..{n.hi:g}" for n in on_face)
            + ", so a pipe to it arrives at bare shell"
        )


# ---------------------------------------------------------------------------
# The drawn artwork and the resolved ports have to agree at *every* box shape.
#
# Everything above measures a symbol in the coordinates it was drawn in, where
# the box is by definition the one it was drawn for. A unit given an explicit
# width and height is placed in a box of some *other* shape, and the port has to
# follow the ink there too -- whichever way the renderer disposes of the spare
# room, by filling the box or by centring the artwork in it. Nothing else covers
# that case, and a port left behind in the whitespace draws a stream that stops
# short of its equipment.
#
# What the artwork did is read back out of the rendered SVG, transform and all,
# so this measures what the renderer *did* rather than what portgeom assumed it
# would do -- which is exactly the disagreement being tested.
# ---------------------------------------------------------------------------

#: Box shapes nothing is drawn at: far wider than tall, far taller than wide,
#: and square. One of the three is the wrong shape for every symbol there is.
_ODD_BOXES = ((300.0, 60.0), (60.0, 300.0), (140.0, 140.0))

#: Placement transforms to try each of those at, as ``pin()`` takes them. The
#: identity, then a quarter turn with a left-right flip and a three-quarter turn
#: with a top-bottom one: a reshaped box and a turned one compose, and the port
#: has to come out on the ink under both at once.
_PLACEMENTS = ({}, {"orientation": 90, "mirrored": "x"}, {"orientation": 270, "mirrored": "y"})

#: The nozzle is measured by inverting the placement the artwork was drawn
#: under, so a port authored exactly ``GEOM_TOL`` from the ink comes back a few
#: parts in 10^13 the wrong side of the line. Slack for that round trip and for
#: nothing else: it is far smaller than any distance a drawing can express.
_ROUNDTRIP_EPS = 1e-9

#: Kinds that cannot be handed a box at all. A Conveyor is sized by ``length``
#: and refuses ``width``/``height``, so its artwork is built to its box and the
#: two can never disagree; tests/test_conveyor.py holds it to that.
_UNBOXABLE_KINDS = {"conveyor"}

_UNIT_BY_KIND = {cls.kind: cls for cls in (getattr(units, n) for n in units.__all__)}

#: The balloon variants that are reached through ``display=`` instead; see
#: :func:`_sized_unit`.
_RETIRED_DISPLAYS = {"panel": "central", "aux": "subsidiary"}


def _sized_unit(kind: str, variant: str, index: int, w: float, h: float):
    """One unit of ``(kind, variant)``, forced into a ``w`` x ``h`` box."""
    cls = _UNIT_BY_KIND[kind]
    if kind == "instrument":  # tagged (type, number) rather than named
        # ``panel`` and ``aux`` are registered artwork whose *constructor*
        # spelling is retired: they are a display, not a symbol type. The
        # drawing is still theirs and still has to satisfy every invariant
        # below, so it is asked for the way that is not on its way out.
        display = _RETIRED_DISPLAYS.get(variant)
        if display is not None:
            return cls("XX", index, display=display, width=w, height=h)
        return cls("XX", index, variant=variant, width=w, height=h)
    return cls(f"{kind}-{variant}-{index}", variant=variant, width=w, height=h)


def _invert(m: Matrix) -> Matrix:
    """The transform that takes a drawn point back where it was drawn from."""
    a, b, c, d, e, f = m
    det = a * d - b * c
    return (
        d / det,
        -b / det,
        -c / det,
        a / det,
        (c * f - d * e) / det,
        (b * e - a * f) / det,
    )


def _natives(fs) -> dict[str, tuple[float, float]]:
    """What each definition on *fs*'s sheet was **authored** at, by ``<defs>`` id.

    Which is not always what its viewBox says: see :func:`_placements`.
    """
    from pandid.render.svg import SvgRenderer

    renderer = SvgRenderer()
    return {
        renderer._sym_id(u): (
            default_registry.for_unit(u).width,
            default_registry.for_unit(u).height,
        )
        for u in fs.units
        if u.frame is not None and u.kind not in ("feed", "product")
    }


def _placements(
    svg: str, natives: dict[str, tuple[float, float]] | None = None
) -> dict[tuple[float, float], Matrix]:
    """Authored symbol coordinates -> sheet coordinates for each placed symbol.

    Keyed by the centre of the box it was placed in, which is the one point a
    quarter turn and a mirror both leave alone, and so the only handle on a
    ``<use>`` that survives its own transform.

    A ``<symbol>`` maps its viewBox onto the ``<use>``'s box under its own
    ``preserveAspectRatio``: ``none`` fills the box exactly, while the default
    ``xMidYMid meet`` scales uniformly and centres, leaving a letterbox the box
    edge is no longer on. Whatever the ``<use>`` then does to the result is
    composed on top.

    One more step, and it is the one #235 added. A placement that would have
    scaled the two axes differently is emitted *redrawn* at the placed size
    rather than stretched by its viewport (``pandid.render.svg._baked``), so its
    viewBox is that box and the viewport contributes a scale of exactly 1 --
    which is the whole point, since a viewport scales ink and a redraw does not.
    Those definitions are therefore no longer written in the coordinates the
    symbol was authored in, and *natives* is what says so: the size each id was
    authored at, from :func:`_natives`. Left out, every viewBox is taken at face
    value, which is right for every definition nothing reshaped.
    """
    natives = natives or {}
    defs = {m.group(1): m.group(0) for m in re.finditer(r'<symbol id="([^"]+)"[^>]*>', svg)}
    out: dict[tuple[float, float], Matrix] = {}
    for use in re.findall(r"<use\b[^>]*/>", svg):
        attr = dict(re.findall(r'([\w-]+)="([^"]*)"', use))
        sym_id = attr["href"][1:]
        ux, uy = float(attr["x"]), float(attr["y"])
        uw, uh = float(attr["width"]), float(attr["height"])
        _, _, vw, vh = _nums(re.search(r'viewBox="([^"]+)"', defs[sym_id]).group(1))
        if 'preserveAspectRatio="none"' in defs[sym_id]:
            sx, sy, ox, oy = uw / vw, uh / vh, 0.0, 0.0
        else:
            sx = sy = min(uw / vw, uh / vh)
            ox, oy = (uw - sx * vw) / 2, (uh - sy * vh) / 2
        fit: Matrix = (sx, 0.0, 0.0, sy, ux + ox, uy + oy)
        nw, nh = natives.get(sym_id, (vw, vh))
        redraw: Matrix = (vw / nw, 0.0, 0.0, vh / nh, 0.0, 0.0)
        key = (round(ux + uw / 2, 6), round(uy + uh / 2, 6))
        out[key] = _compose(_parse_transform(attr.get("transform", "")), _compose(fit, redraw))
    return out


@pytest.fixture(scope="module")
def odd_box_sheets():
    """Every symbol at every shape in :data:`_ODD_BOXES` and every placement.

    One sheet per (shape, placement), built once and shared: the sheets *are*
    what the checks below measure, and rebuilding a hundred-odd units for each
    of a hundred-odd test cases would be the bulk of the suite's runtime.
    """
    from pandid import Flowsheet

    sheets: dict[tuple, dict[tuple[str, str], tuple]] = {}
    for box in _ODD_BOXES:
        for turn, placement in enumerate(_PLACEMENTS):
            fs = Flowsheet("odd boxes")
            placed = {}
            for i, ((kind, variant), _) in enumerate(_SYMBOLS):
                if kind in _DYNAMIC_KINDS or kind in _UNBOXABLE_KINDS:
                    continue
                unit = _sized_unit(kind, variant, i, *box)
                # Pinned well clear of each other: this sheet is a measuring
                # jig, not a diagram, and nothing on it is connected to
                # anything.
                fs.add(unit).pin(x=200 + 600 * (i % 8), y=200 + 600 * (i // 8), **placement)
                placed[(kind, variant)] = unit
            matrices = _placements(fs.to_svg(), _natives(fs))
            sheets[(box, turn)] = {
                key: (unit, matrices[(round(unit.frame.cx, 6), round(unit.frame.cy, 6))])
                for key, unit in placed.items()
            }
    return sheets


def _resolved_in_symbol_space(unit, matrix: Matrix, name: str) -> Point:
    """A port's resolved point, put back in the symbol's own coordinates.

    Which is where ``GEOM_TOL`` is a distance, rather than a distance times
    whatever the box, the turn and the mirror each did to that axis.
    """
    return _apply(_invert(matrix), *port_point(unit, unit.frame, name))


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_ports_land_on_drawn_ink_at_any_box_shape(entry, odd_box_sheets):
    """A nozzle follows the artwork into a box of any shape, at any placement."""
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    if kind in _UNBOXABLE_KINDS:
        pytest.skip("a conveyor is sized by length=, so its box is its artwork's")
    # The ink the *unit* is drawn with, which is not always the registered
    # symbol's: a reactor composes a stirrer and its motor onto the body, and
    # the motor grows the box upward and moves every one of the body's nozzles
    # down into it. Measuring the moved nozzles against the unmoved body would
    # report the composition's own offset as a gap.
    first = next(iter(odd_box_sheets.values()))[(kind, variant)][0]
    segments = _collect_segments(default_registry.for_unit(first).svg)
    for key, sheet in odd_box_sheets.items():
        unit, matrix = sheet[(kind, variant)]
        for name in unit.ports:
            if (kind, variant, name) in _KNOWN_GEOMETRY_GAPS or (kind, name) in _SIGNAL_PORTS:
                continue
            d = _nearest_distance(_resolved_in_symbol_space(unit, matrix, name), segments)
            assert d <= GEOM_TOL + _ROUNDTRIP_EPS, (
                f"{kind}/{variant} port {name!r} in a {key[0][0]:g}x{key[0][1]:g} box at "
                f"{_PLACEMENTS[key[1]] or 'no turn'} is {d:.1f}u from the nearest drawn "
                f"stroke once the artwork's own placement is undone (tolerance {GEOM_TOL})"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_a_directional_symbols_ports_stay_on_ink_under_a_flip(entry):
    """What a symbol has to be able to do before it may declare ``directional``.

    A directional symbol's *drawing* is held still under a flip -- otherwise the
    flip draws the arrow backwards, which on the heater/cooler pair is the other
    symbol -- while its *nozzles* still move, because moving them is what the
    flip was asked for. That is a decoupling, and it is the exact decoupling
    CONTRIBUTING §4 records as having actually happened once: a mirror the
    renderer applied and the geometry did not, drawing every stream detached
    from its nozzle.

    Here it is deliberate, and it is only safe where the artwork under the moved
    nozzle is the same artwork that was under the original -- which is true of
    the three that declare it, whose drawing is a circle with everything else
    laid through its centre. So the flipped port is measured against the
    *unflipped* strokes, which is what the sheet actually draws.

    Every other symbol skips: nothing holds their ink still, so their ports
    travel with it and ``test_ports_land_on_drawn_ink_at_any_box_shape`` is the
    check that applies.
    """
    (kind, variant), sym = entry
    if not sym.directional:
        pytest.skip("not a directional symbol; its artwork flips with its ports")
    segments = _collect_segments(sym.svg)
    # All three, and not the two the caller can spell: a half turn arrives as
    # both flips at once (pandid.render.svg._reflections), so (True, True) is a
    # placement an author reaches by writing orientation=180 as readily as by
    # writing mirrored="xy".
    for mirror_x, mirror_y in ((True, False), (False, True), (True, True)):
        for name, (x, y) in sym.ports.items():
            if (kind, name) in _SIGNAL_PORTS:
                continue
            flipped = (sym.width - x if mirror_x else x, sym.height - y if mirror_y else y)
            d = _nearest_distance(flipped, segments)
            assert d <= GEOM_TOL, (
                f"{kind}/{variant} declares directional, but flipped "
                f"(x={mirror_x}, y={mirror_y}) its port {name!r} lands at {flipped}, "
                f"{d:.1f}u from the nearest stroke of the artwork that is held "
                f"still under that flip (tolerance {GEOM_TOL})"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_a_directional_symbol_carries_no_lettering_of_its_own(entry):
    """The other thing declaring ``directional`` asks of the artwork.

    A directional drawing is held still *as a whole*, so the counter-transform
    that keeps a symbol's own lettering readable has nothing left to do and, if
    it ran anyway, would counter-transform each glyph a second time. The
    renderer therefore picks one of the two rather than composing them, and this
    is what keeps that branch honest. ``scripts/vendor_symbols.py`` refuses the
    combination at generation time; this covers the hand-drawn symbols too.
    """
    (kind, variant), sym = entry
    if not sym.directional:
        pytest.skip("not a directional symbol")
    assert "<text" not in sym.svg, (
        f"{kind}/{variant} declares directional and carries lettering: the "
        f"renderer holds its whole drawing still and cannot also counter-"
        f"transform a glyph inside it"
    )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_signal_ports_stay_on_the_outline_at_any_box_shape(entry, odd_box_sheets):
    """The odd-box counterpart of the outline rule, and the balloons' own case.

    A signal terminates where the line meets the symbol, so its coordinate
    belongs on the symbol's outline -- which is on the *artwork*, not on a box
    edge that may be a long way from it. Every one of an instrument balloon's
    connections is a signal, so without this the balloons are exempt from the
    whole of the check above and nothing holds their taps to the circle."""
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    if kind in _UNBOXABLE_KINDS:
        pytest.skip("a conveyor is sized by length=, so its box is its artwork's")
    corners = [(0.0, 0.0), (sym.width, 0.0), (sym.width, sym.height), (0.0, sym.height)]
    outline = list(zip(corners, corners[1:] + corners[:1]))
    for key, sheet in odd_box_sheets.items():
        unit, matrix = sheet[(kind, variant)]
        for name in unit.ports:
            if (kind, name) not in _SIGNAL_PORTS:
                continue
            d = _nearest_distance(_resolved_in_symbol_space(unit, matrix, name), outline)
            assert d <= GEOM_TOL + _ROUNDTRIP_EPS, (
                f"{kind}/{variant} signal port {name!r} in a {key[0][0]:g}x{key[0][1]:g} box "
                f"at {_PLACEMENTS[key[1]] or 'no turn'} is {d:.1f}u off the "
                f"{sym.width}x{sym.height} outline once the artwork's own placement is "
                f"undone (tolerance {GEOM_TOL})"
            )


# ---------------------------------------------------------------------------
# A vessel's and a tank's five nozzles, on every drawing that has to carry them
# (#222).
#
# The generic invariants above hold every symbol to its OWN port map: what it
# anchors has to land on ink and no two of them may coincide. Neither notices a
# symbol that anchors too FEW, because a symbol has no idea which class draws
# it. That gap is the whole risk in adding a nozzle to a class with seventeen
# drawings: a port the artwork never anchored falls back to the centre of the
# box (``portgeom._drawn_placements``), where every other unanchored port lands
# too, and the sheet draws two streams on one point without raising anything.
#
# So this reads the class's PORTS and asks the drawing, one variant at a time.
# It is the check that would have caught the same class of defect as #225 --
# ports and drawn nozzles drifting apart -- one commit earlier than the sheet.
# ---------------------------------------------------------------------------

_HOLDUP = [(units.Vessel, "vessel"), (units.Tank, "tank")]

#: (kind, variant, port) -> the face the nozzle comes out of at the SYMBOL's own
#: box, for the two nozzles that do not take the face their role asks for.
#:
#: Both are the same fact about the same stencil pair: ``vessel/legs`` and
#: ``vessel/skirted`` are 122.69 tall over a vessel that ends at 95.38, so the
#: bottom head's crown is nearer a side wall (20) than the box's floor (27.3)
#: and ``outward_dir`` reads it as west. The drain is on the vessel's low point
#: regardless, which is where the pipe leaves from; moving it to win a face
#: would put it on a leg. Recorded rather than tolerated silently -- a third
#: entry appearing here is a stencil that needs looking at, and #225 is the
#: change that gives a supported vessel its face back.
_DRAIN_FACES_SIDEWAYS = {
    ("vessel", "legs", "drain"): "W",
    ("vessel", "skirted", "drain"): "W",
}

#: The face each role asks for, by what the role means. ``inlet`` and ``outlet``
#: are absent: where the process pair goes is the stencil's business (a vessel
#: is piped side to side, a tank top to bottom) and this is a rule about the
#: three that are positioned by duty.
_ROLE_FACE = {"vent": "N", "relief": "N", "drain": "S"}


@pytest.mark.parametrize(
    "cls,kind,variant",
    [(cls, kind, v) for cls, kind in _HOLDUP for v in sorted(default_registry.variants(kind))],
    ids=[f"{kind}/{v}" for _, kind in _HOLDUP for v in sorted(default_registry.variants(kind))],
)
def test_every_holdup_variant_anchors_every_nozzle_its_class_declares(cls, kind, variant):
    """No fallback to the centre of the box, on any of the seventeen."""
    from pandid.portgeom import is_anchored

    unit = cls("X-1", variant=variant)
    for name in unit.ports:
        assert is_anchored(unit, name), (
            f"{kind}/{variant} does not anchor {name!r}, so it falls back to the "
            f"centre of the box and shares that point with every other one that does"
        )


@pytest.mark.parametrize(
    "cls,kind,variant",
    [(cls, kind, v) for cls, kind in _HOLDUP for v in sorted(default_registry.variants(kind))],
    ids=[f"{kind}/{v}" for _, kind in _HOLDUP for v in sorted(default_registry.variants(kind))],
)
def test_a_relief_is_on_the_crown_and_a_drain_at_the_low_point(cls, kind, variant):
    """The position is the role, so it is the position that is checked.

    CHEE4001 p.7 is the citable half: wherever it can be, the PSV goes on the
    protected system itself, upright, discharging upward, at the top of the
    container. A relief drawn on the floor is not a layout
    preference gone wrong -- it is a sheet asserting that the protective device
    vents the liquid. The vent is on the crown for the same reason a vapour
    space is at the top, and the drain at the low point because that is what a
    drain is.
    """
    from pandid.portgeom import port_faces

    unit = cls("X-1", variant=variant)
    for name, want in _ROLE_FACE.items():
        want = _DRAIN_FACES_SIDEWAYS.get((kind, variant, name), want)
        got = port_faces(unit, name)
        assert got == [want], (
            f"{kind}/{variant}.{name} is piped from {got} as drawn; the role puts it on {want}"
        )


def test_the_two_holdup_classes_offer_the_same_nozzles():
    """A tank and a vessel are one shell at two design pressures.

    Held here as well as in ``tests/test_units.py`` because this file is where
    the *drawings* are, and the pair only means anything if both families draw
    it: swapping ``Tank`` for ``Vessel`` on a sheet must not lose a connection.
    """
    assert list(units.Tank("T-1").ports) == list(units.Vessel("V-1").ports)


def test_the_reported_column_and_reactor_meet_their_streams():
    """The bug as reported, in the two sizes it was reported at.

    A 110 x 250 column drawn from a 100 x 200 symbol had its artwork scaled to
    fit and centred -- 110 x 220, with 15px of whitespace above and below -- so
    the distillate and bottoms lines stopped 15px short of the dished heads. An
    80 x 100 reactor from a 50 x 96.4 symbol came out 51.9 wide inside its 80,
    and both feed arrows stopped 14.1px short of the vessel wall. Both stencils
    are variable-aspect, so the artwork fills the box and the gap is gone.
    """
    from pandid import Flowsheet

    fs = Flowsheet("as reported")
    col = fs.add(units.Column("T-301", width=110, height=250)).pin(x=100, y=100)
    reactor = fs.add(units.Reactor("M-301", width=80, height=100)).pin(x=600, y=100)
    matrices = _placements(fs.to_svg(), _natives(fs))
    for unit in (col, reactor):
        sym = default_registry.for_unit(unit)
        frame = unit.frame
        matrix = matrices[(round(frame.cx, 6), round(frame.cy, 6))]
        # Whitespace is what the ports were floating in, so start there: the
        # artwork's own corners land on the box's, and there is none.
        assert _apply(matrix, 0.0, 0.0) == pytest.approx((frame.x, frame.y))
        assert _apply(matrix, sym.width, sym.height) == pytest.approx(
            (frame.x + frame.w, frame.y + frame.h)
        )
        drawn = [(_apply(matrix, *a), _apply(matrix, *b)) for a, b in _collect_segments(sym.svg)]
        for name in unit.ports:
            if (unit.kind, name) in _SIGNAL_PORTS:
                continue
            gap = _nearest_distance(port_point(unit, frame, name), drawn)
            assert gap <= GEOM_TOL, (
                f"{unit.name}.{name} is {gap:.1f}px from the nearest drawn stroke "
                f"of a {frame.w:g}x{frame.h:g} {unit.kind}"
            )


# ---------------------------------------------------------------------------
# Symbols the registry *derives* rather than registers.
#
# A reducer piped the other way round is an expansion, and the drawing for it is
# built from the reduction's on demand (SymbolRegistry.for_unit), so it is not in
# ``_SYMBOLS`` and nothing above sees it. It is a drawing a sheet puts ink on
# either way, so it answers to the same rules: every nozzle on the artwork, in
# the coordinates it was drawn in and in a box of any shape.
# ---------------------------------------------------------------------------

#: Every registered reducer, and the expander derived from it.
_TURNED = [
    (
        (kind, variant),
        sym,
        default_registry.for_unit(
            units.Reducer(f"RD-{variant}", variant=variant, large_end="outlet")
        ),
    )
    for (kind, variant), sym in _SYMBOLS
    if kind == "reducer"
]
_TURNED_IDS = [f"{kind}/{variant}" for (kind, variant), _, _ in _TURNED]


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fittings_ports_lie_on_drawn_geometry(entry):
    """The whole menu, on the mirrored artwork's own strokes."""
    (kind, variant), _, turned = entry
    segments = _collect_segments(turned.svg)
    for name, faces in turned.port_faces.items():
        for face, (x, y) in faces.items():
            d = _nearest_distance((x, y), segments)
            assert d <= GEOM_TOL, (
                f"{kind}/{variant} turned end for end: port_faces[{name!r}][{face!r}] "
                f"at ({x}, {y}) is {d:.1f}u from the nearest drawn stroke "
                f"(tolerance {GEOM_TOL})"
            )


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fitting_keeps_its_box_and_its_faces(entry):
    """Same box, same two faces, and no two nozzles on one point.

    The box is what the placement machinery sizes against, so a turned fitting
    that changed shape would move the run it sits in. The faces are what makes
    it a *turn* rather than a mirror: ``inlet`` stays on the west and ``outlet``
    on the east, so the flow still crosses the fitting the way it is drawn.
    """
    _, sym, turned = entry
    assert (turned.width, turned.height) == (sym.width, sym.height)
    assert turned.stretchable == sym.stretchable
    assert list(turned.port_faces["inlet"]) == ["W"]
    assert list(turned.port_faces["outlet"]) == ["E"]
    assert turned.coincident_ports() == []
    assert turned.symbol_id() != sym.symbol_id()


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fitting_opens_out_where_the_reduction_closes_in(entry):
    """The cone points the other way, which is the whole of what this draws.

    Measured as the drawn height of each end face: a reduction is tall on the
    west and short on the east, and the expansion is the two swapped. Nothing
    else distinguishes the two drawings, so nothing else would catch a
    derivation that returned the artwork unchanged.
    """
    _, sym, turned = entry

    def face_height(symbol: Symbol, x: float) -> float:
        """How much ink stands on the vertical line at ``x``."""
        ys = [
            y
            for (ax, ay), (bx, by) in _collect_segments(symbol.svg)
            for x0, y in ((ax, ay), (bx, by))
            if abs(x0 - x) <= BOX_EPS
        ]
        return max(ys) - min(ys)

    assert face_height(sym, 0.0) > face_height(sym, sym.width)
    assert face_height(turned, 0.0) < face_height(turned, turned.width)
    assert face_height(turned, 0.0) == pytest.approx(face_height(sym, sym.width))
    assert face_height(turned, turned.width) == pytest.approx(face_height(sym, 0.0))


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fittings_ports_land_on_drawn_ink_at_any_box_shape(entry):
    """The odd-box rule, for the drawing the registry derives.

    Its own jig rather than the shared one: ``odd_box_sheets`` places one unit
    per registered symbol and a turned fitting is not registered, so the sheet
    it would have to appear on does not exist until it is built here.
    """
    from pandid import Flowsheet

    (kind, variant), _, turned = entry
    segments = _collect_segments(turned.svg)
    for box in _ODD_BOXES:
        for placement in _PLACEMENTS:
            fs = Flowsheet("odd boxes, turned end for end")
            unit = units.Reducer(
                f"{kind}-{variant}",
                variant=variant,
                large_end="outlet",
                width=box[0],
                height=box[1],
            )
            fs.add(unit).pin(x=200, y=200, **placement)
            matrix = _placements(fs.to_svg(), _natives(fs))[
                (round(unit.frame.cx, 6), round(unit.frame.cy, 6))
            ]
            for name in unit.ports:
                d = _nearest_distance(_resolved_in_symbol_space(unit, matrix, name), segments)
                assert d <= GEOM_TOL + _ROUNDTRIP_EPS, (
                    f"{kind}/{variant} turned end for end: port {name!r} in a "
                    f"{box[0]:g}x{box[1]:g} box at {placement or 'no turn'} is "
                    f"{d:.1f}u from the nearest drawn stroke once the artwork's own "
                    f"placement is undone (tolerance {GEOM_TOL})"
                )


def _colliding_symbol(**kwargs) -> Symbol:
    """Build a Symbol that is *expected* to have coincident ports.

    Registering one warns (the engine consults the rule, not just this suite),
    so the warning is asserted here rather than left to leak into the report.
    """
    with pytest.warns(UserWarning, match="Only ports named in faceless_ports"):
        return Symbol(svg='<g id="sym_under_test"/>', **kwargs)


def test_authored_alternates_do_not_buy_a_shared_face():
    """Handing a vapour outlet a copy of the feed's menu gives both ports more
    than one placement, so a "the menu is multi-entry" exemption would wave the
    collision through, which is the point of naming faceless connections
    instead of inferring them from the shape of the menu."""
    sym = _colliding_symbol(
        width=91.5,
        height=30.0,
        ports={"feed": (0.0, 15.0), "vapor": (30.0, 0.0), "liquid": (68.0, 30.0)},
        port_faces={
            "feed": {"W": (0.0, 15.0), "N": (20.0, 0.0), "E": (91.5, 15.0)},
            "vapor": {"W": (0.0, 15.0), "E": (91.5, 15.0)},
        },
    )
    assert sym.coincident_ports() == [("feed", "vapor", (0.0, 15.0))]


def test_a_second_nozzle_on_an_alternates_own_coordinate_is_caught():
    """An outlet given the right head the inlet already offers lands two
    nozzles on (91.5, 15.0)."""
    sym = _colliding_symbol(
        width=91.5,
        height=30.0,
        ports={"inlet": (0.0, 15.0), "outlet": (68.0, 30.0)},
        port_faces={
            "inlet": {"W": (0.0, 15.0), "N": (20.0, 0.0), "E": (91.5, 15.0)},
            "outlet": {"E": (91.5, 15.0)},
        },
    )
    assert sym.coincident_ports() == [("inlet", "outlet", (91.5, 15.0))]


def test_faceless_connections_may_share_a_placement():
    """A balloon is a circle, so every signal connection offers every face and
    the overlap is a menu rather than a collision."""
    faces = {"N": (22.0, 0.0), "S": (22.0, 44.0), "W": (0.0, 22.0), "E": (44.0, 22.0)}
    ports = {"pv": (22.0, 44.0), "sig_in": (0.0, 22.0), "sig_out": (44.0, 22.0)}
    sym = Symbol(
        svg='<g id="sym_balloon"/>',
        width=44.0,
        height=44.0,
        ports=ports,
        port_faces={name: dict(faces) for name in ports},
        faceless_ports=frozenset(ports),
    )
    assert sym.coincident_ports() == []
    # ...but a nozzle that does own its face is still checked against them.
    with_stub = _colliding_symbol(
        width=44.0,
        height=44.0,
        ports={**ports, "tap": (22.0, 0.0)},
        port_faces={name: dict(faces) for name in ports},
        faceless_ports=frozenset(ports),
    )
    assert [(a, b) for a, b, _ in with_stub.coincident_ports()] == [
        ("pv", "tap"),
        ("sig_in", "tap"),
        ("sig_out", "tap"),
    ]


# --- what a symbol may declare -----------------------------------------------
#
# The checks above hold the shipped registry to these rules; Symbol's own
# constructor holds every symbol to them, including the third-party ones this
# suite never sees. Each is rejected rather than discarded in silence.


def test_a_placement_keyed_to_a_face_it_does_not_land_on_is_rejected():
    """The menu is re-keyed by coordinate at resolve time, so a mis-keyed
    alternate would not exist: it lands under the face it actually reaches,
    where it either clobbers the real entry or is clobbered by it."""
    with pytest.raises(ValueError, match=r"nearest the W edge"):
        Symbol(
            svg='<g id="sym_x"/>',
            width=91.5,
            height=30.0,
            ports={"feed": (30.0, 0.0)},
            port_faces={"feed": {"N": (0.0, 15.0)}},  # that point is on the west
        )


def test_an_alternate_on_a_ports_own_home_face_is_rejected():
    """``ports`` is the authority on the home nozzle, so an alternate keyed to
    the same face could only ever be overwritten by it."""
    with pytest.raises(ValueError, match=r"but ports\['feed'\] puts the same face at"):
        Symbol(
            svg='<g id="sym_x"/>',
            width=91.5,
            height=30.0,
            ports={"feed": (0.0, 15.0)},
            port_faces={"feed": {"W": (0.0, 12.0)}},  # the west head is already taken
        )


def test_a_menu_for_a_port_the_symbol_does_not_anchor_is_rejected():
    with pytest.raises(ValueError, match=r"declares a menu for \['nope'\]"):
        Symbol(
            svg='<g id="sym_x"/>',
            width=40.0,
            height=40.0,
            ports={"inlet": (0.0, 20.0)},
            port_faces={"nope": {"E": (40.0, 20.0)}},
        )


def test_a_faceless_port_the_symbol_does_not_anchor_is_rejected():
    with pytest.raises(ValueError, match=r"faceless_ports names \['typo'\]"):
        Symbol(
            svg='<g id="sym_x"/>',
            width=40.0,
            height=40.0,
            ports={"inlet": (0.0, 20.0)},
            faceless_ports=frozenset({"typo"}),
        )


def test_a_home_placement_restated_in_the_menu_is_accepted():
    """The vendored symbols emit the whole menu, home included, so restating it
    with the same coordinate has to stay legal."""
    sym = Symbol(
        svg='<g id="sym_x"/>',
        width=91.5,
        height=30.0,
        ports={"feed": (0.0, 15.0)},
        port_faces={"feed": {"W": (0.0, 15.0), "N": (20.0, 0.0)}},
    )
    assert list(sym.port_faces["feed"]) == ["W", "N"]  # home stays most preferred


# ---------------------------------------------------------------------------
# Port series: the families whose membership the unit decides, not the symbol.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,prefix,ctor_arg,face,variant",
    [
        ("mixer", "in_", "n_inlets", "W", "default"),
        ("splitter", "out_", "n_outlets", "E", "default"),
        ("column", "feed_", "n_feeds", "W", "default"),
        ("reactor", "feed_", "n_feeds", "W", "default"),
        ("reactor", "feed_", "n_feeds", "W", "plain"),
    ],
)
def test_every_member_of_a_port_series_gets_a_nozzle_of_its_own(
    kind, prefix, ctor_arg, face, variant
):
    """Without a series a Mixer's third inlet falls through to the centre of the
    box, landing on top of every other unplaced port -- three streams into one
    point in the middle of the triangle. Each member gets its own spot on
    the flat face, however many there are."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, is_anchored, resolve_size

    cls = {"mixer": U.Mixer, "splitter": U.Splitter, "column": U.Column, "reactor": U.Reactor}[kind]
    for count in range(2, 9):
        unit = cls("X", variant=variant, **{ctor_arg: count})
        w, h = resolve_size(unit)
        seen = []
        for i in range(1, count + 1):
            name = f"{prefix}{i}"
            assert is_anchored(unit, name), f"{kind} n={count}: {name} unplaced"
            placements = _drawn_placements(unit, name, w, h, 0, False, False)
            assert list(placements) == [face], f"{kind} n={count}: {name} off-face"
            ((x, y),) = placements.values()
            assert 0.0 <= y <= h, f"{kind} n={count}: {name} outside the box"
            seen.append(y)
        assert len(set(seen)) == count, f"{kind} n={count}: ports share a point"
        assert seen == sorted(seen), f"{kind} n={count}: ports out of order"


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_series_members_lie_on_drawn_geometry(entry):
    """A family is placed by rule rather than authored point by point, so
    nothing else checks that the rule keeps its members on the vessel: a band
    reaching past the straight shell puts the last feed on a dished head."""
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    segments = _collect_segments(sym.svg)
    for series in sym.port_series:
        for count in range(1, 9):
            for index in range(count):
                x, y = series.placement(index, count, sym.width, sym.height)
                d = _nearest_distance((x, y), segments)
                assert d <= GEOM_TOL, (
                    f"{kind}/{variant} {series.prefix}{index + 1} of {count} at "
                    f"({x}, {y}) is {d:.1f}u from the nearest drawn stroke"
                )


def test_a_lone_member_lands_where_the_fixed_nozzle_did():
    """One feed is the count every existing reactor sheet was drawn with, so the
    family has to reproduce that nozzle exactly -- otherwise supporting a second
    feed moves the first one on every drawing already issued.

    The column is the one family this does not hold for, and the test below is
    why: its pre-family nozzle was not somewhere its family could be centred.

    The number for ``default`` is the *body's*, and the body changed with this
    drawing: the stirred tank is now the same dished-end cylinder the vessel and
    the flash drum are cut from (62 x 100), so its charge nozzle is at the middle
    of the straight wall rather than at the middle of the "Mixing Reactor"
    stencil's. What the check is for is unchanged -- the lone feed lands where a
    single fixed nozzle would, and adding a second does not move it -- and the
    ``mixing`` row below is the old body, still answering the old number."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, resolve_size

    for unit, want in (
        # The stirred tank's drawing is taller than its body: ISO item 1.27
        # X8006's motor hangs above the crown, so the composed box grows by
        # the motor's own diameter (a third of the 62-wide shell) plus the
        # ninth of the body's height of clear air under it, and the shell
        # moves down into it. 50 is still the middle of the straight wall.
        (U.Reactor("R"), (0.0, 50.0 + 62.0 / 3 + 100.0 / 9)),
        (U.Reactor("R", variant="mixing"), (0.0, 48.2)),
        (U.Reactor("R", variant="plain"), (0.0, 30.0)),
    ):
        w, h = resolve_size(unit)
        placed = _drawn_placements(unit, "feed", w, h, 0, False, False)
        assert list(placed) == ["W"]
        assert placed["W"] == pytest.approx(want)


def test_a_lone_column_feed_sits_at_the_centre_of_the_duty_band():
    """The column bought the rule above and could not pay: its pre-family nozzle
    was at y = 130, and 130 is not the centre of the band its feeds have to stay
    inside (65..145, between the duty arrows).

    Centring the family there put the second feed at 147.5, below the reboiler
    duty arrow, so one of the two claims had to go. The band is the one that
    says something about the equipment, while 130 was only ever the height a
    single nozzle happened to be drawn at, so the lone feed moved the 25 up to
    the centre and every column sheet moved with it."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, resolve_size

    for variant in default_registry.variants("column"):
        unit = U.Column("T", variant=variant)
        w, h = resolve_size(unit)
        placed = _drawn_placements(unit, "feed", w, h, 0, False, False)
        assert list(placed) == ["W"], f"column/{variant}"
        assert placed["W"] == pytest.approx((0.0, 105.0)), f"column/{variant}"


def test_a_feed_family_reaching_the_return_nozzles_is_caught():
    """The feeds are on the tower's west wall and the returns on its east one,
    which is what keeps them apart however many feeds there are. Put the family
    on the returns' face and the band covers both of them -- and a collision a
    count away is still a collision, so the check has to say so."""
    from pandid.render.symbols import PortSeries

    column = default_registry.get("column")
    clash = _colliding_symbol(
        width=column.width,
        height=column.height,
        ports=dict(column.ports),
        port_series=(PortSeries("feed_", "E", pitch=35.0, extent=0.9, at=100.0, singular="feed"),),
    )
    assert clash.coincident_ports() == [
        ("feed_*", "reflux_in", (100.0, 35.0)),
        ("boilup_in", "feed_*", (100.0, 175.0)),
        ("condenser_duty", "feed_*", (100.0, 65.0)),
        ("feed_*", "reboiler_duty", (100.0, 145.0)),
    ]


def test_the_shipped_feed_families_reach_nothing_else():
    """The column and both reactors ship a feed family beside fixed nozzles;
    each is the case the check above exists to protect."""
    for kind, variant in (("column", "default"), ("reactor", "default"), ("reactor", "plain")):
        sym = default_registry.get(kind, variant)
        assert sym.port_series, f"{kind}/{variant} has no feed family"
        assert sym.coincident_ports() == [], f"{kind}/{variant}"


@pytest.mark.parametrize("variant", default_registry.variants("column"))
def test_every_column_feed_stays_between_the_duty_arrows(variant):
    """A tower's feeds land between the two duty arrows at every count.

    ``coincident_ports`` above compares a family's band against nozzles that
    resolve to the same *point*, so it only ever reaches the face the family is
    on. The feeds are on the west wall and every nozzle worth clearing is on the
    east, which is why nothing said how far down the shell a feed could be
    drawn, and why the shipped rule ran the second feed of two out below
    ``reboiler_duty`` while the comment over it claimed the opposite.

    The two duty arrows are the innermost fixed nozzles on the opposite wall
    (65 and 145, against ``reflux_in``'s 35 and ``boilup_in``'s 175), so a feed
    inside the band they bound is clear of all four: none is drawn at the
    elevation of anything the tower returns to.

    The band is read off the symbol rather than written down here, so the claim
    follows the drawing, and each feed is resolved through ``portgeom`` on a
    real ``Column`` rather than by re-deriving ``PortSeries``' arithmetic, which
    would only prove this test agrees with itself.
    """
    from pandid import units as U
    from pandid.portgeom import port_offset

    sym = default_registry.get("column", variant)
    lo, hi = sym.ports["condenser_duty"][1], sym.ports["reboiler_duty"][1]
    assert lo < hi, f"column/{variant}: the duty arrows bound no band at all"
    (family,) = sym.port_series
    # Past three the run is squeezed into ``extent`` rather than pitched (see
    # the KIND_MAP comment), so both regimes have to be walked: the defect was a
    # band wider than the one the duty arrows bound, *and* centred below it.
    for count in range(1, 13):
        column = U.Column("T", variant=variant, n_feeds=count)
        feeds = [name for name in column.ports if family.matches(name)]
        assert len(feeds) == count, f"column/{variant} n_feeds={count}: {feeds}"
        for name in feeds:
            y = port_offset(column, name)[1]
            assert lo < y < hi, (
                f"column/{variant} {name} of {count} sits at y={y}, outside the "
                f"({lo}, {hi}) band the duty arrows bound"
            )


def test_two_series_ports_land_where_the_symbol_used_to_draw_them():
    """The two-port case is the one every existing sheet draws, so the spacing
    rule has to reproduce the fixed-symbol coordinates exactly rather than
    merely closely -- otherwise accommodating a third port shifts every mixer
    and splitter on every drawing."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements

    mixer = U.Mixer("M", n_inlets=2)
    assert [_drawn_placements(mixer, f"in_{i}", 50, 50, 0, False, False)["W"] for i in (1, 2)] == [
        (0.0, 15.0),
        (0.0, 35.0),
    ]
    splitter = U.Splitter("S", n_outlets=2)
    assert [
        _drawn_placements(splitter, f"out_{i}", 50, 50, 0, False, False)["E"] for i in (1, 2)
    ] == [(50.0, 15.0), (50.0, 35.0)]


def test_a_series_may_not_restate_a_port_the_symbol_already_anchors():
    """Two authorities on one port's position is the bug the series exists to
    remove, so declaring both is rejected rather than silently resolved."""
    from pandid.render.symbols import PortSeries

    with pytest.raises(ValueError, match=r"only authority"):
        Symbol(
            svg='<g id="sym_x"/>',
            width=50.0,
            height=50.0,
            ports={"in_1": (0.0, 15.0), "outlet": (50.0, 25.0)},
            port_series=(PortSeries("in_", "W"),),
        )


def test_heater_and_cooler_are_one_stencil_pair():
    """They are the same circle and zigzag with the duty arrow reversed, so
    they have to be the same size: a utility cooler drawn half again bigger
    than the heater beside it reads as a different class of equipment. Taking
    the cooler from "Heat Exchanger (Spiral)" instead -- a 100x100 stencil for a
    different machine -- draws it larger than the reactor upstream."""
    heater = default_registry.get("heater", "default")
    cooler = default_registry.get("cooler", "default")
    assert (cooler.width, cooler.height) == (heater.width, heater.height)
    assert cooler.ports["inlet"] == heater.ports["inlet"]
    assert cooler.ports["outlet"] == heater.ports["outlet"]
    # Heat in from below, heat out through the top.
    assert outward_dir(*heater.ports["utility_in"], heater.width, heater.height) == "S"
    assert outward_dir(*cooler.ports["utility_out"], cooler.width, cooler.height) == "N"
    # And the spiral exchanger is reachable under the kind it belongs to.
    spiral = default_registry.get("hex", "spiral")
    assert (spiral.width, spiral.height) == (100.0, 100.0)
    assert set(spiral.ports) == {"side_a_in", "side_a_out", "side_b_in", "side_b_out"}


def test_a_nozzle_standing_in_a_series_band_is_a_collision():
    """A series has no fixed membership, so it has no fixed points to compare a
    nozzle against. The band it may place a member on is what a collision check
    has to test instead. A nozzle inside the stretch of face a series may place
    a member on shares a placement with one for some count, and a static check
    exists to say so before anything is drawn."""
    from pandid.render.symbols import PortSeries

    with pytest.warns(UserWarning, match=r"both have a placement"):
        clash = Symbol(
            svg='<g id="sym_clash"/>',
            width=50.0,
            height=50.0,
            ports={"tap": (0.0, 25.0)},  # dead centre of the W face
            port_series=(PortSeries("in_", "W"),),
        )
    assert clash.coincident_ports() == [("in_*", "tap", (0.0, 25.0))]


def test_a_nozzle_clear_of_the_series_band_is_not_a_collision():
    """The band is the middle ``extent`` of the face, not the whole of it: a
    nozzle out at the corner is somewhere a member can never be put."""
    from pandid.render.symbols import PortSeries

    clear = Symbol(
        svg='<g id="sym_clear"/>',
        width=50.0,
        height=50.0,
        ports={"tap": (0.0, 2.0)},  # outside the 70% band
        port_series=(PortSeries("in_", "W"),),
    )
    assert clear.coincident_ports() == []


def test_a_series_on_another_face_is_not_a_collision():
    """A splitter's inlet sits on the point of the triangle while its outlets
    spread along the opposite face, the shipped case that must stay quiet."""
    assert default_registry.get("splitter").coincident_ports() == []
    assert default_registry.get("mixer").coincident_ports() == []


# ---------------------------------------------------------------------------
# Looking a variant up.
# ---------------------------------------------------------------------------


def test_variants_lists_a_kinds_catalogue_default_first():
    assert default_registry.variants("tank") == [
        "default",
        "conical",
        "conical_bottom",
        "conical_ends",
        "dished_roof_conical_bottom",
        "floating_roof",
        "gas_holder",
        "sphere",
    ]


def test_an_unregistered_variant_raises_naming_the_ones_that_exist():
    """Falling back to the kind's default would let a typo draw the plain
    symbol, which comes out of the printer looking like a drawing decision."""
    with pytest.raises(ValueError) as excinfo:
        default_registry.get("vessel", "dishd")
    message = str(excinfo.value)
    assert "vessel has no variant 'dishd'" in message
    assert "did you mean 'dished'?" in message
    for variant in default_registry.variants("vessel"):
        assert variant in message


def test_a_variant_typo_stops_the_sheet_rather_than_drawing_something_else():
    """The registry is looked up at render time, so that is where a name
    nobody registered has to be caught -- not at construction, which a later
    assignment to unit.variant would walk straight past."""
    from pandid import Flowsheet, units as U

    fs = Flowsheet("typo")
    feed = fs.add(U.Feed("F"))
    tank = fs.add(U.Tank("TK-1", variant="dished"))
    fs.connect(feed.outlet, tank.inlet)
    with pytest.raises(ValueError, match=r"tank has no variant 'dished'"):
        fs.to_svg()


def test_a_kind_with_no_symbols_at_all_still_draws_a_generic_box():
    """The fallback that is load-bearing: a Unit subclass registered by nobody
    has no catalogue for its variant to be measured against, so there is no
    name to reject and a generic box is the only honest answer."""
    assert default_registry.variants("no_such_kind") == []
    assert default_registry.get("no_such_kind").symbol_id() == "sym_generic"
    assert default_registry.get("no_such_kind", "anything").symbol_id() == "sym_generic"


# ---------------------------------------------------------------------------
# The generated file, against the generator that emits it.
#
# ``_vendored_symbols.py`` is written wholesale by scripts/vendor_symbols.py and
# its own docstring says not to edit it, but nothing enforced that: a stale or
# hand-edited copy still imports, still draws, and still passes every check
# above, because every check above measures the registry rather than the mapping
# the registry was built from. Regenerating in memory and comparing is what turns
# "do not edit by hand" from a request into a rule.
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _script(name: str):
    """Import one of the dev-only generator scripts by path.

    They are not part of the package and not importable as one; ``scripts/``
    puts itself on ``sys.path`` when loaded, so this only has to find the file.
    """
    import importlib.util

    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_pandid_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clip(line: str, column: int, width: int = 90) -> str:
    """``line`` windowed on ``column``, for a file whose ``svg=`` lines run to
    thousands of characters. Printing one of those whole shows the reader
    nothing; the neighbourhood of the character the two files part company on is
    the part that identifies the edit."""
    if len(line) <= 2 * width:
        return line
    lo, hi = max(0, column - width), min(len(line), column + width)
    return ("..." if lo else "") + line[lo:hi] + ("..." if hi < len(line) else "")


def _generator_diff(committed: str, generated: str, context: int = 2) -> str:
    """First divergence with a little context -- not a 95KB dump.

    The inequality of two 950-line files says nothing on its own, and the whole
    diff of a regenerated library is unreadable, so this is the first line they
    disagree on and a couple either side: enough to recognise one's own edit.
    """
    old, new = committed.split("\n"), generated.split("\n")
    total = max(len(old), len(new))
    row = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    a = old[row] if row < len(old) else ""
    b = new[row] if row < len(new) else ""
    column = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    out = [f"first divergence at line {row + 1} of {total}, column {column + 1}:"]
    for k in range(max(0, row - context), min(total, row + context + 1)):
        mark = ">>" if k == row else "  "
        for label, lines in (("committed", old), ("regenerated", new)):
            text = _clip(lines[k], column) if k < len(lines) else "<no line>"
            out.append(f"{mark} [{k + 1}] {label}: {text}")
    return "\n".join(out)


def test_the_generated_symbols_match_the_generator():
    """A hand edit to _vendored_symbols.py is lost the next time anyone runs the
    generator, and the drawing silently reverts. Say so here instead."""
    vendor = _script("vendor_symbols")
    # ``vendor.OUT`` rather than the path written out a second time here, so the
    # two things compared are exactly the two the generator relates: what it
    # emits, and where it puts it. Whether the interpreter imported *this*
    # checkout's copy is not this test's business -- every check above measures
    # the registry that import produced, so a run against some other installed
    # copy is already measuring the wrong library throughout.
    #
    # Text mode at both ends, so this compares lines and not line endings:
    # read_text() folds a CRLF working tree back to "\n", which is what render()
    # joins with, and a ``text=auto`` .gitattributes could not turn it red.
    committed = vendor.OUT.read_text(encoding="utf-8")
    generated = vendor.render()
    if generated != committed:
        pytest.fail(
            f"{vendor.OUT.name} is not what scripts/vendor_symbols.py emits today.\n"
            "It is regenerated wholesale, so a hand edit to it is lost the next time\n"
            "anyone runs the generator, and the drawing silently reverts. Change the\n"
            "KIND_MAP entry (or the stencil patch) that produces it, then run\n\n"
            "    python scripts/vendor_symbols.py\n\n"
            "and commit the regenerated file with the change that caused it.\n\n"
            + _generator_diff(committed, generated),
            pytrace=False,
        )


# ---------------------------------------------------------------------------
# Where stretchability comes from.
#
# A draw.io stencil declares whether its shape may be reshaped, and scripts/
# carries that declaration into ``Symbol.stretchable``. Every shape KIND_MAP
# names happens to be a "variable" one, so nothing in the shipped registry
# exercises the other half of the reader -- which is exactly why it is exercised
# here, and why the claim that leaves the generated file free of the keyword is
# written down rather than left to be rediscovered.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "declared,aspect",
    [('aspect="fixed" ', "fixed"), ('aspect="variable" ', "variable"), ("", "variable")],
)
def test_the_converter_reports_a_stencil_shapes_aspect(declared, aspect):
    """Including the shape that names none: mxGraph's own default is
    "variable", so a stencil that says nothing is saying it may be stretched."""
    shape = ET.fromstring(
        f'<shape {declared}w="100" h="50"><foreground>'
        f'<rect x="0" y="0" w="100" h="50"/><stroke/></foreground></shape>'
    )
    assert _script("mxgraph_to_svg").convert_shape(shape)[4] == aspect


def test_every_stencil_shape_the_generator_vendors_may_be_stretched():
    """All 24 "fixed" shapes in the stencil set are draw.io's own instrument
    balloons, which pandid draws itself; nothing KIND_MAP names is one. That is
    why no symbol in the generated file carries ``stretchable=False`` -- if one
    day one does, this test is what says the pipeline put it there."""
    vendor = _script("vendor_symbols")
    fixed = []
    for stencil in sorted({entry[0] for entry in vendor.KIND_MAP.values()}):
        wanted = {shape for s, shape, _ in vendor.KIND_MAP.values() if s == stencil}
        for name, el in vendor.shapes_in(vendor.STENCILS / f"{stencil}.xml"):
            if name in wanted and el.get("aspect", "variable") != "variable":
                fixed.append(f"{stencil}:{name}")
    assert fixed == []
    vendored = [
        (kind, variant)
        for (kind, variant), sym in _SYMBOLS
        if (kind, variant) in vendor.KIND_MAP and not sym.stretchable
    ]
    assert vendored == []


# ---------------------------------------------------------------------------
# What a fill comes out as.
#
# mxGraph paint ops name the operation, not the colour: a fill is painted in
# the canvas's current fill colour, which <fillcolor> sets. Reading a bare
# <fill> as "make this black" turned the floating-roof tank into a solid block
# -- a defect no reader could diagnose, because a block is a perfectly
# plausible thing to have drawn on purpose. These pin the distinction, because
# only three shapes in the whole stencil set use a bare <fill> and it would
# otherwise be one symbol's business.
# ---------------------------------------------------------------------------


def _converted_fills(body: str) -> list[str]:
    """Every ``fill=`` the converter emits for one stencil <foreground>."""
    shape = ET.fromstring(f'<shape w="10" h="10"><foreground>{body}</foreground></shape>')
    return re.findall(r'fill="([^"]*)"', _script("mxgraph_to_svg").convert_shape(shape)[0])


def _painted(ops: str) -> list[str]:
    """The fills for a single rect painted by ``ops``."""
    return _converted_fills(f'<rect x="0" y="0" w="10" h="10"/>{ops}')


def test_a_fill_takes_the_paper_until_the_stencil_asks_for_ink():
    """The fill colour starts at the paper, which is what draw.io fills these
    shapes with -- for <fill> exactly as for <fillstroke>, since both paint the
    same canvas state. A bare <fill> is that background wash and it is opaque:
    a stencil draws its body last and expects it to cover the nozzles and legs
    behind it. <stroke> paints no fill whatever the state is."""
    assert _painted("<fillstroke/>") == ["white"]
    assert _painted("<stroke/>") == ["none"]
    assert _painted("<fill/>") == ["white"]


def test_fillcolor_is_how_a_stencil_asks_for_a_solid_shape():
    """It is the idiom draw.io's own shapes use for a damper's pivot and a
    flow arrow's head, and the converter has to keep it: making the converter
    incapable of a solid would trade one wrong drawing for another."""
    assert _painted('<fillcolor color="#000000"/><fillstroke/>') == ["#111"]
    assert _painted('<fillcolor color="#000000"/><fill/>') == ["#111"]
    # mxGraph's two keywords: "stroke" means the ink, "none" transparent --
    # which is the stencil turning the fill off, not the state it started in.
    assert _painted('<fillcolor color="stroke"/><fillstroke/>') == ["#111"]
    assert _painted('<fillcolor color="none"/><fillstroke/>') == ["none"]


def test_save_and_restore_bracket_the_fill_colour():
    """Several stencils set a fill colour inside <save>/<restore> and expect
    the next shape to be back on the paper; without the stack the ink leaks
    forward and blacks out the rest of the drawing."""
    assert _converted_fills(
        '<save/><rect x="0" y="0" w="4" h="4"/><fillcolor color="#000000"/><fillstroke/>'
        '<restore/><rect x="5" y="5" w="4" h="4"/><fillstroke/>'
    ) == ["#111", "white"]


def test_the_sphere_draws_its_shell_over_its_nozzles():
    """The symbol the fill is most load-bearing on. Its crown stubs
    straddle the shell -- each 12-unit box spans y 0..12 and the shell
    is at y 11.6 under the left one's outer edge -- so the arc crosses
    the box for its whole width and read as a crack in the vessel
    (#268). The stencil answers that by painting the shell last and
    filled, which trims each stub at the shell."""
    svg = default_registry.get("tank", "sphere").svg
    assert svg.rindex("<ellipse") > svg.rindex("<rect"), "the shell is drawn last"
    shell = re.search(r"<ellipse[^>]*>", svg)
    assert 'fill="white"' in shell.group(0), "and is opaque, so it covers them"


# ---------------------------------------------------------------------------
# The curve a split arc draws.
#
# An arc whose chord is about its own diameter comes out visibly thick in
# cairosvg, so the converter splits it into quarter-turn pieces. That split has
# to be an identity on the shape: same ellipse, same two ends, more commands and
# nothing else.
#
# It was not one. ``_endpoint_to_center`` applies the spec's radius correction
# (SVG 1.1 F.6.6: radii too small to span their chord are scaled up until they
# exactly span it), and the converter cut the pieces on that corrected ellipse
# but labelled every one of them with the stencil's uncorrected radii. Each
# piece was then too small for its own, shorter chord, so the reader corrected
# it a second time -- separately, against a different chord, onto a different
# ellipse per piece. The ends stayed exact, which is why every port, every crown
# and every bounding box was right and nothing else in this file noticed: only
# the curve *between* the ends was wrong. On the 40-wide vessel shells the two
# halves of a dished head met in a cusp instead of an apex.
#
# The invariant below is the identity the split claims. It is checked here
# rather than on the shipped SVG because a piece drawn on the wrong ellipse is
# still a perfectly well-formed arc, and the ellipse it *should* have been cut
# from cannot be recovered from it -- the two are only both in hand while the
# stencil is being converted.
# ---------------------------------------------------------------------------

#: One emitted ``A``: rx, ry, x-axis-rotation, large-arc flag, sweep flag, x, y.
_EMITTED_ARC = re.compile(rf"A ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM})")

#: How far a piece's ellipse may sit from the whole arc's, in stencil units.
#: The pieces are written out to four decimal places and their centres are
#: recovered from those, so this is that rounding and nothing else. The defect
#: it replaced put a vessel head's centre 10 units out.
_ARC_TOL = 1e-3

#: Where each stencil path op leaves the pen. An <arc> is stated relative to
#: wherever the previous op left it, so finding one means walking to it.
_PEN_LANDS_AT = {
    "move": ("x", "y"),
    "line": ("x", "y"),
    "quad": ("x2", "y2"),
    "curve": ("x3", "y3"),
}


def _stencil_arcs() -> list[tuple[str, tuple]]:
    """Every <arc> in every shape ``KIND_MAP`` draws, with the point it starts at.

    Keyed by shape rather than by (kind, variant): several symbols share one
    drawing, and converting it once per symbol would only convert it twice.
    """
    mx, vendor = _script("mxgraph_to_svg"), _script("vendor_symbols")
    shapes = sorted({(stencil, shape) for stencil, shape, _ in vendor.KIND_MAP.values()})
    index = {}
    for stencil in sorted({stencil for stencil, _ in shapes}):
        for name, el in vendor.shapes_in(vendor.STENCILS / f"{stencil}.xml"):
            index[(stencil, name)] = vendor.patch_shape(stencil, name, el)
    found: list[tuple[str, tuple]] = []
    for key in shapes:
        for section in ("background", "foreground"):
            sec = index[key].find(section)
            for path in sec if sec is not None else ():
                if path.tag != "path":
                    continue
                x = y = sx = sy = 0.0
                for op in path:
                    if op.tag == "arc":
                        ex, ey = mx._num(op, "x"), mx._num(op, "y")
                        rx, ry = mx._num(op, "rx"), mx._num(op, "ry")
                        # A degenerate radius is a straight line, and the
                        # converter emits it verbatim rather than splitting it.
                        # No stencil in the set has one; the guard is here so
                        # that one added later fails the generator and not this.
                        if min(abs(rx), abs(ry)) > 0:
                            found.append(
                                (
                                    f"{key[0]}:{key[1]}",
                                    (
                                        x,
                                        y,
                                        rx,
                                        ry,
                                        mx._num(op, "x-axis-rotation"),
                                        int(op.get("large-arc-flag", "0")),
                                        int(op.get("sweep-flag", "0")),
                                        ex,
                                        ey,
                                    ),
                                )
                            )
                        x, y = ex, ey
                    elif op.tag == "close":
                        x, y = sx, sy
                    elif op.tag in _PEN_LANDS_AT:
                        ax, ay = _PEN_LANDS_AT[op.tag]
                        x, y = mx._num(op, ax), mx._num(op, ay)
                        if op.tag == "move":
                            sx, sy = x, y
    return found


def _arc_ids(arcs: list[tuple[str, tuple]]) -> list[str]:
    """``vessels:Vessel (Dome)#2`` -- the shape, and which of its arcs."""
    seen: dict[str, int] = {}
    ids = []
    for shape, _ in arcs:
        seen[shape] = seen.get(shape, 0) + 1
        ids.append(f"{shape}#{seen[shape]}")
    return ids


_STENCIL_ARCS = _stencil_arcs()


@pytest.mark.parametrize("shape,arc", _STENCIL_ARCS, ids=_arc_ids(_STENCIL_ARCS))
def test_every_piece_of_a_split_arc_rides_the_ellipse_it_was_cut_from(shape, arc):
    """One ellipse -- same centre, same radii -- for every piece and the whole.

    Both sides go through the spec's own endpoint-to-centre conversion, which is
    what a reader does with the numbers that end up in the file. So this
    compares the ellipse the drawing will be *read* as against the one the
    stencil asked for, rather than comparing the converter with itself.

    The pieces have to chain end to end and land on the arc's own far end too:
    pieces on the right ellipse that did not join up would be a different
    drawing again. An arc the converter leaves whole is one piece and passes
    this trivially, which is the point -- the claim is about the shape, and the
    shape does not depend on how many commands it took.
    """
    mx = _script("mxgraph_to_svg")
    x0, y0, rx, ry, phi_deg, fa, fs, x1, y1 = arc
    want = mx._endpoint_to_center(x0, y0, rx, ry, math.radians(phi_deg), fa, fs, x1, y1)[:4]
    pieces = _EMITTED_ARC.findall(mx._arc_to_path(x0, y0, rx, ry, phi_deg, fa, fs, x1, y1))
    assert pieces, f"{shape}: the converter emitted no arc at all"
    px, py = x0, y0
    for i, (prx, pry, pphi, plaf, psf, ex, ey) in enumerate(pieces, start=1):
        ex, ey = float(ex), float(ey)
        got = mx._endpoint_to_center(
            px, py, float(prx), float(pry), math.radians(float(pphi)), int(plaf), int(psf), ex, ey
        )[:4]
        assert got == pytest.approx(want, abs=_ARC_TOL), (
            f"{shape}: piece {i} of {len(pieces)} is an arc of the ellipse centred "
            f"({got[0]:.4f}, {got[1]:.4f}) with radii ({got[2]:.4f}, {got[3]:.4f}), but the "
            f"arc it was cut from is centred ({want[0]:.4f}, {want[1]:.4f}) with radii "
            f"({want[2]:.4f}, {want[3]:.4f})"
        )
        px, py = ex, ey
    assert (px, py) == pytest.approx((x1, y1), abs=_ARC_TOL), (
        f"{shape}: the pieces run from ({x0}, {y0}) to ({px}, {py}), not to the arc's "
        f"own far end ({x1}, {y1})"
    )


# ---------------------------------------------------------------------------
# Corrections applied to the vendored stencils.
# ---------------------------------------------------------------------------


def test_every_stencil_patch_still_finds_its_shape():
    """A patch matching nothing is a correction that has quietly stopped being
    applied, and the drawing reverts to the defect it was written for. The
    generator refuses to run in that case; this makes the same claim without
    regenerating anything, so it fails in CI rather than on the next person's
    laptop."""
    vendor = _script("vendor_symbols")
    assert vendor.STENCIL_PATCHES, "the patch table is where a stencil defect is recorded"
    for stencil, shape in vendor.STENCIL_PATCHES:
        names = {name for name, _ in vendor.shapes_in(vendor.STENCILS / f"{stencil}.xml")}
        assert shape in names, f"{stencil}.xml has no shape {shape!r} to patch"


def test_the_globe_and_ball_valves_are_not_one_drawing():
    """draw.io ships "Globe Valve" as a byte-for-byte copy of "Ball Valve":
    both draw the bowtie pinched around an OPEN seat, which is the ball valve.
    Two valves drawing one symbol is not a plain drawing, it is the wrong one,
    since the reader has no way to tell which is in the line. The globe's seat
    is filled; everything else about the pair -- box, nozzles, alternates --
    stays identical, because they are the same body."""
    globe = default_registry.get("valve", "globe")
    ball = default_registry.get("valve", "ball")
    assert _artwork(globe) != _artwork(ball)
    assert 'fill="#111"' in globe.svg, "the globe's seat is solid"
    assert 'fill="#111"' not in ball.svg, "the ball's seat is open"
    assert (globe.width, globe.height) == (ball.width, ball.height)
    assert globe.ports == ball.ports
    assert globe.port_faces == ball.port_faces


def test_every_paired_shape_is_one_device_in_two_positions():
    """``CLOSED_SHAPES`` names the second drawing of a device ``KIND_MAP``
    already draws -- a spectacle blind's blanked state -- and the generator
    refuses a pair whose boxes, nozzles or aspect disagree, or whose artwork
    does not.

    Asserted here over the *shipped* registry, so the claim holds without
    regenerating anything. The two drawings are also required to put their ink
    in the same places: that is what carries every geometry invariant above,
    proven for the open drawing, onto the closed one, which the parametrized
    sweep does not reach because it is not a variant of its own."""
    vendor = _script("vendor_symbols")
    assert vendor.CLOSED_SHAPES, "the table is where a two-position device is recorded"
    for (kind, variant), shape in vendor.CLOSED_SHAPES.items():
        assert (kind, variant) in vendor.KIND_MAP, f"{kind}/{variant} is drawn by nothing"
        stencil = vendor.KIND_MAP[(kind, variant)][0]
        names = {name for name, _ in vendor.shapes_in(vendor.STENCILS / f"{stencil}.xml")}
        assert shape in names, f"{stencil}.xml has no shape {shape!r}"
        opened = default_registry.get(kind, variant)
        closed = default_registry.closed_symbol(kind, variant)
        assert closed is not None, f"{kind}/{variant} registered no closed drawing"
        assert (closed.width, closed.height) == (opened.width, opened.height)
        assert closed.ports == opened.ports
        assert closed.port_faces == opened.port_faces
        assert closed.stretchable == opened.stretchable
        assert closed.id_suffix and not opened.id_suffix, "two drawings, two <defs> ids"
        assert _artwork(closed) != _artwork(opened), "the position must be drawn"
        assert _collect_segments(closed.svg) == _collect_segments(opened.svg), (
            f"{kind}/{variant}: the two positions must differ in ink alone, so that "
            f"every port checked against the open drawing is checked against both"
        )


def test_a_closed_drawing_may_not_be_registered_without_an_open_one():
    """The pairing is what keeps the closed state from becoming a variant name
    of its own, so a closed drawing with nothing to be the closed state *of* is
    refused rather than filed under a key nobody looks up."""
    from pandid.render.symbols import SymbolRegistry

    sym = Symbol(svg='<g id="sym_x"/>', width=10.0, height=10.0, ports={"inlet": (0.0, 5.0)})
    with pytest.raises(ValueError, match="no open drawing"):
        SymbolRegistry().register_closed("fitting", sym, "no_such_variant")


def _artwork(sym: Symbol) -> str:
    """A symbol's drawing, with the id that names it stripped off."""
    return re.sub(r'id="[^"]*"', "", sym.svg)


def _ink_extents(svg: str) -> list[tuple[str, float, float]]:
    """(tag, width, height) of every element painted in ink, in symbol space.

    An element is flattened in its own coordinates and then carried out through
    its ancestors' transforms, so a valve's ``scale(0.25)`` is accounted for and
    the extent is comparable with ``Symbol.width``/``height``. <text> has no
    geometry to flatten and so never appears: an operator letter is ink by
    definition and is not what this measures.
    """
    found: list[tuple[str, float, float]] = []

    def walk(el, m: Matrix) -> None:
        tag = el.tag.split("}")[-1]
        if el.get("fill", "none") not in ("none", "white"):
            solo = _collect_segments(f"<g>{ET.tostring(el, encoding='unicode')}</g>")
            points = [_apply(m, *p) for seg in solo for p in seg]
            if points:
                xs = [x for x, _ in points]
                ys = [y for _, y in points]
                found.append((tag, max(xs) - min(xs), max(ys) - min(ys)))
        child_m = _compose(m, _parse_transform(el.get("transform", "")))
        for child in el:
            walk(child, child_m)

    walk(ET.fromstring(svg), _IDENTITY)
    return found


#: How much of a symbol's box a filled shape may cover before it stops reading
#: as a feature of the body and starts reading as the body. The globe's seat,
#: the widest thing any valve fills, covers 27% of it.
_FEATURE_AREA = 0.5


def _body_fill(sym: Symbol) -> float:
    """The largest share of a symbol's box any one filled element covers."""
    return max(
        [(w * h) / (sym.width * sym.height) for _, w, h in _ink_extents(sym.svg)], default=0.0
    )


def test_no_valve_body_is_drawn_filled():
    """A fully darkened valve body is its own convention -- normally closed,
    PIP PIC001 4.2.2.7 -- so no symbol may spend that reading by accident.

    The globe's seat is an interior feature of a body whose two triangles keep
    their white interiors, which is what holds the two apart at sheet scale. A
    valve that filled its *outline* would be claiming something else entirely,
    and would do it silently, since a solid bowtie is a perfectly plausible
    thing to have drawn on purpose.

    Every valve a flowsheet can put in a line is checked, resolved the way the
    renderer resolves it. The one exemption is a valve *declared* normally
    closed, which is filled on purpose and is the subject of the next test:
    the claim here is that nothing is filled by accident, and a declaration is
    the opposite of an accident."""
    for variant in default_registry.variants("valve"):
        valve = units.Valve("HV-1", variant=variant)
        assert valve.normal_position == "open", "an undeclared valve is not marked"
        sym = default_registry.for_unit(valve)
        for tag, w, h in _ink_extents(sym.svg):
            covered = (w * h) / (sym.width * sym.height)
            assert covered < _FEATURE_AREA, (
                f"valve/{variant} fills a <{tag}> covering {covered:.0%} of its "
                f"{sym.width}x{sym.height} box -- that is the body, not a feature of it, "
                f"and a filled body means normally closed"
            )


def test_a_normally_closed_valve_is_the_one_valve_drawn_filled():
    """The other side of the rule above: declaring the position must actually
    darken the body, or the convention is documented and not drawn.

    Every variant is accounted for. It either darkens, or it is forbidden the
    mark outright by PIP PIC001 4.2.2.10, or it carries the NC abbreviation of
    4.2.2.8 -- and a variant that fell through all three would state its
    position nowhere at all, which is the silent failure this catches."""
    from pandid.render.symbols import NC_DARKENS, NC_FORBIDDEN, closed_marking

    seen = set()
    for variant in default_registry.variants("valve"):
        if variant in NC_FORBIDDEN:
            with pytest.raises(ValueError, match="4.2.2.10"):
                units.Valve("HV-1", variant=variant, normal_position="closed")
            seen.add(variant)
            continue
        valve = units.Valve("HV-1", variant=variant, normal_position="closed")
        mark = closed_marking(valve)
        assert mark in ("fill", "NC"), f"valve/{variant} states its position nowhere"
        seen.add(variant)
        sym = default_registry.for_unit(valve)
        if variant in NC_DARKENS:
            assert mark == "fill"
            assert _body_fill(sym) >= _FEATURE_AREA, (
                f"valve/{variant} is declared normally closed but nothing it draws "
                f"covers enough of its box to read as a darkened body"
            )
        else:
            assert mark == "NC"
            assert _artwork(sym) == _artwork(default_registry.get("valve", variant)), (
                f"valve/{variant} cannot be darkened, so its artwork must be the "
                f"ordinary one and the position said in letters instead"
            )
    assert seen == set(default_registry.variants("valve"))


# ---------------------------------------------------------------------------
# Where a valve's run sits in its box.
#
# scripts/vendor_symbols.py states the principle for the vessel family:
# "Switching a vessel between variants is a change of artwork, not of piping,
# so the two must offer the same nozzles in the same places." A valve the run
# goes straight through answers to the same rule, and its nozzles are on the
# body, which is the part that sits in the line.
#
# So the fixed height is measured from the BOTTOM of the box, not the top. An
# operator is drawn *above* the body -- a handwheel, a motor box, a diaphragm
# dome -- so choosing an actuated variant makes the box taller by adding to the
# top of it, and the body underneath stays where it was. valves.xml draws it
# that way: on every actuated shape the bowtie's lower edge is the bottom of the
# shape and the operator occupies the space above.
#
# Measured from the top the family is not one family at all. A gate valve's
# nozzles are 7.5 below the top of its box and a motor-operated one's are 14.9,
# so swapping the two under a corner pin drops the run 7.4 units -- half a valve
# body -- with nothing in the flowsheet having said anything about piping.
# ---------------------------------------------------------------------------

#: How far above the bottom of its box a valve carries the run, in symbol-space
#: units. valves.xml draws the plain bowtie 60 units tall, with the run through
#: its crossing point and its lower edge on the bottom of the shape, so the
#: centreline is 30 units up; ``SCALE["valve"] = 0.25`` makes that a 15.0-tall
#: body in a 24.5 x 15.0 box with the run 7.5 above the bottom of it. Sixteen of
#: the nineteen straight-through variants land on it.
_VALVE_RUN_HEIGHT = 7.5

#: One unit of the stencil's own coordinate space, at ``SCALE["valve"] = 0.25``.
#:
#: Every source of scatter in the conforming sixteen is sub-unit in the space
#: the stencil author drew in, so a drawing cannot express a finer distinction
#: than this and anything inside it is the same centreline:
#:
#: * the bowtie is not one size across valves.xml. It is 60 units tall on the
#:   bare bodies, on Manual Operated (y 5..65) and on Check Valve 1 (y 2..62),
#:   but 59 on Motor/Solenoid/Hydraulic (y 30..89), Pneumatic Operated
#:   (y 20..79) and Back Pressure Regulator 1 (y 35..94). Half of 59 against
#:   half of 60 is 0.5 stencil units of it;
#: * the nozzle's height is a draw.io ``<constraint>`` authored as a *fraction*
#:   of the shape's height and rounded to two or three decimals -- 0.5, 0.54,
#:   0.63, 0.67, 0.685 -- against shapes 60 to 94 tall. One hundredth of an
#:   89-tall shape is 0.89 units, so the fraction cannot land on the body's
#:   centre: it misses by up to 1 unit (Check Valve 1, whose 0.5 is the middle
#:   of the shape while the bowtie inside it is offset 2 units down);
#: * and the generator rounds what it emits to one decimal, 0.2 units here.
#:
#: NOT the quantisation of ``SCALE["valve"] = 0.25`` itself, which was the first
#: guess: that rounding is worth at most +/-0.05 on each of the two numbers, and
#: the exact pre-rounding heights are already spread 7.3075 (pneumatic) to 7.75
#: (check). The scatter is in the stencils, and the drawn-body sizes are most of
#: it. Worst case in the shipped registry is 0.2 (check at 7.7, and the three
#: letter-box operators at 7.3), so this accepts the family with 0.05 to spare
#: and rejects all three exceptions below by an order of magnitude.
_VALVE_RUN_TOL = 0.25


def _straight_through(sym: Symbol) -> bool:
    """True for a valve the run enters on the west face and leaves on the east.

    The scope is a rule about the nozzles rather than a list of names, so a
    variant added later is judged by where it is piped. It excludes the devices
    that have no horizontal run to be level with in the first place: ``relief``
    is piped bottom to top, ``bleed`` top to bottom, and ``angle`` and ``psv``
    turn the flow a quarter. Every valve's menu is single-entry, so the one face
    offered is the home face.
    """
    return list(sym.port_faces.get("inlet", ())) == ["W"] and list(
        sym.port_faces.get("outlet", ())
    ) == ["E"]


_STRAIGHT_VALVES = sorted(
    variant
    for variant in default_registry.variants("valve")
    if _straight_through(default_registry.get("valve", variant))
)

# ---------------------------------------------------------------------------
# The valves that leave the run, and why.
#
# Written out longhand with a reason each, on the pattern of
# tests/test_gravity_orientation.GRAVITY_FIXED, and split by *what kind* of
# exception it is. Moving the run is a statement about the piping, so a variant
# joining either dict has to be argued for here rather than land silently
# alongside the artwork that moved it.
# ---------------------------------------------------------------------------

#: Valves whose box legitimately reaches further below the run than a bowtie
#: does, because the stencil draws something down there. The nozzles are on the
#: ink the shape puts on the line; it is the box that is deeper.
_OFF_THE_RUN_BY_DESIGN = {
    "three_way": (
        "Three-Way Valve draws the bowtie across the TOP of its box -- y 0..60 "
        "of 79 -- and hangs the third way off the crossing point, two legs down "
        "to (19, 79) and (79, 79). The run is exactly where it is on every other "
        "valve; the box is what grew, and it grew downward to hold the branch. "
        "So this is the one straight-through valve fixed against the top of its "
        "box instead, at 7.6 below it, which is the family's 7.5 to within the "
        "drawing's own resolution. Bottom-anchoring it measures the run against "
        "the branch."
    ),
    "knife": (
        "Knife Valve is not a bowtie. It draws a rectangular gate housing, "
        "x 35..65 and y 15..85 of 85, with the run entering it as two stubs at "
        "y = 45 and the blade drawn as an arrowhead inside the lower half of it, "
        "y 50..80. The housing straddles the run rather than sitting under it, "
        "reaching 40 units below the centreline where a bowtie reaches 30 -- 2.5 "
        "units at SCALE['valve'] = 0.25 -- so the run comes out 9.9 above the "
        "bottom. The nozzles are on the stubs the stencil actually draws (11.3 "
        "against ink at 11.25), so nothing is misplaced. Swapping a gate valve "
        "for a knife gate still moves a corner-pinned run by those 2.4 units, "
        "and that is the artwork's doing rather than the port map's."
    ),
}

#: Not a difference: a defect, recorded rather than fixed. Fixing one moves ink
#: on every sheet that draws it, which is a rendering change and a second
#: concern; this file's job is to say the defect is there and to fail the moment
#: it stops being.
#:
#: Empty, and left in place rather than folded away, because emptiness is the
#: statement: there is no straight-through valve today whose run is off the
#: family's height for a reason nobody is prepared to defend. It held exactly
#: one entry, ``butterfly_pneumatic``, drawn 15.0 x 20.0 from an undersized
#: stencil and carrying its run 5.0 above the bottom of its box instead of 7.5.
#: That is fixed, in SCALE, and the rule it was evidence for is now asserted
#: forwards under "Valves drawn off valves.xml's own module" below.
_OFF_THE_RUN_BY_DEFECT: dict[str, str] = {}

_OFF_THE_RUN = {**_OFF_THE_RUN_BY_DESIGN, **_OFF_THE_RUN_BY_DEFECT}


def _run_heights(sym: Symbol) -> dict[tuple[str, str], float]:
    """Every placement of the two process nozzles, as a height above the bottom.

    The whole menu rather than just ``ports``: an alternate face is a nozzle the
    router may actually resolve to, so it answers to the rule as well.
    """
    return {
        (name, face): sym.height - y
        for name in ("inlet", "outlet")
        for face, (_, y) in sym.port_faces[name].items()
    }


def _ink_below_the_run(sym: Symbol) -> float:
    """How far the artwork reaches below the height the nozzles are drawn at."""
    lowest = max(max(ay, by) for (_, ay), (_, by) in _collect_segments(sym.svg))
    return lowest - sym.ports["inlet"][1]


@pytest.mark.parametrize("variant", [v for v in _STRAIGHT_VALVES if v not in _OFF_THE_RUN])
def test_a_straight_through_valve_carries_the_run_at_one_height(variant):
    """The line through a valve is at the same height whichever valve it is."""
    sym = default_registry.get("valve", variant)
    for (name, face), above in _run_heights(sym).items():
        assert above == pytest.approx(_VALVE_RUN_HEIGHT, abs=_VALVE_RUN_TOL), (
            f"valve/{variant} puts {name!r} ({face}) {above:.2f}u above the bottom of its "
            f"{sym.width}x{sym.height} box, not the {_VALVE_RUN_HEIGHT} every other "
            f"straight-through valve carries the run at (tolerance {_VALVE_RUN_TOL}) -- "
            f"so swapping a valve for this one moves the line it sits in"
        )


@pytest.mark.parametrize("variant", _STRAIGHT_VALVES)
def test_the_two_ends_of_a_straight_through_valve_are_level(variant):
    """Exactly level, not nearly: the two ends are one run, and a valve whose
    outlet were a rounding below its inlet would draw a step into a straight
    line. Both ends take the same stencil constraint, so both round alike; a
    pair that did not agree would be saying the body is not square to the pipe.
    """
    sym = default_registry.get("valve", variant)
    assert sym.ports["inlet"][1] == sym.ports["outlet"][1], (
        f"valve/{variant} enters at y={sym.ports['inlet'][1]} and leaves at "
        f"y={sym.ports['outlet'][1]}, which puts a step in the run"
    )


def test_exactly_the_valves_named_above_leave_the_run():
    """Nothing joins the exceptions without an entry beside it saying why.

    The counterpart of the parametrized rule, which can only speak for the
    variants it is given: without this, dropping a name into either dict would
    exempt it and read as green.
    """
    strayed = {
        variant
        for variant in _STRAIGHT_VALVES
        if any(
            abs(above - _VALVE_RUN_HEIGHT) > _VALVE_RUN_TOL
            for above in _run_heights(default_registry.get("valve", variant)).values()
        )
    }
    assert strayed == set(_OFF_THE_RUN)
    assert set(_OFF_THE_RUN_BY_DESIGN) & set(_OFF_THE_RUN_BY_DEFECT) == set()
    assert all(_OFF_THE_RUN.values()), "an exception without a reason is a list of names"


def test_the_valves_the_run_does_not_cross_are_out_of_scope():
    """A PSV is piped bottom to top and an angle body turns the flow a quarter,
    so neither has a horizontal run for the rule above to be about. They are out
    by where their nozzles are rather than by name, and this is what says the
    selection rule still draws the line in the same place -- a straight-through
    valve quietly falling out of scope would take its own invariant with it.
    """
    assert sorted(set(default_registry.variants("valve")) - set(_STRAIGHT_VALVES)) == [
        "angle",
        "bleed",
        "psv",
        "relief",
    ]
    # No assertion on the size of the family: a valve added later is meant to be
    # picked up and held to the rule, not to fail a count. What must not drift is
    # the balance -- an invariant most of its family is excused from asserts
    # nothing, and at that point the rule is the wrong rule rather than the
    # registry being wrong.
    assert len(_OFF_THE_RUN) * 2 < len(_STRAIGHT_VALVES), "the exceptions would be the rule"


@pytest.mark.parametrize("variant", sorted(_OFF_THE_RUN_BY_DESIGN))
def test_a_valve_drawn_below_the_run_is_drawn_there_in_ink(variant):
    """What makes the two by-design exceptions differences rather than defects.

    Each has a box deeper below the run than a bowtie's, and the depth has to be
    artwork: a nozzle 2.4 units off the family's height in a box whose extra
    depth is whitespace is not a valve drawn differently, it is a nozzle in the
    wrong place. So the drawn ink has to reach the bottom of the box, and reach
    further below the run than the plain body does.
    """
    plain = default_registry.get("valve", "gate")
    assert _ink_below_the_run(plain) == pytest.approx(_VALVE_RUN_HEIGHT)
    sym = default_registry.get("valve", variant)
    assert _ink_below_the_run(sym) > _ink_below_the_run(plain), _OFF_THE_RUN_BY_DESIGN[variant]
    assert _ink_below_the_run(sym) == pytest.approx(
        sym.height - sym.ports["inlet"][1], abs=_VALVE_RUN_TOL
    ), f"valve/{variant} has whitespace under it, not a deeper drawing"


def test_the_three_way_carries_the_run_at_the_familys_height_from_the_top():
    """The other half of three_way's reason: the run did not move, the box grew
    under it. Measured downward from the top of the box it is on the family's
    own height, which is what makes the branch below it the whole difference."""
    sym = default_registry.get("valve", "three_way")
    for name in ("inlet", "outlet"):
        assert sym.ports[name][1] == pytest.approx(_VALVE_RUN_HEIGHT, abs=_VALVE_RUN_TOL)


# ---------------------------------------------------------------------------
# Valves drawn off valves.xml's own module.
#
# The rule the pneumatic butterfly's defect was evidence for, said forwards.
# ``SCALE["valve"] = 0.25`` is one number applied to a whole stencil file, and
# it is calibrated to that file's ~98-unit module: it is what puts a Gate
# Valve's 98 x 60 bowtie in the 24.5 x 15.0 box the reference sheet is cut to.
# A shape drawn on any OTHER module therefore comes out at the wrong weight
# unless something makes up the difference, and "wrong weight" is not a matter
# of taste: an undersized body carries its nozzles with it, which is how the
# butterfly ended up drawing its run 5.0 above the bottom of its box instead of
# the family's 7.5.
#
# What the difference is measured in is the BODY, not the box. These are upright
# devices and the box holds whatever rides above the body -- a spring bonnet, a
# diaphragm dome -- so a rule stated about boxes would shrink the part that
# carries the flow to make room for the part that does not. ``angle`` is the
# case that settles it, and it is in ``_ON_THE_MODULE_BY_FOLDING`` below.
# ---------------------------------------------------------------------------

#: The shapes off the module that carry a ``(kind, variant)`` factor of their
#: own, as ``variant: (stencil box, emitted box, why)``. Both boxes are written
#: down so the entry says what the factor buys and not merely that there is one.
_OFF_THE_MODULE = {
    "psv": (
        (55.5, 94.5),
        (19.8, 33.8),
        "Safety PSV 1 draws the family's own seat at 0.7 of its size: the inlet "
        "leg is (0,94.5)-(21,60)-(42,94.5), a 42-wide base under a 34.5 apex, "
        "where every valve on the module has a 60-wide base under a 49 apex. "
        "15.0 / 42 restores it, putting the base on the 15.0 a gate valve's is "
        "drawn at. The lower 19.8 x 19.8 of the box it comes out in is exactly "
        "valve/angle's whole box -- the same quarter-turn body -- with 14 units "
        "of spring bonnet above it.",
    ),
    "relief": (
        (40.0, 59.0),
        (15.0, 22.1),
        "Relief PRV has no seat to measure: it is a 40-wide semicircular bonnet "
        "on a stem, piped S to N, so across-the-run is that bonnet and "
        "15.0 / 40 is the same statement. 15.0 across the run is a gate valve's "
        "15.0 across the run; the 22.1 along it against a gate valve's 24.5 is "
        "this one spending its length on a stem rather than on a bowtie.",
    ),
    "butterfly_pneumatic": (
        (60.0, 80.0),
        (24.5, 30.0),
        "Pneumatic Operated Butterfly Valve is the one that needs the "
        "non-uniform form. Its body is the plain rect x 0..60, y 40..80, at 3:2 "
        "where the family's bowtie is 98:60, so no single factor puts the body "
        "on 24.5 x 15.0 and the run on the family's height at once. "
        "(24.5/60, 15.0/40) does both. At the kind's bare 0.25 it came out "
        "15.0 x 20.0 -- 61% of a gate valve's length, with its run 5.0 up.",
    ),
}

#: A box off the module is not the same thing as a drawing off it, and this is
#: the shape that says so. Angle is 79 x 79 rather than 98 x 60, but its path is
#: (0,79)-(30,30)-(79,0)-(79,60)-(30,30)-(60,79): the family's own triangle,
#: 60-wide base under a 49 apex, drawn twice and folded into an L instead of set
#: base to base. Its seat is therefore already the family's, 0.25 draws it at
#: exactly the 15.0 x 12.25 a gate valve's is drawn at, and a factor of its own
#: would make this the one valve on the sheet with an oversized body.
_ON_THE_MODULE_BY_FOLDING = {
    "angle": "79 x 79, but drawn from the family's own 60 x 49 triangle twice",
}

#: The one left. Bleeder Valve 1 is 25 x 75 and its bowtie is 25 across by 40
#: along, against the family's 60 by 49, so 0.25 draws valve/bleed 6.2 x 18.8:
#: a body 6.2 across the run where a gate valve's is 15.0. It is the same class
#: of defect as the three above and wants the same kind of entry, but it is a
#: different device -- the small drain tapped off a header, piped N to S -- and
#: fixing it moves every sheet that draws one. Recorded here rather than folded
#: in, on ``_OFF_THE_RUN_BY_DEFECT``'s own principle: a defect this file names
#: is one the next reader can find, and the test below fails the moment it is
#: fixed rather than leaving this note behind as a lie.
_STILL_UNDERSIZED = {
    "bleed": "Bleeder Valve 1 is 25 x 75; its bowtie is 25 across where the family's is 60",
}


def _valve_stencil_boxes():
    """Every valve variant's stencil box, read from valves.xml itself.

    The generator's own map and the generator's own stencil, so this is not a
    second opinion about the drawing: it is what ``vendor_symbols`` read.
    """
    vendor = _script("vendor_symbols")
    shapes = {
        variant: shape
        for (kind, variant), (stencil, shape, _) in vendor.KIND_MAP.items()
        if kind == "valve" and stencil == "valves"
    }
    boxes = {
        name: (float(el.get("w")), float(el.get("h")))
        for name, el in vendor.shapes_in(vendor.STENCILS / "valves.xml")
        if name in set(shapes.values())
    }
    return vendor, {variant: boxes[shape] for variant, shape in shapes.items()}


@pytest.mark.parametrize("variant", sorted(_OFF_THE_MODULE))
def test_a_valve_off_the_stencils_module_is_rescaled_onto_the_familys_size(variant):
    """A shape off the module carries a factor of its own, and the factor lands
    it on the family's size.

    Both halves matter. Without the first, the entry above is a claim about a
    stencil nobody checks against the stencil; without the second, a factor
    could be any number at all and the symbol would still be the wrong size.
    """
    stencil_box, emitted, why = _OFF_THE_MODULE[variant]
    vendor, boxes = _valve_stencil_boxes()
    assert boxes[variant] == stencil_box, why
    assert vendor.scale_for("valve", variant) != vendor.scale_for("valve", "gate"), (
        f"valve/{variant} is drawn on a {stencil_box[0]} x {stencil_box[1]} module "
        f"and takes the kind's bare factor, so it is drawn undersized: {why}"
    )
    sym = default_registry.get("valve", variant)
    assert (sym.width, sym.height) == emitted, why


def test_exactly_the_valves_named_above_are_drawn_off_the_stencils_module():
    """Nothing joins or leaves the three dicts silently.

    The counterpart of the parametrized rule, which can only speak for the
    variants it is given. A shape off the module that appears in none of them is
    a valve quietly drawn at the wrong weight, which is the whole defect.
    """
    _, boxes = _valve_stencil_boxes()
    # Width alone, because the module is a LENGTH: every shape on it is 98 wide
    # (the check valve's 98.5 and the knife's 100 are the same length to within
    # the drawing's own resolution), while its height is 60 plus whatever
    # operator the stencil draws above the body -- 79 for a diaphragm dome, 89
    # for a motor box. A height test would call every actuated valve an outlier.
    off = {variant for variant, (w, _h) in boxes.items() if w < 98.0}
    assert off == set(_OFF_THE_MODULE) | set(_ON_THE_MODULE_BY_FOLDING) | set(_STILL_UNDERSIZED)
    assert set(_OFF_THE_MODULE) & set(_STILL_UNDERSIZED) == set(), (
        "a variant cannot be both rescaled and still waiting to be"
    )
    reasons = [entry[2] for entry in _OFF_THE_MODULE.values()]
    reasons += [*_ON_THE_MODULE_BY_FOLDING.values(), *_STILL_UNDERSIZED.values()]
    assert all(reasons), "an exception without a reason is a list of names"


def test_the_pneumatic_butterfly_is_back_on_the_run_because_it_is_rescaled():
    """The successor to the record of its defect: the same shape, the same two
    measurements, now saying it is fixed and saying what fixed it.

    ``test_a_straight_through_valve_carries_the_run_at_one_height`` already
    holds it to the family's height, since it is no longer excused from that
    rule. What it cannot say is *why* the run moved back, so dropping the SCALE
    entry would fail there with nothing pointing at the cause.
    """
    vendor = _script("vendor_symbols")
    assert vendor.scale_for("valve", "butterfly_pneumatic") == (24.5 / 60, 15.0 / 40)
    sym = default_registry.get("valve", "butterfly_pneumatic")
    plain = default_registry.get("valve", "gate")
    # Its body is the rect the stencil draws at x 0..60, y 40..80: the lower half
    # of the box, and now exactly the box a gate valve is drawn in.
    assert (sym.width, sym.height / 2) == (plain.width, plain.height)
    assert "butterfly_pneumatic" not in _OFF_THE_RUN
    assert sym.height - sym.ports["inlet"][1] == _VALVE_RUN_HEIGHT
    assert _ink_below_the_run(sym) == pytest.approx(_ink_below_the_run(plain))
