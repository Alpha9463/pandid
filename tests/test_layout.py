from pandid import Flowsheet, units as U
from pandid.layout import _seed_slots
from pandid.layout.cycles import break_cycles
from pandid.layout.layering import assign_layers
from pandid.layout.ordering import order_within_layers
from pandid.layout.coordinates import assign_coordinates


def test_cycle_breaking():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))

    s1 = fs.connect(u1.outlet, u2.feed)
    s2 = fs.connect(u2.liquid, u1.feed)  # backward

    break_cycles(fs)

    # One of them should be marked as recycle. Because u1 is first,
    # and has out-degree 1, DFS from u1 goes to u2, then u2 goes to u1.
    # The edge from u2 to u1 is the back-edge.
    assert s1.is_recycle is False
    assert s2.is_recycle is True


def test_layering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))
    u3 = fs.add(U.Mixer("M1"))

    fs.connect(u1.outlet, u2.feed)
    fs.connect(u2.vapor, u3.in_1)

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)

    assert u1._slot.col == 0
    assert u2._slot.col == 1
    assert u3._slot.col == 2


def test_pinned_layering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))

    fs.connect(u1.outlet, u2.feed)

    u1.pin(col=2, row=0)  # u1 is forced to col 2

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)

    assert u1._slot.col == 2
    # u2 must be at least u1.col + 1
    assert u2._slot.col == 3


def test_ordering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Separator("S1"))
    u2 = fs.add(U.Reactor("R1"))
    u3 = fs.add(U.Mixer("M1"))

    fs.connect(u1.vapor, u2.feed)
    fs.connect(u1.liquid, u3.in_1)

    break_cycles(fs)
    _seed_slots(fs)
    assign_layers(fs)
    order_within_layers(fs)

    # u2 and u3 are both in col 1, they must have different rows (0 and 1)
    assert u1._slot.row == 0
    assert {u2._slot.row, u3._slot.row} == {0, 1}


def test_coordinates():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u1.pin(col=1, row=2)

    _seed_slots(fs)
    assign_coordinates(fs)

    # Only one column (col 1) exists, so it starts at MARGIN_X
    assert u1.frame.x == 50
    assert u1.frame.y == 50 + 2 * 120


def test_full_layout_via_render(tmp_path):
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))
    fs.connect(u1.outlet, u2.feed)

    # rendering should implicitly trigger layout because frames are None
    svg_path = tmp_path / "test.svg"
    fs.render(str(svg_path))

    assert u1.frame.x is not None
    assert u2.frame.col == 1

    content = svg_path.read_text()
    assert "<use" in content


def test_spine_straightening_scales_the_port_offset_to_the_resolved_box():
    """The straightening target has to come from the resolved box, not the
    symbol.

    A drum resized past its symbol's height carries its inlet proportionally
    lower, so aiming at the raw symbol-space offset lands the run short by
    exactly that ratio -- 6px for a 42-high drum on a 30-high symbol. Only units
    left unpinned in y are affected, which is why the examples do not show it:
    they pin.
    """
    from pandid.portgeom import port_point

    fs = Flowsheet("straighten")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal", height=42))
    fs.connect(feed.outlet, drum.inlet)
    fs.layout()

    assert port_point(feed, feed.frame, "outlet")[1] == port_point(drum, drum.frame, "inlet")[1]


# --- north and south faces (#168) ---------------------------------------------


def _syngas_block():
    """The sheet from issue #168: two north inlets on one block."""
    fs = Flowsheet("north face")
    ng = fs.add(U.Feed("Natural Gas"))
    air = fs.add(U.Feed("Air"))
    steam = fs.add(U.Feed("Steam"))
    sec = fs.add(U.Block("Sec", inputs=["W", "N", "N"], outputs=["E"]))
    prod = fs.add(U.Product("Syngas"))
    fs.connect(ng.outlet, sec.in_1)
    fs.connect(air.outlet, sec.in_2)
    fs.connect(steam.outlet, sec.in_3)
    fs.connect(sec.out_1, prod.inlet)
    return fs, ng, air, steam, sec, prod


