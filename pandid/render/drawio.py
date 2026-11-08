"""Export a flowsheet to a draw.io (``.drawio``) file.

Units become vertices that name draw.io stencils, and streams become
edges between their ports.
"""

from __future__ import annotations

import base64
import hashlib
import html
import math
import re
import urllib.parse
import zlib
from datetime import datetime
from typing import NamedTuple, TYPE_CHECKING
from xml.sax.saxutils import escape

from pandid.package import frame as package_frame
from pandid.portgeom import _flag_reference, _xform, port_point, symbol_to_box, unit_box
from pandid.render.iso_parts import PART_STROKE as _PART_STROKE
from pandid.render import furniture as F
from pandid.render import generator
from pandid.render import svg as _svg
from pandid.render.escape import fmt, writable
from pandid.render.svg import (_DIAMOND_BALLOONS, _ENCLOSURE_STROKE,
                               _FIT_CODES,
                               _LEADER_HEAD, _scale_text, _Sheet, _TAG_TYPE,
                               _SIGNAL_DASH, _stream_rung, _TAP_DASH, TITLE,
                               fit_issue, HOP_R,
                               NUMBER_TYPE, PACKAGE_DASH, boundary_flag, diagram_plan,
                               enclosure_shape, label_findings, package_labels,
                               draws_arrowheads, drawn_codes, flange_marks, impulse_tap,
                               quadrant_labels,
                               resolve_connections, sheet_connections,
                               stream_numbers, stream_polyline, tap_lines, tap_route)
from pandid.render.symbols import (ARROWHEAD, _BODY_INK, TRAP_BODY_D, TRAP_LEAD, TRAP_W,
                                   closed_marking, default_registry, fail_marking,
                                   overlay_boxes, wears_arrowhead)
from pandid.render.weights import LineWeight
from pandid.streams import SIGNAL_KINDS as _SIGNAL_KINDS
from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame
    from pandid.render.symbols import Symbol

_INK = _BODY_INK

# Fill for shapes this module draws itself.
_NO_FILL = "none"

# Fill for a vendored stencil.
_PAPER = "#ffffff"

# No stroke: draw.io drops a key set to ``none``.
_NO_STROKE = "none"

_LINE_INK = "#000000"

# Style for edges that are not streams: they never hop.
_NO_HOP = "noJump=1;"


def _hops(polylines: dict, direction: str,
          style: str = "arc") -> "tuple[list, set, set]":
    """Return the stream edge order, the hopping edges and lost hops.

    Write each hopping edge after the edges it hops, unless they form a
    cycle. A hopping edge keeps ``jumpStyle`` only when every edge that
    hops it, or that it crosses flat, is written after it.

    Parameters
    ----------
    polylines : dict
        ``{key: points}`` for every stream, in write order.
    direction : str
        ``"vertical"`` or ``"horizontal"``.
    style : str, default="arc"
        ``crossing_style``; ``"plain"`` hops nothing.

    Returns
    -------
    order : list
        Keys in write order.
    kept : set
        Keys that carry ``jumpStyle``.
    lost : set
        ``(hopper, crossed, x, y)`` for each sheet hop drawn flat.
    """
    keys = list(polylines)
    if style == "plain":
        return keys, set(), set()
    # The edges each edge must be written after.
    after: dict = {key: set() for key in keys}
    # The edges that hop each edge.
    hopped_by: dict = {key: set() for key in keys}
    hops: set = set()
    # Hops keyed by position: two runs may cross more than once.
    jumps: set = set()
    # Crossings the sheet draws flat, keyed by both edges.
    marginal: dict = {key: set() for key in keys}
    # Hops of a run over itself.
    own: set = set()
    for hop_key, _seg, cross_key, x, y, room in _svg.crossings(polylines, direction):
        if hop_key == cross_key:
            if room:
                own.add((hop_key, cross_key, x, y))
        elif not room:
            marginal[hop_key].add(cross_key)
            marginal[cross_key].add(hop_key)
        else:
            hops.add(hop_key)
            after[hop_key].add(cross_key)
            hopped_by[cross_key].add(hop_key)
            jumps.add((hop_key, cross_key, x, y))
    if not hops:
        return keys, hops, own
    # Topological sort, lowest original index first.
    order: list = []
    done: set = set()
    while len(done) < len(keys):
        ready = [key for key in keys if key not in done and not (after[key] - done)]
        if not ready:  # a cycle
            break
        order.append(ready[0])
        done.add(ready[0])
    # Edges in a cycle or ordered after one, in stream order.
    order += [key for key in keys if key not in done]
    # An edge keeps its style only if every edge that hops it, and every
    # edge it crosses flat, is written after it.
    rank = {key: n for n, key in enumerate(order)}
    kept = {key for key in hops
            if all(rank[other] > rank[key] for other in hopped_by[key])
            and all(rank[other] > rank[key] for other in marginal[key])}
    lost = {(hop_key, cross_key, x, y)
            for hop_key, cross_key, x, y in jumps
            if hop_key not in kept or rank[cross_key] > rank[hop_key]}
    return order, kept, lost | own


# Clockwise turn to draw.io ``direction``.
_DIRECTION = {90: "south", 180: "west", 270: "north"}


def _placed_rect(frame, x: float, y: float, w: float, h: float
                 ) -> "tuple[float, float, float, float]":
    """Return a rectangle in symbol fractions as cell fractions.

    The rectangle turns and mirrors with the parent ``frame``.

    Parameters
    ----------
    frame : Frame
        Parent unit's frame.
    x : float
        Left edge in symbol fractions.
    y : float
        Top edge in symbol fractions.
    w : float
        Width in symbol fractions.
    h : float
        Height in symbol fractions.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x, y, w, h)`` in cell fractions.
    """
    rot, mirror_x, mirror_y = _xform(frame)
    corners = [symbol_to_box(px, py, 1.0, 1.0, rot, mirror_x, mirror_y)[:2]
               for px, py in ((x, y), (x + w, y + h))]
    xs = sorted(point[0] for point in corners)
    ys = sorted(point[1] for point in corners)
    return xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]


class _Fit(NamedTuple):
    """Map drawing coordinates onto the page.

    Attributes
    ----------
    scale : float
        Drawing units to page units.
    dx : float
        Horizontal offset after scaling.
    dy : float
        Vertical offset after scaling.
    """
    scale: float
    dx: float
    dy: float

    def at(self, x: float, y: float) -> "tuple[float, float]":
        """Return a drawing point on the page.

        Parameters
        ----------
        x : float
            Drawing x.
        y : float
            Drawing y.

        Returns
        -------
        tuple[float, float]
            Page point.
        """
        return (self.dx + self.scale * x, self.dy + self.scale * y)

    def box(self, b) -> "tuple[float, float, float, float]":
        """Return a drawing box on the page.

        Parameters
        ----------
        b : tuple
            Drawing box ``(x0, y0, x1, y1)``.

        Returns
        -------
        tuple[float, float, float, float]
            Page box ``(x0, y0, x1, y1)``.
        """
        return (*self.at(b[0], b[1]), *self.at(b[2], b[3]))

    def length(self, v: float) -> float:
        """Return a length scaled to the page.

        Parameters
        ----------
        v : float
            Length in drawing units.

        Returns
        -------
        float
            Length in page units.
        """
        return self.scale * v


def drawio_stencil(svg: str, width: float, height: float,
                   offset: "tuple[float, float]" = (0.0, 0.0), scale: float = 1.0) -> str:
    """Return a draw.io inline stencil drawing an artwork's outlines.

    The artwork's paths, of ``M``, ``L``, ``A`` and ``Z`` commands in
    absolute coordinates, and its rectangles, circles and lines become
    the stencil's own geometry, so draw.io draws them as placed rather
    than stretching a library shape. An element drawn thinner than the
    artwork's widest stroke gets its own fixed width, one filled solid
    keeps its colour, and a dashed one is dashed.

    Parameters
    ----------
    svg : str
        Artwork.
    width, height : float
        The stencil's box.
    offset : tuple[float, float], default=(0.0, 0.0)
        Where the artwork's origin falls in the box.
    scale : float, default=1.0
        Drawn width of a stroke one unit wide.

    Returns
    -------
    str
        A ``stencil(...)`` shape name for a cell's style.
    """
    dx, dy = offset
    base = max((float(w) for w in re.findall(r'stroke-width="([\d.]+)"', svg)), default=1.0)
    out, drawn = [], base
    for tag, attrs in re.findall(r"<(path|rect|circle|line)\b([^>]*?)/?>", svg):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
        stroke = float(a.get("stroke-width", base))
        if stroke != drawn:
            # A fixed width, not scaled with the stencil's box.
            out.append(f'<strokewidth width="{fmt(stroke * scale, 4)}" fixed="1"/>')
            drawn = stroke
        fill = a.get("fill", "none")
        solid = fill not in ("none", "white")
        styled = solid or "stroke-dasharray" in a
        if styled:
            # Set the fill or dash for this element alone.
            out.append("<save/>")
            out.append(f'<fillcolor color="{fill}"/>' if solid else "")
            out.append('<dashed dashed="1"/>' if "stroke-dasharray" in a else "")
        if tag == "rect":
            out.append(f'<rect x="{fmt(float(a["x"]) + dx, 4)}" y="{fmt(float(a["y"]) + dy, 4)}" '
                       f'w="{fmt(float(a["width"]), 4)}" h="{fmt(float(a["height"]), 4)}"/>')
        elif tag == "circle":
            r = float(a["r"])
            out.append(f'<ellipse x="{fmt(float(a["cx"]) - r + dx, 4)}" '
                       f'y="{fmt(float(a["cy"]) - r + dy, 4)}" '
                       f'w="{fmt(2 * r, 4)}" h="{fmt(2 * r, 4)}"/>')
        elif tag == "line":
            out.append(f'<path><move x="{fmt(float(a["x1"]) + dx, 4)}" '
                       f'y="{fmt(float(a["y1"]) + dy, 4)}"/>'
                       f'<line x="{fmt(float(a["x2"]) + dx, 4)}" '
                       f'y="{fmt(float(a["y2"]) + dy, 4)}"/></path>')
        else:
            steps, tokens = [], a["d"].replace(",", " ").split()
            i = 0
            while i < len(tokens):
                cmd, i = tokens[i], i + 1
                if cmd == "Z":
                    steps.append("<close/>")
                    continue
                n = 7 if cmd == "A" else 2
                v = [float(t) for t in tokens[i:i + n]]
                i += n
                x, y = fmt(v[-2] + dx, 4), fmt(v[-1] + dy, 4)
                if cmd == "A":
                    steps.append(f'<arc rx="{fmt(v[0], 4)}" ry="{fmt(v[1], 4)}" '
                                 f'x-axis-rotation="{fmt(v[2], 4)}" '
                                 f'large-arc-flag="{int(v[3])}" sweep-flag="{int(v[4])}" '
                                 f'x="{x}" y="{y}"/>')
                else:
                    steps.append(f'<{"move" if cmd == "M" else "line"} x="{x}" y="{y}"/>')
            out.append(f"<path>{''.join(steps)}</path>")
        out.append("<stroke/>" if fill == "none" else "<fillstroke/>")
        if styled:
            out.append("<restore/>")
    xml = (f'<shape w="{fmt(width, 4)}" h="{fmt(height, 4)}" aspect="variable" '
           f'strokewidth="inherit"><foreground>{"".join(out)}</foreground></shape>')
    # draw.io reads a stencil as raw-deflated, base64'd encodeURIComponent text.
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = urllib.parse.quote(xml, safe="-_.!~*'()").encode("ascii")
    return f"stencil({base64.b64encode(packer.compress(data) + packer.flush()).decode('ascii')})"


