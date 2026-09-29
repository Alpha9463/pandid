"""Place registered valve stations as complete local assemblies."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pandid.geometry import Frame
from pandid.layout.corridor import horizontal_centerline
from pandid.layout.stages import process_units, slot
from pandid.portgeom import port_point, resolve_port, resolve_size, unit_box
from pandid.stations import StationAssembly, member_mirror

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def _frame(unit: Unit, x: float, y: float, *, mirror: bool | str = False,
           orientation: float = 0) -> Frame:
    """Move a unit while retaining its resolved grid rank.

    Parameters
    ----------
    unit : Unit
        Station member with an existing frame.
    x, y : float
        New top-left position.
    mirror : bool or str
        Local station transform.
    orientation : float
        Rotation in degrees.

    Returns
    -------
    Frame
        Candidate member geometry.
    """
    old = unit.frame
    assert old is not None
    probe = replace(old, orientation=orientation,
                    mirrored=mirror in (True, "x", "xy"),
                    mirror_y=mirror in ("y", "xy"))
    width, height = resolve_size(unit, probe)
    return replace(probe, x=x, y=y, w=width, h=height, label_pos=None, port_faces={})


def _station_frames(assembly: StationAssembly, left: float, y: float,
                    mirrored: bool) -> dict[Unit, Frame]:
    """Build main, bypass, and drain frames around one centerline.

    Parameters
    ----------
    assembly : StationAssembly
        Station and its local spacing options.
    left, y : float
        Footprint left edge and material-run centerline.
    mirrored : bool
        Whether flow crosses the footprint from right to left.

    Returns
    -------
    dict[Unit, Frame]
        Candidate geometry for each station member.
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
        probe = _frame(unit, cursor, 0, mirror=mirror)
        inlet_y = port_point(unit, probe, "inlet")[1]
        frames[unit] = replace(probe, y=y - inlet_y)
        cursor += probe.w + assembly.gap

    for drain in (station.upstream_drain, station.downstream_drain):
        if drain is None:
            continue
        incoming = drain.inlet.stream
        assert incoming is not None
        junction = incoming.source.owner
        assert junction is not None
        x = port_point(junction, frames[junction], "branch")[0]
        probe = _frame(drain, 0, 0, orientation=90)
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
        probe = _frame(station.bypass, 0, 0, mirror="x" if mirrored else False)
        inlet = port_point(station.bypass, probe, "inlet")
        frames[station.bypass] = replace(
            probe, x=centre - probe.w / 2,
            y=y - assembly.bypass_rise - inlet[1],
        )
    return frames


def _fits(frames: dict[Unit, Frame], obstacles: list[Unit]) -> bool:
    """Check assembly bodies against units outside the station.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Candidate geometry for the station.
    obstacles : list[Unit]
        Other process units on the sheet.

    Returns
    -------
    bool
        Whether all candidate bodies have external clearance.
    """
    for unit, frame in frames.items():
        pin = unit.pin_
        if pin is not None and (
            pin.col is not None or pin.row is not None
            or frame.orientation != pin.orientation
            or frame.mirrored != pin.mirrored or frame.mirror_y != pin.mirror_y
        ):
            return False
        if pin is not None and any(
            getattr(pin, axis) is not None and getattr(frame, axis) != getattr(pin, axis)
            for axis in ("x", "y")
        ):
            return False
        left, top, right, bottom = unit_box(unit, frame)
        for other in obstacles:
            if other.frame is None:
                continue
            o_left, o_top, o_right, o_bottom = unit_box(other, other.frame)
            if right + 8 > o_left and o_right + 8 > left and bottom + 8 > o_top and o_bottom + 8 > top:
                return False
    return True


def _separated(first: dict[Unit, Frame], second: dict[Unit, Frame]) -> bool:
    """Check clearance between two proposed station footprints.

    Parameters
    ----------
    first, second : dict[Unit, Frame]
        Proposed member frames for distinct stations.

    Returns
    -------
    bool
        Whether their unit bodies remain separate.
    """
    for unit, frame in first.items():
        left, top, right, bottom = unit_box(unit, frame)
        for other, other_frame in second.items():
            o_left, o_top, o_right, o_bottom = unit_box(other, other_frame)
            if right + 8 > o_left and o_right + 8 > left and bottom + 8 > o_top and o_bottom + 8 > top:
                return False
    return True


