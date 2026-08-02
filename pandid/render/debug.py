"""The debugging overlay: the coordinate system, drawn on the sheet.

Placement in ``pandid`` is absolute. ``pin(x=270, y=180)`` puts a unit's
**top-left corner** at (270, 180); ``pin(port="inlet", y=195)`` puts one
**nozzle** at that elevation and works the corner out backwards. Both are
written down in the same units, neither is drawn, and confusing the two is the
single most common authoring mistake this project has: eighteen doglegs across
four shipped example sheets came from it (#128), every one of them a run pinned
to a corner when it should have been pinned to a nozzle.

A grid alone does not fix that. A grid says where 300 is on the page; it does
not say *which point of a unit* lands on 300, which is the part the author has
to guess at. So this module draws four things, and the first is the least
important of them:

1. **The grid** -- faded dashed red at a spacing the caller sets, with the
   coordinate written along the top and left edges. The numbers are the point:
   without them an author counts squares, which is the arithmetic they were
   trying to escape.
2. **Each unit's anchor**, in red: the exact point ``pin(x, y)`` sets, with the
   pair of numbers that sets it. Read it off the sheet and type it back in.
3. **Each port**, in blue: the point a stream attaches to, with the name
   ``pin(port=...)`` and ``connect()`` take and the coordinate it is at.
4. **Each unit's drawn box**, as a faint outline: how much room the thing
   actually occupies, which the anchor alone does not say.

**Two colours, not one.** The grid is red because the sheet is monochrome black
and red reads instantly as not-part-of-the-drawing. Anchors and ports are then
told apart by *colour* rather than by shape, because telling them apart is the
whole reason this exists -- a red cross is a corner, a blue dot is a nozzle, and
that is legible before anything has been read. Red against blue is also the
safest pair to put in front of a colour-blind reader; red against green would
not be.

**Under the drawing, never over it.** These lines are emitted first, so every
piece of the sheet's own ink -- and every opaque white label halo -- paints over
them. An overlay that obscured a symbol would be worse than no overlay: the
author would be debugging the debugger.

That rule and the overlay's whole purpose pull against each other, because the
*text* is the feature: a coordinate you cannot read teaches nothing, and under
the drawing every white halo on the sheet wins against it. Both are kept, and
the way they are kept is :func:`_settle`. Being underneath is only a liability
while the words are placed blind; a label told where the sheet's plates and
lines landed picks paper nothing will be painted on, and then costs the drawing
nothing at all. So the labels are placed *last*, against the finished sheet,
and drawn *first*.

What was rejected, and why, since the obvious fix is the other one:

- **Overlay text above the drawing.** One line to write, and it makes the words
  win everywhere. It also puts a hundred and twenty red and blue strings across
  a P&ID whose placement the author is trying to read, which is the opposite of
  what they turned the overlay on for -- and it fixes nothing between one
  overlay label and the next, which on the densest sheet is the larger half of
  the problem. A debugging sheet is never issued, so ink crossed by scaffolding
  costs little; a drawing the scaffolding has buried costs the whole feature.
- **Overlay text on its own opaque halo, above the drawing.** Legible against
  anything, and it deletes a bite of the drawing per label -- precisely the
  damage the sheet's own placement engine spends two hundred lines avoiding,
  multiplied by every port on the sheet.
- **Fewer labels.** Cheapest of all, and it takes away the thing the author
  came for.

Where nothing is clear the label still lands on the least-covered spot and is
partly eaten. That is the right way round: a coordinate a reader has to zoom in
on beats a symbol replaced by red text.

**Drawn in drawing coordinates.** These lines go inside ``<g id="drawing">``
alongside the diagram, so the numbers written on the sheet are the numbers the
author types into ``pin()``. A fixed ``page_size`` puts that whole group under a
uniform fit scale, which would shrink 8-unit lettering to nothing on an A3
sheet; ``scale`` below is that factor, and everything that should come out a
constant size on paper is divided by it. Nothing else is: a grid line stays at
the drawing coordinate it names, because a grid drawn at page pitch would teach
the wrong numbers, which is the one failure that makes this feature actively
harmful rather than merely absent.

Only geometry the PDF/PNG backend already draws is used -- ``<line>``,
``<rect>``, ``<circle>``, ``<text>`` -- so the overlay exports to every format
this package writes. See :mod:`pandid.render.export` for what that rules out.
"""

