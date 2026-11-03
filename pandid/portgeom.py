"""Resolve unit sizes and port geometry for layout, routing and drawing.

Functions take the placement as a parameter: a ``Frame``, a ``Pin`` or
the solver's ``_Slot``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from pandid.units import Unit


def _sym(unit: "Unit"):
    """Return the symbol the default registry draws a unit with."""
    from pandid.render.symbols import default_registry
    return default_registry.for_unit(unit)


def _xform(frame) -> tuple[int, bool, bool]:
    """Return a placement's turn and left-right and top-bottom flips."""
    return (int(getattr(frame, "orientation", 0) or 0),
            bool(getattr(frame, "mirrored", False)),
            bool(getattr(frame, "mirror_y", False)))


def symbol_to_box(px: float, py: float, sw: float, sh: float,
                  rot: int = 0, mirror_x: bool = False, mirror_y: bool = False
                  ) -> tuple[float, float, float, float]:
    """Map a point in symbol coordinates into the placed box.

    Mirror first, in the symbol's frame, then turn clockwise by
    ``rot`` degrees. Return ``(x, y, box_w, box_h)``; a quarter turn
    swaps the box size.

    Parameters
    ----------
    sw, sh : float
        Symbol width and height.
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


def ink_box(bw: float, bh: float, w: float, h: float, stretchable: bool = True
            ) -> tuple[float, float, float, float]:
    """Return where a symbol's artwork lands inside its placed box.

    A stretchable symbol fills the box; any other keeps its aspect and
    is centred. Return ``(x, y, width, height)`` from the box's
    top-left corner.

    Parameters
    ----------
    bw, bh : float
        Symbol box, already turned by :func:`symbol_to_box`.
    w, h : float
        Placed box.
    """
    if stretchable:
        return 0.0, 0.0, w, h
    scale = min(w / bw, h / bh)
    iw, ih = bw * scale, bh * scale
    return (w - iw) / 2, (h - ih) / 2, iw, ih


def port_faces(unit: "Unit", port_name: str, placed=None) -> list[str]:
    """Return the faces a port may be drawn on, best first.

    Parameters
    ----------
    placed : Pin, Frame or None, optional
        Placement to answer for; defaults to the unit's pin, then frame.
    """
    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mx, my = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    return list(_drawn_placements(unit, port_name, w, h, rot, mx, my))


def unreachable_face(unit: "Unit", port_name: str, face: str,
                     options: list[str]) -> ValueError:
    """Build the error for a face a port cannot take as drawn."""
    offered = " or ".join(filter(None, [", ".join(options[:-1]), *options[-1:]]))
    return ValueError(
        f"{unit.name}.{port_name} can be piped from {offered} as drawn; "
        f"you asked for {face!r}"
    )


def _drawn_placements(unit: "Unit", port_name: str, w: float, h: float,
                      rot: int, mirrored: bool, mirror_y: bool
                      ) -> dict[str, tuple[float, float]]:
    """Return a port's drawn point on each face it may take, best first.

    Points are relative to the box's top-left corner.
    """
    sym = _sym(unit)
    anchor = unit._symbol_anchor(port_name)
    menu = (getattr(sym, "port_faces", None) or {}).get(anchor)
    if menu:
        coords = list(menu.values())
    elif (placed := _series_point(unit, sym, port_name)) is not None:
        coords = [placed]
    else:
        # An unanchored port falls back to the box centre.
        coords = [sym.ports.get(anchor, (sym.width / 2, sym.height / 2))]
    out: dict[str, tuple[float, float]] = {}
    for px, py in coords:
        if unit.kind in ("feed", "product"):
            # A flag port's y scales with the flag; its x does not.
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
    """Return the symbol point a port series gives a port, or None."""
    series = sym.series_for(port_name) if hasattr(sym, "series_for") else None
    if series is None:
        return None
    port_name = unit._canonical_port_name(port_name)
    members = unit._series_members(series)
    index = members.get(port_name)
    if index is None:
        return None
    return series.placement(index, len(members), sym.width, sym.height,
                            pin=unit._series_pin(port_name),
                            band=sym.bands.get(series.face))


def is_anchored(unit: "Unit", port_name: str) -> bool:
    """Return whether the symbol or a port series places a port."""
    sym = _sym(unit)
    return (unit._symbol_anchor(port_name) in sym.ports
            or _series_point(unit, sym, port_name) is not None)


def unit_box(unit: "Unit", frame) -> tuple[float, float, float, float]:
    """Return a unit's drawn box as ``(x_min, y_min, x_max, y_max)``.

    An unmirrored feed extends left from its port at ``frame.x + 50``.
    """
    if unit.kind == "feed" and not frame.mirrored:
        return (frame.x + 50.0 - frame.w, frame.y, frame.x + 50.0, frame.y + frame.h)
    return (frame.x, frame.y, frame.x + frame.w, frame.y + frame.h)


def tag_width(tag: str) -> float:
    """Return the width of the halo an equipment tag is drawn on."""
    from pandid.render.furniture import script_counts

    narrow, wide, _zero = script_counts(tag)
    return narrow * 6.6 + wide * 12 + 8


def face_point(unit: "Unit", frame, face: str) -> tuple[tuple[float, float],
                                                        tuple[float, float]]:
    """Return a unit box face's midpoint and outward normal.

    ``face`` is ``"N"``, ``"S"``, ``"E"`` or ``"W"``, in any case.
    """
    x0, y0, x1, y1 = unit_box(unit, frame)
    return {
        "N": (((x0 + x1) / 2, y0), (0.0, -1.0)),
        "S": (((x0 + x1) / 2, y1), (0.0, 1.0)),
        "W": ((x0, (y0 + y1) / 2), (-1.0, 0.0)),
        "E": ((x1, (y0 + y1) / 2), (1.0, 0.0)),
    }[face.upper()]


def _flag_reference(unit: "Unit") -> str:
    """Return the off-page reference a boundary flag draws, as text."""
    from pandid.document import _drawn_text

    return _drawn_text(getattr(unit, "reference", None))


def resolve_size(unit: "Unit", placed=None) -> tuple[float, float]:
    """Return the size of a unit's placed box.

    An explicit ``width`` or ``height`` is the final size. A symbol
    size swaps on a quarter turn. A feed or product flag is as wide as
    its tag or off-page reference, at least 80.

    Parameters
    ----------
    unit : Unit
        Unit to size.
    placed : Pin, Frame or None, optional
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
    """Return the face chosen for a port, or None for the symbol's own.

    A face set with ``nozzle()`` wins over the engine's choice on the
    placement.
    """
    port_name = unit._canonical_port_name(port_name)
    explicit = (getattr(unit, "_port_faces", None) or {}).get(port_name)
    if explicit is not None:
        return explicit
    return (getattr(placed, "port_faces", None) or {}).get(port_name)


