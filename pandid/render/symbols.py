"""SVG symbols for the unit kinds and the registry that holds them.

The symbols in ``_vendored_symbols.py`` cover valves, pumps,
compressors, blowers, coolers, heaters, heat exchangers, cooling
towers, vessels, columns, reactors, separators, tanks, dryers, filters,
furnaces, thickeners, turbines, reducers, in-line fittings, ejectors,
vents and funnels, and replace hand-drawn symbols of the same kind.
They and the belt conveyor are adapted from draw.io stencils
(Apache-2.0); see ``NOTICE``.
"""

import hashlib
import math
import re
import warnings
from dataclasses import dataclass, field, replace
from functools import lru_cache, partial
from typing import Callable

from pandid._checks import suggest
from pandid.portgeom import outward_dir
from pandid.render.iso_parts import _DASH_LONG, _SQ2
from pandid.render.weights import M, LineWeight
from pandid.streams import PROCESS_KINDS

# Placements closer than this are the same point.
_COINCIDENT = 0.5

#: Side of a process-line arrowhead, in drawing units.
ARROWHEAD = 12.0

#: Gap between two arrowheads side by side (ISO 128-20 4.4).
MIN_HEAD_CLEARANCE = 2 * LineWeight.MAIN_FLOW.width

#: Smallest pitch between two nozzles that both carry an arrowhead.
MIN_NOZZLE_PITCH = ARROWHEAD + MIN_HEAD_CLEARANCE

# Outline weight (ISO 10628-1 5.3.1 b), unfilled and filled white, and
# detail weight (5.3.1 c).
_INK = 'fill="none" stroke="#111" stroke-width="2"'
_OUTLINE = 'fill="white" stroke="#111" stroke-width="2"'
_DETAIL = 'fill="none" stroke="#111" stroke-width="1"'


def wears_arrowhead(stream, registry) -> bool:
    """Return whether a stream ends in an arrowhead.

    The result applies only on a sheet that draws arrowheads.

    Parameters
    ----------
    stream : Stream
        Stream to check.
    registry : SymbolRegistry
        Registry resolving the destination unit's symbol.

    Returns
    -------
    bool
        False for a signal, a shaft or a stream ending at a bare run.

    Raises
    ------
    ValueError
        If the destination unit's symbol cannot be resolved.
    """
    if stream.kind not in PROCESS_KINDS:
        return False
    return not registry.for_unit(stream.dest.owner).bare_run


#: Spread a family symmetrically about ``at``. The default.
CENTRED = "centre"

#: Start a family at ``at`` and grow it along the face.
FROM_START = "start"


def spread(index: int, count: int, along: float, pitch: float,
           extent: float, at: float | None = None,
           align: str = CENTRED,
           band: "tuple[float, float] | None" = None) -> float:
    """Return the position of member ``index`` of ``count`` on a face.

    Members sit ``pitch`` apart about ``at``, squeezed to fit ``extent``
    of the face and the band, then slid into the band.

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
        Position of a lone member; the band middle when omitted.
    align : str, default=CENTRED
        :data:`CENTRED` or :data:`FROM_START`.
    band : tuple[float, float], optional
        ``(lo, hi)`` part of the face to use; the whole face if omitted.

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


def pinned(pin: float, along: float,
           band: "tuple[float, float] | None" = None) -> float:
    """Return the point a fraction of the way along a face.

    The fraction runs from 0 at the face's top or left end to 1 at its
    bottom or right end, and the point is kept inside the band.

    Parameters
    ----------
    pin : float
        Fraction of the face.
    along : float
        Face length.
    band : tuple[float, float], optional
        ``(lo, hi)`` part of the face to keep to; the whole face if
        omitted.

    Returns
    -------
    float
        Coordinate along the face.
    """
    lo, hi = (0.0, along) if band is None else band
    return min(max(pin * along, lo), hi)


def bandless_face(who: str, face: str, at: float, members: "list[str]",
                  sym: "Symbol", drawn: "dict[str, str] | None" = None) -> ValueError:
    """Return the error for several nozzles on a one-point face.

    The cure names only the walled faces every member's role may use.

    Parameters
    ----------
    who : str
        Unit name.
    face : str
        Face name.
    at : float
        The face's single point.
    members : list[str]
        Ports placed on the face, ``in_*`` or ``out_*``.
    sym : Symbol
        Symbol the ports are drawn on.
    drawn : dict[str, str], optional
        The face each of the symbol's own faces is drawn on; the faces
        are named as their own when omitted.

    Returns
    -------
    ValueError
        The error to raise.
    """
    drawn = drawn or {f: f for f in ("N", "E", "S", "W")}
    named = " and ".join(filter(None, [", ".join(members[:-1]), *members[-1:]]))
    verb = "are both" if len(members) == 2 else "are all"
    # Each member's faces whose band has length.
    roles = ["inlet" if m.startswith("in_") else "outlet" for m in members]
    menus = [[f for f in {**sym.port_faces.get(role, {}), **sym.family_faces.get(role, {})}
              if (band := sym.bands.get(f)) is None or band[0] < band[1]]
             for role in roles]
    offered = [drawn[f] for f in menus[0] if all(f in menu for menu in menus)]
    cure = (
        "Put them on "
        + " or ".join(filter(None, [", ".join(offered[:-1]), *offered[-1:]]))
        + ", or leave a single connection here"
        if offered else
        "No face with a wall takes all of them, so leave a single "
        "connection here"
    )
    return ValueError(
        f"{who}: {named} {verb} on the {drawn[face]} face, whose artwork meets the box "
        f"at the single point {at:g} along it -- a dished head, a cone apex or a "
        f"domed roof. One nozzle sits on that point; a second beside it would be "
        f"drawn in mid-air off the ink. {cure}"
    )


@dataclass(frozen=True)
class PortSeries:
    """A family of like ports spread along one face of a symbol.

    Attributes
    ----------
    prefix : str
        Member names are ``prefix`` plus a 1-based index.
    face : str
        Face the family is on: ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    pitch : float
        Preferred spacing between members.
    extent : float
        Largest fraction of the face the run may span.
    at : float or None
        Position of a lone member; the face middle when ``None``.
    singular : str or None
        Name of a lone member, such as a column's ``feed``.
    align : str
        :data:`CENTRED` or :data:`FROM_START`.
    inset : float
        Distance of the members in from the face's edge.
    members : tuple[str, ...]
        Ports this series places in place of its prefix: one face's
        share of a family.
    also : tuple[PortSeries, ...]
        The family's placements on further faces, which ``nozzle()``
        and layout may move a member to.
    """

    prefix: str
    face: str
    pitch: float = 20.0
    extent: float = 0.7
    at: float | None = None
    singular: str | None = None
    align: str = CENTRED
    inset: float = 0.0
    members: tuple[str, ...] = ()
    also: tuple["PortSeries", ...] = ()

    def matches(self, port_name: str) -> bool:
        """Return whether ``port_name`` is a member of this series.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        bool
            True for a named member, else for the singular name or
            ``prefix`` plus digits.
        """
        if self.members:
            return port_name in self.members
        return port_name == self.singular or (
            port_name.startswith(self.prefix)
            and port_name[len(self.prefix):].isdigit())

    def on(self, face: str) -> "PortSeries | None":
        """Return this family's placement on a face, or None.

        Parameters
        ----------
        face : str
            Face.

        Returns
        -------
        PortSeries or None
            This series, or the one in :attr:`also` on ``face``.
        """
        return next((s for s in (self, *self.also) if s.face == face), None)

    def placement(self, index: int, count: int, width: float, height: float,
                  pin: float | None = None,
                  band: "tuple[float, float] | None" = None) -> tuple[float, float]:
        """Return the point of member ``index`` of ``count``.

        Parameters
        ----------
        index : int
            Member index, from 0.
        count : int
            Family size.
        width, height : float
            Symbol box.
        pin : float, optional
            Fraction of the face that places this member instead.
        band : tuple[float, float], optional
            :attr:`Symbol.bands` entry for this face.

        Returns
        -------
        tuple[float, float]
            Point in symbol coordinates.
        """
        along = height if self.face in ("W", "E") else width
        if pin is not None:
            t = pinned(pin, along, band)
        else:
            t = spread(index, count, along, self.pitch, self.extent, self.at,
                       self.align, band)
        return _face_point(self.face, t, self.inset, width, height)

    def reach(self, width: float, height: float,
              band: "tuple[float, float] | None" = None
              ) -> tuple[float, float, float]:
        """Return where members can sit on the face, at any count.

        Parameters
        ----------
        width, height : float
            Symbol box.
        band : tuple[float, float], optional
            :attr:`Symbol.bands` entry for this face.

        Returns
        -------
        tuple[float, float, float]
            The face's fixed coordinate, then ``lo`` and ``hi``.
        """
        along = height if self.face in ("W", "E") else width
        # Two members at full extent give the ends of the range.
        ends = [spread(i, 2, along, self.extent * along, self.extent, self.at,
                       self.align, band)
                for i in (0, 1)]
        fixed = {"W": self.inset, "E": width - self.inset,
                 "N": self.inset, "S": height - self.inset}[self.face]
        return fixed, min(ends), max(ends)


# Supplementary symbols: ISO 10628-2 group 26-29 parts composed onto a
# body (clause 5).

#: ISO 10628-2 Table 1 subject groups whose items may be overlaid.
PART_GROUPS = {
    26: "apparatus elements",
    27: "internals",
    28: "agitators, stirrers",
    29: "internal characteristics and built-in components",
}

#: Apparatus items that may be overlaid, with the item that draws each.
COMPOSED_APPARATUS = {
    "20.6": "1.27 X8006, the motor above a stirred vessel",
}

# Registration number forms of ISO 10628-2 clause 5.
_REG_NO = re.compile(r"\A(?:\d{3,4}|C\d{3,4}|X[28]\d{3})\Z")


@dataclass(frozen=True)
class IsoPart:
    """Identity of one ISO 10628-2 group 26-29 supplementary symbol.

    Attributes
    ----------
    group : int
        Table 1 subject group, 26 to 29; 20 only for item 20.6.
    item : str
        Item number, such as ``"27.3"``.
    reg : str
        Registration number, such as ``"C2028"``.
    name : str
        The item's descriptor in the standard.

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
        """Validate the part's identity.

        Raises
        ------
        ValueError
            If the group, item, registration number or name is invalid.
        """
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

    Placement is in fractions of the body's box. Values outside 0 to 1
    put the part outside the body, and :func:`compose` grows the box.

    Attributes
    ----------
    group : int
        ISO subject group.
    name : str
        Part name in the registry.
    x, y : float
        Left and top edge, as fractions of the body's width and height.
    w, h : float
        Width and height, as positive fractions of the body's box.
    mirror : bool
        Reflect the part left to right.

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
        """Refuse a part with no extent.

        Raises
        ------
        ValueError
            If ``w`` or ``h`` is not positive.
        """
        if self.w <= 0 or self.h <= 0:
            raise ValueError(
                f"overlay {self.group}/{self.name} is placed {self.w:g} x {self.h:g} of "
                f"the body's box; a part with no extent draws nothing, and a negative "
                f"one draws the part inside out"
            )


@dataclass
class Symbol:
    """SVG artwork for a unit, with named port anchors.

    Attributes
    ----------
    svg : str
        Artwork in local coordinates, (0, 0) at the top left.
    width, height : float
        Artwork box.
    ports : dict[str, tuple[float, float]]
        Home anchor of each fixed port, keyed by the unit's port name.
    port_faces : dict[str, dict[str, tuple[float, float]]]
        Placements of each port by face; each must lie nearest its face.
    faceless_ports : frozenset[str]
        Ports in ``ports`` with no face, which may share placements.
    port_series : tuple[PortSeries, ...]
        Port families, each on N, S, E or W and apart from ``ports``.
    bands : dict[str, tuple[float, float]]
        Stretch ``(lo, hi)`` a family may use, from each face's start.
    family_faces : dict[str, dict[str, tuple[float, float]]]
        Further placements by face of the ``inlet`` and ``outlet``
        families, left out of a lone port's menu.
    rim : tuple[tuple[float, float], ...]
        Outline of the artwork as a convex polygon, which lines sharing
        a face are drawn to; the box when empty.
    label_pos : str or None
        Fixed tag side, such as ``"center"``.
    id_suffix : str
        Suffix telling apart definitions of one kind and variant.
    stretchable : bool
        Whether the artwork may be scaled unevenly to fill a box.
    bare_run : bool
        The artwork is only pipe; a stream ending here has no arrowhead.
    gravity_fixed : bool
        The function depends on gravity; turning it is reported.
    directional : bool
        The artwork states a direction and is held still under
        reflections. Its ports must stay on ink under any flip, and it
        must carry no lettering.
    drawio_shape : str
        draw.io stencil key; empty for hand-drawn symbols.
    drawio_flip_h : bool
        Flip the draw.io stencil left to right.
    drawio_fill : str
        Fill for the draw.io stencil.
    drawio_body_shape : str
        draw.io stencil for a composition's body.
    overlays : tuple[Overlay, ...]
        Parts drawn over the body.
    iso_reg : str
        ISO registration number of the drawing, or empty.
    trim : bool
        Draw the outline at the trim weight (ISO 10628-1 5.3.1 c).

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
    family_faces: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    rim: tuple[tuple[float, float], ...] = ()
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
        """Validate the ports and build the full face menus.

        Raises
        ------
        ValueError
            If ports, menus, series or bands are inconsistent.
        """
        declared = {name: dict(faces) for name, faces in self.port_faces.items()}
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
            on = [series.face, *(also.face for also in series.also)]
            if any(face not in ("N", "S", "E", "W") for face in on) or len(set(on)) < len(on):
                raise ValueError(
                    f"{self.symbol_id()}: the {series.prefix!r} series names faces "
                    f"{on}; expected each of N, S, E, W at most once"
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
        for name, faces in self.family_faces.items():
            for face, coord in faces.items():
                lands = outward_dir(coord[0], coord[1], self.width, self.height)
                if lands != face:
                    raise ValueError(
                        f"{self.symbol_id()}: family_faces[{name!r}][{face!r}] at "
                        f"{coord} is nearest the {lands} edge of the "
                        f"{self.width}x{self.height} box, so that is the face it "
                        f"would come out of"
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
        """Return the series placing ``port_name``, if any.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        PortSeries or None
            The series, or ``None`` for a fixed port.
        """
        for series in self.port_series:
            if series.matches(port_name):
                return series
        return None

    def symbol_id(self) -> str:
        """Return the SVG id, for messages.

        Returns
        -------
        str
            The artwork's id, or ``"<symbol>"``.
        """
        match = re.search(r'\bid="([^"]+)"', self.svg)
        return match.group(1) if match else "<symbol>"

    def coincident_ports(self) -> list[tuple[str, str, tuple[float, float]]]:
        """Return pairs of different ports that share a placement.

        Faceless ports may share with each other. A series is checked as
        the stretch of face it may use and reported as ``prefix*``.

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


# Belt conveyor, adapted from the draw.io P&ID stencil "Drier (Roller
# Conveyor Belt)" (Apache-2.0; see NOTICE): the housing is dropped and
# the run and roller size are parameters.

#: Default roller radius.
CONVEYOR_ROLLER = 10.0
#: Default roller diameter, and the drawn depth.
CONVEYOR_DIAMETER = 2 * CONVEYOR_ROLLER
#: Default belt run.
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
        Minimum run.
    """
    return 2 * diameter


def conveyor_too_short(length: float, owner: str = "",
                       diameter: float = CONVEYOR_DIAMETER) -> ValueError:
    """Return the error for a belt run too short for its rollers.

    Parameters
    ----------
    length : float
        Requested run.
    owner : str, default=""
        Unit name for the message, or empty.
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
        Unit name for the message, or empty.

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

    ``feed`` is the tail roller, also offered on top; ``discharge`` is
    the head roller, also offered underneath; ``drive`` is on top of the
    head roller.

    Parameters
    ----------
    length : float, default=CONVEYOR_LENGTH
        Run from tail to head, at least two roller diameters.
    diameter : float, default=CONVEYOR_DIAMETER
        Roller diameter and drawn depth; positive.

    Returns
    -------
    Symbol
        Symbol ``length`` wide and ``diameter`` deep.
    """
    r, height = diameter / 2, float(diameter)
    tail, head = r, length - r
    # The default diameter is left out of the id.
    suffix = f"_L{length:g}" + (f"_D{diameter:g}"
                                if diameter != CONVEYOR_DIAMETER else "")
    roller = '<ellipse cx="{:g}" cy="{:g}" rx="{:g}" ry="{:g}" ' + _INK + "/>"
    svg = (
        f'<g id="sym_conveyor{suffix}">'
        + roller.format(tail, r, r, r)
        + roller.format(head, r, r, r)
        + f'<path d="M {tail:g} 0 L {head:g} 0 M {tail:g} {height:g} '
          f'L {head:g} {height:g}" {_INK}/>'
        + '</g>'
    )
    return Symbol(
        svg=svg, width=float(length), height=height,
        ports={"feed": (0.0, r), "discharge": (float(length), r), "drive": (head, 0.0)},
        port_faces={"feed": {"N": (tail, 0.0)},
                    "discharge": {"S": (head, height)}},
        id_suffix=suffix,
        stretchable=False,
    )


# Screw conveyor, ISO 10628-2 item 18.5 X8063, built to its length.

#: Grid module of item 18.5, in drawing units.
SCREW_MODULE = 5.0

#: Default casing depth: 6 modules.
SCREW_HEIGHT = 6 * SCREW_MODULE

#: Width of one turn along the axis, and its reach either side.
SCREW_TURN, SCREW_REACH = 4 * SCREW_MODULE, 2 * SCREW_MODULE

#: Fraction of the bore the flight sweeps.
SCREW_SWEEP = 2 * SCREW_REACH / SCREW_HEIGHT

#: Pitch between turn starts, and clear casing at each end.
SCREW_PITCH, SCREW_MARGIN = 7 * SCREW_MODULE, 2 * SCREW_MODULE

#: Shortest screw: clear casing, one turn, clear casing.
SCREW_MIN_LENGTH = 2 * SCREW_MARGIN + SCREW_TURN


def screw_too_short(length: float, owner: str = "") -> ValueError:
    """Return the error for a screw casing too short for one turn.

    Parameters
    ----------
    length : float
        Requested length.
    owner : str, default=""
        Unit name for the message, or empty.

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
        Unit name for the message, or empty.

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
    """Return a closed screw conveyor symbol (ISO 10628-2 item 18.5).

    Turns repeat at :data:`SCREW_PITCH` and the flight follows the bore.
    ``drive`` is on the casing's crown above the discharge spout.

    Parameters
    ----------
    length : float, default=CONVEYOR_LENGTH
        Casing length, at least :data:`SCREW_MIN_LENGTH`.
    diameter : float, default=SCREW_HEIGHT
        Casing bore and drawn depth; positive.

    Returns
    -------
    Symbol
        Symbol ``length`` wide and ``diameter`` deep.
    """
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
    # The default bore is left out of the id.
    suffix = f"_L{length:g}" + (f"_D{diameter:g}"
                                if diameter != SCREW_HEIGHT else "")
    svg = (
        f'<g id="sym_conveyor_screw{suffix}">'
        f'<rect x="0" y="0" width="{length:g}" height="{height:g}" {_OUTLINE}/>'
        f'<path d="M 0 {axis:g} L {length:g} {axis:g} {turns}" {_INK}/>'
        f'</g>'
    )
    return Symbol(
        svg=svg, width=float(length), height=height,
        ports={"feed": (SCREW_MODULE, 0.0),
               "discharge": (length - SCREW_MODULE, height),
               "drive": (length - SCREW_MODULE, 0.0)},
        port_faces={"feed": {"W": (0.0, axis)},
                    "discharge": {"E": (float(length), axis)}},
        id_suffix=suffix,
        stretchable=False,
        iso_reg="X8063",
    )


# Bucket elevator, ISO 10628-2 items 18.7 X8065 and 18.8 X8066.

# Grid module of both elevator rows, in drawing units.
_LIFT_M = 10.0

# Pulley radius and belt half-width: 1 module.
_LIFT_R = _LIFT_M


def _lift_pulley(cx: float, cy: float) -> str:
    """Return a pulley circle of radius 1 M.

    Parameters
    ----------
    cx, cy : float
        Centre.

    Returns
    -------
    str
        SVG ``<circle>``.
    """
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{_LIFT_R:g}" {_INK}/>'


def _lift_chute(x: float, y: float, dx: float, dy: float) -> str:
    """Return a chute: a run then a quarter arc back to the belt.

    Parameters
    ----------
    x, y : float
        Start on the belt.
    dx : float
        Signed run length.
    dy : float
        Signed drop of the arc.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    r = abs(dx)
    return (f'<path d="M {x:g} {y:g} L {x + dx:g} {y:g} '
            f'A {r:g} {r:g} 0 0 0 {x:g} {y + dy:g}" {_INK}/>')


# Block flow diagram box, sized to its connections.

#: Spacing of a block's connections on one face.
BLOCK_PITCH = 2.5 * ARROWHEAD

#: Smallest block box.
BLOCK_MIN_WIDTH = 120.0
BLOCK_MIN_HEIGHT = 80.0

# Font size of tags, instrument letters and flag names.
_TAG_TYPE = 12.0

# Padding a tag needs inside a box.
_LABEL_PAD = 30.0


def label_span(text: str) -> float:
    """Return the width a tag needs to letter ``text`` inside a box.

    Parameters
    ----------
    text : str
        Tag text.

    Returns
    -------
    float
        Width in drawing units, padding included.
    """
    from pandid.render.furniture import text_width

    return text_width(text, _TAG_TYPE) + _LABEL_PAD


def block_span(count: int) -> float:
    """Return the face length ``count`` block connections need.

    Parameters
    ----------
    count : int
        Connections on the face.

    Returns
    -------
    float
        One :data:`BLOCK_PITCH` per connection.
    """
    return BLOCK_PITCH * count


def block_box_too_small(owner: str, face: str, count: int, axis: str,
                        given: float, needed: float,
                        turned: bool = False) -> ValueError:
    """Return the error for a block box too small for its connections.

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
        Box size along ``axis``.
    needed : float
        Size the block would choose.
    turned : bool, default=False
        Whether a quarter turn moved ``face`` onto ``axis``.

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


