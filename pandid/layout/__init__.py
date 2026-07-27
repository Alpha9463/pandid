"""Layout Engine orchestrator.

The layout engine computes geometry (each unit's Frame) from topology.
It follows the standard Sugiyama phases:
Phase 0: Cycle breaking
Phase 1: Layering (Rank Assignment)
Phase 2: Ordering (Crossing Reduction)
Phase 3/4: Coordinate Assignment

Two phases follow, both of which need every drawn box to be final and neither of
which may move one: port-face selection, then label placement. Their order is
load-bearing — a label goes to a face no connected nozzle occupies, so it has to
be told which faces those are.
"""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


class LayoutEngine(Protocol):
    def layout(self, fs: "Flowsheet") -> None:
        """Layout the flowsheet by computing a Frame for each unit."""


def _seed_slots(fs: "Flowsheet") -> None:
    """Seed each unit's internal solver ``_Slot`` from its ``Pin`` intent.

    Reseeding from ``pin_`` on every run is what makes layout idempotent: the
    solver never reads back a previous run's coordinates, only the user's intent.
    """
    from pandid.geometry import _Slot
    from pandid.portgeom import resolve_size

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
            mirror_y=pin.mirror_y if pin else False,
        )


class SugiyamaLayoutEngine:
    """Default auto-layout engine implementing the Sugiyama algorithm."""

    def layout(self, fs: "Flowsheet") -> None:
        from pandid.layout.cycles import break_cycles
        from pandid.layout.layering import assign_layers
        from pandid.layout.ordering import order_within_layers
        from pandid.layout.coordinates import assign_coordinates, assign_labels
        from pandid.layout.faces import select_faces

        break_cycles(fs)
        _seed_slots(fs)
        assign_layers(fs)
        order_within_layers(fs)
        assign_coordinates(fs)
        select_faces(fs)
        assign_labels(fs)


default_layout_engine = SugiyamaLayoutEngine()
