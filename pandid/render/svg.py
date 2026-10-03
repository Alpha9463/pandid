"""Render a flowsheet as SVG.

:class:`SvgRenderer` draws the sheet. The module-level functions compute
what both backends share (label placement, crossing marks, flags, line
weights, sheet sizing and render-argument checks), so the draw.io export
in :mod:`pandid.render.drawio` draws the same sheet.
"""

from typing import NamedTuple, TYPE_CHECKING
import math
import re
from datetime import datetime
from functools import lru_cache

from pandid.render import furniture as F
from pandid.render.escape import escaped, ident
from pandid.render.symbols import (ARROWHEAD, closed_marking, fail_marking,
                                   wears_arrowhead)
from pandid.render.weights import LineWeight
from pandid.route_geometry import stream_polyline
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.document import TitleBlock
    from pandid.flowsheet import Flowsheet

# A symbol's own lettering: the "M" in a motor operator, the "S" in a
# solenoid. Matched to be counter-transformed when the symbol is turned
# or flipped.
_SYMBOL_TEXT = re.compile(
    r'<text\b[^>]*?\bx="(-?[\d.]+)"[^>]*?\by="(-?[\d.]+)"[^>]*?>.*?</text>', re.S)
# Balloon variants drawn with a location bar across the middle, which
# their tag text must clear. ``shared`` has a bar and a square: the bar
# says where the information is (ISO 15519-2 Table 1) and the square what
# the function is.
_BARRED_BALLOONS = {"panel", "aux", "shared"}
# Variants drawn as a diamond (ISA-5.1-2009 Table 5.1.1 column B and
# Table 5.1.2 items 3-5): the interlock number sits where the sloping
# sides leave room for it.
_DIAMOND_BALLOONS = {"sis", "logic", "interlock"}
# Variants that stand for a device in the field. Every other ISA-5.1
# balloon places the function in a panel, shared display, computer or
# logic solver (Table 5.1.1, Table 5.1.2), which has no process fluid
# piped to it; see :func:`impulse_tap`. Listed positively so a new
# location symbol defaults to a dashed (signal) line.
_FIELD_BALLOONS = {"default"}

#: Values ``label_pos`` accepts: the four faces, in the order layout tries
#: them (:data:`pandid.layout.coordinates.LABEL_SIDES`), and ``"center"``,
#: which layout never picks but a balloon or an author may ask for.
#:
#: :meth:`SvgRenderer._label_place`, ``pandid.render.drawio._LABEL_SIDE``
#: and :func:`pandid.validate.model_issues` all use this tuple, and
#: ``tests/test_render_api`` keeps them in step. ``"top_right"`` is only
#: for the ``NC`` marking (ISO 15519-1 11.4.5;
#: :meth:`SvgRenderer._nc_label_item`).
LABEL_POSITIONS = ("top", "bottom", "right", "left", "center")

# --- line weights -----------------------------------------------------
# Every width comes from :class:`~.weights.LineWeight`, the 4:2:1 ladder
# in :mod:`pandid.render.weights`. Each element states its rung where it
# is drawn. Material runs are main flow lines (ISO 10628-1 5.3.1 a)).

# Dash pattern per signal kind; pneumatic lines are solid and hatched
# instead. Shared with the draw.io export.
_SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                "capillary": "3,3"}

# Dash for a tap line carrying a measurement or command rather than
# process fluid (an impulse line is solid); see :func:`impulse_tap`.
# Shared with the draw.io export.
_TAP_DASH = "5,4"


#: Radius of a crossing mark: half the run an arc or gap takes out, and
#: how far an arc stands off the run. draw.io sizes its hop differently;
#: :func:`pandid.render.drawio._jump_size` converts.
#:
#: Derived from the pen so the paper an arc leaves stays constant::
#:
#:     clearance = HOP_R - w_hop / 2 - w_crossed / 2
#:
#: :data:`_HOP_CLEARANCE` is that paper for two main flow runs, the widest
#: pair, so it is a floor for every crossing. No standard dimensions a
#: crossing mark. A larger radius is not free: ``_draw_streams`` marks
#: only segments longer than ``2 * HOP_R``, so more crossings would go
#: unmarked (drawn plain, as
#: :data:`~pandid.render.drawio.HOP_DROPPED` also does).
_HOP_CLEARANCE = 3.0
HOP_R = _HOP_CLEARANCE + LineWeight.MAIN_FLOW.width

#: How a crossing of two unconnected runs may be marked, chosen per sheet
#: (see :func:`check_crossing_style`):
#:
#: * ``"gap"`` -- the default: the interruption ISO 10628-1 5.3.4
#:   prescribes, cut over the same ``2 * HOP_R`` of run an arc spans. The
#:   break comes out of the run, so a crossing near a corner leaves a
#:   short leg.
#: * ``"arc"`` -- a semicircular bridge, a drafting convention this
#:   library offers for house styles; no standard specifies it.
#: * ``"plain"`` -- both lines continuous, as ISO 15519-1 12.5 Figure 31
#:   draws a crossing; junctions then carry the mark instead.
#:
#: Mixing styles on one sheet would break the convention a reader learns,
#: so the style applies to the whole sheet.
CROSSING_STYLES = ("arc", "gap", "plain")

#: Crossing style used when none is given: ``"gap"``, since ISO 10628-1
#: 5.3.4 asks for an interruption and 4.1 applies Clause 5 to every
#: diagram this package draws. Public entry points default to it;
#: ``test_every_crossing_style_default_is_the_package_default`` checks
#: every module-level function taking ``crossing_style``.
CROSSING_STYLE_DEFAULT = "gap"

# --- stream-label placement -------------------------------------------
# A label on its opaque halo may sit on the pipe only where the run
# leaves this much pipe showing at each end (room for an ARROWHEAD and a
# visible line); otherwise it goes beside the pipe.
_LABEL_CLEAR = 20.0
# Gap from the pipe to the near edge of a label written beside it.
_LABEL_GAP = 4.0
# Search step along the run.
_LABEL_STEP = 6.0
# Number of sideways stand-off bands the search tries, nearest first. A
# bound on the search; seven is the fewest that places every label on the
# example sheets, and more bands do not move them.
_LABEL_BANDS = 7

def _class_weight(sym) -> LineWeight:
    """Return the line weight a symbol's outline is drawn at.

    Symbols marked :attr:`~.symbols.Symbol.trim` (valves, fittings,
    piping accessories, PCE; ISO 10628-1 5.3.1 c)) use the detail rung;
    equipment and machinery (5.3.1 b)) use the equipment rung. Artwork is
    drawn at one nominal weight (:func:`_nominal`) and scaled to the rung
    at render time (see :meth:`SvgRenderer._defs`).

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
    """Return the line weight of a stream, for both backends.

    Material runs are main flow lines (ISO 10628-1 5.3.1 a)); there is
    no way yet to mark one subsidiary. Signal lines use the detail rung
    (5.3.1 c)).

    Parameters
    ----------
    signal : bool
        Whether the stream is a signal line.

    Returns
    -------
    LineWeight
        Line rung.
    """
    return LineWeight.DETAIL if signal else LineWeight.MAIN_FLOW


def _ink_pad(rung: LineWeight) -> float:
    """Return how far an opaque plate must stop from a line on a rung.

    Half the pen plus one unit of paper; see :func:`_ink`.

    Parameters
    ----------
    rung : LineWeight
        Line weight.

    Returns
    -------
    float
        Padding in drawing units.
    """
    return rung.width / 2 + LineWeight.DETAIL.width


# Paper a label plate leaves outside a symbol's ink. A unit box is the
# geometry and the outline is stroked centred on it, so half the pen lies
# outside the box; a plate flush with the box would erase it.
_PLATE_CLEARANCE = 2.0


def _obstacle(box) -> "tuple[float, float, float, float]":
    """Return a symbol box grown to the area a label must keep off.

    Both label passes (:meth:`SvgRenderer._tag_item` and
    :func:`stream_numbers`) use this, so they agree on where a symbol
    ends; the draw.io export passes its own boxes through it too. The pad
    assumes the heavier equipment rung for every symbol, which keeps labels
    at least as far from real ink as needed.

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
    """Return whether a label lies along the run from ``lo`` to ``hi``.

    ISO 15519-1 7.2.5 writes a connection's designation along or beside
    its line, or elsewhere with a leader. More than half the label must
    lie alongside the run; below that :func:`_leader` takes over. On the
    example sheets the labels fall clearly either side of 50%, which
    ``tests/test_label_invariants.py`` checks.

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
    """Yield label anchors along a run, centred first, then alternately out.

    Parameters
    ----------
    x, y : float
        Centre anchor.
    room : float
        Distance available either way.
    vertical : bool
        Whether the run is vertical.

    Yields
    ------
    tuple[float, float]
        Anchor points.
    """
    yield x, y
    for k in range(1, int(room // _LABEL_STEP) + 1):
        d = k * _LABEL_STEP
        yield (x, y - d) if vertical else (x - d, y)
        yield (x, y + d) if vertical else (x + d, y)


# --- the ink a halo would delete --------------------------------------
# Labels sit on opaque halos, so routed segments and impulse lines count
# as occupied alongside symbol boxes: a halo over another line would make
# it look broken.


class _Ink(NamedTuple):
    """A drawn line, as the rectangle its stroke covers.

    A label may break its own run but no other line, so each piece
    records the infinite line it lies on and which run it belongs to;
    collinear segments of two runs are still two runs.

    Attributes
    ----------
    x0, y0, x1, y1 : float
        Covered rectangle.
    axis : str
        ``"h"`` or ``"v"``.
    at : float
        The ``y`` of a horizontal line or ``x`` of a vertical one.
    kind : str
        ``"pipe"`` or ``"tap"``.
    line : str
        Stream number of the run, or ``""`` for an impulse line.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    axis: str
    at: float
    kind: str  # "pipe" or "tap"
    line: str  # the stream number this is part of, or "" for a tap

    @property
    def box(self) -> "tuple[float, float, float, float]":
        """Return the covered rectangle ``(x0, y0, x1, y1)``."""
        return (self.x0, self.y0, self.x1, self.y1)


def tap_lines(fs):
    """Return every impulse line as ``(instrument, tap, balloon centre)``.

    No line is drawn where the balloon is only placed near its host
    (``relation="near"``; see :data:`~pandid.units.RELATIONS`), where a
    stream already joins the two, or where the element sits on the line
    (``offset=0``). The drawing pass, label placement and the draw.io
    export all use this, so labels avoid exactly the lines drawn.

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


def impulse_tap(inst) -> bool:
    """Return whether the line from a balloon to its host is impulse tubing.

    Impulse tubing carries process fluid, so all three must hold: the host
    holds fluid (not a balloon or signal line), the relation is
    ``"sensing"`` (fluid comes to the instrument), and the balloon is a
    field device (:data:`_FIELD_BALLOONS`). Otherwise the line is a dashed
    signal.

    Parameters
    ----------
    inst : Instrument
        Attached balloon.

    Returns
    -------
    bool
        Whether the tap line is drawn solid as impulse tubing.
    """
    host = getattr(inst, "host", None)
    host_kind = getattr(host, "kind", "")
    holds_fluid = (host is not None and host_kind != "instrument"
                   and host_kind not in _SIGNAL_KINDS)
    return (holds_fluid
            and getattr(inst, "relation", "sensing") == "sensing"
            and getattr(inst, "variant", "default") in _FIELD_BALLOONS)


# --- letter codes written outside the symbol --------------------------
# ISO 15519-2 5.1.3 (Figure 8) writes codes outside a PCI symbol in the
# four corner quadrants, leaving the faces free for connections. 5.2.5
# puts high functions above the centre line and low below, but not which
# side, so each pair keeps its half and takes the side with room.
# Quadrants: (a) references and safety identifiers, (b) the variable for
# letter code U, (c) high functions, (d) low functions.

# Quadrant -> (side, away): which side of the symbol and which way a
# second code stacks; +1 is right or down.
_QUADRANTS = {"a": (-1, -1), "b": (-1, 1), "c": (1, -1), "d": (1, 1)}

# The two quadrant pairs, placed in order, with each pair's preferred
# side. A pair is read as one column.
_QUADRANT_PAIRS = ((("a", "b"), -1), (("c", "d"), 1))

# Paper kept clear either side of the centre line, where a connection
# arrives between the two codes.
_QUADRANT_BAND = 3.0
# Gap from the symbol's edge to the code, about 0.12 balloon diameters as
# on the reference P&ID.
_QUADRANT_GAP = 5.0
# Pitch of two codes in one quadrant: one line of type.
_QUADRANT_PITCH = 15.0
# Furthest a quadrant may move outward to find clear paper; the quadrant
# itself is fixed by meaning.
_QUADRANT_REACH = 60.0


def quadrant_labels(fs, direction: str) -> list:
    """Return every letter code written outside a symbol, placed.

    Items use :meth:`SvgRenderer._draw_unit_labels`' form, so codes are
    haloed like tags. Derived from the flowsheet alone, as
    :func:`stream_numbers` is, so the tag and line-number passes avoid the
    same positions.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out sheet.
    direction : str
        ``jump_direction``, which decides which run draws a crossing arc.

    Returns
    -------
    list
        Label items ``(x, y, anchor, baseline, lpos, text)``.
    """
    from pandid.portgeom import unit_box

    annotated = [u for u in fs.units
                 if u.frame is not None and getattr(u, "quadrants", None)]
    if not annotated:
        return []
    ink = _ink(fs, direction)
    symbols = [_obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    symbols += [_obstacle(b) for b in flange_boxes(fs, None)]

    out: list = []
    for u in annotated:
        box = unit_box(u, u.frame)
        for names, prefers in _QUADRANT_PAIRS:
            codes = {name: u.quadrants.get(name) or () for name in names}
            if not any(codes.values()):
                continue
            # Try the preferred side first; the other wins only if cleaner.
            best = None
            for side in (prefers, -prefers):
                block = _quadrant_block(box, codes, side)
                shift, damage = _quadrant_stand_off(block, side, ink, symbols)
                if best is None or damage < best[0]:
                    best = (damage, [(x + side * shift, y, *rest)
                                     for x, y, *rest in block])
                if damage == (0, 0, 0):
                    break
            assert best is not None
            out.extend(best[1])
            # Placed codes become obstacles for later pairs and balloons.
            symbols += [b for b in map(_unit_label_box, best[1]) if b is not None]
    return out


def _quadrant_block(box, codes, side: int) -> list:
    """Return one side's codes laid out from the symbol's box outward.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Symbol box.
    codes : dict[str, tuple[str, ...]]
        Codes keyed by quadrant letter; :data:`_QUADRANTS` sets which is
        above the centre line.
    side : int
        ``1`` for right, ``-1`` for left.

    Returns
    -------
    list
        Label items.
    """
    cy = (box[1] + box[3]) / 2
    lx = (box[2] if side > 0 else box[0]) + side * _QUADRANT_GAP
    anchor, lpos = ("start", "right") if side > 0 else ("end", "left")
    return [
        (lx,
         cy + _QUADRANTS[name][1] * (_QUADRANT_BAND + _QUADRANT_PITCH / 2
                                     + i * _QUADRANT_PITCH),
         anchor, "middle", lpos, escaped(code))
        for name in codes
        for i, code in enumerate(codes[name])
    ]


def _quadrant_stand_off(block, side: int, ink, symbols):
    """Return how far outward to move a pair of codes, and what remains hit.

    The pair moves together and only outward, so each code stays in its
    quadrant. Positions are scored with :func:`_erases`; the smallest step
    that clears wins.

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
        """Return the :func:`_erases` total with the block shifted by ``m``."""
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
    """Return every drawn line as the rectangle its stroke covers.

    Each line is padded by half its pen plus a unit of paper, so a halo
    neither erases nor crowds it. Paths come from
    :func:`~pandid.layout.attach.stream_path`, as drawn. Crossing arcs
    (:func:`stream_hops`) are included, since a halo cutting one would make
    two crossing lines look joined.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    direction : str
        :meth:`SvgRenderer.render`'s ``jump_direction``, which decides which
        run draws each arc. Required so the arcs match the drawing.

    Returns
    -------
    list[_Ink]
        Pipe, tap and hop rectangles.
    """
    from pandid.layout.attach import stream_path

    out: list[_Ink] = []

    def add(a, b, pad: float, kind: str, line: str = "") -> None:
        """Append the padded rectangle of segment ``a``-``b``."""
        (ax, ay), (bx, by) = a, b
        if abs(ax - bx) < 0.5 and abs(ay - by) < 0.5:
            return  # a zero-length hop between coincident points draws nothing
        axis, at = ("v", (ax + bx) / 2) if abs(ax - bx) < abs(ay - by) else ("h", (ay + by) / 2)
        out.append(_Ink(min(ax, bx) - pad, min(ay, by) - pad,
                        max(ax, bx) + pad, max(ay, by) + pad, axis, at, kind, line))

    for s in fs.streams:
        # Half the pen of ink, then one unit (the finest rung) of paper.
        pad = _ink_pad(_stream_rung(s.kind in _SIGNAL_KINDS))
        points = stream_path(s)
        for a, b in zip(points, points[1:]):
            add(a, b, pad, "pipe", s.name or "")
    for _u, tap, centre in tap_lines(fs):
        # A tap is ISO 10628-1 5.3.1 c) and stands off the same way.
        add(tap, centre, _ink_pad(LineWeight.DETAIL), "tap")
    # A hop belongs to the run that draws it (``line``), so other labels
    # treat it as foreign ink while ``_along`` counts it as part of its run.
    # Scored with pipes and padded off the run's own rung.
    for hop in stream_hops(fs, direction):
        run = fs.streams[hop.stream]
        pad = _ink_pad(_stream_rung(run.kind in _SIGNAL_KINDS))
        x0, y0, x1, y1 = hop_box(hop, pad)
        out.append(_Ink(x0, y0, x1, y1, "v" if hop.vertical else "h",
                        hop.x if hop.vertical else hop.y, "hop", hop.line))
    return out


