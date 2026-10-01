"""Select which declared placement each movable port is drawn on.

This module states a policy only. Coordinates come from
:mod:`pandid.portgeom`.

Selection runs after coordinate assignment has placed every box, because a
face is judged against where the peer landed, and before labels, routing,
and rendering read a face. The choice is stored on the resolved
:class:`~pandid.geometry.Frame`, which each layout run replaces, so placement
passes never read a previous choice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

#: Router stand-off from a nozzle. A face pointing away from its peer costs
#: twice this distance.
_ESCAPE = 25.0


def eligible_faces(fs: "Flowsheet", unit: "Unit", port_name: str) -> tuple[str, ...]:
    """List automatic face choices for a connected port.

    Parameters
    ----------
    fs : Flowsheet
        Drawing whose automatic-face setting controls selection.
    unit : Unit
        Owner of the port.
    port_name : str
        Canonical connected port name.

    Returns
    -------
    tuple[str, ...]
        Drawn-space alternatives in symbol preference order. Author
        nozzles, pinned nozzles, and fixed ports have no alternatives.
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
    """Choose a face for every movable port without author overrides.

    Parameters
    ----------
    fs : Flowsheet
        Placed drawing whose resolved frame faces are updated.
    preferred : Mapping[tuple[int, str], str] or None, optional
        Trial-only preferences keyed by global unit index and port name.
        Unavailable or occupied choices fall back to normal selection.

    Returns
    -------
    None
        Automatic selections are stored on each resolved frame.
    """
    from pandid.layout.stages import is_control

    for index, unit in enumerate(fs.units):
        frame = unit.frame
        if frame is None:
            continue
        # Clear earlier choices so selection depends on the sheet alone.
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        # ``eligible_faces`` excludes pinned and author-chosen nozzles: a pin
        # fixes the box from the nozzle position, so a later choice would move
        # the nozzle off its pin.
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        menus = {name: menu for name in live
                 if (menu := eligible_faces(fs, unit, name))}
        # Record the points of fixed ports. Ports are served in declaration
        # order and no choice may land on a taken point; two connections on
        # one point is a validation error.
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
                continue  # Every face is taken; keep the symbol's placement.
            frame.port_faces[name] = face
            taken.add(_point(unit, frame, name))


def _usable_faces(fs: "Flowsheet", unit: "Unit", frame, port_name: str,
                  menu: list[str]) -> list[str]:
    """Drop faces that are blocked or need more bends than the home face.

    A face is blocked when its outward stub crosses another unit. When the
    peer's nozzle is fixed, an alternate face is also dropped if it needs
    more bends than the first face of the menu. The menu is returned
    unchanged when every face is blocked.

    Parameters
    ----------
    fs : Flowsheet
        Placed drawing.
    unit : Unit
        Owner of the port.
    frame : Frame
        Resolved frame of the unit.
    port_name : str
        Connected port with more than one declared face.
    menu : list[str]
        Declared faces in symbol preference order.

    Returns
    -------
    list[str]
        Usable faces in the same order.
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
    """Return a port's drawn point, rounded for coincidence checks.

    Parameters
    ----------
    unit : Unit
        Owner of the port.
    frame : Frame
        Resolved frame of the unit.
    port_name : str
        Port to resolve.

    Returns
    -------
    tuple[float, ...]
        Point coordinates rounded to three decimals.
    """
    from pandid.portgeom import resolve_port

    return tuple(round(v, 3) for v in resolve_port(unit, frame, port_name).point)


def _reference(port: "Port") -> tuple[float, float] | None:
    """Return the point a candidate face is scored against.

    A peer with one declared face gives its nozzle anchor. A peer with
    several gives the centre of its unit, which does not depend on the face
    it later takes.

    Parameters
    ----------
    port : Port
        Connected port being placed.

    Returns
    -------
    tuple[float, float] or None
        Target point, or ``None`` when the peer is unplaced.
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
    """Return the cheapest untaken face for a run to the target.

    Ties go to the face aimed most directly at the peer, then to the
    symbol's preference order.

    Parameters
    ----------
    unit : Unit
        Owner of the port.
    frame : Frame
        Resolved frame of the unit.
    port_name : str
        Port being placed.
    menu : list[str]
        Candidate faces in symbol preference order.
    target : tuple[float, float]
        Point the run must reach.
    taken : set[tuple[float, ...]]
        Points already used by other connected ports.

    Returns
    -------
    str or None
        Chosen face, or ``None`` when every candidate point is taken.
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
    """Return the orthogonal run length plus a penalty for facing away.

    Parameters
    ----------
    anchor : tuple[float, float]
        Port anchor on the candidate face.
    normal : tuple[float, float]
        Outward normal of that face.
    target : tuple[float, float]
        Point the run must reach.

    Returns
    -------
    float
        Manhattan distance, plus twice the stand-off when the target lies
        behind the face.
    """
    (ax, ay), (nx, ny), (tx, ty) = anchor, normal, target
    reach = (tx - ax) * nx + (ty - ay) * ny
    return abs(tx - ax) + abs(ty - ay) + (0.0 if reach >= 0.0 else 2.0 * _ESCAPE)


def _aim(centre: tuple[float, float], normal: tuple[float, float],
         target: tuple[float, float]) -> float:
    """Return how directly a face's outward normal points at the target.

    Parameters
    ----------
    centre : tuple[float, float]
        Centre of the unit's drawn box.
    normal : tuple[float, float]
        Outward normal of the candidate face.
    target : tuple[float, float]
        Point the run must reach.

    Returns
    -------
    float
        Projection of the centre-to-target vector on the normal.
    """
    return (target[0] - centre[0]) * normal[0] + (target[1] - centre[1]) * normal[1]