class _Piece(NamedTuple):
    """A draw.io built-in shape placed inside a stand-in's cell.

    Attributes
    ----------
    shape : str or None
        Built-in shape name; ``None`` is the rectangle.
    x : float
        Left edge as a fraction of the cell.
    y : float
        Top edge as a fraction of the cell.
    w : float
        Width as a fraction of the cell.
    h : float
        Height as a fraction of the cell.
    """

    shape: "str | None"
    x: float
    y: float
    w: float
    h: float


class _Approximation(NamedTuple):
    """A draw.io built-in standing in for a symbol with no stencil.

    Attributes
    ----------
    shape : str or None
        Built-in shape name; ``None`` is the rectangle.
    lost : str
        Symbol parts missing from the stand-in, or empty.
    flip_h : bool
        Mirror the built-in.
    fill : str
        Fill colour.
    stroke : str
        Ink colour.
    weight : float
        Stroke width.
    keys : tuple
        Extra style keys.
    inscribed : str or None
        A second built-in filling the same box.
    pieces : tuple[_Piece, ...]
        Built-ins placed within the cell instead of ``shape``.
    marks : tuple[_Piece, ...]
        Built-ins drawn over ``shape``.
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
    marks: "tuple[_Piece, ...]" = ()


def _location_bars(variant: str, shape: "str | None") -> "tuple[_Piece, ...]":
    """Return a balloon's location bars as line pieces across a stand-in.

    Each bar keeps its height in the balloon and runs between the
    stand-in's sides.

    Parameters
    ----------
    variant : str
        Registered balloon variant.
    shape : str or None
        Stand-in outline: ``"ellipse"``, ``"hexagon"``, ``"rhombus"``,
        or ``None`` for the rectangle.

    Returns
    -------
    tuple[_Piece, ...]
        One level line per bar, as fractions of the balloon.
    """
    sym = default_registry.get("instrument", variant)
    out = []
    for y in re.findall(r'<line x1="[\d.]+" y1="([\d.]+)"', sym.svg):
        off = abs(float(y) / sym.height - 0.5)
        # Inset of the stand-in's side at this height.
        inset = {"ellipse": 0.5 - math.sqrt(0.25 - off * off), "rhombus": off,
                 "hexagon": off / 2}.get(shape or "", 0.0)
        out.append(_Piece("line", inset, float(y) / sym.height, 1.0 - 2 * inset, 0.0))
    return tuple(out)


def _balloon(shape: "str | None", variant: str,
             inscribed: "str | None" = None) -> _Approximation:
    """Return the stand-in for a balloon, its location bars drawn over it.

    Parameters
    ----------
    shape : str or None
        Built-in outline; ``None`` is the rectangle.
    variant : str
        Registered balloon variant.
    inscribed : str or None, optional
        Built-in drawn inside the outline.

    Returns
    -------
    _Approximation
        Stand-in at the detail weight (ISO 10628-1 5.3.1 c)).
    """
    return _Approximation(shape, "", fill=_BALLOON_FILL, weight=LineWeight.DETAIL.width,
                          inscribed=inscribed, marks=_location_bars(variant, shape))


# Relative aspect change allowed before a symbol counts as reshaped.
_ASPECT_SLACK = 1e-3

#: Warning code for a stand-in that loses part of its symbol.
APPROXIMATED = "drawio-approximated"

#: Warning code for a crossing the sheet hops and the export draws flat.
HOP_DROPPED = "drawio-hop-dropped"


_BALLOON_FILL = "#ffffff"

#: Drawings exported as an inline stencil of their own outline.
OWN_OUTLINE = frozenset({
    ("silo", "default"), ("silo", "bunker"), ("mixer_settler", "default"),
    ("deaerator", "default"),
    ("crystallizer", "default"), ("flotation_cell", "default"),
    ("blower", "general"), ("blower", "centrifugal"), ("blower", "axial"),
    ("furnace", "general"), ("furnace", "combustion_chamber"),
    ("pump", "progressive_cavity"), ("pump", "reciprocating"), ("pump", "diaphragm"),
    ("pump", "lobe"), ("pump", "vertical_turbine"),
    ("fitting", "magnetic"), ("fitting", "ultrasonic_clamp_on"),
    ("fitting", "thermal_mass"), ("fitting", "flume"),
    ("valve", "lift_check"), ("valve", "swing_check"), ("valve", "swing_check_form_2"),
    ("valve", "ball_check"), ("valve", "dual_plate_check"), ("valve", "stop_check"),
    ("valve", "foot"),
    ("tank", "flat_roof"), ("tank", "open_top"),
})

# The built-in drawn for each symbol with no draw.io stencil, and what
# it loses.
_APPROXIMATIONS = {
    # Instrument balloons: a circle, a circle in a square, a hexagon, a
    # diamond in a square and a diamond, each in the field, central and
    # subsidiary.
    **{("instrument", variant): _balloon(shape, variant, inscribed)
       for shape, inscribed, variants in (
           ("ellipse", None, ("default", "panel", "aux")),
           (None, "ellipse", ("shared_field", "shared", "shared_subsidiary")),
           ("hexagon", None, ("computer", "computer_central", "computer_subsidiary")),
           (None, "rhombus", ("sis", "sis_central", "sis_subsidiary",
                              "logic", "logic_central", "logic_subsidiary")),
           ("rhombus", None, ("interlock", "interlock_central", "interlock_subsidiary")))
       for variant in variants},
    # Junctions and boundaries.
    ("mixer", "default"): _Approximation("triangle", ""),
    ("splitter", "default"): _Approximation("triangle", "", flip_h=True),
    # An invisible cell that every edge meets at its centre.
    ("tee", "default"): _Approximation(None, "", stroke=_NO_STROKE),
    # Drawn by DrawioRenderer._shape.
    ("feed", "default"): _Approximation(None, ""),
    ("product", "default"): _Approximation(None, ""),
    ("conveyor", "default"): _Approximation(
        None, "the belt and its two rollers"),
    ("block", "default"): _Approximation(None, ""),
    ("reactor", "tubular"): _Approximation(
        None, "the tube pass inside the shell"),
    # Composed bodies: the mark is a child cell.
    **{("separator", v): _Approximation(
        None, "the V bottom the collected phase draws off through")
       for v in ("gravity", "electrostatic", "electromagnetic")},
    **{("crusher", v): _Approximation(
        None, "the trapezoid outline and the two jaws drawn down it")
       for v in ("default", "cone", "hammer", "impact", "jaw", "roller")},
    **{("mill", v): _Approximation(
        None, "the trapezoid outline and its chamfered top corners")
       for v in ("default", "hammer", "impact", "roller")},
    ("mill", "vibration"): _Approximation(
        None, "the trapezoid outline, its chamfered top corners and the drum"),
    ("crushing_machine", "default"): _Approximation(
        None, "the trapezoid outline"),
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
    ("kiln", "default"): _Approximation(
        None, "the shell's fall from feed end to discharge, its riding rings and its drive"),
    ("kiln", "fluidized_bed"): _Approximation(
        None, "the dished crown, the windbox cone and the distributor grid over it"),
    ("kiln", "shaft"): _Approximation(
        None, "the charging cone, the discharge cone and the calcining zone between them"),
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
    ("conveyor", "screw"): _Approximation(
        None, "the screw's axis and the turns of its flight"),
    ("elevator", "default"): _Approximation(
        None, "the belt, its two pulleys and the loading and discharge chutes"),
    ("elevator", "z_form"): _Approximation(
        None, "the Z-shaped casing, the belt's three runs and its four pulleys"),
    ("boiler", "default"): _Approximation(
        None, "the shell's own outline and the dome on its crown"),
    ("stack", "default"): _Approximation(
        None, "the tapered shaft and the foundation flange under it"),
    ("flare", "default"): _Approximation(
        None, "the shaft and the flame on its tip"),
    ("dryer", "general"): _Approximation(
        None, "the casing's chamfered top corners"),
    ("dryer", "shelf"): _Approximation(
        None, "the casing's chamfered top corners and the three shelf lines"),
    ("dryer", "turbo"): _Approximation(
        None, "the casing's chamfered top corners and the rotor shaft and discs"),
    ("dryer", "belt"): _Approximation(
        None,
        "the casing's chamfered top corners and the two rollers the belt runs on"),
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
    ("feeder", "general"): _Approximation(
        None, "the circle outline and the Z mark drawn inside it"),
    ("feeder", "rotary_valve"): _Approximation(
        None, "the circle outline and the six-spoke rotor drawn inside it"),
    ("feeder", "rotary_table"): _Approximation(
        None, "the table, its shaft and the rotation arrow drawn on it"),
    ("feeder", "metering"): _Approximation(
        None, "the beam, its two pans and the fulcrum triangle under it"),
    ("spray_nozzle", "default"): _Approximation(
        None, "the header line and the three-pronged spray fan under it"),
    ("fitting", "rotary_mixer"): _Approximation(
        None, "the box, its flow axis and the two mixing elements in it",
        weight=LineWeight.DETAIL.width),
    ("fitting", "mixing_path"): _Approximation(
        None, "the box and the three mixing elements in it", weight=LineWeight.DETAIL.width),
    # Two line leads and an ellipse body, in the symbol's proportions.
    ("fitting", "steam_trap"): _Approximation(
        None,
        "the 45-degree diameter across the body and the discharge half filled below it",
        weight=LineWeight.DETAIL.width,
        pieces=(
            _Piece("line", 0.0, 0.0, TRAP_LEAD / TRAP_W, 1.0),
            _Piece("ellipse", TRAP_LEAD / TRAP_W, 0.0, TRAP_BODY_D / TRAP_W, 1.0),
            _Piece("line", (TRAP_LEAD + TRAP_BODY_D) / TRAP_W, 0.0,
                   TRAP_LEAD / TRAP_W, 1.0),
        )),
    ("kneader", "default"): _Approximation(
        None, "the casing and the wave the blades draw across it"),
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

# Built-in stand-ins for ISO 10628-2 parts with no draw.io shape, keyed
# by ``(group, name)``.
_PART_APPROXIMATIONS = {
    (26, "leg"): _Approximation("partialRectangle", "", keys=("top=0",)),
    (26, "bracket"): _Approximation(
        "triangle", "the gusset's right angle: draw.io's triangle is isoceles",
        keys=("direction=north",)),
    (26, "skirt"): _Approximation(
        "partialRectangle", "the two feet turned in at the base ring",
        keys=("top=0", "bottom=0")),
    (26, "ring"): _Approximation("partialRectangle", "", keys=("right=0",)),
    (26, "manhole"): _Approximation(
        "partialRectangle", "the flanges and the gap before the cover", keys=("right=0",)),
    (26, "manhole_up"): _Approximation(
        "partialRectangle", "the flanges and the gap before the cover", keys=("bottom=0",)),
    (26, "manhole_down"): _Approximation(
        "partialRectangle", "the flanges and the gap before the cover", keys=("top=0",)),
    (26, "socket"): _Approximation(
        "partialRectangle", "the stub from the wall to the flange",
        keys=("top=0", "right=0", "bottom=0")),
    (26, "socket_up"): _Approximation(
        "partialRectangle", "the stub from the wall to the flange",
        keys=("left=0", "right=0", "bottom=0")),
    (26, "socket_down"): _Approximation(
        "partialRectangle", "the stub from the wall to the flange",
        keys=("left=0", "right=0", "top=0")),
    (27, "tray"): _Approximation("line", ""),
    (27, "baffle_tray"): _Approximation("line", "the riser at the deck's end"),
    (27, "bubble_cap_tray"): _Approximation("line", "the cap over the deck's opening"),
    (27, "valve_tray"): _Approximation("line", "the valve lifted clear of the deck"),
    (27, "sieve_tray"): _Approximation(
        "line", "", keys=("dashed=1", "dashPattern=8 4")),
    (27, "filter_insert"): _Approximation(
        "line", "", keys=("dashed=1", "dashPattern=8 4 4 4")),
    (27, "fluidised_bed"): _Approximation(
        None, "the staggered field of dots; the box is the bed's extent"),
    (27, "packing"): _Approximation(
        "partialRectangle", "the X across the bed",
        keys=("left=0", "right=0", "dashed=1", "dashPattern=8 4")),
    (20, "motor"): _Approximation("ellipse", "the M inside the circle"),
    (29, "gravity"): _Approximation(
        "triangle", "the arrow's shaft above its head", keys=("direction=south",)),
    (29, "electrostatic"): _Approximation(
        "partialRectangle", "the leads going out from the two plates",
        keys=("top=0", "bottom=0")),
    (29, "electromagnetic"): _Approximation(
        "line", "the three turns standing on the coil's baseline"),
    (29, "disc"): _Approximation(
        None, "the shaft, its two plates and the arms between them; "
              "the box is the rotor's extent"),
    (29, "crushing"): _Approximation(None, "the X between the box's corners"),
    (29, "gear"): _Approximation(None, "the two meshing wheels; the box is the pair's extent"),
    (29, "hammer"): _Approximation(
        None, "the four hammers on their rotor; the box is the rotor's extent"),
    (29, "impact"): _Approximation(
        None, "the rotor at the centre and the four arms out to the corners"),
    (29, "jaw"): _Approximation("line", "the circle the jaw's line runs into"),
    (29, "liquid"): _Approximation("line", "the two dips scalloped out of the line"),
    (29, "roller"): _Approximation(None, "the two rolls; the box is the pair's extent"),
    (29, "cone"): _Approximation(
        "triangle", "the trapezoid's flat top: draw.io's triangle comes to a point",
        keys=("direction=north",)),
    (29, "jet"): _Approximation(
        "ellipse", "the diameter and the two chords drawn across the circle"),
    (29, "vibration"): _Approximation(
        None, "the two arrows and the opposite ways they point"),
}

class _Tags(NamedTuple):
    """Result of the sheet's equipment-tag placement pass.

    Attributes
    ----------
    at : dict
        ``id(unit)`` -> ``(side, dx, dy, near)``: the offset from the side's
        spot, and the offset from the middle of the cell's side to the middle
        of the tag halo's near edge, or ``None`` with no halo.
    plates : list
        Opaque boxes of tags and ``NC``/fail letters, where the sheet
        draws them and where draw.io writes them.
    blocks : dict
        ``id(unit)`` -> the label item of a balloon's function block.
    """
    at: dict
    plates: list
    blocks: dict


def _tag_pass(fs, joints: "str | None", direction: str) -> "_Tags":
    """Place the equipment tags with the SVG renderer's methods.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out flowsheet.
    joints : str or None
        Sheet joint default, whose flange marks tags avoid.
    direction : str
        ``jump_direction``.

    Returns
    -------
    _Tags
        Tag placements and plates.
    """
    from pandid.render.svg import _unit_label_box, unit_tags

    at: dict = {}
    plates: list = []
    blocks: dict = {}
    for u, item, items in unit_tags(fs, joints, direction):
        block = label_box(u, item, items)
        plates += [b for b in (*map(_unit_label_box, items), block) if b is not None]
        if item is not None and u.frame is not None:
            at[id(u)] = _tag_at(u, item)
        blocks.update((id(u), spot) for spot in items if spot[4] == "function")
    return _Tags(at, plates, blocks)


def _tag_at(u, tag) -> tuple:
    """Return where a tag sits against its side, for draw.io.

    Parameters
    ----------
    u : Unit
        Placed unit.
    tag : tuple
        Its tag item.

    Returns
    -------
    tuple
        ``(side, dx, dy, near)``: the offset from the side's spot, and
        the offset from the middle of the cell's side to the middle of
        the tag halo's near edge, or ``None`` with no halo.
    """
    from pandid.render.svg import SvgRenderer, _unit_label_box

    f = u.frame
    x, y, w, h = f.x, f.y, f.w, f.h
    side = tag[4]
    base = SvgRenderer()._label_place(side, x, y, w, h)
    halo = _unit_label_box(tag)
    near = None
    if halo is not None:
        hx0, hy0, hx1, hy1 = halo
        mx, my = (hx0 + hx1 - 2 * x - w) / 2, (hy0 + hy1 - 2 * y - h) / 2
        near = {"top": (mx, hy1 - y), "bottom": (mx, hy0 - y - h),
                "left": (hx1 - x, my), "right": (hx0 - x - w, my)}[side]
    return (side, tag[0] - base[0], tag[1] - base[1], near)


def label_box(u, tag, items) -> "tuple[float, float, float, float] | None":
    """Return the box draw.io writes a unit's tag in, letters stacked under it.

    A tag alone sits on its halo's near edge. With ``NC`` or fail-position
    letters, draw.io stacks them under the tag on its side, moved as far
    as the tag moved from that side's spot.

    Parameters
    ----------
    u : Unit
        Placed unit.
    tag : tuple or None
        Its tag item.
    items : list
        Its label items, tag first.

    Returns
    -------
    tuple[float, float, float, float] or None
        The box, or ``None`` for no tag or a tag inside its symbol.
    """
    if tag is None or u.frame is None:
        return None
    side, dx, dy, near = _tag_at(u, tag)
    if near is None:
        return None
    x0, y0, x1, y1 = unit_box(u, u.frame)
    lw = max(F.text_width(item[5], _TAG_TYPE) for item in items)
    lh = _LINE_BOX * _TAG_TYPE * len(items)
    nx, ny = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}[side]
    gx, gy = _SIDE_LABEL_GAP[side]
    # shortcut: draw.io keeps this gap full size on a page fitted smaller, so
    # a stacked block lands up to a unit off; pass the fit in if that matters.
    ex, ey = near if len(items) == 1 else (dx + gx, dy + gy)
    cx = (x0 + x1 + nx * (x1 - x0 + lw)) / 2 + ex
    cy = (y0 + y1 + ny * (y1 - y0 + lh)) / 2 + ey
    return (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)


def _function_block(cid: str, item, origin: "tuple[float, float]",
                    fit: "_Fit") -> list[str]:
    """Return a balloon's function block as an outlined child cell.

    Parameters
    ----------
    cid : str
        The balloon's cell id.
    item : tuple or None
        The block's label item, or ``None`` for no block.
    origin : tuple[float, float]
        The balloon cell's top-left corner on the page.
    fit : _Fit
        Page fit.

    Returns
    -------
    list[str]
        ``mxCell`` XML lines; empty without a block.
    """
    from pandid.render.svg import _FUNCTION_TYPE, _unit_label_box

    if item is None:
        return []
    box = _unit_label_box(item)
    if box is None:
        return []
    x0, y0, x1, y1 = fit.box(box)
    style = ("rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
             f"strokeColor={_INK};fillColor=#ffffff;fontColor={_LINE_INK};"
             f"strokeWidth={fit.length(LineWeight.DETAIL.width):g};"
             f"fontSize={fit.length(_FUNCTION_TYPE):g};connectable=0;")
    return _rect(f"{cid}-fn", x0 - origin[0], y0 - origin[1], x1 - x0, y1 - y0, style,
                 _html_text(item[5]), parent=cid)


def _quadrant_cell(cid: str, item, fit: "_Fit") -> list[str]:
    """Return a balloon's quadrant letter code as a haloed text cell.

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
    lx, ly, anchor, _baseline, _lpos, text = item
    size = fit.length(_TAG_TYPE)
    x, y = fit.at(lx, ly)
    box_w = F.text_width(text, size) + 2 * _TEXT_INSET
    box_h = _line_box(size) + 2 * _TEXT_INSET
    left, align = ((x + _TEXT_INSET - box_w, "right") if anchor == "end"
                   else (x - _TEXT_INSET, "left"))
    style = ("text;html=1;strokeColor=none;fillColor=none;"
             f"labelBackgroundColor=#ffffff;align={align};"
             f"verticalAlign=middle;fontSize={size:g};fontColor={_LINE_INK};")
    return _rect(cid, left, y - box_h / 2, box_w, box_h, style, _html_text(text))


