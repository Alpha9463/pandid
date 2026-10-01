"""Assign grid columns and rows to process units from their placement claims.

:func:`assign_positions` fits each axis separately with
:func:`pandid.layout.solver.relax`, which gives every unit a fractional
position: the weighted least-squares compromise of the claims touching it.
The passes that follow turn that into whole columns and rows:

1. :func:`_spread` gives each pair a stated column step apart its own
   columns, in the order the fit chose.
2. :func:`_separate` gives units sharing a column distinct rows, as close
   to their fitted rows as stiffness allows.
3. :func:`_unlace` reorders rows within each column to reduce crossings.
   The fit has no crossing term, so units it left unordered are ordered
   here. It only permutes rows a column already holds.

Pinned columns and rows are kept exactly.
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


def assign_positions(fs: "Flowsheet", *, units: list["Unit"] | None = None,
                     claims: list[claims_mod.Claim] | None = None) -> None:
    """Assign grid ranks from process claims.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose process graph supplies the default units and claims.
    units : list[Unit] or None
        Placement nodes, or all process units by default.
    claims : list[Claim] or None
        Claims between those nodes, or all process claims by default.

    Returns
    -------
    None
        The selected unit slots receive column and row ranks.
    """
    from pandid.layout.stages import process_streams, process_units

    if units is None:
        units = process_units(fs)
    if not units:
        return
    at = {u: i for i, u in enumerate(units)}
    if claims is None:
        claims = claims_mod.read(process_streams(fs))

    pulls = {step: [(at[c.author], at[c.subject], c.confidence, float(getattr(c, step)))
                    for c in claims] for step in ("eastward", "southward")}
    # Both axes share one claim graph, so find its components once.
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
    """Fit one axis with pinned positions held fixed.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    at : dict[Unit, int]
        Index of each unit in ``units``.
    pulls : list[Pull]
        Claims on this axis as solver pulls.
    groups : list[list[int]]
        Connected components of the claim graph.
    axis : str
        ``_Slot`` field holding the pin on this axis, ``"col"`` or ``"row"``.

    Returns
    -------
    list[float]
        Fitted position of each unit. An unpinned component is anchored at
        zero through :func:`_anchor`.
    """
    fixed = {at[u]: float(pin) for u in units
             if (pin := getattr(slot(u), axis)) is not None}
    for group in groups:
        if not any(node in fixed for node in group):
            fixed[_anchor(units, group)] = 0.0
    return solver.relax(len(units), pulls, fixed)


def _band(units: list["Unit"], at: dict["Unit", int], groups: list[list[int]],
          southward: list[float]) -> list[float]:
    """Stack disconnected components in separate row bands.

    Every unpinned component is anchored at row zero, so without this
    unrelated trains would overlap and row separation would push them
    apart only in the columns they share. Components are stacked in
    flowsheet order, each below the last. A component holding a pinned row
    stays where the fit put it, and later components stack below it.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    at : dict[Unit, int]
        Index of each unit in ``units``.
    groups : list[list[int]]
        Connected components, in flowsheet order.
    southward : list[float]
        Fitted rows.

    Returns
    -------
    list[float]
        Fitted rows with each free component shifted into its own band.
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
    """Choose the unit that fixes an unpinned component at the origin.

    Claims are relative, so an unpinned component needs one fixed member.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    group : list[int]
        Indices of one component, in flowsheet order.

    Returns
    -------
    int
        Index of the component's first :class:`~pandid.units.Feed`, or of
        its first member when it has none.
    """
    from pandid.units import Feed

    for node in group:
        if isinstance(units[node], Feed):
            return node
    return group[0]


