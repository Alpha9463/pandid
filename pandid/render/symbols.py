"""SVG symbol registry for the topology primitives.

Equipment shapes follow the conventions of ISO 10628-2 and instrument
balloons follow ANSI/ISA-5.1. Neither set is certified conformant to
anything, and the stencil library the equipment comes from makes no
standards claim of its own. Sources:

- **Vendored (draw.io / diagrams.net P&ID stencils, Apache-2.0)**:
  valves and their variants, pumps, compressors, blowers, heat
  exchangers, vessels, columns, reactors, separators, tanks, reducers,
  in-line fittings, ejectors, vents and funnels. Converted from mxGraph
  stencil XML by ``scripts/vendor_symbols.py`` into
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
Every symbol above is drawn whole. ISO 10628-2 also builds symbols out
of a body and the *parts* of its subject groups 26-29, and clause 5
makes doing so a ``shall`` for anything it does not tabulate:
:class:`IsoPart`, :class:`Overlay`, :class:`OverlayPart` and
:func:`compose` are that mechanism. Read the comment block above
:class:`IsoPart` before composing anything -- it says when a drawing may
be composed at all, which is a narrower question than it looks.
"""

import hashlib
import math
import re
import warnings
from dataclasses import dataclass, field
from difflib import get_close_matches
from functools import lru_cache

from pandid.portgeom import outward_dir
from pandid.streams import SIGNAL_KINDS

# Two placements closer together than this are the same point as far as
# a reader (and a stream endpoint) is concerned.
_COINCIDENT = 0.5

#: Side of the arrowhead a PFD draws at the end of a process line, in
#: drawing units. The renderer emits it as the
#: ``markerWidth``/``markerHeight`` of its ``<marker>``
#: (:meth:`pandid.render.svg.SvgRenderer._defs`) at
#: ``markerUnits="userSpaceOnUse"``, so this is the head's real size on
#: the sheet and not a ratio to a stroke; the marker's viewBox is square
#: and fills it, so the filled triangle is this long *along* the run and
#: exactly as much *across* it.
ARROWHEAD = 12.0

#: The white a drawing has to leave between two arrowheads side by side
#: on one face, in drawing units.
#:
#: **ISO 128-20:1996 §4.4**, *Spacing between lines*: the space between
#: parallel lines shall be at least twice the width of the widest line,
#: and never less than 0,7 mm. Two heads on one face are two parallel
#: filled shapes, so the clearance is twice the weight the sheet draws
#: its process lines at (``pandid.render.svg._PROCESS_STROKE``, 2 units,
#: itself ISO 15519-1 §6.2's). ``tests/test_validate.py`` asserts the
#: two stay in step.
#:
#: In drawing units against the drawing's own line weight, so it says
#: the same thing at whatever scale the sheet is issued. Holding any of
#: them at a *physical* width is ISO 15519-1 §11.1.3's separate problem.
MIN_HEAD_CLEARANCE = 2 * 2.0

#: The closest two nozzles that both wear an arrowhead may be pitched on
#: one face: the head, plus the clearance a reader needs beside it.
#:
#: Two heads at pitch ``p`` leave ``p - ARROWHEAD`` of paper, so this is
#: where that white runs out. Reported by
#: :func:`pandid.validate.validate` as ``nozzles-crowded``. It is a
#: *floor*, not a target: :data:`BLOCK_PITCH` is the larger number a
#: symbol picks when it is choosing a pitch for a family, and
#: ``tests/test_validate.py`` holds the two in that order.
MIN_NOZZLE_PITCH = ARROWHEAD + MIN_HEAD_CLEARANCE


def wears_arrowhead(stream, registry) -> bool:
    """Would this stream wear an arrowhead at its far end?

    Two things say no. A signal line never carried one on either
    drawing. And a stream that ends at a symbol drawn as bare pipe has
    not arrived anywhere: a tee is a point on a line where the line
    divides, and the run carries straight on past it. The question is
    about the artwork rather than about the class, so it is the symbol
    that answers it (see :attr:`Symbol.bare_run`).

    The head goes on the ``marker-end`` of the path, so it lands on the
    nozzle the stream *arrives* at and nowhere else. A stream leaving a
    junction gets its head at its own destination.

    A third thing says no and is not asked here: a P&ID draws no heads
    at all. That is a property of the render rather than of the stream,
    so it is the caller's (``SvgRenderer._tipped``'s ``arrows``, and
    ``validate``'s).

    Here rather than in the renderer, and taking the registry rather
    than reaching for one, because the validator asks the same question
    with no renderer in hand.
    """
    if stream.kind in SIGNAL_KINDS:
        return False
    return not registry.for_unit(stream.dest.owner).bare_run


def spread(index: int, count: int, along: float, pitch: float,
           extent: float, at: float | None = None) -> float:
    """Where member ``index`` of ``count`` sits along a face ``along``
    long.

    The library's one rule for spacing a family of like nozzles down a
    face, so a mixer's inlets, a column's feeds and a block's
    connections are all spread the same way and the drawing is
    consistent between them.

    Members sit ``pitch`` apart, centred on ``at`` (the middle of the
    face when it is ``None``). Past the point where that spacing would
    run them off the ends the whole run is squeezed into ``extent`` of
    the face instead, so the count a symbol was drawn for lands exactly
    where a fixed nozzle would and one more does not shove the others
    aside to find room.

    :class:`PortSeries` is the declarative form of this, for a symbol
    that can name its family with one rule. :func:`block_symbol` calls
    it directly, because a block's family is split across up to four
    faces and one series cannot span two of them; see
    :class:`pandid.units.Block`.
    """
    centre = along / 2 if at is None else at
    span = min(pitch * (count - 1), extent * along)
    return centre if count < 2 else centre - span / 2 + span * index / (count - 1)


def _on_face(face: str, t: float, width: float, height: float) -> tuple[float, float]:
    """The symbol-space point ``t`` along ``face`` of a ``width`` x
    ``height`` box.

    ``t`` runs top-to-bottom on the two upright faces and left-to-right
    on the two horizontal ones, which is the direction :func:`spread`
    lays a family out in and the direction a reader numbers nozzles in.
    """
    return {"W": (0.0, t), "E": (width, t),
            "N": (t, 0.0), "S": (t, height)}[face]


@dataclass(frozen=True)
class PortSeries:
    """A family of like ports spread evenly along one face of a symbol.

    A :class:`~pandid.units.Mixer` does not have a fixed set of inlets,
    since the unit decides how many there are, so the symbol cannot
    author a coordinate per port the way a pump authors its suction. It
    declares the *rule* instead, and the coordinates are resolved once
    the unit is in hand and the count is known.

    Members are ``prefix`` followed by a 1-based index (``in_1``,
    ``in_2``, ...), matching the names :class:`~pandid.units.Mixer` and
    :class:`~pandid.units.Splitter` generate. A family that is usually
    singular names its lone member ``singular`` instead: a
    :class:`~pandid.units.Column` with one feed has a nozzle called
    ``feed``, and only grows ``feed_1``, ``feed_2`` when it is given
    more than one.

    Ports sit ``pitch`` apart, centred on ``at``: the point along the
    face the symbol would have drawn a single nozzle at, or the middle
    of the face when it names none. Past the point where that spacing
    would run them off the ends, the whole run is squeezed into
    ``extent`` of the face instead. The count the symbol was drawn for
    therefore lands exactly where a fixed symbol would put it, and one
    more does not shove the others aside to find room.
    """

    prefix: str
    face: str
    pitch: float = 20.0
    extent: float = 0.7
    at: float | None = None
    singular: str | None = None

    def matches(self, port_name: str) -> bool:
        """True when ``port_name`` is a member of this series."""
        return port_name == self.singular or (
            port_name.startswith(self.prefix)
            and port_name[len(self.prefix):].isdigit())

    def placement(self, index: int, count: int,
                  width: float, height: float) -> tuple[float, float]:
        """Symbol-space coordinate of member ``index`` of ``count``."""
        along = height if self.face in ("W", "E") else width
        t = spread(index, count, along, self.pitch, self.extent, self.at)
        return _on_face(self.face, t, width, height)

    def reach(self, width: float, height: float) -> tuple[float, float, float]:
        """Where members can land: ``(face_coordinate, lo, hi)`` along
        the face.

        A series has no fixed membership, so it has no fixed set of
        points to compare a nozzle against. It has a *stretch of face*
        it may put one on, for some count. One member sits at ``at``;
        the widest run spreads ``extent`` of the face around it.
        Anything inside that band shares a placement with a member
        sooner or later, which is what a collision check needs to know.
        """
        along = height if self.face in ("W", "E") else width
        centre = along / 2 if self.at is None else self.at
        half = self.extent * along / 2
        fixed = {"W": 0.0, "E": width, "N": 0.0, "S": height}[self.face]
        return fixed, centre - half, centre + half


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
# THE RULE THIS MODULE ENFORCES, AND THE ONE TO READ BEFORE ADDING A
# COMPOSITION
# --------------------------------------------------------------------
# **Compose only where ISO itself composes. Where ISO registers a
# distinct symbol, it stays a distinct symbol.**
#
# The test is not "does it look like a body with something inside it".
# It is: *is every mark that distinguishes this drawing from the shared
# body a tabulated group-26/27/28/29 item, and can it be named by its
# registration number?* Item 8.3 (gravity separator, X8031) passes -- its
# only mark is the down arrow that Table 2 registers on its own as item
# 29.1, C2028. Item 8.10 (cyclone separator, X2618) fails: its mark is a
# helical vortex, and no item in group 29 draws one, so there is nothing
# to compose it from and X2618 is its own registered symbol. A
# hydrocyclone is not "separator body + cyclone characteristic"; it is
# X2618.
#
# :class:`IsoPart` is where that test is made checkable rather than
# remembered. A part cannot be registered without naming the group, the
# item number and the registration number it claims to be, so a reader
# -- or ``tests/test_composition.py`` -- can put the drawing next to
# Table 2 and check it. Registration numbers are the identity of a
# symbol (ISO 14617-1 §3.6) and are what tells two same-shape symbols
# apart (§4.2), which is exactly the distinction this rule turns on.
# ----------------------------------------------------------------

#: The subject groups of ISO 10628-2 Table 1 that are parts rather than
#: apparatus, with the group name each is listed under. Nothing outside
#: these four is a supplementary symbol, so nothing outside them may be
#: overlaid: a whole apparatus drawn inside another apparatus is two
#: pieces of equipment on one tag, not a composition.
PART_GROUPS = {
    26: "apparatus elements",
    27: "internals",
    28: "agitators, stirrers",
    29: "internal characteristics and built-in components",
}

#: The four registration-number namespaces ISO 10628-2 clause 5 column 2
#: declares, as one pattern:
#:
#: ``nnn`` / ``nnnn``   an ISO 14617 graphical symbol
#: ``Cnnnn``            a preliminary number for a symbol that will be
#:                      implemented in ISO 14617 at the next review
#: ``X2nnn``            an ISO 14617 symbol *example*
#: ``X8nnn``            an ISO 10628-2 symbol *example*
#:
#: The distinction between a bare number and an X number is not
#: cosmetic: ISO 14617-1 §3.5 Note 2 calls a symbol example a guideline,
#: while a bare-numbered entry is a normative basic symbol. It governs
#: how strictly a given shape has to be matched, so it is worth being
#: able to read off the declaration.
_REG_NO = re.compile(r"\A(?:\d{3,4}|C\d{3,4}|X[28]\d{3})\Z")


