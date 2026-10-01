"""SVG symbol registry for the topology primitives.

Equipment shapes follow the conventions of ISO 10628-2 and instrument
balloons follow ANSI/ISA-5.1. Neither set is certified conformant to
anything, and the stencil library the equipment comes from makes no
standards claim of its own. Sources:

- **Vendored (draw.io / diagrams.net P&ID stencils, Apache-2.0)**:
  valves and their variants, pumps, compressors, blowers, coolers,
  heaters, heat exchangers, cooling towers, vessels, columns, reactors,
  separators, tanks, dryers, filters, furnaces, thickeners, turbines,
  reducers, in-line fittings, ejectors, vents and funnels. Converted
  from mxGraph stencil XML by ``scripts/vendor_symbols.py`` into
  ``_vendored_symbols.py`` and registered last (overriding the
  hand-drawn defaults of the same kind). See the repo ``NOTICE`` for
  attribution.
- **Hand-drawn primitives**: Feed/Product boundary markers, the
  variable-port Mixer and Splitter, the pipe tee, and the block flow
  diagram's box.
- **Built to size (draw.io-derived, Apache-2.0)**: the belt conveyor.
  Adapted from a stencil but drawn here rather than generated, because a
  fixed path cannot stretch; see :func:`conveyor_symbol` and the repo
  ``NOTICE``.
- **Built to fit (original)**: the block flow diagram's box, whose
  nozzles are a per-face count the symbol cannot know until it has the
  unit, and whose box is sized to hold them; see :func:`block_symbol`.

Authoring conventions (hand-drawn symbols)
------------------------------------------
- Local coordinates: (0, 0) top-left, spanning ``width`` × ``height``.
- Ports: named anchors on the boundary face a stream attaches to; names
  MUST match the owning :class:`~pandid.units.Unit`'s port names.
- Variants share a ``kind`` and register under a ``variant`` name.
- A symbol whose shape carries meaning sets ``stretchable=False`` and is
  centred in a box of another shape rather than distorted to fill it. A
  balloon is a circle because ISA-5.1 says a circle.

Composed symbols
----------------
ISO 10628-2 also builds symbols from a body and the parts of subject
groups 26-29, and clause 5 requires this for anything it does not
tabulate. :class:`IsoPart`, :class:`Overlay`, :class:`OverlayPart` and
:func:`compose` implement it; read the comment block above
:class:`IsoPart` for when a drawing may be composed.
"""

import hashlib
import math
import re
import warnings
from dataclasses import dataclass, field, replace
from difflib import get_close_matches
from functools import lru_cache
from typing import Callable

from pandid.portgeom import outward_dir
from pandid.render.weights import LineWeight
from pandid.streams import SIGNAL_KINDS

# Two placements closer together than this are the same point as far as
# a reader (and a stream endpoint) is concerned.
_COINCIDENT = 0.5

#: Side of the arrowhead a PFD draws at the end of a process line, in
#: drawing units. The renderer uses it as the marker size with
#: ``markerUnits="userSpaceOnUse"``
#: (:meth:`pandid.render.svg.SvgRenderer._defs`), so the filled triangle
#: is this long along the run and this wide across it.
ARROWHEAD = 12.0

#: Paper to leave between two arrowheads side by side on one face, in
#: drawing units: twice the main flow line weight, the floor ISO
#: 128-20:1996 4.4 and ISO 10628-1 5.3.2 set between parallel lines
#: (:attr:`pandid.render.weights.LineWeight.MAIN_FLOW`).
#: ``tests/test_validate.py`` keeps the two in step. The physical minimum
#: of ISO 15519-1 6.2 (0.18 mm on the final medium) is not checked.
MIN_HEAD_CLEARANCE = 2 * LineWeight.MAIN_FLOW.width

#: Smallest pitch between two nozzles that both carry an arrowhead: the
#: head plus :data:`MIN_HEAD_CLEARANCE`. A floor reported as
#: ``nozzles-crowded`` by :func:`pandid.validate.validate`;
#: :data:`BLOCK_PITCH` is the larger pitch a symbol chooses.
MIN_NOZZLE_PITCH = ARROWHEAD + MIN_HEAD_CLEARANCE


def wears_arrowhead(stream, registry) -> bool:
    """Return whether a stream carries an arrowhead at its destination.

    Signal lines never do, nor does a stream ending at a bare-run symbol
    such as a tee (:attr:`Symbol.bare_run`), since the run continues past
    it. Whether the sheet draws arrowheads at all (not on a P&ID) is the
    caller's question. Takes the registry so the validator can ask without
    a renderer.

    Parameters
    ----------
    stream : Stream
        Stream to check.
    registry : SymbolRegistry
        Registry resolving the destination unit's symbol.

    Returns
    -------
    bool
        Whether the path gets a ``marker-end``.
    """
    if stream.kind in SIGNAL_KINDS:
        return False
    return not registry.for_unit(stream.dest.owner).bare_run


#: Spread a family symmetrically about ``at``, where a single nozzle is
#: drawn: two members straddle it, three put the middle one on it. The
#: default.
CENTRED = "centre"

#: Start a family at ``at`` and grow it along the face. For a nozzle drawn
#: near the end of its wall (a hopper separator's feed, 12 units down an
#: 80-unit wall) there is no room to straddle it, and this keeps the first
#: member where the single nozzle was when a feed is added.
FROM_START = "start"


def spread(index: int, count: int, along: float, pitch: float,
           extent: float, at: float | None = None,
           align: str = CENTRED,
           band: "tuple[float, float] | None" = None) -> float:
    """Return the position of member ``index`` of ``count`` along a face.

    The one spacing rule for nozzle families (mixer inlets, column feeds,
    block connections). Members sit ``pitch`` apart around ``at``; if
    that would run off the face, the run is squeezed to ``extent`` of it,
    so the drawn count lands where fixed nozzles would.

    ``band`` is an outer limit: the run is squeezed to fit inside it, then
    slid by the least amount to lie inside it, so no member is ever off
    the band. The span is ``min(pitch * (count - 1), extent * along,
    hi - lo)``. Sliding rather than re-centring leaves a family that fits
    exactly where ``at`` and ``align`` put it. A zero-length band (a dome
    crown, cone apex or dished head) puts every member on one point and is
    refused by callers; see :func:`bandless_face`.

    :class:`PortSeries` is the declarative form; :func:`block_symbol` calls
    this directly because a block's family spans several faces.

    Parameters
    ----------
    index : int
        Member index, from 0.
    count : int
        Family size.
    along : float
        Face length.
    pitch : float
        Preferred spacing.
    extent : float
        Largest fraction of the face the run may span.
    at : float, optional
        Position of a lone member; the middle of the band when omitted.
    align : str, default=CENTRED
        :data:`CENTRED` or :data:`FROM_START`.
    band : tuple[float, float], optional
        ``(lo, hi)`` stretch of face a member may use; the whole face when
        omitted.

    Returns
    -------
    float
        Coordinate along the face.
    """
    lo, hi = (0.0, along) if band is None else band
    start = (lo + hi) / 2 if at is None else at
    if count < 2:
        return min(max(start, lo), hi)
    span = min(pitch * (count - 1), extent * along, hi - lo)
    first = start - span / 2 if align == CENTRED else start
    first = min(max(first, lo), hi - span)
    return first + span * index / (count - 1)


def walled_faces(sym: "Symbol", role: str) -> list[str]:
    """Return the faces a role may use that have room for several nozzles.

    Used in refusal messages, so they name faces with a real wall.

    Parameters
    ----------
    sym : Symbol
        Symbol.
    role : str
        Port role, such as ``"inlet"``.

    Returns
    -------
    list[str]
        Faces whose band has length.
    """
    return [face for face, band in ((f, sym.bands.get(f))
                                    for f in sym.port_faces.get(role, {}))
            if band is None or band[0] < band[1]]


def bandless_face(who: str, face: str, at: float, members: "list[str]",
                  offered: "list[str]") -> ValueError:
    """Return the error for several nozzles on a face with no wall.

    A dished roof, cone apex or dished head meets its box at one point, so
    a second nozzle there would be drawn in mid-air. Raised by
    :meth:`pandid.units._MultiPortVessel._check_face_room` and
    :func:`vessel_symbol`, so both give the same message.

    Parameters
    ----------
    who : str
        Unit name.
    face : str
        Face.
    at : float
        The single point along the face.
    members : list[str]
        Ports placed there.
    offered : list[str]
        Faces with a wall, from :func:`walled_faces`.

    Returns
    -------
    ValueError
        The error to raise.
    """
    named = " and ".join(filter(None, [", ".join(members[:-1]), *members[-1:]]))
    verb = "are both" if len(members) == 2 else "are all"
    cure = (
        "Put them on "
        + " or ".join(filter(None, [", ".join(offered[:-1]), *offered[-1:]]))
        + ", or leave a single connection here"
        if offered else
        "No face of this drawing has a wall to spread a family along, so it "
        "carries one connection per face and no more"
    )
    return ValueError(
        f"{who}: {named} {verb} on the {face} face, whose artwork meets the box "
        f"at the single point {at:g} along it -- a dished head, a cone apex or a "
        f"domed roof. One nozzle sits on that point; a second beside it would be "
        f"drawn in mid-air off the ink. {cure}"
    )


def _on_face(face: str, t: float, width: float, height: float) -> tuple[float, float]:
    """Return the symbol-space point ``t`` along a face.

    ``t`` runs top to bottom on W and E and left to right on N and S, the
    direction :func:`spread` and readers number nozzles in.

    Parameters
    ----------
    face : str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    t : float
        Distance along the face.
    width, height : float
        Symbol box.

    Returns
    -------
    tuple[float, float]
        Point in symbol coordinates.
    """
    return {"W": (0.0, t), "E": (width, t),
            "N": (t, 0.0), "S": (t, height)}[face]


@dataclass(frozen=True)
class PortSeries:
    """A family of like ports spread along one face of a symbol.

    A unit such as :class:`~pandid.units.Mixer` decides its port count, so
    the symbol declares a rule and coordinates are resolved once the count
    is known, using :func:`spread`.

    Attributes
    ----------
    prefix : str
        Member names are ``prefix`` plus a 1-based index (``in_1``).
    face : str
        Face the family is on.
    pitch : float, default=20.0
        Preferred spacing.
    extent : float, default=0.7
        Largest fraction of the face the run may span.
    at : float or None, default=None
        Position of a lone member; the face middle when ``None``.
    singular : str or None, default=None
        Name of a lone member, such as a column's ``feed``.
    align : str, default=CENTRED
        :data:`CENTRED` or :data:`FROM_START`.
    """

    prefix: str
    face: str
    pitch: float = 20.0
    extent: float = 0.7
    at: float | None = None
    singular: str | None = None
    align: str = CENTRED

    def matches(self, port_name: str) -> bool:
        """Return whether ``port_name`` is a member of this series."""
        return port_name == self.singular or (
            port_name.startswith(self.prefix)
            and port_name[len(self.prefix):].isdigit())

    def placement(self, index: int, count: int, width: float, height: float,
                  pin: float | None = None,
                  band: "tuple[float, float] | None" = None) -> tuple[float, float]:
        """Return the symbol-space point of member ``index`` of ``count``.

        Parameters
        ----------
        index : int
            Member index, from 0.
        count : int
            Family size.
        width, height : float
            Symbol box.
        pin : float, optional
            Fraction of the face that overrides the spread for this member,
            from :meth:`pandid.units.Unit._series_pin` (a column's
            ``feed_stages``).
        band : tuple[float, float], optional
            :attr:`Symbol.bands` entry for this face; the whole face when
            omitted.

        Returns
        -------
        tuple[float, float]
            Point in symbol coordinates.
        """
        along = height if self.face in ("W", "E") else width
        if pin is not None:
            lo, hi = (0.0, along) if band is None else band
            # Clamp a pin to the band, so a stage off the shell still lands
            # on the ink.
            t = min(max(pin * along, lo), hi)
        else:
            t = spread(index, count, along, self.pitch, self.extent, self.at,
                       self.align, band)
        return _on_face(self.face, t, width, height)

    def reach(self, width: float, height: float,
              band: "tuple[float, float] | None" = None
              ) -> tuple[float, float, float]:
        """Return the stretch of face members can occupy, at any count.

        Read from :func:`spread` at the widest run, so collision checks and
        drawn points agree.

        Parameters
        ----------
        width, height : float
            Symbol box.
        band : tuple[float, float], optional
            :attr:`Symbol.bands` entry for this face.

        Returns
        -------
        tuple[float, float, float]
            ``(face_coordinate, lo, hi)``: the fixed coordinate of the face
            and the range along it.
        """
        along = height if self.face in ("W", "E") else width
        # Two members at full extent give the ends of the range.
        ends = [spread(i, 2, along, self.extent * along, self.extent, self.at,
                       self.align, band)
                for i in (0, 1)]
        fixed = {"W": 0.0, "E": width, "N": 0.0, "S": height}[self.face]
        return fixed, min(ends), max(ends)


# ----------------------------------------------------------------
# Supplementary symbols: the parts a body is composed with.
#
# ISO 10628-2:2012 Table 1 numbers 29 subject groups. Groups 1-25 name
# whole apparatus; groups **26-29 name the parts you overlay onto one**:
#
#   26 apparatus elements   support leg, bracket, skirt, ring, manhole,
#                           connection nozzle
#   27 internals            tray, baffle tray, bubble-cap tray, valve
#                           tray, sieve element, filter insert,
#                           fluidised bed, packing
#   28 agitators, stirrers  the general stirrer and nine impeller forms
#   29 internal             the characteristic that says what separates,
#      characteristics      crushes or settles inside the body
#
# ISO 10628-2 clause 5 makes composing from them a **shall** when the
# symbol wanted is not tabulated, and ISO 14617-1:2025 §4.7 with Annex B
# restates it with a worked six-part example. The standard demonstrates
# it on itself: item 8.6 (electrostatic precipitator, X8125) is the
# group-8 body carrying item 29.2 (C2030), item 8.8 (electromagnetic
# separator, X8126) is the same body carrying item 29.3 (C2031), and
# item 8.7 (wet electrostatic precipitator, X8033) is that body carrying
# **two** parts at once.
#
# The rule before adding a composition
# ------------------------------------
# **Compose only where ISO itself composes; where ISO registers a distinct
# symbol, it stays a distinct symbol.**
#
# Test: is every mark distinguishing the drawing from the shared body a
# tabulated group 26-29 item, nameable by registration number? Item 8.3
# (gravity separator, X8031) passes: its arrow is item 29.1, C2028. Item
# 8.10 (cyclone, X2618) fails: no group-29 item draws its vortex, so X2618
# stays its own symbol.
#
# One exception: item 1.27 (X8006) draws the electric motor (item 20.6,
# group 20 drives) above a stirred vessel and registers the result. Such
# items are listed one by one in :data:`COMPOSED_APPARATUS`.
#
# :class:`IsoPart` makes the test checkable: each part names its group,
# item and registration number, the identity of a symbol (ISO 14617-1 3.6,
# 4.2), so ``tests/test_composition.py`` can check it against Table 2.
# ----------------------------------------------------------------

#: ISO 10628-2 Table 1 subject groups that are parts rather than
#: apparatus, with their group names. Only these may be overlaid; a whole
#: apparatus inside another is two pieces of equipment.
PART_GROUPS = {
    26: "apparatus elements",
    27: "internals",
    28: "agitators, stirrers",
    29: "internal characteristics and built-in components",
}

#: Apparatus items ISO itself draws inside another apparatus, each with
#: the tabulated row that licenses it. Item 20.6 C0082 (electric motor)
#: is drawn by item 1.27 X8006 above a stirred vessel. Listed by item, not
#: group: other group-20 drives (turbine, gearbox, generator) are tagged
#: machines drawn beside what they drive. A new entry needs its own
#: tabulated row.
COMPOSED_APPARATUS = {
    "20.6": "1.27 X8006, the motor above a stirred vessel",
}

# The registration-number forms of ISO 10628-2 clause 5, column 2:
#
# ``nnn`` / ``nnnn``   an ISO 14617 graphical symbol (normative)
# ``Cnnnn``            a preliminary number, for ISO 14617's next review
# ``X2nnn``            an ISO 14617 symbol example (a guideline)
# ``X8nnn``            an ISO 10628-2 symbol example
#
# ISO 14617-1 3.5 Note 2: an example is a guideline, a bare number a
# normative basic symbol.
_REG_NO = re.compile(r"\A(?:\d{3,4}|C\d{3,4}|X[28]\d{3})\Z")


@dataclass(frozen=True)
class IsoPart:
    """Identity of one ISO 10628-2 group 26-29 supplementary symbol.

    Required on every :class:`OverlayPart`, so each part can be checked
    against Table 2: a part that cannot name its item has no licence to be
    composed.

    Attributes
    ----------
    group : int
        Table 1 subject group, one of :data:`PART_GROUPS`, or a group whose
        item is in :data:`COMPOSED_APPARATUS`.
    item : str
        Item number including the group, as Table 2 writes it (``"27.3"``).
    reg : str
        Registration number in a clause 5 namespace (see ``_REG_NO``).
    name : str
        The standard's descriptor for the item.

    Raises
    ------
    ValueError
        If the group, item, registration number or name is invalid.
    """

    group: int
    item: str
    reg: str
    name: str

    def __post_init__(self) -> None:
        """Validate the part's identity against ISO 10628-2's rules."""
        if self.group not in PART_GROUPS and self.item not in COMPOSED_APPARATUS:
            raise ValueError(
                f"{self.reg}: ISO 10628-2 group {self.group} is not one of the part "
                f"groups {sorted(PART_GROUPS)}, and item {self.item} is not one of the "
                f"apparatus ISO composes anyway ({', '.join(sorted(COMPOSED_APPARATUS))}). "
                f"Groups 1-25 are whole apparatus, and an apparatus overlaid on another "
                f"apparatus is two units on one tag"
            )
        if not self.item.startswith(f"{self.group}."):
            raise ValueError(
                f"{self.reg}: item {self.item!r} is not in group {self.group}; Table 2 "
                f"numbers an item within its group, so a group-{self.group} item reads "
                f"{self.group}.n"
            )
        if not _REG_NO.match(self.reg):
            raise ValueError(
                f"{self.item}: {self.reg!r} is not a registration number in any "
                f"namespace ISO 10628-2 clause 5 declares (nnn, nnnn, Cnnnn, X2nnn, "
                f"X8nnn). A mark with no registered number is not a supplementary "
                f"symbol, and composing from one would invent a symbol where ISO 14617 "
                f"already has an answer"
            )
        if not self.name.strip():
            raise ValueError(
                f"{self.reg}: a part needs the standard's own descriptor, so a reader "
                f"can find the Table 2 row it claims to be"
            )


@dataclass(frozen=True)
class Overlay:
    """One supplementary part and where it sits on a body's box.

    Refers to the part by registry name, so artwork and registration
    number are looked up in one place and the overlay is a small hashable
    cache key. Placement is in fractions of the body's box, so a part stays
    in proportion when the unit is resized. Fractions outside 0 to 1 put
    the part outside the body, as ISO item 1.27 (X8006) puts the motor
    above the head; :func:`compose` grows the box to hold it. A repeated
    part, such as a tray deck, is one overlay per copy.

    Attributes
    ----------
    group : int
        ISO subject group: 26 to 29, or 20 for the drive in
        :data:`COMPOSED_APPARATUS`.
    name : str
        Registry name in pandid's spelling (``"turbine"``).
    x, y : float
        Left and top edge, as fractions of the body's width and height.
    w, h : float
        Width and height, as fractions of the body's width and height.
    mirror : bool, default=False
        Reflect the part left to right. Item 26.2's bracket and item
        26.4's ring are drawn against one wall, and a vessel needs a pair;
        a second registered part would give one symbol two registration
        numbers. Vertical flips are not offered: an inverted support is not
        a support.

    Raises
    ------
    ValueError
        If ``w`` or ``h`` is not positive.
    """

    group: int
    name: str
    x: float
    y: float
    w: float
    h: float
    mirror: bool = False

    def __post_init__(self) -> None:
        """Refuse a part with no extent."""
        if self.w <= 0 or self.h <= 0:
            raise ValueError(
                f"overlay {self.group}/{self.name} is placed {self.w:g} x {self.h:g} of "
                f"the body's box; a part with no extent draws nothing, and a negative "
                f"one draws the part inside out"
            )