def _stiffness(units: list["Unit"], at: dict["Unit", int],
               claims: list[claims_mod.Claim]) -> list[float]:
    """Return how strongly each unit resists moving.

    Stiffness is the sum of the weights of every claim touching the unit,
    the diagonal of the fit's normal matrix. :func:`_separate` uses it to
    decide which unit gives way.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    at : dict[Unit, int]
        Index of each unit in ``units``.
    claims : list[Claim]
        Claims between the nodes.

    Returns
    -------
    list[float]
        Stiffness per unit, at least :data:`~pandid.layout.claims.LINE`.
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
    """Push apart pairs the fit placed in one column despite a column step.

    Least squares can collapse a chain into one column, for example the
    devices of a valve station held one column apart by strong claims at
    its ends. Each pair joined by a claim with a nonzero eastward step is
    kept at least one column apart. The fit decides which unit is west;
    the claim only says the two need a column between them. Units are
    visited west to east in fitted order and each takes one column past
    every settled unit it follows, so pushes cascade down a chain.

    A pair that also has a claim with no eastward step (such as a relief
    valve stated directly over its vessel) is exempt from the push, as is
    any unit with a pinned column.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    at : dict[Unit, int]
        Index of each unit in ``units``.
    claims : list[Claim]
        Claims between the nodes.
    eastward : list[float]
        Fitted columns.

    Returns
    -------
    dict[Unit, int]
        Whole column for each unit.
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
        # Take the side from the fit, not the claim: enforcing the
        # claim's direction would override claims the fit outweighed.
        west, east = claim.author, claim.subject
        if fitted[west] > fitted[east]:
            west, east = east, west
        after[east].append(west)
    if not after:
        return columns

    # Walk west to east in fitted order. Edges point the same way, so the
    # graph is acyclic and one pass computes the longest path.
    order = sorted(units, key=lambda v: fitted[v])
    settled: set["Unit"] = set()
    for u in order:
        settled.add(u)
        if slot(u).col is not None:
            continue  # pinned column
        behind = [columns[v] for v in after[u]
                  if v in settled and v is not u and (at[u], at[v]) not in level]
        columns[u] = max([columns[u], *(c + 1 for c in behind)])
    return columns


def _by_key(units: list["Unit"], key: dict["Unit", int]) -> dict[int, list["Unit"]]:
    """Group units by a key, keeping flowsheet order within each group.

    Parameters
    ----------
    units : list[Unit]
        Units in flowsheet order.
    key : dict[Unit, int]
        Group key per unit.

    Returns
    -------
    dict[int, list[Unit]]
        Units per key.
    """
    out: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        out[key[u]].append(u)
    return out


def _separate(units: list["Unit"], at: dict["Unit", int], columns: dict["Unit", int],
              southward: list[float], stiffness: list[float]) -> dict["Unit", int]:
    """Give units sharing a column distinct rows near their fitted rows.

    Within one column, taken in fitted order, this solves

    .. code-block:: text

        minimise sum of  stiffness * (row - fitted) ** 2
        subject to       row[i + 1] >= row[i] + 1

    Substituting ``s[i] = row[i] - i`` makes it isotonic regression, solved
    by :func:`_pool_adjacent_violators`. The less stiff unit gives way, so
    two feeds fitted onto one block's roof move up rather than pushing the
    block down.

    Pinned rows are reserved first and free units step down past them.
    Columns are walked west to east; units the fit ties are ordered by the
    average row of their already-placed neighbours, then by flowsheet
    order (see :func:`_tied_first_nearest`).

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    at : dict[Unit, int]
        Index of each unit in ``units``.
    columns : dict[Unit, int]
        Whole column per unit.
    southward : list[float]
        Fitted rows.
    stiffness : list[float]
        Resistance to moving, per unit.

    Returns
    -------
    dict[Unit, int]
        Whole row per unit, distinct within each column.
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
    """Reverse each tied run except the last, so the first stated is nearest.

    Units tied above an anchor are stacked upward, so reversing a tied run
    puts the first stated unit nearest the anchor. Two feeds onto one roof
    then reach their nozzles without crossing. The last run lies below the
    anchor, where flowsheet order already puts the first stated nearest.

    Parameters
    ----------
    members : list[Unit]
        One column's units sorted by fitted row.
    key : Callable[[Unit], object]
        Sort key that defines a tie.

    Returns
    -------
    list[Unit]
        Members in their adjusted order.
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


#: Barycentre passes over the settled grid, west to east and back. Varying
#: it from 0 to 3 changed no drawing in the pins-stripped example corpus
#: (measured September 2026), because :func:`_untangle` runs afterwards.
SWEEPS = 2


