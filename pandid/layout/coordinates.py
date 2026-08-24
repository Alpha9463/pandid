"""Stage 1 geometry: grid positions to pixels, band by band.

A unit's position is ``(band, column, row)``. The column and the row
come from :mod:`pandid.layout.place`; the band is decided here, because
it is the one part of the position that is about *paper* rather than
about the process, and paper is the first thing this module knows about.

Why the band cannot be applied afterwards
-----------------------------------------
Cutting a solved ribbon at ``x > W`` and dropping the tail underneath
looks like the cheap way to wrap, and it is wrong by construction: a
stream crossing the cut now runs right to left, so the unit whose *west*
nozzle carries it sits east of its peer -- reintroducing exactly the
inconsistency between geometry and nozzle that the constraint solver
exists to remove. So the band is part of the position and the ribbon is
cut where the drawing has a seam, not where the ruler falls.

:func:`assign_labels` closes the run but is a separate phase the engine
calls after :mod:`pandid.layout.faces` has chosen the movable ports'
faces, since a label dodges the faces the nozzles actually leave from.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pandid.layout.halo import Pad
from pandid.layout.stages import slot

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.units import Unit

#: Clear paper between one column of boxes and the next, which is where
#: the run between them is drawn -- **and where its line number is
#: written**. ISO 15519-1 §7.2.5 puts that number along or beside its
#: own line and sends it away with a leader only where there is no room
#: beside it, so the gap has to be wide enough to be that room: the
#: longest number in the corpus is seventeen characters, a little under
#: 100 px of lettering, and 100 left it nothing either side. At 120 it
#: fits with a margin, and ``350-LG-314-CS`` on 18_fixed_bed_recycle
#: stops being written a lane away from its own run with a leader drawn
#: back across the loop gas line.
#:
#: It belongs with the placement change rather than in a tidying pass of
#: its own, and the reason is that the placement change is what needs
#: it. At 100 ``tests/test_label_invariants.py`` fails twice on this
#: branch and passes on ``main``: the fit puts two boxes a column apart
#: that the engine before it did not, and the run between them is now a
#: run with a thirteen-character number and 100 px to write it in.
COL_GAP = 120.0
ROW_GAP = 70     # gap between row bands, over the taller row
MARGIN_X = 50
MARGIN_Y = 50

#: Clear paper between one band of the ribbon and the one below it. Wide
#: enough that a run turning down at the end of a band and back along
#: the next has a lane of its own to turn in, and that a reader sees two
#: bands rather than one crowded sheet.
BAND_GAP = 160.0

#: How wide a band may get before the ribbon is folded. Chosen as paper:
#: an A1 sheet is 841 mm across, which at the 96 dpi this library draws
#: in is a little over 3170 px, and a drawing wider than the largest
#: sheet anyone hangs on a wall is a drawing nobody reads. Below it a
#: sheet is left exactly as it was -- 16_demineralised_water is a
#: 2436 px water train with an aspect of 6.5 and folding it would be
#: rearranging a drawing that is already right.
#:
#: Deliberately a width and not a target aspect. Aspect cannot tell a
#: long *small* sheet from a long big one, and folding the small one is
#: how a fix for #429 would have broken the sheets it was told not to
#: touch.
BAND_WIDTH = 3200.0


def assign_coordinates(fs: "Flowsheet") -> None:
    """Map every process unit's ``(column, row)`` to pixels."""
    from pandid.geometry import Frame
    from pandid.layout.halo import balloon_pads
    from pandid.layout.stages import process_units

    units = process_units(fs)
    if not units:
        return
    pads = balloon_pads(fs)
    columns = _columns(units, pads)
    bands = _bands(units, columns, pads, _wrappable(fs, units))
    band_of = {u: b for b, group in enumerate(bands) for c in group for u in columns[c].units}

    cursor = float(MARGIN_Y)
    for index, group in enumerate(bands):
        cursor = _lay_band(columns, group, cursor, pads, anchored=not index)

    _straighten(fs, units, band_of, pads)
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
    """One column of the grid, and the paper it claims."""

    def __init__(self) -> None:
        self.units: list["Unit"] = []
        self.lead = 0.0   # clear paper the balloons on its west want
        self.body = 0.0   # the widest box in it
        self.tail = 0.0   # clear paper the balloons on its east want

    @property
    def span(self) -> float:
        return self.lead + self.body + self.tail


