"""Draw the debugging overlay: the coordinate system on the sheet.

``pin(x=270, y=180)`` places a unit's top-left corner; ``pin(port="inlet",
y=195)`` places a nozzle. Neither point is drawn, and confusing them is a
common authoring mistake, so the overlay draws:

1. **the grid**, dashed red at the requested spacing, numbered along the
   top and left edges;
2. **each unit's anchor**, a red crosshair on the point ``pin(x, y)``
   sets, labelled with its tag and coordinates. On a boundary flag this
   is its nozzle, which is what ``pin`` takes there;
3. **each port**, a blue dot labelled with the name ``connect()`` and
   ``pin(port=...)`` take and its coordinates;
4. **each unit's drawn box**, as a faint outline.

Anchors and ports differ by colour (red and blue, a safe pair for
colour-blind readers).

The overlay is emitted under the drawing, so sheet ink and label halos
paint over it; labels are therefore placed last, against the finished
sheet (:func:`_settle`), and drawn first. It is drawn inside
``<g id="drawing">`` in drawing coordinates, so its numbers are ``pin()``
values; on a fixed page the fit scale is divided out of type and marker
sizes but not grid positions. Only ``<line>``, ``<rect>``, ``<circle>``
and ``<text>`` are used, so it exports to PDF and PNG
(:mod:`pandid.render.export`).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple, Sequence

from pandid.render.escape import escaped

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: Grid pitch in drawing units for ``debug=True``: two or three lines
#: across a typical 60-130 unit symbol.
DEFAULT_SPACING = 50.0

# Smallest accepted pitch, so ``debug=1`` meant as "on" is refused rather
# than ruling thousands of lines.
_MIN_SPACING = 5.0

# Target pitch of numbered grid lines, in drawing units (_label_step).
_LABEL_PITCH = 100.0

# Type and marker sizes in page units; divided by the fit scale.
_AXIS_SIZE = 8.0      # the coordinates written along the top and left edges
_MARK_SIZE = 7.5      # an anchor's or a port's own label
_CROSS = 5.0          # half-length of an anchor crosshair arm
_DOT = 2.2            # radius of a port dot

# Colours: minor rules, numbered rules and numbers in deepening red.
_MINOR = "#f1b8b8"
_MAJOR = "#dd8b8b"
_NUMBER = "#c23b3b"
_BOX = "#eebfbf"
_ANCHOR = "#c00000"
_PORT = "#1550c8"

_FONT = "sans-serif"

# Grid rules are dashed; box outlines are solid.
_DASH = "4,4"

# where a label goes ---------------------------------------------
# Approximate advance width, ascent and descent as fractions of type size;
# an overestimate only moves a debug label somewhere emptier.
_ADV = 0.56
_ASC, _DESC = 0.75, 0.2

# Search steps in type sizes: a line pitch across the text, a wider shift
# along it.
_LINE, _SHIFT = 1.4, 2.4

# Search distance limit in type sizes (|out| + |across|). Crowded pipe
# racks need several bands, but every extra band moves labels further from
# their markers (see _tether).
_REACH = 10.0

# Distance in type sizes beyond which a label gets a tether line to its
# marker.
_TETHER = 3.5


def _n(value: float) -> str:
    """Return a coordinate as an author writes it: ``200``, not ``200.0``."""
    return f"{value:.1f}".rstrip("0").rstrip(".") or "0"


def resolve_spacing(debug: "bool | float") -> "float | None":
    """Return the grid pitch ``debug`` asks for, or ``None`` for no overlay.

    Identity checks keep ``0`` from meaning "off", since ``0 == False``.

    Parameters
    ----------
    debug : bool or float
        ``False`` (off), ``True`` (:data:`DEFAULT_SPACING`) or a pitch.

    Returns
    -------
    float or None
        Grid pitch in drawing units.

    Raises
    ------
    ValueError
        If ``debug`` is not a number or is finer than the minimum pitch.
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
    """Return the numbered-line pitch: a whole multiple of ``spacing``."""
    return spacing * max(1, math.ceil(_LABEL_PITCH / spacing - 1e-9))


def _ticks(lo: float, hi: float, step: float) -> list[float]:
    """Return every multiple of ``step`` from ``lo`` to ``hi`` inclusive.

    Multiples are absolute, so numbered lines fall on 100, 200, 300.

    Parameters
    ----------
    lo, hi : float
        Range.
    step : float
        Pitch.

    Returns
    -------
    list[float]
        Multiples in order; empty for a non-positive step.
    """
    if step <= 0:
        return []
    # Tolerance so a bound exactly on a multiple is included.
    eps = step * 1e-9
    first = math.ceil((lo - eps) / step)
    last = math.floor((hi + eps) / step)
    return [k * step for k in range(first, last + 1)]