def test_a_north_face_puts_its_peer_above_the_block_and_not_beside_it():
    """Issue #168: a peer on a north connection belongs in the row above.

    Ranked as a flow-order step it went a column to the left and wherever
    the barycentre landed it -- for ``Air`` here, the bottom of the sheet,
    from which its run climbed the full height and crossed two others to
    reach a nozzle on the roof.
    """
    fs, ng, air, steam, sec, prod = _syngas_block()
    fs.layout()

    for feed in (air, steam):
        assert feed._slot.col == sec._slot.col
        assert feed._slot.row < sec._slot.row
    # The two of them stack rather than fight over the one row.
    assert air._slot.row != steam._slot.row
    # The west inlet is unaffected: it still ranks a column to the left.
    assert ng._slot.col == sec._slot.col - 1
    assert ng._slot.row == sec._slot.row


def test_a_north_face_peer_reaches_its_nozzle_in_one_turn():
    """The row above is only half of it: the run has to be short too.

    Both feeds face east and the nozzles they drop onto are inside the
    block, so the coordinate pass aims each flag a stand-off short of its
    own nozzle. Without that the run leaves east, drops, and comes back
    west -- three turns to cross ten pixels.
    """
    from pandid.layout.attach import stream_path

    fs, ng, air, steam, sec, prod = _syngas_block()
    fs.layout()
    fs.route()

    for feed in (air, steam):
        legs = _legs(stream_path(feed.outlet.stream))
        assert len(legs) <= 2, f"{feed.name} turns {len(legs) - 1} times: {legs}"


def _legs(path):
    """The straight runs of a routed path, in order, as unit steps.

    Zero-length repeats and the stand-off waypoint that continues a leg
    are folded in, so this counts *turns* rather than waypoints.
    """
    out = []
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if (dx, dy) == (0.0, 0.0):
            continue
        step = (0 if dx == 0 else dx / abs(dx), 0 if dy == 0 else dy / abs(dy))
        if not out or out[-1] != step:
            out.append(step)
    return out


def test_a_south_face_puts_its_peer_below():
    fs = Flowsheet("south face")
    feed = fs.add(U.Feed("Feed"))
    sec = fs.add(U.Block("Sec", inputs=["W"], outputs=["E", "S"]))
    prod = fs.add(U.Product("Product"))
    waste = fs.add(U.Product("Waste"))
    fs.connect(feed.outlet, sec.in_1)
    fs.connect(sec.out_1, prod.inlet)
    fs.connect(sec.out_2, waste.inlet)
    fs.layout()

    assert waste._slot.col == sec._slot.col
    assert waste._slot.row == sec._slot.row + 1
    assert prod._slot.col == sec._slot.col + 1


