"""Resolve unit sizes and port geometry for layout, routing and drawing.

Functions take the placement as a parameter: a ``Frame``, a ``Pin`` or
the solver's ``_Slot``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from pandid.units import Unit, _Families


def _sym(unit: "Unit"):
    """Return the symbol the default registry draws a unit with.

    Parameters
    ----------
    unit : Unit
        Unit to look up.

    Returns
    -------
    Symbol
        The unit's symbol.
    """
    from pandid.render.symbols import default_registry
    return default_registry.for_unit(unit)


def _xform(frame) -> tuple[int, bool, bool]:
    """Return a placement's turn and left-right and top-bottom flips.

    Parameters
    ----------
    frame : Frame, Pin or _Slot
        Placement to read.

    Returns
    -------
    tuple[int, bool, bool]
        Clockwise turn in degrees, ``mirrored`` and ``mirror_y``.
    """
    return (int(getattr(frame, "orientation", 0) or 0),
            bool(getattr(frame, "mirrored", False)),
            bool(getattr(frame, "mirror_y", False)))


def symbol_to_box(px: float, py: float, sw: float, sh: float,
                  rot: int = 0, mirror_x: bool = False, mirror_y: bool = False
                  ) -> tuple[float, float, float, float]:
    """Map a point in symbol coordinates into the placed box.

    Mirror first, in the symbol's frame, then turn clockwise by ``rot``
    degrees; any ``rot`` but 90, 180 or 270 leaves the point unturned.

    Parameters
    ----------
    px, py : float
        Point in symbol coordinates.
    sw, sh : float
        Symbol width and height.
    rot : int, default=0
        Clockwise turn in degrees: 0, 90, 180 or 270.
    mirror_x, mirror_y : bool, default=False
        Left-right and top-bottom flips.

    Returns
    -------
    tuple[float, float, float, float]
        Mapped ``x`` and ``y``, and the turned box width and height.
    """
    if mirror_x:
        px = sw - px
    if mirror_y:
        py = sh - py
    if rot == 90:
        return sh - py, px, sh, sw
    if rot == 180:
        return sw - px, sh - py, sw, sh
    if rot == 270:
        return py, sw - px, sh, sw
    return px, py, sw, sh


#: Compass point to ``(eastward, southward)`` on the y-down canvas.
COMPASS: dict[str, tuple[int, int]] = {
    "N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0),
    "NE": (1, -1), "NW": (-1, -1), "SE": (1, 1), "SW": (-1, 1),
}

#: The four faces of a box.
COMPASS_FACES = ("N", "E", "S", "W")


def port_faces(unit: "Unit", port_name: str, placed=None) -> list[str]:
    """Return the faces a port may be drawn on.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    placed : Pin, Frame, _Slot or None, optional
        Placement to answer for; defaults to the unit's pin, then frame.

    Returns
    -------
    list[str]
        Compass faces, the symbol's own face first.
    """
    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mx, my = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    return list(_drawn_placements(unit, port_name, w, h, rot, mx, my,
                                  _placed_sym(unit, placed)))


def drawn_side(face: str, rot: int, mirrored: bool, mirror_y: bool) -> str:
    """Return the face a symbol's own face is drawn on when placed.

    Parameters
    ----------
    face : str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"`` on the symbol's own axes.
    rot : int
        Clockwise turn in degrees: 0, 90, 180 or 270.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.

    Returns
    -------
    str
        Face as drawn.
    """
    px, py = {"N": (0.5, 0.0), "S": (0.5, 1.0), "W": (0.0, 0.5), "E": (1.0, 0.5)}[face]
    bx, by, bw, bh = symbol_to_box(px, py, 1.0, 1.0, rot, mirrored, mirror_y)
    return outward_dir(bx, by, bw, bh)


def family_faces(unit: "_Families", placed) -> dict[str, str] | None:
    """Return a unit's family faces with the engine's choices applied.

    A lone port its symbol offers a menu of faces is drawn from that
    menu and is left out.

    Parameters
    ----------
    unit : _Families
        Unit with port families.
    placed : Frame or None
        Placement whose ``port_faces`` holds the choices, as drawn.

    Returns
    -------
    dict[str, str] or None
        Port name to face on the unit's own axes, in drawn order, or
        None if the placement moves no family port.
    """
    chosen = getattr(placed, "port_faces", None)
    if not chosen:
        return None
    rot, mx, my = _xform(placed)
    own = {drawn_side(face, rot, mx, my): face for face in COMPASS_FACES}
    menus = _sym(unit).port_faces
    moved = {name: own[face] for name, face in chosen.items()
             if name in unit._faces and name not in unit._stated
             and len(menus.get(name, ())) < 2 and own[face] != unit._faces[name]}
    return {**unit._faces, **moved} if moved else None


def _placed_sym(unit: "Unit", placed):
    """Return the symbol a placement draws a unit with.

    Parameters
    ----------
    unit : Unit
        Unit to look up.
    placed : Pin, Frame, _Slot or None
        Placement, whose ``port_faces`` may move family ports.

    Returns
    -------
    Symbol
        The unit's symbol, with its families on the chosen faces.
    """
    from pandid.units import _Families

    if isinstance(unit, _Families):
        return unit.symbol(family_faces(unit, placed))
    return _sym(unit)


def unreachable_face(unit: "Unit", port_name: str, face: str,
                     options: list[str]) -> ValueError:
    """Build the error for a face a port cannot take as drawn.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    face : str
        Face requested.
    options : list[str]
        Faces the port can take.

    Returns
    -------
    ValueError
        Error naming the faces on offer.
    """
    offered = " or ".join(filter(None, [", ".join(options[:-1]), *options[-1:]]))
    return ValueError(
        f"{unit.name}.{port_name} can be piped from {offered} as drawn; "
        f"you asked for {face!r}"
    )


def _drawn_placements(unit: "Unit", port_name: str, w: float, h: float,
                      rot: int, mirrored: bool, mirror_y: bool,
                      sym=None) -> dict[str, tuple[float, float]]:
    """Return a port's drawn point on each face it may take.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name or alias.
    w, h : float
        Placed box size.
    rot : int
        Clockwise turn in degrees: 0, 90, 180 or 270.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.
    sym : Symbol, optional
        Symbol to read; the unit's own when omitted.

    Returns
    -------
    dict[str, tuple[float, float]]
        Face to point from the box's top-left, own face first.
    """
    if sym is None:
        sym = _sym(unit)
    port_name = unit._canonical_port_name(port_name)
    anchor = unit._symbol_anchor(port_name)
    menu = (getattr(sym, "port_faces", None) or {}).get(anchor)
    # A series member leaves by its series' face.
    declared = None
    if menu:
        coords = list(menu.values())
    elif (placed := _series_point(unit, sym, port_name)) is not None:
        coords = [placed]
        declared = sym.series_for(port_name).face
    else:
        # An unanchored port falls back to the symbol's centre.
        coords = [sym.ports.get(anchor, (sym.width / 2, sym.height / 2))]
    out: dict[str, tuple[float, float]] = {}
    for px, py in coords:
        if unit.kind in ("feed", "product"):
            # A flag port's y scales with the flag; its x does not.
            lx, ly = (sym.width - px if mirrored else px), py / sym.height * h
            face = outward_dir(lx, ly, w, h, unit.kind, anchor, mirrored)
        else:
            (lx, ly), (ox, oy, iw, ih) = _to_box(sym, px, py, w, h, rot, mirrored, mirror_y)
            face = (drawn_side(declared, rot, mirrored, mirror_y) if declared is not None
                    else outward_dir(lx - ox, ly - oy, iw, ih, unit.kind, anchor, mirrored))
        out.setdefault(face, (lx, ly))
    return out


def _to_box(sym, px: float, py: float, w: float, h: float, rot: int,
            mirrored: bool, mirror_y: bool
            ) -> tuple[tuple[float, float], tuple[float, float, float, float]]:
    """Map a symbol point into a placed box, and return the artwork's box.

    Parameters
    ----------
    sym : Symbol
        Symbol the point is on.
    px, py : float
        Point in symbol coordinates.
    w, h : float
        Placed box size.
    rot : int
        Clockwise turn in degrees: 0, 90, 180 or 270.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.

    Returns
    -------
    tuple[tuple[float, float], tuple[float, float, float, float]]
        Point from the box's top-left, and the artwork's ``(x, y, w, h)``
        in the box.
    """
    bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height, rot, mirrored, mirror_y)
    # The artwork fills the box, or keeps its aspect centred in it.
    ox, oy, iw, ih = 0.0, 0.0, w, h
    if not getattr(sym, "stretchable", True):
        scale = min(w / bw, h / bh)
        iw, ih = bw * scale, bh * scale
        ox, oy = (w - iw) / 2, (h - ih) / 2
    return (ox + bx * iw / bw, oy + by * ih / bh), (ox, oy, iw, ih)


def _series_point(unit: "Unit", sym, port_name: str
                  ) -> tuple[float, float] | None:
    """Return the symbol point a port series gives a port.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    sym : Symbol
        Unit's symbol.
    port_name : str
        Port name or alias.

    Returns
    -------
    tuple[float, float] or None
        Point in symbol coordinates, or None if no series places it.
    """
    port_name = unit._canonical_port_name(port_name)
    series = sym.series_for(port_name) if hasattr(sym, "series_for") else None
    if series is None:
        return None
    members = unit._series_members(series)
    index = members.get(port_name)
    if index is None:
        return None
    return series.placement(index, len(members), sym.width, sym.height,
                            pin=unit._series_pin(port_name),
                            band=sym.bands.get(series.face))


def is_anchored(unit: "Unit", port_name: str) -> bool:
    """Return whether the symbol or a port series places a port.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name or alias.

    Returns
    -------
    bool
        True if the symbol or a port series places the port.
    """
    sym = _sym(unit)
    port_name = unit._canonical_port_name(port_name)
    return (unit._symbol_anchor(port_name) in sym.ports
            or _series_point(unit, sym, port_name) is not None)


#: Inset of a flag's pennant from its frame's top and bottom, without
#: and with a reference under the tag.
FLAG_INSET, FLAG_INSET_REF = 15, 12


def unit_box(unit: "Unit", frame) -> tuple[float, float, float, float]:
    """Return the box a unit's symbol is drawn in.

    A Feed or Product is its pennant, inset from the top and bottom of
    its frame. An unmirrored feed extends left from its port at
    ``frame.x + 50``.

    Parameters
    ----------
    unit : Unit
        Unit to measure.
    frame : Frame or _Slot
        Its placement.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x_min, y_min, x_max, y_max)``.
    """
    x0, y0, x1, y1 = frame.x, frame.y, frame.x + frame.w, frame.y + frame.h
    if unit.kind == "feed" and not frame.mirrored:
        x0, x1 = frame.x + 50.0 - frame.w, frame.x + 50.0
    if unit.kind not in ("feed", "product"):
        return x0, y0, x1, y1
    inset = FLAG_INSET_REF if _flag_reference(unit) else FLAG_INSET
    top, bottom = sorted((y0 + inset, y1 - inset))
    return x0, top, x1, bottom


def tag_width(tag: str) -> float:
    """Return the width of the halo an equipment tag is drawn on.

    Parameters
    ----------
    tag : str
        Tag as drawn.

    Returns
    -------
    float
        Halo width.
    """
    from pandid.render.furniture import text_width
    from pandid.render.symbols import _TAG_TYPE

    return text_width(tag, _TAG_TYPE) + 8


def face_point(unit: "Unit", frame, face: str) -> tuple[tuple[float, float],
                                                        tuple[float, float]]:
    """Return the midpoint and outward normal of a drawn box's face.

    Parameters
    ----------
    unit : Unit
        Host unit.
    frame : Frame
        Its placement.
    face : str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``, in any case.

    Returns
    -------
    tuple[tuple[float, float], tuple[float, float]]
        Midpoint and unit normal.

    Raises
    ------
    KeyError
        If ``face.upper()`` is not ``N``, ``S``, ``E`` or ``W``.
    """
    x0, y0, x1, y1 = unit_box(unit, frame)
    return {
        "N": (((x0 + x1) / 2, y0), (0.0, -1.0)),
        "S": (((x0 + x1) / 2, y1), (0.0, 1.0)),
        "W": ((x0, (y0 + y1) / 2), (-1.0, 0.0)),
        "E": ((x1, (y0 + y1) / 2), (1.0, 0.0)),
    }[face.upper()]


def _flag_reference(unit: "Unit") -> str:
    """Return the off-page reference a boundary flag draws, as text.

    Parameters
    ----------
    unit : Unit
        Unit, usually a Feed or Product.

    Returns
    -------
    str
        Reference text, blank if none.
    """
    from pandid.document import _drawn_text

    return _drawn_text(getattr(unit, "reference", None))


def resolve_size(unit: "Unit", placed=None) -> tuple[float, float]:
    """Return the size of a unit's placed box.

    An explicit ``width`` or ``height`` is the final size. A symbol size
    swaps on a quarter turn. A flag's default width fits its tag or
    reference, and is at least 80.

    Parameters
    ----------
    unit : Unit
        Unit to size.
    placed : Pin, Frame, _Slot or None, optional
        Placement whose turn applies; defaults to the unit's pin.

    Returns
    -------
    tuple[float, float]
        Width and height.
    """
    sym = _sym(unit)
    if unit.kind in ("feed", "product"):
        from pandid.render.symbols import label_span
        w = unit.width if unit.width is not None else max(
            80.0, label_span(unit.tag), label_span(_flag_reference(unit)))
        return w, unit.height if unit.height is not None else sym.height

    sym_w, sym_h = sym.width, sym.height
    turn = placed if placed is not None else getattr(unit, "pin_", None)
    if turn is not None and int(getattr(turn, "orientation", 0) or 0) in (90, 270):
        sym_w, sym_h = sym_h, sym_w
    w = unit.width if unit.width is not None else sym_w
    h = unit.height if unit.height is not None else sym_h
    return w, h


def outward_dir(px: float, py: float, w: float, h: float,
                kind: str = "", port_name: str = "", mirrored: bool = False) -> str:
    """Return the face a port at a box-local point faces.

    A feed outlet or product inlet faces along its pennant; any other
    port faces the nearest box edge.

    Parameters
    ----------
    px, py : float
        Port position from the box's top-left corner.
    w, h : float
        Box size.
    kind : str, default=""
        Unit kind.
    port_name : str, default=""
        Anchor name.
    mirrored : bool, default=False
        Whether the unit is flipped left to right.

    Returns
    -------
    str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    """
    if kind == "product" and port_name == "inlet":
        return "E" if mirrored else "W"
    if kind == "feed" and port_name == "outlet":
        return "W" if mirrored else "E"
    dist_N, dist_S, dist_W, dist_E = py, h - py, px, w - px
    m = min(dist_N, dist_S, dist_W, dist_E)
    if m == dist_N:
        return "N"
    if m == dist_S:
        return "S"
    if m == dist_W:
        return "W"
    return "E"


class ResolvedPort(NamedTuple):
    """A port's drawn point, box-edge routing anchor and face.

    Attributes
    ----------
    point : tuple[float, float]
        Where the line attaches on the drawing.
    anchor : tuple[float, float]
        Where routing starts: the point projected onto the box edge.
    face : str
        Compass face the port leaves by.
    """
    point: tuple[float, float]
    anchor: tuple[float, float]
    face: str


#: Spacing of the lines that share a face of an instrument.
SHARED_PITCH = 10.0

#: Largest fraction of an instrument's face those lines may span.
SHARED_EXTENT = 0.7


def resolve_port(unit: "Unit", frame, port_name: str, *, alone: bool = False
                 ) -> ResolvedPort:
    """Resolve a port's drawn point, routing anchor and face.

    A boundary flag's port is the tip of its pennant for both points.
    Lines that share a point on an instrument are spread along its face
    and onto its rim.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Port name or alias.
    alone : bool, default=False
        Resolve the port as if no other line shared its point.

    Returns
    -------
    ResolvedPort
        Point, anchor and face.

    Raises
    ------
    ValueError
        If the chosen face cannot be reached under the placement.
    """
    w, h = frame.w, frame.h
    d, (px, py) = _face_and_point(unit, frame, port_name)

    if unit.kind in ("feed", "product"):
        # The port is the end of the flag's box that the line meets.
        x0, _, x1, _ = unit_box(unit, frame)
        tip = (x1 if (unit.kind == "feed") != _xform(frame)[1] else x0, frame.y + py)
        return ResolvedPort(tip, tip, d)

    if not alone and unit.kind == "instrument":
        px, py = _shared_point(unit, frame, port_name, d, (px, py))
    point = (frame.x + px, frame.y + py)
    ax, ay = point
    if d == "N":
        ay = frame.y
    elif d == "S":
        ay = frame.y + h
    elif d == "W":
        ax = frame.x
    elif d == "E":
        ax = frame.x + w
    return ResolvedPort(point, (ax, ay), d)


def _face_and_point(unit: "Unit", frame, port_name: str
                    ) -> tuple[str, tuple[float, float]]:
    """Return a port's face and its own point from the box's top-left.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Port name or alias.

    Returns
    -------
    tuple[str, tuple[float, float]]
        Face and point.

    Raises
    ------
    ValueError
        If the chosen face cannot be reached under the placement.
    """
    rot, mirrored, mirror_y = _xform(frame)
    # A face set with ``nozzle()`` wins over the engine's choice.
    canonical = unit._canonical_port_name(port_name)
    want = (getattr(unit, "_port_faces", None) or {}).get(canonical)
    if want is None:
        want = (getattr(frame, "port_faces", None) or {}).get(canonical)
    placements = _drawn_placements(unit, port_name, frame.w, frame.h, rot, mirrored,
                                   mirror_y, _placed_sym(unit, frame))
    if want is not None and want not in placements:
        raise unreachable_face(unit, port_name, want, list(placements))
    return next(iter(placements.items())) if want is None else (want, placements[want])


def _shared_point(unit: "Unit", frame, port_name: str, face: str,
                  point: tuple[float, float]) -> tuple[float, float]:
    """Return a connected port's point among the lines sharing it.

    The lines on one point are spread along the artwork's side of the
    face in the order of their peers' bearings, each moved in onto the
    symbol's rim. A port the unit is pinned by keeps its own point, and
    the others take places on either side of it.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Port name or alias.
    face : str
        Face the port is on.
    point : tuple[float, float]
        The port's own point from the box's top-left.

    Returns
    -------
    tuple[float, float]
        Point from the box's top-left.
    """
    from pandid.render.symbols import spread

    name = unit._canonical_port_name(port_name)
    port = unit.ports.get(name)
    pinned = {unit._canonical_port_name(p) for p, _ in pin_intent(unit).values() if p}
    if port is None or port.stream is None or name in pinned:
        return point
    sharing = [other for other, p in unit.ports.items() if p.stream is not None
               and _face_and_point(unit, frame, other) == (face, point)]
    if len(sharing) < 2:
        return point
    sharing.sort(key=lambda other: _bearing(unit, frame, other, face))
    sym = _sym(unit)
    rot, mirrored, mirror_y = _xform(frame)
    rim = [_to_box(sym, x, y, frame.w, frame.h, rot, mirrored, mirror_y)[0]
           for x, y in getattr(sym, "rim", ())]
    _, (ox, oy, iw, ih) = _to_box(sym, 0.0, 0.0, frame.w, frame.h, rot, mirrored, mirror_y)
    upright = face in ("E", "W")
    at, lo, along = (point[1], oy, ih) if upright else (point[0], ox, iw)
    index, count = sharing.index(name), len(sharing)
    fixed = next((i for i, other in enumerate(sharing) if other in pinned), None)
    if fixed is not None:
        # Odd places centred on the pinned port, which takes the middle one.
        reach = max(fixed, count - 1 - fixed)
        index, count = reach + index - fixed, 2 * reach + 1
    t = spread(index, count, along, SHARED_PITCH, SHARED_EXTENT, at, band=(lo, lo + along))
    inward = (_rim_depth(rim, face, t, frame.w, frame.h)
              - _rim_depth(rim, face, at, frame.w, frame.h))
    sign = -1.0 if face in ("E", "S") else 1.0
    return (point[0] + sign * inward, t) if upright else (t, point[1] + sign * inward)


def _bearing(unit: "Unit", frame, port_name: str, face: str) -> float:
    """Return the angle from a face's normal to a port's peer unit.

    The angle grows in the direction positions along the face grow.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Connected port.
    face : str
        Face the port is on.

    Returns
    -------
    float
        Angle in radians, 0.0 while the peer is unplaced.
    """
    port = unit.ports[port_name]
    stream = port.stream
    assert stream is not None
    owner = (stream.dest if stream.source is port else stream.source).owner
    if owner.frame is None:
        return 0.0
    x0, y0, x1, y1 = unit_box(owner, owner.frame)
    dx = (x0 + x1 - frame.w) / 2 - frame.x
    dy = (y0 + y1 - frame.h) / 2 - frame.y
    nx, ny = COMPASS[face]
    return math.atan2(dy if face in ("E", "W") else dx, dx * nx + dy * ny)


def _rim_depth(rim: "Sequence[tuple[float, float]]", face: str, t: float,
               w: float, h: float) -> float:
    """Return how far in from a face a polygon lies, ``t`` along the face.

    Parameters
    ----------
    rim : Sequence[tuple[float, float]]
        Convex polygon in the box; empty for the box itself.
    face : str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    t : float
        Position along the face.
    w, h : float
        Box size.

    Returns
    -------
    float
        Depth, or 0.0 where the polygon does not reach ``t``.
    """
    upright = face in ("E", "W")
    cuts = []
    for (x0, y0), (x1, y1) in zip(rim, [*rim[1:], *rim[:1]]):
        a0, a1, b0, b1 = (y0, y1, x0, x1) if upright else (x0, x1, y0, y1)
        if a0 != a1 and min(a0, a1) <= t <= max(a0, a1):
            cuts.append(b0 + (b1 - b0) * (t - a0) / (a1 - a0))
    if not cuts:
        return 0.0
    return {"W": min(cuts), "N": min(cuts), "E": w - max(cuts), "S": h - max(cuts)}[face]


def port_point(unit: "Unit", frame, port_name: str) -> tuple[float, float]:
    """Return the point where a line attaches to a port.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Port name.

    Returns
    -------
    tuple[float, float]
        Point on the drawing.

    Raises
    ------
    ValueError
        If the chosen face cannot be reached under the placement.
    """
    return resolve_port(unit, frame, port_name).point


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Return a port's routing anchor and face.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    frame : Frame or _Slot
        Its placement.
    port_name : str
        Port name.

    Returns
    -------
    tuple[float, float, str]
        Anchor ``x`` and ``y``, and the face.

    Raises
    ------
    ValueError
        If the chosen face cannot be reached under the placement.
    """
    _, (ax, ay), d = resolve_port(unit, frame, port_name)
    return ax, ay, d


