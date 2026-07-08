"""Phase 0: Cycle Breaking (Feedback Arc Set)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet
    from pfd.units import Unit
    from pfd.streams import Stream


def break_cycles(fs: "Flowsheet") -> None:
    """Identify and mark recycle streams using DFS back-edge detection.
    
    This phase ensures the layout algorithm works on a Directed Acyclic Graph (DAG).
    Streams marked as is_recycle=True will be drawn backward, while all others
    flow forward through the ranks.
    """
    # 1. Reset all recycles
    for s in fs.streams:
        s.is_recycle = False
        
    if not fs.units:
        return
        
    # 2. Build adjacency for material streams
    # Maps unit -> list of outgoing material streams
    adj: dict["Unit", list["Stream"]] = {u: [] for u in fs.units}
    in_degree: dict["Unit", int] = {u: 0 for u in fs.units}
    
    for s in fs.streams:
        if s.kind == "material":
            adj[s.source.owner].append(s)
            in_degree[s.dest.owner] += 1
            
    # Sort outgoing streams so tear_hint=True are traversed LAST.
    # In DFS, a stream traversed later is more likely to hit a node
    # already on the recursion stack, classifying it as the back-edge.
    for u in fs.units:
        adj[u].sort(key=lambda s: s.tear_hint)
        
    visited = set()
    stack = set()
    
    def dfs(u: "Unit"):
        visited.add(u)
        stack.add(u)
        for s in adj[u]:
            v = s.dest.owner
            if v in stack:
                s.is_recycle = True
            elif v not in visited:
                dfs(v)
        stack.remove(u)
        
    # Start DFS from feed nodes (in-degree == 0)
    feeds = [u for u in fs.units if in_degree[u] == 0]
    
    # If no feeds exist (a perfectly closed loop), start from the unit
    # with the highest out-degree as a heuristic root.
    if not feeds:
        highest = max(fs.units, key=lambda x: len(adj[x]))
        feeds = [highest]
        
    for f in feeds:
        if f not in visited:
            dfs(f)
            
    # Catch any disconnected components
    for u in fs.units:
        if u not in visited:
            dfs(u)
