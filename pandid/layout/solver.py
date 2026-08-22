"""One axis of placement, as a system of difference constraints.

A unit's position is two numbers -- how far along the ribbon it is, and
which row it sits in -- and the two are decided by separate runs of this
same solver. Each run is given constraints of two shapes:

- :class:`Order`, ``pos[after] >= pos[before] + 1``. One end of a stream
  is past the other on this axis.
- :class:`Same`, ``pos[a] == pos[b]``. The two ends line up on this
  axis, which is what a vertical connection says about the column.

Splitting the axes is the whole point. A return line leaving a south
nozzle and entering a north one states *below* and nothing at all about
along, so it contributes one :class:`Order` to the row system and
nothing to the column system -- and stops being a cycle in the column
system without anyone having to break it. The old engine read every edge
as a step to the right and had no way to say that.

How it is solved
----------------
Not by iterating a relaxation to a fixed point and watching for a value
that will not settle. A constraint system with no solution is one with a
cycle in it -- every :class:`Order` weighs one, so no cycle through them
closes at zero -- and finding the cycle is cheaper than watching a value
run away from it. Three kinds of pass, and each is a place a *reason*
can be attached to the constraint that gets dropped:

- **Merge** (:func:`_merge`). Union-find over the :class:`Same`
  constraints, so a stack of units is one node. A union is refused where
  it would put two differently pinned positions in one node, or close a
  cycle nothing weaker can be demoted to open.
- **Break** (:func:`_open`). Depth-first search over what is left,
  serving each node's constraints strongest first so the **weakest**
  claim on a cycle is the one classified as the back edge and dropped.
  That is how a recycle gives way to the forward run it returns along
  rather than the other way about.
- **Rank** (:func:`_rank`). Longest path over the remaining acyclic
  graph, then :func:`_remove_slack`.

:func:`solve` runs merge, break, merge, break, rank -- see the comment
in it for why the first two are a rehearsal.

Rank is the caller's statement of which constraint it would rather keep;
see :mod:`pandid.layout.claims` for the levels and what each means.
Every pass walks its inputs in the order it was handed them and orders
its own scratch by the position of the constraint on the sheet, never by
identity, so a sheet lays out the same way twice.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pandid.units import Unit


class Order(NamedTuple):
    """``pos[after] >= pos[before] + 1`` on the axis being solved."""

    before: "Unit"
    after: "Unit"
    rank: int


class Same(NamedTuple):
    """``pos[a] == pos[b]`` on the axis being solved."""

    a: "Unit"
    b: "Unit"
    rank: int


def solve(units: list["Unit"], orders: list[Order], sames: list[Same],
          pinned: dict["Unit", int], seed: dict["Unit", int] | None = None
          ) -> dict["Unit", int]:
    """Position every unit on one axis, from zero -- or from ``seed``.

    ``pinned`` is the author's word and is never moved. Everything else
    comes out of the constraints, and a unit no constraint reaches
    stays where it started -- which, from zero, is the left edge on the
    column axis and the top band on the row axis.

    ``seed`` starts the relaxation somewhere other than zero, and is how
    the row axis carries the crossing reduction's answer in. Relaxation
    only ever moves a position *further* along, so a seeded axis comes
    back with the seed's order intact wherever the constraints had
    nothing to say -- and it keeps its slack, because on a seeded axis
    the slack is the very preference this was given to preserve.
    """
    # The merge is run twice, and the first run is a rehearsal. Every
    # union is taken on trust and the cycles that closes are broken --
    # but only by demoting a constraint **weaker** than the unions
    # themselves. What survives is the graph the merge is then asked
    # about in earnest, so a union is refused exactly when the cycle it
    # closes is made of constraints as strong as it is.
    #
    # Both halves of that are load-bearing. Without the rehearsal a
    # stack is refused whenever a *return* line runs past it: on
    # 01_ammonia_loop the reactor's bottom outlet and the exchanger's
    # top inlet say plainly that the two are one column, and the loop's
    # recycle -- a constraint the solver was always going to demote --
    # makes them look like two ends of a cycle, so the stack was dropped
    # and the exchanger fell to column 0 at the far end of the sheet
    # from the reactor it hangs under. Without the floor the rehearsal
    # demotes a *forward* run to make room for a union, which is a block
    # ranked before and after itself: A feeds B feeds C, and C also
    # takes A over its roof, so the stack has to be the constraint that
    # gives.
    floor = max((same.rank for same in sames), default=0)
    rehearsed = _merge(units, [], sames, pinned)
    open_ = _open(_nodes(units, rehearsed), orders, rehearsed, floor)
    lead = _merge(units, open_, sames, pinned)
    nodes = _nodes(units, lead)
    forward = _open(nodes, open_, lead)
    return _rank(units, nodes, forward, lead, pinned, seed)


# ---------------------------------------------------------------------------
# 1. Merge: the Same constraints, by union-find
# ---------------------------------------------------------------------------


def _merge(units: list["Unit"], orders: list[Order], sames: list[Same],
           pinned: dict["Unit", int]) -> dict["Unit", "Unit"]:
    """Map each unit to the unit whose position it takes.

    The contracted order graph is carried across the unions rather than
    rebuilt for each candidate. Rebuilding it meant contracting every
    unit and every stream and topologically sorting the result once per
    candidate, which is the whole sheet re-read K times: a chain of 800
    blocks with a feed over each of them spent 2.5 M contractions on one
    ``layout()``. Kept here, a union costs the edges of the group being
    folded in, and the question each candidate asks is asked of the two
    ends rather than of the sheet.
    """
    lead: dict["Unit", "Unit"] = {u: u for u in units}

    def find(u: "Unit") -> "Unit":
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    succ: dict["Unit", set["Unit"]] = defaultdict(set)
    pred: dict["Unit", set["Unit"]] = defaultdict(set)
    for edge in orders:
        if edge.before is not edge.after:
            succ[edge.before].add(edge.after)
            pred[edge.after].add(edge.before)

    fixed = dict(pinned)
    for same in sorted(sames, key=lambda s: -s.rank):
        a, b = find(same.a), find(same.b)
        if a is b or (a in fixed and b in fixed and fixed[a] != fixed[b]):
            continue
        if _closes_cycle(succ, pred, a, b):
            continue
        _fold(succ, pred, a, b)
        lead[a] = b
        if a in fixed:
            fixed[b] = fixed.pop(a)
    return {u: find(u) for u in units}


def _fold(succ: dict, pred: dict, a: "Unit", b: "Unit") -> None:
    """Move ``a``'s edges onto ``b``, which is now the two of them.

    An edge between the pair becomes a loop on the merged node and is
    dropped, exactly as contracting the graph wholesale dropped it: an
    order between two units in one position is no longer a step from one
    position to another, and reading it as one would say the merged node
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


