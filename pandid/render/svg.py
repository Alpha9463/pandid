"""Render a flowsheet as SVG.

The module-level functions place labels, crossing marks, flags and sheet
furniture for both this renderer and the draw.io export.
"""

from typing import NamedTuple, TYPE_CHECKING
import math
import re
from datetime import datetime
from functools import lru_cache

from pandid.layout.conflicts import boxes_overlap
from pandid.package import INSET as _PACKAGE_INSET, frame as package_frame
from pandid.portgeom import tag_width, unit_box
from pandid.render import furniture as F
from pandid.render.escape import escaped, fmt, ident
from pandid.render.pipe_marks import pipe_marks
from pandid.render.symbols import (ARROWHEAD, _STROKE, _TAG_TYPE, closed_marking,
                                   default_registry, fail_marking, wears_arrowhead)
from pandid.render.weights import LineWeight, M
from pandid.route_geometry import stream_polyline
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.document import TitleBlock
    from pandid.flowsheet import Flowsheet

# A symbol's own lettering, such as the "M" in a motor operator.
_SYMBOL_TEXT = re.compile(
    r'<text\b[^>]*?\bx="(-?[\d.]+)"[^>]*?\by="(-?[\d.]+)"[^>]*?>.*?</text>', re.S)
# Balloon variants with a location bar across the middle that the tag
# text must clear.
_BARRED_BALLOONS = {"panel", "aux", "shared"}
# Balloon variants drawn as a diamond (ISA-5.1 Table 5.1.1 column B).
_DIAMOND_BALLOONS = {"sis", "logic", "interlock"}
# Balloon variants that stand for a field device.
_FIELD_BALLOONS = {"default"}

#: Values ``label_pos`` accepts: the four faces and ``"center"``.
LABEL_POSITIONS = ("top", "bottom", "right", "left", "center")

# --- line weights -----------------------------------------------------

_SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                "capillary": "3,3"}

# Dash for a tap line that is a signal, not impulse tubing.
_TAP_DASH = "5,4"

#: Dash of a package's boundary frame: ISO 128-20 line type 10 at
#: the detail weight (ISO 15519-1 6.1, Table 1).
PACKAGE_DASH = ",".join(f"{k * LineWeight.DETAIL.width:g}" for k in (12, 3, 0.5, 3))

# Rise of a package's tag above its frame's upper-left corner.
_PACKAGE_RISE = 4.0


#: Radius of a crossing mark: half the run an arc or gap takes out.
#: ``_HOP_CLEARANCE`` is the paper an arc leaves over a main flow run.
_HOP_CLEARANCE = 3.0
HOP_R = _HOP_CLEARANCE + LineWeight.MAIN_FLOW.width

#: Marks for a crossing of two unconnected runs, one style per sheet:
#:
#: * ``"gap"`` -- a break ``2 * HOP_R`` long (ISO 10628-1 5.3.4).
#: * ``"arc"`` -- a semicircular bridge.
#: * ``"plain"`` -- both lines continuous; junctions carry the mark.
CROSSING_STYLES = ("arc", "gap", "plain")

#: Crossing style used when none is given.
CROSSING_STYLE_DEFAULT = "gap"

# --- stream-label placement -------------------------------------------
# Pipe a label written on the pipe leaves showing at each end.
_LABEL_CLEAR = 20.0
# Gap from the pipe to the near edge of a label written beside it.
_LABEL_GAP = 4.0
# Search step along the run.
_LABEL_STEP = 6.0
# Number of sideways stand-off bands the search tries, nearest first.
_LABEL_BANDS = 7
# Furthest a tag steps out from its side's spot.
_TAG_STEP_OUT = 30.0
# How much nearer a stepped-out tag stays to its symbol than to any other.
_TAG_NEARER = 1.25
# Outward direction of each side.
_OUTWARD = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}

def _class_weight(sym) -> LineWeight:
    """Return the line weight of a symbol's outline.

    Trim symbols use the detail rung and equipment the equipment rung
    (ISO 10628-1 5.3.1).

    Parameters
    ----------
    sym : Symbol
        Registered symbol.

    Returns
    -------
    LineWeight
        Outline rung.
    """
    return LineWeight.DETAIL if sym.trim else LineWeight.EQUIPMENT


def _stream_rung(signal: bool) -> LineWeight:
    """Return the line weight of a stream (ISO 10628-1 5.3.1).

    Parameters
    ----------
    signal : bool
        Whether the stream is a signal line.

    Returns
    -------
    LineWeight
        Detail rung for a signal line, else main flow.
    """
    return LineWeight.DETAIL if signal else LineWeight.MAIN_FLOW


def _ink_pad(rung: LineWeight) -> float:
    """Return how far an opaque plate stays from a line on ``rung``.

    Parameters
    ----------
    rung : LineWeight
        Line weight.

    Returns
    -------
    float
        Half the pen plus one unit of paper.
    """
    return rung.width / 2 + LineWeight.DETAIL.width


# Paper a label plate leaves outside a symbol's ink.
_PLATE_CLEARANCE = 2.0


def _obstacle(box) -> "tuple[float, float, float, float]":
    """Return a symbol box grown to the area a label must keep off.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Drawn box ``(x0, y0, x1, y1)``.

    Returns
    -------
    tuple[float, float, float, float]
        Grown box.
    """
    pad = LineWeight.EQUIPMENT.width / 2 + _PLATE_CLEARANCE
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _along(box, vertical: bool, lo: float, hi: float) -> bool:
    """Return whether over half of label ``box`` lies along a run.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Label box.
    vertical : bool
        Whether the run is vertical.
    lo, hi : float
        Run extent along its axis.

    Returns
    -------
    bool
        Whether over half the label is alongside the run.
    """
    a, b = (box[1], box[3]) if vertical else (box[0], box[2])
    return min(b, hi) - max(a, lo) > (b - a) / 2


