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
    for u in fs.units:
        # If user explicitly pinned x, y coordinates, keep them.
        if u.placement.x is None:
            u.placement.x = MARGIN_X + (u.placement.col or 0) * X_GAP
            
        if u.placement.y is None:
            u.placement.y = MARGIN_Y + (u.placement.row or 0) * Y_GAP
