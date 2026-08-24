"""ISO 10628-2:2012 Table 2's supplementary symbols, and one drive.

Groups 1-25 of Table 1 name whole apparatus. Groups **26 apparatus
elements, 27 internals, 28 agitators and 29 internal characteristics**
are the *parts* those apparatus are built out of, and clause 5 makes
composing from them a ``shall`` for any symbol the standard does not
tabulate. :mod:`pandid.render.symbols` has the mechanism -- ``IsoPart``,
``Overlay``, ``OverlayPart`` and ``compose`` -- and this module is the
artwork it was waiting for.

**And item 20.6, the electric motor**, which is not a part at all: group
20 is DRIVES, whole machines. It is here because ISO composes it itself.
Item 1.27 X8006 is a jacketed vessel with a group-28 stirrer *and* a
motor drawn above the top head on the stirrer's own shaft, and the
standard registers that composition as a symbol. See
``symbols.COMPOSED_APPARATUS`` for the admission and how narrow it is.

The bottom of this file is the other half: **where each part goes on a
body**, as fractions of that body's box. ``Reactor(agitator=)``,
``Column(internals=)``, ``Vessel(supports=)`` and
``Separator(characteristic=)`` all end in one of the four helpers there,
because "an agitator hangs from the top head with its blade low in the
liquid" is a fact about the equipment and not about any one unit class.

Provenance
----------
**Original artwork, built to the standard's stated construction.** The
figures in ISO 10628-2 are the document and are protected; the
construction they specify is not, and building to it is the point of a
standard. Every part below was drawn from measurements read off Table 2
in grid modules -- how many modules wide the mark is, where its ends
land, which lines are dashed and at what pitch -- and then re-drawn here
on pandid's own grid. No path was traced, copied or converted from the
document.

The grid
--------
ISO 14617-1:2025 §4.3 and ISO 10628-2 clause 5 both put the artwork on a
**2,5 mm dotted grid**, and every vertex of every Table 2 symbol lands on
it. :data:`M` is that module in drawing units, so a coordinate of ``40``
below reads as "four modules" and can be checked against the standard by
counting dots.

Line weight
-----------
:data:`PART_STROKE` is **1 unit**, half the 2 units
``pandid.render.svg._SYMBOL_STROKE`` rules an equipment outline at. That
is ISO 10628-1:2014 §5.3.1's split, not a stylistic preference: §5.3.1 b)
puts *graphical symbols for equipment and machinery* at 0,5 mm and
§5.3.1 c) puts *valves, fittings, piping accessories and reference
lines* -- the in-line detail band -- at 0,25 mm. A tray deck and an
impeller are detail inside an outline, not the outline, so they belong in
the finer band, and a professionally drawn sheet puts them there. The
weight survives the scale to the body: ``compose`` divides every declared
width by the scale first, because ISO 14617-1 §4.3 holds a symbol's
line width fixed when the symbol is resized.

Connection ticks are not drawn
------------------------------
Table 2 draws a short thin stroke beside many symbols, offset by one
module from the artwork. Clause 5 column 3 says what it is: the mark
that shows where a connection is preferably made, and expressly no part
of the graphical symbol itself. It is a placement note, and pandid
states placement in ``ports`` instead. That matters here because
an agitator's tick sits directly above its shaft with a one-module gap,
so a reader skimming the page sees a broken vertical line and concludes
the shaft is dashed. **It is not.** Every group-28 shaft in Table 2 is a
single solid stroke; the break is the gap between the tick and the
symbol. ``tests/test_iso_parts.py`` holds this module to it.

Every part stretches, and two flags say why not
-----------------------------------------------
**No part sets ``stretchable=False``**, and that is a correction to this
module as it first shipped rather than an oversight. The case for holding
the ten agitators rigid is real -- they differ in nothing but the shape at
the foot of the shaft, and ISO 14617-1 §4.4 bounds reshaping at the
point where the symbol stops being recognisable. But the flag does not
mean *draw this part carefully*. It means two other things, and both are
about the body rather than the part:

1. **Letterbox the part on its rectangle**, keeping its aspect and
   centring what is left over. A part's rectangle is stated in fractions
   of the body's box, so its *aspect* is the body's aspect times those
   fractions -- and which of the two scales binds therefore depends on
   the body. On a 62 x 100 stirred tank the width binds, and the letterbox
   centres the agitator **vertically**, which lifts the shaft's top eight
   units clear of the head and leaves the ``drive`` nozzle floating in
   the vapour space above the liquid it is meant to come through.
   ``tests/test_symbol_invariants`` measured exactly that.
2. **Make the whole composed symbol unstretchable**, since there is no
   way to hold one group still inside a group that is being stretched.
   So a stirred tank given a box would be letterboxed and centred in it
   -- and its neighbours on the same sheet, drawn from whole stencils,
   would not.

Two further facts settle it. draw.io's own ``mxgraph.pid.agitators`` set
draws these same ten items and declares every one of them
``aspect="variable"``; and this module now *names* those stencils, so a
part that refused to stretch would have the two backends sizing one
drawing by two rules -- which is the divergence the cross-backend test
exists to catch. The parts stretch, and what keeps them legible is the
rectangle they are given: the helpers at the foot of this file hand each
part a rectangle of about its own aspect, so the stretch a part sees is
the stretch the body sees and nothing more.

``directional`` is gone for the same kind of reason
---------------------------------------------------
It reads like a claim about the mark and is not. It tells the renderer to
**hold the artwork still under a flip and move only the nozzles**
(:func:`pandid.render.svg._upright_artwork`), which is sound only where
the artwork under the moved nozzle is the same as the artwork under the
original -- a cooler's circle and zigzag, where the arrowhead is the whole
difference from a heater.

A part cannot make that promise on a body's behalf. A settling arrow's
body is a hopper: held still under a vertical flip, its feed nozzle moves
from the shoulder to twenty units below the cone and lands in mid-air. An
agitator's body is a vessel, and its ``drive`` moves off the crown onto
the bottom head. So no part here sets it, and what says the arrow's body
may not be turned is ``gravity_fixed`` -- ISO 14617-1 §4.5's own word for
it, and a prohibition rather than a rendering instruction.

Ports
-----
Only the motor anchors one, and it is the only part that is a machine.
``drive`` is where the power comes into the drawing, and on ISO item
1.27 (X8006) that is the motor: the shaft below it is welded to it, not
connected to it. A tray, a settling arrow and a stirrer are marks inside
or under a body that no line ever reaches.

The group-28 agitators anchored ``drive`` at the top of their shafts
until the motor was drawn, which was right while the shaft's top *was*
the top of the drawing. It is not any more -- the crown is mid-shaft
now -- and a nozzle there would be nearest a *side* of the grown box and
would take its stream out through the shell wall. The two parts always
arrive together (:func:`agitator_overlays` returns both), so moving the
nozzle to the motor loses nothing and puts it where an author would draw
the supply.

Why the drawings are built inside a function
--------------------------------------------
:func:`parts` imports ``IsoPart`` and ``OverlayPart`` when it is first
called rather than at the top of this file, which is the same deferral
``_vendored_symbols.register_vendored`` makes and is not a style choice.
``symbols`` builds its default registry as the last statement of its own
module body, and that build registers these parts -- so an importer who
reaches this module first would otherwise arrive back here for the two
dataclasses before this file had finished defining anything. Deferring
the import is what lets either module be the one imported first.
"""

import math