def _slide(x: float, y: float, room: float, vertical: bool):
    """Yield label anchors along a run, centre first, then outwards.

    Parameters
    ----------
    x, y : float
        Centre anchor.
    room : float
        Distance available either way of ``(x, y)``.
    vertical : bool
        Whether the run is vertical.

    Yields
    ------
    tuple[float, float]
        Anchor point.
    """
    yield x, y
    for k in range(1, int(room // _LABEL_STEP) + 1):
        d = k * _LABEL_STEP
        yield (x, y - d) if vertical else (x - d, y)
        yield (x, y + d) if vertical else (x + d, y)


# --- the ink a halo would delete --------------------------------------


class _Ink(NamedTuple):
    """A drawn line, as the rectangle its stroke covers.

    Attributes
    ----------
    x0, y0, x1, y1 : float
        Covered rectangle.
    axis : str
        ``"h"`` or ``"v"``.
    at : float
        The ``y`` of a horizontal line or ``x`` of a vertical one.
    kind : str
        ``"pipe"``, ``"tap"`` or ``"hop"``.
    line : str
        Stream number of the run, or ``""`` for an impulse line.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    axis: str
    at: float
    kind: str
    line: str

    @property
    def box(self) -> "tuple[float, float, float, float]":
        """Return the covered rectangle.

        Returns
        -------
        tuple[float, float, float, float]
            ``(x0, y0, x1, y1)``.
        """
        return (self.x0, self.y0, self.x1, self.y1)


def tap_lines(fs):
    """Return every drawn tap line.

    Skip balloons placed ``"near"`` their host, those a stream already
    joins to it, and those sitting on the tap point.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.

    Returns
    -------
    list[tuple[Instrument, tuple[float, float], tuple[float, float]]]
        Instrument, tap point and balloon centre for each line.
    """
    from pandid.layout.attach import is_attached

    wired = {(id(s.source.owner), id(s.dest.owner)) for s in fs.streams}
    out = []
    for u in fs.units:
        tap = getattr(u, "tap", None)
        if not is_attached(u) or tap is None or u.frame is None:
            continue
        host = u.host
        if getattr(u, "relation", "sensing") == "near":
            continue
        if (id(u), id(host)) in wired or (id(host), id(u)) in wired:
            continue
        centre = (u.frame.cx, u.frame.cy)
        if abs(centre[0] - tap[0]) < 0.5 and abs(centre[1] - tap[1]) < 0.5:
            continue
        out.append((u, tap, centre))
    return out


def tap_route(inst, tap, centre):
    """Return the orthogonal path of one tap line.

    A balloon on a pipe, or ahead of a unit's face, is reached in one
    straight run when aligned with the tap. Otherwise the line leaves
    the tap square to its host and turns once onto the balloon centre
    (ISO 15519-1 12.4). A balloon behind a unit's face is reached one
    module out from the face, and around the unit's box when level
    with it.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.
    tap, centre : tuple[float, float]
        Tap point and balloon centre, from :func:`tap_lines`.

    Returns
    -------
    list[tuple[float, float]]
        Points from the tap to the balloon centre.
    """
    from pandid.layout.attach import _anchor
    from pandid.streams import Stream

    (tx, ty), (cx, cy) = tap, centre
    anchor = _anchor(inst)
    if anchor is None:
        return [tap, centre]
    # A unit's reference runs along its face; turned, it is the outward normal.
    rx, ry = anchor[1]
    nx, ny = ry, -rx
    across = abs(nx) > abs(ny)
    # A pipe has no outside, so its balloon is always ahead.
    if isinstance(inst.host, Stream) or (cx - tx) * nx + (cy - ty) * ny > 0:
        if abs(cx - tx) < 0.01 or abs(cy - ty) < 0.01:
            return [tap, centre]
        return [tap, (cx, ty) if across else (tx, cy), centre]
    sx, sy = tx + nx * M, ty + ny * M
    x0, y0, x1, y1 = unit_box(inst.host, inst.host.frame)
    if across:
        y = cy if not y0 < cy < y1 else (y0 - M if cy - y0 < y1 - cy else y1 + M)
        bends = [(sx, sy), (sx, y), (cx, y)]
    else:
        x = cx if not x0 < cx < x1 else (x0 - M if cx - x0 < x1 - cx else x1 + M)
        bends = [(sx, sy), (x, sy), (x, cy)]
    return [tap, *bends] if bends[-1] == centre else [tap, *bends, centre]


def impulse_tap(inst) -> bool:
    """Return whether a balloon's tap line is solid impulse tubing.

    It is when the host holds fluid, the relation is ``"sensing"`` and
    the balloon is a field device.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.

    Returns
    -------
    bool
        Whether the tap line is drawn solid.
    """
    host = getattr(inst, "host", None)
    host_kind = getattr(host, "kind", "")
    holds_fluid = (host is not None and host_kind != "instrument"
                   and host_kind not in _SIGNAL_KINDS)
    return (holds_fluid
            and getattr(inst, "relation", "sensing") == "sensing"
            and getattr(inst, "variant", "default") in _FIELD_BALLOONS)


# --- letter codes written outside the symbol --------------------------
# Corner quadrants (ISO 15519-2 5.1.3): (a) references, (b) the variable
# for letter code U, (c) high functions, (d) low functions.

# Quadrant -> (side, away): the side of the symbol and the way a second
# code stacks; +1 is right or down.
_QUADRANTS = {"a": (-1, -1), "b": (-1, 1), "c": (1, -1), "d": (1, 1)}

# The two quadrant pairs, in placement order, with each preferred side.
_QUADRANT_PAIRS = ((("a", "b"), -1), (("c", "d"), 1))

# Paper kept clear either side of the centre line.
_QUADRANT_BAND = 3.0
# Gap from the symbol's edge to the code.
_QUADRANT_GAP = 5.0
# Pitch of two codes in one quadrant: one line of type.
_QUADRANT_PITCH = 15.0
# Furthest a quadrant may move outward to find clear paper.
_QUADRANT_REACH = 60.0


def quadrant_labels(fs, direction: str) -> list:
    """Return every letter code written outside a symbol, placed.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list
        Label items ``(x, y, anchor, baseline, lpos, text)``.
    """
    return [item for pair in _quadrant_pairs(fs, direction) for item in pair[3]]


def drawn_codes(fs, joints: "str | None", direction: str, labels) -> list:
    """Return the letter codes as drawn, after every other label is placed.

    A pair from :func:`quadrant_labels` on a flange mark moves to a spot
    clear of the symbols, lines, flange marks, pneumatic hatches, every
    other code and ``labels``; with no such spot it stays.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    joints : str or None
        :func:`sheet_connections` result.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.
    labels : Sequence[tuple[float, float, float, float]]
        Every other label's final box.

    Returns
    -------
    list
        Label items ``(x, y, anchor, baseline, lpos, text)``.
    """
    from pandid.portgeom import unit_box

    pairs = _quadrant_pairs(fs, direction)
    flanges = [_obstacle(b) for b in flange_boxes(fs, joints)]
    if pairs and flanges:
        ink = _ink(fs, direction)
        held = [_obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
        held += flanges + [_obstacle(m.box) for m in pipe_marks(fs)]
        held += [_obstacle(b) for b in labels]
        # The hatch strokes stand off a pneumatic line, outside its ink.
        held += hatch_boxes(fs)
        for pair in pairs:
            box, codes, prefers, placed = pair
            if not any(boxes_overlap(b, f) for b in map(_unit_label_box, placed)
                       if b is not None for f in flanges):
                continue
            others = [b for other in pairs if other is not pair
                      for b in map(_unit_label_box, other[3]) if b is not None]
            damage, moved = _quadrant_side(box, codes, prefers, ink, held + others)
            if damage == (0, 0, 0):
                pair[3] = moved
    return [item for pair in pairs for item in pair[3]]


def _quadrant_pairs(fs, direction: str) -> list:
    """Return every symbol's pairs of letter codes, placed in turn.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list
        ``[box, codes, prefers, items]`` for each pair: the symbol box, the
        codes by quadrant, the preferred side and the placed label items.
    """
    from pandid.portgeom import unit_box

    annotated = [u for u in fs.units
                 if u.frame is not None and getattr(u, "quadrants", None)]
    if not annotated:
        return []
    ink = _ink(fs, direction)
    symbols = [_obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None]

    pairs: list = []
    for u in annotated:
        box = unit_box(u, u.frame)
        for names, prefers in _QUADRANT_PAIRS:
            codes = {name: u.quadrants.get(name) or () for name in names}
            if not any(codes.values()):
                continue
            _damage, placed = _quadrant_side(box, codes, prefers, ink, symbols)
            pairs.append([box, codes, prefers, placed])
            # Placed codes become obstacles for later pairs.
            symbols += [b for b in map(_unit_label_box, placed) if b is not None]
    return pairs


def _quadrant_side(box, codes, prefers: int, ink, symbols):
    """Return a pair of codes placed on the cleaner side of a symbol.

    The other side wins only if it is cleaner. Where neither side is
    clean, each quadrant takes its own cleaner side if that is cleaner
    still.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Symbol box.
    codes : dict[str, tuple[str, ...]]
        Codes keyed by quadrant letter.
    prefers : int
        Preferred side: ``1`` for right, ``-1`` for left.
    ink : list[_Ink]
        Drawn lines.
    symbols : list[tuple[float, float, float, float]]
        Obstacle boxes.

    Returns
    -------
    tuple[tuple[int, int, int], list]
        The :func:`_erases` score and the placed label items.
    """
    best = None
    for side in (prefers, -prefers):
        block = _quadrant_block(box, codes, side)
        shift, damage = _quadrant_stand_off(block, side, ink, symbols)
        if best is None or damage < best[0]:
            best = (damage, [(x + side * shift, y, *rest) for x, y, *rest in block])
        if damage == (0, 0, 0):
            break
    assert best is not None
    if best[0] != (0, 0, 0) and len(codes) > 1 and all(codes.values()):
        (one, upper), (two, lower) = (_quadrant_side(box, {name: quadrant}, prefers, ink, symbols)
                                      for name, quadrant in codes.items())
        split = (one[0] + two[0], one[1] + two[1], one[2] + two[2])
        if split < best[0]:
            best = (split, upper + lower)
    return best


def _quadrant_block(box, codes, side: int) -> list:
    """Return one side's codes laid out from the symbol's box outward.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Symbol box.
    codes : dict[str, tuple[str, ...]]
        Codes keyed by quadrant letter.
    side : int
        ``1`` for right, ``-1`` for left.

    Returns
    -------
    list
        Label items ``(x, y, anchor, baseline, lpos, text)``.
    """
    cy = (box[1] + box[3]) / 2
    lx = (box[2] if side > 0 else box[0]) + side * _QUADRANT_GAP
    anchor, lpos = ("start", "right") if side > 0 else ("end", "left")
    return [
        (lx,
         cy + _QUADRANTS[name][1] * (_QUADRANT_BAND + _QUADRANT_PITCH / 2
                                     + i * _QUADRANT_PITCH),
         anchor, "middle", lpos, code)
        for name in codes
        for i, code in enumerate(codes[name])
    ]


def _quadrant_stand_off(block, side: int, ink, symbols):
    """Return the outward shift for a pair of codes and its damage.

    Parameters
    ----------
    block : list
        Label items from :func:`_quadrant_block`.
    side : int
        ``1`` for right, ``-1`` for left.
    ink : list[_Ink]
        Drawn lines.
    symbols : list[tuple[float, float, float, float]]
        Obstacle boxes.

    Returns
    -------
    tuple[float, tuple[int, int, int]]
        Shift and the remaining :func:`_erases` score.
    """
    boxes = [b for b in map(_unit_label_box, block) if b is not None]
    if not boxes:
        return 0.0, (0, 0, 0)

    def damage(m: float) -> tuple[int, int, int]:
        """Return the :func:`_erases` total with the block moved ``m``.

        Parameters
        ----------
        m : float
            Outward shift.

        Returns
        -------
        tuple[int, int, int]
            Symbols, impulse lines and pipe pieces hit.
        """
        hits = taps = pipes = 0
        for b in boxes:
            moved = (b[0] + side * m, b[1], b[2] + side * m, b[3])
            one, two, three = _erases(moved, ink, symbols)
            hits, taps, pipes = hits + one, taps + two, pipes + three
        return hits, taps, pipes

    steps = {0.0}
    for o in [*symbols, *(line.box for line in ink)]:
        for b in boxes:
            steps.add(o[2] + _PLATE_CLEARANCE - b[0] if side > 0
                      else b[2] - o[0] + _PLATE_CLEARANCE)
    clear = (0, 0, 0)
    best, cost = 0.0, damage(0.0)
    for m in sorted(step for step in steps if 0.0 < step <= _QUADRANT_REACH):
        if cost == clear:
            break
        got = damage(m)
        if got < cost:
            best, cost = m, got
    return best, cost


def _ink(fs, direction: str) -> "list[_Ink]":
    """Return every drawn line and crossing mark as padded rectangles.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[_Ink]
        Pipe, tap and hop rectangles.
    """
    from pandid.layout.attach import stream_path

    out: list[_Ink] = []

    def add(a, b, pad: float, kind: str, line: str = "") -> None:
        """Append the padded rectangle of segment ``a``-``b``.

        Parameters
        ----------
        a, b : tuple[float, float]
            Segment end points.
        pad : float
            Padding each side.
        kind : str
            ``"pipe"`` or ``"tap"``.
        line : str, default=""
            Stream number of the run.
        """
        (ax, ay), (bx, by) = a, b
        if abs(ax - bx) < 0.5 and abs(ay - by) < 0.5:
            return
        axis, at = ("v", (ax + bx) / 2) if abs(ax - bx) < abs(ay - by) else ("h", (ay + by) / 2)
        out.append(_Ink(min(ax, bx) - pad, min(ay, by) - pad,
                        max(ax, bx) + pad, max(ay, by) + pad, axis, at, kind, line))

    for s in fs.streams:
        pad = _ink_pad(_stream_rung(s.kind in _SIGNAL_KINDS))
        points = stream_path(s)
        for a, b in zip(points, points[1:]):
            add(a, b, pad, "pipe", s.name or "")
    for u, tap, centre in tap_lines(fs):
        route = tap_route(u, tap, centre)
        for a, b in zip(route, route[1:]):
            add(a, b, _ink_pad(LineWeight.DETAIL), "tap")
    # A hop belongs to the run that draws it.
    for hop in stream_hops(fs, direction):
        run = fs.streams[hop.stream]
        pad = _ink_pad(_stream_rung(run.kind in _SIGNAL_KINDS))
        x0, y0, x1, y1 = hop_box(hop, pad)
        out.append(_Ink(x0, y0, x1, y1, "v" if hop.vertical else "h",
                        hop.x if hop.vertical else hop.y, "hop", hop.line))
    return out


def _erases(box, ink, symbols=()) -> "tuple[int, int, int]":
    """Return the symbols, taps and pipes a halo at ``box`` would erase.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Halo box.
    ink : list[_Ink]
        Drawn lines.
    symbols : Sequence[tuple[float, float, float, float]], optional
        Obstacle boxes.

    Returns
    -------
    tuple[int, int, int]
        Symbols, impulse lines and pipe pieces hit, ordered by cost.
    """
    hits = sum(1 for b in symbols if boxes_overlap(box, b))
    taps = pipes = 0
    for line in ink:
        if boxes_overlap(box, line.box):
            if line.kind == "tap":
                taps += 1
            else:
                pipes += 1
    return hits, taps, pipes


def _covering(box, occupied, symbols=(), limit=None) -> "tuple[int, int]":
    """Return the symbols and other boxes a halo at ``box`` covers.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Halo box.
    occupied : Iterable[tuple[float, float, float, float]]
        Other occupied boxes.
    symbols : Sequence[tuple[float, float, float, float]], optional
        Obstacle boxes.
    limit : tuple[int, int], optional
        Best score so far; counting stops once the score exceeds it.

    Returns
    -------
    tuple[int, int]
        Symbols covered and other boxes covered.
    """
    hits = sum(1 for b in symbols if boxes_overlap(box, b))
    n = 0
    for p in occupied:
        if boxes_overlap(box, p):
            n += 1
            if limit is not None and (hits, n) > limit:
                break
    return hits, n


def _box_gap(a, b) -> float:
    """Return the distance between two boxes, ``0`` where they meet.

    Parameters
    ----------
    a, b : tuple[float, float, float, float]
        Boxes ``(x0, y0, x1, y1)``.

    Returns
    -------
    float
        Shortest distance from one to the other.
    """
    return math.hypot(max(b[0] - a[2], a[0] - b[2], 0.0), max(b[1] - a[3], a[1] - b[3], 0.0))


def _step_aside(item, room: float, ink=(), others=()):
    """Slide a valve's position mark along its face to clear other ink.

    The nearest clear shift wins, ties going right and down.

    Parameters
    ----------
    item : tuple
        Label item ``(x, y, anchor, baseline, lpos, text)``.
    room : float
        Furthest the mark may move.
    ink : list[_Ink], optional
        Drawn lines.
    others : Sequence[tuple[float, float, float, float]], optional
        Other obstacle boxes.

    Returns
    -------
    tuple
        The moved item, or ``item`` if no shift is better.
    """
    box = _unit_label_box(item)
    if box is None or not (ink or others):
        return item
    lx, ly, anchor, baseline, lpos, text = item
    # A left or right face slides in y.
    vertical = lpos in ("left", "right")
    lo, hi = (box[1], box[3]) if vertical else (box[0], box[2])
    a, b = (1, 3) if vertical else (0, 2)
    shifts = {0.0}
    for o in [*others, *(line.box for line in ink)]:
        shifts.add(o[a] - _PLATE_CLEARANCE - hi)
        shifts.add(o[b] + _PLATE_CLEARANCE - lo)

    clear = (0, 0, 0)
    best, damage = item, _erases(box, ink, others)
    for d in sorted(shifts, key=lambda d: (abs(d), -d)):
        if damage == clear:
            break
        if abs(d) > room:
            continue
        spot = ((lx, ly + d) if vertical else (lx + d, ly)) + (anchor, baseline, lpos, text)
        cost = _erases(_unit_label_box(spot), ink, others)
        if cost < damage:
            best, damage = spot, cost
    return best


def _label_anchors(cx: float, cy: float, span: float, hw: float, hh: float,
                   vertical: bool, on_run: bool, plate: float):
    """Yield anchors for an ``hw`` by ``hh`` label on a run, best first.

    Anchors on the pipe come first, then bands beside it, above or left
    of the run first (ISO 15519-1 7.2.5).

    Parameters
    ----------
    cx, cy : float
        Run midpoint.
    span : float
        Run length.
    hw, hh : float
        Label width and height.
    vertical : bool
        Whether the run is vertical.
    on_run : bool
        Keep the label on the run, with no side bands.
    plate : float
        Opaque length of the label along the run.

    Yields
    ------
    tuple[float, float, float]
        Anchor ``x``, ``y`` and perpendicular stand-off from the run.
    """
    room = (span - plate) / 2 - _LABEL_CLEAR
    if on_run or span >= hw + 2 * _LABEL_CLEAR:
        for x, y in _slide(cx, cy, room, vertical):
            yield x, y, 0.0
    if on_run:
        return
    for out in range(_LABEL_BANDS):
        off = hh / 2 + _LABEL_GAP + out * hh
        for side in (-1.0, 1.0):
            ax = cx + side * off if vertical else cx
            ay = cy if vertical else cy + side * off
            for x, y in _slide(ax, ay, (span + hw) / 2, vertical):
                yield x, y, off


# --- leaders ----------------------------------------------------------

# Leader arrowhead size: half the flow arrowhead.
_LEADER_HEAD = ARROWHEAD / 2


#: Issue code for a crossing the sheet could not mark.
CROSSING_UNMARKED = "crossing-unmarked"


def crossings(polylines: dict, direction: str):
    """Yield every crossing of two runs, in drawing order.

    A crossing lies strictly inside both segments. With
    ``direction="vertical"`` the vertical segment carries the mark.
    Each yield names the marked run, its segment index, the crossed
    run, the crossing point, and whether the segment has
    :data:`HOP_R` either side for the mark.

    Parameters
    ----------
    polylines : dict
        ``{key: points}`` for every run, in drawing order.
    direction : str
        ``"vertical"`` or ``"horizontal"``.

    Yields
    ------
    tuple
        ``(key, seg, other, x, y, room)`` for each crossing.

    Raises
    ------
    ValueError
        If ``direction`` is not a known value.
    """
    check_jump_direction(direction)
    vertical = direction == "vertical"
    crossed = []  # (key, lo, hi, at) of each crossed segment
    for key, points in polylines.items():
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if vertical and y1 == y2 and x1 != x2:
                crossed.append((key, min(x1, x2), max(x1, x2), y1))
            elif not vertical and x1 == x2 and y1 != y2:
                crossed.append((key, min(y1, y2), max(y1, y2), x1))
    for key, points in polylines.items():
        for i, ((x1, y1), (x2, y2)) in enumerate(zip(points, points[1:])):
            at, start, end = (x1, y1, y2) if vertical else (y1, x1, x2)
            if (x1 != x2 if vertical else y1 != y2) or start == end:
                continue
            lo, hi = min(start, end), max(start, end)
            cuts = sorted((c for c in crossed if c[1] < at < c[2] and lo < c[3] < hi),
                          key=lambda c: c[3], reverse=start > end)
            for other, _lo, _hi, c_at in cuts:
                x, y = (at, c_at) if vertical else (c_at, at)
                yield key, i, other, x, y, lo + HOP_R < c_at < hi - HOP_R


def unmarked_crossings(fs, jump_direction: str = "vertical",
                       crossing_style: str = "gap") -> list:
    """Return every crossing drawn without its mark for lack of room.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    jump_direction : str, default="vertical"
        ``"vertical"`` or ``"horizontal"``: which run carries the mark.
    crossing_style : str, default="gap"
        Crossing mark style; ``"plain"`` returns nothing.

    Returns
    -------
    list[tuple[Stream, Stream, float, float]]
        ``(marked, crossed, x, y)`` per crossing.
    """
    if crossing_style == "plain":
        return []
    streams = fs.streams
    polylines = {n: stream_polyline(s) for n, s in enumerate(streams)}
    return [(streams[n], streams[other], x, y)
            for n, _seg, other, x, y, room in crossings(polylines, jump_direction)
            if not room]


def _crossing_issues(fs, jump_direction: str = "vertical",
                     crossing_style: str = "gap") -> list:
    """Return a :data:`CROSSING_UNMARKED` warning per bare crossing.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    jump_direction : str, default="vertical"
        ``"vertical"`` or ``"horizontal"``: which run carries the mark.
    crossing_style : str, default="gap"
        Crossing mark style.

    Returns
    -------
    list[Issue]
        One warning per crossing drawn without its mark.
    """
    mark = "arc" if crossing_style == "arc" else "interruption"
    issues = []
    for marked, crossed, x, y in unmarked_crossings(fs, jump_direction,
                                                    crossing_style):
        a = marked.name or marked.kind
        b = crossed.name or crossed.kind
        issues.append(Issue(
            "warning", CROSSING_UNMARKED,
            f"{a} crosses {b} at ({x:g}, {y:g}) and the crossing is drawn "
            f"bare: {a} has under {HOP_R:g}px of itself either side of the "
            f"point, which is what the {mark} marking a crossing needs to sit "
            f"on. Every other crossing on this sheet carries that mark, so a "
            f"reader may take this one for a junction. Pin one of the two "
            f"runs with via() to move the crossing clear of the corner, or "
            f"draw the sheet with crossing_style='plain' so every crossing "
            f"on it reads the same way"))
    return issues


def _crosses(start, end, region) -> bool:
    """Return whether a segment passes through a rectangle's interior.

    Parameters
    ----------
    start, end : tuple[float, float]
        Segment end points.
    region : tuple[float, float, float, float]
        Rectangle ``(x0, y0, x1, y1)``.

    Returns
    -------
    bool
        Whether the segment enters the interior.
    """
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - region[0]), (dx, region[2] - x0),
                 (-dy, y0 - region[1]), (dy, region[3] - y0)):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            elif r < t0:
                return False
            else:
                t1 = min(t1, r)
    return t0 < t1


def _cutting(leader, occupied, limit: int) -> int:
    """Return how many occupied boxes a leader cuts, up to ``limit``.

    Parameters
    ----------
    leader : tuple[tuple[float, float], tuple[float, float]]
        Leader end points.
    occupied : Iterable[tuple[float, float, float, float]]
        Occupied boxes.
    limit : int
        Count at which to stop.

    Returns
    -------
    int
        Boxes cut, at most ``limit``.
    """
    n = 0
    for p in occupied:
        if _crosses(leader[0], leader[1], p):
            n += 1
            if n >= limit:
                break
    return n


def _near_segment(p, a, b) -> bool:
    """Return whether ``p`` lies on segment ``a``-``b`` within 0.5.

    Parameters
    ----------
    p : tuple[float, float]
        Point.
    a, b : tuple[float, float]
        Segment end points.

    Returns
    -------
    bool
        Whether the point is on the segment.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    if not span:
        return math.hypot(p[0] - a[0], p[1] - a[1]) <= 0.5
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy)) <= 0.5


