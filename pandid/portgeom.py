"""Resolve unit sizes and port geometry for layout, routing and rendering.

Every caller resolves sizes and port positions here, so the drawn sheet
and the routed paths agree. :func:`resolve_port` is the single authority
on a port's drawn point, routing anchor and face; :func:`port_point`,
:func:`port_anchor` and :func:`port_offset` wrap it. A port's face comes
from :func:`chosen_face`: the author's ``nozzle()`` first, then the
engine's choice, then the symbol's own face.

Functions take the placement as a parameter, so they work on the
solver's ``_Slot`` during layout and on a ``Frame`` afterwards. Where the
placement is optional, they use the unit's pin, then its frame; a caller
about to change either passes its candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from pandid.units import Unit


def _sym(unit: "Unit"):
    """Return the symbol the default registry draws a unit with.

    Parameters
    ----------
    unit : Unit
        Unit to look up.

    Returns
    -------
    Symbol
        Registered symbol for the unit's kind and variant.
    """
    from pandid.render.symbols import default_registry
    return default_registry.for_unit(unit)


def _anchor(unit: "Unit", port_name: str) -> str:
    """Return the name the unit's symbol anchors a port under.

    Usually the port's own name. A class that renames a nozzle its artwork
    already ships declares the old name in
    :attr:`pandid.units.Unit.PORT_ANCHORS`; this applies the rename
    through :meth:`pandid.units.Unit._symbol_anchor`.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.

    Returns
    -------
    str
        Anchor name in the symbol.
    """
    return unit._symbol_anchor(port_name)


def _xform(frame) -> tuple[int, bool, bool]:
    """Return a placement's transform.

    Parameters
    ----------
    frame : Frame, Pin or _Slot
        Placement to read.

    Returns
    -------
    tuple[int, bool, bool]
        Orientation, left-right flip and top-bottom flip.
    """
    return (int(getattr(frame, "orientation", 0) or 0),
            bool(getattr(frame, "mirrored", False)),
            bool(getattr(frame, "mirror_y", False)))


def symbol_to_box(px: float, py: float, sw: float, sh: float,
                  rot: int = 0, mirror_x: bool = False, mirror_y: bool = False
                  ) -> tuple[float, float, float, float]:
    """Map a point from a symbol's coordinates into its placed box.

    Mirroring is applied first, in the symbol's frame, then the clockwise
    quarter turn: the order the renderer's SVG transform uses.

    Parameters
    ----------
    px, py : float
        Point in symbol coordinates.
    sw, sh : float
        Symbol width and height.
    rot : int, default=0
        Clockwise quarter turn in degrees.
    mirror_x, mirror_y : bool, default=False
        Left-right and top-bottom flips.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x, y, box_w, box_h)``; a quarter turn swaps the box size.
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


#: Compass point to ``(eastward, southward)`` on the y-down canvas. Shared by
#: :mod:`pandid.layout.claims` and :func:`drawn_direction` so a claim's step
#: and its transform use one table.
COMPASS: dict[str, tuple[int, int]] = {
    "N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0),
    "NE": (1, -1), "NW": (-1, -1), "SE": (1, 1), "SW": (-1, 1),
}

_POINT = {step: point for point, step in COMPASS.items()}


