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
    from pandid.layout.attach import free_streams, free_units

    # 1. Reset all recycles (private field; is_recycle is read-only to
    #    callers)
    for s in fs.streams:
        s._is_recycle = False

    units = free_units(fs)
    if not units:
        return

    # 2. Build adjacency over free_streams(), which is every stream
    #    between two ranked units. Kind is not filtered: material,
    #    energy and signal can each close a cycle the layering DAG must
    #    be free of, and a ranked-to-ranked signal run is as much a back
    #    edge as a pipe is.
    #
    #    What the filter does cost is the textbook example. A control
    #    loop's transmitter -> controller -> valve feedback runs through
    #    balloons, and every stream touching one is dropped here, so on
    #    a sheet with the whole loop drawn this function sees none of
    #    it. That is not a hole in the DAG -- an attached unit is placed
    #    from its host and never carries a rank for a cycle to break --
    #    but a reader looking for the loop will not find it below.
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