def _station_centerline(source: Unit, source_port: str, dest: Unit,
                        dest_port: str, start: tuple[float, float],
                        end: tuple[float, float]) -> float | None:
    """Find a horizontal station leg after the host nozzles can exit.

    Parameters
    ----------
    source, dest : Unit
        Equipment at the ends of the station's external run.
    source_port, dest_port : str
        Connected nozzle names.
    start, end : tuple[float, float]
        Resolved nozzle points.

    Returns
    -------
    float or None
        A reachable horizontal axis, or ``None`` without one.
    """
    axis = horizontal_centerline(source, source_port, dest, dest_port, start, end)
    if axis is not None:
        return axis
    assert source.frame is not None and dest.frame is not None
    source_face = resolve_port(source, source.frame, source_port).face
    dest_face = resolve_port(dest, dest.frame, dest_port).face
    forward = 1 if end[0] > start[0] else -1
    if source_face in ("E", "W") and source_face != ("E" if forward > 0 else "W"):
        return None
    if dest_face in ("E", "W") and dest_face != ("W" if forward > 0 else "E"):
        return None

    lower, upper = float("-inf"), float("inf")
    for face, point in ((source_face, start), (dest_face, end)):
        if face == "N":
            upper = min(upper, point[1] - 25.0)
        elif face == "S":
            lower = max(lower, point[1] + 25.0)
    if lower > upper:
        return None
    if source_face in ("E", "W"):
        preferred = start[1]
    elif dest_face in ("E", "W"):
        preferred = end[1]
    elif lower == float("-inf"):
        preferred = upper
    elif upper == float("inf"):
        preferred = lower
    else:
        preferred = (lower + upper) / 2
    return max(lower, min(preferred, upper))


def place_stations(fs: Flowsheet) -> int:
    """Move feasible unpinned stations onto their external material runs.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with ordinary process coordinates assigned.

    Returns
    -------
    int
        Number of complete station assemblies placed.
    """
    if not fs._station_assemblies:
        return 0
    units = process_units(fs)
    placed_count = 0
    groups: dict[int, list[StationAssembly]] = {}
    for assembly in fs._station_assemblies:
        key = id(assembly.run) if assembly.run is not None else id(assembly)
        groups.setdefault(key, []).append(assembly)
    for group in groups.values():
        group.sort(key=lambda assembly: assembly.at if assembly.at is not None else 0.5)
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
        if source is None or dest is None or source.frame is None or dest.frame is None:
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
        proposed: list[dict[Unit, Frame]] = []
        for assembly in group:
            if assembly.mirrored and not mirrored:
                break
            station = assembly.station
            branch = {station.bypass, station.upstream_drain, station.downstream_drain}
            main = [unit for unit in station.members if unit not in branch]
            width = sum(resolve_size(unit)[0] for unit in main)
            width += assembly.gap * (len(main) - 1)
            if high - low < width + 16:
                break
            fraction = assembly.at if assembly.at is not None else 0.5
            target = start[0] + fraction * (end[0] - start[0])
            left = min(max(target - width / 2, low + 8), high - width - 8)
            frames = _station_frames(assembly, left, centerline, mirrored)
            if not _fits(frames, obstacles) or any(
                not _separated(frames, earlier) for earlier in proposed
            ):
                break
            proposed.append(frames)
        if len(proposed) != len(group):
            continue
        placed_count += len(proposed)
        for frames in proposed:
            for unit, frame in frames.items():
                unit.frame = frame
                placed = slot(unit)
                placed.x, placed.y = frame.x, frame.y
                placed.w, placed.h = frame.w, frame.h
                placed.orientation = frame.orientation
                placed.mirrored, placed.mirror_y = frame.mirrored, frame.mirror_y
    return placed_count
