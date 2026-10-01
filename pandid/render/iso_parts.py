"""ISO 10628-2:2012 Table 2 supplementary symbols, and the motor drive.

Groups 26 (apparatus elements), 27 (internals), 28 (agitators) and 29
(internal characteristics) are the parts apparatus are composed from;
clause 5 requires composing from them for any symbol the standard does not
tabulate. :mod:`pandid.render.symbols` supplies the mechanism (``IsoPart``,
``Overlay``, ``OverlayPart``, ``compose``) and this module the artwork.

Item 20.6, the electric motor, is a whole machine (group 20, drives), but
ISO composes it itself: item 1.27 X8006 is a vessel with a group-28
stirrer and a motor on its shaft above the head. See
``symbols.COMPOSED_APPARATUS``.

The helpers at the end place each part on a body, as fractions of the
body's box. ``Reactor(agitator=)``, ``Column(internals=)``,
``Vessel(supports=)``, ``Separator(characteristic=)`` and
``Thickener(rake=)`` all use them.

Provenance
----------
Original artwork built to the standard's stated construction. Each part
was measured off Table 2 in grid modules (extent, end points, dash
pitches) and redrawn on pandid's grid; no path was traced, copied or
converted from the document.

Grid and line weight
--------------------
ISO 14617-1:2025 4.3 and ISO 10628-2 clause 5 lay symbols on a 2.5 mm
grid. :data:`M` is that module in drawing units, so a coordinate of
``4 * M`` is four grid dots. Parts are drawn at :data:`PART_STROKE`, the
DETAIL rung (ISO 10628-1:2014 5.3.1 c), 1 unit), since they are detail
inside an outline. ``compose`` keeps the width fixed when a part is
scaled, as ISO 14617-1 4.3 requires.

Conventions
-----------
- **No connection ticks.** Table 2's short strokes beside a symbol mark a
  preferred connection point and are not part of it (clause 5); pandid
  states placement in ``ports``. Every group-28 shaft is one solid
  stroke; ``tests/test_iso_parts.py`` checks this.
- **Every part stretches.** ``stretchable=False`` would letterbox the part
  on its rectangle and make the whole composed symbol unstretchable,
  unlike neighbouring stencils, and draw.io's agitator stencils are all
  ``aspect="variable"``. Legibility comes from giving each part a
  rectangle of about its own aspect.
- **No part is directional.** Holding artwork still under a flip is only
  sound when the body is symmetric; a part cannot promise that.
  Orientation limits are stated with ``gravity_fixed`` (ISO 14617-1 4.5).
- **Only the motor has a port.** ``drive`` is at the top of the motor, the
  only machine here; the shaft below is part of it.

The parts are built inside :func:`_build`, importing ``IsoPart`` and
``OverlayPart`` on first call, because :mod:`pandid.render.symbols`
registers these parts while its own module body is still executing.
"""

import math

# M is the ISO 14617-1 4.3 grid module, shared with the line weights.
from pandid.render.weights import M, LineWeight

#: Stroke width of every part, in drawing units: ISO 10628-1:2014 5.3.1 c),
#: one rung below the outline the part sits inside.
PART_STROKE = LineWeight.DETAIL.width

# Stroke attributes shared by every part, so all parts use one weight.
_INK = f'fill="none" stroke="black" stroke-width="{PART_STROKE:g}"'
_SOLID_INK = 'fill="black" stroke="none"'

# cos 45 degrees: item 29.8's arms start on its rotor's rim, which is what
# distinguishes it from 29.5's plain X.
_SQ2 = math.sqrt(2) / 2

# Table 2 dash pitches: 27.5's sieve deck is 2 M dash, 1 M gap; 27.6's
# filter insert alternates that with a 1 M dash.
_DASH_LONG = f'stroke-dasharray="{2 * M:g},{M:g}"'
_DASH_DOT = f'stroke-dasharray="{2 * M:g},{M:g},{M:g},{M:g}"'

#: Frame shared by the six group-27 decks: 10 M by 2 M, the deck on the
#: centre line and any cap or valve above it. Callers should keep about
#: this aspect, or a bubble cap is smeared.
DECK_W, DECK_H = 10 * M, 2 * M
_DECK_Y = M

#: Frame shared by the ten group-28 agitators: 4 M by 8 M, the shaft on the
#: centre line from the top down to the blade, so agitators are
#: interchangeable on a body.
AGITATOR_W, AGITATOR_H = 4 * M, 8 * M
_AG_X = AGITATOR_W / 2

