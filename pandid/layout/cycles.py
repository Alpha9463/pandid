"""Mark the process streams that close a cycle as return lines.

Placement needs an acyclic process graph. A depth-first walk marks each
back edge with ``Stream._is_recycle``; those streams are drawn right to
left and state a reversed claim (:mod:`pandid.layout.claims`).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit
    from pandid.streams import Stream


def break_cycles(fs: "Flowsheet") -> None:
    """Mark the back edges of the process graph as recycle streams.

    Only process streams count: a signal is not a step along the flow, so a
    control loop is never a cycle here. The walk starts from units with no
    incoming process stream, in flowsheet order, and then from any unit not
    yet reached. Streams with ``draw_as_recycle=True`` are walked last from
    each unit, which makes them the likeliest back edge.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose streams are marked. Every stream's recycle mark is reset
        first.
    """
    from pandid.layout.stages import process_streams, process_units

    # Reset every mark; ``is_recycle`` is read-only to callers.
    for s in fs.streams:
        s._is_recycle = False

    units = process_units(fs)
    if not units:
        return

    # Build adjacency over process streams only.
    adj: dict["Unit", list["Stream"]] = {u: [] for u in units}
    in_degree: dict["Unit", int] = {u: 0 for u in units}

    for s in process_streams(fs):
        assert s.source.owner is not None
        assert s.dest.owner is not None
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1
            
    # Walk draw_as_recycle streams last so they are the likeliest back edge.
    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)
        
    visited: set["Unit"] = set()
    stack: set["Unit"] = set()

    def dfs(start: "Unit") -> None:
        """Walk depth first from one unit, marking back edges.

        An explicit stack of ``(unit, next edge index)`` frames replaces
        recursion, so a long chain cannot reach Python's recursion limit.
        Edges are visited in the same order a recursive walk would use.

        Parameters
        ----------
        start : Unit
            Unit to start from.
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

    # Start from units with no incoming process stream.
    feeds = [u for u in units if in_degree[u] == 0]

    # A closed loop has no such unit: start from the highest out-degree.
    if not feeds:
        highest = max(units, key=lambda x: len(adj[x]))
        feeds = [highest]

    for f in feeds:
        if f not in visited:
            dfs(f)

    # Reach every component the walk has not visited.
    for u in units:
        if u not in visited:
            dfs(u)
