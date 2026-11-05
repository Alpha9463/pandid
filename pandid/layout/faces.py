"""Select the face each movable port is drawn on.

The choice is stored on the unit's resolved frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.routing.visibility import MIN_ESCAPE

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit, _FaceFamilies


def select_faces(fs: "Flowsheet") -> None:
    """Choose a face for every movable port.

    A connected port can move when it has two or more faces and neither
    ``nozzle()``, a list of faces nor a pin names it. A block, tank or
    vessel connection that shares its family's faces moves only where
    that saves its family bends.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    """
    from pandid.layout.stages import is_control
    from pandid.portgeom import pin_intent, port_faces
    from pandid.units import _FaceFamilies

    for unit in fs.units:
        frame = unit.frame
        if frame is None:
            continue
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        fixed = {*unit._port_faces, *getattr(unit, "_stated", ()),
                 *(port for port, _ in pin_intent(unit).values())}
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
        if isinstance(unit, _FaceFamilies) and fs._family_faces:
            members = [name for name in unit._faces
                       if name in live and name not in fixed and name not in menus]
            _choose_family_faces(fs, unit, frame, members)


def _choose_family_faces(fs: "Flowsheet", unit: "_FaceFamilies", frame,
                         members: list[str]) -> None:
    """Move each family port whose move saves its family bends.

    A port moves to a clear face its body offers and its box has room
    on, where every connected family port's line needs fewer bends in
    all and no line it shares the face with crosses or crowds it. A
    port a pin or a ``via()`` route places stays where it is drawn.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed units.
    unit : _FaceFamilies
        Block, tank or vessel.
    frame : Frame
        The unit's frame.
    members : list[str]
        Connected family ports no author statement fixes.
    """
    from pandid.portgeom import _xform, drawn_side, family_faces, pin_intent

    rot, mx, my = _xform(frame)
    pinned = {port for port, _ in pin_intent(unit).values()}
    routes = {name: port.stream.route for name, port in unit.ports.items()
              if name in unit._faces and port.stream is not None}
    family = list(routes)
    held = {name for name, route in routes.items()
            if name in pinned or (route is not None and route.manual)}
    for name in members:
        target = _reference(unit.ports[name])
        if target is None or name in held:
            continue
        faces = family_faces(unit, frame) or unit._faces
        menu = [drawn_side(face, rot, mx, my) for face in unit._offered(name)
                if unit._fits({**faces, name: face}, frame)]
        if len(menu) < 2:
            continue
        before = _lines(unit, frame, family, held)
        better = [face for face in _usable_faces(fs, unit, frame, name, menu)
                  if face != menu[0]
                  and _saves(unit, frame, name, face, family, held, before)]
        # _saves() keeps the port clear of every connected nozzle.
        face = _best(unit, frame, name, better, target, set())
        if face is not None:
            frame.port_faces[name] = face


def _lines(unit: "Unit", frame, names: list[str], held: set[str]
           ) -> dict[str, tuple[tuple[float, float], int | None]]:
    """Return each port's anchor and fewest bends to a fixed peer.

    Parameters
    ----------
    unit : Unit
        Unit owning the ports.
    frame : Frame
        The unit's frame.
    names : list[str]
        Connected ports.
    held : set[str]
        Ports whose nozzle must stay where it is drawn.

    Returns
    -------
    dict[str, tuple[tuple[float, float], int or None]]
        Port name to anchor and bends, None for a held port or one
        whose peer has a choice of faces.
    """
    from pandid.portgeom import resolve_port
    from pandid.routing.metrics import min_bends

    out: dict[str, tuple[tuple[float, float], int | None]] = {}
    for name in names:
        _, anchor, face = resolve_port(unit, frame, name)
        peer = None if name in held else _fixed_peer(unit.ports[name])
        out[name] = (anchor, None if peer is None
                     else min_bends(anchor, face, peer.anchor, peer.face))
    return out


def _saves(unit: "Unit", frame, port_name: str, face: str, family: list[str],
           held: set[str],
           before: dict[str, tuple[tuple[float, float], int | None]]) -> bool:
    """Return whether moving a family port to a face saves bends.

    The move must leave unmoved every line whose bends cannot be
    counted, need fewer bends over the family, and draw no line on the
    face crossing or crowding the moved one.

    Parameters
    ----------
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame.
    port_name : str
        Port to move.
    face : str
        Face to try, as drawn.
    family : list[str]
        Connected family ports.
    held : set[str]
        Ports whose nozzle must stay where it is drawn.
    before : dict[str, tuple[tuple[float, float], int or None]]
        :func:`_lines` with the port where it is.

    Returns
    -------
    bool
        True if the move saves bends.
    """
    frame.port_faces[port_name] = face
    try:
        after = _lines(unit, frame, family, held)
        counted = all(
            (was[1] is not None and now[1] is not None) or was[0] == now[0]
            for was, now in zip(before.values(), after.values())
        )
        fewer = (sum(b for _, b in after.values() if b is not None)
                 < sum(b for _, b in before.values() if b is not None))
        return counted and fewer and not _clashes(unit, frame, port_name, face)
    finally:
        frame.port_faces.pop(port_name, None)


def _clashes(unit: "Unit", frame, port_name: str, face: str) -> bool:
    """Return whether a port crowds or crosses a line on its face.

    Two lines cross when they leave the face in the opposite order to
    their peers.

    Parameters
    ----------
    unit : Unit
        Unit owning the port.
    frame : Frame
        The unit's frame.
    port_name : str
        Port on ``face``.
    face : str
        Face as drawn.

    Returns
    -------
    bool
        True if a connected port on the face is nearer than
        :data:`~pandid.render.symbols.MIN_NOZZLE_PITCH` or crosses it.
    """
    from pandid.portgeom import resolve_port
    from pandid.render.symbols import MIN_NOZZLE_PITCH

    axis = 1 if face in ("W", "E") else 0
    resolved = {name: resolve_port(unit, frame, name)
                for name, port in unit.ports.items() if port.stream is not None}
    on_face = sorted((at.point[axis], name) for name, at in resolved.items()
                     if at.face == face)
    if any(b[0] - a[0] < MIN_NOZZLE_PITCH for a, b in zip(on_face, on_face[1:])):
        return True
    mine = resolved[port_name].point[axis]
    target = _reference(unit.ports[port_name])
    for at, name in on_face:
        other = _reference(unit.ports[name])
        if target is not None and other is not None and (
                (at - mine) * (other[axis] - target[axis]) < 0):
            return True
    return False


def _fixed_peer(port: "Port"):
    """Return the resolved peer nozzle of a port, if it has one face.

    Parameters
    ----------
    port : Port
        Connected port.

    Returns
    -------
    ResolvedPort or None
        Peer's point, anchor and face, or None if the port is
        unconnected, its peer unplaced or offered a choice of faces.
    """
    from pandid.portgeom import port_faces, resolve_port

    stream = port.stream
    if stream is None:
        return None
    peer = stream.dest if stream.source is port else stream.source
    owner = peer.owner
    if owner.frame is None or len(port_faces(owner, peer.name, owner.frame)) != 1:
        return None
    return resolve_port(owner, owner.frame, peer.name)


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
    from pandid.portgeom import face_point, resolve_port, unit_box
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
    fixed_peer = _fixed_peer(port)
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
