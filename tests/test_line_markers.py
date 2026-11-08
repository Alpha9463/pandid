"""Check limits, tie-ins and spec breaks marked at a point on a line."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import ControlValve, Feed, Flowsheet, Product
from pandid.document import notes
from pandid.layout.compact import covered
from pandid.render.line_markers import (
    DIAMOND_HALF,
    LIMIT_DROP,
    LIMIT_RISE,
    SPEC_BAR,
    TIE_IN_HEIGHT,
    line_markers,
    text_box,
)
from pandid.render.furniture import text_width
from pandid.streams import Stream


def _line(numbered: bool = False) -> tuple[Flowsheet, Stream]:
    """Return a sheet with one straight 300 px line from x=100 to x=400 at y=100.

    With ``numbered``, the line carries line number 2-P-1001-A1.
    """
    fs = Flowsheet("Marked line")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    feed.pin(x=100, y=100)
    product.pin(x=400, y=100)
    line = fs.connect(
        feed.outlet,
        product.inlet,
        size=2 if numbered else None,
        service="P" if numbered else None,
        spec="A1" if numbered else None,
    )
    return fs, line


@pytest.mark.parametrize(
    ("kind", "texts", "error", "words"),
    [
        ("bogus", {}, ValueError, "'bogus' is not a line marker"),
        ("tie-in", {}, ValueError, 'needs number=: mark("tie-in", at=..., number="TI-101")'),
        ("spec break", {"before": "A1A"}, ValueError, "needs after="),
        ("tie-in", {"number": "TI-1", "before": "A"}, ValueError, "takes number=, not before="),
        ("battery limit", {"before": 3}, TypeError, "before=3 must be text"),
        ("battery limit", {"after": " "}, ValueError, "after=' ' is blank"),
    ],
)
def test_a_marker_is_checked(kind: str, texts: dict, error: type, words: str) -> None:
    """Refuse an unknown marker, a missing or blank text, or one the kind does not take."""
    _, line = _line()
    with pytest.raises(error, match=re.escape(words)):
        line.mark(kind, at=0.5, **texts)


@pytest.mark.parametrize("at", [0.0, 1.0, -0.2])
def test_a_marker_lies_strictly_inside_its_line(at: float) -> None:
    """Refuse a marker at either end of its line or off it."""
    _, line = _line()
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        line.mark("battery limit", at=at)


def test_a_signal_line_takes_no_marker() -> None:
    """Refuse a marker on a signal line and say to mark the pipe."""
    fs = Flowsheet("Signal")
    signal = fs.connect(fs.add_instrument("FT", 101), fs.add_instrument("FIC", 101))
    with pytest.raises(ValueError, match="electric signal line takes no tie-in"):
        signal.mark("tie-in", at=0.5, number="TI-1")


def test_markers_on_a_split_line_round_trip_through_the_spec() -> None:
    """Keep a split line's markers on its handle through to_dict() and back."""
    fs, line = _line()
    line.mark("battery limit", at=0.25, before="ISBL", after="OSBL")
    line.mark("tie-in", at=0.75, number="TI-101")
    fs.add(ControlValve("FV-1"), on=line, at=0.5)
    read = Flowsheet.from_dict(fs.to_dict())
    assert [s.markers for s in read.streams] == [line.markers, []]


def test_a_battery_limit_is_drawn_as_iso_10628_1_figure_7() -> None:
    """Draw a dashed boundary across the line, a diamond on top and the parties beside it."""
    fs, line = _line()
    line.mark("battery limit", at=0.5, before="ISBL", after="OSBL")
    fs.route()
    (drawn,) = line_markers(fs)
    assert drawn.point == pytest.approx((250.0, 100.0))
    (diamond,) = drawn.shapes
    ys = [y for _, y in diamond.points]
    assert (min(ys), max(ys)) == pytest.approx(
        (100 - LIMIT_RISE - 2 * DIAMOND_HALF, 100 - LIMIT_RISE)
    )
    assert sorted({x for x, _ in diamond.points}) == pytest.approx(
        [250 - DIAMOND_HALF, 250, 250 + DIAMOND_HALF]
    )
    boundary = [s for s in drawn.strokes if s[0][1] >= 100 - LIMIT_RISE]
    assert all(a[0] == b[0] == 250 for a, b in boundary)
    assert max(b[1] for _, b in boundary) == pytest.approx(100 + LIMIT_DROP)
    assert any(a[1] < 100 < b[1] for a, b in boundary), "the boundary crosses the line"
    texts = {t.text: t for t in drawn.texts}
    assert (
        text_box(texts["ISBL"])[2]
        < 250 - DIAMOND_HALF
        < 250 + DIAMOND_HALF
        < text_box(texts["OSBL"])[0]
    )