def drawn_direction(direction: str, placed) -> str:
    """Turn a compass direction from the symbol's frame into the drawing's.

    Applies the placement's mirror, then its clockwise quarter turn, as
    :func:`symbol_to_box` does for points. A ``"W"`` on a unit drawn
    ``mirrored=True`` becomes ``"E"``. :attr:`pandid.units.Unit.PLACES`
    entries are read through this.

    Parameters
    ----------
    direction : str
        Compass point in the symbol's frame, including diagonals.
    placed : Pin, Frame, _Slot or None
        Placement to apply; ``None`` applies no transform.

    Returns
    -------
    str
        Compass point as drawn.
    """
    rot, mirror_x, mirror_y = _xform(placed) if placed is not None else (0, False, False)
    dx, dy = COMPASS[direction]
    if mirror_x:
        dx = -dx
    if mirror_y:
        dy = -dy
    # Clockwise on the y-down canvas: east turns to south.
    for _ in range(rot // 90 % 4):
        dx, dy = -dy, dx
    return _POINT[(dx, dy)]


def ink_box(bw: float, bh: float, w: float, h: float, stretchable: bool = True
            ) -> tuple[float, float, float, float]:
    """Return where a symbol's artwork lands inside its placed box.

    A stretchable symbol fills the box. Otherwise it keeps its aspect and
    is centred, as SVG's ``preserveAspectRatio="xMidYMid meet"`` does, so
    ports resolved against the artwork stay on the drawing.

    Parameters
    ----------
    bw, bh : float
        Symbol box, already turned by :func:`symbol_to_box`.
    w, h : float
        Placed box.
    stretchable : bool, default=True
        Whether the artwork may be distorted to fill the box.

    Returns
    -------
    tuple[float, float, float, float]
        ``(x, y, width, height)`` relative to the box's top-left corner.
    """
    if stretchable:
        return 0.0, 0.0, w, h
    scale = min(w / bw, h / bh)
    iw, ih = bw * scale, bh * scale
    return (w - iw) / 2, (h - ih) / 2, iw, ih


def port_faces(unit: "Unit", port_name: str, placed=None) -> list[str]:
    """Return the faces a port may be drawn on, best first.

    Faces are reported as drawn, in the frame
    :meth:`pandid.units.Unit.nozzle` takes. A port the symbol does not
    anchor reports the one face its box-centre fallback resolves to.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    placed : Pin, Frame or None, optional
        Placement to answer for. Defaults to the unit's pin, then its frame.

    Returns
    -------
    list[str]
        Compass faces, the symbol's own face first.
    """
    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mx, my = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    return list(_drawn_placements(unit, port_name, w, h, rot, mx, my))


def unreachable_face(unit: "Unit", port_name: str, face: str,
                     options: list[str]) -> ValueError:
    """Build the error for a face a port cannot take as drawn.

    Shared by :meth:`pandid.units.Unit.nozzle` and :func:`_local_port` so
    both raise the same message.

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
        Error naming the faces available.
    """
    # Every port resolves somewhere, so the list is never empty.
    offered = " or ".join(filter(None, [", ".join(options[:-1]), *options[-1:]]))
    return ValueError(
        f"{unit.name}.{port_name} can be piped from {offered} as drawn; "
        f"you asked for {face!r}"
    )


def _drawn_placements(unit: "Unit", port_name: str, w: float, h: float,
                      rot: int, mirrored: bool, mirror_y: bool
                      ) -> dict[str, tuple[float, float]]:
    """Return every declared placement of a port, keyed by drawn face.

    The symbol's face menu is mapped through the placement transform and
    :func:`ink_box`, so points lie on the artwork. Each face is read in the
    artwork's own rectangle. When two placements land on one face after a
    turn, the more preferred one is kept. :func:`outward_dir` receives the
    anchor name so a boundary flag's ``outlet_2`` points the same way as
    its ``outlet``.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    w, h : float
        Placed box size.
    rot : int
        Clockwise quarter turn.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.

    Returns
    -------
    dict[str, tuple[float, float]]
        Point relative to the box's top-left corner, keyed by face, in
        preference order.
    """
    sym = _sym(unit)
    anchor = _anchor(unit, port_name)
    menu = (getattr(sym, "port_faces", None) or {}).get(anchor)
    if menu:
        coords = list(menu.values())
    elif (placed := _series_point(unit, sym, port_name)) is not None:
        coords = [placed]
    else:
        # A port the symbol does not anchor falls back to the centre of
        # the box.
        coords = [sym.ports.get(anchor, (sym.width / 2, sym.height / 2))]
    out: dict[str, tuple[float, float]] = {}
    for px, py in coords:
        if unit.kind in ("feed", "product"):
            # Boundary flags are drawn directly: scale the port's height to
            # the placed flag, but keep its horizontal lead fixed from the
            # frame origin (see :func:`unit_box`).
            lx, ly = (sym.width - px if mirrored else px), py / sym.height * h
            face = outward_dir(lx, ly, w, h, unit.kind, anchor, mirrored)
        else:
            bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height,
                                           rot, mirrored, mirror_y)
            ox, oy, iw, ih = ink_box(bw, bh, w, h, getattr(sym, "stretchable", True))
            lx, ly = ox + bx * iw / bw, oy + by * ih / bh
            face = outward_dir(lx - ox, ly - oy, iw, ih, unit.kind, anchor, mirrored)
        out.setdefault(face, (lx, ly))
    return out