# Faces in drawing order.
_BLOCK_FACES = ("W", "E", "N", "S")


@lru_cache(maxsize=None)
def block_symbol(faces: tuple[tuple[str, str], ...], label: str = "") -> Symbol:
    """Return a block flow diagram box with a port per connection.

    Each face is at least :func:`block_span` long.

    Parameters
    ----------
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` in the unit's port order.
    label : str, default=""
        Tag lettered inside the box, which widens it to fit.

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
            # The box always fits the full pitch.
            t = spread(i, len(members), along, BLOCK_PITCH, 1.0)
            ports[port_name] = _face_point(face, t, 0.0, width, height)
    svg = (
        f'<g id="sym_block">'
        f'<rect x="0" y="0" width="{width:g}" height="{height:g}" fill="none" '
        f'stroke="black" stroke-width="2"/>'
        f'</g>'
    )
    return Symbol(
        svg=svg, width=width, height=height, ports=ports,
        # The name is lettered inside the box.
        label_pos="center",
        # Each box size is its own <defs> entry.
        id_suffix=f"_{width:g}x{height:g}",
    )


# Mixer and splitter triangles, their many-nozzle face grown to its count
# where the stock face would crowd it.

#: Depth and stock face length of a mixer or splitter.
JUNCTION_SIZE = 50.0

#: Spacing of the nozzles on a mixer's or splitter's many-nozzle face.
JUNCTION_PITCH = 20.0

#: Largest fraction of the stock face the nozzles may span.
JUNCTION_EXTENT = 0.7

#: Face beyond the end nozzles of a grown mixer or splitter.
JUNCTION_END = 15.0


@lru_cache(maxsize=None)
def junction_symbol(kind: str, count: int = 0, pitch: float = JUNCTION_PITCH) -> Symbol:
    """Return a mixer or splitter triangle.

    The stock triangle has a :data:`JUNCTION_SIZE` face, with its
    nozzles :data:`JUNCTION_PITCH` apart within :data:`JUNCTION_EXTENT`
    of it. A grown one holds ``count`` nozzles ``pitch`` apart, with
    :data:`JUNCTION_END` beyond each end.

    Parameters
    ----------
    kind : str
        ``"mixer"`` or ``"splitter"``.
    count : int, default=0
        Nozzles to grow the face for; 0 for the stock triangle.
    pitch : float, default=JUNCTION_PITCH
        Spacing of the nozzles on a grown face.

    Returns
    -------
    Symbol
        Triangle pointing east for a mixer, west for a splitter.
    """
    w = JUNCTION_SIZE
    h = (count - 1) * pitch + 2 * JUNCTION_END if count else JUNCTION_SIZE
    mixer = kind == "mixer"
    points = f"0,0 {w:g},{h / 2:g} 0,{h:g}" if mixer else f"0,{h / 2:g} {w:g},0 {w:g},{h:g}"
    return Symbol(
        svg=f'<g id="sym_{kind}"><polygon points="{points}" fill="none" stroke="black" '
            f'stroke-width="2"/></g>',
        width=w, height=h,
        ports={"outlet": (w, h / 2)} if mixer else {"inlet": (0.0, h / 2)},
        port_series=(PortSeries("in_" if mixer else "out_", "W" if mixer else "E",
                                pitch=pitch if count else JUNCTION_PITCH,
                                extent=1.0 if count else JUNCTION_EXTENT),),
        # Each face length is its own <defs> entry.
        id_suffix=f"_{h:g}" if count else "",
    )


def header_grows(unit) -> bool:
    """Return whether a mixer or splitter is drawn with a grown face.

    The face grows where the stock face would set its nozzles closer
    than :data:`MIN_NOZZLE_PITCH`, unless the sheet keeps it stock, or
    closer than the pitch the sheet fits it to its lines at; never
    where the unit has a stated ``width`` or ``height`` or its drawing
    is registered again.

    Parameters
    ----------
    unit : Unit
        Unit to test.

    Returns
    -------
    bool
        True if the face grows to its nozzle count.
    """
    if unit.kind not in ("mixer", "splitter") or getattr(unit, "variant", "default") != "default":
        return False
    count = len(unit.inlets if unit.kind == "mixer" else unit.outlets)
    if count < 2 or unit.width is not None or unit.height is not None:
        return False
    stock = min(JUNCTION_PITCH, JUNCTION_EXTENT * JUNCTION_SIZE / (count - 1))
    return ((stock < MIN_NOZZLE_PITCH and not unit._stock_face
             or stock < unit._fit_pitch)
            and default_registry.get(unit.kind) is junction_symbol(unit.kind))


def _junction(unit) -> Symbol:
    """Return a mixer's or splitter's drawing, grown if it grows.

    A grown face spaces its nozzles :data:`JUNCTION_PITCH` apart, or
    the pitch the sheet fits it to its lines at where that is more.

    Parameters
    ----------
    unit : Unit
        Mixer or splitter.

    Returns
    -------
    Symbol
        The grown triangle, else the registered drawing.
    """
    if not header_grows(unit):
        return default_registry.get(unit.kind)
    return junction_symbol(unit.kind, len(unit.inlets if unit.kind == "mixer" else unit.outlets),
                           max(JUNCTION_PITCH, unit._fit_pitch))


def _face_local(face: str, x: float, y: float, width: float, height: float
                ) -> tuple[float, float]:
    """Return ``(along, inset)`` of a symbol-space point on a face.

    Parameters
    ----------
    face : str
        Face name.
    x, y : float
        Point in symbol coordinates.
    width, height : float
        Symbol box.

    Returns
    -------
    tuple[float, float]
        Position along the face and distance in from its edge.
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
    """Return the point ``t`` along a face, ``inset`` from its edge.

    Parameters
    ----------
    face : str
        Face name.
    t : float
        Position along the face.
    inset : float
        Distance in from the face's edge.
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


# Vessel shells, built to the size they are drawn at: the heads, the
# detail on the shell and the nozzle offsets keep their own dimensions,
# and the straight shell takes up the rest of the box.

#: Depth of a pressure vessel's ellipsoidal head.
_HEAD = 7.5

#: Depth of a dished head.
_DISHED = 7.6923

#: Depth of a horizontal drum's head.
_DRUM_HEAD = 5.7692

#: Gap between a wall's band and the end of its straight shell.
_BAND_GAP = 10.0

#: Offset of the relief from the crown of a dished head.
_RELIEF_OFF_CROWN = 12.0

#: Least distance of a relief from the vent on the crown.
_RELIEF_MIN = MIN_NOZZLE_PITCH / 2


#: Side and drop of a dished vessel's own brackets, and the height of
#: their foot above the bottom tangent line.
_BRACKET, _BRACKET_FOOT = 10.0, 15.0

#: Thickness of a jacket or of insulation, and how far inside the
#: tangent lines it ends.
_CLAD, _CLAD_END = 6.0, 5.0

#: Pitch of the insulation hatching.
_HATCH = 5.0

#: Electric heater: element width, element height, lead length, and
#: the reach from the shell to the far side of the element.
_HEATER_W, _HEATER_H, _HEATER_LEAD, _HEATER_REACH = 6.0, 20.0, 10.0, 10.0

#: Swaged vessel: step in from the wide shell to the narrow one, the
#: top head's depth, the narrow shell's length, the cone's height and
#: the bottom head's depth.
_SWAGE_STEP, _SWAGE_TOP, _SWAGE_NECK, _SWAGE_CONE, _SWAGE_HEAD = 10.0, 15.0, 25.0, 10.0, 12.5

#: Swaged vessel: offset of the relief from the crown.
_SWAGE_RELIEF = 9.0

#: Horizontal drum: where along its length the top inlet, the relief,
#: the drain, the vent and the outlet sit, as fractions of it.
_DRUM_INLET_N, _DRUM_RELIEF, _DRUM_DRAIN = 20.0 / 91.5, 30.0 / 91.5, 25.0 / 91.5
_DRUM_VENT, _DRUM_OUTLET = 55.0 / 91.5, 68.0 / 91.5

#: Domed vessel: the manway's width, straight height and cap depth, its
#: east side's offset from the east tangent line, and the height of the
#: head nozzles above the axis.
_DOME_W, _DOME_NECK, _DOME_CAP, _DOME_OFF, _DOME_NOZZLE = 20.0, 10.0, 5.0, 15.0, 8.0

#: Each variant's drawn size when none is stated.
VESSEL_SIZES = {
    "default": (62.0, 100.0),
    "dished": (60.0, 95.4),
    "dome": (95.4, 55.0),
    "electrical_heating": (50.0, 95.4),
    "horizontal": (91.5, 30.0),
    "insulated": (52.0, 95.4),
    "jacketed": (52.0, 95.4),
    "swaged": (50.0, 97.5),
}

#: draw.io stencil each variant exports as.
_DRAWIO = {
    "default": "mxgraph.pid.vessels.pressurized_vessel",
    "dished": "mxgraph.pid.vessels.vessel_(dished_ends,_brackets)",
    "dome": "mxgraph.pid.vessels.vessel_(dome)",
    "electrical_heating": "mxgraph.pid.vessels.vessel_(dished_ends,_electrical_heating)",
    "horizontal": "mxgraph.pid.vessels.drum_or_condenser",
    "insulated": "mxgraph.pid.vessels.vessel_(dished_ends,_thermal_insulation)",
    "jacketed": "mxgraph.pid.vessels.vessel_(dished_ends,_heating-cooling_jacket)",
    "swaged": "mxgraph.pid.vessels.vessel_(different_diameters)",
}


def _n(value: float) -> str:
    """Return a coordinate as SVG text.

    Parameters
    ----------
    value : float
        Coordinate.

    Returns
    -------
    str
        The value to four decimals, without trailing zeros.
    """
    return f"{round(value, 4) + 0.0:g}"


def _band(start: float, end: float) -> tuple[float, float]:
    """Return the stretch of a straight wall a nozzle family may use.

    Parameters
    ----------
    start, end : float
        The straight wall's ends.

    Returns
    -------
    tuple[float, float]
        The wall held :data:`_BAND_GAP` off each end, or its middle
        third on a wall too short for that.
    """
    gap = min(_BAND_GAP, (end - start) / 3)
    return start + gap, end - gap


def _relief_off(rx: float, depth: float, off: float) -> float:
    """Return a relief's distance from a head's crown, kept where it is flat.

    Parameters
    ----------
    rx : float
        Head's half-width.
    depth : float
        Head's depth.
    off : float
        Distance wanted.

    Returns
    -------
    float
        ``off``, or less where the head there slopes more steeply than
        it runs, so the relief's line leaves the head upward.
    """
    return min(off, rx * rx / math.hypot(rx, depth))


def _on_head(rx: float, depth: float, off: float) -> float:
    """Return how far below the crown a point on a top head lies.

    Parameters
    ----------
    rx : float
        Head's half-width.
    depth : float
        Head's depth.
    off : float
        Distance from the crown along the head.

    Returns
    -------
    float
        Drop from the crown to the head's outline.
    """
    return depth * (1 - math.sqrt(max(0.0, 1 - (off / rx) ** 2)))


def _upright(x0: float, x1: float, height: float, depth: float) -> str:
    """Return an upright shell with an elliptical head at each end.

    Parameters
    ----------
    x0, x1 : float
        The shell's walls.
    height : float
        Crown to crown.
    depth : float
        Head depth.

    Returns
    -------
    str
        SVG path data.
    """
    rx, cx = (x1 - x0) / 2, (x0 + x1) / 2
    top, bottom = depth, height - depth
    arc = f"A {_n(rx)} {_n(depth)} 0 0 1"
    return (f"M {_n(x0)} {_n(top)} {arc} {_n(cx)} 0 {arc} {_n(x1)} {_n(top)} "
            f"L {_n(x1)} {_n(bottom)} {arc} {_n(cx)} {_n(height)} {arc} {_n(x0)} {_n(bottom)} Z")


def _tangents(x0: float, x1: float, height: float, depth: float) -> str:
    """Return the tangent lines where an upright shell meets its heads.

    Parameters
    ----------
    x0, x1 : float
        The shell's walls.
    height : float
        Crown to crown.
    depth : float
        Head depth.

    Returns
    -------
    str
        SVG path data.
    """
    return (f" M {_n(x0)} {_n(depth)} L {_n(x1)} {_n(depth)}"
            f" M {_n(x0)} {_n(height - depth)} L {_n(x1)} {_n(height - depth)}")


def _dished_ports(x0: float, x1: float, height: float) -> dict[str, tuple[float, float]]:
    """Return the vent, relief and drain of a dished shell.

    Parameters
    ----------
    x0, x1 : float
        The shell's walls.
    height : float
        Crown to crown.

    Returns
    -------
    dict[str, tuple[float, float]]
        Port anchors.
    """
    cx, rx = (x0 + x1) / 2, (x1 - x0) / 2
    off = _relief_off(rx, _DISHED, _RELIEF_OFF_CROWN)
    return {"vent": (cx, 0.0), "relief": (cx - off, _on_head(rx, _DISHED, off)),
            "drain": (cx, height)}


def _default(w: float, h: float) -> tuple:
    """Return the pressure vessel: a shell with ellipsoidal heads.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    art = f'<path d="{_upright(0.0, w, h, _HEAD)}" {_OUTLINE}/>'
    off = _relief_off(w / 2, _HEAD, w / 4)
    ports = {"inlet": (0.0, h / 2), "outlet": (w, h / 2), "vent": (w / 2, 0.0),
             "relief": (w / 2 - off, _on_head(w / 2, _HEAD, off)), "drain": (w / 2, h)}
    band = _band(_HEAD, h - _HEAD)
    return art, ports, {"W": band, "E": band}


def _dished(w: float, h: float) -> tuple:
    """Return the dished vessel on its own pair of brackets.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    x0, x1 = _BRACKET, w - _BRACKET
    top = h - _DISHED - _BRACKET_FOOT - _BRACKET
    foot = top + _BRACKET
    brackets = (f" M {_n(x1)} {_n(top)} L {_n(w)} {_n(foot)} L {_n(x1)} {_n(foot)} Z"
                f" M {_n(x0)} {_n(top)} L 0 {_n(foot)} L {_n(x0)} {_n(foot)} Z")
    art = (f'<path d="{_upright(x0, x1, h, _DISHED)}{_tangents(x0, x1, h, _DISHED)}'
           f'{brackets}" {_OUTLINE}/>')
    ports = {"inlet": (x0, h / 2), "outlet": (x1, h / 2), **_dished_ports(x0, x1, h)}
    band = _band(_DISHED, h - _DISHED)
    return art, ports, {"W": band, "E": band}


def _clad(w: float, h: float, insulated: bool) -> tuple:
    """Return a dished vessel in a jacket or in insulation.

    Parameters
    ----------
    w, h : float
        Box.
    insulated : bool
        Hatched insulation rather than a jacket.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    x0, x1 = _CLAD, w - _CLAD
    start, end = _DISHED + _CLAD_END, h - _DISHED - _CLAD_END
    shell = f'<path d="{_upright(x0, x1, h, _DISHED)}{_tangents(x0, x1, h, _DISHED)}" {_OUTLINE}/>'
    if insulated:
        lines = [f"M 0 {_n(start)} L 0 {_n(end)}", f"M {_n(w)} {_n(start)} L {_n(w)} {_n(end)}"]
        steps = int((end - start) / _HATCH - 0.05) + 1
        for y in (start + _HATCH * i for i in range(steps)):
            run = min(_CLAD, end - y)
            lines.append(f"M {_n(x0)} {_n(y)} L {_n(x0 - run)} {_n(y + run)}")
        for y in (start + _HATCH * i for i in range(steps)):
            run = min(_CLAD, end - y)
            lines.append(f"M {_n(w)} {_n(y)} L {_n(w - run)} {_n(y + run)}")
        art = shell + f'<path d="{" ".join(lines)}" {_INK}/>'
    else:
        art = shell + "".join(
            f'<rect x="{_n(x)}" y="{_n(start)}" width="{_n(_CLAD)}" '
            f'height="{_n(end - start)}" {_OUTLINE}/>' for x in (0.0, x1))
    ports = {"inlet": (0.0, h / 2), "outlet": (w, h / 2), **_dished_ports(x0, x1, h)}
    band = _band(start, end)
    return art, ports, {"W": band, "E": band}


def _electrical(w: float, h: float) -> tuple:
    """Return a dished vessel with an electric heater on its east side.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    x1 = w - _HEATER_REACH
    mid, left, lead = h / 2, w - _HEATER_W, w - _HEATER_W / 2
    shell = f'<path d="{_upright(0.0, x1, h, _DISHED)}{_tangents(0.0, x1, h, _DISHED)}" {_OUTLINE}/>'
    top, bottom = mid - _HEATER_H / 2, mid + _HEATER_H / 2
    element = (f'<rect x="{_n(left)}" y="{_n(top)}" width="{_n(_HEATER_W)}" '
               f'height="{_n(_HEATER_H)}" {_OUTLINE}/>')
    marks = [f"M {_n(lead)} {_n(top - _HEATER_LEAD)} L {_n(lead)} {_n(top)}",
             f"M {_n(lead)} {_n(bottom)} L {_n(lead)} {_n(bottom + _HEATER_LEAD)}"]
    marks += [f"M {_n(left)} {_n(y)} L {_n(w)} {_n(y)}"
              for y in (mid - _HEATER_H / 4, mid, mid + _HEATER_H / 4)]
    art = shell + element + f'<path d="{" ".join(marks)}" {_INK}/>'
    tangent = h - _DISHED
    ports = {"inlet": (0.0, mid), "outlet": (x1, tangent - _BAND_GAP),
             **_dished_ports(0.0, x1, h)}
    band = _band(_DISHED, tangent)
    return art, ports, {"W": band, "E": band}


def _swaged(w: float, h: float) -> tuple:
    """Return a vessel whose narrow upper shell swages out to a wide one.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    x0, x1, cx = _SWAGE_STEP, w - _SWAGE_STEP, w / 2
    r = (x1 - x0) / 2
    off = _relief_off(r, _SWAGE_TOP, _SWAGE_RELIEF)
    neck = _SWAGE_TOP + _SWAGE_NECK
    wide = neck + _SWAGE_CONE
    knuckle = h - _SWAGE_HEAD
    top = f"A {_n(r)} {_n(_SWAGE_TOP)} 0 0 1"
    art = (f'<path d="M {_n(x0)} {_n(_SWAGE_TOP)} {top} {_n(cx)} 0 '
           f'{top} {_n(x1)} {_n(_SWAGE_TOP)} L {_n(x1)} {_n(neck)} '
           f'L {_n(w)} {_n(wide)} L {_n(w)} {_n(knuckle)} '
           f'A {_n(cx)} {_n(_SWAGE_HEAD)} 0 0 1 {_n(cx)} {_n(h)} '
           f'A {_n(cx)} {_n(_SWAGE_HEAD)} 0 0 1 0 {_n(knuckle)} L 0 {_n(wide)} '
           f'L {_n(x0)} {_n(neck)} Z" {_OUTLINE}/>')
    mid = (wide + knuckle) / 2
    ports = {"inlet": (0.0, mid), "outlet": (w, mid), "vent": (cx, 0.0),
             "relief": (cx - off, _on_head(r, _SWAGE_TOP, off)),
             "drain": (cx, h)}
    band = _band(wide, knuckle)
    return art, ports, {"W": band, "E": band}


def _horizontal(w: float, h: float) -> tuple:
    """Return a horizontal drum.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports, bands and the inlet's face menu.
    """
    x0, x1, mid = _DRUM_HEAD, w - _DRUM_HEAD, h / 2
    arc = f"A {_n(_DRUM_HEAD)} {_n(mid)} 0 0 0"
    art = (f'<path d="M {_n(x0)} {_n(h)} L {_n(x1)} {_n(h)} {arc} {_n(w)} {_n(mid)} '
           f'{arc} {_n(x1)} 0 L {_n(x0)} 0 {arc} 0 {_n(mid)} {arc} {_n(x0)} {_n(h)} Z '
           f'M {_n(x0)} 0 L {_n(x0)} {_n(h)} M {_n(x1)} 0 L {_n(x1)} {_n(h)}" {_OUTLINE}/>')
    ports = {"inlet": (0.0, mid), "outlet": (_DRUM_OUTLET * w, h),
             "vent": (_DRUM_VENT * w, 0.0), "relief": (_DRUM_RELIEF * w, 0.0),
             "drain": (_DRUM_DRAIN * w, h)}
    band = _band(x0, x1)
    faces = {"inlet": {"W": (0.0, mid), "N": (_DRUM_INLET_N * w, 0.0), "E": (w, mid)}}
    return art, ports, {"N": band, "S": band, "W": (mid, mid), "E": (mid, mid)}, faces