@dataclass
class Symbol:
    """SVG template for a unit, with named port anchors.

    Attributes
    ----------
    svg : str
        Artwork, in local coordinates from (0, 0) at the top left.
    width, height : float
        Artwork box.
    ports : dict[str, tuple[float, float]]
        Home anchor of each fixed port.
    port_faces : dict[str, dict[str, tuple[float, float]]]
        Every placement a port may take, by face, such as
        ``{"feed": {"W": (0.0, 15.0), "N": (30.0, 0.0)}}``. The home anchor
        is folded in, so this is the whole menu.
    faceless_ports : frozenset[str]
        Ports with no face of their own (a balloon's signals), which alone
        may share placements with each other.
    port_series : tuple[PortSeries, ...]
        Families whose size the unit decides; each is the only authority
        for its members.
    bands : dict[str, tuple[float, float]]
        Stretch of each face a family may use, measured along it, where the
        artwork does not span the whole box: ``tank/default`` uses
        ``{"W": (36.0, 85.0), "E": (36.0, 85.0), "S": (10.0, 90.0)}`` to
        keep fills off the roof and floor. Read only for families, for
        inlets and outlets alike.
    label_pos : str or None
        Fixed tag side, such as a balloon's ``"center"``.
    id_suffix : str
        Distinguishes definitions of one (kind, variant) that differ, such
        as conveyors built to different lengths.
    stretchable : bool
        Whether the artwork may be scaled unevenly to fill a box. False
        where shape carries meaning (an ISA-5.1 balloon is a circle);
        vendored symbols take it from the stencil's ``aspect``.
    bare_run : bool
        The artwork is only pipe, as a tee; a stream ending here gets no
        arrowhead (:func:`wears_arrowhead`).
    gravity_fixed : bool
        The depicted function depends on gravity, so turning it is reported
        as ``gravity-turned`` (ISO 15519-1 11.4.2, Figure 22 b); the open
        tank 2061 and cyclone X 2618). Vendored symbols take it from
        ``GRAVITY_FIXED`` in ``scripts/vendor_symbols.py``.
    directional : bool
        The artwork states a direction a flip would reverse (heater versus
        cooler arrow). The renderer holds it still under reflections
        (:func:`pandid.render.svg._reflections`); ISO 15519-1 11.4.2 allows
        mirroring. Such artwork must keep ports on ink under any flip and
        carry no lettering. Vendored symbols take it from ``DIRECTIONAL``.
    drawio_shape : str
        draw.io stencil key this artwork was converted from
        (``"mxgraph.pid.valves.gate_valve"``), derived by
        ``drawio_shape_key`` at vendoring time; empty for hand-drawn
        symbols.
    drawio_flip_h : bool
        The draw.io stencil must be flipped (:func:`expander`).
    drawio_fill : str
        Fill for the draw.io stencil (:func:`darkened`).
    drawio_body_shape : str
        Stencil for a composition's body; the parts are exported as child
        cells. Set by :func:`compose`.
    overlays : tuple[Overlay, ...]
        Parts painted over the body, set only by :func:`compose`.
    iso_reg : str
        ISO registration number this drawing claims ("2062", "X2618"), or
        empty where unchecked; the symbol's identity per ISO 14617-1 3.6
        and 4.2. Left empty rather than assumed.
    trim : bool
        The outline is ISO 10628-1 5.3.1 c) (valves, fittings, piping
        accessories, PCE symbols) at half the b) equipment weight. Set per
        drawing, not inferred from ``kind``; read through
        :func:`pandid.render.svg._class_weight`.

    Raises
    ------
    ValueError
        If ports, menus, series or bands are inconsistent.
    """
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    port_faces: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    faceless_ports: frozenset[str] = frozenset()
    port_series: tuple[PortSeries, ...] = ()
    bands: dict[str, tuple[float, float]] = field(default_factory=dict)
    label_pos: str | None = None
    id_suffix: str = ""
    stretchable: bool = True
    bare_run: bool = False
    gravity_fixed: bool = False
    directional: bool = False
    drawio_shape: str = ""
    drawio_flip_h: bool = False
    drawio_fill: str = ""
    drawio_body_shape: str = ""
    overlays: tuple[Overlay, ...] = ()
    iso_reg: str = ""

    trim: bool = False

    def __post_init__(self) -> None:
        """Validate the port declarations and build the full face menus."""
        declared = {name: dict(faces) for name, faces in self.port_faces.items()}
        # Reject rather than repair: a misfiled placement would vanish
        # silently once menus are keyed by coordinate.
        stray = sorted(set(declared) - set(self.ports))
        if stray:
            raise ValueError(
                f"{self.symbol_id()}: port_faces declares a menu for {stray}, which "
                f"ports does not anchor; nothing reads a menu for a port that has "
                f"no nozzle"
            )
        stray = sorted(frozenset(self.faceless_ports) - set(self.ports))
        if stray:
            raise ValueError(
                f"{self.symbol_id()}: faceless_ports names {stray}, which ports does "
                f"not anchor"
            )
        for series in self.port_series:
            clash = sorted(n for n in self.ports if series.matches(n))
            if clash:
                raise ValueError(
                    f"{self.symbol_id()}: ports anchors {clash}, which the "
                    f"{series.prefix!r} series also places; a series is the only "
                    f"authority on where its members go"
                )
            if series.face not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.symbol_id()}: the {series.prefix!r} series names face "
                    f"{series.face!r}; expected one of N, S, E, W"
                )
        for face, span in self.bands.items():
            if face not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.symbol_id()}: bands names face {face!r}; expected one "
                    f"of N, S, E, W"
                )
            lo, hi = span
            along = self.height if face in ("W", "E") else self.width
            if not 0.0 <= lo <= hi <= along:
                raise ValueError(
                    f"{self.symbol_id()}: bands[{face!r}] is {span}, which is not a "
                    f"stretch of a {along:g}-long face measured from its start; a "
                    f"family confined to it would be drawn off the box"
                )
        menu: dict[str, dict[str, tuple[float, float]]] = {}
        for name, xy in self.ports.items():
            home = outward_dir(xy[0], xy[1], self.width, self.height)
            faces = {home: xy}
            for face, coord in declared.get(name, {}).items():
                lands = outward_dir(coord[0], coord[1], self.width, self.height)
                if lands != face:
                    raise ValueError(
                        f"{self.symbol_id()}: port_faces[{name!r}][{face!r}] at "
                        f"{coord} is nearest the {lands} edge of the "
                        f"{self.width}x{self.height} box, so that is the face it "
                        f"would come out of"
                    )
                if face == home and coord != xy:
                    # ``ports`` decides the home nozzle.
                    raise ValueError(
                        f"{self.symbol_id()}: port_faces[{name!r}][{face!r}] is "
                        f"{coord} but ports[{name!r}] puts the same face at {xy}"
                    )
                faces[face] = coord
            menu[name] = faces
        self.port_faces = menu
        for a, b, xy in self.coincident_ports():
            warnings.warn(
                f"{self.symbol_id()}: ports {a!r} and {b!r} both have a placement "
                f"at {xy}, so a stream routed to one lands on top of a stream "
                f"routed to the other. Only ports named in faceless_ports may "
                f"share a placement.",
                stacklevel=2,
            )

    def series_for(self, port_name: str) -> PortSeries | None:
        """Return the series placing ``port_name``, or ``None`` for a fixed port."""
        for series in self.port_series:
            if series.matches(port_name):
                return series
        return None

    def symbol_id(self) -> str:
        """Return the SVG id, for messages."""
        match = re.search(r'\bid="([^"]+)"', self.svg)
        return match.group(1) if match else "<symbol>"

    def coincident_ports(self) -> list[tuple[str, str, tuple[float, float]]]:
        """Return pairs of different ports that share a placement.

        A stream to one would land on a stream to the other. Placements of
        one port may coincide, since only one is live. Faceless ports are
        exempt only from each other. A :class:`PortSeries` is checked as
        the stretch of face it may use, reported as ``prefix*``.

        Returns
        -------
        list[tuple[str, str, tuple[float, float]]]
            ``(port, port, point)`` for each clash.
        """
        placements = [(name, xy) for name, faces in self.port_faces.items()
                      for xy in faces.values()]
        hits: list[tuple[str, str, tuple[float, float]]] = []
        seen: set[tuple[str, str]] = set()
        for i, (n1, p1) in enumerate(placements):
            for n2, p2 in placements[i + 1:]:
                if n1 == n2 or (n1 in self.faceless_ports and n2 in self.faceless_ports):
                    continue
                pair = (n1, n2) if n1 < n2 else (n2, n1)
                if pair in seen or math.hypot(p1[0] - p2[0], p1[1] - p2[1]) >= _COINCIDENT:
                    continue
                seen.add(pair)
                hits.append((pair[0], pair[1], p1))
        for series in self.port_series:
            fixed, lo, hi = series.reach(self.width, self.height,
                                         self.bands.get(series.face))
            member = f"{series.prefix}*"
            for name, xy in placements:
                across, along = (xy[0], xy[1]) if series.face in ("W", "E") else (xy[1], xy[0])
                pair = (name, member) if name < member else (member, name)
                if pair in seen or abs(across - fixed) >= _COINCIDENT:
                    continue
                if lo - _COINCIDENT < along < hi + _COINCIDENT:
                    seen.add(pair)
                    hits.append((pair[0], pair[1], xy))
        return hits


# ----------------------------------------------------------------
# Belt conveyor.
#
# Derived from the draw.io / diagrams.net P&ID stencils (Apache-2.0):
# the shape ``Drier (Roller Conveyor Belt)`` in
# scripts/vendor_data/drawio/driers.xml (w=100, h=140,
# aspect="variable"). Changed: the drier housing is dropped, and the run
# and roller size are parameters, defaulting to the stencil's 60-apart
# r=10 rollers. See NOTICE, and ADAPTED_ELSEWHERE in
# scripts/vendor_symbols.py. Built here rather than generated, because a
# fixed drawing stretched to another aspect would draw elliptical rollers.
# ----------------------------------------------------------------

#: Default roller radius, from the stencil's 20x20 roller ellipses.
CONVEYOR_ROLLER = 10.0
#: Default roller diameter, and the drawn depth: the belt is tangent to
#: both rollers.
CONVEYOR_DIAMETER = 2 * CONVEYOR_ROLLER
#: Default belt run: the stencil's rollers at x=20 and x=80 span x=10..90.
CONVEYOR_LENGTH = 80.0


def conveyor_min_length(diameter: float = CONVEYOR_DIAMETER) -> float:
    """Return the shortest belt run: two roller diameters.

    Parameters
    ----------
    diameter : float, default=CONVEYOR_DIAMETER
        Roller diameter.

    Returns
    -------
    float
        Minimum run; shorter runs overlap the rollers.
    """
    return 2 * diameter


#: Shortest belt run at the default roller.
CONVEYOR_MIN_LENGTH = conveyor_min_length()


def conveyor_too_short(length: float, owner: str = "",
                       diameter: float = CONVEYOR_DIAMETER) -> ValueError:
    """Return the error for a belt run too short for its rollers.

    Shared by :class:`~pandid.units.Conveyor` and :func:`conveyor_symbol`
    so both give the same message.

    Parameters
    ----------
    length : float
        Requested run.
    owner : str, default=""
        Unit name, for the message.
    diameter : float, default=CONVEYOR_DIAMETER
        Roller diameter.

    Returns
    -------
    ValueError
        The error to raise.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}length={length:g} is shorter than a "
        f"conveyor can be drawn: the rollers are {diameter / 2:g} in radius "
        f"and would overlap. Use length={conveyor_min_length(diameter):g} or "
        f"more, two roller diameters."
    )


def conveyor_bad_diameter(diameter: float, owner: str = "") -> ValueError:
    """Return the error for a non-positive roller diameter.

    Parameters
    ----------
    diameter : float
        Requested diameter.
    owner : str, default=""
        Unit name, for the message.

    Returns
    -------
    ValueError
        The error to raise.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}diameter={diameter:g} is not a "
        f"conveyor: the rollers are circles and a circle has a positive "
        f"diameter. Leave diameter= unset for {CONVEYOR_DIAMETER:g}, the "
        f"stencil's own roller."
    )


@lru_cache(maxsize=None)
def conveyor_symbol(length: float = CONVEYOR_LENGTH,
                    diameter: float = CONVEYOR_DIAMETER) -> Symbol:
    """Return a belt conveyor symbol built to its run and roller size.

    The artwork is drawn at the requested size, so its width is the run and
    its height the roller diameter, and the ``<use>`` scales by exactly 1:
    rollers stay circles. ``feed`` is the tail roller, also offered on the
    top for material dropped on; ``discharge`` is the head roller, also
    offered underneath for a chute. Cached, as port resolution asks for it
    on every call.

    Parameters
    ----------
    length : float, default=CONVEYOR_LENGTH
        Run from tail to head.
    diameter : float, default=CONVEYOR_DIAMETER
        Roller diameter, and the drawn depth.

    Returns
    -------
    Symbol
        Conveyor symbol.

    Raises
    ------
    ValueError
        If ``diameter`` is not positive or ``length`` is under two roller
        diameters.
    """
    if diameter <= 0:
        raise conveyor_bad_diameter(diameter)
    if length < conveyor_min_length(diameter):
        raise conveyor_too_short(length, diameter=diameter)
    r, height = diameter / 2, float(diameter)
    tail, head = r, length - r
    # Omit the default roller from the id, so ids without one are stable.
    suffix = f"_L{length:g}" + (f"_D{diameter:g}"
                                if diameter != CONVEYOR_DIAMETER else "")
    roller = ('<ellipse cx="{:g}" cy="{:g}" rx="{:g}" ry="{:g}" fill="none" '
              'stroke="#111" stroke-width="2"/>')
    svg = (
        f'<g id="sym_conveyor{suffix}">'
        + roller.format(tail, r, r, r)
        + roller.format(head, r, r, r)
        + f'<path d="M {tail:g} 0 L {head:g} 0 M {tail:g} {height:g} '
          f'L {head:g} {height:g}" fill="none" stroke="#111" stroke-width="2"/>'
        + '</g>'
    )
    return Symbol(
        svg=svg, width=float(length), height=height,
        ports={"feed": (0.0, r), "discharge": (float(length), r)},
        port_faces={"feed": {"N": (tail, 0.0)},
                    "discharge": {"S": (head, height)}},
        id_suffix=suffix,
        # Built to size so the rollers stay circles.
        stretchable=False,
    )


# ----------------------------------------------------------------
# The screw conveyor, ISO 10628-2 Table 2 item 18.5 X8063.
#
# Original artwork following the construction row 18.5 specifies (see
# pandid.render.iso_parts): a 15 M x 6 M casing, the screw axis along it,
# and zigzag turns 4 M wide reaching 2 M either side. Built to its length,
# not scaled, so the pitch is kept: a longer casing gets more turns.
# ----------------------------------------------------------------

#: Row 18.5's grid module in drawing units, half of
#: :data:`pandid.render.iso_parts.M`, so the 6 M casing is 30 units deep,
#: comparable with the belt conveyor's 20.
SCREW_MODULE = 5.0

#: Default casing depth (bore in elevation): 6 M, from row 18.5.
SCREW_HEIGHT = 6 * SCREW_MODULE

#: One turn of the screw: 4 M along the axis, reaching 2 M either side,
#: drawn as three straight runs as Table 2 flattens a helix (compare item
#: 28.6's helical ribbon).
SCREW_TURN, SCREW_REACH = 4 * SCREW_MODULE, 2 * SCREW_MODULE

#: Fraction of the bore the flight sweeps (row 18.5: 4 M across 6 M). The
#: one dimension that follows the bore, since a screw fills its trough;
#: nothing along the axis changes with the bore.
SCREW_SWEEP = 2 * SCREW_REACH / SCREW_HEIGHT

#: Pitch between turn starts (7 M) and clear casing at each end (2 M),
#: from row 18.5's turns at x 7..11 and 14..18 in a casing at x 5..20.
SCREW_PITCH, SCREW_MARGIN = 7 * SCREW_MODULE, 2 * SCREW_MODULE

#: Shortest drawable screw: clear casing, one turn, clear casing. It
#: happens to equal :data:`CONVEYOR_MIN_LENGTH`.
SCREW_MIN_LENGTH = 2 * SCREW_MARGIN + SCREW_TURN


def screw_too_short(length: float, owner: str = "") -> ValueError:
    """Return the error for a screw casing too short for one turn.

    Separate from :func:`conveyor_too_short`, whose message is about
    rollers. Takes no diameter: the minimum is measured along the axis.

    Parameters
    ----------
    length : float
        Requested run.
    owner : str, default=""
        Unit name, for the message.

    Returns
    -------
    ValueError
        The error to raise.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}length={length:g} is shorter than a "
        f"screw conveyor can be drawn: one turn of the flight is "
        f"{SCREW_TURN:g} with {SCREW_MARGIN:g} of casing at each end. Use "
        f"length={SCREW_MIN_LENGTH:g} or more."
    )


def screw_bad_diameter(diameter: float, owner: str = "") -> ValueError:
    """Return the error for a non-positive screw bore.

    Parameters
    ----------
    diameter : float
        Requested bore.
    owner : str, default=""
        Unit name, for the message.

    Returns
    -------
    ValueError
        The error to raise.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}diameter={diameter:g} is not a screw "
        f"conveyor: the casing is a tube and a tube has a positive bore. "
        f"Leave diameter= unset for {SCREW_HEIGHT:g}, row 18.5's own 6 M "
        f"casing."
    )


@lru_cache(maxsize=None)
def screw_conveyor_symbol(length: float = CONVEYOR_LENGTH,
                          diameter: float = SCREW_HEIGHT) -> Symbol:
    """Return a closed screw conveyor symbol, ISO item 18.5 X8063.

    The casing, the screw axis and as many turns as fit at
    :data:`SCREW_PITCH`. Dimensions along the axis (turn width, pitch,
    end clearance) are fixed, so a longer casing gets more turns; across
    it, the flight follows the bore (:data:`SCREW_SWEEP`). ``feed`` is on
    top a module from the tail and ``discharge`` underneath a module from
    the head, as row 18.5 draws its spouts; the ends are also offered.
    Cached, as :func:`conveyor_symbol` is.

    Parameters
    ----------
    length : float, default=CONVEYOR_LENGTH
        Casing length.
    diameter : float, default=SCREW_HEIGHT
        Casing bore, and the drawn depth.

    Returns
    -------
    Symbol
        Screw conveyor symbol.

    Raises
    ------
    ValueError
        If ``diameter`` is not positive or ``length`` is below
        :data:`SCREW_MIN_LENGTH`.
    """
    if diameter <= 0:
        raise screw_bad_diameter(diameter)
    if length < SCREW_MIN_LENGTH:
        raise screw_too_short(length)
    height = float(diameter)
    axis, reach = height / 2, height * SCREW_SWEEP / 2
    # As many turns as leave SCREW_MARGIN of clear casing at the head.
    starts, x = [], SCREW_MARGIN
    while x + SCREW_TURN <= length - SCREW_MARGIN:
        starts.append(x)
        x += SCREW_PITCH
    turns = "".join(
        f'M {x0:g} {axis:g} L {x0 + SCREW_MODULE:g} {axis - reach:g} '
        f'L {x0 + 3 * SCREW_MODULE:g} {axis + reach:g} '
        f'L {x0 + SCREW_TURN:g} {axis:g} '
        for x0 in starts)
    # The default bore is left out of the id, for the belt's reason.
    suffix = f"_L{length:g}" + (f"_D{diameter:g}"
                                if diameter != SCREW_HEIGHT else "")
    svg = (
        f'<g id="sym_conveyor_screw{suffix}">'
        f'<rect x="0" y="0" width="{length:g}" height="{height:g}" '
        f'fill="white" stroke="#111" stroke-width="2"/>'
        f'<path d="M 0 {axis:g} L {length:g} {axis:g} {turns}" '
        f'fill="none" stroke="#111" stroke-width="2"/>'
        f'</g>'
    )
    return Symbol(
        svg=svg, width=float(length), height=height,
        ports={"feed": (SCREW_MODULE, 0.0),
               "discharge": (length - SCREW_MODULE, height)},
        port_faces={"feed": {"W": (0.0, axis)},
                    "discharge": {"E": (float(length), axis)}},
        id_suffix=suffix,
        # Built to size; stretching would distort the turns.
        stretchable=False,
        iso_reg="X8063",
    )


# ----------------------------------------------------------------
# The bucket elevator, ISO 10628-2 Table 2 items 18.7 X8065 and 18.8
# X8066.
#
# Original artwork on the screw's rule, measured off rows 18.7 and 18.8
# at :data:`pandid.render.iso_parts.M` = 10 units per module. Both rows
# draw a bucket belt closed by a pulley at each end inside a casing, with
# a loading and a discharge chute; the Z-form adds two runs and pulleys.
# Fixed drawings: the lift is not stated, and scaling would flatten the
# pulleys.
# ----------------------------------------------------------------

# Grid module of both elevator rows, in drawing units.
_LIFT_M = 10.0

# Belt half-width and pulley radius (1 M): the runs are 2 M apart.
_LIFT_R = _LIFT_M


def _lift_pulley(cx: float, cy: float) -> str:
    """Return a pulley circle of radius 1 M at ``(cx, cy)``.

    Parameters
    ----------
    cx, cy : float
        Centre.

    Returns
    -------
    str
        SVG ``<circle>``.
    """
    return (f'<circle cx="{cx:g}" cy="{cy:g}" r="{_LIFT_R:g}" '
            f'fill="none" stroke="#111" stroke-width="2"/>')


