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
    tower = fs.add(U.Column("D-1"))
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
