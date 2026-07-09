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
    
    unpinned_y = set()
    for u in fs.units:
        # If user explicitly pinned x, y coordinates, keep them.
        if u.placement.x is None:
            u.placement.x = MARGIN_X + (u.placement.col or 0) * X_GAP
            
        if u.placement.y is None:
            u.placement.y = MARGIN_Y + (u.placement.row or 0) * Y_GAP
            unpinned_y.add(u)
            
    # Post-pass: Align terminal units vertically with their target
    for u in unpinned_y:
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
            
            sym_u = default_registry.get(u.kind)
            sym_other = default_registry.get(other_u.kind)
            
            my_py = sym_u.ports.get(my_port.name, (0, 0))[1]
            other_px, other_py = sym_other.ports.get(other_port.name, (0, 0))
            
            from pfd.routing import get_outward_dir
            out_dir = get_outward_dir(other_px, other_py, sym_other.width, sym_other.height, other_u.kind, other_port.name)
            
            # Target absolute Y of the other port
            target_abs_y = other_u.placement.y + other_py
            
            # If the port faces N or S, the stream must route via the margin escape lane.
            # We align the terminal unit with the escape lane to guarantee an L-shape rather than a Z-shape.
            if out_dir == "N":
                target_abs_y = other_u.placement.y - 15.0
            elif out_dir == "S":
                target_abs_y = other_u.placement.y + sym_other.height + 15.0
            
            # Align our port's absolute Y to match target_abs_y
            u.placement.y = target_abs_y - my_py