def _closes_cycle(succ: dict, pred: dict, a: "Unit", b: "Unit") -> bool:
    """Is there already a run between ``a`` and ``b`` to close a cycle?

    Asked as a reachability question in both directions rather than as a
    search for a cycle, which is what makes it cheap. That is sound
    because the graph reaching this pass has had the cycles it could
    afford to open already opened (see :func:`solve`) and every union
    that would have closed one has been refused by this same test, so a
    new cycle has to run through the merged node.

    The run has to be **two steps or more**: a single order between the
    pair becomes a loop on the merged node, which is dropped rather than
    read as a cycle (see :func:`_fold`).
    """
    return _joined(succ, pred, a, b) or _joined(succ, pred, b, a)


def _joined(succ: dict, pred: dict, x: "Unit", y: "Unit") -> bool:
    """Is there a run of two steps or more from ``x`` to ``y``?

    Such a run has an interior node: one the order reaches from ``x``
    and reaches ``y`` from. So the two sets are grown towards each other
    -- what ``x`` leads to, and what leads to ``y`` -- and the answer is
    whether they ever touch. Growing the smaller of the two each time is
    what keeps a satellite with nothing downstream of it from walking
    the length of the sheet looking for an anchor that could not reach
    it: a feed over a block's roof settles the question on its own empty
    edge set, which is the case nearly every stacked sheet is made of.

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


# ---------------------------------------------------------------------------
# 2. Break: the cycles the Order constraints close
# ---------------------------------------------------------------------------


def _nodes(units: list["Unit"], lead: dict["Unit", "Unit"]) -> list["Unit"]:
    """The merged nodes, in the order the sheet holds their leaders."""
    seen: dict["Unit", None] = {}
    for u in units:
        seen.setdefault(lead[u], None)
    return list(seen)


def _open(nodes: list["Unit"], orders: list[Order],
          lead: dict["Unit", "Unit"], floor: int | None = None) -> list[Order]:
    """The orders that survive once the merged graph's cycles are broken.

    Contracted onto the merged nodes to be walked and handed back as the
    caller's own constraints, so a second merge can be tested against
    them. Two orders on one merged pair say the same thing and differ
    only in rank, so the pair is walked at the strongest of them -- and
    they stand or fall together, since what the walk decides is about
    the pair and not about either constraint on its own.
    """
    members: dict[tuple["Unit", "Unit"], list[int]] = {}
    rank: dict[tuple["Unit", "Unit"], int] = {}
    for index, edge in enumerate(orders):
        a, b = lead[edge.before], lead[edge.after]
        if a is b:
            continue  # a step from a node to itself; the merge dropped it
        members.setdefault((a, b), []).append(index)
        rank[(a, b)] = max(rank.get((a, b), edge.rank), edge.rank)
    pairs = list(members)
    dropped = _break_cycles(nodes, [Order(a, b, rank[(a, b)]) for a, b in pairs], floor)
    dead = {index for pair in dropped for index in members[pairs[pair]]}
    return [e for i, e in enumerate(orders) if i not in dead]


def _break_cycles(nodes: list["Unit"], edges: list[Order],
                  floor: int | None = None) -> set[int]:
    """The edges to drop to leave an acyclic graph: the weakest on each cycle.

    Every order weighs one, so a cycle through them can only close
    above zero -- there is no such thing here as a cycle a solution
    satisfies, and "a value still moving" and "a cycle" are the same
    finding. The depth-first walk classifies an edge into a node already
    on the recursion stack as the back edge, and each node's outgoing
    edges are served **strongest first** so it is the weakest claim that
    arrives late and is the one classified: a recycle gives way to the
    forward run it returns along, not the other way about.

    ``floor`` caps what may be demoted: only a claim ranked *below* it
    is droppable, and a cycle made entirely of claims at or above it is
    left closed. That is not a failure to answer -- it is the answer,
    for the caller that asks whether a cycle can be paid for.

    Walked with an explicit stack rather than the call stack, so the
    depth of the longest unbranched chain never meets Python's recursion
    limit (#413).
    """
    out: dict["Unit", list[tuple[int, int, int, "Unit"]]] = defaultdict(list)
    for index, edge in enumerate(edges):
        # Sorted on the rank and then on where the caller put the
        # constraint, never on identity: two claims that tie on rank are
        # separated by the order the sheet stated them in, which is the
        # same order on every run.
        out[edge.before].append((-edge.rank, index, edge.rank, edge.after))
    for node in out:
        out[node].sort()

    dropped: set[int] = set()
    visited: set["Unit"] = set()
    stack: set["Unit"] = set()

    for root in nodes:
        if root in visited:
            continue
        visited.add(root)
        stack.add(root)
        frames: list[tuple["Unit", int]] = [(root, 0)]
        while frames:
            node, i = frames[-1]
            edges_out = out[node]
            if i < len(edges_out):
                frames[-1] = (node, i + 1)
                _, index, rank, peer = edges_out[i]
                if peer in stack:
                    if floor is None or rank < floor:
                        dropped.add(index)
                elif peer not in visited:
                    visited.add(peer)
                    stack.add(peer)
                    frames.append((peer, 0))
            else:
                stack.remove(node)
                frames.pop()
    return dropped


# ---------------------------------------------------------------------------
# 3. Rank: longest path, then the slack out of it
# ---------------------------------------------------------------------------


def _rank(units: list["Unit"], nodes: list["Unit"], forward: list[Order],
          lead: dict["Unit", "Unit"], pinned: dict["Unit", int],
          seed: dict["Unit", int] | None) -> dict["Unit", int]:
    """Longest path over the acyclic graph, pins held where they are."""
    adj: dict["Unit", list["Unit"]] = defaultdict(list)
    in_degree: dict["Unit", int] = dict.fromkeys(nodes, 0)
    for pair in dict.fromkeys((lead[e.before], lead[e.after]) for e in forward):
        if pair[0] is pair[1]:
            continue
        adj[pair[0]].append(pair[1])
        in_degree[pair[1]] += 1

    pos = dict.fromkeys(nodes, 0)
    if seed is not None:
        # A merged node starts where the furthest of its members did:
        # the merge says they end up together, and relaxation can only
        # move a position on, so the near ones have to come to the far.
        # Written rather than maxed against the zero above, because a
        # seed is free to be negative -- a relief valve on a crown is a
        # band above the run it sits on, and clamping it at zero is the
        # sheet drawn with the valve *in* the vessel.
        started: set["Unit"] = set()
        for u in units:
            node = lead[u]
            pos[node] = max(pos[node], seed[u]) if node in started else seed[u]
            started.add(node)
    fixed: set["Unit"] = set()
    for u in units:
        if u in pinned:
            pos[lead[u]] = pinned[u]
            fixed.add(lead[u])

    # A list rather than a deque, walked in the order the sheet holds
    # the nodes: what comes out is a topological order, of which there
    # are many, and picking one by hand is what makes the sheet the same
    # every time.
    ready = [n for n in nodes if in_degree[n] == 0]
    order: list["Unit"] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for peer in adj[node]:
            if peer not in fixed:
                pos[peer] = max(pos[peer], pos[node] + 1)
            in_degree[peer] -= 1
            if in_degree[peer] == 0:
                ready.append(peer)
    assert len(order) == len(nodes), "cycle survived _break_cycles"

    if seed is None:
        _remove_slack(adj, order, pos, fixed)
    return {u: pos[lead[u]] for u in units}


def _remove_slack(adj: dict, order: list, pos: dict, fixed: set) -> None:
    """Slide every position as far along as its own connections allow.

    Longest path measures *distance from a source*, which is the edge of
    the drawing rather than anything on the sheet, so a branch that
    joins the spine late starts as far back as the spine does and then
    runs the width of the page to reach it. A cooling water flag lands
    in column 0 and crosses under nine units to get to the exchanger it
    serves; the blower that strips a degasser eight columns along starts
    beside the raw water tank.

    Removing the slack is Sugiyama's own answer, and it is safe by
    construction only so long as a position moves *forward*: it goes to
    one short of its nearest successor, so every constraint it is on
    stays satisfied at a gap of at least one and no predecessor can be
    violated. Positions are visited in reverse topological order, so
    each is measured against successors that are already final. A pin is
    an answer already given, and a node with nothing downstream of it is
    as far along as the sheet goes.

    A pin *downstream* is the one case where one short of the nearest
    successor is behind, and a position that moves back is one dragged
    behind the units feeding it -- off the page entirely, where the pin
    sits at zero. Two pins with a chain between them longer than the gap
    they leave cannot both be honoured; the derived position holds its
    longest-path answer and the constraint into the pin is the one that
    comes out short.
    """
    for node in reversed(order):
        if node in fixed or not adj[node]:
            continue
        pos[node] = max(pos[node], min(pos[peer] for peer in adj[node]) - 1)