def _dome(w: float, h: float) -> tuple:
    """Return a horizontal vessel with a manway dome on top.

    Parameters
    ----------
    w, h : float
        Box.

    Returns
    -------
    tuple
        Artwork, ports and bands.
    """
    top = _DOME_NECK + _DOME_CAP
    ry, mid = (h - top) / 2, top + (h - top) / 2
    x0, x1 = _DISHED, w - _DISHED
    right = x1 - _DOME_OFF
    left, apex = right - _DOME_W, right - _DOME_W / 2
    head = f"A {_n(_DISHED)} {_n(ry)} 0 0 1"
    cap = f"A {_n(_DOME_W / 2)} {_n(_DOME_CAP)} 0 0 1"
    art = (f'<path d="M {_n(x1)} {_n(top)} {head} {_n(w)} {_n(mid)} {head} {_n(x1)} {_n(h)} '
           f'L {_n(x0)} {_n(h)} {head} 0 {_n(mid)} {head} {_n(x0)} {_n(top)} '
           f'L {_n(left)} {_n(top)} L {_n(left)} {_n(_DOME_CAP)} {cap} {_n(apex)} 0 '
           f'{cap} {_n(right)} {_n(_DOME_CAP)} L {_n(right)} {_n(top)} Z" {_OUTLINE}/>')
    # The head nozzles sit on the heads' outline, above the axis.
    nozzle, inset = mid - _DOME_NOZZLE, _on_head(ry, _DISHED, _DOME_NOZZLE)
    ports = {"inlet": (inset, nozzle), "outlet": (w - inset, nozzle), "vent": (apex, 0.0),
             "relief": ((x0 + left) / 2, top), "drain": (w / 2, h)}
    return art, ports, {"W": (nozzle, nozzle), "E": (nozzle, nozzle)}


_BUILDERS = {
    "default": _default,
    "dished": _dished,
    "dome": _dome,
    "electrical_heating": _electrical,
    "horizontal": _horizontal,
    "insulated": lambda w, h: _clad(w, h, insulated=True),
    "jacketed": lambda w, h: _clad(w, h, insulated=False),
    "swaged": _swaged,
}


def vessel_shell(variant: str, width: float | None = None,
                 height: float | None = None) -> Symbol:
    """Return a vessel's shell drawn at a size.

    Parameters
    ----------
    variant : str
        One of :data:`VESSEL_SIZES`.
    width, height : float, optional
        Box; the variant's natural size where ``None``.

    Returns
    -------
    Symbol
        The shell, with its nozzles and walls; one object per size.
    """
    nw, nh = VESSEL_SIZES[variant]
    return _shell(variant, float(nw if width is None else width),
                  float(nh if height is None else height))


@lru_cache(maxsize=None)
def _shell(variant: str, w: float, h: float) -> Symbol:
    """Return a vessel's shell drawn at a size.

    Parameters
    ----------
    variant : str
        One of :data:`VESSEL_SIZES`.
    w, h : float
        Box.

    Returns
    -------
    Symbol
        The shell, with its nozzles and walls.
    """
    built = _BUILDERS[variant](w, h)
    art, ports, bands = built[:3]
    faces = built[3] if len(built) > 3 else {}
    family = _shell_family(variant, w, ports)
    if "N" in family.get("inlet", {}):
        x = family["inlet"]["N"][0]
        bands = {**bands, "N": (x, x)}
    name = f"sym_vessel{'' if variant == 'default' else '_' + variant}"
    return Symbol(
        svg=f'<g id="{name}">{art}</g>',
        width=w, height=h,
        ports={k: (round(x, 4), round(y, 4)) for k, (x, y) in ports.items()},
        port_faces={role: {face: (round(x, 4), round(y, 4)) for face, (x, y) in menu.items()}
                    for role, menu in faces.items()},
        family_faces={role: {face: (round(x, 4), round(y, 4)) for face, (x, y) in menu.items()}
                      for role, menu in family.items()},
        bands={k: (round(lo, 4), round(hi, 4)) for k, (lo, hi) in bands.items()},
        id_suffix="" if (w, h) == VESSEL_SIZES[variant] else f"_{w:g}x{h:g}",
        drawio_shape=_DRAWIO[variant],
        gravity_fixed=True,
    )


def _shell_family(variant: str, w: float, ports: dict[str, tuple[float, float]]
                  ) -> dict[str, dict[str, tuple[float, float]]]:
    """Return the family faces of a vessel's shell.

    An upright shell's inlet and outlet each take the opposite wall at
    their own height, and its inlet the top head opposite the relief;
    the heater takes ``electrical_heating``'s east wall. A dome's take
    the opposite head. A horizontal drum has none.

    Parameters
    ----------
    variant : str
        Vessel variant.
    w : float
        Box width.
    ports : dict[str, tuple[float, float]]
        The shell's nozzles.

    Returns
    -------
    dict[str, dict[str, tuple[float, float]]]
        ``"inlet"`` and ``"outlet"`` to their further placements by face.
    """
    if variant == "horizontal":
        return {}
    # The vent marks an upright shell's axis.
    axis = w / 2 if variant == "dome" else ports["vent"][0]

    def mirrored(name: str) -> tuple[float, float]:
        """Return a nozzle mirrored about the shell's axis.

        Parameters
        ----------
        name : str
            Nozzle.

        Returns
        -------
        tuple[float, float]
            Mirrored point.
        """
        x, y = ports[name]
        return 2 * axis - x, y

    inlet = {} if variant == "electrical_heating" else {"E": mirrored("inlet")}
    if variant != "dome":
        inlet["N"] = mirrored("relief")
    return {"inlet": inlet, "outlet": {"W": mirrored("outlet")}}


def vessel_shell_fits(variant: str) -> tuple[float, float]:
    """Return the smallest box a shell can be drawn in.

    Parameters
    ----------
    variant : str
        One of :data:`VESSEL_SIZES`.

    Returns
    -------
    tuple[float, float]
        Least width and least height.
    """
    def reach(depth: float) -> float:
        """Return the half-width a head needs to carry its relief clear of its vent.

        Parameters
        ----------
        depth : float
            Head's depth.

        Returns
        -------
        float
            Least half-width.
        """
        m = _RELIEF_MIN ** 2
        return math.sqrt((m + math.sqrt(m * m + 4 * m * depth ** 2)) / 2)

    least = {
        "default": (2 * reach(_HEAD), 2 * _HEAD),
        "dished": (2 * reach(_DISHED) + 2 * _BRACKET,
                   2 * _DISHED + _BRACKET_FOOT + _BRACKET),
        # The relief stays off the head and nearer the roof than the end.
        "dome": (max(2 * _DISHED + _BAND_GAP, 2 * (_DOME_NECK + _DOME_CAP + 1))
                 + _DOME_OFF + _DOME_W, _DOME_NECK + _DOME_CAP + 2 * _DOME_NOZZLE),
        "electrical_heating": (max(2 * reach(_DISHED), _HEATER_REACH + 1) + _HEATER_REACH,
                               _HEATER_H + 2 * _HEATER_LEAD),
        "horizontal": (_DRUM_HEAD / min(_DRUM_INLET_N, 1 - _DRUM_OUTLET), 1.0),
        "insulated": (2 * reach(_DISHED) + 2 * _CLAD, 2 * (_DISHED + _CLAD_END)),
        "jacketed": (2 * reach(_DISHED) + 2 * _CLAD, 2 * (_DISHED + _CLAD_END)),
        "swaged": (2 * reach(_SWAGE_TOP) + 2 * _SWAGE_STEP,
                   _SWAGE_TOP + _SWAGE_NECK + _SWAGE_CONE + _SWAGE_HEAD),
    }
    return least[variant]


def vessel_floor(variant: str, width: float, height: float, x: float) -> float:
    """Return how far down a shell's outline reaches at a point across it.

    Parameters
    ----------
    variant : str
        One of :data:`VESSEL_SIZES`.
    width, height : float
        The shell's box.
    x : float
        Distance across the box, held to the shell's own span.

    Returns
    -------
    float
        Depth of the shell's lowest outline at ``x``.
    """
    heads = {
        "default": (width / 2, width / 2, _HEAD),
        "dished": (width / 2, width / 2 - _BRACKET, _DISHED),
        "electrical_heating": ((width - _HEATER_REACH) / 2, (width - _HEATER_REACH) / 2, _DISHED),
        "insulated": (width / 2, width / 2 - _CLAD, _DISHED),
        "jacketed": (width / 2, width / 2 - _CLAD, _DISHED),
        "swaged": (width / 2, width / 2, _SWAGE_HEAD),
    }
    if variant not in heads:
        # A lying shell's floor is its straight bottom wall.
        return height
    cx, rx, depth = heads[variant]
    off = min(abs(x - cx), rx)
    return height - depth + depth * math.sqrt(max(0.0, 1 - (off / rx) ** 2))


def _own_detail(variant: str, height: float) -> list[tuple[str, float, float]]:
    """Return the stretches of a shell's side walls its own detail covers.

    Parameters
    ----------
    variant : str
        Vessel variant.
    height : float
        Box height.

    Returns
    -------
    list[tuple[str, float, float]]
        ``(face, top, bottom)`` of the dished vessel's brackets and of
        the electric heater with its leads.
    """
    if variant == "dished":
        top = height - _DISHED - _BRACKET_FOOT - _BRACKET
        return [(face, top, top + _BRACKET) for face in ("W", "E")]
    if variant == "electrical_heating":
        reach = _HEATER_H / 2 + _HEATER_LEAD
        return [("E", height / 2 - reach, height / 2 + reach)]
    return []


def vessel_side(variant: str, width: float, height: float) -> tuple[float, float]:
    """Return the stretch of a shell's west edge its outline meets.

    Parameters
    ----------
    variant : str
        One of :data:`VESSEL_SIZES`.
    width, height : float
        The shell's box.

    Returns
    -------
    tuple[float, float]
        ``(top, bottom)`` down the west edge of the box.
    """
    if variant == "dished":
        foot = height - _DISHED - _BRACKET_FOOT
        return foot, foot
    if variant in ("jacketed", "insulated"):
        return _DISHED + _CLAD_END, height - _DISHED - _CLAD_END
    if variant == "swaged":
        return _SWAGE_TOP + _SWAGE_NECK + _SWAGE_CONE, height - _SWAGE_HEAD
    if variant == "horizontal":
        return height / 2, height / 2
    if variant == "dome":
        top = _DOME_NECK + _DOME_CAP
        return top + (height - top) / 2, top + (height - top) / 2
    head = _HEAD if variant == "default" else _DISHED
    return head, height - head


def _nearest_stretch(band: "tuple[float, float] | None", along: float,
                     inset: float, count: int) -> "tuple[float, float] | None":
    """Return the stretch of a band nearer its face than either end.

    Parameters
    ----------
    band : tuple[float, float] or None
        ``(lo, hi)`` a family may use; the whole face if ``None``.
    along : float
        Face length.
    inset : float
        Distance in from the face's edge to the wall the family is on.
    count : int
        Family size.

    Returns
    -------
    tuple[float, float] or None
        The band cut to points nearer the face than the ends of the
        box, or ``band`` when that leaves too little room to keep
        ``count`` members apart.
    """
    lo, hi = (0.0, along) if band is None else band
    near = (max(lo, inset + _COINCIDENT), min(hi, along - inset - _COINCIDENT))
    return near if near[1] - near[0] >= (count - 1) * _COINCIDENT else band


# Pitch and extent of tank and vessel inlet and outlet families.
_VESSEL_PITCH = 20.0
_VESSEL_EXTENT = 0.7

#: Clearance of a nozzle from a support beside its wall: an arrowhead's
#: half-width and the gap ISO 128-20 4.4 asks for at an inlet, the gap
#: alone at an outlet.
_SUPPORT_CLEARANCE = {"inlet": ARROWHEAD / 2 + MIN_HEAD_CLEARANCE, "outlet": MIN_HEAD_CLEARANCE}


@lru_cache(maxsize=None)
def _vessel_base(kind: str, variant: str, overlays: "tuple[Overlay, ...]",
                 ports: "tuple[tuple[str, tuple[float, float]], ...]",
                 size: "tuple[float, float] | None"
                 ) -> "tuple[Symbol, list[tuple[str, float, float]]]":
    """Return a tank or vessel with its parts, and the supports beside it.

    Parameters
    ----------
    kind : str
        ``"tank"`` or ``"vessel"``.
    variant : str
        Resolved variant.
    overlays : tuple[Overlay, ...]
        The unit's parts.
    ports : tuple[tuple[str, tuple[float, float]], ...]
        ``(name, point)`` nozzles the parts add, in body coordinates.
    size : tuple[float, float] or None
        Box of a shell built to size; the registered body if ``None``.

    Returns
    -------
    tuple
        The composed symbol, and each support beside a wall as
        ``(face, start, end)`` along that face.
    """
    from pandid.render.iso_parts import SUPPORTS

    if size is None:
        base = default_registry.composed(kind, variant, overlays, ports)
        body = default_registry.get(kind, variant)
    else:
        body = vessel_shell(variant, *size)
        drawn = replace(body, ports={**body.ports, **dict(ports)}) if ports else body
        base = compose(drawn, [(o, default_registry.part(o.group, o.name)) for o in overlays])
    boxes = overlay_boxes(body, overlays)
    oy = -min([0.0, *(o.y * body.height for o in overlays)])
    spans = []
    # A skirt carries the bottom connections through it.
    for o, (left, top, right, bottom) in zip(overlays, boxes):
        if o.name not in SUPPORTS or o.name == "skirt":
            continue
        beside = {"W": o.x < 0, "E": o.x + o.w > 1, "N": o.y < 0, "S": o.y + o.h > 1}
        spans += [(face, top, bottom) if face in ("W", "E") else (face, left, right)
                  for face, out in beside.items() if out]
    if kind == "vessel" and body is vessel_shell(variant, body.width, body.height):
        spans += [(face, a + oy, b + oy) for face, a, b in _own_detail(variant, body.height)]
    return base, spans


def _family_band(band: "tuple[float, float] | None", along: float, inset: float,
                 t0: float, count: int, spans: "list[tuple[float, float]]",
                 clearance: float, wall: bool) -> "tuple[tuple[float, float] | None, float]":
    """Return the stretch a family is spread in, and the length it lacks.

    The stretch is nearer the family's face than either end of the box
    and clear of the supports beside the wall, and holds the family at
    :data:`MIN_NOZZLE_PITCH`; the clear stretch nearest the anchor that
    does, else the longest clear stretch.

    Parameters
    ----------
    band : tuple[float, float] or None
        ``(lo, hi)`` the face offers; the whole face if ``None``.
    along : float
        Face length.
    inset : float
        Distance in from the face's edge to the wall.
    t0 : float
        The family's anchor along the face.
    count : int
        Family size.
    spans : list[tuple[float, float]]
        Stretches of the face supports cover.
    clearance : float
        Gap kept from a support.
    wall : bool
        Whether the face is a wall that lengthens with the shell, rather
        than a head's apex.

    Returns
    -------
    tuple
        The stretch, and how much longer the face would have to be for
        a clear stretch to hold the family.
    """
    near = _nearest_stretch(band, along, inset, count) if count > 1 else band
    if near is not None and near[0] >= near[1] and (count == 1 or not wall):
        # A head's apex, or a lone nozzle: it cannot move along it.
        return near, 0.0
    need = MIN_NOZZLE_PITCH * (count - 1)
    pieces = [near or (0.0, along)]
    for a, b in spans:
        a, b = a - clearance, b + clearance
        pieces = [p for lo, hi in pieces for p in ((lo, min(hi, a)), (max(lo, b), hi))]
    longest = max(pieces, key=lambda p: p[1] - p[0])
    short = max(need - (longest[1] - longest[0]),
                need / _VESSEL_EXTENT - along if count > 1 else 0.0, 0.0)
    if not spans:
        return near, short
    fit = [p for p in pieces if p[1] - p[0] >= need]
    if fit:
        return min(fit, key=lambda p: max(p[0] - t0, t0 - p[1], 0.0)), short
    if longest[1] - longest[0] >= (count - 1) * _COINCIDENT:
        return longest, short
    return near, short


def _wall_members(base: Symbol, face: str, members: list[str], t0: float,
                  band: "tuple[float, float] | None", along: float,
                  fixed: "dict[str, tuple[float, float]]") -> list[str]:
    """Return a family with the stencil nozzles it crowds on its wall.

    If a member lands nearer a stencil nozzle on its band than the
    family's pitch, the band's stencil nozzles join the family, in order
    along the wall.

    Parameters
    ----------
    base : Symbol
        The tank or vessel with its parts.
    face : str
        The family's face.
    members : list[str]
        The family, in port order.
    t0 : float
        The family's anchor along the face.
    band : tuple[float, float] or None
        ``(lo, hi)`` the face offers; the whole face if ``None``.
    along : float
        Face length.
    fixed : dict[str, tuple[float, float]]
        The stencil's own nozzles.

    Returns
    -------
    list[str]
        Nozzles to spread along the wall, in order.
    """
    lo, hi = band or (0.0, along)
    on_wall = {
        name: _face_local(face, *xy, base.width, base.height)[0]
        for name, xy in fixed.items() if outward_dir(*xy, base.width, base.height) == face
    }
    beside = {name: t for name, t in on_wall.items() if lo <= t <= hi}
    run = [spread(i, len(members), along, _VESSEL_PITCH, _VESSEL_EXTENT, at=t0, band=band)
           for i in range(len(members))]
    pitch = (run[-1] - run[0]) / (len(run) - 1) if len(run) > 1 else 0.0
    if not any(abs(t - f) < pitch for t in run for f in beside.values()):
        return members
    order = sorted(beside, key=beside.__getitem__)
    return ([n for n in order if beside[n] <= t0] + members
            + [n for n in order if beside[n] > t0])


def _has_wall(variant: str, face: str) -> bool:
    """Return whether a vessel shell's face is a wall at its natural size.

    Parameters
    ----------
    variant : str
        Vessel variant.
    face : str
        Face name.

    Returns
    -------
    bool
        Whether the face's band has length.
    """
    lo, hi = default_registry.get("vessel", variant).bands.get(face, (0.0, 1.0))
    return lo < hi


def _groups(faces: tuple[tuple[str, str], ...]) -> dict[str, list[str]]:
    """Return a tank's or vessel's family ports, by face.

    Parameters
    ----------
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` for the inlet and outlet families.

    Returns
    -------
    dict[str, list[str]]
        Inlets and outlets on each face, in drawn order.
    """
    groups: dict[str, list[str]] = {}
    for port_name, face in faces:
        groups.setdefault(face, []).append(port_name)
    return groups


def _role(port_name: str) -> str:
    """Return the family a tank's or vessel's port belongs to.

    Parameters
    ----------
    port_name : str
        ``in_*`` or ``out_*``.

    Returns
    -------
    str
        ``"inlet"`` or ``"outlet"``.
    """
    return "inlet" if port_name.startswith("in_") else "outlet"


def _reach(base: Symbol) -> dict[str, dict[str, tuple[float, float]]]:
    """Return each family's placements: its menu, then its family faces.

    Parameters
    ----------
    base : Symbol
        Tank or vessel body.

    Returns
    -------
    dict[str, dict[str, tuple[float, float]]]
        ``"inlet"`` and ``"outlet"`` to their placements by face.
    """
    return {role: {**base.port_faces.get(role, {}), **base.family_faces.get(role, {})}
            for role in ("inlet", "outlet")}


def _face_anchor(base: Symbol, reach: dict[str, dict[str, tuple[float, float]]],
                 face: str, members: list[str]) -> tuple[float, float, float]:
    """Return where a face's family ports spread from, and their clearance.

    Inlets and outlets on one face spread about their anchors' mean,
    and keep the larger of their clearances from the supports.

    Parameters
    ----------
    base : Symbol
        Tank or vessel body.
    reach : dict[str, dict[str, tuple[float, float]]]
        What :func:`_reach` returned.
    face : str
        Face the ports are on.
    members : list[str]
        Family ports on the face.

    Returns
    -------
    tuple[float, float, float]
        Anchor along the face, inset from its edge, and clearance.
    """
    roles = {_role(name) for name in members}
    local = {_face_local(face, *reach[role][face], base.width, base.height) for role in roles}
    t0, inset = (next(iter(local)) if len(local) == 1 else
                 (sum(t for t, _ in local) / len(local), sum(i for _, i in local) / len(local)))
    return t0, inset, max(_SUPPORT_CLEARANCE[role] for role in roles)


