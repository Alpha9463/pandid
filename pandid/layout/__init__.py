"""Compute each unit's frame from the flowsheet topology.

Stage 1 places process units and pipe furniture; stage 2 places
instrument balloons against that geometry.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


def _seed_slots(fs: "Flowsheet") -> None:
    """Replace each unit's solver slot with one seeded from its pin.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose units to seed.
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


class ConstraintLayoutEngine:
    """Place units with the default automatic layout."""

    def layout(self, fs: "Flowsheet") -> None:
        """Set unit frames, port faces and label sides.

        Parameters
        ----------
        fs : Flowsheet
            Sheet to lay out.
        """
        from pandid.layout.attach import MAX_PLACEMENT_PASSES
        from pandid.layout.control import place_control
        from pandid.layout.cycles import break_cycles
        from pandid.layout.faces import select_faces
        from pandid.layout.labels import assign_labels
        from pandid.layout.mounted import mounted_runs, place_mounted

        _seed_slots(fs)
        break_cycles(fs)
        runs = mounted_runs(fs, fs._corner_valves)
        fs._mounted_layout = bool(runs)
        place_mounted(fs, runs)
        # Repeat until no balloon moves, up to the pass limit.
        for _ in range(MAX_PLACEMENT_PASSES):
            select_faces(fs)
            if not place_control(fs):
                break
        assign_labels(fs)


default_layout_engine = ConstraintLayoutEngine()
