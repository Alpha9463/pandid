"""Symbol registry, port geometry, and SVG rendering invariants."""

from __future__ import annotations

import math
import re
import warnings
import xml.etree.ElementTree as ET
from typing import Any, NamedTuple

import pytest

from pandid import units
from pandid.portgeom import outward_dir, port_offset, port_point, resolve_size
from pandid.render.symbols import (
    CENTRED,
    FROM_START,
    MIN_NOZZLE_PITCH,
    PortSeries,
    Symbol,
    _face_local,
    _face_point,
    default_registry,
    spread,
)

from _render_cases import _script

_AGITATORS = {name for group, name in default_registry._parts if group == 28}

BOX_EPS = 1.0  # bounding-box slack, in symbol-space units
GEOM_TOL = 2.0  # max distance from a port to the nearest drawn segment

Point = tuple[float, float]
Segment = tuple[Point, Point]
Matrix = tuple[float, float, float, float, float, float]  # a b c d e f, SVG order

# SVG geometry helpers

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _compose(parent: Matrix, child: Matrix) -> Matrix:
    """Compose two affine transforms."""
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
    """Apply an affine transform to a point."""
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_NUM = r"-?\d*\.?\d+(?:[eE][-+]?\d+)?"


def _nums(s: str) -> list[float]:
    """Parse numeric SVG values."""
    return [float(x) for x in re.findall(_NUM, s)]


def _parse_transform(s: str) -> Matrix:
    """Parse supported SVG transforms.

    Parameters
    ----------
    s : str
        SVG transform attribute.

    Returns
    -------
    Matrix
        Combined affine transform.
    """
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
    """Sample an SVG elliptical arc."""
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
        """Return the signed angle between two vectors."""
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
    """Flatten an SVG path into line segments.

    Parameters
    ----------
    d : str
        SVG path data.

    Returns
    -------
    list[Segment]
        Path segments.
    """
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
            start, cmd = newp, ("l" if relative else "L")
        else:
            segs.append((cur, newp))
        cur = newp
    return segs


