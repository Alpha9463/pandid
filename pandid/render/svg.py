"""SVG rendering backend."""

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
# Balloon variants whose symbol draws a location bar across the middle
# (see the instrument symbols in pandid.render.symbols): their tag text
# has to clear it.
#
# ``shared`` carries a bar *and* a square, which is not a contradiction
# and so not a membership to tidy away (#181): ISO 15519-2 Table 1 (p.
# 7) makes the bar an "additional graphic" answering where the
# information lives, while the square answers what the function is. All
# forty balloons on ``professional_examples/P&ID_301.pdf`` carry a bar,
# twelve of them squared.
_BARRED_BALLOONS = {"panel", "aux", "shared"}
# Variants drawn as a diamond (ISA-5.1-2009 Table 5.1.1 column B and
# Table 5.1.2 items 3-5): they carry the interlock number alone, and it
# has to sit where the sloping sides leave room for it rather than in
# the middle of the box.
_DIAMOND_BALLOONS = {"sis", "logic", "interlock"}
# Variants that stand for a device out on the plant. Every ISA-5.1
# balloon but the bare circle is a *location or function* symbol saying
# the function is somewhere else: a bar puts it in a panel (Table 5.1.1
# rows 2-5), a square in the shared display (column B), a hexagon in a
# computer (column C), a diamond in a logic solver (column D and Table
# 5.1.2). Only a thing in the field can have process fluid piped to it,
# which is what decides whether the line reaching it is impulse tubing;
# see :func:`impulse_tap`.
#
# Named positively, so a location symbol added later is out rather than
# in: a dashed line claims the less of the two.
_FIELD_BALLOONS = {"default"}

#: Every side a unit's tag may be asked for, spelled the way
#: ``label_pos`` is written.
#:
#: Four faces and the middle of the box. The faces are
#: :data:`pandid.layout.coordinates.LABEL_SIDES` in the order layout
#: tries them; ``"center"`` is not a face and is not one layout ever
#: picks -- a symbol asks for it (an instrument balloon letters its tag
#: inside itself) or an author does, for a body wide enough to write
#: across.
#:
#: Public because it is the vocabulary and not the implementation, and
#: three things have to agree on it: :meth:`SvgRenderer._label_place`
#: places these five, ``pandid.render.drawio._LABEL_SIDE`` keys on the
#: same five, and :func:`pandid.validate.model_issues` refuses a sixth.
#: ``tests/test_render_api`` holds the two backends against this tuple so
#: none of the three can drift.
#:
#: ``"top_right"`` is deliberately not here. It is where §11.4.5 puts the
#: ``NC`` marking (:meth:`SvgRenderer._nc_label_item`) rather than
#: somewhere a tag may be asked for, and the draw.io backend has no key
#: for it.
LABEL_POSITIONS = ("top", "bottom", "right", "left", "center")

# --- line weights -----------------------------------------------------
# Every width this file draws in comes off :class:`~.weights.LineWeight`
# and there is no local constant to add a fourth to. Which rung each
# element is on is stated at the point it is drawn; the ladder itself,
# and why it is three rungs at 4:2:1 rather than the two this file used
# to hold, is in :mod:`pandid.render.weights`.
#
# What #490 moved is one assignment: a material run is ISO 10628-1
# §5.3.1 a) and not b). It had been drawn at the same 2 units as the
# vessel it enters -- a coherent reading of ISO 15519-2 Annex A.1, which
# spends two widths across pipeline (A.1.01) and instrument and signal
# line (A.1.02, A.1.03), but not the reading 10628-1 §5.3.1 states for
# the documents this library draws.

#: The dash a signal line is drawn with, per kind. A pneumatic line is
#: absent because it is drawn *solid* and cross-hatched instead. Held at
#: module scope because the draw.io export writes the same line, and two
#: tables of dashes would be two answers to what an electric signal
#: looks like.
_SIGNAL_DASH = {"electric": "7,4", "data": "9,3,2,3", "software": "9,3,2,3",
                "capillary": "3,3"}

#: The dash a tap line is drawn with where it carries a measurement or a
#: command rather than process fluid; an impulse line is solid. See
#: :meth:`SvgRenderer._draw_taps` and :func:`impulse_tap`. Here beside
#: the signal dashes and for the same reason: the export writes it too.
_TAP_DASH = "5,4"


#: The radius of the semicircle a crossing line hops with, which is half
#: the length of run the hop takes out and how far it stands off it.
#: :meth:`SvgRenderer._draw_streams` builds the arc from this alone.
#:
#: Named for the same reason :data:`_TAP_DASH` is, and with arithmetic
#: in the way: draw.io sizes its own hop from a ``jumpSize``, where
#: ``mxConnector.paintLine`` makes the half-extent ``(jumpSize - 2) / 2
#: + strokeWidth``. That is a different number, and
#: :func:`pandid.render.drawio._jump_size` solves it for this radius.
#:
#: **Derived from the pen since #490, because it has to be.** The paper
#: the arc leaves against the run it bridges is the radius less a
#: half-pen of each::
#:
#:     clearance = HOP_R - w_hop / 2 - w_crossed / 2
#:
#: Left at the flat 5 it was, a run widening from 2 units to
#: :attr:`~.weights.LineWeight.MAIN_FLOW`'s 4 took that from 3 units to
#: **1, 0,25 mm** -- measured on the raster, not only computed -- and at
#: that width the crescent closes: the arc, the run it crosses and the
#: corner beside it merge into one shape, and the mark states a junction
#: where there is none. A tight crossing is a defect; one that reads as
#: a tee is a false statement, so the radius follows the rung.
#:
#: :data:`_HOP_CLEARANCE` is the paper the sheet has always left there,
#: and the term added to it is a half-pen of each of two main flow runs
#: -- the widest pair that can meet -- so the clearance is a floor for
#: every crossing and exact for that one.
#:
#: **No clause sizes this**, and none is cited as if it did. §5.3.2's
#: floor is between *parallel* lines and does not reach a crossing, and
#: nothing in §5.3.4, ISO 15519-1 §12.5 or ISO 15519-2 Table A.1 gives
#: the gap a dimension. The number below restores what the drawing had
#: and claims nothing further.
#:
#: **Nor is the arc itself specified anywhere.** §5.3.4 draws an
#: interruption, 15519-1 §12.5 draws a plain crossing, and none of the
#: three reference sheets in ``professional_examples/`` marks a crossing
#: at all -- 393 of 393 interior crossings are plain. An arc is a
#: drafting convention this library brought with it, and which of the
#: three a sheet should draw is #499, with the prototype and the
#: measurements on it.
#:
#: The radius cannot simply be raised to whatever would be comfortable.
#: ``_draw_streams`` only marks a segment longer than twice it, so a
#: larger radius *drops* crossings -- 2 of the corpus's 53 at 7 and 5 at
#: 12 -- and an interruption wide enough to clear the run eats the run
#: it is cut into instead, leaving 0,25 mm stubs of pipe beside a corner
#: on this same corpus. Both conventions meet the same wall: the router
#: puts crossings within a few units of a corner
#: (``pandid.routing.separation``, whose spacing is 6 units and is
#: derived from nothing), and at 0,4 M no crossing mark of any shape
#: fits in what it leaves. That is #498.
#:
#: The two crossings that go unmarked here are drawn plain, which is
#: ambiguous where the merged arc was wrong -- the same trade
#: :data:`~pandid.render.drawio.HOP_DROPPED` already makes, and the way
#: every crossing on all three reference sheets is drawn.
_HOP_CLEARANCE = 3.0
HOP_R = _HOP_CLEARANCE + LineWeight.MAIN_FLOW.width

#: How a crossing of two unconnected runs is marked. **The author's
#: choice**, because the documents on disk do not agree on one --
#: :data:`HOP_R`'s note above sets out the reading, and #499 settled it
#: as a choice rather than a fix.
#:
#: * ``"arc"`` -- the semicircular bridge, and the default, so that no
#:   drawing already issued changes. It is in no standard this project
#:   holds and on none of the reference sheets; it is a drafting
#:   convention this library brought with it.
#: * ``"gap"`` -- the interruption ISO 10628-1 5.3.4 prescribes. Drawn
#:   over the same ``2 * HOP_R`` of run the arc spans, because no clause
#:   dimensions it and matching the arc's footprint is the one choice
#:   that invents no number and moves nothing else on the sheet. **It
#:   costs run**: the break comes out of the line rather than being laid
#:   over it, so a crossing near a corner leaves a short leg. Measured
#:   on this corpus at this radius: of the 84 resulting pieces of run,
#:   3 keep a straight leg under 1 mm -- 0,15 mm at the worst, on
#:   ``11_ethanol_pid`` -- and the shortest whole piece is 1,5 mm. The
#:   arc meets the same wall from the other side (it drops 1 of 50
#:   crossings), and both are the router putting crossings within a few
#:   units of a corner, which is #498.
#: * ``"plain"`` -- both lines continuous, as ISO 15519-1 12.5 Figure 31
#:   draws a crossing and as all 393 interior crossings on the reference
#:   sheets are drawn. A junction is then told from a crossing by the
#:   *junction* carrying a mark, which is the other way round from the
#:   two above.
#:
#: The choice is the **sheet's** and not the line's: a drawing that
#: marked some crossings one way and some another would teach its reader
#: a convention and then break it, which is worse than either. See
#: :func:`check_crossing_style`.
CROSSING_STYLES = ("arc", "gap", "plain")

#: What a crossing is drawn as when the author says nothing.
#:
#: ISO 10628-1 5.3.4 asks for an interruption and describes no other mark,
#: and 4.1 puts every diagram this package draws -- block, PFD and P&ID
#: alike -- under Clause 5, so the rule does not vary by diagram type.
#: The arc is a drafting convention this library brought with it and no
#: document here specifies; it stays available because a house style may
#: want it, but it is no longer what a sheet gets by default.
#:
#: Every signature that takes ``crossing_style`` defaults to this value,
#: and ``test_every_crossing_style_default_is_the_package_default``
#: fails if one of them drifts.
CROSSING_STYLE_DEFAULT = "gap"

# --- stream-label placement -------------------------------------------
# A stream label is written on an opaque halo, so it can only sit *on*
# the pipe where the run leaves pipe showing at each end: the ARROWHEAD
# a PFD draws, plus enough line either side that the run still reads as
# one line rather than two stubs. Anything shorter goes beside the pipe.
_LABEL_CLEAR = 20.0
# Gap from the pipe to the near edge of a label written beside it.
_LABEL_GAP = 4.0
# Search step along the run. Fine, because a label only has to clear
# whatever it landed on rather than jump a whole label width.
_LABEL_STEP = 6.0
# How many bands of sideways stand-off the search may walk through. A
# bound on the search rather than a judgement about what reads: the
# bands are walked inward-out and a clear band wins outright, so the
# number only matters to a label whose nearer bands are all spoken for.
#
# Seven because six left one label on the shipped corpus with nowhere to
# go -- AE-304 on ``11_ethanol_pid``, whose 276 candidate spots all
# covered something once a halo stopped being allowed to break a symbol
# (:func:`_covering`) -- and its first clear band is the seventh. The
# answer settles there rather than merely first appearing there: at 8,
# 10 and 12 bands that label lands in the same place.
_LABEL_BANDS = 7

def _class_weight(sym) -> LineWeight:
    """The rung *sym*'s outline is drawn on.

    :attr:`~.symbols.Symbol.trim` is the flag that says which, and it
    says it for exactly ISO 10628-1 §5.3.1 c)'s class -- valves,
    fittings, piping accessories and PCE symbols -- against §5.3.1 b)'s
    equipment and machinery for everything else.

    ISO 15519-1 §11.1.3 applies to both rungs alike. :func:`_nominal`
    holds every artwork in the registry to one nominal weight whichever
    rung it is placed on, so a class is one number for the whole class
    rather than a property of any one drawing, and the division to the
    finer rung happens once at render time (see :meth:`SvgRenderer._defs`).
    """
    return LineWeight.DETAIL if sym.trim else LineWeight.EQUIPMENT


def _stream_rung(signal: bool) -> LineWeight:
    """The rung a run is drawn on.

    ISO 10628-1 §5.3.1 a) for a material run and c) for a control or
    data line -- the *whole* of what either backend has to decide about
    a stream's width, in one place, because both of them ask here.

    A material run is drawn on a) rather than b) and the clause offers
    no third answer for it: b)'s flow-line class is the *subsidiary*
    one, and this library has no way for an author to call a run
    subsidiary (see #497). Every material run is therefore a main flow
    line, which is what #490 changed -- they had all been drawn on b),
    at the weight of the equipment they run into.

    This is also the seam #489 attaches at: an energy carrier is
    §5.3.1 b), so it is one branch here and :attr:`~.weights
    .LineWeight.EQUIPMENT`, with no new rung and nothing else to move.
    """
    return LineWeight.DETAIL if signal else LineWeight.MAIN_FLOW


def _ink_pad(rung: LineWeight) -> float:
    """How far off a line drawn on *rung* an opaque plate has to stop.

    Half a pen of ink and one unit of paper beyond it; see the call in
    :func:`_ink`, which is where the two halves are argued.
    """
    return rung.width / 2 + LineWeight.DETAIL.width


#: The paper a label's opaque plate leaves outside a symbol's ink.
#:
#: **A symbol's box is not its ink**, which is the whole of issue #243.
#: :func:`~pandid.portgeom.unit_box` reports the *geometry*, and an
#: outline is stroked centred on it, so half the pen falls outside the
#: box and a plate laid flush against the box covers exactly that half.
#: Measured on the shipped ``examples/14``: V-604's left shell wall
#: integrated 1.141 of ink for the forty pixels ``VAP-611-150-40-CS``'s
#: plate ran beside it against 2.345 the row after it ended -- 48,7 % of
#: its weight gone, with nothing in the drawing to say why.
#:
#: A clearance rather than a bare half-pen, since half the pen is where
#: the plate stops *erasing* and this is where it stops *crowding*: the
#: same division :func:`_ink` already makes for a pipe.
_PLATE_CLEARANCE = 2.0


def _obstacle(box) -> "tuple[float, float, float, float]":
    """A symbol's drawn box, grown to what a label has to keep off.

    Every place that treats a unit as something a label may not land on
    goes through here, so the two label passes -- the equipment tags in
    :meth:`SvgRenderer._tag_item`, the line numbers and their leaders in
    :func:`stream_numbers` -- cannot disagree about where a symbol ends.
    The growth is applied where the boxes are *used* rather than where
    they are built, because the draw.io exporter builds a list of its
    own and hands it to ``_tag_item``.

    Held to :attr:`~.weights.LineWeight.EQUIPMENT`, the heavier of the
    two symbol rungs, whatever *box* was actually drawn at. This is a clearance
    around a box that already grew to the ink (see :data:`_PLATE_CLEARANCE`),
    not the ink's own measurement, so an obstacle for a valve or a
    balloon a half-pen too generous never puts a label nearer real ink
    than it draws -- only ever ekes it a little further off a trimmed
    symbol than :attr:`~.weights.LineWeight.DETAIL` strictly requires. Threading which
    class each box was drawn in through every caller here, several of
    which build their list from mixed geometry (a flange mark has no
    :class:`~.symbols.Symbol` at all), would buy nothing a reader could
    see.
    """
    pad = LineWeight.EQUIPMENT.width / 2 + _PLATE_CLEARANCE
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _along(box, vertical: bool, lo: float, hi: float) -> bool:
    """Is a label at *box* written **along** the run ``lo``..``hi``?

    ISO 15519-1 §7.2.5, on the reference designation of a connection,
    orients it along or beside the connecting line it belongs to, and
    where there is no room beside that line it goes elsewhere in the
    content area with a leader drawn back to it.

    Two *shall*s, the second naming the only escape from the first, so
    this is where *along* stops and :func:`_leader` takes over. It asks
    the one question the clause turns on -- is the line *there*, beside
    the words? -- and not how wide the paper between them is.

    More than half, measured over all 286 line numbers on the 21
    shipped sheets: 25 overrun their run at all, and they fall in two
    groups with a clear band of nothing between, 21 from 60 % of the
    string alongside its own line up to 98 %, and four -- the ones
    below this function's own 50 % line, which is what actually earns
    a leader -- at 18 %, 29 %, 34 % and 36 %. The band has narrowed as
    the corpus grew: 40 % to 61 % over fourteen sheets, measured at
    ``87935d6``, and 32 % to 74 % over twelve, at ``07cb3b3``. Those
    two are cited and not re-derivable -- the corpora they were taken
    over are gone -- but they are what says the band is narrowing, and
    a sheet that lands a number *in* today's band is the signal this
    threshold has stopped sorting them. The two checks in
    ``tests/test_label_invariants.py`` that read the corpus are what
    would say so.
    """
    a, b = (box[1], box[3]) if vertical else (box[0], box[2])
    return min(b, hi) - max(a, lo) > (b - a) / 2