def test_a_tie_in_is_a_hexagon_on_the_line_that_hides_it() -> None:
    """Draw the tie-in number in a white hexagon centred on the line, over the line."""
    fs, line = _line()
    line.mark("tie-in", at=0.5, number="TI-101")
    svg = fs.to_svg(diagram="p&id")
    (drawn,) = line_markers(fs)
    (hexagon,) = drawn.shapes
    ys = [y for _, y in hexagon.points]
    assert (min(ys), max(ys)) == pytest.approx((100 - TIE_IN_HEIGHT / 2, 100 + TIE_IN_HEIGHT / 2))
    assert hexagon.fill and len(hexagon.points) == 6
    assert [t.text for t in drawn.texts] == ["TI-101"]
    body = svg.split('<g id="streams">', 1)[1]
    assert body.index('fill="white"') > body.index("<path")


def test_a_spec_break_sits_across_the_line_with_a_class_either_side() -> None:
    """Draw a bar across the line, the upstream class before it and the downstream after."""
    fs, line = _line()
    line.mark("spec break", at=0.5, before="A1A", after="B2B")
    fs.route()
    (drawn,) = line_markers(fs)
    assert drawn.strokes == [((250.0, 100 - SPEC_BAR), (250.0, 100 + SPEC_BAR))]
    before, after = (text_box(t) for t in drawn.texts)
    assert before[2] < 250 < after[0] and before[3] < 100 and after[3] < 100


def test_a_marker_on_a_split_line_falls_on_the_segment_at_its_fraction() -> None:
    """Find a marker's point along the whole run of a split line."""
    fs, line = _line()
    fs.add(ControlValve("FV-1"), on=line, at=0.5)
    line.mark("tie-in", at=0.9, number="TI-1")
    fs.route()
    (drawn,) = line_markers(fs)
    assert drawn.stream is fs.streams[1] and drawn.line is line
    assert drawn.point[0] > 300


def test_draw_io_places_the_marker_where_the_sheet_draws_it() -> None:
    """Resolve each draw.io child of the edge and match the sheet's marker."""
    fs, line = _line()
    line.mark("battery limit", at=0.5, before="ISBL", after="OSBL")
    fs.route()
    (drawn,) = line_markers(fs)
    root = ET.fromstring(fs.to_drawio())
    cells = [c for c in root.iter("mxCell") if (c.get("id") or "").startswith("s0k0")]
    assert len(cells) == len(drawn.strokes) + len(drawn.shapes) + len(drawn.texts)
    total = math.dist(drawn.start, drawn.end)
    for cell in cells:
        geo = cell.find("mxGeometry")
        offset = geo.find("mxPoint") if geo is not None else None
        assert geo is not None and offset is not None
        along = (float(geo.get("x", "nan")) + 1) / 2 * total
        assert drawn.start[0] + along == pytest.approx(drawn.point[0])
    diamond = next(c for c in cells if "rhombus" in (c.get("style") or ""))
    geo = diamond.find("mxGeometry")
    assert geo is not None
    assert float(geo.get("width", "nan")) == pytest.approx(2 * DIAMOND_HALF)
    words = sorted(c.get("value") or "" for c in cells if (c.get("style") or "").startswith("text"))
    assert words == ["ISBL", "OSBL"]


