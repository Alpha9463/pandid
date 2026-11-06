"""Check that a vessel's shell is built to its size, not scaled to it."""

import base64
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

import pytest

from pandid import Evaporator, Feed, Flare, Flowsheet, Product, Vessel
from pandid.portgeom import outward_dir, resolve_size
from pandid.render.iso_parts import _CLUTTERED, SUPPORTS
from pandid.render.symbols import (
    ARROWHEAD,
    MIN_HEAD_CLEARANCE,
    MIN_NOZZLE_PITCH,
    VESSEL_SIZES,
    default_registry,
    overlay_boxes,
    vessel_shell_fits,
)
from pandid.units import _drawn_parts
from test_symbol_invariants import _collect_segments, _nearest_distance

UPRIGHT = [v for v in VESSEL_SIZES if v not in ("horizontal", "dome")]
LYING = ["horizontal", "dome"]


@pytest.mark.parametrize("variant", UPRIGHT)
def test_a_taller_upright_shell_keeps_its_heads_and_lengthens_its_wall(variant):
    """Check that a stated height adds only to the straight shell."""
    natural = default_registry.get("vessel", variant)
    taller = Vessel("D-1", variant=variant, height=natural.height + 60).symbol()
    assert (taller.width, taller.height) == (natural.width, natural.height + 60)
    for name in ("vent", "relief"):
        assert taller.ports[name] == pytest.approx(natural.ports[name]), name
    assert taller.ports["drain"][1] == pytest.approx(natural.ports["drain"][1] + 60)
    for face, (lo, hi) in natural.bands.items():
        # The top head's one point stays where it is.
        want = (lo, hi) if face == "N" else (lo, hi + 60)
        assert taller.bands[face] == pytest.approx(want), face


@pytest.mark.parametrize("variant", LYING)
def test_a_longer_lying_shell_keeps_its_heads_and_lengthens_its_wall(variant):
    """Check that a stated width adds only to the straight shell."""
    natural = default_registry.get("vessel", variant)
    longer = Vessel("D-1", variant=variant, width=natural.width + 60).symbol()
    assert (longer.width, longer.height) == (natural.width + 60, natural.height)
    for name, anchor in (("in_1", "inlet"), ("out_1", "outlet")):
        assert longer.ports[name][1] == pytest.approx(natural.ports[anchor][1]), name
    for face, (lo, hi) in natural.bands.items():
        if lo < hi:
            assert longer.bands[face] == pytest.approx((lo, hi + 60)), face


@pytest.mark.parametrize("supports", SUPPORTS)
def test_a_support_keeps_its_own_size_on_any_shell(supports):
    """Check that a support is drawn the same size whatever the box."""
    sizes = []
    for height in (None, 160.0, 300.0):
        vessel = Vessel("D-1", supports=supports, height=height)
        body, parts, _, _ = _drawn_parts(vessel, vessel.__dict__["overlays"])
        sizes.append(
            [
                (round(x1 - x0, 6), round(y1 - y0, 6))
                for x0, y0, x1, y1 in overlay_boxes(body, parts)
            ]
        )
        assert resolve_size(vessel)[1] == pytest.approx(height or vessel.symbol().height)
    assert sizes[1] == sizes[0] and sizes[2] == sizes[0]


def _cases():
    """Yield every vessel variant, support, family role, face and count."""
    for variant in VESSEL_SIZES:
        body = default_registry.get("vessel", variant)
        for supports in (None, *SUPPORTS):
            for role, prefix in (("inlet", "in_"), ("outlet", "out_")):
                for face in body.port_faces.get(role, {}):
                    lo, hi = body.bands.get(face, (0.0, 1.0))
                    for count in range(1, 9 if lo < hi else 2):
                        yield variant, supports, role, prefix, face, count


def _build(variant, supports, role, face, count, **size):
    """Return the vessel for one case, or None where the variant refuses the support."""
    faces = [face] * count
    try:
        if role == "inlet":
            return Vessel("D-1", variant=variant, supports=supports, inputs=faces, **size)
        return Vessel("D-1", variant=variant, supports=supports, outputs=faces, **size)
    except ValueError as exc:
        assert "cannot carry" in str(exc), exc
        return None


