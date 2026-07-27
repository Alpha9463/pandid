"""Phase 2: Crossing Reduction (Ordering within ranks)."""

from typing import TYPE_CHECKING
from collections import defaultdict

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit


def order_within_layers(fs: "Flowsheet") -> None:
    """Assign a row index to each unit to minimise stream crossings."""
    from pandid.layout.attach import free_streams, free_units

    units = free_units(fs)
    if not units:
        return

    # Group units by column
    cols: dict[int, list["Unit"]] = defaultdict(list)
    for u in units:
        assert u._slot is not None and u._slot.col is not None
        cols[u._slot.col].append(u)

    if not cols:
        return

    max_col = max(cols.keys())

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
        for col_idx in range(1, max_col + 1):
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
        for col_idx in range(max_col - 1, -1, -1):
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
