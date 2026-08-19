"""Validation: hard errors raise from render(); soft issues warn."""

import pytest

from pandid import Flowsheet, units as U
from pandid.render.symbols import default_registry
from pandid.validate import OFFSET_BY_DESIGN


def test_overlapping_pins_raise():
    fs = Flowsheet("overlap")
    a = fs.add(U.Reactor("R1")).pin(x=100, y=100)
    b = fs.add(U.Reactor("R2")).pin(x=110, y=110)  # sits on top of R1
    fs.connect(a.outlet, b.feed)
    with pytest.raises(ValueError, match="overlap"):
        fs.to_svg()


def test_negative_pin_raises():
    fs = Flowsheet("oob")
    a = fs.add(U.Feed("F")).pin(x=-50, y=10)
    b = fs.add(U.Product("P")).pin(x=200, y=10)
    fs.connect(a.outlet, b.inlet)
    with pytest.raises(ValueError, match="negative|off-sheet"):
        fs.to_svg()


def test_check_false_bypasses_validation():
    fs = Flowsheet("overlap-bypass")
    a = fs.add(U.Reactor("R1")).pin(x=100, y=100)
    b = fs.add(U.Reactor("R2")).pin(x=110, y=110)
    fs.connect(a.outlet, b.feed)
    svg = fs.to_svg(check=False)  # must not raise
    assert "<svg" in svg


def test_clean_flowsheet_has_no_errors():
    fs = Flowsheet("clean")
    f = fs.add(U.Feed("F"))
    r = fs.add(U.Reactor("R"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, r.feed)
    fs.connect(r.outlet, p.inlet)
    fs.layout()
    fs.route()
    errors = [i for i in fs.validate() if i.severity == "error"]
    assert errors == []


# --- coincident connected ports ----------------------------------------------


def _loop_with_a_balloon():
    """A controller taking a signal in and driving a valve, plus its process tap.

    A balloon is a circle, so all three of its connections offer all four faces
    and the symbol-level duplicate-nozzle check must let those menus overlap.
    Which placement each one actually took is only visible on a laid-out sheet.
    """
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=300, y=180)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    lt = fs.add(U.Instrument("LT-101")).pin(x=300, y=400)
    lic = fs.add(U.Instrument("LIC-101", display="central")).pin(x=300, y=520)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    return fs, lic


def test_two_live_connections_on_one_point_are_an_error():
    fs, lic = _loop_with_a_balloon()
    # Both named, because an override is the only way onto one point: the engine
    # picks a free face for anything the author leaves open.
    lic.nozzle("sig_in", "W")
    lic.nozzle("sig_out", "W")
    fs.layout()
    errors = [i for i in fs.validate() if i.severity == "error"]
    assert [i.code for i in errors] == ["coincident-ports"]
    assert "LIC-101.sig_in and LIC-101.sig_out" in errors[0].message
    with pytest.raises(ValueError, match="coincident-ports"):
        fs.to_svg()


def test_distinct_placements_on_the_same_balloon_are_fine():
    fs, lic = _loop_with_a_balloon()
    lic.nozzle("sig_out", "N")
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []


def test_ports_the_symbol_never_anchored_warn_rather_than_raise(gapped_kind):
    """Ports a symbol does not anchor fall back to the centre of the box, so
    they coincide by construction. That is a gap in the symbol, not a
    contradiction on the sheet, and must not stop rendering."""
    fs = Flowsheet("gapped")
    unit = fs.add(gapped_kind("G-1"))
    prod = fs.add(U.Product("P"))
    for port in ("inlet", "spare_a", "spare_b"):
        feed = fs.add(U.Feed(f"F-{port}"))
        fs.connect(feed.outlet, unit.ports[port])
    fs.connect(unit.outlet, prod.inlet)
    fs.layout()
    issues = [i for i in fs.validate() if i.code == "coincident-ports"]
    assert [i.severity for i in issues] == ["warning"]
    assert "anchors no nozzle" in issues[0].message
    fs.to_svg()  # must not raise


def test_an_extractive_towers_feeds_get_nozzles_of_their_own():
    """The solvent enters above the feed tray: two real nozzles down the shell,
    not two streams landing on one point in the middle of the tower."""
    fs = Flowsheet("extractive")
    col = fs.add(U.Column("T-302", n_feeds=2))
    for port in ("feed_1", "feed_2"):
        feed = fs.add(U.Feed(port))
        fs.connect(feed.outlet, col.ports[port])
    fs.connect(col.distillate, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []
    fs.to_svg()  # must not raise


def test_two_feeds_pinned_to_the_same_stage_are_coincident():
    """``feed_stages=`` is a placement rule like any other a
    :class:`~pandid.render.symbols.PortSeries` resolves, so two feeds
    asked for the same stage land on the same point and the existing
    check catches it -- no code of its own is needed."""
    fs = Flowsheet("same-stage")
    col = fs.add(
        U.Column("T-302", internals="valve_tray", trays=30, n_feeds=2, feed_stages=[12, 12])
    )
    for port in ("feed_1", "feed_2"):
        feed = fs.add(U.Feed(port))
        fs.connect(feed.outlet, col.ports[port])
    fs.layout()
    errors = [i for i in fs.validate() if i.severity == "error"]
    assert [i.code for i in errors] == ["coincident-ports"]
    assert "T-302.feed_1 and T-302.feed_2" in errors[0].message
    with pytest.raises(ValueError, match="coincident-ports"):
        fs.to_svg()


def test_a_kettle_takes_its_bottoms_off_its_own_draw():
    """The draw is a nozzle of the reboiler's, so a tower can hand it the sump
    and take product back without an imaginary splitter in between."""
    fs = Flowsheet("reboiler")
    col = fs.add(U.Column("T-701"))
    reb = fs.add(U.HeatExchanger("E-702", variant="kettle"))
    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, draw_as_recycle=True)
    fs.connect(reb.bottoms, fs.add(U.Product("Bottoms")).inlet)
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []
    fs.to_svg()  # must not raise


def test_a_mixers_extra_inlets_get_nozzles_of_their_own():
    """A third inlet is a real nozzle on the flat face, not a third stream
    landing in the middle of the symbol on the box-centre fallback."""
    fs = Flowsheet("wide-mixer")
    mix = fs.add(U.Mixer("M-1", n_inlets=4))
    prod = fs.add(U.Product("P"))
    for i in range(1, 5):
        feed = fs.add(U.Feed(f"F{i}"))
        fs.connect(feed.outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, prod.inlet)
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []


# --- near-miss run elevations -------------------------------------------------


def _off_elevation(fs):
    return [i for i in fs.validate() if i.code == "run-off-elevation"]


def _corner_pinned_run(fv_y=180.0):
    """The real bug, from an earlier draft of examples/04.

    A control valve is 19.8 tall and carries its body under the diaphragm
    actuator, so its nozzles sit 12.4 below the corner ``pin()`` reads; a vessel
    takes its inlet at mid-height, 50 below. Pinning both to convenient corner
    values silently puts the two nozzles on different elevations, and the router
    draws a step into the valve and a step back out.
    """
    fs = Flowsheet("corner-pinned")
    feed = fs.add(U.Feed("Feed")).pin(x=110, y=195)
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=270, y=fv_y)
    drum = fs.add(U.Vessel("V-101")).pin(x=420, y=145)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    return fs, fv


def test_a_corner_pinned_inline_device_is_reported_off_the_run():
    fs, _ = _corner_pinned_run()
    fs.layout()
    issues = _off_elevation(fs)
    assert [i.severity for i in issues] == ["warning", "warning"]
    assert "2.6px apart" in issues[0].message
    # The finding is only worth making if it also says what to do about it, the
    # way gravity-turned names the lying drum.
    assert "FV-101.pin(port='inlet', y=195)" in issues[0].message


def test_pinning_the_nozzle_is_the_cure_the_message_names():
    """Typing the message's own suggestion back in has to silence it, or the
    advice is wrong. 195 is the drum's inlet and the feed flag's tip alike."""
    fs, fv = _corner_pinned_run()
    fv.pin(x=270, port="inlet", y=195)
    fs.layout()
    assert _off_elevation(fs) == []


def test_a_deliberate_elevation_change_is_not_a_near_miss():
    """Two vessels on genuinely different levels, with the run stepping 300px
    between them. That is engineering, not arithmetic, and must stay silent."""
    fs = Flowsheet("two-levels")
    upper = fs.add(U.Vessel("V-1")).pin(x=100, y=100)
    lower = fs.add(U.Vessel("V-2")).pin(x=400, y=400)
    fs.connect(upper.outlet, lower.inlet)
    fs.layout()
    assert _off_elevation(fs) == []


def test_an_eccentric_reducer_is_meant_to_change_centreline():
    """Its small end is drawn higher than its large end on purpose -- that is
    what keeps a pump suction from pocketing vapour against the roof of the
    line. Straightening the run through it would undo the fitting."""
    fs = Flowsheet("eccentric")
    feed = fs.add(U.Feed("F")).pin(x=60, port="outlet", y=300)
    red = fs.add(U.Reducer("R-1", variant="eccentric")).pin(x=300, port="inlet", y=300)
    prod = fs.add(U.Product("P")).pin(x=600, port="inlet", y=300)
    fs.connect(feed.outlet, red.inlet)
    fs.connect(red.outlet, prod.inlet)
    fs.layout()
    assert _off_elevation(fs) == []


