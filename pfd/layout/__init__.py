"""Layout Engine orchestrator.

The layout engine computes geometry (each unit's Frame) from topology.
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
        """Layout the flowsheet by computing a Frame for each unit."""


def _seed_slots(fs: "Flowsheet") -> None:
    """Seed each unit's internal solver ``_Slot`` from its ``Pin`` intent.

    Reseeding from ``pin_`` on every run is what makes layout idempotent: the
    solver never reads back a previous run's coordinates, only the user's intent.
    """
    from pfd.geometry import _Slot
    from pfd.portgeom import resolve_size

    for u in fs.units:
        w, h = resolve_size(u)
        pin = u.pin_
        u._slot = _Slot(
            w=w, h=h,
            col=pin.col if pin else None,
            row=pin.row if pin else None,
            x=pin.x if pin else None,
            y=pin.y if pin else None,
            orientation=pin.orientation if pin else 0.0,
            mirrored=pin.mirrored if pin else False,
        )


class SugiyamaLayoutEngine:
    """Default auto-layout engine implementing the Sugiyama algorithm."""

    def layout(self, fs: "Flowsheet") -> None:
        from pfd.layout.cycles import break_cycles
        from pfd.layout.layering import assign_layers
        from pfd.layout.ordering import order_within_layers
        from pfd.layout.coordinates import assign_coordinates

        break_cycles(fs)
        _seed_slots(fs)
        assign_layers(fs)
        order_within_layers(fs)
        assign_coordinates(fs)


default_layout_engine = SugiyamaLayoutEngine()