from __future__ import annotations

import html
import math
from typing import TYPE_CHECKING, NamedTuple, Sequence

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: Grid pitch, in drawing units, when the overlay is asked for without one.
#: Equipment on these sheets is 60 to 130 units across and the examples pin on
#: round multiples of 10, so 50 puts two to three lines through a typical symbol
#: and lands a labelled line every 100 -- fine enough to read a nozzle off,
#: coarse enough that a sheet is not a hatch pattern.
DEFAULT_SPACING = 50.0

# The smallest pitch that is a pitch rather than a typing mistake. ``debug`` is
# a bool-or-number, and the one slip that union invites is ``debug=1`` meant as
# "on", which would rule three thousand lines across a flagship sheet before
# anyone saw it. Five is already absurdly fine -- a fifth of the narrowest
# symbol -- so nothing legitimate is refused, and the message names the spelling
# that was meant.
_MIN_SPACING = 5.0

# How far apart the written coordinates should be, in drawing units. Every
# ``k``-th line is drawn stronger and carries its number, ``k`` being the fewest
# whole steps that cover this; see :func:`_label_step`. 100 keeps the labelling
# at the same density whatever the pitch is, so a spacing of 10 does not become
# a wall of numbers and a spacing of 500 still gets numbered at all.
_LABEL_PITCH = 100.0

# Type sizes and marker geometry, in *page* units: divided by the fit scale so
# they come out the same on an A3 sheet as on one sized to its own drawing.
_AXIS_SIZE = 8.0      # the coordinates written along the top and left edges
_MARK_SIZE = 7.5      # an anchor's or a port's own label
_CROSS = 5.0          # half-length of an anchor crosshair arm
_DOT = 2.2            # radius of a port dot

# Faded for the minor rules, a shade up for the numbered ones, and a shade up
# again for the numbers themselves, which have to be read rather than sensed.
_MINOR = "#f1b8b8"
_MAJOR = "#dd8b8b"
_NUMBER = "#c23b3b"
_BOX = "#eebfbf"
_ANCHOR = "#c00000"
_PORT = "#1550c8"

_FONT = "sans-serif"

# Grid lines are dashed and the box outlines are solid, so the two are told
# apart at a glance even though both are red: a rule runs the width of the
# sheet and an outline closes on itself.
_DASH = "4,4"

# --- where a label goes ------------------------------------------------------
# Rough advance width of the sans-serif above, as a fraction of the type size,
# and how far a line of it reaches above and below its own baseline. The same
# 0.56 :mod:`pandid.render.furniture` measures its boxes at. Approximate on
# purpose: the number decides how much paper a label is held to need, and
# reserving a hair too much only ever pushes it to somewhere emptier.
_ADV = 0.56
_ASC, _DESC = 0.75, 0.2

# One step of the search, in units of the label's own type size. A step across
# the text is a line pitch, so labels that end up stacked read as lines of a
# list rather than as one another's neighbours. A step *along* the text is
# wider, since sliding a fifteen-character string by less than that leaves it
# on top of where it was.
_LINE, _SHIFT = 1.4, 2.4

# How far the search may walk from the marker, in type sizes, counted along the
# two axes together. A *distance* and not a number of steps, because the two
# steps above are different sizes and a count would let a label slide half a
# sheet sideways while allowing it only three lines up.
#
# It is set by the pipe rack on ``11_ethanol_pid``: four valves in sixty units,
# each with an inlet, an outlet and an actuator, whose labels are three times
# longer than the space between them and so cannot share an elevation however
# they are shuffled. The way out is upward, and it takes bands, and the number
# below is how many. Ten is 75 drawing units, a symbol and a half.
#
# What sets the ceiling is not the search, which would happily go further and
# would keep finding clear paper if it did. It is that past about here the walk
# stops paying: the labels still landing on something are the ones wedged in a
# corner of the rack with nothing within reach either, and every extra band
# costs *every* label a little more distance from its own marker. See
# :func:`_tether` for what makes distance affordable at all, and why it is not
# free.
_REACH = 10.0

# How far the words may sit from their marker before a line is drawn to say
# whose they are, in type sizes. Three and a half is 26 drawing units, which is
# about where a label stops reading as part of the same mark as its dot: nearer
# than that the pair are plainly one thing and a tether is clutter saying what
# the eye already had. On the four sheets that are not crowded this fires on a
# handful of labels; on ``11_ethanol_pid`` it fires on most of them, which is
# the honest picture of a sheet with three hundred and sixty of them.
_TETHER = 3.5