def _drawn_type(nominal: float, fit: "_Fit", *, lines: int = 1, box=None) -> str:
    """Return the ``fontSize`` key for lettering in the drawing.

    Parameters
    ----------
    nominal : float
        Unscaled size.
    fit : _Fit
        Page fit.
    lines : int, default=1
        Lines of text inside ``box``.
    box : tuple, optional
        Cell box in drawing units; caps the size so ``lines`` fit.

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

    Parameters
    ----------
    value : object
        Value to write; XML-unwritable characters are removed.

    Returns
    -------
    str
        Quoted attribute value.
    """
    return '"' + escape(writable(value), {'"': "&quot;", "'": "&apos;"}) + '"'


def _html_text(value) -> str:
    """Return author text escaped for an HTML draw.io ``value``.

    Parameters
    ----------
    value : object
        Text to write.

    Returns
    -------
    str
        Escaped text.
    """
    return html.escape(writable(value), quote=False)


def _dash(pattern: str) -> list[str]:
    """Return draw.io dash style keys for an SVG dash pattern.

    Parameters
    ----------
    pattern : str
        SVG dash pattern in drawing units; empty or ``"none"`` is solid.

    Returns
    -------
    list[str]
        Style keys, or an empty list for a solid line.
    """
    if not pattern or pattern == "none":
        return []
    lengths = " ".join(pattern.replace(",", " ").split())
    return ["dashed=1", f"dashPattern={lengths}", "fixDash=1"]


