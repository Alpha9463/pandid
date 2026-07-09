"""Phase 2: Crossing Reduction (Ordering within ranks)."""

from typing import TYPE_CHECKING
from collections import defaultdict

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet
    from pfd.units import Unit


def order_within_layers(fs: "Flowsheet") -> None:
    """Assign a row index to each unit to minimise stream crossings."""
    if not fs.units:
        return
        
    # Group units by column
    cols: dict[int, list["Unit"]] = defaultdict(list)
    for u in fs.units:
        assert u.placement is not None and u.placement.col is not None
        cols[u.placement.col].append(u)
        
    if not cols:
        return
        
    max_col = max(cols.keys())
    
    # 0. Identify user-pinned rows before we overwrite anything
    pinned_rows = {}
    for u in fs.units:
        assert u.placement is not None
        if u.placement.row is not None:
            pinned_rows[u] = u.placement.row

    # 1. Initial row assignment
    for col_idx, units_in_col in cols.items():
        occupied = {pinned_rows[u] for u in units_in_col if u in pinned_rows}
        next_avail = 0
        for u in units_in_col:
            assert u.placement is not None
            if u not in pinned_rows:
                while next_avail in occupied:
                    next_avail += 1
                u.placement.row = next_avail
                occupied.add(next_avail)
                
    # Build forward and backward adjacency for Barycenter
    parents_of: dict["Unit", list["Unit"]] = defaultdict(list)
    children_of: dict["Unit", list["Unit"]] = defaultdict(list)
    
    for s in fs.streams:
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
                    assert u.placement is not None
                    u.placement.row = target + offset
                    occupied.add(target + offset)
                    break
                if target - offset >= 0 and (target - offset) not in occupied:
                    assert u.placement is not None
                    u.placement.row = target - offset
                    occupied.add(target - offset)
                    break
                offset += 1
                
    for _ in range(4): # 4 iterations
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
                assert u.placement is not None and u.placement.row is not None
                if parents:
                    val = sum((p.placement.row for p in parents if p.placement and p.placement.row is not None), start=0)
                    target_barys[u] = val / len(parents)
                else:
                    target_barys[u] = float(u.placement.row) # keep current
                    
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
                assert u.placement is not None and u.placement.row is not None
                if children:
                    val = sum((c.placement.row for c in children if c.placement and c.placement.row is not None), start=0)
                    target_barys[u] = val / len(children)
                else:
                    target_barys[u] = float(u.placement.row)
                    
            assign_closest_available(unpinned, target_barys, occupied)
