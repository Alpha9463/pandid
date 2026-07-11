"""Phase 3/4: Coordinate Assignment.

Maps each unit's grid rank (``_slot.col``/``_slot.row``) to absolute pixel
coordinates, honoring any pinned ``x``/``y``, then emits the resolved
:class:`~pfd.geometry.Frame` the router and renderer consume.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

X_GAP = 150
Y_GAP = 120
MARGIN_X = 50
MARGIN_Y = 50


def assign_coordinates(fs: "Flowsheet") -> None:
    """Map (col, row) ranks to absolute (x, y) pixel coordinates and emit frames."""
    from pfd.geometry import Frame
    from pfd.render.symbols import default_registry
    from pfd.portgeom import outward_dir

    # Max resolved width of units in each column (widths already on the slot).
    col_widths: dict[int, float] = {}
    for u in fs.units:
        col = u._slot.col or 0
        col_widths[col] = max(col_widths.get(col, 0.0), u._slot.w)

    # Compute X start coordinates for each column.
    x_pos: dict[int, float] = {}
    curr_x = MARGIN_X
    for col in sorted(col_widths.keys()):
        x_pos[col] = curr_x
        curr_x += col_widths[col] + 100.0  # 100px routing gap minimum

    unpinned_y = set()
    for u in fs.units:
        s = u._slot
        # If the user pinned x / y, keep them; otherwise derive from the grid.
        if s.x is None:
            s.x = x_pos.get(s.col or 0, MARGIN_X)
        if s.y is None:
            s.y = MARGIN_Y + (s.row or 0) * Y_GAP
            unpinned_y.add(u)

    # Post-pass: align single-stream terminals (Feed/Product) with their target
    # so the connecting stream is a clean L rather than a Z.
    for u in unpinned_y:
        s = u._slot
        connected = [st for st in fs.streams if st.source.owner is u or st.dest.owner is u]
        if len(connected) != 1:
            continue

        st = connected[0]
        if st.source.owner is u:
            my_port, other_port = st.source, st.dest
        else:
            my_port, other_port = st.dest, st.source

        other_u = other_port.owner
        assert other_u is not None and other_u._slot is not None

        sym_u = default_registry.get(u.kind)
        sym_other = default_registry.get(other_u.kind)

        my_py = sym_u.ports.get(my_port.name, (0, 0))[1]
        other_px, other_py = sym_other.ports.get(other_port.name, (0, 0))
        out_dir = outward_dir(other_px, other_py, sym_other.width, sym_other.height,
                              other_u.kind, other_port.name)

        # Target absolute Y of the other port; if it faces N/S the stream escapes
        # via the margin lane, so align to that lane instead of the raw port.
        target_abs_y = other_u._slot.y + other_py
        if out_dir == "N":
            target_abs_y = other_u._slot.y - 15.0
        elif out_dir == "S":
            target_abs_y = other_u._slot.y + sym_other.height + 15.0

        new_y = target_abs_y - my_py

        # Don't overlap another unit in the same column.
        overlap = False
        for other_unit in fs.units:
            if other_unit is u or other_unit._slot is None:
                continue
            if other_unit._slot.col != s.col:
                continue
            oy, oh = other_unit._slot.y, other_unit._slot.h
            if oy is None:
                continue
            if not (new_y + s.h <= oy or new_y >= oy + oh):
                overlap = True
                break

        if not overlap:
            s.y = new_y

    # Emit the resolved frame for every unit.
    for u in fs.units:
        s = u._slot
        u.frame = Frame(
            x=s.x, y=s.y, w=s.w, h=s.h,
            col=s.col, row=s.row,
            orientation=s.orientation, mirrored=s.mirrored,
        )