class DrawioRenderer:
    """Render a laid-out flowsheet to a draw.io ``mxfile`` document."""

    def __init__(self):  # numpydoc ignore=GL08
        # Findings put on fs.warnings at the end of render().
        self._findings: list = []
        # Whether a side label is laid out by draw.io off the sheet's plates.
        self._loose_label = False

    # --------------------------------------------------- document

    def render(self, fs: "Flowsheet", *, diagram: "str | None" = None,
               page_size: "str | None" = None, border: "str | None" = None,
               connections: "str | None" = None,
               jump_direction: str = "vertical",
               crossing_style: str = "gap",
               show_stream_table: "bool | str" = False) -> str:
        """Render the flowsheet to a draw.io document.

        Add the render's findings to ``fs.warnings``, replacing the fit
        findings there.

        Parameters
        ----------
        fs : Flowsheet
            Laid-out and routed flowsheet.
        diagram : str, optional
            ``"pfd"`` (default), ``"p&id"`` (or ``"pid"``) or ``"bfd"``.
        page_size : str, optional
            ``"A4"`` to ``"A0"``, or ``None`` to fit the drawing.
        border : str, optional
            ``"zone"`` or ``"none"``; ``"zone"`` for a table sheet.
        connections : str, optional
            Default P&ID joint: ``"flanged"`` or ``"none"``.
        jump_direction : str, default="vertical"
            ``"vertical"`` or ``"horizontal"``: the line that hops.
        crossing_style : str, default="gap"
            ``"gap"``, ``"arc"`` or ``"plain"``.
        show_stream_table : bool or str, default=False
            ``True`` docks the table; ``"sheet"`` gives it a sheet.

        Returns
        -------
        str
            ``mxfile`` XML document.

        Raises
        ------
        ValueError
            For a bad argument, too small a page or an unframed unit.
        """
        from pandid.render.svg import _page, _resolve_sheet, wants_table_sheet

        arrows = draws_arrowheads(diagram)
        self._findings = []
        self._loose_label = False
        table_sheet = wants_table_sheet(show_stream_table)
        if table_sheet and border is None:
            border = "zone"
        border, kind = _resolve_sheet(border, diagram)
        sheet = _page(page_size)
        if table_sheet:
            return self._table_sheet(fs, sheet, border, kind)

        joints = sheet_connections(diagram, connections)
        tags = _tag_pass(fs, joints, jump_direction)
        body: list[str] = []
        # Cell order is z-order: border and furniture first.
        furniture, frame, fit = self._furniture(fs, sheet, bool(show_stream_table), border,
                                                kind, tags.plates)
        body.extend(self._border(frame, border))
        body.extend(furniture)
        body.extend(self._packages(fs, fit))
        # Then equipment, runs, taps and balloons.
        balloons: list[str] = []
        for i, u in enumerate(fs.units):
            (balloons if u.kind == "instrument" else body).extend(
                self._vertex(u, i, fit, tags))
        body.extend(self._edges(fs, arrows, fit, tags, jump_direction, joints,
                                crossing_style))
        body.extend(self._taps(fs, fit))
        body.extend(balloons)
        # shortcut: draw.io keeps main's codes on a sheet with a stacked or wrapped
        # side label, whose box draw.io lays out; box those labels if that is common.
        codes = (quadrant_labels(fs, jump_direction) if self._loose_label
                 else drawn_codes(fs, joints, jump_direction, tags.plates))
        for n, code in enumerate(codes):
            body.extend(_quadrant_cell(f"q{n}", code, fit))

        return self._document(fs, sheet, frame, body)

    def _table_sheet(self, fs, sheet, border, diagram) -> str:
        """Return the stream table's own sheet as a draw.io document.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose streams are tabulated.
        sheet : _Sheet or None
            Fixed page, or ``None``.
        border : str
            ``"none"`` or ``"zone"``.
        diagram : str
            Diagram type the table belongs to.

        Returns
        -------
        str
            ``mxfile`` XML document.
        """
        from pandid.render.svg import table_sheet_plan

        plan = table_sheet_plan(fs, sheet, diagram)
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

        Add this backend's findings to ``fs.warnings``, replacing the fit
        findings there.

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
        # The page size is always stated; page view is on only for a
        # fixed page.
        if sheet is not None:
            page_w, page_h = sheet.width, sheet.height
        else:
            _ox, _oy, ow, oh = F.sheet_rect(*frame)
            page_w, page_h = ow + 2 * F.OUTER_MARGIN, oh + 2 * F.OUTER_MARGIN
        paper = (f'page="{0 if sheet is None else 1}" pageScale="1" '
                 f'pageWidth="{fmt(page_w, 2)}" pageHeight="{fmt(page_h, 2)}"')
        # A page id stable across exports.
        page = hashlib.sha256(fs.name.encode("utf-8")).hexdigest()[:16]
        # Replace validate's fit findings with the render's.
        fs.warnings = [w for w in fs.warnings
                       if getattr(w, "code", "") not in _FIT_CODES] + self._findings
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
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
    def _packages(fs, fit: "_Fit") -> list[str]:
        """Return each package's boundary frame as an unfilled cell.

        The tag is the cell's label, above its upper-left corner; the
        reference is a child text cell inside its lower-left corner.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet being drawn.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Cell XML lines.
        """
        size = fit.length(_TAG_TYPE)
        out: list[str] = []
        for n, pkg in enumerate(fs.packages):
            box = package_frame(pkg)
            assert box is not None
            x0, y0, x1, y1 = fit.box(box)
            style = ";".join([
                "rounded=0", "html=1", f"fillColor={_NO_FILL}", f"strokeColor={_LINE_INK}",
                f"strokeWidth={fit.length(LineWeight.DETAIL.width):g}", *_dash(PACKAGE_DASH),
                "labelPosition=center", "verticalLabelPosition=top", "align=left",
                "verticalAlign=bottom", "spacing=0", f"spacingBottom={fit.length(4):g}",
                f"fontSize={size:g}", f"fontColor={_LINE_INK}", "connectable=0"]) + ";"
            out += _rect(f"pk{n}", x0, y0, x1 - x0, y1 - y0, style, _html_text(pkg.name))
            for item in package_labels(pkg, box)[1:]:
                text = item[5]
                w = F.text_width(text, size) + 2 * _TEXT_INSET
                h = _line_box(size) + 2 * _TEXT_INSET
                lx, ly = fit.at(item[0], item[1])
                out += _rect(f"pk{n}-ref", lx - x0 - _TEXT_INSET, ly - y0 - h + _TEXT_INSET, w, h,
                             "text;html=1;strokeColor=none;fillColor=none;align=left;"
                             f"verticalAlign=bottom;fontSize={size:g};fontColor={_LINE_INK};",
                             _html_text(text), parent=f"pk{n}")
        return out

    @staticmethod
    def _id(index: int) -> str:
        """Return the cell id for the unit at ``index``.

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

        Parameters
        ----------
        u : Unit
            Unit.
        sym : Symbol
            Its symbol.

        Returns
        -------
        _Approximation or None
            Stand-in, or ``None`` with a stencil or no stand-in.
        """
        if sym.drawio_shape or sym.drawio_body_shape:
            return None
        return _APPROXIMATIONS.get((u.kind, getattr(u, "variant", "default")))

    def _placement(self, u, sym) -> "tuple[list[str], bool, bool]":
        """Return the style keys placing a symbol, and its net flips.

        Mirror a non-directional symbol as its frame is mirrored, then
        add the flip of a stencil or stand-in drawn the other way.

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
            return [], False, False
        rot = int(getattr(f, "orientation", 0) or 0)
        keys = []
        if rot in _DIRECTION:
            # Connection points stay fractions of the box as placed.
            keys += [f"direction={_DIRECTION[rot]}", "anchorPointDirection=0",
                     "legacyAnchorPoints=1"]
        if sym.directional:
            flip_h, flip_v = False, False
        else:
            flip_h, flip_v = bool(f.mirrored), bool(getattr(f, "mirror_y", False))
        # Add the flip of a stencil or stand-in drawn the other way.
        approx = self._approximation(u, sym)
        if sym.drawio_flip_h or (approx is not None and approx.flip_h):
            flip_h = not flip_h
        if flip_h:
            keys.append("flipH=1")
        if flip_v:
            keys.append("flipV=1")
        return keys, flip_h, flip_v

    def _shape(self, u, sym, fit: "_Fit") -> list[str]:
        """Return the style keys naming the shape drawn for a unit.

        Parameters
        ----------
        u : Unit
            Unit.
        sym : Symbol
            Its symbol.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Style keys.
        """
        weight = (f"strokeWidth="
                  f"{fit.length(_svg._class_weight(sym).width):g}")
        if u.kind in ("feed", "product"):
            # draw.io's offPageConnector, turned north to point east and
            # south to point west.
            (x0, _, x1, _), depth, east = boundary_flag(u, u.frame)
            size = (depth / (x1 - x0)) if x1 - x0 else 0.375
            return ["shape=offPageConnector", f"size={fmt(min(1.0, size), 6)}",
                    f"direction={'north' if east else 'south'}",
                    "anchorPointDirection=0", "legacyAnchorPoints=1",
                    "rounded=0", "whiteSpace=wrap",
                    f"strokeColor={_LINE_INK}", f"fillColor={_NO_FILL}",
                    f"strokeWidth={fit.length(LineWeight.EQUIPMENT.width):g}"]
        stencil = sym.drawio_shape or sym.drawio_body_shape
        body = self._shell(u)
        if body is None and not stencil and (u.kind, u.variant) in OWN_OUTLINE:
            body = default_registry.get(u.kind, u.variant)
        if body is not None:
            # A shell built to size, or a drawing exported as its own
            # outline, is drawn as built; its parts are child cells.
            shift = (-min([0.0, *(o.x * body.width for o in sym.overlays)]),
                     -min([0.0, *(o.y * body.height for o in sym.overlays)]))
            stencil = drawio_stencil(body.svg, sym.width, sym.height, shift,
                                     fit.length(1.0))
        if stencil:
            # outlineConnect=0 keeps a stream on its nozzle.
            keys = [f"shape={stencil}", "outlineConnect=0",
                    f"strokeColor={_INK}", f"fillColor={sym.drawio_fill or _PAPER}",
                    weight]
            return keys
        approx = self._approximation(u, sym)
        shape = approx.shape if approx is not None else None
        keys = [] if shape is None else [f"shape={shape}"]
        keys += ["rounded=0", "whiteSpace=wrap"]
        if approx is None:
            return keys + [f"strokeColor={_INK}", f"fillColor={_NO_FILL}", weight]
        if approx.pieces:
            # The pieces draw the symbol; the cell is invisible.
            return keys + ["strokeColor=none", f"fillColor={_NO_FILL}"]
        return keys + [*approx.keys, f"strokeColor={approx.stroke}",
                       f"fillColor={approx.fill}",
                       f"strokeWidth={fit.length(approx.weight):g}"]

    def _label(self, u, fit: "_Fit", tags: "_Tags",
               wraps: bool) -> "tuple[str, list[str], tuple]":
        """Return a unit's label text, placing keys and tag offset.

        An instrument's tag goes inside its balloon; other tags go on
        the side from ``tags``. ``NC`` and fail-position letters follow
        the tag.

        Parameters
        ----------
        u : Unit
            Unit.
        fit : _Fit
            Drawing fit.
        tags : _Tags
            Tag placements from the tag pass.
        wraps : bool
            Whether draw.io wraps the label to the cell's width.

        Returns
        -------
        tuple[str, list[str], tuple[float, float]]
            HTML label, style keys and the ``(dx, dy)`` offset.
        """
        from pandid.units import split_tag

        if u.kind == "instrument":
            letters, number = split_tag(getattr(u, "type", "") or u.tag,
                                        getattr(u, "number", "") or "")
            display = getattr(u, "display", "field")
            diamond = getattr(u, "symbol_type", u.variant) in _DIAMOND_BALLOONS
            # A diamond carries the number alone.
            parts = [number or letters.upper()] if diamond else [letters.upper(), number]
            parts = [part for part in parts if part]
            text = "<br>".join(_html_text(part) for part in parts)
            offset = (0.0, 0.0)
            if display != "field" and diamond:
                # The number sits under the bars, as on the sheet.
                offset = (0.0, fit.length(8.0 if display == "subsidiary" else 7.0))
            elif display != "field" and len(parts) > 1:
                # Letters above the bars and the number below, as on the
                # sheet.
                text = f'<div style="line-height:{fmt(fit.length(21.0), 2)}px">{text}</div>'
            # One size for both lines, capped to fit the balloon.
            return text, ["verticalLabelPosition=middle", "verticalAlign=middle",
                          "align=center",
                          _drawn_type(_TAG_TYPE, fit, lines=len(parts),
                                      box=unit_box(u, u.frame))], offset

        lines = [u.tag] if u.tag else []
        if u.kind in ("feed", "product"):
            reference = _flag_reference(u)
            if reference:
                lines.append(reference)
            # Centred inside the flag, capped to fit it.
            return "<br>".join(_html_text(line) for line in lines), _LABEL_SIDE["center"] + [
                _drawn_type(_TAG_TYPE, fit, lines=len(lines),
                            box=unit_box(u, u.frame))], (0.0, 0.0)
        if closed_marking(u, default_registry) == "NC":
            lines.append("NC")
        letters = fail_marking(u)
        if letters:
            lines.append(letters)
        side, dx, dy, near = tags.at.get(id(u), (
            (u.frame.label_pos or "top") if u.frame is not None else "top", 0.0, 0.0, None))
        offset = (fit.length(dx), fit.length(dy))
        x0, _y0, x1, _y1 = fit.box(unit_box(u, u.frame))
        one_line = len(lines) == 1 and not (
            wraps and F.text_width(lines[0], fit.length(_TAG_TYPE)) > x1 - x0 - 2 * _TEXT_INSET)
        if near is not None and one_line:
            # A one-line tag sits on its halo; any other label keeps draw.io's spot.
            gx, gy = _SIDE_LABEL_GAP[side]
            offset = (fit.length(near[0]) - gx, fit.length(near[1]) - gy)
        elif lines and side in _SIDE_LABEL_GAP:
            self._loose_label = True
        # No cap: a side label sits outside the cell.
        return "<br>".join(_html_text(line) for line in lines), _LABEL_SIDE.get(
            side, _LABEL_SIDE["top"]
        ) + [_drawn_type(_TAG_TYPE, fit)], offset

    def _vertex(self, u, index: int, fit: "_Fit", tags: "_Tags") -> list[str]:
        """Return one unit as a draw.io vertex and its child cells.

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
        sym = default_registry.for_unit(u)
        approx = self._approximation(u, sym)
        if approx is not None and approx.lost:
            self._findings.append(Issue(
                "warning", APPROXIMATED,
                f"{u.name} has no draw.io stencil and is exported as a stand-in, "
                f"which loses {approx.lost}"))
        self._report_reshape(u, sym, approx)
        x0, y0, x1, y1 = fit.box(unit_box(u, u.frame))
        placement, _, _ = self._placement(u, sym)
        shape = self._shape(u, sym, fit)
        text, label_keys, (dx, dy) = self._label(u, fit, tags, "whiteSpace=wrap" in shape)
        style = ";".join(["html=1", *shape, *label_keys, *placement]) + ";"
        geometry = (f'          <mxGeometry x="{fmt(x0, 2)}" y="{fmt(y0, 2)}" '
                    f'width="{fmt(x1 - x0, 2)}" height="{fmt(y1 - y0, 2)}" as="geometry"')
        body = ([geometry + ">",
                 f'            <mxPoint x="{fmt(dx, 2)}" y="{fmt(dy, 2)}" as="offset" />',
                 '          </mxGeometry>']
                if (round(dx, 2) or round(dy, 2)) else [geometry + " />"])
        cid = self._id(index)
        # A stand-in's second outline, as a child cell.
        inscribed = [] if approx is None or approx.inscribed is None else _rect(
            f"{cid}-in", 0, 0, x1 - x0, y1 - y0,
            ";".join([f"shape={approx.inscribed}", "rounded=0", "html=1",
                      f"strokeColor={approx.stroke}", f"fillColor={_NO_FILL}",
                      f"strokeWidth={fit.length(approx.weight):g}",
                      "connectable=0", "movable=0"]) + ";", parent=cid)
        return [
            f'        <mxCell id="{cid}" value={_attr(text)} '
            f'style={_attr(style)} vertex="1" parent="1">',
            *body,
            '        </mxCell>',
            *inscribed,
            *self._pieces(u, approx, cid, x1 - x0, y1 - y0, fit),
            *self._overlay_cells(cid, sym, x1 - x0, y1 - y0, fit, u.frame, u.name,
                                 self._shell(u)),
            *_function_block(cid, tags.blocks.get(id(u)), (x0, y0), fit),
        ]

    def _report_reshape(self, u, sym, approx: "_Approximation | None") -> None:
        """Report a stand-in stretched to a different aspect.

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
        x0, y0, x1, y1 = unit_box(u, u.frame)
        w, h = x1 - x0, y1 - y0
        # The symbol's box as placed, turn included.
        _px, _py, bw, bh = symbol_to_box(0.0, 0.0, sym.width, sym.height, *_xform(u.frame))
        if not (w > 0 and h > 0 and bw > 0 and bh > 0):
            return
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
        """Return a stand-in's pieces and marks, one child cell per built-in.

        Each piece turns and mirrors with the parent.

        Parameters
        ----------
        u : Unit
            Placed unit.
        approx : _Approximation or None
            Its stand-in.
        cid : str
            Parent cell id.
        w : float
            Parent cell width.
        h : float
            Parent cell height.
        fit : _Fit
            Drawing fit.

        Returns
        -------
        list[str]
            Cell XML lines; empty without pieces or marks.
        """
        if approx is None or not (approx.pieces or approx.marks):
            return []
        rot = _xform(u.frame)[0]
        turn = [f"direction={_DIRECTION[rot]}"] if rot in _DIRECTION else []
        out: list[str] = []
        for i, piece in enumerate((*approx.pieces, *approx.marks)):
            px, py, pw, ph = _placed_rect(u.frame, piece.x, piece.y, piece.w, piece.h)
            keys = [] if piece.shape is None else [f"shape={piece.shape}"]
            style = ";".join([
                "html=1", "rounded=0", *keys, *turn,
                f"strokeColor={approx.stroke}", f"fillColor={approx.fill}",
                f"strokeWidth={fit.length(approx.weight):g}",
                "connectable=0", "movable=0"]) + ";"
            out += _rect(f"{cid}-s{i}", px * w, py * h, pw * w, ph * h, style, parent=cid)
        return out

    @staticmethod
    def _shell(u) -> "Symbol | None":
        """Return the body a vessel or a stirred tank is drawn in place on.

        Parameters
        ----------
        u : Unit
            Unit.

        Returns
        -------
        Symbol or None
            A vessel's shell built to size, or a stirred tank's body
            under its motor; ``None`` for any other unit.
        """
        from pandid.units import _built_to_size, _drawn_parts

        if not (_built_to_size(u) or (u.kind == "tank" and getattr(u, "agitator", None))):
            return None
        return _drawn_parts(u, tuple(getattr(u, "overlays", ()) or ()))[0]

    def _overlay_cells(self, cid: str, sym, w: float, h: float,
                       fit: "_Fit", frame: "Frame", name: str,
                       body: "Symbol | None" = None) -> list[str]:
        """Return one child cell per part on a composed body.

        Parameters
        ----------
        cid : str
            Parent cell id.
        sym : Symbol
            Composed symbol.
        w : float
            Parent cell width.
        h : float
            Parent cell height.
        fit : _Fit
            Drawing fit.
        frame : Frame
            Unit placement.
        name : str
            Unit name, for findings.
        body : Symbol, optional
            The shell the parts are placed on, where it is drawn in
            place within the cell.

        Returns
        -------
        list[str]
            Cell XML lines; empty without overlays.
        """
        if not sym.overlays:
            return []
        # Each part's box as fractions of the cell.
        boxes = [(o.x, o.y, o.w, o.h) for o in sym.overlays] if body is None else [
            (left / sym.width, top / sym.height, (right - left) / sym.width,
             (bottom - top) / sym.height)
            for left, top, right, bottom in overlay_boxes(body, sym.overlays)]
        rot = _xform(frame)[0]
        turn = [f"direction={_DIRECTION[rot]}"] if rot in _DIRECTION else []
        out: list[str] = []
        for i, overlay in enumerate(sym.overlays):
            part = default_registry.part(overlay.group, overlay.name)
            approx = _PART_APPROXIMATIONS.get((overlay.group, overlay.name))
            if part.drawio_shape:
                keys = [f"shape={part.drawio_shape}"]
            else:
                keys = [] if approx is None or approx.shape is None else [
                    f"shape={approx.shape}"]
                keys += [] if approx is None else list(approx.keys)
                if approx is not None and approx.lost:
                    self._findings.append(Issue(
                        "warning", APPROXIMATED,
                        f"{name or cid}: the {overlay.name} part has no draw.io "
                        f"stencil and is exported as a stand-in, which loses "
                        f"{approx.lost}"))
            if overlay.mirror:
                keys.append("flipH=1")
            ox, oy, ow, oh = _placed_rect(frame, *boxes[i])
            style = ";".join([
                "html=1", "rounded=0", *keys, *turn,
                f"strokeColor={_INK}", f"fillColor={_NO_FILL}",
                f"strokeWidth={fit.length(_PART_STROKE):g}",
                "connectable=0", "movable=0"]) + ";"
            out += _rect(f"{cid}-p{i}", ox * w, oy * h, ow * w, oh * h, style, parent=cid)
        return out

    # ---------------------------------------------------- streams

    def _fraction(self, u, sym, point) -> "tuple[float, float]":
        """Return a point on a unit as a draw.io connection fraction.

        The fraction is reflected through the cell's flips.

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
        x0, y0, x1, y1 = unit_box(u, u.frame)
        w, h = x1 - x0, y1 - y0
        fx = (px - x0) / w if w else 0.5
        fy = (py - y0) / h if h else 0.5
        _, flip_h, flip_v = self._placement(u, sym)
        return (1.0 - fx if flip_h else fx, 1.0 - fy if flip_v else fy)

    def _constraint(self, u, sym, port_name: str) -> "tuple[float, float]":
        """Return where a stream meets a port, as a cell fraction.

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
            # Every leg of a tee runs to its centre.
            x0, y0, x1, y1 = unit_box(u, u.frame)
            return self._fraction(u, sym, ((x0 + x1) / 2, (y0 + y1) / 2))
        return self._fraction(u, sym, port_point(u, u.frame, port_name))

    @staticmethod
    def _ends(exit_at, entry_at) -> list[str]:
        """Return the style keys pinning an edge's ends to cell points.

        Parameters
        ----------
        exit_at : tuple[float, float] or None
            Fraction on the source cell; ``None`` for a floating end.
        entry_at : tuple[float, float] or None
            Fraction on the target cell; ``None`` for a floating end.

        Returns
        -------
        list[str]
            Style keys.
        """
        keys = []
        for prefix, at in (("exit", exit_at), ("entry", entry_at)):
            if at is None:
                continue
            keys += [f"{prefix}X={fmt(at[0], 6)}", f"{prefix}Y={fmt(at[1], 6)}",
                     f"{prefix}Dx=0", f"{prefix}Dy=0", f"{prefix}Perimeter=0"]
        return keys

    def _edges(self, fs, arrows: bool, fit: "_Fit", tags: "_Tags",
               direction: str = "vertical",
               joints: "str | None" = None,
               crossing_style: str = "gap") -> list[str]:
        """Return every stream as a draw.io edge between its two ports.

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
            ``jump_direction``: ``"vertical"`` or ``"horizontal"``.
        joints : str, optional
            Sheet joint default.
        crossing_style : str, default="gap"
            ``"gap"``, ``"arc"`` or ``"plain"``.

        Returns
        -------
        list[str]
            Cell XML lines: edges in hop order, then number enclosures.
        """
        index = {id(u): i for i, u in enumerate(fs.units)}
        # The numbers' boxes join the tag plates, which the codes keep off.
        placed = stream_numbers(fs, tags.plates, joints, direction)
        numbers = {number.name: number for number in placed}
        shape = enclosure_shape(fs)
        self._findings += label_findings(fs, shape, placed, direction)
        polylines = {n: stream_polyline(s) for n, s in enumerate(fs.streams)}
        order, hops, lost = _hops(polylines, direction, crossing_style)
        for hop_key, cross_key, x, y in sorted(lost):
            at = f"({fmt(x, 2)}, {fmt(y, 2)})"
            hopper, crossed = (fs.streams[k].name or f"stream {k + 1}"
                               for k in (hop_key, cross_key))
            self._findings.append(Issue(
                "warning", HOP_DROPPED,
                f"{hopper} crosses itself at {at}, and draw.io hops a line "
                f"only over the lines written before it, never over itself; the "
                f"crossing is exported flat" if hop_key == cross_key else
                f"{hopper} hops {crossed} at {at} "
                f"on the sheet, and the two cross each other more than once, which "
                f"draw.io cannot draw either way round; the crossing is exported "
                f"flat"))
        labelled: set = set()
        cells: dict = {}
        boxes: list[str] = []
        for n, s in enumerate(fs.streams):
            src_u, dst_u = s.source.owner, s.dest.owner
            points = polylines[n]
            ex, ey = self._constraint(src_u, default_registry.for_unit(src_u), s.source.name)
            tx, ty = self._constraint(dst_u, default_registry.for_unit(dst_u), s.dest.name)
            signal = s.kind in _SIGNAL_KINDS

            keys = [
                "html=1",
                # edgeStyle=none keeps the routed polyline.
                "edgeStyle=none", "rounded=0", "orthogonalLoop=1", "jettySize=auto",
                *self._ends((ex, ey), (tx, ty)),
                f"strokeColor={s.color or _LINE_INK}",
                f"strokeWidth={fit.length(_stream_rung(signal).width):g}",
            ]
            wireless = s.kind == "wireless"
            if wireless:
                # The wave's crests are a curved edge's control points.
                keys.append("curved=1")
            if n in hops and not wireless:
                # draw.io's jumpSize for a hop of HOP_R on this line, at least 1.
                weight = fit.length(_stream_rung(signal).width)
                size = max(1, round(2.0 * (fit.length(HOP_R) - weight) + 2.0))
                # draw.io's jumpStyle takes the crossing style's name.
                keys += [f"jumpStyle={crossing_style}", f"jumpSize={size}"]
            keys += _dash(s.dasharray or _SIGNAL_DASH.get(s.kind, ""))
            if arrows and wears_arrowhead(s, default_registry):
                keys += ["endArrow=block", "endFill=1",
                         f"endSize={fit.length(ARROWHEAD):g}"]
            else:
                keys.append("endArrow=none")
            keys.append("startArrow=none")

            # Only the first segment of a named run carries its number;
            # signal lines carry none. An enclosed number is its own
            # vertex.
            label = ""
            number = None
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
            waypoints = (_svg.wave_points(points) if wireless else points)[1:-1]
            along, offset = _number_geometry(None if boxed else number, points, fit)
            body = [
                *(['            <Array as="points">',
                   *(f'              <mxPoint x="{fmt(fx, 2)}" y="{fmt(fy, 2)}" />'
                     for fx, fy in (fit.at(px, py) for px, py in waypoints)),
                   '            </Array>'] if waypoints else []),
                *([f'            <mxPoint x="{fmt(offset[0], 2)}" y="{fmt(offset[1], 2)}" '
                   'as="offset" />'] if offset is not None else []),
            ]
            # The geometry's x places the label along the run and its
            # offset across it.
            head = ('          <mxGeometry relative="1" as="geometry"'
                    + ('' if along is None else f' x="{fmt(along, 6)}"'))
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
            cells[n] += _line_marks(f"s{n}", s, points, resolve_connections(s, joints),
                                    s.color or _LINE_INK, fit)
            if number is not None and number.leader is not None:
                cells[n] += _leader(f"s{n}", number, s.color or _LINE_INK, fit)
            if boxed:
                boxes += _enclosure(f"s{n}", number, shape,
                                    s.color or _LINE_INK, fit)
        out: list[str] = []
        for n in order:
            out += cells[n]
        return out + boxes

    def _taps(self, fs, fit: "_Fit") -> list[str]:
        """Return every instrument connection as a draw.io edge.

        The balloon end is pinned to the balloon's centre. The other end
        is pinned to the host unit, or is a free point on a host stream.
        The corners of the tap's route are waypoints.

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
            if target is None:  # not on the sheet
                continue
            entry = self._fraction(inst, default_registry.for_unit(inst), centre)
            host = getattr(inst, "host", None)
            source = index.get(id(host)) if getattr(host, "frame", None) is not None else None
            exit_at = (self._fraction(host, default_registry.for_unit(host), tap)
                       if source is not None else None)
            keys = [
                "html=1", "edgeStyle=none", "rounded=0",
                *self._ends(exit_at, (entry[0], entry[1])),
                f"strokeColor={_LINE_INK}",
                f"strokeWidth={fit.length(LineWeight.DETAIL.width):g}",
            ]
            if not impulse_tap(inst):
                keys += _dash(_TAP_DASH)
            keys += ["endArrow=none", "startArrow=none", _NO_HOP.rstrip(";")]
            style = ";".join(keys) + ";"
            terminals = f' source="{self._id(source)}"' if source is not None else ""
            body = [f'            <mxPoint x="{fmt(fit.at(*tap)[0], 2)}" '
                    f'y="{fmt(fit.at(*tap)[1], 2)}" as="sourcePoint" />'] if source is None else []
            bends = [fit.at(*p) for p in tap_route(inst, tap, centre)[1:-1]]
            if bends:
                body += ['            <Array as="points">',
                         *(f'              <mxPoint x="{fmt(x, 2)}" y="{fmt(y, 2)}" />'
                           for x, y in bends),
                         '            </Array>']
            geometry = ['          <mxGeometry relative="1" as="geometry">', *body,
                        '          </mxGeometry>'] if body else [
                '          <mxGeometry relative="1" as="geometry" />']
            out += [
                f'        <mxCell id="t{n}" value="" style={_attr(style)} '
                f'edge="1" parent="1"{terminals} target="{self._id(target)}">',
                *geometry,
                '        </mxCell>',
            ]
        return out

    # -------------------------------------------------- furniture

    def _furniture(self, fs, sheet: "_Sheet | None" = None, show_stream_table: bool = False,
                   border: str = "none", diagram: "str | None" = None, labels=()):
        """Return the furniture cells, the frame and the drawing fit.

        With a fixed ``sheet`` the drawing is fitted into the space the
        furniture leaves.

        Parameters
        ----------
        fs : Flowsheet
            Flowsheet whose title block and annotations are drawn.
        sheet : _Sheet, optional
            Fixed page.
        show_stream_table : bool, default=False
            Whether to dock the stream table.
        border : str, default="none"
            ``"none"`` or ``"zone"``.
        diagram : str or None, optional
            Diagram type; ``None`` is a PFD.
        labels : sequence of tuple, optional
            Boxes ``(x0, y0, x1, y1)`` of the labels drawn beside units.

        Returns
        -------
        tuple[list[str], tuple, _Fit]
            Cell XML lines, the frame ``(x, y, w, h)`` and the fit.

        Raises
        ------
        ValueError
            If the page is too small for the furniture.
        """
        plan = diagram_plan(fs, sheet, border, show_stream_table, diagram, labels)
        fit = _Fit(1.0, 0.0, 0.0) if plan.fit is None else _Fit(*plan.fit)
        # Fallbacks for the strip's name, date and scale.
        name = fs.name
        date = datetime.now().strftime("%Y-%m-%d")
        scale = "" if plan.fit is None else _scale_text(fit.scale)
        out: list[str] = []
        for n, (obj, x, y, w, h) in enumerate(plan.placed):
            out += self._furniture_cell(f"f{n}", plan.block if obj is TITLE else obj,
                                        x, y, w, h, name, date, scale)
        return out, plan.frame, fit

    @staticmethod
    def _border(frame, border: str) -> list[str]:
        """Return the zone-ruled drawing frame as cells.

        Parameters
        ----------
        frame : tuple[float, float, float, float]
            Inner frame.
        border : str
            ``"none"`` or ``"zone"``.

        Returns
        -------
        list[str]
            Cell XML lines; empty unless ``border`` is ``"zone"``.
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
            # Columns without a stated alignment are centred.
            align = list(obj.col_align or [])
            # The table container draws the border and every rule.
            return _table(cid, title, [str(c) for c in obj.headers],
                          [[str(c) for c in row] for row in obj.rows],
                          x, y, w, h, col_w, (size + F._TABLE_TITLE) if title else 0.0,
                          font=size, keys=f"strokeWidth={F._CELL_RULE:g};",
                          col_keys=[_ALIGN_KEY.get(align[c] if c < len(align) else "c",
                                                   "align=center;")
                                    for c in range(len(col_w))])
        F.check_annotation_fit(obj, lambda *cell: self._findings.append(fit_issue(*cell)))
        rows = list(getattr(obj, "rows", []) or [])
        if any(isinstance(r, (tuple, list)) for r in rows):
            # Columnar rows, at the sheet's column widths. The first
            # cell starts at the border; a later one starts _ANN_LEAD
            # before its text.
            size, _row_h, title_h, col_w = F._ann_layout(obj)
            col_w = col_w or [0.0]  # rows of empty cells: one blank column
            grid = [[str(c) for c in r] if isinstance(r, (tuple, list)) else [str(r)]
                    for r in rows]
            widths = [cw + F._ANN_GAP for cw in col_w]
            widths[0] += F._ANN_PAD - _ANN_LEAD
            widths[-1] += w - sum(widths)  # the rest of the box
            insets = [F._ANN_PAD] + [_ANN_LEAD] * (len(col_w) - 1)
            return _table(cid, title, [], grid, x, y, w, h, widths, title_h,
                          font=size,
                          keys=(_ANNOTATION_KEYS + f"fontSize={size + 1:g};"
                                + f"strokeWidth={F._BOX_RULE:g};"),
                          # A row's first cell is bold.
                          cell_keys=[[_TABLE_BODY + "align=left;"
                                      f"spacingLeft={fmt(insets[c] - _TEXT_INSET, 2)};"
                                      + ("fontStyle=1;" if c == 0 and len(r) > 1 else "")
                                      for c in range(len(col_w))] for r in grid])
        # Free-form lines.
        size, _row_h, title_h, _col_w = F._ann_layout(obj)
        return _text_box(cid, title, [str(r) for r in rows], x, y, w, h, size,
                         title_h)

    def _title_strip(self, cid: str, block, x, y, w, h, name: str, date: str,
                     scale: str) -> list[str]:
        """Return the title strip as cells.

        The revision history is a draw.io table; the other bands are a
        rectangle, rules and text cells.

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
        strip = F.title_strip_layout(
            block, name, date, x + w, y + h, scale,
            report=lambda *cell: self._findings.append(fit_issue(*cell)))
        bx, by, bw, bh = strip.box
        out = _rect(cid, bx, by, bw, bh,
                    "rounded=0;html=1;movable=1;"
                    f"strokeColor={_LINE_INK};fillColor={_NO_FILL};"
                    f"strokeWidth={F._STRIP_RULE:g};")
        for n, (_kind, x1, y1, x2, y2, weight) in enumerate(strip.rules):
            out += _segment(f"{cid}-v{n}", x1, y1, x2, y2, _LINE_INK, weight)
        out += _rev_table(f"{cid}-rev", strip.rev)
        for n, part in enumerate(strip.parts):
            if part[0] == "rule":
                _kind, x1, y1, x2, y2, weight = part
                out += _segment(f"{cid}-p{n}", x1, y1, x2, y2, _LINE_INK, weight)
            else:
                out += _strip_label(f"{cid}-p{n}", part)
        return out


