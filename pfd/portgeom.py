"""Single source of truth for unit sizing and port geometry.

Layout, routing, and rendering all resolve a unit's size and its port positions
*here*, so the drawn diagram and the routed paths can never disagree. (The class
of bug this prevents: the renderer forgetting the mirror flip that the router
applied, which left mirrored units' streams visually disconnected.)

All functions take a resolved box explicitly (``w``, ``h``, ``mirrored``) rather
than reading ``unit.frame``, so they work both during layout (on a ``_Slot``)
and afterwards (on a ``Frame``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.units import Unit


def _sym(unit: "Unit"):
    from pfd.render.symbols import default_registry
    return default_registry.get(unit.kind, getattr(unit, "variant", "default"))


def _xform(frame) -> tuple[int, bool, bool]:
    """Read (orientation, mirror_x, mirror_y) off a Frame or _Slot."""
    return (int(getattr(frame, "orientation", 0) or 0),
            bool(getattr(frame, "mirrored", False)),
            bool(getattr(frame, "mirror_y", False)))


def symbol_to_box(px: float, py: float, sw: float, sh: float,
                  rot: int = 0, mirror_x: bool = False, mirror_y: bool = False
                  ) -> tuple[float, float, float, float]:
    """Map a point from a symbol's own coordinates into its *placed* box.

    Mirroring is applied first (in the symbol's frame), then the clockwise
    quarter turn — the same order the renderer's SVG transform composes in, so
    ports and artwork can never drift apart. Returns ``(x, y, box_w, box_h)``;
    a quarter turn swaps the box's width and height.
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


def port_faces(unit: "Unit", port_name: str) -> list[str]:
    """Faces this port may be moved to, most-preferred first.

    The first entry is the symbol's own default. Extra faces come from the
    symbol's ``port_alts``, which give an exact coordinate per face so an
    alternate placement still lands on drawn ink.
    """
    sym = _sym(unit)
    if port_name not in sym.ports:
        return []
    rot, mx, my = _xform(unit.frame) if unit.frame is not None else (0, False, False)
    faces = []
    for face, (px, py) in _face_options(unit, port_name).items():
        bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height, rot, mx, my)
        faces.append((face, outward_dir(bx, by, bw, bh, unit.kind, port_name)))
    # de-duplicate while keeping order (two alts can land on one face once rotated)
    seen, out = set(), []
    for _, d in faces:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _face_options(unit: "Unit", port_name: str) -> dict:
    """``{face_key: (x, y)}`` for a port: its default plus any declared alts."""
    sym = _sym(unit)
    opts = {"_default": sym.ports[port_name]}
    alts = getattr(sym, "port_alts", None) or {}
    for face, xy in (alts.get(port_name) or {}).items():
        opts[face] = xy
    return opts


def unit_box(unit: "Unit", frame) -> tuple[float, float, float, float]:
    """True drawn bounding box (x_min, y_min, x_max, y_max) of a unit.

    A non-mirrored Feed keeps its port at ``frame.x + 50`` with the box extending
    left from there; everything else spans ``frame.x .. frame.x + w``.
    """
    if unit.kind == "feed" and not frame.mirrored:
        return (frame.x + 50.0 - frame.w, frame.y, frame.x + 50.0, frame.y + frame.h)
    return (frame.x, frame.y, frame.x + frame.w, frame.y + frame.h)


def face_point(unit: "Unit", frame, face: str) -> tuple[tuple[float, float],
                                                        tuple[float, float]]:
    """Midpoint of one face of a unit's drawn box, and that face's outward normal.

    The tap point for an instrument mounted on equipment. Read off the same
    :func:`unit_box` the router treats as the obstacle, so a bubble hung on the
    east face sits against the same edge a stream would leave from.
    """
    x0, y0, x1, y1 = unit_box(unit, frame)
    return {
        "N": (((x0 + x1) / 2, y0), (0.0, -1.0)),
        "S": (((x0 + x1) / 2, y1), (0.0, 1.0)),
        "W": ((x0, (y0 + y1) / 2), (-1.0, 0.0)),
        "E": ((x1, (y0 + y1) / 2), (1.0, 0.0)),
    }[face.upper()]


