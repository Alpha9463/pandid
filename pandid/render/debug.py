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
author would be debugging the debugger. The cost is that an anchor label landing
on a white-filled symbol is partly knocked out, which is the right way round.

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
from typing import TYPE_CHECKING

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


def _grid(bounds: "tuple[float, float, float, float]", spacing: float,
          scale: float) -> list[str]:
    """The ruled grid and the coordinates written along its top and left edges.

    Ruled only *within* the drawing's own bounding box. The overlay therefore
    adds nothing to the extent of the drawing, which is what lets it be switched
    on for a sheet with a fixed ``page_size`` without pushing the fit, moving
    the scale, or reaching out over the border and the title strip.
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
    for y in sorted(numbered_y):
        out.append(_text(x0 + 0.15 * size, y - 0.35 * size, _n(y), size, _NUMBER))
    return out


def _anchors(fs: "Flowsheet", scale: float, left_edge: float) -> list[str]:
    """A crosshair on the point ``pin(x, y)`` sets, and the pair that sets it.

    ``Frame.x``/``Frame.y`` *is* that point -- the layout engine honours a
    pinned axis exactly and computes the rest -- so this is as true of a unit
    nobody pinned as of one somebody did. That is half its value: the sheet
    tells an author what to write down to keep the placement the engine chose.

    A quarter turn or a mirror does not move it. Both are applied about the
    box's centre (see ``SvgRenderer._draw_units``), so a turned unit's corner is
    still the corner its pin names, and the crosshair still sits where the call
    put it.
    """
    from pandid.portgeom import unit_box

    out: list[str] = []
    arm, width = _CROSS / scale, 1.0 / scale
    size = _MARK_SIZE / scale
    for u in fs.units:
        f = u.frame
        if f is None:
            continue
        bx0, by0, bx1, by1 = unit_box(u, f)
        out.append(
            f'    <rect x="{_n(bx0)}" y="{_n(by0)}" width="{_n(bx1 - bx0)}" '
            f'height="{_n(by1 - by0)}" fill="none" stroke="{_BOX}" '
            f'stroke-width="{0.75 / scale:.3f}" />')
        out.append(f'    <line x1="{_n(f.x - arm)}" y1="{_n(f.y)}" x2="{_n(f.x + arm)}" '
                   f'y2="{_n(f.y)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        out.append(f'    <line x1="{_n(f.x)}" y1="{_n(f.y - arm)}" x2="{_n(f.x)}" '
                   f'y2="{_n(f.y + arm)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        # The tag is written beside the coordinates because the whole use of
        # this marker is matching a line of source to a point on paper, and the
        # tag is what the author searches their own file for.
        label = f"{u.tag} {_n(f.x)},{_n(f.y)}" if u.tag else f"{_n(f.x)},{_n(f.y)}"

        # Above the corner and running *left*. Running right walks straight into
        # the band the renderer reserves for the unit's own tag -- centred over
        # the box, on an opaque halo -- and on every heat exchanger in the corpus
        # that halo ate the coordinates and left the bare tag showing, which is
        # the one part of the string the sheet already said. Leftward, the label
        # heads away from the box entirely.
        #
        # Three lines up, which is what it takes to clear the row the tag sets
        # on. ``SvgRenderer._label_place`` puts a top label's baseline ten units
        # above the box in 12-unit type, so its halo occupies roughly the ten to
        # twenty units above the corner -- and on a unit narrower than its own
        # tag (a valve, a flow element, a relief valve) that halo reaches out
        # past the corner and ate the *coordinates* off the end of a label
        # written any closer. Above it there is paper.
        text_w = 0.56 * size * len(label)  # the advance width furniture.py measures at
        y = f.y - 3.2 * size
        if f.x - arm - text_w < left_edge:
            # ...except at the drawing's own left edge, where leftward would
            # hang the label off the region the overlay is allowed to occupy and
            # -- on a sheet fitted to a fixed page -- out over the border.
            out.append(_text(f.x + arm * 0.6, y, label, size, _ANCHOR))
        else:
            out.append(_text(f.x - arm * 0.6, y, label, size, _ANCHOR, anchor="end"))
    return out


# Where a port's label goes, by the direction the nozzle faces: the offset from
# the port point, in units of the label's own size, and the anchor to write it
# from. Pushed out along the normal, and set off the line's centreline so the
# pipe running into the nozzle strikes through as little of it as possible.
#
# **East above the line and west below it**, which is what stops the commonest
# collision on any sheet: a run joins an outlet facing east to an inlet facing
# west, so the two labels are written toward each other along one elevation and
# on a short run they overlap. Sending them to opposite sides of the pipe
# separates exactly the pair that would otherwise clash, and costs nothing where
# the run is long. North and south are already apart, being the two ends of a
# vertical, and both are written to the right so a stack of them lines up.
#
# North and south are pushed a good way sideways as well as out. Their dot sits
# at the middle of the box's top or bottom edge, which is exactly where the
# renderer centres the unit's own tag and the opaque halo under it; a label
# starting beside the dot begins underneath that halo and loses its first two
# characters to it. A shove of a line and a half clears a short tag outright and
# most of a long one.
_PORT_LABEL = {
    "E": (0.5, -0.6, "start"),
    "W": (-0.5, 1.35, "end"),
    "N": (1.5, -1.0, "start"),
    "S": (1.5, 1.6, "start"),
}


def _ports(fs: "Flowsheet", scale: float) -> list[str]:
    """A dot on every port, named and placed.

    Every declared port, including the signal ones an instrument or a valve
    actuator carries: all of them are things ``connect()`` joins and things
    ``pin(port=...)`` will pin to, so a rule that left some of them off would be
    a rule the author has to remember. The name is written because it is the
    string the API takes, and the coordinate because that is the elevation a run
    has to be pinned to.
    """
    from pandid.portgeom import resolve_port

    out: list[str] = []
    dot, size = _DOT / scale, _MARK_SIZE / scale
    for u in fs.units:
        if u.frame is None:
            continue
        for name in u.ports:
            (px, py), _, facing = resolve_port(u, u.frame, name)
            out.append(f'    <circle cx="{_n(px)}" cy="{_n(py)}" r="{dot:.3f}" '
                       f'fill="{_PORT}" />')
            dx, dy, anchor = _PORT_LABEL.get(facing, _PORT_LABEL["E"])
            out.append(_text(px + dx * size, py + dy * size,
                             f"{name} {_n(px)},{_n(py)}", size, _PORT, anchor))
    return out


def overlay(fs: "Flowsheet", bounds: "tuple[float, float, float, float]",
            spacing: float, scale: float = 1.0) -> list[str]:
    """The whole overlay, as SVG fragments in drawing coordinates.

    *bounds* is the drawing's own bounding box and *scale* the uniform factor a
    fixed page fits it by (1.0 when the sheet is sized to the drawing). The
    caller puts these lines at the *head* of the drawing so everything else
    paints over them.
    """
    body = (_grid(bounds, spacing, scale)
            + _anchors(fs, scale, bounds[0])
            + _ports(fs, scale))
    return ['  <g id="debug">', *body, '  </g>']