def port_offset(unit: "Unit", port_name: str, placed=None) -> tuple[float, float]:
    """Return a port's offset from its unit's top-left corner.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    placed : Pin, Frame, _Slot or None, optional
        Placement to use; defaults to the pin, then the frame.

    Returns
    -------
    tuple[float, float]
        Offset in the placed box.

    Raises
    ------
    ValueError
        If a face set with ``nozzle()`` cannot be reached when placed.
    """
    from pandid.geometry import Frame

    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mirror_x, mirror_y = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    probe = Frame(x=0.0, y=0.0, w=w, h=h, orientation=rot,
                  mirrored=mirror_x, mirror_y=mirror_y)
    return port_point(unit, probe, port_name)


def _pinned(unit: "Unit", axis: str, port_name: str | None) -> float:
    """Return one pinned coordinate of a unit's corner or port.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    axis : str
        ``"x"`` or ``"y"``.
    port_name : str or None
        Port to measure to, or None for the corner.

    Returns
    -------
    float
        Absolute coordinate.

    Raises
    ------
    ValueError
        If ``axis`` is unpinned or the port's face is unreachable.
    """
    pin = unit.pin_
    if pin is None:
        raise ValueError(
            f"{unit.name} has not been pinned, so it has no {axis} to read. "
            f"pin() it first, or ask its frame after the sheet is laid out "
            f"(port_point(unit, unit.frame, ...))."
        )
    corner = getattr(pin, axis)
    if corner is None:
        placed = "col/row" if (pin.col is not None or pin.row is not None) else "nothing"
        raise ValueError(
            f"{unit.name} is pinned by {placed} and not by an absolute {axis}, so "
            f"there is no coordinate to read: the solver decides it, and it is not "
            f"decided until the sheet is laid out. Pin it with {axis}=, or read "
            f"unit.frame.{axis} afterwards."
        )
    if port_name is None:
        return corner
    return corner + port_offset(unit, port_name)[0 if axis == "x" else 1]


