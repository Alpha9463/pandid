"""Select the face each movable port is drawn on.

The choice is stored on the unit's resolved frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

#: Router stand-off from a nozzle.
_ESCAPE = 25.0


def eligible_faces(fs: "Flowsheet", unit: "Unit", port_name: str) -> tuple[str, ...]:
    """Return the faces a connected port may move between, or ``()``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being laid out.
    unit : Unit
        Unit owning the port.
    port_name : str
        Canonical port name.

    Returns
    -------
    tuple[str, ...]
        Two or more faces, or ``()`` if the port's face cannot move.
    """
    from pandid.portgeom import pin_intent, port_faces

    frame = unit.frame
    if not fs.auto_faces or frame is None or unit.ports[port_name].stream is None:
        return ()
    if port_name in unit._port_faces:
        return ()
    if any(port_name == port for port, _ in pin_intent(unit).values()):
        return ()
    menu = tuple(port_faces(unit, port_name, frame))
    return menu if len(menu) > 1 else ()


def select_faces(
    fs: "Flowsheet",
    preferred: Mapping[tuple[int, str], str] | None = None,
) -> None:
    """Choose a face for every movable port.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    preferred : Mapping[tuple[int, str], str] or None, optional
        Face to try first, keyed by unit index and port name.
    """
    from pandid.layout.stages import is_control

    for index, unit in enumerate(fs.units):
        frame = unit.frame
        if frame is None:
            continue
        # Clear earlier choices.
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        menus = {name: menu for name in live
                 if (menu := eligible_faces(fs, unit, name))}
        # Points of fixed ports; no choice may land on a taken point.
        taken = {_point(unit, frame, name) for name in live if name not in menus}
        for name, menu in menus.items():
            target = _reference(unit.ports[name])
            if target is None:
                continue
            preferred_face = None if preferred is None else preferred.get((index, name))
            face = (_best(unit, frame, name, [preferred_face], target, taken)
                    if preferred_face in menu else None)
            if face is None and not is_control(unit):
                usable = _usable_faces(fs, unit, frame, name, list(menu))
                face = _best(unit, frame, name, usable, target, taken)
            if face is None:
                face = _best(unit, frame, name, list(menu), target, taken)
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
        tip = (anchor[0] + _ESCAPE * normal[0], anchor[1] + _ESCAPE * normal[1])
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
        # Order by cost, then aim, then symbol preference.
        scored.append((_cost(anchor, normal, target), -_aim(centre, normal, target),
                       rank, face))
    frame.port_faces.pop(port_name, None)
    return min(scored)[-1] if scored else None


def _cost(anchor: tuple[float, float], normal: tuple[float, float],
          target: tuple[float, float]) -> float:
    """Return the Manhattan distance, plus a penalty for facing away.

    Parameters
    ----------
    anchor : tuple[float, float]
        Nozzle anchor.
    normal : tuple[float, float]
        Outward face normal.
    target : tuple[float, float]
        Point the port should face.

    Returns
    -------
    float
        Cost of the face.
    """
    (ax, ay), (nx, ny), (tx, ty) = anchor, normal, target
    reach = (tx - ax) * nx + (ty - ay) * ny
    return abs(tx - ax) + abs(ty - ay) + (0.0 if reach >= 0.0 else 2.0 * _ESCAPE)


def _aim(centre: tuple[float, float], normal: tuple[float, float],
         target: tuple[float, float]) -> float:
    """Return the centre-to-target vector projected on a face normal.

    Parameters
    ----------
    centre : tuple[float, float]
        Centre of the unit box.
    normal : tuple[float, float]
        Outward face normal.
    target : tuple[float, float]
        Point the port should face.

    Returns
    -------
    float
        Projection length.
    """
    return (target[0] - centre[0]) * normal[0] + (target[1] - centre[1]) * normal[1]
