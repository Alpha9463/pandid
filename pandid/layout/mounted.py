"""Set pipe furniture on its routed pipe after placing the equipment.

Furniture is every straight-through valve, reducer or fitting with no
pinned position on a material line, and every valve station whose
members state no position, turn, mirror or nozzle face.
"""

from __future__ import annotations

from contextlib import contextmanager
from itertools import accumulate
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable, Iterator, Union

from pandid.geometry import Frame
from pandid.inline import _INLINE_KINDS
from pandid.layout.conflicts import _BODY_TOL, boxes_overlap
from pandid.layout.halo import balloon_pads, fixed_balloons
from pandid.layout.stages import process_streams, process_units, slot
from pandid.package import MARGIN as PACKAGE_MARGIN, boundary, tag_reach
from pandid.portgeom import port_point, resolve_size, unit_box
from pandid.routing.metrics import path_length
from pandid.routing.visibility import MARGIN
from pandid.streams import MECHANICAL

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.package import Package
    from pandid.ports import Port
    from pandid.stations import StationAssembly
    from pandid.streams import Stream
    from pandid.units import Mixer, Splitter, Unit

    Element = Union[Unit, StationAssembly]

#: Length kept clear at a leg end that turns a corner.
END = 25.0

#: Length kept clear at a leg end that is the pipe's own end nozzle.
NOZZLE_END = 8.0

#: Clearance kept across a pipe between an element and another unit.
GAP = 8.0

#: Clearance kept along a pipe between an element and anything else.
ALONG = 25.0

#: Reach of a balloon from the point where it taps a pipe.
TAP = 45.0

#: Step, in pixels, of the search along a leg for a clear spot.
NUDGE_STEP = 5.0

Point = tuple[float, float]
Leg = tuple[Point, Point]
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class MountedRun:
    """One pipe between two placed units and the furniture on it.

    Attributes
    ----------
    segments : tuple[Stream, ...]
        Streams of the pipe, in flow order.
    elements : tuple[Element, ...]
        Devices and station assemblies on the pipe, in flow order.
    places : tuple[tuple[Port, Port, float] or None, ...]
        Each element's line ends and fraction; None unless set ``on=``.
    taps : tuple[tuple[Port, Port, float], ...]
        Line ends and fraction of each balloon on the pipe, by fraction.
    """

    segments: tuple[Stream, ...]
    elements: tuple[Element, ...]
    places: tuple[tuple[Port, Port, float] | None, ...]
    taps: tuple[tuple[Port, Port, float], ...] = ()

    @property
    def source(self) -> Port:
        """Return the nozzle the pipe leaves.

        Returns
        -------
        Port
            Source nozzle of the first segment.
        """
        return self.segments[0].source

    @property
    def dest(self) -> Port:
        """Return the nozzle the pipe reaches.

        Returns
        -------
        Port
            Destination nozzle of the last segment.
        """
        return self.segments[-1].dest


def _position_pinned(unit: Unit) -> bool:
    """Return whether a unit pins ``col``, ``row``, ``x`` or ``y``.

    Parameters
    ----------
    unit : Unit
        Unit to check.

    Returns
    -------
    bool
        True if any position axis is pinned.
    """
    pin = unit.pin_
    return pin is not None and any(
        getattr(pin, axis) is not None for axis in ("col", "row", "x", "y")
    )


def _device(unit: Unit | None, angle: bool = False) -> bool:
    """Return whether a unit is an unpinned straight-through device.

    That is a valve, reducer or fitting whose only process ports,
    ``inlet`` and ``outlet``, carry material on opposite faces, or with
    ``angle`` set on adjacent faces.

    Parameters
    ----------
    unit : Unit or None
        Unit to check.
    angle : bool, default=False
        Take a device that turns its pipe too.

    Returns
    -------
    bool
        True for such a device.
    """
    from pandid.geometry import Pin
    from pandid.portgeom import port_offset

    if unit is None or unit.kind not in _INLINE_KINDS or _position_pinned(unit):
        return False
    ports = {p.name: p for p in unit.ports.values() if p.role == "process"}
    if set(ports) != {"inlet", "outlet"} or not all(
        p.stream is not None and p.stream.kind == "material" for p in ports.values()
    ):
        return False
    # Read the device as its author placed it.
    placed = unit.pin_ or Pin()
    width, height = resolve_size(unit, placed)
    (ax, ay), (bx, by) = (port_offset(unit, name, placed) for name in ("inlet", "outlet"))
    return (abs(abs(ax - bx) - width) < 1.0 or abs(abs(ay - by) - height) < 1.0
            or angle and _turns(unit))


def _turns(unit: Unit) -> bool:
    """Return whether a unit's inlet and outlet sit on adjacent faces.

    Parameters
    ----------
    unit : Unit
        Device to check, as its author placed it.

    Returns
    -------
    bool
        True for a device that turns its pipe, such as an angle valve.
    """
    from pandid.geometry import Pin
    from pandid.portgeom import port_faces

    placed = unit.pin_ or Pin()
    faces = {port_faces(unit, name, placed)[0] for name in ("inlet", "outlet")}
    return len(faces & {"N", "S"}) == 1 and len(faces & {"E", "W"}) == 1


def lateral_pitch(header: Mixer | Splitter) -> float:
    """Return the nozzle pitch the furniture on a header's lines needs.

    That is the widest furniture across its line, among the devices
    from each nozzle of the many-nozzle face to the first unit that is
    no device, plus :data:`GAP`.

    Parameters
    ----------
    header : Mixer or Splitter
        Header to measure.

    Returns
    -------
    float
        Pitch, or 0.0 where no line carries furniture.
    """
    from pandid.geometry import Pin
    from pandid.portgeom import port_offset
    from pandid.units import Mixer

    mixer = isinstance(header, Mixer)
    across = 0.0
    for port in header.inlets if isinstance(header, Mixer) else header.outlets:
        stream = port.stream
        while stream is not None:
            device = stream.source.owner if mixer else stream.dest.owner
            if not _device(device):
                break
            placed = device.pin_ or Pin()
            width, height = resolve_size(device, placed)
            (ax, ay), (bx, by) = (port_offset(device, name, placed) for name in ("inlet", "outlet"))
            across = max(across, width if abs(by - ay) > abs(bx - ax) else height)
            stream = device.ports["inlet" if mixer else "outlet"].stream
    return across + GAP if across else 0.0


def _members(element: Element) -> list[Unit]:
    """Return the units an element draws.

    Parameters
    ----------
    element : Unit or StationAssembly
        Device or station assembly.

    Returns
    -------
    list[Unit]
        The device, or the station's members.
    """
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return list(element.station.members)
    return [element]