@dataclass(frozen=True)
class IsoPart:
    """The identity of one ISO 10628-2 group 26-29 supplementary symbol.

    Four facts, all of them checkable against Table 2 by anyone holding
    the standard: which of the four part groups it belongs to, its item
    number within that group, its registration number, and what the
    standard calls it.

    Required on every :class:`OverlayPart`, which is the whole point.
    pandid records no registration number for any of its 157 whole-symbol
    drawings today, so nothing ties a shape to the entry it claims to be
    and no conformance statement about one can be checked. A part is
    where that stops: an overlay is only ever justified by the standard
    composing there, and a part that cannot name the item it is has no
    justification to offer.

    Args:
        group: The Table 1 subject group, one of :data:`PART_GROUPS`.
        item: The item number within the group, as Table 2 writes it and
            including the group -- ``"27.3"``, not ``"3"``.
        reg: The registration number, in one of the four namespaces
            clause 5 declares. See :data:`_REG_NO`.
        name: The standard's own descriptor for the item, so a reader
            can find the row without counting down the column.
    """

    group: int
    item: str
    reg: str
    name: str

    def __post_init__(self) -> None:
        if self.group not in PART_GROUPS:
            raise ValueError(
                f"{self.reg}: ISO 10628-2 group {self.group} is not one of the part "
                f"groups {sorted(PART_GROUPS)}. Groups 1-25 are whole apparatus, and "
                f"an apparatus overlaid on another apparatus is two units on one tag"
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
    """One supplementary part, and where it sits on a body's box.

    Named rather than held: an overlay carries the part's registry key,
    so the artwork and the registration number are looked up in the one
    place they are declared, and an overlay is a small hashable value the
    composition cache can be keyed by.

    The placement is stated in **fractions of the body's box**, not in
    drawing units, which is what makes a composition survive being
    resized. A tray at ``y=0.3`` is three-tenths down the shell whether
    the shell is drawn at its own size or stretched to a box the author
    gave the unit, so the trays stay evenly spaced instead of drifting
    off the bottom head.

    Fractions outside ``0..1`` put the part outside the body, and that is
    a supported case rather than an accident: ISO item 1.27 (X8006) hangs
    the drive motor **above** the top head, on the agitator's shaft.
    :func:`compose` grows the composed box to hold it.

    A part that repeats -- a tray column is one deck drawn N times -- is
    N overlays with N values of ``y``, not one overlay with a count. The
    pitch is then the caller's arithmetic and the mechanism stays a
    placement rule, which is what lets a baffle-tray column alternate
    which wall each deck touches by varying ``x`` as well.

    Args:
        group: The part's ISO subject group, 26 to 29.
        name: The part's registry name, in pandid's spelling
            (``"turbine"``), not the standard's descriptor.
        x: Left edge, as a fraction of the body's width.
        y: Top edge, as a fraction of the body's height.
        w: Width, as a fraction of the body's width.
        h: Height, as a fraction of the body's height.
        mirror: Draw the part reflected left to right on its rectangle.

    Why a mirror, and only in this direction
    ----------------------------------------
    Two of Table 2's four group-26 supports are **chiral**: the standard
    draws item 26.2's bracket and item 26.4's ring against a wall on one
    side, and a vessel standing on either wants a pair, one per wall. The
    parts are drawn in the hand Table 2 draws them in, so the other hand
    has to come from somewhere, and a placement flag is the cheaper of
    the two answers -- a second registered part would be a *second
    registration number* for a symbol the standard numbers once, which is
    exactly the false identity :class:`IsoPart` exists to stop.

    Left to right only, because that is the whole of the case. A support
    turned upside down is not a support, and a mark that means something
    different upside down is what :attr:`OverlayPart.directional` is for.
    """

    group: int
    name: str
    x: float
    y: float
    w: float
    h: float
    mirror: bool = False

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError(
                f"overlay {self.group}/{self.name} is placed {self.w:g} x {self.h:g} of "
                f"the body's box; a part with no extent draws nothing, and a negative "
                f"one draws the part inside out"
            )


@dataclass
class Symbol:
    """An SVG template for a unit, with named port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Every placement a port may take, keyed by the face it lands on,
    # each with its own exact coordinate so a moved port still lands on
    # drawn ink:
    #   {"feed": {"W": (0.0, 15.0), "N": (30.0, 0.0)}}
    # ``__post_init__`` folds the symbol's own nozzle in as the first
    # entry, so this is the *whole* menu and nothing downstream has to
    # merge a privileged default back in. A nozzle fixed by physics is
    # simply one with a single entry.
    port_faces: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    # Connections with no face of their own. An instrument balloon is a
    # circle, so a signal may meet it anywhere and "in on the west, out
    # on the east" is an artefact of having to pick a default. Only
    # these may offer each other the same face: the overlap is a menu,
    # not a collision, since one placement per port is ever live.
    # Authoring *alternates* for an equipment nozzle does not make it
    # faceless -- a drum's inlet may be moved to the right head, but it
    # is still the inlet's nozzle and nothing else may sit on it.
    faceless_ports: frozenset[str] = frozenset()
    # Port families whose membership the *unit* decides, such as a
    # Mixer's inlets. The symbol cannot list them in ``ports`` because
    # it does not know how many there are, so it declares the rule and
    # :mod:`pandid.portgeom` resolves the coordinates against the unit.
    # A series is the sole authority for its own members; naming one in
    # ``ports`` as well is rejected below.
    port_series: tuple[PortSeries, ...] = ()
    label_pos: str | None = None
    # Tells two definitions of one (kind, variant) apart when they are
    # not the same drawing. A conveyor is built to its belt run rather
    # than scaled to it, so each length is its own ``<defs>`` entry and
    # needs an id of its own; every fixed symbol leaves this empty.
    id_suffix: str = ""
    # May the artwork be scaled unevenly to fill a box of another shape?
    # A user who sizes a unit is asking for a box, and a shell, tank or
    # exchanger simply becomes that box. A shape whose roundness carries
    # meaning does not: an instrument balloon is a circle because
    # ISA-5.1 says a circle, so it keeps its aspect and is centred in
    # the box.
    #
    # The vendored symbols take this from the stencil's own ``aspect``
    # attribute -- ``variable`` is stretchable and ``fixed`` is not --
    # and the default here is theirs. :mod:`pandid.portgeom` resolves
    # ports onto the artwork either way, since a port in the letterbox
    # would draw a stream that stops short of its equipment.
    stretchable: bool = True
    # Is the artwork the pipe itself and nothing else? A tee is three
    # lines meeting: no body is drawn, and the run passes straight
    # through. That is what decides whether a stream *ending* here wears
    # the PFD arrowhead; see :func:`wears_arrowhead`.
    bare_run: bool = False
    # Does the artwork only mean what it says one way up? ISO 15519-1
    # §11.4.2 permits turning and mirroring "in order to fit into the
    # actual layout of the diagram", then excepts one class of symbol:
    #
    #     Exceptions for turning are symbols representing components
    #     or devices where gravity is a functionality, for example
    #     symbol 2061: Open tank or symbol X 2618: Cyclone separator;
    #     see Figure 22 b). Such symbols must not be turned.
    #
    # Set where the separation, containment or holdup the symbol depicts
    # is performed by gravity and the drawing shows it: a free liquid
    # surface, an open top, a settling body that drops its heavy phase
    # out of a low point. Not set for a device whose function is
    # pressure, rotation, heat transfer or throttling, even when a
    # nozzle happens to be drawn low. The vendored symbols take it from
    # GRAVITY_FIXED in ``scripts/vendor_symbols.py``, which records the
    # reason per family.
    #
    # A turned one is reported by :func:`pandid.validate.validate`
    # rather than refused: the sheet still draws, and the escape hatch
    # ISO's own paragraph recommends -- "a new symbol should be created
    # to the actual orientation" -- is here as a variant
    # (``vessel/horizontal``).
    gravity_fixed: bool = False
    # Does the artwork state a *direction* that an axis flip would
    # reverse? The heater and the cooler are one stencil pair -- the
    # same circle and the same zigzag -- distinguished by nothing but
    # which end of the diagonal wears the arrowhead, so a flip does not
    # draw a flipped cooler: it draws the other symbol.
    #
    # Which placements reverse it, and which merely carry it, is
    # :func:`pandid.render.svg._reflections`' answer, and the line falls
    # between the four that leave the axes alone and the four that swap
    # them:
    #
    #   reversed   mirrored="x", mirrored="y", mirrored="xy",
    #              orientation=180
    #   carried    orientation=90, orientation=270 (with or without a
    #              mirror, whose part is undone on its own)
    #
    # A half turn is exactly the two mirrors composed and puts the head
    # at the far end of the diagonal, where the sibling symbol draws it;
    # a quarter turn puts it on the *other* diagonal, where no upright
    # drawing of either symbol has it, and turns the box with it.
    #
    # ISO 15519-1 §11.4.2 permits mirroring "in order to fit into the
    # actual layout of the diagram" and excepts *turning* only, so the
    # flip is not the thing to refuse: the placement still moves the
    # nozzles and the renderer holds the drawing still under it, as it
    # already holds a symbol's own lettering upright
    # (:func:`pandid.render.svg._upright_text`).
    #
    # Declaring it costs a ``<defs>`` entry per reflection (three,
    # shared across all eight placements) and asks two things of the
    # artwork: every port has to stay on ink under any flip, and it must
    # carry no lettering of its own, since a glyph inside a drawing held
    # still would need the residual of the two rather than its own
    # counter-transform. ``tests/test_symbol_invariants`` holds any
    # later one to both. The vendored symbols take it from DIRECTIONAL
    # in ``scripts/vendor_symbols.py``.
    directional: bool = False
    # The draw.io stencil this artwork was converted from, under the key
    # draw.io's own registry files it:
    # ``"mxgraph.pid.valves.gate_valve"``. Empty for a symbol drawn here
    # rather than vendored, and read by :mod:`pandid.render.drawio` and
    # nothing else.
    #
    # The key is derived from the two names in the stencil file itself,
    # by draw.io's own rule, at the moment the artwork is converted --
    # see ``drawio_shape_key`` in ``scripts/vendor_symbols.py``. One
    # written down by hand would go on naming a shape after a re-vendor
    # renamed it, and draw.io answers a key it cannot resolve with a
    # plain rectangle rather than an error, so the sheet would quietly
    # stop being a P&ID.
    drawio_shape: str = ""
    # How a *derived* symbol differs from the stencil ``drawio_shape``
    # names, for the two derivations this module makes. Neither is a
    # stencil of its own, so the reference alone would draw the shape it
    # was derived from: a fitting turned end for end (:func:`expander`)
    # draws its stencil mirrored, and a normally closed valve
    # (:func:`darkened`) draws it with its body filled. Stated as what
    # they are rather than as draw.io style text.
    drawio_flip_h: bool = False
    drawio_fill: str = ""
    # The stencil that draws the **body** of a composition, for a symbol
    # that has one. Never :attr:`drawio_shape`, and the two are different
    # claims: ``drawio_shape`` says *this drawing is that stencil*, which
    # a composition is not, while this says *the outline under the parts
    # is that stencil, and the parts are somewhere else*.
    #
    # :mod:`pandid.render.drawio` is the only reader, and it draws the
    # body from this and one child cell per :attr:`overlays` entry. That
    # is what stops the strainer divergence: a composed reactor exported
    # under the vessel's own ``drawio_shape`` would come out as a bare
    # vessel, the right outline silently missing the thing that made it a
    # reactor, whereas a body cell with the agitator beside it is the
    # drawing the sheet has.
    #
    # Written by :func:`compose` from the body's own reference, and empty
    # where the body is drawn here rather than vendored.
    drawio_body_shape: str = ""
    # The supplementary parts this drawing carries, in the order they are
    # painted over the body. Empty for a symbol drawn whole, which is
    # every symbol the registry ships today: a body with no parts is the
    # zero case of a composition and nothing about it changes.
    #
    # Written by :func:`compose` and by nothing else, so it is a record of
    # what the artwork *is* rather than a request. Read by the draw.io
    # backend, which has to export a composition as its parts rather than
    # as a stencil reference; see :attr:`drawio_shape`.
    overlays: tuple[Overlay, ...] = ()
    # The ISO registration number this drawing claims to be -- "2062",
    # "X2618", "C2044" -- or empty where nobody has checked it against
    # the standard yet, which is where all 157 shipped symbols stand.
    #
    # Per ISO 14617-1 §3.6 the registration number is a symbol's identity
    # and is stable for its lifetime, and §4.2 makes it the thing that
    # tells two same-shape symbols apart. Recording it is the difference
    # between "this looks like a cyclone" and "this is X2618", and it is
    # what makes the composition rule in the block above :class:`IsoPart`
    # checkable rather than remembered.
    #
    # Deliberately optional and deliberately empty: filling it in for a
    # symbol is a conformance claim about that symbol's geometry, and one
    # made by assumption is worse than none. :class:`IsoPart` is where it
    # is *required*, because a part that cannot name its Table 2 row has
    # no business being composed with.
    iso_reg: str = ""

    def __post_init__(self) -> None:
        declared = {name: dict(faces) for name, faces in self.port_faces.items()}
        # Everything below rejects rather than repairs. The menu is
        # re-keyed by coordinate at resolve time, so a placement filed
        # under the wrong face simply ceases to exist, and one that
        # vanishes is indistinguishable from one never authored. The
        # invariant suite catches these for the shipped registry; a
        # third-party symbol only ever meets this constructor.
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
                    # ``ports`` is the authority on the home nozzle, so
                    # this placement could only ever be discarded.
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
        """The series placing ``port_name``, None for a fixed nozzle."""
        for series in self.port_series:
            if series.matches(port_name):
                return series
        return None

    def symbol_id(self) -> str:
        """The svg id, for messages; a Symbol has no name of its own."""
        match = re.search(r'\bid="([^"]+)"', self.svg)
        return match.group(1) if match else "<symbol>"

    def coincident_ports(self) -> list[tuple[str, str, tuple[float, float]]]:
        """Pairs of *different* ports sharing a placement, with the
        point.

        Two ports at one coordinate means a stream routed to one lands
        exactly on top of a stream routed to the other. Two placements
        of a *single* port may coincide, since only one of them is ever
        live.

        :attr:`faceless_ports` are exempt from *each other*, not from
        the rule: they are still checked against the nozzles that do own
        their face. The exemption is a declaration, deliberately, rather
        than something read off the shape of the menu: "this connection
        is faceless" and "this nozzle has authored alternatives" both
        produce a multi-entry menu, and only the first of them justifies
        two ports sitting on one point.

        A :class:`PortSeries` is checked as the band of face it may
        place a member on, reported against ``prefix*``. Its membership
        belongs to the unit rather than the symbol, so there is no set
        of points to compare, but a nozzle standing inside that band
        shares a placement with a member for some count, and the whole
        value of a static check is saying so before a drawing is made.
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
            fixed, lo, hi = series.reach(self.width, self.height)
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
# aspect="variable"). Two changes were made to it. The ``<background>``
# drier housing is dropped, since the housing is the drier and not the
# conveyor. And the distance between the two rollers becomes a parameter
# while the rollers keep the stencil's own r=10, so a longer conveyor
# grows its straight run and its rollers stay circles. See NOTICE, and
# ADAPTED_ELSEWHERE in scripts/vendor_symbols.py.
#
# It cannot come through that generator with the rest: the generator
# emits one fixed-size Symbol per shape, and a fixed drawing placed in a
# box of another aspect ratio is scaled unevenly, which would draw the
# rollers as ellipses.
# ----------------------------------------------------------------

#: Roller radius, from the stencil's 20x20 roller ellipses. The same at
#: every length: only the straight belt run between the rollers grows.
CONVEYOR_ROLLER = 10.0
#: Default belt run, from the stencil's own proportions: it draws the
#: rollers centred at x=20 and x=80, so the conveyor spans x=10..90.
CONVEYOR_LENGTH = 80.0
#: Two roller diameters. Any shorter and the rollers overlap, leaving no
#: belt.
CONVEYOR_MIN_LENGTH = 4 * CONVEYOR_ROLLER


def conveyor_too_short(length: float, owner: str = "") -> ValueError:
    """The error for a belt run the rollers do not leave room for.

    Built here so the message :class:`~pandid.units.Conveyor` raises up
    front and the one :func:`conveyor_symbol` raises later are the same
    sentence about the same rule.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}length={length:g} is shorter than a "
        f"conveyor can be drawn: the rollers are {CONVEYOR_ROLLER:g} in radius "
        f"and would overlap. Use length={CONVEYOR_MIN_LENGTH:g} or more, two "
        f"roller diameters."
    )


@lru_cache(maxsize=None)
def conveyor_symbol(length: float = CONVEYOR_LENGTH) -> Symbol:
    """A belt conveyor ``length`` long: two rollers and the belt run
    between.

    The symbol is *built* to the length rather than scaled to it, so its
    width **is** the length and the box a conveyor is placed in is
    exactly the box its artwork was drawn in. That is what holds the
    rollers to :data:`CONVEYOR_ROLLER` at every length.

    ``feed`` is the tail roller. Its home nozzle is the end of the belt,
    and it is offered on the top face as well, because material is
    dropped onto a conveyor rather than piped into it. ``discharge`` is
    the head roller, where the belt throws off; it is offered on the
    underside too, for the chute that catches what comes over. Every
    placement sits on a roller circle or on the end of a belt line, at
    any length.

    Cached, because port resolution asks for a unit's symbol on every
    call and the registry already hands out one shared instance per
    fixed symbol.
    """
    if length < CONVEYOR_MIN_LENGTH:
        raise conveyor_too_short(length)
    r, height = CONVEYOR_ROLLER, 2 * CONVEYOR_ROLLER
    tail, head = r, length - r
    suffix = f"_L{length:g}"
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
        svg=svg, width=float(length), height=float(height),
        ports={"feed": (0.0, r), "discharge": (float(length), r)},
        port_faces={"feed": {"N": (tail, 0.0)},
                    "discharge": {"S": (head, float(height))}},
        id_suffix=suffix,
        # The rollers are circles, which is why this symbol is built to
        # its length instead of scaled to it.
        stretchable=False,
    )


# ----------------------------------------------------------------
# The block flow diagram's box.
#
# An original primitive, not a stencil: a BFD block is a plain rectangle
# with a name in it, and the draw.io P&ID set is a set of *equipment*.
# See NOTICE section 1, beside the Mixer, the Splitter and the pipe tee.
#
# Its nozzles cannot be authored in advance. A Mixer's are a PortSeries:
# one rule, one face, spread by count. A block's connections are split
# across up to four faces with a count on each, so one series cannot
# place them and the symbol has to be built once the unit is in hand --
# the conveyor's mechanism above, for a different reason. That is also
# what lets the box size itself to what it carries.
# ----------------------------------------------------------------

#: How far apart a block spreads the connections on one face.
#:
#: Derived from the arrowhead rather than chosen: two nozzles pitched
#: closer than about two and a half heads apart draw two arrows whose
#: tips touch, and at print size the pair reads as one double-headed
#: blob rather than as two lines arriving. That is the defect reported
#: against ``10_ethanol_pfd``'s M-301, whose two feeds are 14.5 apart
#: carrying 12-unit heads. 2.5 leaves a head's worth of white between
#: them.
BLOCK_PITCH = 2.5 * ARROWHEAD

#: The smallest box a block is drawn in, whatever it carries. Big enough
#: to hold a short name at the 12pt the renderer letters a tag in, and
#: to read as a section of plant rather than as an in-line fitting.
BLOCK_MIN_WIDTH = 120.0
BLOCK_MIN_HEIGHT = 80.0

#: Drawn width of one character of a tag, at the renderer's 12pt
#: sans-serif, plus the padding either side of it. The same rule and the
#: same numbers :func:`pandid.portgeom.resolve_size` sizes a boundary
#: flag's label by; a block letters its name inside the box, so the box
#: has to be at least that wide or the name hangs out of both ends of
#: it.
_LABEL_EM = 8.0
_LABEL_PAD = 30.0


def block_span(count: int) -> float:
    """The least length of face ``count`` connections can be drawn on.

    ``count`` nozzles at :data:`BLOCK_PITCH` apart, with half a pitch of
    margin at each end so the outermost one is not drawn into a corner.
    This is what a block grows to fit rather than squeezing.
    """
    return BLOCK_PITCH * count


def block_box_too_small(owner: str, face: str, count: int, axis: str,
                        given: float, needed: float,
                        turned: bool = False) -> ValueError:
    """The error for a box too small to draw a block's nozzles legibly.

    Built here so every call that can produce it -- the constructor,
    :meth:`pandid.units.Block.nozzle`, :meth:`pandid.units.Block.pin`
    and a later assignment to ``width`` -- raises the same sentence
    about the same rule, exactly as :func:`conveyor_too_short` is.

    ``turned`` names the case worth spelling out, because otherwise the
    message is about an axis the author never mentioned: a quarter turn
    draws the box's upright faces across the sheet, so the run that was
    measured against the height is now measured against the width.
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


#: The order the faces are visited in when a block's box is measured and
#: its nozzles are laid out. Fixed, so a block's drawing does not depend
#: on the order its connections happened to be declared in.
_BLOCK_FACES = ("W", "E", "N", "S")


@lru_cache(maxsize=None)
def block_symbol(faces: tuple[tuple[str, str], ...], label: str = "") -> Symbol:
    """A block flow diagram's box, with a nozzle per declared
    connection.

    ``faces`` is ``((port_name, face), ...)`` in the unit's own port
    order. Both it and the box that has to hold it come off the unit,
    which is why this is built rather than registered: the count on each
    face is the author's.

    **The box grows to fit rather than crushing the spacing.** Each face
    is made at least :func:`block_span` long for the connections on it,
    so eight inputs on the west wall make a taller block instead of
    eight nozzles squeezed into the height a one-inlet block was drawn
    at -- the opposite of what :func:`spread` does when it runs out of
    room, since a block is a box whose size means nothing at all and
    there is nothing here to trade against legibility.

    ``label`` is the tag lettered inside the box, and widens it enough
    to hold the letters. It is passed **empty by a unit that was given a
    ``width`` of its own**: an explicit width wins outright, as
    :func:`pandid.portgeom.resolve_size` has it, so a name longer than
    the box the author asked for simply overflows it. That is also what
    keeps one port layout to one drawing whatever the block is called,
    which lets a block be measured against the registered symbol the way
    every other kind is.

    Every nozzle sits on the rectangle's own outline, so every one is on
    drawn ink on whichever face it was put on, at any count and in a box
    of any shape. There is no menu: a block's connection has exactly the
    face it was declared with, and :meth:`pandid.units.Block.nozzle`
    moves it by *changing the declaration* and rebuilding this drawing.

    Cached, because port resolution asks for a unit's symbol on every
    call.
    """
    on: dict[str, list[str]] = {face: [] for face in _BLOCK_FACES}
    for port_name, face in faces:
        on[face].append(port_name)
    width = max(BLOCK_MIN_WIDTH, _LABEL_EM * len(label) + _LABEL_PAD,
                block_span(len(on["N"])), block_span(len(on["S"])))
    height = max(BLOCK_MIN_HEIGHT, block_span(len(on["W"])), block_span(len(on["E"])))
    ports: dict[str, tuple[float, float]] = {}
    for face in _BLOCK_FACES:
        members = on[face]
        along = height if face in ("W", "E") else width
        for i, port_name in enumerate(members):
            # extent=1.0, because the box was just made long enough for
            # the run at full pitch, so the squeeze never engages. The
            # only way to reach it is to hand the block a smaller box
            # than it sized itself to, and Block refuses that outright
            # rather than drawing it.
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
        # A BFD writes the section's name inside its box. Saying so here
        # stops the label being hung off a side and stops the router
        # standing lines off to clear one that is not there.
        label_pos="center",
        # The artwork is built to the box, so each distinct box is its
        # own <defs> entry -- the conveyor's rule, for the same reason.
        id_suffix=f"_{width:g}x{height:g}",
    )


