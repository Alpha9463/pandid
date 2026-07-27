"""SVG symbol registry for the topology primitives.

Equipment shapes follow the conventions of ISO 10628-2 and instrument balloons
follow ANSI/ISA-5.1. Neither set is certified conformant to anything, and the
stencil library the equipment comes from makes no standards claim of its own.
Sources:

- **Vendored (draw.io / diagrams.net P&ID stencils, Apache-2.0)** — valves and
  their variants, pumps, compressors, blowers, heat exchangers, vessels,
  columns, reactors, separators, tanks, reducers, in-line fittings, ejectors,
  vents and funnels. Converted from mxGraph
  stencil XML by ``scripts/vendor_symbols.py`` into ``_vendored_symbols.py`` and
  registered last (overriding the hand-drawn defaults of the same kind). See the
  repo ``NOTICE`` for attribution.
- **Hand-drawn primitives** — Feed/Product boundary markers, the variable-port
  Mixer and Splitter, and the pipe tee.
- **Built to size (draw.io-derived, Apache-2.0)** — the belt conveyor. Adapted
  from a stencil but drawn here rather than generated, because a fixed path
  cannot stretch; see :func:`conveyor_symbol` and the repo ``NOTICE``.

Authoring conventions (hand-drawn symbols)
------------------------------------------
- Local coordinates: (0, 0) top-left, spanning ``width`` × ``height``.
- Ports: named anchors on the boundary face a stream attaches to; names MUST
  match the owning :class:`~pandid.units.Unit`'s port names.
- Variants share a ``kind`` and register under a ``variant`` name.
- A symbol whose shape carries meaning — a balloon is a circle because ISA-5.1
  says a circle — sets ``stretchable=False``, and is centred in a box of another
  shape rather than distorted to fill it.
"""

import math
import re
import warnings
from dataclasses import InitVar, dataclass, field
from difflib import get_close_matches
from functools import lru_cache

from pandid.portgeom import outward_dir

# Two placements closer together than this are the same point as far as a reader
# (and a stream endpoint) is concerned.
_COINCIDENT = 0.5


