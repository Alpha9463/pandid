"""Test stream-label enclosure geometry, findings, and exports.

Small flowsheets test isolated geometry. Selected gallery sheets test dense
label layouts; representative golden fixtures own default-render integration.
"""

import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

import pytest

from pandid import Feed, Flowsheet, Pump, ShellAndTubeExchanger, Tank, Vessel
from pandid.document import StreamLabelOptions
from pandid.render.drawio import _tag_pass
from pandid.render.symbols import default_registry
from pandid.render.svg import (
    _HALO_CHAR,
    _HALO_DEEP,
    _HALO_PAD,
    _ink,
    _LABEL_CODES,
    _meets,
    _shape_hits,
    _shapes_meet,
    enclosure_box,
    fillable_enclosures,
    hop_box,
    HOP_R,
    JUMP_DIRECTIONS,
    sheet_connections,
    stream_hops,
    stream_numbers,
)
from pandid.spec import SpecError, from_dict, to_dict
from _render_cases import gallery

#: Supported non-default stream-label enclosure shapes.
SHAPES = ("diamond", "circle", "box")

#: Gallery sheet with vertical labels and leaders.
CROWDED = "13_mineral_dewatering"

#: Gallery sheet with crossing runs and line jumps.
CROSSED = "11_ethanol_pid"

#: Gallery sheets with label-pair findings across all enclosure shapes.
LABEL_CASES = ("11_ethanol_pid", "13_mineral_dewatering", "14_tank_farm")


def sheet(scheme: "str | Callable[[int], str]" = "S{n}") -> Flowsheet:
    """Build a small flowsheet for stream-label enclosure checks.

    Parameters
    ----------
    scheme : str | Callable[[int], str]
        Stream naming scheme for the test flowsheet.

    Returns
    -------
    Flowsheet
        Small flowsheet with connected process streams.
    """
    fs = Flowsheet("enclosure", stream_naming_scheme=scheme)
    f = fs.add(Feed("Broth"))
    t = fs.add(Tank("T-101"))
    p = fs.add(Pump("P-101"))
    hx = fs.add(ShellAndTubeExchanger("E-101"))
    v = fs.add(Vessel("V-101"))
    fs.connect(f.outlet, t.inlet)
    fs.connect(t.outlet, p.suction)
    fs.connect(p.discharge, hx.tube_in)
    fs.connect(hx.tube_out, v.inlet)
    return fs


def numbers(fs: Flowsheet, **kwargs) -> list:
    """Return resolved stream-label placements for a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet under test.
    **kwargs : object
        Render options passed to the target backend.

    Returns
    -------
    list
        Resolved stream-label placements.
    """
    fs.to_svg(**kwargs)
    joints = sheet_connections(kwargs.get("diagram"), kwargs.get("connections"))
    plates = list(_tag_pass(fs, default_registry, joints, "vertical").plates)
    return list(stream_numbers(fs, plates, joints, "vertical"))


def halo(name: str) -> "tuple[float, float]":
    """Return the text-plate dimensions for a stream label.

    Parameters
    ----------
    name : str
        Scenario or stream identifier under test.

    Returns
    -------
    tuple[float, float]
        Width and height of the label text plate.
    """
    return len(name) * _HALO_CHAR + _HALO_PAD, _HALO_DEEP