def pinned_x(unit: "Unit", port_name: str | None = None) -> float:
    """Return the pinned ``x`` of a unit's corner or one of its ports.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    port_name : str or None, optional
        Port to measure to, or None for the corner.

    Returns
    -------
    float
        Absolute ``x``.

    Raises
    ------
    ValueError
        If no ``x`` is pinned or the port's face is unreachable.
    """
    return _pinned(unit, "x", port_name)


def pinned_y(unit: "Unit", port_name: str | None = None) -> float:
    """Return the pinned ``y`` of a unit's corner or one of its ports.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    port_name : str or None, optional
        Port to measure to, or None for the corner.

    Returns
    -------
    float
        Absolute ``y``.

    Raises
    ------
    ValueError
        If no ``y`` is pinned or the port's face is unreachable.
    """
    return _pinned(unit, "y", port_name)


def pin_intent(unit: "Unit") -> dict[str, tuple[str | None, float]]:
    """Return the pixel coordinates the author pinned, per axis.

    Parameters
    ----------
    unit : Unit
        Unit to read.

    Returns
    -------
    dict[str, tuple[str or None, float]]
        Axis to ``(port or None, value)``; empty when nothing is pinned.
    """
    pin = getattr(unit, "_pin", None)
    if pin is None:
        return {}
    ports = getattr(unit, "_pin_ports", None) or {}
    return {axis: (ports.get(axis), value)
            for axis in ("x", "y")
            if (value := getattr(pin, axis)) is not None}


def port_refusal(port_name: "str | None", axes: "Sequence[str]",
                 measured: "Collection[str]", ranks: "Collection[str]",
                 drop: str) -> str | None:
    """Return why a port named on a pin locates no coordinate.

    Parameters
    ----------
    port_name : str or None
        Port named on the pin.
    axes : Sequence[str]
        Coordinates the port is offered for.
    measured : Collection[str]
        Coordinates measured to the port.
    ranks : Collection[str]
        Grid ranks the pin names.
    drop : str
        What the author removes to keep the rest, such as ``port.x``.

    Returns
    -------
    str or None
        Message, or None if ``axes`` is empty or meets ``measured``.
    """
    if not axes or set(axes) & set(measured):
        return None
    subject = " or ".join(axes)
    said = (f"port {port_name!r} is the nozzle {subject} "
            f"{'are' if len(axes) > 1 else 'is'} measured to, and this pin states "
            f"{'neither' if len(axes) > 1 else f'no {axes[0]}'}")
    if ranks:
        named = " and ".join(sorted(ranks))
        said += (f": {named} {'name' if len(ranks) > 1 else 'names'} a grid cell, "
                 f"which has no nozzle in it")
    return f"{said}. Give {subject}, or drop {drop}"
