"""Check the tracing, insulation and jacket marks drawn along a pipe."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import ControlValve, Feed, Flowsheet, Product
from pandid.document import notes
from pandid.layout.compact import covered
from pandid.render.pipe_marks import (
    INSULATION_COVER,
    INSULATION_PITCH,
    JACKET_HALF,
    MARK_LENGTH,
    TRACER_OFFSET,
    pipe_marks,
)
from pandid.render.weights import LineWeight
from pandid.route_geometry import stream_polyline
from pandid.streams import Stream


def _line(
    tracing: str | None = None,
    insulated: bool = False,
    jacketed: bool = False,
    numbered: bool = False,
) -> tuple[Flowsheet, Stream]:
    """Return a routed sheet with one straight 300 px line, treated as asked.

    With ``numbered``, the line carries line number 2-P-1001-A1.
    """
    fs = Flowsheet("Marked line")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    feed.pin(x=100, y=100)
    product.pin(x=400, y=100)
    line = fs.connect(
        feed.outlet,
        product.inlet,
        tracing=tracing,
        insulated=insulated,
        jacketed=jacketed,
        size=2 if numbered else None,
        service="P" if numbered else None,
        spec="A1" if numbered else None,
    )
    fs.route()
    return fs, line


def _strokes(fs: Flowsheet) -> list[tuple[float, float, float, float, float]]:
    """Return each mark stroke as ``(x1, y1, x2, y2, width)``, relative to the line."""
    mark = pipe_marks(fs)[0]
    y = stream_polyline(mark.stream)[0][1]
    return [(a[0], a[1] - y, b[0], b[1] - y, w.width) for a, b, w in mark.strokes]


def test_connect_takes_the_treatments_and_a_split_line_keeps_them() -> None:
    """Keep tracing, insulated and jacketed on every segment and in the spec."""
    fs, line = _line(tracing="steam", insulated=True)
    fs.add(ControlValve("FV-1"), on=line, at=0.5)
    line.jacketed = True
    treated = [(s.tracing, s.insulated, s.jacketed) for s in fs.streams]
    assert treated == [("steam", True, True)] * 2
    read = Flowsheet.from_dict(fs.to_dict())
    assert [(s.tracing, s.insulated, s.jacketed) for s in read.streams] == treated


@pytest.mark.parametrize(
    ("name", "value", "error", "words"),
    [
        ("insulated", 1, TypeError, "insulated=1 must be True or False"),
        ("tracing", " ", ValueError, "is blank"),
        ("tracing", True, TypeError, "must name the tracing medium"),
    ],
)
def test_a_treatment_is_checked(name: str, value: object, error: type, words: str) -> None:
    """Refuse a treatment of the wrong type, or a blank medium."""
    _, line = _line()
    with pytest.raises(error, match=re.escape(words)):
        setattr(line, name, value)


def test_a_signal_line_is_not_traced() -> None:
    """Refuse tracing on a signal line and say to set it on the pipe."""
    fs = Flowsheet("Signal")
    ft, fic = fs.add_instrument("FT", 101), fs.add_instrument("FIC", 101)
    with pytest.raises(ValueError, match="electric signal line is not traced"):
        fs.connect(ft, fic, tracing="electric")


def test_an_insulated_line_is_hatched_as_iso_10628_2_item_25_9() -> None:
    """Draw the band a cover either side of the pipe, hatched at 45 degrees."""
    fs, _ = _line(insulated=True)
    strokes = _strokes(fs)
    edges = [s for s in strokes if s[1] == s[3]]
    assert sorted({s[1] for s in edges}) == [-INSULATION_COVER, INSULATION_COVER]
    assert all(s[2] - s[0] == pytest.approx(MARK_LENGTH) for s in edges)
    hatch = [s for s in strokes if s[1] != s[3]]
    assert all(abs(s[2] - s[0]) == pytest.approx(abs(s[3] - s[1])) for s in hatch)
    crests = sorted(s[0] for s in hatch if s[1] == -INSULATION_COVER)
    assert [b - a for a, b in zip(crests, crests[1:])] == [INSULATION_PITCH] * (len(crests) - 1)
    assert {s[4] for s in strokes} == {LineWeight.DETAIL.width}


def test_a_traced_insulated_line_covers_its_tracer_as_item_25_8() -> None:
    """Draw the tracer a step off the pipe, inside a band that covers it."""
    fs, _ = _line(tracing="steam", insulated=True)
    strokes = _strokes(fs)
    levels = {s[1] for s in strokes if s[1] == s[3]}
    assert levels == {-TRACER_OFFSET - INSULATION_COVER, -TRACER_OFFSET, INSULATION_COVER}
    tracer = sorted((s[0], s[2]) for s in strokes if s[1] == s[3] == -TRACER_OFFSET)
    # A dash, two dots and a dash, filling the mark.
    assert len(tracer) == 4
    assert tracer[-1][1] - tracer[0][0] == pytest.approx(MARK_LENGTH)


def test_a_jacketed_line_is_boxed_on_the_main_flow_rung() -> None:
    """Draw the jacket as a box a half-jacket either side of the pipe."""
    fs, _ = _line(jacketed=True)
    strokes = _strokes(fs)
    assert len(strokes) == 4
    assert {round(s[1], 6) for s in strokes} | {round(s[3], 6) for s in strokes} == {
        -JACKET_HALF,
        JACKET_HALF,
    }
    assert {s[4] for s in strokes} == {LineWeight.MAIN_FLOW.width}


def test_the_svg_draws_every_stroke_and_the_line_number_keeps_off_them() -> None:
    """Draw each stroke in the line's group and keep the line number off the marks."""
    fs, _ = _line(tracing="steam", insulated=True, numbered=True)
    svg = fs.to_svg(diagram="p&id")
    mark = pipe_marks(fs)[0]
    for (x1, y1), (x2, y2), _w in mark.strokes:
        assert f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"' in svg
    assert fs.validate() == []
    root = ET.fromstring(svg)
    number = next(
        t for t in root.iter("{http://www.w3.org/2000/svg}text") if t.text == "2-P-1001-A1"
    )
    x = float(number.get("x", "nan"))
    assert not mark.box[0] <= x <= mark.box[2]


