"""Check that a vessel's shell is built to its size, not scaled to it."""

import base64
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

import pytest

from pandid import Feed, Flare, Flowsheet, Product, Vessel
from pandid.portgeom import outward_dir, resolve_size
from pandid.render.iso_parts import SUPPORTS
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
        assert taller.bands[face] == pytest.approx((lo, hi + 60)), face


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
            assert "is too small to draw" in str(exc) or "leaves no room on its walls" in str(
                exc
            ), exc
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
    """Check that a stated size with no clear wall for a line is reported."""
    fs = _fed(Vessel("D-1", variant="swaged", supports="bracket", height=97.5))
    found = sorted(i.message for i in fs.validate() if i.code == "line-through-support")
    assert [m.split(" runs")[0] for m in found] == [
        "D-1: the line on in_1",
        "D-1: the line on out_1",
    ]
    assert all("through its bracket support" in m and "D-1.height" in m for m in found)


def test_an_unsized_shell_grows_clear_of_its_supports():
    """Check that with no size stated the shell takes the room its lines need."""
    vessel = Vessel("D-1", variant="swaged", supports="bracket")
    fs = _fed(vessel)
    assert [i for i in fs.validate() if i.code == "line-through-support"] == []
    assert vessel.symbol().height > default_registry.get("vessel", "swaged").height


def test_a_box_too_small_for_the_heads_is_refused_with_the_size_that_fits():
    """Check that a height the heads cannot fit in names the least that can."""
    with pytest.raises(ValueError, match=r"D-1: a height of 60 is too small .* give height=62\.5"):
        Vessel("D-1", variant="swaged", height=60).symbol()


#: Distance a nozzle may sit from the drawn outline.
ON_OUTLINE = 0.1


def _sizes():
    """Yield each variant at its own size and over a grid down to its least."""
    for variant, (nw, nh) in VESSEL_SIZES.items():
        widths = (None, vessel_shell_fits(variant, nw)[0], 1.5 * nw, 3 * nw)
        for width in widths:
            least = vessel_shell_fits(variant, width or nw)[1]
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
    vessel = Vessel("D-1", variant=variant, width=width, height=height)
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