def drawn(shape: str, box, ink: str = "black", fill: bool = False) -> str:
    """Return an SVG enclosure element for a label box.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.
    ink : str
        Stroke colour used by the generated SVG.
    fill : bool
        Whether the generated enclosure is filled.

    Returns
    -------
    str
        SVG element for the requested enclosure.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pen = f'fill="{"white" if fill else "none"}" stroke="{ink}" stroke-width="1" />'
    if shape == "diamond":
        return (
            f'<polygon points="{cx:.1f},{y0:.1f} {x1:.1f},{cy:.1f} '
            f'{cx:.1f},{y1:.1f} {x0:.1f},{cy:.1f}" {pen}'
        )
    if shape == "circle":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{(x1 - x0) / 2:.1f}" {pen}'
    return f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" {pen}'


def plate(box) -> str:
    """Return an SVG text plate for a label box.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.

    Returns
    -------
    str
        SVG rectangle for the label text plate.
    """
    x0, y0, x1, y1 = box
    return (
        f'<rect x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" fill="white" />'
    )


SVG_NS = "{http://www.w3.org/2000/svg}"

_NUMBER = r"-?\d+(?:\.\d+)?"
_COMMAND = re.compile(rf"([MLA])\s*((?:{_NUMBER}[,\s]*)+)")


def _streams_group(svg: str):
    """Return the SVG group containing rendered process streams.

    Parameters
    ----------
    svg : str
        Rendered SVG document text.

    Returns
    -------
    xml.etree.ElementTree.Element
        Element with the ``streams`` identifier.
    """
    root = ET.fromstring(svg)
    return next(g for g in root.iter(f"{SVG_NS}g") if g.get("id") == "streams")


def drawn_runs(svg: str) -> "list[tuple[list, float]]":
    """Return process-stream segments parsed from rendered SVG.

    Parameters
    ----------
    svg : str
        Rendered SVG document text.

    Returns
    -------
    list[tuple[list, float]]
        Stream segments and their stroke widths.
    """
    out = []
    for node in _streams_group(svg).iter(f"{SVG_NS}path"):
        width = node.get("stroke-width")
        if node.get("fill") != "none" or width is None:
            continue
        out.append((_segments(node.get("d") or ""), float(width)))
    return out


def drawn_plates(svg: str) -> "list[tuple[float, float, float, float]]":
    """Return label plates parsed from rendered SVG.

    Parameters
    ----------
    svg : str
        Rendered SVG document text.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Label plates rendered in the SVG.
    """
    out = []
    for node in _streams_group(svg).iter(f"{SVG_NS}rect"):
        if node.get("fill") != "white" or node.get("stroke"):
            continue
        x, y = float(node.get("x") or 0), float(node.get("y") or 0)
        # Round to SVG serialization precision.
        out.append(
            (
                round(x, 4),
                round(y, 4),
                round(x + float(node.get("width") or 0), 4),
                round(y + float(node.get("height") or 0), 4),
            )
        )
    return out


def as_drawn(box) -> "tuple[float, float, float, float]":
    """Return an enclosure shape parsed from rendered SVG.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.

    Returns
    -------
    tuple[float, float, float, float]
        Parsed enclosure geometry.
    """
    x0, y0 = round(box[0], 1), round(box[1], 1)
    return (
        x0,
        y0,
        round(x0 + round(box[2] - box[0], 1), 4),
        round(y0 + round(box[3] - box[1], 1), 4),
    )


def _segments(d: str) -> "list[tuple[tuple[float, float], tuple[float, float]]]":
    """Return straight segments represented by an SVG path.

    Parameters
    ----------
    d : str
        SVG path data.

    Returns
    -------
    list[tuple[tuple[float, float], tuple[float, float]]]
        Straight path segments.
    """
    pts: list[tuple[float, float]] = []
    here = (0.0, 0.0)
    for cmd, raw in _COMMAND.findall(d):
        nums = [float(v) for v in re.findall(_NUMBER, raw)]
        if cmd in "ML":
            here = (nums[0], nums[1])
            pts.append(here)
        else:  # A rx ry rotation large sweep x y
            radius, _ry, _rot, large, sweep, ex, ey = nums[:7]
            pts.extend(_chords(here, (ex, ey), radius, int(large), int(sweep)))
            here = (ex, ey)
            pts.append(here)
    return list(zip(pts, pts[1:]))


def _chords(start, end, radius, large, sweep, steps=180):
    """Return chord segments for an SVG arc.

    Parameters
    ----------
    start : tuple[float, float]
        Starting point of an SVG arc.
    end : tuple[float, float]
        Ending point of an SVG arc.
    radius : float
        Arc radius used to construct chord segments.
    large : bool
        Whether the SVG arc uses the large-arc flag.
    sweep : bool
        Whether the SVG arc uses the sweep flag.
    steps : int
        Number of chord segments used for an SVG arc.

    Returns
    -------
    list
        Chord segments approximating an SVG arc.
    """
    (x0, y0), (x1, y1) = start, end
    dx, dy = (x1 - x0) / 2, (y1 - y0) / 2
    half = math.hypot(dx, dy)
    if half == 0 or radius == 0:
        return []
    radius = max(radius, half)
    off = math.sqrt(max(radius * radius - half * half, 0.0))
    sign = 1 if large != sweep else -1
    cx = (x0 + x1) / 2 + sign * off * (-dy / half)
    cy = (y0 + y1) / 2 + sign * off * (dx / half)
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    if sweep and a1 < a0:
        a1 += 2 * math.pi
    if not sweep and a1 > a0:
        a1 -= 2 * math.pi
    return [
        (
            cx + radius * math.cos(a0 + (a1 - a0) * i / steps),
            cy + radius * math.sin(a0 + (a1 - a0) * i / steps),
        )
        for i in range(1, steps)
    ]


def stroke_meets(rect, segment, width: float) -> bool:
    """Return whether a stroke intersects a label plate.

    Parameters
    ----------
    rect : tuple[float, float, float, float]
        Label plate rectangle under test.
    segment : tuple[tuple[float, float], tuple[float, float]]
        Rendered stream segment under test.
    width : float
        Rendered stream stroke width.

    Returns
    -------
    bool
        Whether the stroke reaches the plate.
    """
    half = width / 2
    x0, y0 = rect[0] - half, rect[1] - half
    x1, y1 = rect[2] + half, rect[3] + half
    (ax, ay), (bx, by) = segment
    dx, dy = bx - ax, by - ay
    lo, hi = 0.0, 1.0
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
        if p == 0:
            if q <= 0:
                return False
        else:
            t = q / p
            if p < 0:
                lo = max(lo, t)
            else:
                hi = min(hi, t)
    return lo < hi


def corners(shape: str, box) -> "list[tuple[float, float]]":
    """Return the corners of an enclosure box.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.

    Returns
    -------
    list[tuple[float, float]]
        Corner coordinates in drawing order.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if shape == "diamond":
        return [(cx, y0), (x1, cy), (cx, y1), (x0, cy)]
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def shared(shape: str, box, other) -> float:
    """Return the shared area of two enclosure shapes.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.
    other : object
        Second geometry value under test.

    Returns
    -------
    float
        Area shared by the two enclosure shapes.
    """
    poly = corners(shape, box)
    clip = corners(shape, other)
    for i, stop in enumerate(clip):
        start = clip[i - 1]
        kept: "list[tuple[float, float]]" = []
        for j, here in enumerate(poly):
            prev = poly[j - 1]
            if _left(start, stop, here) >= 0:
                if _left(start, stop, prev) < 0:
                    kept.append(_cut(prev, here, start, stop))
                kept.append(here)
            elif _left(start, stop, prev) >= 0:
                kept.append(_cut(prev, here, start, stop))
        poly = kept
        if not poly:
            return 0.0
    twice = sum(poly[i - 1][0] * q[1] - q[0] * poly[i - 1][1] for i, q in enumerate(poly))
    return abs(twice) / 2


