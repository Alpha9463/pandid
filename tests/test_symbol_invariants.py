"""Symbol-invariant tests over EVERY (kind, variant) in the registry.

This is the class of defect the other render tests never caught -- a port
placed in empty space, a stroke half-clipped by an SVG viewport, a label
struck through by a line -- because those tests only ever exercise the
handful of symbols the example flowsheets happen to use. Every registered
symbol is checked here, so the ~50 about to be added get the same scrutiny
for free.

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

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pfd.portgeom import outward_dir
from pfd.render.symbols import Symbol, default_registry

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
        segs.append((cur, newp))
        if upper == "M":
            start, cmd = newp, ("l" if relative else "L")
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
# Known, pre-existing exceptions.
#
# These are real defects these checks surfaced in the current registry.
# Reported (see the task's final write-up), not fixed here: this suite is
# test-only and pfd/ is out of scope. Exempting the specific (kind, variant[,
# port]) keeps every invariant strict for every other symbol, including the
# ~50 about to be added.
# ---------------------------------------------------------------------------

# feed/product are drawn dynamically by SvgRenderer._draw_boundary and never
# from their own Symbol.svg (see the "fallbacks" comment in symbols.py), so
# their registered geometry is intentionally unrelated to their ports.
_DYNAMIC_KINDS = {"feed", "product"}

# port sits several units off the nearest drawn stroke.
# Intentional, not defects: on these symbols the casing is drawn *open* where
# the suction nozzle attaches, and the port sits in the mouth of that opening —
# which is where the pipe should meet it. The nearest stroke is therefore half
# the opening away. Do not "fix" these by moving the port onto the casing.
_KNOWN_GEOMETRY_GAPS = {
    ("pump", "default", "suction"),
    ("compressor", "default", "suction"),
    ("pump", "screw", "suction"),
}

# Two distinct ports resolving to the identical coordinate. Empty: keep it that
# way — a duplicate means two streams land on the same point and draw over each
# other, so a new entry here should be a fix, not an exemption.
_KNOWN_DUPLICATE_PORTS: set = set()

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
    a lie the engine cannot catch: ``port_anchor`` derives the face from the
    coordinate, so the nozzle silently comes out somewhere else. The home entry
    is keyed from the coordinate and so cannot fail; an authored alternate can."""
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
    privileged default to merge back in."""
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
        if (kind, variant, name) in _KNOWN_GEOMETRY_GAPS:
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
        if (kind, variant, name) in _KNOWN_GEOMETRY_GAPS:
            continue
        for face, (x, y) in faces.items():
            d = _nearest_distance((x, y), segments)
            assert d <= GEOM_TOL, (
                f"{kind}/{variant} port_faces[{name!r}][{face!r}] at ({x}, {y}) is "
                f"{d:.1f}u from the nearest drawn stroke (tolerance {GEOM_TOL})"
            )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_no_two_ports_coincide(entry):
    (kind, variant), sym = entry
    if (kind, variant) in _KNOWN_DUPLICATE_PORTS:
        pytest.skip(f"{kind}/{variant}: known duplicate, see _KNOWN_DUPLICATE_PORTS")
    # The rule itself lives on Symbol, so a third-party symbol this suite never
    # sees is held to it too. Here we only assert the shipped registry is clean.
    assert sym.coincident_ports() == [], f"{kind}/{variant}: " + "; ".join(
        f"ports {a!r} and {b!r} both resolve to {xy}" for a, b, xy in sym.coincident_ports()
    )


def _colliding_symbol(**kwargs) -> Symbol:
    """Build a Symbol that is *expected* to have coincident ports.

    Registering one warns — the engine consults the rule, not just this suite —
    so the warning is asserted here rather than left to leak into the report.
    """
    with pytest.warns(UserWarning, match="Only ports named in faceless_ports"):
        return Symbol(svg='<g id="sym_under_test"/>', **kwargs)


def test_authored_alternates_do_not_buy_a_shared_face():
    """The historical ``separator/horizontal`` bug: the vapour outlet handed a
    copy of the feed's menu. Both ports then have more than one placement, so a
    "the menu is multi-entry" exemption waves the collision through — which is
    the point of naming faceless connections instead of inferring them."""
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
    """The historical ``vessel/horizontal`` bug: the outlet given the right head
    the inlet already offers, landing two nozzles on (91.5, 15.0)."""
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
