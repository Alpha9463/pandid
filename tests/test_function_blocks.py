"""Check function blocks drawn beside a balloon, in SVG and draw.io."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units

#: A balloon's circle: its radius about the centre of its 44-unit box.
_RADIUS = 21.0


def _blocks(svg: str) -> list[tuple[float, float, float, float, str]]:
    """Return each outlined box in the label group, with the text drawn at its middle."""
    body = svg.split('<g id="unit_labels">', 1)[1].split("</g>", 1)[0]
    rects = [
        tuple(map(float, m))
        for m in re.findall(
            r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)" '
            r'fill="white" stroke=',
            body,
        )
    ]
    texts = [
        (float(x), float(y), t)
        for x, y, t in re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>([^<]*)</text>', body)
    ]
    out = []
    for x, y, w, h in rects:
        inside = [
            t for tx, ty, t in texts if abs(tx - (x + w / 2)) < 0.6 and abs(ty - (y + h / 2)) < 0.6
        ]
        out.append((x, y, w, h, inside[0] if inside else ""))
    return out


def _balloon(**kwargs) -> tuple[Flowsheet, units.Instrument]:
    """Return a laid-out sheet with one balloon FY-101 at (200, 200)."""
    fs = Flowsheet("block")
    fy = fs.add_instrument("FY", 101, **kwargs).pin(x=200, y=200)
    fs.layout()
    return fs, fy


def test_a_function_block_touches_the_balloon_at_its_upper_right():
    """Draw ISA's function block: a square outside the balloon, its corner on the circle."""
    fs, fy = _balloon(function="I/P")
    frame = fy.frame
    assert frame is not None
    cx, cy = frame.x + frame.w / 2, frame.y + frame.h / 2
    (block,) = _blocks(fs.to_svg(check=False))
    x, y, w, h, text = block
    assert text == "I/P"
    assert w == pytest.approx(h) and 16 <= w <= 30
    # Its lower-left corner sits on the circle, up and to the right of the centre.
    corner = (x, y + h)
    assert math.dist(corner, (cx, cy)) == pytest.approx(_RADIUS, abs=1.0)
    assert corner[0] - cx == pytest.approx(cy - corner[1], abs=1.0) and corner[0] > cx


@pytest.mark.parametrize("variant", ["default", "shared", "computer", "sis", "interlock"])
def test_the_block_meets_every_balloon_outline_at_a_corner(variant):
    """Put the block's inner corner on the drawn outline, out from the centre."""
    from pandid.render.symbols import default_registry
    from test_symbol_invariants import _collect_segments, _nearest_distance

    fs, fy = _balloon(function="Σ", variant=variant)
    frame = fy.frame
    assert frame is not None
    (block,) = _blocks(fs.to_svg(check=False))
    x, y, _w, h, text = block
    assert text == "Σ"
    outline = _collect_segments(default_registry.get("instrument", fy.variant).svg)
    corner = (x - frame.x, y + h - frame.y)
    assert _nearest_distance(corner, outline) <= 1.5
    assert corner[0] > frame.w / 2 and corner[1] < frame.h / 2


def test_a_balloon_without_a_function_draws_no_block():
    """Draw no box beside a plain balloon."""
    fs, _fy = _balloon()
    assert _blocks(fs.to_svg(check=False)) == []


@pytest.mark.parametrize(
    "typed,drawn",
    [
        ("sqrt", "√"),
        ("√", "√"),
        ("sum", "Σ"),
        ("average", "Σ/n"),
        ("high select", ">"),
        ("max", "MAX"),
        ("E/P", "E/P"),
        ("derivative", "dx/dt"),
        ("bias", "±"),
    ],
)
def test_a_function_is_typed_as_an_engineer_writes_it(typed, drawn):
    """Accept the symbol or its word, and draw the symbol."""
    assert units.Instrument("FY", 101, function=typed).function == drawn


@pytest.mark.parametrize("typed", ["", "foo", "I/I", "4-20mA"])
def test_an_unknown_function_is_refused_naming_the_ones_drawn(typed):
    """Refuse a function the standards draw no block for, listing the spellings."""
    with pytest.raises(ValueError, match="'sqrt'") as caught:
        units.Instrument("FY", 101, function=typed)
    assert "I/P" in str(caught.value)


def test_a_function_reads_back_from_its_spec():
    """Keep the function block through ``to_dict`` and ``from_dict``."""
    fs, _fy = _balloon(function="sqrt")
    (read,) = Flowsheet.from_dict(fs.to_dict()).units
    assert isinstance(read, units.Instrument) and read.function == "√"


def test_the_block_takes_another_corner_when_a_line_crosses_the_upper_right():
    """Move the block to a clear corner rather than draw it over a line."""
    fs = Flowsheet("crossed")
    fy = fs.add_instrument("FY", 101, function="I/P").pin(x=200, y=200)
    # A pipe runs just above the balloon, through the upper corners' height,
    # and stops short of the left one.
    feed = fs.add(units.Feed("F")).pin(x=300, y=190)
    prod = fs.add(units.Product("P")).pin(x=560, y=190)
    fs.connect(feed.outlet, prod.inlet)
    fs.route()
    frame = fy.frame
    assert frame is not None
    cx, cy = frame.x + frame.w / 2, frame.y + frame.h / 2
    (block,) = _blocks(fs.to_svg(check=False))
    x, y, w, h, _text = block
    # Not over the pipe at y=190, so below the balloon's centre or left of it.
    assert not (y <= 190 <= y + h and x + w >= 300)
    assert x + w / 2 < cx or y + h / 2 > cy