def crosses(shape: str, box, other) -> bool:
    """Return whether two enclosure shapes intersect.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.
    other : object
        Second geometry value under test.

    Returns
    -------
    bool
        Whether the enclosure shapes intersect.
    """
    if shape != "circle":
        return shared(shape, box, other) > 0
    ax, ay = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    bx, by = (other[0] + other[2]) / 2, (other[1] + other[3]) / 2
    radii = (box[2] - box[0]) / 2 + (other[2] - other[0]) / 2
    return math.hypot(bx - ax, by - ay) < radii


def _left(a, b, p) -> float:
    """Return the signed side of a point relative to a segment.

    Parameters
    ----------
    a : tuple[float, float]
        Point used by the geometry helper.
    b : tuple[float, float]
        Second point used by the geometry helper.
    p : tuple[float, float]
        Point used by the geometry helper.

    Returns
    -------
    float
        Signed side value for the point and segment.
    """
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _cut(p, q, a, b) -> "tuple[float, float]":
    """Return the intersection point of two line segments.

    Parameters
    ----------
    p : tuple[float, float]
        Point used by the geometry helper.
    q : tuple[float, float]
        Second point used by the geometry helper.
    a : tuple[float, float]
        Point used by the geometry helper.
    b : tuple[float, float]
        Second point used by the geometry helper.

    Returns
    -------
    tuple[float, float] | None
        Intersection point, when the segments meet.
    """
    d1, d2 = _left(a, b, p), _left(a, b, q)
    t = d1 / (d1 - d2)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def inside(shape: str, box, point) -> bool:
    """Return whether a point lies inside an enclosure shape.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    box : tuple[float, float, float, float]
        Bounding box used by the geometry check.
    point : tuple[float, float]
        Point evaluated by the geometry check.

    Returns
    -------
    bool
        Whether the point lies within the shape.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a, b = (x1 - x0) / 2, (y1 - y0) / 2
    dx, dy = abs(point[0] - cx), abs(point[1] - cy)
    tol = 1e-6
    if shape == "diamond":
        return dx / a + dy / b <= 1 + tol
    if shape == "circle":
        return math.hypot(dx, dy) <= a + tol
    return dx <= a + tol and dy <= b + tol


# Default enclosure behaviour.


def test_a_new_flowsheet_rules_nothing_around_its_labels():
    """Test that a new flowsheet rules nothing around its labels.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert Flowsheet("x").stream_labels.enclosure == "none"


def test_stating_the_default_draws_the_sheet_the_default_draws():
    """Test that stating the default draws the sheet the default draws.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    plain = sheet().to_svg()
    stated = sheet()
    stated.stream_labels.enclosure = "none"
    assert stated.to_svg() == plain


def test_the_export_is_unchanged_where_no_enclosure_is_asked_for():
    """Test that the export is unchanged where no enclosure is asked for.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    plain = fs.to_drawio()
    fs.stream_labels.enclosure = "none"
    assert fs.to_drawio() == plain
    assert "-box" not in plain


# Enclosure geometry.


@pytest.mark.parametrize("shape", SHAPES)
def test_the_shape_is_ruled_round_the_box_reserved_and_fills_none_of_it(shape):
    """Test that the shape is ruled round the box reserved and fills none of it.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = shape
    ruled = fs.to_svg()
    placed = numbers(fs)
    assert placed

    fillable = fillable_enclosures(fs, shape, placed, "vertical")
    assert all(fillable), (
        f"{shape}: this fixture is uncrowded, so every shape on it should be "
        f"clear enough to fill; got {fillable}"
    )
    for number, fill in zip(placed, fillable):
        assert ruled.count(drawn(shape, number.box, fill=fill)) == 1, (
            f"{shape}: {number.name} is not drawn to fill the box reserved for it"
        )
        # The uncrowded fixture keeps every label plate.
        assert number.words is not None
        assert ruled.count(plate(number.words)) == 1
        # The label plate is smaller than its enclosure.
        assert number.words != number.box


@pytest.mark.parametrize("shape", SHAPES)
def test_the_words_fit_inside_the_shape_ruled_around_them(shape):
    """Test that the words fit inside the shape ruled around them.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet(scheme=lambda n: str(n) if n % 2 else str(1000 + n))
    fs.stream_labels.enclosure = shape
    for number in numbers(fs):
        w, h = halo(number.name)
        if number.vertical:
            w, h = h, w
        for sx in (-1, 1):
            for sy in (-1, 1):
                point = (number.x + sx * w / 2, number.y + sy * h / 2)
                assert inside(shape, number.box, point), (
                    f"{shape}: {number.name} is written outside its own enclosure"
                )


# Shared enclosure size.


@pytest.mark.parametrize("shape", SHAPES)
def test_one_size_rules_every_label_however_long_its_own_name_is(shape):
    """Test that one size rules every label however long its own name is.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet(scheme=lambda n: str(n) if n % 2 else str(1000 + n))
    fs.stream_labels.enclosure = shape
    placed = numbers(fs)
    names = [n.name for n in placed]
    assert min(len(x) for x in names) == 1 and max(len(x) for x in names) == 4

    sizes = {
        (round(n.box[2] - n.box[0], 6), round(n.box[3] - n.box[1], 6))
        for n in placed
        if not n.vertical
    }
    assert len(sizes) == 1, f"{shape}: {len(sizes)} sizes on one sheet"
    widest = max(halo(name)[0] for name in names)
    assert sizes.pop() == pytest.approx(enclosure_box(shape, widest, _HALO_DEEP))


@pytest.mark.parametrize("shape", SHAPES)
def test_a_label_on_a_vertical_run_turns_its_shape_with_it(shape):
    """Test that a label on a vertical run turns its shape with it.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = shape
    placed = numbers(fs, **kwargs)

    flat = {
        (round(n.box[2] - n.box[0], 6), round(n.box[3] - n.box[1], 6))
        for n in placed
        if not _on_a_vertical_run(n)
    }
    turned = {
        (round(n.box[3] - n.box[1], 6), round(n.box[2] - n.box[0], 6))
        for n in placed
        if _on_a_vertical_run(n)
    }
    assert flat and turned, "the fixture has to draw both, or this checks nothing"
    assert flat == turned