def test_draw_io_places_each_stroke_where_the_sheet_draws_it() -> None:
    """Resolve each draw.io stroke along its edge and match the sheet's stroke."""
    fs, line = _line(tracing="steam", insulated=True, jacketed=True)
    mark = pipe_marks(fs)[0]
    points = stream_polyline(line)
    root = ET.fromstring(fs.to_drawio())
    cells = [c for c in root.iter("mxCell") if (c.get("id") or "").startswith("s0m")]
    assert len(cells) == len(mark.strokes)
    total = math.dist(points[0], points[-1])
    centres = []
    for cell in cells:
        geo = cell.find("mxGeometry")
        offset = geo.find("mxPoint") if geo is not None else None
        assert geo is not None and offset is not None
        half = float(geo.get("width", "nan")) / 2
        along = (float(geo.get("x", "nan")) + 1) / 2 * total
        centres.append(
            (along, float(offset.get("x", "nan")) + half, float(offset.get("y", "nan")) + half)
        )
    for (along, dx, dy), ((ax, ay), (bx, by), _w) in zip(centres, mark.strokes):
        cx, cy = (ax + bx) / 2, (ay + by) / 2
        assert along + points[0][0] + dx == pytest.approx(cx, abs=0.05)
        assert points[0][1] + dy == pytest.approx(cy, abs=0.05)


def test_marks_drawn_over_a_placed_note_count_as_the_line() -> None:
    """Count a line whose marks meet a placed note as drawn over it."""
    fs, line = _line(insulated=True)
    mark = pipe_marks(fs)[0]
    note = fs.add_annotation(notes(["Drain"], position=(mark.box[0], mark.box[1] - 40)))
    assert ("line", line.name) not in covered(fs)
    note.position = (mark.box[0], mark.box[1] - 12)
    assert ("line", line.name) in covered(fs)


