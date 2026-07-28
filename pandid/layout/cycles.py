"""Phase 0: Cycle Breaking (Feedback Arc Set)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit
    from pandid.streams import Stream


def break_cycles(fs: "Flowsheet") -> None:
    """Identify and mark recycle streams using DFS back-edge detection.
    
    This phase ensures the layout algorithm works on a Directed Acyclic Graph (DAG).
    Streams marked as is_recycle=True will be drawn backward, while all others
    flow forward through the ranks.
    """
    from pandid.layout.attach import free_streams, free_units

    # 1. Reset all recycles (private field; is_recycle is read-only to callers)
    for s in fs.streams:
        s._is_recycle = False

    units = free_units(fs)
    if not units:
        return

    # 2. Build adjacency across ALL streams (material, energy, and signal). Any
    # of them can form a cycle the layering DAG must be free of, e.g. a control
    # loop's transmitter -> controller -> valve -> ... signal feedback.
    adj: dict["Unit", list["Stream"]] = {u: [] for u in units}
    in_degree: dict["Unit", int] = {u: 0 for u in units}

    for s in free_streams(fs):
        assert s.source.owner is not None
        assert s.dest.owner is not None
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1
            
    # Sort outgoing streams so draw_as_recycle=True are traversed LAST.
    # In DFS, a stream traversed later is more likely to hit a node
    # already on the recursion stack, classifying it as the back-edge.
    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)
        
    visited = set()
    stack = set()
    
    def dfs(u: "Unit"):
        visited.add(u)
        stack.add(u)
        for s in adj[u]:
            v = s.dest.owner
            assert v is not None
            if v in stack:
                s._is_recycle = True
            elif v not in visited:
                dfs(v)
        stack.remove(u)
        
    # Start DFS from feed nodes (in-degree == 0)
    feeds = [u for u in units if in_degree[u] == 0]

    # If no feeds exist (a perfectly closed loop), start from the unit
    # with the highest out-degree as a heuristic root.
    if not feeds:
        highest = max(units, key=lambda x: len(adj[x]))
        feeds = [highest]

    for f in feeds:
        if f not in visited:
            dfs(f)

    # Catch any disconnected components
    for u in units:
        if u not in visited:
            dfs(u)