# Enclosed-label placement.


def _on_a_vertical_run(number) -> bool:
    """Return whether a stream-number segment is vertical.

    Parameters
    ----------
    number : object
        Resolved stream-number placement.

    Returns
    -------
    bool
        Whether the vertical span exceeds the horizontal span.
    """
    (x1, y1), (x2, y2) = number.seg
    return abs(x2 - x1) < abs(y2 - y1)


def _on_its_run(number) -> "tuple[bool, float, float]":
    """Return whether a label remains on its stream run.

    Parameters
    ----------
    number : object
        Resolved stream-number placement.

    Returns
    -------
    tuple[bool, float, float]
        Run-membership result and measured spans.
    """
    (x1, y1), (x2, y2) = number.seg
    if abs(x2 - x1) < abs(y2 - y1):
        axis, centre, span = (x1 + x2) / 2, number.x, abs(y2 - y1)
        reach = number.box[3] - number.box[1]
    else:
        axis, centre, span = (y1 + y2) / 2, number.y, abs(x2 - x1)
        reach = number.box[2] - number.box[0]
    return abs(centre - axis) <= 0.5, span, reach


@pytest.mark.parametrize("stem", LABEL_CASES, ids=LABEL_CASES)
@pytest.mark.parametrize("shape", SHAPES)
def test_an_enclosed_label_is_written_on_its_run_and_never_beside_it(shape, stem):
    """Keep enclosed labels on representative dense stream runs.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    stem : str
        Gallery example identifier.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(stem)
    fs.stream_labels.enclosure = shape
    placed = numbers(fs, **kwargs)
    assert placed
    for number in placed:
        on, span, reach = _on_its_run(number)
        assert on, (
            f"{stem}: {number.name}'s {shape} left its run, which is {span:.1f} "
            f"units long against a {reach:.1f}-unit shape"
        )
        assert number.leader is None, f"{stem}: {number.name} carries a leader"


def test_a_shape_too_big_for_its_run_stays_on_the_line_anyway():
    """Test that a shape too big for its run stays on the line anyway.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet(scheme="VERY-LONG-STREAM-{n}00")
    fs.stream_labels.enclosure = "diamond"
    placed = numbers(fs)
    assert placed
    overrun = 0
    for number in placed:
        on, span, reach = _on_its_run(number)
        assert on, f"{number.name} left its run"
        overrun += reach > span
    assert overrun, "no diamond here is too big for its run, so nothing is tested"


def test_a_bare_label_still_leaves_the_line_where_it_always_did():
    """Test that a bare label still leaves the line where it always did.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    assert any(not _on_its_run(n)[0] for n in numbers(fs, **kwargs)), (
        "the fixture has to displace a bare label, or the pair proves nothing"
    )


def test_the_crowded_sheet_keeps_its_leaders_bare_and_drops_them_when_ruled():
    """Test that the crowded sheet keeps its leaders bare and drops them when ruled.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    assert [n for n in numbers(fs, **kwargs) if n.leader is not None], (
        "this sheet is the fixture because its bare labels draw leaders"
    )

    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    svg = fs.to_svg(**kwargs)
    assert not [n for n in numbers(fs, **kwargs) if n.leader is not None]
    # Enclosed labels do not write leader arrowheads.
    assert svg.count("<path d=") == 0 or "leader" not in svg


def test_the_sheet_draws_a_bare_label_s_leader_over_its_halo():
    """Test that the sheet draws a bare label s leader over its halo.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    svg = fs.to_svg(**kwargs)
    plain = [n for n in numbers(fs, **kwargs) if n.leader is not None]
    assert plain
    for number in plain:
        (ax, ay), _ = number.leader
        assert svg.index(f'<line x1="{ax:.1f}" y1="{ay:.1f}"') > svg.index(plate(number.box))


# Label plates and crossing streams.

#: Gallery sheet and label with no safe opaque plate.
PLATELESS_SHEET = "18_fixed_bed_recycle"
PLATELESS = "350-LG-314-CS"


def foreign(fs, name) -> list:
    """Return stream ink that belongs to another label.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet under test.
    name : str
        Scenario or stream identifier under test.

    Returns
    -------
    list
        Ink boxes belonging to other streams.
    """
    return [line.box for line in _ink(fs, "vertical") if line.line != name]


@pytest.mark.parametrize("stem", LABEL_CASES, ids=LABEL_CASES)
@pytest.mark.parametrize("shape", ("none", *SHAPES))
def test_no_label_paints_out_a_line_that_is_not_its_own(shape, stem):
    """Keep label plates clear of unrelated rendered stream ink.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    stem : str
        Gallery example identifier.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(stem)
    fs.stream_labels.enclosure = shape
    svg = fs.to_svg(**kwargs)
    placed = numbers(fs, **kwargs)
    assert placed
    runs = drawn_runs(svg)
    # Draw one run per stream in stream order.
    assert len(runs) == len(fs.streams), f"{stem}: {len(runs)} runs drawn"
    # Every resolved plate is rendered in the SVG.
    assert sorted(drawn_plates(svg)) == sorted(
        as_drawn(n.words) for n in placed if n.words is not None
    ), f"{stem}: the plates in the file are not the plates the placement laid"

    for number in placed:
        if number.words is None:
            continue
        plate_box = as_drawn(number.words)
        for stream, (segments, width) in zip(fs.streams, runs):
            if stream.name == number.name:
                continue
            for segment in segments:
                assert not stroke_meets(plate_box, segment, width), (
                    f"{stem}: {number.name}'s plate at {shape!r} is laid over "
                    f"{stream.name}'s drawn run near "
                    f"{tuple(round(v, 2) for v in segment[0])}, which it deletes"
                )


