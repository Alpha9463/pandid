"""Set pipe furniture on its routed pipe after placing the equipment.

Furniture is every unpinned valve, reducer or fitting on a material line,
and every valve station none of whose members is pinned, however it was
written: put in a line with ``on=`` or wired with ``connect()``. A pinned
device is drawn where it is pinned, like equipment, and splits the line.

:func:`place_mounted` lays out a sheet that has furniture:

1. Equipment is placed with each furnished pipe contracted to one link
   between its two end nozzles (:mod:`pandid.layout.layered`).
2. The contracted pipes are routed on a view of the sheet that holds only
   that equipment.
3. Each pipe's devices and stations are set in flow order on straight legs
   of its routed pipe, near their positions on the line, clear of other units.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable, Iterator, Union

from pandid.geometry import Frame
from pandid.layout.stages import process_streams, process_units, slot
from pandid.portgeom import port_point, resolve_size, unit_box

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.stations import StationAssembly
    from pandid.streams import Stream
    from pandid.units import Unit

    Element = Union[Unit, StationAssembly]

#: Length kept clear at a leg end that turns a corner, one nozzle stand-off.
END = 25.0

#: Length kept clear at a leg end that is the pipe's own end nozzle.
NOZZLE_END = 8.0

#: Clearance kept across a pipe between an element and another unit.
GAP = 8.0

#: Clearance kept along a pipe between an element and anything else, its
#: neighbours on the pipe included, so each keeps room for its tag.
ALONG = 25.0

#: Reach of a balloon from the point where it taps a pipe.
TAP = 45.0

#: Step, in pixels, of the search along a leg for a clear spot.
NUDGE_STEP = 5.0

_INLINE_KINDS = frozenset({"valve", "reducer", "fitting"})

Point = tuple[float, float]
Leg = tuple[Point, Point]
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class MountedRun:
    """One pipe between two placed units and the furniture on it.

    Attributes
    ----------
    segments : tuple[Stream, ...]
        Physical segments in flow order.
    elements : tuple[Unit or StationAssembly, ...]
        Devices and station assemblies in flow order.
    places : tuple[tuple[Port, Port, float] or None, ...]
        Where each element sits on the author's line: the line's two end
        nozzles and the fraction between them, or ``None`` for one wired in
        with ``connect()``, which states no position.
    taps : tuple[tuple[Port, Port, float], ...]
        Where each balloon that senses the pipe taps it, placed the same way.
    """

    segments: tuple[Stream, ...]
    elements: tuple[Element, ...]
    places: tuple[tuple[Port, Port, float] | None, ...]
    taps: tuple[tuple[Port, Port, float], ...] = ()

    @property
    def source(self) -> Port:
        """Return the nozzle the pipe leaves."""
        return self.segments[0].source

    @property
    def dest(self) -> Port:
        """Return the nozzle the pipe reaches."""
        return self.segments[-1].dest


def _position_pinned(unit: Unit) -> bool:
    """Return whether a unit has a grid or pixel position pin.

    Parameters
    ----------
    unit : Unit
        Unit to inspect.

    Returns
    -------
    bool
        Whether ``col``, ``row``, ``x`` or ``y`` is pinned.
    """
    pin = unit.pin_
    return pin is not None and any(
        getattr(pin, axis) is not None for axis in ("col", "row", "x", "y")
    )


def _device(unit: Unit | None) -> bool:
    """Return whether a unit is an unpinned device carrying material through.

    Parameters
    ----------
    unit : Unit or None
        Unit to inspect.

    Returns
    -------
    bool
        Whether it is an unpinned valve, reducer or fitting whose only
        process ports, ``inlet`` and ``outlet``, both carry material and sit
        on opposite faces. An angle valve turns the pipe, so it is placed
        like equipment.
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
    upright = Pin()  # opposite faces stay opposite under any turn or mirror
    width, height = resolve_size(unit, upright)
    (ax, ay), (bx, by) = (port_offset(unit, name, upright) for name in ("inlet", "outlet"))
    return abs(abs(ax - bx) - width) < 1.0 or abs(abs(ay - by) - height) < 1.0