def test_the_line_number_keeps_off_a_marker() -> None:
    """Keep the line number off a tie-in at the middle of the line."""
    fs, line = _line(numbered=True)
    line.mark("tie-in", at=0.5, number="TI-101")
    root = ET.fromstring(fs.to_svg(diagram="p&id"))
    (drawn,) = line_markers(fs)
    number = next(
        t for t in root.iter("{http://www.w3.org/2000/svg}text") if t.text == "2-P-1001-A1"
    )
    assert not drawn.box[0] <= float(number.get("x", "nan")) <= drawn.box[2]
    assert fs.validate() == []


def test_a_marker_drawn_over_a_placed_note_counts_as_its_line() -> None:
    """Count a line whose marker meets a placed note as drawn over it."""
    fs, line = _line()
    line.mark("battery limit", at=0.5, before="ISBL", after="OSBL")
    fs.route()
    (drawn,) = line_markers(fs)
    note = fs.add_annotation(notes(["Drain"], position=(drawn.box[0], drawn.box[1] - 60)))
    assert ("line", line.name) not in covered(fs)
    note.position = (drawn.box[0], drawn.box[1] - 20)
    assert ("line", line.name) in covered(fs)


def test_a_marker_drawn_over_a_unit_is_reported_with_the_call_that_moves_it() -> None:
    """Report a tie-in drawn over its line's feed, naming the call that marks it elsewhere."""
    fs, line = _line()
    line.mark("tie-in", at=0.02, number="TI-1")
    fs.route()
    assert [i.message for i in fs.validate() if i.code == "line-marker-crowded"] == [
        "the tie-in at=0.02 on S1 is drawn over F. Mark it elsewhere along S1: drop it from "
        "S1.markers and call S1.mark('tie-in', at=..., number='TI-1')"
    ]


# Guards: each marker is checked in the emitted SVG and draw.io against
# geometry stated here, for the straight line from (100, 100) to (400, 100)
# marked at its middle, (250, 100).

#: Half the tie-in hexagon's width: half its number, then a 5 pad and a 7.5 point.
_HEX = text_width("TI-101", 10) / 2 + 12.5

_GUARDED = {
    "battery limit": (
        {"before": "ISBL", "after": "OSBL"},
        {(250.0, 75.0, 250.0, 105.0), (250.0, 115.0, 250.0, 135.0), (250.0, 45.0, 250.0, 75.0)},
        {("diamond", ((250.0, 45.0), (265.0, 60.0), (250.0, 75.0), (235.0, 60.0)))},
        {("end", 230.0, 60.0, "ISBL"), ("start", 270.0, 60.0, "OSBL")},
    ),
    "limit of supply": (
        {"before": "VENDOR", "after": "OWNER"},
        {(250.0, 75.0, 250.0, 105.0), (250.0, 115.0, 250.0, 135.0), (250.0, 45.0, 250.0, 75.0)},
        {("diamond", ((250.0, 45.0), (265.0, 60.0), (250.0, 75.0), (235.0, 60.0)))},
        {("end", 230.0, 60.0, "VENDOR"), ("start", 270.0, 60.0, "OWNER")},
    ),
    "tie-in": (
        {"number": "TI-101"},
        set(),
        {
            (
                "hexagon",
                (
                    (250 - _HEX, 100.0),
                    (250 - _HEX + 7.5, 90.0),
                    (250 + _HEX - 7.5, 90.0),
                    (250 + _HEX, 100.0),
                    (250 + _HEX - 7.5, 110.0),
                    (250 - _HEX + 7.5, 110.0),
                ),
            )
        },
        {("middle", 250.0, 100.0, "TI-101")},
    ),
    "spec break": (
        {"before": "A1A", "after": "B2B"},
        {(250.0, 90.0, 250.0, 110.0)},
        set(),
        {("end", 245.0, 90.0, "A1A"), ("start", 255.0, 90.0, "B2B")},
    ),
}


def _r(value: float) -> float:
    """Return a coordinate rounded for comparison."""
    return round(value, 1)


