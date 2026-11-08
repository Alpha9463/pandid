"""Hang each driver beside the machine it drives.

A driver whose only line is the shaft to a machine's ``drive`` is drawn
on the side that drive faces, a short straight shaft away, and the
machine keeps room for it there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.halo import Pad
from pandid.layout.stages import slot
from pandid.portgeom import COMPASS, resolve_port, resolve_size, unit_box
from pandid.render.weights import M
from pandid.streams import MECHANICAL

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: Length of the shaft drawn between a hung driver and its machine.
SHAFT = 2 * M

_BACK = {"N": "S", "S": "N", "E": "W", "W": "E"}


def hung(fs: "Flowsheet") -> "list[Stream]":
    """Return the shafts whose driver is drawn beside its machine.

    A driver hangs when the shaft is its only line and no pin places it.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.

    Returns
    -------
    list[Stream]
        Each such shaft, in sheet order.
    """
    out = []
    for s in fs.streams:
        driver = s.source.owner
        if (s.kind == MECHANICAL and driver.pin_ is None
                and all(p.stream is s or p.stream is None for p in driver.ports.values())):
            out.append(s)
    return out


def _hang(shaft: "Stream", host: Frame) -> Frame:
    """Return the frame that puts a driver a shaft away from its machine.

    Parameters
    ----------
    shaft : Stream
        Shaft from the driver to the machine.
    host : Frame
        Frame of the machine.

    Returns
    -------
    Frame
        Frame of the driver, its shaft facing the machine's drive.
    """
    drive, driver = shaft.dest, shaft.source.owner
    _, (ax, ay), face = resolve_port(drive.owner, host, drive.name)
    dx, dy = COMPASS[face]
    w, h = resolve_size(driver)
    faces = {shaft.source.name: _BACK[face]}
    (px, py), _, _ = resolve_port(driver, Frame(x=0.0, y=0.0, w=w, h=h, port_faces=faces),
                                  shaft.source.name)
    return Frame(x=ax + dx * SHAFT - px, y=ay + dy * SHAFT - py, w=w, h=h, port_faces=faces)


def driver_pads(shafts: "list[Stream]") -> "dict[Unit, Pad]":
    """Return the room each machine keeps for the drivers hung on it.

    Parameters
    ----------
    shafts : list[Stream]
        Shafts from :func:`hung`, each machine with a seeded slot.

    Returns
    -------
    dict[Unit, Pad]
        How far the hung drivers reach past each machine's box.
    """
    pads: "dict[Unit, Pad]" = {}
    for shaft in shafts:
        host = shaft.dest.owner
        s = slot(host)
        probe = Frame(x=0.0, y=0.0, w=s.w, h=s.h, orientation=s.orientation,
                      mirrored=s.mirrored, mirror_y=s.mirror_y)
        x0, y0, x1, y1 = unit_box(host, probe)
        hx0, hy0, hx1, hy1 = unit_box(shaft.source.owner, _hang(shaft, probe))
        reach = Pad(y0 - hy0, hy1 - y1, hx1 - x1, x0 - hx0)
        pads[host] = Pad(*(max(0.0, a, b) for a, b in zip(pads.get(host, Pad()), reach)))
    return pads


def place_drivers(shafts: "list[Stream]") -> None:
    """Give each hung driver its frame beside its placed machine.

    Parameters
    ----------
    shafts : list[Stream]
        Shafts from :func:`hung`, each machine placed.
    """
    for shaft in shafts:
        driver, host = shaft.source.owner, shaft.dest.owner
        assert host.frame is not None, f"{host.name} has no frame to hang {driver.name} on"
        frame = _hang(shaft, host.frame)
        s = slot(driver)
        s.x, s.y = frame.x, frame.y
        driver.frame = frame
