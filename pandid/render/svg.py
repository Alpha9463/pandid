"""SVG rendering backend."""

from typing import NamedTuple, TYPE_CHECKING
import html
import math
import re
from datetime import datetime
from functools import lru_cache

from pandid.render import furniture as F
from pandid.render.symbols import (ARROWHEAD, closed_marking, fail_marking,
                                   wears_arrowhead)
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

# A symbol's own lettering: the "M" in a motor operator, the "S" in a solenoid.
# Matched to be counter-transformed when the symbol is turned or flipped.
_SYMBOL_TEXT = re.compile(
    r'<text\b[^>]*?\bx="(-?[\d.]+)"[^>]*?\by="(-?[\d.]+)"[^>]*?>.*?</text>', re.S)
# Balloon variants whose symbol draws a location bar across the middle (see the
# instrument symbols in pandid.render.symbols): their tag text has to clear it.
#
# ``shared`` joined them for #181. It is the one variant that carries a bar
# *and* a square, and the pair is not a contradiction: ISO 15519-2 Table 1
# (p. 7) makes the bar an "additional graphic" answering where the information
# lives -- one full line is "Information available in central control system" --
# while the square answers what the function is, and a shared display is a
# control-room function by definition. All forty balloons on
# ``professional_examples/P&ID_301.pdf`` carry one, twelve of them squared.
_BARRED_BALLOONS = {"panel", "aux", "shared"}
# Variants drawn as a diamond (ISA-5.1-2009 Table 5.1.1 column B and Table 5.1.2
# items 3-5): they carry the interlock number alone, and it has to sit where the
# sloping sides leave room for it rather than in the middle of the box.
_DIAMOND_BALLOONS = {"sis", "logic", "interlock"}
# Variants that stand for a device out on the plant. Every ISA-5.1 balloon but
# the bare circle is a *location or function* symbol and says outright that the
# function is somewhere else: a bar across it puts it in a panel (Table 5.1.1
# rows 2-5), a square around it in the shared display (column B), a hexagon in a
# computer (column C) and a diamond in a logic solver (column D and Table 5.1.2).
# Only a thing in the field can have process fluid piped to it, which is what
# decides whether the line reaching it is impulse tubing; see :func:`impulse_tap`.
#
# Named positively so a location symbol added later is out rather than in. A
# dashed line claims the less of the two, and the drawing that is wrong the
# quieter way is the one to default to.
_FIELD_BALLOONS = {"default"}

# --- line weights ------------------------------------------------------------
# ISO 15519 draws a process diagram in two weights, and the ratio between them
# is what tells a reader the process from the instrumentation at a glance.
#
# ISO 15519-1 §6.2 Table 1 gives the process industry field symbols 0,1 M and
# connections 0,2 M, with 0,4 M available where §12.2 wants a significant
# connection emphasised, and M = 2,5 mm (§11.1.2). That is the 0,25 / 0,5 / 1,0
# ladder ISO 10628-1 §5.3.1 uses: one ladder, of which ISO 15519 spends two
# rungs by default and holds the third in reserve. §6.2 then makes the spacing
# a requirement rather than a habit: "If two or more widths of line are used,
# the ratio between any two widths shall be at least 2:1."
#
# ISO 15519-2 Annex A.1 spends that pair per line type: A.1.01 pipeline 0,50;
# A.1.02 instrument connection and control connection 0,25; A.1.03 pilot line
# and signal line 0,25.
#
# A drawing unit here is a CSS pixel, 25,4/96 mm, so 2 and 1 land on 0,53 mm and
# 0,26 mm, which is the standard's own pair at exactly the 2:1 it requires.
# They are relative weights within one drawing and still scale with the sheet;
# holding them at a physical width is ISO 15519-1 §11.1.3's separate problem.
_PROCESS_STROKE = 2
_SIGNAL_STROKE = 1

#: The dash a signal line is drawn with, per kind. A pneumatic line is absent
#: because it is drawn *solid* and marked with cross-hatches instead, and a
#: capillary's short dash is its own; the rest are the conventional ones. Held
#: at module scope rather than inside the draw pass because the draw.io export
#: has to write the same line: two tables of dashes is two answers to "what does
#: an electric signal look like".
_SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                "capillary": "3,3"}

#: The dash a tap line is drawn with where what it carries is a measurement or a
#: command rather than process fluid; an impulse line is solid. See
#: :meth:`SvgRenderer._draw_taps` and :func:`impulse_tap`. Here beside the signal
#: dashes and for the same reason: the export writes this one too.
_TAP_DASH = "5,4"

#: The radius of the semicircle a crossing line hops with, which is half the
#: length of run the hop takes out and how far it stands off it.
#: :meth:`SvgRenderer._draw_streams` builds the arc from this and nothing else.
#:
#: Named for the same reason :data:`_TAP_DASH` is: draw.io draws its own hop from
#: a ``jumpSize``, which is a *different* number in a different arithmetic
#: (``mxConnector.paintLine``: half-extent = ``(jumpSize - 2) / 2 + strokeWidth``),
#: and :func:`pandid.render.drawio._jump_size` solves that for this radius. Two
#: literal fives, one here and one in the exporter, would be two answers to how
#: big a hop is on this sheet.
HOP_R = 5

# --- stream-label placement -------------------------------------------------
# A stream label is written on an opaque halo, so it can only sit *on* the pipe
# where the run is long enough to leave pipe showing at each end: the ARROWHEAD
# a PFD draws, plus enough line either side that the run still reads as one line
# rather than two stubs. Anything shorter is written beside the pipe instead,
# which is what a sheet does with a line number a dozen characters long.
_LABEL_CLEAR = 20.0
# Gap from the pipe to the near edge of a label written beside it.
_LABEL_GAP = 4.0
# Search step along the run. Fine, because a label only has to clear whatever it
# landed on rather than jump a whole label width.
_LABEL_STEP = 6.0
# How many bands of sideways stand-off the search may walk through. Beyond
# _label_reach below each one costs a leader line, so the walk is free to go
# further than it used to in search of paper that is actually clear, instead of
# settling for the least damaging spot within three bands.
#
# It is a bound on the search and not a judgement about what reads: a clear band
# wins outright and the bands are walked inward-out, so the number only ever
# matters to a label whose nearer bands are all spoken for. Six left exactly one
# such label on the shipped corpus with nowhere at all to go -- AE-304 on
# ``11_ethanol_pid``, a sixteen-character number naming a thirty-unit stub
# wedged between a condenser and a reflux drum, whose 276 candidate spots all
# covered something once a halo stopped being allowed to break a symbol
# (:func:`_covering`). Its first clear band is the seventh. Seven is where the
# answer settles rather than merely where it first appears: at 8, 10 and 12
# bands that label lands in the same place, because the walk stops at the first
# clear band and there is nothing past it to find.
_LABEL_BANDS = 7

#: The weight a graphical symbol's outline is drawn at, in whatever box it is
#: placed in. ISO 15519-1 §11.1.3 is a *shall* -- "When the size of a symbol is
#: changed, the line width shall be unchanged" -- and :func:`_nominal` is what
#: holds every artwork in the registry to it, so this is one number for all of
#: them and not a property of any one drawing.
_SYMBOL_STROKE = 2.0

#: The paper a label's opaque plate leaves outside a symbol's ink.
#:
#: **A symbol's box is not its ink**, and this is the whole of issue #243.
#: :func:`~pandid.portgeom.unit_box` reports the *geometry*; an outline is
#: stroked centred on that geometry, so half the pen falls outside the box, and
#: a plate laid flush against the box covers exactly that half. On the shipped
#: ``examples/14`` V-604's left shell wall is centred on x = 1255 with its pen
#: spanning 1254..1256, and ``VAP-611-150-40-CS``'s plate ended at 1255.0 and
#: deleted the inner half of it. The rendered wall integrated 1.141 of ink for
#: the forty pixels the plate ran beside it and 2.345 the row after it ended:
#: 48,7 % of its weight, with nothing in the drawing to say why. ISO 15519-1
#: §6.2 leaves nothing to call that -- "If two or more widths of line are used,
#: the ratio between any two widths shall be at least 2:1" -- so 2,06:1 inside
#: one outline is not a second weight, it is damage.
#:
#: Stated as a clearance and not as a bare half-pen, because the two say
#: different things and only one of them is arithmetic. Half the pen is where
#: the plate stops *erasing*; this is where it stops *crowding*, and a line
#: number set hard against a vessel wall is bad drafting even on the reading
#: where it takes nothing away, since the reader has to pick the lettering off
#: the equipment. It is the same division :func:`_ink` already makes for a
#: pipe, which pads by a whole stroke and calls half of it ink and half of it
#: margin; the margin is the larger share here because an outline is what
#: identifies a symbol and a run is identified at both ends.
_PLATE_CLEARANCE = 2.0


def _obstacle(box) -> "tuple[float, float, float, float]":
    """A symbol's drawn box, grown to what a label has to keep off.

    Every place in this module that treats a unit as something a label may not
    land on goes through here, so the two label passes -- the equipment tags in
    :meth:`SvgRenderer._tag_item` and the line numbers and their leaders in
    :func:`stream_numbers` -- cannot disagree about where a symbol ends. The
    draw.io exporter builds its own list of boxes and hands them to
    ``_tag_item``, which is why the growth is applied where the boxes are
    *used* rather than where that one list is built: an exporter that had to
    remember to grow them is an exporter that will one day forget.
    """
    pad = _SYMBOL_STROKE / 2 + _PLATE_CLEARANCE
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _along(box, vertical: bool, lo: float, hi: float) -> bool:
    """Is a label at *box* written **along** the run that spans ``lo``..``hi``?

    ISO 15519-1 §7.2.5, on the reference designation of a connection: "They
    shall be oriented along or adjacent to the relevant connecting lines. If it
    is not possible to place the reference designation adjacent to the
    connecting line, it shall be shown elsewhere in the content area with a
    leader line to the actual connecting line. See also 6.4."

    Two *shall*s, and the second names the only escape from the first, so this
    function is where "along" stops and :func:`_leader` takes over. It asks the
    one question the clause turns on: is the line *there*, beside the words?
    A line number is a caption on a length of line, and a caption is attached
    by lying against the thing it captions. Where the run runs past the whole
    string there is nothing to be in doubt about, however wide the paper between
    them; where the string has run out past the end of its own line, the part
    that has overrun is lying against something else, and that something else is
    what a reader attaches it to.

    More than half, because that is the least arbitrary line there is to draw
    and because nothing in the corpus sits on it. Measured over all 145 line
    numbers on the fourteen shipped sheets, twelve overrun their run at all, and
    they fall in two groups with a clear band of nothing between: nine read as
    their own line's without help, from ``VAP-611-150-40-CS`` on 14 at 61 % of
    it alongside up through ``3"-P-1005-A1A`` on 09 at 74 % (overrunning only
    where it passes the relief valve the line leaves) to
    ``E10-609-200-40-CS`` on 14 at 98 %; and three do not --
    ``MS-601-200-40-CS`` on 14 at 40 %, ``S-403`` on 13 at 37 % and
    ``AE-304-150-80-SS`` on 11 at 29 %, the last a sixteen-character number
    naming a thirty-unit stub, so two thirds of it lies against a reflux drum
    and a condenser instead.

    The band has narrowed as the corpus has grown -- 40 % to 61 % over fourteen
    sheets, where it was 32 % to 74 % over twelve -- and that is worth watching
    rather than worth moving the rule for. Half is still the only value in it
    that names something (the words are mostly beside their line, or mostly not)
    and the twelve overruns are still nine plainly one way and three plainly the
    other. A sheet that lands a number *in* the band is the signal that this
    threshold has stopped sorting them, and the two checks in
    ``tests/test_label_invariants.py`` that read this corpus are what would say
    so.

    What this replaces is a cap on the *stand-off*: past one label height of
    blank paper the number was held to be adrift and given a leader. That
    measures the wrong thing, and 11 says so in both directions.
    ``FB-306-100-160-SS`` stands two bands off its own run with a valve tag
    between, and is not in the least ambiguous, because the run it names goes
    the whole length of it and past both ends; it was given a leader anyway, and
    the leader is what introduced the doubt, since it lands under one half of a
    number that was already sitting over its line. ``AE-304`` needs one and is
    only two bands out as well. Distance across the gap is not what decides it.
    """
    a, b = (box[1], box[3]) if vertical else (box[0], box[2])
    return min(b, hi) - max(a, lo) > (b - a) / 2


