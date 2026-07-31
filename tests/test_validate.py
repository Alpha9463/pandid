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

    A control valve is 15 tall, so its nozzles sit 7.5 below the corner ``pin()``
    reads; a vessel takes its inlet at mid-height, 50 below. Pinning both to
    convenient corner values silently puts the two nozzles on different
    elevations, and the router draws a step into the valve and a step back out.
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
    assert "7.5px apart" in issues[0].message
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
    on five of the twelve shipped examples -- 01, 03, 05 and 10 carry a mixer at
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