# Opaque plate behind a line number.
_NUMBER_PLATE = "labelBackgroundColor=#ffffff"

_NUMBER_KEYS = ["verticalAlign=middle", "align=center"]


def _number_geometry(number, points, fit: "_Fit"):
    """Return a line number's position on its edge as draw.io states it.

    ``x`` runs -1 to +1 along the polyline; ``(dx, dy)`` is the offset
    from the run.

    Parameters
    ----------
    number : StreamNumber or None
        Placed number.
    points : list[tuple[float, float]]
        Stream polyline.
    fit : _Fit
        Drawing fit.

    Returns
    -------
    tuple
        ``(x, (dx, dy))``, with ``None`` for what does not apply.
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

    # Position along the whole polyline.
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
    else:  # the segment is not on this edge
        return None, (fit.length(number.x - foot[0]), fit.length(number.y - foot[1]))
    reach = before + t * span
    return (max(-1.0, min(1.0, 2.0 * reach / total - 1.0)),
            (fit.length(number.x - foot[0]), fit.length(number.y - foot[1])))


def _leader(edge_id: str, number, ink: str, fit: "_Fit") -> list[str]:
    """Return the leader joining a displaced line number to its run.

    The leader is a free edge with an arrowhead on the run.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    number : StreamNumber
        Placed number with a leader.
    ink : str
        Line colour.
    fit : _Fit
        Drawing fit.

    Returns
    -------
    list[str]
        XML lines for the leader cell.
    """
    (ax, ay), (bx, by) = number.leader
    return _segment(f"{edge_id}-lead", *fit.at(ax, ay), *fit.at(bx, by), ink,
                    fit.length(LineWeight.DETAIL.width), head=fit.length(_LEADER_HEAD))


# draw.io built-in for each stream-label enclosure.
_ENCLOSURE_SHAPE = {"diamond": "rhombus", "circle": "ellipse", "box": "rounded=0"}


def _enclosure(edge_id: str, number, shape: str, ink: str, fit: "_Fit") -> list[str]:
    """Return a stream label's enclosure as an unfilled cell holding it.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    number : StreamNumber
        Placed number.
    shape : str
        ``"diamond"``, ``"circle"`` or ``"box"``.
    ink : str
        Line colour.
    fit : _Fit
        Drawing fit.

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
    return _rect(f"{edge_id}-box", x, y, fit.length(x1 - x0), fit.length(y1 - y0),
                 style, _html_text(number.name))