def mounted_runs(fs: Flowsheet, angle: bool = False) -> list[MountedRun]:
    """Collect the pipes that carry furniture, in stream order.

    A pipe runs from a unit that is neither furniture nor a station
    member, through furniture, to the next unit that is not furniture.
    A pipe that starts and ends on one unit, ends at furniture, or has
    a manual route, is skipped.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read.
    angle : bool, default=False
        Take devices that turn their pipe, such as angle valves, as
        furniture too.

    Returns
    -------
    list[MountedRun]
        Furnished pipes.
    """
    from pandid.inline import position

    from pandid.streams import Stream

    members = {u for a in fs._station_assemblies for u in a.station.members}
    # A balloon on a stream taps its whole line, at a fraction of it.
    tapped: dict[int, list[tuple[Port, Port, float]]] = {}
    for unit in fs.units:
        host, at = vars(unit).get("host"), getattr(unit, "at", None)
        if unit.kind != "instrument" or not isinstance(host, Stream):
            continue
        line = host._logical_root or host
        tap = (line.source, line._logical_to or line.dest, 0.5 if at is None else float(at))
        for segment in line._logical_segments or [line]:
            tapped.setdefault(id(segment), []).append(tap)
    # Skip a station whose members state a position, turn, mirror or
    # nozzle face.
    stations = {id(a.station.inlet): a for a in fs._station_assemblies
                if not any(_position_pinned(u) or u._turn_stated or u._mirror_stated
                           or u._port_faces for u in a.station.members)}
    runs = []
    for first in process_streams(fs):
        start = first.source.owner
        if start in members or _device(start, angle):
            continue
        segments: list[Stream] = [first]
        elements: list[Element] = []
        while True:
            dest = segments[-1].dest
            assembly = stations.get(id(dest))
            if assembly is not None:
                element, out = assembly, assembly.station.outlet
            elif (dest.name == "inlet" and dest.owner not in members
                  and _device(dest.owner, angle)):
                element, out = dest.owner, dest.owner.ports["outlet"]
            else:
                break
            following = out.stream
            if following is None or following.kind != "material":
                elements = []
                break
            elements.append(element)
            segments.append(following)
        if (not elements or start is segments[-1].dest.owner
                or any(s.route is not None and s.route.manual for s in segments)):
            continue
        places = []
        for segment in segments[:-1]:
            line, at = segment._logical_root or segment, position(segment)
            end = line._logical_to
            places.append(None if end is None or at is None else (line.source, end, at))
        taps = {id(tap): tap for segment in segments for tap in tapped.get(id(segment), [])}
        runs.append(MountedRun(tuple(segments), tuple(elements), tuple(places),
                               tuple(sorted(taps.values(), key=lambda tap: tap[2]))))
    return runs


def _station_width(assemblies: list[StationAssembly]) -> float:
    """Return the room the stations on one pipe take along it.

    Parameters
    ----------
    assemblies : list[StationAssembly]
        Stations on the pipe.

    Returns
    -------
    float
        Length along the pipe.
    """
    return 16.0 + sum(_main_width(assembly) + 16.0 for assembly in assemblies)


def _chain_width(run: MountedRun) -> float:
    """Return the level room a pipe's furniture needs.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.

    Returns
    -------
    float
        Length along a level pipe.
    """
    from pandid.layout.layered import END_ROOM
    from pandid.stations import StationAssembly

    stations = [element for element in run.elements if isinstance(element, StationAssembly)]
    devices = [element for element in run.elements if not isinstance(element, StationAssembly)]
    width = _station_width(stations) if stations else 0.0
    if devices:
        width += sum(resolve_size(unit)[0] for unit in devices) + ALONG * (len(devices) + 1)
    return max(width, _room(run) - END_ROOM)


def _column_room(run: MountedRun, upright: bool = False) -> float:
    """Return the upright pipe length a run's furniture needs.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    upright : bool, default=False
        Whether a station may stand on an upright leg.

    Returns
    -------
    float
        Length along an upright pipe, or 0 if the run carries a station
        and ``upright`` is not set. A run carrying a station gets at
        least the pipe that holds each element where wanted.
    """
    from pandid.stations import StationAssembly

    station = any(isinstance(element, StationAssembly) for element in run.elements)
    if station and not upright:
        return 0.0
    lengths = [_level_length(element) for element in run.elements]
    room = (sum(lengths) + ALONG * (len(lengths) - 1) + NOZZLE_END + END
            + 2 * (TAP + ALONG) * len(run.taps))
    return max(room, _room(run)) if station else room


@contextmanager
def _pipe_view(fs: Flowsheet, units: list[Unit], pipes: list[Stream]) -> Iterator[None]:
    """Show the sheet as only the given units and pipes until exit.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to narrow.
    units : list[Unit]
        Units to show.
    pipes : list[Stream]
        Streams to show.

    Yields
    ------
    None
        Control while the narrowed view is in place.
    """
    saved_units, saved_streams = fs.units, fs.streams
    saved_ports = [(port, port.stream) for pipe in pipes for port in (pipe.source, pipe.dest)]
    saved_marks = [(stream, stream._is_recycle, stream.route) for stream in pipes]
    fs.units, fs.streams = list(units), list(pipes)
    for pipe in pipes:
        pipe.source.stream = pipe
        pipe.dest.stream = pipe
    try:
        yield
    finally:
        fs.units, fs.streams = saved_units, saved_streams
        for port, stream in reversed(saved_ports):
            port.stream = stream
        for stream, mark, route in saved_marks:
            stream._is_recycle = mark
            stream.route = route


def _routed_pipes(fs: Flowsheet, runs: list[MountedRun],
                  retained: list[Unit]) -> tuple[list[list[Point]], list[list[Point]]]:
    """Route each furnished pipe as one line between placed equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed equipment.
    runs : list[MountedRun]
        Furnished pipes.
    retained : list[Unit]
        Placed units the pipes run between.

    Returns
    -------
    tuple[list[list[Point]], list[list[Point]]]
        Each pipe's polyline, empty where routing failed, and the routed
        polylines of the other process streams between retained units.
    """
    from pandid.layout.cycles import break_cycles
    from pandid.layout.faces import select_faces
    from pandid.route_geometry import stream_polyline
    from pandid.routing import DefaultRouter
    from pandid.streams import Stream

    shown = set(retained)
    segments = {id(segment) for run in runs for segment in run.segments}
    others = [stream for stream in process_streams(fs)
              if id(stream) not in segments
              and stream.source.owner in shown and stream.dest.owner in shown]
    pipes = [Stream(name=run.segments[0].name, source=run.source, dest=run.dest,
                    kind="material") for run in runs]
    with _pipe_view(fs, retained, [*others, *pipes]):
        break_cycles(fs)
        select_faces(fs)
        DefaultRouter().route(fs)
        return ([stream_polyline(pipe) if pipe.route is not None else [] for pipe in pipes],
                [stream_polyline(other) for other in others if other.route is not None])


def _level(leg: Leg) -> bool:
    """Return whether a leg is horizontal.

    Parameters
    ----------
    leg : Leg
        Straight leg.

    Returns
    -------
    bool
        True if the leg is horizontal.
    """
    return abs(leg[0][1] - leg[1][1]) < 1e-6


def _candidate(unit: Unit, point: tuple[float, float], orientation: int,
               mirrored: bool) -> Frame:
    """Return a device frame centred on a point in a turn and mirror.

    Parameters
    ----------
    unit : Unit
        Device with a frame.
    point : tuple[float, float]
        Centre.
    orientation : int
        Clockwise turn in degrees: 0, 90, 180 or 270.
    mirrored : bool
        Left-right flip.

    Returns
    -------
    Frame
        Candidate frame.
    """
    original = unit.frame
    assert original is not None
    probe = replace(original, orientation=orientation, mirrored=mirrored)
    width, height = resolve_size(unit, probe)
    return replace(
        probe, x=point[0] - width / 2, y=point[1] - height / 2,
        w=width, h=height, label_pos=None, port_faces={},
    )