def crossing_sheet() -> "tuple[Flowsheet, str]":
    """Build a flowsheet with a stream crossing.

    Returns
    -------
    tuple[Flowsheet, str]
        Crossed flowsheet and rendered SVG.
    """
    fs = Flowsheet("hop")
    west = fs.add(Feed("West")).pin(x=100, y=300)
    east = fs.add(Tank("T-101")).pin(x=500, y=270)
    north = fs.add(Feed("North")).pin(x=300, y=100)
    south = fs.add(Tank("T-102")).pin(x=270, y=480)
    fs.connect(west.outlet, east.inlet)  # S1, the horizontal one
    fs.connect(north.outlet, south.inlet)  # S2, the vertical one
    # Render before inspecting stream geometry.
    return fs, fs.to_svg()


def test_the_hop_the_sheet_draws_is_the_hop_the_search_is_told_about():
    """Test that the hop the sheet draws is the hop the search is told about.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, _ = crossing_sheet()
    # The hopping stream is drawn as an arc.
    svg = fs.to_svg(crossing_style="arc")
    hops = stream_hops(fs, "vertical")
    assert len(hops) == 1, "the fixture has to draw exactly one hop"
    hop = hops[0]

    # The rendered hop occupies the expected arc box.
    segments, _width = drawn_runs(svg)[hop.stream]
    near = [
        p
        for segment in segments
        for p in segment
        if abs((p[1] - hop.y) if hop.vertical else (p[0] - hop.x)) <= HOP_R + 0.01
    ]
    assert near, "the sheet drew nothing where the hop is supposed to be"
    offsets = [(p[0] - hop.x) if hop.vertical else (p[1] - hop.y) for p in near]
    stand = max(offsets, key=abs)
    assert abs(stand) == pytest.approx(HOP_R, abs=0.01), "no arc stands off the run"
    assert (stand > 0) is (hop.side > 0), "the arc leaves the run the other way"

    # The placement search reserves the rendered hop ink.
    reserved = [line for line in _ink(fs, "vertical") if line.kind == "hop"]
    assert len(reserved) == 1
    assert reserved[0].line == hop.line
    # The reserved hop box includes stream stroke padding.
    own = [line for line in _ink(fs, "vertical") if line.line == hop.line and line.kind != "hop"]
    assert own, "the hopping run has to have a route, or this proves nothing"
    pad = min((line.x1 - line.x0) if hop.vertical else (line.y1 - line.y0) for line in own) / 2
    assert reserved[0].box == hop_box(hop, pad)
    # The hop reserves ink outside the stream's straight route.
    tip = (hop.x + hop.side * HOP_R, hop.y) if hop.vertical else (hop.x, hop.y + hop.side * HOP_R)
    route = [
        line.box for line in _ink(fs, "vertical") if line.line == hop.line and line.kind != "hop"
    ]
    assert route, "the hopping run has to have a route, or this proves nothing"
    assert not any(b[0] <= tip[0] <= b[2] and b[1] <= tip[1] <= b[3] for b in route), (
        "the arc's far point is already inside the hopping run's own straight "
        "ink, so this fixture cannot tell a hop-aware model from a blind one"
    )


def test_a_hop_belongs_to_the_run_that_draws_it_and_to_no_other():
    """Test that a hop belongs to the run that draws it and to no other.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, _svg = crossing_sheet()
    hop = stream_hops(fs, "vertical")[0]
    vertical = next(s for s in fs.streams if s.source.owner.name == "North")
    horizontal = next(s for s in fs.streams if s.source.owner.name == "West")
    assert hop.vertical and hop.line == vertical.name
    assert hop.line != horizontal.name
    # The alternate direction assigns the hop to the other stream.
    other = stream_hops(fs, "horizontal")
    assert len(other) == 1 and not other[0].vertical
    assert other[0].line == horizontal.name


@pytest.mark.parametrize("shape", SHAPES)
def test_a_label_with_nowhere_clear_for_its_plate_lays_none(shape):
    """Test that a label with nowhere clear for its plate lays none.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(PLATELESS_SHEET)
    fs.stream_labels.enclosure = shape
    svg = fs.to_svg(**kwargs)
    placed = numbers(fs, **kwargs)
    assert [n.name for n in placed if n.words is None] == [PLATELESS]

    for number in placed:
        w, h = halo(number.name)
        if number.vertical:
            w, h = h, w
        would_be = (number.x - w / 2, number.y - h / 2, number.x + w / 2, number.y + h / 2)
        if number.words is None:
            # The label has no opaque plate.
            assert plate(would_be) not in svg
            assert plate(number.box) not in svg
            # Crossing runs prevent a safe plate.
            assert any(_meets(would_be, b) for b in foreign(fs, number.name))
        else:
            assert number.words == pytest.approx(would_be)
            assert svg.count(plate(number.words)) == 1


@pytest.mark.parametrize("shape", SHAPES)
def test_the_author_is_told_when_the_number_itself_is_written_across_a_run(shape):
    """Test that the author is told when the number itself is written across a run.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(PLATELESS_SHEET)
    fs.stream_labels.enclosure = shape
    fs.to_svg(**kwargs)
    said = {i.message.split("'s ")[0]: i.message for i in findings(fs, {"label-over-line"})}
    assert set(said) == {PLATELESS}, "only the plateless label is written across"
    assert "is written across" in said[PLATELESS]
    # The finding names each crossing stream.
    crossed = next(n.crossed for n in numbers(fs, **kwargs) if n.name == PLATELESS)
    assert crossed
    for run in crossed:
        assert run in said[PLATELESS]
    # The enclosure finding does not duplicate the label warning.
    for issue in findings(fs, {"enclosure-over-line"}):
        assert "written on clear paper" not in issue.message
        assert "was dropped" not in issue.message