# Style keys for a label on each side of a cell.
_LABEL_SIDE = {
    "top": ["verticalLabelPosition=top", "verticalAlign=bottom", "align=center"],
    "bottom": ["verticalLabelPosition=bottom", "verticalAlign=top", "align=center"],
    "left": ["labelPosition=left", "align=right",
             "verticalLabelPosition=middle", "verticalAlign=middle"],
    "right": ["labelPosition=right", "align=left",
              "verticalLabelPosition=middle", "verticalAlign=middle"],
    "center": ["verticalLabelPosition=middle", "verticalAlign=middle", "align=center"],
}


# The pneumatic and hydraulic marks

# Hatch stroke angle on a horizontal run, in clockwise degrees, and
# stroke length.
_HATCH_ANGLE = round(math.degrees(math.atan2(-2 * _svg.HATCH_ARM[1], 2 * _svg.HATCH_ARM[0])), 2)
_HATCH_LEN = round(2 * math.hypot(*_svg.HATCH_ARM), 2)


def _line_marks(edge_id: str, s, points, ends, ink: str, fit: "_Fit") -> list[str]:
    """Return the signal marks and the flanged-joint marks on one line.

    A pneumatic mark is two strokes, a hydraulic mark a stroke and its
    foot, and each flange two bars, every one a ``line`` child vertex
    of the edge placed by arc length.

    Parameters
    ----------
    edge_id : str
        Id of the stream's edge.
    s : Stream
        Stream.
    points : list[tuple[float, float]]
        Stream polyline.
    ends : tuple[str, str]
        Resolved ``(source, dest)`` joint settings.
    ink : str
        Line colour.
    fit : _Fit
        Drawing fit.

    Returns
    -------
    list[str]
        XML lines for the mark cells, then the flange cells.
    """
    from pandid.render.svg import MARKED_KINDS, signal_marks

    total = sum(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                for (ax, ay), (bx, by) in zip(points, points[1:]))
    if total <= 0:
        return []
    gap = fit.length(_svg.FLANGE_GAP / 2)
    # Per family: id letter, stroke length, and each mark's arc length,
    # rotation and stroke offsets. A further quarter turn makes a flange
    # bar cross the run.
    spots = signal_marks(points) if s.kind in MARKED_KINDS else []
    strokes = _svg.HATCH_ALONG if s.kind == "pneumatic" else (0.0,)
    along, across = _svg.HATCH_ARM
    # A hydraulic stroke's foot, centred half its length on from the
    # stroke's first end.
    feet = [] if s.kind != "hydraulic" else [
        (m.along, 0.0 if m.horizontal else 90.0,
         [(fit.length(_svg.HYDRAULIC_FOOT / 2 - along), fit.length(across)) if m.horizontal
          else (fit.length(-across), fit.length(_svg.HYDRAULIC_FOOT / 2 - along))])
        for m in spots]
    families = (
        ("h", _HATCH_LEN, [
            (m.along, _HATCH_ANGLE if m.horizontal else _HATCH_ANGLE + 90.0,
             [(fit.length(off), 0.0) if m.horizontal else (0.0, fit.length(off))
              for off in strokes])
            for m in spots]),
        ("t", _svg.HYDRAULIC_FOOT, feet),
        ("f", _svg.FLANGE_TICK, [
            (m.along, m.angle + 90.0,
             [(math.cos(math.radians(m.angle)) * step, math.sin(math.radians(m.angle)) * step)
              for step in (-gap, gap)])
            for m in flange_marks(s, points, ends)]),
    )
    out: list[str] = []
    for letter, size, marks in families:
        length = fit.length(size)
        half = length / 2
        for n, (along, angle, offsets) in enumerate(marks):
            # -1 to +1 from source to target by arc length.
            rel = max(-1.0, min(1.0, 2.0 * along / total - 1.0))
            style = (f"shape=line;rotation={angle:g};strokeColor={ink};"
                     f"strokeWidth={fit.length(LineWeight.DETAIL.width):g};"
                     f"fillColor={_NO_FILL};html=1;resizable=0;movable=1;")
            for k, (dx, dy) in enumerate(offsets):
                out += [
                    f'        <mxCell id="{edge_id}{letter}{n}{k}" value="" '
                    f'style={_attr(style)} vertex="1" connectable="0" parent="{edge_id}">',
                    f'          <mxGeometry x="{fmt(rel, 6)}" y="0" '
                    f'width="{fmt(length, 2)}" height="{fmt(length, 2)}" '
                    'relative="1" as="geometry">',
                    f'            <mxPoint x="{fmt(dx - half, 2)}" y="{fmt(dy - half, 2)}" '
                    'as="offset" />',
                    '          </mxGeometry>',
                    '        </mxCell>',
                ]
    return out