def test_every_family_is_drawn_clear_of_the_supports_at_its_pitch():
    """Check that an unsized shell grows until each family clears its supports."""
    clearance = {"inlet": ARROWHEAD / 2 + MIN_HEAD_CLEARANCE, "outlet": MIN_HEAD_CLEARANCE}
    for variant, supports, role, prefix, face, count in _cases():
        vessel = _build(variant, supports, role, face, count)
        if vessel is None:
            continue
        sym = vessel.symbol()
        body, parts, _, _ = _drawn_parts(vessel, vessel.__dict__.get("overlays", ()))
        boxes = [
            box
            for part, box in zip(parts, overlay_boxes(body, parts))
            if part.name in SUPPORTS and part.name != "skirt"
        ]
        where = f"{variant} on {supports}, {count} on {face}"
        upright = face in ("W", "E")
        lo, hi = sym.bands[face]
        if lo >= hi:
            continue  # a head's apex, where the nozzle cannot move
        along = sorted(sym.ports[f"{prefix}{i}"][1 if upright else 0] for i in range(1, count + 1))
        if count > 1:
            assert min(b - a for a, b in zip(along, along[1:])) >= MIN_NOZZLE_PITCH - 1e-3, where
        for i in range(1, count + 1):
            x, y = sym.ports[f"{prefix}{i}"]
            assert outward_dir(x, y, sym.width, sym.height) == face, where
            for x0, y0, x1, y1 in boxes:
                beside = {
                    "W": x1 <= x + 1e-6,
                    "E": x0 >= x - 1e-6,
                    "N": y1 <= y + 1e-6,
                    "S": y0 >= y - 1e-6,
                }[face]
                lo, hi, t = (y0, y1, y) if upright else (x0, x1, x)
                if beside and lo < hi:
                    gap = max(lo - t, t - hi)
                    assert gap >= clearance[role] - 1e-6, f"{where}: {prefix}{i} {gap:.1f} off"


@pytest.mark.parametrize(
    "size", [{"width": 140.0}, {"height": 160.0}, {"width": 200.0, "height": 70.0}]
)
def test_a_stated_size_draws_every_family_member_on_its_wall(size):
    """Check that a shell built to a stated box keeps each member nearest its face."""
    for variant, supports, role, prefix, face, count in _cases():
        try:
            vessel = _build(variant, supports, role, face, count, **size)
            sym = vessel.symbol() if vessel is not None else None
        except ValueError as exc:
            assert "is too small to draw" in str(exc), exc
            continue
        if vessel is None or sym is None:
            continue
        w, h = resolve_size(vessel)
        assert (sym.width, sym.height) == pytest.approx((w, h)), "built to the box, not scaled"
        for i in range(1, count + 1):
            x, y = sym.ports[f"{prefix}{i}"]
            assert outward_dir(x, y, w, h) == face, f"{variant} on {supports}: {prefix}{i}"


def _fed(vessel):
    """Return a sheet with a line into each of the vessel's inlets."""
    fs = Flowsheet("supported")
    fs.add(vessel)
    for i, port in enumerate(vessel.inlets, 1):
        fs.connect(fs.add(Feed(f"F-{i}")).outlet, port)
    for i, port in enumerate(vessel.outlets, 1):
        fs.connect(port, fs.add(Product(f"P-{i}")).inlet)
    fs.layout()
    return fs


def test_a_line_through_a_support_is_reported():
    """Check that a line drawn through a support beside its nozzle is reported."""
    fs = Flowsheet("supported")
    evaporator = fs.add(Evaporator("E-1", supports="bracket"))
    fs.connect(evaporator.condensate, fs.add(Product("Condensate")).inlet)
    fs.layout()
    found = [i.message for i in fs.validate() if i.code == "line-through-support"]
    assert found == [
        "E-1: the line on condensate runs through its bracket support. Build E-1 with "
        "supports= that keep clear of the line"
    ]