def _lift_chute(x: float, y: float, dx: float, dy: float) -> str:
    """Return a chute: a straight run then a quarter arc back to the belt.

    The run goes from ``(x, y)`` to ``(x + dx, y)`` and the arc returns to
    ``(x, y + dy)``. Only the two outer edges are drawn; the belt is the
    third side.

    Parameters
    ----------
    x, y : float
        Start on the belt.
    dx, dy : float
        Run length and arc drop, signed.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    r = abs(dx)
    return (f'<path d="M {x:g} {y:g} L {x + dx:g} {y:g} '
            f'A {r:g} {r:g} 0 0 0 {x:g} {y + dy:g}" '
            f'fill="none" stroke="#111" stroke-width="2"/>')


# ----------------------------------------------------------------
# The block flow diagram's box.
#
# An original primitive (see NOTICE section 1). Its connections are split
# across up to four faces with a count on each, so the symbol is built per
# unit and the box sizes itself to them.
# ----------------------------------------------------------------

#: Spacing of a block's connections on one face: 2.5 arrowheads, which
#: leaves a head's width of paper between adjacent arrows so they do not
#: read as one.
BLOCK_PITCH = 2.5 * ARROWHEAD

#: Smallest block box: room for a short 12 pt name, and clearly a section
#: of plant rather than a fitting.
BLOCK_MIN_WIDTH = 120.0
BLOCK_MIN_HEIGHT = 80.0

# Width of one narrow tag character at the renderer's 12 pt sans-serif,
# and the padding; :func:`pandid.portgeom.resolve_size` uses the same
# rule for boundary flags.
_LABEL_EM = 8.0
_LABEL_PAD = 30.0

# Width of a wide (CJK or fullwidth) character: a full em.
_LABEL_EM_WIDE = 12.0


def label_span(text: str) -> float:
    """Return the width a tag needs to letter ``text`` inside a box.

    Used by :func:`block_symbol` to size a box,
    ``label-overruns-symbol`` (:mod:`pandid.validate`) to check one, and
    :func:`pandid.portgeom.resolve_size` for boundary flags, so all agree.
    Narrow characters count :data:`_LABEL_EM`, wide (CJK or fullwidth) ones
    :data:`_LABEL_EM_WIDE` and combining marks nothing
    (:func:`pandid.render.furniture.script_counts`), plus padding.

    Parameters
    ----------
    text : str
        Tag text.

    Returns
    -------
    float
        Width in drawing units.
    """
    from pandid.render.furniture import script_counts
    narrow, wide, zero = script_counts(text)
    if not wide and not zero:
        return _LABEL_EM * len(text) + _LABEL_PAD
    return _LABEL_EM * narrow + _LABEL_EM_WIDE * wide + _LABEL_PAD


def block_span(count: int) -> float:
    """Return the face length needed for ``count`` block connections.

    One :data:`BLOCK_PITCH` per connection: the spacing plus half a pitch
    at each end.

    Parameters
    ----------
    count : int
        Connections on the face.

    Returns
    -------
    float
        Minimum face length.
    """
    return BLOCK_PITCH * count


def block_box_too_small(owner: str, face: str, count: int, axis: str,
                        given: float, needed: float,
                        turned: bool = False) -> ValueError:
    """Return the error for a block box too small for its connections.

    Raised by the constructor, :meth:`pandid.units.Block.nozzle`,
    :meth:`pandid.units.Block.pin` and width or height assignment, so all
    give the same message.

    Parameters
    ----------
    owner : str
        Unit name.
    face : str
        Crowded face.
    count : int
        Connections on it.
    axis : str
        ``"width"`` or ``"height"``.
    given : float
        Box size along that axis.
    needed : float
        Size the block would choose.
    turned : bool, default=False
        Whether a quarter turn moved the face onto ``axis``; explained in
        the message.

    Returns
    -------
    ValueError
        The error to raise.
    """
    spun = (f" The block is turned a quarter, so its {face} face is drawn along "
            f"the box's {axis}." if turned else "")
    return ValueError(
        f"{owner}: {count} connections on the {face} face are drawn "
        f"{BLOCK_PITCH:g} apart, which is what keeps two {ARROWHEAD:g}-unit "
        f"arrowheads from touching, and the block sized itself to {needed:g} to "
        f"hold them.{spun} {axis}={given:g} squeezes the same run into "
        f"{given / needed:.0%} of that. Give at least {axis}={needed:g}, or leave "
        f"width/height off and the block sizes itself to its connections."
    )


# Fixed face order, so the drawing does not depend on declaration order.
_BLOCK_FACES = ("W", "E", "N", "S")


@lru_cache(maxsize=None)
def block_symbol(faces: tuple[tuple[str, str], ...], label: str = "") -> Symbol:
    """Return a block flow diagram box with a port per connection.

    Each face is made at least :func:`block_span` long, so the box grows
    instead of squeezing the spacing. Every port sits on the rectangle, and
    each connection has only its declared face;
    :meth:`pandid.units.Block.nozzle` changes the declaration and rebuilds.
    Cached, as port resolution asks for it on every call.

    Parameters
    ----------
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` in the unit's port order.
    label : str, default=""
        Tag lettered inside the box, which widens it to fit. Empty when the
        unit has an explicit width, which wins.

    Returns
    -------
    Symbol
        Block symbol.
    """
    on: dict[str, list[str]] = {face: [] for face in _BLOCK_FACES}
    for port_name, face in faces:
        on[face].append(port_name)
    width = max(BLOCK_MIN_WIDTH, label_span(label),
                block_span(len(on["N"])), block_span(len(on["S"])))
    height = max(BLOCK_MIN_HEIGHT, block_span(len(on["W"])), block_span(len(on["E"])))
    ports: dict[str, tuple[float, float]] = {}
    for face in _BLOCK_FACES:
        members = on[face]
        along = height if face in ("W", "E") else width
        for i, port_name in enumerate(members):
            # extent=1.0: the box already fits the full pitch, and Block
            # refuses a smaller box.
            t = spread(i, len(members), along, BLOCK_PITCH, 1.0)
            ports[port_name] = _on_face(face, t, width, height)
    svg = (
        f'<g id="sym_block">'
        f'<rect x="0" y="0" width="{width:g}" height="{height:g}" fill="none" '
        f'stroke="black" stroke-width="2"/>'
        f'</g>'
    )
    return Symbol(
        svg=svg, width=width, height=height, ports=ports,
        # The name is lettered inside the box, so no outside label.
        label_pos="center",
        # Built to the box, so each box size is its own <defs> entry.
        id_suffix=f"_{width:g}x{height:g}",
    )


# Drawings built from the unit, not drawn once and scaled: a conveyor to
# keep its rollers round, a block, tank or vessel to fit its connection
# families. Keyed by (kind, variant), with ``None`` meaning every variant;
# the belt conveyor names its variant so the screw gets its own builder.
def _face_local(face: str, x: float, y: float, width: float, height: float
                ) -> tuple[float, float]:
    """Return a symbol-space point as (position along face, inset from edge).

    The inverse of :func:`_face_point`. A dished roof recedes from its box,
    so a crown nozzle is inset; keeping the inset (which :func:`_on_face`
    assumes is zero) lets a squeezed family stay on the drawn roofline.

    Parameters
    ----------
    face : str
        Face.
    x, y : float
        Point in symbol coordinates.
    width, height : float
        Symbol box.

    Returns
    -------
    tuple[float, float]
        ``(along, inset)``.
    """
    if face == "W":
        return y, x
    if face == "E":
        return y, width - x
    if face == "N":
        return x, y
    return x, height - y  # "S"


def _face_point(face: str, t: float, inset: float, width: float, height: float
                ) -> tuple[float, float]:
    """Return the symbol-space point at ``t`` along a face and ``inset`` in.

    The inverse of :func:`_face_local`.

    Parameters
    ----------
    face : str
        Face.
    t : float
        Position along the face.
    inset : float
        Distance in from the box edge.
    width, height : float
        Symbol box.

    Returns
    -------
    tuple[float, float]
        Point in symbol coordinates.
    """
    if face == "W":
        return inset, t
    if face == "E":
        return width - inset, t
    if face == "N":
        return t, inset
    return t, height - inset  # "S"


# Pitch and extent for tank and vessel inlet and outlet families, the
# PortSeries defaults. The extent limits how tightly a family is pitched;
# Symbol.bands limits where it may be drawn; whichever is tighter wins
# (see :func:`spread`).
_VESSEL_PITCH = 20.0
_VESSEL_EXTENT = 0.7


@lru_cache(maxsize=None)
def vessel_symbol(kind: str, variant: str, faces: tuple[tuple[str, str], ...],
                  overlays: "tuple[Overlay, ...]" = ()) -> Symbol:
    """Return a tank or vessel symbol with its inlet and outlet families placed.

    Starts from the vendored stencil with ``overlays`` composed on
    (:meth:`SymbolRegistry.composed`); this must happen here because
    :data:`_BUILT_TO_SIZE` sends tanks and vessels here before
    :meth:`SymbolRegistry.for_unit` reaches its own overlay branch. ``vent``,
    ``relief`` and ``drain`` keep the stencil's placements and menus.

    Families are squeezed, not grown, since the vendored size is
    meaningful; a single member lands exactly on the stencil's anchor. Each
    run is confined to :attr:`Symbol.bands`, the shell between roof and
    floor. The artwork itself is unchanged, so the ``<defs>`` id is shared.
    A role with one member keeps its full face menu for ``nozzle()`` and
    automatic face selection. Cached, as port resolution asks on every call.

    Parameters
    ----------
    kind : str
        ``"tank"`` or ``"vessel"``.
    variant : str
        Resolved variant.
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` for the inlet and outlet families, in port
        order.
    overlays : tuple[Overlay, ...], default=()
        The unit's composed parts, such as a vessel's supports.

    Returns
    -------
    Symbol
        Symbol with the families placed.

    Raises
    ------
    ValueError
        If a role has no placement on a requested face, or several members
        share a face with no wall (:func:`bandless_face`).
    """
    base = default_registry.composed(kind, variant, overlays)
    ports = {name: xy for name, xy in base.ports.items() if name not in ("inlet", "outlet")}
    port_faces = {
        name: dict(menu) for name, menu in base.port_faces.items()
        if name not in ("inlet", "outlet")
    }
    menus = {"inlet": base.port_faces.get("inlet", {}), "outlet": base.port_faces.get("outlet", {})}
    members_by_role: dict[str, list[str]] = {"inlet": [], "outlet": []}
    groups: dict[tuple[str, str], list[str]] = {}
    for port_name, face in faces:
        role = "inlet" if port_name.startswith("in_") else "outlet"
        members_by_role[role].append(port_name)
        groups.setdefault((role, face), []).append(port_name)
    for (role, face), members in groups.items():
        menu = menus[role]
        if face not in menu:
            raise ValueError(
                f"{kind}/{variant}: {role} has no {face!r} placement to draw "
                f"{', '.join(members)} on; offered: "
                f"{', '.join(menu) if menu else 'nothing'}"
            )
        t0, inset = _face_local(face, *menu[face], base.width, base.height)
        along = base.height if face in ("W", "E") else base.width
        band = base.bands.get(face)
        if len(members) > 1 and band is not None and band[0] >= band[1]:
            raise bandless_face(f"{kind}/{variant}", face, band[0], members,
                                walled_faces(base, role))
        for i, name in enumerate(members):
            t = spread(i, len(members), along, _VESSEL_PITCH, _VESSEL_EXTENT,
                       at=t0, band=band)
            ports[name] = _face_point(face, t, inset, base.width, base.height)
    # A lone member keeps its whole menu for nozzle() and automatic face
    # selection (:mod:`pandid.layout.faces`); members sharing a face keep
    # only their spread placement.
    for role, members in members_by_role.items():
        if len(members) == 1 and menus[role]:
            port_faces[members[0]] = dict(menus[role])
    return replace(base, ports=ports, port_faces=port_faces)


_BUILT_TO_SIZE: "dict[tuple[str, str | None], Callable[..., Symbol]]" = {
    ("conveyor", "default"): lambda unit: conveyor_symbol(unit.length,
                                                          unit.diameter),
    ("conveyor", "screw"): lambda unit: screw_conveyor_symbol(unit.length,
                                                              unit.diameter),
    ("block", None): lambda unit: unit.symbol(),
    ("tank", None): lambda unit: unit.symbol(),
    ("vessel", None): lambda unit: unit.symbol(),
}


def _built_to_size(kind: str, variant: str) -> "Callable[..., Symbol] | None":
    """Return the builder for ``(kind, variant)``, most specific first.

    Parameters
    ----------
    kind : str
        Unit kind.
    variant : str
        Resolved variant.

    Returns
    -------
    callable or None
        Function taking the unit and returning its symbol.
    """
    return _BUILT_TO_SIZE.get((kind, variant)) or _BUILT_TO_SIZE.get((kind, None))


# ----------------------------------------------------------------
# Devices drawn in a normal position.
#
# Normally closed valves: PIP PIC001 4.2.2.7 darkens the body. Neither
# ISA-5.1 nor ISO 10628 has this convention, so a sheet using it needs a
# legend entry (ISA-5.1 2.8.1(b)(1), 2.8.2, 5.2.5). See
# :class:`pandid.units.Valve`.
#
# A spectacle blind's closed state is a second registered stencil
# (``SymbolRegistry.register_closed``), not a derived mark, so it needs no
# legend entry.
# ----------------------------------------------------------------

#: Valve variants whose body may be darkened: those whose outline alone
#: still identifies the valve, with any marks and operators outside the
#: body. Others (butterfly disc, check arrow, knife blade, all inside the
#: outline) take the NC letters of PIP PIC001 4.2.2.8, which is also the
#: safe default for new variants. ``solenoid`` is included: despite the
#: stencil's name, its artwork matches the motor valve and carries no
#: fill.
NC_DARKENS = frozenset({
    "default", "gate", "globe", "ball", "needle", "plug", "pinch", "three_way",
    "angle", "bleed", "manual", "motor", "solenoid", "hydraulic",
})

#: Valve variants that may not be shown normally closed (PIP PIC001
#: 4.2.2.10: control and relief valves). ``butterfly_pneumatic`` is
#: allowed: it is usually an on-off block valve, and takes the 4.2.2.8
#: letters.
NC_FORBIDDEN = frozenset({"control", "regulator", "relief", "psv"})

# ----------------------------------------------------------------
# Body and actuator: two questions, one drawing that answers both.
#
# ISO 15519-2:2015 Table A.3 treats body and actuator separately: A.3.20,
# the general control valve with a general actuator, carries three
# registration numbers (2101A, 210A, P050B). 7.4.4.3 asks for a general
# actuator unless the type matters. The API takes ``variant`` (body) and
# ``actuator`` separately, but the draw.io stencils fuse body and operator
# into one shape, so only the pairings below can be drawn; others raise
# rather than substitute a drawing. A synthesised pairing would have no
# ``drawio_shape``. ``default`` and ``gate`` are the same stencil, ISO's
# general two-way body.
# ----------------------------------------------------------------

#: ``(body, actuator)`` -> the variant whose artwork draws that pairing.
#: :class:`pandid.units.Valve` resolves the pair and stores only the
#: variant.
ACTUATED: dict[tuple[str, str], str] = {
    # Control valve: A.3.20's general body with A.3.41's diaphragm, as on
    # professional_examples/P&ID_301.pdf and CHEE4001-7103 p.5.
    ("default", "diaphragm"): "control",
    ("gate", "diaphragm"): "control",
    # The one non-bowtie pairing.
    ("butterfly", "diaphragm"): "butterfly_pneumatic",
    # Lettered operator boxes.
    ("default", "motor"): "motor",
    ("gate", "motor"): "motor",
    ("default", "solenoid"): "solenoid",
    ("gate", "solenoid"): "solenoid",
    ("default", "hydraulic"): "hydraulic",
    ("gate", "hydraulic"): "hydraulic",
    # A handwheel is an operator, not an actuator, so it has no fail
    # position (:data:`FAIL_ACTUATED`).
    ("default", "handwheel"): "manual",
    ("gate", "handwheel"): "manual",
}

#: Actuators that may be named: the powered ones ISA-5.1 note 5.3.4(10)
#: applies failure symbols to, then the hand operator. No ``piston``: ISO
#: A.3.43 registers a cylinder (P051B) but the stencils draw none; register
#: artwork with :meth:`SymbolRegistry.register` if needed.
ACTUATORS: tuple[str, ...] = ("diaphragm", "motor", "solenoid", "hydraulic",
                              "handwheel")


def actuated_variant(body: str, actuator: str) -> str:
    """Return the variant that draws ``body`` with ``actuator`` on it.

    Parameters
    ----------
    body : str
        Body variant.
    actuator : str
        One of :data:`ACTUATORS`.

    Returns
    -------
    str
        Variant from :data:`ACTUATED`.

    Raises
    ------
    ValueError
        If the pairing has no drawing; the message lists every pairing.
    """
    drawn = ACTUATED.get((body, actuator))
    if drawn is not None:
        return drawn
    pairs = ", ".join(
        f"variant={b!r}, actuator={a!r}" for b, a in sorted(ACTUATED) if b != "gate"
    )
    raise ValueError(
        f"no symbol draws a {body!r} body with a {actuator!r} actuator on it. The "
        f"draw.io P&ID stencil set this package vendors draws each actuated valve "
        f"as one fused shape rather than as a body plus an operator, so only the "
        f"pairings it ships can be drawn: {pairs} (and 'gate' wherever 'default' "
        f"appears, which is the same drawing). Ask for the body on its own if the "
        f"sheet does not have to say what strokes it."
    )


# ----------------------------------------------------------------
# Fail position: where an actuated valve goes when its power is lost.
# A different property from ``normal_position``, marked by a different
# standard in a different place -- see :attr:`pandid.units.Valve.fail`.
# ----------------------------------------------------------------

#: Fail positions a valve may declare, with the letters drawn
#: (ANSI/ISA-5.1-2009 Table 5.4.4 Method B): ``FO``, ``FC``, ``FL``,
#: ``FI`` (fail indeterminate) and 2009's ``FL/DO`` and ``FL/DC`` (fail
#: last, drifting). Ordered for the error message.
FAIL_POSITIONS: dict[str, str] = {
    "open": "FO",
    "closed": "FC",
    "last": "FL",
    "drift_open": "FL/DO",
    "drift_closed": "FL/DC",
    "indeterminate": "FI",
}

#: Valve variants with an actuator powered from outside the valve, and so
#: a fail position (ANSI/ISA-5.1-2009 note 5.3.4(10)). Excluded:
#: hand-operated valves (``manual``, ``knife``), self-acting valves
#: (``regulator``, ``relief``, ``psv``) and bare bodies. All are two-port:
#: PIP PIC001 4.5.3.2(2) restricts multi-port valves to ``FL`` or ``FI``
#: plus fail-path arrows this package does not draw, so an actuated
#: multi-port variant must not simply be added here.
FAIL_ACTUATED = frozenset({
    "control", "butterfly_pneumatic", "solenoid", "motor", "hydraulic",
})


def fail_marking(unit) -> str:
    """Return the fail-position letters for an actuated valve.

    Uses the letters of ANSI/ISA-5.1-2009 Table 5.4.4 Method B, as PIP
    PIC001 4.5.3.2 requires, not Method A's stem arrows. The letters are
    the whole mark, so the drawing is otherwise unchanged. See
    :attr:`pandid.units.Valve.fail`.

    Parameters
    ----------
    unit : Unit
        Valve.

    Returns
    -------
    str
        Letters, or ``""`` when no fail position is declared.

    Raises
    ------
    ValueError
        If a fail position is declared on a variant with no actuator.
    """
    declared = getattr(unit, "fail", "") or ""
    if not declared:
        return ""
    # Construction refuses this, but a later variant change can reach it;
    # raise rather than silently drop the mark.
    if getattr(unit, "variant", "") not in FAIL_ACTUATED:
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: declared fail={declared!r}, but "
            f"variant {getattr(unit, 'variant', '')!r} has no actuator to lose its "
            f"motive power. The variants that take a fail position are: "
            f"{', '.join(sorted(FAIL_ACTUATED))}."
        )
    return FAIL_POSITIONS[declared]


# Fill for a darkened body: the vendored artwork's stroke colour.
_BODY_INK = "#111"

# The body is the artwork's first <path>; checked, not assumed, since
# _vendored_symbols.py is generated.
_FIRST_PATH = re.compile(r"<path\b[^>]*>")

# The body's fill before darkening (scripts/mxgraph_to_svg.DEFAULT_FILL).
_BODY_PAPER = 'fill="white"'


def closed_marking(unit, registry=None) -> str:
    """Return how a unit's normally closed position is drawn.

    ``"stencil"`` uses a second registered drawing (a spectacle blind),
    ``"fill"`` darkens the body (PIP PIC001 4.2.2.7) and ``"NC"`` letters
    the valve above and to the right (ISO 15519-1 11.4.5, Figure 28; PIP
    4.2.2.8 places it below). No ISO or ISA document fills a body. Deciding
    all three here stops the renderer both darkening and lettering a valve.

    Parameters
    ----------
    unit : Unit
        Valve or fitting.
    registry : SymbolRegistry, optional
        Registry to look up closed stencils in; ``default_registry`` when
        omitted.

    Returns
    -------
    str
        ``"stencil"``, ``"fill"``, ``"NC"``, or ``""`` when not normally
        closed.

    Raises
    ------
    ValueError
        If a non-valve with no closed drawing is normally closed.
    """
    if getattr(unit, "normal_position", "open") != "closed":
        return ""
    variant = getattr(unit, "variant", "")
    reg = default_registry if registry is None else registry
    if reg.closed_symbol(unit.kind, variant) is not None:
        return "stencil"
    # Fill and letters are valve conventions, so another closed device
    # needs a closed stencil. Construction refuses this, but a later
    # variant change can reach it; raise rather than draw it open.
    if unit.kind != "valve":
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: {unit.kind}/{variant} is drawn one "
            f"way, so nothing can show it normally closed. Either it is the wrong "
            f"variant for a device that isolates a line, or normal_position should "
            f"be 'open'."
        )
    return "fill" if variant in NC_DARKENS else "NC"


def darkened(sym: Symbol) -> Symbol:
    """Return ``sym`` with its body filled: the normally closed valve.

    A separate symbol with the ``_nc`` id suffix, since the open and closed
    valves need separate ``<defs>``; box and ports are unchanged.

    Parameters
    ----------
    sym : Symbol
        Open valve symbol.

    Returns
    -------
    Symbol
        Darkened symbol.

    Raises
    ------
    ValueError
        If the first ``<path>`` is not a paper-filled body.
    """
    head = _FIRST_PATH.search(sym.svg)
    if head is None or _BODY_PAPER not in head.group(0):
        raise ValueError(
            f"{sym.symbol_id()}: cannot be darkened -- its first <path> is not a "
            f"paper-filled body. A symbol whose body is not the first path it "
            f"draws does not belong in NC_DARKENS; PIP PIC001 4.2.2.8's NC "
            f"abbreviation is what such a valve states its position with."
        )
    filled = head.group(0).replace(_BODY_PAPER, f'fill="{_BODY_INK}"', 1)
    svg = sym.svg[:head.start()] + filled + sym.svg[head.end():]
    return Symbol(
        svg=re.sub(r'id="([^"]*)"', r'id="\1_nc"', svg, count=1),
        width=sym.width, height=sym.height, ports=dict(sym.ports),
        port_faces={name: dict(faces) for name, faces in sym.port_faces.items()},
        faceless_ports=sym.faceless_ports, port_series=sym.port_series,
        label_pos=sym.label_pos, id_suffix=sym.id_suffix + "_nc",
        stretchable=sym.stretchable, bare_run=sym.bare_run,
        gravity_fixed=sym.gravity_fixed,
        # The fill travels with the draw.io reference, or the export would
        # show the valve open.
        drawio_shape=sym.drawio_shape, drawio_flip_h=sym.drawio_flip_h,
        drawio_fill=_BODY_INK,
    )


# ----------------------------------------------------------------
# The fitting piped the other way round.
#
# A reducer and an expander are one casting installed either way round,
# and the drawing must show which way the cone points. ``pin(mirrored="x")``
# cannot say this, since it mirrors the ports too and the run would enter
# from downstream. This derivation mirrors only the artwork and keeps
# ``inlet`` west and ``outlet`` east. See
# :attr:`pandid.units.Reducer.large_end`.
# ----------------------------------------------------------------

# Face after a left-to-right mirror.
_FLIPPED_FACE = {"W": "E", "E": "W", "N": "N", "S": "S"}

# A symbol's artwork split into opening <g>, contents and closing tag. Every
# symbol is one group, so :func:`expander` and :func:`compose` can reach
# the contents without parsing SVG.
_GROUP = re.compile(r"\A(<g\b[^>]*>)(.*)(</g>)\Z", re.DOTALL)


def expander(sym: Symbol) -> Symbol:
    """Return ``sym`` turned end for end: the fitting piped the other way.

    The artwork is mirrored left to right and ``inlet`` and ``outlet``
    trade placements, so ``inlet`` stays west and the run passes in its
    drawn direction; every placement is mirrored with its ink. A separate
    symbol with the ``_exp`` id suffix, as for :func:`darkened`.

    Parameters
    ----------
    sym : Symbol
        Reducer symbol.

    Returns
    -------
    Symbol
        Expander symbol.

    Raises
    ------
    ValueError
        If the ports are not exactly ``inlet`` and ``outlet``, or the
        artwork is not a single ``<g>``.
    """
    swap = {"inlet": "outlet", "outlet": "inlet"}
    # Only inlet and outlet: any other port would be silently dropped.
    if set(sym.ports) != set(swap) or sym.port_series:
        raise ValueError(
            f"{sym.symbol_id()}: cannot be turned end for end -- its nozzles are "
            f"{sorted(set(sym.ports) | {s.prefix + '*' for s in sym.port_series})}. "
            f"Only a fitting whose whole connection list is 'inlet' and 'outlet' "
            f"has two ends to trade."
        )
    match = _GROUP.match(sym.svg)
    if match is None:
        raise ValueError(
            f"{sym.symbol_id()}: cannot be turned end for end -- its artwork is "
            f"not a single <g> group to mirror"
        )
    head, body, tail = match.groups()
    head = re.sub(r'id="([^"]*)"', r'id="\1_exp"', head, count=1)
    # Mirror about the box's mid-line so the drawing stays in its box.
    svg = (f'{head}<g transform="translate({sym.width:g},0) scale(-1,1)">'
           f'{body}</g>{tail}')

    def turn(xy: tuple[float, float]) -> tuple[float, float]:
        """Return ``xy`` mirrored left to right in the symbol box."""
        return (round(sym.width - xy[0], 4), xy[1])

    return Symbol(
        svg=svg, width=sym.width, height=sym.height,
        ports={new: turn(sym.ports[old]) for new, old in swap.items()},
        port_faces={new: {_FLIPPED_FACE[face]: turn(xy)
                          for face, xy in sym.port_faces[old].items()}
                    for new, old in swap.items()},
        faceless_ports=sym.faceless_ports,
        label_pos=sym.label_pos, id_suffix=sym.id_suffix + "_exp",
        stretchable=sym.stretchable, bare_run=sym.bare_run,
        gravity_fixed=sym.gravity_fixed,
        # The flip travels with the draw.io reference, or the export would
        # draw the reduction.
        drawio_shape=sym.drawio_shape, drawio_fill=sym.drawio_fill,
        drawio_flip_h=not sym.drawio_flip_h,
    )


# ----------------------------------------------------------------
# The body carrying its parts. See the block above :class:`IsoPart` for
# when a drawing may be composed.
# ----------------------------------------------------------------


@dataclass(frozen=True)
class OverlayPart:
    """One supplementary symbol's artwork, and the ISO item it is.

    A part is only ever combined with a body, never drawn alone, which
    makes it a supplementary symbol under ISO 14617-1 3.3 rather than a
    basic one under 3.2. It is drawn in its own ``width`` x ``height`` box
    with (0, 0) at the top left, and :func:`compose` maps that box onto the
    rectangle of the body an :class:`Overlay` names.

    A part's ports are added to the body's, never substituted: an agitator
    brings its ``drive`` (ISO item 1.27 X8006 draws the shaft up through
    the head to the item 20.6 C0082 motor), while internals (group 27) and
    characteristics (group 29) are marks no line reaches and anchor nothing.
    A unit connects to a part's port only if it declares it in ``PORTS`` or
    ``_VARIANT_PORTS``.

    Attributes
    ----------
    name : str
        pandid's spelling and half the registry key, such as ``"turbine"``
        for "Agitator, turbine type".
    iso : IsoPart
        The Table 2 row this drawing claims to be.
    svg : str
        A single ``<g>`` group; only its contents are painted onto a body.
    width, height : float
        Box the artwork is drawn in.
    ports : dict[str, tuple[float, float]]
        Connections the part brings, in the part's own coordinates.
        Usually empty.
    stretchable : bool, default=True
        Whether the artwork may be scaled unevenly. A tray deck may; an
        impeller or a manhole may not. A part that may not is scaled evenly
        and centred, and makes the whole composition unstretchable.
    gravity_fixed : bool, default=False
        Whether the part states that gravity does the work, as item 29.1's
        settling arrow does; the body then may not be turned (ISO 14617-1
        4.5).
    directional : bool, default=False
        Whether an axis flip would reverse what the artwork says.
    drawio_shape : str, default=""
        draw.io stencil that draws this part alone, such as ``Prop
        Agitator``; empty where the part is exported as geometry.

    Raises
    ------
    ValueError
        If the name is blank, the box is empty, the artwork is not a single
        ``<g>`` group, or a port lies outside the box.
    """

    name: str
    iso: IsoPart
    svg: str
    width: float
    height: float
    ports: dict = field(default_factory=dict)
    stretchable: bool = True
    gravity_fixed: bool = False
    directional: bool = False
    drawio_shape: str = ""

    def __post_init__(self) -> None:
        """Check the name, box, artwork and port positions."""
        if not self.name.strip():
            raise ValueError(
                f"{self.iso.reg}: a part needs a name to be registered and asked for "
                f"under; it is half the registry key"
            )
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"{self.iso.reg}: a part is drawn in a {self.width:g} x "
                f"{self.height:g} box, which has nothing to map onto a body"
            )
        if _GROUP.match(self.svg) is None:
            raise ValueError(
                f"{self.iso.reg}: a part's artwork has to be a single <g> group, so "
                f"compose() can paint its contents onto a body without parsing the SVG"
            )
        for port, xy in self.ports.items():
            if not (0 <= xy[0] <= self.width and 0 <= xy[1] <= self.height):
                raise ValueError(
                    f"{self.iso.reg}: the {port!r} nozzle is at {xy}, outside the "
                    f"{self.width:g} x {self.height:g} box the part is drawn in; a "
                    f"placement outside the artwork lands wherever the part is scaled "
                    f"to, which is nowhere in particular"
                )

    def key(self) -> "tuple[int, str]":
        """Return the registry key: ISO subject group, then pandid's name."""
        return (self.iso.group, self.name)


