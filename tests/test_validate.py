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
    lic = fs.add(U.Instrument("LIC-101", variant="panel")).pin(x=300, y=520)
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
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
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
    lic = fs.add_instrument("LIC", 101, on=drum, at="S", offset=90, variant="panel")
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
        # The false positives, one per family, taken from what the fourteen shipped
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
    ],
)
def test_a_nozzle_the_class_declares_is_never_counted(build, bare):
    """252 ports carry no stream across the fourteen shipped examples and every
    one of them is one of these. The drain valve is the plainest: "a drain runs
    down to a funnel on the floor, which is not on this sheet, so the leg ends
    at the valve", in ``add_valve_station``'s own words, and its outlet is bare
    eight times on ``11_ethanol_pid`` alone."""
    fs = Flowsheet("declared")
    unit = build(fs)
    assert unit.ports[bare].stream is None
    assert _unpiped(fs) == []


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
    """The acceptance test, over the drawings this package stands behind. 36
    counted nozzles across eight of the shipped sheets, and every one of them
    piped -- so the rule is exercised by the corpus rather than merely silent on
    it. The thirty-sixth is ``14_tank_farm``'s two-inlet blend tee."""
    from tests.test_golden import SCENARIOS

    offenders, counted = [], 0
    for name, (build, kwargs) in SCENARIOS.items():
        fs = build()
        fs.to_svg(**kwargs)
        counted += sum(_family_members(u) for u in fs.units)
        offenders += [f"{name}: {w.message}" for w in fs.warnings if w.code == "nozzle-unconnected"]
    assert offenders == []
    assert counted == 36


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
    on five of the fourteen shipped examples -- 01, 03, 05 and 10 carry a mixer at
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
