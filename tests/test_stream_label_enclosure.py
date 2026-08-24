"""A stream label ruled inside a shape: ``fs.stream_labels.enclosure`` (#480).

**A drafting convention and not a standard.** A stream number in a diamond is
widespread in North American practice and in the chemical-engineering
textbooks, which is why courses and company drawing standards ask for it. No
clause of ISO 10628 or ISO 15519 prescribes a shape around a stream number, so
nothing here is asserted as conformance: what is asserted is that the option
draws what it says, that the default is untouched, and that the two backends
draw one drawing.

Four things carry the weight.

**The enclosure is what the search reserves.** A stream label sits *on* its
line and a shape is bigger than the words in it. If the placement search went
on reserving the words alone, the shape would be drawn over paper nothing had
accounted for -- so ``StreamNumber.box`` *is* the enclosure, and every check
here is against that one box.

**An enclosed label never leaves its run** (#480, decided by the owner). The
displacement path a bare label takes -- beside the line, or out to a leader --
is not taken, because a diamond off its run has no reading at all while one
too big for its run is merely crowded. Crowding is the drafter's to fix by
spacing the sheet, and it is reported so they can.

**No label paints out a line that is not its own**, at any setting. The shape
is an outline -- a filled one is a plate the size of a diamond and deletes
whatever run crosses it -- and the plate under the words is laid only where it
covers the labelled run alone. Where a run offers no such place, no plate is
laid: the number is written straight onto the sheet and the crossing run is
drawn through it. A drawing showing a connection that is not there is worse
than a crowded one, and ``validate()`` cannot see the difference because the
topology is untouched.

**One size for the whole sheet.** Measured over the longest label and given to
every label, the way the stream table rules its columns (#477).

``to_drawio()`` cannot rule a diamond round an edge label -- mxGraph has
``labelBorderColor`` and it draws a rectangle -- so an enclosed number leaves
the edge and becomes a vertex of its own. The geometry checks below are what
says the vertex lands where the sheet draws the shape, and reports what the
sheet reports.
"""

import importlib.util
import math
import pathlib
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
    hop_box,
    HOP_R,
    JUMP_DIRECTIONS,
    sheet_connections,
    stream_hops,
    stream_numbers,
)
from pandid.spec import SpecError, from_dict, to_dict

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every shape the option takes but ``"none"``, which is the default and is the
#: absence of one.
SHAPES = ("diamond", "circle", "box")

#: A sheet of the shipped corpus that draws vertical labels and leaders both.
#: The checks needing one are parametrised on it rather than on a fixture that
#: would have to be kept crowded on purpose.
CROWDED = "13_mineral_dewatering"

#: A sheet of the shipped corpus with runs that cross, so it draws line jumps.
#: ``CROWDED`` draws none: nothing on it crosses anything.
CROSSED = "11_ethanol_pid"


