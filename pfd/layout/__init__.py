"""Layout Engine orchestrator.

The layout engine computes geometry (Placement attributes) from topology.
It follows the standard Sugiyama phases:
Phase 0: Cycle breaking
Phase 1: Layering (Rank Assignment)
Phase 2: Ordering (Crossing Reduction)
Phase 3/4: Coordinate Assignment
"""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet


class LayoutEngine(Protocol):
    def layout(self, fs: "Flowsheet") -> None:
        """Layout the flowsheet by computing Placements for each unit."""


class SugiyamaLayoutEngine:
    """Default auto-layout engine implementing the Sugiyama algorithm."""
    
    def layout(self, fs: "Flowsheet") -> None:
        from pfd.layout.cycles import break_cycles
        from pfd.layout.layering import assign_layers
        from pfd.layout.ordering import order_within_layers
        from pfd.layout.coordinates import assign_coordinates
        
        break_cycles(fs)
        assign_layers(fs)
        order_within_layers(fs)
        assign_coordinates(fs)


default_layout_engine = SugiyamaLayoutEngine()
