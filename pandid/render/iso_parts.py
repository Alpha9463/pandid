"""ISO 10628-2:2012 Table 2 groups 26-29: the supplementary symbols.

Groups 1-25 of Table 1 name whole apparatus. Groups **26 apparatus
elements, 27 internals, 28 agitators and 29 internal characteristics**
are the *parts* those apparatus are built out of, and clause 5 makes
composing from them a ``shall`` for any symbol the standard does not
tabulate. :mod:`pandid.render.symbols` has the mechanism -- ``IsoPart``,
``Overlay``, ``OverlayPart`` and ``compose`` -- and this module is the
artwork it was waiting for.

Nothing here is drawn by any unit yet. Registering a part makes it
*available* to be overlaid; the keyword that puts one on a reactor or a
column is a separate change, and until it lands every symbol the library
ships is the drawing it has always been.

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
width by the scale first, per ISO 14617-1 §4.3's "when the size of a
symbol is changed, the line width shall be unchanged".

Connection ticks are not drawn
------------------------------
Table 2 draws a short thin stroke beside many symbols, offset by one
module from the artwork. Clause 5 column 3 says what it is: *"Preferred
locations of connections at graphical symbols are indicated by '—'. This
is not a part of the graphical symbol."* It is a placement note, and
pandid states placement in ``ports`` instead. That matters here because
an agitator's tick sits directly above its shaft with a one-module gap,
so a reader skimming the page sees a broken vertical line and concludes
the shaft is dashed. **It is not.** Every group-28 shaft in Table 2 is a
single solid stroke; the break is the gap between the tick and the
symbol. ``tests/test_iso_parts.py`` holds this module to it.

Which parts may be stretched
----------------------------
``stretchable=False`` where the *form* of the mark is what distinguishes
it from its siblings, since squashing it then destroys the only thing it
says: the ten group-28 agitators differ in nothing but the shape at the
foot of the shaft, and the group-29 characteristics differ in nothing but
the mark. Group 26's supports and group 27's decks are lines that follow
the body they are drawn in and are stretched with it. ISO 14617-1 §4.4
draws the line in the same place -- proportions may be modified, but "the
extent of modification of the symbol shape shall not make it impossible
to recognize the symbol".

Ports
-----
Only an agitator anchors one. ISO item 1.27 (X8006) runs the stirrer's
shaft up through the top head to a motor drawn above the vessel, so the
drive is a real connection at a real place; a tray and a settling arrow
are marks inside a body that no line ever reaches. Every group-28 part
therefore anchors ``drive`` at the top of its shaft and nothing else
anchors anything.

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

    def agitator(name, item, reg, descriptor, shaft_to, *blade):
        """A group-28 agitator: the shaft down to ``shaft_to``, then its
        blade, in the common agitator frame."""
        return OverlayPart(
            name=name, iso=IsoPart(28, item, reg, descriptor),
            svg=_g(f"28_{name}",
                   f'<line x1="{_AG_X:g}" y1="0" x2="{_AG_X:g}" y2="{shaft_to:g}" {_INK}/>',
                   *blade),
            width=AGITATOR_W, height=AGITATOR_H,
            # ISO item 1.27 (X8006) runs the shaft up through the top
            # head to a motor drawn above the vessel, so the drive is a
            # real connection at a real place on the drawing.
            ports={"drive": (_AG_X, 0.0)},
            stretchable=False,
            # Turned, the drive comes in from the side and the blade
            # hangs sideways in a vessel that is still upright; flipped,
            # the blade is on top and the drive underneath. Neither is
            # the equipment this draws, so ISO 14617-1 §4.5 applies to
            # the body carrying it even where the bare body was free.
            gravity_fixed=True, directional=True)

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
        "agitator", "28.1", "2672", "Agitator (general), stirrer (general)", 7 * M,
        # Two 2 M verticals 4 M apart with a diagonal falling between
        # them: the general stirrer, and the item every other one is a
        # specialisation of.
        f'<path d="M 0 {6 * M:g} L 0 {8 * M:g} '
        f'M 0 {6 * M:g} L {4 * M:g} {8 * M:g} '
        f'M {4 * M:g} {6 * M:g} L {4 * M:g} {8 * M:g}" {_INK}/>')

    flat_blade = agitator(
        "flat_blade", "28.2", "C2019", "Agitator, flat-blade paddle type", 4 * M,
        # A 4 M square hanging off the shaft's foot.
        f'<rect x="0" y="{4 * M:g}" width="{4 * M:g}" height="{4 * M:g}" {_INK}/>')

    gate_paddle = agitator(
        "gate_paddle", "28.3", "C2020", "Agitator, gate paddle type", 8 * M,
        # A 4 M x 2 M gate divided by the shaft, each half crossed by a
        # diagonal.
        f'<rect x="0" y="{6 * M:g}" width="{4 * M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M 0 {8 * M:g} L {2 * M:g} {6 * M:g} '
        f'M {2 * M:g} {8 * M:g} L {4 * M:g} {6 * M:g}" {_INK}/>')

    cross_beam = agitator(
        "cross_beam", "28.4", "C2021", "Agitator, cross-beam type", 8 * M,
        # Two 4 M beams 2 M apart, threaded on the shaft.
        f'<path d="M 0 {6 * M:g} L {4 * M:g} {6 * M:g} '
        f'M 0 {8 * M:g} L {4 * M:g} {8 * M:g}" {_INK}/>')

    anchor = agitator(
        "anchor", "28.5", "C2022", "Agitator, anchor type", 8 * M,
        # Two 1,5 M arms dropping to an arc that sweeps 1 M below their
        # feet: the blade that follows a dished bottom head.
        f'<path d="M 0 {5.5 * M:g} L 0 {7 * M:g} '
        f'A {2.5 * M:g} {2.5 * M:g} 0 0 0 {4 * M:g} {7 * M:g} '
        f'L {4 * M:g} {5.5 * M:g}" {_INK}/>')

    helical = agitator(
        "helical", "28.6", "C2023", "Agitator, helical type", 7.5 * M,
        # A helix seen edge on: three strokes across 4 M, descending 1 M
        # each, which is how Table 2 flattens a ribbon into two
        # dimensions.
        f'<path d="M 0 {5 * M:g} L {4 * M:g} {6 * M:g} L 0 {7 * M:g} '
        f'L {4 * M:g} {8 * M:g}" {_INK}/>')

    impeller = agitator(
        "impeller", "28.7", "C2024", "Agitator, impeller type", 7.5 * M,
        # A single blade in profile: an ogee about 4 M across and 1 M
        # deep, with the straight blade section crossing the shaft.
        f'<path d="M 0 {8 * M:g} C {0.2 * M:g} {7.2 * M:g} {M:g} {7.1 * M:g} '
        f'{2 * M:g} {7.5 * M:g} C {3 * M:g} {7.9 * M:g} {3.8 * M:g} {7.8 * M:g} '
        f'{4 * M:g} {7 * M:g}" {_INK}/>'
        f'<path d="M {1.4 * M:g} {7.8 * M:g} L {2.6 * M:g} {7.2 * M:g}" {_INK}/>')

    propeller = agitator(
        "propeller", "28.8", "C2025", "Agitator, propeller type", 7.5 * M,
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
        "disc", "28.9", "C2026", "Agitator, disc type", 7 * M,
        # The disc seen edge on: a 1 M x 2 M plate each side of the
        # shaft, joined across it by the hub.
        f'<rect x="0" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<rect x="{3 * M:g}" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {7 * M:g} L {3 * M:g} {7 * M:g}" {_INK}/>')

    turbine = agitator(
        "turbine", "28.10", "C2027", "Agitator, turbine type", 8 * M,
        # A 4 M x 2 M rotor split into three: the 2 M hub the shaft runs
        # into, and a 1 M blade each side of it.
        f'<rect x="0" y="{6 * M:g}" width="{4 * M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {6 * M:g} L {M:g} {8 * M:g} '
        f'M {3 * M:g} {6 * M:g} L {3 * M:g} {8 * M:g}" {_INK}/>')

    # ------------------------------------------------------------
    # Group 29 -- internal characteristics and built-in components
    #
    # The mark that says how a body does its separating. Table 2 has
    # fourteen; the three below are the three whose composition onto
    # group 8's separating vessel is verified glyph for glyph -- item 8.3
    # X8031 is the body carrying 29.1, 8.6 X8125 carries 29.2, and 8.8
    # X8126 carries 29.3.
    #
    # The other eleven are drawn when something composes from them, and
    # not before. Two absences are load-bearing rather than incidental:
    # there is **no vortex or cyclone item in group 29**, which is why
    # ISO 8.10 X2618 is a symbol in its own right and not a body plus a
    # characteristic; and there is no spray, which is why 8.7 X8033 -- a
    # body carrying both a spray mark and 29.2 -- cannot be composed
    # either, its spray having no group 26-29 number to be a part under.
    # ------------------------------------------------------------

    gravity = OverlayPart(
        name="gravity", iso=IsoPart(29, "29.1", "C2028", "Gravity type, settling type"),
        # A 6 M arrow pointing down, with the solid head Table 2 draws:
        # 1 M long and a little over half a module across.
        svg=_g("29_gravity",
               f'<line x1="{M:g}" y1="0" x2="{M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<polygon points="{M:g},{6 * M:g} {0.73 * M:g},{5 * M:g} '
               f'{1.27 * M:g},{5 * M:g}" {_SOLID_INK}/>'),
        width=2 * M, height=6 * M, stretchable=False,
        # The arrow *is* the statement that gravity does the work here,
        # so this is the case ISO 14617-1 §4.5's prohibition on turning
        # was written for -- and flipped, the same arrow says the heavy
        # phase rises.
        gravity_fixed=True, directional=True)

    electrostatic = OverlayPart(
        name="electrostatic", iso=IsoPart(29, "29.2", "C2030", "Electrostatic type"),
        # Two 2 M plates a module apart, each with a 1 M lead going out
        # from its middle.
        svg=_g("29_electrostatic",
               f'<path d="M {M:g} 0 L {M:g} {2 * M:g} '
               f'M {2 * M:g} 0 L {2 * M:g} {2 * M:g}" {_INK}/>'
               f'<path d="M 0 {M:g} L {M:g} {M:g} '
               f'M {2 * M:g} {M:g} L {3 * M:g} {M:g}" {_INK}/>'),
        width=3 * M, height=2 * M, stretchable=False)

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
        width=7 * M, height=M, stretchable=False)

    return (
        leg, bracket, skirt, ring,
        tray, baffle_tray, bubble_cap_tray, valve_tray, sieve_tray, filter_insert,
        fluidised_bed, packing,
        agitator_general, flat_blade, gate_paddle, cross_beam, anchor, helical,
        impeller, propeller, disc, turbine,
        gravity, electrostatic, electromagnetic,
    )


_PARTS: "tuple | None" = None


def parts() -> tuple:
    """Every group 26-29 supplementary symbol, in Table 2 order.

    Built once and shared, so a part asked for through the registry and a
    part read off this module are the same object.
    """
    global _PARTS
    if _PARTS is None:
        _PARTS = _build()
    return _PARTS


def register_parts(registry) -> None:
    """Register every group 26-29 supplementary symbol on ``registry``.

    Called from :meth:`pandid.render.symbols.SymbolRegistry.__init__`
    after the whole symbols, since a part is only ever overlaid on one.
    """
    for part in parts():
        registry.register_part(part)