# Furniture, as draw.io tables

# Table styles. The table rules its own row and column lines; rows and
# cells draw no edges.
_TABLE_SHAPE = ("shape=table;childLayout=tableLayout;container=1;collapsible=0;"
                "fixedHeader=1;html=1;whiteSpace=wrap;align=center;"
                "verticalAlign=middle;fontStyle=1;"
                f"strokeColor={_INK};fillColor={_NO_FILL};")
# A row has a connection point at each end.
_TABLE_ROW = ("shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;"
              "swimlaneBody=0;strokeColor=inherit;fillColor=none;"
              "collapsible=0;dropTarget=0;fixedHeader=1;"
              "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
              "top=0;left=0;right=0;bottom=0;")
_TABLE_CELL = ("shape=partialRectangle;html=1;whiteSpace=wrap;connectable=0;"
               "strokeColor=inherit;overflow=hidden;"
               "top=0;left=0;bottom=0;right=0;pointerEvents=1;")
# Heading cells are filled and bold.
_TABLE_HEAD = "fillColor=#eeeeee;fontStyle=1;align=center;"
_TABLE_BODY = "fillColor=none;"


def _distribute(weights, total: float) -> list[float]:
    """Return ``total`` split in proportion to ``weights``.

    Parts are rounded to two decimals and the last takes the remainder.

    Parameters
    ----------
    weights : iterable of float
        Relative widths; negative values count as 0.
    total : float
        Width to split.

    Returns
    -------
    list[float]
        Parts summing to ``round(total, 2)``.
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


# Line box height as a multiple of font size.
_LINE_BOX = 1.2


def _line_box(size: float) -> float:
    """Return the line box height for a font size.

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