#: The ISO 14617-1 §4.3 grid module, in pandid drawing units. Table 2's
#: artwork is laid out on a 2,5 mm dotted grid and every vertex lands on
#: it, so the coordinates below are whole multiples of this and can be
#: checked against the standard by counting grid dots.
M = 10.0

#: The weight every part is drawn at, in drawing units. See the module
#: docstring: ISO 10628-1:2014 §5.3.1 c)'s detail band, half the
#: equipment outline's.
PART_STROKE = 1.0

# The attributes every stroked path in this module carries. Kept in one
# string so a part cannot quietly acquire its own weight: the whole
# argument for 1 unit is that the parts agree with each other and differ
# from the outline they are drawn inside.
_INK = f'fill="none" stroke="black" stroke-width="{PART_STROKE:g}"'
_SOLID_INK = 'fill="black" stroke="none"'

# cos 45 degrees, which is also sin 45: how far along each axis a
# diagonal has gone when it leaves a circle of radius 1. Item 29.8's
# four arms start on the rim of its rotor rather than at the centre,
# which is the only thing telling that mark from 29.5's plain X.
_SQ2 = math.sqrt(2) / 2

# ISO's own dash pitches, measured off Table 2 in modules and written
# here in units. 27.5's sieve deck is a 2 M dash with a 1 M gap; 27.6's
# filter insert alternates that long dash with a 1 M short one, which is
# the only thing telling the two rows apart.
_DASH_LONG = f'stroke-dasharray="{2 * M:g},{M:g}"'
_DASH_DOT = f'stroke-dasharray="{2 * M:g},{M:g},{M:g},{M:g}"'

#: The frame every group-27 deck is drawn in: 10 M across, 2 M tall, with
#: the deck itself on the horizontal centre line and anything the item
#: adds above it. One frame for all six, so a caller places every tray
#: the same way and they differ only in what Table 2 says they differ in.
#: A deck is stretchable, so a rectangle far from this aspect smears the
#: bubble cap; that is the caller's arithmetic to get right.
DECK_W, DECK_H = 10 * M, 2 * M
_DECK_Y = M

#: The frame every group-28 agitator is drawn in: 4 M across, 8 M tall,
#: shaft on the centre line from the top of the box down to the impeller.
#: One frame for all ten, so a body can swap one for another without
#: moving anything and the ``drive`` nozzle lands in the same place
#: whichever is fitted.
AGITATOR_W, AGITATOR_H = 4 * M, 8 * M
_AG_X = AGITATOR_W / 2

#: draw.io's own agitator stencil set, which has exactly ten shapes and
#: they are ISO group 28's ten, item for item. Naming them is what lets a
#: composed reactor export with a real agitator on it; see
#: :func:`_build`'s ``agitator`` helper.
_AG = "mxgraph.pid.agitators."


def _g(name: str, *body: str) -> str:
    """One part's artwork, wrapped as ``compose`` requires.

    The id is dropped when the part is painted onto a body -- only the
    group's contents are copied -- so it is never emitted and exists to
    make this module readable.
    """
    return f'<g id="part_{name}">{"".join(body)}</g>'


def _run(x0: float, x1: float, y: float = _DECK_Y, dash: str = "") -> str:
    """One horizontal stroke of a deck."""
    return (f'<line x1="{x0:g}" y1="{y:g}" x2="{x1:g}" y2="{y:g}" {_INK}'
            + (f" {dash}" if dash else "") + "/>")