def _members(element: Element) -> list[Unit]:
    """Return the units an element draws.

    Parameters
    ----------
    element : Unit or StationAssembly
        Mounted device or station.

    Returns
    -------
    list[Unit]
        The device, or every station member.
    """
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return list(element.station.members)
    return [element]


def mounted_runs(fs: Flowsheet) -> list[MountedRun]:
    """Collect the pipes that carry furniture.

    A pipe runs from a unit that is not furniture, through furniture, to
    the next unit that is not. A pipe that starts and ends on one unit, or
    has a manual route, keeps its furniture in the grid.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to inspect.

    Returns
    -------
    list[MountedRun]
        One entry per furnished pipe, in stream order.
    """
    from pandid.inline import position

    from pandid.streams import Stream

    members = {u for a in fs._station_assemblies for u in a.station.members}
    # A balloon on a stream taps its whole line, at a fraction of it.
    tapped: dict[int, list[tuple[Port, Port, float]]] = {}
    for unit in fs.units:
        host, at = vars(unit).get("host"), getattr(unit, "at", None)
        if unit.kind != "instrument" or not isinstance(host, Stream) or isinstance(at, str):
            continue
        line = host._logical_root or host
        tap = (line.source, line._logical_to or line.dest, 0.5 if at is None else float(at))
        for segment in line._logical_segments or [line]:
            tapped.setdefault(id(segment), []).append(tap)
    stations = {id(a.station.inlet): a for a in fs._station_assemblies
                if not any(_position_pinned(u) for u in a.station.members)}
    runs = []
    for first in process_streams(fs):
        start = first.source.owner
        if start in members or _device(start):
            continue
        segments: list[Stream] = [first]
        elements: list[Element] = []
        while True:
            dest = segments[-1].dest
            assembly = stations.get(id(dest))
            if assembly is not None:
                element, out = assembly, assembly.station.outlet
            elif dest.name == "inlet" and dest.owner not in members and _device(dest.owner):
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
    """Measure the main legs of stations sharing one host run.

    Parameters
    ----------
    assemblies : list[StationAssembly]
        Stations ordered along one logical run.

    Returns
    -------
    float
        Required horizontal room for the station members.
    """
    width = 16.0
    for assembly in assemblies:
        station = assembly.station
        branch = {station.bypass, station.upstream_drain, station.downstream_drain}
        main = [unit for unit in station.members if unit not in branch]
        width += sum(resolve_size(unit)[0] for unit in main)
        width += assembly.gap * (len(main) - 1) + 16.0
    return width


def _chain_width(run: MountedRun) -> float:
    """Return the level room a pipe's furniture takes, for the equipment solve.

    Parameters
    ----------
    run : MountedRun
        Pipe to measure.

    Returns
    -------
    float
        Station room as :func:`_station_width` gives
        it, plus each device's width with :data:`ALONG` around each, or more
        where the stated positions need a longer pipe (:func:`_room`).
    """
    from pandid.layout.layered import END_ROOM
    from pandid.stations import StationAssembly

    stations = [element for element in run.elements if isinstance(element, StationAssembly)]
    devices = [element for element in run.elements if not isinstance(element, StationAssembly)]
    width = _station_width(stations) if stations else 0.0
    if devices:
        width += sum(resolve_size(unit)[0] for unit in devices) + ALONG * (len(devices) + 1)
    return max(width, _room(run) - END_ROOM)


def _column_room(run: MountedRun) -> float:
    """Return the vertical pipe a run's devices need between two stacked units.

    Parameters
    ----------
    run : MountedRun
        Pipe to measure.

    Returns
    -------
    float
        Devices end to end, :data:`ALONG` apart, with the margin kept at the
        nozzle and at the corner; 0 for a pipe carrying a station, which is
        set only on a level leg.
    """
    from pandid.stations import StationAssembly

    if any(isinstance(element, StationAssembly) for element in run.elements):
        return 0.0
    lengths = [_level_length(element) for element in run.elements]
    return (sum(lengths) + ALONG * (len(lengths) - 1) + NOZZLE_END + END
            + 2 * (TAP + ALONG) * len(run.taps))


