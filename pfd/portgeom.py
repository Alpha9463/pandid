"""Single source of truth for unit sizing and port geometry.

Layout, routing, and rendering all resolve a unit's size and its port positions
*here*, so the drawn diagram and the routed paths can never disagree. (The class
of bug this prevents: the renderer forgetting the mirror flip that the router
applied, which left mirrored units' streams visually disconnected.)

:func:`resolve_port` is the single authority: it answers a port's drawn point,
its routing anchor and its face together, and everything else here is a wrapper
over it. Deriving any one of the three somewhere else is the bug.

All functions take a resolved box explicitly (``w``, ``h``, ``mirrored``) rather
than reading ``unit.frame``, so they work both during layout (on a ``_Slot``)
and afterwards (on a ``Frame``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

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


def port_faces(unit: "Unit", port_name: str, placed=None) -> list[str]:
    """Faces this port may be piped from *as drawn*, most-preferred first.

    The symbol authors an exact coordinate per face, so an alternate placement
    still lands on drawn ink. Answers in the same frame of reference as
    :meth:`pfd.units.Unit.nozzle` takes its argument, which is why it has to
    apply the mirror the way :func:`resolve_port` does rather than report the
    symbol's own faces.

    ``placed`` is the placement to answer for — a :class:`~pfd.geometry.Pin` or
    :class:`~pfd.geometry.Frame`. It defaults to the unit's own, preferring the
    *pin* over the frame: the transform is intent, which layout copies onto the
    frame, so a ``pin()`` already made describes the sheet that is coming rather
    than the one it replaces. A caller about to change the pin must pass its
    candidate, since answering from the committed one answers about a sheet that
    is on its way out.
    """
    if port_name not in _sym(unit).ports:
        return []
    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mx, my = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    return list(_drawn_placements(unit, port_name, w, h, rot, mx, my))


def unreachable_face(unit: "Unit", port_name: str, face: str,
                     options: list[str]) -> ValueError:
    """The error for a face this port cannot be put on under its transform.

    Built here so the message :meth:`pfd.units.Unit.nozzle` raises up front and
    the one the resolver raises later are the same sentence about the same rule.
    """
    offered = " or ".join(filter(None, [", ".join(options[:-1]), *options[-1:]]))
    return ValueError(
        f"{unit.name}.{port_name} can be piped from {offered or 'nowhere'} as "
        f"drawn; you asked for {face!r}"
    )


def _drawn_placements(unit: "Unit", port_name: str, w: float, h: float,
                      rot: int, mirrored: bool, mirror_y: bool
                      ) -> dict[str, tuple[float, float]]:
    """Every declared placement of a port, keyed by the face it lands on as drawn.

    The menu is authored in the symbol's own frame; mapping it through the
    placement transform *here* is what lets a caller name a face on the finished
    sheet without redoing the mirror arithmetic. Coordinates come back relative
    to the unit's top-left, in resolved pixels. Two placements can collapse onto
    one face after a quarter turn, in which case the more-preferred one wins.
    """
    sym = _sym(unit)
    menu = (getattr(sym, "port_faces", None) or {}).get(port_name)
    # A port the symbol does not anchor falls back to the centre of the box.
    coords = list(menu.values()) if menu else [
        sym.ports.get(port_name, (sym.width / 2, sym.height / 2))]
    out: dict[str, tuple[float, float]] = {}
    for px, py in coords:
        if unit.kind in ("feed", "product"):
            # Boundary flags are drawn directly, not from the symbol box.
            lx, ly = (sym.width - px if mirrored else px), py
        else:
            bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height,
                                           rot, mirrored, mirror_y)
            lx, ly = bx * w / bw, by * h / bh
        out.setdefault(outward_dir(lx, ly, w, h, unit.kind, port_name, mirrored), (lx, ly))
    return out


def is_anchored(unit: "Unit", port_name: str) -> bool:
    """True when the symbol authors a coordinate for this port.

    An unanchored port — a ``Mixer``'s third inlet, past the two its symbol
    draws — falls back to the centre of the box, so any two of them land on the
    same point by construction. That is a gap in the symbol rather than a
    placement, and callers that police collisions have to tell the two apart.
    """
    return port_name in _sym(unit).ports


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


def resolve_size(unit: "Unit", placed=None) -> tuple[float, float]:
    """Intrinsic (w, h) of a unit's placed box.

    Explicit ``width``/``height`` win and are taken as the *final* box, so a
    caller who sizes a rotated unit gets exactly what they asked for. Symbol
    defaults are swapped by a quarter turn. Feed/Product get a dynamic width
    sized to their label text.

    ``placed`` names the placement whose quarter turn decides that swap, and
    defaults to the unit's pin; a caller weighing a placement it has not
    committed passes the candidate.
    """
    sym = _sym(unit)
    if unit.kind in ("feed", "product"):
        # Boundary flag: size to the wider of the name or the off-page reference
        # (drawn as the connector's second line), so neither overflows the flag.
        text_len = max(len(unit.name), len(getattr(unit, "reference", "") or ""))
        w = unit.width if unit.width is not None else max(80.0, text_len * 8.0 + 30.0)
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


def _local_port(unit: "Unit", port_name: str, w: float, h: float,
                mirrored: bool, mirror_y: bool = False, rot: int = 0
                ) -> tuple[float, float]:
    """Port position relative to the unit's top-left, in resolved pixels.

    Takes the placement whose drawn face the caller asked for through
    :meth:`pfd.units.Unit.nozzle`, else the symbol's own nozzle — which is the
    menu's first entry, since the whole point of folding the home in is that
    there is no second place to look.

    A face that *was* chosen and this transform cannot reach raises. Falling
    back to the home nozzle instead is what let a rotation applied after the
    choice move the stream to the far side of the unit with nobody saying so:
    every guard upstream of here can be defeated by a later ``pin()``, but this
    is the call that decides where the ink goes.
    """
    placements = _drawn_placements(unit, port_name, w, h, rot, mirrored, mirror_y)
    want = (getattr(unit, "_port_faces", None) or {}).get(port_name)
    if want is None:
        return next(iter(placements.values()))
    if want not in placements:
        raise unreachable_face(unit, port_name, want, list(placements))
    return placements[want]


class ResolvedPort(NamedTuple):
    """Where a port is drawn, where a path meets it, and which way it faces."""
    point: tuple[float, float]
    anchor: tuple[float, float]
    face: str


def resolve_port(unit: "Unit", frame, port_name: str) -> ResolvedPort:
    """Resolve a port's drawn geometry: nozzle point, routing anchor and face.

    All three together, because deriving one of them somewhere else is how the
    renderer and the router came to disagree in the first place. The anchor is
    the point projected onto the bounding-box edge the port faces, so the
    visibility grid and the router leave a unit where the ink does; Feed/Product
    use their arrow-tip convention for both (the port sits at the tip, whichever
    way it points).
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    px, py = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot)
    d = outward_dir(px, py, w, h, unit.kind, port_name, mirrored)

    if unit.kind in ("feed", "product"):
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
    """Absolute (x, y) where a stream visually attaches to the port nozzle.

    This is the endpoint the renderer draws to.
    """
    return resolve_port(unit, frame, port_name).point


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Absolute routing anchor for a port: (x, y, outward_dir)."""
    _, (ax, ay), d = resolve_port(unit, frame, port_name)
    return ax, ay, d
