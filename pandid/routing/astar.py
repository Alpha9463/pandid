import bisect
import heapq
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Literal
from pandid.routing.visibility import VisibilityGraph

BEND_PENALTY = 500.0

# The two axes a crossing is ever measured on. A ``str`` would take a typo or
# a stray direction letter silently -- ``crosses("garbage")`` used to fall
# through to the ``else`` branch and answer a *vertical*-run question, which
# is worse than raising, since a caller reads a wrong answer as a right one.
Axis = Literal["h", "v"]

# What one perpendicular crossing of an already-drawn line costs, charged
# only when the search settles for a route that needs it (see the crossing
# check in the main loop below).
#
# Chosen by sweeping this value across the full corpus
# (``scripts/route_quality.py`` and ``scripts/layout_quality.py``, both
# corpora together) at every whole integer from 0px to 40px -- the range
# this choice actually depends on, not a claim about anything past it -- and
# reading off crossing count, bend-optimal share and mean length ratio at
# each. That is corpus tuning: the goal is the smallest value that clears
# every crossing this corpus has a same- or near-cost alternative for, and a
# sweep over the corpus is how that smallest value is found, not something
# to call untuned. What the sweep actually shows:
#
#   penalty   pinned cross   auto cross   auto bend-optimal%   auto mean len
#     0            32            246           90.485437          1.076884
#     1-6          29            233           90.485437          1.076884
#     7-15         29            232           90.485437          1.076884
#    16-25         29            232           90.485437          1.077248
#    26-30         29            225           90.291262          1.077660
#    31-40         29            225           90.291262          1.077840
#
# 1px through 15px is flat on bend-optimal share and mean length ratio --
# nothing in that range trades either away -- while the crossing count alone
# keeps falling (233 auto at 1px-6px, 232 at 7px-15px), because a handful of
# crossings clear at an alternative costing a few px more than the cheapest
# ones, not at exactly 0; raising the penalty just far enough catches those
# too, still inside the flat band. Past 15px, mean length ratio moves first,
# at 16px; bend-optimal share follows at 26px, not 30px as a sampled rather
# than exhaustive pass through this same sweep once claimed here; length
# moves *again* at 31px, inside what that pass called one flat 30px-40px
# row. Both were genuine errors in reading the sweep, not stale numbers, and
# both are why this pass reruns every integer rather than a sample of them.
# 10 sits inside 7px-15px, the sub-range that clears every crossing this
# corpus has a same- or near-cost alternative for, with margin either side
# of it rather than pinned to where the band happens to end.
#
# "No length regression" above describes this corpus, not a property of the
# design -- nothing here stops a *different* sheet from buying length with
# this charge. Two same-bend routes, one 60px and crossing something, one
# 69px and clear: uncharged the 60px one wins; charged 10px it costs 70 and
# the 69px one wins instead, spending 9px of length this corpus's own 21
# examples do not happen to price an alternative into. The bound is
# CROSSING_PENALTY itself -- a route can never be bought more length than
# one penalty's worth, and never a bend at all (see the goal-arrival
# comment below) -- not zero.
#
# Rerun in full, not spot-checked, once ``crossings_along`` started pricing
# a crossing strictly inside a graph edge or a fallback L's own leg (not
# only at a node) and ``DefaultRouter.route()`` started recording every
# already-routed stream's *previewed*, post-separation position instead of
# its raw one (see ``crossings_along``'s docstring and ``settle`` in
# ``pandid/routing/__init__.py``) -- either could in principle have moved
# every number in the table above, since both change what counts as a
# crossing. Neither did: the table is bit-for-bit what it was before both
# fixes, on this corpus, at every one of the 41 penalties checked.
CROSSING_PENALTY = 10.0

# A candidate move's direction, reduced to the axis a crossing is measured
# on: two segments cross only when they run on different axes. Kept local
# rather than importing ``visibility.TRAVEL`` (which carries a sign this has
# no use for) or ``route_quality.py``'s equivalent (a script, not a package
# import).
_AXIS: Dict[str, Axis] = {"E": "h", "W": "h", "N": "v", "S": "v"}