def _n(value: float) -> str:
    """A coordinate as an author would write it: 200, not 200.0."""
    return f"{value:.1f}".rstrip("0").rstrip(".") or "0"


def resolve_spacing(debug: "bool | float") -> "float | None":
    """The grid pitch *debug* asks for, or ``None`` when it asks for no overlay.

    ``False`` is off, ``True`` is :data:`DEFAULT_SPACING`, and a number is that
    pitch. The identity checks are deliberate: ``0 == False`` in Python, and a
    pitch of nought is a mistake worth a message rather than a silent off
    switch.
    """
    if debug is False or debug is None:
        return None
    if debug is True:
        return DEFAULT_SPACING
    try:
        spacing = float(debug)
    except (TypeError, ValueError):
        raise ValueError(
            f"debug must be True, False, or the grid spacing in drawing units, "
            f"got {debug!r}"
        ) from None
    if not math.isfinite(spacing) or spacing < _MIN_SPACING:
        raise ValueError(
            f"debug={debug!r} asks for a grid at a spacing of {_n(spacing)} drawing units, "
            f"finer than the {_n(_MIN_SPACING)} this can draw. Pass debug=True for the "
            f"default {_n(DEFAULT_SPACING)}-unit grid, or a spacing of {_n(_MIN_SPACING)} "
            f"or more."
        )
    return spacing


def _label_step(spacing: float) -> float:
    """The pitch the coordinates are written at: a whole number of *spacing*."""
    return spacing * max(1, math.ceil(_LABEL_PITCH / spacing - 1e-9))


def _ticks(lo: float, hi: float, step: float) -> list[float]:
    """Every multiple of *step* inside ``lo``..``hi``, inclusive.

    Multiples of the step in absolute coordinates rather than steps counted from
    the drawing's own left edge, so the numbered lines land on 100, 200, 300 and
    not on 137, 237, 337. A number nobody would type is a number nobody can use.
    """
    if step <= 0:
        return []
    # A hair of tolerance either way: a bound that is exactly on a multiple is a
    # line the drawing reaches, and binary floating point should not decide it.
    eps = step * 1e-9
    first = math.ceil((lo - eps) / step)
    last = math.floor((hi + eps) / step)
    return [k * step for k in range(first, last + 1)]


def _text(x: float, y: float, body: str, size: float, fill: str,
          anchor: str = "start") -> str:
    """One string, placed by its baseline.

    No ``dominant-baseline``: every ``y`` here is worked out as a baseline
    already, and the attribute is the one piece of text placement the PDF
    backend has to be taught (see :mod:`pandid.render.export`). Not setting it
    is one fewer thing to keep in step.
    """
    return (f'    <text x="{_n(x)}" y="{_n(y)}" font-family="{_FONT}" '
            f'font-size="{size:.2f}" text-anchor="{anchor}" fill="{fill}">'
            f'{html.escape(body)}</text>')


def _rule(x1: float, y1: float, x2: float, y2: float, colour: str,
          width: float) -> str:
    return (f'    <line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
            f'stroke="{colour}" stroke-width="{width:.3f}" stroke-dasharray="{_DASH}" />')


def _step(vec: "tuple[float, float]") -> float:
    """One search step along *vec*: a line pitch upright, a wider shift across."""
    return _LINE if vec[1] else _SHIFT


def _spots(out: "tuple[float, float]", across: "tuple[float, float]",
           reach: float, side: float) -> "list[tuple[float, float]]":
    """Offsets a label may be written at, in type sizes, nearest first.

    Two axes, both unit vectors, both already pointing the way this label
    prefers to go. *out* is the direction that takes the words **away from the
    thing they name** -- a nozzle's own outward normal, or straight up off a
    corner marker -- and is walked one way only, since the other way is into the
    symbol. *across* is the perpendicular, walked both ways with the preferred
    side first. ``reach`` and ``side`` are where the pair start from, which is
    the placement #200 arrived at by hand and is kept as the first thing
    tried.

    Ordered by how far the pair has walked, so the search gives up nearness in
    the smallest steps it can, and within a tie by *across* first: a label that
    has moved sideways is still beside its own nozzle, while one slid a long way
    out along the run has drifted toward the next unit's nozzle and starts
    reading as that one's.
    """
    so, sa = _step(out), _step(across)
    span = int(_REACH / min(so, sa)) + 1
    grid = [(o, a) for o in range(span + 1) for a in range(-span, span + 1)
            if o * so + abs(a) * sa <= _REACH]
    grid.sort(key=lambda oa: (oa[0] * so + abs(oa[1]) * sa, oa[0], oa[1] < 0))
    return [((reach + o * so) * out[0] + (side + a * sa) * across[0],
             (reach + o * so) * out[1] + (side + a * sa) * across[1])
            for o, a in grid]


