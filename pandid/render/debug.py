"""Debug overlay of the coordinate grid, unit anchors and ports.

The overlay is a dashed red grid numbered along the top and left edges,
a red crosshair on each unit's ``pin(x, y)`` point, a blue dot on each
port and each unit's box as a faint outline, with labelled anchors and
ports.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple, Sequence

from pandid.render.escape import escaped, fmt

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: Grid pitch in drawing units for ``debug=True``.
DEFAULT_SPACING = 50.0

# Smallest accepted pitch.
_MIN_SPACING = 5.0

# Target pitch of numbered grid lines, in drawing units (_label_step).
_LABEL_PITCH = 100.0

# Type and marker sizes in page units; divided by the fit scale.
_AXIS_SIZE = 8.0      # axis numbers
_MARK_SIZE = 7.5      # anchor and port labels
_CROSS = 5.0          # half-length of a crosshair arm
_DOT = 2.2            # radius of a port dot

# Colours. Minor rules, numbered rules and numbers deepen in red.
_MINOR = "#f1b8b8"
_MAJOR = "#dd8b8b"
_NUMBER = "#c23b3b"
_BOX = "#eebfbf"
_ANCHOR = "#c00000"
_PORT = "#1550c8"

_FONT = "sans-serif"

# Dash pattern of the grid rules.
_DASH = "4,4"

# Label placement: advance width, ascent and descent as fractions of
# type size.
_ADV = 0.56
_ASC, _DESC = 0.75, 0.2

# Search steps in type sizes: across the text and along it.
_LINE, _SHIFT = 1.4, 2.4

# Search distance limit in type sizes (|out| + |across|).
_REACH = 10.0

# Label distance, in type sizes, beyond which a tether is drawn.
_TETHER = 3.5


def resolve_spacing(debug: "bool | float") -> "float | None":
    """Return the grid pitch for ``debug``, or ``None`` for no overlay.

    Parameters
    ----------
    debug : bool or float
        ``False`` (off), ``True`` (:data:`DEFAULT_SPACING`) or a pitch.

    Returns
    -------
    float or None
        Grid pitch in drawing units, or ``None``.

    Raises
    ------
    ValueError
        If ``debug`` is not a finite number of at least
        :data:`_MIN_SPACING`.
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
            f"debug={debug!r} asks for a grid at a spacing of {fmt(spacing, 1)} drawing units, "
            f"finer than the {fmt(_MIN_SPACING, 1)} this can draw. Pass debug=True for the "
            f"default {fmt(DEFAULT_SPACING, 1)}-unit grid, or a spacing of {fmt(_MIN_SPACING, 1)} "
            f"or more."
        )
    return spacing


def _label_step(spacing: float) -> float:
    """Return the numbered-line pitch, a multiple of ``spacing``.

    Parameters
    ----------
    spacing : float
        Grid pitch.

    Returns
    -------
    float
        Pitch of the numbered lines.
    """
    return spacing * max(1, math.ceil(_LABEL_PITCH / spacing - 1e-9))


def _ticks(lo: float, hi: float, step: float) -> list[float]:
    """Return each multiple of ``step`` in ``[lo, hi]``.

    Parameters
    ----------
    lo : float
        Lower bound.
    hi : float
        Upper bound.
    step : float
        Pitch; a step that is not positive gives no multiples.

    Returns
    -------
    list[float]
        The multiples, in ascending order.
    """
    if step <= 0:
        return []
    # Include a bound that lies exactly on a multiple.
    eps = step * 1e-9
    first = math.ceil((lo - eps) / step)
    last = math.floor((hi + eps) / step)
    return [k * step for k in range(first, last + 1)]


