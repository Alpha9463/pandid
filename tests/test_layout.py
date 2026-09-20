import pytest

from pandid import Flowsheet, devices as D, units as U
from pandid.layout import _seed_slots
from pandid.layout.cycles import break_cycles
from pandid.layout.coordinates import assign_coordinates
from pandid.layout.place import assign_positions


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

    _seed_slots(fs)
    break_cycles(fs)
    assign_positions(fs)

    assert u1._slot.col == 0
    assert u2._slot.col == 1
    assert u3._slot.col == 2


def test_pinned_layering():
    fs = Flowsheet("Test")
    u1 = fs.add(U.Reactor("R1"))
    u2 = fs.add(U.Separator("S1"))

    fs.connect(u1.outlet, u2.feed)

    u1.pin(col=2, row=0)  # u1 is forced to col 2

    _seed_slots(fs)
    break_cycles(fs)
    assign_positions(fs)

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

    _seed_slots(fs)
    break_cycles(fs)
    assign_positions(fs)

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


def test_two_north_faces_facing_each_other_settle_on_one_column():
    """A north connected to a north says each is above the other.

    No arrangement satisfies both, and the two are equally sure, so the
    row they settle on is the *same* row -- and both say, separately and
    in agreement, that they are in one column. So the sheet stacks them,
    and the separation gives one of them the row below.

    The engine before this one cancelled the pair outright, dropping
    what they agreed on along with what they did not, and fell back to
    flow order. That cancellation is #446: a column overhead and a
    condenser inlet are exactly this pair of faces, and dropping both
    left nothing at all to say which way up the tower went. Here the
    disagreement is settled by weight and there is nothing to drop --
    which for two plain blocks, neither of which has a convention to
    appeal to, is a stack.
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

    assert b._slot.col == a._slot.col
    assert b._slot.row != a._slot.row


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
    the slack puts it in the next column to the tower instead.

    *Which* side it lands on is the tower's own nozzle: ``boilup_in`` is
    on the east face, so the run enters from the east and the blower
    that feeds it is drawn there. Only the distance is this test's
    subject -- the branch is one column from what it joins, wherever the
    nozzle puts it, rather than the width of the sheet away.
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

    assert abs(blower._slot.col - tower._slot.col) == 1
    assert abs(air._slot.col - blower._slot.col) == 1
    # And not at the left edge, which is where longest path alone put it.
    assert blower._slot.col > b._slot.col


def test_a_unit_between_two_pins_is_drawn_between_them():
    """Both pins hold, and what is derived sits where its claims want.

    The engine before this one ranked by longest path and then slid every
    derived position as far along as its own connections allowed, so the
    pump took one column short of the drum and left five empty columns
    for its own feed line to cross. There is no distance-from-a-source
    here to remove the slack from: the pump is pulled by the flag on one
    side and the drum on the other, and lands where those weigh out.
    """
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
    assert 0 < pump._slot.col < 6


def test_two_pins_that_contradict_hold_and_the_derived_one_gives():
    """``P-1`` east of ``P-3``, with the flow running the other way.

    Two pins this far apart cannot both be honoured with a chain between
    them, and what gives is the position nobody stated: ``P-2`` settles
    between the two rather than being dragged off the page behind the
    pump feeding it. Both pins hold exactly, which is the point -- a pin
    is a boundary condition and not a preference to be reconciled.
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
    assert 0 <= b.frame.col <= 3
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


def test_vertical_claims_that_state_no_top_settle_on_one_row():
    """Two blocks each told to sit over the other, and beside it too.

    Two runs between the same pair: one names the arriving face and one
    the leaving face, so each block claims the other is its satellite --
    and a third pair of claims, off the two sideways faces, says they
    are side by side on one row. Those cancel; these do not, and the two
    weigh the same, so the answer is the arrangement both sideways faces
    asked for.

    The engine before this one had no way to say "cancel on one axis and
    not on the other", so it read the pair as one column and stacked
    them.
    """
    fs = Flowsheet("vertical cycle")
    a = fs.add(U.Block("A", inputs=["W"], outputs=["E", "N"]))
    b = fs.add(U.Block("B", inputs=["N", "W"], outputs=["E"]))
    fs.connect(fs.add(U.Feed("F")).outlet, a.in_1)
    fs.connect(a.out_1, b.in_1)
    fs.connect(a.out_2, b.in_2)
    fs.connect(b.out_1, fs.add(U.Product("P")).inlet)
    fs.layout()

    assert b.frame.col == a.frame.col + 1
    assert a.frame.row == b.frame.row


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