def _box(x: float, y: float, text: str, size: float, lead: float
         ) -> "tuple[float, float, float, float]":
    """The paper a line of *text* covers, written from ``(x, y)`` in *lead*'s
    direction: rightward where the offset that put it there was positive,
    leftward where it was negative, so the words always run *away* from the
    marker they belong to and never back across it."""
    w = _ADV * size * len(text)
    x0 = x if lead >= 0 else x - w
    return (x0, y - _ASC * size, x0 + w, y + _DESC * size)


class _Label(NamedTuple):
    """One string waiting to be written, and everywhere it might go.

    Built for every marker before any of them is placed, because the order they
    are placed in turns out to matter more than anything else in this module:
    see :func:`_settle`.
    """
    text: str
    px: float
    py: float
    size: float
    colour: str
    spots: "list[tuple[float, float]]"
    #: What is already on the sheet and near enough to be under one of *spots*:
    #: the heavy tier and the light one, windowed once here rather than at every
    #: step of two passes over every candidate.
    near: "tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]"


def _window(lab: "_Label") -> "tuple[float, float, float, float]":
    """Everything *lab* can reach: the furthest offset, plus its own length."""
    span = lab.size * (max(max(abs(dx), abs(dy)) for dx, dy in lab.spots)
                       + _ADV * len(lab.text) + _ASC)
    return (lab.px - span, lab.py - span, lab.px + span, lab.py + span)


def _cost(lab: "_Label", dx: float, dy: float,
          placed: "Sequence[tuple[float, float, float, float]]",
          bounds: "tuple[float, float, float, float]",
          limit: "tuple[int, int, int] | None"):
    """What writing *lab* at this offset would cost, and the box it would take.

    The scoring is :func:`pandid.render.svg._covering`, which is the sheet's own
    label-placement engine, used here rather than copied. That is the half of
    that engine worth sharing: it is where *what damage is* is written down, and
    it is the half that moves -- #194 taught it that a symbol broken by a plate
    is a different and heavier kind of loss than a line crossed, and an overlay
    carrying its own collision test would never have heard. Even
    :func:`~pandid.render.svg._meets` matters: it holds that boxes touching edge
    to edge do not overlap, and two placement passes disagreeing on that would
    be a bug nobody could see.

    Its two tiers are read here from the other side, which is what makes them
    fit. The engine asks what a label's opaque halo would *delete*; this asks
    what would be painted **over** these words, since the overlay is underneath
    everything. So they hold every white halo the sheet lays down and every
    symbol box, whose fill is just as final, because either erases the words
    outright; and then the routed pipe and the impulse lines, because a hairline
    ruled through a red number still leaves a red number.

    Above both of those sits a tier the sheet's own engine has no use for:
    **another overlay label**. Landing on one is the only move here that ruins
    *two* strings rather than one -- they are the same colour at the same weight
    with nothing between them, so neither survives -- while a coordinate written
    across a valve's bounding box is one string, usually only partly lost, since
    most of that box is paper. Counting the two together let a label buy its way
    out of a vessel by sitting on its neighbour, at twice the cost and no gain.

    Last, and a tiebreak rather than a prohibition, is whether the label has
    left the drawing's own bounding box. Outside it is usually the margin, which
    is clear paper, and a coordinate written on clear paper a little outside the
    box beats one written inside it on top of a vessel.

    What is **not** reused is :func:`~pandid.render.svg._label_anchors`. That
    generates the places a line number may go *relative to a run*, and answers
    ISO 15519-1 §7.2.5 -- along or adjacent to the connecting line it names,
    with a leader where neither is possible. A port marker's label names a
    *point*: there is often no run at all, since every declared port is marked
    whether anything is connected to it or not, and the clause does not govern
    scaffolding. Feeding it a zero-length run to get candidate boxes out of it
    would make its contract a lie in order to reuse a for-loop. :func:`_spots`
    is that for-loop, in ten lines, and it keeps the shared surface to the one
    piece that is actually the same question.
    """
    from pandid.render.svg import _covering, _meets

    plates, ink = lab.near
    x, y = lab.px + dx * lab.size, lab.py + dy * lab.size
    box = _box(x, y, lab.text, lab.size, dx)
    mine = sum(1 for b in placed if _meets(box, b))
    # *limit* is the best score so far, and the counting stops as soon as this
    # spot is past it: the search only ever needs to know whether it is worse.
    # Beaten on the first number already and there is nothing left to count;
    # ahead on it and the count has to be exact, because this is the spot that
    # will be kept and everything after it is compared against what is stored.
    cap: "tuple[int, int] | None"
    if limit is None or mine < limit[0]:
        cap = None
    elif mine > limit[0]:
        cap = (0, 0)
    else:
        cap = (limit[1], limit[2])
    hits = _covering(box, ink, plates, cap)
    outside = 0 if (box[0] >= bounds[0] and box[1] >= bounds[1]
                    and box[2] <= bounds[2] and box[3] <= bounds[3]) else 1
    # Worst kind of loss first, so comparing two of these tuples is the order a
    # label gives things up in.
    return (mine, *hits, outside), (x, y, "start" if dx >= 0 else "end"), box