def no_clear_paper() -> Flowsheet:
    """Build a flowsheet with no clear label plates.

    Returns
    -------
    Flowsheet
        Flowsheet with no clear text-plate positions.
    """
    fs = Flowsheet("dense", stream_naming_scheme="L" + "0" * 22 + "{n}")
    for row in range(13):
        y = 400 + row * 14
        feed = fs.add(Feed(f"F{row}")).pin(x=200, y=y)
        vessel = fs.add(Vessel(f"V-{row}")).pin(x=900, y=y - 50)
        fs.connect(feed.outlet, vessel.inlet)
    for picket in range(14):
        x = 300 + picket * 30
        top = fs.add(Tank(f"TA-{picket}")).pin(x=x, y=120)
        bottom = fs.add(Tank(f"TB-{picket}")).pin(x=x, y=900)
        fs.connect(top.outlet, bottom.inlet)
    return fs


def test_the_default_says_so_when_a_label_gives_up_its_plate():
    """Test that the default says so when a label gives up its plate.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = no_clear_paper()
    fs.to_svg(check=False)
    plateless = [n.name for n in numbers(fs, check=False) if n.words is None]
    assert plateless, "the fixture has to force a plate off, or this is vacuous"

    said = findings(fs, {"label-over-line"})
    assert [i.message.split("'s ")[0] for i in said] == plateless
    for issue in said:
        assert issue.severity == "warning"
        assert "is written across" in issue.message
    # A bare label has no enclosure findings.
    assert not findings(fs, set(_LABEL_CODES) - {"label-over-line"})


def test_both_backends_say_it_at_the_default_too():
    """Test that both backends say it at the default too.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = no_clear_paper()
    fs.to_svg(check=False)
    sheet_said = [(i.code, i.message) for i in findings(fs)]
    assert sheet_said, "the fixture has to report something"
    fs.to_drawio(check=False)
    assert [(i.code, i.message) for i in findings(fs)] == sheet_said


def test_a_bare_label_on_the_same_sheet_keeps_every_plate():
    """Test that a bare label on the same sheet keeps every plate.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    placed = numbers(fs, **kwargs)
    assert placed
    assert all(n.words is not None for n in placed)


# Enclosure option validation.


def test_a_shape_nobody_draws_is_refused_at_the_constructor():
    """Test that a shape nobody draws is refused at the constructor.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(ValueError, match="enclosure must be one of"):
        StreamLabelOptions(enclosure="rhombus")  # type: ignore[arg-type]


def test_a_shape_nobody_draws_is_refused_at_the_render():
    """Test that a shape nobody draws is refused at the render.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = "rhombus"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="enclosure must be one of"):
        fs.to_svg()
    with pytest.raises(ValueError, match="enclosure must be one of"):
        fs.to_drawio()


@pytest.mark.parametrize("draw", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("check", [True, False])
def test_a_refused_shape_leaves_the_sheet_exactly_as_it_found_it(draw, check):
    """Test that a refused shape leaves the sheet exactly as it found it.

    Parameters
    ----------
    draw : str
        Renderer method under test.
    check : bool
        Whether the test expects the operation to fail.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = "rhombus"  # type: ignore[assignment]
    fs.warnings = ["a finding from an earlier render"]  # type: ignore[list-item]
    before = (
        fs._layout_stale,
        fs._route_stale,
        [u.frame for u in fs.units],
        [s.route for s in fs.streams],
        list(fs.warnings),
        [s.name for s in fs.streams],
    )
    with pytest.raises(ValueError, match="enclosure must be one of"):
        getattr(fs, draw)(check=check)
    assert (
        fs._layout_stale,
        fs._route_stale,
        [u.frame for u in fs.units],
        [s.route for s in fs.streams],
        list(fs.warnings),
        [s.name for s in fs.streams],
    ) == before


@pytest.mark.parametrize("draw", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("spelling", ["vertcial", "Vertical", "none", "", "up"])
def test_a_jump_direction_nobody_draws_is_refused(draw, spelling):
    """Test that a jump direction nobody draws is refused.

    Parameters
    ----------
    draw : str
        Renderer method under test.
    spelling : str
        Configured jump-direction spelling.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    allowed = _DRAWIO_KWARGS if draw == "to_drawio" else kwargs
    passed = {k: v for k, v in kwargs.items() if k in allowed}
    with pytest.raises(ValueError, match="Unknown jump_direction"):
        getattr(fs, draw)(jump_direction=spelling, **passed)


@pytest.mark.parametrize("spelling", list(JUMP_DIRECTIONS))
def test_both_spellings_the_sheet_draws_are_taken(spelling):
    """Test that both spellings the sheet draws are taken.

    Parameters
    ----------
    spelling : str
        Configured jump-direction spelling.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROSSED)
    drawn = fs.to_svg(jump_direction=spelling, **kwargs)
    assert drawn
    hops = stream_hops(fs, spelling)
    assert hops and all(h.vertical is (spelling == "vertical") for h in hops)


# Enclosure collision findings.


def findings(fs, codes=None) -> list:
    """Return label-related render findings for a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet under test.
    codes : set[str] | None
        Finding codes to retain, when provided.

    Returns
    -------
    list
        Matching renderer findings.
    """
    return [w for w in fs.warnings if w.code in _LABEL_CODES and (codes is None or w.code in codes)]