def resolve_size(unit: "Unit") -> tuple[float, float]:
    """Intrinsic (w, h) of a unit's placed box.

    Explicit ``width``/``height`` win and are taken as the *final* box, so a
    caller who sizes a rotated unit gets exactly what they asked for. Symbol
    defaults are swapped by a quarter turn. Feed/Product get a dynamic width
    sized to their label text.
    """
    sym = _sym(unit)
    if unit.kind in ("feed", "product"):
        # Boundary flag: size to the wider of the name or the off-page reference
        # (drawn as the connector's second line), so neither overflows the flag.
        text_len = max(len(unit.name), len(getattr(unit, "reference", "") or ""))
        w = unit.width if unit.width is not None else max(80.0, text_len * 8.0 + 30.0)
        return w, unit.height if unit.height is not None else sym.height

    sym_w, sym_h = sym.width, sym.height
    pin = getattr(unit, "pin_", None)
    if pin is not None and int(getattr(pin, "orientation", 0) or 0) in (90, 270):
        sym_w, sym_h = sym_h, sym_w
    w = unit.width if unit.width is not None else sym_w
    h = unit.height if unit.height is not None else sym_h
    return w, h


def outward_dir(px: float, py: float, w: float, h: float,
                kind: str = "", port_name: str = "", mirrored: bool = False) -> str:
    """Outward normal ("N"/"S"/"E"/"W") for a port at local (px, py) in a w×h box."""
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


def _symbol_port(unit: "Unit", port_name: str) -> tuple[float, float]:
    """The port's coordinate in symbol space, honouring any face override."""
    sym = _sym(unit)
    face = (getattr(unit, "_port_faces", None) or {}).get(port_name)
    if face is not None:
        alt = (getattr(sym, "port_alts", None) or {}).get(port_name) or {}
        if face in alt:
            return alt[face]
    return sym.ports.get(port_name, (sym.width / 2, sym.height / 2))


def _local_port(unit: "Unit", port_name: str, w: float, h: float,
                mirrored: bool, mirror_y: bool = False, rot: int = 0
                ) -> tuple[float, float]:
    """Port position relative to the unit's top-left, in resolved pixels.

    Applies the face override, then the symbol→box transform (mirror, then
    quarter turn), then scales into the resolved box.
    """
    sym = _sym(unit)
    px, py = _symbol_port(unit, port_name)
    if unit.kind in ("feed", "product"):
        # Boundary flags are drawn directly, not from the symbol box.
        return (sym.width - px if mirrored else px), py
    bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height, rot, mirrored, mirror_y)
    return bx * w / bw, by * h / bh


def port_point(unit: "Unit", frame, port_name: str) -> tuple[float, float]:
    """Absolute (x, y) where a stream visually attaches to the port nozzle.

    This is the endpoint the renderer draws to. Feed/Product use their special
    arrow-tip convention (the port sits at the tip, whichever way it points).
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    _, py = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot)
    if unit.kind == "feed":
        ax = frame.x if mirrored else frame.x + 50.0
        return ax, frame.y + py
    if unit.kind == "product":
        ax = frame.x + w if mirrored else frame.x
        return ax, frame.y + py
    px, _ = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot)
    return frame.x + px, frame.y + py


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Absolute routing anchor for a port: (x, y, outward_dir).

    For process units the anchor is projected onto the bounding-box edge the
    port faces, so the visibility grid and the router agree on where a path
    leaves/enters a unit. Feed/Product anchor at their arrow tip.
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    px, py = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot)
    d = outward_dir(px, py, w, h, unit.kind, port_name, mirrored)

    if unit.kind == "feed":
        ax = frame.x if mirrored else frame.x + 50.0
        return ax, frame.y + py, d
    if unit.kind == "product":
        ax = frame.x + w if mirrored else frame.x
        return ax, frame.y + py, d

    ax, ay = frame.x + px, frame.y + py
    if d == "N":
        ay = frame.y
    elif d == "S":
        ay = frame.y + h
    elif d == "W":
        ax = frame.x
    elif d == "E":
        ax = frame.x + w
    return ax, ay, d
