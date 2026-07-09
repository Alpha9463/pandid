"""Phase 1: Rank Assignment (Layering)."""

from typing import TYPE_CHECKING
from collections import defaultdict, deque

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class VirtualNode:
    """A dummy node inserted to split long edges across multiple ranks."""
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self.placement = None  # Will be assigned later


def assign_layers(fs: "Flowsheet") -> None:
    """Assign a column rank to each unit using longest-path algorithm."""
    from pfd.geometry import Placement
    
    # 1. Initialize Placements if they don't exist
    for u in fs.units:
        if u.placement is None:
            u.placement = Placement()
            
    # 2. Build DAG of forward streams only
    adj = defaultdict(list)
    in_degree = defaultdict(int)
    
    for u in fs.units:
        in_degree[u] = 0
        
    for s in fs.streams:
        if not s.is_recycle:
            assert s.source.owner is not None and s.dest.owner is not None
            adj[s.source.owner].append(s.dest.owner)
            in_degree[s.dest.owner] += 1
            
    # 3. Topological Sort + Longest Path
    queue = deque([u for u in fs.units if in_degree[u] == 0])
    ranks = {}
    
    for u in fs.units:
        assert u.placement is not None
        if u.placement.col is not None:
            ranks[u] = u.placement.col
        else:
            ranks[u] = 0
            
    visited_count = 0
    while queue:
        u = queue.popleft()
        visited_count += 1
        
        for v in adj[u]:
            assert v.placement is not None
            # The rank of v must be at least rank(u) + 1
            if v.placement.col is None:
                ranks[v] = max(ranks[v], ranks[u] + 1)
                
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
                
    if visited_count < len(fs.units):
        raise ValueError("Cycle detected in forward streams. Phase 0 failed.")
        
    # Write ranks back to placement
    for u in fs.units:
        assert u.placement is not None
        if u.placement.col is None:
            u.placement.col = ranks[u]

    # Note: Virtual Node insertion for long edges (spanning > 1 rank) 
    # would go here if we were doing full Sugiyama crossing reduction.
    # For v1, we will handle crossing reduction directly on units and let 
    # the orthogonal router deal with edge geometries.