def _tag_box(svg: str, tag: str) -> tuple[float, float, float, float]:
    """Return a box round a tag's 12-pt text, from its anchor and baseline."""
    found = re.search(
        rf'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*text-anchor="(\w+)" '
        rf'dominant-baseline="(\w+)">{re.escape(tag)}</text>',
        svg,
    )
    assert found is not None, f"{tag} is not drawn"
    x, y, anchor, baseline = float(found[1]), float(found[2]), found[3], found[4]
    width = 7.0 * len(tag)
    x0 = {"middle": x - width / 2, "end": x - width}.get(anchor, x)
    y0 = y - 6 if baseline == "middle" else y - 10
    return (x0, y0, x0 + width, y0 + 12)


def _apart(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Return whether two boxes ``(x0, y0, x1, y1)`` do not overlap."""
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def _block_box(svg: str) -> tuple[float, float, float, float]:
    """Return the one function block's box."""
    ((x, y, w, h, _text),) = _blocks(svg)
    return (x, y, x + w, y + h)


# A balloon whose upper-right block would land on HV-101's tag above it.
_BALLOON_AT, _VALVE_AT = (222.4, 131.35), (288.0, 142.5)


def test_a_block_moves_off_a_tag_that_cannot_move():
    """Take another corner where the upper right would cover a fixed tag."""
    fs = Flowsheet("fixed tag")
    fy = fs.add_instrument("FY", 101, function="I/P").pin(x=_BALLOON_AT[0], y=_BALLOON_AT[1])
    fs.add(units.Valve("HV-101", label_pos="top")).pin(x=_VALVE_AT[0], y=_VALVE_AT[1])
    fs.layout()
    svg = fs.to_svg(check=False)
    tag, block = _tag_box(svg, "HV-101"), _block_box(svg)
    frame = fy.frame
    assert frame is not None
    # The premise: the upper-right corner is where the tag is.
    corner = frame.x + frame.w / 2 + 14.85, frame.y + frame.h / 2 - 14.85
    assert not _apart(tag, (corner[0], corner[1] - 22, corner[0] + 22, corner[1]))
    assert _apart(tag, block)


def test_a_tag_moves_off_a_block_hemmed_in_at_its_corner():
    """Move a valve's tag off a block whose other corners lines cross."""
    fs = Flowsheet("hemmed")
    fs.add(units.Valve("HV-101")).pin(x=_VALVE_AT[0], y=_VALVE_AT[1])
    fy = fs.add_instrument("FY", 101, function="I/P").pin(x=_BALLOON_AT[0], y=_BALLOON_AT[1])
    f1 = fs.add(units.Feed("F1")).pin(x=214.4, y=60)
    p1 = fs.add(units.Product("P1")).pin(x=214.4, y=320)
    fs.connect(f1.outlet, p1.inlet)
    f2 = fs.add(units.Feed("F2")).pin(x=120, y=179.35)
    p2 = fs.add(units.Product("P2")).pin(x=420, y=179.35)
    fs.connect(f2.outlet, p2.inlet)
    fs.route()
    svg = fs.to_svg(check=False)
    frame = fy.frame
    assert frame is not None
    block = _block_box(svg)
    # The block keeps the upper right, the only corner no line crosses.
    assert block[0] > frame.x + frame.w / 2 and block[3] < frame.y + frame.h / 2
    assert _apart(_tag_box(svg, "HV-101"), block)


def test_the_block_exports_to_drawio_where_the_sheet_draws_it():
    """Write the block as an outlined child cell of the balloon holding its symbol."""
    fs, fy = _balloon(function="sqrt")
    (block,) = _blocks(fs.to_svg(check=False))
    root = ET.fromstring(fs.to_drawio(check=False))
    cells = {c.get("id", ""): c for c in root.iter("mxCell")}
    balloon = next(c for c in cells.values() if (c.get("value") or "").startswith("FY"))
    (child,) = [c for c in cells.values() if c.get("parent") == balloon.get("id")]
    assert child.get("value") == "√"
    style = child.get("style") or ""
    assert "strokeColor=none" not in style and "fillColor=#ffffff" in style
    # Child geometry is relative to the balloon's cell, at the sheet's scale.
    box, own = child.find("mxGeometry"), balloon.find("mxGeometry")
    assert box is not None and own is not None and fy.frame is not None
    scale = float(own.get("width", 0)) / fy.frame.w
    x, y, w, h, _text = block
    got = [float(box.get(k, 0)) / scale for k in ("x", "y", "width", "height")]
    assert got == pytest.approx([x - fy.frame.x, y - fy.frame.y, w, h], abs=0.1)
