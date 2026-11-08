"""Limits, tie-ins and spec breaks marked at a point on a line.

A battery limit or a limit of supply is drawn as ISO 10628-1:2014 5.6
and Figure 7 show it: a dashed boundary across the line with a diamond
at its top, the parties either side of the diamond. A tie-in is a
hexagon on the line holding its number, and a spec break a bar across
the line with a piping class either side, as in common practice. All
are drawn on the detail rung. "Up" is the top of the sheet beside a
horizontal run and its left beside a vertical one.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

from pandid.render.weights import LineWeight, M

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import LineMarker, Stream

#: Half-diagonal of a limit's diamond (ISO 10628-1 Figure 7).
DIAMOND_HALF = 1.5 * M
#: Height of the diamond's lower vertex above the line.
LIMIT_RISE = 2.5 * M
#: Reach of the boundary below the line.
LIMIT_DROP = 3.5 * M
#: Dash and gap of the boundary.
LIMIT_DASH = 3 * M
LIMIT_GAP = 1 * M
#: Height of a tie-in's hexagon, depth of its points and room beside its number.
TIE_IN_HEIGHT = 2 * M
TIE_IN_POINT = 0.75 * M
TIE_IN_PAD = 0.5 * M
#: Reach of a spec break's bar either side of the line.
SPEC_BAR = 1 * M
#: Gap between a marker's text and its diamond or bar, and between a
#: spec break's text and the line.
MARKER_TEXT_GAP = 0.5 * M
#: Font size of a marker's text.
MARKER_TYPE = 10.0

Point = tuple[float, float]
Box = tuple[float, float, float, float]


class Shape(NamedTuple):
    """A closed outline of a marker.

    Attributes
    ----------
    kind : str
        ``"diamond"`` or ``"hexagon"``.
    points : list[tuple[float, float]]
        Vertices in order.
    fill : bool
        Whether it is filled white, hiding the line under it.
    """

    kind: str
    points: list[Point]
    fill: bool


class Text(NamedTuple):
    """A line of a marker's text.

    Attributes
    ----------
    x, y : float
        Anchor point; ``y`` is the text's middle.
    anchor : str
        ``"start"``, ``"middle"`` or ``"end"``.
    text : str
        Text.
    """

    x: float
    y: float
    anchor: str
    text: str


class DrawnMarker(NamedTuple):
    """A marker as drawn on its line.

    Attributes
    ----------
    stream : Stream
        Segment it is drawn on.
    marker : LineMarker
        What is marked.
    line : Stream
        The line it was marked on.
    point : tuple[float, float]
        Its point on the line.
    start, end : tuple[float, float]
        The run it sits on, in flow order.
    before : float
        Length of the segment's drawn line before the run.
    strokes : list[tuple[tuple[float, float], tuple[float, float]]]
        Straight strokes.
    shapes : list[Shape]
        Closed outlines.
    texts : list[Text]
        Text beside it.
    box : tuple[float, float, float, float]
        Everything it draws, as left, top, right, bottom.
    """

    stream: "Stream"
    marker: "LineMarker"
    line: "Stream"
    point: Point
    start: Point
    end: Point
    before: float
    strokes: list[tuple[Point, Point]]
    shapes: list[Shape]
    texts: list[Text]
    box: Box


def text_box(text: Text) -> Box:
    """Return the box a marker's text takes.

    Parameters
    ----------
    text : Text
        Text item.

    Returns
    -------
    tuple[float, float, float, float]
        Left, top, right, bottom.
    """
    from pandid.render import furniture as F

    width = F.text_width(text.text, MARKER_TYPE)
    left = {"start": text.x, "middle": text.x - width / 2, "end": text.x - width}[text.anchor]
    return (left, text.y - MARKER_TYPE / 2, left + width, text.y + MARKER_TYPE / 2)


def _locate(line: "Stream", at: float):
    """Return where a fraction of a line's drawn length falls.

    Parameters
    ----------
    line : Stream
        Line, or a split line's handle.
    at : float
        Fraction of the drawn length of its segments.

    Returns
    -------
    tuple or None
        The segment, the point, the run's ends in flow order and the
        length of the segment's line before the run; ``None`` when a
        segment's end is not placed or the line has no length.
    """
    from pandid.route_geometry import stream_polyline

    segments = line._logical_segments or [line]
    if any(s.source.owner.frame is None or s.dest.owner.frame is None for s in segments):
        return None
    parts = [(s, stream_polyline(s)) for s in segments]
    total = sum(math.dist(a, b) for _, points in parts for a, b in zip(points, points[1:]))
    if total <= 0:
        return None
    left = at * total
    last = None
    for s, points in parts:
        before = 0.0
        for a, b in zip(points, points[1:]):
            n = math.dist(a, b)
            if n <= 0:
                continue
            last = (s, b, a, b, before)
            if left <= n:
                t = left / n
                return s, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), a, b, before
            left -= n
            before += n
    return last


def _draw(marker: "LineMarker", point: Point, start: Point, end: Point):
    """Return a marker's strokes, outlines and text at a point of a run.

    Parameters
    ----------
    marker : LineMarker
        What is marked.
    point : tuple[float, float]
        Its point.
    start, end : tuple[float, float]
        The run's ends in flow order.

    Returns
    -------
    tuple[list, list[Shape], list[Text]]
        Strokes, outlines and text.
    """
    px, py = point
    flat = abs(end[0] - start[0]) >= abs(end[1] - start[1])
    sign = (1.0 if end[0] >= start[0] else -1.0) if flat else (1.0 if end[1] >= start[1] else -1.0)

    def at(u: float, v: float) -> Point:
        """Return a point ``u`` downstream of the marker and ``v`` across, up negative."""
        return (px + sign * u, py + v) if flat else (px + v, py + sign * u)

    strokes: list[tuple[Point, Point]] = []
    shapes: list[Shape] = []
    texts: list[Text] = []
    if marker.kind in ("battery limit", "limit of supply"):
        v = -LIMIT_RISE
        while v < LIMIT_DROP:
            strokes.append((at(0, v), at(0, min(v + LIMIT_DASH, LIMIT_DROP))))
            v += LIMIT_DASH + LIMIT_GAP
        top, mid = -LIMIT_RISE - 2 * DIAMOND_HALF, -LIMIT_RISE - DIAMOND_HALF
        strokes.append((at(0, top), at(0, -LIMIT_RISE)))
        shapes.append(Shape("diamond", [at(0, top), at(DIAMOND_HALF, mid),
                                        at(0, -LIMIT_RISE), at(-DIAMOND_HALF, mid)], False))
        reach = DIAMOND_HALF + MARKER_TEXT_GAP
        for u, text in ((-reach, marker.before), (reach, marker.after)):
            if text:
                if flat:
                    x, y = at(u, mid)
                    texts.append(Text(x, y, "end" if sign * u < 0 else "start", text))
                else:
                    x, y = at(0, mid)
                    off = DIAMOND_HALF + MARKER_TEXT_GAP + MARKER_TYPE / 2
                    texts.append(Text(x, y + (off if sign * u > 0 else -off), "middle", text))
    elif marker.kind == "tie-in":
        from pandid.render import furniture as F

        number = marker.number or ""
        half = F.text_width(number, MARKER_TYPE) / 2 + TIE_IN_PAD + TIE_IN_POINT
        rise = TIE_IN_HEIGHT / 2
        shapes.append(Shape("hexagon", [
            (px - half, py), (px - half + TIE_IN_POINT, py - rise),
            (px + half - TIE_IN_POINT, py - rise), (px + half, py),
            (px + half - TIE_IN_POINT, py + rise), (px - half + TIE_IN_POINT, py + rise)],
            True))
        texts.append(Text(px, py, "middle", number))
    else:
        strokes.append((at(0, -SPEC_BAR), at(0, SPEC_BAR)))
        for u, text in ((-MARKER_TEXT_GAP, marker.before), (MARKER_TEXT_GAP, marker.after)):
            assert text is not None
            if flat:
                x, y = at(u, -MARKER_TEXT_GAP - MARKER_TYPE / 2)
                texts.append(Text(x, y, "end" if sign * u < 0 else "start", text))
            else:
                x, y = at(u + math.copysign(MARKER_TYPE / 2, u), -MARKER_TEXT_GAP)
                texts.append(Text(x, y, "end", text))
    return strokes, shapes, texts


def line_markers(fs: "Flowsheet") -> list[DrawnMarker]:
    """Return every marker on the sheet's lines as drawn.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[DrawnMarker]
        In stream order, then marking order.
    """
    out: list[DrawnMarker] = []
    for line in fs.streams:
        for marker in line.markers:
            found = _locate(line, marker.at)
            if found is None:
                continue
            s, point, start, end, before = found
            strokes, shapes, texts = _draw(marker, point, start, end)
            pad = LineWeight.DETAIL.width / 2
            xs = ([p[0] for st in strokes for p in st] + [p[0] for sh in shapes for p in sh.points]
                  + [b for t in texts for b in text_box(t)[0::2]])
            ys = ([p[1] for st in strokes for p in st] + [p[1] for sh in shapes for p in sh.points]
                  + [b for t in texts for b in text_box(t)[1::2]])
            box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
            out.append(DrawnMarker(s, marker, line, point, start, end, before,
                                   strokes, shapes, texts, box))
    return out