@dataclass(frozen=True)
class PortSeries:
    """A family of like ports spread evenly along one face of a symbol.

    A :class:`~pandid.units.Mixer` does not have a fixed set of inlets — the unit
    decides how many there are — so the symbol cannot author a coordinate per
    port the way a pump authors its suction. It declares the *rule* instead, and
    the coordinates are resolved once the unit is in hand and the count is known.

    Members are ``prefix`` followed by a 1-based index (``in_1``, ``in_2``, ...),
    matching the names :class:`~pandid.units.Mixer` and
    :class:`~pandid.units.Splitter` generate. A family that is usually singular
    names its lone member ``singular`` instead: a :class:`~pandid.units.Column`
    with one feed has a nozzle called ``feed``, and only grows ``feed_1``,
    ``feed_2`` when it is given more than one.

    Ports sit ``pitch`` apart, centred on ``at`` — the point along the face the
    symbol would have drawn a single nozzle at, or the middle of the face when
    it names none. Past the point where that spacing would run them off the
    ends, the whole run is squeezed into ``extent`` of the face instead. The
    count the symbol was drawn for therefore lands exactly where a fixed symbol
    would put it, and one more does not shove the others aside to find room.
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
        """Symbol-space coordinate of member ``index`` of ``count`` (0-based)."""
        along = height if self.face in ("W", "E") else width
        centre = along / 2 if self.at is None else self.at
        span = min(self.pitch * (count - 1), self.extent * along)
        t = centre if count < 2 else centre - span / 2 + span * index / (count - 1)
        return {"W": (0.0, t), "E": (width, t),
                "N": (t, 0.0), "S": (t, height)}[self.face]

    def reach(self, width: float, height: float) -> tuple[float, float, float]:
        """Where members can land: ``(face_coordinate, lo, hi)`` along the face.

        A series has no fixed membership, so it has no fixed set of points to
        compare a nozzle against — it has a *stretch of face* it may put one on,
        for some count. One member sits at ``at``; the widest run spreads
        ``extent`` of the face around it. Anything inside that band shares a
        placement with a member sooner or later, which is what a collision check
        needs to know.
        """
        along = height if self.face in ("W", "E") else width
        centre = along / 2 if self.at is None else self.at
        half = self.extent * along / 2
        fixed = {"W": 0.0, "E": width, "N": 0.0, "S": height}[self.face]
        return fixed, centre - half, centre + half


@dataclass
class Symbol:
    """An SVG template for a unit, with named connection port anchors."""
    svg: str
    width: float
    height: float
    ports: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Every placement a port may take, keyed by the face it lands on, each with
    # its own exact coordinate so a moved port still lands on drawn ink:
    #   {"feed": {"W": (0.0, 15.0), "N": (30.0, 0.0), "E": (91.5, 15.0)}}
    # ``__post_init__`` folds the symbol's own nozzle in as the first entry, so
    # this is the *whole* menu — nothing downstream has to merge a privileged
    # default back in, and a nozzle fixed by physics (a drum's liquid draw is on
    # the bottom because gravity put it there) is simply one with a single entry.
    port_faces: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    # Connections with no face of their own. An instrument balloon is a circle,
    # so a signal may meet it anywhere and "in on the west, out on the east" is
    # an artefact of having to pick a default rather than physics. Only these
    # may offer each other the same face: the overlap is a menu, not a
    # collision, since one placement per port is ever live. Authoring
    # *alternates* for an equipment nozzle does not make it faceless — a drum's
    # inlet may be moved to the right head, but that is still the inlet's
    # nozzle and nothing else may sit on it.
    faceless_ports: frozenset[str] = frozenset()
    # Port families whose membership the *unit* decides — a Mixer's inlets. The
    # symbol cannot list them in ``ports`` because it does not know how many
    # there are, so it declares the rule and :mod:`pandid.portgeom` resolves the
    # coordinates against the unit. A series is the sole authority for its own
    # members; naming one in ``ports`` as well would be two answers to one
    # question, and is rejected below.
    port_series: tuple[PortSeries, ...] = ()
    label_pos: str | None = None
    # Tells two definitions of one (kind, variant) apart when they are not the
    # same drawing. A conveyor is built to its belt run rather than scaled to
    # it, so each length is its own ``<defs>`` entry and needs an id of its own;
    # every fixed symbol leaves this empty and shares one definition however it
    # is placed.
    id_suffix: str = ""
    # May the artwork be scaled unevenly to fill a box of another shape? A user
    # who sizes a unit is asking for a box, and a shell, tank or exchanger
    # simply becomes that box. A shape whose roundness carries meaning does not:
    # an instrument balloon is a circle because ISA-5.1 says a circle, so it
    # keeps its aspect and is centred in the box instead, leaving whitespace.
    #
    # The vendored symbols take this from the stencil's own ``aspect``
    # attribute, which is the draw.io author's statement about the same
    # question; ``variable`` is stretchable and ``fixed`` is not, and the
    # default here is theirs. :mod:`pandid.portgeom` resolves ports onto the
    # artwork either way -- a port in the letterbox would draw a stream that
    # stops short of its equipment.
    stretchable: bool = True
    # Deprecated spelling, accepted so a symbol authored against the old
    # interface still registers. ``port_alts`` listed only the *extra* faces.
    port_alts: InitVar[dict[str, dict[str, tuple[float, float]]] | None] = None
    free_ports: InitVar[frozenset[str] | None] = None

    def __post_init__(self, port_alts, free_ports) -> None:
        if free_ports is not None:
            warnings.warn(
                "Symbol.free_ports is now Symbol.faceless_ports.",
                DeprecationWarning, stacklevel=2,
            )
            self.faceless_ports = frozenset(self.faceless_ports) | frozenset(free_ports)
        declared = {name: dict(faces) for name, faces in self.port_faces.items()}
        if port_alts is not None:
            warnings.warn(
                "Symbol.port_alts is deprecated; declare the whole menu in "
                "Symbol.port_faces (the symbol's own nozzle is folded in for you).",
                DeprecationWarning, stacklevel=2,
            )
            for name, faces in port_alts.items():
                declared.setdefault(name, {}).update(faces)
        # Everything below rejects rather than repairs. Dropping a declaration
        # the engine cannot honour would be silent: the menu is re-keyed by
        # coordinate at resolve time, so a placement filed under the wrong face
        # simply ceases to exist, and a placement that vanishes is
        # indistinguishable from one that was never authored. The invariant
        # suite catches these for the shipped registry; a third-party symbol
        # only ever meets this constructor.
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
                    # ``ports`` is the authority on the home nozzle, so this
                    # placement could only ever be discarded.
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
        """The series that places ``port_name``, or None if it is a fixed nozzle."""
        for series in self.port_series:
            if series.matches(port_name):
                return series
        return None

    def symbol_id(self) -> str:
        """The svg id, for messages — a Symbol carries no name of its own."""
        match = re.search(r'\bid="([^"]+)"', self.svg)
        return match.group(1) if match else "<symbol>"

    def coincident_ports(self) -> list[tuple[str, str, tuple[float, float]]]:
        """Pairs of *different* ports sharing a placement, with the point.

        Two ports at one coordinate means a stream routed to one lands exactly
        on top of a stream routed to the other. Two placements of a *single*
        port may coincide — only one of them is ever live.

        :attr:`faceless_ports` are exempt from *each other*, not from the rule:
        they are still checked against the nozzles that do own their face. The
        exemption is a declaration, deliberately, rather than something read off
        the shape of the menu — "this connection is faceless" and "this nozzle
        has authored alternatives" both produce a multi-entry menu, and only the
        first of them justifies two ports sitting on one point.

        A :class:`PortSeries` is checked as the band of face it may place a
        member on, reported against ``prefix*``. Its membership belongs to the
        unit rather than the symbol, so there is no set of points to compare —
        but a nozzle standing inside that band shares a placement with a member
        for some count, and the whole value of a static check is saying so
        before a drawing is made.
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