@lru_cache(maxsize=None)
def vessel_room(variant: str, faces: tuple[tuple[str, str], ...],
                overlays: "tuple[Overlay, ...]",
                ports: "tuple[tuple[str, tuple[float, float]], ...]",
                size: "tuple[float, float]") -> "tuple[float, float]":
    """Return how much wider and taller a vessel's shell must be.

    The shell is long enough when each family has a stretch of its wall
    clear of the supports that holds it at :data:`MIN_NOZZLE_PITCH`.

    Parameters
    ----------
    variant : str
        Vessel variant.
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` for the inlet and outlet families.
    overlays : tuple[Overlay, ...]
        The vessel's parts, placed on the shell.
    ports : tuple[tuple[str, tuple[float, float]], ...]
        ``(name, point)`` nozzles the parts add, in body coordinates.
    size : tuple[float, float]
        The shell's box.

    Returns
    -------
    tuple[float, float]
        Width and height to add.
    """
    base, spans = _vessel_base("vessel", variant, overlays, ports, size)
    reach = _reach(base)
    wide = tall = 0.0
    for face, members in _groups(faces).items():
        if any(face not in reach[_role(name)] for name in members):
            continue
        t0, inset, clearance = _face_anchor(base, reach, face, members)
        along = base.height if face in ("W", "E") else base.width
        band = base.bands.get(face)
        fixed = {name: xy for name, xy in base.ports.items()
                 if name not in ("inlet", "outlet", *dict(ports))}
        members = _wall_members(base, face, members, t0, band, along, fixed)
        _, short = _family_band(band, along, inset, t0, len(members),
                                [(a, b) for f, a, b in spans if f == face],
                                clearance, _has_wall(variant, face))
        if face in ("W", "E"):
            tall = max(tall, short)
        else:
            wide = max(wide, short)
    return wide, tall


@lru_cache(maxsize=None)
def vessel_symbol(kind: str, variant: str, faces: tuple[tuple[str, str], ...],
                  overlays: "tuple[Overlay, ...]" = (),
                  ports: "tuple[tuple[str, tuple[float, float]], ...]" = (),
                  size: "tuple[float, float] | None" = None) -> Symbol:
    """Return a tank or vessel symbol with its nozzle families placed.

    The family ports on a face are spread about the stencil's anchor,
    or the mean of the inlet's and outlet's where both share it, within
    the part of :attr:`Symbol.bands` nearer its face than either end of
    the box, clear of the supports beside its wall where that stretch
    holds it. A family may take :attr:`Symbol.family_faces` too; a role
    with one member keeps its full menu. If a member lands nearer
    a stencil nozzle on its band than the family's pitch, the band's
    stencil nozzles are spread with the family, in order along the
    wall.

    Parameters
    ----------
    kind : str
        ``"tank"`` or ``"vessel"``.
    variant : str
        Resolved variant.
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` for the inlet and outlet families.
    overlays : tuple[Overlay, ...], default=()
        The unit's composed parts.
    ports : tuple[tuple[str, tuple[float, float]], ...], default=()
        ``(name, point)`` nozzles the parts add, in body coordinates.
    size : tuple[float, float], optional
        Box of a vessel shell built to size; the registered body if
        omitted.

    Returns
    -------
    Symbol
        Symbol with the families placed.

    Raises
    ------
    ValueError
        If the variant or a part is unregistered, or composing fails.
    ValueError
        If a role has no placement on a requested face.
    ValueError
        If two or more nozzles share a face whose band is one point.
    ValueError
        If the parts leave a nozzle nearer another edge than its face.
    """
    base, spans = _vessel_base(kind, variant, overlays, ports, size)
    placed = {name: xy for name, xy in base.ports.items() if name not in ("inlet", "outlet")}
    port_faces = {
        name: dict(menu) for name, menu in base.port_faces.items()
        if name not in ("inlet", "outlet")
    }
    fixed = [name for name in placed if name not in dict(ports)]
    menus = {"inlet": base.port_faces.get("inlet", {}), "outlet": base.port_faces.get("outlet", {})}
    reach = _reach(base)
    members_by_role: dict[str, list[str]] = {"inlet": [], "outlet": []}
    by_face: dict[str, list[str]] = {}
    for port_name, face in faces:
        members_by_role[_role(port_name)].append(port_name)
        by_face.setdefault(face, []).append(port_name)
    for face, members in by_face.items():
        missing = [name for name in members if face not in reach[_role(name)]]
        if missing:
            role = _role(missing[0])
            raise ValueError(
                f"{kind}/{variant}: {role} has no {face!r} placement to draw "
                f"{', '.join(missing)} on; offered: "
                f"{', '.join(reach[role]) if reach[role] else 'nothing'}"
            )
        t0, inset, clearance = _face_anchor(base, reach, face, members)
        along = base.height if face in ("W", "E") else base.width
        band = base.bands.get(face)
        members = _wall_members(base, face, members, t0, band, along,
                                {name: placed[name] for name in fixed})
        band, _ = _family_band(band, along, inset, t0, len(members),
                               [(a, b) for f, a, b in spans if f == face],
                               clearance, kind == "vessel" and _has_wall(variant, face))
        for i, name in enumerate(members):
            t = spread(i, len(members), along, _VESSEL_PITCH, _VESSEL_EXTENT,
                       at=t0, band=band)
            placed[name] = _face_point(face, t, inset, base.width, base.height)
            if face in port_faces.get(name, {}):
                port_faces[name][face] = placed[name]
            lands = outward_dir(*placed[name], base.width, base.height)
            if lands != face:
                raise ValueError(
                    f"{kind}/{variant}: {name} is drawn on the {face} wall at "
                    f"{placed[name]}, which the parts beside the body leave nearer the "
                    f"{lands} edge of the {base.width:g}x{base.height:g} box, so its "
                    f"line would leave {lands}. Put fewer nozzles on {face}, or the "
                    f"parts on another wall"
                )
    # Inlets and outlets count together on a point face.
    for face, on_face in by_face.items():
        band = base.bands.get(face)
        if len(on_face) > 1 and band is not None and band[0] >= band[1]:
            raise bandless_face(f"{kind}/{variant}", face, band[0], on_face, base)
    # A lone member keeps its own placement and the faces of its menu no
    # other family member is on.
    on = dict(faces)
    for role, members in members_by_role.items():
        if len(members) == 1 and menus[role]:
            name = members[0]
            port_faces[name] = {
                **{face: xy for face, xy in menus[role].items()
                   if not any(face == on[other] for other in on if other != name)},
                on[name]: placed[name],
            }
    return replace(base, ports=placed, port_faces=port_faces)


@lru_cache(maxsize=None)
def series_symbol(kind: str, variant: str, faces: tuple[tuple[str, str], ...],
                  overlays: "tuple[Overlay, ...]" = ()) -> Symbol:
    """Return a symbol with its series members on the faces given.

    The members on one face, in the order given, are one series there,
    spread about the mean of their families' anchors on it.

    Parameters
    ----------
    kind : str
        Unit kind.
    variant : str
        Resolved variant.
    faces : tuple[tuple[str, str], ...]
        ``(port_name, face)`` for every member of the symbol's series.
    overlays : tuple[Overlay, ...], default=()
        The unit's composed parts.

    Returns
    -------
    Symbol
        The symbol, one series per face.

    Raises
    ------
    ValueError
        If a member's family has no placement on its face, or two
        members share a face that is one point.
    """
    base = default_registry.composed(kind, variant, overlays)
    by_face: dict[str, list[tuple[str, PortSeries]]] = {}
    for name, face in faces:
        series = base.series_for(name)
        placed = series.on(face) if series is not None else None
        if placed is None:
            raise ValueError(f"{kind}/{variant}: {name} has no placement on the {face} face")
        by_face.setdefault(face, []).append((name, placed))
    split = []
    for face, members in by_face.items():
        placements = [placed for _, placed in members]
        if len(members) > 1 and any(placed.extent == 0.0 for placed in placements):
            raise ValueError(
                f"{kind}/{variant}: {', '.join(name for name, _ in members)} are all on the "
                f"{face} face, which takes one nozzle")
        along = base.height if face in ("W", "E") else base.width
        ats = {along / 2 if placed.at is None else placed.at for placed in placements}
        at = next(iter(ats)) if len(ats) == 1 else sum(ats) / len(ats)
        split.append(replace(placements[0], at=at, members=tuple(name for name, _ in members),
                             also=()))
    named = {name for name, _ in faces}
    kept = tuple(series for series in base.port_series
                 if not any(series.matches(name) for name in named))
    return replace(base, port_series=(*split, *kept))


# Builders of symbols drawn per unit, by (kind, variant). A ``None``
# variant matches every variant.
_BUILT_TO_SIZE: "dict[tuple[str, str | None], Callable[..., Symbol]]" = {
    ("conveyor", "default"): lambda unit: conveyor_symbol(unit.length,
                                                          unit.diameter),
    ("conveyor", "screw"): lambda unit: screw_conveyor_symbol(unit.length,
                                                              unit.diameter),
    ("block", None): lambda unit: unit.symbol(),
    ("mixer", "default"): _junction,
    ("splitter", "default"): _junction,
    ("tank", None): lambda unit: unit.symbol(),
    ("vessel", None): lambda unit: unit.symbol(),
    ("evaporator", None): lambda unit: unit.symbol(),
}


# Normally closed devices.

#: Valve variants whose body is darkened when normally closed.
NC_DARKENS = frozenset({
    "default", "gate", "globe", "ball", "needle", "plug", "pinch", "three_way",
    "angle", "bleed", "manual", "motor", "solenoid", "hydraulic",
})

#: Valve variants that may not be normally closed
#: (PIP PIC001 4.2.2.10).
NC_FORBIDDEN = frozenset({"control", "regulator", "relief", "psv"})

# Valve body and actuator pairings.

#: ``(body, actuator)`` to the variant whose artwork draws the pair.
ACTUATED: dict[tuple[str, str], str] = {
    ("default", "diaphragm"): "control",
    ("gate", "diaphragm"): "control",
    ("butterfly", "diaphragm"): "butterfly_pneumatic",
    # Lettered operator boxes.
    ("default", "motor"): "motor",
    ("gate", "motor"): "motor",
    ("default", "solenoid"): "solenoid",
    ("gate", "solenoid"): "solenoid",
    ("default", "hydraulic"): "hydraulic",
    ("gate", "hydraulic"): "hydraulic",
    ("default", "handwheel"): "manual",
    ("gate", "handwheel"): "manual",
}

#: Actuators that may be named.
ACTUATORS: tuple[str, ...] = ("diaphragm", "motor", "solenoid", "hydraulic",
                              "handwheel")


def variant_actuator(variant: str) -> str:
    """Return the actuator a valve variant draws, from :data:`ACTUATED`.

    Parameters
    ----------
    variant : str
        Resolved valve variant.

    Returns
    -------
    str
        One of :data:`ACTUATORS`, or ``""`` if the variant draws none.
    """
    return next((a for (_, a), drawn in ACTUATED.items() if drawn == variant), "")


def actuated_variant(body: str, actuator: str) -> str:
    """Return the variant drawing ``body`` with ``actuator`` on it.

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
        If no variant draws the pairing.
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


# Fail position: where an actuated valve goes on loss of power.

#: Fail positions and the letters drawn for them (ANSI/ISA-5.1-2009
#: Table 5.4.4 Method B).
FAIL_POSITIONS: dict[str, str] = {
    "open": "FO",
    "closed": "FC",
    "last": "FL",
    "drift_open": "FL/DO",
    "drift_closed": "FL/DC",
    "indeterminate": "FI",
}

#: Valve variants with a powered actuator, which take a fail position.
FAIL_ACTUATED = frozenset({
    "control", "butterfly_pneumatic", "solenoid", "motor", "hydraulic",
})


def fail_marking(unit) -> str:
    """Return the fail-position letters for a valve, or ``""``.

    Parameters
    ----------
    unit : Unit
        Valve.

    Returns
    -------
    str
        Letters from :data:`FAIL_POSITIONS`, or ``""`` if none declared.

    Raises
    ------
    ValueError
        If the variant has no powered actuator but declares ``fail``.
    """
    declared = getattr(unit, "fail", "") or ""
    if not declared:
        return ""
    if getattr(unit, "variant", "") not in FAIL_ACTUATED:
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: declared fail={declared!r}, but "
            f"variant {getattr(unit, 'variant', '')!r} has no actuator to lose its "
            f"motive power. The variants that take a fail position are: "
            f"{', '.join(sorted(FAIL_ACTUATED))}."
        )
    return FAIL_POSITIONS[declared]


# Fill for a darkened body.
_BODY_INK = "#111"

# The body is the artwork's first <path>.
_FIRST_PATH = re.compile(r"<path\b[^>]*>")

# The body's fill before darkening.
_BODY_PAPER = 'fill="white"'


def closed_marking(unit, registry=None) -> str:
    """Return how a unit's normally closed position is drawn.

    ``"stencil"`` uses a registered closed drawing, ``"fill"`` darkens
    the body (PIP PIC001 4.2.2.7) and ``"NC"`` letters the valve
    (ISO 15519-1 11.4.5).

    Parameters
    ----------
    unit : Unit
        Valve or fitting.
    registry : SymbolRegistry, optional
        Registry of closed drawings; ``default_registry`` when omitted.

    Returns
    -------
    str
        ``"stencil"``, ``"fill"``, ``"NC"``, or ``""`` if not closed.

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
    # Only valves take the fill or the letters.
    if unit.kind != "valve":
        raise ValueError(
            f"{getattr(unit, 'name', unit.kind)}: {unit.kind}/{variant} is drawn one "
            f"way, so nothing can show it normally closed. Either it is the wrong "
            f"variant for a device that isolates a line, or normal_position should "
            f"be 'open'."
        )
    return "fill" if variant in NC_DARKENS else "NC"


def darkened(sym: Symbol) -> Symbol:
    """Return ``sym`` with its body filled and an ``_nc`` id suffix.

    Every other field is kept.

    Parameters
    ----------
    sym : Symbol
        Open valve symbol.

    Returns
    -------
    Symbol
        Normally closed valve symbol.

    Raises
    ------
    ValueError
        If the first ``<path>`` is missing or not filled white.
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
    return replace(
        sym, svg=re.sub(r'id="([^"]*)"', r'id="\1_nc"', svg, count=1),
        id_suffix=sym.id_suffix + "_nc",
        # Carry the fill to the draw.io export.
        drawio_fill=_BODY_INK,
    )


# Expander: a reducer piped the other way round.

# Face after a left-to-right mirror.
_FLIPPED_FACE = {"W": "E", "E": "W", "N": "N", "S": "S"}

# A symbol's artwork as opening <g>, contents and closing tag.
_GROUP = re.compile(r"\A(<g\b[^>]*>)(.*)(</g>)\Z", re.DOTALL)


def expander(sym: Symbol) -> Symbol:
    """Return ``sym`` turned end for end, as an expander.

    The artwork, bands and overlays are mirrored left to right and
    ``inlet`` and ``outlet`` trade placements. The id gains ``_exp``.
    Every other field is kept.

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
        If the ports are not exactly ``inlet`` and ``outlet``.
    ValueError
        If the artwork is not a single ``<g>`` group.
    """
    swap = {"inlet": "outlet", "outlet": "inlet"}
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
    # Mirror about the box's mid-line.
    svg = (f'{head}<g transform="translate({sym.width:g},0) scale(-1,1)">'
           f'{body}</g>{tail}')

    def turn(xy: tuple[float, float]) -> tuple[float, float]:
        """Return ``xy`` mirrored left to right in the symbol box.

        Parameters
        ----------
        xy : tuple[float, float]
            Point in symbol coordinates.

        Returns
        -------
        tuple[float, float]
            Mirrored point.
        """
        return (round(sym.width - xy[0], 4), xy[1])

    # ``replace`` carries every field the mirror does not change.
    return replace(
        sym, svg=svg,
        ports={new: turn(sym.ports[old]) for new, old in swap.items()},
        port_faces={new: {_FLIPPED_FACE[face]: turn(xy)
                          for face, xy in sym.port_faces[old].items()}
                    for new, old in swap.items()},
        bands={_FLIPPED_FACE[face]: span if face in ("W", "E")
               else (sym.width - span[1], sym.width - span[0])
               for face, span in sym.bands.items()},
        overlays=tuple(replace(o, x=1 - o.x - o.w, mirror=not o.mirror)
                       for o in sym.overlays),
        id_suffix=sym.id_suffix + "_exp",
        # Carry the flip to the draw.io export.
        drawio_flip_h=not sym.drawio_flip_h,
    )


# Composition: a body carrying its parts.


@dataclass(frozen=True)
class OverlayPart:
    """One supplementary symbol's artwork, and the ISO item it is.

    :func:`compose` maps the part's own box onto the rectangle of the
    body an :class:`Overlay` names. A part's ports are added to the
    body's.

    Attributes
    ----------
    name : str
        Registry name, such as ``"turbine"``.
    iso : IsoPart
        The Table 2 item this drawing is.
    svg : str
        A single ``<g>`` group.
    width, height : float
        Positive box the artwork is drawn in.
    ports : dict[str, tuple[float, float]]
        Connections the part brings, inside its own box.
    stretchable : bool
        Whether the artwork may be scaled unevenly.
    gravity_fixed : bool
        Whether a body carrying the part may not be turned.
    directional : bool
        Whether an axis flip would reverse what the artwork says.
    drawio_shape : str
        draw.io stencil that draws this part alone, or empty.

    Raises
    ------
    ValueError
        If the name, box, artwork or a port position is invalid.
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
        """Check the name, box, artwork and port positions.

        Raises
        ------
        ValueError
            If the name, box, artwork or a port position is invalid.
        """
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
        """Return the registry key ``(group, name)``.

        Returns
        -------
        tuple[int, str]
            ISO subject group and part name.
        """
        return (self.iso.group, self.name)


# A stroke-width attribute.
_STROKE = re.compile(r'stroke-width="([\d.]+)"')


def _shifted_series(series: PortSeries, body: Symbol, ox: float, oy: float,
                    width: float, height: float) -> PortSeries:
    """Return ``series`` moved and rescaled onto the composed box.

    Parameters
    ----------
    series : PortSeries
        Body's port series.
    body : Symbol
        Body being composed.
    ox, oy : float
        Offset of the body in the composed box.
    width, height : float
        Composed box.

    Returns
    -------
    PortSeries
        The series with ``at`` and ``inset`` moved, ``extent`` rescaled,
        and its further faces moved alike.
    """
    along, grown = ((body.height, height) if series.face in ("W", "E")
                    else (body.width, width))
    offset = oy if series.face in ("W", "E") else ox
    across = {"W": ox, "E": width - ox - body.width, "N": oy,
              "S": height - oy - body.height}[series.face]
    also = tuple(_shifted_series(s, body, ox, oy, width, height) for s in series.also)
    if (offset, along, across) == (0.0, grown, 0.0) and also == series.also:
        return series
    at = (along / 2 if series.at is None else series.at) + offset
    return replace(series, at=at, extent=series.extent * along / grown,
                   inset=series.inset + across, also=also)