def _series_point(unit: "Unit", sym, port_name: str
                  ) -> tuple[float, float] | None:
    """Return the symbol-space point of a port placed by a port series.

    Members are ordered by the unit's port order. The port name is first
    converted from an alias such as ``Column.feed`` to the real name, so an
    alias resolves to the same point.

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
        Point in symbol coordinates, or ``None`` when no series places the
        port.
    """
    series = sym.series_for(port_name) if hasattr(sym, "series_for") else None
    if series is None:
        return None
    # Resolve the alias first; the member cache is keyed by real names.
    port_name = unit._canonical_port_name(port_name)
    members = unit._series_members(series)
    index = members.get(port_name)
    if index is None:
        return None
    return series.placement(index, len(members), sym.width, sym.height,
                            pin=unit._series_pin(port_name),
                            band=sym.bands.get(series.face))


def is_anchored(unit: "Unit", port_name: str) -> bool:
    """Return whether the symbol places a port.

    An unplaced port falls back to the box centre, so two such ports
    coincide. Collision checks use this to tell that apart from a real
    placement.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.

    Returns
    -------
    bool
        Whether the port is anchored or placed by a port series.
    """
    sym = _sym(unit)
    return (_anchor(unit, port_name) in sym.ports
            or _series_point(unit, sym, port_name) is not None)


def unit_box(unit: "Unit", frame) -> tuple[float, float, float, float]:
    """Return a unit's drawn bounding box.

    The router treats this box as the unit's obstacle. A feed flag that is
    not mirrored keeps its port at ``frame.x + 50`` and extends left from
    it, so the port does not move as the label grows.

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
    if unit.kind == "feed" and not frame.mirrored:
        return (frame.x + 50.0 - frame.w, frame.y, frame.x + 50.0, frame.y + frame.h)
    return (frame.x, frame.y, frame.x + frame.w, frame.y + frame.h)


def face_point(unit: "Unit", frame, face: str) -> tuple[tuple[float, float],
                                                        tuple[float, float]]:
    """Return the midpoint of one face of a unit's box and its normal.

    Used as the tap point of an instrument mounted on equipment. It uses
    :func:`unit_box`, the box the router avoids.

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
        Midpoint and outward unit normal.
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

    ``reference`` is not enforced to be ``str``, so ``100`` draws ``"100"``,
    as a title-block field does (:func:`pandid.document._drawn_text`).

    Parameters
    ----------
    unit : Unit
        Unit, usually a Feed or Product.

    Returns
    -------
    str
        The reference, or ``""`` when it is unset.
    """
    from pandid.document import _drawn_text

    return _drawn_text(getattr(unit, "reference", None))


def resolve_size(unit: "Unit", placed=None) -> tuple[float, float]:
    """Return the size of a unit's placed box.

    An explicit ``width`` or ``height`` is the final size, even when the
    unit is turned. Symbol sizes swap on a quarter turn. Feed and product
    flags are as wide as their tag or off-page reference, at least 80.

    Parameters
    ----------
    unit : Unit
        Unit to size.
    placed : Pin, Frame, _Slot or None, optional
        Placement whose quarter turn applies; defaults to the unit's pin.

    Returns
    -------
    tuple[float, float]
        Width and height.
    """
    sym = _sym(unit)
    if unit.kind in ("feed", "product"):
        # Size the flag to the wider of its tag and its off-page reference.
        # Measure each string separately, since scripts differ in width.
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
    """Return the face a port at a local point faces.

    Feed outlets and product inlets face along their pennant; any other
    port faces the nearest box edge.

    Parameters
    ----------
    px, py : float
        Port position relative to the box's top-left corner.
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
        ``"N"``, ``"S"``, ``"W"`` or ``"E"``.
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