def test_a_concentric_reducer_in_the_same_run_is_not_exempt():
    """The exemption is the eccentric fitting's, not the reducer kind's: a
    concentric one keeps both ends on one centreline, so nothing about it needs
    excusing and the sweep above would not notice if it were excused anyway."""
    assert ("reducer", "concentric") not in OFFSET_BY_DESIGN
    assert ("reducer", "default") not in OFFSET_BY_DESIGN


@pytest.mark.parametrize("variant", ["angle", "psv", "relief"])
def test_a_relief_valve_needs_no_entry_in_the_exemption_set(variant):
    """None of the three has a step to be excused for.

    The angle valve and the PSV turn the run a quarter, so no placement puts
    both their nozzles along one elevation at all and the face test in
    ``_off_elevation`` never even reaches them. The relief valve is different
    and worth the parametrize: laid on its side it *does* offer a horizontal
    pair, and the pair is level, so there is still nothing to excuse.

    That is the property OFFSET_BY_DESIGN would otherwise have to cover, and it
    is asserted over every turn rather than taken on faith: a name in that set
    is a rule with no geometry behind it, which is how such a set grows
    silently. Compare the eccentric reducer, which fails this and is listed.
    """
    from pandid.geometry import Pin
    from pandid.portgeom import port_faces, port_offset

    assert ("valve", variant) not in OFFSET_BY_DESIGN
    valve = U.Valve("HV-1", variant=variant)
    for turn in (0, 90, 180, 270):
        placed = Pin(x=0.0, y=0.0, orientation=turn)
        faces = {n: port_faces(valve, n, placed)[0] for n in ("inlet", "outlet")}
        if not set(faces.values()) <= {"E", "W"}:
            continue  # a quarter-turn device: not a run at one elevation
        ys = [port_offset(valve, n, placed)[1] for n in ("inlet", "outlet")]
        assert ys[0] == pytest.approx(ys[1]), (variant, turn, faces, ys)


def test_the_eccentric_reducer_is_the_one_that_fails_that_test():
    """The counterpart, and the reason the set is not empty: laid in a run its
    two nozzles are both along it *and* on different centrelines."""
    from pandid.geometry import Pin
    from pandid.portgeom import port_faces, port_offset

    red = U.Reducer("R-1", variant="eccentric")
    placed = Pin(x=0.0, y=0.0)
    assert {port_faces(red, n, placed)[0] for n in ("inlet", "outlet")} == {"E", "W"}
    ys = [port_offset(red, n, placed)[1] for n in ("inlet", "outlet")]
    assert ys[0] != pytest.approx(ys[1])
    assert ("reducer", "eccentric") in OFFSET_BY_DESIGN


def test_an_unpinned_sheet_keeps_its_elevations_to_itself():
    """Nothing here was placed by hand, so there is no arithmetic to have got
    wrong and no pin to correct. Telling an author to pin a nozzle they never
    positioned is telling them to hand-place a sheet that did not ask for it."""
    fs = Flowsheet("auto")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    drum = fs.add(U.Vessel("V-1"))
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.layout()
    assert _off_elevation(fs) == []


def test_a_signal_line_has_no_elevation_to_be_off():
    """A signal carries a measurement, not a fluid. Its balloon end is placed by
    add_instrument(), so there is no pin() to name either."""
    fs = Flowsheet("signal")
    fv = fs.add(U.Valve("FV-1", variant="control")).pin(x=270, y=180)
    drum = fs.add(U.Vessel("V-1")).pin(x=420, y=145)
    prod = fs.add(U.Product("P")).pin(x=700, port="inlet", y=195)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    lic = fs.add_instrument("LIC", 101, sensing=drum, at="S", offset=90, display="central")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    assert [i.message for i in _off_elevation(fs) if "LIC" in i.message] == []


def test_a_vertical_drop_is_a_runs_length_and_not_a_miss():
    """A tank draining into the roof of the one below it. Both nozzles face
    along the drop, so the difference in y is how far the line *falls*; a riser
    reported as 300px off its elevation would be absurd. The 5px they are apart
    in x is a plan offset and not an elevation at all, which is why the check
    reads the faces rather than taking the smaller of the two differences.
    """
    fs = Flowsheet("drop")
    upper = fs.add(U.Tank("TK-1")).pin(x=200, y=100)
    lower = fs.add(U.Tank("TK-2")).pin(x=205, y=500)
    fs.connect(upper.outlet, lower.inlet)
    fs.layout()
    assert _off_elevation(fs) == []


# --- a counted nozzle with no line on it --------------------------------------


def _unpiped(fs, **kw):
    return [i for i in fs.validate(**kw) if i.code == "nozzle-unconnected"]