# ---------------------------------------------------------------------------
# Belt conveyor.
#
# Derived from the draw.io / diagrams.net P&ID stencils (Apache-2.0): the shape
# ``Drier (Roller Conveyor Belt)`` in scripts/vendor_data/drawio/driers.xml
# (w=100, h=140, aspect="variable"). Two changes were made to it. The
# ``<background>`` drier housing is dropped, since the housing is the drier and
# not the conveyor, leaving the ``<foreground>`` roller belt alone. And the
# distance between the two rollers becomes a parameter, while the rollers keep
# the stencil's own r=10, so a longer conveyor grows its straight run and its
# rollers stay circles. See NOTICE, and ADAPTED_ELSEWHERE in
# scripts/vendor_symbols.py, which records the same provenance beside KIND_MAP,
# where the next person will look for it.
#
# It cannot come through that generator with the rest: the generator emits one
# fixed-size Symbol per shape, and a fixed drawing placed in a box of another
# aspect ratio is scaled unevenly — which would draw the rollers as ellipses,
# the one thing this symbol exists to avoid.
# ---------------------------------------------------------------------------

#: Roller radius, from the stencil's 20x20 roller ellipses. The same at every
#: length: only the straight belt run between the rollers grows.
CONVEYOR_ROLLER = 10.0
#: Default belt run, from the stencil's own proportions — it draws the rollers
#: centred at x=20 and x=80, so the conveyor spans x=10..90.
CONVEYOR_LENGTH = 80.0
#: Two roller diameters. Any shorter and the rollers overlap, leaving no belt.
CONVEYOR_MIN_LENGTH = 4 * CONVEYOR_ROLLER


def conveyor_too_short(length: float, owner: str = "") -> ValueError:
    """The error for a belt run the rollers do not leave room for.

    Built here so the message :class:`~pandid.units.Conveyor` raises up front and
    the one :func:`conveyor_symbol` raises later are the same sentence about the
    same rule.
    """
    return ValueError(
        f"{owner + ': ' if owner else ''}length={length:g} is shorter than a "
        f"conveyor can be drawn: the rollers are {CONVEYOR_ROLLER:g} in radius "
        f"and would overlap. Use length={CONVEYOR_MIN_LENGTH:g} or more, two "
        f"roller diameters."
    )