def test_two_north_faces_facing_each_other_state_no_order():
    """A north connected to a north says each is above the other.

    There is no arrangement that satisfies both, so neither is applied and
    the edge ranks as any other does.
    """
    fs = Flowsheet("facing")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["N"]))
    b = fs.add(U.Block("B", inputs=["N"], outputs=["E"]))
    feed = fs.add(U.Feed("Feed"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(b.out_1, prod.inlet)
    fs.layout()

    assert b._slot.col == a._slot.col + 1


def test_an_equipment_nozzle_on_the_north_is_not_a_stacking_constraint():
    """A drum's vapour leaves the top because vapour does.

    The compressor it feeds is still the next unit along, and a rule read
    off the geometry rather than off the author would put it on the roof --
    and would rearrange every sheet in the corpus for the same reason.
    """
    fs = Flowsheet("equipment")
    feed = fs.add(U.Feed("Feed"))
    sep = fs.add(U.Separator("V-1"))
    comp = fs.add(U.Compressor("K-1"))
    fs.connect(feed.outlet, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.layout()

    assert comp._slot.col == sep._slot.col + 1
    assert comp._slot.row == sep._slot.row


def test_a_named_north_nozzle_is_not_a_stacking_constraint_either():
    """``examples/08`` feeds its deaerator over the top tray.

    ``nozzle("inlet", "N")`` moves the stream to another part of the same
    drum; the pump on the other end of it still belongs beside the drum.
    """
    fs = Flowsheet("named")
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    drum.nozzle("inlet", "N")
    fs.connect(pump.discharge, drum.inlet)
    fs.layout()

    assert drum._slot.col == pump._slot.col + 1


def test_a_recycle_into_a_south_face_does_not_drag_its_source_back():
    """A recycle is drawn backward from a unit columns downstream.

    Reading its face as a same-column constraint would pull that unit back
    to the block it returns to.
    """
    fs = Flowsheet("recycle")
    feed = fs.add(U.Feed("Feed"))
    a = fs.add(U.Block("A", inputs=["W", "S"], outputs=["E"]))
    b = fs.add(U.Block("B", inputs=["W"], outputs=["E", "E"]))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(b.out_1, prod.inlet)
    fs.connect(b.out_2, a.in_2, draw_as_recycle=True)
    fs.layout()

    assert b._slot.col == a._slot.col + 1


def test_a_stacked_sheet_lays_out_the_same_way_twice():
    """Faces are read off the solver slot, not off the frames left behind."""
    fs, *_ = _syngas_block()
    fs.layout()
    first = {u.name: (u.frame.x, u.frame.y) for u in fs.units}
    fs.layout()
    assert {u.name: (u.frame.x, u.frame.y) for u in fs.units} == first


# --- slack removal ------------------------------------------------------------


def test_a_branch_ranks_beside_the_spine_it_joins():
    """Longest path measures from the left edge of the drawing.

    A blower feeding a tower eight units along starts beside the first
    unit of the train and runs the width of the page to reach it. Removing
    the slack puts it one column short of the tower instead.
    """
    fs = Flowsheet("slack")
    water = fs.add(U.Feed("Water"))
    a = fs.add(U.Filter("F-1"))
    b = fs.add(U.Filter("F-2"))
    tower = fs.add(U.Stripper("D-1"))
    air = fs.add(U.Feed("Air"))
    blower = fs.add(U.Blower("B-1"))
    fs.connect(water.outlet, a.inlet)
    fs.connect(a.outlet, b.inlet)
    fs.connect(b.outlet, tower.feed)
    fs.connect(air.outlet, blower.suction)
    fs.connect(blower.discharge, tower.boilup_in)
    fs.layout()

    assert blower._slot.col == tower._slot.col - 1
    assert air._slot.col == blower._slot.col - 1


def test_slack_removal_leaves_a_pinned_column_alone():
    fs = Flowsheet("pinned slack")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, drum.inlet)
    feed.pin(col=0)
    drum.pin(col=6)
    fs.layout()

    assert feed._slot.col == 0
    assert drum._slot.col == 6
    # The pump has slack between them and takes the tight end of it.
    assert pump._slot.col == 5


def test_slack_removal_keeps_a_rank_right_of_its_own_upstream():
    """Sliding a rank right is safe. A pinned successor slid it left.

    ``P-2`` took one column short of ``P-3``'s pin and landed four
    columns *behind* the pump feeding it, at a column left of the page.
    Two pins this far apart cannot both be honoured with a forward edge
    between them, and the one that gives is the derived rank.
    """
    fs = Flowsheet("conflicting pins")
    a = fs.add(U.Pump("P-1"))
    b = fs.add(U.Pump("P-2"))
    c = fs.add(U.Pump("P-3"))
    fs.connect(a.discharge, b.suction)
    fs.connect(b.discharge, c.suction)
    a.pin(col=3)
    c.pin(col=0)
    fs.layout()

    assert a.frame.col == 3
    assert c.frame.col == 0
    assert b.frame.col > a.frame.col
    assert min(u.frame.col for u in fs.units) >= 0


# --- rows and columns left of the origin ---------------------------------------


def test_a_row_pinned_above_the_first_band_draws():
    """``pin(row=-1)`` names the band over row 0, which is a real place.

    The coordinate pass counted its bands up from zero, so the pin
    indexed a band that was never built and the sheet raised
    ``KeyError`` instead of drawing.
    """
    fs = Flowsheet("negative row")
    top = fs.add(U.Feed("Top"))
    bottom = fs.add(U.Feed("Bottom"))
    mixer = fs.add(U.Mixer("M-1"))
    fs.connect(top.outlet, mixer.in_1)
    fs.connect(bottom.outlet, mixer.in_2)
    top.pin(row=-1)
    bottom.pin(row=2)
    fs.layout()

    assert top.frame.row == -1
    assert bottom.frame.row == 2
    # The band above row 0 is drawn above it, and on the page.
    assert 0 <= top.frame.y < bottom.frame.y


def test_crossing_reduction_runs_left_of_column_zero():
    """The barycentre swept ``range(1, max_col + 1)``.

    A sheet pinned to the left of column 0 has ``max_col == 0``, which
    makes that range and its mirror both empty: every sweep became a
    no-op and the sheet came out unordered with nothing reported.
    """
    fs = Flowsheet("negative column")
    a, b, c = (fs.add(U.Block(n, inputs=1, outputs=1)) for n in "ABC")
    x, y, z = (fs.add(U.Block(n, inputs=1, outputs=1)) for n in "XYZ")
    for src, dest in ((a, z), (b, y), (c, x)):
        fs.connect(src.out_1, dest.in_1)
        src.pin(col=-1)
    fs.layout()

    # Each sink follows the source feeding it, so no run crosses another.
    assert [z.frame.row, y.frame.row, x.frame.row] == [0, 1, 2]


def test_a_pinned_row_survives_a_sheet_that_stacks_above_it():
    """Neither the pin nor the stacking constraint gives.

    ``Air`` on the north face lands a row above the block, which is a
    row below zero here, and the rebase cannot renumber the bands out
    from under a pin. It walked every unit rather than the satellites,
    so the pinned product was renumbered too.

    It then put the satellite in the first free row instead, which is
    *below* the unit feeding it. The coordinate pass builds a band for a
    negative row now, so there is nothing left to drop: the pin keeps its
    band and the feed keeps its roof.
    """
    fs = Flowsheet("pinned row over a stack")
    ng = fs.add(U.Feed("Natural Gas"))
    air = fs.add(U.Feed("Air"))
    sec = fs.add(U.Block("Sec", inputs=["W", "N"], outputs=["E"]))
    prod = fs.add(U.Product("Syngas"))
    fs.connect(ng.outlet, sec.in_1)
    fs.connect(air.outlet, sec.in_2)
    fs.connect(sec.out_1, prod.inlet)
    prod.pin(row=-1)
    fs.layout()

    assert prod.frame.row == -1
    assert air.frame.row == sec.frame.row - 1
    assert air.frame.y < sec.frame.y


def _pinned_north_feed(pin_row):
    """A block with a west feed and a north one, optionally pinned."""
    fs = Flowsheet("stack")
    b = fs.add(U.Block("Reaction", inputs=["W", "N"], outputs=1))
    feed = fs.add(U.Feed("Main"))
    air = fs.add(U.Feed("Air"))
    prod = fs.add(U.Product("Out"))
    fs.connect(feed.outlet, b.in_1)
    fs.connect(air.outlet, b.in_2)
    fs.connect(b.out_1, prod.inlet)
    if pin_row is not None:
        b.pin(row=pin_row)
    fs.layout()
    return b, air


def test_pinning_the_row_the_engine_picks_anyway_does_not_flip_a_north_feed():
    """Issue #311: a pin that moves nothing turned the drawing upside down.

    ``pin(row=0)`` is what an author types to say *this is the top of the
    sheet*, and it put the north feed on the south side of the block it
    feeds. Every one of these is the same sheet, and ``Air`` is over the
    block on all of them.
    """
    for pin_row in (None, 0, 1, 2, -1):
        block, air = _pinned_north_feed(pin_row)
        assert air.frame.row == block.frame.row - 1, f"pin(row={pin_row})"
        assert air.frame.y < block.frame.y, f"pin(row={pin_row})"
    # The pin is still the pin: the band it named is the band it gets.
    for pin_row in (0, 1, 2, -1):
        assert _pinned_north_feed(pin_row)[0].frame.row == pin_row


def test_vertical_constraints_that_state_no_top_fall_back_to_a_free_row():
    """Two blocks each told to sit over the other.

    Two streams between the same pair, one naming the arriving face and
    one the leaving face, so each block is the other's satellite. The
    chain never resolves, which states no top and no bottom, and both
    take the first free row in their column instead of hanging.
    """
    fs = Flowsheet("vertical cycle")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["E", "N"]))
    b = fs.add(U.Block("B", inputs=["N", "W"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(a.out_2, b.in_2)
    fs.connect(b.out_1, fs.add(U.Product("P")).inlet)
    fs.layout()

    # Ranked as one column all the same, and no two units on one band.
    assert a.frame.col == b.frame.col
    assert a.frame.row != b.frame.row
    assert {a.frame.row, b.frame.row} == {0, 1}


# --- laying a sheet out twice draws it twice the same -------------------------


def _interlock_on_a_signal():
    """``examples/04_control_loop.py``'s shape: a balloon on a balloon's line.

    ``LT`` reads the drum, ``LIC`` sits under it, and the interlock hangs
    off the *signal between the two* -- a stream whose ends are both
    attached instruments, so where it is drawn from depends on faces
    chosen after the boxes are placed.
    """
    fs = Flowsheet("interlock")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)

    lt = fs.add_instrument("LT", 101, sensing=drum, at="S", offset=70)
    lic = fs.add_instrument("LIC", 101, near=lt, at="S", offset=95, variant="shared")
    measurement = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    interlock = fs.add_instrument(
        "I", 1, sensing=measurement, at=0.5, offset=44, angle=90, variant="logic"
    )
    return fs, interlock


def test_laying_a_sheet_out_twice_puts_every_box_in_the_same_place():
    """Issue #294: ``layout()`` has to be a function of the model.

    An instrument hung on a signal between two other balloons was placed
    from the faces a symbol defaults to on the first run and from the
    faces the first run chose on the second, so ``layout()`` moved it
    16px the second time it was called. The sheet drew correctly all the
    same -- ``route()`` runs the placement to a fixed point of its own --
    but anyone calling ``layout()`` and reading ``frame`` got the
    unsettled answer, and so did ``validate()``.
    """
    fs, interlock = _interlock_on_a_signal()

    def boxes():
        return {u.name: (u.frame.x, u.frame.y) for u in fs.units if u.frame}

    fs.layout()
    first = boxes()
    assert interlock.name in first  # the balloon under test is on the sheet
    fs.layout()
    assert boxes() == first
    fs.layout()
    assert boxes() == first


def test_the_face_a_signal_leaves_on_is_settled_before_the_labels_are_placed():
    """A label dodges the faces the nozzles leave from, so it is told last.

    The placement fixed point sits between the two, which only works if
    it ends on a selection nothing has moved a box since.
    """
    fs, interlock = _interlock_on_a_signal()
    fs.layout()

    lt = next(u for u in fs.units if u.name == "LT-101")
    before = dict(lt.frame.port_faces)
    from pandid.layout.attach import place_attached

    assert not place_attached(fs), "a further pass still moves a balloon"
    assert dict(lt.frame.port_faces) == before


# --- the column-sharing pass against the scan it replaced ---------------------


def _closes_cycle_by_rebuild(units, flow, find, a, b):
    """The cycle test as it read before the contracted graph was carried.

    Contract every unit and every stream with ``a`` and ``b`` identified,
    then topologically sort the result: a cycle is a node the sort never
    reaches. Kept here as the definition the fast test is measured
    against, since it is the one every shipped sheet was laid out by.
    """
    from collections import defaultdict, deque

    def merged(u):
        g = find(u)
        return b if g is a else g

    adj = defaultdict(set)
    nodes = {merged(u) for u in units}
    for s in flow:
        x, y = merged(s.source.owner), merged(s.dest.owner)
        if x is not y:
            adj[x].add(y)
    in_degree = dict.fromkeys(nodes, 0)
    for ys in adj.values():
        for y in ys:
            in_degree[y] += 1
    queue = deque([n for n in nodes if in_degree[n] == 0])
    seen = 0
    while queue:
        n = queue.popleft()
        seen += 1
        for y in adj[n]:
            in_degree[y] -= 1
            if in_degree[y] == 0:
                queue.append(y)
    return seen < len(nodes)


def _share_columns_by_rebuild(units, flow, stacks):
    """``_share_columns`` driving the rebuild above, candidate by candidate."""
    lead = {u: u for u in units}

    def find(u):
        while lead[u] is not u:
            lead[u] = lead[lead[u]]
            u = lead[u]
        return u

    col = {u: u._slot.col for u in units if u._slot.col is not None}
    for st in stacks:
        a, b = find(st.satellite), find(st.anchor)
        if a is b or (a in col and b in col and col[a] != col[b]):
            continue
        if _closes_cycle_by_rebuild(units, flow, find, a, b):
            continue
        lead[a] = b
        if a in col:
            col[b] = col.pop(a)
    return {u: find(u) for u in units}


def _sharing_inputs(fs):
    """The three arguments ``assign_layers`` hands the column-sharing pass."""
    from pandid.layout.attach import free_streams, free_units
    from pandid.layout.stacking import stacked_edges

    break_cycles(fs)
    _seed_slots(fs)
    units = free_units(fs)
    stacks = stacked_edges(fs)
    vertical = {id(st.stream) for st in stacks}
    flow = [s for s in free_streams(fs) if not s.is_recycle and id(s) not in vertical]
    return units, flow, stacks


def _stacked_chain(n, pins=()):
    """*n* blocks in a row, each with a feed over its roof."""
    fs = Flowsheet("stacked chain")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W", "N"], outputs=["E"]))
        fs.connect(port, block.in_1)
        fs.connect(fs.add(U.Feed(f"A-{i}")).outlet, block.in_2)
        if i in pins:
            block.pin(col=i)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def _stack_over_a_chain():
    """A north face reaching two blocks down its own train.

    ``A`` feeds ``B`` feeds ``C``, and ``C`` also takes ``A`` over its
    roof. Ranking the two as one column would put ``B`` after the merged
    rank and before it at once, so the constraint has to be refused.
    """
    fs = Flowsheet("stack over a chain")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["E", "E"]))
    b = fs.add(U.Block("B", inputs=["W"], outputs=["E"]))
    c = fs.add(U.Block("C", inputs=["W", "N"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(b.out_1, c.in_1)
    fs.connect(a.out_2, c.in_2)
    fs.connect(c.out_1, fs.add(U.Product("P")).inlet)
    return fs, a, b, c


def _stack_of_three():
    """Three blocks in one column, each hung over the one below it.

    ``Top`` over ``Mid`` over ``Base``, and each carries a feed and a
    product of its own -- so the second union folds a group that already
    has edges to move, rather than a bare flag with none.
    """
    fs = Flowsheet("stack of three")
    base = fs.add(U.Block("Base", inputs=["W", "N"], outputs=["E"]))
    mid = fs.add(U.Block("Mid", inputs=["W", "N"], outputs=["E", "E"]))
    top = fs.add(U.Block("Top", inputs=["W"], outputs=["E"]))
    for u in (base, mid, top):
        fs.connect(fs.add(U.Feed(f"F-{u.name}")).outlet, u.in_1)
    fs.connect(base.out_1, fs.add(U.Product("P-Base")).inlet)
    fs.connect(mid.out_1, fs.add(U.Product("P-Mid")).inlet)
    fs.connect(mid.out_2, base.in_2)
    fs.connect(top.out_1, mid.in_2)
    return fs


def _cycle_only_a_merge_can_see():
    """A union refused only because of the edges an earlier one moved.

    ``A`` reaches nothing on its own. ``D`` reaches ``C`` through ``X``,
    and the first constraint hangs ``D`` over ``A``, so the merged rank
    inherits that reach. The second constraint would then hang ``A`` over
    ``C`` -- which the merged rank already runs to, two steps along -- and
    has to be refused. A pass that read the graph as it stood before the
    first union sees nothing between the two and takes it.
    """
    fs = Flowsheet("inherited reach")
    a = fs.add(U.Block("A", inputs=["W", "N"], outputs=["E", "E"]))
    c = fs.add(U.Block("C", inputs=["W", "N"], outputs=["E"]))
    d = fs.add(U.Block("D", inputs=["W"], outputs=["E", "E"]))
    x = fs.add(U.Block("X", inputs=["W"], outputs=["E"]))
    y = fs.add(U.Block("Y", inputs=["W"], outputs=["E"]))
    for u in (a, d):
        fs.connect(fs.add(U.Feed(f"F-{u.name}")).outlet, u.in_1)
    fs.connect(d.out_1, x.in_1)
    fs.connect(x.out_1, c.in_1)
    fs.connect(a.out_1, y.in_1)
    fs.connect(d.out_2, a.in_2)  # first: D hangs over A
    fs.connect(a.out_2, c.in_2)  # second: A would hang over C
    fs.connect(c.out_1, fs.add(U.Product("P")).inlet)
    return fs, a, c


def _stacked_on_what_it_feeds():
    """Each block both feeds the next and hangs over it.

    The flow edge between a merged pair becomes a loop on the merged
    rank, and a rank that runs to itself is not an order between two
    things: dropped when the graph was contracted wholesale, and dropped
    on the fold. Left in, it makes the *next* union look as though the
    two ends already had a run between them, and a constraint the sheet
    can honour is turned down.
    """
    fs = Flowsheet("stacked on what it feeds")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["E", "E"]))
    b = fs.add(U.Block("B", inputs=["W", "N"], outputs=["E", "E"]))
    y = fs.add(U.Block("Y", inputs=["W", "N"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(b.out_1, y.in_1)
    fs.connect(a.out_2, b.in_2)
    fs.connect(b.out_2, y.in_2)
    fs.connect(y.out_1, fs.add(U.Product("P")).inlet)
    return fs, a, b, y


def test_the_column_sharing_pass_answers_what_the_whole_sheet_scan_did():
    """The contracted graph is carried across the unions, not rebuilt.

    Rebuilding it meant contracting every unit and every stream and
    topologically sorting the result once per stacked edge. The answer
    has to be the same one -- these are the ranks every shipped sheet is
    drawn on -- so the scan it replaced is kept in this file and both are
    asked the same question.

    Order is part of the answer: the unions are greedy and the first of
    two conflicting constraints wins, so a pass refusing a *different*
    one would draw a different sheet on the same count refused.
    """
    from pandid.layout.layering import _share_columns

    corpus = [
        _stacked_chain(6),
        _stacked_chain(6, pins=(1, 4)),
        _stack_over_a_chain()[0],
        _stack_of_three(),
        _cycle_only_a_merge_can_see()[0],
        _stacked_on_what_it_feeds()[0],
        _syngas_block()[0],
    ]
    for fs in corpus:
        units, flow, stacks = _sharing_inputs(fs)
        assert stacks, f"{fs.name} states no vertical constraint to share on"
        assert _share_columns(units, flow, stacks) == _share_columns_by_rebuild(
            units, flow, stacks
        ), fs.name


def test_a_stack_that_would_rank_a_block_before_and_after_itself_is_refused():
    """The corpus above is only worth comparing if a union is turned down."""
    from pandid.layout.layering import _share_columns

    fs, a, b, c = _stack_over_a_chain()
    units, flow, stacks = _sharing_inputs(fs)
    assert _closes_cycle_by_rebuild(units, flow, lambda u: u, a, c)
    assert _share_columns(units, flow, stacks)[a] is not _share_columns(units, flow, stacks)[c]

    # And the sheet still draws, with B between the two rather than beside
    # a rank that is its own predecessor.
    fs.layout()
    assert a._slot.col < b._slot.col < c._slot.col


def test_a_union_is_judged_on_the_edges_the_one_before_it_moved():
    """The contracted graph is carried, so it has to be kept in step.

    Reading the graph as it stood before the earlier union would find
    nothing between these two ranks and merge them, which is the rank
    running to itself two steps along.
    """
    from pandid.layout.layering import _share_columns

    fs, a, c = _cycle_only_a_merge_can_see()
    units, flow, stacks = _sharing_inputs(fs)
    assert [(st.satellite.name, st.anchor.name) for st in stacks] == [("D", "A"), ("A", "C")]
    head = _share_columns(units, flow, stacks)
    assert head[a] is not head[c]