# Baseline depth within a line box, as a fraction of font size.
_BASELINE = 0.9

# Inset draw.io applies on every side of a cell before its text.
_TEXT_INSET = 2.0

# Step from the middle of a cell's side to the middle of a side label's near
# edge: the inset, and the 1 under and 5 over its text that draw.io adds.
_SIDE_LABEL_GAP = {"top": (0.0, -_TEXT_INSET - 1), "bottom": (0.0, _TEXT_INSET + 5),
                   "left": (-_TEXT_INSET, 0.0), "right": (_TEXT_INSET, 0.0)}

# Style keys for TableBox column alignment.
_ALIGN_KEY = {"l": f"align=left;spacingLeft={fmt(F._TABLE_PAD - _TEXT_INSET, 2)};",
              "r": f"align=right;spacingRight={fmt(F._TABLE_PAD - _TEXT_INSET, 2)};",
              "c": "align=center;"}


def _table(cid: str, title: str, headers, rows, x, y, w, h, widths,
           start: float = 0.0, *, header_last: bool = False,
           font: float = 11.0, col_keys=(), row_h: "float | None" = None,
           heights=None, keys: str = "", row_widths=None,
           cell_keys=None) -> list[str]:
    """Return a ruled grid as a draw.io table, rows and cells.

    Parameters
    ----------
    cid : str
        Container cell id.
    title : str
        Title in the head band; empty for none.
    headers : list[str]
        Heading row, or empty.
    rows : list[list[str]]
        Body rows.
    x, y, w, h : float
        Table rectangle.
    widths : list[float]
        Column widths.
    start : float, default=0.0
        Title band height; 0 for no band.
    header_last : bool, default=False
        Put the heading row at the foot.
    font : float, default=11.0
        Cell font size.
    col_keys : sequence of str, optional
        Extra style per column.
    row_h : float, optional
        Fixed row height; the table is then as tall as its rows.
    heights : sequence of float, optional
        Relative row heights.
    keys : str, default=""
        Extra container style.
    row_widths : list[list[float]], optional
        Cell widths per row, for a row with merged cells.
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
    w, start = round(float(w), 2), round(float(start), 2)
    if row_h is not None and body:
        h = round(start + row_h * len(body), 2)
    else:
        h = round(float(h), 2)
    widths = _distribute(list(widths)[:ncol] or [1.0] * ncol, w)
    if len(widths) < ncol:
        widths = _distribute([1.0] * ncol, w)
    ragged = [_distribute(rw, w) for rw in row_widths] if row_widths else None
    rows_h = _distribute(list(heights) if heights else [1.0] * len(body),
                         h - start) if body else []

    shape = _TABLE_SHAPE + f"startSize={fmt(start, 2)};fontSize={font:g};" + keys
    cell = _TABLE_CELL + f"fontSize={font:g};"
    out = _rect(cid, x, y, w, h, shape, _html_text(title))
    ry = start
    for r, cells in enumerate(body):
        rh = rows_h[r]
        cw = ragged[r] if ragged else widths
        head = "" if cell_keys is not None else (
            _TABLE_HEAD if r == head_at else _TABLE_BODY)
        out += [
            f'        <mxCell id="{cid}-r{r}" value="" style={_attr(_TABLE_ROW)} '
            f'vertex="1" parent="{cid}">',
            f'          <mxGeometry y="{fmt(ry, 2)}" width="{fmt(w, 2)}" '
            f'height="{fmt(rh, 2)}" as="geometry" />',
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
                f'          <mxGeometry x="{fmt(cx, 2)}" width="{fmt(cw[c], 2)}" '
                f'height="{fmt(rh, 2)}" as="geometry">',
                f'            <mxRectangle width="{fmt(cw[c], 2)}" '
                f'height="{fmt(rh, 2)}" as="alternateBounds" />',
                '          </mxGeometry>',
                '        </mxCell>',
            ]
            cx += cw[c]
        ry += rh
    return out


def _fill(colour: str) -> str:
    """Return ``"white"`` or a three-digit hex colour as ``#rrggbb``.

    Parameters
    ----------
    colour : str
        CSS colour such as ``"white"`` or ``"#eee"``.

    Returns
    -------
    str
        The colour as ``#rrggbb``, or unchanged.
    """
    if colour == "white":
        return "#ffffff"
    if len(colour) == 4 and colour.startswith("#"):
        return "#" + "".join(c * 2 for c in colour[1:])
    return colour


def _stream_table(cid: str, table, x, y) -> list[str]:
    """Return the stream property table as a draw.io table.

    Every cell is ruled. A section heading is a row with one full-width
    cell.

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
                  cell_keys=[[f"fillColor={_fill(c.fill)};"
                              + (f"align=left;spacingLeft={fmt(F._STREAM_PAD - _TEXT_INSET, 2)};"
                                 if c.anchor == "start" else "align=center;")
                              + ("fontStyle=1;" if c.bold else "")
                              for c in row] for row in table.rows])


def _text_box(cid: str, title: str, rows, x, y, w, h, font: float = 11.0,
              title_h: float = 0.0) -> list[str]:
    """Return a box of free-form lines, such as a notes list.

    The box has a ruled title band and the lines in one left-aligned
    cell.

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
        # Centred, bold, one point larger.
        out += _strip_label(f"{cid}-t", ("text", x + w / 2, y + title_h - F._TITLE_RISE,
                                         title, font + 1, "middle", True, "black"))
        out += _segment(f"{cid}-r", x, y + title_h, x + w, y + title_h,
                        _INK, F._BOX_UNDERLINE)
    body = ("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
            f"align=left;verticalAlign=top;spacingLeft={fmt(F._ANN_PAD - _TEXT_INSET, 2)};"
            f"fontSize={font:g};"
            f"fontColor={_LINE_INK};")
    return out + _rect(f"{cid}-b", x, y + title_h, w, h - title_h, body,
                       "<br>".join(_html_text(r) for r in rows))


# Annotation tables draw only the border and title band.
_ANNOTATION_KEYS = "rowLines=0;columnLines=0;"

# How far an annotation cell after the first starts before its text.
_ANN_LEAD = 3.0


def _rect(cid: str, x, y, w, h, style: str, value: str = "",
          parent: str = "1") -> list[str]:
    """Return a vertex cell with a rectangular geometry.

    Parameters
    ----------
    cid : str
        Cell id.
    x, y, w, h : float
        Rectangle, relative to ``parent``.
    style : str
        Cell style.
    value : str, default=""
        Label, already escaped for HTML.
    parent : str, default="1"
        Parent cell id.

    Returns
    -------
    list[str]
        XML lines.
    """
    return [
        f'        <mxCell id="{cid}" value={_attr(value)} style={_attr(style)} '
        f'vertex="1" parent="{parent}">',
        f'          <mxGeometry x="{fmt(x, 2)}" y="{fmt(y, 2)}" width="{fmt(w, 2)}" '
        f'height="{fmt(h, 2)}" as="geometry" />',
        '        </mxCell>',
    ]


def _segment(cid: str, x1, y1, x2, y2, ink: str, weight: float,
             head: "float | None" = None) -> list[str]:
    """Return a free line between two points as an edge.

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
    head : float, optional
        Arrowhead size at the second point; no head when omitted.

    Returns
    -------
    list[str]
        XML lines.
    """
    arrows = ("endArrow=none;startArrow=none;" if head is None
              else f"startArrow=none;endArrow=block;endFill=1;endSize={head:g};")
    style = (f"edgeStyle=none;rounded=0;html=1;{arrows}"
             f"strokeColor={ink};strokeWidth={weight:g};movable=1;{_NO_HOP}")
    return [
        f'        <mxCell id="{cid}" value="" style={_attr(style)} '
        f'edge="1" parent="1">',
        '          <mxGeometry relative="1" as="geometry">',
        f'            <mxPoint x="{fmt(x1, 2)}" y="{fmt(y1, 2)}" as="sourcePoint" />',
        f'            <mxPoint x="{fmt(x2, 2)}" y="{fmt(y2, 2)}" as="targetPoint" />',
        '          </mxGeometry>',
        '        </mxCell>',
    ]


# Half the cell a zone letter is centred in.
_LABEL_HALF = 8.0


def _label(cid: str, cx, cy, text: str, size: float) -> list[str]:
    """Return bold lettering centred on a point.

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
    return _rect(cid, cx - _LABEL_HALF, cy - _LABEL_HALF, 2 * _LABEL_HALF, 2 * _LABEL_HALF,
                 style, _html_text(text))


def _strip_label(cid: str, part) -> list[str]:
    """Return one piece of title-strip lettering as a text cell.

    The text's baseline is at the part's ``y``.

    Parameters
    ----------
    cid : str
        Cell id.
    part : tuple
        ``(kind, x, y, text, size, anchor, bold, ink)``.

    Returns
    -------
    list[str]
        XML lines; empty for empty text.
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
    return _rect(cid, left, top, box_w, box_h, style, _html_text(text))


def _rev_table(cid: str, grid) -> list[str]:
    """Return the revision history as a draw.io table.

    The table has column lines only and a rule above the heading row at
    the foot. The space above the oldest revision becomes blank rows.

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
                 col_keys=[f"align=left;spacingLeft={fmt(F._REV_PAD - _TEXT_INSET, 2)};"]
                 * len(headings))
    return out + _segment(f"{cid}-rule", grid.x, grid.header_y,
                          grid.x + grid.w, grid.header_y, _LINE_INK,
                          F._BOX_UNDERLINE)