#: How far a boundary flag's nozzle stands inside its own frame origin.
#: The flag grows *west* from there as its label does, so a wide label
#: is drawn outside the box the column laid out for it. See
#: :func:`~pandid.portgeom.unit_box`, which is where the convention is.
_FLAG_LEAD = 50.0


def _west(u: "Unit", pads: dict["Unit", Pad]) -> float:
    """Clear paper this unit needs on its west, its own box included.

    A boundary flag is the one unit drawn outside the box the grid laid
    out for it: its nozzle sits a fixed lead inside its own origin and
    the pennant grows *west* from there as the label does (see
    :func:`~pandid.portgeom.unit_box`), so a long tag reaches back into
    whatever the column before it holds.
    """
    west = pads.get(u, Pad()).west
    if u.kind == "feed" and not slot(u).mirrored:
        west = max(west, slot(u).w - _FLAG_LEAD)
    return west


def _columns(units: list["Unit"], pads: dict["Unit", Pad]) -> dict[int, _Column]:
    """Every column the sheet uses, with the width it needs."""
    out: dict[int, _Column] = defaultdict(_Column)
    for u in units:
        column = out[slot(u).col or 0]
        column.units.append(u)
        column.lead = max(column.lead, _west(u, pads))
        column.body = max(column.body, slot(u).w)
        column.tail = max(column.tail, pads.get(u, Pad()).east)
    return dict(out)


def _wrappable(fs: "Flowsheet", units: list["Unit"]) -> bool:
    """May this sheet be folded at all?

    Not where anything is pinned to an absolute coordinate. A band is a
    statement about where the grid goes, and a unit placed at ``x=420``
    is not on the grid: folding around it would drop a band on top of
    equipment the author put somewhere on purpose. An author placing by
    hand has already decided the shape of the sheet.
    """
    return not any(u.pin_ is not None and (u.pin_.x is not None or u.pin_.y is not None)
                   for u in units)


def _bands(units: list["Unit"], columns: dict[int, _Column],
           pads: dict["Unit", Pad], wrappable: bool) -> list[list[int]]:
    """The columns of the grid, cut into bands that fit the paper.

    Greedy from the left, then the cut is slid to the nearest column
    boundary with the fewest runs across it -- a fold through a seam in
    the process rather than through the middle of a train. Sliding only
    backwards keeps every band inside the width; a fold that made one
    band wider to tidy the seam would be a fold that did not fit.

    A candidate band is measured by :func:`_lay_columns`, the same pass
    that will place it. Measuring it by adding up the columns' own
    widths instead over-counts, badly: a balloon standing east of a
    valve in one row does not push the column after it away from every
    *other* row, so a sheet 2370 px across measured 3400 and was folded
    in two -- with three units in the second band and an empty quarter
    of the page between them.
    """
    order = sorted(columns)
    if not wrappable or _lay_columns(columns, order, pads) <= BAND_WIDTH:
        return [order]

    crossings = _seam_cost(units)
    bands: list[list[int]] = []
    band: list[int] = []
    for column in order:
        if band and _lay_columns(columns, [*band, column], pads) > BAND_WIDTH:
            band = _slide(band, crossings)
            bands.append(band)
            band = []
        band.append(column)
    if band:
        bands.append(band)
    # A column dropped by the slide is not lost: the slide hands back a
    # prefix, and the loop carries on from the column after it.
    return _refill(order, bands)


def _seam_cost(units: list["Unit"]) -> dict[int, int]:
    """How many runs cross the gap after each column."""
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