def _segment(x1: float, y1: float, x2: float, y2: float) -> tuple:
    """Return a stroke rounded, its ends in order."""
    a, b = sorted([(_r(x1), _r(y1)), (_r(x2), _r(y2))])
    return (*a, *b)


def _shape(kind: str, points) -> tuple:
    """Return an outline rounded, as its kind and sorted vertices."""
    return kind, tuple(sorted((_r(x), _r(y)) for x, y in points))


def _expected(kind: str) -> tuple[set, set, set]:
    """Return a marker's stated strokes, outlines and text, rounded."""
    _, lines, shapes, texts = _GUARDED[kind]
    return (
        {_segment(*line) for line in lines},
        {_shape(k, points) for k, points in shapes},
        {(anchor, _r(x), _r(y), text) for anchor, x, y, text in texts},
    )


def _svg_marker(svg: str) -> tuple[set, set, set]:
    """Return the strokes, outlines and text in the SVG's streams group."""
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    lines = {
        _segment(*map(float, m.groups()))
        for m in re.finditer(
            r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body
        )
    }
    shapes = set()
    for m in re.finditer(r'<polygon points="([^"]+)" fill="(\w+)"', body):
        points = [tuple(map(float, p.split(","))) for p in m.group(1).split()]
        shapes.add(_shape("diamond" if len(points) == 4 else "hexagon", points))
        assert m.group(2) == ("none" if len(points) == 4 else "white")
    texts = {
        (m.group(3), _r(float(m.group(1))), _r(float(m.group(2))), m.group(4))
        for m in re.finditer(
            r'<text x="([-\d.]+)" y="([-\d.]+)" font-family="sans-serif" font-size="10" '
            r'text-anchor="(\w+)" dominant-baseline="middle" fill="[^"]*">([^<]*)</text>',
            body,
        )
    }
    return lines, shapes, texts


def _drawio_marker(xml: str) -> tuple[set, set, set]:
    """Return the marker children of the first edge, placed as mxGraph places them.

    A relative child's top-left sits at the point ``(x + 1) / 2`` along the
    edge plus its offset. A line shape runs across its box's middle, turned
    by ``rotation``; a rhombus joins its sides' midpoints; a hexagon cuts
    ``size`` off each end. The result is shifted so the edge starts at
    (100, 100).
    """
    root = ET.fromstring(xml)
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    edge = cells["s0"]

    def style(cell: ET.Element) -> dict[str, str]:
        """Return a cell's style as a mapping."""
        return dict(kv.split("=", 1) for kv in (cell.get("style") or "").split(";") if "=" in kv)

    ends = []
    for side, key in (("source", "exit"), ("target", "entry")):
        geo = cells[edge.get(side)].find("mxGeometry")
        assert geo is not None
        x, y, w, h = (float(geo.get(k, "0")) for k in ("x", "y", "width", "height"))
        ends.append((x + float(style(edge)[key + "X"]) * w, y + float(style(edge)[key + "Y"]) * h))
    (ax, ay), (bx, by) = ends
    assert ay == pytest.approx(by) and bx - ax == pytest.approx(300.0)
    lines, shapes, texts = set(), set(), set()
    for cell in cells.values():
        if cell.get("parent") != "s0":
            continue
        geo = cell.find("mxGeometry")
        offset = geo.find("mxPoint") if geo is not None else None
        assert geo is not None and offset is not None
        w, h = float(geo.get("width", "nan")), float(geo.get("height", "nan"))
        x0 = 100 + (float(geo.get("x", "nan")) + 1) / 2 * 300.0 + float(offset.get("x", "nan"))
        y0 = 100 + float(offset.get("y", "nan"))
        cx, cy, kind = x0 + w / 2, y0 + h / 2, style(cell)
        if kind.get("shape") == "line":
            turn = math.radians(float(kind["rotation"]))
            dx, dy = math.cos(turn) * w / 2, math.sin(turn) * w / 2
            lines.add(_segment(cx - dx, cy - dy, cx + dx, cy + dy))
        elif kind.get("shape") == "rhombus":
            assert kind["fillColor"] == "none"
            shapes.add(_shape("diamond", [(cx, y0), (x0 + w, cy), (cx, y0 + h), (x0, cy)]))
        elif kind.get("shape") == "hexagon":
            assert kind["fillColor"] == "#ffffff"
            k = float(kind["size"])
            hexagon = [(x0, cy), (x0 + k, y0), (x0 + w - k, y0), (x0 + w, cy),
                       (x0 + w - k, y0 + h), (x0 + k, y0 + h)]  # fmt: skip
            shapes.add(_shape("hexagon", hexagon))
        else:
            align = kind["align"]
            anchor, x = {"left": ("start", x0), "center": ("middle", cx), "right": ("end", x0 + w)}[
                align
            ]
            texts.add((anchor, _r(x), _r(cy), cell.get("value") or ""))
    return lines, shapes, texts


