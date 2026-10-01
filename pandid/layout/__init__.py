"""Compute each unit's frame from the flowsheet topology.

**Stage 1, process.** Units that carry material and streams of kind
``"material"``:

- cycle breaking, which identifies return lines;
- placement (:mod:`pandid.layout.place`): one weighted least-squares fit per
  axis over the neighbour positions each unit claims
  (:mod:`pandid.layout.claims`), solved by :mod:`pandid.layout.solver`, then
  whole grid columns and rows with crossing-reduction sweeps;
- coordinates (:mod:`pandid.layout.coordinates`): grid to pixels, folded
  into bands, with instrumentation space reserved
  (:mod:`pandid.layout.halo`).

**Stage 2, control.** Instruments and signal runs, placed against the
stage 1 geometry (:mod:`pandid.layout.control`).

Port-face selection and control placement then repeat until neither moves
the other, because an attached balloon sits on a drawn path that depends on
the selected faces. Labels are placed last, on faces no connected nozzle
uses.
"""

from typing import Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet


class LayoutEngine(Protocol):
    """Define the interface ``Flowsheet.layout`` requires of an engine."""

    def layout(self, fs: "Flowsheet") -> None:
        """Compute a frame for each unit.

        Parameters
        ----------
        fs : Flowsheet
            Sheet to lay out.

        Returns
        -------
        None
            Frames are stored on the units.
        """


def _seed_slots(fs: "Flowsheet") -> None:
    """Seed each unit's solver slot from its pin.

    Every run starts from author intent, never from earlier coordinates,
    so layout is idempotent.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose units receive fresh slots.

    Returns
    -------
    None
        ``_slot`` is replaced on every unit.
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
    """Place units with the default automatic layout.

    Equipment and stream-relative stations are placed in separate passes
    when a station can be contracted. Other sheets use the full unit graph.
    """

    def layout(self, fs: "Flowsheet", *, use_coarse: bool = True,
               reservation: Literal["conservative", "compact", "shared"] = "shared",
               row_compaction: float = 0.0,
               directional_station: bool = False,
               unaligned: frozenset[int] = frozenset()) -> None:
        """Resolve process, inline, and control geometry for a sheet.

        Parameters
        ----------
        fs : Flowsheet
            Sheet to lay out.
        use_coarse : bool, optional
            Try equipment-first placement for stream-relative stations.
        reservation : {"conservative", "compact", "shared"}, optional
            Attachment-corridor estimate for an isolated equipment trial.
        row_compaction : float, optional
            Fraction of independent column-row compaction to apply.
        directional_station : bool, optional
            Follow explicitly mirrored station flow in a detached trial.
        unaligned : frozenset[int], optional
            Global indices of units a detached trial keeps on their row
            axis. Equipment-first placement ignores it.

        Returns
        -------
        None
            Unit frames and chosen faces are updated in place.
        """
        from pandid.layout.attach import MAX_PLACEMENT_PASSES
        from pandid.layout.control import place_control
        from pandid.layout.coarse import (has_free_station, place_equipment_first,
                                          place_inline_equipment_first)
        from pandid.layout.coordinates import assign_coordinates, assign_labels
        from pandid.layout.cycles import break_cycles
        from pandid.layout.faces import select_faces
        from pandid.layout.inline import place_inline
        from pandid.layout.station import place_stations
        from pandid.layout.place import assign_positions

        _seed_slots(fs)
        break_cycles(fs)
        station_coarse = use_coarse and place_equipment_first(
            fs, reservation=reservation, directional=directional_station
        )
        inline_coarse = False
        if (use_coarse and not station_coarse and not has_free_station(fs)
                and any(stream._logical_to is not None for stream in fs.streams)):
            inline_coarse = place_inline_equipment_first(fs, reservation=reservation)
        fs._coarse_layout_candidate = station_coarse or inline_coarse
        if not fs._coarse_layout_candidate:
            _seed_slots(fs)
            assign_positions(fs)
            assign_coordinates(fs, row_compaction=row_compaction, unaligned=unaligned)
            place_stations(fs)
            place_inline(fs)
        elif not inline_coarse:
            place_inline(fs)
        # Repeat face selection and control placement until no balloon moves,
        # up to the pass limit.
        for _ in range(MAX_PLACEMENT_PASSES):
            select_faces(fs)
            if not place_control(fs):
                break
        assign_labels(fs)


default_layout_engine = ConstraintLayoutEngine()
