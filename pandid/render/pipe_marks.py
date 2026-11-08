"""Tracing, insulation and jacket marks drawn along a pipe.

The marks are ISO 10628-2:2012 items 25.6 (traced), 25.7 (jacketed),
25.8 (traced and insulated) and 25.9 (insulated). ISO 10628-2 does not
say how often a line carries its mark, so a line carries it once: its
marks stand together on one straight run of the line, its own segments'
runs longest first and then those of its valve stations' pipework,
where they keep clear of every unit, other line, tap line, pneumatic
hatch, placed annotation and other line's marks. A line with no such run
carries none. The jacket is a pipe and is drawn on the main-flow rung;
tracer and insulation are drawn on the detail rung.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

from pandid.render.weights import LineWeight, M

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

#: Length of one mark along its line.
MARK_LENGTH = 5 * M
#: Gap between a jacket mark and the mark beside it.
MARK_GAP = 1 * M
#: Room kept between the marks and either end of their straight run.
MARK_END_CLEAR = 1.5 * M
#: Distance of a tracer from its pipe (25.6, 25.8).
TRACER_OFFSET = 1 * M
#: A tracer's long dash, the gaps of its pattern and its two dots.
TRACER_DASH = 1.5 * M
TRACER_GAP = 0.5 * M
TRACER_DOT = 0.25 * M
#: Reach of insulation past the pipe, and past a tracer under it (25.8, 25.9).
INSULATION_COVER = 1 * M
#: Pitch of the insulation hatch along the line.
INSULATION_PITCH = 2 * M
#: Reach of a jacket either side of its pipe (25.7).
JACKET_HALF = 1 * M

#: Room a mark keeps from what it must not meet, past its own extent.
_CLEARANCE = LineWeight.MAIN_FLOW.width


class Stroke(NamedTuple):
    """One straight stroke of a mark.

    Attributes
    ----------
    a, b : tuple[float, float]
        Ends, in drawing coordinates.
    weight : LineWeight
        Line-weight class.
    """

    a: tuple[float, float]
    b: tuple[float, float]
    weight: LineWeight


class PipeMark(NamedTuple):
    """The marks one line carries, on one straight run of one segment.

    Attributes
    ----------
    stream : Stream
        Segment the run belongs to.
    kinds : tuple[tuple[str, ...], ...]
        Marks in order along the run: ``("jacket",)``, then
        ``("tracer",)``, ``("insulation",)`` or ``("tracer",
        "insulation")``.
    start, end : tuple[float, float]
        The run's ends, in flow order.
    before : float
        Length of the segment's drawn line before the run.
    strokes : list[Stroke]
        Every stroke of the marks.
    box : tuple[float, float, float, float]
        The area the marks cover, as left, top, right, bottom.
    """

    stream: "Stream"
    kinds: tuple[tuple[str, ...], ...]
    start: tuple[float, float]
    end: tuple[float, float]
    before: float
    strokes: list[Stroke]
    box: tuple[float, float, float, float]


def _parts(s: "Stream") -> list[tuple[str, ...]]:
    """Return a treated segment's marks in order along its run.

    Parameters
    ----------
    s : Stream
        Segment.

    Returns
    -------
    list[tuple[str, ...]]
        One entry per mark: ``("jacket",)``, then ``("tracer",)``,
        ``("insulation",)`` or ``("tracer", "insulation")``.
    """
    out: list[tuple[str, ...]] = [("jacket",)] if s.jacketed else []
    cover = tuple(k for k, on in (("tracer", s.tracing is not None),
                                  ("insulation", s.insulated)) if on)
    return out + [cover] if cover else out


def _reach(part: tuple[str, ...]) -> tuple[float, float]:
    """Return how far a mark reaches either side of its pipe.

    Parameters
    ----------
    part : tuple[str, ...]
        One mark from :func:`_parts`.

    Returns
    -------
    tuple[float, float]
        Reach on the tracer's side, as a negative offset, and on the
        other.
    """
    if part == ("jacket",):
        return -JACKET_HALF, JACKET_HALF
    if part == ("tracer",):
        return -TRACER_OFFSET, 0.0
    top = -(TRACER_OFFSET + INSULATION_COVER) if "tracer" in part else -INSULATION_COVER
    return top, INSULATION_COVER


def _tracer(u0: float, v: float) -> list[tuple[float, float, float, float]]:
    """Return a tracer's dashes and dots from ``u0`` along a run.

    Parameters
    ----------
    u0 : float
        Start along the run.
    v : float
        Offset across it.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Strokes as ``(u, v, u, v)``.
    """
    pattern = (TRACER_DASH, TRACER_GAP, TRACER_DOT, TRACER_GAP, TRACER_DOT, TRACER_GAP)
    out = []
    u, k = 0.0, 0
    while u < MARK_LENGTH - 1e-9:
        step = pattern[k % len(pattern)]
        if k % 2 == 0:
            out.append((u0 + u, v, u0 + min(u + step, MARK_LENGTH), v))
        u, k = u + step, k + 1
    return out


def _hatch(u0: float, top: float, bottom: float) -> list[tuple[float, float, float, float]]:
    """Return an insulation band's edges and its hatch from ``u0``.

    Each hatch stroke falls at 45 degrees from the top edge, its tops
    ``INSULATION_PITCH`` apart from half a pitch in, clipped to the mark.

    Parameters
    ----------
    u0 : float
        Start along the run.
    top, bottom : float
        Offsets of the band's edges across the run.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Strokes as ``(u, v, u, v)``.
    """
    end, depth = u0 + MARK_LENGTH, bottom - top
    out = [(u0, top, end, top), (u0, bottom, end, bottom)]
    crest = u0 + INSULATION_PITCH / 2
    while crest - depth < end:
        low = max(0.0, (crest - end) / depth)
        high = min(1.0, (crest - u0) / depth)
        if low < high:
            out.append((crest - depth * low, top + depth * low,
                        crest - depth * high, top + depth * high))
        crest += INSULATION_PITCH
    return out


def _local_strokes(parts: list[tuple[str, ...]]) -> list[tuple[float, float, float, float, LineWeight]]:
    """Return the strokes of a line's marks from the start of their span.

    Parameters
    ----------
    parts : list[tuple[str, ...]]
        Marks from :func:`_parts`.

    Returns
    -------
    list[tuple[float, float, float, float, LineWeight]]
        Strokes as ``(u, v, u, v, weight)``; ``u`` runs along the run and
        ``v`` across it, negative on the tracer's side.
    """
    out = []
    u0 = 0.0
    for part in parts:
        if part == ("jacket",):
            end = u0 + MARK_LENGTH
            box = [(u0, -JACKET_HALF, end, -JACKET_HALF), (u0, JACKET_HALF, end, JACKET_HALF),
                   (u0, -JACKET_HALF, u0, JACKET_HALF), (end, -JACKET_HALF, end, JACKET_HALF)]
            out += [(*stroke, LineWeight.MAIN_FLOW) for stroke in box]
        else:
            if "tracer" in part:
                out += [(*stroke, LineWeight.DETAIL) for stroke in _tracer(u0, -TRACER_OFFSET)]
            if "insulation" in part:
                top, bottom = _reach(part)
                out += [(*stroke, LineWeight.DETAIL) for stroke in _hatch(u0, top, bottom)]
        u0 += MARK_LENGTH + MARK_GAP
    return out


def _runs(points: list[tuple[float, float]]) -> list[tuple[int, float]]:
    """Return a polyline's horizontal and vertical runs, longest first.

    Parameters
    ----------
    points : list[tuple[float, float]]
        Drawn line.

    Returns
    -------
    list[tuple[int, float]]
        Segment index and length of each run.
    """
    out = []
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(points, points[1:])):
        if abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6:
            out.append((i, abs(x2 - x1) + abs(y2 - y1)))
    return sorted(out, key=lambda run: -run[1])


def has_marks(fs: "Flowsheet") -> bool:
    """Return whether any line on the sheet is traced, insulated or jacketed.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    bool
        True if a line carries a mark.
    """
    return any(s.tracing is not None or s.insulated or s.jacketed for s in fs.streams)


def pipe_marks(fs: "Flowsheet") -> list[PipeMark]:
    """Return the marks of every traced, insulated or jacketed line with room.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[PipeMark]
        One entry per line that has a clear run for its marks, in stream
        order.
    """
    return _place(fs)[0]


def crowded_marks(fs: "Flowsheet") -> list[tuple["Stream", tuple[tuple[str, ...], ...]]]:
    """Return each treated line that has no clear run for its marks.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[tuple[Stream, tuple[tuple[str, ...], ...]]]
        The line, or its handle, and the marks it would carry, as
        :attr:`PipeMark.kinds`.
    """
    return _place(fs)[1]


def _place(fs: "Flowsheet") -> tuple[list[PipeMark], list]:
    """Place the marks of every treated line that is drawn.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    tuple[list[PipeMark], list]
        The marks placed, and each line with none, as :func:`crowded_marks`.
    """
    if not has_marks(fs):
        return [], []
    from pandid.layout.compact import placed
    from pandid.layout.conflicts import boxes_overlap, segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import hatch_boxes, tap_lines, tap_route
    from pandid.route_geometry import stream_polyline

    drawn = {id(s): stream_polyline(s) for s in fs.streams
             if s.source.owner.frame is not None and s.dest.owner.frame is not None}
    # Each line's own segments, then its stations' pipework.
    piped = {id(p) for s in fs.streams for p in s._logical_pipework}
    lines: dict[int, tuple] = {}
    for s in fs.streams:
        if s._logical_root is None and id(s) not in piped:
            lines[id(s)] = (s, [*(s._logical_segments or [s])], [*s._logical_pipework])
    owner = {id(p): handle for handle, own, pipework in lines.values() for p in own + pipework}
    groups: dict[tuple, list] = {}
    for s in fs.streams:
        parts = _parts(s)
        if parts:
            handle = owner.get(id(s), s)
            groups.setdefault((id(handle), tuple(parts)), [handle]).append(s)
    if not groups:
        return [], []

    blocks = [unit_box(u, u.frame) for u in fs.units if u.frame is not None]
    blocks += hatch_boxes(fs) + placed(fs)
    # Every segment a mark must not meet: tap lines', then each line's.
    taps = [tap_route(*tap) for tap in tap_lines(fs)]
    reach: list[tuple[Stream | None, int, tuple[float, float], tuple[float, float]]] = [
        (None, -1, a, b) for route in taps for a, b in zip(route, route[1:])]
    reach += [(s, i, a, b) for s in fs.streams if id(s) in drawn
              for i, (a, b) in enumerate(zip(drawn[id(s)], drawn[id(s)][1:]))]
    out: list[PipeMark] = []
    crowded: list = []

    def build(parts, points, i, u0) -> "tuple[list[Stroke], tuple, tuple, tuple, float]":
        """Return the marks' strokes and box with their span from ``u0`` on a run.

        Parameters
        ----------
        parts : list[tuple[str, ...]]
            Marks from :func:`_parts`.
        points : list[tuple[float, float]]
            Its drawn line.
        i : int
            Run's segment index.
        u0 : float
            Start of the span from the run's low end.

        Returns
        -------
        tuple
            Strokes, box, run start, run end and the length before the run.
        """
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        flat = abs(y1 - y2) < 1e-6
        low = min(x1, x2) if flat else min(y1, y2)

        def at(u: float, v: float) -> tuple[float, float]:
            """Return a point ``u`` along the run from its low end and ``v`` across."""
            return (low + u, y1 + v) if flat else (x1 + v, low + u)

        strokes = [Stroke(at(u0 + ua, va), at(u0 + ub, vb), w)
                   for ua, va, ub, vb, w in _local_strokes(parts)]
        extents = [_reach(p) for p in parts]
        span = len(parts) * MARK_LENGTH + (len(parts) - 1) * MARK_GAP
        lo, hi = min(r[0] for r in extents), max(r[1] for r in extents)
        (ax, ay), (bx, by) = at(u0, lo), at(u0 + span, hi)
        box = (min(ax, bx) - _CLEARANCE, min(ay, by) - _CLEARANCE,
               max(ax, bx) + _CLEARANCE, max(ay, by) + _CLEARANCE)
        before = sum(math.hypot(qx - px, qy - py)
                     for (px, py), (qx, qy) in zip(points[:i], points[1:i + 1]))
        return strokes, box, (x1, y1), (x2, y2), before

    for (_handle, parts_key), (handle, *streams) in groups.items():
        parts = list(parts_key)
        span = len(parts) * MARK_LENGTH + (len(parts) - 1) * MARK_GAP
        boxes = blocks + [m.box for m in out]
        _, own, pipework = lines.get(id(handle), (handle, [handle], []))
        candidates = []
        for tier in (own, pipework):
            runs = [(s, drawn[id(s)], i, n) for s in tier
                    if any(s is t for t in streams) and id(s) in drawn
                    for i, n in _runs(drawn[id(s)])]
            candidates += sorted(runs, key=lambda run: -run[3])
        chosen = None
        for s, points, i, n in candidates:
            room = n - 2 * MARK_END_CLEAR - span
            if room < 0:
                continue
            steps = int(room / 2 // M)
            for k in sorted(range(-steps, steps + 1), key=abs):
                strokes, box, start, end, before = build(parts, points, i,
                                                         (n - span) / 2 + k * M)
                if (not any(boxes_overlap(box, b) for b in boxes)
                        and not any(segment_crosses_box(a, b, box) for t, j, a, b in reach
                                    if not (t is s and j == i))):
                    chosen = PipeMark(s, parts_key, start, end, before, strokes, box)
                    break
            if chosen is not None:
                break
        if chosen is not None:
            out.append(chosen)
        elif any(id(s) in drawn for s in streams):
            crowded.append((handle, parts_key))
    return out, crowded