def compose(body: Symbol, parts: "list[tuple[Overlay, OverlayPart]]",
            iso_reg: str = "") -> Symbol:
    """Return ``body`` with its supplementary parts painted over it.

    Each part maps from its own box onto the fraction of the body box
    its :class:`Overlay` names, and the box grows to hold every part.

    Parameters
    ----------
    body : Symbol
        Body drawn as one ``<g>`` group.
    parts : list[tuple[Overlay, OverlayPart]]
        Placements and the parts placed.
    iso_reg : str, default=""
        Registration number of the composition, if it has one.

    Returns
    -------
    Symbol
        Composed symbol.

    Raises
    ------
    ValueError
        If the body is not one group, a port moves face or names clash.
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
            # Keep the aspect: use the smaller scale and centre.
            scale = min(sx, sy)
            rx, ry = rx + (rw - scale * part.width) / 2, ry + (rh - scale * part.height) / 2
            sx = sy = scale
        placed.append((part, rx, ry, sx, sy, overlay.mirror))

    xs = [0.0, body.width]
    ys = [0.0, body.height]
    for part, rx, ry, sx, sy, _ in placed:
        xs += [rx, rx + sx * part.width]
        ys += [ry, ry + sy * part.height]
    # Shift the union's top-left corner to the origin. ``+ 0.0`` turns
    # -0.0 into 0.0.
    ox, oy = -min(xs) + 0.0, -min(ys) + 0.0
    width, height = max(xs) + ox, max(ys) + oy

    art = [inner if (ox, oy) == (0.0, 0.0)
           else f'<g transform="translate({ox:g},{oy:g})">{inner}</g>']
    for part, rx, ry, sx, sy, mirror in placed:
        contents = _GROUP.match(part.svg).group(2)  # type: ignore[union-attr]
        # A mirrored part starts at its rectangle's right edge.
        left = rx + ox + (sx * part.width if mirror else 0.0)
        # Compensate strokes by the geometric mean of the two scales.
        scale = math.sqrt(abs(sx * sy))
        if not math.isclose(scale, 1.0, rel_tol=1e-9):
            contents = _STROKE.sub(
                lambda m: f'stroke-width="{float(m.group(1)) / scale:.6g}"',
                contents)
        art.append(
            f'<g transform="translate({left:g},{ry + oy:g}) '
            f'scale({-sx if mirror else sx:g},{sy:g})">{contents}</g>'
        )

    def shift(xy: "tuple[float, float]") -> "tuple[float, float]":
        """Return a body point moved into the composed box.

        Parameters
        ----------
        xy : tuple[float, float]
            Point in body coordinates.

        Returns
        -------
        tuple[float, float]
            Point in composed coordinates.
        """
        return (round(xy[0] + ox, 4), round(xy[1] + oy, 4))

    ports = {name: shift(xy) for name, xy in body.ports.items()}
    # Refuse a body port that the grown box moves onto another face.
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
        # The body's face menu, moved with the ink.
        port_faces={name: {face: shift(xy) for face, xy in menu.items()}
                    for name, menu in body.port_faces.items()},
        family_faces={name: {face: shift(xy) for face, xy in menu.items()}
                      for name, menu in body.family_faces.items()},
        faceless_ports=body.faceless_ports,
        port_series=tuple(_shifted_series(s, body, ox, oy, width, height)
                          for s in body.port_series),
        bands={face: (lo + (oy if face in ("W", "E") else ox),
                      hi + (oy if face in ("W", "E") else ox))
               for face, (lo, hi) in body.bands.items()},
        label_pos=body.label_pos,
        # One definition per composition, with an id stable across
        # processes.
        id_suffix=body.id_suffix + "_c" + hashlib.blake2s(
            repr([o for o, _ in parts]).encode(), digest_size=4).hexdigest(),
        stretchable=body.stretchable and all(p.stretchable for p, *_ in placed),
        bare_run=body.bare_run,
        gravity_fixed=body.gravity_fixed or any(p.gravity_fixed for p, *_ in placed),
        directional=body.directional or any(p.directional for p, *_ in placed),
        drawio_shape="",
        drawio_body_shape=body.drawio_shape or body.drawio_body_shape,
        drawio_flip_h=body.drawio_flip_h, drawio_fill=body.drawio_fill,
        overlays=tuple(overlay for overlay, _ in parts),
        iso_reg=iso_reg,
    )


def overlay_boxes(body: Symbol, overlays: "tuple[Overlay, ...]"
                  ) -> "list[tuple[float, float, float, float]]":
    """Return where :func:`compose` draws each stretchable part.

    Parameters
    ----------
    body : Symbol
        Body the parts are composed onto.
    overlays : tuple[Overlay, ...]
        Every part on the body.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Each part's ``(left, top, right, bottom)`` in the composed box.
    """
    ox = -min([0.0, *(o.x * body.width for o in overlays)])
    oy = -min([0.0, *(o.y * body.height for o in overlays)])
    return [(o.x * body.width + ox, o.y * body.height + oy,
             (o.x + o.w) * body.width + ox, (o.y + o.h) * body.height + oy)
            for o in overlays]


# The ISO 10628-2 group-8 separating vessel outline, a body for
# compositions.
_SEPARATING_VESSEL = Symbol(
    svg='<g id="sym_separator_vessel">'
        f'<path d="M 0 0 L 80 0 L 80 80 L 40 120 L 0 80 Z" {_OUTLINE}/></g>',
    width=80.0, height=120.0,
    # High draw opposite the feed, collected phase out of the apex.
    ports={"vapor": (80.0, 12.0), "liquid": (40.0, 120.0)},
    # Feeds run down the west wall from (0, 12).
    port_series=(PortSeries("feed_", "W", pitch=20.0, extent=0.5, at=12.0,
                            singular="feed", align=FROM_START),),
    gravity_fixed=True,
)


def _family(outline: str, width: float, height: float, ports: dict, prefix: str,
            name: str, reg: str, *detail: str, gravity_fixed: bool = True) -> Symbol:
    """Return one member of an ISO family: the shared outline plus its marks.

    Parameters
    ----------
    outline : str
        The family's outline.
    width, height : float
        Symbol box.
    ports : dict
        Port positions.
    prefix : str
        Start of the SVG id after ``sym_``.
    name : str
        Rest of the SVG id.
    reg : str
        ISO registration number, or ``""``.
    *detail : str
        Marks drawn over the outline.
    gravity_fixed : bool, default=True
        Whether the symbol keeps its way up.

    Returns
    -------
    Symbol
        The member's symbol.
    """
    return Symbol(
        svg=f'<g id="sym_{prefix}{name}">{outline}' + "".join(detail) + "</g>",
        width=width, height=height, ports=dict(ports),
        gravity_fixed=gravity_fixed, iso_reg=reg,
    )


# Side of the ISO 10628-2 group-9 square outline: 8 modules.
_CENTRIFUGE_SQ = 80.0

# Ink outside the square: a shaft below it (9.1-9.4) or a feed pipe
# through the west wall (9.5-9.8).
_CENTRIFUGE_MARGIN = 10.0


# Ink runs of a perforated wall, as (start, end) offsets from the
# square's near edge.
_CENTRIFUGE_DASH = ((10.0, 20.0), (30.0, 50.0), (60.0, 70.0))


def _dashed_wall(fixed: float, offset: float, vertical: bool) -> str:
    """Return one perforated wall as :data:`_CENTRIFUGE_DASH` runs.

    Parameters
    ----------
    fixed : float
        The wall's x if vertical, else its y.
    offset : float
        Position of the square's near edge along the wall.
    vertical : bool
        Whether the wall is vertical.

    Returns
    -------
    str
        SVG ``<line>`` elements.
    """
    out = []
    for a, b in _CENTRIFUGE_DASH:
        p0, p1 = offset + a, offset + b
        if vertical:
            out.append(f'<line x1="{fixed:g}" y1="{p0:g}" x2="{fixed:g}" y2="{p1:g}" {_INK}/>')
        else:
            out.append(f'<line x1="{p0:g}" y1="{fixed:g}" x2="{p1:g}" y2="{fixed:g}" {_INK}/>')
    return "".join(out)


# Ports of items 9.1-9.4.
_CENTRIFUGE_TOP_PORTS = {
    "feed": (40.0, 0.0),
    "overflow": (80.0, 20.0),
    "underflow": (40.0, 90.0),
}

# Ports of items 9.5-9.8.
_CENTRIFUGE_SIDE_PORTS = {
    "feed": (0.0, 40.0),
    "overflow": (90.0, 20.0),
    "underflow": (80.0, 80.0),
}

# Item 9.1 X2619: an open funnel on a shaft.
_CENTRIFUGE_ROTOR = (
    f'<path d="M 10 70 L 30 20 M 50 20 L 70 70 L 10 70" {_INK}/>'
    f'<line x1="40" y1="70" x2="40" y2="90" {_INK}/>'
)

# Item 9.2 X2614: a basket with perforated side walls.
_CENTRIFUGE_BASKET_DASHED = (
    _dashed_wall(10.0, 0.0, True) + _dashed_wall(70.0, 0.0, True) +
    f'<line x1="10" y1="70" x2="70" y2="70" {_INK}/>'
    f'<line x1="40" y1="70" x2="40" y2="90" {_INK}/>'
)

# Item 9.3 X8035: 9.2's basket with solid side walls.
_CENTRIFUGE_BASKET_SOLID = (
    f'<path d="M 10 70 L 10 10 M 70 70 L 70 10 M 10 70 L 70 70" {_INK}/>'
    f'<line x1="40" y1="70" x2="40" y2="90" {_INK}/>'
)

# Item 9.4 X8036: a disc stack edge on, on a shaft.
_CENTRIFUGE_DISC_STACK = (
    f'<path d="M 10 24 L 40 10 L 70 24 M 10 44 L 40 30 L 70 44" {_INK}/>'
    f'<line x1="40" y1="10" x2="40" y2="90" {_INK}/>'
)

# Item 9.5 X8037: a horizontal perforated basket with a screw flight.
_CENTRIFUGE_SCREW_PERFORATED = (
    f'<line x1="20" y1="10" x2="20" y2="70" {_INK}/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    f'<line x1="0" y1="40" x2="80" y2="40" {_INK}/>'
    f'<path d="M 30 40 L 40 20 L 60 60 L 70 40" {_INK}/>'
)

# Item 9.6 X8082, the decanter: 9.5 with a solid roof and floor.
_CENTRIFUGE_SCREW_SOLID = (
    f'<path d="M 20 70 L 20 10 L 80 10 M 20 70 L 80 70" {_INK}/>'
    f'<line x1="0" y1="40" x2="80" y2="40" {_INK}/>'
    f'<path d="M 30 40 L 40 20 L 60 60 L 70 40" {_INK}/>'
)

# Item 9.7 X8038: 9.5's basket with a pusher rod for the screw.
_CENTRIFUGE_PUSHER = (
    f'<line x1="20" y1="10" x2="20" y2="70" {_INK}/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    f'<line x1="0" y1="40" x2="30" y2="40" {_INK}/>'
    f'<line x1="30" y1="20" x2="30" y2="60" {_INK}/>'
)

# Item 9.8 X8039: 9.5's basket with a skimmer tube.
_CENTRIFUGE_SKIMMER = (
    f'<line x1="20" y1="10" x2="20" y2="70" {_INK}/>'
    + _dashed_wall(10.0, 10.0, False) + _dashed_wall(70.0, 10.0, False) +
    f'<line x1="0" y1="40" x2="20" y2="40" {_INK}/>'
    f'<path d="M 70 20 L 50 20 L 50 10 L 60 20" {_INK}/>'
)


# Box of the ISO 10628-2 group-11 trapezoid outline.
_CRUSHER_W, _CRUSHER_H = 100.0, 60.0

# The group-11 trapezoid outline.
_CRUSHER_OUTLINE = (
    f'<path d="M 0 0 L {_CRUSHER_W:g} 0 L {_CRUSHER_W * 0.8:g} {_CRUSHER_H:g} '
    f'L {_CRUSHER_W * 0.2:g} {_CRUSHER_H:g} Z" {_OUTLINE}/>'
)

# Foot of the mill's corner chord on the sloping wall (item 11.8).
_MILL_CHORD_X, _MILL_CHORD_Y = 100 / 13, 300 / 13

# Group-11 ports: feed above the top edge, discharge below the bottom,
# drive halfway down the east wall.
_CRUSHER_PORTS = {"feed": (_CRUSHER_W / 2, 0.0),
                  "discharge": (_CRUSHER_W / 2, _CRUSHER_H),
                  "drive": (_CRUSHER_W * 0.9, _CRUSHER_H / 2)}


# One group-11 body: the shared trapezoid plus its marks.
_crushing_machine = partial(_family, _CRUSHER_OUTLINE, _CRUSHER_W, _CRUSHER_H, _CRUSHER_PORTS, "")


# Crusher mark, ISO item 11.2 X8085: two full-depth verticals.
_CRUSHER_JAWS = (
    f'<path d="M {_CRUSHER_W * 0.2:g} 0 L {_CRUSHER_W * 0.2:g} {_CRUSHER_H:g} '
    f'M {_CRUSHER_W * 0.8:g} 0 L {_CRUSHER_W * 0.8:g} {_CRUSHER_H:g}" {_INK}/>'
)

# Mill mark, ISO item 11.8 X8086: two chords cutting the top corners.
_MILL_CHAMFERS = (
    f'<path d="M 25 0 L {_MILL_CHORD_X:.4f} {_MILL_CHORD_Y:.4f} '
    f'M 75 0 L {_CRUSHER_W - _MILL_CHORD_X:.4f} {_MILL_CHORD_Y:.4f}" {_INK}/>'
)

# Vibration mill drum, ISO item 11.12 X8054: a 4 M circle.
_VIBRATION_DRUM = f'<circle cx="{_CRUSHER_W / 2:g}" cy="{_CRUSHER_H / 2:g}" r="20" {_INK}/>'


# Stack inlet on the tapering west wall, 8 M down.
_STACK_INLET_Y = 80.0
_STACK_INLET_X = 20.0 - (20.0 - 10.0) * (_STACK_INLET_Y / 100.0)


# ISO 10628-2 group-10 dryer casing, from item 10.1.
_DRIER_W, _DRIER_H = 80.0, 120.0
_DRIER_OUTLINE = f'<path d="M 0 120 L 0 20 L 10 0 L 70 0 L 80 20 L 80 120 Z" {_OUTLINE}/>'

# Group-10 ports: feed and product on the walls, heating_in on the
# floor and vent on the top.
_DRIER_PORTS = {
    "feed": (0.0, 70.0), "product": (80.0, 70.0),
    "heating_in": (40.0, 120.0), "vent": (40.0, 0.0),
}


# One group-10 dryer: the shared casing plus its marks.
_drier = partial(_family, _DRIER_OUTLINE, _DRIER_W, _DRIER_H, _DRIER_PORTS, "drier_",
                 gravity_fixed=False)


# Item 10.2 X8083: three shelves.
_DRIER_SHELVES = "".join(
    f'<line x1="20" y1="{y:g}" x2="60" y2="{y:g}" {_INK}/>' for y in (30, 40, 50))

# Item 10.3 X8040: a rotating disc stack on a shaft.
_DRIER_TURBO = (
    '<path d="M 20 30 L 60 30 M 20 50 L 60 50 M 0 40 L 30 40 M 50 40 L 80 40 '
    f'M 40 50 L 40 0" {_INK}/>'
)

# Item 10.6 X8043: a belt between two rollers.
_DRIER_BELT = (
    f'<circle cx="17.5" cy="40" r="7.5" {_INK}/>'
    f'<circle cx="62.5" cy="40" r="7.5" {_INK}/>'
    f'<path d="M 17.5 32.5 L 62.5 32.5 M 17.5 47.5 L 62.5 47.5" {_INK}/>'
)


# ISO 10628-2 group-5 cooling tower outline, from item 5.1.
_TOWER_W, _TOWER_H = 80.0, 100.0
_TOWER_OUTLINE = (
    f'<path d="M 20 0 L 60 0 L 80 80 L 80 100 L 0 100 L 0 80 Z" {_OUTLINE}/>'
    f'<line x1="0" y1="80" x2="80" y2="80" {_INK}/>'
)

# CoolingTower ports: air out of the apex, water and air in at the
# basin's sides, and three bottom connections.
_TOWER_PORTS = {
    "air_out": (40.0, 0.0),
    "water_in": (0.0, 90.0), "air_in": (80.0, 90.0),
    "water_out": (40.0, 100.0), "makeup": (20.0, 100.0), "blowdown": (60.0, 100.0),
}

# Dry-fill mark (items 5.2-5.4 and 5.8): a ticked rule.
_TOWER_DRY = (
    f'<line x1="0" y1="90" x2="80" y2="90" {_INK}/>'
    + "".join(f'<line x1="{x:g}" y1="85" x2="{x:g}" y2="95" {_INK}/>' for x in range(10, 71, 10))
)

# Wet-fill mark (items 5.5-5.8): a distribution stub and arrow.
_TOWER_WET = f'<path d="M 10 40 L 40 40 M 30 50 L 40 40 L 50 50 M 40 40 L 40 50" {_INK}/>'

def _tower_fan(cy: float) -> str:
    """Return a 2 M fan with bow-tie blades.

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
        f'<circle cx="40" cy="{cy:g}" r="10" {_INK}/>'
        f'<path d="M 36 {cy - 9:g} L 31 {cy + 5:g} M 44 {cy - 9:g} L 49 {cy + 5:g}" {_INK}/>'
    )


_TOWER_FAN_FORCED = _tower_fan(65.0)
_TOWER_FAN_INDUCED = _tower_fan(15.0)


# ISO 10628-2 item 18.7 X8065, the bucket elevator. The home ports are
# on the walls at the chute heights; the item's own ticks are offered
# as N and S faces.
_BUCKET_ELEVATOR = Symbol(
    svg='<g id="sym_elevator">'
        f'<rect x="0" y="0" width="80" height="120" {_OUTLINE}/>'
        f'<path d="M 30 20 L 30 100 M 50 20 L 50 100" {_INK}/>'
        + _lift_pulley(40, 20) + _lift_pulley(40, 100)
        # Head chute east and boot chute west.
        + _lift_chute(50, 40, 2 * _LIFT_M, -2 * _LIFT_M)
        + _lift_chute(30, 80, -2 * _LIFT_M, 2 * _LIFT_M)
        + '</g>',
    width=80.0, height=120.0,
    ports={"feed": (0.0, 80.0), "discharge": (80.0, 40.0)},
    # Row 18.7's own ticks, offered as alternatives.
    port_faces={"feed": {"N": (10.0, 0.0)},
                "discharge": {"S": (70.0, 120.0)}},
    stretchable=False,
    gravity_fixed=True,
    iso_reg="X8065",
)