def test_a_bare_sheet_is_told_nothing_about_enclosures():
    """Test that a bare sheet is told nothing about enclosures.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.to_svg(**kwargs)
    assert not findings(fs)


def test_the_author_is_told_which_unit_a_diamond_was_drawn_over():
    """Test that the author is told which unit a diamond was drawn over.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    over_units = findings(fs, {"enclosure-over-unit"})
    assert over_units
    for issue in over_units:
        assert issue.severity == "warning"
        assert " is drawn over " in issue.message
        # Each finding names the label and unit.
        assert any(u.name in issue.message for u in fs.units)


def test_the_author_is_told_which_line_a_diamond_was_drawn_over():
    """Test that the author is told which line a diamond was drawn over.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    over_lines = findings(fs, {"enclosure-over-line"})
    assert over_lines
    named = {i.message.split("'s diamond")[0] for i in over_lines}
    assert "FB-307-250-160-SS" in named
    said = next(i for i in over_lines if i.message.startswith("FB-307-250-160-SS"))
    assert "HPS-308-100-80-CS" in said.message
    for issue in over_lines:
        assert issue.severity == "warning"

    # Reported shapes remain unfilled.
    placed = numbers(fs, **kwargs)
    fills = dict(
        zip(
            (n.name for n in placed),
            fillable_enclosures(fs, "diamond", placed, kwargs.get("jump_direction", "vertical")),
        )
    )
    for name in named:
        assert fills[name] is False, (
            f"{name}'s diamond is reported as drawn over another line and is "
            f"filled white, so it is deleting that line rather than crowding it"
        )


def reported_pairs(fs, shape: str) -> set:
    """Return stream-label pairs reported as intersecting.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet under test.
    shape : str
        Enclosure shape under test.

    Returns
    -------
    set[frozenset[str]]
        Reported label-pair intersections.
    """
    out = set()
    for issue in findings(fs, {"enclosure-over-label"}):
        first, _, rest = issue.message.partition(f"'s {shape} crosses ")
        for other in rest.split("'s.")[0].split(", "):
            assert frozenset((first, other)) not in out, "reported both ways round"
            out.add(frozenset((first, other)))
    return out


def test_two_shapes_that_do_not_touch_are_not_called_a_collision():
    """Test that two shapes that do not touch are not called a collision.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    a = (753.6273224043716, 647.0, 976.4273224043716, 673.0)
    b = (533.6382513661202, 642.0, 756.4382513661202, 668.0)
    assert _meets(a, b), "the boxes do overlap, which is what made this hard"
    assert _shape_hits("diamond", a, b) and _shape_hits("diamond", b, a)
    assert shared("diamond", a, b) == 0
    assert not _shapes_meet("diamond", a, b)
    assert not _shapes_meet("diamond", b, a)


@pytest.mark.parametrize("shape", SHAPES)
def test_every_pair_the_sheet_calls_crossed_really_crosses(shape):
    """Match reported enclosure intersections with independent geometry.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    reported = 0
    for stem in LABEL_CASES:
        fs, kwargs = gallery.flowsheet(stem)
        fs.stream_labels.enclosure = shape
        fs.to_svg(**kwargs)
        named = reported_pairs(fs, shape)
        reported += len(named)
        placed = numbers(fs, **kwargs)
        for i, number in enumerate(placed):
            for other in placed[:i]:
                pair = frozenset((number.name, other.name))
                assert (pair in named) == crosses(shape, number.box, other.box), (
                    f"{stem}: {shape}s of {number.name} and {other.name} "
                    f"{'were' if pair in named else 'were not'} called crossed"
                )
    assert reported, f"{shape}: representative sheets have no reported intersections"


def test_two_shapes_crossing_are_reported_once():
    """Test that two shapes crossing are reported once.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    assert reported_pairs(fs, "diamond")


def test_a_second_render_replaces_the_findings_rather_than_repeating_them():
    """Test that a second render replaces the findings rather than repeating them.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    once = findings(fs)
    assert once
    fs.to_svg(**kwargs)
    assert [i.message for i in findings(fs)] == [i.message for i in once]
    fs.stream_labels.enclosure = "none"
    fs.to_svg(**kwargs)
    assert not findings(fs)


def test_both_backends_report_the_same_findings_and_both_report_some():
    """Test that both backends report the same findings and both report some.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    sheet_said = [(i.code, i.message) for i in findings(fs)]
    assert sheet_said, "the fixture has to report something, or parity is vacuous"
    fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
    export_said = [(i.code, i.message) for i in findings(fs)]
    assert export_said and export_said == sheet_said


def test_a_shape_nobody_draws_is_refused_in_a_spec():
    """Test that a shape nobody draws is refused in a spec.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(SpecError, match=r"stream_labels\.enclosure"):
        from_dict({"name": "x", "stream_labels": {"enclosure": "hexagon"}})


def test_an_unknown_key_under_stream_labels_is_refused():
    """Test that an unknown key under stream labels is refused.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(SpecError, match="stream_labels"):
        from_dict({"name": "x", "stream_labels": {"shape": "diamond"}})


def test_the_enclosure_comes_through_a_spec_round_trip():
    """Test that the enclosure comes through a spec round trip.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = "diamond"
    assert to_dict(fs)["stream_labels"] == {"enclosure": "diamond"}
    assert from_dict(to_dict(fs)).stream_labels.enclosure == "diamond"


def test_a_shape_nobody_draws_is_refused_on_the_way_out_to_a_spec():
    """Test that a shape nobody draws is refused on the way out to a spec.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = "rhombus"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="enclosure must be one of"):
        to_dict(fs)