def _leader(box, seg, occupied, keep_out: float = 0.0) -> "tuple[tuple, int]":
    """Return the leader from a label halo to its run, and what it cuts.

    The leader leaves the halo's near face and lands about 45 degrees
    along the run (ISO 15519-1 Figure 4). Candidates rank by boxes cut,
    closeness to 45 degrees, then closeness to the face's middle.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Label halo.
    seg : tuple[tuple[float, float], tuple[float, float]]
        The run's segment.
    occupied : Sequence[tuple[float, float, float, float]]
        Occupied boxes.
    keep_out : float, default=0.0
        Extra clearance from the run's ends, for drawn flanges.

    Returns
    -------
    tuple[tuple, int]
        ``((start, end), crossings)``: the leader and the boxes it cuts.
    """
    (sx1, sy1), (sx2, sy2) = seg
    vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
    # Work in the run's frame: u along it, v across.
    lo, hi = ((min(sy1, sy2), max(sy1, sy2)) if vertical
              else (min(sx1, sx2), max(sx1, sx2)))
    at = (sx1 + sx2) / 2 if vertical else (sy1 + sy2) / 2
    u0, u1 = (box[1], box[3]) if vertical else (box[0], box[2])
    v0, v1 = (box[0], box[2]) if vertical else (box[1], box[3])
    v = v0 if abs(v0 - at) < abs(v1 - at) else v1
    gap = abs(v - at)
    if keep_out and hi - lo > 3 * keep_out:
        lo, hi = lo + keep_out, hi - keep_out
    inset = min(_LABEL_CLEAR, (hi - lo) / 3)
    near, far = lo + inset, hi - inset

    def route(s: float):
        """Return the leader from face position ``s``.

        Parameters
        ----------
        s : float
            Start position along the halo's face.

        Returns
        -------
        tuple[tuple[float, float], tuple[float, float]]
            Leader start and end.
        """
        u = max((min(max(s + d * gap, near), far) for d in (1.0, -1.0)),
                key=lambda c: abs(c - s))
        return ((v, s), (at, u)) if vertical else ((s, v), (u, at))

    # Inset the face ends, at most a quarter of a short face.
    ends = min(abs(v1 - v0) / 2, (u1 - u0) / 4)
    first, last, mid = u0 + ends, u1 - ends, (u0 + u1) / 2
    starts = [first + k * _LABEL_STEP
              for k in range(int((last - first) // _LABEL_STEP) + 1)] + [last]

    def scored(s: float, limit: int):
        """Return the leader from ``s`` and its ranking key.

        Parameters
        ----------
        s : float
            Start position along the halo's face.
        limit : int
            Count at which :func:`_cutting` stops.

        Returns
        -------
        tuple[tuple, tuple[int, float, float]]
            Leader and its ranking key.
        """
        lead = route(s)
        u = lead[1][1] if vertical else lead[1][0]
        return lead, (_cutting(lead, occupied, limit), abs(abs(u - s) - gap),
                      abs(s - mid))

    best, score = scored(starts[0], len(occupied) + 1)
    for s in starts[1:]:
        lead, rank = scored(s, score[0] + 1)
        if rank < score:
            best, score = lead, rank
    return best, score[0]


class _Hop(NamedTuple):
    """One crossing mark and the run that draws it.

    Attributes
    ----------
    x, y : float
        Centre of the mark on the marked run.
    vertical : bool
        Whether the marked run is vertical.
    side : float
        Which way an arc bulges: ``+1`` towards greater x (or y).
    stream : int
        Index of the marked run in ``fs.streams``.
    seg : int
        Index of its segment in :func:`stream_polyline`.
    line : str
        Marked run's number.
    """
    x: float
    y: float
    vertical: bool
    side: float
    stream: int
    seg: int
    line: str


def stream_hops(fs, direction: str) -> "list[_Hop]":
    """Return every crossing mark the sheet draws, in drawing order.

    An arc bulges by SVG's clockwise sweep: a run drawn downward bulges
    right, upward left, rightward up, leftward down.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[_Hop]
        Crossing marks that have room to be drawn.

    Raises
    ------
    ValueError
        If ``direction`` is not a known value.
    """
    polylines = {n: stream_polyline(s) for n, s in enumerate(fs.streams)}
    vertical = direction == "vertical"
    out: list[_Hop] = []
    for n, i, _other, x, y, room in crossings(polylines, direction):
        if room:
            (x1, y1), (x2, y2) = polylines[n][i:i + 2]
            side = (1.0 if y1 < y2 else -1.0) if vertical else (-1.0 if x1 < x2 else 1.0)
            out.append(_Hop(x, y, vertical, side, n, i, fs.streams[n].name or ""))
    return out


def hop_box(hop: _Hop, pad: float) -> "tuple[float, float, float, float]":
    """Return the padded box of a crossing arc on its bulging side.

    Parameters
    ----------
    hop : _Hop
        Crossing mark.
    pad : float
        Padding each side.

    Returns
    -------
    tuple[float, float, float, float]
        Box ``(x0, y0, x1, y1)``.
    """
    if hop.vertical:
        lo, hi = sorted((hop.x, hop.x + hop.side * HOP_R))
        return (lo - pad, hop.y - HOP_R - pad, hi + pad, hop.y + HOP_R + pad)
    lo, hi = sorted((hop.y, hop.y + hop.side * HOP_R))
    return (hop.x - HOP_R - pad, lo - pad, hop.x + HOP_R + pad, hi + pad)


#: Font size of a line number.
NUMBER_TYPE = 10
# Halo width added to the words, and depth.
_HALO_PAD, _HALO_DEEP = 6.0, 13.0

# Gap a box enclosure leaves outside the halo on each side.
_ENCLOSURE_PAD = 4.0

# Enclosure stroke: the narrow line a leader also uses.
_ENCLOSURE_STROKE = LineWeight.DETAIL.width

#: Enclosures whose numbers stay upright on a vertical run.
UPRIGHT_ENCLOSURES = ("diamond", "circle")


def enclosure_shape(fs) -> str:
    """Return the sheet's stream-label enclosure shape.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        ``"none"``, ``"diamond"``, ``"circle"`` or ``"box"``.

    Raises
    ------
    ValueError
        If the configured shape is unknown.
    """
    from pandid.document import _resolve_enclosure

    return _resolve_enclosure(fs.stream_labels.enclosure)


def enclosure_box(shape: str, hw: float, hh: float) -> "tuple[float, float]":
    """Return the size of an enclosure holding an ``hw`` by ``hh`` halo.

    * ``diamond`` -- the smallest square turned 45 degrees round the
      halo, ``hw + hh`` each way.
    * ``circle`` -- the circumscribed circle.
    * ``box`` -- the halo plus :data:`_ENCLOSURE_PAD` each side.

    Parameters
    ----------
    shape : str
        Enclosure shape; any other value returns the halo size.
    hw, hh : float
        Halo width and height.

    Returns
    -------
    tuple[float, float]
        Enclosure size along and across the words.
    """
    if shape == "diamond":
        side = hw + hh
        return side, side
    if shape == "circle":
        d = math.hypot(hw, hh)
        return d, d
    if shape == "box":
        return hw + 2 * _ENCLOSURE_PAD, hh + 2 * _ENCLOSURE_PAD
    return hw, hh


def _enclosure_svg(shape: str, box, words, color: str, fill: bool = False) -> list[str]:
    """Return the SVG for a stream label's plate and enclosure outline.

    Parameters
    ----------
    shape : str
        Enclosure shape; ``"none"`` returns the plate alone.
    box : tuple[float, float, float, float]
        Enclosure box.
    words : tuple[float, float, float, float] or None
        Plate under the words, or ``None`` for no plate.
    color : str
        Outline colour.
    fill : bool, default=False
        Fill the outline white.

    Returns
    -------
    list[str]
        SVG elements: plate, then outline.
    """
    plate = []
    if words is not None:
        a0, b0, a1, b1 = words
        plate = [f'    <rect x="{a0:.1f}" y="{b0:.1f}" '
                 f'width="{a1 - a0:.1f}" height="{b1 - b0:.1f}" fill="white" />']
    if shape == "none":
        return plate
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pen = (f'fill="{"white" if fill else "none"}" stroke="{color}" '
           f'stroke-width="{_ENCLOSURE_STROKE:g}"')
    if shape == "diamond":
        points = (f"{cx:.1f},{y0:.1f} {x1:.1f},{cy:.1f} "
                  f"{cx:.1f},{y1:.1f} {x0:.1f},{cy:.1f}")
        outline = f'    <polygon points="{points}" {pen} />'
    elif shape == "circle":
        outline = (f'    <circle cx="{cx:.1f}" cy="{cy:.1f}" '
                   f'r="{(x1 - x0) / 2:.1f}" {pen} />')
    else:
        outline = (f'    <rect x="{x0:.1f}" y="{y0:.1f}" '
                   f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" {pen} />')
    return [*plate, outline]


class StreamNumber(NamedTuple):
    """Placement of one line number, read by both backends.

    Attributes
    ----------
    name : str
        Line number.
    color : str
        Text colour.
    seg : tuple
        The run's longest segment, which the number names.
    x, y : float
        Centre of the string.
    vertical : bool
        Whether the words are turned to read bottom to top.
    box : tuple
        Enclosure shape's box, or the halo where none is drawn.
    leader : tuple or None
        Leader end points, or ``None`` when written along the run.
    words : tuple or None
        Opaque plate under the string, or ``None`` for no plate.
    crossed : tuple[str, ...]
        Runs the number is written across, if any.
    """
    name: str
    color: str
    seg: tuple
    x: float
    y: float
    vertical: bool
    box: tuple
    leader: "tuple | None"
    words: "tuple | None"
    crossed: "tuple[str, ...]"


def stream_numbers(fs, placed: list, joints: "str | None",
                   direction: str) -> "list[StreamNumber]":
    """Place one line number on each named material run.

    The number goes on the run's longest segment. Candidates rank by
    other lines the plate would erase, symbols and labels covered, then
    boxes a leader would cut. Where every spot erases another run, the
    number gets no plate.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    placed : list
        Occupied label boxes; chosen boxes are appended.
    joints : str or None
        Sheet-wide connection style.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[StreamNumber]
        One placement per named material run.
    """
    from pandid.portgeom import unit_box

    ink = _ink(fs, direction)
    symbols: list[tuple[float, float, float, float]] = [
        _obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None
    ]

    symbols += [_obstacle(b) for b in flange_boxes(fs, joints)]
    symbols += [_obstacle(m.box) for m in pipe_marks(fs)]
    symbols += [b for b in map(_unit_label_box, quadrant_labels(fs, direction))
                if b is not None]
    symbols += [_obstacle(b) for b in package_edges(fs)]

    # One number per run name, through inline valves and fittings.
    label_items: list = []
    labeled_names: set = set()
    for s in fs.streams:
        if s.kind in _SIGNAL_KINDS or s.name in labeled_names:
            continue
        longest_seg, max_len = None, -1.0
        carrier, carrier_points = s, []
        candidates = [part for part in s._logical_segments if part.name == s.name] or [s]
        for part in candidates:
            points = stream_polyline(part)
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = abs(x2 - x1) + abs(y2 - y1)
                if length > max_len:
                    max_len, longest_seg = length, ((x1, y1), (x2, y2))
                    carrier, carrier_points = part, points
        if not longest_seg:
            continue
        labeled_names.add(s.name)
        # Length the segment's own flange marks take at its ends.
        (mx1, my1), (mx2, my2) = longest_seg
        keep = FLANGE_STANDOFF + FLANGE_GAP / 2 if any(
            _near_segment((m.x, m.y), (mx1, my1), (mx2, my2))
            for m in flange_marks(carrier, carrier_points, resolve_connections(carrier, joints))
        ) else 0.0
        label_items.append((longest_seg, s.name, s.color or "black", keep))

    # Enclosures are one size per sheet, fitted to the longest label.
    shape = enclosure_shape(fs)
    widest = max((F.text_width(name, NUMBER_TYPE) + _HALO_PAD
                  for _s, name, _c, _k in label_items), default=0.0)
    uniform = enclosure_box(shape, widest, _HALO_DEEP)

    out: list[StreamNumber] = []
    for seg, name, color, keep in label_items:
        (sx1, sy1), (sx2, sy2) = seg
        # The words' size, and the reserved size.
        tw, th = F.text_width(name, NUMBER_TYPE) + _HALO_PAD, _HALO_DEEP
        hw, hh = (tw, th) if shape == "none" else uniform
        cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
        vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
        span = abs(sy2 - sy1) if vertical else abs(sx2 - sx1)
        # A bare or boxed number reads bottom to top on a vertical run
        # (ISO 15519-1 7.2.5).
        turned = vertical and shape not in UPRIGHT_ENCLOSURES
        bw, bh = (hh, hw) if vertical else (hw, hh)
        lw, lh = (th, tw) if turned else (tw, th)

        # The area any anchor can reach.
        along = (span + hw) / 2 + max(bw, bh) / 2
        across = hh / 2 + _LABEL_GAP + _LABEL_BANDS * hh + max(bw, bh) / 2
        rx, ry = (across, along) if vertical else (along, across)
        window = (cx - rx, cy - ry, cx + rx, cy + ry)

        axis, at = ("v", (sx1 + sx2) / 2) if vertical else ("h", (sy1 + sy2) / 2)
        # Centreline extent of the whole collinear run, through inline valves.
        run_lo = min(sy1, sy2) if vertical else min(sx1, sx2)
        run_hi = max(sy1, sy2) if vertical else max(sx1, sx2)
        for line in ink:
            if (line.kind == "pipe" and line.line == name and line.axis == axis
                    and abs(line.at - at) < 0.5):
                # A pipe's box pads its centreline equally on every side.
                pad = (line.x1 - line.x0) / 2 if vertical else (line.y1 - line.y0) / 2
                run_lo = min(run_lo, (line.y0 if vertical else line.x0) + pad)
                run_hi = max(run_hi, (line.y1 if vertical else line.x1) - pad)

        near_symbols = [p for p in symbols if boxes_overlap(p, window)]
        occupied = [p for p in placed if boxes_overlap(p, window)]
        occupied += [line.box for line in ink
                     if not (line.axis == axis and abs(line.at - at) < 0.5)
                     and boxes_overlap(line.box, window)]
        # Other runs' ink, by name, and every tap.
        foreign = [line for line in ink
                   if line.line != name and boxes_overlap(line.box, window)]
        everything = near_symbols + occupied

        # The first clear spot wins, otherwise the least damaging.
        clear = (0, 0, 0, 0)
        spot: "tuple[float, float] | None" = None
        damage: "tuple[int, int, int, int] | None" = None
        leader: "tuple | None" = None
        for ux, uy, _off in _label_anchors(cx, cy, span, hw, hh, vertical,
                                           shape != "none", tw):
            box = (ux - bw / 2, uy - bh / 2, ux + bw / 2, uy + bh / 2)
            paper = (box if shape == "none" else
                     (ux - lw / 2, uy - lh / 2, ux + lw / 2, uy + lh / 2))
            erased = sum(1 for line in foreign if boxes_overlap(paper, line.box))
            limit = None
            if damage is not None:
                if erased > damage[0]:
                    continue
                limit = damage[1:3] if erased == damage[0] else None
            hits = _covering(box, occupied, near_symbols, limit)
            if limit is not None and hits > limit:
                continue
            lead, cut = ((None, 0)
                         if shape != "none" or _along(box, vertical, run_lo, run_hi)
                         else _leader(box, seg, everything, keep))
            cost = (erased, *hits, cut)
            if damage is None or cost < damage:
                spot, damage, leader = (ux, uy), cost, lead
                if cost == clear:
                    break
        assert spot is not None and damage is not None
        tx, ty = spot
        halo = (tx - bw / 2, ty - bh / 2, tx + bw / 2, ty + bh / 2)
        # The halo with no enclosure, otherwise the words' box.
        paper = (halo if shape == "none" else
                 (tx - lw / 2, ty - lh / 2, tx + lw / 2, ty + lh / 2))
        words = None if damage[0] else paper
        crossed = () if words is not None else tuple(sorted(
            {line.line or "an instrument connection" for line in foreign
             if boxes_overlap(paper, line.box)}))
        placed.append(halo)
        if leader is not None:
            (ax0, ay0), (ax1, ay1) = leader
            placed.append((min(ax0, ax1), min(ay0, ay1),
                           max(ax0, ax1), max(ay0, ay1)))
        out.append(StreamNumber(name, color, seg, tx, ty, turned, halo,
                                leader, words, crossed))
    return out


# Issue codes from the stream-label pass.
_LABEL_CODES = ("label-over-line", "enclosure-over-unit",
                "enclosure-over-line", "enclosure-over-label")


def _shape_hits(shape: str, box, rect) -> bool:
    """Return whether an enclosure filling ``box`` meets ``rect``.

    Parameters
    ----------
    shape : str
        ``"box"``, ``"circle"`` or ``"diamond"``.
    box : tuple[float, float, float, float]
        Enclosure box.
    rect : tuple[float, float, float, float]
        Rectangle to test.

    Returns
    -------
    bool
        Whether the shape and the rectangle share area.
    """
    if not boxes_overlap(box, rect):
        return False
    x0, y0, x1, y1 = box
    if shape == "box":
        return True
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a, b = (x1 - x0) / 2, (y1 - y0) / 2
    dx = max(rect[0] - cx, 0.0, cx - rect[2])
    dy = max(rect[1] - cy, 0.0, cy - rect[3])
    if shape == "circle":
        return math.hypot(dx, dy) <= a
    return a > 0 and b > 0 and dx / a + dy / b <= 1.0


def _shapes_meet(shape: str, box, other) -> bool:
    """Return whether two enclosures of one shape share area.

    Parameters
    ----------
    shape : str
        ``"box"``, ``"circle"`` or ``"diamond"``.
    box, other : tuple[float, float, float, float]
        The two enclosure boxes.

    Returns
    -------
    bool
        Whether the shapes share area.
    """
    if not boxes_overlap(box, other):
        return False
    if shape == "box":
        return True
    ax, ay = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    bx, by = (other[0] + other[2]) / 2, (other[1] + other[3]) / 2
    a1, b1 = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
    a2, b2 = (other[2] - other[0]) / 2, (other[3] - other[1]) / 2
    dx, dy = bx - ax, by - ay
    if shape == "circle":
        return math.hypot(dx, dy) < a1 + a2
    for ux, uy in ((b1, a1), (b1, -a1), (b2, a2), (b2, -a2)):
        reach = max(abs(a1 * ux), abs(b1 * uy)) + max(abs(a2 * ux), abs(b2 * uy))
        if abs(dx * ux + dy * uy) >= reach:
            return False
    return True


def fillable_enclosures(fs, shape: str, numbers: "list[StreamNumber]",
                        direction: str) -> "list[bool]":
    """Return which enclosures may be filled white, in order.

    A shape is filled only when it reaches no symbol, no other run's ink
    and no other enclosure.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    shape : str
        Enclosure shape; ``"none"`` fills nothing.
    numbers : list[StreamNumber]
        Placed numbers.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[bool]
        Whether each enclosure may be filled.
    """
    from pandid.portgeom import unit_box

    if shape == "none":
        return [False] * len(numbers)
    ink = _ink(fs, direction)
    boxes = [u.frame is not None and unit_box(u, u.frame) for u in fs.units]
    out: list[bool] = []
    for number in numbers:
        clear = (
            not any(box and _shape_hits(shape, number.box, box) for box in boxes)
            and not any(line.line != number.name
                        and _shape_hits(shape, number.box, line.box) for line in ink)
            and not any(other is not number
                        and _shapes_meet(shape, number.box, other.box)
                        for other in numbers)
        )
        out.append(clear)
    return out


def label_findings(fs, shape: str, numbers: "list[StreamNumber]",
                   direction: str) -> "list[Issue]":
    """Return warnings for what stream labels are drawn over.

    * ``label-over-line`` -- the number is written across another run.
    * ``enclosure-over-unit`` -- the shape crosses a symbol's box.
    * ``enclosure-over-line`` -- the shape crosses another run's ink.
    * ``enclosure-over-label`` -- two enclosures overlap, reported once
      per pair.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    shape : str
        Enclosure shape; ``"none"`` returns only ``label-over-line``.
    numbers : list[StreamNumber]
        Placed numbers.
    direction : str
        ``jump_direction``: ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[Issue]
        Warnings.
    """
    from pandid.portgeom import unit_box

    out: list[Issue] = []
    for number in numbers:
        if number.crossed:
            out.append(Issue(
                "warning", "label-over-line",
                f"{number.name}'s number is written across "
                f"{', '.join(number.crossed)}. Nowhere along its run could "
                f"the plate the number is written on go without painting out "
                f"a line that is not {number.name}, so no plate is drawn and "
                f"the crossing run is drawn through the number instead of "
                f"being rubbed out under it. Space the sheet, or route "
                f"{number.name} clear with via()"))
    if shape == "none":
        return out
    ink = _ink(fs, direction)
    for i, number in enumerate(numbers):
        units = sorted({u.name for u in fs.units if u.frame is not None
                        and _shape_hits(shape, number.box, unit_box(u, u.frame))})
        lines = sorted({line.line or "an instrument connection" for line in ink
                        if line.line != number.name
                        and _shape_hits(shape, number.box, line.box)})
        if units:
            out.append(Issue(
                "warning", "enclosure-over-unit",
                f"{number.name}'s {shape} is drawn over {', '.join(units)}. An "
                f"enclosed label stays on its run, so the shape goes where the "
                f"line goes; space the sheet to clear it, or set "
                f"fs.stream_labels.enclosure = 'circle', which is the tightest "
                f"of the three on a long label"))
        if lines:
            out.append(Issue(
                "warning", "enclosure-over-line",
                f"{number.name}'s {shape} is drawn over {', '.join(lines)}, so "
                f"more than one run passes through one shape. Every line is "
                f"still drawn -- the shape is an outline and fills nothing -- "
                f"but the reader has to tell them apart. Space the sheet, or "
                f"route {number.name} clear with via()"))
        # Earlier labels only, so each pair is reported once.
        pairs = sorted({other.name for other in numbers[:i]
                        if _shapes_meet(shape, number.box, other.box)})
        if pairs:
            out.append(Issue(
                "warning", "enclosure-over-label",
                f"{number.name}'s {shape} crosses {', '.join(pairs)}'s. Two "
                f"outlines over one another read as a shape that is neither; "
                f"both labels are on their own runs and neither may leave, so "
                f"space the runs apart"))
    return out


#: Depth of an off-page flag's point.
FLAG_POINT = 15


class Pennant(NamedTuple):
    """Off-page flag geometry for a Feed or Product.

    Attributes
    ----------
    box : tuple[float, float, float, float]
        Rectangle the pennant occupies.
    point : float
        Depth the point is cut back from its end.
    east : bool
        Whether the point is on the east end.
    """
    box: tuple[float, float, float, float]
    point: float
    east: bool


def boundary_flag(u, frame) -> Pennant:
    """Return the pennant an off-page flag is drawn as.

    The pennant fills :func:`~pandid.portgeom.unit_box` and points
    east, or west when mirrored.

    Parameters
    ----------
    u : Unit
        Feed or Product.
    frame : Frame
        The unit's placed frame.

    Returns
    -------
    Pennant
        Flag geometry.
    """
    from pandid.portgeom import unit_box

    return Pennant(unit_box(u, frame), FLAG_POINT, not frame.mirrored)


#: Positions of the two strokes of a pneumatic double cross-hatch along
#: the run, relative to the mark.
HATCH_ALONG = (-2.5, 1.5)
#: Half-reach of each stroke along and across the run.
HATCH_ARM = (3.0, 5.0)


class Hatch(NamedTuple):
    """One double cross-hatch on a pneumatic line.

    Attributes
    ----------
    x, y : float
        Mark position.
    horizontal : bool
        Whether the segment it sits on is horizontal.
    along : float
        Euclidean arc length from the source.
    """
    x: float
    y: float
    horizontal: bool
    along: float


def pneumatic_marks(points) -> "list[Hatch]":
    """Return the double cross-hatches marking a pneumatic line.

    Each segment gets one mark per whole 45 px of its Manhattan length,
    or one mark if it is 16 px or longer; the marks divide the segment
    into equal parts.

    Parameters
    ----------
    points : sequence of tuple[float, float]
        Line polyline.

    Returns
    -------
    list[Hatch]
        Marks in drawing order.
    """
    out: list[Hatch] = []
    walked = 0.0
    for i in range(len(points) - 1):
        (px1, py1), (px2, py2) = points[i], points[i + 1]
        # Manhattan length sets the spacing, Euclidean the position.
        seglen = abs(px2 - px1) + abs(py2 - py1)
        span = math.hypot(px2 - px1, py2 - py1)
        n = int(seglen // 45) or (1 if seglen >= 16 else 0)
        horiz = abs(py1 - py2) < 0.1
        for k in range(1, n + 1):
            t = k / (n + 1)
            out.append(Hatch(px1 + (px2 - px1) * t, py1 + (py2 - py1) * t,
                             horiz, walked + span * t))
        walked += span
    return out


def _hatch_strokes(points) -> list:
    """Return the strokes of every double cross-hatch on a pneumatic line.

    Parameters
    ----------
    points : sequence of tuple[float, float]
        Line polyline.

    Returns
    -------
    list[tuple[tuple[float, float], tuple[float, float]]]
        Stroke end points, in drawing order.
    """
    along, across = HATCH_ARM
    out = []
    for mx, my, horiz, _at in pneumatic_marks(points):
        for off in HATCH_ALONG:
            if horiz:
                out.append(((mx + off - along, my + across), (mx + off + along, my - across)))
            else:
                out.append(((mx - across, my + off - along), (mx + across, my + off + along)))
    return out


def hatch_boxes(fs) -> "list[tuple[float, float, float, float]]":
    """Return the box each pneumatic hatch stroke inks.

    Parameters
    ----------
    fs : Flowsheet
        Routed flowsheet.

    Returns
    -------
    list[tuple[float, float, float, float]]
        ``(x0, y0, x1, y1)`` of each stroke, grown by its half pen.
    """
    pad = _ink_pad(LineWeight.DETAIL)
    return [(min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad)
            for s in fs.streams if s.kind == "pneumatic"
            for (x1, y1), (x2, y2) in _hatch_strokes(stream_polyline(s))]


#: Joint markings where lines meet what they serve.
#:
#: * ``"none"`` -- no marks.
#: * ``"flanged"`` -- equipment nozzles and both sides of valves and
#:   fittings, except a fitting whose symbol is a flange.
#: * ``"flanged-at-nozzles"`` -- only where a line meets an equipment
#:   nozzle.
CONNECTIONS = ("none", "flanged", "flanged-at-nozzles")

# In-line kinds ``"flanged"`` can mark on both sides.
_INLINE_BODIES = frozenset({"valve", "fitting"})

#: Flanged-connection mark: two bars this long and this far apart.
FLANGE_TICK = 12.5
FLANGE_GAP = 5.0

#: Distance from the nozzle to the pair's centre along the run.
FLANGE_STANDOFF = 5.0


class Flange(NamedTuple):
    """One flanged-connection mark on a stream.

    Attributes
    ----------
    x, y : float
        Mark centre.
    angle : float
        Run direction at the mark, in degrees.
    along : float
        Arc length from the source end, as on :class:`Hatch`.
    """
    x: float
    y: float
    angle: float
    along: float


def flanged_joint(port, want: str) -> bool:
    """Return whether a joint setting marks this end of a stream.

    Boundary flags and instruments take no mark and equipment nozzles
    always take one. An in-line unit takes one only under ``"flanged"``,
    when it is a valve or fitting whose own symbol is not a flange.

    Parameters
    ----------
    port : Port
        Stream end.
    want : str
        One of :data:`CONNECTIONS`, resolved for this stream.

    Returns
    -------
    bool
        Whether this end gets a flange mark.
    """
    from pandid.flowsheet import INLINE_KINDS

    kind = port.owner.kind
    if kind in {"feed", "product", "instrument"}:
        return False
    if kind in INLINE_KINDS:
        if want != "flanged" or kind not in _INLINE_BODIES:
            return False
        own = default_registry.get(kind, getattr(port.owner, "variant", "default")).drawio_shape
        return own is None or own != default_registry.get("fitting", "flange").drawio_shape
    return True


def flange_marks(s, points, ends) -> "list[Flange]":
    """Return the flange marks one stream carries, at most one per end.

    Parameters
    ----------
    s : Stream
        Stream; a signal line carries no marks.
    points : sequence of tuple[float, float]
        The stream's drawn polyline, source end first.
    ends : tuple[str, str]
        Resolved ``(source, dest)`` settings from :data:`CONNECTIONS`.

    Returns
    -------
    list[Flange]
        Marks in drawing order.
    """
    if len(points) < 2 or s.kind in _SIGNAL_KINDS:
        return []

    spans = [math.hypot(bx - ax, by - ay)
             for (ax, ay), (bx, by) in zip(points, points[1:])]
    total = sum(spans)

    out: list[Flange] = []
    for at_dest, want in enumerate(ends):
        if want == "none":
            continue
        port = s.dest if at_dest else s.source
        if not flanged_joint(port, want):
            continue

        tip = points[-1] if at_dest else points[0]
        neighbour = points[-2] if at_dest else points[1]
        span = spans[-1] if at_dest else spans[0]

        if span < FLANGE_STANDOFF + FLANGE_GAP / 2:
            continue

        ux, uy = (neighbour[0] - tip[0]) / span, (neighbour[1] - tip[1]) / span
        cx, cy = tip[0] + ux * FLANGE_STANDOFF, tip[1] + uy * FLANGE_STANDOFF
        along = total - FLANGE_STANDOFF if at_dest else FLANGE_STANDOFF
        out.append(Flange(cx, cy, math.degrees(math.atan2(uy, ux)), along))
    return out


def flange_boxes(fs, joints) -> "list[tuple[float, float, float, float]]":
    """Return a square box around every flange mark on a sheet.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed sheet.
    joints : str or None
        :func:`sheet_connections` result.

    Returns
    -------
    list[tuple[float, float, float, float]]
        One box per mark.
    """
    half = max(FLANGE_TICK, FLANGE_GAP) / 2
    return [
        (m.x - half, m.y - half, m.x + half, m.y + half)
        for s in fs.streams
        for m in flange_marks(s, stream_polyline(s), resolve_connections(s, joints))
    ]


def _arrowhead(start, end) -> str:
    """Return path data for the arrowhead ending a leader at ``end``.

    Parameters
    ----------
    start, end : tuple[float, float]
        Last leader segment.

    Returns
    -------
    str
        SVG path data.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    bx, by = end[0] - ux * _LEADER_HEAD, end[1] - uy * _LEADER_HEAD
    px, py = -uy * _LEADER_HEAD / 2, ux * _LEADER_HEAD / 2
    return (f"M {end[0]:.1f},{end[1]:.1f} L {bx + px:.1f},{by + py:.1f} "
            f"L {bx - px:.1f},{by - py:.1f} Z")


def arrow_marker_id(color: str) -> str:
    """Return the ``<marker>`` id for an arrowhead in ``color``.

    Parameters
    ----------
    color : str
        Stroke colour; a leading ``#`` is dropped.

    Returns
    -------
    str
        Valid XML id.
    """
    return ident("arrow", color.lstrip("#"))


def _unit_label_box(item) -> "tuple[float, float, float, float] | None":
    """Return the halo rectangle of an equipment tag.

    Parameters
    ----------
    item : tuple
        ``(x, y, anchor, baseline, label_pos, text)``, text unescaped.

    Returns
    -------
    tuple[float, float, float, float] or None
        Halo box, or ``None`` for a ``center`` tag.
    """
    lx, ly, anchor, baseline, lpos, text = item
    if lpos == "center":
        return None
    hw = tag_width(text)
    hh = 15.0
    rx = lx - hw / 2 if anchor == "middle" else (lx - hw if anchor == "end" else lx)
    ry = ly - hh / 2 if baseline == "middle" else ly - hh + 3
    return (rx, ry, rx + hw, ry + hh)


def _placed_box(u) -> "tuple[float, float]":
    """Return the size a unit's artwork is drawn into, before rotation.

    Parameters
    ----------
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        ``(width, height)``.
    """
    f = u.frame
    rot = int(getattr(f, "orientation", 0) or 0)
    return (f.h, f.w) if rot in (90, 270) else (f.w, f.h)


def _reshapes(sym, u) -> bool:
    """Return whether a unit's box and symbol differ in aspect.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    bool
        Whether the aspects differ.
    """
    bw, bh = _placed_box(u)
    return not math.isclose(sym.width * bh, sym.height * bw, rel_tol=1e-9)


# --- the pen a placement draws with -----------------------------------
# _pen_scale divides a uniform placement scale out of the line weights;
# _baked rewrites artwork placed at an uneven scale.


def _placement_scale(sym, u) -> "tuple[float, float]":
    """Return the ``(sx, sy)`` a unit's ``<use>`` box applies.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        ``(sx, sy)``; ``(1, 1)`` if the symbol has no size.
    """
    if not (sym.width and sym.height):
        return (1.0, 1.0)
    box = _placed_box(u)
    return (box[0] / sym.width, box[1] / sym.height)


@lru_cache(maxsize=2048)
def _uneven(svg: str, fx: float, fy: float) -> bool:
    """Return whether any stroke in ``svg`` is scaled unevenly.

    The placement scale multiplies the artwork's own group transforms.
    A mirror is not uneven.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    fx, fy : float
        Placement scale.

    Returns
    -------
    bool
        Whether some stroke's x and y scales differ.
    """
    scales = [(fx, fy)]
    for m in _TAG.finditer(svg):
        closing, name, raw, self_closing = m.groups()
        if closing:
            scales.pop()
            continue
        ax, ay = scales[-1]
        if name == "g":
            found = re.search(r'\btransform="([^"]*)"', raw)
            if found:
                sx, sy, _, _ = _affine(found.group(1))
                ax, ay = ax * sx, ay * sy
        elif 'stroke-width="' in raw:
            if not math.isclose(abs(ax), abs(ay), rel_tol=1e-9):
                return True
        if not self_closing:
            scales.append((ax, ay))
    return False


def _fold(sym, u) -> "tuple[float, float]":
    """Return the scale to bake into a definition's coordinates.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        ``(1, 1)`` unless the placement would scale a stroke unevenly.
    """
    if not (sym.stretchable and _reshapes(sym, u)):
        return (1.0, 1.0)
    fx, fy = _placement_scale(sym, u)
    return (fx, fy) if _uneven(sym.svg, fx, fy) else (1.0, 1.0)


def _pen_scale(sym, u) -> float:
    """Return the factor a placement scales a symbol's line weights by.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    float
        Pen scale; 1 when the definition is baked.
    """
    if _fold(sym, u) != (1.0, 1.0):
        return 1.0
    kx, ky = _placement_scale(sym, u)
    if sym.stretchable and _reshapes(sym, u):
        # An uneven box that cancels the artwork's own uneven wrapper.
        return math.sqrt(kx * ky)
    return min(kx, ky)


def _at_pen_scale(svg: str, scale: float) -> str:
    """Return ``svg`` with every line weight divided by ``scale``.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    scale : float
        Pen scale from :func:`_pen_scale`.

    Returns
    -------
    str
        Rewritten artwork.
    """
    if scale == 1.0:
        return svg
    return _STROKE.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


# --- baking an uneven scale into the drawing --------------------------
# The artwork is rewritten at the placed size, one definition per
# size (ISO 15519-1 11.1.3).

# A point takes scale and translation; a length takes the unsigned scale
# only. ``r`` is handled separately.
_X_POINTS = {"x", "x1", "x2", "cx"}
_Y_POINTS = {"y", "y1", "y2", "cy"}
_X_LENGTHS = {"rx", "width"}
_Y_LENGTHS = {"ry", "height"}

_TAG = re.compile(r'<(/?)([A-Za-z][\w.-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*(/?)>')
_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')
# Supported absolute path commands and their argument counts.
_PATH_ARITY = {"M": 2, "L": 2, "C": 6, "A": 7, "Z": 0, "z": 0}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _affine(transform: str) -> "tuple[float, float, float, float]":
    """Return a symbol transform as the map ``(sx, sy, tx, ty)``.

    Parameters
    ----------
    transform : str
        SVG ``transform`` attribute.

    Returns
    -------
    tuple[float, float, float, float]
        Scale and translation.

    Raises
    ------
    RuntimeError
        If the transform contains a rotation, skew or other operation.
    """
    sx = sy = 1.0
    tx = ty = 0.0
    for op, args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", transform):
        v = [float(t) for t in args.replace(",", " ").split()]
        if op == "translate":
            tx += sx * v[0]
            ty += sy * (v[1] if len(v) > 1 else 0.0)
        elif op == "scale":
            sx, sy = sx * v[0], sy * v[-1]
        else:
            raise RuntimeError(
                f"a symbol carries transform={transform!r}, whose {op}() is not "
                f"axis-aligned; pandid.render.svg._baked needs to learn it."
            )
    return (sx, sy, tx, ty)


def _scaled_ellipse(rx: float, ry: float, rot: float,
                    ax: float, ay: float) -> "tuple[float, float, float]":
    """Return ``(rx, ry, rot)`` of an ellipse after ``scale(ax, ay)``.

    Uses the singular value decomposition of
    ``diag(ax, ay) R(rot) diag(rx, ry)``.

    Parameters
    ----------
    rx, ry : float
        Radii.
    rot : float
        Tilt in degrees.
    ax, ay : float
        Scale.

    Returns
    -------
    tuple[float, float, float]
        New radii and tilt.
    """
    if ax == ay:
        return rx * ax, ry * ay, rot
    r = math.radians(rot)
    cos, sin = math.cos(r), math.sin(r)
    a, b = ax * cos * rx, -ax * sin * ry
    c, d = ay * sin * rx, ay * cos * ry
    e, f = (a + d) / 2, (a - d) / 2
    g, h = (c + b) / 2, (c - b) / 2
    q, s = math.hypot(e, h), math.hypot(f, g)
    return abs(q + s), abs(q - s), math.degrees((math.atan2(h, e) + math.atan2(g, f)) / 2)


def _scaled_path(d: str, m: "tuple[float, float, float, float]") -> str:
    """Return path data ``d`` with the map ``(sx, sy, tx, ty)`` applied.

    Parameters
    ----------
    d : str
        Path data using commands from ``_PATH_ARITY``.
    m : tuple[float, float, float, float]
        ``(sx, sy, tx, ty)``.

    Returns
    -------
    str
        Mapped path data.

    Raises
    ------
    RuntimeError
        If the path uses an unsupported command.
    """
    ax, ay, ex, ey = m
    tokens = _PATH_TOKEN.findall(d)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        arity = _PATH_ARITY.get(cmd)
        if arity is None:
            raise RuntimeError(
                f"path command {cmd!r} is not one pandid.render.svg._baked can scale"
            )
        nums = [float(v) for v in tokens[i + 1: i + 1 + arity]]
        out.append(cmd)
        if cmd == "A":
            rx, ry, rot = _scaled_ellipse(nums[0], nums[1], nums[2], ax, ay)
            # A mirror reverses the sweep flag.
            sweep = int(nums[4]) if ax * ay > 0 else 1 - int(nums[4])
            out += [fmt(rx, 6), fmt(ry, 6), fmt(rot, 6), str(int(nums[3])), str(sweep),
                    fmt(nums[5] * ax + ex, 6), fmt(nums[6] * ay + ey, 6)]
        else:
            out += [fmt(n * ax + ex if k % 2 == 0 else n * ay + ey, 6)
                    for k, n in enumerate(nums)]
        i += 1 + arity
    return " ".join(out)


def _scaled_element(name: str, attrs: "list[tuple[str, str]]",
                    m: "tuple[float, float, float, float]",
                    gx: float, gy: float, self_closing: str) -> str:
    """Return one drawn element rewritten under the map ``m``.

    A circle becomes an ellipse. Stroke widths keep their nominal
    weight (ISO 15519-1 11.1.3).

    Parameters
    ----------
    name : str
        Element name.
    attrs : list[tuple[str, str]]
        Attributes in source order.
    m : tuple[float, float, float, float]
        Accumulated ``(sx, sy, tx, ty)``.
    gx, gy : float
        Artwork's own share of the scale.
    self_closing : str
        Non-empty if the tag self-closes.

    Returns
    -------
    str
        Rewritten tag.
    """
    ax, ay, ex, ey = m
    src = dict(attrs)
    # Map both ends of a rect and take the lower, for mirrors.
    corner = {}
    if name == "rect":
        for axis, span, s, e in (("x", "width", ax, ex), ("y", "height", ay, ey)):
            lo = float(src.get(axis, 0)) * s + e
            corner[axis] = min(lo, lo + float(src.get(span, 0)) * s)
    out: list[tuple[str, str]] = []
    for key, value in attrs:
        if key == "stroke-width":
            # The geometric mean of the scale keeps the sheet weight.
            out.append(("stroke-width", fmt(float(value) * math.sqrt(abs(gx * gy)), 6)))
        elif key == "d":
            out.append((key, _scaled_path(value, m)))
        elif key == "points":
            v = [float(t) for t in value.replace(",", " ").split()]
            out.append((key, " ".join(f"{fmt(v[i] * ax + ex, 6)},{fmt(v[i + 1] * ay + ey, 6)}"
                                      for i in range(0, len(v), 2))))
        elif key == "font-size":
            # Scale text by the geometric mean.
            out.append((key, fmt(math.sqrt(abs(ax * ay)) * float(value), 6)))
        elif key == "r":
            out.append(("rx", fmt(abs(float(value) * ax), 6)))
            out.append(("ry", fmt(abs(float(value) * ay), 6)))
            name = "ellipse"
        elif key in corner:
            out.append((key, fmt(corner[key], 6)))
        elif key in _X_LENGTHS:
            out.append((key, fmt(abs(float(value) * ax), 6)))
        elif key in _Y_LENGTHS:
            out.append((key, fmt(abs(float(value) * ay), 6)))
        elif key in _X_POINTS:
            out.append((key, fmt(float(value) * ax + ex, 6)))
        elif key in _Y_POINTS:
            out.append((key, fmt(float(value) * ay + ey, 6)))
        else:
            out.append((key, value))
    written = "".join(f' {k}="{v}"' for k, v in out)
    return f"<{name}{written}{'/' if self_closing else ''}>"


def _baked(svg: str, fx: float, fy: float) -> str:
    """Return ``svg`` redrawn at ``scale(fx, fy)``, groups flattened.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    fx, fy : float
        Placement scale.

    Returns
    -------
    str
        Flattened artwork, or ``svg`` unchanged for an even scale.
    """
    if not _uneven(svg, fx, fy):
        return svg
    out: list[str] = []
    pos = 0
    maps = [(fx, fy, 0.0, 0.0)]  # accumulated map, innermost last
    elided: list[bool] = []      # whether an open tag is dropped
    for m in _TAG.finditer(svg):
        out.append(svg[pos:m.start()])
        pos = m.end()
        closing, name, raw, self_closing = m.groups()
        if closing:
            if not elided.pop():
                out.append(m.group(0))
            maps.pop()
            continue
        here = maps[-1]
        attrs = _ATTR.findall(raw)
        if name == "g":
            kept = [(k, v) for k, v in attrs if k != "transform"]
            for _, value in [a for a in attrs if a[0] == "transform"]:
                ax, ay, ex, ey = here
                sx, sy, tx, ty = _affine(value)
                here = (ax * sx, ay * sy, ax * tx + ex, ay * ty + ey)
            # Drop a group that carried only the transform.
            if not self_closing:
                maps.append(here)
                elided.append(not kept)
            if kept:
                written = "".join(f' {k}="{v}"' for k, v in kept)
                out.append(f"<g{written}{'/' if self_closing else ''}>")
            continue
        out.append(_scaled_element(name, attrs, here, here[0] / fx, here[1] / fy,
                                   self_closing))
        if not self_closing:
            maps.append(here)
            elided.append(False)
    out.append(svg[pos:])
    return "".join(out)


def _upright_text(svg: str, rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Return ``svg`` with its text kept upright under a placement.

    Each text element is wrapped in the inverse transform about its own
    centre.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    rot : int
        Rotation in degrees.
    mirror_x, mirror_y : bool
        Mirrors applied by the placement.

    Returns
    -------
    str
        Artwork with each text element wrapped.
    """
    if not (rot or mirror_x or mirror_y):
        return svg

    def wrap(match: "re.Match[str]") -> str:
        """Return one text element wrapped in the inverse transform.

        Parameters
        ----------
        match : re.Match[str]
            Text element and its ``x`` and ``y``.

        Returns
        -------
        str
            Wrapped element.
        """
        tx, ty = float(match.group(1)), float(match.group(2))
        # Pivot on the glyph centre, about 0.35 em above the baseline.
        size = re.search(r'font-size="(-?[\d.]+)"', match.group(0))
        cy = ty - 0.35 * float(size.group(1) if size else 12.0)
        # Undo in the reverse of the order the <use> applies them.
        ops = []
        if mirror_x:
            ops.append(f"translate({fmt(2 * tx, 2)}, 0) scale(-1, 1)")
        if mirror_y:
            ops.append(f"translate(0, {fmt(2 * cy, 2)}) scale(1, -1)")
        if rot:
            ops.append(f"rotate({-rot}, {fmt(tx, 2)}, {fmt(cy, 2)})")
        return f'<g transform="{" ".join(ops)}">{match.group(0)}</g>'

    return _SYMBOL_TEXT.sub(wrap, svg)


def _reflections(rot: int, mirror_x: bool, mirror_y: bool) -> "tuple[bool, bool]":
    """Return a placement's net x and y flips.

    A half turn counts as both mirrors; quarter turns add none.

    Parameters
    ----------
    rot : int
        Rotation in degrees.
    mirror_x, mirror_y : bool
        Mirrors applied.

    Returns
    -------
    tuple[bool, bool]
        Net x and y flips.
    """
    half = rot == 180
    return (mirror_x != half, mirror_y != half)


def _upright_artwork(svg: str, w: float, h: float,
                     mirror_x: bool, mirror_y: bool) -> str:
    """Return directional artwork with a placement flip undone in it.

    The flip is undone about the symbol's centre lines in an inner
    group.

    Parameters
    ----------
    svg : str
        Symbol artwork, wrapped in an outer ``<g>``.
    w, h : float
        Symbol size.
    mirror_x, mirror_y : bool
        Net flips from :func:`_reflections`.

    Returns
    -------
    str
        Artwork with an inner counter-flip group.
    """
    if not (mirror_x or mirror_y) or not svg.startswith("<g"):
        return svg
    ops = []
    if mirror_x:
        ops.append(f"translate({fmt(w, 2)}, 0) scale(-1, 1)")
    if mirror_y:
        ops.append(f"translate(0, {fmt(h, 2)}) scale(1, -1)")
    head, inner = svg[:svg.find(">") + 1], svg[svg.find(">") + 1:svg.rfind("</g>")]
    return f'{head}<g transform="{" ".join(ops)}">{inner}</g></g>'


# ISO 216 page sizes in millimetres, landscape.
_PAGE_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}

# Layout units are CSS pixels, 1/96 inch.
_PX_PER_MM = 96.0 / 25.4


class _Sheet(NamedTuple):
    """A fixed sheet the drawing is placed on.

    Attributes
    ----------
    name : str
        Page size name, such as ``"A3"``.
    width_mm, height_mm : float
        Physical size the SVG declares.
    """
    name: str
    width_mm: float
    height_mm: float

    @property
    def width(self) -> float:
        """Return the sheet width.

        Returns
        -------
        float
            Width in layout units (CSS px).
        """
        return self.width_mm * _PX_PER_MM

    @property
    def height(self) -> float:
        """Return the sheet height.

        Returns
        -------
        float
            Height in layout units (CSS px).
        """
        return self.height_mm * _PX_PER_MM


def _page(page_size: "str | None") -> "_Sheet | None":
    """Return the fixed sheet for a page size.

    Parameters
    ----------
    page_size : str or None
        ISO A-size name, any case; ``None`` fits the drawing.

    Returns
    -------
    _Sheet or None
        Sheet, or ``None`` to fit.

    Raises
    ------
    ValueError
        If the size is unknown.
    """
    if page_size is None:
        return None
    dims = _PAGE_SIZES.get(page_size.upper())
    if dims is None:
        raise ValueError(
            f"Unknown page size {page_size!r}; use one of {', '.join(_PAGE_SIZES)}, "
            "or omit page_size to fit the sheet to the drawing."
        )
    return _Sheet(page_size.upper(), *dims)


_BORDERS = ("none", "zone")
# Accepted spellings of each diagram kind (ISO 10628-1 4.2 to 4.4).
_ALIASES = {"pid": "p&id", "p&id": "p&id", "pfd": "pfd", "bfd": "bfd"}


def _resolve_sheet(border: "str | None", diagram: "str | None") -> "tuple[str, str]":
    """Return the validated ``(border, diagram)``.

    Parameters
    ----------
    border : str or None
        ``"none"`` or ``"zone"``; ``None`` means ``"none"``.
    diagram : str or None
        ``"pfd"``, ``"p&id"``, ``"pid"`` or ``"bfd"``, in any case;
        ``None`` is ``"pfd"``.

    Returns
    -------
    tuple[str, str]
        ``(border, diagram)``.

    Raises
    ------
    ValueError
        If either name is unknown.
    """
    if border is None:
        border = "none"
    elif border not in _BORDERS:
        raise ValueError(
            f"Unknown border {border!r}; use one of {', '.join(_BORDERS)}."
        )

    if diagram is None:
        return border, "pfd"
    kind = _ALIASES.get(diagram.strip().lower())
    if kind is None:
        raise ValueError(
            f"Unknown diagram {diagram!r}; use 'pfd', "
            f"'p&id' (also spelled 'pid') or 'bfd'."
        )
    return border, kind


#: ``show_stream_table`` value that draws the table as its own sheet.
TABLE_SHEET = "sheet"


def wants_table_sheet(show_stream_table) -> bool:
    """Return whether ``show_stream_table`` is ``"sheet"``.

    Parameters
    ----------
    show_stream_table : bool, str or None
        ``False``, ``True`` or ``"sheet"``.

    Returns
    -------
    bool
        True for ``"sheet"``.

    Raises
    ------
    ValueError
        If the value is not a bool, ``None`` or ``"sheet"``.
    """
    if isinstance(show_stream_table, bool) or show_stream_table is None:
        return False
    if show_stream_table == TABLE_SHEET:
        return True
    raise ValueError(
        f"show_stream_table={show_stream_table!r}: the table is drawn on the "
        f"diagram (True), left off it (False), or given a sheet of its own "
        f'("{TABLE_SHEET}"). Nothing else is a place to put it.'
    )


def draws_arrowheads(diagram: "str | None") -> bool:
    """Return whether a diagram kind draws arrowheads on process lines.

    Parameters
    ----------
    diagram : str or None
        ``"pfd"`` (or ``None``), ``"p&id"``, ``"pid"`` or ``"bfd"``.

    Returns
    -------
    bool
        False only for a P&ID.

    Raises
    ------
    ValueError
        If the diagram name is unknown.
    """
    return _resolve_sheet(None, diagram)[1] != "p&id"


def tabulates_boundary_flows(diagram: "str | None") -> bool:
    """Return whether a diagram must state boundary flow rates.

    Parameters
    ----------
    diagram : str or None
        ``"pfd"`` (or ``None``), ``"p&id"``, ``"pid"`` or ``"bfd"``.

    Returns
    -------
    bool
        True only for a PFD (ISO 10628-1 4.3.2 d)).

    Raises
    ------
    ValueError
        If the diagram name is unknown.
    """
    return _resolve_sheet(None, diagram)[1] == "pfd"


def check_connections(value) -> None:
    """Check a ``connections`` value against :data:`CONNECTIONS`.

    Parameters
    ----------
    value : str or Sequence[str]
        One name, or a stream's ``(source, dest)`` pair.

    Raises
    ------
    ValueError
        If any name is unknown.
    """
    for name in ((value,) if isinstance(value, str) else tuple(value)):
        if name not in CONNECTIONS:
            raise ValueError(
                f"Unknown connections {name!r}; use one of "
                f"{', '.join(CONNECTIONS)}."
            )


#: Which of two crossing lines is the one that hops the other.
JUMP_DIRECTIONS = ("vertical", "horizontal")


def check_jump_direction(value) -> None:
    """Check a ``jump_direction`` value against :data:`JUMP_DIRECTIONS`.

    Parameters
    ----------
    value : str
        ``"vertical"`` or ``"horizontal"``.

    Raises
    ------
    ValueError
        If the value is unknown.
    """
    if value not in JUMP_DIRECTIONS:
        raise ValueError(
            f"Unknown jump_direction {value!r}; use one of "
            f"{', '.join(JUMP_DIRECTIONS)}."
        )


def check_crossing_style(value) -> None:
    """Check a ``crossing_style`` value against :data:`CROSSING_STYLES`.

    Parameters
    ----------
    value : str
        ``"arc"``, ``"gap"`` or ``"plain"``.

    Raises
    ------
    ValueError
        If the value is unknown.
    """
    if value not in CROSSING_STYLES:
        raise ValueError(
            f"Unknown crossing_style {value!r}; use one of "
            f"{', '.join(repr(name) for name in CROSSING_STYLES)}."
        )


def sheet_connections(diagram: "str | None",
                      connections: "str | None") -> "str | None":
    """Return the joint marking a sheet uses by default.

    Only a P&ID marks joints (ISO 15519-2 Table 5).

    Parameters
    ----------
    diagram : str or None
        ``"pfd"`` (or ``None``), ``"p&id"``, ``"pid"`` or ``"bfd"``.
    connections : str or None
        One of :data:`CONNECTIONS`; ``None`` means ``"none"``.

    Returns
    -------
    str or None
        ``connections`` or ``"none"`` on a P&ID, else ``None``.

    Raises
    ------
    ValueError
        If ``connections`` or ``diagram`` is unknown.
    """
    if connections is not None:
        check_connections(connections)
    if _resolve_sheet(None, diagram)[1] != "p&id":
        return None
    return connections or "none"


def resolve_connections(s, default: "str | None") -> "tuple[str, str]":
    """Return a stream's joint settings as ``(source, dest)``.

    Parameters
    ----------
    s : Stream
        Stream; a set ``ends`` wins over ``default``.
    default : str or None
        :func:`sheet_connections` result; ``None`` gives
        ``("none", "none")`` whatever ``s.ends`` says.

    Returns
    -------
    tuple[str, str]
        Settings for the source and destination ends.
    """
    if default is None:
        return ("none", "none")
    ends = getattr(s, "ends", None) or default
    return (ends, ends) if isinstance(ends, str) else (ends[0], ends[1])


def _fitted(inner, free) -> "tuple[float, float, float]":
    """Return the scale, at most 1, and offset centring a drawing in ``free``.

    Parameters
    ----------
    inner : tuple[float, float, float, float]
        Drawing bounds ``(x0, y0, x1, y1)``.
    free : tuple[float, float, float, float]
        Region ``(x, y, w, h)`` left for the drawing.

    Returns
    -------
    tuple[float, float, float]
        ``(scale, offset_x, offset_y)``.
    """
    dx0, dy0, dx1, dy1 = inner
    fx, fy, fw, fh = free
    dw, dh = dx1 - dx0, dy1 - dy0
    s = min(1.0, fw / dw if dw > 0 else 1.0, fh / dh if dh > 0 else 1.0)
    return (s, fx + (fw - s * dw) / 2 - s * dx0, fy + (fh - s * dh) / 2 - s * dy0)


def unit_tags(fs, joints: "str | None", direction: str) -> list:
    """Place each unit's tag and its ``NC`` and fail-position letters.

    The labels keep clear of the drawn lines, the symbols, the flange
    marks, the quadrant codes, the package frames and each other. Tags
    placed again with leave to step out from their face are kept only if
    no unit then erases more of any ink, and no more labels overlap, than
    without.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed flowsheet.
    joints : str or None
        Sheet joint default, whose flange marks the labels avoid.
    direction : str
        ``jump_direction``.

    Returns
    -------
    list[tuple]
        ``(unit, tag, items)`` for each unit labelled beside its symbol:
        the tag item or ``None``, and every label item, tag first.
    """
    sheet = SvgRenderer()
    ink = _ink(fs, direction)
    hatches = hatch_boxes(fs)
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    symbols += [(None, b) for b in flange_boxes(fs, joints)]
    symbols += [(None, m.box) for m in pipe_marks(fs)]
    symbols += [(None, b) for b in map(_unit_label_box, quadrant_labels(fs, direction))
                if b is not None]
    symbols += [(None, b) for b in package_edges(fs)]

    from pandid.render.drawio import label_box

    def drawn(u, tag, items) -> "tuple[list, list]":
        """Return a unit's label boxes as the sheet and draw.io draw them.

        Parameters
        ----------
        u : Unit
            Unit the labels belong to.
        tag : tuple or None
            Its tag item.
        items : list
            Its label items.

        Returns
        -------
        tuple[list, list]
            The sheet's halos, then draw.io's boxes.
        """
        halos = [b for b in map(_unit_label_box, items) if b is not None]
        block = label_box(u, tag, items)
        return halos, halos if block is None else [block]

    def cost(u, boxes, others) -> "list[int]":
        """Return what boxes erase, then the other labels they cover.

        Parameters
        ----------
        u : Unit
            Unit the boxes belong to.
        boxes : list
            Its label boxes.
        others : list
            Other units' label boxes.

        Returns
        -------
        list[int]
            Symbols, impulse lines, pipes and labels.
        """
        obstacles = [_obstacle(b) for v, b in symbols if v is not u]
        return [sum(n) for n in zip((0, 0, 0, 0), *(
            (*_erases(b, ink, obstacles), sum(1 for o in others if boxes_overlap(b, o)))
            for b in boxes))]

    def worse(u, now, was, others) -> bool:
        """Return whether new labels erase or cover more of anything.

        Parameters
        ----------
        u : Unit
            Unit the labels belong to.
        now, was : tuple[list, list]
            Its new and old boxes from ``drawn``.
        others : list
            Other units' boxes from ``drawn``.

        Returns
        -------
        bool
            True if either drawing is worse in any count.
        """
        for k in (0, 1):
            rest = [b for o in others for b in o[k]]
            if any(a > b for a, b in zip(cost(u, now[k], rest), cost(u, was[k], rest))):
                return True
        return False

    def place(step_out: bool) -> "tuple[dict, dict]":
        """Place every unit's labels alone, then again off the others.

        The second time, a unit takes the first spot no worse in either
        drawing than its first placement, against the others as they
        stand.

        Parameters
        ----------
        step_out : bool
            Whether tags may step out from the face, trying their spots
            in turn.

        Returns
        -------
        tuple[dict, dict]
            ``id(unit)`` -> ``(unit, tag, items)``, and -> its boxes from
            ``drawn``.
        """
        placed: dict = {}
        shown: dict = {}
        for alone in (True, False):
            for u in fs.units:
                f = u.frame
                if f is None or u.kind in ("feed", "product", "instrument"):
                    continue
                x, y, w, h = f.x, f.y, f.w, f.h
                others = [o for k, o in shown.items() if k != id(u)]
                labels = None if alone else [b for o in others for b in o[0]]
                spots = (sheet._tag_spots(u, f, x, y, w, h, u.tag, ink, symbols, labels,
                                          hatches, step_out) if u.tag else [None])
                if not step_out:
                    spots = list(dict.fromkeys([spots[0], spots[-1]]))
                for tag in spots:
                    tag_box = None if tag is None else _unit_label_box(tag)
                    items = [] if tag is None else [tag]
                    # NC marking (ISO 15519-1 11.4.5).
                    if closed_marking(u, default_registry) == "NC":
                        items.append(sheet._nc_label_item(u, f, x, y, w, h, tag_box))
                    # Fail position (ISA-5.1 Table 5.4.4).
                    letters = fail_marking(u)
                    if letters:
                        items.append(sheet._fail_label_item(u, f, x, y, w, h, letters,
                                                            tag_box, ink, symbols))
                    now = drawn(u, tag, items)
                    if alone or not worse(u, now, shown[id(u)], others):
                        placed[id(u)] = (u, tag, items)
                        shown[id(u)] = now
                        break
        return placed, shown

    def overlaps(shown, k) -> int:
        """Return how many pairs of units' labels overlap in one drawing.

        Parameters
        ----------
        shown : dict
            ``id(unit)`` -> its boxes from ``drawn``.
        k : int
            ``0`` for the sheet, ``1`` for draw.io.

        Returns
        -------
        int
            Overlapping pairs.
        """
        boxes = list(shown.values())
        return sum(1 for i, a in enumerate(boxes) for b in boxes[i + 1:]
                   if any(boxes_overlap(p, q) for p in a[k] for q in b[k]))

    # Keep the stepped-out placement only if it is no worse than the plain
    # one in either drawing: no unit erasing more of any ink, no more pairs
    # of labels overlapping.
    plain, plain_shown = place(False)
    stepped, stepped_shown = place(True)
    for k in (0, 1):
        if overlaps(stepped_shown, k) > overlaps(plain_shown, k):
            return list(plain.values())
        for key, (u, _tag, _items) in plain.items():
            if any(a > b for a, b in zip(cost(u, stepped_shown[key][k], [])[:3],
                                         cost(u, plain_shown[key][k], [])[:3])):
                return list(plain.values())
    return list(stepped.values())


def drawing_bounds(fs, labels=()) -> "tuple[float, float, float, float]":
    """Return the box round the units, labels, routes and package frames.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    labels : sequence of tuple, optional
        Boxes ``(x0, y0, x1, y1)`` of the labels drawn beside units.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x0, y0, x1, y1)``; zeros for an empty flowsheet.

    Raises
    ------
    ValueError
        If a unit has no frame.
    """
    if not fs.units:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for u in fs.units:
        if u.frame is None:
            raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
    for bx0, by0, bx1, by1 in (*(unit_box(u, u.frame) for u in fs.units), *labels):
        x0, y0 = min(x0, bx0), min(y0, by0)
        x1, y1 = max(x1, bx1), max(y1, by1)
    for s in fs.streams:
        if s.route and s.route.waypoints:
            for px, py in s.route.waypoints:
                x0, y0 = min(x0, px), min(y0, py)
                x1, y1 = max(x1, px), max(y1, py)
    for pkg in fs.packages:
        frame = package_frame(pkg)
        assert frame is not None
        for bx0, by0, bx1, by1 in (frame, *(b for b in map(_unit_label_box,
                                                           package_labels(pkg, frame))
                                            if b is not None)):
            x0, y0 = min(x0, bx0), min(y0, by0)
            x1, y1 = max(x1, bx1), max(y1, by1)
    return (x0, y0, x1, y1)


def package_edges(fs) -> "list[tuple[float, float, float, float]]":
    """Return the four sides of each package's frame as boxes.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.

    Returns
    -------
    list[tuple[float, float, float, float]]
        ``(x0, y0, x1, y1)`` of each side, as thin as its line.
    """
    out = []
    for pkg in fs.packages:
        frame = package_frame(pkg)
        if frame is None:
            continue
        x0, y0, x1, y1 = frame
        out += [(x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)]
    return out


def package_labels(pkg, box) -> list:
    """Return a package's tag and reference as label items.

    The tag stands outside the frame's upper-left corner (ISO 15519-1
    7.3.3) and the reference inside its lower-left corner (7.3.2).

    Parameters
    ----------
    pkg : Package
        Package being drawn.
    box : tuple[float, float, float, float]
        Its frame from :func:`pandid.package.frame`.

    Returns
    -------
    list[tuple]
        ``(x, y, anchor, baseline, side, text)`` items.
    """
    x0, y0, _, y1 = box
    items = [(x0, y0 - _PACKAGE_RISE, "start", "baseline", "top", pkg.name)]
    if pkg.reference:
        items.append((x0 + _PACKAGE_INSET, y1 - _PACKAGE_INSET, "start", "baseline",
                      "bottom", str(pkg.reference)))
    return items


def _scale_text(s: float) -> str:
    """Return a fit scale as a ratio, such as ``"1:2.5"``.

    Parameters
    ----------
    s : float
        Drawing scale.

    Returns
    -------
    str
        Ratio text.
    """
    return "1:1" if s >= 1.0 else f"1:{1 / s:.3g}"


# Renderer findings about text that did not fit its cell.
_FIT_CODES = ("text-truncated", "text-overruns-cell")

#: Finding code for a stream-table sheet with no drawing number.
TABLE_SHEET_UNNUMBERED = "table-sheet-unnumbered"



def fit_issue(field: str, text: str, drawn: str,
              room: float, need: float) -> Issue:
    """Return a text-fit finding for one title-strip or furniture cell.

    Parameters
    ----------
    field : str
        Field name.
    text : str
        Value given.
    drawn : str
        Value drawn.
    room, need : float
        Cell width and text width, in drawing units.

    Returns
    -------
    Issue
        ``text-truncated`` if ``drawn`` differs from ``text``, else
        ``text-overruns-cell``.
    """
    # Omit the ratio when the cell has no width.
    span = (f"needs {need:.0f} of the {room:.0f} units its cell has"
            + (f" ({need / room:.1f}x)" if room > 0 else ""))
    if drawn != text:
        return Issue("warning", "text-truncated",
                     f"{field} was truncated to fit its cell: "
                     f"{text!r} {span}, drawn as {drawn!r}")
    return Issue("warning", "text-overruns-cell",
                 f"{field} is wider than the cell it is drawn in: "
                 f"{text!r} {span}")


def _too_small(sheet: _Sheet, need_w: float, need_h: float,
               cause: str = "") -> ValueError:
    """Return the error for a sheet too small for its furniture.

    Parameters
    ----------
    sheet : _Sheet
        Fixed sheet.
    need_w, need_h : float
        Space the furniture needs, in px.
    cause : str, default=""
        Name of the widest piece.

    Returns
    -------
    ValueError
        Error naming the sheet and the space needed.
    """
    blame = f" The widest piece is {cause}." if cause else ""
    return ValueError(
        f"The sheet furniture does not fit page size {sheet.name}: the border, title strip "
        f"and docked boxes need at least {need_w:.0f}x{need_h:.0f}px of the "
        f"{sheet.width:.0f}x{sheet.height:.0f}px sheet.{blame} Use a larger page_size, or omit "
        "page_size to fit the sheet to the drawing."
    )


# Sentinel for the title strip among docked furniture.
TITLE = "\x00title"


def _furniture_name(obj) -> str:
    """Return a readable name for a piece of furniture, for errors.

    Parameters
    ----------
    obj : object
        Title sentinel, stream table or annotation box.

    Returns
    -------
    str
        Name such as ``"the stream table"``.
    """
    if obj is TITLE:
        return "the title strip"
    if isinstance(obj, F.StreamTable):
        return "the stream table"
    title = getattr(obj, "title", "")
    return f"the {title!r} box" if title else "an untitled annotation box"


#: Comments fencing the provenance block.
PROVENANCE_OPEN = "  <!-- pandid:provenance -->"
PROVENANCE_CLOSE = "  <!-- /pandid:provenance -->"

_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _sheet_title(fs: "Flowsheet") -> str:
    """Return the title block's title, else the flowsheet name.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        Stripped title; empty when neither is stated.
    """
    tb = fs.title_block
    title = F._field(tb, "title") if tb is not None else ""
    return title or str(fs.name or "").strip()


def _provenance(fs: "Flowsheet", title: "str | None" = None) -> list[str]:
    """Return the ``<title>`` and provenance lines of an SVG document.

    Provenance is a comment and a ``<metadata>`` block with
    ``dc:creator`` and ``dc:title``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    title : str, optional
        Title to use instead of :func:`_sheet_title`.

    Returns
    -------
    list[str]
        Indented SVG lines.
    """
    from pandid.render import HOMEPAGE, generator
    who = generator()
    if title is None:
        title = _sheet_title(fs)
    lines = []
    if title:
        lines.append(f"  <title>{escaped(title)}</title>")
    lines.append(PROVENANCE_OPEN)
    lines.append(f"  <!-- Generated by {who}: {HOMEPAGE} -->")
    lines.append("  <metadata>")
    lines.append(f'    <rdf:RDF xmlns:rdf="{_RDF_NS}" xmlns:dc="{_DC_NS}">')
    # rdf:about="" means this document.
    lines.append('      <rdf:Description rdf:about="">')
    lines.append(f"        <dc:creator>{escaped(who)}</dc:creator>")
    if title:
        lines.append(f"        <dc:title>{escaped(title)}</dc:title>")
    lines.append("      </rdf:Description>")
    lines.append("    </rdf:RDF>")
    lines.append("  </metadata>")
    lines.append(PROVENANCE_CLOSE)
    return lines


def _document(fs: "Flowsheet", sheet: "_Sheet | None",
              viewbox: "tuple[float, float, float, float]",
              body: list[str], title: "str | None" = None) -> str:
    """Return a complete SVG document around a sheet's ink.

    A fixed page declares its size in millimetres; a fitted sheet in
    user units.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    sheet : _Sheet or None
        Fixed page, or ``None`` when fitted to the drawing.
    viewbox : tuple[float, float, float, float]
        Canvas rectangle in drawing units.
    body : list[str]
        Ink lines.
    title : str, optional
        Title passed to :func:`_provenance`.

    Returns
    -------
    str
        SVG source.
    """
    x, y, w, h = viewbox
    if sheet is not None:
        decl_w, decl_h = f"{sheet.width_mm:g}mm", f"{sheet.height_mm:g}mm"
    else:
        decl_w, decl_h = f"{w:.0f}", f"{h:.0f}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{decl_w}" height="{decl_h}" '
        f'viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}">',
    ]
    # Title and provenance come first.
    lines.extend(_provenance(fs, title))
    lines.append('  <!-- Background -->')
    lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="white" />')
    lines.extend(body)
    lines.append('</svg>')
    return "\n".join(lines)


class TableSheetPlan(NamedTuple):
    """Stream-table sheet geometry, shared by both backends.

    Attributes
    ----------
    table : TableSheet
        Wrapped table.
    block : TitleBlock
        What the title strip says.
    name, date : str
        Strip name and date.
    strip : tuple[float, float, float, float]
        Strip rectangle.
    frame : tuple[float, float, float, float]
        Drawing frame the border is ruled on.
    left, top : float
        Corner the table blocks are drawn from.
    findings : list[Issue]
        Warnings for the backend to report.
    """
    table: "F.TableSheet"
    block: "TitleBlock"
    name: str
    date: str
    strip: "tuple[float, float, float, float]"
    frame: "tuple[float, float, float, float]"
    left: float
    top: float
    findings: list


def table_sheet_plan(fs, sheet: "_Sheet | None",
                     diagram: "str | None" = None) -> TableSheetPlan:
    """Lay out the stream table's own sheet.

    Wrap the table to the page, dock the title strip and frame both.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    sheet : _Sheet or None
        Fixed page, or ``None`` to fit the sheet to the table.
    diagram : str or None, optional
        Diagram type the table belongs to; ``None`` is a PFD.

    Returns
    -------
    TableSheetPlan
        Layout and findings.

    Raises
    ------
    ValueError
        If nothing is tabulated, or the page is too small for the table
        or strip.
    """
    from pandid.document import TABLE_SHEET_SUFFIX, table_sheet_block

    # Wrap to the frame width less the dock clearance.
    room = None if sheet is None else (
        sheet.width - 2 * (F.OUTER_MARGIN + F.ZONE_BAND) - 2 * F.INNER)
    table = F.stream_table_sheet(fs, room, diagram)
    if table is None:
        raise ValueError(
            "show_stream_table='sheet' draws a sheet whose body is the stream "
            "table, and this flowsheet has nothing to tabulate: no stream "
            "states a property. Put properties on the streams "
            "(stream.properties = {...}), or drop the table sheet")
    block = table_sheet_block(fs.title_block, F._options(fs))
    ts_w, ts_h = F.measure_title_strip(block)
    items = [(TITLE, "bottom-right", ts_w, ts_h)]
    inner = (0.0, 0.0, table.w, table.h)
    if sheet is None:
        placed, frame, free = F.dock(items, inner)
    else:
        page = sheet
        placed, frame, free = F.dock(
            items, inner, sheet=page,
            too_small=lambda need_w, need_h, culprit: _too_small(
                page, need_w, need_h,
                _furniture_name(culprit) if culprit else ""))
        assert free is not None
        _fx, _fy, fw, fh = free
        if table.w > fw or table.h > fh:
            raise _too_small(page, page.width - fw + table.w,
                             page.height - fh + table.h, "the stream table")
    _obj, sx, sy, sw, sh = placed[0]
    # Centre the block stack across the region a fixed page leaves.
    left, top = (0.0, 0.0) if free is None else (free[0] + (free[2] - table.w) / 2, free[1])
    date = block.date or datetime.now().strftime("%Y-%m-%d")
    findings = []
    if not block.drawing_number:
        findings.append(Issue(
            "warning", TABLE_SHEET_UNNUMBERED,
            f"the stream table sheet for {fs.name!r} carries no drawing "
            f"number, so nothing on it says which drawing it belongs to but "
            f"its title. Give the diagram one -- "
            f"fs.title_block = TitleBlock(drawing_number='PFD-301') -- and the "
            f"table sheet takes it with {TABLE_SHEET_SUFFIX!r} after it, or "
            f"number the table sheet alone with "
            f"fs.stream_table.sheet_drawing_number"))
    return TableSheetPlan(table, block, block.title or fs.name, date,
                          (sx, sy, sw, sh), frame, left, top, findings)


# Margin round a sheet with no furniture.
_PLAIN_MARGIN = 55.0


class DiagramPlan(NamedTuple):
    """Diagram sheet geometry, shared by both backends.

    Attributes
    ----------
    placed : list[Docked]
        Furniture in drawing order; the title strip is :data:`TITLE`.
    block : TitleBlock
        What the title strip says.
    bounds : tuple[float, float, float, float]
        Drawing bounds ``(x0, y0, x1, y1)``.
    frame : tuple[float, float, float, float]
        Drawing frame the border is ruled on.
    fit : tuple[float, float, float] or None
        ``(scale, offset_x, offset_y)`` fitting the drawing into the
        region a fixed page leaves for it, or ``None``.
    """
    placed: list
    block: "TitleBlock"
    bounds: "tuple[float, float, float, float]"
    frame: "tuple[float, float, float, float]"
    fit: "tuple[float, float, float] | None"


def diagram_plan(fs, sheet: "_Sheet | None", border: str,
                 show_stream_table: bool,
                 diagram: "str | None" = None, labels=()) -> DiagramPlan:
    """Lay out the diagram's sheet and dock its furniture.

    Furniture is the annotation boxes, a title strip for a title block
    or zone border, and the stream table.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    sheet : _Sheet or None
        Fixed page, or ``None`` to fit the sheet to the drawing.
    border : str
        ``"none"`` or ``"zone"``.
    show_stream_table : bool
        Whether to dock the stream table.
    diagram : str or None, optional
        Diagram type; ``None`` is a PFD.
    labels : sequence of tuple, optional
        Boxes ``(x0, y0, x1, y1)`` of the labels drawn beside units.

    Returns
    -------
    DiagramPlan
        Layout.

    Raises
    ------
    ValueError
        If a unit has no frame, or the page is too small.
    """
    from pandid.document import TableBox, TitleBlock

    bounds = drawing_bounds(fs, labels)
    if not fs.units:  # empty flowsheet: use the nominal page size
        nominal = sheet or _page("A3")
        assert nominal is not None
        bounds = (0.0, 0.0, nominal.width, nominal.height)
    block = fs.title_block or TitleBlock()
    items = [(a, a.align, *(F.measure_table(a) if isinstance(a, TableBox)
                            else F.measure_annotation(a)))
             for a in fs.annotations]
    if fs.title_block is not None or border == "zone":
        items.append((TITLE, "bottom-right", *F.measure_title_strip(block)))
    table = F.stream_table_layout(fs, diagram) if show_stream_table else None
    if table is not None:
        items.append((table, "bottom-left", table.w, table.h))
    # The frame sits where a border would.
    inset = F.OUTER_MARGIN + F.ZONE_BAND
    if items:
        if sheet is None:
            placed, frame, free = F.dock(items, bounds)
        else:
            page = sheet
            placed, frame, free = F.dock(
                items, bounds, sheet=page,
                too_small=lambda need_w, need_h, culprit: _too_small(
                    page, need_w, need_h, _furniture_name(culprit) if culprit else ""))
        return DiagramPlan(placed, block, bounds, frame,
                           None if free is None else _fitted(bounds, free))
    if sheet is None:
        x0, y0, x1, y1 = bounds
        m = _PLAIN_MARGIN - inset
        return DiagramPlan([], block, bounds,
                           (x0 - m, y0 - m, x1 - x0 + 2 * m, y1 - y0 + 2 * m), None)
    free_w = sheet.width - 2 * _PLAIN_MARGIN
    free_h = sheet.height - 2 * _PLAIN_MARGIN
    if free_w <= 0 or free_h <= 0:
        raise _too_small(sheet, 2 * _PLAIN_MARGIN, 2 * _PLAIN_MARGIN)
    return DiagramPlan([], block, bounds,
                       (inset, inset, sheet.width - 2 * inset, sheet.height - 2 * inset),
                       _fitted(bounds, (_PLAIN_MARGIN, _PLAIN_MARGIN, free_w, free_h)))


def check_render_arguments(fs, *, show_stream_table: "bool | str" = False,
                           border: "str | None" = None,
                           diagram: "str | None" = None,
                           page_size: "str | None" = None,
                           connections: "str | None" = None,
                           jump_direction: str = "vertical",
                           crossing_style: str = "gap",
                           debug: "bool | float" = False) -> None:
    """Check render arguments before the sheet is laid out or routed.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    show_stream_table : bool or str, default=False
        ``True``, ``False`` or ``"sheet"``.
    border : str, optional
        ``"none"`` or ``"zone"``.
    diagram : str, optional
        ``"pfd"``, ``"p&id"`` (or ``"pid"``) or ``"bfd"``.
    page_size : str, optional
        ISO A-size.
    connections : str, optional
        One of :data:`CONNECTIONS`.
    jump_direction : str, default="vertical"
        One of :data:`JUMP_DIRECTIONS`.
    crossing_style : str, default="gap"
        One of :data:`CROSSING_STYLES`.
    debug : bool or float, default=False
        Debug overlay setting.

    Raises
    ------
    ValueError
        If any argument is invalid, ``debug`` is set with
        ``show_stream_table="sheet"``, or the table sheet cannot be laid
        out.
    """
    from pandid.render import debug as _debug

    grid = _debug.resolve_spacing(debug)
    check_jump_direction(jump_direction)
    check_crossing_style(crossing_style)
    _, kind = _resolve_sheet(border, diagram)
    sheet_connections(kind, connections)
    page = _page(page_size)
    if not wants_table_sheet(show_stream_table):
        return
    if grid is not None:
        raise ValueError(
            "debug draws the coordinate overlay under a *diagram*, and "
            "show_stream_table='sheet' draws no diagram. Render the diagram "
            "to see the overlay, or drop debug=")
    # Lay the table sheet out to check it, then restore fs.warnings in
    # place.
    was = fs.warnings
    contents = list(was)
    try:
        table_sheet_plan(fs, page, kind)
    finally:
        was[:] = contents
        fs.warnings = was


class SvgRenderer:
    """Renderer of a laid-out Flowsheet to SVG."""

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical",
               crossing_style: str = "gap",
               show_stream_table: "bool | str" = False,
               border: "str | None" = None, diagram: "str | None" = None,
               page_size: "str | None" = None, connections: "str | None" = None,
               debug: "bool | float" = False) -> str:
        """Render the flowsheet to SVG.

        Add the render's findings to ``fs.warnings``, replacing the
        fit findings there.

        Parameters
        ----------
        fs : Flowsheet
            Laid-out and routed flowsheet.
        jump_direction : str, default="vertical"
            Line carrying the mark: ``"vertical"`` or ``"horizontal"``.
        crossing_style : str, default="gap"
            ``"gap"``, ``"arc"`` or ``"plain"``.
        show_stream_table : bool or str, default=False
            ``True`` docks the stream table on the diagram; ``"sheet"``
            draws it as its own sheet.
        border : str, optional
            ``"none"`` or ``"zone"``, the default on a table sheet.
        diagram : str, optional
            ``"pfd"`` (default), ``"p&id"`` (or ``"pid"``) or ``"bfd"``.
        page_size : str, optional
            ``"A4"`` to ``"A0"``, or ``None`` to fit the drawing.
        connections : str, optional
            P&ID joint default: ``"none"``, ``"flanged"`` or
            ``"flanged-at-nozzles"``.
        debug : bool or float, default=False
            Draw the coordinate overlay, optionally at a grid spacing.

        Returns
        -------
        str
            SVG document.

        Raises
        ------
        ValueError
            If an argument is invalid, the page is too small, or a unit
            has no frame.
        """
        from pandid.render import debug as _debug
        grid = _debug.resolve_spacing(debug)
        table_sheet = wants_table_sheet(show_stream_table)
        if table_sheet and border is None:
            border = "zone"
        border, diagram = _resolve_sheet(border, diagram)
        arrows = draws_arrowheads(diagram)
        joints = sheet_connections(diagram, connections)
        sheet = _page(page_size)
        if table_sheet:
            return self._table_sheet(fs, sheet, border, diagram)

        # 1. The sheet: furniture docked round the drawing and its tags.
        tags = [item for _, _, items in unit_tags(fs, joints, jump_direction)
                for item in items]
        plan = diagram_plan(fs, sheet, border, bool(show_stream_table), diagram,
                            [b for b in map(_unit_label_box, tags) if b is not None])
        fit_issues: list[Issue] = []
        # Findings from the label passes.
        self._findings: list[Issue] = []
        furniture, canvas = self._place_furniture(
            fs, plan, border, lambda *cell: fit_issues.append(fit_issue(*cell)))

        # Replace validate's fit findings with the render's.
        render_issues = fit_issues + _crossing_issues(fs, jump_direction,
                                                      crossing_style)
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _FIT_CODES] + render_issues

        # 2. SVG document, with furniture behind the diagram.
        lines = ["    " + item for item in furniture]
        lines.extend(self._defs(fs, arrows))
        unit_labels: list = []
        balloons: list = []
        drawing: list[str] = []
        # Opaque plates, for the debug overlay and the codes drawn last.
        plates: "list[tuple[float, float, float, float]]" = []
        drawing.extend(self._draw_packages(fs, unit_labels))
        unit_labels += tags
        drawing.extend(self._draw_units(fs, balloons))
        drawing.extend(self._draw_streams(fs, jump_direction, unit_labels, arrows,
                                          plates, joints, crossing_style))
        # Instruments go over the lines.
        drawing.extend(self._draw_taps(fs))
        if balloons:
            drawing.append('  <g id="instruments">')
            drawing.extend(balloons)
            drawing.append('  </g>')
        # Tags and quadrant codes go last, on halos, over every line.
        drawing.extend(self._draw_unit_labels(
            unit_labels + drawn_codes(fs, joints, jump_direction, plates)))
        fs.warnings = fs.warnings + self._findings

        # The debug overlay is drawn first, under the sheet's ink.
        if grid is not None:
            drawing[:0] = _debug.overlay(
                fs, plan.bounds, grid, 1.0 if plan.fit is None else plan.fit[0],
                plates=plates, ink=[line.box for line in _ink(fs, jump_direction)])

        if plan.fit is None:
            lines.extend(drawing)
        else:  # a fixed sheet: fit the drawing into the free region
            s, ox, oy = plan.fit
            lines.append(f'  <g id="drawing" transform="translate({fmt(ox, 2)}, {fmt(oy, 2)}) '
                         f'scale({s:.6g})">')
            lines.extend(drawing)
            lines.append('  </g>')
        return _document(fs, sheet, canvas, lines)

    # --- furniture ----------------------------------------------------

    def _place_furniture(self, fs, plan, border, report=None):
        """Draw the docked furniture and the border.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose name the title strip falls back to.
        plan : DiagramPlan
            Sheet layout.
        border : str
            ``"none"`` or ``"zone"``.
        report : callable, optional
            Receives title and annotation fit findings.

        Returns
        -------
        tuple[list[str], tuple[float, float, float, float]]
            SVG lines and the canvas ``(x, y, w, h)``.
        """
        from pandid.document import TableBox

        furniture: list[str] = []
        # The scale cell states the fit scale on a fixed page.
        fit = "" if plan.fit is None else _scale_text(plan.fit[0])
        date = datetime.now().strftime("%Y-%m-%d")
        for obj, x, y, w, h in plan.placed:
            if obj is TITLE:
                furniture.extend(
                    F.draw_title_strip(plan.block, fs.name, date, x + w, y + h,
                                       fit_scale=fit, report=report))
            elif isinstance(obj, F.StreamTable):
                furniture.extend(F.draw_stream_table(obj, x, y))
            elif isinstance(obj, TableBox):
                furniture.extend(F.draw_table(obj, x, y))
            else:
                furniture.extend(F.draw_annotation(obj, x, y, report=report))

        # --- border around the frame, then the sheet edge -------------
        if border == "zone":
            furniture[:0] = F.zone_frame(*plan.frame)  # border sits behind the boxes
        ox, oy, ow, oh = F.sheet_rect(*plan.frame)
        OUT = F.OUTER_MARGIN
        return furniture, (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT)

    def _table_sheet(self, fs, sheet, border, diagram) -> str:
        """Return the stream table drawn as a sheet of its own.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose streams are tabulated.
        sheet : _Sheet or None
            Fixed page, or ``None`` to size to the table.
        border : str
            ``"none"`` or ``"zone"``.
        diagram : str
            Diagram type the table belongs to.

        Returns
        -------
        str
            SVG document.
        """
        from pandid.document import _drawn_text

        fit_issues: list[Issue] = []
        plan = table_sheet_plan(fs, sheet, diagram)
        furniture: list[str] = []
        for i, part, bx, by in plan.table.at(plan.left, plan.top):
            furniture.extend(F.draw_stream_table(
                part, bx, by, group=f"stream_table_{i + 1}"))
        sx, sy, sw, sh = plan.strip
        furniture.extend(F.draw_title_strip(
            plan.block, plan.name, plan.date, sx + sw, sy + sh,
            report=lambda *cell: fit_issues.append(fit_issue(*cell))))
        if border == "zone":
            furniture[:0] = F.zone_frame(*plan.frame)  # the border sits behind the rest
        ox, oy, ow, oh = F.sheet_rect(*plan.frame)
        OUT = F.OUTER_MARGIN
        # Replace validate's fit findings with the render's.
        fs.warnings = ([w for w in fs.warnings
                        if getattr(w, "code", "") not in _FIT_CODES]
                       + plan.findings + fit_issues)
        subtitle = _drawn_text(F._options(fs).sheet_subtitle)
        return _document(
            fs, sheet, (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT),
            ["    " + item for item in furniture],
            title=" - ".join(p for p in (_sheet_title(fs), subtitle) if p))

    # --- defs ---------------------------------------------------------

    def _baked_xform(self, u) -> tuple[int, bool, bool]:
        """Return the placement baked into a symbol definition.

        Symbols with lettering bake the whole placement, directional
        symbols its reflections, and others the identity.

        Parameters
        ----------
        u : Unit
            Placed unit.

        Returns
        -------
        tuple[int, bool, bool]
            ``(rotation, mirror_x, mirror_y)``.
        """
        sym = default_registry.for_unit(u)
        f = u.frame
        rot = int(getattr(f, "orientation", 0) or 0)
        mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        if "<text" in sym.svg:
            return (rot, mirror_x, mirror_y)
        if sym.directional:
            return (0, *_reflections(rot, mirror_x, mirror_y))
        return (0, False, False)

    def _sym_id(self, u) -> str:
        """Return the ``<defs>`` id a unit's ``<use>`` refers to.

        The id names the kind and variant, suffixed for any size, pen
        scale or transform baked into the definition.

        Parameters
        ----------
        u : Unit
            Placed unit.

        Returns
        -------
        str
            Definition id.
        """
        variant = getattr(u, 'variant', 'default')
        sym = default_registry.for_unit(u)
        body = (u.kind if variant == "default" else f"{u.kind}_{variant}") + sym.id_suffix
        if not (math.isclose(_pen_scale(sym, u), 1.0, rel_tol=1e-9)
                and _fold(sym, u) == (1.0, 1.0)):
            bw, bh = _placed_box(u)
            body += f"_s{fmt(bw, 2)}x{fmt(bh, 2)}"
        rot, mirror_x, mirror_y = self._baked_xform(u)
        if rot or mirror_x or mirror_y:
            body += ("_t" + (f"r{rot}" if rot else "") + ("x" if mirror_x else "")
                     + ("y" if mirror_y else ""))
        return ident("sym", body)

    def _defs(self, fs, arrows=True):
        """Return the ``<defs>`` block: arrow markers and symbols, each in id order.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        arrows : bool, default=True
            Whether to define arrowhead markers.

        Returns
        -------
        list[str]
            SVG lines.
        """
        lines = []
        used_colors = sorted({s.color or "black" for s in fs.streams}, key=arrow_marker_id)
        lines.append('  <defs>')
        for c in used_colors if arrows else ():
            lines.append(
                f'    <marker id="{arrow_marker_id(c)}" viewBox="0 0 10 10" '
                f'refX="10" refY="5" '
                f'markerWidth="{ARROWHEAD:g}" markerHeight="{ARROWHEAD:g}" '
                f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{escaped(c)}" />')
            lines.append('    </marker>')

        # One definition per (kind, variant) and anything baked in.
        used: dict[tuple, tuple] = {}
        # Stretchable definitions placed in a box of another shape.
        stretched: set[tuple] = set()
        for u in fs.units:
            if u.kind in ("feed", "product"):
                continue
            sym = default_registry.for_unit(u)
            xform = self._baked_xform(u)
            fold, pen = _fold(sym, u), _pen_scale(sym, u)
            key = ((u.kind, getattr(u, 'variant', 'default'), sym.id_suffix, fold, pen)
                   + xform)
            used[key] = (self._sym_id(u), sym, fold, pen, *xform)
            if sym.stretchable and _reshapes(sym, u) and fold == (1.0, 1.0):
                stretched.add(key)
        for key in sorted(used, key=lambda k: used[k][0]):
            sym_id, sym, fold, pen, rot, mirror_x, mirror_y = used[key]
            art = _baked(sym.svg, *fold)
            width, height = sym.width * fold[0], sym.height * fold[1]
            # Artwork is drawn at the EQUIPMENT weight; scale it to the
            # symbol's class weight.
            stroke = pen * LineWeight.EQUIPMENT.width / _class_weight(sym).width
            if sym.directional:
                svg_str = _upright_artwork(_at_pen_scale(art, stroke),
                                           width, height, mirror_x, mirror_y)
            else:
                svg_str = _upright_text(_at_pen_scale(art, stroke), rot, mirror_x, mirror_y)
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                fill = ' preserveAspectRatio="none"' if key in stretched else ''
                # overflow="visible" keeps strokes on the viewBox edge.
                box = (f"{sym.width} {sym.height}" if fold == (1.0, 1.0)
                       else f"{fmt(width, 6)} {fmt(height, 6)}")
                svg_str = (f'<symbol id="{sym_id}" viewBox="0 0 {box}"'
                           f'{fill} overflow="visible">{inner}</symbol>')
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')
        return lines

    # --- units --------------------------------------------------------

    def _draw_units(self, fs, balloons):
        """Return the ``units`` group and collect balloons.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        balloons : list[str]
            Receives instrument SVG.

        Returns
        -------
        list[str]
            SVG lines.
        """
        lines = ['  <g id="units">']
        for u in fs.units:
            f = u.frame
            out = balloons if u.kind == "instrument" else lines
            x, y = f.x, f.y
            safe_name = escaped(u.tag)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, safe_name))
                continue

            sym_id = self._sym_id(u)
            u_width, u_height = f.w, f.h
            rot = int(getattr(f, "orientation", 0) or 0)
            mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
            cx, cy = x + u_width / 2, y + u_height / 2

            # A quarter turn swaps the artwork box.
            if rot in (90, 270):
                bw, bh = u_height, u_width
            else:
                bw, bh = u_width, u_height
            ux, uy = cx - bw / 2, cy - bh / 2

            # SVG composes right to left: mirror, then rotate.
            ops = []
            if rot:
                ops.append(f"rotate({rot}, {fmt(cx, 2)}, {fmt(cy, 2)})")
            if mirror_x:
                ops.append(f"translate({fmt(2 * cx, 2)}, 0) scale(-1, 1)")
            if mirror_y:
                ops.append(f"translate(0, {fmt(2 * cy, 2)}) scale(1, -1)")
            transform = f' transform="{" ".join(ops)}"' if ops else ""
            out.append(f'    <use href="#{sym_id}" x="{fmt(ux, 2)}" y="{fmt(uy, 2)}" '
                       f'width="{bw}" height="{bh}"{transform} />')

            if u.kind == "instrument":
                out.extend(self._draw_instrument_tag(u, x, y, u_width, u_height))
        lines.append('  </g>')
        return lines

    def _draw_packages(self, fs, label_items):
        """Return the ``packages`` group of boundary frames.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        label_items : list
            Receives each package's tag and reference.

        Returns
        -------
        list[str]
            SVG lines, empty when there are no packages.
        """
        out = []
        for pkg in fs.packages:
            box = package_frame(pkg)
            assert box is not None
            x0, y0, x1, y1 = box
            out.append(f'    <rect x="{fmt(x0, 2)}" y="{fmt(y0, 2)}" '
                       f'width="{fmt(x1 - x0, 2)}" height="{fmt(y1 - y0, 2)}" fill="none" '
                       f'stroke="black" stroke-width="{LineWeight.DETAIL.width:g}" '
                       f'stroke-dasharray="{PACKAGE_DASH}" />')
            label_items.extend(package_labels(pkg, box))
        return ['  <g id="packages">'] + out + ['  </g>'] if out else []

    def _draw_taps(self, fs):
        """Return the lines from tap points to their balloons.

        Draw impulse lines solid and signal lines dashed, along
        :func:`tap_route`.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.

        Returns
        -------
        list[str]
            SVG lines, empty when there are no taps.
        """
        out = []
        for u, tap, centre in tap_lines(fs):
            dash = "" if impulse_tap(u) else f' stroke-dasharray="{_TAP_DASH}"'
            pen = f'stroke="black" stroke-width="{LineWeight.DETAIL.width:g}"{dash} />'
            route = tap_route(u, tap, centre)
            if len(route) == 2:
                (tx, ty), (cx, cy) = route
                out.append(f'    <line x1="{fmt(tx, 2)}" y1="{fmt(ty, 2)}" '
                           f'x2="{fmt(cx, 2)}" y2="{fmt(cy, 2)}" {pen}')
            else:
                d = " L ".join(f"{fmt(x, 2)},{fmt(y, 2)}" for x, y in route)
                out.append(f'    <path d="M {d}" fill="none" {pen}')
        return ['  <g id="instrument_taps">'] + out + ['  </g>'] if out else []

    def _draw_boundary(self, u, f, safe_name):
        """Return a Feed or Product off-page flag.

        A ``reference`` adds a second line naming the connected drawing.

        Parameters
        ----------
        u : Unit
            Feed or Product.
        f : Frame
            Its frame.
        safe_name : str
            Escaped tag.

        Returns
        -------
        list[str]
            SVG lines.
        """
        from pandid.portgeom import _flag_reference

        ref = _flag_reference(u)
        (bx0, top, bx1, bot), depth, east = boundary_flag(u, f)
        mid = (top + bot) / 2
        label_w = f.w
        # Letter the flat part, not the point.
        if east:
            px0, px1, px2 = bx0, bx1 - depth, bx1
            tx = px0 + (label_w - depth) / 2
        else:
            px0, px1, px2 = bx1, bx0 + depth, bx0
            tx = bx0 + depth + (label_w - depth) / 2
        points = f"{px0},{top} {px1},{top} {px2},{mid} {px1},{bot} {px0},{bot}"
        out = [f'    <polygon points="{points}" fill="transparent" '
               f'stroke="black" stroke-width="{LineWeight.EQUIPMENT.width:g}" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{mid - 4}" font-family="sans-serif" font-size="{_TAG_TYPE:g}" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{mid + 8}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{escaped(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{mid}" font-family="sans-serif" font-size="{_TAG_TYPE:g}" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        """Return the balloon lettering: letters over loop number.

        A diamond carries the number alone.

        Parameters
        ----------
        u : Instrument
            Balloon.
        x, y, u_width, u_height : float
            Drawn box.

        Returns
        -------
        list[str]
            SVG ``<text>`` lines.
        """
        from pandid.units import split_tag

        variant = getattr(u, "variant", "default")
        tag = getattr(u, "tag", "") or u.name
        top, bot = split_tag(getattr(u, "type", "") or tag, getattr(u, "number", "") or "")
        cx, cy = x + u_width / 2, y + u_height / 2
        if variant in _DIAMOND_BALLOONS:
            # The number goes in the lower half of the diamond.
            return [f'    <text x="{cx}" y="{cy + 7}" font-family="sans-serif" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top.upper())}</text>']
        if not top:
            return [f'    <text x="{cx}" y="{cy}" font-family="sans-serif" '
                    f'font-size="{_TAG_TYPE:g}" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top)}</text>']
        # Letters above a location bar and the number below it.
        letters_dy, number_dy = (-10, 11) if variant in _BARRED_BALLOONS else (-4, 10)
        out = [f'    <text x="{cx}" y="{cy + letters_dy}" font-family="sans-serif" '
               f'font-size="{_TAG_TYPE:g}" font-weight="bold" text-anchor="middle" '
               f'dominant-baseline="middle">{escaped(top.upper())}</text>']
        if bot:
            out.append(f'    <text x="{cx}" y="{cy + number_dy}" font-family="sans-serif" '
                       f'font-size="11" text-anchor="middle" '
                       f'dominant-baseline="middle">{escaped(bot)}</text>')
        return out

    def _label_place(self, lpos: str, x: float, y: float, u_width: float,
                     u_height: float) -> "tuple[float, float, str, str]":
        """Return a label's anchor and text alignment for one side.

        Parameters
        ----------
        lpos : str
            A :data:`LABEL_POSITIONS` value, or ``"top_right"`` for NC.
        x, y, u_width, u_height : float
            Unit box.

        Returns
        -------
        tuple[float, float, str, str]
            ``(x, y, text_anchor, dominant_baseline)``.
        """
        if lpos == "bottom":
            return x + u_width / 2, y + u_height + 15, "middle", "middle"
        if lpos == "left":
            return x - 10, y + u_height / 2, "end", "middle"
        if lpos == "right":
            return x + u_width + 10, y + u_height / 2, "start", "middle"
        if lpos == "center":
            return x + u_width / 2, y + u_height / 2, "middle", "middle"
        if lpos == "top_right":
            return x + u_width, y - 10, "start", "baseline"
        return x + u_width / 2, y - 10, "middle", "baseline"  # top

    def _unit_label_item(self, u, f, x, y, u_width, u_height, tag):
        """Return a unit label item on its layout-chosen side.

        Parameters
        ----------
        u : Unit
            Unit.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        tag : str
            Tag as drawn, unescaped.

        Returns
        -------
        tuple
            ``(x, y, anchor, baseline, side, text)``.
        """
        lpos = f.label_pos or "top"
        return (*self._label_place(lpos, x, y, u_width, u_height), lpos, tag)

    def _tag_spots(self, u, f, x, y, u_width, u_height, tag, ink, symbols=(), labels=None,
                   hatches=(), step_out=True):
        """Return the spots to try for an equipment tag, best first.

        The tag slides up to half the face along its side, then along
        the other free sides. The first placement that erases nothing
        wins, else the least damaging. A side set on the unit or symbol
        is kept.

        Given ``labels``, the tag then also tries every side, free sides
        first, sliding until its near end reaches the corner, then steps
        out from the face. A stepped-out tag stays well nearer its own
        symbol than any other tagged one, and off every pneumatic hatch.
        It ranks the spots that score better than the first placement,
        erasing least then covering fewest labels, and the first
        placement last.

        Parameters
        ----------
        u : Unit
            Unit.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        tag : str
            Tag as drawn, unescaped.
        ink : sequence of _Ink
            Drawn lines.
        symbols : sequence of tuple, optional
            ``(unit, box)`` for every symbol and owner-less mark.
        labels : sequence of tuple, optional
            Halo boxes of other labels.
        hatches : sequence of tuple, optional
            Boxes of the pneumatic hatch strokes.
        step_out : bool, default=True
            Whether the tag may step out from the face.

        Returns
        -------
        list[tuple]
            Label items, best first.
        """
        from pandid.layout.labels import LABEL_SIDES, free_label_sides

        item = self._unit_label_item(u, f, x, y, u_width, u_height, tag)
        box = _unit_label_box(item)
        if box is None or not (ink or symbols):
            return [item]
        if getattr(u, "label_pos", None) or default_registry.for_unit(u).label_pos:
            return [item]
        # Test only ink near the unit.
        pad = max(u_width, u_height) + (box[2] - box[0]) + _TAG_STEP_OUT
        window = (x - pad, y - pad, x + u_width + pad, y + u_height + pad)
        near = [line for line in ink if boxes_overlap(line.box, window)]
        # Every other symbol box, grown to its ink.
        others = [_obstacle(b) for v, b in symbols
                  if v is not u and boxes_overlap(_obstacle(b), window)]

        clear = (0, 0, 0)
        best, damage = item, _erases(box, near, others)
        free = [item[4]] + [s for s in free_label_sides(u) if s != item[4]]
        for side in free:
            if damage == clear:
                break
            lx, ly, anchor, baseline = self._label_place(side, x, y, u_width, u_height)
            # Slide at most half the face.
            edgewise = side in ("left", "right")
            for sx, sy in _slide(lx, ly, (u_height if edgewise else u_width) / 2, edgewise):
                spot = (sx, sy, anchor, baseline, side, tag)
                cost = _erases(_unit_label_box(spot), near, others)
                if cost < damage:
                    best, damage = spot, cost
                    if damage == clear:
                        break
        if labels is None:
            return [best]
        covered = [b for b in labels if boxes_overlap(b, window)]

        def score(spot) -> "tuple[int, int, int, int]":
            """Return what a spot erases, then the labels it covers.

            Parameters
            ----------
            spot : tuple
                Label item.

            Returns
            -------
            tuple[int, int, int, int]
                Symbols, impulse lines, pipes and labels.
            """
            halo = _unit_label_box(spot)
            assert halo is not None
            return (*_erases(halo, near, others),
                    sum(1 for b in covered if boxes_overlap(halo, b)))

        own = (x, y, x + u_width, y + u_height)
        rivals = [b for v, b in symbols if v is not None and v is not u
                  and v.kind not in ("feed", "product", "instrument")
                  and boxes_overlap(b, window)]

        def astray(halo) -> bool:
            """Return whether a stepped-out halo is too near another symbol.

            Parameters
            ----------
            halo : tuple[float, float, float, float]
                Halo box.

            Returns
            -------
            bool
                True if it is not well nearer its own symbol than any
                other tagged one, or it lies on a hatch.
            """
            if any(_box_gap(halo, b) < _TAG_NEARER * _box_gap(halo, own) for b in rivals):
                return True
            return any(boxes_overlap(halo, h) for h in hatches)
        least = score(best)
        if least == (0, 0, 0, 0):
            return [best]
        better = []
        sides = free + [s for s in LABEL_SIDES if s not in free]
        reach = _TAG_STEP_OUT if step_out else 0.0
        for out in [k * _LABEL_STEP for k in range(int(reach // _LABEL_STEP) + 1)]:
            for side in sides:
                lx, ly, anchor, baseline = self._label_place(side, x, y, u_width, u_height)
                nx, ny = _OUTWARD[side]
                edgewise = side in ("left", "right")
                face, along = ((u_height, box[3] - box[1]) if edgewise
                               else (u_width, box[2] - box[0]))
                for sx, sy in _slide(lx + nx * out, ly + ny * out, (face + along) / 2, edgewise):
                    spot = (sx, sy, anchor, baseline, side, tag)
                    halo = _unit_label_box(spot)
                    assert halo is not None
                    if out and astray(halo):
                        continue
                    cost = score(spot)
                    if cost < least:
                        better.append((cost, len(better), spot))
        return [spot for _cost, _n, spot in sorted(better)] + [best]

    def _nc_label_item(self, u, f, x, y, u_width, u_height, tag_box=None):
        """Return the ``NC`` label above and right of the symbol.

        The letters follow ISO 15519-1 11.4.5 and step right past a tag
        in that corner.

        Parameters
        ----------
        u : Unit
            Valve or fitting.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        tag_box : tuple, optional
            Where the tag landed; resolved from the frame when omitted.

        Returns
        -------
        tuple
            Label item.
        """
        item = (*self._label_place("top_right", x, y, u_width, u_height), "top_right", "NC")
        tag = tag_box if tag_box is not None else _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, u.tag))
        nc = _unit_label_box(item)
        if tag is not None and nc is not None and (
                boxes_overlap(tag, nc)):
            lx, ly, anchor, baseline, lpos, text = item
            item = (lx + tag[2] - nc[0] + 6, ly, anchor, baseline, lpos, text)
        return item

    def _fail_label_item(self, u, f, x, y, u_width, u_height, letters, tag_box=None,
                         ink=(), symbols=()):
        """Return the fail-position letters beside a control valve.

        The letters go below a horizontal valve and right of a vertical
        one. They step out past the tag, then slide along the face off
        any line or symbol.

        Parameters
        ----------
        u : Unit
            Valve.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        letters : str
            Fail-position letters.
        tag_box : tuple, optional
            Where the tag landed; resolved from the frame when omitted.
        ink : sequence of _Ink, optional
            Drawn lines.
        symbols : sequence of tuple, optional
            ``(unit, box)`` for every symbol.

        Returns
        -------
        tuple
            Label item.
        """
        upright = int(getattr(f, "orientation", 0) or 0) in (90, 270)
        lpos = "right" if upright else "bottom"
        item = (*self._label_place(lpos, x, y, u_width, u_height), lpos, letters)
        tag = tag_box if tag_box is not None else _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, u.tag))
        fail = _unit_label_box(item)
        if tag is not None and fail is not None and (
                boxes_overlap(tag, fail)):
            lx, ly, anchor, baseline, lpos, text = item
            # Step past the tag by the overlap plus a gap.
            if upright:
                item = (lx + tag[2] - fail[0] + 6, ly, anchor, baseline, lpos, text)
            else:
                item = (lx, ly + tag[3] - fail[1] + 4, anchor, baseline, lpos, text)
        others = [_obstacle(b) for v, b in symbols if v is not u]
        if tag is not None:
            others.append(tag)
        # Slide at most until the plate's near edge reaches the far end
        # of the face.
        plate = _unit_label_box(item)
        assert plate is not None
        face, along = ((u_height, plate[3] - plate[1]) if upright
                       else (u_width, plate[2] - plate[0]))
        return _step_aside(item, (face + along) / 2, ink, others)

    def _draw_unit_labels(self, items):
        """Return the label pass: tags on white halos over the lines.

        A ``center`` label gets no halo.

        Parameters
        ----------
        items : list[tuple]
            Label items.

        Returns
        -------
        list[str]
            SVG lines.
        """
        out = ['  <g id="unit_labels">']
        for item in items:
            lx, ly, anchor, baseline, _, text = item
            box = _unit_label_box(item)
            if box is not None:
                rx, ry, rx1, ry1 = box
                out.append(f'    <rect x="{rx:.1f}" y="{ry:.1f}" width="{rx1 - rx:.1f}" '
                           f'height="{ry1 - ry:.1f}" fill="white" />')
            out.append(f'    <text x="{lx}" y="{ly}" font-family="sans-serif" '
                       f'font-size="{_TAG_TYPE:g}" text-anchor="{anchor}" '
                       f'dominant-baseline="{baseline}">{escaped(text)}</text>')
        out.append('  </g>')
        return out

    # --- streams ------------------------------------------------------

    def _draw_streams(self, fs, jump_direction, unit_labels, arrows=True,
                      plates=None, joints=None, crossing_style="gap"):
        """Return the ``streams`` group: runs, joint marks and numbers.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        jump_direction : str
            Line carrying the mark: ``"vertical"`` or ``"horizontal"``.
        unit_labels : list
            Tag items already placed, for numbers to avoid.
        arrows : bool, default=True
            Whether process lines get arrowheads.
        plates : list, optional
            Receives every opaque box the label passes reserve.
        joints : str, optional
            Sheet joint default, or ``None``.
        crossing_style : str, default="gap"
            ``"gap"``, ``"arc"`` or ``"plain"``.

        Returns
        -------
        list[str]
            SVG lines.
        """
        stream_geoms = [(s, stream_polyline(s)) for s in fs.streams]
        marks: dict[int, list] = {}
        for mark in pipe_marks(fs):
            marks.setdefault(id(mark.stream), []).append(mark)
        # Hops keyed by (stream, segment), in drawing order.
        hops: dict[tuple[int, int], list[_Hop]] = {}
        if crossing_style != "plain":
            for hop in stream_hops(fs, jump_direction):
                hops.setdefault((hop.stream, hop.seg), []).append(hop)

        # The command crossing to the far side: an arc, or a gap as an
        # ``M`` subpath in the same ``d``.
        cross = f"A {HOP_R:g} {HOP_R:g} 0 0 1 " if crossing_style == "arc" else "M "
        lines = ['  <g id="streams">']
        for n, (s, points) in enumerate(stream_geoms):
            paint = s.color or "black"
            marker_id = arrow_marker_id(paint)
            color = escaped(paint)
            is_signal = s.kind in _SIGNAL_KINDS
            pattern = s.dasharray or _SIGNAL_DASH.get(s.kind, "")
            dash = f' stroke-dasharray="{escaped(pattern)}"' if pattern else ""

            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                # Stop HOP_R before the crossing and resume HOP_R past.
                for hop in hops.get((n, i), ()):
                    if hop.vertical:
                        foot = HOP_R if y1 < y2 else -HOP_R
                        d_parts.extend([
                            f"L {x1},{hop.y - foot:g}",
                            f"{cross}{x1},{hop.y + foot:g}"])
                    else:
                        foot = HOP_R if x1 < x2 else -HOP_R
                        d_parts.extend([
                            f"L {hop.x - foot:g},{y1}",
                            f"{cross}{hop.x + foot:g},{y1}"])
                d_parts.append(f"L {x2},{y2}")
            d_str = " ".join(d_parts)

            marker = (f' marker-end="url(#{marker_id})"'
                      if arrows and wears_arrowhead(s, default_registry) else "")
            width = _stream_rung(is_signal).width
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="{width:g}"{dash}{marker} />'
            )

            # Flange faces across the run, on the detail rung.
            for fx, fy, angle, _at in flange_marks(s, points,
                                                   resolve_connections(s, joints)):
                rad = math.radians(angle)
                ax, ay = math.cos(rad) * FLANGE_GAP / 2, math.sin(rad) * FLANGE_GAP / 2
                bx, by = -math.sin(rad) * FLANGE_TICK / 2, math.cos(rad) * FLANGE_TICK / 2
                for sign in (-1, 1):
                    mx, my = fx + ax * sign, fy + ay * sign
                    lines.append(
                        f'    <line x1="{mx - bx:.1f}" y1="{my - by:.1f}" '
                        f'x2="{mx + bx:.1f}" y2="{my + by:.1f}" '
                        f'stroke="{color}" '
                        f'stroke-width="{LineWeight.DETAIL.width:g}" />'
                    )

            # Tracing, insulation and jacket (ISO 10628-2 25.6-25.9).
            for mark in marks.get(id(s), ()):
                for (x1, y1), (x2, y2), weight in mark.strokes:
                    lines.append(f'    <line x1="{x1:.1f}" y1="{y1:.1f}" '
                                 f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
                                 f'stroke-width="{weight.width:g}" />')

            if s.kind == "pneumatic":
                # Pneumatic hatching (ISO 15519-2 Annex A.1.09).
                for (x1, y1), (x2, y2) in _hatch_strokes(points):
                    lines.append(f'    <line x1="{x1:.1f}" y1="{y1:.1f}" '
                                 f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
                                 f'stroke-width="{LineWeight.DETAIL.width:g}" />')

        # Final pass: stream numbers on white halos.
        placed: list[tuple[float, float, float, float]] = [
            b for b in map(_unit_label_box, unit_labels) if b is not None
        ]

        shape = enclosure_shape(fs)
        numbers = stream_numbers(fs, placed, joints, jump_direction)
        self._findings += label_findings(fs, shape, numbers, jump_direction)
        fills = fillable_enclosures(fs, shape, numbers, jump_direction)
        for number, fill in zip(numbers, fills):
            tx, ty, name = number.x, number.y, number.name
            color = escaped(number.color)
            lines += _enclosure_svg(shape, number.box, number.words, color, fill)
            turn = f' transform="rotate(-90, {tx:.1f}, {ty:.1f})"' if number.vertical else ""
            lines.append(
                f'    <text x="{tx:.1f}" y="{ty:.1f}" font-family="sans-serif" '
                f'font-size="{NUMBER_TYPE}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{color}"{turn}>{escaped(name)}</text>'
            )
            if number.leader is not None:
                (ax0, ay0), (ax1, ay1) = number.leader
                lines.append(f'    <line x1="{ax0:.1f}" y1="{ay0:.1f}" '
                             f'x2="{ax1:.1f}" y2="{ay1:.1f}" '
                             f'stroke="{color}" '
                             f'stroke-width="{LineWeight.DETAIL.width:g}" />')
                lines.append(f'    <path d="{_arrowhead(*number.leader)}" fill="{color}" />')
        # ``placed`` holds every box both label passes reserved.
        if plates is not None:
            plates.extend(placed)
        lines.append('  </g>')
        return lines
