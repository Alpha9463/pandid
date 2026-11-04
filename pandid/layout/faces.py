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
    ``nozzle()`` nor a pin names it.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    """
    from pandid.layout.stages import is_control
    from pandid.portgeom import pin_intent, port_faces

    for unit in fs.units:
        frame = unit.frame
        if frame is None:
            continue
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        fixed = {*unit._port_faces, *(port for port, _ in pin_intent(unit).values())}
        menus = {name: menu for name in live if name not in fixed
                 and len(menu := port_faces(unit, name, frame)) > 1}
        # Points of fixed ports; no choice may land on a taken point.
        taken = {_point(unit, frame, name) for name in live if name not in menus}
        for name, menu in menus.items():
            target = _reference(unit.ports[name])
            if target is None:
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
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import face_point, port_faces, resolve_port, unit_box
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
        if owner is not None and owner.frame is not None
        and len(port_faces(owner, peer.name, owner.frame)) == 1
        else None
    )
    clear: list[str] = []
    bends: dict[str, int | None] = {}
    for face in menu:
        frame.port_faces[port_name] = face
        _, anchor, landed = resolve_port(unit, frame, port_name)
        normal = face_point(unit, frame, landed)[1]
        tip = (anchor[0] + MIN_ESCAPE * normal[0], anchor[1] + MIN_ESCAPE * normal[1])
        if not any(segment_crosses_box(anchor, tip, box) for box in boxes):
            clear.append(face)
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
    if owner is None or owner.frame is None:
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