def _mixer(n_inlets, wired):
    """A mixer built for *n_inlets* with only *wired* of them piped."""
    fs = Flowsheet("unpiped")
    mix = fs.add(U.Mixer("M-101", n_inlets=n_inlets))
    for i in wired:
        fs.connect(fs.add(U.Feed(f"F-{i}")).outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    return fs, mix


def test_the_off_by_one_that_started_this():
    """Issue #183, written the way the user wrote it: ``m.inlets`` is indexed
    from zero and the nozzles are numbered from one, so a loop over ``(1, 2, 3)``
    meaning ``in_1``, ``in_2``, ``in_3`` wires ``in_2``, ``in_3`` and ``in_4``.
    Before this finding the sheet drew, nothing raised and ``validate()`` was
    empty."""
    fs = Flowsheet("183")
    mix = fs.add(U.Mixer("M-101", n_inlets=4))
    for i in (1, 2, 3):
        fs.connect(fs.add(U.Feed(f"F-{i}")).outlet, mix.inlets[i])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    issues = _unpiped(fs)
    assert [i.severity for i in issues] == ["warning"]
    assert "M-101.in_1 carries no stream" in issues[0].message
    # The arithmetic, so the author can see which of the two things happened.
    assert "built with 4 numbered nozzles, in_1..in_4, and 3 of them are piped" in issues[0].message
    assert "asserts 4 connections and draws 3" in issues[0].message
    # Both cures, because the finding cannot tell which was meant.
    assert "Connect it, or build M-101 with the 3 it uses." in issues[0].message


def test_wiring_the_nozzle_is_the_cure():
    """Doing what the message says has to silence it, or the advice is wrong."""
    assert _unpiped(_mixer(4, (1, 2, 3, 4))[0]) == []


def test_the_other_cure_is_the_count():
    """The second half of the same sentence: a mixer built for the three it
    uses is the same sheet with nothing left over to report."""
    assert _unpiped(_mixer(3, (1, 2, 3))[0]) == []


def test_it_is_reported_before_layout_has_run():
    """A connectivity fact needs no frames, and the call in the issue is a bare
    ``fs.validate()`` on a flowsheet nobody has laid out. Reporting it only
    after a render would answer a different question from the one asked."""
    fs, mix = _mixer(4, (2, 3, 4))
    assert all(u.frame is None for u in fs.units)
    assert len(_unpiped(fs)) == 1
    fs.layout()
    assert len(_unpiped(fs)) == 1  # and the same one afterwards


def test_two_loose_nozzles_on_one_unit_are_one_finding():
    """One wrong count with one thing to do about it, said once -- the way
    ``letter-sequence`` says a repeated tag once and ``nozzles-crowded``
    reports a face rather than each pair on it."""
    fs, _ = _mixer(4, (2, 3))
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "M-101.in_1 and M-101.in_4 carry no stream" in issues[0].message
    assert "Connect them, or build M-101 with the 2 it uses." in issues[0].message


def test_a_family_with_nothing_on_it_is_not_offered_a_count():
    """Telling an author to build M-101 with the 0 it uses is not advice. A
    mixer nothing is piped to has a different problem from a mixer that is one
    line short, so the sentence changes rather than doing the arithmetic and
    reading a zero out of it."""
    fs, _ = _mixer(2, ())
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "0 of them are piped" in issues[0].message
    assert "Connect them: nothing is piped to M-101 at all." in issues[0].message


def test_a_splitter_counts_its_outlets_the_same_way():
    fs = Flowsheet("split")
    sp = fs.add(U.Splitter("SP-1", n_outlets=3))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    for i in (1, 2):
        fs.connect(sp.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "SP-1.out_3 carries no stream" in issues[0].message


def test_a_block_is_caught_though_its_symbol_has_no_series():
    """The reason the check reads the *unit's* ports and not the symbol's
    :class:`PortSeries`. A block's family is split across up to four faces and
    one series cannot put ``in_3`` on a face its ``in_1`` is not on, so
    ``block_symbol`` authors an anchor per connection and there is no series to
    ask. A block's ``in_2`` is a counted nozzle all the same, and a block is the
    one class whose *entire* connection list is counted."""
    from pandid.render.symbols import default_registry

    fs = Flowsheet("bfd")
    blk = fs.add(U.Block("Reaction", inputs=["W", "W", "N"], outputs=2))
    fs.connect(fs.add(U.Feed("F")).outlet, blk.in_1)
    fs.connect(blk.out_1, fs.add(U.Product("P")).inlet)
    assert default_registry.for_unit(blk).port_series == ()  # nothing to borrow
    issues = _unpiped(fs)
    assert len(issues) == 2  # one per family, not one per unit
    assert "Reaction.in_2 and Reaction.in_3 carry no stream" in issues[0].message
    assert "Reaction.out_2 carries no stream" in issues[1].message


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_a_vessels_spare_relief_and_drain_are_not_reported(cls):
    """The other half of "only counted nozzles", on the case #222 added.

    A vessel and a tank each carry five connections and a sheet typically pipes
    two. Those three are *offered* -- CHEE4001 p.7 says where a relief goes, not
    that one must be drawn -- exactly as a vessel's ``vent`` has been offered
    since 0.1.0 and is one of the 7 unpiped vents this finding was measured
    against. Had #222 answered with a count instead (``Tank(outlets=3)``) every
    one of them would report here, which is the concrete cost of the API this
    file's rule would have made the wrong one.
    """
    fs = Flowsheet("holdup")
    u = fs.add(cls("V-1"))
    fs.connect(fs.add(U.Feed("F")).outlet, u.inlet)
    fs.connect(u.outlet, fs.add(U.Product("P")).inlet)
    assert _unpiped(fs) == []
    assert [n for n in u.ports if u.ports[n].stream is None] == ["vent", "relief", "drain"]


def test_a_column_counts_its_feeds():
    fs = Flowsheet("col")
    col = fs.add(U.Column("T-1", n_feeds=3))
    fs.connect(fs.add(U.Feed("F")).outlet, col.feeds[0])
    fs.connect(col.distillate, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "T-1.feed_2 and T-1.feed_3 carry no stream" in issues[0].message
    assert "feed_1..feed_3, and 1 of them is piped" in issues[0].message


def test_the_singular_spelling_of_a_family_is_not_counted():
    """A one-feed column's nozzle is called ``feed`` and not ``feed_1``, and
    that spelling is the whole difference: it is declared as a class annotation
    beside ``distillate`` and ``bottoms``, like any other fixed nozzle, and no
    count was ever written down for it. ``n_feeds`` is what spells the family,
    and only then is there a number to have failed to meet."""
    fs = Flowsheet("col1")
    col = fs.add(U.Column("T-2"))
    fs.connect(col.distillate, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    assert "feed" in col.ports and "feed_1" not in col.ports
    assert _unpiped(fs) == []


def test_a_family_of_one_is_still_a_family():
    """``n_inlets=1`` is a count somebody wrote, and the nozzle it produces is
    spelled ``in_1``. The singular exemption above is about the *name*, which is
    what records whether a count was asked for, and not about the arity."""
    fs, _ = _mixer(1, ())
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "built with 1 numbered nozzle, in_1" in issues[0].message


def test_a_family_with_a_number_missing_is_listed_and_not_ranged():
    """No constructor here can build one, but a hand-written ``PORTS`` list can,
    and ``in_1..in_7`` said of four nozzles would be the message inventing three
    the unit does not have. The range is only used where the run really is 1 to
    n; anything else is named member by member."""

    class Odd(U.Unit):
        kind = "unit"
        PORTS = [
            ("in_1", "inlet", "process"),
            ("in_2", "inlet", "process"),
            ("in_4", "inlet", "process"),
            ("in_7", "inlet", "process"),
        ]

    fs = Flowsheet("ragged")
    fs.add(Odd("X-1"))
    message = _unpiped(fs)[0].message
    assert "4 numbered nozzles, in_1, in_2, in_4 and in_7" in message
    assert ".." not in message


def test_a_spec_built_sheet_is_checked_too():
    """``08_from_data`` builds its mixer from a mapping, and ``n_inlets`` is a
    spec field like any other, so a count written in YAML is a count this reads."""
    from pandid.spec import from_dict

    fs = from_dict(
        {
            "name": "spec",
            "units": [
                {"kind": "Mixer", "name": "M-1", "n_inlets": 3},
                {"kind": "Feed", "name": "F1"},
                {"kind": "Product", "name": "P1"},
            ],
            "streams": [
                {"from": ["F1", "outlet"], "to": ["M-1", "in_1"]},
                {"from": ["M-1", "outlet"], "to": ["P1", "inlet"]},
            ],
        }
    )
    assert "M-1.in_2 and M-1.in_3 carry no stream" in _unpiped(fs)[0].message
    # ...and it survives the round trip, since to_dict() writes the count back.
    assert [i.code for i in from_dict(fs.to_dict()).validate()] == ["nozzle-unconnected"]


@pytest.mark.parametrize(
    "build,bare",
    [
        # The false positives, one per family, taken from what the sixteen shipped
        # examples actually leave open. Each is a nozzle its *class* declares --
        # offered to every instance whether a sheet uses it or not -- so leaving it
        # open is a drawing decision and not a count that went unmet.
        (lambda fs: fs.add(U.HeatExchanger("E-1")), "tube_in"),  # 26 of them
        (lambda fs: fs.add(U.Reactor("R-1")), "duty"),  # a duty
        (lambda fs: fs.add(U.Reactor("R-1")), "vent"),  # an off-gas
        (lambda fs: fs.add(U.Vessel("V-1")), "vent"),
        (lambda fs: fs.add(U.Column("T-1")), "reboiler_duty"),
        (lambda fs: fs.add(U.Valve("HV-1")), "outlet"),  # a drain leg
        (lambda fs: fs.add(U.Separator("S-1")), "vapor"),
        (lambda fs: fs.add(U.Ejector("EJ-1")), "motive"),
        # The wash and the cake a cake-forming filter offers. Both are per
        # variant rather than per class, which is a second way of being
        # declared and not a count: no number was written down, so there is
        # nothing for a bare one to have failed to meet.
        (lambda fs: fs.add(U.Filter("F-1", variant="press")), "wash_in"),
        (lambda fs: fs.add(U.Filter("F-1", variant="press")), "cake"),
        (lambda fs: fs.add(U.Filter("F-1", variant="ion_exchange")), "regenerant_in"),
        (lambda fs: fs.add(U.Filter("F-1", variant="ion_exchange")), "spent_regenerant"),
    ],
)
def test_a_nozzle_the_class_declares_is_never_counted(build, bare):
    """276 ports carry no stream across the sixteen shipped examples and every
    one of them is one of these. The drain valve is the plainest: "a drain runs
    down to a funnel on the floor, which is not on this sheet, so the leg ends
    at the valve", in ``add_valve_station``'s own words, and its outlet is bare
    eight times on ``11_ethanol_pid`` alone."""
    fs = Flowsheet("declared")
    unit = build(fs)
    assert unit.ports[bare].stream is None
    assert _unpiped(fs) == []


def test_a_press_that_takes_no_wash_is_a_clean_sheet():
    """The whole sheet, not just this finding, on the case adding the nozzles
    could have broken.

    Plenty of presses are run without a displacement wash, and plenty of sheets
    draw the filtrate and let the cake fall to a bin off the drawing. Neither
    author asked for a wash line, so neither should be told about one -- and a
    warning nobody can act on is how a checker stops being read.
    """
    fs = Flowsheet("press")
    press = fs.add(U.Filter("F-301", variant="press"))
    fs.connect(fs.add(U.Feed("Slurry")).outlet, press.port("inlet"))
    fs.connect(press.port("outlet"), fs.add(U.Product("Filtrate")).inlet)
    assert [n for n in press.ports if press.ports[n].stream is None] == ["wash_in", "cake"]
    assert fs.validate() == []
    # ...and piping the cake and still no wash is equally quiet, which is the
    # commoner sheet of the two.
    fs.connect(press.port("cake"), fs.add(U.Product("Cake")).inlet)
    assert fs.validate() == []


def test_a_numbered_signal_family_is_out_of_scope():
    """Signal ports are a different question and this finding does not answer
    it. A balloon's ``pv`` is bare on 51 of those 252 because an instrument may
    be *placed* against its equipment rather than drawn tapped off a line, and
    an actuator with nothing on it is a hand valve; neither is settled by
    counting. No shipped class numbers a signal port, so the scope is stated
    against a unit of the kind ``docs/api.md`` tells a user to write."""

    class Marshalling(U.Unit):
        kind = "marshalling"
        PORTS = [
            ("sig_1", "inlet", "signal"),
            ("sig_2", "inlet", "signal"),
            ("in_1", "inlet", "process"),
            ("in_2", "inlet", "process"),
        ]

    fs = Flowsheet("signals")
    box = fs.add(Marshalling("JB-1"))
    fs.connect(fs.add(U.Feed("F")).outlet, box.port("in_1"))
    # Two counted families on one unit, both a nozzle short. Only the process
    # one is reported, and the signal pair is not so much as named.
    issues = _unpiped(fs)
    assert len(issues) == 1
    assert "JB-1.in_2 carries no stream" in issues[0].message
    assert "sig_" not in issues[0].message


@pytest.mark.parametrize(
    "name,stem",
    [
        ("in_1", "in"),
        ("in_12", "in"),
        ("out_3", "out"),
        ("feed_2", "feed"),
        ("inlet", None),
        ("outlet", None),
        ("sig_in", None),
        ("sig_out", None),
        ("tube_in", None),
        ("shell_out", None),
        ("feed", None),
        ("pv", None),
        ("reboiler_duty", None),
        ("normally_closed", None),
        ("_1", None),
    ],
)
def test_what_the_naming_rule_reads(name, stem):
    """The one rule the finding turns on, held to the nozzle names the package
    really ships. ``tube_in`` and ``sig_out`` are the pair worth pinning: both
    end in a word after an underscore, and a rule that split on the underscore
    without asking for digits would count them."""
    from pandid.validate import _family_stem

    assert _family_stem(name) == stem


@pytest.mark.parametrize(
    "build,stem,size",
    [
        (lambda: U.Mixer("M", n_inlets=4), "in", 4),
        (lambda: U.Splitter("S", n_outlets=3), "out", 3),
        (lambda: U.Column("T", n_feeds=2), "feed", 2),
        (lambda: U.Reactor("R", n_feeds=5), "feed", 5),
        (lambda: U.Block("B", inputs=["W", "N", "N"], outputs=1), "in", 3),
        (lambda: U.Block("B", inputs=1, outputs=2), "out", 2),
    ],
)
def test_every_counted_family_answers_to_the_naming_rule(build, stem, size):
    """The five classes ``tests/test_port_annotations._DECLARED_FAMILIES`` pins,
    against the rule this finding reads them with. A sixth class that numbered
    its nozzles some other way would be invisible here, so the tie is made
    rather than assumed -- the same reason the ``OFFSET_BY_DESIGN`` sweep
    measures the geometry instead of taking the exemption on faith."""
    from pandid.validate import _family_stem

    unit = build()
    members = [n for n in unit.ports if _family_stem(n) == stem]
    assert len(members) == size


def test_nothing_shipped_leaves_a_counted_nozzle_open():
    """The acceptance test, over the drawings this package stands behind. 47
    counted nozzles across eleven of the shipped sheets, and every one of them
    piped -- so the rule is exercised by the corpus rather than merely silent on
    it. ``14_tank_farm`` contributes one, the second signal output its cascade
    master mints; ``15_condensing_turbine`` three, a two-outlet steam splitter
    and the same second output on its level controller;
    ``19_absorber_stripper`` two, the contactor's counter-current feeds;
    ``21_alumina_refinery`` six, the three inlets of each of its two mixing
    tanks."""
    from tests.test_golden import SCENARIOS

    offenders, counted = [], 0
    for name, (build, kwargs) in SCENARIOS.items():
        fs = build()
        fs.to_svg(**kwargs)
        counted += sum(_family_members(u) for u in fs.units)
        offenders += [f"{name}: {w.message}" for w in fs.warnings if w.code == "nozzle-unconnected"]
    assert offenders == []
    assert counted == 47


def _family_members(unit):
    from pandid.validate import _family_stem

    return sum(_family_stem(n) is not None for n in unit.ports)


# --- nozzles crowded under their own arrowheads -------------------------------


def _crowded(fs, **kw):
    return [i for i in fs.validate(**kw) if i.code == "nozzles-crowded"]


def _fed_mixer(n_inlets=2, **box):
    """A mixer taking its feeds on one face, which is where this defect lives.

    The mixer symbol is 50px tall and spreads its inlet series 20px apart in its
    own coordinates, and the drawn pitch is that scaled by the box: at the
    default size two feeds land 20px apart, which is 8px of paper between two
    12px arrowheads and perfectly legible. ``height=35`` is the same two nozzles
    in the short box an author gave them, 14px apart with 2px between the heads.
    """
    fs = Flowsheet("crowded")
    mix = fs.add(U.Mixer("M-1", n_inlets=n_inlets, **box))
    for i in range(1, n_inlets + 1):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    fs.layout()
    return fs, mix


def test_two_heads_without_the_paper_between_them_are_reported():
    fs, _ = _fed_mixer(height=35)
    issues = _crowded(fs)
    assert [i.severity for i in issues] == ["warning"]
    assert "M-1.in_1 and M-1.in_2 are 14.0px apart on M-1's W face" in issues[0].message
    # The measurement a reader can check: the white, against the standard.
    assert "leaves 2.0px of paper between two 12px arrowheads" in issues[0].message
    assert "4px ISO 128-20:1996 4.4" in issues[0].message
    # The finding is only worth making if it also says what to do about it, the
    # way run-off-elevation names the pin.
    assert "M-1.height = 40" in issues[0].message


def test_the_box_the_message_names_is_the_cure():
    """Typing the message's own suggestion back in has to silence it, or the
    advice is wrong. 40 is the 35px box scaled by the 16/14 it fell short by."""
    fs, _ = _fed_mixer(height=40)
    assert _crowded(fs) == []


def test_a_default_mixer_is_not_a_finding():
    """The pitch this check must *not* report, and the reason it is stated as a
    clearance rather than as a multiple of the head. Two heads 20px apart leave
    8px of paper, four times the weight the sheet draws a process line at, and a
    reader resolves them without effort. A floor that reported this would fire
    on five of the sixteen shipped examples -- 01, 03, 05 and 10 carry a mixer at
    this same 20px pitch, and 08's takes three feeds 17.5px apart -- and be
    wrong about all five: the tightest of them still leaves 5.5px of paper, over
    the 4px ISO 128-20:1996 4.4 asks for."""
    fs, _ = _fed_mixer()
    assert _crowded(fs) == []


def test_overlapping_heads_are_worded_as_the_overlap_they_are():
    """Four inlets squeezed onto a 50px face land 11.7px apart, so the heads are
    not merely close: they are drawn over each other. Quoting a clearance of
    "-0.3px" would be arithmetic rather than a description."""
    fs, _ = _fed_mixer(n_inlets=4)
    issues = _crowded(fs)
    assert len(issues) == 1
    assert "overlaps two 12px arrowheads by 0.3px" in issues[0].message
    assert "the tightest of the 4 it carries there" in issues[0].message


def test_a_third_nozzle_on_one_face_is_still_one_finding():
    """Three heads on one face is one crowded face with one thing to do about
    it, so it is said once -- the way letter-sequence says a repeated tag once."""
    fs, _ = _fed_mixer(n_inlets=3, height=35)
    issues = _crowded(fs)
    assert len(issues) == 1
    assert "the tightest of the 3 it carries there" in issues[0].message


def test_nozzles_that_carry_no_arrowhead_are_not_crowded():
    """A splitter's outlets in the same short box sit at the same 14px pitch a
    mixer's inlets are reported at, and the sheet reads them without trouble: a
    stream *leaving* takes its head at the far end of the branch, so the face
    carries two bare 2px lines rather than two 12px triangles. One pitch, two
    drawings, and only the one with the heads on it is a drawing that misleads."""
    from pandid.portgeom import port_point

    fs = Flowsheet("splitter")
    sp = fs.add(U.Splitter("SP-1", n_outlets=2, height=35))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    for i in (1, 2):
        fs.connect(sp.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    fs.layout()
    ys = [port_point(sp, sp.frame, f"out_{i}")[1] for i in (1, 2)]
    assert abs(ys[1] - ys[0]) == 14.0  # the pitch the mixer above is reported at
    assert _crowded(fs) == []


def test_a_p_and_id_draws_no_head_to_be_crowded_by():
    """The finding is about ink, and a P&ID draws none of it: ANSI/ISA-5.1 puts
    no arrowhead on process piping, so nozzles inside a head that is not there
    are not a defect. Reporting one would be advice to make a unit 50% taller to
    fix a drawing that is already right."""
    fs, _ = _fed_mixer(height=35)
    assert len(_crowded(fs, diagram="pfd")) == 1  # the same sheet as a PFD
    assert _crowded(fs, diagram="p&id") == []
    assert _crowded(fs, diagram="pid") == []  # the other spelling
    # ...and the warnings a render leaves behind are about the sheet it drew.
    fs.to_svg(diagram="p&id")
    assert [w for w in fs.warnings if w.code == "nozzles-crowded"] == []
    assert "marker-end" not in fs.to_svg(diagram="p&id")
    fs.to_svg()
    assert len([w for w in fs.warnings if w.code == "nozzles-crowded"]) == 1


def test_the_floor_is_the_arrowhead_the_renderer_actually_draws():
    """Not a number this module picked. The head the marker is drawn at, the
    clearance beside it and the weight the clearance is twice of are all read
    back off the sheet or off the renderer, so redrawing any of them moves the
    floor rather than leaving the two to drift apart."""
    import re

    from pandid.render.svg import _PROCESS_STROKE
    from pandid.render.symbols import ARROWHEAD, MIN_HEAD_CLEARANCE, MIN_NOZZLE_PITCH

    fs, _ = _fed_mixer()
    drawn = re.search(
        r'<marker id="arrow_[^"]*"[^>]*markerWidth="([\d.]+)" '
        r'markerHeight="([\d.]+)"',
        fs.to_svg(),
    )
    assert drawn is not None
    assert [float(v) for v in drawn.groups()] == [ARROWHEAD, ARROWHEAD]
    # ISO 128-20:1996 4.4: at least twice the width of the widest line.
    assert MIN_HEAD_CLEARANCE == 2 * _PROCESS_STROKE
    assert MIN_NOZZLE_PITCH == ARROWHEAD + MIN_HEAD_CLEARANCE


def test_the_pitch_a_block_chooses_clears_the_floor_this_check_enforces():
    """The two arrowhead-derived pitches say different things and are separate
    names for that reason: ``MIN_NOZZLE_PITCH`` is where a drawing becomes wrong,
    ``BLOCK_PITCH`` is what a symbol free to size itself picks. A target has to
    clear its own floor, and a block flow diagram is the case that gathers the
    most streams onto one face, so it is the one that would find out first.

    Asserted rather than assumed: the two are edited by different concerns, and
    lowering either without looking at the other is exactly the change that
    would ship a symbol whose own nozzles this check then reports.
    """
    from pandid.render.symbols import BLOCK_PITCH, MIN_NOZZLE_PITCH

    assert BLOCK_PITCH >= MIN_NOZZLE_PITCH


def test_a_block_gathering_streams_onto_one_face_is_not_crowded():
    """The same claim on a drawn sheet rather than on the constants. A block is
    the first unit for which N/S process connections are ordinary, and it sizes
    itself to its nozzles, so a crowded one would mean the two rules disagree."""
    fs = Flowsheet("bfd")
    block = fs.add(U.Block("U-100", inputs=["W"] * 4 + ["N"] * 3, outputs=["E"] * 2 + ["S"] * 2))
    for i in range(1, 8):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, block.ports[f"in_{i}"])
    for i in range(1, 5):
        fs.connect(block.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    fs.layout()
    assert _crowded(fs) == []


def _unit_classes():
    """Every built-in Unit subclass, keyed by the ``kind`` its symbols answer to."""
    from pandid import units as unit_types

    out = {}
    for name in unit_types.__all__:
        cls = getattr(unit_types, name)
        if isinstance(cls, type) and issubclass(cls, U.Unit) and cls is not U.Unit:
            out.setdefault(cls.kind, cls)
    return out


#: Every registered (kind, variant) that could be the middle of a run. Boundary
#: flags have one port and instruments carry only signals, so neither can be.
_REGISTERED = sorted(
    (kind, variant)
    for (kind, variant) in default_registry._symbols
    if kind not in ("feed", "product", "instrument")
)


@pytest.mark.parametrize("kind,variant", _REGISTERED, ids=lambda v: str(v))
def test_every_registered_symbol_is_quiet_on_a_nozzle_pinned_run(kind, variant):
    """The sweep that fixes OFFSET_BY_DESIGN, run over the whole registry rather
    than over the handful of symbols the examples happen to use.

    Each symbol is put in a run with the arithmetic done *right*: the upstream
    flag on the device's inlet and the downstream flag on the device's own
    outlet, wherever the artwork carries it. A symbol that still fires is one
    whose geometry the check cannot describe, and is either a bug in the check
    or a fitting that belongs in OFFSET_BY_DESIGN with a reason beside it.

    A device may legitimately step the run -- a pump's discharge is drawn above
    its suction -- which is why the downstream end is pinned to the outlet and
    not to the inlet's elevation. That step is real, and a *downstream unit*
    that missed it is exactly what this finding is for.
    """
    from pandid.portgeom import port_point

    cls = _unit_classes().get(kind)
    if cls is None:
        pytest.skip(f"{kind} has no built-in Unit class")
    unit = cls("U-1", variant=variant)
    ins = [n for n, p in unit.ports.items() if p.direction == "inlet" and p.role != "signal"]
    outs = [n for n, p in unit.ports.items() if p.direction == "outlet" and p.role != "signal"]
    if not ins or not outs:
        pytest.skip(f"{kind}/{variant} is not an in-line device ({ins} -> {outs})")

    fs = Flowsheet(f"{kind}-{variant}")
    fs.add(unit)
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, unit.ports[ins[0]])
    fs.connect(unit.ports[outs[0]], prod.inlet)
    feed.pin(x=60, port="outlet", y=300)
    unit.pin(x=300, port=ins[0], y=300)
    prod.pin(x=700, y=300)
    fs.layout()
    prod.pin(x=700, port="inlet", y=port_point(unit, unit.frame, outs[0])[1])
    fs.layout()
    assert _off_elevation(fs) == []


# --- a balloon nothing could place --------------------------------------------


def _unplaced(fs, **kw):
    return [i for i in fs.validate(**kw) if i.code == "instrument-unplaced"]


def _cyclic_balloons(pump_x=400, pump_y=100):
    """Two balloons hung off each other, over a run that is otherwise fine.

    ``place_attached`` resolves a host before whatever hangs on it, so a pair
    that hosts each other is a chain with no end: neither is ever placed, both
    keep ``frame = None``, and the sweep stops once a pass places nothing. That
    give-up is the silent failure this section is about.

    *pump_x*/*pump_y* put P-1 clear of T-1 or on top of it, so one builder
    serves both the finding itself and the sheet it used to blind.
    """
    fs = Flowsheet("cycle")
    tank = fs.add(U.Tank("T-1")).pin(x=100, y=100)
    pump = fs.add(U.Pump("P-1")).pin(x=pump_x, y=pump_y)
    fs.connect(tank.outlet, pump.suction)
    lt = fs.add_instrument("LT", 1, near=tank)
    lic = fs.add_instrument("LIC", 1, near=tank, display="central")
    lt.attach(lic, relation="near")
    lic.attach(lt, relation="near")
    return fs


def test_a_balloon_no_host_could_place_is_reported():
    """The give-up path used to return without a word, leaving two instruments
    on the model that appear on no sheet and in no finding."""
    fs = _cyclic_balloons()
    fs.layout()
    issues = _unplaced(fs)
    assert [i.severity for i in issues] == ["error", "error"]
    assert sorted(i.message.split()[0] for i in issues) == ["LIC-1", "LT-1"]
    # Each names the host it is waiting on, so the cycle is readable off the
    # two messages rather than guessed at.
    assert "hangs off LIC-1, which is unplaced itself" in issues[0].message
    assert "hangs off LT-1, which is unplaced itself" in issues[1].message
    # And what to do about it, the way the surrounding findings do.
    assert "LT-1.attach(<stream or unit>)" in issues[0].message


def test_an_unplaced_balloon_does_not_blind_the_rest_of_the_sheet():
    """The regression that matters. T-1 and P-1 are pinned on top of each other,
    which is a hard error; one unplaceable balloon used to take the whole
    geometric block down with it and hand back a clean bill of health."""
    fs = _cyclic_balloons(pump_x=110, pump_y=110)
    fs.layout()
    codes = [i.code for i in fs.validate()]
    assert "unit-overlap" in codes
    assert codes.count("instrument-unplaced") == 2


def test_a_sheet_that_places_its_balloons_reports_nothing_here():
    """The other half: the finding must not fire on the ordinary case, where a
    balloon hangs off a unit the ranker positions."""
    fs = Flowsheet("placed")
    tank = fs.add(U.Tank("T-1"))
    pump = fs.add(U.Pump("P-1"))
    fs.connect(tank.outlet, pump.suction)
    lt = fs.add_instrument("LT", 1, near=tank)
    fs.add_instrument("LIC", 1, near=lt, display="central")
    fs.layout()
    assert fs.unplaced_instruments == []
    assert _unplaced(fs) == []


def test_it_is_not_reported_before_layout_has_run():
    """``frame is None`` alone cannot tell "layout has not run" from "layout gave
    up", which is why the sweep records the ones it gave up on rather than
    validate() looking for frameless units. A sheet nobody has laid out yet has
    no unplaceable balloons on it, only unplaced ones."""
    fs = _cyclic_balloons()
    assert _unplaced(fs) == []


def test_a_balloon_tapping_a_line_with_an_unplaced_end_names_the_line():
    """A stream host is not placed itself; what stops it anchoring a balloon is
    an end that never was, so the message names that rather than claiming the
    line is unplaced."""
    fs = _cyclic_balloons()
    by_name = {u.name: u for u in fs.units}
    sig = fs.connect(by_name["LT-1"].sig_out, by_name["LIC-1"].sig_in, kind="electric")
    fs.add_instrument("LY", 1, sensing=sig)
    fs.layout()
    ly = [i for i in _unplaced(fs) if i.message.startswith("LY-1")]
    assert len(ly) == 1
    assert f"hangs off stream {sig.name}, which has an end nothing placed" in ly[0].message


def test_render_refuses_the_sheet_by_the_finding_and_not_the_bounding_box():
    """An error, not a warning: the renderer will not draw a frameless unit at
    all, so there is no drawing to warn about. Raising it from validate() names
    the balloon and the cure in place of a bare "lacks a frame"."""
    fs = _cyclic_balloons()
    with pytest.raises(ValueError, match="instrument-unplaced"):
        fs.to_svg()


# --- stream-name-reused ---------------------------------------------------
# Two streams answering to one name lose a stream-table column between
# them, since the table is one column per distinct name. Sharing a name
# is ordinary, though -- a run drawn in several connect() calls is one
# stream, meant to be labelled once -- so only a name *auto-numbering*
# chose is reported: nobody asked for that one, and the counter's whole
# promise is that it hands out a free one.


def _reused(fs) -> list:
    return [i for i in fs.validate() if i.code == "stream-name-reused"]


def _collided() -> Flowsheet:
    """A sheet whose explicit name sits on a number the counter reaches.

    The half of the defect numbering cannot fix: a name is free text, so
    ``S102`` on a ``stream_number_start=100`` sheet meets the third
    number however carefully the series is counted.
    """
    fs = Flowsheet("collide", stream_number_start=100)
    feeds = [fs.add(U.Feed(f"F{i}")) for i in range(3)]
    m = fs.add(U.Mixer("M-1", n_inlets=3))
    fs.connect(feeds[0].outlet, m.inlets[0], name="S102")  # the third number
    fs.connect(feeds[1].outlet, m.inlets[1])
    fs.connect(feeds[2].outlet, m.inlets[2])
    return fs


def test_a_counted_name_landing_on_a_used_one_is_reported():
    found = _reused(_collided())
    assert len(found) == 1
    assert "2 streams answer to 'S102'" in found[0].message
    assert "F2 to M-1" in found[0].message  # which run took the counted name


def test_the_reused_name_costs_a_stream_table_column():
    """The finding's whole content: the table is keyed by name, so two
    runs sharing one are tabulated as one and a column of properties is
    absent from the sheet."""
    from pandid.render.furniture import _table_streams

    fs = _collided()
    assert len(_table_streams(fs)) == len(fs.streams) - 1
    assert _reused(fs)


def test_the_collision_is_soft_so_the_sheet_still_draws():
    """Every line is drawn and the sheet reads; what was wrong with it
    was the silence. The cure is a rename only the author can choose."""
    fs = _collided()
    assert [i.severity for i in _reused(fs)] == ["warning"]
    fs.to_svg()  # does not raise


def test_a_run_drawn_in_segments_is_not_a_collision():
    """``examples/10_ethanol_pfd.py``'s S-305 spans five connect() calls
    around a reflux circuit. Its segments are one stream deliberately
    labelled once, and the equipment between them is not inline, so they
    do not even share a numbering group."""
    fs = Flowsheet("segments")
    f = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-1"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, hx.tube_in, name="S-305")
    fs.connect(hx.tube_out, p.inlet, name="S-305")
    assert len(fs._stream_groups()) == 2  # two groups, one name, no finding
    assert _reused(fs) == []


def test_one_line_number_on_two_runs_is_not_a_collision():
    """A line number is built out of components the author wrote down,
    so two runs carrying it are the author naming one line twice --
    which ``examples/11_ethanol_pid.py`` does four times."""
    fs = Flowsheet("lines")
    f = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-1"))
    p = fs.add(U.Product("P"))
    a = fs.connect(f.outlet, hx.tube_in, size=6, service="P", spec="A1A", sequence=1001)
    b = fs.connect(hx.tube_out, p.inlet, size=6, service="P", spec="A1A", sequence=1001)
    assert a.name == b.name  # same components, same line number
    assert _reused(fs) == []


def test_a_plainly_numbered_sheet_reports_nothing():
    fs = Flowsheet("plain")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, v.inlet)
    fs.connect(v.outlet, p.inlet)
    assert _reused(fs) == []


# --- boundary-flow-missing ------------------------------------------------
# ISO 10628-1:2014 4.3.2 d) makes the flow rates or quantities of ingoing
# and outgoing materials something a process flow diagram *shall* contain,
# where 4.3.3 a) leaves the flows between the process steps optional. So the
# stream table drops an internal column with nothing in it and keeps a
# boundary one (tests/test_titleblock.py), and this is the other half of
# that: an empty column kept on the sheet is a shall unmet, and a column of
# dashes is easy to read past.
#
# Only on a sheet that tabulates its other streams. One that tabulates none
# of them has not left a feed out, it has taken none of it up -- and pandid
# ships show_stream_table=False, so that is a decision above this finding's
# head rather than an author's slip.


def _missing(fs) -> list:
    return [i for i in fs.validate() if i.code == "boundary-flow-missing"]


def _partly_tabulated() -> Flowsheet:
    """A sheet that states properties on its inlet and on nothing else."""
    fs = Flowsheet("partly")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    prod = fs.add(U.Product("To Storage"))
    fs.connect(feed.outlet, pump.suction).properties = {"Flow (kg/h)": "4200"}
    fs.connect(pump.discharge, prod.inlet)
    return fs


def test_an_outgoing_line_with_nothing_on_it_is_reported():
    found = _missing(_partly_tabulated())
    assert len(found) == 1
    assert found[0].message.startswith("S2 crosses the sheet edge at To Storage")
    assert "4.3.2 d)" in found[0].message


def test_the_reported_line_is_the_column_the_table_keeps_empty():
    """The finding's whole content. Neither half is any use alone: the
    column is what the reader sees and the finding is what says why it is
    blank, so the two have to be about the same lines."""
    from pandid.render.furniture import _table_streams

    fs = _partly_tabulated()
    kept = [s.name for s in _table_streams(fs) if not s.properties]
    assert kept == [i.message.split()[0] for i in _missing(fs)] == ["S2"]


def test_an_internal_line_with_nothing_on_it_is_not_reported():
    """4.3.3 a) leaves it optional, so its column is dropped instead --
    there is no clause to hold the sheet to and nothing to tell the author."""
    fs = Flowsheet("internal")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("To Storage"))
    fs.connect(feed.outlet, pump.suction).properties = {"Flow (kg/h)": "4200"}
    fs.connect(pump.discharge, hx.tube_in)  # internal, and nothing on it
    fs.connect(hx.tube_out, prod.inlet).properties = {"Flow (kg/h)": "4200"}
    assert _missing(fs) == []


def test_a_sheet_that_tabulates_nothing_is_not_reported():
    """The narrowness that keeps this off fourteen of the twenty shipped
    examples. A sheet with no property on any stream has not omitted one
    line's flow, it has recorded none of them, and pandid's own
    show_stream_table=False is half of that decision."""
    fs = _partly_tabulated()
    fs.streams[0].properties = {}
    assert _missing(fs) == []


def test_a_value_present_and_blank_is_a_report():
    """The escape hatch the table honours, honoured here too: an empty
    string is the author saying this line has nothing to report, which is a
    report. An absent key is silence, which is what this finding is about."""
    fs = _partly_tabulated()
    fs.streams[1].properties = {"Flow (kg/h)": ""}
    assert _missing(fs) == []


def test_the_finding_is_soft_so_the_sheet_still_draws():
    """The column is drawn and the line is named on it; what is missing is
    a number only the author has."""
    fs = _partly_tabulated()
    assert [i.severity for i in _missing(fs)] == ["warning"]
    fs.to_svg(show_stream_table=True)  # does not raise


# --- the model is checked before any geometry is built ------------------------
# A render used to lay out and route first and validate the result, so a
# sheet the validator would refuse outright was handed to the engine
# anyway. ``pin(x=nan)`` is the case that shows it: `pin-not-finite` names
# the contradiction exactly, and the same coordinate is one the router
# starts from and does not come back from, so the finding was made about a
# drawing nobody could obtain.
#
# Every test below therefore runs with `no_geometry` in place. Without it a
# regression would not fail this file, it would hang it.


class _GeometryRan(AssertionError):
    """Raised in place of layout or routing, so a test can prove neither ran."""


@pytest.fixture
def no_geometry(monkeypatch):
    """Make ``layout()`` and ``route()`` fail loudly instead of running.

    The guard these tests need, and the assertion they make. A model-only
    error has to be raised before either is called, so replacing both with
    a raise turns "the check came too late" from an open-ended wait into an
    immediate, named failure -- and turns "the check came first" into an
    ordinary ``pytest.raises(ValueError)`` that never touches the router.
    """

    def refuse(self, *args, **kwargs):
        raise _GeometryRan("layout/route ran before the model was checked")

    monkeypatch.setattr(Flowsheet, "layout", refuse)
    monkeypatch.setattr(Flowsheet, "route", refuse)


def _off_sheet(value=float("nan"), axis="x"):
    """A three-unit run whose middle unit is pinned at *value* on *axis*."""
    fs = Flowsheet("not-finite")
    f = fs.add(U.Feed("F")).pin(x=60, y=100)
    hx = fs.add(U.HeatExchanger("E-101")).pin(**{axis: value, "y" if axis == "x" else "x": 100})
    p = fs.add(U.Product("P")).pin(x=600, y=100)
    fs.connect(f.outlet, hx.tube_in)
    fs.connect(hx.tube_out, p.inlet)
    return fs


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_a_pin_that_is_not_a_number_is_an_error(value, axis):
    """`pin-not-finite` itself, on both axes and all three non-numbers.

    ``-inf`` is deliberately here beside ``nan``: it is also negative, and
    the finding must be that it is not finite rather than that it is off
    the left edge, since ``pin-out-of-bounds`` would tell the author to
    move it somewhere it cannot be moved to.
    """
    issues = [i for i in _off_sheet(value, axis).validate() if i.code == "pin-not-finite"]
    assert [i.severity for i in issues] == ["error"]
    assert f"E-101 pinned {axis}={value!r} is not a finite number" == issues[0].message


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_to_svg_refuses_a_pin_that_is_not_a_number(no_geometry, value):
    with pytest.raises(ValueError, match="pin-not-finite"):
        _off_sheet(value).to_svg()


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_to_drawio_refuses_a_pin_that_is_not_a_number(no_geometry, value):
    with pytest.raises(ValueError, match="pin-not-finite"):
        _off_sheet(value).to_drawio()


@pytest.mark.parametrize("suffix", [".svg", ".drawio"])
def test_render_to_a_file_refuses_a_pin_that_is_not_a_number(no_geometry, tmp_path, suffix):
    """Both branches of ``render()``: the sheet backends and the model one."""
    out = tmp_path / f"sheet{suffix}"
    with pytest.raises(ValueError, match="pin-not-finite"):
        _off_sheet().render(out)
    assert not out.exists()  # nothing half-written


def test_the_model_error_is_the_one_reported(no_geometry):
    """A sheet wrong in both halves is refused for the model half.

    T-1 and P-1 sit on top of each other, which is ``unit-overlap`` -- a
    finding that needs frames. The message must name the pin and not the
    overlap, because the overlap has not been looked for: this is the
    assertion that the model check happens *first* rather than merely
    happening.
    """
    fs = Flowsheet("both")
    a = fs.add(U.Tank("T-1")).pin(x=float("nan"), y=100)
    b = fs.add(U.Pump("P-1")).pin(x=100, y=100)
    fs.add(U.Tank("T-2")).pin(x=100, y=100)
    fs.connect(a.outlet, b.suction)
    with pytest.raises(ValueError) as caught:
        fs.to_svg()
    assert "pin-not-finite" in str(caught.value)
    assert "unit-overlap" not in str(caught.value)


def test_check_false_skips_the_model_check_too(no_geometry):
    """``check=False`` still means *no* validation, not "the late half only".

    With the geometry guard in place the proof is which exception comes
    out: reaching layout at all says the model check was skipped, where a
    ``ValueError`` would say it had quietly become unconditional.
    """
    with pytest.raises(_GeometryRan):
        _off_sheet().to_svg(check=False)


def test_a_sound_model_still_reaches_the_geometry(no_geometry):
    """The other half: the pre-flight refuses a sheet, it does not stop one.

    A clean model must pass through the model check and go on to lay out,
    so this asserts the guard fires rather than a ``ValueError``.
    """
    fs = Flowsheet("clean")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    with pytest.raises(_GeometryRan):
        fs.to_svg()


def test_the_two_halves_are_the_whole_of_validate():
    """``validate()`` is still every finding, and still errors first.

    The split is an order, not a subset: nothing may fall between the two
    functions, and a caller who asks the sheet what is wrong with it gets
    the same list as before.
    """
    from pandid.validate import geometry_issues, model_issues, validate

    fs = _cyclic_balloons(pump_x=110, pump_y=110)  # overlap, and two loose balloons
    fs.layout()
    whole = validate(fs)
    halves = model_issues(fs) + geometry_issues(fs)
    assert sorted(str(i) for i in whole) == sorted(str(i) for i in halves)
    assert [i.severity for i in whole] == sorted(
        (i.severity for i in whole), key=lambda s: s != "error"
    )


def test_warnings_from_both_halves_land_on_the_sheet_together():
    """``fs.warnings`` is one sheet's findings, not one phase's.

    ``letter-sequence`` is made by the model half and ``route-detour`` by
    the geometric one, so a render that collected only the second list
    would drop half the findings on the floor.
    """
    fs = Flowsheet("warnings")
    f = fs.add(U.Feed("F")).pin(x=60, y=100)
    p = fs.add(U.Product("P")).pin(x=400, y=100)
    fs.connect(f.outlet, p.inlet)
    fs.add_instrument("FCI", 1, near=f)  # I, then C: out of ISO 15519-2 order
    fs.to_svg()
    assert "letter-sequence" in [w.code for w in fs.warnings]
    assert all(w.severity == "warning" for w in fs.warnings)


# --- a run drawn on the slant -------------------------------------------------


def _hand_routed(*waypoints):
    """A pump discharge routed through hand-written points."""
    fs = Flowsheet("via")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    q = fs.add(U.Product("Q"))
    fs.connect(f.outlet, p.suction)
    run = fs.connect(p.discharge, q.inlet).via(list(waypoints))
    fs.layout()
    fs.route()
    return fs, run


def test_a_single_via_waypoint_that_squares_nothing_up_is_reported():
    """`via()` states the middle of the path and nothing squares the ends
    against it, so one point off the axis of both nozzles leaves a diagonal.
    `tests/test_route_invariants` holds the shipped corpus orthogonal; an author
    drawing their own sheet had nothing watching at all."""
    from pandid.layout.attach import stream_path

    fs, run = _hand_routed((300.0, 200.0))
    assert stream_path(run) == [(300.0, 60.0), (300.0, 200.0), (400.0, 60.0)]
    (found,) = [i for i in fs.validate() if i.code == "route-diagonal"]
    assert found.severity == "warning"
    assert "(300, 200) to (400, 60)" in found.message
    # The corner it turns at, and only the one that is not already on the path:
    # turning at the source doubles the line back on itself.
    assert "Add the corner it turns at, (400, 200)" in found.message


def test_the_corner_it_names_is_the_cure():
    fs, _ = _hand_routed((300.0, 200.0), (400.0, 200.0))
    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_neither_route_finding_beside_it_can_see_a_diagonal():
    """`route-detour` measures Manhattan length, which a diagonal and the elbow
    replacing it share exactly, and `_seg_crosses_box` answers `False` for a
    sloping segment whatever it runs over. So the finding could not be left to
    either of them."""
    from pandid.validate import _seg_crosses_box

    def detour(fs):
        return next(i for i in fs.validate() if i.code == "route-detour").message

    assert detour(_hand_routed((300.0, 200.0))[0]) == detour(
        _hand_routed((300.0, 200.0), (400.0, 200.0))[0]
    )
    assert not _seg_crosses_box(0, 0, 100, 100, (10, 10, 90, 90))
    assert _seg_crosses_box(50, 0, 50, 100, (10, 10, 90, 90))


# --- what the sheet drew but nothing said -------------------------------------


def test_a_label_side_nothing_places_is_refused_rather_than_topped():
    """A misspelt ``label_pos`` used to mean "top" and mean it silently.

    Two defects in one: the tag went to the wrong side, and a stated side is
    read as deliberate, so ``_tag_item`` skipped the search that steps a tag
    clear of the ink under it and nailed the typo where it landed.
    """
    fs = Flowsheet("botom")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1", label_pos="botom"))
    q = fs.add(U.Product("Q"))
    fs.connect(f.outlet, p.suction)
    fs.connect(p.discharge, q.inlet)
    with pytest.raises(ValueError, match="label-pos-unknown") as raised:
        fs.to_svg()
    assert "did you mean 'bottom'?" in str(raised.value)
    assert "top, bottom, right, left, center" in str(raised.value)


def test_the_label_sides_that_do_place_are_not_accused():
    """Including ``center``, which no free face ever answers with: a symbol
    asks for it or an author does, and it is drawn either way."""
    from pandid.render.svg import LABEL_POSITIONS

    for side in (*LABEL_POSITIONS, None, ""):
        fs = Flowsheet("sides")
        fs.add(U.Pump("P-1", label_pos=side))
        assert [i.code for i in fs.validate()] == [], side


def test_a_label_side_is_refused_before_anything_is_laid_out():
    """A model finding, and hard: the side is the author's and needs no
    geometry, and a render that reached the router would have drawn the wrong
    sheet before anything could say so."""
    from pandid.validate import model_issues

    fs = Flowsheet("early")
    fs.add(U.Pump("P-1", label_pos="centre"))
    assert all(u.frame is None for u in fs.units)
    found = model_issues(fs)
    assert [(i.severity, i.code) for i in found] == [("error", "label-pos-unknown")]
    assert "did you mean 'center'?" in found[0].message


def test_a_kind_with_no_artwork_is_named_rather_than_drawn_blank():
    """Two spellings of one mistake were handled oppositely.

    An unregistered *variant* of a registered kind raises and names the
    catalogue; the same typo one key up drew an empty 60x60 box with no ports,
    under an id that looks like the author's symbol, and said nothing.
    """

    class Widget(U.Unit):
        kind = "pumpp"

    fs = Flowsheet("blank")
    fs.add(Widget("X-1"))
    fs.add(Widget("X-2"))
    fs.to_svg()
    found = [w for w in fs.warnings if w.code == "symbol-kind-unknown"]
    # One per kind, not one per unit: two Widgets are one thing to fix.
    assert len(found) == 1
    assert "X-1" in found[0].message
    assert "'pumpp'" in found[0].message
    assert "did you mean 'pump'?" in found[0].message
    assert "60x60" in found[0].message

    # ...and the registered kinds are not accused of anything.
    clean = Flowsheet("clean-kinds")
    f = clean.add(U.Feed("F"))
    p = clean.add(U.Product("P"))
    clean.connect(f.outlet, p.inlet)
    clean.to_svg()
    assert "symbol-kind-unknown" not in [w.code for w in clean.warnings]


def test_a_block_letters_its_name_out_of_a_box_it_was_given():
    """A width the author set wins outright, so the name overflows it.

    ``block_symbol`` widens a box it sizes itself, so this can only reach a
    block given a ``width`` of its own -- and a section name centred on a
    120-wide box hangs a long way out of each side of it, silently.
    """
    fs = Flowsheet("bfd")
    a = fs.add(U.Block("Fermentation and Beer Stripping Section", width=120))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    found = [w for w in fs.warnings if w.code == "label-overruns-symbol"]
    assert len(found) == 1
    assert "Fermentation and Beer Stripping Section" in found[0].message
    assert "120" in found[0].message


def test_a_block_that_sizes_itself_always_fits_its_name():
    """The other half of the rule, so the check cannot be firing on everything."""
    fs = Flowsheet("bfd-auto")
    a = fs.add(U.Block("Fermentation and Beer Stripping Section"))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    assert "label-overruns-symbol" not in [w.code for w in fs.warnings]


def test_warnings_describe_the_last_render_and_nothing_earlier():
    """``fs.warnings`` was only ever *assigned* inside ``if check:``.

    So after a ``check=False`` render it still held the previous render's
    findings, and a caller could not tell a stale list from an empty one.
    """
    fs = Flowsheet("stale")
    f = fs.add(U.Feed("F")).pin(x=60, y=100)
    p = fs.add(U.Product("P")).pin(x=400, y=100)
    fs.connect(f.outlet, p.inlet)
    fs.add_instrument("FCI", 1, near=f)  # out of ISO 15519-2 order

    fs.to_svg()
    assert "letter-sequence" in [w.code for w in fs.warnings]
    # A caller who wants two renders' findings keeps them; the sheet does not.
    kept = list(fs.warnings)

    fs.to_svg(check=False)
    assert fs.warnings == []
    assert kept, "the copy is the caller's, and is untouched by the next render"

    # ...and a checked render fills it again rather than appending to a list
    # that has been growing since the first one.
    fs.to_svg()
    fs.to_svg()
    assert [w.code for w in fs.warnings].count("letter-sequence") == 1


# --- a round mark drawn as an oval ---------------------------------------------


def _out_of_aspect(fs) -> list:
    return [i for i in fs.validate() if i.code == "symbol-out-of-aspect"]


def _sized(name="R-1", **kw) -> Flowsheet:
    fs = Flowsheet("aspect")
    fs.add(U.Reactor(name, **kw))
    return fs


def test_the_box_that_shipped_a_seventy_percent_stretch_is_reported():
    """``examples/10_ethanol_pfd.py``'s M-301, as it stood.

    80 x 100 was right when a stirred reactor's box was 62 x 100. Composing
    ISO item 20.6's motor above the crown took the box to 62 x 131,8 and left
    the number behind, and nothing said so: the sheet scaled the artwork x1,29
    across and x0,76 down and drew the motor as a flat oval.
    """
    found = _out_of_aspect(_sized("M-301", n_feeds=2, width=80, height=100))
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert "M-301" in found[0].message
    assert "80x100" in found[0].message and "62x131.778" in found[0].message
    assert "70% out of shape" in found[0].message
    # The part is named by the row of Table 2 it claims to be, and the cure is
    # the width that goes with the height the author asked for.
    assert "ISO item 20.6 C0082" in found[0].message
    assert "M-301.width = 47.05" in found[0].message


def test_the_width_the_message_offers_is_the_one_that_silences_it():
    """The arithmetic in the message, checked rather than asserted in prose."""
    fs = _sized("M-301", n_feeds=2, width=80, height=100)
    sym = default_registry.for_unit(fs.units[0])
    fixed = _sized("M-301", n_feeds=2, width=sym.width / sym.height * 100, height=100)
    assert _out_of_aspect(fixed) == []


@pytest.mark.parametrize("width,height", [(None, None), (72, 153), (124, 264), (36, 76.5)])
def test_a_box_of_the_symbols_own_shape_is_quiet(width, height):
    """At the artwork's own aspect, at any size, and unsized at all."""
    kw = {k: v for k, v in (("width", width), ("height", height)) if v is not None}
    assert _out_of_aspect(_sized("M-301", n_feeds=2, **kw)) == []


def test_a_quarter_turn_is_not_a_stretch():
    """``FA-601`` reads 334 % against the symbol's box and is a rotation.

    ``resolve_size`` swaps the symbol's own box for a quarter turn, so a
    12 x 25 arrestor drawn 25 x 12 is measured against 25 x 12. Checked here on
    the reactor, which is the only family the finding can reach at all -- and
    turned, which is what makes the two boxes disagree if the swap is missed.
    """
    fs = Flowsheet("turned")
    rx = fs.add(U.Reactor("R-1", n_feeds=2))
    sym = default_registry.for_unit(rx)
    rx.pin(x=100, y=100, orientation=90)
    rx.width, rx.height = sym.height, sym.width
    assert _out_of_aspect(fs) == []
    # ...and the same numbers *un*-turned are the stretch they describe.
    rx.pin(x=100, y=100, orientation=0)
    assert len(_out_of_aspect(fs)) == 1


def test_a_boundary_flag_stretched_to_hold_its_label_is_not_reported():
    """A pennant's own box is the wide one: it is sized to the text it carries.

    106 of the 127 boxes on the twenty shipped sheets that differ from a
    registered symbol's are these, and every one is the flag doing its job.
    """
    fs = Flowsheet("pennant")
    f = fs.add(U.Feed("Cooling Water Supply Header", reference="P&ID-101"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    fs.to_svg()
    assert "symbol-out-of-aspect" not in [w.code for w in fs.warnings]


def test_a_body_whose_marks_are_lines_may_be_any_shape():
    """The narrowness is the measurement; see ``ROUND_PARTS``.

    A packed bed and a trayed column are stretched hard on the shipped sheets
    and are right: a deck is a line and a shell is drawn at the proportions the
    plant has. A rule phrased as "the box is not the symbol's shape" would ask
    for a 170 x 340 amine contactor.
    """
    packed = _sized("R-301", internals="packing", width=90, height=200)
    assert _out_of_aspect(packed) == []

    fs = Flowsheet("column")
    fs.add(U.Column("T-401", internals="valve_tray", trays=20, width=110, height=340))
    assert _out_of_aspect(fs) == []


def test_the_motor_really_is_round_on_its_own_box_and_oval_off_it():
    """``ROUND_PARTS`` is a rule with no geometry behind it, so measure it.

    ``agitator_overlays`` sizes the motor's rectangle as a third of the shell's
    width by *whatever fraction of this body's height that is*. This asserts the
    consequence rather than the arithmetic: the rectangle is a square at the
    natural box, and stops being one at a box of another shape -- by exactly the
    amount the finding reports.
    """
    from pandid.render.iso_parts import agitator_overlays
    from pandid.validate import ROUND_PARTS

    for variant in ("default", "jacketed"):
        body = default_registry.get("reactor", variant)
        overlays = agitator_overlays("agitator", "reactor", variant)
        motor = next(o for o in overlays if (o.group, o.name) in ROUND_PARTS)
        # Round at the body's own box: the rectangle is a square.
        rect_w, rect_h = motor.w * body.width, motor.h * body.height
        assert rect_w == pytest.approx(rect_h, rel=1e-9)
        # ...and the composed drawing stretched into a box 30 % wider than its
        # shape draws that square 30 % wider, which is the oval.
        sym = default_registry.for_unit(U.Reactor("R-1", variant=variant))
        drawn_w, drawn_h = 1.3 * sym.width, sym.height
        stretched = (rect_w * drawn_w / sym.width) / (rect_h * drawn_h / sym.height)
        assert stretched == pytest.approx(1.3, rel=1e-9)


def test_it_answers_before_anything_is_laid_out():
    """A model finding: the box is the author's and needs no geometry.

    ``resolve_size`` is what layout sizes the frame with, so the two agree, and
    saying it early is the point -- the number is in the source and the artwork
    it no longer matches is in the library.
    """
    from pandid.validate import model_issues

    fs = _sized("M-301", n_feeds=2, width=80, height=100)
    assert all(u.frame is None for u in fs.units)
    assert [i.code for i in model_issues(fs)].count("symbol-out-of-aspect") == 1