@contextmanager
def _pipe_view(fs: Flowsheet, units: list[Unit], pipes: list[Stream]) -> Iterator[None]:
    """Show the sheet as the given units joined by the given pipes.

    Ports, routes and recycle marks touched by the view are restored on exit.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to view.
    units : list[Unit]
        Units shown.
    pipes : list[Stream]
        Streams shown, temporary pipes included.

    Yields
    ------
    None
        The sheet shows the view until the block exits.
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
        Sheet whose retained units have frames.
    runs : list[MountedRun]
        Pipes to route.
    retained : list[Unit]
        Units placed by the equipment solve.

    Returns
    -------
    tuple[list[list[Point]], list[list[Point]]]
        Drawn polyline of each pipe, empty where routing failed, and of
        every other process stream between retained units.
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


def _legs(points: list[Point]) -> list[Leg]:
    """Merge a polyline into straight legs.

    Parameters
    ----------
    points : list[Point]
        Orthogonal polyline.

    Returns
    -------
    list[Leg]
        Start and end of each maximal straight leg, in order.
    """
    legs: list[Leg] = []
    for a, b in zip(points, points[1:]):
        if a == b:
            continue
        if legs:
            p, q = legs[-1]
            level = abs(p[1] - q[1]) < 1e-6
            if level == (abs(a[1] - b[1]) < 1e-6) and (
                (q[0] - p[0]) * (b[0] - a[0]) > 0 or (q[1] - p[1]) * (b[1] - a[1]) > 0
            ):
                legs[-1] = (p, b)
                continue
        legs.append((a, b))
    return legs


def _size(leg: Leg) -> float:
    """Return a leg's length.

    Parameters
    ----------
    leg : Leg
        Straight leg.

    Returns
    -------
    float
        Length in pixels.
    """
    return abs(leg[1][0] - leg[0][0]) + abs(leg[1][1] - leg[0][1])


def _level(leg: Leg) -> bool:
    """Return whether a leg is horizontal.

    Parameters
    ----------
    leg : Leg
        Straight leg.

    Returns
    -------
    bool
        Whether both ends share a ``y``.
    """
    return abs(leg[0][1] - leg[1][1]) < 1e-6


def _candidate(unit: Unit, point: tuple[float, float], orientation: int,
               mirrored: bool) -> Frame:
    """Center a device at a point in a given turn and mirror.

    Parameters
    ----------
    unit : Unit
        Inline device to position.
    point : tuple[float, float]
        Preferred center of the device.
    orientation : int
        Clockwise quarter-turn angle.
    mirrored : bool
        Whether the symbol is mirrored left to right before it is turned.

    Returns
    -------
    Frame
        Candidate frame with the existing top-to-bottom mirror.
    """
    original = unit.frame
    assert original is not None
    probe = replace(original, orientation=orientation, mirrored=mirrored)
    width, height = resolve_size(unit, probe)
    return replace(
        probe, x=point[0] - width / 2, y=point[1] - height / 2,
        w=width, h=height, label_pos=None, port_faces={},
    )


def _on_corridor(
    unit: Unit, candidate: Frame, direction: tuple[int, int], ordinate: float,
) -> bool:
    """Require both nozzles to follow the straight host corridor.

    Parameters
    ----------
    unit : Unit
        Device being placed.
    candidate : Frame
        Proposed geometry.
    direction : tuple[int, int]
        Unit step of the material flow on the drawing.
    ordinate : float
        Fixed coordinate perpendicular to that flow.

    Returns
    -------
    bool
        Whether both ports align and face in material order.
    """
    inlet = port_point(unit, candidate, "inlet")
    outlet = port_point(unit, candidate, "outlet")
    axis = 0 if direction[0] else 1
    other = 1 - axis
    forward = direction[axis]
    return (abs(inlet[other] - ordinate) < 1.0
            and abs(outlet[other] - ordinate) < 1.0
            and (outlet[axis] - inlet[axis]) * forward > 0)


def _device_frame(unit: Unit, point: Point, leg: Leg) -> Frame:
    """Return a device frame centred on a leg point, piped in flow order.

    A device whose author stated a quarter turn keeps it, mirrored along the
    pipe if the flow runs the other way. Otherwise the first quarter turn
    and mirror that put both nozzles on the leg, inlet upstream, are used,
    so a device on an upright leg is turned to run along it. A pose that
    does is set with its nozzles on the leg, since they need not be at the
    box centre; one that cannot is centred on the point.

    Parameters
    ----------
    unit : Unit
        Two-port device with a frame.
    point : Point
        Point on the leg.
    leg : Leg
        Leg the device sits on.

    Returns
    -------
    Frame
        Candidate frame.
    """
    (ax, ay), (bx, by) = leg
    level = _level(leg)
    forward = 1 if (bx - ax if level else by - ay) > 0 else -1
    direction = (forward, 0) if level else (0, forward)
    ordinate = ay if level else ax
    assert unit.frame is not None
    # A pin with no turn (a mirror, or what is left of a position) states no turn.
    turned = unit.pin_ is not None and bool(unit.pin_.orientation % 360)
    if turned:
        # A stated turn is kept, mirrored along the pipe when the flow runs the other way.
        turn, flip = int(unit.frame.orientation), bool(unit.frame.mirrored)
        poses = [(turn, flip), (turn, not flip)]
    else:
        # A mirror before a half turn keeps an actuator on top of a pipe running west.
        first = 0 if level else 90
        poses = [(turn % 360, flip) for turn in (first, first + 180, first + 90, first + 270)
                 for flip in (False, True)]
    fits = []
    for turn, flip in poses:
        candidate = _candidate(unit, point, turn, flip)
        inlet = port_point(unit, candidate, "inlet")
        shift = ordinate - inlet[1 if level else 0]
        candidate = replace(candidate, x=candidate.x + (0.0 if level else shift),
                            y=candidate.y + (shift if level else 0.0))
        if _on_corridor(unit, candidate, direction, ordinate):
            fits.append(candidate)
    if not fits:
        return _candidate(unit, point, *poses[0])
    if turned or level or "actuator" not in unit.ports:
        return fits[0]
    # On an upright pipe the actuator goes to the left of the flow, where its
    # balloons hang by default, so its signals need not cross the pipe.
    left = -forward
    return min(fits, key=lambda c: (port_point(unit, c, "actuator")[0] - ordinate) * left > 0)


def _main_width(assembly: StationAssembly) -> float:
    """Return the length of a station's run, end nozzle to end nozzle.

    Parameters
    ----------
    assembly : StationAssembly
        Station to measure.

    Returns
    -------
    float
        Widths of the members on the run plus the gaps between them.
    """
    station = assembly.station
    branch = {station.bypass, station.upstream_drain, station.downstream_drain}
    main = [unit for unit in station.members if unit not in branch]
    return sum(resolve_size(unit)[0] for unit in main) + assembly.gap * (len(main) - 1)


def _length(element: Element, leg: Leg) -> float:
    """Return the room an element takes along a leg.

    Parameters
    ----------
    element : Unit or StationAssembly
        Device or station.
    leg : Leg
        Leg it would sit on.

    Returns
    -------
    float
        Length along the leg; infinite for a station on a vertical leg.
    """
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return _main_width(element) if _level(leg) else float("inf")
    frame = _device_frame(element, (0.0, 0.0), leg)
    level = _level(leg)
    (ax, ay), (bx, by) = (port_point(element, frame, name) for name in ("inlet", "outlet"))
    if abs((ay - by) if level else (ax - bx)) > 1.0:
        return float("inf")  # a stated turn that runs across this leg
    return frame.w if level else frame.h


def _level_length(element: Element) -> float:
    """Return the room an element takes along its pipe, before it is set.

    Parameters
    ----------
    element : Unit or StationAssembly
        Device or station.

    Returns
    -------
    float
        Station run length, or the device's extent from inlet to outlet
        side, whichever way its symbol is drawn.
    """
    from pandid.portgeom import port_offset
    from pandid.stations import StationAssembly

    if isinstance(element, StationAssembly):
        return _main_width(element)
    width, height = resolve_size(element)
    (ax, ay), (bx, by) = (port_offset(element, name, slot(element)) for name in ("inlet", "outlet"))
    return height if abs(by - ay) > abs(bx - ax) else width


def _frames_at(element: Element, centre: float, leg: Leg) -> dict[Unit, Frame]:
    """Return the frames that set an element centred a distance along a leg.

    Parameters
    ----------
    element : Unit or StationAssembly
        Device or station.
    centre : float
        Distance of the element's centre from the leg start.
    leg : Leg
        Leg it sits on.

    Returns
    -------
    dict[Unit, Frame]
        Frame for each unit the element draws.
    """
    from pandid.layout.station import _station_frames
    from pandid.stations import StationAssembly

    (ax, ay), (bx, by) = leg
    total = _size(leg)
    t = centre / total if total else 0.5
    point = (ax + t * (bx - ax), ay + t * (by - ay))
    if isinstance(element, StationAssembly):
        width = _length(element, leg)
        return _station_frames(element, point[0] - width / 2, point[1], bx < ax)
    return {element: _device_frame(element, point, leg)}


def _clear(frames: dict[Unit, Frame], obstacles: list[Unit], level: bool,
           zones: list[Box], pipes: list[list[Point]], ends: tuple[Unit, ...] = ()) -> bool:
    """Return whether proposed frames keep clear of other units.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Proposed frames.
    obstacles : list[Unit]
        Units already drawn.
    level : bool
        Whether the leg is horizontal, which sets the along-pipe axis.
    zones : list[Box]
        Ground other pipes' stations cover, bypass and drain legs included.
    pipes : list[list[Point]]
        Routed pipes, whose lines an actuator's signal must not have to cross.
    ends : tuple[Unit, ...], optional
        The pipe's own end units, which an actuator's signal must clear too.

    Returns
    -------
    bool
        Whether every frame keeps :data:`ALONG` along the pipe and
        :data:`GAP` across it from every obstacle and zone, and each
        connected signal port has a clear exit (:func:`_signal_exits`).
    """
    dx, dy = (ALONG, GAP) if level else (GAP, ALONG)
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
        if any(right > o[0] and o[2] > left and bottom > o[1] and o[3] > top for o in boxes):
            return False
        if any(max(a[0], b[0]) >= left and right >= min(a[0], b[0])
               and max(a[1], b[1]) >= top and bottom >= min(a[1], b[1]) for a, b in lines):
            return False
    return True


def _signal_exits(frames: dict[Unit, Frame]) -> list[Box]:
    """Return the router stand-off beyond each connected signal port.

    A control valve's actuator takes its signal from beyond its face, so
    that stretch must stay free of other units and pipes.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Proposed frames.

    Returns
    -------
    list[Box]
        One thin box per connected signal port, :data:`END` long.
    """
    from pandid.portgeom import port_anchor

    reach = {"N": (0.0, -END), "S": (0.0, END), "E": (END, 0.0), "W": (-END, 0.0)}
    out = []
    for unit, frame in frames.items():
        for port in unit.ports.values():
            if port.role != "signal" or port.stream is None:
                continue
            x, y, face = port_anchor(unit, frame, port.name)
            ux, uy = reach.get(face, (0.0, 0.0))
            out.append((min(x, x + ux), min(y, y + uy), max(x, x + ux), max(y, y + uy)))
    return out


def _commit(frames: dict[Unit, Frame], obstacles: list[Unit]) -> None:
    """Install frames and make the units obstacles for later elements.

    Parameters
    ----------
    frames : dict[Unit, Frame]
        Frames to install.
    obstacles : list[Unit]
        Obstacle list, extended in place.

    Returns
    -------
    None
        Frames and solver slots are updated.
    """
    for unit, frame in frames.items():
        unit.frame = frame
        placed = slot(unit)
        placed.x, placed.y, placed.w, placed.h = frame.x, frame.y, frame.w, frame.h
        placed.orientation = frame.orientation
        placed.mirrored, placed.mirror_y = frame.mirrored, frame.mirror_y
        obstacles.append(unit)


def _margins(index: int, count: int) -> tuple[float, float]:
    """Return the length kept clear at each end of a leg.

    Parameters
    ----------
    index : int
        Leg position along the pipe.
    count : int
        Number of legs.

    Returns
    -------
    tuple[float, float]
        :data:`NOZZLE_END` where the leg ends at the pipe's own nozzle,
        :data:`END` where it turns a corner.
    """
    return (NOZZLE_END if index == 0 else END,
            NOZZLE_END if index == count - 1 else END)


def _along(legs: list[Leg], point: Point) -> float:
    """Return how far along a pipe a point lies, measured past either end.

    Parameters
    ----------
    legs : list[Leg]
        Legs of the pipe.
    point : Point
        Point on or near it.

    Returns
    -------
    float
        Distance from the pipe's start to the point's nearest projection;
        negative before the start, beyond the length after the end.
    """
    best: tuple[float, float] | None = None
    travelled = 0.0
    for index, leg in enumerate(legs):
        (ax, ay), (bx, by) = leg
        size = _size(leg)
        level = _level(leg)
        ahead = (point[0] - ax) * (1 if bx >= ax else -1) if level else             (point[1] - ay) * (1 if by >= ay else -1)
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
    """Return the point a distance along a pipe, clamped to its ends.

    Parameters
    ----------
    legs : list[Leg]
        Legs of the pipe.
    distance : float
        Distance from the pipe's start.

    Returns
    -------
    tuple[Point, bool]
        Point on the pipe, and whether its leg is level.
    """
    for leg in legs:
        (ax, ay), (bx, by) = leg
        size = _size(leg)
        if distance <= size:
            t = max(distance, 0.0) / size if size else 0.0
            return (ax + t * (bx - ax), ay + t * (by - ay)), _level(leg)
        distance -= size
    return legs[-1][1], _level(legs[-1])


def _wanted(run: MountedRun, total: float, along: Callable[[Port], float] | None = None,
            extra: tuple[tuple[Port, Port, float], ...] = ()) -> list[float]:
    """Return where along the pipe each element's centre is wanted.

    An element with a place is put at its fraction of the author's line,
    measured between that line's two end nozzles. An element wired in with
    ``connect()``, or whose line ends off the pipe where ``along`` cannot
    say how far, is spread evenly along the pipe.

    Parameters
    ----------
    run : MountedRun
        Pipe whose elements are placed.
    total : float
        Length of the pipe.
    along : callable or None, optional
        Distance along the pipe of a nozzle that is not on it.
    extra : tuple[tuple[Port, Port, float], ...], optional
        Further places to locate, such as balloon taps.

    Returns
    -------
    list[float]
        Wanted distance from the pipe's start for each element, then for
        each extra place.
    """
    count = len(run.elements)
    even = [(k + 1) / (count + 1) * total for k in range(count)]

    def anchor(port: Port, side: float) -> float | None:
        """Return how far along the pipe a line's end nozzle is.

        Parameters
        ----------
        port : Port
            End nozzle of an author's line.
        side : float
            +1 for the outlet a line leaves, -1 for the inlet it reaches.

        Returns
        -------
        float or None
            Distance along the pipe, or ``None`` where it is not known.
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
    """Return the shortest straight pipe that holds every element where wanted.

    Wanted distances grow linearly with the pipe's length, so each spacing
    rule gives a least length; the longest of them is returned.

    Parameters
    ----------
    run : MountedRun
        Pipe to measure.

    Returns
    -------
    float
        Pipe length, nozzle to nozzle.
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


def _assign(run: MountedRun, legs: list[Leg], wanted: list[float]) -> list[list[int]]:
    """Return ways to put the elements on legs, best first, keeping flow order.

    The whole chain goes on one leg when one holds it: the legs nearest the
    elements' positions come first, level legs before upright ones. Last,
    elements are dealt onto legs in order, each on the first leg with room
    left.

    Parameters
    ----------
    run : MountedRun
        Pipe whose elements are placed.
    legs : list[Leg]
        Legs of its routed pipe.
    wanted : list[float]
        Wanted distance along the pipe of each element, from :func:`_wanted`.

    Returns
    -------
    list[list[int]]
        For each way, the leg index of each element.
    """
    room = [_size(leg) - sum(_margins(index, len(legs))) + ALONG
            for index, leg in enumerate(legs)]
    need = [[_length(element, leg) + ALONG for leg in legs] for element in run.elements]
    starts, travelled = [], 0.0
    for leg in legs:
        starts.append(travelled)
        travelled += _size(leg)
    middle = sum(wanted) / len(wanted)

    def distance(index: int) -> float:
        """Return how far a leg's middle is from the chain's wanted spot.

        Parameters
        ----------
        index : int
            Leg index.

        Returns
        -------
        float
            Distance along the pipe, in pixels.
        """
        return abs(starts[index] + _size(legs[index]) / 2 - middle)

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
            choice = max(usable or [max(range(len(legs)), key=lambda index: _size(legs[index]))],
                         key=lambda index: room[index] - used[index])
        if row[choice] != float("inf"):
            used[choice] += row[choice]
        assigned.append(choice)
        cursor = max(cursor, choice)
    return [*plans, assigned]


def _centres(wanted: list[float], lengths: list[float], size: float,
             head: float, tail: float) -> list[float]:
    """Return centres near the wanted ones, in order, apart and inside the leg.

    Parameters
    ----------
    wanted : list[float]
        Wanted centre distances from the leg start, in flow order.
    lengths : list[float]
        Length of each element along the leg.
    size : float
        Leg length.
    head, tail : float
        Length kept clear at the leg's start and end.

    Returns
    -------
    list[float]
        Centre distances; spaced evenly when the elements do not fit.
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