def _slide(band: list[int], crossings: dict[int, int]) -> list[int]:
    """Pull a band's last column back to the quietest seam near it.

    At most a quarter of the band, so a seam is looked for where one
    plausibly is and the fold never walks back to the start of a band it
    has just filled.
    """
    reach = max(1, len(band) // 4)
    best = min(range(len(band) - reach, len(band)),
               key=lambda i: (crossings.get(band[i], 0), len(band) - 1 - i))
    return band[:best + 1]


def _refill(order: list[int], bands: list[list[int]]) -> list[list[int]]:
    """Re-cut the column list at the boundaries the bands settled on."""
    out: list[list[int]] = []
    seen = 0
    for band in bands[:-1]:
        end = order.index(band[-1]) + 1
        out.append(order[seen:end])
        seen = end
    if seen < len(order):
        out.append(order[seen:])
    return [band for band in out if band]


# ---------------------------------------------------------------------------
# One band's pixels
# ---------------------------------------------------------------------------


def _lay_columns(columns: dict[int, _Column], band: list[int],
                 pads: dict["Unit", Pad], place: bool = False) -> float:
    """How wide this run of columns comes out, and optionally place it.

    The balloon demand is settled **per row**, the way the rows settle
    theirs per column: a bubble standing east of a valve in row 2 wants
    paper east of *row 2*, not a gap driven through every row the column
    has. ``wall`` is how far east each row is already spoken for.

    Measuring and placing are one function so that the width a band is
    cut to and the width it is drawn at cannot come apart.
    """
    # A row with nothing to its west yet reserves nothing: the first
    # column starts on the margin, and a boundary flag whose pennant
    # reaches back past its own origin reaches into the margin rather
    # than pushing the whole sheet right.
    wall: dict[int, float] = {}
    cursor = float(MARGIN_X)
    for column in band:
        held = columns[column]
        x = cursor
        for u in held.units:
            behind = wall.get(slot(u).row or 0)
            if behind is not None:
                x = max(x, behind + _west(u, pads))
        if place:
            for u in held.units:
                if slot(u).x is None:
                    slot(u).x = x
        cursor = x + held.body + COL_GAP
        for u in held.units:
            row = slot(u).row or 0
            wall[row] = max(wall.get(row, 0.0),
                            x + slot(u).w + pads.get(u, Pad()).east)
    return max([cursor - COL_GAP, *wall.values()], default=cursor) - MARGIN_X


def _lay_band(columns: dict[int, _Column], band: list[int], top: float,
              pads: dict["Unit", Pad], anchored: bool) -> float:
    """Place one band's units and return where the next band starts."""
    members = [u for c in band for u in columns[c].units]
    if not members:
        return top

    _lay_columns(columns, band, pads, place=True)

    # Bands are built for every row the sheet names between the band's
    # own first and last, and a pin can name one above row 0:
    # ``pin(row=-1)`` is the band over it, which is where a header
    # belongs. An empty row keeps a default height, so a run has a lane.
    banded = [slot(u).row or 0 for u in members if slot(u).y is None]
    if not banded:
        return top
    # Row 0 anchors the top margin of the *first* band where nothing
    # goes above it, so ``pin(row=2)`` keeps the two empty bands it
    # asked for. A later band counts from its own first row instead:
    # the rows are global, and building every band from zero would
    # leave each one preceded by every band above it, empty.
    floor_row = min([*banded, 0]) if anchored else min(banded)
    rows = list(range(floor_row, max(banded) + 1))
    body = dict.fromkeys(rows, 50.0)  # the tallest box in the row
    holds: dict[int, list["Unit"]] = {r: [] for r in rows}
    for u in members:
        if slot(u).y is None:
            row = slot(u).row or 0
            holds[row].append(u)
            body[row] = max(body[row], slot(u).h)

    # The balloon demand is settled **per column**, not per row. A chain
    # of bubbles standing 200 units over an orifice plate in column 3
    # wants 200 units of paper over *column 3*; charging it to the whole
    # row charges it once per column the row has, and on a sheet with a
    # dozen instrumented runs that is a sheet four times too tall.
    # ``floor`` is how far down each column is already spoken for, which
    # is what lets a chain reach up through a band its own column has
    # nothing in.
    floor: dict[int, float] = {}
    axis: dict[int, float] = {}
    cursor_y = top
    for index, row in enumerate(rows):
        if index:
            cursor_y += body[rows[index - 1]] + ROW_GAP
        here = cursor_y + body[row] / 2.0
        for u in holds[row]:
            pad = pads.get(u, Pad())
            here = max(here, floor.get(slot(u).col or 0, top)
                       + pad.north + slot(u).h / 2.0)
        axis[row] = here
        cursor_y = here - body[row] / 2.0
        for u in holds[row]:
            col, pad = slot(u).col or 0, pads.get(u, Pad())
            floor[col] = max(floor.get(col, top),
                             here + slot(u).h / 2.0 + pad.south)
    for u in members:
        if slot(u).y is None:
            slot(u).y = axis[slot(u).row or 0] - slot(u).h / 2.0
    return max([cursor_y + body[rows[-1]], *floor.values()], default=top) + BAND_GAP


# ---------------------------------------------------------------------------
# Straightening
# ---------------------------------------------------------------------------

#: How far short of the nozzle it drops onto a sideways-facing one is
#: aimed. The router stands a run off a nozzle before it may turn, so
#: aiming dead on costs a turn out and a turn back; this is that
#: stand-off, spent going the way the run was already going.
STACK_LEAD = 25.0


def _straighten(fs: "Flowsheet", units: list["Unit"], band_of: dict["Unit", int],
                pads: dict["Unit", Pad]) -> None:
    """Turn staircase jogs into straight runs, within one band.

    Walk units left to right and, where a unit has a single horizontal
    process connection to pull it, shift it vertically so the two ports
    share an absolute height. Only a peer strictly to the left counts as
    upstream; everything else buckets downstream, a peer in this unit's
    own column included, so a same-column peer can be the lone anchor.
    Nothing rules that out ahead of time: the overlap check is what
    settles it, and two boxes asked to share a height in one column will
    fail it unless the target is an N/S escape lane clear of both.

    A peer in another band is no anchor at all. Aiming at it would drag
    a unit out of its own band and into the gap between two, which is
    the lane the folded runs are drawn in.

    A unit a nozzle stacks something over does not move on its own: the
    whole stack goes with it. The rows already say a relief valve is
    above the vessel it protects; straightening the vessel onto its own
    spine and leaving the valve on the row axis would say it in the row
    numbers and deny it in the ink, which is exactly the disagreement
    between geometry and nozzle this engine exists to end.

    The slot carries the same box the Frame will (size and transform),
    so the port resolver answers here exactly as it will once the frames
    are emitted. That is the point: a target read off the symbol instead
    ignores the resize, the mirror and any ``nozzle()`` choice, and aims
    at the wrong height.
    """
    from pandid.layout import claims as claims_mod
    from pandid.layout.stages import process_streams
    from pandid.portgeom import resolve_port

    def target_y(other_u: "Unit", other_port) -> float:
        """Absolute Y to aim a run at, honouring N/S escape lanes."""
        s = slot(other_u)
        (_, py), _, d = resolve_port(other_u, s, other_port.name)
        if d == "N":
            return (s.y or 0.0) - 15.0
        if d == "S":
            return (s.y or 0.0) + s.h + 15.0
        return py

    # Both questions below are asked of a *neighbourhood* -- the runs on
    # one unit, and the boxes in one column -- and both used to be
    # answered by reading the whole sheet: a pass over every stream and
    # a pass over every unit, per unit. Indexed once here instead.
    by_col: dict[int | None, list["Unit"]] = defaultdict(list)
    for u in units:
        by_col[slot(u).col].append(u)

    touching: dict["Unit", list] = defaultdict(list)
    for st in process_streams(fs):
        if st.is_recycle:
            continue
        src, dst = st.source.owner, st.dest.owner
        assert src is not None and dst is not None
        touching[dst].append((st.dest, src, st.source))
        if src is not dst:
            touching[src].append((st.source, dst, st.dest))

    def overlaps(u: "Unit", new_y: float, moving: set["Unit"]) -> bool:
        """Would ``u`` at ``new_y`` land on a neighbour, or on its halo?

        Measured on the *padded* box, so the paper a unit reserved for
        the balloons hanging off it is paper the straightener cannot
        spend either. Reserving it in the band layout and then handing
        it out here is how a bubble comes to be drawn over the boundary
        flag beside its own orifice plate.
        """
        s, pad = slot(u), pads.get(u, Pad())
        top, bottom = new_y - pad.north, new_y + s.h + pad.south
        for other in by_col[s.col]:
            o, o_pad = slot(other), pads.get(other, Pad())
            if other is u or other in moving or o.y is None:
                continue
            if not (bottom <= o.y - o_pad.north or top >= o.y + o.h + o_pad.south):
                return True
        return False

    stack_of = claims_mod.stacks(fs, units)
    stacked: dict["Unit", list["Unit"]] = defaultdict(list)
    for u in units:
        stacked[stack_of[u]].append(u)

    settled: set["Unit"] = set()
    for u in sorted(units, key=lambda v: (slot(v).col or 0, slot(v).y or 0.0)):
        s = slot(u)
        if u in settled or s.y is None:
            continue
        group = stacked[stack_of[u]]
        if any(v.pin_ is not None and v.pin_.y is not None for v in group):
            continue
        ups: list[tuple] = []
        downs: list[tuple] = []
        for pair in touching[u]:
            if band_of.get(pair[1]) != band_of.get(u) or pair[1] in group:
                continue
            (ups if (pair[1]._slot.col or 0) < (s.col or 0) else downs).append(pair)
        # A single upstream anchor chains the spine; fall back to a
        # single downstream one so terminals (Feed) still align.
        anchor = ups[0] if len(ups) == 1 else (downs[0] if not ups and len(downs) == 1 else None)
        if anchor is None:
            continue
        my_port, other_u, other_port = anchor
        if slot(other_u).y is None:
            continue
        # Only straighten horizontal runs: the port must face the
        # neighbour sideways (E/W); a vertical port keeps the row axis.
        (_, my_y), _, my_d = resolve_port(u, s, my_port.name)
        if my_d not in ("E", "W"):
            continue
        shift = target_y(other_u, other_port) - my_y
        riding = set(group)
        if any(overlaps(v, (slot(v).y or 0.0) + shift, riding) for v in group):
            continue
        for v in group:
            slot(v).y = (slot(v).y or 0.0) + shift
        settled.update(group)

    for u, new_x in _stack_offsets(fs, units, band_of):
        if not _overlaps_x(u, new_x, units):
            slot(u).x = new_x


def _stack_offsets(fs: "Flowsheet", units: list["Unit"],
                   band_of: dict["Unit", int]) -> list[tuple["Unit", float]]:
    """``(unit, x)`` for every stacked unit worth shifting sideways.

    Ranking has put a vertically connected pair in one column, which is
    not the same as putting the nozzles in one line, and 10 px out is
    enough for a run to leave east, drop, and come back west. Aim the
    leaving nozzle a stand-off short of the arriving one and that
    becomes one turn. Only a nozzle facing sideways is aimed: one
    already facing the peer it is stacked against drops straight onto
    it, and moving the box would be the thing that bent the run.
    """
    from pandid.layout.claims import fixed_face
    from pandid.layout.stages import process_streams
    from pandid.portgeom import resolve_port

    placed = set(units)
    out: list[tuple["Unit", float]] = []
    for st in process_streams(fs):
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
            if face not in ("E", "W"):
                continue
            (my_x, _), _, _ = resolve_port(u, slot(u), mine.name)
            (their_x, _), _, _ = resolve_port(peer, slot(peer), theirs.name)
            lead = STACK_LEAD if face == "E" else -STACK_LEAD
            out.append((u, their_x - lead - (my_x - my_x0)))
    return out


#: Clear paper a sideways nudge has to leave between the box it moves
#: and the one beside it. Not a collision margin: a run between two
#: boxes has to be *drawn*, and its number written along it, and a
#: number is a couple of dozen pixels of lettering before it is
#: anything else. Slid until it merely fails to overlap, an ejector
#: lining up with the vent above it left 17 px between itself and the
#: splitter feeding it -- a run too short to write ``S7`` beside, so the
#: number went off looking for paper and had to be drawn back to its own
#: line across the splitter (15_condensing_turbine).
STACK_CLEAR = 40.0


def _overlaps_x(u: "Unit", new_x: float, units: list["Unit"]) -> bool:
    """Would moving ``u`` to ``new_x`` crowd a unit beside it?"""
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
