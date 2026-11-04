"""Put devices and valve stations on a line, keeping its handle."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import TYPE_CHECKING, TypeVar

from pandid.streams import Stream
from pandid.units import Unit

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.stations import ValveStation

_UnitT = TypeVar("_UnitT", bound="Unit")
_INLINE_KINDS = frozenset({"valve", "reducer", "fitting"})


def split_point(fs: Flowsheet, line: Stream, at: float | None) -> tuple[list[Stream], int]:
    """Return a line's segments and the index a new item splits.

    An item without ``at`` goes last; one with ``at`` goes before the
    first item with a larger ``at``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that owns the line.
    line : Stream
        Line handle returned by ``connect()``.
    at : float or None
        Fraction of the line strictly between 0 and 1, or ``None``.

    Returns
    -------
    tuple[list[Stream], int]
        The physical segments in flow order, and the index of the
        segment whose destination the new item takes.

    Raises
    ------
    ValueError
        If ``line`` or ``at`` cannot be used.
    """
    if not isinstance(line, Stream):
        raise ValueError(f"on= takes a line returned by connect(), got {line!r}")
    fs._refuse_foreign("on", line)
    if line._logical_root is not None:
        raise ValueError("on= takes the line connect() returned, not one of its segments")
    if at is not None and (isinstance(at, bool) or not isinstance(at, (int, float))
                           or not isfinite(at) or not 0 < at < 1):
        raise ValueError(f"at= is a fraction of the line strictly between 0 and 1, got {at!r}")
    if line.kind != "material":
        raise ValueError(f"on= takes a material line; {line.name!r} is {line.kind}")
    if not line._logical_segments and line._inline_at is not None:
        raise ValueError("on= cannot replace an existing inline position")
    segments = line._logical_segments or [line]
    if any(s.draw_as_recycle or s.is_recycle for s in segments):
        flagged = any(s.draw_as_recycle for s in segments)
        source, dest = _ends(segments)
        raise ValueError(
            f"on= cannot split {line.name}: it "
            + ("is marked draw_as_recycle=True, and a split line would leave one "
               "part without that mark" if flagged else
               "is the recycle line the last render drew to close a cycle")
            + f". Pipe the device in with two connect() calls in place of the one "
            f"that drew {line.name}, keeping its other arguments: "
            f"fs.connect({source}, <device>.inlet"
            + (", draw_as_recycle=True" if flagged else "")
            + f") and fs.connect(<device>.outlet, {dest})"
            + _carried(fs, line, segments)
        )
    if any(s.route is not None and s.route.manual for s in segments):
        raise ValueError("on= cannot split a manual route")
    if any(s.ends is not None for s in segments):
        raise ValueError("on= cannot split a line with explicit end-joint styles")
    stated = [segment._inline_at for segment in segments[:-1]]
    if at is None:
        return segments, len(stated)
    if at in stated:
        raise ValueError("inline positions must be distinct")
    return segments, next((i for i, value in enumerate(stated)
                           if value is not None and value > at), len(stated))


def _ends(segments: list[Stream]) -> tuple[str, str]:
    """Return a line's source and destination as ``connect()`` took them.

    Parameters
    ----------
    segments : list[Stream]
        The line's physical segments in flow order.

    Returns
    -------
    tuple[str, str]
        ``unit.port`` where the line starts and ends, naming a pool
        member by its pool.
    """
    source, dest = (f"{p.owner.name}.{p.owner._pool_of(p.name) or p.name}"
                    for p in (segments[0].source, segments[-1].dest))
    return source, dest


def _carried(fs: Flowsheet, line: Stream, segments: list[Stream]) -> str:
    """Return a sentence listing what a line carries, to put back.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that owns the line.
    line : Stream
        Line handle.
    segments : list[Stream]
        The line's physical segments in flow order.

    Returns
    -------
    str
        The devices and valve stations on the line in flow order, then
        the balloons on it or its parts; ``""`` when it carries none.
    """
    from pandid.units import Instrument

    devices = [next((f"valve station {a.station.control.name}" for a in fs._station_assemblies
                     if a.station.inlet is s.dest), s.dest.owner.name)
               for s in segments[:-1]]
    balloons = [u.name for u in fs.units
                if isinstance(u, Instrument) and any(u.host is s for s in segments)]
    items = ([", ".join(devices) + (" (in flow order)" if len(devices) > 1 else "")]
             if devices else []) + balloons
    if not items:
        return ""
    listed = " and ".join(filter(None, (", ".join(items[:-1]), items[-1])))
    return f". Then put back what {line.name} carries, each where it sits now: {listed}"


def position(segment: Stream) -> float | None:
    """Return the line fraction of the item a segment enters.

    An item without ``at`` is spread evenly between its neighbours.

    Parameters
    ----------
    segment : Stream
        Physical segment entering a device or station.

    Returns
    -------
    float or None
        The segment's stated ``at``; else its spread fraction on a
        split line; else ``None``.
    """
    if segment._inline_at is not None:
        return segment._inline_at
    line = segment._logical_root or segment
    entering = line._logical_segments[:-1]
    k = next((i for i, s in enumerate(entering) if s is segment), None)
    if k is None:
        return None
    known = {i: s._inline_at for i, s in enumerate(entering) if s._inline_at is not None}
    low = max((i for i in known if i < k), default=-1)
    high = min((i for i in known if i > k), default=len(entering))
    start, end = known.get(low, 0.0), known.get(high, 1.0)
    return start + (end - start) * (k - low) / (high - low)


def _splice(fs: Flowsheet, line: Stream, segments: list[Stream], index: int,
            inlet: Port, outlet: Port, at: float | None) -> None:
    """Route a segment into ``inlet`` and a new one from ``outlet``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that owns the line.
    line : Stream
        Line handle.
    segments : list[Stream]
        The line's physical segments in flow order.
    index : int
        Segment to split, from :func:`split_point`.
    inlet, outlet : Port
        Where the line enters and leaves the new item.
    at : float or None
        The item's stated fraction.
    """
    selected = segments[index]
    old_dest = selected.dest
    successor = Stream(name="", source=outlet, dest=old_dest, kind="material",
                       color=selected.color, dasharray=selected.dasharray)
    successor._inline_at = selected._inline_at
    successor._logical_root = line
    selected.dest = inlet
    inlet.stream = selected
    outlet.stream = successor
    old_dest.stream = successor
    selected._inline_at = None if at is None else float(at)
    if line._logical_to is None:
        line._logical_to = old_dest
    line._logical_segments = [*segments[:index + 1], successor, *segments[index + 1:]]
    place = next(i for i, stream in enumerate(fs.streams) if stream is selected)
    fs.streams.insert(place + 1, successor)


def insert_device(fs: Flowsheet, line: Stream, device: _UnitT, *,
                  at: float | None) -> _UnitT:
    """Add an unconnected two-port device to a sheet, in a line.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that owns the line.
    line : Stream
        Line handle returned by ``connect()``.
    device : Unit
        Unconnected valve, reducer or fitting.
    at : float or None
        Fraction of the line, or ``None`` to go last.

    Returns
    -------
    Unit
        The added device.

    Raises
    ------
    ValueError
        If the line, device or fraction cannot be used.
    """
    segments, index = split_point(fs, line, at)
    if isinstance(device, Unit) and device.kind == "tee":
        source, dest = _ends(segments)
        tee = device.name
        branch = (f"fs.connect({tee}.branch, ...)"
                  if device.ports["branch"].direction == "outlet"
                  else f"fs.connect(..., {tee}.branch)")
        raise ValueError(
            f"on= cannot put a tee in a line: its branch needs a line of its own. "
            f"Draw {line.name} through {tee} with connect() calls in place of the one "
            f"that drew {line.name}, keeping its other arguments: "
            f"fs.connect({source}, {tee}.inlet), fs.connect({tee}.outlet, {dest}) "
            f"and {branch}" + _carried(fs, line, segments)
        )
    if not isinstance(device, Unit) or device.kind not in _INLINE_KINDS:
        raise ValueError("on= puts a valve, reducer or fitting in a line")
    ports = device.ports
    if ({p.name for p in ports.values() if p.role == "process"} != {"inlet", "outlet"}
            or any(p.stream is not None for p in ports.values())):
        raise ValueError("on= takes an unconnected device with one inlet and one outlet")
    fs._refuse_unaddable(device)
    old_dest = segments[index].dest
    with fs._unchanged_if_it_raises((fs, *fs.streams, old_dest, device, *ports.values())):
        fs.add(device)
        _splice(fs, line, segments, index, ports["inlet"], ports["outlet"], at)
        fs.renumber_streams()
        fs._invalidate_layout()
    return device


def insert_station(fs: Flowsheet, line: Stream, station: ValveStation, *,
                   at: float | None) -> None:
    """Put a newly built valve station in a line.

    Parameters
    ----------
    fs : Flowsheet
        Sheet owning the line and the station members.
    line : Stream
        Line handle returned by ``connect()``.
    station : ValveStation
        Station whose inlet and outlet are free.
    at : float or None
        Fraction of the line, or ``None`` to go last.

    Raises
    ------
    ValueError
        If the line or fraction cannot be used.
    """
    segments, index = split_point(fs, line, at)
    record = next(i for i, item in enumerate(fs._station_assemblies) if item.station is station)
    old_dest = segments[index].dest
    with fs._unchanged_if_it_raises((fs, *fs.streams, old_dest, station.inlet, station.outlet)):
        _splice(fs, line, segments, index, station.inlet, station.outlet, at)
        fs._station_assemblies[record] = replace(
            fs._station_assemblies[record], run=line, at=None if at is None else float(at),
        )
        fs.renumber_streams()
        fs._invalidate_layout()


def restore_logical_run(fs: Flowsheet, root: Stream, endpoint: Port) -> None:
    """Rebuild a split line from its serialized physical segments.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing the segments.
    root : Stream
        First segment and the line's handle.
    endpoint : Port
        The line's final destination.

    Raises
    ------
    ValueError
        If the segments do not form one split line to ``endpoint``.
    """
    if root._logical_to is not None or root._logical_root is not None:
        raise ValueError("logical run roots cannot overlap")
    segments = [root]
    visited = {id(root)}
    while segments[-1].dest is not endpoint:
        incoming = segments[-1]
        unit = incoming.dest.owner
        station = next((assembly.station for assembly in fs._station_assemblies
                        if assembly.run is root and assembly.station.inlet is incoming.dest), None)
        if station is None and unit.kind not in _INLINE_KINDS:
            raise ValueError("logical run does not reach its destination through inline devices")
        outlet = station.outlet if station is not None else unit.ports.get("outlet")
        following = outlet.stream if outlet is not None else None
        if (following is None or following.source is not outlet
                or following.kind != "material" or id(following) in visited
                or following._logical_root is not None):
            raise ValueError("logical run has a missing or repeated physical segment")
        visited.add(id(following))
        segments.append(following)
    if len(segments) < 2:
        raise ValueError("logical run must contain an inline device")
    stated = [s._inline_at for s in segments[:-1] if s._inline_at is not None]
    if stated != sorted(stated) or len(set(stated)) != len(stated):
        raise ValueError("logical run positions must be distinct and in flow order")
    root._logical_to = endpoint
    root._logical_segments = segments
    for segment in segments[1:]:
        segment._logical_root = root