def chosen_face(unit: "Unit", placed, port_name: str) -> str | None:
    """Return the face chosen for a port, if any.

    A face set with :meth:`pandid.units.Unit.nozzle` wins over the face
    the layout engine chose, which is stored on the frame. Aliases are
    resolved to real port names first.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    placed : Frame, _Slot or None
        Placement that may carry the engine's choice.
    port_name : str
        Port name or alias.

    Returns
    -------
    str or None
        Chosen face, or ``None`` to use the symbol's own face.
    """
    port_name = unit._canonical_port_name(port_name)
    explicit = (getattr(unit, "_port_faces", None) or {}).get(port_name)
    if explicit is not None:
        return explicit
    return (getattr(placed, "port_faces", None) or {}).get(port_name)


def _local_port(unit: "Unit", port_name: str, w: float, h: float,
                mirrored: bool, mirror_y: bool, rot: int, want: str | None
                ) -> tuple[str, tuple[float, float]]:
    """Return a port's face and its offset from the box's top-left corner.

    The placement is looked up by face, not inferred from the point, so
    the two cannot disagree.

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    w, h : float
        Placed box size.
    mirrored, mirror_y : bool
        Left-right and top-bottom flips.
    rot : int
        Clockwise quarter turn.
    want : str or None
        Chosen face, or ``None`` for the symbol's own.

    Returns
    -------
    tuple[str, tuple[float, float]]
        Face and offset.

    Raises
    ------
    ValueError
        If ``want`` cannot be reached under this transform.
    """
    placements = _drawn_placements(unit, port_name, w, h, rot, mirrored, mirror_y)
    if want is None:
        return next(iter(placements.items()))
    if want not in placements:
        raise unreachable_face(unit, port_name, want, list(placements))
    return want, placements[want]


