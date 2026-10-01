"""Export a flowsheet to draw.io / diagrams.net (``.drawio``).

The SVG backend draws a finished picture; this one exports the model:
units as draw.io vertices and streams as edges between them, so an
author can move a unit in draw.io and its lines follow. draw.io also
exports to Visio.

The library's symbols are draw.io's own P&ID stencils, vendored and
converted (see NOTICE), so the export names each shape rather than
tracing it. ``mxgraph.pid.valves.gate_valve`` is a key draw.io's stencil
registry resolves. :func:`scripts.vendor_symbols.drawio_shape_key`
derives it from the stencil file by draw.io's own rule, and
:attr:`~pandid.render.symbols.Symbol.drawio_shape` carries it here. draw.io
draws an unresolved key as a plain rectangle without an error, so
``tests/test_drawio.py`` checks every reference against the vendored
stencils.

Three things follow:

* **Sizing.** draw.io scales a stencil into its cell, stretching where
  the stencil says ``aspect="variable"`` and letterboxing where it says
  ``"fixed"``, the question :func:`pandid.portgeom.ink_box` asks of
  :attr:`~pandid.render.symbols.Symbol.stretchable`. The cell box is
  therefore the whole mapping; a test pins that every referenced
  stencil is ``variable``.
* **Ports.** A draw.io fixed connection point is a fraction of the cell
  box; dividing :func:`pandid.portgeom.port_point` through by the box
  is the conversion.
* **Ink.** ``scripts/mxgraph_to_svg.py`` converts stencils with fill
  ``none`` and strokes ``#111``, standing in for the style's
  ``fillColor`` and ``strokeColor``, so stating those in the style
  reproduces the sheet's ink.

Symbols draw.io has no stencil for are listed in :data:`_APPROXIMATIONS`,
each stood in for by a draw.io built-in (which cannot fail to resolve)
with a sentence saying what it loses. Every such loss is reported on
``fs.warnings`` (:data:`APPROXIMATED`), as is any title-block cell that
had to abbreviate, through :data:`~pandid.render.furniture.Reporter`.
Sheet furniture is docked and ruled as on the sheet
(:meth:`DrawioRenderer._furniture`).

A composed symbol (a body carrying ISO 10628-2 parts, such as an agitator
in a reactor) names no stencil of its own, since a stencil reference
names one shape. It is exported as the body's cell with one child cell
per part, placed by the same fractions the SVG uses
(:meth:`DrawioRenderer._overlay_cells`). The ten group-28 agitators name
draw.io's ``mxgraph.pid.agitators`` stencils; other parts use
:data:`_PART_APPROXIMATIONS`.

With ``page_size`` the export is a sheet: the file states the page,
furniture docks to it, and the drawing is fitted into what is left,
through the same :func:`~pandid.render.furniture.dock` and
:func:`~pandid.render.svg._fit_scale` as the SVG; ``border="zone"`` rules
the page. Without it the drawing keeps its own coordinates (see
:class:`_Fit`).

Not exported: a symbol's own lettering held upright under a turn (the
"M" on a motor operator), which draw.io turns with the shape.

The output is a plain uncompressed ``mxfile``, which draw.io reads and
which diffs cleanly.

What draw.io actually does
--------------------------

Read from draw.io's and mxGraph's source, since nothing in this
repository opens a ``.drawio`` file. Each item names its source
functions.

* **A shape reference that misses fails silently, and there is no log.**
  ``mxCellRenderer.createShape`` asks ``mxStencilRegistry.getStencil``
  first and ``mxCellRenderer.defaultShapes`` second;
  ``getShapeConstructor`` then falls back to ``mxRectangleShape``.
  Neither table normalises case. A name beginning ``mxgraph.``
  additionally triggers a **blocking, uncached** fetch of
  ``stencils/<set>.xml``, retried once per referencing cell if it 404s.
  ``tests/test_drawio.py`` exists for this hazard. ``jgraph/mxgraph``
  ``view/mxCellRenderer.js``; ``jgraph/drawio``
  ``src/main/webapp/js/grapheditor/Graph.js``
  (``mxStencilRegistry.getStencil``, ``parseStencilSet``).
* **The stencil key rule**: lowercase the set's ``name``, add a dot, add
  the shape's ``name`` with spaces replaced by ``_``, lowercased.
  ``parseStencilSet``, as above.
  ``scripts/vendor_symbols.drawio_shape_key`` implements the same rule.
* **A style is ``split(';')`` then ``indexOf('=')``, with no escaping
  anywhere.** So ``;`` is the *only* character a value cannot contain;
  parentheses,
  commas, ampersands, hyphens and slashes in stencil keys are safe.
  Two traps: a
  value of exactly ``none`` **deletes** the key rather than setting it
  (so ``shape=none`` draws a plain rectangle), and a token containing no
  ``=`` is looked up as a *named style*. ``mxStylesheet.getCellStyle``,
  ``mxUtils.getStylename``.
* **A dash pattern is separated by spaces and scaled by the stroke
  width.** ``createDashPattern`` splits on ``' '`` and runs each part
  through ``Number()``, so a comma yields ``NaN``; and
  ``stroke-dasharray`` comes out as ``pattern x strokeWidth x scale``
  unless ``fixDash=1``. See :func:`_dash`.
  ``mxSvgCanvas2D.createDashPattern``, ``mxShape.configureCanvas``.
* **draw.io has two anchor-point algorithms and they disagree.** The
  default, ``Graph.getLegacyConnectionPoint``, honours
  ``anchorPointDirection=0`` by skipping both the ``r1`` rotation *and*
  the 90-degree bounds swap a north or south ``direction`` would
  otherwise apply; the newer one behind ``legacyAnchorPoints=0`` swaps
  the bounds regardless. With the legacy one and ``exitPerimeter=0``, a
  point is: fraction of the bounds as placed, then the cell's flips
  about the bounds centre, then ``rotation``. That is the model
  :meth:`_constraint` applies, and the file says
  ``legacyAnchorPoints=1`` so it stays that way.
  ``Graph.getConnectionPoint``, ``mxGraph.getConnectionConstraint``,
  ``mxConstants.STYLE_ANCHOR_POINT_DIRECTION``.
* **A stencil cannot draw an edge.** ``mxShape.paint`` takes the stencil
  branch before the ``points`` branch, so a stencil named on an edge is
  stretched into the route's bounding box and no line is drawn. And a
  marker goes at an edge's two ends and nowhere else:
  ``mxConnector.createMarker`` is called twice, with ``pts[0]`` and
  ``pts[n-1]``. There is no mid-line marker style.
* **A line jump is a style on the edge that hops, and the hop goes on
  whichever of two crossing edges is written later.**
  ``mxGraphView.updateLineJumps`` reads ``jumpStyle`` off the edge being
  validated and intersects its segments against ``this.validEdges`` -- a
  list ``mxGraphView.validateCellState`` *appends to* as it walks the
  model in child order, so it holds exactly the edges that appear before
  this one in ``<root>``. ``state2.style['noJump'] != '1'`` in the same
  loop is the opt-out. See :func:`_hops`.
* **A child vertex on an edge is positioned by arc length, from its
  top-left.** ``mxGeometry.x`` runs -1 to +1 over the *routed*
  polyline's Euclidean length; ``mxGeometry.y`` displaces perpendicular;
  ``mxGeometry.offset`` displaces in plain drawing units; and
  ``mxGraphView.updateCellState`` puts the child's **top-left** -- not
  its centre -- on the point ``getPoint`` returns. Nothing is cached, so
  such a child rides the edge when a terminal moves. ``rotation``
  applies about the child's own centre, and there is no auto-orientation
  to the segment. See :func:`_hatches`. ``mxGraphView.getPoint``,
  ``mxGraphView.updateCellState``, ``mxShape.updateTransform``.
* **draw.io ships no P&ID signal-line style of any kind.**
  ``diagramly/sidebar/Sidebar-PID.js`` registers no edge template at all
  -- every entry in all thirteen of its palettes is
  ``createVertexTemplateEntry`` -- and nothing in ``stencils/pid/`` is a
  line. So the hatch in :func:`_hatches` is built rather than
  referenced.
* **``direction`` is a rotation of 0/90/180/270 for
  east/south/west/north, and north and south swap the painting box's
  width and height first.** They also **swap ``flipH`` with ``flipV``**.
  ``mxShape.getShapeRotation``, ``mxShape.paint``, ``mxShape.apply``.
  This is what :meth:`DrawioRenderer._flag_shape` turns an
  ``offPageConnector`` with.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import NamedTuple, TYPE_CHECKING

from pandid.portgeom import _xform, port_point, symbol_to_box, unit_box
# ISO 10628-1 5.3.1 c) detail weight, shared so parts match the sheet.
from pandid.render.iso_parts import PART_STROKE as _PART_STROKE
from pandid.render import furniture as F
from pandid.render import generator
from pandid.render import svg as _svg
from pandid.render.escape import escaped, writable
from pandid.render.svg import (_DIAMOND_BALLOONS, _ENCLOSURE_STROKE,
                               _furniture_name, _LABEL_CODES, _RENDER_CODES,
                               _LEADER_HEAD, _scale_text, _Sheet, _too_small,
                               _SIGNAL_DASH, _stream_rung, _TAP_DASH,
                               fit_issue, HOP_R,
                               NUMBER_TYPE, boundary_flag, enclosure_shape,
                               label_findings,
                               draws_arrowheads, flange_marks, impulse_tap,
                               resolve_connections, sheet_connections,
                               stream_numbers, stream_polyline, tap_lines)
from pandid.render.symbols import (ARROWHEAD, TRAP_BODY_D, TRAP_LEAD, TRAP_W,
                                   closed_marking, fail_marking, wears_arrowhead)
from pandid.render.weights import LineWeight
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame

# Stencil ink, as scripts/mxgraph_to_svg.py converts it and as
# symbols._BODY_INK; repeated because scripts/ is not installed.
_INK = "#111"

# Fill for everything this file draws itself: the paper shows through.
_NO_FILL = "none"

# Fill for a vendored stencil: the page colour its artwork was authored
# under, so its body covers the nozzles behind it
# (scripts/mxgraph_to_svg.DEFAULT_FILL).
_PAPER = "#ffffff"

# No stroke. mxStylesheet.getCellStyle deletes a key whose value is
# ``none``, so the cell strokes nothing but stays selectable and
# connectable. (``shape=none`` is the trap: deleting that key draws the
# default rectangle.)
_NO_STROKE = "none"

# --- line weights -----------------------------------------------------
# Every width comes from :class:`~.weights.LineWeight`, the ladder the
# sheet uses. A pen must be stated on every cell, because the vendored
# stencils declare ``strokewidth="inherit"`` and would otherwise draw at
# draw.io's default 1. Every width goes through ``fit.length`` so it
# scales with a fitted drawing.

# Ink for lines: the SVG strokes streams ``black`` and stencils ``#111``,
# and both are kept as the sheet has them.
_LINE_INK = "#000000"

# draw.io's ``jumpStyle`` for the sheet's arc hop (one of none, arc, gap,
# sharp, line; EditorFormatPanel.addLineJumps). mxConnector.paintLine
# draws a cubic whose crown is 0.975 of the hop's half-extent, so it is
# slightly shallower than a semicircle. draw.io chooses the bulge side
# from the segment direction (east of vertical runs, north of horizontal
# ones), while the sheet follows the routing direction, so the two can
# bulge on opposite sides.
_JUMP_STYLE = "arc"

# ``jumpStyle`` for each crossing style draw.io can draw; the names are
# draw.io's. ``"plain"`` is absent: it writes no jumpStyle, and _hops
# leaves the edge order unchanged.
_JUMP_STYLES = {"arc": _JUMP_STYLE, "gap": "gap"}

# Style for edges that are not streams (furniture rules, instrument
# connections, leaders). Only streams hop or are hopped on the sheet, but
# draw.io would hop any edge, and _hops reorders edges, so the rule is
# stated with ``noJump=1``.
_NO_HOP = "noJump=1;"


def _jump_size(radius: float, weight: float) -> int:
    """Return draw.io's ``jumpSize`` for a hop of ``radius`` on a line of ``weight``.

    ``mxConnector.paintLine`` makes the hop's half-extent
    ``(parseInt(jumpSize) - 2) / 2 + strokewidth``, using the edge's own
    pen, so ``jumpSize = 2 (radius - weight) + 2``. ``parseInt`` truncates,
    so the value is rounded here. The floor of 1 stops a negative
    half-extent drawing the hop inside out (draw.io's default is 6).

    Parameters
    ----------
    radius : float
        Hop radius in drawing units.
    weight : float
        Edge stroke width.

    Returns
    -------
    int
        ``jumpSize`` value.
    """
    return max(1, round(2.0 * (radius - weight) + 2.0))


def _hops(polylines: dict, direction: str,
          style: str = "arc") -> "tuple[list, set, set]":
    """Return the stream edge order, the edges that hop, and the hops lost.

    The sheet's rule picks the hopping line: a vertical segment hops a
    horizontal one (the reverse under ``jump_direction="horizontal"``),
    for crossings strictly inside both segments and at least ``HOP_R``
    from the hopper's segment ends, as
    :meth:`SvgRenderer._draw_streams` draws them.

    ``mxGraphView.updateLineJumps`` hops an edge only over edges written
    before it, so each hopper must follow everything it crosses. Edges are
    emitted in a stable topological order ("crossed before crossing", ties
    by original index), so a sheet without crossings keeps its order.

    ``jumpStyle`` is per edge and cannot be aimed. Where two edges each
    hop the other (a cycle), or a crossing is too near a segment end for
    the sheet to draw an arc, an edge that would hop the wrong line or
    draw a hop the sheet does not gives up its style: a flat crossing is
    ambiguous, but a reversed hop states something false.

    Parameters
    ----------
    polylines : dict
        ``{key: points}`` for every stream, in write order.
    direction : str
        ``jump_direction``; any value other than ``"vertical"`` or
        ``"horizontal"`` hops nothing.
    style : str, default="arc"
        ``crossing_style``; one without a draw.io jump style (``"plain"``)
        hops nothing.

    Returns
    -------
    order : list
        Keys in write order.
    kept : set
        Keys that carry ``jumpStyle``.
    lost : set
        ``(hopper, crossed, x, y)`` for each crossing the sheet hops and
        the export draws flat.
    """
    keys = list(polylines)
    if style not in _JUMP_STYLES or direction not in ("vertical", "horizontal"):
        return keys, set(), set()
    # Hopping and crossed segments by owner, as _draw_streams splits them.
    hopping: list = []
    crossed: list = []
    for key, points in polylines.items():
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                (crossed if direction == "vertical" else hopping).append(
                    (key, min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                (hopping if direction == "vertical" else crossed).append(
                    (key, min(y1, y2), max(y1, y2), x1))
    # (crossed, hopper): the crossed edge must be written first.
    after: dict = {key: set() for key in keys}
    # Who may hop each edge, to tell a lost hop from a wrong one.
    hopped_by: dict = {key: set() for key in keys}
    hops: set = set()
    # Crossings keyed by position too: two runs may cross more than once.
    crossings: set = set()
    # Crossings the sheet draws flat (within HOP_R of a segment end) but
    # draw.io would hop, keyed by the edge that must then drop its style.
    marginal: dict = {key: set() for key in keys}
    for hop_key, lo, hi, at in hopping:
        for cross_key, c_lo, c_hi, c_at in crossed:
            # Same test as _draw_streams: the arc needs HOP_R either side.
            if not (c_lo < at < c_hi and lo + HOP_R < c_at < hi - HOP_R):
                if c_lo < at < c_hi and lo < c_at < hi and hop_key != cross_key:
                    # Drawn flat, so whichever edge is written second must
                    # not carry the style.
                    marginal[hop_key].add(cross_key)
                    marginal[cross_key].add(hop_key)
                continue
            # A run never hops itself, in draw.io either.
            if hop_key == cross_key:
                continue
            hops.add(hop_key)
            after[hop_key].add(cross_key)
            hopped_by[cross_key].add(hop_key)
            point = (at, c_at) if direction == "vertical" else (c_at, at)
            crossings.add((hop_key, cross_key, *point))
    if not hops:
        return keys, hops, set()
    # Kahn's algorithm, lowest original index first, to stay near stream
    # order.
    order: list = []
    done: set = set()
    while len(done) < len(keys):
        ready = [key for key in keys if key not in done and not (after[key] - done)]
        if not ready:  # a cycle: see the docstring
            break
        order.append(ready[0])
        done.add(ready[0])
    # Whatever the cycle left behind, in stream order.
    order += [key for key in keys if key not in done]
    # Drop the style from an edge written after one entitled to hop it
    # (only possible in a cycle; otherwise this keeps every hop).
    rank = {key: n for n, key in enumerate(order)}
    # Also drop it from an edge with a marginal crossing against an earlier
    # edge, since draw.io would draw a hop the sheet does not.
    kept = {key for key in hops
            if all(rank[other] > rank[key] for other in hopped_by[key])
            and all(rank[other] > rank[key] for other in marginal[key])}
    # Every crossing the sheet hops and the export draws flat, per crossing
    # rather than per edge, so the caller can report each one.
    lost = {(hop_key, cross_key, x, y)
            for hop_key, cross_key, x, y in crossings
            if hop_key not in kept or rank[cross_key] > rank[hop_key]}
    return order, kept, lost


# Clockwise turn -> draw.io ``direction`` (mxShape.getShapeRotation adds
# 90 for south, 180 for west, 270 for north). No entry for 0.
_DIRECTION = {90: "south", 180: "west", 270: "north"}


def _placed_rect(frame, x: float, y: float, w: float, h: float
                 ) -> "tuple[float, float, float, float]":
    """Return a child rectangle, given in symbol fractions, in the placed cell.

    mxGraph does not apply a parent's ``direction`` or flips to a child's
    geometry, so a child that is part of the drawing is turned here, through
    :func:`~pandid.portgeom.symbol_to_box` on the unit square, the same map
    the ports use. :meth:`DrawioRenderer._inscribed` fills the whole box
    and needs none of this.

    Parameters
    ----------
    frame : Frame
        Parent unit's frame.
    x, y, w, h : float
        Rectangle in symbol fractions.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x, y, w, h)`` in cell fractions; axes swapped by a quarter turn.
    """
    rot, mirror_x, mirror_y = _xform(frame)
    corners = [symbol_to_box(px, py, 1.0, 1.0, rot, mirror_x, mirror_y)[:2]
               for px, py in ((x, y), (x + w, y + h))]
    xs = sorted(point[0] for point in corners)
    ys = sorted(point[1] for point in corners)
    return xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]


def _turn_keys(frame) -> list[str]:
    """Return the ``direction`` key that turns a child cell's shape with its parent.

    :func:`_placed_rect` turns the child's geometry; this turns how the
    shape paints inside it (``mxLine`` and agitator stencils are not
    symmetric).

    Parameters
    ----------
    frame : Frame
        Parent unit's frame.

    Returns
    -------
    list[str]
        ``["direction=..."]``, or empty when unturned.
    """
    rot, _mirror_x, _mirror_y = _xform(frame)
    return [] if rot not in _DIRECTION else [f"direction={_DIRECTION[rot]}"]


class _Fit(NamedTuple):
    """Map drawing coordinates onto the page.

    With a page size the drawing is fitted into the space the furniture
    leaves, as the SVG's ``<g id="drawing" transform=...>`` does. Drawing
    coordinates go through this; sheet coordinates (furniture, border) do
    not. Without a page it is the identity.

    Attributes
    ----------
    scale : float
        Scale factor.
    dx, dy : float
        Translation.
    """
    scale: float
    dx: float
    dy: float

    @classmethod
    def identity(cls) -> "_Fit":
        """Return the identity fit, for an export without a page."""
        return cls(1.0, 0.0, 0.0)

    def at(self, x: float, y: float) -> "tuple[float, float]":
        """Return a drawing point on the page."""
        return (self.dx + self.scale * x, self.dy + self.scale * y)

    def box(self, b) -> "tuple[float, float, float, float]":
        """Return a drawing box ``(x0, y0, x1, y1)`` on the page."""
        return (*self.at(b[0], b[1]), *self.at(b[2], b[3]))

    def length(self, v: float) -> float:
        """Return a length (stroke width, mark size) scaled but not translated."""
        return self.scale * v


class _Piece(NamedTuple):
    """A built-in shape placed inside a stand-in's cell, in fractions of it.

    For stand-ins whose parts sit at different places along the cell, such
    as a steam trap's body between two leads. The rectangle is converted
    like an :class:`~pandid.render.symbols.Overlay`
    (:meth:`DrawioRenderer._pieces`); the parent cell draws nothing and
    holds the connection points.

    Attributes
    ----------
    shape : str or None
        draw.io built-in (never a stencil key); ``None`` is the rectangle.
    x, y, w, h : float
        Rectangle in fractions of the cell.
    """

    shape: "str | None"
    x: float
    y: float
    w: float
    h: float


class _Approximation(NamedTuple):
    """A draw.io built-in standing in for a symbol with no draw.io stencil.

    Built-ins are compiled into draw.io, so unlike stencil keys they cannot
    fail to resolve. The accepted names are ``_BUILTIN_SHAPES`` in
    ``tests/test_drawio.py`` (mxGraph's built-ins plus draw.io's own).

    Attributes
    ----------
    shape : str or None
        Built-in shape name; ``None`` is draw.io's default rectangle.
    lost : str
        What the sheet draws that the stand-in does not; reported under
        :data:`APPROXIMATED`. Empty when nothing is lost.
    flip_h : bool
        Mirror the built-in, for a shape draw.io points the other way.
    fill : str
        The symbol's own fill; opaque white for a balloon, which masks the
        line it is drawn over.
    stroke : str
        Ink colour; a pipe tee uses the line's black, not the stencil's.
    weight : float
        Stroke width: EQUIPMENT, or DETAIL for symbols whose
        :class:`~.symbols.Symbol` carries :attr:`~.symbols.Symbol.trim`
        (balloons and the in-line mixers).
    keys : tuple
        Extra style keys.
    inscribed : str or None
        A second built-in filling the same box, for a symbol that is two
        outlines (:meth:`DrawioRenderer._vertex`).
    pieces : tuple[_Piece, ...]
        Built-ins placed within the cell instead of ``shape``.
    """

    shape: str | None
    lost: str
    flip_h: bool = False
    fill: str = _NO_FILL
    stroke: str = _INK
    weight: float = LineWeight.EQUIPMENT.width
    keys: tuple = ()
    inscribed: "str | None" = None
    pieces: "tuple[_Piece, ...]" = ()


# Relative aspect drift allowed before _report_reshape reports a
# reproportioned symbol; looser than layout rounding, tighter than anything
# visible.
_ASPECT_SLACK = 1e-3

#: Warning code for a stand-in that loses part of its symbol; the message
#: names the unit and the stand-in's ``lost`` sentence.
APPROXIMATED = "drawio-approximated"

#: Warning code for a crossing the sheet hops and the export draws flat
#: (see :func:`_hops`): a flat crossing is ambiguous, a reversed hop would
#: be wrong.
HOP_DROPPED = "drawio-hop-dropped"

# Codes this backend puts on fs.warnings; replaced on each export.
_EXPORT_CODES = (*_RENDER_CODES, *_LABEL_CODES, APPROXIMATED, HOP_DROPPED)


# Balloon fill: opaque, so a balloon masks the line it is drawn over.
_BALLOON_FILL = "#ffffff"

# Every symbol the library draws itself (no draw.io stencil exists), with
# the built-in drawn instead and what it loses. Balloons keep their
# outline and lose only the location marking (bar or surrounding square).
_APPROXIMATIONS = {
    # ISA balloons -----------------------------------------------
    # Every balloon carries the DETAIL rung: a PCE symbol is ISO
    # 10628-1 §5.3.1 c), never b), whichever built-in stands in for it.
    ("instrument", "default"): _Approximation(
        # A circle is a circle: nothing lost.
        "ellipse", "", fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    ("instrument", "panel"): _Approximation(
        "ellipse", "the bar across the balloon that puts the instrument in a panel",
        fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    ("instrument", "aux"): _Approximation(
        "ellipse", "the double bar that puts the instrument in an auxiliary panel",
        fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    ("instrument", "shared"): _Approximation(
        "ellipse", "the square around the balloon that puts the function in a "
                   "shared display, and the bar that puts it in the control room",
        fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    ("instrument", "computer"): _Approximation(
        # The computer hexagon, drawn as one.
        "hexagon", "", fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    # A diamond inscribed in a square: two outlines, two cells. ``logic``
    # is the same Symbol as ``sis``, so the entries must match.
    ("instrument", "sis"): _Approximation(
        None, "", fill=_BALLOON_FILL, inscribed="rhombus", weight=LineWeight.DETAIL.width),
    ("instrument", "logic"): _Approximation(
        None, "", fill=_BALLOON_FILL, inscribed="rhombus", weight=LineWeight.DETAIL.width),
    ("instrument", "interlock"): _Approximation(
        # A bare diamond, drawn as one.
        "rhombus", "", fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width),
    # junctions and boundaries -----------------------------------
    # A mixer is a triangle pointing the way the streams combine,
    # which is draw.io's own triangle; a splitter is that triangle
    # turned round, which is that triangle flipped.
    ("mixer", "default"): _Approximation("triangle", ""),
    ("splitter", "default"): _Approximation("triangle", "", flip_h=True),
    # Bare pipe: the cell draws nothing. _constraint lands every stream on
    # the box centre, so the three edges meet at one point, collinear with
    # their approaches. The invisible cell keeps the edges attached when
    # the junction is dragged.
    ("tee", "default"): _Approximation(None, "", stroke=_NO_STROKE),
    # Drawn as ``offPageConnector`` (Shapes.js OffPageConnectorShape), five
    # points with a flat back, turned by ``direction``; see _BOUNDARY_SHAPE,
    # which sizes it per cell. Not ``step``, whose notch cannot be removed.
    ("feed", "default"): _Approximation(None, ""),
    ("product", "default"): _Approximation(None, ""),
    # Built to its length, so no stencil. draw.io's "Drier (Roller Conveyor
    # Belt)" would draw a drier.
    ("conveyor", "default"): _Approximation(
        None, "the belt and its two rollers"),
    # Exact: a BFD block is draw.io's default rectangle.
    ("block", "default"): _Approximation(None, ""),
    # Neither ISO nor draw.io has a tubular reactor; draw.io's nearest is an
    # exchanger, which is different equipment.
    ("reactor", "tubular"): _Approximation(
        None, "the tube pass inside the shell"),
    # Composed separating vessels (items 8.3, 8.6, 8.8): the mark is a child
    # cell; the rectangle loses the V bottom, since draw.io has no stencil
    # for the bare body and a composed symbol may not name a stencil.
    ("separator", "gravity"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    ("separator", "electrostatic"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    ("separator", "electromagnetic"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    # ISO group 11: no crusher or mill stencil and no trapezoid built-in, so a
    # rectangle. The group-29 mark is still exported as a child cell.
    ("crusher", "default"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("crusher", "cone"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("crusher", "hammer"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("crusher", "impact"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("crusher", "jaw"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("crusher", "roller"): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it"),
    ("mill", "default"): _Approximation(
        None, "the trapezoid outline and its chamfered top corners"),
    ("mill", "hammer"): _Approximation(
        None, "the trapezoid outline and its chamfered top corners"),
    ("mill", "impact"): _Approximation(
        None, "the trapezoid outline and its chamfered top corners"),
    ("mill", "roller"): _Approximation(
        None, "the trapezoid outline and its chamfered top corners"),
    ("mill", "vibration"): _Approximation(
        None, "the trapezoid outline, its chamfered top corners and the drum"),
    # ISO item 11.1, the general machine both bodies above are built on:
    # the bare trapezoid, neither mark drawn.
    ("crushing_machine", "default"): _Approximation(
        None, "the trapezoid outline"),
    # Evaporators: no matching stencil (hex/thin_film is a wiped-film
    # column), so a rectangle; each sentence names the lost element.
    ("evaporator", "default"): _Approximation(
        None, "the dished heads and the boxed heating element between the tubesheets"),
    ("evaporator", "calandria"): _Approximation(
        None, "the dished heads and the short tube bundle around its central downcomer"),
    ("evaporator", "falling_film"): _Approximation(
        None, "the dished heads, the long tube bundle and the distributor over it"),
    ("evaporator", "climbing_film"): _Approximation(
        None, "the dished heads and the long tube bundle"),
    ("evaporator", "plate"): _Approximation(
        None, "the dished heads and the plate pack between them"),
    # Kilns: no stencil, so a rectangle.
    ("kiln", "default"): _Approximation(
        None, "the shell's fall from feed end to discharge, its riding rings and its drive"),
    ("kiln", "fluidized_bed"): _Approximation(
        None, "the dished crown, the windbox cone and the distributor grid over it"),
    ("kiln", "shaft"): _Approximation(
        None, "the charging cone, the discharge cone and the calcining zone between them"),
    # ISO group 9: no centrifuge stencil. ``default`` and ``decanter`` are
    # one Symbol, so their entries match.
    ("centrifuge", "default"): _Approximation(
        None, "the square outline, the basket's solid walls and the screw"),
    ("centrifuge", "high_speed"): _Approximation(
        None, "the square outline and the open rotor drawn inside it"),
    ("centrifuge", "perforated_shell"): _Approximation(
        None, "the square outline and the basket's broken walls"),
    ("centrifuge", "solid_shell"): _Approximation(
        None, "the square outline and the basket's solid walls"),
    ("centrifuge", "disc"): _Approximation(
        None, "the square outline and the disc stack drawn inside it"),
    ("centrifuge", "screw_perforated"): _Approximation(
        None, "the square outline, the basket's broken walls and the screw"),
    ("centrifuge", "decanter"): _Approximation(
        None, "the square outline, the basket's solid walls and the screw"),
    ("centrifuge", "pusher"): _Approximation(
        None, "the square outline, the basket's broken walls and the pusher plate"),
    ("centrifuge", "skimmer"): _Approximation(
        None, "the square outline, the basket's broken walls and the skimmer tube"),
    # ISO group 18: no stencils (draw.io's "Screw Pump" is a different
    # machine). The screw casing is a rectangle; elevators lose their
    # interiors, and the Z-form its outline.
    ("conveyor", "screw"): _Approximation(
        None, "the screw's axis and the turns of its flight"),
    ("elevator", "default"): _Approximation(
        None, "the belt, its two pulleys and the loading and discharge chutes"),
    ("elevator", "z_form"): _Approximation(
        None, "the Z-shaped casing, the belt's three runs and its four pulleys"),
    # ISO group 4: no stencil or close built-in.
    ("boiler", "default"): _Approximation(
        None, "the shell's own outline and the dome on its crown"),
    ("stack", "default"): _Approximation(
        None, "the tapered shaft and the foundation flange under it"),
    ("flare", "default"): _Approximation(
        None, "the shaft and the flame on its tip"),
    # ISO 10628-2 group 10, the four rows built the way group 11's
    # crushers are: one casing, composed here rather than vendored.
    ("dryer", "general"): _Approximation(
        None, "the casing's chamfered top corners"),
    ("dryer", "shelf"): _Approximation(
        None, "the casing's chamfered top corners and the three shelf lines"),
    ("dryer", "turbo"): _Approximation(
        None, "the casing's chamfered top corners and the rotor shaft and discs"),
    ("dryer", "belt"): _Approximation(
        None,
        "the casing's chamfered top corners and the two rollers the belt runs on"),
    # ISO 10628-2 group 5, the eight rows built the same way: one
    # trapezoid-on-a-basin outline, composed with a fill mark and a
    # draught mark.
    ("cooling_tower", "general"): _Approximation(
        None, "the trapezoid-on-a-basin outline"),
    ("cooling_tower", "dry_natural"): _Approximation(
        None, "the trapezoid-on-a-basin outline and the dry-fill hatch in the basin"),
    ("cooling_tower", "dry_forced"): _Approximation(
        None, "the trapezoid-on-a-basin outline, the dry-fill hatch and the fan "
              "low in the tower"),
    ("cooling_tower", "dry_induced"): _Approximation(
        None, "the trapezoid-on-a-basin outline, the dry-fill hatch and the fan "
              "high in the tower"),
    ("cooling_tower", "wet_natural"): _Approximation(
        None, "the trapezoid-on-a-basin outline and the wet-fill arrow rising "
              "through the tower"),
    ("cooling_tower", "wet_forced"): _Approximation(
        None, "the trapezoid-on-a-basin outline, the wet-fill arrow and the fan "
              "low in the tower"),
    ("cooling_tower", "wet_induced"): _Approximation(
        None, "the trapezoid-on-a-basin outline, the wet-fill arrow and the fan "
              "high in the tower"),
    ("cooling_tower", "wet_dry_natural"): _Approximation(
        None, "the trapezoid-on-a-basin outline and both fill marks in it"),
    # ISO 10628-2 group 19, PROPORTIONERS, FEEDERS AND DISTRIBUTION
    # FACILITIES: no vendored stencil under any name, so the circle or
    # the balance every drawing is built on goes with the mark inside it.
    ("feeder", "general"): _Approximation(
        None, "the circle outline and the Z mark drawn inside it"),
    ("feeder", "rotary_valve"): _Approximation(
        None, "the circle outline and the six-spoke rotor drawn inside it"),
    ("feeder", "rotary_table"): _Approximation(
        None, "the table, its shaft and the rotation arrow drawn on it"),
    ("feeder", "metering"): _Approximation(
        None, "the beam, its two pans and the fulcrum triangle under it"),
    # Item 19.5, the spray nozzle: the header line and the fan below it.
    ("spray_nozzle", "default"): _Approximation(
        None, "the header line and the three-pronged spray fan under it"),
    # ISO 10628-2 group 12's other two in-line mixers, beside the
    # vendored ``fitting/static_mixer`` (which keeps its own stencil):
    # the box and the "N" element or elements drawn inside it.
    ("fitting", "rotary_mixer"): _Approximation(
        None, "the box, its flow axis and the two mixing elements in it",
        weight=LineWeight.DETAIL.width),
    ("fitting", "mixing_path"): _Approximation(
        None, "the box and the three mixing elements in it", weight=LineWeight.DETAIL.width),
    # Item 24.15 (2181). draw.io's "Steam Trap" is an empty rectangle (see
    # scripts/vendor_symbols.py), so three pieces: two ``line`` leads
    # (mxLine strokes its box at mid-height) and an ``ellipse`` body, in
    # the symbol's own proportions. Only the diagonal and the half fill
    # are lost.
    ("fitting", "steam_trap"): _Approximation(
        None,
        "the 45-degree diameter across the body and the discharge half filled below it",
        # Transparent: only balloons are exported opaque.
        weight=LineWeight.DETAIL.width,
        pieces=(
            _Piece("line", 0.0, 0.0, TRAP_LEAD / TRAP_W, 1.0),
            _Piece("ellipse", TRAP_LEAD / TRAP_W, 0.0, TRAP_BODY_D / TRAP_W, 1.0),
            _Piece("line", (TRAP_LEAD + TRAP_BODY_D) / TRAP_W, 0.0,
                   TRAP_LEAD / TRAP_W, 1.0),
        )),
    # Item 12.4, the kneader: the casing and the wave its blades draw.
    ("kneader", "default"): _Approximation(
        None, "the casing and the wave the blades draw across it"),
    # ISO group 7: no stencil (separator/sifter keeps its own and is not one
    # of these rows), so the outline goes with the mark.
    ("screening_device", "general"): _Approximation(
        None, "the wall-and-point outline and the corner-to-corner mesh diagonal"),
    ("screening_device", "coarse_rake"): _Approximation(
        None, "the outline, the mesh diagonal and its three coarse rake teeth"),
    ("screening_device", "fine_rake"): _Approximation(
        None, "the outline, the mesh diagonal and its five fine rake teeth"),
    ("screening_device", "coarse_and_fine"): _Approximation(
        None, "the outline and its two parallel mesh diagonals"),
    ("screening_device", "vibrating"): _Approximation(
        None, "the outline, the mesh diagonal and the double arrow beside it"),
    ("screening_device", "rotating_drum"): _Approximation(
        None, "the outline and the dashed drum drawn inside it"),
    ("screening_device", "basket_reel"): _Approximation(
        None, "the outline, the reel's two rollers and the dashed rails between them"),
}

# Built-in stand-ins for ISO 10628-2 parts draw.io has no shape for. The
# ten group-28 agitators are absent: they name draw.io's own
# ``mxgraph.pid.agitators`` stencils
# (:attr:`~pandid.render.symbols.OverlayPart.drawio_shape`).
# ``partialRectangle`` draws only the sides asked for, which fits legs,
# rings, skirts and precipitator plates.
_PART_APPROXIMATIONS = {
    # ---- group 26, apparatus elements ----
    # A channel section closed at the foot and open at the top, which is
    # three sides of a rectangle. Nothing lost.
    (26, "leg"): _Approximation("partialRectangle", "", keys=("top=0",)),
    # A gusset: a foot, a hypotenuse, and the wall it bears on. draw.io's
    # triangle is isoceles and points east, so a quarter turn stands it on
    # its foot at the cost of the right angle.
    (26, "bracket"): _Approximation(
        "triangle", "the gusset's right angle: draw.io's triangle is isoceles",
        keys=("direction=north",)),
    # Two walls, open between them, with a foot turned in at each base.
    (26, "skirt"): _Approximation(
        "partialRectangle", "the two feet turned in at the base ring",
        keys=("top=0", "bottom=0")),
    # A 4 M x 1 M ledge, closed on three sides and open against the wall.
    # Nothing lost.
    (26, "ring"): _Approximation("partialRectangle", "", keys=("right=0",)),
    # ---- group 27, internals ----
    # A deck is a line across the shell and ``line`` is a line across the
    # cell; what varies between the six is what stands on the deck.
    (27, "tray"): _Approximation("line", ""),
    (27, "baffle_tray"): _Approximation("line", "the riser at the deck's end"),
    (27, "bubble_cap_tray"): _Approximation("line", "the cap over the deck's opening"),
    (27, "valve_tray"): _Approximation("line", "the valve lifted clear of the deck"),
    # These two are told apart from a plain deck, and from each other, by
    # nothing but their dash pattern, so the pattern is the whole of what
    # has to survive.
    (27, "sieve_tray"): _Approximation(
        "line", "", keys=("dashed=1", "dashPattern=8 4")),
    (27, "filter_insert"): _Approximation(
        "line", "", keys=("dashed=1", "dashPattern=8 4 4 4")),
    # A field of dots. The box is the bed's extent, which is the part of it
    # a reader needs; the texture has no built-in.
    (27, "fluidised_bed"): _Approximation(
        None, "the staggered field of dots; the box is the bed's extent"),
    # A bed between two dashed support lines with a large X across it. The
    # bounds are drawn and the X is not.
    (27, "packing"): _Approximation(
        "partialRectangle", "the X across the bed",
        keys=("left=0", "right=0", "dashed=1", "dashPattern=8 4")),
    # ---- group 20, drives ----
    # A circle with an M in it. ``ellipse`` draws the circle; the letter
    # would have to be the cell's own ``value``, and that is the tag
    # column -- a child cell lettered "M" would read as a second unit.
    (20, "motor"): _Approximation("ellipse", "the M inside the circle"),
    # ---- group 29, internal characteristics ----
    # A down arrow. draw.io's triangle turned south is its head; the shaft
    # above it has no built-in that is not a second cell.
    (29, "gravity"): _Approximation(
        "triangle", "the arrow's shaft above its head", keys=("direction=south",)),
    # Two plates a module apart, which is two sides of a rectangle.
    (29, "electrostatic"): _Approximation(
        "partialRectangle", "the leads going out from the two plates",
        keys=("top=0", "bottom=0")),
    # A coil standing on a baseline. The baseline is drawn.
    (29, "electromagnetic"): _Approximation(
        "line", "the three turns standing on the coil's baseline"),
    # 29.4 to 29.14: most have no built-in and use the rectangle as the
    # mark's extent; the rest name a built-in that draws part of it.
    (29, "disc"): _Approximation(
        None, "the shaft, its two plates and the arms between them; "
              "the box is the rotor's extent"),
    (29, "crushing"): _Approximation(None, "the X between the box's corners"),
    # A rectangle, not an ellipse: an oval would be a different drawing and
    # would make 29.6 and 29.11 identical.
    (29, "gear"): _Approximation(None, "the two meshing wheels; the box is the pair's extent"),
    (29, "hammer"): _Approximation(
        None, "the four hammers on their rotor; the box is the rotor's extent"),
    (29, "impact"): _Approximation(
        None, "the rotor at the centre and the four arms out to the corners"),
    # A line into a circle, and the line is drawn -- the same trade
    # 27.2's baffle tray and 29.3's coil both take.
    (29, "jaw"): _Approximation("line", "the circle the jaw's line runs into"),
    # The mark *is* a line; only the two dips scalloped out of it go.
    (29, "liquid"): _Approximation("line", "the two dips scalloped out of the line"),
    (29, "roller"): _Approximation(None, "the two rolls; the box is the pair's extent"),
    # A trapezoid, and draw.io has no trapezoid built in. Its triangle
    # is isoceles and points east, so a quarter turn stands it on the
    # wide base at the cost of the flat top.
    (29, "cone"): _Approximation(
        "triangle", "the trapezoid's flat top: draw.io's triangle comes to a point",
        keys=("direction=north",)),
    # The one of the eleven a built-in draws outright: the mark's
    # outline is a circle filling its box.
    (29, "jet"): _Approximation(
        "ellipse", "the diameter and the two chords drawn across the circle"),
    (29, "vibration"): _Approximation(
        None, "the two arrows and the opposite ways they point"),
}

# Type size for drawing lettering (tags, instrument letters, flag names),
# matching the SVG renderer's 12. Line numbers use svg.NUMBER_TYPE.
_TAG_TYPE = 12.0


class _Tags(NamedTuple):
    """Result of the sheet's equipment-tag placement pass.

    Attributes
    ----------
    at : dict
        ``id(unit)`` -> ``(side, dx, dy)``: the side the tag settled on and
        its step along it, in drawing units.
    plates : list
        Opaque boxes of tags and ``NC``/fail letters, which
        :func:`~pandid.render.svg.stream_numbers` must keep line numbers
        off.
    codes : list
        :func:`~pandid.render.svg.quadrant_labels` items, exported by
        :func:`_quadrant_cell`.
    """
    at: dict
    plates: list
    codes: list


def _tag_pass(fs, registry, joints: "str | None", direction: str) -> "_Tags":
    """Run the sheet's tag placement without drawing anything.

    Calls the sheet's own placement methods
    (:meth:`~SvgRenderer._tag_item`, :meth:`~SvgRenderer._nc_label_item`,
    :meth:`~SvgRenderer._fail_label_item`) so the two backends cannot
    disagree; only the walk over units is repeated. Text is escaped before
    measuring, as the sheet measures the escaped string. Instruments,
    boundary flags and untagged units are skipped, as on the sheet.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    registry : SymbolRegistry
        Symbol registry.
    joints : str or None
        Sheet joint default, whose flange marks tags avoid.
    direction : str
        ``jump_direction``.

    Returns
    -------
    _Tags
        Tag placements, plates and quadrant codes.
    """
    from pandid.render.svg import (SvgRenderer, _ink, _unit_label_box,
                                   flange_boxes, quadrant_labels)

    sheet = SvgRenderer(registry)
    ink = _ink(fs, direction)
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    # Flange marks are ink tags must avoid, as on the sheet.
    symbols += [(None, b) for b in flange_boxes(fs, joints)]
    # Quadrant codes are placed first, as in _draw_units, so tags see them.
    codes = quadrant_labels(fs, direction)
    symbols += [(None, b) for b in map(_unit_label_box, codes) if b is not None]
    at: dict = {}
    items: list = []
    for u in fs.units:
        f = u.frame
        if f is None or u.kind in ("feed", "product", "instrument"):
            continue
        x, y, w, h = f.x, f.y, f.w, f.h
        tag_box = None
        if u.tag:
            item = sheet._tag_item(u, f, x, y, w, h, escaped(u.tag),
                                   ink, symbols)
            tag_box = _unit_label_box(item)
            items.append(item)
            # Record the side and the step from that side's untouched spot,
            # as draw.io states them (_LABEL_SIDE plus an offset).
            side = item[4]
            base = sheet._label_place(side, x, y, w, h)
            at[id(u)] = (side, item[0] - base[0], item[1] - base[1])
        if closed_marking(u, registry) == "NC":
            items.append(sheet._nc_label_item(u, f, x, y, w, h, tag_box))
        letters = fail_marking(u)
        if letters:
            items.append(sheet._fail_label_item(u, f, x, y, w, h, letters, tag_box,
                                                ink, symbols))
    return _Tags(at, [b for b in map(_unit_label_box, items) if b is not None],
                 codes)


def _quadrant_cell(cid: str, item, fit: "_Fit") -> list[str]:
    """Return a quadrant letter code as a text cell.

    Placed where :func:`~pandid.render.svg.quadrant_labels` put it, in its
    own cell since a balloon's label is its tag, with a white
    ``labelBackgroundColor`` halo. The text arrives HTML-escaped from the
    sheet and :func:`_attr` escapes it again for XML; only the width is
    measured on the unescaped text.

    Parameters
    ----------
    cid : str
        Cell id.
    item : tuple
        Quadrant label item.
    fit : _Fit
        Page fit.

    Returns
    -------
    list[str]
        ``mxCell`` XML lines.
    """
    import html as _html

    lx, ly, anchor, _baseline, _lpos, text = item
    size = fit.length(_TAG_TYPE)
    x, y = fit.at(lx, ly)
    box_w = F.text_width(_html.unescape(text), size) + 2 * _TEXT_INSET
    box_h = _line_box(size) + 2 * _TEXT_INSET
    left, align = ((x + _TEXT_INSET - box_w, "right") if anchor == "end"
                   else (x - _TEXT_INSET, "left"))
    style = ("text;html=1;strokeColor=none;fillColor=none;"
             f"labelBackgroundColor=#ffffff;align={align};"
             f"verticalAlign=middle;fontSize={size:g};fontColor={_LINE_INK};")
    return [
        f'        <mxCell id="{cid}" value={_attr(text)} style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(left)}" y="{_num(y - box_h / 2)}" '
        f'width="{_num(box_w)}" height="{_num(box_h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _drawn_type(nominal: float, fit: "_Fit", *, lines: int = 1, box=None) -> str:
    """Return the ``fontSize`` key for lettering in the drawing.

    The size scales with :class:`_Fit`, as the SVG's group transform
    scales its text. Text inside a shape (a flag or balloon) is also capped
    so ``lines`` lines fit ``box``'s depth, since mxGraph does not shrink
    text to fit.

    Parameters
    ----------
    nominal : float
        Unscaled size.
    fit : _Fit
        Page fit.
    lines : int, default=1
        Lines of text inside the shape.
    box : tuple, optional
        Cell box in drawing units, for the cap.

    Returns
    -------
    str
        ``fontSize=...``.
    """
    size = nominal
    if box is not None and lines > 0:
        depth = abs(box[3] - box[1])
        size = min(size, depth / (lines * _LINE_BOX))
    return f"fontSize={fit.length(size):g}"


def _attr(value) -> str:
    """Return an XML attribute value, quoted and escaped.

    Escapes exactly the five XML entities, so a ``<br>`` in a label reaches
    draw.io's HTML parser as a tag. Characters XML 1.0 2.2 cannot represent
    are removed first, as :func:`~pandid.render.escape.escaped` does.

    Parameters
    ----------
    value : object
        Value to write.

    Returns
    -------
    str
        Quoted attribute value.
    """
    text = writable(value)
    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                         ('"', "&quot;"), ("'", "&apos;")):
        text = text.replace(char, entity)
    return f'"{text}"'


def _html_text(value) -> str:
    """Return author text escaped for an HTML draw.io ``value``.

    Escapes ``&``, ``<`` and ``>`` for the HTML layer; :func:`_attr` then
    escapes for XML, so typed markup shows literally. Quotes need no HTML
    escaping in element content. Only the library's own ``<br>`` bypasses
    this: escape each piece of author text, then join with ``<br>``.

    Parameters
    ----------
    value : object
        Author text.

    Returns
    -------
    str
        Escaped text.
    """
    text = writable(value)
    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;")):
        text = text.replace(char, entity)
    return text


def _num(v: float) -> str:
    """Return a coordinate rounded to two decimals, for stable diffs.

    Parameters
    ----------
    v : float
        Coordinate in drawing units (CSS pixels).

    Returns
    -------
    str
        Formatted number.
    """
    return f"{round(float(v), 2):g}"


def _dash(pattern: str) -> list[str]:
    """Return draw.io dash style keys for an SVG dash pattern.

    ``mxSvgCanvas2D.createDashPattern`` splits on spaces (a comma gives
    ``NaN``), so commas become spaces. ``fixDash=1`` stops draw.io
    multiplying the pattern by the stroke width, so the numbers stay in
    drawing units.

    Parameters
    ----------
    pattern : str
        SVG ``stroke-dasharray``, or empty for a solid line.

    Returns
    -------
    list[str]
        Style keys; empty for a solid line.
    """
    if not pattern:
        return []
    return ["dashed=1", f"dashPattern={pattern.replace(',', ' ')}", "fixDash=1"]


def _fraction(v: float) -> str:
    """Return a connection-point fraction rounded to six places.

    Six places, since it is multiplied by a box up to hundreds of units
    across.

    Parameters
    ----------
    v : float
        Fraction of the cell box.

    Returns
    -------
    str
        Formatted number.
    """
    return f"{round(float(v), 6):g}"


class DrawioRenderer:
    """Render a laid-out Flowsheet to a draw.io ``mxfile`` document.

    A :class:`pandid.render.Renderer` beside
    :class:`~pandid.render.svg.SvgRenderer`. It reads the same resolved
    geometry (layout frames, routed waypoints, :mod:`pandid.portgeom` port
    points) without re-deriving any, so the two backends agree.

    Parameters
    ----------
    registry : SymbolRegistry, optional
        Symbols to draw with; ``default_registry`` when omitted.
    """

    def __init__(self, registry=None):
        """Store the registry and start an empty findings list."""
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry
        # What the export could not carry across, handed to the flowsheet
        # at the end of render(). A renderer is built fresh per export.
        self._findings: list = []

    def _report(self, field: str, text: str, drawn: str,
                room: float, need: float) -> None:
        """Record a cell that could not hold its text.

        A :data:`~pandid.render.furniture.Reporter`, giving the same finding
        as the SVG backend.

        Parameters
        ----------
        field : str
            Field name.
        text : str
            Text supplied.
        drawn : str
            Text drawn.
        room, need : float
            Width available and width needed.
        """
        self._findings.append(fit_issue(field, text, drawn, room, need))

    # --------------------------------------------------- document

    def render(self, fs: "Flowsheet", *, diagram: "str | None" = None,
               page_size: "str | None" = None, border: "str | None" = None,
               connections: "str | None" = None,
               jump_direction: str = "vertical",
               crossing_style: str = "gap",
               show_stream_table: "bool | str" = False, **opts) -> str:
        """Render the flowsheet to a draw.io document.

        The file always states a page size, because draw.io reads a file
        without one as the reader's locale default paper and bounds PDF
        export by it (see :meth:`_document`). Export findings replace those
        of any earlier export on ``fs.warnings``. The debug overlay is
        refused.

        Parameters
        ----------
        fs : Flowsheet
            Laid-out and routed flowsheet.
        diagram : str, optional
            ``"pfd"`` (default), ``"p&id"`` (or ``"pid"``) or ``"bfd"``, as
            for :meth:`~pandid.flowsheet.Flowsheet.to_svg`. A P&ID exports
            its process lines without arrowheads.
        page_size : str, optional
            ``"A4"`` to ``"A0"``: the file carries that page, furniture docks
            to it and the drawing is fitted between, as on the SVG sheet.
            ``None`` keeps the drawing's own coordinates and docks furniture
            to its bounds.
        border : str, optional
            ``"zone"`` draws the frame, sheet edge and lettered band;
            ``"none"`` leaves the page edge as the paper's. Defaults to
            ``"none"``, or ``"zone"`` for a table sheet.
        connections : str, optional
            Joint marked on P&ID streams that state none: ``"flanged"`` or
            ``"none"``. Ignored outside a P&ID
            (:func:`~pandid.render.svg.sheet_connections`).
        jump_direction : str, default="vertical"
            Which of two crossing lines carries the crossing mark. Exported
            as a style key on the marking edges and as their z-order
            (:func:`_hops`).
        crossing_style : str, default="gap"
            ``"gap"``, ``"arc"`` or ``"plain"``
            (:data:`~pandid.render.svg.CROSSING_STYLES`). The first two
            are draw.io line-jump styles; ``"plain"`` writes none.
        show_stream_table : bool or str, default=False
            ``True`` docks the stream table at the foot of the sheet as a
            real table, measured as on the SVG sheet; ``"sheet"`` exports
            the table as its own sheet.
        **opts
            Refused, including ``debug``.

        Returns
        -------
        str
            ``mxfile`` XML document.

        Raises
        ------
        ValueError
            If an argument is invalid, the page is too small, or a unit has
            no frame.
        """
        from pandid.render.svg import (
            _page, _resolve_sheet, check_render_arguments,
            reject_unknown_options, wants_table_sheet)

        # Refuse unknown options, debug included: a .drawio file has no
        # overlay to draw.
        reject_unknown_options("DrawioRenderer.render()", opts)
        arrows = draws_arrowheads(diagram)
        self._findings = []
        # Check every argument before branching, so the table-sheet path
        # does not silently accept a bad value it never uses.
        check_render_arguments(
            fs, show_stream_table=show_stream_table, border=border,
            diagram=diagram, page_size=page_size, connections=connections,
            jump_direction=jump_direction, crossing_style=crossing_style)
        table_sheet = wants_table_sheet(show_stream_table)
        if not table_sheet:
            for u in fs.units:
                if u.frame is None:
                    raise ValueError(
                        f"Unit '{u.name}' lacks a frame even after layout was run.")
        # A table sheet gets the zone frame unless border is stated, as in
        # SvgRenderer.render.
        if table_sheet and border is None:
            border = "zone"
        border, _diagram = _resolve_sheet(border, diagram)
        sheet = _page(page_size)
        if table_sheet:
            return self._table_sheet(fs, sheet, border)

        body: list[str] = []
        # Cell order is z-order: border, then furniture, behind the
        # drawing. The table sheet has returned, so the stream-table
        # argument is now a plain bool.
        furniture, frame, fit = self._furniture(fs, sheet, bool(show_stream_table))
        body.extend(self._border(frame, border))
        body.extend(furniture)
        # Then equipment, runs and balloons, in the SVG renderer's order, so
        # a balloon's opaque body masks what it straddles. An edge may name
        # a later balloon cell, since mxCell source/target resolve by id
        # over the whole document. The tag pass (:class:`_Tags`) runs once
        # and also gives the line-number search the tag plates to avoid.
        joints = sheet_connections(diagram, connections)
        tags = _tag_pass(fs, self.registry, joints, jump_direction)
        balloons: list[str] = []
        for i, u in enumerate(fs.units):
            (balloons if u.kind == "instrument" else body).extend(
                self._vertex(u, i, fit, tags))
        body.extend(self._edges(fs, arrows, fit, tags, jump_direction, joints,
                                crossing_style))
        # Taps then balloons over the lines, as on the sheet.
        body.extend(self._taps(fs, fit))
        body.extend(balloons)
        # Balloon quadrant codes last, haloed, as on the sheet.
        for n, code in enumerate(tags.codes):
            body.extend(_quadrant_cell(f"q{n}", code, fit))

        return self._document(fs, sheet, frame, body)

    def _table_sheet(self, fs, sheet, border) -> str:
        """Return the stream table's own sheet as a draw.io document.

        Geometry comes from :func:`~pandid.render.svg.table_sheet_plan`, as
        on the SVG sheet, and every block is an editable ``shape=table``.
        The frame is the page on a paged export and the table's bounds
        otherwise.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose streams are tabulated.
        sheet : _Sheet or None
            Fixed page, or ``None``.
        border : str
            ``"none"`` or ``"zone"``.

        Returns
        -------
        str
            ``mxfile`` XML document.
        """
        from pandid.render.svg import table_sheet_plan

        plan = table_sheet_plan(fs, sheet)
        # Report the plan's findings, as the SVG backend does.
        self._findings.extend(plan.findings)
        body = list(self._border(plan.frame, border))
        for i, part, bx, by in plan.table.at(plan.left, plan.top):
            body += _stream_table(f"st{i}", part, bx, by)
        x, y, w, h = plan.strip
        # A table has no scale to state.
        body += self._title_strip("f0", plan.block, x, y, w, h,
                                  plan.name, plan.date, "")
        return self._document(fs, sheet, plan.frame, body)

    def _document(self, fs, sheet, frame, body: list[str]) -> str:
        """Return the draw.io file around a sheet's cells.

        Shared by the diagram and the table sheet so both state their page
        the same way.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet, for the name, page id and warnings.
        sheet : _Sheet or None
            Fixed page, or ``None``.
        frame : tuple[float, float, float, float]
            Frame the cells are placed against.
        body : list[str]
            Cell XML lines.

        Returns
        -------
        str
            ``mxfile`` XML document.
        """
        # Page size and page view are separate statements (function names
        # below refer to the drawio sources).
        #
        # Always state the size. With pageWidth/pageHeight absent,
        # Editor.readGraphState keeps mxGraph's locale default (A4, or US
        # Letter for en-us/en-ca/es-mx), and PDF export (js/export.js
        # renderPage) bounds the drawing by whole page tiles of that size.
        # PNG and SVG use the drawing's own extent. The stated size is the
        # sheet the SVG backend draws (:meth:`_page_box`).
        #
        # page= only sets the page view. A model with no paper says
        # page="0", which also makes export compute the origin from the
        # content (autoOrigin), so drawings with negative coordinates are
        # not clipped. A fixed page has every cell within [0, sheet].
        #
        # pageScale is stated as 1, since mxGraph's own default is 1.5;
        # math is off so export does not re-typeset before measuring.
        page_w, page_h = self._page_box(sheet, frame)
        paper = (f'page="{0 if sheet is None else 1}" pageScale="1" '
                 f'pageWidth="{_num(page_w)}" pageHeight="{_num(page_h)}"')
        # A stable page id, so re-exporting gives an identical file.
        page = hashlib.sha256(fs.name.encode("utf-8")).hexdigest()[:16]
        # Replace earlier export findings with this export's, as
        # SvgRenderer.render does.
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _EXPORT_CODES] + self._findings
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            # agent carries the generator and version; host is the
            # application name.
            f'<mxfile host="pandid" agent={_attr(generator())} type="device">',
            f'  <diagram id="pandid-{page}" name={_attr(fs.name)}>',
            '    <mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" {paper} '
            'math="0" shadow="0">',
            '      <root>',
            '        <mxCell id="0" />',
            '        <mxCell id="1" parent="0" />',
            *body,
            '      </root>',
            '    </mxGraphModel>',
            '  </diagram>',
            '</mxfile>',
        ]) + "\n"

    # ------------------------------------------------------ units

    @staticmethod
    def _id(index: int) -> str:
        """Return the cell id for the unit at ``index`` in ``fs.units``.

        Positional, because tags repeat (a trip square drawn in several
        places), and prefixed to avoid the root cells ``0`` and ``1``.

        Parameters
        ----------
        index : int
            Unit index.

        Returns
        -------
        str
            Cell id.
        """
        return f"u{index}"

    @staticmethod
    def _approximation(u, sym) -> "_Approximation | None":
        """Return the built-in stand-in for a symbol without a stencil.

        ``None`` for vendored symbols, compositions on a vendored body
        (:attr:`~pandid.render.symbols.Symbol.drawio_body_shape`, with parts
        as child cells), and kinds with no artwork, which get draw.io's
        default vertex as they get a generic box on the sheet.

        Parameters
        ----------
        u : Unit
            Unit.
        sym : Symbol
            Its symbol.

        Returns
        -------
        _Approximation or None
            Stand-in from :data:`_APPROXIMATIONS`.
        """
        if sym.drawio_shape or sym.drawio_body_shape:
            return None
        return _APPROXIMATIONS.get((u.kind, getattr(u, "variant", "default")))

    def _placement(self, u, sym) -> "tuple[list[str], bool, bool]":
        """Return the style keys placing a symbol, and its net flips.

        The flips are returned so :meth:`_constraint` states connection
        points in the frame draw.io then flips. A directional symbol is
        never flipped: its artwork states a direction (a cooler versus a
        heater), so like :func:`pandid.render.svg._upright_artwork` only its
        ports move, and they are stated as coordinates.

        Parameters
        ----------
        u : Unit
            Placed unit.
        sym : Symbol
            Its symbol.

        Returns
        -------
        tuple[list[str], bool, bool]
            Style keys, ``flip_h`` and ``flip_v``.
        """
        f = u.frame
        if u.kind in ("feed", "product"):
            # A flag is placed in _flag_shape, by direction, not flips.
            return [], False, False
        rot = int(getattr(f, "orientation", 0) or 0)
        keys = []
        if rot in _DIRECTION:
            # anchorPointDirection=0 (a vertex key) stops draw.io turning
            # the connection points with the shape; legacyAnchorPoints=1
            # pins the anchor algorithm that honours it, since every
            # fraction here is of the box as placed.
            keys += [f"direction={_DIRECTION[rot]}", "anchorPointDirection=0",
                     "legacyAnchorPoints=1"]
        if sym.directional:
            flip_h, flip_v = False, False
        else:
            flip_h, flip_v = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        # A stencil or stand-in that points the other way composes its flip
        # with the placement; folded in here so _constraint uses the same
        # net flip.
        approx = self._approximation(u, sym)
        if sym.drawio_flip_h or (approx is not None and approx.flip_h):
            flip_h = not flip_h
        if flip_h:
            keys.append("flipH=1")
        if flip_v:
            keys.append("flipV=1")
        return keys, flip_h, flip_v

    def _shape(self, u, sym, fit: "_Fit") -> list[str]:
        """Return the style keys naming what draw.io draws for a unit.

        Parameters
        ----------
        u : Unit
            Unit.
        sym : Symbol
            Its symbol.
        fit : _Fit
            Drawing fit, which scales the outline like every pen.

        Returns
        -------
        list[str]
            Style keys.
        """
        weight = (f"strokeWidth="
                  f"{fit.length(_svg._class_weight(sym).width):g}")
        if u.kind in ("feed", "product"):
            return self._flag_shape(u, fit)
        # A composition names its body's stencil; the parts get child
        # cells (:meth:`_overlay_cells`).
        stencil = sym.drawio_shape or sym.drawio_body_shape
        if stencil:
            # A vendored stencil. outlineConnect=0, as draw.io's P&ID
            # palette sets, keeps a stream on its routed nozzle rather than
            # the outline. Stencils use strokewidth="inherit", so state the
            # pen (:func:`pandid.render.svg._class_weight`).
            keys = [f"shape={stencil}", "outlineConnect=0",
                    f"strokeColor={_INK}", f"fillColor={sym.drawio_fill or _PAPER}",
                    weight]
            return keys
        # The stand-in, or the default vertex; flips are in _placement.
        approx = self._approximation(u, sym)
        shape = approx.shape if approx is not None else None
        keys = [] if shape is None else [f"shape={shape}"]
        keys += ["rounded=0", "whiteSpace=wrap"]
        if approx is None:
            # No artwork: the generic box, as on the sheet.
            return keys + [f"strokeColor={_INK}", f"fillColor={_NO_FILL}", weight]
        if approx.pieces:
            # The pieces draw the symbol (:meth:`_pieces`); the cell stays
            # an invisible vertex for connection points and dragging.
            return keys + ["strokeColor=none", f"fillColor={_NO_FILL}"]
        return keys + [*approx.keys, f"strokeColor={approx.stroke}",
                       f"fillColor={approx.fill}",
                       f"strokeWidth={fit.length(approx.weight):g}"]

    @staticmethod
    def _flag_shape(u, fit: "_Fit") -> list[str]:
        """Return the style keys for an off-page flag.

        draw.io's ``offPageConnector`` is the pennant
        :func:`~pandid.render.svg.boundary_flag` describes, pointing south,
        so it is turned with ``direction=north`` (tip east) or ``south``
        (tip west). ``size`` is a fraction of the shape's height, which is
        the cell's width after the turn. The anchor keys stop draw.io
        resolving connection points against rotated bounds, as in
        :meth:`_placement`.

        Parameters
        ----------
        u : Unit
            Feed or Product.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Style keys.
        """
        (x0, _, x1, _), depth, east = boundary_flag(u, u.frame)
        width = x1 - x0
        size = (depth / width) if width else 0.375
        return ["shape=offPageConnector", f"size={_fraction(min(1.0, size))}",
                f"direction={'north' if east else 'south'}",
                "anchorPointDirection=0", "legacyAnchorPoints=1",
                "rounded=0", "whiteSpace=wrap",
                f"strokeColor={_LINE_INK}", f"fillColor={_NO_FILL}",
                # A symbol outline on the ISO 10628-1 5.3.1 b) rung, scaled
                # with the drawing, as SvgRenderer._draw_boundary draws it.
                f"strokeWidth={fit.length(LineWeight.EQUIPMENT.width):g}"]

    def _label(self, u, fit: "_Fit", tags: "_Tags") -> "tuple[str, list[str], tuple]":
        """Return a unit's label text, placing keys and tag offset.

        An instrument's tag goes inside its balloon. Other tags go on the
        side the sheet settled on (:func:`_tag_pass`, the same search as
        :meth:`SvgRenderer._tag_item`). ``NC`` and fail-position letters
        follow the tag, since a draw.io cell has one label.

        Parameters
        ----------
        u : Unit
            Unit.
        fit : _Fit
            Drawing fit; lettering scales with it (:func:`_drawn_type`).
        tags : _Tags
            Tag placements from the tag pass.

        Returns
        -------
        tuple[str, list[str], tuple[float, float]]
            HTML label, style keys and the ``(dx, dy)`` offset.
        """
        from pandid.units import split_tag

        if u.kind == "instrument":
            letters, number = split_tag(getattr(u, "type", "") or u.tag,
                                        getattr(u, "number", "") or "")
            # A diamond carries the number alone, as on the sheet.
            if getattr(u, "variant", "default") in _DIAMOND_BALLOONS:
                parts = [number or letters.upper()]
            else:
                parts = [letters.upper(), number]
            parts = [part for part in parts if part]
            # Escape each part before joining, so only the <br> is markup
            # (:func:`_html_text`).
            text = "<br>".join(_html_text(part) for part in parts)
            # Capped to fit the balloon; one size for both lines, the
            # letters' 12 rather than the number's 11.
            return text, ["verticalLabelPosition=middle", "verticalAlign=middle",
                          "align=center",
                          _drawn_type(_TAG_TYPE, fit, lines=len(parts),
                                      box=self._cell_box(u))], (0.0, 0.0)

        lines = [u.tag] if u.tag else []
        if u.kind in ("feed", "product"):
            reference = getattr(u, "reference", "") or ""
            if reference:
                lines.append(reference)
            # Centred inside the flag, as the sheet writes it, capped to the
            # pennant: draw.io has one size and line height per label, so
            # tag and reference are set slightly smaller to fit.
            return "<br>".join(_html_text(line) for line in lines), _LABEL_SIDE["center"] + [
                _drawn_type(_TAG_TYPE, fit, lines=len(lines),
                            box=self._cell_box(u))], (0.0, 0.0)
        if closed_marking(u, self.registry) == "NC":
            lines.append("NC")
        letters = fail_marking(u)
        if letters:
            lines.append(letters)
        side, dx, dy = tags.at.get(id(u), (
            (u.frame.label_pos or "top") if u.frame is not None else "top", 0.0, 0.0))
        # No cap: a side label sits outside the cell.
        return "<br>".join(_html_text(line) for line in lines), _LABEL_SIDE.get(
            side, _LABEL_SIDE["top"]
        ) + [_drawn_type(_TAG_TYPE, fit)], (fit.length(dx), fit.length(dy))

    @staticmethod
    def _cell_box(u) -> "tuple[float, float, float, float]":
        """Return the rectangle draw.io is given for a unit.

        :func:`~pandid.portgeom.unit_box`, which a variable stencil fills.
        An off-page flag uses its pennant box, which is inset top and bottom
        (:func:`~pandid.render.svg.boundary_flag`), so connection fractions
        land on the pennant.

        Parameters
        ----------
        u : Unit
            Placed unit.

        Returns
        -------
        tuple[float, float, float, float]
            Box ``(x0, y0, x1, y1)``.
        """
        if u.kind in ("feed", "product"):
            return boundary_flag(u, u.frame).box
        return unit_box(u, u.frame)

    def _vertex(self, u, index: int, fit: "_Fit", tags: "_Tags") -> list[str]:
        """Return one unit as a draw.io vertex and its child cells.

        The ``<mxPoint as="offset">`` moves the label, not the cell, by the
        tag's step along its side. Child cells draw a second outline
        (:meth:`_inscribed`), stand-in pieces (:meth:`_pieces`) and
        supplementary parts (:meth:`_overlay_cells`).

        Parameters
        ----------
        u : Unit
            Placed unit.
        index : int
            Unit index, for the cell id.
        fit : _Fit
            Drawing fit.
        tags : _Tags
            Tag placements.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        sym = self.registry.for_unit(u)
        approx = self._approximation(u, sym)
        if approx is not None and approx.lost:
            # Report only stand-ins that lose something.
            self._findings.append(Issue(
                "warning", APPROXIMATED,
                f"{u.name} has no draw.io stencil and is exported as a stand-in, "
                f"which loses {approx.lost}"))
        self._report_reshape(u, sym, approx)
        x0, y0, x1, y1 = fit.box(self._cell_box(u))
        placement, _, _ = self._placement(u, sym)
        text, label_keys, (dx, dy) = self._label(u, fit, tags)
        style = ";".join(["html=1", *self._shape(u, sym, fit), *label_keys, *placement]) + ";"
        geometry = (f'          <mxGeometry x="{_num(x0)}" y="{_num(y0)}" '
                    f'width="{_num(x1 - x0)}" height="{_num(y1 - y0)}" as="geometry"')
        body = ([geometry + ">",
                 f'            <mxPoint x="{_num(dx)}" y="{_num(dy)}" as="offset" />',
                 '          </mxGeometry>']
                if (round(dx, 2) or round(dy, 2)) else [geometry + " />"])
        cid = self._id(index)
        return [
            f'        <mxCell id="{cid}" value={_attr(text)} '
            f'style={_attr(style)} vertex="1" parent="1">',
            *body,
            '        </mxCell>',
            *self._inscribed(cid, approx, x1 - x0, y1 - y0, fit),
            *self._pieces(u, approx, cid, x1 - x0, y1 - y0, fit),
            *self._overlay_cells(cid, sym, x1 - x0, y1 - y0, fit, u.frame, u.name),
        ]

    def _report_reshape(self, u, sym, approx: "_Approximation | None") -> None:
        """Report a stand-in draw.io will stretch where the sheet letterboxes.

        Vendored stencils are variable and match the sheet. A built-in
        stand-in for an unstretchable symbol fills its cell, while
        :func:`~pandid.portgeom.ink_box` centres the artwork on the sheet,
        so a unit sized to another aspect is reported. Silent when the
        aspect matches.

        Parameters
        ----------
        u : Unit
            Placed unit.
        sym : Symbol
            Its symbol.
        approx : _Approximation or None
            Its stand-in.
        """
        if approx is None or sym.stretchable:
            return
        x0, y0, x1, y1 = self._cell_box(u)
        w, h = x1 - x0, y1 - y0
        # Compare with the symbol's box as placed, turn included.
        _px, _py, bw, bh = symbol_to_box(0.0, 0.0, sym.width, sym.height, *_xform(u.frame))
        if not (w > 0 and h > 0 and bw > 0 and bh > 0):
            return
        # Same aspect, same drawing: a uniform scale is not a distortion.
        if abs(w / h - bw / bh) <= _ASPECT_SLACK:
            return
        self._findings.append(Issue(
            "warning", APPROXIMATED,
            f"{u.name} is drawn to a box of {w:g} x {h:g} and its symbol keeps its "
            f"shape, so the sheet centres the drawing and leaves the rest blank; "
            f"draw.io has no stand-in that can refuse to be stretched, so the "
            f"export fills the cell instead and the drawing comes out reproportioned"))

    @staticmethod
    def _pieces(u, approx: "_Approximation | None", cid: str,
                w: float, h: float, fit: "_Fit") -> list[str]:
        """Return a multi-piece stand-in as one child cell per built-in.

        See :class:`_Piece`. mxGraph does not turn a child's geometry with
        its parent, so each piece's rectangle is mapped through
        :func:`~pandid.portgeom.symbol_to_box` (as ports and SVG artwork
        are) and the parent's quarter turn is restated on it. Pieces are
        ``connectable=0`` and ``movable=0``, as in :meth:`_inscribed`.

        Parameters
        ----------
        u : Unit
            Placed unit.
        approx : _Approximation or None
            Its stand-in.
        cid : str
            Parent cell id.
        w, h : float
            Parent cell size.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Cell XML lines; empty without pieces.
        """
        if approx is None or not approx.pieces:
            return []
        turn = _turn_keys(u.frame)
        out: list[str] = []
        for i, piece in enumerate(approx.pieces):
            px, py, pw, ph = _placed_rect(u.frame, piece.x, piece.y, piece.w, piece.h)
            keys = [] if piece.shape is None else [f"shape={piece.shape}"]
            style = ";".join([
                "html=1", "rounded=0", *keys, *turn,
                f"strokeColor={approx.stroke}", f"fillColor={approx.fill}",
                f"strokeWidth={fit.length(approx.weight):g}",
                "connectable=0", "movable=0"]) + ";"
            out += [
                f'        <mxCell id="{cid}-s{i}" value="" style={_attr(style)} '
                f'vertex="1" parent="{cid}">',
                f'          <mxGeometry x="{_num(px * w)}" y="{_num(py * h)}" '
                f'width="{_num(pw * w)}" height="{_num(ph * h)}" as="geometry" />',
                '        </mxCell>',
            ]
        return out

    def _overlay_cells(self, cid: str, sym, w: float, h: float,
                       fit: "_Fit", frame: "Frame", name: str) -> list[str]:
        """Return one child cell per ISO supplementary part on a composed body.

        A composition names no stencil, since a stencil would draw only the
        body; each part becomes a child cell instead. An
        :class:`~pandid.render.symbols.Overlay` is in fractions of the body
        box, which is the parent cell, so the conversion is a multiply
        (``tests/test_drawio.py`` checks it against the SVG). Children move
        and resize with the parent; ``connectable=0`` and ``movable=0`` as
        in :meth:`_inscribed`. Parts use the detail pen (ISO 10628-1 5.3.1,
        :data:`_PART_STROKE`).

        Parameters
        ----------
        cid : str
            Parent cell id.
        sym : Symbol
            Composed symbol.
        w, h : float
            Parent cell size.
        fit : _Fit
            Drawing fit.
        frame : Frame
            Unit placement; the caller guarantees one exists.
        name : str
            Unit name, for findings.

        Returns
        -------
        list[str]
            Cell XML lines; empty without overlays.
        """
        if not sym.overlays:
            return []
        out: list[str] = []
        for i, overlay in enumerate(sym.overlays):
            part = self.registry.part(overlay.group, overlay.name)
            approx = _PART_APPROXIMATIONS.get((overlay.group, overlay.name))
            if part.drawio_shape:
                keys = [f"shape={part.drawio_shape}"]
            else:
                keys = [] if approx is None or approx.shape is None else [
                    f"shape={approx.shape}"]
                keys += [] if approx is None else list(approx.keys)
                if approx is not None and approx.lost:
                    # Report a part stand-in that loses something.
                    self._findings.append(Issue(
                        "warning", APPROXIMATED,
                        f"{name or cid}: the {overlay.name} part has no draw.io "
                        f"stencil and is exported as a stand-in, which loses "
                        f"{approx.lost}"))
            # A chiral part's other hand, flipped within its own box.
            if overlay.mirror:
                keys.append("flipH=1")
            # Children do not inherit placement (:func:`_placed_rect`).
            ox, oy, ow, oh = _placed_rect(frame, overlay.x, overlay.y, overlay.w, overlay.h)
            style = ";".join([
                "html=1", "rounded=0", *keys, *_turn_keys(frame),
                f"strokeColor={_INK}", f"fillColor={_NO_FILL}",
                f"strokeWidth={fit.length(_PART_STROKE):g}",
                "connectable=0", "movable=0"]) + ";"
            out += [
                f'        <mxCell id="{cid}-p{i}" value="" style={_attr(style)} '
                f'vertex="1" parent="{cid}">',
                f'          <mxGeometry x="{_num(ox * w)}" y="{_num(oy * h)}" '
                f'width="{_num(ow * w)}" height="{_num(oh * h)}" as="geometry" />',
                '        </mxCell>',
            ]
        return out

    @staticmethod
    def _inscribed(cid: str, approx: "_Approximation | None",
                   w: float, h: float, fit: "_Fit") -> list[str]:
        """Return a symbol's second outline as a child of its first.

        Used for the safety-instrumented-system balloon, a square with an
        inscribed diamond (ANSI/ISA-5.1-2009 Table 5.1.1 column B); a bare
        rhombus is Table 5.1.2's interlock. A child cell, not an inline
        compressed stencil, keeps the file plain and diffable.

        The child moves and resizes with the parent
        (``Graph.isRecursiveVertexResize``; a ``childLayout`` would disable
        that). ``connectable=0`` keeps streams on the parent's points and
        ``movable=0`` stops the child being dragged out. Its fill is none,
        as the parent is already opaque.

        Parameters
        ----------
        cid : str
            Parent cell id.
        approx : _Approximation or None
            Stand-in.
        w, h : float
            Parent cell size.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Cell XML lines; empty without an inscribed shape.
        """
        if approx is None or approx.inscribed is None:
            return []
        style = ";".join([f"shape={approx.inscribed}", "rounded=0", "html=1",
                          f"strokeColor={approx.stroke}", f"fillColor={_NO_FILL}",
                          f"strokeWidth={fit.length(approx.weight):g}",
                          "connectable=0", "movable=0"]) + ";"
        return [
            f'        <mxCell id="{cid}-in" value="" style={_attr(style)} '
            f'vertex="1" parent="{cid}">',
            f'          <mxGeometry x="0" y="0" width="{_num(w)}" '
            f'height="{_num(h)}" as="geometry" />',
            '        </mxCell>',
        ]

    # ---------------------------------------------------- streams

    def _fraction(self, u, sym, point) -> "tuple[float, float]":
        """Return a point on a unit as a draw.io connection fraction.

        Used for ports and for tap points, which are face midpoints, not
        ports. The fraction is reflected through the cell's flips.

        Parameters
        ----------
        u : Unit
            Placed unit.
        sym : Symbol
            Its symbol.
        point : tuple[float, float]
            Absolute point.

        Returns
        -------
        tuple[float, float]
            Fractions of the cell box.
        """
        px, py = point
        x0, y0, x1, y1 = self._cell_box(u)
        w, h = x1 - x0, y1 - y0
        fx = (px - x0) / w if w else 0.5
        fy = (py - y0) / h if h else 0.5
        _, flip_h, flip_v = self._placement(u, sym)
        return (1.0 - fx if flip_h else fx, 1.0 - fy if flip_v else fy)

    def _constraint(self, u, sym, port_name: str) -> "tuple[float, float]":
        """Return where a stream meets a port, as a connection fraction.

        draw.io applies the cell's flips to the fraction, so the drawn
        fraction is reflected back through them (:meth:`_fraction`).
        ``anchorPointDirection=0`` on the vertex (:meth:`_placement`) stops
        draw.io rotating the point again, since
        :func:`~pandid.portgeom.port_point` is already turned.
        ``exitPerimeter=0``/``entryPerimeter=0`` on the edge stop it
        projecting an inboard nozzle onto the bounding box.

        Parameters
        ----------
        u : Unit
            Placed unit.
        sym : Symbol
            Its symbol.
        port_name : str
            Port name.

        Returns
        -------
        tuple[float, float]
            Fractions of the cell box.
        """
        if u.kind == "tee":
            # A tee is a junction: no built-in draws its mark, so all three
            # legs run to the centre and the cell draws nothing.
            x0, y0, x1, y1 = self._cell_box(u)
            return self._fraction(u, sym, ((x0 + x1) / 2, (y0 + y1) / 2))
        return self._fraction(u, sym, port_point(u, u.frame, port_name))

    @staticmethod
    def _ends(exit_at, entry_at) -> list[str]:
        """Return the style keys pinning an edge's ends to cell points.

        Parameters
        ----------
        exit_at, entry_at : tuple[float, float] or None
            Fractions on the source and target cells; ``None`` for a
            floating end stated in the geometry (:meth:`_taps`).

        Returns
        -------
        list[str]
            Style keys.
        """
        keys = []
        for prefix, at in (("exit", exit_at), ("entry", entry_at)):
            if at is None:
                continue
            keys += [f"{prefix}X={_fraction(at[0])}", f"{prefix}Y={_fraction(at[1])}",
                     f"{prefix}Dx=0", f"{prefix}Dy=0", f"{prefix}Perimeter=0"]
        return keys

    def _edges(self, fs, arrows: bool, fit: "_Fit", tags: "_Tags",
               direction: str = "vertical",
               joints: "str | None" = None,
               crossing_style: str = "gap") -> list[str]:
        """Return every stream as a draw.io edge between its two ports.

        Cells are built in ``fs.streams`` order, so a run's number goes on
        its first segment as on the sheet, and written in hop order, since
        draw.io breaks crossing ties by z-order (:func:`_hops`).

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being exported.
        arrows : bool
            Whether process lines get arrowheads.
        fit : _Fit
            Drawing fit.
        tags : _Tags
            Tag placements, whose plates the numbers avoid.
        direction : str, default="vertical"
            The sheet's ``jump_direction``.
        joints : str, optional
            Sheet joint default (:func:`~pandid.render.svg.sheet_connections`).
        crossing_style : str, default="gap"
            Crossing mark (:data:`_JUMP_STYLES`), or ``"plain"`` for none.

        Returns
        -------
        list[str]
            Cell XML lines: edges, then number enclosures.
        """
        index = {id(u): i for i, u in enumerate(fs.units)}
        # Place numbers by the sheet's own search, seeded with the tag
        # plates (:func:`_number_geometry`, :class:`_Tags`).
        placed = stream_numbers(fs, list(tags.plates), joints, direction)
        numbers = {number.name: number for number in placed}
        shape = enclosure_shape(fs)
        # Same findings as the sheet, from the same placement.
        self._findings += label_findings(fs, shape, placed, direction)
        polylines = {n: stream_polyline(s) for n, s in enumerate(fs.streams)}
        order, hops, lost = _hops(polylines, direction, crossing_style)

        def _run(key):
            """Return a stream's name for a message."""
            return fs.streams[key].name or f"stream {key + 1}"

        for hop_key, cross_key, x, y in sorted(lost):
            self._findings.append(Issue(
                "warning", HOP_DROPPED,
                f"{_run(hop_key)} hops {_run(cross_key)} at ({_num(x)}, {_num(y)}) "
                f"on the sheet, and the two cross each other more than once, which "
                f"draw.io cannot draw either way round; the crossing is exported "
                f"flat"))
        labelled: set = set()
        cells: dict = {}
        boxes: list[str] = []
        for n, s in enumerate(fs.streams):
            src_u, dst_u = s.source.owner, s.dest.owner
            points = polylines[n]
            ex, ey = self._constraint(src_u, self.registry.for_unit(src_u), s.source.name)
            tx, ty = self._constraint(dst_u, self.registry.for_unit(dst_u), s.dest.name)
            signal = s.kind in _SIGNAL_KINDS

            keys = [
                "html=1",
                # edgeStyle=none draws the routed polyline rather than
                # letting draw.io re-route it. A dragged block then leaves
                # a sloping end leg for the author to fix.
                "edgeStyle=none", "rounded=0", "orthogonalLoop=1", "jettySize=auto",
                *self._ends((ex, ey), (tx, ty)),
                f"strokeColor={s.color or _LINE_INK}",
                # ISO 10628-1 5.3.1 a) for material, c) for signals.
                f"strokeWidth={fit.length(_stream_rung(signal).width):g}",
            ]
            # The crossing mark on hopping runs, sized net of the pen
            # (:func:`_jump_size`).
            if n in hops:
                weight = fit.length(_stream_rung(signal).width)
                # One jumpSize for arc and gap, as HOP_R is on the sheet.
                keys += [f"jumpStyle={_JUMP_STYLES[crossing_style]}",
                         f"jumpSize={_jump_size(fit.length(HOP_R), weight)}"]
            keys += _dash(s.dasharray or _SIGNAL_DASH.get(s.kind, ""))
            if arrows and wears_arrowhead(s, self.registry):
                # The head is drawing size, so it scales with the fit.
                keys += ["endArrow=block", "endFill=1",
                         f"endSize={fit.length(ARROWHEAD):g}"]
            else:
                keys.append("endArrow=none")
            keys.append("startArrow=none")

            # A number names a run, which keeps its name through valves and
            # fittings, so only its first segment is labelled. Signal lines
            # are unlabelled, as on the sheet.
            label = ""
            number = None
            # An enclosed number is its own vertex, since an edge label can
            # only have a rectangular border. It sits at absolute
            # coordinates, so it does not follow the run when edited; a
            # child of the edge would follow but would be painted before
            # later runs, which could then cross the number.
            boxed = False
            if not signal and s.name not in labelled:
                labelled.add(s.name)
                number = numbers.get(s.name)
                boxed = number is not None and shape != "none"
                if not boxed:
                    label = s.name
                    if number is not None:
                        keys += ([_NUMBER_PLATE] if number.words is not None
                                 else [])
                        keys += _NUMBER_KEYS + [_drawn_type(NUMBER_TYPE, fit)]
                        if number.vertical:
                            keys.append("horizontal=0")

            style = ";".join(keys) + ";"
            # Ends are constraints; the array holds only the turns, and a
            # straight run has none.
            waypoints = points[1:-1]
            along, offset = _number_geometry(None if boxed else number, points, fit)
            body = [
                *(['            <Array as="points">',
                   *(f'              <mxPoint x="{_num(fx)}" y="{_num(fy)}" />'
                     for fx, fy in (fit.at(px, py) for px, py in waypoints)),
                   '            </Array>'] if waypoints else []),
                *([f'            <mxPoint x="{_num(offset[0])}" y="{_num(offset[1])}" '
                   'as="offset" />'] if offset is not None else []),
            ]
            # The geometry's x places the label along the run and its
            # offset across it, beside the waypoints, as draw.io itself
            # writes a dragged edge label (mxEdgeHandler.moveLabel).
            head = ('          <mxGeometry relative="1" as="geometry"'
                    + ('' if along is None else f' x="{_fraction(along)}"'))
            if body:
                geometry = [head + ">", *body, '          </mxGeometry>']
            else:
                geometry = [head + " />"]
            cells[n] = [
                f'        <mxCell id="s{n}" value={_attr(_html_text(label))} '
                f'style={_attr(style)} '
                f'edge="1" parent="1" source="{self._id(index[id(src_u)])}" '
                f'target="{self._id(index[id(dst_u)])}">',
                *geometry,
                '        </mxCell>',
            ]
            # Hatches, flanges and leaders are written after their edge.
            if s.kind == "pneumatic":
                cells[n] += _hatches(f"s{n}", points, s.color or _LINE_INK, fit)
            cells[n] += _flanges(f"s{n}", s, points, resolve_connections(s, joints),
                                 s.color or _LINE_INK, fit)
            if number is not None and number.leader is not None:
                cells[n] += _leader(f"s{n}", number, s.color or _LINE_INK, fit)
            # Enclosures are written after every edge; see the return.
            if boxed:
                boxes += _enclosure(f"s{n}", number, shape,
                                    s.color or _LINE_INK, fit)
        out: list[str] = []
        for n in order:
            out += cells[n]
        # Enclosures after every run, so no later run is painted across a
        # number, as SvgRenderer._draw_streams draws numbers last. They
        # stay before taps and balloons, which come after the runs on the
        # sheet too.
        return out + boxes

    def _taps(self, fs, fit: "_Fit") -> list[str]:
        """Return every instrument connection as a draw.io edge.

        Taps are not streams, but ISO 15519-2 5.1.1 (Figure 6) requires a
        PCI symbol to be connected to the process and the control system.
        Endpoints come from :func:`~pandid.render.svg.tap_lines` and line
        type from :func:`~pandid.render.svg.impulse_tap`, as on the sheet.

        The balloon end is pinned to the balloon's centre, so the line
        follows the balloon; balloons are written after, so their bodies
        mask it. The other end is pinned to a host unit's face, or is a
        floating point on a host stream, since draw.io would choose its own
        point on an edge. A tap is one straight line, sloping if the
        balloon is not level or square with the host, as on the sheet.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being exported.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        index = {id(u): i for i, u in enumerate(fs.units)}
        out: list[str] = []
        for n, (inst, tap, centre) in enumerate(tap_lines(fs)):
            target = index.get(id(inst))
            if target is None:  # not on the sheet; nothing to hang a line off
                continue
            entry = self._fraction(inst, self.registry.for_unit(inst), centre)
            host = getattr(inst, "host", None)
            source = index.get(id(host)) if getattr(host, "frame", None) is not None else None
            exit_at = (self._fraction(host, self.registry.for_unit(host), tap)
                       if source is not None else None)
            keys = [
                "html=1", "edgeStyle=none", "rounded=0",
                *self._ends(exit_at, (entry[0], entry[1])),
                f"strokeColor={_LINE_INK}",
                # ISO 15519-2 Annex A.1.02: the 0.25 mm DETAIL rung.
                f"strokeWidth={fit.length(LineWeight.DETAIL.width):g}",
            ]
            if not impulse_tap(inst):
                keys += _dash(_TAP_DASH)
            # No arrowheads (ISO 15519-2 5.1.1) and no jumps
            # (:data:`_NO_HOP`).
            keys += ["endArrow=none", "startArrow=none", _NO_HOP.rstrip(";")]
            style = ";".join(keys) + ";"
            terminals = f' source="{self._id(source)}"' if source is not None else ""
            geometry = ['          <mxGeometry relative="1" as="geometry">',
                        f'            <mxPoint x="{_num(fit.at(*tap)[0])}" '
                        f'y="{_num(fit.at(*tap)[1])}" as="sourcePoint" />',
                        '          </mxGeometry>'] if source is None else [
                '          <mxGeometry relative="1" as="geometry" />']
            out += [
                f'        <mxCell id="t{n}" value="" style={_attr(style)} '
                f'edge="1" parent="1"{terminals} target="{self._id(target)}">',
                *geometry,
                '        </mxCell>',
            ]
        return out

    # -------------------------------------------------- furniture

    @staticmethod
    def _drawing_box(fs) -> "tuple[float, float, float, float]":
        """Return the drawing's bounding box, which furniture docks around.

        Unit boxes and route waypoints, as in :meth:`SvgRenderer.render`; an
        empty flowsheet gives zeros.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet.

        Returns
        -------
        tuple[float, float, float, float]
            ``(x0, y0, x1, y1)``.
        """
        if not fs.units:
            return (0.0, 0.0, 0.0, 0.0)
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for u in fs.units:
            bx0, by0, bx1, by1 = unit_box(u, u.frame)
            x0, y0 = min(x0, bx0), min(y0, by0)
            x1, y1 = max(x1, bx1), max(y1, by1)
        for s in fs.streams:
            if s.route and s.route.waypoints:
                for px, py in s.route.waypoints:
                    x0, y0 = min(x0, px), min(y0, py)
                    x1, y1 = max(x1, px), max(y1, py)
        return (x0, y0, x1, y1)

    @staticmethod
    def _page_box(sheet, frame) -> "tuple[float, float]":
        """Return the page the file states, in drawing units.

        Drawing units, since pageWidth and pageHeight are measured in cell
        coordinates (A3 is 1587 by 1123). A fixed page is the sheet.
        Without one, it is the furniture frame out through the border band
        (:func:`~pandid.render.furniture.sheet_rect`) and
        :data:`~pandid.render.furniture.OUTER_MARGIN`, so a zone border stays
        on the page; ``tests/test_drawio.py`` checks every cell lies inside.
        Only the extent is used: with ``page="0"`` draw.io positions the page
        from the drawing's top-left.

        Parameters
        ----------
        sheet : _Sheet or None
            Fixed page, or ``None``.
        frame : tuple[float, float, float, float]
            Furniture frame.

        Returns
        -------
        tuple[float, float]
            ``(width, height)``.
        """
        if sheet is not None:
            return (sheet.width, sheet.height)
        _ox, _oy, ow, oh = F.sheet_rect(*frame)
        return (ow + 2 * F.OUTER_MARGIN, oh + 2 * F.OUTER_MARGIN)

    def _furniture(self, fs, sheet: "_Sheet | None" = None, show_stream_table: bool = False):
        """Return the docked furniture cells, the frame and the drawing fit.

        Placement is :func:`pandid.render.furniture.dock`, shared with the
        SVG sheet. Without a page the frame grows around the drawing's own
        bounds; with one, the drawing is fitted into what the furniture
        leaves. Boxes with columnar rows export as editable ``shape=table``
        grids, ruled only where the sheet rules them: annotations have no
        inner rules (:data:`_ANNOTATION_KEYS`), table boxes rule every
        cell. Boxes of plain lines stay text boxes.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose title block and annotations are drawn.
        sheet : _Sheet, optional
            Fixed page.
        show_stream_table : bool, default=False
            Whether to dock the stream table.

        Returns
        -------
        tuple[list[str], tuple, _Fit]
            Cell XML lines, the frame ``(x, y, w, h)`` and the fit.

        Raises
        ------
        ValueError
            If the page is too small for the furniture.
        """
        from pandid.document import TableBox

        items: list = []
        if fs.title_block is not None:
            items.append((fs.title_block, "bottom-right",
                          *_strip_size(fs.title_block)))
        for a in getattr(fs, "annotations", []) or []:
            w, h = (F.measure_table(a) if isinstance(a, TableBox)
                    else F.measure_annotation(a))
            items.append((a, a.align, w, h))
        # The stream table docks last at bottom-left, against the foot of
        # the sheet, measured as on the SVG sheet.
        table = F.stream_table_layout(fs) if show_stream_table else None
        if table is not None:
            items.append((table, "bottom-left", table.w, table.h))

        inner = self._drawing_box(fs)
        if sheet is None:
            placed, frame, free = F.dock(items, inner)
        else:
            # Rebind so the closure's type is _Sheet, not _Sheet | None.
            page = sheet
            placed, frame, free = F.dock(
                items, inner, sheet=page,
                too_small=lambda need_w, need_h, culprit: _too_small(
                    page, need_w, need_h, _furniture_name(culprit) if culprit else ""))
        # A fixed page fits the drawing into the free region; otherwise the
        # drawing keeps its coordinates.
        fit = _Fit.identity() if free is None else _Fit(
            *_fitted(inner, free))
        # Fallbacks for the strip's name, date and scale, passed unchosen so
        # the strip decides after treating blank fields as empty.
        name = fs.name
        date = datetime.now().strftime("%Y-%m-%d")
        scale = "" if free is None else _scale_text(fit.scale)
        out: list[str] = []
        for n, (obj, x, y, w, h) in enumerate(placed):
            out += self._furniture_cell(f"f{n}", obj, x, y, w, h, name, date, scale)
        return out, frame, fit

    @staticmethod
    def _border(frame, border: str) -> list[str]:
        """Return the zone-ruled drawing frame as cells.

        Only for ``border="zone"``; an unruled sheet draws no rectangle, and
        the page draw.io rules is its edge. Geometry comes from
        :func:`pandid.render.furniture.zone_layout`. The grid is a snapshot:
        zone references (ISO 15519-1 Clause 9) stop being true once a reader
        moves equipment in the editable model.

        Parameters
        ----------
        frame : tuple[float, float, float, float]
            Inner frame.
        border : str
            ``"none"`` or ``"zone"``.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        if border != "zone":
            return []
        ix, iy, iw, ih = frame
        z = F.zone_layout(ix, iy, iw, ih)
        ox, oy, ow, oh = z.outer
        rect = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;movable=1;"
                f"strokeColor={_LINE_INK};")
        out = _rect("z-sheet", ox, oy, ow, oh,
                    rect + f"strokeWidth={F.SHEET_RULE:g};")
        out += _rect("z-frame", ix, iy, iw, ih,
                     rect + f"strokeWidth={F.FRAME_RULE:g};")
        for n, part in enumerate(z.parts):
            if part[0] == "rule":
                _, x1, y1, x2, y2 = part
                out += _segment(f"z{n}", x1, y1, x2, y2, _LINE_INK, F.ZONE_TICK)
            else:
                _, lx, ly, text = part
                out += _label(f"z{n}", lx, ly, text, F.ZONE_TYPE)
        return out

    def _furniture_cell(self, cid: str, obj, x, y, w, h,
                        name: str = "", date: str = "",
                        scale: str = "") -> list[str]:
        """Return the cells drawing one docked piece of furniture.

        Parameters
        ----------
        cid : str
            Cell id prefix.
        obj : TitleBlock, StreamTable, TableBox or Annotation
            The furniture.
        x, y, w, h : float
            Docked box.
        name, date, scale : str, default=""
            Title-strip fallbacks.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        from pandid.document import TableBox, TitleBlock

        if isinstance(obj, TitleBlock):
            return self._title_strip(cid, obj, x, y, w, h, name, date, scale)
        if isinstance(obj, F.StreamTable):
            return _stream_table(cid, obj, x, y)
        title = getattr(obj, "title", "") or ""
        if isinstance(obj, TableBox):
            size, _ncol, col_w, _row_h = F._table_layout(obj)
            # The table container draws the border and every rule
            # (TableShape.paintTableForeground), so state the cell-rule
            # weight there.
            return _table(cid, title, [str(c) for c in obj.headers],
                          [[str(c) for c in row] for row in obj.rows],
                          x, y, w, h, col_w, (size + 10) if title else 0.0,
                          font=size, keys=f"strokeWidth={F._CELL_RULE:g};",
                          col_keys=_ALIGN_KEYS(obj.col_align, len(col_w)))
        rows = list(getattr(obj, "rows", []) or [])
        if any(isinstance(r, (tuple, list)) for r in rows):
            # Columnar (equipment list, legend, notes): columns measured
            # from their text (:func:`columns`).
            size, _row_h, title_h, _col_w = F._ann_layout(obj)
            grid = [[str(c) for c in r] if isinstance(r, (tuple, list)) else [str(r)]
                    for r in rows]
            ncol = max(len(r) for r in grid)
            # Left-aligned, first column bold, as draw_annotation sets it;
            # columns are measured in the same weights.
            heavy = [True] + [False] * (ncol - 1)
            return _table(cid, title, [], grid, x, y, w, h,
                          columns(grid, [size] * ncol, w, bold=heavy), title_h,
                          font=size,
                          # The border is this box's only rule.
                          keys=(_ANNOTATION_KEYS + f"fontSize={size + 1:g};"
                                + f"strokeWidth={F._BOX_RULE:g};"),
                          col_keys=[f"align=left;spacingLeft=4;{'fontStyle=1;' if b else ''}"
                                    for b in heavy])
        # Free-form lines, or any other docked object with a title and
        # rows.
        size = getattr(obj, "font_size", 11.0)
        _s, _row_h, title_h, _col_w = F._ann_layout(obj) if rows or title else (
            size, 0.0, 0.0, [])
        return _text_box(cid, title, [str(r) for r in rows], x, y, w, h, size,
                         title_h)

    def _title_strip(self, cid: str, block, x, y, w, h, name: str, date: str,
                     scale: str) -> list[str]:
        """Return the title strip as cells, ruled where the sheet rules it.

        The parts come from
        :func:`~pandid.render.furniture.title_strip_layout`, as
        :func:`~pandid.render.furniture.draw_title_strip` uses, so this
        method does no strip arithmetic. Only the revision history is a
        real table (:func:`_rev_table`); the other bands have rows of
        unequal depth, which a draw.io table cannot hold, so they are a
        rectangle, rules and text cells, each with its own id. Overflowing
        fields are reported (:meth:`_report`).

        Parameters
        ----------
        cid : str
            Cell id prefix.
        block : TitleBlock
            Title block.
        x, y, w, h : float
            Docked strip box.
        name, date, scale : str
            Fallbacks for the name, date and scale cells.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        strip = F.title_strip_layout(block, name, date, x + w, y + h, scale,
                                     report=self._report)
        bx, by, bw, bh = strip.box
        # Flush to the frame's bottom-right, rules coincident, as on the
        # sheet.
        out = _rect(cid, bx, by, bw, bh,
                    "rounded=0;html=1;movable=1;"
                    f"strokeColor={_LINE_INK};fillColor={_NO_FILL};"
                    f"strokeWidth={F._STRIP_RULE:g};")
        for n, part in enumerate(strip.rules):
            out += _strip_rule(f"{cid}-v{n}", part)
        out += _rev_table(f"{cid}-rev", strip.rev)
        for n, part in enumerate(strip.parts):
            out += (_strip_rule(f"{cid}-p{n}", part) if part[0] == "rule"
                    else _strip_label(f"{cid}-p{n}", part))
        return out