def _text(x: float, y: float, body: str, size: float, fill: str,
          anchor: str = "start") -> str:
    """Return one ``<text>`` placed by its baseline.

    No ``dominant-baseline`` is used, since every ``y`` is a baseline.

    Parameters
    ----------
    x, y : float
        Baseline position.
    body : str
        Text.
    size : float
        Font size.
    fill : str
        Colour.
    anchor : str, default="start"
        ``text-anchor``.

    Returns
    -------
    str
        SVG element.
    """
    return (f'    <text x="{_n(x)}" y="{_n(y)}" font-family="{_FONT}" '
            f'font-size="{size:.2f}" text-anchor="{anchor}" fill="{fill}">'
            f'{escaped(body)}</text>')


def _rule(x1: float, y1: float, x2: float, y2: float, colour: str,
          width: float) -> str:
    """Return one dashed grid rule as an SVG ``<line>``."""
    return (f'    <line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
            f'stroke="{colour}" stroke-width="{width:.3f}" stroke-dasharray="{_DASH}" />')


def _step(vec: "tuple[float, float]") -> float:
    """Return the search step for an axis: a line pitch if vertical."""
    return _LINE if vec[1] else _SHIFT


def _spots(out: "tuple[float, float]", across: "tuple[float, float]",
           reach: float, side: float) -> "list[tuple[float, float]]":
    """Return candidate label offsets in type sizes, nearest first.

    ``out`` points away from the marked object and is walked one way;
    ``across`` is perpendicular and walked both ways, preferred side
    first. Candidates are ordered by walked distance, then by less
    outward travel, since a label slid far along a run starts to read as
    the next nozzle's.

    Parameters
    ----------
    out, across : tuple[float, float]
        Unit vectors.
    reach, side : float
        Starting offsets along ``out`` and ``across``.

    Returns
    -------
    list[tuple[float, float]]
        Offsets within :data:`_REACH`.
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
    """Return the box a line of text covers when written from ``(x, y)``.

    Text runs right for a non-negative ``lead`` and left otherwise, so it
    always runs away from its marker.

    Parameters
    ----------
    x, y : float
        Baseline start.
    text : str
        Text.
    size : float
        Font size.
    lead : float
        Horizontal offset sign.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x0, y0, x1, y1)``.
    """
    w = _ADV * size * len(text)
    x0 = x if lead >= 0 else x - w
    return (x0, y - _ASC * size, x0 + w, y + _DESC * size)


class _Label(NamedTuple):
    """A label to place, with its candidate offsets.

    Attributes
    ----------
    text : str
        Label text.
    px, py : float
        Marker position.
    size : float
        Font size.
    colour : str
        Text colour.
    spots : list[tuple[float, float]]
        Candidate offsets from :func:`_spots`.
    near : tuple[list, list]
        Nearby plates and ink, windowed once for speed.
    """
    text: str
    px: float
    py: float
    size: float
    colour: str
    spots: "list[tuple[float, float]]"
    near: "tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]"


def _window(lab: "_Label") -> "tuple[float, float, float, float]":
    """Return the region a label's candidates can cover."""
    span = lab.size * (max(max(abs(dx), abs(dy)) for dx, dy in lab.spots)
                       + _ADV * len(lab.text) + _ASC)
    return (lab.px - span, lab.py - span, lab.px + span, lab.py + span)


def _cost(lab: "_Label", dx: float, dy: float,
          placed: "Sequence[tuple[float, float, float, float]]",
          bounds: "tuple[float, float, float, float]",
          limit: "tuple[int, int, int] | None"):
    """Return the cost, placement and box of writing a label at an offset.

    Cost is compared as a tuple, worst loss first: overlap with another
    overlay label, then what would be painted over the words (via
    :func:`pandid.render.svg._covering`: halos and symbol boxes, then
    lines), then whether the label leaves the drawing's bounds. The
    overlay sits under the sheet, so the tiers count what covers it.

    Parameters
    ----------
    lab : _Label
        Label.
    dx, dy : float
        Offset in type sizes.
    placed : sequence of tuple
        Boxes of overlay labels already placed.
    bounds : tuple[float, float, float, float]
        Drawing bounds.
    limit : tuple[int, int, int] or None
        Best cost so far; counting stops once this spot is worse.

    Returns
    -------
    tuple
        ``(cost, (x, y, anchor), box)``.
    """
    from pandid.render.svg import _covering, _meets

    plates, ink = lab.near
    x, y = lab.px + dx * lab.size, lab.py + dy * lab.size
    box = _box(x, y, lab.text, lab.size, dx)
    mine = sum(1 for b in placed if _meets(box, b))
    # Count exactly only while this spot could still beat ``limit``.
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
    # Worst loss first, so tuples compare in priority order.
    return (mine, *hits, outside), (x, y, "start" if dx >= 0 else "end"), box