@pytest.mark.parametrize("kind", sorted(_GUARDED))
def test_each_marker_is_drawn_as_stated_in_svg_and_drawio(kind: str) -> None:
    """Draw each marker's strokes, outlines and text, and only those, in both backends."""
    fs, line = _line()
    line.mark(kind, at=0.5, **_GUARDED[kind][0])
    expected = _expected(kind)
    lines, shapes, texts = _svg_marker(fs.to_svg(diagram="p&id"))
    # Leave out the line's own number, S1.
    assert (lines, shapes, {t for t in texts if t[3] != line.name}) == expected
    assert _drawio_marker(fs.to_drawio()) == expected


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Return whether two boxes, as left, top, right, bottom, share area."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_a_docked_note_keeps_off_a_limit_above_its_line() -> None:
    """Dock a top-left notes box clear of a limit's diamond and parties, in SVG and draw.io."""
    fs = Flowsheet("Docked")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    line = fs.connect(feed.outlet, product.inlet)
    line.mark("battery limit", at=0.5, before="VENDOR", after="OWNER")
    fs.add_annotation(
        notes(["Tie in to the owner's header", "Hydrotest by vendor"], align="top-left")
    )
    svg = fs.to_svg(diagram="p&id")
    found = re.search(
        r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" '
        r'stroke="black" stroke-width="1.5"/>\s*<text[^>]*>NOTES<',
        svg,
    )
    assert found is not None
    x, y, w, h = map(float, found.groups())
    sheet_note = (x, y, x + w, y + h)
    points = re.search(r'<polygon points="([^"]+)" fill="none"', svg)
    assert points is not None
    xs, ys = zip(*(map(float, p.split(",")) for p in points.group(1).split()))
    assert not _overlap(sheet_note, (min(xs), min(ys), max(xs), max(ys)))
    for word in ("VENDOR", "OWNER"):
        at = re.search(rf'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>{word}<', svg)
        assert at is not None
        assert float(at.group(2)) - 5 > sheet_note[3]

    root = ET.fromstring(fs.to_drawio())
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    note = next(c for c in cells.values() if c.get("value") == "NOTES")
    geo = note.find("mxGeometry")
    assert geo is not None
    nx, ny, nw, nh = (float(geo.get(k, "nan")) for k in ("x", "y", "width", "height"))
    edge, source = cells["s0"], cells[cells["s0"].get("source")]
    style = dict(kv.split("=", 1) for kv in (edge.get("style") or "").split(";") if "=" in kv)
    src = source.find("mxGeometry")
    assert src is not None
    ex = float(src.get("x", "nan")) + float(style["exitX"]) * float(src.get("width", "nan"))
    ey = float(src.get("y", "nan")) + float(style["exitY"]) * float(src.get("height", "nan"))
    (drawn,) = line_markers(fs)
    total = math.dist(drawn.start, drawn.end)
    for cell in cells.values():
        if cell.get("parent") != "s0":
            continue
        child = cell.find("mxGeometry")
        offset = child.find("mxPoint") if child is not None else None
        assert child is not None and offset is not None
        left = ex + (float(child.get("x", "nan")) + 1) / 2 * total + float(offset.get("x", "nan"))
        top = ey + float(offset.get("y", "nan"))
        box = (
            left,
            top,
            left + float(child.get("width", "nan")),
            top + float(child.get("height", "nan")),
        )
        assert not _overlap((nx, ny, nx + nw, ny + nh), box), cell.get("id")