def _device_frame(unit: Unit, point: Point, leg: Leg) -> Frame:
    """Return a device frame on a leg point, piped in flow order.

    Poses run 0, 180, 90, 270 on a level leg or 90, 270, 180, 0
    upright, each unmirrored then mirrored, kept to a stated turn or
    mirror and to poses every stated nozzle face allows, else the
    current pose; with both a turn and a mirror stated, the stated
    turn mirrored the other way follows. The first pose with both
    nozzles on the leg, inlet upstream, wins; upright, with an
    actuator and no stated turn, the first with the actuator on the
    flow's left wins, else the first.

    Parameters
    ----------
    unit : Unit
        Device with a frame.
    point : Point
        Point on the leg.
    leg : Leg
        Leg to pipe along.

    Returns
    -------
    Frame
        Winning frame, else the first pose centred on the point.
    """
    (ax, ay), (bx, by) = leg
    level = _level(leg)
    forward = 1 if (bx - ax if level else by - ay) > 0 else -1
    along, across = (0, 1) if level else (1, 0)
    ordinate = ay if level else ax
    assert unit.frame is not None
    turned = unit._turn_stated
    first = 0 if level else 90
    turns = ([int(unit.frame.orientation)] if turned else [0] if _upright(unit)
             else [turn % 360 for turn in (first, first + 180, first + 90, first + 270)])
    flips = [bool(unit.frame.mirrored)] if unit._mirror_stated else [False, True]
    if turned and unit._mirror_stated:
        # Then try the stated turn end for end: the other mirror.
        flips.append(not flips[0])
    poses = [(turn, flip) for turn in turns for flip in flips
             if _reaches(unit, _candidate(unit, point, turn, flip))]
    if not poses:
        poses = [(int(unit.frame.orientation), bool(unit.frame.mirrored))]
    fits = []
    for turn, flip in poses:
        candidate = _candidate(unit, point, turn, flip)
        inlet = port_point(unit, candidate, "inlet")
        shift = ordinate - inlet[1 if level else 0]
        candidate = replace(candidate, x=candidate.x + (0.0 if level else shift),
                            y=candidate.y + (shift if level else 0.0))
        # Keep a pose with both nozzles on the leg's line, in flow order.
        inlet = port_point(unit, candidate, "inlet")
        outlet = port_point(unit, candidate, "outlet")
        if (abs(inlet[across] - ordinate) < 1.0 and abs(outlet[across] - ordinate) < 1.0
                and (outlet[along] - inlet[along]) * forward > 0):
            fits.append(candidate)
    if not fits and _upright(unit) and not turned:
        # Hang it upright from the leg by its outlet.
        candidate = _candidate(unit, point, *poses[0])
        outlet = port_point(unit, candidate, "outlet")
        return replace(candidate, x=candidate.x + point[0] - outlet[0],
                       y=candidate.y + point[1] - outlet[1])
    if not fits:
        return _candidate(unit, point, *poses[0])
    if turned or level or "actuator" not in unit.ports:
        return fits[0]
    # On an upright leg, put the actuator left of the flow.
    left = -forward
    return min(fits, key=lambda c: (port_point(unit, c, "actuator")[0] - ordinate) * left > 0)


def _heading(start: Point, end: Point) -> str:
    """Return the compass face from one point toward another.

    Parameters
    ----------
    start, end : Point
        Ends of a level or upright leg.

    Returns
    -------
    str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.
    """
    if _level((start, end)):
        return "E" if end[0] > start[0] else "W"
    return "S" if end[1] > start[1] else "N"


def _corner_frame(unit: Unit, into: Leg, out: Leg, head: float,
                  tail: float) -> Frame | None:
    """Return a device frame turning a pipe's corner through it.

    The first pose, of any turn and mirror the author left free, with
    its inlet facing back along the leg into the corner and its outlet
    facing along the leg out of it wins, set with each nozzle on its
    leg.

    Parameters
    ----------
    unit : Unit
        Device whose nozzles sit on adjacent faces.
    into, out : Leg
        Legs into and out of the corner.
    head, tail : float
        Length kept clear at the start of ``into`` and the end of
        ``out``.

    Returns
    -------
    Frame or None
        The frame, or None if no pose turns the corner within the legs.
    """
    from pandid.portgeom import port_anchor

    (a, corner), (_, b) = into, out
    want = (_heading(corner, a), _heading(corner, b))
    assert unit.frame is not None
    turns = ([int(unit.frame.orientation)] if unit._turn_stated
             else [0] if _upright(unit) else [0, 90, 180, 270])
    flips = [bool(unit.frame.mirrored)] if unit._mirror_stated else [False, True]
    for turn in turns:
        for flip in flips:
            frame = _candidate(unit, corner, turn, flip)
            if not _reaches(unit, frame) or tuple(
                    port_anchor(unit, frame, name)[2] for name in ("inlet", "outlet")) != want:
                continue
            inlet, outlet = (port_point(unit, frame, name) for name in ("inlet", "outlet"))
            # Put the inlet on the leg in and the outlet on the leg out.
            level = _level(into)
            frame = replace(frame, x=frame.x + corner[0] - (outlet if level else inlet)[0],
                            y=frame.y + corner[1] - (inlet if level else outlet)[1])
            inlet, outlet = (port_point(unit, frame, name) for name in ("inlet", "outlet"))
            if (path_length((a, inlet, corner)) <= path_length(into) + 1.0
                    and path_length((corner, outlet, b)) <= path_length(out) + 1.0
                    and path_length((a, inlet)) >= head and path_length((outlet, b)) >= tail):
                return frame
    return None


def _upright(unit: Unit) -> bool:
    """Return whether a device must stay as drawn, gravity being its function.

    Parameters
    ----------
    unit : Unit
        Device to check.

    Returns
    -------
    bool
        Whether its symbol is gravity-fixed (ISO 15519-1 11.4.2).
    """
    from pandid.render.symbols import default_registry

    return default_registry.for_unit(unit).gravity_fixed


def _reaches(unit: Unit, frame: Frame) -> bool:
    """Return whether each stated nozzle face resolves in a frame.

    Parameters
    ----------
    unit : Unit
        Unit with stated nozzle faces.
    frame : Frame
        Proposed frame.

    Returns
    -------
    bool
        True if every stated face can be drawn.
    """
    try:
        for name in unit._port_faces:
            port_point(unit, frame, name)
    except ValueError:
        return False
    return True


def _main_width(assembly: StationAssembly) -> float:
    """Return a station's run length, end nozzle to end nozzle.

    Parameters
    ----------
    assembly : StationAssembly
        Station to measure.

    Returns
    -------
    float
        Length of the main run.
    """
    station = assembly.station
    branch = {station.bypass, station.upstream_drain, station.downstream_drain}
    main = [unit for unit in station.members if unit not in branch]
    return sum(resolve_size(unit)[0] for unit in main) + assembly.gap * (len(main) - 1)


