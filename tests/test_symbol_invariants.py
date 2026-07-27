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
# the suction nozzle attaches, and the port sits in the mouth of that opening —
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
    postcondition over the shipped registry rather than the primary guard —
    it would only fire if that check were weakened *and* a symbol were authored
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


def _sized_unit(kind: str, variant: str, index: int, w: float, h: float):
    """One unit of ``(kind, variant)``, forced into a ``w`` x ``h`` box."""
    cls = _UNIT_BY_KIND[kind]
    if kind == "instrument":  # tagged (type, number) rather than named
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


def _placements(svg: str) -> dict[tuple[float, float], Matrix]:
    """Symbol coordinates -> sheet coordinates for each placed symbol.

    Keyed by the centre of the box it was placed in, which is the one point a
    quarter turn and a mirror both leave alone, and so the only handle on a
    ``<use>`` that survives its own transform.

    A ``<symbol>`` maps its viewBox onto the ``<use>``'s box under its own
    ``preserveAspectRatio``: ``none`` fills the box exactly, while the default
    ``xMidYMid meet`` scales uniformly and centres, leaving a letterbox the box
    edge is no longer on. Whatever the ``<use>`` then does to the result is
    composed on top, so the matrix is the whole journey from the coordinates the
    symbol was authored in to the ones the sheet is drawn in.
    """
    defs = {m.group(1): m.group(0) for m in re.finditer(r'<symbol id="([^"]+)"[^>]*>', svg)}
    out: dict[tuple[float, float], Matrix] = {}
    for use in re.findall(r"<use\b[^>]*/>", svg):
        attr = dict(re.findall(r'([\w-]+)="([^"]*)"', use))
        ux, uy = float(attr["x"]), float(attr["y"])
        uw, uh = float(attr["width"]), float(attr["height"])
        _, _, vw, vh = _nums(re.search(r'viewBox="([^"]+)"', defs[attr["href"][1:]]).group(1))
        if 'preserveAspectRatio="none"' in defs[attr["href"][1:]]:
            sx, sy, ox, oy = uw / vw, uh / vh, 0.0, 0.0
        else:
            sx = sy = min(uw / vw, uh / vh)
            ox, oy = (uw - sx * vw) / 2, (uh - sy * vh) / 2
        fit: Matrix = (sx, 0.0, 0.0, sy, ux + ox, uy + oy)
        key = (round(ux + uw / 2, 6), round(uy + uh / 2, 6))
        out[key] = _compose(_parse_transform(attr.get("transform", "")), fit)
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
            matrices = _placements(fs.to_svg())
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
    segments = _collect_segments(sym.svg)
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
    matrices = _placements(fs.to_svg())
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


def _colliding_symbol(**kwargs) -> Symbol:
    """Build a Symbol that is *expected* to have coincident ports.

    Registering one warns — the engine consults the rule, not just this suite —
    so the warning is asserted here rather than left to leak into the report.
    """
    with pytest.warns(UserWarning, match="Only ports named in faceless_ports"):
        return Symbol(svg='<g id="sym_under_test"/>', **kwargs)


def test_authored_alternates_do_not_buy_a_shared_face():
    """Handing a vapour outlet a copy of the feed's menu gives both ports more
    than one placement, so a "the menu is multi-entry" exemption would wave the
    collision through — which is the point of naming faceless connections
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
    """One feed is the count every existing column sheet was drawn with, so the
    family has to reproduce that nozzle exactly -- otherwise supporting a second
    feed moves the first one on every drawing already issued."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, resolve_size

    for unit, want in (
        (U.Column("T"), (0.0, 130.0)),
        (U.Reactor("R"), (0.0, 48.2)),
        (U.Reactor("R", variant="plain"), (0.0, 30.0)),
    ):
        w, h = resolve_size(unit)
        placed = _drawn_placements(unit, "feed", w, h, 0, False, False)
        assert list(placed) == ["W"]
        assert placed["W"] == pytest.approx(want)


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
    assert outward_dir(*heater.ports["duty"], heater.width, heater.height) == "S"
    assert outward_dir(*cooler.ports["duty"], cooler.width, cooler.height) == "N"
    # And the spiral exchanger is reachable under the kind it belongs to.
    spiral = default_registry.get("hex", "spiral")
    assert (spiral.width, spiral.height) == (100.0, 100.0)
    assert set(spiral.ports) == {"cold_in", "cold_out", "hot_in", "hot_out"}