def test_an_insulation_mark_keeps_clear_of_a_tie_in_on_its_line() -> None:
    """Draw a line's insulation mark off the tie-in marked at its middle."""
    from pandid.layout.conflicts import segment_crosses_box

    fs = Flowsheet("Marked and treated")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    feed.pin(x=100, y=100)
    product.pin(x=400, y=100)
    line = fs.connect(feed.outlet, product.inlet, insulated=True)
    line.mark("tie-in", at=0.5, number="TI-101")
    svg = fs.to_svg(diagram="p&id")
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    hexagon = re.search(r'<polygon points="([^"]+)" fill="white"', body)
    assert hexagon is not None
    xs, ys = zip(*(map(float, p.split(",")) for p in hexagon.group(1).split()))
    box = (min(xs), min(ys), max(xs), max(ys))
    strokes = [
        tuple(map(float, m.groups()))
        for m in re.finditer(
            r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body
        )
    ]
    # The 25.9 mark: two band edges and three hatch strokes.
    assert len(strokes) == 5
    assert not any(segment_crosses_box((a, b), (c, d), box) for a, b, c, d in strokes)
    assert [i.code for i in fs.validate() if "crowded" in i.code] == []


def _tee_advice(**treated: object) -> tuple[str, dict[str, tuple[float, float]]]:
    """Return the advice refusing a tee on a marked line, and where its markers are drawn."""
    from pandid.units import Tee

    fs = Flowsheet("Tee")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    feed.pin(x=100, y=100)
    product.pin(x=500, y=100)
    line = fs.connect(feed.outlet, product.inlet)
    for key, value in treated.items():
        setattr(line, key, value)
    line.mark("tie-in", at=0.75, number="TI-101")
    line.mark("battery limit", at=0.2, before="VENDOR", after="OWNER")
    fs.route()
    drawn = {m.marker.kind: m.point for m in line_markers(fs)}
    with pytest.raises(ValueError) as refused:
        fs.add(Tee("T"), on=line, at=0.375)
    return str(refused.value), drawn


def test_following_the_tee_advice_keeps_each_marker_where_it_was_drawn() -> None:
    """Draw the line through the tee as advised, re-marked as advised, and find each marker unmoved."""
    from pandid.units import Tee

    advice, drawn = _tee_advice()
    fs = Flowsheet("Tee")
    feed, product, drain = fs.add(Feed("F")), fs.add(Product("P")), fs.add(Product("D"))
    tee = fs.add(Tee("T"))
    feed.pin(x=100, y=100)
    product.pin(x=500, y=100)
    # The tee's 12 px box centred where on= at=0.375 splits the 400 px line,
    # at (250, 100), its ports either side on the line.
    tee.pin(x=244, y=94)
    drain.pin(x=250, y=250)
    streams = {
        "fs.connect(F.outlet, T.inlet)": fs.connect(feed.outlet, tee.inlet),
        "fs.connect(T.outlet, P.inlet)": fs.connect(tee.outlet, product.inlet),
    }
    fs.connect(tee.branch, drain.inlet)
    advised = re.findall(r"on (fs\.connect\([^)]*\)), ((?:\.mark\([^)]*\)(?: and )?)+)", advice)
    assert {side for side, _ in advised} == set(streams)
    for side, calls in advised:
        for call in re.findall(r"\.mark\([^)]*\)", calls):
            eval("stream" + call, {"stream": streams[side]})  # noqa: S307
    fs.route()
    moved = {m.marker.kind: m.point for m in line_markers(fs)}
    assert moved.keys() == drawn.keys()
    for kind, point in drawn.items():
        assert moved[kind] == pytest.approx(point, abs=0.05)