#: A spot nothing is drawn on: no overlay label, no plate, no ink. The first one
#: found wins outright and stops the search.
_CLEAR = (0, 0, 0, 0)


def _options(lab: "_Label", bounds: "tuple[float, float, float, float]") -> int:
    """How many of *lab*'s spots are clear of what the **sheet** already drew.

    Counted before anything is placed, and it is what decides the order they are
    placed in. Nothing about the overlay's own labels enters into it: they are
    the part that has not been decided yet.
    """
    clear = (_CLEAR[0], _CLEAR[1], _CLEAR[2])
    return sum(_cost(lab, dx, dy, (), bounds, clear)[0] == _CLEAR
               for dx, dy in lab.spots)


def _tether(lab: "_Label", box: "tuple[float, float, float, float]") -> "str | None":
    """A hairline from the marker to the label, where the words have gone far
    enough that lying beside the marker no longer says whose they are.

    This is what makes the search above safe to let off the leash, and without
    it the whole placement is a trade of one defect for a worse one. A label
    knocked out by a halo is a coordinate you cannot read, and you know you
    cannot read it. A label that has quietly stepped two nozzles along the rack
    is a coordinate you *can* read against the wrong dot, and there is nothing
    on the sheet to say so -- and this feature exists because a wrong coordinate
    typed into ``pin()`` is believed. So the words are allowed to walk, and the
    line is what they walk on.

    ISO 15519-1 §6.4 is where the sheet's own leaders come from, and the
    resemblance stops at the idea. That clause governs the reference
    designation of a *connection* and dresses its leader accordingly -- oblique,
    arrowheaded, drawn at half the weight of a process line. None of it applies
    to scaffolding, which no standard has an opinion about, so this is the
    plainest thing that does the job: a straight hairline in the label's own
    colour, from the marker to the nearest corner of the words, under all the
    ink like everything else here. No head, because there is no run for a reader
    to confuse it with, and adding one would put a triangle on a sheet that
    already has two meanings for a triangle.
    """
    near = (min(max(lab.px, box[0]), box[2]), min(max(lab.py, box[1]), box[3]))
    if math.hypot(near[0] - lab.px, near[1] - lab.py) <= _TETHER * lab.size:
        return None
    return (f'    <line x1="{_n(lab.px)}" y1="{_n(lab.py)}" x2="{_n(near[0])}" '
            f'y2="{_n(near[1])}" stroke="{lab.colour}" '
            f'stroke-width="{0.4 * lab.size / _MARK_SIZE:.3f}" />')