# ISO 10628-2 item 18.8 X8066, the Z-form bucket elevator. The ports
# are on the arms' end walls: in low at the west, out high at the east.
_Z_ELEVATOR = Symbol(
    svg='<g id="sym_elevator_z_form">'
        '<path d="M 0 120 L 0 80 L 80 80 L 80 0 L 200 0 L 200 40 '
        f'L 120 40 L 120 120 Z" {_OUTLINE}/>'
        '<path d="M 20 90 L 100 90 M 20 110 L 100 110 '
        'M 90 20 L 90 100 M 110 20 L 110 100 '
        f'M 100 10 L 180 10 M 100 30 L 180 30" {_INK}/>'
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


# ISO 10628-2 group 19: feeders, and item 19.5, the spray nozzle.

# The 4 M circle of items 19.1 C2056 and 19.2 X8067.
_FEEDER_CIRCLE = 40.0
_FEEDER_CIRCLE_PORTS = {"feed": (20.0, 0.0), "discharge": (20.0, 40.0), "drive": (40.0, 20.0)}


# A group-19 circle body: the shared rim plus its mark.
_feeder_circle = partial(_family, f'<circle cx="20" cy="20" r="20" {_OUTLINE}/>',
                         _FEEDER_CIRCLE, _FEEDER_CIRCLE, _FEEDER_CIRCLE_PORTS, "feeder_")


# Item 19.1 C2056: a Z in one stroke.
_FEEDER_Z = f'<path d="M 37.3 30 L 2.7 30 L 37.3 10 L 2.7 10" {_INK}/>'

# Item 19.2 X8067: a rotary valve rotor end-on, a hub and six spokes.
_FEEDER_HUB_R = 3.0
_FEEDER_ROTOR_MARK = f'<circle cx="20" cy="20" r="{_FEEDER_HUB_R:g}" {_INK}/>' + "".join(
    f'<line x1="{20.0 + _FEEDER_HUB_R * math.cos(math.radians(a)):g}" '
    f'y1="{20.0 + _FEEDER_HUB_R * math.sin(math.radians(a)):g}" '
    f'x2="{20.0 + 20.0 * math.cos(math.radians(a)):g}" '
    f'y2="{20.0 + 20.0 * math.sin(math.radians(a)):g}" {_INK}/>'
    for a in range(0, 360, 60))


# ISO item 19.3 C0074, the rotary table feeder: a table, a shaft and a
# rotation arrow.
_FEEDER_TABLE_W = 50.0
_FEEDER_TABLE_H = 60.0
_FEEDER_TABLE = (
    f'<line x1="0" y1="0" x2="50" y2="0" {_INK}/>'
    f'<line x1="25" y1="0" x2="25" y2="60" {_INK}/>'
    f'<ellipse cx="25" cy="37.5" rx="25" ry="12.5" {_INK}/>'
    # Rotation arrow up the east tangent.
    f'<line x1="50" y1="37.5" x2="50" y2="30.5" {_INK}/>'
    '<polygon points="50,27.5 47.3,30.5 52.7,30.5" fill="#111" stroke="none"/>'
)

# ISO item 19.4 C0035, the metering feeder: a beam with a pan at each
# end on a fulcrum.
_METER_W = 148.0
_METER_H = 33.0
_METER_BEAM_Y = 3.0
_METER_PAN_R = 22.0
_METER = (
    f'<line x1="0" y1="{_METER_BEAM_Y:g}" x2="{_METER_W:g}" y2="{_METER_BEAM_Y:g}" {_INK}/>'
    f'<path d="M 0 {_METER_BEAM_Y:g} A {_METER_PAN_R:g} {_METER_PAN_R:g} 0 0 1 '
    f'{2 * _METER_PAN_R:g} {_METER_BEAM_Y:g}" {_INK}/>'
    f'<path d="M {_METER_W - 2 * _METER_PAN_R:g} {_METER_BEAM_Y:g} '
    f'A {_METER_PAN_R:g} {_METER_PAN_R:g} 0 0 1 {_METER_W:g} {_METER_BEAM_Y:g}" {_INK}/>'
    f'<path d="M {_METER_W / 2:g} {_METER_BEAM_Y:g} L {_METER_W / 2 - 17:g} '
    f'{_METER_BEAM_Y + 30:g} L {_METER_W / 2 + 17:g} {_METER_BEAM_Y + 30:g} Z" {_INK}/>'
)

# ISO item 19.5 2037, the spray nozzle: three prongs under a header.
# The inlet is offered west and east.
_SPRAY_W = 40.0
_SPRAY_H = 20.0
_SPRAY_PORT_Y = 1.0
_SPRAY_NOZZLE = Symbol(
    svg='<g id="sym_spray_nozzle">'
        f'<line x1="0" y1="0" x2="{_SPRAY_W:g}" y2="0" {_INK}/>'
        f'<path d="M 20 0 L 0 20 M 20 0 L 20 20 M 20 0 L 40 20" {_INK}/></g>',
    width=_SPRAY_W, height=_SPRAY_H,
    ports={"inlet": (0.0, _SPRAY_PORT_Y)},
    port_faces={"inlet": {"E": (_SPRAY_W, _SPRAY_PORT_Y)}},
    iso_reg="2037",
)


# ISO 10628-2 items 20.6 to 20.8, the electric motor: a 4 M circle with
# an M in one stroke and, for AC or DC, a tilde or a bar under it.
_MOTOR_LETTER = (f"M {1.25 * M:g} {3 * M:g} L {1.25 * M:g} {M:g} L {2 * M:g} {2 * M:g} "
                 f"L {2.75 * M:g} {M:g} L {2.75 * M:g} {3 * M:g} ")
_MOTOR_TILDE = (f"M {M:g} {3.5 * M:g} A {0.75 * M:g} {0.75 * M:g} 0 0 1 {2 * M:g} {3.5 * M:g} "
                f"A {0.75 * M:g} {0.75 * M:g} 0 0 0 {3 * M:g} {3.5 * M:g}")
_MOTOR_BAR = f"M {M:g} {3.5 * M:g} L {3 * M:g} {3.5 * M:g}"
# The shaft leaves whichever side faces the machine.
_MOTOR_SHAFT = {"N": (2 * M, 0.0), "S": (2 * M, 4 * M), "E": (4 * M, 2 * M), "W": (0.0, 2 * M)}


def _motor(name: str, reg: str, mark: str = "") -> Symbol:
    """Return an electric motor, its shaft offered on every side.

    Parameters
    ----------
    name : str
        Variant name.
    reg : str
        ISO registration number.
    mark : str, default=""
        Path data for the supply mark under the letter.

    Returns
    -------
    Symbol
        A 4 M square symbol.
    """
    return Symbol(
        svg=f'<g id="sym_motor_{name}">'
            f'<circle cx="{2 * M:g}" cy="{2 * M:g}" r="{2 * M:g}" {_OUTLINE}/>'
            f'<path d="{_MOTOR_LETTER}{mark}" {_INK}/></g>',
        width=4 * M, height=4 * M,
        ports={"shaft": _MOTOR_SHAFT["S"]},
        port_faces={"shaft": dict(_MOTOR_SHAFT)},
        stretchable=False,
        iso_reg=reg,
    )


# ISO 10628-2 group 12: mixers and kneaders. Item 12.2 is the vendored
# fitting/static_mixer.

def _mix_element(x0: float) -> str:
    """Return one "N" mixing element of items 12.1-12.3.

    Parameters
    ----------
    x0 : float
        Left edge.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    return (
        f'<path d="M {x0:g} 5 L {x0:g} 25 M {x0:g} 5 L {x0 + 40:g} 55 '
        f'M {x0 + 40:g} 35 L {x0 + 40:g} 55" {_INK}/>'
    )


# ISO item 12.1 X2672, the in-line rotary mixer: two elements and a
# flow axis reaching a module past the west wall.
_MIXER_W = 130.0
_MIXER_H = 60.0
_MIXER_PORTS = {"inlet": (0.0, 30.0), "outlet": (_MIXER_W, 30.0)}
_ROTARY_MIXER = Symbol(
    svg='<g id="sym_fitting_rotary_mixer">'
        f'<path d="M 10 0 L 130 0 L 130 60 L 10 60 Z" {_OUTLINE}/>'
        f'<line x1="0" y1="30" x2="130" y2="30" {_INK}/>'
        + _mix_element(20.0) + _mix_element(70.0)
        + '</g>',
    width=_MIXER_W, height=_MIXER_H,
    ports=dict(_MIXER_PORTS),
    iso_reg="X2672",
    trim=True,
)

# ISO item 12.3 X8184, the mixing path: three elements in a box.
_PATH_W = 160.0
_PATH_H = 60.0
_MIXING_PATH = Symbol(
    svg='<g id="sym_fitting_mixing_path">'
        f'<path d="M 0 0 L 160 0 L 160 60 L 0 60 Z" {_OUTLINE}/>'
        + _mix_element(10.0) + _mix_element(60.0) + _mix_element(110.0)
        + '</g>',
    width=_PATH_W, height=_PATH_H,
    ports={"inlet": (0.0, 30.0), "outlet": (_PATH_W, 30.0)},
    iso_reg="X8184",
    trim=True,
)

# ISO item 12.4 X8134, the kneader: a casing crossed by one wave.
_KNEADER_W = 110.0
_KNEADER_H = 60.0
_KNEADER_PORTS = {"inlet": (0.0, 30.0), "outlet": (_KNEADER_W, 30.0)}
_KNEADER = Symbol(
    svg='<g id="sym_kneader">'
        f'<path d="M 10 0 L 110 0 L 110 60 L 10 60 Z" {_OUTLINE}/>'
        f'<path d="M 0 30 L 20 30 L 40 20 L 70 40 L 100 30 L 110 30" {_INK}/></g>',
    width=_KNEADER_W, height=_KNEADER_H,
    ports=dict(_KNEADER_PORTS),
    gravity_fixed=True,
    iso_reg="X8134",
)


# Fans. ISO 10628-2 item 17.1, X8164: a 6 M circle with two chords
# converging on the discharge and a three-bladed impeller at its centre.
_FAN_R = 3 * M


def _fan_chord(sign: int) -> str:
    """Return one chord of item 17.1, clipped to the circle.

    The chord runs through the grid points (-1.5 M, -2.5 M) and
    (2.5 M, -1.5 M) from the centre, mirrored below the axis.

    Parameters
    ----------
    sign : int
        ``-1`` for the chord above the axis, ``1`` for the one below.

    Returns
    -------
    str
        Path data for the chord.
    """
    (x0, y0), (dx, dy) = (-1.5 * M, sign * 2.5 * M), (4 * M, -sign * M)
    # Solve |P0 + t D| = R for the two ends.
    a, b, c = dx * dx + dy * dy, 2 * (x0 * dx + y0 * dy), x0 * x0 + y0 * y0 - _FAN_R ** 2
    ends = ((-b + k * math.sqrt(b * b - 4 * a * c)) / (2 * a) for k in (-1, 1))
    (ax, ay), (bx, by) = ((_FAN_R + x0 + t * dx, _FAN_R + y0 + t * dy) for t in ends)
    return f"M {ax:.4f} {ay:.4f} L {bx:.4f} {by:.4f} "


# Impeller: blades 2 M long, sides of radius 2 M; the two rear blades
# tip at (-1 M, -1.5 M) and (-1 M, 1.5 M) from the hub and share one
# inner arc through it.
_FAN_BLADE_R = 2 * M
_FAN_REAR_R = 1.625 * M
_FAN_GENERAL = Symbol(
    svg='<g id="sym_blower_general">'
        f'<circle cx="{_FAN_R:g}" cy="{_FAN_R:g}" r="{_FAN_R:g}" {_OUTLINE}/>'
        f'<path d="{_fan_chord(-1)}{_fan_chord(1)}'
        f'M {_FAN_R:g} {_FAN_R:g} '
        f'A {_FAN_BLADE_R:g} {_FAN_BLADE_R:g} 0 0 1 {_FAN_R + 2 * M:g} {_FAN_R:g} '
        f'A {_FAN_BLADE_R:g} {_FAN_BLADE_R:g} 0 0 1 {_FAN_R:g} {_FAN_R:g} '
        f'A {_FAN_BLADE_R:g} {_FAN_BLADE_R:g} 0 0 1 {_FAN_R - M:g} {_FAN_R - 1.5 * M:g} '
        f'M {_FAN_R:g} {_FAN_R:g} '
        f'A {_FAN_BLADE_R:g} {_FAN_BLADE_R:g} 0 0 0 {_FAN_R - M:g} {_FAN_R + 1.5 * M:g} '
        f'M {_FAN_R - M:g} {_FAN_R - 1.5 * M:g} '
        f'A {_FAN_REAR_R:g} {_FAN_REAR_R:g} 0 0 1 {_FAN_R - M:g} {_FAN_R + 1.5 * M:g}" '
        f'{_INK}/></g>',
    width=2 * _FAN_R, height=2 * _FAN_R,
    ports={"suction": (0.0, _FAN_R), "discharge": (2 * _FAN_R, _FAN_R), "drive": (_FAN_R, 0.0)},
    iso_reg="X8164",
)

# Centrifugal fan: a scroll round the eye, discharging east along its
# crown.
_SCROLL_R = 30.0
_SCROLL_EYE_R = 10.0
_SCROLL_OUTLET_W, _SCROLL_OUTLET_H = 40.0, 20.0
_SCROLL_W = _SCROLL_R + _SCROLL_OUTLET_W
_SCROLL_LIP_X = _SCROLL_R + math.sqrt(_SCROLL_R ** 2 - (_SCROLL_R - _SCROLL_OUTLET_H) ** 2)
_FAN_CENTRIFUGAL = Symbol(
    svg='<g id="sym_blower_centrifugal">'
        f'<path d="M {_SCROLL_R:g} 0 L {_SCROLL_W:g} 0 L {_SCROLL_W:g} {_SCROLL_OUTLET_H:g} '
        f'L {_SCROLL_LIP_X:.4f} {_SCROLL_OUTLET_H:g} '
        f'A {_SCROLL_R:g} {_SCROLL_R:g} 0 1 1 {_SCROLL_R:g} 0 Z" {_OUTLINE}/>'
        f'<circle cx="{_SCROLL_R:g}" cy="{_SCROLL_R:g}" r="{_SCROLL_EYE_R:g}" {_INK}/></g>',
    width=_SCROLL_W, height=2 * _SCROLL_R,
    ports={"suction": (0.0, _SCROLL_R), "discharge": (_SCROLL_W, _SCROLL_OUTLET_H / 2),
           "drive": (_SCROLL_R, 0.0)},
)

# Axial fan: a two-bladed propeller across a casing on the run.
_AXIAL_W, _AXIAL_H = 60.0, 40.0
_AXIAL_BLADE = 15.0
_AXIAL_BLADE_R = 12.0
_FAN_AXIAL = Symbol(
    svg='<g id="sym_blower_axial">'
        f'<rect x="0" y="0" width="{_AXIAL_W:g}" height="{_AXIAL_H:g}" {_OUTLINE}/>'
        '<path d="'
        + "".join(
            f"M {_AXIAL_W / 2:g} {_AXIAL_H / 2:g} "
            f"A {_AXIAL_BLADE_R:g} {_AXIAL_BLADE_R:g} 0 0 1 {_AXIAL_W / 2:g} {tip:g} "
            f"A {_AXIAL_BLADE_R:g} {_AXIAL_BLADE_R:g} 0 0 1 {_AXIAL_W / 2:g} {_AXIAL_H / 2:g} "
            for tip in (_AXIAL_H / 2 - _AXIAL_BLADE, _AXIAL_H / 2 + _AXIAL_BLADE))
        + f'" {_INK}/></g>',
    width=_AXIAL_W, height=_AXIAL_H,
    ports={"suction": (0.0, _AXIAL_H / 2), "discharge": (_AXIAL_W, _AXIAL_H / 2),
           "drive": (_AXIAL_W / 2, 0.0)},
)


# ISO 10628-2 item 24.15, registered 2181: the steam trap.

#: Steam trap body diameter.
TRAP_BODY_D = 40.0

#: Run drawn each side of the trap body.
TRAP_LEAD = 10.0

TRAP_W = TRAP_LEAD + TRAP_BODY_D + TRAP_LEAD
_TRAP_H = TRAP_BODY_D
_TRAP_R = TRAP_BODY_D / 2
_TRAP_CX = TRAP_LEAD + _TRAP_R
_TRAP_CY = _TRAP_H / 2

# Half the 45-degree diameter on each axis.
_TRAP_SEAT = _TRAP_R / math.sqrt(2)

# Ports on the horizontal diameter, at the ends of the leads.
_TRAP_PORTS = {"inlet": (0.0, _TRAP_CY), "outlet": (TRAP_W, _TRAP_CY)}

# Layer 1: the run into and out of the body.
_TRAP_RUN = (
    f'<path d="M 0 {_TRAP_CY:g} L {TRAP_LEAD:g} {_TRAP_CY:g} '
    f'M {TRAP_LEAD + TRAP_BODY_D:g} {_TRAP_CY:g} L {TRAP_W:g} {_TRAP_CY:g}" {_INK}/>'
)

# Layer 2: the body, filled white.
_TRAP_BODY = f'<circle cx="{_TRAP_CX:g}" cy="{_TRAP_CY:g}" r="{_TRAP_R:g}" {_OUTLINE}/>'

# Layer 3: the half below the diameter, filled, as two quarter arcs.
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
    stretchable=False,
    trim=True,
    iso_reg="2181",
)


# Primary flow elements drawn in a box on the run, the size of the
# vendored ones.

#: Side of a flow element's box.
FE_BOX = 25.0

_FE_FRAME = f'<rect x="0" y="0" width="{FE_BOX:g}" height="{FE_BOX:g}" {_OUTLINE}/>'
_FE_PORTS = {"inlet": (0.0, FE_BOX / 2), "outlet": (FE_BOX, FE_BOX / 2)}

#: Radius of one turn of a magnetic flowmeter's field coil.
MAG_TURN_R = 1.5

#: Turns in each field coil.
MAG_TURNS = 4

#: Field coil's inset from the box's top and bottom.
MAG_INSET = 4.0


def _field_coil(y: float, sweep: int) -> str:
    """Return a field coil centred across the box.

    Parameters
    ----------
    y : float
        Height of the coil's ends.
    sweep : int
        SVG arc sweep flag: 0 bulges the turns down, 1 up.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    x = FE_BOX / 2 - MAG_TURNS * MAG_TURN_R
    turns = "".join(
        f" A {MAG_TURN_R:g} {MAG_TURN_R:g} 0 0 {sweep} "
        f"{x + 2 * MAG_TURN_R * (k + 1):g} {y:g}"
        for k in range(MAG_TURNS))
    return f'<path d="M {x:g} {y:g}{turns}" {_INK}/>'


# ISO 15519-2 A.4.48, the magnetic flowmeter: a field coil above and
# below the run, each turned towards it.
_FE_MAGNETIC = Symbol(
    svg='<g id="sym_fitting_magnetic">' + _FE_FRAME
        + _field_coil(MAG_INSET, 0) + _field_coil(FE_BOX - MAG_INSET, 1) + '</g>',
    width=FE_BOX, height=FE_BOX,
    ports=dict(_FE_PORTS),
    trim=True,
)

#: Radii of the two wave arcs at each clamp-on transducer.
CLAMP_WAVE_R = (4.0, 7.0)

# The clamp-on meter's box, down to the run's ink under its bottom edge.
_CLAMP_H = FE_BOX + LineWeight.MAIN_FLOW.width / 2


def _transducer(cx: float, cy: float, start: "tuple[float, float]",
                end: "tuple[float, float]") -> str:
    """Return the wave arcs of one transducer, centred on a box corner.

    Parameters
    ----------
    cx, cy : float
        The corner.
    start, end : tuple[float, float]
        Unit directions from the corner to each arc's ends, taken
        counter-clockwise.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    d = "".join(
        f"M {cx + r * start[0]:g} {cy + r * start[1]:g} A {r:g} {r:g} 0 0 0 "
        f"{cx + r * end[0]:g} {cy + r * end[1]:g} "
        for r in CLAMP_WAVE_R)
    return f'<path d="{d.strip()}" {_INK}/>'


# ISO 15519-2 A.4.47, the clamp-on ultrasonic flowmeter: the box sits on
# the pipe, whose run passes along its bottom edge, with a transducer in
# two opposite corners.
_FE_CLAMP_ON = Symbol(
    svg='<g id="sym_fitting_ultrasonic_clamp_on">' + _FE_FRAME
        + _transducer(FE_BOX, 0.0, (-1.0, 0.0), (0.0, 1.0))
        + _transducer(0.0, FE_BOX, (1.0, 0.0), (0.0, -1.0)) + '</g>',
    width=FE_BOX, height=_CLAMP_H,
    ports={"inlet": (0.0, FE_BOX), "outlet": (FE_BOX, FE_BOX)},
    trim=True,
)

#: Where the two thermal probes stand across the box.
THERMAL_PROBE_X = (9.0, 16.0)

#: Length of a thermal probe's stem from the box's top.
THERMAL_STEM = 10.0

#: Radius of a thermal probe's sensing tip.
THERMAL_TIP_R = 2.0

# The thermal mass flowmeter: twin probes, heated and reference, hung
# into the run.
_FE_THERMAL_MASS = Symbol(
    svg='<g id="sym_fitting_thermal_mass">' + _FE_FRAME
        + "".join(
            f'<line x1="{x:g}" y1="0" x2="{x:g}" y2="{THERMAL_STEM:g}" {_INK}/>'
            f'<circle cx="{x:g}" cy="{THERMAL_STEM + THERMAL_TIP_R:g}" '
            f'r="{THERMAL_TIP_R:g}" {_INK}/>'
            for x in THERMAL_PROBE_X)
        + '</g>',
    width=FE_BOX, height=FE_BOX,
    ports=dict(_FE_PORTS),
    trim=True,
)

#: Width of a flume's open mouth at each end.
FLUME_MOUTH = 19.0

#: Width of a flume's throat.
FLUME_THROAT = 9.0

#: Length of the converging and diverging walls.
FLUME_TAPER = 10.0

#: Length of the throat.
FLUME_THROAT_L = 5.0

_FLUME_W = 2 * FLUME_TAPER + FLUME_THROAT_L
_FLUME_H = FLUME_MOUTH


def _flume_wall(y_mouth: float, y_throat: float) -> str:
    """Return one wall of a flume in plan.

    Parameters
    ----------
    y_mouth : float
        Height of the wall at both mouths.
    y_throat : float
        Height of the wall along the throat.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    return (f'<path d="M 0 {y_mouth:g} L {FLUME_TAPER:g} {y_throat:g} '
            f'L {FLUME_TAPER + FLUME_THROAT_L:g} {y_throat:g} '
            f'L {_FLUME_W:g} {y_mouth:g}" {_INK}/>')


# A flume in plan: the walls close in to a throat and open out again,
# and the run passes along its axis.
_FE_FLUME = Symbol(
    svg='<g id="sym_fitting_flume">'
        + _flume_wall(0.0, (FLUME_MOUTH - FLUME_THROAT) / 2)
        + _flume_wall(FLUME_MOUTH, (FLUME_MOUTH + FLUME_THROAT) / 2)
        + f'<line x1="0" y1="{_FLUME_H / 2:g}" x2="{_FLUME_W:g}" y2="{_FLUME_H / 2:g}" '
          f'{_INK}/></g>',
    width=_FLUME_W, height=_FLUME_H,
    ports={"inlet": (0.0, _FLUME_H / 2), "outlet": (_FLUME_W, _FLUME_H / 2)},
    trim=True,
)


# ISO 10628-2 group 7: screening devices, sieves and rakes.

# Group-7 outline, from item 7.1 (all items but 7.7).
_SCREEN_W, _SCREEN_H = 60.0, 90.0
_SCREEN_OUTLINE = f'<path d="M 0 0 L 60 0 L 60 60 L 30 90 L 0 60 Z" {_OUTLINE}/>'

# Group-7 ports, from item 7.1.
_SCREEN_PORTS = {"feed": (30.0, 0.0), "oversize": (60.0, 50.0), "undersize": (30.0, 90.0)}

# The dashed mesh diagonal: item 7.1 X8123's mark and the base of
# 7.2-7.5.
_SCREEN_MESH = f'<line x1="0" y1="0" x2="60" y2="60" {_INK} {_DASH_LONG}/>'


# A group-7 screen: the shared outline plus its mark.
_screen = partial(_family, _SCREEN_OUTLINE, _SCREEN_W, _SCREEN_H, _SCREEN_PORTS, "screen_")


def _rake_teeth(points: "tuple[float, ...]", half_len: float) -> str:
    """Return rake teeth across the mesh diagonal.

    Parameters
    ----------
    points : tuple[float, ...]
        Fractions along the diagonal.
    half_len : float
        Half the tooth length.

    Returns
    -------
    str
        SVG ``<line>`` elements.
    """
    out = []
    for t in points:
        x, y = 60 * t, 60 * t
        dx = dy = half_len * _SQ2
        out.append(f'<line x1="{x + dx:g}" y1="{y - dy:g}" x2="{x - dx:g}" '
                    f'y2="{y + dy:g}" {_INK}/>')
    return "".join(out)


def _screen_vibration() -> str:
    """Return item 7.5 X2605's vibration mark by the mesh diagonal.

    Returns
    -------
    str
        Two opposed arrows on tracks either side of the diagonal.
    """
    along = (_SQ2, _SQ2)
    across = (_SQ2, -_SQ2)

    def track(tail: "tuple[float, float]", tip: "tuple[float, float]") -> str:
        """Return one arrow from ``tail`` to ``tip``.

        Parameters
        ----------
        tail, tip : tuple[float, float]
            Ends of the arrow.

        Returns
        -------
        str
            SVG line and arrowhead.
        """
        base = (tip[0] - 6 * along[0], tip[1] - 6 * along[1])
        wing = 2.5
        left = (base[0] + wing * across[0], base[1] + wing * across[1])
        right = (base[0] - wing * across[0], base[1] - wing * across[1])
        return (
            f'<line x1="{tail[0]:g}" y1="{tail[1]:g}" x2="{base[0]:g}" '
            f'y2="{base[1]:g}" {_INK}/>'
            f'<polygon points="{tip[0]:g},{tip[1]:g} {left[0]:g},{left[1]:g} '
            f'{right[0]:g},{right[1]:g}" fill="#111" stroke="none"/>'
        )

    # Tracks 4 units either side of the midpoint (30, 30), 10 units
    # long, pointing away from each other.
    o1 = (30 + 4 * across[0], 30 + 4 * across[1])
    o2 = (30 - 4 * across[0], 30 - 4 * across[1])
    return (
        track((o1[0] - 5 * along[0], o1[1] - 5 * along[1]),
              (o1[0] + 5 * along[0], o1[1] + 5 * along[1]))
        + track((o2[0] + 5 * along[0], o2[1] + 5 * along[1]),
                 (o2[0] - 5 * along[0], o2[1] - 5 * along[1]))
    )


_SCREEN_VIBRATION = _screen_vibration()

# Item 7.6 X8029: the rotating drum, dashed.
_SCREEN_DRUM = f'<circle cx="30" cy="45" r="15" {_INK} {_DASH_LONG}/>'

# ISO item 7.7 X8030's outline, taller for the rollers.
_REEL_W, _REEL_H = 80.0, 160.0
_REEL_OUTLINE = f'<path d="M 0 0 L 80 0 L 80 120 L 40 160 L 0 120 Z" {_OUTLINE}/>'

# Item 7.7 is ported on the walls level with the top roller.
_REEL_PORTS = {"feed": (0.0, 20.0), "oversize": (_REEL_W, 20.0), "undersize": (40.0, 160.0)}

# Item 7.7 X8030: two rollers joined by dashed rails, the wire basket.
_REEL_MARK = (
    f'<circle cx="40" cy="20" r="10" {_INK}/>'
    f'<circle cx="40" cy="100" r="10" {_INK}/>'
    f'<line x1="30" y1="30" x2="30" y2="90" {_INK} {_DASH_LONG}/>'
    f'<line x1="50" y1="30" x2="50" y2="90" {_INK} {_DASH_LONG}/>'
)

_REEL_BODY = _family(_REEL_OUTLINE, _REEL_W, _REEL_H, _REEL_PORTS, "screen_", "basket_reel",
                     "X8030", _REEL_MARK)


# Evaporators and kilns: original drawings with no registration number.

# Evaporator body: dished head, straight side, dished bottom.
_EVAP_W = 80.0
_EVAP_HEAD = 12.0
_EVAP_SHELL = 136.0
_EVAP_H = 2 * _EVAP_HEAD + _EVAP_SHELL

_EVAP_OUTLINE = (
    f'<path d="M 0 {_EVAP_HEAD:g} '
    f'A {_EVAP_W / 2:g} {_EVAP_HEAD:g} 0 0 1 {_EVAP_W:g} {_EVAP_HEAD:g} '
    f'L {_EVAP_W:g} {_EVAP_HEAD + _EVAP_SHELL:g} '
    f'A {_EVAP_W / 2:g} {_EVAP_HEAD:g} 0 0 1 0 {_EVAP_HEAD + _EVAP_SHELL:g} Z" {_OUTLINE}/>'
)

# Long-tube heating band (falling film, climbing film and general).
_EVAP_TUBE_TOP, _EVAP_TUBE_BOT = 60.0, 130.0

# Short-tube (calandria) band, centred on the long band.
_EVAP_CALANDRIA_TOP, _EVAP_CALANDRIA_BOT = 79.0, 111.0

# Steam-chest ports sit this far inside their tubesheet. Steam enters
# west and condensate leaves east.
_EVAP_STEAM_INSET = 6.0

# Feed height above the element (falling film) and below it
# (climbing film).
_EVAP_FEED_HIGH, _EVAP_FEED_LOW = 30.0, 140.0


def _evap_tubesheets(top: float, bot: float) -> str:
    """Return the two tubesheets, wall to wall.

    Parameters
    ----------
    top, bot : float
        Tubesheet heights.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    return (f'<path d="M 0 {top:g} L {_EVAP_W:g} {top:g} '
            f'M 0 {bot:g} L {_EVAP_W:g} {bot:g}" {_DETAIL}/>')


def _evap_tubes(top: float, bot: float, xs: "tuple[float, ...]") -> str:
    """Return tubes between the tubesheets.

    Parameters
    ----------
    top, bot : float
        Tubesheet heights.
    xs : tuple[float, ...]
        Tube positions.

    Returns
    -------
    str
        SVG ``<path>``.
    """
    return ('<path d="'
            + " ".join(f"M {x:g} {top:g} L {x:g} {bot:g}" for x in xs)
            + f'" {_DETAIL}/>')


# The general element: a closed box inset from the walls.
_EVAP_ELEMENT_INSET = 12.0
_EVAP_ELEMENT = (
    f'<rect x="{_EVAP_ELEMENT_INSET:g}" y="{_EVAP_TUBE_TOP:g}" '
    f'width="{_EVAP_W - 2 * _EVAP_ELEMENT_INSET:g}" '
    f'height="{_EVAP_TUBE_BOT - _EVAP_TUBE_TOP:g}" {_DETAIL}/>'
)


# Long-tube rows: five tubes on a 12-unit pitch, centred.
_EVAP_TUBE_XS = (16.0, 28.0, 40.0, 52.0, 64.0)

# Calandria: three tubes either side of a central downcomer, drawn as
# two walls.
_EVAP_CALANDRIA_XS = (8.0, 16.0, 24.0, 56.0, 64.0, 72.0)
_EVAP_DOWNCOMER_XS = (32.0, 48.0)

# Falling-film distributor: a tray above the top tubesheet with three
# drops.
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

# Plate row: nine plates wall to wall, with no tubesheets.
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

    Parameters
    ----------
    name : str
        Variant, used in the SVG id.
    *detail : str
        Element marks.
    band : tuple[float, float], optional
        Element's top and bottom; the long-tube band by default.
    feed_y : float, optional
        Feed height on the west wall; above the element by default.

    Returns
    -------
    Symbol
        Evaporator symbol.
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
        # The straight shell, held 10 off each head.
        bands={face: (_EVAP_HEAD + 10, _EVAP_HEAD + _EVAP_SHELL - 10) for face in ("W", "E")},
        gravity_fixed=True,
    )


# Draft-tube baffle crystallizer: dished head, straight shell, cone and
# elutriation leg.
CRYST_W = 90.0
_CRYST_HEAD = 12.0
_CRYST_SHELL = 110.0
_CRYST_CONE = 35.0
_CRYST_LEG_W, _CRYST_LEG_H = 20.0, 15.0
CRYST_H = _CRYST_HEAD + _CRYST_SHELL + _CRYST_CONE + _CRYST_LEG_H

_CRYST_OUTLINE = (
    f'<path d="M 0 {_CRYST_HEAD:g} '
    f'A {CRYST_W / 2:g} {_CRYST_HEAD:g} 0 0 1 {CRYST_W:g} {_CRYST_HEAD:g} '
    f'L {CRYST_W:g} {_CRYST_HEAD + _CRYST_SHELL:g} '
    f'L {(CRYST_W + _CRYST_LEG_W) / 2:g} {CRYST_H - _CRYST_LEG_H:g} '
    f'L {(CRYST_W + _CRYST_LEG_W) / 2:g} {CRYST_H:g} '
    f'L {(CRYST_W - _CRYST_LEG_W) / 2:g} {CRYST_H:g} '
    f'L {(CRYST_W - _CRYST_LEG_W) / 2:g} {CRYST_H - _CRYST_LEG_H:g} '
    f'L 0 {_CRYST_HEAD + _CRYST_SHELL:g} Z" {_OUTLINE}/>'
)

# Draft tube: width, top and bottom.
_CRYST_TUBE_W = 36.0
_CRYST_TUBE_TOP, _CRYST_TUBE_BOT = 40.0, 120.0

# Baffle skirt: inset from the shell, from its top down to the cone.
_CRYST_BAFFLE_INSET = 10.0
_CRYST_BAFFLE_TOP = 70.0

_CRYST_INTERNALS = (
    '<path d="'
    + " ".join(
        f"M {x:g} {_CRYST_TUBE_TOP:g} L {x:g} {_CRYST_TUBE_BOT:g}"
        for x in ((CRYST_W - _CRYST_TUBE_W) / 2, (CRYST_W + _CRYST_TUBE_W) / 2))
    + " "
    + " ".join(
        f"M {x:g} {_CRYST_BAFFLE_TOP:g} L {x:g} {_CRYST_HEAD + _CRYST_SHELL:g}"
        for x in (_CRYST_BAFFLE_INSET, CRYST_W - _CRYST_BAFFLE_INSET))
    + f'" {_DETAIL}/>'
)

#: Agitator in the draft tube: width, and the depth of its foot.
CRYST_AGITATOR_W, CRYST_AGITATOR_FOOT = 28.0, 115.0

# Vapour nozzle on the head, this far east of the shaft.
_CRYST_VAPOR_DX = 22.5

# Feed above the baffle, overflow from the settling zone behind it,
# product from the leg.
_CRYST_PORTS = {
    "feed": (0.0, 50.0),
    "vapor": (CRYST_W / 2 + _CRYST_VAPOR_DX,
              round(_CRYST_HEAD * (1 - math.sqrt(1 - (2 * _CRYST_VAPOR_DX / CRYST_W) ** 2)), 4)),
    "overflow": (CRYST_W, 96.0),
    "product": (CRYST_W / 2, CRYST_H),
}


# Flotation cell: an open tank whose east wall is the froth lip, with
# the launder hung outside it.
FLOT_TANK_W = 100.0
_FLOT_TANK_H = 80.0
_FLOT_LAUNDER_W = 20.0
# The launder's outer wall stands this far above the lip.
_FLOT_LAUNDER_RISE = 10.0
_FLOT_LAUNDER_DEPTH = 25.0
FLOT_W = FLOT_TANK_W + _FLOT_LAUNDER_W
FLOT_H = _FLOT_LAUNDER_RISE + _FLOT_TANK_H
_FLOT_LIP = _FLOT_LAUNDER_RISE
_FLOT_LAUNDER_FLOOR = _FLOT_LIP + _FLOT_LAUNDER_DEPTH

_FLOT_OUTLINE = (
    f'<path d="M 0 {_FLOT_LIP:g} L 0 {FLOT_H:g} L {FLOT_TANK_W:g} {FLOT_H:g} '
    f'L {FLOT_TANK_W:g} {_FLOT_LIP:g} '
    f'M {FLOT_TANK_W:g} {_FLOT_LAUNDER_FLOOR:g} L {FLOT_W:g} {_FLOT_LAUNDER_FLOOR:g} '
    f'L {FLOT_W:g} 0" {_INK}/>'
)

# Air standpipe beside the shaft, from the top to above the impeller.
_FLOT_AIR_X = 60.0
_FLOT_AIR_FOOT = 50.0
_FLOT_AIR = (
    f'<line x1="{_FLOT_AIR_X:g}" y1="0" x2="{_FLOT_AIR_X:g}" '
    f'y2="{_FLOT_AIR_FOOT:g}" {_DETAIL}/>'
)

# Froth: bubbles between the standpipe and the lip.
_FLOT_BUBBLE_R = 2.5
_FLOT_BUBBLES = "".join(
    f'<circle cx="{x:g}" cy="{y:g}" r="{_FLOT_BUBBLE_R:g}" {_DETAIL}/>'
    for x, y in ((70.0, 17.0), (78.0, 13.0), (80.0, 22.0), (88.0, 16.0), (94.0, 23.0)))

#: Agitator on the tank's centre line: width, and the depth of its foot.
FLOT_AGITATOR_W, FLOT_AGITATOR_FOOT = 24.0, 75.0

# Feed through the west wall, froth out of the launder, tailings out of
# the floor and air down the standpipe.
_FLOT_PORTS = {
    "feed": (0.0, 45.0),
    "concentrate": (FLOT_W, 30.0),
    "tailings": (80.0, FLOT_H),
    "air": (_FLOT_AIR_X, 0.0),
}


# ISO 10628-2 items 1.8 and 1.9: walls 6 M apart and 6 M deep over a
# 3 M cone, fed through the west wall a module below the rim and
# emptied at the apex. Item 1.9 closes the top; item 1.8 leaves it open.
_BIN_PORTS = {"feed": (0.0, M), "discharge": (3 * M, 9 * M)}
_BIN_WALLS = f"M 0 0 L 0 {6 * M:g} L {3 * M:g} {9 * M:g} L {6 * M:g} {6 * M:g} L {6 * M:g} 0"

# Item 1.9, X2062, closed tank with conical bottom, vented at the
# middle of its roof.
_SILO = Symbol(
    svg=f'<g id="sym_silo"><path d="{_BIN_WALLS} Z" {_OUTLINE}/></g>',
    width=6 * M, height=9 * M,
    ports={**_BIN_PORTS, "vent": (3 * M, 0.0)},
    gravity_fixed=True,
    iso_reg="X2062",
)

# Item 1.8, 2064, bunker with conical bottom.
_BUNKER = Symbol(
    svg=f'<g id="sym_silo_bunker"><path d="{_BIN_WALLS}" {_INK}/></g>',
    width=6 * M, height=9 * M,
    ports=dict(_BIN_PORTS),
    gravity_fixed=True,
    iso_reg="2064",
)


# Mixer-settler: a closed box whose west compartment is the mixer. The
# dispersion overflows the partition into the settler, and the light
# phase overflows the weir into the launder at the east end.
MS_W, MS_H = 140.0, 50.0
#: Mixer partition: position, and the gap it leaves under the lid.
MS_MIXER_W, _MS_OVERFLOW = 40.0, 12.0
# Light-phase weir: position, and its height off the floor.
_MS_WEIR_X, _MS_WEIR_H = 120.0, 30.0
_MIXER_SETTLER = Symbol(
    svg='<g id="sym_mixer_settler">'
        f'<rect x="0" y="0" width="{MS_W:g}" height="{MS_H:g}" {_OUTLINE}/>'
        f'<path d="M {MS_MIXER_W:g} {_MS_OVERFLOW:g} L {MS_MIXER_W:g} {MS_H:g} '
        f'M {_MS_WEIR_X:g} {MS_H - _MS_WEIR_H:g} L {_MS_WEIR_X:g} {MS_H:g}" {_INK}/></g>',
    width=MS_W, height=MS_H,
    # Both phases into the mixer; the heavy phase out of the settler's
    # floor, the light phase out of the launder.
    ports={"light_in": (0.0, 15.0), "heavy_in": (0.0, 35.0),
           "light_out": (MS_W, 40.0), "heavy_out": (100.0, MS_H)},
    gravity_fixed=True,
)

#: Agitator on the mixer's centre line: width, and the depth of its foot.
MS_AGITATOR_W, MS_AGITATOR_FOOT = 24.0, 42.0


# Deaerator: a horizontal storage drum with dished ends, and the
# deaerating column standing on its crown towards the west end.
_DA_DRUM_W, _DA_DRUM_H = 160.0, 50.0
_DA_DRUM_END = 12.0
_DA_COLUMN_X, _DA_COLUMN_W = 30.0, 40.0
_DA_COLUMN_H = 60.0
_DA_CROWN = 8.0
_DA_H = _DA_COLUMN_H + _DA_DRUM_H
_DA_FEED_DX = -16.0


def _da_crown_y(dx: float) -> float:
    """Return the column crown's height a distance off its centre line.

    Parameters
    ----------
    dx : float
        Distance from the column's centre line.

    Returns
    -------
    float
        Height of the crown, rounded to four places.
    """
    return round(_DA_CROWN * (1 - math.sqrt(1 - (2 * dx / _DA_COLUMN_W) ** 2)), 4)


_DEAERATOR = Symbol(
    svg='<g id="sym_deaerator">'
        f'<path d="M {_DA_DRUM_END:g} {_DA_COLUMN_H:g} L {_DA_DRUM_W - _DA_DRUM_END:g} {_DA_COLUMN_H:g} '
        f'A {_DA_DRUM_END:g} {_DA_DRUM_H / 2:g} 0 0 1 {_DA_DRUM_W - _DA_DRUM_END:g} {_DA_H:g} '
        f'L {_DA_DRUM_END:g} {_DA_H:g} '
        f'A {_DA_DRUM_END:g} {_DA_DRUM_H / 2:g} 0 0 1 {_DA_DRUM_END:g} {_DA_COLUMN_H:g} Z" {_OUTLINE}/>'
        f'<path d="M {_DA_COLUMN_X:g} {_DA_COLUMN_H:g} L {_DA_COLUMN_X:g} {_DA_CROWN:g} '
        f'A {_DA_COLUMN_W / 2:g} {_DA_CROWN:g} 0 0 1 {_DA_COLUMN_X + _DA_COLUMN_W:g} {_DA_CROWN:g} '
        f'L {_DA_COLUMN_X + _DA_COLUMN_W:g} {_DA_COLUMN_H:g}" {_OUTLINE}/></g>',
    width=_DA_DRUM_W, height=_DA_H,
    # Water and vent through the column's crown, steam into the drum's
    # west end, deaerated water out of the drum's floor.
    ports={
        "feed": (_DA_COLUMN_X + _DA_COLUMN_W / 2 + _DA_FEED_DX, _da_crown_y(_DA_FEED_DX)),
        "vent": (_DA_COLUMN_X + _DA_COLUMN_W / 2, 0.0),
        "steam": (0.0, _DA_COLUMN_H + _DA_DRUM_H / 2),
        "outlet": (120.0, _DA_H),
    },
    gravity_fixed=True,
)


# Rotary kiln shell: 26 units of fall over 180 of length.
_KILN_W = 180.0
_KILN_BORE = 28.0
_KILN_FALL = 26.0
_KILN_H = _KILN_BORE + _KILN_FALL


def _kiln_top(x: float) -> float:
    """Return the shell's upper wall height at ``x``.

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

# Girth gear and pinion: a block under the shell between the rings.
_KILN_DRIVE_X, _KILN_DRIVE_W, _KILN_DRIVE_H = 95.0, 18.0, 7.0
_KILN_DRIVE = (
    f'<rect x="{_KILN_DRIVE_X - _KILN_DRIVE_W / 2:g}" '
    f'y="{_kiln_top(_KILN_DRIVE_X) + _KILN_BORE:g}" '
    f'width="{_KILN_DRIVE_W:g}" height="{_KILN_DRIVE_H:g}" {_DETAIL}/>'
)

# Solids in at the high end and out at the low end; offgas at the feed
# end; fuel and air into the hood at the discharge end.
_KILN_PORTS = {
    "feed": (0.0, _KILN_BORE / 2),
    "product": (_KILN_W, _KILN_FALL + _KILN_BORE / 2),
    "offgas": (24.0, _kiln_top(24.0)),
    "air": (140.0, _kiln_top(140.0) + _KILN_BORE),
    "fuel": (160.0, _kiln_top(160.0) + _KILN_BORE),
}

# Fluidised-bed calciner: dished crown, straight freeboard and a
# windbox cone, with a dashed distributor grid where they meet.
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
    f'{_DETAIL} {_DASH_LONG}/>'
)