def _length(element: Element, leg: Leg, upright: bool = False) -> float:
    """Return the room an element takes along a leg.

    Parameters
    ----------
    element : Unit or StationAssembly
        Element to measure.
    leg : Leg
        Leg it sits on.
    upright : bool, default=False
        Whether a station may stand on an upright leg.

    Returns
    -------
    float
        Length, or infinity if the element cannot lie in line with it.
    """
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return _main_width(element) if upright or _level(leg) else float("inf")
    frame = _device_frame(element, (0.0, 0.0), leg)
    level = _level(leg)
    (ax, ay), (bx, by) = (port_point(element, frame, name) for name in ("inlet", "outlet"))
    if abs((ay - by) if level else (ax - bx)) > 1.0:
        return float("inf")
    return frame.w if level else frame.h


def _level_length(element: Element) -> float:
    """Return an element's length along its pipe before it is set.

    Parameters
    ----------
    element : Unit or StationAssembly
        Element to measure.

    Returns
    -------
    float
        Length along the pipe.
    """
    from pandid.portgeom import port_offset
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return _main_width(element)
    width, height = resolve_size(element)
    (ax, ay), (bx, by) = (port_offset(element, name, slot(element)) for name in ("inlet", "outlet"))
    return height if abs(by - ay) > abs(bx - ax) else width


def _turned(assembly: StationAssembly, point: Point, down: bool,
            flip: bool) -> dict[Unit, Frame]:
    """Return a station's frames turned to run up or down through a point.

    The station is laid out level, flowing west if ``flip`` is set,
    else east, and turned a quarter about its main run's middle.

    Parameters
    ----------
    assembly : StationAssembly
        Station to lay out.
    point : Point
        Middle of the main run.
    down : bool
        Whether flow runs down.
    flip : bool
        Lay the station out flowing west before turning it.

    Returns
    -------
    dict[Unit, Frame]
        Frame of each member.
    """
    from pandid.layout.station import _station_frames

    width = _main_width(assembly)
    turn = 90 if down != flip else 270
    sign = 1 if turn == 90 else -1
    frames = {}
    for unit, frame in _station_frames(assembly, -width / 2, 0.0, flip).items():
        cx, cy = -sign * frame.cy, sign * frame.cx
        frames[unit] = replace(frame, x=point[0] + cx - frame.h / 2,
                               y=point[1] + cy - frame.w / 2, w=frame.h, h=frame.w,
                               orientation=(int(frame.orientation) + turn) % 360)
    return frames


def _frames_at(element: Element, centre: float, leg: Leg) -> list[dict[Unit, Frame]]:
    """Return ways to centre an element a distance along a leg.

    A station on an upright leg is turned to run along it, with its
    bypass on either side.

    Parameters
    ----------
    element : Unit or StationAssembly
        Element to place.
    centre : float
        Distance from the leg start.
    leg : Leg
        Leg to place on.

    Returns
    -------
    list[dict[Unit, Frame]]
        Frame of each unit the element draws, for each way, best first.
    """
    from pandid.layout.station import _station_frames
    from pandid.stations import StationAssembly

    (ax, ay), (bx, by) = leg
    total = path_length(leg)
    t = centre / total if total else 0.5
    point = (ax + t * (bx - ax), ay + t * (by - ay))
    if isinstance(element, StationAssembly):
        if not _level(leg):
            return [_turned(element, point, by > ay, flip) for flip in (False, True)]
        width = _main_width(element)
        return [_station_frames(element, point[0] - width / 2, point[1], bx < ax)]
    return [{element: _device_frame(element, point, leg)}]


def _clear(frames: dict[Unit, Frame], obstacles: list[Unit], level: bool,
           zones: list[Box], pipes: list[list[Point]], ends: tuple[Unit, ...] = (),
           exit_gap: float = 0.0, room: tuple[float, float] = (ALONG, GAP)) -> bool:
    """Return whether proposed frames keep clear of other units.

    Each frame keeps ``room`` along the pipe or across it from every
    obstacle and zone. Each signal exit keeps ``exit_gap`` from
    obstacles, zones and end units, and stays off pipes.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Proposed frames.
    obstacles : list[Unit]
        Placed units to keep clear of.
    level : bool
        Whether the pipe is horizontal here.
    zones : list[Box]
        Ground covered by stations, balloon taps and earlier elements.
    pipes : list[list[Point]]
        Routed lines the signal exits keep off.
    ends : tuple[Unit, ...], optional
        The pipe's own end units.
    exit_gap : float, default=0.0
        Clearance each signal exit keeps.
    room : tuple[float, float], default=(ALONG, GAP)
        Clearance each frame keeps along the pipe, then across it.

    Returns
    -------
    bool
        True if the frames are clear.
    """
    dx, dy = room if level else room[::-1]
    boxes = [*(unit_box(other, other.frame) for other in obstacles if other.frame is not None),
             *zones]
    for unit, frame in frames.items():
        left, top, right, bottom = unit_box(unit, frame)
        for o_left, o_top, o_right, o_bottom in boxes:
            if (right + dx > o_left and o_right + dx > left
                    and bottom + dy > o_top and o_bottom + dy > top):
                return False
    lines = [(a, b) for line in pipes for a, b in zip(line, line[1:])]
    boxes += [unit_box(unit, unit.frame) for unit in ends if unit.frame is not None]
    for left, top, right, bottom in _signal_exits(frames):
        if any(boxes_overlap((left, top, right, bottom), o, exit_gap) for o in boxes):
            return False
        if any(max(a[0], b[0]) >= left and right >= min(a[0], b[0])
               and max(a[1], b[1]) >= top and bottom >= min(a[1], b[1]) for a, b in lines):
            return False
    return True


def _bound(frames: dict[Unit, Frame]) -> Box:
    """Return the box around every frame.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Frames to bound.

    Returns
    -------
    Box
        Left, top, right and bottom.
    """
    drawn = [unit_box(unit, frame) for unit, frame in frames.items()]
    return (min(b[0] for b in drawn), min(b[1] for b in drawn),
            max(b[2] for b in drawn), max(b[3] for b in drawn))


def _footprint(assembly: StationAssembly, frames: dict[Unit, Frame]) -> list[Box]:
    """Return the box of each member of a station and of its bypass loop.

    Parameters
    ----------
    assembly : StationAssembly
        Station.
    frames : dict[Unit, Frame]
        Frame of each member.

    Returns
    -------
    list[Box]
        One box per member, then the box around the bypass valve and
        the tees it joins, if any.
    """
    station = assembly.station
    boxes = [unit_box(unit, frame) for unit, frame in frames.items()]
    if station.bypass is not None:
        loop = (station.tees[0], station.bypass, station.tees[-1])
        boxes.append(_bound({unit: frames[unit] for unit in loop}))
    return boxes


def _on_pipes(frames: dict[Unit, Frame], pipes: list[list[Point]], leg: Leg) -> bool:
    """Return whether a pipe other than a leg's own line enters a frame.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Proposed frames on the leg.
    pipes : list[list[Point]]
        Routed lines.
    leg : Leg
        Leg the frames sit on.

    Returns
    -------
    bool
        True if a segment off the leg's line overlaps any frame.
    """
    axis = 1 if _level(leg) else 0
    line = leg[0][axis]
    boxes = [unit_box(unit, frame) for unit, frame in frames.items()]
    return any(boxes_overlap(box, (min(a[0], b[0]), min(a[1], b[1]),
                                   max(a[0], b[0]), max(a[1], b[1])))
               for points in pipes for a, b in zip(points, points[1:])
               if abs(a[axis] - line) > 1e-6 or abs(b[axis] - line) > 1e-6
               for box in boxes)


