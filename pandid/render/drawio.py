"""draw.io / diagrams.net (``.drawio``) export.

The SVG backend draws a finished picture. This one hands the reader back
the *model*: units as draw.io vertices, streams as draw.io edges between
them, so an author can open the sheet, drag a column two hundred units
left and have its lines follow. It is also the way to Visio, which
draw.io exports natively.

**The symbols in this library are draw.io's own P&ID stencils**,
vendored and converted (see NOTICE), so the export does not trace
geometry: it names the shape. ``mxgraph.pid.valves.gate_valve`` is a key
draw.io's stencil registry already answers to.
:func:`scripts.vendor_symbols.drawio_shape_key` derives it from the two
names in the stencil file itself, by draw.io's own rule, at the moment
the artwork is converted, and
:attr:`~pandid.render.symbols.Symbol.drawio_shape` carries it here. A
key that has stopped resolving is the quietest failure this file can
have -- draw.io answers one with a plain rectangle rather than an error
-- so ``tests/test_drawio.py`` walks every symbol the library can draw
and holds each reference against the vendored stencils.

Three things fall out of that arrangement:

* **Sizing.** draw.io scales a stencil into the box the cell is given,
  stretching it where the stencil says ``aspect="variable"`` and
  centring it uniformly where it says ``"fixed"`` -- the same question
  :func:`pandid.portgeom.ink_box` asks of
  :attr:`~pandid.render.symbols.Symbol.stretchable`, since that flag
  *is* the stencil's own attribute. So the box is the whole of the
  mapping, and the reproportioning ``SCALE`` in
  ``scripts/vendor_symbols.py`` applies to four families is already in
  the box the layout engine used. This holds only while every referenced
  stencil is ``variable``, and a test pins that.
* **Ports.** A draw.io fixed connection point is a fraction of the
  cell's box, which is what :func:`pandid.portgeom.port_point` already
  computes in absolute terms; dividing through is the whole conversion.
* **Ink.** ``scripts/mxgraph_to_svg.py`` converts a stencil with its
  fill state starting at ``none`` and every stroke at ``#111``, standing
  in for the ``fillColor``/``strokeColor`` draw.io would have taken from
  the style. Saying those two back in the style reproduces the sheet's
  ink, ``<fillcolor>`` overrides inside the stencil included, since
  draw.io honours those itself.

What is *not* free is written down rather than discovered in draw.io.
:data:`_APPROXIMATIONS` is every symbol this library draws itself
because draw.io has no stencil for it, each with the sentence saying
what its stand-in loses; the stand-ins are draw.io *built-ins* rather
than stencils, so a reference there cannot fail to resolve the way a
stencil key could. Sheet furniture is docked where the sheet docks it
and ruled the way the sheet rules it
(:meth:`DrawioRenderer._furniture`).

**Nothing on the sheet is silently absent.** Written down is not the
same as said, so every one of those sentences is *reported*: a stand-in
that loses something names the unit and what it lost on
``fs.warnings`` (:data:`APPROXIMATED`), and a title-block cell that had
to abbreviate its value says so there too, in the words the rendered
sheet uses and through the same
:data:`~pandid.render.furniture.Reporter`. An export that says nothing
lost nothing.

**A composed symbol is a group of cells, not a shape.** A body carrying
ISO 10628-2 supplementary parts -- an agitator in a reactor, trays in a
column, a settling arrow in a separating vessel -- names no stencil of
its own, and that is deliberate: a stencil reference names *one* shape,
so a stirred tank exported under the vessel's own reference would come
out a bare vessel, the right outline with the thing that made it a
reactor silently gone. It is drawn instead as **the body's cell with one
child cell per part**, each placed by the same fractions of the body's
box the SVG uses (:meth:`DrawioRenderer._overlay_cells`), so the two
backends draw the same parts in the same places from one set of numbers.
The ten group-28 agitators name draw.io's own ``mxgraph.pid.agitators``
stencils; the other twenty-seven parts have :data:`_PART_APPROXIMATIONS`,
which is :data:`_APPROXIMATIONS` for parts and carries the same sentence
each about what its stand-in loses.

**A model, or a sheet.** Given ``page_size`` this stops being a drawing
on an unbounded canvas and becomes paper: the file states the page, the
furniture docks to it rather than to the drawing's own bounds, and the
drawing is fitted into what the furniture leaves, all through the same
:func:`~pandid.render.furniture.dock` and
:func:`~pandid.render.svg._fit_scale` the rendered sheet uses.
``border="zone"`` then rules that page. Without a page size none of it
happens and the drawing keeps its own coordinates. See :class:`_Fit`.

**One** piece of sheet detail has no draw.io construct at all, and
simply is not drawn: a symbol's own lettering held upright under a turn
(the "M" on a motor operator), which draw.io turns with the shape.

The output is a plain uncompressed ``mxfile``. draw.io reads that as
readily as its compressed form, and it diffs.

What draw.io actually does
--------------------------

Everything below was read out of draw.io's and mxGraph's own source
rather than inferred from behaviour, because none of it can be checked
here: nothing in this repository opens a ``.drawio`` file. Each item
says where it came from. Line numbers drift; the function names do not.

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
  anywhere.** So ``;`` is the *only* character a value cannot contain --
  parentheses, commas, ampersands, hyphens and slashes, which
  forty-eight of the vendored keys carry, are all safe. Two traps: a
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

from pandid.portgeom import port_point, unit_box
# ISO 10628-1 5.3.1 c)'s in-line detail band, half the outline weight
# below: imported rather than repeated, since the sheet draws a part and
# its body at exactly that ratio and an export at another one is a second
# drawing.
from pandid.render.iso_parts import PART_STROKE as _PART_STROKE
from pandid.render import furniture as F
from pandid.render import generator
from pandid.render import svg as _svg
from pandid.render.escape import escaped, writable
from pandid.render.svg import (_DIAMOND_BALLOONS, _FIT_CODES, _furniture_name,
                               _LEADER_HEAD, _scale_text, _too_small,
                               _SIGNAL_DASH, _PROCESS_STROKE,
                               _SIGNAL_STROKE, _TAP_DASH, fit_issue, HOP_R,
                               NUMBER_TYPE, boundary_flag,
                               draws_arrowheads, flange_marks, impulse_tap,
                               resolve_connections, sheet_connections,
                               stream_numbers, stream_polyline, tap_lines)
from pandid.render.symbols import (ARROWHEAD, closed_marking, fail_marking,
                                   wears_arrowhead)
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: The one ink the sheet is drawn in, and the one draw.io has to be told
#: to draw it in. ``scripts/mxgraph_to_svg.py`` converts every stencil
#: stroke to this and fills a solid part of one with it;
#: :data:`pandid.render.symbols._BODY_INK` is the same colour, for the
#: same reason. Repeated here rather than imported from the script,
#: which is not part of the installed package.
_INK = "#111"

#: What the fill starts at, for everything this file draws itself: a
#: monochrome sheet lets the paper through.
_NO_FILL = "none"

#: What a *vendored stencil* is filled with, which is not that. draw.io
#: draws its shape, and no P&ID palette in it names a ``fillColor``, so
#: the page colour is what the artwork was authored under: its body is
#: the last ``<fillstroke>`` in the shape and covers the nozzles behind
#: it. See ``scripts/mxgraph_to_svg.DEFAULT_FILL``, the same colour for
#: the same reason. Written ``none`` here, the sphere's shell ran
#: through both its crown nozzles on the export as well as the sheet.
_PAPER = "#ffffff"

#: No ink at all. The same word, and it works for the same reason:
#: draw.io's ``mxStylesheet.getCellStyle`` *deletes* a key whose value
#: is exactly ``none`` rather than setting it, so the cell inherits
#: neither the style's colour nor the stylesheet default's, and
#: ``mxShape.configureCanvas`` strokes nothing. A cell drawn in it keeps
#: its geometry and stays selectable and connectable, which is the whole
#: point of using it for a junction that draws no ink of its own;
#: ``shape=none`` is the trap next door, since deleting *that* key falls
#: back to the default vertex and draws a plain rectangle.
_NO_STROKE = "none"

#: The pen the sheet rules a **symbol's outline** with.
#:
#: It has to be stated: every one of the 319 vendored stencils declares
#: ``strokewidth="inherit"``, which puts the pen in the cell's style
#: rather than in the stencil's own coordinate space, so a cell that
#: says nothing draws at draw.io's default 1 against pipes emitted at
#: the sheet's 2.
#:
#: Two is the sheet's own answer, in two places. Every hand-drawn symbol
#: in :mod:`pandid.render.symbols` says ``stroke-width="2"`` on its
#: outline, and ``scripts/vendor_symbols.py`` compensates each converted
#: stencil for the scale its artwork is drawn at, ``stroke_width = 2.0 /
#: sqrt(sx * sy)``, so a gate valve's ``8.0`` inside a ``scale(0.25)``
#: group is that same 2 on the paper. Neither is a constant to import --
#: one is a literal in a hundred SVG fragments, the other is in a
#: generator outside the installed package -- so
#: ``tests/test_drawio.py`` measures it back off the rendered sheet.
#:
#: ISO 15519-1:2010 §6.2 Table 1 gives the process industry 0,1 M for
#: symbols and 0,2 M for connections, so a symbol is *meant* to be the
#: lighter of the two, by a stated ratio rather than by whatever the
#: reader's editor defaults to. This library rules both at 2.
_SYMBOL_STROKE = 2.0

#: The ink a *line* is drawn in, which is not quite the ink a symbol is
#: drawn in: the SVG renderer strokes a stream ``black`` and a converted
#: stencil ``#111``, and this is the first of those, written the way a
#: draw.io style writes a colour. A hundredth of a shade apart, and
#: copied rather than unified, since unifying them here would be this
#: file quietly editing the sheet.
_LINE_INK = "#000000"

#: The glyph draw.io hops a crossing line with, of the five its Format
#: panel offers (``none``, ``arc``, ``gap``, ``sharp``, ``line`` --
#: ``EditorFormatPanel.addLineJumps``). ``arc`` because the sheet draws
#: a semicircle: :meth:`SvgRenderer._draw_streams` writes ``A 5 5 0 0
#: 1`` and nothing else, and ``gap`` breaks the line instead while
#: ``sharp`` and ``line`` are a chevron and a pair of ticks.
#:
#: The arc is not quite a semicircle at draw.io's end:
#: ``mxConnector.paintLine`` draws a *cubic* whose two control points
#: stand off the run by ``1,3`` times the hop's half-extent, putting the
#: crown at ``0,75 x 1,3 = 0,975`` of it. So a hop sized to the sheet's
#: radius is a hundredth of a unit shallower. There is no key that makes
#: it an arc of a circle.
#:
#: **Which side it bulges is draw.io's and not the author's.**
#: ``paintLine`` takes the sign from the segment's own direction -- ``f
#: = (round(n.x) < 0 || (round(n.x) == 0 && round(n.y) <= 0)) ? 1 : -1``
#: -- which works out to *east* for every vertical run and *north* for
#: every horizontal one, whichever way round the run was routed. The
#: sheet fixes its sweep flag instead of its sign, so its hop follows
#: the routing: east down a run and west up the identical run. A
#: difference a reader comparing the two drawings will see.
_JUMP_STYLE = "arc"

#: An edge that is never hopped, whatever is written after it.
#:
#: The sheet's jump pass builds its two lists of segments from
#: ``fs.streams`` and from nothing else
#: (:meth:`SvgRenderer._draw_streams`), so on paper only a *stream* hops
#: and only a stream is hopped. Everything else this file writes as an
#: edge -- a ruled line of furniture, an instrument connection, a line
#: number's leader -- is an edge because that is how the format says "a
#: line between two points", not because it is a connection anything
#: flows along.
#:
#: draw.io has no such distinction and would hop any of them, so the
#: rule is stated rather than left to the emission order that happens to
#: hold today: ``updateLineJumps`` skips a candidate whose style says
#: ``noJump=1``. Saying it makes the drawing right whichever way round
#: the cells are written, which matters here more than usual, since
#: :func:`_hops` reorders them.
_NO_HOP = "noJump=1;"


def _jump_size(radius: float, weight: float) -> int:
    """draw.io's ``jumpSize``, for a hop of *radius* on a line of
    *weight*.

    Not the radius. ``mxConnector.paintLine`` computes the hop's
    half-extent along the run as ``(parseInt(jumpSize) - 2) / 2 +
    this.strokewidth``, so the number in the style is two units of its
    own plus twice the pen -- and the pen is the *edge's* pen, which is
    why this takes one: a signal line and the pipe it crosses are hopped
    by the same radius but stated with different sizes. Solved for
    ``jumpSize`` that is ``2 (radius - weight) + 2``.

    ``parseInt`` and not ``parseFloat``, so a fractional value is
    **truncated** rather than rounded; the answer is rounded here
    instead, which is worth at most a quarter of a unit of radius and
    never the whole unit truncation would cost. One is the floor because
    a ``jumpSize`` small enough to make the half-extent negative would
    draw the hop inside out, and draw.io's own default is 6
    (``Graph.defaultJumpSize``).
    """
    return max(1, round(2.0 * (radius - weight) + 2.0))


def _hops(polylines: dict, direction: str) -> "tuple[list, set]":
    """Which edges carry the hop, and the order that lets draw.io draw
    it.

    ``polylines`` is ``{key: points}`` for every **stream** on the
    sheet, in the order the streams are to be written; ``direction`` is
    :meth:`Flowsheet.to_svg`'s own ``jump_direction``. Returns the keys
    in the order they must be emitted in, and the set of them that is to
    carry :data:`_JUMP_STYLE`.

    **Which line hops** is the sheet's rule, taken from the same place
    :meth:`SvgRenderer._draw_streams` takes it: a *vertical* segment
    crossing a *horizontal* one hops it, or the other way round under
    ``jump_direction="horizontal"``. Strictly inside both segments, as
    the sheet has it, so a run that merely ends on another one is a
    junction and is not hopped. Any other spelling of ``direction`` hops
    nothing, which is what the SVG does with one too.

    **Which line draw.io *lets* hop** is z-order, and that is the half
    the exporter has to build rather than state: ``updateLineJumps``
    intersects an edge only against the edges written before it, so the
    hopping edge has to be written after every edge it crosses. The
    streams are therefore emitted in a topological order of "crossed
    before crossing" rather than in ``fs.streams`` order -- stable, by
    original index, so a sheet with no crossing on it comes out in
    exactly the order it always did, and so does every part of a sheet
    that is not involved in one.

    Only the *hop* is per-edge; a style key cannot say "hop on my
    vertical segments and not my horizontal ones", and it does not have
    to. An edge H that is crossed at c is written *before* the edge V
    that hops it, so H cannot hop at c whether or not it carries
    ``jumpStyle`` for a crossing of its own elsewhere. "Hopper after
    crossed" is the whole constraint.

    Where it does not hold is a **cycle**: V's vertical crosses H's
    horizontal *and* H's vertical crosses V's horizontal, so each has to
    be written after the other. draw.io's model cannot express that pair
    and neither can this function; it satisfies every constraint it can
    and leaves the remainder in stream order, so the sheet loses a hop
    rather than gaining a wrong one. Nothing in the shipped corpus
    reaches it -- ``11_ethanol_pid`` is the only example with crossings
    at all, seven of them, and its precedence graph is a forest -- and a
    test pins that the emitted order satisfies every crossing.
    """
    keys = list(polylines)
    if direction not in ("vertical", "horizontal"):
        return keys, set()
    # The two families of segment, by the edge that owns each.
    # `_draw_streams` keeps the same two lists and tests the same strict
    # containment.
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
    hops: set = set()
    for hop_key, lo, hi, at in hopping:
        for cross_key, c_lo, c_hi, c_at in crossed:
            if not (c_lo < at < c_hi and lo < c_at < hi):
                continue
            # A run crossing itself is one line, not two, and draw.io
            # does not hop it either: an edge is pushed onto
            # `validEdges` after its own jumps are computed, so it never
            # intersects itself.
            if hop_key == cross_key:
                continue
            hops.add(hop_key)
            after[hop_key].add(cross_key)
    if not hops:
        return keys, hops
    # Kahn's, taking the lowest original index each round -- `keys` is
    # already in that order, so `ready[0]` is it -- which keeps the
    # emitted order as close to the stream order as the crossings allow.
    order: list = []
    done: set = set()
    while len(done) < len(keys):
        ready = [key for key in keys if key not in done and not (after[key] - done)]
        if not ready:  # a cycle: see the docstring
            break
        order.append(ready[0])
        done.add(ready[0])
    # Whatever the cycle left behind, in stream order.
    return order + [key for key in keys if key not in done], hops


#: pandid turns a symbol clockwise; draw.io names the same four
#: attitudes after the compass point the shape's own east ends up on.
#: ``mxShape.getShapeRotation`` adds 90 for ``south``, 180 for ``west``
#: and 270 for ``north``, so this is that table read the other way. The
#: identity is absent: a cell with no ``direction`` is already upright,
#: and saying so would only make every style longer.
_DIRECTION = {90: "south", 180: "west", 270: "north"}


class _Fit(NamedTuple):
    """Where the drawing sits on the paper, and how big.

    A page size makes the export a *sheet*: the furniture docks to the
    paper and the drawing is fitted into whatever the bands leave, which
    is :meth:`SvgRenderer.render`'s ``<g id="drawing"
    transform="translate(...) scale(...)">`` and nothing more. Every
    coordinate that belongs to the **drawing** goes through this on the
    way out; every coordinate that belongs to the **sheet** -- the
    furniture, the border -- does not, because the sheet is already in
    page units. That is the same division the SVG makes by putting one
    of them inside the group and the other outside it.

    Without a page there is no fitting to do and this is the identity,
    which is why the unpaged export is unchanged to the last coordinate.
    """
    scale: float
    dx: float
    dy: float

    @classmethod
    def identity(cls) -> "_Fit":
        return cls(1.0, 0.0, 0.0)

    def at(self, x: float, y: float) -> "tuple[float, float]":
        return (self.dx + self.scale * x, self.dy + self.scale * y)

    def box(self, b) -> "tuple[float, float, float, float]":
        return (*self.at(b[0], b[1]), *self.at(b[2], b[3]))

    def length(self, v: float) -> float:
        """A distance, which scales but does not translate: a stroke
        width, a mark's size. The SVG's transform scales these too,
        being a transform on the group rather than on each coordinate in
        it.
        """
        return self.scale * v


class _Approximation(NamedTuple):
    """A draw.io built-in standing in for a symbol draw.io has no
    stencil for.

    ``shape`` is a *built-in* shape name and deliberately never a
    stencil key: the whole hazard this file guards against is a
    reference that silently fails to resolve, and a built-in is compiled
    into draw.io rather than loaded from a file, so it cannot. ``None``
    is draw.io's default rectangle. See :data:`_BUILTIN_SHAPES` for what
    counts as a built-in and why the set is wider than mxGraph's own.

    ``flip_h`` mirrors the built-in, for the one shape whose draw.io
    version points the other way. ``fill`` is the colour the symbol's
    own artwork fills itself with, which for a balloon is opaque white
    and not the transparent default: an ISA balloon is drawn over the
    line it reads and knocks a hole in it, and a transparent one would
    have a process line running across the tag inside it. ``stroke`` and
    ``weight`` are the ink, which is the symbol's own and not always the
    sheet's stencil ink: a pipe tee is *pipe*, drawn black at the
    pipeline's weight, and drawing it at a stencil's ``#111`` hairline
    put a visibly lighter, thinner rule across every junction on the
    sheet. ``lost`` says what the sheet has that the stand-in does not,
    in words, and is the point of the table: an approximation nobody
    wrote down is indistinguishable from a mistake.

    ``inscribed`` is a *second* built-in, drawn inside the first and
    filling the same box, for a symbol that is two outlines rather than
    one. See :meth:`DrawioRenderer._vertex`, which emits it as a child
    of the cell.
    """

    shape: str | None
    lost: str
    flip_h: bool = False
    fill: str = _NO_FILL
    stroke: str = _INK
    weight: float = _SYMBOL_STROKE
    keys: tuple = ()
    inscribed: "str | None" = None


#: The code every ``lost`` sentence is reported under.
#:
#: ``lost`` is written down for each stand-in and was read by nothing:
#: a ``Conveyor`` exported as a bare rectangle, the belt and its two
#: rollers gone, and ``fs.warnings == []``. A stand-in is a deliberate
#: approximation and not an error -- the module docstring's claim is that
#: it is not a *silent* one -- so it is a warning naming the unit and the
#: sentence beside its entry in :data:`_APPROXIMATIONS`.
APPROXIMATED = "drawio-approximated"

#: The codes this backend puts on ``fs.warnings`` itself, as against the
#: validator's findings about the diagram. Replaced rather than added to
#: on each export, the way ``SvgRenderer.render`` replaces its own.
_EXPORT_CODES = (*_FIT_CODES, APPROXIMATED)


#: Every symbol this library draws itself, and what draw.io is asked for
#: instead.
#:
#: These are the fourteen hand-drawn symbols plus the block: draw.io's
#: P&ID library has no stencil for any of them, so there is no key to
#: derive and none is invented. What is here instead is a built-in shape
#: chosen to be the nearest honest statement, with the difference
#: recorded.
#:
#: The balloons are the ones that matter, a P&ID being mostly balloons.
#: Every one keeps its outline -- a circle stays a circle, a diamond a
#: diamond, the computer hexagon a hexagon -- and what goes is the
#: *location* marking layered on it: the bar across a panel balloon, the
#: square around a shared-display one. So an exported balloon says
#: "instrument" correctly and stops saying where the instrument lives.
#: Nothing here is a silent loss; it is a loss with a sentence against
#: it.

#: Opaque, as every balloon's own artwork is: a balloon is drawn over
#: the line it reads and knocks a hole in it, and a transparent one
#: would have that line running through the tag inside it.
_BALLOON_FILL = "#ffffff"

_APPROXIMATIONS = {
    # ISA balloons -----------------------------------------------
    ("instrument", "default"): _Approximation(
        # A circle is a circle: nothing lost.
        "ellipse", "", fill=_BALLOON_FILL),
    ("instrument", "panel"): _Approximation(
        "ellipse", "the bar across the balloon that puts the instrument in a panel",
        fill=_BALLOON_FILL),
    ("instrument", "aux"): _Approximation(
        "ellipse", "the double bar that puts the instrument in an auxiliary panel",
        fill=_BALLOON_FILL),
    ("instrument", "shared"): _Approximation(
        "ellipse", "the square around the balloon that puts the function in a "
                   "shared display, and the bar that puts it in the control room",
        fill=_BALLOON_FILL),
    ("instrument", "computer"): _Approximation(
        # The computer hexagon, drawn as one.
        "hexagon", "", fill=_BALLOON_FILL),
    # A square with a diamond inscribed in it, which is two outlines and
    # so two cells. Nothing lost, so nothing listed. `logic` is the same
    # Symbol under its second name (pandid.render.symbols registers one
    # object twice), so the two entries have to say the same thing or
    # the two spellings would draw differently.
    ("instrument", "sis"): _Approximation(
        None, "", fill=_BALLOON_FILL, inscribed="rhombus"),
    ("instrument", "logic"): _Approximation(
        None, "", fill=_BALLOON_FILL, inscribed="rhombus"),
    ("instrument", "interlock"): _Approximation(
        # A bare diamond, drawn as one.
        "rhombus", "", fill=_BALLOON_FILL),
    # junctions and boundaries -----------------------------------
    # A mixer is a triangle pointing the way the streams combine,
    # which is draw.io's own triangle; a splitter is that triangle
    # turned round, which is that triangle flipped.
    ("mixer", "default"): _Approximation("triangle", ""),
    ("splitter", "default"): _Approximation("triangle", "", flip_h=True),
    # Bare pipe: three runs meeting, with no body at all. **The pipes
    # draw the junction and the cell draws nothing.**
    # :meth:`DrawioRenderer._constraint` lands every stream that meets a
    # tee on the box **centre** rather than on its nozzle, so three
    # edges end on one point: flush by construction, with no tolerance
    # to get wrong, and each leg collinear with its own approach, since
    # a tee's nozzles are the midpoints of three faces and the centre is
    # on the axis of all three. Nothing is lost, so nothing is listed.
    #
    # The cell stays, invisible, because it is what the three edges are
    # *attached* to: a reader who drags the junction takes all three
    # pipes with it, where three floating endpoints would come apart.
    ("tee", "default"): _Approximation(None, "", stroke=_NO_STROKE),
    # An off-page flag is a rectangle with one end drawn to a point, and
    # `offPageConnector` is that polygon exactly -- five points, flat
    # back, no notch (drawio Shapes.js,
    # OffPageConnectorShape.redrawPath). It points south as drawn, so
    # the flag states a `direction` to turn it: `north` for a flag
    # pointing east, `south` for one pointing west. See _BOUNDARY_SHAPE,
    # which has to compute `size` per cell and so cannot live in this
    # table. Not `step`, whose sixth point cuts a chevron notch into the
    # flag's back with no setting that removes it (`fixedSize` is a flag
    # rather than a length).
    ("feed", "default"): _Approximation(None, ""),
    ("product", "default"): _Approximation(None, ""),
    # Built to its belt run rather than scaled to it, so it is written
    # by hand here and not generated. draw.io has "Drier (Roller
    # Conveyor Belt)", which this artwork is adapted from -- but adapted
    # by dropping the drier housing and making the roller spacing a
    # parameter, so referencing it would draw a drier where the sheet
    # has a conveyor. A rectangle is wrong in a way the reader can see.
    ("conveyor", "default"): _Approximation(
        None, "the belt and its two rollers"),
    # Not an approximation at all, and here to say so: a block flow
    # diagram's block is one rectangle, and draw.io's default vertex is
    # one rectangle.
    ("block", "default"): _Approximation(None, ""),
    # A shell with a serpentine tube pass, drawn here because ISO has no
    # tubular-reactor symbol and neither has draw.io's P&ID set: its
    # nearest shape is a heat exchanger, which is a different piece of
    # equipment on a P&ID.
    ("reactor", "tubular"): _Approximation(
        None, "the tube pass inside the shell"),
    # ISO's separating vessel with one group-29 characteristic in it --
    # items 8.3, 8.6 and 8.8, built by composition (see
    # ``SymbolRegistry._register_composed``). The **mark** is not lost:
    # it is emitted as a child cell, as every composed part is. What the
    # rectangle loses is the body's V bottom, and it loses it because
    # draw.io has a stencil for each of these three *complete* but none
    # for the outline underneath them -- and a composed symbol may not
    # name a stencil, which is what stops a body's reference being reused
    # for a body-plus-parts drawing.
    ("separator", "gravity"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    ("separator", "electrostatic"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    ("separator", "electromagnetic"): _Approximation(
        None, "the V bottom the collected phase draws off through"),
    # ISO group 11. The vendored set has no crusher and no mill under any
    # name, and the nearest built-in to a trapezoid is a rectangle: there
    # is no ``trapezoid`` in mxGraph's own shapes or in draw.io's
    # ``Shapes.js``, and naming a *stencil* for it is the silent-miss
    # this whole table exists to avoid. So the mouth-and-throat outline
    # goes, and with it the mark that says which of the two machines this
    # is -- which is why both sentences below name it. The group-29
    # characteristic inside is **not** lost on the nine composed
    # variants: it is emitted as a child cell, as every composed part is.
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
}

#: What draw.io is asked for to draw one ISO 10628-2 supplementary part,
#: for the parts draw.io has no shape of its own for.
#:
#: The ten group-28 agitators are **not** here and want nothing here:
#: draw.io ships ``mxgraph.pid.agitators``, which is those ten items and
#: nothing else, so each part names its own stencil
#: (:attr:`~pandid.render.symbols.OverlayPart.drawio_shape`) and the
#: export draws a real agitator.
#:
#: The other fifteen are stood in for by built-ins, on
#: :data:`_APPROXIMATIONS`' rule and for its reason -- a built-in is
#: compiled into draw.io and so cannot fail to resolve.
#: ``partialRectangle`` earns its place four times over: it draws a
#: rectangle with only the sides it is asked for, which is exactly what a
#: channel-section leg, a support ring, a skirt and a pair of
#: precipitator plates each are.
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
    # 29.4 to 29.14, the eleven marks that say how a machine crushes.
    # Nine of them are combinations of lines, circles and an X that no
    # built-in draws, so they take draw.io's default rectangle and what
    # it gives is the mark's extent -- the same answer 27.7's field of
    # dots takes, and for the same reason.
    (29, "disc"): _Approximation(
        None, "the shaft, its two plates and the arms between them; "
              "the box is the rotor's extent"),
    (29, "crushing"): _Approximation(None, "the X between the box's corners"),
    # A rectangle for the pair rather than an ``ellipse``: one oval
    # filling a box twice as wide as it is tall is a different drawing,
    # not a reduced one, and it would export 29.6 and 29.11 -- which
    # differ only in whether the two wheels overlap -- as the same oval.
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

#: A rough character width and line height for the furniture boxes,
#: which are the only thing here that has to be given a size rather than
#: told one. The drawing itself never needs this: every unit and every
#: waypoint arrives with the geometry the layout engine settled. 6.2 is
#: the width the SVG renderer measures a label's halo with, so the two
#: at least agree with each other.
_CHAR_W, _LINE_H = 6.2, 14.0

#: The size the *drawing* is lettered at: an equipment tag, an
#: instrument's letters, a boundary flag's service name. Twelve, because
#: that is what ``SvgRenderer._draw_unit_labels``,
#: ``_draw_instrument_tag`` and ``_draw_boundary`` all set, and a sheet
#: exported at a different size from the one it renders at is two
#: drawings. A line number's size is the sheet's
#: :data:`~pandid.render.svg.NUMBER_TYPE`, imported rather than
#: repeated: it is the one number both backends letter the same string
#: with.
_TAG_TYPE = 12.0


class _Tags(NamedTuple):
    """The sheet's equipment-tag pass, which this exporter had never
    run.

    ``at`` is where each unit's tag ended up, by ``id(unit)``: the side
    it settled on and how far along that side it was stepped, in
    **drawing** units. ``plates`` is the opaque white rectangle each of
    those tags lays on the paper -- the tag itself, and the ``NC`` and
    fail-position letters that go in the corners beside it.

    ``plates`` is the point. :func:`~pandid.render.svg.stream_numbers`
    takes the plates already on the sheet as its seed and steps a line
    number clear of them; an exporter passing ``[]`` gets that
    function's documented caveat -- "a placement that dodges every
    symbol and every line but may still land under a tag". Over the
    fourteen examples that is seventeen numbers on four sheets, nine of
    them on ``11_ethanol_pid``, six on ``14_tank_farm`` and one each on
    ``09_line_numbers`` and ``13_mineral_dewatering``. Each strikes its
    tag, which is enough to lose it, and the sheet writes none of them
    there.

    ``codes`` is every letter code written *outside* a balloon, placed:
    :func:`~pandid.render.svg.quadrant_labels`' own items. They are a
    third thing here because they are a third thing on the sheet -- a
    code is neither a unit's label nor a line's, so nothing in this
    exporter carried one and six alarms went out of ``11_ethanol_pid``
    unlettered. See :func:`_quadrant_cell`.
    """
    at: dict
    plates: list
    codes: list


def _tag_pass(fs, registry, joints=None) -> "_Tags":
    """Run the sheet's equipment-tag placement, without drawing
    anything.

    :meth:`SvgRenderer._tag_item` is the search and it is called here
    rather than re-derived, for the reason
    :func:`~pandid.render.furniture.dock` and
    :func:`~pandid.render.svg.stream_numbers` are: a second
    implementation of a *search* does not drift, it answers differently
    on the first crowded corridor. What is repeated is only the walk
    over the units, which is fused into ``SvgRenderer._draw_units`` with
    the drawing of them and so cannot be called on its own; the three
    placements it dispatches to (:meth:`~SvgRenderer._tag_item`,
    :meth:`~SvgRenderer._nc_label_item`,
    :meth:`~SvgRenderer._fail_label_item`) and the halo each lands on
    (``_unit_label_box``) are the sheet's own.

    The text goes through :func:`~pandid.render.escape.escaped` before
    it is measured because the sheet measures the escaped string --
    ``_unit_label_box`` sizes a halo from ``len(text)``, and an
    ampersand in a tag is five characters to it. The same function as
    the sheet's, so the two passes measure the same string.

    Three kinds of unit are skipped, and each for the reason the sheet
    skips it: an instrument writes its tag *inside* its balloon, so
    there is no halo; a boundary flag writes its service name inside the
    pennant, likewise; and a unit with no tag -- the pipe tee is the
    only one today -- is labelled nowhere at all.
    """
    from pandid.render.svg import (SvgRenderer, _ink, _unit_label_box,
                                   flange_boxes, quadrant_labels)

    sheet = SvgRenderer(registry)
    ink = _ink(fs)
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    # ``joints`` is the sheet's answer about its connections, and it is
    # threaded in for the same reason ``ink`` is: on a flanged sheet the
    # marks are ink the tag has to step off, and a pass told about the
    # lines and the symbols but not about those places one tag here and
    # another one there. See :func:`~pandid.render.svg.flange_boxes`.
    # ``None`` on a sheet that marks no joints, and then this adds
    # nothing.
    symbols += [(None, b) for b in flange_boxes(fs, joints)]
    # A letter code outside a balloon is placed before either label pass
    # runs, so both are told where it went; ``SvgRenderer._draw_units``
    # seeds itself with the same boxes and this pass has to see the same
    # paper taken, or the two settle a crowded tag on different sides.
    codes = quadrant_labels(fs)
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
            # The side, and the step along it, said the way a draw.io
            # style has to say it: `_LABEL_SIDE` states the side and the
            # geometry offset states the step, so the step is measured
            # against where that same side would have put the tag
            # untouched.
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
    """One letter code written outside a balloon, as a text cell.

    ``item`` is :func:`~pandid.render.svg.quadrant_labels`' own, so the
    code is exported into the quadrant the sheet drew it in rather than
    into a second opinion about where ISO 15519-2 §5.1.3 puts it.

    A cell of its own because a draw.io cell carries **one** label and
    the balloon's is its tag. The anchor becomes a box and an ``align``
    the way :func:`_strip_label` makes one -- see :data:`_TEXT_INSET` --
    and ``labelBackgroundColor`` is the halo the sheet letters a code
    on; see :data:`_NUMBER_KEYS`.

    The text arrives escaped, the sheet having written it into SVG, and
    :func:`_attr` escapes what it is handed: unescaped here so that it
    is escaped exactly once.
    """
    import html as _html

    lx, ly, anchor, _baseline, _lpos, text = item
    value = _html.unescape(text)
    size = fit.length(_TAG_TYPE)
    x, y = fit.at(lx, ly)
    box_w = F.text_width(value, size) + 2 * _TEXT_INSET
    box_h = _line_box(size) + 2 * _TEXT_INSET
    left, align = ((x + _TEXT_INSET - box_w, "right") if anchor == "end"
                   else (x - _TEXT_INSET, "left"))
    style = ("text;html=1;strokeColor=none;fillColor=none;"
             f"labelBackgroundColor=#ffffff;align={align};"
             f"verticalAlign=middle;fontSize={size:g};fontColor={_LINE_INK};")
    return [
        f'        <mxCell id="{cid}" value={_attr(value)} style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(left)}" y="{_num(y - box_h / 2)}" '
        f'width="{_num(box_w)}" height="{_num(box_h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _drawn_type(nominal: float, fit: "_Fit", *, lines: int = 1, box=None) -> str:
    """The ``fontSize`` key for a piece of lettering **in the drawing**.

    Two things happen to it that do not happen to a piece of furniture.

    **It scales.** ``page_size`` makes the export a sheet, and the
    drawing is then fitted into whatever the furniture leaves. On the
    rendered sheet that fitting is one ``<g transform="scale(s)">``
    around the whole drawing, and a ``font-size="12"`` inside it comes
    out at ``12 s``. draw.io has no such group -- :class:`_Fit`
    multiplies every coordinate on the way out instead -- so the type
    has to be multiplied with them or the sheet's own proportion between
    a symbol and the tag beside it is lost. On ``11_ethanol_pid`` the
    ratio is 0,76, a third again too much ink on every label.

    **It is capped where it is written *inside* the shape.** A boundary
    flag and an ISA balloon carry their text in the cell, so ``lines``
    of it at :data:`_LINE_BOX` each have to fit ``box``'s depth. Nothing
    in mxGraph shrinks type to fit -- see :data:`_LINE_BOX` -- so a
    label too tall for its cell is drawn across the shape's top and
    bottom edges, and with ``overflow=hidden`` cut there: two lines of
    12 need 28,8 in a pennant 26 deep.

    ``box`` is in **drawing** units, since
    :meth:`DrawioRenderer._cell_box` is, so the cap is taken there and
    the fit applied to the answer.
    """
    size = nominal
    if box is not None and lines > 0:
        depth = abs(box[3] - box[1])
        size = min(size, depth / (lines * _LINE_BOX))
    return f"fontSize={fit.length(size):g}"


def _attr(value) -> str:
    """One XML attribute value, quoted and escaped.

    Written out rather than reached for in the standard library because
    the escaping has to be exactly this: draw.io reads a cell's
    ``value`` as *HTML*, so a ``<br>`` between an instrument's letters
    and its number has to arrive at the HTML parser as a tag, which
    means leaving this function as ``&lt;br&gt;`` and no further.
    Escaping the five and only the five is what does that.

    What it does share with :func:`~pandid.render.escape.escaped` is the
    removal first. A character XML 1.0 §2.2 has no spelling for -- a
    ``NUL`` in a tag read out of a spec file -- cannot be escaped into
    legality by any of the five substitutions, and one of them in one
    attribute makes the whole document unreadable to draw.io.
    """
    text = writable(value)
    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                         ('"', "&quot;"), ("'", "&apos;")):
        text = text.replace(char, entity)
    return f'"{text}"'


def _num(v: float) -> str:
    """A coordinate, at the precision draw.io files are written to.

    Two decimals: the drawing unit is a CSS pixel, so this is a
    hundredth of a pixel, and rounding is what keeps the file diffable
    against the last export instead of churning in the sixteenth digit.
    """
    return f"{round(float(v), 2):g}"


def _dash(pattern: str) -> list[str]:
    """A stroke dash, as draw.io states one, or nothing for a solid
    line.

    Two things about the translation are not obvious and both come from
    ``mxSvgCanvas2D.createDashPattern``.

    The separator is a **space**: mxGraph splits the pattern on ``' '``
    and runs each part through ``Number()``, so a comma survives into
    ``Number("5,4")``, comes back ``NaN``, and takes the whole pattern
    with it. SVG writes the same pattern with commas, which is why this
    is a translation rather than a copy.

    ``fixDash=1`` is what makes the numbers mean what they say. Without
    it draw.io multiplies every length by the **stroke width** --
    ``stroke-dasharray = pattern x strokeWidth x scale`` -- so a dash
    written for a 1-unit signal line comes out twice as long on a 2-unit
    process line. With it the multiplier is 1 and the numbers are
    drawing units, as they are everywhere else in this library.
    """
    if not pattern:
        return []
    return ["dashed=1", f"dashPattern={pattern.replace(',', ' ')}", "fixDash=1"]


def _fraction(v: float) -> str:
    """A connection point, as draw.io writes one: a fraction of the
    cell's box.

    Six figures rather than two, because this one is multiplied by a box
    that may be two hundred units across before it becomes a coordinate.
    """
    return f"{round(float(v), 6):g}"


class DrawioRenderer:
    """Renders a Flowsheet to a draw.io ``mxfile`` document.

    Satisfies :class:`pandid.render.Renderer`, so it is a backend beside
    :class:`~pandid.render.svg.SvgRenderer` rather than a converter
    bolted onto one. It reads the same resolved geometry the SVG
    renderer reads -- frames from layout, waypoints from routing, port
    points from :mod:`pandid.portgeom` -- and never re-derives any of
    it, which is what lets the two agree to the pixel.
    """

    def __init__(self, registry=None):
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry
        # What this export could not carry across, collected as it is
        # written and handed to the flowsheet at the end of
        # :meth:`render`. A list rather than a callback because the
        # methods that find these are deep in the cell writers and a
        # renderer is built fresh for each render
        # (:meth:`~pandid.flowsheet.Flowsheet.to_drawio`).
        self._findings: list = []

    def _report(self, field: str, text: str, drawn: str) -> None:
        """A cell that could not hold what it was given
        (:data:`~pandid.render.furniture.Reporter`).

        The same sentence the sheet's own renderer produces, from the
        same function: the two backends measure one strip with one set of
        cell widths, so which file was exported must not change what the
        author is told about it.
        """
        self._findings.append(fit_issue(field, text, drawn))

    # --------------------------------------------------- document

    def render(self, fs: "Flowsheet", *, diagram: "str | None" = None,
               page_size: "str | None" = None, border: "str | None" = None,
               connections: "str | None" = None,
               jump_direction: str = "vertical",
               show_stream_table: bool = False, **opts) -> str:
        """Render the flowsheet to a draw.io document.

        ``diagram`` says which drawing this is, in the spelling
        :meth:`~pandid.flowsheet.Flowsheet.to_svg` takes it: a P&ID
        draws its process lines without arrowheads and so exports them
        without one.

        ``page_size`` puts the model on **paper**. Without it the
        drawing keeps its own coordinates and the furniture docks to its
        own bounds, which is what a model is; with it the file carries
        the page draw.io is to rule, the furniture docks to that page
        instead, and the drawing is fitted into what the furniture
        leaves -- the same three things :meth:`SvgRenderer.render` does
        with the same argument, so the two open at the same size on the
        same paper.

        What it does **not** decide is whether the file states a page
        size at all. It always does, because draw.io does not offer a
        document the option of having none: a file that states no size
        is not read as unpaged, it is read as being on whatever paper
        the reader's locale defaults to, and PDF export then bounds the
        drawing by that. The long note beside the ``paper`` attributes
        below is the evidence, and :meth:`_page_box` is the size.

        ``border`` rules that page. ``"zone"`` draws the frame, the
        sheet edge and the lettered band between them; ``"none"`` leaves
        the page's own edge to be the paper's, which is what the sheet
        does too -- an unruled sheet draws no rectangle, it just stops.

        ``jump_direction`` says which of two crossing lines hops the
        other, and means what it means on the sheet: ``"vertical"`` puts
        the semicircle on the vertical runs. It reaches draw.io as a
        style key on the hopping edges *and* as the order those edges
        are written in, since z-order is what breaks the tie. See
        :func:`_hops`.

        ``show_stream_table`` docks the stream property table at the
        foot of the sheet and rules it as the grid it is, exactly as
        :meth:`SvgRenderer .render` does with the same argument: both
        backends measure it with
        :func:`~pandid.render.furniture.stream_table_layout`, so the
        columns are the same columns and the section headings fall in
        the same places.

        The debug overlay remains refused. It is scaffolding for whoever
        is writing a placement rather than part of the drawing.
        """
        from pandid.render.svg import _page, _resolve_sheet

        arrows = draws_arrowheads(diagram)
        self._findings = []
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")
        border, _diagram = _resolve_sheet(border, diagram)
        sheet = _page(page_size)

        body: list[str] = []
        # Sheet furniture first: a later cell draws over an earlier one,
        # and the boxes are behind the drawing on the sheet. The border
        # is behind even those, which is the order _place_furniture
        # splices it in at.
        furniture, frame, fit = self._furniture(fs, sheet, show_stream_table)
        body.extend(self._border(frame, border))
        body.extend(furniture)
        # Then equipment, then the runs between it, then the balloons --
        # which is the SVG renderer's own order, and it is that order
        # for the same reason: a balloon's opaque body knocks out the
        # line an in-line element straddles, and a cell drawn earlier is
        # a cell drawn under.
        #
        # That leaves an edge to a balloon naming a cell that appears
        # later in the file, which the format allows: an mxCell's
        # ``source``/``target`` is a reference resolved by id over the
        # whole document, not a back-pointer into what has been read so
        # far. It has to be, since z-order *is* cell order and draw.io
        # lets a user send an edge behind the shapes it joins. The
        # sheet's equipment-tag pass, run once: it settles where every
        # tag lands *and* hands the line-number search the plates it has
        # to step clear of. See :class:`_Tags`.
        joints = sheet_connections(diagram, connections)
        tags = _tag_pass(fs, self.registry, joints)
        balloons: list[str] = []
        for i, u in enumerate(fs.units):
            (balloons if u.kind == "instrument" else body).extend(
                self._vertex(u, i, fit, tags))
        body.extend(self._edges(fs, arrows, fit, tags, jump_direction, joints))
        # Instrumentation goes on over the lines, as it does on the
        # sheet: the tap runs from the plant to the balloon and the
        # balloon's opaque body then knocks out both it and any process
        # line an in-line element straddles. Same three passes, same
        # order, same reason.
        body.extend(self._taps(fs, fit))
        body.extend(balloons)
        # The codes lettered outside the balloons go on last, over
        # everything, exactly as `_draw_unit_labels` puts them on the
        # sheet: a code is written on paper the search cleared for it,
        # and it is haloed for the lines it could not clear.
        for n, code in enumerate(tags.codes):
            body.extend(_quadrant_cell(f"q{n}", code, fit))

        # **The page and the page *view* are two separate statements.**
        # Function names are the anchors below; both repositories move.
        #
        # **The size is never optional.**
        # `Editor.prototype.readGraphState` (drawio,
        # js/grapheditor/Editor.js) parses pageWidth/pageHeight into
        # `graph.pageFormat` and, when either is absent, has no `else`
        # branch at all: the format keeps whatever `resetGraph` left,
        # which is `mxGraph.prototype.pageFormat`. That is not "no page"
        # and not reliably A4 either -- js/grapheditor/Graph.js sets it
        # by locale, A4 portrait 827x1169 everywhere except
        # en-us/en-ca/es-mx, which get US Letter 850x1100. So a file
        # stating no size opens on whatever paper the *reader's* machine
        # picks, and is a different document in Brisbane and in Houston.
        #
        # **And the size is what bounds a PDF.** The headless renderer
        # both drawio-desktop and the export server run (js/export.js,
        # `renderPage`) sets `graph.pdfPageVisible = !imagePageVisible`
        # for every PDF export, whatever `page` says, and then bounds
        # the export by `graph.view.getBackgroundPageBounds()`, which
        # snaps outward to a whole number of page tiles: a
        # 1950-unit-wide drawing against an 827-wide default tile comes
        # back as a 3x1 grid cut across the joins. PNG and SVG are
        # unaffected -- `Graph.prototype.getSvg` resolves the default
        # exportType='diagram' to `getGraphBounds()`, the drawing's own
        # extent. So the size is stated either way, and what is stated
        # is the sheet the SVG backend would have drawn: see
        # :meth:`_page_box`.
        #
        # **The page view is the separate question**, and
        # `readGraphState` spends `page` on `graph.pageVisible` and
        # `pageBreaksVisible` -- editor chrome -- and on nothing about
        # `pageFormat`. A model with no paper has no page to rule, so
        # page="0" is the true thing for it to say, and it is also what
        # makes such a model export whole: `renderPage` sets
        # `autoOrigin` when `page` is not "1", which mxPrintPreview
        # documents as "Specifies if the origin should be automatically
        # computed based on the top, left corner of the actual diagram
        # contents". An unpaged export keeps the drawing's own
        # coordinates and those routinely run left of or above zero
        # (`12_block_flow_diagram`'s frame starts at x = -34,
        # `03_distillation_train`'s at y = -165), so anchored at zero
        # each would lose its left or top edge to the tile before it. A
        # fixed page is the opposite case on both counts: there *is*
        # paper and every coordinate already lies within [0, sheet].
        #
        # **pageScale stays 1 and stays stated.** drawio's own default
        # is 1, but it reaches it by overriding
        # `mxGraph.prototype.pageScale`, which is 1.5. Nothing else is
        # needed to stop a re-fit: every rescaling path in the sources
        # is driven by a request parameter or a checkbox rather than by
        # any attribute a document carries. `math` would matter -- the
        # diagramly `getSvg` force-typesets before measuring when it is
        # on -- and is off here.
        page_w, page_h = self._page_box(sheet, frame)
        paper = (f'page="{0 if sheet is None else 1}" pageScale="1" '
                 f'pageWidth="{_num(page_w)}" pageHeight="{_num(page_h)}"')
        # A stable page id, so exporting the same flowsheet twice gives
        # the same file. draw.io generates a random one; a random one
        # here would make every re-export a diff of one line that means
        # nothing.
        page = hashlib.sha256(fs.name.encode("utf-8")).hexdigest()[:16]
        # What this export could not carry across joins the validator's
        # findings, exactly as ``SvgRenderer.render`` puts the sheet's
        # there: one list, whichever document was asked for. Findings
        # from an earlier export are dropped rather than added to -- a
        # drawing number shortened and re-exported must stop warning
        # about the old one.
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _EXPORT_CODES] + self._findings
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            # ``agent`` is where draw.io writes the user-agent string of
            # whatever produced the file, so it is where the version
            # belongs; ``host`` stays the bare application name, which
            # is what it names. A bare ``agent="pandid"`` could not tell
            # 0.1.0 output from 0.1.2 output, which is the whole
            # complaint.
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
        """The cell id for the unit at ``index`` in ``fs.units``.

        Derived from the position rather than from the tag: a tag
        repeats (a trip square is one piece of logic drawn wherever it
        acts), and two cells under one id is a file draw.io reads as one
        cell. ``0`` and ``1`` are the model's own root cells, which is
        what the prefix keeps clear of.
        """
        return f"u{index}"

    @staticmethod
    def _approximation(u, sym) -> "_Approximation | None":
        """The stand-in for a unit draw.io has no stencil for, or None.

        None for every vendored symbol, which is the great majority, and
        for a kind with no artwork at all -- a
        :class:`~pandid.units.Unit` subclass from outside this package,
        which draws a generic box on the sheet and gets draw.io's
        default vertex here, the same statement either way.

        A **composition** whose body was vendored is in the first case,
        not the second: it carries the body's reference under
        :attr:`~pandid.render.symbols.Symbol.drawio_body_shape`, the
        body's stencil draws the outline, and the parts are child cells
        (:meth:`_overlay_cells`). One whose body was drawn here falls
        through to the table like any other hand-drawn symbol.
        """
        if sym.drawio_shape or sym.drawio_body_shape:
            return None
        return _APPROXIMATIONS.get((u.kind, getattr(u, "variant", "default")))

    def _placement(self, u, sym) -> "tuple[list[str], bool, bool]":
        """The style keys that place a symbol, and the flips they came
        out as.

        The flips come back with the keys because the connection points
        below have to be stated in a frame draw.io will then flip, so
        the two have to be worked out together or they disagree about
        which side of the box a nozzle is on.

        A **directional** symbol takes no flip at all, and that is not
        an omission. Its artwork *is* a statement of direction -- a
        cooler is the heater's circle and zigzag with the arrowhead at
        the other end of the diagonal, and nothing else tells the two
        apart -- so the SVG renderer holds the drawing still under a
        flip and lets only the nozzles move
        (:func:`pandid.render.svg._upright_artwork`). Flipping the
        draw.io shape would draw the sibling symbol and say the opposite
        thing about which way the heat goes. The nozzles still move,
        because they are stated as coordinates below and not inferred
        from the shape.
        """
        f = u.frame
        if u.kind in ("feed", "product"):
            # A flag states its whole placement in :meth:`_flag_shape`:
            # it is never turned (the sheet does not turn one either)
            # and its mirror is a `direction` rather than a flip, since
            # the shape it is drawn with already points a quarter away
            # from where it is wanted.
            return [], False, False
        rot = int(getattr(f, "orientation", 0) or 0)
        keys = []
        if rot in _DIRECTION:
            # anchorPointDirection=0 rides with the turn and only with
            # it: it stops draw.io turning this cell's connection points
            # along with the shape, which it only ever would for a cell
            # that states a direction. A *vertex* key -- mxGraph reads
            # it off the shape being connected to, not off the edge --
            # and :meth:`_constraint` is where it is wanted.
            #
            # legacyAnchorPoints=1 pins *which* of draw.io's two anchor
            # algorithms honours it. Every fraction this file writes is
            # a fraction of the box *as placed*, so only the legacy one
            # is right, and relying on its being the default is a nozzle
            # that moves when draw.io changes its mind.
            keys += [f"direction={_DIRECTION[rot]}", "anchorPointDirection=0",
                     "legacyAnchorPoints=1"]
        if sym.directional:
            flip_h, flip_v = False, False
        else:
            flip_h, flip_v = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        # A fitting turned end for end draws its stencil mirrored, and a
        # left-pointing splitter draws draw.io's own triangle mirrored.
        # Both are the *drawing* differing from the shape being named
        # rather than anything the author asked for, so both compose
        # with the placement instead of overriding it -- and both are
        # folded in here, in the one place, because :meth:`_constraint`
        # has to state its fractions in a frame draw.io will then flip
        # and would otherwise be answering from a different sum.
        approx = self._approximation(u, sym)
        if sym.drawio_flip_h or (approx is not None and approx.flip_h):
            flip_h = not flip_h
        if flip_h:
            keys.append("flipH=1")
        if flip_v:
            keys.append("flipV=1")
        return keys, flip_h, flip_v

    def _shape(self, u, sym, fit: "_Fit") -> list[str]:
        """The style keys naming what draw.io is to draw for this unit.

        ``fit`` is here for the pen. A symbol's outline is a **drawing**
        dimension, so it scales with the drawing exactly as a pipe's
        does (:class:`_Fit`), and stating it unscaled beside a stream
        stated scaled would put the two back out of proportion at the
        other end.
        """
        weight = f"strokeWidth={fit.length(_SYMBOL_STROKE):g}"
        if u.kind in ("feed", "product"):
            return self._flag_shape(u, fit)
        # A composition names no stencil of its own -- that is what stops
        # a body's reference being reused for a body-plus-parts drawing,
        # which would export a stirred tank as a bare vessel. What it does
        # carry is the stencil that draws its *body*, and that one is true
        # of the cell this method is styling, because the parts get cells
        # of their own beside it (:meth:`_overlay_cells`).
        stencil = sym.drawio_shape or sym.drawio_body_shape
        if stencil:
            # A vendored stencil: name it and let draw.io draw its own
            # artwork. `outlineConnect=0` is what draw.io's own P&ID
            # palette sets, and it matters here more than there: it
            # stops a stream being dropped onto the shape's outline
            # instead of onto the nozzle it was routed to.
            #
            # And the pen, which was not being written at all. Every
            # vendored stencil declares `strokewidth="inherit"`, which
            # is a stencil saying "take the pen from the cell" -- and
            # the cell said nothing, so draw.io's default 1 drew every
            # symbol lighter than the pipes around it. See
            # :data:`_SYMBOL_STROKE`.
            keys = [f"shape={stencil}", "outlineConnect=0",
                    f"strokeColor={_INK}", f"fillColor={sym.drawio_fill or _PAPER}",
                    weight]
            return keys
        # The stand-in, or draw.io's default vertex. Its mirror, where
        # it needs one, is applied in :meth:`_placement` with everything
        # else that flips.
        approx = self._approximation(u, sym)
        shape = approx.shape if approx is not None else None
        keys = [] if shape is None else [f"shape={shape}"]
        keys += ["rounded=0", "whiteSpace=wrap"]
        if approx is None:
            # A kind with no artwork at all: the sheet draws
            # `_generic_symbol`'s 60-unit box, ruled at the same weight
            # everything else is.
            return keys + [f"strokeColor={_INK}", f"fillColor={_NO_FILL}", weight]
        return keys + [*approx.keys, f"strokeColor={approx.stroke}",
                       f"fillColor={approx.fill}",
                       f"strokeWidth={fit.length(approx.weight):g}"]

    @staticmethod
    def _flag_shape(u, fit: "_Fit") -> list[str]:
        """The off-page flag, as draw.io's own five-point connector
        polygon.

        ``offPageConnector`` draws ``(0,0) (w,0) (w,h-s) (w/2,h)
        (0,h-s)``: a rectangle with one end drawn to a point,
        flat-backed, which is the pennant
        :func:`~pandid.render.svg.boundary_flag` describes. It points
        *south*, so it is turned a quarter: mxShape adds 270 degrees for
        ``direction=north`` and swaps the painting box's width and
        height first, which lands the tip on the middle of the east edge
        and leaves the cell's own bounding box alone. ``south`` is the
        same shape turned the other way, tip west, which is a mirrored
        flag.

        ``size`` is a *fraction of the shape's own height*, and that
        height is the cell's **width** after the quarter turn, so the
        fifteen units the sheet cuts the point back by is fifteen over
        the width of this particular flag rather than a constant.

        The two anchor keys are here because ``direction`` is: draw.io
        resolves a fixed connection point against bounds it rotates by
        90 for a north or south direction, which would take every
        fraction against a transposed rectangle.
        ``anchorPointDirection=0`` is what stops that, and
        ``legacyAnchorPoints=1`` pins *which* of draw.io's two anchor
        algorithms honours it -- the legacy one, which is the default,
        is the one in which ``anchorPointDirection=0`` suppresses the
        bounds swap as well as the rotation. Saying so is cheap and the
        alternative is a file whose nozzles depend on a default.
        """
        (x0, _, x1, _), depth, east = boundary_flag(u, u.frame)
        width = x1 - x0
        size = (depth / width) if width else 0.375
        return ["shape=offPageConnector", f"size={_fraction(min(1.0, size))}",
                f"direction={'north' if east else 'south'}",
                "anchorPointDirection=0", "legacyAnchorPoints=1",
                "rounded=0", "whiteSpace=wrap",
                f"strokeColor={_LINE_INK}", f"fillColor={_NO_FILL}",
                # The pennant is a symbol outline and is ruled like one,
                # and like one it scales with the drawing. It was stated
                # flat here, which on a paged sheet drew the flag
                # heavier than the pipe running into it.
                f"strokeWidth={fit.length(_SYMBOL_STROKE):g}"]

    def _label(self, u, fit: "_Fit", tags: "_Tags") -> "tuple[str, list[str], tuple]":
        """A unit's label text, the style keys that place it, and how
        far the sheet stepped it off that side.

        An instrument's tag goes *inside* its balloon, letters over
        number, which is where a sheet writes it and where draw.io's
        default centred label puts it. Everything else is labelled on
        the side the sheet settles on -- which is
        :func:`pandid.layout.coordinates.assign_labels`' choice and then
        :meth:`SvgRenderer._tag_item`'s, because a face with no nozzle
        on it is not yet free paper. See :meth:`_tag_placement`.

        Two markings ride along on the label because they have nowhere
        else to go: ``NC`` for a valve declared normally closed whose
        body cannot carry the darkening, and the fail-position letters.
        The renderer places both as small labels of their own against
        the corner of the symbol; there is no second label on a draw.io
        cell, so they follow the tag rather than being dropped.

        ``fit`` is here because every one of these is lettering **in the
        drawing**, and the drawing is scaled. See :func:`_drawn_type`.
        """
        from pandid.units import split_tag

        if u.kind == "instrument":
            letters, number = split_tag(getattr(u, "type", "") or u.tag,
                                        getattr(u, "number", "") or "")
            # A diamond carries the number alone, as the sheet draws it:
            # its letters are only the tag prefix and there is no room
            # under them.
            if getattr(u, "variant", "default") in _DIAMOND_BALLOONS:
                parts = [number or letters.upper()]
            else:
                parts = [letters.upper(), number]
            parts = [part for part in parts if part]
            text = "<br>".join(parts)
            # A balloon's tag is written inside the balloon, so its type
            # is capped to what the balloon holds. The sheet sets the
            # letters at 12 and the number at 11 and a draw.io label has
            # one size for the whole of it, so the pair goes out at the
            # larger of the two -- the letters are what a reader picks
            # the loop out by.
            return text, ["verticalLabelPosition=middle", "verticalAlign=middle",
                          "align=center",
                          _drawn_type(_TAG_TYPE, fit, lines=len(parts),
                                      box=self._cell_box(u))], (0.0, 0.0)

        lines = [u.tag] if u.tag else []
        if u.kind in ("feed", "product"):
            reference = getattr(u, "reference", "") or ""
            if reference:
                lines.append(reference)
            # Inside the flag, over the off-page reference, which is
            # where the sheet writes it: a boundary flag's label *is*
            # its content (:meth:`SvgRenderer._draw_boundary`).
            #
            # Centred on the cell, where the sheet centres it on the
            # *flat* part of the pennant -- half the point's depth to
            # the blunt end of the difference, under four units on a
            # flag eighty wide. There is no key that says "centre me in
            # the shape minus its point".
            #
            # The type is capped to the pennant, which a side label does
            # not need: a flag carrying an off-page reference is 26
            # units deep and two lines at the sheet's own 12 want 28,8
            # of draw.io's line box, so the pair is set a shade smaller
            # rather than laid across the pennant's edges. The sheet
            # does not have to make that trade -- it sets the reference
            # at 10,5 on a baseline of its own -- and a draw.io label
            # has one size and one line height for the whole of it.
            return "<br>".join(lines), _LABEL_SIDE["center"] + [
                _drawn_type(_TAG_TYPE, fit, lines=len(lines),
                            box=self._cell_box(u))], (0.0, 0.0)
        if closed_marking(u, self.registry) == "NC":
            lines.append("NC")
        letters = fail_marking(u)
        if letters:
            lines.append(letters)
        side, dx, dy = tags.at.get(id(u), (
            (u.frame.label_pos or "top") if u.frame is not None else "top", 0.0, 0.0))
        # No cap: a tag on a side of a symbol is written on the paper
        # beside it, not in the cell, so there is no box for it to
        # overflow. `_LABEL_SIDE` gives the label its own box outside
        # the cell and mxGraph draws it at whatever size it is told
        # (`mxGraphView.updateVertexLabelOffset`).
        return "<br>".join(lines), _LABEL_SIDE.get(side, _LABEL_SIDE["top"]) + [
            _drawn_type(_TAG_TYPE, fit)], (fit.length(dx), fit.length(dy))

    @staticmethod
    def _cell_box(u) -> "tuple[float, float, float, float]":
        """The rectangle draw.io is handed for this unit.

        :func:`~pandid.portgeom.unit_box` for everything with artwork
        that fills its box, which is everything drawn from a stencil:
        draw.io stretches a ``variable`` stencil into the cell exactly
        as :func:`~pandid.portgeom.ink_box` stretches the symbol into
        the frame, so the box *is* the mapping.

        An off-page flag is the one thing that is drawn smaller than its
        box. Its pennant fills the box left to right and is inset twelve
        or fifteen units top and bottom
        (:func:`~pandid.render.svg.boundary_flag`), so handing draw.io
        the whole 50-unit box would draw a flag twice the height the
        sheet rules one at. The cell is the pennant, which is also what
        makes the connection points below come out right: a fraction is
        a fraction of *this* rectangle, and the port sits on the middle
        of the pennant's end rather than halfway down a box the drawing
        does not reach the bottom of.
        """
        if u.kind in ("feed", "product"):
            return boundary_flag(u, u.frame).box
        return unit_box(u, u.frame)

    def _vertex(self, u, index: int, fit: "_Fit", tags: "_Tags") -> list[str]:
        """One unit, as a draw.io vertex.

        The ``<mxPoint as="offset">`` is how far the sheet stepped this
        unit's tag along the side it settled on.
        ``mxGraphView.updateCellState`` reads a *vertex* geometry's
        offset into ``state.absoluteOffset``, and
        ``mxCellRenderer.getLabelBounds`` starts its non-edge branch
        from exactly that -- so it displaces the label and leaves the
        cell alone, which is what a tag stepping clear of somebody
        else's line is.

        A symbol that is **two outlines** gets a second cell, inscribed
        in the first: see :meth:`_inscribed`. A **composed** symbol gets
        one cell per supplementary part: see :meth:`_overlay_cells`.
        """
        sym = self.registry.for_unit(u)
        approx = self._approximation(u, sym)
        if approx is not None and approx.lost:
            # A stand-in with nothing in its ``lost`` sentence loses
            # nothing -- a ring support really is three sides of a
            # rectangle -- so only the ones that do are reported.
            self._findings.append(Issue(
                "warning", APPROXIMATED,
                f"{u.name} has no draw.io stencil and is exported as a stand-in, "
                f"which loses {approx.lost}"))
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
            *self._overlay_cells(cid, sym, x1 - x0, y1 - y0, fit, u.name),
        ]

    def _overlay_cells(self, cid: str, sym, w: float, h: float,
                       fit: "_Fit", owner: str = "") -> list[str]:
        """One cell per ISO supplementary part, grouped under the body's.

        **This is what a composed symbol exports as.** A composition names
        no stencil (:func:`pandid.render.symbols.compose` clears it),
        because a stencil reference names *one* shape and draw.io draws
        whatever that name resolves to -- so a stirred tank exported under
        the vessel's own reference would come out a bare vessel, the right
        outline with the thing that made it a reactor silently gone.
        Instead the cell above draws the body and each part gets a cell of
        its own inside it.

        The geometry is the composition's own arithmetic, unchanged: an
        :class:`~pandid.render.symbols.Overlay` states its rectangle as
        **fractions of the body's box**, a child's geometry is relative to
        its parent's, and the parent's box *is* the body's box -- so
        multiplying the four fractions by the cell's width and height is
        the whole conversion, and the two backends place a part by one set
        of numbers. ``tests/test_drawio.py`` measures that against the SVG.

        The pair holds together under editing for the reasons
        :meth:`_inscribed` sets out: a child moves with its parent and
        ``Graph.isRecursiveVertexResize`` scales it with its parent, so a
        reader who drags or resizes a column takes its trays with it.
        ``connectable=0`` keeps a stream from landing on a tray instead of
        on the nozzle it was routed to, and ``movable=0`` keeps a reader
        who grabs the middle of a vessel from dragging its agitator out of
        it.

        The pen is the part's and not the body's: ISO 10628-1 §5.3.1 puts
        an outline at 0,5 mm and the detail inside it at 0,25, and the
        sheet draws them at exactly that ratio (:data:`_PART_STROKE`).
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
                    # The body's rule, one level down: a part stood in
                    # for by a built-in that does not draw all of it
                    # says so, naming the unit it is drawn on.
                    self._findings.append(Issue(
                        "warning", APPROXIMATED,
                        f"{owner or cid}: the {overlay.name} part has no draw.io "
                        f"stencil and is exported as a stand-in, which loses "
                        f"{approx.lost}"))
            # A chiral part's second hand. The SVG reflects the artwork
            # about its rectangle's own centre line and so does this: the
            # child's box is the same box either way, and only what is
            # drawn inside it turns round.
            if overlay.mirror:
                keys.append("flipH=1")
            style = ";".join([
                "html=1", "rounded=0", *keys,
                f"strokeColor={_INK}", f"fillColor={_NO_FILL}",
                f"strokeWidth={fit.length(_PART_STROKE):g}",
                "connectable=0", "movable=0"]) + ";"
            out += [
                f'        <mxCell id="{cid}-p{i}" value="" style={_attr(style)} '
                f'vertex="1" parent="{cid}">',
                f'          <mxGeometry x="{_num(overlay.x * w)}" '
                f'y="{_num(overlay.y * h)}" width="{_num(overlay.w * w)}" '
                f'height="{_num(overlay.h * h)}" as="geometry" />',
                '        </mxCell>',
            ]
        return out

    @staticmethod
    def _inscribed(cid: str, approx: "_Approximation | None",
                   w: float, h: float, fit: "_Fit") -> list[str]:
        """The second outline of a symbol that has two, as a child of
        the first.

        The safety-instrumented-system balloon is the case and today the
        only one: ANSI/ISA-5.1-2009 Table 5.1.1 column B draws it as a
        **square with an inscribed diamond**, where a bare
        ``shape=rhombus`` is Table 5.1.2's generic interlock and the
        symbol of the variant next door.

        **A child cell rather than a stencil.** Every shape named in
        :data:`_APPROXIMATIONS` is a draw.io *built-in* and never a
        stencil key. An inline ``shape=stencil(<deflated base64>)``
        would carry its artwork in the style, but a compressed blob is
        not the "plain uncompressed ``mxfile`` ... and it diffs" this
        file promises, and it would be the one shape
        ``tests/test_drawio.py`` has no stencil set to check.

        The pair holds together under editing:

        * **moving.** A child's geometry is relative to its parent's
          origin, so the parent moves and the child comes with it.
        * **resizing.** ``Graph.isRecursiveVertexResize`` answers yes
          for any non-swimlane vertex that has children, is not
          collapsed, states no ``childLayout`` and does not say
          ``recursiveResize=0`` -- which is this cell -- and
          ``mxVertexHandler.isRecursiveResize`` defers to it.
          ``resizeChildCells`` then scales the child by the ratio of the
          new box to the old, so the diamond stays inscribed. This is
          why the child is a plain vertex and not a group with a layout:
          a ``childLayout`` would switch the recursion *off*.
        * ``connectable=0``, so a stream dropped on the balloon lands on
          the square. Every fraction :meth:`_constraint` writes is a
          fraction of the square's box.
        * ``movable=0``, because the diamond is *part of* the symbol.
          The child is drawn over the parent -- children are validated
          after their parents -- so a reader clicking the middle of the
          balloon grabs the diamond and would otherwise drag it out of
          its square.

        ``fillColor`` is not the parent's: the square is already opaque
        white and knocks the hole in the line the balloon is dropped on.
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
        """An absolute point on a unit, as the fraction draw.io states
        one in.

        The arithmetic :meth:`_constraint` describes, taken on any point
        rather than only on a nozzle, because a tap line ends somewhere
        that is not a nozzle: the midpoint of a face of the host's box
        (:func:`pandid.layout.attach._anchor`), which is a point on the
        cell and not a port of it.
        """
        px, py = point
        x0, y0, x1, y1 = self._cell_box(u)
        w, h = x1 - x0, y1 - y0
        fx = (px - x0) / w if w else 0.5
        fy = (py - y0) / h if h else 0.5
        _, flip_h, flip_v = self._placement(u, sym)
        return (1.0 - fx if flip_h else fx, 1.0 - fy if flip_v else fy)

    def _constraint(self, u, sym, port_name: str) -> "tuple[float, float]":
        """Where a stream meets a port, as the fraction draw.io states
        one in.

        draw.io resolves a fixed connection point by taking the fraction
        of the cell's bounding box, then applying the cell's own flips
        to it. So the fraction to *write* is the one that lands on the
        port after those flips, which is the drawn fraction reflected
        back through them.

        Two style keys keep that the whole of the arithmetic, and they
        are set in two different places because mxGraph reads them in
        two different places:

        ``anchorPointDirection=0``, on the **vertex**
        (:meth:`_placement`, beside the ``direction`` it answers), stops
        draw.io rotating the anchor with the shape. It would otherwise
        state the point in the symbol's own upright frame and turn it,
        which is a second, equivalent way to arrive here -- and the
        wrong one to pick, because the point being divided through is
        :func:`~pandid.portgeom.port_point`'s, which has *already* been
        through the turn. Undoing a turn to let draw.io redo it is two
        chances to disagree about a nozzle that is not in doubt.

        ``exitPerimeter=0``/``entryPerimeter=0``, on the **edge**, stop
        draw.io projecting the point out onto the shape's perimeter. A
        nozzle inboard of the box -- a dome crown, a shell wall drawn
        inside the extent because brackets widen it -- is where the pipe
        meets the equipment, and projecting it would slide the line off
        the drawing onto the bounding box, which is exactly the
        distinction :func:`pandid.portgeom.resolve_port` keeps between a
        port's point and its routing anchor.
        """
        if u.kind == "tee":
            # A junction, not a nozzle. On the sheet the meeting is
            # drawn by the tee's own twelve-unit mark and the pipes stop
            # at the box edge; draw.io has no built-in that draws that
            # mark without also drawing a stub out the side, so the
            # pipes are carried the last six units in and the cell draws
            # nothing.
            #
            # The centre, so all three legs end on one point: flush by
            # construction, with no tolerance to get wrong. Each leg
            # stays straight, a tee's three nozzles being face midpoints
            # with the centre on the axis of all three.
            x0, y0, x1, y1 = self._cell_box(u)
            return self._fraction(u, sym, ((x0 + x1) / 2, (y0 + y1) / 2))
        return self._fraction(u, sym, port_point(u, u.frame, port_name))

    @staticmethod
    def _ends(exit_at, entry_at) -> list[str]:
        """The style keys pinning an edge's two ends to fixed points on
        its cells.

        ``None`` for an end that is not pinned to a cell at all, which
        is a floating point stated in the geometry instead. See
        :meth:`_taps`.
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
               joints: "str | None" = None) -> list[str]:
        """Every stream, as a draw.io edge between the two ports it
        joins.

        ``joints`` is the sheet's
        :func:`~pandid.render.svg.sheet_connections` answer, threaded in
        for the same reason ``arrows`` is: the flange mark is a fact
        about the drawing, and the export draws the drawing.

        ``direction`` is the sheet's ``jump_direction``, and it settles
        two things at once: which edges carry :data:`_JUMP_STYLE`, and
        **the order the edges come out in**, since draw.io breaks the
        tie between two crossing lines by z-order. Both are
        :func:`_hops`' answer.

        The cells are therefore built in ``fs.streams`` order and
        *written* in the hop order. Building them in stream order is not
        incidental: a line number is written on the first segment of its
        run to carry it, and "first" has to mean first in the flowsheet
        or a crossing somewhere else on the sheet would move a number
        onto a different segment of a run it was not otherwise involved
        in.
        """
        index = {id(u): i for i, u in enumerate(fs.units)}
        # Where the sheet writes each line number, by the sheet's own
        # search rather than by centring it on the edge -- seeded with
        # the equipment tags the sheet seeds it with, so the search is
        # offered the same paper. See :func:`_number_geometry` and
        # :class:`_Tags`.
        numbers = {number.name: number
                   for number in stream_numbers(fs, list(tags.plates), joints)}
        polylines = {n: stream_polyline(s) for n, s in enumerate(fs.streams)}
        order, hops = _hops(polylines, direction)
        labelled: set = set()
        cells: dict = {}
        for n, s in enumerate(fs.streams):
            src_u, dst_u = s.source.owner, s.dest.owner
            points = polylines[n]
            ex, ey = self._constraint(src_u, self.registry.for_unit(src_u), s.source.name)
            tx, ty = self._constraint(dst_u, self.registry.for_unit(dst_u), s.dest.name)
            signal = s.kind in _SIGNAL_KINDS

            keys = [
                "html=1",
                # edgeStyle=none: draw the polyline that was routed,
                # segment for segment, rather than handing the path back
                # to draw.io's own orthogonal router. The router would
                # re-derive a path from the same waypoints and is
                # entitled to a different one, and the first thing a
                # reader does with this file is check that it looks like
                # the sheet. The cost is that a block dragged in draw.io
                # leaves its end leg sloping until the author re-routes
                # it, which is a thing they can see and fix.
                "edgeStyle=none", "rounded=0", "orthogonalLoop=1", "jettySize=auto",
                *self._ends((ex, ey), (tx, ty)),
                f"strokeColor={s.color or _LINE_INK}",
                # A signal is drawn at half the weight of the pipe it
                # reads, and the pair is the sheet's whole line-weight
                # vocabulary; see the note on _PROCESS_STROKE in
                # pandid.render.svg.
                f"strokeWidth={fit.length(_SIGNAL_STROKE if signal else _PROCESS_STROKE):g}",
            ]
            # The semicircle this run hops the runs it crosses with,
            # where the direction selects it. Sized off the edge's own
            # pen, since draw.io's jumpSize is stated net of it; see
            # :func:`_jump_size`.
            if n in hops:
                weight = fit.length(_SIGNAL_STROKE if signal else _PROCESS_STROKE)
                keys += [f"jumpStyle={_JUMP_STYLE}",
                         f"jumpSize={_jump_size(fit.length(HOP_R), weight)}"]
            keys += _dash(s.dasharray or _SIGNAL_DASH.get(s.kind, ""))
            if arrows and wears_arrowhead(s, self.registry):
                # Through the fit, like the pen beside it. A flow head
                # is twelve units of *drawing*, and stating it flat on a
                # sheet fitted to three quarters of its own size drew a
                # head a third too big at the end of a line correctly
                # thinned -- the same slip as the missing stroke widths,
                # in the same function.
                keys += ["endArrow=block", "endFill=1",
                         f"endSize={fit.length(ARROWHEAD):g}"]
            else:
                keys.append("endArrow=none")
            keys.append("startArrow=none")

            # A number names a *run*, and a run survives the valves and
            # fittings in it: renumber_streams() gives every segment of
            # one the same name, and the sheet writes it once. Writing
            # it on each segment would put the same number on a line
            # three times over, so the first segment to carry it is the
            # one that carries it here too. A signal line is unlabelled
            # on the sheet and stays unlabelled here.
            label = ""
            number = None
            if not signal and s.name not in labelled:
                labelled.add(s.name)
                label = s.name
                number = numbers.get(s.name)
                if number is not None:
                    keys += _NUMBER_KEYS + [_drawn_type(NUMBER_TYPE, fit)]
                    if number.vertical:
                        keys.append("horizontal=0")

            style = ";".join(keys) + ";"
            # The ends are the two nozzles, and they are stated as
            # constraints above; what goes in the array is the turns
            # between them. A run with no turn in it carries no array at
            # all, which is how draw.io writes a straight edge and keeps
            # a straight run from reading as a route that happens to
            # have no points left.
            waypoints = points[1:-1]
            along, offset = _number_geometry(number, points, fit)
            body = [
                *(['            <Array as="points">',
                   *(f'              <mxPoint x="{_num(fx)}" y="{_num(fy)}" />'
                     for fx, fy in (fit.at(px, py) for px, py in waypoints)),
                   '            </Array>'] if waypoints else []),
                *([f'            <mxPoint x="{_num(offset[0])}" y="{_num(offset[1])}" '
                   'as="offset" />'] if offset is not None else []),
            ]
            # `x` on the edge's own geometry is where the label sits
            # along the run; the `offset` beside it is where it sits
            # across. Both are the *label's*, and they ride on the same
            # mxGeometry as the waypoints because mxGeometry has a field
            # for each and mxObjectCodec decodes them independently --
            # an `<Array as="points">` and an `<mxPoint as="offset">`
            # are two named children of one element, and draw.io writes
            # exactly this shape itself when a reader drags a label
            # along a routed edge (`mxEdgeHandler.moveLabel`).
            head = ('          <mxGeometry relative="1" as="geometry"'
                    + ('' if along is None else f' x="{_fraction(along)}"'))
            if body:
                geometry = [head + ">", *body, '          </mxGeometry>']
            else:
                geometry = [head + " />"]
            cells[n] = [
                f'        <mxCell id="s{n}" value={_attr(label)} style={_attr(style)} '
                f'edge="1" parent="1" source="{self._id(index[id(src_u)])}" '
                f'target="{self._id(index[id(dst_u)])}">',
                *geometry,
                '        </mxCell>',
            ]
            # The hatch marks ride on their edge and go out with it,
            # wherever the hop order puts it: a child cell is resolved
            # by its parent's id, but draw.io writes a parent before its
            # children and so does this.
            if s.kind == "pneumatic":
                cells[n] += _hatches(f"s{n}", points, s.color or _LINE_INK, fit)
            cells[n] += _flanges(f"s{n}", s, points, resolve_connections(s, joints),
                                 s.color or _LINE_INK, fit)
            if number is not None and number.leader is not None:
                cells[n] += _leader(f"s{n}", number, s.color or _LINE_INK, fit)
        out: list[str] = []
        for n in order:
            out += cells[n]
        return out

    def _taps(self, fs, fit: "_Fit") -> list[str]:
        """Every instrument connection, as a draw.io edge.

        The line from a tap to the balloon reading it. It is not a
        stream and so is not in ``fs.streams``, and an exporter that
        walks only the streams hands back a sheet of balloons floating
        free of the plant. ISO 15519-2 §5.1.1 (document page 8, under
        Figure 6) does not leave that open:

            The PCI symbol **shall** be connected, see Figure 6, to the
            following:

            -- the process system with a solid functional
            connection line without indications of for example
            signal flow directions, signal types, etc.;

            -- the control system with a solid or dashed functional
            connection line depending on the type of diagram, see
            Clause 6.

        Which of the two a given line is, is
        :func:`~pandid.render.svg.impulse_tap`'s answer and not this
        file's, and the endpoints are
        :func:`~pandid.render.svg.tap_lines`': there is one derivation
        of where a tap runs and the SVG renderer draws from the same
        one.

        **An edge and not a drawn line**, because the balloon is the
        thing an author moves and a drawn line would come away from it.
        The balloon end is pinned to the balloon's own cell, at the
        centre, which is where the sheet runs it to and where the
        balloon's opaque body then knocks it out -- the balloons are
        written after these, so draw.io stacks them the same way.

        The other end is pinned to the *host's* cell where the host is a
        piece of plant, since the tap is the midpoint of a face of that
        cell and moves with it. Where the host is a **stream** the end
        is a floating point instead: draw.io can join an edge to another
        edge, but the point it would pick is its own, and a tap that
        slid to the middle of the pipe would be a different statement
        about where the reading is taken.

        One thing is reproduced faithfully rather than fixed: issue #170
        records that a tap is a single straight line, so a tap whose
        balloon is neither level with nor square to its host is drawn
        sloping rather than doglegged. The export slopes it too.
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
                # ISO 15519-2 Annex A.1.02 puts an instrument connection
                # on the 0,25 rung, alongside the signal line and half
                # the pipeline it taps. See _SIGNAL_STROKE in
                # pandid.render.svg.
                f"strokeWidth={fit.length(_SIGNAL_STROKE):g}",
            ]
            if not impulse_tap(inst):
                keys += _dash(_TAP_DASH)
            # No head at either end: the line says what the instrument
            # is on, not which way anything flows. §5.1.1 above says so
            # in as many words. And no hop over it either: a tap is not
            # one of the runs the sheet's jump pass looks at. See
            # :data:`_NO_HOP`.
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
        """The drawing's own bounding box, which is what the furniture
        docks around.

        Every unit's drawn box and every route waypoint, which is
        :meth:`SvgRenderer.render`'s step 1 exactly. It has to be
        exactly that: the dock places a box relative to this rectangle,
        so a rectangle measured differently would dock the same
        equipment list somewhere else.
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
        """The page the file states, as ``(width, height)`` in drawing
        units.

        Drawing units, not millimetres, which is what makes an A3 page
        1587 by 1123 rather than 420 by 297: pageWidth and pageHeight
        are read straight into `graph.pageFormat` and measured against
        the same coordinates every cell in the file is placed at.

        **Given paper, the paper.** The dock has already fitted the
        drawing into what the sheet's furniture left, so the page and
        the sheet are one thing.

        **Without paper, the extent of what this file draws.** There is
        a page either way -- see :meth:`render` for why draw.io leaves
        nobody the option of having none -- and the size is measured
        from the rectangle these cells are actually placed against,
        which is :meth:`_furniture`'s ``frame``: the dock hangs every
        box off it, and :meth:`_border` rules the sheet edge at
        :func:`~pandid.render.furniture.sheet_rect` of it. So the page
        is that frame, out through the border band -- which an unruled
        sheet keeps as plain margin -- and out again by
        :data:`~pandid.render.furniture.OUTER_MARGIN`. Sized from any
        other rectangle it could leave a zone border hanging over the
        edge of its own page.

        On a furnished sheet that lands exactly on
        ``SvgRenderer._place_furniture``'s viewBox. On an unfurnished
        one the two differ by five units a side, the SVG taking a flat
        55 margin off the drawing where the dock takes 26 and the band
        and margin make it 50. ``tests/test_drawio.py`` asserts what
        matters: that every cell the file writes lands inside the page
        it states.

        Only the *extent* is taken, never the corner. ``page="0"`` has
        draw.io position the unpaged page from the drawing's own
        top-left, so adding the frame's own offset in would inflate the
        page by however far the author pinned the first vessel from
        zero.
        """
        if sheet is not None:
            return (sheet.width, sheet.height)
        _ox, _oy, ow, oh = F.sheet_rect(*frame)
        return (ow + 2 * F.OUTER_MARGIN, oh + 2 * F.OUTER_MARGIN)

    def _furniture(self, fs, sheet=None, show_stream_table: bool = False):
        """Title block, annotations, table boxes and the stream table,
        docked where the sheet docks them and ruled as the tables they
        are.

        **Docked, not stacked.** Where a box lands is
        :func:`pandid.render.furniture.dock`'s answer and not this
        file's, so both backends put the same measurements to the same
        function: the equipment list to the top right, the legend to the
        top left, the notes wherever they were aligned and the title
        strip into the bottom-right corner.

        The one thing that cannot follow the sheet is the *frame*. A
        rendered sheet may be a fixed page, and then the furniture docks
        to the paper; a ``.drawio`` file is an unbounded canvas with no
        paper in it, so the dock is given the drawing's own bounds and
        grows a frame around them. On a sheet drawn at
        ``page_size="A3"`` the corners are therefore the drawing's
        rather than the page's, which is the only relationship that
        survives the reader re-laying the model out by hand.

        **Ruled, not run together.** A box whose rows have columns in
        them is a *table*, and draw.io has real ones: a ``shape=table``
        carrying ``shape=tableRow`` children carrying
        ``shape=partialRectangle`` cells, which open as an editable grid
        rather than as one string of text with ``<br>`` in it. Every
        equipment list, legend, note list,
        :class:`~pandid.document.TableBox` and stream table goes out as
        one. A box whose rows are plain strings stays a box: ruling a
        single column into a grid would invent structure the author did
        not write.

        **Ruled where the sheet rules it, and not everywhere a grid
        could be ruled.** A table's rows and cells are what make it
        editable; its *lines* are a separate question and the answer is
        the sheet's. An :class:`~pandid.document.Annotation` is drawn on
        paper as a box with a title bar and rows of text -- no column
        rules, no row rules -- so it is exported with
        ``rowLines=0;columnLines=0`` and keeps its cells (see
        :data:`_ANNOTATION_KEYS`). A :class:`~pandid.document.TableBox`
        really does rule every cell (``draw_table`` strokes a rectangle
        apiece) and so keeps both.
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
        # Last into the bottom-left column, which is where the sheet
        # puts it: `put_bottom` stacks upward from the frame edge, so
        # the table sits against the foot of the sheet with anything
        # else docked there above it. The measurement is the sheet's own
        # -- there is one stream table and both backends ask the same
        # function for it.
        table = F.stream_table_layout(fs) if show_stream_table else None
        if table is not None:
            items.append((table, "bottom-left", table.w, table.h))

        inner = self._drawing_box(fs)
        placed, frame, free = F.dock(
            items, inner, sheet=sheet,
            too_small=lambda need_w, need_h, culprit: _too_small(
                sheet, need_w, need_h, _furniture_name(culprit) if culprit else ""))
        # A fixed page fits the drawing into whatever the bands leave,
        # at the ratio the title strip's scale cell reports. Without one
        # there is no fitting: the drawing keeps its own coordinates and
        # the frame was grown around it.
        fit = _Fit.identity() if free is None else _Fit(
            *_fitted(inner, free))
        # What the title strip's own three variable fields are filled
        # from, all three of them the sheet's answer rather than this
        # file's: the drawing name a blank title falls back to, today's
        # date where the block states none, and the ratio the dock has
        # just settled the drawing at.
        block = fs.title_block
        name = (getattr(block, "title", "") or fs.name) if block is not None else fs.name
        date = (getattr(block, "date", "") if block is not None else "") or \
            datetime.now().strftime("%Y-%m-%d")
        scale = "" if free is None else _scale_text(fit.scale)
        out: list[str] = []
        for n, (obj, x, y, w, h) in enumerate(placed):
            out += self._furniture_cell(f"f{n}", obj, x, y, w, h, name, date, scale)
        return out, frame, fit

    @staticmethod
    def _border(frame, border: str) -> list[str]:
        """The zone-ruled drawing frame, as cells.

        Only where the sheet rules one. An unruled sheet draws no
        rectangle at all -- ``_place_furniture`` takes ``sheet_rect``
        for the canvas bounds and strokes nothing -- so an unruled
        export draws none either, and what the reader sees as the edge
        of the paper is the page draw.io is now told to rule. Inventing
        a rectangle here would put ink on the sheet that the rendered
        one does not have.

        The geometry is :func:`pandid.render.furniture.zone_layout`'s,
        so the band is divided into the same fields, lettered the same
        way round.

        A caveat worth the author knowing, and it is why this was argued
        about rather than just added: a zone grid is an **address
        space**. ISO 15519-1 Clause 9 uses it for "reference to a
        document, to a sheet of a document, or to a column, a row or a
        zone on a sheet", and :attr:`pandid.units._Boundary.reference`
        is where this library writes such addresses. On paper they hold
        because the sheet holds. In an editable model they do not: drag
        a column two hundred units left and it is in a different zone
        from the one every reference on the sheet names, while the grid
        still looks authoritative. So what is exported here is a
        **snapshot of the grid at export time**, true of the drawing as
        it left pandid and no longer true of it once the reader has
        moved anything.
        """
        if border != "zone":
            return []
        ix, iy, iw, ih = frame
        z = F.zone_layout(ix, iy, iw, ih)
        ox, oy, ow, oh = z.outer
        rect = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;movable=1;"
                f"strokeColor={_LINE_INK};")
        out = _rect("z-sheet", ox, oy, ow, oh, rect + "strokeWidth=1;")
        out += _rect("z-frame", ix, iy, iw, ih,
                     rect + f"strokeWidth={_FRAME_STROKE:g};")
        for n, part in enumerate(z.parts):
            if part[0] == "rule":
                _, x1, y1, x2, y2 = part
                out += _segment(f"z{n}", x1, y1, x2, y2, _LINE_INK, 0.75)
            else:
                _, lx, ly, text = part
                out += _label(f"z{n}", lx, ly, text, F.ZONE_TYPE)
        return out

    def _furniture_cell(self, cid: str, obj, x, y, w, h,
                        name: str = "", date: str = "",
                        scale: str = "") -> list[str]:
        """One docked piece of furniture, as the cells that draw it."""
        from pandid.document import TableBox, TitleBlock

        if isinstance(obj, TitleBlock):
            return self._title_strip(cid, obj, x, y, w, h, name, date, scale)
        if isinstance(obj, F.StreamTable):
            return _stream_table(cid, obj, x, y)
        title = getattr(obj, "title", "") or ""
        if isinstance(obj, TableBox):
            size, _ncol, col_w, _row_h = F._table_layout(obj)
            # A TableBox rules its own columns, and _table_layout's
            # widths already carry that ruling's padding and sum to the
            # measured box. A table's border and every rule inside it
            # are drawn by the *container*, from the container's own
            # style (``TableShape.paintTableForeground``), so the weight
            # has to be stated there or draw.io rules the whole grid at
            # its default 1 where the sheet strokes each cell at
            # ``_CELL_RULE``.
            return _table(cid, title, [str(c) for c in obj.headers],
                          [[str(c) for c in row] for row in obj.rows],
                          x, y, w, h, col_w, (size + 10) if title else 0.0,
                          font=size, keys=f"strokeWidth={F._CELL_RULE:g};",
                          col_keys=_ALIGN_KEYS(obj.col_align, len(col_w)))
        rows = list(getattr(obj, "rows", []) or [])
        if any(isinstance(r, (tuple, list)) for r in rows):
            # Columnar: an equipment schedule, a legend, a numbered note
            # list. The columns are measured off their own text at the
            # size they will be drawn at, not shared out in proportion;
            # see :func:`columns`.
            size, _row_h, title_h, _col_w = F._ann_layout(obj)
            grid = [[str(c) for c in r] if isinstance(r, (tuple, list)) else [str(r)]
                    for r in rows]
            ncol = max(len(r) for r in grid)
            # Left, as the sheet sets a row, with the first column bold
            # where there is more than one -- draw_annotation's own
            # rule. The same list of weights is what the columns are
            # measured in, so the key column is measured in the face its
            # key is drawn in.
            heavy = [True] + [False] * (ncol - 1)
            return _table(cid, title, [], grid, x, y, w, h,
                          columns(grid, [size] * ncol, w, bold=heavy), title_h,
                          font=size,
                          # `_ANNOTATION_KEYS` leaves the container's
                          # own border as the only rule this box draws,
                          # so the weight stated here is the weight of
                          # the rectangle the sheet strokes around a
                          # legend. It was unstated, and draw.io's
                          # default 1 drew it two thirds as heavy.
                          keys=(_ANNOTATION_KEYS + f"fontSize={size + 1:g};"
                                + f"strokeWidth={F._BOX_RULE:g};"),
                          col_keys=[f"align=left;spacingLeft=4;{'fontStyle=1;' if b else ''}"
                                    for b in heavy])
        # Not tabular: a titled box of free-form lines, which is what it
        # is on the sheet too. Anything docked that is neither an
        # Annotation nor a TableBox lands here as well, on the two
        # things every box has -- a title and some rows -- rather than
        # being dropped for being neither.
        size = getattr(obj, "font_size", 11.0)
        _s, _row_h, title_h, _col_w = F._ann_layout(obj) if rows or title else (
            size, 0.0, 0.0, [])
        return _text_box(cid, title, [str(r) for r in rows], x, y, w, h, size,
                         title_h)

    def _title_strip(self, cid: str, block, x, y, w, h, name: str, date: str,
                     scale: str) -> list[str]:
        """The engineering title strip, ruled where the sheet rules it.

        The strip is one rectangle and three columns: a revision grid on
        the left, a company cell in the middle, and on the right an
        information block of bands of unequal depth -- a title band with
        the sheet count tucked into its corner, a status band, and a
        bottom band ruled into DRAWING No / SCALE / DATE / REV. Only the
        first is a uniform grid, and a draw.io table gives every cell in
        a row that row's height (``TableLayout.layoutRow``), so the
        other two cannot be tables without becoming a list of label and
        value, one field per row -- which holds every value and looks
        nothing like the sheet.

        So the bands go out as what they are: a rectangle, some rules,
        and text at the sizes and weights the sheet letters them at,
        read from :func:`~pandid.render.furniture.title_strip_layout`,
        which :func:`~pandid.render.furniture.draw_title_strip` strokes
        into SVG from the same list of parts. **There is no strip
        arithmetic in this method at all**: a band whose depth is 0,4 of
        the block is 0,4 of it in both backends because neither backend
        works it out.

        **The revision history stays a real table**, and it is the only
        piece that could be one: a grid of six named columns with one
        row per revision, and the one part of an issued title block a
        reader actually edits. See :func:`_rev_table`.

        The cost, plainly: the eleven identification fields are not
        cells of a grid, so a reader changing the drawing number
        double-clicks a text label and there is no column rule to drag.
        Every field is still a cell of its own with its own id, and so
        is every rule.

        ``report`` is why the layout is asked for by name rather than
        with the arguments alone. The strip is fixed geometry and a value
        too long for its cell is abbreviated to an ellipsis, which tells
        a reader that something was cut and tells the program that
        supplied it nothing -- so an issued sheet exported to draw.io
        carried a *wrong drawing number* silently. The sheet has said so
        since the cells were ruled; this says it too, in the same words.
        """
        strip = F.title_strip_layout(block, name, date, x + w, y + h, scale,
                                     report=self._report)
        bx, by, bw, bh = strip.box
        # Flush to the frame, exactly as the sheet's own strip is:
        # `_strip_size` reports the sheet's rectangle and `dock` puts
        # its bottom-right corner on the frame's. The strip's rule and
        # the frame's are then coincident and two units wide apiece,
        # which is what the rendered sheet draws.
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


#: What a line number is, over and above where it is put.
#:
#: ``labelBackgroundColor`` is the sheet's halo, said in a style:
#: mxGraph paints an opaque box behind a label sized to the measured
#: text, on an edge exactly as on a vertex -- ``mxText.configureCanvas``
#: calls ``setFontBackgroundColor`` and ``mxSvgCanvas2D`` either writes
#: a CSS ``background-color`` or inserts a ``<rect>`` before the glyphs,
#: and nothing in that path asks whether the cell is an edge. So a
#: number that has to be written across a passing run still reads, which
#: is the whole reason the sheet draws one.
#:
#: ``verticalLabelPosition`` is **not** here, though it places every
#: *vertex* label in this file: it has no effect at all on an edge.
#: ``mxCellRenderer.getLabelBounds`` takes a separate branch for an
#: edge, starting from ``state.absoluteOffset`` and adding only the
#: text's spacing, and the final ``if (!isEdge)`` guard skips
#: ``rotateLabelBounds`` -- the only place either label-position style
#: changes any geometry. The other reader, ``updateVertexLabelOffset``,
#: is vertex-only by name. An edge label is moved by its geometry and by
#: nothing else.
#:
#: ``horizontal=0`` is the exception, added per number in
#: :meth:`DrawioRenderer._edges` for one on a vertical run. The sheet
#: turns such a number a quarter to read bottom to top (ISO 15519-1
#: §7.2.5, and §5.1.5 for reading "from the right-hand edge of the
#: document"), so the paper the search reserved for it is 13 units
#: across by however long the string is; written flat the label occupies
#: the **transpose** of that. Two of the sixteen numbers on
#: ``11_ethanol_pid`` and eight of the twenty-four on
#: ``13_mineral_dewatering`` are vertical.
#:
#: Unlike the two above it does reach an edge label:
#: ``mxText.getTextRotation`` defers to ``mxShape.getTextRotation``,
#: which adds ``mxText.verticalTextRotation`` -- **-90**, bottom to top,
#: the way round the sheet turns it -- whenever ``horizontal`` is not 1.
#: That is a property of the *shape*, and an edge has one
#: (``mxConnector``). The opaque halo turns with it: ``mxSvgCanvas2D``
#: puts the background on the same transformed group as the glyphs.
_NUMBER_KEYS = ["labelBackgroundColor=#ffffff", "verticalAlign=middle",
                "align=center"]


def _number_geometry(number, points, fit: "_Fit"):
    """A line number's place on its edge: how far along, and how far
    across.

    ``mxGraphView.getPoint`` is the whole of the mechanism and it is
    exact enough to reproduce the sheet's own placement rather than
    approximate it. For an edge whose geometry is ``relative``,
    ``geometry.x`` runs -1 to +1 over the routed polyline's Euclidean
    arc length -- ``dist = Math.round((geometry.x / 2 + 0.5) *
    state.length)`` -- and ``geometry.offset``, an ``<mxPoint
    as="offset">``, displaces the label from there in plain drawing
    units, multiplied by the view's zoom and by nothing else.

    **The offset and not ``geometry.y``**, which is the other
    displacement on offer and is a trap. ``getPoint`` applies it as
    ``(nx * gy, -ny * gy)`` where ``nx = dy/segment`` and ``ny =
    dx/segment``, so its sign is taken from the direction the segment
    happens to be *routed* in: the same positive number puts a label
    above a run drawn left to right and below the identical run drawn
    right to left. Which end of a stream is its source is a fact about
    the process and not about the paper, so a perpendicular offset
    stated that way would put half this sheet's numbers on the wrong
    side of their lines. The offset is axis-aligned and direction-free,
    and the sheet's answer is already an absolute point.

    The along-run figure is taken by projecting that point onto the
    segment the number names -- clamped to the segment, so a number the
    sheet slid past the end of a short run stays attached to it and the
    overrun goes into the offset instead. The label lands on the same
    paper either way; what the clamping buys is that the number rides
    its own segment when a reader drags the plant about, rather than
    jumping to whichever piece of the route the arc length then points
    at.

    Returns ``(None, None)`` for an edge with no number on it.
    """
    if number is None:
        return None, None
    (ax, ay), (bx, by) = number.seg
    dx, dy = bx - ax, by - ay
    span = (dx * dx + dy * dy) ** 0.5
    if span <= 0:
        return None, None
    # The foot of the perpendicular from the number onto its own
    # segment, held inside it.
    t = min(1.0, max(0.0, ((number.x - ax) * dx + (number.y - ay) * dy) / (span * span)))
    foot = (ax + t * dx, ay + t * dy)

    # ...and where that foot falls along the *whole* polyline, which is
    # what draw.io measures the fraction against. The segment is found
    # by identity on its endpoints, since stream_polyline is what both
    # the number and the edge were built from.
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
    """The leader a displaced line number is tied back to its run with.

    Where :func:`~pandid.render.svg.stream_numbers` finds no clear paper
    alongside a run it writes the number off the line and draws a leader
    back to it, and ISO 15519-1 §6.4 says how that leader ends: "Leader
    lines **shall** terminate: with a dot if it terminates within an
    object; with an arrowhead if it ends on the outline of an object or
    a connection; with an oblique stroke if it ends at several parallel
    connections." A line number's leader ends on a connection, so it
    wears an arrowhead. Without one the number is a string of characters
    floating in blank paper, attached to nothing, which is what
    ``AE-304-150-80-SS`` on ``11_ethanol_pid`` was in every exported
    file.

    An edge whose two terminals are stated as ``mxPoint``\\ s and
    neither as a cell is how draw.io writes a free-standing rule -- what
    :func:`_segment` emits for the sheet furniture -- and
    ``endArrow=block;endFill=1`` is the filled triangle
    :func:`~pandid.render.svg._arrowhead` draws.

    The honest cost is that **it does not ride the run**. Its two ends
    are absolute points, so dragging the plant leaves the leader where
    it was while the number itself -- which *is* on the edge's geometry
    -- moves with the line. That is the trade
    :meth:`DrawioRenderer._taps` takes for a tap whose host is a stream,
    for the same reason: draw.io can join an edge to another edge, but
    the point it picks is its own, and a leader that slid along the pipe
    would point somewhere the sheet does not.

    ``noJump=1`` because a leader is not a connection and the sheet's
    jump pass never sees one; see :data:`_NO_HOP`. ``ink`` is the
    label's colour, which ``stream_numbers`` takes from ``s.color``, so
    it is passed in, in the spelling :data:`_LINE_INK` settles on rather
    than in the SVG's ``black``. The weight is
    :data:`~pandid.render.svg._SIGNAL_STROKE`, because §6.4 hands the
    leader itself to ISO 128-22 where it is a narrow line.
    """
    (ax, ay), (bx, by) = number.leader
    style = (f"edgeStyle=none;rounded=0;html=1;startArrow=none;endArrow=block;"
             f"endFill=1;endSize={fit.length(_LEADER_HEAD):g};"
             f"strokeColor={ink};"
             f"strokeWidth={fit.length(_SIGNAL_STROKE):g};movable=1;{_NO_HOP}")
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


#: How a label on each of the four sides of a box is asked for in a
#: draw.io style. ``verticalLabelPosition``/``labelPosition`` put the
#: label's *box* outside the cell, and the ``verticalAlign``/``align``
#: beside each pull the text back against the cell it belongs to;
#: stating only the first of each pair leaves the text centred on the
#: cell it was just moved off.
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

#: The angle a hatch stroke is drawn at, in draw.io's clockwise degrees,
#: on a horizontal run. The sheet strokes it 6 units along the run by 10
#: across (:data:`~pandid.render.svg.HATCH_ARM`), which is ``atan2(-10,
#: 6)``; a vertical run is the same mark on a run turned a quarter, so
#: it is this plus ninety.
_HATCH_ANGLE = -59.04
#: The box the stroke is drawn across. ``line`` strokes its box's
#: horizontal centreline edge to edge, so the width *is* the stroke's
#: length: 6 along by 10 across is a stroke 11.66 long.
_HATCH_LEN = 11.66


def _hatches(edge_id: str, points, ink: str, fit: "_Fit") -> list[str]:
    """The double cross-hatch that marks a pneumatic line, hung on its
    edge.

    ISO 15519-2 §6.2 (document page 14) is what makes this worth the
    trouble rather than decoration:

        Graphical symbols for indication of signal media, e.g.
        pneumatic or hydraulic, should only be used to differentiate,
        if the majority of signal lines in same diagram are electric.
        For graphical symbols for signal media, see Annex A.

    which is ``examples/11``'s case: most of its signal lines are
    electric or software and the pneumatic ones run to actuators.

    **There is no native way to draw it.** ``Sidebar-PID.js`` registers
    no edge template at all and no stencil in the set is a signal line.
    Nor can a stencil describe an edge: ``mxShape.paint`` takes the
    stencil branch before the edge branch, so a stencil named on an edge
    is stretched into the route's bounding box and the line is not
    drawn. And mxGraph puts a marker at an edge's two ends and nowhere
    else -- ``mxConnector.createMarker`` is called twice, with
    ``pts[0]`` and ``pts[n-1]``.

    What there is, is a **child vertex on the edge**, the mechanism
    draw.io's own edge labels ride on. ``mxGraphView.getPoint`` maps
    ``mxGeometry.x`` in ``[-1, 1]`` onto distance along the *routed*
    polyline by arc length, and ``mxGraphView.updateCellState`` puts the
    child's **top-left** on the point it returns -- not its centre,
    which is why every offset below carries a ``-length/2``.
    ``mxGeometry.offset`` displaces it in plain drawing units. Nothing
    is cached, so dragging a balloon re-routes the line and the marks
    move with it.

    Two departures from the sheet, neither silent:

    * **the stroke does not re-orient.** mxGraph has no auto-orientation
      for a shape on an edge (``labelAutoRotate`` turns *text*, not
      shapes), so the angle is computed here from the segment the mark
      falls on and written as a ``rotation``. Re-route the line through
      a turn and a mark keeps the angle it was exported with.
    * **the mark is a built-in ``line``, twice**, rather than one glyph,
      so the double hatch is two cells a reader can select apart.

    Where the marks fall is :func:`~pandid.render.svg.pneumatic_marks`'.
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
        # mxGeometry.x runs -1 at the source end to +1 at the target
        # end, by arc length; the mark already knows how far along it
        # is, so this is the whole conversion.
        rel = max(-1.0, min(1.0, 2.0 * mark.along / total - 1.0))
        horiz = mark.horizontal
        angle = _HATCH_ANGLE if horiz else _HATCH_ANGLE + 90.0
        style = (f"shape=line;rotation={angle:g};strokeColor={ink};"
                 f"strokeWidth={fit.length(_SIGNAL_STROKE):g};fillColor={_NO_FILL};html=1;"
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
    """The flanged-connection marks on one line, hung on its edge.

    **It does not ride on the arrowhead's path, and it could not.** An
    arrowhead is a terminal on an edge: ``_ends`` states the two nozzles
    as ``exitX``/``entryX`` constraints and the head itself is three
    style keys, ``endArrow=block;endFill=1;endSize=...``. draw.io's
    arrow vocabulary is the ``mxMarker`` registry -- classic, block,
    open, oval, diamond, ERone and the rest -- and there is no flange in
    it, nor any way to register one in a file rather than in the
    application. Worse, the terminal marker is drawn *at* the end point
    and rotated to the segment, which is an arrowhead's geometry and not
    a flange's: the mark stands **off** the nozzle by
    :data:`~pandid.render.svg.FLANGE_STANDOFF`, and there is no marker
    property that displaces one along its line. And a line has two ends
    but wants marks on however many of them take one, which
    ``startArrow``/``endArrow`` cannot express independently of the
    head.

    So it gets its own cells, by the same mechanism :func:`_hatches`
    uses and for the same reason -- a child vertex on the edge, placed
    by arc length along the routed polyline, which rides the line when
    draw.io re-routes it. Two cells per mark, because two bars is what
    the mark *is*.

    Where the marks fall is :func:`~pandid.render.svg.flange_marks`', so
    the export marks the joints the sheet marks and in the places the
    sheet marks them. A flange lands hard against an equipment outline,
    where one rule here and another there is the difference between a
    joint and a collision.
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
        # The bar is drawn *across* the run, and `line` strokes its
        # box's horizontal centreline, so the box turns a further
        # quarter.
        style = (f"shape=line;rotation={mark.angle + 90.0:g};strokeColor={ink};"
                 f"strokeWidth={fit.length(_PROCESS_STROKE):g};fillColor={_NO_FILL};"
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

#: The three shapes a draw.io table is built from, in the styles
#: draw.io's own ``Graph.createTable`` writes -- which is what its
#: Insert > Table calls, so this is the file the application itself
#: would have produced.
#:
#: ``childLayout=tableLayout`` is the only key ``Graph.isTable`` tests,
#: and ``shape=table`` is load-bearing beyond the painting:
#: ``Graph.isSwimlane`` answers yes for it, and without that
#: ``getActualStartSize`` returns zero and the ``startSize`` title band
#: is not ruled at all. ``rowLines``/``columnLines`` default on and are
#: drawn by the **table**, from its cells' geometry, in the table's own
#: ink -- which is why every row and cell below switches its own four
#: edges off and inherits the colour rather than stroking anything
#: itself.
_TABLE_SHAPE = ("shape=table;childLayout=tableLayout;container=1;collapsible=0;"
                "fixedHeader=1;html=1;whiteSpace=wrap;align=center;"
                "verticalAlign=middle;fontStyle=1;"
                f"strokeColor={_INK};fillColor={_NO_FILL};")
#: A row is a swimlane turned on its side (``horizontal=0``) with no
#: label strip of its own (``startSize=0``).
#: ``points``/``portConstraint`` are draw.io's own and worth keeping:
#: they give a row a connection point at each end, so an edge can be
#: drawn to a line of a schedule.
_TABLE_ROW = ("shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;"
              "swimlaneBody=0;strokeColor=inherit;fillColor=none;"
              "collapsible=0;dropTarget=0;fixedHeader=1;"
              "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
              "top=0;left=0;right=0;bottom=0;")
#: ``pointerEvents=1`` is not decoration: an unfilled cell is
#: click-through without it, and a schedule whose cells cannot be
#: clicked is not editable.
_TABLE_CELL = ("shape=partialRectangle;html=1;whiteSpace=wrap;connectable=0;"
               "strokeColor=inherit;overflow=hidden;"
               "top=0;left=0;bottom=0;right=0;pointerEvents=1;")
#: A heading row is filled and set bold, which is what the sheet does
#: with one and what draw.io's own table templates do. There is no
#: header *flag* in the format: a heading is a row whose cells are
#: styled like one.
_TABLE_HEAD = "fillColor=#eeeeee;fontStyle=1;align=center;"
_TABLE_BODY = "fillColor=none;"


def _distribute(weights, total: float) -> list[float]:
    """``total`` split between columns in proportion to ``weights``.

    The last column takes the remainder rather than its own share, so
    the parts sum to the total exactly. That is not tidiness:
    ``childLayout=tableLayout`` lays a row out from its cells, and cells
    that do not add up to their row are a table whose right-hand rule
    does not meet its own frame. Nothing repairs that on load, either --
    draw.io's layout manager short-circuits on the root change that
    every file load produces -- so what is written is what is drawn
    until the reader's first edit.

    The parts are rounded to the precision they will be *written* at
    before the remainder is taken, and the remainder is taken from the
    rounded total. Doing it the other way round is how three exact
    thirds of an eighty-unit strip become 26.67 three times and a table
    one hundredth of a unit too tall.
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


#: Clearance between a cell's rule and the text in it, both sides
#: together.
#:
#: **There is no ``mxConstants.LABEL_INSET``** in mxGraph or in
#: draw.io's fork of it -- a search of both trees returns nothing. What
#: is really taken off a cell before the text starts is the *spacing*:
#: ``mxText.prototype.spacing`` is 2 and is added to each of the four
#: sides on top of whatever ``spacingLeft``/``spacingRight`` the style
#: states, and ``mxCellRenderer.rotateLabelBounds`` then narrows the
#: label's bounds by ``spacingLeft + spacingRight`` -- but only while
#: ``labelPosition`` is ``center`` and ``verticalLabelPosition`` is
#: ``middle``, which for a table cell they are. Every cell here says
#: ``spacingLeft=3`` or ``4``, so seven or eight of the twelve is spent
#: before a letter is drawn.
#:
#: The rest is the gutter, and it is generous rather than exact.
#: :func:`~pandid.render.furniture.text_width` sets a bold capital at
#: ``_ADV_BOLD`` = 0,62 em where Helvetica Bold sets ``HPSSH`` at 0,689,
#: eleven per cent wider. That estimate is the only measurement either
#: backend has, so the slack is where the difference between it and the
#: face has to live; at eight, one unit was left and the legend clipped
#: ``HPSSH`` to ``HPSSI``.
_CELL_PAD = 12.0

#: A line of text, as a multiple of its font size, which is what a row
#: has to be at least as tall as.
#:
#: Every label this file writes is an HTML label -- ``html=1``, and
#: draw.io's ``Graph.isHtmlLabel`` also answers yes to anything carrying
#: ``whiteSpace=wrap`` -- so it goes out through
#: ``mxSvgCanvas2D.getTextCss``, which writes ``line-height`` from
#: ``mxConstants.LINE_HEIGHT``. That is 1.2,
#: ``mxConstants.ABSOLUTE_LINE_HEIGHT`` is false and
#: ``mxSvgCanvas2D.lineHeightCorrection`` is 1, so what reaches the
#: browser is the *unitless* ``line-height: 1.2``: a line's box is 1,2
#: times its font size and ``n`` lines are ``n`` times that. (The
#: plain-SVG path measures a single line as the font size flat and only
#: steps by 1,2 between lines. It is not the path taken here.)
#:
#: **Nothing shrinks type to fit.** There is no font-scaling pass
#: anywhere in mxGraph: ``mxText.updateSize`` sets a ``max-height`` and
#: an ``overflow`` and leaves the size alone, and ``TableLayout`` never
#: measures a string at all -- it takes each row's height from the
#: geometry and normalises the rows to fill the table. A row shorter
#: than its own line box loses the difference off the top and bottom of
#: every letter in it: eleven-point values in fourteen-unit rows are
#: fine, and draw.io's default twelve needs 14,4.
_LINE_BOX = 1.2


def _line_box(size: float) -> float:
    """How tall one line at ``size`` draws. See :data:`_LINE_BOX`."""
    return size * _LINE_BOX

#: How a :class:`~pandid.document.TableBox`'s per-column
#: ``l``/``c``/``r`` alignment is said in a draw.io style. The sheet's
#: own default is centred (``draw_table``), so a column that says
#: nothing gets nothing said about it.
_ALIGN_KEY = {"l": "align=left;spacingLeft=4;", "r": "align=right;spacingRight=4;",
              "c": "align=center;"}

#: The weight the drawing frame is ruled at.
#:
#: mxGraph strokes a rectangle on its path, so this lays one unit of ink
#: *inside* the rectangle the title strip docks to. The strip is the
#: sheet's own rectangle and the sheet docks it flush, setting its
#: bottom band's value on a baseline five units above its own edge, so
#: the clearance is in the layout where it belongs.
_FRAME_STROKE = 2.0

#: How far into its line box a baseline falls, as a fraction of the font
#: size.
#:
#: The sheet states a piece of lettering the way SVG does, at a
#: **baseline**; draw.io states one the way CSS does, as a box a line is
#: laid out in. This is the conversion, and it is the only place in this
#: file where the two ways of saying where a letter sits meet.
#:
#: A line box is :data:`_LINE_BOX` = 1,2 em. Inside it the browser
#: stacks half-leading, then the ascent, then the baseline: ``(1,2 -
#: (ascent + descent)) / 2 + ascent``. Helvetica's own ascent and
#: descent are 0,770 and 0,230, which sum to one em and put the baseline
#: at 0,90; Arial, which is what a machine without Helvetica resolves
#: draw.io's font stack to, reports 0,905 and 0,212 and puts it at
#: 0,947. So this is right for one face and about half a unit out at
#: 12,5 for the other, and there is no third number that is right for
#: both -- a browser measures the face it actually loaded and this file
#: cannot. Half a unit is inside the error of
#: :func:`~pandid.render.furniture.text_width`.
_BASELINE = 0.9

#: What a draw.io cell takes off its own rectangle before a letter is
#: drawn.
#:
#: ``mxText.spacing`` is 2 and is added to each of the four sides
#: (``this.spacingLeft = this.spacing + parseInt(spacingLeft || 0)``,
#: and so on), and ``mxCellRenderer.rotateLabelBounds`` then shifts the
#: label bounds by ``mxText.getSpacing()`` and narrows them by
#: ``spacingLeft + spacingRight``. Worked through for each alignment --
#: the ``bounds.x -= margin.x * bounds.width`` at the head of that
#: function is undone by the ``x + this.margin.x * w`` in
#: ``mxText.paint`` -- the answer is the same every time: **the text is
#: laid out inside the cell rectangle inset by two units on every
#: side**. So a cell whose text must start at the sheet's ``x`` begins
#: two units left of it, and one whose text must end there ends two
#: units right.
_TEXT_INSET = 2.0


def _ALIGN_KEYS(col_align, ncol: int) -> list[str]:
    align = list(col_align or [])
    return [_ALIGN_KEY.get(align[c] if c < len(align) else "c", "align=center;")
            for c in range(ncol)]


def columns(rows, sizes, total: float, bold=None) -> list[float]:
    """Column widths for a grid, measured off the text rather than
    shared out.

    A *proportional* share of the box is not a measurement of anything:
    a narrow column beside a wide one gets a narrow share of a box that
    is only just wide enough, which clipped the legend's ``HPSSH`` to
    ``HPSS``. So every column is measured at
    :func:`pandid.render.furniture.text_width`, which is what the SVG
    renderer rules its own columns with, plus the clearance a cell
    needs. Slack goes to the **last** column, the one holding prose; a
    shortfall is shared out in proportion, since a box too narrow for
    its contents has to clip somewhere and the sheet clips it too.

    ``sizes`` is the font size per column, because a title block sets
    its field captions smaller than its values and a column has to be
    measured at the size it will be *drawn* at.

    ``bold`` is the same statement about *weight*, per column, and a
    sequence because the title strip sets its captions light and its
    **values** bold. Bold is the wider face -- ``_ADV_BOLD`` against
    ``_ADV`` is 0,62 against 0,56, eleven per cent -- so a column
    measured in the wrong face clips or wastes the room the column
    beside it needed. The caller states it because the caller is what
    writes the ``fontStyle=1`` into the cell's own style.
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
    """A ruled grid, as draw.io's own table: container, rows, cells.

    ``widths`` are absolute column widths and must sum to ``w``; they
    come from :func:`columns`, or from the sheet's own ruling where it
    has one (a revision strip is ruled at fixed widths and this
    reproduces them). ``start`` is the height of the title band, which
    is a table container's swimlane head and carries the box's title; a
    box with no title is given ``startSize=0`` and no band at all.

    ``font`` is the size the cells are *drawn* at, and it is stated **on
    every cell** rather than left to draw.io or to the table. draw.io's
    default is 12 while every box on the sheet measures its own text at
    its ``font_size``, and a column measured at 11 and drawn at 12 is a
    column three-quarters of a letter too narrow.

    Saying it once on the container does not work, because **mxGraph
    does not inherit a style from a parent cell.**
    ``mxGraph.getCellStyle`` resolves a cell's own style string against
    the stylesheet's default and stops; the only key on a draw.io table
    that reaches down the tree is the literal value ``inherit``, which
    ``Graph.getCellStyle`` special-cases for ``strokeColor``,
    ``fillColor`` and ``gradientColor`` alone -- which is why every row
    and cell here says ``strokeColor=inherit`` in as many words rather
    than simply not mentioning ink. A ``fontSize`` on the container
    styles the container's *own* label, the table's title band, and
    nothing else.

    It goes in ahead of ``col_keys`` so a column that sets a size of its
    own still wins: a style is parsed left to right into a dictionary
    (``mxStylesheet.getCellStyle``), so the last statement of a key
    stands.

    ``row_h`` rules every row at that height and lets the table be as
    tall as its rows come to; the default fills ``h`` instead. Eleven
    title-block fields stretched to fill an eighty-unit strip are rows
    5.6 units tall, which draw no text at all and read as a grid of
    empty rules.

    ``header_last`` puts the heading row at the foot, which is where a
    revision history has it: the newest revision sits against the
    heading and the older ones climb away from it.

    ``heights`` rules the rows at *stated* depths rather than at one
    depth. A revision grid is the case: the sheet rules its revisions at
    14 apiece and leaves whatever is over as blank paper above them, so
    the grid is not a uniform stack and cannot be written as one. They
    are shared out through :func:`_distribute` like the widths, and so
    add up to the table exactly as written.

    ``keys`` are table-level style keys for the caller's own case --
    ``rowLines=0`` for a grid the sheet does not rule across, a
    ``strokeWidth`` for one it rules lighter. They go on the container,
    which is where a table draws its own row and column lines from
    (``TableShape.paintTableForeground`` reads
    ``rowLines``/``columnLines`` off exactly this style).

    ``row_widths`` rules each row's cells at *stated* widths rather than
    at one set of column widths, and it is what lets a row hold a
    **different number of cells** from the row above it: the cell count
    of a row is the length of its own width list. A stream table's
    section heading is the case -- one cell spanning the whole table,
    which is the single rectangle the sheet strokes for it and what a
    merged cell is in this format. A table rules a column line at a
    cell's edge, so a row of one cell is a row with no column line in
    it, which is again what the sheet draws.

    ``cell_keys`` states each cell's own style, ``[row][column]``. It is
    for a table whose cells are not uniform across a row -- a stream
    table fills its heading row, its row labels and its values three
    different greys and sets two of the three left rather than centred.
    It replaces the row-level heading/body style rather than being added
    to it, because a caller that states what every cell is filled with
    does not want a default underneath it saying something else first.
    """
    body = [row for row in rows]
    if headers:
        body = body + [headers] if header_last else [headers] + body
    head_at = (len(body) - 1) if (headers and header_last) else (0 if headers else None)
    ncol = max((len(r) for r in body), default=1)
    # Every dimension is rounded to the precision it is written at
    # *before* the rows and cells are cut out of it, so the parts add up
    # to the whole as written rather than as computed. See
    # :func:`_distribute`.
    w, start = round(float(w), 2), round(float(start), 2)
    if row_h is not None and body:
        h = round(start + row_h * len(body), 2)
    else:
        h = round(float(h), 2)
    widths = _distribute(list(widths)[:ncol] or [1.0] * ncol, w)
    if len(widths) < ncol:
        widths = _distribute([1.0] * ncol, w)
    # Each row's own widths get the same treatment the shared ones do:
    # rounded to the precision they are written at, with the last cell
    # taking the remainder, so a ragged row still meets the table's
    # right-hand rule.
    ragged = [_distribute(rw, w) for rw in row_widths] if row_widths else None
    rows_h = _distribute(list(heights) if heights else [1.0] * len(body),
                         h - start) if body else []

    shape = _TABLE_SHAPE + f"startSize={_num(start)};fontSize={font:g};" + keys
    cell = _TABLE_CELL + f"fontSize={font:g};"
    out = [
        f'        <mxCell id="{cid}" value={_attr(title)} '
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
                f'        <mxCell id="{cid}-r{r}-c{c}" value={_attr(value)} '
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
    """A sheet fill, as draw.io states one.

    The sheet writes its greys the short way (``#eee``) and its paper by
    name (``white``), which is CSS and is what an SVG consumer reads. A
    ``.drawio`` file is read by draw.io's own colour handling before it
    is ever read by a browser, so both are written out in the six-digit
    form its style strings and its colour picker are written in. The
    colour itself does not change: the fill is the sheet's, said the
    other way.
    """
    if colour == "white":
        return "#ffffff"
    if len(colour) == 4 and colour.startswith("#"):
        return "#" + "".join(c * 2 for c in colour[1:])
    return colour


def _stream_cell(cell) -> str:
    """One :class:`~pandid.render.furniture.StreamCell`'s own style.

    Three things per cell, all of them the layout's rather than this
    file's: the grey it is filled with, whether it is set bold, and
    which way it is set. The sheet insets text against a rule by
    :data:`~pandid.render.furniture._STREAM_PAD`; a draw.io cell insets
    its own label by :data:`_TEXT_INSET` before any ``spacingLeft`` is
    added, so what is stated here is the difference and a row label
    starts the same distance in from its rule in either backend.
    """
    if cell.anchor == "start":
        align = f"align=left;spacingLeft={_num(F._STREAM_PAD - _TEXT_INSET)};"
    else:
        align = "align=center;"
    return (f"fillColor={_fill(cell.fill)};" + align
            + ("fontStyle=1;" if cell.bold else ""))


def _stream_table(cid: str, table, x, y) -> list[str]:
    """The stream property table, as draw.io's own table.

    It is a grid on the sheet -- read across for one property, down for
    one stream -- so it is a grid here: a ``shape=table`` a reader can
    widen a column of, rather than lettering arranged to look like one.

    **Ruled where the sheet rules it.** Every cell of a stream table is
    stroked on all four sides
    (:func:`~pandid.render.furniture.draw_stream_table` strokes a
    rectangle apiece), so a rule between every row and every column is
    the sheet's own answer and draw.io's ``rowLines``/``columnLines``
    defaults are right here -- unlike the revision grid, where the
    default put six lines into a strip the sheet rules none across. The
    *weight* is not draw.io's default: the sheet rules this grid at
    :data:`~pandid.render.furniture._CELL_RULE`, the lighter of its two
    weights, and left unsaid the container would rule the whole table at
    1.

    The section headings come through as themselves.
    ``fs.stream_table_sections`` puts a full-width heading row into the
    table before a named property, and the sheet strokes that as one
    rectangle across the whole grid; here it is one cell across the
    whole row (see :func:`_table`'s ``row_widths``), which is the same
    rectangle and is what a merged cell is in this format. A table rules
    its column lines at its cells' own edges, so the row that has one
    cell is ruled the way the sheet rules it: across, and not down.
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
    """A box of free-form lines, for furniture that is not a grid.

    A note list written as sentences has one column, and ruling one
    column into a table would invent a structure the author did not
    write. The lines go into one cell, which is what the sheet draws
    too.

    **The title band is the sheet's**, and it was not here: the box went
    out as one cell holding the title and the notes as one run of
    ``<br>``-separated lines, left-aligned and set at the body size,
    where :func:`~pandid.render.furniture.draw_annotation` centres the
    title, sets it bold and a point larger, and rules a line under it.
    The reader saw ``GENERAL NOTES`` reading as the first note. So it is
    three cells: the box, the title on its own with the sheet's own
    weight and size, and the rule.

    ``font`` for the reason :func:`_table` states one: the box was
    measured off its own ``font_size``
    (:func:`~pandid.render.furniture.measure_annotation`) and draw.io
    would otherwise set it at 12, which is a notes box whose lines are
    wider and taller than the box measured for them.
    """
    box = ("rounded=0;whiteSpace=wrap;html=1;movable=1;"
           f"strokeColor={_INK};fillColor={_NO_FILL};"
           f"strokeWidth={F._BOX_RULE:g};")
    out = _rect(cid, x, y, w, h, box)
    if title:
        # Centred, bold and one point larger, which is draw_annotation's
        # own rule; the band is `_ann_layout`'s so the rule under it
        # lands where the sheet rules it.
        out += _strip_label(f"{cid}-t", ("text", x + w / 2, y + title_h - 6,
                                         title, font + 1, "middle", True, "black"))
        out += _segment(f"{cid}-r", x, y + title_h, x + w, y + title_h,
                        _INK, F._BOX_UNDERLINE)
    # The body, in the sheet's own gutter: `draw_annotation` sets a row
    # at `pad` = 9 from the box edge, less the two units a draw.io cell
    # spends before its first letter (:data:`_TEXT_INSET`).
    body = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
            f"align=left;verticalAlign=top;spacingLeft=7;fontSize={font:g};"
            f"fontColor={_LINE_INK};")
    return out + [
        f'        <mxCell id="{cid}-b" value={_attr("<br>".join(str(r) for r in rows))} '
        f'style={_attr(body)} vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y + title_h)}" '
        f'width="{_num(w)}" height="{_num(h - title_h)}" as="geometry" />',
        '        </mxCell>',
    ]


#: What an :class:`~pandid.document.Annotation` is ruled with, over and
#: above being a table.
#:
#: **No internal rules at all.** The sheet draws one of these as a box
#: with a title bar, one line under the title, and rows of text: no
#: column rules and no row rules. ``rowLines``/``columnLines`` are read
#: off the table container's own style by
#: ``TableShape.paintTableForeground``, and switching both off leaves
#: the container's border and its ``startSize`` title band -- exactly
#: the two rules the sheet does draw.
#:
#: The rows and cells stay. They are what makes the box an editable grid
#: and they cost no ink: every one already says
#: ``top=0;left=0;right=0;bottom=0`` and strokes nothing itself.
_ANNOTATION_KEYS = "rowLines=0;columnLines=0;"


def _fitted(inner, free) -> "tuple[float, float, float]":
    """The scale and offset that centre the drawing in the region left
    for it.

    :func:`pandid.render.svg._fit_scale` for the ratio and
    :meth:`SvgRenderer._fit` for the centring, said as three numbers
    instead of as an SVG transform string. Deriving the ratio here would
    be a second opinion about how big the drawing comes out, and the
    title strip's scale cell reports the first one.
    """
    from pandid.render.svg import _fit_scale

    dx0, dy0, dx1, dy1 = inner
    fx, fy, fw, fh = free
    dw, dh = dx1 - dx0, dy1 - dy0
    s = _fit_scale(dw, dh, free)
    return (s, fx + (fw - s * dw) / 2 - s * dx0, fy + (fh - s * dh) / 2 - s * dy0)


def _rect(cid: str, x, y, w, h, style: str) -> list[str]:
    """A bare rectangle, for the two the drawing frame is built from."""
    return [
        f'        <mxCell id="{cid}" value="" style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" '
        f'height="{_num(h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _segment(cid: str, x1, y1, x2, y2, ink: str, weight: float) -> list[str]:
    """A plain ruled line between two fixed points.

    An edge rather than a vertex, because that is what a line joining
    two points is in this format, and an edge with both terminals stated
    as points and neither as a cell is how draw.io itself writes a
    free-standing rule.

    ``noJump=1`` because it is a **rule and not a connection**. Every
    one of these is furniture -- a zone tick, a title-strip rule, the
    line under a notes box's heading -- and :data:`_NO_HOP` is where
    that is argued.
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


#: Half the box a zone letter is centred in. The glyph is placed by its
#: centre and a draw.io label is centred in its cell, so the cell is
#: drawn around the point rather than from it.
_LABEL_HALF = 8.0


def _label(cid: str, cx, cy, text: str, size: float) -> list[str]:
    """One piece of lettering, centred on a point: a zone's letter or
    numeral.

    ``text`` with no stroke and no fill, which is draw.io's own way of
    writing a caption that is lettering and not a box.
    """
    style = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
             f"align=center;verticalAlign=middle;fontStyle=1;fontSize={size:g};"
             f"fontColor={_LINE_INK};")
    return [
        f'        <mxCell id="{cid}" value={_attr(text)} style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(cx - _LABEL_HALF)}" '
        f'y="{_num(cy - _LABEL_HALF)}" width="{_num(2 * _LABEL_HALF)}" '
        f'height="{_num(2 * _LABEL_HALF)}" as="geometry" />',
        '        </mxCell>',
    ]


def _strip_rule(cid: str, part) -> list[str]:
    """One of the strip's rules, as an edge between two points."""
    _kind, x1, y1, x2, y2, weight = part
    return _segment(cid, x1, y1, x2, y2, _LINE_INK, weight)


def _strip_label(cid: str, part) -> list[str]:
    """One piece of the title strip's lettering, as a draw.io text cell.

    ``part`` is :class:`~pandid.render.furniture.Strip`'s own: a string,
    a size, a ``text-anchor`` and a **baseline**, which is how SVG says
    where a letter sits. The conversion to the box draw.io says it in is
    :data:`_BASELINE` for the baseline and :data:`_TEXT_INSET` for the
    anchor, and both are stated there rather than here.

    The cell is exactly one line box tall plus the inset, so the line
    draw.io lays out in it *is* the line the sheet draws, rather than a
    line floating in a taller box. Nothing wraps and nothing clips:
    ``whiteSpace`` is left unsaid (so ``mxText.wrap`` is false) and
    ``overflow`` defaults to visible, which means a string this file
    measured a shade narrow than the browser sets it runs on past its
    box instead of being folded onto a second line halfway through a
    drawing number. The width does not move the text either way --
    align=left fixes the left edge, align=right the right, align=center
    the centre -- so it is a measurement for the reader's selection
    handle rather than for the layout.
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
        f'        <mxCell id="{cid}" value={_attr(text)} style={_attr(style)} '
        f'vertex="1" parent="1">',
        f'          <mxGeometry x="{_num(left)}" y="{_num(top)}" '
        f'width="{_num(box_w)}" height="{_num(box_h)}" as="geometry" />',
        '        </mxCell>',
    ]


def _rev_table(cid: str, grid) -> list[str]:
    """The revision history, as draw.io's own table.

    The one part of the strip that is a grid, and the one part a reader
    edits: the next thing that happens to an issued drawing is a
    revision, and this is where it is written. So it is a real
    ``shape=table`` with real rows and cells rather than lettering that
    looks like one.

    **Ruled to the sheet's rules and no others.** ``rowLines=0``,
    because the sheet draws no rule *between* revisions -- it tells them
    apart by their lettering, and ruling each one would put six more
    lines into the busiest corner of the drawing.
    ``Graph.getTableLines`` builds one horizontal line per row only
    while ``rowLines`` is not ``0`` and takes the vertical ones from a
    separate ``columnLines``, so switching the first off leaves the
    column rules the sheet does draw. The single horizontal the sheet
    draws -- above the heading row at the foot -- is a segment of its
    own, at the weight the sheet strokes it.

    ``strokeWidth`` is the sheet's own hairline for those column rules.
    The table's outer border is drawn at the same weight and is
    invisible for it: the strip's own two-unit rectangle is on three of
    its edges and the company cell's rule on the fourth, so there is no
    edge of this table that is not already inked by something heavier.

    The blank paper above the oldest revision goes out as blank rows of
    the same depth. That is what the sheet leaves there -- ruled
    vertically, ruled across not at all -- and it is somewhere for the
    reader to type.
    """
    headings = [heading for heading, _cw in grid.cols]
    rows = [row for row in grid.rows]
    # Filler first, then the revisions oldest to newest, then the
    # heading at the foot. The remainder that is not a whole row goes
    # into the topmost filler rather than being ruled as a short row of
    # its own.
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
                          grid.x + grid.w, grid.header_y, _LINE_INK, 1)


def _strip_size(block) -> "tuple[float, float]":
    """How much room the exported title strip needs: the sheet's own
    rectangle.

    ``measure_title_strip``'s answer repeated, which is what makes the
    exported strip land on the same paper the rendered one does.
    """
    return F.measure_title_strip(block)
