"""Stage 1: where every process unit sits on the grid.

Two runs of :func:`pandid.layout.solver.relax`, one per axis, over the
claims :mod:`pandid.layout.claims` reads off the equipment. Each run
answers with a *fractional* position -- the compromise between every
claim touching that unit -- and this module turns the two into a whole
column and a whole row.

Preference, then legality
-------------------------
The fit states where each unit would rather be, and it is free to say
"between": a pair of claims of ``+1`` and ``-1`` average to ``0``, which
as a preference is "the same row would suit both of you" and as a
drawing is one box on top of another. So the fit supplies preference and
:func:`_separate` supplies legality, in that order and never the other
way about. Separation walks each column top to bottom in the order the
fit asked for and hands out distinct rows, so the arrangement the claims
argued their way to survives being made legal.

Then crossing reduction, and it is **not** what the fit computes
------------------------------------------------------------------
The fit puts every unit at the weighted average of every claim touching
it, which looks like what a barycentre sweep converges to and is a
different quantity: least squares minimises *displacement*, and a
crossing is nowhere in that objective. Where two units in one column
have no claim about each other -- which on a sheet of valve stations is
most pairs -- the fit puts them in whichever order the arithmetic came
out, and swapping them costs it nothing and the drawing plenty. Deleting
the sweep on the grounds that the fit subsumed it cost the corpus 93
crossings; :func:`_unlace` puts it back, after the solve and as a
permutation within each column, so that the two passes answer the two
different questions rather than one pretending to answer both.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pandid.layout import claims as claims_mod
from pandid.layout import solver
from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def assign_positions(fs: "Flowsheet") -> None:
    """Fill in ``_slot.col`` and ``_slot.row`` for every process unit."""
    from pandid.layout.stages import process_streams, process_units

    units = process_units(fs)
    if not units:
        return
    at = {u: i for i, u in enumerate(units)}
    claims = claims_mod.read(process_streams(fs))

    pulls = {step: [(at[c.author], at[c.subject], c.confidence, float(getattr(c, step)))
                    for c in claims] for step in ("eastward", "southward")}
    # One graph, two axes: the components are the same set either way,
    # since a claim that weighs nothing on one axis weighs nothing on
    # both. Found once, so the column run and the row run cannot come to
    # different conclusions about what is joined to what.
    groups = solver.components(len(units), pulls["eastward"])

    eastward = _fit(units, at, pulls["eastward"], groups, "col")
    southward = _band(units, at, groups, _fit(units, at, pulls["southward"], groups, "row"))

    stiffness = _stiffness(units, at, claims)
    columns = _spread(units, at, claims, eastward)
    rows = _unlace(units, claims, columns,
                   _separate(units, at, columns, southward, stiffness))
    for u in units:
        s = slot(u)
        s.col, s.row = columns[u], rows[u]
    _rebase(units, "col")
    _rebase(units, "row")


def _fit(units: list["Unit"], at: dict["Unit", int], pulls: list[solver.Pull],
         groups: list[list[int]], axis: str) -> list[float]:
    """One axis, fitted: the pins held fast and everything else settled.

    ``axis`` names the ``_Slot`` field the author's pin arrives in, and
    is the only thing that differs between the column run and the row
    run beyond the pulls themselves.
    """
    fixed = {at[u]: float(pin) for u in units
             if (pin := getattr(slot(u), axis)) is not None}
    for group in groups:
        if not any(node in fixed for node in group):
            fixed[_anchor(units, group)] = 0.0
    return solver.relax(len(units), pulls, fixed)


def _band(units: list["Unit"], at: dict["Unit", int], groups: list[list[int]],
          southward: list[float]) -> list[float]:
    """Give each piece of a sheet in several pieces a band of its own.

    Every component with nothing pinned in it is anchored at zero, so
    two trains that share no run are fitted on top of each other -- and
    then the row separation, which works a column at a time, pushes them
    apart in the columns they both use and leaves them alone in the
    columns only one of them reaches. A three-block chain beside an
    unrelated pair came out with a *kink* in it: the two blocks sharing
    a column with the pair were lifted a row and the third, alone in its
    column, was not.

    So the pieces are stacked here instead, in the order the flowsheet
    states them, each below the last. What the separation is then left
    with is the collisions inside one train, which is what it is for.

    A component holding a pin is left exactly where the fit put it: the
    author has said which band it goes in. It still claims the paper it
    covers, so that a free component after it is stacked clear rather
    than into it.
    """
    if len(groups) < 2:
        return southward
    out = list(southward)
    cursor = 0.0
    for group in groups:
        lo = min(southward[node] for node in group)
        hi = max(southward[node] for node in group)
        if any(slot(units[node]).row is not None for node in group):
            cursor = max(cursor, hi + 1.0)
            continue
        for node in group:
            out[node] = southward[node] - lo + cursor
        cursor += hi - lo + 1.0
    return out


def _anchor(units: list["Unit"], group: list[int]) -> int:
    """Which unit of an unpinned component is nailed to the origin.

    Claims are all relative, so a component nothing is pinned in is
    determined only up to a shared translation and something has to be
    chosen. The first :class:`~pandid.units.Feed` in it, because a
    drawing is read from where the material comes in and that is the
    box a reader's eye starts at; failing that the component's lowest
    member in the order the flowsheet holds its units, which is stated
    by the author and the same on every run.

    A sheet in several pieces gets one anchor per piece, so a component
    joined to nothing still lands on the grid instead of taking the
    matrix apart.
    """
    from pandid.units import Feed

    for node in group:
        if isinstance(units[node], Feed):
            return node
    return group[0]


def _stiffness(units: list["Unit"], at: dict["Unit", int],
               claims: list[claims_mod.Claim]) -> list[float]:
    """How hard each unit is to move: every weight touching it, summed.

    This is the diagonal of the fit's own matrix, and it is what
    :func:`_separate` spends when it has to move somebody. A unit
    wired into half the sheet earns its stiffness by connection count
    alone, which is emergent rather than declared.

    Floored at :data:`~pandid.layout.claims.LINE` so a unit nothing
    claims anything about still has a weight to be weighed by.
    """
    out = [0.0] * len(units)
    for claim in claims:
        if claim.author is claim.subject:
            continue
        out[at[claim.author]] += claim.confidence
        out[at[claim.subject]] += claim.confidence
    return [max(w, claims_mod.LINE) for w in out]


def _spread(units: list["Unit"], at: dict["Unit", int],
            claims: list[claims_mod.Claim], eastward: list[float]) -> dict["Unit", int]:
    """A whole column each, for a run of units the fit squeezed into one.

    The fit is a compromise and a compromise can be *zero*: a valve
    station between a column and its condenser is eight fittings whose
    only claims are the pipe's own, weighed at
    :data:`~pandid.layout.claims.LINE`, and the two ends of it are held
    a single column apart by claims weighed at 8. Least squares crushes
    the eight into that one column -- 11_ethanol_pid came out 25 rows
    deep and folded to a quarter of full size -- and no weighting fixes
    it, because two nodes held one column apart with a chain between
    them is a statement the fit can only compromise on.

    What is legal here is sharper than "no two boxes in one place". A
    run that states a step **along** the sheet has to be given one: with
    both ends in the same column the run leaves an east nozzle, turns,
    and comes back west to reach a west nozzle beside it, which is the
    disagreement between geometry and nozzle this whole engine exists to
    end. So a pair the fit collapsed is pushed apart, in the order the
    fit put them and by :func:`_pool_adjacent_violators`, exactly as a
    column of boxes is.

    Only where a claim asked for the step, and only where none asked for
    none. A relief valve over the vessel it protects is in one column
    because the vessel *said* so -- ``PLACES["relief"] == "N"``, a step
    of zero along -- and nothing here moves it.

    Which **side** of the gap each end takes is the fit's answer and not
    the claim's; see the comment on the loop. That is worth 14 crossings
    on 20_molecular_sieve_dryer, where two identical adsorber beds are
    read differently -- one of them has the torn edge of the
    regeneration loop on it -- and the fit still has them side by side
    while the claims, read for their direction, do not.

    Each unit takes a column one past the furthest of the neighbours
    already placed that stated it comes after them -- a longest path,
    over the handful of units one column holds. Spacing them evenly
    instead is what a valve station shows to be wrong: its bypass runs
    *parallel* to the isolations it is tapped outside of, so it wants
    the same columns they do and one row down, and spread evenly the
    eleven of them walk eleven columns diagonally across the sheet.
    """
    columns = {u: solver.discretise(eastward[at[u]]) for u in units}
    after: dict["Unit", list["Unit"]] = defaultdict(list)
    level: set[tuple[int, int]] = set()
    fitted = {u: (round(eastward[at[u]], solver.PLACES), at[u]) for u in units}
    for claim in claims:
        if claim.eastward == 0:
            level.add((at[claim.author], at[claim.subject]))
            level.add((at[claim.subject], at[claim.author]))
            continue
        # Which way round is the *fit's* answer and never the claim's.
        # The claim is read for one thing only -- that these two are a
        # column apart -- because that is the part of it the fit cannot
        # honour and this pass exists to restore. Read for its direction
        # as well and a claim the fit weighed and turned down would be
        # enforced here anyway, at full strength, by a pass that weighed
        # nothing: a stripper's ``boilup_in: SE`` and the blower's own
        # ``discharge: E`` would push each other apart a column at a
        # time and end three columns from where either wanted. Taking
        # the side from the fit and the gap from the claim leaves the
        # arrangement the solve settled on and only stretches it.
        west, east = claim.author, claim.subject
        if fitted[west] > fitted[east]:
            west, east = east, west
        after[east].append(west)
    if not after:
        return columns

    # West to east in the order the *fit* put them, each unit taking a
    # column past every neighbour already settled that it claims to come
    # after. Two things fall out of walking that order and no other.
    #
    # It **cascades**: pushing the valve on a column's overhead off the
    # column pushes the tee after it off the valve, and so on down the
    # manifold. Measuring each unit against the fit's own answer for its
    # neighbour instead stops at the first push, and left
    # 05_reactor_recycle with its compressor and its reactor stacked in
    # one column because the compressor had been moved into the
    # reactor's.
    #
    # And the order is the same one the edges above were oriented by, so
    # every push is forward and one walk settles the lot: this is a
    # longest path over a graph that is acyclic by construction rather
    # than one somebody had to break the cycles in.
    order = sorted(units, key=lambda v: fitted[v])
    settled: set["Unit"] = set()
    for u in order:
        settled.add(u)
        if slot(u).col is not None:
            continue  # the author's answer, and not this pass's business
        behind = [columns[v] for v in after[u]
                  if v in settled and v is not u and (at[u], at[v]) not in level]
        columns[u] = max([columns[u], *(c + 1 for c in behind)])
    return columns


def _by_key(units: list["Unit"], key: dict["Unit", int]) -> dict[int, list["Unit"]]:
    """The units grouped by ``key``, each group in flowsheet order."""
    out: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        out[key[u]].append(u)
    return out


def _separate(units: list["Unit"], at: dict["Unit", int], columns: dict["Unit", int],
              southward: list[float], stiffness: list[float]) -> dict["Unit", int]:
    """One row per unit, distinct within a column.

    Two units in one column may not be in one row, and the fit has no
    way to know that: it is a statement about boxes having *size*, and
    the claims are not about size. So this is the same objective solved
    a second time with that one constraint added --

    .. code-block:: text

        minimise sum of  stiffness * (row - fitted) ** 2
        subject to       row[i + 1] >= row[i] + 1

    -- over the units of one column, taken in fitted order. Substituting
    ``s[i] = row[i] - i`` turns the constraint into "``s`` does not
    decrease", which is isotonic regression, and
    :func:`_pool_adjacent_violators` is its standard linear-time
    solution.

    Solving rather than pushing matters, and the case that shows it is
    two feeds over one block's roof. Both fit to half a row above the
    block, which is one row once separated, and pushing the loser *down*
    puts it on the block and the block a row below its own train. The
    fit says instead that the block is eight times the stiffer -- it has
    eight claims on it and the feeds two each -- so what gives is the
    feeds, which go to two rows and one row above the roof they land on.
    That is the drawing, and nobody had to write a rule for it.

    A pinned row is exempt and exact. It is reserved before the walk and
    a free unit steps over it, down, so the fitted order survives being
    made legal.

    Where the fit **ties** it has nothing to say, and the columns are
    walked west to east so that what has already been placed can say it
    instead: a tied unit sorts by the average row of the neighbours to
    its west, and only then by the order the flowsheet states. Three
    parallel trains pinned into one column tie exactly, and settling
    each column on the flowsheet's order alone lands the first train's
    source opposite the last one's sink -- three runs crossing where the
    fit had no preference at all. This is a **tie-break** and never
    anything more: it cannot move a unit the fit placed.
    """
    by_column = _by_key(units, columns)
    out: dict["Unit", int] = {}
    settled: dict["Unit", int] = {}
    for column in sorted(by_column):
        members = _tied_first_nearest(sorted(by_column[column], key=lambda u: (
            round(southward[at[u]], solver.PLACES), _westward(u, settled), at[u])),
            lambda u: (round(southward[at[u]], solver.PLACES), _westward(u, settled)))
        taken = {row for u in members if (row := slot(u).row) is not None}
        for u in members:
            if (pinned := slot(u).row) is not None:
                out[u] = pinned
        free = [u for u in members if slot(u).row is None]
        wanted = _pool_adjacent_violators([southward[at[u]] for u in free],
                                          [stiffness[at[u]] for u in free])
        cursor: int | None = None
        for u, row in zip(free, wanted):
            if cursor is not None and row < cursor:
                row = cursor
            while row in taken:
                row += 1
            out[u] = row
            taken.add(row)
            cursor = row + 1
        for u in members:
            settled[u] = out[u]
    return out


def _tied_first_nearest(members: list["Unit"], key) -> list["Unit"]:
    """Reverse each tied run but the last, so the first stated lands nearest.

    Two feeds onto one roof fit to the same fraction of a row above the
    block and the claims say nothing about which of them is higher. The
    one stated **first** goes nearest the block, which is the answer the
    corpus is drawn against and the reason its runs come down in one
    turn: the near feed drops straight onto its own nozzle, and the far
    one clears it because its nozzle is further along the roof. Stated
    the other way round the near feed has to get past the far one's box
    -- a detour east, down and back west, which is three turns to cross
    ten pixels.

    The last tied run in a column is the one *below* whatever anchors
    it, and there the first stated is already the nearest, so it is left
    alone.
    """
    runs: list[list["Unit"]] = []
    for unit in members:
        if runs and key(runs[-1][0]) == key(unit):
            runs[-1].append(unit)
        else:
            runs.append([unit])
    out: list["Unit"] = []
    for index, run in enumerate(runs):
        out.extend(run if index == len(runs) - 1 else reversed(run))
    return out


#: Barycentre passes over the settled grid, down the sheet and back.
#:
#: **Worth nothing on today's corpus, and that is worth writing down
#: rather than leaving as a number nobody re-ran.** Setting this to 0,
#: 1, 2 or 3 leaves the auto-placed corpus at 246 crossings and leaves
#: every unit's ``(col, row)`` on all 21 sheets identical: the
#: :func:`_untangle` loop below runs unconditionally afterwards and now
#: recovers everything the sweeps used to buy. It was worth 34 when it
#: was measured, against a smaller corpus and an engine since replaced.
#: Kept at 2 because a pass that costs nothing and might catch an
#: arrangement the untangler cannot is not worth removing on a corpus
#: this size -- but nobody should tune it expecting movement.
SWEEPS = 2


def _unlace(units: list["Unit"], claims: list[claims_mod.Claim],
            columns: dict["Unit", int],
            rows: dict["Unit", int]) -> dict["Unit", int]:
    """One column's rows, dealt out again so that fewer runs cross.

    The fit answers *where*, and it has no term for a crossing: it
    minimises how far each unit is from where its claims put it, and two
    units in one column whose claims say nothing about each other land
    in whichever order the arithmetic came out. Which of them is drawn
    on top is then decided by nothing -- and on a sheet of valve
    stations that is most of the sheet. So the order within a column is
    settled here instead, by the pass that always settled it: a
    barycentre, each unit to the average row of its neighbours, and then
    a swap of any neighbouring pair that demonstrably unlaces.

    **A permutation and nothing but a permutation.** Each column keeps
    exactly the rows it was given and hands them back out among its own
    members, so the columns the fit chose, the rows the sheet is deep,
    and every collision :func:`_separate` resolved all come through
    untouched. Nothing here can move a unit off an arrangement the
    claims argued for; it can only choose between arrangements they were
    silent about. That is what makes it safe to run *after* the solve
    rather than as a seed before it, which is where the engine this
    replaces had to put it.

    Silence is not all or nothing, which is why the barycentre is
    **blended** rather than run over a free list. Each unit's own row is
    weighed in at ``upright`` -- every confidence that stated a step
    across, summed -- against its neighbours at one apiece. A condenser
    its column places north east carries 8 or more against two or three
    neighbours and does not move; a block valve carries nothing and goes
    wherever its line goes. Freezing the stated units outright instead,
    which is this same rule with the blend rounded to 0 and 1, costs 26
    crossings, 19 of them on 20_molecular_sieve_dryer: a unit that
    states one thing weakly is not a unit with nothing left to say.
    """
    upright: dict["Unit", float] = defaultdict(float)
    for claim in claims:
        if claim.southward != 0 and claim.confidence > 0.0:
            upright[claim.author] += claim.confidence
            upright[claim.subject] += claim.confidence
    pinned = {u for u in units if slot(u).row is not None}
    by_column = _by_key(units, columns)
    order = {u: i for i, u in enumerate(units)}
    out = dict(rows)
    west_east = sorted(by_column)
    for _ in range(SWEEPS):
        for column in west_east:
            _sweep(by_column[column], columns, out, pinned, order, upright)
        for column in reversed(west_east):
            _sweep(by_column[column], columns, out, pinned, order, upright)
    for _ in range(len(west_east)):
        if not any(_untangle(by_column[c], columns, out, pinned)
                   for c in west_east):
            break
    return out


def _sweep(members: list["Unit"], columns: dict["Unit", int], rows: dict["Unit", int],
           pinned: set["Unit"], order: dict["Unit", int],
           upright: dict["Unit", float]) -> None:
    """This column's free members, re-dealt its own rows by barycentre.

    Every run the unit is on counts, in either direction and returns
    included. Reading only the runs *into* it on the way down and only
    the runs *out* of it on the way back is the textbook sweep and is 30
    crossings worse here: a P&ID is not layered, a header reaches ten
    columns, and half of a unit's neighbourhood is a worse estimate of
    where it belongs than all of it. Neighbours in this same column are
    skipped, being what is under discussion.

    A pinned row is not a row to deal: it is left out of both the
    members being ranked and the rows being handed round, so the author
    keeps it exactly and the rest sort themselves around it.
    """
    free = [u for u in members if u not in pinned]
    if not free:
        return
    here = columns[members[0]]
    target: dict["Unit", float] = {}
    for u in free:
        near = [rows[p] for p in _peers(u) if p in columns and columns[p] != here]
        held = upright[u]
        target[u] = ((sum(near) + held * rows[u]) / (len(near) + held)
                     if near else float(rows[u]))
    ranked = sorted(free, key=lambda v: (target[v], rows[v], order[v]))
    for u, row in zip(ranked, sorted(rows[u] for u in free)):
        rows[u] = row


def _untangle(members: list["Unit"], columns: dict["Unit", int],
              rows: dict["Unit", int], pinned: set["Unit"]) -> bool:
    """Swap neighbouring pairs in one column while that unlaces runs.

    A barycentre answers "roughly where", and where two units' averages
    tie it has nothing to say about which goes on top. This counts
    instead: for a pair, how many of the upper one's runs leave it below
    a run of the lower one's, which is how many times the two would
    cross if their neighbours were the next column along. Swapped where
    that count falls and left alone where it does not, so every swap is
    demonstrated rather than guessed.

    Worth nothing while the stated units were frozen -- the barycentre
    had already found every swap that was left to it -- and 20 crossings
    once the blend let them move. The two are one mechanism and neither
    is redundant.
    """
    here = columns[members[0]]
    reach = {u: [rows[p] for p in _peers(u) if p in columns and columns[p] != here]
             for u in members}

    def tangle(above: "Unit", below: "Unit") -> int:
        return sum(1 for a in reach[above] for b in reach[below] if a > b)

    ranked = sorted(members, key=lambda u: rows[u])
    moved = False
    for _ in range(len(ranked)):
        swapped = False
        for i, (a, b) in enumerate(zip(ranked, ranked[1:])):
            if a in pinned or b in pinned or tangle(b, a) >= tangle(a, b):
                continue
            rows[a], rows[b] = rows[b], rows[a]
            ranked[i], ranked[i + 1] = b, a
            swapped = moved = True
        if not swapped:
            break
    return moved


def _westward(unit: "Unit", settled: dict["Unit", int]) -> float:
    """The average row of this unit's already-placed neighbours.

    Only the runs this unit is on, and only the ends of them the walk
    has already settled -- which, since the columns are walked west to
    east, is everything to the west of it. A unit with none sorts last,
    so a column of tied units puts the ones nothing to the west reaches
    below the ones something does rather than interleaving them.
    """
    rows = [settled[peer] for peer in _peers(unit) if peer in settled]
    return sum(rows) / len(rows) if rows else float("inf")


def _peers(unit: "Unit") -> list["Unit"]:
    """Every unit a run joins this one to, in nozzle order."""
    out: list["Unit"] = []
    for port in unit.ports.values():
        stream = port.stream
        if stream is None:
            continue
        peer = stream.dest.owner if stream.source.owner is unit else stream.source.owner
        if peer is not None and peer is not unit:
            out.append(peer)
    return out


def _pool_adjacent_violators(fitted: list[float], weights: list[float]) -> list[int]:
    """Whole rows, one apart and in order, nearest the fitted positions.

    Pool adjacent violators over ``fitted[i] - i``: each run that comes
    out flat is a group of units the constraint has pressed together,
    and its level is their weighted mean. ``O(n)`` -- every unit is
    pushed once and popped at most once.

    The rounding is per *group*, not per unit, and that is load-bearing.
    Two boxes pooled at a level of -0.5 sit at -0.5 and +0.5, which
    rounded one at a time and half away from zero are -1 and +1 with an
    empty row between them. Rounded once, at the group's first member,
    they are -1 and 0 -- adjacent, which is what "one apart" meant.
    """
    #: weight, weight * level, first index, how many
    groups: list[list[float]] = []
    for index, (value, weight) in enumerate(zip(fitted, weights)):
        groups.append([weight, weight * (value - index), float(index), 1.0])
        while len(groups) > 1:
            below, above = groups[-2], groups[-1]
            # Cross-multiplied rather than divided: the weights are
            # positive, so this is the same comparison without a
            # division whose rounding would have to be reasoned about.
            if below[1] * above[0] < above[1] * below[0]:
                break
            below[0] += above[0]
            below[1] += above[1]
            below[3] += above[3]
            groups.pop()

    out: list[int] = []
    for weight, level, first, count in groups:
        base = solver.discretise(level / weight + first)
        out.extend(base + step for step in range(int(count)))
    return out


def _rebase(units: list["Unit"], axis: str) -> None:
    """Slide one axis back so the sheet starts at zero.

    Both directions. A satellite over a unit on the top row lands above
    it, and a run of claims all saying *below* pushes the whole sheet
    down; either way the drawing is the same one and only its numbering
    moved. What a row or a column is counted from has to be the sheet,
    so that a ``frame.row`` a caller reads back means the band it can
    count to and ``pin(col=0)`` means the left edge.

    A sheet carrying a pin on this axis is left where it is. A pin names
    a band or a column, so renumbering under it would move a unit the
    author placed -- and a negative row is a row the coordinate pass
    builds a band for.
    """
    if any(u.pin_ is not None and getattr(u.pin_, axis) is not None for u in units):
        return
    lift = min(getattr(slot(u), axis) or 0 for u in units)
    if lift == 0:
        return
    for u in units:
        setattr(slot(u), axis, (getattr(slot(u), axis) or 0) - lift)
