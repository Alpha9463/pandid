"""ISO 10628-2 Table 2 parts, the motor drive, and their placement.

Builds the group 26-29 parts and the item 20.6 motor on the :data:`M`
grid at :data:`PART_STROKE`, every agitator shaft one solid stroke, and
places each part on a body as fractions of the body's box.
"""

import functools
import math
from typing import TYPE_CHECKING

from pandid.render.weights import M, LineWeight

if TYPE_CHECKING:
    from pandid.render.symbols import Overlay, Symbol

#: Stroke width of every part, in drawing units.
PART_STROKE = LineWeight.DETAIL.width

_INK = f'fill="none" stroke="black" stroke-width="{PART_STROKE:g}"'
_SOLID_INK = 'fill="black" stroke="none"'

# cos 45 degrees, for item 29.8's arms.
_SQ2 = math.sqrt(2) / 2

# Dash patterns of items 27.5 (sieve deck) and 27.6 (filter insert).
_DASH_LONG = f'stroke-dasharray="{2 * M:g},{M:g}"'
_DASH_DOT = f'stroke-dasharray="{2 * M:g},{M:g},{M:g},{M:g}"'

#: Frame of the six group-27 decks, with the deck on its centre line.
DECK_W, DECK_H = 10 * M, 2 * M
_DECK_Y = M

#: Frame of the ten group-28 agitators, the shaft on its centre line.
AGITATOR_W, AGITATOR_H = 4 * M, 8 * M
_AG_X = AGITATOR_W / 2

# Prefix of the draw.io agitator shape names.
_AG = "mxgraph.pid.agitators."


def _g(name: str, *body: str) -> str:
    """Return one part's artwork wrapped in a ``<g>``.

    Parameters
    ----------
    name : str
        Suffix of the group id.
    *body : str
        SVG elements to wrap.

    Returns
    -------
    str
        The ``<g>`` group.
    """
    return f'<g id="part_{name}">{"".join(body)}</g>'


def _run(x0: float, x1: float, y: float = _DECK_Y, dash: str = "") -> str:
    """Return a horizontal stroke at ``y``, dashed by ``dash``.

    Parameters
    ----------
    x0 : float
        Start x.
    x1 : float
        End x.
    y : float, default=_DECK_Y
        Height of the stroke.
    dash : str, default=""
        ``stroke-dasharray`` attribute, or empty for a solid stroke.

    Returns
    -------
    str
        SVG ``<line>``.
    """
    return (f'<line x1="{x0:g}" y1="{y:g}" x2="{x1:g}" y2="{y:g}" {_INK}'
            + (f" {dash}" if dash else "") + "/>")