def _slide(x: float, y: float, room: float, vertical: bool):
    """Anchors along a run: centred first, then out either way."""
    yield x, y
    for k in range(1, int(room // _LABEL_STEP) + 1):
        d = k * _LABEL_STEP
        yield (x, y - d) if vertical else (x - d, y)
        yield (x, y + d) if vertical else (x + d, y)


# --- the ink a halo would delete --------------------------------------
# Every label is written on an opaque rect, so wherever one lands it
# erases what was drawn under it -- and the ink is not just the symbols,
# it is every routed segment and every impulse line. A halo that deletes
# a length of somebody else's pipe says two things that are not true,
# that the line stops there and that the gap is where a reader may
# write, and neither is visible to the validator, whose topology is
# untouched. So the lines are seeded as occupied alongside the boxes.


class _Ink(NamedTuple):
    """A drawn line, as the rectangle its stroke covers.

    ``axis``/``at`` name the infinite line it lies on (``"h"`` at a
    ``y``, ``"v"`` at an ``x``), which is how a label tells its own run
    from a line that merely crosses it: breaking the run you are
    labelling is the convention, and breaking the one beside it is a lie
    about that line.

    ``line`` is whose it is, and it is the rest of that answer. Two
    different runs at one height are collinear and are still two runs,
    so a number gathering "its own" length by ``axis``/``at`` alone
    gathers the neighbour's as well -- and reads as written along a line
    it has nothing to do with. Empty for an impulse line, which is
    nobody's run.
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
        """The covered rectangle, as every collision test takes it."""
        return (self.x0, self.y0, self.x1, self.y1)


def tap_lines(fs):
    """Every impulse line, as ``(instrument, tap, balloon centre)``.

    The line from a tap to the balloon reading it, and the rule for when
    there is one at all: nothing is drawn where the balloon is merely
    *placed* against its host (``near=``, issue #137; see
    :data:`~pandid.units.RELATIONS`), where a stream already joins the
    two, or where the element sits directly on the line (``offset=0``).

    One derivation, shared by the drawing pass, by label placement and
    by the draw.io exporter. A label cannot then be placed against an
    impulse line the renderer declines to draw, or over one it does; and
    these are the only lines on a P&ID that are not streams, so an
    exporter walking ``fs.streams`` alone left 13 of
    ``11_ethanol_pid``'s 29 balloons floating unconnected -- the rest
    already touch a stream of their own (a signal wire to another
    instrument) and were never at risk.
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
    """Is the line from *inst* to its host impulse tubing?

    The question is about the **edge**, not about the class of either
    thing on the end of it. An impulse line is a piece of pipe: it
    exists only where there is process fluid at one end and something
    out in the plant to pipe it to at the other. So both ends are asked,
    and each answers out of a fact the model already states.

    *The host end* carries fluid unless it carries a measurement
    instead: a balloon holds nothing at all, and a signal line holds a
    command. Everything else a balloon may hang on -- a process line, a
    vessel, an exchanger, an in-line element -- is full of the fluid the
    reading is taken from.

    *The balloon end* can receive it only where the balloon is a device
    in the field. Every other ISA-5.1 balloon is a symbol for a function
    in a panel, in the shared display, in a computer or in a logic
    solver, and no tubing runs from a drum to any of those; see
    :data:`_FIELD_BALLOONS`.

    *The line itself* has to be carrying the reading. Tubing brings the
    fluid **to** the instrument, so only a ``sensing`` relation can be
    one; a trip square hung on the valve it strokes is ``acting_on``,
    and what runs down to the actuator is a command.
    """
    host = getattr(inst, "host", None)
    host_kind = getattr(host, "kind", "")
    holds_fluid = (host is not None and host_kind != "instrument"
                   and host_kind not in _SIGNAL_KINDS)
    return (holds_fluid
            and getattr(inst, "relation", "sensing") == "sensing"
            and getattr(inst, "variant", "default") in _FIELD_BALLOONS)


# --- letter codes written outside the symbol --------------------------
# ISO 15519-2 §5.1.3, p. 19, puts anything written outside a PCI symbol
# in the four quadrants around it, drawn at Figure 8, and gives the
# reason: doing so leaves the symbol free to be connected horizontally
# and vertically.
#
# The quadrants are the *corners*, and that reason is why: N, S, E and W
# stay clear for the four connections a balloon takes, so annotating one
# spends no face (#253).
#
# §5.2.5 fixes the *vertical* half -- the value a code stands for rises
# with its distance from the centre line, so a high function is above it
# and a low one below -- and does not fix which side of the symbol the
# pair goes on.
# ``professional_examples/P&ID_301.pdf`` bears that out: all three of
# its annotated controllers put their alarms on whichever side has room.
# So a pair keeps its half of the symbol and takes whichever side reads.
# The four are (a) references and safety identifiers with (b) the
# measured-variable type for letter code U, and (c) high functions with
# (d) low.

#: Each quadrant as ``(side, away)``: which way from the symbol it sits,
#: and which way a second code in it stacks. Both are +1 right/down.
_QUADRANTS = {"a": (-1, -1), "b": (-1, 1), "c": (1, -1), "d": (1, 1)}

#: The two pairs, in the order they are placed, and the side each
#: prefers. Placed as pairs because they are read as one: a high code
#: over a low one is a column.
_QUADRANT_PAIRS = ((("a", "b"), -1), (("c", "d"), 1))

#: Paper left clear on the symbol's centre line, each side. A connection
#: arrives there -- on ``professional_examples/P&ID_301.pdf`` the signal
#: line into every annotated controller runs between the two alarm codes
#: -- so the band keeps the pair straddling the line, not sitting on it.
_QUADRANT_BAND = 3.0
#: From the symbol's drawn edge to the near edge of the code. 0,12
#: balloon diameters, which is what PIC-301 and LIC-304 are drawn at
#: (0,142 and 0,085); TIC-302's 0,384 is the outlier and the three
#: together are hand-placed.
_QUADRANT_GAP = 5.0
#: Between two codes stacked in one quadrant: one line of type, so the
#: halos touch and the pair reads as a block.
_QUADRANT_PITCH = 15.0
#: How far outward the search may push a quadrant to find clear paper.
#: The quadrant itself is what the code *means*, so the only freedom is
#: the stand-off; past this the placement is one to make by hand.
_QUADRANT_REACH = 60.0


def quadrant_labels(fs, direction: str) -> list:
    """Every letter code written outside a symbol, placed.

    Items in :meth:`SvgRenderer._draw_unit_labels`' own form, so the
    codes are haloed and drawn over the lines exactly as a tag is.

    Derived from the flowsheet alone, for the reason
    :func:`stream_numbers` is: the tag pass and the line-number pass
    both have to dodge these, and a second derivation would put them
    somewhere else for one of the two.
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
            # The preferred side first, so a tie keeps it; the other
            # only wins by being cleaner, which is the draughtsman's own
            # reason to swap.
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
            # Each code is paper for the next pair, and for the next
            # balloon's: two controllers a balloon apart annotate into
            # the same gap, and the second has to see where the first
            # landed.
            symbols += [b for b in map(_unit_label_box, best[1]) if b is not None]
    return out


def _quadrant_block(box, codes, side: int) -> list:
    """One side's codes, laid out from the symbol's box outward.

    ``codes`` is the pair keyed by quadrant letter; which of the two is
    above the centre line and which below is :data:`_QUADRANTS`', and
    does not change with the side.
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
    """How far out of the symbol a pair's codes stand, and what is left.

    Returns ``(shift, damage)``. Outward only, and the whole pair moves
    together: the codes are a block whose order is the standard's, and
    outward is the only direction that leaves each in its own quadrant.

    Scored with :func:`_erases`, so a code gives things up in the order
    every other label does, and the smallest clearing step wins, which
    keeps a code hard against its own symbol where the paper is clear.
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


def _ink(fs, direction: str) -> "list[_Ink]":
    """Every line the sheet draws, as the rectangle its stroke covers.

    Padded by a whole stroke width: half is the ink itself, drawn
    centred on the path, and half the margin that stops a halo shaving
    the edge of a line it only just reaches, since a run clipped to nine
    tenths of its weight reads as a fault rather than as a line.

    The paths come from :func:`~pandid.layout.attach.stream_path`, which
    is what :meth:`SvgRenderer._draw_streams` draws, so what is dodged
    here is what lands on the sheet.

    **And the hops, which are in no route at all.** Where one run
    crosses another the sheet draws a semicircle standing off the line
    (:func:`stream_hops`), and this function used to measure the
    straight path underneath it and stop there. A plate half a unit
    clear of the run was therefore free to take a bite out of the arc
    over it, and did: ``S-934``'s number cut ``S-939``'s hop in two on
    ``21_alumina_refinery``, on ``main`` and at every setting of
    ``fs.stream_labels.enclosure``. That is the worst mark on the sheet
    to break, since a hop exists only to say *these two lines cross and
    are not joined* and half a hop says they are joined. ``direction``
    is :meth:`SvgRenderer.render`'s ``jump_direction`` and is what
    settles which of the two runs draws the arc; it is required rather
    than defaulted, because a pass that guesses it dodges the arcs of a
    drawing nobody asked for.
    """
    from pandid.layout.attach import stream_path

    out: list[_Ink] = []

    def add(a, b, pad: float, kind: str, line: str = "") -> None:
        (ax, ay), (bx, by) = a, b
        if abs(ax - bx) < 0.5 and abs(ay - by) < 0.5:
            return  # a zero-length hop between coincident points draws nothing
        axis, at = ("v", (ax + bx) / 2) if abs(ax - bx) < abs(ay - by) else ("h", (ay + by) / 2)
        out.append(_Ink(min(ax, bx) - pad, min(ay, by) - pad,
                        max(ax, bx) + pad, max(ay, by) + pad, axis, at, kind, line))

    for s in fs.streams:
        # Half the pen is the ink itself; the unit beyond it is paper
        # a halo may not crowd. Two quantities, and stated as two
        # since #490: written as the whole pen they were one number,
        # which read correctly only while every rung's clearance
        # happened to equal its own half-pen. Widening the main flow
        # rung would then have doubled a clearance nothing asked to
        # move -- the same slip as :data:`_LEADER_HEAD`, a step
        # further from the pen.
        #
        # One unit of paper because that is the finest rung on the
        # ladder: the narrowest thing this sheet can draw, and so the
        # narrowest gap that reads as a gap rather than as a join. It
        # is what a main flow line already stood off at, and it is the
        # same division :data:`_PLATE_CLEARANCE` makes around a symbol
        # -- half a pen of ink, then a clearance with its own name.
        pad = _ink_pad(_stream_rung(s.kind in _SIGNAL_KINDS))
        points = stream_path(s)
        for a, b in zip(points, points[1:]):
            add(a, b, pad, "pipe", s.name or "")
    for _u, tap, centre in tap_lines(fs):
        # A tap is §5.3.1 c) too, and stands off by the same rule.
        add(tap, centre, _ink_pad(LineWeight.DETAIL), "tap")
    # A hop belongs to the run that draws it, and `line` says so: to
    # every *other* label on the sheet it is somebody else's ink, which
    # is the whole of the fix. `axis`/`at` name the run it stands on and
    # not the offset arc, so a label reading its own run's length
    # (`_along`) counts the hop as part of that run, which it is.
    # `kind` is its own word so a reader can tell one from a straight
    # length; `_erases` scores it with the pipes, which is where a
    # broken one belongs. Padded off the hopping run's own rung, the
    # same way its straight length is: the arc is drawn at that weight.
    for hop in stream_hops(fs, direction):
        run = fs.streams[hop.stream]
        pad = _ink_pad(_stream_rung(run.kind in _SIGNAL_KINDS))
        x0, y0, x1, y1 = hop_box(hop, pad)
        out.append(_Ink(x0, y0, x1, y1, "v" if hop.vertical else "h",
                        hop.x if hop.vertical else hop.y, "hop", hop.line))
    return out


def _meets(box, region) -> bool:
    """Do two rectangles share any area?

    Touching edge to edge does not count: the padding a line already
    carries is what keeps a halo off it.
    """
    return (box[2] > region[0] and box[0] < region[2]
            and box[3] > region[1] and box[1] < region[3])


def _erases(box, ink, symbols=()) -> "tuple[int, int, int]":
    """What a halo at *box* deletes: symbols, impulse lines, pipe.

    Ordered, because the three are not worth the same. A line broken by
    a halo is still that line, and the reader reads across the gap --
    which is why writing a number *in* a run is a convention at all. An
    impulse line is the only mark saying *where* a transmitter measures
    and is a couple of centimetres long, so a break takes more of it.

    A **graphical symbol** is worse than either, and is first for that
    reason: its outline is what identifies it -- ANSI/ISA-5.1 draws an
    instrument as a circle and a shared display as a circle in a square,
    and the difference is the outline -- so a bite out of a balloon
    replaces one symbol with a shape that is in neither standard. (The
    square is ISA's: ISO 15519-2 §5.1.1 has a circle and an extended
    circle and nothing else, and neither of its two encodes function.)
    On
    ``11_ethanol_pid`` D-301's tag ate the upper-left of LT-304's
    balloon and HV-301C's the left edge of PIC-301's square, both
    because nothing here had been told a symbol was there.

    Comparing these tuples is what does the stepping, so the order above
    is the order a tag gives things up in.
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
    """What a halo at *box* covers: symbols, then everything else.

    Two numbers and not one, for the reason :func:`_erases` orders its
    three: covering a symbol is not a worse version of covering a line
    but a different and heavier kind of damage. Counted together, a
    label a band closer to its own run could buy that place with a
    stripe out of a heat exchanger's tube bundle and win, because one
    box is one box.

    Counting of the second kind stops once the pair is already worse
    than *limit*, the best score so far, since the search only needs to
    know whether a spot is worse than the one it is holding. That is
    what keeps scoring every anchor on a crowded sheet affordable.
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
    """Slide a valve's position mark along its own face until it takes
    nothing away, and return where it ended up.

    Issue #223: the mark had one thing it stepped past, the equipment
    tag, and a face has three. ``examples/14``'s XV-601 hangs its trip
    square below the valve and fails closed, so PIP PIC001 4.2.4.6(1)
    puts ``FC`` directly below the body and the square's impulse line
    leaves the same face for the same place -- and the letters' plate is
    opaque and drawn last. ISO 15519-2 §5.1.1 makes that connection a
    *shall*, and it is a couple of centimetres long, so a bite out of it
    is the whole statement.

    **Along the face, and not out from it**, which is the one thing this
    does that the tag step above it does not. Out is what clears a tag,
    which is centred on the face and as wide as the symbol; it is no use
    against an impulse line, which leaves that same face and runs the
    way the mark would be going, so the letters follow it down however
    far they are pushed.

    The candidates are the exact distances that clear each obstacle by
    :data:`_PLATE_CLEARANCE`, which is #243's answer to the same
    question asked of a line number's plate. The nearest one
    :func:`_erases` scores clear wins, so the mark moves as little as
    the paper allows and the base position is kept where it is already
    clear. A tie -- which a plate astride a line produces every time,
    the two ways round being the same distance -- goes right and down,
    the way the tag step goes.

    *room* is how far the caller will let it go, and is not the tag's
    bound of half a face (:meth:`SvgRenderer._tag_item`): two letters
    against a 24-unit valve body are a plate 21 wide on a face 24 long,
    and no position in that half-face band clears a line down the middle
    of it.
    """
    box = _unit_label_box(item)
    if box is None or not (ink or others):
        return item
    lx, ly, anchor, baseline, lpos, text = item
    # Which way the face runs, not which way the label was pushed out
    # along it: a left or right face runs up and down, so it slides in
    # y.
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
    """Where an ``hw`` x ``hh`` label may go on a run, best first.

    Yields ``(x, y, off)``: the anchor, and the perpendicular stand-off
    from the run that put it there, which is what the outermost band is
    counted in. Whether the label needs a leader is :func:`_along`'s
    separate question.

    On the pipe only while the run can still show clear line at each
    end; then beside it (above a horizontal run, left of a vertical
    one), then the far side, then further out. Each is slid along the
    run in turn, so the label leaves the pipe before it leaves the
    neighbourhood of its own line. Above and left is the side ISO
    15519-1 §7.2.5 asks for, as a ``should``; on the pipe comes first
    anyway, a dozen-character line number costing the sheet more room
    beside the run than on it.

    On the pipe the label has to stay within the run, clearance and all.
    Beside it, it erases nothing, so it may slide until its near edge
    reaches the run's end -- far enough to get out from under a symbol
    the run butts into, and no further.

    ``on_run`` is the label that may not leave its line at all, which is
    what an enclosure asks for (#480). Both of the rules above are then
    suspended: the run's clear length no longer decides whether the
    label may sit on it, and the bands beside it are never offered. A
    diamond's whole grammar is *the run passes through me*, so one
    written beside the line, or out on a leader, is a symbol a reader
    cannot identify -- while one that will not fit is merely crowded,
    and crowding is the author's to fix by spacing the sheet. The slide
    that is left is what lets the search still dodge; where even that is
    spent, :data:`_slide` yields the centre alone and the label stays
    there.

    ``plate`` is how much of the label *along the run* is opaque, where
    that is less than the whole of it: the words inside an enclosure,
    the enclosure itself being an outline the run is seen straight
    through (:func:`_enclosure_svg`). The slide is bounded by it rather
    than by ``hw``, and that is one rule and not two -- what has to keep
    clear line at each end is the paper the label paints, because that
    is the only part of it a reader could take for the end of the run.
    Bounding the slide by the shape instead leaves every label whose
    shape outruns its segment -- 70 of the 286 on the shipped corpus at
    ``"diamond"`` -- with no slide at all, pinned to the middle of the
    segment whatever happens to cross there, which is where four of the
    corpus's thirteen covered plates this branch started with came
    from.
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
# ISO 15519-1 §6.4 gives a leader three terminators and picks between
# them by where the leader lands: a dot inside an object, an arrowhead on
# the outline of an object or on a connection, an oblique stroke across
# several parallel connections. A line number's leader ends on a
# connection, so it wears an arrowhead, and Figure 4 c) draws the leader
# itself *oblique*, running down onto a plain horizontal connecting line
# with the text at its upper end.
#
# The slope is load-bearing. §12.1 holds the connecting lines -- pipes,
# mechanical links, conductors, functional connections and the rest --
# to horizontal or vertical, and it is being oblique that keeps a leader
# from being read as one of those, which is why
# tests/test_route_invariants.py sweeps streams and impulse lines and
# not this.
#
# The head is ambiguous against the sheet's own flow marker, and
# knowingly so: both are a solid filled triangle, this one at 1,8 times
# the size, with nothing else telling them apart. §6.4 offers no other
# terminator, so what pays the ambiguity down is drawing fewer leaders
# -- §7.2.5 wants the number along its line and treats the leader as
# what to do when that is impossible. See :func:`_along`.

# Half the sheet's flow arrowhead: §6.4 hands the leader to ISO 128-22,
# where it is a narrow line, and a terminator heavier than the line it
# ends would read as the weightier of the two. Same proportions as the
# flow head, so the two are one drawing at two sizes.
#
# A *size*, and half outright. It was written as the ratio between two
# line weights that happened to stand at 2:1, which made a glyph's size
# a function of a width -- so #490's widening of the main flow rung
# would have shrunk this head to a quarter of the flow head without
# anything in the drawing asking it to. A width and a size are
# different quantities and this is the one place they were tied.
_LEADER_HEAD = ARROWHEAD / 2


#: A crossing the sheet could not mark. See :func:`unmarked_crossings`.
CROSSING_UNMARKED = "crossing-unmarked"


def unmarked_crossings(fs, jump_direction: str = "vertical",
                       crossing_style: str = "gap") -> list:
    """Every crossing of two unconnected runs the sheet draws **bare**.

    A crossing is marked by breaking one of the two runs over the other
    across :data:`HOP_R` either side of it
    (:meth:`SvgRenderer._draw_streams`), and the run that carries the
    mark needs that much of itself either side of the crossing for the
    mark to sit on rather than overhang. Where it has less, no mark is
    drawn and the two runs are laid down straight through each other.

    **One answer for two of the three styles.** The arc and the
    interruption occupy the same ``2 * HOP_R`` of run, so a crossing has
    the room for one exactly when it has the room for the other, and
    :data:`CROSSING_STYLES` changes only the noun in the sentence
    :func:`_crossing_issues` writes. ``"plain"`` returns nothing: a
    sheet that marks no crossing anywhere drew every one of them the way
    it said it would, and a finding against each would be a finding
    against the option rather than against the drawing.

    **That is not a neutral fallback on this sheet.** A drawing on which
    every other crossing carries an arc has taught its reader that a
    crossing looks like an arc, so a bare one does not read as "no
    information" -- it reads as the other thing, a junction. The
    reference sheets get away with drawing every crossing bare because
    they draw *all* of them bare and mark the junctions instead; a sheet
    that does both cannot borrow that. So the sheet says so rather than
    leaving the reader to find it: :meth:`SvgRenderer.render` turns each
    of these into a :data:`CROSSING_UNMARKED` warning naming both runs
    and the point.

    Returns ``(marked, crossed, x, y)`` per crossing, where *marked* is
    the run that would have carried the arc. The room test is the one
    ``_draw_streams`` applies, and ``tests/test_render.py``'s
    ``test_a_hop_has_room_for_its_own_arc`` holds the two to agreeing:
    it counts the arcs actually drawn against the crossings that have
    room, so a drift here shows up there.

    Widening a run is what made this worth reporting -- at 0,4 M an arc
    needs more room than it did (see :data:`HOP_R`) -- but the condition
    is older than #490 and the count on the shipped corpus is 2 of 53.
    Giving those two the room is the router's to do, and is #498.
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
    """:func:`unmarked_crossings`, worded for the reader of the sheet.

    The mark is named as the sheet drew it, and the cure has gained a
    second half since #499: where the router has left no room, drawing
    every crossing plain is the honest answer, and it is the one that
    keeps the sheet reading by a single convention throughout.
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
    """Does the segment *start* -> *end* pass through *region*?

    Liang-Barsky, and strict at the ends for the reason :func:`_meets`
    is: a leader that grazes the edge of a box is not cutting through
    it.
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
    """How many of *occupied* a leader cuts, counted to *limit*.

    A leader is new ink on a sheet already too crowded to write the
    number beside its line, so it is scored the way the label is: one
    running through the vessel the label stepped around has moved the
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

    Returns ``((start, end), crossings)``: the leader, the end being the
    point on the run the arrowhead lands on, and how many of *occupied*
    it cuts through.

    Every candidate leaves the halo's **near face** and lands 45 degrees
    away along the run -- the slope Figure 4 draws. Leaving from the
    label rather than aiming at a fixed point on the run is what makes a
    leader *move* when the search slides the label along; pinned to the
    run, every anchor in a band produced the same leader.

    The tail is swept along that face and scored, in this order:

    **What it cuts**, first, for the reason the halo dodges anything at
    all. The strip of paper directly between a label and its run is
    often the congestion that pushed the label out, so a leader dropping
    out of the middle of the face is aimed straight into it and one
    leaving from nearer an end takes it around.

    **How near 45 degrees it lands**, second. It is the same slope on
    every leader on the sheet, so a reader learns the mark once.

    **How near the middle of the face it starts**, last. A halo is
    measured at 6,2 per character plus padding, which over-measures a
    string as hyphen-heavy as a line number by the better part of a
    character at each end, so its corners are blank paper and a tail
    landing there does not touch the words at all. The sweep is inset
    from the corners by half the halo's thickness, about one character
    at this size.

    The landing point is kept off the ends of the run, since those are
    where it meets the equipment it serves and a head there points at
    the vessel as readily as at the pipe -- the very reading the clause
    exists to prevent. The clearance is ``_LABEL_CLEAR``, or a third of
    the run where the run is too short to give that much; where the
    clamp bites the leader comes in shallower than 45 degrees, which is
    still oblique, and the second key spends the sweep's freedom getting
    back towards 45.

    ``keep_out`` extends that clearance by whatever the run's ends are
    *marked* with, and is the same clause rather than a new one: on a
    flanged sheet the joint is drawn, so landing on it points at the
    joint exactly as landing at the end points at the vessel. Measured
    off the run's ends before the inset, which is what lets a short
    spool with a flange pair at each end put the head in the clear
    middle.
    """
    (sx1, sy1), (sx2, sy2) = seg
    vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
    # Everything below is in the run's own frame -- *u* along it, *v*
    # across -- so one arithmetic serves a horizontal run and a
    # vertical.
    lo, hi = ((min(sy1, sy2), max(sy1, sy2)) if vertical
              else (min(sx1, sx2), max(sx1, sx2)))
    at = (sx1 + sx2) / 2 if vertical else (sy1 + sy2) / 2
    u0, u1 = (box[1], box[3]) if vertical else (box[0], box[2])
    v0, v1 = (box[0], box[2]) if vertical else (box[1], box[3])
    v = v0 if abs(v0 - at) < abs(v1 - at) else v1
    gap = abs(v - at)
    # Only where the run can spare it: a band inverted by its own
    # clearance would put the head off the run altogether.
    if keep_out and hi - lo > 3 * keep_out:
        lo, hi = lo + keep_out, hi - keep_out
    inset = min(_LABEL_CLEAR, (hi - lo) / 3)
    near, far = lo + inset, hi - inset

    def route(s: float):
        """The leader leaving the near face at *s*, 45 degrees along.

        Both directions along the run are offered and the one landing
        *furthest* from ``s`` wins, which is the same as the one nearest
        45 degrees: an unclamped landing is exactly ``gap`` away, and
        clamping to the run can only bring it closer in.
        """
        u = max((min(max(s + d * gap, near), far) for d in (1.0, -1.0)),
                key=lambda c: abs(c - s))
        return ((v, s), (at, u)) if vertical else ((s, v), (u, at))

    # The face, inset at each end so the tail lands on the lettering
    # rather than the halo's padding, never past a quarter of a short
    # one.
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
    """Every point a stream's line is drawn through, ends included.

    The route's waypoints are the middle of the answer and not the whole
    of it: a route runs between two *anchors* on the units' bounding
    boxes, and what gets drawn runs between the two nozzles those
    anchors stand for. So the ends come from
    :func:`~pandid.portgeom.port_point` and the waypoints go in between.

    Collinear middle points are dropped. The router emits a point per
    grid step it turned at, and three points on one straight length are
    harmless as ink but not as *structure*: every consumer downstream
    asks how long a segment is -- the stream label picks the longest to
    write itself in, a draw.io edge carries one waypoint per real turn
    -- and a run chopped into pieces answers wrongly.

    Lifted out of the SVG renderer so the draw.io exporter draws the
    same line rather than a second opinion about it.
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


class _Hop(NamedTuple):
    """One line jump: the crossing it stands over, and who draws it.

    ``x``/``y`` is the point on the **hopping** run the semicircle is
    centred on, ``vertical`` says that run is the vertical one, and
    ``side`` is which way the arc leaves it -- ``+1`` towards greater
    x (or y), ``-1`` the other way. ``stream``/``seg`` index the run and
    the segment of :func:`stream_polyline` carrying it, which is what
    lets the renderer take one segment's hops in the order it draws
    them.

    ``line`` is the hopping run's number, and it is the field the
    label search turns on: a hop is drawn as part of *that* run, so to
    every other label on the sheet it is somebody else's ink.
    """
    x: float
    y: float
    vertical: bool
    side: float
    stream: int
    seg: int
    line: str


def stream_hops(fs, direction: str) -> "list[_Hop]":
    """Every line jump the sheet draws, in the order it draws them.

    Lifted out of :meth:`SvgRenderer._draw_streams` for the reason
    :func:`stream_polyline` was, and for a second reason that cost the
    drawing a run: the hop is the one piece of a line whose geometry is
    **not** in the route. :func:`_ink` measured the straight path and
    nothing else, so a plate could sit clear of the run by half a
    millimetre and still take a bite out of the arc standing over it --
    which is what happened to ``S-939``'s hop under ``S-934``'s number
    on ``21_alumina_refinery``, on ``main`` and at every setting of
    ``fs.stream_labels.enclosure``. A hop is the worst thing on the
    sheet to erase: it exists solely to say *these two lines cross and
    are not joined*, and cut in half it says the opposite. So the
    derivation is one function, and the pass that draws it and the pass
    that dodges it read the same answer.

    **Which run hops** is ``direction``: a vertical segment crossing a
    horizontal one hops it, or the other way round under
    ``"horizontal"``. Strictly inside both, so a run that merely ends on
    another is a junction and is not hopped, and strictly far enough
    inside the hopping segment for the arc's two feet
    (:data:`HOP_R`) to land on it.

    **Any other spelling is refused, and used not to be.** This read
    ``direction`` the way the drawing pass used to read it, against the
    two names it knows and no others, so ``jump_direction="vertcial"``
    hopped nothing and drew every crossing flat -- a drawing that says
    two lines meet where they cross, which is the same lie a severed hop
    tells, told the other way round. There is no third value to mean
    "no hops": :meth:`SvgRenderer.render` documents two, and a sheet
    that wants none is a sheet with no crossings on it.

    The refusal is :func:`check_jump_direction`'s sentence and not a
    second one: #492 gave the parameter a closed set and a message, and
    a value checked against two spellings of one set is how a set stops
    being closed. What is here is the **second door**. #492 refuses at
    :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw`, before the
    sheet is touched, which is where an author's typo should be caught;
    this catches the caller who reaches the geometry without going
    through a flowsheet at all, which is the argument
    :func:`enclosure_shape` makes for its own re-check. Neither replaces
    the other, and the read site is the one that makes it impossible to
    *use* the value without having checked it.

    **Which way it bulges** follows from the direction of travel and
    SVG's sweep flag, which is always ``1``: on a screen whose y runs
    down, that is clockwise, so a run drawn downwards bulges right and
    one drawn upwards bulges left; a run drawn rightwards bulges up and
    one drawn leftwards bulges down. The arc is a semicircle, so the
    side is the whole of the difference between the paper it covers and
    the paper beside it.
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
    """The paper a hop's arc covers, as a rectangle, padded like a line.

    The bounding box of the *semicircle* and not of the whole disc: the
    arc leaves the run on one side only, and the other side is paper a
    label may still use. Deliberately the box and not the half-disc,
    which over-states two corners of about 10,7 square units between
    them -- every other consumer of :class:`_Ink` compares rectangles,
    and the way for this to err is towards reserving paper that is
    clear rather than towards painting over paper that is not.
    """
    if hop.vertical:
        lo, hi = sorted((hop.x, hop.x + hop.side * HOP_R))
        return (lo - pad, hop.y - HOP_R - pad, hi + pad, hop.y + HOP_R + pad)
    lo, hi = sorted((hop.y, hop.y + hop.side * HOP_R))
    return (hop.x - HOP_R - pad, lo - pad, hop.x + HOP_R + pad, hi + pad)


#: The size a line number is lettered at, and the halo it is written on:
#: the string's estimated width plus a gutter, by a fixed depth. Held at
#: module scope because the exporter sizes the same label with them.
NUMBER_TYPE = 10
_HALO_CHAR, _HALO_PAD, _HALO_DEEP = 6.2, 6.0, 13.0

#: The paper a **box** enclosure leaves outside the halo it is ruled
#: around, on each of the four sides. The other two shapes need none: a
#: rule that slopes or curves away from the words is already clear of
#: them everywhere except the two points it touches, and those two
#: points are the halo's corners, which :data:`_HALO_CHAR` over-measures
#: into blank paper anyway (see :func:`_leader`). A rule *parallel* to
#: the words at the halo's own edge is the one case with nothing
#: between, so the box buys the gutter the geometry gives the others.
_ENCLOSURE_PAD = 4.0

#: The weight a stream label's enclosure is ruled at.
#:
#: :attr:`~.weights.LineWeight.DETAIL`, and the reason is not that the
#: balloons happen to be drawn there. The diamond an interlock balloon
#: draws is a graphical symbol, ISO 10628-1 §5.3.1 c), and answers to
#: that clause; a shape around a stream number stands for nothing in the
#: plant at all. It is part of the *annotation*, like the leader beside
#: it, and ISO 15519-1 §6.4 hands a leader to ISO 128-22 where it is a
#: narrow line -- which is the rung this file spells ``DETAIL``. The two
#: arriving at one number is a coincidence, so the one carrying the
#: reason is written here. A quarter of the weight of a main flow line
#: either way, which is the part a reader sees: an enclosure heavier
#: than the run it sits on would read as plant.
_ENCLOSURE_STROKE = LineWeight.DETAIL.width


def enclosure_shape(fs) -> str:
    """The shape ruled around every stream label on *fs*.

    Read off the flowsheet rather than passed down from the renderer, so
    the two backends cannot be handed different answers.

    Re-checked here, though
    :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw` has already
    refused a name outside the set before a thing was touched: this is
    the guard for the caller who reaches a renderer without going
    through a flowsheet at all, and it is deliberately not the first
    line of defence. It used to be the only one, and a render that
    raised from here had already numbered the streams, laid out the
    sheet and routed it.
    """
    from pandid.document import _resolve_enclosure

    return _resolve_enclosure(fs.stream_labels.enclosure)


def enclosure_box(shape: str, hw: float, hh: float) -> "tuple[float, float]":
    """How big an enclosure has to be to hold an ``hw`` x ``hh`` halo.

    Returned as the enclosure's own bounding box, measured along the
    words by across them; a label on a vertical run turns the pair over
    with everything else about it.

    The diamond and the circle are the **smallest of their kind
    containing the rectangle**, so neither is a size somebody had to
    choose. The box is not, and cannot be: the smallest rectangle
    containing a rectangle is that rectangle, and a rule drawn on the
    plate's own edge is a rule through the words -- the plate is what
    :data:`_HALO_CHAR` and :data:`_HALO_DEEP` measure the *glyphs*
    into, with no paper left over on the long sides. So the box is the
    one shape here carrying a chosen number, :data:`_ENCLOSURE_PAD`,
    and that constant is where the choice is argued.

    * ``diamond`` -- the minimum-area rhombus around a rectangle has
      each half-diagonal at twice the half-side it answers to (put the
      corner on the side, ``p/a + q/b = 1``, and the area ``2ab`` is
      least at ``a = 2p``, ``b = 2q``), so the box simply doubles. Then
      held to at least as wide as it is deep: a one-character number
      would otherwise get a rhombus standing on end, which is a shape a
      reader stops at and no drawing office rules.
    * ``circle`` -- the circumscribed circle, diameter the halo's
      diagonal. Much the tightest of the three on a long label, since it
      pays for the corners once rather than twice. It is also what an
      ISA balloon is drawn as, which is why it is not the default and
      why :class:`~pandid.document.StreamLabelOptions` says so for a
      sheet carrying instruments.
    * ``box`` -- the halo plus :data:`_ENCLOSURE_PAD`.
    """
    if shape == "diamond":
        return max(2 * hw, 2 * hh), 2 * hh
    if shape == "circle":
        d = math.hypot(hw, hh)
        return d, d
    if shape == "box":
        return hw + 2 * _ENCLOSURE_PAD, hh + 2 * _ENCLOSURE_PAD
    return hw, hh


def _enclosure_svg(shape: str, box, words, color: str) -> list[str]:
    """The plate a stream label is written on, and the shape ruled
    around it: *words* is the plate and *box* the shape, and *words* is
    ``None`` where the label lays down no plate at all.

    **The shape fills nothing, and the plate inside it erases nothing
    but the label's own run.** Those are the two halves of one rule, and
    together they are what lets an enclosure cost the drawing no ink
    that is not its own.

    A shape filled white is an opaque plate the size of a diamond, and a
    diamond is large -- twice the words in each direction -- so over the
    twenty-one shipped sheets, at the placement this file draws today,
    one would erase **1154 square units of drawn ink in 26 places**.
    Measured off the rendered document, by sampling each shape against
    the stroke every other run actually lays down: an area taken off
    :func:`_ink` instead is reservation area, the stroke padded by a
    whole stroke width, and this file of all files may not offer one for
    the other -- its own finding was that ``_ink`` is not the drawing.
    **Clipping a unit and deleting a line are not the same damage.** A block crowded by a diamond is a crowded drawing, and
    #480 decided the author spaces the sheet; a pipe with a bite out of
    it is a *wrong* drawing, and it says two things that are not true --
    that the line ends there, and that the gap is blank paper. An enclosed label may no longer step off what it
    covers (:func:`_label_anchors`, ``on_run``), so the fill is what had
    to give.

    Unfilling the shape is not the whole answer, and taking it for the
    whole answer is the defect this docstring used to carry. The plate
    under the words is opaque too, and pinning the label to its run laid
    **thirteen** of the 286 plates across a crossing pipe -- thirteen
    13-unit breaks in lines this drawing says are continuous -- where
    the same corpus lettered bare breaks none at all. So the plate is
    placed to cover nothing but the run it names
    (:func:`stream_numbers`), and where the run offers no such place it
    is **not drawn**: *words* arrives here ``None``, the number is
    written straight onto the sheet, and the line crossing it is drawn
    through it in full. Nine of the 286 land there on this corpus, and
    :func:`label_findings` names each one. A number a passing run
    has to be read across is harder to read; a run with a piece missing
    is not there. Foreign ink erased, at each of the four settings:
    **none** -- and measured off the rendered document rather than off
    :func:`_ink`, which is the only measurement that can catch
    :func:`_ink` being wrong, and did.

    The fill is then the one thing a drawing office does that this does
    not. A white-filled diamond hiding its own run is what they rule,
    and it cannot be ruled here without deleting the neighbour's: the
    fill would have to be clipped to the label's own ink, ``<clipPath>``
    is the only exact way to say that in SVG, and
    :mod:`pandid.render.export` refuses one outright rather than drop it
    silently from the PDF and the PNG. What carries the convention
    without it is that the run is seen to pass *through* the shape
    rather than to stop inside it, which is the grammar the whole
    decision rests on.

    ``"none"`` is the plate alone, to the byte it always was.
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
    pen = f'fill="none" stroke="{color}" stroke-width="{_ENCLOSURE_STROKE:g}"'
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
    # The outline first and the plate over it, so a rule that grazes the
    # words is buried by them rather than drawn across them -- which is
    # only ever the box, whose gutter is _ENCLOSURE_PAD, but it costs
    # nothing to be true of all three.
    return [outline, *plate]


class StreamNumber(NamedTuple):
    """One line number, and where the sheet decided to write it.

    ``seg`` is the segment of the run the number names -- its longest,
    the piece with the most line to attach a caption to. ``x``/``y`` is
    the point the string is *centred* on, ``vertical`` says it is turned
    a quarter to read bottom to top, ``box`` is the shape it is written
    in -- the opaque halo where the sheet rules none -- and ``leader``
    is the pair of points a leader runs between where the search found
    no paper alongside the run (``None`` where it did).

    ``words`` is the opaque plate the string itself is written on, and
    is the *only* white a label lays down: it equals ``box`` where
    nothing is ruled, and is the smaller rectangle inside it where
    something is. It is ``None`` where the label lays down no plate at
    all -- the case where every place its run offered would have painted
    out somebody else's line, and a crowded number was the cheaper of
    the two. See :func:`_enclosure_svg`.

    ``crossed`` names the runs the number is written across when that
    happened, and is empty otherwise. It is settled here rather than
    worked out again from the geometry, because here is the only place
    that holds both the plate the label wanted and the ink that took it
    away -- and because the rectangle it was measured against is not
    ``box`` once a shape is ruled around it, so a later reader of
    ``box`` alone would name lines the *number* never touched.
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
    """Where every line number on the sheet goes.

    Lifted out of :meth:`SvgRenderer._draw_streams` for the reason
    :func:`stream_polyline` and :func:`boundary_flag` were, and with
    more at stake: this is a *search*, not a formula, so a second
    implementation would not merely drift, it would answer differently
    on the first crowded corridor.

    ``placed`` is the list of opaque plates already on the sheet, and it
    is **appended to**: each number's halo, and each leader's box, is
    seeded as occupied so the next number does not delete it. The caller
    passes the equipment tags it has laid down and gets back the whole
    set, which is what :meth:`SvgRenderer._draw_streams` hands to the
    debugging overlay. An exporter with no equipment-tag pass of its own
    passes an empty list and gets a placement that dodges every symbol
    and every line but may still land under a tag -- the one thing about
    this the two backends do not share, and a difference of a seed
    rather than of a method.

    Everything else the search needs is derived here from the flowsheet,
    so the two callers cannot disagree about it: :func:`_ink` for the
    lines, and :func:`~pandid.portgeom.unit_box` through
    :func:`_obstacle` for the symbols.
    """
    from pandid.portgeom import unit_box

    ink = _ink(fs, direction)
    symbols: list[tuple[float, float, float, float]] = [
        _obstacle(unit_box(u, u.frame)) for u in fs.units if u.frame is not None
    ]

    # A flange mark is a symbol on a run, so it goes in with the
    # symbols: the search dodges it as it dodges a valve body, and both
    # the halo and the leader are scored against it. The mark is drawn
    # hard against a nozzle and a leader wants the clear middle of a
    # segment -- on the short spool between a condenser and the drum
    # beneath it, "the clear middle" was the two units between the two
    # flanges. See :func:`flange_boxes`.
    symbols += [_obstacle(b) for b in flange_boxes(fs, joints)]
    # A letter code written outside a balloon is a mark on the sheet the
    # same way: it is placed before either label pass runs (see
    # :func:`quadrant_labels`), so both can be told where it went.
    symbols += [b for b in map(_unit_label_box, quadrant_labels(fs, direction))
                if b is not None]

    # A number names a *run*, and a run survives the valves and fittings
    # in it: renumber_streams() gives every segment the same name and
    # the sheet writes it once, on the longest piece.
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
        # How much of the segment its own flange marks take: the mark's
        # standoff plus its half-width, where the near bar ends. Nought
        # on a run whose longest piece is in the middle of it, the marks
        # being at the nozzles and nowhere else.
        (mx1, my1), (mx2, my2) = longest_seg
        keep = FLANGE_STANDOFF + FLANGE_GAP / 2 if any(
            _near_segment((m.x, m.y), (mx1, my1), (mx2, my2))
            for m in flange_marks(s, points, resolve_connections(s, joints))
        ) else 0.0
        label_items.append((longest_seg, s.name, s.color or "black", keep))

    # An enclosure is ruled at **one size for the whole sheet**: measured
    # over the longest label on it, and given to every label, so a sheet
    # carrying 1 and 1002 draws one diamond seven times rather than two
    # diamonds. Sizing each to its own text is the alternative and it
    # comes out worse than it sounds -- on the mixed sheet #480 asked
    # for, per-label rules 26 units of diamond around `1` and 61,6
    # around `1002`, alternating down one process -- because a row of
    # shapes that vary reads as a drawing where the shape *means*
    # something. Same answer and the same argument as the stream table's
    # columns (#477), and the same cost: every label is paid for at the
    # width of the longest.
    #
    # The words' plate is the exception and stays per-label, because it
    # is not a shape a reader compares -- it is paper, and invisible --
    # and it is the only white a label lays down, so widening it to the
    # longest name would rub out a run's worth of pipe on either side of
    # every short one for nothing at all.
    shape = enclosure_shape(fs)
    widest = max((len(name) * _HALO_CHAR + _HALO_PAD
                  for _s, name, _c, _k in label_items), default=0.0)
    uniform = enclosure_box(shape, widest, _HALO_DEEP)

    out: list[StreamNumber] = []
    for seg, name, color, keep in label_items:
        (sx1, sy1), (sx2, sy2) = seg
        # What the words occupy, and what is reserved for them. One box
        # with no enclosure; with one, the second contains the first.
        tw, th = len(name) * _HALO_CHAR + _HALO_PAD, _HALO_DEEP
        hw, hh = (tw, th) if shape == "none" else uniform
        cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
        vertical = abs(sx2 - sx1) < abs(sy2 - sy1)
        span = abs(sy2 - sy1) if vertical else abs(sx2 - sx1)
        # Turned to follow the run, the halo measures hw along it, hh
        # across.
        bw, bh = (hh, hw) if vertical else (hw, hh)
        lw, lh = (th, tw) if vertical else (tw, th)

        # Everything the anchors below can reach: along the run as far
        # as _label_anchors will slide the label, and across it to the
        # outermost band. Seeds outside it are dropped before the search
        # rather than re-tested at every step of it.
        along = (span + hw) / 2 + max(bw, bh) / 2
        across = hh / 2 + _LABEL_GAP + _LABEL_BANDS * hh + max(bw, bh) / 2
        rx, ry = (across, along) if vertical else (along, across)
        window = (cx - rx, cy - ry, cx + rx, cy + ry)

        axis, at = ("v", (sx1 + sx2) / 2) if vertical else ("h", (sy1 + sy2) / 2)
        # How far **the run** goes, which is not how far the labelled
        # segment goes: an in-line valve splits a straight length of
        # pipe into three drawn pieces and a reader sees one line.
        # Everything collinear with the segment, which is what
        # :func:`_along` measures against. Taken over all the ink and
        # not only the ink inside the window, since a run that leaves
        # the window is one the label cannot overrun on that side.
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
        # Somebody else's line, which is the ink the label's own plate
        # may not be laid over at any price. By **name** and not by the
        # axis test above it: that one asks whether a line is collinear
        # with this segment, which is the question `_along` needs, and
        # two runs at one height are collinear and are still two runs.
        # A tap carries no name and so is foreign to every label, which
        # is what it is -- the one mark saying where a transmitter
        # measures.
        foreign = [line for line in ink
                   if line.line != name and _meets(line.box, window)]
        # A leader is ink like any other and dodges the same things the
        # halo does, symbols included, so it is scored against the lot.
        everything = near_symbols + occupied

        # Best first, and the first spot that covers nothing wins
        # outright; where nothing is clear the least damaging wins and a
        # tie keeps the earlier anchor. The anchors that sit *on* the
        # pipe come first, which makes the label's own line the last
        # resort -- breaking the run you are naming is a convention a
        # reader knows, and breaking the one beside it is a lie about
        # that line.
        #
        # An anchor the run does not run along carries a leader instead
        # (ISO 15519-1 §7.2.5; :func:`_along` for where the line falls),
        # and the leader's own crossings are the last part of the score.
        # A clear spot alongside the run still wins outright, scoring
        # all zeros with the anchors generated near-first.
        clear = (0, 0, 0, 0)
        spot: "tuple[float, float] | None" = None
        damage: "tuple[int, int, int, int] | None" = None
        leader: "tuple | None" = None
        for ux, uy, _off in _label_anchors(cx, cy, span, hw, hh, vertical,
                                           shape != "none", tw):
            box = (ux - bw / 2, uy - bh / 2, ux + bw / 2, uy + bh / 2)
            paper = (box if shape == "none" else
                     (ux - lw / 2, uy - lh / 2, ux + lw / 2, uy + lh / 2))
            # **First, and ahead of everything else the search weighs.**
            # The plate is the only white a label lays down, so this is
            # the only term that can *delete* a line rather than crowd
            # it, and a drawing that shows a connected pipe as broken is
            # wrong where a crowded one is merely hard to read. Nothing
            # further down this tuple may buy a spot that erases one.
            erased = sum(1 for line in foreign if _meets(paper, line.box))
            limit = None
            if damage is not None:
                if erased > damage[0]:
                    continue
                limit = damage[1:3] if erased == damage[0] else None
            hits = _covering(box, occupied, near_symbols, limit)
            if limit is not None and hits > limit:
                continue
            # An enclosed label is on its run by construction, so it
            # never carries a leader: a leader stands in for adjacency
            # (:func:`_along`, ISO 15519-1 §7.2.5) and there is nothing
            # to stand in for when the line goes through the shape.
            lead, cut = ((None, 0)
                         if shape != "none" or _along(box, vertical, run_lo, run_hi)
                         else _leader(box, seg, everything, keep))
            cost = (erased, *hits, cut)
            if damage is None or cost < damage:
                spot, damage, leader = (ux, uy), cost, lead
                if cost == clear:
                    break
        # `_label_anchors` always offers at least the innermost band
        # either side of the run: the search chooses between anchors, it
        # never fails to find one.
        assert spot is not None and damage is not None
        tx, ty = spot
        halo = (tx - bw / 2, ty - bh / 2, tx + bw / 2, ty + bh / 2)
        # The one opaque plate the label lays down -- the reserved box
        # itself where nothing is ruled, the words' own smaller
        # rectangle inside the shape where something is (see
        # :func:`_enclosure_svg` for why the shape adds no white) --
        # **and nothing at all where every place the run offered would
        # have painted out a line that is not this one's.** Erasing a
        # neighbour's pipe is the one damage the search may not choose,
        # so where it cannot be dodged it is not paid: the words go
        # straight onto the sheet, the crossing line is drawn through
        # them in full, and a reader sees a crowded label rather than a
        # line that stops for no reason. `label_findings` names every
        # one, at every setting, and this is where the names come from:
        # worked out here where the candidate and the ink that beat it
        # are both in hand, rather than re-derived later from a box
        # whose size a shape has changed.
        paper = (halo if shape == "none" else
                 (tx - lw / 2, ty - lh / 2, tx + lw / 2, ty + lh / 2))
        words = None if damage[0] else paper
        crossed = () if words is not None else tuple(sorted(
            {line.line or "an instrument connection" for line in foreign
             if _meets(paper, line.box)}))
        placed.append(halo)
        if leader is not None:
            # Seeded as occupied so the next label's halo cannot delete
            # it. The bounding box rather than the stroke, which is
            # generous for a sloping line, but a leader is rare and the
            # alternative is a halo on the one mark saying which line
            # this number belongs to.
            (ax0, ay0), (ax1, ay1) = leader
            placed.append((min(ax0, ax1), min(ay0, ay1),
                           max(ax0, ax1), max(ay0, ay1)))
        out.append(StreamNumber(name, color, seg, tx, ty, vertical, halo,
                                leader, words, crossed))
    return out


#: The codes the stream-label pass puts on ``fs.warnings``.
#:
#: ``label-over-line`` is the one that is **not** about an enclosure and
#: fires whatever ``fs.stream_labels.enclosure`` says, the default
#: included, because the rule it reports is unconditional: a label lays
#: its opaque plate only where it covers nothing but its own run, and
#: gives the plate up rather than paint out a neighbour's. That is a
#: change to the drawing, so it is a change the author has to be told
#: about on the sheet they did not opt into.
_LABEL_CODES = ("label-over-line", "enclosure-over-unit",
                "enclosure-over-line", "enclosure-over-label")


def _shape_hits(shape: str, box, rect) -> bool:
    """Does the enclosure *shape* filling *box* meet the rectangle *rect*?

    The shape and not its bounding box, which is the difference between
    a finding worth acting on and a list the author learns to ignore: a
    diamond is half the area of the box it is measured in, and all four
    of the halves it is missing are corners -- exactly where a
    neighbouring line passes closest without touching.

    Both shapes are symmetric about the enclosure's centre and the
    rectangle's nearest point to that centre can be taken axis by axis,
    so ``dx``/``dy`` below is the nearest point of *rect* in the
    quadrant geometry, and each shape is then one inequality. For the
    rhombus that is exact because ``|x|/a + |y|/b`` is separable and
    increasing in each term, so minimising it over a rectangle
    minimises each coordinate on its own.
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
    """Do the two enclosures of the same *shape* filling *box* and
    *other* share any area?

    :func:`_shape_hits` answers a shape against a **rectangle**, which
    is what a symbol and a length of pipe are, and it is exact for one.
    A second enclosure is not a rectangle, and asking it twice -- each
    shape against the other's bounding box, both ways round -- is not
    the same question and gets the wrong answer: two rhombi can each
    reach into the other's box while neither reaches the other. The
    corpus draws that pair. Two diamonds 222,8 by 26, centres five units
    apart across their runs and overlapping 2,81 along them, and over
    the whole of that overlap the two rhombi between them reach 0,328 --
    they cannot touch, and both directions of the box test call it a
    collision. Over the twenty-one sheets at ``"diamond"`` that test
    names seven crossing pairs where five touch, and bounding box
    against bounding box names twelve. A list the author is asked to
    work from earns nothing by being generous, so this settles it
    exactly. ``tests/test_stream_label_enclosure.py`` keeps that pair of
    rectangles as literals, and checks every pair on the corpus against
    a clipped polygon area.

    Each shape is its own answer. Two boxes are two rectangles and
    :func:`_meets` has already decided. Two circles meet when their
    centres are closer than the two radii. Two rhombi are convex
    polygons, so the separating-axis theorem is exact over the edge
    normals of both: a rhombus of half-diagonals ``a`` by ``b`` has two
    distinct edge normals, ``(b, a)`` and ``(b, -a)``, and its own
    extent about its centre along any axis ``u`` is
    ``max(|a*ux|, |b*uy|)`` -- the four vertices being the only
    candidates and lying on the axes. Four axes settle any pair.
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


def label_findings(fs, shape: str, numbers: "list[StreamNumber]",
                   direction: str) -> "list[Issue]":
    """What the stream labels on this sheet have been drawn over.

    An enclosed label may not leave its run (#480), so where the shape
    is bigger than the paper beside the line the sheet draws it there
    anyway and something ends up underneath. **That is the decision, and
    this is the list it owes the author**: spacing the plant is a
    drafting choice and belongs to the drafter, but they cannot make it
    from a sheet they have to scan diamond by diamond.

    Three codes, because the three are not the same news:

    * ``enclosure-over-unit`` -- the shape crosses a symbol's box. This
      is the case the decision accepted outright, and the finding is a
      cue and not a complaint: the drawing is crowded and complete.
    * ``enclosure-over-line`` -- the shape crosses ink belonging to some
      other run. Worse to read, because a shape whose grammar is *the
      run passes through me* now has two runs through it.
    * ``enclosure-over-label`` -- two enclosures cross each other,
      which on the shipped corpus is five pairs out of 286 diamonds.
      Reported once per pair, from the second of the two: the first was
      seeded as occupied before the second was placed
      (:func:`stream_numbers`), so the search preferred every clear
      alternative it had and this is what was left. Settled by
      :func:`_shapes_meet`, which is exact: this used to ask the
      shape-against-rectangle test both ways round, which names seven
      pairs here and is wrong about two of them.

    **All three are warnings, and that is a consequence of what the
    drawing does rather than a judgement about crowding.** A sheet that
    shows a connected pipe as broken is a wrong drawing, and a render
    that emits one should refuse rather than warn about it. Nothing
    here emits one: the shape is an outline, and the plate under the
    number is laid only where it covers nothing but the run it names
    (:func:`_enclosure_svg`). What is left over is a crowded drawing
    the author can read, and crowding is what #480 handed to the
    drafter. Give the shape a fill, or let the plate cover a foreign
    run again, and this severity has to rise with it.

    Where the plate had to be dropped -- nine labels of the 286 on the
    corpus with a shape ruled, the runs too short to hold it clear
    anywhere -- ``label-over-line`` says so, and says which runs the
    number is written across. It is a separate code from
    ``enclosure-over-line`` because it is a separate fact: one is a
    shape with two runs through it, the other is a *number* with a run
    through it, and a reader who has to space the sheet needs to know
    which they have.

    ``label-over-line`` is the fourth, and it is the one that has
    nothing to do with enclosures: it fires **at every setting**, the
    default included. A label gives its plate up rather than paint out a
    run that is not its own, and that rule is not conditional on the
    option -- so neither is the finding, or the sheet nobody opted into
    would quietly drop a plate and say nothing. Bare labels reach it
    only on a crowded sheet, since a bare label may still step off what
    it would cover and on the shipped corpus always finds paper; the
    twenty-seven-stream fixture in
    ``tests/test_stream_label_enclosure.py`` is what a sheet with no
    clear paper in any of the fourteen bands beside a run looks like.

    The other three are silent at ``"none"`` for the reason they are
    named after: there is no enclosure to have been drawn over
    anything.
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
            # About the *shape* only. Whether the number inside it is
            # crossed too is `label-over-line`'s to say, and saying it
            # in both would be one fact wearing two codes -- which is
            # how a list the author works from stops being read.
            out.append(Issue(
                "warning", "enclosure-over-line",
                f"{number.name}'s {shape} is drawn over {', '.join(lines)}, so "
                f"more than one run passes through one shape. Every line is "
                f"still drawn -- the shape is an outline and fills nothing -- "
                f"but the reader has to tell them apart. Space the sheet, or "
                f"route {number.name} clear with via()"))
        # Against the labels already placed only, so a crossing pair is
        # one finding rather than two saying the same thing twice.
        # Shape against shape, exactly: see :func:`_shapes_meet` for
        # what asking it as two box questions got wrong.
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


#: How deep the point of an off-page flag is cut back from the end of
#: its rectangle, and how far the pennant is inset inside the flag's
#: box, top and bottom -- less where an off-page reference has to be
#: written under the tag, since two lines need a taller flag than one.
FLAG_POINT = 15
_FLAG_INSET, _FLAG_INSET_REF = 15, 12


class Pennant(NamedTuple):
    """The off-page flag a Feed or a Product is drawn as.

    ``box`` is the rectangle the pennant occupies, ``point`` how deep
    its point is cut back from the end, and ``east`` which end that
    point is on.
    """
    box: tuple[float, float, float, float]
    point: float
    east: bool


def boundary_flag(u, frame) -> Pennant:
    """The pennant an off-page flag is drawn as.

    A rectangle with one end drawn to a point at mid-height, pointing
    the way the stream runs: east out of a Feed, east into a Product,
    and west for either where the placement mirrors it. The point is
    where the line meets the flag on a Feed and the blunt end is where
    it meets a Product, which is why both point the same way.

    Two things about the rectangle are worth writing down once rather
    than measuring twice. It spans the *whole* of
    :func:`~pandid.portgeom.unit_box` horizontally -- a Feed's box
    extends left from its port, the one place in the library where that
    is true -- and it is inset a fixed 12 or 15 units off ``frame.h``
    top and bottom, so a flag at the default 50-unit height is 26 or 20
    units deep. Reading the inset off the *placed* height rather than a
    fixed 50 is what lets a caller who sizes a flag get a pennant that
    fills it instead of one stuck 20 units deep near the top of a box
    the drawing never reaches the bottom of. An exporter taking the box
    for the drawing would rule a flag 1,9 to 2,5 times too tall,
    depending on which inset it carries -- not simply twice, either way.

    Nothing here reads ``header``: a utility header flag is the same
    pennant as an off-page reference, and what tells the two apart on a
    sheet is the label rather than the outline.

    Shared with the draw.io exporter, as :func:`stream_polyline` is.

    The horizontal extent is written out again rather than read from
    ``unit_box`` for one reason: this arithmetic is what the polygon is
    *formatted from*, and ``unit_box``'s ``50.0`` would write a
    whole-number coordinate as ``100.0`` where the sheet has always
    written ``100``. The two agree on the number, which
    ``test_a_flag_is_drawn_across_its_own_box`` pins over every
    placement.
    """
    inset = _FLAG_INSET_REF if (getattr(u, "reference", "") or "") else _FLAG_INSET
    if u.kind == "feed" and not frame.mirrored:
        x0, x1 = frame.x + 50 - frame.w, frame.x + 50
    else:
        x0, x1 = frame.x, frame.x + frame.w
    return Pennant((x0, frame.y + inset, x1, frame.y + frame.h - inset),
                   FLAG_POINT, not frame.mirrored)


#: Where the two strokes of a pneumatic double cross-hatch sit *along*
#: the run, relative to the mark's own point, and how far each reaches
#: across it. The stroke leans, 6 units along by 10 across, which makes
#: it a slash rather than a tick.
HATCH_ALONG = (-2.5, 1.5)
HATCH_ARM = (3.0, 5.0)


class Hatch(NamedTuple):
    """One double cross-hatch on a pneumatic line.

    ``along`` is how far down the line the mark sits, by the Euclidean
    arc length ``mxGraphView.getPoint`` measures a relative child of an
    edge by. Carried rather than recovered from ``(x, y)`` because a
    point cannot always be found again: an orthogonal route that doubles
    back passes through the same neighbourhood twice, and a mark on the
    second pass matched against the first is hung on the wrong part of
    the line.
    """
    x: float
    y: float
    horizontal: bool
    along: float


def pneumatic_marks(points) -> "list[Hatch]":
    """Every double cross-hatch a pneumatic line is marked with.

    ISA-5.1 draws a pneumatic signal as a *solid* line marked with
    double cross-hatches, so the hatch is the only thing telling it
    apart from process piping. One mark per 45px alone leaves a short
    run (a transducer to the actuator right beneath it) with none at
    all, reading as plain pipe. Any segment with room gets at least one;
    longer segments keep the 45px spacing.

    Shared with the draw.io exporter, which has no way to stroke a mark
    across a line and hangs one on the edge at these points instead. For
    a mark that is the *whole* of what identifies the line, a second
    rule for where they fall is worse than a different style.
    """
    out: list[Hatch] = []
    walked = 0.0
    for i in range(len(points) - 1):
        (px1, py1), (px2, py2) = points[i], points[i + 1]
        # Manhattan for the spacing rule, which is what the sheet counts
        # marks by; Euclidean for the distance, which is what mxGraph
        # measures a mark's place on an edge in. The two agree on an
        # orthogonal segment and differ only on a sloping leg.
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


#: What a drawing may say about the joints where its lines meet what
#: they serve. A tuple rather than a bool for the reason
#: ``Valve.NORMAL_POSITIONS`` is one: the joint's make-up is an
#: enumeration the plant has more entries in (threaded, socket-welded, a
#: spec break), not a switch with two settings.
#:
#: ``"none"`` is not ``"welded"``. It is the drawing declining to say,
#: which is what an unmarked line has always meant: a library that
#: marked every joint flanged would be claiming something about piping
#: nobody gave it.
#:
#: The other two differ in one thing, and it is the thing the author is
#: choosing between -- whether the **bodies standing in the run**, the
#: valves and the in-line fittings, are bolted in or welded in.
#:
#: * ``"flanged"`` marks every joint the sheet can mark, valves
#  included.
#: * ``"flanged-at-nozzles"`` marks only where a line meets an equipment
#:   nozzle, leaving the bodies in the run unmarked.
#:
#: See :func:`flanged_joint` for what each marks, and for why no
#: standard settles it.
CONNECTIONS = ("none", "flanged", "flanged-at-nozzles")

#: The in-line kinds that are *bodies bolted into* a run rather than
#: pipe welded along it, and so the ones ``"flanged"`` marks. A strict
#: subset of :data:`~pandid.flowsheet.INLINE_KINDS`, the wider set of
#: things that interrupt a line without ending it; ``test_render_api``
#: holds the subset relation so the two cannot drift together.
#:
#: A valve, a strainer, a sight glass or an orifice plate is a body you
#: break the line to pull, bolted between a pair of faces *so that* you
#: can. A concentric reducer and a tee are butt-welded fittings, as much
#: "pipe" as the pipe either side. So the mark follows what has to come
#: out.
_INLINE_BODIES = frozenset({"valve", "fitting"})

#: The flanged-connection mark, in the proportions the vendored draw.io
#: stencil draws it in: ``('fitting', 'flange')`` in
#: :mod:`._vendored_symbols` is two bars 5.0 apart and 12.5 long, at the
#: weight of the pipe. Held to those exact numbers so the sheet and an
#: export that places the stencil are one mark rather than two drawings
#: of one.
#:
#: Against P&ID_301 the proportions check out: its ticks are 8.5pt long,
#: 2.13pt apart, at a ~0.85pt pen. The gap is 1.5 pen widths there and
#: 1.5 here (5.0 apart less a 2.0 stroke), which is what makes the two
#: bars read as one mark rather than two ticks near each other.
FLANGE_TICK = 12.5
FLANGE_GAP = 5.0

#: How far the pair's *centre* stands off the nozzle, along the run.
#: Enough that the near bar clears the outline it is drawn against: the
#: mark says the joint is outside the equipment, and a bar overlapping
#: the shell reads as part of the shell.
FLANGE_STANDOFF = 5.0


class Flange(NamedTuple):
    """One flanged-connection mark on a stream.

    ``angle`` is the direction of the *run* at the mark in degrees, not
    the direction the bars are stroked in; the bars are drawn across it.
    Carried rather than recovered because the draw.io exporter cannot
    re-derive it -- mxGraph has no auto-orientation for a shape on an
    edge. ``along`` is arc length from the source end, for the reason it
    is on :class:`Hatch`.
    """
    x: float
    y: float
    angle: float
    along: float


def _draws_its_own_flange(u) -> bool:
    """Is this body's own symbol already the flanged connection?

    ``Fitting``'s *default* variant is the flanged connection and
    ``"flange"`` is the same artwork under its own name, so an author
    who pins one has drawn the joint explicitly; marking it would put
    three flange pairs where one was asked for. Asked of the registry
    rather than matched against variant names, so re-pointing the
    artwork cannot leave this checking for a symbol nothing draws.
    """
    from pandid.render.symbols import default_registry

    own = default_registry.get(u.kind, getattr(u, "variant", "default"))
    return (own.drawio_shape is not None
            and own.drawio_shape == default_registry.get("fitting", "flange").drawio_shape)


def flanged_joint(port, want: str) -> bool:
    """Does a ``want`` joint put a mark at this end of a stream?

    ``want`` is one of :data:`CONNECTIONS`, already resolved against the
    sheet by :func:`resolve_connections`, so all that is left is whether
    this end is the kind of end that takes a mark.

    **No standard on disk settles this, and this docstring is not going
    to pretend one does.** The word "flange" appears nowhere in either
    part of the reference the rest of this module cites -- zero
    occurrences in ISO 15519-1:2010 and zero in ISO 15519-2:2015.
    ISO 15519-1 §12.4 is headed *Joints* and is not about pipe joints at
    all: it governs the joining of *connecting lines* on the paper, and
    marks a join with symbol 501, *Joint of connections*, a dot. Its last
    sentence lets that dot be left off a T-joint, and that is the
    permission this package takes. Nothing here draws a joining
    dot: a tee is two straight strokes and no ``<circle>`` is emitted
    anywhere (see the tee's own artwork in
    :mod:`pandid.render.symbols`). That is conforming, but it is
    conforming by the exemption rather than by the rule.
    ISO 15519-2 §6.3.1 hands symbols to the ISO 14617 series, where the
    flanged-connection symbol lives, but 14617 is a registry of symbols
    rather than a rule about where to put them and is not in
    ``professional_examples/``, so nothing is quoted from it.

    So: **no clause requires a flange at a valve and no clause forbids
    one.** What follows is a drafting choice, and is offered as a choice
    for that reason rather than settled on the author's behalf.

    Two kinds of end are not joints under either setting:

    * a boundary flag, a ``Feed`` or ``Product`` being a reference to
      another sheet, and a reference has no flange faces;
    * an instrument, since what a balloon terminates is a tap or a
      signal, and :func:`flange_marks` has dropped the signal lines.

    Everything else turns on ``want``:

    ``"flanged"``
        Every equipment nozzle, **and both sides of every body standing
        in the run** (:data:`_INLINE_BODIES`). A valve in flanged
        service is flanged both sides, which is how it is got out of the
        line. Reducers and tees stay unmarked, being welded fittings.

    ``"flanged-at-nozzles"``
        The nozzles only, which is what ``P&ID_301.pdf`` draws: every
        piped branch off a shell carries the mark there and nothing else
        on the sheet does, not the gate valves either side of CV-305,
        not the drains, not the boundary flags. On that sheet the mark
        means *this branch is bolted to the vessel* and says nothing
        about the valve downstream. Evidence of what one drawing office
        drew rather than of what a standard demands.
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
    """Every flange mark one stream carries, in drawing order.

    ``ends`` is the resolved ``(source, dest)`` pair, each a member of
    :data:`CONNECTIONS`; resolving it against the sheet is
    :func:`resolve_connections`' job, so this asks only whether the
    geometry and the flowsheet agree that a mark belongs.

    A signal line never carries one: a flange is a fact about pipe, and
    there is no joint to describe.

    Shared with the draw.io exporter for the reason
    :func:`pneumatic_marks` is, and more sharply -- this mark lands hard
    against a vessel outline, where a few units either way is the
    difference between a joint and a collision.
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

        # The mark stands off the nozzle *along the line*, the same
        # placement the arrowhead has and stated the same way: the run's
        # direction at the end it terminates, from the last two points
        # of the polyline the pipe is drawn through.
        tip = points[-1] if at_dest else points[0]
        neighbour = points[-2] if at_dest else points[1]
        span = spans[-1] if at_dest else spans[0]

        # No room, no mark. The pair needs its standoff plus its own
        # half-width of straight run to sit on, and a flange drawn
        # across the corner beyond a short first segment is worse than
        # none.
        if span < FLANGE_STANDOFF + FLANGE_GAP / 2:
            continue

        ux, uy = (neighbour[0] - tip[0]) / span, (neighbour[1] - tip[1]) / span
        cx, cy = tip[0] + ux * FLANGE_STANDOFF, tip[1] + uy * FLANGE_STANDOFF
        along = total - FLANGE_STANDOFF if at_dest else FLANGE_STANDOFF
        out.append(Flange(cx, cy, math.degrees(math.atan2(uy, ux)), along))
    return out


def flange_boxes(fs, joints) -> "list[tuple[float, float, float, float]]":
    """Every flange mark on a sheet, as a box a label must keep off.

    **A flange mark is a graphical symbol standing on a run**, so every
    pass that places opaque lettering ranks it with the symbols and not
    with the pipe. The distinction is :func:`_erases`': a halo over pipe
    is a gap the reader reads across, and a halo over a flange face is
    the sheet no longer saying the joint is bolted.

    ``joints`` is :func:`sheet_connections`' answer, and ``None`` -- a
    drawing that marks no joints -- gives an empty list, so a caller
    with nothing to dodge need not ask whether it has anything to dodge.

    One function rather than a list built at each of the three passes,
    which were not agreeing: ``RB-301``'s tag went out with two units of
    a flange face on the reboiler's vapour riser cut out of it, because
    :meth:`SvgRenderer._draw_units` had not grown the rule
    :func:`stream_numbers` had. The exporter's
    :func:`~pandid.render.drawio._tag_pass` runs the same search and has
    to be handed the same ink.

    Square, and sized on the longer of the pair's two dimensions: the
    mark's angle follows the run, and a box tracking the angle would be
    four numbers saying less than one. A little slack along the run, on
    a mark 12,5 across.

    Ungrown. The caller applies :func:`_obstacle`, for the reason there.
    """
    half = max(FLANGE_TICK, FLANGE_GAP) / 2
    return [
        (m.x - half, m.y - half, m.x + half, m.y + half)
        for s in fs.streams
        for m in flange_marks(s, stream_polyline(s), resolve_connections(s, joints))
    ]


def _arrowhead(start, end) -> str:
    """Path data for the filled head terminating a leader at *end*."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    bx, by = end[0] - ux * _LEADER_HEAD, end[1] - uy * _LEADER_HEAD
    px, py = -uy * _LEADER_HEAD / 2, ux * _LEADER_HEAD / 2
    return (f"M {end[0]:.1f},{end[1]:.1f} L {bx + px:.1f},{by + py:.1f} "
            f"L {bx - px:.1f},{by - py:.1f} Z")


def arrow_marker_id(color: str) -> str:
    """The ``<marker>`` id the arrowhead in *colour* is defined under.

    One function for the definition and for the ``url(#...)`` that
    reaches it, so the two cannot drift, over
    :func:`~pandid.render.escape.ident`, which is what makes the answer
    a legal XML name whatever the colour is spelled like. A hex triple
    loses its ``#`` first because ``#0a7`` and ``0a7`` are the same
    colour to a reader and only one of them is a name -- and because
    that is the id these sheets have always carried.

    ``rgb(0, 170, 119)`` is the case that used to break: pasted whole it
    gives ``arrow_rgb(0,_170,_119)``, which a browser rejects as an id,
    drops the definition for, and then draws the line without its head.
    Nothing warns, and a PDF export -- which resolves the reference
    itself rather than through the document -- still shows the head, so
    the two outputs disagree about the drawing.
    """
    return ident("arrow", color.lstrip("#"))


def _unit_label_box(item) -> "tuple[float, float, float, float] | None":
    """Halo rect of an equipment tag.

    ``None`` for a ``center`` tag, which sits inside its own symbol and
    so is drawn without one.

    ``6.6`` is this label font's per-character width (hand-tuned for
    12pt) and ``8`` the padding either side; a Latin, digit or
    punctuation tag still computes exactly that, unchanged. A wide
    (CJK/fullwidth) character is charged a full em (12, this font's own
    size) instead of that per-character rate, and a combining mark
    nothing -- see :func:`~pandid.render.furniture.script_counts`. Left
    uncounted, a wide character was the halo that stopped a third short
    of its own ink and let the line behind the tag show through it.
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
    """Format a coordinate without trailing zeros (100.0 -> '100')."""
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _xform_tag(rot: int, mirror_x: bool, mirror_y: bool) -> str:
    """Id suffix naming a placement transform ('' for the identity)."""
    if not (rot or mirror_x or mirror_y):
        return ""
    return "_t" + (f"r{rot}" if rot else "") + ("x" if mirror_x else "") + ("y" if mirror_y else "")


def _placed_box(u) -> "tuple[float, float] | None":
    """The box a unit's artwork is drawn into, in its own attitude.

    A quarter turn swaps the box the drawing is laid into and turns the
    result back onto the frame, so the artwork never sees the swap.
    Every question about how a placement scales a symbol is asked in
    these terms.
    """
    f = getattr(u, "frame", None)
    if f is None:
        return None
    rot = int(getattr(f, "orientation", 0) or 0)
    return (f.h, f.w) if rot in (90, 270) else (f.w, f.h)


def _reshapes(sym, u) -> bool:
    """True when a unit's box is a different shape from its symbol.

    Which is the whole of what a placement can ask of the artwork beyond
    a plain resize: an explicit ``width``/``height`` is taken as the
    final box, so a unit left to size itself lands on the symbol's
    proportions exactly. A quarter turn swaps the box and swaps the
    symbol with it, so it never reshapes anything by itself.
    """
    box = _placed_box(u)
    if box is None:
        return False
    bw, bh = box
    # Cross-multiplied, so a zero dimension cannot divide. A box that
    # matches is copied from the symbol's own size and matches to the
    # bit; the tolerance is there only so arithmetic on a size the
    # author computed cannot claim a reshaping that is not one.
    return not math.isclose(sym.width * bh, sym.height * bw, rel_tol=1e-9)


# --- the pen a placement draws with -----------------------------------
# A symbol's line weights are compensated once, at generation time:
# scripts/vendor_symbols.py bakes stroke_width = 2/sqrt(sx*sy) inside
# the scale group it wraps the artwork in, so a valve drawn under
# scale(0.25) carries an 8.0 and lands on the sheet's 2.0. That is right
# for exactly one box, the symbol's own. A <use> resizes the <symbol>'s
# viewport, and a viewport scales the ink as readily as the geometry, so
# the same valve placed in a box twice its own draws at 4.0 with nothing
# to scale it back. _pen_scale is the other half: divide the baked
# weight back out by whatever the placement multiplied it by, which is
# what makes a resized unit's <defs> entry per placed *size* rather than
# per (kind, variant).
#
# Dividing works while the placement scales both axes alike, and only
# then. A stroke is swept by a *circular* pen, and a viewport scaling
# the axes differently sweeps an elliptical one: under
# preserveAspectRatio="none" a vertical line comes out at sx and a
# horizontal one at sy, and no single stroke-width undoes a difference
# that depends on which way the element runs. _baked handles that case.


def _placement_scale(sym, u) -> "tuple[float, float]":
    """What a unit's ``<use>`` box scales its artwork by, per axis."""
    box = _placed_box(u)
    if box is None or not (sym.width and sym.height):
        return (1.0, 1.0)
    return (box[0] / sym.width, box[1] / sym.height)


def _stretch_scale(sym, u) -> "tuple[float, float]":
    """What the ``<use>`` viewport would scale the artwork by, per axis.

    ``(1, 1)`` unless the placement actually reshapes a symbol that may
    be reshaped: everything else lands on a *uniform* scale -- the
    symbol's own box, a plain resize, or the letterbox a non-stretchable
    symbol is centred in -- which is the case the pen division below
    answers exactly.
    """
    if sym.stretchable and _reshapes(sym, u):
        return _placement_scale(sym, u)
    return (1.0, 1.0)


# Bounded rather than unbounded: the key is a whole artwork string and a
# placed size, so a long-running process drawing many differently-sized
# units would otherwise hold every one forever. Cached at all because
# _fold, _pen_scale, _size_tag and _sym_id each ask it, several times
# per unit.
@lru_cache(maxsize=2048)
def _uneven(svg: str, fx: float, fy: float) -> bool:
    """Would an *uneven* scale stand between this ink and the page?

    Two things can put one there and they multiply. The placement is
    one, and is what :func:`_stretch_scale` reports. The artwork's own
    groups are the other, and are easy to miss:
    ``scripts/vendor_symbols.py`` reproportions four stencil families to
    the box the library wants them in -- a plain vessel is drawn under
    ``scale(0.62, 0.5)`` -- so those four draw an elliptical pen *at
    their own size*, with no placement involved. It is why a separator
    on a sheet that resizes nothing still draws its shell walls at 2.23
    against its heads' 1.80.

    Magnitudes, so a mirror does not read as an unevenness: the derived
    expansion fittings are their reducer under ``scale(-1, 1)``, which
    turns the pen round without deforming it.
    """
    return any(not math.isclose(ax, ay, rel_tol=1e-9)
               for ax, ay in _stroke_scales(svg, fx, fy))


def _stroke_scales(svg: str, fx: float, fy: float) -> "list[tuple[float, float]]":
    """The scale over every stroke in *svg*, at ``scale(fx, fy)``.

    Magnitudes.
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
    """The placement scale a definition takes into its own coordinates.

    ``(1, 1)`` -- the artwork left in the symbol's own coordinates, the
    viewport doing the scaling -- unless the viewport would scale the
    two axes differently, in which case there is nothing for it but to
    rewrite the drawing at the placed size. See :func:`_baked`.
    """
    fx, fy = _stretch_scale(sym, u)
    return (fx, fy) if _uneven(sym.svg, fx, fy) else (1.0, 1.0)


def _pen_scale(sym, u) -> float:
    """The factor a placement multiplies a symbol's line weights by.

    One factor and not two, because ``stroke-width`` is one number, so
    this is only ever asked where the placement leaves a *uniform* scale
    over the artwork. :func:`_fold` guarantees it: a placement that
    would have left an uneven one has already been rewritten into the
    coordinates, at which point the viewport scales by exactly 1.

    What is left is the three ways a placement can resize a symbol
    evenly: not at all, a plain resize, and the letterbox a symbol that
    may not be stretched is centred in, which keeps its aspect at the
    smaller of the two scales.
    """
    if _fold(sym, u) != (1.0, 1.0):
        return 1.0
    kx, ky = _placement_scale(sym, u)
    if sym.stretchable and _reshapes(sym, u):
        # An uneven box over an artwork whose own wrapper is uneven the
        # other way: the two cancel and the pen comes out round after
        # all. Rare, but it is the case _uneven() declines to rewrite.
        return math.sqrt(kx * ky)
    return min(kx, ky)


def _size_tag(sym, u) -> str:
    """Id suffix naming the box a placement had its symbol drawn for.

    Empty for the great majority, which is the point: a unit left to
    size itself lands on its symbol's own box at a scale of exactly 1
    and goes on sharing one definition with every other unit of its
    kind. Only a unit given a ``width``/``height`` costs a second entry.
    """
    if (math.isclose(_pen_scale(sym, u), 1.0, rel_tol=1e-9)
            and _fold(sym, u) == (1.0, 1.0)):
        return ""
    box = _placed_box(u)
    assert box is not None  # a scale of anything but 1 came from a box
    return f"_s{_num(box[0])}x{_num(box[1])}"


# Written on the element in every symbol here, hand-drawn and vendored
# alike; nothing reaches a stroke through CSS, which is what lets this
# be a rewrite of the emitted string rather than a parse of it.
_STROKE_WIDTH = re.compile(r'stroke-width="([\d.]+)"')


def _at_pen_scale(svg: str, scale: float) -> str:
    """*svg* with every line weight in it divided by *scale*.

    Every weight and not only the 2.0 outline: a symbol's own fine
    detail -- a column's trays, an agitator, the location bar across a
    panel balloon -- is drawn at a deliberate fraction of the sheet
    weight, and the placement swells all of them alike, so dividing all
    of them alike is what holds the ratio its author drew. Six
    significant figures because the number is read back as a weight and
    multiplied by the scale again on the way to the page.
    """
    if scale == 1.0:
        return svg
    return _STROKE_WIDTH.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


# --- baking an uneven scale into the drawing --------------------------
#
# ISO 15519-1:2010 §11.1.3, *Line width in graphical symbols*, is a
# *shall*: a symbol's line is normally 0,1 M after ISO 81714-1, and
# resizing the symbol leaves that width alone.
#
# §11.1.2 permits the proportions themselves to be modified, so
# stretching a stencil to fill the box a unit was given is allowed;
# carrying the stroke along with it is not. §6.2 closes the other door by
# holding any two line widths on a drawing at least 2:1 apart, so an
# outline drawn 1,53 heavier one way than the other cannot be defended
# as a deliberate second weight either.
#
# No ``stroke-width`` can put an uneven viewport back, the width the
# reader measures depending on the direction the line runs in. Two
# constructs can, and the first is not available here:
#
# - ``vector-effect="non-scaling-stroke"`` says it directly and browsers
#   honour it. **svglib has no notion of the property** (grep it), so
#   the PDF/PNG backend strokes the scaled geometry and drops the
#   attribute without a word, and ``export._reject_unsupported`` does
#   not catch it because an attribute it has never been taught is one it
#   does not look for. Measured through ``export.to_png`` on a rule
#   stretched 3:1, the raster is byte-identical with the attribute and
#   without it. Emitting it would leave the .svg right and every
#   exported sheet and every gallery PNG wrong, which is the worst of
#   the three states because it looks fixed.
#
# - Rewriting the artwork's coordinates at the placed size, which is
#   this. It costs a definition per placed size, which the sheet was
#   already paying (see _size_tag), and the arithmetic is exact but for
#   the last bits of a float.
#
# Baked and not merely straightened, because the same rewrite is what
# rounds out the *four vendored families* whose own wrapper group is
# uneven before any placement touches them (see _uneven). Those draw an
# elliptical pen at their natural size, which no care at the <use> could
# have fixed.

def _nominal(width: float, gx: float, gy: float) -> float:
    """What *width* stands for on the sheet under ``scale(gx, gy)``.

    The generator divides by this same geometric mean when it bakes the
    weight in (``scripts/vendor_symbols.py``), so the two are inverses
    and a vendored outline reads back as exactly the 2.0 it was drawn to
    be. The mean rather than either axis because it is the factor that
    leaves the pen's *area* alone, and because for the 138 families
    whose wrapper is uniform the choice does not arise: ``sqrt(k*k)`` is
    ``k``.

    Magnitudes, a mirror being a negative scale that turns no pen over.
    """
    return width * math.sqrt(abs(gx * gy))


# How each attribute answers to the map, by name. A *point* takes the
# scale and the translation; a *length* takes the scale alone, and
# unsigned, since a mirror turns the drawing over and no drawn width is
# negative. ``rx``/``ry`` cover both the ellipse radii and a rect's
# corner rounding, being the same lengths on the same axes; ``r`` is
# handled apart, a circle scaled unevenly not being a circle.
_X_POINTS = {"x", "x1", "x2", "cx"}
_Y_POINTS = {"y", "y1", "y2", "cy"}
_X_LENGTHS = {"rx", "width"}
_Y_LENGTHS = {"ry", "height"}

_TAG = re.compile(r'<(/?)([A-Za-z][\w.-]*)((?:\s+[\w:.-]+="[^"]*")*)\s*(/?)>')
_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')
# Absolute moves, lines, cubics and elliptical arcs, and how many
# numbers each takes.
#
# Everything but the arc is a list of *points*, so an axis-aligned scale
# is applied to each in turn and a cubic needs nothing the line does not
# -- the image of a Bezier under an affine map is the Bezier through the
# mapped control points, exactly. The arc is the one that has to be
# recomputed rather than scaled, which is what :func:`_scaled_ellipse`
# is for.
#
# A **relative** command is still refused, and deliberately: its numbers
# are displacements, so the scale applies and the translation must not,
# and quietly adding it to this table would apply both. Nothing in the
# library emits one. ``H``/``V`` are refused for a related reason -- a
# lone number that is an x on one and a y on the other does not fit the
# alternating map below. Both are a few lines to support on the day a
# drawing needs them, and an error until then, as
# ``export._reject_unsupported`` does it.
_PATH_ARITY = {"M": 2, "L": 2, "C": 6, "A": 7, "Z": 0, "z": 0}
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _art(v: float) -> str:
    """A number in a symbol's own coordinates.

    Six decimals, four more than the sheet coordinates around it get
    (:func:`_num`): these are products of numbers the artwork already
    carried, and rounding them to the drawing's own precision would be a
    *geometry* change made in the course of fixing a *weight*.
    Fixed-point rather than significant figures so a small number never
    comes out in exponent notation, which SVG accepts and no other
    number in the file is written in.
    """
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0", "0") else s


def _affine(transform: str) -> "tuple[float, float, float, float]":
    """A symbol's transform as the map ``(sx, sy, tx, ty)`` it is.

    The library writes two things and only two: the ``scale()`` a
    vendored stencil is reproportioned by, and the ``translate()
    scale(-1, 1)`` that turns a reducer end for end into an expansion.
    Both are diagonal, which is what lets the flattening below be
    arithmetic on each number in turn rather than a matrix applied to a
    point; a rotation or a skew is not, and is refused rather than
    silently flattened as though it were.
    """
    sx = sy = 1.0
    tx = ty = 0.0
    for op, args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", transform):
        v = [float(t) for t in args.replace(",", " ").split()]
        if op == "translate":
            # Composed on the right: each op is stated in the frame the
            # ones before it have established.
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
    """The ellipse ``scale(ax, ay)`` makes of *rx*, *ry*, *rot*.

    An axis-aligned scale of a *tilted* ellipse is still an ellipse, but
    with different radii and a different tilt, so the arc's parameters
    have to be recomputed rather than scaled. The ellipse is the image
    of the unit circle under ``R(rot) diag(rx, ry)``; the scale composes
    on the left, and the singular value decomposition of the product
    hands back the new radii and tilt directly. The sweep flag is
    untouched because both scales are positive, and the large-arc flag
    because neither depends on the frame.

    One family needs this -- the domed vessel, whose arcs are vendored
    at a tilt of 179,97 degrees -- and only when something stretches it.
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
            # The large-arc flag is a property of the arc; the sweep
            # flag is a handedness, and a map that turns the plane over
            # reverses it. The two are written back as the integers they
            # are, since a round trip through float would print them
            # "1.0" and the arc grammar takes a single digit.
            sweep = int(nums[4]) if ax * ay > 0 else 1 - int(nums[4])
            out += [_art(rx), _art(ry), _art(rot), str(int(nums[3])), str(sweep),
                    _art(nums[5] * ax + ex), _art(nums[6] * ay + ey)]
        else:
            out += [_art(n * ax + ex if k % 2 == 0 else n * ay + ey)
                    for k, n in enumerate(nums)]
        i += 1 + arity
    return " ".join(out)


def _scaled_points(points: str, m: "tuple[float, float, float, float]") -> str:
    """One ``points`` attribute with *m* folded into its numbers."""
    ax, ay, ex, ey = m
    v = [float(t) for t in points.replace(",", " ").split()]
    return " ".join(
        f"{_art(v[i] * ax + ex)},{_art(v[i + 1] * ay + ey)}" for i in range(0, len(v), 2)
    )


def _scaled_element(name: str, attrs: "list[tuple[str, str]]",
                    m: "tuple[float, float, float, float]",
                    gx: float, gy: float, self_closing: str) -> str:
    """One drawn element, rewritten as it would look under the map *m*.

    *gx*, *gy* are the artwork's *own* share of that map's scale -- its
    groups, without the placement -- and are what the weight is read
    back through. The weight is therefore independent of the box: a
    symbol drawn to a 2.0 outline comes out declaring 2.0 whatever size
    it was placed at, which is ISO 15519-1 §11.1.3 in one line of code.
    """
    ax, ay, ex, ey = m
    src = dict(attrs)
    # A rect is stated as one corner and two lengths, and a map that
    # turns an axis over moves the corner it is stated from to the other
    # end. Both ends are mapped and the near one taken, so the rectangle
    # covers the same ground whichever way round the map is.
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
            # A glyph has no direction to be measured along, so an
            # uneven scale has no size to give it. The mean keeps the
            # lettering a legal character height rather than a stretched
            # one (ISO 15519-1 §11.4.1).
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
    """*svg* redrawn at ``scale(fx, fy)``, scale groups flattened out.

    The drawing is unchanged -- every point lands where the scale would
    have put it -- and what changes is that no scale is left above any
    stroke, so each ``stroke-width`` is the width the reader measures,
    in both directions, at the weight the symbol's author drew.

    A no-op wherever the scale over the ink is already even, which is
    the great majority: a uniform wrapper is harmless, the ``<use>``
    viewport divides back out exactly (:func:`_at_pen_scale`), and
    leaving those alone keeps the ``<defs>`` recognisable as the
    vendored stencil.
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
            # A group carrying nothing but the transform has nothing
            # left to say once the transform is in the numbers.
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
    """Keep a symbol's lettering readable under a placement.

    Flipping a motor-operated valve to put its operator below the line
    is a statement about the *equipment*, not about the letter stamped
    on it: the box moves, the "M" inside it does not turn upside down.
    The transform on the ``<use>`` reaches the glyphs as readily as the
    strokes, so each text is wrapped in the inverse of that transform
    about its own anchor. The anchor still lands where the flip puts it;
    only the orientation is undone.
    """
    if not (rot or mirror_x or mirror_y):
        return svg

    def wrap(match: "re.Match[str]") -> str:
        tx, ty = float(match.group(1)), float(match.group(2))
        # Pivot on the glyph's visual centre, not its anchor: `y` is a
        # *baseline*, and reflecting one leaves the letter hanging off
        # the top of the box it is stamped in, the glyph body sitting
        # above the line rather than astride it. Cap height is ~0.7em,
        # so the middle of a capital is ~0.35em above the baseline. `x`
        # needs no such correction: these are all text-anchor="middle".
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
    """A placement's *reflection content*, as a pair of axis flips.

    The eight placements a unit may take are the symmetries of a square,
    and they split in two. Four leave the axes alone -- the identity,
    the two mirrors, and the **half turn, which is exactly the two
    mirrors composed** -- so each is some combination of ``scale(-1,
    1)`` and ``scale(1, -1)`` about the box's centre, which is what this
    returns. The other four swap the axes: the quarter turns, and each
    with a mirror on top.

    That split is the one a directional mark cares about and the one the
    arithmetic cares about, which is not a coincidence. An axis flip
    commutes with the per-axis scaling that fits a symbol into its box,
    so it can be cancelled exactly inside the definition; a quarter turn
    does not, and on a box that is not square it cannot be. An axis flip
    also lands a mark somewhere else on a drawing the reader still sees
    the same way up -- which is how a cooler comes to be drawn as a
    heater -- where a quarter turn turns the box with it.

    So ``orientation=180`` is not a turn as far as the mark is
    concerned: it is both mirrors at once, and reverses the arrow as
    either would.
    """
    half = rot == 180
    return (mirror_x != half, mirror_y != half)


def _upright_artwork(svg: str, w: float, h: float,
                     mirror_x: bool, mirror_y: bool) -> str:
    """Keep a *directional* drawing saying the same thing under a flip.

    The lettering problem one level out. A cooler is the heater's circle
    and zigzag with the arrowhead moved to the other end of the
    diagonal, and nothing else tells the two apart, so a flipped cooler
    is not a cooler drawn the other way round: it is the heater, drawn
    where the author asked for a cooler. What the flip was asked for is
    the *nozzles* on the other side -- ``examples/10_ethanol_pfd`` flips
    one to put the condenser's shell inlet underneath, so the overhead
    rises into it dead straight -- and the ports move under the
    placement transform however this leaves the ink.

    So the flip is undone inside the definition, about the symbol's own
    centre lines, and the ``<use>`` reapplies it: the two cancel
    exactly, an axis flip commuting with the per-axis scaling that fits
    the artwork into its box, so the drawing lands where it was drawn
    while the nozzles go where the flip puts them.

    *mirror_x* and *mirror_y* are the placement's whole reflection
    content and not only what the caller spelled ``mirrored=``: a half
    turn is both flips composed and reverses the mark as either one
    does, so it arrives here as both. :func:`_reflections` works that
    out, and is also where the quarter turn is left alone -- it takes
    the mark onto ground no upright drawing of either symbol occupies,
    and turns the box with it. See
    :attr:`pandid.render.symbols.Symbol.directional`.

    Only the whole drawing, never part of it: on the one family that
    declares this the artwork *is* the statement, a circle with the
    zigzag and the arrow both on its centre. Held still it stays exactly
    as vendored, which is what the check in
    ``tests/test_symbol_invariants`` measures the flipped nozzles
    against.
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


# Standard page sizes in millimetres, landscape, straight from ISO 216.
# Held in millimetres because that is what the sizes are defined in:
# deriving each from the last by doubling accumulates ISO's per-size
# rounding, which is how A1 and A0 came out a millimetre short.
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
    ``width_mm``/``height_mm`` are the physical size the SVG declares,
    so the sheet prints and converts to PDF at exactly its ISO size
    rather than at whatever the consumer assumes a pixel is worth.
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
    """Resolve ``page_size``; ``None`` fits the sheet to the drawing."""
    if page_size is None:
        return None
    dims = _PAGE_SIZES.get(page_size.upper())
    if dims is None:
        raise ValueError(
            f"Unknown page size {page_size!r}; use one of {', '.join(_PAGE_SIZES)}, "
            "or omit page_size to fit the sheet to the drawing."
        )
    return _Sheet(page_size.upper(), *dims)


# The frame the sheet is ruled with: sheet furniture, a statement about
# the paper rather than about the diagram drawn on it. A PFD carries a
# zone frame as readily as a P&ID does.
_BORDERS = ("none", "zone")
# Which drawing this is, a statement about the conventions it is read
# by -- and about which clause of ISO 10628-1 governs what it has to
# carry. Two questions read it: :func:`draws_arrowheads` and
# :func:`tabulates_boundary_flows`.
#
# One value per clause of 10628-1 4: a block flow diagram answers 4.2, a
# process flow diagram 4.3, a P&ID 4.4. Three kinds and not two, because
# ``12_block_flow_diagram`` is a BFD drawn with ``Block`` and had no way
# to say so, so it was checked against 4.3.2 -- a clause that does not
# reach it -- and reported for a stream table its own clause never asked
# for.
_DIAGRAMS = ("pfd", "p&id", "bfd")
# One accepted spelling per value, plus whatever the caller can
# reasonably be expected to type for it.
_ALIASES = {"pid": "p&id", "p&id": "p&id", "pfd": "pfd", "bfd": "bfd"}


def _canon(value: str) -> str:
    """Fold a diagram name to the one spelling the table keys on.

    Case is folded and the ampersand-less ``"pid"`` is read as
    ``"p&id"``. This package spells the name with the ampersand
    everywhere else, down to the distribution, so an engineer typing
    ``"P&ID"`` is typing the real name; ``"pid"`` is the spelling
    already published and stays working. Nothing else is guessed at.
    """
    return _ALIASES.get(value.strip().lower(), value)


def _resolve_sheet(border: "str | None", diagram: "str | None") -> "tuple[str, str]":
    """The frame to rule and the drawing to rule it around.

    The two are independent: the frame is sheet furniture and a PFD
    carries the zone-ruled one as readily as a P&ID does. A name neither
    knows is a sheet the renderer cannot draw, so it raises rather than
    quietly handing back a plain PFD.
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


# What ``show_stream_table`` says when the table is to be a drawing in
# its own right rather than a block docked at the foot of a diagram.
TABLE_SHEET = "sheet"


def wants_table_sheet(show_stream_table) -> bool:
    """Is this render being asked for the stream table's **own sheet**?

    ``show_stream_table`` takes three answers: ``False``, no table;
    ``True``, the table docked at the foot of the diagram; and
    ``"sheet"``, the table as a full drawing of its own -- border, title
    strip, drawing number -- with no diagram on it at all.

    A third answer on the keyword that already asks for the table,
    rather than a tenth keyword on the four calls that render. It is a
    property of the *call* and not of the flowsheet -- which sheet this
    file is, not how the table is drawn -- so it does not belong beside
    :class:`~pandid.document.StreamTableOptions`; and one call still
    writes one file, so it is not a flag that makes ``render()`` emit
    two. ``debug`` grew from a flag into ``bool | float`` in these same
    signatures for the same reason: the question had a third answer, not
    a second question.

    A spelling neither backend knows is refused here rather than read as
    truthy, which is what would have drawn the whole table onto the
    diagram for ``show_stream_table="own sheet"``.
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
    """Does this kind of drawing head the end of a process line?

    ANSI/ISA-5.1 draws process piping on a P&ID as plain line: flow
    direction is read off the equipment and the line list, so an
    arrowhead at the end of every run is a PFD convention.

    A block flow diagram heads its lines, which is why this is a
    question about the P&ID alone and not about "is this a PFD". ISO
    10628-1:2014 4.2.2 c) is the item that puts flow direction among a
    block diagram's minimum content, and a rectangle with a name in it
    carries the direction nowhere else.
    :func:`tabulates_boundary_flows` is the other question this name
    is read for, and the two answer differently on a BFD -- which is
    the whole reason there are two of them.

    Public, and asked rather than open-coded, because two callers need
    the answer and only one is the renderer.
    :func:`pandid.validate.validate` reports nozzles pitched inside the
    heads they carry, and on a sheet that draws none there are no heads
    to be inside of -- a finding about ink the drawing does not contain
    is false however well the geometry is measured. Takes the argument
    in the spelling :meth:`pandid.flowsheet.Flowsheet.to_svg` takes it.
    """
    return _resolve_sheet(None, diagram)[1] != "p&id"


def tabulates_boundary_flows(diagram: "str | None") -> bool:
    """Must this kind of drawing state the *rate* of what crosses its edge?

    True for a process flow diagram alone. ISO 10628-1:2014 4.3.2 d) is
    where that sits in a PFD's minimum content; a P&ID answers 4.4.2
    instead, and a block flow diagram answers 4.2, whose minimum content
    is 4.2.2 -- the flow rates are listed a clause later, under 4.2.3,
    which is the *additional* information a block diagram may also
    carry.

    So the finding that reads this, ``stream-table-missing``, is silent
    on both of the other two, and for two different reasons: it is not
    the P&ID's clause, and on the BFD it is not a *shall*.

    Public and asked rather than open-coded for the reason
    :func:`draws_arrowheads` is, and separate from it because the two
    part company exactly here: a BFD draws the arrowhead and owes no
    flow rate. Read as one boolean, ``12_block_flow_diagram`` could only
    be a sheet that tabulates or a sheet without arrows, and it is
    neither. Takes the argument in the spelling
    :meth:`pandid.flowsheet.Flowsheet.to_svg` takes it.
    """
    return _resolve_sheet(None, diagram)[1] == "pfd"


def check_connections(value) -> None:
    """Reject a joint with no mark, naming the ones there are.

    Takes the sheet's spelling or a stream's: a stream may state its two
    ends separately, so a pair is as valid a value as a name and is
    checked a name at a time.
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
    """Reject a hop direction that is neither of the two, naming them.

    Every other sheet option this module takes is checked against its
    own closed set; this one was not, and the reason it went unnoticed
    is the reason it matters. ``jump_direction`` is read where the hops
    are *drawn*, as ``== "vertical"`` and ``== "horizontal"``, so a
    misspelling is not a value the renderer rejects -- it is a value
    that matches neither branch, and the sheet quietly comes out with no
    hops at all. A drawing where two crossing lines are drawn straight
    through each other says the lines are joined, and nobody was told.

    Checked whatever the sheet turns out to hold, and that is the point
    of a separate function: a sheet with nothing crossing on it draws
    the same picture for every spelling, so the one render that could
    have caught the typo by its result is the render that cannot.
    """
    if value not in JUMP_DIRECTIONS:
        raise ValueError(
            f"Unknown jump_direction {value!r}; use one of "
            f"{', '.join(JUMP_DIRECTIONS)}."
        )


def check_crossing_style(value) -> None:
    """Reject a crossing mark this library cannot draw, naming the ones
    it can.

    :func:`check_jump_direction` beside it, one question further on, and
    for exactly the same reason: ``crossing_style`` is read where the
    marks are *drawn*, so a misspelling would not be a value the
    renderer rejects but one that matches no branch -- and the sheet
    would come out drawn some other way with nobody told. An author who
    typed ``"break"`` and got the arc has a drawing they did not ask for
    and would find out from a reader.

    Checked whatever the sheet turns out to hold, and that is why it
    lives here rather than in ``_draw_streams``: a sheet with nothing
    crossing on it draws the same picture for every spelling, so the one
    render that could have caught the typo by its result is the render
    that cannot.
    """
    if value not in CROSSING_STYLES:
        raise ValueError(
            f"Unknown crossing_style {value!r}; use one of "
            f"{', '.join(repr(name) for name in CROSSING_STYLES)}."
        )


def sheet_connections(diagram: "str | None",
                      connections: "str | None") -> "str | None":
    """The joint a sheet marks by default, or ``None`` if it marks none.

    The ``None`` is the load-bearing part and is not the same answer as
    ``"none"``. ``"none"`` is a P&ID asked about its joints that has
    declined to say, so one line on it may still say otherwise; ``None``
    is a drawing on which the question does not arise, and nothing a
    stream states can reopen it.

    That distinction is ISO 15519-2:2015's. Table 5 (p. 19) counts, among
    the *basic* information for a P&ID, the **specific** symbols for
    process equipment, prime movers, valves, actuators and connections;
    Table 4 (p. 17) allows the PFD only **general** symbols for its
    connections. A flange face is as specific as a connection gets, so
    ``connections="flanged"`` on a PFD draws nothing.

    Public and asked rather than open-coded for the reason
    :func:`draws_arrowheads` is: the draw.io exporter needs the same
    answer and is not the renderer.
    """
    if connections is not None:
        check_connections(connections)
    if _resolve_sheet(None, diagram)[1] != "p&id":
        return None
    return connections or "none"


def resolve_connections(s, default: "str | None") -> "tuple[str, str]":
    """What a stream says about its two joints, ``(source, dest)``.

    ``Stream.ends`` unset means "whatever the sheet said", the shape a
    valve station's ``tag_scheme`` override takes and for the same
    reason: an author has to be able to say the *opposite* of the sheet,
    both ways round, or a mostly-welded sheet with three flanged joints
    and a mostly-flanged sheet with three welded ones cannot both be
    written. So an unset stream inherits and a set one wins, including
    winning with ``"none"``.

    A pair states the two ends apart, in the order they were connected:
    ``connect(a, b)`` then ``ends=("flanged", "none")`` is the joint at
    *a* flanged and the joint at *b* not.
    """
    if default is None:
        return ("none", "none")
    ends = getattr(s, "ends", None) or default
    return (ends, ends) if isinstance(ends, str) else (ends[0], ends[1])


def _fit_scale(dw: float, dh: float, free) -> float:
    """The uniform scale putting a ``dw`` x ``dh`` drawing in *free*.

    Never enlarges: sheet furniture is drawn at a fixed size, so blowing
    a small drawing up to fill the page would swell its line weights and
    lettering out of proportion to the border and title strip around it.
    """
    _, _, fw, fh = free
    return min(1.0, fw / dw if dw > 0 else 1.0, fh / dh if dh > 0 else 1.0)


def _scale_text(s: float) -> str:
    """A fit scale as a title-block ratio."""
    return "1:1" if s >= 1.0 else f"1:{1 / s:.3g}"


# Findings a renderer raises about text that did not fit the cell drawn
# for it, as against the validator's findings about the diagram.
_FIT_CODES = ("text-truncated", "text-overruns-cell")

#: The stream table's own sheet, carrying no drawing number. Two sheets
#: of one set are told apart by their numbers, and this one has none to
#: derive: see :func:`table_sheet_plan`.
TABLE_SHEET_UNNUMBERED = "table-sheet-unnumbered"

#: Every code the *renderer* puts on ``fs.warnings`` itself, as against
#: the validator's findings about the model. Replaced rather than added
#: to on each render, so a sheet redrawn after a fix stops reporting
#: what the last one found -- as true of a table sheet that has since
#: been given a number as of a crossing that has since been marked. The
#: draw.io exporter extends this with what only an export can find
#: (:data:`~pandid.render.drawio._EXPORT_CODES`).
_RENDER_CODES = _FIT_CODES + ("crossing-unmarked", TABLE_SHEET_UNNUMBERED)



def fit_issue(field: str, text: str, drawn: str,
              room: float, need: float) -> Issue:
    """One :data:`_FIT_CODES` finding, from what a cell was given and
    what it drew.

    The shape :data:`~pandid.render.furniture.Reporter` reports in, made
    into an :class:`~pandid.validate.Issue` here rather than in each
    backend: the draw.io exporter measures the same title strip with the
    same functions, and :func:`pandid.validate.model_issues` measures it
    with no file at all, so the sentence a reader gets must not depend
    on which of the three asked.

    The two widths are the actionable half of the finding, stated the
    way ``route-detour`` states its two lengths: how much room the cell
    has, how much the value wanted, and the ratio between them, which is
    what says whether a word has to come out or a whole phrase.
    """
    # A box given ``width=0`` has no ratio to state, so the ratio is
    # dropped rather than the finding.
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
    """A sheet too small for its furniture.

    Furniture is drawn at a fixed size, so this is an error no scale of
    the drawing can resolve. ``cause`` names the widest piece, which is
    the one worth shortening: a stream table sized to its own contents
    is usually what pushed a sheet over, and "the furniture does not
    fit" does not say which furniture.
    """
    blame = f" The widest piece is {cause}." if cause else ""
    return ValueError(
        f"The sheet furniture does not fit page size {sheet.name}: the border, title strip "
        f"and docked boxes need at least {need_w:.0f}x{need_h:.0f}px of the "
        f"{sheet.width:.0f}x{sheet.height:.0f}px sheet.{blame} Use a larger page_size, or omit "
        "page_size to fit the sheet to the drawing."
    )


# The title strip is placed by the same band arithmetic as the boxes the
# caller docked, but it is not an object of the caller's -- a zone-ruled
# sheet rules a strip whether or not a title block was filled in -- so
# it stands in the columns as a sentinel. Naming it is what an error
# that has to say *which* piece of furniture will not fit needs.
TITLE = "\x00title"
_FURNITURE_NAMES = {TITLE: "the title strip"}


def _furniture_name(obj) -> str:
    if isinstance(obj, str):
        return _FURNITURE_NAMES.get(obj, obj)
    if isinstance(obj, F.StreamTable):
        return "the stream table"
    title = getattr(obj, "title", "")
    return f"the {title!r} box" if title else "an untitled annotation box"


# The two comments that fence the provenance block, for the reader who
# has to *ignore* it: a version string in the body of an SVG would move
# every golden fixture and every committed gallery sheet on each
# release. ``tests/test_golden.py`` drops everything between these two
# lines before comparing -- one slice, not a regex over the document --
# and keeps the fences, so a golden still records that the block is
# there and where in the file it sits.
#
# **Anything version-dependent must go inside the fence.** ``<title>``
# stays outside on purpose: it carries the sheet's own name and no
# version, so it is real content and belongs in the comparison.
PROVENANCE_OPEN = "  <!-- pandid:provenance -->"
PROVENANCE_CLOSE = "  <!-- /pandid:provenance -->"

_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _sheet_title(fs: "Flowsheet") -> str:
    """What this drawing is called.

    The title block's title when the sheet has been given one -- the
    title the drawing is *issued* under, and what is lettered on it --
    and the flowsheet's own name otherwise. Either can be empty, and an
    empty accessible name is worse than none, so the caller drops
    ``<title>`` rather than emitting a blank one -- and a title of
    nothing but spaces is one of those, being *truthy* and announced by
    a screen reader as silence. Both are stripped to the blank they
    mean, so the fallback to the flowsheet's name happens for either.

    Read through the strip's own :func:`~pandid.render.furniture._field`
    rather than restated here. Which of the two names the document is
    *this* function's decision -- the accessible name is not title-strip
    ink and does not follow the strip's fallbacks -- but what counts as
    the author having stated a title is one question, and asked twice it
    was answered twice: a copy of the read here kept the truthy test
    after the strip stopped using it, so ``title=0`` would have been
    lettered on the sheet and dropped from the document's name.
    """
    tb = fs.title_block
    title = F._field(tb, "title") if tb is not None else ""
    return title or str(fs.name or "").strip()


def _table_sheet_title(fs: "Flowsheet", options) -> str:
    """What the stream table's own sheet is called, as a document.

    The drawing's title and the sheet's, in the order the strip letters
    them. Two sheets of one drawing set are two documents, and a reader
    with both open has only this to tell them apart: left at the
    drawing's title alone, the table sheet and the diagram it belongs to
    would answer to the same accessible name.
    """
    parts = [p for p in (_sheet_title(fs), options.sheet_subtitle) if p]
    return " - ".join(parts)


def _provenance(fs: "Flowsheet", title: "str | None" = None) -> list[str]:
    """The document's title and the block saying what drew it.

    Openly, in a comment and in a real ``<metadata>`` element, and never
    as a white-on-white string in the drawing: an invisible run of text
    inside a controlled engineering document comes out on
    select-all-copy and in any text extractor, and ends up pasted into a
    client deliverable nobody chose to put it in.

    ``<title>`` is the first child of ``<svg>`` because that is where a
    browser looks for the tooltip and where a screen reader looks for
    the document's accessible name; it holds the sheet's own title (see
    :func:`_sheet_title`) and nothing else. ``dc:title`` repeats it
    inside the metadata, where a cataloguing tool reads it, and
    ``dc:creator`` names what drew the file.

    ``title`` states that name instead of reading it off the flowsheet,
    for the one sheet that is not the diagram: the stream table's own
    (:func:`_table_sheet_title`).
    """
    from pandid.render import HOMEPAGE, generator
    who = generator()
    if title is None:
        title = _sheet_title(fs)
    lines = []
    if title:
        lines.append(f"  <title>{escaped(title)}</title>")
    lines.append(PROVENANCE_OPEN)
    # The colon is not a style choice: an XML comment may not contain
    # "--" anywhere (XML 1.0 §2.5), so "pandid 0.1.2 -- https://..."
    # would make every sheet malformed.
    lines.append(f"  <!-- Generated by {who}: {HOMEPAGE} -->")
    lines.append("  <metadata>")
    lines.append(f'    <rdf:RDF xmlns:rdf="{_RDF_NS}" xmlns:dc="{_DC_NS}">')
    # ``rdf:about=""`` is the RDF spelling of "this document" -- the
    # file, not the plant it draws.
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
    """The SVG document around a sheet's ink: the declaration, the
    element, the provenance block and the paper, then *body*.

    Two sheets come out of this renderer -- the diagram and the stream
    table's own sheet -- and both are the same document with different
    ink in it. Written twice, they would be free to disagree about the
    one thing every consumer of the file reads first: the physical size
    it prints at.

    ``viewbox`` is the canvas rectangle in drawing units. A named page
    size additionally declares its *physical* size, so the sheet prints
    and converts to PDF at exactly that ISO size instead of at whatever
    the consumer takes a user unit to be worth; a sheet fitted to its
    contents has none to declare and stays in user units.
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
    # What drew the file, and what it is called. First children of
    # <svg>, before any ink: <title> is the document's accessible
    # name and is only picked up there. See :func:`_provenance`.
    lines.extend(_provenance(fs, title))
    lines.append('  <!-- Background -->')
    lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="white" />')
    lines.extend(body)
    lines.append('</svg>')
    return "\n".join(lines)


class TableSheetPlan(NamedTuple):
    """A stream-table sheet as geometry, before either backend draws it.

    ``table`` is the wrapped table and ``left``/``top`` the corner its
    block stack is drawn from; ``block``/``name``/``date`` are what the
    title strip says and ``strip`` the rectangle it says it in;
    ``frame`` is the drawing frame the border is ruled on.

    ``findings`` is what this sheet has to report about itself, for
    whichever backend drew it to put on ``fs.warnings``. It is carried
    here rather than raised because the plan is worked out twice -- once
    before the model is laid out, to refuse a render that cannot happen,
    and once to draw from -- and a warning emitted from the first of
    those would be a warning about a file that was never written.
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
    """Lay out the stream table's own sheet: the table wrapped to the
    page, the strip docked, and the frame around both.

    **Both backends ask this**, exactly as both ask :func:`dock` where a
    legend goes. Everything here is a statement about a sheet rather
    than about a file format -- how many streams a block holds, what the
    strip says, where the frame is ruled -- and a second opinion about
    any of it would be a table sheet that exported differently from the
    one that printed.

    The table is the sheet's **body** rather than a piece of docked
    furniture, which is the one structural difference from
    :meth:`SvgRenderer._place_furniture`. Docked, it would share the
    bottom band with the strip and be ruled to what the strip left of
    the page width -- some six hundred units of a table sheet's whole
    reason for existing. So only the strip is docked, and the table
    takes the region that leaves, exactly as a diagram does.

    The strip is drawn whether or not the flowsheet carries a title
    block: a sheet issued into a set without one cannot be filed, and
    the acceptance for this drawing is that it carries a border, a title
    block and a drawing number. What it says is
    :func:`~pandid.document.table_sheet_block`'s.

    The flowsheet's annotation boxes are **not** repeated here. An
    equipment list schedules the plant the diagram draws and a legend
    explains its symbols; neither is about this sheet, whose body is the
    table and nothing else. ``fs.annotations`` is one list belonging to
    one drawing, so there is nowhere yet to say *this box, on that
    sheet* -- that is a sheet set's question, and #407's.

    Raises :class:`ValueError` for a flowsheet with nothing to tabulate,
    and the page's own "too small" for a table the paper cannot hold.
    """
    from pandid.document import TABLE_SHEET_SUFFIX, table_sheet_block

    # What the page leaves the table to wrap into: the frame, less the
    # clearance the dock keeps between the frame and whatever it frames.
    # A sheet with no page has no width to wrap against and takes the
    # table in one block, however wide that comes to.
    room = None if sheet is None else (
        sheet.width - 2 * (F.OUTER_MARGIN + F.ZONE_BAND) - 2 * F.INNER)
    table = F.stream_table_sheet(fs, room)
    if table is None:
        # Refused rather than drawn empty: what was asked for is a sheet
        # whose whole body is the table, and there is no table. See
        # :func:`~pandid.render.furniture.stream_table_layout` for the
        # two ways that happens.
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
            # The table is measured from its contents and wrapped to the
            # page, so what can be left over is depth -- more rows than
            # the paper takes -- or a block one column wide that is
            # still too wide, which is a section heading or a single
            # value no page this size can hold.
            raise _too_small(page, page.width - fw + table.w,
                             page.height - fh + table.h, "the stream table")
    _obj, sx, sy, sw, sh = placed[0]
    left, top = F.table_sheet_origin(table, free)
    date = block.date or datetime.now().strftime("%Y-%m-%d")
    findings = []
    if not block.drawing_number:
        # There is nothing to derive a number from, so the sheet is
        # drawn unnumbered and says so. **Drawn, not refused**: a
        # flowsheet is not obliged to carry a title block anywhere else
        # in this library, and refusing here would make the simplest
        # possible table sheet -- build a flowsheet, render its table --
        # the one that raises. But an unnumbered sheet is a real defect
        # rather than a style: it is the sheet's own identity missing,
        # and the two documents this call is one of can then only be
        # told apart by their titles.
        #
        # Soft rather than hard for the reason `boundary-flow-missing`
        # is soft: the sheet draws, and what is absent is a number
        # nobody but the author has. Nothing here can invent one -- a
        # drawing number is a filing identity issued by the office that
        # owns the set, and a number made up from the flowsheet's name
        # would be worse than a blank, because it would look issued.
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
    """Refuse the keywords a backend does not know, naming them.

    Both renderers end their signature with ``**opts``, because
    :class:`~pandid.render.Renderer` is a protocol every backend has to
    answer and a future one will take arguments these two never heard
    of. What that spelling must not mean is **accepted and dropped**: an
    argument a backend swallows is a caller told something false about
    the file they now hold, and it is silent in exactly the case that
    matters -- ``DrawioRenderer().render(fs, debug=True)`` returned a
    57-kilobyte document with no overlay in it and no complaint, because
    a ``.drawio`` file has no overlay to draw and nothing said so.

    Raised for the whole set rather than the first one, for the reason
    :meth:`~pandid.flowsheet.Flowsheet._raise_on_errors` names every
    error it found: an author who misspelled two keywords should not
    meet them one render at a time.

    A closed door rather than a longer list of arguments to remember to
    forward. The defect this closes was one argument going unchecked;
    the fix is that an *unknown* argument cannot go unchecked, so the
    next keyword added to a render call cannot repeat it.
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
    """Everything a render can refuse about the arguments it was given,
    asked **before the sheet is laid out or routed**.

    Laying a sheet out and routing it writes a ``Frame`` onto every unit
    and a ``Route`` onto every stream. A render that raises after that
    has changed the flowsheet on its way to failing: the author fixes
    the typo, renders again, and the second render reuses geometry the
    first one resolved -- and if the argument that raised was one that
    *decides* geometry, the sheet they finally get was laid out for the
    call that failed. The rule this restores is
    :meth:`~pandid.flowsheet.Flowsheet._prepare_to_draw`'s own, and the
    reason ``pin-not-finite`` is checked before the router sees it: a
    render that cannot happen must not have happened halfway.

    So every one of these is a question about the *arguments* and the
    *model*, answerable with no geometry at all -- which page was named,
    how it is spelled, whether the table has anything in it, whether it
    fits the paper. The renderers ask the same questions again where
    they use the answers; asking twice is cheap (this measures strings)
    and is what lets a backend be called directly without losing a
    check.

    ``jump_direction``, ``crossing_style`` and ``connections`` are
    checked here **whether or not this sheet can show them**. That is the whole of their fix: a
    sheet with nothing crossing on it, or with no process line at all,
    draws the same picture for every spelling, so leaving the check to
    the drawing means the option is validated on the sheets that did not
    need validating and swallowed on the ones that did.
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
        # Refused rather than ignored, as a .drawio render refuses it:
        # the overlay draws the coordinates a ``pin()`` takes, and there
        # is nothing pinned on this sheet for it to be about.
        raise ValueError(
            "debug draws the coordinate overlay under a *diagram*, and "
            "show_stream_table='sheet' draws no diagram. Render the diagram "
            "to see the overlay, or drop debug=")
    # The plan is the check: a flowsheet with nothing to tabulate, a
    # page too small for the table, a table sheet numbered as the
    # diagram it belongs to. Its answer is thrown away and worked out
    # again to draw from, exactly as `title_strip_fit` runs the strip's
    # own layout and discards the ink -- one measurement, so what is
    # refused here is what would have been drawn there.
    #
    # Discarding the answer is not enough: measuring the table *reports*
    # (:func:`~pandid.render.furniture._report_unused_sections` writes a
    # `stream-table-section-unused` finding onto ``fs.warnings``), and a
    # finding left behind by a render that then raised is a finding
    # about a sheet nobody has. So the list is put back exactly as it
    # was, in a ``finally`` because the interesting case is the one that
    # raises. The render that follows measures again and reports then,
    # which is when there is a drawing for the finding to be about.
    #
    # Restored wholesale rather than by undoing what this call is known
    # to write: what a measurement reports is the measurement's
    # business, and a guard that named today's findings would go stale
    # the day another one is added.
    # The *same list*, refilled -- not a new list with the same
    # contents. A caller holding a reference to ``fs.warnings`` from
    # before this call has to keep seeing what the flowsheet sees, and
    # the writers below rebind the attribute rather than mutating it, so
    # putting the original object back is what restores both.
    was = fs.warnings
    contents = list(was)
    try:
        table_sheet_plan(fs, page)
    finally:
        was[:] = contents
        fs.warnings = was


class SvgRenderer:
    """Renders a Flowsheet to an SVG file using manual geometry."""

    def __init__(self, registry=None):
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

        Parameters
        ----------
        fs : Flowsheet
            The flowsheet to render.
        jump_direction : str
            Which of two crossing lines carries the crossing mark:
            ``"vertical"`` or ``"horizontal"``.
        crossing_style : str
            What that mark is: ``"arc"`` (the default), ``"gap"`` or
            ``"plain"``. See :data:`CROSSING_STYLES`. Any other spelling
            raises rather than being folded to the default.
        show_stream_table : bool | str
            ``True`` docks the stream property table at the foot of the
            diagram; ``"sheet"`` draws the table as a sheet of its own
            and no diagram at all. See :func:`wants_table_sheet`.
        border : str | None
            ``"none"`` for a plain sheet edge, ``"zone"`` for the
            zone-ruled drawing frame, lettered A.. top down and numbered
            1.. left to right. The flowsheet's title block and
            annotation boxes are drawn whichever is chosen. A table
            sheet rules the zone frame unless told otherwise: it is a
            drawing in its own right rather than a table on paper.
        diagram : str | None
            Which drawing this is: ``"pfd"`` (the default), ``"p&id"``,
            also spelled ``"pid"``, or ``"bfd"``. A P&ID draws its
            process lines without arrowheads; the other two head
            theirs.
        page_size : str | None
            Standard paper size (``"A4"`` through ``"A0"``), drawn at
            exactly that size, with the furniture docked to the sheet
            edges and the drawing fitted into what they leave. ``None``
            (the default) sizes the sheet to the drawing instead.
        connections : str | None
            The joint a P&ID marks on a stream that does not say its own
            (``"flanged"`` or ``"none"``), or ``None`` to mark nothing a
            stream has not stated. Ignored outside a P&ID, since a PFD's
            symbols are only ever general ones. See
            :func:`sheet_connections`.
        debug : bool | float
            Draw the coordinate overlay under the diagram: a ruled grid
            carrying its own coordinates, every unit's ``pin()`` anchor
            and every port. ``True`` rules it at the default spacing and
            a number sets that spacing. Off by default. See
            :mod:`pandid.render.debug`.
        """
        from pandid.portgeom import unit_box
        from pandid.render import debug as _debug
        # Resolved first, so a spacing the overlay cannot draw is
        # refused before a whole sheet has been built rather than after.
        reject_unknown_options("SvgRenderer.render()", opts)
        grid = _debug.resolve_spacing(debug)
        table_sheet = wants_table_sheet(show_stream_table)
        # Asked again here, and asked of the arguments this backend was
        # handed. `Flowsheet` asks before it lays the sheet out, which is
        # what keeps a refused render from having moved anything; a
        # caller holding a renderer directly has skipped that, and a
        # check that only the entry point ran is a check the backend
        # does not have. Both calls are the same function, so there is
        # one rule and two places that insist on it.
        check_render_arguments(
            fs, show_stream_table=show_stream_table, border=border,
            diagram=diagram, page_size=page_size, connections=connections,
            jump_direction=jump_direction, crossing_style=crossing_style,
            debug=debug)
        # A table sheet is a formal drawing rather than a table on
        # paper, so it rules the frame the reference sets do; the
        # diagram's own default stays the plain edge. Stated `border`
        # still decides either way.
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
        # What the *drawing* found, as against what the furniture did.
        # A separate list because it is filled much later -- the label
        # passes run after the sheet has been sized -- and because only
        # this one knows where a stream label ended up.
        self._findings: list[Issue] = []

        def report(field: str, text: str, drawn: str,
                   room: float, need: float) -> None:
            fit_issues.append(fit_issue(field, text, drawn, room, need))

        # Furniture belongs to the sheet, not to the border: a title
        # block or a docked box is drawn because it was supplied. A zone
        # border implies a formal sheet, which carries a title strip
        # whether one was filled in or not. A stream table is furniture
        # too, and the only kind :func:`~pandid.render.furniture.dock`
        # can place without help from any of the other three -- routing
        # it through the same call as they do is what keeps this
        # in agreement with the draw.io exporter, which docks everything
        # through that one function and knows no "plain sheet" case of
        # its own to disagree from.
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
            # Bare sheet: no border, no title block, no annotations and
            # no stream table either, so nothing was ever placed and the
            # frame is just the drawing's own bounds, margined.
            frame_x, frame_y = dx0 - margin, dy0 - margin
            canvas_width = (dx1 - dx0) + 2 * margin
            canvas_height = (dy1 - dy0) + 2 * margin

        # A cell that could not hold its text is a finding about this
        # render, so it joins the validator's on ``fs.warnings``.
        # Findings from an earlier render are dropped rather than added
        # to: a title shortened and re-rendered must stop warning about
        # the old one.
        #
        # A crossing drawn bare is the same kind of finding and is
        # replaced the same way: it depends on ``jump_direction``, which
        # is this render's option and not a property of the model, so
        # the validator cannot know it (:func:`unmarked_crossings`).
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
        # Where every line on the sheet runs. Both label passes below
        # write on an opaque halo and so have to be told, and this is
        # the first point where the answer exists: the routes are
        # settled and the balloons have stopped moving, so the impulse
        # lines are settled with them. See :func:`_ink`.
        ink = _ink(fs, jump_direction)
        # The letter codes written outside the balloons, placed before
        # anything that has to dodge them; see :func:`quadrant_labels`.
        # Drawn with the equipment tags at the end, on the same halo.
        quadrants = quadrant_labels(fs, jump_direction)
        drawing: list[str] = []
        # Every opaque white plate the sheet lays down, collected only
        # when the overlay is going to be drawn. The overlay is emitted
        # *under* the drawing, so a plate is the one thing that can
        # delete it outright and the only way to step clear is to be
        # told where they landed. With ``debug`` off the list is
        # ``None`` and not one of these boxes is computed.
        plates: "list[tuple[float, float, float, float]] | None" = (
            [] if grid is not None else None)
        drawing.extend(self._draw_units(fs, unit_labels, balloons, ink, joints,
                                        quadrants))
        drawing.extend(self._draw_streams(fs, jump_direction, unit_labels, arrows,
                                          plates, joints, crossing_style))
        # Instrumentation goes on over the lines: an impulse line runs
        # from the tap to the balloon, and the balloon's opaque body
        # then knocks out both it and any process line an in-line
        # element straddles.
        drawing.extend(self._draw_taps(fs))
        if balloons:
            drawing.append('  <g id="instruments">')
            drawing.extend(balloons)
            drawing.append('  </g>')
        # Equipment tags go on last, haloed, so no stream line strikes
        # through them, and the quadrant codes with them: a code is
        # lettering outside a symbol and wants the same halo.
        drawing.extend(self._draw_unit_labels(unit_labels + quadrants))
        # The label passes have run, so what a stream label's enclosure
        # was drawn over is now known; the furniture's findings were
        # already added above, and the stale ones of both kinds dropped
        # with them.
        fs.warnings = fs.warnings + self._findings

        # Placed last and drawn first. The overlay must sit *under*
        # every piece of the sheet's own ink -- it is scaffolding and
        # must not come between the reader and the drawing -- but it can
        # only choose paper the sheet has left clear once the sheet
        # exists. Splicing the result onto the head is what satisfies
        # both.
        #
        # It goes inside the fitted group for a separate reason: the
        # numbers it writes have to be the ones ``pin()`` takes, and a
        # fixed page scales that group, so the overlay is told the scale
        # and holds its lettering to a constant size on paper while
        # leaving its geometry in drawing units.
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
        """Transform centring the drawing in *free*, scaled to fit."""
        fx, fy, fw, fh = free
        dw, dh = dx1 - dx0, dy1 - dy0
        s = _fit_scale(dw, dh, free)
        return (f"translate({_num(fx + (fw - s * dw) / 2 - s * dx0)}, "
                f"{_num(fy + (fh - s * dh) / 2 - s * dy0)}) scale({s:.6g})")

    # --- furniture ----------------------------------------------------

    def _place_furniture(self, fs, st_layout, dx0, dy0, dx1, dy1, furniture, sheet,
                         border, report=None):
        """Dock furniture flush to the sheet *frame*, not the drawing.

        The frame is ruled into zones where the sheet asked for a
        border.

        Boxes are grouped into edge *bands* by ``align``; the frame
        grows outward from the diagram bounds just enough to hold them,
        and each box is placed flush against the frame edge its
        ``align`` names (inset by its ``margin``). A box with an
        explicit ``position`` is hand-placed instead. Given a *sheet*,
        the frame is the fixed page inset by the border, and the drawing
        is fitted into the region the bands leave.

        The band arithmetic is :func:`pandid.render.furniture.dock`'s,
        which is a statement about a *sheet* rather than about SVG and
        is shared with the draw.io exporter for that reason. What is
        left here is the drawing.

        Returns the outer canvas rect ``(x, y, w, h)`` and that free
        region, or ``None`` when the frame was grown to the drawing.
        """
        from pandid.document import TitleBlock, TableBox

        OUT = F.OUTER_MARGIN

        def measure(a):
            return F.measure_table(a) if isinstance(a, TableBox) else F.measure_annotation(a)

        def draw_box(a, x, y):
            furniture.extend(F.draw_table(a, x, y) if isinstance(a, TableBox)
                             else F.draw_annotation(a, x, y, report=report))

        # Title strip + stream table are bottom furniture, at the foot
        # of the bottom-right / bottom-left columns so the band maths
        # sizes the frame around them too. The strip stands in as a
        # sentinel (see TITLE); the stream table stands in as itself.
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
        # The scale cell reports the ratio the drawing was placed at,
        # which the dock has just settled. A frame grown to the drawing
        # has no fixed page and so no scale to state.
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
        """The stream table as a sheet of its own: border, title strip,
        drawing number, and the table for a body.

        The geometry is :func:`table_sheet_plan`'s, which the draw.io
        exporter asks for the same sheet; this strokes it.

        The scale cell is **ruled and left empty**. A table is not
        drawn to scale, so there is no ratio to write in the box -- but
        the box is the form's and not the drawing's, and #370 settled
        that it is ruled whether or not a sheet has a scale to state,
        because a band that gives its room back changes what
        ``drawing_number`` is budgeted. That argument does not stop at
        the diagram: a table sheet is a sheet of the same issue, filed
        by the same number, and its number has to survive the same
        width. See :func:`~pandid.render.furniture.title_strip_layout`.
        """
        fit_issues: list[Issue] = []

        def report(field: str, text: str, drawn: str,
                   room: float, need: float) -> None:
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
        """A fixed page carrying no furniture of its own.

        The stream table docks to the foot of the sheet and the drawing
        takes the region above it, which is what is returned.
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
        """The placement transform a symbol definition must bake in.

        Two things in a drawing belong to the *drawing* rather than to
        the attitude the equipment is installed in, and so have to
        survive the placement: its own lettering, which stays readable
        (:func:`_upright_text`), and a directional mark, which an axis
        flip reverses (:func:`_upright_artwork`). Each is undone inside
        the definition and reapplied by the ``<use>``.

        The identity for every symbol with neither -- the great majority
        -- so those keep sharing one definition and one id however they
        are placed.

        A directional symbol reports its placement's *reflection
        content* rather than the placement, that being the whole of what
        it bakes in: a half turn arrives as both flips
        (:func:`_reflections`) and a quarter turn as none, so
        ``orientation=90`` on an unflipped one still shares one
        definition and the four placements that flip it share three.
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

        One definition per ``(kind, variant)``, plus a suffix for
        whatever else is baked in rather than applied by the ``<use>``:
        the size a built-to-measure symbol was drawn at, the size a
        *resized* unit had its line weights compensated for (see
        :func:`_pen_scale`) or was redrawn at outright (see
        :func:`_fold`), and the counter-transform that keeps a symbol's
        lettering readable or its arrow pointing the way it was drawn.

        Through :func:`~pandid.render.escape.ident` for the reason
        :func:`arrow_marker_id` is: a ``kind`` is a key the author of a
        custom unit chooses, and every one this library ships is already
        a name, so the sanitising is a no-op on every sheet it draws and
        the guard is there for the kind nobody has written yet.
        """
        variant = getattr(u, 'variant', 'default')
        sym = self.registry.for_unit(u)
        body = u.kind if variant == "default" else f"{u.kind}_{variant}"
        body += sym.id_suffix + _size_tag(sym, u) + _xform_tag(*self._baked_xform(u))
        return ident("sym", body)

    def _defs(self, fs, arrows=True):
        lines = []
        # Sorted, not raw set order: set iteration depends on the
        # process hash seed, so an identical flowsheet would otherwise
        # emit byte-different SVG from run to run, breaking diffs,
        # caching and golden tests.
        used_colors = sorted({s.color or "black" for s in fs.streams})
        lines.append('  <defs>')
        # A sheet that draws no arrowhead defines none: only process
        # lines ever wore one, so on a P&ID the whole set is dead.
        for c in used_colors if arrows else ():
            lines.append(
                f'    <marker id="{arrow_marker_id(c)}" viewBox="0 0 10 10" '
                f'refX="10" refY="5" '
                f'markerWidth="{ARROWHEAD:g}" markerHeight="{ARROWHEAD:g}" '
                f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            )
            lines.append(f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{escaped(c)}" />')
            lines.append('    </marker>')

        # A symbol carrying its own lettering, or a directional mark,
        # needs one definition per placement transform in use, the
        # counter-transform being baked into the definition. A symbol
        # built to measure needs one per size, so the box it is placed
        # in is the box it was drawn in and the scale stays exactly 1. A
        # symbol some unit *resized* needs one per placed size too,
        # since the weight it is drawn at is compensated for that scale
        # (see _pen_scale) and a definition cannot carry two. Everything
        # else shares a single definition however it is placed.
        used: dict[tuple, tuple] = {}
        # Definitions some placement asks to fill a box of another
        # shape. A <symbol> scales its viewBox to fit and centres what
        # is left over, so a unit given a width and height of its own is
        # drawn smaller than the box with whitespace down one pair of
        # sides -- and portgeom, which maps its ports linearly onto the
        # box, then puts them out in that whitespace. The two are made
        # to agree by stretching the artwork wherever the symbol says it
        # may be (see Symbol.stretchable); where it may not, portgeom
        # follows the letterbox and the ports land on the drawing.
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
            # A definition redrawn at the placed size fills its box by
            # being the size of it, so it has no aspect ratio to give
            # up.
            if sym.stretchable and _reshapes(sym, u) and fold == (1.0, 1.0):
                stretched.add(key)
        for key in sorted(used):
            sym_id, sym, fold, pen, rot, mirror_x, mirror_y = used[key]
            # The redraw first, so everything after it -- the pen
            # division, the counter-transforms, the viewBox -- is stated
            # in the coordinates the definition will be written in.
            art = _baked(sym.svg, *fold)
            width, height = sym.width * fold[0], sym.height * fold[1]
            # Every weight the artwork was drawn at is baked to
            # :attr:`~.weights.LineWeight.EQUIPMENT`, whichever rung the symbol is
            # actually in (see :func:`_nominal`), so a trimmed symbol's
            # weight is divided out here rather than carried by `pen`,
            # which stays the *resize* factor alone and nothing else:
            # :func:`_size_tag` and the cache `key` above both read it
            # for that, and every symbol of one (kind, variant) is one
            # class, so folding the two together would buy the cache
            # nothing and cost `_size_tag` its meaning.
            stroke = pen * LineWeight.EQUIPMENT.width / _class_weight(sym).width
            # Either, never both. A directional symbol's *whole*
            # drawing is held still, lettering included, so a glyph
            # inside one would need the residual of the two rather than
            # its own counter-transform. No symbol carries both, and
            # test_a_directional_symbol_carries_no_lettering_of_its_own
            # says so over the registry rather than leaving this branch
            # to be trusted.
            if sym.directional:
                svg_str = _upright_artwork(_at_pen_scale(art, stroke),
                                           width, height, mirror_x, mirror_y)
            else:
                svg_str = _upright_text(_at_pen_scale(art, stroke), rot, mirror_x, mirror_y)
            if svg_str.startswith('<g'):
                inner = svg_str[svg_str.find('>') + 1:svg_str.rfind('</g>')]
                # preserveAspectRatio: stated only where a placement
                # reshapes the artwork, "none" and the "xMidYMid meet"
                # default being the same drawing whenever the scale is
                # uniform.
                fill = ' preserveAspectRatio="none"' if key in stretched else ''
                # overflow="visible": a <symbol> viewport defaults to
                # overflow:hidden, which clips the outer half of any
                # stroke whose geometry sits on the viewBox edge (an
                # ellipse with rx == w/2, say), so a circle renders thin
                # at its four cardinal points while the diagonals stay
                # full weight.
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
        from pandid.portgeom import unit_box

        lines = ['  <g id="units">']
        # Every symbol on the sheet, paired with the unit that drew it,
        # so a tag can step off somebody else's artwork the way it steps
        # off somebody else's line. Built once, being the same list for
        # every tag.
        #
        # The flange marks are in it under no unit at all, which is what
        # they are: a mark on a run belongs to the joint and not to
        # either end of it, and _tag_item's `v is not u` test then lets
        # every tag see every one of them.
        symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
        symbols += [(None, b) for b in flange_boxes(fs, joints)]
        # A letter code outside a balloon is under no unit either, and
        # for the same reason: it is lettering, not artwork, so every
        # tag has to see it and none of them owns it.
        symbols += [(None, b) for b in map(_unit_label_box, quadrants) if b is not None]
        for u in fs.units:
            f = u.frame
            out = balloons if u.kind == "instrument" else lines
            x, y = f.x, f.y
            # The tag, not the name: a symbol that repeats (a trip
            # square, a utility header flag) is drawn with the tag it
            # shares and named apart only so the flowsheet can address
            # each drawing of it.
            safe_name = escaped(u.tag)

            if u.kind in ("feed", "product"):
                lines.extend(self._draw_boundary(u, f, safe_name))
                continue

            sym_id = self._sym_id(u)
            u_width, u_height = f.w, f.h
            rot = int(getattr(f, "orientation", 0) or 0)
            mirror_x, mirror_y = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
            cx, cy = x + u_width / 2, y + u_height / 2

            # A quarter turn swaps the box the artwork is drawn into;
            # place that box centred on the frame so rotating it about
            # the centre lands it back on the frame exactly.
            if rot in (90, 270):
                bw, bh = u_height, u_width
            else:
                bw, bh = u_width, u_height
            ux, uy = cx - bw / 2, cy - bh / 2

            # Composed right-to-left by SVG, so this reads "mirror, then
            # rotate", the order portgeom.symbol_to_box uses for the
            # ports.
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
                # A symbol that carries no tag is labelled nowhere. Only
                # the pipe tee is one today: it is bare pipe, and an
                # issued sheet writes nothing against a junction.
                tag_box = None
                if u.tag:
                    item = self._tag_item(u, f, x, y, u_width, u_height, safe_name,
                                          ink, symbols)
                    tag_box = _unit_label_box(item)
                    label_items.append(item)
                # A body that cannot carry the darkening says so in
                # letters instead; see ISO 15519-1 §11.4.5.
                if closed_marking(u, self.registry) == "NC":
                    label_items.append(
                        self._nc_label_item(u, f, x, y, u_width, u_height, tag_box))
                # Where an actuated valve goes when its air or power is
                # lost. A separate question from the one above, in a
                # separate corner; see ISA-5.1 Table 5.4.4.
                letters = fail_marking(u)
                if letters:
                    label_items.append(
                        self._fail_label_item(u, f, x, y, u_width, u_height, letters,
                                              tag_box, ink, symbols))
        lines.append('  </g>')
        return lines

    def _draw_taps(self, fs):
        """The fine line from a tap point to the balloon reading it.

        Solid where the line is an **impulse line**: a length of tubing
        between the pipe and the element, full of the fluid the reading
        is taken from. Dashed everywhere else, where the line carries a
        measurement or a command -- a balloon hung off another balloon,
        a balloon teed off a **signal line**, a trip square hung on the
        valve it strokes. Nothing is drawn where a stream already joins
        the two, or where the element sits directly on the line
        (``offset=0``).

        Which of the two it is, is a question about the *line*, asked of
        both its ends and not of the host's class: see
        :func:`impulse_tap`.

        Fine is the same fine as a signal stream: ISO 15519-2 Annex
        A.1.02 puts an instrument connection on the 0,25 rung, alongside
        the signal line and half the pipeline it taps. See
        :attr:`~.weights.LineWeight.DETAIL`.

        Which lines there are is :func:`tap_lines`' answer, since label
        placement has to dodge exactly the ones this draws.
        """
        out = []
        for u, (tx, ty), (cx, cy) in tap_lines(fs):
            dash = "" if impulse_tap(u) else f' stroke-dasharray="{_TAP_DASH}"'
            out.append(f'    <line x1="{_num(tx)}" y1="{_num(ty)}" x2="{_num(cx)}" '
                       f'y2="{_num(cy)}" stroke="black" '
                       f'stroke-width="{LineWeight.DETAIL.width:g}"{dash} />')
        return ['  <g id="instrument_taps">'] + out + ['  </g>'] if out else []

    def _draw_boundary(self, u, f, safe_name):
        """A Feed or Product off-page connector flag.

        With an optional second line referencing the drawing the stream
        comes from or goes to.
        """
        ref = getattr(u, "reference", "") or ""
        # The pennant's own geometry, which the draw.io exporter reads
        # too; see :func:`boundary_flag`. Slightly taller where an
        # off-page reference has to fit under the tag, and centred on
        # the port either way -- the midpoint of the pennant's own
        # (inset) top and bottom, not a fixed offset off ``y``, so a
        # flag sized taller than the default 50 units keeps its point
        # and its lettering in the middle of the ink it actually drew
        # rather than stuck near the top of a box it does not fill.
        (bx0, top, bx1, bot), depth, east = boundary_flag(u, f)
        mid = (top + bot) / 2
        label_w = f.w
        # The tag goes in the flat part of the flag: the point is not
        # paper a word can be written across.
        if east:
            px0, px1, px2 = bx0, bx1 - depth, bx1
            tx = px0 + (label_w - depth) / 2
        else:
            px0, px1, px2 = bx1, bx0 + depth, bx0
            tx = bx0 + depth + (label_w - depth) / 2
        points = f"{px0},{top} {px1},{top} {px2},{mid} {px1},{bot} {px0},{bot}"
        # The pennant is a graphical symbol on the sheet rather
        # than a valve, a fitting or a PCE symbol, so it is drawn
        # on ISO 10628-1 §5.3.1 b)'s rung -- the same rung
        # ``pandid.render.drawio._boundary_cell`` states, read off
        # the ladder here since #490 rather than written as a bare
        # ``2`` that only happened to agree with it.
        out = [f'    <polygon points="{points}" fill="transparent" '
               f'stroke="black" stroke-width="{LineWeight.EQUIPMENT.width:g}" />']
        if ref:
            out.append(f'    <text x="{tx}" y="{mid - 4}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
            out.append(f'    <text x="{tx}" y="{mid + 8}" font-family="sans-serif" font-size="10.5" text-anchor="middle" dominant-baseline="middle" fill="#333">{escaped(ref)}</text>')
        else:
            out.append(f'    <text x="{tx}" y="{mid}" font-family="sans-serif" font-size="12" text-anchor="middle" dominant-baseline="middle">{safe_name}</text>')
        return out

    def _draw_instrument_tag(self, u, x, y, u_width, u_height):
        """Functional letters over the loop number, as ISA-5.1 draws.

        An interlock square carries the number alone: its letters are
        only the tag prefix, and a real sheet leaves the square holding
        one figure.
        """
        from pandid.units import split_tag

        variant = getattr(u, "variant", "default")
        # The tag, not the name: a repeated square is drawn with the
        # tag it shares and named apart only so it can be addressed.
        tag = getattr(u, "tag", "") or u.name
        top, bot = split_tag(getattr(u, "type", "") or tag, getattr(u, "number", "") or "")
        cx, cy = x + u_width / 2, y + u_height / 2
        if variant in _DIAMOND_BALLOONS:
            # A diamond is widest on its horizontal diagonal and
            # narrows to nothing at the bottom vertex, so the number
            # cannot be centred in the box: it goes in the lower half,
            # where ISA-5.1 draws it under the interlock designator, but
            # only as far down as the sloping sides leave it room. Seven
            # units below the middle of a 40 box is where a two-figure
            # number's bottom corners clear the edges.
            return [f'    <text x="{cx}" y="{cy + 7}" font-family="sans-serif" '
                    f'font-size="11" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top)}</text>']
        if not top:
            return [f'    <text x="{cx}" y="{cy}" font-family="sans-serif" '
                    f'font-size="12" text-anchor="middle" '
                    f'dominant-baseline="middle">{escaped(bot or top)}</text>']
        # The location bar says *where* the instrument lives and is
        # drawn across the middle, exactly where the letters would
        # otherwise sit. ISA-5.1 puts the letters wholly above the bar
        # and the number wholly below, so a barred variant needs the
        # pair pushed apart to leave the band clear.
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
        """Where a label on side ``lpos`` goes, and how it sets.

        ``lpos`` is one of :data:`LABEL_POSITIONS`, or the ``top_right``
        corner the ``NC`` marking is lettered in. A unit carrying
        anything else is ``label-pos-unknown`` and never reaches a
        render; the trailing ``top`` is that side and not a fallback.
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
            # Above the symbol *and to the right*: the text starts at
            # the box's right edge on the same baseline a top label sets
            # on. Only the NC marking is placed here.
            return x + u_width, y - 10, "start", "baseline"
        return x + u_width / 2, y - 10, "middle", "baseline"  # top

    def _unit_label_item(self, u, f, x, y, u_width, u_height, safe_name):
        """Resolve a unit label's placement.

        Drawn in a final pass (see :meth:`_draw_unit_labels`) so stream
        lines never strike through it.
        """
        lpos = f.label_pos or "top"
        return (*self._label_place(lpos, x, y, u_width, u_height), lpos, safe_name)

    def _tag_item(self, u, f, x, y, u_width, u_height, safe_name, ink, symbols=()):
        """The equipment tag, stepped clear of what is on the sheet.

        :func:`~pandid.layout.coordinates.assign_labels` chose the side,
        from the faces no nozzle leaves from, which is the whole of what
        is knowable while layout runs. It is not the whole question: a
        face with no nozzle of its own still has the line that passes
        it, the impulse line from a tap on that line to the balloon
        reading it, and the balloon itself. The tag is drawn last of
        everything, on an opaque halo, so it wins against all three --
        and what it wins is a hole in somebody else's drawing.

        *symbols* is every other unit's box, because a free face is not
        free paper: a nozzle is the only thing layout can see, and a
        balloon parked just off the face is invisible to it. Both halos
        eating a symbol on ``11_ethanol_pid`` were on a face layout was
        right to call free -- D-301's right face carries no nozzle, and
        LT-304 hangs off the end of the impulse line that leaves it.

        So the placement is settled again here, where the ink exists.
        The tag first steps *along* the side it was given, the same move
        the ``NC`` and fail-position letters make: a reader scans a
        sheet by side, so a tag beside the symbol it names on the face
        layout chose is worth more than a tidy centring. Only when the
        whole face is spoken for does it try another free one. The first
        placement that deletes nothing wins; where nothing is clear the
        least damaging wins, by :func:`_erases`, and a tie keeps the
        earlier answer.

        A side the author named is left where they put it, as is one the
        symbol fixes (an instrument balloon's ``center``).
        """
        from pandid.layout.coordinates import free_label_sides

        item = self._unit_label_item(u, f, x, y, u_width, u_height, safe_name)
        box = _unit_label_box(item)
        if box is None or not (ink or symbols):
            return item
        if getattr(u, "label_pos", None) or self.registry.for_unit(u).label_pos:
            return item
        # Only what is near this unit can be under one of its tag's
        # candidate spots, and testing the whole sheet against every one
        # is what would make choosing between them expensive.
        pad = max(u_width, u_height) + (box[2] - box[0])
        window = (x - pad, y - pad, x + u_width + pad, y + u_height + pad)
        near = [line for line in ink if _meets(line.box, window)]
        # This unit's own box is not among them: a tag is placed a fixed
        # clear distance off its own symbol and never lands on it, so
        # counting it would make every spot equally bad and the search
        # choose nothing. The rest are grown to their ink
        # (:func:`_obstacle`) here rather than by the caller, so the
        # draw.io exporter -- which builds a list of its own and hands
        # it to this method -- gets the same answer.
        others = [_obstacle(b) for v, b in symbols
                  if v is not u and _meets(_obstacle(b), window)]

        clear = (0, 0, 0)
        best, damage = item, _erases(box, near, others)
        sides = [item[4]] + [s for s in free_label_sides(u) if s != item[4]]
        for side in sides:
            if damage == clear:
                break
            lx, ly, anchor, baseline = self._label_place(side, x, y, u_width, u_height)
            # A tag steps along its face only as far as the symbol's
            # own half width (or half height, on a side face). Past that
            # it starts reading as the neighbour's.
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
        """The ``NC`` abbreviation, for a body that cannot be darkened.

        **ISO 15519-1 §11.4.5** governs the letters: it allows the state
        to be marked with ``NC`` for *normal closed* or ``NO`` for
        *normal open*, set **above the symbol and to the right**, and
        illustrates that at Figure 28. The figure draws it on an unfilled
        bowtie with the letters starting at about the valve's right-hand
        edge, clear above the run.

        The corner is fixed, not chosen from the valve's quarter turn:
        reading the marking always in the same place is what lets
        someone scan a sheet for closed valves, and the upper right is
        the corner an equipment tag is least likely to be in, the
        default tag sitting centred *above*.

        This departs from PIP PIC001 4.2.2.8, which puts the letters
        below a horizontal valve and to the right of a vertical one, and
        which is where the darkened body of 4.2.2.7 still comes from.
        The two are taken from different sources on purpose: PIP is the
        only standard that fills a valve body, and ISO 15519-1 the only
        one that letters it. See
        :func:`pandid.render.symbols.closed_marking`.

        Where the equipment tag already reaches into that corner, the
        abbreviation steps past it rather than over it -- both are drawn
        on opaque halos in the same final pass, so the second one down
        would otherwise erase the first. ``tag_box`` is where that tag
        actually landed, which is not always the side layout picked (see
        :meth:`_tag_item`); it is resolved from the frame when a caller
        has not already done so.
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
        """The fail position, in letters, beside the valve body.

        The letters are **ANSI/ISA-5.1-2009 Table 5.4.4** Method B,
        which **PIP PIC001 clause 4.5.3.2** requires over the standard's
        own Method A stem arrows. See
        :func:`pandid.render.symbols.fail_marking`.

        **PIP PIC001 clause 4.2.4.6(1)** places them, and is followed
        exactly: 0.06 inch directly below the control valve on a
        horizontal line, and 0.06 inch to its right on a vertical one.

        So the quarter turn moves these letters where it does not move
        the ``NC`` abbreviation (:meth:`_nc_label_item`), and the two
        are not inconsistent. ``NC`` sits in a *corner*, and a corner is
        free whichever way a valve is laid. These letters sit against a
        *face*, and which face is free is exactly what the quarter turn
        changes: the face below a valve on a horizontal run is clear,
        and the face below the same valve on a riser is its outlet
        nozzle with the line running out of it.

        Where the equipment tag is already on the side the letters want
        -- which the engine does choose for a valve on a riser -- the
        letters step past it along that same side rather than over it,
        both being drawn on opaque halos in the same final pass.
        ``tag_box`` is where that tag actually landed (see
        :meth:`_tag_item`), resolved from the frame when a caller has
        not already done so.

        A tag is not the only thing on that face, and treating it as
        though it were is issue #223: the letters then step *out* past
        the tag and land on the impulse line joining the valve to the
        trip square hung below it. So the ink and the neighbouring
        symbols are asked too, by :func:`_step_aside`, which slides the
        mark **along** the face -- the one direction that gets it off a
        line leaving that same face -- and holds it to half the face so
        PIP's *directly below* survives the move. ``ink`` and
        ``symbols`` are the sheet's, in the two forms :meth:`_tag_item`
        takes them; a mark placed with neither still steps past its tag.

        The two moves compose in the order the sheet has them: out past
        the tag first, that one being settled by a box the mark cannot
        share at all, then sideways off whatever the outward step landed
        on. The tag goes into the sideways pass's obstacles as well, so
        the slide cannot walk back onto what the step just cleared.

        This does not extend to ``NC``, for the reason
        :meth:`_nc_label_item` already rests on: a corner has nowhere to
        slide to that is still the corner.
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
            # Step along the axis the side runs off, by the overlap
            # plus a gap. Sideways is the six _nc_label_item steps by,
            # being the same move; downwards is tighter, a halo being 15
            # tall against 12 of text and so already carrying a margin
            # the horizontal one does not.
            if upright:
                item = (lx + tag[2] - fail[0] + 6, ly, anchor, baseline, lpos, text)
            else:
                item = (lx, ly + tag[3] - fail[1] + 4, anchor, baseline, lpos, text)
        # This unit's own box is left out for the reason _tag_item
        # leaves it out: the mark is placed a fixed clear distance off
        # its own symbol and never lands on it, so counting it would
        # score every candidate equally badly.
        others = [_obstacle(b) for v, b in symbols if v is not u]
        if tag is not None:
            others.append(tag)
        # How far along the face the letters may go: until the near edge
        # of their plate reaches the far end of the face, which is where
        # the mark stops lying against the body at all. ISO 15519-1
        # §7.2.3 is the clause for lettering beside a *symbol*, and asks
        # for it "adjacent to the symbol"; this bound is what adjacent
        # comes to here. Not §7.2.5, cited elsewhere in this file: that
        # one is a *connection's* designation and governs a line number.
        # The search takes the *smallest*
        # clearing step, so the bound is only ever reached by a mark
        # with nowhere to go, and there the placement is one to make by
        # hand.
        plate = _unit_label_box(item)
        # `_unit_label_box` only answers None for a `center` item, and
        # `item` above is built with `lpos` fixed to "right" or "bottom"
        # (see `lpos` at the top of this method) -- never reassigned to
        # "center" on any path that reaches here.
        assert plate is not None
        face, along = ((u_height, plate[3] - plate[1]) if upright
                       else (u_width, plate[2] - plate[0]))
        return _step_aside(item, (face + along) / 2, ink, others)

    def _draw_unit_labels(self, items):
        """Final pass: equipment tags on white halos, over the streams.

        Labels are placed on a free face where one exists, but a
        passing stream (or a unit whose every face carries a nozzle) can
        still run behind the text; the halo keeps the tag legible either
        way. A ``center`` label sits inside its symbol, so it gets no
        halo that would erase detail.
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
        """Does *this drawing* head the end of this stream?

        :func:`wears_arrowhead` and one thing more: a P&ID draws no
        heads at all, so ``arrows`` is false for the whole sheet. That
        part is a property of the render rather than of the stream,
        which is why it lives here and the rest lives where a caller
        with no renderer can reach it.
        """
        return arrows and wears_arrowhead(s, self.registry)

    def _draw_streams(self, fs, jump_direction, unit_labels, arrows=True,
                      plates=None, joints=None, crossing_style="arc"):
        """Draw every run, and the numbers written on and beside them.

        ``crossing_style`` is the mark a crossing of two unconnected
        runs carries and ``jump_direction`` is which of the two carries
        it; see :data:`CROSSING_STYLES`. All three are the same two path
        commands over the same ``2 * HOP_R`` of run -- the arc sweeps
        across it, the interruption lifts the pen over it, and
        ``"plain"`` writes neither and leaves the ``L`` that was going
        to be written anyway. So a crossing has the room for one exactly
        when it has the room for the others, and
        :func:`unmarked_crossings` needs no third answer.

        **Where the numbers go does not follow the style.** :func:`_ink`
        reserves a :func:`hop_box` for every crossing whichever mark the
        sheet draws, so a sheet redrawn in another convention keeps its
        line numbers exactly where the arc left them. On ``"gap"`` and
        ``"plain"`` that reserves the semicircle's paper for a mark that
        does not cover it -- reserving paper that is clear, which is the
        direction :func:`hop_box` already says it prefers to err in, and
        the alternative is a change of convention that also moves every
        number near a crossing.

        ``joints`` is the sheet's :func:`sheet_connections` answer --
        the joint every line takes unless it says otherwise, or ``None``
        on a drawing that marks no joints at all.

        ``plates`` is an out-parameter, filled -- when a caller supplies
        a list -- with every opaque white rectangle this pass and the
        equipment-tag pass between them put on the sheet. Only the
        debugging overlay asks for it, and it asks because it is drawn
        *underneath* all of them: see
        :func:`pandid.render.debug.overlay`. Left ``None`` nothing is
        collected and nothing about the render changes.

        The lines and symbols a number has to dodge are
        :func:`stream_numbers`' own business, derived from the
        flowsheet, so the two backends that ask it where a number goes
        cannot be given different answers by being given different
        seeds.
        """
        stream_geoms = [(s, stream_polyline(s)) for s in fs.streams]
        # Which run hops what, worked out once for the whole sheet and
        # read here rather than here and again in :func:`_ink`. Keyed by
        # the segment that carries it, already in the order that segment
        # is drawn in. See :func:`stream_hops`.
        hops: dict[tuple[int, int], list[_Hop]] = {}
        if crossing_style != "plain":
            for hop in stream_hops(fs, jump_direction):
                hops.setdefault((hop.stream, hop.seg), []).append(hop)

        # The crossing mark, as the one path command that differs
        # between the three styles. Everything before it -- which
        # segments cross which, which of the two carries the mark, and
        # the ``L`` up to the near side of the crossing -- is the same
        # for all three, so this is the whole of what the option
        # changes.
        #
        # ``M`` and not a second path element: the interruption is a
        # break in *this* run and the run continues after it, so it is a
        # second subpath of the same ``d``. That keeps ``marker-end`` on
        # the run's far end, where it attaches to the last subpath, and
        # keeps one line one element for anything reading the file back.

        def cross(far: str) -> str:
            """The command that gets the run from one side of a crossing
            to the other, given the far side as ``"x,y"``."""
            if crossing_style == "arc":
                return f"A {HOP_R:g} {HOP_R:g} 0 0 1 {far}"
            return f"M {far}"

        lines = ['  <g id="streams">']
        for n, (s, points) in enumerate(stream_geoms):
            paint = s.color or "black"
            # The same call ``_defs`` defines the marker under: one
            # function, so the reference and the definition are one
            # string rather than two spellings that agree today.
            marker_id = arrow_marker_id(paint)
            # Escaped once, here, rather than at each of the attributes
            # it is written into below. A checked colour
            # (:func:`pandid.streams.check_color`) has nothing left in
            # it to escape, and that is the point of doing it anyway:
            # the sink is where the guarantee is cheap to read off.
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
                # The two feet stand `HOP_R` back along the run either
                # side of the crossing, and the mark between them is
                # `cross`'s one command -- the arc leaving the run on
                # `side` with sweep flag 1 throughout, which is what
                # makes `side` follow the direction of travel, or the
                # `M` that lifts the pen over the same span. `:g`
                # because HOP_R is a clearance plus a pen width and so
                # is no longer a whole number.
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
            # A signal is drawn at half the weight of the pipe it
            # reads, per ISO 15519-2 Annex A.1.02/A.1.03 against A.1.01.
            width = _stream_rung(is_signal).width
            lines.append(
                f'    <path d="{d_str}" fill="none" '
                f'stroke="{color}" stroke-width="{width:g}"{dash}{marker} />'
            )

            # The joint marks, drawn over the line rather than instead
            # of it: the pipe runs into the nozzle and the flange faces
            # sit across it, which is what P&ID_301 draws and what makes
            # the mark read as hardware on the run instead of a gap.
            for fx, fy, angle, _at in flange_marks(s, points,
                                                   resolve_connections(s, joints)):
                rad = math.radians(angle)
                # A flange is a piping accessory, so the pair of faces
                # is ISO 10628-1 §5.3.1 c) and not the rung of the run
                # they sit across -- which is what they were drawn at
                # before #490, when that rung was the same number.
                #
                # §5.3.2 settles it independently and arithmetically.
                # The two bars are :data:`FLANGE_GAP` apart centre to
                # centre, so at a width w they leave 5 - w of paper
                # against that clause's floor of 2w and of 1 mm (4
                # units). Only the c) rung clears both: at 1 unit the
                # pair leaves exactly 4, at 2 it leaves 3, and at the
                # run's own 4 the two faces all but merge.
                # Along the run for the offset between the two faces,
                # across it for the bars themselves.
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
                # A supplementary symbol on a connection (ISO 15519-2
                # Annex A.1.09, pneumatic type 433A), and the line it
                # marks is a pneumatic signal: both are ISO 10628-1
                # §5.3.1 c), so the mark is the rung its line is.
                for mx, my, horiz, _at in pneumatic_marks(points):
                    for off in HATCH_ALONG:
                        if horiz:
                            lines.append(f'    <line x1="{mx+off-3:.1f}" y1="{my+5:.1f}" '
                                         f'x2="{mx+off+3:.1f}" y2="{my-5:.1f}" stroke="{color}" '
                                         f'stroke-width="{LineWeight.DETAIL.width:g}" />')
                        else:
                            lines.append(f'    <line x1="{mx-5:.1f}" y1="{my+off-3:.1f}" '
                                         f'x2="{mx+5:.1f}" y2="{my+off+3:.1f}" stroke="{color}" '
                                         f'stroke-width="{LineWeight.DETAIL.width:g}" />')

        # Final pass: stream-number labels, each on a white halo so it
        # reads cleanly over any line crossing beneath it.
        #
        # A label runs parallel to the pipe it names, turned on a
        # vertical run so it reads bottom to top and never upside down.
        # ISO 15519-1 §5.1.5 gives text two reading directions, from the
        # bottom edge of the document and from its right-hand edge, and
        # this is the second of those. Its next sentence keeps a
        # reference designation horizontal whatever way its symbol is
        # turned, which is about a *symbol's* designation and does not
        # reach a connection:
        # §7.2.5 is the clause for those, and asks for orientation
        # *along* the connecting line. Figure 40 turns the annotation on
        # every vertical connecting line to read bottom to top, left of
        # the line, while boxing symbol designations flat.
        #
        # Where each number goes is :func:`stream_numbers`', and this
        # pass only draws it.
        placed: list[tuple[float, float, float, float]] = [
            b for b in map(_unit_label_box, unit_labels) if b is not None
        ]

        shape = enclosure_shape(fs)
        numbers = stream_numbers(fs, placed, joints, jump_direction)
        self._findings += label_findings(fs, shape, numbers, jump_direction)
        for number in numbers:
            tx, ty, name = number.x, number.y, number.name
            color = escaped(number.color)
            lines += _enclosure_svg(shape, number.box, number.words, color)
            turn = f' transform="rotate(-90, {tx:.1f}, {ty:.1f})"' if number.vertical else ""
            lines.append(
                f'    <text x="{tx:.1f}" y="{ty:.1f}" font-family="sans-serif" '
                f'font-size="{NUMBER_TYPE}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{color}"{turn}>{escaped(name)}</text>'
            )
            # Over the words, because a halo has no outline for the tail
            # to meet and a tail buried under one would be a leader
            # joined to nothing. Only a bare label ever carries one: an
            # enclosed label never leaves its run (:func:`stream_numbers`).
            if number.leader is not None:
                (ax0, ay0), (ax1, ay1) = number.leader
                # In the label's own colour: it is part of the label,
                # not a line of its own.
                lines.append(f'    <line x1="{ax0:.1f}" y1="{ay0:.1f}" '
                             f'x2="{ax1:.1f}" y2="{ay1:.1f}" '
                             f'stroke="{color}" '
                             f'stroke-width="{LineWeight.DETAIL.width:g}" />')
                lines.append(f'    <path d="{_arrowhead(*number.leader)}" fill="{color}" />')
        # ``placed`` is now every box the sheet's two label passes
        # reserved: the equipment tags it was seeded with, each line
        # number, each leader. Reserved and not painted -- an
        # enclosure's box is ruled as an outline, and a label whose run
        # had nowhere clear paints no plate at all -- so this is what
        # the next mark has to keep off, which is what the overlay
        # draws. This is the only point where it exists.
        if plates is not None:
            plates.extend(placed)
        lines.append('  </g>')
        return lines