@dataclass
class CrossingIndex:
    """Every already-drawn stream's segments, indexed for a strict-interior
    crossing test -- see ``committed_segments`` for what goes in and the
    crossing check in ``find_path`` for what comes out.

    Indexed by *span*, not by the individual graph nodes a path happens to
    visit, because two of the segments a committed path draws are not built
    from lane hops at all: the fixed anchor->projection stub at each end, and
    the shared mid-point ``share_escape_room`` gives two nozzles too close
    for both stand-offs. Both can run 20px or more past lane coordinates
    nothing was ever asked to stop at, so a later stream turning onto one of
    those interior lanes -- a couple of lanes over from wherever the earlier
    search happened to bend -- would cross it unnoticed if only the nodes
    visited were on record. #425's ``17_stirred_reactor_train`` is exactly
    that: two lanes 2px apart, one crossing a header's stub, the other not,
    and a node-keyed index found only the one it already knew the name of.

    ``h[y]`` is every horizontal segment's ``(x_lo, x_hi)`` at that y;
    ``v[x]`` the same for vertical segments at that x. A later stream
    travelling through node ``(x, y)`` on axis *a* crosses one of these if
    the *other* axis's list at that fixed coordinate holds a span with the
    node's coordinate strictly inside it.
    """

    h: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)
    v: Dict[float, List[Tuple[float, float]]] = field(default_factory=dict)

    # A cached, sorted view of ``h``/``v``'s own keys, so ``crossings_along``
    # can *bisect* to the handful of tracks a query's range actually covers
    # instead of walking every track this index has ever been given -- that
    # scan now runs once per candidate edge, not once per node, on every
    # search on the sheet (#483 round 6: +56% on a real corpus sheet, 154x
    # on a synthetic worst case of a long path against 50,000 tracks).
    #
    # Not maintained incrementally on ``record`` -- a test (and there are
    # several) builds one of these by poking ``h``/``v`` directly, which a
    # parallel sorted list kept up to date only inside ``record`` would
    # silently fall out of sync with. Cached and rebuilt instead, keyed on
    # ``len(h)``/``len(v)``: adding a *new* track changes that count, so the
    # cache is known stale and re-sorted; appending another span onto a
    # track already keyed (``record``'s common case for a straight run
    # crossing an existing one, or a test extending ``h[y]`` in place) does
    # not change the key set at all, so the cached order is still exactly
    # right and paying to re-sort would buy nothing. One index served
    # through one search sees its key count settle after the handful of
    # ``record`` calls building it and then queried thousands of times, so
    # this pays the sort once per sheet's worth of growth, not once per
    # query.
    _h_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)
    _v_sorted: Optional[Tuple[int, List[float]]] = field(default=None, repr=False, compare=False)

    def record(self, path: List[Tuple[float, float]]) -> None:
        """Add one committed, drawn path's segments to the index."""
        for axis, fixed, lo, hi in committed_segments(path):
            (self.h if axis == "h" else self.v).setdefault(fixed, []).append((lo, hi))

    def _sorted_keys(self, axis: Axis) -> List[float]:
        d = self.h if axis == "h" else self.v
        cached = self._h_sorted if axis == "h" else self._v_sorted
        if cached is not None and cached[0] == len(d):
            return cached[1]
        keys = sorted(d)
        if axis == "h":
            self._h_sorted = (len(d), keys)
        else:
            self._v_sorted = (len(d), keys)
        return keys

    def crosses(self, node: Tuple[float, float], axis: Axis) -> int:
        """How many already-recorded segments does a run through *node*,
        continuing straight on *axis*, properly cross?

        A count, not a bool: two different earlier streams can each cross
        the same point (each drew its own span, and both happen to cover
        it), and a route through there crosses both of them, not one --
        ``0`` stays falsy for a caller that only asks whether it crossed
        anything at all, but a caller pricing the crossing has to multiply
        by this, not just test it, or a second stream crossed for free
        after the first already did.

        ``axis`` is typed as ``Axis`` so a caller passing anything else is a
        type-checker error, but every caller here builds it from a plain
        ``str`` first (``_AXIS[cur_dir]``, a test literal), so a value that
        slipped past that -- a typo, a stray compass letter -- is checked
        again at runtime rather than silently answered as one of the two
        real axes it happens to look most like.
        """
        if axis not in ("h", "v"):
            raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")
        x, y = node
        if axis == "v":
            return sum(1 for lo, hi in self.h.get(y, ()) if lo < x < hi)
        return sum(1 for lo, hi in self.v.get(x, ()) if lo < y < hi)

    def crossings_along(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> int:
        """How many already-recorded segments does the *whole* straight run
        from *p1* to *p2* properly cross?

        ``crosses`` answers this for one node a search is actually visiting;
        a fallback L is not built from graph lanes at all -- its corner sits
        wherever the two escape stand-offs happen to combine -- so there is
        no node-by-node walk to check it with. This scans every span on the
        other axis instead, over the run's whole coordinate range, the way
        ``route_quality.py``'s own ``crossing_point`` reads the drawn
        geometry rather than the search that produced it -- but only the
        tracks strictly inside that range, found by bisecting ``_sorted
        _keys`` rather than testing every track this index has ever been
        given: ``find_path`` calls this once per candidate edge now, not
        once per node, so a scan proportional to the *whole* index rather
        than to what a query's own range actually covers is a cost this
        search pays on every edge of every route on the sheet, not once.

        ``0`` for a diagonal or zero-length pair: neither is a segment this
        index's straight-line spans can properly cross.
        """
        if p1[1] == p2[1] and p1[0] != p2[0]:  # horizontal
            y = p1[1]
            xlo, xhi = sorted((p1[0], p2[0]))
            keys = self._sorted_keys("v")
            i0, i1 = bisect.bisect_right(keys, xlo), bisect.bisect_left(keys, xhi)
            return sum(1 for x in keys[i0:i1] for lo, hi in self.v[x] if lo < y < hi)
        if p1[0] == p2[0] and p1[1] != p2[1]:  # vertical
            x = p1[0]
            ylo, yhi = sorted((p1[1], p2[1]))
            keys = self._sorted_keys("h")
            i0, i1 = bisect.bisect_right(keys, ylo), bisect.bisect_left(keys, yhi)
            return sum(1 for y in keys[i0:i1] for lo, hi in self.h[y] if lo < x < hi)
        return 0


def committed_segments(path: List[Tuple[float, float]]) -> List[Tuple[Axis, float, float, float]]:
    """``(axis, fixed, lo, hi)`` for every merged straight run in a
    *committed* path -- one interval per continuous line, not one entry per
    atomic graph hop or per waypoint, so a stub or a shared-midpoint jump
    that never touched most of the lanes it passes over is still recorded
    over its whole length. See :class:`CrossingIndex` for why that
    granularity is the one a later stream's crossing check needs.

    A repeated point -- an escape stub ``share_escape_room`` shrank to
    nothing, say -- carries no direction of its own and is dropped before
    anything else runs, so two same-axis segments meeting at one do not read
    as two separate, merely-touching spans: the drawn line is one continuous
    run either side of a duplicate waypoint, and a crossing exactly at the
    join is still a crossing.

    Raises ``ValueError`` on a genuinely diagonal pair (both coordinates
    differ) rather than guessing an axis from whichever one the ``if``
    happened to test first -- a router-drawn path is orthogonal by
    construction (``test_routes_remain_orthogonal_and_clear_of_equipment``),
    so a diagonal pair reaching here is a caller bug worth failing loudly on,
    not geometry worth misreading.
    """
    def axis_of(p: Tuple[float, float], q: Tuple[float, float]) -> Optional[Axis]:
        dx, dy = p[0] != q[0], p[1] != q[1]
        if dx and dy:
            raise ValueError(f"committed_segments: {p!r} -> {q!r} is diagonal, not orthogonal")
        if dx:
            return "h"
        if dy:
            return "v"
        return None  # p == q: no direction, no segment

    dedup = [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]

    segs = []
    n = len(dedup)
    i = 0
    while i < n - 1:
        ax = axis_of(dedup[i], dedup[i + 1])
        assert ax is not None  # dedup guarantees no two consecutive points are equal
        j = i + 1
        while j < n - 1 and axis_of(dedup[j], dedup[j + 1]) == ax:
            j += 1
        p0, p1 = dedup[i], dedup[j]
        idx = 0 if ax == "h" else 1
        fixed = p0[1 - idx]
        lo, hi = (p0[idx], p1[idx]) if p0[idx] <= p1[idx] else (p1[idx], p0[idx])
        segs.append((ax, fixed, lo, hi))
        i = j
    return segs

# What the search is allowed to spend before it is called a bug rather than a
# hard sheet. A* terminates because ``visited`` settles each state at most
# once, and that argument holds only while the costs compare: a single NaN
# coordinate makes ``visited[state] <= g`` false for ever, so every state
# re-expands and the queue's paths grow until the process dies. A ceiling makes
# termination unconditional rather than conditional on the numbers.
#
# The budget is the larger of a flat floor and a per-node allowance, because
# the two bind at opposite ends. A small graph is cheap to re-cross, so its
# cost per node is high -- the worst of 14,107 real searches across the suite
# and the examples expands 9.5 states per node, on a graph of 219. A large
# graph is never crossed more than a fraction of the way: that same corpus
# never expands more than 2,411 states in total, on a graph of 3,082. So the
# floor carries the small graphs and the allowance carries the large, and each
# leaves about twenty times the worst measured demand.
MAX_EXPANSIONS_PER_NODE = 16
MIN_EXPANSION_BUDGET = 50_000

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}