def test_marks_with_no_clear_run_are_not_drawn_and_are_reported() -> None:
    """Draw no jacket on a line too short for it, and say what to do."""
    fs = Flowsheet("Short")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    feed.pin(x=100, y=100)
    product.pin(x=160, y=100)
    fs.connect(feed.outlet, product.inlet, jacketed=True)
    svg = fs.to_svg(diagram="p&id")
    assert "<line" not in svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    assert [i.message for i in fs.validate() if i.code == "line-mark-crowded"] == [
        "S1 has no straight run 80 px long clear of units and other lines for its jacket "
        "mark, so it is not drawn. Lengthen a straight run of S1, or move the units and "
        "lines beside it apart"
    ]


def test_a_line_through_a_valve_station_carries_one_mark_clear_of_every_unit() -> None:
    """Draw one insulation mark for a line and its station, on a run clear of every unit."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box

    fs = Flowsheet("Steam")
    feed, product = fs.add(Feed("F")), fs.add(Product("P"))
    line = fs.connect(feed.outlet, product.inlet, insulated=True)
    fs.add_valve_station("CV-101", on=line)
    svg = fs.to_svg(diagram="p&id")
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    strokes = [
        tuple(map(float, m.groups()))
        for m in re.finditer(
            r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body
        )
    ]
    # One 25.9 mark: two band edges and three hatch strokes.
    assert len(strokes) == 5
    boxes = [unit_box(u, u.frame) for u in fs.units if u.frame is not None]
    for x1, y1, x2, y2 in strokes:
        assert not any(segment_crosses_box((x1, y1), (x2, y2), box) for box in boxes)
    assert [i for i in fs.validate() if i.code == "line-mark-crowded"] == []


def test_a_treated_line_with_an_unplaced_end_draws_no_mark() -> None:
    """Validate a sheet whose treated line ends at a unit with no place."""
    from pandid import Pump

    fs = Flowsheet("Unplaced")
    feed, pump, product = fs.add(Feed("F")), fs.add(Pump("P-1")), fs.add(Product("P"))
    fs.connect(feed.outlet, pump.suction, insulated=True)
    fs.connect(pump.discharge, product.inlet)
    fs.layout()
    pump.frame = None
    assert pipe_marks(fs) == []
    assert "line-mark-crowded" not in [i.code for i in fs.validate()]


# Guards: each mark is checked in the emitted SVG and draw.io against
# strokes stated here, for the straight line from (100, 100) to (400, 100).
# A mark is 50 long and centred on the run, from x=225 to x=275.

#: Expected strokes per treatment, as (x1, y1, x2, y2, width).
_EXPECTED = {
    "insulated": {
        (225.0, 90.0, 275.0, 90.0, 1.0),
        (225.0, 110.0, 275.0, 110.0, 1.0),
        (235.0, 90.0, 225.0, 100.0, 1.0),
        (255.0, 90.0, 235.0, 110.0, 1.0),
        (275.0, 90.0, 255.0, 110.0, 1.0),
    },
    "traced": {
        (225.0, 90.0, 240.0, 90.0, 1.0),
        (245.0, 90.0, 247.5, 90.0, 1.0),
        (252.5, 90.0, 255.0, 90.0, 1.0),
        (260.0, 90.0, 275.0, 90.0, 1.0),
    },
    "jacketed": {
        (225.0, 90.0, 275.0, 90.0, 2.0),
        (225.0, 110.0, 275.0, 110.0, 2.0),
        (225.0, 90.0, 225.0, 110.0, 2.0),
        (275.0, 90.0, 275.0, 110.0, 2.0),
    },
}
_EXPECTED["traced and insulated"] = {
    (225.0, 90.0, 240.0, 90.0, 1.0),
    (245.0, 90.0, 247.5, 90.0, 1.0),
    (252.5, 90.0, 255.0, 90.0, 1.0),
    (260.0, 90.0, 275.0, 90.0, 1.0),
    (225.0, 80.0, 275.0, 80.0, 1.0),
    (225.0, 110.0, 275.0, 110.0, 1.0),
    (235.0, 80.0, 225.0, 90.0, 1.0),
    (255.0, 80.0, 225.0, 110.0, 1.0),
    (275.0, 80.0, 245.0, 110.0, 1.0),
    (275.0, 100.0, 265.0, 110.0, 1.0),
}

_TREATED = {
    "insulated": {"insulated": True},
    "traced": {"tracing": "steam"},
    "jacketed": {"jacketed": True},
    "traced and insulated": {"tracing": "steam", "insulated": True},
}


def _key(x1: float, y1: float, x2: float, y2: float, width: float) -> tuple:
    """Return a stroke rounded and with its ends in order, for comparison."""
    a, b = sorted([(round(x1, 1), round(y1, 1)), (round(x2, 1), round(y2, 1))])
    return (*a, *b, round(width, 2))


def _svg_strokes(svg: str) -> set[tuple]:
    """Return every ``<line>`` in the SVG's streams group."""
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    found = re.finditer(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" '
        r'stroke="[^"]*" stroke-width="([\d.]+)"',
        body,
    )
    return {_key(*map(float, m.groups())) for m in found}