class ResolvedPort(NamedTuple):
    """A port's resolved geometry.

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


def resolve_port(unit: "Unit", frame, port_name: str) -> ResolvedPort:
    """Resolve a port's drawn point, routing anchor and face.

    The anchor is the point projected onto the edge of the full placed box,
    which the router treats as the obstacle. A boundary flag's port is the
    tip of its pennant for both; turning or flipping a flag top to bottom
    has no effect, because the pennant states its direction.

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
    ResolvedPort
        Point, anchor and face.

    Raises
    ------
    ValueError
        If the chosen face cannot be reached under the placement.
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    want = chosen_face(unit, frame, port_name)
    d, (px, py) = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot, want)

    if unit.kind in ("feed", "product"):
        # Keep the lead 50 units from the frame origin, so a wider label does
        # not move the nozzle (see :func:`unit_box`).
        if unit.kind == "feed":
            ax = frame.x if mirrored else frame.x + 50.0
        else:
            ax = frame.x + w if mirrored else frame.x
        tip = (ax, frame.y + py)
        return ResolvedPort(tip, tip, d)

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
        Absolute point the renderer draws to.
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
        Anchor ``x``, ``y`` and outward face.
    """
    _, (ax, ay), d = resolve_port(unit, frame, port_name)
    return ax, ay, d


def port_offset(unit: "Unit", port_name: str, placed=None) -> tuple[float, float]:
    """Return a port's offset from its unit's top-left corner.

    Read from the symbol, so it stays right when the artwork or size
    changes. ``pin(port=...)`` uses it to place a nozzle; :func:`pinned_x`
    and :func:`pinned_y` add it to a pinned corner::

        feed_y = pinned_y(column, "feed")

    Parameters
    ----------
    unit : Unit
        Unit that owns the port.
    port_name : str
        Port name.
    placed : Pin, Frame, _Slot or None, optional
        Placement to answer for. Defaults to the unit's pin, then its frame.
        A turn or mirror changes the offset.

    Returns
    -------
    tuple[float, float]
        Offset in the placed box.
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
    """Return one pinned coordinate of a unit's corner or one of its ports.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    axis : str
        ``"x"`` or ``"y"``.
    port_name : str or None
        Port to measure to, or ``None`` for the corner.

    Returns
    -------
    float
        Absolute coordinate.

    Raises
    ------
    ValueError
        If the unit is unpinned or not pinned in pixels on this axis.
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

    Prefer this to ``unit.pin_.x + port_offset(unit, port)[0]``, which
    fails obscurely when the unit is unpinned or pinned by grid rank, and
    pairs index and axis by hand::

        spine_y = pinned_y(column, "feed")     # the nozzle's elevation
        centre_x = pinned_x(tee) + tee_w / 2   # the unit's own corner

    It reads the pin, so it describes the drawing being built; after layout
    use :func:`port_point` on the frame.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    port_name : str or None, optional
        Port to measure to, or ``None`` for the corner.

    Returns
    -------
    float
        Absolute ``x``.

    Raises
    ------
    ValueError
        If the unit is unpinned or not pinned by ``x``.
    """
    return _pinned(unit, "x", port_name)


def pinned_y(unit: "Unit", port_name: str | None = None) -> float:
    """Return the pinned ``y`` of a unit's corner or one of its ports.

    See :func:`pinned_x`.

    Parameters
    ----------
    unit : Unit
        Pinned unit.
    port_name : str or None, optional
        Port to measure to, or ``None`` for the corner.

    Returns
    -------
    float
        Absolute ``y``.

    Raises
    ------
    ValueError
        If the unit is unpinned or not pinned by ``y``.
    """
    return _pinned(unit, "y", port_name)


def pin_intent(unit: "Unit") -> dict[str, tuple[str | None, float]]:
    """Return the pixel coordinates the author pinned, per axis.

    A coordinate measured to a nozzle survives later turns, mirrors,
    resizes and ``nozzle()`` calls; a corner coordinate does not, so the
    two are reported separately. Used by
    :func:`pandid.validate.geometry_issues` and
    :func:`pandid.layout.faces.select_faces`.

    Parameters
    ----------
    unit : Unit
        Unit to read.

    Returns
    -------
    dict[str, tuple[str | None, float]]
        For each pinned pixel axis, the port measured to (``None`` for the
        corner) and the value, such as ``{"y": ("inlet", 440.0)}``. Axes
        placed by grid rank or not pinned are absent.
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
    """Explain why a port named on a pin locates nothing, if it does not.

    One rule for :meth:`pandid.units.Unit.pin` and the spec's ``pin:``: a
    named port must be what some stated coordinate is measured to. Check it
    against the pin the unit will have after the call, not against one
    call's arguments. A grid rank beside the port does not change the
    verdict, only the message.

    Parameters
    ----------
    port_name : str or None
        Port named on the pin.
    axes : Sequence[str]
        Coordinates the port is offered for.
    measured : Collection[str]
        Coordinates actually measured to the port.
    ranks : Collection[str]
        Grid ranks the pin names.
    drop : str
        What the author removes to keep the rest of the pin, such as
        ``port`` or ``port.x``.

    Returns
    -------
    str or None
        Explanation, or ``None`` when the port locates a coordinate.
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