# Drawings built to a size the *unit* carries, rather than drawn once and
# scaled into whatever box they land in. Uneven scaling turns a
# conveyor's rollers into ellipses, so its drawing is made to measure; a
# block's nozzles are a per-face count the symbol cannot know until it
# has the unit, so its drawing is made to *fit*.
#
# Keyed by ``(kind, variant)``, with ``None`` for the variant meaning
# "every variant of this kind". Both entries today are kind-wide, and
# both kinds have exactly one variant, so the two spellings say the same
# thing about the symbols on hand -- but only one of them stays true when
# a second variant arrives. A tray column drawn to its tray count is a
# ``("column", "tray")`` entry, and under a kind-wide key it would have
# captured ``column/default`` and ``column/packed`` as well and drawn
# every tower as a tray tower.
_BUILT_TO_SIZE: "dict[tuple[str, str | None], object]" = {
    ("conveyor", None): lambda unit: conveyor_symbol(unit.length),
    ("block", None): lambda unit: unit.symbol(),
}


def _built_to_size(kind: str, variant: str):
    """The builder for ``(kind, variant)``, most specific first."""
    return _BUILT_TO_SIZE.get((kind, variant)) or _BUILT_TO_SIZE.get((kind, None))


# ----------------------------------------------------------------
# Devices drawn in a normal position.
#
# Normally closed valves: PIP PIC001 4.2.2.7 draws one with its body
# darkened solid. Not an ISA-5.1 convention -- ISA-5.1 says nothing
# about valve fill and leaves manual block valve depiction to the piping
# group -- and not an ISO 10628 one either, so a sheet that draws one
# owes its reader a legend entry (ISA-5.1 2.8.1(b)(1), 2.8.2, 5.2.5).
# See :class:`pandid.units.Valve`.
#
# A spectacle blind is the other case. Its position is not a mark
# applied to a symbol; it is *which symbol*, because the device is two
# discs and the drawing says which of them is in the line by filling it.
# The stencil set draws both, so the closed state is a registered shape
# rather than a derived one -- see ``SymbolRegistry.register_closed``.
# Nothing has to be declared on a legend for it.
# ----------------------------------------------------------------