# Feed high, product low over a weir, offgas off the crown, fuel into
# the bed and air into the windbox.
_FBC_PORTS = {
    "feed": (0.0, 40.0),
    "product": (_FBC_W, 100.0),
    "offgas": (_FBC_W / 2, 0.0),
    "fuel": (0.0, 96.0),
    "air": (_FBC_W / 2, _FBC_H),
}

# Shaft kiln: charging mouth, shaft and discharge cone. The two zone
# lines bound the calcining zone.
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

# Charged over the mouth and discharged from the cone; offgas above
# the calcining zone, fuel at its top and cooling air below it.
_SHAFT_PORTS = {
    "feed": (_SHAFT_W / 2, 0.0),
    "product": (_SHAFT_W / 2, _SHAFT_H),
    "offgas": (0.0, 36.0),
    "fuel": (_SHAFT_W, _SHAFT_ZONE_TOP + 12.0),
    "air": (0.0, _SHAFT_ZONE_BOT + 14.0),
}


class SymbolRegistry:
    """Catalogue of symbols keyed by ``(kind, variant)``, and ISO parts.

    :meth:`for_unit` resolves the drawing for a unit, including drawings
    derived from it, each cached.
    """

    def __init__(self):
        """Create the registry and register the default symbols."""
        self._symbols: dict[tuple[str, str], Symbol] = {}
        # Caches of derived symbols.
        self._darkened: dict[tuple[str, str], Symbol] = {}
        # Closed-state drawings.
        self._closed: dict[tuple[str, str], Symbol] = {}
        # Fittings turned end for end (expanders).
        self._expanders: dict[tuple[str, str], Symbol] = {}
        # ISO 10628-2 group 26-29 supplementary symbols, keyed by
        # (group, name).
        self._parts: dict[tuple[int, str], OverlayPart] = {}
        # Bodies with parts, per (kind, variant, overlays).
        self._composed: dict[tuple, Symbol] = {}
        self._register_defaults()

    def register(self, kind: str, template: Symbol, variant: str = "default") -> None:
        """Register a drawing for ``(kind, variant)``.

        Replaces any earlier drawing and drops the drawings derived from
        it, closed state included.

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
        for cached in (vessel_symbol, vessel_room, _vessel_base):
            cached.cache_clear()

    def register_part(self, part: OverlayPart) -> None:
        """Register one ISO 10628-2 group 26-29 supplementary symbol.

        Parameters
        ----------
        part : OverlayPart
            Part to register, keyed by ``(group, name)``.
        """
        self._parts[part.key()] = part
        # Drop every composition; any may use this part.
        self._composed.clear()
        for cached in (vessel_symbol, vessel_room, _vessel_base):
            cached.cache_clear()

    def part(self, group: int, name: str) -> OverlayPart:
        """Return the part registered as ``(group, name)``.

        Parameters
        ----------
        group : int
            ISO 10628-2 subject group: 26 to 29, or 20 for the motor.
        name : str
            Registered part name.

        Returns
        -------
        OverlayPart
            The part.

        Raises
        ------
        ValueError
            If no part is registered under ``(group, name)``.
        """
        if (group, name) in self._parts:
            return self._parts[(group, name)]
        known = self.part_names(group)
        suggestion = suggest(name, known)
        raise ValueError(
            f"ISO 10628-2 group {group} has no part {name!r}{suggestion}; registered "
            f"group {group} parts: {', '.join(known) or '(none)'}"
        )

    def part_names(self, group: int) -> list[str]:
        """Return the sorted part names registered in ``group``.

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
        """Return every registered part, by group then name.

        Returns
        -------
        list[OverlayPart]
            Registered parts.
        """
        return [self._parts[key] for key in sorted(self._parts)]

    def composed(self, kind: str, variant: str = "default",
                 overlays: "tuple[Overlay, ...]" = (),
                 ports: "tuple[tuple[str, tuple[float, float]], ...]" = ()
                 ) -> Symbol:
        """Return ``(kind, variant)`` with ``overlays`` drawn on it.

        Compositions are cached. With no overlays and no ports the body
        is returned.

        Parameters
        ----------
        kind : str
            Unit kind.
        variant : str, default="default"
            Registered variant name.
        overlays : tuple[Overlay, ...], default=()
            Parts to draw, each registered with :meth:`register_part`.
        ports : tuple[tuple[str, tuple[float, float]], ...], default=()
            ``(name, point)`` nozzles to add to the body, in body
            coordinates.

        Returns
        -------
        Symbol
            Composed drawing.

        Raises
        ------
        ValueError
            If ``kind`` is registered without ``variant``.
        ValueError
            If a part is unregistered or cannot be composed.
        """
        if not overlays and not ports:
            return self.get(kind, variant)
        key = (kind, variant, tuple(overlays), tuple(ports))
        if key not in self._composed:
            body = self.get(kind, variant)
            if ports:
                body = replace(body, ports={**body.ports, **dict(ports)})
            self._composed[key] = compose(
                body,
                [(overlay, self.part(overlay.group, overlay.name))
                 for overlay in overlays],
            )
        return self._composed[key]

    def register_closed(self, kind: str, template: Symbol, variant: str = "default") -> None:
        """Register the normally closed drawing of ``(kind, variant)``.

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
        """Return the closed drawing of ``(kind, variant)``, if any.

        Parameters
        ----------
        kind : str
            Unit kind.
        variant : str, default="default"
            Variant name.

        Returns
        -------
        Symbol or None
            Closed-state drawing, or ``None``.
        """
        return self._closed.get((kind, variant))

    def closed_variants(self, kind: str) -> list[str]:
        """Return the sorted ``kind`` variants with a closed drawing.

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

        Starts from :meth:`get`, then uses, in order, a symbol built
        to the unit's size, the body with its parts, a normally closed
        drawing, or a reducer turned end for end.

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
            If the unit's kind is registered without its variant.
        ValueError
            If a derived drawing is refused.
        """
        variant = getattr(unit, "variant", "default")
        sym = self.get(unit.kind, variant)
        build = (_BUILT_TO_SIZE.get((unit.kind, variant))
                 or _BUILT_TO_SIZE.get((unit.kind, None)))
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

        A kind with no drawings gets a blank 60 x 60 box.

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
            If the kind has drawings but none under ``variant``.
        """
        if (kind, variant) in self._symbols:
            return self._symbols[(kind, variant)]
        known = self.variants(kind)
        if not known:
            return self._generic_symbol()
        suggestion = suggest(variant, known)
        raise ValueError(
            f"{kind} has no variant {variant!r}{suggestion}; "
            f"registered {kind} variants: {', '.join(known)}"
        )

    def _generic_symbol(self) -> Symbol:
        """Return the blank 60 x 60 box for an unregistered kind.

        Returns
        -------
        Symbol
            Generic box symbol.
        """
        svg = (
            '<g id="sym_generic">'
            '<rect x="0" y="0" width="60" height="60" fill="none" stroke="black" stroke-width="2" />'
            '</g>'
        )
        return Symbol(svg=svg, width=60, height=60)

    def _register_defaults(self):
        """Register the hand-drawn, vendored and ISO symbols."""
        # Fallbacks for Feed and Product, which the renderer draws.
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

        # Mixer: a triangle pointing right.
        self.register("mixer", junction_symbol("mixer"))

        # Belt and screw conveyors at their default length.
        self.register("conveyor", conveyor_symbol())
        self.register("conveyor", screw_conveyor_symbol(), "screw")

        # Bucket elevators, at a fixed size.
        self.register("elevator", _BUCKET_ELEVATOR)
        self.register("elevator", _Z_ELEVATOR, "z_form")

        # Pipe tee: the run crosses at mid-height and the branch drops
        # to the south face.
        self.register("tee", Symbol(
            svg='<g id="sym_tee">'
                '<path d="M 0 6 L 12 6 M 6 6 L 6 12" fill="none" stroke="black" '
                'stroke-width="2"/>'
                '</g>',
            width=12.0, height=12.0,
            ports={"inlet": (0.0, 6.0), "outlet": (12.0, 6.0), "branch": (6.0, 12.0)},
            # The tee carries no tag.
            label_pos="center",
            bare_run=True,
        ))

        # Block box with one inlet west and one outlet east.
        self.register("block", block_symbol((("in_1", "W"), ("out_1", "E"))))

        # Splitter: a triangle pointing left.
        self.register("splitter", junction_symbol("splitter"))

        # ISA-5.1 instrument balloons, lettered by the renderer. Every
        # port offers all four faces.
        _inst_faces = {"N": (22.0, 0.0), "S": (22.0, 44.0),
                       "W": (0.0, 22.0), "E": (44.0, 22.0)}
        _inst_ports = {'pv': (22.0, 44.0), 'sig_in': (0.0, 22.0), 'sig_out': (44.0, 22.0)}
        # The face menus overlap (faceless_ports).
        _inst_menu = {name: dict(_inst_faces) for name in _inst_ports}
        _inst_faceless = frozenset(_inst_ports)
        # A 64-gon traces the circle.
        _inst_rim = tuple((22.0 + 21.0 * math.cos(math.pi * k / 32),
                           22.0 + 21.0 * math.sin(math.pi * k / 32)) for k in range(64))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, rim=_inst_rim, label_pos="center",
            stretchable=False, trim=True))
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_panel"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="22" x2="43" y2="22" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, rim=_inst_rim, label_pos="center",
            stretchable=False, trim=True), "panel")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_aux"><circle cx="22" cy="22" r="21" fill="white" stroke="black" stroke-width="2"/><line x1="1" y1="19" x2="43" y2="19" stroke="black" stroke-width="2"/><line x1="1" y1="25" x2="43" y2="25" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, rim=_inst_rim, label_pos="center",
            stretchable=False, trim=True), "aux")
        # Shared display: a circle in a square with one bar
        # (ISO 15519-2 Table 1).
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_shared"><rect x="1" y="1" width="42" height="42" fill="white" stroke="black" stroke-width="2"/><circle cx="22" cy="22" r="20" fill="none" stroke="black" stroke-width="2"/><line x1="2" y1="22" x2="42" y2="22" stroke="black" stroke-width="2"/></g>',
            width=44.0, height=44.0, ports=_inst_ports, port_faces=_inst_menu,
            faceless_ports=_inst_faceless, label_pos="center", stretchable=False,
            trim=True), "shared")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_computer"><polygon points="11,3 33,3 43,22 33,41 11,41 1,22" fill="white" stroke="black" stroke-width="2"/></g>',
            # pv sits 1 unit below the hexagon's flat bottom.
            width=44.0, height=44.0, label_pos="center", stretchable=False,
            faceless_ports=_inst_faceless,
            ports={**_inst_ports, "pv": (22.0, 42.0)},
            # N and S stubs on the flat top and bottom.
            port_faces={n: {**_inst_faces, "N": (22.0, 2.0), "S": (22.0, 42.0)}
                        for n in _inst_ports},
            rim=((11.0, 3.0), (33.0, 3.0), (43.0, 22.0), (33.0, 41.0), (11.0, 41.0),
                 (1.0, 22.0)),
            trim=True), "computer")
        # ISA-5.1 trip and logic symbols. Ports sit on the diamond's
        # vertices.
        _logic_ports = {'pv': (20.0, 39.0), 'sig_in': (1.0, 20.0), 'sig_out': (39.0, 20.0)}
        # One Symbol under two names.
        _sis = Symbol(
            svg='<g id="sym_instrument_sis">'
                '<rect x="1" y="1" width="38" height="38" fill="white" stroke="black" stroke-width="2"/>'
                '<polygon points="20,1 39,20 20,39 1,20" fill="none" stroke="black" stroke-width="2"/>'
                '</g>',
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports, trim=True)
        self.register("instrument", _sis, "sis")
        self.register("instrument", _sis, "logic")
        self.register("instrument", Symbol(
            svg='<g id="sym_instrument_interlock">'
                '<polygon points="20,1 39,20 20,39 1,20" fill="white" stroke="black" stroke-width="2"/>'
                '</g>',
            width=40.0, height=40.0, label_pos="center", stretchable=False,
            ports=_logic_ports, rim=((20.0, 1.0), (39.0, 20.0), (20.0, 39.0), (1.0, 20.0)),
            trim=True),
            "interlock")

        # Tubular reactor: a rectangular shell with a serpentine tube. The
        # shell is 64 tall, so three feeds fit 16 apart in half its W face.
        self.register("reactor", Symbol(
            svg='<g id="sym_reactor_tubular">'
                f'<rect x="0" y="0" width="120" height="64" {_OUTLINE}/>'
                '<path d="M 15 16 L 105 16 A 8 8 0 0 1 105 32 L 15 32 '
                f'A 8 8 0 0 0 15 48 L 105 48" {_DETAIL}/></g>',
            width=120.0, height=64.0,
            ports={"outlet": (120.0, 32.0), "duty": (60.0, 0.0)},
            port_series=(PortSeries(prefix="feed_", face="W", pitch=MIN_NOZZLE_PITCH,
                                    extent=0.5, at=32.0, singular="feed"),),
        ), "tubular")

        # ISO 10628-2 group 4: boiler, furnace, combustion chamber,
        # stack and flare.

        # Item 4.1, 2532, boiler with dome.
        self.register("boiler", Symbol(
            svg='<g id="sym_boiler"><path d="M 25 25 A 25 25 0 0 1 75 25 '
                f'L 100 25 L 100 125 L 0 125 L 0 25 Z" {_OUTLINE}/></g>',
            width=100.0, height=125.0,
            ports={"feedwater": (0.0, 50.0), "steam": (50.0, 0.0)},
            gravity_fixed=True,
            iso_reg="2532",
        ), "default")

        # Item 4.3, 2533, furnace: a closed top over a U-shaped lining,
        # chamfered at the floor.
        self.register("furnace", Symbol(
            svg='<g id="sym_furnace_general">'
                f'<path d="M 0 0 L 80 0 L 80 60 L 60 80 L 20 80 L 0 60 Z" {_OUTLINE}/>'
                f'<path d="M 15 0 L 15 55 L 25 65 L 55 65 L 65 55 L 65 0" {_INK}/></g>',
            width=80.0, height=80.0,
            ports={"inlet": (0.0, 40.0), "outlet": (80.0, 40.0), "fuel": (40.0, 80.0)},
            iso_reg="2533",
        ), "general")

        # Item 4.5, X8106, combustion chamber: a burner's flame on its
        # plate inside the chamber. Air from the west, fuel from below,
        # hot gas out of the top.
        self.register("furnace", Symbol(
            svg='<g id="sym_furnace_combustion_chamber">'
                f'<rect x="0" y="0" width="100" height="80" {_OUTLINE}/>'
                '<path d="M 0 70 L 100 70 M 20 70 L 50 20 L 80 70 '
                f'M 35 70 L 50 45 L 65 70" {_INK}/></g>',
            width=100.0, height=80.0,
            ports={"inlet": (0.0, 40.0), "outlet": (50.0, 0.0), "fuel": (50.0, 80.0)},
            iso_reg="X8106",
        ), "combustion_chamber")

        # Item 4.7, 2041, stack: a tapering shaft on a flange.
        self.register("stack", Symbol(
            svg='<g id="sym_stack"><path d="M 20 0 L 40 0 M 20 0 L 10 100 '
                f'M 40 0 L 50 100 M 0 100 L 60 100" {_INK}/></g>',
            width=60.0, height=100.0,
            ports={"inlet": (_STACK_INLET_X, _STACK_INLET_Y)},
            gravity_fixed=True,
            iso_reg="2041",
        ), "default")

        # Item 4.8, 2591, gas flare: a shaft with a flame on top.
        self.register("flare", Symbol(
            svg='<g id="sym_flare">'
                f'<path d="M 30 40 A 25 25 0 0 1 30 0 A 25 25 0 0 1 30 40 Z" {_INK}/>'
                '<path d="M 20 40 L 40 40 M 20 40 L 20 120 M 40 40 L 40 120 '
                f'M 0 120 L 60 120" {_INK}/>'
                '</g>',
            width=60.0, height=120.0,
            # Inlet on the west wall, two modules up.
            ports={"inlet": (20.0, 90.0)},
            gravity_fixed=True,
            iso_reg="2591",
        ), "default")

        # Vendored draw.io symbols (Apache-2.0).
        from pandid.render._vendored_symbols import register_vendored
        register_vendored(self)

        # Vessel shells, built to size.
        for variant in VESSEL_SIZES:
            self.register("vessel", vessel_shell(variant), variant)

        # ISO 10628-2 group 26-29 parts, then the ISO families.
        from pandid.render.iso_parts import parts
        for part in parts():
            self.register_part(part)
        self._register_composed()
        self._register_crushing_machines()
        self._register_centrifuges()
        self._register_driers()
        self._register_cooling_towers()
        self._register_feeders()
        self._register_mixers()
        self._register_screens()
        self._register_evaporators()
        self._register_crystallizer()
        self._register_flotation_cell()
        self.register("silo", _SILO)
        self.register("silo", _BUNKER, "bunker")
        self.register("mixer_settler", _MIXER_SETTLER)
        self.register("deaerator", _DEAERATOR)
        self.register("motor", _motor("general", "C0082"), "general")
        self.register("motor", _motor("ac", "X8157", _MOTOR_TILDE), "ac")
        self.register("motor", _motor("dc", "X8158", _MOTOR_BAR), "dc")
        self._register_kilns()
        self._register_steam_trap()
        self._register_flow_elements()
        self._register_fans()

    def _register_fans(self):
        """Register the general, centrifugal and axial fans."""
        self.register("blower", _FAN_GENERAL, "general")
        self.register("blower", _FAN_CENTRIFUGAL, "centrifugal")
        self.register("blower", _FAN_AXIAL, "axial")

    def _register_steam_trap(self):
        """Register the steam trap, ISO 10628-2 item 24.15 (2181)."""
        self.register("fitting", _STEAM_TRAP, "steam_trap")

    def _register_flow_elements(self):
        """Register the hand-drawn primary flow elements."""
        self.register("fitting", _FE_MAGNETIC, "magnetic")
        self.register("fitting", _FE_CLAMP_ON, "ultrasonic_clamp_on")
        self.register("fitting", _FE_THERMAL_MASS, "thermal_mass")
        self.register("fitting", _FE_FLUME, "flume")

    def _register_composed(self):
        """Register the three composed group-8 separators."""
        from pandid.render.iso_parts import characteristic_overlays

        for name, reg in (("gravity", "X8031"), ("electrostatic", "X8125"),
                          ("electromagnetic", "X8126")):
            overlays = characteristic_overlays(name, registry=self)
            self.register("separator", compose(
                _SEPARATING_VESSEL,
                [(o, self.part(o.group, o.name)) for o in overlays],
                iso_reg=reg,
            ), name)

    def _register_crushing_machines(self):
        """Register ISO 10628-2 group 11, the crushers and mills."""
        from pandid.render.iso_parts import crushing_overlays

        general = _crushing_machine("crushing_machine", "X8084")
        crusher = _crushing_machine("crusher", "X8085", _CRUSHER_JAWS)
        mill = _crushing_machine("mill", "X8086", _MILL_CHAMFERS)
        # Unregistered drum body.
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
                overlays = crushing_overlays(name, registry=self)
                self.register(kind, compose(
                    body,
                    [(o, self.part(o.group, o.name)) for o in overlays],
                    iso_reg=reg,
                ), name)

    def _register_centrifuges(self):
        """Register ISO 10628-2 group 9, the centrifuges.

        The decanter is also registered as ``default``.
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
            # The bare square, its west wall at ox.
            outline = (f'<path d="M {ox:g} 0 L {ox + sq:g} 0 L {ox + sq:g} {sq:g} '
                       f'L {ox:g} {sq:g} Z" {_OUTLINE}/>')
            sym = _family(outline, width, height, ports, "centrifuge_", name, reg, detail,
                          gravity_fixed=False)
            self.register("centrifuge", sym, name)
            by_name[name] = sym
        # The default is the decanter.
        self.register("centrifuge", by_name["decanter"])

    def _register_driers(self):
        """Register four ISO 10628-2 group-10 dryers."""
        self.register("dryer", _drier("general", "C0046"), "general")
        # Only the shelf dryer is gravity-fixed.
        self.register(
            "dryer", _drier("shelf", "X8083", _DRIER_SHELVES, gravity_fixed=True),
            "shelf")
        self.register(
            "dryer", _drier("turbo", "X8040", _DRIER_TURBO), "turbo")
        self.register(
            "dryer", _drier("belt", "X8043", _DRIER_BELT), "belt")

    def _register_cooling_towers(self):
        """Register ISO 10628-2 group 5 except the spray cooler."""
        for name, fill, fan, reg in (
            ("general", "", "", "2521"),
            ("dry_natural", _TOWER_DRY, "", "X8109"),
            ("dry_forced", _TOWER_DRY, _TOWER_FAN_FORCED, "X8110"),
            ("dry_induced", _TOWER_DRY, _TOWER_FAN_INDUCED, "X8111"),
            ("wet_natural", _TOWER_WET, "", "X8112"),
            ("wet_forced", _TOWER_WET, _TOWER_FAN_FORCED, "X8113"),
            ("wet_induced", _TOWER_WET, _TOWER_FAN_INDUCED, "X8114"),
            ("wet_dry_natural", _TOWER_DRY + _TOWER_WET, "", "X8115"),
        ):
            self.register("cooling_tower", _family(
                _TOWER_OUTLINE, _TOWER_W, _TOWER_H, _TOWER_PORTS, "cooling_tower_", name, reg,
                fill, fan), name)

    def _register_feeders(self):
        """Register the ISO 10628-2 group 19 symbols."""
        self.register("feeder", _feeder_circle("general", "C2056", _FEEDER_Z), "general")
        self.register(
            "feeder", _feeder_circle("rotary_valve", "X8067", _FEEDER_ROTOR_MARK),
            "rotary_valve")
        self.register("feeder", Symbol(
            svg=f'<g id="sym_feeder_rotary_table">{_FEEDER_TABLE}</g>',
            width=_FEEDER_TABLE_W, height=_FEEDER_TABLE_H,
            ports={"feed": (25.0, 0.0), "discharge": (25.0, 60.0), "drive": (0.0, 37.5)},
            gravity_fixed=True, iso_reg="C0074",
        ), "rotary_table")
        self.register("feeder", Symbol(
            svg=f'<g id="sym_feeder_metering">{_METER}</g>',
            width=_METER_W, height=_METER_H,
            ports={"feed": (0.0, _METER_BEAM_Y), "discharge": (_METER_W, _METER_BEAM_Y),
                   "drive": (_METER_W / 2, _METER_H)},
            gravity_fixed=True, iso_reg="C0035",
        ), "metering")
        self.register("spray_nozzle", _SPRAY_NOZZLE)

    def _register_mixers(self):
        """Register ISO 10628-2 items 12.1, 12.3 and 12.4."""
        self.register("fitting", _ROTARY_MIXER, "rotary_mixer")
        self.register("fitting", _MIXING_PATH, "mixing_path")
        self.register("kneader", _KNEADER)

    def _register_screens(self):
        """Register ISO 10628-2 group 7, the screening devices."""
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
            + f'<line x1="20" y1="0" x2="60" y2="40" {_INK} {_DASH_LONG}/>'), "coarse_and_fine")
        self.register("screening_device", _screen(
            "vibrating", "X2605", _SCREEN_MESH + _SCREEN_VIBRATION), "vibrating")
        self.register("screening_device", _screen(
            "rotating_drum", "X8029", _SCREEN_DRUM), "rotating_drum")
        self.register("screening_device", _REEL_BODY, "basket_reel")

    def _register_evaporators(self):
        """Register the five evaporator bodies on one shell."""
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

    def _register_crystallizer(self):
        """Register the draft-tube baffle crystallizer."""
        self.register("crystallizer", Symbol(
            svg=f'<g id="sym_crystallizer">{_CRYST_OUTLINE}{_CRYST_INTERNALS}</g>',
            width=CRYST_W, height=CRYST_H, ports=dict(_CRYST_PORTS),
            gravity_fixed=True,
        ))

    def _register_flotation_cell(self):
        """Register the mechanical flotation cell."""
        self.register("flotation_cell", Symbol(
            svg=f'<g id="sym_flotation_cell">{_FLOT_OUTLINE}{_FLOT_AIR}{_FLOT_BUBBLES}</g>',
            width=FLOT_W, height=FLOT_H, ports=dict(_FLOT_PORTS),
            gravity_fixed=True,
        ))

    def _register_kilns(self):
        """Register the rotary, fluidised-bed and shaft kilns."""
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