def _set_run(run: MountedRun, points: list[Point], obstacles: list[Unit],
             zones: list[Box], pipes: list[list[Point]]) -> bool:
    """Set a pipe's elements on its routed polyline.

    Parameters
    ----------
    run : MountedRun
        Pipe to set.
    points : list[Point]
        Routed polyline of its contracted pipe.
    obstacles : list[Unit]
        Units already drawn; extended with the elements set.
    zones : list[Box]
        Ground covered by stations already set; extended with this pipe's.
    pipes : list[list[Point]]
        Every routed pipe, this one included.

    Returns
    -------
    bool
        Whether every element found clear room.
    """
    source, dest = run.source.owner, run.dest.owner
    assert source is not None and dest is not None
    assert source.frame is not None and dest.frame is not None
    legs = _legs(points)
    if not legs:
        a = port_point(source, source.frame, run.source.name)
        b = port_point(dest, dest.frame, run.dest.name)
        legs = [(a, (b[0], a[1])) if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else (a, (a[0], b[1]))]
    count = len(run.elements)
    want = _wanted(run, sum(_size(leg) for leg in legs),
                   lambda port: _along(legs, port_point(port.owner, port.owner.frame, port.name)),
                   run.taps)
    # On an upright pipe a balloon hangs level with the devices, so they keep
    # its reach clear along the pipe from where it taps.
    tap_zones = []
    for distance in want[count:]:
        (x, y), level = _point_at(legs, distance)
        if not level:
            tap_zones.append((x - 1.0, y - TAP, x + 1.0, y + TAP))
    want = want[:count]
    starts, travelled = [], 0.0
    for leg in legs:
        starts.append(travelled)
        travelled += _size(leg)
    # The pipe's own end units keep only the leg margin, not the ALONG clearance.
    others = [unit for unit in obstacles if unit is not source and unit is not dest]

    def attempt(assigned: list[int], strict: bool) -> list[dict[Unit, Frame]] | None:
        """Return frames for each element on its leg, or ``None`` if one has no room.

        Parameters
        ----------
        assigned : list[int]
            Leg index of each element.
        strict : bool
            Give up when an element finds no clear spot, rather than set it
            as near its wanted spot as the leg allows.

        Returns
        -------
        list[dict[Unit, Frame]] or None
            Frames for each element, in flow order.
        """
        placed: list[dict[Unit, Frame]] = []
        mine = [*zones, *tap_zones]
        for index in sorted(set(assigned)):
            leg, size, level = legs[index], _size(legs[index]), _level(legs[index])
            head, tail = _margins(index, len(legs))
            group = [i for i, a in enumerate(assigned) if a == index]
            lengths = [min(_length(run.elements[i], leg), size) for i in group]
            if strict and sum(lengths) + ALONG * (len(group) - 1) + head + tail > size:
                return None
            centres = _centres([want[i] - starts[index] for i in group], lengths, size, head, tail)
            floor = 0.0
            for i, length, centre in zip(group, lengths, centres):
                low = max(length / 2 + head, floor + length / 2)
                high = size - length / 2 - tail
                chosen = None
                reach = int(size / NUDGE_STEP) + 1  # anywhere on the leg, nearest first
                for step in sorted(range(-reach, reach + 1), key=abs):
                    at = centre + step * NUDGE_STEP
                    if not low - 1e-6 <= at <= high + 1e-6:
                        continue
                    frames = _frames_at(run.elements[i], at, leg)
                    if _clear(frames, others, level, mine, pipes, (source, dest)):
                        chosen = (at, frames)
                        break
                if chosen is None:
                    if strict:
                        return None
                    at = min(max(centre, low), max(low, high)) if high >= low else size / 2
                    chosen = (at, _frames_at(run.elements[i], at, leg))
                drawn = [unit_box(unit, frame) for unit, frame in chosen[1].items()]
                mine.append((min(b[0] for b in drawn), min(b[1] for b in drawn),
                             max(b[2] for b in drawn), max(b[3] for b in drawn)))
                placed.append(chosen[1])
                floor = chosen[0] + length / 2 + ALONG
        return placed

    plans = _assign(run, legs, want)
    placed = next((p for p in (attempt(plan, True) for plan in plans) if p is not None), None)
    roomy = placed is not None
    for frames in placed if placed is not None else attempt(plans[0], False) or []:
        _commit(frames, obstacles)
        if len(frames) > 1:
            drawn = [unit_box(unit, frame) for unit, frame in frames.items()]
            zones.append((min(b[0] for b in drawn), min(b[1] for b in drawn),
                          max(b[2] for b in drawn), max(b[3] for b in drawn)))
    return roomy