def test_a_nozzle_standing_in_a_series_band_is_a_collision():
    """A series has no fixed membership, so it has no fixed points to compare a
    nozzle against — the band it may place a member on is what a collision check
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
    spread along the opposite face — the shipped case that must stay quiet."""
    assert default_registry.get("splitter").coincident_ports() == []
    assert default_registry.get("mixer").coincident_ports() == []


# ---------------------------------------------------------------------------
# Looking a variant up.
# ---------------------------------------------------------------------------


def test_variants_lists_a_kinds_catalogue_default_first():
    assert default_registry.variants("tank") == ["default", "conical", "floating_roof", "sphere"]


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
# Where stretchability comes from.
#
# A draw.io stencil declares whether its shape may be reshaped, and scripts/
# carries that declaration into ``Symbol.stretchable``. Every shape KIND_MAP
# names happens to be a "variable" one, so nothing in the shipped registry
# exercises the other half of the reader -- which is exactly why it is exercised
# here, and why the claim that leaves the generated file free of the keyword is
# written down rather than left to be rediscovered.
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
    """The sheet is monochrome and its outlines are transparent, so the fill
    colour starts at "none" -- for <fill> exactly as for <fillstroke>, since
    both paint the same canvas state. A bare <fill> is a background wash, and
    a wash in no colour draws nothing at all rather than an invisible element
    for some later reader to mistake for ink."""
    assert _painted("<fillstroke/>") == ["none"]
    assert _painted("<stroke/>") == ["none"]
    assert _painted("<fill/>") == []


def test_fillcolor_is_how_a_stencil_asks_for_a_solid_shape():
    """It is the idiom draw.io's own shapes use for a damper's pivot and a
    flow arrow's head, and the converter has to keep it: making the converter
    incapable of a solid would trade one wrong drawing for another."""
    assert _painted('<fillcolor color="#000000"/><fillstroke/>') == ["#111"]
    assert _painted('<fillcolor color="#000000"/><fill/>') == ["#111"]
    # mxGraph's two keywords: "stroke" means the ink, "none" the paper.
    assert _painted('<fillcolor color="stroke"/><fillstroke/>') == ["#111"]
    assert _painted('<fillcolor color="none"/><fillstroke/>') == ["none"]


def test_save_and_restore_bracket_the_fill_colour():
    """Several stencils set a fill colour inside <save>/<restore> and expect
    the next shape to be back on the paper; without the stack the ink leaks
    forward and blacks out the rest of the drawing."""
    assert _converted_fills(
        '<save/><rect x="0" y="0" w="4" h="4"/><fillcolor color="#000000"/><fillstroke/>'
        '<restore/><rect x="5" y="5" w="4" h="4"/><fillstroke/>'
    ) == ["#111", "none"]


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


def test_no_valve_body_is_drawn_filled():
    """A fully darkened valve body is its own convention -- normally closed,
    PIP PIC001 4.2.2.7 -- so no symbol may spend that reading by accident.

    The globe's seat is an interior feature of a body whose two triangles keep
    their white interiors, which is what holds the two apart at sheet scale. A
    valve that filled its *outline* would be claiming something else entirely,
    and would do it silently, since a solid bowtie is a perfectly plausible
    thing to have drawn on purpose."""
    for (kind, variant), sym in _SYMBOLS:
        if kind != "valve":
            continue
        for tag, w, h in _ink_extents(sym.svg):
            covered = (w * h) / (sym.width * sym.height)
            assert covered < _FEATURE_AREA, (
                f"{kind}/{variant} fills a <{tag}> covering {covered:.0%} of its "
                f"{sym.width}x{sym.height} box -- that is the body, not a feature of it, "
                f"and a filled body means normally closed"
            )
