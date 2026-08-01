"""draw.io / diagrams.net (``.drawio``) export.

The SVG backend draws a finished picture. This one hands the reader back the
*model*: units as draw.io vertices, streams as draw.io edges between them, so an
author can open the sheet in draw.io, drag a column two hundred units left and
have its lines follow. It is also the way to Visio, which draw.io exports
natively -- going at ``.vsdx`` directly would mean writing a zip of Open
Packaging Convention XML against a stencil model of its own, to arrive where
this arrives.

What makes this cheap here, and expensive for anything else that draws a P&ID,
is that **the symbols in this library are draw.io's own P&ID stencils**, vendored
and converted (see NOTICE). So the export does not trace geometry: it names the
shape. ``mxgraph.pid.valves.gate_valve`` is a key draw.io's stencil registry
already answers to, and a reader who opens the file gets the native, editable
shape rather than a picture of one. The key is not written down anywhere, and
must not be: :func:`scripts.vendor_symbols.drawio_shape_key` derives it from the
two names in the stencil file itself, by draw.io's own rule, at the moment the
artwork is converted, and :attr:`~pandid.render.symbols.Symbol.drawio_shape`
carries it here. A key that has stopped resolving is the quietest failure this
file can have -- draw.io answers one with a plain rectangle rather than an
error, so the sheet still opens and has merely stopped being a P&ID -- which is
why ``tests/test_drawio.py`` walks every symbol the library can draw and holds
each reference against the vendored stencils.

Three things fall out of that arrangement rather than having to be arranged:

* **Sizing.** draw.io scales a stencil into the box the cell is given, stretching
  it where the stencil says ``aspect="variable"`` and centring it uniformly where
  it says ``"fixed"`` -- which is the same question, answered the same way, as
  :func:`pandid.portgeom.ink_box` asks of
  :attr:`~pandid.render.symbols.Symbol.stretchable`, since that flag *is* the
  stencil's own attribute. So the box is the whole of the mapping, and the
  reproportioning ``SCALE`` in ``scripts/vendor_symbols.py`` applies to four
  families needs no undoing: it is already in the box the layout engine used.
  This holds only while every referenced stencil is ``variable`` -- a fixed one
  scaled unevenly would centre against a different aspect at each end -- and a
  test pins that.
* **Ports.** A draw.io fixed connection point is a fraction of the cell's box,
  which is what :func:`pandid.portgeom.port_point` already computes in absolute
  terms; dividing through is the whole conversion.
* **Ink.** ``scripts/mxgraph_to_svg.py`` converts a stencil with its fill state
  starting at ``none`` and every stroke at ``#111``, standing in for the
  ``fillColor``/``strokeColor`` draw.io would have taken from the style. Saying
  those two back in the style is what reproduces the sheet's ink, ``<fillcolor>``
  overrides inside the stencil included, since draw.io honours those itself.

What is *not* free is written down rather than discovered in draw.io.
:data:`_APPROXIMATIONS` is every symbol this library draws itself because draw.io
has no stencil for it, each with the sentence saying what its stand-in loses; the
stand-ins are draw.io *built-ins* rather than stencils, so a reference there
cannot fail to resolve the way a stencil key could. Sheet furniture becomes
labelled boxes (:meth:`DrawioRenderer._furniture`). Nothing on the sheet is
silently absent.

Five pieces of sheet *detail* have no draw.io construct at all, and simply are
not drawn: the semicircle a crossing line hops with, since draw.io decides its
own jumps; the double cross-hatch that marks a pneumatic signal line, which the
renderer lays on top of a solid line, so the line exports solid and reads as
pipe; the fine tap line from a process line to the balloon reading it, which is
drawn by the renderer rather than being a stream and so is not an edge to export;
the searched placement of a stream number, and the leader it gets where no clear
paper was found, both of which become a plain edge label; and a symbol's own
lettering held upright under a turn (the "M" on a motor operator), which draw.io
turns with the shape.

The output is a plain uncompressed ``mxfile``. draw.io reads that as readily as
its compressed form, and it diffs.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple, TYPE_CHECKING

from pandid.portgeom import port_point, unit_box
from pandid.render.svg import (_DIAMOND_BALLOONS, _SIGNAL_DASH, _PROCESS_STROKE,
                               _SIGNAL_STROKE, draws_arrowheads, stream_polyline)
from pandid.render.symbols import (ARROWHEAD, closed_marking, fail_marking,
                                   wears_arrowhead)
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: The one ink the sheet is drawn in, and the one draw.io has to be told to draw
#: it in. ``scripts/mxgraph_to_svg.py`` converts every stencil stroke to this and
#: fills a solid part of one with it; :data:`pandid.render.symbols._BODY_INK` is
#: the same colour, for the same reason. Repeated here rather than imported from
#: the script, which is not part of the installed package.
_INK = "#111"

#: What the fill starts at. Also ``mxgraph_to_svg``'s: a monochrome sheet lets
#: the paper through, and a stencil that wants a part of itself solid says so
#: with its own ``<fillcolor>``, which draw.io reads out of the stencil and not
#: out of the style. So this is the state the converted artwork was drawn under,
#: said back.
_NO_FILL = "none"

#: The ink a *line* is drawn in, which is not quite the ink a symbol is drawn in:
#: the SVG renderer strokes a stream ``black`` and a converted stencil ``#111``,
#: and this is the first of those, written the way a draw.io style writes a
#: colour. A hundredth of a shade apart, and copied rather than unified because
#: unifying them here would be this file quietly editing the sheet.
_LINE_INK = "#000000"

#: pandid turns a symbol clockwise; draw.io names the same four attitudes after
#: the compass point the shape's own east ends up on. ``mxShape.getShapeRotation``
#: adds 90 for ``south``, 180 for ``west`` and 270 for ``north``, so this is that
#: table read the other way. The identity is absent: a cell with no ``direction``
#: is already upright, and saying so would only make every style longer.
_DIRECTION = {90: "south", 180: "west", 270: "north"}


class _Approximation(NamedTuple):
    """A draw.io built-in standing in for a symbol draw.io has no stencil for.

    ``shape`` is a *built-in* shape name and deliberately never a stencil key:
    the whole hazard this file guards against is a reference that silently fails
    to resolve, and mxGraph's own shapes (``ellipse``, ``rhombus``, ``hexagon``,
    ``triangle``, ``line``, and the default rectangle) are compiled into
    draw.io rather than loaded from a file, so they cannot. ``None`` is that
    default rectangle.

    ``flip_h`` mirrors the built-in, for the one shape whose draw.io version
    points the other way. ``fill`` is the colour the symbol's own artwork fills
    itself with, which for a balloon is opaque white and not the transparent
    default: an ISA balloon is drawn over the line it reads and knocks a hole in
    it, and a transparent one would have a process line running across the tag
    inside it. ``lost`` says what the sheet has that the stand-in does not, in
    words, and is the point of the table: an approximation nobody wrote down is
    indistinguishable from a mistake.
    """

    shape: str | None
    lost: str
    flip_h: bool = False
    fill: str = _NO_FILL


#: Every symbol this library draws itself, and what draw.io is asked for instead.
#:
#: These are the fourteen hand-drawn symbols plus the block: draw.io's P&ID
#: library has no stencil for any of them, so there is no key to derive and none
#: is invented. What is here instead is a built-in shape chosen to be the nearest
#: honest statement, with the difference recorded.
#:
#: The balloons are the ones that matter, a P&ID being mostly balloons. Every one
#: of them keeps its outline -- a circle stays a circle, a diamond a diamond, the
#: computer hexagon a hexagon -- and what goes is the *location* marking layered
#: on it: the bar across a panel balloon, the square around a shared-display one,
#: the square behind a logic diamond. So an exported balloon says "instrument"
#: correctly and stops saying where the instrument lives. Nothing here is a
#: silent loss; it is a loss with a sentence against it.
#: Opaque, as every balloon's own artwork is: a balloon is drawn over the line it
#: reads and knocks a hole in it, and a transparent one would have that line
#: running through the tag inside it.
_BALLOON_FILL = "#ffffff"

_APPROXIMATIONS = {
    # --- ISA balloons ------------------------------------------------------
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
                   "shared display", fill=_BALLOON_FILL),
    ("instrument", "computer"): _Approximation(
        # The computer hexagon, drawn as one.
        "hexagon", "", fill=_BALLOON_FILL),
    ("instrument", "sis"): _Approximation(
        "rhombus", "the square around the diamond that puts the logic in a safety "
                   "instrumented system", fill=_BALLOON_FILL),
    ("instrument", "logic"): _Approximation(
        "rhombus", "the square around the diamond that puts the function in a "
                   "logic solver", fill=_BALLOON_FILL),
    ("instrument", "interlock"): _Approximation(
        # A bare diamond, drawn as one.
        "rhombus", "", fill=_BALLOON_FILL),
    # --- junctions and boundaries -----------------------------------------
    # A mixer is a triangle pointing the way the streams combine, which is
    # draw.io's own triangle; a splitter is that triangle turned round, which is
    # that triangle flipped.
    ("mixer", "default"): _Approximation("triangle", ""),
    ("splitter", "default"): _Approximation("triangle", "", flip_h=True),
    # Bare pipe: two segments meeting, with no body at all. draw.io's `line`
    # draws the run across the box and there is nothing in the library that
    # draws the stub, so the stub is what goes. The alternative was a rectangle,
    # which would put a body on a junction that has none.
    ("tee", "default"): _Approximation(
        "line", "the branch stub; the run through the junction is drawn"),
    # An off-page flag is a rectangle with one end drawn to a point. draw.io's
    # `step` would be the shape, but it is one of draw.io's own additions rather
    # than an mxGraph built-in and nothing in this repository pins its name, so
    # the flag squares off rather than the reference being guessed at.
    ("feed", "default"): _Approximation(
        None, "the arrow point on the off-page flag; the tag and the off-page "
              "reference are kept"),
    ("product", "default"): _Approximation(
        None, "the arrow point on the off-page flag; the tag and the off-page "
              "reference are kept"),
    # Built to its belt run rather than scaled to it, so it is written by hand
    # here and not generated. draw.io has "Drier (Roller Conveyor Belt)", which
    # this artwork is adapted from -- but adapted by dropping the drier housing
    # and making the roller spacing a parameter, so referencing it would draw a
    # drier where the sheet has a conveyor. A rectangle is wrong in a way the
    # reader can see; that would be wrong in a way they could not.
    ("conveyor", "default"): _Approximation(
        None, "the belt and its two rollers"),
    # Not an approximation at all, and here to say so: a block flow diagram's
    # block is one rectangle, and draw.io's default vertex is one rectangle.
    ("block", "default"): _Approximation(None, ""),
}

#: A rough character width and line height for the furniture boxes, which are the
#: only thing here that has to be given a size rather than told one. The drawing
#: itself never needs this: every unit and every waypoint arrives with the
#: geometry the layout engine settled. 6.2 is the width the SVG renderer measures
#: a label's halo with, so the two at least agree with each other.
_CHAR_W, _LINE_H = 6.2, 14.0


def _attr(value) -> str:
    """One XML attribute value, quoted and escaped.

    Written out rather than reached for in the standard library because the
    escaping has to be exactly this: draw.io reads a cell's ``value`` as *HTML*,
    so a ``<br>`` between an instrument's letters and its number has to arrive at
    the HTML parser as a tag, which means leaving this function as ``&lt;br&gt;``
    and no further. Escaping the five and only the five is what does that.
    """
    text = str(value)
    for char, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                         ('"', "&quot;"), ("'", "&apos;")):
        text = text.replace(char, entity)
    return f'"{text}"'


def _num(v: float) -> str:
    """A coordinate, at the precision draw.io files are written to.

    Two decimals: the drawing unit is a CSS pixel, so this is a hundredth of a
    pixel, and rounding is what keeps the file diffable against the last export
    instead of churning in the sixteenth digit.
    """
    return f"{round(float(v), 2):g}"


def _fraction(v: float) -> str:
    """A connection point, as draw.io writes one: a fraction of the cell's box.

    Six figures rather than two, because this one is multiplied by a box that may
    be two hundred units across before it becomes a coordinate.
    """
    return f"{round(float(v), 6):g}"


class DrawioRenderer:
    """Renders a Flowsheet to a draw.io ``mxfile`` document.

    Satisfies :class:`pandid.render.Renderer`, so it is a backend beside
    :class:`~pandid.render.svg.SvgRenderer` rather than a converter bolted onto
    one. It reads the same resolved geometry the SVG renderer reads -- frames
    from layout, waypoints from routing, port points from
    :mod:`pandid.portgeom` -- and never re-derives any of it, which is what lets
    the two agree to the pixel.
    """

    def __init__(self, registry=None):
        from pandid.render.symbols import default_registry
        self.registry = registry or default_registry

    # ------------------------------------------------------------------ document

    def render(self, fs: "Flowsheet", *, diagram: "str | None" = None, **opts) -> str:
        """Render the flowsheet to a draw.io document.

        ``diagram`` says which drawing this is, in the spelling
        :meth:`~pandid.flowsheet.Flowsheet.to_svg` takes it: a P&ID draws its
        process lines without arrowheads and so exports them without one.

        Nothing else about the sheet is an option here. The SVG renderer's page
        size, border, stream table, jump direction and debug overlay are all
        statements about a *sheet*, and what this produces is a model on an
        unbounded canvas that its reader will re-lay out by hand; refusing them
        is :meth:`~pandid.flowsheet.Flowsheet.render`'s job, which is where a
        caller can be told rather than ignored.
        """
        arrows = draws_arrowheads(diagram)
        for u in fs.units:
            if u.frame is None:
                raise ValueError(f"Unit '{u.name}' lacks a frame even after layout was run.")

        body: list[str] = []
        # Sheet furniture first: a later cell draws over an earlier one, and the
        # boxes are behind the drawing on the sheet.
        body.extend(self._furniture(fs))
        # Then equipment, then the runs between it, then the balloons -- which is
        # the SVG renderer's own order, and it is that order for the same reason:
        # a balloon's opaque body knocks out the line an in-line element
        # straddles, and a cell drawn earlier is a cell drawn under.
        #
        # That leaves an edge to a balloon naming a cell that appears later in
        # the file, which the format allows: an mxCell's ``source``/``target`` is
        # a reference resolved by id over the whole document, not a back-pointer
        # into what has been read so far. It has to be, since z-order *is* cell
        # order and draw.io lets a user send an edge behind the shapes it joins.
        balloons: list[str] = []
        for i, u in enumerate(fs.units):
            (balloons if u.kind == "instrument" else body).extend(self._vertex(u, i))
        body.extend(self._edges(fs, arrows))
        body.extend(balloons)

        # A stable page id, so exporting the same flowsheet twice gives the same
        # file. draw.io generates a random one; a random one here would make
        # every re-export a diff of one line that means nothing.
        page = hashlib.sha256(fs.name.encode("utf-8")).hexdigest()[:16]
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<mxfile host="pandid" agent="pandid" type="device">',
            f'  <diagram id="pandid-{page}" name={_attr(fs.name)}>',
            # page="0": the drawing is sized to itself, exactly as to_svg() does
            # without a page_size, so there is no paper for draw.io to rule page
            # breaks across. Stating a page here would draw break lines through
            # a sheet that was never laid out to fit them.
            '    <mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" '
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

    # ------------------------------------------------------------------ units

    @staticmethod
    def _id(index: int) -> str:
        """The cell id for the unit at ``index`` in ``fs.units``.

        Derived from the position rather than from the tag: a tag repeats (a trip
        square is one piece of logic drawn wherever it acts), and two cells under
        one id is a file draw.io reads as one cell. ``0`` and ``1`` are the
        model's own root cells, which is what the prefix keeps clear of.
        """
        return f"u{index}"

    @staticmethod
    def _approximation(u, sym) -> "_Approximation | None":
        """The stand-in for a unit draw.io has no stencil for, or None.

        None for every vendored symbol, which is the great majority, and for a
        kind with no artwork at all -- a :class:`~pandid.units.Unit` subclass
        from outside this package, which draws a generic box on the sheet and
        gets draw.io's default vertex here, the same statement either way.
        """
        if sym.drawio_shape:
            return None
        return _APPROXIMATIONS.get((u.kind, getattr(u, "variant", "default")))

    def _placement(self, u, sym) -> "tuple[list[str], bool, bool]":
        """The style keys that place a symbol, and the flips they came out as.

        The flips come back with the keys because the connection points below
        have to be stated in a frame draw.io will then flip, so the two have to
        be worked out together or they disagree about which side of the box a
        nozzle is on.

        A **directional** symbol takes no flip at all, and that is not an
        omission. Its artwork *is* a statement of direction -- a cooler is the
        heater's circle and zigzag with the arrowhead at the other end of the
        diagonal, and nothing else tells the two apart -- so the SVG renderer
        holds the drawing still under a flip and lets only the nozzles move
        (:func:`pandid.render.svg._upright_artwork`). Flipping the draw.io shape
        would draw the sibling symbol and say the opposite thing about which way
        the heat goes. The nozzles still move, because they are stated as
        coordinates below and not inferred from the shape.
        """
        f = u.frame
        rot = int(getattr(f, "orientation", 0) or 0)
        keys = []
        if rot in _DIRECTION:
            # anchorPointDirection=0 rides with the turn, and only with it: it
            # stops draw.io turning this cell's connection points along with the
            # shape, and draw.io only ever would for a cell that states a
            # direction. It is a *vertex* key -- mxGraph reads it off the shape
            # being connected to, not off the edge doing the connecting -- and
            # the reason it is wanted is in :meth:`_constraint`.
            keys += [f"direction={_DIRECTION[rot]}", "anchorPointDirection=0"]
        if sym.directional:
            flip_h, flip_v = False, False
        else:
            flip_h, flip_v = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        # A fitting turned end for end draws its stencil mirrored, and a
        # left-pointing splitter draws draw.io's own triangle mirrored. Both are
        # the *drawing* differing from the shape being named rather than anything
        # the author asked for, so both compose with the placement instead of
        # overriding it -- and both are folded in here, in the one place, because
        # :meth:`_constraint` has to state its fractions in a frame draw.io will
        # then flip and would otherwise be answering from a different sum.
        approx = self._approximation(u, sym)
        if sym.drawio_flip_h or (approx is not None and approx.flip_h):
            flip_h = not flip_h
        if flip_h:
            keys.append("flipH=1")
        if flip_v:
            keys.append("flipV=1")
        return keys, flip_h, flip_v

    def _shape(self, u, sym) -> list[str]:
        """The style keys naming what draw.io is to draw for this unit."""
        if sym.drawio_shape:
            # A vendored stencil: name it and let draw.io draw its own artwork.
            # `outlineConnect=0` is what draw.io's own P&ID palette sets, and it
            # matters here more than there: it stops a stream being dropped onto
            # the shape's outline instead of onto the nozzle it was routed to.
            keys = [f"shape={sym.drawio_shape}", "outlineConnect=0",
                    f"strokeColor={_INK}", f"fillColor={sym.drawio_fill or _NO_FILL}"]
            return keys
        # The stand-in, or draw.io's default vertex. Its mirror, where it needs
        # one, is applied in :meth:`_placement` with everything else that flips.
        approx = self._approximation(u, sym)
        shape = approx.shape if approx is not None else None
        keys = [] if shape is None else [f"shape={shape}"]
        return keys + ["rounded=0", "whiteSpace=wrap", f"strokeColor={_INK}",
                       f"fillColor={approx.fill if approx is not None else _NO_FILL}"]

    def _label(self, u) -> "tuple[str, list[str]]":
        """A unit's label text and the style keys that place it.

        An instrument's tag goes *inside* its balloon, letters over number, which
        is where a sheet writes it and where draw.io's default centred label puts
        it. Everything else is labelled on the side layout picked for it
        (:func:`pandid.layout.coordinates.assign_labels`), which is a resolved
        result on the frame and so is read rather than decided again.

        Two markings ride along on the label because they have nowhere else to
        go: ``NC`` for a valve declared normally closed whose body cannot carry
        the darkening, and the fail-position letters. The renderer places both as
        small labels of their own against the corner of the symbol; there is no
        second label on a draw.io cell, so they follow the tag rather than being
        dropped.
        """
        from pandid.units import split_tag

        if u.kind == "instrument":
            letters, number = split_tag(getattr(u, "type", "") or u.tag,
                                        getattr(u, "number", "") or "")
            # A diamond carries the number alone, as the sheet draws it: its
            # letters are only the tag prefix and there is no room under them.
            if getattr(u, "variant", "default") in _DIAMOND_BALLOONS:
                parts = [number or letters.upper()]
            else:
                parts = [letters.upper(), number]
            text = "<br>".join(part for part in parts if part)
            return text, ["verticalLabelPosition=middle", "verticalAlign=middle",
                          "align=center"]

        lines = [u.tag] if u.tag else []
        if u.kind in ("feed", "product"):
            reference = getattr(u, "reference", "") or ""
            if reference:
                lines.append(reference)
        if closed_marking(u, self.registry) == "NC":
            lines.append("NC")
        letters = fail_marking(u)
        if letters:
            lines.append(letters)
        side = (u.frame.label_pos or "top") if u.frame is not None else "top"
        return "<br>".join(lines), _LABEL_SIDE.get(side, _LABEL_SIDE["top"])

    def _vertex(self, u, index: int) -> list[str]:
        """One unit, as a draw.io vertex."""
        sym = self.registry.for_unit(u)
        x0, y0, x1, y1 = unit_box(u, u.frame)
        placement, _, _ = self._placement(u, sym)
        text, label_keys = self._label(u)
        style = ";".join(["html=1", *self._shape(u, sym), *label_keys, *placement]) + ";"
        return [
            f'        <mxCell id="{self._id(index)}" value={_attr(text)} '
            f'style={_attr(style)} vertex="1" parent="1">',
            f'          <mxGeometry x="{_num(x0)}" y="{_num(y0)}" '
            f'width="{_num(x1 - x0)}" height="{_num(y1 - y0)}" as="geometry" />',
            '        </mxCell>',
        ]

    # ------------------------------------------------------------------ streams

    def _constraint(self, u, sym, port_name: str) -> "tuple[float, float]":
        """Where a stream meets a port, as the fraction draw.io states one in.

        draw.io resolves a fixed connection point by taking the fraction of the
        cell's bounding box, then applying the cell's own flips to it. So the
        fraction to *write* is the one that lands on the port after those flips,
        which is the drawn fraction reflected back through them.

        Two style keys keep that the whole of the arithmetic, and they are set in
        two different places because mxGraph reads them in two different places:

        ``anchorPointDirection=0``, on the **vertex** (:meth:`_placement`, beside
        the ``direction`` it answers), stops draw.io rotating the anchor with the
        shape. It would otherwise state the point in the symbol's own upright
        frame and turn it, which is a second, equivalent way to arrive here --
        and the wrong one to pick, because the point being divided through is
        :func:`~pandid.portgeom.port_point`'s, which has *already* been through
        the turn. Undoing a turn to let draw.io redo it is two chances to
        disagree about a nozzle that is not in doubt.

        ``exitPerimeter=0``/``entryPerimeter=0``, on the **edge**, stop draw.io
        projecting the point out onto the shape's perimeter. A nozzle inboard of
        the box -- a
        dome crown, a shell wall drawn inside the extent because brackets widen
        it -- is where the pipe meets the equipment, and projecting it would slide
        the line off the drawing onto the bounding box, which is exactly the
        distinction :func:`pandid.portgeom.resolve_port` keeps between a port's
        point and its routing anchor.
        """
        px, py = port_point(u, u.frame, port_name)
        x0, y0, x1, y1 = unit_box(u, u.frame)
        w, h = x1 - x0, y1 - y0
        fx = (px - x0) / w if w else 0.5
        fy = (py - y0) / h if h else 0.5
        _, flip_h, flip_v = self._placement(u, sym)
        return (1.0 - fx if flip_h else fx, 1.0 - fy if flip_v else fy)

    def _edges(self, fs, arrows: bool) -> list[str]:
        """Every stream, as a draw.io edge between the two ports it joins."""
        index = {id(u): i for i, u in enumerate(fs.units)}
        labelled: set = set()
        out: list[str] = []
        for n, s in enumerate(fs.streams):
            src_u, dst_u = s.source.owner, s.dest.owner
            points = stream_polyline(s)
            ex, ey = self._constraint(src_u, self.registry.for_unit(src_u), s.source.name)
            tx, ty = self._constraint(dst_u, self.registry.for_unit(dst_u), s.dest.name)
            signal = s.kind in _SIGNAL_KINDS

            keys = [
                "html=1",
                # edgeStyle=none: draw the polyline that was routed, segment for
                # segment, rather than handing the path back to draw.io's own
                # orthogonal router. The router would re-derive a path from the
                # same waypoints and is entitled to a different one, and the
                # first thing a reader does with this file is check that it looks
                # like the sheet. The cost is that a block dragged in draw.io
                # leaves its end leg sloping until the author re-routes it, which
                # is a thing they can see and fix.
                "edgeStyle=none", "rounded=0", "orthogonalLoop=1", "jettySize=auto",
                f"exitX={_fraction(ex)}", f"exitY={_fraction(ey)}",
                "exitDx=0", "exitDy=0", "exitPerimeter=0",
                f"entryX={_fraction(tx)}", f"entryY={_fraction(ty)}",
                "entryDx=0", "entryDy=0", "entryPerimeter=0",
                f"strokeColor={s.color or _LINE_INK}",
                # A signal is drawn at half the weight of the pipe it reads, and
                # the pair is the sheet's whole line-weight vocabulary; see the
                # note on _PROCESS_STROKE in pandid.render.svg.
                f"strokeWidth={_SIGNAL_STROKE if signal else _PROCESS_STROKE}",
            ]
            dash = s.dasharray or _SIGNAL_DASH.get(s.kind, "")
            if dash:
                keys += ["dashed=1", f"dashPattern={dash.replace(',', ' ')}"]
            if arrows and wears_arrowhead(s, self.registry):
                keys += ["endArrow=block", "endFill=1", f"endSize={ARROWHEAD:g}"]
            else:
                keys.append("endArrow=none")
            keys.append("startArrow=none")

            # A number names a *run*, and a run survives the valves and fittings
            # in it: renumber_streams() gives every segment of one the same name,
            # and the sheet writes it once. Writing it on each segment would put
            # the same number on a line three times over, so the first segment to
            # carry it is the one that carries it here too. A signal line is
            # unlabelled on the sheet and stays unlabelled here.
            label = ""
            if not signal and s.name not in labelled:
                labelled.add(s.name)
                label = s.name

            style = ";".join(keys) + ";"
            # The ends are the two nozzles, and they are stated as constraints
            # above; what goes in the array is the turns between them. A run with
            # no turn in it carries no array at all, which is how draw.io writes
            # a straight edge and keeps a straight run from reading as a route
            # that happens to have no points left.
            waypoints = points[1:-1]
            if waypoints:
                geometry = ['          <mxGeometry relative="1" as="geometry">',
                            '            <Array as="points">',
                            *(f'              <mxPoint x="{_num(px)}" y="{_num(py)}" />'
                              for px, py in waypoints),
                            '            </Array>',
                            '          </mxGeometry>']
            else:
                geometry = ['          <mxGeometry relative="1" as="geometry" />']
            out += [
                f'        <mxCell id="s{n}" value={_attr(label)} style={_attr(style)} '
                f'edge="1" parent="1" source="{self._id(index[id(src_u)])}" '
                f'target="{self._id(index[id(dst_u)])}">',
                *geometry,
                '        </mxCell>',
            ]
        return out

    # ------------------------------------------------------------------ furniture

    def _furniture(self, fs) -> list[str]:
        """Title block, annotations and table boxes, as labelled boxes.

        The one place this file gives something a position of its own. Everything
        else arrives with geometry the layout engine settled; the furniture does
        not, because where a box lands on the sheet is worked out inside the SVG
        renderer against a frame that only exists once the paper does, and there
        is no paper here.

        So they are stacked below the drawing, in the order they were added, at a
        size measured off their own text. That is plainly not where the sheet
        rules them, and it is meant to be plain: a box in the wrong place is a
        box the reader drags, where a box quietly missing is a sheet that has
        lost its drawing number. Their content is exact -- every field, every
        row, every revision.
        """
        from pandid.document import TableBox

        boxes: list[tuple[str, list[str]]] = []
        if fs.title_block is not None:
            boxes.append(_title_block_text(fs.title_block))
        for item in getattr(fs, "annotations", []):
            rows = [row if isinstance(row, str) else "  ".join(str(c) for c in row)
                    for row in getattr(item, "rows", [])]
            if isinstance(item, TableBox):
                # A table's header row is a row like any other once the ruling
                # is gone, and it goes first because that is what it is.
                rows = ([" | ".join(str(c) for c in item.headers)] if item.headers
                        else []) + [" | ".join(str(c) for c in row) for row in item.rows]
            # Anything else docked to the sheet is taken on the two things every
            # box has, a title and some rows, rather than being skipped for not
            # being one of the two classes this module knows. A box added later
            # comes out as a box; the alternative is a sheet that has quietly
            # lost its notes.
            boxes.append((getattr(item, "title", "") or "", rows))
        if not boxes:
            return []

        # Below the drawing, which is the only region guaranteed clear of it.
        x0 = min(unit_box(u, u.frame)[0] for u in fs.units) if fs.units else 0.0
        y = (max(unit_box(u, u.frame)[3] for u in fs.units) if fs.units else 0.0) + 60.0
        out: list[str] = []
        for n, (title, rows) in enumerate(boxes):
            lines = [title] + rows if title else list(rows)
            w = max((len(line) for line in lines), default=20) * _CHAR_W + 24.0
            h = max(len(lines), 1) * _LINE_H + 16.0
            style = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                     f"strokeColor={_INK};fillColor={_NO_FILL};")
            out += [
                f'        <mxCell id="f{n}" value={_attr("<br>".join(lines))} '
                f'style={_attr(style)} vertex="1" parent="1">',
                f'          <mxGeometry x="{_num(x0)}" y="{_num(y)}" '
                f'width="{_num(w)}" height="{_num(h)}" as="geometry" />',
                '        </mxCell>',
            ]
            y += h + 20.0
        return out


#: How a label on each of the four sides of a box is asked for in a draw.io
#: style. ``verticalLabelPosition``/``labelPosition`` put the label's *box*
#: outside the cell, and the ``verticalAlign``/``align`` beside each pull the
#: text back against the cell it belongs to; stating only the first of each pair
#: leaves the text centred on the cell it was just moved off.
_LABEL_SIDE = {
    "top": ["verticalLabelPosition=top", "verticalAlign=bottom", "align=center"],
    "bottom": ["verticalLabelPosition=bottom", "verticalAlign=top", "align=center"],
    "left": ["labelPosition=left", "align=right",
             "verticalLabelPosition=middle", "verticalAlign=middle"],
    "right": ["labelPosition=right", "align=left",
              "verticalLabelPosition=middle", "verticalAlign=middle"],
    "center": ["verticalLabelPosition=middle", "verticalAlign=middle", "align=center"],
}


def _title_block_text(block) -> "tuple[str, list[str]]":
    """A title block's fields as a heading and a list of lines.

    Every field that was filled in, named, in the order the strip rules them.
    A blank field is left out rather than ruled empty, which is what the sheet
    does with one too.
    """
    rows = []
    for label, value in (("Client", block.client), ("Project", block.project),
                         ("Company", block.company), ("Drawing", block.drawing_number),
                         ("Status", block.status), ("Scale", block.scale),
                         ("Sheet", f"{block.sheet} of {block.of_sheets}"
                          if block.sheet or block.of_sheets else ""),
                         ("Date", block.date), ("Drawn", block.drawn_by),
                         ("Checked", block.checked_by), ("Approved", block.approved_by)):
        if value:
            rows.append(f"{label}: {value}")
    for rev in block.revisions:
        parts = [p for p in (rev.rev, rev.date, rev.description, rev.by,
                             rev.checked, rev.approved) if p]
        if parts:
            rows.append("Rev " + "  ".join(parts))
    title = " - ".join(p for p in (block.title, block.subtitle) if p)
    return title, rows