def _signal_exits(frames: dict[Unit, Frame]) -> list[Box]:
    """Return the stand-off box beyond each connected signal port.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Proposed frames.

    Returns
    -------
    list[Box]
        One box per connected signal port.
    """
    from pandid.portgeom import COMPASS, port_anchor

    out = []
    for unit, frame in frames.items():
        for port in unit.ports.values():
            if port.role != "signal" or port.stream is None:
                continue
            x, y, face = port_anchor(unit, frame, port.name)
            ux, uy = END * COMPASS[face][0], END * COMPASS[face][1]
            out.append((min(x, x + ux), min(y, y + uy), max(x, x + ux), max(y, y + uy)))
    return out


def _commit(frames: dict[Unit, Frame], obstacles: list[Unit]) -> None:
    """Install frames and slots, and add the units to ``obstacles``.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Frames to install.
    obstacles : list[Unit]
        Placed units; extended in place.
    """
    for unit, frame in frames.items():
        unit.frame = frame
        placed = slot(unit)
        placed.x, placed.y, placed.w, placed.h = frame.x, frame.y, frame.w, frame.h
        placed.orientation = frame.orientation
        placed.mirrored, placed.mirror_y = frame.mirrored, frame.mirror_y
        obstacles.append(unit)


def _margins(index: int, count: int) -> tuple[float, float]:
    """Return the length kept clear at the start and end of a leg.

    Parameters
    ----------
    index : int
        Leg index.
    count : int
        Number of legs.

    Returns
    -------
    tuple[float, float]
        Start and end margins.
    """
    return (NOZZLE_END if index == 0 else END,
            NOZZLE_END if index == count - 1 else END)


def _along(legs: list[Leg], point: Point) -> float:
    """Return the distance along a pipe of a point's projection.

    Parameters
    ----------
    legs : list[Leg]
        Pipe legs in flow order.
    point : Point
        Point to project.

    Returns
    -------
    float
        Distance; below 0 before the start, past the end after it.
    """
    best: tuple[float, float] | None = None
    travelled = 0.0
    for index, leg in enumerate(legs):
        (ax, ay), (bx, by) = leg
        size = path_length(leg)
        level = _level(leg)
        ahead = ((point[0] - ax) * (1 if bx >= ax else -1) if level
                 else (point[1] - ay) * (1 if by >= ay else -1))
        across = abs(point[1] - ay) if level else abs(point[0] - ax)
        lo = -float("inf") if index == 0 else 0.0
        hi = float("inf") if index == len(legs) - 1 else size
        reach = min(max(ahead, lo), hi)
        miss = across + abs(ahead - reach)
        if best is None or miss < best[0]:
            best = (miss, travelled + reach)
        travelled += size
    assert best is not None
    return best[1]


def _point_at(legs: list[Leg], distance: float) -> tuple[Point, bool]:
    """Return the point at a distance along a pipe, clamped to its ends.

    Parameters
    ----------
    legs : list[Leg]
        Pipe legs in flow order.
    distance : float
        Distance from the start.

    Returns
    -------
    tuple[Point, bool]
        The point, and whether its leg is level.
    """
    for leg in legs:
        (ax, ay), (bx, by) = leg
        size = path_length(leg)
        if distance <= size:
            t = max(distance, 0.0) / size if size else 0.0
            return (ax + t * (bx - ax), ay + t * (by - ay)), _level(leg)
        distance -= size
    return legs[-1][1], _level(legs[-1])


def _wanted(run: MountedRun, total: float, along: Callable[[Port], float] | None = None,
            extra: tuple[tuple[Port, Port, float], ...] = ()) -> list[float]:
    """Return the wanted centre distance along the pipe of each element.

    An element whose place has both line ends located sits at its
    fraction between them; any other is spread evenly. Extra places
    follow, mid-pipe where one cannot be located.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    total : float
        Pipe length.
    along : callable or None, optional
        Distance along the pipe of a nozzle that is not on it.
    extra : tuple[tuple[Port, Port, float], ...], optional
        Further places to locate, such as balloon taps.

    Returns
    -------
    list[float]
        Wanted distances, elements first.
    """
    count = len(run.elements)
    even = [(k + 1) / (count + 1) * total for k in range(count)]

    def anchor(port: Port, side: float) -> float | None:
        """Return a line end nozzle's distance along the pipe.

        Parameters
        ----------
        port : Port
            Line end nozzle.
        side : float
            +1 for the outlet a line leaves, -1 for the inlet it enters.

        Returns
        -------
        float or None
            Distance, or None if the nozzle cannot be located.
        """
        if port is run.source:
            return 0.0
        if port is run.dest:
            return total
        for k, element in enumerate(run.elements):
            if port.owner in _members(element):
                return even[k] + side * _level_length(element) / 2
        return None if along is None else along(port)

    out = []
    for k, place in enumerate([*run.places, *extra]):
        low = high = None
        if place is not None:
            low, high = anchor(place[0], 1.0), anchor(place[1], -1.0)
        if place is None or low is None or high is None:
            out.append(even[k] if k < count else total / 2)
        else:
            out.append(low + place[2] * (high - low))
    return out


def _room(run: MountedRun) -> float:
    """Return the shortest pipe that holds each element where wanted.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.

    Returns
    -------
    float
        Pipe length, ignoring gaps that no length opens.
    """
    start, unit = _wanted(run, 0.0), _wanted(run, 1.0)
    slope = [b - a for a, b in zip(start, unit)]
    lengths = [_level_length(element) for element in run.elements]
    rules = [(slope[0], start[0] - lengths[0] / 2, NOZZLE_END),
             (1 - slope[-1], -start[-1] - lengths[-1] / 2, NOZZLE_END)]
    rules += [(slope[k] - slope[k - 1], start[k] - start[k - 1],
               (lengths[k - 1] + lengths[k]) / 2 + ALONG) for k in range(1, len(lengths))]
    # Each rule reads slope * length + offset >= floor.
    return max([(floor - offset) / rate for rate, offset, floor in rules if rate > 1e-9],
               default=0.0)


def _assign(run: MountedRun, legs: list[Leg], wanted: list[float],
            upright: bool = False) -> list[list[int]]:
    """Return ways to put elements on legs, best first.

    Single legs that hold the whole chain come first, level before
    upright, then nearest the wanted middle. The last way deals each
    element onto the first leg with room from the previous element's
    on, else the roomiest it pipes along, else the longest leg.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    legs : list[Leg]
        Pipe legs in flow order.
    wanted : list[float]
        Wanted centre distance of each element.
    upright : bool, default=False
        Whether a station may stand on an upright leg.

    Returns
    -------
    list[list[int]]
        Plans, each giving every element's leg index.
    """
    room = [path_length(leg) - sum(_margins(index, len(legs))) + ALONG
            for index, leg in enumerate(legs)]
    need = [[_length(element, leg, upright) + ALONG for leg in legs] for element in run.elements]
    starts = [0.0, *accumulate(map(path_length, legs))]
    middle = sum(wanted) / len(wanted)

    def distance(index: int) -> float:
        """Return how far a leg's middle is from the wanted middle.

        Parameters
        ----------
        index : int
            Leg index.

        Returns
        -------
        float
            Distance along the pipe.
        """
        return abs(starts[index] + path_length(legs[index]) / 2 - middle)

    whole = sorted((index for index in range(len(legs))
                    if sum(row[index] for row in need) <= room[index]),
                   key=lambda index: (not _level(legs[index]), distance(index), index))
    plans = [[index] * len(run.elements) for index in whole]
    assigned, used, cursor = [], [0.0] * len(legs), 0
    for row in need:
        choice = next((index for index in range(cursor, len(legs))
                       if used[index] + row[index] <= room[index]), None)
        if choice is None:
            usable = [index for index in range(cursor, len(legs)) if row[index] != float("inf")]
            choice = max(usable or [max(range(len(legs)), key=lambda i: path_length(legs[i]))],
                         key=lambda index: room[index] - used[index])
        if row[choice] != float("inf"):
            used[choice] += row[choice]
        assigned.append(choice)
        cursor = max(cursor, choice)
    return [*plans, assigned]


