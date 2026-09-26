"""Immutable process structure inferred before geometric placement.

Indices refer to ``process_units(fs)`` and ``process_streams(fs)`` in their
original order. This module reads cycle marks and author intent; it never
updates slots, frames, pins, or streams.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import TYPE_CHECKING

from pandid.layout import claims as claims_mod
from pandid.layout.stages import process_streams, process_units

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Pin


@dataclass(frozen=True)
class Edge:
    """One material connection in process-list coordinates.

    Attributes
    ----------
    stream, source, dest : int
        Process-stream and process-unit indices.
    source_role, dest_role : str
        Port roles at the two ends of the connection.
    recycle : bool
        Cycle-break decision already made for this stream.
    """

    stream: int
    source: int
    dest: int
    source_role: str
    dest_role: str
    recycle: bool


@dataclass(frozen=True)
class ProcessPath:
    """An ordered run of process units and connecting streams.

    Attributes
    ----------
    units : tuple[int, ...]
        Process-unit indices from upstream to downstream.
    streams : tuple[int, ...]
        Connecting stream indices, one fewer than units.
    """

    units: tuple[int, ...]
    streams: tuple[int, ...]


@dataclass(frozen=True)
class Branch:
    """Direct, non-nested arms between a common split and merge.

    Attributes
    ----------
    split, merge : int
        Process-unit indices at the two shared endpoints.
    arms : tuple[ProcessPath, ...]
        Arms in outgoing process-stream order.
    repeated : bool
        Whether nonempty arms have matching unit and port-role patterns.
    """

    split: int
    merge: int
    arms: tuple[ProcessPath, ...]
    repeated: bool


@dataclass(frozen=True)
class ArmRegion:
    """All forward paths from one split exit to a shared merge.

    Attributes
    ----------
    entry_stream : int
        The stream leaving the split on this arm.
    units, streams : tuple[int, ...]
        Process indices on any forward path through the arm, including
        the shared split and merge endpoints.
    """

    entry_stream: int
    units: tuple[int, ...]
    streams: tuple[int, ...]


@dataclass(frozen=True)
class BranchRegion:
    """A split and a shared merge, either partial or fully closing.

    Attributes
    ----------
    split, merge : int
        Shared endpoint process-unit indices.
    arms : tuple[ArmRegion, ...]
        One region per outgoing stream, in stream order. An arm may
        contain nested splits and merges; bypass paths are excluded.
    closed : bool
        Whether every path from each exit passes through this merge.
        A partial region is only a shared subregion, not a movable group.
    """

    split: int
    merge: int
    arms: tuple[ArmRegion, ...]
    closed: bool


@dataclass(frozen=True)
class Corridor:
    """Forward process region spanned by a recycle connection.

    Attributes
    ----------
    recycle_stream : int
        Index of the backward material stream.
    head, tail : int
        Destination and source of that backward stream, respectively.
    units, streams : tuple[int, ...]
        Every unit and forward stream on a path from head to tail.
        Both are empty when no such forward path exists.
    """

    recycle_stream: int
    head: int
    tail: int
    units: tuple[int, ...]
    streams: tuple[int, ...]


@dataclass(frozen=True)
class PlacementClaim:
    """One equipment placement preference without mutable unit references.

    Attributes
    ----------
    author, subject : int
        Process-unit indices of the asserting unit and its peer.
    eastward, southward : int
        Preferred grid displacement from author to subject.
    confidence : float
        Existing claim weight.
    """

    author: int
    subject: int
    eastward: int
    southward: int
    confidence: float


@dataclass(frozen=True)
class PinIntent:
    """Author placement and transform intent for one process unit.

    Attributes
    ----------
    unit : int
        Process-unit index.
    pin : Pin or None
        Frozen author value, including partial axes and transforms. A
        port-relative absolute value is kept as a nozzle coordinate.
    port_axes : tuple[tuple[str, str], ...]
        Pinned axis and nozzle name for port-relative absolute pins.
    """

    unit: int
    pin: Pin | None
    port_axes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Structure:
    """Read-only structural facts for later candidate generation.

    Attributes
    ----------
    unit_count : int
        Number of stage-one process units.
    edges : tuple[Edge, ...]
        All material edges, including cycle-breaking recycles.
    claims : tuple[PlacementClaim, ...]
        Existing equipment-relative placement preferences.
    pins : tuple[PinIntent, ...]
        Explicit author placement and transform choices.
    components : tuple[tuple[int, ...], ...]
        Weakly connected process groups in first-unit order.
    forward_order : tuple[int, ...]
        Stable topological order after recycle edges are removed.
    chains : tuple[ProcessPath, ...]
        Maximal forward paths through units with one input and output.
    principal_paths : tuple[ProcessPath, ...]
        Longest forward path of each component, with stable ties. This
        is a candidate process spine, not a guaranteed main product run.
    branches : tuple[Branch, ...]
        Simple split/merge regions with non-nested arms.
    branch_regions : tuple[BranchRegion, ...]
        Shared split/merge subregions, including partial regions with
        side takeoffs. Only ``closed`` regions describe whole arms.
    corridors : tuple[Corridor, ...]
        Forward regions crossed by marked recycle edges.
    service_candidates : tuple[int, ...]
        Material streams from a shared boundary supply or into a shared
        boundary sink. These are possible headers, not reserved lanes.
    """

    unit_count: int
    edges: tuple[Edge, ...]
    claims: tuple[PlacementClaim, ...]
    pins: tuple[PinIntent, ...]
    components: tuple[tuple[int, ...], ...]
    forward_order: tuple[int, ...]
    chains: tuple[ProcessPath, ...]
    principal_paths: tuple[ProcessPath, ...]
    branches: tuple[Branch, ...]
    branch_regions: tuple[BranchRegion, ...]
    corridors: tuple[Corridor, ...]
    service_candidates: tuple[int, ...]


def _components(count: int, edges: tuple[Edge, ...]) -> tuple[tuple[int, ...], ...]:
    """Find weak process components, including recycle connections.

    Parameters
    ----------
    count : int
        Number of process units.
    edges : tuple[Edge, ...]
        Material connections in stream order.

    Returns
    -------
    tuple[tuple[int, ...], ...]
        Components sorted by their first process-unit index.
    """
    neighbours: list[list[int]] = [[] for _ in range(count)]
    for edge in edges:
        neighbours[edge.source].append(edge.dest)
        neighbours[edge.dest].append(edge.source)
    seen: set[int] = set()
    groups = []
    for start in range(count):
        if start in seen:
            continue
        seen.add(start)
        queue = deque([start])
        group = []
        while queue:
            node = queue.popleft()
            group.append(node)
            for peer in neighbours[node]:
                if peer not in seen:
                    seen.add(peer)
                    queue.append(peer)
        groups.append(tuple(sorted(group)))
    return tuple(groups)


def _forward_graph(
    count: int, edges: tuple[Edge, ...]
) -> tuple[list[list[Edge]], list[list[Edge]], tuple[int, ...]]:
    """Build the stable forward DAG after the established recycle cuts.

    Parameters
    ----------
    count : int
        Number of process units.
    edges : tuple[Edge, ...]
        Material edges with cycle-break marks.

    Returns
    -------
    tuple[list[list[Edge]], list[list[Edge]], tuple[int, ...]]
        Outgoing and incoming edges and stable topological unit order.

    Raises
    ------
    ValueError
        If unmarked forward edges still contain a cycle.
    """
    outgoing: list[list[Edge]] = [[] for _ in range(count)]
    incoming: list[list[Edge]] = [[] for _ in range(count)]
    degrees = [0] * count
    for edge in edges:
        if edge.recycle:
            continue
        outgoing[edge.source].append(edge)
        incoming[edge.dest].append(edge)
        degrees[edge.dest] += 1
    ready: list[int] = []
    for unit, degree in enumerate(degrees):
        if degree == 0:
            heappush(ready, unit)
    order = []
    while ready:
        unit = heappop(ready)
        order.append(unit)
        for edge in outgoing[unit]:
            degrees[edge.dest] -= 1
            if degrees[edge.dest] == 0:
                heappush(ready, edge.dest)
    if len(order) != count:
        raise ValueError("structure inference requires cycle breaking first")
    return outgoing, incoming, tuple(order)


def _chains(
    count: int, edges: tuple[Edge, ...], outgoing: list[list[Edge]], incoming: list[list[Edge]]
) -> tuple[ProcessPath, ...]:
    """Condense forward degree-two runs into maximal ordered paths.

    Parameters
    ----------
    count : int
        Number of process units.
    edges : tuple[Edge, ...]
        Material edges in stream order.
    outgoing, incoming : list[list[Edge]]
        Forward adjacency in the same order.

    Returns
    -------
    tuple[ProcessPath, ...]
        Every forward edge exactly once, plus isolated-unit paths.
    """
    visited: set[int] = set()
    paths = []
    starts = [
        edge
        for edge in edges
        if not edge.recycle and (len(incoming[edge.source]) != 1 or len(outgoing[edge.source]) != 1)
    ]
    start_streams = {edge.stream for edge in starts}
    starts.extend(edge for edge in edges if not edge.recycle and edge.stream not in start_streams)
    for first in starts:
        if first.stream in visited:
            continue
        units = [first.source]
        streams = []
        edge = first
        while edge.stream not in visited:
            visited.add(edge.stream)
            streams.append(edge.stream)
            units.append(edge.dest)
            if len(incoming[edge.dest]) != 1 or len(outgoing[edge.dest]) != 1:
                break
            edge = outgoing[edge.dest][0]
        paths.append(ProcessPath(tuple(units), tuple(streams)))
    for unit in range(count):
        if not outgoing[unit] and not incoming[unit]:
            paths.append(ProcessPath((unit,), ()))
    return tuple(paths)


def _principal_paths(
    components: tuple[tuple[int, ...], ...], order: tuple[int, ...], outgoing: list[list[Edge]]
) -> tuple[ProcessPath, ...]:
    """Choose a longest forward path per component without path copying.

    Parameters
    ----------
    components : tuple[tuple[int, ...], ...]
        Weak process groups.
    order : tuple[int, ...]
        Topological unit order.
    outgoing : list[list[Edge]]
        Forward material adjacency.

    Returns
    -------
    tuple[ProcessPath, ...]
        One longest-path candidate for each component in component order.
        A utility or regeneration path can be longer than the main run.
    """
    length = [0] * len(outgoing)
    previous: list[tuple[int, int] | None] = [None] * len(outgoing)
    for source in order:
        for edge in outgoing[source]:
            if length[source] + 1 > length[edge.dest]:
                length[edge.dest] = length[source] + 1
                previous[edge.dest] = (source, edge.stream)
    paths = []
    for component in components:
        tail = max(component, key=lambda unit: (length[unit], -unit))
        units = [tail]
        streams = []
        while (step := previous[units[-1]]) is not None:
            source, stream = step
            units.append(source)
            streams.append(stream)
        paths.append(ProcessPath(tuple(reversed(units)), tuple(reversed(streams))))
    return tuple(paths)


def _branches(
    outgoing: list[list[Edge]],
    incoming: list[list[Edge]],
    chains: tuple[ProcessPath, ...],
    units: list,
    streams: list,
) -> tuple[Branch, ...]:
    """Recognize simple split/merge arms and matching repeated trains.

    Parameters
    ----------
    outgoing, incoming : list[list[Edge]]
        Forward adjacency.
    chains : tuple[ProcessPath, ...]
        Maximal non-recycle paths.
    units, streams : list
        Original process units and streams in index order.

    Returns
    -------
    tuple[Branch, ...]
        Disjoint direct-arm diamonds in split-unit order.
    """
    first_path = {path.streams[0]: path for path in chains if path.streams}
    result = []
    for split, exits in enumerate(outgoing):
        if len(exits) < 2:
            continue
        arms = tuple(first_path[edge.stream] for edge in exits)
        merge = arms[0].units[-1]
        if any(arm.units[-1] != merge for arm in arms) or len(incoming[merge]) < 2:
            continue
        signatures = []
        for arm in arms:
            signatures.append(
                tuple(
                    (
                        type(units[unit]).__name__,
                        streams[arm.streams[index - 1]].dest.role,
                        streams[arm.streams[index]].source.role,
                    )
                    for index, unit in enumerate(arm.units[1:-1], start=1)
                )
            )
        repeated = bool(signatures[0]) and all(sig == signatures[0] for sig in signatures)
        result.append(Branch(split, merge, arms, repeated))
    return tuple(result)


def _reachable(start: int, adjacency: list[list[Edge]], *, backwards: bool) -> set[int]:
    """Visit one side of a recycle's forward process region.

    Parameters
    ----------
    start : int
        Process-unit index to start from.
    adjacency : list[list[Edge]]
        Forward or reverse edge lists.
    backwards : bool
        Follow source rather than destination endpoints when true.

    Returns
    -------
    set[int]
        Units reachable in the chosen direction.
    """
    seen = {start}
    stack = [start]
    while stack:
        for edge in adjacency[stack.pop()]:
            peer = edge.source if backwards else edge.dest
            if peer not in seen:
                seen.add(peer)
                stack.append(peer)
    return seen


def _postdominator_masks(
    outgoing: list[list[Edge]], order: tuple[int, ...]
) -> tuple[list[int], dict[int, int]]:
    """Find units visited by every forward path from each unit.

    Parameters
    ----------
    outgoing : list[list[Edge]]
        Forward DAG adjacency.
    order : tuple[int, ...]
        Stable topological unit order.

    Returns
    -------
    tuple[list[int], dict[int, int]]
        Per-unit bitsets of postdominators and unit-to-bit positions.
    """
    rank = {unit: position for position, unit in enumerate(order)}
    masks = [0] * len(outgoing)
    for unit in reversed(order):
        exits = outgoing[unit]
        common = masks[exits[0].dest] if exits else 0
        for edge in exits[1:]:
            common &= masks[edge.dest]
        masks[unit] = common | (1 << rank[unit])
    return masks, rank


def _reachability_masks(
    outgoing: list[list[Edge]], order: tuple[int, ...], rank: dict[int, int]
) -> tuple[list[int], list[int]]:
    """Index forward descendants and reverse ancestors of the DAG.

    Parameters
    ----------
    outgoing : list[list[Edge]]
        Forward process adjacency.
    order : tuple[int, ...]
        Stable topological unit order.
    rank : dict[int, int]
        Unit index to bit position in that order.

    Returns
    -------
    tuple[list[int], list[int]]
        Descendant and ancestor bitsets for every process unit.
    """
    descendants = [0] * len(outgoing)
    ancestors = [0] * len(outgoing)
    for unit in reversed(order):
        mask = 1 << rank[unit]
        for edge in outgoing[unit]:
            mask |= descendants[edge.dest]
        descendants[unit] = mask
    for unit in order:
        mask = ancestors[unit] | (1 << rank[unit])
        ancestors[unit] = mask
        for edge in outgoing[unit]:
            ancestors[edge.dest] |= mask
    return descendants, ancestors


def _branch_regions(
    outgoing: list[list[Edge]], incoming: list[list[Edge]], order: tuple[int, ...]
) -> tuple[BranchRegion, ...]:
    """Find a shared merge and mark whether it closes every exit.

    Parameters
    ----------
    outgoing, incoming : list[list[Edge]]
        Forward and reverse adjacency after recycle cuts.
    order : tuple[int, ...]
        Stable topological unit order.

    Returns
    -------
    tuple[BranchRegion, ...]
        Shared downstream subregions in split-unit order. A split with
        no common merge contributes no region.
    """
    if not any(len(exits) > 1 for exits in outgoing):
        return ()
    masks, rank = _postdominator_masks(outgoing, order)
    descendants, ancestors = _reachability_masks(outgoing, order, rank)
    merge_bits = sum(1 << rank[unit] for unit, entries in enumerate(incoming) if len(entries) >= 2)
    result = []
    for split, exits in enumerate(outgoing):
        if len(exits) < 2:
            continue
        common = merge_bits
        unavoidable = merge_bits
        for edge in exits:
            common &= descendants[edge.dest]
            unavoidable &= masks[edge.dest]
        if not common:
            continue
        first_common = common & -common
        first_closed = unavoidable & -unavoidable
        candidate_bits = (
            (first_common,) if first_closed in (0, first_common) else (first_common, first_closed)
        )
        for merge_bit in candidate_bits:
            merge = order[merge_bit.bit_length() - 1]
            to_merge = ancestors[merge]
            arms = []
            for entry in exits:
                region = {split, entry.dest, merge}
                arm_streams = {entry.stream}
                stack = [entry.dest]
                while stack:
                    unit = stack.pop()
                    if unit == merge:
                        continue
                    for edge in outgoing[unit]:
                        if not to_merge & (1 << rank[edge.dest]):
                            continue
                        arm_streams.add(edge.stream)
                        if edge.dest not in region:
                            region.add(edge.dest)
                            stack.append(edge.dest)
                arms.append(
                    ArmRegion(
                        entry.stream,
                        tuple(sorted(region, key=rank.__getitem__)),
                        tuple(sorted(arm_streams)),
                    )
                )
            result.append(BranchRegion(split, merge, tuple(arms), bool(unavoidable & merge_bit)))
    return tuple(result)


def _corridors(
    edges: tuple[Edge, ...],
    outgoing: list[list[Edge]],
    incoming: list[list[Edge]],
    order: tuple[int, ...],
) -> tuple[Corridor, ...]:
    """Collect every forward arm between each recycle's endpoints.

    Parameters
    ----------
    edges : tuple[Edge, ...]
        All material streams with recycle decisions.
    outgoing, incoming : list[list[Edge]]
        Forward and reverse adjacency.
    order : tuple[int, ...]
        Stable topological unit order.

    Returns
    -------
    tuple[Corridor, ...]
        One read-only corridor record per marked recycle.
    """
    result = []
    for edge in edges:
        if not edge.recycle:
            continue
        head, tail = edge.dest, edge.source
        from_head = _reachable(head, outgoing, backwards=False)
        if tail not in from_head:
            result.append(Corridor(edge.stream, head, tail, (), ()))
            continue
        to_tail = _reachable(tail, incoming, backwards=True)
        region = from_head & to_tail
        forward_streams = tuple(
            candidate.stream
            for candidate in edges
            if not candidate.recycle and candidate.source in region and candidate.dest in region
        )
        result.append(
            Corridor(
                edge.stream,
                head,
                tail,
                tuple(unit for unit in order if unit in region),
                forward_streams,
            )
        )
    return tuple(result)


def infer(fs: Flowsheet) -> Structure:
    """Infer structural facts from the cycle-broken process graph.

    Parameters
    ----------
    fs : Flowsheet
        Sheet after ``layout()`` or after ``_seed_slots(fs)`` followed by
        ``break_cycles(fs)``. Claims read the seeded pin transforms;
        no resolved geometry is read or changed here.

    Returns
    -------
    Structure
        Immutable, index-based process paths, branches, corridors,
        placement claims, and author pin intent.

    Raises
    ------
    ValueError
        If unmarked material edges still contain a cycle.
    """
    units = process_units(fs)
    streams = process_streams(fs)
    index = {unit: position for position, unit in enumerate(units)}
    edges = tuple(
        Edge(
            position,
            index[stream.source.owner],
            index[stream.dest.owner],
            stream.source.role,
            stream.dest.role,
            stream.is_recycle,
        )
        for position, stream in enumerate(streams)
    )
    outgoing, incoming, order = _forward_graph(len(units), edges)
    components = _components(len(units), edges)
    chains = _chains(len(units), edges, outgoing, incoming)
    claims = tuple(
        PlacementClaim(
            index[claim.author],
            index[claim.subject],
            claim.eastward,
            claim.southward,
            claim.confidence,
        )
        for claim in claims_mod.read(streams)
    )
    pins = tuple(
        PinIntent(position, unit._pin, tuple(sorted(unit._pin_ports.items())))
        for position, unit in enumerate(units)
    )
    service_candidates = tuple(
        edge.stream
        for edge in edges
        if not edge.recycle
        and (
            (units[edge.source].kind == "feed" and len(outgoing[edge.source]) > 1)
            or (units[edge.dest].kind == "product" and len(incoming[edge.dest]) > 1)
        )
    )
    return Structure(
        unit_count=len(units),
        edges=edges,
        claims=claims,
        pins=pins,
        components=components,
        forward_order=order,
        chains=chains,
        principal_paths=_principal_paths(components, order, outgoing),
        branches=_branches(outgoing, incoming, chains, units, streams),
        branch_regions=_branch_regions(outgoing, incoming, order),
        corridors=_corridors(edges, outgoing, incoming, order),
        service_candidates=service_candidates,
    )
