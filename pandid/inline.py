"""Insert simple inline devices while retaining a logical stream handle."""

from __future__ import annotations

from bisect import bisect_left
from math import isfinite
from typing import TYPE_CHECKING, TypeVar

from pandid.streams import Stream
from pandid.units import Unit

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.ports import Port
    from pandid.units import Unit

_UnitT = TypeVar("_UnitT", bound="Unit")
_INLINE_KINDS = frozenset({"valve", "reducer", "fitting"})


def insert_device(fs: Flowsheet, run: Stream, device: _UnitT, *, at: float) -> _UnitT:
    """Split a material run around one fresh inline device.

    Parameters
    ----------
    fs : Flowsheet
        Sheet that owns the run.
    run : Stream
        Original stream handle, including after earlier insertions.
    device : Unit
        Unconnected two-port inline unit to insert.
    at : float
        Strictly interior fraction of the complete run.

    Returns
    -------
    Unit
        The inserted device.

    Raises
    ------
    ValueError
        If any author-owned connection intent would be changed.
    """
    if not isinstance(run, Stream):
        raise ValueError("place_on requires a stream handle")
    fs._refuse_foreign("run", run)
    if run._logical_root is not None:
        raise ValueError("place_on requires the original run handle")
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not isfinite(at) or not 0 < at < 1:
        raise ValueError("at must be a finite number between 0 and 1")
    if run.kind != "material":
        raise ValueError("place_on requires a material run")
    if not run._logical_segments and run._inline_at is not None:
        raise ValueError("place_on cannot replace an existing inline position")
    segments = run._logical_segments or [run]
    if any(s.draw_as_recycle or s.is_recycle for s in segments):
        raise ValueError("place_on cannot split a recycle run")
    if any(s.route is not None and s.route.manual for s in segments):
        raise ValueError("place_on cannot split a manual route")
    if any(s.ends is not None for s in segments):
        raise ValueError("place_on cannot split explicit end-joint styles")
    if not isinstance(device, Unit) or device.kind not in _INLINE_KINDS:
        raise ValueError("place_on requires a valve, reducer, or fitting")
    ports = device.ports
    if ({p.name for p in ports.values() if p.role == "process"} != {"inlet", "outlet"}
            or any(p.stream is not None for p in ports.values())):
        raise ValueError("place_on requires an unconnected two-port device")
    fs._refuse_unaddable(device)

    fractions = [segment._inline_at for segment in segments[:-1]]
    if any(value is None for value in fractions):
        raise ValueError("place_on requires an intact logical run")
    ordered = [value for value in fractions if value is not None]
    if at in ordered or ordered != sorted(ordered):
        raise ValueError("inline positions must be distinct and in flow order")
    position = bisect_left(ordered, at)
    selected = segments[position]
    inlet, outlet = ports["inlet"], ports["outlet"]
    old_dest = selected.dest
    successor = Stream(
        name="", source=outlet, dest=old_dest, kind="material",
        color=selected.color, dasharray=selected.dasharray,
    )
    successor._inline_at = selected._inline_at
    successor._logical_root = run
    with fs._unchanged_if_it_raises((fs, *fs.streams, old_dest, device, *ports.values())):
        fs.add(device)
        selected.dest = inlet
        inlet.stream = selected
        outlet.stream = successor
        old_dest.stream = successor
        selected._inline_at = float(at)
        if run._logical_to is None:
            run._logical_to = old_dest
        run._logical_segments = [*segments[:position + 1], successor, *segments[position + 1:]]
        stream_index = next(i for i, stream in enumerate(fs.streams) if stream is selected)
        fs.streams.insert(stream_index + 1, successor)
        fs.renumber_streams()
        fs._invalidate_layout()
    return device


def restore_logical_run(fs: Flowsheet, root: Stream, endpoint: Port) -> None:
    """Rebuild a logical run from its serialized physical segments.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing all physical segments.
    root : Stream
        First physical segment and logical run handle.
    endpoint : Port
        Original destination of the run before insertion.

    Returns
    -------
    None
        The root and its downstream segments are linked.

    Raises
    ------
    ValueError
        If the physical chain cannot reach the stated endpoint.
    """
    if root._logical_to is not None or root._logical_root is not None:
        raise ValueError("logical run roots cannot overlap")
    segments = [root]
    visited = {id(root)}
    while segments[-1].dest is not endpoint:
        incoming = segments[-1]
        unit = incoming.dest.owner
        if unit is None or unit.kind not in _INLINE_KINDS or incoming._inline_at is None:
            raise ValueError("logical run does not reach its destination through inline devices")
        outlet = unit.ports.get("outlet")
        following = outlet.stream if outlet is not None else None
        if (following is None or following.source is not outlet
                or following.kind != "material" or id(following) in visited
                or following._logical_root is not None):
            raise ValueError("logical run has a missing or repeated physical segment")
        visited.add(id(following))
        segments.append(following)
    if len(segments) < 2:
        raise ValueError("logical run must contain an inline device")
    fractions = [segment._inline_at for segment in segments[:-1]]
    ordered = [value for value in fractions if value is not None]
    if len(ordered) != len(fractions) or ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise ValueError("logical run positions must be distinct and in flow order")
    root._logical_to = endpoint
    root._logical_segments = segments
    for segment in segments[1:]:
        segment._logical_root = root