def _text(x: float, y: float, body: str, size: float, fill: str,
          anchor: str = "start") -> str:
    """Return one ``<text>`` placed by its baseline.

    Parameters
    ----------
    x : float
        Anchor x.
    y : float
        Baseline y.
    body : str
        Text, escaped on output.
    size : float
        Type size.
    fill : str
        Text colour.
    anchor : str, default="start"
        SVG ``text-anchor``.

    Returns
    -------
    str
        SVG ``<text>`` element.
    """
    return (f'    <text x="{fmt(x, 1)}" y="{fmt(y, 1)}" font-family="{_FONT}" '
            f'font-size="{size:.2f}" text-anchor="{anchor}" fill="{fill}">'
            f'{escaped(body)}</text>')


def _rule(x1: float, y1: float, x2: float, y2: float, colour: str,
          width: float) -> str:
    """Return one dashed grid rule as an SVG ``<line>``.

    Parameters
    ----------
    x1 : float
        Start x.
    y1 : float
        Start y.
    x2 : float
        End x.
    y2 : float
        End y.
    colour : str
        Stroke colour.
    width : float
        Stroke width.

    Returns
    -------
    str
        SVG ``<line>`` element.
    """
    return (f'    <line x1="{fmt(x1, 1)}" y1="{fmt(y1, 1)}" x2="{fmt(x2, 1)}" y2="{fmt(y2, 1)}" '
            f'stroke="{colour}" stroke-width="{width:.3f}" stroke-dasharray="{_DASH}" />')


def _step(vec: "tuple[float, float]") -> float:
    """Return the search step for an axis: a line pitch if vertical.

    Parameters
    ----------
    vec : tuple[float, float]
        Unit vector of the axis.

    Returns
    -------
    float
        Step in type sizes.
    """
    return _LINE if vec[1] else _SHIFT


def _spots(out: "tuple[float, float]", across: "tuple[float, float]",
           reach: float, side: float) -> "list[tuple[float, float]]":
    """Return candidate label offsets in type sizes, nearest first.

    Parameters
    ----------
    out : tuple[float, float]
        Unit vector walked one way from ``reach``.
    across : tuple[float, float]
        Unit vector walked both ways from ``side``.
    reach : float
        Start distance along ``out``.
    side : float
        Start distance along ``across``, the preferred side.

    Returns
    -------
    list[tuple[float, float]]
        Offsets ``(dx, dy)`` in type sizes.
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
    """Return the box a line of text covers written from ``(x, y)``.

    Parameters
    ----------
    x : float
        Anchor x.
    y : float
        Baseline y.
    text : str
        Text.
    size : float
        Type size.
    lead : float
        Run direction: right if non-negative, else left.

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
        Marker point.
    size : float
        Type size.
    colour : str
        Text colour.
    spots : list[tuple[float, float]]
        Candidate offsets from :func:`_spots`.
    near : tuple[list, list]
        Plate and ink boxes near the marker.
    """
    text: str
    px: float
    py: float
    size: float
    colour: str
    spots: "list[tuple[float, float]]"
    near: "tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]"


def _window(lab: "_Label") -> "tuple[float, float, float, float]":
    """Return the region a label's candidates can cover.

    Parameters
    ----------
    lab : _Label
        Label.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x0, y0, x1, y1)``.
    """
    span = lab.size * (max(max(abs(dx), abs(dy)) for dx, dy in lab.spots)
                       + _ADV * len(lab.text) + _ASC)
    return (lab.px - span, lab.py - span, lab.px + span, lab.py + span)


def _cost(lab: "_Label", dx: float, dy: float,
          placed: "Sequence[tuple[float, float, float, float]]",
          bounds: "tuple[float, float, float, float]",
          limit: "tuple[int, int, int] | None"):
    """Return the cost, placement and box of a label at an offset.

    Parameters
    ----------
    lab : _Label
        Label.
    dx : float
        Offset x in type sizes.
    dy : float
        Offset y in type sizes.
    placed : Sequence[tuple[float, float, float, float]]
        Boxes of labels already placed.
    bounds : tuple[float, float, float, float]
        Sheet bounds.
    limit : tuple[int, int, int] or None
        Cost beyond which counting stops, or ``None``.

    Returns
    -------
    tuple
        ``((labels, plates, ink, outside), (x, y, anchor), box)``.
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
    return (mine, *hits, outside), (x, y, "start" if dx >= 0 else "end"), box


