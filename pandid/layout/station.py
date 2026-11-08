"""Place valve stations as whole assemblies on their lines."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.conflicts import boxes_overlap
from pandid.layout.stages import process_units
from pandid.portgeom import port_point, resolve_port, resolve_size, unit_box
from pandid.routing.visibility import MIN_ESCAPE
from pandid.stations import StationAssembly, member_mirror

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def _frame(unit: Unit, *, mirror: bool | str = False, orientation: float = 0) -> Frame:
    """Return a unit's frame at the origin with a new transform.

    Parameters
    ----------
    unit : Unit
        Placed unit.
    mirror : bool or str, default=False
        ``"x"`` (or ``True``), ``"y"`` or ``"xy"``: axes to flip.
    orientation : float, default=0
        Rotation in degrees.

    Returns
    -------
    Frame
        The moved frame, with no label side or port faces.
    """
    old = unit.frame
    assert old is not None
    probe = replace(old, orientation=orientation,
                    mirrored=mirror in (True, "x", "xy"),
                    mirror_y=mirror in ("y", "xy"))
    width, height = resolve_size(unit, probe)
    return replace(probe, x=0, y=0, w=width, h=height, label_pos=None, port_faces={})


def _station_frames(assembly: StationAssembly, left: float, y: float,
                    mirrored: bool) -> dict[Unit, Frame]:
    """Return main, bypass and drain frames around one centerline.

    Parameters
    ----------
    assembly : StationAssembly
        Station to lay out.
    left : float
        Main run's left edge.
    y : float
        Centerline.
    mirrored : bool
        Whether flow runs right to left.

    Returns
    -------
    dict[Unit, Frame]
        Frame of each member.

    Raises
    ------
    ValueError
        If a member's stated nozzle face cannot be drawn in the station.
    """
    station = assembly.station
    branch = {station.bypass, station.upstream_drain, station.downstream_drain}
    main = [unit for unit in station.members if unit not in branch]
    takeoff = station.tees[0] if station.bypass is not None else None
    rejoin = station.tees[-1] if station.bypass is not None else None
    frames: dict[Unit, Frame] = {}
    cursor = left
    for unit in (reversed(main) if mirrored else main):
        mirror = member_mirror(mirrored, unit in (takeoff, rejoin))
        probe = _frame(unit, mirror=mirror)
        inlet_y = port_point(unit, probe, "inlet")[1]
        frames[unit] = replace(probe, x=cursor, y=y - inlet_y)
        cursor += probe.w + assembly.gap

    for drain in (station.upstream_drain, station.downstream_drain):
        if drain is None:
            continue
        incoming = drain.inlet.stream
        assert incoming is not None
        junction = incoming.source.owner
        x = port_point(junction, frames[junction], "branch")[0]
        probe = _frame(drain, orientation=90)
        inlet = port_point(drain, probe, "inlet")
        frames[drain] = replace(probe, x=x - inlet[0],
                                y=y + assembly.drain_drop - inlet[1])

    if station.bypass is not None and takeoff is not None and rejoin is not None:
        target = getattr(station, assembly.bypass_over) if assembly.bypass_over else None
        if target is not None:
            centre = frames[target].cx
        else:
            centre = sum(port_point(tee, frames[tee], "branch")[0]
                         for tee in (takeoff, rejoin)) / 2
        probe = _frame(station.bypass, mirror="x" if mirrored else False)
        inlet = port_point(station.bypass, probe, "inlet")
        frames[station.bypass] = replace(
            probe, x=centre - probe.w / 2,
            y=y - assembly.bypass_rise - inlet[1],
        )
    return frames


def _anchored_origin(assembly: StationAssembly, preferred_left: float,
                     centerline: float, mirrored: bool) -> tuple[float, float] | None:
    """Return a station origin that meets its members' pins, or None.

    Parameters
    ----------
    assembly : StationAssembly
        Station to place.
    preferred_left : float
        Left edge to use when no member pins x.
    centerline : float
        Centerline to use when no member pins y.
    mirrored : bool
        Whether flow runs right to left.

    Returns
    -------
    tuple[float, float] or None
        Left edge and centerline, or None for a grid pin or pins
        that cannot all hold.

    Raises
    ------
    ValueError
        If a member's stated nozzle face cannot be drawn in the station.
    """
    base = _station_frames(assembly, 0.0, 0.0, mirrored)
    pinned_x: float | None = None
    pinned_y: float | None = None
    for unit, frame in base.items():
        pin = unit.pin_
        if pin is None:
            continue
        if pin.col is not None or pin.row is not None:
            return None
        if (frame.orientation != pin.orientation or frame.mirrored != pin.mirrored
                or frame.mirror_y != pin.mirror_y):
            return None
        if pin.x is not None:
            candidate_x = pin.x - frame.x
            if pinned_x is not None and abs(candidate_x - pinned_x) > 1e-6:
                return None
            pinned_x = candidate_x
        if pin.y is not None:
            candidate_y = pin.y - frame.y
            if pinned_y is not None and abs(candidate_y - pinned_y) > 1e-6:
                return None
            pinned_y = candidate_y
    return (preferred_left if pinned_x is None else pinned_x,
            centerline if pinned_y is None else pinned_y)


def _separated(first: dict[Unit, Frame], second: dict[Unit, Frame]) -> bool:
    """Return whether two sets of member boxes keep clear.

    Parameters
    ----------
    first : dict[Unit, Frame]
        Proposed member frames.
    second : dict[Unit, Frame]
        Frames to clear.

    Returns
    -------
    bool
        True if no two boxes come within 8 of each other.
    """
    return not any(boxes_overlap(unit_box(unit, frame), unit_box(other, other_frame), 8)
                   for unit, frame in first.items() for other, other_frame in second.items())


def _station_centerline(source: Unit, source_port: str, dest: Unit,
                        dest_port: str, start: tuple[float, float],
                        end: tuple[float, float]) -> float | None:
    """Return the y of a station's horizontal leg, or None.

    Parameters
    ----------
    source : Unit
        Unit at the start of the line.
    source_port : str
        Port name on ``source``.
    dest : Unit
        Unit at the end of the line.
    dest_port : str
        Port name on ``dest``.
    start : tuple[float, float]
        Source nozzle point.
    end : tuple[float, float]
        Destination nozzle point.

    Returns
    -------
    float or None
        The leg's y, or None if no horizontal leg fits.
    """
    assert source.frame is not None and dest.frame is not None
    source_face = resolve_port(source, source.frame, source_port).face
    dest_face = resolve_port(dest, dest.frame, dest_port).face
    ahead, behind = ("E", "W") if end[0] > start[0] else ("W", "E")
    if abs(start[1] - end[1]) <= 1 or (source_face == ahead and dest_face not in ("E", "W")):
        return start[1]
    if dest_face == behind and source_face not in ("E", "W"):
        return end[1]
    if source_face in ("E", "W") and source_face != ahead:
        return None
    if dest_face in ("E", "W") and dest_face != behind:
        return None

    lower, upper = float("-inf"), float("inf")
    for face, point in ((source_face, start), (dest_face, end)):
        if face == "N":
            upper = min(upper, point[1] - MIN_ESCAPE)
        elif face == "S":
            lower = max(lower, point[1] + MIN_ESCAPE)
    if lower > upper:
        return None
    if source_face in ("E", "W"):
        preferred = start[1]
    elif lower == float("-inf"):
        preferred = upper
    elif upper == float("inf"):
        preferred = lower
    else:
        preferred = (lower + upper) / 2
    return max(lower, min(preferred, upper))


def _fraction(assembly: StationAssembly) -> float:
    """Return a station's fraction along its line.

    Parameters
    ----------
    assembly : StationAssembly
        Station on a line.

    Returns
    -------
    float
        Fraction from 0 to 1.
    """
    from pandid.inline import position

    incoming = assembly.station.inlet.stream
    value = position(incoming) if incoming is not None else None
    return 0.5 if value is None else value


def place_stations(fs: Flowsheet, assemblies: list[StationAssembly]) -> None:
    """Place each line's stations where all of them fit.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed process units.
    assemblies : list[StationAssembly]
        Stations to place.
    """
    from pandid.layout.mounted import _commit, _main_width

    units = process_units(fs)
    groups: dict[int, list[StationAssembly]] = {}
    for assembly in assemblies:
        key = id(assembly.run) if assembly.run is not None else id(assembly)
        groups.setdefault(key, []).append(assembly)
    for group in groups.values():
        group.sort(key=_fraction)
        root = group[0].run
        if root is not None:
            source_port, dest_port = root.source, root._logical_to
        else:
            station = group[0].station
            incoming, outgoing = station.inlet.stream, station.outlet.stream
            if incoming is None or outgoing is None:
                continue
            source_port, dest_port = incoming.source, outgoing.dest
        if dest_port is None:
            continue
        source, dest = source_port.owner, dest_port.owner
        if source.frame is None or dest.frame is None:
            continue
        start = port_point(source, source.frame, source_port.name)
        end = port_point(dest, dest.frame, dest_port.name)
        if abs(start[0] - end[0]) < 1:
            continue
        centerline = _station_centerline(source, source_port.name, dest,
                                         dest_port.name, start, end)
        if centerline is None:
            continue
        mirrored = start[0] > end[0]
        low, high = sorted((start[0], end[0]))
        members = {unit for assembly in group for unit in assembly.station.members}
        if any(stream.route is not None and stream.route.manual
               for stream in fs.streams
               if stream.source.owner in members or stream.dest.owner in members):
            continue
        obstacles = [unit for unit in units if unit not in members]
        placed = {unit: unit.frame for unit in obstacles if unit.frame is not None}
        proposed: list[dict[Unit, Frame]] = []
        for assembly in group:
            if assembly.mirrored and not mirrored:
                break
            width = _main_width(assembly)
            if high - low < width + 16:
                break
            fraction = _fraction(assembly)
            target = start[0] + fraction * (end[0] - start[0])
            left = min(max(target - width / 2, low + 8), high - width - 8)
            try:
                origin = _anchored_origin(assembly, left, centerline, mirrored)
                if origin is None or not low + 8 <= origin[0] <= high - width - 8:
                    break
                frames = _station_frames(assembly, *origin, mirrored)
            except ValueError:
                # Stop at a stated nozzle face the station cannot draw.
                break
            if not all(_separated(frames, other) for other in (placed, *proposed)):
                break
            for unit, frame in frames.items():
                pin = unit.pin_
                if pin is not None and (pin.x is not None or pin.y is not None):
                    frames[unit] = replace(
                        frame,
                        x=pin.x if pin.x is not None else frame.x,
                        y=pin.y if pin.y is not None else frame.y,
                    )
            proposed.append(frames)
        if len(proposed) != len(group):
            continue
        for frames in proposed:
            _commit(frames, obstacles)
