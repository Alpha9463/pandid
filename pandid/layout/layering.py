"""Phase 1: Rank Assignment (Layering)."""

from typing import TYPE_CHECKING
from collections import defaultdict, deque

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


def assign_layers(fs: "Flowsheet") -> None:
    """Assign a column rank to each unit using longest-path algorithm.

    Operates on the pre-seeded ``_slot`` scratch state (see ``_seed_slots``).
    """
    from pandid.layout.attach import free_streams, free_units

    units = free_units(fs)

    # Build DAG of forward streams only
    adj = defaultdict(list)
    in_degree = defaultdict(int)

    for u in units:
        in_degree[u] = 0

    for s in free_streams(fs):
        if not s.is_recycle:
            assert s.source.owner is not None and s.dest.owner is not None
            adj[s.source.owner].append(s.dest.owner)
            in_degree[s.dest.owner] += 1
            
    # 3. Topological Sort + Longest Path
    queue = deque([u for u in units if in_degree[u] == 0])
    ranks = {}

    for u in units:
        if u._slot.col is not None:
            ranks[u] = u._slot.col
        else:
            ranks[u] = 0
            
    visited_count = 0
    while queue:
        u = queue.popleft()
        visited_count += 1
        
        for v in adj[u]:
            # The rank of v must be at least rank(u) + 1
            if v._slot.col is None:
                ranks[v] = max(ranks[v], ranks[u] + 1)
                
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
                
    if visited_count < len(units):
        raise ValueError("Cycle detected in forward streams. Phase 0 failed.")

    # Write ranks back to the solver slot
    for u in units:
        if u._slot.col is None:
            u._slot.col = ranks[u]

    # Virtual-node insertion for long edges (spanning > 1 rank) would go here in
    # full Sugiyama crossing reduction. Crossing reduction runs directly on the
    # units instead, leaving edge geometry to the orthogonal router.