def _gallery():
    path = ROOT / "scripts" / "gallery.py"
    found = importlib.util.spec_from_file_location("_pandid_gallery_enclosure", path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


gallery = _gallery()
SHEETS = gallery.sheets()


def sheet(scheme: "str | Callable[[int], str]" = "S{n}") -> Flowsheet:
    """A small train, four runs, no crowding: the fixture for the checks about
    the shape rather than about the search."""
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
    """Where the sheet writes each label, the layout having been resolved.

    ``to_svg`` first, because the search reads the *drawn* geometry: a
    flowsheet not yet laid out has no frames to route between and no runs to
    write a number along.

    Seeded with the equipment tags, and given the sheet's joints, because both
    are ink the search dodges: asked without them this returns a placement the
    sheet does not draw, which is a check against a different drawing. It is
    ``tests/test_drawio.py``'s seed for the same reason.
    """
    fs.to_svg(**kwargs)
    joints = sheet_connections(kwargs.get("diagram"), kwargs.get("connections"))
    plates = list(_tag_pass(fs, default_registry, joints, "vertical").plates)
    return list(stream_numbers(fs, plates, joints, "vertical"))


def halo(name: str) -> "tuple[float, float]":
    """The plate the words alone are written on, which is what every shape is
    ruled around."""
    return len(name) * _HALO_CHAR + _HALO_PAD, _HALO_DEEP


def drawn(shape: str, box, ink: str = "black") -> str:
    """The one SVG element *shape* is drawn as, ruled around *box*.

    Spelled out here rather than taken from ``_enclosure_svg``, so the check is
    against what a reader's browser is handed and not against the function that
    writes it. *ink* is the label's own colour: an enclosure is part of the
    label, like the leader beside it, and a coloured line's number is ruled in
    the colour it is written in.

    ``fill="none"``, which is the whole of #480's second defect: a filled shape
    is an opaque plate the size of a diamond and it deletes whatever run
    crosses it. Only the words are written on paper.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pen = f'fill="none" stroke="{ink}" stroke-width="1" />'
    if shape == "diamond":
        return (
            f'<polygon points="{cx:.1f},{y0:.1f} {x1:.1f},{cy:.1f} '
            f'{cx:.1f},{y1:.1f} {x0:.1f},{cy:.1f}" {pen}'
        )
    if shape == "circle":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{(x1 - x0) / 2:.1f}" {pen}'
    return f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" {pen}'


def plate(box) -> str:
    """The opaque white rectangle a label's words are written on."""
    x0, y0, x1, y1 = box
    return (
        f'<rect x="{x0:.1f}" y="{y0:.1f}" '
        f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" fill="white" />'
    )


SVG_NS = "{http://www.w3.org/2000/svg}"

_NUMBER = r"-?\d+(?:\.\d+)?"
_COMMAND = re.compile(rf"([MLA])\s*((?:{_NUMBER}[,\s]*)+)")


def _streams_group(svg: str):
    root = ET.fromstring(svg)
    return next(g for g in root.iter(f"{SVG_NS}g") if g.get("id") == "streams")


def drawn_runs(svg: str) -> "list[tuple[list, float]]":
    """Every run the sheet **drew**, as straight segments and the weight they
    are stroked at, one entry per stream in ``fs.streams`` order.

    Read out of the ``d`` attribute, arcs chopped into chords, because a hop
    is the one piece of a line whose geometry is in no route: it is added by
    the drawing pass and the model's own ``_ink`` was blind to it for exactly
    that reason. A check fed by ``_ink`` cannot fail for that, however bad the
    drawing gets, so this one is fed by the document.

    A run is ``fill="none"`` with a ``stroke-width``; an arrowhead and a
    leader's head are filled paths and carry neither, so this picks out the
    runs and nothing else.
    """
    out = []
    for node in _streams_group(svg).iter(f"{SVG_NS}path"):
        width = node.get("stroke-width")
        if node.get("fill") != "none" or width is None:
            continue
        out.append((_segments(node.get("d") or ""), float(width)))
    return out


def drawn_plates(svg: str) -> "list[tuple[float, float, float, float]]":
    """Every opaque white rectangle the label pass laid down."""
    out = []
    for node in _streams_group(svg).iter(f"{SVG_NS}rect"):
        if node.get("fill") != "white":
            continue
        x, y = float(node.get("x") or 0), float(node.get("y") or 0)
        # Rounded to the decimal the file is written at, so a plate read back
        # out compares equal to the same plate reconstructed by `as_drawn`
        # rather than differing in the last bits of a float sum.
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
    """The rectangle the file carries, which is the one a reader sees: ``x``
    and ``width`` at one decimal, the way ``_enclosure_svg`` writes them."""
    x0, y0 = round(box[0], 1), round(box[1], 1)
    return (
        x0,
        y0,
        round(x0 + round(box[2] - box[0], 1), 4),
        round(y0 + round(box[3] - box[1], 1), 4),
    )


def _segments(d: str) -> "list[tuple[tuple[float, float], tuple[float, float]]]":
    """The path as straight pieces, every arc chopped fine enough that a chord
    stands in for it to well under a thousandth of a unit."""
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
    """Points along a circular SVG arc, centre worked out from the ends."""
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
    """Does a stroke of *width* along *segment* reach inside *rect*?

    The centreline against the rectangle grown by half the stroke, which is
    where the ink's outer edge lands. Liang--Barsky, strict at the edges for
    the reason ``_meets`` is.
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
    """*shape* filling *box*, as a polygon wound so its inside is to the left.

    Written out here rather than taken from the renderer, so what follows is a
    second opinion about the geometry and not the same opinion twice. The
    circle is not one of these: two circles share area exactly when their
    centres are closer than the two radii, and a polygon standing in for one
    would only blur that.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if shape == "diamond":
        return [(cx, y0), (x1, cy), (cx, y1), (x0, cy)]
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def shared(shape: str, box, other) -> float:
    """The area two polygon enclosures share, exactly.

    Sutherland--Hodgman -- one convex polygon clipped by each edge of the other
    -- and then the shoelace. Zero for two that merely touch, which is the
    convention :func:`_meets` already keeps for rectangles.
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
    """Do the two enclosures share any area? The answer worked out from the
    shapes themselves, which is what ``_shapes_meet`` has to agree with."""
    if shape != "circle":
        return shared(shape, box, other) > 0
    ax, ay = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    bx, by = (other[0] + other[2]) / 2, (other[1] + other[3]) / 2
    radii = (box[2] - box[0]) / 2 + (other[2] - other[0]) / 2
    return math.hypot(bx - ax, by - ay) < radii


def _left(a, b, p) -> float:
    """Which side of the directed line *a* -> *b* the point *p* is on."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _cut(p, q, a, b) -> "tuple[float, float]":
    """Where the segment *p* -> *q* crosses the line *a* -> *b*."""
    d1, d2 = _left(a, b, p), _left(a, b, q)
    t = d1 / (d1 - d2)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def inside(shape: str, box, point) -> bool:
    """Is *point* within the *shape* ruled around *box*?"""
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


# ---------------------------------------------------------------------------
# The default
# ---------------------------------------------------------------------------


def test_a_new_flowsheet_rules_nothing_around_its_labels():
    assert Flowsheet("x").stream_labels.enclosure == "none"


def test_stating_the_default_draws_the_sheet_the_default_draws():
    """The check that the option is *off* by default rather than defaulting to
    a shape that happens to look like nothing. The twenty-one goldens are the
    wider proof; this is the local one."""
    plain = sheet().to_svg()
    stated = sheet()
    stated.stream_labels.enclosure = "none"
    assert stated.to_svg() == plain


def test_the_export_is_unchanged_where_no_enclosure_is_asked_for():
    fs = sheet()
    plain = fs.to_drawio()
    fs.stream_labels.enclosure = "none"
    assert fs.to_drawio() == plain
    assert "-box" not in plain


# ---------------------------------------------------------------------------
# What is drawn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_the_shape_is_ruled_round_the_box_reserved_and_fills_none_of_it(shape):
    """The shape is drawn, and it is an outline: **one check, because either
    half alone is passed by a renderer that draws no enclosure at all.** A stub
    that ruled nothing would satisfy "no white the bare sheet does not lay" and
    a stub that filled its shapes would satisfy "one element per label", so
    neither is asked on its own.

    ``StreamNumber.box`` is the enclosure's box, so the paper the placement
    search reserved and the shape a reader sees are one rectangle: one element
    per label, in the shape asked for, at the reserved size and place.

    And it fills none of it, which is #480's second defect. A shape filled
    white is a plate the size of a diamond, and on ``14_tank_farm`` it took 8,5
    units out of ``MS-605``: a run that stopped and started again for no reason
    a reader could see, on a sheet whose validator is blind to it because the
    topology is untouched. So a sheet ruling shapes writes exactly as many
    opaque fills as the same sheet ruling nothing -- one per label and no more,
    however much larger the shapes are.
    """
    bare = sheet().to_svg()
    fs = sheet()
    fs.stream_labels.enclosure = shape
    ruled = fs.to_svg()
    placed = numbers(fs)
    assert placed

    assert ruled.count('fill="white"') == bare.count('fill="white"'), (
        f"{shape}: the sheet lays down white the bare sheet does not"
    )
    for number in placed:
        assert ruled.count(drawn(shape, number.box)) == 1, (
            f"{shape}: {number.name} is not drawn to fill the box reserved for it"
        )
        assert 'fill="none"' in drawn(shape, number.box)
        # This sheet is uncrowded, so every label keeps its plate...
        assert number.words is not None
        assert ruled.count(plate(number.words)) == 1
        # ...and the plate is strictly inside the shape, so the shape is not
        # the plate under another name.
        assert number.words != number.box


@pytest.mark.parametrize("shape", SHAPES)
def test_the_words_fit_inside_the_shape_ruled_around_them(shape):
    """Every corner of every label's own halo lands inside its shape.

    This is the check that ``enclosure_box`` circumscribes rather than merely
    enlarges: the minimum-area rhombus around a rectangle is twice it in each
    direction, and a diamond sized to the rectangle itself would cut both top
    corners off the number. It is also what lets a leader start inside the
    words' box and be buried by the shape.
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


# ---------------------------------------------------------------------------
# One size for the sheet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_one_size_rules_every_label_however_long_its_own_name_is(shape):
    """The decision #480 asked to be argued rather than assumed, in the form a
    reader would see it: ``1`` and ``1002`` on one sheet.

    Per-label sizing rules a 26-unit diamond around ``1`` and a 61,6-unit one
    around ``1002``, alternating down one process, and a row of shapes that
    vary reads as a drawing where the shape *means* something. Uniform pays the
    longest label's width at every label instead, which is the trade the stream
    table takes for its columns (#477).
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
    """A number reads bottom to top on a vertical run (ISO 15519-1 §7.2.5, and
    §5.1.5 for the reading direction), so the paper it takes is the transpose
    of the paper it takes flat -- and so is the shape around it. A circle
    transposes to itself, which is the check that this is measured rather than
    special-cased."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = shape
    placed = numbers(fs, **kwargs)
    flat = {
        (round(n.box[2] - n.box[0], 6), round(n.box[3] - n.box[1], 6))
        for n in placed
        if not n.vertical
    }
    turned = {
        (round(n.box[3] - n.box[1], 6), round(n.box[2] - n.box[0], 6)) for n in placed if n.vertical
    }
    assert flat and turned, "the fixture has to draw both, or this checks nothing"
    assert flat == turned


# ---------------------------------------------------------------------------
# An enclosed label never leaves its run
# ---------------------------------------------------------------------------


def _on_its_run(number) -> "tuple[bool, float, float]":
    """Is the label written *on* its own run, and if so how much run is there
    against how much label?"""
    (x1, y1), (x2, y2) = number.seg
    if number.vertical:
        axis, centre, span = (x1 + x2) / 2, number.x, abs(y2 - y1)
        reach = number.box[3] - number.box[1]
    else:
        axis, centre, span = (y1 + y2) / 2, number.y, abs(x2 - x1)
        reach = number.box[2] - number.box[0]
    return abs(centre - axis) <= 0.5, span, reach


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
@pytest.mark.parametrize("shape", SHAPES)
def test_an_enclosed_label_is_written_on_its_run_and_never_beside_it(shape, stem):
    """The owner's decision on #480, over the whole shipped corpus.

    > When the diagram is requested to use diamonds, then they have to be
    > located on the stream no matter what.

    A diamond's whole visual grammar is *the run passes through me*, so one
    written beside the line -- or out on a leader -- is a symbol a reader
    cannot identify at all, while one too big for its run is merely crowded
    and the author holds the lever that fixes it. So the displacement path is
    not taken: not on any of the twenty-one sheets, and not for any of the
    three shapes, including the ones whose bare labels are displaced.
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
    """The decision from the side that can fail: one train, a label that fits
    on its run bare and cannot fit in a diamond, and the diamond stays put.

    Without this the check above passes on a corpus where every shape happens
    to fit, and says nothing about the rule.
    """
    fs = sheet(scheme="STREAM-{n}00")
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
    """The rule is conditional on the option and is not a change to label
    placement in general: ruled with nothing, the same sheet still takes a
    label beside the line where the search finds no room on it. Without this
    the check above could pass by pinning every label on every sheet."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    assert any(not _on_its_run(n)[0] for n in numbers(fs, **kwargs)), (
        "the fixture has to displace a bare label, or the pair proves nothing"
    )


def test_the_crowded_sheet_keeps_its_leaders_bare_and_drops_them_when_ruled():
    """A leader stands in for adjacency (ISO 15519-1 §7.2.5) and there is
    nothing to stand in for once the line goes through the shape. The fixture
    is the sheet that draws leaders when nothing is ruled."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    assert [n for n in numbers(fs, **kwargs) if n.leader is not None], (
        "this sheet is the fixture because its bare labels draw leaders"
    )

    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    svg = fs.to_svg(**kwargs)
    assert not [n for n in numbers(fs, **kwargs) if n.leader is not None]
    # ...and the arrowhead a leader wears is gone from the file with it.
    assert svg.count("<path d=") == 0 or "leader" not in svg


def test_the_sheet_draws_a_bare_label_s_leader_over_its_halo():
    """Unchanged, and checked because the enclosure pass rewrote the lines
    that draw it: document order is paint order in SVG, and a halo has no
    outline for a tail to meet, so the leader goes on top and is seen whole.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    svg = fs.to_svg(**kwargs)
    plain = [n for n in numbers(fs, **kwargs) if n.leader is not None]
    assert plain
    for number in plain:
        (ax, ay), _ = number.leader
        assert svg.index(f'<line x1="{ax:.1f}" y1="{ay:.1f}"') > svg.index(plate(number.box))


# ---------------------------------------------------------------------------
# What a label paints out
# ---------------------------------------------------------------------------

#: The one label on the crowded sheet whose run has nowhere to put a plate:
#: ``S-403`` names a 14-unit segment with two other runs crossing it, and no
#: slide along 14 units moves a 43-unit plate off either of them. It is the
#: knot the second review rendered and looked at.
PLATELESS = "S-403"


def foreign(fs, name) -> list:
    """Every rectangle of drawn line on the sheet that is not *name*'s own."""
    return [line.box for line in _ink(fs, "vertical") if line.line != name]


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
@pytest.mark.parametrize("shape", ("none", *SHAPES))
def test_no_label_paints_out_a_line_that_is_not_its_own(shape, stem):
    """**The invariant the whole option rests on**, over the whole shipped
    corpus and at every setting, the default included.

    A stream label is written on an opaque plate, and a plate laid across a
    passing run draws that run stopping where it does not stop. It says two
    things that are not true -- that the line ends there, and that the gap is
    blank paper -- and ``validate()`` sees neither, because the topology is
    untouched. Ruling a shape is what takes away the search's room to dodge:
    an enclosed label may not leave its run (#480), and unfilling the shape
    was not enough on its own, since the plate under the words is opaque too.
    Thirteen of the 286 plates on this corpus landed across a crossing pipe
    that way -- thirteen 13-unit breaks in lines the sheet says are continuous
    -- where the same corpus lettered bare breaks none at all.

    So the plate is laid only where it covers the labelled run alone, and
    where the run offers no such place it is not laid at all
    (``StreamNumber.words`` is ``None``): the number goes straight onto the
    sheet and the crossing run is drawn through it in full. A number a passing
    run has to be read across is harder to read; a run with a piece missing is
    not there.

    **Measured off the rendered document and not off the model**, which is
    not a detail. Asked of ``_ink`` this check compared the placement against
    the very function the placement consults, so it agreed with the code by
    construction and could not fail however bad the drawing got -- and it did
    not fail while ``S-934``'s plate cut ``S-939``'s hop in two on
    ``21_alumina_refinery``, because ``_ink`` had no hop in it to compare
    against. The ``d`` attribute is the only thing on the sheet that can
    contradict ``_ink``, so it is what this reads: every stroke the sheet drew,
    arcs and all, against every plate the sheet laid.
    """
    fs, kwargs = gallery.flowsheet(stem)
    fs.stream_labels.enclosure = shape
    svg = fs.to_svg(**kwargs)
    placed = numbers(fs, **kwargs)
    assert placed
    runs = drawn_runs(svg)
    # One drawn run per stream, in order, which is what lets a stroke be
    # attributed to the line that owns it. Asserted rather than assumed: the
    # attribution is what "somebody else's ink" means here.
    assert len(runs) == len(fs.streams), f"{stem}: {len(runs)} runs drawn"
    # And every plate the model says it laid is a plate in the file, so
    # neither side of the comparison is the model's word for the other's.
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
    """Two runs that cross, so the sheet draws exactly one hop, and the sheet
    it drew.

    Pinned rather than laid out, because the fixture's whole job is the
    crossing: an auto-placed pair of trains is free to stop crossing the next
    time the layout improves, and then this would check nothing.
    """
    fs = Flowsheet("hop")
    west = fs.add(Feed("West")).pin(x=100, y=300)
    east = fs.add(Tank("T-101")).pin(x=500, y=270)
    north = fs.add(Feed("North")).pin(x=300, y=100)
    south = fs.add(Tank("T-102")).pin(x=270, y=480)
    fs.connect(west.outlet, east.inlet)  # S1, the horizontal one
    fs.connect(north.outlet, south.inlet)  # S2, the vertical one
    # Drawn here, because every question below is about the drawing and a
    # sheet that has not been laid out has no runs to cross.
    return fs, fs.to_svg()


def test_the_hop_the_sheet_draws_is_the_hop_the_search_is_told_about():
    """A hop is the one piece of a line whose geometry is in **no route**, so
    it is the one piece a model of the routes cannot see. ``_ink`` could not,
    and a plate half a unit clear of a run took a bite out of the arc standing
    over it.

    Both halves now come from :func:`stream_hops`, and this is what says so:
    the arc in the drawn ``d`` attribute and the rectangle the search reserves
    are checked against the *same* hop, including which side of the run it
    leaves -- which is the part a second implementation would get backwards,
    since it falls out of the sweep flag and the direction of travel rather
    than out of anything written down in the path.
    """
    fs, svg = crossing_sheet()
    hops = stream_hops(fs, "vertical")
    assert len(hops) == 1, "the fixture has to draw exactly one hop"
    hop = hops[0]

    # The drawing: the hopping run's own path, over the length the arc
    # occupies, standing off its axis by HOP_R and on the side the hop says.
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

    # The search: one piece of ink, the hopping run's own, reaching the same
    # way, and reaching paper the straight route does not reserve.
    reserved = [line for line in _ink(fs, "vertical") if line.kind == "hop"]
    assert len(reserved) == 1
    assert reserved[0].line == hop.line
    # Padded like the run it belongs to, whatever rung that run is drawn on:
    # a straight length of it is a box `2 * pad` across, the segment itself
    # having no width. Read off the ink rather than restated here, so a change
    # of pen weight moves the two together or fails on this line.
    own = [line for line in _ink(fs, "vertical") if line.line == hop.line and line.kind != "hop"]
    assert own, "the hopping run has to have a route, or this proves nothing"
    pad = min((line.x1 - line.x0) if hop.vertical else (line.y1 - line.y0) for line in own) / 2
    assert reserved[0].box == hop_box(hop, pad)
    # ...and reserving paper the hopping run's own **route** does not, which
    # is the whole of why a model of the routes could not see it. At the arc's
    # far point the only ink booked to `S2` is the hop; the straight ink there
    # is `S1`'s, and `S1`'s own label is entitled to paint over `S1`. That is
    # exactly how `S-934`'s plate came to cut `S-939`'s hop.
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
    """Which run owns the arc is the whole of the fix. ``S-934``'s plate cut
    ``S-939``'s hop, and ``S-934`` is the run being *crossed* -- so a hop
    booked to the crossed run, or to both, would have left the plate free to
    paint over it as its own ink."""
    fs, _svg = crossing_sheet()
    hop = stream_hops(fs, "vertical")[0]
    vertical = next(s for s in fs.streams if s.source.owner.name == "North")
    horizontal = next(s for s in fs.streams if s.source.owner.name == "West")
    assert hop.vertical and hop.line == vertical.name
    assert hop.line != horizontal.name
    # And under the other rule it is the other run's, which is what
    # `jump_direction` means.
    other = stream_hops(fs, "horizontal")
    assert len(other) == 1 and not other[0].vertical
    assert other[0].line == horizontal.name


@pytest.mark.parametrize("shape", SHAPES)
def test_a_label_with_nowhere_clear_for_its_plate_lays_none(shape):
    """The check from the side that can fail, and the case the corpus draws.

    Without it the sweep above passes on a corpus where every plate happens to
    find clear paper, and says nothing about what happens when none does.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
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
            # Nothing at all: not the plate it would have had, and not the
            # shape's box standing in for one either.
            assert plate(would_be) not in svg
            assert plate(number.box) not in svg
            # ...and the crossing runs it is written over are the reason.
            assert any(_meets(would_be, b) for b in foreign(fs, number.name))
        else:
            assert number.words == pytest.approx(would_be)
            assert svg.count(plate(number.words)) == 1


@pytest.mark.parametrize("shape", SHAPES)
def test_the_author_is_told_when_the_number_itself_is_written_across_a_run(shape):
    """A dropped plate is not silent, and it is not the same news as a crowded
    shape. "Your diamond has another pipe through it" is
    ``enclosure-over-line``; "your *number* has another pipe through it" is
    ``label-over-line``, which names the runs it is written across so the
    author knows which two to space apart.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = shape
    fs.to_svg(**kwargs)
    said = {i.message.split("'s ")[0]: i.message for i in findings(fs, {"label-over-line"})}
    assert set(said) == {PLATELESS}, "only the plateless label is written across"
    assert "is written across" in said[PLATELESS]
    # The runs it names are the ones drawn through it, and no others.
    crossed = next(n.crossed for n in numbers(fs, **kwargs) if n.name == PLATELESS)
    assert crossed
    for run in crossed:
        assert run in said[PLATELESS]
    # ...and the shape's own finding no longer says any of it twice.
    for issue in findings(fs, {"enclosure-over-line"}):
        assert "written on clear paper" not in issue.message
        assert "was dropped" not in issue.message


def no_clear_paper() -> Flowsheet:
    """A sheet with nowhere for one label's plate to go, drawn with **no
    enclosure at all**.

    Thirteen straight runs stacked fourteen apart fill every one of the seven
    bands either side of the middle ones, and fourteen verticals crossing them
    fill the run itself, so a twenty-four-character number in the middle of the
    bundle has no candidate anywhere that misses a line belonging to somebody
    else. Long names because the plate has to be wide enough that the pickets
    cannot be threaded between; that is the case ``docs/api.md`` already warns
    about, a sheet lettered with full line numbers.

    Pinned, so a better layout cannot quietly stop it being crowded and leave
    this checking nothing.
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
    """**The rule is unconditional, so the finding has to be.**

    Giving the plate up rather than paint out a neighbour's run is not
    something ``fs.stream_labels.enclosure`` turns on -- it is how every label
    on every sheet is drawn, the default included. For a while the reporting
    *was* conditional: ``label_findings`` returned early at ``"none"``, so the
    one setting nobody opts into was the one that could drop a plate and say
    nothing at all. A drawing that quietly stops doing what it did is the
    defect this whole branch is about, and it does not stop being one because
    the drawing got more honest rather than less.
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
    # ...and nothing about an enclosure, because none was ruled.
    assert not findings(fs, set(_LABEL_CODES) - {"label-over-line"})


def test_both_backends_say_it_at_the_default_too():
    """The export takes its placement from the same search, so it owes the
    author the same sentence -- including on the sheet that rules no shape,
    which is the one the parity check used not to cover."""
    fs = no_clear_paper()
    fs.to_svg(check=False)
    sheet_said = [(i.code, i.message) for i in findings(fs)]
    assert sheet_said, "the fixture has to report something"
    fs.to_drawio(check=False)
    assert [(i.code, i.message) for i in findings(fs)] == sheet_said


def test_a_bare_label_on_the_same_sheet_keeps_every_plate():
    """The rule is one rule at every setting, and the default still gets a
    plate under every number: on this corpus the search always finds clear
    paper for a label free to step off its line, which is why the twenty-one
    goldens do not move."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    placed = numbers(fs, **kwargs)
    assert placed
    assert all(n.words is not None for n in placed)


# ---------------------------------------------------------------------------
# The option itself
# ---------------------------------------------------------------------------


def test_a_shape_nobody_draws_is_refused_at_the_constructor():
    with pytest.raises(ValueError, match="enclosure must be one of"):
        StreamLabelOptions(enclosure="rhombus")  # type: ignore[arg-type]


def test_a_shape_nobody_draws_is_refused_at_the_render():
    """The field is a plain attribute, so the constructor is not the only door
    in and cannot be the only check. Assigning to it and rendering would
    otherwise draw the sheet with no enclosure at all and say nothing."""
    fs = sheet()
    fs.stream_labels.enclosure = "rhombus"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="enclosure must be one of"):
        fs.to_svg()
    with pytest.raises(ValueError, match="enclosure must be one of"):
        fs.to_drawio()


@pytest.mark.parametrize("draw", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("check", [True, False])
def test_a_refused_shape_leaves_the_sheet_exactly_as_it_found_it(draw, check):
    """The defect class of #433 and #451, in this option.

    The check lived in the renderer, and the renderer runs *after*
    ``_prepare_to_draw`` -- so a name outside the set raised from the far side
    of ``layout()`` and ``route()``, leaving the caller holding a sheet that
    had been numbered, laid out, routed, marked current and given this
    render's warnings, behind a call that had failed. A refused render has to
    leave the model as it was, or the caller who catches the error cannot tell
    what they still hold.

    Under ``check=False`` too: that keyword selects which findings about the
    *drawing* are looked for, and a shape that does not exist is not a
    finding, it is an argument no output answers to.
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
    """A misspelled ``jump_direction`` used to hop nothing and draw every
    crossing flat -- two lines shown meeting where they only cross, which is
    the same lie a severed hop tells and told the other way round. Nothing
    said so; the value was read against the two names it knows and anything
    else fell through the bottom.

    ``stream_hops`` refuses it at the point of reading, so no caller reaches
    the geometry with a name the sheet cannot draw. #492 is moving the refusal
    forward to ``_prepare_to_draw`` for the parameter as a whole; the two
    guards compose and neither replaces the other.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    allowed = _DRAWIO_KWARGS if draw == "to_drawio" else kwargs
    passed = {k: v for k, v in kwargs.items() if k in allowed}
    with pytest.raises(ValueError, match="Unknown jump_direction"):
        getattr(fs, draw)(jump_direction=spelling, **passed)


@pytest.mark.parametrize("spelling", list(JUMP_DIRECTIONS))
def test_both_spellings_the_sheet_draws_are_taken(spelling):
    """And the check is not simply refusing everything: each of the two names
    draws a sheet, and they draw *different* ones -- the hop changes hands.

    ``CROWDED`` is no use here: it has no crossing on it at all, so it would
    pass this with no hop drawn either way.
    """
    fs, kwargs = gallery.flowsheet(CROSSED)
    drawn = fs.to_svg(jump_direction=spelling, **kwargs)
    assert drawn
    hops = stream_hops(fs, spelling)
    assert hops and all(h.vertical is (spelling == "vertical") for h in hops)


# ---------------------------------------------------------------------------
# What the shape was drawn over
# ---------------------------------------------------------------------------


def findings(fs, codes=None) -> list:
    """The stream-label pass's own findings. Taken from ``_LABEL_CODES``
    rather than from a prefix, because one of the four is deliberately not
    named after an enclosure: a dropped plate is reported at every setting."""
    return [w for w in fs.warnings if w.code in _LABEL_CODES and (codes is None or w.code in codes)]


def test_a_bare_sheet_is_told_nothing_about_enclosures():
    """``"none"`` reserves the plate it always reserved and the search may
    still step off anything it would cover, so a finding here would be about a
    placement the sheet has drawn since long before this option existed."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.to_svg(**kwargs)
    assert not findings(fs)


def test_the_author_is_told_which_unit_a_diamond_was_drawn_over():
    """The decision #480 settled leaves the shape on the line whatever is
    under it, and hands the author the lever: space the plant. This is the
    list they need to use it -- ``13_mineral_dewatering`` carries four
    diamonds over equipment and naming them turns "look carefully at every
    diamond" into a list."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    over_units = findings(fs, {"enclosure-over-unit"})
    assert over_units
    for issue in over_units:
        assert issue.severity == "warning"
        assert " is drawn over " in issue.message
        # Names the label and what it landed on, both, or it is not a list.
        assert any(u.name in issue.message for u in fs.units)


def test_the_author_is_told_which_line_a_diamond_was_drawn_over():
    """The finding this file used to have no way of making: every check here
    measured a label's clearance on its *own* run and looked at no other pipe
    at all, so a diamond laid across ``CWR-312`` on ``11_ethanol_pid`` passed
    the lot.

    A warning and not an error, and that is settled by ``_enclosure_svg``: the
    shape is an outline, so the crossing line is still drawn and the drawing
    is crowded rather than false. Fill the shape again and this severity has
    to rise with it -- a sheet that draws a connection which is not there is
    not something to warn about.
    """
    fs, kwargs = gallery.flowsheet("11_ethanol_pid")
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    over_lines = findings(fs, {"enclosure-over-line"})
    assert over_lines
    named = {i.message.split("'s diamond")[0] for i in over_lines}
    assert "AE-309-100-80-SS" in named
    said = next(i for i in over_lines if i.message.startswith("AE-309-100-80-SS"))
    assert "AE-303-80-80-SS" in said.message
    for issue in over_lines:
        assert issue.severity == "warning"


def reported_pairs(fs, shape: str) -> set:
    """Every pair ``enclosure-over-label`` names, unordered."""
    out = set()
    for issue in findings(fs, {"enclosure-over-label"}):
        first, _, rest = issue.message.partition(f"'s {shape} crosses ")
        for other in rest.split("'s.")[0].split(", "):
            assert frozenset((first, other)) not in out, "reported both ways round"
            out.add(frozenset((first, other)))
    return out


def test_two_shapes_that_do_not_touch_are_not_called_a_collision():
    """The false finding: the corpus named seven crossing pairs of which six
    touched.

    The two rectangles are the pair, as literals, because the placement they
    came from has since moved on and the geometry is the point. Two diamonds
    222,8 by 26, centres five units apart across their runs and overlapping
    2,81 along them: each rhombus reaches into the other's *bounding box*, so
    asking the shape-against-rectangle test both ways round says yes twice --
    and over the whole of that 2,81 the two rhombi between them reach 0,328,
    so they cannot touch. A list the author is asked to work from earns
    nothing by being generous.
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
    """Both ways round, over the whole corpus: the shapes the sheet names as
    crossing share area, and no pair sharing area goes unnamed. Settled
    against a second implementation of the geometry -- exact polygon clipping
    for the two polygon shapes, two radii against a distance for the circle --
    so the renderer's separating-axis answer cannot be checked against itself.
    """
    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.stream_labels.enclosure = shape
        fs.to_svg(**kwargs)
        named = reported_pairs(fs, shape)
        placed = numbers(fs, **kwargs)
        for i, number in enumerate(placed):
            for other in placed[:i]:
                pair = frozenset((number.name, other.name))
                assert (pair in named) == crosses(shape, number.box, other.box), (
                    f"{stem}: {shape}s of {number.name} and {other.name} "
                    f"{'were' if pair in named else 'were not'} called crossed"
                )


def test_two_shapes_crossing_are_reported_once():
    """The pair is one finding, from the second of the two: the first was
    seeded as occupied before the second was placed, so the search preferred
    every clear alternative it had and this is what was left."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    fs.to_svg(**kwargs)
    assert reported_pairs(fs, "diamond")


def test_a_second_render_replaces_the_findings_rather_than_repeating_them():
    """A sheet spaced out and re-rendered must stop warning about the old
    one, which is the rule every other renderer finding follows."""
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
    """One placement, one account of it: the export asks the same function
    where every number goes, so it owes the author the same list.

    **Two assertions, and the second is not decoration.** Equality alone is
    satisfied by two empty lists, so a ``stream_numbers`` that returned
    nothing at all would pass a parity check on its own -- the classic way a
    "both backends agree" test agrees about nothing. The count is asserted
    here, in the same test, so the pair cannot be split up and half of it
    deleted as redundant. ``test_the_author_is_told_which_unit_a_diamond_was_``
    ``drawn_over`` and its neighbours are what say the list is *right*; this
    one says both backends have it and it is not empty.
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
    with pytest.raises(SpecError, match=r"stream_labels\.enclosure"):
        from_dict({"name": "x", "stream_labels": {"enclosure": "hexagon"}})


def test_an_unknown_key_under_stream_labels_is_refused():
    with pytest.raises(SpecError, match="stream_labels"):
        from_dict({"name": "x", "stream_labels": {"shape": "diamond"}})


def test_the_enclosure_comes_through_a_spec_round_trip():
    fs = sheet()
    fs.stream_labels.enclosure = "diamond"
    assert to_dict(fs)["stream_labels"] == {"enclosure": "diamond"}
    assert from_dict(to_dict(fs)).stream_labels.enclosure == "diamond"


def test_a_shape_nobody_draws_is_refused_on_the_way_out_to_a_spec():
    """``enclosure`` is a plain attribute, so it holds whatever it is assigned
    long after the dataclass checked it. A writer that lets that through
    writes a file its own reader refuses -- ``from_dict(to_dict(fs))`` raising
    on a flowsheet nobody edited -- and the author finds out when somebody
    else opens the file. Same sentence at both doors, and at the render.
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
    """``rhombus`` is what the geometry texts call a diamond and ``oval`` what a
    drawing office calls a circle, so an author who types one has not made a
    typing mistake -- they have used the other name for the thing they want.
    The set stays closed and neither spelling is accepted, so one sheet cannot
    say in one word what the next says in another; the message says which of
    the four they were reaching for.
    """
    with pytest.raises(ValueError, match=f"spells that one '{meant}'"):
        StreamLabelOptions(enclosure=typed)


def test_a_shape_nobody_has_a_name_for_is_refused_without_a_guess():
    with pytest.raises(ValueError) as raised:
        StreamLabelOptions(enclosure="hexagon")  # type: ignore[arg-type]
    assert "spells that one" not in str(raised.value)


def test_a_sheet_that_left_the_labels_alone_writes_the_spec_it_always_wrote():
    """Only what was changed, so a spec written before the option existed and
    one written after are the same file."""
    assert "stream_labels" not in to_dict(sheet())


# ---------------------------------------------------------------------------
# draw.io
# ---------------------------------------------------------------------------

_DRAWIO_KWARGS = ("diagram", "page_size", "border", "show_stream_table", "connections")

#: The built-in each shape is exported as. draw.io's rhombus is the
#: quadrilateral through its box's four edge-midpoints and its ellipse in a
#: square box is a circle, so both are the sheet's own geometry rather than an
#: approximation of it; ``rounded=0`` is the default vertex with square corners.
_EXPORTED = {"diamond": "rhombus", "circle": "ellipse", "box": "rounded"}


def cells(fs, **kwargs) -> "list[ET.Element]":
    text = fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
    return list(ET.fromstring(text).iter("mxCell"))


def style(cell) -> dict:
    out = {}
    for key in (cell.get("style") or "").split(";"):
        if key:
            name, _, value = key.partition("=")
            out[name] = value
    return out


@pytest.mark.parametrize("shape", SHAPES)
def test_the_export_draws_the_enclosure_the_sheet_draws(shape):
    """Not a bare label. The number leaves the edge and becomes a vertex, and
    the vertex is the sheet's own ``StreamNumber.box`` -- so the shape lands
    where the sheet puts it rather than centred on the run, and the two files
    are one drawing."""
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
        # Unfilled, for the reason the sheet's own shape is: a filled one
        # deletes the run that crosses it. The white the export lays down is
        # the label's plate and nothing else.
        assert style(cell)["fillColor"] == "none"
        assert style(cell)["labelBackgroundColor"] == "#ffffff"
        geometry = cell.find("mxGeometry")
        assert geometry is not None
        x0, y0, x1, y1 = placed[name].box
        got = tuple(float(geometry.get(k) or 0) for k in ("x", "y", "width", "height"))
        # Two decimals, which is what `_num` writes and all draw.io reads.
        assert got == pytest.approx((x0, y0, x1 - x0, y1 - y0), abs=0.01)
        # ...and the edge itself no longer carries the number, or the sheet
        # would show it twice.
        assert not found[cid[: -len("-box")]].get("value")
    assert seen == set(placed)


def test_the_export_writes_every_enclosure_after_every_run():
    """Document order is z-order in draw.io. An enclosure written beside its
    own edge is painted before whichever runs the hop order puts later, and one
    of those crossing it would be drawn straight through the opaque shape and
    the number in it -- the one thing the shape exists to prevent. The sheet
    has the same rule for the same reason: the numbers go on in a pass of their
    own, after the last pipe.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    order = [c.get("id") or "" for c in cells(fs, **kwargs)]
    edges = [i for i, cid in enumerate(order) if re.fullmatch(r"s\d+", cid)]
    boxes = [i for i, cid in enumerate(order) if cid.endswith("-box")]
    assert edges and boxes
    assert min(boxes) > max(edges)


def test_the_export_writes_no_leader_beside_an_enclosure():
    """An enclosed label never leaves its run, so the export has none of the
    leader cells the same sheet writes when nothing is ruled."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    plain = [c.get("id") or "" for c in cells(fs, **kwargs)]
    assert [cid for cid in plain if cid.endswith("-lead")], "the fixture draws them"

    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    order = [c.get("id") or "" for c in cells(fs, **kwargs)]
    assert not [cid for cid in order if cid.endswith("-lead")]
    assert [cid for cid in order if cid.endswith("-box")]


def test_the_export_lays_down_no_plate_where_the_sheet_lays_none():
    """Both files or neither. ``labelBackgroundColor`` is draw.io's spelling of
    the sheet's opaque plate, so the label the sheet writes with no plate is
    exported with no ``labelBackgroundColor`` -- otherwise the ``.drawio``
    deletes the run the ``.svg`` was careful to leave whole, and the two files
    stop being one drawing.
    """
    fs, kwargs = gallery.flowsheet(CROWDED)
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


def test_the_export_turns_a_number_on_a_vertical_run():
    """``horizontal=0`` on the vertex, which is the ordinary way to set text on
    end in draw.io and needs none of the argument the edge-label case does."""
    fs, kwargs = gallery.flowsheet(CROWDED)
    fs.stream_labels.enclosure = "diamond"
    turned = {n.name for n in numbers(fs, **kwargs) if n.vertical}
    assert turned, "the fixture has to draw one, or this checks nothing"
    checked = 0
    for cell in cells(fs, **kwargs):
        if (cell.get("id") or "").endswith("-box"):
            checked += 1
            assert (style(cell).get("horizontal") == "0") is (cell.get("value") in turned)
    assert checked
