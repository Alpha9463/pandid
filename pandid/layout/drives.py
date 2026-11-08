"""Hang each free driver or driven machine beside the unit it turns with.

A unit whose only lines are shafts, such as a motor, a gearbox or a
generator, is drawn on the side its partner's shaft end faces, a short
straight shaft away, and the partner keeps room for it there. A train
hangs from its piped or pinned units, else from the machine it drives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pandid.geometry import Frame
from pandid.layout.halo import Pad
from pandid.layout.stages import slot
from pandid.portgeom import COMPASS, port_faces, resolve_port, resolve_size, unit_box
from pandid.render.weights import M
from pandid.streams import MECHANICAL

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.streams import Stream
    from pandid.units import Unit

#: Length of the shaft drawn between a hung unit and its partner.
SHAFT = 2 * M

_BACK = {"N": "S", "S": "N", "E": "W", "W": "E"}


class Hang(NamedTuple):
    """One unit hung on a shaft from a unit placed before it.

    Attributes
    ----------
    shaft : Stream
        The shaft.
    host : Port
        The shaft's end on the unit already placed.
    end : Port
        The shaft's end on the hung unit.
    """

    shaft: Stream
    host: Port
    end: Port


def _free(unit: "Unit") -> bool:
    """Return whether a unit has no pin and no line but shafts.

    Parameters
    ----------
    unit : Unit
        Unit to test.

    Returns
    -------
    bool
        True if it may hang from a partner.
    """
    return unit.pin_ is None and all(
        p.stream is None or p.stream.kind == MECHANICAL for p in unit.ports.values())


def hung(fs: "Flowsheet") -> list[Hang]:
    """Return the units drawn beside a partner, each after its host.

    A train hangs from each of its units that is piped or pinned, else
    from the unit that drives nothing. A unit whose shaft end cannot
    face its host is not hung.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with seeded slots.

    Returns
    -------
    list[Hang]
        Each hung unit's shaft and ends, in placing order.
    """
    shafts = [s for s in fs.streams if s.kind == MECHANICAL]
    if not shafts:
        return []
    joined = {id(u): u for s in shafts for u in (s.source.owner, s.dest.owner)}
    roots = {i for i, u in joined.items() if not _free(u)}
    # A train of free units hangs from the unit that drives nothing.
    roots |= {i for i, u in joined.items() if i not in roots
              and all(p.stream is None or p.role != "shaft" for p in u.ports.values())
              and not any(id(v) in roots for v in _train(u, shafts))}
    probes = {i: _probe(joined[i]) for i in roots}
    out: list[Hang] = []
    grown = True
    while grown:
        grown = False
        for s in shafts:
            for host, end in ((s.dest, s.source), (s.source, s.dest)):
                if id(host.owner) not in probes or id(end.owner) in probes:
                    continue
                face = resolve_port(host.owner, probes[id(host.owner)], host.name).face
                if _BACK[face] in port_faces(end.owner, end.name, slot(end.owner)):
                    hang = Hang(s, host, end)
                    probes[id(end.owner)] = _hang(hang, probes[id(host.owner)])
                    out.append(hang)
                    grown = True
    return out


def _probe(unit: "Unit") -> Frame:
    """Return a frame at the origin with a unit's seeded size and turn.

    Parameters
    ----------
    unit : Unit
        Unit with a seeded slot.

    Returns
    -------
    Frame
        The probe.
    """
    s = slot(unit)
    return Frame(x=0.0, y=0.0, w=s.w, h=s.h, orientation=s.orientation,
                 mirrored=s.mirrored, mirror_y=s.mirror_y)


def _train(unit: "Unit", shafts: "list[Stream]") -> "list[Unit]":
    """Return the units joined to one by shafts, itself included.

    Parameters
    ----------
    unit : Unit
        Unit to start from.
    shafts : list[Stream]
        Every shaft on the sheet.

    Returns
    -------
    list[Unit]
        The train.
    """
    found = {id(unit): unit}
    grown = True
    while grown:
        grown = False
        for s in shafts:
            a, b = s.source.owner, s.dest.owner
            for u, v in ((a, b), (b, a)):
                if id(u) in found and id(v) not in found:
                    found[id(v)] = v
                    grown = True
    return list(found.values())


def _hang(hang: Hang, host: Frame) -> Frame:
    """Return the frame that puts a unit a shaft away from its host.

    The hung unit's end faces the host, and its other shaft ends face
    on, away from it, where they can.

    Parameters
    ----------
    hang : Hang
        The shaft and its two ends.
    host : Frame
        Frame of the host.

    Returns
    -------
    Frame
        Frame of the hung unit.
    """
    unit = hang.end.owner
    _, (ax, ay), face = resolve_port(hang.host.owner, host, hang.host.name)
    dx, dy = COMPASS[face]
    w, h = resolve_size(unit)
    probe = Frame(x=0.0, y=0.0, w=w, h=h)
    faces = {name: face for name, port in unit.ports.items()
             if port.stream is not None and port.stream.kind == MECHANICAL
             and face in port_faces(unit, name, probe)}
    faces[hang.end.name] = _BACK[face]
    probe.port_faces.update(faces)
    (px, py), _, _ = resolve_port(unit, probe, hang.end.name)
    return Frame(x=ax + dx * SHAFT - px, y=ay + dy * SHAFT - py, w=w, h=h, port_faces=faces)


def driver_pads(hangs: "list[Hang]") -> "dict[Unit, Pad]":
    """Return the room each placed unit keeps for the train hung on it.

    Parameters
    ----------
    hangs : list[Hang]
        Hung units from :func:`hung`, each with a seeded slot.

    Returns
    -------
    dict[Unit, Pad]
        How far each placed unit's hung train reaches past its box.
    """
    frames: "dict[int, Frame]" = {}
    roots: "dict[int, Unit]" = {}
    for hang in hangs:
        host = hang.host.owner
        if id(host) not in frames:
            frames[id(host)], roots[id(host)] = _probe(host), host
        roots[id(hang.end.owner)] = roots[id(host)]
        frames[id(hang.end.owner)] = _hang(hang, frames[id(host)])
    pads: "dict[Unit, Pad]" = {}
    for hang in hangs:
        root = roots[id(hang.end.owner)]
        x0, y0, x1, y1 = unit_box(root, frames[id(root)])
        hx0, hy0, hx1, hy1 = unit_box(hang.end.owner, frames[id(hang.end.owner)])
        reach = Pad(y0 - hy0, hy1 - y1, hx1 - x1, x0 - hx0)
        pads[root] = Pad(*(max(0.0, a, b) for a, b in zip(pads.get(root, Pad()), reach)))
    return pads


def place_drivers(hangs: "list[Hang]") -> None:
    """Give each hung unit its frame beside its placed host.

    Parameters
    ----------
    hangs : list[Hang]
        Hung units from :func:`hung`, in placing order.
    """
    for hang in hangs:
        unit, host = hang.end.owner, hang.host.owner
        assert host.frame is not None, f"{host.name} has no frame to hang {unit.name} on"
        frame = _hang(hang, host.frame)
        s = slot(unit)
        s.x, s.y = frame.x, frame.y
        unit.frame = frame
