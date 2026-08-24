"""Port-face selection: which declared placement gets the stream.

Policy only. Every coordinate here is asked for from
:mod:`pandid.portgeom`, which stays the single authority on where a port
is; this module names a candidate face and reads back where that puts
the ink. *portgeom answers where; this answers which.*

Where this runs
---------------
Selection is a layout phase, after coordinate assignment has settled
every drawn box and before anything reads a face. That is the only cut
with no cycle in it: a face can only be judged against where its peer's
box ended up, and the passes that place those boxes (ranking, the spine
straightener) resolve ports themselves, so a pick they could see would
feed back into the geometry it was derived from. Downstream, labels,
routing and rendering all read
:func:`~pandid.portgeom.resolve_port` and so see the same answer.

The pick is written to the resolved :class:`~pandid.geometry.Frame`. The
solver's ``_Slot`` has no such field, which makes "the box passes cannot
read a pick" structural rather than a convention, and every layout run
emits fresh frames, so laying a sheet out twice draws it the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

# How far the router stands a run off a nozzle before it may turn. A
# face pointing away from its peer pays that twice: out to the
# stand-off, then back past the nozzle before the run has made any
# ground. That is what separates a detour from a merely longer straight
# run.
_ESCAPE = 25.0


def select_faces(fs: "Flowsheet") -> None:
    """Choose a face for every movable port with none named or pinned."""
    from pandid.portgeom import pin_intent, port_faces

    for unit in fs.units:
        frame = unit.frame
        if frame is None:
            continue
        # Start from nothing. An attached balloon's frame carries its
        # picks across a re-place, so without this the phase would read
        # its own last answer back in and stop being a function of the
        # sheet alone.
        frame.port_faces.clear()
        if not fs.auto_faces:
            continue
        # A nozzle the author put on a coordinate. Its face is settled
        # by that, not chosen here: ``pin(port="in_1", y=440)`` is
        # honoured by deriving a corner from where the nozzle sits on
        # the box (:attr:`pandid.units.Unit.pin_`), and the box is
        # already placed by the time this phase runs -- so a pick made
        # here would move the nozzle off the coordinate the solver was
        # seeded from, with nothing downstream to re-derive the corner.
        # A tank pinned by its inlet was drawn with the run entering its
        # roof instead of the pinned point on its wall (#294).
        #
        # The constraint goes this way round and not the other because
        # the cut above it is load-bearing: a face is only judgeable
        # against where its peer's box landed, so selection cannot run
        # before placement, so a pin cannot be re-derived from a pick.
        # A pin is the author's boundary condition and a face is the
        # engine's preference, and it is the preference that yields.
        # :meth:`~pandid.units.Unit.nozzle` is how a face is *chosen*
        # for a pinned nozzle, and it wins here by the same exemption.
        pinned = {port for port, _ in pin_intent(unit).values() if port is not None}
        live = [name for name, port in unit.ports.items() if port.stream is not None]
        movable = [name for name in live
                   if name not in unit._port_faces
                   and name not in pinned
                   and len(port_faces(unit, name, frame)) > 1]
        # Points already spoken for: a nozzle the author named, one
        # fixed by physics. Two live connections resolving to one point
        # is a hard validation error, and the selector must not be the
        # thing that makes one. Ports are served in declaration order,
        # so a sheet does not depend on which of them the author
        # happened to connect first.
        #
        # A boundary flag carrying several runs is the one place two
        # live connections *do* resolve to one point, deliberately
        # (:attr:`pandid.units.Unit.ONE_NOZZLE_MANY_RUNS`), and nothing
        # here has to change for it: a flag's connection has a single
        # placement, so no member of it is ever ``movable``, and they
        # all land in ``taken`` -- which is a set, and already holds one
        # entry for one point. The rule this comment states is still the
        # rule and the selector still cannot break it; what the flag
        # changes is only that ``validate`` no longer *reports* the
        # coincidence, and it reports it for everything else.
        taken = {_point(unit, frame, name) for name in live if name not in movable}
        for name in movable:
            target = _reference(unit.ports[name])
            if target is None:
                continue
            face = _best(unit, frame, name, port_faces(unit, name, frame), target, taken)
            if face is None:
                continue  # all faces taken; leave the symbol's
            frame.port_faces[name] = face
            taken.add(_point(unit, frame, name))


def _point(unit: "Unit", frame, port_name: str) -> tuple[float, ...]:
    """Where a nozzle lands, rounded as the coincidence check is."""
    from pandid.portgeom import resolve_port

    return tuple(round(v, 3) for v in resolve_port(unit, frame, port_name).point)


def _reference(port: "Port") -> tuple[float, float] | None:
    """The point a candidate face for ``port`` is scored against.

    None when there is nothing placed to aim at. The peer's nozzle is
    the target where it has one placement and so cannot move; where it
    can move it has no settled position yet (reading a provisional one
    would make each port's answer depend on the order the ports happened
    to be visited), so the centre of its unit's drawn box stands in for
    it, which is the same point whichever face it ends up on.
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
    """The cheapest free face in ``menu`` for a run to ``target``.

    Scoring a candidate by resolving it is what keeps the geometry in
    one place: the selector states a face and reads back the anchor and
    normal the router and renderer will use, rather than deriving a
    second set of its own.
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
        # Ties are common and expected: a balloon is square, so stepping
        # a signal round to the next face trades exactly as much
        # horizontal run for vertical. Break them towards the face
        # pointing most directly at the peer, then on the symbol's own
        # order of preference, so the answer never turns on how the menu
        # was iterated.
        scored.append((_cost(anchor, normal, target), -_aim(centre, normal, target),
                       rank, face))
    frame.port_faces.pop(port_name, None)
    return min(scored)[-1] if scored else None


def _cost(anchor: tuple[float, float], normal: tuple[float, float],
          target: tuple[float, float]) -> float:
    """Orthogonal run to the peer, and the price of turning back."""
    (ax, ay), (nx, ny), (tx, ty) = anchor, normal, target
    reach = (tx - ax) * nx + (ty - ay) * ny
    return abs(tx - ax) + abs(ty - ay) + (0.0 if reach >= 0.0 else 2.0 * _ESCAPE)


def _aim(centre: tuple[float, float], normal: tuple[float, float],
         target: tuple[float, float]) -> float:
    """How squarely a face's outward normal points at the peer."""
    return (target[0] - centre[0]) * normal[0] + (target[1] - centre[1]) * normal[1]