# Cost of a clear spot, which ends the search.
_CLEAR = (0, 0, 0, 0)


def _options(lab: "_Label", bounds: "tuple[float, float, float, float]") -> int:
    """Return how many of a label's spots are clear of the sheet.

    Parameters
    ----------
    lab : _Label
        Label.
    bounds : tuple[float, float, float, float]
        Sheet bounds.

    Returns
    -------
    int
        Number of clear spots.
    """
    clear = (_CLEAR[0], _CLEAR[1], _CLEAR[2])
    return sum(_cost(lab, dx, dy, (), bounds, clear)[0] == _CLEAR
               for dx, dy in lab.spots)


def _tether(lab: "_Label", box: "tuple[float, float, float, float]") -> "str | None":
    """Return a tether from marker to label, or ``None`` when close.

    Parameters
    ----------
    lab : _Label
        Label.
    box : tuple[float, float, float, float]
        Placed label box.

    Returns
    -------
    str or None
        SVG ``<line>``, or ``None``.
    """
    near = (min(max(lab.px, box[0]), box[2]), min(max(lab.py, box[1]), box[3]))
    if math.hypot(near[0] - lab.px, near[1] - lab.py) <= _TETHER * lab.size:
        return None
    return (f'    <line x1="{fmt(lab.px, 1)}" y1="{fmt(lab.py, 1)}" x2="{fmt(near[0], 1)}" '
            f'y2="{fmt(near[1], 1)}" stroke="{lab.colour}" '
            f'stroke-width="{0.4 * lab.size / _MARK_SIZE:.3f}" />')


def _settle(labels: "list[_Label]", bounds: "tuple[float, float, float, float]"
            ) -> "tuple[list[str], list[str]]":
    """Place every label clear of the sheet and of earlier labels.

    Parameters
    ----------
    labels : list[_Label]
        Labels to place.
    bounds : tuple[float, float, float, float]
        Sheet bounds.

    Returns
    -------
    tuple[list[str], list[str]]
        Tether lines and text elements, each in input order.
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
    """Return the grid rules and its numbers along the top and left.

    Parameters
    ----------
    bounds : tuple[float, float, float, float]
        Region to rule.
    spacing : float
        Grid pitch.
    scale : float
        Fit scale; type and stroke sizes are divided by it.
    taken : list[tuple[float, float, float, float]]
        Boxes; each number's box is appended.

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

    # x numbers sit a line below the top edge, y numbers just above
    # their line.
    size = _AXIS_SIZE / scale
    for x in sorted(numbered_x):
        out.append(_text(x + 0.15 * size, y0 + 1.1 * size, fmt(x, 1), size, _NUMBER))
        taken.append(_box(x + 0.15 * size, y0 + 1.1 * size, fmt(x, 1), size, 1.0))
    for y in sorted(numbered_y):
        out.append(_text(x0 + 0.15 * size, y - 0.35 * size, fmt(y, 1), size, _NUMBER))
        taken.append(_box(x0 + 0.15 * size, y - 0.35 * size, fmt(y, 1), size, 1.0))
    return out


# Anchor label start (out, across, reach, side): up from the corner,
# running left.
_ANCHOR_LABEL = ((0.0, -1.0), (-1.0, 0.0), 1.2, 0.6)

# Port label start by facing, as (out, across, reach, side). East labels
# go above the line, west below, and north and south to the right.
_PORT_LABEL = {
    "E": ((1.0, 0.0), (0.0, -1.0), 0.5, 0.6),
    "W": ((-1.0, 0.0), (0.0, 1.0), 0.5, 1.35),
    "N": ((0.0, -1.0), (1.0, 0.0), 1.0, 1.5),
    "S": ((0.0, 1.0), (1.0, 0.0), 1.6, 1.5),
}