def _centres(wanted: list[float], lengths: list[float], size: float,
             head: float, tail: float) -> list[float]:
    """Return ordered, spaced centres near the wanted ones.

    Space them evenly when they do not fit.

    Parameters
    ----------
    wanted : list[float]
        Wanted centre distances from the leg start.
    lengths : list[float]
        Element lengths along the leg.
    size : float
        Leg length.
    head, tail : float
        Length kept clear at the leg's start and end.

    Returns
    -------
    list[float]
        Centre distances from the leg start.
    """
    if sum(lengths) + ALONG * (len(lengths) - 1) + head + tail > size:
        free = max(0.0, size - sum(lengths))
        step = free / (len(lengths) + 1)
        centres, cursor = [], 0.0
        for length in lengths:
            cursor += step
            centres.append(cursor + length / 2)
            cursor += length
        return centres
    centres = [min(max(w, head + n / 2), size - tail - n / 2) for w, n in zip(wanted, lengths)]
    for k in range(1, len(centres)):
        centres[k] = max(centres[k], centres[k - 1] + (lengths[k - 1] + lengths[k]) / 2 + ALONG)
    for k in range(len(centres) - 1, -1, -1):
        limit = size - tail - lengths[k] / 2
        if k + 1 < len(centres):
            limit = min(limit, centres[k + 1] - (lengths[k] + lengths[k + 1]) / 2 - ALONG)
        centres[k] = min(centres[k], limit)
    return centres


def _off_header(run: MountedRun) -> bool:
    """Return whether a pipe joins a header to a unit, its elements free.

    That is a pipe from a splitter to a unit, or to a mixer from a unit,
    where the unit is no splitter, mixer or boundary flag, with no
    element set ``on=``.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.

    Returns
    -------
    bool
        True for such a pipe.
    """
    source, dest = run.source.owner.kind, run.dest.owner.kind
    unit = dest if source == "splitter" else source if dest == "mixer" else None
    return unit not in (None, "splitter", "mixer", "feed", "product") and not any(run.places)


def _fanned(run: MountedRun, legs: list[Leg]) -> tuple[list[Leg], list[float]] | None:
    """Return a header lateral's legs turned at its header, and centres.

    A header lateral is a pipe :func:`_off_header` takes that runs as
    one level leg, or whose level end legs, at two heights, run the same
    way; the second kind turns :data:`END` from the header. Its elements
    pack against the end away from the header, :data:`ALONG` apart and
    from its nozzle.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    legs : list[Leg]
        Its legs in flow order.

    Returns
    -------
    tuple[list[Leg], list[float]] or None
        The turned legs and each element's centre distance along them,
        or None if the pipe is no header lateral.
    """
    if not (_off_header(run) and _level(legs[0]) and _level(legs[-1])):
        return None
    head = run.source.owner.kind == "splitter"
    (a, after), (before, b) = legs[0], legs[-1]
    sign = 1.0 if after[0] > a[0] else -1.0
    x = a[0] + sign * END if head else b[0] - sign * END
    if len(legs) == 1:
        turned = legs
    elif (abs(a[1] - b[1]) < 1e-6 or (b[0] - before[0]) * sign <= 0
            or not 0 < (x - a[0]) * sign < (b[0] - a[0]) * sign):
        return None
    else:
        turned = [(a, (x, a[1])), ((x, a[1]), (x, b[1])), ((x, b[1]), b)]
    lengths = [_level_length(element) for element in run.elements]
    if head:
        total = sum(map(path_length, turned))
        return turned, [total - sum(n + ALONG for n in lengths[k:]) + n / 2
                        for k, n in enumerate(lengths)]
    return turned, [sum(n + ALONG for n in lengths[:k + 1]) - n / 2
                    for k, n in enumerate(lengths)]