def _settle(labels: "list[_Label]", bounds: "tuple[float, float, float, float]"
            ) -> "tuple[list[str], list[str]]":
    """Write every label, each one clear of the sheet and of the ones before it.

    **Fewest places to go, first.** Taking them in the order the flowsheet
    happens to list its units is the worst of the available choices: it walks
    along a pipe rack handing the clear paper to whichever valve was declared
    first and leaving the last one nothing. Ordered instead by how many spots the
    *sheet* has left each label -- which is fixed before any of them move, so it
    is a property of the drawing and not of the order -- the labels that have a
    choice give way to the ones that do not. On ``11_ethanol_pid`` that is worth
    a fifth of the labels that would otherwise be more than a quarter buried (52
    of 364 down to 41), measured when the corpus was twelve sheets; 11 now
    writes 366 labels and leaves 26 of them touching a halo at all, and
    ``14_tank_farm`` -- which did not exist then -- leaves two. So the second
    half of that sentence, that it costs nothing anywhere else, is now the
    weaker claim that it costs nothing anywhere else *much*. The A/B is not
    restated here because reproducing it means running the placement in
    declaration order under a "more than a quarter covered" threshold, which is
    an experiment on this heuristic rather than a count of the corpus; the
    standing bound is ``_CROWDED`` in ``tests/test_debug_overlay.py``.

    An anchor label goes before a port label on a tie. There are far fewer of
    them and each says more -- a unit has one corner and up to eight nozzles,
    and the corner carries the pair of numbers ``pin()`` is actually written
    with.

    Each label joins the obstacles as it lands, so one only ever writes over
    another where the second had nowhere at all left to go. Swept over the
    fifteen sheets ``tests/test_debug_overlay.py`` renders, that is today
    nowhere at all -- no overlay label overlaps another anywhere in the corpus;
    it was four times on 11 when this was written. That is the other half of
    what #200 left on that
    sheet, and it is the same defect as the halo eating a port label seen from
    the other side -- both are the overlay writing where something else already
    is.

    Returns the tethers and then the text, each in the order the labels came in,
    which is unit by unit down the flowsheet: the search order is a search order,
    and a sheet that reads in source order is one a diff can be read against.
    """
    placed: "list[tuple[float, float, float, float]]" = []
    words: "list[str]" = [""] * len(labels)
    leads: "list[str | None]" = [None] * len(labels)
    for i, lab in sorted(enumerate(labels), key=lambda kv: (_options(kv[1], bounds), kv[0])):
        best = damage = None
        for dx, dy in lab.spots:
            cost, spot, box = _cost(lab, dx, dy, placed, bounds,
                                    None if damage is None else damage[:3])
            if damage is None or cost < damage:
                best, damage = (spot, box), cost
                if cost == _CLEAR:
                    break
        assert best is not None  # _spots never returns an empty list
        (x, y, anchor), box = best
        placed.append(box)
        words[i] = _text(x, y, lab.text, lab.size, lab.colour, anchor)
        leads[i] = _tether(lab, box)
    return [line for line in leads if line is not None], words


def _grid(bounds: "tuple[float, float, float, float]", spacing: float,
          scale: float, taken: "list[tuple[float, float, float, float]]") -> list[str]:
    """The ruled grid and the coordinates written along its top and left edges.

    Ruled only *within* the drawing's own bounding box. The overlay therefore
    adds nothing to the extent of the drawing, which is what lets it be switched
    on for a sheet with a fixed ``page_size`` without pushing the fit, moving
    the scale, or reaching out over the border and the title strip.

    These coordinates are placed rather than chosen, in the sense that they go
    where the edges of the grid put them and nowhere else -- an axis number that
    stepped aside would be naming a different line. So they are appended to
    *taken* instead: they are fixed, and it is every other overlay label that
    has to keep off *them*.
    """
    x0, y0, x1, y1 = bounds
    step = _label_step(spacing)
    out: list[str] = []

    minor_w, major_w = 0.5 / scale, 0.9 / scale
    numbered_x = set(_ticks(x0, x1, step))
    numbered_y = set(_ticks(y0, y1, step))

    for x in _ticks(x0, x1, spacing):
        strong = x in numbered_x
        out.append(_rule(x, y0, x, y1, _MAJOR if strong else _MINOR,
                         major_w if strong else minor_w))
    for y in _ticks(y0, y1, spacing):
        strong = y in numbered_y
        out.append(_rule(x0, y, x1, y, _MAJOR if strong else _MINOR,
                         major_w if strong else minor_w))

    # The numbers go *inside* the grid, for the same reason the rules stop at
    # its edge: outside it there is no paper the overlay is entitled to. The x
    # coordinates sit in a row a line's height *under* the top edge and the y
    # coordinates sit just *above* their own line, which is a line and a half
    # apart -- so the two runs cannot collide even where the drawing starts on a
    # numbered line and both want the same corner.
    size = _AXIS_SIZE / scale
    for x in sorted(numbered_x):
        out.append(_text(x + 0.15 * size, y0 + 1.1 * size, _n(x), size, _NUMBER))
        taken.append(_box(x + 0.15 * size, y0 + 1.1 * size, _n(x), size, 1.0))
    for y in sorted(numbered_y):
        out.append(_text(x0 + 0.15 * size, y - 0.35 * size, _n(y), size, _NUMBER))
        taken.append(_box(x0 + 0.15 * size, y - 0.35 * size, _n(y), size, 1.0))
    return out