#: Valve variants whose body may be darkened. Filling a body leaves only
#: its *outline*, so the test is whether the outline alone still names
#: the device. A gate's pinched waist, a globe's and a ball's round one,
#: an angle body's right-angled lobes and a three-way's third lobe all
#: survive, as do the marks a plug and a pinch valve draw in the open
#: notches, the needle's stem across the waist, and every operator drawn
#: *outside* the body.
#:
#: Everything else takes the NC abbreviation of clause 4.2.2.8, which is
#: the safe default for a variant added later: a butterfly's disc (the
#: standard's own example), a check valve's flow arrow and a knife
#: gate's blade are all *inside* the outline, and a body filled over
#: them draws a darkened gate valve wearing another name.
#:
#: ``solenoid`` is on the list. Its stencil is called "Solenoid Valve
#: Closed", but the artwork is byte-for-byte the motor- and
#: hydraulic-operated valves' -- same body path, same operator box,
#: differing only in the letter -- and carries no fill of its own. The
#: name is draw.io's label for the mechanism's rest state, not something
#: the drawing says.
NC_DARKENS = frozenset({
    "default", "gate", "globe", "ball", "needle", "plug", "pinch", "three_way",
    "angle", "bleed", "manual", "motor", "solenoid", "hydraulic",
})

#: Valve variants that may not be shown normally closed at all. PIP
#: PIC001 clause 4.2.2.10: "Control valves or relief valves shall not be
#: shown as NC." A darkened control valve on an issued sheet reads as a
#: block valve someone has closed, which is a drafting error rather than
#: a style.
#:
#: ``butterfly_pneumatic`` is deliberately absent. An actuated butterfly
#: is ordinarily an on-off block valve rather than a modulating one, and
#: 4.2.2.10 scopes itself to control and relief valves; its disc lives
#: inside the outline so it takes the letters of 4.2.2.8 rather than the
#: fill.
NC_FORBIDDEN = frozenset({"control", "regulator", "relief", "psv"})

# ----------------------------------------------------------------
# Body and actuator: two questions, one drawing that answers both.
#
# ISO 15519-2:2015 Table A.3 puts these on separate axes and says so
# with its registration numbers: A.3.20, "Control valve, general,
# continuously adjustability, SHOWN WITH GENERAL ACTUATOR", carries
# three at once -- 2101A, 210A, P050B -- because the control valve
# symbol *is* the body symbol with an actuator symbol on it. §7.4.4.3
# completes the rule: "Actuators shall be represented by actuator
# symbols without indication of type or indication of power media. Only
# if it of importance for understanding of the diagram actuator symbol
# of specific type should be used."
#
# So the API takes the two questions separately -- ``variant`` is the
# body, ``actuator`` is what strokes it. The artwork cannot follow it.
#
# The stencil set FUSES the two. Every actuated valve draw.io ships is
# one path drawing a body and an operator together: "Pneumatic Operated"
# is the bowtie with a dome on it, "Motor Operated Valve" the same
# bowtie with a lettered box, and so on through the whole of valves.xml
# (32 shapes; the six below are all of them that draw an operator at
# all). There is no separate actuator glyph to lay over a globe or a
# ball, so a globe body with a diaphragm actuator is not a combination
# this package can draw -- not because the API forbids it, but because
# no drawing of it exists. A synthesised one would have no
# ``drawio_shape``, so an export to draw.io would hand the reader a
# traced picture where every other valve is a native editable stencil.
#
# This table is therefore the pairs the stencil set can draw, keyed the
# way an engineer asks for them. A pair that is not here raises and
# names the ones that are: reject rather than repair, because a silently
# substituted drawing says something the author did not.
#
# ``default`` and ``gate`` are both keyed because they are byte-for-byte
# the same stencil (draw.io's "Gate Valve"), and it is ISO's *general*
# two-way body rather than specifically a gate: A.3.20 builds the
# control valve on exactly it.
# ----------------------------------------------------------------

#: ``(body, actuator)`` -> the variant whose artwork draws that pairing.
#:
#: Read by :class:`pandid.units.Valve`, which resolves the pair to a
#: single variant and stores *that*. The pair is a spelling and the
#: variant is the drawing; keeping both would be one fact in two places,
#: and the drawing is the one the sheet is issued with.
ACTUATED: dict[tuple[str, str], str] = {
    # The control valve. ISO A.3.20's general body with A.3.41's
    # diaphragm on it, which is what professional_examples/P&ID_301.pdf
    # draws on CV-301-1, CV-303, CV-305, CV-306, CV-308 and CV-312, and
    # what CHEE4001-7103 p.5 draws. ``variant="control"`` is the
    # shorthand for this pairing.
    ("default", "diaphragm"): "control",
    ("gate", "diaphragm"): "control",
    # The same actuator on a butterfly body: the one non-bowtie pairing
    # the stencil set draws.
    ("butterfly", "diaphragm"): "butterfly_pneumatic",
    # The three lettered operator boxes. One body, three letters, so
    # they are three stencils and three pairings.
    ("default", "motor"): "motor",
    ("gate", "motor"): "motor",
    ("default", "solenoid"): "solenoid",
    ("gate", "solenoid"): "solenoid",
    ("default", "hydraulic"): "hydraulic",
    ("gate", "hydraulic"): "hydraulic",
    # A handwheel is an *operator* and not an actuator -- it loses no
    # air, so :data:`FAIL_ACTUATED` refuses it a fail position. It is in
    # this table all the same, "what is on top of this valve" being one
    # question a hand valve answers too.
    ("default", "handwheel"): "manual",
    ("gate", "handwheel"): "manual",
}

#: The actuators that may be named, in the order the error message lists
#: them: the three powered ones ISA-5.1 note 5.3.4(10) scopes its
#: failure symbols to, then the hand operator.
#:
#: ``piston`` is deliberately not here. ISO A.3.43 registers a cylinder
#: actuator (P051B), but valves.xml draws no cylinder. An author who
#: needs one supplies the artwork through
#: :meth:`SymbolRegistry.register` and asks for it by variant.
ACTUATORS: tuple[str, ...] = ("diaphragm", "motor", "solenoid", "hydraulic",
                              "handwheel")