def test_an_unsized_shell_grows_clear_of_its_supports():
    """Check that with no size stated the shell takes the room its lines need."""
    vessel = Vessel("D-1", variant="swaged", supports="bracket")
    fs = _fed(vessel)
    assert [i for i in fs.validate() if i.code == "line-through-support"] == []
    assert vessel.symbol().height > default_registry.get("vessel", "swaged").height


def test_a_box_too_small_for_the_heads_is_refused_with_the_size_that_fits():
    """Check that a height the heads cannot fit in names the least that can."""
    with pytest.raises(
        ValueError, match=r"D-1: a height of 60 is too small .* give height=63 or more"
    ):
        Vessel("D-1", variant="swaged", height=60).symbol()


#: Distance a nozzle may sit from the drawn outline.
ON_OUTLINE = 0.1

#: Distance a part's corner may sit from the outline and still meet it.
TOUCHING = 0.5


def _sizes():
    """Yield each variant at its own size and over a grid down to its least."""
    for variant, (nw, nh) in VESSEL_SIZES.items():
        widths = (None, vessel_shell_fits(variant)[0], 1.5 * nw, 3 * nw)
        for width in widths:
            least = vessel_shell_fits(variant)[1]
            for height in (None, least, 1.5 * nh, 3 * nh):
                yield variant, width, height


def _stencil_segments(style: str) -> list:
    """Return the outline a draw.io inline stencil draws, in its own units."""
    packed = re.search(r"shape=stencil\(([^)]*)\)", style)
    assert packed, f"no inline stencil in {style!r}"
    xml = urllib.parse.unquote(zlib.decompress(base64.b64decode(packed.group(1)), -15).decode())
    shape = ET.fromstring(xml)
    art = []
    for element in shape.iter():
        if element.tag == "path":
            d = []
            for step in element:
                a = step.attrib
                if step.tag in ("move", "line"):
                    d.append(f"{'M' if step.tag == 'move' else 'L'} {a['x']} {a['y']}")
                elif step.tag == "arc":
                    d.append(
                        f"A {a['rx']} {a['ry']} {a['x-axis-rotation']} {a['large-arc-flag']} "
                        f"{a['sweep-flag']} {a['x']} {a['y']}"
                    )
                elif step.tag == "close":
                    d.append("Z")
            art.append(f'<path d="{" ".join(d)}"/>')
        elif element.tag == "rect":
            a = element.attrib
            art.append(f'<rect x="{a["x"]}" y="{a["y"]}" width="{a["w"]}" height="{a["h"]}"/>')
    return _collect_segments(f"<g>{''.join(art)}</g>")


@pytest.mark.parametrize(("variant", "width", "height"), list(_sizes()))
def test_every_nozzle_is_on_the_outline_in_svg_and_drawio(variant, width, height):
    """Check every nozzle sits on the shell's outline as drawn and as exported."""
    vessel = _drawable(variant, {}, {"width": width, "height": height})
    assert vessel is not None
    fs = Flowsheet("outline")
    fs.add(vessel)
    fs.connect(fs.add(Feed("Feed")).outlet, vessel.inlet)
    fs.connect(vessel.outlet, fs.add(Product("Product")).inlet)
    for port in (vessel.vent, vessel.relief):
        fs.connect(port, fs.add(Flare(f"FL-{port.name}")).inlet)
    fs.connect(vessel.drain, fs.add(Product("Drain")).inlet)
    fs.to_svg(diagram="p&id")
    sym = vessel.symbol()
    segments = _collect_segments(sym.svg)
    for name, point in sym.ports.items():
        assert _nearest_distance(point, segments) <= ON_OUTLINE, f"svg {name}"
    cells = {c.get("id"): c for c in ET.fromstring(fs.to_drawio(diagram="p&id")).iter("mxCell")}
    shell = next(c for c in cells.values() if c.get("value") == "D-1")
    stencil = _stencil_segments(shell.get("style", ""))
    for cell in cells.values():
        style = cell.get("style", "")
        for end, key in (("source", "exit"), ("target", "entry")):
            if cell.get(end) != shell.get("id"):
                continue
            at = re.search(rf"{key}X=([\d.]+);{key}Y=([\d.]+)", style)
            assert at, f"{cell.get('value')} names no {key} point"
            point = (float(at.group(1)) * sym.width, float(at.group(2)) * sym.height)
            assert _nearest_distance(point, stencil) <= ON_OUTLINE, f"drawio {cell.get('value')}"


