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


def resolve_size(unit: "Unit") -> tuple[float, float]:
    """Intrinsic (w, h) of a unit.

    Explicit ``width``/``height`` win; otherwise the symbol default is used.
    Feed/Product get a dynamic width sized to their label text.
    """
    sym = _sym(unit)
    h = unit.height if unit.height is not None else sym.height
    if unit.kind in ("feed", "product"):
        w = unit.width if unit.width is not None else max(80.0, len(unit.name) * 8.0 + 30.0)
    else:
        w = unit.width if unit.width is not None else sym.width
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
                mirrored: bool) -> tuple[float, float]:
    """Port position in the symbol's own coordinates, mirror + scale applied.

    Returns coordinates relative to the unit's top-left, in resolved pixels.
    """
    sym = _sym(unit)
    px, py = sym.ports.get(port_name, (sym.width / 2, sym.height / 2))
    if mirrored:
        px = sym.width - px
    if unit.kind not in ("feed", "product"):
        px *= w / sym.width
        py *= h / sym.height
    return px, py


def port_point(unit: "Unit", frame, port_name: str) -> tuple[float, float]:
    """Absolute (x, y) where a stream visually attaches to the port nozzle.

    This is the endpoint the renderer draws to. Feed/Product use their special
    arrow-tip convention (the port sits at the tip, whichever way it points).
    """
    w, h, mirrored = frame.w, frame.h, frame.mirrored
    _, py = _local_port(unit, port_name, w, h, mirrored)
    if unit.kind == "feed":
        ax = frame.x if mirrored else frame.x + 50.0
        return ax, frame.y + py
    if unit.kind == "product":
        ax = frame.x + w if mirrored else frame.x
        return ax, frame.y + py
    px, _ = _local_port(unit, port_name, w, h, mirrored)
    return frame.x + px, frame.y + py


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Absolute routing anchor for a port: (x, y, outward_dir).

    For process units the anchor is projected onto the bounding-box edge the
    port faces, so the visibility grid and the router agree on where a path
    leaves/enters a unit. Feed/Product anchor at their arrow tip.
    """
    w, h, mirrored = frame.w, frame.h, frame.mirrored
    px, py = _local_port(unit, port_name, w, h, mirrored)
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