def actuated_variant(body: str, actuator: str) -> str:
    """The variant drawing *body* with *actuator* on it.

    Raises :class:`ValueError` naming every pairing that exists when
    this one does not, because the reader of that message is holding a
    body the stencil set draws and an actuator it draws and has no way
    to know which of the two is the reason.
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

#: The fail positions a valve may be declared in, and the letters each
#: one draws. The names are the plant's vocabulary and the letters are
#: the drawing's, kept apart for the reason ``normal_position="closed"``
#: is not spelled ``"NC"``.
#:
#: The letters are **ANSI/ISA-5.1-2009 Table 5.4.4** Method B. ``FO``,
#: ``FC`` and ``FL`` are the three ISA-5.1-1984 §6.7 already had;
#: ``FI``, *fail indeterminate*, is 1984's fourth and is kept because a
#: valve whose failed position genuinely cannot be predicted has to be
#: able to say so rather than claim ``FL``. ``FL/DO`` and ``FL/DC`` are
#: 2009's additions, *fail last* with the direction the valve then
#: drifts.
#:
#: Ordered so the error message naming them reads open, closed, then the
#: three that hold, rather than in dictionary order.
FAIL_POSITIONS: dict[str, str] = {
    "open": "FO",
    "closed": "FC",
    "last": "FL",
    "drift_open": "FL/DO",
    "drift_closed": "FL/DC",
    "indeterminate": "FI",
}

#: Valve variants that have motive power to lose, and so a fail position
#: to declare. **ANSI/ISA-5.1-2009** note 5.3.4(10) says the failure
#: symbols "are applicable to all types of control valves and
#: actuators", and that is the test: an *actuator*, driven by air,
#: hydraulic fluid or electricity supplied from outside the valve.
#:
#: Three groups are refused by it, for three different reasons.
#:
#: - A **hand-operated** valve has an operator but no actuator.
#:   ``manual`` draws a handwheel and ``knife`` a rising stem through
#:   one; a handwheel loses no air.
#: - A **self-acting** valve is powered by the process it sits in.
#:   ``regulator`` works off its own dome and ``relief`` and ``psv`` off
#:   a spring against line pressure, so there is no supply whose failure
#:   is the question.
#: - A **bare body** -- ``gate``, ``globe``, ``ball``, ``butterfly`` and
#:   the rest -- is drawn with no operator at all.
#:
#: Every entry is a pairing out of :data:`ACTUATED`, which is the whole
#: of the rule: a valve declares a fail position when the drawing puts a
#: powered actuator on it. ``manual`` is the one pairing left out,
#: because a handwheel is an operator and not an actuator.
#:
#: Every variant here is a two-port body. PIP PIC001 4.5.3.2(2) rules
#: multi-port valves out of the letters -- "for multi-port automated
#: valves, FL and FI shall be used where appropriate", with the comment
#: that "FO and FC shall not be used; instead, arrows shall be used to
#: show fail position flow paths" -- and this package draws no such
#: arrows. ``three_way`` is a bare body with no operator, so the
#: question does not arise today; an actuated multi-port variant added
#: later must not simply be added to this set.
FAIL_ACTUATED = frozenset({
    "control", "butterfly_pneumatic", "solenoid", "motor", "hydraulic",
})


def fail_marking(unit) -> str:
    """The letters an actuated valve's fail position is drawn with,
    ``""`` if none.

    One method, not two. **ANSI/ISA-5.1-2009 Table 5.4.4** offers Method
    A, arrows or bars on the actuator stem, and Method B, the letters;
    **PIP PIC001 clause 4.5.3.2** picks between them -- *"Automated
    valve fail actions shall be shown with text (FC/FO/FL/FI) in
    accordance with ISA-5.1"*, with the comment that *"using stem arrows
    as outlined in ISA-5.1 is not recommended"* -- and this follows PIP.
    See :attr:`pandid.units.Valve.fail`.

    The letters, unlike a darkened body, are the *whole* of the mark, so
    a valve keeps the drawing, the box and the nozzles it had before it
    was given a fail position.
    """
    declared = getattr(unit, "fail", "") or ""
    if not declared:
        return ""
    # The unit refuses an unactuated variant at construction; it can
    # still be reached by assigning ``variant`` afterwards, and drawing
    # nothing would be the silent failure -- a sheet issued with a trip
    # valve that says where it goes on a power failure in the model and
    # nowhere on the paper.
    if getattr(unit, "variant", "") not in FAIL_ACTUATED:
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: declared fail={declared!r}, but "
            f"variant {getattr(unit, 'variant', '')!r} has no actuator to lose its "
            f"motive power. The variants that take a fail position are: "
            f"{', '.join(sorted(FAIL_ACTUATED))}."
        )
    return FAIL_POSITIONS[declared]


#: The ink a darkened body is filled with -- the colour the vendored
#: valve artwork already strokes in, so the fill and the outline around
#: it are one solid symbol rather than a black shape in a grey frame.
_BODY_INK = "#111"

#: The body is the artwork's first ``<path>``. True of every variant in
#: :data:`NC_DARKENS` and checked rather than assumed, because
#: ``_vendored_symbols.py`` is generated: a stencil that grows a
#: foreground element ahead of its background one would otherwise have
#: the wrong shape filled, silently and plausibly.
_FIRST_PATH = re.compile(r"<path\b[^>]*>")

#: What that body is filled with before it is darkened: the paper a
#: stencil is converted on, as ``scripts/mxgraph_to_svg.DEFAULT_FILL``.
#: Darkening is that fill swapped for ink, so it is what the swap looks
#: for, and a body that does not carry it is not a body.
_BODY_PAPER = 'fill="white"'


def closed_marking(unit, registry=None) -> str:
    """How a unit's normally closed position is drawn, ``""`` when it is
    not one.

    ``"stencil"`` swaps in a second drawing the stencil author already
    made -- a spectacle blind's two states are two shapes. ``"fill"``
    darkens the body (PIP PIC001 4.2.2.7), and ``"NC"`` is the
    abbreviation written beside a valve whose body cannot carry the
    fill.

    The two markings come from two standards, because only one standard
    offers each. No ISO or ISA document fills a valve body; PIP PIC001
    4.2.2.7 is the source for that, and 4.2.2.10's prohibition on
    control and relief valves comes with it. The letters are the other
    way round: ISO 15519-1 §11.4.5 prescribes ``NC``/``NO`` "above the
    symbol and to the right" (Figure 28), so the letters and their
    placement are taken from there rather than from PIP PIC001 4.2.2.8,
    which puts them below.

    All three are one decision made in one place, so the renderer cannot
    letter a valve the registry has already darkened, or darken one it
    is about to letter. ``registry`` is the catalogue to answer against,
    since which devices have a second drawing is a fact about the
    symbols on hand.
    """
    if getattr(unit, "normal_position", "open") != "closed":
        return ""
    variant = getattr(unit, "variant", "")
    reg = default_registry if registry is None else registry
    if reg.closed_symbol(unit.kind, variant) is not None:
        return "stencil"
    # The fill and the abbreviation are the *valve* conventions of PIP
    # PIC001, so a closed anything-else whose variant has no second
    # drawing has no way to say so. The unit refuses that at
    # construction; it can still be reached by assigning ``variant``
    # afterwards, and drawing the open symbol would be the silent
    # failure -- an issued sheet showing a line as open when it is
    # blanked.
    if unit.kind != "valve":
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: {unit.kind}/{variant} is drawn one "
            f"way, so nothing can show it normally closed. Either it is the wrong "
            f"variant for a device that isolates a line, or normal_position should "
            f"be 'open'."
        )
    return "fill" if variant in NC_DARKENS else "NC"


def darkened(sym: Symbol) -> Symbol:
    """``sym`` with its body filled solid: the normally closed valve
    symbol.

    A separate ``Symbol`` rather than a fill applied at draw time,
    because the ``<defs>`` entry a ``<use>`` points at is keyed by the
    artwork: the open and the closed valve are two drawings and need two
    definitions, which is what the ``_nc`` :attr:`Symbol.id_suffix`
    buys. Everything else about the symbol -- box, nozzles, alternates,
    aspect -- is the same valve.
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
        # Same stencil, filled. The fill is what the derivation *is*, so
        # it travels with the reference; a reference on its own would
        # name the open valve and draw a line that is shut as one that
        # is not.
        drawio_shape=sym.drawio_shape, drawio_flip_h=sym.drawio_flip_h,
        drawio_fill=_BODY_INK,
    )


# ----------------------------------------------------------------
# The fitting piped the other way round.
#
# A reducer and an expander are one casting: a trapezoid between a large
# face and a small one, installed with the flow going into whichever end
# the line needs. The drawing has to say which, because the cone points
# downstream on one and upstream on the other, and a run drawn through
# the wrong one narrows where it should open out.
#
# It cannot be said with ``pin(mirrored="x")``. That mirror is applied
# to the ports as well as to the ink (portgeom.symbol_to_box), so it
# swaps the west and east faces and the run enters the fitting from
# downstream. The two have to move independently, which is what this
# derivation does: mirror the artwork, then put ``inlet`` back on the
# west face and ``outlet`` back on the east one. See
# :attr:`pandid.units.Reducer.large_end`.
# ----------------------------------------------------------------

#: The face a placement lands on after the artwork is mirrored
#: left-to-right. North and south are unmoved by it.
_FLIPPED_FACE = {"W": "E", "E": "W", "N": "N", "S": "S"}

#: A symbol's artwork, split into its opening ``<g>``, its contents and
#: its closing tag. Every symbol here is one group and nothing else, so
#: the two derivations that rewrite artwork -- :func:`expander`, which
#: mirrors it, and :func:`compose`, which paints parts over it -- can
#: reach the contents without parsing the SVG.
_GROUP = re.compile(r"\A(<g\b[^>]*>)(.*)(</g>)\Z", re.DOTALL)


def expander(sym: Symbol) -> Symbol:
    """``sym`` turned end for end: the same fitting, piped the other way
    round.

    The artwork is mirrored left-to-right so the cone points the other
    way, and the two process nozzles trade names, so ``inlet`` stays on
    the west face and ``outlet`` on the east and the run still passes
    through in the direction it was drawn in. Every placement keeps its
    exact coordinate, mirrored with the ink it was authored against, so
    a nozzle on drawn stroke stays on drawn stroke.

    A separate ``Symbol`` rather than a transform applied at draw time,
    for :func:`darkened`'s reason: the ``<defs>`` entry a ``<use>``
    points at is keyed by the artwork, so the reduction and the
    expansion need two definitions -- the ``_exp``
    :attr:`Symbol.id_suffix`.
    """
    swap = {"inlet": "outlet", "outlet": "inlet"}
    # Exactly the two, and no family: every nozzle has to be accounted
    # for, or turning the fitting would quietly drop the ones nothing
    # here knows how to move, and a symbol short of a nozzle draws a
    # stream to the middle of its own box.
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
    # Mirror about the box's own mid-line, so the drawing lands back in
    # the box it was drawn in and the placed geometry is unchanged.
    svg = (f'{head}<g transform="translate({sym.width:g},0) scale(-1,1)">'
           f'{body}</g>{tail}')

    def turn(xy: tuple[float, float]) -> tuple[float, float]:
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
        # Same stencil, mirrored -- which is the whole of the
        # derivation, and the whole of what has to travel with the
        # reference. Left off, an export would name the reduction and
        # draw a run narrowing where the sheet opens it out.
        drawio_shape=sym.drawio_shape, drawio_fill=sym.drawio_fill,
        drawio_flip_h=not sym.drawio_flip_h,
    )


# ----------------------------------------------------------------
# The body carrying its parts.
#
# Read the block above :class:`IsoPart` first: it says when a drawing may
# be composed at all. This is only the machinery for one that may.
# ----------------------------------------------------------------


@dataclass(frozen=True)
class OverlayPart:
    """One supplementary symbol's artwork, and the ISO item it is.

    A part is *only* combinable, never standalone: that is what makes it
    a supplementary symbol under ISO 14617-1 §3.3 rather than a basic one
    under §3.2. It is drawn in its own ``width`` x ``height`` box, with
    (0, 0) at the top-left exactly as a :class:`Symbol` is, and
    :func:`compose` maps that box onto whatever rectangle of the body's
    an :class:`Overlay` names.

    Args:
        name: pandid's spelling, and half the registry key --
            ``"turbine"``, where the standard says "Agitator, turbine
            type". Short, because it is what an author types.
        iso: The Table 2 row this drawing claims to be. Required; see
            :class:`IsoPart`.
        svg: A single ``<g>`` group, like a :class:`Symbol`'s. The
            wrapper is dropped when the part is painted onto a body, so
            its id is never emitted and only its contents are.
        width: The box the artwork is drawn in.
        height: The box the artwork is drawn in.
        ports: Connections the *part* brings with it, in the part's own
            coordinates. Almost always empty; see below.
        stretchable: May the artwork be scaled unevenly to fill the
            rectangle it is placed on? The same question
            :attr:`Symbol.stretchable` asks, with the same answer: a tray
            deck is a line and may be any length, an impeller and a
            manhole are shapes and may not be squashed. A part that says
            no is scaled evenly and centred on its rectangle, and it
            makes the whole composition unstretchable -- see
            :func:`compose`.
        gravity_fixed: Does this part state that gravity does the work?
            ISO 14617-1 §4.5 forbids turning a symbol where gravity is a
            functionality, and item 29.1 (C2028, the settling arrow) is
            that statement made as a part: a body carrying it must not be
            turned even when the bare body may be.
        directional: Does the artwork state a direction an axis flip
            would reverse? Same question :attr:`Symbol.directional` asks.
            The settling arrow is the case again -- flipped, it says the
            heavy phase rises.
        drawio_shape: The draw.io stencil that draws this part on its
            own, where one exists (the stencil set ships ``Prop
            Agitator`` and ``Turbine Agitator`` as exactly this kind of
            drop-on overlay). Empty where the part has to be exported as
            geometry.

    Ports: what a part does and does not contribute
    ----------------------------------------------
    **An agitator brings a connection; an internal and a characteristic
    do not.** That is not a convenience, it is what the standard draws.
    ISO item 1.27 (X8006, "jacketed vessel with dished ends and agitator
    driven by electric motor") draws the stirrer's shaft running up
    through the top head to a circle marked ``M`` sitting *above* the
    vessel -- itself item 20.6, C0082, "electric motor (general)". The
    drive is a real connection at a real place on the drawing, so the
    part that draws it anchors a nozzle there. A tray (group 27) and a
    characteristic (group 29) are marks inside a body that no line ever
    reaches, and they anchor nothing.

    A part's ports are **added** to the body's, never substituted for
    them: :func:`compose` refuses a part whose nozzle name the body
    already anchors, because two nozzles under one name is a stream drawn
    to whichever the dict happened to keep.

    That leaves the port coherent with the unit layer without any special
    case. A symbol anchoring a nozzle its unit does not declare is
    already ordinary here -- the anchor is simply never asked for -- so a
    body composed with an agitator draws the drive and a
    :class:`~pandid.units.Unit` that has no ``drive`` in its ``PORTS``
    connects nothing to it. The unit half is the other side of the same
    change and is declared where every other nozzle is: in ``PORTS``, or
    in a ``_VARIANT_PORTS`` table for a nozzle only some variants have.
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
        """The registry key: ISO subject group, then pandid's name."""
        return (self.iso.group, self.name)