def get_dir(p1: Tuple[float, float], p2: Tuple[float, float]) -> Optional[str]:
    if p1[0] < p2[0]:
        return "E"
    if p1[0] > p2[0]:
        return "W"
    if p1[1] < p2[1]:
        return "S"
    if p1[1] > p2[1]:
        return "N"
    return None

def heuristic(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    h = dx + dy
    # Add a penalty if a bend will be required to reach the goal
    if dx > 0 and dy > 0:
        h += BEND_PENALTY
    return h

def find_path(
    graph: VisibilityGraph,
    start: Tuple[float, float],
    goal: Tuple[float, float],
    start_dir: Optional[str] = None,
    goal_dir: Optional[str] = None,
    edge_penalties: Optional[Dict[Tuple[Tuple[float, float], Tuple[float, float]], float]] = None,
    is_recycle: bool = False,
    crossing_index: Optional[CrossingIndex] = None,
) -> List[Tuple[float, float]]:
    """Find the shortest orthogonal path on the visibility graph using A*.

    start_dir: The OUTWARD normal direction of the source port. ``start`` is already
        the port's projected escape node, so this only seeds the travel direction;
        it is not re-imposed on the first step.
    goal_dir: The OUTWARD normal direction of the destination port. The path may
        arrive head-on or from either side; only arriving from *behind* -- that
        is, travelling along the outward normal, which means coming through the
        unit body -- is banned. See the goal-approach comment in the loop.

    crossing_index: every *earlier* stream's drawn segments in this sheet's
        routing order -- see ``DefaultRouter.route()``, the only caller that
        builds one, and :class:`CrossingIndex` for the index itself. A node
        this path also runs straight through, on the other axis from one of
        those segments, is a drawn crossing, and so is any point strictly
        *between* two nodes an edge connects directly (``crossings_along``,
        below) -- an earlier stream is under no obligation to land on a lane
        at all, so a crossing with one can sit anywhere a graph edge happens
        to span, not only at its ends. Both are charged ``CROSSING_PENALTY``
        once per earlier segment crossed there, not once regardless of how
        many (``CrossingIndex.crosses`` and ``crossings_along`` both count).
        Earlier only: a run can cross a line already on the sheet, not one
        that has yet to be routed, so the charge sees exactly what a
        draughtsman working stream-by-stream would have seen too -- and
        stays reproducible run to run, since it is built by walking
        ``fs.streams``, an ordered list, rather than by iterating a
        hash-ordered container whose order ``PYTHONHASHSEED`` could change.

        Still scoped, in one way that is not fixable from inside this
        function: the two stub segments the *caller* draws outside it,
        anchor->``start`` at one end and ``goal``->anchor at the other, are
        recorded into ``crossing_index`` for later streams (``committed
        _segments`` walks the whole committed path, stubs included) but
        never themselves checked against it, because neither is a choice
        this search makes -- there is exactly one way to draw a fixed stub,
        so it cannot change which route wins, but a crossing landing purely
        inside one is still invisible to every search that runs after it.

    The heuristic is not weighted for recycle streams. Scaling an admissible
    heuristic cannot change which path A* returns, only how greedily it looks
    for it; a genuine preference for the recycle lanes has to be a change to
    ``cost``, as the off-lane charge below is.

    Raises ``ValueError`` on a non-finite endpoint, and ``RuntimeError`` on a
    search that will not settle within its expansion budget. Both beat the
    alternative, which is a render that never returns at all.
    """
    for role, point in (("start", start), ("goal", goal)):
        if not (math.isfinite(point[0]) and math.isfinite(point[1])):
            raise ValueError(
                f"cannot route from a non-finite {role} {point!r}: every "
                f"comparison against it is false, so the search would settle "
                f"no state and never return."
            )

    if edge_penalties is None:
        edge_penalties = {}

    budget = max(MIN_EXPANSION_BUDGET, MAX_EXPANSIONS_PER_NODE * len(graph.nodes))
    expansions = 0

    # Priority queue: (f_score, g_score, counter, current_node, current_dir, path)
    # The counter breaks ties so equal (f, g) entries never fall through to
    # comparing the node tuples themselves.
    queue: list[tuple[float, float, int, tuple[float, float], Optional[str], list[tuple[float, float]]]] = []
    heapq.heappush(queue, (0, 0, 0, start, start_dir, [start]))
    
    # State key: ((x, y), dir)
    visited: Dict[Tuple[Tuple[float, float], Optional[str]], float] = {}
    
    # Count for tie-breaking
    counter = 1
    
    while queue:
        expansions += 1
        if expansions > budget:
            raise RuntimeError(
                f"routing {start} -> {goal} expanded {expansions} states over "
                f"{len(graph.nodes)} graph nodes, past the {budget} this graph "
                f"is allowed, without settling. The search is not converging: "
                f"suspect a coordinate that does not compare, or a cost that "
                f"keeps falling."
            )
        f, g, _, current, cur_dir, path = heapq.heappop(queue)

        if current == goal:
            return path
            
        state_key = (current, cur_dir)
        if state_key in visited and visited[state_key] <= g:
            continue
        visited[state_key] = g
        
        for neighbor in graph.edges.get(current, []):
            ndir = get_dir(current, neighbor)
            
            # 1. Never reverse along the axis just travelled. A reversal
            #    retraces the segment it just drew, and the cost model charges
            #    it a single bend, cheaper than the honest two-bend detour
            #    around the obstacle that provoked it, so without this ban the
            #    search prefers lines drawn over themselves.
            #
            #    ``start`` is the port's *projected* escape node and the caller
            #    draws the anchor->projection stub itself, so the square exit is
            #    already guaranteed. Seeding ``cur_dir`` with ``start_dir`` and
            #    banning the reverse is therefore the whole port constraint:
            #    the path may turn immediately, but never back over the stub.
            #    Re-imposing ``start_dir`` on the first step instead would buy an
            #    arbitrary extra hop outward before any turn was allowed.
            if cur_dir and ndir == OPPOSITE[cur_dir]:
                continue

            # 2. Goal approach. The router appends a perpendicular goal_proj->port
            #    segment, so the port is always entered squarely however
            #    goal_proj is reached. Allow reaching it head-on OR from either
            #    side; only forbid arriving from *behind* (heading along the
            #    outward normal = coming through the unit body). Requiring a
            #    strictly head-on arrival forces tall detours up to the sheet
            #    edge to line up above a top/bottom port.
            if neighbor == goal and goal_dir:
                if ndir == goal_dir:
                    continue
                    
            dist = abs(neighbor[0] - current[0]) + abs(neighbor[1] - current[1])
            cost = g + dist + edge_penalties.get((current, neighbor), 0.0)

            # A graph edge is one straight hop, but not a short one: the grid
            # skips lane coordinates an obstacle blocks, not the ones past it,
            # so the edge joining the two nearest *unblocked* lanes can run
            # well past several skipped ones (see ``VisibilityGraph``'s
            # "Horizontal edges" / "Vertical edges" passes). A hand-drawn
            # (``.via()``) route is under no obligation to land on a lane at
            # all -- ``committed_segments`` records it at whatever coordinate
            # its author wrote -- so an earlier stream's crossing can sit
            # anywhere along a skipped stretch like that: strictly between
            # ``current`` and ``neighbor`` but at neither, where every check
            # below (which only ever prices a node this search itself stops
            # at) would never see it. ``crossings_along`` scans the edge's
            # whole span instead of one endpoint. It is open on both ends, so
            # it never re-charges a crossing landing exactly on ``current`` or
            # ``neighbor`` themselves -- the node checks below already do, or
            # will once that node is ``current`` in a later iteration.
            if crossing_index is not None:
                cost += CROSSING_PENALTY * crossing_index.crossings_along(current, neighbor)

            # No edge offered here lies along an obstacle boundary, so there is
            # nothing to charge one for. ``Rect.intersects_segment`` bounds the
            # obstacle inclusively: a run exactly on ``x_min`` or ``y_max``
            # counts as intersecting it, and the visibility graph never builds
            # the edge. Pricing a boundary-hugging lane means letting those
            # edges exist first, which is a change to ``visibility.py``.
            bend_cost = BEND_PENALTY
            if is_recycle:
                bend_cost = BEND_PENALTY / 2.0
                if (current[1] == neighbor[1] and current[1] not in graph.recycle_y
                        and current[1] not in (start[1], goal[1])):
                    # Penalize off-lane horizontal travel, EXCEPT at the stream's own
                    # port elevations: lets a short recycle run straight at its port
                    # height instead of dipping down to the lane and back.
                    cost += dist * 10.0
            else:
                # Recycle lanes are reserved for recycle streams. Forbid forward
                # streams from travelling along them so up-and-over routes hug the
                # equipment instead of spiking to the sheet edge (looks "cut off").
                if current[1] == neighbor[1] and current[1] in graph.recycle_y:
                    cost += 100000.0
            
            if cur_dir and ndir != cur_dir:
                cost += bend_cost
            elif cur_dir and crossing_index is not None:
                # Not a bend: this step continues straight through ``current``
                # on its own axis (``_AXIS[cur_dir]``), so ``current`` is
                # strictly interior to this path's run there. If an earlier
                # stream's segment sits on the *other* axis with ``current``
                # strictly interior to *it* too, the two lines properly
                # cross -- a T where one line only touches the other's
                # interior does not count, and cannot: a touch means one of
                # them turns at this node, which takes the ``if`` above
                # instead of this ``elif``.
                #
                # Checked against ``current``, not ``neighbor``: this path's
                # own strict-interior claim on the node is only settled once
                # both its in- and out-edges are known, never on the step
                # that only arrives at it not yet knowing whether it will
                # turn there.
                #
                # Multiplied by the count, not just tested: two different
                # earlier streams can each cross this same node, and a route
                # through it crosses both, not one -- ``crosses`` counts
                # rather than answers yes/no for exactly this.
                cost += CROSSING_PENALTY * crossing_index.crosses(current, _AXIS[cur_dir])

            # Goal's own pass-through, independent of the check above and
            # never covered by it: this search returns the instant it pops a
            # state at ``goal`` (the ``if current == goal`` at the top of the
            # loop), so ``goal`` is never itself *expanded* -- the ordinary
            # per-node check only prices a node when the search considers a
            # move leading *out* of it, which a state it terminates on never
            # gets. The caller always draws one more fixed segment past it,
            # ``goal`` (here, ``goal_proj``) to the port, straight along
            # ``OPPOSITE[goal_dir]``, and what happens at that join depends
            # on whether *this* move already arrives along that direction:
            #
            # - if it does, nothing between the two segments bends, and
            #   ``goal`` is a strict-interior point of the drawn line exactly
            #   like any other, so it is priced against ``crossing_index``
            #   the same way ``current`` is above;
            # - if it does not -- an allowed side approach, see the
            #   goal-approach comment above -- the join *is* a bend, and one
            #   this search has never itself drawn or priced, because it is
            #   part of the fixed stub the caller adds after this function
            #   returns. Left unpriced, this hands the search a bend no
            #   crossing should ever be worth buying, exactly the case a
            #   registered crossing on the straight arrival's own axis
            #   creates: it makes the straight approach look more expensive
            #   than a side one charged nothing for a bend it draws just as
            #   really. So the side approach is charged that bend's cost
            #   here, but *only* when a straight arrival at this same goal
            #   would itself have been crossing-charged -- checked
            #   independently of which one this move actually is, since
            #   ``crossing_index.crosses`` reads only the recorded geometry,
            #   not this search's own path. Elsewhere -- the overwhelming
            #   majority of goal arrivals, which cross nothing -- a side
            #   approach costs exactly what it always did, because there is
            #   no crossing charge here for its blind spot to make cheaper
            #   than a bend.
            #
            # Gated on ``CROSSING_PENALTY > 0`` as well as ``crossing_index
            # is not None``: this whole block, including the bend charge
            # above, exists only to keep the crossing charge honest, so a
            # penalty of zero -- the sensitivity sweep's own baseline --
            # must switch every part of it off, not just the charge itself.
            if neighbor == goal and goal_dir and crossing_index is not None and CROSSING_PENALTY > 0:
                if ndir is not None and ndir == OPPOSITE[goal_dir]:
                    # Multiplied by the count, same reasoning as the
                    # ``current`` check above: crossing two earlier streams
                    # at ``goal`` is not the same as crossing one.
                    cost += CROSSING_PENALTY * crossing_index.crosses(goal, _AXIS[ndir])
                elif crossing_index.crosses(goal, _AXIS[OPPOSITE[goal_dir]]):
                    # Not multiplied: however many lines the straight
                    # arrival would have crossed here, the side approach
                    # still draws exactly one bend, never more than one.
                    cost += bend_cost

            h = heuristic(neighbor, goal)

            counter += 1
            heapq.heappush(queue, (cost + h, cost, counter, neighbor, ndir, path + [neighbor]))

    return []
