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
    construction only so long as a rank moves *right*: it goes to one
    short of its nearest successor, so every edge it is on stays a
    forward edge of length at least one and no predecessor can be
    violated. Ranks are visited in reverse topological order, so each is
    measured against successors that are already final. A pinned column
    is an answer already given, and a rank with nothing downstream of it
    is as far right as the sheet goes.

    A pin *downstream* is the one case where one short of the nearest
    successor is to the left, and a rank that moves left is a rank
    dragged behind the units feeding it -- off the page entirely, where
    the pin sits in column 0. Two pins with a chain between them longer
    than the gap they leave cannot both be honoured; the derived rank
    holds its longest-path column and the edge into the pin is the one
    that comes out short.
    """
    for g in reversed(order):
        if g in pinned or not adj[g]:
            continue
        ranks[g] = max(ranks[g], min(ranks[h] for h in adj[g]) - 1)


def _share_columns(units: list, flow: list["Stream"],
                   stacks: list["Stack"]) -> dict:
    """Map each unit to the unit whose rank it takes.

    Union-find over the vertical edges, so a stack of units ranks once.
    A union is refused where it would put two differently pinned columns
    in one rank, or close a cycle in the contracted flow graph. Either
    makes the ranking unanswerable, and a sheet with one constraint
    dropped is worth more than a sheet with no ranks at all.

    The contracted graph is carried across the unions rather than rebuilt
    for each candidate. Rebuilding it meant contracting every unit and
    every stream and topologically sorting the result once per stacked
    edge, which is the whole sheet re-read K times: a chain of 800 blocks
    with a feed over each of them spent 2.5 M contractions and 2.6 M
    find()s on one ``layout()``. Kept here, a union costs the edges of
    the group being folded in, and the question each candidate asks is
    asked of the two ends rather than of the sheet.
    """
    lead = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    succ: dict = defaultdict(set)
    pred: dict = defaultdict(set)
    for s in flow:
        assert s.source.owner is not None and s.dest.owner is not None
        x, y = s.source.owner, s.dest.owner
        if x is not y:
            succ[x].add(y)
            pred[y].add(x)

    col = {u: u._slot.col for u in units if u._slot.col is not None}
    for st in stacks:
        a, b = find(st.satellite), find(st.anchor)
        if a is b or (a in col and b in col and col[a] != col[b]):
            continue
        if _closes_cycle(succ, pred, a, b):
            continue
        _fold(succ, pred, a, b)
        lead[a] = b
        if a in col:
            col[b] = col.pop(a)
    return {u: find(u) for u in units}


def _fold(succ: dict, pred: dict, a, b) -> None:
    """Move ``a``'s edges onto ``b``, which is now the two of them.

    An edge between the pair becomes a loop on the merged node and is
    dropped, exactly as contracting the graph wholesale dropped it: a
    stream between two units in one rank is no longer a step from one
    rank to another, and reading it as one would say the merged rank
    comes after itself.
    """
    for y in succ.pop(a, ()):
        pred[y].discard(a)
        if y is not b:
            succ[b].add(y)
            pred[y].add(b)
    for x in pred.pop(a, ()):
        succ[x].discard(a)
        if x is not b:
            pred[b].add(x)
            succ[x].add(b)
    succ[b].discard(b)
    pred[b].discard(b)


def _closes_cycle(succ: dict, pred: dict, a, b) -> bool:
    """Would merging ranks ``a`` and ``b`` leave the flow graph cyclic?

    The graph this is asked about is acyclic already -- Phase 0 broke the
    cycles in the flow, and every union that would have closed one has
    been refused by this same test -- so a cycle in the merged graph has
    to run through the merged node. That is a run out of one end and back
    into the other, and it has to be **two steps or more**: a single
    stream between the pair becomes a loop on the merged node, which is
    dropped rather than read as a cycle (see :func:`_fold`).
    """
    return _joined(succ, pred, a, b) or _joined(succ, pred, b, a)


def _joined(succ: dict, pred: dict, x, y) -> bool:
    """Is there a run of two steps or more from ``x`` to ``y``?

    Such a run has an interior node: one the flow reaches from ``x`` and
    reaches ``y`` from. So the two sets are grown towards each other --
    what ``x`` leads to, and what leads to ``y`` -- and the answer is
    whether they ever touch. Growing the smaller of the two each time is
    what keeps a satellite with nothing downstream of it from walking the
    length of the sheet looking for an anchor that could not reach it: a
    feed over a block's roof settles the question on its own empty edge
    set, which is the case nearly every stacked sheet is made of.

    Each new front is tested against the whole of the far side, so a
    node the two reach at different times is still caught by whichever
    of them arrives second.
    """
    ahead, behind = set(succ[x]), set(pred[y])
    if not ahead.isdisjoint(behind):
        return True
    seen_ahead, seen_behind = set(ahead), set(behind)
    while ahead and behind:
        if len(ahead) <= len(behind):
            ahead = {n for f in ahead for n in succ[f]} - seen_ahead
            if not ahead.isdisjoint(seen_behind):
                return True
            seen_ahead |= ahead
        else:
            behind = {n for f in behind for n in pred[f]} - seen_behind
            if not behind.isdisjoint(seen_ahead):
                return True
            seen_behind |= behind
    return False
