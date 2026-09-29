"""Major process nodes and ordered inline devices on material runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.layout.stages import process_streams, process_units

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit


@dataclass(frozen=True)
class BackboneRun:
    """One material run between retained process nodes.

    Attributes
    ----------
    source, dest : int
        Endpoint indices in ``process_units(fs)``.
    inline_units : tuple[int, ...]
        Contracted unit indices in flow order.
    streams : tuple[int, ...]
        Original indices in ``process_streams(fs)`` in flow order.
    inline_at : tuple[float | None, ...]
        Preferred run fractions for the corresponding inline units.
    """

    source: int
    dest: int
    inline_units: tuple[int, ...]
    streams: tuple[int, ...]
    inline_at: tuple[float | None, ...] = ()


@dataclass(frozen=True)
class Backbone:
    """A read-only equipment graph with its inline material runs.

    Attributes
    ----------
    unit_count, stream_count : int
        Sizes of the original process-unit and material-stream lists.
    nodes : tuple[int, ...]
        Process-unit indices retained as placement nodes.
    runs : tuple[BackboneRun, ...]
        Material runs in their first stream's declaration order.
    """

    unit_count: int
    stream_count: int
    nodes: tuple[int, ...]
    runs: tuple[BackboneRun, ...]


def _free_inline(
    unit: Unit,
    incoming: list[int],
    outgoing: list[int],
    streams: list[Stream],
) -> bool:
    """Whether a two-port device can be represented within a run.

    Parameters
    ----------
    unit : Unit
        Process unit to classify.
    incoming, outgoing : list[int]
        Indices of incident material streams in each direction.
    streams : list[Stream]
        Material streams in flowsheet order.

    Returns
    -------
    bool
        Whether the device lacks a position pin and is outside recycle cuts.
    """
    if unit.kind not in {"valve", "reducer", "fitting"}:
        return False
    if len(incoming) != 1 or len(outgoing) != 1:
        return False
    if {port.name for port in unit.ports.values() if port.role == "process"} != {"inlet", "outlet"}:
        return False
    if streams[incoming[0]].dest.name != "inlet":
        return False
    if streams[outgoing[0]].source.name != "outlet":
        return False
    if streams[incoming[0]].is_recycle or streams[outgoing[0]].is_recycle:
        return False
    pin = unit.pin_
    return pin is None or all(getattr(pin, axis) is None for axis in ("col", "row", "x", "y"))


def infer_backbone(fs: Flowsheet) -> Backbone:
    """Contract position-free two-port devices without changing the flowsheet.

    Call after cycle breaking when the sheet contains recycles. Tees,
    boundaries, authored position pins, and recycle endpoints remain nodes.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose material graph is inspected.

    Returns
    -------
    Backbone
        Deterministic node and run indices into the original graph.

    Raises
    ------
    ValueError
        If a material stream cannot be assigned to exactly one run.
    """
    units = process_units(fs)
    streams = process_streams(fs)
    index_of = {unit: index for index, unit in enumerate(units)}
    incoming: list[list[int]] = [[] for _ in units]
    outgoing: list[list[int]] = [[] for _ in units]
    sources: list[int] = []
    destinations: list[int] = []
    for index, stream in enumerate(streams):
        source_unit = stream.source.owner
        dest_unit = stream.dest.owner
        assert source_unit is not None and dest_unit is not None
        source_index = index_of[source_unit]
        dest_index = index_of[dest_unit]
        sources.append(source_index)
        destinations.append(dest_index)
        outgoing[source_index].append(index)
        incoming[dest_index].append(index)

    inline = {
        index
        for index, unit in enumerate(units)
        if _free_inline(unit, incoming[index], outgoing[index], streams)
    }
    nodes = tuple(index for index in range(len(units)) if index not in inline)
    covered: set[int] = set()
    runs: list[BackboneRun] = []
    for first, source_index in enumerate(sources):
        if source_index in inline:
            continue
        path = [first]
        seen = {first}
        members: list[int] = []
        dest_index = destinations[first]
        while dest_index in inline:
            members.append(dest_index)
            following = outgoing[dest_index][0]
            if following in seen:
                raise ValueError("material cycle requires cycle breaking before inference")
            path.append(following)
            seen.add(following)
            dest_index = destinations[following]
        if covered.intersection(path):
            raise ValueError("material stream appears in more than one backbone run")
        covered.update(path)
        runs.append(BackboneRun(
            source_index, dest_index, tuple(members), tuple(path),
            tuple(streams[index]._inline_at for index in path[:-1]),
        ))
    if len(covered) != len(streams):
        raise ValueError("material cycle requires cycle breaking before inference")
    return Backbone(len(units), len(streams), nodes, tuple(runs))
