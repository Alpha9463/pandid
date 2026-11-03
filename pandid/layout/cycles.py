"""Mark the process streams that close a cycle as recycle streams."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit
    from pandid.streams import Stream


def break_cycles(fs: "Flowsheet") -> None:
    """Mark the back edges of the process graph as recycle streams.

    The depth-first walk starts from units with no incoming process
    stream, then from any unit not yet reached.
    """
    from pandid.layout.stages import process_streams, process_units

    for s in fs.streams:
        s._is_recycle = False

    units = process_units(fs)
    if not units:
        return

    adj: dict["Unit", list["Stream"]] = {u: [] for u in units}
    in_degree: dict["Unit", int] = {u: 0 for u in units}

    for s in process_streams(fs):
        assert s.source.owner is not None
        assert s.dest.owner is not None
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1
            
    # Walk draw_as_recycle streams last from each unit.
    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)
        
    visited: set["Unit"] = set()
    stack: set["Unit"] = set()

    def dfs(start: "Unit") -> None:
        """Walk depth first from one unit, marking back edges."""
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

    feeds = [u for u in units if in_degree[u] == 0]

    # With no feed, start from the highest out-degree.
    if not feeds:
        highest = max(units, key=lambda x: len(adj[x]))
        feeds = [highest]

    for f in feeds:
        if f not in visited:
            dfs(f)

    for u in units:
        if u not in visited:
            dfs(u)