def _drawio_strokes(xml: str) -> set[tuple]:
    """Return every line child of the first edge, placed as mxGraph places it.

    A relative child's top-left sits at the point ``(x + 1) / 2`` along
    the edge plus its offset; a line shape runs across its box's middle,
    turned by ``rotation`` about the centre. The result is shifted so the
    edge starts at (100, 100).
    """
    root = ET.fromstring(xml)
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    edge = cells["s0"]
    style = dict(kv.split("=", 1) for kv in (edge.get("style") or "").split(";") if "=" in kv)
    ends = []
    for side, key in (("source", "exit"), ("target", "entry")):
        geo = cells[edge.get(side)].find("mxGeometry")
        assert geo is not None
        x, y, w, h = (float(geo.get(k, "0")) for k in ("x", "y", "width", "height"))
        ends.append((x + float(style[key + "X"]) * w, y + float(style[key + "Y"]) * h))
    (ax, ay), (bx, by) = ends
    assert ay == pytest.approx(by) and bx - ax == pytest.approx(300.0)
    out = set()
    for cell in cells.values():
        if cell.get("parent") != "s0" or "shape=line" not in (cell.get("style") or ""):
            continue
        geo = cell.find("mxGeometry")
        offset = geo.find("mxPoint") if geo is not None else None
        assert geo is not None and offset is not None
        side = float(geo.get("width", "nan"))
        cx = ax + (float(geo.get("x", "nan")) + 1) / 2 * 300.0 + float(offset.get("x", "nan"))
        cy = ay + float(offset.get("y", "nan"))
        cx, cy = cx + side / 2 - ax + 100, cy + side / 2 - ay + 100
        mark = dict(kv.split("=", 1) for kv in (cell.get("style") or "").split(";") if "=" in kv)
        turn = math.radians(float(mark["rotation"]))
        dx, dy = math.cos(turn) * side / 2, math.sin(turn) * side / 2
        out.add(_key(cx - dx, cy - dy, cx + dx, cy + dy, float(mark["strokeWidth"])))
    return out


@pytest.mark.parametrize("treated", sorted(_TREATED))
def test_each_mark_is_drawn_where_iso_10628_2_puts_it(treated: str) -> None:
    """Draw each mark's strokes, and only those, in SVG and in draw.io."""
    fs, _ = _line(**_TREATED[treated])
    expected = {_key(*stroke) for stroke in _EXPECTED[treated]}
    assert _svg_strokes(fs.to_svg(diagram="p&id")) == expected
    assert _drawio_strokes(fs.to_drawio()) == expected


def test_the_drawing_bounds_take_in_marks_that_reach_past_the_units() -> None:
    """Bound the drawing round a traced and insulated band that stands above its units."""
    from pandid.portgeom import unit_box
    from pandid.render.svg import drawing_bounds

    fs, _ = _line(tracing="steam", insulated=True)
    (mark,) = pipe_marks(fs)
    top = min(unit_box(u, u.frame)[1] for u in fs.units if u.frame is not None)
    assert mark.box[1] < top, "the fixture stopped reaching past the units"
    x0, y0, x1, y1 = drawing_bounds(fs)
    assert x0 <= mark.box[0] and y0 <= mark.box[1]
    assert x1 >= mark.box[2] and y1 >= mark.box[3]