#: Each fitting a shell can carry, as constructor keywords.
FITTINGS = {
    "bare": {},
    **{name: {"supports": name} for name in SUPPORTS},
    "walls": {"manholes": "walls", "sockets": "walls"},
}


def _wall_places(variant: str) -> dict:
    """Return a manhole and a socket on the middle of a variant's walls."""
    body = default_registry.get("vessel", variant)
    walls = [
        f
        for f, (lo, hi) in body.bands.items()
        if lo < hi and f not in _CLUTTERED.get(("vessel", variant), ())
    ]
    if not walls:
        return {}
    face = walls[0]
    lo, hi = body.bands[face]
    along = body.height if face in ("W", "E") else body.width
    return {
        "manholes": [(face, (lo + 0.25 * (hi - lo)) / along)],
        "sockets": [(face, (lo + 0.75 * (hi - lo)) / along)],
    }


def _build_case(variant: str, fitting: str, width, height):
    """Return the vessel for one case, at the size its refusal names if it refuses."""
    body = default_registry.get("vessel", variant)
    keywords = dict(FITTINGS[fitting])
    if fitting == "walls":
        keywords = _wall_places(variant)
        if not keywords:
            return None
    family = {}
    for role, keyword in (("inlet", "inputs"), ("outlet", "outputs")):
        face = outward_dir(*body.ports[role], body.width, body.height)
        lo, hi = body.bands.get(face, (0.0, 0.0))
        family[keyword] = 2 if lo < hi else 1
    return _drawable(variant, {**keywords, **family}, {"width": width, "height": height})


def _drawable(variant: str, keywords: dict, size: dict):
    """Return a vessel at a size, or at the size its refusal names."""
    for _ in range(3):
        try:
            vessel = Vessel("D-1", variant=variant, **keywords, **size)
            vessel.symbol()
            return vessel
        except ValueError as exc:
            if "cannot carry" in str(exc):
                return None
            fits = re.findall(r"(width|height)=([\d.]+)", str(exc).split("give")[-1])
            assert fits, exc
            size.update((axis, float(value)) for axis, value in fits)
    raise AssertionError(f"{variant} with {keywords}: the size a refusal names is refused")


def _drawn_shell(vessel):
    """Return a vessel's symbol, its shell's outline and its parts' boxes."""
    sym = vessel.symbol()
    body, parts, _, _ = _drawn_parts(vessel, vessel.__dict__.get("overlays", ()))
    ox = -min([0.0, *(o.x * body.width for o in parts)])
    oy = -min([0.0, *(o.y * body.height for o in parts)])
    outline = [
        ((ax + ox, ay + oy), (bx + ox, by + oy))
        for (ax, ay), (bx, by) in _collect_segments(body.svg)
    ]
    return sym, outline, list(zip(parts, overlay_boxes(body, parts)))


def _crosses(a, b, c, d) -> bool:
    """Return whether segment ab meets segment cd."""

    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return (side(a, b, c) * side(a, b, d) <= 0) and (side(c, d, a) * side(c, d, b) <= 0)


def _touches(box, outline) -> bool:
    """Return whether a part's box meets the shell's outline."""
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    for a, b in outline:
        if any(_crosses(a, b, c, d) for c, d in edges):
            return True
        if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (a, b)):
            return True
    # The outline's arcs are drawn as chords, which fall inside them.
    return min(_nearest_distance(c, outline) for c in corners) <= TOUCHING