# The twin of ``pandid.render.svg._at_pen_scale``, which cannot be
# imported here because that module imports this one. Kept private and
# small rather than shared through a third module: the two are four lines
# of the same regex substitution and the coupling would cost more than
# the duplication.
_STROKE = re.compile(r'stroke-width="([\d.]+)"')


def _at_part_scale(svg: str, scale: float) -> str:
    """*svg* with every line weight in it divided by *scale*.

    ISO 14617-1 §4.3, a ``shall``: "When the size of a symbol is changed,
    the line width shall be unchanged." A part painted onto a body is
    scaled to the rectangle it was given, and the transform would carry
    its strokes with it -- a tray deck placed at a fifth of the body's
    height drawn at a fifth of the weight its author chose. Dividing
    first is what leaves the drawn weight the one the part declares.

    Every weight, not only the outline: a part's own fine detail is drawn
    at a deliberate fraction of the sheet weight and the scale swells all
    of them alike.
    """
    if math.isclose(scale, 1.0, rel_tol=1e-9):
        return svg
    return _STROKE.sub(
        lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"', svg)


def compose(body: Symbol, parts: "list[tuple[Overlay, OverlayPart]]",
            iso_reg: str = "") -> Symbol:
    """``body`` with its supplementary parts painted over it.

    One :class:`Symbol` out, so nothing downstream learns a second kind
    of drawing: a composition is placed, resized, mirrored, exported and
    cached exactly as a whole symbol is, and the renderer never asks
    whether it was composed. That is the same choice :func:`darkened` and
    :func:`expander` make, for the same reason -- the ``<defs>`` entry a
    ``<use>`` points at is keyed by the artwork, so a body with parts and
    the bare body are two drawings and need two definitions.

    Each part is mapped from its own box onto the rectangle of the body's
    box its :class:`Overlay` names. Because the rectangle is stated as
    *fractions*, the mapping is re-done nowhere: the placement is already
    proportional, so stretching the finished symbol into a unit's box
    carries the parts with the body and a tray three-tenths down the
    shell stays three-tenths down it.

    What the parts decide about the whole
    -------------------------------------
    - **Stretchable** only if the body and every part is. A part that may
      not be reshaped is scaled evenly and centred on its own rectangle
      here, which handles the composition at its own size -- but the
      renderer stretches the *finished* symbol as one drawing, and there
      is no way to hold one group still inside a group that is being
      stretched. Refusing the stretch for the whole symbol is the only
      answer that keeps an impeller round, and it costs the body nothing
      it was entitled to: ISO 14617-1 §4.4 bounds reshaping by "shall not
      make it impossible to recognize the symbol", and an impeller drawn
      as a smear is exactly that.
    - **Gravity-fixed** and **directional** if the body or any part is.
      Both are statements the artwork makes, and a part makes them as
      readily as a body: item 29.1's settling arrow says the heavy phase
      goes *down*, so a body carrying it may not be turned (ISO 14617-1
      §4.5) and may not be flipped without drawing the opposite claim.

    The box, and parts drawn outside the body
    -----------------------------------------
    The composed box is the union of the body's and every part's. A part
    inside the body leaves it exactly the body's box, which is the common
    case and costs nothing. A part hanging off it grows the box and
    shifts everything into it, which is what ISO item 1.27 (X8006) needs:
    the drive motor is drawn above the top head, so the vessel is no
    longer the whole drawing and the nozzles have to move down with it.

    draw.io
    -------
    The composed symbol carries no ``drawio_shape``. A stencil reference
    names *one* shape and draw.io draws whatever that name resolves to,
    so a composed reactor exported under its body's reference would come
    out as a bare vessel -- the right outline, silently missing the thing
    that made it a reactor. Naming nothing is what makes the two backends
    disagree loudly instead of quietly.

    What the exporter reads instead is :attr:`Symbol.overlays` for the
    parts and :attr:`Symbol.drawio_body_shape` for the outline under
    them, and it emits **one cell per part, grouped under the body's**.
    The body's reference is carried across to that second field rather
    than dropped, because it is still true of the body -- and stating it
    under a name that says "body" is what keeps it from being read as a
    statement about the whole drawing.
    """
    match = _GROUP.match(body.svg)
    if match is None:
        raise ValueError(
            f"{body.symbol_id()}: cannot carry a part -- its artwork is not a "
            f"single <g> group to compose into"
        )
    head, inner, tail = match.groups()

    # Where each part lands, in the body's own coordinates, before the
    # box is squared up below.
    placed = []
    for overlay, part in parts:
        rx, ry = overlay.x * body.width, overlay.y * body.height
        rw, rh = overlay.w * body.width, overlay.h * body.height
        sx, sy = rw / part.width, rh / part.height
        if not part.stretchable:
            # The letterbox pandid.portgeom.ink_box applies to a whole
            # symbol, applied to a part on its rectangle: keep the
            # aspect, take the smaller scale, centre what is left over.
            scale = min(sx, sy)
            rx, ry = rx + (rw - scale * part.width) / 2, ry + (rh - scale * part.height) / 2
            sx = sy = scale
        placed.append((part, rx, ry, sx, sy, overlay.mirror))

    xs = [0.0, body.width]
    ys = [0.0, body.height]
    for part, rx, ry, sx, sy, _ in placed:
        xs += [rx, rx + sx * part.width]
        ys += [ry, ry + sy * part.height]
    # The shift that puts the union's top-left corner back on the origin.
    # Zero whenever every part is inside the body, which is when the
    # composed drawing is the body's own box and no wrapper is emitted.
    # The ``+ 0.0`` is not decoration: negating a zero gives ``-0.0``,
    # which formats as ``-0`` and would put a minus sign in the emitted
    # SVG of every composition that needed no shift at all.
    ox, oy = -min(xs) + 0.0, -min(ys) + 0.0
    width, height = max(xs) + ox, max(ys) + oy

    art = [inner if (ox, oy) == (0.0, 0.0)
           else f'<g transform="translate({ox:g},{oy:g})">{inner}</g>']
    for part, rx, ry, sx, sy, mirror in placed:
        contents = _GROUP.match(part.svg).group(2)  # type: ignore[union-attr]
        # A mirrored part is reflected about its rectangle's own vertical
        # centre line, so the reflection stays inside the rectangle it
        # was given rather than swinging across the body. Written as a
        # translate to the rectangle's *right* edge and a negative x
        # scale, which is the same two numbers the port below is mapped
        # through.
        left = rx + ox + (sx * part.width if mirror else 0.0)
        # One number for a stroke that has two scales: the geometric mean
        # is what pandid.render.svg._pen_scale settles an uneven
        # placement with, and a part scaled unevenly is the same
        # question. A part that may not be reshaped never reaches it --
        # its two scales were made equal above. The mirror contributes no
        # magnitude, hence the absolute value.
        art.append(
            f'<g transform="translate({left:g},{ry + oy:g}) '
            f'scale({-sx if mirror else sx:g},{sy:g})">'
            f'{_at_part_scale(contents, math.sqrt(abs(sx * sy)))}</g>'
        )

    def shift(xy: "tuple[float, float]") -> "tuple[float, float]":
        return (round(xy[0] + ox, 4), round(xy[1] + oy, 4))

    ports = {name: shift(xy) for name, xy in body.ports.items()}
    # A nozzle comes out of whichever face of its box it is nearest
    # (:func:`pandid.portgeom.outward_dir`), so growing the box can move
    # one onto a face it was never drawn for: a relief on the crown of a
    # vessel, a quarter of the way across it, is nearer the top of the
    # vessel's own box and nearer the *side* of a box grown to hold a
    # drive motor above it. The stream would then leave sideways through
    # the shell wall. Refused here rather than by the constructor, whose
    # message is about the coordinate and cannot mention the part that
    # moved it.
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
            # Through the same transform the artwork went through, so a
            # nozzle on a mirrored part stays on the ink it was drawn on.
            along = (part.width - px) if mirror else px
            ports[name] = (round(rx + ox + sx * along, 4), round(ry + oy + sy * py, 4))

    return Symbol(
        svg=head + "".join(art) + tail,
        width=round(width, 4), height=round(height, 4),
        ports=ports,
        # The body's authored menu, moved with the ink it was authored
        # against, so a nozzle the layout engine chose to move to another
        # face still lands on drawn stroke. Every entry in it has already
        # been checked against the composed box above.
        port_faces={name: {face: shift(xy) for face, xy in menu.items()}
                    for name, menu in body.port_faces.items()},
        faceless_ports=body.faceless_ports, port_series=body.port_series,
        label_pos=body.label_pos,
        # A definition per composition, on darkened()'s and expander()'s
        # rule. Digested rather than spelled out because a tray column is
        # thirty overlays and an id is read by a person: four bytes of
        # blake2s is short, and stable across processes in a way hash()
        # is not, which matters because this lands in the emitted SVG and
        # the golden fixtures compare it byte for byte.
        id_suffix=body.id_suffix + "_c" + hashlib.blake2s(
            repr([o for o, _ in parts]).encode(), digest_size=4).hexdigest(),
        stretchable=body.stretchable and all(p.stretchable for p, *_ in placed),
        bare_run=body.bare_run,
        gravity_fixed=body.gravity_fixed or any(p.gravity_fixed for p, *_ in placed),
        directional=body.directional or any(p.directional for p, *_ in placed),
        # Deliberately not the body's; see the docstring. The body's own
        # reference moves to the field that says it is the body's, which
        # is where the exporter looks for it.
        drawio_shape="",
        drawio_body_shape=body.drawio_shape or body.drawio_body_shape,
        drawio_flip_h=body.drawio_flip_h, drawio_fill=body.drawio_fill,
        overlays=tuple(overlay for overlay, _ in parts),
        # *Not* the body's. A composition is a different symbol from the
        # thing it was composed onto, so carrying the body's number
        # forward would claim a stirred tank is a plain vessel -- the
        # exact false identity :class:`IsoPart`'s rule exists to stop.
        # Where the composition reproduces a tabulated symbol example it
        # has a number of its own -- a body carrying item 29.2 is
        # X8125 -- and the caller that knows which one states it.
        iso_reg=iso_reg,
    )


#: ISO 10628-2 Table 2's separating vessel: the outline every group-8 row
#: except the cyclone is drawn on, with nothing inside it.
#:
#: **Measured off Table 2 item 8.3, in grid modules:** walls at x 9 and
#: 15, top edge at y 1, walls down to y 7, then (9,7) -> (12,10) ->
#: (15,7). A 6 M x 6 M rectangle over a 3 M V, 6 M x 9 M overall. The
#: draw.io separator stencils are all 80 x 120 with the shoulder at 80,
#: which is that ratio exactly -- so a composed separator lands on the
#: same outline as the five that stay vendored whole, and a sheet
#: carrying both reads as one family.
#:
#: **Not registered as a variant**, deliberately. The bare outline is not
#: a tabulated symbol: ISO's general separator is item 8.1 X8081, which
#: draws a fork of two arrows inside this outline, so offering the empty
#: body under a variant name would put a symbol in the catalogue that the
#: standard does not have. It is a body, and the only things built on it
#: are the three compositions in
#: :meth:`SymbolRegistry._register_composed`.
_SEPARATING_VESSEL = Symbol(
    svg='<g id="sym_separator_vessel">'
        '<path d="M 0 0 L 80 0 L 80 80 L 40 120 L 0 80 Z" '
        'fill="white" stroke="#111" stroke-width="2"/></g>',
    width=80.0, height=120.0,
    # The anchors the four mechanical separators already use, coordinate
    # for coordinate: the feed high on the west wall, the high draw
    # opposite it, the collected phase out of the apex.
    ports={"feed": (0.0, 12.0), "vapor": (80.0, 12.0), "liquid": (40.0, 120.0)},
    # A hopper collects out of its apex; turned, the apex is a roof and
    # nothing falls into it. Every group-8 drawing in the library is
    # fixed for this reason -- ISO 15519-1 §11.4.2's exception.
    gravity_fixed=True,
)


class SymbolRegistry:
    def __init__(self):
        self._symbols: dict[tuple[str, str], Symbol] = {}
        # Darkened bodies, built once each on demand. Port resolution
        # asks for a unit's symbol on every call, so a derived symbol
        # has to be shared the way a fixed one is or every nozzle lookup
        # rebuilds the artwork.
        self._darkened: dict[tuple[str, str], Symbol] = {}
        # Second drawings, for the devices the stencil set draws in two
        # positions. Not a variant: one (kind, variant) with two states,
        # and which is drawn comes off the unit's ``normal_position``.
        self._closed: dict[tuple[str, str], Symbol] = {}
        # Fittings turned end for end, built once each on demand and
        # shared for the same reason the darkened bodies are.
        self._expanders: dict[tuple[str, str], Symbol] = {}
        # The supplementary symbols of ISO 10628-2 groups 26-29, keyed by
        # (group, name). Empty until the artwork is drawn: the mechanism
        # ships before the glyphs do, so that the first part added is a
        # drawing and nothing else.
        self._parts: dict[tuple[int, str], OverlayPart] = {}
        # Bodies with their parts on, built once per (kind, variant,
        # overlays) and shared. Port resolution asks for a unit's symbol
        # on every call and a tray column is thirty parts to paint, so a
        # composition that is rebuilt per lookup is rebuilt thousands of
        # times per sheet.
        self._composed: dict[tuple, Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol, variant: str = "default") -> None:
        self._symbols[(kind, variant)] = template
        self._darkened.pop((kind, variant), None)
        self._closed.pop((kind, variant), None)
        self._expanders.pop((kind, variant), None)
        for key in [k for k in self._composed if k[:2] == (kind, variant)]:
            del self._composed[key]

    def register_part(self, part: OverlayPart) -> None:
        """Register one ISO group 26-29 supplementary symbol.

        Keyed by ``(group, name)``, so the ISO subject group is part of
        the identity rather than a note about it: a tray is a group-27
        internal and an agitator a group-28 stirrer, and a name is only
        unique inside its group.

        Read the block above :class:`IsoPart` before adding one. A part
        is justified by the standard composing at that point, and the
        registration number it carries is what lets that be checked.
        """
        self._parts[part.key()] = part
        # Every composition, since any of them may have used this part.
        # Registering a part is a startup act, so there is nothing to
        # save by being clever about which.
        self._composed.clear()

    def part(self, group: int, name: str) -> OverlayPart:
        """The supplementary symbol registered as ``(group, name)``."""
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
        """Every part registered in one ISO subject group, A-Z."""
        return sorted(name for (g, name) in self._parts if g == group)

    def parts(self) -> list[OverlayPart]:
        """Every registered supplementary symbol, by group then name."""
        return [self._parts[key] for key in sorted(self._parts)]

    def composed(self, kind: str, variant: str = "default",
                 overlays: "tuple[Overlay, ...]" = ()) -> Symbol:
        """``(kind, variant)`` carrying ``overlays``, built once.

        The whole resolution: a body from :meth:`get`, a part per overlay
        from :meth:`part`, and :func:`compose` to paint them. No overlays
        gives the body back unchanged, which is the zero case every
        symbol the registry ships is in, and it does not go near the
        cache -- there is nothing to build.
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
        """The drawing for ``(kind, variant)`` declared normally closed.

        For a device whose closed state is a *shape of its own* rather
        than a fill applied to the open one: a spectacle blind is two
        discs and the solid one is whichever is in the line. Registered
        against the same ``(kind, variant)`` as :meth:`register`, so the
        closed state never becomes a second variant name for one device,
        and always after it, since re-registering the open drawing drops
        the pairing.
        """
        if (kind, variant) not in self._symbols:
            raise ValueError(
                f"{kind}/{variant} has no open drawing to be the closed state of; "
                f"register() it first"
            )
        self._closed[(kind, variant)] = template

    def closed_symbol(self, kind: str, variant: str = "default") -> Symbol | None:
        """``(kind, variant)``'s normally closed drawing, or None."""
        return self._closed.get((kind, variant))

    def closed_variants(self, kind: str) -> list[str]:
        """Every variant of a kind drawn in two positions, A-Z."""
        return sorted(variant for (k, variant) in self._closed if k == kind)

    def for_unit(self, unit) -> Symbol:
        """The symbol to draw ``unit`` with, built to its size where it
        has one.

        :meth:`get` answers for a ``(kind, variant)``, which is
        everything a fixed drawing depends on. A conveyor's artwork
        depends on the unit as well, since it is made to its belt run,
        and a valve's or a blind's on whether it is declared normally
        closed -- which darkens the one and swaps the other for the
        second shape its stencil set draws; a reducer's on which end its
        large face is, which turns the fitting end for end. The lookup
        still runs in every case, so a variant name nobody registered is
        still rejected.

        A unit may also name **supplementary parts** to be drawn on its
        body -- an agitator in a reactor, trays in a column. Nothing sets
        them today, so every unit takes the empty tuple and the drawing
        it has always had.

        The three derivations below are disjoint from composition rather
        than ordered against it. A normally closed valve and a fitting
        piped backwards are two of them, and neither kind composes: a
        valve is a registered symbol of ISO group 21, and a body carrying
        an internal has no normal position to show.
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
        # A reduction is the drawing as vendored; an expansion is that
        # same fitting piped the other way round. See :func:`expander`.
        if getattr(unit, "large_end", "inlet") == "outlet":
            key = (unit.kind, variant)
            if key not in self._expanders:
                self._expanders[key] = expander(sym)
            return self._expanders[key]
        return sym

    def variants(self, kind: str) -> list[str]:
        """Every variant registered for a kind, ``default`` then A-Z."""
        names = [variant for (k, variant) in self._symbols if k == kind]
        return sorted(names, key=lambda name: (name != "default", name))

    def get(self, kind: str, variant: str = "default") -> Symbol:
        if (kind, variant) in self._symbols:
            return self._symbols[(kind, variant)]
        known = self.variants(kind)
        if not known:
            # A kind with no artwork at all -- a Unit subclass from
            # outside this package -- draws a generic box, and there is
            # no catalogue to hold its variant against. Only a kind that
            # *has* a catalogue can be said to lack a name from it.
            return self._generic_symbol()
        # A name no symbol answers to is a typo, and drawing the kind's
        # default in its place is silent by construction: the sheet
        # comes out looking right, so nothing downstream is ever in a
        # position to say the symbol the author asked for does not
        # exist.
        close = get_close_matches(variant, known, n=1, cutoff=0.6)
        suggestion = f" (did you mean {close[0]!r}?)" if close else ""
        raise ValueError(
            f"{kind} has no variant {variant!r}{suggestion}; "
            f"registered {kind} variants: {', '.join(known)}"
        )

    def _generic_symbol(self) -> Symbol:
        svg = (
            '<g id="sym_generic">'
            '<rect x="0" y="0" width="60" height="60" fill="none" stroke="black" stroke-width="2" />'
            '</g>'
        )
        return Symbol(svg=svg, width=60, height=60)

    def _register_defaults(self):
        # Feed / Product: rendered dynamically in svg.py, these are
        # fallbacks
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

        # The equipment symbols below are fallbacks: the vendored
        # registry at the bottom of this method registers over every one
        # of them, so none is what a sheet draws today, and their
        # geometry notes describe them rather than the artwork in use.
        # The Mixer, the Splitter and the pipe tee are the exceptions;
        # there is no stencil for any of the three.

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
        

        # Mixer: standard triangle pointing right All inputs on the left
        # flat face, output at right vertex
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
            ports={'inlet': (0.0, 15.0), 'outlet': (40.0, 15.0)}
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
        

        # Belt conveyor: registered at its default length. A conveyor of
        # any other length gets its own symbol from for_unit(); see
        # conveyor_symbol.
        self.register("conveyor", conveyor_symbol())

        # Pipe tee: the junction where a line branches.
        #
        # Drawn as the pipe and nothing else. On the reference sheet
        # P&ID-301 the CV-303 station's four junctions are all three
        # lines meeting: no dot, circle or fitting symbol at any of
        # them, and every stroke 0.75 pt, the same weight as the run. So
        # the branch is pipe and is drawn as pipe.
        #
        # The run goes straight across at mid-height and the branch stub
        # from the centre down to the south face. The two run nozzles
        # share one centreline, which keeps the main run from kinking
        # through the junction. The box is small because a tee has no
        # size -- it is a point on the line -- and only large enough
        # that the stub reads as a spur at the 2-unit process stroke.
        #
        # An original primitive rather than a stencil: the draw.io P&ID
        # set draws no bare junction. See NOTICE section 1.
        self.register("tee", Symbol(
            svg='<g id="sym_tee">'
                '<path d="M 0 6 L 12 6 M 6 6 L 6 12" fill="none" stroke="black" '
                'stroke-width="2"/>'
                '</g>',
            width=12.0, height=12.0,
            ports={"inlet": (0.0, 6.0), "outlet": (12.0, 6.0), "branch": (6.0, 12.0)},
            # A tee is labelled nowhere, so it has no side to keep clear
            # for a tag. "center" stops the layout engine reserving one
            # and the router standing its lines off to clear it.
            label_pos="center",
            # ...and for the same reason there is nothing for an
            # arrowhead to land against: the run divides and carries on.
            bare_run=True,
        ))

        # Block flow diagram box: a plain labelled rectangle.
        #
        # Registered at the shape a Block asked for by name is drawn in
        # -- one connection in on the west, one out on the east -- which
        # is what the registry answers for a (kind, variant) and what
        # the symbol sheet and the invariant suite measure. A block with
        # any other set of connections gets its own drawing from
        # for_unit(); see block_symbol().
        self.register("block", block_symbol((("in_1", "W"), ("out_1", "E"))))

        # Splitter: standard triangle with point on left, flat on right
        # All outputs on the right flat face, input at left vertex
        self.register("splitter", Symbol(
            svg='<g id="sym_splitter"><polygon points="0,25 50,0 50,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'inlet': (0.0, 25.0)},
            port_series=(PortSeries("out_", "E"),),
        ))

        # ISA-5.1 instrument bubbles. The tag text is drawn dynamically
        # from the unit name by the renderer, so the symbol is just the
        # balloon + its location bar. Ports: pv (process connection,
        # bottom), in/out (signals). Variants: default (bare field
        # balloon), panel (single bar), aux (double bar), shared
        # (balloon-in-square + single bar = DCS/shared display),
        # computer (hexagon), sis / logic (diamond-in-square = safety
        # instrumented system), interlock (plain diamond = interlock
        # logic function). A balloon is a circle: a signal can meet it
        # anywhere, so every connection offers all four faces and none
        # of them owns one. The coordinates are one unit clear of the
        # r=21 circle, matching the nozzle stub used everywhere else.
        _inst_faces = {"N": (22.0, 0.0), "S": (22.0, 44.0),
                       "W": (0.0, 22.0), "E": (44.0, 22.0)}
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        # Every connection offers every face, so none of them owns one:
        # the menus overlap on purpose, which is what faceless_ports
        # declares.
        _inst_menu = {name: dict(_inst_faces) for name in _inst_ports}
        _inst_faceless = frozenset(_inst_ports)
        # None of them stretches. ISA-5.1 balloons are *circles*, and
        # the square, the hexagon and the interlock box are read against
        # that circle: an oval bubble is not a bubble drawn wide, it is
        # a different symbol, and a squashed hexagon stops being the one
        # that means "computer function". Sized off their own
        # proportions they keep them and are centred in the box, which
        # is what makes a balloon a balloon at any width the author asks
        # for.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_panel"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="22" x2="43" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False), "panel")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_aux"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="19" x2="43" y2="19" stroke="black" stroke-width="1.5"/><line x1="1" y1="25" x2="43" y2="25" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False), "aux")
        # The bar is issue #181. ISO 15519-2 Table 1 (p. 7) tabulates
        # the *additional graphic* a PCI symbol carries: "None:
        # Information available on field mounted instrument/display",
        # "Horizontal single full line: Information available in central
        # control system", "Horizontal double full line: ... subsidiary
        # control system". A shared display *is* the central control
        # system, so a squared balloon with no bar states the one thing
        # about it that is certainly false.
        #
        # `professional_examples/P&ID_301.pdf` settles the geometry: all
        # forty of its balloons carry a bar, twelve of them
        # circle-in-square, and on every one the bar runs the circle's
        # full diameter through the exact vertical centre -- 17,01 pt of
        # bar on a 17,01 pt circle -- with the letters wholly above it
        # and the number wholly below, which is where ISO 15519-2 5.1.2
        # puts them. So the bar spans the *circle*, 2..42, and not the
        # square around it; the square is a second statement, about what
        # the instrument does rather than where it is.
        #
        # 1,5 and not the outline's 2, which is this package's weight
        # for a location bar rather than that sheet's: `panel` and `aux`
        # above are drawn that way. P&ID_301 draws bar and outline at
        # one weight (0,24 pt each).
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/><line x1="2" y1="22" x2="42" y2="22" stroke="black" stroke-width="1.5"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # The hexagon's flat bottom is at y=41, not y=43 like the
            # circular variants, so pv needs its own coordinate to keep
            # the same 1-unit nozzle stub instead of floating 3 units
            # clear of the outline.
            width=44.0, height=44.0, label_pos="center", stretchable=False,
            faceless_ports=_inst_faceless,
            ports={**_inst_ports, "pv": (22.0, 42.0)},
            # the hexagon is flat-topped at y=3 and flat-bottomed at
            # y=41, so N and S need their own stubs; the side vertices
            # sit where the circles do.
            port_faces={n: {**_inst_faces, "N": (22.0, 2.0), "S": (22.0, 42.0)}
                        for n in _inst_ports}), "computer")
        # The two trip / logic squares, hung under the instrument they
        # act on. ANSI/ISA-5.1-2009 draws these as two *different*
        # symbols and the package carries both:
        #
        #   Table 5.1.2 items 3-5  a plain diamond           interlock
        #   Table 5.1.1 column B   a diamond inside a square sis/logic
        #
        # The plain diamond is the generic interlock logic function. The
        # diamond-in-square is the safety-instrumented-system /
        # alternate-choice instrument symbol, and it is what an issued
        # sheet draws for a trip: every occurrence on the reference
        # P&ID-301 is diamond-in-square.
        #
        # ``logic`` is retained as a second name for the
        # diamond-in-square: it is the name the package shipped, the one
        # every drawing already authored uses, and the one `Instrument`
        # keys its repeat rule on. It is a package spelling of ``sis``
        # rather than a claim about Table 5.1.2.
        #
        # Both are drawn in a 40 box. An inscribed diamond has half its
        # square's area and all of that loss is taken out of the corners
        # a number's corners occupy, so the square has to grow by root
        # two -- 28 * 1.414 = 39.6 -- for a two-figure number to sit
        # inside the diamond with the clearance it had inside the
        # square. 40 also lands just inside the 44 balloon, which is the
        # relationship a real sheet draws: on P&ID-301 the trip square
        # and the balloons are both 17.0 pt, cut to one module.
        #
        # The three ports need no adjusting: the midpoint of each side
        # of the box is where the diamond's vertices are.
        _logic_ports = {'pv': (20.0, 39.0), 'sig_in': (1.0, 20.0), 'sig_out': (39.0, 20.0)}
        # One Symbol registered under two names, so the two spellings
        # cannot drift apart. The ``<defs>`` id still follows the
        # spelling, since that is what the renderer keys a definition
        # by; a sheet using both would carry the same drawing twice,
        # which is harmless and vanishingly rare.
        _sis = Symbol(
            svg='<g id="sym_instrument_sis">'
                '<rect x="1" y="1" width="38" height="38" fill="white" stroke="black" stroke-width="2"/>'
                '<polygon points="20,1 39,20 20,39 1,20" fill="none" stroke="black" stroke-width="2"/>'
                '</g>',
            # A diamond on the square's diagonals is as much a shape
            # that carries meaning as the balloon's circle: stretched to
            # a box of another proportion its vertices leave the sides'
            # midpoints, which is where all three ports sit.
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports)
        self.register("instrument", _sis, "sis")
        self.register("instrument", _sis, "logic")
        # The plain diamond fills its own outline: nothing is drawn
        # behind it to show through, and a white body keeps a line it is
        # dropped on from striking through the interlock number.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_interlock">'
                '<polygon points="20,1 39,20 20,39 1,20" fill="white" stroke="black" stroke-width="2"/>'
                '</g>',
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports),
            "interlock")

        # The tubular reactor: a PFR, and the one reactor that is not a
        # vertical vessel. ISO 10628-2 has no reactor group and no
        # tubular-reactor symbol -- group 1 is vessels, and none of them
        # is a horizontal shell with a tube pass in it -- so this is
        # built to item 3.7's construction instead (reg 2514, "heat
        # exchanger with coil-shaped tubes"), which is the nearest thing
        # the standard does draw: a shell with a serpentine tube inside
        # it. A PFR is a jacketed tube, so that is the right ancestor.
        #
        # 12 M x 4 M, and the shell is a plain rectangle rather than the
        # dished cylinder every vertical vessel here is. Both walls are
        # then straight for their whole height, which is what a charge
        # nozzle down the west face needs: on a dished end only the apex
        # is on the box edge, so a second feed would land in the air
        # beside the head.
        #
        # The tube pass is drawn at ``iso_parts.PART_STROKE``, the
        # in-line detail weight ISO 10628-1:2014 §5.3.1 c) rules the
        # internals of a symbol at, against the outline's §5.3.1 b).
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

        # Vendored draw.io symbols (Apache-2.0): registered last so they
        # override the hand-drawn defaults for shared kinds and add
        # variants.
        from pandid.render._vendored_symbols import register_vendored
        register_vendored(self)

        # The ISO 10628-2 groups 26-29 supplementary symbols. Not
        # symbols: a part is only ever combinable and lives in its own
        # namespace, so registering them adds nothing to the catalogue
        # and changes no drawing. Registered after the whole symbols
        # because a part is only ever overlaid on one.
        from pandid.render.iso_parts import register_parts
        register_parts(self)
        self._register_composed()

    def _register_composed(self):
        """The three drawings ISO composes and gives a number of its own.

        Two kinds of composition ship. One the **author** configures --
        which agitator, how many trays -- is built per unit from the
        keywords on :class:`~pandid.units.Reactor` and its siblings, and
        cannot be enumerated here because the combinations are the point.
        The other is a composition the **standard itself** tabulates as a
        symbol example with a registration number, and that one has a
        fixed answer, so it belongs in the registry where every other
        fixed drawing is.

        Three of them, all in ISO 10628-2 group 8, all one separating
        vessel (:data:`_SEPARATING_VESSEL`) carrying one group-29
        characteristic:

        =====  ======  ==============================================
        item   reg     body + part
        =====  ======  ==============================================
        8.3    X8031   separating vessel + 29.1 C2028 gravity
        8.6    X8125   separating vessel + 29.2 C2030 electrostatic
        8.8    X8126   separating vessel + 29.3 C2031 electromagnetic
        =====  ======  ==============================================

        The five group-8 drawings pandid ships beside them stay vendored
        whole, because ISO gives each a distinct registered symbol and
        group 29 has nothing to build them out of: **no vortex** (8.10
        X2618, the cyclone -- which ISO 14617-1 §4.5 names by number as a
        symbol in its own right), no baffle (8.2 X2616), no spray (8.5
        X2621, and so not 8.7 X8033 either) and no permanent magnet (8.9
        X8127). Item 8.4's wet scrubber would need item 29.10's double
        arc, which is not drawn yet.

        The cost, stated because it is real: the three lose their draw.io
        stencils. Each of the three *is* a stencil in draw.io's P&ID set,
        but the outline underneath them is not, so the exporter draws the
        body as a rectangle with the mark as a child cell rather than as
        the shape draw.io has for the pair. Naming the whole-composition
        stencil here instead would put a ``drawio_shape`` on a composed
        symbol, which is the one thing :func:`compose` refuses -- and the
        refusal is what stops a *body's* reference being reused for a
        body-plus-parts drawing, which is the far commoner and far
        quieter error.
        """
        from pandid.render.iso_parts import characteristic_overlays

        for name, reg in (("gravity", "X8031"), ("electrostatic", "X8125"),
                          ("electromagnetic", "X8126")):
            # ``registry=self``: this runs inside ``__init__``, so the
            # module's ``default_registry`` the helper would otherwise
            # ask is the object still being built.
            overlays = characteristic_overlays(name, registry=self)
            self.register("separator", compose(
                _SEPARATING_VESSEL,
                [(o, self.part(o.group, o.name)) for o in overlays],
                iso_reg=reg,
            ), name)


default_registry = SymbolRegistry()