def _slide(x: float, y: float, room: float, vertical: bool):
    """Anchor positions along a run: centred first, then out either way."""
    yield x, y
    for k in range(1, int(room // _LABEL_STEP) + 1):
        d = k * _LABEL_STEP
        yield (x, y - d) if vertical else (x - d, y)
        yield (x, y + d) if vertical else (x + d, y)


# --- the ink a halo would delete ---------------------------------------------
# Every label on the sheet is written on an opaque rect, so wherever one lands it
# erases whatever was drawn under it. Placement has to be told where the ink is,
# and the ink is not just the symbols: it is every routed segment and every
# impulse line too. A halo that deletes a length of somebody else's pipe leaves
# a drawing that says two things which are not true -- that the line stops there,
# and that the gap is where a reader may write -- and neither is visible to the
# validator, since the topology it checks is untouched. So the lines are seeded
# as occupied alongside the boxes, and what is left is a *placement* problem.


class _Ink(NamedTuple):
    """A drawn line, as the rectangle its stroke covers.

    ``axis``/``at`` name the infinite line it lies on (``"h"`` at a ``y``,
    ``"v"`` at an ``x``), which is how a label tells its own run from a line
    that merely crosses it: breaking the run you are labelling is the whole
    convention, and breaking the one beside it is a lie about that line.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    axis: str
    at: float
    kind: str  # "pipe" or "tap"

    @property
    def box(self) -> "tuple[float, float, float, float]":
        """The covered rectangle, in the form every collision test here takes."""
        return (self.x0, self.y0, self.x1, self.y1)


def tap_lines(fs):
    """Every impulse line the sheet draws, as ``(instrument, tap point, balloon
    centre)``.

    The line from a tap to the balloon reading it, and the rule for when there
    is one at all: nothing is drawn where the balloon is merely *placed*
    against its host (``near=``; see :data:`~pandid.units.RELATIONS`), where a
    stream already joins the two, or where the element sits directly on the
    line (``offset=0``). Shared by the drawing pass and by label placement, so
    a label cannot be placed against an impulse line the renderer then declines
    to draw, or over one it does.

    ``near=`` is issue #137. An author wanting somewhere to hang a control-room
    faceplate had only ``on=``, which meant both, so the sheet grew a line
    saying the faceplate was piped to a drum. A placement is now a placement.

    Shared with the draw.io exporter for the reason :func:`stream_polyline` is:
    these are the only lines on a P&ID that are not streams, so an exporter that
    walked ``fs.streams`` alone dropped every one of them and left all 26 of
    ``11_ethanol_pid``'s balloons floating unconnected. There is one derivation
    of where a tap line runs, and this is it.
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
    """Is the line between *inst* and its host a length of impulse tubing?

    The question is about the **edge**, not about the class of either thing on
    the end of it. An impulse line is a piece of pipe: it exists only where
    there is process fluid at one end and something out in the plant to pipe it
    to at the other. So both ends are asked, and each answers out of a fact the
    model already states.

    *The host end* carries fluid unless it carries a measurement instead: a
    balloon holds nothing at all, and a signal line holds a command. Everything
    else a balloon may hang on -- a process line, a vessel, an exchanger, an
    in-line element -- is full of the fluid the reading is taken from.

    *The balloon end* can receive it only where the balloon is a device in the
    field. Every other ISA-5.1 balloon is a symbol for a function in a panel, in
    the shared display, in a computer or in a logic solver, and no tubing runs
    from a drum to any of those; see :data:`_FIELD_BALLOONS`.

    *The line itself* has to be carrying the reading. Tubing brings the fluid
    **to** the instrument, so only a ``sensing`` relation can be one; a trip
    square hung on the valve it strokes is ``acting_on``, and what runs down to
    the actuator is a command.

    Reading the host alone, which is what this used to do, answered a question
    about the *host* and drew the answer as though it were about the line. Three
    of the shipped sheets state something untrue because of it, every one of
    them solid where the line carries no fluid: 11's feed trip square is drawn
    as impulse tubing off a solenoid valve while four identical squares
    elsewhere on that sheet are dashed, and 07's and 08's control-room level
    controllers, declared ``on`` a vessel for placement only, are drawn piped to
    it. The host is a piece of plant in all three, and in none of them is the
    line.
    """
    host = getattr(inst, "host", None)
    host_kind = getattr(host, "kind", "")
    holds_fluid = (host is not None and host_kind != "instrument"
                   and host_kind not in _SIGNAL_KINDS)
    return (holds_fluid
            and getattr(inst, "relation", "sensing") == "sensing"
            and getattr(inst, "variant", "default") in _FIELD_BALLOONS)


# --- letter codes written outside the symbol ---------------------------------
# ISO 15519-2 §5.1.3, p. 19: "Information placed outside the PCI symbol shall be
# placed in the four quadrants around the symbol as illustrated in Figure 8.
# This allows for horizontal and vertical connections to the symbol."
#
# The quadrants are the *corners*, and the second sentence is why: N, S, E and W
# stay clear for the four connections a balloon takes, so annotating one spends
# no face. That is the half of #253 that also undoes what #253 records -- a
# controller whose north face was "spent on the high alarm".
#
# What §5.2.5 fixes is the *vertical* half: "increasing value away from the
# centre line", so a high function is above it and a low one below. Which side of
# the symbol the pair goes on it does not fix, and
# ``professional_examples/P&ID_301.pdf`` bears that out -- all three of its
# annotated controllers put their alarms on the left, which is the side each of
# them has room on. So a pair keeps its half of the symbol and takes whichever
# side reads: the two kinds of information are (a) references and safety
# identifiers with (b) the measured-variable type for letter code U, and (c) high
# functions with (d) low.

#: Each quadrant as ``(side, away)``: which way from the symbol it sits, and
#: which way a second code in it stacks. Both are +1 right/down.
_QUADRANTS = {"a": (-1, -1), "b": (-1, 1), "c": (1, -1), "d": (1, 1)}

#: The two pairs, in the order they are placed, and the side each prefers. They
#: are placed as pairs because they are read as one: a high code over a low one
#: is a column, and splitting it across the symbol would put the reader's eye in
#: two places for one statement.
_QUADRANT_PAIRS = ((("a", "b"), -1), (("c", "d"), 1))

#: Paper left clear on the symbol's centre line, each side. A connection arrives
#: there -- on ``professional_examples/P&ID_301.pdf`` the signal line into every
#: annotated controller runs between the two alarm codes -- so the band is what
#: keeps the pair straddling the line rather than sitting on it.
_QUADRANT_BAND = 3.0
#: From the symbol's drawn edge to the near edge of the code. 0,12 balloon
#: diameters, which is what PIC-301 and LIC-304 are drawn at (0,142 and 0,085);
#: TIC-302's 0,384 is the outlier and the three together are hand-placed.
_QUADRANT_GAP = 5.0
#: Between two codes stacked in one quadrant: one line of type, so the halos
#: touch and the pair reads as a block.
_QUADRANT_PITCH = 15.0
#: How far outward the search may push a quadrant to find clear paper. The
#: quadrant itself is not up for negotiation -- it is what the code *means* --
#: so the only freedom is the stand-off, and past this the placement is one to
#: make by hand.
_QUADRANT_REACH = 60.0


def quadrant_labels(fs) -> list:
    """Every letter code written outside a symbol, placed.

    Items in :meth:`SvgRenderer._draw_unit_labels`' own form, so the codes are
    haloed and drawn over the lines exactly as an equipment tag is.

    Derived from the flowsheet alone, for the reason :func:`stream_numbers` is:
    the tag pass and the line-number pass both have to dodge these, and a second
    derivation would put them somewhere else for one of the two.
    """
    from pandid.portgeom import unit_box

    annotated = [u for u in fs.units
                 if u.frame is not None and getattr(u, "quadrants", None)]
    if not annotated:
        return []
    ink = _ink(fs)
    symbols = [_obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    symbols += [_obstacle(b) for b in flange_boxes(fs, None)]

    out: list = []
    for u in annotated:
        box = unit_box(u, u.frame)
        for names, prefers in _QUADRANT_PAIRS:
            codes = {name: u.quadrants.get(name) or () for name in names}
            if not any(codes.values()):
                continue
            # The preferred side first, so a tie keeps it; the other only wins
            # by being cleaner, which is the draughtsman's own reason to swap.
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
            # Each code is paper for the next pair, and for the next balloon's:
            # two controllers a balloon apart annotate into the same gap, and
            # the second has to see where the first landed.
            symbols += [b for b in map(_unit_label_box, best[1]) if b is not None]
    return out


def _quadrant_block(box, codes, side: int) -> list:
    """One side's codes, laid out from the symbol's box outward.

    ``codes`` is the pair keyed by quadrant letter; which of the two is above
    the centre line and which below is :data:`_QUADRANTS`', and does not change
    with the side.
    """
    cy = (box[1] + box[3]) / 2
    lx = (box[2] if side > 0 else box[0]) + side * _QUADRANT_GAP
    anchor, lpos = ("start", "right") if side > 0 else ("end", "left")
    return [
        (lx,
         cy + _QUADRANTS[name][1] * (_QUADRANT_BAND + _QUADRANT_PITCH / 2
                                     + i * _QUADRANT_PITCH),
         anchor, "middle", lpos, html.escape(code))
        for name in codes
        for i, code in enumerate(codes[name])
    ]


def _quadrant_stand_off(block, side: int, ink, symbols):
    """How far out of the symbol a pair's codes have to stand, and what is left.

    Returns ``(shift, damage)``. Outward only, and the whole pair moves
    together: the codes are a block whose order is the standard's, so sliding
    one out of line would say something the author did not, and outward is the
    only direction that leaves each code in its own quadrant.

    Scored with :func:`_erases`, so a code gives things up in the order every
    other label on the sheet does -- symbols first, then impulse lines, then
    pipe -- and the smallest clearing step wins, which keeps a code hard against
    its own symbol wherever the paper there is already clear.
    """
    boxes = [b for b in map(_unit_label_box, block) if b is not None]
    if not boxes:
        return 0.0, (0, 0, 0)

    def damage(m: float) -> tuple[int, int, int]:
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


def _ink(fs) -> "list[_Ink]":
    """Every line the sheet draws, as the rectangle its stroke actually covers.

    Padded by a whole stroke width. Half of that is the ink itself, drawn
    centred on the path, and the other half is the margin that stops a halo from
    shaving the edge of a line it only just reaches: a run clipped to nine tenths
    of its weight reads as a fault in the drawing rather than as a line.

    The paths come from :func:`~pandid.layout.attach.stream_path`, which is what
    :meth:`SvgRenderer._draw_streams` draws, so what is dodged here is what
    lands on the sheet.
    """
    from pandid.layout.attach import stream_path

    out: list[_Ink] = []

    def add(a, b, pad: float, kind: str) -> None:
        (ax, ay), (bx, by) = a, b
        if abs(ax - bx) < 0.5 and abs(ay - by) < 0.5:
            return  # a zero-length hop between coincident points draws nothing
        axis, at = ("v", (ax + bx) / 2) if abs(ax - bx) < abs(ay - by) else ("h", (ay + by) / 2)
        out.append(_Ink(min(ax, bx) - pad, min(ay, by) - pad,
                        max(ax, bx) + pad, max(ay, by) + pad, axis, at, kind))

    for s in fs.streams:
        pad = float(_SIGNAL_STROKE if s.kind in _SIGNAL_KINDS else _PROCESS_STROKE)
        points = stream_path(s)
        for a, b in zip(points, points[1:]):
            add(a, b, pad, "pipe")
    for _u, tap, centre in tap_lines(fs):
        add(tap, centre, float(_SIGNAL_STROKE), "tap")
    return out


def _meets(box, region) -> bool:
    """Do two rectangles share any area? Touching edge to edge does not count,
    since the padding a line already carries is what keeps a halo off it."""
    return (box[2] > region[0] and box[0] < region[2]
            and box[3] > region[1] and box[1] < region[3])


def _erases(box, ink, symbols=()) -> "tuple[int, int, int]":
    """What a halo at *box* would delete: symbols, then impulse lines, then pipe.

    Ordered, because the three are not worth the same. An equipment tag written
    over a pipe is a defensible drawing: the run is long, it is identified at
    both ends, and a reader follows it past the break. An impulse line is the
    only mark on the sheet saying *where* a transmitter measures, it is a couple
    of centimetres long, and deleting a length of it deletes the statement.

    A **graphical symbol** is worse than either, and is first for that reason.
    A line broken by a halo is still that line: the reader reads across the gap,
    which is the whole reason writing a number *in* a run is a convention at
    all. A symbol broken by a halo has stopped being the symbol. Its outline is
    what identifies it -- ISO 15519-2 draws an instrument as a circle and a
    shared display as a circle in a square, and the difference between them is
    the outline -- so a bite out of a balloon does not obscure information, it
    replaces one symbol with a shape that is not in the standard, and a reader
    is entitled to read that as a fault in the drawing rather than as a tag
    sitting on top. On ``11_ethanol_pid`` D-301's tag ate the upper-left of
    LT-304's balloon and HV-301C's ate the left edge of PIC-301's square, both
    of them because nothing in this cost function had ever been told a symbol
    was there.

    Comparing these tuples is what does the stepping, so the order above is the
    order a tag gives things up in.
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
    """What a halo at *box* would cover: graphical symbols, then everything else.

    Two numbers and not one, for the reason :func:`_erases` orders its three:
    a line, a tag or another number broken by a halo is still itself, and a
    reader reads across the gap -- writing the number *in* the run is a
    convention precisely because that reading works. A symbol broken by a halo
    has stopped being the symbol, since its outline is what identifies it, so
    covering one is not a worse version of covering a line but a different and
    heavier kind of damage. Counting them together let a label a whole band
    closer to its own run buy that place with a stripe out of a heat
    exchanger's tube bundle, and win, because one box is one box.

    Counting of the second kind stops once the pair is already worse than
    *limit*, the best score so far, because the search only ever needs to know
    whether a spot is worse than the one it is holding. That is what keeps a
    label on a crowded sheet, where nothing is clear and every anchor has to be
    scored, costing what the old first-clear-wins scan cost.
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
    """Slide a valve's position mark **along its own face** until it takes
    nothing away, and return where it ended up.

    This is issue #223, and the shortest statement of it is that the mark had
    exactly one thing it stepped past -- the equipment tag -- and a face has
    three. ``examples/14``'s XV-601 hangs its trip square below the valve and
    fails closed, so PIP PIC001 4.2.4.6(1) puts ``FC`` directly below the body
    and the square's impulse line runs from the same face to the same place; the
    letters' plate is opaque and drawn last, so the sheet lost the only mark on
    it joining the trip to the valve it strokes. The example shipped with the
    fail position taken off and a note in words instead.

    That is the wrong way round. A halo exists so lettering stays legible over
    ink it crosses, and an impulse line is not ink a mark may cross: ISO 15519-2
    §5.1.1 makes the connection between a PCI symbol and the process a *shall*,
    and it is a couple of centimetres long, so a bite out of it is the whole
    statement. :func:`_erases` already ranks exactly that -- a symbol, then an
    impulse line, then pipe -- for the equipment tag, and nothing had ever asked
    it about a position mark.

    **Along the face, and not out from it**, which is the one thing this move
    does that the tag step above it does not. Stepping further *out* is what
    clears a tag, because a tag on the same face is centred on it and as wide as
    the symbol; it is no use at all against an impulse line, which leaves that
    same face and runs the way the mark would be going, so the letters would
    follow it down however far they were pushed. Sideways is the direction that
    gets off it.

    Nothing new decides how far to stand off. The candidates are the exact
    distances that clear each obstacle by :data:`_PLATE_CLEARANCE`, which is
    #243's answer to the same question asked of a line number's plate, taken
    whole; the nearest one that :func:`_erases` then scores clear of everything
    wins, so the mark moves as little as the paper allows and the base position
    is tried first and kept where it is already clear. A tie -- and a plate
    astride a line it has to get off produces one every time, the two ways round
    being the same distance -- goes the way the tag step goes, right and down,
    so the two moves this method makes never disagree about which way is out.

    *room* is how far the caller will let it go, and the caller states it,
    because the bound is about what the mark still reads as belonging to and
    only the caller knows what the mark is. It is not the tag's bound. A tag is
    held to half its symbol's face (:meth:`SvgRenderer._tag_item`) because past
    that it starts reading as the neighbour's, and a tag is written on a face
    that is mostly free. Two letters against a 24-unit valve body are a plate 21
    wide on a face 24 long, and half of it is not enough room to get out from
    under anything: there is no position in that band that a line down the
    middle of the face does not still meet.
    """
    box = _unit_label_box(item)
    if box is None or not (ink or others):
        return item
    lx, ly, anchor, baseline, lpos, text = item
    # Which way the face runs, not which way the label was pushed out along it:
    # a left or right face runs up and down, so the mark slides in y.
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


def _label_anchors(cx: float, cy: float, span: float, hw: float, hh: float, vertical: bool):
    """Where a label of ``hw`` x ``hh`` may go on a run of ``span``, best first.

    Yields ``(x, y, off)``: the anchor, and the perpendicular stand-off from the
    run that put it there, which is what the outermost band is counted in.
    Whether the label needs a leader is a separate question and not this one:
    see :func:`_along`.

    On the pipe only while the run can still show clear line at each end; then
    beside it (above a horizontal run, left of a vertical one), then the far
    side, then further out. Each of those is slid along the run in turn, so the
    label leaves the pipe before it leaves the neighbourhood of its own line.

    Above and left is the side ISO 15519-1 §7.2.5 asks for. On the pipe comes
    first anyway, since a dozen-character line number costs the sheet more room
    beside the run than on it, and §7.2.5 words its preference as a ``should``.

    On the pipe the label has to stay within the run, clearance and all. Beside
    it, it erases nothing, so it may slide until its near edge reaches the run's
    end: far enough to get out from under a symbol the run butts into, and no
    further, since past that it stops reading as this line's number.
    """
    if span >= hw + 2 * _LABEL_CLEAR:
        for x, y in _slide(cx, cy, (span - hw) / 2 - _LABEL_CLEAR, vertical):
            yield x, y, 0.0
    for out in range(_LABEL_BANDS):
        off = hh / 2 + _LABEL_GAP + out * hh
        for side in (-1.0, 1.0):
            ax = cx + side * off if vertical else cx
            ay = cy if vertical else cy + side * off
            for x, y in _slide(ax, ay, (span + hw) / 2, vertical):
                yield x, y, off


# --- the leader that stands in for adjacency ----------------------------------
# ISO 15519-1 §6.4, on how a leader ends: "Leader lines shall terminate: with a
# dot if it terminates within an object; with an arrowhead if it ends on the
# outline of an object or a connection; with an oblique stroke if it ends at
# several parallel connections." A line number's leader ends on a connection, so
# it wears an arrowhead, and Figure 4 c) -- the case drawn for exactly that --
# draws the leader itself *oblique*, running down onto a plain horizontal
# connecting line with the text carried at its upper end.
#
# Oblique is not an oversight there and is not a licence taken here. §12.1 holds
# "the connecting lines representing pipelines, mechanical links, conductors,
# functional connections, etc." to horizontal or vertical, and a leader is none
# of those: it carries no fluid, no signal and no mechanical link, and says only
# *this text belongs to that line*. The slope is what keeps it from being read
# as a connection at all, which is why tests/test_route_invariants.py sweeps
# streams and impulse lines and not this.
#
# The arrowhead is drawn on a P&ID too, where no process line carries one. By
# the standard that is not an inconsistency: a flow arrowhead is a statement
# about direction, a P&ID reads direction off the line list instead, and this
# one is §6.4's *termination symbol*, which says only where the leader ends.
#
# By this package's own corpus it is thinner than that, and worth being honest
# about. A leader's head is a solid filled triangle on a fine line and pandid's
# flow marker is a solid filled triangle on a process line: same shape, 1,8
# times the size, and nothing else -- not hollow against filled, not dashed
# against solid -- telling them apart. ``11_ethanol_pid`` carries no flow marker
# at all, so nothing on that sheet teaches a reader which of the two a triangle
# is, while 04 and 07 have taught them that a triangle on a line means flow. The
# clause permits the head; it does not make the head self-explaining. What
# follows from that is not a different terminator, which §6.4 does not offer,
# but drawing fewer leaders: §7.2.5 wants the number written along its line and
# treats the leader as what to do when that is impossible, so :func:`_along` is
# where the cost of this ambiguity is actually paid down.

# The head is half the sheet's flow arrowhead, because a leader is drawn at half
# the weight of a process line: §6.4 hands the leader itself to ISO 128-22,
# where it is a narrow line, and a terminator heavier than the line it ends
# would read as the weightier of the two. Same proportions as the flow head,
# whose marker is 12 long and 12 wide, so the two are one drawing at two sizes
# rather than two different arrowheads.
_LEADER_HEAD = ARROWHEAD * _SIGNAL_STROKE / _PROCESS_STROKE


def _crosses(start, end, region) -> bool:
    """Does the segment *start* -> *end* pass through the rectangle *region*?

    Liang-Barsky, and strict at the ends for the same reason :func:`_meets` is:
    a leader that grazes the edge of a box is not cutting through it, and the
    padding a line already carries is what keeps ink off it.
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
    """How many of *occupied* a leader would cut through, counted to *limit*.

    A leader is new ink on a sheet that was already too crowded to write the
    number beside its line, so it has to be scored the way the label itself is:
    one that runs through the vessel the label stepped around has moved the
    problem rather than solved it.
    """
    n = 0
    for p in occupied:
        if _crosses(leader[0], leader[1], p):
            n += 1
            if n >= limit:
                break
    return n


def _near_segment(p, a, b, tol: float = 0.5) -> bool:
    """Does *p* sit on the segment ``a``-``b``, to within *tol*?"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    if not span:
        return math.hypot(p[0] - a[0], p[1] - a[1]) <= tol
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy)) <= tol


def _leader(box, seg, occupied, keep_out: float = 0.0) -> "tuple[tuple, int]":
    """How a label's halo at *box* is joined to the run *seg* names.

    Returns ``((start, end), crossings)``: the leader, the end being the point
    on the run the arrowhead lands on, and how many of *occupied* it cuts
    through.

    Every candidate leaves the halo's **near face** and lands 45 degrees away
    along the run -- the slope Figure 4 draws. Leaving from the label rather
    than aiming at a fixed point on the run is what makes a leader *move* when
    the search slides the label along; pinned to the run instead, every anchor
    in a band produced the same leader and a congested gap had exactly one
    answer.

    The tail is swept along that face and scored, in this order:

    **What it cuts**, first, for the reason the halo dodges anything at all.
    This is where the old three fixed starts -- the middle and the two corners
    -- did their real work: the strip of paper directly between a label and its
    run is often the congestion that pushed the label out, a leader dropping
    out of the middle of the face is aimed straight into it, and leaving from
    nearer an end takes it around. The sweep does that where it is needed and
    nothing where it is not, instead of always offering exactly the corners.

    **How near 45 degrees it lands**, second. The slope Figure 4 c) draws is
    what makes the mark read as a pointer rather than as a branch off the line,
    and it is the same slope on every leader on the sheet, so a reader learns
    the mark once.

    **How near the middle of the face it starts**, last, and this is the tie the
    old fixed starts kept losing. A halo is measured at 6,2 per character plus
    padding, which over-measures a string as hyphen-heavy as a line number by
    the better part of a character at each end, so its corners are blank paper.
    ``AE-304-150-80-SS`` on ``11_ethanol_pid`` was led from the top corner of a
    rotated halo, which put the tail past the end of the last letter with a gap
    between the two, and a mark that does not touch the words does not attach
    them to anything. So the sweep is inset from the corners by half the halo's
    thickness -- about one character at this size -- and, all else equal, a tail
    nearer the middle of the words wins.

    The landing point is kept off the ends of the run, because a run's ends are
    where it meets the equipment it serves and a head landing there points at
    the vessel as readily as at the pipe -- which is the very reading this whole
    clause exists to prevent. The clearance is ``_LABEL_CLEAR``, the length of
    run this module already requires to be showing past a mark for the run to
    still read as one line, or a third of the run where the run is too short to
    give that much. Where that clamp bites the leader comes in shallower than 45
    degrees; it stays oblique, which is all the slope has to be, and the second
    key above is what spends the freedom the sweep has on getting back towards
    45 rather than on nothing.

    ``keep_out`` extends that clearance by whatever the run's ends are *marked*
    with, and is the same clause rather than a new one: the clearance exists so
    a head does not land where the run meets what it serves, and on a flanged
    sheet the joint is drawn, so landing on it points at the joint exactly as
    landing at the end points at the vessel. It is measured off the run's ends
    before the inset, which is what lets a short spool between two vessels --
    ``AE-304-150-80-SS`` on ``11_ethanol_pid``, thirty units with a flange pair
    at each end -- put the head in the clear middle instead of on the upper
    pair, which is where it went when the marks were ink nothing could see.
    """
    (sx1, sy1), (sx2, sy2) = seg
    vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
    # Everything below is in the run's own frame -- *u* along it, *v* across --
    # so one piece of arithmetic serves a horizontal run and a vertical one.
    lo, hi = ((min(sy1, sy2), max(sy1, sy2)) if vertical
              else (min(sx1, sx2), max(sx1, sx2)))
    at = (sx1 + sx2) / 2 if vertical else (sy1 + sy2) / 2
    u0, u1 = (box[1], box[3]) if vertical else (box[0], box[2])
    v0, v1 = (box[0], box[2]) if vertical else (box[1], box[3])
    v = v0 if abs(v0 - at) < abs(v1 - at) else v1
    gap = abs(v - at)
    # Only where the run can spare it: a mark on a run too short to hold both
    # its marks and a landing has to be landed near anyway, and a band inverted
    # by its own clearance would put the head off the run altogether.
    if keep_out and hi - lo > 3 * keep_out:
        lo, hi = lo + keep_out, hi - keep_out
    inset = min(_LABEL_CLEAR, (hi - lo) / 3)
    near, far = lo + inset, hi - inset

    def route(s: float):
        """The leader leaving the near face at *s*, landing 45 degrees along.

        Both directions along the run are offered and the one that lands
        *furthest* from ``s`` wins, which is the same thing as the one nearest
        45 degrees: an unclamped landing is exactly ``gap`` away, and clamping
        to the run can only bring it closer in.
        """
        u = max((min(max(s + d * gap, near), far) for d in (1.0, -1.0)),
                key=lambda c: abs(c - s))
        return ((v, s), (at, u)) if vertical else ((s, v), (u, at))

    # The face, inset at each end so the tail lands on the lettering rather than
    # on the halo's padding, and never inset past a quarter of a short one.
    ends = min(abs(v1 - v0) / 2, (u1 - u0) / 4)
    first, last, mid = u0 + ends, u1 - ends, (u0 + u1) / 2
    starts = [first + k * _LABEL_STEP
              for k in range(int((last - first) // _LABEL_STEP) + 1)] + [last]

    def scored(s: float, limit: int):
        """The leader from *s*, and the three keys it is chosen on."""
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


def stream_polyline(s) -> "list[tuple[float, float]]":
    """Every point one stream's line is drawn through, both ends included.

    The route's waypoints are the middle of the answer and not the whole of it:
    a route runs between two *anchors* on the units' bounding boxes, and what
    gets drawn runs between the two nozzles those anchors stand for, which is
    where a reader sees the pipe meet the equipment. So the ends come from
    :func:`~pandid.portgeom.port_point` and the waypoints go in between.

    Collinear middle points are dropped. The router emits a point per grid step
    it turned at, and three points on one straight length are one segment drawn
    in three pieces: harmless as ink, but not as *structure* -- every consumer
    downstream of this asks how long a segment is (the stream label picks the
    longest to write itself in, and a draw.io edge carries one waypoint per real
    turn), and a run chopped into pieces answers wrongly.

    Lifted out of the SVG renderer so the draw.io exporter draws the same line
    rather than a second opinion about it. Two derivations of one polyline is
    exactly the drift that would leave an exported sheet a few pixels off the
    rendered one with nothing to say which was right.
    """
    from pandid.portgeom import port_point

    src_u, dst_u = s.source.owner, s.dest.owner
    start = port_point(src_u, src_u.frame, s.source.name)
    end = port_point(dst_u, dst_u.frame, s.dest.name)
    points = [start] + list(s.route.waypoints if s.route and s.route.waypoints else []) + [end]

    simplified = [points[0]]
    for i in range(1, len(points) - 1):
        p_prev, p_curr, p_next = simplified[-1], points[i], points[i + 1]
        if (p_prev[0] == p_curr[0] == p_next[0]) or (p_prev[1] == p_curr[1] == p_next[1]):
            continue
        simplified.append(p_curr)
    simplified.append(points[-1])
    return simplified


#: The size a line number is lettered at, and the halo it is written on: the
#: string's estimated width plus a gutter, by a fixed depth. Held at module
#: scope because the draw.io exporter sizes the same label with them.
NUMBER_TYPE = 10
_HALO_CHAR, _HALO_PAD, _HALO_DEEP = 6.2, 6.0, 13.0


class StreamNumber(NamedTuple):
    """One line number, and where the sheet decided to write it.

    ``seg`` is the segment of the run the number names -- its longest, which is
    the piece a reader has the most line to attach a caption to. ``x``/``y`` is
    the point the string is *centred* on, ``vertical`` says it is turned a
    quarter to read bottom to top, ``box`` is the opaque halo it is written on,
    and ``leader`` is the pair of points a leader runs between where the search
    could not find paper alongside the run (``None`` where it could).
    """
    name: str
    color: str
    seg: tuple
    x: float
    y: float
    vertical: bool
    box: tuple
    leader: "tuple | None"


def stream_numbers(fs, placed: list,
                   joints: "str | None" = None) -> "list[StreamNumber]":
    """Where every line number on the sheet goes.

    Lifted out of :meth:`SvgRenderer._draw_streams` for the reason
    :func:`stream_polyline` and :func:`boundary_flag` were, and with more at
    stake than either: this is a *search*, not a formula, so a second
    implementation of it would not merely drift, it would answer differently on
    the first crowded corridor. The draw.io exporter had no way to ask and
    centred each number on its edge instead, which put ``CWS-311-150-40-CS``
    across a hand valve, ``FB-301-200-160-SS`` across an off-page flag's own
    lettering, and ``FB-310-300-160-SS`` likewise -- three numbers the sheet
    places clear of all three.

    ``placed`` is the list of opaque plates already on the sheet, and it is
    **appended to**: each number's halo, and each leader's box, is seeded as
    occupied so the next number does not delete it. The caller passes the
    equipment tags it has already laid down, and gets back the whole set --
    which is exactly what :meth:`SvgRenderer._draw_streams` hands to the
    debugging overlay. An exporter with no equipment-tag pass of its own passes
    an empty list and gets a placement that dodges every symbol and every line
    but may still land under a tag; that is the one thing about this the two
    backends do not share, and it is a difference of a seed rather than of a
    method.

    Everything else the search needs is derived here from the flowsheet, so the
    two callers cannot disagree about it: :func:`_ink` for the lines, and
    :func:`~pandid.portgeom.unit_box` through :func:`_obstacle` for the symbols.
    """
    from pandid.portgeom import unit_box

    ink = _ink(fs)
    symbols: list[tuple[float, float, float, float]] = [
        _obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None
    ]

    # A flange mark is a symbol on a run, so it goes in with the symbols: the
    # search dodges it exactly as it dodges a valve body, and both the halo and
    # the leader are scored against it. It has to be here rather than nowhere,
    # because the mark is drawn hard against a nozzle and a leader wants the
    # clear middle of a segment -- on the short spool between a condenser and
    # the drum beneath it, "the clear middle" was the two units between the two
    # flanges, and the number's leader landed on one of them. See
    # :func:`flange_boxes`, which the equipment-tag pass now asks as well.
    symbols += [_obstacle(b) for b in flange_boxes(fs, joints)]
    # A letter code written outside a balloon is a mark on the sheet the same
    # way: it is placed before either label pass runs (see
    # :func:`quadrant_labels`), so both can be told where it went.
    symbols += [b for b in map(_unit_label_box, quadrant_labels(fs)) if b is not None]

    # A number names a *run*, and a run survives the valves and fittings in it:
    # renumber_streams() gives every segment of one the same name and the sheet
    # writes it once, on the longest piece.
    label_items: list = []
    labeled_names: set = set()
    for s in fs.streams:
        if s.kind in _SIGNAL_KINDS or s.name in labeled_names:
            continue
        points = stream_polyline(s)
        longest_seg, max_len = None, -1.0
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            seg = abs(x2 - x1) + abs(y2 - y1)
            if seg > max_len:
                max_len, longest_seg = seg, ((x1, y1), (x2, y2))
        if not longest_seg:
            continue
        labeled_names.add(s.name)
        # How much of the segment its own flange marks take, if it carries any:
        # the mark's standoff plus its half-width, which is where the near bar
        # ends. Nought on a run whose longest piece is in the middle of it,
        # since the marks are at the nozzles and nowhere else.
        (mx1, my1), (mx2, my2) = longest_seg
        keep = FLANGE_STANDOFF + FLANGE_GAP / 2 if any(
            _near_segment((m.x, m.y), (mx1, my1), (mx2, my2))
            for m in flange_marks(s, points, resolve_connections(s, joints))
        ) else 0.0
        label_items.append((longest_seg, s.name, s.color or "black", keep))

    out: list[StreamNumber] = []
    for seg, name, color, keep in label_items:
        (sx1, sy1), (sx2, sy2) = seg
        hw, hh = len(name) * _HALO_CHAR + _HALO_PAD, _HALO_DEEP
        cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
        vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
        span = abs(sy2 - sy1) if vertical else abs(sx2 - sx1)
        # Turned to follow the run, the halo measures hw along it, hh across.
        bw, bh = (hh, hw) if vertical else (hw, hh)

        # Everything the anchors below can reach: along the run as far as
        # _label_anchors will slide the label, and across it as far as the
        # outermost band beside the pipe. Seeds outside it can be dropped
        # before the search rather than re-tested at every step of it.
        along = (span + hw) / 2 + max(bw, bh) / 2
        across = hh / 2 + _LABEL_GAP + _LABEL_BANDS * hh + max(bw, bh) / 2
        rx, ry = (across, along) if vertical else (along, across)
        window = (cx - rx, cy - ry, cx + rx, cy + ry)

        axis, at = ("v", (sx1 + sx2) / 2) if vertical else ("h", (sy1 + sy2) / 2)
        # How far **the run** goes, which is not how far the labelled segment
        # goes: an in-line valve splits a straight length of pipe into three
        # drawn pieces, and a reader sees one line. It is the same set this
        # search already treats as the label's own -- everything collinear
        # with the segment -- and it is what :func:`_along` measures against.
        # Taken over all the ink and not just the ink inside the window,
        # since a run that leaves the window is a run the label cannot
        # overrun on that side.
        run_lo = min(sy1, sy2) if vertical else min(sx1, sx2)
        run_hi = max(sy1, sy2) if vertical else max(sx1, sx2)
        for line in ink:
            if line.axis == axis and abs(line.at - at) < 0.5:
                run_lo = min(run_lo, line.y0 if vertical else line.x0)
                run_hi = max(run_hi, line.y1 if vertical else line.x1)

        near_symbols = [p for p in symbols if _meets(p, window)]
        occupied = [p for p in placed if _meets(p, window)]
        occupied += [line.box for line in ink
                     if not (line.axis == axis and abs(line.at - at) < 0.5)
                     and _meets(line.box, window)]
        # A leader is ink like any other and has to dodge the same things
        # the halo does, symbols included, so it is scored against the lot.
        everything = near_symbols + occupied

        # Best first, and the first spot that covers nothing wins outright.
        # Where nothing is clear -- a dozen-character line number in a
        # crowded corridor -- the least damaging spot wins instead, and a tie
        # keeps the earlier anchor. Since the anchors that sit *on* the pipe
        # come first, that makes the label's own line the last resort, which
        # is the right one: breaking the run you are naming is a convention a
        # reader knows, and breaking the run beside it is a lie about that
        # line. The old fallback was whichever anchor happened to be first,
        # taken however much of the sheet it deleted.
        #
        # An anchor the run does not run along is no longer this line's
        # number on its own terms, so it carries a leader instead
        # (ISO 15519-1 §7.2.5, and :func:`_along` for where the line falls).
        # The leader's own crossings are the last part of the score: new ink
        # drawn through the vessel the label stepped around is not an
        # improvement on the label sitting against that vessel, and the halo
        # machinery this search is built on exists precisely so a label does
        # not delete somebody else's line. A clear spot alongside the run
        # still wins outright, since it scores all zeros and the anchors are
        # generated near-first.
        clear = (0, 0, 0)
        spot: "tuple[float, float] | None" = None
        damage: "tuple[int, int, int] | None" = None
        leader: "tuple | None" = None
        for ux, uy, _off in _label_anchors(cx, cy, span, hw, hh, vertical):
            box = (ux - bw / 2, uy - bh / 2, ux + bw / 2, uy + bh / 2)
            hits = _covering(box, occupied, near_symbols,
                             None if damage is None else damage[:2])
            if damage is not None and hits > damage[:2]:
                continue
            lead, cut = ((None, 0) if _along(box, vertical, run_lo, run_hi)
                         else _leader(box, seg, everything, keep))
            cost = (*hits, cut)
            if damage is None or cost < damage:
                spot, damage, leader = (ux, uy), cost, lead
                if cost == clear:
                    break
        # `_label_anchors` always offers at least the innermost band either side
        # of the run, so there is always a spot: the search chooses between
        # anchors, it never fails to find one.
        assert spot is not None
        tx, ty = spot
        halo = (tx - bw / 2, ty - bh / 2, tx + bw / 2, ty + bh / 2)
        placed.append(halo)
        if leader is not None:
            # Seeded as occupied so the next label's halo cannot delete it. The
            # seed is the leader's bounding box rather than the stroke, which is
            # generous for a sloping line -- but a leader is rare, and the
            # alternative is a halo landing on the one mark that says which line
            # this number belongs to.
            (ax0, ay0), (ax1, ay1) = leader
            placed.append((min(ax0, ax1), min(ay0, ay1),
                           max(ax0, ax1), max(ay0, ay1)))
        out.append(StreamNumber(name, color, seg, tx, ty, vertical, halo, leader))
    return out


#: How deep the point of an off-page flag is cut back from the end of its
#: rectangle, and how far the pennant is inset inside the flag's box, top and
#: bottom -- less where an off-page reference has to be written under the tag,
#: since two lines need a taller flag than one.
FLAG_POINT = 15
_FLAG_INSET, _FLAG_INSET_REF = 15, 12


class Pennant(NamedTuple):
    """The off-page flag a Feed or a Product is drawn as.

    ``box`` is the rectangle the pennant occupies, ``point`` how deep its point
    is cut back from the end, and ``east`` which end that point is on.
    """
    box: tuple[float, float, float, float]
    point: float
    east: bool


def boundary_flag(u, frame) -> Pennant:
    """The pennant an off-page flag is drawn as.

    A rectangle with one end drawn to a point at mid-height, pointing the way
    the stream runs: east out of a Feed, east into a Product, and west for
    either where the placement mirrors it. The point is where the line meets
    the flag on a Feed and the blunt end is where it meets a Product, which is
    why both point the same way.

    Two things about the rectangle are worth having written down once rather
    than measured twice. It spans the *whole* of :func:`~pandid.portgeom.unit_box`
    horizontally -- a Feed's box extends left from its port, which is the one
    place in the library where that is true -- and it is inset top and bottom,
    so the flag is 26 units of a 50-unit box and not the box. An exporter that
    took the box for the drawing would draw a flag twice the height the sheet
    rules it at.

    Nothing here reads ``header``: a utility header flag is the same pennant as
    an off-page reference, drawn at each tap of the service, and what tells the
    two apart on a sheet is the label rather than the outline.

    Shared with the draw.io exporter, for the reason :func:`stream_polyline` is.

    The horizontal extent is :func:`~pandid.portgeom.unit_box`'s and is written
    out again rather than read from it, for one reason and no other: this
    function's arithmetic is what the sheet's polygon is *formatted from*, and
    ``unit_box``'s ``50.0`` would write a whole-number coordinate as ``100.0``
    where the sheet has always written ``100``. The two agree on the number,
    which ``test_a_flag_is_drawn_across_its_own_box`` pins over every placement.
    """
    inset = _FLAG_INSET_REF if (getattr(u, "reference", "") or "") else _FLAG_INSET
    if u.kind == "feed" and not frame.mirrored:
        x0, x1 = frame.x + 50 - frame.w, frame.x + 50
    else:
        x0, x1 = frame.x, frame.x + frame.w
    return Pennant((x0, frame.y + inset, x1, frame.y + (50 - inset)),
                   FLAG_POINT, not frame.mirrored)


#: Where the two strokes of a pneumatic double cross-hatch sit *along* the run,
#: relative to the mark's own point, and how far each reaches across it. The
#: stroke leans: 6 units along by 10 across, which is what makes it a slash
#: rather than a tick and what tells a pneumatic line from anything drawn with a
#: perpendicular mark.
HATCH_ALONG = (-2.5, 1.5)
HATCH_ARM = (3.0, 5.0)


class Hatch(NamedTuple):
    """One double cross-hatch on a pneumatic line.

    ``along`` is how far down the line the mark sits, by the same Euclidean arc
    length ``mxGraphView.getPoint`` measures a relative child of an edge by. It
    is here rather than being recovered from ``(x, y)`` because a point cannot
    always be found again: an orthogonal route that doubles back passes through
    the same neighbourhood twice, and a mark on the second pass matched against
    the first would be hung on the wrong part of the line.
    """
    x: float
    y: float
    horizontal: bool
    along: float


def pneumatic_marks(points) -> "list[Hatch]":
    """Every double cross-hatch a pneumatic line is marked with.

    ISA-5.1 draws a pneumatic signal as a *solid* line marked with double
    cross-hatches, so the hatch is the only thing telling it apart from process
    piping. One mark per 45px alone leaves a short run (a transducer to the
    actuator right beneath it) with none at all, reading as plain pipe. Any
    segment with room for a mark gets at least one; longer segments keep the
    45px spacing.

    Shared with the draw.io exporter, which has no way to stroke a mark across a
    line and hangs one on the edge instead, at these points. A second rule for
    where the hatches fall would put the export's marks somewhere the sheet's
    are not, which for a mark that is the *whole* of what identifies the line is
    worse than a mark in a slightly different style.
    """
    out: list[Hatch] = []
    walked = 0.0
    for i in range(len(points) - 1):
        (px1, py1), (px2, py2) = points[i], points[i + 1]
        # Manhattan for the spacing rule, which is what the sheet has always
        # counted marks by and what keeps this byte for byte the drawing it was;
        # Euclidean for the distance, which is the one mxGraph measures a mark's
        # place on an edge in. The two are the same number on an orthogonal
        # segment and differ only on the sloping leg a nozzle sometimes needs.
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


#: What a drawing may say about the joints where its lines meet what they serve.
#: A tuple rather than a bool for the reason ``Valve.NORMAL_POSITIONS`` is one:
#: the joint's make-up is an enumeration the plant has more entries in
#: (threaded, socket-welded, a spec break) and not a switch with two settings.
#:
#: ``"none"`` is not ``"welded"``. It is the drawing declining to say, which is
#: what an unmarked line has always meant and the only honest default: a library
#: that marked every joint flanged would be making a claim about piping nobody
#: gave it.
#:
#: The other two differ in exactly one thing, and it is the thing the author is
#: choosing between: whether the **bodies standing in the run** -- the valves and
#: the in-line fittings -- are bolted in or welded in.
#:
#: * ``"flanged"`` marks every joint the sheet can mark, valves included.
#: * ``"flanged-at-nozzles"`` marks only where a line meets an equipment nozzle
#:   and leaves the bodies in the run unmarked.
#:
#: The broader one takes the plain word deliberately. ``connections="flanged"``
#: has one reading to somebody who has not read this file -- *the connections on
#: this sheet are flanged, all of them* -- and an API whose plain word means the
#: narrower thing teaches that reading is wrong. So the narrower setting says
#: what it restricts, in its own name, and nobody has to be told. See
#: :func:`flanged_joint` for what each marks, and for why no standard settles it.
CONNECTIONS = ("none", "flanged", "flanged-at-nozzles")

#: The in-line kinds that are *bodies bolted into* a run rather than pipe welded
#: along it, and so the ones ``"flanged"`` marks. A strict subset of
#: :data:`~pandid.flowsheet.INLINE_KINDS`, which is the wider set of things that
#: interrupt a line without ending it; the two are not the same question and
#: ``test_render_api`` holds the subset relation so they cannot drift into being
#: treated as though they were.
#:
#: A valve, a strainer, a sight glass or an orifice plate is a body you break the
#: line to pull, and it is bolted between a pair of faces *so that* you can. A
#: concentric reducer and a tee are butt-welded fittings: they are as much "pipe"
#: as the pipe either side, and a sheet that flanged them would be describing a
#: plant almost nobody builds. So the mark follows what has to come out, which is
#: also the only reading of it that tells a reader something they did not already
#: know from the symbol.
_INLINE_BODIES = frozenset({"valve", "fitting"})

#: The flanged-connection mark, in the proportions the vendored draw.io stencil
#: draws it in: ``('fitting', 'flange')`` in :mod:`._vendored_symbols` is two
#: bars 5.0 apart and 12.5 long, at the weight of the pipe. Held to those exact
#: numbers so the sheet and an export that places the stencil are one mark
#: rather than two drawings of one, and so the same pair is recognisable whether
#: an author drew it as a convention here or pinned a ``Fitting`` unit there.
#:
#: Against P&ID_301 the proportions check out: its ticks are 8.5pt long, 2.13pt
#: apart, at a ~0.85pt pen. The gap is 1.5 pen widths there and 1.5 pen widths
#: here (5.0 apart less a 2.0 stroke), which is what makes the two bars read as
#: one mark instead of two ticks that happen to be near each other.
FLANGE_TICK = 12.5
FLANGE_GAP = 5.0

#: How far the pair's *centre* stands off the nozzle, along the run. Enough that
#: the near bar clears the outline it is drawn against rather than sitting on
#: it: the mark says the joint is outside the equipment, and a bar overlapping
#: the shell reads as part of the shell.
FLANGE_STANDOFF = 5.0


class Flange(NamedTuple):
    """One flanged-connection mark on a stream.

    ``angle`` is the direction of the *run* at the mark in degrees, not the
    direction the bars are stroked in; the bars are drawn across it. It is
    carried rather than recovered because the draw.io exporter cannot re-derive
    it -- mxGraph has no auto-orientation for a shape on an edge -- and two
    derivations of one angle is the drift :func:`pneumatic_marks` exists to
    avoid. ``along`` is arc length from the source end, for the same reason it
    is on :class:`Hatch`.
    """
    x: float
    y: float
    angle: float
    along: float


def _draws_its_own_flange(u) -> bool:
    """Is this body's own symbol already the flanged connection?

    ``Fitting``'s *default* variant is the flanged connection, and ``"flange"``
    is the same artwork under its own name, so an author who pins one has drawn
    the joint explicitly. Marking it would put three flange pairs where one was
    asked for. Asked of the registry rather than matched against a list of
    variant names, so re-pointing the artwork cannot leave this checking for a
    symbol nothing draws any more.
    """
    from pandid.render.symbols import default_registry

    own = default_registry.get(u.kind, getattr(u, "variant", "default"))
    return (own.drawio_shape is not None
            and own.drawio_shape == default_registry.get("fitting", "flange").drawio_shape)


def flanged_joint(port, want: str) -> bool:
    """Does a ``want`` joint put a mark at this end of a stream?

    ``want`` is one of :data:`CONNECTIONS` and has already been resolved against
    the sheet by :func:`resolve_connections`, so all that is left is whether this
    particular end is the kind of thing that end takes a mark.

    **No standard on disk settles this, and this docstring is not going to
    pretend one does.** The word "flange" appears nowhere in either part of the
    reference the rest of this module cites -- zero occurrences in
    ISO 15519-1:2010 and zero in ISO 15519-2:2015. ISO 15519-1 §12.4 is headed
    *Joints* and is not about pipe joints at all: it governs the joining of
    *connecting lines* on the paper -- "Joining shall be indicated with symbol
    501: Joint of connections, a dot" -- which is the T-junction dot this library
    already draws for a tee. ISO 15519-2 §6.3.1 hands symbols off to the
    ISO 14617 series, which is where the flanged-connection symbol lives, but
    14617 is a registry of symbols rather than a rule about where to put them and
    it is not in ``professional_examples/``, so nothing is quoted from it here.

    So: **no clause requires a flange at a valve and no clause forbids one.**
    What follows is a drafting choice, attributed to nothing but ordinary
    practice, and it is offered as a choice for that reason rather than settled
    on the author's behalf.

    Two kinds of end are not joints under either setting, and these two really
    are rules rather than preferences:

    * a boundary flag, because a ``Feed`` or a ``Product`` is a reference to
      another sheet and a reference has no flange faces;
    * an instrument, because what a balloon terminates is a tap or a signal, and
      :func:`flange_marks` has already dropped the signal lines.

    Everything else turns on ``want``:

    ``"flanged"``
        Every equipment nozzle, **and both sides of every body standing in the
        run** (:data:`_INLINE_BODIES`). A valve in flanged service is flanged
        both sides -- that is how it is got out of the line -- so a sheet that
        says its connections are flanged and then draws a valve welded in is
        saying two things. Reducers and tees stay unmarked: they are welded
        fittings, not bodies. See :data:`_INLINE_BODIES`.

    ``"flanged-at-nozzles"``
        The nozzles only, which is what ``P&ID_301.pdf`` draws. Every piped
        branch off a shell carries the mark there -- all four of D-301's
        nozzles, both of RB-301's level-bridle taps, each of HX-301's four,
        T-301's ``-160-SS`` feed and its pressure taps -- and nothing else on
        the sheet does: not the gate valves either side of CV-305, not the
        drains, not the boundary flags. It reads correctly, because on that
        sheet the mark means *this branch is bolted to the vessel* and says
        nothing about the valve downstream of it. It is a real drawing office's
        convention and it stays reachable; it is simply not the only one, and
        the reference sheet is evidence of what one office drew rather than of
        what a standard demands.
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
    """Every flanged-connection mark one stream carries, in drawing order.

    ``ends`` is the resolved ``(source, dest)`` pair, each a member of
    :data:`CONNECTIONS`; resolving it against the sheet is
    :func:`resolve_connections`' job, so this asks only whether the geometry and
    the flowsheet agree that a mark belongs.

    A signal line never carries one. ISA-5.1 draws a signal as a line to a
    balloon, and a flange is a fact about pipe: there is no joint to describe.

    Shared with the draw.io exporter for the reason :func:`pneumatic_marks` is:
    a mark placed by one rule on the sheet and a second rule in the export is
    two drawings, and this one lands hard against a vessel outline where a few
    units either way is the difference between a joint and a collision.
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

        # The mark stands off the nozzle *along the line*, which is the same
        # placement the arrowhead has and stated the same way: the run's own
        # direction at the end it terminates, taken from the last two points of
        # the polyline the pipe is drawn through.
        tip = points[-1] if at_dest else points[0]
        neighbour = points[-2] if at_dest else points[1]
        span = spans[-1] if at_dest else spans[0]

        # No room, no mark. The pair needs its standoff plus its own half-width
        # of straight run to sit on; a nozzle whose first segment is shorter
        # than that would take the mark round the turn beyond it, and a flange
        # drawn across a corner is worse than one the reader does not get.
        if span < FLANGE_STANDOFF + FLANGE_GAP / 2:
            continue

        ux, uy = (neighbour[0] - tip[0]) / span, (neighbour[1] - tip[1]) / span
        cx, cy = tip[0] + ux * FLANGE_STANDOFF, tip[1] + uy * FLANGE_STANDOFF
        along = total - FLANGE_STANDOFF if at_dest else FLANGE_STANDOFF
        out.append(Flange(cx, cy, math.degrees(math.atan2(uy, ux)), along))
    return out


def flange_boxes(fs, joints) -> "list[tuple[float, float, float, float]]":
    """Every flanged-connection mark on a sheet, as a box a label must keep off.

    **A flange mark is a graphical symbol standing on a run**, so every pass that
    places opaque lettering has to rank it with the symbols and not with the
    pipe. The distinction is :func:`_erases`': a halo over a length of pipe is a
    gap the reader reads across, and a halo over a flange face is the sheet no
    longer saying the joint is bolted.

    ``joints`` is :func:`sheet_connections`' answer, and ``None`` -- a drawing
    that marks no joints -- gives an empty list, so a caller with nothing to
    dodge need not ask whether it has anything to dodge.

    One function rather than a list built at each pass, because there are now
    three of them and they were not agreeing. :func:`stream_numbers` grew the
    rule when a line number's leader landed on a flange on the spool under
    ``11_ethanol_pid``'s condenser; :meth:`SvgRenderer._draw_units` did not, and
    ``RB-301``'s tag went out with two units of a flange face on the reboiler's
    vapour riser cut out of it. The exporter's :func:`~pandid.render.drawio
    ._tag_pass` runs the same search and has to be handed the same ink or the
    two backends place one tag in two places.

    Square, and sized on the longer of the pair's two dimensions, because the
    mark's angle follows the run and a box that tracked the angle would be four
    numbers saying less than one. That is a little slack on the along-the-run
    axis, on a mark 12,5 across; a label wanting those two units is a label with
    somewhere better to be.

    Ungrown. The caller applies :func:`_obstacle`, for the reason given there.
    """
    half = max(FLANGE_TICK, FLANGE_GAP) / 2
    return [
        (m.x - half, m.y - half, m.x + half, m.y + half)
        for s in fs.streams
        for m in flange_marks(s, stream_polyline(s), resolve_connections(s, joints))
    ]


def _arrowhead(start, end) -> str:
    """Path data for the filled head that terminates a leader at *end*."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    bx, by = end[0] - ux * _LEADER_HEAD, end[1] - uy * _LEADER_HEAD
    px, py = -uy * _LEADER_HEAD / 2, ux * _LEADER_HEAD / 2
    return (f"M {end[0]:.1f},{end[1]:.1f} L {bx + px:.1f},{by + py:.1f} "
            f"L {bx - px:.1f},{by - py:.1f} Z")


def _unit_label_box(item) -> "tuple[float, float, float, float] | None":
    """Halo rect of an equipment tag. ``None`` for a ``center`` tag, which sits
    inside its own symbol and so is drawn without one."""
    lx, ly, anchor, baseline, lpos, text = item
    if lpos == "center":
        return None
    hw, hh = len(text) * 6.6 + 8, 15.0
    rx = lx - hw / 2 if anchor == "middle" else (lx - hw if anchor == "end" else lx)
    ry = ly - hh / 2 if baseline == "middle" else ly - hh + 3
    return (rx, ry, rx + hw, ry + hh)


def _num(v: float) -> str:
    """Format a coordinate without trailing zeros (100.0 -> '100')."""
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _xform_tag(rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Short id suffix naming a placement transform ('' for the identity)."""
    if not (rot or mirror_x or mirror_y):
        return ""
    return "_t" + (f"r{rot}" if rot else "") + ("x" if mirror_x else "") + ("y" if mirror_y else "")


def _placed_box(u) -> "tuple[float, float] | None":
    """The box a unit's artwork is drawn into, in the symbol's own attitude.

    A quarter turn swaps the box the drawing is laid into and then turns the
    result back onto the frame, so the artwork never sees the swap; every
    question about how a placement scales a symbol is asked in these terms.
    """
    f = getattr(u, "frame", None)
    if f is None:
        return None
    rot = int(getattr(f, "orientation", 0) or 0)
    return (f.h, f.w) if rot in (90, 270) else (f.w, f.h)


def _reshapes(sym, u) -> bool:
    """True when a unit's box is a different shape from its symbol's own.

    Which is the whole of what a placement can ask of the artwork beyond a plain
    resize: an explicit ``width``/``height`` is taken as the final box, so a unit
    left to size itself lands on the symbol's proportions exactly and one given
    both may land on any others. A quarter turn swaps the box, and swaps the
    symbol with it, so it never reshapes anything by itself.
    """
    box = _placed_box(u)
    if box is None:
        return False
    bw, bh = box
    # Cross-multiplied, so a zero dimension cannot divide. A box that matches is
    # copied from the symbol's own size and matches to the bit; the tolerance is
    # only there so arithmetic on a size the author computed cannot claim a
    # reshaping that is not one.
    return not math.isclose(sym.width * bh, sym.height * bw, rel_tol=1e-9)


# --- the pen a placement draws with ------------------------------------------
# A symbol's line weights are compensated once, at generation time:
# scripts/vendor_symbols.py bakes stroke_width = 2/sqrt(sx*sy) inside the scale
# group it wraps the artwork in -- the geometric mean, for the reason given at
# _NOMINAL below -- so a valve drawn under scale(0.25) carries an 8.0 and lands
# on the sheet's 2.0. That is right for exactly one box -- the symbol's own. A
# <use> resizes the <symbol>'s viewport, and a viewport scales the ink as
# readily as the geometry, so the same valve placed in a box twice its own
# draws at 4.0, and nothing scales it back. The compensation is therefore half
# an answer, and _pen_scale is the other half: divide the baked weight back out
# by whatever the placement multiplied it by, which is what makes a resized
# unit's <defs> entry per placed *size* rather than per (kind, variant).
#
# Dividing works while the placement scales both axes alike, and only then. A
# stroke is swept by a *circular* pen, and a viewport that scales the axes
# differently sweeps an elliptical one: under preserveAspectRatio="none" a
# vertical line comes out at sx and a horizontal one at sy, and no single
# stroke-width can undo a difference that depends on which way the element runs.
# _baked is what handles that case, and the comment above it is the argument for
# how.


def _placement_scale(sym, u) -> "tuple[float, float]":
    """What a unit's ``<use>`` box scales its symbol's artwork by, per axis."""
    box = _placed_box(u)
    if box is None or not (sym.width and sym.height):
        return (1.0, 1.0)
    return (box[0] / sym.width, box[1] / sym.height)


def _stretch_scale(sym, u) -> "tuple[float, float]":
    """What the ``<use>`` viewport would scale the artwork by, per axis.

    ``(1, 1)`` unless the placement actually reshapes a symbol that may be
    reshaped: everything else lands on a *uniform* scale (the symbol's own box,
    a plain resize, or the letterbox a non-stretchable symbol is centred in),
    and a uniform scale is the case the pen division below answers exactly.
    """
    if sym.stretchable and _reshapes(sym, u):
        return _placement_scale(sym, u)
    return (1.0, 1.0)


# Bounded rather than unbounded: the key is a whole artwork string and a placed
# size, so a long-running process drawing many differently-sized units would
# otherwise hold every one of them forever. Cached at all because _fold,
# _pen_scale, _size_tag and _sym_id each ask it, several times per unit.
@lru_cache(maxsize=2048)
def _uneven(svg: str, fx: float, fy: float) -> bool:
    """Would an *uneven* scale stand between this artwork's ink and the page?

    Two things can put one there and they multiply. The placement is one, and
    is what :func:`_stretch_scale` reports. The artwork's own groups are the
    other, and are easy to miss: ``scripts/vendor_symbols.py`` reproportions
    four stencil families to the box the library wants them in -- a plain vessel
    is drawn under ``scale(0.62, 0.5)`` -- so those four draw an elliptical pen
    *at their own size*, with no placement involved at all. It is why a
    separator on a sheet that resizes nothing still draws its shell walls at
    2.23 against its heads' 1.80.

    Magnitudes, so a mirror does not read as an unevenness: the derived
    expansion fittings are their reducer under ``scale(-1, 1)``, which turns the
    pen round and does not deform it.
    """
    return any(not math.isclose(ax, ay, rel_tol=1e-9)
               for ax, ay in _stroke_scales(svg, fx, fy))


def _stroke_scales(svg: str, fx: float, fy: float) -> "list[tuple[float, float]]":
    """The magnitude of the scale over every stroke in *svg*, at ``scale(fx, fy)``."""
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
    """The placement scale a definition takes into its own coordinates.

    ``(1, 1)`` -- the artwork is left in the symbol's own coordinates and the
    viewport does the scaling -- unless the viewport would scale the two axes
    differently, in which case there is nothing for it to do but rewrite the
    drawing at the placed size. See :func:`_baked`.
    """
    fx, fy = _stretch_scale(sym, u)
    return (fx, fy) if _uneven(sym.svg, fx, fy) else (1.0, 1.0)


def _pen_scale(sym, u) -> float:
    """The single factor a placement multiplies a symbol's line weights by.

    One factor and not two, because ``stroke-width`` is one number -- so this
    is only ever asked where the placement leaves a *uniform* scale over the
    artwork, and it is :func:`_fold` that guarantees it: a placement that would
    have left an uneven one has already been rewritten into the coordinates, at
    which point the viewport scales by exactly 1 and there is nothing to divide.

    What is left is the three ways a placement can resize a symbol evenly: not
    at all, a plain resize, and the letterbox a symbol that may not be stretched
    is centred in, which keeps its aspect at the smaller of the two scales.
    """
    if _fold(sym, u) != (1.0, 1.0):
        return 1.0
    kx, ky = _placement_scale(sym, u)
    if sym.stretchable and _reshapes(sym, u):
        # An uneven box over an artwork whose own wrapper is uneven the other
        # way: the two cancel and the pen comes out round after all. Rare, but
        # it is the case _uneven() declines to rewrite, so it has to be priced.
        return math.sqrt(kx * ky)
    return min(kx, ky)


def _size_tag(sym, u) -> str:
    """Id suffix naming the box a placement had its symbol drawn for.

    Empty for the great majority, which is the point: a unit left to size itself
    lands on its symbol's own box at a scale of exactly 1, and goes on sharing
    one definition with every other unit of its kind. Only a unit given a
    ``width``/``height`` of its own costs the sheet a second entry.
    """
    if (math.isclose(_pen_scale(sym, u), 1.0, rel_tol=1e-9)
            and _fold(sym, u) == (1.0, 1.0)):
        return ""
    box = _placed_box(u)
    assert box is not None  # a scale of anything but 1 came from a box
    return f"_s{_num(box[0])}x{_num(box[1])}"


# Written on the element in every symbol here, hand-drawn and vendored alike;
# nothing reaches a stroke through CSS, which is what lets this be a rewrite of
# the emitted string rather than a parse of it.
_STROKE_WIDTH = re.compile(r'stroke-width="([\d.]+)"')


def _at_pen_scale(svg: str, scale: float) -> str:
    """*svg* with every line weight in it divided by *scale*.

    Every weight and not only the 2.0 outline: a symbol's own fine detail -- a
    column's trays, an agitator, the location bar across a panel balloon -- is
    drawn at a deliberate fraction of the sheet weight, the placement swells all
    of them alike, and dividing all of them alike is what holds the ratio the
    symbol's author drew. Six significant figures because the number is read
    back as a weight and multiplied by the scale again on the way to the page.
    """
    if scale == 1.0:
        return svg
    return _STROKE_WIDTH.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


# --- baking an uneven scale into the drawing ---------------------------------
#
# ISO 15519-1:2010 §11.1.3, "Line width in graphical symbols", is a *shall*:
#
#     The normal line width of graphical symbols is 0,1 M, according to
#     ISO 81714-1. When the size of a symbol is changed, the line width shall be
#     unchanged.
#
# §11.1.2 immediately above permits the proportions themselves to be modified,
# so stretching a stencil to fill the box a unit was given is allowed; carrying
# the stroke along with it is what is not. And §6.2 closes the other door --
# "If two or more widths of line are used, the ratio between any two widths
# shall be at least 2:1" -- so an outline drawn 1,53 heavier one way than the
# other cannot be defended as a deliberate second weight either. Nothing between
# 1:1 and 2:1 is a weight; it is a mistake.
#
# An uneven viewport breaks that rule and no ``stroke-width`` can put it back,
# because the width the reader measures depends on the direction the line runs
# in and a stroke-width is one number. Exactly two constructs can, and the first
# is not available here:
#
# - ``vector-effect="non-scaling-stroke"`` says the thing directly, and browsers
#   honour it. The PDF/PNG backend does not: svglib has no notion of the
#   property (grep it), so it strokes the scaled geometry and drops the
#   attribute without a word, and ``export._reject_unsupported`` would not catch
#   it because an attribute it has never been taught is an attribute it does not
#   look for. Measured through ``export.to_png`` on a rule stretched 3:1, the
#   raster comes out byte-identical with the attribute and without it. Emitting
#   it would leave the .svg right and every exported sheet and every gallery PNG
#   wrong -- the worst of the three states to be in, because it looks fixed.
#
# - Rewriting the artwork's coordinates at the placed size, which is this. It
#   costs a definition per placed size, which the sheet was already paying (see
#   _size_tag), and it rewrites every number in the drawing to move nothing --
#   the objection to it, and not much of one against a *shall*, since it is
#   arithmetic that is exact except in the last bits of a float and leaves the
#   drawing with no uneven scale anywhere above a stroke. What the placement
#   asked for is then the whole of what the reader gets: the shape is stretched
#   and the pen is not.
#
# Baked and not merely straightened, note, because the same rewrite is what
# rounds out the *four vendored families* whose own wrapper group is uneven
# before any placement touches them (see _uneven). Those draw an elliptical pen
# at their natural size, which no amount of care at the <use> could have fixed.

def _nominal(width: float, gx: float, gy: float) -> float:
    """The weight *width* stands for on the sheet, drawn under ``scale(gx, gy)``.

    The generator divides by this same geometric mean when it bakes the weight
    in (``scripts/vendor_symbols.py``), so the two are inverses and a vendored
    outline reads back as exactly the 2.0 it was drawn to be. The mean rather
    than either axis because that is the factor that leaves the pen's *area*
    alone, and because for the 138 families whose wrapper is uniform the choice
    does not arise at all: ``sqrt(k*k)`` is ``k``.

    Magnitudes, since a mirror is a negative scale and turns no pen over.
    """
    return width * math.sqrt(abs(gx * gy))


# How each attribute answers to the map, by name. A *point* takes the scale and
# the translation; a *length* takes the scale alone, and unsigned, since a
# mirror turns the drawing over and no drawn width is negative. ``rx``/``ry``
# cover both the ellipse radii and a rect's corner rounding, which are the same
# lengths on the same axes; ``r`` is handled apart, since a circle scaled
# unevenly is not a circle any more.
_X_POINTS = {"x", "x1", "x2", "cx"}
_Y_POINTS = {"y", "y1", "y2", "cy"}
_X_LENGTHS = {"rx", "width"}
_Y_LENGTHS = {"ry", "height"}

_TAG = re.compile(r'<(/?)([A-Za-z][\w.-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*(/?)>')
_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')
# Absolute moves, lines and elliptical arcs, and how many numbers each takes.
# The symbol library emits these and nothing else; a relative or curve command
# would mean the library had changed under this file, and is refused rather than
# guessed at, for the reason export._reject_unsupported exists.
_PATH_ARITY = {"M": 2, "L": 2, "A": 7, "Z": 0, "z": 0}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _art(v: float) -> str:
    """A number in a symbol's own coordinates.

    Six decimals, which is four more than the sheet coordinates around it get
    (:func:`_num`) and about six more than any plate size can resolve: these are
    products of numbers the artwork already carried, and rounding them to the
    drawing's own precision would be a *geometry* change made in the course of
    fixing a *weight*. Fixed-point rather than significant figures so a small
    number never comes out in exponent notation, which SVG does accept and no
    other number in the file is written in.
    """
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0", "0") else s


def _affine(transform: str) -> "tuple[float, float, float, float]":
    """A symbol's own transform as the axis-aligned map it is: ``(sx, sy, tx, ty)``.

    The library writes two things and only two: the ``scale()`` a vendored
    stencil is reproportioned by, and the ``translate() scale(-1, 1)`` that
    turns a reducer end for end into an expansion. Both are diagonal, which is
    what lets the flattening below be arithmetic on each number in turn rather
    than a matrix applied to a point; a rotation or a skew is not, and is
    refused rather than silently flattened as though it were.
    """
    sx = sy = 1.0
    tx = ty = 0.0
    for op, args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", transform):
        v = [float(t) for t in args.replace(",", " ").split()]
        if op == "translate":
            # Composed on the right: each op is stated in the frame the ones
            # before it have already established.
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
    """The ellipse ``scale(ax, ay)`` makes of the one *rx*, *ry*, *rot* describe.

    An axis-aligned scale of a *tilted* ellipse is still an ellipse, but with
    different radii and a different tilt, so the arc's own parameters have to be
    recomputed rather than scaled. The ellipse is the image of the unit circle
    under ``R(rot) diag(rx, ry)``; the scale composes on the left, and the
    singular value decomposition of the product hands back the new radii and the
    new tilt directly. The sweep flag is untouched because both scales are
    positive, and the large-arc flag because neither depends on the frame.

    One family needs this -- the domed vessel, whose arcs are vendored at a tilt
    of 179,97 degrees -- and it needs it only when something stretches it.
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
    """One ``d`` attribute with the map *m* folded into its numbers."""
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
            # The large-arc flag is a property of the arc; the sweep flag is a
            # handedness, and a map that turns the plane over reverses it. The
            # two are written back as the integers they are, since a round trip
            # through float would print them "1.0" and the arc grammar takes a
            # single digit.
            sweep = int(nums[4]) if ax * ay > 0 else 1 - int(nums[4])
            out += [_art(rx), _art(ry), _art(rot), str(int(nums[3])), str(sweep),
                    _art(nums[5] * ax + ex), _art(nums[6] * ay + ey)]
        else:
            out += [_art(n * ax + ex if k % 2 == 0 else n * ay + ey)
                    for k, n in enumerate(nums)]
        i += 1 + arity
    return " ".join(out)


def _scaled_points(points: str, m: "tuple[float, float, float, float]") -> str:
    """One ``points`` attribute with the map *m* folded into its numbers."""
    ax, ay, ex, ey = m
    v = [float(t) for t in points.replace(",", " ").split()]
    return " ".join(
        f"{_art(v[i] * ax + ex)},{_art(v[i + 1] * ay + ey)}" for i in range(0, len(v), 2)
    )


def _scaled_element(name: str, attrs: "list[tuple[str, str]]",
                    m: "tuple[float, float, float, float]",
                    gx: float, gy: float, self_closing: str) -> str:
    """One drawn element, rewritten as it would look under the map *m*.

    *gx*, *gy* are the artwork's *own* share of that map's scale -- its groups,
    without the placement -- and are what the weight is read back through. The
    weight is therefore independent of the box: a symbol drawn to a 2.0 outline
    comes out declaring 2.0 whatever size it was placed at, which is
    ISO 15519-1 §11.1.3 stated in one line of code.
    """
    ax, ay, ex, ey = m
    src = dict(attrs)
    # A rect is stated as one corner and two lengths, and a map that turns an
    # axis over moves the corner it is stated from to the other end. Both ends
    # are mapped and the near one taken, so the rectangle covers the same ground
    # whichever way round the map is.
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
            # A glyph has no direction to be measured along, so an uneven scale
            # has no size to give it; the mean is the only answer, and it is the
            # answer that keeps the lettering a legal character height rather
            # than a stretched one (ISO 15519-1 §11.4.1).
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
    """*svg* redrawn at ``scale(fx, fy)``, with every scale group flattened out.

    The drawing is unchanged -- every point lands where the scale would have put
    it -- and what changes is that no scale is left above any stroke, so each
    ``stroke-width`` is the width the reader measures, in both directions, and
    is stated at the weight the symbol's author drew.

    A no-op wherever the scale over the ink is already even, which is the great
    majority: a uniform wrapper is harmless, the ``<use>`` viewport divides back
    out exactly (:func:`_at_pen_scale`), and leaving those alone keeps the
    ``<defs>`` a reader can still recognise as the vendored stencil.
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
            # A group that carried nothing but the transform has nothing left
            # to say once the transform is in the numbers, so it goes with it.
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
    """Keep a symbol's own lettering readable under a placement transform.

    Flipping a motor-operated valve to put its operator below the line is a
    statement about the *equipment*, not about the letter stamped on it: the
    box moves, the "M" inside it does not turn upside down. The transform on
    the ``<use>`` reaches the glyphs as readily as the strokes, so each text is
    wrapped in the inverse of that transform taken about its own anchor. The
    anchor still lands where the flip puts it; only the orientation is undone.
    """
    if not (rot or mirror_x or mirror_y):
        return svg

    def wrap(match: "re.Match[str]") -> str:
        tx, ty = float(match.group(1)), float(match.group(2))
        # Pivot on the glyph's visual centre, not on its anchor: `y` is a
        # *baseline*, and reflecting a baseline leaves the letter hanging off
        # the top of the box it is stamped in, since the glyph body sits above
        # the line rather than astride it. Cap height is ~0.7em, so the middle
        # of a capital is ~0.35em above the baseline. `x` needs no such
        # correction: these are all text-anchor="middle".
        size = re.search(r'font-size="(-?[\d.]+)"', match.group(0))
        cy = ty - 0.35 * float(size.group(1) if size else 12.0)
        # Undone in the reverse of the order the <use> applies them.
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
    """A placement's *reflection content*, as the pair of axis flips it is.

    The eight placements a unit may take are the symmetries of a square, and
    they split in two for this purpose. Four of them leave the axes alone --
    the identity, the two mirrors, and the **half turn, which is exactly the
    two mirrors composed** -- so every one of them is some combination of
    ``scale(-1, 1)`` and ``scale(1, -1)`` about the box's centre, which is what
    this returns. The other four swap the axes: the quarter turns, and each of
    them with a mirror on top.

    That split is the one a directional mark cares about, and it is the same
    split the arithmetic cares about, which is not a coincidence. An axis flip
    commutes with the per-axis scaling that fits a symbol into its box, so it
    can be cancelled exactly inside the definition; a quarter turn does not,
    and on a box that is not square it cannot be. And an axis flip is what
    lands a mark somewhere else on a drawing the reader still sees the same way
    up -- which is how a cooler comes to be drawn as a heater -- where a
    quarter turn turns the box with it and what the reader sees is a symbol
    that has plainly been turned.

    So ``orientation=180`` is not a turn as far as the mark is concerned. It is
    both mirrors at once, and it reverses the arrow exactly as either of them
    would: it was the half of this that shipped un-handled.
    """
    half = rot == 180
    return (mirror_x != half, mirror_y != half)


def _upright_artwork(svg: str, w: float, h: float,
                     mirror_x: bool, mirror_y: bool) -> str:
    """Keep a symbol's *directional* drawing saying the same thing under a flip.

    The lettering problem one level out. A cooler is the heater's circle and the
    heater's zigzag with the arrowhead moved to the other end of the diagonal,
    and nothing else tells the two apart, so a flipped cooler is not a cooler
    drawn the other way round: it is the heater, drawn where the author asked
    for a cooler. What the flip was asked for is the *nozzles* on the other side
    -- the reason ``examples/10_ethanol_pfd`` flips one is to put the condenser's
    shell inlet underneath, so the overhead rises into it dead straight -- and
    the ports move under the placement transform however this leaves the ink.

    So the flip is undone inside the definition, about the symbol's own centre
    lines, and the ``<use>`` reapplies it: the two cancel exactly, and the
    drawing lands where it was drawn while the nozzles go where the flip puts
    them. Exactly, because an axis flip commutes with the per-axis scaling that
    fits the artwork into its box.

    *mirror_x* and *mirror_y* are the placement's whole reflection content and
    not only what the caller spelled ``mirrored=``: a half turn is both flips
    composed and reverses the mark just as either one does, so it arrives here
    as both. :func:`_reflections` is where that is worked out, and is also where
    the quarter turn is left alone, which it should be -- a quarter turn takes
    the mark onto ground no upright drawing of either symbol occupies, and turns
    the box with it, so what a reader sees is a turned symbol rather than a
    different one. See :attr:`pandid.render.symbols.Symbol.directional`.

    Only the whole drawing, never part of it: on the one family that declares
    this, the artwork *is* the statement, drawn as a circle with the zigzag and
    the arrow both on its centre. Held still it stays exactly as vendored, which
    is the drawing the check in ``tests/test_symbol_invariants`` measures the
    flipped nozzles against.
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


# Standard page sizes in millimetres, landscape, straight from ISO 216. Held in
# millimetres because that is what the sizes are defined in: deriving each one
# from the last by doubling accumulates ISO's per-size rounding, which is how A1
# and A0 previously came out a millimetre short.
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

    ``width``/``height`` are the layout units the diagram is placed in;
    ``width_mm``/``height_mm`` are the physical size the SVG declares, so the
    sheet prints and converts to PDF at exactly its ISO size rather than at
    whatever the consumer assumes a pixel is worth.
    """
    name: str
    width_mm: float
    height_mm: float

    @property
    def width(self) -> float:
        return self.width_mm * _PX_PER_MM

    @property
    def height(self) -> float:
        return self.height_mm * _PX_PER_MM


def _page(page_size: "str | None") -> "_Sheet | None":
    """Resolve ``page_size``; ``None`` means fit the sheet to the drawing."""
    if page_size is None:
        return None
    dims = _PAGE_SIZES.get(page_size.upper())
    if dims is None:
        raise ValueError(
            f"Unknown page size {page_size!r}; use one of {', '.join(_PAGE_SIZES)}, "
            "or omit page_size to fit the sheet to the drawing."
        )
    return _Sheet(page_size.upper(), *dims)


# The frame the sheet is ruled with: sheet furniture, and a statement about the
# paper rather than about the diagram drawn on it. A PFD carries a zone frame as
# readily as a P&ID does.
_BORDERS = ("none", "zone")
# Which drawing this is, which is a statement about the conventions it is read
# by. It is what decides whether a process line carries an arrowhead.
_DIAGRAMS = ("pfd", "p&id")
# The drawing's name has one accepted spelling per value plus whatever the
# caller can reasonably be expected to type for it.
_ALIASES = {"pid": "p&id", "p&id": "p&id", "pfd": "pfd"}


def _canon(value: str) -> str:
    """Fold a diagram name to the one spelling the table keys on.

    Case is folded and the ampersand-less ``"pid"`` is read as ``"p&id"``. This
    package spells the drawing's name with the ampersand everywhere else, down
    to the distribution, so an engineer who types ``"P&ID"`` is typing the real
    name and must not be told it is unknown; ``"pid"`` is the spelling already
    published and stays working. Nothing else is guessed at.
    """
    return _ALIASES.get(value.strip().lower(), value)


def _resolve_sheet(border: "str | None", diagram: "str | None") -> "tuple[str, str]":
    """The frame to rule and the drawing to rule it around.

    The two are independent: the frame is sheet furniture and a PFD carries the
    zone-ruled one as readily as a P&ID does. A name neither knows is a sheet
    the renderer cannot draw, so it raises rather than quietly handing back a
    plain PFD.
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
            f"Unknown diagram {diagram!r}; use 'p&id' (also spelled 'pid') or 'pfd'."
        )
    return border, kind


def draws_arrowheads(diagram: "str | None") -> bool:
    """Does a drawing of this kind put a head on the end of a process line?

    ANSI/ISA-5.1 draws process piping on a P&ID as plain line: flow direction is
    read off the equipment and off the line list, so an arrowhead at the end of
    every run is a PFD convention, where showing where the material goes is the
    whole job of the line.

    Public, and asked rather than open-coded, because two callers need the
    answer and only one of them is the renderer.
    :func:`pandid.validate.validate` reports nozzles pitched inside the heads
    they carry, and on a sheet that draws none there are no heads to be inside
    of -- a finding about ink the drawing does not contain is a false one however
    well the geometry is measured. Takes the argument in the spelling
    :meth:`pandid.flowsheet.Flowsheet.to_svg` takes it, since that is where a
    caller's answer comes from.
    """
    return _resolve_sheet(None, diagram)[1] != "p&id"


def check_connections(value) -> None:
    """Reject a joint this package has no mark for, naming the ones it has.

    Takes the sheet's spelling or a stream's: a stream may state its two ends
    separately, so a pair is as valid a value as a name and is checked a name
    at a time.
    """
    for name in ((value,) if isinstance(value, str) else tuple(value)):
        if name not in CONNECTIONS:
            raise ValueError(
                f"Unknown connections {name!r}; use one of "
                f"{', '.join(CONNECTIONS)}."
            )


def sheet_connections(diagram: "str | None",
                      connections: "str | None") -> "str | None":
    """The joint a sheet marks by default, or ``None`` if it marks none at all.

    The ``None`` is the load-bearing part and is not the same answer as
    ``"none"``. ``"none"`` is a P&ID that has been asked about its joints and
    has declined to say, so one line on it may still say otherwise; ``None`` is
    a drawing on which the question does not arise, and nothing a stream states
    can reopen it.

    That distinction is ISO 15519-2:2015's, not this package's. Table 5 (p. 19)
    lists, as *basic* information for a P&ID, "specific graphical symbols for
    process equipment incl. prime movers (electrical motors, combustion motors,
    turbines, etc.), valves incl. actuators, **connections**, etc."; Table 4
    (p. 17) gives the PFD only "general graphical symbols for connections". A
    flange face is as specific as a connection gets. A PFD that drew one would
    be answering a question -- how is this bolted up? -- that the drawing it is
    has not been asked, so ``connections="flanged"`` on a PFD draws nothing,
    exactly as ``diagram`` already overrules everything about arrowheads.

    Public and asked rather than open-coded for the reason
    :func:`draws_arrowheads` is: the draw.io exporter needs the same answer and
    is not the renderer.
    """
    if connections is not None:
        check_connections(connections)
    if _resolve_sheet(None, diagram)[1] != "p&id":
        return None
    return connections or "none"


def resolve_connections(s, default: "str | None") -> "tuple[str, str]":
    """What one stream says about its own two joints, ``(source, dest)``.

    ``Stream.ends`` unset means "whatever the sheet said", the same shape a
    valve station's ``tag_scheme`` override takes and for the same reason: what
    an author states on one line has to be able to say the *opposite* of the
    sheet, both ways round, or a mostly-welded sheet with three flanged joints
    and a mostly-flanged sheet with three welded ones cannot both be written.
    So an unset stream inherits and a set one wins, including winning with
    ``"none"``.

    A pair states the two ends apart, in the order they were connected, because
    that is the order the author already typed them in: ``connect(a, b)`` then
    ``ends=("flanged", "none")`` is the joint at *a* flanged and the joint at
    *b* not. Nothing else would have to be remembered.
    """
    if default is None:
        return ("none", "none")
    ends = getattr(s, "ends", None) or default
    return (ends, ends) if isinstance(ends, str) else (ends[0], ends[1])


def _fit_scale(dw: float, dh: float, free) -> float:
    """The uniform scale that puts a ``dw`` x ``dh`` drawing inside *free*.

    Never enlarges: sheet furniture is drawn at a fixed size, so blowing a small
    drawing up to fill the page would swell its line weights and lettering out
    of proportion to the border and title strip around it. A draftsman picks a
    scale that fits and leaves the rest of the sheet white.
    """
    _, _, fw, fh = free
    return min(1.0, fw / dw if dw > 0 else 1.0, fh / dh if dh > 0 else 1.0)


def _scale_text(s: float) -> str:
    """A fit scale as a title-block ratio."""
    return "1:1" if s >= 1.0 else f"1:{1 / s:.3g}"


# Findings this renderer raises about text that did not fit the cell drawn for
# it, as opposed to the validator's findings about the diagram.
_FIT_CODES = ("text-truncated", "text-overruns-cell")


def _too_small(sheet: _Sheet, need_w: float, need_h: float,
               cause: str = "") -> ValueError:
    """Furniture is drawn at a fixed size, so a sheet too small to hold it is an
    error no scale of the drawing can resolve.

    ``cause`` names the widest piece, which is the one worth shortening: a
    stream table sized to its own contents is usually what pushed a sheet over,
    and "the furniture does not fit" does not say which furniture.
    """
    blame = f" The widest piece is {cause}." if cause else ""
    return ValueError(
        f"The sheet furniture does not fit page size {sheet.name}: the border, title strip "
        f"and docked boxes need at least {need_w:.0f}x{need_h:.0f}px of the "
        f"{sheet.width:.0f}x{sheet.height:.0f}px sheet.{blame} Use a larger page_size, or omit "
        "page_size to fit the sheet to the drawing."
    )


# The title strip is placed by the same band arithmetic as the boxes the caller
# docked, but it is not an object of the caller's -- a zone-ruled sheet rules a
# strip whether or not a title block was filled in -- so it stands in the
# columns as a sentinel. Naming it is what an error that has to say *which*
# piece of furniture will not fit needs.
#
# The stream table used to need one too and no longer does: it is a
# :class:`~pandid.render.furniture.StreamTable`, an object both backends
# measure and dock, so it stands in the columns as itself.
TITLE = "\x00title"
_FURNITURE_NAMES = {TITLE: "the title strip"}


def _furniture_name(obj) -> str:
    if isinstance(obj, str):
        return _FURNITURE_NAMES.get(obj, obj)
    if isinstance(obj, F.StreamTable):
        return "the stream table"
    title = getattr(obj, "title", "")
    return f"the {title!r} box" if title else "an untitled annotation box"


# The two comments that fence the provenance block. They exist for the reader
# who has to *ignore* it: a version string in the body of an SVG would move
# every golden fixture and every committed gallery sheet on each release, and a
# comparison that wants to look past it needs somewhere to stop rather than a
# pattern to hunt for. ``tests/test_golden.py`` drops everything between these
# two lines before comparing -- one slice, not a regex over the document -- and
# keeps the fences themselves, so a golden still records that the block is there
# and where in the file it sits.
#
# Anything version-dependent must therefore go *inside* the fence. ``<title>``
# stays outside it on purpose: it carries the sheet's own name and no version,
# so it is real content and belongs in the comparison like any other line.
PROVENANCE_OPEN = "  <!-- pandid:provenance -->"
PROVENANCE_CLOSE = "  <!-- /pandid:provenance -->"

_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _sheet_title(fs: "Flowsheet") -> str:
    """What this drawing is called.

    The title block's title when the sheet has been given one -- that is the
    title the drawing is *issued* under, and it is what is lettered on the sheet
    -- and the flowsheet's own name otherwise, which is all an unfurnished sheet
    has. Either can be empty, and an empty accessible name is worse than none,
    so the caller drops ``<title>`` rather than emitting a blank one.
    """
    tb = fs.title_block
    if tb is not None and tb.title:
        return tb.title
    return fs.name or ""


def _provenance(fs: "Flowsheet") -> list[str]:
    """The document's title and the block saying what drew it.

    Openly, in a comment and in a real ``<metadata>`` element, and *not* as a
    white-on-white string in the drawing. That was considered and rejected on
    three counts. An SVG is plain text, so a mark hidden from the eye is not
    hidden from anyone who opens the file -- it buys nothing a comment does not.
    It is removable in a single edit, so its presence attributes a file and its
    absence proves nothing, which makes it worthless as evidence. And an
    invisible run of text inside a controlled engineering document is a
    liability: it comes out on select-all-copy and in any text extractor, and
    ends up pasted into a client deliverable nobody chose to put it in.

    ``<title>`` is the first child of ``<svg>`` because that is where a browser
    looks for the tooltip and where a screen reader looks for the document's
    accessible name; it holds the sheet's own title (see :func:`_sheet_title`)
    and nothing else. ``dc:title`` repeats it inside the metadata, where a
    cataloguing tool reads it, and ``dc:creator`` names what drew the file.
    """
    from pandid.render import HOMEPAGE, generator
    who = generator()
    title = _sheet_title(fs)
    lines = []
    if title:
        lines.append(f"  <title>{html.escape(title)}</title>")
    lines.append(PROVENANCE_OPEN)
    # Not the em-dash-free prose it looks like: an XML comment may not contain
    # "--" anywhere (XML 1.0 §2.5), so the "pandid 0.1.2 -- https://..." this was
    # first drafted as would have made every sheet malformed. Several tests parse
    # a rendered sheet with ElementTree and would have caught it; the colon costs
    # nothing and is legal.
    lines.append(f"  <!-- Generated by {who}: {HOMEPAGE} -->")
    lines.append("  <metadata>")
    lines.append(f'    <rdf:RDF xmlns:rdf="{_RDF_NS}" xmlns:dc="{_DC_NS}">')
    # ``rdf:about=""`` is the RDF spelling of "this document", which is what the
    # description is about -- the file, not the plant it draws.
    lines.append('      <rdf:Description rdf:about="">')
    lines.append(f"        <dc:creator>{html.escape(who)}</dc:creator>")
    if title:
        lines.append(f"        <dc:title>{html.escape(title)}</dc:title>")
    lines.append("      </rdf:Description>")
    lines.append("    </rdf:RDF>")
    lines.append("  </metadata>")
    lines.append(PROVENANCE_CLOSE)
    return lines


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry

    def render(self, fs: "Flowsheet", *, jump_direction: str = "vertical",
               show_stream_table: bool = False,
               border: "str | None" = None, diagram: "str | None" = None,
               page_size: "str | None" = None, connections: "str | None" = None,
               debug: "bool | float" = False,
               **opts) -> str:
        """Render the flowsheet to SVG.

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
        jump_direction : str
            Which crossing lines get a semicircle bump: ``"vertical"`` or ``"horizontal"``.
        show_stream_table : bool
            Whether to render a stream property table on the sheet.
        border : str | None
            ``"none"`` for a plain sheet edge, ``"zone"`` for the zone-ruled
            ASME-style drawing frame. The flowsheet's title block and annotation
            boxes are drawn whichever is chosen.
        diagram : str | None
            Which drawing this is: ``"pfd"`` (the default) or ``"p&id"``, also
            spelled ``"pid"``. A P&ID draws its process lines without arrowheads.
        page_size : str | None
            Standard paper size (``"A4"``, ``"A3"``, ``"A2"``, ``"A1"``, ``"A0"``),
            drawn at exactly that size, with the furniture docked to the sheet edges
            and the drawing fitted into what they leave. ``None`` (the default) sizes
            the sheet to the drawing instead.
        debug : bool | float
            Draw the coordinate overlay under the diagram: a ruled grid carrying
            its own coordinates, every unit's ``pin()`` anchor and every port.
            ``True`` rules it at the default spacing and a number sets that
            spacing. Off by default. See :mod:`pandid.render.debug`.
        """
        from pandid.portgeom import unit_box
        from pandid.render import debug as _debug
        # Resolved first, so a spacing the overlay cannot draw is refused before
        # anything is drawn rather than after a whole sheet has been built.
        grid = _debug.resolve_spacing(debug)
        border, diagram = _resolve_sheet(border, diagram)
        arrows = draws_arrowheads(diagram)
        joints = sheet_connections(diagram, connections)
        sheet = _page(page_size)

        # 1. Diagram bounding box: union of every unit's drawn box and every
        #    route waypoint. Furniture is placed *around* this fixed region.
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

        # 2. The stream table, measured. Shared with the draw.io exporter, which
        #    docks and rules the same one; see F.stream_table_layout.
        st_layout = F.stream_table_layout(fs) if show_stream_table else None

        # 3. Place furniture around the diagram and size the sheet.
        margin = 55.0
        furniture: list[str] = []
        # union of everything drawn (diagram + furniture), grown as boxes land
        U = [dx0, dy0, dx1, dy1]

        def grow(x0, y0, x1, y1):
            U[0], U[1] = min(U[0], x0), min(U[1], y0)
            U[2], U[3] = max(U[2], x1), max(U[3], y1)

        free = None  # region a fixed sheet leaves for the drawing
        fit_issues: list[Issue] = []

        def report(field: str, text: str, drawn: str) -> None:
            fit_issues.append(
                Issue("warning", "text-truncated",
                      f"{field} was truncated to fit its cell: "
                      f"{text!r} drawn as {drawn!r}")
                if drawn != text else
                Issue("warning", "text-overruns-cell",
                      f"{field} is wider than the cell it is drawn in: {text!r}"))

        # Furniture belongs to the sheet, not to the border: a title block or a
        # docked box is drawn because it was supplied. A zone border implies a
        # formal sheet, which carries a title strip whether one was filled in or
        # not.
        furnished = (border == "zone" or fs.title_block is not None
                     or bool(getattr(fs, "annotations", None)))
        if furnished:
            (frame_x, frame_y, canvas_width, canvas_height), free = self._place_furniture(
                fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet, border, report)
        elif sheet is not None:
            free = self._place_plain(st_layout, sheet, margin, furniture)
            frame_x, frame_y = 0.0, 0.0
            canvas_width, canvas_height = sheet.width, sheet.height
        else:
            # Plain sheet: optional stream table docked below the diagram, left.
            if st_layout:
                top = dy1 + 24
                furniture.extend(F.draw_stream_table(st_layout, dx0, top))
                grow(dx0, top, dx0 + st_layout.w, top + st_layout.h)
            frame_x, frame_y = U[0] - margin, U[1] - margin
            canvas_width = (U[2] - U[0]) + 2 * margin
            canvas_height = (U[3] - U[1]) + 2 * margin

        # A cell that could not hold its text is a finding about this render, so
        # it joins the validator's on ``fs.warnings``. Findings from an earlier
        # render are dropped rather than added to: a title shortened and
        # re-rendered must stop warning about the old one.
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _FIT_CODES] + fit_issues

        # 4. SVG document.
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        # A named page size declares its physical size, so the sheet prints and
        # converts to PDF at exactly that ISO size instead of at whatever the
        # consumer takes a user unit to be worth. A sheet fitted to the drawing
        # has no physical size to declare and stays in user units.
        if sheet is not None:
            decl_w, decl_h = f"{sheet.width_mm:g}mm", f"{sheet.height_mm:g}mm"
        else:
            decl_w, decl_h = f"{canvas_width:.0f}", f"{canvas_height:.0f}"
        lines.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{decl_w}" height="{decl_h}" '
            f'viewBox="{frame_x:.1f} {frame_y:.1f} {canvas_width:.1f} {canvas_height:.1f}">'
        )
        # What drew the file, and what the file is called. First children of
        # <svg>, before any ink: <title> is the document's accessible name and
        # is only picked up there, and the generator comment is what a reader
        # opening the text sees first. See :func:`_provenance`.
        lines.extend(_provenance(fs))
        lines.append('  <!-- Background -->')
        lines.append(f'  <rect x="{frame_x:.1f}" y="{frame_y:.1f}" width="{canvas_width:.1f}" height="{canvas_height:.1f}" fill="white" />')

        # Furniture (border + title strip + boxes) sits behind the diagram.
        for item in furniture:
            lines.append("    " + item)

        lines.extend(self._defs(fs, arrows))
        unit_labels: list = []
        balloons: list = []
        # Where every line on the sheet runs. Both label passes below write on an
        # opaque halo and so have to be told, and this is the first point in the
        # program where the answer exists: the routes are settled and the
        # balloons have stopped moving, so the impulse lines are settled with
        # them. See :func:`_ink`.
        ink = _ink(fs)
        # The letter codes written outside the balloons, placed before anything
        # that has to dodge them; see :func:`quadrant_labels`. Drawn with the
        # equipment tags at the end, on the same halo.
        quadrants = quadrant_labels(fs)
        drawing: list[str] = []
        # Every opaque white plate the sheet lays down, collected only when the
        # overlay is going to be drawn. The overlay is emitted *under* the
        # drawing, so a plate is the one thing on the sheet that can delete it
        # outright, and the only way for it to step clear is to be told where
        # they landed. Nothing here changes what is drawn: with ``debug`` off
        # the list is ``None`` and not one of these boxes is computed.
        plates: "list[tuple[float, float, float, float]] | None" = (
            [] if grid is not None else None)
        drawing.extend(self._draw_units(fs, unit_labels, balloons, ink, joints,
                                        quadrants))
        drawing.extend(self._draw_streams(fs, jump_direction, unit_labels, arrows,
                                          plates, joints))
        # Instrumentation goes on over the lines: an impulse line runs from the
        # tap to the balloon, and the balloon's opaque body then knocks out both
        # it and any process line an in-line element straddles.
        drawing.extend(self._draw_taps(fs))
        if balloons:
            drawing.append('  <g id="instruments">')
            drawing.extend(balloons)
            drawing.append('  </g>')
        # Equipment tags go on last, haloed, so no stream line strikes through
        # them, and the quadrant codes with them: a code is lettering outside a
        # symbol and wants the same halo over the same lines.
        drawing.extend(self._draw_unit_labels(unit_labels + quadrants))

        # Placed last and drawn first. The overlay must sit *under* every piece
        # of the sheet's own ink -- it is scaffolding for the author and must
        # not come between the reader and the drawing -- but it can only choose
        # paper the sheet has left clear if it is worked out once the sheet
        # exists. Those two are not in conflict; they are the same requirement
        # read from both ends, and the only thing standing between them was the
        # order this function happened to build its list in. Splicing the result
        # onto the head is what keeps the drawing order the overlay's whole
        # safety argument rests on.
        #
        # It goes inside the fitted group for a separate reason: the numbers it
        # writes have to be the ones ``pin()`` takes, and a fixed page scales
        # that group, so the overlay is told the scale and holds its lettering
        # to a constant size on paper while leaving its geometry in drawing
        # units.
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
        lines.append('</svg>')
        return "\n".join(lines)

    def _fit(self, dx0, dy0, dx1, dy1, free) -> str:
        """Transform centring the drawing in *free* at a uniform scale."""
        fx, fy, fw, fh = free
        dw, dh = dx1 - dx0, dy1 - dy0
        s = _fit_scale(dw, dh, free)
        return (f"translate({_num(fx + (fw - s * dw) / 2 - s * dx0)}, "
                f"{_num(fy + (fh - s * dh) / 2 - s * dy0)}) scale({s:.6g})")

    # ------------------------------------------------------------------ furniture

    def _place_furniture(self, fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet,
                         border, report=None):
        """Dock furniture flush to the sheet *frame* (not the drawing), and rule
        that frame into zones when the sheet asked for a border.

        Boxes are grouped into edge *bands* by ``align``; the frame grows
        outward from the diagram bounds just enough to hold them, and each box
        is placed flush against the frame edge its ``align`` names (inset by its
        ``margin``). A box with an explicit ``position`` is hand-placed instead.
        Given a *sheet*, the frame is instead the fixed page inset by the border,
        and the drawing is fitted into the region the bands leave.

        The band arithmetic itself is :func:`pandid.render.furniture.dock`'s,
        which is a statement about a *sheet* rather than about SVG and is shared
        with the draw.io exporter for that reason. What is left here is the
        drawing: measure each box, hand the measurements to the dock, and stroke
        whatever comes back where it says.

        Returns the outer canvas rect ``(x, y, w, h)`` and that free region
        ``(x, y, w, h)``, or ``None`` when the frame was grown to the drawing.
        """
        from pandid.document import TitleBlock, TableBox

        OUT = F.OUTER_MARGIN

        def measure(a):
            return F.measure_table(a) if isinstance(a, TableBox) else F.measure_annotation(a)

        def draw_box(a, x, y):
            furniture.extend(F.draw_table(a, x, y) if isinstance(a, TableBox)
                             else F.draw_annotation(a, x, y, report=report))

        # Title strip + stream table are bottom furniture, at the foot of the
        # bottom-right / bottom-left columns so the band maths sizes the frame
        # around them too. The strip stands in as a sentinel (see TITLE); the
        # stream table is a measured object and stands in as itself.
        strip = fs.title_block is not None or border == "zone"
        tb = fs.title_block or TitleBlock()
        ts_w, ts_h = F.measure_title_strip(tb)
        date = tb.date or datetime.now().strftime("%Y-%m-%d")
        name = tb.title or fs.name

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
        # The scale cell reports the ratio the drawing was actually placed at,
        # which the dock has just settled. A frame grown to the drawing has no
        # fixed page and so no scale to state.
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

        # --- border around the frame, then the sheet edge ---------------------
        if border == "zone":
            frame_lines, outer = F.zone_frame(ix, iy, iw, ih)
            furniture[:0] = frame_lines  # border sits behind the boxes
        else:
            outer = F.sheet_rect(ix, iy, iw, ih)
        ox, oy, ow, oh = outer
        return (ox - OUT, oy - OUT, ow + 2 * OUT, oh + 2 * OUT), free

    def _place_plain(self, st_layout, sheet, margin, furniture):
        """Fixed page carrying no furniture of its own: the stream table docks to
        the foot of the sheet and the drawing takes the region above it. Returns
        that region."""
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

    # ------------------------------------------------------------------ defs

    def _baked_xform(self, u) -> tuple[int, bool, bool]:
        """The placement transform a unit's symbol definition must bake in.

        Two things in a drawing belong to the *drawing* rather than to the
        attitude the equipment is installed in, and so have to survive the
        placement: its own lettering, which stays readable
        (:func:`_upright_text`), and a directional mark, which an axis flip
        reverses (:func:`_upright_artwork`). Each is undone inside the
        definition and reapplied by the ``<use>``.

        The identity for every symbol with neither -- the great majority -- so
        those keep sharing one definition and one id no matter how they are
        placed.

        A directional symbol reports its placement's *reflection content*
        instead of the placement, since that is the whole of what it bakes in:
        a half turn arrives as both flips (:func:`_reflections`), and a quarter
        turn as none, so ``orientation=90`` on an unflipped one still shares the
        single definition the sheet had before and the four placements that flip
        it share three more between them.
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
        """The ``<defs>`` id a unit's ``<use>`` points at.

        One definition per ``(kind, variant)``, plus a suffix for whatever else
        is baked into the definition rather than applied by the ``<use>``: the
        size a built-to-measure symbol was drawn at, the size a *resized* unit
        had its line weights compensated for (see :func:`_pen_scale`) or was
        redrawn at outright (see :func:`_fold`), and the counter-transform that
        keeps a symbol's own lettering readable or its direction arrow pointing
        the way it was drawn.
        """
        variant = getattr(u, 'variant', 'default')
        sym = self.registry.for_unit(u)
        sym_id = f"sym_{u.kind}" if variant == "default" else f"sym_{u.kind}_{variant}"
        sym_id += sym.id_suffix + _size_tag(sym, u)
        return sym_id + _xform_tag(*self._baked_xform(u))

    def _defs(self, fs, arrows=True):
        lines = []
        # Sorted, not raw set order: set iteration depends on the process hash
        # seed, so an identical flowsheet would otherwise emit byte-different
        # SVG from run to run, breaking diffs, caching and golden tests.
        used_colors = sorted({s.color or "black" for s in fs.streams})
        lines.append('  <defs>')
        # A sheet that draws no arrowhead defines none: the only lines that ever
        # wore one are the process lines, so on a P&ID the whole set is dead.
        for c in used_colors if arrows else ():
            marker_id = f'arrow_{c.replace("#", "").replace(" ", "_")}'
            lines.append(
                f'    <marker id="{marker_id}" viewBox="0 0 10 10" refX="10" refY="5" '
                f'markerWidth="{ARROWHEAD:g}" markerHeight="{ARROWHEAD:g}" '
                f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{c}" />')
            lines.append('    </marker>')

        # A symbol carrying its own lettering, or a directional mark, needs one
        # definition per placement transform in use, since the counter-transform
        # that keeps the letters readable and the arrow pointing the way it was
        # drawn is baked into the definition; a symbol built to measure needs
        # one per size, so the box it is placed in is the box it was drawn in and
        # the scale factor stays exactly 1; and a symbol some unit *resized*
        # needs one per placed size too, since the weight it is drawn at is
        # compensated for that scale (see _pen_scale) and a definition cannot
        # carry two. Everything else (the great majority) still shares a single
        # definition however it is placed.
        used: dict[tuple, tuple] = {}
        # Definitions some placement asks to fill a box of another shape. A
        # <symbol> scales its viewBox to fit and centres what is left over, so a
        # unit given a width and height of its own is drawn smaller than the box
        # with whitespace down one pair of sides -- and portgeom, which maps its
        # ports linearly onto the box, then puts them out in that whitespace.
        # The two are made to agree by stretching the artwork instead, wherever
        # the symbol says it may be (see Symbol.stretchable); where it may not,
        # portgeom follows the letterbox and the ports land on the drawing.
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
            # A definition redrawn at the placed size fills its box by being the
            # size of it, so it has no aspect ratio left to give up.
            if sym.stretchable and _reshapes(sym, u) and fold == (1.0, 1.0):
                stretched.add(key)
        for key in sorted(used):
            sym_id, sym, fold, pen, rot, mirror_x, mirror_y = used[key]
            # The redraw first, so everything after it -- the pen division, the
            # counter-transforms, the viewBox -- is stated in the coordinates
            # the definition is actually going to be written in.
            art = _baked(sym.svg, *fold)
            width, height = sym.width * fold[0], sym.height * fold[1]
            # Either, never both. A directional symbol's *whole* drawing is held
            # still, lettering included, so a glyph inside one would need the
            # residual of the two rather than its own counter-transform. No
            # symbol carries both, and
            # test_a_directional_symbol_carries_no_lettering_of_its_own says so
            # over the registry rather than leaving this branch to be trusted.
            if sym.directional:
                svg_str = _upright_artwork(_at_pen_scale(art, pen),
                                           width, height, mirror_x, mirror_y)
            else:
                svg_str = _upright_text(_at_pen_scale(art, pen), rot, mirror_x, mirror_y)
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                # preserveAspectRatio: stated only where a placement reshapes the
                # artwork, since "none" and the "xMidYMid meet" default are the
                # same drawing whenever the scale is uniform -- and a definition
                # nothing reshapes has nothing to say about being reshaped.
                fill = ' preserveAspectRatio="none"' if key in stretched else ''
                # overflow="visible": a <symbol> viewport defaults to overflow:hidden,
                # which clips the outer half of any stroke whose geometry sits on the
                # viewBox edge (e.g. an ellipse with rx == w/2). That makes a circle
                # render thin at its four cardinal points while the diagonals stay full
                # weight. Letting the symbol overflow keeps every stroke at uniform width.
                box = (f"{sym.width} {sym.height}" if fold == (1.0, 1.0)
                       else f"{_art(width)} {_art(height)}")
                svg_str = (f'<symbol id="{sym_id}" viewBox="0 0 {box}"'
                           f'{fill} overflow="visible">{inner}</symbol>')
            else:
                svg_str = re.sub(r'id="[^"]+"', f'id="{sym_id}"', svg_str, count=1)
            lines.append(f'    {svg_str}')
        lines.append('  </defs>')
        return lines

    # ------------------------------------------------------------------ units

    def _draw_units(self, fs, label_items, balloons, ink=(), joints=None,
                    quadrants=()):
        from pandid.portgeom import unit_box

        lines = ['  <g id="units">']
        # Every symbol on the sheet, paired with the unit that drew it, so a tag
        # can step off somebody else's artwork the way it already steps off
        # somebody else's line. Built once: it is the same list for every tag.
        #
        # The flange marks are in it under no unit at all, which is what they
        # are: a mark on a run belongs to the joint and not to either end of it,
        # and _tag_item's `v is not u` test then lets every tag see every one of
        # them. They earn their place the way the balloons did -- RB-301's tag
        # shipped with two units cut out of the flange face on the reboiler's
        # vapour riser, and every test passed, because the tag pass was told
        # about the lines and the symbols and a flange is neither.
        symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
        symbols += [(None, b) for b in flange_boxes(fs, joints)]
        # A letter code outside a balloon is under no unit either, and for the
        # same reason: it is lettering, not artwork, so every tag has to see it
        # and none of them owns it.
        symbols += [(None, b) for b in map(_unit_label_box, quadrants) if b is not None]
        for u in fs.units:
            f = u.frame
            out = balloons if u.kind == "instrument" else lines
            x, y = f.x, f.y
            # The tag, not the name: a symbol that repeats (a trip square, a
            # utility header flag) is drawn with the tag it shares and named
            # apart only so the flowsheet can address each drawing of it.
            safe_name = html.escape(u.tag)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, x, y, safe_name))
                continue

            sym_id = self._sym_id(u)
            u_width, u_height = f.w, f.h
            rot = int(getattr(f, "orientation", 0) or 0)
            mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
            cx, cy = x + u_width / 2, y + u_height / 2

            # A quarter turn swaps the box the artwork is drawn into; place that
            # box centred on the frame so rotating it about the centre lands it
            # back on the frame exactly.
            if rot in (90, 270):
                bw, bh = u_height, u_width
            else:
                bw, bh = u_width, u_height
            ux, uy = cx - bw / 2, cy - bh / 2

            # Composed right-to-left by SVG, so this reads "mirror, then
            # rotate", the same order portgeom.symbol_to_box uses for the ports.
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
                # A symbol that carries no tag is labelled nowhere. Only the
                # pipe tee is such a symbol today: it is bare pipe, and an
                # issued sheet writes nothing against a junction.
                tag_box = None
                if u.tag:
                    item = self._tag_item(u, f, x, y, u_width, u_height, safe_name,
                                          ink, symbols)
                    tag_box = _unit_label_box(item)
                    label_items.append(item)
                # A body that cannot carry the darkening says so in letters
                # instead; see ISO 15519-1 §11.4.5 and _nc_label_item.
                if closed_marking(u, self.registry) == "NC":
                    label_items.append(
                        self._nc_label_item(u, f, x, y, u_width, u_height, tag_box))
                # Where an actuated valve goes when its air or power is lost.
                # A separate question from the one above, in a separate corner;
                # see ISA-5.1 Table 5.4.4 and _fail_label_item.
                letters = fail_marking(u)
                if letters:
                    label_items.append(
                        self._fail_label_item(u, f, x, y, u_width, u_height, letters,
                                              tag_box, ink, symbols))
        lines.append('  </g>')
        return lines

    def _draw_taps(self, fs):
        """The fine line from a tap point to the balloon reading it.

        Solid where the line is an **impulse line**, because that is what it is:
        a length of tubing standing between the pipe and the element, full of
        the fluid the reading is taken from. Dashed everywhere else, where what
        the line carries is a measurement or a command -- a balloon hung off
        another balloon (an interlock under its controller), a balloon teed off
        a **signal line**, which is how the issued sheet draws a trip, and a
        trip square hung on the valve it strokes. Nothing is drawn at all where
        a stream already joins the two, or where the element sits directly on
        the line (``offset=0``).

        Which of the two it is, is a question about the line and is asked of
        both its ends: see :func:`impulse_tap`. It is emphatically *not* a question
        about the host's class, which is what this used to read, and answering
        the wrong question drew a signal as pipe on three of the shipped sheets.

        Fine is the same fine as a signal stream: ISO 15519-2 Annex A.1.02 puts
        an instrument connection on the 0,25 rung, alongside the signal line and
        half the pipeline it taps. See :data:`_SIGNAL_STROKE`.

        Which lines there are is :func:`tap_lines`' answer, since label
        placement has to dodge exactly the ones this draws.
        """
        out = []
        for u, (tx, ty), (cx, cy) in tap_lines(fs):
            dash = "" if impulse_tap(u) else f' stroke-dasharray="{_TAP_DASH}"'
            out.append(f'    <line x1="{_num(tx)}" y1="{_num(ty)}" x2="{_num(cx)}" '
                       f'y2="{_num(cy)}" stroke="black" stroke-width="{_SIGNAL_STROKE}"{dash} />')
        return ['  <g id="instrument_taps">'] + out + ['  </g>'] if out else []

    def _draw_boundary(self, u, f, x, y, safe_name):
        """Feed / Product off-page connector flag, with an optional second line
        referencing the drawing the stream comes from / goes to."""
        ref = getattr(u, "reference", "") or ""
        # The pennant's own geometry, which the draw.io exporter reads too; see
        # :func:`boundary_flag`. Slightly taller where an off-page reference has
        # to fit under the tag, and centred on the port either way (y + 25).
        (bx0, top, bx1, bot), depth, east = boundary_flag(u, f)
        label_w = f.w
        # The tag goes in the flat part of the flag, not in the whole of it: the
        # point is not paper a word can be written across.
        if east:
            px0, px1, px2 = bx0, bx1 - depth, bx1
            tx = px0 + (label_w - depth) / 2
        else:
            px0, px1, px2 = bx1, bx0 + depth, bx0
            tx = bx0 + depth + (label_w - depth) / 2
        points = f"{px0},{top} {px1},{top} {px2},{y + 25} {px1},{bot} {px0},{bot}"
        out = [f'    <polygon points="{points}" fill="transparent" stroke="black" stroke-width="2" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{y + 21}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{y + 33}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{html.escape(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{y + 25}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        """Functional letters over the bare loop number, as ISA-5.1 draws them.

        An interlock square carries the number alone: its letters are only the
        tag prefix, and a real sheet leaves the square holding one figure.
        """
        from pandid.units import split_tag

        variant = getattr(u, "variant", "default")
        # The tag, not the name: a repeated square is drawn with the tag it
        # shares and named apart only so the flowsheet can address it.
        tag = getattr(u, "tag", "") or u.name
        top, bot = split_tag(getattr(u, "type", "") or tag, getattr(u, "number", "") or "")
        cx, cy = x + u_width / 2, y + u_height / 2
        if variant in _DIAMOND_BALLOONS:
            # A diamond is widest on its horizontal diagonal and narrows to
            # nothing at the bottom vertex, so the number cannot simply be
            # centred in the box the way the old bare square's was: it goes in
            # the lower half, where ISA-5.1 draws it under the interlock
            # designator, but only as far down as the sloping sides still leave
            # it room. Seven units below the middle of a 40 box is where a
            # two-figure number's bottom corners clear the edges; it is set at
            # the balloons' own number size, being the same loop number they
            # carry.
            return [f'    <text x="{cx}" y="{cy + 7}" font-family="sans-serif" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{html.escape(bot or top)}</text>']
        if not top:
            return [f'    <text x="{cx}" y="{cy}" font-family="sans-serif" '
                    f'font-size="12" text-anchor="middle" '
                    f'dominant-baseline="middle">{html.escape(bot or top)}</text>']
        # The location bar is what the balloon says about *where* the instrument
        # lives, and it is drawn across the middle, exactly where the letters
        # would otherwise sit. ISA-5.1 puts the letters wholly above the bar and
        # the number wholly below, so a barred variant needs the pair pushed
        # apart to leave the band clear.
        letters_dy, number_dy = (-10, 11) if variant in _BARRED_BALLOONS else (-4, 10)
        out = [f'    <text x="{cx}" y="{cy + letters_dy}" font-family="sans-serif" '
               f'font-size="12" font-weight="bold" text-anchor="middle" '
               f'dominant-baseline="middle">{html.escape(top.upper())}</text>']
        if bot:
            out.append(f'    <text x="{cx}" y="{cy + number_dy}" font-family="sans-serif" '
                       f'font-size="11" text-anchor="middle" '
                       f'dominant-baseline="middle">{html.escape(bot)}</text>')
        return out

    def _label_place(self, lpos, x, y, u_width, u_height):
        """Where a label on side ``lpos`` of a unit's box goes, and how it sets."""
        if lpos == "bottom":
            return x + u_width / 2, y + u_height + 15, "middle", "middle"
        if lpos == "left":
            return x - 10, y + u_height / 2, "end", "middle"
        if lpos == "right":
            return x + u_width + 10, y + u_height / 2, "start", "middle"
        if lpos == "center":
            return x + u_width / 2, y + u_height / 2, "middle", "middle"
        if lpos == "top_right":
            # Above the symbol *and to the right*: the text starts at the box's
            # right edge on the same baseline a top label sets on. Only the NC
            # marking is placed here; see :meth:`_nc_label_item`.
            return x + u_width, y - 10, "start", "baseline"
        return x + u_width / 2, y - 10, "middle", "baseline"  # top

    def _unit_label_item(self, u, f, x, y, u_width, u_height, safe_name):
        """Resolve a unit label's placement. Drawn in a final pass (see
        :meth:`_draw_unit_labels`) so stream lines never strike through it."""
        lpos = f.label_pos or "top"
        return (*self._label_place(lpos, x, y, u_width, u_height), lpos, safe_name)

    def _tag_item(self, u, f, x, y, u_width, u_height, safe_name, ink, symbols=()):
        """The equipment tag, stepped clear of what is already on the sheet.

        :func:`~pandid.layout.coordinates.assign_labels` chose the side, from the
        faces no nozzle leaves from, which is the whole of what is knowable while
        layout runs. It is not the whole of the question. A face with no nozzle of
        its own still has the line that passes it, the impulse line running from
        a tap on that line to the balloon reading it, and the balloon itself; the
        tag is drawn last of everything, on an opaque halo, so it wins against
        all three, and what it wins is a hole in somebody else's drawing.

        *symbols* is every other unit's box, because a free face is not free
        paper: a nozzle is the only thing layout can see, and a balloon parked
        just off the face is invisible to it. Both halos that were eating a
        symbol on ``11_ethanol_pid`` were on a face layout was right to call
        free -- D-301's right face carries no nozzle, and LT-304 hangs off the
        end of the impulse line that leaves it.

        So the placement is settled again here, where the ink exists. The tag
        first steps *along* the side it was given, which is the same move the
        ``NC`` and fail-position letters make around it: a reader scans a sheet
        by side, so a tag beside the symbol it names on the face layout chose is
        worth more than a tidy centring. Only when the whole face is spoken for
        does it try another free one. The first placement that deletes nothing
        wins; where nothing is clear the least damaging wins, weighed by
        :func:`_erases`, and a tie keeps the earlier answer, so a tag that has
        nowhere better to go stays where layout put it.

        A side the author named is left where they put it, as is one the symbol
        fixes (an instrument balloon's ``center``), because neither is this
        function's to overrule.
        """
        from pandid.layout.coordinates import free_label_sides

        item = self._unit_label_item(u, f, x, y, u_width, u_height, safe_name)
        box = _unit_label_box(item)
        if box is None or not (ink or symbols):
            return item
        if getattr(u, "label_pos", None) or self.registry.for_unit(u).label_pos:
            return item
        # Only what is near this unit can be under one of its tag's candidate
        # spots, and testing the whole sheet against every one of them is what
        # would make choosing between them expensive.
        pad = max(u_width, u_height) + (box[2] - box[0])
        window = (x - pad, y - pad, x + u_width + pad, y + u_height + pad)
        near = [line for line in ink if _meets(line.box, window)]
        # This unit's own box is not among them: a tag is placed a fixed clear
        # distance off its own symbol and never lands on it, and counting it
        # would make every spot equally bad and so make the search choose
        # nothing. The rest are grown to their ink (:func:`_obstacle`) here
        # rather than by the caller, so the draw.io exporter -- which builds a
        # list of its own and hands it to this method -- gets the same answer.
        others = [_obstacle(b) for v, b in symbols
                  if v is not u and _meets(_obstacle(b), window)]

        clear = (0, 0, 0)
        best, damage = item, _erases(box, near, others)
        sides = [item[4]] + [s for s in free_label_sides(u) if s != item[4]]
        for side in sides:
            if damage == clear:
                break
            lx, ly, anchor, baseline = self._label_place(side, x, y, u_width, u_height)
            # A tag steps along its face only as far as the symbol's own half
            # width (or half height, on a side face). Past that it stops reading
            # as this unit's tag and starts reading as the neighbour's.
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
        """The ``NC`` abbreviation, for a valve whose body cannot be darkened.

        **ISO 15519-1 §11.4.5** governs the letters: the state "may be indicated
        by adding the letter symbol NC *Normal closed* or NO *Normal open*
        **above the symbol and to the right**, as indicated in Figure 28". The
        figure draws it on an unfilled bowtie with the letters starting at about
        the valve's right-hand edge, clear above the run.

        The corner is fixed, not chosen from the valve's quarter turn. Reading
        the marking always in the same place is what lets someone scan a sheet
        for closed valves, and the upper right is the corner an equipment tag is
        least likely to be in already: the default tag sits centred *above*.

        This departs from PIP PIC001 4.2.2.8, which puts the letters below a
        horizontal valve and to the right of a vertical one, and which is where
        the darkened body of 4.2.2.7 still comes from. The two conventions are
        answering different questions and are taken from different sources on
        purpose: PIP is the only standard that fills a valve body, and ISO
        15519-1 is the only one that letters it. See
        :func:`pandid.render.symbols.closed_marking`.

        Where the equipment tag already reaches into that corner, the
        abbreviation steps past it rather than over it. Both are drawn on opaque
        halos in the same final pass, so the second one down would otherwise
        erase the first. ``tag_box`` is where that tag actually landed, which is
        not always the side layout picked (see :meth:`_tag_item`); it is resolved
        from the frame when a caller has not already done so.
        """
        item = (*self._label_place("top_right", x, y, u_width, u_height), "top_right", "NC")
        tag = tag_box if tag_box is not None else _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, html.escape(u.tag)))
        nc = _unit_label_box(item)
        if tag is not None and nc is not None and (
                tag[0] < nc[2] and tag[2] > nc[0] and tag[1] < nc[3] and tag[3] > nc[1]):
            lx, ly, anchor, baseline, lpos, text = item
            item = (lx + tag[2] - nc[0] + 6, ly, anchor, baseline, lpos, text)
        return item

    def _fail_label_item(self, u, f, x, y, u_width, u_height, letters, tag_box=None,
                         ink=(), symbols=()):
        """The fail position, in letters, beside the valve body.

        The letters are **ANSI/ISA-5.1-2009 Table 5.4.4** Method B, which **PIP
        PIC001 clause 4.5.3.2** requires over the standard's own Method A stem
        arrows. See :func:`pandid.render.symbols.fail_marking`.

        **PIP PIC001 clause 4.2.4.6(1)** places them, and is followed exactly:
        *"Control valve failure action abbreviation shall be shown at 0.06 inch
        directly below the control valve in horizontal lines and 0.06 inch to
        the right of the control valve in vertical lines."*

        The quarter turn therefore moves these letters, where it does not move
        the ``NC`` abbreviation (:meth:`_nc_label_item`), and the two are not
        inconsistent: they are the same principle applied to marks that live in
        different places. ``NC`` sits in a *corner*, and a corner is free
        whichever way a valve is laid, so fixing it lets a reader scan for one
        thing in one place. These letters sit against a *face*, and which face
        is free is exactly what the quarter turn changes: the face below a valve
        on a horizontal run is clear, and the face below the same valve on a
        riser is its outlet nozzle with the line running out of it. PIP's rule
        is the geometry, not a style, which is why it is taken whole.

        The remaining sides are spoken for either way. Every valve symbol here
        draws its actuator on **top** and the controller output or interlock
        lands there, so the space above the body belongs to the signal line and
        to the default equipment tag; the upper right corner is the ``NC``
        abbreviation's, fixed there by ISO 15519-1 §11.4.5. A valve stating both
        of the two things it can state about its position states them in two
        places that cannot collide.

        Where the equipment tag is already on the side the letters want -- which
        the engine chooses freely, and does choose the right-hand side for a
        valve on a riser -- the letters step past it along that same side rather
        than over it. Both are drawn on opaque halos in the same final pass, so
        the second one down would otherwise erase the first. ``tag_box`` is where
        that tag actually landed (see :meth:`_tag_item`), resolved from the frame
        when a caller has not already done so.

        A tag is not the only thing on that face, and treating it as though it
        were is issue #223: the letters then step *out* past the tag and land on
        the impulse line joining the valve to the trip square hung below it,
        which their plate deletes. So the ink and the neighbouring symbols are
        asked too, by :func:`_step_aside`, which slides the mark **along** the
        face rather than out from it -- the one direction that gets it off a
        line leaving that same face -- and holds it to half the face so PIP's
        "directly below" survives the move. ``ink`` and ``symbols`` are the
        sheet's, in the two forms :meth:`_tag_item` takes them: a mark placed
        with neither still steps past its tag and nothing else, which is what
        every caller outside a full render wants.

        The two moves compose in the order the sheet has them: out past the tag
        first, because that one is settled by a box the mark cannot share at
        all, then sideways off whatever the outward step landed on. The tag goes
        into the sideways pass's obstacles as well, so the slide cannot walk
        back onto what the step just cleared.

        This does not extend to the ``NC`` abbreviation, and the difference is
        the one :meth:`_nc_label_item` already rests on. ISO 15519-1 §11.4.5
        fixes that mark to a *corner*, and a corner has nowhere to slide to that
        is still the corner; these letters are fixed to a *face*, and a face is
        a length of paper with room along it.
        """
        # 90 and 270 both stand the run on end; 0 and 180 both leave it flat.
        upright = int(getattr(f, "orientation", 0) or 0) in (90, 270)
        lpos = "right" if upright else "bottom"
        item = (*self._label_place(lpos, x, y, u_width, u_height), lpos, letters)
        tag = tag_box if tag_box is not None else _unit_label_box(self._unit_label_item(
            u, f, x, y, u_width, u_height, html.escape(u.tag)))
        fail = _unit_label_box(item)
        if tag is not None and fail is not None and (
                tag[0] < fail[2] and tag[2] > fail[0] and tag[1] < fail[3] and tag[3] > fail[1]):
            lx, ly, anchor, baseline, lpos, text = item
            # Step along the axis the side runs off, by the overlap plus a gap.
            # Sideways is the six _nc_label_item steps by, being the same move;
            # downwards is tighter, because a halo is 15 tall against 12 of text
            # and so already carries a margin the horizontal one does not.
            if upright:
                item = (lx + tag[2] - fail[0] + 6, ly, anchor, baseline, lpos, text)
            else:
                item = (lx, ly + tag[3] - fail[1] + 4, anchor, baseline, lpos, text)
        # This unit's own box is left out for the reason _tag_item leaves it
        # out: the mark is placed a fixed clear distance off its own symbol and
        # never lands on it, and counting it would score every candidate equally
        # badly and so choose between none of them.
        others = [_obstacle(b) for v, b in symbols if v is not u]
        if tag is not None:
            others.append(tag)
        # How far along the face the letters may go: until the near edge of
        # their plate reaches the far end of the face. That is the distance at
        # which the mark stops lying against the body at all, and lying against
        # it is what attaches a mark to a symbol -- the same reading ISO
        # 15519-1 §7.2.5 asks of a line number, which :func:`_along` measures.
        # The search takes the *smallest* clearing step, so the bound is only
        # ever reached by a mark with nowhere at all to go; where that happens
        # the face is genuinely spoken for and the placement is one to make by
        # hand, as the last paragraph above says.
        plate = _unit_label_box(item)
        face, along = ((u_height, plate[3] - plate[1]) if upright
                       else (u_width, plate[2] - plate[0]))
        return _step_aside(item, (face + along) / 2, ink, others)

    def _draw_unit_labels(self, items):
        """Final pass: equipment tags on white halos, over every stream line.

        Labels are placed on a free face where one exists, but a passing stream
        (or a unit whose every face carries a nozzle) can still run behind the
        text; the halo keeps the tag legible either way. A ``center`` label
        sits inside its symbol, so it gets no halo that would erase detail.
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

    # ------------------------------------------------------------------ streams

    def _tipped(self, s, arrows: bool) -> bool:
        """Does *this drawing* put an arrowhead on the end of this stream?

        :func:`wears_arrowhead` and one thing more: a P&ID draws no heads at
        all, so ``arrows`` is false for the whole sheet. That part is a property
        of the render rather than of the stream, which is why it lives here and
        the rest lives where a caller with no renderer can reach it.
        """
        return arrows and wears_arrowhead(s, self.registry)

    def _draw_streams(self, fs, jump_direction, unit_labels, arrows=True,
                      plates=None, joints=None):
        """Draw every run, and the line numbers written on and beside them.

        ``joints`` is the sheet's :func:`sheet_connections` answer -- the joint
        every line takes unless it says otherwise, or ``None`` on a drawing that
        marks no joints at all.

        ``plates`` is an out-parameter, filled -- when a caller supplies a list
        -- with every opaque white rectangle this pass and the equipment-tag
        pass between them put on the sheet. Only the debugging overlay asks for
        it, and it asks because it is drawn *underneath* all of them: see
        :func:`pandid.render.debug.overlay`. Left ``None`` nothing is collected
        and nothing about the render changes.

        The ink this used to be handed is :func:`stream_numbers`' own business
        now: it derives the lines and the symbols from the flowsheet, so the two
        backends that ask it where a number goes cannot be given different
        answers by being given different seeds.
        """
        stream_geoms, horizontals, verticals = [], [], []
        for s in fs.streams:
            points = stream_polyline(s)
            stream_geoms.append((s, points))
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if y1 == y2:
                    horizontals.append((min(x1, x2), max(x1, x2), y1))
                elif x1 == x2:
                    verticals.append((x1, min(y1, y2), max(y1, y2)))

        lines = ['  <g id="streams">']
        for s, points in stream_geoms:
            color = s.color or "black"
            marker_id = f'arrow_{color.replace("#", "").replace(" ", "_")}'
            is_signal = s.kind in _SIGNAL_KINDS
            dash = ""
            if s.dasharray:
                dash = f' stroke-dasharray="{s.dasharray}"'
            elif s.kind in _SIGNAL_DASH:
                dash = f' stroke-dasharray="{_SIGNAL_DASH[s.kind]}"'

            d_parts = [f"M {points[0][0]},{points[0][1]}"]
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if jump_direction == "vertical" and x1 == x2:
                    crossings = [hy for mnx, mxx, hy in horizontals if mnx < x1 < mxx and min(y1, y2) < hy < max(y1, y2)]
                    crossings.sort(reverse=(y1 > y2))
                    for hy in crossings:
                        if y1 < y2:
                            d_parts.extend([f"L {x1},{hy - HOP_R}", f"A {HOP_R} {HOP_R} 0 0 1 {x1},{hy + HOP_R}"])
                        else:
                            d_parts.extend([f"L {x1},{hy + HOP_R}", f"A {HOP_R} {HOP_R} 0 0 1 {x1},{hy - HOP_R}"])
                    d_parts.append(f"L {x2},{y2}")
                elif jump_direction == "horizontal" and y1 == y2:
                    crossings = [vx for vx, my, My in verticals if my < y1 < My and min(x1, x2) < vx < max(x1, x2)]
                    crossings.sort(reverse=(x1 > x2))
                    for vx in crossings:
                        if x1 < x2:
                            d_parts.extend([f"L {vx - HOP_R},{y1}", f"A {HOP_R} {HOP_R} 0 0 1 {vx + HOP_R},{y1}"])
                        else:
                            d_parts.extend([f"L {vx + HOP_R},{y1}", f"A {HOP_R} {HOP_R} 0 0 1 {vx - HOP_R},{y1}"])
                    d_parts.append(f"L {x2},{y2}")
                else:
                    d_parts.append(f"L {x2},{y2}")
            d_str = " ".join(d_parts)

            marker = f' marker-end="url(#{marker_id})"' if self._tipped(s, arrows) else ""
            # A signal is drawn at half the weight of the pipe it reads, per
            # ISO 15519-2 Annex A.1.02/A.1.03 against A.1.01. See _SIGNAL_STROKE.
            width = _SIGNAL_STROKE if is_signal else _PROCESS_STROKE
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="{width}"{dash}{marker} />'
            )

            # The joint marks, drawn over the line rather than instead of it:
            # the pipe runs into the nozzle and the flange faces sit across it,
            # which is what P&ID_301 draws and what makes the mark read as
            # hardware on the run instead of a gap in it.
            for fx, fy, angle, _at in flange_marks(s, points,
                                                   resolve_connections(s, joints)):
                rad = math.radians(angle)
                # Along the run for the offset between the two faces, across it
                # for the bars themselves.
                ax, ay = math.cos(rad) * FLANGE_GAP / 2, math.sin(rad) * FLANGE_GAP / 2
                bx, by = -math.sin(rad) * FLANGE_TICK / 2, math.cos(rad) * FLANGE_TICK / 2
                for sign in (-1, 1):
                    mx, my = fx + ax * sign, fy + ay * sign
                    lines.append(
                        f'    <line x1="{mx - bx:.1f}" y1="{my - by:.1f}" '
                        f'x2="{mx + bx:.1f}" y2="{my + by:.1f}" '
                        f'stroke="{color}" stroke-width="{_PROCESS_STROKE}" />'
                    )

            if s.kind == "pneumatic":
                # The mark is drawn at the weight of the line it marks. A
                # supplementary symbol on a connection is a graphical symbol
                # (ISO 15519-2 Annex A.1.09, pneumatic type 433A), and
                # ISO 15519-1 §11.1.3 puts a graphical symbol at 0,1 M, the
                # same rung the signal line itself sits on. A hatch heavier
                # than its own line would read as the weightier of the two.
                for mx, my, horiz, _at in pneumatic_marks(points):
                    for off in HATCH_ALONG:
                        if horiz:
                            lines.append(f'    <line x1="{mx+off-3:.1f}" y1="{my+5:.1f}" '
                                         f'x2="{mx+off+3:.1f}" y2="{my-5:.1f}" stroke="{color}" stroke-width="{_SIGNAL_STROKE}" />')
                        else:
                            lines.append(f'    <line x1="{mx-5:.1f}" y1="{my+off-3:.1f}" '
                                         f'x2="{mx+5:.1f}" y2="{my+off+3:.1f}" stroke="{color}" stroke-width="{_SIGNAL_STROKE}" />')

        # Final pass: stream-number labels, each on a white halo so it reads
        # cleanly over any line that crosses beneath it.
        #
        # A label runs parallel to the pipe it names, turned on a vertical run so
        # it reads bottom to top and never upside down. ISO 15519-1 §5.1.5 allows
        # text read "from the bottom edge or ... from the right-hand edge of the
        # document", and this is the second of those. Its next sentence, that
        # reference designations stay horizontal "independent of symbol
        # orientation", is a rule about a symbol's own designation and does not
        # reach a connection: §7.2.5 is the clause for those, and it asks for
        # orientation *along* the connecting line. ISO 15519-1's own Figure 40
        # turns the annotation on every vertical connecting line to read bottom
        # to top, left of the line, while boxing symbol designations flat.
        #
        # What is already on the sheet is seeded as occupied so a label slides
        # clear of it. The symbols are kept apart from the rest, because they
        # are the one thing on the sheet a halo may not break: see
        # :func:`_covering`. The other boxes: equipment tags are drawn over the
        # lines, so a number parked under one would simply vanish, and each
        # label as it lands, because two streams sharing a corridor sit only a
        # few px apart, which is what a draftsman does. The lines too, every
        # routed segment and every impulse line (:func:`_ink`), since the halo
        # is opaque and a number written across a passing run deletes a length
        # of it.
        #
        # The single exception is the run the label names. Writing the number
        # *in* the line is the convention, and the halo is what opens the gap it
        # is written in, so a line collinear with the labelled segment is left
        # out of that run's seeds.
        #
        # All of which is :func:`stream_numbers`' now, and this pass only draws
        # it: the draw.io exporter has the same question to answer and had been
        # answering it by centring each number on its own edge. See that
        # function.
        placed: list[tuple[float, float, float, float]] = [
            b for b in map(_unit_label_box, unit_labels) if b is not None
        ]

        for number in stream_numbers(fs, placed, joints):
            tx, ty, name, color = number.x, number.y, number.name, number.color
            bx0, by0, bx1, by1 = number.box
            lines.append(f'    <rect x="{bx0:.1f}" y="{by0:.1f}" '
                         f'width="{bx1 - bx0:.1f}" height="{by1 - by0:.1f}" fill="white" />')
            turn = f' transform="rotate(-90, {tx:.1f}, {ty:.1f})"' if number.vertical else ""
            lines.append(
                f'    <text x="{tx:.1f}" y="{ty:.1f}" font-family="sans-serif" '
                f'font-size="{NUMBER_TYPE}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{color}"{turn}>{html.escape(name)}</text>'
            )
            if number.leader is not None:
                (ax0, ay0), (ax1, ay1) = number.leader
                # Drawn in the label's own colour, since it is part of the label
                # and not a line of its own.
                lines.append(f'    <line x1="{ax0:.1f}" y1="{ay0:.1f}" '
                             f'x2="{ax1:.1f}" y2="{ay1:.1f}" '
                             f'stroke="{color}" stroke-width="{_SIGNAL_STROKE}" />')
                lines.append(f'    <path d="{_arrowhead(*number.leader)}" fill="{color}" />')
        # ``placed`` is now every opaque plate the sheet's two label passes lay
        # down: the equipment tags it was seeded with, each line number, and
        # each leader. That is exactly the set the overlay has to dodge, and
        # this is the only point in the program where it exists.
        if plates is not None:
            plates.extend(placed)
        lines.append('  </g>')
        return lines