def _pin_point(unit, frame) -> "tuple[float, float]":
    """Return the point ``pin(x, y)`` sets on a unit.

    Parameters
    ----------
    unit : Unit
        Unit.
    frame : Frame
        The unit's frame.

    Returns
    -------
    tuple[float, float]
        Frame corner, or the nozzle of a boundary flag.
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
    """Return the marker geometry, with tethers, and the label text.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    scale : float
        Fit scale.
    bounds : tuple[float, float, float, float]
        Sheet bounds.
    plates : list[tuple[float, float, float, float]]
        Opaque boxes labels avoid.
    ink : list[tuple[float, float, float, float]]
        Line boxes labels avoid.

    Returns
    -------
    tuple[list[str], list[str]]
        Geometry and tethers, then the label text elements.
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
        """Queue a label with the plates and ink near it.

        Parameters
        ----------
        text : str
            Label text.
        px : float
            Marker x.
        py : float
            Marker y.
        colour : str
            Text colour.
        spots : list[tuple[float, float]]
            Candidate offsets.
        """
        lab = _Label(text, px, py, size, colour, spots, ([], []))
        seen = _window(lab)
        jobs.append(lab._replace(near=([b for b in plates if _meets(b, seen)],
                                       [b for b in ink if _meets(b, seen)])))

    anchor_spots = _spots(*_ANCHOR_LABEL)
    for u, f in frames:
        bx0, by0, bx1, by1 = unit_box(u, f)
        ax, ay = _pin_point(u, f)
        geometry.append(
            f'    <rect x="{fmt(bx0, 1)}" y="{fmt(by0, 1)}" width="{fmt(bx1 - bx0, 1)}" '
            f'height="{fmt(by1 - by0, 1)}" fill="none" stroke="{_BOX}" '
            f'stroke-width="{0.75 / scale:.3f}" />')
        geometry.append(
            f'    <line x1="{fmt(ax - arm, 1)}" y1="{fmt(ay, 1)}" x2="{fmt(ax + arm, 1)}" '
            f'y2="{fmt(ay, 1)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        geometry.append(
            f'    <line x1="{fmt(ax, 1)}" y1="{fmt(ay - arm, 1)}" x2="{fmt(ax, 1)}" '
            f'y2="{fmt(ay + arm, 1)}" stroke="{_ANCHOR}" stroke-width="{width:.3f}" />')
        label = f"{u.tag} {fmt(ax, 1)},{fmt(ay, 1)}" if u.tag else f"{fmt(ax, 1)},{fmt(ay, 1)}"
        job(label, ax, ay, _ANCHOR, anchor_spots)

    for u, f in frames:
        for name in u.ports:
            (px, py), _, facing = resolve_port(u, f, name)
            geometry.append(f'    <circle cx="{fmt(px, 1)}" cy="{fmt(py, 1)}" r="{dot:.3f}" '
                            f'fill="{_PORT}" />')
            job(f"{name} {fmt(px, 1)},{fmt(py, 1)}", px, py, _PORT,
                _spots(*_PORT_LABEL.get(facing, _PORT_LABEL["E"])))

    tethers, words = _settle(jobs, bounds)
    return geometry + tethers, words


def overlay(fs: "Flowsheet", bounds: "tuple[float, float, float, float]",
            spacing: float, scale: float = 1.0,
            plates: "list[tuple[float, float, float, float]] | None" = None,
            ink: "list[tuple[float, float, float, float]] | None" = None
            ) -> list[str]:
    """Return the debug overlay as SVG elements in drawing coordinates.

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
        Opaque boxes the sheet draws over the overlay.
    ink : list[tuple[float, float, float, float]], optional
        Line boxes the sheet draws.

    Returns
    -------
    list[str]
        SVG lines of the ``debug`` group.
    """
    from pandid.portgeom import unit_box

    solid = list(plates or ())
    solid.extend(unit_box(u, u.frame) for u in fs.units if u.frame is not None)
    grid = _grid(bounds, spacing, scale, solid)
    geometry, words = _marks(fs, scale, bounds, solid, list(ink or ()))
    return ['  <g id="debug">', *grid, *geometry, *words, '  </g>']
