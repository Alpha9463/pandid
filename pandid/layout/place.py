"""Stage 1: where every process unit sits on the grid.

Two runs of :func:`pandid.layout.solver.solve`, one per axis, over the
constraints :mod:`pandid.layout.claims` reads off the nozzles. The
column axis is solved first because the row axis needs to know which
units share a column -- two boxes in one column may not be in one row,
and that is a constraint the row system has to be told about rather than
a collision found afterwards.

Crossing reduction sits between them. It is not a constraint and does
not pretend to be one: a barycentre says which of two units in a column
*reads* better on top, and the answer is fed to the row solver as the
position to start from. Everything the constraints then do is to push a
unit further down, never up, so the ordering survives whatever the
nozzles insist on.

Why the barycentre no longer holds anything out
-----------------------------------------------
The old ordering pass kept a vertically connected unit out of the
sweeps, because averaging it in would have moved the very unit it was
about to be measured against. Here the sweep is a *seed* and the
measurement happens afterwards, in the solver, so there is nothing to
hold out: a satellite is averaged in like anything else and is then
pushed to where its face says, from wherever the average left it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pandid.layout import claims as claims_mod
from pandid.layout.solver import Order, solve
from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream
    from pandid.units import Unit

#: Barycentre sweeps, down the sheet and back. Four is what the old
#: ordering phase ran and what the corpus is drawn against; the sweeps
#: are cheap and the fourth still moves a unit on the two widest sheets.
SWEEPS = 4


def assign_positions(fs: "Flowsheet") -> None:
    """Fill in ``_slot.col`` and ``_slot.row`` for every process unit."""
    from pandid.layout.stages import process_streams, process_units

    units = process_units(fs)
    if not units:
        return
    streams = process_streams(fs)
    claims = claims_mod.read(fs, streams)

    columns = solve(units, claims.along, claims.columns,
                    {u: col for u in units if (col := slot(u).col) is not None})
    for u in units:
        slot(u).col = columns[u]

    # The row axis is solved three times, and the first two are about
    # the *stacks* rather than about the sheet. A stack is only rigid
    # once the separations inside it are in -- two feeds over one block
    # are a row apart, not the same row -- so the arrangement is settled
    # before the crossing reduction is asked where to put the whole
    # thing. Settling it afterwards left the block two rows below the
    # run it sits on, because the separation pushed it down after the
    # stack had already been slid onto the row that run wanted.
    pins = {u: row for u in units if (row := slot(u).row) is not None}
    stacked = solve(units, claims.across, [], {})
    stacked = solve(units, claims.across + _separations(units, columns, stacked), [], {})
    seed = _settled(units, claims, pins, stacked,
                    _crossing_order(units, streams, columns, stacked))
    rows = solve(units, claims.across + _separations(units, columns, seed), [],
                 pins, seed=seed)
    for u, row in _rebased(units, rows).items():
        slot(u).row = row


def _settled(units: list["Unit"], claims: claims_mod.Claims,
             pins: dict["Unit", int], stacked: dict["Unit", int],
             bary: dict["Unit", int]) -> dict["Unit", int]:
    """Where each stack of units belongs, as a whole.

    A run of units a nozzle stacks -- a relief valve over the vessel it
    protects, over the flare header it discharges to -- is **rigid**:
    what the faces fix is the arrangement inside it, and where the whole
    thing goes is decided by whichever of its members are wired into the
    rest of the sheet. So the relative rows come from ``stacked``, which
    is the face constraints solved on their own, and the stack is then
    slid bodily onto the row the crossing reduction wants for the
    members that have a run to somewhere else.

    Sliding is the point. The row solver only ever moves a unit further
    *down*, so a stack it has to satisfy from a flat start satisfies it
    by pushing the bottom unit down -- and the bottom unit is the vessel
    on the main run, which then leaves the spine it belongs on and drags
    the drawing into a staircase. Slid instead, the same three units
    keep their arrangement and it is the relief valve and the flare that
    go up, which is where they were always going to be drawn.
    """
    lead = claims_mod.stacks(units, claims)
    members: dict["Unit", list["Unit"]] = defaultdict(list)
    for u in units:
        members[lead[u]].append(u)
    wired = {u for edge in claims.along for u in (edge.before, edge.after)
             if lead[edge.before] is not lead[edge.after]}

    seed: dict["Unit", int] = {}
    for group in members.values():
        held = [u for u in group if u in pins]
        if held:
            # A pin on any member is a pin on the stack: the faces have
            # already said how the members sit relative to each other,
            # so the band the author named for one of them names the
            # bands the rest go in. Solving the stack against the pin
            # instead leaves the pinned unit where it is and pushes
            # everything else *down* past it -- a north feed drawn under
            # the block it feeds, which is #311.
            shift = pins[held[0]] - stacked[held[0]]
        else:
            anchors = [u for u in group if u in wired] or group
            shift = round(sum(bary[u] - stacked[u] for u in anchors) / len(anchors))
        for u in group:
            seed[u] = stacked[u] + shift
    return seed


def _separations(units: list["Unit"], columns: dict["Unit", int],
                 seed: dict["Unit", int]) -> list[Order]:
    """One constraint per neighbouring pair in a column, top to bottom.

    Read off the seed the stacks settled on rather than off the
    barycentre alone, so the order these state is the order the nozzles
    have already agreed to. Stating a different one would put a
    separation and a face on opposite sides of one pair, and the solver
    would have to drop the face -- two boxes in one place being the
    worse drawing of the two.
    """
    by_column: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        by_column[columns[u]].append(u)
    order = {u: i for i, u in enumerate(units)}
    out: list[Order] = []
    for column in sorted(by_column):
        stack = stacked_order(by_column[column], seed, order)
        for above, below in zip(stack, stack[1:]):
            out.append(Order(above, below, claims_mod.SEPARATION))
    return out


def stacked_order(column: list["Unit"], rows: dict["Unit", int],
                  order: dict["Unit", int]) -> list["Unit"]:
    """One column's units, top to bottom, ties settled by the flowsheet.

    Two feeds onto one roof are both a row above the block and the
    constraints say nothing about which of them is higher. The one
    stated first goes **nearest** the block, which is the answer the old
    stacking pass gave and the reason its runs came down in one turn:
    the near feed drops straight onto its nozzle, and the far one clears
    it because its own nozzle is further along the roof. Stated the
    other way round the near feed's run has to get round the far one's
    box, which is a detour east, down and back west.

    So a tied run is reversed unless it is the last one in the column,
    which is the run *below* an anchor rather than above it -- there the
    first stated is already the nearest.
    """
    groups: dict[int, list["Unit"]] = defaultdict(list)
    for u in sorted(column, key=lambda v: order[v]):
        groups[rows[u]].append(u)
    keys = sorted(groups)
    out: list["Unit"] = []
    for index, key in enumerate(keys):
        run = groups[key]
        out.extend(run if index == len(keys) - 1 else reversed(run))
    return out


def _rebased(units: list["Unit"], rows: dict["Unit", int]) -> dict["Unit", int]:
    """Slide the rows back to zero, which the bands count from.

    Both directions. A satellite over a unit on the top row lands above
    it, and a run of nozzles all saying *below* pushes the whole sheet
    down; either way the drawing is the same one and only its numbering
    moved. What the row is measured from has to be the sheet, so that a
    ``frame.row`` a caller reads back means the band it can count to.

    A sheet carrying a pinned row is left where it is. A pin names a
    band, so renumbering the bands under it would move a unit the author
    placed -- and the satellite over it can stay where its face put it,
    because a row below zero is a row the coordinate pass builds a band
    for.
    """
    lift = min(rows.values(), default=0)
    if lift == 0 or any(u.pin_ is not None and u.pin_.row is not None for u in units):
        return rows
    return {u: row - lift for u, row in rows.items()}


# ---------------------------------------------------------------------------
# Crossing reduction
# ---------------------------------------------------------------------------


def _crossing_order(units: list["Unit"], streams: list["Stream"],
                    columns: dict["Unit", int],
                    stacked: dict["Unit", int]) -> dict["Unit", int]:
    """A row per unit that reads well, before any nozzle has its say.

    Sugiyama's barycentre, swept down the sheet and back: a unit goes to
    the average row of what feeds it, then of what it feeds. Rows stay
    whole and distinct within a column throughout -- a barycentre that
    lands on a taken row steps out to the nearest free one -- so what
    comes out is already a legal arrangement and not a set of
    preferences someone else has to make legal.

    The starting arrangement in each column is the order the *faces*
    ask for, so a sweep that has nothing to say about a pair leaves them
    the way the nozzles wanted them rather than the way the flowsheet
    happened to list them.
    """
    by_column: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        by_column[columns[u]].append(u)

    pinned = {u: row for u in units if (row := slot(u).row) is not None}
    position = {u: i for i, u in enumerate(units)}
    rows: dict["Unit", int] = {}
    for column in sorted(by_column):
        taken = {pinned[u] for u in by_column[column] if u in pinned}
        free = 0
        for u in stacked_order(by_column[column], stacked, position):
            if u in pinned:
                rows[u] = pinned[u]
                continue
            while free in taken:
                free += 1
            rows[u] = free
            taken.add(free)

    parents: dict["Unit", list["Unit"]] = defaultdict(list)
    children: dict["Unit", list["Unit"]] = defaultdict(list)
    for s in streams:
        if s.is_recycle:
            continue  # a run drawn backwards is not a reason to line up
        src, dst = s.source.owner, s.dest.owner
        assert src is not None and dst is not None
        children[src].append(dst)
        parents[dst].append(src)

    order = {u: i for i, u in enumerate(units)}
    sweeps = sorted(by_column)
    for _ in range(SWEEPS):
        for column in sweeps:
            _sweep(by_column[column], parents, rows, pinned, order)
        for column in reversed(sweeps):
            _sweep(by_column[column], children, rows, pinned, order)
    return rows


def _sweep(column: list["Unit"], towards: dict["Unit", list["Unit"]],
           rows: dict["Unit", int], pinned: dict["Unit", int],
           order: dict["Unit", int]) -> None:
    """Move one column's units to the average row of their neighbours."""
    movable = [u for u in column if u not in pinned]
    if not movable:
        return
    target: dict["Unit", float] = {}
    for u in movable:
        peers = [p for p in towards[u] if p in rows]
        target[u] = (sum(rows[p] for p in peers) / len(peers) if peers
                     else float(rows[u]))
    taken = {pinned[u] for u in column if u in pinned}
    for u in sorted(movable, key=lambda v: (target[v], order[v])):
        rows[u] = _closest_available(round(target[u]), taken)
        taken.add(rows[u])


def _closest_available(target: int, taken: set[int]) -> int:
    """The free row nearest ``target``, and never above the sheet.

    Stepping out from the barycentre rather than packing from zero is
    what keeps a unit that belongs beside its neighbour from being
    handed whichever row happened to be spare.
    """
    offset = 0
    while True:
        if target + offset >= 0 and target + offset not in taken:
            return target + offset
        if target - offset >= 0 and target - offset not in taken:
            return target - offset
        offset += 1
