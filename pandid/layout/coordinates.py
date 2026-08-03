"""Phase 3/4: Coordinate Assignment.

Maps each unit's grid rank (``_slot.col``/``_slot.row``) to absolute
pixel coordinates, honoring any pinned ``x``/``y``, then emits the
resolved :class:`~pandid.geometry.Frame` the router and renderer
consume.

:func:`assign_labels` closes the run but is a separate phase the engine
calls after :mod:`pandid.layout.faces` has chosen the movable ports'
faces, since a label dodges the faces the nozzles actually leave from.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

X_GAP = 150
Y_GAP = 120
ROW_GAP = 70   # gap between row bands, over the taller row
MARGIN_X = 50
MARGIN_Y = 50


def assign_coordinates(fs: "Flowsheet") -> None:
    """Map (col, row) ranks to pixel coordinates and emit frames."""
    from pandid.geometry import Frame
    from pandid.layout.attach import free_streams, free_units, place_attached
    from pandid.portgeom import resolve_port

    units = free_units(fs)
    streams = free_streams(fs)

    # Max resolved width of units in each column (widths already on the
    # slot).
    col_widths: dict[int, float] = {}
    for u in units:
        col = u._slot.col or 0
        col_widths[col] = max(col_widths.get(col, 0.0), u._slot.w)

    # Compute X start coordinates for each column.
    x_pos: dict[int, float] = {}
    curr_x: float = MARGIN_X
    for col in sorted(col_widths.keys()):
        x_pos[col] = curr_x
        curr_x += col_widths[col] + 100.0  # 100px routing gap minimum

    # Center each row's units on a common horizontal flow axis (rather
    # than top-aligning), so equipment of different heights lines up on
    # one spine: a short mixer and a tall column share a centerline,
    # minimizing the vertical jog between their connecting ports.
    max_row = max((u._slot.row or 0 for u in units if u._slot.y is None), default=-1)
    # Empty rows keep a default band.
    row_height: dict[int, float] = {r: 50.0 for r in range(max_row + 1)}
    for u in units:
        if u._slot.y is None:
            r = u._slot.row or 0
            row_height[r] = max(row_height[r], u._slot.h)
    row_axis: dict[int, float] = {}
    cursor: float = MARGIN_Y
    for r in range(max_row + 1):
        row_axis[r] = cursor + row_height[r] / 2.0
        cursor += row_height[r] + ROW_GAP

    unpinned_y = set()
    for u in units:
        s = u._slot
        # If the user pinned x / y, keep them; otherwise derive from the
        # grid.
        if s.x is None:
            s.x = x_pos.get(s.col or 0, MARGIN_X)
        if s.y is None:
            s.y = row_axis[s.row or 0] - s.h / 2.0
            unpinned_y.add(u)

    # Post-pass: straighten the process spine. Walk units left-to-right
    # and, where a unit has a single horizontal process connection to a
    # neighbour in another column, shift it vertically so the two ports
    # share an absolute height, turning staircase jogs into straight
    # runs (and clean L's for single-stream Feed/Product terminals).
    # Anything that would overlap a neighbour in the same column is left
    # on the row axis. The slot carries the same box the Frame will
    # (size and transform), so the port resolver answers here exactly as
    # it will once the frames are emitted. That is the point: a target
    # read off the symbol instead ignores the resize, the mirror and any
    # nozzle() choice, and aims at the wrong height.
    def _target_y(other_u, other_port):
        """Absolute Y to aim a run at, honouring N/S escape lanes."""
        s = other_u._slot
        (_, py), _, d = resolve_port(other_u, s, other_port.name)
        if d == "N":
            return s.y - 15.0
        if d == "S":
            return s.y + s.h + 15.0
        return py

    def _overlaps(u, s, new_y):
        for other in units:
            if other is u or other._slot is None or other._slot.col != s.col:
                continue
            oy, oh = other._slot.y, other._slot.h
            if oy is not None and not (new_y + s.h <= oy or new_y >= oy + oh):
                return True
        return False

    for u in sorted(unpinned_y, key=lambda v: (v._slot.col or 0, v._slot.y)):
        s = u._slot
        ups: list = []
        downs: list = []
        for st in streams:
            if st.is_recycle or st.kind != "material":
                continue
            if st.dest.owner is u and st.source.owner is not None:
                pair = (st.dest, st.source.owner, st.source)
            elif st.source.owner is u and st.dest.owner is not None:
                pair = (st.source, st.dest.owner, st.dest)
            else:
                continue
            bucket = ups if (pair[1]._slot.col or 0) < (s.col or 0) else downs
            bucket.append(pair)
        # A single upstream anchor chains the spine; fall back to a
        # single downstream one so terminals (Feed) still align.
        anchor = ups[0] if len(ups) == 1 else (downs[0] if not ups and len(downs) == 1 else None)
        if anchor is None:
            continue
        my_port, other_u, other_port = anchor
        if other_u._slot is None or other_u._slot.y is None:
            continue
        # Only straighten horizontal runs: the port must face the
        # neighbour sideways (E/W); vertical ports keep the row axis.
        (_, my_y), _, my_d = resolve_port(u, s, my_port.name)
        if my_d not in ("E", "W"):
            continue
        new_y = _target_y(other_u, other_port) - (my_y - s.y)
        if not _overlaps(u, s, new_y):
            s.y = new_y

    # The same post-pass across the other axis, for the runs the one
    # above cannot straighten: a unit stacked over or under its peer by
    # a north/south face (see pandid.layout.stacking), whose own nozzle
    # points sideways. Ranking has put the two in one column, which is
    # not the same as putting the nozzles in one line, and 10px out is
    # enough for a run to leave east, drop, and come back west. Aim the
    # leaving nozzle a stand-off short of the arriving one and that
    # becomes one turn.
    for u, s, new_x in _stack_offsets(fs, units):
        if not _overlaps_x(u, s, new_x, units):
            s.x = new_x

    # Emit the resolved frame for every ranked unit; attached
    # instruments take theirs from their host instead.
    for u in units:
        s = u._slot
        u.frame = Frame(
            x=s.x, y=s.y, w=s.w, h=s.h,
            col=s.col, row=s.row,
            orientation=s.orientation, mirrored=s.mirrored, mirror_y=s.mirror_y,
        )

    place_attached(fs)


#: How far short of the nozzle it drops onto a sideways-facing one is
#: aimed. The router stands a run off a nozzle before it may turn, so
#: aiming dead on costs a turn out and a turn back; this is that
#: stand-off, spent going the way the run was already going.
STACK_LEAD = 25.0


def _stack_offsets(fs: "Flowsheet", units: list) -> list[tuple]:
    """``(unit, slot, x)`` for every stacked unit worth shifting.

    Only a nozzle facing sideways is aimed: one already facing the peer
    it is stacked against drops straight onto it, and moving the box
    would be the thing that bent the run.
    """
    from pandid.layout.stacking import stacked_edges
    from pandid.portgeom import resolve_port

    out = []
    for st in stacked_edges(fs):
        u, peer = st.satellite, st.anchor
        if u not in units or peer not in units:
            continue
        s, p = u._slot, peer._slot
        if s is None or p is None or s.x is None:
            continue
        if u.pin_ is not None and u.pin_.x is not None:
            continue
        mine = st.stream.source if st.stream.source.owner is u else st.stream.dest
        theirs = st.stream.dest if mine is st.stream.source else st.stream.source
        (my_x, _), _, face = resolve_port(u, s, mine.name)
        if face not in ("E", "W"):
            continue
        (their_x, _), _, _ = resolve_port(peer, p, theirs.name)
        lead = STACK_LEAD if face == "E" else -STACK_LEAD
        out.append((u, s, their_x - lead - (my_x - s.x)))
    return out


def _overlaps_x(u, s, new_x: float, units: list) -> bool:
    """Would moving ``u`` to ``new_x`` put it over a unit beside it?"""
    for other in units:
        o = other._slot
        if other is u or o is None or o.x is None or o.y is None:
            continue
        if s.y + s.h <= o.y or s.y >= o.y + o.h:
            continue
        if not (new_x + s.w <= o.x or new_x >= o.x + o.w):
            return True
    return False


_DIR_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}
#: Label sides in the order a sheet prefers them, best first.
LABEL_SIDES = ("top", "bottom", "right", "left")


def free_label_sides(u) -> list[str]:
    """The sides of a box no connected nozzle leaves, best first.

    Read off :mod:`pandid.portgeom`, so the faces this reports free are
    the faces the router and the renderer will actually see empty. The
    renderer asks the same question again once the sheet is routed,
    because a face free of nozzles can still have a passing line or an
    impulse line across it, and neither of those exists yet while layout
    runs. This is the half of the answer that does: a nozzle is
    geometry, and geometry is settled here.
    """
    from pandid.portgeom import port_anchor

    if u.frame is None:
        return []
    occupied = set()
    for name, port in u.ports.items():
        if port.stream is None:
            continue
        _, _, d = port_anchor(u, u.frame, name)
        occupied.add(d)
    return [side for side in LABEL_SIDES if _DIR_OF_SIDE[side] not in occupied]


def assign_labels(fs: "Flowsheet") -> None:
    """Resolve each label side, avoiding faces a live port holds.

    Explicit user ``label_pos`` or a symbol default wins; otherwise the
    label goes to the first free face in top → bottom → right → left
    order, so a stream leaving (say) a pump's top nozzle does not run
    through its label.
    """
    from pandid.render.symbols import default_registry

    for u in fs.units:
        if u.kind in ("feed", "product") or u.frame is None:
            continue  # labels are drawn inline on the arrow
        explicit = getattr(u, "label_pos", None)
        if explicit:
            u.frame.label_pos = explicit
            continue
        sym = default_registry.get(u.kind, getattr(u, "variant", "default"))
        if sym.label_pos:
            u.frame.label_pos = sym.label_pos
            continue
        free = free_label_sides(u)
        u.frame.label_pos = free[0] if free else "top"
