"""Structural facts used to keep connected layout moves safe."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from typing import TYPE_CHECKING

from pandid.layout import claims as claims_mod
from pandid.layout.stages import process_streams, process_units

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


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
class Structure:
    """Process edges, claims, and closed or partial branch regions.

    Attributes
    ----------
    unit_count : int
        Number of process units in the drawing.
    edges : tuple[Edge, ...]
        Material connections in process-stream order.
    claims : tuple[PlacementClaim, ...]
        Relative placement preferences used by search scoring.
    branch_regions : tuple[BranchRegion, ...]
        Regions that constrain safe connected movement.
    """

    unit_count: int
    edges: tuple[Edge, ...]
    claims: tuple[PlacementClaim, ...]
    branch_regions: tuple[BranchRegion, ...]


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


def infer(fs: Flowsheet) -> Structure:
    """Infer only the process facts consumed by layout search.

    Parameters
    ----------
    fs : Flowsheet
        Sheet after cycle breaking and process slot seeding.

    Returns
    -------
    Structure
        Immutable process edges, claims, and branch regions.

    Raises
    ------
    ValueError
        If unmarked forward edges still contain a cycle.
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
    return Structure(len(units), edges, claims, _branch_regions(outgoing, incoming, order))