def place_mounted(fs: Flowsheet, runs: list[MountedRun]) -> None:
    """Lay out a sheet in two passes: equipment, then furniture on its routed pipes.

    Pass 1 places equipment and flags with each furnished pipe stating the
    room its furniture needs (:class:`pandid.layout.layered.Link`), so pass
    2 sets the furniture without moving equipment.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with fresh solver slots and recycle marks.
    runs : list[MountedRun]
        Its furnished pipes, from :func:`mounted_runs`; may be empty.

    Returns
    -------
    None
        Every process unit has a frame.
    """
    from pandid.layout.layered import Link, place_equipment
    from pandid.layout.station import place_stations

    members = {unit for run in runs for element in run.elements for unit in _members(element)}
    retained = [unit for unit in process_units(fs) if unit not in members]
    shown = set(retained)
    loose = [a for a in fs._station_assemblies if not members.intersection(a.station.members)]
    inside = {id(segment) for run in runs for segment in run.segments}
    place_equipment(fs, retained, [
        *(Link(s.source, s.dest, s.is_recycle) for s in process_streams(fs)
          if id(s) not in inside and s.source.owner in shown and s.dest.owner in shown
          and s.source.owner is not s.dest.owner),
        *(Link(run.source, run.dest, any(s.is_recycle for s in run.segments),
               _chain_width(run), _column_room(run))
          for run in runs)])
    for unit in members:
        placed = slot(unit)
        unit.frame = Frame(x=0.0, y=0.0, w=placed.w, h=placed.h,
                           orientation=placed.orientation, mirrored=placed.mirrored,
                           mirror_y=placed.mirror_y)
    place_stations(fs, loose)
    if not runs:
        return
    routes, lines = _routed_pipes(fs, runs, retained)
    obstacles = list(retained)
    zones: list[Box] = []
    # The longest chains, stations first, are the hardest to fit.
    for i in sorted(range(len(runs)), key=lambda i: (-_chain_width(runs[i]), i)):
        _set_run(runs[i], routes[i], obstacles, zones, [*lines, *routes])