# --- what a fixed nozzle face says about placement (#431) ---------------------


def test_a_relief_valve_is_drawn_over_the_vessel_it_protects():
    """Issue #430: the two ends of a return line had no relation at all.

    The vessel's crown and the valve's own inlet both say the valve is
    above it, and neither says anything about how far along -- so the
    column comes out the same for both and the relief runs straight up.
    Ranked as a step along the flow instead, the valve landed at the
    bottom right of the sheet and the relief line was drawn round the
    outside of everything to reach it.
    """
    fs = Flowsheet("relief")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-101"))
    prod = fs.add(U.Product("Product"))
    psv = fs.add(D.ReliefValve("PSV-101"))
    flare = fs.add(U.Product("To Flare"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)
    fs.layout()

    assert psv.frame is not None and drum.frame is not None
    assert psv.frame.col == drum.frame.col
    assert psv.frame.y_max <= drum.frame.y


def test_one_fixed_nozzle_places_an_edge_whose_far_end_can_move():
    """The reading is per endpoint, which a per-edge rule cannot do.

    A horizontal drum's inlet is authored on three faces, so nothing
    about *it* says where the drum goes. The pump's discharge is on one,
    and that is enough: the drum is east of the pump.
    """
    from pandid.portgeom import port_faces

    fs = Flowsheet("one fixed end")
    pump = fs.add(U.Pump("P-1"))
    drum = fs.add(U.Vessel("V-1", variant="horizontal"))
    fs.connect(pump.discharge, drum.in_1)
    fs.layout()

    assert len(port_faces(drum, "in_1", drum.frame)) > 1, "in_1 is not movable"
    assert drum.frame is not None and pump.frame is not None
    assert drum.frame.col == pump.frame.col + 1


def test_a_signal_run_states_no_order_along_the_sheet():
    """Issue #430's other half: a wire is not a step along the process.

    Read as one, the controller was pushed a full column east of the
    transmitter and the loop it closed became a cycle the flow graph had
    to be torn to break.
    """
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    ft = fs.add(U.Instrument("FT-101"))
    fic = fs.add(U.Instrument("FIC-101"))
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    signal = fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()

    # No wire is a recycle, because no wire is in the flow graph at all.
    assert [s.name for s in fs.streams if s.is_recycle] == []
    assert not signal.is_recycle
    # The process reads exactly as it does without the loop on it.
    assert prod.frame is not None and valve.frame is not None
    assert prod.frame.col == valve.frame.col + 1
    # And both balloons are drawn, off the grid the equipment is on.
    for balloon in (ft, fic):
        assert balloon.frame is not None
        assert balloon.frame.col is None


def test_a_free_standing_balloon_is_placed_near_what_it_is_wired_to():
    fs = Flowsheet("panel")
    feed = fs.add(U.Feed("Feed"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fic = fs.add(U.Instrument("FIC-101"))
    fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()

    assert fic.frame is not None and valve.frame is not None
    reach = abs(fic.frame.cx - valve.frame.cx) + abs(fic.frame.cy - valve.frame.cy)
    assert reach < 400, "the controller is nowhere near the valve it commands"
    # Near, but not on top of it.
    assert not (
        fic.frame.x < valve.frame.x_max
        and fic.frame.x_max > valve.frame.x
        and fic.frame.y < valve.frame.y_max
        and fic.frame.y_max > valve.frame.y
    )


# --- reserving the space stage 2 will need (#428) ------------------------------


def test_a_chain_of_balloons_is_reserved_paper_before_anything_is_placed():
    """Stage 1 has to leave room for what stage 2 hangs on it.

    Packed as though the sheet were empty, the transmitter and its
    controller land on whatever the next column put beside the plate
    they read.
    """
    fs = Flowsheet("halo")
    feed = fs.add(U.Feed("Feed"))
    plate = fs.add(D.Fitting("FE-101", variant="orifice"))
    valve = fs.add(D.ControlValve("FV-101"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, plate.inlet)
    fs.connect(plate.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    top = fs.add_balloon(plate, at="N", offset=38)
    ft = fs.add_instrument("FT", 101, near=top, at="N", offset=23)
    fs.add_instrument("FIC", 101, near=ft, at="N", offset=60, variant="shared")
    fs.route()

    assert not [i for i in fs.validate() if i.code == "unit-overlap"], (
        "a balloon was drawn over something"
    )


# --- bands (#429) --------------------------------------------------------------


def _long_train(n):
    """*n* blocks in one straight line, each feeding the next."""
    fs = Flowsheet("train")
    port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        block = fs.add(U.Block(f"B-{i}", inputs=["W"], outputs=["E"]))
        fs.connect(port, block.in_1)
        port = block.out_1
    fs.connect(port, fs.add(U.Product("P")).inlet)
    return fs


def test_a_ribbon_wider_than_the_paper_is_folded_into_bands():
    """Issue #429: nothing wrapped, so a big plant became one long run."""
    from pandid.layout.coordinates import BAND_WIDTH

    fs = _long_train(30)
    fs.layout()
    frames = [u.frame for u in fs.units if u.frame is not None]
    width = max(f.x_max for f in frames) - min(f.x for f in frames)
    assert width <= BAND_WIDTH
    # Folded, not squashed: the sheet is several rows of blocks deep.
    assert len({round(f.cy) for f in frames}) > 1


def test_a_ribbon_that_fits_the_paper_is_left_alone():
    """The fold is for a sheet nobody could read, not for every sheet."""
    fs = _long_train(6)
    fs.layout()
    frames = [u.frame for u in fs.units if u.frame is not None]
    assert len({round(f.cy) for f in frames}) == 1


def _pixel_anchored_pump(dx=0, dy=0, vertical=False):
    fs = Flowsheet("Pixel anchors")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("P-1"))
    product = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    if vertical:
        pump.pin(orientation=90)
        feed.pin(x=400 + dx, y=100 + dy, orientation=90)
        product.pin(x=400 + dx, y=700 + dy, orientation=90)
    else:
        feed.pin(x=100 + dx, y=400 + dy)
        product.pin(x=700 + dx, y=400 + dy)
    fs.layout()
    return fs, pump


def test_free_pump_follows_translated_pixel_anchors():
    import pytest

    from pandid.portgeom import port_point

    before_fs, before = _pixel_anchored_pump()
    after_fs, after = _pixel_anchored_pump(dx=1000)
    assert after.frame.x - before.frame.x == pytest.approx(1000)
    assert after.frame.y == pytest.approx(before.frame.y)
    assert 1100 < after.frame.x < after.frame.x_max < 1700
    assert port_point(after_fs.units[0], after_fs.units[0].frame, "outlet") == (1100, 400)
    assert port_point(after_fs.units[-1], after_fs.units[-1].frame, "inlet") == (1700, 400)
    before_fs.to_svg()
    after_fs.to_svg()


def test_vertical_pump_follows_translated_pixel_anchors():
    import pytest

    _, before = _pixel_anchored_pump(vertical=True)
    fs, after = _pixel_anchored_pump(dy=1000, vertical=True)
    assert after.frame.y - before.frame.y == pytest.approx(1000)
    assert after.frame.x == pytest.approx(before.frame.x)
    assert 1100 < after.frame.y < after.frame.y_max < 1700
    fs.to_svg()


def test_partial_pixel_pins_follow_transformed_nozzles_and_preserve_grid_intent():
    import pytest

    from pandid.portgeom import port_point

    def build(dx, dy):
        fs = Flowsheet("Partial transformed anchors")
        pump = fs.add(U.Pump("P-1", width=140, height=100))
        valve = fs.add(D.Valve("V-1"))
        product = fs.add(U.Product("Product"))
        pump.pin(col=1, port="discharge", x=1000 + dx, y=400 + dy, orientation=90, mirrored="x")
        product.pin(row=2, x=1800 + dx)
        fs.connect(pump.discharge, valve.inlet)
        fs.connect(valve.outlet, product.inlet)
        fs.layout()
        return fs, pump, valve, product

    _, _, valve_before, _ = build(0, 0)
    after, pump, valve, product = build(1000, 500)
    assert valve.frame.x - valve_before.frame.x == pytest.approx(1000)
    assert valve.frame.y - valve_before.frame.y == pytest.approx(500)
    assert port_point(pump, pump.frame, "discharge") == pytest.approx((2000, 900))
    assert port_point(product, product.frame, "inlet")[0] == 2800
    assert pump.frame.col == 1
    assert product.frame.row == 2
    assert product.pin_.y is None
    assert (pump.frame.w, pump.frame.h) == (140, 100)
    restored = Flowsheet.from_dict(after.to_dict())
    restored.layout()
    assert restored.to_dict() == after.to_dict()
    expected = [(u.frame.x, u.frame.y) for u in after.units]
    after.layout()
    assert [(u.frame.x, u.frame.y) for u in after.units] == expected
    assert [(u.frame.x, u.frame.y) for u in restored.units] == expected


def test_pixel_anchors_leave_a_disconnected_free_component_in_place():
    def build(dx):
        fs, _ = _pixel_anchored_pump(dx=dx)
        feed = fs.add(U.Feed("Other feed"))
        pump = fs.add(U.Pump("Other pump"))
        fs.connect(feed.outlet, pump.suction)
        fs.layout()
        return [(u.frame.x, u.frame.y) for u in (feed, pump)]

    assert build(0) == build(1000)


def test_conflicting_pixel_pins_are_reported_without_moving_them():
    import pytest

    fs = Flowsheet("Conflicting pixel pins")
    a = fs.add(U.Pump("P-1")).pin(x=400, y=300)
    b = fs.add(U.Pump("P-2")).pin(x=400, y=300)
    fs.connect(a.discharge, b.suction)
    fs.layout()
    assert (a.frame.x, a.frame.y) == (400, 300)
    assert (b.frame.x, b.frame.y) == (400, 300)
    with pytest.raises(ValueError, match="overlap"):
        fs.to_svg()


def test_biodiesel_pixel_refinement_keeps_the_pinned_control_renderable():
    import pytest

    from _layout_cases import build
    from pandid.portgeom import pin_intent

    fs, _ = build()
    fs.to_svg()
    before = {u: (u.frame.x, u.frame.y) for u in fs.units}
    for u in fs.units:
        for axis, (port, value) in pin_intent(u).items():
            u.pin(**{axis: value + 1000}, port=port)
    fs.to_svg()
    for u, (x, y) in before.items():
        assert (u.frame.x, u.frame.y) == pytest.approx((x + 1000, y + 1000)), u.name


def test_pixel_clearance_does_not_move_a_separator_into_a_free_pump():
    fs = Flowsheet("Branched pixel anchors")
    feed = fs.add(U.Feed("F"))
    separator = fs.add(U.Separator("S"))
    first = fs.add(U.Pump("P1"))
    second = fs.add(U.Pump("P2"))
    a = fs.add(U.Product("A"))
    b = fs.add(U.Product("B"))
    fs.connect(feed.outlet, separator.feed)
    fs.connect(separator.vapor, first.suction)
    fs.connect(separator.liquid, second.suction)
    fs.connect(first.discharge, a.inlet)
    fs.connect(second.discharge, b.inlet)
    b.pin(x=450)
    feed.pin(y=200)
    a.pin(x=1400, y=375)
    fs.to_svg()


@pytest.mark.parametrize("skip", ["s103", "dirty_water"])
def test_biodiesel_unpin_matches_a_fresh_build_and_keeps_remaining_pins(skip):
    from _layout_cases import build
    from pandid.portgeom import pin_intent, port_point

    live, units = build()
    live.to_svg()
    units[skip].pin_ = None
    fresh, _ = build(skip=skip)
    assert live.to_svg() == fresh.to_svg()
    assert not [issue for issue in live.validate() if issue.code == "unit-overlap"]
    for unit in live.units:
        for axis, (port, value) in pin_intent(unit).items():
            point = port_point(unit, unit.frame, port) if port else (unit.frame.x, unit.frame.y)
            assert point[0 if axis == "x" else 1] == pytest.approx(value)
    positions = [(u.frame.x, u.frame.y) for u in live.units]
    live.layout()
    assert [(u.frame.x, u.frame.y) for u in live.units] == positions


def test_disconnected_partial_pin_clears_a_fixed_body_on_its_free_axis():
    fs = Flowsheet("Partial pin clearance")
    fixed = fs.add(U.Pump("Fixed")).pin(x=50, y=50)
    free = fs.add(U.Pump("Free")).pin(y=50)
    fs.to_svg()
    assert (fixed.frame.x, fixed.frame.y) == (50, 50)
    assert free.frame.y == 50
    assert free.frame.x_max <= fixed.frame.x or free.frame.x >= fixed.frame.x_max


def test_pin_clearance_uses_drawn_feed_extents_and_transformed_equipment_size():
    from pandid.portgeom import port_point, unit_box

    fs = Flowsheet("Drawn extent clearance")
    feed = fs.add(U.Feed("Long feed label that extends far to the left")).pin(x=300, y=100)
    pump = fs.add(U.Pump("Rotated", width=140, height=90)).pin(y=75, orientation=90, mirrored="x")
    fs.to_svg()
    assert port_point(feed, feed.frame, "outlet") == (300, 100)
    assert (pump.frame.y, pump.frame.w, pump.frame.h) == (75, 140, 90)
    left, right = unit_box(feed, feed.frame), unit_box(pump, pump.frame)
    assert right[2] <= left[0] or right[0] >= left[2]


def test_straightening_preserves_explicit_grid_row_order():
    fs = Flowsheet("Explicit row order")
    source = fs.add(U.Feed("Source")).pin(col=0, row=2)
    top = fs.add(U.Pump("Top")).pin(col=1, row=0)
    middle = fs.add(U.Pump("Middle")).pin(col=2, row=1)
    fs.connect(source.outlet, top.suction)
    fs.to_svg()
    assert (top.frame.row, middle.frame.row, source.frame.row) == (0, 1, 2)
    assert top.frame.y_max <= middle.frame.y < middle.frame.y_max <= source.frame.y


def test_collision_repair_preserves_explicit_grid_row_order():
    fs = Flowsheet("Clearance within explicit rows")
    obstacle = fs.add(U.Pump("Fixed", height=540)).pin(x=50, y=0)
    top = fs.add(U.Pump("Top")).pin(x=50, row=3)
    bottom = fs.add(U.Pump("Bottom")).pin(x=50, row=4)
    fs.to_svg()
    assert (obstacle.frame.x, obstacle.frame.y) == (50, 0)
    assert (top.frame.x, bottom.frame.x) == (50, 50)
    assert (top.frame.row, bottom.frame.row) == (3, 4)
    assert top.frame.y_max <= bottom.frame.y


def test_collision_repair_keeps_an_attached_instrument_clear_with_its_host():
    fs = Flowsheet("Instrument clearance")
    fixed = fs.add(U.Pump("Fixed", width=1500, height=400)).pin(x=0, y=50)
    host = fs.add(U.Pump("Host", width=100, height=100)).pin(x=550)
    fs.connect(fixed.discharge, host.suction)
    fs.add_instrument("LT", 1, sensing=host, at="S", offset=40)
    fs.to_svg()
    assert (fixed.frame.x, fixed.frame.y) == (0, 50)
    assert host.frame.x == 550
    assert not [issue for issue in fs.validate() if issue.code == "unit-overlap"]


def test_collision_repair_can_make_room_between_free_grid_rows():
    fs = Flowsheet("Make room between rows")
    upper = fs.add(U.Pump("Upper")).pin(row=0, x=500)
    middle = fs.add(U.Pump("Middle")).pin(row=1, x=50)
    lower = fs.add(U.Pump("Lower")).pin(row=2, x=500)
    fixed = fs.add(U.Pump("Fixed", height=100)).pin(x=50, y=150)
    fs.to_svg()
    assert (upper.frame.x, middle.frame.x, lower.frame.x) == (500, 50, 500)
    assert (fixed.frame.x, fixed.frame.y) == (50, 150)
    assert upper.frame.y_max <= middle.frame.y < middle.frame.y_max <= lower.frame.y
    positions = [(u.frame.x, u.frame.y) for u in fs.units]
    fs.layout()
    assert [(u.frame.x, u.frame.y) for u in fs.units] == positions


def test_collision_repair_can_make_room_for_two_units_in_one_grid_column():
    fs = Flowsheet("Make room within a column")
    left = fs.add(U.Pump("Left", width=100)).pin(col=0, y=150)
    right = fs.add(U.Pump("Right")).pin(col=2, row=0)
    fixed = fs.add(U.Pump("Fixed", width=50)).pin(x=100, y=50)
    a = fs.add(U.Pump("A", width=50)).pin(col=1, y=50)
    b = fs.add(U.Pump("B", width=70, height=50)).pin(col=1, y=50)
    fs.to_svg()
    assert (fixed.frame.x, fixed.frame.y) == (100, 50)
    assert (left.frame.y, a.frame.y, b.frame.y) == (150, 50, 50)
    assert left.frame.x_max <= min(a.frame.x, b.frame.x)
    assert max(a.frame.x_max, b.frame.x_max) <= right.frame.x
    assert a.frame.x_max <= b.frame.x or b.frame.x_max <= a.frame.x
    assert fixed.frame.x_max < min(a.frame.x, b.frame.x)
