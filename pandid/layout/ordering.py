"""Phase 2: Crossing Reduction (Ordering within ranks)."""

from typing import TYPE_CHECKING
from collections import defaultdict

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import _Slot
    from pandid.layout.stacking import Stack
    from pandid.units import Unit


def order_within_layers(fs: "Flowsheet") -> None:
    """Assign a row index to each unit to minimise stream crossings."""
    from pandid.layout.attach import free_streams, free_units

    every = free_units(fs)
    if not every:
        return

    # A unit a vertical connection places is held out of the barycentre
    # and given its row afterwards, from the unit it hangs under or over
    # (see _stack_rows). Averaging it in would move the very unit it is
    # measured against, and the row a north face asks for is not an
    # average of anything.
    satellites = _satellites(fs)
    units = [u for u in every if u not in satellites]

    # Group units by column
    cols: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        assert u._slot is not None and u._slot.col is not None
        cols[u._slot.col].append(u)

    if not cols:
        _stack_rows(every, satellites)
        return

    # The sweeps run between the columns that exist, which a pin can put
    # left of zero. Counting from zero instead leaves both sweeps empty
    # on such a sheet -- no ordering done, and nothing said about it.
    min_col, max_col = min(cols.keys()), max(cols.keys())

    # 0. Identify user-pinned rows before anything is overwritten
    pinned_rows = {}
    for u in units:
        assert u._slot is not None
        if u._slot.row is not None:
            pinned_rows[u] = u._slot.row

    # 1. Initial row assignment
    for col_idx, units_in_col in cols.items():
        occupied = {pinned_rows[u] for u in units_in_col if u in pinned_rows}
        next_avail = 0
        for u in units_in_col:
            assert u._slot is not None
            if u not in pinned_rows:
                while next_avail in occupied:
                    next_avail += 1
                u._slot.row = next_avail
                occupied.add(next_avail)

    # Build forward and backward adjacency for Barycenter
    parents_of: dict["Unit", list["Unit"]] = defaultdict(list)
    children_of: dict["Unit", list["Unit"]] = defaultdict(list)

    for s in free_streams(fs):
        if not s.is_recycle:
            u, v = s.source.owner, s.dest.owner
            assert u is not None and v is not None
            if u in satellites or v in satellites:
                continue
            children_of[u].append(v)
            parents_of[v].append(u)

    # 2. Iterative Barycenter sweeps
    def assign_closest_available(units, target_barys, occupied):
        sorted_units = sorted(units, key=lambda x: target_barys[x])
        for u in sorted_units:
            target = round(target_barys[u])
            offset = 0
            while True:
                if target + offset >= 0 and (target + offset) not in occupied:
                    assert u._slot is not None
                    u._slot.row = target + offset
                    occupied.add(target + offset)
                    break
                if target - offset >= 0 and (target - offset) not in occupied:
                    assert u._slot is not None
                    u._slot.row = target - offset
                    occupied.add(target - offset)
                    break
                offset += 1

    for _ in range(4):
        # Down sweep (left to right)
        for col_idx in range(min_col + 1, max_col + 1):
            if col_idx not in cols:
                continue

            units = cols[col_idx]
            occupied = {pinned_rows[u] for u in units if u in pinned_rows}
            unpinned = [u for u in units if u not in pinned_rows]

            if not unpinned:
                continue

            target_barys = {}
            for u in unpinned:
                parents = parents_of[u]
                assert u._slot is not None and u._slot.row is not None
                if parents:
                    val = sum((p._slot.row for p in parents if p._slot and p._slot.row is not None), start=0)
                    target_barys[u] = val / len(parents)
                else:
                    target_barys[u] = float(u._slot.row) # keep current

            assign_closest_available(unpinned, target_barys, occupied)

        # Up sweep (right to left)
        for col_idx in range(max_col - 1, min_col - 1, -1):
            if col_idx not in cols:
                continue

            units = cols[col_idx]
            occupied = {pinned_rows[u] for u in units if u in pinned_rows}
            unpinned = [u for u in units if u not in pinned_rows]

            if not unpinned:
                continue

            target_barys = {}
            for u in unpinned:
                children = children_of[u]
                assert u._slot is not None and u._slot.row is not None
                if children:
                    val = sum((c._slot.row for c in children if c._slot and c._slot.row is not None), start=0)
                    target_barys[u] = val / len(children)
                else:
                    target_barys[u] = float(u._slot.row)

            assign_closest_available(unpinned, target_barys, occupied)

    _stack_rows(every, satellites)