def _meets(box, region) -> bool:
    """Return whether two rectangles overlap; touching edges do not count.

    Parameters
    ----------
    box, region : tuple[float, float, float, float]
        Rectangles ``(x0, y0, x1, y1)``.

    Returns
    -------
    bool
        Whether they share area.
    """
    return (box[2] > region[0] and box[0] < region[2]
            and box[3] > region[1] and box[1] < region[3])


def _erases(box, ink, symbols=()) -> "tuple[int, int, int]":
    """Return what a halo at ``box`` would erase: symbols, taps, pipes.

    Ordered by cost, and compared as a tuple. A symbol is worst, since its
    outline identifies it (a circle against a circle in a square). An
    impulse line is short and shows where a measurement is taken. A pipe
    reads across a gap, which is why labels may sit in a run.

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
        Symbols, impulse lines and pipe pieces hit.
    """
    hits = sum(1 for b in symbols if _meets(box, b))
    taps = pipes = 0
    for line in ink:
        if _meets(box, line.box):
            if line.kind == "tap":
                taps += 1
            else:
                pipes += 1
    return hits, taps, pipes


def _covering(box, occupied, symbols=(), limit=None) -> "tuple[int, int]":
    """Return what a halo at ``box`` covers: symbols, then everything else.

    Kept as two counts, as in :func:`_erases`, so covering a symbol never
    trades against covering lines. Counting stops once the score exceeds
    ``limit``.

    Parameters
    ----------
    box : tuple[float, float, float, float]
        Halo box.
    occupied : Iterable[tuple[float, float, float, float]]
        Other occupied boxes.
    symbols : Sequence[tuple[float, float, float, float]], optional
        Obstacle boxes.
    limit : tuple[int, int], optional
        Best score so far.

    Returns
    -------
    tuple[int, int]
        Symbols covered and other boxes covered.
    """
    hits = sum(1 for b in symbols if _meets(box, b))
    n = 0
    for p in occupied:
        if _meets(box, p):
            n += 1
            if limit is not None and (hits, n) > limit:
                break
    return hits, n


def _step_aside(item, room: float, ink=(), others=()):
    """Slide a valve's position mark along its face until it erases nothing.

    A mark such as ``FC`` below a valve (PIP PIC001 4.2.4.6(1)) can sit on
    an impulse line leaving the same face, which ISO 15519-2 5.1.1 requires
    to be drawn. Moving along the face clears such a line; moving outward
    would follow it. Candidates are the distances that clear each obstacle
    by :data:`_PLATE_CLEARANCE`; the nearest clear one wins, ties going
    right and down.

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
        The moved item, or ``item`` if nothing is better.
    """
    box = _unit_label_box(item)
    if box is None or not (ink or others):
        return item
    lx, ly, anchor, baseline, lpos, text = item
    # A left or right face runs vertically, so slide in y.
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

    On the pipe first, while the run still shows clear line at each end
    (a long line number takes less room on the pipe than beside it); then
    beside it, above a horizontal run or left of a vertical one as ISO
    15519-1 7.2.5 recommends, then the far side, then further out. Each
    position slides along the run before the next band is tried. Whether
    a leader is needed is :func:`_along`'s question.

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
        Keep the label on the run (an enclosure, whose meaning is that the
        run passes through it); no side bands are offered.
    plate : float
        Opaque length of the label along the run, which bounds the slide;
        an enclosure's outline is see-through, so only its words count.

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


# --- the leader that stands in for adjacency --------------------------
# ISO 15519-1 6.4: a leader ending on a connection takes an arrowhead,
# and Figure 4 c) draws it oblique onto the line with the text at its
# upper end. The slope keeps it from reading as a connecting line, which
# 12.1 holds to horizontal or vertical. The head resembles the flow
# arrowhead, and 6.4 offers no other terminator, so leaders are a last
# resort after writing the number along its line (7.2.5; :func:`_along`).

# Leader arrowhead size: half the flow arrowhead, same proportions, since
# the leader is a narrow line (ISO 128-22).
_LEADER_HEAD = ARROWHEAD / 2


#: Issue code for a crossing the sheet could not mark; see
#: :func:`unmarked_crossings`.
CROSSING_UNMARKED = "crossing-unmarked"


