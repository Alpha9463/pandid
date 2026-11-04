"""Select the face each movable port is drawn on.

The choice is stored on the unit's resolved frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.routing.visibility import MIN_ESCAPE

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit


def select_faces(fs: "Flowsheet") -> None:
    """Choose a face for every movable port.

    A connected port can move when it has two or more faces and neither
    ``nozzle()`` nor a pin names it. One a ``via()`` line leaves takes
    the face :func:`_frozen` finds.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    """
    from pandid.layout.stages import is_control

    for unit in fs.units:
        frame = unit.frame
        if frame is None:
            continue
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        menus = _menus(unit, frame)
        frozen = _frozen(unit, frame, menus)
        frame.port_faces.update(frozen)
        # Points of fixed ports; no choice may land on a taken point.
        taken = {_point(unit, frame, name) for name in live
                 if name not in menus or name in frozen}
        for name, menu in menus.items():
            target = _reference(unit.ports[name])
            if target is None or name in frozen:
                continue
            face = None
            if not is_control(unit):
                usable = _usable_faces(fs, unit, frame, name, menu)
                face = _best(unit, frame, name, usable, target, taken)
            if face is None:
                face = _best(unit, frame, name, menu, target, taken)
            if face is None:
                # Every face is taken; keep the symbol's placement.
                continue
            frame.port_faces[name] = face
            taken.add(_point(unit, frame, name))


def freeze_faces(fs: "Flowsheet") -> None:
    """Put each movable port a ``via()`` line leaves on the face it leaves from.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    """
    if not fs.auto_faces:
        return
    for unit in fs.units:
        if unit.frame is not None:
            unit.frame.port_faces.update(_frozen(unit, unit.frame, _menus(unit, unit.frame)))


def _menus(unit: "Unit", frame) -> dict[str, list[str]]:
    """Return the faces each movable port may take.

    Parameters
    ----------
    unit : Unit
        Placed unit.
    frame : Frame
        The unit's frame.

    Returns
    -------
    dict[str, list[str]]
        Faces of each connected port with two or more, that neither
        ``nozzle()`` nor a pin names.
    """
    from pandid.portgeom import pin_intent, port_faces

    fixed = {*unit._port_faces, *(port for port, _ in pin_intent(unit).values())}
    return {name: menu for name, port in unit.ports.items()
            if port.stream is not None and name not in fixed
            and len(menu := port_faces(unit, name, frame)) > 1}


def _frozen(unit: "Unit", frame, menus: dict[str, list[str]]) -> dict[str, str]:
    """Return the face each port leaves its ``via()`` line from.

    Parameters
    ----------
    unit : Unit
        Placed unit.
    frame : Frame
        The unit's frame.
    menus : dict[str, list[str]]
        Faces each port may take.

    Returns
    -------
    dict[str, str]
        For each port whose line is drawn by hand, the first face whose
        point or anchor lies within ``_SQUARE_TOL`` of the line's end
        there.
    """
    import math
    from dataclasses import replace

    from pandid.layout.conflicts import _SQUARE_TOL
    from pandid.portgeom import resolve_port

    out = {}
    for name, menu in menus.items():
        port = unit.ports[name]
        stream = port.stream
        route = stream.route if stream is not None else None
        if stream is None or route is None or not route.manual or not route.waypoints:
            continue
        end = route.waypoints[0] if stream.source is port else route.waypoints[-1]
        for face in menu:
            probe = replace(frame, port_faces={**frame.port_faces, name: face})
            resolved = resolve_port(unit, probe, name)
            if min(math.dist(resolved.point, end), math.dist(resolved.anchor, end)) <= _SQUARE_TOL:
                out[name] = face
                break
    return out


def blocked_nozzles(fs: "Flowsheet") -> list[tuple["Unit", str]]:
    """Return the blocked balloon nozzles that may turn.

    A nozzle may turn when neither ``nozzle()`` nor a pin names its
    face.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.

    Returns
    -------
    list[tuple[Unit, str]]
        Each balloon and the name of a nozzle :func:`_blocked` holds for.
    """
    from pandid.layout.stages import is_control
    from pandid.portgeom import pin_intent

    if not fs.auto_faces:
        return []
    out = []
    for unit in fs.units:
        if not is_control(unit):
            continue
        fixed = {*unit._port_faces, *(port for port, _ in pin_intent(unit).values())}
        out += [(unit, name) for name in unit.ports
                if name not in fixed and _blocked(fs, unit, name)]
    return out


def clear_faces(fs: "Flowsheet", unit: "Unit", port_name: str) -> list[str]:
    """Return the faces a blocked nozzle may turn to, cheapest first.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    unit : Unit
        Balloon owning the nozzle.
    port_name : str
        Nozzle to turn.

    Returns
    -------
    list[str]
        Faces clear of what :func:`_blocking` returns, on no point
        another line on the balloon takes, in :func:`_best` order;
        none if the nozzle is not blocked.
    """
    from dataclasses import replace

    from pandid.portgeom import port_faces

    frame = unit.frame
    port = unit.ports[port_name]
    target = _reference(port)
    if frame is None or target is None or not _blocked(fs, unit, port_name):
        return []
    blocking = _blocking(fs, port)
    menu = [face for face in port_faces(unit, port_name, frame) if _clear(
        unit, replace(frame, port_faces={**frame.port_faces, port_name: face}),
        port_name, blocking)]
    taken = {_point(unit, frame, name) for name, other in unit.ports.items()
             if other.stream is not None and name != port_name}
    order: list[str] = []
    while (face := _best(unit, replace(frame, port_faces=dict(frame.port_faces)),
                         port_name, menu, target, taken)) is not None:
        order.append(face)
        menu.remove(face)
    return order


def _blocked(fs: "Flowsheet", unit: "Unit", port_name: str) -> bool:
    """Return whether the router gave up on a line at a blocked nozzle.

    Parameters
    ----------
    fs : Flowsheet
        Routed sheet.
    unit : Unit
        Unit owning the nozzle.
    port_name : str
        Nozzle to test.

    Returns
    -------
    bool
        True if the nozzle's automatic line takes the fallback path and
        its outward stub enters a box :func:`_blocking` returns.
    """
    port = unit.ports[port_name]
    route = port.stream.route if port.stream is not None else None
    if unit.frame is None or route is None or route.manual or not route.used_fallback:
        return False
    return not _clear(unit, unit.frame, port_name, _blocking(fs, port))


def _blocking(fs: "Flowsheet", port: "Port") -> list[tuple[float, float, float, float]]:
    """Return the boxes a balloon nozzle's outward stub must miss.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    port : Port
        Connected nozzle.

    Returns
    -------
    list[tuple[float, float, float, float]]
        Bodies of units other than its own and its line's other end,
        and tag halos of units other than its own.
    """
    from pandid.portgeom import unit_box
    from pandid.routing.visibility import _tag_halo

    stream = port.stream
    assert stream is not None
    far = (stream.dest if stream.source is port else stream.source).owner
    out = []
    for u in fs.units:
        if u.frame is None or u is port.owner:
            continue
        if u is not far:
            out.append(unit_box(u, u.frame))
        halo = _tag_halo(u, u.frame)
        if halo is not None:
            out.append((halo.x_min, halo.y_min, halo.x_max, halo.y_max))
    return out


def _clear(unit: "Unit", frame, port_name: str,
           boxes: list[tuple[float, float, float, float]]) -> bool:
    """Return whether a port's outward stub misses every box.

    Parameters
    ----------
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame, with the face to test.
    port_name : str
        Port to test.
    boxes : list[tuple[float, float, float, float]]
        Boxes as left, top, right, bottom.

    Returns
    -------
    bool
        True if the stub, :data:`MIN_ESCAPE` long, enters no box.
    """
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import face_point, resolve_port

    _, anchor, landed = resolve_port(unit, frame, port_name)
    normal = face_point(unit, frame, landed)[1]
    tip = (anchor[0] + MIN_ESCAPE * normal[0], anchor[1] + MIN_ESCAPE * normal[1])
    return not any(segment_crosses_box(anchor, tip, box) for box in boxes)


def _usable_faces(fs: "Flowsheet", unit: "Unit", frame, port_name: str,
                  menu: list[str]) -> list[str]:
    """Return the clear faces, dropping any that add bends.

    A face is clear when its outward stub misses every unattached unit
    but the peer; with none clear, the menu comes back unchanged. If
    the first face is clear and the peer's face is fixed, faces needing
    more bends than the first are dropped.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame.
    port_name : str
        Port to choose a face for.
    menu : list[str]
        Faces the port may take.

    Returns
    -------
    list[str]
        Usable faces, in menu order.
    """
    from pandid.layout.attach import is_attached
    from pandid.portgeom import port_faces, resolve_port, unit_box
    from pandid.routing.metrics import min_bends

    port = unit.ports[port_name]
    stream = port.stream
    assert stream is not None
    peer = stream.dest if stream.source is port else stream.source
    owner = peer.owner
    boxes = [
        unit_box(other, other.frame)
        for other in fs.units
        if other is not unit and other is not owner and other.frame is not None
        and not is_attached(other)
    ]
    fixed_peer = (
        resolve_port(owner, owner.frame, peer.name)
        if owner.frame is not None
        and len(port_faces(owner, peer.name, owner.frame)) == 1
        else None
    )
    clear: list[str] = []
    bends: dict[str, int | None] = {}
    for face in menu:
        frame.port_faces[port_name] = face
        if _clear(unit, frame, port_name, boxes):
            clear.append(face)
        _, anchor, landed = resolve_port(unit, frame, port_name)
        bends[face] = (
            None if fixed_peer is None
            else min_bends(anchor, landed, fixed_peer.anchor, fixed_peer.face)
        )
    frame.port_faces.pop(port_name, None)
    if not clear:
        return menu
    home = bends[clear[0]] if clear[0] == menu[0] else None
    if home is None:
        return clear
    usable: list[str] = []
    for face in clear:
        needed = bends[face]
        if face == menu[0] or (needed is not None and needed <= home):
            usable.append(face)
    return usable


def _point(unit: "Unit", frame, port_name: str) -> tuple[float, ...]:
    """Return a port's drawn point, rounded to three decimals.

    Parameters
    ----------
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame.
    port_name : str
        Port to locate.

    Returns
    -------
    tuple[float, ...]
        Rounded point.
    """
    from pandid.portgeom import resolve_port

    return tuple(round(v, 3) for v in resolve_port(unit, frame, port_name).point)


def _reference(port: "Port") -> tuple[float, float] | None:
    """Return the point a port's faces are scored against, or None.

    This is the peer's nozzle anchor if that nozzle has one face, else
    the centre of the peer unit.

    Parameters
    ----------
    port : Port
        Connected port.

    Returns
    -------
    tuple[float, float] or None
        Target, or None if the port is unconnected or its peer unplaced.
    """
    from pandid.portgeom import port_faces, resolve_port, unit_box

    stream = port.stream
    if stream is None:
        return None
    peer = stream.dest if stream.source is port else stream.source
    owner = peer.owner
    if owner.frame is None:
        return None
    if len(port_faces(owner, peer.name, owner.frame)) == 1:
        return resolve_port(owner, owner.frame, peer.name).anchor
    x0, y0, x1, y1 = unit_box(owner, owner.frame)
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _best(unit: "Unit", frame, port_name: str, menu: list[str],
          target: tuple[float, float], taken: set[tuple[float, ...]]) -> str | None:
    """Return the cheapest untaken face toward the target, or None.

    Parameters
    ----------
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame.
    port_name : str
        Port to choose a face for.
    menu : list[str]
        Faces to score.
    target : tuple[float, float]
        Point the port should face.
    taken : set[tuple[float, ...]]
        Rounded points already used by other ports.

    Returns
    -------
    str or None
        Best face, or None if every face lands on a taken point.
    """
    from pandid.portgeom import face_point, resolve_port, unit_box

    x0, y0, x1, y1 = unit_box(unit, frame)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    scored = []
    for rank, face in enumerate(menu):
        frame.port_faces[port_name] = face
        point, anchor, landed = resolve_port(unit, frame, port_name)
        if tuple(round(v, 3) for v in point) in taken:
            continue
        normal = face_point(unit, frame, landed)[1]
        # Cost the Manhattan distance, plus a penalty for facing away.
        dx, dy = target[0] - anchor[0], target[1] - anchor[1]
        facing = dx * normal[0] + dy * normal[1] >= 0.0
        cost = abs(dx) + abs(dy) + (0.0 if facing else 2.0 * MIN_ESCAPE)
        # Order by cost, then aim, then symbol preference.
        aim = (target[0] - centre[0]) * normal[0] + (target[1] - centre[1]) * normal[1]
        scored.append((cost, -aim, rank, face))
    frame.port_faces.pop(port_name, None)
    return min(scored)[-1] if scored else None