# Prefix of draw.io's agitator stencils, which match ISO group 28 item for
# item, so a composed reactor exports with a real agitator.
_AG = "mxgraph.pid.agitators."


def _g(name: str, *body: str) -> str:
    """Return one part's artwork wrapped in a ``<g>`` as ``compose`` expects.

    ``compose`` copies only the group's contents, so the id is never
    emitted.

    Parameters
    ----------
    name : str
        Part name, used in the id.
    *body : str
        SVG elements.

    Returns
    -------
    str
        SVG group.
    """
    return f'<g id="part_{name}">{"".join(body)}</g>'


def _run(x0: float, x1: float, y: float = _DECK_Y, dash: str = "") -> str:
    """Return one horizontal deck stroke.

    Parameters
    ----------
    x0, x1 : float
        Stroke ends.
    y : float, default=_DECK_Y
        Height.
    dash : str, default=""
        ``stroke-dasharray`` attribute, or empty for solid.

    Returns
    -------
    str
        SVG ``<line>``.
    """
    return (f'<line x1="{x0:g}" y1="{y:g}" x2="{x1:g}" y2="{y:g}" {_INK}'
            + (f" {dash}" if dash else "") + "/>")


def _build() -> tuple:
    """Return every part, built on first use.

    Imports the part classes here to avoid an import cycle with
    :mod:`pandid.render.symbols`.

    Returns
    -------
    tuple[OverlayPart, ...]
        Parts in Table 2 order.
    """
    from pandid.render.symbols import IsoPart, OverlayPart

    def deck(name, item, reg, descriptor, *ink):
        """Return a group-27 internal in the shared deck frame."""
        return OverlayPart(
            name=name, iso=IsoPart(27, item, reg, descriptor),
            svg=_g(f"27_{name}", *ink), width=DECK_W, height=DECK_H)

    def agitator(name, item, reg, descriptor, stencil, shaft_to, *blade):
        """Return a group-28 agitator: shaft down to ``shaft_to``, then blade.

        ``stencil`` is the matching draw.io ``mxgraph.pid.agitators``
        shape; ``tests/test_drawio.py`` checks the keys against the
        stencil XML.
        """
        return OverlayPart(
            name=name, iso=IsoPart(28, item, reg, descriptor),
            svg=_g(f"28_{name}",
                   f'<line x1="{_AG_X:g}" y1="0" x2="{_AG_X:g}" y2="{shaft_to:g}" {_INK}/>',
                   *blade),
            width=AGITATOR_W, height=AGITATOR_H, drawio_shape=stencil,
            # No port: the motor (item 20.6) carries ``drive``. A turned
            # agitator would hang sideways in an upright vessel, so the
            # body carrying it may not be turned (ISO 14617-1 4.5).
            gravity_fixed=True)

    # ------------------------------------------------------------
    # Group 26 -- apparatus elements
    #
    # Supports, drawn under or around the body. 26.5 manhole and 26.6
    # socket are omitted: they sit on the vessel wall, whose position
    # depends on the body. 26.2's bracket and 26.4's ring are drawn in
    # the hand Table 2 uses; the other hand is a mirrored Overlay.
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
    # Six decks share DECK_W x DECK_H; the two beds have their own boxes.
    # 27.8 packing is also group 2's fixed bed, so packed columns,
    # packed-bed reactors and adsorbers share one drawing.
    # ------------------------------------------------------------

    tray = deck("tray", "27.1", "C2044", "Tray (general)", _run(0, DECK_W))

    baffle_tray = deck(
        "baffle_tray", "27.2", "X8166", "Tray with baffle",
        _run(0, 9 * M, dash=_DASH_LONG),
        # The baffle: a 1 M riser at the deck's end. Alternating ends on
        # consecutive decks is a placement for the caller.
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
    # Ten items differing only in the blade. Shafts are solid.
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
    # Only item 20.6, because ISO draws it inside item 1.27; other drives
    # are whole symbols with their own tags.
    # ------------------------------------------------------------

    motor = OverlayPart(
        name="motor", iso=IsoPart(20, "20.6", "C0082", "Electric motor (general)"),
        # Measured off row 20.6: a 4 M circle with the letter M in it.
        # The M is 1,5 M x 2 M on the circle's centre -- verticals at
        # x 1,25 and 2,75 running from y 1 to y 3, and a vee between
        # their tops that comes down to the centre and back up. Drawn as
        # one stroke, which is how the row draws it.
        #
        # Item 1.27 draws it at half size; that is a placement, made in
        # agitator_overlays.
        svg=_g("20_motor",
               f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{2 * M:g}" {_INK}/>'
               f'<path d="M {1.25 * M:g} {3 * M:g} L {1.25 * M:g} {M:g} '
               f'L {2 * M:g} {2 * M:g} L {2.75 * M:g} {M:g} '
               f'L {2.75 * M:g} {3 * M:g}" {_INK}/>'),
        width=4 * M, height=4 * M,
        # Power in, at the top of the motor.
        ports={"drive": (2 * M, 0.0)},
        # Inverted, the motor would hang under the vessel (ISO 14617-1 4.5).
        gravity_fixed=True)

    # ------------------------------------------------------------
    # Group 29 -- internal characteristics and built-in components
    #
    # All fourteen Table 2 items: how a body separates or crushes.
    # 29.1-29.3 compose onto group 8's separating vessel as items 8.3
    # X8031, 8.6 X8125 and 8.8 X8126 (Separator(characteristic=)); 29.4-29.14
    # go in group 11 crushing and grinding bodies. Group 29 has no vortex
    # or spray, so the cyclone (X2618) and item 8.7 X8033 cannot be
    # composed. Only 29.1 has a direction, so only it is gravity_fixed.
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
        # Flipped, the arrow would say the heavy phase rises, so the body
        # may not be turned (ISO 14617-1 4.5).
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

    # Registered as "disc" too: parts are keyed by (group, name), so it
    # does not clash with agitator 28.9.
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
        # C024 has three digits as printed in Table 2; _REG_NO allows it.
        iso=IsoPart(29, "29.6", "C024", "Gear type, gearwheels type"),
        # Two 2 M wheels meshing: centres 1,5 M apart, so they overlap
        # by half a module. The pair is 3,5 M across and the row's grid
        # box is 4 M, so the centres sit 0,75 M either side of the box's
        # middle with a quarter module of air at each end. 29.11 is the
        # same wheels just touching.
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
    """Return every part, in Table 2 order, built once and shared.

    Groups 26 to 29, with item 20.6 (the motor) after the agitators.

    Returns
    -------
    tuple[OverlayPart, ...]
        Parts; the registry holds the same objects.
    """
    global _PARTS
    if _PARTS is None:
        _PARTS = _build()
    return _PARTS


def register_parts(registry) -> None:
    """Register every part on ``registry``.

    Called by :meth:`pandid.render.symbols.SymbolRegistry.__init__` after
    the whole symbols.

    Parameters
    ----------
    registry : SymbolRegistry
        Registry to add the parts to.
    """
    for part in parts():
        registry.register_part(part)


# ----------------------------------------------------------------
# Where a part goes on a body.
#
# Rectangles are read off Table 2 and stated as fractions of the body's
# box, which is how Overlay is placed; fractions transfer to pandid's
# bodies, whose proportions differ from ISO's. Each helper names the item
# it was measured on. Parts fill their rectangle, so each rectangle keeps
# about the part's own aspect on its usual body.
# ----------------------------------------------------------------


def _part(group: int, name: str, registry=None):
    """Return a registered part, so a misspelt part fails at construction.

    Parameters
    ----------
    group : int
        ISO group.
    name : str
        Part name.
    registry : SymbolRegistry, optional
        Registry to ask; the default registry when omitted. Passed by
        ``SymbolRegistry._register_composed`` while it is being built.

    Returns
    -------
    OverlayPart
        The part.

    Raises
    ------
    ValueError
        If no such part is registered.
    """
    if registry is None:
        from pandid.render.symbols import default_registry as registry
    return registry.part(group, name)


# Motor diameter as a fraction of shell width, and its gap above the crown
# as a fraction of body height, from item 1.27 X8006 (6 M x 9 M body, 2 M
# motor one module above it).
_MOTOR_WIDTH, _MOTOR_GAP = 1 / 3, 1 / 9

# Stirrer rectangle from item 1.27: 48% of the shell width, centred, with
# its foot 76% of the way down.
_AGITATOR_X, _AGITATOR_W, _AGITATOR_FOOT = 0.26, 0.48, 0.76


def agitator_overlays(name: str, kind: str, variant: str, registry=None) -> tuple:
    """Return an agitator and its motor placed on a vertical body.

    ISO item 1.27 X8006 is the only tabulated stirred vessel and draws the
    item 20.6 motor above the head, so the motor always comes with the
    agitator. Measured off its 6 M x 9 M body: the blade is 48% of the shell
    width, centred, its foot 76% down; the shaft runs up to the motor, a
    2 M circle one module above the crown. ``compose`` grows the box
    upward to hold it.

    The motor's height is derived from the body's aspect, so it stays round
    on any body.

    Parameters
    ----------
    name : str
        Group-28 agitator name.
    kind, variant : str
        Body symbol.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay, Overlay]
        The agitator and the motor.

    Raises
    ------
    ValueError
        If the agitator is not registered.
    """
    from pandid.render.symbols import Overlay
    if registry is None:
        from pandid.render.symbols import default_registry as registry
    _part(28, name, registry)
    _part(20, "motor", registry)
    body = registry.get(kind, variant)
    # Keep the motor round: height is the width converted to this body.
    height = _MOTOR_WIDTH * body.width / body.height
    return (
        # The stirrer reaches up to the motor, so the shaft is one stroke.
        Overlay(28, name, _AGITATOR_X, -_MOTOR_GAP, _AGITATOR_W,
                _AGITATOR_FOOT + _MOTOR_GAP),
        # The motor, centred on the shaft, clear of the head.
        Overlay(20, "motor", (1 - _MOTOR_WIDTH) / 2, -(_MOTOR_GAP + height),
                _MOTOR_WIDTH, height),
    )


# Internals band as fractions of body height, from item 2.6 X8011: eight
# decks at y 6..20 on a body spanning y 4..22.
_INTERNALS_TOP, _INTERNALS_BOTTOM = 0.11, 0.89

# Height of one deck's rectangle: ISO's 2 M band on an 18 M body.
_DECK_BAND = 2.0 / 18.0

# Deck inset from the shell wall: zero, as item 2.6 runs decks wall to wall.
_DECK_INSET = 0.0


def internals_overlays(name: str, count: int = 1, registry=None) -> tuple:
    """Return ``count`` group-27 internals stacked down a vertical body.

    Decks are spaced evenly down the internals band, one overlay each.
    Beds (parts taller than :data:`DECK_H`) split the band into ``count``
    stacked beds with gaps between them.

    Parameters
    ----------
    name : str
        Group-27 part name.
    count : int, default=1
        Number of decks or beds.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay, ...]
        One overlay per deck or bed.

    Raises
    ------
    ValueError
        If the part is unknown or ``count`` is less than 1.
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
        # Decks: centre each on its share of the span.
        pitch = span / count
        return tuple(
            Overlay(27, name, _DECK_INSET,
                    top + (i + 0.5) * pitch - _DECK_BAND / 2, width, _DECK_BAND)
            for i in range(count))
    # Beds: leave a tenth of each band clear above and below.
    band = span / count
    return tuple(
        Overlay(27, name, _DECK_INSET, top + (i + 0.1) * band, width, band * 0.8)
        for i in range(count))


def stage_fraction(name: str, stage: int, count: int, registry=None) -> float:
    """Return a stage's height as a fraction of the body's box.

    Uses the same band as :func:`internals_overlays`. Stages count from 1
    at the top. A deck stage is the centre of its deck; a bed stage is the
    top of its bed, where a feed enters above the packing.

    Parameters
    ----------
    name : str
        Group-27 part name.
    stage : int
        Stage number.
    count : int
        Drawn number of decks or beds.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    float
        Fraction of the body height.

    Raises
    ------
    ValueError
        If ``stage`` is outside 1 to ``count`` or the part is unknown.
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


# Support rectangle top and depth, as fractions of body height. Supports
# start just inside the bottom of the box and extend below; ``compose``
# grows the box to hold them.
_SUPPORT_TOP, _SUPPORT_DROP = 0.97, 0.28


def support_overlays(name: str, registry=None) -> tuple:
    """Return a support placed under or beside a vertical body.

    ISO group 1 items 1.16 to 1.19 are these compositions. A leg (26.1) is
    a pair under the walls; a skirt (26.3) is one spanning the body. A
    bracket (26.2) or ring (26.4) is chiral, so it is a mirrored pair
    against the outer shell wall.

    Parameters
    ----------
    name : str
        ``"leg"``, ``"skirt"``, ``"bracket"`` or ``"ring"``.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay, ...]
        One or two overlays.

    Raises
    ------
    ValueError
        If the support is not registered.
    """
    from pandid.render.symbols import Overlay
    _part(26, name, registry)
    if name == "skirt":
        return (Overlay(26, name, 0.20, _SUPPORT_TOP, 0.60, _SUPPORT_DROP),)
    if name in ("bracket", "ring"):
        # Outside the box, against the outer shell. Table 2 draws the wall
        # on the right, so the unmirrored hand goes on the west wall,
        # two-thirds down the shell, as draw.io's ringed vessel does.
        depth, drop = 0.20, 0.10 if name == "ring" else 0.18
        return (Overlay(26, name, -depth, 0.62, depth, drop),
                Overlay(26, name, 1.0, 0.62, depth, drop, mirror=True))
    return (Overlay(26, name, 0.14, _SUPPORT_TOP, 0.10, _SUPPORT_DROP),
            Overlay(26, name, 0.76, _SUPPORT_TOP, 0.10, _SUPPORT_DROP))


# Rake rectangle on draw.io's 100 x 80 settling tank (ISO has no
# thickener): arms x 20..80, foot at y 62, just above the sloping floor
# (y 65 at x 20).
_RAKE_X, _RAKE_W, _RAKE_FOOT = 0.20, 0.60, 0.775


def rake_overlays(name: str, registry=None) -> tuple:
    """Return a group-28 stirrer hung down the centre of a thickener.

    No motor is drawn: ISO composes a motor inside an apparatus only for
    item 1.27 (``symbols.COMPOSED_APPARATUS``), so a rake drive is drawn
    and tagged separately. Item 28.4's cross-beam is the default rake
    (:class:`~pandid.units.Thickener`).

    Parameters
    ----------
    name : str
        Group-28 part name.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay]
        The rake overlay.

    Raises
    ------
    ValueError
        If the part is not registered.
    """
    from pandid.render.symbols import Overlay
    _part(28, name, registry)
    return (Overlay(28, name, _RAKE_X, 0.0, _RAKE_W, _RAKE_FOOT),)


#: Group-11 crusher and mill body box in grid modules (top edge x 7..17,
#: bottom x 9..15, y 4..10); pandid draws these bodies at :data:`M` units
#: per module.
CRUSHER_MODULES_W, CRUSHER_MODULES_H = 10.0, 6.0

# Width of 29.14's arrows inside a mill: 2 M, as item 11.12 draws them,
# against 3 M in their own row.
_VIBRATION_IN_MILL = 2 * M


def crushing_overlays(name: str, registry=None) -> tuple:
    """Return a group-29 characteristic centred in a group-11 body.

    Table 2 centres each mark on the body box at its own row's size,
    checked against rows 11.3 to 11.12. Vibration is drawn narrower
    (:data:`_VIBRATION_IN_MILL`). The jaw is centred too, though Table 2
    shifts it half a module to land on grid dots.

    Parameters
    ----------
    name : str
        Group-29 part name.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay]
        The characteristic overlay.

    Raises
    ------
    ValueError
        If the part is not registered.
    """
    from pandid.render.symbols import Overlay
    part = _part(29, name, registry)
    width = _VIBRATION_IN_MILL if name == "vibration" else part.width
    w, h = width / M / CRUSHER_MODULES_W, part.height / M / CRUSHER_MODULES_H
    return (Overlay(29, name, (1 - w) / 2, (1 - h) / 2, w, h),)


def characteristic_overlays(name: str, registry=None) -> tuple:
    """Return a group-29 characteristic placed in a separating vessel.

    Placed as ISO's group-8 rows place it on their shared 6 M x 9 M
    outline: 29.1's arrow on the centre line from the top down to mid
    depth (item 8.3 X8031); 29.2 and 29.3 across the middle (items 8.6
    X8125 and 8.8 X8126).

    Parameters
    ----------
    name : str
        ``"gravity"``, ``"electrostatic"`` or ``"electromagnetic"``.
    registry : SymbolRegistry, optional
        Registry; the default registry when omitted.

    Returns
    -------
    tuple[Overlay]
        The characteristic overlay.

    Raises
    ------
    ValueError
        If the part is not registered.
    """
    from pandid.render.symbols import Overlay
    _part(29, name, registry)
    if name == "gravity":
        # x 11..13 of 9..15, y 1..6 of 1..10.
        return (Overlay(29, name, 1 / 3, 0.0, 1 / 3, 5 / 9),)
    # x 10..14 of 9..15, y 4..7 of 1..10.
    return (Overlay(29, name, 1 / 6, 1 / 3, 2 / 3, 1 / 3),)
