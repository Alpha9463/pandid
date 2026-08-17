"""Layout Engine orchestrator.

The layout engine computes geometry (each unit's Frame) from topology.
It follows the standard Sugiyama phases:

- Phase 0: Cycle breaking
- Phase 1: Layering (rank assignment)
- Phase 2: Ordering (crossing reduction)
- Phase 3/4: Coordinate assignment

Two phases follow, both of which need every drawn box to be final:
port-face selection, then label placement. Their order is load-bearing:
a label goes to a face no connected nozzle occupies, so it has to be
told which faces those are.

Face selection and one part of the coordinate phase do not settle in a
single pass, and they are run to a fixed point rather than in an order.
A balloon hung on a *stream* lands on that stream's drawn path, and
where the path leaves each end is the face selection's answer -- while
the selection reads the boxes, of which the balloon is one. Neither can
go first: run once, the first ``layout()`` placed such a balloon from
the faces a symbol defaults to and the second placed it from the faces
the first chose, so laying a sheet out twice did not draw it twice the
same. ``examples/04_control_loop.py``'s interlock, hung on the signal
between two balloons, moved 16px on the second run.
"""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


class LayoutEngine(Protocol):
    def layout(self, fs: "Flowsheet") -> None:
        """Layout the flowsheet by computing a Frame for each unit."""


def _seed_slots(fs: "Flowsheet") -> None:
    """Seed each unit's solver ``_Slot`` from its ``Pin`` intent.

    Reseeding from ``pin_`` on every run is what makes layout
    idempotent: the solver never reads back a previous run's
    coordinates, only the user's intent.
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
    """The default auto-layout engine: Sugiyama's algorithm."""

    def layout(self, fs: "Flowsheet") -> None:
        from pandid.layout.attach import MAX_PLACEMENT_PASSES, place_attached
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
        # Choose the faces, and place again where that moved a balloon.
        # The loop ends on a selection made against boxes nothing has
        # moved since, so the sheet it hands on is a function of the
        # model and not of what the last run left behind. Every sheet in
        # the corpus settles in one pass and 04 in two; the cap is
        # ``route()``'s own, for the same reason it has one.
        for _ in range(MAX_PLACEMENT_PASSES):
            select_faces(fs)
            if not place_attached(fs):
                break
        assign_labels(fs)


default_layout_engine = SugiyamaLayoutEngine()