@lru_cache(maxsize=None)
def conveyor_symbol(length: float = CONVEYOR_LENGTH) -> Symbol:
    """A belt conveyor ``length`` long: two rollers and the belt run between.

    The symbol is *built* to the length rather than scaled to it, so its width
    **is** the length and the box a conveyor is placed in is exactly the box its
    artwork was drawn in. That is what holds the rollers to
    :data:`CONVEYOR_ROLLER` at every length.

    ``feed`` is the tail roller. Its home nozzle is the end of the belt, and it
    is offered on the top face as well, because material is dropped onto a
    conveyor rather than piped into it. ``discharge`` is the head roller, where
    the belt throws off; it is offered on the underside too, for the chute that
    catches what comes over. Every placement sits on a roller circle or on the
    end of a belt line, at any length.

    Cached, because port resolution asks for a unit's symbol on every call and
    the registry already hands out one shared instance per fixed symbol.
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
        # The rollers are circles, which is the whole reason this symbol is
        # built to its length instead of scaled to it. A Conveyor is sized by
        # ``length`` and refuses width/height, so its box is always exactly the
        # box it was drawn in and nothing ever asks — but the drawing says what
        # it is either way.
        stretchable=False,
    )


# Kinds whose artwork is built to a size the *unit* carries, rather than drawn
# once and scaled into whatever box it lands in. Uneven scaling is what turns a
# conveyor's rollers into ellipses, so its drawing has to be made to measure.
_BUILT_TO_SIZE = {"conveyor": lambda unit: conveyor_symbol(unit.length)}


# ---------------------------------------------------------------------------
# Devices drawn in a normal position.
#
# Normally closed valves: PIP PIC001 4.2.2.7 draws one with its body darkened
# solid. Not an ISA-5.1 convention -- ISA-5.1 says nothing about valve fill and
# leaves manual block valve depiction to the piping group -- and not an
# ISO 10628 one either, so a sheet that draws one owes its reader a legend
# entry (ISA-5.1 2.8.1(b)(1), 2.8.2, 5.2.5). See :class:`pandid.units.Valve`.
#
# A spectacle blind is the other case, and it is not the same one. Its position
# is not a mark applied to a symbol; it is *which symbol*, because the device is
# two discs and the drawing says which of them is in the line by filling it.
# The stencil set draws both, so the closed state is a registered shape rather
# than a derived one -- see ``SymbolRegistry.register_closed``. Nothing has to
# be declared on a legend for it: a solid disc blanking a line is the device's
# own long-standing convention rather than an extension of anybody's standard.
# ---------------------------------------------------------------------------

#: Valve variants whose body may be darkened. Filling a body leaves only its
#: *outline*, so the test is whether the outline alone still names the device.
#: A gate's pinched waist, a globe's and a ball's round one, an angle body's
#: right-angled lobes and a three-way's third lobe all survive, as do the marks
#: a plug and a pinch valve draw in the open notches above and below the waist,
#: the needle's stem across it, and every operator drawn *outside* the body --
#: the lettered boxes, the handwheel, the bleeder's tap.
#:
#: Everything else takes the NC abbreviation of clause 4.2.2.8 instead, which
#: is the safe default for a variant added later: a butterfly's disc (the
#: standard's own example), a check valve's flow arrow and a knife gate's blade
#: are all *inside* the outline, and a body filled over them draws a darkened
#: gate valve wearing another name.
#:
#: ``solenoid`` is on the list. Its stencil is called "Solenoid Valve Closed",
#: but the artwork is byte-for-byte the motor- and hydraulic-operated valves'
#: -- same body path, same operator box, differing only in the letter -- and
#: carries no fill of its own. The name is draw.io's label for the mechanism's
#: rest state, not something the drawing says, so the fill is the only thing on
#: that symbol that states a position.
NC_DARKENS = frozenset({
    "default", "gate", "globe", "ball", "needle", "plug", "pinch", "three_way",
    "angle", "bleed", "manual", "motor", "solenoid", "hydraulic",
})

#: Valve variants that may not be shown normally closed at all. PIP PIC001
#: clause 4.2.2.10: "Control valves or relief valves shall not be shown as NC."
#: A darkened control valve on an issued sheet reads as a block valve someone
#: has closed, which is a drafting error rather than a style.
NC_FORBIDDEN = frozenset({"control", "pneumatic", "regulator", "relief", "psv"})

#: The ink a darkened body is filled with -- the colour the vendored valve
#: artwork already strokes in, so the fill and the outline around it are one
#: solid symbol rather than a black shape in a grey frame.
_BODY_INK = "#111"

#: The body is the artwork's first ``<path>``. True of every variant in
#: :data:`NC_DARKENS` and checked rather than assumed, because
#: ``_vendored_symbols.py`` is generated: a stencil that grows a foreground
#: element ahead of its background one would otherwise have the wrong shape
#: filled, silently and plausibly.
_FIRST_PATH = re.compile(r"<path\b[^>]*>")


def closed_marking(unit, registry=None) -> str:
    """How a unit's normally closed position is drawn, ``""`` when it is not one.

    ``"stencil"`` swaps in a second drawing the stencil author already made --
    a spectacle blind's two states are two shapes, and the solid disc is the
    device's own convention rather than anything applied to it. ``"fill"``
    darkens the body (PIP PIC001 4.2.2.7), and ``"NC"`` is the abbreviation
    written beside a valve whose body cannot carry the fill (4.2.2.8).

    All three are one decision made in one place, so the renderer cannot letter
    a valve the registry has already darkened, or darken one it is about to
    letter. ``registry`` is the catalogue to answer against, since which
    devices have a second drawing is a fact about the symbols on hand.
    """
    if getattr(unit, "normal_position", "open") != "closed":
        return ""
    variant = getattr(unit, "variant", "")
    reg = default_registry if registry is None else registry
    if reg.closed_symbol(unit.kind, variant) is not None:
        return "stencil"
    # The fill and the abbreviation are the *valve* conventions of PIP PIC001,
    # and nothing else on a sheet is read by them. So a closed anything-else
    # whose variant has no second drawing has no way at all to say so. The unit
    # refuses that at construction; it can still be reached by assigning
    # ``variant`` afterwards, and drawing the open symbol would be the silent
    # failure -- an issued sheet showing a line that is open when it is blanked.
    if unit.kind != "valve":
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: {unit.kind}/{variant} is drawn one "
            f"way, so nothing can show it normally closed. Either it is the wrong "
            f"variant for a device that isolates a line, or normal_position should "
            f"be 'open'."
        )
    return "fill" if variant in NC_DARKENS else "NC"


def darkened(sym: Symbol) -> Symbol:
    """``sym`` with its body filled solid: the normally closed valve symbol.

    A separate ``Symbol`` rather than a fill applied at draw time, because the
    ``<defs>`` entry a ``<use>`` points at is keyed by the artwork: the open and
    the closed valve are two drawings and need two definitions, which is what
    the ``_nc`` :attr:`Symbol.id_suffix` buys. Everything else about the symbol
    -- box, nozzles, alternates, aspect -- is the same valve.
    """
    head = _FIRST_PATH.search(sym.svg)
    if head is None or 'fill="none"' not in head.group(0):
        raise ValueError(
            f"{sym.symbol_id()}: cannot be darkened -- its first <path> is not an "
            f"unfilled body. A symbol whose body is not the first path it draws "
            f"does not belong in NC_DARKENS; PIP PIC001 4.2.2.8's NC abbreviation "
            f"is what such a valve states its position with."
        )
    filled = head.group(0).replace('fill="none"', f'fill="{_BODY_INK}"', 1)
    svg = sym.svg[:head.start()] + filled + sym.svg[head.end():]
    return Symbol(
        svg=re.sub(r'id="([^"]*)"', r'id="\1_nc"', svg, count=1),
        width=sym.width, height=sym.height, ports=dict(sym.ports),
        port_faces={name: dict(faces) for name, faces in sym.port_faces.items()},
        faceless_ports=sym.faceless_ports, port_series=sym.port_series,
        label_pos=sym.label_pos, id_suffix=sym.id_suffix + "_nc",
        stretchable=sym.stretchable,
    )


class SymbolRegistry:
    def __init__(self):
        self._symbols: dict[tuple[str, str], Symbol] = {}
        # Darkened bodies, built once each on demand. Port resolution asks for a
        # unit's symbol on every call, and the registry hands out one shared
        # instance per fixed symbol; a derived one has to be shared the same way
        # or every nozzle lookup rebuilds the artwork.
        self._darkened: dict[tuple[str, str], Symbol] = {}
        # Second drawings, for the devices the stencil set draws in two
        # positions. Not a variant: one (kind, variant) with two states, and
        # which one is drawn comes off the unit's ``normal_position``.
        self._closed: dict[tuple[str, str], Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol, variant: str = "default") -> None:
        self._symbols[(kind, variant)] = template
        self._darkened.pop((kind, variant), None)
        self._closed.pop((kind, variant), None)

    def register_closed(self, kind: str, template: Symbol, variant: str = "default") -> None:
        """The drawing for ``(kind, variant)`` declared normally closed.

        For a device whose closed state is a *shape of its own* rather than a
        fill applied to the open one: a spectacle blind is two discs and the
        solid one is whichever is in the line. Registered against the same
        ``(kind, variant)`` as :meth:`register`, so the closed state never
        becomes a second variant name for one device, and always after it,
        since re-registering the open drawing drops the pairing.
        """
        if (kind, variant) not in self._symbols:
            raise ValueError(
                f"{kind}/{variant} has no open drawing to be the closed state of; "
                f"register() it first"
            )
        self._closed[(kind, variant)] = template

    def closed_symbol(self, kind: str, variant: str = "default") -> Symbol | None:
        """``(kind, variant)``'s normally closed drawing, or None if it has none."""
        return self._closed.get((kind, variant))

    def closed_variants(self, kind: str) -> list[str]:
        """Every variant of a kind that is drawn in two positions, A-Z."""
        return sorted(variant for (k, variant) in self._closed if k == kind)

    def for_unit(self, unit) -> Symbol:
        """The symbol to draw ``unit`` with, built to its size where it has one.

        :meth:`get` answers for a ``(kind, variant)``, which is everything a
        fixed drawing depends on. A conveyor's artwork depends on the unit as
        well, since it is made to its belt run, and a valve's or a blind's on
        whether it is declared normally closed -- which darkens the one and
        swaps the other for the second shape its stencil set draws; the lookup
        still runs either way, so a variant name nobody registered is still
        rejected.
        """
        variant = getattr(unit, "variant", "default")
        sym = self.get(unit.kind, variant)
        build = _BUILT_TO_SIZE.get(unit.kind)
        if build is not None:
            return build(unit)
        mark = closed_marking(unit, self)
        if mark == "stencil":
            return self._closed[(unit.kind, variant)]
        if mark == "fill":
            key = (unit.kind, variant)
            if key not in self._darkened:
                self._darkened[key] = darkened(sym)
            return self._darkened[key]
        return sym

    def variants(self, kind: str) -> list[str]:
        """Every variant registered for a kind, ``default`` first then A-Z."""
        names = [variant for (k, variant) in self._symbols if k == kind]
        return sorted(names, key=lambda name: (name != "default", name))

    def get(self, kind: str, variant: str = "default") -> Symbol:
        if (kind, variant) in self._symbols:
            return self._symbols[(kind, variant)]
        known = self.variants(kind)
        if not known:
            # A kind with no artwork at all -- a Unit subclass from outside this
            # package -- draws a generic box, and there is no catalogue to hold
            # its variant against. Only a kind that *has* a catalogue can be
            # said to lack a name from it.
            return self._generic_symbol()
        # A name no symbol answers to is a typo, and drawing the kind's default
        # in its place is silent by construction: the sheet comes out looking
        # right, so nothing downstream is ever in a position to say the symbol
        # the author asked for does not exist.
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
        # ====================================================================
        # Feed / Product — rendered dynamically in svg.py, these are fallbacks
        # ====================================================================
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

        # The equipment symbols below are fallbacks: the vendored registry at
        # the bottom of this method registers over every one of them, so none is
        # what a sheet draws today. They are kept as the shape of last resort if
        # a stencil is ever dropped, and their geometry notes describe them, not
        # the artwork in use. The Mixer, the Splitter and the pipe tee are the
        # exceptions; there is no stencil for any of the three, so those are
        # drawn as written.

        # ====================================================================
        # Centrifugal Pump — circle with discharge nozzle at top, suction on
        # left, baseplate line
        # ====================================================================
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

        # ====================================================================
        # Compressor — circle with triangle indicator
        # ====================================================================
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

        # ====================================================================
        # Separator — vertical vessel with elliptical heads
        # ====================================================================
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

        # ====================================================================
        # Reactor — vertical vessel with internal coil indicator
        # ====================================================================
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

        # ====================================================================
        # Shell & Tube Heat Exchanger
        # Horizontal cylinder with two tube-side nozzles on ends
        # and two shell-side nozzles on top/bottom
        # ====================================================================
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
                'cold_in': (0.0, 30.0),
                'cold_out': (100.0, 30.0),
                'hot_in': (50.0, 10.0),
                'hot_out': (50.0, 50.0),
            }
        ))
        

        # ====================================================================
        # Mixer — Standard triangle pointing right
        # All inputs on the left flat face, output at right vertex
        # ====================================================================
        self.register("mixer", Symbol(
            svg='<g id="sym_mixer"><polygon points="0,0 50,25 0,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'outlet': (50.0, 25.0)},
            port_series=(PortSeries("in_", "W"),),
        ))

        # ====================================================================
        # Valve — a bowtie, two opposing triangles, with a stem bar
        # ====================================================================
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

        # ====================================================================
        # Vessel — vertical drum with dished heads
        # ====================================================================
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

        # ====================================================================
        # Heater — circle with an internal zigzag (electric heater symbol)
        # ====================================================================
        self.register("heater", Symbol(
            svg=(
                '<g id="sym_heater">'
                '<circle cx="30" cy="30" r="25" fill="none" stroke="black" stroke-width="2"/>'
                '<path d="M15,30 L20,20 L25,40 L30,20 L35,40 L40,20 L45,30" fill="none" stroke="black" stroke-width="1.5"/>'
                '</g>'
            ),
            width=60.0, height=60.0,
            ports={'outlet': (55.0, 30.0), 'duty': (30.0, 55.0), 'inlet': (5.0, 30.0)}
        ))

        # ====================================================================
        # Cooler — circle with internal zigzag plus cooling arrow
        # ====================================================================
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
            ports={'outlet': (55.0, 30.0), 'inlet': (5.0, 30.0), 'duty': (30.0, 5.0)}
        ))

        # ====================================================================
        # Distillation Column — tall vertical vessel with internal trays
        # ====================================================================
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
        

        # ====================================================================
        # Belt conveyor — registered at its default length. A conveyor of any
        # other length gets its own symbol from for_unit(); see conveyor_symbol.
        # ====================================================================
        self.register("conveyor", conveyor_symbol())

        # ====================================================================
        # Pipe tee — the junction where a line branches.
        #
        # Drawn as the pipe and nothing else. On the reference sheet P&ID-301
        # the CV-303 station carries a bypass over the top and two drain legs
        # below, and all four junctions are three lines meeting: the main run is
        # one unbroken stroke from x=471.34 to x=703.78 at y=233.29, the bypass
        # leaves it at (569.14, 233.29) and returns at (676.85, 233.29), the two
        # drains drop from (598.90, 233.29) and (648.51, 233.29), and there is
        # no dot, circle or fitting symbol at any of them -- the sheet contains
        # no filled shape smaller than 6 pt anywhere. Every one of those strokes
        # is 0.75 pt, the same weight as the run, so the branch is pipe and is
        # drawn as pipe.
        #
        # So: the run straight across at mid-height, and the branch stub from
        # the centre down to the south face. The two run nozzles share one
        # centreline, which is what keeps the main run from kinking through the
        # junction. The box is small because a tee has no size -- it is a point
        # on the line -- and only large enough that the branch stub reads as a
        # spur at the 2-unit stroke the process lines are drawn in.
        #
        # An original primitive rather than a stencil: the draw.io P&ID set
        # draws no bare junction, and two line segments are not artwork anyone
        # holds a copyright in. See NOTICE section 1.
        # ====================================================================
        self.register("tee", Symbol(
            svg='<g id="sym_tee">'
                '<path d="M 0 6 L 12 6 M 6 6 L 6 12" fill="none" stroke="black" '
                'stroke-width="2"/>'
                '</g>',
            width=12.0, height=12.0,
            ports={"inlet": (0.0, 6.0), "outlet": (12.0, 6.0), "branch": (6.0, 12.0)},
            # A tee is labelled nowhere, so it has no side to keep clear for a
            # tag. Saying "center" is what stops the layout engine reserving one
            # and the router standing its lines off to clear a label that is
            # never drawn.
            label_pos="center",
        ))

        # ====================================================================
        # Splitter — Standard triangle with point on left, flat on right
        # All outputs on the right flat face, input at left vertex
        # ====================================================================
        self.register("splitter", Symbol(
            svg='<g id="sym_splitter"><polygon points="0,25 50,0 50,50" fill="none" stroke="black" stroke-width="2"/></g>',
            width=50.0, height=50.0,
            ports={'inlet': (0.0, 25.0)},
            port_series=(PortSeries("out_", "E"),),
        ))

        # ====================================================================
        # ISA-5.1 instrument bubbles. The tag text is drawn dynamically from the
        # unit name by the renderer, so the symbol is just the balloon + its
        # location bar. Ports: pv (process connection, bottom), in/out (signals).
        # Variants: default (bare field balloon), panel (single bar), aux (double bar),
        # shared (balloon-in-square = DCS/shared display), computer (hexagon),
        # sis / logic (diamond-in-square = safety instrumented system),
        # interlock (plain diamond = interlock logic function).
        # ====================================================================
        # A balloon is a circle: a signal can meet it anywhere, so every
        # connection offers all four faces and none of them owns one. The
        # coordinates are one unit clear of the r=21 circle, matching the
        # nozzle stub used everywhere else.
        _inst_faces = {"N": (22.0, 0.0), "S": (22.0, 44.0),
                       "W": (0.0, 22.0), "E": (44.0, 22.0)}
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        # Every connection offers every face, so none of them owns one: the
        # menus overlap on purpose, which is what faceless_ports declares.
        _inst_menu = {name: dict(_inst_faces) for name in _inst_ports}
        _inst_faceless = frozenset(_inst_ports)
        # None of them stretches. ISA-5.1 balloons are *circles*, and the square,
        # the hexagon and the interlock box are read against that circle — an
        # oval bubble is not a bubble drawn wide, it is a different symbol, and
        # a squashed hexagon stops being the one that means "computer function".
        # Sized off their own proportions they keep them and are centred in the
        # box, which is what makes a balloon a balloon at any width the author
        # asks for.
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
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # The hexagon's flat bottom is at y=41, not y=43 like the circular
            # variants, so pv needs its own coordinate to keep the same 1-unit
            # nozzle stub instead of floating 3 units clear of the outline.
            width=44.0, height=44.0, label_pos="center", stretchable=False,
            faceless_ports=_inst_faceless,
            ports={**_inst_ports, "pv": (22.0, 42.0)},
            # the hexagon is flat-topped at y=3 and flat-bottomed at y=41, so N and S
            # need their own stubs; the side vertices sit where the circles do.
            port_faces={n: {**_inst_faces, "N": (22.0, 2.0), "S": (22.0, 42.0)}
                        for n in _inst_ports}), "computer")
        # The two trip / logic squares, hung under the instrument they act on.
        # ANSI/ISA-5.1-2009 draws these as two *different* symbols, and the
        # package now carries both rather than conflating them:
        #
        #   Table 5.1.2 items 3-5    a plain diamond              -> "interlock"
        #   Table 5.1.1 column B     a diamond inside a square    -> "sis"/"logic"
        #
        # The plain diamond is the generic interlock logic function. The
        # diamond-in-square is the safety-instrumented-system / alternate-choice
        # instrument symbol, and it is what an issued sheet draws for a trip:
        # every occurrence on the reference P&ID-301 is diamond-in-square. What
        # neither of them is, is a bare square — that is the shared-display
        # symbol of the "shared" variant with its balloon left off, which is
        # what this variant used to be drawn as.
        #
        # ``logic`` is retained as a second name for the diamond-in-square. It
        # is the name the package shipped, the one every drawing already
        # authored uses, and the one `Instrument` keys its repeat rule on; it is
        # a package spelling of ``sis`` and is documented as one rather than as
        # a claim about Table 5.1.2.
        #
        # Both are drawn in a 40 box, not the 28 the bare square used. An
        # inscribed diamond has half its square's area, and all of that loss is
        # taken out of the corners the number's corners occupy, so a 28 square
        # that held a two-figure number in full holds it only by crossing the
        # diamond's lower edges: the square has to grow by root two, 28 * 1.414
        # = 39.6, for the number to sit inside the diamond with the clearance it
        # had inside the square. 40 also lands just inside the 44 balloon, which
        # is the relationship a real sheet draws — on P&ID-301 the trip square
        # and the balloons are both 17.0 pt, cut to one module.
        #
        # The three ports are unchanged and need no adjusting: the midpoint of
        # each side of the box is where the diamond's vertices are, so every one
        # of them lands on the diamond, and on the square where there is one.
        _logic_ports = {'pv': (20.0, 39.0), 'sig_in': (1.0, 20.0), 'sig_out': (39.0, 20.0)}
        # One Symbol registered under two names, so the two spellings cannot
        # drift apart. The ``<defs>`` id still follows the spelling, since that
        # is what the renderer keys a definition by; a sheet using both would
        # carry the same drawing twice, which is harmless and vanishingly rare.
        _sis = Symbol(
            svg='<g id="sym_instrument_sis">'
                '<rect x="1" y="1" width="38" height="38" fill="white" stroke="black" stroke-width="2"/>'
                '<polygon points="20,1 39,20 20,39 1,20" fill="none" stroke="black" stroke-width="2"/>'
                '</g>',
            # A diamond on the square's diagonals is as much a shape that carries
            # meaning as the balloon's circle: stretched to a box of another
            # proportion its vertices leave the sides' midpoints, which is where
            # all three ports sit.
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports)
        self.register("instrument", _sis, "sis")
        self.register("instrument", _sis, "logic")
        # The plain diamond fills its own outline: nothing is drawn behind it to
        # show through, and a white body keeps a line it is dropped on from
        # striking through the interlock number.
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_interlock">'
                '<polygon points="20,1 39,20 20,39 1,20" fill="white" stroke="black" stroke-width="2"/>'
                '</g>',
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports),
            "interlock")

        # Vendored draw.io symbols (Apache-2.0) — registered last so they
        # override the hand-drawn defaults for shared kinds and add variants.
        from pandid.render._vendored_symbols import register_vendored
        register_vendored(self)


default_registry = SymbolRegistry()