def _set_run(run: MountedRun, points: list[Point], obstacles: list[Unit],
             zones: list[Box], pipes: list[list[Point]], exit_gap: float = 0.0,
             fan: bool = False, packages: tuple[tuple[set[Unit], Box], ...] = (),
             upright: bool = False, wanted: list[float] | None = None,
             spread: int = 0) -> bool:
    """Set a pipe's elements on its routed polyline.

    With no route, one straight leg from the source nozzle along the
    larger offset to the destination stands in. With ``fan`` set, a
    header lateral is set as :func:`_fanned` turns and packs it. Each
    element keeps clear of the ground of each package it has no unit
    in. With ``spread`` set, where no way keeps :data:`ALONG` along
    the pipe and the elements would be drawn over a unit, each keeps
    :data:`GAP` all round and off every other pipe on the nearest spot
    on the side ``spread`` names, if any way has one.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    points : list[Point]
        Its routed polyline; empty if routing failed.
    obstacles : list[Unit]
        Units already drawn; extended with the elements set.
    zones : list[Box]
        Ground covered by stations set so far; extended in place.
    pipes : list[list[Point]]
        Routed lines between placed equipment, every pipe included.
    exit_gap : float, default=0.0
        Clearance each element's signal exits keep from other units.
    fan : bool, default=False
        Set a header lateral as :func:`_fanned` turns and packs it.
    packages : tuple[tuple[set[Unit], Box], ...], optional
        Each package's units and the ground they cover.
    upright : bool, default=False
        Let a station stand on an upright leg.
    wanted : list[float] or None, optional
        Wanted centre distance of each element along ``points``, in
        place of the one its place gives.
    spread : int, default=0
        -1 to move elements drawn over a unit back along the pipe, +1
        to move them on along it, 0 to leave them.

    Returns
    -------
    bool
        True if every element found clear room.
    """
    from pandid.stations import StationAssembly

    source, dest = run.source.owner, run.dest.owner
    assert source.frame is not None and dest.frame is not None
    legs: list[Leg] = list(zip(points, points[1:]))
    if not legs:
        a = port_point(source, source.frame, run.source.name)
        b = port_point(dest, dest.frame, run.dest.name)
        legs = [(a, (b[0], a[1])) if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else (a, (a[0], b[1]))]
    fanned = _fanned(run, legs) if fan else None
    if fanned is not None:
        legs = fanned[0]
    count = len(run.elements)
    want = _wanted(run, sum(path_length(leg) for leg in legs),
                   lambda port: _along(legs, port_point(port.owner, port.owner.frame, port.name)),
                   run.taps)
    # Keep a balloon's reach clear around its tap on an upright leg.
    tap_zones = []
    for distance in want[count:]:
        (x, y), level = _point_at(legs, distance)
        if not level:
            tap_zones.append((x - 1.0, y - TAP, x + 1.0, y + TAP))
    want = wanted or (want[:count] if fanned is None else fanned[1])
    angled = next((i for i, element in enumerate(run.elements)
                   if not isinstance(element, StationAssembly) and _turns(element)), None)
    if angled is not None:
        return _set_corner(run, angled, legs, want, obstacles, zones, pipes, exit_gap,
                           packages, spread)
    starts = [0.0, *accumulate(map(path_length, legs))]
    # The pipe's own end units keep only the leg margin.
    others = [unit for unit in obstacles if unit is not source and unit is not dest]

    def attempt(assigned: list[int], strict: bool, room: tuple[float, float] = (ALONG, GAP),
                side: int = 0) -> list[dict[Unit, Frame]] | None:
        """Return each element's frames on its assigned leg.

        Parameters
        ----------
        assigned : list[int]
            Leg index of each element.
        strict : bool
            Return None if a leg's elements cannot fit or find room.
        room : tuple[float, float], default=(ALONG, GAP)
            Clearance each element keeps from other units along the
            pipe, then across it.
        side : int, default=0
            -1 to search only back along the leg from each wanted
            centre, +1 only on along it, 0 both ways; either way set,
            each element also stays off every other pipe.

        Returns
        -------
        list[dict[Unit, Frame]] or None
            Frames per element, or None on a strict failure.
        """
        placed: list[dict[Unit, Frame]] = []
        mine = [*zones, *tap_zones]
        for index in sorted(set(assigned)):
            leg, size, level = legs[index], path_length(legs[index]), _level(legs[index])
            head, tail = _margins(index, len(legs))
            group = [i for i, a in enumerate(assigned) if a == index]
            lengths = [min(_length(run.elements[i], leg, upright), size) for i in group]
            if strict and sum(lengths) + ALONG * (len(group) - 1) + head + tail > size:
                return None
            centres = _centres([want[i] - starts[index] for i in group], lengths, size, head, tail)
            floor = 0.0
            for i, length, centre in zip(group, lengths, centres):
                fenced = [*mine, *(box for held, box in packages
                                   if not held.intersection(_members(run.elements[i])))]
                low = max(length / 2 + head, floor + length / 2)
                high = size - length / 2 - tail
                chosen = None
                element = run.elements[i]
                # A station turned upright also keeps clear of the end units.
                turned = element if isinstance(element, StationAssembly) and not level else None
                ends = [unit_box(end, end.frame) for end in (source, dest)]
                # Search the whole leg, nearest spot first.
                reach = int(size / NUDGE_STEP) + 1
                for step in sorted(range(-reach, reach + 1), key=abs):
                    at = centre + step * NUDGE_STEP
                    if step * side < 0 or not low - 1e-6 <= at <= high + 1e-6:
                        continue
                    chosen = next(((at, frames) for frames in _frames_at(element, at, leg)
                                   if _clear(frames, others, level, fenced, pipes, (source, dest),
                                             exit_gap, room)
                                   and not (side and _on_pipes(frames, pipes, leg))
                                   and (turned is None or not any(
                                       boxes_overlap(box, end, GAP)
                                       for box in _footprint(turned, frames) for end in ends))),
                                  None)
                    if chosen is not None:
                        break
                if chosen is None:
                    if strict:
                        return None
                    at = min(max(centre, low), max(low, high)) if high >= low else size / 2
                    chosen = (at, _frames_at(element, at, leg)[0])
                mine.append(_bound(chosen[1]))
                placed.append(chosen[1])
                floor = chosen[0] + length / 2 + ALONG
        return placed

    plans = _assign(run, legs, want, upright)
    placed = next((p for p in (attempt(plan, True) for plan in plans) if p is not None), None)
    roomy = placed is not None
    if placed is None:
        placed = attempt(plans[0], False) or []
        drawn = [unit_box(unit, unit.frame) for unit in obstacles if unit.frame is not None]
        if spread and any(boxes_overlap(unit_box(unit, frame), box, -_BODY_TOL)
                          for frames in placed for unit, frame in frames.items() for box in drawn):
            placed = next((p for p in (attempt(plan, True, (GAP, GAP), spread) for plan in plans)
                           if p is not None), placed)
    for frames in placed:
        _commit(frames, obstacles)
        if len(frames) > 1:
            zones.append(_bound(frames))
    return roomy


def _ground(pkg: Package, placed: set[Unit]) -> Box:
    """Return the frame round a package's units placed so far.

    Each unit counts with room for a tag on either side.

    Parameters
    ----------
    pkg : Package
        Package with at least one unit in ``placed``.
    placed : set[Unit]
        Units with frames.

    Returns
    -------
    Box
        Left, top, right, bottom.
    """
    boxes = [(unit_box(u, u.frame), tag_reach(u)) for u in pkg.units
             if u in placed and u.frame is not None]
    return boundary(pkg, [(b[0] - reach, b[1], b[2] + reach, b[3]) for b, reach in boxes])


def _fence(run: MountedRun, group: dict[Unit, int]) -> float:
    """Return the level pipe a pipe's package ends keep its furniture off.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    group : dict[Unit, int]
        Package index of each unit in a package.

    Returns
    -------
    float
        The package margin and the reach of a tag beside the end unit,
        for each end in a package that holds not every element.
    """
    held = [group.get(unit) for element in run.elements for unit in _members(element)]
    return sum(PACKAGE_MARGIN + tag_reach(port.owner) for port in (run.source, run.dest)
               if (p := group.get(port.owner)) is not None and any(h != p for h in held))


