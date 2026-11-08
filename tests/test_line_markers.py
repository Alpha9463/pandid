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