# Cost of a completely clear spot, which ends the search.
_CLEAR = (0, 0, 0, 0)


def _options(lab: "_Label", bounds: "tuple[float, float, float, float]") -> int:
    """Return how many of a label's spots are clear of the sheet's ink.

    Computed before any overlay label is placed; it sets placement order.

    Parameters
    ----------
    lab : _Label
        Label.
    bounds : tuple[float, float, float, float]
        Drawing bounds.

    Returns
    -------
    int
        Number of clear spots.
    """
    clear = (_CLEAR[0], _CLEAR[1], _CLEAR[2])
    return sum(_cost(lab, dx, dy, (), bounds, clear)[0] == _CLEAR
               for dx, dy in lab.spots)


def _tether(lab: "_Label", box: "tuple[float, float, float, float]") -> "str | None":
    """Return a hairline from marker to label when the label is far away.

    A displaced coordinate read against the wrong dot would be typed into
    ``pin()`` and believed, so a distant label is tethered. The overlay is
    not part of an issued drawing, so ISO 15519-1 6.4 leader terminators
    are not used.

    Parameters
    ----------
    lab : _Label
        Label.
    box : tuple[float, float, float, float]
        Where it was placed.

    Returns
    -------
    str or None
        SVG ``<line>``, or ``None`` within :data:`_TETHER`.
    """
    near = (min(max(lab.px, box[0]), box[2]), min(max(lab.py, box[1]), box[3]))
    if math.hypot(near[0] - lab.px, near[1] - lab.py) <= _TETHER * lab.size:
        return None
    return (f'    <line x1="{_n(lab.px)}" y1="{_n(lab.py)}" x2="{_n(near[0])}" '
            f'y2="{_n(near[1])}" stroke="{lab.colour}" '
            f'stroke-width="{0.4 * lab.size / _MARK_SIZE:.3f}" />')


def _settle(labels: "list[_Label]", bounds: "tuple[float, float, float, float]"
            ) -> "tuple[list[str], list[str]]":
    """Place every label clear of the sheet and of earlier labels.

    Labels with the fewest clear spots go first, so constrained labels are
    not crowded out by declaration order; anchors win ties over ports.
    Each placed label becomes an obstacle for the rest.
    ``tests/test_debug_overlay.py`` bounds how many end up covered.

    Parameters
    ----------
    labels : list[_Label]
        Labels in flowsheet order.
    bounds : tuple[float, float, float, float]
        Drawing bounds.

    Returns
    -------
    tuple[list[str], list[str]]
        Tether lines and text elements, each in input order for stable
        diffs.
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
    """Return the grid rules and the numbers along its top and left edges.

    Ruled only within the drawing bounds, so the overlay never changes
    the fit on a fixed page or reaches the border. The axis numbers are
    fixed in place and appended to ``taken`` for other labels to avoid.

    Parameters
    ----------
    bounds : tuple[float, float, float, float]
        Drawing bounds.
    spacing : float
        Grid pitch.
    scale : float
        Fit scale.
    taken : list[tuple[float, float, float, float]]
        Obstacle boxes, appended to in place.

    Returns
    -------
    list[str]
        SVG elements.
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

    # Numbers sit inside the grid: x values a line below the top edge, y
    # values just above their line, so the two rows cannot collide.
    size = _AXIS_SIZE / scale
    for x in sorted(numbered_x):
        out.append(_text(x + 0.15 * size, y0 + 1.1 * size, _n(x), size, _NUMBER))
        taken.append(_box(x + 0.15 * size, y0 + 1.1 * size, _n(x), size, 1.0))
    for y in sorted(numbered_y):
        out.append(_text(x0 + 0.15 * size, y - 0.35 * size, _n(y), size, _NUMBER))
        taken.append(_box(x0 + 0.15 * size, y - 0.35 * size, _n(y), size, 1.0))
    return out


# Anchor label: up from the corner and running left, away from the tag
# the renderer centres over the box.
_ANCHOR_LABEL = ((0.0, -1.0), (-1.0, 0.0), 1.2, 0.6)