def _set_corner(run: MountedRun, index: int, legs: list[Leg], wanted: list[float],
                obstacles: list[Unit], zones: list[Box], pipes: list[list[Point]],
                exit_gap: float, packages: tuple[tuple[set[Unit], Box], ...],
                spread: int = 0) -> bool:
    """Set a pipe's device that turns it at a corner, then the rest.

    The corner nearest the device's wanted distance where
    :func:`_corner_frame` turns the pipe clear of other units and of
    the ground of each package it is not in takes it, and its box joins
    ``zones``; the furniture before it is set on the pipe up to its
    inlet, and the furniture after it on the pipe from its outlet. With
    no such corner, the device keeps its place among the equipment and
    the rest is set on the whole pipe.

    Parameters
    ----------
    run : MountedRun
        Furnished pipe.
    index : int
        Index of the device among the pipe's elements.
    legs : list[Leg]
        Pipe legs in flow order.
    wanted : list[float]
        Wanted centre distance of each element along the pipe.
    obstacles : list[Unit]
        Units already drawn; extended with the elements set.
    zones : list[Box]
        Ground covered by stations set so far; extended in place.
    pipes : list[list[Point]]
        Routed lines between placed equipment.
    exit_gap : float
        Clearance each element's signal exits keep from other units.
    packages : tuple[tuple[set[Unit], Box], ...]
        Each package's units and the ground they cover.
    spread : int, default=0
        Way to move furniture drawn over a unit, as :func:`_set_run`
        takes it.

    Returns
    -------
    bool
        True if every element found clear room.
    """
    from pandid.stations import StationAssembly

    unit = run.elements[index]
    assert not isinstance(unit, StationAssembly) and unit.frame is not None
    source, dest = run.source.owner, run.dest.owner
    others = [other for other in obstacles if other is not source and other is not dest]
    fenced = [*zones, *(box for held, box in packages if unit not in held)]
    points = [legs[0][0], *(leg[1] for leg in legs)]
    starts = [0.0, *accumulate(map(path_length, legs))]
    for k in sorted(range(1, len(legs)), key=lambda k: abs(starts[k] - wanted[index])):
        frame = _corner_frame(unit, legs[k - 1], legs[k], _margins(k - 1, len(legs))[0],
                              _margins(k, len(legs))[1])
        if frame is not None and _clear({unit: frame}, others, _level(legs[k - 1]), fenced,
                                        pipes, (source, dest), exit_gap):
            break
    else:
        obstacles.append(unit)
        rest = MountedRun(run.segments, run.elements[:index] + run.elements[index + 1:],
                          run.places[:index] + run.places[index + 1:], run.taps)
        if rest.elements:
            _set_run(rest, points, obstacles, zones, pipes, exit_gap, packages=packages,
                     wanted=wanted[:index] + wanted[index + 1:], spread=spread)
        return False
    _commit({unit: frame}, obstacles)
    zones.append(unit_box(unit, frame))
    inlet, outlet = (port_point(unit, frame, name) for name in ("inlet", "outlet"))
    after = starts[k] + path_length((points[k], outlet))
    roomy = True
    for part, line, want in (
            (MountedRun(run.segments[:index + 1], run.elements[:index], run.places[:index]),
             [*points[:k], inlet], wanted[:index]),
            (MountedRun(run.segments[index + 1:], run.elements[index + 1:],
                        run.places[index + 1:]),
             [outlet, *points[k + 1:]], [w - after for w in wanted[index + 1:]])):
        if part.elements:
            roomy = _set_run(part, line, obstacles, zones, pipes, exit_gap,
                             packages=packages, wanted=want, spread=spread) and roomy
    return roomy


def place_mounted(fs: Flowsheet, runs: list[MountedRun]) -> None:
    """Place equipment and its drivers, loose stations, then furniture.

    Each furnished pipe reserves its furniture's room in the equipment
    solve (:class:`pandid.layout.layered.Link`). With
    ``fs._pin_balloons`` set, furniture keeps clear of each fixed
    balloon (:func:`~pandid.layout.halo.fixed_balloons`) and its chain. With
    ``fs._exit_clear`` set, each signal exit keeps
    :data:`~pandid.routing.visibility.MARGIN` from other units;
    ``fs._exit_tight`` records whether any comes closer. With
    ``fs._fan_out`` set, each header lateral is set as :func:`_fanned`
    turns and packs it; ``fs._fannable`` records whether any pipe is one.
    With ``fs._upright_stations`` set, a station may stand on an upright
    leg, its room budgeted between the units it joins;
    ``fs._crowded_station`` records whether any station on a pipe with
    an upright leg found no clear room.
    With ``fs._corner_valves`` set, ``runs`` may hold devices that turn
    their pipe, such as angle valves: the equipment is placed with each
    as a unit, as :func:`mounted_runs` with ``angle`` unset finds it,
    then each is set at a corner of its pipe. ``fs._angle_valves``
    records whether any pipe carries such a device.
    ``fs._spread`` is passed to :func:`_set_run` as ``spread``, and
    ``fs._furniture_over`` records whether any furniture is drawn over
    another unit.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with fresh solver slots and recycle marks.
    runs : list[MountedRun]
        Furnished pipes from :func:`mounted_runs`; may be empty.
    """
    from pandid.layout.drives import driver_pads, hung, place_drivers
    from pandid.layout.layered import Link, place_equipment
    from pandid.layout.station import place_stations
    from pandid.stations import StationAssembly

    fs._angle_valves = any(not isinstance(element, StationAssembly) and _turns(element)
                           for run in mounted_runs(fs, True) for element in run.elements)
    laid = mounted_runs(fs) if fs._corner_valves else runs
    members = {unit for run in laid for element in run.elements for unit in _members(element)}
    hangs = hung(fs)
    drivers = [hang.end.owner for hang in hangs]
    retained = [unit for unit in process_units(fs) if unit not in members and unit not in drivers]
    shown = set(retained)
    loose = [a for a in fs._station_assemblies if not members.intersection(a.station.members)]
    inside = {id(segment) for run in laid for segment in run.segments}
    group = {u: i for i, p in enumerate(fs.packages) for u in p.units}
    place_equipment(fs, retained, [
        *(Link(s.source, s.dest, s.is_recycle) for s in process_streams(fs)
          if id(s) not in inside and s.source.owner in shown and s.dest.owner in shown
          and s.source.owner is not s.dest.owner),
        *(Link(run.source, run.dest, any(s.is_recycle for s in run.segments),
               _chain_width(run) + _fence(run, group), _column_room(run, fs._upright_stations),
               fs._fan_out and _off_header(run))
          for run in laid),
        *(Link(s.source, s.dest) for s in fs.streams
          if s.kind == MECHANICAL and s.source.owner in shown and s.dest.owner in shown)],
        driver_pads(hangs))
    place_drivers(hangs)
    retained += drivers
    for unit in members:
        placed = slot(unit)
        unit.frame = Frame(x=0.0, y=0.0, w=placed.w, h=placed.h,
                           orientation=placed.orientation, mirrored=placed.mirrored,
                           mirror_y=placed.mirror_y)
    place_stations(fs, loose)
    if not runs:
        return
    # Lift each device that turns its pipe out of the equipment.
    members = {unit for run in runs for element in run.elements for unit in _members(element)}
    retained = [unit for unit in retained if unit not in members]
    shown = set(retained)
    routes, lines = _routed_pipes(fs, runs, retained)
    fs._fannable = any(_fanned(run, list(zip(points, points[1:]))) is not None
                       for run, points in zip(runs, routes) if len(points) > 1)
    obstacles = list(retained)
    zones: list[Box] = fixed_balloons(fs, balloon_pads(fs)) if fs._pin_balloons else []
    exit_gap = MARGIN if fs._exit_clear else 0.0
    packages = tuple((set(p.units), _ground(p, shown)) for p in fs.packages
                     if shown.intersection(p.units))
    crowded = False
    for i in sorted(range(len(runs)), key=lambda i: (-_chain_width(runs[i]), i)):
        roomy = _set_run(runs[i], routes[i], obstacles, zones, [*lines, *routes], exit_gap,
                         fs._fan_out, packages, fs._upright_stations, spread=fs._spread)
        crowded = crowded or (
            not roomy and any(not _level(leg) for leg in zip(routes[i], routes[i][1:]))
            and any(isinstance(element, StationAssembly) for element in runs[i].elements))
    fs._crowded_station = crowded
    # Note a signal exit drawn within MARGIN of another unit.
    fs._exit_tight = any(boxes_overlap(box, unit_box(other, other.frame), MARGIN)
                         for unit in members if unit.frame is not None
                         for box in _signal_exits({unit: unit.frame})
                         for other in obstacles if other is not unit and other.frame is not None)
    fs._furniture_over = any(
        boxes_overlap(unit_box(unit, unit.frame), unit_box(other, other.frame), -_BODY_TOL)
        for unit in members if unit.frame is not None
        for other in obstacles if other is not unit and other.frame is not None)