# A copy of pandid.render.svg._at_pen_scale's pattern; that module imports
# this one, so it cannot be imported here.
_STROKE = re.compile(r'stroke-width="([\d.]+)"')


def _at_part_scale(svg: str, scale: float) -> str:
    """Return ``svg`` with every line weight divided by ``scale``.

    ISO 14617-1 4.3 requires resizing to leave line width unchanged. A part
    is scaled onto its rectangle, so dividing its weights first keeps the
    drawn weights the ones the part declares.

    Parameters
    ----------
    svg : str
        Part artwork.
    scale : float
        Scale the part will be drawn at.

    Returns
    -------
    str
        Artwork with compensated stroke widths.
    """
    if math.isclose(scale, 1.0, rel_tol=1e-9):
        return svg
    return _STROKE.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


def _shifted_bands(body: Symbol, ox: float, oy: float
                   ) -> "dict[str, tuple[float, float]]":
    """Return ``body.bands`` moved onto the composed box.

    Bands are absolute coordinates along a face, so they move by ``oy`` on
    a W/E face and ``ox`` on an N/S face and are not rescaled.

    Parameters
    ----------
    body : Symbol
        Body being composed.
    ox, oy : float
        Offset of the body within the composed box.

    Returns
    -------
    dict[str, tuple[float, float]]
        Face to ``(start, end)`` along that face.
    """
    if (ox, oy) == (0.0, 0.0):
        return dict(body.bands)
    return {face: (lo + (oy if face in ("W", "E") else ox),
                   hi + (oy if face in ("W", "E") else ox))
            for face, (lo, hi) in body.bands.items()}


def _shifted_series(series: PortSeries, body: Symbol, ox: float, oy: float,
                    width: float, height: float) -> PortSeries:
    """Return ``series`` moved and rescaled onto the composed box.

    ``at`` and ``pitch`` are absolute but ``extent`` is a fraction of the
    face, so on a grown box ``at`` moves with the ink and ``extent`` is
    rescaled to cover the same length of wall. Otherwise a family would
    move along the face, as when a motor is drawn above a vessel.

    Parameters
    ----------
    series : PortSeries
        Body's port series.
    body : Symbol
        Body being composed.
    ox, oy : float
        Offset of the body within the composed box.
    width, height : float
        Composed box.

    Returns
    -------
    PortSeries
        The series, unchanged if the face neither moved nor grew.
    """
    along, grown = ((body.height, height) if series.face in ("W", "E")
                    else (body.width, width))
    offset = oy if series.face in ("W", "E") else ox
    if (offset, along) == (0.0, grown):
        return series
    at = (along / 2 if series.at is None else series.at) + offset
    return replace(series, at=at, extent=series.extent * along / grown)


def compose(body: Symbol, parts: "list[tuple[Overlay, OverlayPart]]",
            iso_reg: str = "") -> Symbol:
    """Return ``body`` with its supplementary parts painted over it.

    The result is one :class:`Symbol`, placed, resized, mirrored, exported
    and cached like any other, with its own ``<defs>`` id as for
    :func:`darkened` and :func:`expander`. Each part maps from its own box
    onto the fraction of the body box its :class:`Overlay` names, so
    stretching the finished symbol keeps parts in proportion.

    The composition is:

    - stretchable only if the body and every part are, since the renderer
      stretches the finished symbol as one drawing and a round impeller
      must stay round (ISO 14617-1 4.4);
    - gravity-fixed or directional if the body or any part is, so a body
      carrying item 29.1's settling arrow may not be turned (ISO 14617-1
      4.5) or flipped.

    The composed box is the union of the body's and every part's. A part
    outside the body, such as item 1.27's motor above the head, grows the
    box and shifts the ink, fixed ports and port series
    (:func:`_shifted_series`) with it. A body port that would then be
    nearest a different face is refused, since its stream would leave
    through the wrong side; clear the crown first, as item 1.27 does.

    The result has no ``drawio_shape``: a stencil names one shape, and a
    composed reactor exported as its body would silently lose its parts.
    draw.io reads :attr:`Symbol.overlays` and
    :attr:`Symbol.drawio_body_shape` instead and emits one cell per part
    grouped under the body.

    Parameters
    ----------
    body : Symbol
        Body; its artwork must be a single ``<g>`` group.
    parts : list[tuple[Overlay, OverlayPart]]
        Placements and the parts placed.
    iso_reg : str, default=""
        Registration number of the composition, where it reproduces a
        tabulated symbol (a body with item 29.2 is X8125). The body's is not
        carried over.

    Returns
    -------
    Symbol
        Composed symbol.

    Raises
    ------
    ValueError
        If the body is not a single group, a body port would change face,
        or a part port reuses a body port name.
    """
    match = _GROUP.match(body.svg)
    if match is None:
        raise ValueError(
            f"{body.symbol_id()}: cannot carry a part -- its artwork is not a "
            f"single <g> group to compose into"
        )
    head, inner, tail = match.groups()

    # Each part's placement in body coordinates, before the box grows.
    placed = []
    for overlay, part in parts:
        rx, ry = overlay.x * body.width, overlay.y * body.height
        rw, rh = overlay.w * body.width, overlay.h * body.height
        sx, sy = rw / part.width, rh / part.height
        if not part.stretchable:
            # Letterbox as pandid.portgeom.ink_box does: keep the aspect,
            # take the smaller scale and centre the rest.
            scale = min(sx, sy)
            rx, ry = rx + (rw - scale * part.width) / 2, ry + (rh - scale * part.height) / 2
            sx = sy = scale
        placed.append((part, rx, ry, sx, sy, overlay.mirror))

    xs = [0.0, body.width]
    ys = [0.0, body.height]
    for part, rx, ry, sx, sy, _ in placed:
        xs += [rx, rx + sx * part.width]
        ys += [ry, ry + sy * part.height]
    # Shift the union's top-left corner to the origin; zero when every
    # part is inside the body. ``+ 0.0`` turns -0.0 into 0.0, which would
    # otherwise be written as ``-0``.
    ox, oy = -min(xs) + 0.0, -min(ys) + 0.0
    width, height = max(xs) + ox, max(ys) + oy

    art = [inner if (ox, oy) == (0.0, 0.0)
           else f'<g transform="translate({ox:g},{oy:g})">{inner}</g>']
    for part, rx, ry, sx, sy, mirror in placed:
        contents = _GROUP.match(part.svg).group(2)  # type: ignore[union-attr]
        # Mirror about the rectangle's own centre line: translate to its
        # right edge and scale x by -1, as the ports below are mapped.
        left = rx + ox + (sx * part.width if mirror else 0.0)
        # Compensate strokes by the geometric mean of the two scales, as
        # pandid.render.svg._pen_scale does; abs() ignores the mirror sign.
        art.append(
            f'<g transform="translate({left:g},{ry + oy:g}) '
            f'scale({-sx if mirror else sx:g},{sy:g})">'
            f'{_at_part_scale(contents, math.sqrt(abs(sx * sy)))}</g>'
        )

    def shift(xy: "tuple[float, float]") -> "tuple[float, float]":
        """Return a body point moved into the composed box."""
        return (round(xy[0] + ox, 4), round(xy[1] + oy, 4))

    ports = {name: shift(xy) for name, xy in body.ports.items()}
    # A port leaves by its nearest box edge (:func:`pandid.portgeom.
    # outward_dir`), so a grown box can move a crown nozzle onto a side.
    # Refuse it here, where the message can name the part.
    for name, menu in body.port_faces.items():
        for face, xy in menu.items():
            moved = shift(xy)
            lands = outward_dir(moved[0], moved[1], width, height)
            if lands != face:
                raise ValueError(
                    f"{body.symbol_id()}: a part drawn outside the body grows the box "
                    f"to {width:g}x{height:g}, and the {name!r} nozzle at {moved} is "
                    f"then nearest the {lands} edge rather than the {face} face it is "
                    f"drawn on -- a stream routed to it would leave through the side "
                    f"of the body. Place the part inside the body's box, or give the "
                    f"body a drawing whose box already holds it"
                )
    for part, rx, ry, sx, sy, mirror in placed:
        for name, (px, py) in part.ports.items():
            if name in ports:
                raise ValueError(
                    f"{body.symbol_id()}: the {part.iso.reg} part anchors a nozzle "
                    f"called {name!r}, and the body already has one. A part adds "
                    f"connections and never replaces them, since two nozzles under "
                    f"one name draw a stream to whichever survived the merge"
                )
            # Map through the artwork's transform, mirror included.
            along = (part.width - px) if mirror else px
            ports[name] = (round(rx + ox + sx * along, 4), round(ry + oy + sy * py, 4))

    return Symbol(
        svg=head + "".join(art) + tail,
        width=round(width, 4), height=round(height, 4),
        ports=ports,
        # The body's face menu, moved with the ink and checked above.
        port_faces={name: {face: shift(xy) for face, xy in menu.items()}
                    for name, menu in body.port_faces.items()},
        faceless_ports=body.faceless_ports,
        port_series=tuple(_shifted_series(s, body, ox, oy, width, height)
                          for s in body.port_series),
        # Moved with the ink, not lengthened.
        bands=_shifted_bands(body, ox, oy),
        label_pos=body.label_pos,
        # One definition per composition, as for darkened() and
        # expander(). A short blake2s digest keeps ids readable and, unlike
        # hash(), stable across processes for the golden fixtures.
        id_suffix=body.id_suffix + "_c" + hashlib.blake2s(
            repr([o for o, _ in parts]).encode(), digest_size=4).hexdigest(),
        stretchable=body.stretchable and all(p.stretchable for p, *_ in placed),
        bare_run=body.bare_run,
        gravity_fixed=body.gravity_fixed or any(p.gravity_fixed for p, *_ in placed),
        directional=body.directional or any(p.directional for p, *_ in placed),
        # Not the body's; see the docstring. The exporter reads the body's
        # stencil from drawio_body_shape.
        drawio_shape="",
        drawio_body_shape=body.drawio_shape or body.drawio_body_shape,
        drawio_flip_h=body.drawio_flip_h, drawio_fill=body.drawio_fill,
        overlays=tuple(overlay for overlay, _ in parts),
        # Not the body's number, which would mislabel the composition; the
        # caller states the composition's own number where it has one.
        iso_reg=iso_reg,
    )


# ISO 10628-2 Table 2's separating vessel: the empty outline every group-8
# row except the cyclone is drawn on. Measured off item 8.3 in grid
# modules: a 6 M x 6 M rectangle over a 3 M V, 6 M x 9 M overall, the same
# ratio as the 80 x 120 draw.io separator stencils. Not registered as a
# variant, since ISO has no empty separator (item 8.1 X8081 draws arrows
# inside it); it is the body for SymbolRegistry._register_composed.
_SEPARATING_VESSEL = Symbol(
    svg='<g id="sym_separator_vessel">'
        '<path d="M 0 0 L 80 0 L 80 80 L 40 120 L 0 80 Z" '
        'fill="white" stroke="#111" stroke-width="2"/></g>',
    width=80.0, height=120.0,
    # Anchors as on the mechanical separators: high draw opposite the
    # feed, collected phase out of the apex. Feeds are the series below.
    ports={"vapor": (80.0, 12.0), "liquid": (40.0, 120.0)},
    # Feeds run down the west wall from (0, 12) (:data:`FROM_START`): the
    # wall is y 0..80 and a centred family would reach the top corner.
    port_series=(PortSeries("feed_", "W", pitch=20.0, extent=0.5, at=12.0,
                            singular="feed", align=FROM_START),),
    # A hopper collects at its apex, so it may not be turned (ISO 15519-1
    # 11.4.2).
    gravity_fixed=True,
)


# ISO 10628-2 group 9's shared outline: an 8 M x 8 M square, at 10 units
# to the module as for _CRUSHER_OUTLINE.
_CENTRIFUGE_SQ = 80.0

# Ink outside the square, one module: a shaft below the floor (9.1-9.4)
# or a feed pipe through the west wall (9.5-9.8). Both are equipment
# geometry, not connection ticks, so the box holds them.
_CENTRIFUGE_MARGIN = 10.0


def _centrifuge_outline(ox: float) -> str:
    """Return the bare group-9 square with its west wall at ``ox``.

    Parameters
    ----------
    ox : float
        0 for 9.1-9.4; :data:`_CENTRIFUGE_MARGIN` for 9.5-9.8, whose box is
        one module wider for the feed pipe (:data:`_CENTRIFUGE_SIDE_PORTS`).

    Returns
    -------
    str
        SVG path.
    """
    return (f'<path d="M {ox:g} 0 L {ox + _CENTRIFUGE_SQ:g} 0 '
            f'L {ox + _CENTRIFUGE_SQ:g} {_CENTRIFUGE_SQ:g} '
            f'L {ox:g} {_CENTRIFUGE_SQ:g} Z" fill="white" stroke="#111" stroke-width="2"/>')


# A perforated wall's three ink runs, as (start, end) offsets from the
# square's near edge, measured off item 9.2: 1 M ink, 1 M gap, 2 M ink,
# 1 M gap, 1 M ink, a module in from each end. Items 9.5, 9.7 and 9.8 use
# it turned 90 degrees.
_CENTRIFUGE_DASH = ((10.0, 20.0), (30.0, 50.0), (60.0, 70.0))


def _dashed_wall(fixed: float, offset: float, vertical: bool) -> str:
    """Return one perforated wall drawn as :data:`_CENTRIFUGE_DASH`'s runs.

    Parameters
    ----------
    fixed : float
        The wall's x (vertical) or y (horizontal).
    offset : float
        Position of the square's left or top edge along the wall.
    vertical : bool
        Whether the wall is vertical.

    Returns
    -------
    str
        SVG lines.
    """
    out = []
    for a, b in _CENTRIFUGE_DASH:
        p0, p1 = offset + a, offset + b
        if vertical:
            out.append(f'<line x1="{fixed:g}" y1="{p0:g}" x2="{fixed:g}" y2="{p1:g}" '
                       f'fill="none" stroke="#111" stroke-width="2"/>')
        else:
            out.append(f'<line x1="{p0:g}" y1="{fixed:g}" x2="{p1:g}" y2="{fixed:g}" '
                       f'fill="none" stroke="#111" stroke-width="2"/>')
    return "".join(out)


# Ports of 9.1-9.4: feed on the top-edge tick, overflow on the east wall
# 2 M down (the position 9.3, 9.4 and 9.6 draw; 9.1 and 9.2 draw it at
# 0 M), underflow at the end of the drawn shaft a module below the floor.
_CENTRIFUGE_TOP_PORTS = {
    "feed": (40.0, 0.0),
    "overflow": (80.0, 20.0),
    "underflow": (40.0, 90.0),
}

# Ports of 9.5-9.8: feed at the end of the pipe drawn through the west
# wall, overflow as for 9.1-9.4 shifted a module for the margin, underflow
# at the tick below the south-east corner, where a screw discharges.
_CENTRIFUGE_SIDE_PORTS = {
    "feed": (0.0, 40.0),
    "overflow": (90.0, 20.0),
    "underflow": (80.0, 80.0),
}