def _local_port(unit: "Unit", port_name: str, w: float, h: float,
                mirrored: bool, mirror_y: bool, rot: int, want: str | None
                ) -> tuple[str, tuple[float, float]]:
    """Return a port's face and offset from the box's top-left corner.

    Parameters
    ----------
    want : str or None
        Face to use, or ``None`` for the symbol's own.
    """
    placements = _drawn_placements(unit, port_name, w, h, rot, mirrored, mirror_y)
    if want is None:
        return next(iter(placements.items()))
    if want not in placements:
        raise unreachable_face(unit, port_name, want, list(placements))
    return want, placements[want]


class ResolvedPort(NamedTuple):
    """A port's drawn point, box-edge routing anchor and face."""
    point: tuple[float, float]
    anchor: tuple[float, float]
    face: str


def resolve_port(unit: "Unit", frame, port_name: str) -> ResolvedPort:
    """Resolve a port's drawn point, routing anchor and face.

    The anchor is the point projected onto the edge of the placed box. A
    boundary flag's port is the tip of its pennant for both.
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    want = chosen_face(unit, frame, port_name)
    d, (px, py) = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot, want)

    if unit.kind in ("feed", "product"):
        # An unmirrored feed's lead is 50 from the frame origin.
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
    frame : Frame
        Its placement.
    port_name : str
        Port name.

    Returns
    -------
    tuple[float, float]
        Point on the drawing.
    """
    return resolve_port(unit, frame, port_name).point


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Return a port's routing anchor ``x``, ``y`` and face."""
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
    placed : Pin, Frame or None, optional
        Placement whose turn and mirror apply; defaults to the unit's
        pin, then its frame.

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
    """Return one pinned coordinate of a unit's corner or port."""
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

    It reads the pin; after layout use :func:`port_point` on the frame.

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

    Map each pinned pixel axis to the port it is measured to (``None``
    for the corner) and its value, such as ``{"y": ("inlet", 440.0)}``.
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
    """Return why a port named on a pin locates no coordinate, or None.

    Parameters
    ----------
    axes : Sequence[str]
        Coordinates the port is offered for.
    measured : Collection[str]
        Coordinates measured to the port.
    ranks : Collection[str]
        Grid ranks the pin names.
    drop : str
        What the author removes to keep the rest of the pin, such as
        ``port`` or ``port.x``.
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
