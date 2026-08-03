"""Phase 1: Rank Assignment (Layering)."""

from typing import TYPE_CHECKING
from collections import defaultdict, deque

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.layout.stacking import Stack
    from pandid.streams import Stream
    from pandid.units import Unit


def assign_layers(fs: "Flowsheet") -> None:
    """Assign a column rank to each unit using longest-path algorithm.

    Operates on the pre-seeded ``_slot`` scratch state (see
    ``_seed_slots``). Units a vertical connection stacks (see
    :mod:`pandid.layout.stacking`) are ranked as one: north and south say
    *above* and *below*, which is a statement about the row, so the
    column has to come out the same for both ends or the row cannot be
    honoured.
    """
    from pandid.layout.attach import free_streams, free_units
    from pandid.layout.stacking import stacked_edges

    units = free_units(fs)
    stacks = stacked_edges(fs)
    vertical = {id(st.stream) for st in stacks}
    flow = [s for s in free_streams(fs)
            if not s.is_recycle and id(s) not in vertical]
    head = _share_columns(units, flow, stacks)

    # Build DAG of forward streams only, over the shared columns.
    adj = defaultdict(list)
    in_degree: dict = {head[u]: 0 for u in units}

    for s in flow:
        assert s.source.owner is not None and s.dest.owner is not None
        a, b = head[s.source.owner], head[s.dest.owner]
        if a is b:
            continue
        adj[a].append(b)
        in_degree[b] += 1

    # 3. Topological Sort + Longest Path
    ranks = dict.fromkeys(in_degree, 0)
    pinned = set()
    for u in units:
        if u._slot.col is not None:
            ranks[head[u]] = u._slot.col
            pinned.add(head[u])

    queue = deque([g for g in in_degree if in_degree[g] == 0])
    order = []
    while queue:
        g = queue.popleft()
        order.append(g)

        for h in adj[g]:
            # The rank of h must be at least rank(g) + 1
            if h not in pinned:
                ranks[h] = max(ranks[h], ranks[g] + 1)

            in_degree[h] -= 1
            if in_degree[h] == 0:
                queue.append(h)

    if len(order) < len(in_degree):
        raise ValueError("Cycle detected in forward streams. Phase 0 failed.")

    _remove_slack(adj, order, ranks, pinned)

    # Write ranks back to the solver slot
    for u in units:
        if u._slot.col is None:
            u._slot.col = ranks[head[u]]

    # Virtual-node insertion for long edges (spanning > 1 rank) would go
    # here in full Sugiyama crossing reduction. Crossing reduction runs
    # directly on the units instead, leaving edge geometry to the
    # orthogonal router.


def _remove_slack(adj: dict, order: list, ranks: dict, pinned: set) -> None:
    """Slide every rank as far right as its own connections allow.

    Longest path ranks by *distance from a source*, which is the left
    edge of the drawing rather than anything on the sheet, so a branch
    that joins the spine late starts as far left as the spine does and
    then runs the width of the page to reach it. A cooling water flag
    lands in column 0 and crosses under nine units to get to the
    exchanger it serves; the blower that strips a degasser eight columns
    along starts beside the raw water tank.

    Removing the slack is Sugiyama's own answer, and it is safe by
    construction: a rank only moves *right*, and only to one short of
    its nearest successor, so every edge it is on stays a forward edge
    of length at least one and no predecessor can be violated. Ranks are
    visited in reverse topological order, so each is measured against
    successors that are already final. A pinned column is an answer
    already given, and a rank with nothing downstream of it is as far
    right as the sheet goes.
    """
    for g in reversed(order):
        if g in pinned or not adj[g]:
            continue
        ranks[g] = min(ranks[h] for h in adj[g]) - 1


def _share_columns(units: list, flow: list["Stream"],
                   stacks: list["Stack"]) -> dict:
    """Map each unit to the unit whose rank it takes.

    Union-find over the vertical edges, so a stack of units ranks once.
    A union is refused where it would put two differently pinned columns
    in one rank, or close a cycle in the contracted flow graph. Either
    makes the ranking unanswerable, and a sheet with one constraint
    dropped is worth more than a sheet with no ranks at all.
    """
    lead = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    col = {u: u._slot.col for u in units if u._slot.col is not None}
    for st in stacks:
        a, b = find(st.satellite), find(st.anchor)
        if a is b or (a in col and b in col and col[a] != col[b]):
            continue
        if _closes_cycle(units, flow, find, a, b):
            continue
        lead[a] = b
        if a in col:
            col[b] = col.pop(a)
    return {u: find(u) for u in units}


def _closes_cycle(units: list, flow: list["Stream"], find, a, b) -> bool:
    """Would merging ranks ``a`` and ``b`` leave the flow graph cyclic?"""
    def merged(u: "Unit"):
        g = find(u)
        return b if g is a else g

    adj = defaultdict(set)
    nodes = {merged(u) for u in units}
    for s in flow:
        assert s.source.owner is not None and s.dest.owner is not None
        x, y = merged(s.source.owner), merged(s.dest.owner)
        if x is not y:
            adj[x].add(y)
    in_degree = dict.fromkeys(nodes, 0)
    for ys in adj.values():
        for y in ys:
            in_degree[y] += 1
    queue = deque([n for n in nodes if in_degree[n] == 0])
    seen = 0
    while queue:
        n = queue.popleft()
        seen += 1
        for y in adj[n]:
            in_degree[y] -= 1
            if in_degree[y] == 0:
                queue.append(y)
    return seen < len(nodes)