# Item 9.1 X2619: an open funnel (two strokes rising from the floor, 2 M
# apart at the top) and the shaft a module below the floor.
_CENTRIFUGE_ROTOR = (
    '<path d="M 10 70 L 30 20 M 50 20 L 70 70 L 10 70" '
    'fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="40" y1="70" x2="40" y2="90" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.2 X2614: a 6 M x 6 M basket inset a module from the walls, open
# at the top, with perforated (broken) side walls.
_CENTRIFUGE_BASKET_DASHED = (
    _dashed_wall(10.0, 0.0, True) + _dashed_wall(70.0, 0.0, True) +
    '<line x1="10" y1="70" x2="70" y2="70" fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="40" y1="70" x2="40" y2="90" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.3 X8035: 9.2's basket with solid side walls.
_CENTRIFUGE_BASKET_SOLID = (
    '<path d="M 10 70 L 10 10 M 70 70 L 70 10 M 10 70 L 70 70" '
    'fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="40" y1="70" x2="40" y2="90" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.4 X8036: two chevrons 2 M apart (the disc stack edge on) on a
# shaft from above the top chevron to below the floor.
_CENTRIFUGE_DISC_STACK = (
    '<path d="M 10 24 L 40 10 L 70 24 M 10 44 L 40 30 L 70 44" '
    'fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="40" y1="10" x2="40" y2="90" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.5 X8037: a basket lying on its side with a solid west wall and
# perforated roof and floor, the feed pipe at mid-height and a zigzag
# screw flight inside.
_CENTRIFUGE_SCREW_PERFORATED = (
    '<line x1="20" y1="10" x2="20" y2="70" fill="none" stroke="#111" stroke-width="2"/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    '<line x1="0" y1="40" x2="80" y2="40" fill="none" stroke="#111" stroke-width="2"/>'
    '<path d="M 30 40 L 40 20 L 60 60 L 70 40" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.6 X8082, the decanter (the Centrifuge default): 9.5 with a solid
# roof and floor.
_CENTRIFUGE_SCREW_SOLID = (
    '<path d="M 20 70 L 20 10 L 80 10 M 20 70 L 80 70" '
    'fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="0" y1="40" x2="80" y2="40" fill="none" stroke="#111" stroke-width="2"/>'
    '<path d="M 30 40 L 40 20 L 60 60 L 70 40" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.7 X8038: 9.5's basket with a pusher rod in place of the screw;
# the feed pipe stops at the rod.
_CENTRIFUGE_PUSHER = (
    '<line x1="20" y1="10" x2="20" y2="70" fill="none" stroke="#111" stroke-width="2"/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    '<line x1="0" y1="40" x2="30" y2="40" fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="30" y1="20" x2="30" y2="60" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 9.8 X8039: 9.5's basket with the feed stopping at the wall and a
# skimmer tube near the roof.
_CENTRIFUGE_SKIMMER = (
    '<line x1="20" y1="10" x2="20" y2="70" fill="none" stroke="#111" stroke-width="2"/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    '<line x1="0" y1="40" x2="20" y2="40" fill="none" stroke="#111" stroke-width="2"/>'
    '<path d="M 70 20 L 50 20 L 50 10 L 60 20" fill="none" stroke="#111" stroke-width="2"/>'
)


def _centrifuge(name: str, reg: str, width: float, height: float, ox: float,
               detail: str, ports: dict) -> Symbol:
    """Return one group-9 centrifuge: the shared square plus its row's mark.

    There is no draw.io stencil for a centrifuge, so none is named. Not
    gravity-fixed: rotation, not gravity, separates (ISO 15519-1 11.4.2).

    Parameters
    ----------
    name : str
        Variant, used in the SVG id.
    reg : str
        ISO registration number.
    width, height : float
        Box.
    ox : float
        West wall offset (:func:`_centrifuge_outline`).
    detail : str
        The row's mark.
    ports : dict
        Port positions.

    Returns
    -------
    Symbol
        The centrifuge symbol.
    """
    return Symbol(
        svg=f'<g id="sym_centrifuge_{name}">{_centrifuge_outline(ox)}{detail}</g>',
        width=width, height=height, ports=dict(ports),
        iso_reg=reg,
    )


# ISO 10628-2 group 11's shared outline, measured off rows 11.1-11.12: a
# trapezoid 10 M across the top, 6 M across the bottom and 6 M deep, at 10
# units to the module (:data:`~pandid.render.iso_parts.M`). Keeping the
# standard's proportions keeps composed group-29 marks undistorted.
_CRUSHER_W, _CRUSHER_H = 100.0, 60.0

# The trapezoid path. Not registered, since ISO has no empty trapezoid.
_CRUSHER_OUTLINE = (
    f'<path d="M 0 0 L {_CRUSHER_W:g} 0 L {_CRUSHER_W * 0.8:g} {_CRUSHER_H:g} '
    f'L {_CRUSHER_W * 0.2:g} {_CRUSHER_H:g} Z" '
    f'fill="white" stroke="#111" stroke-width="2"/>'
)

# Foot of the mill's corner chord on the sloping wall. The chord starts
# 2.5 M in on the top edge and falls 4 down per 3 across; the wall is
# x = y/3 (in modules), so the foot is at (10/13, 30/13) M. From row 11.8.
_MILL_CHORD_X, _MILL_CHORD_Y = 100 / 13, 300 / 13

# Group 11's only two ticks: feed above the top edge, discharge below the
# bottom. ISO draws no drive connection for these machines.
_CRUSHER_PORTS = {"feed": (_CRUSHER_W / 2, 0.0),
                  "discharge": (_CRUSHER_W / 2, _CRUSHER_H)}


def _crushing_machine(name: str, reg: str, *detail: str) -> Symbol:
    """Return one group-11 body: the shared trapezoid plus its mark.

    Gravity-fixed, since feed falls in at the top and out at the bottom
    (ISO 15519-1 11.4.2). There is no draw.io stencil.

    Parameters
    ----------
    name : str
        Name used in the SVG id.
    reg : str
        Registration number of the row it reproduces, or ``""``.
    *detail : str
        Marks drawn inside the outline.

    Returns
    -------
    Symbol
        The body.
    """
    return Symbol(
        svg=f'<g id="sym_{name}">{_CRUSHER_OUTLINE}'
            + "".join(detail) + "</g>",
        width=_CRUSHER_W, height=_CRUSHER_H,
        ports=dict(_CRUSHER_PORTS),
        gravity_fixed=True,
        iso_reg=reg,
    )


# Crusher mark, ISO item 11.2 X8085: two full-depth verticals at x 9 and
# 15 M, carried by 11.3-11.7. Drawn into the body, as group 29 has no
# such part.
_CRUSHER_JAWS = (
    f'<path d="M {_CRUSHER_W * 0.2:g} 0 L {_CRUSHER_W * 0.2:g} {_CRUSHER_H:g} '
    f'M {_CRUSHER_W * 0.8:g} 0 L {_CRUSHER_W * 0.8:g} {_CRUSHER_H:g}" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
)

# Mill mark, ISO item 11.8 X8086: two chords cutting the top corners
# (:data:`_MILL_CHORD_X`), carried by 11.9-11.12; body, not part.
_MILL_CHAMFERS = (
    f'<path d="M 25 0 L {_MILL_CHORD_X:.4f} {_MILL_CHORD_Y:.4f} '
    f'M 75 0 L {_CRUSHER_W - _MILL_CHORD_X:.4f} {_MILL_CHORD_Y:.4f}" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
)

# Vibration mill drum, ISO item 11.12 X8054: a 4 M circle holding 29.14's
# arrows. Group 29 has no circle, so the drum is body; without it the
# composition would not be X8054.
_VIBRATION_DRUM = (
    f'<circle cx="{_CRUSHER_W / 2:g}" cy="{_CRUSHER_H / 2:g}" r="20" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
)


# Stack inlet on the tapering west wall, (2,0) M to (1,10) M. Row 4.7
# ticks it at 9 M, but there the point is nearer the bottom edge and
# outward_dir would face it south, so it is held at 8 M, where
# x = 2 - (8/10) M keeps it on the west face.
_STACK_INLET_Y = 80.0
_STACK_INLET_X = 20.0 - (20.0 - 10.0) * (_STACK_INLET_Y / 100.0)


# ISO 10628-2 group 10's shared outline, from row 10.1: an 8 M x 12 M
# casing with 1 M x 2 M chamfers at the top corners, origin at the
# chamfer's top-left. Rows 10.1-10.7 differ only in the mark inside.
_DRIER_W, _DRIER_H = 80.0, 120.0
_DRIER_OUTLINE = (
    '<path d="M 0 120 L 0 20 L 10 0 L 70 0 L 80 20 L 80 120 Z" '
    'fill="white" stroke="#111" stroke-width="2"/>'
)

# feed and product are group 10's two ticks, mid-way down the straight
# walls. No row ticks a third, so heating_in and vent are centred on the
# floor and the flat top (see :class:`~pandid.units.Dryer`).
_DRIER_PORTS = {
    "feed": (0.0, 70.0), "product": (80.0, 70.0),
    "heating_in": (40.0, 120.0), "vent": (40.0, 0.0),
}


def _drier(name: str, reg: str, *detail: str, gravity_fixed: bool = False) -> Symbol:
    """Return one group-10 dryer: the shared casing plus its mark.

    Group 10 has no supplementary parts, so marks are drawn into the body.

    Parameters
    ----------
    name : str
        Name used in the SVG id.
    reg : str
        ISO registration number.
    *detail : str
        Marks drawn inside the casing.
    gravity_fixed : bool, default=False
        True only where the mark itself relies on gravity, as a tray
        dryer's shelves do; the casing's horizontal feed and discharge do
        not.

    Returns
    -------
    Symbol
        The dryer symbol.
    """
    return Symbol(
        svg=f'<g id="sym_drier_{name}">{_DRIER_OUTLINE}' + "".join(detail) + "</g>",
        width=_DRIER_W, height=_DRIER_H,
        ports=dict(_DRIER_PORTS),
        gravity_fixed=gravity_fixed,
        iso_reg=reg,
    )


# Item 10.2 X8083: three centred 4 M shelf lines at y 3, 4 and 5 M.
_DRIER_SHELVES = "".join(
    f'<line x1="20" y1="{y:g}" x2="60" y2="{y:g}" fill="none" stroke="#111" '
    f'stroke-width="2"/>' for y in (30, 40, 50))

# Item 10.3 X8040: a shaft up to the chamfered top crossed by two shelf
# lines and a wider third broken at the shaft (the rotating disc stack).
_DRIER_TURBO = (
    '<path d="M 20 30 L 60 30 M 20 50 L 60 50 M 0 40 L 30 40 M 50 40 L 80 40 '
    'M 40 50 L 40 0" fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 10.6 X8043: two 1.5 M rollers centred at x 1.75 and 6.25 M, y 4 M,
# with belt lines at y 3.25 and 4.75 M.
_DRIER_BELT = (
    '<circle cx="17.5" cy="40" r="7.5" fill="none" stroke="#111" stroke-width="2"/>'
    '<circle cx="62.5" cy="40" r="7.5" fill="none" stroke="#111" stroke-width="2"/>'
    '<path d="M 17.5 32.5 L 62.5 32.5 M 17.5 47.5 L 62.5 47.5" '
    'fill="none" stroke="#111" stroke-width="2"/>'
)


# ISO 10628-2 group 5's shared outline, from row 5.1: a trapezoid 4 M
# wide at the top widening to 8 M at a shoulder 8 M down, on a 2 M basin,
# 8 M x 10 M overall. Rows 5.1-5.8 differ only in fill and draught marks.
_TOWER_W, _TOWER_TRAP_H, _TOWER_H = 80.0, 80.0, 100.0
_TOWER_OUTLINE = (
    '<path d="M 20 0 L 60 0 L 80 80 L 80 100 L 0 100 L 0 80 Z" '
    'fill="white" stroke="#111" stroke-width="2"/>'
    '<line x1="0" y1="80" x2="80" y2="80" fill="none" stroke="#111" stroke-width="2"/>'
)

# The six CoolingTower ports: air out of the apex, water in (west) and air
# in (east) at the basin's mid-height (row 5.1's side ticks), and three
# bottom connections. ISO ticks no bottom connection, so water_out, makeup
# and blowdown are offered, not read off a mark.
_TOWER_PORTS = {
    "air_out": (40.0, 0.0),
    "water_in": (0.0, 90.0), "air_in": (80.0, 90.0),
    "water_out": (40.0, 100.0), "makeup": (20.0, 100.0), "blowdown": (60.0, 100.0),
}

# Dry-fill mark (items 5.2-5.4, 5.8), from row 5.2: a rule at the basin's
# mid-height (y 13 M) with seven 1 M ticks a module apart.
_TOWER_DRY = (
    '<line x1="0" y1="90" x2="80" y2="90" fill="none" stroke="#111" stroke-width="2"/>'
    + "".join(f'<line x1="{x:g}" y1="85" x2="{x:g}" y2="95" fill="none" stroke="#111" '
              f'stroke-width="2"/>' for x in range(10, 71, 10))
)

# Wet-fill mark (items 5.5-5.8), from row 5.5: a distribution stub off the
# west wall at y 4 M ending in an upward arrow.
_TOWER_WET = (
    '<path d="M 10 40 L 40 40 M 30 50 L 40 40 L 50 50 M 40 40 L 40 50" '
    'fill="none" stroke="#111" stroke-width="2"/>'
)

def _tower_fan(cy: float) -> str:
    """Return a 2 M fan circle with bow-tie blades centred at height ``cy``.

    Low for forced draught (items 5.3, 5.6) and high for induced draught
    (5.4, 5.7); rows 5.3 and 5.4 differ only in this height.

    Parameters
    ----------
    cy : float
        Centre height in drawing units.

    Returns
    -------
    str
        SVG elements.
    """
    return (
        f'<circle cx="40" cy="{cy:g}" r="10" fill="none" stroke="#111" stroke-width="2"/>'
        f'<path d="M 36 {cy - 9:g} L 31 {cy + 5:g} M 44 {cy - 9:g} L 49 {cy + 5:g}" '
        f'fill="none" stroke="#111" stroke-width="2"/>'
    )


_TOWER_FAN_FORCED = _tower_fan(65.0)
_TOWER_FAN_INDUCED = _tower_fan(15.0)


# ISO 10628-2 item 18.7 X8065, the bucket elevator, measured in modules:
# an 8 M x 12 M casing (origin at its top-left); belt runs at x 3 and 5 M
# from y 2 to 10 M between 1 M pulleys; loading chute west at y 8 M and
# discharge chute east at y 4 M. ISO's ticks are vertical (in at the top,
# out at the bottom), which as nozzles would put the discharge below the
# feed. So the home ports are on the walls at the chute heights, in low
# west and out high east, and ISO's directions are offered as N and S
# faces.
_BUCKET_ELEVATOR = Symbol(
    svg='<g id="sym_elevator">'
        '<rect x="0" y="0" width="80" height="120" '
        'fill="white" stroke="#111" stroke-width="2"/>'
        '<path d="M 30 20 L 30 100 M 50 20 L 50 100" '
        'fill="none" stroke="#111" stroke-width="2"/>'
        + _lift_pulley(40, 20) + _lift_pulley(40, 100)
        # Head chute east and boot chute west, each a quadrant whose third
        # side is the belt run.
        + _lift_chute(50, 40, 2 * _LIFT_M, -2 * _LIFT_M)
        + _lift_chute(30, 80, -2 * _LIFT_M, 2 * _LIFT_M)
        + '</g>',
    width=80.0, height=120.0,
    ports={"feed": (0.0, 80.0), "discharge": (80.0, 40.0)},
    # Row 18.7's own ticks, offered as alternatives.
    port_faces={"feed": {"N": (10.0, 0.0)},
                "discharge": {"S": (70.0, 120.0)}},
    # Pulleys must stay round.
    stretchable=False,
    # It raises material, so it may not be turned (ISO 15519-1 11.4.2).
    gravity_fixed=True,
    iso_reg="X8065",
)

# ISO 10628-2 item 18.8 X8066, the Z-form bucket elevator: an eight-sided
# Z casing (2,13) (2,9) (10,9) (10,1) (22,1) (22,5) (14,5) (14,13) M, a
# 20 M x 12 M box, with the belt in three runs (low arm, riser, high arm),
# each drawn as two edges 2 M apart. ISO ticks the feed above the low arm
# and the discharge below the high arm, but those points are nearer a side
# edge of the box than the crown (outward_dir), so the ports are on the
# arms' end walls instead: in at the west end low, out at the east end
# high.
_Z_ELEVATOR = Symbol(
    svg='<g id="sym_elevator_z_form">'
        '<path d="M 0 120 L 0 80 L 80 80 L 80 0 L 200 0 L 200 40 '
        'L 120 40 L 120 120 Z" fill="white" stroke="#111" stroke-width="2"/>'
        '<path d="M 20 90 L 100 90 M 20 110 L 100 110 '
        'M 90 20 L 90 100 M 110 20 L 110 100 '
        'M 100 10 L 180 10 M 100 30 L 180 30" '
        'fill="none" stroke="#111" stroke-width="2"/>'
        # Pulleys at the loop's ends and at its two corners.
        + _lift_pulley(20, 100) + _lift_pulley(100, 100)
        + _lift_pulley(100, 20) + _lift_pulley(180, 20)
        + '</g>',
    width=200.0, height=120.0,
    ports={"feed": (0.0, 100.0), "discharge": (200.0, 20.0)},
    stretchable=False,
    gravity_fixed=True,
    iso_reg="X8066",
)


# ----------------------------------------------------------------
# ISO 10628-2 group 19: proportioners, feeders and distribution, and item
# 19.5, the spray nozzle. 19.1 and 19.2 share a 4 M circle; 19.3 and 19.4
# are their own drawings. Group 19 has no supplementary parts, so marks are
# drawn into the body.
# ----------------------------------------------------------------

# The 4 M circle of 19.1 C2056 and 19.2 X8067, fed from above and
# discharging below.
_FEEDER_CIRCLE = 40.0
_FEEDER_CIRCLE_PORTS = {"feed": (20.0, 0.0), "discharge": (20.0, 40.0)}


def _feeder_circle(name: str, reg: str, mark: str) -> Symbol:
    """Return one group-19 circle body: the shared rim plus its mark.

    Gravity-fixed: fed from above and discharged below (ISO 15519-1
    11.4.2).

    Parameters
    ----------
    name : str
        Name used in the SVG id.
    reg : str
        ISO registration number.
    mark : str
        The row's mark.

    Returns
    -------
    Symbol
        The feeder symbol.
    """
    return Symbol(
        svg=f'<g id="sym_feeder_{name}">'
            f'<circle cx="20" cy="20" r="20" fill="white" stroke="#111" '
            f'stroke-width="2"/>{mark}</g>',
        width=_FEEDER_CIRCLE, height=_FEEDER_CIRCLE,
        ports=dict(_FEEDER_CIRCLE_PORTS),
        gravity_fixed=True,
        iso_reg=reg,
    )


# Item 19.1 C2056: a Z in one stroke, two 3.46 M bars at y 1 and 3 M,
# each 0.27 M in from the wall, joined by the diagonal.
_FEEDER_Z = (
    '<path d="M 37.3 30 L 2.7 30 L 37.3 10 L 2.7 10" '
    'fill="none" stroke="#111" stroke-width="2"/>'
)

# Item 19.2 X8067: a rotary valve rotor end-on, a 0.3 M hub with six
# spokes 60 degrees apart reaching the rim.
_FEEDER_HUB_R = 3.0
_FEEDER_ROTOR_ANGLES = (0, 60, 120, 180, 240, 300)


def _feeder_rotor(cx: float, cy: float, hub_r: float, rim_r: float) -> str:
    """Return a hub circle and spokes from the hub to the rim.

    Parameters
    ----------
    cx, cy : float
        Centre.
    hub_r, rim_r : float
        Hub and rim radii.

    Returns
    -------
    str
        SVG elements.
    """
    ink = 'fill="none" stroke="#111" stroke-width="2"'
    spokes = "".join(
        f'<line x1="{cx + hub_r * math.cos(math.radians(a)):g}" '
        f'y1="{cy + hub_r * math.sin(math.radians(a)):g}" '
        f'x2="{cx + rim_r * math.cos(math.radians(a)):g}" '
        f'y2="{cy + rim_r * math.sin(math.radians(a)):g}" {ink}/>'
        for a in _FEEDER_ROTOR_ANGLES
    )
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{hub_r:g}" {ink}/>' + spokes


_FEEDER_ROTOR_MARK = _feeder_rotor(20.0, 20.0, _FEEDER_HUB_R, 20.0)


# ISO item 19.3 C0074, the rotary table feeder: a 5 M table bar, a shaft
# down 6 M to the discharge, and the rotation as a 5 M x 2.5 M ellipse two
# thirds down. ISO breaks the ellipse at the arrow; only the arrow is
# drawn, at the ellipse's east point where the tangent is vertical.
_FEEDER_TABLE_W = 50.0
_FEEDER_TABLE_H = 60.0
_FEEDER_TABLE = (
    '<line x1="0" y1="0" x2="50" y2="0" fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="25" y1="0" x2="25" y2="60" fill="none" stroke="#111" stroke-width="2"/>'
    '<ellipse cx="25" cy="37.5" rx="25" ry="12.5" fill="none" stroke="#111" '
    'stroke-width="2"/>'
    # Rotation arrow: a 0.7 M tail up the east tangent with a head in
    # 29.1's proportions (1 M long, about 0.5 M wide).
    '<line x1="50" y1="37.5" x2="50" y2="30.5" fill="none" stroke="#111" '
    'stroke-width="2"/>'
    '<polygon points="50,27.5 47.3,30.5 52.7,30.5" fill="#111" stroke="none"/>'
)

# ISO item 19.4 C0035, the metering feeder: a 14.8 M beam with a 2.2 M
# pan at each end and a fulcrum triangle (base 3 M below, 1.7 M each side).
# The beam sits 0.3 M below the top edge so the end ports are not on box
# corners, where outward_dir cannot tell north from west or east.
_METER_W = 148.0
_METER_H = 33.0
_METER_BEAM_Y = 3.0
_METER_PAN_R = 22.0
_METER = (
    f'<line x1="0" y1="{_METER_BEAM_Y:g}" x2="{_METER_W:g}" y2="{_METER_BEAM_Y:g}" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
    f'<path d="M 0 {_METER_BEAM_Y:g} A {_METER_PAN_R:g} {_METER_PAN_R:g} 0 0 1 '
    f'{2 * _METER_PAN_R:g} {_METER_BEAM_Y:g}" fill="none" stroke="#111" stroke-width="2"/>'
    f'<path d="M {_METER_W - 2 * _METER_PAN_R:g} {_METER_BEAM_Y:g} '
    f'A {_METER_PAN_R:g} {_METER_PAN_R:g} 0 0 1 {_METER_W:g} {_METER_BEAM_Y:g}" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
    f'<path d="M {_METER_W / 2:g} {_METER_BEAM_Y:g} L {_METER_W / 2 - 17:g} '
    f'{_METER_BEAM_Y + 30:g} L {_METER_W / 2 + 17:g} {_METER_BEAM_Y + 30:g} Z" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
)

# ISO item 19.5 2037, the spray nozzle: a three-pronged fan 4 M x 2 M
# meeting under a header, apex (2 M, 0), legs to (0, 2), (2, 2) and
# (4, 2) M. ISO ticks the header on both sides, so the header spans the box
# and inlet is offered west and east (:class:`~pandid.units.SprayNozzle`).
# The port sits 0.1 M below the header, off the box corner, as for
# _METER_BEAM_Y.
_SPRAY_W = 40.0
_SPRAY_H = 20.0
_SPRAY_PORT_Y = 1.0
_SPRAY_NOZZLE = Symbol(
    svg='<g id="sym_spray_nozzle">'
        f'<line x1="0" y1="0" x2="{_SPRAY_W:g}" y2="0" fill="none" stroke="#111" '
        f'stroke-width="2"/>'
        '<path d="M 20 0 L 0 20 M 20 0 L 20 20 M 20 0 L 40 20" '
        'fill="none" stroke="#111" stroke-width="2"/></g>',
    width=_SPRAY_W, height=_SPRAY_H,
    ports={"inlet": (0.0, _SPRAY_PORT_Y)},
    port_faces={"inlet": {"E": (_SPRAY_W, _SPRAY_PORT_Y)}},
    iso_reg="2037",
)


# ----------------------------------------------------------------
# ISO 10628-2 group 12: mixers and kneaders. 12.1-12.3 are one box with
# one, two or three "N" mixing elements. 12.2 is the vendored
# fitting/static_mixer, which matches item 12.2 X2673 and is registered
# rather than redrawn (pandid.render._vendored_symbols). 12.4, the kneader,
# draws a wave and is :class:`~pandid.units.Kneader`.
# ----------------------------------------------------------------

def _mix_element(x0: float) -> str:
    """Return one 4 M "N" mixing element in the 6 M group-12 band.

    A top stub from y 0.5 to 2.5 M, a diagonal to the opposite corner and a
    bottom stub from y 3.5 to 5.5 M, as on items 12.1-12.3.

    Parameters
    ----------
    x0 : float
        Left edge.

    Returns
    -------
    str
        SVG path.
    """
    ink = 'fill="none" stroke="#111" stroke-width="2"'
    return (
        f'<path d="M {x0:g} 5 L {x0:g} 25 M {x0:g} 5 L {x0 + 40:g} 55 '
        f'M {x0 + 40:g} 35 L {x0 + 40:g} 55" {ink}/>'
    )


# ISO item 12.1 X2672, the in-line rotary mixer: a 12 M x 6 M box with two
# elements and a flow-axis stroke at mid-height reaching a module past the
# west wall, which _MIXER_W includes so inlet lands on ink.
_MIXER_W = 130.0
_MIXER_H = 60.0
_MIXER_PORTS = {"inlet": (0.0, 30.0), "outlet": (_MIXER_W, 30.0)}
_ROTARY_MIXER = Symbol(
    svg='<g id="sym_fitting_rotary_mixer">'
        '<path d="M 10 0 L 130 0 L 130 60 L 10 60 Z" '
        'fill="white" stroke="#111" stroke-width="2"/>'
        '<line x1="0" y1="30" x2="130" y2="30" fill="none" stroke="#111" '
        'stroke-width="2"/>'
        + _mix_element(20.0) + _mix_element(70.0)
        + '</g>',
    width=_MIXER_W, height=_MIXER_H,
    ports=dict(_MIXER_PORTS),
    iso_reg="X2672",
    # An in-line piping accessory (:attr:`Symbol.trim`).
    trim=True,
)

# ISO item 12.3 X8184, the mixing path: a 16 M x 6 M box with three
# elements, 1 M margins and gaps, ticks at mid-height, no flow-axis stroke.
_PATH_W = 160.0
_PATH_H = 60.0
_MIXING_PATH = Symbol(
    svg='<g id="sym_fitting_mixing_path">'
        '<path d="M 0 0 L 160 0 L 160 60 L 0 60 Z" '
        'fill="white" stroke="#111" stroke-width="2"/>'
        + _mix_element(10.0) + _mix_element(60.0) + _mix_element(110.0)
        + '</g>',
    width=_PATH_W, height=_PATH_H,
    ports={"inlet": (0.0, 30.0), "outlet": (_PATH_W, 30.0)},
    iso_reg="X8184",
    # An in-line piping accessory, as _ROTARY_MIXER.
    trim=True,
)

# ISO item 12.4 X8134, the kneader: a 10 M x 6 M casing crossed on its
# centre line by one wave (up 1 M, down 2 M, back up 1 M), poking 1 M out
# of the west wall as 12.1's axis does.
_KNEADER_W = 110.0
_KNEADER_H = 60.0
_KNEADER_PORTS = {"inlet": (0.0, 30.0), "outlet": (_KNEADER_W, 30.0)}
_KNEADER = Symbol(
    svg='<g id="sym_kneader">'
        '<path d="M 10 0 L 110 0 L 110 60 L 10 60 Z" '
        'fill="white" stroke="#111" stroke-width="2"/>'
        '<path d="M 0 30 L 20 30 L 40 20 L 70 40 L 100 30 L 110 30" '
        'fill="none" stroke="#111" stroke-width="2"/></g>',
    width=_KNEADER_W, height=_KNEADER_H,
    ports=dict(_KNEADER_PORTS),
    # Shafts driven from above over a trough below, so not turned.
    gravity_fixed=True,
    iso_reg="X8134",
)


# ----------------------------------------------------------------
# ISO 10628-2 item 24.15, registered 2181: the steam trap. Hand-drawn
# because the draw.io "Steam Trap" is an empty box identical to its
# "Desuper Heater" (see scripts/vendor_symbols.py). The half-filled body is
# in no group 26-29, so it is drawn into the body, not composed.
# ----------------------------------------------------------------

#: Steam trap body diameter: a 4 M circle on the run's horizontal axis.
TRAP_BODY_D = 40.0

#: Run drawn each side of the trap body: 1 M. ISO leaves this gap empty;
#: it is drawn so the ports are on ink.
TRAP_LEAD = 10.0

TRAP_W = TRAP_LEAD + TRAP_BODY_D + TRAP_LEAD
_TRAP_H = TRAP_BODY_D
_TRAP_R = TRAP_BODY_D / 2
_TRAP_CX = TRAP_LEAD + _TRAP_R
_TRAP_CY = _TRAP_H / 2

# Half the 45-degree diameter on each axis, from lower left to upper right.
_TRAP_SEAT = _TRAP_R / math.sqrt(2)

# Ports on the horizontal diameter, at the ends of the leads.
_TRAP_PORTS = {"inlet": (0.0, _TRAP_CY), "outlet": (TRAP_W, _TRAP_CY)}

# Layer 1: the run into and out of the body.
_TRAP_RUN = (
    f'<path d="M 0 {_TRAP_CY:g} L {TRAP_LEAD:g} {_TRAP_CY:g} '
    f'M {TRAP_LEAD + TRAP_BODY_D:g} {_TRAP_CY:g} L {TRAP_W:g} {_TRAP_CY:g}" '
    f'fill="none" stroke="#111" stroke-width="2"/>'
)

# Layer 2: the body, filled white so lines behind it are hidden.
_TRAP_BODY = (
    f'<circle cx="{_TRAP_CX:g}" cy="{_TRAP_CY:g}" r="{_TRAP_R:g}" '
    f'fill="white" stroke="#111" stroke-width="2"/>'
)

# Layer 3: the half below the diameter, filled. Two quarter arcs, since a
# 180-degree arc has an undetermined centre when _scaled_path redraws it.
_TRAP_DISCHARGE = (
    f'<path d="M {_TRAP_CX - _TRAP_SEAT:.6f} {_TRAP_CY + _TRAP_SEAT:.6f} '
    f'A {_TRAP_R:g} {_TRAP_R:g} 0 0 0 '
    f'{_TRAP_CX + _TRAP_SEAT:.6f} {_TRAP_CY + _TRAP_SEAT:.6f} '
    f'A {_TRAP_R:g} {_TRAP_R:g} 0 0 0 '
    f'{_TRAP_CX + _TRAP_SEAT:.6f} {_TRAP_CY - _TRAP_SEAT:.6f} Z" '
    f'fill="#111" stroke="#111" stroke-width="2"/>'
)

_STEAM_TRAP = Symbol(
    svg='<g id="sym_fitting_steam_trap">'
        + _TRAP_RUN + _TRAP_BODY + _TRAP_DISCHARGE
        + '</g>',
    width=TRAP_W, height=_TRAP_H,
    ports=dict(_TRAP_PORTS),
    # Stretching would change the 45-degree diameter, so keep the aspect.
    stretchable=False,
    # A piping accessory at half equipment weight (ISO 10628-1 5.3.1 c)).
    trim=True,
    iso_reg="2181",
)


# ----------------------------------------------------------------
# ISO 10628-2 group 7: screening devices, sieves and rakes. Six rows share
# _SCREEN_OUTLINE with different marks; 7.7 has a taller box for its
# rollers (_REEL_OUTLINE). The vendored separator/sifter is not one of
# these rows (group 8 proportions, a different mesh mark) and is left
# unregistered here.
# ----------------------------------------------------------------

# Group 7 outline (all rows but 7.7), from row 7.1: a 6 M x 6 M wall
# square over a 3 M point, 6 M x 9 M, the 2:2:1 proportion of
# _SEPARATING_VESSEL.
_SCREEN_W, _SCREEN_H = 60.0, 90.0
_SCREEN_OUTLINE = (
    '<path d="M 0 0 L 60 0 L 60 60 L 30 90 L 0 60 Z" '
    'fill="white" stroke="#111" stroke-width="2"/>'
)

# From row 7.1: feed above the top edge, oversize out of the east wall
# five sixths of the way down, undersize out of the apex
# (:class:`~pandid.units.ScreeningDevice`).
_SCREEN_PORTS = {"feed": (30.0, 0.0), "oversize": (60.0, 50.0), "undersize": (30.0, 90.0)}

# ISO's 2 M dash, 1 M gap, as iso_parts._DASH_LONG; repeated because
# iso_parts imports this module.
_SCREEN_DASH = 'stroke-dasharray="20,10"'

# The dashed corner-to-corner mesh diagonal, (0,0) to (60,60): item 7.1
# X8123's mark and the base of 7.2-7.5.
_SCREEN_MESH = (
    f'<line x1="0" y1="0" x2="60" y2="60" fill="none" stroke="#111" '
    f'stroke-width="2" {_SCREEN_DASH}/>'
)


def _screen(name: str, reg: str, mark: str) -> Symbol:
    """Return one group-7 screen: the shared outline plus its row's mark.

    Gravity-fixed: oversize stays on the deck and undersize falls through
    (ISO 15519-1 11.4.2).

    Parameters
    ----------
    name : str
        Name used in the SVG id.
    reg : str
        ISO registration number.
    mark : str
        The row's mark.

    Returns
    -------
    Symbol
        The screen symbol.
    """
    return Symbol(
        svg=f'<g id="sym_screen_{name}">{_SCREEN_OUTLINE}{mark}</g>',
        width=_SCREEN_W, height=_SCREEN_H,
        ports=dict(_SCREEN_PORTS),
        gravity_fixed=True,
        iso_reg=reg,
    )


# cos 45 = sin 45, the axis step of a tick perpendicular to the mesh
# diagonal; local copy of iso_parts._SQ2.
_SCREEN_SQ2 = math.sqrt(2) / 2


def _rake_teeth(points: "tuple[float, ...]", half_len: float) -> str:
    """Return rake teeth crossing :data:`_SCREEN_MESH` at right angles.

    Item 7.2 X8026 draws three coarse teeth and 7.3 X8027 five finer ones.

    Parameters
    ----------
    points : tuple[float, ...]
        Fractions along the diagonal.
    half_len : float
        Half the tooth length.

    Returns
    -------
    str
        SVG lines.
    """
    ink = 'fill="none" stroke="#111" stroke-width="2"'
    out = []
    for t in points:
        x, y = 60 * t, 60 * t
        dx = dy = half_len * _SCREEN_SQ2
        out.append(f'<line x1="{x + dx:g}" y1="{y - dy:g}" x2="{x - dx:g}" '
                    f'y2="{y + dy:g}" {ink}/>')
    return "".join(out)


def _screen_vibration() -> str:
    """Return item 7.5 X2605's vibration mark beside the mesh diagonal.

    Two opposed arrows on tracks either side of the diagonal, as item
    29.14 draws oscillation, turned to 45 degrees and kept beside the
    diagonal's middle so the mesh stays legible. Built from the diagonal's
    unit vectors ``along`` and ``across``, so the tracks are parallel to it.

    Returns
    -------
    str
        SVG elements.
    """
    along = (_SCREEN_SQ2, _SCREEN_SQ2)
    across = (_SCREEN_SQ2, -_SCREEN_SQ2)
    ink = 'fill="none" stroke="#111" stroke-width="2"'

    def track(tail: "tuple[float, float]", tip: "tuple[float, float]") -> str:
        """Return one arrow from ``tail`` to ``tip``, head 6 units long."""
        base = (tip[0] - 6 * along[0], tip[1] - 6 * along[1])
        wing = 2.5
        left = (base[0] + wing * across[0], base[1] + wing * across[1])
        right = (base[0] - wing * across[0], base[1] - wing * across[1])
        return (
            f'<line x1="{tail[0]:g}" y1="{tail[1]:g}" x2="{base[0]:g}" '
            f'y2="{base[1]:g}" {ink}/>'
            f'<polygon points="{tip[0]:g},{tip[1]:g} {left[0]:g},{left[1]:g} '
            f'{right[0]:g},{right[1]:g}" fill="#111" stroke="none"/>'
        )

    # Tracks 4 units either side of the midpoint (30, 30), 10 units long,
    # pointing away from each other.
    o1 = (30 + 4 * across[0], 30 + 4 * across[1])
    o2 = (30 - 4 * across[0], 30 - 4 * across[1])
    return (
        track((o1[0] - 5 * along[0], o1[1] - 5 * along[1]),
              (o1[0] + 5 * along[0], o1[1] + 5 * along[1]))
        + track((o2[0] + 5 * along[0], o2[1] + 5 * along[1]),
                 (o2[0] - 5 * along[0], o2[1] - 5 * along[1]))
    )


_SCREEN_VIBRATION = _screen_vibration()

# Item 7.6 X8029: the rotating drum, dashed as a hidden rotating part, a
# 1.5 M radius circle at (30, 45).
_SCREEN_DRUM = (
    '<circle cx="30" cy="45" r="15" fill="none" stroke="#111" stroke-width="2" '
    + _SCREEN_DASH + "/>"
)

# ISO item 7.7 X8030's outline: an 8 M x 12 M wall over a 4 M point,
# 8 M x 16 M, the group's 2:2:1 proportion in a larger box for the rollers.
_REEL_W, _REEL_H = 80.0, 160.0
_REEL_OUTLINE = (
    '<path d="M 0 0 L 80 0 L 80 120 L 40 160 L 0 120 Z" '
    'fill="white" stroke="#111" stroke-width="2"/>'
)

# 7.7 is ticked on the west and east walls at y 20, level with the top
# roller, rather than above the top edge.
_REEL_PORTS = {"feed": (0.0, 20.0), "oversize": (_REEL_W, 20.0), "undersize": (40.0, 160.0)}

# Item 7.7 X8030: two 1 M rollers 8 M apart on the centre line, joined by
# dashed rails a module either side (the wire basket). The basket's sag is
# not drawn.
_REEL_MARK = (
    '<circle cx="40" cy="20" r="10" fill="none" stroke="#111" stroke-width="2"/>'
    '<circle cx="40" cy="100" r="10" fill="none" stroke="#111" stroke-width="2"/>'
    '<line x1="30" y1="30" x2="30" y2="90" fill="none" stroke="#111" stroke-width="2" '
    + _SCREEN_DASH + "/>"
    '<line x1="50" y1="30" x2="50" y2="90" fill="none" stroke="#111" stroke-width="2" '
    + _SCREEN_DASH + "/>"
)

_REEL_BODY = Symbol(
    svg=f'<g id="sym_screen_basket_reel">{_REEL_OUTLINE}{_REEL_MARK}</g>',
    width=_REEL_W, height=_REEL_H,
    ports=dict(_REEL_PORTS),
    gravity_fixed=True,
    iso_reg="X8030",
)


# ----------------------------------------------------------------
# Evaporators and kilns: pandid's own drawings, since ISO 10628-2 has
# neither. They carry no registration number (ISO 14617-1 3.6; see
# :class:`IsoPart`), and every feature has a named dimension so the
# drawing can be checked by measurement.
# ----------------------------------------------------------------

# Detail weight, ISO 10628-1:2014 5.3.1 c), and outline weight, 5.3.1 b).
# Repeated from iso_parts.PART_STROKE, since iso_parts imports this module.
_DETAIL = 'fill="none" stroke="#111" stroke-width="1"'
_OUTLINE = 'fill="white" stroke="#111" stroke-width="2"'


# Evaporator body: dished head, straight side, dished bottom. 80 wide like
# the other upright bodies; heads 12 deep on a 40 half-width, as the
# vendored dished vessels; a 136 straight side to hold both the heating
# element and the disengaging space.
_EVAP_W = 80.0
_EVAP_HEAD = 12.0
_EVAP_SHELL = 136.0
_EVAP_H = 2 * _EVAP_HEAD + _EVAP_SHELL

_EVAP_OUTLINE = (
    f'<path d="M 0 {_EVAP_HEAD:g} '
    f'A {_EVAP_W / 2:g} {_EVAP_HEAD:g} 0 0 1 {_EVAP_W:g} {_EVAP_HEAD:g} '
    f'L {_EVAP_W:g} {_EVAP_HEAD + _EVAP_SHELL:g} '
    f'A {_EVAP_W / 2:g} {_EVAP_HEAD:g} 0 0 1 0 {_EVAP_HEAD + _EVAP_SHELL:g} Z" '
    f'{_OUTLINE}/>'
)

# Long-tube heating band (falling film, climbing film and the general row):
# a third of the way down the shell to a fifth off the bottom, leaving
# disengaging space above and a pool below.
_EVAP_TUBE_TOP, _EVAP_TUBE_BOT = 60.0, 130.0

# Short-tube (calandria) band: 32 units against 70, centred on the long
# band.
_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT = 79.0, 111.0

# Steam-chest ports sit this far inside their tubesheet, so they read as
# the chest's. Steam enters west and condensate leaves east, so in a
# left-to-right multiple-effect train each effect's vapour reaches the next
# effect's west wall without crossing the body.
_EVAP_STEAM_INSET = 6.0

# Feed height above the element (falling film, onto the top tubesheet) and
# below it (climbing film, into the tube bottoms).
_EVAP_FEED_HIGH, _EVAP_FEED_LOW = 30.0, 140.0


def _evap_tubesheets(top: float, bot: float) -> str:
    """Return the two tubesheets, drawn wall to wall as welded sheets.

    Parameters
    ----------
    top, bot : float
        Tubesheet heights.

    Returns
    -------
    str
        SVG path.
    """
    return (f'<path d="M 0 {top:g} L {_EVAP_W:g} {top:g} '
            f'M 0 {bot:g} L {_EVAP_W:g} {bot:g}" {_DETAIL}/>')


def _evap_tubes(top: float, bot: float, xs: "tuple[float, ...]") -> str:
    """Return tubes between the tubesheets at each x in ``xs``.

    Parameters
    ----------
    top, bot : float
        Tubesheet heights.
    xs : tuple[float, ...]
        Tube positions.

    Returns
    -------
    str
        SVG path.
    """
    return ('<path d="'
            + " ".join(f"M {x:g} {top:g} L {x:g} {bot:g}" for x in xs)
            + f'" {_DETAIL}/>')


# The general row draws an unspecified element as a closed box inset from
# the walls; a bare pair of lines would read as a tray.
_EVAP_ELEMENT_INSET = 12.0
_EVAP_ELEMENT = (
    f'<rect x="{_EVAP_ELEMENT_INSET:g}" y="{_EVAP_TUBE_TOP:g}" '
    f'width="{_EVAP_W - 2 * _EVAP_ELEMENT_INSET:g}" '
    f'height="{_EVAP_TUBE_BOT - _EVAP_TUBE_TOP:g}" {_DETAIL}/>'
)


# Long-tube rows: five tubes on a 12-unit pitch, centred; a picture of a
# bundle, not a count.
_EVAP_TUBE_XS = (16.0, 28.0, 40.0, 52.0, 64.0)

# Calandria: three tubes either side of a central downcomer, drawn as two
# walls at twice the 8-unit tube pitch so it does not read as a tube.
_EVAP_CALANDRIA_PITCH = 8.0
_EVAP_CALANDRIA_XS = (8.0, 16.0, 24.0, 56.0, 64.0, 72.0)
_EVAP_DOWNCOMER_XS = (32.0, 48.0)

# Falling-film distributor: a tray 8 units above the top tubesheet with
# three drops; the only mark that differs from the climbing-film row.
_EVAP_DISTRIBUTOR_GAP = 8.0
_EVAP_DISTRIBUTOR_DROP = 5.0
_EVAP_DISTRIBUTOR_XS = (24.0, 40.0, 56.0)
_EVAP_DISTRIBUTOR = (
    f'<path d="M 8 {_EVAP_TUBE_TOP - _EVAP_DISTRIBUTOR_GAP:g} '
    f'L 72 {_EVAP_TUBE_TOP - _EVAP_DISTRIBUTOR_GAP:g}'
    + "".join(
        f' M {x:g} {_EVAP_TUBE_TOP - _EVAP_DISTRIBUTOR_GAP:g} '
        f'L {x:g} {_EVAP_TUBE_TOP - _EVAP_DISTRIBUTOR_GAP + _EVAP_DISTRIBUTOR_DROP:g}'
        for x in _EVAP_DISTRIBUTOR_XS)
    + f'" {_DETAIL}/>'
)

# Plate row: nine plates on an 8-unit pitch wall to wall, with no
# tubesheets.
_EVAP_PLATE_XS = tuple(8.0 + 8.0 * i for i in range(9))
_EVAP_PLATES = (
    '<path d="'
    + " ".join(f"M {x:g} {_EVAP_TUBE_TOP:g} L {x:g} {_EVAP_TUBE_BOT:g}"
               for x in _EVAP_PLATE_XS)
    + f'" {_DETAIL}/>'
)


def _evaporator(name: str, *detail: str,
                band: "tuple[float, float]" = (_EVAP_TUBE_TOP, _EVAP_TUBE_BOT),
                feed_y: float = _EVAP_FEED_HIGH) -> Symbol:
    """Return one evaporator: the shared shell plus its element.

    Steam-chest ports are placed from ``band``, so they follow the element.
    Gravity-fixed: vapour leaves the crown and concentrate the bottom (ISO
    15519-1 11.4.2).

    Parameters
    ----------
    name : str
        Variant, used in the SVG id.
    *detail : str
        Element marks.
    band : tuple[float, float], default=(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT)
        Heating element's top and bottom.
    feed_y : float, default=_EVAP_FEED_HIGH
        Feed height on the west wall.

    Returns
    -------
    Symbol
        The evaporator symbol.
    """
    top, bot = band
    return Symbol(
        svg=f'<g id="sym_evaporator_{name}">{_EVAP_OUTLINE}' + "".join(detail) + "</g>",
        width=_EVAP_W, height=_EVAP_H,
        ports={
            "feed": (0.0, feed_y),
            "vapor": (_EVAP_W / 2, 0.0),
            "concentrate": (_EVAP_W / 2, _EVAP_H),
            "heating_in": (0.0, top + _EVAP_STEAM_INSET),
            "condensate": (_EVAP_W, bot - _EVAP_STEAM_INSET),
        },
        gravity_fixed=True,
    )


# Rotary kiln shell: 26 units of fall over 180 of length. Much steeper
# than a real kiln, since a near-level cylinder would read as a rotary
# dryer (ISO item 10.7 X8044).
_KILN_W = 180.0
_KILN_BORE = 28.0
_KILN_FALL = 26.0
_KILN_H = _KILN_BORE + _KILN_FALL


def _kiln_top(x: float) -> float:
    """Return the shell's upper wall height at ``x``.

    Every mark and port is placed through this, so they follow
    :data:`_KILN_FALL`.

    Parameters
    ----------
    x : float
        Distance along the kiln.

    Returns
    -------
    float
        Height of the upper wall.
    """
    return _KILN_FALL * x / _KILN_W


_KILN_OUTLINE = (
    f'<path d="M 0 0 L {_KILN_W:g} {_KILN_FALL:g} '
    f'L {_KILN_W:g} {_KILN_H:g} L 0 {_KILN_BORE:g} Z" {_OUTLINE}/>'
)

# Riding rings: position along the shell and how far they stand proud.
# They show the shell rotates.
_KILN_RING_XS = (60.0, 130.0)
_KILN_RING_PROUD = 5.0
_KILN_RINGS = (
    '<path d="'
    + " ".join(
        f"M {x:g} {_kiln_top(x) - _KILN_RING_PROUD:g} "
        f"L {x:g} {_kiln_top(x) + _KILN_BORE + _KILN_RING_PROUD:g}"
        for x in _KILN_RING_XS)
    + f'" {_DETAIL}/>'
)

# Girth gear and pinion: an 18 x 7 block under the shell between the
# rings, where the drive station stands.
_KILN_DRIVE_X, _KILN_DRIVE_W, _KILN_DRIVE_H = 95.0, 18.0, 7.0
_KILN_DRIVE = (
    f'<rect x="{_KILN_DRIVE_X - _KILN_DRIVE_W / 2:g}" '
    f'y="{_kiln_top(_KILN_DRIVE_X) + _KILN_BORE:g}" '
    f'width="{_KILN_DRIVE_W:g}" height="{_KILN_DRIVE_H:g}" {_DETAIL}/>'
)

# Solids in at the high end, out at the low end. Fired counter-current
# from the discharge end, so offgas leaves at the feed end; fuel and air
# enter the hood underneath at the discharge end.
_KILN_PORTS = {
    "feed": (0.0, _KILN_BORE / 2),
    "product": (_KILN_W, _KILN_FALL + _KILN_BORE / 2),
    "offgas": (24.0, _kiln_top(24.0)),
    "air": (140.0, _kiln_top(140.0) + _KILN_BORE),
    "fuel": (160.0, _kiln_top(160.0) + _KILN_BORE),
}

# Fluidised-bed calciner: dished crown, straight freeboard and a windbox
# cone. The dashed distributor grid where the walls meet the cone is the
# defining mark (dashed as perforated, like item 27.5). The bed is not
# drawn; it is part 27.7 (2604) in iso_parts.
_FBC_W = 90.0
_FBC_CROWN = 12.0
_FBC_FREEBOARD = 98.0
_FBC_CONE = 40.0
_FBC_FLOOR = 30.0
_FBC_H = _FBC_CROWN + _FBC_FREEBOARD + _FBC_CONE
_FBC_GRID_Y = _FBC_CROWN + _FBC_FREEBOARD

_FBC_OUTLINE = (
    f'<path d="M 0 {_FBC_CROWN:g} '
    f'A {_FBC_W / 2:g} {_FBC_CROWN:g} 0 0 1 {_FBC_W:g} {_FBC_CROWN:g} '
    f'L {_FBC_W:g} {_FBC_GRID_Y:g} '
    f'L {(_FBC_W + _FBC_FLOOR) / 2:g} {_FBC_H:g} '
    f'L {(_FBC_W - _FBC_FLOOR) / 2:g} {_FBC_H:g} '
    f'L 0 {_FBC_GRID_Y:g} Z" {_OUTLINE}/>'
)
_FBC_GRID = (
    f'<line x1="0" y1="{_FBC_GRID_Y:g}" x2="{_FBC_W:g}" y2="{_FBC_GRID_Y:g}" '
    f'{_DETAIL} {_SCREEN_DASH}/>'
)

# Feed high on one wall and product over a weir low on the other, both
# above the grid; offgas off the crown; fuel into the bed; air into the
# windbox.
_FBC_PORTS = {
    "feed": (0.0, 40.0),
    "product": (_FBC_W, 100.0),
    "offgas": (_FBC_W / 2, 0.0),
    "fuel": (0.0, 96.0),
    "air": (_FBC_W / 2, _FBC_H),
}

# Shaft kiln: charging mouth, shaft and discharge cone in a 70 x 160 box,
# narrower than the 80-wide bodies. The 20-deep cones leave 120 of
# straight wall so it reads as a shaft. The two zone lines bound the
# calcining zone, where burners and cooling air enter.
_SHAFT_W, _SHAFT_H = 70.0, 160.0
_SHAFT_CONE = 20.0
_SHAFT_MOUTH = 40.0
_SHAFT_ZONE_TOP, _SHAFT_ZONE_BOT = 68.0, 104.0

_SHAFT_OUTLINE = (
    f'<path d="M {(_SHAFT_W - _SHAFT_MOUTH) / 2:g} 0 L 0 {_SHAFT_CONE:g} '
    f'L 0 {_SHAFT_H - _SHAFT_CONE:g} '
    f'L {(_SHAFT_W - _SHAFT_MOUTH) / 2:g} {_SHAFT_H:g} '
    f'L {(_SHAFT_W + _SHAFT_MOUTH) / 2:g} {_SHAFT_H:g} '
    f'L {_SHAFT_W:g} {_SHAFT_H - _SHAFT_CONE:g} '
    f'L {_SHAFT_W:g} {_SHAFT_CONE:g} '
    f'L {(_SHAFT_W + _SHAFT_MOUTH) / 2:g} 0 Z" {_OUTLINE}/>'
)
_SHAFT_ZONES = (
    f'<path d="M 0 {_SHAFT_ZONE_TOP:g} L {_SHAFT_W:g} {_SHAFT_ZONE_TOP:g} '
    f'M 0 {_SHAFT_ZONE_BOT:g} L {_SHAFT_W:g} {_SHAFT_ZONE_BOT:g}" {_DETAIL}/>'
)

# Charged over the mouth and discharged from the cone; offgas above the
# calcining zone, fuel at its top and cooling air below it,
# counter-current to the burden.
_SHAFT_PORTS = {
    "feed": (_SHAFT_W / 2, 0.0),
    "product": (_SHAFT_W / 2, _SHAFT_H),
    "offgas": (0.0, 36.0),
    "fuel": (_SHAFT_W, _SHAFT_ZONE_TOP + 12.0),
    "air": (0.0, _SHAFT_ZONE_BOT + 14.0),
}


class SymbolRegistry:
    """Catalogue of symbols keyed by ``(kind, variant)``, and ISO parts.

    Holds whole drawings (:meth:`register`), their normally closed
    states (:meth:`register_closed`) and the ISO 10628-2 group 26-29
    supplementary symbols (:meth:`register_part`). :meth:`for_unit`
    resolves the drawing for a unit, including derived drawings built
    from the unit (built to size, composed, darkened, closed or turned end
    for end), each cached because port resolution asks on every call.
    """

    def __init__(self):
        """Create the registry and register the default symbols."""
        self._symbols: dict[tuple[str, str], Symbol] = {}
        # Caches of derived symbols: port resolution asks for a unit's
        # symbol on every call, so each is built once and shared.
        self._darkened: dict[tuple[str, str], Symbol] = {}
        # Closed-state drawings: one (kind, variant) with two states, chosen
        # by the unit's normal_position, not a second variant.
        self._closed: dict[tuple[str, str], Symbol] = {}
        # Fittings turned end for end (expanders).
        self._expanders: dict[tuple[str, str], Symbol] = {}
        # ISO 10628-2 group 26-29 supplementary symbols, keyed by
        # (group, name).
        self._parts: dict[tuple[int, str], OverlayPart] = {}
        # Bodies with parts, per (kind, variant, overlays); a tray column
        # has dozens of parts, so rebuilding per lookup would be costly.
        self._composed: dict[tuple, Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol, variant: str = "default") -> None:
        """Register a drawing for ``(kind, variant)``, replacing any earlier one.

        Derived drawings cached for that key (darkened, closed, expander,
        composed) are dropped. Re-registering drops the closed-state
        pairing, so call :meth:`register_closed` afterwards.

        Parameters
        ----------
        kind : str
            Unit kind.
        template : Symbol
            Drawing.
        variant : str, default="default"
            Variant name.
        """
        self._symbols[(kind, variant)] = template
        self._darkened.pop((kind, variant), None)
        self._closed.pop((kind, variant), None)
        self._expanders.pop((kind, variant), None)
        for key in [k for k in self._composed if k[:2] == (kind, variant)]:
            del self._composed[key]

    def register_part(self, part: OverlayPart) -> None:
        """Register one ISO 10628-2 group 26-29 supplementary symbol.

        Keyed by ``(group, name)``: a name is unique only within its ISO
        subject group. A part should carry the registration number of the
        composition the standard draws (see :class:`IsoPart`).

        Parameters
        ----------
        part : OverlayPart
            Part to register.
        """
        self._parts[part.key()] = part
        # Drop every composition; any may use this part.
        self._composed.clear()

    def part(self, group: int, name: str) -> OverlayPart:
        """Return the supplementary symbol registered as ``(group, name)``.

        Parameters
        ----------
        group : int
            ISO 10628-2 subject group (26-29).
        name : str
            Part name.

        Returns
        -------
        OverlayPart
            Registered part.

        Raises
        ------
        ValueError
            If no such part is registered; the message suggests a close
            name.
        """
        if (group, name) in self._parts:
            return self._parts[(group, name)]
        known = self.part_names(group)
        close = get_close_matches(name, known, n=1, cutoff=0.6)
        suggestion = f" (did you mean {close[0]!r}?)" if close else ""
        raise ValueError(
            f"ISO 10628-2 group {group} has no part {name!r}{suggestion}; registered "
            f"group {group} parts: {', '.join(known) or '(none)'}"
        )

    def part_names(self, group: int) -> list[str]:
        """Return the part names registered in one ISO subject group, sorted.

        Parameters
        ----------
        group : int
            ISO 10628-2 subject group.

        Returns
        -------
        list[str]
            Part names.
        """
        return sorted(name for (g, name) in self._parts if g == group)

    def parts(self) -> list[OverlayPart]:
        """Return every registered supplementary symbol, by group then name.

        Returns
        -------
        list[OverlayPart]
            Registered parts.
        """
        return [self._parts[key] for key in sorted(self._parts)]

    def composed(self, kind: str, variant: str = "default",
                 overlays: "tuple[Overlay, ...]" = ()) -> Symbol:
        """Return ``(kind, variant)`` with ``overlays`` drawn on it, cached.

        The body comes from :meth:`get`, each part from :meth:`part`, and
        :func:`compose` paints them. With no overlays the body is returned
        unchanged and nothing is cached.

        Parameters
        ----------
        kind : str
            Unit kind.
        variant : str, default="default"
            Variant name.
        overlays : tuple[Overlay, ...], optional
            Parts to draw on the body.

        Returns
        -------
        Symbol
            Composed drawing.

        Raises
        ------
        ValueError
            If the variant or a part is not registered.
        """
        if not overlays:
            return self.get(kind, variant)
        key = (kind, variant, tuple(overlays))
        if key not in self._composed:
            self._composed[key] = compose(
                self.get(kind, variant),
                [(overlay, self.part(overlay.group, overlay.name))
                 for overlay in overlays],
            )
        return self._composed[key]

    def register_closed(self, kind: str, template: Symbol, variant: str = "default") -> None:
        """Register the normally closed drawing of ``(kind, variant)``.

        For a device whose closed state is a shape of its own rather than
        a fill of the open one, such as a spectacle blind. It is a state,
        not a second variant. Register the open drawing first, since
        re-registering it drops this pairing.

        Parameters
        ----------
        kind : str
            Unit kind.
        template : Symbol
            Closed-state drawing.
        variant : str, default="default"
            Variant name.

        Raises
        ------
        ValueError
            If ``(kind, variant)`` has no open drawing.
        """
        if (kind, variant) not in self._symbols:
            raise ValueError(
                f"{kind}/{variant} has no open drawing to be the closed state of; "
                f"register() it first"
            )
        self._closed[(kind, variant)] = template

    def closed_symbol(self, kind: str, variant: str = "default") -> Symbol | None:
        """Return the normally closed drawing of ``(kind, variant)``.

        Parameters
        ----------
        kind : str
            Unit kind.
        variant : str, default="default"
            Variant name.

        Returns
        -------
        Symbol or None
            Closed-state drawing, or ``None`` if there is none.
        """
        return self._closed.get((kind, variant))

    def closed_variants(self, kind: str) -> list[str]:
        """Return the variants of a kind that have a closed drawing, sorted.

        Parameters
        ----------
        kind : str
            Unit kind.

        Returns
        -------
        list[str]
            Variant names.
        """
        return sorted(variant for (k, variant) in self._closed if k == kind)

    def for_unit(self, unit) -> Symbol:
        """Return the symbol to draw a unit with.

        Starts from :meth:`get`, which also rejects an unregistered
        variant, then derives from the unit where needed, in order:

        1. a symbol built to the unit's size (conveyors, blocks, vessels);
        2. the body with the unit's supplementary parts
           (:meth:`composed`);
        3. a normally closed device's own closed drawing, or its darkened
           body (:func:`closed_marking`);
        4. a reducer with ``large_end="outlet"`` turned end for end
           (:func:`expander`).

        Composition and the closed or reversed forms never meet: valves
        and fittings carry no parts.

        Parameters
        ----------
        unit : Unit
            Unit to draw.

        Returns
        -------
        Symbol
            Drawing for the unit.

        Raises
        ------
        ValueError
            If the unit's variant is not registered for its kind.
        """
        variant = getattr(unit, "variant", "default")
        sym = self.get(unit.kind, variant)
        build = _built_to_size(unit.kind, variant)
        if build is not None:
            return build(unit)
        overlays = tuple(getattr(unit, "overlays", ()) or ())
        if overlays:
            return self.composed(unit.kind, variant, overlays)
        mark = closed_marking(unit, self)
        if mark == "stencil":
            return self._closed[(unit.kind, variant)]
        if mark == "fill":
            key = (unit.kind, variant)
            if key not in self._darkened:
                self._darkened[key] = darkened(sym)
            return self._darkened[key]
        # An expansion is the vendored reduction piped the other way round.
        if getattr(unit, "large_end", "inlet") == "outlet":
            key = (unit.kind, variant)
            if key not in self._expanders:
                self._expanders[key] = expander(sym)
            return self._expanders[key]
        return sym

    def variants(self, kind: str) -> list[str]:
        """Return the variants registered for a kind, ``default`` first.

        Parameters
        ----------
        kind : str
            Unit kind.

        Returns
        -------
        list[str]
            Variant names, ``default`` then sorted.
        """
        names = [variant for (k, variant) in self._symbols if k == kind]
        return sorted(names, key=lambda name: (name != "default", name))

    def get(self, kind: str, variant: str = "default") -> Symbol:
        """Return the registered drawing for ``(kind, variant)``.

        A kind with no drawings at all, such as a custom Unit subclass,
        gets a blank 60 x 60 box.

        Parameters
        ----------
        kind : str
            Unit kind.
        variant : str, default="default"
            Variant name.

        Returns
        -------
        Symbol
            Registered drawing, or the generic box for an unknown kind.

        Raises
        ------
        ValueError
            If the kind has drawings but none under ``variant``; the
            message suggests a close name.
        """
        if (kind, variant) in self._symbols:
            return self._symbols[(kind, variant)]
        known = self.variants(kind)
        if not known:
            # No catalogue to check the variant against.
            return self._generic_symbol()
        # An unknown variant is a typo; drawing the default instead would
        # hide it.
        close = get_close_matches(variant, known, n=1, cutoff=0.6)
        suggestion = f" (did you mean {close[0]!r}?)" if close else ""
        raise ValueError(
            f"{kind} has no variant {variant!r}{suggestion}; "
            f"registered {kind} variants: {', '.join(known)}"
        )

    def _generic_symbol(self) -> Symbol:
        """Return the blank 60 x 60 box drawn for an unregistered kind."""
        svg = (
            '<g id="sym_generic">'
            '<rect x="0" y="0" width="60" height="60" fill="none" stroke="black" stroke-width="2" />'
            '</g>'
        )
        return Symbol(svg=svg, width=60, height=60)

    def _register_defaults(self):
        """Register the hand-drawn fallbacks, the vendored set and ISO families.

        The vendored draw.io symbols are registered after the fallbacks and
        replace them for shared kinds; the ISO parts and generated families
        follow.
        """
        # Feed and Product are drawn by the renderer; these are fallbacks.
        self.register("feed", Symbol(
            svg='<g id="sym_feed"><polygon points="0,10 35,10 50,25 35,40 0,40" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={"outlet": (50.0, 25.0)}
        ))
        self.register("product", Symbol(
            svg='<g id="sym_product"><polygon points="0,10 35,10 50,25 35,40 0,40 10,25" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50, height=50,
            ports={"inlet": (0.0, 25.0)}
        ))

        # The equipment symbols below are fallbacks that the vendored
        # registry replaces, except the Mixer, Splitter and pipe tee, which
        # have no stencil.

        # Centrifugal Pump: circle with discharge nozzle at top, suction
        # on left, baseplate line
        self.register("pump", Symbol(
            svg=(
                '<g id="sym_pump">'
                '<circle cx="30" cy="30" r="22" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="8" y1="52" x2="52" y2="52" stroke="black" stroke-width="2"/>'
                '<line x1="30" y1="8" x2="30" y2="0" stroke="black" stroke-width="2"/>'
                '<line x1="0" y1="30" x2="8" y2="30" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=60.0, height=55.0,
            ports={'suction': (0.0, 30.0), 'discharge': (30.0, 0.0)}
        ))

        # Compressor: circle with triangle indicator
        self.register("compressor", Symbol(
            svg=(
                '<g id="sym_compressor">'
                '<circle cx="40" cy="40" r="30" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="25,55 55,55 40,25" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=80.0,
            ports={'suction': (10.0, 40.0), 'discharge': (40.0, 10.0)}
        ))

        # Separator: vertical vessel with elliptical heads
        self.register("separator", Symbol(
            svg=(
                '<g id="sym_separator">'
                '<rect x="10" y="25" width="60" height="130" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="155" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=170.0,
            ports={'liquid': (40.0, 167.0), 'feed': (10.0, 90.0), 'vapor': (40.0, 13.0)}
        ))

        # Reactor: vertical vessel with internal coil indicator
        self.register("reactor", Symbol(
            svg=(
                '<g id="sym_reactor">'
                '<rect x="10" y="25" width="60" height="130" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="25" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="155" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M25,70 Q40,55 55,70 Q40,85 25,70" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=80.0, height=170.0,
            ports={'duty': (70.0, 90.0), 'outlet': (40.0, 167.0), 'feed': (40.0, 13.0)}
        ))

        # Shell & Tube Heat Exchanger Horizontal cylinder with two
        # tube-side nozzles on ends and two shell-side nozzles on
        # top/bottom
        self.register("hex", Symbol(
            svg=(
                '<g id="sym_hex">'
                '<rect x="15" y="10" width="70" height="40" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="15" cy="30" rx="8" ry="20" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="85" cy="30" rx="8" ry="20" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="15" y1="30" x2="85" y2="30" stroke="black" stroke-width="1" stroke-dasharray="4,3"/>'
                '</g>'
            ),
            width=100.0, height=60.0,
            ports={
                'tube_in': (0.0, 30.0),
                'tube_out': (100.0, 30.0),
                'shell_in': (50.0, 10.0),
                'shell_out': (50.0, 50.0),
            }
        ))
        

        # Mixer: triangle pointing right; inlets on the left face, outlet
        # at the right vertex.
        self.register("mixer", Symbol(
            svg='<g id="sym_mixer"><polygon points="0,0 50,25 0,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'outlet': (50.0, 25.0)},
            port_series=(PortSeries("in_", "W"),),
        ))

        # Valve: a bowtie, two opposing triangles, with a stem bar
        self.register("valve", Symbol(
            svg=(
                '<g id="sym_valve">'
                '<polygon points="0,0 20,15 0,30" fill="none" stroke="black" stroke-width="2"/>'
                '<polygon points="40,0 20,15 40,30" fill="none" stroke="black" stroke-width="2"/>'
                '<line x1="20" y1="0" x2="20" y2="15" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=40.0, height=30.0,
            ports={'inlet': (0.0, 15.0), 'outlet': (40.0, 15.0)},
            # Matches the vendored valve this fallback stands in for.
            trim=True,
        ))

        # Vessel: vertical drum with dished heads
        self.register("vessel", Symbol(
            svg=(
                '<g id="sym_vessel">'
                '<rect x="10" y="20" width="60" height="80" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="20" rx="30" ry="10" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="100" rx="30" ry="10" fill="none" stroke="black" stroke-width="2"/>'
                '</g>'
            ),
            width=80.0, height=115.0,
            ports={'inlet': (10.0, 55.0), 'outlet': (70.0, 55.0)}
        ))

        # Heater: circle with an internal zigzag (electric heater
        # symbol)
        self.register("heater", Symbol(
            svg=(
                '<g id="sym_heater">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M15,30 L20,20 L25,40 L30,20 L35,40 L40,20 L45,30" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={'outlet': (55.0, 30.0), 'utility_in': (30.0, 55.0), 'inlet': (5.0, 30.0)}
        ))

        # Cooler: circle with internal zigzag plus cooling arrow
        self.register("cooler", Symbol(
            svg=(
                '<g id="sym_cooler">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M15,30 L20,20 L25,40 L30,20 L35,40 L40,20 L45,30" fill="none" stroke="black" stroke-width="1.5"/>'
                '<path d="M48,12 L55,5" stroke="black" stroke-width="1.5"/>'
                '<path d="M52,8 L55,5 L51,5" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={'outlet': (55.0, 30.0), 'inlet': (5.0, 30.0), 'utility_out': (30.0, 5.0)}
        ))

        # Distillation Column: tall vertical vessel with internal trays
        self.register("column", Symbol(
            svg=(
                '<g id="sym_column">'
                '<rect x="10" y="20" width="60" height="170" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="20" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                '<ellipse cx="40" cy="190" rx="30" ry="12" fill="none" stroke="black" stroke-width="2"/>'
                # Internal tray lines
                '<line x1="15" y1="65" x2="65" y2="65" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="100" x2="65" y2="100" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="135" x2="65" y2="135" stroke="black" stroke-width="1"/>'
                '<line x1="15" y1="170" x2="65" y2="170" stroke="black" stroke-width="1"/>'
                '</g>'
            ),
            width=80.0, height=205.0,
            ports={
                'reboiler_duty': (70.0, 105.0),
                'bottoms': (40.0, 202.0),
                'feed': (10.0, 105.0),
                'distillate': (40.0, 8.0),
            }
        ))
        

        # Belt conveyor at its default length; other lengths are built by
        # for_unit() (conveyor_symbol).
        self.register("conveyor", conveyor_symbol())
        # Screw conveyor, ISO item 18.5 X8063, the same way.
        self.register("conveyor", screw_conveyor_symbol(), "screw")

        # Bucket elevators, ISO items 18.7 X8065 and 18.8 X8066, at a
        # fixed size: a flowsheet does not state the lift.
        self.register("elevator", _BUCKET_ELEVATOR)
        self.register("elevator", _Z_ELEVATOR, "z_form")

        # Pipe tee: three lines meeting, drawn as pipe with no junction
        # mark, as on reference sheet P&ID-301. The run crosses at
        # mid-height and the branch drops to the south face; the box is
        # just large enough for the stub to read. An original primitive:
        # the draw.io set has no bare junction (NOTICE section 1).
        self.register("tee", Symbol(
            svg='<g id="sym_tee">'
                '<path d="M 0 6 L 12 6 M 6 6 L 6 12" fill="none" stroke="black" '
                'stroke-width="2"/>'
                '</g>',
            width=12.0, height=12.0,
            ports={"inlet": (0.0, 6.0), "outlet": (12.0, 6.0), "branch": (6.0, 12.0)},
            # No tag, so reserve no label side.
            label_pos="center",
            # No arrowhead: the run divides and carries on.
            bare_run=True,
        ))

        # Block flow diagram box, registered with one inlet west and one
        # outlet east; other blocks are built by for_unit()
        # (block_symbol).
        self.register("block", block_symbol((("in_1", "W"), ("out_1", "E"))))

        # Splitter: triangle pointing left; inlet at the left vertex,
        # outlets on the right face.
        self.register("splitter", Symbol(
            svg='<g id="sym_splitter"><polygon points="0,25 50,0 50,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'inlet': (0.0, 25.0)},
            port_series=(PortSeries("out_", "E"),),
        ))

        # ISA-5.1 instrument balloons; the renderer letters the tag. Ports:
        # pv (process, bottom), sig_in and sig_out. Variants: default
        # (field), panel (one bar), aux (two bars), shared (circle in
        # square with a bar), computer (hexagon), sis/logic (diamond in
        # square) and interlock (diamond). Every port offers all four faces,
        # one unit clear of the r=21 circle.
        _inst_faces = {"N": (22.0, 0.0), "S": (22.0, 44.0),
                       "W": (0.0, 22.0), "E": (44.0, 22.0)}
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        # The face menus overlap by design (faceless_ports).
        _inst_menu = {name: dict(_inst_faces) for name in _inst_ports}
        _inst_faceless = frozenset(_inst_ports)
        # Not stretchable: an oval balloon or squashed hexagon would read
        # as a different ISA-5.1 symbol, so each keeps its proportions.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False,
            # A PCE symbol, ISO 10628-1 §5.3.1 c). See :attr:`Symbol.trim`.
            trim=True))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_panel"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="22" x2="43" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False,
            trim=True), "panel")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_aux"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="19" x2="43" y2="19" stroke="black" stroke-width="1.5"/><line x1="1" y1="25" x2="43" y2="25" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False,
            trim=True), "aux")
        # A shared display is in the central control system, so it carries
        # one bar (ISO 15519-2 Table 1). The bar spans the circle through
        # its centre, with letters above and number below (ISO 15519-2
        # 5.1.2), as on reference sheet P&ID-301. Drawn at 1.5, this
        # package's location-bar weight, like panel and aux.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/><line x1="2" y1="22" x2="42" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False,
            trim=True), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # The hexagon's bottom is at y=41, so pv moves up to keep a
            # 1-unit stub.
            width=44.0, height=44.0, label_pos="center", stretchable=False,
            faceless_ports=_inst_faceless,
            ports={**_inst_ports, "pv": (22.0, 42.0)},
            # Flat top and bottom at y=3 and y=41 need their own N and S
            # stubs.
            port_faces={n: {**_inst_faces, "N": (22.0, 2.0), "S": (22.0, 42.0)}
                        for n in _inst_ports},
            trim=True), "computer")
        # Trip and logic symbols (ANSI/ISA-5.1-2009):
        #
        #   Table 5.1.2 items 3-5  a plain diamond           interlock
        #   Table 5.1.1 column B   a diamond inside a square sis/logic
        #
        # The diamond in a square is what reference sheet P&ID-301 draws
        # for a trip. ``logic`` is a second package name for ``sis``, used
        # by existing sheets and Instrument's repeat rule. Both are drawn in
        # a 40 box: an inscribed diamond needs the square grown by root two
        # to hold a two-figure number. Ports sit at the side midpoints,
        # which are the diamond's vertices.
        _logic_ports = {'pv': (20.0, 39.0), 'sig_in': (1.0, 20.0), 'sig_out': (39.0, 20.0)}
        # One Symbol under two names, so they cannot drift apart.
        _sis = Symbol(
            svg='<g id="sym_instrument_sis">'
                '<rect x="1" y="1" width="38" height="38" fill="white" stroke="black" stroke-width="2"/>'
                '<polygon points="20,1 39,20 20,39 1,20" fill="none" stroke="black" stroke-width="2"/>'
                '</g>',
            # Not stretchable: the vertices must stay on the ports.
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports, trim=True)
        self.register("instrument", _sis, "sis")
        self.register("instrument", _sis, "logic")
        # A white fill keeps lines from striking through the number.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_interlock">'
                '<polygon points="20,1 39,20 20,39 1,20" fill="white" stroke="black" stroke-width="2"/>'
                '</g>',
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports, trim=True),
            "interlock")

        # Tubular reactor (PFR). ISO 10628-2 has no reactor symbol, so it is
        # built like item 3.7 (reg 2514, coil-tube heat exchanger): a 12 M x
        # 4 M rectangular shell with a serpentine tube. Straight walls let
        # several feeds sit on the west face. The tube pass is drawn at
        # ``iso_parts.PART_STROKE`` (ISO 10628-1:2014 5.3.1 c)).
        self.register("reactor", Symbol(
            svg='<g id="sym_reactor_tubular">'
                '<rect x="0" y="0" width="120" height="40" fill="white" '
                'stroke="#111" stroke-width="2"/>'
                '<path d="M 15 10 L 105 10 A 5 5 0 0 1 105 20 L 15 20 '
                'A 5 5 0 0 0 15 30 L 105 30" fill="none" stroke="#111" '
                'stroke-width="1"/></g>',
            width=120.0, height=40.0,
            ports={"outlet": (120.0, 20.0), "duty": (60.0, 0.0)},
            port_series=(PortSeries(prefix="feed_", face="W", pitch=10.0,
                                    extent=0.5, at=20.0, singular="feed"),),
        ), "tubular")

        # ISO 10628-2 Table 2 group 4: boiler, stack and flare, each its own
        # outline since groups 26-29 have nothing to compose them from.
        # Item 4.3 (2533, furnace) is not registered: furnace/default is
        # the vendored fired-heater drawing, which is not that row, and
        # replacing it would change every existing sheet.

        # Item 4.1, 2532, boiler with dome: a 10 M square shell with a 5 M
        # semicircular dome on its crown. Feedwater a quarter of the way
        # down the west wall; steam at the dome's apex (connection ticks as
        # in ``iso_parts``).
        self.register("boiler", Symbol(
            svg='<g id="sym_boiler"><path d="M 25 25 A 25 25 0 0 1 75 25 '
                'L 100 25 L 100 125 L 0 125 L 0 25 Z" '
                'fill="white" stroke="#111" stroke-width="2"/></g>',
            width=100.0, height=125.0,
            ports={"feedwater": (0.0, 50.0), "steam": (50.0, 0.0)},
            # The dome must be the high point (ISO 15519-1 11.4.2).
            gravity_fixed=True,
            iso_reg="2532",
        ), "default")

        # Item 4.7, 2041, stack: a shaft tapering from a 2 M cap to a 6 M
        # foundation flange drawn as one stroke beneath it, as Table 2
        # draws it (open strokes, not a closed outline). One inlet low on
        # the west wall (:data:`_STACK_INLET_Y`).
        self.register("stack", Symbol(
            svg='<g id="sym_stack"><path d="M 20 0 L 40 0 M 20 0 L 10 100 '
                'M 40 0 L 50 100 M 0 100 L 60 100" '
                'fill="none" stroke="#111" stroke-width="2"/></g>',
            width=60.0, height=100.0,
            ports={"inlet": (_STACK_INLET_X, _STACK_INLET_Y)},
            # A stack exhausts upward (ISO 15519-1 11.4.2).
            gravity_fixed=True,
            iso_reg="2041",
        ), "default")

        # Item 4.8, 2591, gas flare: the stack's construction with straight
        # walls and a 2 M x 4 M vesica flame on top, its arcs struck from
        # centres 1.5 M either side of the shaft centreline.
        self.register("flare", Symbol(
            svg='<g id="sym_flare">'
                '<path d="M 30 40 A 25 25 0 0 1 30 0 A 25 25 0 0 1 30 40 Z" '
                'fill="none" stroke="#111" stroke-width="2"/>'
                '<path d="M 20 40 L 40 40 M 20 40 L 20 120 M 40 40 L 40 120 '
                'M 0 120 L 60 120" fill="none" stroke="#111" stroke-width="2"/>'
                '</g>',
            width=60.0, height=120.0,
            # Inlet on the west wall at x 2 M, two modules up rather than
            # ISO's one so it reads as on the wall (see _STACK_INLET_Y).
            ports={"inlet": (20.0, 90.0)},
            # The flame burns upward.
            gravity_fixed=True,
            iso_reg="2591",
        ), "default")

        # Vendored draw.io symbols (Apache-2.0), registered after the
        # fallbacks so they replace them and add variants.
        from pandid.render._vendored_symbols import register_vendored
        register_vendored(self)

        # ISO 10628-2 group 26-29 parts, in their own namespace and added
        # after the whole symbols they overlay.
        from pandid.render.iso_parts import register_parts
        register_parts(self)
        self._register_composed()
        self._register_crushing_machines()
        self._register_centrifuges()
        self._register_driers()
        self._register_cooling_towers()
        self._register_feeders()
        self._register_mixers()
        self._register_screens()
        self._register_evaporators()
        self._register_kilns()
        self._register_steam_trap()

    def _register_steam_trap(self):
        """Register the steam trap, ISO 10628-2 Table 2 item 24.15 (2181).

        A :class:`~pandid.units.Fitting` variant, like the other in-line
        group 24 items. Hand-drawn because the vendored "Steam Trap"
        stencil is empty (see ``scripts/vendor_symbols.py``).
        """
        self.register("fitting", _STEAM_TRAP, "steam_trap")

    def _register_composed(self):
        """Register the three group-8 drawings ISO composes and numbers.

        Author-configured compositions (agitators, trays) are built per
        unit; these are fixed compositions the standard tabulates, so they
        are registered. Each is the separating vessel
        (:data:`_SEPARATING_VESSEL`) with one group-29 characteristic:

        =====  ======  ==============================================
        item   reg     body + part
        =====  ======  ==============================================
        8.3    X8031   separating vessel + 29.1 C2028 gravity
        8.6    X8125   separating vessel + 29.2 C2030 electrostatic
        8.8    X8126   separating vessel + 29.3 C2031 electromagnetic
        =====  ======  ==============================================

        The other group-8 drawings stay vendored whole, because group 29
        has no mark to build them from: the cyclone (8.10 X2618, named in
        ISO 15519-1 11.4.2 and ISO 14617-1 4.5), the baffle (8.2 X2616),
        the spray (8.5 X2621) and the permanent magnet (8.9 X8127). The wet
        scrubber (8.4) could now be composed from 29.10 but stays vendored,
        since composing it would change an existing drawing and its ports.

        These three lose their draw.io stencils: the exporter draws the
        body as a rectangle with the mark as a child cell, because
        :func:`compose` refuses a ``drawio_shape`` on a composed symbol.
        """
        from pandid.render.iso_parts import characteristic_overlays

        for name, reg in (("gravity", "X8031"), ("electrostatic", "X8125"),
                          ("electromagnetic", "X8126")):
            # Pass self: default_registry is still being built.
            overlays = characteristic_overlays(name, registry=self)
            self.register("separator", compose(
                _SEPARATING_VESSEL,
                [(o, self.part(o.group, o.name)) for o in overlays],
                iso_reg=reg,
            ), name)

    def _register_crushing_machines(self):
        """Register ISO 10628-2 Table 2 group 11, all twelve rows.

        One trapezoid (:data:`_CRUSHER_OUTLINE`) in two layers:

        1. The body mark: the crusher's two verticals (11.2 X8085), the
           mill's two chords (11.8 X8086) or none (11.1 X8084, a machine
           not yet chosen, for an early PFD). Group 29 has neither mark,
           so the three bodies are whole drawings.
        2. A group-29 characteristic from :mod:`pandid.render.iso_parts`,
           centred on the body, on nine of the rows.

        Item 11.12 X8054 adds a 4 M drum around 29.14's arrows; see
        :data:`_VIBRATION_DRUM`.

        ==============  ======  =====================================
        item            reg     body + part
        ==============  ======  =====================================
        11.1            X8084   general machine, no mark
        11.2            X8085   crusher, no mark
        11.3            X8045   crusher + 29.7 C2034 hammer
        11.4            X8046   crusher + 29.8 C2035 impact
        11.5            X8047   crusher + 29.9 C2036 jaw
        11.6            X8048   crusher + 29.11 C2037 roller
        11.7            X8049   crusher + 29.12 C2038 cone
        11.8            X8086   mill, no mark
        11.9            X8050   mill + 29.7 C2034 hammer
        11.10           X8051   mill + 29.8 C2035 impact
        11.11           X8053   mill + 29.11 C2037 roller
        11.12           X8054   mill and drum + 29.14 3831 vibration
        ==============  ======  =====================================
        """
        from pandid.render.iso_parts import crushing_overlays

        general = _crushing_machine("crushing_machine", "X8084")
        crusher = _crushing_machine("crusher", "X8085", _CRUSHER_JAWS)
        mill = _crushing_machine("mill", "X8086", _MILL_CHAMFERS)
        # Unregistered drum body; X8054 numbers the composition.
        drum = _crushing_machine("mill_vibration", "", _MILL_CHAMFERS, _VIBRATION_DRUM)
        self.register("crushing_machine", general)
        self.register("crusher", crusher)
        self.register("mill", mill)

        for kind, body, marks in (
            ("crusher", crusher, (("hammer", "X8045"), ("impact", "X8046"),
                                  ("jaw", "X8047"), ("roller", "X8048"),
                                  ("cone", "X8049"))),
            ("mill", mill, (("hammer", "X8050"), ("impact", "X8051"),
                            ("roller", "X8053"))),
            ("mill", drum, (("vibration", "X8054"),)),
        ):
            for name, reg in marks:
                # Pass self: default_registry is still being built.
                overlays = crushing_overlays(name, registry=self)
                self.register(kind, compose(
                    body,
                    [(o, self.part(o.group, o.name)) for o in overlays],
                    iso_reg=reg,
                ), name)

    def _register_centrifuges(self):
        """Register ISO 10628-2 Table 2 group 9, all eight rows: centrifuges.

        One 8 M x 8 M square (:func:`_centrifuge_outline`) with each row's
        mark drawn in; group 29 has none of these marks, so none is a part.

        ====  ======  ==================================================
        item  reg     descriptor
        ====  ======  ==================================================
        9.1   X2619   High speed centrifuge
        9.2   X2614   Centrifuge with perforated shell
        9.3   X8035   Centrifuge with solid shell
        9.4   X8036   Centrifuge, separator disc-type
        9.5   X8037   Centrifuge, screw-type with perforated shell
        9.6   X8082   Decanter, centrifuge, screw type with solid shell
        9.7   X8038   Centrifuge, pusher type
        9.8   X8039   Centrifuge, skimmer type
        ====  ======  ==================================================

        All eight have the same ``feed``, ``overflow`` and ``underflow``
        ports, at :data:`_CENTRIFUGE_TOP_PORTS` (9.1-9.4) or
        :data:`_CENTRIFUGE_SIDE_PORTS` (9.5-9.8; 9.6 uses its drawn side
        pipe). The decanter (9.6) is also registered as ``default``; see
        :class:`~pandid.units.Centrifuge`.
        """
        top, side = _CENTRIFUGE_TOP_PORTS, _CENTRIFUGE_SIDE_PORTS
        sq, margin = _CENTRIFUGE_SQ, _CENTRIFUGE_MARGIN

        rows = (
            ("high_speed", "X2619", sq, sq + margin, 0.0, _CENTRIFUGE_ROTOR, top),
            ("perforated_shell", "X2614", sq, sq + margin, 0.0,
             _CENTRIFUGE_BASKET_DASHED, top),
            ("solid_shell", "X8035", sq, sq + margin, 0.0,
             _CENTRIFUGE_BASKET_SOLID, top),
            ("disc", "X8036", sq, sq + margin, 0.0, _CENTRIFUGE_DISC_STACK, top),
            ("screw_perforated", "X8037", sq + margin, sq, margin,
             _CENTRIFUGE_SCREW_PERFORATED, side),
            ("decanter", "X8082", sq + margin, sq, margin,
             _CENTRIFUGE_SCREW_SOLID, side),
            ("pusher", "X8038", sq + margin, sq, margin, _CENTRIFUGE_PUSHER, side),
            ("skimmer", "X8039", sq + margin, sq, margin, _CENTRIFUGE_SKIMMER, side),
        )
        by_name: dict[str, Symbol] = {}
        for name, reg, width, height, ox, detail, ports in rows:
            sym = _centrifuge(name, reg, width, height, ox, detail, ports)
            self.register("centrifuge", sym, name)
            by_name[name] = sym
        # The default is the decanter; look it up so a missing row fails.
        self.register("centrifuge", by_name["decanter"])

    def _register_driers(self):
        """Register four ISO 10628-2 Table 2 group-10 dryer rows.

        One shared outline (:data:`_DRIER_OUTLINE`) and four bodies; group
        10 has no supplementary-symbol group.

        ========  ======  ================================================
        item      reg     descriptor
        ========  ======  ================================================
        10.1      C0046   Drier (general)
        10.2      X8083   Drying oven, drying chamber, shelf drier
        10.3      X8040   Turbo drier, disc drier, moving shelf drier
        10.6      X8043   Belt drier, roller-conveyor type drier
        ========  ======  ================================================

        Rows 10.4 (X8041, fluidised bed), 10.5 (X8042, spray) and 10.7
        (X8044, rotary drum) are left to the vendored ``fluidized_bed``,
        ``spray`` and ``default`` drawings, which differ slightly from these
        rows; replacing them would change existing sheets.
        """
        self.register("dryer", _drier("general", "C0046"), "general")
        # Only the shelf dryer is gravity-fixed: turned over, its trays fall
        # (ISO 15519-1 11.4.2).
        self.register(
            "dryer", _drier("shelf", "X8083", _DRIER_SHELVES, gravity_fixed=True),
            "shelf")
        self.register(
            "dryer", _drier("turbo", "X8040", _DRIER_TURBO), "turbo")
        self.register(
            "dryer", _drier("belt", "X8043", _DRIER_BELT), "belt")

    def _register_cooling_towers(self):
        """Register ISO 10628-2 Table 2 group 5 except the spray cooler.

        One outline (:data:`_TOWER_OUTLINE`) with a fill mark (dry, wet or
        both) and a draught mark (fan low for forced, high for induced, none
        for natural), in the eight combinations Table 2 tabulates:

        =================  ======  =========================================
        item               reg     fill + draught
        =================  ======  =========================================
        5.1                2521    none (general)
        5.2                X8109   dry, natural
        5.3                X8110   dry, forced
        5.4                X8111   dry, induced
        5.5                X8112   wet, natural
        5.6                X8113   wet, forced
        5.7                X8114   wet, induced
        5.8                X8115   wet-dry, natural
        =================  ======  =========================================

        Table 2 has the wet-dry hybrid at natural draught only. Item 5.9
        (X2504, spray cooler) is a different body with three connections
        and would need its own class. The vendored ``default``,
        ``induced_draft`` and ``forced_draft`` drawings are a different
        outline and are left as they are.
        """
        self.register("cooling_tower", Symbol(
            svg=f'<g id="sym_cooling_tower_general">{_TOWER_OUTLINE}</g>',
            width=_TOWER_W, height=_TOWER_H, ports=dict(_TOWER_PORTS),
            gravity_fixed=True, iso_reg="2521",
        ), "general")

        for name, fill, fan, reg in (
            ("dry_natural", _TOWER_DRY, "", "X8109"),
            ("dry_forced", _TOWER_DRY, _TOWER_FAN_FORCED, "X8110"),
            ("dry_induced", _TOWER_DRY, _TOWER_FAN_INDUCED, "X8111"),
            ("wet_natural", _TOWER_WET, "", "X8112"),
            ("wet_forced", _TOWER_WET, _TOWER_FAN_FORCED, "X8113"),
            ("wet_induced", _TOWER_WET, _TOWER_FAN_INDUCED, "X8114"),
            ("wet_dry_natural", _TOWER_DRY + _TOWER_WET, "", "X8115"),
        ):
            self.register("cooling_tower", Symbol(
                svg=f'<g id="sym_cooling_tower_{name}">{_TOWER_OUTLINE}'
                    f'{fill}{fan}</g>',
                width=_TOWER_W, height=_TOWER_H, ports=dict(_TOWER_PORTS),
                gravity_fixed=True, iso_reg=reg,
            ), name)

    def _register_feeders(self):
        """Register ISO 10628-2 Table 2 group 19, all five rows.

        19.1 and 19.2 are a 4 M circle with one mark each; 19.3 and 19.4
        are their own drawings. 19.5, a distribution fitting, is registered
        as its own kind. Group 19 has no parts.

        ====  ======  ==============================================
        item  reg     descriptor
        ====  ======  ==============================================
        19.1  C2056   Proportional feeder (general)
        19.2  X8067   Proportional feeder, rotary valve type
        19.3  C0074   Feeder, rotary table type
        19.4  C0035   Proportional feeder, metering type
        19.5  2037    Spray nozzle
        ====  ======  ==============================================

        :class:`~pandid.units.Feeder` is the class that draws the first
        four; :class:`~pandid.units.SprayNozzle` draws the fifth.
        """
        self.register("feeder", _feeder_circle("general", "C2056", _FEEDER_Z), "general")
        self.register(
            "feeder", _feeder_circle("rotary_valve", "X8067", _FEEDER_ROTOR_MARK),
            "rotary_valve")
        self.register("feeder", Symbol(
            svg=f'<g id="sym_feeder_rotary_table">{_FEEDER_TABLE}</g>',
            width=_FEEDER_TABLE_W, height=_FEEDER_TABLE_H,
            ports={"feed": (25.0, 0.0), "discharge": (25.0, 60.0)},
            gravity_fixed=True, iso_reg="C0074",
        ), "rotary_table")
        self.register("feeder", Symbol(
            svg=f'<g id="sym_feeder_metering">{_METER}</g>',
            width=_METER_W, height=_METER_H,
            ports={"feed": (0.0, _METER_BEAM_Y), "discharge": (_METER_W, _METER_BEAM_Y)},
            gravity_fixed=True, iso_reg="C0035",
        ), "metering")
        self.register("spray_nozzle", _SPRAY_NOZZLE)

    def _register_mixers(self):
        """Register ISO 10628-2 Table 2 group 12: mixers and kneaders.

        ====  ======  ==============================================
        item  reg     descriptor
        ====  ======  ==============================================
        12.1  X2672   In-line rotary mixer
        12.2  X2673   In-line static mixer
        12.3  X8184   Mixing path
        12.4  X8134   Kneader
        ====  ======  ==============================================

        12.2 is the vendored ``fitting/static_mixer``, which matches the
        row. 12.1 and 12.3 are :class:`~pandid.units.Fitting` variants
        beside it; 12.4 is the tagged :class:`~pandid.units.Kneader`.
        """
        self.register("fitting", _ROTARY_MIXER, "rotary_mixer")
        self.register("fitting", _MIXING_PATH, "mixing_path")
        self.register("kneader", _KNEADER)

    def _register_screens(self):
        """Register ISO 10628-2 Table 2 group 7: screening devices.

        One outline (:data:`_SCREEN_OUTLINE`) with each row's mark drawn
        in, plus 7.7's larger outline for its reel. Group 7 has no parts.

        ====  ======  ==============================================
        item  reg     descriptor
        ====  ======  ==============================================
        7.1   X8123   Screening device, sieve, strainer, general
        7.2   X8026   coarse rake type
        7.3   X8027   fine rake type
        7.4   X8028   with coarse and fine screens
        7.5   X2605   sieve, strainer, vibrating type
        7.6   X8029   rotating drum type
        7.7   X8030   basket reel type
        ====  ======  ==============================================

        ``separator/sifter`` is a different drawing; see
        :data:`_SCREEN_OUTLINE`.
        """
        self.register("screening_device", _screen("general", "X8123", _SCREEN_MESH), "general")
        self.register("screening_device", _screen(
            "coarse_rake", "X8026",
            _SCREEN_MESH + _rake_teeth((0.4, 0.55, 0.7), 12.0)), "coarse_rake")
        self.register("screening_device", _screen(
            "fine_rake", "X8027",
            _SCREEN_MESH + _rake_teeth((0.35, 0.45, 0.55, 0.65, 0.75), 7.0)), "fine_rake")
        self.register("screening_device", _screen(
            "coarse_and_fine", "X8028",
            _SCREEN_MESH
            + f'<line x1="20" y1="0" x2="60" y2="40" fill="none" stroke="#111" '
              f'stroke-width="2" {_SCREEN_DASH}/>'), "coarse_and_fine")
        self.register("screening_device", _screen(
            "vibrating", "X2605", _SCREEN_MESH + _SCREEN_VIBRATION), "vibrating")
        self.register("screening_device", _screen(
            "rotating_drum", "X8029", _SCREEN_DRUM), "rotating_drum")
        self.register("screening_device", _REEL_BODY, "basket_reel")

    def _register_evaporators(self):
        """Register the five evaporator bodies on one shell.

        ISO 10628-2 has no evaporator group; the set covers the machines a
        designer chooses between, as far as the drawing can show them:

        =================  =============================================
        variant            what tells it from the others
        =================  =============================================
        ``default``        two tubesheets around a plain boxed element:
                           an evaporator whose element is not yet chosen
        ``calandria``      short tubes and a central downcomer
        ``falling_film``   long tubes, fed onto a distributor over them
        ``climbing_film``  the same long tubes, fed into the foot of them
        ``plate``          a plate pack, and so no tubesheets at all
        =================  =============================================

        ``default`` is for an early PFD, like ISO item 11.1. The falling-
        and climbing-film bodies share tubes but differ in feed height
        (:data:`_EVAP_FEED_HIGH`, :data:`_EVAP_FEED_LOW`) and in the
        distributor, which only falling film has. Forced circulation is
        three tagged items (body, heater, pump), not one symbol; see
        :data:`COMPOSED_APPARATUS`.
        """
        self.register("evaporator", _evaporator(
            "general", _evap_tubesheets(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT),
            _EVAP_ELEMENT))
        self.register("evaporator", _evaporator(
            "calandria",
            _evap_tubesheets(_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT),
            _evap_tubes(_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT, _EVAP_CALANDRIA_XS),
            _evap_tubes(_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT, _EVAP_DOWNCOMER_XS),
            band=(_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT)), "calandria")
        self.register("evaporator", _evaporator(
            "falling_film",
            _evap_tubesheets(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT),
            _evap_tubes(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT, _EVAP_TUBE_XS),
            _EVAP_DISTRIBUTOR), "falling_film")
        self.register("evaporator", _evaporator(
            "climbing_film",
            _evap_tubesheets(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT),
            _evap_tubes(_EVAP_TUBE_TOP, _EVAP_TUBE_BOT, _EVAP_TUBE_XS),
            feed_y=_EVAP_FEED_LOW), "climbing_film")
        self.register("evaporator", _evaporator("plate", _EVAP_PLATES), "plate")

    def _register_kilns(self):
        """Register the three kiln bodies, which share only their ports.

        A rotary kiln, a fluidised calciner and a shaft kiln have no common
        outline; each takes solids in, calcined solids and off-gas out, and
        fires its own fuel.

        ==================  ============================================
        variant             body
        ==================  ============================================
        ``default``         rotary kiln: the sloping shell, its two
                            riding rings and its drive
        ``fluidized_bed``   fluidised-bed or gas-suspension calciner
        ``shaft``           vertical shaft kiln
        ==================  ============================================

        ``default`` is the rotary kiln, the usual meaning of "kiln". All
        three are gravity-fixed (ISO 15519-1 11.4.2): the rotary shell
        falls from feed to discharge, the calciner's bed rests on its grid,
        and the shaft kiln is charged at the top.
        """
        self.register("kiln", Symbol(
            svg=f'<g id="sym_kiln">{_KILN_OUTLINE}{_KILN_RINGS}{_KILN_DRIVE}</g>',
            width=_KILN_W, height=_KILN_H, ports=dict(_KILN_PORTS),
            gravity_fixed=True,
        ), "default")
        self.register("kiln", Symbol(
            svg=f'<g id="sym_kiln_fluidized_bed">{_FBC_OUTLINE}{_FBC_GRID}</g>',
            width=_FBC_W, height=_FBC_H, ports=dict(_FBC_PORTS),
            gravity_fixed=True,
        ), "fluidized_bed")
        self.register("kiln", Symbol(
            svg=f'<g id="sym_kiln_shaft">{_SHAFT_OUTLINE}{_SHAFT_ZONES}</g>',
            width=_SHAFT_W, height=_SHAFT_H, ports=dict(_SHAFT_PORTS),
            gravity_fixed=True,
        ), "shaft")


#: Registry used when none is given.
default_registry = SymbolRegistry()
