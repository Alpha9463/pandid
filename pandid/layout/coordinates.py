"""Convert process grid positions to pixels, band by band.

A unit's position is ``(band, column, row)``. Columns and rows come from
:mod:`pandid.layout.place`; bands are chosen here from the paper width. A
band boundary is part of the position: cutting a solved ribbon afterwards
would make streams across the cut run against their nozzle faces.

:func:`assign_labels` runs as a separate phase after
:mod:`pandid.layout.faces`, because a label avoids the faces nozzles use.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from pandid.layout.halo import Pad
from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import _Slot
    from pandid.layout.coarse import Host
    from pandid.ports import Port
    from pandid.units import Unit

#: Clear width between adjacent columns. It holds the connecting run and its
#: line number (ISO 15519-1 §7.2.5); the longest corpus number needs just
#: under 100 px.
COL_GAP = 120.0
#: Clear height between adjacent rows, measured from the taller row.
ROW_GAP = 70
#: Left and top sheet margins.
MARGIN_X = 50
MARGIN_Y = 50

#: Clear height between adjacent bands, wide enough for a lane in which a
#: folded run turns.
BAND_GAP = 160.0

#: Maximum band width before the ribbon folds: about the width of an A1
#: sheet at 96 dpi. It is a width and not an aspect ratio, so a long, small
#: sheet is not folded (#429).
BAND_WIDTH = 3200.0


def assign_coordinates(fs: "Flowsheet", *, units: list["Unit"] | None = None,
                       extra_gap: dict[int, float] | None = None,
                       links: list[tuple["Unit", "Unit", float]] | None = None,
                       hosts: list["Host"] | None = None,
                       row_compaction: float = 0.0,
                       unaligned: frozenset[int] = frozenset()) -> None:
    """Map selected process-unit grid ranks to pixels.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing the process units.
    units : list[Unit] or None
        Units to coordinate, or every process unit by default.
    extra_gap : dict[int, float] or None
        Additional paper reserved after each grid column.
    links : list[tuple[Unit, Unit, float]] or None
        Contracted connections used when resolving absolute pins.
    hosts : list[Host] or None
        Contracted runs whose endpoint nozzles guide pixel alignment.
    row_compaction : float, optional
        Fraction of independent column-row compaction to apply.
    unaligned : frozenset[int], optional
        Global indices of units kept on their row axis.

    Returns
    -------
    None
        Frames are assigned to the selected units.
    """
    from pandid.geometry import Frame
    from pandid.layout.halo import balloon_pads
    from pandid.layout.pixel import clear_pins, refine
    from pandid.layout.stages import process_units

    if units is None:
        units = process_units(fs)
    if not units:
        return
    pads = balloon_pads(fs)
    columns = _columns(units, pads)
    bands = _bands(units, columns, pads, _wrappable(fs, units), extra_gap, hosts)
    band_of = {u: b for b, group in enumerate(bands) for c in group for u in columns[c].units}

    cursor = float(MARGIN_Y)
    for index, group in enumerate(bands):
        cursor = _lay_band(columns, group, cursor, pads, anchored=not index,
                           extra_gap=extra_gap, row_compaction=row_compaction)

    moved: dict[str, list["Unit"]] = {}
    if not _wrappable(fs, units):
        nominal = {u: replace(slot(u), x=None, y=None) for u in units}
        cursor = float(MARGIN_Y)
        for index, group in enumerate(bands):
            cursor = _lay_band(columns, group, cursor, pads, anchored=not index,
                               positions=nominal, extra_gap=extra_gap,
                               row_compaction=row_compaction)
        reference = {u: (s.x or 0.0, s.y or 0.0) for u, s in nominal.items()}
        moved = refine(fs, units, reference, links)

    _straighten(fs, units, band_of, pads, hosts, unaligned)
    if moved:
        clear_pins(units, moved, STACK_CLEAR, pads)
    for u in units:
        s = slot(u)
        u.frame = Frame(x=s.x or 0.0, y=s.y or 0.0, w=s.w, h=s.h,
                        col=s.col, row=s.row,
                        orientation=s.orientation, mirrored=s.mirrored,
                        mirror_y=s.mirror_y)


# ---------------------------------------------------------------------------
# Columns and bands
# ---------------------------------------------------------------------------


class _Column:
    """Hold the units of one grid column and the width they need.

    Attributes
    ----------
    units : list[Unit]
        Units placed in the column.
    lead : float
        Clearance attached objects need on the west.
    body : float
        Width of the widest unit.
    tail : float
        Clearance attached objects need on the east.
    """

    def __init__(self) -> None:
        """Create an empty column."""
        self.units: list["Unit"] = []
        self.lead = 0.0
        self.body = 0.0
        self.tail = 0.0

    @property
    def span(self) -> float:
        """Return the total width the column needs.

        Returns
        -------
        float
            Sum of the west clearance, body width, and east clearance.
        """
        return self.lead + self.body + self.tail


#: Distance from a boundary flag's frame origin to its nozzle. The flag
#: extends west from the nozzle; see :func:`~pandid.portgeom.unit_box`.
_FLAG_LEAD = 50.0


def _west(u: "Unit", pads: dict["Unit", Pad]) -> float:
    """Return the clearance a unit needs on its west side.

    A boundary flag extends west of its frame origin as its label grows.

    Parameters
    ----------
    u : Unit
        Unit to measure.
    pads : dict[Unit, Pad]
        Attached-object clearance around each unit.

    Returns
    -------
    float
        Clearance in pixels, including a flag's westward body.
    """
    west = pads.get(u, Pad()).west
    if u.kind == "feed" and not slot(u).mirrored:
        west = max(west, slot(u).w - _FLAG_LEAD)
    return west


def _columns(units: list["Unit"], pads: dict["Unit", Pad]) -> dict[int, _Column]:
    """Group units into grid columns and measure each column.

    Parameters
    ----------
    units : list[Unit]
        Process units with seeded grid columns.
    pads : dict[Unit, Pad]
        Attached-object clearance around each unit.

    Returns
    -------
    dict[int, _Column]
        Columns keyed by grid column number.
    """
    out: dict[int, _Column] = defaultdict(_Column)
    for u in units:
        column = out[slot(u).col or 0]
        column.units.append(u)
        column.lead = max(column.lead, _west(u, pads))
        column.body = max(column.body, slot(u).w)
        column.tail = max(column.tail, pads.get(u, Pad()).east)
    return dict(out)


def _wrappable(fs: "Flowsheet", units: list["Unit"]) -> bool:
    """Return whether the sheet may be folded into bands.

    A sheet with an absolute pin is not folded; a band could land on the
    pinned unit.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being laid out.
    units : list[Unit]
        Process units to inspect.

    Returns
    -------
    bool
        Whether no unit is pinned to an absolute x or y.
    """
    return not any(u.pin_ is not None and (u.pin_.x is not None or u.pin_.y is not None)
                   for u in units)


def _bands(units: list["Unit"], columns: dict[int, _Column],
           pads: dict["Unit", Pad], wrappable: bool,
           extra_gap: dict[int, float] | None = None,
           hosts: list["Host"] | None = None) -> list[list[int]]:
    """Partition grid columns into bands within the paper width.

    Parameters
    ----------
    units : list[Unit]
        Process units used to score fold boundaries.
    columns : dict[int, _Column]
        Occupied grid columns.
    pads : dict[Unit, Pad]
        Attached label and balloon clearance around each unit.
    wrappable : bool
        Whether the drawing may use multiple bands.
    extra_gap : dict[int, float] or None
        Additional width reserved after each column.
    hosts : list[Host] or None
        Contracted runs whose attachments should stay within one band.

    Returns
    -------
    list[list[int]]
        Ordered column numbers in each band.
    """
    order = sorted(columns)
    if not wrappable or _lay_columns(columns, order, pads, extra_gap=extra_gap) <= BAND_WIDTH:
        return [order]

    crossings = _seam_cost(units)
    protected: set[int] = set()
    for host in hosts or []:
        source, dest = host.source.owner, host.dest.owner
        assert source is not None and dest is not None
        left, right = slot(source).col, slot(dest).col
        assert left is not None and right is not None
        low, high = sorted((left, right))
        protected.update(column for column in order if low <= column < high)
    bands: list[list[int]] = []
    first = 0
    while first < len(order):
        end = first + 1
        while end < len(order) and _lay_columns(
            columns, order[first:end + 1], pads, extra_gap=extra_gap
        ) <= BAND_WIDTH:
            end += 1
        if end == len(order):
            bands.append(order[first:end])
            break
        band = _slide(order[first:end], crossings, protected)
        bands.append(band)
        first += len(band)
    return bands


def _seam_cost(units: list["Unit"]) -> dict[int, int]:
    """Count the connections that cross the gap after each column.

    Parameters
    ----------
    units : list[Unit]
        Process units with seeded grid columns.

    Returns
    -------
    dict[int, int]
        Crossing count keyed by the column before the gap.
    """
    where = {u: (slot(u).col or 0) for u in units}
    cost: dict[int, int] = defaultdict(int)
    for u in units:
        for port in u.ports.values():
            stream = port.stream
            if stream is None:
                continue
            peer = stream.dest.owner if stream.source.owner is u else stream.source.owner
            if peer is None or peer not in where:
                continue
            lo, hi = sorted((where[u], where[peer]))
            for column in range(lo, hi):
                cost[column] += 1
    return cost


def _slide(band: list[int], crossings: dict[int, int],
           protected: set[int] | None = None) -> list[int]:
    """Pull a band's last column back to the quietest seam near it.

    The search covers at most the last quarter of the band.

    Parameters
    ----------
    band : list[int]
        Candidate columns in the current band.
    crossings : dict[int, int]
        Material connections crossing each possible seam.
    protected : set[int] or None
        Seams inside contracted attachment runs.

    Returns
    -------
    list[int]
        Prefix ending at the preferred fold seam.
    """
    reach = max(1, len(band) // 4)
    protected = protected or set()
    best = min(range(len(band) - reach, len(band)),
               key=lambda i: (band[i] in protected,
                              crossings.get(band[i], 0), len(band) - 1 - i))
    return band[:best + 1]


# ---------------------------------------------------------------------------
# One band's pixels
# ---------------------------------------------------------------------------


def _lay_columns(columns: dict[int, _Column], band: list[int],
                 pads: dict["Unit", Pad], place: bool = False,
                 positions: dict["Unit", "_Slot"] | None = None,
                 extra_gap: dict[int, float] | None = None) -> float:
    """Measure a column band and optionally assign horizontal positions.

    Parameters
    ----------
    columns : dict[int, _Column]
        Occupied grid columns.
    band : list[int]
        Columns to measure or place.
    pads : dict[Unit, Pad]
        Attached-object clearance around each unit.
    place : bool
        Assign horizontal coordinates when true.
    positions : dict[Unit, _Slot] or None
        Alternate slots receiving assigned coordinates.
    extra_gap : dict[int, float] or None
        Additional width reserved after each column.

    Returns
    -------
    float
        Width of the band in pixels.
    """
    # Start the first column on the margin; a boundary flag there extends
    # into the margin.
    position = slot if positions is None else positions.__getitem__
    wall: dict[int, float] = {}
    cursor = float(MARGIN_X)
    for column in band:
        held = columns[column]
        x = cursor
        for u in held.units:
            behind = wall.get(position(u).row or 0)
            if behind is not None:
                x = max(x, behind + _west(u, pads))
        if place:
            for u in held.units:
                if position(u).x is None:
                    position(u).x = x
        cursor = x + held.body + COL_GAP + (extra_gap or {}).get(column, 0.0)
        for u in held.units:
            row = position(u).row or 0
            wall[row] = max(wall.get(row, 0.0),
                            x + position(u).w + pads.get(u, Pad()).east)
    return max([cursor - COL_GAP, *wall.values()], default=cursor) - MARGIN_X


def _lay_band(columns: dict[int, _Column], band: list[int], top: float,
              pads: dict["Unit", Pad], anchored: bool,
              positions: dict["Unit", "_Slot"] | None = None,
              extra_gap: dict[int, float] | None = None,
              row_compaction: float = 0.0) -> float:
    """Place the units of one band.

    Parameters
    ----------
    columns : dict[int, _Column]
        Occupied grid columns.
    band : list[int]
        Columns in this band.
    top : float
        Vertical starting coordinate.
    pads : dict[Unit, Pad]
        Attached-object clearance around each unit.
    anchored : bool
        Keep empty rows before the first occupied row when true.
    positions : dict[Unit, _Slot] or None
        Alternate slots receiving assigned coordinates.
    extra_gap : dict[int, float] or None
        Additional width reserved after each column.
    row_compaction : float, optional
        Fraction of the unused vertical row space to recover per column.

    Returns
    -------
    float
        Vertical starting coordinate for the next band.
    """
    position = slot if positions is None else positions.__getitem__
    members = [u for c in band for u in columns[c].units]
    if not members:
        return top

    _lay_columns(columns, band, pads, place=True, positions=positions,
                 extra_gap=extra_gap)

    # Build every row between the band's first and last, including pinned
    # rows above row 0. An empty row keeps a default height for a lane.
    banded = [position(u).row or 0 for u in members if position(u).y is None]
    if not banded:
        return top
    # Anchor the first band at row 0 so ``pin(row=2)`` keeps two empty rows
    # above it. Later bands start from their own first row.
    floor_row = min([*banded, 0]) if anchored else min(banded)
    rows = list(range(floor_row, max(banded) + 1))
    body = dict.fromkeys(rows, 50.0)  # Height of the tallest unit in each row.
    holds: dict[int, list["Unit"]] = {r: [] for r in rows}
    for u in members:
        if position(u).y is None:
            row = position(u).row or 0
            holds[row].append(u)
            body[row] = max(body[row], position(u).h)

    # Reserve attached-object clearance per column, not per row. ``floor``
    # records how far down each column is already occupied.
    floor: dict[int, float] = {}
    axis: dict[int, float] = {}
    cursor_y = top
    for index, row in enumerate(rows):
        if index:
            cursor_y += body[rows[index - 1]] + ROW_GAP
        here = cursor_y + body[row] / 2.0
        for u in holds[row]:
            pad = pads.get(u, Pad())
            here = max(here, floor.get(position(u).col or 0, top)
                       + pad.north + position(u).h / 2.0)
        axis[row] = here
        cursor_y = here - body[row] / 2.0
        for u in holds[row]:
            col, pad = position(u).col or 0, pads.get(u, Pad())
            floor[col] = max(floor.get(col, top),
                             here + position(u).h / 2.0 + pad.south)
    for u in members:
        if position(u).y is None:
            position(u).y = axis[position(u).row or 0] - position(u).h / 2.0
    next_top = max([cursor_y + body[rows[-1]], *floor.values()], default=top) + BAND_GAP
    if row_compaction:
        compacted_top = _compact_column_rows(columns, band, top, pads, position,
                                              row_compaction)
        return min(next_top, compacted_top)
    return next_top


def _compact_column_rows(columns: dict[int, _Column], band: list[int], top: float,
                         pads: dict["Unit", Pad], position: Callable[["Unit"], "_Slot"],
                         fraction: float) -> float:
    """Recover row space that no unit in a column reserves.

    Parameters
    ----------
    columns : dict[int, _Column]
        Occupied grid columns.
    band : list[int]
        Columns in the current paper band.
    top : float
        Start of the paper band.
    pads : dict[Unit, Pad]
        Per-unit clearances for attached controls and labels.
    position : callable
        Slot lookup for the current coordinate assignment.
    fraction : float
        Share of the available vertical slack to remove.

    Returns
    -------
    float
        Start of the next band after the compacted columns.
    """
    end = top
    for column in band:
        ordered = sorted(columns[column].units,
                         key=lambda unit: (position(unit).row or 0, position(unit).y or 0.0))
        floor = top
        for unit in ordered:
            placed = position(unit)
            pad = pads.get(unit, Pad())
            if placed.y is None:
                continue
            if unit.pin_ is None or (unit.pin_.y is None and unit.pin_.row is None):
                proposed = max(top + pad.north, floor + pad.north)
                placed.y += fraction * (proposed - placed.y)
            floor = max(floor, placed.y + placed.h + pad.south + ROW_GAP)
        end = max(end, floor)
    return end + BAND_GAP


# ---------------------------------------------------------------------------
# Straightening
# ---------------------------------------------------------------------------

#: Router stand-off reserved when a unit is aligned with a vertical nozzle.
STACK_LEAD = 25.0


def _target_y(other_u: Unit, other_port: Port, contracted: bool) -> float:
    """Aim at a neighbour's nozzle or its vertical exit lane.

    Parameters
    ----------
    other_u : Unit
        Equipment providing the alignment target.
    other_port : Port
        Connected nozzle on that equipment.
    contracted : bool
        Reserve a full router exit for a contracted host run.

    Returns
    -------
    float
        Absolute height of the horizontal connection leg.
    """
    from pandid.portgeom import resolve_port

    s = slot(other_u)
    (_, py), _, direction = resolve_port(other_u, s, other_port.name)
    clearance = STACK_LEAD if contracted else 15.0
    if direction == "N":
        return (s.y or 0.0) - clearance
    if direction == "S":
        return (s.y or 0.0) + s.h + clearance
    return py


def _straighten(fs: "Flowsheet", units: list["Unit"], band_of: dict["Unit", int],
                pads: dict["Unit", Pad], hosts: list["Host"] | None = None,
                unaligned: frozenset[int] = frozenset()) -> None:
    """Shift units vertically so horizontal runs become straight.

    Units are visited left to right. A unit with exactly one upstream peer,
    or no upstream peer and exactly one downstream peer, is shifted so its
    sideways port shares the peer's height. A peer in another band is
    ignored. A stack moves as one group. A shift is rejected when it breaks
    grid-row order or overlaps a neighbour's padded box.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose material connections guide alignment.
    units : list[Unit]
        Equipment eligible for pixel adjustment.
    band_of : dict[Unit, int]
        Paper band assigned to each unit.
    pads : dict[Unit, Pad]
        Reserved clearance around equipment.
    hosts : list[Host] or None
        Contracted material runs between retained equipment.
    unaligned : frozenset[int], optional
        Global indices of units kept on their row axis.

    Returns
    -------
    None
        Eligible slots receive adjusted coordinates.
    """
    from pandid.layout import claims as claims_mod
    from pandid.layout.pixel import grid_limits, occupied_box
    from pandid.layout.stages import process_streams
    from pandid.portgeom import resolve_port

    # Index units by column and connections by unit once.
    by_col: dict[int | None, list["Unit"]] = defaultdict(list)
    for u in units:
        by_col[slot(u).col].append(u)

    touching: dict["Unit", list] = defaultdict(list)
    for st in process_streams(fs):
        if st.is_recycle:
            continue
        src, dst = st.source.owner, st.dest.owner
        assert src is not None and dst is not None
        touching[dst].append((st.dest, src, st.source, False))
        if src is not dst:
            touching[src].append((st.source, dst, st.dest, False))
    for host in hosts or []:
        dest = host.dest
        src = host.source.owner
        assert src is not None and dest is not None and dest.owner is not None
        touching[dest.owner].append((dest, src, host.source, True))
        touching[src].append((host.source, dest.owner, dest, True))

    boxes = {u: occupied_box(u, pads) for u in units}
    pixel_pins = not _wrappable(fs, units)

    def overlaps(u: "Unit", new_y: float, moving: set["Unit"]) -> bool:
        """Return whether a vertical shift is illegal.

        Boxes include the clearance reserved for attached objects.

        Parameters
        ----------
        u : Unit
            Unit to move.
        new_y : float
            Proposed top coordinate.
        moving : set[Unit]
            Units shifting together, which do not block each other.

        Returns
        -------
        bool
            Whether the shift breaks grid-row order or overlaps a neighbour.
        """
        lower, upper = grid_limits(u, "y", boxes, moving=moving)
        if not lower <= new_y <= upper:
            return True
        s, pad = slot(u), pads.get(u, Pad())
        top, bottom = new_y - pad.north, new_y + s.h + pad.south
        for other in units if pixel_pins else by_col[s.col]:
            o, o_pad = slot(other), pads.get(other, Pad())
            if other is u or other in moving or o.y is None:
                continue
            if pixel_pins and (boxes[u][2] <= boxes[other][0]
                               or boxes[u][0] >= boxes[other][2]):
                continue
            if not (bottom <= o.y - o_pad.north or top >= o.y + o.h + o_pad.south):
                return True
        return False

    stack_of = claims_mod.stacks(fs, units)
    stacked: dict["Unit", list["Unit"]] = defaultdict(list)
    for u in units:
        stacked[stack_of[u]].append(u)

    held = {fs.units[index] for index in unaligned}
    settled: set["Unit"] = set()
    for u in sorted(units, key=lambda v: (slot(v).col or 0, slot(v).y or 0.0)):
        s = slot(u)
        if u in settled or s.y is None:
            continue
        group = stacked[stack_of[u]]
        if any(v.pin_ is not None and v.pin_.y is not None for v in group):
            continue
        if held.intersection(group):
            continue
        ups: list[tuple] = []
        downs: list[tuple] = []
        for pair in touching[u]:
            if band_of.get(pair[1]) != band_of.get(u) or pair[1] in group:
                continue
            (ups if (pair[1]._slot.col or 0) < (s.col or 0) else downs).append(pair)
        # Use a single upstream anchor, else a single downstream one.
        anchor = ups[0] if len(ups) == 1 else (downs[0] if not ups and len(downs) == 1 else None)
        if anchor is None:
            continue
        my_port, other_u, other_port, contracted = anchor
        if slot(other_u).y is None:
            continue
        # Straighten only a port that faces east or west.
        (_, my_y), _, my_d = resolve_port(u, s, my_port.name)
        if my_d not in ("E", "W"):
            continue
        shift = _target_y(other_u, other_port, contracted) - my_y
        riding = set(group)
        if any(overlaps(v, (slot(v).y or 0.0) + shift, riding) for v in group):
            continue
        for v in group:
            slot(v).y = (slot(v).y or 0.0) + shift
            boxes[v] = occupied_box(v, pads)
        settled.update(group)

    for u, new_x in _stack_offsets(fs, units, band_of):
        lower, upper = grid_limits(u, "x", boxes)
        if lower <= new_x <= upper and not _overlaps_x(u, new_x, units):
            slot(u).x = new_x
            boxes[u] = occupied_box(u, pads)


def _stack_offsets(fs: "Flowsheet", units: list["Unit"],
                   band_of: dict["Unit", int]) -> list[tuple["Unit", float]]:
    """Propose same-column nozzle alignment for safe process units.

    Parameters
    ----------
    fs : Flowsheet
        Sheet supplying material connections.
    units : list[Unit]
        Equipment eligible for pixel adjustment.
    band_of : dict[Unit, int]
        Paper band assigned to each unit.

    Returns
    -------
    list[tuple[Unit, float]]
        Unit and proposed left coordinate, before pin and overlap checks.
    """
    from pandid.layout.claims import fixed_face
    from pandid.layout.stages import process_streams
    from pandid.portgeom import resolve_port

    placed = set(units)
    out: list[tuple["Unit", float]] = []
    streams = process_streams(fs)
    degree: dict["Unit", int] = defaultdict(int)
    for stream in streams:
        degree[stream.source.owner] += 1
        if stream.dest.owner is not stream.source.owner:
            degree[stream.dest.owner] += 1
    for st in streams:
        src, dst = st.source.owner, st.dest.owner
        assert src is not None and dst is not None
        if st.is_recycle or src is dst or src not in placed or dst not in placed:
            continue
        if (slot(src).col or 0) != (slot(dst).col or 0) or band_of.get(src) != band_of.get(dst):
            continue
        for mine, theirs, u, peer in ((st.source, st.dest, src, dst),
                                      (st.dest, st.source, dst, src)):
            my_x0 = slot(u).x
            if my_x0 is None or (u.pin_ is not None and u.pin_.x is not None):
                continue
            face = fixed_face(u, mine.name, slot(u))
            (my_x, _), _, _ = resolve_port(u, slot(u), mine.name)
            (their_x, _), _, _ = resolve_port(peer, slot(peer), theirs.name)
            if face in ("E", "W"):
                lead = STACK_LEAD if face == "E" else -STACK_LEAD
                out.append((u, their_x - lead - (my_x - my_x0)))
            elif (face in ("N", "S") and u.kind in {"feed", "product", "vent"}
                  and peer.kind not in {"feed", "product", "vent"} and degree[u] == 1
                  and fixed_face(peer, theirs.name, slot(peer)) in ("N", "S")):
                out.append((u, their_x - (my_x - my_x0)))
    return out


#: Clearance a sideways nudge leaves beside the moved unit, enough to draw
#: a run and write its number.
STACK_CLEAR = 40.0


def _overlaps_x(u: "Unit", new_x: float, units: list["Unit"]) -> bool:
    """Return whether a horizontal move crowds a neighbouring unit.

    Parameters
    ----------
    u : Unit
        Unit to move.
    new_x : float
        Proposed left coordinate.
    units : list[Unit]
        Units that may be beside it.

    Returns
    -------
    bool
        Whether a vertically overlapping unit lies within ``STACK_CLEAR``.
    """
    s = slot(u)
    if s.y is None:
        return True
    for other in units:
        o = slot(other)
        if other is u or o.x is None or o.y is None:
            continue
        if s.y + s.h <= o.y or s.y >= o.y + o.h:
            continue
        if not (new_x + s.w + STACK_CLEAR <= o.x or new_x >= o.x + o.w + STACK_CLEAR):
            return True
    return False


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

_DIR_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}
#: Label sides in order of preference.
LABEL_SIDES = ("top", "bottom", "right", "left")


def free_label_sides(u) -> list[str]:
    """Return the sides of a unit that no connected nozzle uses.

    Parameters
    ----------
    u : Unit
        Placed unit.

    Returns
    -------
    list[str]
        Free sides in order of preference; empty for an unplaced unit.
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
    """Choose a label side for every placed unit.

    An explicit ``label_pos`` wins, then the symbol's default, then the
    first side free of connected nozzles.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with placed frames and selected port faces.

    Returns
    -------
    None
        ``label_pos`` is stored on each frame.
    """
    from pandid.render.symbols import default_registry

    for u in fs.units:
        if u.kind in ("feed", "product") or u.frame is None:
            continue  # A boundary flag draws its own label.
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