def test_the_tee_advice_gives_both_connections_the_lines_treatments() -> None:
    """Name the tracing and insulation both connections through the tee take."""
    advice, _ = _tee_advice(tracing="steam", insulated=True)
    assert "Give both connections through T tracing='steam', insulated=True." in advice


def _through_tee(centre: float) -> tuple[Flowsheet, dict[str, Stream]]:
    """Return the line of :func:`_line` drawn through a tee centred at x=centre.

    The streams are keyed by the connect() call the tee advice names.
    """
    from pandid.units import Tee

    fs = Flowsheet("Tee")
    feed, product, drain = fs.add(Feed("F")), fs.add(Product("P")), fs.add(Product("D"))
    tee = fs.add(Tee("T"))
    feed.pin(x=100, y=100)
    product.pin(x=400, y=100)
    # The tee's box is 12 px, its ports either side of its centre on the line.
    tee.pin(x=centre - 6, y=94)
    drain.pin(x=centre, y=250)
    streams = {
        "fs.connect(F.outlet, T.inlet)": fs.connect(feed.outlet, tee.inlet),
        "fs.connect(T.outlet, P.inlet)": fs.connect(tee.outlet, product.inlet),
    }
    fs.connect(tee.branch, drain.inlet)
    return fs, streams


def test_a_marker_within_the_tees_span_is_given_a_choice_of_side() -> None:
    """Name both sides for a spec break where the tee goes, and draw each choice beside it."""
    from pandid.units import Tee

    fs, line = _line()
    line.mark("spec break", at=0.5, before="A1A", after="B2B")
    fs.route()
    with pytest.raises(ValueError) as refused:
        fs.add(Tee("T"), on=line, at=0.5)
    advice = str(refused.value)
    assert "The spec break at=0.5 on S1 falls within T's span" in advice
    options = re.findall(r"on the stream (fs\.connect\([^)]*\)) returns, (\.mark\([^)]*\))", advice)
    assert [side for side, _ in options] == [
        "fs.connect(F.outlet, T.inlet)",
        "fs.connect(T.outlet, P.inlet)",
    ]
    # The tee's ports at x=244 and x=256; each choice a module clear of them.
    for (side, call), want in zip(options, (234.0, 266.0)):
        sheet, streams = _through_tee(250.0)
        eval("stream" + call, {"stream": streams[side]})  # noqa: S307
        sheet.route()
        (drawn,) = line_markers(sheet)
        assert drawn.point == pytest.approx((want, 100.0), abs=0.05)


def test_a_marker_past_a_valve_is_marked_again_where_it_was_drawn() -> None:
    """Re-mark a spec break on the segment past a valve, through the tee, where it was."""
    from pandid.units import Tee

    fs, line = _line()
    valve = fs.add(ControlValve("FV"), on=line, at=0.4)
    outlet = valve.outlet.stream
    assert outlet is not None
    outlet.mark("spec break", at=0.5, before="A1A", after="B2B")
    fs.route()
    (drawn,) = line_markers(fs)
    with pytest.raises(ValueError) as refused:
        fs.add(Tee("T"), on=line, at=0.7)
    advice = str(refused.value)
    assert "put back what S1 carries, each where it sits now: FV" in advice
    # On the 300 px line, FV's centre is at x=220 and the tee's at x=310.
    sheet, streams = _through_tee(310.0)
    # FV where it sits now: 120 px along the 204 px run up to the tee's inlet.
    sheet.add(ControlValve("FV"), on=streams["fs.connect(F.outlet, T.inlet)"], at=120 / 204)
    advised = re.findall(r"on (fs\.connect\([^)]*\)), ((?:\.mark\([^)]*\)(?: and )?)+)", advice)
    assert advised, advice
    for side, calls in advised:
        for call in re.findall(r"\.mark\([^)]*\)", calls):
            eval("stream" + call, {"stream": streams[side]})  # noqa: S307
    sheet.route()
    (moved,) = line_markers(sheet)
    assert moved.point == pytest.approx(drawn.point, abs=0.05)
