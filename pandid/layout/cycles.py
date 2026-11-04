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

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose streams to mark.
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
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1
            
    # Walk draw_as_recycle streams last from each unit.
    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)
        
    visited: set["Unit"] = set()
    stack: set["Unit"] = set()

    feeds = [u for u in units if in_degree[u] == 0]

    # With no feed, start from the highest out-degree.
    if not feeds:
        highest = max(units, key=lambda x: len(adj[x]))
        feeds = [highest]

    # Walk depth first from each feed, then from each unit not yet reached.
    for start in [*feeds, *units]:
        if start in visited:
            continue
        visited.add(start)
        stack.add(start)
        frames: list[tuple["Unit", int]] = [(start, 0)]
        while frames:
            u, i = frames[-1]
            if i < len(adj[u]):
                frames[-1] = (u, i + 1)
                s = adj[u][i]
                v = s.dest.owner
                if v in stack:
                    s._is_recycle = True
                elif v not in visited:
                    visited.add(v)
                    stack.add(v)
                    frames.append((v, 0))
            else:
                stack.remove(u)
                frames.pop()