def _faces_out(point, face, width, height, outline) -> bool:
    """Return whether a nozzle's line leaves without running along the outline."""
    dx, dy = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}[face]
    reach = {"N": point[1], "S": height - point[1], "W": point[0], "E": width - point[0]}[face]
    along, t = 0.0, 0.5
    while t < reach:
        if _nearest_distance((point[0] + dx * t, point[1] + dy * t), outline) < 0.25:
            along += 0.25
        t += 0.25
    return along <= 1.0


def _check_drawn(where, vessel, sym, outline, parts):
    """Check a drawing's parts, nozzles and families against its shell."""
    for part, box in parts:
        if part.name in (
            *SUPPORTS,
            "manhole",
            "manhole_up",
            "manhole_down",
            "socket",
            "socket_up",
            "socket_down",
        ):
            assert _touches(box, outline), f"{where}: the {part.name} floats"
    sockets = [box for part, box in parts if part.name.startswith("socket")]
    for name, point in sym.ports.items():
        # A socket's line starts at its flange, off the shell.
        on = (
            outline
            if not name.startswith("socket_")
            else [
                seg
                for x0, y0, x1, y1 in sockets
                for seg in (
                    ((x0, y0), (x1, y0)),
                    ((x1, y0), (x1, y1)),
                    ((x1, y1), (x0, y1)),
                    ((x0, y1), (x0, y0)),
                )
            ]
        )
        assert _nearest_distance(point, on) <= ON_OUTLINE, f"{where}: {name} off the shell"
        x, y = point
        face = outward_dir(x, y, sym.width, sym.height)
        assert _faces_out(point, face, sym.width, sym.height, outline), (
            f"{where}: {name} faces {face} along the shell"
        )
    families: dict = {}
    for name, face in vessel._faces.items():
        x, y = sym.ports[name]
        families.setdefault((name[:3], face), []).append(y if face in ("W", "E") else x)
    for members in families.values():
        members.sort()
        assert all(b - a >= MIN_NOZZLE_PITCH - 1e-3 for a, b in zip(members, members[1:])), where


def _fitted_cases():
    """Yield every variant and fitting over a grid of sizes."""
    for variant, (nw, nh) in VESSEL_SIZES.items():
        for fitting in FITTINGS:
            for width in (None, 1.0, 2 * nw):
                for height in (None, 1.0, 2 * nh):
                    yield variant, fitting, width, height


@pytest.mark.parametrize(("variant", "fitting", "width", "height"), list(_fitted_cases()))
def test_every_part_and_nozzle_sits_on_the_shell_in_svg_and_drawio(variant, fitting, width, height):
    """Check parts touch the shell, nozzles face out and families keep their pitch."""
    vessel = _build_case(variant, fitting, width, height)
    if vessel is None:
        return
    where = f"{variant} with {fitting} at {width}x{height}"
    sym, outline, parts = _drawn_shell(vessel)
    _check_drawn(f"svg {where}", vessel, sym, outline, parts)
    fs = Flowsheet("fitted")
    fs.add(vessel)
    cells = {c.get("id"): c for c in ET.fromstring(fs.to_drawio(check=False)).iter("mxCell")}
    shell = next(c for c in cells.values() if c.get("value") == "D-1")
    geometry = shell.find("mxGeometry")
    assert geometry is not None
    kx = sym.width / float(geometry.get("width", "1"))
    ky = sym.height / float(geometry.get("height", "1"))
    exported = []
    for cell in cells.values():
        if cell.get("parent") != shell.get("id") or "-p" not in (cell.get("id") or ""):
            continue
        g = cell.find("mxGeometry")
        assert g is not None
        x, y = float(g.get("x", "0")) * kx, float(g.get("y", "0")) * ky
        w, h = float(g.get("width", "0")) * kx, float(g.get("height", "0")) * ky
        exported.append((parts[len(exported)][0], (x, y, x + w, y + h)))
    assert len(exported) == len(parts), f"drawio {where}: a part is not exported"
    _check_drawn(
        f"drawio {where}", vessel, sym, _stencil_segments(shell.get("style", "")), exported
    )