def _unlace(units: list["Unit"], claims: list[claims_mod.Claim],
            columns: dict["Unit", int],
            rows: dict["Unit", int]) -> dict["Unit", int]:
    """Reorder rows within each column so that fewer runs cross.

    Each column keeps the set of rows it was given and only permutes them
    among its free members, so the fitted columns and the separation from
    :func:`_separate` are preserved. :data:`SWEEPS` barycentre passes
    (:func:`_sweep`) run first, then :func:`_untangle` swaps adjacent pairs
    until no swap helps.

    The barycentre is blended: a unit's own row is weighted by the sum of
    the confidences of its claims with a north or south step, against its
    neighbours at one each. A unit with a strong vertical claim (a
    condenser over its column) stays; a unit with none follows its line.

    Parameters
    ----------
    units : list[Unit]
        Placement nodes.
    claims : list[Claim]
        Claims between the nodes.
    columns : dict[Unit, int]
        Whole column per unit.
    rows : dict[Unit, int]
        Separated row per unit.

    Returns
    -------
    dict[Unit, int]
        Reordered row per unit.
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
    """Reassign one column's free rows by blended barycentre.

    Every run the unit is on counts, in both directions and returns
    included, because a P&ID is not layered. Neighbours in the same column
    are ignored. Pinned members keep their rows and are excluded from the
    rows handed out.

    Parameters
    ----------
    members : list[Unit]
        Units in the column.
    columns : dict[Unit, int]
        Whole column per unit.
    rows : dict[Unit, int]
        Current rows, updated in place.
    pinned : set[Unit]
        Units with a pinned row.
    order : dict[Unit, int]
        Flowsheet order, used to break ties.
    upright : dict[Unit, float]
        Weight of each unit's own row in the blend.
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
    """Swap adjacent pairs in one column while a swap reduces crossings.

    For a pair, the count of crossings is the number of neighbour rows of
    the upper unit that lie below a neighbour row of the lower unit. A
    pair is swapped only when swapping lowers that count. Pinned units are
    not swapped.

    Parameters
    ----------
    members : list[Unit]
        Units in the column.
    columns : dict[Unit, int]
        Whole column per unit.
    rows : dict[Unit, int]
        Current rows, updated in place.
    pinned : set[Unit]
        Units with a pinned row.

    Returns
    -------
    bool
        Whether any pair was swapped.
    """
    here = columns[members[0]]
    reach = {u: [rows[p] for p in _peers(u) if p in columns and columns[p] != here]
             for u in members}

    def tangle(above: "Unit", below: "Unit") -> int:
        """Count crossings between two units' runs to other columns.

        Parameters
        ----------
        above, below : Unit
            Upper and lower unit of the pair.

        Returns
        -------
        int
            Pairs of neighbour rows that cross.
        """
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
    """Return the average row of a unit's already-placed neighbours.

    Parameters
    ----------
    unit : Unit
        Unit to rank.
    settled : dict[Unit, int]
        Rows of units in columns already walked (those to the west).

    Returns
    -------
    float
        Average neighbour row, or infinity when none is placed, so such a
        unit sorts last.
    """
    rows = [settled[peer] for peer in _peers(unit) if peer in settled]
    return sum(rows) / len(rows) if rows else float("inf")


def _peers(unit: "Unit") -> list["Unit"]:
    """Return every unit a stream joins to this one, in port order.

    Parameters
    ----------
    unit : Unit
        Unit whose neighbours are wanted.

    Returns
    -------
    list[Unit]
        Neighbouring units, repeated once per connecting stream.
    """
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
    """Return whole rows, one apart and in order, nearest the fitted rows.

    Pool adjacent violators over ``fitted[i] - i``; each pooled group sits
    at its weighted mean. Rounding happens once per group, at its first
    member, so a group stays contiguous (two units pooled at -0.5 become
    rows -1 and 0, not -1 and +1). Runs in O(n).

    Parameters
    ----------
    fitted : list[float]
        Fitted rows in column order.
    weights : list[float]
        Positive stiffness per unit.

    Returns
    -------
    list[int]
        Strictly increasing rows, one per unit.
    """
    #: weight, weight * level, first index, how many
    groups: list[list[float]] = []
    for index, (value, weight) in enumerate(zip(fitted, weights)):
        groups.append([weight, weight * (value - index), float(index), 1.0])
        while len(groups) > 1:
            below, above = groups[-2], groups[-1]
            # Compare weighted means by cross-multiplying; weights are positive.
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
    """Shift one axis so the smallest rank is zero.

    Skipped when any unit has a pin on this axis, since a pin names a fixed
    column or row.

    Parameters
    ----------
    units : list[Unit]
        Placed units.
    axis : str
        ``"col"`` or ``"row"``.
    """
    if any(u.pin_ is not None and getattr(u.pin_, axis) is not None for u in units):
        return
    lift = min(getattr(slot(u), axis) or 0 for u in units)
    if lift == 0:
        return
    for u in units:
        setattr(slot(u), axis, (getattr(slot(u), axis) or 0) - lift)