# Straight up off the corner and running *left*, which is where #200 put this
# label by hand and where it still starts from. Rightward walks into the band
# the renderer reserves for the unit's own tag -- centred over the box, on an
# opaque halo -- and on every heat exchanger in the corpus that halo ate the
# coordinates and left the bare tag showing, which is the one part of the string
# the sheet already said. Leftward, the label heads away from the box entirely.
#
# What #200 also had to hard-code was the *height*: three and a bit lines up,
# measured off ``SvgRenderer._label_place``'s ten-unit gap and its 15-unit halo,
# because a tag on a unit narrower than itself reaches out past the corner. That
# number is gone. :func:`_settle` is told where the halo actually landed, which
# is not always where ``_label_place`` would have put it (see
# ``SvgRenderer._tag_item``), and steps over it or under it or around it as the
# sheet requires. A little over one line up is simply the closest place to start
# looking.
_ANCHOR_LABEL = ((0.0, -1.0), (-1.0, 0.0), 1.2, 0.6)

# Where a port's label starts from, by the direction the nozzle faces: the
# outward axis, the across axis, and how far along each. The across axis carries
# the preferred side already folded into its sign, so :func:`_spots` can walk it
# both ways without knowing which face it is on.
#
# **East above the line and west below it**, which is what stops the commonest
# collision on any sheet: a run joins an outlet facing east to an inlet facing
# west, so the two labels are written toward each other along one elevation and
# on a short run they overlap. Sending them to opposite sides of the pipe
# separates exactly the pair that would otherwise clash, and costs nothing where
# the run is long. North and south are already apart, being the two ends of a
# vertical, and both start to the right so a stack of them lines up.
#
# North and south start a good way sideways as well as out. Their dot sits at
# the middle of the box's top or bottom edge, which is exactly where the
# renderer centres the unit's own tag and the opaque halo under it.
_PORT_LABEL = {
    "E": ((1.0, 0.0), (0.0, -1.0), 0.5, 0.6),
    "W": ((-1.0, 0.0), (0.0, 1.0), 0.5, 1.35),
    "N": ((0.0, -1.0), (1.0, 0.0), 1.0, 1.5),
    "S": ((0.0, 1.0), (1.0, 0.0), 1.6, 1.5),
}


