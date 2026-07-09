"""Phase 3/4: Coordinate Assignment."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

X_GAP = 150
Y_GAP = 120
MARGIN_X = 50
MARGIN_Y = 50

def assign_coordinates(fs: "Flowsheet") -> None:
    """Map (col, row) ranks to absolute (x, y) pixel coordinates."""
    from pfd.render.symbols import default_registry
    
    # Calculate max width of units in each column
    col_widths = {}
    for u in fs.units:
        col = u.placement.col or 0
        if u.width is not None:
            w = u.width
        else:
            sym = default_registry.get(u.kind, getattr(u, 'variant', 'default'))
            w = sym.width
            if u.kind in ("feed", "product"):
                w = max(80.0, len(u.name) * 8.0 + 30.0)
        col_widths[col] = max(col_widths.get(col, 0.0), w)

    # Compute X start coordinates for each column
    x_pos = {}
    curr_x = MARGIN_X
    for col in sorted(col_widths.keys()):
        x_pos[col] = curr_x
        curr_x += col_widths[col] + 100.0  # 100px routing gap minimum
    
    unpinned_y = set()
    for u in fs.units:
        assert u.placement is not None
        # If user explicitly pinned x, y coordinates, keep them.
        if u.placement.x is None:
            col = u.placement.col or 0
            u.placement.x = x_pos.get(col, MARGIN_X)
            
        if u.placement.y is None:
            u.placement.y = MARGIN_Y + (u.placement.row or 0) * Y_GAP
            unpinned_y.add(u)
            
    # Post-pass: Align terminal units vertically with their target
    for u in unpinned_y:
        assert u.placement is not None
        connected_streams = [s for s in fs.streams if s.source.owner == u or s.dest.owner == u]
        
        # If this unit is a terminal (like Feed or Product) with exactly 1 stream
        if len(connected_streams) == 1:
            s = connected_streams[0]
            
            if s.source.owner == u:
                my_port = s.source
                other_port = s.dest
            else:
                my_port = s.dest
                other_port = s.source
                
            other_u = other_port.owner
            assert other_u is not None
            assert other_u.placement is not None
            
            sym_u = default_registry.get(u.kind)
            sym_other = default_registry.get(other_u.kind)
            
            my_py = sym_u.ports.get(my_port.name, (0, 0))[1]
            other_px, other_py = sym_other.ports.get(other_port.name, (0, 0))
            
            from pfd.routing import get_outward_dir
            out_dir = get_outward_dir(other_px, other_py, sym_other.width, sym_other.height, other_u.kind, other_port.name)
            
            # Target absolute Y of the other port
            assert other_u.placement.y is not None
            target_abs_y = other_u.placement.y + other_py
            
            # If the port faces N or S, the stream must route via the margin escape lane.
            # We align the terminal unit with the escape lane to guarantee an L-shape rather than a Z-shape.
            if out_dir == "N":
                target_abs_y = other_u.placement.y - 15.0
            elif out_dir == "S":
                target_abs_y = other_u.placement.y + sym_other.height + 15.0
            
            # Align our port's absolute Y to match target_abs_y
            new_y = target_abs_y - my_py
            
            # Ensure we don't overlap with another unit in the same column
            overlap = False
            for other_unit in fs.units:
                if other_unit != u and other_unit.placement and other_unit.placement.col == u.placement.col:
                    other_sym = default_registry.get(other_unit.kind)
                    if other_unit.placement.y is not None:
                        # Check bounding box overlap
                        if not (new_y + sym_u.height <= other_unit.placement.y or new_y >= other_unit.placement.y + other_sym.height):
                            overlap = True
                            break
                            
            if not overlap:
                u.placement.y = new_y