def _satellites(fs: "Flowsheet") -> dict["Unit", "Stack"]:
    """The unit each vertical connection places, and what places it.

    One constraint per unit: a peer taken from the north by two blocks
    at once can only sit over one of them, and the streams are visited
    in the order the flowsheet holds them so which one does not depend
    on the order the author connected them. A row the author pinned wins
    outright and leaves the unit ranked normally.
    """
    from pandid.layout.stacking import stacked_edges

    out: dict["Unit", "Stack"] = {}
    for st in stacked_edges(fs):
        if _slot(st.satellite).row is None and st.satellite not in out:
            out[st.satellite] = st
    return out


def _stack_rows(every: list["Unit"], satellites: dict["Unit", "Stack"]) -> None:
    """Put each satellite in the row its face asks for.

    One row past its anchor, on the side the face names, and one further
    out again where that row is already spoken for -- so two north feeds
    into one block stack above it rather than fighting over the row
    directly over its roof.

    Anchors are resolved before what hangs off them, since a satellite
    can itself be one. A chain that never resolves is a cycle of
    vertical connections, which states no top and no bottom; those units
    fall back to the first free row in their column.
    """
    if not satellites:
        return
    pending = list(satellites)
    while pending:
        progressed = False
        for u in list(pending):
            st = satellites[u]
            if st.anchor in pending:
                continue
            taken = _taken(every, u)
            row = (_slot(st.anchor).row or 0) + st.delta
            while row in taken:
                row += st.delta
            _slot(u).row = row
            pending.remove(u)
            progressed = True
        if not progressed:
            for u in pending:
                _free_row(every, u)
            break
    _rebase(every, satellites)


def _slot(u: "Unit") -> "_Slot":
    """The solver state every ranked unit carries by this phase."""
    assert u._slot is not None
    return u._slot


def _taken(every: list["Unit"], u: "Unit") -> set[int]:
    """Rows already held in ``u``'s column."""
    col = _slot(u).col
    return {r for v in every
            if v is not u and _slot(v).col == col
            and (r := _slot(v).row) is not None}


def _free_row(every: list["Unit"], u: "Unit") -> None:
    """Drop ``u`` in the first unused row of its column."""
    taken = _taken(every, u)
    _slot(u).row = next(r for r in range(len(every) + 1) if r not in taken)


def _rebase(every: list["Unit"], satellites: dict["Unit", "Stack"]) -> None:
    """Slide the rows back down to zero, which the bands count from.

    A north satellite over a unit on the top row lands above it, and the
    coordinate pass has no band there. Moving every row together is what
    keeps that from being a change to the drawing: the sheet is the same
    one, one band lower.

    A sheet carrying a pinned row is left alone. A pin names a band, so
    renumbering the bands under it would move a unit the author placed.
    Where that leaves a row below zero the satellite takes the first
    free row instead, which is the constraint dropped rather than the
    pin broken.
    """
    rows = [r for u in every if (r := _slot(u).row) is not None]
    if not rows or min(rows) >= 0:
        return
    if any(u.pin_ is not None and u.pin_.row is not None for u in every):
        for u in satellites:
            row = _slot(u).row
            if row is not None and row < 0:
                _free_row(every, u)
        return
    lift = min(rows)
    for u in every:
        row = _slot(u).row
        if row is not None:
            _slot(u).row = row - lift
