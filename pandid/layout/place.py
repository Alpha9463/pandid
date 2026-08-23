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

There is no crossing-reduction sweep here any more and none is missing.
A barycentre pass moves a unit to the average row of its neighbours and
repeats until that stops changing anything; the fit puts every unit at
the weighted average of every claim touching it, exactly, in one step.
The sweep was an approximation to the answer this now computes.
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
    rows = _separate(units, at, columns, southward, stiffness)
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
    for claim in claims:
        if claim.eastward > 0:
            after[claim.subject].append(claim.author)
        elif claim.eastward < 0:
            after[claim.author].append(claim.subject)
        else:
            level.add((at[claim.author], at[claim.subject]))
            level.add((at[claim.subject], at[claim.author]))
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
    # And it **cannot enforce a claim the fit turned down**. A unit only
    # looks at neighbours already settled -- which are the ones the fit
    # put west of it -- so a claim that the fit weighed and placed the
    # other way round is never seen from this end. A stripper's
    # ``boilup_in: SE`` puts the blower feeding it south east at
    # confidence 8, over the blower's own ``discharge: E`` at 2; read
    # both ways round here, the two push each other apart a column at a
    # time and end three columns from where either wanted.
    order = sorted(units, key=lambda v: (round(eastward[at[v]], solver.PLACES), at[v]))
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