def _marks(fs: "Flowsheet", scale: float,
           bounds: "tuple[float, float, float, float]",
           plates: "list[tuple[float, float, float, float]]",
           ink: "list[tuple[float, float, float, float]]"
           ) -> "tuple[list[str], list[str]]":
    """Every marker, and every label placed against one. Geometry, then words.

    **The anchors**, in red: a crosshair on the point ``pin(x, y)`` sets.
    ``Frame.x``/``Frame.y`` *is* that point -- the layout engine honours a
    pinned axis exactly and computes the rest -- so this is as true of a unit
    nobody pinned as of one somebody did. That is half its value: the sheet
    tells an author what to write down to keep the placement the engine chose. A
    quarter turn or a mirror does not move it: both are applied about the box's
    centre (see ``SvgRenderer._draw_units``), so a turned unit's corner is still
    the corner its pin names.

    **The ports**, in blue: a dot on every declared one, including the signal
    ports an instrument or a valve actuator carries. All of them are things
    ``connect()`` joins and things ``pin(port=...)`` will pin to, so a rule that
    left some of them off would be a rule the author has to remember. The name
    is written because it is the string the API takes, and the coordinate
    because that is the elevation a run has to be pinned to.

    Every label is built before any is written, since which of them picks first
    is what :func:`_settle` turns on. Anchors are listed before ports so that a
    tie there goes the anchor's way.

    The marker geometry is returned apart from the lettering so the caller can
    draw all of it first: a crosshair arm or a box outline under a coordinate
    is the overlay obscuring itself, in miniature, and the fix is free.
    """
    from pandid.portgeom import resolve_port, unit_box
    from pandid.render.svg import _meets

    geometry: list[str] = []
    jobs: list[_Label] = []
    arm, width = _CROSS / scale, 1.0 / scale
    dot, size = _DOT / scale, _MARK_SIZE / scale
    frames = [(u, u.frame) for u in fs.units if u.frame is not None]

    def job(text: str, px: float, py: float, colour: str,
            spots: "list[tuple[float, float]]") -> None:
        lab = _Label(text, px, py, size, colour, spots, ([], []))
        seen = _window(lab)
        jobs.append(lab._replace(near=([b for b in plates if _meets(b, seen)],
                                       [b for b in ink if _meets(b, seen)])))

    anchor_spots = _spots(*_ANCHOR_LABEL)
    for u, f in frames:
        bx0, by0, bx1, by1 = unit_box(u, f)
        geometry.append(
            f'    <rect x="{_n(bx0)}" y="{_n(by0)}" width="{_n(bx1 - bx0)}" '
            f'height="{_n(by1 - by0)}" fill="none" stroke="{_BOX}" '
            f'stroke-width="{0.75 / scale:.3f}" />')
        geometry.append(
            f'    <line x1="{_n(f.x - arm)}" y1="{_n(f.y)}" x2="{_n(f.x + arm)}" '
            f'y2="{_n(f.y)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        geometry.append(
            f'    <line x1="{_n(f.x)}" y1="{_n(f.y - arm)}" x2="{_n(f.x)}" '
            f'y2="{_n(f.y + arm)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        # The tag is written beside the coordinates because the whole use of
        # this marker is matching a line of source to a point on paper, and the
        # tag is what the author searches their own file for.
        label = f"{u.tag} {_n(f.x)},{_n(f.y)}" if u.tag else f"{_n(f.x)},{_n(f.y)}"
        job(label, f.x, f.y, _ANCHOR, anchor_spots)

    for u, f in frames:
        for name in u.ports:
            (px, py), _, facing = resolve_port(u, f, name)
            geometry.append(f'    <circle cx="{_n(px)}" cy="{_n(py)}" r="{dot:.3f}" '
                            f'fill="{_PORT}" />')
            job(f"{name} {_n(px)},{_n(py)}", px, py, _PORT,
                _spots(*_PORT_LABEL.get(facing, _PORT_LABEL["E"])))

    tethers, words = _settle(jobs, bounds)
    return geometry + tethers, words


def overlay(fs: "Flowsheet", bounds: "tuple[float, float, float, float]",
            spacing: float, scale: float = 1.0,
            plates: "list[tuple[float, float, float, float]] | None" = None,
            ink: "list[tuple[float, float, float, float]] | None" = None
            ) -> list[str]:
    """The whole overlay, as SVG fragments in drawing coordinates.

    *bounds* is the drawing's own bounding box and *scale* the uniform factor a
    fixed page fits it by (1.0 when the sheet is sized to the drawing). The
    caller puts these lines at the *head* of the drawing so everything else
    paints over them.

    *plates* is every opaque white rectangle the sheet lays down over the top --
    each label halo, each leader -- and *ink* every line it draws. They are what
    the lettering is placed against; see :func:`_cost`. Passing neither draws the
    overlay blind, which is what the sheet's own labels then eat. Neither list is
    modified.
    """
    # The symbol boxes come from :func:`~pandid.portgeom.unit_box`, the same box
    # the router treats as the obstacle and the sheet's own placement engine
    # scores against. Most of them are white-filled artwork; the rest are near
    # enough that a coordinate written across one is not a coordinate anybody
    # reads. They belong with the halos rather than with the ink, and the caller
    # does not have to hand them over because they are the overlay's own
    # business: it draws each of them as an outline anyway.
    from pandid.portgeom import unit_box

    solid = list(plates or ())
    solid.extend(unit_box(u, u.frame) for u in fs.units if u.frame is not None)
    grid = _grid(bounds, spacing, scale, solid)
    geometry, words = _marks(fs, scale, bounds, solid, list(ink or ()))
    return ['  <g id="debug">', *grid, *geometry, *words, '  </g>']