# Opaque plate behind a line number, written only where the sheet lays one
# (:attr:`~pandid.render.svg.StreamNumber.words`). mxGraph paints a label
# background on edges as on vertices.
_NUMBER_PLATE = "labelBackgroundColor=#ffffff"

# Line-number label keys. verticalLabelPosition is omitted because it has
# no effect on edge labels (mxCellRenderer.getLabelBounds). horizontal=0 is
# added per number on a vertical run (DrawioRenderer._edges), turning it to
# read bottom to top as the sheet does (ISO 15519-1 7.2.5, 5.1.5); it does
# rotate edge labels and their background.
_NUMBER_KEYS = ["verticalAlign=middle", "align=center"]


def _number_geometry(number, points, fit: "_Fit"):
    """Return a line number's position on its edge as draw.io states it.

    For a relative edge geometry, ``geometry.x`` runs -1 to +1 over the
    routed polyline's arc length (``mxGraphView.getPoint``), and
    ``geometry.offset`` displaces the label in drawing units. The offset
    is used rather than ``geometry.y``, whose sign depends on the
    direction the segment was routed in. The along-run figure projects the
    number onto its own segment, clamped to it, so the number stays on that
    segment when the drawing is edited.

    Parameters
    ----------
    number : StreamNumber or None
        Placed number.
    points : list[tuple[float, float]]
        Stream polyline.
    fit : _Fit
        Sheet-to-file transform.

    Returns
    -------
    tuple
        ``(x, (dx, dy))`` for the geometry and offset, ``(None, offset)``
        if the segment is not on this edge, or ``(None, None)`` for no
        number.
    """
    if number is None:
        return None, None
    (ax, ay), (bx, by) = number.seg
    dx, dy = bx - ax, by - ay
    span = (dx * dx + dy * dy) ** 0.5
    if span <= 0:
        return None, None
    # Foot of the perpendicular onto the segment, clamped to it.
    t = min(1.0, max(0.0, ((number.x - ax) * dx + (number.y - ay) * dy) / (span * span)))
    foot = (ax + t * dx, ay + t * dy)

    # Position along the whole polyline, which draw.io measures against.
    # Both come from stream_polyline, so endpoints match exactly.
    lengths = [((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
               for p, q in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0:
        return None, None
    before = 0.0
    for i, (p, q) in enumerate(zip(points, points[1:])):
        if p == (ax, ay) and q == (bx, by):
            break
        before += lengths[i]
    else:  # the number names a segment this edge does not carry: leave it centred
        return None, (fit.length(number.x - foot[0]), fit.length(number.y - foot[1]))
    reach = before + t * span
    return (max(-1.0, min(1.0, 2.0 * reach / total - 1.0)),
            (fit.length(number.x - foot[0]), fit.length(number.y - foot[1])))


def _leader(edge_id: str, number, ink: str, fit: "_Fit") -> list[str]:
    """Return the leader joining a displaced line number to its run.

    ISO 15519-1 6.4 requires a terminator; a leader ending on a
    connection gets an arrowhead (``endArrow=block;endFill=1``, as
    :func:`~pandid.render.svg._arrowhead` draws). The leader is a free
    edge between two ``mxPoint`` terminals, so unlike the number it does
    not follow the run when the drawing is edited, the same trade as
    :meth:`DrawioRenderer._taps`. ``noJump=1`` because a leader is not a
    connection (:data:`_NO_HOP`). Drawn at the DETAIL weight, as ISO 128-22
    makes a leader a narrow line.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    number : StreamNumber
        Placed number with a leader.
    ink : str
        Label colour, as :data:`_LINE_INK` spells it.
    fit : _Fit
        Sheet-to-file transform.

    Returns
    -------
    list[str]
        XML lines for the leader cell.
    """
    (ax, ay), (bx, by) = number.leader
    style = (f"edgeStyle=none;rounded=0;html=1;startArrow=none;endArrow=block;"
             f"endFill=1;endSize={fit.length(_LEADER_HEAD):g};"
             f"strokeColor={ink};"
             f"strokeWidth={fit.length(LineWeight.DETAIL.width):g};movable=1;{_NO_HOP}")
    x0, y0 = fit.at(ax, ay)
    x1, y1 = fit.at(bx, by)
    return [
        f'        <mxCell id="{edge_id}-lead" value="" style={_attr(style)} '
        f'edge="1" parent="1">',
        '          <mxGeometry relative="1" as="geometry">',
        f'            <mxPoint x="{_num(x0)}" y="{_num(y0)}" as="sourcePoint" />',
        f'            <mxPoint x="{_num(x1)}" y="{_num(y1)}" as="targetPoint" />',
        '          </mxGeometry>',
        '        </mxCell>',
    ]


# draw.io built-in for each stream-label enclosure, drawn to fill
# StreamNumber.box exactly as the SVG does; none is an approximation.
_ENCLOSURE_SHAPE = {"diamond": "rhombus", "circle": "ellipse", "box": "rounded=0"}


def _enclosure(edge_id: str, number, shape: str, ink: str, fit: "_Fit") -> list[str]:
    """Return the enclosure round a stream label as its own cell.

    The cell carries the number (see :meth:`DrawioRenderer._edges`). It
    is unfilled, so it never hides a crossing run; a
    ``labelBackgroundColor`` plate is written only where the SVG draws one
    (:func:`~pandid.render.svg._enclosure_svg`). A vertical run sets the
    text bottom to top with ``horizontal=0``.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    number : StreamNumber
        Placed number.
    shape : str
        ``"diamond"``, ``"circle"`` or ``"box"``.
    ink : str
        Label colour.
    fit : _Fit
        Sheet-to-file transform.

    Returns
    -------
    list[str]
        XML lines for the enclosure cell.
    """
    x0, y0, x1, y1 = number.box
    x, y = fit.at(x0, y0)
    style = (f"{_ENCLOSURE_SHAPE[shape]};html=1;fillColor=none;"
             + (f"labelBackgroundColor={_BALLOON_FILL};"
                if number.words is not None else "")
             + f"strokeColor={ink};fontColor={ink};"
             f"strokeWidth={fit.length(_ENCLOSURE_STROKE):g};"
             f"{_drawn_type(NUMBER_TYPE, fit)};verticalAlign=middle;align=center;"
             + ("horizontal=0;" if number.vertical else ""))
    return [
        f'        <mxCell id="{edge_id}-box" value={_attr(_html_text(number.name))} '
        f'style={_attr(style)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y)}" '
        f'width="{_num(fit.length(x1 - x0))}" height="{_num(fit.length(y1 - y0))}" '
        f'as="geometry" />',
        '        </mxCell>',
    ]


# Style keys for a label on each side of a cell. The position key moves
# the label box outside the cell; the align key pulls the text back
# against it.
_LABEL_SIDE = {
    "top": ["verticalLabelPosition=top", "verticalAlign=bottom", "align=center"],
    "bottom": ["verticalLabelPosition=bottom", "verticalAlign=top", "align=center"],
    "left": ["labelPosition=left", "align=right",
             "verticalLabelPosition=middle", "verticalAlign=middle"],
    "right": ["labelPosition=right", "align=left",
              "verticalLabelPosition=middle", "verticalAlign=middle"],
    "center": ["verticalLabelPosition=middle", "verticalAlign=middle", "align=center"],
}


# ----------------------------------------------------------------
# The pneumatic cross-hatch
# ----------------------------------------------------------------

# Hatch stroke angle on a horizontal run, in draw.io's clockwise degrees:
# atan2(-10, 6) for the SVG's 6-along, 10-across stroke
# (:data:`~pandid.render.svg.HATCH_ARM`). Add 90 on a vertical run.
_HATCH_ANGLE = -59.04
# Hatch stroke length (box width for shape=line): sqrt(6^2 + 10^2).
_HATCH_LEN = 11.66


def _hatches(edge_id: str, points, ink: str, fit: "_Fit") -> list[str]:
    """Return the double cross-hatch marking a pneumatic line.

    ISO 15519-2 6.2 keeps signal-medium marks for distinguishing a
    minority medium (Annex A). draw.io cannot draw them natively: it has no
    signal-line edge template, a stencil on an edge replaces the line, and
    markers exist only at the ends. Each mark is therefore a child vertex
    on the edge, placed by arc length (``mxGeometry.x`` in -1..1) with its
    top-left on the point, so it moves when the line is re-routed. Its angle
    is fixed at export, and the double hatch is two ``line`` cells.
    Positions come from :func:`~pandid.render.svg.pneumatic_marks`.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    points : list[tuple[float, float]]
        Stream polyline.
    ink : str
        Line colour.
    fit : _Fit
        Sheet-to-file transform.

    Returns
    -------
    list[str]
        XML lines for the hatch cells.
    """
    from pandid.render.svg import pneumatic_marks

    total = sum(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                for (ax, ay), (bx, by) in zip(points, points[1:]))
    if total <= 0:
        return []

    length = fit.length(_HATCH_LEN)
    half = length / 2
    out: list[str] = []
    for n, mark in enumerate(pneumatic_marks(points)):
        # mxGeometry.x runs -1 to +1 from source to target by arc length.
        rel = max(-1.0, min(1.0, 2.0 * mark.along / total - 1.0))
        horiz = mark.horizontal
        angle = _HATCH_ANGLE if horiz else _HATCH_ANGLE + 90.0
        style = (f"shape=line;rotation={angle:g};strokeColor={ink};"
                 f"strokeWidth={fit.length(LineWeight.DETAIL.width):g};fillColor={_NO_FILL};html=1;"
                 "resizable=0;movable=1;")
        for k, off in enumerate(_svg.HATCH_ALONG):
            step = fit.length(off)
            dx, dy = (step, 0.0) if horiz else (0.0, step)
            out += [
                f'        <mxCell id="{edge_id}h{n}{k}" value="" style={_attr(style)} '
                f'vertex="1" connectable="0" parent="{edge_id}">',
                f'          <mxGeometry x="{_fraction(rel)}" y="0" '
                f'width="{_num(length)}" height="{_num(length)}" '
                'relative="1" as="geometry">',
                f'            <mxPoint x="{_num(dx - half)}" y="{_num(dy - half)}" '
                'as="offset" />',
                '          </mxGeometry>',
                '        </mxCell>',
            ]
    return out


def _flanges(edge_id: str, s, points, ends, ink: str, fit: "_Fit") -> list[str]:
    """Return the flanged-joint marks on one line.

    draw.io's end markers cannot draw a flange: there is no flange marker,
    markers sit on the end point rather than
    :data:`~pandid.render.svg.FLANGE_STANDOFF` off it, and both ends are
    already used by the arrowhead. So, as in :func:`_hatches`, each bar is
    a child vertex on the edge, two per mark. Positions come from
    :func:`~pandid.render.svg.flange_marks`, so both backends mark the same
    joints.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    s : Stream
        Stream.
    points : list[tuple[float, float]]
        Stream polyline.
    ends : str or None
        Joint for the stream's ends.
    ink : str
        Line colour.
    fit : _Fit
        Sheet-to-file transform.

    Returns
    -------
    list[str]
        XML lines for the flange cells.
    """
    total = sum(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                for (ax, ay), (bx, by) in zip(points, points[1:]))
    if total <= 0:
        return []

    length = fit.length(_svg.FLANGE_TICK)
    half = length / 2
    out: list[str] = []
    for n, mark in enumerate(flange_marks(s, points, ends)):
        rel = max(-1.0, min(1.0, 2.0 * mark.along / total - 1.0))
        # Turn a further quarter so the bar crosses the run. DETAIL
        # weight per ISO 10628-1 5.3.1 c) and 5.3.2, as in the SVG.
        style = (f"shape=line;rotation={mark.angle + 90.0:g};strokeColor={ink};"
                 f"strokeWidth={fit.length(LineWeight.DETAIL.width):g};fillColor={_NO_FILL};"
                 "html=1;resizable=0;movable=1;")
        rad = math.radians(mark.angle)
        for k, sign in enumerate((-1, 1)):
            step = fit.length(_svg.FLANGE_GAP / 2) * sign
            dx, dy = math.cos(rad) * step, math.sin(rad) * step
            out += [
                f'        <mxCell id="{edge_id}f{n}{k}" value="" style={_attr(style)} '
                f'vertex="1" connectable="0" parent="{edge_id}">',
                f'          <mxGeometry x="{_fraction(rel)}" y="0" '
                f'width="{_num(length)}" height="{_num(length)}" '
                'relative="1" as="geometry">',
                f'            <mxPoint x="{_num(dx - half)}" y="{_num(dy - half)}" '
                'as="offset" />',
                '          </mxGeometry>',
                '        </mxCell>',
            ]
    return out


# ----------------------------------------------------------------
# Furniture, as draw.io tables
# ----------------------------------------------------------------

# Table styles as draw.io's Graph.createTable writes them.
# childLayout=tableLayout marks a table; shape=table is needed for the
# startSize title band. The table rules row and column lines itself, so
# rows and cells turn their own edges off and inherit its colour.
_TABLE_SHAPE = ("shape=table;childLayout=tableLayout;container=1;collapsible=0;"
                "fixedHeader=1;html=1;whiteSpace=wrap;align=center;"
                "verticalAlign=middle;fontStyle=1;"
                f"strokeColor={_INK};fillColor={_NO_FILL};")
# A row is a horizontal swimlane with no label strip; points and
# portConstraint give it a connection point at each end.
_TABLE_ROW = ("shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;"
              "swimlaneBody=0;strokeColor=inherit;fillColor=none;"
              "collapsible=0;dropTarget=0;fixedHeader=1;"
              "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
              "top=0;left=0;right=0;bottom=0;")
# pointerEvents=1 keeps unfilled cells clickable.
_TABLE_CELL = ("shape=partialRectangle;html=1;whiteSpace=wrap;connectable=0;"
               "strokeColor=inherit;overflow=hidden;"
               "top=0;left=0;bottom=0;right=0;pointerEvents=1;")
# Heading cells are filled and bold; draw.io has no header flag.
_TABLE_HEAD = "fillColor=#eeeeee;fontStyle=1;align=center;"
_TABLE_BODY = "fillColor=none;"


def _distribute(weights, total: float) -> list[float]:
    """Return ``total`` split between columns in proportion to ``weights``.

    Parts are rounded to two decimals and the last takes the remainder,
    so the cells sum exactly to their row: draw.io's table layout does not
    correct a mismatch on load.

    Parameters
    ----------
    weights : iterable of float
        Relative widths; negative values count as 0.
    total : float
        Width to split.

    Returns
    -------
    list[float]
        Column widths summing to ``total`` rounded to two decimals.
    """
    ws = [max(float(w), 0.0) for w in weights] or [1.0]
    span = sum(ws)
    if span <= 0:
        ws, span = [1.0] * len(ws), float(len(ws))
    whole = round(float(total), 2)
    out, used = [], 0.0
    for w in ws[:-1]:
        part = round(whole * w / span, 2)
        out.append(part)
        used += part
    out.append(round(whole - used, 2))
    return out


# Clearance between a cell's rules and its text, both sides together.
# draw.io adds mxText.spacing (2) to the style's spacingLeft/Right (3 or 4
# here), using 7 to 8 of the 12; the rest absorbs the error of
# furniture.text_width, which underestimates bold capitals by about 11%.
_CELL_PAD = 12.0

# Line box height as a multiple of font size. HTML labels get the
# unitless CSS line-height 1.2 (mxConstants.LINE_HEIGHT). mxGraph never
# shrinks text to fit, so a row shorter than its line box clips letters.
_LINE_BOX = 1.2


def _line_box(size: float) -> float:
    """Return the line box height for a font size (:data:`_LINE_BOX`).

    Parameters
    ----------
    size : float
        Font size.

    Returns
    -------
    float
        Line height.
    """
    return size * _LINE_BOX

# Style keys for TableBox column alignment; unstated columns are centred.
_ALIGN_KEY = {"l": "align=left;spacingLeft=4;", "r": "align=right;spacingRight=4;",
              "c": "align=center;"}

# The frame weight is pandid.render.furniture.FRAME_RULE, shared by both
# backends; the title strip's layout already clears the frame's ink.

# Baseline depth within a line box, as a fraction of font size: converts
# the SVG's baseline positions to draw.io's CSS boxes. Helvetica gives
# 0.87 and Arial 0.947 in a 1.2 em box; 0.9 splits the difference, within
# the error of furniture.text_width.
_BASELINE = 0.9

# Inset draw.io applies on every side of a cell before text (mxText.spacing
# = 2). A cell whose text must start at the SVG's x begins 2 units left.
_TEXT_INSET = 2.0


def _ALIGN_KEYS(col_align, ncol: int) -> list[str]:
    """Return the alignment style keys for each column.

    Parameters
    ----------
    col_align : sequence of str or None
        ``"l"``, ``"c"`` or ``"r"`` per column; missing columns are centred.
    ncol : int
        Number of columns.

    Returns
    -------
    list[str]
        Style fragment per column.
    """
    align = list(col_align or [])
    return [_ALIGN_KEY.get(align[c] if c < len(align) else "c", "align=center;")
            for c in range(ncol)]


def columns(rows, sizes, total: float, bold=None) -> list[float]:
    """Return column widths measured from the text.

    Each column is as wide as its widest text
    (:func:`pandid.render.furniture.text_width`, as the SVG measures) plus
    :data:`_CELL_PAD`. Slack goes to the last column; a shortfall is shared
    in proportion, as the SVG clips.

    Parameters
    ----------
    rows : list[list[str]]
        Cell text.
    sizes : sequence of float
        Font size per column; the last applies to any extra columns.
    total : float
        Table width.
    bold : sequence of bool, optional
        Whether each column is bold, which is about 11% wider.

    Returns
    -------
    list[float]
        Column widths summing to ``total``.
    """
    from pandid.render.furniture import text_width

    ncol = max((len(r) for r in rows), default=1)
    weights = list(bold) if bold is not None else []
    need = []
    for c in range(ncol):
        size = sizes[c] if c < len(sizes) else (sizes[-1] if sizes else 11.0)
        heavy = bool(weights[c]) if c < len(weights) else False
        widest = max((text_width(r[c], size, heavy) for r in rows if c < len(r)),
                     default=0.0)
        need.append(widest + _CELL_PAD)
    span = sum(need)
    if span <= 0:
        return _distribute([1.0] * ncol, total)
    if span > total:  # cannot fit; clip in proportion, as the sheet does
        return _distribute(need, total)
    out = _distribute(need[:-1] + [need[-1] + (total - span)], total)
    return out


def _table(cid: str, title: str, headers, rows, x, y, w, h, widths,
           start: float = 0.0, *, header_last: bool = False,
           font: float = 11.0, col_keys=(), row_h: "float | None" = None,
           heights=None, keys: str = "", row_widths=None,
           cell_keys=None) -> list[str]:
    """Return a ruled grid as a draw.io table: container, rows and cells.

    mxGraph does not inherit style from a parent cell (only ``inherit``
    for stroke and fill colours), so the font size is stated on every
    cell. It precedes ``col_keys``, so a column's own size wins.
    Dimensions are rounded before rows and cells are cut, so parts sum
    exactly to the whole (:func:`_distribute`).

    Parameters
    ----------
    cid : str
        Container cell id.
    title : str
        Title in the swimlane head; empty for none.
    headers : list[str]
        Heading row, or empty.
    rows : list[list[str]]
        Body rows.
    x, y, w, h : float
        Table rectangle.
    widths : list[float]
        Column widths summing to ``w`` (from :func:`columns` or a fixed
        ruling).
    start : float, default=0.0
        Title band height; 0 for no band.
    header_last : bool, default=False
        Put the heading row at the foot, as a revision history does.
    font : float, default=11.0
        Cell font size; draw.io's default is 12.
    col_keys : sequence of str, optional
        Extra style per column.
    row_h : float, optional
        Fixed row height; the table is then as tall as its rows.
    heights : sequence of float, optional
        Relative row heights, distributed over the body height.
    keys : str, default=""
        Extra container style, such as ``rowLines=0``.
    row_widths : list[list[float]], optional
        Cell widths per row, allowing a row with fewer (merged) cells.
    cell_keys : list[list[str]], optional
        Style per cell, replacing the heading and body styles.

    Returns
    -------
    list[str]
        XML lines.
    """
    body = [row for row in rows]
    if headers:
        body = body + [headers] if header_last else [headers] + body
    head_at = (len(body) - 1) if (headers and header_last) else (0 if headers else None)
    ncol = max((len(r) for r in body), default=1)
    # Round before cutting rows and cells, so parts sum as written.
    w, start = round(float(w), 2), round(float(start), 2)
    if row_h is not None and body:
        h = round(start + row_h * len(body), 2)
    else:
        h = round(float(h), 2)
    widths = _distribute(list(widths)[:ncol] or [1.0] * ncol, w)
    if len(widths) < ncol:
        widths = _distribute([1.0] * ncol, w)
    # Per-row widths are distributed the same way.
    ragged = [_distribute(rw, w) for rw in row_widths] if row_widths else None
    rows_h = _distribute(list(heights) if heights else [1.0] * len(body),
                         h - start) if body else []

    shape = _TABLE_SHAPE + f"startSize={_num(start)};fontSize={font:g};" + keys
    cell = _TABLE_CELL + f"fontSize={font:g};"
    out = [
        f'        <mxCell id="{cid}" value={_attr(_html_text(title))} '
        f'style={_attr(shape)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" '
        f'height="{_num(h)}" as="geometry" />',
        '        </mxCell>',
    ]
    ry = start
    for r, cells in enumerate(body):
        rh = rows_h[r]
        cw = ragged[r] if ragged else widths
        head = "" if cell_keys is not None else (
            _TABLE_HEAD if r == head_at else _TABLE_BODY)
        out += [
            f'        <mxCell id="{cid}-r{r}" value="" style={_attr(_TABLE_ROW)} '
            f'vertex="1" parent="{cid}">',
            f'          <mxGeometry y="{_num(ry)}" width="{_num(w)}" '
            f'height="{_num(rh)}" as="geometry" />',
            '        </mxCell>',
        ]
        cx = 0.0
        for c in range(len(cw)):
            value = str(cells[c]) if c < len(cells) else ""
            extra = (cell_keys[r][c] if cell_keys is not None
                     else col_keys[c] if c < len(col_keys) else "")
            out += [
                f'        <mxCell id="{cid}-r{r}-c{c}" value={_attr(_html_text(value))} '
                f'style={_attr(cell + head + extra)} vertex="1" '
                f'parent="{cid}-r{r}">',
                f'          <mxGeometry x="{_num(cx)}" width="{_num(cw[c])}" '
                f'height="{_num(rh)}" as="geometry">',
                f'            <mxRectangle width="{_num(cw[c])}" '
                f'height="{_num(rh)}" as="alternateBounds" />',
                '          </mxGeometry>',
                '        </mxCell>',
            ]
            cx += cw[c]
        ry += rh
    return out


def _fill(colour: str) -> str:
    """Return a sheet fill in draw.io's six-digit hex form.

    Parameters
    ----------
    colour : str
        CSS colour such as ``"white"`` or ``"#eee"``.

    Returns
    -------
    str
        The same colour as ``#rrggbb`` where it was a name or short hex.
    """
    if colour == "white":
        return "#ffffff"
    if len(colour) == 4 and colour.startswith("#"):
        return "#" + "".join(c * 2 for c in colour[1:])
    return colour


def _stream_cell(cell) -> str:
    """Return the style for one stream-table cell.

    Fill, weight and alignment come from the layout. Left-aligned text is
    inset by :data:`~pandid.render.furniture._STREAM_PAD` less draw.io's
    own :data:`_TEXT_INSET`, matching the SVG.

    Parameters
    ----------
    cell : StreamCell
        Laid-out cell.

    Returns
    -------
    str
        Style fragment.
    """
    if cell.anchor == "start":
        align = f"align=left;spacingLeft={_num(F._STREAM_PAD - _TEXT_INSET)};"
    else:
        align = "align=center;"
    return (f"fillColor={_fill(cell.fill)};" + align
            + ("fontStyle=1;" if cell.bold else ""))


def _stream_table(cid: str, table, x, y) -> list[str]:
    """Return the stream property table as a draw.io table.

    Every cell is ruled, as the SVG strokes each cell, at
    :data:`~pandid.render.furniture._CELL_RULE`. A section heading is a row
    with one full-width cell, which draws no column lines.

    Parameters
    ----------
    cid : str
        Container cell id.
    table : StreamTable
        Laid-out table.
    x, y : float
        Top-left corner.

    Returns
    -------
    list[str]
        XML lines.
    """
    values = [[c.text for c in row] for row in table.rows]
    widths = [[c.w for c in row] for row in table.rows]
    return _table(cid, "", [], values, x, y, table.w, table.h, widths[0],
                  font=table.size, row_h=table.row_h,
                  keys=f"strokeWidth={F._CELL_RULE:g};",
                  row_widths=widths,
                  cell_keys=[[_stream_cell(c) for c in row]
                             for row in table.rows])


def _text_box(cid: str, title: str, rows, x, y, w, h, font: float = 11.0,
              title_h: float = 0.0) -> list[str]:
    """Return a box of free-form lines, such as a notes list.

    Drawn as the SVG draws it
    (:func:`~pandid.render.furniture.draw_annotation`): the box, a centred
    bold title one point larger with a rule under it, and the lines in one
    left-aligned cell. The font size is stated, since draw.io defaults to
    12.

    Parameters
    ----------
    cid : str
        Base cell id.
    title : str
        Title, or empty.
    rows : list[str]
        Lines of text.
    x, y, w, h : float
        Box rectangle.
    font : float, default=11.0
        Body font size.
    title_h : float, default=0.0
        Title band height.

    Returns
    -------
    list[str]
        XML lines.
    """
    box = ("rounded=0;whiteSpace=wrap;html=1;movable=1;"
           f"strokeColor={_INK};fillColor={_NO_FILL};"
           f"strokeWidth={F._BOX_RULE:g};")
    out = _rect(cid, x, y, w, h, box)
    if title:
        # As draw_annotation: centred, bold, one point larger.
        out += _strip_label(f"{cid}-t", ("text", x + w / 2, y + title_h - 6,
                                         title, font + 1, "middle", True, "black"))
        out += _segment(f"{cid}-r", x, y + title_h, x + w, y + title_h,
                        _INK, F._BOX_UNDERLINE)
    # Body gutter: the SVG's 9 less draw.io's _TEXT_INSET.
    body = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
            f"align=left;verticalAlign=top;spacingLeft=7;fontSize={font:g};"
            f"fontColor={_LINE_INK};")
    return out + [
        f'        <mxCell id="{cid}-b" '
        f'value={_attr("<br>".join(_html_text(r) for r in rows))} '
        f'style={_attr(body)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y + title_h)}" '
        f'width="{_num(w)}" height="{_num(h - title_h)}" as="geometry" />',
        '        </mxCell>',
    ]


# Annotation tables draw only the border and title band, as the SVG does;
# rows and cells remain for editing and stroke nothing.
_ANNOTATION_KEYS = "rowLines=0;columnLines=0;"


def _fitted(inner, free) -> "tuple[float, float, float]":
    """Return the scale and offset that centre the drawing in ``free``.

    Uses :func:`pandid.render.svg._fit_scale`, so the title strip's scale
    cell matches.

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
    from pandid.render.svg import _fit_scale

    dx0, dy0, dx1, dy1 = inner
    fx, fy, fw, fh = free
    dw, dh = dx1 - dx0, dy1 - dy0
    s = _fit_scale(dw, dh, free)
    return (s, fx + (fw - s * dw) / 2 - s * dx0, fy + (fh - s * dh) / 2 - s * dy0)


def _rect(cid: str, x, y, w, h, style: str) -> list[str]:
    """Return a bare rectangle cell, used for the drawing frame.

    Parameters
    ----------
    cid : str
        Cell id.
    x, y, w, h : float
        Rectangle.
    style : str
        Cell style.

    Returns
    -------
    list[str]
        XML lines.
    """
    return [
        f'        <mxCell id="{cid}" value="" style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" '
        f'height="{_num(h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _segment(cid: str, x1, y1, x2, y2, ink: str, weight: float) -> list[str]:
    """Return a ruled line between two points, as draw.io writes a free rule.

    ``noJump=1``, since furniture rules are not connections
    (:data:`_NO_HOP`).

    Parameters
    ----------
    cid : str
        Cell id.
    x1, y1, x2, y2 : float
        End points.
    ink : str
        Stroke colour.
    weight : float
        Stroke width.

    Returns
    -------
    list[str]
        XML lines.
    """
    style = (f"edgeStyle=none;rounded=0;html=1;endArrow=none;startArrow=none;"
             f"strokeColor={ink};strokeWidth={weight:g};movable=1;{_NO_HOP}")
    return [
        f'        <mxCell id="{cid}" value="" style={_attr(style)} '
        f'edge="1" parent="1">',
        '          <mxGeometry relative="1" as="geometry">',
        f'            <mxPoint x="{_num(x1)}" y="{_num(y1)}" as="sourcePoint" />',
        f'            <mxPoint x="{_num(x2)}" y="{_num(y2)}" as="targetPoint" />',
        '          </mxGeometry>',
        '        </mxCell>',
    ]


# Half the cell a zone letter is centred in.
_LABEL_HALF = 8.0


def _label(cid: str, cx, cy, text: str, size: float) -> list[str]:
    """Return bold lettering centred on a point, such as a zone letter.

    Parameters
    ----------
    cid : str
        Cell id.
    cx, cy : float
        Centre.
    text : str
        Text.
    size : float
        Font size.

    Returns
    -------
    list[str]
        XML lines.
    """
    style = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
             f"align=center;verticalAlign=middle;fontStyle=1;fontSize={size:g};"
             f"fontColor={_LINE_INK};")
    return [
        f'        <mxCell id="{cid}" value={_attr(_html_text(text))} '
        f'style={_attr(style)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(cx - _LABEL_HALF)}" '
        f'y="{_num(cy - _LABEL_HALF)}" width="{_num(2 * _LABEL_HALF)}" '
        f'height="{_num(2 * _LABEL_HALF)}" as="geometry" />',
        '        </mxCell>',
    ]


def _strip_rule(cid: str, part) -> list[str]:
    """Return one title-strip rule as an edge.

    Parameters
    ----------
    cid : str
        Cell id.
    part : tuple
        ``(kind, x1, y1, x2, y2, weight)``.

    Returns
    -------
    list[str]
        XML lines.
    """
    _kind, x1, y1, x2, y2, weight = part
    return _segment(cid, x1, y1, x2, y2, _LINE_INK, weight)


def _strip_label(cid: str, part) -> list[str]:
    """Return one piece of title-strip lettering as a text cell.

    The strip gives an SVG baseline and ``text-anchor``; :data:`_BASELINE`
    and :data:`_TEXT_INSET` convert them to a draw.io box one line tall.
    Text does not wrap and overflow stays visible, so a slightly
    underestimated width runs past the box rather than wrapping.

    Parameters
    ----------
    cid : str
        Cell id.
    part : tuple
        ``(kind, x, y, text, size, anchor, bold, ink)`` from
        :class:`~pandid.render.furniture.Strip`.

    Returns
    -------
    list[str]
        XML lines, empty for empty text.
    """
    _kind, tx, ty, text, size, anchor, bold, ink = part
    if not text:
        return []
    box_w = F.text_width(text, size, bold) + 2 * _TEXT_INSET
    box_h = _line_box(size) + 2 * _TEXT_INSET
    top = ty - _BASELINE * size - _TEXT_INSET
    if anchor == "middle":
        left, align = tx - box_w / 2, "center"
    elif anchor == "end":
        left, align = tx + _TEXT_INSET - box_w, "right"
    else:
        left, align = tx - _TEXT_INSET, "left"
    style = ("text;html=1;strokeColor=none;fillColor=none;"
             f"align={align};verticalAlign=middle;fontSize={size:g};"
             f"fontColor={_LINE_INK if ink == 'black' else ink};"
             + ("fontStyle=1;" if bold else ""))
    return [
        f'        <mxCell id="{cid}" value={_attr(_html_text(text))} '
        f'style={_attr(style)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(left)}" y="{_num(top)}" '
        f'width="{_num(box_w)}" height="{_num(box_h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _rev_table(cid: str, grid) -> list[str]:
    """Return the revision history as an editable draw.io table.

    Ruled as the SVG rules it: column lines only (``rowLines=0``), at the
    strip hairline, plus one rule above the heading row at the foot. The
    blank space above the oldest revision becomes blank rows to type into.

    Parameters
    ----------
    cid : str
        Container cell id.
    grid : RevGrid
        Laid-out revision grid.

    Returns
    -------
    list[str]
        XML lines.
    """
    headings = [heading for heading, _cw in grid.cols]
    rows = [row for row in grid.rows]
    # Filler rows, then revisions oldest to newest, then the heading. A
    # partial row's remainder goes into the topmost filler row.
    blank = grid.header_y - grid.y - grid.row_h * len(rows)
    whole = int(round(blank / grid.row_h - 0.5)) if blank > 0 else 0
    heights: list[float] = []
    if whole:
        heights = [blank - (whole - 1) * grid.row_h] + [grid.row_h] * (whole - 1)
    elif blank > 0.01:
        heights = [blank]
    body = [[""] * len(headings) for _ in heights] + rows
    heights += [grid.row_h] * (len(rows) + 1)

    out = _table(cid, "", headings, body, grid.x, grid.y, grid.w, grid.h,
                 [cw for _heading, cw in grid.cols], header_last=True,
                 font=F._REV_TYPE, heights=heights,
                 keys=f"rowLines=0;strokeWidth={F._STRIP_HAIRLINE:g};",
                 col_keys=["align=left;spacingLeft=3;"] * len(headings))
    return out + _segment(f"{cid}-rule", grid.x, grid.header_y,
                          grid.x + grid.w, grid.header_y, _LINE_INK,
                          F._BOX_UNDERLINE)


def _strip_size(block) -> "tuple[float, float]":
    """Return the title strip size, as the SVG measures it.

    Parameters
    ----------
    block : TitleBlock
        Title block.

    Returns
    -------
    tuple[float, float]
        Width and height.
    """
    return F.measure_title_strip(block)