def _ellipse_segments(cx, cy, rx, ry, n=48) -> list[Segment]:
    """Approximate an ellipse with line segments."""
    pts = [
        (cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ]
    return list(zip(pts, pts[1:] + pts[:1]))


def _poly_segments(points_attr: str, *, closed: bool) -> list[Segment]:
    """Convert polygon coordinates to segments."""
    nums = _nums(points_attr)
    pts = list(zip(nums[0::2], nums[1::2]))
    segs = list(zip(pts, pts[1:]))
    if closed and len(pts) > 2:
        segs.append((pts[-1], pts[0]))
    return segs


def _collect_segments(svg: str) -> list[Segment]:
    """Flatten drawn SVG primitives into world-space segments."""
    root = ET.fromstring(svg)
    segs: list[Segment] = []

    def walk(el, m: Matrix) -> None:
        """Traverse one SVG element tree."""
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
    """Measure point-to-segment distance."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _nearest_distance(p: Point, segments: list[Segment]) -> float:
    """Find the nearest segment distance."""
    return min((_point_segment_distance(p, a, b) for a, b in segments), default=math.inf)


# Registry and static-symbol invariants

_DYNAMIC_KINDS = {"feed", "product"}

_KNOWN_GEOMETRY_GAPS = {
    ("pump", "default", "suction"),
    ("compressor", "default", "suction"),
    ("pump", "screw", "suction"),
}

_SIGNAL_PORTS = {
    (cls.kind, name)
    for cls in (getattr(units, n) for n in units.__all__)
    for name, _, role in [
        *cls.PORTS,
        *(
            port
            for variant in default_registry.variants(cls.kind)
            for port in cls._variant_ports(variant)
        ),
    ]
    if role == "signal"
}

_SYMBOLS = sorted(default_registry._symbols.items())
_IDS = [f"{kind}/{variant}" for (kind, variant), _ in _SYMBOLS]
_DIRECTIONAL = [entry for entry in _SYMBOLS if entry[1].directional]
_DIRECTIONAL_IDS = [f"{kind}/{variant}" for (kind, variant), _ in _DIRECTIONAL]


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_svg_is_well_formed_and_declares_stroke_width(entry):
    """Verify registry symbols render as valid SVG with a stroke width."""
    (kind, variant), sym = entry
    ET.fromstring(sym.svg)  # raises ET.ParseError on malformed XML
    assert "stroke-width" in sym.svg, f"{kind}/{variant} declares no stroke-width"


_BAKED_SPECIMEN = """\
<g id="specimen" transform="translate(7 11) scale(2 3)">
  <path d="M 1 2 L 9 2 A 4 2 30 0 1 12 8 Z" fill="none" stroke="black" stroke-width="2"/>
  <rect x="2" y="3" width="5" height="7" rx="1" ry="2" fill="none" stroke="black"/>
  <circle cx="13" cy="5" r="3" fill="none" stroke="black"/>
  <ellipse cx="20" cy="6" rx="4" ry="2" fill="none" stroke="black"/>
  <line x1="1" y1="14" x2="9" y2="18" stroke="black"/>
  <polygon points="12,14 16,18 10,19" fill="none" stroke="black"/>
  <polyline points="20,14 24,18 19,20" fill="none" stroke="black"/>
  <text x="8" y="24" font-size="10">T</text>
</g>"""


def test_baked_identity_keeps_the_artwork_unchanged():
    """Verify identity resizing preserves the source artwork."""
    from pandid.render.svg import _baked

    artwork = '<g id="identity"><line x1="1" y1="2" x2="3" y2="4" stroke="black"/></g>'
    assert _baked(artwork, 1.0, 1.0) == artwork


def test_baked_redraw_preserves_supported_geometry():
    """Verify non-uniform resizing preserves supported SVG geometry."""
    from pandid.render.svg import _baked

    fx, fy = 3.0, 0.5
    expected = [
        ((ax * fx, ay * fy), (bx * fx, by * fy))
        for (ax, ay), (bx, by) in _collect_segments(_BAKED_SPECIMEN)
    ]
    redrawn = _baked(_BAKED_SPECIMEN, fx, fy)
    actual = _collect_segments(redrawn)
    assert len(actual) == len(expected)
    worst = max(
        (
            max(math.dist(point, target) for point, target in zip(got, want))
            for got, want in zip(actual, expected)
        ),
        default=0.0,
    )
    assert worst <= 1e-5, f"redraw moved ink by {worst:.3g} units"
    text = ET.fromstring(redrawn).find("text")
    assert text is not None
    assert float(text.get("font-size")) == pytest.approx(math.sqrt(fx * fy * 6.0) * 10.0)


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_port_faces_within_bounding_box(entry):
    """Verify alternate port faces remain inside their boxes."""
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
def test_every_port_placement_lies_on_the_drawing(entry):
    """Verify process placements land on ink and signal placements on the outline."""
    (kind, variant), sym = entry
    drawn = kind not in _DYNAMIC_KINDS
    segments = _collect_segments(sym.svg) if drawn else []
    for name, faces in sym.port_faces.items():
        for face, (x, y) in faces.items():
            where = f"{kind}/{variant} port_faces[{name!r}][{face!r}] at ({x}, {y})"
            if (kind, name) in _SIGNAL_PORTS:
                inboard = min(x, y, sym.width - x, sym.height - y)
                assert inboard <= GEOM_TOL, f"{where} is a signal port inside its box"
            elif drawn and (kind, variant, name) not in _KNOWN_GEOMETRY_GAPS:
                d = _nearest_distance((x, y), segments)
                assert d <= GEOM_TOL, (
                    f"{where} is {d:.1f}u from the nearest drawn stroke (tolerance {GEOM_TOL})"
                )


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_no_two_ports_coincide(entry):
    """Verify distinct ports do not share coordinates."""
    (kind, variant), sym = entry
    assert sym.coincident_ports() == [], f"{kind}/{variant}: " + "; ".join(
        f"ports {a!r} and {b!r} both resolve to {xy}" for a, b, xy in sym.coincident_ports()
    )


# Drawn-nozzle invariants

_NOZZLE_STUB = 0.25
_NOZZLE_FLANGE = 2.0

_NOT_NOZZLES = {("separator", "knockout")}


def _rects(svg: str) -> list[tuple[float, float, float, float]]:
    """Read transformed SVG rectangles."""
    out: list[tuple[float, float, float, float]] = []

    def walk(el, m: Matrix) -> None:
        """Traverse SVG elements for rectangles."""
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
    """Describe a detected artwork nozzle."""

    face: str
    point: Point
    lo: float
    hi: float


def _drawn_nozzles(sym: Symbol) -> list[_Nozzle]:
    """Find flanged nozzle stubs in artwork."""
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


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_drawn_nozzles_and_ports_agree(entry):
    """Verify each drawn nozzle has a port and no port sits between two nozzles."""
    (kind, variant), sym = entry
    if (kind, variant) in _NOT_NOZZLES:
        pytest.skip("draws a gauge stub, not a process nozzle")
    nozzles = _drawn_nozzles(sym)
    placements = [
        (name, face, xy) for name, faces in sym.port_faces.items() for face, xy in faces.items()
    ]
    points = [xy for _n, _f, xy in placements]
    for nozzle in nozzles:
        near = min(math.dist(nozzle.point, p) for p in points) if points else math.inf
        assert near <= GEOM_TOL, f"{kind}/{variant}: no port on the nozzle at {nozzle.point}"
    for name, face, (x, y) in placements:
        on_face = [n for n in nozzles if n.face == face]
        if len(on_face) < 2:
            continue
        along = x if face in ("N", "S") else y
        if any(n.lo - GEOM_TOL <= along <= n.hi + GEOM_TOL for n in on_face):
            continue
        assert not (min(n.lo for n in on_face) < along < max(n.hi for n in on_face)), (
            f"{kind}/{variant} port {name!r} at ({x}, {y}) sits between two nozzles"
        )


_ODD_BOXES = ((300.0, 60.0), (60.0, 300.0))

_ROUNDTRIP_EPS = 1e-9

_UNBOXABLE_KINDS = {"conveyor"}

_UNIT_BY_KIND = {cls.kind: cls for cls in (getattr(units, n) for n in units.__all__)}

_DISPLAYS = {"panel": "central", "aux": "subsidiary"}


def _drawing(cls, variant: str) -> dict[str, Any]:
    """Return the keyword that asks ``cls`` for a registered drawing."""
    if cls is units.Instrument and variant in _DISPLAYS:
        return {"display": _DISPLAYS[variant]}
    key = "characteristic" if variant in getattr(cls, "_CHARACTERISTICS", ()) else "variant"
    return {key: variant}


# Dynamic-unit placement invariants


def _unit(kind: str, variant: str, index: int = 1, **size: float):
    """Construct a unit drawing a registered symbol."""
    cls = _UNIT_BY_KIND[kind]
    if kind == "instrument":  # tagged (type, number) rather than named
        return cls("XX", index, **_drawing(cls, variant), **size)
    return cls(f"{kind}-{variant}-{index}", **_drawing(cls, variant), **size)


_WIDEST_CLASS_FOR_KIND = {"column": units.DistillationColumn}

_FAMILY_ANCHOR_STEM = {"inlet": "in", "outlet": "out"}


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_every_anchor_the_artwork_offers_a_modelled_port_can_reach(entry):
    """Verify every drawn anchor is reachable by a modelled port."""
    (kind, variant), sym = entry
    cls = _WIDEST_CLASS_FOR_KIND.get(kind)
    unit = cls(f"{kind}-{variant}-x", variant=variant) if cls else _unit(kind, variant)
    reachable = {unit._symbol_anchor(name) for name in unit.ports}
    reachable |= {
        artwork_name
        for artwork_name, stem in _FAMILY_ANCHOR_STEM.items()
        if any(name.startswith(f"{stem}_") for name in unit.ports)
    }
    unreached = set(sym.ports) - reachable
    assert not unreached, f"{kind}/{variant}: no port reaches {sorted(unreached)}"


def _invert(m: Matrix) -> Matrix:
    """Invert an affine transform."""
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
    """Read native definition sizes from a flowsheet."""
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
    """Read symbol-to-sheet transforms from SVG output.

    Parameters
    ----------
    svg : str
        Rendered SVG.
    natives : dict[str, tuple[float, float]] or None
        Native definition sizes.

    Returns
    -------
    dict[tuple[float, float], Matrix]
        Transforms by placed-box centre.
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
    """Provide settled sheets for odd-sized symbols."""
    from pandid import Flowsheet

    sheets: dict[tuple, dict[tuple[str, str], tuple]] = {}
    for box in _ODD_BOXES:
        fs = Flowsheet("odd boxes")
        placed = {}
        for i, ((kind, variant), _) in enumerate(_SYMBOLS):
            if kind in _DYNAMIC_KINDS or kind in _UNBOXABLE_KINDS:
                continue
            unit = _unit(kind, variant, i, width=box[0], height=box[1])
            fs.add(unit).pin(x=200 + 600 * (i % 8), y=200 + 600 * (i // 8))
            placed[(kind, variant)] = unit
        matrices = _placements(fs.to_svg(), _natives(fs))
        sheets[box] = {
            key: (unit, matrices[(round(unit.frame.cx, 6), round(unit.frame.cy, 6))])
            for key, unit in placed.items()
        }
    return sheets


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_ports_stay_on_the_drawing_at_any_box_shape(entry, odd_box_sheets):
    """Verify process ports stay on ink and signal ports on the outline in odd boxes."""
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    if kind in _UNBOXABLE_KINDS:
        pytest.skip("a conveyor is sized by length=, so its box is its artwork's")
    first = next(iter(odd_box_sheets.values()))[(kind, variant)][0]
    segments = _collect_segments(default_registry.for_unit(first).svg)
    corners = [(0.0, 0.0), (sym.width, 0.0), (sym.width, sym.height), (0.0, sym.height)]
    outline = list(zip(corners, corners[1:] + corners[:1]))
    for (w, h), sheet in odd_box_sheets.items():
        unit, matrix = sheet[(kind, variant)]
        for name in unit.ports:
            where = f"{kind}/{variant} port {name!r} in a {w:g}x{h:g} box"
            point = _apply(_invert(matrix), *port_point(unit, unit.frame, name))
            if (kind, name) in _SIGNAL_PORTS:
                d = _nearest_distance(point, outline)
                assert d <= GEOM_TOL + _ROUNDTRIP_EPS, f"{where} is a signal port off the outline"
            elif (kind, variant, name) not in _KNOWN_GEOMETRY_GAPS:
                d = _nearest_distance(point, segments)
                assert d <= GEOM_TOL + _ROUNDTRIP_EPS, f"{where} is off ink"


@pytest.mark.parametrize("entry", _DIRECTIONAL, ids=_DIRECTIONAL_IDS)
def test_a_directional_symbols_ports_stay_on_ink_under_a_flip(entry):
    """Verify directional-symbol ports remain on ink when flipped."""
    (kind, variant), sym = entry
    segments = _collect_segments(sym.svg)
    for mirror_x, mirror_y in ((True, False), (False, True), (True, True)):
        for name, (x, y) in sym.ports.items():
            flipped = (sym.width - x if mirror_x else x, sym.height - y if mirror_y else y)
            d = _nearest_distance(flipped, segments)
            assert d <= GEOM_TOL, f"{kind}/{variant} {mirror_x=} {mirror_y=}: {name!r} off ink"


@pytest.mark.parametrize("entry", _DIRECTIONAL, ids=_DIRECTIONAL_IDS)
def test_a_directional_symbol_carries_no_lettering_of_its_own(entry):
    """Verify directional symbols do not contain fixed lettering."""
    (kind, variant), sym = entry
    assert "<text" not in sym.svg, f"{kind}/{variant} is directional and carries lettering"


_HOLDUP_CASES = [
    (cls, kind, variant)
    for cls, kind in ((units.Vessel, "vessel"), (units.Tank, "tank"))
    for variant in sorted(default_registry.variants(kind))
]
_HOLDUP_CASE_IDS = [f"{kind}/{variant}" for _, kind, variant in _HOLDUP_CASES]

_ROLE_FACE = {"vent": "N", "relief": "N", "drain": "S"}


@pytest.mark.parametrize("cls,kind,variant", _HOLDUP_CASES, ids=_HOLDUP_CASE_IDS)
def test_every_holdup_variant_anchors_every_nozzle_its_class_declares(cls, kind, variant):
    """Verify holdup variants anchor every declared nozzle."""
    from pandid.portgeom import is_anchored

    unit = cls("X-1", variant=variant)
    for name in unit.ports:
        assert is_anchored(unit, name), f"{kind}/{variant} does not anchor {name!r}"


@pytest.mark.parametrize("cls,kind,variant", _HOLDUP_CASES, ids=_HOLDUP_CASE_IDS)
def test_a_relief_is_on_the_crown_and_a_drain_at_the_low_point(cls, kind, variant):
    """Verify relief and drain ports occupy their prescribed positions."""
    from pandid.portgeom import port_faces

    unit = cls("X-1", variant=variant)
    for name, want in _ROLE_FACE.items():
        got = port_faces(unit, name)
        assert got == [want], (
            f"{kind}/{variant}.{name} is piped from {got} as drawn; the role puts it on {want}"
        )


def test_the_two_holdup_classes_offer_the_same_nozzles():
    """Verify tank and vessel classes expose the same nozzles."""
    assert list(units.Tank("T-1").ports) == list(units.Vessel("V-1").ports)


def test_the_reported_column_and_reactor_meet_their_streams():
    """Verify reported column and reactor stream connections."""
    from pandid import Flowsheet

    fs = Flowsheet("as reported")
    col = fs.add(units.Column("T-301", width=110, height=250)).pin(x=100, y=100)
    reactor = fs.add(units.Reactor("M-301", width=80, height=100)).pin(x=600, y=100)
    matrices = _placements(fs.to_svg(), _natives(fs))
    for unit in (col, reactor):
        sym = default_registry.for_unit(unit)
        frame = unit.frame
        matrix = matrices[(round(frame.cx, 6), round(frame.cy, 6))]
        assert _apply(matrix, 0.0, 0.0) == pytest.approx((frame.x, frame.y))
        assert _apply(matrix, sym.width, sym.height) == pytest.approx(
            (frame.x + frame.w, frame.y + frame.h)
        )
        drawn = [(_apply(matrix, *a), _apply(matrix, *b)) for a, b in _collect_segments(sym.svg)]
        for name in unit.ports:
            gap = _nearest_distance(port_point(unit, frame, name), drawn)
            assert gap <= GEOM_TOL, f"{unit.name}.{name} in a {frame.w:g}x{frame.h:g} box"


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
    """Verify turned-fitting ports lie on drawn geometry."""
    (kind, variant), _, turned = entry
    segments = _collect_segments(turned.svg)
    for name, faces in turned.port_faces.items():
        for face, (x, y) in faces.items():
            d = _nearest_distance((x, y), segments)
            assert d <= GEOM_TOL, f"{kind}/{variant} turned: {name!r} on {face!r} at ({x}, {y})"


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fitting_keeps_its_box_and_its_faces(entry):
    """Verify turned fittings preserve their boxes and port faces."""
    _, sym, turned = entry
    assert (turned.width, turned.height) == (sym.width, sym.height)
    assert turned.stretchable == sym.stretchable
    assert list(turned.port_faces["inlet"]) == ["W"]
    assert list(turned.port_faces["outlet"]) == ["E"]
    assert turned.coincident_ports() == []
    assert turned.symbol_id() != sym.symbol_id()


@pytest.mark.parametrize("entry", _TURNED, ids=_TURNED_IDS)
def test_a_turned_fitting_opens_out_where_the_reduction_closes_in(entry):
    """Verify turned reductions reverse the cone direction."""
    _, sym, turned = entry

    def face_height(symbol: Symbol, x: float) -> float:
        """Measure ink height at a vertical coordinate."""
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
    """Verify turned-fitting ports follow ink across box shapes."""
    from pandid import Flowsheet

    (kind, variant), _, turned = entry
    segments = _collect_segments(turned.svg)
    for w, h in _ODD_BOXES:
        fs = Flowsheet("odd boxes, turned end for end")
        unit = units.Reducer(
            f"{kind}-{variant}", variant=variant, large_end="outlet", width=w, height=h
        )
        fs.add(unit).pin(x=200, y=200)
        matrix = _placements(fs.to_svg(), _natives(fs))[
            (round(unit.frame.cx, 6), round(unit.frame.cy, 6))
        ]
        for name in unit.ports:
            point = _apply(_invert(matrix), *port_point(unit, unit.frame, name))
            d = _nearest_distance(point, segments)
            assert d <= GEOM_TOL + _ROUNDTRIP_EPS, f"{kind}/{variant} turned: {name!r} {w:g}x{h:g}"


# Port-placement menu invariants


def _colliding_symbol(**kwargs) -> Symbol:
    """Build a symbol with expected coincident ports."""
    with pytest.warns(UserWarning, match="Only ports named in faceless_ports"):
        return Symbol(svg='<g id="sym_under_test"/>', **kwargs)


@pytest.mark.parametrize(
    ("ports", "port_faces", "clash"),
    [
        (
            {"feed": (0.0, 15.0), "vapor": (30.0, 0.0), "liquid": (68.0, 30.0)},
            {
                "feed": {"W": (0.0, 15.0), "N": (20.0, 0.0), "E": (91.5, 15.0)},
                "vapor": {"W": (0.0, 15.0), "E": (91.5, 15.0)},
            },
            ("feed", "vapor", (0.0, 15.0)),
        ),
        (
            {"inlet": (0.0, 15.0), "outlet": (68.0, 30.0)},
            {
                "inlet": {"W": (0.0, 15.0), "N": (20.0, 0.0), "E": (91.5, 15.0)},
                "outlet": {"E": (91.5, 15.0)},
            },
            ("inlet", "outlet", (91.5, 15.0)),
        ),
    ],
)
def test_two_ports_on_one_alternate_placement_are_caught(ports, port_faces, clash):
    """Verify a shared alternate, or a nozzle on an alternate's coordinate, is caught."""
    sym = _colliding_symbol(width=91.5, height=30.0, ports=ports, port_faces=port_faces)
    assert sym.coincident_ports() == [clash]


def test_faceless_connections_may_share_a_placement():
    """Verify faceless connections may share a placement."""
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


@pytest.mark.parametrize(
    ("menus", "match"),
    [
        # (0.0, 15.0) is on the west edge, not the north.
        (
            {"ports": {"feed": (30.0, 0.0)}, "port_faces": {"feed": {"N": (0.0, 15.0)}}},
            r"nearest the W edge",
        ),
        (
            {"ports": {"feed": (0.0, 15.0)}, "port_faces": {"feed": {"W": (0.0, 12.0)}}},
            r"but ports\['feed'\] puts the same face at",
        ),
        (
            {"ports": {"inlet": (0.0, 20.0)}, "port_faces": {"nope": {"E": (40.0, 20.0)}}},
            r"declares a menu for \['nope'\]",
        ),
        (
            {"ports": {"inlet": (0.0, 20.0)}, "faceless_ports": frozenset({"typo"})},
            r"faceless_ports names \['typo'\]",
        ),
    ],
)
def test_a_menu_that_does_not_fit_the_ports_is_rejected(menus, match):
    """Verify a misplaced, restated or unanchored menu or faceless port is rejected."""
    with pytest.raises(ValueError, match=match):
        Symbol(svg='<g id="sym_x"/>', width=91.5, height=30.0, **menus)


def test_a_home_placement_restated_in_the_menu_is_accepted():
    """Verify a port menu may restate the home placement."""
    sym = Symbol(
        svg='<g id="sym_x"/>',
        width=91.5,
        height=30.0,
        ports={"feed": (0.0, 15.0)},
        port_faces={"feed": {"W": (0.0, 15.0), "N": (20.0, 0.0)}},
    )
    assert list(sym.port_faces["feed"]) == ["W", "N"]


def test_every_port_menu_starts_from_its_home_placement():
    """Verify each port's menu holds its home placement first, menu or no menu."""
    sym = Symbol(
        svg='<g id="sym_x"/>',
        width=91.5,
        height=30.0,
        ports={"feed": (0.0, 15.0), "vapor": (91.5, 15.0)},
        port_faces={"feed": {"N": (20.0, 0.0)}},
    )
    assert sym.port_faces == {
        "feed": {"W": (0.0, 15.0), "N": (20.0, 0.0)},
        "vapor": {"E": (91.5, 15.0)},
    }
    assert list(sym.port_faces["feed"]) == ["W", "N"]


# Port-series invariants


@pytest.mark.parametrize(
    "kind,prefix,ctor_arg,face,variant",
    [
        ("mixer", "in_", "n_inlets", "W", "default"),
        ("splitter", "out_", "n_outlets", "E", "default"),
        ("column", "feed_", "n_feeds", "W", "default"),
        ("column", "draw_", "n_draws", "E", "default"),
        ("reactor", "feed_", "n_feeds", "W", "default"),
        ("separator", "feed_", "n_feeds", "W", "default"),
        ("separator", "feed_", "n_feeds", "W", "knockout"),
        ("separator", "feed_", "n_feeds", "W", "cyclone"),
        ("separator", "feed_", "n_feeds", "W", "sifter"),
    ],
)
def test_every_member_of_a_port_series_gets_a_nozzle_of_its_own(
    kind, prefix, ctor_arg, face, variant
):
    """Verify each port-series member receives a distinct nozzle."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, is_anchored, resolve_size

    cls = {
        "mixer": U.Mixer,
        "splitter": U.Splitter,
        "column": U.Column,
        "reactor": U.Reactor,
        "separator": U.Separator,
    }[kind]
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
    """Verify port-series members lie on drawn geometry."""
    (kind, variant), sym = entry
    if kind in _DYNAMIC_KINDS:
        pytest.skip("feed/product are drawn dynamically, not from Symbol.svg")
    segments = _collect_segments(sym.svg)
    for series in sym.port_series:
        for count in range(1, 9):
            for index in range(count):
                x, y = series.placement(index, count, sym.width, sym.height)
                d = _nearest_distance((x, y), segments)
                assert d <= GEOM_TOL, f"{kind}/{variant} {series.prefix}{index + 1} of {count}"


@pytest.mark.parametrize("entry", _SYMBOLS, ids=_IDS)
def test_every_port_series_sets_two_members_an_arrowhead_pitch_apart(entry):
    """Verify every series pitch, and two members' gap, is MIN_NOZZLE_PITCH."""
    (kind, variant), sym = entry
    for series in sym.port_series:
        assert series.pitch >= MIN_NOZZLE_PITCH, f"{kind}/{variant} {series.prefix}"
        band = sym.bands.get(series.face)
        (x0, y0), (x1, y1) = (
            series.placement(i, 2, sym.width, sym.height, band=band) for i in (0, 1)
        )
        gap = abs(y1 - y0) if series.face in ("W", "E") else abs(x1 - x0)
        assert gap >= MIN_NOZZLE_PITCH, f"{kind}/{variant} {series.prefix}: {gap}"


def test_a_lone_member_lands_where_the_fixed_nozzle_did():
    """Verify a lone series member preserves its fixed-nozzle position."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, resolve_size

    for unit, want in (
        (U.Reactor("R"), (0.0, 50.0 + 62.0 / 3 + 100.0 / 9)),
        (U.Separator("V"), (0.0, 50.0)),
        (U.Separator("V", variant="knockout"), (0.0, 55.0)),
        (U.Separator("V", variant="cyclone"), (0.0, 12.0)),
        (U.Separator("V", variant="scrubber"), (0.0, 12.0)),
    ):
        w, h = resolve_size(unit)
        placed = _drawn_placements(unit, "feed", w, h, 0, False, False)
        assert list(placed) == ["W"]
        assert placed["W"] == pytest.approx(want)


@pytest.mark.parametrize(("family", "draws", "face"), [("feed", 0, "W"), ("draw", 1, "E")])
def test_a_lone_column_feed_or_draw_sits_at_the_centre_of_the_duty_band(family, draws, face):
    """Verify a lone column feed or draw centres in its duty band."""
    from pandid import units as U
    from pandid.portgeom import _drawn_placements, resolve_size

    for variant in default_registry.variants("column"):
        unit = U.Column("T", variant=variant, n_draws=draws)
        w, h = resolve_size(unit)
        placed = _drawn_placements(unit, family, w, h, 0, False, False)
        assert list(placed) == [face], f"column/{variant}"
        x = 0.0 if face == "W" else w
        assert placed[face] == pytest.approx((x, 105.0)), f"column/{variant}"


def test_a_feed_family_reaching_the_return_nozzles_is_caught():
    """Verify feed families cannot reach return nozzles."""
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
    """Verify shipped feed families avoid unrelated nozzles."""
    for kind, variant in (("column", "default"), ("reactor", "default")):
        sym = default_registry.get(kind, variant)
        assert sym.port_series, f"{kind}/{variant} has no feed family"
        assert sym.coincident_ports() == [], f"{kind}/{variant}"


@pytest.mark.parametrize(("prefix", "label"), [("feed_", "n_feeds"), ("draw_", "n_draws")])
@pytest.mark.parametrize("variant", default_registry.variants("column"))
def test_every_column_feed_and_draw_stays_between_the_duty_arrows(variant, prefix, label):
    """Verify column feeds and draws remain between duty arrows."""
    from pandid import units as U
    from pandid.portgeom import port_offset

    sym = default_registry.get("column", variant)
    lo, hi = sym.ports["condenser_duty"][1], sym.ports["reboiler_duty"][1]
    assert lo < hi, f"column/{variant}: the duty arrows bound no band at all"
    (family,) = (series for series in sym.port_series if series.prefix == prefix)
    for count in range(1, 13):
        family_size: dict[str, Any] = {label: count}
        column = U.Column("T", variant=variant, **family_size)
        members = [name for name in column.ports if family.matches(name)]
        assert len(members) == count, f"column/{variant} {label}={count}: {members}"
        for name in members:
            y = port_offset(column, name)[1]
            assert lo < y < hi, (
                f"column/{variant} {name} of {count} sits at y={y}, outside the "
                f"({lo}, {hi}) band the duty arrows bound"
            )


def test_two_series_ports_land_where_the_symbol_used_to_draw_them():
    """Verify two-member series preserve existing nozzle positions."""
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
    """Verify a series cannot restate an anchored port."""
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
    """Verify heater and cooler stencil variants share dimensions."""
    heater = default_registry.get("heater", "default")
    cooler = default_registry.get("cooler", "default")
    assert (cooler.width, cooler.height) == (heater.width, heater.height)
    assert cooler.ports["inlet"] == heater.ports["inlet"]
    assert cooler.ports["outlet"] == heater.ports["outlet"]
    assert outward_dir(*heater.ports["utility_in"], heater.width, heater.height) == "S"
    assert outward_dir(*cooler.ports["utility_out"], cooler.width, cooler.height) == "N"
    spiral = default_registry.get("hex", "spiral")
    assert (spiral.width, spiral.height) == (100.0, 100.0)
    assert set(spiral.ports) == {"side_a_in", "side_a_out", "side_b_in", "side_b_out"}


def test_a_nozzle_standing_in_a_series_band_is_a_collision():
    """Verify nozzles within a series band are collisions."""
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
    """Verify nozzles outside a series band are not collisions."""
    from pandid.render.symbols import PortSeries

    clear = Symbol(
        svg='<g id="sym_clear"/>',
        width=50.0,
        height=50.0,
        ports={"tap": (0.0, 2.0)},  # outside the 70% band
        port_series=(PortSeries("in_", "W"),),
    )
    assert clear.coincident_ports() == []


_HOLDUP = [
    (kind, variant) for kind in ("tank", "vessel") for variant in default_registry.variants(kind)
]
_HOLDUP_IDS = [f"{kind}/{variant}" for kind, variant in _HOLDUP]

_BANDED = [key for key, sym in _SYMBOLS if getattr(sym, "bands", {})]
_BANDED_IDS = [f"{kind}/{variant}" for kind, variant in _BANDED]

_COMPOSABLE = [
    (kind, variant)
    for kind, variant in _HOLDUP
    if "supports" in getattr(units.Tank if kind == "tank" else units.Vessel, "COMPOSITION", {})
]
_COMPOSABLE_IDS = [f"{kind}/{variant}" for kind, variant in _COMPOSABLE]

ON_BODY_TOL = 1e-6


# Holdup-family invariants


def _holdup(kind: str, variant: str, role: str, faces: list[str]) -> units.Unit:
    """Build a tank or vessel family case."""
    cls = units.Tank if kind == "tank" else units.Vessel
    if role == "inlet":
        return cls("X-1", variant=variant, inputs=faces)
    return cls("X-1", variant=variant, outputs=faces)


def _has_wall(sym: Symbol, face: str) -> bool:
    """Report whether a face supports multiple connections."""
    band = sym.bands.get(face)
    return band is None or band[0] < band[1]


def _role_menus(kind: str, variant: str):
    """Yield inlet and outlet face menus."""
    sym = default_registry.get(kind, variant)
    for role, prefix in (("inlet", "in_"), ("outlet", "out_")):
        yield role, prefix, sym.port_faces.get(role, {})


def test_spread_never_leaves_the_band_it_is_given():
    """Verify series spreading remains within its band."""
    face = 95.5
    for band in ((0.0, face), (36.0, 85.0), (10.0, 20.0), (50.0, 50.0)):
        lo, hi = band
        for at in (0.0, 5.0, 40.0, 85.0, 95.5, None):
            for align in (CENTRED, FROM_START):
                for count in range(1, 13):
                    got = [spread(i, count, face, 20.0, 0.7, at, align, band) for i in range(count)]
                    where = f"band={band} at={at} align={align} n={count}"
                    assert all(lo - 1e-9 <= t <= hi + 1e-9 for t in got), where
                    assert got == sorted(got), where


def test_spread_slides_a_run_no_further_than_it_has_to():
    """Verify constrained series spreading makes the smallest shift."""
    inside = [spread(i, 3, 95.5, 20.0, 0.7, 50.0, CENTRED, (10.0, 90.0)) for i in range(3)]
    assert inside == pytest.approx([30.0, 50.0, 70.0])
    assert inside == pytest.approx([spread(i, 3, 95.5, 20.0, 0.7, 50.0, CENTRED) for i in range(3)])
    against = [spread(i, 3, 95.5, 20.0, 0.7, 85.0, CENTRED, (36.0, 85.0)) for i in range(3)]
    assert against == pytest.approx([45.0, 65.0, 85.0])


def test_three_inlets_stack_up_a_dished_roof_tanks_shell():
    """Verify three tank inlets follow the dished roof."""
    tank = units.Tank("TK-1", inputs=3)
    assert [port_offset(tank, f"in_{i}")[1] for i in (1, 2, 3)] == pytest.approx([45.0, 65.0, 85.0])
    assert [port_offset(tank, f"in_{i}")[0] for i in (1, 2, 3)] == pytest.approx([0.0] * 3)


@pytest.mark.parametrize(("kind", "variant"), _HOLDUP, ids=_HOLDUP_IDS)
def test_a_holdup_family_stays_on_its_wall_and_its_ink_at_every_count(kind, variant):
    """Verify a holdup family stays on its box, its declared wall and its drawn ink."""
    sym = default_registry.get(kind, variant)
    segments = _collect_segments(sym.svg)
    for role, prefix, menu in _role_menus(kind, variant):
        for face, drawn in menu.items():
            assert face in sym.bands, f"{kind}/{variant}: {role} on {face} has no band"
            lo, hi = sym.bands[face]
            for count in range(1, 9 if _has_wall(sym, face) else 2):
                unit = _holdup(kind, variant, role, [face] * count)
                w, h = resolve_size(unit)
                for i in range(1, count + 1):
                    x, y = port_offset(unit, f"{prefix}{i}")
                    where = f"{kind}/{variant} {prefix}{i} of {count} on {face} at ({x}, {y})"
                    if count == 1:
                        assert (x, y) == pytest.approx(drawn), f"{where}, not at {drawn} as drawn"
                    assert -ON_BODY_TOL <= x <= w + ON_BODY_TOL, f"{where} is outside {w} wide"
                    assert -ON_BODY_TOL <= y <= h + ON_BODY_TOL, f"{where} is outside {h} tall"
                    along = y if face in ("W", "E") else x
                    assert lo - ON_BODY_TOL <= along <= hi + ON_BODY_TOL, (
                        f"{where} is outside the ({lo}, {hi}) wall the symbol declares"
                    )
                    d = _nearest_distance((x, y), segments)
                    assert d <= GEOM_TOL, f"{where} is {d:.1f}u from the nearest drawn stroke"


@pytest.mark.parametrize(("kind", "variant"), _HOLDUP, ids=_HOLDUP_IDS)
def test_a_holdup_family_keeps_its_pitch_from_the_fixed_nozzles_on_its_wall(kind, variant):
    """Verify no vent, relief or drain sits nearer a family than its pitch."""
    sym = default_registry.get(kind, variant)
    segments = _collect_segments(sym.svg)
    w, h = sym.width, sym.height
    for role, prefix, menu in _role_menus(kind, variant):
        for face in menu:
            for count in range(2, 9 if _has_wall(sym, face) else 2):
                unit = _holdup(kind, variant, role, [face] * count)
                run = [
                    _face_local(face, *port_offset(unit, f"{prefix}{i}"), w, h)[0]
                    for i in range(1, count + 1)
                ]
                pitch = min(abs(b - a) for a, b in zip(run, run[1:]))
                for name in ("vent", "relief", "drain"):
                    at = port_offset(unit, name)
                    if outward_dir(at[0], at[1], w, h) != face:
                        continue
                    t = _face_local(face, at[0], at[1], w, h)[0]
                    gap = min(abs(t - member) for member in run)
                    where = f"{kind}/{variant} {name} beside {count} {role}s on {face}"
                    assert gap >= pitch - 1e-6, f"{where}: {gap:.1f}u off, pitch {pitch:.1f}u"
                    d = _nearest_distance(at, segments)
                    assert d <= GEOM_TOL, f"{where} is {d:.1f}u from the nearest drawn stroke"


def test_four_bottom_outlets_leave_a_tanks_drain_its_own_nozzle():
    """Verify ``outputs=["S"] * 4`` builds without stacking out_1 on the drain."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        tank = units.Tank("X-1", outputs=["S"] * 4)
        points = [port_offset(tank, name) for name in ("drain", "out_1", "out_2", "out_3", "out_4")]
    assert len(set(points)) == 5


@pytest.mark.parametrize(("kind", "variant"), _BANDED, ids=_BANDED_IDS)
def test_every_declared_wall_lies_on_the_drawing(kind, variant):
    """Verify each declared wall lies on the drawing."""
    sym = default_registry.get(kind, variant)
    segments = _collect_segments(sym.svg)
    for face, (lo, hi) in sym.bands.items():
        insets = set()
        for role in ("inlet", "outlet"):
            drawn = sym.port_faces.get(role, {}).get(face)
            if drawn is not None:
                insets.add(_face_local(face, drawn[0], drawn[1], sym.width, sym.height)[1])
        # A wall with no connection drawn on it is the box's edge.
        for inset in insets or {0.0}:
            for t in (lo, (lo + hi) / 2, hi):
                point = _face_point(face, t, inset, sym.width, sym.height)
                d = _nearest_distance(point, segments)
                assert d <= GEOM_TOL, f"{kind}/{variant} band {face!r} at {t} is off ink"


@pytest.mark.parametrize(("kind", "variant"), _HOLDUP, ids=_HOLDUP_IDS)
def test_a_wall_takes_a_second_connection_and_a_point_refuses_one(kind, variant):
    """Verify walls accept series ports and points reject them."""
    sym = default_registry.get(kind, variant)
    for role, prefix, menu in _role_menus(kind, variant):
        for face in menu:
            _holdup(kind, variant, role, [face])
            if not _has_wall(sym, face):
                with pytest.raises(ValueError, match="mid-air off the ink"):
                    _holdup(kind, variant, role, [face, face])
                continue
            pair = _holdup(kind, variant, role, [face, face])
            one, two = (port_offset(pair, f"{prefix}{i}") for i in (1, 2))
            assert one != two, f"{kind}/{variant} {role} on {face}: two connections coincide"


def test_a_face_with_no_wall_is_refused_by_the_drawing_too():
    """Verify drawing rejects series ports on wall-less faces."""
    from pandid.render.symbols import vessel_symbol

    with pytest.raises(ValueError, match="mid-air off the ink"):
        vessel_symbol("tank", "default", (("in_1", "N"), ("in_2", "N")))


def test_an_inlet_and_an_outlet_on_a_face_with_no_wall_are_refused_by_the_drawing():
    """Verify an inlet and an outlet on one wall-less face are refused."""
    from pandid.render.symbols import vessel_symbol

    variant = "cross_role_test"
    with pytest.warns(UserWarning, match="'inlet' and 'outlet' both have a placement"):
        apex = Symbol(
            svg='<g id="sym_tank_cross_role_test"><path d="M 0 20 L 0 90 L 100 90 '
            'L 100 20 L 50 0 Z" fill="none" stroke="black" stroke-width="2"/></g>',
            width=100.0,
            height=90.0,
            ports={"inlet": (50.0, 0.0), "outlet": (0.0, 80.0)},
            port_faces={
                "inlet": {"N": (50.0, 0.0)},
                "outlet": {"W": (0.0, 80.0), "N": (50.0, 0.0)},
            },
            bands={"N": (50.0, 50.0), "W": (30.0, 80.0)},
        )
    default_registry.register("tank", apex, variant)
    try:
        with pytest.raises(ValueError, match="in_1 and out_1 are both on the N face") as drawn:
            vessel_symbol("tank", variant, (("in_1", "N"), ("out_1", "N")))
        tank = units.Tank("T-1", variant=variant, inputs=["N"], outputs=["W"])
        with pytest.raises(ValueError, match="in_1 and out_1 are both on the N face") as moved:
            tank.nozzle("out_1", "N")
    finally:
        default_registry._symbols.pop(("tank", variant), None)
    for refused in (drawn, moved):
        assert "No face with a wall takes all of them" in str(refused.value)


def test_moving_a_second_connection_onto_a_wall_less_face_is_refused():
    """Verify moving a series port onto a wall-less face is rejected."""
    tank = units.Tank("T-1", inputs=["N", "W"])
    with pytest.raises(ValueError, match="mid-air off the ink"):
        tank.nozzle("in_2", "N")
    assert tank.face("in_2") == "W"


@pytest.mark.parametrize(("kind", "variant"), _COMPOSABLE, ids=_COMPOSABLE_IDS)
def test_a_supported_body_keeps_the_wall_its_body_declares(kind, variant):
    """Verify supported bodies preserve their declared walls."""
    sym = default_registry.get(kind, variant)
    assert sym.bands, f"{kind}/{variant} is a holdup body and declares no wall"
    for supports in ("leg", "skirt", "bracket", "ring"):
        try:
            drawn = default_registry.for_unit(
                units.Vessel("X-1", variant=variant, supports=supports)
            )
        except ValueError as exc:
            assert "cannot carry supports=" in str(exc), f"vessel/{variant} + {supports}: {exc}"
            continue
        assert drawn.bands == sym.bands, (
            f"vessel/{variant} on {supports}s lost the wall its body declares"
        )


def test_a_wall_moves_with_the_ink_when_a_part_grows_the_box_upwards():
    """Verify walls move with artwork when the box grows upward."""
    from pandid.render.symbols import Overlay, compose

    body = Symbol(
        svg='<g id="sym_walled_test"><rect x="0" y="0" width="60" height="100" '
        'fill="none" stroke="black" stroke-width="2"/></g>',
        width=60.0,
        height=100.0,
        ports={"inlet": (0.0, 50.0), "outlet": (60.0, 50.0)},
        bands={"W": (20.0, 80.0), "E": (20.0, 80.0), "N": (10.0, 50.0)},
    )
    part = default_registry.part(20, "motor")
    grown = compose(body, [(Overlay(20, "motor", 0.35, -0.3, 0.3, 0.3), part)])
    lift = grown.height - body.height
    assert lift == pytest.approx(30.0), "the overlay was meant to lift the ink 30"
    for face, (lo, hi) in body.bands.items():
        shift = lift if face in ("W", "E") else 0.0
        assert grown.bands[face] == pytest.approx((lo + shift, hi + shift)), (
            f"the {face} wall did not move with its own ink"
        )
    moved = grown.ports["inlet"][1]
    assert grown.bands["W"][0] <= moved <= grown.bands["W"][1]


def test_a_pinned_series_member_stays_inside_the_band():
    """Verify pinned series members remain inside their bands."""
    from pandid.render.symbols import PortSeries

    series = PortSeries("feed_", "W", pitch=20.0, extent=0.7, at=50.0)
    band = (30.0, 70.0)
    assert series.placement(0, 1, 60.0, 100.0, pin=0.05, band=band) == (0.0, 30.0)
    assert series.placement(0, 1, 60.0, 100.0, pin=0.95, band=band) == (0.0, 70.0)
    assert series.placement(0, 1, 60.0, 100.0, pin=0.5, band=band) == (0.0, 50.0)
    assert series.placement(0, 1, 60.0, 100.0, pin=0.05) == (0.0, 5.0)


# Registry lookup invariants


def test_variants_lists_a_kinds_catalogue_default_first():
    """Verify variant lists place the default first."""
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
    """Verify unknown variants report registered alternatives."""
    with pytest.raises(ValueError) as excinfo:
        default_registry.get("vessel", "dishd")
    message = str(excinfo.value)
    assert "vessel has no variant 'dishd'" in message
    assert "did you mean 'dished'?" in message
    for variant in default_registry.variants("vessel"):
        assert variant in message


def test_a_variant_typo_stops_the_sheet_rather_than_drawing_something_else():
    """Verify a variant typo fails before rendering a sheet."""
    from pandid import Flowsheet, units as U

    fs = Flowsheet("typo")
    feed = fs.add(U.Feed("F"))
    tank = fs.add(U.Tank("TK-1", variant="dished"))
    fs.connect(feed.outlet, tank.inlet)
    with pytest.raises(ValueError, match=r"tank has no variant 'dished'"):
        fs.to_svg()


def test_a_kind_with_no_symbols_at_all_still_draws_a_generic_box():
    """Verify unregistered kinds render as generic boxes."""
    assert default_registry.variants("no_such_kind") == []
    assert default_registry.get("no_such_kind").symbol_id() == "sym_generic"
    assert default_registry.get("no_such_kind", "anything").symbol_id() == "sym_generic"


# Stencil-generation invariants


def test_the_generated_symbols_match_the_generator():
    """Verify generated symbols match the generator output."""
    vendor = _script("vendor_symbols")
    committed = vendor.OUT.read_text(encoding="utf-8")
    generated = vendor.render()
    assert generated == committed, "run scripts/vendor_symbols.py"


def test_every_stencil_shape_the_generator_vendors_may_be_stretched():
    """Verify vendored stencil shapes may be stretched."""
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


# Stencil fill and arc invariants


def test_the_sphere_draws_its_shell_over_its_nozzles():
    """Verify a sphere draws its shell over its nozzles."""
    svg = default_registry.get("tank", "sphere").svg
    assert svg.rindex("<ellipse") > svg.rindex("<rect"), "the shell is drawn last"
    shell = re.search(r"<ellipse[^>]*>", svg)
    assert 'fill="white"' in shell.group(0), "and is opaque, so it covers them"


_EMITTED_ARC = re.compile(rf"A ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM}) ({_NUM})")

_ARC_TOL = 1e-3

_PEN_LANDS_AT = {
    "move": ("x", "y"),
    "line": ("x", "y"),
    "quad": ("x2", "y2"),
    "curve": ("x3", "y3"),
}


def _stencil_arcs() -> list[tuple[str, tuple]]:
    """Read arcs used by vendored stencil shapes."""
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
    """Build stable identifiers for stencil arcs."""
    seen: dict[str, int] = {}
    ids = []
    for shape, _ in arcs:
        seen[shape] = seen.get(shape, 0) + 1
        ids.append(f"{shape}#{seen[shape]}")
    return ids


_STENCIL_ARCS = _stencil_arcs()


@pytest.mark.parametrize("shape,arc", _STENCIL_ARCS, ids=_arc_ids(_STENCIL_ARCS))
def test_every_piece_of_a_split_arc_rides_the_ellipse_it_was_cut_from(shape, arc):
    """Verify split arcs retain their source ellipse geometry."""
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


def test_every_stencil_patch_still_finds_its_shape():
    """Verify each stencil patch matches a source shape."""
    vendor = _script("vendor_symbols")
    assert vendor.STENCIL_PATCHES, "the patch table is where a stencil defect is recorded"
    for stencil, shape in vendor.STENCIL_PATCHES:
        names = {name for name, _ in vendor.shapes_in(vendor.STENCILS / f"{stencil}.xml")}
        assert shape in names, f"{stencil}.xml has no shape {shape!r} to patch"


def test_the_globe_and_ball_valves_are_not_one_drawing():
    """Verify globe and ball valves use distinct drawings."""
    globe = default_registry.get("valve", "globe")
    ball = default_registry.get("valve", "ball")
    assert _artwork(globe) != _artwork(ball)
    assert 'fill="#111"' in globe.svg, "the globe's seat is solid"
    assert 'fill="#111"' not in ball.svg, "the ball's seat is open"
    assert (globe.width, globe.height) == (ball.width, ball.height)
    assert globe.ports == ball.ports
    assert globe.port_faces == ball.port_faces


def test_every_paired_shape_is_one_device_in_two_positions():
    """Verify paired valve shapes describe one device in two positions."""
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
            f"{kind}/{variant}: the two positions differ in more than ink"
        )


def test_a_closed_drawing_may_not_be_registered_without_an_open_one():
    """Verify closed valve drawings require an open counterpart."""
    from pandid.render.symbols import SymbolRegistry

    sym = Symbol(svg='<g id="sym_x"/>', width=10.0, height=10.0, ports={"inlet": (0.0, 5.0)})
    with pytest.raises(ValueError, match="no open drawing"):
        SymbolRegistry().register_closed("fitting", sym, "no_such_variant")


# Valve-symbol invariants


def _artwork(sym: Symbol) -> str:
    """Remove a symbol identifier from artwork."""
    return re.sub(r'id="[^"]*"', "", sym.svg)


def _ink_extents(svg: str) -> list[tuple[str, float, float]]:
    """Measure extents of filled SVG elements."""
    found: list[tuple[str, float, float]] = []

    def walk(el, m: Matrix) -> None:
        """Traverse SVG elements for filled extents."""
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


_FEATURE_AREA = 0.5


def test_no_valve_body_is_drawn_filled():
    """Verify valve bodies are not filled by default."""
    for variant in default_registry.variants("valve"):
        valve = units.Valve("HV-1", variant=variant)
        assert valve.normal_position == "open", "an undeclared valve is not marked"
        sym = default_registry.for_unit(valve)
        for tag, w, h in _ink_extents(sym.svg):
            covered = (w * h) / (sym.width * sym.height)
            assert covered < _FEATURE_AREA, f"valve/{variant} fills a <{tag}> over {covered:.0%}"


def test_a_normally_closed_valve_is_the_one_valve_drawn_filled():
    """Verify normally closed valves render with filled bodies."""
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
            fill = max(
                [(w * h) / (sym.width * sym.height) for _, w, h in _ink_extents(sym.svg)],
                default=0.0,
            )
            assert fill >= _FEATURE_AREA, f"valve/{variant} draws no darkened body"
        else:
            assert mark == "NC"
            assert _artwork(sym) == _artwork(default_registry.get("valve", variant)), (
                f"valve/{variant} changes its artwork"
            )
    assert seen == set(default_registry.variants("valve"))


_VALVE_RUN_HEIGHT = 7.5

_VALVE_RUN_TOL = 0.25


_STRAIGHT_VALVES = sorted(
    variant
    for variant in default_registry.variants("valve")
    for faces in [default_registry.get("valve", variant).port_faces]
    if list(faces.get("inlet", ())) == ["W"] and list(faces.get("outlet", ())) == ["E"]
)


_OFF_THE_RUN = {
    "three_way": "The branch extends the box below the top-aligned process run.",
    "knife": "The gate housing extends below the process run.",
}


def _ink_below_the_run(sym: Symbol) -> float:
    """Measure ink depth below a valve run."""
    lowest = max(max(ay, by) for (_, ay), (_, by) in _collect_segments(sym.svg))
    return lowest - sym.ports["inlet"][1]


@pytest.mark.parametrize("variant", [v for v in _STRAIGHT_VALVES if v not in _OFF_THE_RUN])
def test_a_straight_through_valve_carries_the_run_at_one_height(variant):
    """Verify straight-through valves preserve run height."""
    sym = default_registry.get("valve", variant)
    for name in ("inlet", "outlet"):
        for face, (_, y) in sym.port_faces[name].items():
            above = sym.height - y
            assert above == pytest.approx(_VALVE_RUN_HEIGHT, abs=_VALVE_RUN_TOL), (
                f"valve/{variant} {name!r} ({face})"
            )


@pytest.mark.parametrize("variant", _STRAIGHT_VALVES)
def test_the_two_ends_of_a_straight_through_valve_are_level(variant):
    """Verify straight-through valve endpoints are level."""
    sym = default_registry.get("valve", variant)
    assert sym.ports["inlet"][1] == sym.ports["outlet"][1], f"valve/{variant}"


def test_exactly_the_valves_named_above_leave_the_run():
    """Verify only documented valve types leave the main run."""
    strayed = {
        variant
        for variant in _STRAIGHT_VALVES
        for sym in [default_registry.get("valve", variant)]
        if any(
            abs(sym.height - y - _VALVE_RUN_HEIGHT) > _VALVE_RUN_TOL
            for name in ("inlet", "outlet")
            for _, y in sym.port_faces[name].values()
        )
    }
    assert strayed == set(_OFF_THE_RUN)
    assert all(_OFF_THE_RUN.values()), "an exception without a reason is a list of names"


def test_the_valves_the_run_does_not_cross_are_out_of_scope():
    """Verify non-straight valve types are excluded from run checks."""
    assert sorted(set(default_registry.variants("valve")) - set(_STRAIGHT_VALVES)) == [
        "angle",
        "bleed",
        "psv",
        "relief",
    ]
    assert len(_OFF_THE_RUN) * 2 < len(_STRAIGHT_VALVES), "the exceptions would be the rule"


@pytest.mark.parametrize("variant", sorted(_OFF_THE_RUN))
def test_a_valve_drawn_below_the_run_is_drawn_there_in_ink(variant):
    """Verify below-run valves render at their declared offset."""
    plain = default_registry.get("valve", "gate")
    assert _ink_below_the_run(plain) == pytest.approx(_VALVE_RUN_HEIGHT)
    sym = default_registry.get("valve", variant)
    assert _ink_below_the_run(sym) > _ink_below_the_run(plain), _OFF_THE_RUN[variant]
    assert _ink_below_the_run(sym) == pytest.approx(
        sym.height - sym.ports["inlet"][1], abs=_VALVE_RUN_TOL
    ), f"valve/{variant} has whitespace under it, not a deeper drawing"


def test_the_three_way_carries_the_run_at_the_familys_height_from_the_top():
    """Verify three-way valves preserve their top-aligned run height."""
    sym = default_registry.get("valve", "three_way")
    for name in ("inlet", "outlet"):
        assert sym.ports[name][1] == pytest.approx(_VALVE_RUN_HEIGHT, abs=_VALVE_RUN_TOL)


_OFF_THE_MODULE = {
    "psv": (
        (55.5, 94.5),
        (19.8, 33.8),
        "The PSV stencil requires scaling to the valve family size.",
    ),
    "relief": (
        (40.0, 59.0),
        (15.0, 22.1),
        "The relief-valve stencil requires scaling to the family width.",
    ),
    "butterfly_pneumatic": (
        (60.0, 80.0),
        (24.5, 30.0),
        "The pneumatic butterfly requires non-uniform scaling.",
    ),
}

_ON_THE_MODULE_BY_FOLDING = {
    "angle": "The angle valve composes two valve-family triangles.",
}

_STILL_UNDERSIZED = {
    "bleed": "The bleeder-valve stencil remains narrower than the family.",
}


def _valve_stencil_boxes():
    """Read valve stencil dimensions."""
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
    """Verify external valve stencils are scaled to the family size."""
    stencil_box, emitted, why = _OFF_THE_MODULE[variant]
    vendor, boxes = _valve_stencil_boxes()
    assert boxes[variant] == stencil_box, why
    assert vendor.scale_for("valve", variant) != vendor.scale_for("valve", "gate"), (
        f"valve/{variant} on a {stencil_box[0]} x {stencil_box[1]} module is undersized: {why}"
    )
    sym = default_registry.get("valve", variant)
    assert (sym.width, sym.height) == emitted, why


def test_exactly_the_valves_named_above_are_drawn_off_the_stencils_module():
    """Verify only documented valves use external stencil sources."""
    _, boxes = _valve_stencil_boxes()
    off = {variant for variant, (w, _h) in boxes.items() if w < 98.0}
    assert off == set(_OFF_THE_MODULE) | set(_ON_THE_MODULE_BY_FOLDING) | set(_STILL_UNDERSIZED)
    assert set(_OFF_THE_MODULE) & set(_STILL_UNDERSIZED) == set(), (
        "a variant cannot be both rescaled and still waiting to be"
    )
    reasons = [entry[2] for entry in _OFF_THE_MODULE.values()]
    reasons += [*_ON_THE_MODULE_BY_FOLDING.values(), *_STILL_UNDERSIZED.values()]
    assert all(reasons), "an exception without a reason is a list of names"


def test_the_pneumatic_butterfly_is_back_on_the_run_because_it_is_rescaled():
    """Verify the rescaled pneumatic butterfly preserves run height."""
    vendor = _script("vendor_symbols")
    assert vendor.scale_for("valve", "butterfly_pneumatic") == (24.5 / 60, 15.0 / 40)
    sym = default_registry.get("valve", "butterfly_pneumatic")
    plain = default_registry.get("valve", "gate")
    assert (sym.width, sym.height / 2) == (plain.width, plain.height)
    assert "butterfly_pneumatic" not in _OFF_THE_RUN
    assert sym.height - sym.ports["inlet"][1] == _VALVE_RUN_HEIGHT
    assert _ink_below_the_run(sym) == pytest.approx(_ink_below_the_run(plain))


# General rendering and placement invariants


def _every_drawing():
    """Yield registered symbols and supplementary parts."""
    for key, sym in sorted(default_registry._symbols.items(), key=lambda kv: str(kv[0])):
        yield f"{key[0]}/{key[1]}", sym.svg
    for key, part in sorted(default_registry._parts.items(), key=lambda kv: str(kv[0])):
        yield f"part {key[0]}.{key[1]}", part.svg


@pytest.mark.parametrize(
    ("name", "svg"), list(_every_drawing()), ids=[n for n, _ in _every_drawing()]
)
def test_every_drawing_survives_being_scaled(name, svg):
    """Verify every drawing supports renderer scaling."""
    from pandid.render.svg import _baked

    _baked(svg, 1.37, 0.61)


@pytest.mark.parametrize("agitator", sorted(_AGITATORS))
def test_every_agitator_a_reactor_offers_can_be_drawn(agitator):
    """Verify every reactor agitator variant can be drawn."""
    from pandid import Flowsheet

    fs = Flowsheet("agitator")
    fs.add(units.Reactor("R-1", agitator=agitator))
    assert fs.to_svg()


# Port-series placement algorithms


@pytest.mark.parametrize("align", [CENTRED, FROM_START])
@pytest.mark.parametrize("count", range(1, 9))
def test_a_lone_member_sits_on_at_whichever_way_the_family_grows(align, count):
    """Verify lone series members retain their anchor position."""
    assert spread(0, 1, 120.0, 20.0, 0.5, 12.0, align) == 12.0
    run = [spread(i, count, 120.0, 20.0, 0.5, 12.0, align) for i in range(count)]
    assert run == sorted(run)
    assert all(b - a == pytest.approx(run[1] - run[0]) for a, b in zip(run, run[1:]))


def test_a_family_growing_from_its_start_never_reaches_back_past_it():
    """Verify start-aligned series do not extend before their anchors."""
    at, along = 12.0, 120.0
    centred = [spread(i, 3, along, 20.0, 0.5, at, CENTRED) for i in range(3)]
    started = [spread(i, 3, along, 20.0, 0.5, at, FROM_START) for i in range(3)]
    assert centred[0] < at < centred[-1]
    assert started[0] == at and started[-1] > at
    assert started == [12.0, 32.0, 52.0]


@pytest.mark.parametrize("align", [CENTRED, FROM_START])
def test_the_band_a_series_reports_is_the_run_it_really_draws(align):
    """Verify a series reports the band it actually draws."""
    series = PortSeries("feed_", "W", pitch=20.0, extent=0.5, at=12.0, align=align)
    _, lo, hi = series.reach(80.0, 120.0)
    for count in range(1, 9):
        for i in range(count):
            assert lo - 1e-9 <= series.placement(i, count, 80.0, 120.0)[1] <= hi + 1e-9


# Vendored-registry documentation invariants

_VENDORED_SOURCE_WORDS = {
    "valve": "valves",
    "pump": "pumps",
    "compressor": "compressors",
    "blower": "blowers",
    "cooler": "coolers",
    "heater": "heaters",
    "hex": "heat exchangers",
    "cooling_tower": "cooling towers",
    "vessel": "vessels",
    "column": "columns",
    "reactor": "reactors",
    "separator": "separators",
    "tank": "tanks",
    "dryer": "dryers",
    "filter": "filters",
    "furnace": "furnaces",
    "thickener": "thickeners",
    "turbine": "turbines",
    "reducer": "reducers",
    "fitting": "in-line fittings",
    "ejector": "ejectors",
    "vent": "vents",
    "funnel": "funnels",
}


def test_every_vendored_kind_is_named_in_the_module_docstring():
    """Verify module documentation lists every vendored kind."""
    import re

    import pandid.render.symbols as symbols_module
    from pandid.render._vendored_symbols import register_vendored

    fresh = default_registry.__class__.__new__(default_registry.__class__)
    fresh._symbols, fresh._darkened, fresh._closed = {}, {}, {}
    fresh._expanders, fresh._parts, fresh._composed = {}, {}, {}
    register_vendored(fresh)
    vendored_kinds = {kind for kind, _variant in fresh._symbols}

    assert vendored_kinds, "register_vendored() registered no (kind, variant) at all"

    unmapped = vendored_kinds - _VENDORED_SOURCE_WORDS.keys()
    assert not unmapped, f"{unmapped} are not in _VENDORED_SOURCE_WORDS"

    doc = " ".join((symbols_module.__doc__ or "").split())
    missing = [
        kind
        for kind in vendored_kinds
        if not re.search(rf"\b{re.escape(_VENDORED_SOURCE_WORDS[kind])}\b", doc)
    ]
    assert not missing, [_VENDORED_SOURCE_WORDS[k] for k in missing]