# Port label start by facing: (out, across, reach, side), with the
# preferred side folded into ``across``. East labels go above the line and
# west below, so facing outlet and inlet labels on one run do not collide;
# north and south start to the right of the tag position.
_PORT_LABEL = {
    "E": ((1.0, 0.0), (0.0, -1.0), 0.5, 0.6),
    "W": ((-1.0, 0.0), (0.0, 1.0), 0.5, 1.35),
    "N": ((0.0, -1.0), (1.0, 0.0), 1.0, 1.5),
    "S": ((0.0, 1.0), (1.0, 0.0), 1.6, 1.5),
}


def _pin_point(unit, frame) -> "tuple[float, float]":
    """Return the point ``pin(x, y)`` sets on a unit.

    The frame corner for equipment; the nozzle for a boundary flag, which
    is pinned by it (:meth:`pandid.units.Unit.pin`).

    Parameters
    ----------
    unit : Unit
        Placed unit.
    frame : Frame
        Its frame.

    Returns
    -------
    tuple[float, float]
        Anchor point.
    """
    from pandid.portgeom import resolve_port
    from pandid.units import _Boundary

    if isinstance(unit, _Boundary):
        return resolve_port(unit, frame, next(iter(unit.ports))).point
    return frame.x, frame.y


def _marks(fs: "Flowsheet", scale: float,
           bounds: "tuple[float, float, float, float]",
           plates: "list[tuple[float, float, float, float]]",
           ink: "list[tuple[float, float, float, float]]"
           ) -> "tuple[list[str], list[str]]":
    """Return the box, anchor and port markers, and their labels.

    Anchors are red crosshairs at ``Frame.x``/``Frame.y`` (or the flag
    nozzle), which turns and mirrors do not move. Ports are blue dots on
    every declared port, signal ports included, labelled with name and
    coordinates. Labels are built before any is placed (:func:`_settle`),
    anchors first.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    scale : float
        Fit scale.
    bounds : tuple[float, float, float, float]
        Drawing bounds.
    plates, ink : list[tuple[float, float, float, float]]
        Opaque boxes and drawn lines for labels to avoid.

    Returns
    -------
    tuple[list[str], list[str]]
        Marker geometry (with tethers) and label text, drawn in that order
        so markers never cover text.
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
        """Queue a label with the plates and ink near it."""
        lab = _Label(text, px, py, size, colour, spots, ([], []))
        seen = _window(lab)
        jobs.append(lab._replace(near=([b for b in plates if _meets(b, seen)],
                                       [b for b in ink if _meets(b, seen)])))

    anchor_spots = _spots(*_ANCHOR_LABEL)
    for u, f in frames:
        bx0, by0, bx1, by1 = unit_box(u, f)
        ax, ay = _pin_point(u, f)
        geometry.append(
            f'    <rect x="{_n(bx0)}" y="{_n(by0)}" width="{_n(bx1 - bx0)}" '
            f'height="{_n(by1 - by0)}" fill="none" stroke="{_BOX}" '
            f'stroke-width="{0.75 / scale:.3f}" />')
        geometry.append(
            f'    <line x1="{_n(ax - arm)}" y1="{_n(ay)}" x2="{_n(ax + arm)}" '
            f'y2="{_n(ay)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        geometry.append(
            f'    <line x1="{_n(ax)}" y1="{_n(ay - arm)}" x2="{_n(ax)}" '
            f'y2="{_n(ay + arm)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        # Include the tag, which is what the author searches the source for.
        label = f"{u.tag} {_n(ax)},{_n(ay)}" if u.tag else f"{_n(ax)},{_n(ay)}"
        job(label, ax, ay, _ANCHOR, anchor_spots)

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
    """Return the debug overlay as SVG elements in drawing coordinates.

    The caller puts these at the head of the drawing so everything else
    paints over them. Symbol boxes (:func:`~pandid.portgeom.unit_box`,
    not grown to ink) join the plates as obstacles.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    bounds : tuple[float, float, float, float]
        Drawing bounds.
    spacing : float
        Grid pitch.
    scale : float, default=1.0
        Fit scale of a fixed page.
    plates : list[tuple[float, float, float, float]], optional
        Opaque boxes the sheet draws over the overlay (halos, leaders).
    ink : list[tuple[float, float, float, float]], optional
        Line boxes the sheet draws. Neither list is modified.

    Returns
    -------
    list[str]
        SVG lines in a ``<g id="debug">`` group.
    """
    from pandid.portgeom import unit_box

    solid = list(plates or ())
    solid.extend(unit_box(u, u.frame) for u in fs.units if u.frame is not None)
    grid = _grid(bounds, spacing, scale, solid)
    geometry, words = _marks(fs, scale, bounds, solid, list(ink or ()))
    return ['  <g id="debug">', *grid, *geometry, *words, '  </g>']
