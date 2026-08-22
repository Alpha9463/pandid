"""Phase 0: Cycle Breaking (Feedback Arc Set)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit
    from pandid.streams import Stream


def break_cycles(fs: "Flowsheet") -> None:
    """Identify and mark recycle streams using DFS back-edge detection.

    This phase ensures the layout algorithm works on a Directed Acyclic
    Graph (DAG). Streams marked as is_recycle=True will be drawn
    backward, while all others flow forward through the ranks.
    """
    from pandid.layout.stages import process_streams, process_units

    # 1. Reset all recycles (private field; is_recycle is read-only to
    #    callers)
    for s in fs.streams:
        s._is_recycle = False

    units = process_units(fs)
    if not units:
        return

    # 2. Build adjacency over the *process* runs -- material, between
    #    two units that carry material. A signal is not a step along the
    #    flow, so a control loop closing on the valve it commands is not
    #    a cycle here and there is nothing in it to tear. That was the
    #    old engine's defect and not a simplification: with signals in,
    #    a loop's feedback wire was marked a recycle, then excluded from
    #    every phase that places anything, so its two ends were placed
    #    with no relationship to each other and the router drew it the
    #    long way round (#430).
    adj: dict["Unit", list["Stream"]] = {u: [] for u in units}
    in_degree: dict["Unit", int] = {u: 0 for u in units}

    for s in process_streams(fs):
        assert s.source.owner is not None
        assert s.dest.owner is not None
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1
            
    # Sort outgoing streams so draw_as_recycle=True are traversed LAST.
    # In DFS, a stream traversed later is more likely to hit a node
    # already on the recursion stack, classifying it as the back-edge.
    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)
        
    visited: set["Unit"] = set()
    stack: set["Unit"] = set()

    def dfs(start: "Unit") -> None:
        """Walk from ``start`` with an explicit stack instead of the
        call stack, so the depth of the longest unbranched chain never
        meets Python's recursion limit (#413).

        Each frame is a node plus how far through *its own* adjacency
        list it has gotten -- exactly the state a recursive call would
        otherwise hold on the real stack -- so an edge is visited, and
        a back edge marked, in precisely the order the recursive walk
        used to: pushing a frame for ``v`` and looping happens the
        instant a recursive call to ``dfs(v)`` would have, and a frame
        is popped, with ``u`` dropped from ``stack``, at the same point
        a recursive call would have returned. This is a mechanical
        rewrite of the recursion below, not a re-ordering of it:

            def dfs(u):
                visited.add(u); stack.add(u)
                for s in adj[u]:
                    v = s.dest.owner
                    if v in stack: s._is_recycle = True
                    elif v not in visited: dfs(v)
                stack.remove(u)
        """
        visited.add(start)
        stack.add(start)
        frames: list[tuple["Unit", int]] = [(start, 0)]
        while frames:
            u, i = frames[-1]
            if i < len(adj[u]):
                frames[-1] = (u, i + 1)
                s = adj[u][i]
                v = s.dest.owner
                assert v is not None
                if v in stack:
                    s._is_recycle = True
                elif v not in visited:
                    visited.add(v)
                    stack.add(v)
                    frames.append((v, 0))
            else:
                stack.remove(u)
                frames.pop()

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