def unmarked_crossings(fs, jump_direction: str = "vertical",
                       crossing_style: str = "gap") -> list:
    """Return every crossing the sheet draws without its mark.

    An arc or gap needs :data:`HOP_R` of the marked run either side of the
    crossing; with less, the runs are drawn straight through. Both styles
    need the same room. On a sheet where other crossings carry a mark, a
    bare one may read as a junction, so :meth:`SvgRenderer.render` reports
    each as a :data:`CROSSING_UNMARKED` warning. ``tests/test_render.py``
    checks this agrees with the marks ``_draw_streams`` draws.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    jump_direction : str, default="vertical"
        Which run carries the mark.
    crossing_style : str, default="gap"
        ``"plain"`` returns nothing, since no crossing is marked.

    Returns
    -------
    list[tuple[Stream, Stream, float, float]]
        ``(marked, crossed, x, y)`` per crossing.
    """
    if crossing_style == "plain":
        return []
    segments = []
    for stream in fs.streams:
        points = stream_polyline(stream)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                segments.append((stream, "h", min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                segments.append((stream, "v", min(y1, y2), max(y1, y2), x1))

    marks = "v" if jump_direction == "vertical" else "h"
    out = []
    for stream, axis, lo, hi, at in segments:
        if axis != marks:
            continue
        for other, o_axis, o_lo, o_hi, o_at in segments:
            if o_axis == axis or not (o_lo < at < o_hi) or not (lo < o_at < hi):
                continue
            if lo + HOP_R < o_at < hi - HOP_R:
                continue  # room for the mark; the sheet draws it
            x, y = (at, o_at) if axis == "v" else (o_at, at)
            out.append((stream, other, x, y))
    return out


def _crossing_issues(fs, jump_direction: str = "vertical",
                     crossing_style: str = "gap") -> list:
    """Return :func:`unmarked_crossings` as warnings.

    The message names the mark style and suggests moving the crossing with
    ``via()`` or drawing every crossing ``"plain"``.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    jump_direction : str, default="vertical"
        Which run carries the mark.
    crossing_style : str, default="gap"
        Crossing mark style.

    Returns
    -------
    list[Issue]
        One :data:`CROSSING_UNMARKED` warning per bare crossing.
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

    Liang-Barsky clipping; grazing an edge does not count.

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
                return False   # parallel to this pair of edges, and outside them
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
    """Return how many occupied boxes a leader cuts, counting up to a limit.

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


def _near_segment(p, a, b, tol: float = 0.5) -> bool:
    """Return whether ``p`` lies on segment ``a``-``b`` within ``tol``.

    Parameters
    ----------
    p, a, b : tuple[float, float]
        Point and segment end points.
    tol : float, default=0.5
        Distance tolerance.

    Returns
    -------
    bool
        Whether the point is on the segment.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    if not span:
        return math.hypot(p[0] - a[0], p[1] - a[1]) <= tol
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy)) <= tol


def _leader(box, seg, occupied, keep_out: float = 0.0) -> "tuple[tuple, int]":
    """Return the leader joining a label halo to its run, and what it cuts.

    Each candidate leaves the halo's near face and lands about 45 degrees
    along the run (ISO 15519-1 Figure 4), so the leader follows the label
    as it slides. Starts are swept along the face, inset by about one
    character from the corners, and ranked by: boxes cut, closeness to 45
    degrees, then closeness to the middle of the face. The landing point
    keeps :data:`_LABEL_CLEAR` (or a third of a short run) from the run's
    ends, where a head would point at the equipment instead.

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
        ``((start, end), crossings)``: the leader, ending on the run, and
        how many occupied boxes it cuts.
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
    # Only where the run is long enough to keep a landing band.
    if keep_out and hi - lo > 3 * keep_out:
        lo, hi = lo + keep_out, hi - keep_out
    inset = min(_LABEL_CLEAR, (hi - lo) / 3)
    near, far = lo + inset, hi - inset

    def route(s: float):
        """Return the leader from face position ``s``, landing 45 degrees along.

        The direction landing furthest from ``s`` is nearest 45 degrees,
        since clamping to the run can only shorten it.
        """
        u = max((min(max(s + d * gap, near), far) for d in (1.0, -1.0)),
                key=lambda c: abs(c - s))
        return ((v, s), (at, u)) if vertical else ((s, v), (u, at))

    # Inset the face so the tail starts at the lettering, at most a
    # quarter of a short face.
    ends = min(abs(v1 - v0) / 2, (u1 - u0) / 4)
    first, last, mid = u0 + ends, u1 - ends, (u0 + u1) / 2
    starts = [first + k * _LABEL_STEP
              for k in range(int((last - first) // _LABEL_STEP) + 1)] + [last]

    def scored(s: float, limit: int):
        """Return the leader from ``s`` and its ranking key."""
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
        Which way an arc bulges: ``+1`` towards greater x (or y), ``-1``
        the other way.
    stream : int
        Index of the marked run in ``fs.streams``.
    seg : int
        Index of its segment in :func:`stream_polyline`.
    line : str
        Marked run's number; other labels treat the mark as foreign ink.
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

    Shared by :meth:`SvgRenderer._draw_streams` and :func:`_ink`, so labels
    avoid the marks, which are not part of any route.

    With ``direction="vertical"`` a vertical segment carries the mark over
    a horizontal one, and the reverse for ``"horizontal"``. A run that
    ends on another is a junction, not a crossing, and the mark needs
    :data:`HOP_R` of the marked segment either side. Any other value
    raises, as :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw` would,
    for callers that bypass a flowsheet.

    An arc bulges by SVG's clockwise sweep (y down): a run drawn downward
    bulges right, upward left, rightward up, leftward down.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    direction : str
        ``"vertical"`` or ``"horizontal"``.

    Returns
    -------
    list[_Hop]
        Crossing marks.

    Raises
    ------
    ValueError
        If ``direction`` is not a known value.
    """
    check_jump_direction(direction)
    geoms = [(s, stream_polyline(s)) for s in fs.streams]
    horizontals: list[tuple[float, float, float]] = []
    verticals: list[tuple[float, float, float]] = []
    for _s, points in geoms:
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2:
                horizontals.append((min(x1, x2), max(x1, x2), y1))
            elif x1 == x2:
                verticals.append((x1, min(y1, y2), max(y1, y2)))

    out: list[_Hop] = []
    for n, (s, points) in enumerate(geoms):
        name = s.name or ""
        for i, ((x1, y1), (x2, y2)) in enumerate(zip(points, points[1:])):
            if direction == "vertical" and x1 == x2:
                cuts = sorted((hy for mnx, mxx, hy in horizontals
                               if mnx < x1 < mxx
                               and min(y1, y2) + HOP_R < hy < max(y1, y2) - HOP_R),
                              reverse=y1 > y2)
                side = 1.0 if y1 < y2 else -1.0
                out += [_Hop(x1, hy, True, side, n, i, name) for hy in cuts]
            elif direction == "horizontal" and y1 == y2:
                cuts = sorted((vx for vx, my, my2 in verticals
                               if my < y1 < my2
                               and min(x1, x2) + HOP_R < vx < max(x1, x2) - HOP_R),
                              reverse=x1 > x2)
                side = -1.0 if x1 < x2 else 1.0
                out += [_Hop(vx, y1, False, side, n, i, name) for vx in cuts]
    return out


def hop_box(hop: _Hop, pad: float) -> "tuple[float, float, float, float]":
    """Return the padded bounding box of a crossing arc.

    The box of the semicircle on its bulging side only; the other side of
    the run stays free. A rectangle slightly over-reserves the corners,
    which errs on the safe side.

    Parameters
    ----------
    hop : _Hop
        Crossing mark.
    pad : float
        Padding, as for a line.

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


#: Font size of a line number. The halo under it is the estimated string
#: width plus a gutter, by a fixed depth; the export uses the same sizes.
NUMBER_TYPE = 10
_HALO_CHAR, _HALO_PAD, _HALO_DEEP = 6.2, 6.0, 13.0

# Gap a box enclosure leaves outside the halo on each side. A diamond or
# circle touches the halo only at its corners, which are blank paper; a
# box's sides run parallel to the words and need the gap.
_ENCLOSURE_PAD = 4.0

# Enclosure stroke: the narrow annotation line a leader also uses (ISO
# 15519-1 6.4, ISO 128-22), a quarter of a main flow line so it does not
# read as plant.
_ENCLOSURE_STROKE = LineWeight.DETAIL.width

#: Enclosures unchanged by a quarter turn, whose numbers stay upright on a
#: vertical run (see ``turned`` in :func:`stream_numbers`).
#: :mod:`pandid.render.drawio` reads it too.
UPRIGHT_ENCLOSURES = ("diamond", "circle")


def enclosure_shape(fs) -> str:
    """Return the enclosure shape for every stream label on a sheet.

    Read from the flowsheet so both backends agree. Checked again here for
    callers that bypass :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw`.

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

    Sizes are measured along the words, then across; a label on a vertical
    run swaps them.

    * ``diamond`` -- the smallest square turned 45 degrees containing the
      halo. With a halo corner on the edge, ``p/a + q/b <= 1`` and
      ``a = b = d`` give ``d = (hw + hh) / 2``, a box ``hw + hh`` each way.
      This is shorter along the run than the minimum-area rhombus, which
      matters because the reach along the run is what collides.
    * ``circle`` -- the circumscribed circle, diameter the halo's
      diagonal; tightest for long labels, but it resembles an ISA balloon
      (see :class:`~pandid.document.StreamLabelOptions`).
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

    The outline is hollow unless :func:`fillable_enclosures` found it
    touches only its own run, and the white plate under the words covers
    only that run (:func:`stream_numbers`). Where no such place exists the
    plate is omitted (``words`` is ``None``) and the crossing line is drawn
    through the number, reported by :func:`label_findings`: a crowded
    number is better than a line with a piece missing. A clipped fill
    would need ``<clipPath>``, which :mod:`pandid.render.export` refuses.

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
        SVG elements: plate, then outline. The words are written by the
        caller, on top.
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
    # Fill white only where the shape reaches nothing but its own run. The
    # label pass runs after every run is drawn, so the fill hides the run
    # inside the outline.
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
    # Draw the plate, then the outline over it: a diamond's or circle's
    # outline touches the halo corners, which would otherwise notch it.
    return [*plate, outline]


class StreamNumber(NamedTuple):
    """One placed line number.

    Both backends read these fields rather than re-deriving them, so the
    ``.drawio`` file matches the sheet.

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
        Whether the words are turned to read bottom to top. Words stay
        upright in a diamond or circle on a vertical run
        (:data:`UPRIGHT_ENCLOSURES`).
    box : tuple
        Enclosure shape's box, or the halo where none is drawn.
    leader : tuple or None
        Leader end points, or ``None`` when written along the run.
    words : tuple or None
        Opaque plate under the string; equals ``box`` with no enclosure,
        and is ``None`` when any plate would erase another line.
    crossed : tuple[str, ...]
        Runs the number is written across, if any. Recorded here, where
        the plate and the ink are both known.
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
    """Choose one readable label position for each named material run.

    The number goes on the run's longest segment. Candidates come from
    :func:`_label_anchors` and are ranked by: other lines the plate would
    erase, symbols and labels covered, then boxes a leader would cut. The
    first spot with no damage wins. A plate is never laid over another
    run: where no spot avoids one, the number is written without a plate
    and the runs it crosses are recorded for :func:`label_findings`.

    Parameters
    ----------
    fs : Flowsheet
        Routed drawing whose stream names are placed.
    placed : list
        Occupied label boxes; selected boxes are appended to this list.
    joints : str or None
        Sheet-wide connection style.
    direction : str
        ``jump_direction``, which decides where crossing marks are drawn.

    Returns
    -------
    list[StreamNumber]
        Label placements shared by SVG and draw.io output.
    """
    from pandid.portgeom import unit_box

    ink = _ink(fs, direction)
    symbols: list[tuple[float, float, float, float]] = [
        _obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None
    ]

    # Flange marks and quadrant codes are obstacles like symbols.
    symbols += [_obstacle(b) for b in flange_boxes(fs, joints)]
    symbols += [b for b in map(_unit_label_box, quadrant_labels(fs, direction))
                if b is not None]

    # One number per run name, through inline valves and fittings, on the
    # longest segment.
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
        # Length the segment's own flange marks take at its ends, if any.
        (mx1, my1), (mx2, my2) = longest_seg
        keep = FLANGE_STANDOFF + FLANGE_GAP / 2 if any(
            _near_segment((m.x, m.y), (mx1, my1), (mx2, my2))
            for m in flange_marks(carrier, carrier_points, resolve_connections(carrier, joints))
        ) else 0.0
        label_items.append((longest_seg, s.name, s.color or "black", keep))

    # Enclosures are one size per sheet, fitted to the longest label, so
    # the shapes do not vary along a process. The plate under the words
    # stays per label, since a wider plate would erase more pipe.
    shape = enclosure_shape(fs)
    widest = max((len(name) * _HALO_CHAR + _HALO_PAD
                  for _s, name, _c, _k in label_items), default=0.0)
    uniform = enclosure_box(shape, widest, _HALO_DEEP)

    out: list[StreamNumber] = []
    for seg, name, color, keep in label_items:
        (sx1, sy1), (sx2, sy2) = seg
        # The words' size, and the reserved size (the enclosure, if any).
        tw, th = len(name) * _HALO_CHAR + _HALO_PAD, _HALO_DEEP
        hw, hh = (tw, th) if shape == "none" else uniform
        cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
        vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
        span = abs(sy2 - sy1) if vertical else abs(sx2 - sx1)
        # A bare or boxed number follows its run (ISO 15519-1 7.2.5,
        # Figure 40: bottom to top on a vertical line). Inside a diamond or
        # circle it reads horizontally, like a balloon, since neither shape
        # changes under a quarter turn.
        turned = vertical and shape not in UPRIGHT_ENCLOSURES
        # The enclosure follows the run; upright shapes are square anyway.
        bw, bh = (hh, hw) if vertical else (hw, hh)
        lw, lh = (th, tw) if turned else (tw, th)

        # The area any anchor can reach; obstacles outside it are dropped.
        along = (span + hw) / 2 + max(bw, bh) / 2
        across = hh / 2 + _LABEL_GAP + _LABEL_BANDS * hh + max(bw, bh) / 2
        rx, ry = (across, along) if vertical else (along, across)
        window = (cx - rx, cy - ry, cx + rx, cy + ry)

        axis, at = ("v", (sx1 + sx2) / 2) if vertical else ("h", (sy1 + sy2) / 2)
        # Extent of the whole collinear run, through inline valves, which
        # is what :func:`_along` measures against.
        run_lo = min(sy1, sy2) if vertical else min(sx1, sx2)
        run_hi = max(sy1, sy2) if vertical else max(sx1, sx2)
        for line in ink:
            if line.line == name and line.axis == axis and abs(line.at - at) < 0.5:
                run_lo = min(run_lo, line.y0 if vertical else line.x0)
                run_hi = max(run_hi, line.y1 if vertical else line.x1)

        near_symbols = [p for p in symbols if _meets(p, window)]
        occupied = [p for p in placed if _meets(p, window)]
        occupied += [line.box for line in ink
                     if not (line.axis == axis and abs(line.at - at) < 0.5)
                     and _meets(line.box, window)]
        # Other runs' ink, by name (collinear runs are still separate), and
        # every tap. The plate must never cover these.
        foreign = [line for line in ink
                   if line.line != name and _meets(line.box, window)]
        # A leader avoids the same things as the halo.
        everything = near_symbols + occupied

        # Anchors come best first; the first clear spot wins, otherwise the
        # least damaging, ties keeping the earlier. On-pipe anchors come
        # first, since breaking one's own run is a known convention. An
        # anchor not along the run needs a leader, whose cuts score last.
        clear = (0, 0, 0, 0)
        spot: "tuple[float, float] | None" = None
        damage: "tuple[int, int, int, int] | None" = None
        leader: "tuple | None" = None
        for ux, uy, _off in _label_anchors(cx, cy, span, hw, hh, vertical,
                                           shape != "none", tw):
            box = (ux - bw / 2, uy - bh / 2, ux + bw / 2, uy + bh / 2)
            paper = (box if shape == "none" else
                     (ux - lw / 2, uy - lh / 2, ux + lw / 2, uy + lh / 2))
            # Erasing another line ranks above everything else: a pipe shown
            # broken is wrong, while a crowded label is only hard to read.
            erased = sum(1 for line in foreign if _meets(paper, line.box))
            limit = None
            if damage is not None:
                if erased > damage[0]:
                    continue
                limit = damage[1:3] if erased == damage[0] else None
            hits = _covering(box, occupied, near_symbols, limit)
            if limit is not None and hits > limit:
                continue
            # An enclosed label is on its run and never needs a leader.
            lead, cut = ((None, 0)
                         if shape != "none" or _along(box, vertical, run_lo, run_hi)
                         else _leader(box, seg, everything, keep))
            cost = (erased, *hits, cut)
            if damage is None or cost < damage:
                spot, damage, leader = (ux, uy), cost, lead
                if cost == clear:
                    break
        # _label_anchors always yields at least one anchor.
        assert spot is not None and damage is not None
        tx, ty = spot
        halo = (tx - bw / 2, ty - bh / 2, tx + bw / 2, ty + bh / 2)
        # The opaque plate: the halo with no enclosure, the words' box
        # inside one, and none where every spot would erase another line.
        # The runs crossed are recorded here, where both are known.
        paper = (halo if shape == "none" else
                 (tx - lw / 2, ty - lh / 2, tx + lw / 2, ty + lh / 2))
        words = None if damage[0] else paper
        crossed = () if words is not None else tuple(sorted(
            {line.line or "an instrument connection" for line in foreign
             if _meets(paper, line.box)}))
        placed.append(halo)
        if leader is not None:
            # Reserve the leader's bounding box so later halos avoid it.
            (ax0, ay0), (ax1, ay1) = leader
            placed.append((min(ax0, ax1), min(ay0, ay1),
                           max(ax0, ax1), max(ay0, ay1)))
        out.append(StreamNumber(name, color, seg, tx, ty, turned, halo,
                                leader, words, crossed))
    return out


# Issue codes from the stream-label pass. ``label-over-line`` applies at
# every enclosure setting, the default included.
_LABEL_CODES = ("label-over-line", "enclosure-over-unit",
                "enclosure-over-line", "enclosure-over-label")


def _shape_hits(shape: str, box, rect) -> bool:
    """Return whether an enclosure shape filling ``box`` meets a rectangle.

    Tests the shape, not its bounding box, since a diamond's missing
    corners are where neighbouring lines pass. Both shapes are symmetric,
    so the rectangle's nearest point is found per axis, and
    ``|x|/a + |y|/b`` is separable, making the rhombus test exact.

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
        Whether they share area.
    """
    if not _meets(box, rect):
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
    """Return whether two enclosures of one shape overlap, exactly.

    Testing each shape against the other's bounding box over-reports, since
    two rhombi can each reach into the other's box without touching;
    ``tests/test_stream_label_enclosure.py`` keeps such a pair. Boxes are
    settled by :func:`_meets` and circles by centre distance. Rhombi use
    the separating-axis theorem over both shapes' edge normals ``(b, a)``
    and ``(b, -a)``; a rhombus's extent along ``u`` is
    ``max(|a*ux|, |b*uy|)``.

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
    if not _meets(box, other):
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

    A filled shape hides its own run inside the outline, as drawing
    offices rule it, but is opaque over everything. So a shape is filled
    only when it reaches no symbol, no other run's ink and no other
    enclosure; otherwise it stays hollow and :func:`label_findings`
    reports it. :func:`_ink` slightly over-reserves, so this refuses a few
    safe fills and never allows an unsafe one.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    shape : str
        Enclosure shape; ``"none"`` fills nothing.
    numbers : list[StreamNumber]
        Placed numbers.
    direction : str
        ``jump_direction``.

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
            # Check every other label: both members of a pair stay hollow.
            and not any(other is not number
                        and _shapes_meet(shape, number.box, other.box)
                        for other in numbers)
        )
        out.append(clear)
    return out


def label_findings(fs, shape: str, numbers: "list[StreamNumber]",
                   direction: str) -> "list[Issue]":
    """Return warnings for what stream labels are drawn over.

    An enclosed label must stay on its run, so a shape larger than the
    paper beside it is drawn over something; spacing the sheet is the
    author's choice, and these findings say where. All are warnings because
    nothing is erased: the shape is an outline and the plate covers only
    its own run. If a fill or plate ever covered another run, this would
    have to become an error.

    * ``label-over-line`` -- no plate could be laid without erasing another
      run, so the number is written across it. Raised at every enclosure
      setting.
    * ``enclosure-over-unit`` -- the shape crosses a symbol's box.
    * ``enclosure-over-line`` -- the shape crosses another run's ink.
    * ``enclosure-over-label`` -- two enclosures overlap
      (:func:`_shapes_meet`), reported once per pair from the later label.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    shape : str
        Enclosure shape; ``"none"`` returns only ``label-over-line``.
    numbers : list[StreamNumber]
        Placed numbers.
    direction : str
        ``jump_direction``.

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
            # The shape only; a crossed number is label-over-line's finding.
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


#: Depth of an off-page flag's point. The private insets are the pennant's
#: top and bottom inset in the flag box, smaller when a reference is
#: written under the tag.
FLAG_POINT = 15
_FLAG_INSET, _FLAG_INSET_REF = 15, 12


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

    A rectangle with one end pointed at mid-height, pointing east (west
    when mirrored): the line meets a Feed at its point and a Product at
    its blunt end. The rectangle spans the whole of
    :func:`~pandid.portgeom.unit_box` horizontally (a Feed's box extends
    left of its port) and is inset 12 or 15 units from the top and bottom
    of the placed ``frame.h``, so a resized flag fills its box. ``header``
    does not change the outline. Shared with the draw.io exporter.

    The horizontal extent is computed here rather than read from
    ``unit_box`` so whole-number coordinates format as ``100``, not
    ``100.0``; ``test_a_flag_is_drawn_across_its_own_box`` checks they
    agree.

    Parameters
    ----------
    u : Unit
        Feed or Product.
    frame : Frame
        Its placed frame.

    Returns
    -------
    Pennant
        Flag geometry.
    """
    from pandid.portgeom import _flag_reference

    inset = _FLAG_INSET_REF if _flag_reference(u) else _FLAG_INSET
    if u.kind == "feed" and not frame.mirrored:
        x0, x1 = frame.x + 50 - frame.w, frame.x + 50
    else:
        x0, x1 = frame.x, frame.x + frame.w
    return Pennant((x0, frame.y + inset, x1, frame.y + frame.h - inset),
                   FLAG_POINT, not frame.mirrored)


#: Positions of the two strokes of a pneumatic double cross-hatch along
#: the run, relative to the mark.
HATCH_ALONG = (-2.5, 1.5)
#: Half-reach of each stroke along and across the run. Each stroke leans
#: 6 units along by 10 across, so it reads as a slash. The draw.io
#: exporter derives its stroke angle and length from this.
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
        Euclidean arc length from the source, as
        ``mxGraphView.getPoint`` measures it. Stored because a route that
        doubles back makes the position ambiguous.
    """
    x: float
    y: float
    horizontal: bool
    along: float


def pneumatic_marks(points) -> "list[Hatch]":
    """Return the double cross-hatches marking a pneumatic line.

    ISA-5.1 draws a pneumatic signal as a solid line with double
    cross-hatches, so the hatch is what distinguishes it from piping.
    Marks are spaced every 45 px, and any segment of 16 px or more gets
    at least one. Shared with the draw.io exporter so both mark the same
    places.

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
        # Manhattan length sets the spacing; Euclidean length is what
        # mxGraph measures positions in. They differ only on a slope.
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


#: Joint markings a drawing may state where lines meet what they serve.
#:
#: * ``"none"`` -- no marks; the drawing does not say, which is not the
#:   same as welded.
#: * ``"flanged"`` -- every joint the sheet can mark, including both
#:   sides of valves and in-line fittings.
#: * ``"flanged-at-nozzles"`` -- only where a line meets an equipment
#:   nozzle.
#:
#: See :func:`flanged_joint`.
CONNECTIONS = ("none", "flanged", "flanged-at-nozzles")

# In-line kinds bolted into a run (removable bodies), which "flanged"
# marks; reducers and tees are welded fittings. A subset of
# pandid.flowsheet.INLINE_KINDS, checked by test_render_api.
_INLINE_BODIES = frozenset({"valve", "fitting"})

#: Flanged-connection mark size: two bars 12.5 long and 5.0 apart, as the
#: vendored ``('fitting', 'flange')`` stencil draws them, so the sheet and
#: the draw.io export match. P&ID_301 has the same gap of 1.5 pen widths.
FLANGE_TICK = 12.5
FLANGE_GAP = 5.0

#: Distance from the nozzle to the pair's centre along the run, so the
#: near bar clears the equipment outline.
FLANGE_STANDOFF = 5.0


class Flange(NamedTuple):
    """One flanged-connection mark on a stream.

    Attributes
    ----------
    x, y : float
        Mark centre.
    angle : float
        Run direction at the mark, in degrees; the bars are drawn across
        it. Stored because mxGraph cannot orient a shape on an edge.
    along : float
        Arc length from the source end, as on :class:`Hatch`.
    """
    x: float
    y: float
    angle: float
    along: float


def _draws_its_own_flange(u) -> bool:
    """Return whether a unit's own symbol is the flanged connection.

    Such a fitting already draws the joint, so it is not marked again.
    Compared through the registry's artwork, not variant names.

    Parameters
    ----------
    u : Unit
        In-line unit.

    Returns
    -------
    bool
        True when its artwork is the flange stencil.
    """
    from pandid.render.symbols import default_registry

    own = default_registry.get(u.kind, getattr(u, "variant", "default"))
    return (own.drawio_shape is not None
            and own.drawio_shape == default_registry.get("fitting", "flange").drawio_shape)


def flanged_joint(port, want: str) -> bool:
    """Return whether a joint setting marks this end of a stream.

    No standard on hand settles where flanges are drawn: ISO 15519-1 and
    15519-2 do not mention flanges, and 15519-1 12.4 concerns joins of
    connecting lines (symbol 501, a dot, which may be omitted at a
    T-joint, as this package does). So the setting is a drafting choice.

    Boundary flags and instruments never take a mark. Otherwise:

    ``"flanged"``
        Every equipment nozzle and both sides of every body in the run
        (:data:`_INLINE_BODIES`); reducers and tees stay unmarked.

    ``"flanged-at-nozzles"``
        Equipment nozzles only, as ``P&ID_301.pdf`` draws them.

    Parameters
    ----------
    port : Port
        Stream end.
    want : str
        One of :data:`CONNECTIONS`, already resolved by
        :func:`resolve_connections`.

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
        return (want == "flanged" and kind in _INLINE_BODIES
                and not _draws_its_own_flange(port.owner))
    return True


def flange_marks(s, points, ends) -> "list[Flange]":
    """Return the flange marks one stream carries, in drawing order.

    Signal lines carry none. Shared with the draw.io exporter, since the
    mark sits hard against an outline.

    Parameters
    ----------
    s : Stream
        Stream.
    points : sequence of tuple[float, float]
        Its drawn polyline.
    ends : tuple[str, str]
        Resolved ``(source, dest)`` settings from :data:`CONNECTIONS`.

    Returns
    -------
    list[Flange]
        Marks, at most one per end.
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

        # Stand off the nozzle along the end segment, as the arrowhead does.
        tip = points[-1] if at_dest else points[0]
        neighbour = points[-2] if at_dest else points[1]
        span = spans[-1] if at_dest else spans[0]

        # Skip the mark when the end segment is too short to hold it.
        if span < FLANGE_STANDOFF + FLANGE_GAP / 2:
            continue

        ux, uy = (neighbour[0] - tip[0]) / span, (neighbour[1] - tip[1]) / span
        cx, cy = tip[0] + ux * FLANGE_STANDOFF, tip[1] + uy * FLANGE_STANDOFF
        along = total - FLANGE_STANDOFF if at_dest else FLANGE_STANDOFF
        out.append(Flange(cx, cy, math.degrees(math.atan2(uy, ux)), along))
    return out


def flange_boxes(fs, joints) -> "list[tuple[float, float, float, float]]":
    """Return every flange mark on a sheet as a box labels must avoid.

    A flange mark is a symbol, so label placement treats it as one
    (:func:`_erases`): a halo over it would hide the joint. Every label
    pass, including the exporter's :func:`~pandid.render.drawio._tag_pass`,
    uses this one list. Boxes are square on the longer mark dimension and
    ungrown; callers apply :func:`_obstacle`.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    joints : str or None
        :func:`sheet_connections` result; ``None`` gives no boxes.

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
    """Return path data for the filled arrowhead ending a leader at ``end``.

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
    """Return the ``<marker>`` id for an arrowhead in a colour.

    Used for both the definition and the ``url(#...)`` reference, and
    built with :func:`~pandid.render.escape.ident` so any colour spelling,
    such as ``rgb(0, 170, 119)``, gives a legal XML id. A leading ``#`` is
    dropped.

    Parameters
    ----------
    color : str
        Stroke colour.

    Returns
    -------
    str
        Marker id.
    """
    return ident("arrow", color.lstrip("#"))


def _unit_label_box(item) -> "tuple[float, float, float, float] | None":
    """Return the halo rectangle of an equipment tag.

    Width is 6.6 px per narrow character (12 pt font) plus 8 px padding;
    a wide (CJK or fullwidth) character counts a full 12 px em and a
    combining mark nothing (:func:`~pandid.render.furniture.script_counts`).

    Parameters
    ----------
    item : tuple
        ``(x, y, anchor, baseline, label_pos, text)``.

    Returns
    -------
    tuple[float, float, float, float] or None
        Halo box, or ``None`` for a ``center`` tag, drawn without a halo
        inside its symbol.
    """
    lx, ly, anchor, baseline, lpos, text = item
    if lpos == "center":
        return None
    narrow, wide, zero = F.script_counts(text)
    hw = (len(text) * 6.6 + 8 if not wide and not zero
          else narrow * 6.6 + wide * 12 + 8)
    hh = 15.0
    rx = lx - hw / 2 if anchor == "middle" else (lx - hw if anchor == "end" else lx)
    ry = ly - hh / 2 if baseline == "middle" else ly - hh + 3
    return (rx, ry, rx + hw, ry + hh)


def _num(v: float) -> str:
    """Return a coordinate without trailing zeros (``100.0`` gives ``'100'``)."""
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _xform_tag(rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Return the id suffix naming a placement transform (``''`` for identity)."""
    if not (rot or mirror_x or mirror_y):
        return ""
    return "_t" + (f"r{rot}" if rot else "") + ("x" if mirror_x else "") + ("y" if mirror_y else "")


def _placed_box(u) -> "tuple[float, float] | None":
    """Return the box a unit's artwork is drawn into, before rotation.

    A quarter turn swaps the frame's width and height, so the artwork
    never sees the swap.

    Parameters
    ----------
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float] or None
        ``(width, height)``, or ``None`` if unplaced.
    """
    f = getattr(u, "frame", None)
    if f is None:
        return None
    rot = int(getattr(f, "orientation", 0) or 0)
    return (f.h, f.w) if rot in (90, 270) else (f.w, f.h)


def _reshapes(sym, u) -> bool:
    """Return whether a unit's box has a different aspect from its symbol.

    Only an explicit ``width`` or ``height`` can reshape; a quarter turn
    swaps box and symbol together.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    bool
        True when the aspects differ.
    """
    box = _placed_box(u)
    if box is None:
        return False
    bw, bh = box
    # Cross-multiply to avoid dividing by zero; the tolerance absorbs
    # rounding in author-computed sizes.
    return not math.isclose(sym.width * bh, sym.height * bw, rel_tol=1e-9)


# --- the pen a placement draws with -----------------------------------
# scripts/vendor_symbols.py bakes stroke_width = 2/sqrt(sx*sy) into each
# symbol, which is right only at the symbol's own size. A <use> scales
# ink with its viewport, so _pen_scale divides the placement's scale back
# out, giving one <defs> entry per placed size. That works only for a
# uniform scale; an uneven one turns the round pen elliptical, which no
# single stroke-width undoes, and _baked handles it.


def _placement_scale(sym, u) -> "tuple[float, float]":
    """Return the per-axis scale a unit's ``<use>`` box applies to its artwork.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        ``(sx, sy)``; ``(1, 1)`` if unplaced or the symbol has no size.
    """
    box = _placed_box(u)
    if box is None or not (sym.width and sym.height):
        return (1.0, 1.0)
    return (box[0] / sym.width, box[1] / sym.height)


def _stretch_scale(sym, u) -> "tuple[float, float]":
    """Return the uneven per-axis scale a placement would stretch artwork by.

    ``(1, 1)`` unless a stretchable symbol is reshaped; every other case
    (own size, plain resize, or letterboxing a non-stretchable symbol) is
    a uniform scale handled by :func:`_pen_scale`.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        ``(sx, sy)``.
    """
    if sym.stretchable and _reshapes(sym, u):
        return _placement_scale(sym, u)
    return (1.0, 1.0)


# Bounded: keys are whole artwork strings and sizes. Cached because
# _fold, _pen_scale, _size_tag and _sym_id ask it repeatedly per unit.
@lru_cache(maxsize=2048)
def _uneven(svg: str, fx: float, fy: float) -> bool:
    """Return whether any stroke in ``svg`` is drawn under an uneven scale.

    The placement scale multiplies the artwork's own group transforms:
    ``scripts/vendor_symbols.py`` reproportions four stencil families
    unevenly (a plain vessel uses ``scale(0.62, 0.5)``), so those draw an
    elliptical pen even at their own size. Magnitudes are compared, so a
    mirror is not uneven.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    fx, fy : float
        Placement scale.

    Returns
    -------
    bool
        True if some stroke's x and y scales differ.
    """
    return any(not math.isclose(ax, ay, rel_tol=1e-9)
               for ax, ay in _stroke_scales(svg, fx, fy))


def _stroke_scales(svg: str, fx: float, fy: float) -> "list[tuple[float, float]]":
    """Return the effective scale magnitudes over each stroke in ``svg``.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    fx, fy : float
        Outer scale.

    Returns
    -------
    list[tuple[float, float]]
        ``(|sx|, |sy|)`` per element carrying a ``stroke-width``.
    """
    out: list[tuple[float, float]] = []
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
            out.append((abs(ax), abs(ay)))
        if not self_closing:
            scales.append((ax, ay))
    return out


def _fold(sym, u) -> "tuple[float, float]":
    """Return the scale to bake into a definition's coordinates.

    ``(1, 1)``, leaving the viewport to scale, unless the scale would be
    uneven, in which case the artwork is rewritten at the placed size
    (:func:`_baked`).

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    tuple[float, float]
        Scale to bake in.
    """
    fx, fy = _stretch_scale(sym, u)
    return (fx, fy) if _uneven(sym.svg, fx, fy) else (1.0, 1.0)


def _pen_scale(sym, u) -> float:
    """Return the factor a placement multiplies a symbol's line weights by.

    Only asked where the remaining viewport scale is uniform, since
    :func:`_fold` bakes uneven ones: no resize, a plain resize, or a
    letterbox at the smaller of the two scales.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    float
        Pen scale; 1 when the definition was baked.
    """
    if _fold(sym, u) != (1.0, 1.0):
        return 1.0
    kx, ky = _placement_scale(sym, u)
    if sym.stretchable and _reshapes(sym, u):
        # An uneven box that cancels the artwork's own uneven wrapper, so
        # the pen is round and _uneven() did not rewrite it.
        return math.sqrt(kx * ky)
    return min(kx, ky)


def _size_tag(sym, u) -> str:
    """Return the id suffix naming the box a symbol was drawn for.

    Empty for a unit at its symbol's own size, so such units share one
    definition; only a unit with an explicit size needs its own.

    Parameters
    ----------
    sym : Symbol
        Unit's symbol.
    u : Unit
        Placed unit.

    Returns
    -------
    str
        ``""`` or ``"_s<w>x<h>"``.
    """
    if (math.isclose(_pen_scale(sym, u), 1.0, rel_tol=1e-9)
            and _fold(sym, u) == (1.0, 1.0)):
        return ""
    box = _placed_box(u)
    assert box is not None  # a scale of anything but 1 came from a box
    return f"_s{_num(box[0])}x{_num(box[1])}"


# Every symbol writes stroke-width as an attribute, never through CSS, so
# a string rewrite suffices.
_STROKE_WIDTH = re.compile(r'stroke-width="([\d.]+)"')


def _at_pen_scale(svg: str, scale: float) -> str:
    """Return ``svg`` with every line weight divided by ``scale``.

    All weights, including fine detail, so their ratios are kept. Six
    significant figures, since the value is scaled again on the page.

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
    return _STROKE_WIDTH.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


# --- baking an uneven scale into the drawing --------------------------
#
# ISO 15519-1:2010 11.1.3 requires a symbol's line width (normally 0,1 M,
# after ISO 81714-1) to stay unchanged when the symbol is resized; 11.1.2
# allows changing its proportions, and 6.2 requires line widths at least
# 2:1 apart, so an elliptical pen is not a second weight.
#
# vector-effect="non-scaling-stroke" would fix the .svg but svglib ignores
# it, leaving PDF and PNG exports wrong. Instead the artwork is rewritten
# at the placed size, one definition per placed size (see _size_tag). The
# same rewrite rounds the pen of the four vendored families whose own
# wrapper is uneven (see _uneven).

def _nominal(width: float, gx: float, gy: float) -> float:
    """Return the sheet weight ``width`` represents under ``scale(gx, gy)``.

    Uses the geometric mean of the magnitudes, the inverse of what
    ``scripts/vendor_symbols.py`` bakes in, so a vendored outline reads
    back as 2.0. For a uniform scale this is just the scale.

    Parameters
    ----------
    width : float
        Stroke width in artwork units.
    gx, gy : float
        Enclosing scale.

    Returns
    -------
    float
        Nominal width on the sheet.
    """
    return width * math.sqrt(abs(gx * gy))


# How each attribute maps: a point takes scale and translation; a length
# takes the unsigned scale only. rx/ry cover ellipse radii and rect corner
# rounding; r is handled separately, since a circle scaled unevenly is not
# a circle.
_X_POINTS = {"x", "x1", "x2", "cx"}
_Y_POINTS = {"y", "y1", "y2", "cy"}
_X_LENGTHS = {"rx", "width"}
_Y_LENGTHS = {"ry", "height"}

_TAG = re.compile(r'<(/?)([A-Za-z][\w.-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*(/?)>')
_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')
# Supported absolute path commands and their argument counts. Points map
# directly (an affine image of a Bezier is the Bezier of the mapped
# control points); arcs are recomputed by _scaled_ellipse. Relative
# commands and H/V are refused, since nothing in the library emits them.
_PATH_ARITY = {"M": 2, "L": 2, "C": 6, "A": 7, "Z": 0, "z": 0}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _art(v: float) -> str:
    """Return a number in a symbol's own coordinates.

    Six decimals, more than sheet coordinates (:func:`_num`), so baking a
    weight fix does not change geometry; fixed-point, so no exponent
    notation appears.

    Parameters
    ----------
    v : float
        Value.

    Returns
    -------
    str
        Formatted number.
    """
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0", "0") else s


def _affine(transform: str) -> "tuple[float, float, float, float]":
    """Return a symbol transform as the diagonal map ``(sx, sy, tx, ty)``.

    The library writes only ``scale()`` and ``translate() scale(-1, 1)``,
    both axis-aligned, so each number maps independently.

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
            # Compose on the right, in the frame earlier ops set up.
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
    """Return the radii and tilt of a tilted ellipse after ``scale(ax, ay)``.

    The ellipse is the image of the unit circle under
    ``R(rot) diag(rx, ry)``; the singular value decomposition of
    ``diag(ax, ay) R(rot) diag(rx, ry)`` gives the new radii and tilt. Only
    the domed vessel's arcs (tilted 179,97 degrees) need this when
    stretched.

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
        New ``(rx, ry, rot)``.
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
    """Return a path ``d`` attribute with the map ``m`` applied.

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
            # A mirror reverses the sweep flag. Write flags as integers,
            # since the arc grammar takes single digits.
            sweep = int(nums[4]) if ax * ay > 0 else 1 - int(nums[4])
            out += [_art(rx), _art(ry), _art(rot), str(int(nums[3])), str(sweep),
                    _art(nums[5] * ax + ex), _art(nums[6] * ay + ey)]
        else:
            out += [_art(n * ax + ex if k % 2 == 0 else n * ay + ey)
                    for k, n in enumerate(nums)]
        i += 1 + arity
    return " ".join(out)


def _scaled_points(points: str, m: "tuple[float, float, float, float]") -> str:
    """Return a ``points`` attribute with the map ``m`` applied.

    Parameters
    ----------
    points : str
        Polyline or polygon points.
    m : tuple[float, float, float, float]
        ``(sx, sy, tx, ty)``.

    Returns
    -------
    str
        Mapped points.
    """
    ax, ay, ex, ey = m
    v = [float(t) for t in points.replace(",", " ").split()]
    return " ".join(
        f"{_art(v[i] * ax + ex)},{_art(v[i + 1] * ay + ey)}" for i in range(0, len(v), 2)
    )


def _scaled_element(name: str, attrs: "list[tuple[str, str]]",
                    m: "tuple[float, float, float, float]",
                    gx: float, gy: float, self_closing: str) -> str:
    """Return one drawn element rewritten under the map ``m``.

    Stroke widths are read back through the artwork's own scale ``gx``,
    ``gy`` (without the placement), so a 2.0 outline stays 2.0 at any
    placed size, as ISO 15519-1 11.1.3 requires.

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
        Rewritten tag; a circle becomes an ellipse.
    """
    ax, ay, ex, ey = m
    src = dict(attrs)
    # A mirror moves a rect's stated corner to the other end, so map both
    # ends and take the lower.
    corner = {}
    if name == "rect":
        for axis, span, s, e in (("x", "width", ax, ex), ("y", "height", ay, ey)):
            lo = float(src.get(axis, 0)) * s + e
            corner[axis] = min(lo, lo + float(src.get(span, 0)) * s)
    out: list[tuple[str, str]] = []
    for key, value in attrs:
        if key == "stroke-width":
            out.append(("stroke-width", _art(_nominal(float(value), gx, gy))))
        elif key == "d":
            out.append((key, _scaled_path(value, m)))
        elif key == "points":
            out.append((key, _scaled_points(value, m)))
        elif key == "font-size":
            # Scale text by the geometric mean so it keeps a valid
            # character height (ISO 15519-1 11.4.1).
            out.append((key, _art(math.sqrt(abs(ax * ay)) * float(value))))
        elif key == "r":
            out.append(("rx", _art(abs(float(value) * ax))))
            out.append(("ry", _art(abs(float(value) * ay))))
            name = "ellipse"  # a circle stretched unevenly is not a circle
        elif key in corner:
            out.append((key, _art(corner[key])))
        elif key in _X_LENGTHS:
            out.append((key, _art(abs(float(value) * ax))))
        elif key in _Y_LENGTHS:
            out.append((key, _art(abs(float(value) * ay))))
        elif key in _X_POINTS:
            out.append((key, _art(float(value) * ax + ex)))
        elif key in _Y_POINTS:
            out.append((key, _art(float(value) * ay + ey)))
        else:
            out.append((key, value))
    written = "".join(f' {k}="{v}"' for k, v in out)
    return f"<{name}{written}{'/' if self_closing else ''}>"


def _baked(svg: str, fx: float, fy: float) -> str:
    """Return ``svg`` redrawn at ``scale(fx, fy)`` with scale groups flattened.

    Geometry is unchanged, but no scale remains above any stroke, so each
    ``stroke-width`` is the width drawn in both directions. Returns
    ``svg`` unchanged when the scale is even, which keeps most ``<defs>``
    identical to the vendored stencil.

    Parameters
    ----------
    svg : str
        Symbol artwork.
    fx, fy : float
        Placement scale.

    Returns
    -------
    str
        Flattened artwork.
    """
    if not _uneven(svg, fx, fy):
        return svg
    out: list[str] = []
    pos = 0
    maps = [(fx, fy, 0.0, 0.0)]  # accumulated map, innermost last
    elided: list[bool] = []      # whether an open tag's closer went with it
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
    """Return ``svg`` with its text wrapped to stay upright under a placement.

    Flipping a unit moves its lettering but must not turn it over, so
    each text element is wrapped in the inverse transform about its own
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
        """Return one text element wrapped in the inverse transform."""
        tx, ty = float(match.group(1)), float(match.group(2))
        # Pivot on the glyph centre, about 0.35 em above the baseline
        # (cap height is about 0.7 em). x is already centred
        # (text-anchor="middle").
        size = re.search(r'font-size="(-?[\d.]+)"', match.group(0))
        cy = ty - 0.35 * float(size.group(1) if size else 12.0)
        # Undo in the reverse of the order the <use> applies them.
        ops = []
        if mirror_x:
            ops.append(f"translate({_num(2 * tx)}, 0) scale(-1, 1)")
        if mirror_y:
            ops.append(f"translate(0, {_num(2 * cy)}) scale(1, -1)")
        if rot:
            ops.append(f"rotate({-rot}, {_num(tx)}, {_num(cy)})")
        return f'<g transform="{" ".join(ops)}">{match.group(0)}</g>'

    return _SYMBOL_TEXT.sub(wrap, svg)


def _reflections(rot: int, mirror_x: bool, mirror_y: bool) -> "tuple[bool, bool]":
    """Return a placement's reflection content as a pair of axis flips.

    The identity, the two mirrors and the half turn (both mirrors
    composed) leave the axes in place and can be undone inside a symbol
    definition, since an axis flip commutes with per-axis scaling. Quarter
    turns swap the axes and are not undone. So ``orientation=180``
    reverses a directional mark as either mirror would.

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
    """Return directional artwork with a placement flip undone inside it.

    A cooler differs from a heater only by where its arrowhead sits, so a
    flipped cooler would read as a heater. The flip is undone about the
    symbol's centre lines and reapplied by the ``<use>``, so the artwork
    stays as drawn while the ports move with the flip. ``mirror_x`` and
    ``mirror_y`` are the net flips from :func:`_reflections`; quarter turns
    are left alone. See :attr:`pandid.render.symbols.Symbol.directional`.

    Parameters
    ----------
    svg : str
        Symbol artwork, wrapped in an outer ``<g>``.
    w, h : float
        Symbol size.
    mirror_x, mirror_y : bool
        Net flips.

    Returns
    -------
    str
        Artwork with an inner counter-flip group.
    """
    if not (mirror_x or mirror_y) or not svg.startswith("<g"):
        return svg
    ops = []
    if mirror_x:
        ops.append(f"translate({_num(w)}, 0) scale(-1, 1)")
    if mirror_y:
        ops.append(f"translate(0, {_num(h)}) scale(1, -1)")
    head, inner = svg[:svg.find(">") + 1], svg[svg.find(">") + 1:svg.rfind("</g>")]
    return f'{head}<g transform="{" ".join(ops)}">{inner}</g></g>'


# ISO 216 page sizes in millimetres, landscape. Listed, not derived by
# doubling, because ISO rounds each size.
_PAGE_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}

# The user unit the drawing is laid out in is the CSS pixel, 1/96 inch.
_PX_PER_MM = 96.0 / 25.4


class _Sheet(NamedTuple):
    """A fixed sheet the drawing is placed on, rather than sized to.

    Attributes
    ----------
    name : str
        Page size name, such as ``"A3"``.
    width_mm, height_mm : float
        Physical size the SVG declares, so it prints at its ISO size.
    """
    name: str
    width_mm: float
    height_mm: float

    @property
    def width(self) -> float:
        """Return the sheet width in layout units (CSS px)."""
        return self.width_mm * _PX_PER_MM

    @property
    def height(self) -> float:
        """Return the sheet height in layout units (CSS px)."""
        return self.height_mm * _PX_PER_MM


def _page(page_size: "str | None") -> "_Sheet | None":
    """Return the fixed sheet for a page size.

    Parameters
    ----------
    page_size : str or None
        ISO A-size name, case-insensitive; ``None`` fits the sheet to the
        drawing.

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


# Border frames; any diagram may carry the zone frame.
_BORDERS = ("none", "zone")
# Diagram kinds, one per ISO 10628-1 clause 4 subclause: BFD 4.2, PFD 4.3,
# P&ID 4.4. Read by draws_arrowheads and tabulates_boundary_flows.
_DIAGRAMS = ("pfd", "p&id", "bfd")
# Accepted spellings of each diagram kind.
_ALIASES = {"pid": "p&id", "p&id": "p&id", "pfd": "pfd", "bfd": "bfd"}


def _canon(value: str) -> str:
    """Return a diagram name in canonical spelling.

    Case is folded and ``"pid"`` is read as ``"p&id"``; nothing else is
    guessed.

    Parameters
    ----------
    value : str
        Diagram name.

    Returns
    -------
    str
        Canonical name, or ``value`` unchanged if unknown.
    """
    return _ALIASES.get(value.strip().lower(), value)


def _resolve_sheet(border: "str | None", diagram: "str | None") -> "tuple[str, str]":
    """Return the validated border and diagram kind.

    Parameters
    ----------
    border : str or None
        ``"none"`` or ``"zone"``; ``None`` means ``"none"``.
    diagram : str or None
        ``"pfd"``, ``"p&id"`` (or ``"pid"``) or ``"bfd"``; ``None`` means
        ``"pfd"``.

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
    kind = _canon(diagram)
    if kind not in _DIAGRAMS:
        raise ValueError(
            f"Unknown diagram {diagram!r}; use 'pfd', "
            f"'p&id' (also spelled 'pid') or 'bfd'."
        )
    return border, kind


#: ``show_stream_table`` value that draws the stream table as its own sheet.
TABLE_SHEET = "sheet"


def wants_table_sheet(show_stream_table) -> bool:
    """Return whether a render asks for the stream table on its own sheet.

    ``show_stream_table`` is ``False`` (no table), ``True`` (table docked
    at the foot of the diagram) or ``"sheet"`` (the table alone as a full
    drawing with border and title strip). One call still writes one file.

    Parameters
    ----------
    show_stream_table : bool, str or None
        Render argument.

    Returns
    -------
    bool
        True for ``"sheet"``.

    Raises
    ------
    ValueError
        If the value is any other string or object.
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

    ANSI/ISA-5.1 draws P&ID piping as plain lines. A BFD heads its lines,
    since ISO 10628-1:2014 4.2.2 c) requires it to show flow direction.
    Used by the renderer and by :func:`pandid.validate.validate`, which
    skips arrowhead checks on a sheet without heads.

    Parameters
    ----------
    diagram : str or None
        Diagram name as :meth:`pandid.flowsheet.Flowsheet.to_svg` takes it.

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
    """Return whether a diagram kind must state boundary flow rates.

    True only for a PFD (ISO 10628-1:2014 4.3.2 d)). A P&ID answers 4.4.2,
    and a BFD lists flow rates as optional (4.2.3), so
    ``stream-table-missing`` is silent on both. Separate from
    :func:`draws_arrowheads` because a BFD draws arrowheads but owes no
    rates.

    Parameters
    ----------
    diagram : str or None
        Diagram name as :meth:`pandid.flowsheet.Flowsheet.to_svg` takes it.

    Returns
    -------
    bool
        True only for a PFD.

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

    Checked up front because the drawing code tests for each value, so a
    misspelling would silently draw no hops, and a sheet with no
    crossings would never reveal it.

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

    Checked up front, as :func:`check_jump_direction` is, so a
    misspelling raises even on a sheet with no crossings instead of
    silently drawing another style. The default is
    :data:`CROSSING_STYLE_DEFAULT` (``"gap"``).

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

    ``None`` means the sheet never marks joints and no stream can
    override it; ``"none"`` is a P&ID that marks none by default but lets
    a stream say otherwise. Only a P&ID marks joints: ISO 15519-2:2015
    Table 5 gives it specific connection symbols, while Table 4 limits a
    PFD to general ones, so ``connections="flanged"`` on a PFD draws
    nothing. Shared with the draw.io exporter.

    Parameters
    ----------
    diagram : str or None
        Diagram name.
    connections : str or None
        Requested setting from :data:`CONNECTIONS`.

    Returns
    -------
    str or None
        Default setting, or ``None`` when the diagram is not a P&ID.

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

    An unset ``Stream.ends`` inherits the sheet default; a set one wins,
    including ``"none"``, so a sheet can have exceptions either way. A pair
    gives the two ends in connection order: ``connect(a, b)`` with
    ``ends=("flanged", "none")`` flanges the joint at ``a`` only.

    Parameters
    ----------
    s : Stream
        Stream.
    default : str or None
        :func:`sheet_connections` result.

    Returns
    -------
    tuple[str, str]
        Settings for the source and destination ends; ``("none", "none")``
        when the sheet marks no joints.
    """
    if default is None:
        return ("none", "none")
    ends = getattr(s, "ends", None) or default
    return (ends, ends) if isinstance(ends, str) else (ends[0], ends[1])


def _fit_scale(dw: float, dh: float, free) -> float:
    """Return the uniform scale that fits a drawing into a free area.

    Never enlarges, since furniture is drawn at a fixed size and an
    enlarged drawing would outweigh it.

    Parameters
    ----------
    dw, dh : float
        Drawing size.
    free : tuple[float, float, float, float]
        Free area ``(x, y, w, h)``.

    Returns
    -------
    float
        Scale, at most 1.
    """
    _, _, fw, fh = free
    return min(1.0, fw / dw if dw > 0 else 1.0, fh / dh if dh > 0 else 1.0)


def _scale_text(s: float) -> str:
    """Return a fit scale as a title-block ratio, such as ``"1:2.5"``."""
    return "1:1" if s >= 1.0 else f"1:{1 / s:.3g}"


# Renderer findings about text that did not fit its cell.
_FIT_CODES = ("text-truncated", "text-overruns-cell")

#: Finding code for a stream-table sheet with no drawing number to tell
#: it from its diagram; see :func:`table_sheet_plan`.
TABLE_SHEET_UNNUMBERED = "table-sheet-unnumbered"

# Codes the renderer itself puts on fs.warnings. Each render replaces
# them, so fixed problems stop being reported. The draw.io exporter adds
# its own (pandid.render.drawio._EXPORT_CODES).
_RENDER_CODES = _FIT_CODES + ("crossing-unmarked", TABLE_SHEET_UNNUMBERED)



def fit_issue(field: str, text: str, drawn: str,
              room: float, need: float) -> Issue:
    """Return a text-fit finding for one title-strip or furniture cell.

    Shared by both renderers and :func:`pandid.validate.model_issues`, so
    the message does not depend on which one measured. It states the room,
    the width needed and their ratio.

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
        ``text-truncated`` if the value was shortened, else
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

    Furniture is drawn at a fixed size, so no drawing scale can fix it.

    Parameters
    ----------
    sheet : _Sheet
        Fixed sheet.
    need_w, need_h : float
        Space the furniture needs, in px.
    cause : str, default=""
        Name of the widest piece, often the stream table.

    Returns
    -------
    ValueError
        Error to raise.
    """
    blame = f" The widest piece is {cause}." if cause else ""
    return ValueError(
        f"The sheet furniture does not fit page size {sheet.name}: the border, title strip "
        f"and docked boxes need at least {need_w:.0f}x{need_h:.0f}px of the "
        f"{sheet.width:.0f}x{sheet.height:.0f}px sheet.{blame} Use a larger page_size, or omit "
        "page_size to fit the sheet to the drawing."
    )


# Sentinel for the title strip among docked furniture, so a fit error can
# name it.
TITLE = "\x00title"
_FURNITURE_NAMES = {TITLE: "the title strip"}


def _furniture_name(obj) -> str:
    """Return a readable name for a piece of furniture in an error message.

    Parameters
    ----------
    obj : object
        Title sentinel, stream table or annotation box.

    Returns
    -------
    str
        Name such as ``"the stream table"``.
    """
    if isinstance(obj, str):
        return _FURNITURE_NAMES.get(obj, obj)
    if isinstance(obj, F.StreamTable):
        return "the stream table"
    title = getattr(obj, "title", "")
    return f"the {title!r} box" if title else "an untitled annotation box"


#: Comments fencing the provenance block. tests/test_golden.py drops the
#: lines between them, so anything version-dependent must go inside.
#: ``<title>`` stays outside because it is real content.
PROVENANCE_OPEN = "  <!-- pandid:provenance -->"
PROVENANCE_CLOSE = "  <!-- /pandid:provenance -->"

_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _sheet_title(fs: "Flowsheet") -> str:
    """Return the drawing's accessible title.

    The title block's title if stated, else the flowsheet name, both
    stripped. Uses :func:`~pandid.render.furniture._field` so "stated"
    means the same as on the title strip. An empty result means the caller
    omits ``<title>``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.

    Returns
    -------
    str
        Title, possibly empty.
    """
    tb = fs.title_block
    title = F._field(tb, "title") if tb is not None else ""
    return title or str(fs.name or "").strip()


def _table_sheet_title(fs: "Flowsheet", options) -> str:
    """Return the stream-table sheet's title: drawing title and subtitle.

    Gives it an accessible name distinct from its diagram's.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    options : StreamTableOptions
        Table options carrying ``sheet_subtitle``.

    Returns
    -------
    str
        Title parts joined with ``" - "``.
    """
    from pandid.document import _drawn_text

    # The subtitle is drawn text, so a number such as 100 reads "100".
    parts = [p for p in (_sheet_title(fs), _drawn_text(options.sheet_subtitle)) if p]
    return " - ".join(parts)


def _provenance(fs: "Flowsheet", title: "str | None" = None) -> list[str]:
    """Return the ``<title>`` and provenance lines of an SVG document.

    Provenance goes in a comment and a ``<metadata>`` block, never as
    hidden text that would be copied out of the drawing. ``<title>`` is
    the first child, for tooltips and screen readers; ``dc:title`` repeats
    it and ``dc:creator`` names the generator.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    title : str, optional
        Title to use instead of :func:`_sheet_title`, for the stream-table
        sheet.

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
    # Use a colon: an XML comment may not contain "--" (XML 1.0 2.5).
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

    Writes the XML declaration, the ``<svg>`` element, provenance, a white
    background and then ``body``. Shared by the diagram and the
    stream-table sheet so both declare their size the same way. A named
    page declares its physical size in millimetres, so it prints at its ISO
    size; a fitted sheet stays in user units.

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
    # Title and provenance must be the first children of <svg>.
    lines.extend(_provenance(fs, title))
    lines.append('  <!-- Background -->')
    lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="white" />')
    lines.extend(body)
    lines.append('</svg>')
    return "\n".join(lines)


class TableSheetPlan(NamedTuple):
    """Stream-table sheet geometry, shared by both backends.

    Findings are carried rather than emitted because the plan is computed
    twice: once to refuse an impossible render, once to draw.

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


def table_sheet_plan(fs, sheet: "_Sheet | None") -> TableSheetPlan:
    """Lay out the stream table's own sheet.

    Wraps the table to the page, docks the title strip and frames both.
    Both backends use it, as they use :func:`dock`, so the export and the
    print agree. The table is the sheet's body rather than docked
    furniture, so it gets the full width. The strip is always drawn, from
    :func:`~pandid.document.table_sheet_block`, since a sheet in a set
    needs a number. The flowsheet's annotation boxes belong to the
    diagram and are not repeated.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    sheet : _Sheet or None
        Fixed page, or ``None`` to fit.

    Returns
    -------
    TableSheetPlan
        Layout and findings.

    Raises
    ------
    ValueError
        If nothing is tabulated, or the page is too small for the table or
        strip.
    """
    from pandid.document import TABLE_SHEET_SUFFIX, table_sheet_block

    # Wrap to the frame width less the dock clearance; with no page the
    # table is one block.
    room = None if sheet is None else (
        sheet.width - 2 * (F.OUTER_MARGIN + F.ZONE_BAND) - 2 * F.INNER)
    table = F.stream_table_sheet(fs, room)
    if table is None:
        # No table to draw; see furniture.stream_table_layout.
        raise ValueError(
            "show_stream_table='sheet' draws a sheet whose body is the stream "
            "table, and this flowsheet has nothing to tabulate: no stream "
            "states a property and none crosses the sheet edge. Put properties "
            "on the streams (stream.properties = {...}), or drop the table sheet")
    block = table_sheet_block(fs.title_block, F._options(fs))
    ts_w, ts_h = F.measure_title_strip(block)
    items = [(TITLE, "bottom-right", ts_w, ts_h)]
    inner = (0.0, 0.0, table.w, table.h)
    if sheet is None:
        placed, frame, free = F.dock(items, inner)
    else:
        page = sheet  # rebound so the closure closes over a _Sheet
        placed, frame, free = F.dock(
            items, inner, sheet=page,
            too_small=lambda need_w, need_h, culprit: _too_small(
                page, need_w, need_h,
                _furniture_name(culprit) if culprit else ""))
        assert free is not None  # a fixed page always leaves a region
        _fx, _fy, fw, fh = free
        if table.w > fw or table.h > fh:
            # Too many rows, or one column still too wide, for this page.
            raise _too_small(page, page.width - fw + table.w,
                             page.height - fh + table.h, "the stream table")
    _obj, sx, sy, sw, sh = placed[0]
    left, top = F.table_sheet_origin(table, free)
    date = block.date or datetime.now().strftime("%Y-%m-%d")
    findings = []
    if not block.drawing_number:
        # Draw unnumbered and warn: a title block is optional elsewhere,
        # and a drawing number must be issued, not invented.
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


def reject_unknown_options(where: str, opts: dict) -> None:
    """Raise if a backend was given keywords it does not take.

    Backends accept ``**opts`` to satisfy the
    :class:`~pandid.render.Renderer` protocol, but silently dropping an
    argument (such as ``debug=True`` on a draw.io render) would mislead
    the caller. All unknown names are reported at once.

    Parameters
    ----------
    where : str
        Backend name, for the message.
    opts : dict
        Unrecognised keyword arguments.

    Raises
    ------
    ValueError
        If ``opts`` is not empty.
    """
    if opts:
        raise ValueError(
            f"{where} was given {', '.join(sorted(opts))}, which it does not "
            f"take. A render argument this backend does not know is an "
            f"argument it would have dropped, and a file that quietly lacks "
            f"what was asked for is worse than a refused one."
        )


def check_render_arguments(fs, *, show_stream_table: "bool | str" = False,
                           border: "str | None" = None,
                           diagram: "str | None" = None,
                           page_size: "str | None" = None,
                           connections: "str | None" = None,
                           jump_direction: str = "vertical",
                           crossing_style: str = "gap",
                           debug: "bool | float" = False) -> None:
    """Check render arguments before the sheet is laid out or routed.

    Layout and routing write frames and routes onto the flowsheet, so a
    render that failed afterwards would leave geometry for the failed
    call (see :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw`). These
    checks need no geometry. ``jump_direction``, ``crossing_style`` and
    ``connections`` are checked even when the sheet cannot show them, so
    a typo is caught on any sheet. Renderers repeat the checks where they
    use the values.

    Parameters
    ----------
    fs : Flowsheet
        Sheet.
    show_stream_table : bool or str, default=False
        ``True``, ``False`` or ``"sheet"``.
    border : str, optional
        ``"none"`` or ``"zone"``.
    diagram : str, optional
        ``"pfd"``, ``"p&id"`` or ``"bfd"``.
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
        # The coordinate overlay needs a diagram; refuse rather than ignore.
        raise ValueError(
            "debug draws the coordinate overlay under a *diagram*, and "
            "show_stream_table='sheet' draws no diagram. Render the diagram "
            "to see the overlay, or drop debug=")
    # Lay the table sheet out to check it, then discard the result.
    # Measuring may add findings to fs.warnings, which must not outlive a
    # render that then raises, so restore the same list object (callers
    # may hold a reference), even on error.
    was = fs.warnings
    contents = list(was)
    try:
        table_sheet_plan(fs, page)
    finally:
        was[:] = contents
        fs.warnings = was


class SvgRenderer:
    """Render a laid-out Flowsheet to SVG.

    Parameters
    ----------
    registry : SymbolRegistry, optional
        Symbols to draw with; ``default_registry`` when omitted.
    """

    def __init__(self, registry=None):
        """Store the symbol registry."""
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical",
               crossing_style: str = "gap",
               show_stream_table: "bool | str" = False,
               border: "str | None" = None, diagram: "str | None" = None,
               page_size: "str | None" = None, connections: "str | None" = None,
               debug: "bool | float" = False,
               **opts) -> str:
        """Render the flowsheet to SVG.

        Render warnings (title-block fit, unmarked crossings, label
        placement) replace those of any earlier render on ``fs.warnings``.

        Parameters
        ----------
        fs : Flowsheet
            Laid-out and routed flowsheet.
        jump_direction : str, default="vertical"
            Which of two crossing lines carries the crossing mark:
            ``"vertical"`` or ``"horizontal"``.
        crossing_style : str, default="gap"
            The mark: ``"gap"``, ``"arc"`` or ``"plain"``; see
            :data:`CROSSING_STYLES`.
        show_stream_table : bool or str, default=False
            ``True`` docks the stream table at the foot of the diagram;
            ``"sheet"`` draws the table as its own sheet with no diagram
            (:func:`wants_table_sheet`).
        border : str, optional
            ``"none"`` for a plain edge or ``"zone"`` for the zone-ruled
            frame (rows lettered A.. top down, columns numbered 1.. left to
            right). Defaults to ``"none"``, or ``"zone"`` for a table sheet.
        diagram : str, optional
            ``"pfd"`` (default), ``"p&id"`` (or ``"pid"``) or ``"bfd"``. A
            P&ID draws process lines without arrowheads.
        page_size : str, optional
            ``"A4"`` to ``"A0"``: draw at that size with furniture docked to
            the edges and the drawing fitted between. ``None`` sizes the
            sheet to the drawing.
        connections : str, optional
            Joint marked on P&ID streams that state none: ``"flanged"`` or
            ``"none"``. Ignored outside a P&ID (:func:`sheet_connections`).
        debug : bool or float, default=False
            Draw the coordinate overlay (:mod:`pandid.render.debug`):
            ``True`` for the default grid spacing, or a spacing.
        **opts
            Refused; any unknown keyword raises.

        Returns
        -------
        str
            SVG document.

        Raises
        ------
        ValueError
            If an argument is invalid, the page is too small, or a unit has
            no frame.
        """
        from pandid.portgeom import unit_box
        from pandid.render import debug as _debug
        # Check options before building anything.
        reject_unknown_options("SvgRenderer.render()", opts)
        grid = _debug.resolve_spacing(debug)
        table_sheet = wants_table_sheet(show_stream_table)
        # Flowsheet checks these before layout; check again for callers
        # using the renderer directly.
        check_render_arguments(
            fs, show_stream_table=show_stream_table, border=border,
            diagram=diagram, page_size=page_size, connections=connections,
            jump_direction=jump_direction, crossing_style=crossing_style,
            debug=debug)
        # A table sheet is a formal drawing, so it gets the zone frame
        # unless border is stated.
        if table_sheet and border is None:
            border = "zone"
        border, diagram = _resolve_sheet(border, diagram)
        arrows = draws_arrowheads(diagram)
        joints = sheet_connections(diagram, connections)
        sheet = _page(page_size)
        if table_sheet:
            return self._table_sheet(fs, sheet, border)

        # 1. Diagram bounding box: union of every unit's drawn box and
        #    every route waypoint. Furniture goes *around* this region.
        dx0 = dy0 = float("inf")
        dx1 = dy1 = float("-inf")
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            dx0, dy0 = min(dx0, bx0), min(dy0, by0)
            dx1, dy1 = max(dx1, bx1), max(dy1, by1)
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    dx0, dy0 = min(dx0, px), min(dy0, py)
                    dx1, dy1 = max(dx1, px), max(dy1, py)
        if not fs.units:  # empty flowsheet: fall back to the nominal page size
            nominal = sheet or _page("A3")
            assert nominal is not None
            dx0 = dy0 = 0.0
            dx1, dy1 = nominal.width, nominal.height

        # 2. The stream table, measured. Shared with the draw.io
        #    exporter, which docks and rules the same one.
        st_layout = F.stream_table_layout(fs) if show_stream_table else None

        # 3. Place furniture around the diagram and size the sheet.
        margin = 55.0
        furniture: list[str] = []
        free = None  # region a fixed sheet leaves for the drawing
        fit_issues: list[Issue] = []
        # Findings from the label passes, which run after sizing.
        self._findings: list[Issue] = []

        def report(field: str, text: str, drawn: str,
                   room: float, need: float) -> None:
            """Record a title-block or annotation cell that overflowed."""
            fit_issues.append(fit_issue(field, text, drawn, room, need))

        # Furniture comes from what was supplied: a title block,
        # annotations or a stream table, plus a title strip on any zone
        # border. Docking everything through furniture.dock keeps this in
        # step with the draw.io exporter.
        furnished = (border == "zone" or fs.title_block is not None
                     or bool(getattr(fs, "annotations", None))
                     or st_layout is not None)
        if furnished:
            (frame_x, frame_y, canvas_width, canvas_height), free = self._place_furniture(
                fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet, border, report)
        elif sheet is not None:
            free = self._place_plain(st_layout, sheet, margin, furniture)
            frame_x, frame_y = 0.0, 0.0
            canvas_width, canvas_height = sheet.width, sheet.height
        else:
            # Bare sheet: the frame is the drawing's bounds plus margin.
            frame_x, frame_y = dx0 - margin, dy0 - margin
            canvas_width = (dx1 - dx0) + 2 * margin
            canvas_height = (dy1 - dy0) + 2 * margin

        # Replace render findings from earlier renders. Unmarked crossings
        # depend on jump_direction, a render option, so only the render can
        # report them (:func:`unmarked_crossings`).
        render_issues = fit_issues + _crossing_issues(fs, jump_direction,
                                                      crossing_style)
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _RENDER_CODES
                       and getattr(w, "code", "") not in _LABEL_CODES] + render_issues

        # 4. SVG document. Furniture (border + title strip + boxes) sits
        #    behind the diagram.
        lines = ["    " + item for item in furniture]
        lines.extend(self._defs(fs, arrows))
        unit_labels: list = []
        balloons: list = []
        # Every drawn line, for the label passes, which write on opaque
        # halos (:func:`_ink`).
        ink = _ink(fs, jump_direction)
        # Balloon quadrant codes, placed before anything that must dodge
        # them and drawn with the tags (:func:`quadrant_labels`).
        quadrants = quadrant_labels(fs, jump_direction)
        drawing: list[str] = []
        # Opaque plates, collected only for the debug overlay, which is
        # drawn underneath and must avoid them.
        plates: "list[tuple[float, float, float, float]] | None" = (
            [] if grid is not None else None)
        drawing.extend(self._draw_units(fs, unit_labels, balloons, ink, joints,
                                        quadrants))
        drawing.extend(self._draw_streams(fs, jump_direction, unit_labels, arrows,
                                          plates, joints, crossing_style))
        # Instruments go over the lines, so a balloon's opaque body masks
        # its impulse line and any process line it straddles.
        drawing.extend(self._draw_taps(fs))
        if balloons:
            drawing.append('  <g id="instruments">')
            drawing.extend(balloons)
            drawing.append('  </g>')
        # Tags and quadrant codes go last, on halos, over every line.
        drawing.extend(self._draw_unit_labels(unit_labels + quadrants))
        # Add the label-pass findings now that they are known.
        fs.warnings = fs.warnings + self._findings

        # The debug overlay is computed last but drawn first, under the
        # sheet's ink, inside the fitted group so its numbers are pin()
        # coordinates; its lettering is held to a constant paper size.
        if grid is not None:
            assert plates is not None
            drawing[:0] = _debug.overlay(
                fs, (dx0, dy0, dx1, dy1), grid,
                _fit_scale(dx1 - dx0, dy1 - dy0, free) if free is not None else 1.0,
                plates=plates, ink=[line.box for line in ink])

        if free is None:
            lines.extend(drawing)
        else:  # a fixed sheet: the drawing is fitted into what the furniture leaves
            lines.append(f'  <g id="drawing" transform="{self._fit(dx0, dy0, dx1, dy1, free)}">')
            lines.extend(drawing)
            lines.append('  </g>')
        return _document(fs, sheet,
                         (frame_x, frame_y, canvas_width, canvas_height), lines)

    def _fit(self, dx0, dy0, dx1, dy1, free) -> str:
        """Return the SVG transform that centres and scales the drawing in ``free``.

        Parameters
        ----------
        dx0, dy0, dx1, dy1 : float
            Drawing bounds.
        free : tuple[float, float, float, float]
            Region ``(x, y, w, h)`` left for the drawing.

        Returns
        -------
        str
            ``translate(...) scale(...)``.
        """
        fx, fy, fw, fh = free
        dw, dh = dx1 - dx0, dy1 - dy0
        s = _fit_scale(dw, dh, free)
        return (f"translate({_num(fx + (fw - s * dw) / 2 - s * dx0)}, "
                f"{_num(fy + (fh - s * dh) / 2 - s * dy0)}) scale({s:.6g})")

    # --- furniture ----------------------------------------------------

    def _place_furniture(self, fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet,
                         border, report=None):
        """Dock furniture to the sheet frame and draw it.

        Boxes are grouped into edge bands by ``align`` and placed flush to
        the frame edge, inset by their ``margin``; a box with ``position``
        is placed by hand. Without a fixed sheet the frame grows from the
        drawing bounds to hold the bands; with one, the frame is the page
        and the drawing fits the region left. The band arithmetic is
        :func:`pandid.render.furniture.dock`, shared with draw.io.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose title block and annotations are drawn.
        st_layout : StreamTable or None
            Measured stream table.
        dx0, dy0, dx1, dy1 : float
            Drawing bounds.
        furniture : list[str]
            SVG lines, appended to in place.
        sheet : _Sheet or None
            Fixed page, or ``None``.
        border : str
            ``"none"`` or ``"zone"``.
        report : callable, optional
            Receives title and annotation fit findings.

        Returns
        -------
        tuple
            Canvas ``(x, y, w, h)`` and the free region, or ``None`` when
            the frame grew to the drawing.
        """
        from pandid.document import TitleBlock, TableBox

        OUT = F.OUTER_MARGIN

        def measure(a):
            """Return a box's ``(w, h)``."""
            return F.measure_table(a) if isinstance(a, TableBox) else F.measure_annotation(a)

        def draw_box(a, x, y):
            """Draw a table or annotation box at ``(x, y)``."""
            furniture.extend(F.draw_table(a, x, y) if isinstance(a, TableBox)
                             else F.draw_annotation(a, x, y, report=report))

        # The title strip (as the TITLE sentinel) and the stream table dock
        # at the bottom-right and bottom-left.
        strip = fs.title_block is not None or border == "zone"
        tb = fs.title_block or TitleBlock()
        ts_w, ts_h = F.measure_title_strip(tb)
        date = datetime.now().strftime("%Y-%m-%d")
        name = fs.name

        items = [(a, a.align, *measure(a))
                 for a in getattr(fs, "annotations", []) or []]
        if strip:
            items.append((TITLE, "bottom-right", ts_w, ts_h))
        if st_layout:
            items.append((st_layout, "bottom-left", st_layout.w, st_layout.h))

        placed, (ix, iy, iw, ih), free = F.dock(
            items, (dx0, dy0, dx1, dy1), sheet=sheet,
            too_small=lambda need_w, need_h, culprit: _too_small(
                sheet, need_w, need_h, _furniture_name(culprit) if culprit else ""))
        # The scale cell states the fit scale; a grown frame has none.
        fit = "" if free is None else _scale_text(
            _fit_scale(dx1 - dx0, dy1 - dy0, free))

        for obj, x, y, w, h in placed:
            if obj is TITLE:
                furniture.extend(
                    F.draw_title_strip(tb, name, date, x + w, y + h, fit_scale=fit,
                                       report=report))
            elif isinstance(obj, F.StreamTable):
                furniture.extend(F.draw_stream_table(obj, x, y))
            else:
                draw_box(obj, x, y)

        # --- border around the frame, then the sheet edge -------------
        if border == "zone":
            frame_lines, outer = F.zone_frame(ix, iy, iw, ih)
            furniture[:0] = frame_lines  # border sits behind the boxes
        else:
            outer = F.sheet_rect(ix, iy, iw, ih)
        ox, oy, ow, oh = outer
        return (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT), free

    def _table_sheet(self, fs, sheet, border) -> str:
        """Return the stream table drawn as a sheet of its own.

        Geometry comes from :func:`table_sheet_plan`, shared with draw.io.
        The scale cell is ruled but empty, since a table has no scale, and
        is kept so the drawing-number budget matches the diagram sheets
        (:func:`~pandid.render.furniture.title_strip_layout`).

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose streams are tabulated.
        sheet : _Sheet or None
            Fixed page, or ``None`` to size to the table.
        border : str
            ``"none"`` or ``"zone"``.

        Returns
        -------
        str
            SVG document.
        """
        fit_issues: list[Issue] = []

        def report(field: str, text: str, drawn: str,
                   room: float, need: float) -> None:
            """Record a title-block or annotation cell that overflowed."""
            fit_issues.append(fit_issue(field, text, drawn, room, need))

        plan = table_sheet_plan(fs, sheet)
        furniture: list[str] = []
        for i, part, bx, by in plan.table.at(plan.left, plan.top):
            furniture.extend(F.draw_stream_table(
                part, bx, by, group=f"stream_table_{i + 1}"))
        sx, sy, sw, sh = plan.strip
        furniture.extend(F.draw_title_strip(plan.block, plan.name, plan.date,
                                            sx + sw, sy + sh, report=report))
        if border == "zone":
            frame_lines, outer = F.zone_frame(*plan.frame)
            furniture[:0] = frame_lines  # the border sits behind the rest
        else:
            outer = F.sheet_rect(*plan.frame)
        ox, oy, ow, oh = outer
        OUT = F.OUTER_MARGIN
        fs.warnings = ([w for w in fs.warnings
                        if getattr(w, "code", "") not in _RENDER_CODES]
                       + plan.findings + fit_issues)
        return _document(
            fs, sheet, (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT),
            ["    " + item for item in furniture],
            title=_table_sheet_title(fs, F._options(fs)))

    def _place_plain(self, st_layout, sheet, margin, furniture):
        """Lay out a fixed page with no furniture except a stream table.

        Parameters
        ----------
        st_layout : StreamTable or None
            Measured stream table, docked at the foot.
        sheet : _Sheet
            Fixed page.
        margin : float
            Page margin.
        furniture : list[str]
            SVG lines, appended to in place.

        Returns
        -------
        tuple[float, float, float, float]
            Region ``(x, y, w, h)`` left for the drawing.

        Raises
        ------
        ValueError
            If the page is too small.
        """
        free_w = sheet.width - 2 * margin
        free_h = sheet.height - 2 * margin
        table_h = (st_layout.h + 24) if st_layout else 0.0
        if free_w <= 0 or free_h - table_h <= 0 or (st_layout and st_layout.w > free_w):
            raise _too_small(sheet,
                             2 * margin + (st_layout.w if st_layout else 0.0),
                             2 * margin + table_h,
                             "the stream table" if st_layout else "")
        if st_layout:
            furniture.extend(F.draw_stream_table(
                st_layout, margin, sheet.height - margin - st_layout.h))
        return (margin, margin, free_w, free_h - table_h)

    # --- defs ---------------------------------------------------------

    def _baked_xform(self, u) -> tuple[int, bool, bool]:
        """Return the placement transform baked into a symbol definition.

        Lettering must stay readable (:func:`_upright_text`) and a
        directional mark must survive a flip (:func:`_upright_artwork`), so
        these are undone inside the definition and reapplied by ``<use>``.
        Other symbols get the identity and share one definition. A
        directional symbol bakes only the reflection content
        (:func:`_reflections`).

        Parameters
        ----------
        u : Unit
            Placed unit.

        Returns
        -------
        tuple[int, bool, bool]
            ``(rotation, mirror_x, mirror_y)``.
        """
        sym = self.registry.for_unit(u)
        f = getattr(u, "frame", None)
        if f is None:
            return (0, False, False)
        rot = int(getattr(f, "orientation", 0) or 0)
        mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        if "<text" in sym.svg:
            return (rot, mirror_x, mirror_y)
        if sym.directional:
            return (0, *_reflections(rot, mirror_x, mirror_y))
        return (0, False, False)

    def _sym_id(self, u) -> str:
        """Return the ``<defs>`` id a unit's ``<use>`` refers to.

        One definition per ``(kind, variant)``, suffixed for anything baked
        in: a built-to-measure size, a resized unit's pen compensation
        (:func:`_pen_scale`) or redraw (:func:`_fold`), and the
        counter-transform from :meth:`_baked_xform`. Passed through
        :func:`~pandid.render.escape.ident` because custom kinds are
        author-chosen.

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
        sym = self.registry.for_unit(u)
        body = u.kind if variant == "default" else f"{u.kind}_{variant}"
        body += sym.id_suffix + _size_tag(sym, u) + _xform_tag(*self._baked_xform(u))
        return ident("sym", body)

    def _defs(self, fs, arrows=True):
        """Return the ``<defs>`` block: arrow markers and symbol definitions.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        arrows : bool, default=True
            Whether to define arrowhead markers; a P&ID draws none.

        Returns
        -------
        list[str]
            SVG lines.
        """
        lines = []
        # Sort for byte-identical output across runs (set order depends on
        # the hash seed).
        used_colors = sorted({s.color or "black" for s in fs.streams})
        lines.append('  <defs>')
        # No arrowheads, no markers.
        for c in used_colors if arrows else ():
            lines.append(
                f'    <marker id="{arrow_marker_id(c)}" viewBox="0 0 10 10" '
                f'refX="10" refY="5" '
                f'markerWidth="{ARROWHEAD:g}" markerHeight="{ARROWHEAD:g}" '
                f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{escaped(c)}" />')
            lines.append('    </marker>')

        # One definition per (kind, variant) unless something is baked in:
        # a counter-transform for lettering or a directional mark, a
        # built-to-measure size, or a resized unit's pen compensation
        # (_pen_scale), which a shared definition cannot carry.
        used: dict[tuple, tuple] = {}
        # Definitions placed in a box of another shape. A <symbol> would
        # letterbox the artwork while portgeom maps ports linearly onto the
        # box, so stretchable symbols are stretched to agree
        # (Symbol.stretchable); for the rest portgeom follows the letterbox.
        stretched: set[tuple] = set()
        for u in fs.units:
            if u.kind in ("feed", "product"):
                continue
            sym = self.registry.for_unit(u)
            xform = self._baked_xform(u)
            fold, pen = _fold(sym, u), _pen_scale(sym, u)
            key = ((u.kind, getattr(u, 'variant', 'default'), sym.id_suffix, fold, pen)
                   + xform)
            used[key] = (self._sym_id(u), sym, fold, pen, *xform)
            # A redrawn definition already fills its box.
            if sym.stretchable and _reshapes(sym, u) and fold == (1.0, 1.0):
                stretched.add(key)
        for key in sorted(used):
            sym_id, sym, fold, pen, rot, mirror_x, mirror_y = used[key]
            # Redraw first, so later steps use the definition's coordinates.
            art = _baked(sym.svg, *fold)
            width, height = sym.width * fold[0], sym.height * fold[1]
            # Artwork is drawn at the EQUIPMENT weight (:func:`_nominal`);
            # divide out the symbol's class weight here, and keep `pen` as
            # the resize factor alone, which _size_tag and the key read.
            stroke = pen * LineWeight.EQUIPMENT.width / _class_weight(sym).width
            # A directional symbol has no lettering (tested over the
            # registry), so it needs only one of the two counter-transforms.
            if sym.directional:
                svg_str = _upright_artwork(_at_pen_scale(art, stroke),
                                           width, height, mirror_x, mirror_y)
            else:
                svg_str = _upright_text(_at_pen_scale(art, stroke), rot, mirror_x, mirror_y)
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                # Stretch only where a placement reshapes the artwork.
                fill = ' preserveAspectRatio="none"' if key in stretched else ''
                # overflow="visible" stops the viewport clipping strokes on
                # the viewBox edge, which would thin a circle at four points.
                box = (f"{sym.width} {sym.height}" if fold == (1.0, 1.0)
                       else f"{_art(width)} {_art(height)}")
                svg_str = (f'<symbol id="{sym_id}" viewBox="0 0 {box}"'
                           f'{fill} overflow="visible">{inner}</symbol>')
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')
        return lines

    # --- units --------------------------------------------------------

    def _draw_units(self, fs, label_items, balloons, ink=(), joints=None,
                    quadrants=()):
        """Return the ``units`` group and collect tags and balloons.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        label_items : list
            Receives tag, ``NC`` and fail-position label items.
        balloons : list[str]
            Receives instrument SVG, drawn later over the lines.
        ink : sequence of _Ink, optional
            Drawn lines for tags to avoid.
        joints : str, optional
            Sheet joint default, for flange marks to avoid.
        quadrants : sequence, optional
            Quadrant label items for tags to avoid.

        Returns
        -------
        list[str]
            SVG lines.
        """
        from pandid.portgeom import unit_box

        lines = ['  <g id="units">']
        # Every symbol box, with its unit, for tags to avoid. Flange marks
        # and quadrant codes have no owner, so every tag avoids them.
        symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
        symbols += [(None, b) for b in flange_boxes(fs, joints)]
        symbols += [(None, b) for b in map(_unit_label_box, quadrants) if b is not None]
        for u in fs.units:
            f = u.frame
            out = balloons if u.kind == "instrument" else lines
            x, y = f.x, f.y
            # Draw the shared tag, not the unique name, for repeated symbols.
            safe_name = escaped(u.tag)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, safe_name))
                continue

            sym_id = self._sym_id(u)
            u_width, u_height = f.w, f.h
            rot = int(getattr(f, "orientation", 0) or 0)
            mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
            cx, cy = x + u_width / 2, y + u_height / 2

            # A quarter turn swaps the artwork box; centre it on the frame
            # so rotating about the centre lands it on the frame.
            if rot in (90, 270):
                bw, bh = u_height, u_width
            else:
                bw, bh = u_width, u_height
            ux, uy = cx - bw / 2, cy - bh / 2

            # SVG composes right to left: mirror, then rotate, matching
            # portgeom.symbol_to_box.
            ops = []
            if rot:
                ops.append(f"rotate({rot}, {_num(cx)}, {_num(cy)})")
            if mirror_x:
                ops.append(f"translate({_num(2 * cx)}, 0) scale(-1, 1)")
            if mirror_y:
                ops.append(f"translate(0, {_num(2 * cy)}) scale(1, -1)")
            transform = f' transform="{" ".join(ops)}"' if ops else ""
            out.append(f'    <use href="#{sym_id}" x="{_num(ux)}" y="{_num(uy)}" '
                       f'width="{bw}" height="{bh}"{transform} />')

            if u.kind == "instrument":
                out.extend(self._draw_instrument_tag(u, x, y, u_width, u_height))
            else:
                # Untagged symbols (a pipe tee) get no label.
                tag_box = None
                if u.tag:
                    item = self._tag_item(u, f, x, y, u_width, u_height, safe_name,
                                          ink, symbols)
                    tag_box = _unit_label_box(item)
                    label_items.append(item)
                # Letter NC where the body cannot be darkened (ISO 15519-1
                # 11.4.5).
                if closed_marking(u, self.registry) == "NC":
                    label_items.append(
                        self._nc_label_item(u, f, x, y, u_width, u_height, tag_box))
                # Fail position of an actuated valve (ISA-5.1 Table 5.4.4).
                letters = fail_marking(u)
                if letters:
                    label_items.append(
                        self._fail_label_item(u, f, x, y, u_width, u_height, letters,
                                              tag_box, ink, symbols))
        lines.append('  </g>')
        return lines

    def _draw_taps(self, fs):
        """Return the lines from tap points to the balloons reading them.

        Solid for an impulse line (tubing full of process fluid), dashed for
        a signal or command (a balloon on a balloon, on a signal line, or a
        trip square on its valve); see :func:`impulse_tap`. Lines come from
        :func:`tap_lines`, which label placement also avoids. Drawn on the
        DETAIL rung, as ISO 15519-2 Annex A.1.02 puts an instrument
        connection at 0.25 mm.

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
        for u, (tx, ty), (cx, cy) in tap_lines(fs):
            dash = "" if impulse_tap(u) else f' stroke-dasharray="{_TAP_DASH}"'
            out.append(f'    <line x1="{_num(tx)}" y1="{_num(ty)}" x2="{_num(cx)}" '
                       f'y2="{_num(cy)}" stroke="black" '
                       f'stroke-width="{LineWeight.DETAIL.width:g}"{dash} />')
        return ['  <g id="instrument_taps">'] + out + ['  </g>'] if out else []

    def _draw_boundary(self, u, f, safe_name):
        """Return a Feed or Product off-page flag.

        A ``reference`` adds a second line naming the connected drawing.

        Parameters
        ----------
        u : Unit
            Boundary unit.
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
        # Pennant geometry is shared with draw.io (:func:`boundary_flag`).
        # Centre on the pennant's own top and bottom, so a taller flag
        # keeps its point and lettering in the middle of its ink.
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
        # Drawn on the ISO 10628-1 5.3.1 b) symbol rung, as in draw.io.
        out = [f'    <polygon points="{points}" fill="transparent" '
               f'stroke="black" stroke-width="{LineWeight.EQUIPMENT.width:g}" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{mid - 4}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{mid + 8}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{escaped(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{mid}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        """Return the balloon lettering: function letters over loop number.

        An interlock square carries the number alone (ISA-5.1).

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
        # The shared tag, not the unique name.
        tag = getattr(u, "tag", "") or u.name
        top, bot = split_tag(getattr(u, "type", "") or tag, getattr(u, "number", "") or "")
        cx, cy = x + u_width / 2, y + u_height / 2
        if variant in _DIAMOND_BALLOONS:
            # Put the number in the lower half of the diamond, as ISA-5.1
            # does; 7 units below centre clears a two-figure number.
            return [f'    <text x="{cx}" y="{cy + 7}" font-family="sans-serif" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top)}</text>']
        if not top:
            return [f'    <text x="{cx}" y="{cy}" font-family="sans-serif" '
                    f'font-size="12" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top)}</text>']
        # A location bar crosses the middle, so push letters above it and
        # the number below (ISA-5.1).
        letters_dy, number_dy = (-10, 11) if variant in _BARRED_BALLOONS else (-4, 10)
        out = [f'    <text x="{cx}" y="{cy + letters_dy}" font-family="sans-serif" '
               f'font-size="12" font-weight="bold" text-anchor="middle" '
               f'dominant-baseline="middle">{escaped(top.upper())}</text>']
        if bot:
            out.append(f'    <text x="{cx}" y="{cy + number_dy}" font-family="sans-serif" '
                       f'font-size="11" text-anchor="middle" '
                       f'dominant-baseline="middle">{escaped(bot)}</text>')
        return out

    def _label_place(self, lpos: str, x: float, y: float, u_width: float,
                     u_height: float) -> "tuple[float, float, str, str]":
        """Return a label's anchor point and text alignment for one side.

        Parameters
        ----------
        lpos : str
            One of :data:`LABEL_POSITIONS`, or ``"top_right"`` for the NC
            marking. Validation rejects anything else, so the final
            ``top`` branch is that side, not a fallback.
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
            # Above and to the right, on a top label's baseline (NC only).
            return x + u_width, y - 10, "start", "baseline"
        return x + u_width / 2, y - 10, "middle", "baseline"  # top

    def _unit_label_item(self, u, f, x, y, u_width, u_height, safe_name):
        """Return a unit label item on its layout-chosen side.

        Parameters
        ----------
        u : Unit
            Unit.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        safe_name : str
            Escaped tag.

        Returns
        -------
        tuple
            ``(x, y, anchor, baseline, side, text)``, drawn by
            :meth:`_draw_unit_labels`.
        """
        lpos = f.label_pos or "top"
        return (*self._label_place(lpos, x, y, u_width, u_height), lpos, safe_name)

    def _tag_item(self, u, f, x, y, u_width, u_height, safe_name, ink, symbols=()):
        """Return the equipment tag item, moved clear of drawn ink.

        Layout chose a side from faces without nozzles
        (:func:`~pandid.layout.coordinates.assign_labels`), but passing
        lines, impulse lines and balloons can still lie there, and the tag's
        opaque halo would erase them. The tag first slides along its side,
        then tries other free sides; the first placement that erases
        nothing wins, otherwise the least damaging (:func:`_erases`), ties
        keeping the earlier one. A side set on the unit or fixed by the
        symbol is kept.

        Parameters
        ----------
        u : Unit
            Unit.
        f : Frame
            Its frame.
        x, y, u_width, u_height : float
            Unit box.
        safe_name : str
            Escaped tag.
        ink : sequence of _Ink
            Drawn lines.
        symbols : sequence of tuple, optional
            ``(unit, box)`` for every symbol and owner-less mark.

        Returns
        -------
        tuple
            Label item.
        """
        from pandid.layout.coordinates import free_label_sides

        item = self._unit_label_item(u, f, x, y, u_width, u_height, safe_name)
        box = _unit_label_box(item)
        if box is None or not (ink or symbols):
            return item
        if getattr(u, "label_pos", None) or self.registry.for_unit(u).label_pos:
            return item
        # Test only ink near the unit, to keep the search cheap.
        pad = max(u_width, u_height) + (box[2] - box[0])
        window = (x - pad, y - pad, x + u_width + pad, y + u_height + pad)
        near = [line for line in ink if _meets(line.box, window)]
        # Exclude the unit's own box, which the tag never overlaps. Grow
        # the others to their ink here so draw.io gets the same answer.
        others = [_obstacle(b) for v, b in symbols
                  if v is not u and _meets(_obstacle(b), window)]

        clear = (0, 0, 0)
        best, damage = item, _erases(box, near, others)
        sides = [item[4]] + [s for s in free_label_sides(u) if s != item[4]]
        for side in sides:
            if damage == clear:
                break
            lx, ly, anchor, baseline = self._label_place(side, x, y, u_width, u_height)
            # Slide at most half the face, or it reads as the neighbour's.
            edgewise = side in ("left", "right")
            for sx, sy in _slide(lx, ly, (u_height if edgewise else u_width) / 2, edgewise):
                spot = (sx, sy, anchor, baseline, side, safe_name)
                cost = _erases(_unit_label_box(spot), near, others)
                if cost < damage:
                    best, damage = spot, cost
                    if damage == clear:
                        break
        return best

    def _nc_label_item(self, u, f, x, y, u_width, u_height, tag_box=None):
        """Return the ``NC`` label for a body that cannot be darkened.

        ISO 15519-1 11.4.5 (Figure 28) letters ``NC`` above and to the
        right of the symbol. The corner is fixed so closed valves can be
        scanned for, and it is the corner a tag least often uses. This
        differs from PIP PIC001 4.2.2.8's placement, deliberately: PIP
        supplies the darkened body (4.2.2.7) and ISO the lettering (see
        :func:`pandid.render.symbols.closed_marking`). If the tag reaches
        into that corner, the letters step right past it.

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
            u, f, x, y, u_width, u_height, escaped(u.tag)))
        nc = _unit_label_box(item)
        if tag is not None and nc is not None and (
                tag[0] < nc[2] and tag[2] > nc[0] and tag[1] < nc[3] and tag[3] > nc[1]):
            lx, ly, anchor, baseline, lpos, text = item
            item = (lx + tag[2] - nc[0] + 6, ly, anchor, baseline, lpos, text)
        return item

    def _fail_label_item(self, u, f, x, y, u_width, u_height, letters, tag_box=None,
                         ink=(), symbols=()):
        """Return the fail-position letters beside a control valve.

        Letters per ANSI/ISA-5.1-2009 Table 5.4.4 Method B, as PIP PIC001
        4.5.3.2 requires (:func:`pandid.render.symbols.fail_marking`),
        placed per PIP PIC001 4.2.4.6(1): below a horizontal valve, right of
        a vertical one. Unlike ``NC``, which sits in a corner, these sit
        against a face, so a quarter turn moves them.

        If the tag is on that side, the letters step out past it; then
        :func:`_step_aside` slides them along the face off any line or
        symbol, within half the face so they stay beside the body.

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
        # 90 and 270 both stand the run on end; 0 and 180 both leave it
        # flat.
        upright = int(getattr(f, "orientation", 0) or 0) in (90, 270)
        lpos = "right" if upright else "bottom"
        item = (*self._label_place(lpos, x, y, u_width, u_height), lpos, letters)
        tag = tag_box if tag_box is not None else _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, escaped(u.tag)))
        fail = _unit_label_box(item)
        if tag is not None and fail is not None and (
                tag[0] < fail[2] and tag[2] > fail[0] and tag[1] < fail[3] and tag[3] > fail[1]):
            lx, ly, anchor, baseline, lpos, text = item
            # Step past the tag by the overlap plus a gap; less below,
            # since the halo already adds vertical margin.
            if upright:
                item = (lx + tag[2] - fail[0] + 6, ly, anchor, baseline, lpos, text)
            else:
                item = (lx, ly + tag[3] - fail[1] + 4, anchor, baseline, lpos, text)
        # Exclude the unit's own box, as _tag_item does.
        others = [_obstacle(b) for v, b in symbols if v is not u]
        if tag is not None:
            others.append(tag)
        # Slide at most until the plate's near edge reaches the far end of
        # the face, keeping the letters adjacent to the symbol (ISO
        # 15519-1 7.2.3).
        plate = _unit_label_box(item)
        # Only a "center" item has no box, and lpos is right or bottom.
        assert plate is not None
        face, along = ((u_height, plate[3] - plate[1]) if upright
                       else (u_width, plate[2] - plate[0]))
        return _step_aside(item, (face + along) / 2, ink, others)

    def _draw_unit_labels(self, items):
        """Return the final label pass: tags on white halos over the lines.

        A ``center`` label sits inside its symbol and gets no halo.

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
                       f'font-size="12" text-anchor="{anchor}" '
                       f'dominant-baseline="{baseline}">{text}</text>')
        out.append('  </g>')
        return out

    # --- streams ------------------------------------------------------

    def _tipped(self, s, arrows: bool) -> bool:
        """Return whether this render draws an arrowhead on the stream.

        :func:`wears_arrowhead`, and ``arrows`` is false on a P&ID.

        Parameters
        ----------
        s : Stream
            Stream.
        arrows : bool
            Whether the sheet draws arrowheads.

        Returns
        -------
        bool
            Whether to add the marker.
        """
        return arrows and wears_arrowhead(s, self.registry)

    def _draw_streams(self, fs, jump_direction, unit_labels, arrows=True,
                      plates=None, joints=None, crossing_style="arc"):
        """Return the ``streams`` group: runs, joint marks and stream numbers.

        Every crossing style uses the same ``2 * HOP_R`` of run (arc, pen
        lift or plain line), so :func:`unmarked_crossings` is the same for
        all. :func:`_ink` reserves a :func:`hop_box` at every crossing
        whatever the style, so stream numbers do not move when the style
        changes. Number placement is :func:`stream_numbers`', shared with
        draw.io.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        jump_direction : str
            Which crossing line carries the mark.
        unit_labels : list
            Tag items already placed, for numbers to avoid.
        arrows : bool, default=True
            Whether process lines get arrowheads.
        plates : list, optional
            Receives every opaque box reserved by the label passes, for the
            debug overlay (:func:`pandid.render.debug.overlay`).
        joints : str, optional
            Sheet joint default (:func:`sheet_connections`), or ``None``.
        crossing_style : str, default="arc"
            Crossing mark (:data:`CROSSING_STYLES`). :meth:`render` always
            passes its own value, whose default is ``"gap"``.

        Returns
        -------
        list[str]
            SVG lines.
        """
        stream_geoms = [(s, stream_polyline(s)) for s in fs.streams]
        # Hops for the whole sheet, keyed by (stream, segment) in drawing
        # order (:func:`stream_hops`).
        hops: dict[tuple[int, int], list[_Hop]] = {}
        if crossing_style != "plain":
            for hop in stream_hops(fs, jump_direction):
                hops.setdefault((hop.stream, hop.seg), []).append(hop)

        # The crossing mark is the only path command the styles differ in.
        # A gap is an ``M`` subpath in the same ``d``, so the run stays one
        # element and ``marker-end`` stays on its far end.

        def cross(far: str) -> str:
            """Return the path command crossing to the far side ``"x,y"``."""
            if crossing_style == "arc":
                return f"A {HOP_R:g} {HOP_R:g} 0 0 1 {far}"
            return f"M {far}"

        lines = ['  <g id="streams">']
        for n, (s, points) in enumerate(stream_geoms):
            paint = s.color or "black"
            # Same function as _defs, so reference and definition match.
            marker_id = arrow_marker_id(paint)
            # Escape at the sink, though check_color already restricts it.
            color = escaped(paint)
            is_signal = s.kind in _SIGNAL_KINDS
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{escaped(s.dasharray)}"'
            elif s.kind in _SIGNAL_DASH:
                dash = f' stroke-dasharray="{_SIGNAL_DASH[s.kind]}"'

            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                # Stop HOP_R before the crossing, then cross to HOP_R past
                # it. Sweep flag 1 keeps the arc on the travel side; ``:g``
                # because HOP_R is not a whole number.
                for hop in hops.get((n, i), ()):
                    if hop.vertical:
                        foot = HOP_R if y1 < y2 else -HOP_R
                        d_parts.extend([
                            f"L {x1},{hop.y - foot:g}",
                            cross(f"{x1},{hop.y + foot:g}")])
                    else:
                        foot = HOP_R if x1 < x2 else -HOP_R
                        d_parts.extend([
                            f"L {hop.x - foot:g},{y1}",
                            cross(f"{hop.x + foot:g},{y1}")])
                d_parts.append(f"L {x2},{y2}")
            d_str = " ".join(d_parts)

            marker = f' marker-end="url(#{marker_id})"' if self._tipped(s, arrows) else ""
            # Signals at half the pipe weight (ISO 15519-2 Annex A.1.01-A.1.03).
            width = _stream_rung(is_signal).width
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="{width:g}"{dash}{marker} />'
            )

            # Joint marks are drawn over the line, as flange faces across
            # the run, not as a gap in it.
            for fx, fy, angle, _at in flange_marks(s, points,
                                                   resolve_connections(s, joints)):
                rad = math.radians(angle)
                # Flange faces are a piping accessory, ISO 10628-1 5.3.1 c)
                # (DETAIL). That rung also satisfies 5.3.2: bars FLANGE_GAP
                # apart leave 5 - w of paper, at least 2w and 1 mm (4
                # units) only for w = 1. Offset along the run, bars across.
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

            if s.kind == "pneumatic":
                # Pneumatic hatching (ISO 15519-2 Annex A.1.09, 433A) on the
                # line's own rung, ISO 10628-1 5.3.1 c).
                along, across = HATCH_ARM
                for mx, my, horiz, _at in pneumatic_marks(points):
                    for off in HATCH_ALONG:
                        if horiz:
                            x1, y1 = mx + off - along, my + across
                            x2, y2 = mx + off + along, my - across
                        else:
                            x1, y1 = mx - across, my + off - along
                            x2, y2 = mx + across, my + off + along
                        lines.append(f'    <line x1="{x1:.1f}" y1="{y1:.1f}" '
                                     f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
                                     f'stroke-width="{LineWeight.DETAIL.width:g}" />')

        # Final pass: stream numbers on white halos. A label on a vertical
        # run reads bottom to top, along the line (ISO 15519-1 5.1.5,
        # 7.2.5, Figure 40). Placement is :func:`stream_numbers`'.
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
            # Draw the leader over the words so it meets the label; only a
            # bare label has one (:func:`stream_numbers`).
            if number.leader is not None:
                (ax0, ay0), (ax1, ay1) = number.leader
                # In the label's colour, as part of the label.
                lines.append(f'    <line x1="{ax0:.1f}" y1="{ay0:.1f}" '
                             f'x2="{ax1:.1f}" y2="{ay1:.1f}" '
                             f'stroke="{color}" '
                             f'stroke-width="{LineWeight.DETAIL.width:g}" />')
                lines.append(f'    <path d="{_arrowhead(*number.leader)}" fill="{color}" />')
        # ``placed`` now holds every box both label passes reserved, which
        # is what the debug overlay must avoid.
        if plates is not None:
            plates.extend(placed)
        lines.append('  </g>')
        return lines