def _build() -> tuple:
    """Every part, drawn. See the module docstring for the deferral."""
    from pandid.render.symbols import IsoPart, OverlayPart

    def deck(name, item, reg, descriptor, *ink):
        """A group-27 internal in the common deck frame."""
        return OverlayPart(
            name=name, iso=IsoPart(27, item, reg, descriptor),
            svg=_g(f"27_{name}", *ink), width=DECK_W, height=DECK_H)

    def agitator(name, item, reg, descriptor, stencil, shaft_to, *blade):
        """A group-28 agitator: the shaft down to ``shaft_to``, then its
        blade, in the common agitator frame.

        ``stencil`` is the shape in draw.io's own ``mxgraph.pid.agitators``
        set that draws this same ISO item, which is the whole of that set:
        it has ten shapes and they are group 28's ten, item for item. So a
        composed reactor exports with a real agitator on it rather than an
        approximation of one. ``tests/test_drawio.py`` derives the keys
        from the stencil XML and holds these to them.
        """
        return OverlayPart(
            name=name, iso=IsoPart(28, item, reg, descriptor),
            svg=_g(f"28_{name}",
                   f'<line x1="{_AG_X:g}" y1="0" x2="{_AG_X:g}" y2="{shaft_to:g}" {_INK}/>',
                   *blade),
            width=AGITATOR_W, height=AGITATOR_H, drawio_shape=stencil,
            # No nozzle. The shaft's top is welded to the motor above it
            # -- item 20.6 below, which anchors ``drive`` -- and is not
            # where a line arrives. See the module docstring on ports.
            # Turned, the drive comes in from the side and the blade
            # hangs sideways in a vessel that is still upright. That is
            # not the equipment this draws, so ISO 14617-1 §4.5 applies
            # to the body carrying it even where the bare body was free.
            # See the module docstring for why the flip is *not* also
            # declared here.
            gravity_fixed=True)

    # ------------------------------------------------------------
    # Group 26 -- apparatus elements
    #
    # Supports, drawn under or around the body rather than inside it.
    # Table 2 gives six; the four supports are here and 26.5 manhole /
    # 26.6 socket are not, because both are drawn *on the vessel wall*
    # and where a wall is depends on the body -- a placement question the
    # keyword that puts them there has to answer, not the artwork.
    #
    # Two of the four are chiral: Table 2 draws 26.2's bracket and 26.4's
    # ring against the wall on one side. They are reproduced in the hand
    # the standard draws them in, and a body wanting the other hand needs
    # a mirrored placement, which ``Overlay`` cannot yet express.
    # ------------------------------------------------------------

    leg = OverlayPart(
        name="leg", iso=IsoPart(26, "26.1", "C2005", "Support leg"),
        # A channel section 1 M x 5 M: two verticals closed at the foot
        # and open at the top, where the vessel it carries closes it.
        svg=_g("26_leg",
               f'<path d="M 0 0 L 0 {5 * M:g} L {M:g} {5 * M:g} L {M:g} 0" {_INK}/>'),
        width=M, height=5 * M)

    bracket = OverlayPart(
        name="bracket", iso=IsoPart(26, "26.2", "C2006", "Support bracket"),
        # A gusset: a 4 M horizontal foot and a hypotenuse rising 4 M to
        # the wall. The third side *is* the wall, so it is not drawn.
        svg=_g("26_bracket",
               f'<path d="M {4 * M:g} {4 * M:g} L 0 {4 * M:g} L {4 * M:g} 0" {_INK}/>'),
        width=4 * M, height=4 * M)

    skirt = OverlayPart(
        name="skirt", iso=IsoPart(26, "26.3", "C2007", "Support skirt"),
        # Two 4 M walls 8 M apart, each turning 2 M inwards at the base
        # ring. Open in the middle, which is what makes it a skirt and
        # not a box.
        svg=_g("26_skirt",
               f'<path d="M 0 0 L 0 {4 * M:g} L {2 * M:g} {4 * M:g}" {_INK}/>'
               f'<path d="M {8 * M:g} 0 L {8 * M:g} {4 * M:g} '
               f'L {6 * M:g} {4 * M:g}" {_INK}/>'),
        width=8 * M, height=4 * M)

    ring = OverlayPart(
        name="ring", iso=IsoPart(26, "26.4", "C2008", "Support ring"),
        # A 4 M x 1 M bracket open on the wall side: the ring seen in
        # section, sitting on its bearing surface.
        svg=_g("26_ring",
               f'<path d="M {4 * M:g} 0 L 0 0 L 0 {M:g} L {4 * M:g} {M:g}" {_INK}/>'),
        width=4 * M, height=M)

    # ------------------------------------------------------------
    # Group 27 -- internals
    #
    # Six of the eight are decks and share :data:`DECK_W` x
    # :data:`DECK_H`; the other two are beds and fill their own box.
    #
    # Note what this collapses. Table 2 draws 27.8 packing and group 2's
    # fixed bed with the same construction, so a packed column, a
    # packed-bed reactor, an adsorber and a molecular sieve are one
    # drawing told apart by its tag, not four drawings.
    # ------------------------------------------------------------

    tray = deck("tray", "27.1", "C2044", "Tray (general)", _run(0, DECK_W))

    baffle_tray = deck(
        "baffle_tray", "27.2", "X8166", "Tray with baffle",
        _run(0, 9 * M, dash=_DASH_LONG),
        # The baffle: a 1 M riser standing at the deck's end. Table 2
        # draws the pair, one deck with its riser at each end, because
        # the point of the item is that consecutive decks alternate --
        # which is placement, so it is the caller's ``x`` that says it.
        f'<line x1="{9 * M:g}" y1="{_DECK_Y:g}" x2="{9 * M:g}" y2="0" {_INK}/>')

    bubble_cap_tray = deck(
        "bubble_cap_tray", "27.3", "C2010", "Tray, bubble-cap type",
        # The deck opens 2 M for the cap and closes again.
        _run(0, 4 * M), _run(6 * M, DECK_W),
        # The cap: a shallow arc 4 M across, rising 0,5 M above the deck.
        # The radius follows from the chord and the rise,
        # r = (c^2 + 4h^2) / 8h with c = 4 M and h = 0,5 M.
        f'<path d="M {3 * M:g} {_DECK_Y / 2:g} '
        f'A {4.25 * M:g} {4.25 * M:g} 0 0 1 {7 * M:g} {_DECK_Y / 2:g}" {_INK}/>')

    valve_tray = deck(
        "valve_tray", "27.4", "C2011", "Tray, valve type",
        _run(0, 4 * M), _run(6 * M, DECK_W),
        # The valve: the middle 2 M of the deck lifted 0,5 M clear of it.
        _run(4 * M, 6 * M, y=_DECK_Y / 2))

    sieve_tray = deck(
        "sieve_tray", "27.5", "2602", "Sieve tray, screen or sieve element",
        _run(0, DECK_W, dash=_DASH_LONG))

    filter_insert = deck(
        "filter_insert", "27.6", "C2047", "Filter insert (general)",
        _run(0, DECK_W, dash=_DASH_DOT))

    fluidised_bed = OverlayPart(
        name="fluidised_bed", iso=IsoPart(27, "27.7", "2604", "Fluidized bed"),
        # A staggered field of filled dots 0,4 M across: 2 M pitch along
        # a row, rows 1 M apart, alternate rows offset by half a pitch so
        # the field reads as bubbling rather than as a lattice.
        svg=_g("27_fluidised_bed", "".join(
            f'<circle cx="{x:g}" cy="{y:g}" r="{M / 5:g}" {_SOLID_INK}/>'
            for row, y in enumerate(M / 2 + M * i for i in range(5))
            for x in (M + 2 * M * i + (M if row % 2 else 0)
                      for i in range(5 if row % 2 else 6)))),
        width=12 * M, height=5 * M)

    packing = OverlayPart(
        name="packing", iso=IsoPart(27, "27.8", "X8141", "packing"),
        # One large X across the bed, bounded above and below by a long-
        # dashed line the X's corners land on.
        svg=_g("27_packing",
               _run(0, 8 * M, y=0, dash=_DASH_LONG),
               _run(0, 8 * M, y=7 * M, dash=_DASH_LONG),
               f'<path d="M 0 0 L {8 * M:g} {7 * M:g} '
               f'M {8 * M:g} 0 L 0 {7 * M:g}" {_INK}/>'),
        width=8 * M, height=7 * M)

    # ------------------------------------------------------------
    # Group 28 -- agitators, stirrers
    #
    # Ten items that differ in nothing but the shape at the foot of the
    # shaft. The shafts are SOLID -- see the module docstring on
    # connection ticks, which is what the dashed reading came from.
    # ------------------------------------------------------------

    agitator_general = agitator(
        "agitator", "28.1", "2672", "Agitator (general), stirrer (general)",
        _AG + "agitator,_stirrer", 7 * M,
        # Two 2 M verticals 4 M apart with a diagonal falling between
        # them: the general stirrer, and the item every other one is a
        # specialisation of.
        f'<path d="M 0 {6 * M:g} L 0 {8 * M:g} '
        f'M 0 {6 * M:g} L {4 * M:g} {8 * M:g} '
        f'M {4 * M:g} {6 * M:g} L {4 * M:g} {8 * M:g}" {_INK}/>')

    flat_blade = agitator(
        "flat_blade", "28.2", "C2019", "Agitator, flat-blade paddle type",
        _AG + "agitator_(flate-blade_paddle)", 4 * M,
        # A 4 M square hanging off the shaft's foot.
        f'<rect x="0" y="{4 * M:g}" width="{4 * M:g}" height="{4 * M:g}" {_INK}/>')

    gate_paddle = agitator(
        "gate_paddle", "28.3", "C2020", "Agitator, gate paddle type",
        _AG + "agitator_(gat_paddle)", 8 * M,
        # A 4 M x 2 M gate divided by the shaft, each half crossed by a
        # diagonal.
        f'<rect x="0" y="{6 * M:g}" width="{4 * M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M 0 {8 * M:g} L {2 * M:g} {6 * M:g} '
        f'M {2 * M:g} {8 * M:g} L {4 * M:g} {6 * M:g}" {_INK}/>')

    cross_beam = agitator(
        "cross_beam", "28.4", "C2021", "Agitator, cross-beam type",
        _AG + "agitator_(cross-beam)", 8 * M,
        # Two 4 M beams 2 M apart, threaded on the shaft.
        f'<path d="M 0 {6 * M:g} L {4 * M:g} {6 * M:g} '
        f'M 0 {8 * M:g} L {4 * M:g} {8 * M:g}" {_INK}/>')

    anchor = agitator(
        "anchor", "28.5", "C2022", "Agitator, anchor type",
        _AG + "agitator_(anchor)", 8 * M,
        # Two 1,5 M arms dropping to an arc that sweeps 1 M below their
        # feet: the blade that follows a dished bottom head.
        f'<path d="M 0 {5.5 * M:g} L 0 {7 * M:g} '
        f'A {2.5 * M:g} {2.5 * M:g} 0 0 0 {4 * M:g} {7 * M:g} '
        f'L {4 * M:g} {5.5 * M:g}" {_INK}/>')

    helical = agitator(
        "helical", "28.6", "C2023", "Agitator, helical type",
        _AG + "agitator_(helical)", 7.5 * M,
        # A helix seen edge on: three strokes across 4 M, descending 1 M
        # each, which is how Table 2 flattens a ribbon into two
        # dimensions.
        f'<path d="M 0 {5 * M:g} L {4 * M:g} {6 * M:g} L 0 {7 * M:g} '
        f'L {4 * M:g} {8 * M:g}" {_INK}/>')

    impeller = agitator(
        "impeller", "28.7", "C2024", "Agitator, impeller type",
        _AG + "agitator_(impeller)", 7.5 * M,
        # A single blade in profile: an ogee about 4 M across and 1 M
        # deep, with the straight blade section crossing the shaft.
        f'<path d="M 0 {8 * M:g} C {0.2 * M:g} {7.2 * M:g} {M:g} {7.1 * M:g} '
        f'{2 * M:g} {7.5 * M:g} C {3 * M:g} {7.9 * M:g} {3.8 * M:g} {7.8 * M:g} '
        f'{4 * M:g} {7 * M:g}" {_INK}/>'
        f'<path d="M {1.4 * M:g} {7.8 * M:g} L {2.6 * M:g} {7.2 * M:g}" {_INK}/>')

    propeller = agitator(
        "propeller", "28.8", "C2025", "Agitator, propeller type",
        _AG + "agitator_(propeller)", 7.5 * M,
        # The bow tie: two lobes meeting on the shaft, 4 M across and 1 M
        # deep, with the blades crossing inside them.
        f'<path d="M {2 * M:g} {7.5 * M:g} C {1.4 * M:g} {6.8 * M:g} '
        f'{0.2 * M:g} {6.8 * M:g} 0 {7.5 * M:g} '
        f'C {0.2 * M:g} {8.2 * M:g} {1.4 * M:g} {8.2 * M:g} {2 * M:g} {7.5 * M:g} '
        f'C {2.6 * M:g} {6.8 * M:g} {3.8 * M:g} {6.8 * M:g} {4 * M:g} {7.5 * M:g} '
        f'C {3.8 * M:g} {8.2 * M:g} {2.6 * M:g} {8.2 * M:g} '
        f'{2 * M:g} {7.5 * M:g}" {_INK}/>'
        f'<path d="M {0.7 * M:g} {7.05 * M:g} L {3.3 * M:g} {7.95 * M:g} '
        f'M {3.3 * M:g} {7.05 * M:g} L {0.7 * M:g} {7.95 * M:g}" {_INK}/>')

    disc = agitator(
        "disc", "28.9", "C2026", "Agitator, disc type",
        _AG + "agitator_(disc)", 7 * M,
        # The disc seen edge on: a 1 M x 2 M plate each side of the
        # shaft, joined across it by the hub.
        f'<rect x="0" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<rect x="{3 * M:g}" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {7 * M:g} L {3 * M:g} {7 * M:g}" {_INK}/>')

    turbine = agitator(
        "turbine", "28.10", "C2027", "Agitator, turbine type",
        _AG + "agitator_(turbine)", 8 * M,
        # A 4 M x 2 M rotor split into three: the 2 M hub the shaft runs
        # into, and a 1 M blade each side of it.
        f'<rect x="0" y="{6 * M:g}" width="{4 * M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {6 * M:g} L {M:g} {8 * M:g} '
        f'M {3 * M:g} {6 * M:g} L {3 * M:g} {8 * M:g}" {_INK}/>')

    # ------------------------------------------------------------
    # Group 20 -- drives
    #
    # One item of the eight, and it is here on ISO's own authority rather
    # than on the rule the other thirty-six are here on: see the module
    # docstring and ``symbols.COMPOSED_APPARATUS``. A motor is a machine,
    # and pandid draws seven other group-20 machines as whole symbols
    # with tags of their own; this is the one the standard draws *inside*
    # another symbol.
    # ------------------------------------------------------------

    motor = OverlayPart(
        name="motor", iso=IsoPart(20, "20.6", "C0082", "Electric motor (general)"),
        # Measured off row 20.6: a 4 M circle with the letter M in it.
        # The M is 1,5 M x 2 M on the circle's centre -- verticals at
        # x 1,25 and 2,75 running from y 1 to y 3, and a vee between
        # their tops that comes down to the centre and back up. Drawn as
        # one stroke, which is how the row draws it.
        #
        # 1.27 draws this same mark at half size, 2 M across, which is
        # the standard's usual treatment of a symbol set inside another.
        # That is a *placement*, so it is stated in
        # :func:`agitator_overlays` and not here.
        svg=_g("20_motor",
               f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{2 * M:g}" {_INK}/>'
               f'<path d="M {1.25 * M:g} {3 * M:g} L {1.25 * M:g} {M:g} '
               f'L {2 * M:g} {2 * M:g} L {2.75 * M:g} {M:g} '
               f'L {2.75 * M:g} {3 * M:g}" {_INK}/>'),
        width=4 * M, height=4 * M,
        # The whole drawing's one connection: power in, at the top of the
        # motor. See the module docstring -- the agitators gave this up
        # when the motor was drawn, because the top of the shaft stopped
        # being the top of the drawing.
        ports={"drive": (2 * M, 0.0)},
        # A motor over a vessel is over it; upside down it is a motor
        # hanging under the floor with the vessel's stirrer running up
        # into it. ISO 14617-1 §4.5 again, and the same claim about the
        # body the agitator it drives already makes.
        gravity_fixed=True)

    # ------------------------------------------------------------
    # Group 29 -- internal characteristics and built-in components
    #
    # The mark that says how a body does its separating, and -- for most
    # of the group -- how it does its crushing. All fourteen of Table 2's
    # items are here.
    #
    # The first three are the three whose composition onto group 8's
    # separating vessel is verified glyph for glyph: item 8.3 X8031 is
    # the body carrying 29.1, 8.6 X8125 carries 29.2, and 8.8 X8126
    # carries 29.3. Those three are what ``Separator(characteristic=)``
    # names, and it still names only those three -- registering the other
    # eleven adds artwork, not keywords, and moves no drawing.
    #
    # The other eleven are 29.4 to 29.14, and the group's own heading is
    # why they belong here rather than under a mill: Table 2 files them as
    # *characteristics*, marks that say what the machine does inside its
    # outline, exactly as the first three do. The bodies they go in are
    # Table 1 group 11, CRUSHING/GRINDING MACHINES.
    #
    # Two absences from the fourteen are load-bearing rather than
    # incidental: there is **no vortex or cyclone item in group 29**,
    # which is why ISO 8.10 X2618 is a symbol in its own right and not a
    # body plus a characteristic; and there is no spray, which is why
    # 8.7 X8033 -- a body carrying both a spray mark and 29.2 -- cannot be
    # composed either, its spray having no group 26-29 number to be a
    # part under.
    #
    # Only 29.1 says which way is down, so only 29.1 is
    # ``gravity_fixed``. A crushing X and a pair of gearwheels read the
    # same whichever way up the machine is drawn, and 29.14's two arrows
    # are each other's mirror, so none of the eleven has a claim to make
    # about the body's orientation.
    # ------------------------------------------------------------

    gravity = OverlayPart(
        name="gravity", iso=IsoPart(29, "29.1", "C2028", "Gravity type, settling type"),
        # A 6 M arrow pointing down, with the solid head Table 2 draws:
        # 1 M long and a little over half a module across.
        svg=_g("29_gravity",
               f'<line x1="{M:g}" y1="0" x2="{M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<polygon points="{M:g},{6 * M:g} {0.73 * M:g},{5 * M:g} '
               f'{1.27 * M:g},{5 * M:g}" {_SOLID_INK}/>'),
        width=2 * M, height=6 * M,
        # The arrow *is* the statement that gravity does the work here,
        # so this is the case ISO 14617-1 §4.5's prohibition on turning
        # was written for. Flipped, the same arrow says the heavy phase
        # rises -- which is a reason to leave the drawing alone and not,
        # as this part first claimed, a reason to set ``directional``;
        # see the module docstring.
        gravity_fixed=True)

    electrostatic = OverlayPart(
        name="electrostatic", iso=IsoPart(29, "29.2", "C2030", "Electrostatic type"),
        # Two 2 M plates a module apart, each with a 1 M lead going out
        # from its middle.
        svg=_g("29_electrostatic",
               f'<path d="M {M:g} 0 L {M:g} {2 * M:g} '
               f'M {2 * M:g} 0 L {2 * M:g} {2 * M:g}" {_INK}/>'
               f'<path d="M 0 {M:g} L {M:g} {M:g} '
               f'M {2 * M:g} {M:g} L {3 * M:g} {M:g}" {_INK}/>'),
        width=3 * M, height=2 * M)

    electromagnetic = OverlayPart(
        name="electromagnetic", iso=IsoPart(29, "29.3", "C2031", "Electromagnetic type"),
        # A coil seen from the side: three 2 M turns on a 7 M baseline,
        # with half a module of lead at each end.
        svg=_g("29_electromagnetic",
               f'<path d="M 0 {M:g} L {0.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {2.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {4.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {6.5 * M:g} {M:g} '
               f'L {7 * M:g} {M:g}" {_INK}/>'),
        width=7 * M, height=M)

    # ``disc_type`` rather than ``disc``: 28.9 above is *also* called
    # disc, and both keep the standard's own word. They are different
    # parts in different groups, which is what ``(group, name)`` keys
    # are for -- as ``turbine`` the agitator and ``turbine`` the machine
    # already are on the symbol side.
    disc_type = OverlayPart(
        name="disc", iso=IsoPart(29, "29.4", "C2033", "Disc type"),
        # A bladed disc rotor seen edge on, in an 8 M x 5 M box. A shaft
        # down the middle to y 5 M; two 4 M plates crossing it, at y 3 M
        # and at its foot; and between them at y 4 M a pair of 3 M arms
        # that stop 1 M short of the shaft on either side, so the box's
        # full 8 M width is theirs and the plates' is not.
        svg=_g("29_disc",
               f'<line x1="{4 * M:g}" y1="0" x2="{4 * M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<line x1="{2 * M:g}" y1="{3 * M:g}" x2="{6 * M:g}" y2="{3 * M:g}" {_INK}/>'
               f'<line x1="{2 * M:g}" y1="{5 * M:g}" x2="{6 * M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<line x1="0" y1="{4 * M:g}" x2="{3 * M:g}" y2="{4 * M:g}" {_INK}/>'
               f'<line x1="{5 * M:g}" y1="{4 * M:g}" x2="{8 * M:g}" y2="{4 * M:g}" {_INK}/>'),
        width=8 * M, height=5 * M)

    crushing = OverlayPart(
        name="crushing", iso=IsoPart(29, "29.5", "C0240", "Crushing"),
        # A plain X, corner to corner of a 4 M box -- the same
        # construction 27.8 packing draws across its bed, at its own
        # size and with no bounding lines.
        svg=_g("29_crushing",
               f'<path d="M 0 0 L {4 * M:g} {4 * M:g} '
               f'M {4 * M:g} 0 L 0 {4 * M:g}" {_INK}/>'),
        width=4 * M, height=4 * M)

    gear = OverlayPart(
        name="gear",
        # C024 is three digits where every sibling in the group has
        # four. That is how Table 2 prints it, checked against the row
        # twice, and ``_REG_NO`` allows three or four for exactly this
        # kind of reason. Recorded as printed rather than repaired.
        iso=IsoPart(29, "29.6", "C024", "Gear type, gearwheels type"),
        # Two 2 M wheels meshing: centres 1,5 M apart, so they overlap
        # by half a module. The pair is 3,5 M across and the row's grid
        # box is 4 M, so the centres sit 0,75 M either side of the box's
        # middle and a quarter module of air is left at each end. 29.11
        # below is the same two wheels moved apart until they only
        # touch, which is the whole of what Table 2 draws between them.
        svg=_g("29_gear",
               f'<circle cx="{1.25 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'
               f'<circle cx="{2.75 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=4 * M, height=2 * M)

    hammer = OverlayPart(
        name="hammer", iso=IsoPart(29, "29.7", "C2034", "Hammer type"),
        # Four hammers swinging off a rotor, in a 3 M box. The rotor is
        # an X through the centre whose arms run one module in each
        # direction; each arm is then capped by a 1 M x 1 M crossbar at
        # right angles to it -- the hammer head -- and every one of the
        # eight cap ends lands on a grid dot on the box's edge.
        svg=_g("29_hammer",
               f'<path d="M {0.5 * M:g} {0.5 * M:g} L {2.5 * M:g} {2.5 * M:g} '
               f'M {0.5 * M:g} {2.5 * M:g} L {2.5 * M:g} {0.5 * M:g}" {_INK}/>'
               f'<path d="M {M:g} 0 L 0 {M:g} '
               f'M {2 * M:g} 0 L {3 * M:g} {M:g} '
               f'M {3 * M:g} {2 * M:g} L {2 * M:g} {3 * M:g} '
               f'M {M:g} {3 * M:g} L 0 {2 * M:g}" {_INK}/>'),
        width=3 * M, height=3 * M)

    impact = OverlayPart(
        name="impact", iso=IsoPart(29, "29.8", "C2035", "Impact type"),
        # Crushing's 4 M X with a 2 M rotor drawn on the crossing: the
        # four arms are cut back to the circle and run from its edge out
        # to the box's corners, so the mark is 29.5 with the thing that
        # does the striking put in the middle of it.
        svg=_g("29_impact",
               f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{M:g}" {_INK}/>'
               + "".join(
                   f'<line x1="{(2 + _SQ2 * sx) * M:g}" y1="{(2 + _SQ2 * sy) * M:g}" '
                   f'x2="{(2 + 2 * sx) * M:g}" y2="{(2 + 2 * sy) * M:g}" {_INK}/>'
                   for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)))),
        width=4 * M, height=4 * M)

    jaw = OverlayPart(
        name="jaw", iso=IsoPart(29, "29.9", "C2036", "Jaw type"),
        # The swing jaw and its eccentric: a 3 M line running into a 2 M
        # circle at the far end of a 5 M x 2 M box.
        svg=_g("29_jaw",
               f'<line x1="0" y1="{M:g}" x2="{3 * M:g}" y2="{M:g}" {_INK}/>'
               f'<circle cx="{4 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=5 * M, height=2 * M)

    liquid = OverlayPart(
        name="liquid", iso=IsoPart(29, "29.10", "321", "Liquid type, wet type"),
        # Two scallops meeting at the middle of a 4 M x 1 M box: each is
        # an arc of a 2 M circle over a 1,85 M chord, which by
        # r = (c^2 + 4h^2) / 8h dips 0,62 M. The 0,62 M is centred in the
        # module band, so 0,19 M of air is left above and below -- the
        # same way 29.1's arrow is centred across its own 2 M box.
        svg=_g("29_liquid",
               f'<path d="M {0.15 * M:g} {0.19 * M:g} '
               f'A {M:g} {M:g} 0 0 0 {2 * M:g} {0.19 * M:g} '
               f'A {M:g} {M:g} 0 0 0 {3.85 * M:g} {0.19 * M:g}" {_INK}/>'),
        width=4 * M, height=M)

    roller = OverlayPart(
        name="roller", iso=IsoPart(29, "29.11", "C2037", "Roller type"),
        # Two 2 M rolls with the nip between them: centres 2 M apart, so
        # they touch and do not overlap. See 29.6 above -- the spacing
        # is the entire difference, and it is why both are drawn in the
        # same 4 M x 2 M box.
        svg=_g("29_roller",
               f'<circle cx="{M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'
               f'<circle cx="{3 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=4 * M, height=2 * M)

    cone = OverlayPart(
        name="cone", iso=IsoPart(29, "29.12", "C2038", "Cone type"),
        # The crushing head in section: an isosceles trapezoid 2 M
        # across the top, 4 M across the bottom and 3 M deep.
        svg=_g("29_cone",
               f'<path d="M {M:g} 0 L {3 * M:g} 0 L {4 * M:g} {3 * M:g} '
               f'L 0 {3 * M:g} Z" {_INK}/>'),
        width=4 * M, height=3 * M)

    jet = OverlayPart(
        name="jet", iso=IsoPart(29, "29.13", "X8176", "Jet type"),
        # The grinding chamber of a jet mill, and the biggest mark in
        # the group by some way: a 6 M circle with its full horizontal
        # diameter drawn, and two further chords mirrored about that
        # diameter. The chord ends below are measured off the row and
        # land on the circle -- 2,61^2 + 1,47^2 = 3^2 to within a
        # thousandth of a module, which is a hundredth of the stroke.
        svg=_g("29_jet",
               f'<circle cx="{3 * M:g}" cy="{3 * M:g}" r="{3 * M:g}" {_INK}/>'
               f'<line x1="0" y1="{3 * M:g}" x2="{6 * M:g}" y2="{3 * M:g}" {_INK}/>'
               f'<path d="M {1.39 * M:g} {0.47 * M:g} L {5.61 * M:g} {1.53 * M:g} '
               f'M {1.39 * M:g} {5.53 * M:g} L {5.61 * M:g} {4.47 * M:g}" {_INK}/>'),
        width=6 * M, height=6 * M)

    vibration = OverlayPart(
        name="vibration", iso=IsoPart(29, "29.14", "3831", "Vibration type"),
        # Two 3 M arrows on tracks a module apart, pointing opposite
        # ways -- the standard's own idiom for oscillation. The heads
        # are 29.1's: 1 M long and a little over half a module across,
        # with the shaft stopping at the head's base.
        svg=_g("29_vibration",
               f'<line x1="{3 * M:g}" y1="{0.5 * M:g}" x2="{M:g}" y2="{0.5 * M:g}" {_INK}/>'
               f'<polygon points="0,{0.5 * M:g} {M:g},{0.23 * M:g} '
               f'{M:g},{0.77 * M:g}" {_SOLID_INK}/>'
               f'<line x1="0" y1="{1.5 * M:g}" x2="{2 * M:g}" y2="{1.5 * M:g}" {_INK}/>'
               f'<polygon points="{3 * M:g},{1.5 * M:g} {2 * M:g},{1.23 * M:g} '
               f'{2 * M:g},{1.77 * M:g}" {_SOLID_INK}/>'),
        width=3 * M, height=2 * M)

    return (
        leg, bracket, skirt, ring,
        tray, baffle_tray, bubble_cap_tray, valve_tray, sieve_tray, filter_insert,
        fluidised_bed, packing,
        agitator_general, flat_blade, gate_paddle, cross_beam, anchor, helical,
        impeller, propeller, disc, turbine,
        motor,
        gravity, electrostatic, electromagnetic,
        disc_type, crushing, gear, hammer, impact, jaw, liquid, roller, cone,
        jet, vibration,
    )


_PARTS: "tuple | None" = None


def parts() -> tuple:
    """Every part this module draws, in Table 2 order.

    The groups 26-29 supplementary symbols, and item 20.6 the motor
    between the agitators it belongs with and group 29.

    Built once and shared, so a part asked for through the registry and a
    part read off this module are the same object.
    """
    global _PARTS
    if _PARTS is None:
        _PARTS = _build()
    return _PARTS


def register_parts(registry) -> None:
    """Register every part this module draws on ``registry``.

    Called from :meth:`pandid.render.symbols.SymbolRegistry.__init__`
    after the whole symbols, since a part is only ever overlaid on one.
    """
    for part in parts():
        registry.register_part(part)


# ----------------------------------------------------------------
# Where a part goes on a body.
#
# The four unit keywords -- ``Reactor(agitator=)``, ``Column(internals=)``,
# ``Vessel(supports=)``, ``Separator(characteristic=)`` -- all end here,
# because "an agitator hangs from the top head with its blade low in the
# liquid" is a fact about the equipment and not about any one class.
#
# **Every rectangle below is read off Table 2 and converted to fractions
# of the body's box**, which is the coordinate ``Overlay`` is stated in.
# The conversion needs the item the placement was measured on, so each
# helper names it. The bodies pandid draws are not the standard's own
# proportions to the last module -- a vendored stencil is 62 x 100 where
# ISO's vessel is 8 M x 12 M -- so a *fraction* transfers where a module
# count would not.
#
# Every part fills the rectangle it is given (see the module docstring on
# why none of them letterboxes), so a rectangle is a placement and a
# proportion at once and both have to be right. A deck stretched two to
# one is still a deck; a bubble cap stretched two to one is a smear. The
# rectangles below are therefore about the part's own aspect on the body
# each is placed on, and where a body is far from that shape it is the
# body that is unusual rather than the number here.
# ----------------------------------------------------------------


def _part(group: int, name: str, registry=None):
    """The registered part, or a ValueError naming the ones there are.

    *registry* is passed by the one caller with no default registry to
    ask -- ``SymbolRegistry._register_composed``, which runs while that
    registry is still being built. Everyone else asks the library's.

    Called for its exception. Resolving the name here is what makes
    ``Reactor("R-101", agitator="turbin")`` raise on the line the author
    typed rather than when the sheet is finally rendered.
    """
    if registry is None:
        from pandid.render.symbols import default_registry as registry
    return registry.part(group, name)


#: The motor's diameter as a fraction of the **shell's width**, and the
#: clear air between it and the crown as a fraction of the **body's
#: height**. Both read off ISO item 1.27 X8006: the shell runs x 11..17
#: and the body y 4..13, so a 6 M x 9 M box; the motor circle is x 13..15
#: and y 1..3. Two modules across a six-module shell, sitting one module
#: over a nine-module body.
_MOTOR_WIDTH, _MOTOR_GAP = 1 / 3, 1 / 9

#: Where the stirrer's blade sits, as a fraction of the body's box: 48 %
#: of the shell's width centred on it, with the foot of the part 76 % of
#: the way down. Also 1.27's, and unchanged by the motor -- the shaft
#: grew upward and the blade stayed in the liquid.
_AGITATOR_X, _AGITATOR_W, _AGITATOR_FOOT = 0.26, 0.48, 0.76


def agitator_overlays(name: str, kind: str, variant: str, registry=None) -> tuple:
    """``name``'s agitator and its motor, on a vertical body.

    **Two overlays, because ISO item 1.27 X8006 draws two marks.** The
    row is a vessel with a group-28 stirrer *and* item 20.6's electric
    motor above the top head, and the shaft is one continuous stroke from
    the motor's underside, through the head, down to the blade. There is
    no tabulated stirred vessel without a driver -- group 1 has 29 rows,
    exactly one carries an agitator, and it carries the motor too -- so
    the motor is not a keyword and there is nothing to ask for.

    Measured off that row, against its 6 M x 9 M body box:

    - the blade is 48 % of the shell's width, centred, with the foot of
      the stirrer 76 % of the way down -- low in the liquid;
    - the shaft's top is **one module above the crown**, at the motor;
    - the motor is a **2 M circle on a 6 M shell**, so a third of the
      shell's width, centred on the shaft.

    ``compose`` grows the composed box upward to hold it and moves the
    body's own nozzles down into it, which is the case
    :class:`~pandid.render.symbols.Overlay` was written to support.

    Why this one helper needs the body
    ----------------------------------
    A rectangle here is stated in fractions of the body's box, so its
    *shape* is the body's shape times those fractions -- and the motor is
    a **circle**. A third of the width against a fixed fraction of the
    height comes out 7 % oval on the 62 x 100 stirred tank and 22 % oval
    on the 52 x 95,4 jacketed one. The height is therefore derived from
    the width and the body it is going on, which is the only way to say
    "round" in a coordinate that has no units. Every other rectangle in
    this file is a line, a bar or a deck, and says nothing about a shape
    a stretch could destroy.

    Letterboxing is not the alternative. A part that declares
    ``stretchable=False`` makes the whole composition unstretchable (see
    the module docstring), so a stirred tank given a box would be
    centred in it while every stencilled neighbour filled one.
    """
    from pandid.render.symbols import Overlay
    if registry is None:
        from pandid.render.symbols import default_registry as registry
    _part(28, name, registry)
    _part(20, "motor", registry)
    body = registry.get(kind, variant)
    # Round: the circle's diameter is a third of the shell's width, and
    # its height is whatever fraction of *this* body's height that is.
    height = _MOTOR_WIDTH * body.width / body.height
    return (
        # The stirrer, its rectangle reaching up past the crown to the
        # motor's underside so the shaft is the one stroke 1.27 draws.
        # The foot does not move: only the top edge goes negative.
        Overlay(28, name, _AGITATOR_X, -_MOTOR_GAP, _AGITATOR_W,
                _AGITATOR_FOOT + _MOTOR_GAP),
        # The motor, centred on the shaft, clear of the head.
        Overlay(20, "motor", (1 - _MOTOR_WIDTH) / 2, -(_MOTOR_GAP + height),
                _MOTOR_WIDTH, height),
    )


#: Where a column's internals live, as fractions of a vertical body's
#: height. Read off **ISO item 2.6 X8011**, the tray column: its shell is
#: 8 M x 18 M overall with a 16 M straight side, and its eight decks sit
#: at y 6, 8, ... 20 on a body spanning y 4 to 22 -- so the first deck is
#: at (6-4)/18 and the last at (20-4)/18 of the box.
_INTERNALS_TOP, _INTERNALS_BOTTOM = 0.11, 0.89

#: How much of the body's height one deck's rectangle is given. A deck is
#: a line, so the number decides nothing about the drawing except how
#: much room a bubble cap or a valve has to stand up in; ISO's own decks
#: are drawn in a 2 M band on an 18 M body.
_DECK_BAND = 2.0 / 18.0

#: How far a deck is held off the shell wall, as a fraction of the body's
#: width. **Zero**: ISO item 2.6 runs every deck wall to wall, and a
#: tray that stops short of the shell is a tray with a gap the vapour
#: would go round.
_DECK_INSET = 0.0


def internals_overlays(name: str, count: int = 1, registry=None) -> tuple:
    """``count`` of ``name``, stacked down a vertical body.

    A **deck** repeats: ``count`` decks are ``count`` overlays evenly
    spaced down the internals band, which is what makes a thirty-tray
    column thirty placements rather than a number in a drawing.

    A **bed** does not. ISO draws one packed bed filling the space it
    occupies, so ``count`` beds are ``count`` bands stacked down that
    same span with a gap between them -- which is a two-bed absorber,
    drawn by asking for two.

    Which of the two a part is comes off its own frame: every group-27
    deck is drawn in the 10 M x 2 M frame :data:`DECK_H` names, and the
    two beds are drawn in boxes of their own that are taller than it.
    """
    from pandid.render.symbols import Overlay
    part = _part(27, name, registry)
    if count < 1:
        raise ValueError(
            f"a body with {count} of an internal has none of it; pass "
            f"internals=None to draw a bare shell"
        )
    top, span = _INTERNALS_TOP, _INTERNALS_BOTTOM - _INTERNALS_TOP
    width = 1.0 - 2 * _DECK_INSET
    if part.height <= DECK_H:
        # A deck: a line at a height, repeated. The band is centred on
        # each deck's own share of the span, so the decks are evenly
        # pitched and the top and bottom ones are half a pitch inside
        # the span rather than sitting on its ends.
        pitch = span / count
        return tuple(
            Overlay(27, name, _DECK_INSET,
                    top + (i + 0.5) * pitch - _DECK_BAND / 2, width, _DECK_BAND)
            for i in range(count))
    # A bed: a band with a tenth of its height clear above and below, so
    # two beds read as two rather than as one tall one.
    band = span / count
    return tuple(
        Overlay(27, name, _DECK_INSET, top + (i + 0.1) * band, width, band * 0.8)
        for i in range(count))


def stage_fraction(name: str, stage: int, count: int, registry=None) -> float:
    """Where stage ``stage`` of ``count`` sits, as a fraction of the body's box.

    The same reading :func:`internals_overlays` lays the internals band out
    with, so a feed asked for stage ``k`` lands on the deck it names (or
    above the bed it names) rather than somewhere close to it -- the two
    read off the one pair of constants and cannot drift apart.

    A **deck** stage is numbered top to bottom, 1 at the top, and lands on
    the centre of its own pitch: the same point the tray line itself is
    centred on.

    A **bed** stage lands on the *top* of the bed it names, not through it
    -- a packed tower's feed enters above the packing, where the liquid
    distributor sits, and never through the middle of the bed itself.
    """
    if stage < 1 or stage > count:
        raise ValueError(
            f"stage {stage} is not on a column of {count}; a stage counts from 1 "
            f"at the top to {count} at the bottom, the same count trays= gives"
        )
    part = _part(27, name, registry)
    top, span = _INTERNALS_TOP, _INTERNALS_BOTTOM - _INTERNALS_TOP
    step = span / count
    if part.height <= DECK_H:
        return top + (stage - 0.5) * step
    return top + (stage - 1 + 0.1) * step


#: How far below the body's box a support reaches, and how wide a leg is,
#: as fractions of the body's box. A support is drawn *under* the vessel,
#: so the rectangle starts just inside the bottom of the box and runs out
#: of it; ``compose`` grows the composed box to hold it and moves the
#: body down into it.
_SUPPORT_TOP, _SUPPORT_DROP = 0.97, 0.28


def support_overlays(name: str, registry=None) -> tuple:
    """``name``'s supports, standing under or beside a vertical body.

    ISO group 1 items 1.16 to 1.19 are this composition drawn out -- one
    vessel outline and one group-26 element each -- so what varies is
    only where the element goes, and that follows from what the element
    is:

    - a **leg** (26.1, a 1 M x 5 M channel) is one of a pair under the
      two walls;
    - a **skirt** (26.3, two walls 8 M apart) is one, spanning the body,
      because the item already draws both of its sides;
    - a **bracket** (26.2) and a **ring** (26.4) are **chiral**: Table 2
      draws each against a wall on one side. Both are drawn as a pair
      with the second mirrored, which is what :attr:`Overlay.mirror` is
      for, and both sit **on the shell wall** rather than under the
      floor, since that is what they bear on. A ring in particular is a
      4 M x 1 M ledge and reads as a ledge only when it is against
      something.
    """
    from pandid.render.symbols import Overlay
    _part(26, name, registry)
    if name == "skirt":
        return (Overlay(26, name, 0.20, _SUPPORT_TOP, 0.60, _SUPPORT_DROP),)
    if name in ("bracket", "ring"):
        # **Outside the box, not inside it.** Both bear on the *outer*
        # face of the shell, so each rectangle starts at a wall and runs
        # away from the body; ``compose`` grows the composed box to hold
        # the pair and moves the body into it.
        #
        # Table 2 draws both with the wall on their **right**, so the
        # unmirrored hand goes on the west wall and the mirror on the
        # east. Two-thirds of the way down the shell, which is where
        # draw.io's own "Vessel (Dished Ends, Ring)" puts the same pair
        # of lugs.
        depth, drop = 0.20, 0.10 if name == "ring" else 0.18
        return (Overlay(26, name, -depth, 0.62, depth, drop),
                Overlay(26, name, 1.0, 0.62, depth, drop, mirror=True))
    return (Overlay(26, name, 0.14, _SUPPORT_TOP, 0.10, _SUPPORT_DROP),
            Overlay(26, name, 0.76, _SUPPORT_TOP, 0.10, _SUPPORT_DROP))


#: Where a thickener's rake sits on the settling-tank body, as fractions
#: of its box. Read off the body pandid draws rather than off a Table 2
#: row, because there is no row: ISO 10628-2 has no thickener and no
#: rake, and the body under this one is draw.io's "Settling Tank" -- a
#: 100 x 80 box whose floor falls from the walls at y 55 to an apex at
#: (50, 80).
#:
#: The arms therefore run x 20..80 and stop at y 62, which is **above
#: the floor at their own outer ends** (the floor is at y 65 under x 20).
#: A rake ploughs the floor and does not go through it, so those two
#: numbers are the one thing this placement has to get right and they are
#: read off the same slope the outline is drawn from.
_RAKE_X, _RAKE_W, _RAKE_FOOT = 0.20, 0.60, 0.775


def rake_overlays(name: str, registry=None) -> tuple:
    """``name``'s stirrer, hung down the centre of a thickener.

    **One overlay and no motor**, which is where this parts company with
    :func:`agitator_overlays`. That helper draws item 20.6's electric
    motor over the crown because ISO item 1.27 X8006 draws one there, and
    :data:`~pandid.render.symbols.COMPOSED_APPARATUS` admits the motor
    on the strength of that one tabulated row. There is no such row for a
    thickener: a whole apparatus drawn inside another apparatus is two
    units on one tag unless the standard itself composed them, and the
    standard did not compose this. So the rake is drawn and its drive is
    not -- an author who needs the drive on the sheet draws it beside the
    thickener and tags it, which is the answer that dict already gives.

    The **group-28 part is the rake**, and that is a claim worth being
    exact about. ISO 10628-2 clause 5 has composing from groups 26 to 29
    when the symbol wanted is not tabulated, and this one is not
    tabulated: what a thickener has turning in it is a slow central
    shaft carrying arms, which is what group 28 draws ten forms of. Item
    28.4's cross-beam is the nearest of the ten and is what
    :class:`~pandid.units.Thickener` asks for unless told otherwise; the
    other nine are reachable because a rake is a real mechanism with real
    variety and the standard has already drawn the vocabulary.
    """
    from pandid.render.symbols import Overlay
    _part(28, name, registry)
    return (Overlay(28, name, _RAKE_X, 0.0, _RAKE_W, _RAKE_FOOT),)


#: The group-11 body's box, in grid modules. Read off every one of the
#: twelve rows: top edge x 7..17, bottom edge x 9..15, y 4..10. The
#: crusher and mill drawings in :mod:`pandid.render.symbols` are built at
#: :data:`M` units to the module, so this box *is* their box and a
#: fraction of one is a fraction of the other.
CRUSHER_MODULES_W, CRUSHER_MODULES_H = 10.0, 6.0

#: How wide 29.14's arrows are drawn **inside a mill**, in modules. Its
#: own row (and so the part) draws them 3 M across; ISO item 11.12 draws
#: them 2 M across, inside the drum. The part is squeezed to match,
#: because the row is the drawing this reproduces.
_VIBRATION_IN_MILL = 2 * M


def crushing_overlays(name: str, registry=None) -> tuple:
    """``name``'s characteristic, centred in an ISO group-11 body.

    **One rule for all nine**, rather than a rectangle each: Table 2
    centres every mark on the body's box -- x 12 and y 7 of a box running
    x 7..17 and y 4..10 -- and draws it at exactly the size its own
    group-29 row draws it at. So the placement follows from the part's
    declared box and nothing has to be measured twice. Checked mark by
    mark against rows 11.3 to 11.12; :data:`_VIBRATION_IN_MILL` is the
    one size the standard changes and it is stated there.

    The one departure is the **jaw**, item 11.5: Table 2 shifts it half a
    module left, to x 9..14 rather than 9,5..14,5, so that a mark of odd
    width still lands on grid dots. pandid's bodies are not drawn on the
    2,5 mm grid -- there are no dots to land on -- so it is centred with
    the other eight, which is half a module on a ten-module box.
    """
    from pandid.render.symbols import Overlay
    part = _part(29, name, registry)
    width = _VIBRATION_IN_MILL if name == "vibration" else part.width
    w, h = width / M / CRUSHER_MODULES_W, part.height / M / CRUSHER_MODULES_H
    return (Overlay(29, name, (1 - w) / 2, (1 - h) / 2, w, h),)


def characteristic_overlays(name: str, registry=None) -> tuple:
    """``name``'s characteristic, inside a separating vessel.

    Placed where ISO's own group-8 rows place it, measured against the
    6 M x 9 M outline those rows share (walls at x 9 and 15, top edge at
    y 1, apex at y 10):

    - **29.1** the settling arrow, item 8.3 X8031: on the centre line,
      from the top edge down to y 6 -- half the body's depth, head and
      all.
    - **29.2** and **29.3**, items 8.6 X8125 and 8.8 X8126: across the
      body's middle, the plates at y 5 to 7 and the coil on y 5.
    """
    from pandid.render.symbols import Overlay
    _part(29, name, registry)
    if name == "gravity":
        # x 11..13 of 9..15, y 1..6 of 1..10.
        return (Overlay(29, name, 1 / 3, 0.0, 1 / 3, 5 / 9),)
    # x 10..14 of 9..15, y 4..7 of 1..10 -- a module of air above and
    # below the mark, so a wide body letterboxes it on its own height
    # rather than on the walls.
    return (Overlay(29, name, 1 / 6, 1 / 3, 2 / 3, 1 / 3),)