@pytest.mark.parametrize(
    "typed, meant",
    [("rhombus", "diamond"), ("Oval ", "circle"), ("square", "box"), ("off", "none")],
)
def test_the_refusal_names_the_shape_the_author_probably_meant(typed, meant):
    """Test that the refusal names the shape the author probably meant.

    Parameters
    ----------
    typed : str
        Unsupported enclosure name supplied by the user.
    meant : str
        Suggested supported enclosure shape.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(ValueError, match=f"spells that one '{meant}'"):
        StreamLabelOptions(enclosure=typed)


def test_a_shape_nobody_has_a_name_for_is_refused_without_a_guess():
    """Test that a shape nobody has a name for is refused without a guess.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(ValueError) as raised:
        StreamLabelOptions(enclosure="hexagon")  # type: ignore[arg-type]
    assert "spells that one" not in str(raised.value)


def test_a_sheet_that_left_the_labels_alone_writes_the_spec_it_always_wrote():
    """Test that a sheet that left the labels alone writes the spec it always wrote.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert "stream_labels" not in to_dict(sheet())


# draw.io export.

_DRAWIO_KWARGS = ("diagram", "page_size", "border", "show_stream_table", "connections")

#: draw.io cell shape for each stream-label enclosure.
_EXPORTED = {"diamond": "rhombus", "circle": "ellipse", "box": "rounded"}


def cells(fs, **kwargs) -> "list[ET.Element]":
    """Return draw.io cells produced for a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet under test.
    **kwargs : object
        Render options passed to the target backend.

    Returns
    -------
    list[xml.etree.ElementTree.Element]
        Parsed draw.io cells in document order.
    """
    text = fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
    return list(ET.fromstring(text).iter("mxCell"))


def style(cell) -> dict:
    """Parse a draw.io cell style into key-value pairs.

    Parameters
    ----------
    cell : xml.etree.ElementTree.Element
        Draw.io cell with an optional style attribute.

    Returns
    -------
    dict[str, str]
        Style entries keyed by draw.io property name.
    """
    out = {}
    for key in (cell.get("style") or "").split(";"):
        if key:
            name, _, value = key.partition("=")
            out[name] = value
    return out


@pytest.mark.parametrize("shape", SHAPES)
def test_the_export_draws_the_enclosure_the_sheet_draws(shape):
    """Test that the export draws the enclosure the sheet draws.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = sheet()
    fs.stream_labels.enclosure = shape
    placed = {n.name: n for n in numbers(fs)}
    found = {c.get("id"): c for c in cells(fs)}
    seen = set()
    for cid, cell in found.items():
        if not cid or not cid.endswith("-box"):
            continue
        name = cell.get("value")
        assert name in placed
        seen.add(name)
        assert _EXPORTED[shape] in style(cell)
        # The enclosure remains unfilled.
        assert style(cell)["fillColor"] == "none"
        assert style(cell)["labelBackgroundColor"] == "#ffffff"
        geometry = cell.find("mxGeometry")
        assert geometry is not None
        x0, y0, x1, y1 = placed[name].box
        got = tuple(float(geometry.get(k) or 0) for k in ("x", "y", "width", "height"))
        # draw.io coordinates use two decimal places.
        assert got == pytest.approx((x0, y0, x1 - x0, y1 - y0), abs=0.01)
        # The edge label is removed after creating its enclosure cell.
        assert not found[cid[: -len("-box")]].get("value")
    assert seen == set(placed)


def test_the_export_writes_every_enclosure_after_every_run():
    """Test that the export writes every enclosure after every run.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    order = [c.get("id") or "" for c in cells(fs, **kwargs)]
    edges = [i for i, cid in enumerate(order) if re.fullmatch(r"s\d+", cid)]
    boxes = [i for i, cid in enumerate(order) if cid.endswith("-box")]
    assert edges and boxes
    assert min(boxes) > max(edges)


def test_the_export_writes_no_leader_beside_an_enclosure():
    """Test that the export writes no leader beside an enclosure.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    plain = [c.get("id") or "" for c in cells(fs, **kwargs)]
    assert [cid for cid in plain if cid.endswith("-lead")], "the fixture draws them"

    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    order = [c.get("id") or "" for c in cells(fs, **kwargs)]
    assert not [cid for cid in order if cid.endswith("-lead")]
    assert [cid for cid in order if cid.endswith("-box")]


def test_the_export_lays_down_no_plate_where_the_sheet_lays_none():
    """Test that the export lays down no plate where the sheet lays none.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(PLATELESS_SHEET)
    fs.stream_labels.enclosure = "diamond"
    bare = {n.name for n in numbers(fs, **kwargs) if n.words is None}
    assert bare == {PLATELESS}
    checked = 0
    for cell in cells(fs, **kwargs):
        if (cell.get("id") or "").endswith("-box"):
            checked += 1
            has = "labelBackgroundColor" in style(cell)
            assert has is (cell.get("value") not in bare), cell.get("value")
    assert checked


@pytest.mark.parametrize(
    "shape, any_turned",
    [("box", True), ("diamond", False)],
    ids=["box-turns-with-its-line", "diamond-stays-upright"],
)
def test_the_export_turns_exactly_the_numbers_the_sheet_turns(shape, any_turned):
    """Test that the export turns exactly the numbers the sheet turns.

    Parameters
    ----------
    shape : str
        Enclosure shape under test.
    any_turned : bool
        Expected presence of vertically oriented labels.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = shape
    turned = {n.name for n in numbers(fs, **kwargs) if n.vertical}
    assert bool(turned) is any_turned, (
        f"{shape}: the fixture turned {len(turned)} numbers, so this checks nothing"
    )
    checked = 0
    for cell in cells(fs, **kwargs):
        if (cell.get("id") or "").endswith("-box"):
            checked += 1
            assert (style(cell).get("horizontal") == "0") is (cell.get("value") in turned)
    assert checked