@functools.cache
def parts() -> tuple:
    """Return every part in Table 2 order, built once.

    Returns
    -------
    tuple[OverlayPart, ...]
        The parts.
    """
    from pandid.render.symbols import IsoPart, OverlayPart

    def deck(name, item, reg, descriptor, *ink):
        """Return a group-27 internal in the shared deck frame.

        Parameters
        ----------
        name : str
            Part name.
        item : str
            ISO item number.
        reg : str
            ISO registration number.
        descriptor : str
            ISO descriptor.
        *ink : str
            SVG elements of the part.

        Returns
        -------
        OverlayPart
            The part.

        Raises
        ------
        ValueError
            If ``name``, ``item``, ``reg`` or ``descriptor`` is invalid.
        """
        return OverlayPart(
            name=name, iso=IsoPart(27, item, reg, descriptor),
            svg=_g(f"27_{name}", *ink), width=DECK_W, height=DECK_H)

    def agitator(name, item, reg, descriptor, stencil, shaft_to, *blade):
        """Return a group-28 agitator with a shaft to ``shaft_to``.

        Parameters
        ----------
        name : str
            Part name.
        item : str
            ISO item number.
        reg : str
            ISO registration number.
        descriptor : str
            ISO descriptor.
        stencil : str
            draw.io stencil name.
        shaft_to : float
            Depth the shaft reaches.
        *blade : str
            SVG elements of the blade.

        Returns
        -------
        OverlayPart
            The part.

        Raises
        ------
        ValueError
            If ``name``, ``item``, ``reg`` or ``descriptor`` is invalid.
        """
        return OverlayPart(
            name=name, iso=IsoPart(28, item, reg, descriptor),
            svg=_g(f"28_{name}",
                   f'<line x1="{_AG_X:g}" y1="0" x2="{_AG_X:g}" y2="{shaft_to:g}" {_INK}/>',
                   *blade),
            width=AGITATOR_W, height=AGITATOR_H, drawio_shape=stencil,
            gravity_fixed=True)

    # Group 26: apparatus elements.

    leg = OverlayPart(
        name="leg", iso=IsoPart(26, "26.1", "C2005", "Support leg"),
        # A channel section, open at the top.
        svg=_g("26_leg",
               f'<path d="M 0 0 L 0 {5 * M:g} L {M:g} {5 * M:g} L {M:g} 0" {_INK}/>'),
        width=M, height=5 * M)

    bracket = OverlayPart(
        name="bracket", iso=IsoPart(26, "26.2", "C2006", "Support bracket"),
        # A gusset: a foot and a hypotenuse up to the wall.
        svg=_g("26_bracket",
               f'<path d="M {4 * M:g} {4 * M:g} L 0 {4 * M:g} L {4 * M:g} 0" {_INK}/>'),
        width=4 * M, height=4 * M)

    skirt = OverlayPart(
        name="skirt", iso=IsoPart(26, "26.3", "C2007", "Support skirt"),
        # Two walls, each turning inwards at the base ring.
        svg=_g("26_skirt",
               f'<path d="M 0 0 L 0 {4 * M:g} L {2 * M:g} {4 * M:g}" {_INK}/>'
               f'<path d="M {8 * M:g} 0 L {8 * M:g} {4 * M:g} '
               f'L {6 * M:g} {4 * M:g}" {_INK}/>'),
        width=8 * M, height=4 * M)

    ring = OverlayPart(
        name="ring", iso=IsoPart(26, "26.4", "C2008", "Support ring"),
        # The ring in section, open on the wall side.
        svg=_g("26_ring",
               f'<path d="M {4 * M:g} 0 L 0 0 L 0 {M:g} L {4 * M:g} {M:g}" {_INK}/>'),
        width=4 * M, height=M)

    def on_wall(name, item, reg, descriptor, depth, span, *runs):
        """Return a wall part drawn on a west, a north and a south wall.

        Parameters
        ----------
        name : str
            Part name; the north and south drawings add ``_up`` and
            ``_down``, the way the part points.
        item : str
            ISO item number.
        reg : str
            ISO registration number.
        descriptor : str
            ISO descriptor.
        depth : float
            Reach out from the wall.
        span : float
            Length along the wall.
        *runs : tuple[tuple[float, float], ...]
            Strokes as ``(out, along)`` points, ``out`` 0 at the far
            end and ``depth`` at the wall.

        Returns
        -------
        tuple[OverlayPart, OverlayPart, OverlayPart]
            The west, north and south drawings.
        """
        iso = IsoPart(26, item, reg, descriptor)
        # Each drawing's (x, y) for an (out, along) point.
        turns = {
            "": lambda out, along: (out, along),
            "_up": lambda out, along: (along, out),
            "_down": lambda out, along: (along, depth - out),
        }
        drawn = []
        for suffix, turn in turns.items():
            d = " ".join("M " + " L ".join("{:g} {:g}".format(*turn(*point)) for point in run)
                         for run in runs)
            w, h = (depth, span) if suffix == "" else (span, depth)
            drawn.append(OverlayPart(
                name=name + suffix, iso=iso,
                svg=_g(f"26_{name}{suffix}", f'<path d="{d}" {_INK}/>'), width=w, height=h))
        return tuple(drawn)

    # A 4 M neck flanged 1 M each side, and the cover 1 M beyond.
    manhole, manhole_up, manhole_down = on_wall(
        "manhole", "26.5", "X8159", "Manhole", 5 * M, 6 * M,
        ((5 * M, M), (M, M), (M, 0)),
        ((5 * M, 5 * M), (M, 5 * M), (M, 6 * M)),
        ((0, 0), (0, 6 * M)))

    # A 2 M stub ending in a 2 M flange face.
    socket, socket_up, socket_down = on_wall(
        "socket", "26.6", "X8160", "Socket, connection nozzle", 2 * M, 2 * M,
        ((2 * M, M), (0, M)),
        ((0, 0), (0, 2 * M)))

    # Group 27: internals. The six decks share DECK_W x DECK_H.

    tray = deck("tray", "27.1", "C2044", "Tray (general)", _run(0, DECK_W))

    baffle_tray = deck(
        "baffle_tray", "27.2", "X8166", "Tray with baffle",
        _run(0, 9 * M, dash=_DASH_LONG),
        # The baffle: a 1 M riser at the deck's end.
        f'<line x1="{9 * M:g}" y1="{_DECK_Y:g}" x2="{9 * M:g}" y2="0" {_INK}/>')

    bubble_cap_tray = deck(
        "bubble_cap_tray", "27.3", "C2010", "Tray, bubble-cap type",
        # The deck opens 2 M for the cap.
        _run(0, 4 * M), _run(6 * M, DECK_W),
        # The cap: an arc 4 M across, radius 4.25 M.
        f'<path d="M {3 * M:g} {_DECK_Y / 2:g} '
        f'A {4.25 * M:g} {4.25 * M:g} 0 0 1 {7 * M:g} {_DECK_Y / 2:g}" {_INK}/>')

    valve_tray = deck(
        "valve_tray", "27.4", "C2011", "Tray, valve type",
        _run(0, 4 * M), _run(6 * M, DECK_W),
        # The valve: the middle 2 M of the deck, lifted 0.5 M.
        _run(4 * M, 6 * M, y=_DECK_Y / 2))

    sieve_tray = deck(
        "sieve_tray", "27.5", "2602", "Sieve tray, screen or sieve element",
        _run(0, DECK_W, dash=_DASH_LONG))

    filter_insert = deck(
        "filter_insert", "27.6", "C2047", "Filter insert (general)",
        _run(0, DECK_W, dash=_DASH_DOT))

    fluidised_bed = OverlayPart(
        name="fluidised_bed", iso=IsoPart(27, "27.7", "2604", "Fluidized bed"),
        # Dots at a 2 M pitch in rows 1 M apart, alternate rows offset.
        svg=_g("27_fluidised_bed", "".join(
            f'<circle cx="{x:g}" cy="{y:g}" r="{M / 5:g}" {_SOLID_INK}/>'
            for row, y in enumerate(M / 2 + M * i for i in range(5))
            for x in (M + 2 * M * i + (M if row % 2 else 0)
                      for i in range(5 if row % 2 else 6)))),
        width=12 * M, height=5 * M)

    packing = OverlayPart(
        name="packing", iso=IsoPart(27, "27.8", "X8141", "packing"),
        # An X across the bed between two long-dashed lines.
        svg=_g("27_packing",
               _run(0, 8 * M, y=0, dash=_DASH_LONG),
               _run(0, 8 * M, y=7 * M, dash=_DASH_LONG),
               f'<path d="M 0 0 L {8 * M:g} {7 * M:g} '
               f'M {8 * M:g} 0 L 0 {7 * M:g}" {_INK}/>'),
        width=8 * M, height=7 * M)

    # Group 28: agitators. Each is a solid shaft and a blade.

    agitator_general = agitator(
        "agitator", "28.1", "2672", "Agitator (general), stirrer (general)",
        _AG + "agitator,_stirrer", 7 * M,
        # Two verticals with a diagonal between them.
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
        # A gate split by the shaft, each half crossed by a diagonal.
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
        # Two arms dropping to an arc 1 M below their feet.
        f'<path d="M 0 {5.5 * M:g} L 0 {7 * M:g} '
        f'A {2.5 * M:g} {2.5 * M:g} 0 0 0 {4 * M:g} {7 * M:g} '
        f'L {4 * M:g} {5.5 * M:g}" {_INK}/>')

    helical = agitator(
        "helical", "28.6", "C2023", "Agitator, helical type",
        _AG + "agitator_(helical)", 7.5 * M,
        # A helix seen edge on: three strokes, each 1 M lower.
        f'<path d="M 0 {5 * M:g} L {4 * M:g} {6 * M:g} L 0 {7 * M:g} '
        f'L {4 * M:g} {8 * M:g}" {_INK}/>')

    impeller = agitator(
        "impeller", "28.7", "C2024", "Agitator, impeller type",
        _AG + "agitator_(impeller)", 7.5 * M,
        # One blade in profile: an ogee, crossed at the shaft.
        f'<path d="M 0 {8 * M:g} C {0.2 * M:g} {7.2 * M:g} {M:g} {7.1 * M:g} '
        f'{2 * M:g} {7.5 * M:g} C {3 * M:g} {7.9 * M:g} {3.8 * M:g} {7.8 * M:g} '
        f'{4 * M:g} {7 * M:g}" {_INK}/>'
        f'<path d="M {1.4 * M:g} {7.8 * M:g} L {2.6 * M:g} {7.2 * M:g}" {_INK}/>')

    propeller = agitator(
        "propeller", "28.8", "C2025", "Agitator, propeller type",
        _AG + "agitator_(propeller)", 7.5 * M,
        # Two lobes meeting on the shaft, the blades crossing inside.
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
        # The disc edge on: a plate each side of the shaft, and the hub.
        f'<rect x="0" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<rect x="{3 * M:g}" y="{6 * M:g}" width="{M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {7 * M:g} L {3 * M:g} {7 * M:g}" {_INK}/>')

    turbine = agitator(
        "turbine", "28.10", "C2027", "Agitator, turbine type",
        _AG + "agitator_(turbine)", 8 * M,
        # A rotor split into a 2 M hub and a 1 M blade each side.
        f'<rect x="0" y="{6 * M:g}" width="{4 * M:g}" height="{2 * M:g}" {_INK}/>'
        f'<path d="M {M:g} {6 * M:g} L {M:g} {8 * M:g} '
        f'M {3 * M:g} {6 * M:g} L {3 * M:g} {8 * M:g}" {_INK}/>')

    # Group 20: item 20.6, the electric motor.

    motor = OverlayPart(
        name="motor", iso=IsoPart(20, "20.6", "C0082", "Electric motor (general)"),
        # A 4 M circle with an M in it, the M drawn as one stroke.
        svg=_g("20_motor",
               f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{2 * M:g}" {_INK}/>'
               f'<path d="M {1.25 * M:g} {3 * M:g} L {1.25 * M:g} {M:g} '
               f'L {2 * M:g} {2 * M:g} L {2.75 * M:g} {M:g} '
               f'L {2.75 * M:g} {3 * M:g}" {_INK}/>'),
        width=4 * M, height=4 * M,
        ports={"drive": (2 * M, 0.0)},
        gravity_fixed=True)

    # Group 29: internal characteristics. 29.1-29.3 go in a separating
    # vessel and 29.4-29.14 in a crushing or grinding body.

    gravity = OverlayPart(
        name="gravity", iso=IsoPart(29, "29.1", "C2028", "Gravity type, settling type"),
        # A 6 M arrow pointing down, with a solid head.
        svg=_g("29_gravity",
               f'<line x1="{M:g}" y1="0" x2="{M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<polygon points="{M:g},{6 * M:g} {0.73 * M:g},{5 * M:g} '
               f'{1.27 * M:g},{5 * M:g}" {_SOLID_INK}/>'),
        width=2 * M, height=6 * M,
        gravity_fixed=True)

    electrostatic = OverlayPart(
        name="electrostatic", iso=IsoPart(29, "29.2", "C2030", "Electrostatic type"),
        # Two plates a module apart, each with a lead from its middle.
        svg=_g("29_electrostatic",
               f'<path d="M {M:g} 0 L {M:g} {2 * M:g} '
               f'M {2 * M:g} 0 L {2 * M:g} {2 * M:g}" {_INK}/>'
               f'<path d="M 0 {M:g} L {M:g} {M:g} '
               f'M {2 * M:g} {M:g} L {3 * M:g} {M:g}" {_INK}/>'),
        width=3 * M, height=2 * M)

    electromagnetic = OverlayPart(
        name="electromagnetic", iso=IsoPart(29, "29.3", "C2031", "Electromagnetic type"),
        # A coil of three turns, with a lead at each end.
        svg=_g("29_electromagnetic",
               f'<path d="M 0 {M:g} L {0.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {2.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {4.5 * M:g} {M:g} '
               f'A {M:g} {M:g} 0 0 1 {6.5 * M:g} {M:g} '
               f'L {7 * M:g} {M:g}" {_INK}/>'),
        width=7 * M, height=M)

    disc_type = OverlayPart(
        name="disc", iso=IsoPart(29, "29.4", "C2033", "Disc type"),
        # A bladed rotor edge on: a shaft, two plates across it, and two
        # arms between them.
        svg=_g("29_disc",
               f'<line x1="{4 * M:g}" y1="0" x2="{4 * M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<line x1="{2 * M:g}" y1="{3 * M:g}" x2="{6 * M:g}" y2="{3 * M:g}" {_INK}/>'
               f'<line x1="{2 * M:g}" y1="{5 * M:g}" x2="{6 * M:g}" y2="{5 * M:g}" {_INK}/>'
               f'<line x1="0" y1="{4 * M:g}" x2="{3 * M:g}" y2="{4 * M:g}" {_INK}/>'
               f'<line x1="{5 * M:g}" y1="{4 * M:g}" x2="{8 * M:g}" y2="{4 * M:g}" {_INK}/>'),
        width=8 * M, height=5 * M)

    crushing = OverlayPart(
        name="crushing", iso=IsoPart(29, "29.5", "C0240", "Crushing"),
        # An X, corner to corner of a 4 M box.
        svg=_g("29_crushing",
               f'<path d="M 0 0 L {4 * M:g} {4 * M:g} '
               f'M {4 * M:g} 0 L 0 {4 * M:g}" {_INK}/>'),
        width=4 * M, height=4 * M)

    gear = OverlayPart(
        name="gear",
        # Three digits, as printed in Table 2.
        iso=IsoPart(29, "29.6", "C024", "Gear type, gearwheels type"),
        # Two 2 M wheels, centres 1.5 M apart, overlapping by 0.5 M.
        svg=_g("29_gear",
               f'<circle cx="{1.25 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'
               f'<circle cx="{2.75 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=4 * M, height=2 * M)

    hammer = OverlayPart(
        name="hammer", iso=IsoPart(29, "29.7", "C2034", "Hammer type"),
        # An X rotor with a crossbar, the hammer head, on each arm.
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
        # Item 29.5's X, cut back to a 2 M rotor on the crossing.
        svg=_g("29_impact",
               f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{M:g}" {_INK}/>'
               + "".join(
                   f'<line x1="{(2 + _SQ2 * sx) * M:g}" y1="{(2 + _SQ2 * sy) * M:g}" '
                   f'x2="{(2 + 2 * sx) * M:g}" y2="{(2 + 2 * sy) * M:g}" {_INK}/>'
                   for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)))),
        width=4 * M, height=4 * M)

    jaw = OverlayPart(
        name="jaw", iso=IsoPart(29, "29.9", "C2036", "Jaw type"),
        # The swing jaw and its eccentric: a line into a circle.
        svg=_g("29_jaw",
               f'<line x1="0" y1="{M:g}" x2="{3 * M:g}" y2="{M:g}" {_INK}/>'
               f'<circle cx="{4 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=5 * M, height=2 * M)

    liquid = OverlayPart(
        name="liquid", iso=IsoPart(29, "29.10", "321", "Liquid type, wet type"),
        # Two scallops, each an arc of a 2 M circle on a 1.85 M chord.
        svg=_g("29_liquid",
               f'<path d="M {0.15 * M:g} {0.19 * M:g} '
               f'A {M:g} {M:g} 0 0 0 {2 * M:g} {0.19 * M:g} '
               f'A {M:g} {M:g} 0 0 0 {3.85 * M:g} {0.19 * M:g}" {_INK}/>'),
        width=4 * M, height=M)

    roller = OverlayPart(
        name="roller", iso=IsoPart(29, "29.11", "C2037", "Roller type"),
        # Two 2 M rolls touching at the nip.
        svg=_g("29_roller",
               f'<circle cx="{M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'
               f'<circle cx="{3 * M:g}" cy="{M:g}" r="{M:g}" {_INK}/>'),
        width=4 * M, height=2 * M)

    cone = OverlayPart(
        name="cone", iso=IsoPart(29, "29.12", "C2038", "Cone type"),
        # The crushing head in section: a trapezoid.
        svg=_g("29_cone",
               f'<path d="M {M:g} 0 L {3 * M:g} 0 L {4 * M:g} {3 * M:g} '
               f'L 0 {3 * M:g} Z" {_INK}/>'),
        width=4 * M, height=3 * M)

    jet = OverlayPart(
        name="jet", iso=IsoPart(29, "29.13", "X8176", "Jet type"),
        # A 6 M circle, its horizontal diameter and two mirrored chords.
        svg=_g("29_jet",
               f'<circle cx="{3 * M:g}" cy="{3 * M:g}" r="{3 * M:g}" {_INK}/>'
               f'<line x1="0" y1="{3 * M:g}" x2="{6 * M:g}" y2="{3 * M:g}" {_INK}/>'
               f'<path d="M {1.39 * M:g} {0.47 * M:g} L {5.61 * M:g} {1.53 * M:g} '
               f'M {1.39 * M:g} {5.53 * M:g} L {5.61 * M:g} {4.47 * M:g}" {_INK}/>'),
        width=6 * M, height=6 * M)

    vibration = OverlayPart(
        name="vibration", iso=IsoPart(29, "29.14", "3831", "Vibration type"),
        # Two arrows on tracks a module apart, pointing opposite ways.
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
        manhole, manhole_up, manhole_down, socket, socket_up, socket_down,
        tray, baffle_tray, bubble_cap_tray, valve_tray, sieve_tray, filter_insert,
        fluidised_bed, packing,
        agitator_general, flat_blade, gate_paddle, cross_beam, anchor, helical,
        impeller, propeller, disc, turbine,
        motor,
        gravity, electrostatic, electromagnetic,
        disc_type, crushing, gear, hammer, impact, jaw, liquid, roller, cone,
        jet, vibration,
    )


# Placement helpers: each returns overlays placed as fractions of the
# body's box.


def _part(group: int, name: str, registry=None):
    """Return a part from ``registry`` or the default registry.

    Parameters
    ----------
    group : int
        ISO subject group.
    name : str
        Part name.
    registry : SymbolRegistry, optional
        Registry to read; the default registry when omitted.

    Returns
    -------
    OverlayPart
        The registered part.

    Raises
    ------
    ValueError
        If no part ``(group, name)`` is registered.
    """
    if registry is None:
        from pandid.render.symbols import default_registry as registry
    return registry.part(group, name)


# Motor diameter as a fraction of shell width, and its gap above the
# crown as a fraction of body height (item 1.27 X8006).
_MOTOR_WIDTH, _MOTOR_GAP = 1 / 3, 1 / 9

#: Motor diameter, and its gap above the body, on a body drawn to size
#: (item 1.27 X8006).
MOTOR_D, MOTOR_GAP = 2 * M, M

# Stirrer x, width and foot as fractions of the body (item 1.27).
_AGITATOR_X, _AGITATOR_W, _AGITATOR_FOOT = 0.26, 0.48, 0.76


def agitator_overlays(name: str, kind: str, variant: str,
                      drawn: "tuple[float, float] | None" = None,
                      foot: "float | None" = None) -> tuple:
    """Return an agitator and its motor placed on a vertical body.

    The stirrer is drawn in proportion to the body. On a body drawn
    at ``drawn``, the motor is :data:`MOTOR_D` across and
    :data:`MOTOR_GAP` above it, and the stirrer reaches ``foot``;
    otherwise the motor is a third of the body's width.

    Parameters
    ----------
    name : str
        Group-28 agitator name.
    kind : str
        Body kind.
    variant : str
        Body variant.
    drawn : tuple[float, float], optional
        Width and height the body is drawn at.
    foot : float, optional
        Depth the stirrer reaches on a body drawn at ``drawn``, as a
        fraction of its height; the foot of the body's west wall band
        if omitted.

    Returns
    -------
    tuple[Overlay, Overlay]
        The agitator, then the motor.

    Raises
    ------
    ValueError
        If ``name`` is not a registered agitator.
    ValueError
        If ``kind`` is registered without ``variant``.
    """
    from pandid.render.symbols import Overlay, default_registry
    _part(28, name)
    _part(20, "motor")
    body = default_registry.get(kind, variant)
    if drawn is None:
        # The height that keeps the motor round on this body.
        width, height, gap = _MOTOR_WIDTH, _MOTOR_WIDTH * body.width / body.height, _MOTOR_GAP
        foot = _AGITATOR_FOOT
    else:
        width, height, gap = MOTOR_D / drawn[0], MOTOR_D / drawn[1], MOTOR_GAP / drawn[1]
        if foot is None:
            foot = body.bands.get("W", (0.0, _AGITATOR_FOOT * body.height))[1] / body.height
    return (
        # The shaft reaches up to the motor.
        Overlay(28, name, _AGITATOR_X, -gap, _AGITATOR_W, foot + gap),
        # The motor, centred above the head.
        Overlay(20, "motor", (1 - width) / 2, -(gap + height), width, height),
    )


# Internals band as fractions of body height (item 2.6 X8011).
_INTERNALS_TOP, _INTERNALS_BOTTOM = 0.11, 0.89

# Height of one deck: a 2 M band on an 18 M body.
_DECK_BAND = 2.0 / 18.0


def internals_overlays(name: str, count: int = 1) -> tuple:
    """Return ``count`` group-27 internals stacked down a vertical body.

    Parameters
    ----------
    name : str
        Group-27 part name.
    count : int, default=1
        Number of internals.

    Returns
    -------
    tuple[Overlay, ...]
        One overlay per internal, top first.

    Raises
    ------
    ValueError
        If ``name`` is not a registered group-27 part.
    ValueError
        If ``count`` is less than 1.
    """
    from pandid.render.symbols import Overlay
    part = _part(27, name)
    if count < 1:
        raise ValueError(
            f"a body with {count} of an internal has none of it; pass "
            f"internals=None to draw a bare shell"
        )
    # Each internal spans the shell from wall to wall: a deck centred on
    # its stage, a bed filling the middle 0.8 of its band.
    if part.height <= DECK_H:
        return tuple(Overlay(27, name, 0.0, stage_fraction(name, i, count) - _DECK_BAND / 2,
                             1.0, _DECK_BAND) for i in range(1, count + 1))
    band = (_INTERNALS_BOTTOM - _INTERNALS_TOP) / count
    return tuple(Overlay(27, name, 0.0, stage_fraction(name, i, count), 1.0, band * 0.8)
                 for i in range(1, count + 1))


def stage_fraction(name: str, stage: int, count: int) -> float:
    """Return stage ``stage`` of ``count`` as a fraction of body height.

    Parameters
    ----------
    name : str
        Group-27 part name.
    stage : int
        Stage number, from 1 at the top.
    count : int
        Number of stages.

    Returns
    -------
    float
        Centre of a deck, or top of a bed.

    Raises
    ------
    ValueError
        If ``stage`` is not between 1 and ``count``.
    ValueError
        If ``name`` is not a registered group-27 part.
    """
    if stage < 1 or stage > count:
        raise ValueError(
            f"stage {stage} is not on a column of {count}; a stage counts from 1 "
            f"at the top to {count} at the bottom, the same count trays= gives"
        )
    part = _part(27, name)
    top, span = _INTERNALS_TOP, _INTERNALS_BOTTOM - _INTERNALS_TOP
    step = span / count
    if part.height <= DECK_H:
        return top + (stage - 0.5) * step
    return top + (stage - 1 + 0.1) * step


# Support top and depth as fractions of body height.
_SUPPORT_TOP, _SUPPORT_DROP = 0.97, 0.28

#: The group-26 parts ``supports=`` takes.
SUPPORTS = ("leg", "bracket", "skirt", "ring")

#: The group-26 parts placed on a wall, and the drawn reach out from it
#: and length along it of each.
WALL_PARTS = ("manhole", "socket")
MANHOLE_DEPTH, MANHOLE_SPAN = 1.5 * M, 1.8 * M
SOCKET_DEPTH, SOCKET_SPAN = M, M


#: Walls of a body drawn with detail standing off them, which a manhole
#: or socket would be drawn over.
_CLUTTERED = {
    # The stencil's own brackets.
    ("vessel", "dished"): ("W", "E"),
    # The heater.
    ("vessel", "electrical_heating"): ("E",),
}


def wall_point(kind: str, variant: str, face: str, fraction: float, what: str,
               body: "Symbol | None" = None) -> float:
    """Return where a fraction of the way along a wall falls on a body.

    Parameters
    ----------
    kind : str
        Body kind.
    variant : str
        Body variant.
    face : str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    fraction : float
        Fraction of the face, 0 at its top or left end.
    what : str
        The unit and the part, for messages, such as
        ``"D-101: the manhole at ('E', 0.3)"``.
    body : Symbol, optional
        The body drawn; the registered one if omitted.

    Returns
    -------
    float
        Coordinate along the face.

    Raises
    ------
    ValueError
        If the face has no clear straight wall, or the fraction is off
        it.
    """
    from pandid.render.symbols import default_registry, pinned
    body = body or default_registry.get(kind, variant)
    walls = [f for f, (lo, hi) in body.bands.items()
             if lo < hi and f not in _CLUTTERED.get((kind, variant), ())]
    if face not in walls:
        raise ValueError(
            f"{what} is on the {face} face, where a {variant!r} {kind} has no clear "
            f"straight wall; "
            + (f"put it on {' or '.join(map(repr, walls))}" if walls else
               "no face of that drawing has one, so draw it with variant='default'")
        )
    along = body.height if face in ("W", "E") else body.width
    lo, hi = body.bands[face]
    if not lo - 1e-9 <= fraction * along <= hi + 1e-9:
        raise ValueError(
            f"{what} is off the {face} wall, which runs from "
            f"{math.ceil(lo / along * 100) / 100:g} to {math.floor(hi / along * 100) / 100:g} "
            f"of the way {'down' if face in ('W', 'E') else 'across'} the face; "
            f"give a fraction in that range"
        )
    return pinned(fraction, along, body.bands[face])


def _fit(stated: "float | None", ends: list) -> float:
    """Return the scale that draws ``ends`` across ``stated`` units.

    Each end is ``(a, b)``, drawn at ``scale * a + b``: ``a`` in body
    units and ``b`` a fixed reach.

    Parameters
    ----------
    stated : float or None
        Drawn extent; ``None`` draws the body at its own size.
    ends : list[tuple[float, float]]
        Extreme points of the body, its parts and its wall parts.

    Returns
    -------
    float
        Scale; ``1`` when nothing is stated.
    """
    if stated is None:
        return 1.0
    return min((stated - (b1 - b0)) / (a1 - a0)
               for a1, b1 in ends for a0, b0 in ends if a1 > a0)


def wall_overlays(kind: str, variant: str, overlays: tuple, manholes: tuple,
                  sockets: tuple, size: tuple, who: str,
                  body: "Symbol | None" = None) -> tuple:
    """Return manholes and sockets placed on a body at their drawn size.

    A stated size is the drawn box, parts included; the body and its
    other parts stretch to fill what the wall parts leave of it.

    Parameters
    ----------
    kind : str
        Body kind.
    variant : str
        Body variant.
    overlays : tuple[Overlay, ...]
        The body's other parts.
    manholes, sockets : tuple[tuple[str, float], ...]
        ``(face, fraction)`` of each.
    size : tuple[float or None, float or None]
        Stated width and height of the drawn box, unturned.
    who : str
        Unit name, for messages.
    body : Symbol, optional
        The body drawn; the registered one if omitted.

    Returns
    -------
    tuple
        The wall parts; ``(socket_n, point)`` for each socket's flange
        face in body coordinates; and the ``(x, y)`` scale the stated
        size draws the composed body at.

    Raises
    ------
    ValueError
        If a placement is off the body's walls, or the stated size
        leaves no room for the body.
    """
    from pandid.render.symbols import Overlay, default_registry
    body = body or default_registry.get(kind, variant)
    bw, bh = body.width, body.height
    placed = [(name, face, wall_point(kind, variant, face, fraction,
                                      f"{who}: the {name} at {(face, fraction)!r}", body))
              for name, entries in (("manhole", manholes), ("socket", sockets))
              for face, fraction in entries]
    sizes = {"manhole": (MANHOLE_DEPTH, MANHOLE_SPAN), "socket": (SOCKET_DEPTH, SOCKET_SPAN)}
    # Ends along x and y: the body and its parts, then each wall part's.
    xs = [(0.0, 0.0), (bw, 0.0)] + [(o.x * bw, 0.0) for o in overlays] + [
        ((o.x + o.w) * bw, 0.0) for o in overlays]
    ys = [(0.0, 0.0), (bh, 0.0)] + [(o.y * bh, 0.0) for o in overlays] + [
        ((o.y + o.h) * bh, 0.0) for o in overlays]
    for name, face, t in placed:
        depth, span = sizes[name]
        across, along = (xs, ys) if face in ("W", "E") else (ys, xs)
        wall = 0.0 if face in ("W", "N") else (bw if face == "E" else bh)
        across += [(wall, 0.0), (wall, -depth if face in ("W", "N") else depth)]
        along += [(t, -span / 2), (t, span / 2)]
    sx, sy = _fit(size[0], xs), _fit(size[1], ys)
    if sx <= 0 or sy <= 0:
        raise ValueError(
            f"{who}: a box of {size[0] if sx <= 0 else size[1]:g} leaves no room for "
            f"the body beside its manholes and sockets; give a larger "
            f"{'width' if sx <= 0 else 'height'}"
        )
    parts: list[Overlay] = []
    ports: list[tuple[str, tuple[float, float]]] = []
    for name, face, t in placed:
        depth, span = sizes[name]
        if face in ("W", "E"):
            w, h = depth / sx, span / sy
            x, y = (-w if face == "W" else bw), t - h / 2
            point = (x if face == "W" else x + w, t)
        else:
            w, h = span / sx, depth / sy
            x, y = t - w / 2, (-h if face == "N" else bh)
            point = (t, y if face == "N" else y + h)
        drawing = name + {"N": "_up", "S": "_down"}.get(face, "")
        parts.append(Overlay(26, drawing, x / bw, y / bh, w / bw, h / bh, mirror=face == "E"))
        if name == "socket":
            ports.append((f"socket_{len(ports) + 1}", point))
    return tuple(parts), tuple(ports), (sx, sy)


def support_overlays(name: str) -> tuple:
    """Return a support placed under or beside a vertical body.

    Parameters
    ----------
    name : str
        Group-26 support name.

    Returns
    -------
    tuple[Overlay, ...]
        A skirt, or a pair of legs, brackets or rings.

    Raises
    ------
    ValueError
        If ``name`` is not one of :data:`SUPPORTS`.
    """
    from pandid._checks import suggest
    from pandid.render.symbols import Overlay
    if name not in SUPPORTS:
        wall = name.split("_")[0] if name.startswith(WALL_PARTS) else ""
        raise ValueError(
            f"supports={name!r} is not a support{suggest(name, SUPPORTS)}; supports= "
            f"takes {', '.join(map(repr, SUPPORTS))}"
            + (f". A {wall} sits on a wall: {wall}s=[('E', 0.3)]" if wall else "")
        )
    _part(26, name)
    if name == "skirt":
        return (Overlay(26, name, 0.20, _SUPPORT_TOP, 0.60, _SUPPORT_DROP),)
    if name in ("bracket", "ring"):
        # The unmirrored hand goes on the west wall.
        depth, drop = 0.20, 0.10 if name == "ring" else 0.18
        return (Overlay(26, name, -depth, 0.62, depth, drop),
                Overlay(26, name, 1.0, 0.62, depth, drop, mirror=True))
    return (Overlay(26, name, 0.14, _SUPPORT_TOP, 0.10, _SUPPORT_DROP),
            Overlay(26, name, 0.76, _SUPPORT_TOP, 0.10, _SUPPORT_DROP))


def _kept(start: float, size: float, natural: float, drawn: float) -> tuple[float, float]:
    """Return one axis of a part moved onto a body of another size.

    A part across the body's middle keeps its share of the body; any
    other part keeps its own size and its gap to the nearer end.

    Parameters
    ----------
    start, size : float
        The part's start and size, as fractions of the natural body.
    natural, drawn : float
        The natural and the drawn body's length on this axis.

    Returns
    -------
    tuple[float, float]
        Start and size as fractions of the drawn body.
    """
    lead, length, tail = start * natural, size * natural, (1 - start - size) * natural
    if start < 0.5 < start + size and start >= 0 and start + size <= 1:
        return start, size
    if start + size / 2 <= 0.5:
        return lead / drawn, length / drawn
    return (drawn - tail - length) / drawn, length / drawn


def anchored(overlay: "Overlay", natural: "Symbol", body: "Symbol") -> "Overlay":
    """Return a part placed for a natural body, moved onto a drawn one.

    The part keeps its own size and its distance from the body's nearer
    edges, so a support on a taller shell is the same support.

    Parameters
    ----------
    overlay : Overlay
        Placement on the natural body.
    natural : Symbol
        The body at its natural size.
    body : Symbol
        The body drawn.

    Returns
    -------
    Overlay
        Placement on ``body``.
    """
    from dataclasses import replace

    x, w = _kept(overlay.x, overlay.w, natural.width, body.width)
    y, h = _kept(overlay.y, overlay.h, natural.height, body.height)
    return replace(overlay, x=x, y=y, w=w, h=h)


def seated(overlay: "Overlay", body: "Symbol", variant: str) -> "Overlay":
    """Return a support moved to meet a vessel shell's outline.

    A leg or skirt keeps its foot and starts where the shell's bottom
    outline is highest across its width. A bracket or ring beside the
    shell slides up or down until it meets the stretch of the side the
    shell's outline reaches. Any other part is returned unchanged.

    Parameters
    ----------
    overlay : Overlay
        Placement on ``body``.
    body : Symbol
        The vessel shell drawn.
    variant : str
        The shell's variant.

    Returns
    -------
    Overlay
        Placement on ``body``.
    """
    from dataclasses import replace

    from pandid.render.symbols import vessel_floor, vessel_side

    w, h = body.width, body.height
    if overlay.name in ("bracket", "ring"):
        lo, hi = vessel_side(variant, h)
        top = min(max(overlay.y * h, lo - overlay.h * h), hi)
        return replace(overlay, y=top / h)
    if overlay.name not in ("leg", "skirt"):
        return overlay
    top = min(vessel_floor(variant, w, h, x * w) for x in (overlay.x, overlay.x + overlay.w))
    foot = (overlay.y + overlay.h) * h
    return replace(overlay, y=top / h, h=(foot - top) / h)


# Rake rectangle as fractions of the thickener body.
_RAKE_X, _RAKE_W, _RAKE_FOOT = 0.20, 0.60, 0.775


def rake_overlays(name: str) -> tuple:
    """Return a group-28 stirrer hung down the centre of a thickener.

    Parameters
    ----------
    name : str
        Group-28 agitator name.

    Returns
    -------
    tuple[Overlay]
        The stirrer.

    Raises
    ------
    ValueError
        If ``name`` is not a registered group-28 part.
    """
    from pandid.render.symbols import Overlay
    _part(28, name)
    return (Overlay(28, name, _RAKE_X, 0.0, _RAKE_W, _RAKE_FOOT),)


def hung_agitator(kind: str, name: str) -> tuple:
    """Return a group-28 agitator hung down the middle of a unit's
    agitated chamber: a crystallizer's draft tube, a flotation cell's
    tank or a mixer-settler's mixer.

    Parameters
    ----------
    kind : str
        ``"crystallizer"``, ``"flotation_cell"`` or ``"mixer_settler"``.
    name : str
        Group-28 agitator name.

    Returns
    -------
    tuple[Overlay]
        The agitator.

    Raises
    ------
    ValueError
        If ``name`` is not a registered group-28 part.
    """
    from pandid.render import symbols as s
    room, width, foot, body_w, body_h = {
        "crystallizer": (s.CRYST_W, s.CRYST_AGITATOR_W, s.CRYST_AGITATOR_FOOT,
                         s.CRYST_W, s.CRYST_H),
        "flotation_cell": (s.FLOT_TANK_W, s.FLOT_AGITATOR_W, s.FLOT_AGITATOR_FOOT,
                           s.FLOT_W, s.FLOT_H),
        "mixer_settler": (s.MS_MIXER_W, s.MS_AGITATOR_W, s.MS_AGITATOR_FOOT,
                          s.MS_W, s.MS_H),
    }[kind]
    _part(28, name)
    return (s.Overlay(28, name, (room - width) / 2 / body_w, 0.0, width / body_w,
                      foot / body_h),)


#: Group-11 crusher and mill body box, in grid modules.
CRUSHER_MODULES_W, CRUSHER_MODULES_H = 10.0, 6.0

# Width of item 29.14's arrows inside a mill (item 11.12).
_VIBRATION_IN_MILL = 2 * M


def crushing_overlays(name: str, registry=None) -> tuple:
    """Return a group-29 characteristic centred in a group-11 body.

    Parameters
    ----------
    name : str
        Group-29 part name.
    registry : SymbolRegistry, optional
        Registry to read; the default registry when omitted.

    Returns
    -------
    tuple[Overlay]
        The characteristic.

    Raises
    ------
    ValueError
        If ``name`` is not a registered group-29 part.
    """
    from pandid.render.symbols import Overlay
    part = _part(29, name, registry)
    width = _VIBRATION_IN_MILL if name == "vibration" else part.width
    w, h = width / M / CRUSHER_MODULES_W, part.height / M / CRUSHER_MODULES_H
    return (Overlay(29, name, (1 - w) / 2, (1 - h) / 2, w, h),)


def characteristic_overlays(name: str, registry=None) -> tuple:
    """Return a group-29 characteristic in a separating vessel.

    Parameters
    ----------
    name : str
        Group-29 part name.
    registry : SymbolRegistry, optional
        Registry to read; the default registry when omitted.

    Returns
    -------
    tuple[Overlay]
        The characteristic.

    Raises
    ------
    ValueError
        If ``name`` is not a registered group-29 part.
    """
    from pandid.render.symbols import Overlay
    _part(29, name, registry)
    if name == "gravity":
        # Item 8.3: x 11..13 of 9..15, y 1..6 of 1..10.
        return (Overlay(29, name, 1 / 3, 0.0, 1 / 3, 5 / 9),)
    # Items 8.6 and 8.8: x 10..14 of 9..15, y 4..7 of 1..10.
    return (Overlay(29, name, 1 / 6, 1 / 3, 2 / 3, 1 / 3),)
